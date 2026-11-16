"""Only the current admin key can apply one source-bound management policy."""
import datetime as dt

import pytest

import developaid_finance_management as management
import developaid_monitor as monitor
from test_finance_money_bridge import source
from test_monitor_cumulative_api import api, post, poll, KEY

DAY = '2026-11-10'
PROJECT = 'Synthetic management API'


@pytest.mark.parametrize('path', ['view', 'apply', 'result'])
@pytest.mark.parametrize('key,session', [('', ''), ('bad', 'claimed-owner'), ('', 'demo')])
def test_admission_precedes_source_job_and_policy_access(api, monkeypatch, path, key, session):
    client, root = api
    monkeypatch.setattr(management, 'view', lambda *a, **k: pytest.fail('read before admission'))
    monkeypatch.setattr(management, 'apply', lambda *a, **k: pytest.fail('write before admission'))
    body = {'ticket': 'a'*32} if path == 'result' else {'project': PROJECT, 'cut': DAY}
    if path == 'apply':
        body.update(source_sha256='b'*64, revision=0, item_ids=['c'*64],
                    management_article='2.6', note='Owner decision.')
    answer = post(client, 'finance-management/'+path, key=key, session=session, **body)
    assert answer.status_code == 403
    assert answer.headers['cache-control'] == 'private, no-store'
    assert not (root/'monitor').exists()


def run(client, path, **body):
    response = post(client, 'finance-management/'+path, project=PROJECT, cut=DAY, **body)
    assert response.status_code in (200, 202)
    result = response.json()
    return poll(client, result['ticket'], family='finance-management').json() if response.status_code == 202 else result


def test_actual_background_apply_cas_rotation_and_cross_family_are_private(api, monkeypatch):
    client, root = api
    monkeypatch.setattr(management, '_now', lambda: dt.datetime(2026,11,10,12,tzinfo=dt.timezone.utc))
    path = monitor._project_dir(PROJECT)/'baseline'/'finance.xlsx'
    path.parent.mkdir(parents=True)
    raw = source(future_bank='3.1');path.write_bytes(raw)
    state = run(client, 'view')['management']
    payload = {'source_sha256':state['source_sha256'],'revision':0,
               'item_ids':[item['item_id'] for item in state['rows']],
               'management_article':'2.6','note':'Owner: all economic AHR fact and plan management2.6.'}
    response = post(client, 'finance-management/apply', project=PROJECT, cut=DAY, **payload)
    assert response.status_code == 202
    ticket = response.json()['ticket']
    saved = poll(client, ticket, family='finance-management').json()
    assert saved['ok'] and saved['management']['revision'] == 1
    assert post(client,'finance-allocation/result',ticket=ticket).status_code == 404
    stale = run(client, 'apply', **payload)
    assert not stale['ok'] and stale['status'] == 409
    assert path.read_bytes() == raw
    events = list(root.rglob('finance_management/*.json'))
    assert len(events) == 1 and KEY not in events[0].read_text()
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'rotated-current-key')
    assert post(client,'finance-management/result',ticket=ticket).status_code == 403


@pytest.mark.parametrize('tamper', [{'amount':1},{'fact':0},{'bank_code':'2.6'},
                                  {'revision':True},{'item_ids':[]},{'management_article':'3.1'},
                                  {'source_sha256':'bad'}])
def test_schema_does_not_accept_money_bank_override_or_unbound_source(api, tamper):
    client, _ = api
    payload = {'project':PROJECT,'cut':DAY,'source_sha256':'a'*64,'revision':0,
               'item_ids':['b'*64],'management_article':'2.6','note':'Owner decision.'}
    payload.update(tamper)
    answer = post(client,'finance-management/apply',**payload)
    assert answer.status_code == 422
    assert answer.headers['cache-control'] == 'private, no-store'
