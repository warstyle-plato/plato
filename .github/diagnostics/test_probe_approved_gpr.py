"""Only synthetic fixed projects and in-memory HTTP responses are used."""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import socket
import urllib.error

import pytest

SCRIPT=Path(__file__).with_name('probe-approved-gpr.py')
spec=importlib.util.spec_from_file_location('read_only_probe_test',SCRIPT)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
ops=probe.ops
COMMIT='a'*40
KEY='Synthetic secret never printed'
PROJECT='Synthetic private project never printed'
TODAY=dt.date(2026,11,10)
BUNDLE={'project':PROJECT,'old_cut':'2026-11-06','source_as_of':'2026-11-06',
        'snapshot_id':'2026-11-06-'+'c'*64,'expected_physical_revision':7}


class Response(io.BytesIO):
    status=200
    def __init__(self,url,payload):
        raw=json.dumps(payload).encode();super().__init__(raw)
        self.url,self.headers=url,{'Content-Length':str(len(raw))}
    def geturl(self):return self.url


class Server:
    def __init__(self,mutation=None):self.calls=[];self.mutation=mutation
    def open(self,request,timeout):
        path=request.full_url.removeprefix(ops.BASE)
        body=json.loads(request.data) if request.data else None
        assert path in {'/health',ops.PHYSICAL}
        assert request.get_header('Authorization') is None
        assert 0<timeout<=60
        self.calls.append((path,body,timeout))
        if path=='/health':
            payload={'status':'ok','commit':COMMIT,'version':'0.28.93','data_writable':True}
            assert request.method=='GET'
        else:
            assert request.method=='POST' and set(body)=={'key','project','cut','offset'}
            assert body['key']==KEY and body['project']==PROJECT and body['offset']==0
            assert body['cut'] in {'2026-11-06',TODAY.isoformat()}
            payload={'source_sha256':ops.OLD_SOURCE_SHA256,'snapshot_id':BUNDLE['snapshot_id'],
                     'revision':7,'tasks':[]}
        response=Response(request.full_url,payload)
        return self.mutation(request,response) if self.mutation else response


@pytest.fixture
def setup(monkeypatch,tmp_path):
    env={'RUNNER_TEMP':str(tmp_path),'EXPECTED_RUNTIME_COMMIT':COMMIT,
         'APPLY_ADMIN_KEY':KEY,'GITHUB_TOKEN':'Synthetic GitHub token never printed'}
    monkeypatch.setattr(ops,'trusted_checkout',lambda environment:None)
    monkeypatch.setattr(ops,'decrypt_bundle',lambda *a,**k:dict(BUNDLE))
    monkeypatch.setattr(ops.Operation,'execute',lambda *a,**k:pytest.fail('probe attempted execute'))
    def provider(temporary):
        assert temporary==tmp_path
        assert env['APPLY_ADMIN_KEY']==KEY
        return b'Synthetic ciphertext','Synthetic temporary key'
    return env,provider


def run(setup,server,**kwargs):
    env,provider=setup
    return probe.probe(env,input_provider=provider,opener=server,
                       today=lambda:TODAY,**kwargs)


def test_success_is_explicitly_read_only_with_only_sanitized_results(setup):
    server=Server();summary=run(setup,server)
    assert summary['ok'] and summary['probe_only'] and not summary['write_attempted']
    assert summary['outcome_unknown'] is False and summary['input_verified'] and summary['runtime_verified']
    assert [r['phase'] for r in summary['results']]==[
        'health_before_decrypt','health_before_reads','old_cut','current_cut','health_after_reads']
    assert len(server.calls)==5 and all(r['http_status']==200 for r in summary['results'])
    assert all(r['source_matches_old'] and r['snapshot_matches'] and r['physical_revision_matches']
               and r['tasks_known'] for r in summary['results'] if r['phase'] in probe.PHYSICAL_PHASES)
    public=json.dumps(summary)
    assert KEY not in public and PROJECT not in public and 'https://' not in public
    assert 'Synthetic GitHub token' not in public and ops.OLD_SOURCE_SHA256 not in public
    assert 'APPLY_ADMIN_KEY' not in setup[0]


@pytest.mark.parametrize('phase',[ops.APPROVE,ops.PREVIEW,'https://evil.invalid','unknown','/health',None])
def test_unknown_or_mutating_phase_rejected_before_http(phase):
    server=Server();client=probe.ReadOnlyProbe(COMMIT,opener=server)
    with pytest.raises(ops.ApplyError) as error:client.request(phase)
    assert error.value.code==ops.FENCE and not server.calls


@pytest.mark.parametrize('status',[401,403,404,500,502,504])
def test_http_error_status_is_visible_but_private_body_is_not(setup,status):
    def fail(request,response):
        if request.data and json.loads(request.data)['cut']=='2026-11-06':
            raise urllib.error.HTTPError(request.full_url,status,KEY,{},io.BytesIO(PROJECT.encode()))
        return response
    server=Server(fail);summary=run(setup,server)
    old=next(r for r in summary['results'] if r['phase']=='old_cut')
    assert old['http_status']==status and old['timeout'] is False and not old['json_known']
    assert not summary['ok'] and summary['error_code']==ops.HTTP and not summary['write_attempted']
    assert any(body and body['cut']==TODAY.isoformat() for _,body,_ in server.calls)
    assert PROJECT not in json.dumps(summary) and KEY not in json.dumps(summary)


@pytest.mark.parametrize('failure',[socket.timeout(KEY),urllib.error.URLError(socket.timeout(KEY))])
def test_timeout_is_distinct_and_current_cut_is_still_read(setup,failure):
    def fail(request,response):
        if request.data and json.loads(request.data)['cut']=='2026-11-06':raise failure
        return response
    server=Server(fail);summary=run(setup,server)
    old=next(r for r in summary['results'] if r['phase']=='old_cut')
    assert old['timeout'] is True and old['http_status']==0
    assert not summary['ok'] and not summary['write_attempted']
    assert any(body and body['cut']==TODAY.isoformat() for _,body,_ in server.calls)
    assert KEY not in json.dumps(summary)


def test_general_network_failure_is_not_reported_as_timeout(setup):
    def fail(request,response):
        if request.data:raise urllib.error.URLError(KEY)
        return response
    summary=run(setup,Server(fail))
    assert not summary['ok']
    assert all(not r['timeout'] for r in summary['results'])
    assert KEY not in json.dumps(summary)


@pytest.mark.parametrize('kind',['redirect','oversize','duplicate-json','key-in-body','wrong-runtime'])
def test_unsafe_responses_stop_before_any_mutation(setup,kind):
    def change(request,response):
        if kind=='redirect':response.url='https://evil.invalid'
        elif kind=='oversize':response.headers['Content-Length']=str(ops.MAX_RESPONSE+1)
        elif kind=='duplicate-json':
            response=io.BytesIO(b'{"ok":true,"ok":false}');response.status=200
            response.headers={};response.geturl=lambda:request.full_url
        elif kind=='key-in-body' and request.data:response=Response(request.full_url,{'private':KEY})
        elif kind=='wrong-runtime':response=Response(request.full_url,{'status':'ok','commit':'e'*40})
        return response
    summary=run(setup,Server(change))
    assert not summary['ok'] and not summary['write_attempted']
    assert summary['error_code']!=0 and KEY not in json.dumps(summary)


def test_invalid_fixed_input_never_reads_admin_or_private_endpoint(setup,monkeypatch):
    def reject(*args,**kwargs):raise ops.ApplyError(ops.INPUT)
    monkeypatch.setattr(ops,'decrypt_bundle',reject)
    server=Server();summary=run(setup,server)
    assert not summary['input_verified'] and not summary['write_attempted']
    assert all(path=='/health' for path,_,_ in server.calls)
    assert setup[0]['APPLY_ADMIN_KEY']==KEY


def test_transport_wait_precedes_probe_deadline(setup,monkeypatch):
    env,provider=setup;state={'wait_done':False}
    def clock():
        assert state['wait_done']
        return 1000
    def delayed(temporary):state['wait_done']=True;return provider(temporary)
    result=probe.probe(env,input_provider=delayed,opener=Server(),clock=clock,today=lambda:TODAY)
    assert result['ok']


def test_probe_deadline_stops_http_before_request():
    now=[0];server=Server()
    client=probe.ReadOnlyProbe(COMMIT,opener=server,clock=lambda:now[0])
    now[0]=181
    with pytest.raises(ops.ApplyError) as error:client.request('health_before_decrypt')
    assert error.value.code==ops.DEADLINE and not server.calls


def test_utc_date_change_rejects_further_private_read(setup):
    server=Server();client=probe.ReadOnlyProbe(COMMIT,opener=server,today=lambda:TODAY)
    client.bundle,client.key,client.effective=dict(BUNDLE),KEY,'2026-11-09'
    with pytest.raises(ops.ApplyError) as error:client.request('old_cut')
    assert error.value.code==ops.FENCE and not server.calls


def test_workflow_is_temporarily_probe_only_with_one_runtime_input():
    import yaml
    workflow=yaml.safe_load((SCRIPT.parents[1]/'workflows/prod-smoke.yml').read_text())
    triggers=workflow.get('on',workflow.get(True))
    assert set(triggers)=={'workflow_dispatch'}
    assert set(triggers['workflow_dispatch']['inputs'])=={'expected_runtime_commit'}
    assert workflow['permissions']=={'contents':'read'}
    assert workflow['run-name']=='approved-gpr-source-readonly-probe'
    apply=next(s for s in workflow['jobs']['apply']['steps'] if s.get('id')=='apply')
    assert apply['run']=='python3 .github/diagnostics/ephemeral-gpr-transport.py probe'
    assert not any(s.get('run','').endswith('transport.py apply') for s in workflow['jobs']['apply']['steps'])
