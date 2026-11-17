"""Admin-only worker profiling preserves the full bounded as-of snapshot."""
import json
import sys
import threading

from fastapi.encoders import jsonable_encoder
import pytest

import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import developaid_monitor_python_profile as profile
from test_monitor_view_jobs import api, call, poll, KEY, core
from test_monitor_view_asof_source import sources, PROJECT, CUT, OLD, KEY as SOURCE_KEY, SESSION


def admit(client,ticket='a'*32,**extra):
    return call(client,project='Fixture',cut='2034-01-01',background=True,ticket=ticket,**extra)


@pytest.mark.parametrize('invalid',[0,1,'true','false',None,{},[]])
def test_profile_flag_is_a_strict_boolean_before_storage(api,invalid):
    client,root=api
    assert admit(client,profile_python=invalid).status_code==422
    assert not (root/'monitor'/'.view_jobs').exists()


@pytest.mark.parametrize('background',[False,True])
def test_admin_gate_precedes_profiler_sources_and_job_lookup(api,monkeypatch,background):
    client,root=api
    monkeypatch.setattr(monitor,'build',lambda *a,**k:pytest.fail('Unauthenticated source read'))
    monkeypatch.setattr(profile,'run',lambda *a,**k:pytest.fail('Unauthenticated profiler'))
    response=call(client,key='wrong',session='claimed-demo-owner',project='Fixture',cut='2034-01-01',background=background,profile_python=True)
    assert response.status_code==403 and not (root/'monitor'/'.view_jobs').exists()


def test_profile_is_rejected_for_legacy_sync_without_reading_programme_or_sources(api,monkeypatch):
    client,root=api
    monkeypatch.setattr(core,'_monitor_programme',lambda *a:pytest.fail('Sync programme read'))
    response=call(client,project='Fixture',cut='2034-01-01',profile_python=True,programme_base64='invalid')
    assert response.status_code==400 and response.headers['cache-control']=='private, no-store'
    assert not (root/'monitor'/'.view_jobs').exists()


def test_native_asof_normal_profiled_snapshots_are_complete_equal_and_keep_key_order(sources):
    client,root=sources
    originals={p:p.read_bytes() for p in root.rglob('*.xlsx')}
    expected=jsonable_encoder(monitor.build(PROJECT,CUT,upto=CUT))
    def start(ticket,**flags):
        return client.post('/monitor/view',json=dict(project=PROJECT,cut=CUT,key=SOURCE_KEY,session=SESSION,
            ticket=ticket,background=True,**flags))
    def finish(ticket):return poll(client,ticket,key=SOURCE_KEY,session=SESSION)
    assert start('a'*32).status_code==202
    normal=finish('a'*32).json()
    assert start('b'*32,profile_python=True).status_code==202
    traced=finish('b'*32).json()
    assert normal['snapshot']==traced['snapshot']==expected
    assert json.dumps(normal['snapshot'],ensure_ascii=False)==json.dumps(traced['snapshot'],ensure_ascii=False)
    assert traced['snapshot']['source']['estimate']==OLD
    assert traced['snapshot']['money']['estimate']==1000
    assert 'diagnostics' not in normal and set(traced)==set(normal)|{'diagnostics'}
    assert traced['diagnostics']['purpose']==profile.PURPOSE
    assert any(row['function']=='_build' or row['function']=='build' for row in traced['diagnostics']['rows'])
    assert len(json.dumps(traced['diagnostics']).encode())<=profile.MAX_BYTES
    assert all(path.read_bytes()==value for path,value in originals.items())
    store=jobs.Store(monitor._SNAPSHOT_DIR/'.view_jobs')
    assert store._meta('b'*32)['result_limit_bytes']==jobs.MAX_EXTENDED_RESULT_BYTES


@pytest.mark.parametrize('profiled',[False,True])
def test_ticket_cannot_switch_purpose_and_retries_build_only_once(api,monkeypatch,profiled):
    client,_=api;calls=[]
    admission_thread=threading.current_thread()
    def build(project,**kwargs):
        assert threading.current_thread() is not admission_thread
        assert (sys.getprofile() is not None) is profiled
        calls.append(kwargs)
        return {'unknown':None,'zero':0,'refund':-25}
    monkeypatch.setattr(monitor,'build',build)
    monkeypatch.setattr(monitor,'trend',lambda *a,**k:pytest.fail('Unexpected historical rebuild'))
    assert admit(client,profile_python=profiled).status_code==202
    result=poll(client,'a'*32)
    assert admit(client,profile_python=profiled).json()==result.json()
    assert admit(client,profile_python=not profiled).status_code==409
    assert calls==[{'cut':'2034-01-01','upto':'2034-01-01'}]


def test_predeploy_ordinary_fingerprint_and_wire_accept_omitted_and_false(api,monkeypatch):
    client,root=api;store=jobs.Store(root/'monitor'/'.view_jobs')
    owner=jobs.owner_binding(KEY,'','admin');ticket='a'*32
    params={'project':'Fixture','cut':'2034-01-01','click':ticket}
    store.start(owner,'admin',params,lambda:{'snapshot':{'old':True}},ticket,result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
    result=poll(client,ticket);before=store._meta(ticket)
    monkeypatch.setattr(monitor,'build',lambda *a,**k:pytest.fail('Old ticket rebuilt'))
    assert admit(client).json()==result.json()
    assert admit(client,profile_python=False).json()==result.json()
    assert admit(client,profile_python=True).status_code==409
    assert store._meta(ticket)==before


def test_legacy_sync_false_preserves_complete_existing_wire(sources):
    client,_=sources
    body=dict(project=PROJECT,cut=CUT,key=SOURCE_KEY,session=SESSION,background=False)
    ordinary=client.post('/monitor/view',json=body)
    explicit=client.post('/monitor/view',json={**body,'profile_python':False})
    assert ordinary.status_code==explicit.status_code==200
    assert ordinary.content==explicit.content


def test_profile_owner_current_key_ttl_and_wrong_purpose_still_fail_closed(api,monkeypatch):
    client,root=api
    monkeypatch.setattr(monitor,'build',lambda *a,**k:{'rows':[]})
    assert admit(client,session='owner',profile_python=True).status_code==202
    assert poll(client,'a'*32,session='owner').status_code==200
    assert call(client,'/result',ticket='a'*32,session='other').status_code==404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','rotated-profile-key')
    assert call(client,'/result',ticket='a'*32,session='owner').status_code==403
    assert call(client,'/result',ticket='a'*32,session='owner',key='rotated-profile-key').status_code==404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    store=jobs.Store(root/'monitor'/'.view_jobs')
    with store._locked():
        meta=store._meta('a'*32);meta['created']-=jobs.TTL_SECONDS+1;store._save(meta)
    assert call(client,'/result',ticket='a'*32,session='owner').status_code==404
    owner=jobs.owner_binding(KEY,'','admin')
    store.start(owner,'admin',{'project':'Fixture','cut':'2034-01-01','click':'b'*32,'diagnostics':'wrong-purpose'},lambda:{'snapshot':{}},'b'*32)
    assert admit(client,'b'*32,profile_python=True).status_code==409


def test_private_worker_errors_remain_generic_and_profiler_does_not_poison_next_job(api,monkeypatch,caplog):
    client,root=api;private='SYNTHETIC_PRIVATE_PATH_CELL_MONEY'
    def fail(*a,**k):raise ValueError(private)
    monkeypatch.setattr(monitor,'build',fail)
    assert admit(client,profile_python=True).status_code==202
    response=poll(client,'a'*32)
    assert response.status_code==500
    meta=jobs.Store(root/'monitor'/'.view_jobs')._meta('a'*32)
    assert private not in response.text+caplog.text+json.dumps(meta)
    monkeypatch.setattr(monitor,'build',lambda *a,**k:{'zero':0})
    assert admit(client,'b'*32,profile_python=True).status_code==202
    assert poll(client,'b'*32).json()['diagnostics']['purpose']==profile.PURPOSE
