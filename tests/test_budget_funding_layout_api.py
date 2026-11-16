"""Real native auth/routes/job store, synthetic source pairs and no startup."""
import copy
import json
import time

import pytest
from fastapi.testclient import TestClient

import main as wrapper
import developaid_budget_funding_layout_proof as layout
import developaid_management_report_jobs as jobs
from test_budget_funding_layout_proof import pair, RUNTIME

START = '/monitor/audit/budget-funding/layout'
RESULT = START + '/result'
KEY = 'SYNTHETIC-LAYOUT-ADMIN'


@pytest.fixture
def api(pair, monkeypatch, tmp_path):
    core = wrapper.core
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setattr(core, 'COMMIT', RUNTIME['commit'])
    monkeypatch.setattr(core, 'VERSION', RUNTIME['version'])
    monkeypatch.setattr(core.developaid_monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    # No TestClient context manager: application startup services are never run.
    client = TestClient(core.app, raise_server_exceptions=False)
    body = {'key': KEY, 'session': '', 'purpose': layout.PURPOSE, 'scope': layout.SCOPE,
        'project': 'Synthetic', 'cut': '2026-11-13', 'ticket': '1'*32, 'expected': pair['expected']()}
    return client, body, pair, tmp_path/'monitor'


def finish(client, body):
    response = client.post(START, json=body)
    assert response.status_code in (200, 202), response.text
    ticket = response.json()['ticket']
    deadline = time.monotonic()+5
    while response.status_code == 202 and time.monotonic() < deadline:
        time.sleep(.005)
        response = client.post(RESULT, json={'key': KEY, 'session': '', 'purpose': layout.PURPOSE, 'ticket': ticket})
    assert response.status_code == 200, response.text
    return response


def test_native_job_roundtrip_contains_only_closed_layout_and_no_credential_metadata(api):
    client, body, pair, root = api
    response = finish(client, body)
    assert response.headers['cache-control'] == 'private, no-store'
    value = response.json()
    assert set(value) == {'pending', 'ticket', 'layout_proof'}
    assert value['layout_proof']['outcome'] == 'verified'
    assert layout.validate_projection(value['layout_proof']) == value['layout_proof']
    assert len(response.content) <= layout.MAX_WIRE
    assert pair['calls'] == ['fm','rss','fm','rss']
    files = list((root/'.admin_budget_funding_layout_proof_jobs').iterdir())
    assert files
    for path in files:
        assert KEY.encode() not in path.read_bytes()
    manifest = json.loads(next(path for path in files if path.suffix == '.json').read_text())
    assert manifest['profile'] == layout.PURPOSE
    assert 'Synthetic' not in json.dumps(manifest)


@pytest.mark.parametrize('path', [START, RESULT])
def test_auth_precedes_producer_source_and_job_IO(api, monkeypatch, path):
    client, body, pair, root = api
    def forbidden(*a, **k):pytest.fail('unauthorized I/O')
    monkeypatch.setattr(layout, 'producer_hashes', forbidden)
    monkeypatch.setattr(jobs.Store, '__init__', forbidden)
    body = {**body, 'key': 'wrong'} if path == START else {
        'key': 'wrong', 'session': '', 'purpose': layout.PURPOSE, 'ticket': '1'*32}
    answer = client.post(path, json=body)
    assert answer.status_code == 403
    assert answer.headers['cache-control'] == 'private, no-store'
    assert pair['calls'] == [] and not root.exists()


@pytest.mark.parametrize('fault', ['extra', 'runtime', 'producer', 'duplicate', 'oversize'])
def test_bad_request_binding_cannot_enter_job_or_source(api, monkeypatch, fault):
    client, body, pair, root = api
    def forbidden(*a, **k):pytest.fail('invalid request entered store')
    monkeypatch.setattr(jobs.Store, '__init__', forbidden)
    body = copy.deepcopy(body)
    if fault == 'extra':body['filename'] = 'not-allowed.xlsx'
    elif fault == 'runtime':body['expected']['runtime_commit'] = 'f'*40
    elif fault == 'producer':body['expected']['producer_sha256']['budget_source'] = 'f'*64
    if fault == 'duplicate':
        encoded = json.dumps(body)[:-1]+',"purpose":"'+layout.PURPOSE+'"}'
        answer = client.post(START, content=encoded, headers={'content-type':'application/json'})
    elif fault == 'oversize':
        answer = client.post(START, content=b' '*(layout.MAX_REQUEST+1))
    else:
        answer = client.post(START, json=body)
    assert answer.status_code in (400,409,413), answer.text
    assert pair['calls'] == [] and not root.exists()


def test_result_is_bound_to_owner_session_profile_and_request(api):
    client, body, pair, root = api
    finish(client, body)
    changed = copy.deepcopy(body);changed['cut'] = '2026-11-12'
    assert client.post(START, json=changed).status_code == 409
    answer = client.post(RESULT, json={'key': KEY, 'session': 'another-session',
        'purpose': layout.PURPOSE, 'ticket': body['ticket']})
    assert answer.status_code == 404
    answer = client.post('/monitor/audit/budget-funding/result',
        json={'key':KEY,'session':'','ticket':body['ticket']})
    assert answer.status_code == 404
    assert pair['calls'] == ['fm','rss','fm','rss']


def test_wire_cap_fails_closed_without_financial_fallback(api, monkeypatch):
    client, body, pair, root = api
    monkeypatch.setattr(layout, 'MAX_WIRE', 10)
    answer = client.post(START, json=body)
    assert answer.status_code == 503
    # Let the synthetic native worker finish before fixture teardown.
    store = jobs.Store(root/'.admin_budget_funding_layout_proof_jobs')
    owner = jobs.owner_binding(KEY, '', layout.PURPOSE)
    deadline = time.monotonic()+5
    while store.poll(body['ticket'], owner, layout.PURPOSE)['pending'] and time.monotonic() < deadline:
        time.sleep(.005)
    assert len(pair['calls']) == 4
