"""A complete private report can exceed the old job budget without losing data."""
import json
import time

import pytest
from fastapi.testclient import TestClient

import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import main as wrapper

core = wrapper.core
KEY = 'synthetic-summary-budget-key'
PARAMS = {'project': 'Fixture', 'kind': 'week', 'end': '2026-11-26'}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    return TestClient(core.app), tmp_path / 'monitor' / '.report_jobs'


def call(client, path, **payload):
    return client.post('/monitor/report/' + path, json={'key': KEY, **payload})


def poll(client, ticket):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        response = call(client, 'result', ticket=ticket)
        if response.status_code != 202:
            return response
        time.sleep(.01)
    pytest.fail('Synthetic report did not finish')


def large_result():
    return {'report': {'financial_observation': {'value': 123.45, 'source': 'fixture'}},
            'text': 'complete fixture report', 'html': 'x' * (jobs.MAX_RESULT_BYTES + 1024)}


def test_a_valid_report_larger_than_legacy_limit_is_complete_and_built_once(api, monkeypatch):
    client, root = api
    result, calls = large_result(), []
    def build(*args, **kwargs):
        calls.append(1)
        return result
    monkeypatch.setattr(core, '_monitor_report_body', build)
    ticket = call(client, 'build', **PARAMS).json()['ticket']
    response = poll(client, ticket)
    assert response.status_code == 200
    assert {key: response.json()[key] for key in result} == result
    assert poll(client, ticket).json() == response.json()
    assert calls == [1]
    meta = json.loads((root / (ticket + '.json')).read_text())
    assert meta['result_limit_bytes'] == jobs.MAX_EXTENDED_RESULT_BYTES == 64 * 1024 * 1024
    assert response.headers['cache-control'] == 'private, no-store'


def test_client_cannot_raise_the_server_report_budget(api, monkeypatch):
    client, root = api
    monkeypatch.setattr(core, '_monitor_report_body', lambda *a, **k: {'html': '<p>Fixture</p>'})
    ticket = call(client, 'build', **PARAMS, result_limit_bytes=2**40).json()['ticket']
    assert poll(client, ticket).status_code == 200
    assert json.loads((root / (ticket + '.json')).read_text())['result_limit_bytes'] == jobs.MAX_EXTENDED_RESULT_BYTES


def test_report_larger_than_server_budget_fails_with_safe_category(api, monkeypatch):
    client, root = api
    monkeypatch.setattr(jobs, 'MAX_EXTENDED_RESULT_BYTES', jobs.MAX_RESULT_BYTES + 16)
    monkeypatch.setattr(core, '_monitor_report_body', lambda *a, **k: large_result())
    ticket = call(client, 'build', **PARAMS).json()['ticket']
    response = poll(client, ticket)
    assert response.status_code == 500
    assert response.headers['x-monitor-job-error'] == 'result_too_large'
    assert not (root / (ticket + '.result')).exists()
    assert KEY not in response.text


@pytest.mark.parametrize('failure,expected', [
    ('builder', 'builder_failed'), ('nonfinite', 'serialization_failed'),
    ('source', 'source_changed'), ('untrusted_code', 'builder_failed')])
def test_report_failures_expose_only_closed_safe_categories(api, monkeypatch, caplog, failure, expected):
    client, root = api
    private = 'PRIVATE_CLIENT_OR_AMOUNT_MUST_NOT_LEAK'
    def build(*args, **kwargs):
        if failure == 'builder':
            raise ValueError(private)
        if failure == 'source':
            raise jobs.JobProblem(409, private, code='source_changed')
        if failure == 'untrusted_code':
            problem = jobs.JobProblem(500, private)
            problem.code = private
            raise problem
        return {'html': private, 'value': float('nan')}
    monkeypatch.setattr(core, '_monitor_report_body', build)
    ticket = call(client, 'build', **PARAMS).json()['ticket']
    response = poll(client, ticket)
    assert response.status_code == 500
    assert response.headers['x-monitor-job-error'] == expected
    assert private not in response.text + caplog.text
    assert all(private.encode() not in path.read_bytes() and KEY.encode() not in path.read_bytes()
               for path in root.iterdir() if path.is_file())


def test_existing_legacy_ticket_keeps_its_original_budget_without_rebuild(api, monkeypatch):
    client, root = api
    import developaid_monitor_ledgers as ledgers
    context = ledgers.snapshot_job_context(PARAMS['project'])
    store = jobs.Store(root, context_validator=ledgers.validate_snapshot_job_context)
    result, calls = large_result(), []
    def old_build():
        calls.append(1)
        return result
    old = '9' * 32
    owner = jobs.owner_binding(KEY, '', 'admin')
    store.start(owner, 'admin', {**PARAMS, 'sales_project': None}, old_build, old, context=context)
    assert poll(client, old).status_code == 500
    assert call(client, 'build', **PARAMS, ticket=old).status_code == 500
    assert calls == [1]
    assert 'result_limit_bytes' not in json.loads((root / (old + '.json')).read_text())
    monkeypatch.setattr(core, '_monitor_report_body', lambda *a, **k: result)
    fresh = call(client, 'build', **PARAMS).json()['ticket']
    assert fresh != old and poll(client, fresh).status_code == 200


def test_unrelated_legacy_job_family_retains_the_16mib_default(tmp_path):
    store = jobs.Store(tmp_path / 'other-family')
    owner = jobs.owner_binding(KEY, '', 'admin')
    ticket = 'a' * 32
    store.start(owner, 'admin', PARAMS, large_result, ticket)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        try:
            state = store.poll(ticket, owner, 'admin')
        except jobs.JobProblem as exc:
            assert exc.status == 500 and exc.code == ''
            break
        assert state['pending']
        time.sleep(.01)
    else:
        pytest.fail('Synthetic legacy family did not finish')
    assert 'result_limit_bytes' not in json.loads((store.root / (ticket + '.json')).read_text())
