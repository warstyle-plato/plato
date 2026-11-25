"""Same-call proof gates and final worker assertion protect the full register."""
import json
import threading
import datetime as dt

import openpyxl

import pytest

import developaid_contract_files as files
import developaid_contract_match_cache as cache
import developaid_contract_match_verify as verify
import developaid_contract_stage_profile as stages
import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_contract_stage_profile_api import admit, PROJECT, CUT
from test_monitor_cumulative_api import api, post, poll, core, KEY
from test_contracts_archive_union import grown
from test_contracts_from_cumulative_headers import archive as header_archive, ks


@pytest.mark.parametrize('value',[1,0,'true','false',None,{},[]])
def test_verify_requires_strict_boolean_before_storage(api,value):
    client,root=api
    assert admit(client,'a'*32,profile_stages=True,profile_matching_verify=value).status_code==422
    assert not (root/'monitor'/'.cumulative_jobs').exists()


@pytest.mark.parametrize('flags',[{}, {'profile_stages':False},
    {'profile_stages':True,'profile_matching_cache_off':True}])
def test_verify_only_admits_admin_stage_profile_with_normal_cache(api,monkeypatch,flags):
    client,root=api
    monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *a:pytest.fail('Invalid admission'))
    assert admit(client,'a'*32,profile_matching_verify=True,**flags).status_code==400
    assert admit(client,'a'*32,key='wrong-key',session='claimed-demo',profile_matching_verify=True,**flags).status_code==403
    assert not (root/'monitor'/'.cumulative_jobs').exists()


def test_full_native_register_and_key_order_are_equal_and_original_cache_scopes_stay_local(api,monkeypatch):
    client,root=api
    ledgers.store_archive(PROJECT,header_archive([('A.xlsx',ks()),('B.xlsx',ks(number='B-24'))]),'2026-10-01','first.zip')
    ledgers.store_archive(PROJECT,header_archive([('A.xlsx',grown())]),'2026-11-01','second.zip')
    folder=monitor._project_dir(PROJECT)/'estimate';folder.mkdir()
    workbook=openpyxl.Workbook();sheet=workbook.active;sheet.title='Реестр договоров'
    sheet.cell(1,1,'Заказчик');sheet.cell(1,2,'ООО «Заказчик»')
    for col,name in ((4,'Дата договора'),(8,'Сумма договора'),(12,'Выполнено по реестру')):sheet.cell(6,col,name)
    for row,number in enumerate(('A-12','B-24'),9):
        for col,value in ((2,'ООО «Подрядчик»'),(3,number),(4,dt.date(2026,1,1)),(8,1000),(12,900)):sheet.cell(row,col,value)
    payments=workbook.create_sheet('Реестр платежей')
    for row,(number,day,amount) in enumerate((('A-12',dt.date(2026,1,1),100),('A-12',dt.date(2026,1,1),-25),
                                            ('A-12',None,0),('B-24',dt.date(2026,1,1),0)),10):
        for col,value in ((2,'Подрядчик ООО'),(3,number),(4,day),(6,'Аванс'),(9,dt.date(2026,10,5)),(10,amount)):payments.cell(row,col,value)
    workbook.save(folder/'2026-11-01.xlsx');workbook.close()
    reports=monitor._project_dir(PROJECT)/'daily';reports.mkdir()
    report={'date':CUT,'parsed':{'contractors':[],'works':[
        {'contractor':'Подрядчик ООО (бетонирование)',
         'line':f'Корпус 1 по договору № A-12 бетонирование участок {index}'}
        for index in range(3)]}}
    (reports/(CUT+'.json')).write_text(json.dumps(report,ensure_ascii=False))
    expected=core._monitor_cumulative_execute('view',{'project':PROJECT,'cut':CUT})
    execute=core._monitor_cumulative_execute
    def observed(*args):
        assert cache._current() is None  # VERIFY adds no executor-wide cache.
        result=execute(*args)
        assert cache._current() is None
        return result
    monkeypatch.setattr(core,'_monitor_cumulative_execute',observed)
    assert admit(client,'a'*32,profile_stages=True,profile_matching_verify=True,chunked=True).status_code==202
    result=poll(client,'a'*32)
    assert result.status_code==200,result.text
    output=result.json()
    assert output['register']==expected['register']
    assert json.dumps(output['register'],ensure_ascii=False)==json.dumps(expected['register'],ensure_ascii=False)
    rows={row['contract']:row for row in output['register']['rows']}
    assert rows['A-12']['advance']['paid'] is None
    assert rows['A-12']['advance']['confirmed_paid']==75
    assert rows['A-12']['advance']['unmatched_candidates']==1
    assert rows['B-24']['advance']['paid']==0
    assert len(rows['A-12']['progress']['series'])==2
    proof=output['diagnostics']['matching_cache_verification']
    assert proof['purpose']==verify.PURPOSE and proof['state']=='all_observed_hits_verified'
    assert sum(item['verified'] for item in proof['hits'].values())>0
    assert proof['entered_scopes']==proof['exited_scopes']>0
    assert all(item['attempted']==item['verified'] for item in proof['hits'].values())
    assert set(proof['hits'])==set(verify.KINDS)
    assert all(item['verified']>0 for item in proof['hits'].values())
    meta=jobs.Store(root/'monitor'/'.cumulative_jobs')._meta('a'*32)
    assert meta['compress_result'] is True and meta['result_limit_bytes']==jobs.MAX_EXTENDED_RESULT_BYTES


@pytest.mark.parametrize('kind',verify.KINDS)
def test_native_card_broad_fallback_cannot_emit_success_after_poisoned_hit(api,monkeypatch,kind,caplog):
    client,root=api;private='SYNTHETIC_PRIVATE_POISONED_VALUE'
    monkeypatch.setattr(files.fact,'acts',lambda row:{})
    def listing(*args):
        with cache.scope() as ordinary:
            cache.remember(kind,('key',),lambda:'correct')
            ordinary.entries[(kind,('key',))]=private
            cache.remember(kind,('key',),lambda:'correct')
    monkeypatch.setattr(files,'listing',listing)
    def execute(*args):
        register=files._register_control_raw(PROJECT,{'rows':[{'id':'synthetic'}]},CUT)
        assert register['rows'][0]['schedule_control']['documents'] is None
        return {'ok':True,'register':register}  # The actual broad fallback swallowed the failure.
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    assert admit(client,'a'*32,profile_stages=True,profile_matching_verify=True).status_code==202
    response=poll(client,'a'*32)
    assert response.status_code==500 and 'diagnostics' not in response.json()
    store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    assert not store._path('a'*32,'result').exists()
    assert private not in response.text+json.dumps(store._meta('a'*32))+caplog.text


@pytest.mark.parametrize('mode',['ordinary','on','off','verify'])
def test_ticket_modes_are_bound_but_false_and_omitted_keep_old_fingerprints(api,monkeypatch,mode):
    client,root=api
    def execute(*args):
        with cache.scope():
            for _ in range(2):cache.remember('party',('same',),lambda:'value')
        return {'ok':True,'register':{'rows':[],'unknown':None,'zero':0,'refund':-25}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    flags={'ordinary':{},'on':{'profile_stages':True},
        'off':{'profile_stages':True,'profile_matching_cache_off':True},
        'verify':{'profile_stages':True,'profile_matching_verify':True}}
    assert admit(client,'a'*32,**flags[mode]).status_code==202
    expected=poll(client,'a'*32)
    assert expected.status_code==200
    assert admit(client,'a'*32,**flags[mode]).json()==expected.json()
    for other in flags:
        if other!=mode:assert admit(client,'a'*32,**flags[other]).status_code==409
    if mode!='verify':assert admit(client,'a'*32,profile_matching_verify=False,**flags[mode]).json()==expected.json()


@pytest.mark.parametrize('mode',['ordinary','on','off'])
def test_explicit_source_bound_payload_accepts_false_verify_without_rebuilding(api,monkeypatch,mode):
    client,root=api;store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    family='monitor-cumulative-v1:contracts';owner=jobs.owner_binding(KEY,'',family)
    context=ledgers.snapshot_job_context(PROJECT)
    import developaid_contract_control as control
    payload={'operation':'view','click':'a'*32,'project':PROJECT,'cut':CUT,'source_context':context,
             'contract_calculation_revision':control.CALCULATION_REVISION}
    flags={}
    if mode!='ordinary':payload['diagnostics']=stages.PURPOSE;flags['profile_stages']=True
    if mode=='off':payload['matching_cache']=cache.DISABLED_PURPOSE;flags['profile_matching_cache_off']=True
    store.start(owner,family,payload,lambda:{'ok':True,'register':{'rows':[]}},'a'*32,
                result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES,context=context)
    response=poll(client,'a'*32);assert response.status_code==200
    expected=response.json();before=store._meta('a'*32)
    monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *a:pytest.fail('Legacy ticket rebuilt'))
    for extra in ({},{'profile_matching_verify':False}):assert admit(client,'a'*32,**flags,**extra).json()==expected
    assert store._meta('a'*32)==before


def test_no_hits_is_not_a_successful_verification_proof(api,monkeypatch):
    client,root=api
    monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *a:{'ok':True,'register':{'rows':[]}})
    assert admit(client,'a'*32,profile_stages=True,profile_matching_verify=True).status_code==202
    response=poll(client,'a'*32)
    assert response.status_code==500 and 'diagnostics' not in response.json()
    assert not jobs.Store(root/'monitor'/'.cumulative_jobs')._path('a'*32,'result').exists()


@pytest.mark.parametrize('failed',[False,True])
def test_v1_verify_ticket_is_immutable_and_cannot_be_readmitted_as_v2(api,monkeypatch,failed):
    client,root=api;store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    family='monitor-cumulative-v1:contracts';owner=jobs.owner_binding(KEY,'',family)
    context=ledgers.snapshot_job_context(PROJECT)
    import developaid_contract_control as control
    payload={'operation':'view','click':'a'*32,'project':PROJECT,'cut':CUT,'source_context':context,
             'contract_calculation_revision':control.CALCULATION_REVISION,
             'diagnostics':stages.PURPOSE,'matching_cache':'contract-pure-matching-hit-verify-v1'}
    def legacy():
        if failed:raise ValueError('synthetic legacy failure')
        return {'ok':True,'register':{'rows':[]},'diagnostics':{
            'matching_cache_verification':{'purpose':'contract-pure-matching-hit-verify-v1'}}}
    store.start(owner,family,payload,legacy,'a'*32,result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES,context=context)
    expected=poll(client,'a'*32);assert expected.status_code==(500 if failed else 200)
    before=store._meta('a'*32)
    monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *a:pytest.fail('Legacy VERIFY rebuilt'))
    for flags in ({},{'profile_stages':True},{'profile_stages':True,'profile_matching_cache_off':True},
                  {'profile_stages':True,'profile_matching_verify':True}):
        assert admit(client,'a'*32,**flags).status_code==409
    assert poll(client,'a'*32).json()==expected.json()
    assert store._meta('a'*32)==before


def test_normal_and_verify_parallel_workers_keep_cache_scopes_and_counts_isolated(api,monkeypatch):
    client,_=api;barrier=threading.Barrier(2);observed=[]
    def execute(*args):
        verifying=verify._VERIFY.get() is not None
        assert cache._current() is None
        calls=[]
        with cache.scope():
            barrier.wait(timeout=10)
            for _ in range(3):cache.remember('party',('same',),lambda:calls.append(1) or 'value')
        observed.append((verifying,len(calls)))
        return {'ok':True,'register':{'rows':[]}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    assert admit(client,'a'*32,profile_stages=True,profile_matching_verify=True).status_code==202
    assert admit(client,'b'*32,profile_stages=True).status_code==202
    verified=poll(client,'a'*32).json();normal=poll(client,'b'*32).json()
    assert sorted(observed)==[(False,1),(True,3)]
    assert verified['diagnostics']['matching_cache_verification']['hits']['party']=={'attempted':2,'verified':2}
    assert 'matching_cache_verification' not in normal['diagnostics']
    assert verify._VERIFY.get() is None


def test_verify_uses_existing_owner_key_profile_and_ttl_before_result_reads(api,monkeypatch):
    client,root=api
    def execute(*args):
        with cache.scope():
            for _ in range(2):cache.remember('party',('same',),lambda:'value')
        return {'ok':True,'register':{'rows':[]}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    assert admit(client,'a'*32,key='wrong',profile_stages=True,profile_matching_verify=True).status_code==403
    assert admit(client,'a'*32,session='owner',profile_stages=True,profile_matching_verify=True).status_code==202
    assert poll(client,'a'*32,session='owner').status_code==200
    assert post(client,'contracts/result',ticket='a'*32,session='other').status_code==404
    assert post(client,'cumulative/result',ticket='a'*32,session='owner').status_code==404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','rotated-verify-key')
    assert post(client,'contracts/result',ticket='a'*32,session='owner').status_code==403
    assert post(client,'contracts/result',ticket='a'*32,session='owner',key='rotated-verify-key').status_code==404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    with store._locked():
        meta=store._meta('a'*32);meta['created']-=jobs.TTL_SECONDS+1;store._save(meta)
    assert post(client,'contracts/result',ticket='a'*32,session='owner').status_code==404
