"""Derived reads are prepared finitely, without widening register/source gates."""
import copy
import hashlib

import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_identity_store as journal
import developaid_contract_ownership as ownership
import developaid_contract_parse_refresh as preparation
import developaid_monitor_contracts as contracts
from tests.test_contract_logical_ownership import pair, PROJECT, CUT
from tests.test_contract_source_correction import confirm
from tests.test_contract_documents_are_read_from_their_tables import schedule_pdf
from tests.test_contract_price_follows_its_agreements import _pdf


def source_set(pair, monkeypatch, count=6):
    current = documents.READER_VERSION
    monkeypatch.setattr(documents, 'READER_VERSION', 11)
    row = next(r for r in pair['before']['rows'] if r['id'] == pair['new'])
    raw = _pdf('Договор подряда № SOURCE-B от 01.01.2026',
               '3.1. Цена Договора составляет 2 000 рублей с НДС.')
    price_sha = files.store(PROJECT, row, 'synthetic-price.pdf', raw)['sha256']
    folder = pair['root']/'contract_documents'/pair['new']
    path = folder/(price_sha+'.json')
    record = files._stored(path)
    record.pop('signature_evidence', None)
    files._json(path, record)
    for index in range(count-1):
        raw = schedule_pdf(title=('к Договору подряда № SOURCE-B от 01.01.2026',
                                  'График производства работ '+str(index)))
        files.store(PROJECT, row, 'synthetic-graph-'+str(index)+'.pdf', raw)
    confirm(pair)
    state = copy.deepcopy(journal.load(PROJECT))
    monkeypatch.setattr(documents, 'READER_VERSION', current)
    return folder, price_sha, state


def test_plan_never_parses_or_changes_document_or_human_journal(pair, monkeypatch):
    folder, _, state = source_set(pair, monkeypatch, 2)
    before = {p.name: p.read_bytes() for p in folder.glob('*.json')}
    monkeypatch.setattr(documents, 'read', lambda _: pytest.fail('A plan cannot reparse a PDF.'))
    plan = preparation.prepare(PROJECT, CUT)
    assert plan['remaining'] == 2 and plan['processed'] == 0 and not plan['done']
    assert {p.name: p.read_bytes() for p in folder.glob('*.json')} == before
    assert journal.load(PROJECT) == state


def test_one_pdf_jobs_restore_register_without_expanding_budget_and_price_first(pair, monkeypatch):
    folder, price_sha, state = source_set(pair, monkeypatch)
    before = {p.name: p.read_bytes() for p in folder.glob('*.json')}
    monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_FILES', 8)
    with pytest.raises(files.ParseRefreshRequired):
        contracts.build(PROJECT, CUT, include_history=False)
    assert {p.name: p.read_bytes() for p in folder.glob('*.json')} == before
    observed = []
    original = documents.read
    def read(raw):
        observed.append(hashlib.sha256(raw).hexdigest())
        return original(raw)
    monkeypatch.setattr(documents, 'read', read)
    plan = preparation.prepare(PROJECT, CUT)
    for count in range(6):
        previous = plan['remaining']
        plan = preparation.prepare(PROJECT, CUT, plan['guard'])
        assert plan['processed'] == 1 and plan['remaining'] == previous-1
        assert len(observed) == count+1 and journal.load(PROJECT) == state
    assert observed[0] == price_sha and len(set(observed)) == 6 and plan['done']
    assert all(files._stored(p)['reader'] == documents.READER_VERSION for p in folder.glob('*.json'))
    monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_FILES', 64)
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    assert row['source_correction']['fresh'] and row['amount'] == 2000
    assert len(observed) == 6 and journal.load(PROJECT) == state


@pytest.mark.parametrize('change', ['deadline', 'links', 'metadata'])
def test_between_admissions_owner_change_aborts_without_rebasing_guard(pair, monkeypatch, change):
    folder, _, state = source_set(pair, monkeypatch, 2)
    plan = preparation.prepare(PROJECT, CUT)
    if change == 'deadline':
        files._json(pair['root']/'cumulative_terms.json', {pair['new']: {'deadline': '2027-01-01'}})
    elif change == 'links':
        files._json(folder/'links.json', {'choices': {}, 'owner_note': 'new mapping'})
    else:
        path = next(folder.glob('*.json'))
        value = files._stored(path)
        files._json(path, {**value, 'owner_note': 'new source metadata'})
    before = {p.name: p.read_bytes() for p in folder.glob('*.json')}
    with pytest.raises(preparation.PreparationChanged, match='изменились'):
        preparation.prepare(PROJECT, CUT, plan['guard'])
    assert {p.name: p.read_bytes() for p in folder.glob('*.json')} == before
    assert journal.load(PROJECT) == state


@pytest.mark.parametrize('damage', ['pdf_hash', 'pdf_symlink', 'budget', 'future_reader'])
def test_one_pdf_operation_still_fails_closed_on_source_and_budget(pair, monkeypatch, damage, tmp_path):
    folder, price_sha, state = source_set(pair, monkeypatch, 2)
    path = folder/(price_sha+'.json')
    if damage == 'future_reader':
        record = files._stored(path)
        files._json(path, {**record, 'reader': documents.READER_VERSION+1})
        with pytest.raises(files.ContractFilesProblem, match='Версия'):
            preparation.prepare(PROJECT, CUT)
        assert files._stored(path)['reader'] == documents.READER_VERSION+1
        return
    plan = preparation.prepare(PROJECT, CUT)
    pdf = folder/(price_sha+'.pdf')
    if damage == 'pdf_hash':
        pdf.write_bytes(pdf.read_bytes()+b'changed')
    elif damage == 'pdf_symlink':
        target = tmp_path/'outside.pdf'
        target.write_bytes(pdf.read_bytes())
        pdf.unlink(); pdf.symlink_to(target)
    else:
        monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_BYTES', 1)
    before = path.read_bytes()
    with pytest.raises((files.ContractFilesProblem, journal.IdentityProblem)):
        preparation.prepare(PROJECT, CUT, plan['guard'])
    assert path.read_bytes() == before and journal.load(PROJECT) == state


def test_preparation_cannot_run_inside_existing_ownership_pins(pair, monkeypatch):
    source_set(pair, monkeypatch, 2)
    with ownership.read_scope(PROJECT, CUT):
        with pytest.raises(files.ContractFilesProblem, match='до сборки'):
            preparation.prepare(PROJECT, CUT)


def test_native_api_exposes_preparation_only_as_authenticated_bounded_job(pair, monkeypatch):
    import main
    from fastapi.testclient import TestClient
    source_set(pair, monkeypatch, 2)
    client = TestClient(main.app)
    response = client.post('/monitor/contracts/parse-refresh', json={'project': PROJECT, 'cut': CUT})
    assert response.status_code in {401, 403, 422}
    route = next(r for r in main.app.routes if getattr(r, 'path', '') == '/monitor/contracts/parse-refresh')
    assert route.endpoint.__name__ == 'monitor_contract_parse_refresh'
    monkeypatch.setattr(main.core, '_require_admin_key', lambda *args: None)
    monkeypatch.setattr(main.core, '_env_str', lambda key, default='': 'synthetic-admin' if key == 'DEVELOPAID_ADMIN_KEY' else default)
    response = client.post('/monitor/contracts/parse-refresh', json={'key': 'synthetic-admin',
        'session': 'synthetic-session', 'project': PROJECT, 'cut': CUT, 'expected_guard': ''})
    assert response.status_code in {200, 202}, response.text
    value = response.json()
    assert isinstance(value['ticket'], str)
    for _ in range(100):
        if not value.get('pending'):
            break
        import time
        time.sleep(.01)
        value = client.post('/monitor/contracts/result', json={'key': 'synthetic-admin',
            'session': 'synthetic-session', 'ticket': value['ticket']}).json()
    assert value.get('ok') is True and value['parse_refresh']['remaining'] == 2, value
