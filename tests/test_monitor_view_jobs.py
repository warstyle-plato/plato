"""Slow Monitor calculation cannot hold the page's HTTP request or hide other work."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import developaid_monitor as monitor
import main as wrapper

core = wrapper.core
KEY = 'synthetic-monitor-view-owner'


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    return TestClient(core.app), tmp_path


def call(client, path='', *, key=KEY, session='', **data):
    return client.post('/monitor/view'+path, json={'key': key, 'session': session, **data})


def poll(client, ticket, **auth):
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        result = call(client, '/result', ticket=ticket, **auth)
        if result.status_code != 202:
            return result
        time.sleep(.01)
    pytest.fail('Synthetic view job did not finish')


def test_slow_view_admission_is_short_retry_is_single_and_history_is_not_built(api, monkeypatch):
    client, root = api
    release = threading.Event()
    seen = []
    def build(project, **kwargs):
        seen.append((project, kwargs))
        assert release.wait(5)
        return {'cut': kwargs['cut'], 'schedule': {'approved_plan': {'revision': 4}}}
    monkeypatch.setattr(monitor, 'build', build)
    monkeypatch.setattr(monitor, 'trend', lambda *a, **k: pytest.fail('History delays the current view'))
    body = dict(project='Fixture', cut='2026-11-10', background=True, ticket='1'*32)
    try:
        start_time = time.monotonic()
        response = call(client, session='fixture-session', **body)
        assert response.status_code == 202 and time.monotonic()-start_time < 1
        assert response.headers['cache-control'] == 'private, no-store'
        assert call(client, session='fixture-session', **body).json()['ticket'] == body['ticket']
        assert call(client, '/result', session='fixture-session', ticket=body['ticket']).status_code == 202
    finally:
        release.set()
    result = poll(client, body['ticket'], session='fixture-session')
    assert result.status_code == 200 and result.json()['snapshot']['schedule']['approved_plan']['revision'] == 4
    assert seen == [('Fixture', {'cut': '2026-11-10'})]
    private = b''.join(f.read_bytes() for f in (root/'monitor'/'.view_jobs').iterdir() if f.is_file())
    assert KEY.encode() not in private and b'fixture-session' not in private


@pytest.mark.parametrize('path,data', [('', {'project': 'Fixture', 'cut': 'bad', 'background': True}),
                                      ('/result', {'ticket': 'a'*32})])
def test_admission_and_lookup_require_current_administrator_before_storage(api, monkeypatch, path, data):
    client, root = api
    monkeypatch.setattr(monitor, 'build', lambda *a, **k: pytest.fail('Unauthorized calculation'))
    for key in ('', 'wrong'):
        result = call(client, path, key=key, **data)
        assert result.status_code == 403
        assert result.headers['cache-control'] == 'private, no-store'
    assert not (root/'monitor'/'.view_jobs').exists()


def test_result_is_bound_to_owner_key_and_exact_request(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(monitor, 'build', lambda project, **k: {'project': project})
    body = dict(project='Fixture', cut='2026-11-10', background=True, ticket='2'*32)
    ticket = call(client, session='A', **body).json()['ticket']
    assert poll(client, ticket, session='A').json()['snapshot']['project'] == 'Fixture'
    assert call(client, '/result', session='B', ticket=ticket).status_code == 404
    assert call(client, session='A', **dict(body, project='Other')).status_code == 409
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'rotated-synthetic-key')
    assert call(client, '/result', session='A', ticket=ticket).status_code == 403
    assert call(client, '/result', session='A', key='rotated-synthetic-key', ticket=ticket).status_code == 404


def test_fresh_click_does_not_reuse_inflight_view_and_failure_explains_calculation(api, monkeypatch):
    client, _ = api
    release = threading.Event()
    calls = []
    def build(*a, **k):
        calls.append(1)
        assert release.wait(5)
        raise FileNotFoundError('PRIVATE_SOURCE_PATH')
    monkeypatch.setattr(monitor, 'build', build)
    try:
        a = call(client, project='Fixture', cut='2026-11-10', background=True, ticket='3'*32)
        b = call(client, project='Fixture', cut='2026-11-10', background=True, ticket='4'*32)
        assert a.status_code == b.status_code == 202
        assert a.json()['ticket'] != b.json()['ticket']
    finally:
        release.set()
    result = poll(client, a.json()['ticket'])
    assert result.status_code == 500 and 'план и факт' in result.json()['detail']
    assert 'PRIVATE_SOURCE_PATH' not in result.text and len(calls) == 2


@pytest.mark.parametrize('cut', ['2026-02-31', 'bad', '20261110'])
def test_invalid_date_is_rejected_without_background_work(api, monkeypatch, cut):
    client, _ = api
    monkeypatch.setattr(monitor, 'build', lambda *a, **k: pytest.fail('Invalid date reached worker'))
    assert call(client, project='Fixture', cut=cut, background=True).status_code == 400
