"""Admin admission precedes private source access; workers never retain keys."""
import datetime as dt

import pytest

import developaid_finance_allocations as allocations
import developaid_monitor as monitor
from test_finance_money_bridge import source
from test_monitor_cumulative_api import api, post, poll, KEY

DAY = '2026-11-09'
PROJECT = 'Synthetic finance'


@pytest.mark.parametrize('path', ['view', 'apply', 'result'])
@pytest.mark.parametrize('key,session', [('', ''), ('bad', 'claimed-owner'), ('', 'demo')])
def test_current_admin_admission_precedes_private_source_or_job_access(api, monkeypatch, path, key, session):
    client, _ = api
    monkeypatch.setattr(allocations, 'view', lambda *a, **kw: pytest.fail('private read before admission'))
    monkeypatch.setattr(allocations, 'apply', lambda *a, **kw: pytest.fail('write before admission'))
    data = {'ticket': 'a'*32} if path == 'result' else {'project': PROJECT, 'cut': DAY}
    if path == 'apply':
        data.update(source_sha256='b'*64, revision=0, assignments=[{'row_id':'c'*64,'bank_code':'2.6'}], note='Owner instructed.')
    response = post(client, 'finance-allocation/'+path, key=key, session=session, **data)
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'private, no-store'


def run(client, path, **data):
    response = post(client, 'finance-allocation/'+path, project=PROJECT, cut=DAY, **data)
    assert response.status_code in (200, 202)
    body = response.json()
    if response.status_code == 202:
        body = poll(client, body['ticket'], family='finance-allocation').json()
    return body


def test_real_admin_background_apply_revision_fence_and_key_rotation(api, monkeypatch):
    client, root = api
    monkeypatch.setattr(allocations, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    path = monitor._project_dir(PROJECT) / 'baseline' / 'finance.xlsx'
    path.parent.mkdir(parents=True)
    raw = source()
    path.write_bytes(raw)
    state = run(client, 'view')['allocation']
    payload = {'source_sha256':state['source_sha256'],'revision':0,
        'assignments':[{'row_id':state['rows'][0]['row_id'],'bank_code':'2.6'}], 'note':'Owner instruction for selected payment.'}
    saved = run(client, 'apply', **payload)
    assert saved['ok'] and saved['allocation']['revision'] == 1
    stale = run(client, 'apply', **payload)
    assert not stale['ok'] and stale['status'] == 409
    assert path.read_bytes() == raw
    audit = list(root.rglob('finance_allocations/*.json'))
    assert len(audit) == 1 and KEY not in audit[0].read_text()
    assert 'amount' not in audit[0].read_text()
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'rotated-synthetic-key')
    assert post(client, 'finance-allocation/view', project=PROJECT, cut=DAY).status_code == 403


@pytest.mark.parametrize('change', [{'amount':1}, {'assignments':[{'row_id':'a'*64,'bank_code':'2.6','amount':1}]},
    {'revision':True}, {'source_sha256':'bad'}, {'assignments':[]}, {'assignments':[{'row_id':'a'*64,'bank_code':'4.1'}]}])
def test_payload_cannot_override_money_or_escape_target_schema(api, change):
    client, _ = api
    payload={'project':PROJECT,'cut':DAY,'source_sha256':'b'*64,'revision':0,
        'assignments':[{'row_id':'a'*64,'bank_code':'2.6'}],'note':'Owner instruction.'}
    payload.update(change)
    response=post(client,'finance-allocation/apply',**payload)
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'private, no-store'
