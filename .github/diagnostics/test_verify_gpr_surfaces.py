"""Synthetic HTTP/PDF fixtures exercise only the fixed read-only capture contour."""
from __future__ import annotations

import base64
import copy
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import urllib.error

import pytest

SCRIPT=Path(__file__).with_name('verify-gpr-surfaces.py')
spec=importlib.util.spec_from_file_location('surface_verify_test',SCRIPT)
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
ops=verify.ops
COMMIT='a'*40
KEY='Synthetic private administrator key'
PROJECT='Synthetic private project'
TODAY=dt.date(2026,11,10)
BUNDLE={'project':PROJECT,'old_cut':'2026-11-06','source_as_of':'2026-11-06','owner_rnv_note':'Synthetic owner note'}
OWNER={'revision':1,'date':'2027-09-30','source':'owner_decision','note':BUNDLE['owner_rnv_note'],
       'effective_from':'2026-11-10','recorded_at':'2026-11-10T09:00:00+00:00'}
PDF=b'%PDF-1.4\nSynthetic server PDF fixture\n%%EOF\n'
HTML='<h2>Finance before</h2><p>Private money must not enter JSON proof</p><h3>Сроки работ по корпусам</h3><section>30.09.2027 Real schedule renderer</section><h3>Фото со стройки за неделю</h3><p>Private photos</p><h2>Sales</h2>'


def schedule():
    return {'approved_plan':{'source_sha256':ops.SOURCE_SHA256,'revision':1,
            'baseline_scope':ops.BASELINE_SCOPE,'owner_rnv':copy.deepcopy(OWNER)},
        'owner_rnv':copy.deepcopy(OWNER),'corpus_gpr':{'sha256':ops.SOURCE_SHA256,'packages':[{'name':'Private work'}]},
        'rows':[{'name':'Private work','plan_finish':'2027-06-30'}],
        'management':[{'name':'Private work'}],'completed_facts':{'qualified_task_completions':[]},
        'money':{'private_total':12345},'payments':{'private_paid':6789}}


def report(cut):
    return {'kind':'week','end':cut,'gantt':{'corpus_gpr':{'sha256':ops.SOURCE_SHA256},
        'dependency_timeline':{'rnv':{'owner_rnv':copy.deepcopy(OWNER),'approved':'2027-09-30',
                                   'approved_source':'owner_decision'}}},
        'schedule':{'state':'ok'},'finance':{'private':12345}}


class Response(io.BytesIO):
    status=200
    def __init__(self,url,value,pdf=False):
        raw=value if pdf else json.dumps(value).encode();super().__init__(raw)
        self.url,self.headers=url,{'Content-Length':str(len(raw)),
            'Content-Type':'application/pdf' if pdf else 'application/json'}
    def geturl(self):return self.url


class Server:
    def __init__(self,mutation=None):self.calls=[];self.mutation=mutation
    def open(self,request,timeout):
        path=request.full_url.removeprefix(ops.BASE);body=json.loads(request.data) if request.data else None
        assert path in {'/health',*verify.ROUTES.values()}
        assert request.get_header('Authorization') is None and 0<timeout<=120
        self.calls.append((path,body))
        if path=='/health':response=Response(request.full_url,{'status':'ok','commit':COMMIT,'version':'0.28.93','data_writable':True})
        else:
            assert body['key']==KEY and body['project']==PROJECT and request.method=='POST'
            if path=='/monitor/view':
                assert set(body)=={'key','project','cut'}
                response=Response(request.full_url,{'snapshot':{'schedule':schedule(),'money':{'private':12345}},'trend':{'private':6789}})
            else:
                assert set(body)=={'key','project','kind','end'}
                assert body['kind']=='week' and 'sales_project' not in body
                response=(Response(request.full_url,PDF,pdf=True) if path.endswith('.pdf') else
                    Response(request.full_url,{'report':report(body['end']),'html':HTML,'text':'Private whole report'}))
        return self.mutation(request,response) if self.mutation else response


@pytest.fixture
def setup(monkeypatch,tmp_path):
    env={'RUNNER_TEMP':str(tmp_path),'EXPECTED_RUNTIME_COMMIT':COMMIT,'APPLY_ADMIN_KEY':KEY,'GITHUB_TOKEN':'Synthetic GitHub token'}
    monkeypatch.setattr(ops,'trusted_checkout',lambda environment:None)
    monkeypatch.setattr(ops,'decrypt_bundle',lambda *a,**k:copy.deepcopy(BUNDLE))
    monkeypatch.setattr(ops.Operation,'execute',lambda *a,**k:pytest.fail('surface capture attempted mutation'))
    recipient=tmp_path/'recipient.pem';recipient.write_bytes(b'Synthetic output certificate')
    monkeypatch.setattr(ops,'PUBLIC_RECIPIENT',recipient);monkeypatch.setattr(ops,'RECIPIENT_SHA256',ops.sha(recipient.read_bytes()))
    captured=[]
    def encrypt(proof,recipient,target,temporary,secrets=()):
        captured.append(copy.deepcopy(proof));target.write_bytes(b'Synthetic protected output')
        assert KEY in secrets and 'Synthetic GitHub token' in secrets
    monkeypatch.setattr(ops,'encrypt_proof',encrypt)
    provider=lambda temporary:(b'Synthetic ciphertext','Synthetic ephemeral private key')
    return env,provider,captured


def run(setup,server):
    env,provider,_=setup
    return verify.verify(env,input_provider=provider,opener=server,today=lambda:TODAY)


def test_only_readonly_surfaces_and_actual_response_pdf_are_captured(setup):
    server=Server();result=run(setup,server)
    assert result['ok'] and result['probe_only'] and not result['write_attempted'] and not result['outcome_unknown']
    assert result['monitor_verified'] and result['report_verified'] and result['server_pdfs_received']==2
    assert result['encrypted_proof_created'] and len(setup[2])==1
    proof=setup[2][0]
    for label in ['old_cut','current_cut']:
        value=proof['cuts'][label]
        assert base64.b64decode(value['server_pdf_base64'])==PDF
        assert 'money' not in value['monitor_schedule'] and 'payments' not in value['monitor_schedule']
        assert 'finance' not in value['report_schedule']
        assert 'Finance before' not in value['report_schedule']['schedule_html']
        assert 'Private photos' not in value['report_schedule']['schedule_html']
        assert 'Real schedule renderer' in value['report_schedule']['schedule_html']
    public=json.dumps(result)
    assert all(secret not in public for secret in [KEY,PROJECT,'Private work','Synthetic owner note','Synthetic GitHub token','https://'])
    assert len(server.calls)==9


@pytest.mark.parametrize('kind,label',[(ops.APPROVE,'old_cut'),(ops.PREVIEW,'old_cut'),
    ('/monitor/report/link','old_cut'),('https://evil.invalid','current_cut'),
    ('monitor','another_cut'),('pdf','2026-11-10'),('health','old_cut')])
def test_mutating_arbitrary_route_or_cut_is_rejected_before_http(kind,label):
    server=Server();reader=verify.SurfaceReader(COMMIT,opener=server)
    with pytest.raises(ops.ApplyError) as error:reader.request(kind,label)
    assert error.value.code==ops.FENCE and not server.calls


@pytest.mark.parametrize('mutation',[
    lambda value:value['approved_plan'].update(source_sha256='e'*64),
    lambda value:value['approved_plan'].update(revision=True),
    lambda value:value['approved_plan'].update(baseline_scope='full_schedule'),
    lambda value:value['approved_plan'].update(owner_rnv=None),
    lambda value:value['owner_rnv'].update(date='2027-09-29'),
    lambda value:value.update(rows=[]),lambda value:value.update(corpus_gpr=None)])
def test_unknown_wrong_source_or_owner_is_never_monitor_pass(mutation):
    value=schedule();mutation(value)
    assert not verify.schedule_matches(value,BUNDLE)


@pytest.mark.parametrize('kind',['wrong-type','wrong-magic','truncated','key-reflection','oversize','redirect','http-error','timeout'])
def test_pdf_or_transport_errors_are_sanitized_and_not_pass(setup,kind):
    def mutate(request,response):
        if not request.full_url.endswith('.pdf'):return response
        if kind=='wrong-type':response.headers['Content-Type']='text/html'
        if kind=='wrong-magic':response=Response(request.full_url,b'not a PDF %%EOF',pdf=True)
        if kind=='truncated':response=Response(request.full_url,b'%PDF-1.4 truncated',pdf=True)
        if kind=='key-reflection':response=Response(request.full_url,b'%PDF-1.4 '+KEY.encode()+b' %%EOF',pdf=True)
        if kind=='oversize':response.headers['Content-Length']=str(ops.MAX_RESPONSE+1)
        if kind=='redirect':response.url='https://evil.invalid'
        if kind=='http-error':raise urllib.error.HTTPError(request.full_url,503,KEY,{},io.BytesIO(PROJECT.encode()))
        if kind=='timeout':raise TimeoutError(KEY)
        return response
    result=run(setup,Server(mutate))
    assert not result['ok'] and not result['write_attempted'] and result['server_pdfs_received']==0
    assert KEY not in json.dumps(result) and PROJECT not in json.dumps(result)
    assert result['encrypted_proof_created'] # Partial schedule evidence remains protected.


def test_budget_exhaustion_cannot_create_a_successful_proof(setup,monkeypatch):
    monkeypatch.setattr(ops,'MAX_PROOF',100)
    result=run(setup,Server())
    assert not result['ok'] and result['error_code']==ops.PROOF and not result['write_attempted']


def test_output_encryption_failure_is_not_reported_as_completed_capture(setup,monkeypatch):
    def fail(*args,**kwargs):raise ops.ApplyError(ops.PROOF)
    monkeypatch.setattr(ops,'encrypt_proof',fail)
    result=run(setup,Server())
    assert not result['ok'] and not result['encrypted_proof_created'] and result['error_code']==ops.PROOF


def test_unknown_source_report_and_missing_server_html_never_pass():
    value=verify.report_projection(report(TODAY.isoformat()),HTML)
    value['gantt']['corpus_gpr']['sha256']='f'*64
    assert not verify.report_matches(value,BUNDLE,TODAY.isoformat())
    with pytest.raises(ops.ApplyError):verify.report_projection(report(TODAY.isoformat()),'No schedule renderer')


def test_verify_clock_stops_before_http_after_deadline():
    now=[0];server=Server();reader=verify.SurfaceReader(COMMIT,opener=server,clock=lambda:now[0])
    now[0]=901
    with pytest.raises(ops.ApplyError):reader.request('health')
    assert not server.calls


def test_workflow_is_fixed_readonly_verify_with_protected_artifact_and_cleanup():
    import yaml
    value=yaml.safe_load((SCRIPT.parents[1]/'workflows/prod-smoke.yml').read_text())
    assert value['permissions']=={'contents':'read'} and value['run-name']=='approved-gpr-source-surface-verify'
    job=value['jobs']['apply'];assert job['timeout-minutes']==35
    stage=next(step for step in job['steps'] if step.get('id')=='apply')
    assert stage['run']=='python3 .github/diagnostics/ephemeral-gpr-transport.py verify'
    proof=next(step for step in job['steps'] if step.get('with',{}).get('name')=='approved-gpr-apply-encrypted')
    assert proof['if']=="always() && steps.apply.outputs.proof_created == 'true'"
    assert job['steps'][-1]['if']=='always()' and 'gpr-session-' in job['steps'][-1]['run']



def test_projection_keeps_qualified_facts_without_duplicate_raw_ks_positions():
    inventory={'qualified_task_completions':[{'name':'Qualified old completed task'}],
               'counts':{'confirmed_works':1,'ks_positions':10000},
               'completed_ks_positions':[{'private_raw_row':index} for index in range(10000)]}
    value=schedule();value['completed_facts']=inventory
    value['dependency_timeline']={'rnv':{'completed_facts':inventory}}
    projection=verify.schedule_projection(value)
    assert projection['completed_facts']['qualified_task_completions']==inventory['qualified_task_completions']
    assert projection['completed_facts']['counts']==inventory['counts']
    assert 'completed_ks_positions' not in json.dumps(projection)
    assert len(json.dumps(projection))<3000
    assert verify.MAX_CAPTURE==24*1024*1024
