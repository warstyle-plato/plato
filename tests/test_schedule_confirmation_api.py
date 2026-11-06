"""All confirmation access needs the current administrator key."""
import datetime as dt

import pytest

import developaid_schedule_confirmation as confirmation
from test_monitor_cumulative_api import api, post, KEY


@pytest.mark.parametrize('path', ['view', 'save'])
@pytest.mark.parametrize('key,session', [('', ''), ('wrong', ''), ('', 'telegram'), ('market', 'demo')])
def test_admission_precedes_read_and_mutation(api, monkeypatch, path, key, session):
    client, _ = api
    monkeypatch.setattr(confirmation, 'view', lambda *a, **kw: pytest.fail('private read before admission'))
    monkeypatch.setattr(confirmation, 'save', lambda *a, **kw: pytest.fail('mutation before admission'))
    response = post(client, 'schedule-confirmation/'+path, key=key, session=session,
                    project='Учебный проект', source_sha256='a'*64, revision=0,
                    calendar_basis='calendar_days', rnv_chain_complete=True, note='Проверил Иван.')
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'private, no-store'


def test_save_reload_revoke_and_stale_editor(api, monkeypatch):
    import developaid_monitor as monitor
    client, root = api
    monkeypatch.setattr(confirmation, '_now', lambda: dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc))
    path = monitor._project_dir('Учебный проект') / 'baseline' / 'pm.xlsx'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'synthetic source')
    state = post(client, 'schedule-confirmation/view', project='Учебный проект', cut='2026-11-06').json()
    payload = dict(project='Учебный проект', source_sha256=state['source_sha256'], revision=state['revision'],
                   calendar_basis='calendar_days', rnv_chain_complete=True, note='Проверила Анна по перечню этапов.')
    saved = post(client, 'schedule-confirmation/save', **payload)
    assert saved.status_code == 200 and saved.json()['rnv_chain_complete']
    assert saved.headers['cache-control'] == 'private, no-store'
    assert post(client, 'schedule-confirmation/save', **payload).status_code == 409
    assert post(client, 'schedule-confirmation/view', project='Учебный проект', cut='2026-11-05').json()['recorded_at'] is None
    payload.update(revision=saved.json()['revision'], calendar_basis='unconfirmed', rnv_chain_complete=False)
    assert not post(client, 'schedule-confirmation/save', **payload).json()['rnv_chain_complete']
    audit = list(root.rglob('schedule_confirmations/*.json'))
    assert len(audit) == 2 and all(KEY not in p.read_text() for p in audit)


@pytest.mark.parametrize('change', [dict(rnv_chain_complete='false'), dict(revision=True), dict(calendar_basis='working_days'), dict(note='')])
def test_validation_and_errors_are_not_cacheable(api, change):
    client, _ = api
    payload = dict(project='Учебный проект', source_sha256='a'*64, revision=0,
                   calendar_basis='calendar_days', rnv_chain_complete=True, note='Проверено.')
    payload.update(change)
    response = post(client, 'schedule-confirmation/save', **payload)
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'private, no-store'


def test_bad_cut_and_private_storage_failure_have_accurate_errors(api, monkeypatch, caplog):
    client, _ = api
    bad = post(client, 'schedule-confirmation/view', project='Учебный проект', cut='2026-02-31')
    assert bad.status_code == 400
    marker = 'private-path-and-customer-information'
    def fail(*a, **kw):
        raise OSError(marker)
    monkeypatch.setattr(confirmation, 'view', fail)
    response = post(client, 'schedule-confirmation/view', project='Учебный проект')
    assert response.status_code == 503
    assert response.headers['cache-control'] == 'private, no-store'
    assert marker not in response.text and marker not in caplog.text
