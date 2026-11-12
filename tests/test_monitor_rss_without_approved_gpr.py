"""A saved RSS remains readable before its approved GPR is available.

Real source files and the native async endpoints distinguish an absent plan
from a lost/corrupt source; neither case invents progress or bypasses admission.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

import developaid_monitor as monitor
import main as wrapper
from developaid_monitor_ledgers import LedgerProblem
from test_monitor_keeps_every_snapshot import _rss_book, _baseline_book

KEY = 'synthetic-rss-only-owner'
PROJECT = 'Synthetic RSS without approved GPR'
CUT = '2026-11-09'
REASON = 'Утверждённый график работ не загружен.'


@pytest.fixture
def rss_project(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    raw = _rss_book(acts=[('08.11.2026', 400e6)],
                    payments=[(dt.date(2026, 11, 8), 100e6)])
    monitor.store_estimate(PROJECT, raw, CUT)
    path = monitor._project_dir(PROJECT) / 'estimate' / (CUT + '.xlsx')
    return path, raw


def assert_rss_view(view):
    schedule = view['schedule']
    assert schedule['rows'] == []
    assert schedule['reason'] == REASON
    assert schedule['baseline_end'] is schedule['forecast_end'] is None
    assert view['money']['accepted'] == pytest.approx(400e6)
    assert view['money']['payment_fact'] == pytest.approx(100e6)
    assert view['payments']['known'] is False
    assert view['payments']['plan_total'] is None
    assert view['payments']['fact_total'] == pytest.approx(100e6)
    assert all(row['plan'] is None for row in view['payments']['rows'])


def poll(client, ticket, *, key=KEY, session='rss-owner'):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.post('/monitor/view/result', json={
            'key': key, 'session': session, 'ticket': ticket})
        if response.status_code != 202:
            return response
        time.sleep(.01)
    pytest.fail('Synthetic RSS-only calculation did not finish')


def test_saved_rss_build_keeps_known_ks_and_payments_without_inventing_gpr(rss_project):
    path, raw = rss_project
    assert_rss_view(monitor.build(PROJECT, CUT))
    assert path.read_bytes() == raw
    assert not monitor._baseline_file(PROJECT, CUT)


def test_native_async_rss_view_finishes_and_preserves_admission_owner_and_sources(rss_project):
    path, raw = rss_project
    client = TestClient(wrapper.core.app)
    body = {'project': PROJECT, 'cut': CUT, 'background': True,
            'ticket': 'd' * 32, 'session': 'rss-owner'}
    denied = client.post('/monitor/view', json={**body, 'key': 'wrong'})
    assert denied.status_code == 403
    assert denied.headers['cache-control'] == 'private, no-store'
    assert not (monitor._SNAPSHOT_DIR / '.view_jobs').exists()
    admitted = client.post('/monitor/view', json={**body, 'key': KEY})
    assert admitted.status_code == 202
    ticket = admitted.json()['ticket']
    result = poll(client, ticket)
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'private, no-store'
    assert_rss_view(result.json()['snapshot'])
    assert poll(client, ticket, key='wrong').status_code == 403
    assert poll(client, ticket, session='another-owner').status_code == 404
    assert path.read_bytes() == raw
    assert not monitor._baseline_file(PROJECT, CUT)


def test_corrupt_rss_is_not_reported_as_an_empty_approved_plan(rss_project):
    path, _ = rss_project
    path.write_bytes(b'corrupt synthetic RSS')
    with pytest.raises(zipfile.BadZipFile):
        monitor.build(PROJECT, CUT)


@pytest.mark.parametrize('with_rss', [False, True])
def test_lost_selected_gpr_file_is_not_a_missing_approved_plan(rss_project, with_rss):
    path, _ = rss_project
    if not with_rss:
        path.unlink()
    folder = monitor._project_dir(PROJECT) / 'baseline'
    folder.mkdir()
    sha = hashlib.sha256(_baseline_book()).hexdigest()
    # A valid committed selection whose immutable source has been lost is
    # different from a project with no approved selection at all.
    (folder / 'schedule_versions.json').write_text(json.dumps({
        'schema': 1, 'versions': [{'revision': 1, 'source_sha256': sha,
            'previous_source_sha256': '', 'effective_from': CUT,
            'approved_at': CUT + 'T08:00:00+00:00', 'baseline_scope': 'full_schedule'}]}))
    with pytest.raises(FileNotFoundError) as failure:
        monitor.build(PROJECT, CUT)
    assert not isinstance(failure.value, monitor.ApprovedScheduleMissing)


def test_corrupt_selected_gpr_remains_an_error(rss_project):
    folder = monitor._project_dir(PROJECT) / 'baseline'
    folder.mkdir()
    (folder / 'gpr.xlsx').write_bytes(b'corrupt synthetic GPR')
    with pytest.raises(LedgerProblem, match='ZIP'):
        monitor.build(PROJECT, CUT)


def test_other_missing_input_is_not_swallowed_as_missing_gpr(rss_project, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError('synthetic unrelated source')
    monkeypatch.setattr(monitor.actuals, 'read_payments', missing)
    with pytest.raises(FileNotFoundError, match='unrelated source'):
        monitor.build(PROJECT, CUT)


def test_no_rss_and_no_gpr_keep_financial_values_unknown(rss_project):
    path, _ = rss_project
    path.unlink()
    view = monitor.build(PROJECT, CUT)
    assert view['schedule']['rows'] == []
    assert view['schedule']['reason'] == REASON
    assert view['money']['accepted'] is None
    assert view['payments']['fact_total'] is None
    assert view['financial_state']['state'] == 'missing'
