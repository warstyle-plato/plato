"""Offline, credential-free execution of the exact protected workflow script."""
from __future__ import annotations
import ast
import io
import json
from pathlib import Path
import types
import urllib.error
import urllib.parse
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/prod-smoke.yml'
RUNTIME = '2061d1a01d7607eb44113bc2cc429abfaf4814de'
PROJECT = 'Synthetic private project'
KEY = 'synthetic-key-must-never-appear-in-output'
PRIVATE = 'synthetic-private-financial-source'


def script():
    text = WORKFLOW.read_text()
    raw = text.split("          python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    return '\n'.join(line[10:] if line.startswith(' '*10) else line for line in raw.splitlines())


@pytest.fixture
def probe():
    namespace = {'__name__': 'offline_private_financial_probe'}
    exec(compile(script(), str(WORKFLOW), 'exec'), namespace)
    return types.SimpleNamespace(**namespace)


def view():
    return {'snapshot': {'cut': '2026-11-09', 'source': {'estimate': '2026-11-05'},
        'money': {'payment_fact': 2468.13}, 'payments': {'unknown_count': 59},
        'dashboard': {'construction': {'approved': 120000.99, 'limit': 90000.01},
          'funding': {'known': True, 'own_money': {
              'budget': 123456.78, 'paid': 2468.13, 'limit': 100000.01,
              'left': 97531.88, 'need': 23456.77,
              'rows': [{'chapter': '2', 'amount': 20000.01}, {'chapter': '3', 'amount': 3456.76}]},
            'source_dates': {'report_date': '2026-11-09',
                'rss': {'data_date': '2026-11-05', 'file': PRIVATE+'.xlsx'},
                'budget': {'data_date': '2026-10-01', 'uploaded_at': '2026-11-01T10:00:00Z'},
                'schedule': {'data_date': None}}}, 'sources': {'financial_baseline': PRIVATE}},
        'schedule': {'irrelevant_schedule_private_data': 'not required'}},
        'trend': [{'irrelevant_historical_private_data': 'not required'}]}


def register():
    return {'snapshots': {'rss': '2026-11-05', 'cumulative_id': '2026-11-06-'+'a'*64},
            'rows': [{'id': '1'*64}], 'unmatched_works': []}


class Response:
    status = 200
    def __init__(self, payload, url):
        self.stream = io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.url = url
    def geturl(self): return self.url
    def read1(self, count): return self.stream.read(count)
    def __enter__(self): return self
    def __exit__(self, *args): pass


class Transport:
    def __init__(self, change=None):
        self.calls, self.views, self.healths, self.timeouts = [], 0, 0, []
        self.change = change
    def open(self, request, timeout):
        self.calls.append(request)
        path = urllib.parse.urlsplit(request.full_url).path
        self.timeouts.append((path,timeout))
        assert 0 < timeout <= (60 if path=='/monitor/view' else 15)
        assert request.full_url.startswith('https://developaid.ru/')
        path = urllib.parse.urlsplit(request.full_url).path
        body = json.loads(request.data) if request.data else None
        if path == '/health':
            self.healths += 1
            payload = {'status': 'ok', 'commit': RUNTIME, 'version': '0.28.84'}
            if self.change == 'runtime' and self.healths > 1: payload['commit'] = 'f'*40
        elif path == '/monitor/report/projects':
            payload = {'projects': [{'project': PROJECT, 'data': ['cumulative', 'estimate']}]}
        elif path == '/monitor/contracts/build':
            payload = {'pending': False, 'ticket': 'b'*32, 'register': register()}
        elif path == '/monitor/view':
            self.views += 1
            assert body == {'project': PROJECT, 'cut': '2026-11-09', 'key': KEY}
            payload = view()
            if self.views == 2:
                funding = payload['snapshot']['dashboard']['funding']
                if self.change == 'amount': funding['own_money']['budget'] += 1
                if self.change == 'date': funding['source_dates']['budget']['data_date'] = '2026-10-02'
                if self.change == 'revision': funding['source_dates']['budget']['uploaded_at'] = '2026-11-02T10:00:00Z'
        else: pytest.fail('Unexpected outbound path: '+path)
        return Response(payload, request.full_url)


def execute(probe, monkeypatch, tmp_path, change=None, encryption_ok=True):
    transport = Transport(change)
    captured = []
    def encrypt(args, **kwargs):
        assert args == ['openssl', 'cms', '-encrypt', '-aes-256-gcm', '-binary', '-outform', 'DER',
                        '-recip', '.github/diagnostics/contract-audit-recipient.pem',
                        '-keyopt', 'rsa_padding_mode:oaep', '-keyopt', 'rsa_oaep_md:sha256']
        assert set(kwargs['env']) == {'PATH'} and kwargs['timeout'] == 30
        captured.append(json.loads(kwargs['input']))
        kwargs['stdout'].write(b'SyntheticCiphertextOnly')
        return types.SimpleNamespace(returncode=0 if encryption_ok else 1)
    monkeypatch.setattr(probe.subprocess, 'run', encrypt)
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path))
    return probe.Probe(RUNTIME, opener=transport, clock=lambda: 0, sleep=lambda _: None), transport, captured


def test_success_encrypts_exact_financial_projection_and_only_publishes_flags(probe, monkeypatch, tmp_path, capsys):
    runner, transport, captured = execute(probe, monkeypatch, tmp_path)
    result = runner.run(lambda: KEY)
    assert transport.views == 2 and transport.healths == 2
    assert len(captured) == 1
    private = captured[0]
    assert KEY not in json.dumps(private)
    projection = probe.financial_projection(view(), register())
    assert set(private)=={'runtime_commit','run_id','project','cut','rss_date','financial_view'}
    assert not any('gpr' in request.full_url or 'physical' in request.full_url for request in transport.calls)
    assert {timeout for path,timeout in transport.timeouts if path=='/monitor/view'}=={60}
    assert all(timeout<=15 for path,timeout in transport.timeouts if path!='/monitor/view')
    assert private['financial_view'] == projection
    assert private['financial_view']['dashboard']['funding']['own_money']['budget'] == 123456.78
    assert 'trend' not in projection and 'schedule' not in projection
    public = json.dumps(result)
    assert all(type(value) in (bool, int) for key, value in result.items() if key.startswith('financial_'))
    assert result['financial_component_rows'] == 2
    for forbidden in (KEY, PROJECT, PRIVATE, '123456.78', '2026-11-09', '2026-11-05'):
        assert forbidden not in public and forbidden not in capsys.readouterr().out
    files = list(tmp_path.iterdir())
    assert [p.name for p in files] == ['contracts-audit.cms']
    assert files[0].read_bytes() == b'SyntheticCiphertextOnly'
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert all(request.method == ('GET' if request.full_url.endswith('/health') else 'POST') for request in transport.calls)


@pytest.mark.parametrize('runtime', ['', 'f'*40, RUNTIME+'?query', None])
def test_wrong_runtime_rejected_before_transport_or_key_access(probe, runtime):
    with pytest.raises(probe.ProbeError, match='invalid_expected_commit'):
        probe.Probe(runtime, opener=object())


@pytest.mark.parametrize('change', ['amount', 'date', 'revision', 'runtime'])
def test_runtime_and_financial_source_drift_prevent_encrypted_publication(probe, monkeypatch, tmp_path, change):
    runner, transport, captured = execute(probe, monkeypatch, tmp_path, change)
    with pytest.raises(probe.ProbeError, match='runtime_mismatch' if change=='runtime' else 'financial_source_changed'):
        runner.run(lambda: KEY)
    assert captured == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('path', ['/monitor/estimate', '/monitor/contracts/link', '/monitor/view?url=elsewhere',
                                 'https://elsewhere.invalid/monitor/view', '//elsewhere.invalid/monitor/view',
                                 '/monitor/gpr-corpus/view','/monitor/schedule-gpr-physical/view'])
def test_existing_reader_allowlist_does_not_expand_to_writes_or_arbitrary_urls(probe, path):
    runner = probe.Probe(RUNTIME, opener=object())
    with pytest.raises(probe.ProbeError, match='invalid_payload'):
        runner.request(path, {'key': KEY})


@pytest.mark.parametrize('change', ['cut', 'rss', 'register-rss', 'report-date', 'funding-type', 'money-type', 'nan', 'bad-date'])
def test_unqualified_dates_types_or_nonfinite_financial_values_fail_closed(probe, change):
    payload, reg = view(), register()
    snapshot = payload['snapshot']; funding = snapshot['dashboard']['funding']
    if change == 'cut': snapshot['cut'] = '2026-11-10'
    if change == 'rss': snapshot['source']['estimate'] = '2026-11-06'
    if change == 'register-rss': reg['snapshots']['rss'] = '2026-11-06'
    if change == 'report-date': funding['source_dates']['report_date'] = '2026-11-10'
    if change == 'funding-type': funding['known'] = 1
    if change == 'money-type': funding['own_money']['budget'] = True
    if change == 'nan': funding['own_money']['budget'] = float('nan')
    if change == 'bad-date': funding['source_dates']['budget']['data_date'] = '2026-02-31'
    with pytest.raises(probe.ProbeError): probe.financial_projection(payload, reg)


def test_unknown_money_stays_unknown_and_zero_stays_zero(probe):
    payload = view(); funding = payload['snapshot']['dashboard']['funding']
    funding['own_money']['need'] = 0; funding['own_money']['left'] = None
    projected = probe.financial_projection(payload, register())['dashboard']['funding']['own_money']
    assert projected['need'] == 0 and projected['left'] is None
    funding['own_money'] = None; funding['known'] = False
    assert probe.financial_projection(payload, register())['dashboard']['funding']['own_money'] is None


def test_redirect_and_oversized_response_are_rejected_without_credentials_in_exception(probe):
    class Redirect:
        def open(self, request, timeout): return Response({}, 'https://elsewhere.invalid/')
    runner = probe.Probe(RUNTIME, opener=Redirect()); runner._financial_project = PROJECT
    body = {'project': PROJECT, 'cut': '2026-11-09', 'key': KEY}
    with pytest.raises(probe.ProbeError, match='redirect_denied') as exc:
        runner.request('/monitor/view', body)
    assert KEY not in str(exc.value)
    class Large:
        def open(self, request, timeout): return Response(b'x'*(probe.MAX_BYTES+1), request.full_url)
    runner = probe.Probe(RUNTIME, opener=Large()); runner._financial_project = PROJECT
    with pytest.raises(probe.ProbeError, match='response_too_large'):
        runner.request('/monitor/view', body)


@pytest.mark.parametrize('change', ['programme', 'extra', 'project', 'cut', 'missing-key', 'unbound-project'])
def test_financial_transport_schema_cannot_be_used_as_a_generic_monitor_request(probe, change):
    runner = probe.Probe(RUNTIME, opener=object()); runner._financial_project = PROJECT
    body = {'project': PROJECT, 'cut': '2026-11-09', 'key': KEY}
    if change == 'programme': body['programme_base64'] = 'not permitted'
    if change == 'extra': body['upto'] = ''
    if change == 'project': body['project'] = 'Another project'
    if change == 'cut': body['cut'] = '2026-11-10'
    if change == 'missing-key': body.pop('key')
    if change == 'unbound-project': runner._financial_project = None
    with pytest.raises(probe.ProbeError, match='invalid_payload'):
        runner.request('/monitor/view', body)


@pytest.mark.parametrize('node,field', [('snapshot','money'),('snapshot','payments'),
    ('dashboard','construction'),('dashboard','sources'),('own_money','budget'),('own_money','rows')])
def test_required_financial_evidence_is_not_silently_replaced_with_an_empty_mapping(probe,node,field):
    payload = view();snapshot=payload['snapshot'];dashboard=snapshot['dashboard']
    parent={'snapshot':snapshot,'dashboard':dashboard,'own_money':dashboard['funding']['own_money']}[node]
    parent.pop(field)
    with pytest.raises(probe.ProbeError, match='invalid_payload'):
        probe.financial_projection(payload,register())


def test_deadline_is_total_and_encryption_failure_drops_the_artifact(probe, monkeypatch, tmp_path):
    ticks = iter([0, probe.TOTAL_SECONDS+1])
    class NeverTransport:
        def open(self, *args, **kwargs): pytest.fail('Expired operation reached transport')
    runner = probe.Probe(RUNTIME, opener=NeverTransport(), clock=lambda: next(ticks))
    with pytest.raises(probe.ProbeError, match='deadline'): runner.request('/health')
    runner, _, _ = execute(probe, monkeypatch, tmp_path, encryption_ok=False)
    with pytest.raises(probe.ProbeError, match='unexpected_error'): runner.run(lambda: KEY)
    assert list(tmp_path.iterdir()) == []


def test_route_is_the_actual_readonly_schema_and_the_recipient_is_only_public():
    module = ast.parse((ROOT/'engine/monitor.py').read_text())
    request = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name=='MonitorViewRequest')
    fields = {n.target.id for n in request.body if isinstance(n, ast.AnnAssign)}
    assert {'project', 'cut', 'key'} <= fields
    handler = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name=='monitor_view')
    calls = [n for n in ast.walk(handler) if isinstance(n, ast.Call)]
    access = next(n for n in calls if isinstance(n.func, ast.Name) and n.func.id=='_require_team_access')
    assert any(k.arg=='write' and isinstance(k.value, ast.Constant) and k.value.value is False for k in access.keywords)
    monitor_calls = [n.func.attr for n in calls if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id=='developaid_monitor']
    assert set(monitor_calls) == {'build', 'trend'}
    cert = (ROOT/'.github/diagnostics/contract-audit-recipient.pem').read_text()
    assert 'BEGIN CERTIFICATE' in cert and 'PRIVATE KEY' not in cert
    assert 'workflow_dispatch:' in WORKFLOW.read_text()
    assert 'runs-on: ubuntu-latest' in WORKFLOW.read_text()
    assert 'retention-days: 1' in WORKFLOW.read_text()


@pytest.mark.parametrize('failure', ['auth', 'invalid-json', 'encryption'])
def test_real_entrypoint_redacts_failure_stdout_stderr_and_never_keeps_plaintext(probe,monkeypatch,tmp_path,capsys,failure):
    _, transport, _ = execute(probe,monkeypatch,tmp_path,encryption_ok=failure!='encryption')
    original = transport.open
    def fail(request,timeout):
        if not request.full_url.endswith('/health') and failure in {'auth','invalid-json'}:
            if failure == 'auth':
                raise urllib.error.HTTPError(request.full_url,403,KEY+PRIVATE,None,io.BytesIO(PROJECT.encode()))
            return Response((KEY+PRIVATE+PROJECT).encode(),request.full_url)
        return original(request,timeout)
    transport.open = fail
    monkeypatch.setattr(probe.urllib.request,'build_opener',lambda *args:transport)
    monkeypatch.setenv('EXPECTED_COMMIT',RUNTIME);monkeypatch.setenv('PROBE_ADMIN_KEY',KEY)
    monkeypatch.setattr(probe.signal,'signal',lambda *args:None)
    monkeypatch.setattr(probe.signal,'alarm',lambda *args:None)
    assert probe.main()==1
    out=capsys.readouterr();public=json.loads(out.out)
    assert public['status']=='error'
    assert type(public['phase_code']) is int
    assert public['phase_code']==(80 if failure=='encryption' else 30)
    assert public['reason_code']=={'auth':'http_auth','invalid-json':'invalid_json','encryption':'unexpected_error'}[failure]
    for forbidden in (KEY,PRIVATE,PROJECT,'123456.78'):
        assert forbidden not in out.out+out.err
    assert out.err=='' and list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('elapsed,path,expected',[(0,'/health',15),(0,'/monitor/view',60),
    (345,'/monitor/view',15),(355,'/health',5)])
def test_each_call_timeout_respects_both_route_budget_and_original_total_deadline(probe,elapsed,path,expected):
    now=[0];seen=[]
    class Budget:
        def open(self,request,timeout):seen.append(timeout);return Response({},request.full_url)
    runner=probe.Probe(RUNTIME,opener=Budget(),clock=lambda:now[0]);runner._financial_project=PROJECT
    now[0]=elapsed
    runner.request(path,{'project':PROJECT,'cut':'2026-11-09','key':KEY} if path=='/monitor/view' else None)
    assert seen==[expected]
    now[0]=360
    with pytest.raises(probe.ProbeError,match='deadline'):
        runner.request(path,{'project':PROJECT,'cut':'2026-11-09','key':KEY} if path=='/monitor/view' else None)
    assert len(seen)==1


def test_async_register_admitted_once_and_financial_reads_never_add_gpr_or_pagination_calls(probe,monkeypatch,tmp_path):
    runner,transport,captured=execute(probe,monkeypatch,tmp_path);original=transport.open;polls=[]
    def pending(request,timeout):
        path=urllib.parse.urlsplit(request.full_url).path
        if path=='/monitor/contracts/build':
            transport.calls.append(request);return Response({'pending':True,'ticket':'b'*32},request.full_url)
        if path=='/monitor/contracts/result':
            transport.calls.append(request);polls.append(1)
            return Response({'pending':len(polls)<2,'ticket':'b'*32,'register':register()},request.full_url)
        return original(request,timeout)
    transport.open=pending
    runner.run(lambda:KEY)
    paths=[urllib.parse.urlsplit(request.full_url).path for request in transport.calls]
    assert paths.count('/monitor/contracts/build')==1 and paths.count('/monitor/contracts/result')==2
    assert paths.count('/monitor/view')==2 and paths.count('/health')==2
    assert set(paths)=={'/health','/monitor/report/projects','/monitor/contracts/build','/monitor/contracts/result','/monitor/view'}
    assert len(captured)==1 and 'register' not in captured[0]


@pytest.mark.parametrize('stage,expected_phase',[('start-health',10),('projects',30),('register',40),('first-view',50),('second-view',60),('end-health',70)])
def test_transport_failure_reports_only_a_safe_phase_integer(probe,monkeypatch,tmp_path,capsys,stage,expected_phase):
    _,transport,_=execute(probe,monkeypatch,tmp_path);original=transport.open;calls={'health':0,'view':0}
    def fail(request,timeout):
        path=urllib.parse.urlsplit(request.full_url).path
        if path=='/health':calls['health']+=1
        if path=='/monitor/view':calls['view']+=1
        at=(stage=='start-health' and path=='/health' and calls['health']==1 or
            stage=='end-health' and path=='/health' and calls['health']==2 or
            stage=='projects' and path=='/monitor/report/projects' or
            stage=='register' and path=='/monitor/contracts/build' or
            stage=='first-view' and path=='/monitor/view' and calls['view']==1 or
            stage=='second-view' and path=='/monitor/view' and calls['view']==2)
        if at:raise TimeoutError(KEY+PROJECT+PRIVATE+'https://private.invalid')
        return original(request,timeout)
    transport.open=fail
    monkeypatch.setattr(probe.urllib.request,'build_opener',lambda *args:transport)
    monkeypatch.setenv('EXPECTED_COMMIT',RUNTIME);monkeypatch.setenv('PROBE_ADMIN_KEY',KEY)
    monkeypatch.setattr(probe.signal,'signal',lambda *args:None);monkeypatch.setattr(probe.signal,'alarm',lambda *args:None)
    assert probe.main()==1
    out=capsys.readouterr();result=json.loads(out.out)
    assert result['reason_code']=='transport_failure' and type(result['phase_code']) is int and result['phase_code']==expected_phase
    assert all(value not in out.out+out.err for value in (KEY,PROJECT,PRIVATE,'https://'))
    assert out.err=='' and list(tmp_path.iterdir())==[]


def test_wrong_register_rss_rejects_before_any_heavy_financial_read(probe,monkeypatch,tmp_path):
    runner,transport,captured=execute(probe,monkeypatch,tmp_path);original=transport.open
    def drift(request,timeout):
        if request.full_url.endswith('/monitor/contracts/build'):
            transport.calls.append(request);r=register();r['snapshots']['rss']='2026-11-06'
            return Response({'pending':False,'ticket':'b'*32,'register':r},request.full_url)
        return original(request,timeout)
    transport.open=drift
    with pytest.raises(probe.ProbeError,match='runtime_mismatch'):
        runner.run(lambda:KEY)
    assert runner.phase_code==40 and transport.views==0 and captured==[]
    assert not list(tmp_path.iterdir())
