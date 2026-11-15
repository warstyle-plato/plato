"""Strict owner-only metadata operations share the existing native job service."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import developaid_contract_identity as identity
import developaid_contract_identity_store as journal
import developaid_monitor as monitor
import main as wrapper
from test_contract_identity_corrections import CUT, PROJECT, retained

core = wrapper.core
KEY = 'synthetic-identity-owner-key'
PREFIX = '/monitor/contracts/identity/'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    return TestClient(core.app)


def start(client, operation, **values):
    return client.post(PREFIX+operation, json={'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, **values})


def result(client, response, **auth):
    assert response.status_code in {200, 202}
    ticket = response.json()['ticket']
    for _ in range(1000):
        polled = client.post(PREFIX+'result', json={'key': KEY, 'session': 'synthetic-owner', 'ticket': ticket, **auth})
        assert polled.headers['cache-control'] == 'private, no-store'
        if polled.status_code != 202:
            return polled
        time.sleep(.005)
    raise AssertionError('synthetic identity operation did not finish')


def confirm_values(checked, old):
    return dict(raw_ids=checked['raw_ids'], expected_revision=checked['revision'], inventory_sha256=checked['inventory_sha256'],
                source_tokens=[item['source_token'] for item in checked['source_versions']], anchor_id=old,
                canonical_number='C-NEW', note='Synthetic owner confirmation.')


@pytest.mark.parametrize('operation,values', [
    ('inventory', {'raw_ids': ['a'*64, 'b'*64]}),
    ('resolve', {'contract_id': 'a'*64}),
    ('confirm', {'raw_ids': ['a'*64, 'b'*64], 'expected_revision': 0, 'inventory_sha256': 'a'*64,
                 'source_tokens': ['a'*64, 'b'*64], 'anchor_id': 'a'*64, 'canonical_number': 'C-NEW', 'note': 'owner'}),
    ('revoke', {'decision_id': 'a'*64, 'expected_revision': 1, 'note': 'owner'}),
])
@pytest.mark.parametrize('key', ['', 'wrong-key', 'synthetic-market-key'])
def test_owner_auth_before_any_source_or_job_lookup(client, monkeypatch, operation, values, key):
    monkeypatch.setattr(core, '_monitor_cumulative_execute', lambda *_: pytest.fail('worker before owner auth'))
    response = start(client, operation, key=key, **values)
    assert response.status_code == 403 and response.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.cumulative_jobs').exists()


@pytest.mark.parametrize('extra,value', [('source_path', '/tmp/synthetic'), ('actor', 'a'*64),
                                        ('recorded_at', '1999-01-01T00:00:00+00:00'), ('aliases', {})])
def test_unknown_fields_and_caller_time_or_actor_are_rejected(client, extra, value):
    response = start(client, 'inventory', raw_ids=['a'*64, 'b'*64], **{extra: value})
    assert response.status_code == 422 and response.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.cumulative_jobs').exists()


@pytest.mark.parametrize('body', [b'{"key":"x","key":"y"}', b'{"revision":NaN}', b'[]', b'{'])
def test_ambiguous_json_is_private_and_never_reaches_worker(client, monkeypatch, body):
    monkeypatch.setattr(core, '_monitor_cumulative_execute', lambda *_: pytest.fail('worker before strict JSON'))
    response = client.post(PREFIX+'inventory', content=body, headers={'content-type': 'application/json'})
    assert response.status_code == 422 and response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('chunked', [False, True])
def test_request_body_cap_before_json_parse_including_chunked(client, chunked):
    body = b' '*65537
    content = (chunk for chunk in [body[:32768], body[32768:]]) if chunked else body
    response = client.post(PREFIX+'inventory', content=content, headers={'content-type': 'application/json'})
    assert response.status_code == 413 and response.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.cumulative_jobs').exists()


def test_actual_native_inventory_confirm_resolve_revoke_and_private_owner_poll(client, retained, monkeypatch):
    root, old, new = retained
    inventory_start = start(client, 'inventory', raw_ids=[old, new])
    assert inventory_start.headers['cache-control'] == 'private, no-store'
    assert client.post('/monitor/contracts/result', json={'key': KEY, 'session': 'synthetic-owner',
                                                        'ticket': inventory_start.json()['ticket']}).status_code == 404
    assert client.post(PREFIX+'result', json={'key': KEY, 'session': 'different-owner',
                                            'ticket': inventory_start.json()['ticket']}).status_code == 404
    checked = result(client, inventory_start).json()['identity_inventory']
    saved = result(client, start(client, 'confirm', **confirm_values(checked, old))).json()['identity_decision']
    assert saved['action'] == 'confirm' and saved['revision'] == 1
    for identifier in (old, new):
        resolved = result(client, start(client, 'resolve', contract_id=identifier)).json()['identity_resolution']
        assert resolved['logical_id'] == old and resolved['raw_id'] == identifier and resolved['financial_acceptance'] is False
    stale = result(client, start(client, 'confirm', **confirm_values(checked, old))).json()
    assert stale['ok'] is False and 'изменились' in stale['detail']
    revoked = result(client, start(client, 'revoke', decision_id=saved['event_id'], expected_revision=1, note='Owner revoke')).json()
    assert revoked['identity_decision']['action'] == 'revoke'
    assert identity.resolve(PROJECT, new, CUT)['status'] == 'revoked'
    # Only opaque server owner binding enters the append log/job files.
    state = journal.load(PROJECT)
    assert len(state['events']) == 2 and all(len(event['actor']) == 64 for event in state['events'])
    private = b''.join(path.read_bytes() for path in (monitor._SNAPSHOT_DIR/'.cumulative_jobs').iterdir() if path.is_file())
    assert KEY.encode() not in private and b'synthetic-owner' not in private
    assert KEY.encode() not in (root/journal.LOG).read_bytes() and b'synthetic-owner' not in (root/journal.LOG).read_bytes()
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'rotated-synthetic-key')
    assert result(client, inventory_start).status_code == 403
    assert result(client, inventory_start, key='rotated-synthetic-key').status_code == 404


def test_identity_endpoints_are_post_only(client):
    response = client.get(PREFIX+'inventory')
    assert response.status_code == 405 and response.headers['cache-control'] == 'private, no-store'
