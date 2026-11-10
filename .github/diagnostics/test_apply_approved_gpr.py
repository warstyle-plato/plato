"""Offline protocol counterexamples for the single fixed approval operation."""
from __future__ import annotations

import datetime as dt
import base64
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest

SCRIPT = Path(__file__).with_name('apply-approved-gpr.py')
spec = importlib.util.spec_from_file_location('oneoff_apply',SCRIPT)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
TODAY = '2026-11-09'
OLD_CUT = '2026-11-06'
OLD = 'a'*64
COMMIT = 'b'*40
KEY = 'synthetic-administrator-secret'
SOURCE = b'Synthetic reviewed remaining-work schedule'


@pytest.fixture(autouse=True)
def synthetic_input_only(monkeypatch,tmp_path):
    envelope = b'Synthetic authenticated envelope; no real ciphertext read'
    path = tmp_path/'input.cms';path.write_bytes(envelope)
    monkeypatch.setattr(ops,'INPUT_PATH',path)
    monkeypatch.setattr(ops,'INPUT_SHA256',ops.sha(envelope))
    monkeypatch.setattr(ops,'PLAINTEXT_SHA256','1'*64)
    monkeypatch.setattr(ops,'SOURCE_SHA256',ops.sha(SOURCE))
    monkeypatch.setattr(ops,'SOURCE_BYTES',len(SOURCE))
    monkeypatch.setattr(ops,'OLD_SOURCE_SHA256',OLD)
    monkeypatch.setattr(ops.urllib.request,'build_opener',
                        lambda *a,**k:pytest.fail('offline protocol attempted a real HTTP client'))


def bundle():
    return {'schema':2,'project':'Synthetic fixed project','old_source_sha256':OLD,
            'new_source_sha256':ops.SOURCE_SHA256,'source_base64':base64.b64encode(SOURCE).decode(),
            'old_cut':OLD_CUT,'snapshot_id':OLD_CUT+'-'+'c'*64,'source_as_of':OLD_CUT,
            'baseline_proof_sha256':'d'*64,'operation_nonce':'e'*64,'expected_physical_revision':7,
            'owner_rnv_date':ops.OWNER_RNV_DATE,'owner_rnv_note':'Synthetic explicit owner decision',
            'expected_owner_rnv_revision':0}


class Response(io.BytesIO):
    status = 200
    def __init__(self,url,payload):
        data = json.dumps(payload).encode()
        super().__init__(data)
        self.url,self.headers = url,{'Content-Length':str(len(data))}
    def geturl(self):
        return self.url


class Server:
    def __init__(self, *, active=False, effective=TODAY, mutation=None):
        self.active,self.effective,self.mutation = active,effective,mutation
        self.calls,self.approvals = [],0
        self.version_revision = 1 if active else 0
        self.owner_revision = 1 if active else 0
        self.health_count = 0
    def owner(self):
        return {'revision':self.owner_revision,'source':'owner_decision','date':ops.OWNER_RNV_DATE,
                'note':bundle()['owner_rnv_note'],'effective_from':self.effective,
                'recorded_at':self.effective+'T12:00:00+00:00','author':'Synthetic administrator'} if self.active else None
    def open(self,request,timeout):
        path = request.full_url.removeprefix(ops.BASE)
        body = json.loads(request.data) if request.data else None
        self.calls.append((path,body,timeout))
        if path == '/health':
            self.health_count += 1
            result = {'status':'ok','commit':COMMIT,'version':'0.1.2','data_writable':True}
        elif path == ops.PREVIEW:
            result = {'source_sha256':ops.SOURCE_SHA256,'works':213,'effective_from':body['effective_from'],
                      'source_format':'corpus-gpr-v1','requires_initial_baseline':False,
                      'current_revision':self.version_revision,
                      'latest_source_revision':self.version_revision,
                      'active_source_sha256':ops.SOURCE_SHA256 if self.active else OLD,
                      'expected_previous_sha256':ops.SOURCE_SHA256 if self.active else OLD,
                      'approved_previous_sha256':OLD if self.active else None,
                      'already_approved':self.active,
                      'approved_effective_from':self.effective if self.active else '2026-10-01',
                      'baseline_scope':ops.BASELINE_SCOPE,'owner_rnv_revision':self.owner_revision,
                      'owner_rnv':self.owner(),'proposed_owner_rnv':{'date':ops.OWNER_RNV_DATE,
                          'source':'owner_decision','note':body['owner_rnv_note'],'effective_from':body['effective_from']},
                      'capabilities':{'owner_rnv_v1':True,'remaining_plan_v1':True,'historical_fact_audit_v1':True},
                      'audit':{'cut':OLD_CUT,'known':True,'archival_source_sha256':OLD,
                          'archival_source_revision':0,'snapshot_id':bundle()['snapshot_id'],
                          'snapshot_sha256':'c'*64,'physical_revision':7,
                          'physical_configuration_sha256':'d'*64,'factual_state_sha256':'e'*64}}
        elif path == ops.PHYSICAL:
            current_new = self.active
            result = {'source_kind':'gpr','source_sha256':ops.SOURCE_SHA256 if current_new else OLD,
                      'snapshot_id':bundle()['snapshot_id'],'revision':7,'recorded_at':'2026-11-05T00:00:00+00:00',
                      'source_changed':False,'source_state':'approved_gpr','configuration':{'tasks':[]},
                      'item_count':2,'offset':0,'items':[{'item_id':'0:0'},{'item_id':'0:1'}],
                      'tasks':[{'task_id':str(i)} for i in range(213 if current_new else 5)],
                      'model':{'tasks':[{'task_id':'x','progress':.5}],'computed_at':len(self.calls)}}
        elif path == ops.APPROVE:
            self.approvals += 1
            self.active,self.version_revision,self.effective = True,1,body['effective_from']
            self.owner_revision = 1
            result = {'revision':1,'source_sha256':ops.SOURCE_SHA256,'effective_from':self.effective,
                      'approved_at':self.effective+'T12:00:00+00:00','unchanged':False,
                      'baseline_scope':ops.BASELINE_SCOPE,'owner_rnv_revision':self.owner_revision,
                      'owner_rnv':self.owner()}
        else:
            raise AssertionError('unexpected path')
        if self.mutation:
            result = self.mutation(self,path,body,result)
        return Response(request.full_url,result)


def operation(server):
    return ops.Operation(COMMIT,opener=server,today=lambda:dt.date.fromisoformat(TODAY))


def test_initial_write_and_existing_new_have_distinct_version_fences():
    first = Server()
    result = operation(first).execute(bundle(),KEY)
    assert result['ok'] and result['write_attempted'] and result['write_response_verified']
    assert first.approvals == 1 and result['old_cut_verified'] and not result['outcome_unknown']
    assert result['historical_audit_verified'] and result['owner_rnv_verified']
    assert all(call[0] in ops.POST_PATHS|{'/health'} for call in first.calls)
    assert all(call[1] is None or call[1]['project']==bundle()['project'] for call in first.calls)
    existing = Server(active=True,effective='2026-11-08')
    result = operation(existing).execute(bundle(),KEY)
    assert result['ok'] and result['already_active'] and not result['write_attempted']
    assert existing.approvals == 0


@pytest.mark.parametrize('already_active',[False,True])
def test_fixed_final_contract_accepts_literal_213_independent_of_the_server_fixture(already_active):
    def final_contract(server,path,body,result):
        if path==ops.PREVIEW:result['works']=213
        if path==ops.PHYSICAL and server.active:
            result['tasks']=[{'task_id':str(index)} for index in range(213)]
        return result
    server=Server(active=already_active,mutation=final_contract)
    result=operation(server).execute(bundle(),KEY)
    assert result['ok'] and result['preview_works']==213
    assert server.approvals==(0 if already_active else 1)


@pytest.mark.parametrize('old_surface',['preview','physical'])
def test_superseded_198_count_cannot_pass_a_final_source_fence(old_surface):
    def old_count(server,path,body,result):
        if old_surface=='preview' and path==ops.PREVIEW:result['works']=198
        if old_surface=='physical' and path==ops.PHYSICAL:
            result['tasks']=[{'task_id':str(index)} for index in range(198)]
        return result
    server=Server(active=True,mutation=old_count)
    with pytest.raises(ops.ApplyError):operation(server).execute(bundle(),KEY)
    assert server.approvals==0


@pytest.mark.parametrize('field,value',[
    ('schema',1),('schema',True),('old_source_sha256','f'*64),('new_source_sha256','f'*64),
    ('old_cut','2026-11-05'),('snapshot_id','2026-11-05-'+'c'*64),('source_as_of','not-a-date'),
    ('expected_physical_revision',True),('expected_physical_revision',-1),
    ('expected_owner_rnv_revision',True),('expected_owner_rnv_revision',1),
    ('owner_rnv_date','2027-09-29'),('owner_rnv_note',''),('owner_rnv_note',' not trimmed'),
    ('owner_rnv_note','x'*1001),('source_base64','!'),('source_base64',base64.b64encode(SOURCE+b'x').decode()),
    ('baseline_proof_sha256',None),('operation_nonce',None),
])
def test_manifest_drift_is_rejected_before_any_http(field,value):
    data=bundle();data[field]=value
    server=Server()
    with pytest.raises(ops.ApplyError):operation(server).execute(data,KEY)
    assert not server.calls and server.approvals==0


def test_decryption_and_manifest_validation_use_synthetic_bytes_only(tmp_path,monkeypatch):
    raw=json.dumps(bundle()).encode()
    monkeypatch.setattr(ops,'PLAINTEXT_SHA256',ops.sha(raw))
    calls=[]
    def decrypt(command,**kwargs):
        calls.append(command)
        assert kwargs['input']==ops.INPUT_PATH.read_bytes()
        return SimpleNamespace(returncode=0,stdout=raw)
    monkeypatch.setattr(ops.subprocess,'run',decrypt)
    result=ops.decrypt_bundle(ops.INPUT_PATH.read_bytes(), '-----BEGIN PRIVATE KEY-----\n'+'x'*1100,tmp_path)
    assert result==bundle() and len(calls)==1 and not list(tmp_path.glob('gpr-input-*'))


@pytest.mark.parametrize('capability',['owner_rnv_v1','remaining_plan_v1','historical_fact_audit_v1'])
@pytest.mark.parametrize('value',[None,False,1])
def test_unsupported_or_untyped_api_capability_never_reaches_approve(capability,value):
    def mutate(server,path,body,result):
        if path==ops.PREVIEW:result['capabilities'][capability]=value
        return result
    server=Server(mutation=mutate)
    with pytest.raises(ops.ApplyError):operation(server).execute(bundle(),KEY)
    assert server.approvals==0


@pytest.mark.parametrize('field,value',[
    ('known',False),('known',1),('cut','2026-11-05'),('archival_source_sha256','f'*64),
    ('archival_source_revision',True),('archival_source_revision',1),('snapshot_id','unexpected'),
    ('snapshot_sha256',None),('snapshot_sha256','f'*64),('physical_revision',True),('physical_revision',8),
    ('physical_configuration_sha256',None),('physical_configuration_sha256',''),
    ('factual_state_sha256',None),('factual_state_sha256',[]),
])
def test_historical_audit_is_explicit_known_and_source_qualified_before_write(field,value):
    def mutate(server,path,body,result):
        if path==ops.PREVIEW:result['audit'][field]=value
        return result
    server=Server(mutation=mutate)
    with pytest.raises(ops.ApplyError):operation(server).execute(bundle(),KEY)
    assert server.approvals==0


@pytest.mark.parametrize('field,value',[
    ('owner_rnv_revision',0),('owner_rnv_revision',True),('owner_rnv_revision',2),
    ('owner_rnv',None),('approved_previous_sha256',None),('approved_previous_sha256','f'*64),
    ('latest_source_revision',2),('active_source_sha256',OLD),
])
def test_source_only_already_active_is_not_success(field,value):
    def mutate(server,path,body,result):
        if path==ops.PREVIEW:result[field]=value
        return result
    server=Server(active=True,mutation=mutate)
    with pytest.raises(ops.ApplyError):operation(server).execute(bundle(),KEY)
    assert server.approvals==0


@pytest.mark.parametrize('field,value',[
    ('date','2027-09-29'),('source','gpr'),('revision',True),('revision',2),('note','Other decision'),
    ('effective_from','2026-11-08'),('recorded_at','2026-11-09T12:00:00'),('author',None),('author',' '),
])
def test_idempotence_requires_the_entire_recorded_owner_decision(field,value):
    def mutate(server,path,body,result):
        if path==ops.PREVIEW:result['owner_rnv'][field]=value
        return result
    server=Server(active=True,mutation=mutate)
    with pytest.raises(ops.ApplyError):operation(server).execute(bundle(),KEY)
    assert server.approvals==0


@pytest.mark.parametrize('field',['physical_configuration_sha256','factual_state_sha256'])
def test_valid_but_changed_archival_hash_after_write_is_an_uncertain_outcome(field):
    def mutate(server,path,body,result):
        if path==ops.PREVIEW and server.approvals:result['audit'][field]='f'*64
        return result
    server=Server(mutation=mutate);op=operation(server)
    with pytest.raises(ops.ApplyError):op.execute(bundle(),KEY)
    assert server.approvals==1 and op.summary['outcome_unknown'] and not op.summary['postflight_verified']


@pytest.mark.parametrize('field,value',[('owner_rnv',None),('owner_rnv_revision',0),('baseline_scope','all_work')])
def test_source_write_without_the_atomic_owner_result_is_not_called_success(field,value):
    def mutate(server,path,body,result):
        if path==ops.APPROVE:result[field]=value
        return result
    server=Server(mutation=mutate);op=operation(server)
    with pytest.raises(ops.ApplyError):op.execute(bundle(),KEY)
    assert server.approvals==1 and op.summary['write_attempted'] and op.summary['outcome_unknown']
    assert not op.summary['write_response_verified'] and not op.summary['ok']


def test_an_uncertain_operation_cannot_reenter_even_read_only_preflight():
    def mutate(server,path,body,result):
        if path==ops.APPROVE:raise urllib.error.URLError('synthetic ambiguous response')
        return result
    server=Server(mutation=mutate);op=operation(server)
    with pytest.raises(ops.ApplyError):op.execute(bundle(),KEY)
    calls=len(server.calls)
    with pytest.raises(ops.ApplyError):op.execute(bundle(),KEY)
    assert len(server.calls)==calls and server.approvals==1


@pytest.mark.parametrize('field,value',[
    ('source_sha256','d'*64),('works',198),('works',True),('source_format','other'),
    ('effective_from','2026-11-12'),('current_revision',True),('requires_initial_baseline',True),
    ('expected_previous_sha256','e'*64),('already_approved',True),
    ('latest_source_revision',True),('latest_source_revision',1),('active_source_sha256',None),
    ('active_source_sha256','f'*64),
])
def test_bad_preview_cannot_reach_the_writer(field,value):
    def mutate(server,path,body,result):
        if path == ops.PREVIEW:
            result[field] = value
        return result
    server = Server(mutation=mutate)
    with pytest.raises(ops.ApplyError):
        operation(server).execute(bundle(),KEY)
    assert server.approvals == 0


@pytest.mark.parametrize('effective,revision', [('2026-11-12',1),('2026-11-06',1),('2026-11-08',2)])
def test_already_new_is_not_a_sha_only_shortcut(effective,revision):
    server = Server(active=True,effective=effective)
    server.version_revision = revision
    with pytest.raises(ops.ApplyError):
        operation(server).execute(bundle(),KEY)
    assert server.approvals == 0


def test_already_active_cannot_predate_the_manifest_observation():
    data=bundle();data['source_as_of']=TODAY
    server=Server(active=True,effective='2026-11-08')
    with pytest.raises(ops.ApplyError):operation(server).execute(data,KEY)
    assert server.approvals==0


def test_an_uncertain_write_has_no_retry_or_success_claim():
    def mutate(server,path,body,result):
        if path == ops.APPROVE:
            raise urllib.error.URLError('synthetic lost response')
        return result
    server = Server(mutation=mutate)
    op = operation(server)
    with pytest.raises(ops.ApplyError):
        op.execute(bundle(),KEY)
    assert server.active and server.approvals == 1
    assert op.summary['write_attempted'] and op.summary['outcome_unknown'] and not op.summary['ok']
    assert not op.summary['write_response_verified']


@pytest.mark.parametrize('case',['wrong-response-day','wrong-preview-day','historical-facts-changed','runtime-changed'])
def test_postwrite_failure_is_distinct_from_not_applied(case):
    def mutate(server,path,body,result):
        if case=='wrong-response-day' and path==ops.APPROVE:
            result['effective_from'] = '2026-11-08'
        if case=='wrong-preview-day' and path==ops.PREVIEW and server.approvals:
            result['approved_effective_from'] = '2026-11-08'
        if case=='historical-facts-changed' and path==ops.PREVIEW and server.approvals:
            result['audit']['factual_state_sha256'] = 'f'*64
        if case=='runtime-changed' and path=='/health' and server.approvals:
            result['commit'] = 'f'*40
        return result
    server,op = Server(mutation=mutate),None
    op = operation(server)
    with pytest.raises(ops.ApplyError):
        op.execute(bundle(),KEY)
    assert server.approvals == 1 and op.summary['write_attempted']
    assert op.summary['outcome_unknown'] and not op.summary['ok']


def test_foreign_paths_and_redirects_are_never_followed():
    server = Server()
    op = operation(server)
    with pytest.raises(ops.ApplyError):
        op.request('https://other.example/health')
    assert not server.calls
    class RedirectServer:
        calls = 0
        def open(self,request,timeout):
            self.calls += 1
            response = Response('https://other.example/health',{'status':'ok'})
            return response
    redirected = RedirectServer()
    with pytest.raises(ops.ApplyError):
        operation(redirected).health()
    assert redirected.calls == 1
    with pytest.raises(ops.ApplyError):
        ops.NoRedirect().redirect_request(None,None,307,'',{},'https://other.example/')


def environment():
    return {'GITHUB_REPOSITORY':ops.REPOSITORY,'GITHUB_ACTOR':ops.ACTOR,
            'GITHUB_TRIGGERING_ACTOR':ops.ACTOR,'GITHUB_REF':ops.BRANCH,
            'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
            'GITHUB_SHA':COMMIT,'GITHUB_WORKFLOW_SHA':COMMIT,'GITHUB_REPOSITORY_OWNER':'an-organization'}


def test_checkout_pins_an_explicit_human_not_repository_owner():
    def run(command,**kwargs):
        return SimpleNamespace(returncode=0,stdout=COMMIT.encode())
    ops.trusted_checkout(environment(),run=run)


@pytest.mark.parametrize('field,value',[
    ('GITHUB_ACTOR','an-organization'),('GITHUB_TRIGGERING_ACTOR','other-human'),
    ('GITHUB_REPOSITORY','other/repository'),('GITHUB_REF','refs/heads/main'),
    ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_EVENT_NAME','push'),('GITHUB_WORKFLOW_SHA','e'*40),
])
def test_wrong_workflow_identity_fails_before_checkout(field,value):
    env = environment();env[field]=value
    with pytest.raises(ops.ApplyError):
        ops.trusted_checkout(env,run=lambda *a,**k:pytest.fail('checkout reached'))


def test_secret_echo_cannot_enter_the_private_proof_or_trigger_a_write():
    def mutate(server,path,body,result):
        if path==ops.PHYSICAL:
            result['unexpected'] = KEY
        return result
    server = Server(mutation=mutate)
    with pytest.raises(ops.ApplyError):
        operation(server).execute(bundle(),KEY)
    assert server.approvals == 0


def test_unapproved_physical_source_cannot_authorize_the_write():
    def mutate(server,path,body,result):
        if path==ops.PHYSICAL:
            result['source_state'] = 'unapproved_corpus'
        return result
    server = Server(mutation=mutate)
    with pytest.raises(ops.ApplyError):
        operation(server).execute(bundle(),KEY)
    assert server.approvals == 0


def test_failed_encryption_removes_its_own_incomplete_target(tmp_path,monkeypatch):
    recipient = ops.PUBLIC_RECIPIENT.read_bytes()
    target = tmp_path/'proof.cms'
    monkeypatch.setattr(ops.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    with pytest.raises(ops.ApplyError):
        ops.encrypt_proof({'safe':True},recipient,target,tmp_path)
    assert not target.exists() and not list(tmp_path.glob('gpr-proof-*'))


def test_json_ambiguity_and_oversized_responses_fail_closed():
    for raw in [b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}',b'[]']:
        with pytest.raises(ops.ApplyError):
            ops.strict_json(raw)
    class Oversized(Server):
        def open(self,request,timeout):
            response = super().open(request,timeout)
            response.headers['Content-Length'] = str(ops.MAX_RESPONSE+1)
            return response
    with pytest.raises(ops.ApplyError):
        operation(Oversized()).health()


def main_environment(monkeypatch,tmp_path,server):
    monkeypatch.setattr(ops,'trusted_checkout',lambda _:None)
    initialize = ops.Operation.__init__
    def fixed(self,expected,**kwargs):
        initialize(self,expected,opener=server,today=lambda:dt.date.fromisoformat(TODAY))
    monkeypatch.setattr(ops.Operation,'__init__',fixed)
    monkeypatch.setattr(ops,'decrypt_bundle',lambda *a:bundle())
    monkeypatch.setattr(ops.os,'environ',{'EXPECTED_RUNTIME_COMMIT':COMMIT,'RUNNER_TEMP':str(tmp_path),
        'GITHUB_OUTPUT':str(tmp_path/'outputs'),'GPR_ONCE_TRANSPORT_KEY':'synthetic-transport-secret',
        'APPLY_ADMIN_KEY':KEY})


def public_result(capsys):
    captured = capsys.readouterr()
    assert not captured.err
    assert KEY not in captured.out and 'synthetic-transport-secret' not in captured.out
    assert bundle()['project'] not in captured.out and ops.SOURCE_SHA256 not in captured.out
    result = json.loads(captured.out)
    assert all(type(value) in {bool,int} for value in result.values())
    return result


def test_main_success_publishes_only_booleans_counts_and_encrypted_proof(monkeypatch,tmp_path,capsys):
    server = Server()
    main_environment(monkeypatch,tmp_path,server)
    assert ops.main() == 0
    result = public_result(capsys)
    assert result['ok'] and result['encrypted_proof_created'] and server.approvals==1
    assert (tmp_path/'approved-gpr-apply-proof.cms').is_file()
    assert not list(tmp_path.glob('gpr-input-*')) and not list(tmp_path.glob('gpr-proof-*'))
    assert (tmp_path/'outputs').read_text() == 'proof_created=true\n'


def test_main_unknown_outcome_keeps_partial_ciphertext_but_never_retries(monkeypatch,tmp_path,capsys):
    def mutate(server,path,body,result):
        if path==ops.APPROVE:
            raise urllib.error.URLError(KEY+' '+bundle()['project'])
        return result
    server = Server(mutation=mutate)
    main_environment(monkeypatch,tmp_path,server)
    assert ops.main() == 1
    result = public_result(capsys)
    assert result['write_attempted'] and result['outcome_unknown'] and not result['write_response_verified']
    assert result['encrypted_proof_created'] and not result['postflight_verified']
    assert server.approvals == 1


def test_main_runtime_gate_precedes_decryption_and_admin_reads(monkeypatch,tmp_path,capsys):
    def mutate(server,path,body,result):
        if path=='/health':
            result['commit'] = 'f'*40
        return result
    server = Server(mutation=mutate)
    main_environment(monkeypatch,tmp_path,server)
    monkeypatch.setattr(ops,'decrypt_bundle',lambda *a:pytest.fail('decryption before runtime gate'))
    assert ops.main() == 1
    result = public_result(capsys)
    assert result['error_code'] == ops.RUNTIME and not result['encrypted_proof_created']
    assert [path for path,_,_ in server.calls] == ['/health'] and server.approvals == 0


def test_unsealed_protocol_cannot_read_any_input_key_or_make_any_http_request(monkeypatch,tmp_path,capsys):
    server=Server();main_environment(monkeypatch,tmp_path,server)
    monkeypatch.setattr(ops,'INPUT_SHA256',None)
    monkeypatch.setattr(ops,'bounded_file',lambda *a:pytest.fail('unsealed input was read'))
    monkeypatch.setattr(ops,'decrypt_bundle',lambda *a:pytest.fail('unsealed input was decrypted'))
    assert ops.main()==1
    result=public_result(capsys)
    assert result['error_code']==ops.SETUP and not result['write_attempted'] and not server.calls


def test_workflow_has_only_explicit_fixed_scope_and_ciphertext_artifact():
    import yaml
    workflow = yaml.safe_load((SCRIPT.parents[1]/'workflows/prod-smoke.yml').read_text())
    triggers = workflow.get('on',workflow.get(True))
    assert set(triggers)=={'workflow_dispatch'}
    assert set(triggers['workflow_dispatch']['inputs'])=={'expected_runtime_commit'}
    assert workflow['permissions']=={'contents':'read'}
    assert workflow['concurrency']=={'group':'approved-gpr-source-apply-once','cancel-in-progress':False}
    job = workflow['jobs']['apply']
    assert 'github.actor' in job['if'] and 'github.triggering_actor' in job['if']
    assert 'repository_owner' not in job['if'] and ops.BRANCH in job['if']
    checkout = job['steps'][0]
    assert checkout['with']['ref']=='${{ github.sha }}' and checkout['with']['persist-credentials'] is False
    artifact = next(step for step in job['steps'] if step.get('with',{}).get('name')=='approved-gpr-apply-encrypted')
    assert artifact['if']=="always() && steps.apply.outputs.proof_created == 'true'"
    assert artifact['with']['path']=='${{ runner.temp }}/approved-gpr-apply-proof.cms'
    assert artifact['with']['retention-days']==1 and job['steps'][-1]['if']=='always()'


@pytest.mark.parametrize('read_seconds',[18,45])
def test_realistic_slow_reads_complete_once_with_bounded_new_timeouts(read_seconds):
    now=[0.0]
    class SlowReads(Server):
        def open(self,request,timeout):
            path=request.full_url.removeprefix(ops.BASE)
            delay=read_seconds if path in {ops.PHYSICAL,ops.PREVIEW} else 0
            assert 0<timeout<=60
            if timeout<delay:
                now[0]+=timeout
                raise TimeoutError('Synthetic slow fixed read')
            now[0]+=delay
            return super().open(request,timeout)
    server=SlowReads()
    value=ops.Operation(COMMIT,opener=server,clock=lambda:now[0],
        today=lambda:dt.date.fromisoformat(TODAY))
    value.health();value.health()
    result=value.execute(bundle(),KEY)
    assert result['ok'] and result['postflight_verified'] and server.approvals==1
    assert result['write_attempted'] and result['write_response_verified'] and not result['outcome_unknown']
    assert now[0]<ops.TOTAL_SECONDS
    if read_seconds==45:assert now[0]>240  # Old total clock fails despite healthy individual reads.


def test_extended_apply_clock_still_refuses_http_after_expiry():
    now=[0.0];server=Server()
    value=ops.Operation(COMMIT,opener=server,clock=lambda:now[0],
        today=lambda:dt.date.fromisoformat(TODAY))
    now[0]=601
    with pytest.raises(ops.ApplyError) as error:value.execute(bundle(),KEY)
    assert error.value.code==ops.DEADLINE and server.approvals==0 and not server.calls


def test_apply_timeouts_remain_explicitly_bounded():
    assert ops.HTTP_SECONDS==60 and ops.TOTAL_SECONDS==600
