"""Initial PDF admission uses current owner auth and a separate private job family."""
from __future__ import annotations

import base64
import time

from fastapi.testclient import TestClient
import pytest

import developaid_monitor as monitor
import main as wrapper
from test_contract_pdf_intake import PROJECT, pdf, project  # noqa: F401

core = wrapper.core
KEY = 'synthetic-pdf-intake-admin'
PREFIX = '/monitor/contracts/pdf-intake/'


@pytest.fixture
def client(monkeypatch, project):  # noqa: F811
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    return TestClient(core.app)


def body():
    raw, claims = pdf()
    return {'key': KEY, 'session': 'synthetic-pdf-owner', 'project': PROJECT,
            'content_base64': base64.b64encode(raw).decode(), **claims}


def finish(client, response, **auth):
    assert response.status_code in {200, 202}, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    for _ in range(1000):
        polled = client.post(PREFIX+'result', json={'key': KEY, 'session': 'synthetic-pdf-owner',
                                                  'ticket': response.json()['ticket'], **auth})
        assert polled.headers['cache-control'] == 'private, no-store'
        if polled.status_code != 202:
            return polled
        time.sleep(.005)
    raise AssertionError('Synthetic PDF intake did not finish')


@pytest.mark.parametrize('operation', ['preview', 'commit', 'result'])
@pytest.mark.parametrize('key', ['', 'wrong', 'synthetic-market-key'])
def test_auth_before_source_job_or_project_access(client, monkeypatch, operation, key):
    monkeypatch.setattr(core, '_monitor_cumulative_execute', lambda *_: pytest.fail('worker before owner auth'))
    values = body()
    if operation == 'commit':
        values.update(filename='source.pdf', expected_revision=0, preview_token='a'*64)
    if operation == 'result':
        values = {'session': 'synthetic-pdf-owner', 'ticket': 'a'*32}
    response = client.post(PREFIX+operation, json={**values, 'key': key})
    assert response.status_code == 403 and response.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.cumulative_jobs').exists()


@pytest.mark.parametrize('extra,value', [('contract_id', 'a'*64), ('source_path', '/tmp/synthetic'),
                                       ('actor', 'a'*64), ('recorded_at', '1999-01-01')])
def test_caller_cannot_supply_paths_ids_or_actor(client, extra, value):
    response = client.post(PREFIX+'preview', json={**body(), extra: value})
    assert response.status_code == 422 and response.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.cumulative_jobs').exists()


@pytest.mark.parametrize('raw', [b'{"key":"x","key":"y"}', b'[]', b'{"revision":NaN}'])
def test_ambiguous_body_is_refused_before_admission(client, raw):
    response = client.post(PREFIX+'preview', content=raw, headers={'content-type': 'application/json'})
    assert response.status_code == 422 and response.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.cumulative_jobs').exists()


def test_native_preview_commit_poll_and_replay_with_current_owner(client, project, monkeypatch):  # noqa: F811
    values = body()
    started = client.post(PREFIX+'preview', json=values)
    assert finish(client, started, session='different-owner').status_code == 404
    assert client.post('/monitor/contracts/result', json={'key': KEY, 'session': values['session'],
                                                        'ticket': started.json()['ticket']}).status_code == 404
    checked = finish(client, started).json()['pdf_intake']
    posted = client.post(PREFIX+'commit', json={**values, 'filename': 'source.pdf',
                         'expected_revision': checked['revision'], 'preview_token': checked['preview_token']})
    saved = finish(client, posted).json()['pdf_intake']
    assert saved['contract_id'] == checked['contract_id'] and saved['revision'] == 1
    again = finish(client, client.post(PREFIX+'commit', json={**values, 'filename': 'copy.pdf',
                   'expected_revision': 0, 'preview_token': checked['preview_token']})).json()['pdf_intake']
    assert again['already']
    private = b''.join(p.read_bytes() for p in (monitor._SNAPSHOT_DIR/'.cumulative_jobs').iterdir() if p.is_file())
    assert KEY.encode() not in private and values['session'].encode() not in private
    assert KEY.encode() not in (project/'contract_pdf_sources.json').read_bytes()
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'rotated-synthetic-key')
    assert finish(client, started).status_code == 403
    assert finish(client, started, key='rotated-synthetic-key').status_code == 404


def test_post_only_and_oversized_body_are_private(client):
    response = client.get(PREFIX+'preview')
    assert response.status_code == 405 and response.headers['cache-control'] == 'private, no-store'
    response = client.post(PREFIX+'preview', content=b'{}', headers={'content-length': str(29*1024*1024),
                                                                  'content-type': 'application/json'})
    assert response.status_code == 413 and response.headers['cache-control'] == 'private, no-store'
