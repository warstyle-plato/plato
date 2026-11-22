"""An admin stage-profile can bypass only the pure matching memoization."""
import concurrent.futures
import contextvars
import base64
import gzip
import json
import threading

import pytest
from fastapi.encoders import jsonable_encoder

import developaid_contract_match_cache as cache
import developaid_contract_stage_profile as stages
import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_contract_stage_profile_api import admit, PROJECT, CUT
from test_monitor_cumulative_api import api, post, poll, core, KEY
from test_monitor_cumulative_ledgers import archive, book
from test_monitor_keeps_every_snapshot import _rss_book


def test_disabled_context_bypasses_populated_outer_cache_and_all_nested_scopes():
    calls=[]
    def compute():calls.append(1);return 'same exact pure result'
    with cache.scope() as enabled:
        expected=cache.remember('party',('same',),compute)
        with pytest.raises(RuntimeError,match='synthetic'):
            with cache.disabled_scope() as disabled:
                assert disabled is not enabled
                with cache.scope() as nested, cache.disabled_scope() as repeated:
                    assert nested is repeated is disabled
                    for _ in range(3):assert cache.remember('party',('same',),compute)==expected
                assert disabled.entries=={} and disabled.bytes==0
                assert cache.disabled_proof(disabled)==dict(purpose=cache.DISABLED_PURPOSE,mode='off',bypass_calls=3)
                raise RuntimeError('synthetic')
        assert cache._current() is enabled
        assert cache.remember('party',('same',),compute)==expected
    assert len(calls)==4 and cache._current() is None
    with pytest.raises(ValueError):cache.disabled_proof(disabled)


def test_copied_context_foreign_thread_cannot_inherit_disable_or_mutate_its_count():
    with cache.disabled_scope() as disabled:
        inherited=contextvars.copy_context()
        def worker():
            with cache.scope() as enabled:
                assert enabled is not disabled and not enabled.disabled
                calls=[]
                for _ in range(2):assert cache.remember('party',('same',),lambda:calls.append(1) or 'value')=='value'
                return len(calls),enabled.owner
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            count,owner=pool.submit(inherited.run,worker).result(timeout=10)
        assert count==1 and owner is not threading.current_thread()
        assert cache._current() is disabled and disabled.bypasses==0
    assert cache._current() is None


def test_mode_proof_is_fixed_bounded_and_does_not_retain_values_or_exception_text():
    private='SYNTHETIC_PRIVATE_PATH_HASH_CELL_MONEY'
    with cache.disabled_scope() as disabled, stages.collect() as measured:
        disabled.bypasses=cache.MAX_BYPASSES-1
        for _ in range(3):assert cache.remember('reference',(private,),lambda:private)==private
        for label in stages.STAGES:measured.stages[label]=[stages.MAX_COUNT,stages.MAX_SECONDS,stages.MAX_SECONDS]
        for label in stages.COUNTERS:measured.add(label,stages.MAX_COUNT)
        output=measured.export();output['matching_cache']=cache.disabled_proof(disabled)
        raw=json.dumps(output,allow_nan=False)
        assert private not in raw and len(raw.encode())<=stages.MAX_BYTES
        assert output['matching_cache']['bypass_calls']==cache.MAX_BYPASSES
        assert not disabled.entries and disabled.bytes==0


@pytest.mark.parametrize('invalid',[1,0,'true','false',None,{},[]])
def test_off_flag_is_strict_before_any_job_or_source_admission(api,invalid):
    client,root=api
    assert admit(client,'a'*32,profile_stages=True,profile_matching_cache_off=invalid).status_code==422
    assert not (root/'monitor'/'.cumulative_jobs').exists()


@pytest.mark.parametrize('profile',[False,None])
def test_off_requires_the_fixed_profile_purpose_and_admin_gate(api,monkeypatch,profile):
    client,root=api
    monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *args:pytest.fail('invalid worker'))
    flags={'profile_matching_cache_off':True}
    if profile is not None:flags['profile_stages']=profile
    assert admit(client,'a'*32,**flags).status_code==400
    assert admit(client,'a'*32,key='wrong-key',session='claimed-demo-team',**flags).status_code==403
    assert not (root/'monitor'/'.cumulative_jobs').exists()


def _wire(value):return json.dumps(jsonable_encoder(value),ensure_ascii=False,separators=(',',':'))


def test_complete_native_direct_and_async_ordinary_on_off_registers_have_identical_key_order(api):
    client,root=api
    monitor.store_estimate(PROJECT,_rss_book(payments=[(CUT,100),(CUT,-20),(CUT,0)]),CUT)
    for day in ('2026-11-01',CUT):ledgers.store_archive(PROJECT,archive([('Works.xlsx',book())]),day,'Works.zip')
    files={p:p.read_bytes() for p in monitor._project_dir(PROJECT).rglob('*') if p.suffix in {'.zip','.xlsx','.json'}}
    direct=core._monitor_cumulative_execute('view',{'project':PROJECT,'cut':CUT})
    with cache.disabled_scope() as disabled:
        direct_off=core._monitor_cumulative_execute('view',{'project':PROJECT,'cut':CUT})
        assert disabled.bypasses>0 and not disabled.entries and disabled.bytes==0
    assert _wire(direct_off)==_wire(direct)
    outputs=[]
    for ticket,flags in [('a'*32,{}),('b'*32,{'profile_stages':True}),
                         ('c'*32,{'profile_stages':True,'profile_matching_cache_off':True,'chunked':True})]:
        assert admit(client,ticket,**flags).status_code==202
        response=poll(client,ticket);assert response.status_code==200
        outputs.append(response.json())
    normal,on,off=outputs
    for value in outputs:
        assert _wire(value['register'])==_wire(direct['register'])
    assert 'diagnostics' not in normal and 'matching_cache' not in on['diagnostics']
    assert set(off)==set(on)==set(normal)|{'diagnostics'}
    assert off['diagnostics']['matching_cache']['purpose']==cache.DISABLED_PURPOSE
    assert off['diagnostics']['matching_cache']['mode']=='off'
    assert off['diagnostics']['matching_cache']['bypass_calls']>0
    meta=jobs.Store(root/'monitor'/'.cumulative_jobs')._meta('c'*32)
    assert meta['result_limit_bytes']==jobs.MAX_EXTENDED_RESULT_BYTES and meta['compress_result'] is True
    chunk=post(client,'contracts/result-part',ticket='c'*32,offset=0,accept_gzip=True)
    assert chunk.status_code==200
    part=chunk.json()['result_part'];packed=base64.b64decode(part['content_base64'],validate=True)
    assert len(packed)==part['total_bytes'] and part['encoding']=='gzip'
    raw=gzip.decompress(packed)
    assert json.loads(raw)=={key:value for key,value in off.items() if key not in {'pending','ticket'}}
    assert len(raw)==part['json_bytes']<=jobs.MAX_EXTENDED_RESULT_BYTES
    assert all(path.read_bytes()==data for path,data in files.items())
    assert cache._current() is None and stages._ACTIVE.get() is None


@pytest.mark.parametrize('initial', ['ordinary','on','off'])
def test_three_modes_are_bound_to_ticket_but_false_keeps_legacy_fingerprints(api,monkeypatch,initial):
    client,root=api
    calls=[]
    def execute(*args):
        with cache.scope() as state:
            calls.append(state.disabled)
            for _ in range(2):cache.remember('party',('same',),lambda:'normalized')
        return {'ok':True,'register':{'rows':[],'unknown':None,'zero':0}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    flags={'ordinary':{},'on':{'profile_stages':True},'off':{'profile_stages':True,'profile_matching_cache_off':True}}
    assert admit(client,'a'*32,**flags[initial]).status_code==202
    expected=poll(client,'a'*32).json()
    assert admit(client,'a'*32,**flags[initial]).json()==expected
    for mode in flags:
        if mode!=initial:assert admit(client,'a'*32,**flags[mode]).status_code==409
    assert calls==[initial=='off']
    if initial!='off':assert admit(client,'a'*32,profile_matching_cache_off=False,**flags[initial]).json()==expected


def test_predeploy_profiled_and_ordinary_tickets_keep_their_exact_prior_payload(api,monkeypatch):
    client,root=api
    store=jobs.Store(root/'monitor'/'.cumulative_jobs');family='monitor-cumulative-v1:contracts'
    owner=jobs.owner_binding(KEY,'',family)
    for ticket,profiled in [('a'*32,False),('b'*32,True)]:
        legacy={'operation':'view','click':ticket,'project':PROJECT,'cut':CUT}
        if profiled:legacy['diagnostics']=stages.PURPOSE
        store.start(owner,family,legacy,lambda:{'ok':True,'register':{'rows':[]}},ticket,
            result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
        expected=poll(client,ticket).json();before=store._meta(ticket)
        monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *args:pytest.fail('old ticket rebuilt'))
        for false_flag in ({},{'profile_matching_cache_off':False}):
            assert admit(client,ticket,profile_stages=profiled,**false_flag).json()==expected
        assert admit(client,ticket,profile_stages=True,profile_matching_cache_off=True).status_code==409
        assert store._meta(ticket)==before


def test_counterfactual_wrong_fingerprint_purpose_and_owner_key_ttl_cannot_reuse_ticket(api,monkeypatch):
    client,root=api
    monkeypatch.setattr(core,'_monitor_cumulative_execute',lambda *args:{'ok':True,'register':{'rows':[]}})
    store=jobs.Store(root/'monitor'/'.cumulative_jobs');family='monitor-cumulative-v1:contracts'
    owner=jobs.owner_binding(KEY,'owner',family)
    wrong={'operation':'view','click':'a'*32,'project':PROJECT,'cut':CUT,'diagnostics':stages.PURPOSE,
           'matching_cache':'unrecognized-purpose'}
    store.start(owner,family,wrong,lambda:{'ok':True},'a'*32,result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
    assert admit(client,'a'*32,session='owner',profile_stages=True,profile_matching_cache_off=True).status_code==409
    assert admit(client,'b'*32,session='owner',profile_stages=True,profile_matching_cache_off=True).status_code==202
    assert poll(client,'b'*32,session='owner').status_code==200
    assert post(client,'contracts/result',ticket='b'*32,session='other').status_code==404
    assert post(client,'cumulative/result',ticket='b'*32,session='owner').status_code==404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','rotated-synthetic-key')
    assert post(client,'contracts/result',ticket='b'*32,session='owner').status_code==403
    assert post(client,'contracts/result',ticket='b'*32,session='owner',key='rotated-synthetic-key').status_code==404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    with store._locked():
        meta=store._meta('b'*32);meta['created']-=jobs.TTL_SECONDS+1;store._save(meta)
    assert post(client,'contracts/result',ticket='b'*32,session='owner').status_code==404


def test_parallel_worker_modes_are_local(api,monkeypatch):
    client,_=api
    barrier=threading.Barrier(2);observed=[]
    def execute(operation,payload,archive):
        with cache.scope() as state:
            barrier.wait(timeout=10)
            computed=[]
            for _ in range(2):cache.remember('party',('same',),lambda:computed.append(1) or 'same result')
            observed.append((state.disabled,len(computed),state.owner is threading.current_thread()))
        return {'ok':True,'register':{'rows':[]}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    assert admit(client,'a'*32,profile_stages=True,profile_matching_cache_off=True).status_code==202
    assert admit(client,'b'*32,profile_stages=True).status_code==202
    off=poll(client,'a'*32).json();on=poll(client,'b'*32).json()
    assert sorted(observed)==[(False,1,True),(True,2,True)]
    assert off['diagnostics']['matching_cache']['bypass_calls']==2 and 'matching_cache' not in on['diagnostics']
    assert cache._current() is None


def test_failed_off_worker_does_not_leak_private_failure_or_disable_later_jobs(api,monkeypatch,caplog):
    client,root=api
    private='SYNTHETIC_PRIVATE_PATH_HASH_CELL_MONEY'
    def failed(*args):
        with cache.scope() as state:
            assert state.disabled
            cache.remember('party',(private,),lambda:private)
            raise ValueError(private)
    monkeypatch.setattr(core,'_monitor_cumulative_execute',failed)
    assert admit(client,'a'*32,profile_stages=True,profile_matching_cache_off=True).status_code==202
    response=poll(client,'a'*32)
    assert response.status_code==500
    meta=jobs.Store(root/'monitor'/'.cumulative_jobs')._meta('a'*32)
    assert private not in response.text+json.dumps(meta)+caplog.text
    def normal(*args):
        with cache.scope() as state:assert not state.disabled
        return {'ok':True,'register':{'rows':[]}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',normal)
    assert admit(client,'b'*32).status_code==202 and poll(client,'b'*32).status_code==200
    assert cache._current() is None
