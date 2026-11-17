"""Whole Monitor DTOs retain all fields inside a server-owned job budget."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
import pytest

import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import main as wrapper

core = wrapper.core
KEY = 'synthetic-view-budget-key'
SESSION = 'synthetic-view-owner'
PROJECT = 'Synthetic full view'
CUT = '2026-11-06'
TICKET = 'a' * 32
PRIVATE = 'SYNTHETIC_PRIVATE_EXCEPTION_CONTENT'
SMALL = {'cut': CUT, 'schedule': {'rows': []},
         'finance': {'amount': None, 'zero': 0, 'refund': -25}, 'date': dt.date(2026, 11, 6)}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setattr(monitor, 'build', lambda *args, **kwargs: SMALL)
    return TestClient(core.app), jobs.Store(monitor._SNAPSHOT_DIR / '.view_jobs')


def post(client, *, start=False, key=KEY, session=SESSION, ticket=TICKET, **extra):
    body = {'ticket': ticket, 'key': key, 'session': session}
    if start:
        body.update(project=PROJECT, cut=CUT, background=True)
    return client.post('/monitor/view' if start else '/monitor/view/result', json={**body, **extra})


def terminal(client, **auth):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = post(client, **auth)
        if response.status_code != 202:
            return response
        time.sleep(.01)
    pytest.fail('Synthetic view job did not finish')


def test_full_view_over_default_limit_roundtrips_every_projection(api, monkeypatch):
    client, store = api
    observed = {'source_text': 'я' * (5 * 1024 * 1024), 'quantity': None,
                'zero': 0, 'refund': -25}
    snapshot = {'schedule': {'rows': [{'raw': observed}]},
                'finance': {'observations': [observed]}, 'cut': CUT}
    size = len(json.dumps({'snapshot': snapshot}, ensure_ascii=False, allow_nan=False).encode())
    assert jobs.MAX_RESULT_BYTES < size < jobs.MAX_EXTENDED_RESULT_BYTES
    calls = []
    def build(*args, **kwargs):
        calls.append(1)
        return snapshot
    monkeypatch.setattr(monitor, 'build', build)
    assert post(client, start=True).status_code == 202
    response = terminal(client)
    assert response.status_code == 200
    assert response.json() == {'pending': False, 'ticket': TICKET, 'snapshot': snapshot}
    assert store._path(TICKET, 'result').stat().st_size == size
    assert store._meta(TICKET)['result_limit_bytes'] == jobs.MAX_EXTENDED_RESULT_BYTES
    assert response.headers['cache-control'] == 'private, no-store'
    assert post(client, start=True).json() == response.json()
    assert calls == [1]


def test_view_still_rejects_over_64_mib_with_safe_typed_error(api, monkeypatch, caplog):
    client, store = api
    monkeypatch.setattr(monitor, 'build', lambda *a, **k: {'source': 'x' * jobs.MAX_EXTENDED_RESULT_BYTES})
    assert post(client, start=True).status_code == 202
    response = terminal(client)
    assert response.status_code == 500
    assert response.headers['x-monitor-job-error'] == 'result_too_large'
    assert 'размер' in response.json()['detail']
    assert response.headers['cache-control'] == 'private, no-store'
    assert store._meta(TICKET)['failure_code'] == 'result_too_large'
    assert not store._path(TICKET, 'result').exists()
    assert 'report result too large' not in response.text + caplog.text


def test_default_16_mib_and_old_failed_ticket_are_never_upgraded_or_rebuilt(api, monkeypatch):
    client, store = api
    assert jobs.MAX_RESULT_BYTES == 16 * 1024 * 1024
    owner = jobs.owner_binding(KEY, SESSION, 'admin')
    params = {'project': PROJECT, 'cut': CUT, 'click': TICKET}
    store.start(owner, 'admin', params, lambda: {'source': 'x' * jobs.MAX_RESULT_BYTES}, TICKET)
    assert terminal(client).status_code == 500
    before = store._meta(TICKET)
    assert 'result_limit_bytes' not in before and 'failure_code' not in before
    monkeypatch.setattr(monitor, 'build', lambda *a, **k: pytest.fail('Old failed ticket was rebuilt'))
    for start in (True, False):
        response = post(client, start=start)
        assert response.status_code == 500 and 'x-monitor-job-error' not in response.headers
    assert store._meta(TICKET) == before
    assert not store._path(TICKET, 'result').exists()


def test_small_response_shape_and_legacy_synchronous_response_are_unchanged(api, monkeypatch):
    client, _ = api
    post(client, start=True, result_limit_bytes=1)  # Request fields cannot select the server budget.
    response = terminal(client)
    expected = {'pending': False, 'ticket': TICKET, 'snapshot': jsonable_encoder(SMALL)}
    assert response.status_code == 200 and response.json() == expected
    assert list(response.json()) == list(expected)
    assert 'x-monitor-job-error' not in response.headers
    monkeypatch.setattr(monitor, 'trend', lambda *a, **k: [{'synthetic': True}])
    legacy = client.post('/monitor/view', json={'project': PROJECT, 'cut': CUT, 'key': KEY})
    assert legacy.json() == {'snapshot': jsonable_encoder(SMALL), 'trend': [{'synthetic': True}]}


def test_current_key_owner_profile_and_ttl_still_gate_every_poll(api, monkeypatch):
    client, store = api
    for key in ('', 'wrong'):
        assert post(client, start=True, key=key).status_code == 403
    assert not store.root.exists()
    post(client, start=True)
    assert terminal(client).status_code == 200
    assert post(client, key='wrong').status_code == 403
    assert post(client, session='another-owner').status_code == 404
    assert post(client, start=True, cut='2026-11-05').status_code == 409
    monkeypatch.setattr(core, 'demo_session_chat', lambda session: 1)
    assert post(client).status_code == 404  # Same session/key, different admitted profile.
    monkeypatch.setattr(core, 'demo_session_chat', lambda session: 0)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'rotated-synthetic-key')
    assert post(client).status_code == 403
    assert post(client, key='rotated-synthetic-key').status_code == 404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    with store._locked():
        meta = store._meta(TICKET)
        meta['created'] -= jobs.TTL_SECONDS + 1
        store._save(meta)
    response = post(client)
    assert response.status_code == 404 and response.headers['cache-control'] == 'private, no-store'


def test_extended_budget_does_not_admit_more_active_view_jobs(api, monkeypatch):
    client, _ = api
    release = threading.Event()
    monkeypatch.setattr(monitor, 'build', lambda *a, **k: (release.wait(10), SMALL)[1])
    try:
        assert jobs.MAX_ACTIVE == 2
        assert post(client, start=True).status_code == 202
        assert post(client, start=True, ticket='b' * 32).status_code == 202
        blocked = post(client, start=True, ticket='c' * 32)
        assert blocked.status_code == 429 and blocked.headers['cache-control'] == 'private, no-store'
    finally:
        release.set()
    assert terminal(client).status_code == 200
    assert terminal(client, ticket='b' * 32).status_code == 200


@pytest.mark.parametrize('phase', ['builder_failed', 'serialization_failed', 'storage_failed'])
def test_failure_header_is_an_enum_and_never_exposes_private_content(api, monkeypatch, caplog, phase):
    client, store = api
    def build(*args, **kwargs):
        if phase == 'builder_failed':
            raise ValueError(PRIVATE)
        return {'value': float('nan')} if phase == 'serialization_failed' else SMALL
    monkeypatch.setattr(monitor, 'build', build)
    write = jobs.Store._write
    def write_result(self, path, data):
        if phase == 'storage_failed' and path.suffix == '.result':
            raise OSError(PRIVATE)
        return write(self, path, data)
    monkeypatch.setattr(jobs.Store, '_write', write_result)
    post(client, start=True)
    response = terminal(client)
    assert response.status_code == 500 and response.headers['x-monitor-job-error'] == phase
    observed = response.text + str(response.headers) + caplog.text + json.dumps(store._meta(TICKET))
    assert PRIVATE not in observed and KEY not in observed and SESSION not in observed
