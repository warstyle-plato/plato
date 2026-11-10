"""Closed source evidence without parsers, calculations, refresh or data writes."""
import base64
import builtins
import datetime as dt
import hashlib
import json
import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

import main as wrapper
import developaid_monitor as monitor
import developaid_actuals as actuals
import developaid_cached_source_audit as audit

core=wrapper.core
KEY='cached-audit-owner-key'
NOW=dt.datetime(2026,11,10,9,tzinfo=dt.timezone.utc)
RUNTIME={'commit':'a'*40,'version':'0.28.93'}
FINANCE='/monitor/audit/sources'
KRT='/auctions/krt/audit/cached'


def write(root,name,value):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode())
    return path


@pytest.fixture
def source(tmp_path,monkeypatch):
    root=tmp_path/'monitor';root.mkdir()
    project='Учебный проект';slug=monitor._slug(project);folder=root/slug
    fm=b'original accepted financial workbook bytes\x00\xff'
    bank=b'original bank RSS workbook with payments inside\x00\xfe'
    write(folder,'baseline/finance.xlsx',fm)
    write(folder,'baseline/finance_meta.json',{'file_name':'fm.xlsx','uploaded_at':'2026-11-10T07:00:00Z','taken_at':'2026-10-01'})
    write(folder,'estimate/2026-10-01.xlsx',b'older bank snapshot')
    write(folder,'estimate/2026-11-06.xlsx',bank)
    write(folder,'estimate/2026-11-06.json',{'filename':'bank.xlsx','loaded_at':'2026-11-10T08:00:00Z',
        'taken_at':'2026-11-06','bytes':len(bank),'token':'CANARY-METADATA-TOKEN'})
    write(folder,'estimate/2026-12-01.xlsx',b'future bank snapshot')
    monkeypatch.setattr(audit,'ACCEPTED_FINANCE_SHA256',hashlib.sha256(fm).hexdigest())
    return root,project,folder,fm,bank


def capture(source,cut='2026-11-10'):
    root,project,*_=source
    return audit.capture_finance(root,runtime=RUNTIME,project=project,cut=cut,
        slug_function=monitor._slug,now=NOW)


def test_only_accepted_fm_and_latest_bank_rss_are_copied_without_modification(source):
    root,project,folder,fm,bank=source
    before={str(p.relative_to(root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    result=capture(source)
    after={str(p.relative_to(root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert before==after
    by_slot={r['slot']:r for r in result['files']}
    assert set(by_slot)=={'finance','finance_meta','bank_rss','bank_rss_meta'}
    assert base64.b64decode(by_slot['finance']['content_base64'])==fm
    assert base64.b64decode(by_slot['bank_rss']['content_base64'])==bank
    assert result['bank_rss_date']=='2026-11-06' and result['gaps']==[]
    assert result['paid_through_date'] is None and result['paid_through_not_inferred_from_upload_or_filename']
    assert 'CANARY-METADATA-TOKEN' not in json.dumps(result)
    assert result['coherent'] and not result['financial_acceptance'] and not result['source_files_written']
    assert not (folder/'.parsed').exists()


def test_actual_existing_alias_namespace_is_used(source):
    root,project,folder,*_=source
    canonical=root/'canonical';folder.rename(canonical)
    write(root,'.aliases.json',{'aliases':{monitor._slug(project):'canonical'}})
    result=capture(source)
    assert result['namespace']=='canonical' and result['identity']['aliases_sha256']
    assert not folder.exists()


@pytest.mark.parametrize('target',['../outside','/etc','alias/child','..',''])
def test_unsafe_alias_never_opens_another_namespace(source,target):
    root,project,*_=source
    write(root,'.aliases.json',{'aliases':{monitor._slug(project):target}})
    with pytest.raises(audit.AuditError,match='unsafe_project_identity'):capture(source)


def test_alias_chain_is_not_guessed(source):
    root,project,*_=source
    write(root,'.aliases.json',{'aliases':{monitor._slug(project):'alias','alias':'canonical'}})
    with pytest.raises(audit.AuditError,match='alias_chain'):capture(source)


def test_unknown_project_is_not_created(source):
    root,*_=source
    with pytest.raises(audit.AuditError):
        audit.capture_finance(root,runtime=RUNTIME,project='Не существующий',cut='2026-11-10',
            slug_function=monitor._slug,now=NOW)
    assert not (root/monitor._slug('Не существующий')).exists()


@pytest.mark.parametrize('cut',['2026-02-31','2026-11-11','2026-1-01','../2026-01-01'])
def test_invalid_or_future_cut_fails_before_source_io(source,cut,monkeypatch):
    monkeypatch.setattr(audit.Reader,'__init__',lambda *a,**k:pytest.fail('reader before cut validation'))
    with pytest.raises(audit.AuditError):capture(source,cut)


def test_finance_source_mismatch_is_exported_as_a_gap_not_as_accepted(source,monkeypatch):
    monkeypatch.setattr(audit,'ACCEPTED_FINANCE_SHA256','f'*64)
    result=capture(source)
    assert 'accepted_finance_source_mismatch' in result['gaps']
    assert any(r['slot']=='finance' and r.get('content_base64') for r in result['files'])
    assert not result['financial_acceptance']


def test_missing_fm_meta_and_rss_meta_are_explicit_gaps(source):
    _,_,folder,*_=source
    (folder/'baseline/finance_meta.json').unlink();(folder/'estimate/2026-11-06.json').unlink()
    result=capture(source)
    assert {'finance_meta_missing','bank_rss_meta_missing'}<=set(result['gaps'])
    assert any(r['slot']=='bank_rss' for r in result['files'])


def test_no_cross_bdds_or_payment_bridge_is_required_or_read(source):
    _,_,folder,*_=source
    write(folder,'bdds/auth.json',b'CANARY-BDDS-NOT-A-SOURCE')
    write(folder,'funding_schedule/auth.json',b'CANARY-FUNDING-NOT-A-SOURCE')
    result=capture(source)
    assert not result['gaps']
    assert 'CANARY-' not in json.dumps(result)


def test_historical_fm_support_uses_taken_at_not_upload_date(source):
    _,_,folder,*_=source
    meta=folder/'baseline/finance_meta.json'
    value=json.loads(meta.read_text());value['taken_at']='2026-11-09';write(folder,'baseline/finance_meta.json',value)
    result=capture(source,cut='2026-11-06')
    assert 'finance_not_supported_at_cut' in result['gaps']


def test_oversized_source_is_a_size_failure_not_missing_data(source,monkeypatch):
    monkeypatch.setattr(audit,'MAX_FINANCE_RAW_BYTES',8)
    with pytest.raises(audit.AuditError,match='source_size_limit'):capture(source)


def test_new_eligible_rss_during_capture_is_not_mixed(source,monkeypatch):
    _,_,folder,*_=source;real=audit._estimate_members;calls=0
    def change(reader):
        nonlocal calls
        calls+=1
        if calls==2:write(folder,'estimate/2026-11-07.xlsx',b'new bank snapshot')
        return real(reader)
    monkeypatch.setattr(audit,'_estimate_members',change)
    with pytest.raises(audit.AuditError,match='snapshot_changed'):capture(source)


def test_future_upload_does_not_change_the_supported_historical_source(source,monkeypatch):
    _,_,folder,*_=source;real=audit._estimate_members;calls=0
    def change(reader):
        nonlocal calls
        calls+=1
        if calls==2:write(folder,'estimate/2027-01-01.xlsx',b'future snapshot')
        return real(reader)
    monkeypatch.setattr(audit,'_estimate_members',change)
    assert capture(source)['bank_rss_date']=='2026-11-06'


def test_malformed_existing_xlsx_date_is_not_silently_sorted(source):
    _,_,folder,*_=source;write(folder,'estimate/2026-02-31.xlsx',b'invalid date')
    with pytest.raises(audit.AuditError,match='invalid_estimate_name'):capture(source)


def test_krt_replay_keeps_real_structured_financial_values_but_not_prompts(tmp_path):
    write(tmp_path,'ranking.json',{'schema_version':1,'rows':[{'slug':'running-site',
        'investment_rating':{'available':True,'score':31.4,'prompt':'CANARY-RATING-PROMPT'}}]})
    write(tmp_path,'reports/running-site.json',{'schema_version':1,'slug':'running-site','computed_at':123,
        'screening':{'available':True,'metrics':{'llcr':1.21,'api_key':'CANARY-API-KEY'},
            'model_inputs':{'inputs':{'land_price_mln':123.45,'credentials':{'password':'CANARY-PASS'}}},
            'text':'CANARY-RAW-NARRATIVE','system_prompt':'CANARY-SYSTEM-PROMPT'}})
    result=audit.capture_krt(tmp_path,runtime=RUNTIME,now=NOW,purpose='krt_cached_replay_v1')
    report=next(r['projection'] for r in result['files'] if r['logical_path'].endswith('running-site.json'))
    structured=report['structured_blocks']['screening']
    assert structured['metrics']=={'llcr':1.21}
    assert structured['model_inputs']=={'inputs':{'land_price_mln':123.45}}
    assert 'CANARY-' not in json.dumps(result)
    assert not result['production_acceptance']
    metadata=audit.capture_krt(tmp_path,runtime=RUNTIME,now=NOW,purpose='krt_cached_metadata_v1')
    assert all('structured_blocks' not in r['projection'] for r in metadata['files'])


@pytest.fixture
def client(monkeypatch):
    from auction_search.api import install
    app=FastAPI()
    # Install real routes in a private app. Installing auctions onto core.app
    # before main_registry imports would capture its market service too early.
    install(app)
    endpoint=next(r.endpoint for r in core.app.routes if getattr(r,'path',None)==FINANCE)
    app.add_api_route(FINANCE,endpoint,methods=['POST'])
    monkeypatch.setattr(audit,'_utc_now',lambda:NOW)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    monkeypatch.setattr(core,'usage_admin_ids',lambda:[777])
    monkeypatch.setattr(core,'COMMIT',RUNTIME['commit'])
    return TestClient(app,raise_server_exceptions=False)


@pytest.mark.parametrize('path',[FINANCE,KRT])
@pytest.mark.parametrize('body',[
    {'key':'wrong','purpose':'wrong','cut':'not-a-date'},
    {'key':'','project':'../../etc','root':'/etc'},
    {'key':'','session':'invalid-owner-session','purpose':'krt_cached_metadata_v1'},
])
def test_access_denied_before_collector_import_or_io(client,monkeypatch,path,body):
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name=='developaid_cached_source_audit':pytest.fail('collector imported before admission')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    answer=client.post(path,json=body,headers={'X-Market-Key':'not-owner'})
    assert answer.status_code==403 and answer.headers['cache-control']=='private, no-store'


def test_monitor_endpoint_uses_real_gate_and_raw_sources_without_parsers(client,source,monkeypatch):
    root,project,*_=source
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',root)
    def no_parser(*args,**kwargs):pytest.fail('product parser/store/resolver called')
    for name in ['_project_dir','finance_baseline_meta','_latest','_aliases']:
        monkeypatch.setattr(monitor,name,no_parser)
    for name in ['read_estimate','read_payments','read_contracts']:
        monkeypatch.setattr(actuals,name,no_parser)
    answer=client.post(FINANCE,json={'key':KEY,'purpose':'finance_sources_v1','project':project,'cut':'2026-11-10'})
    assert answer.status_code==200,answer.text[:200]
    assert answer.json()['bank_rss_date']=='2026-11-06'
    assert answer.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('path',[FINANCE,KRT])
def test_missing_owner_configuration_does_not_fail_open(client,monkeypatch,path):
    monkeypatch.delenv('DEVELOPAID_ADMIN_KEY',raising=False)
    monkeypatch.setattr(core,'usage_admin_ids',lambda:[])
    answer=client.post(path,json={'key':KEY,'purpose':'krt_cached_metadata_v1'})
    assert answer.status_code==403 and answer.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('path,purpose',[(FINANCE,'finance_sources_v1'),(KRT,'krt_cached_metadata_v1')])
def test_authorized_arbitrary_file_selectors_are_rejected_before_io(client,monkeypatch,path,purpose):
    monkeypatch.setattr(audit.Reader,'__init__',lambda *a,**k:pytest.fail('reader before strict request validation'))
    answer=client.post(path,json={'key':KEY,'purpose':purpose,'project':'Учебный','cut':'2026-11-10','root':'/etc','path':'auth.json'})
    assert answer.status_code==400 and answer.headers['cache-control']=='private, no-store'


def test_krt_handler_does_not_call_refresh_or_models(client,monkeypatch):
    calls=[]
    def capture(root,**kwargs):
        assert root.is_absolute()
        calls.append((root,kwargs));return {'reads_only':True,'purpose':kwargs['purpose']}
    monkeypatch.setattr(audit,'capture_krt',capture)
    answer=client.post(KRT,json={'key':KEY,'purpose':'krt_cached_metadata_v1'})
    assert answer.status_code==200 and answer.json()['reads_only']
    assert len(calls)==1 and calls[0][1]['runtime']['commit']==RUNTIME['commit']
    assert answer.headers['cache-control']=='private, no-store'


def test_replay_scrubs_camelcase_credential_fields_without_fake_model_values():
    original={'metrics':{'llcr':1.23,'apiKey':'CANARY1','authToken':'CANARY2'},
              'model_inputs':{'inputs':{'land_price_mln':100,'privateKey':'CANARY3'}},
              'myPrompt':'CANARY4','authorizationHeader':'CANARY5'}
    scrubbed=audit._scrub(original)
    assert scrubbed['metrics']=={'llcr':1.23}
    assert scrubbed['model_inputs']['inputs']=={'land_price_mln':100}
    assert 'CANARY' not in json.dumps(scrubbed)


@pytest.mark.parametrize('path',[FINANCE,KRT])
def test_private_posts_do_not_touch_market_admission_before_owner_gate(client,monkeypatch,path):
    from auction_search import access_keys
    from market_search import cabinet as market_cabinet
    def forbidden(*args,**kwargs):pytest.fail('market registry or admission before private owner gate')
    monkeypatch.setattr(access_keys,'has_cookie',forbidden)
    monkeypatch.setattr(market_cabinet,'authorised',forbidden)
    # A refused Monitor key is classified by the existing gate for logging.
    # With a valid owner key, no market admission or registry is needed at all.
    answer=client.post(path,json={'key':KEY,'purpose':'wrong'})
    assert answer.status_code==400 and answer.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('path',[FINANCE,KRT])
@pytest.mark.parametrize('raw',[b'{',b'[]',b'{"key":1}',b'{"key":"wrong","key":"another"}',b'{"purpose":NaN}',b'x'*16385])
def test_malformed_private_requests_never_leak_or_cache(client,path,raw):
    answer=client.post(path,content=raw,headers={'X-Developaid-Admin-Key':KEY})
    assert answer.status_code in {400,403,413}
    assert answer.headers['cache-control']=='private, no-store'
    assert KEY not in answer.text


@pytest.mark.parametrize('path,purpose',[(FINANCE,'finance_sources_v1'),(KRT,'krt_cached_metadata_v1')])
@pytest.mark.parametrize('code,status',[('source_size_limit',413),('snapshot_changed',409),('invalid_json',400)])
def test_capture_errors_are_fixed_codes_and_no_store(client,monkeypatch,path,purpose,code,status):
    def failed(*args,**kwargs):raise audit.AuditError(code)
    monkeypatch.setattr(audit,'capture_finance' if path==FINANCE else 'capture_krt',failed)
    body={'key':KEY,'purpose':purpose}
    if path==FINANCE:body.update(project='Учебный',cut='2026-11-10')
    answer=client.post(path,json=body)
    assert answer.status_code==status and answer.json()['code']==code
    assert answer.headers['cache-control']=='private, no-store'


def test_real_krt_route_reads_existing_saved_files_without_refresh(client,tmp_path,monkeypatch):
    tmp_path=tmp_path/'saved-krt';tmp_path.mkdir()
    endpoint=next(r.endpoint for r in client.app.routes if getattr(r,'path',None)==KRT)
    stores=inspect.getclosurevars(endpoint).nonlocals
    monkeypatch.setattr(stores['krt_registry'],'path',tmp_path/'catalogue.json')
    monkeypatch.setattr(stores['krt_ranking'],'path',tmp_path/'ranking.json')
    write(tmp_path,'catalogue.json',{'schema_version':3,'retrieved_at':NOW.timestamp()-10,
        'complete':True,'projects':[{'slug':'existing-site','status_kind':'running'}]})
    write(tmp_path,'ranking.json',{'schema_version':1,'rows':[{'slug':'existing-site',
        'investment_rating':{'available':True,'score':13.4}}]})
    def forbidden(*args,**kwargs):pytest.fail('refresh, source read, model or cache constructor called')
    for name in ('catalogue','decisions','refresh'):
        if hasattr(stores['krt_registry'],name):monkeypatch.setattr(stores['krt_registry'],name,forbidden)
    for name in ('ranked','refresh','report','model_fingerprint'):
        if hasattr(stores['krt_ranking'],name):monkeypatch.setattr(stores['krt_ranking'],name,forbidden)
    before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    answer=client.post(KRT,json={'key':KEY,'purpose':'krt_cached_replay_v1'})
    assert answer.status_code==200,answer.text[:200]
    result=answer.json()
    catalogue=next(r['projection'] for r in result['files'] if r['logical_path']=='krt/catalogue.json')
    assert catalogue['projects'][0]['slug']=='existing-site'
    assert not result['production_acceptance'] and not result['models_or_scores_computed']
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.iterdir()}


def test_finance_limits_original_bytes_before_reading_an_oversized_file(source,monkeypatch):
    _,_,folder,*_=source
    reader=audit.Reader(folder,'finance')
    try:
        def forbidden(*args,**kwargs):pytest.fail('oversized original bytes read')
        monkeypatch.setattr(audit.os,'read',forbidden)
        with pytest.raises(audit.AuditError,match='source_size_limit'):
            reader.read('baseline/finance.xlsx',max_bytes=1)
    finally:reader.close()


def test_project_namespace_replaced_during_capture_is_rejected(source,monkeypatch):
    root,_,folder,*_=source;real=audit._estimate_members;calls=0
    def change(reader):
        nonlocal calls
        calls+=1
        if calls==2:
            folder.rename(root/'previous');folder.mkdir()
        return real(reader)
    monkeypatch.setattr(audit,'_estimate_members',change)
    with pytest.raises(audit.AuditError,match='snapshot_changed'):capture(source)
