"""An administrator can clarify one immutable source cell without rewriting KS."""
from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_header_confirmations as confirmations
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import archive, ks
from test_monitor_cumulative_api import api, post, poll, KEY


def stored(project='Fixture', *, second=False):
    files = [('One.xlsx', ks(date='03.07.124'))]
    if second:
        files.append(('Two.xlsx', ks(date='03.07.124')))
    payload = archive(files)
    day = (dt.date.today()-dt.timedelta(days=30)).isoformat()
    ledgers.store_archive(project, payload, day, 'KS.zip')
    snapshot = contracts._archive(project, dt.date.today().isoformat())
    return snapshot


def fields(snapshot, index=0):
    ledger = snapshot['ledgers'][index]
    reference = confirmations.binding(snapshot, ledger, ledger['contract_date_evidence'][0])
    assert reference is not None
    return {**reference, 'contract_date': '2024-07-03'}


def test_current_key_confirm_is_bound_durable_private_and_does_not_rewrite_originals(api):
    client, root = api
    snapshot = stored()
    before = {p.name: p.read_bytes() for p in ledgers._root('Fixture').iterdir() if p.is_file()}
    data = fields(snapshot)
    response = post(client, 'contracts/header-date', project='Fixture', cut=dt.date.today().isoformat(),
                    session='synthetic-session', origin='arbitrary-owner-claim', **data)
    assert response.status_code in {200, 202}
    assert response.headers['cache-control'] == 'private, no-store'
    result = response if response.status_code == 200 else poll(client, response.json()['ticket'], session='synthetic-session')
    assert result.json()['ok'] is True
    record = result.json()['header_date']
    assert record['origin'] == 'manual_confirmation'
    assert record['confirmed_at'][:10] == dt.date.today().isoformat()
    assert record['binding']['raw'] == '03.07.124'
    view = contracts.build('Fixture', dt.date.today().isoformat())
    row, = view['rows']
    assert row['contract_date'] == '2024-07-03'
    assert row['date_confirmation']['binding']['cell'] == 'B4'
    assert not view['unresolved_sources']
    for path in ledgers._root('Fixture').iterdir():
        if path.name in before:
            assert path.read_bytes() == before[path.name]
    path = confirmations._path('Fixture')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    private = b''.join(p.read_bytes() for p in root.rglob('*') if p.is_file())
    assert KEY.encode() not in private and b'synthetic-session' not in private
    assert b'arbitrary-owner-claim' not in path.read_bytes()


def test_confirmation_is_not_historical_source_truth(api):
    snapshot = stored()
    data = fields(snapshot)
    contracts.confirm_header_date('Fixture', dt.date.today().isoformat(), **data)
    before = contracts.build('Fixture', (dt.date.today()-dt.timedelta(days=1)).isoformat())
    assert len(before['rows']) == 1 and before['rows'][0]['contract_date'] is None
    unresolved, = before['unresolved_sources']
    assert unresolved['date_confirmation']['applicable_to_cut'] is False
    assert unresolved['date_confirmation']['contract_date'] == '2024-07-03'
    assert unresolved['date_evidence'][0]['raw'] == '03.07.124'


@pytest.mark.parametrize('field', ['snapshot_id', 'file_sha256', 'filename', 'sheet', 'cell', 'raw'])
def test_any_source_binding_change_prevents_carrying_confirmation(api, field):
    snapshot = stored()
    data = fields(snapshot)
    contracts.confirm_header_date('Fixture', dt.date.today().isoformat(), **data)
    changed = copy.deepcopy(snapshot)
    if field == 'snapshot_id':
        changed[field] = '2026-01-01-' + 'a'*64
    elif field == 'file_sha256':
        changed['ledgers'][0][field] = 'a'*64
    elif field in {'filename', 'sheet'}:
        changed['ledgers'][0]['source'][field] += '-changed'
    elif field == 'cell':
        changed['ledgers'][0]['contract_date_evidence'][0]['source']['cell'] = 'C4'
    else:
        changed['ledgers'][0]['contract_date_evidence'][0]['raw'] += ' '
    result = confirmations.apply('Fixture', changed, dt.date.today().isoformat())
    assert result['ledgers'][0]['contract_date'] is None
    assert 'date_confirmation' not in result['ledgers'][0]
    assert confirmations.apply('Other', snapshot, dt.date.today().isoformat())['ledgers'][0]['contract_date'] is None


def test_concurrent_source_confirmations_preserve_both_and_are_idempotent(api):
    snapshot = stored(second=True)
    def write(index):
        return contracts.confirm_header_date('Fixture', dt.date.today().isoformat(), **fields(snapshot, index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(write, [0, 1]))
    assert len(confirmations._read('Fixture')) == 2
    assert write(0) == values[0]
    row, = contracts.build('Fixture', dt.date.today().isoformat())['rows']
    assert row['contract_date'] == '2024-07-03'
    assert len(row['date_confirmations']) == 2


@pytest.mark.parametrize('bad', [[], {}, {'schema': 1, 'confirmations': []},
                                {'schema': 1, 'confirmations': {'a': {'binding': {}}}}])
def test_malformed_metadata_is_not_applied_or_overwritten(api, bad):
    snapshot = stored()
    path = confirmations._path('Fixture')
    path.write_text(json.dumps(bad))
    before = path.read_bytes()
    with pytest.raises(contracts.ContractProblem):
        contracts.build('Fixture', dt.date.today().isoformat())
    with pytest.raises(contracts.ContractProblem):
        contracts.confirm_header_date('Fixture', dt.date.today().isoformat(), **fields(snapshot))
    assert path.read_bytes() == before


@pytest.mark.parametrize('failure', ['fsync', 'replace'])
def test_failed_write_keeps_previous_metadata_and_cleans_temporary(api, monkeypatch, failure):
    snapshot = stored(second=True)
    contracts.confirm_header_date('Fixture', dt.date.today().isoformat(), **fields(snapshot, 0))
    path = confirmations._path('Fixture')
    before = path.read_bytes()
    def fail(*args):
        raise OSError('synthetic-private-marker')
    monkeypatch.setattr(confirmations.os, failure, fail)
    with pytest.raises(OSError):
        contracts.confirm_header_date('Fixture', dt.date.today().isoformat(), **fields(snapshot, 1))
    assert path.read_bytes() == before
    assert not list(path.parent.glob('.header-date-*'))


def test_header_date_job_rotation_owner_profile_and_parameters_are_checked(api, monkeypatch):
    client, root = api
    snapshot = stored()
    data = dict(fields(snapshot), project='Fixture', cut=dt.date.today().isoformat(), ticket='a'*32)
    response = post(client, 'contracts/header-date', session='A', **data)
    ticket = response.json()['ticket']
    assert poll(client, ticket, session='A').json()['ok']
    assert post(client, 'contracts/result', session='B', ticket=ticket).status_code == 404
    assert post(client, 'cumulative/result', session='A', ticket=ticket).status_code == 404
    assert post(client, 'contracts/header-date', session='A', **dict(data, raw='changed')).status_code == 409
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'synthetic-rotated')
    assert post(client, 'contracts/result', ticket=ticket, session='A').status_code == 403
    assert post(client, 'contracts/result', ticket=ticket, session='A', key='synthetic-rotated').status_code == 404


def test_wrong_binding_does_not_create_metadata_or_echo_source_data(api):
    client, root = api
    snapshot = stored()
    data = dict(fields(snapshot), raw='different-raw', project='Fixture', cut=dt.date.today().isoformat())
    response = post(client, 'contracts/header-date', **data)
    result = response if response.status_code == 200 else poll(client, response.json()['ticket'])
    assert result.status_code == 200 and result.json()['ok'] is False
    assert not confirmations._path('Fixture').exists()
    assert 'different-raw' not in result.text


def _days_ago(n):
    return (dt.date.today()-dt.timedelta(days=n)).isoformat()


def test_wrong_clarification_can_be_corrected_with_a_note_and_history_is_kept(api, monkeypatch):
    snapshot = stored()
    data = fields(snapshot)
    first = dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=3)
    real_datetime = dt.datetime

    class Frozen(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return first
    monkeypatch.setattr(confirmations.dt, 'datetime', Frozen)
    contracts.confirm_header_date('Fixture', _days_ago(0), **{**data, 'contract_date': '2024-03-07'})
    monkeypatch.setattr(confirmations.dt, 'datetime', real_datetime)
    with pytest.raises(contracts.ContractProblem, match='основание'):
        contracts.confirm_header_date('Fixture', _days_ago(0), **data)
    record = contracts.confirm_header_date('Fixture', _days_ago(0), **data, note='Дата по подписанному экземпляру.')
    assert record['contract_date'] == '2024-07-03' and record['previous'][0]['contract_date'] == '2024-03-07'
    row, = contracts.build('Fixture', _days_ago(0))['rows']
    assert row['contract_date'] == '2024-07-03'
    assert row['date_confirmation']['note'] == 'Дата по подписанному экземпляру.'
    # A cut between the two decisions sees the decision in force then.
    old, = contracts.build('Fixture', _days_ago(1))['rows']
    assert old['contract_date'] == '2024-03-07'


def test_clarification_can_be_revoked_and_the_contract_returns_to_review(api):
    snapshot = stored()
    data = fields(snapshot)
    with pytest.raises(contracts.ContractProblem, match='снимать нечего'):
        contracts.confirm_header_date('Fixture', _days_ago(0), **{**data, 'contract_date': ''}, note='Ошибка.')
    contracts.confirm_header_date('Fixture', _days_ago(0), **data)
    record = contracts.confirm_header_date('Fixture', _days_ago(0), **{**data, 'contract_date': ''},
                                           note='Уточнение внесено по ошибке.')
    assert record['contract_date'] is None and len(record['previous']) == 1
    view = contracts.build('Fixture', _days_ago(0))
    assert len(view['rows']) == 1 and view['rows'][0]['contract_date'] is None
    unresolved, = view['unresolved_sources']
    assert unresolved['date_confirmation']['revoked'] is True
    # The page receives the exact binding it must send back.
    assert unresolved['date_evidence'][0]['binding'] == {k: v for k, v in data.items() if k != 'contract_date'}


def test_corrupted_correction_history_fails_closed(api):
    snapshot = stored()
    data = fields(snapshot)
    contracts.confirm_header_date('Fixture', _days_ago(0), **data)
    path = confirmations._path('Fixture')
    value = json.loads(path.read_text())
    record, = value['confirmations'].values()
    record['contract_date'] = None  # A revocation without any prior decision.
    path.write_text(json.dumps(value))
    with pytest.raises(contracts.ContractProblem, match='неверный формат'):
        contracts.build('Fixture', _days_ago(0))


def test_real_page_sends_correction_for_the_exact_header_cell():
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page, register
    binding = {'snapshot_id': '2026-11-06-'+'a'*64, 'file_sha256': 'b'*64, 'filename': 'Учебная.xlsx',
               'sheet': 'Работы', 'cell': 'B4', 'raw': '03.07.124'}
    data = register()
    data['unresolved_sources'] = [{
        'contractor': 'ООО «Учебный подрядчик»', 'contract': 'У-1', 'reason': 'В шапке не подтверждены: дата.',
        'source': {'label': 'Учебная.xlsx'}, 'date_evidence': [{'raw': '03.07.124', 'source': {'cell': 'B4'}, 'binding': binding}],
        'date_confirmation': {'binding': binding, 'contract_date': '2024-03-07', 'confirmed_at': '2026-11-05T09:00:00+00:00',
                              'origin': 'manual_confirmation', 'applicable_to_cut': True, 'revoked': False}}]
    sent = []

    def header_date(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'pending': False, 'ok': True, 'header_date': {}})
    with browser_page(390) as (page, responses, errors):
        responses.data = data
        page.route('**/monitor/contracts/header-date', header_date)
        page.locator('#contractsTab').click()
        button = page.locator('#contractsWarnings .header-date-edit')

        def open_form():
            # The unresolved header list is collapsed by default.
            details = page.locator('#contractsWarnings details.contract-detail')
            if not details.evaluate('d => d.open'):
                details.locator('summary').click()
            button.click()
        expect(button).to_have_count(1)
        expect(button).to_have_text('Исправить дату договора')
        open_form()
        expect(page.locator('#contractsHeaderDateTitle')).to_contain_text('ячейка B4')
        expect(page.locator('#contractsHeaderDateValue')).to_have_value('2024-03-07')
        page.locator('#contractsHeaderDateValue').fill('2024-07-03')
        page.locator('#contractsHeaderDateSave').click()
        expect(page.locator('#contractsHeaderDateMsg')).to_contain_text('основание')
        assert not sent
        page.locator('#contractsHeaderDateNote').fill('Дата по подписанному экземпляру.')
        page.locator('#contractsHeaderDateSave').click()
        expect(page.locator('#contractsHeaderDate')).to_be_hidden()
        body, = sent
        assert {k: body[k] for k in binding} == binding
        assert body['contract_date'] == '2024-07-03' and body['note'] == 'Дата по подписанному экземпляру.'
        open_form()
        page.locator('#contractsHeaderDateNote').fill('Уточнение внесено по ошибке.')
        page.locator('#contractsHeaderDateRevoke').click()
        expect(page.locator('#contractsHeaderDate')).to_be_hidden()
        assert sent[-1]['contract_date'] == '' and len(sent) == 2
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
