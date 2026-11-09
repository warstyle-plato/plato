"""Offline protocol counterexamples for the single fixed approval operation."""
from __future__ import annotations

import datetime as dt
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


def bundle():
    return {'project':'Synthetic fixed project','old_source_sha256':OLD,
            'new_source_sha256':ops.SOURCE_SHA256,'source_base64':'c3ludGhldGlj',
            'old_cut':OLD_CUT,'snapshot_id':OLD_CUT+'-'+'c'*64,'source_as_of':OLD_CUT}


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
        self.health_count = 0
    def open(self,request,timeout):
        path = request.full_url.removeprefix(ops.BASE)
        body = json.loads(request.data) if request.data else None
        self.calls.append((path,body,timeout))
        if path == '/health':
            self.health_count += 1
            result = {'status':'ok','commit':COMMIT,'version':'0.1.2','data_writable':True}
        elif path == ops.PREVIEW:
            result = {'source_sha256':ops.SOURCE_SHA256,'works':198,'effective_from':body['effective_from'],
                      'source_format':'corpus-gpr-v1','requires_initial_baseline':False,
                      'current_revision':self.version_revision,
                      'expected_previous_sha256':ops.SOURCE_SHA256 if self.active else OLD,
                      'already_approved':self.active,
                      'approved_effective_from':self.effective if self.active else '2026-10-01'}
        elif path == ops.PHYSICAL:
            historic = body['cut'] == OLD_CUT
            current_new = self.active and not historic
            result = {'source_kind':'gpr','source_sha256':ops.SOURCE_SHA256 if current_new else OLD,
                      'snapshot_id':bundle()['snapshot_id'],'revision':7,'recorded_at':'2026-11-05T00:00:00+00:00',
                      'source_changed':False,'source_state':'approved_gpr','configuration':{'tasks':[]},
                      'item_count':2,'offset':0,'items':[{'item_id':'0:0'},{'item_id':'0:1'}],
                      'tasks':[{'task_id':str(i)} for i in range(198 if current_new else 5)],
                      'model':{'tasks':[{'task_id':'x','progress':.5}],'computed_at':len(self.calls)}}
        elif path == ops.APPROVE:
            self.approvals += 1
            self.active,self.version_revision,self.effective = True,1,body['effective_from']
            result = {'revision':1,'source_sha256':ops.SOURCE_SHA256,'effective_from':self.effective,
                      'approved_at':self.effective+'T12:00:00+00:00','unchanged':False}
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
    assert all(call[0] in ops.POST_PATHS|{'/health'} for call in first.calls)
    assert all(call[1] is None or call[1]['project']==bundle()['project'] for call in first.calls)
    existing = Server(active=True,effective='2026-11-08')
    result = operation(existing).execute(bundle(),KEY)
    assert result['ok'] and result['already_active'] and not result['write_attempted']
    assert existing.approvals == 0


@pytest.mark.parametrize('field,value',[
    ('source_sha256','d'*64),('works',197),('works',True),('source_format','other'),
    ('effective_from','2026-11-12'),('current_revision',True),('requires_initial_baseline',True),
    ('expected_previous_sha256','e'*64),('already_approved',True),
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


@pytest.mark.parametrize('case',['wrong-response-day','wrong-preview-day','old-cut-changed','runtime-changed'])
def test_postwrite_failure_is_distinct_from_not_applied(case):
    def mutate(server,path,body,result):
        if case=='wrong-response-day' and path==ops.APPROVE:
            result['effective_from'] = '2026-11-08'
        if case=='wrong-preview-day' and path==ops.PREVIEW and server.approvals:
            result['approved_effective_from'] = '2026-11-08'
        if case=='old-cut-changed' and path==ops.PHYSICAL and body['cut']==OLD_CUT and server.approvals:
            result['model']['tasks'][0]['progress'] = .9
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
    for raw in [b'{"a":1,"a":2}',b'{"a":NaN}',b'[]']:
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
    monkeypatch.setenv('EXPECTED_RUNTIME_COMMIT',COMMIT)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setenv('GITHUB_OUTPUT',str(tmp_path/'outputs'))
    monkeypatch.setenv('GPR_ONCE_TRANSPORT_KEY','synthetic-transport-secret')
    monkeypatch.setenv('APPLY_ADMIN_KEY',KEY)


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
    artifact = next(step for step in job['steps'] if str(step.get('uses','')).startswith('actions/upload-artifact'))
    assert artifact['if']=="always() && steps.apply.outputs.proof_created == 'true'"
    assert artifact['with']['path']=='${{ runner.temp }}/approved-gpr-apply-proof.cms'
    assert artifact['with']['retention-days']==1 and job['steps'][-1]['if']=='always()'
