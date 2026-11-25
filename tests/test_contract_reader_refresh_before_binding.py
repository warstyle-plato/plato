"""A reader cache upgrade cannot invalidate its own native ownership read.

Owner/source edits remain protected by the full final inventory CAS.
All sources and identity decisions here are synthetic, in temporary storage.
"""
import hashlib
import multiprocessing

import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_identity as identity
import developaid_contract_ownership as ownership
import developaid_monitor_contracts as contracts
from tests.test_contract_logical_ownership import pair, PROJECT, CUT
from tests.test_contract_source_correction import confirm
from tests.test_contract_documents_are_read_from_their_tables import schedule_pdf


def retained(pair, monkeypatch, version, *, scan=None, removed=False, pending=False):
    current = documents.READER_VERSION
    monkeypatch.setattr(documents, 'READER_VERSION', version)
    row = next(row for row in pair['before']['rows'] if row['id'] == pair['new'])
    raw = schedule_pdf(title=('к Договору подряда № SOURCE-B от 01.01.2026', 'График производства работ'))
    sha = files.store(PROJECT, row, 'synthetic-source.pdf', raw)['sha256']
    folder = pair['root']/'contract_documents'/pair['new']
    value = files._stored(folder/(sha+'.json'))
    if scan is not None:
        value['scan'] = scan
    if removed:
        value['removed_at'] = '2026-11-14T00:00:00+00:00'
    if pending:
        value['gpr_pending'] = True
    files._json(folder/(sha+'.json'), value)
    confirm(pair)
    monkeypatch.setattr(documents, 'READER_VERSION', current)
    return folder, sha, raw, value


@pytest.mark.parametrize('version', [11, 12, 13])
def test_native_operational_first_read_refreshes_old_reader_before_pin(pair, monkeypatch, version):
    import main
    folder, sha, raw, _ = retained(pair, monkeypatch, version)
    calls = []
    reader = documents.read
    def observed(data):
        calls.append(hashlib.sha256(data).hexdigest())
        return reader(data)
    monkeypatch.setattr(documents, 'read', observed)
    view = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert view['ok'], view
    assert calls == [sha]
    assert (folder/(sha+'.pdf')).read_bytes() == raw
    assert files._stored(folder/(sha+'.json'))['reader'] == documents.READER_VERSION
    row, = view['register']['rows']
    selected = row['source_correction']
    card = main.core._monitor_cumulative_execute('documents', dict(project=PROJECT, cut=CUT,
        contract_id=row['id'], view='operational', correction_id=selected['decision_id'],
        correction_guard=selected['read_guard']))
    assert card['ok'], card
    assert card['documents_raw_id'] == pair['new'] and calls == [sha]
    assert row['completed'] == 400 and row['amount'] == 1500


def test_current_reader_does_not_reparse_or_write_metadata(pair, monkeypatch):
    folder, sha, _, _ = retained(pair, monkeypatch, documents.READER_VERSION)
    before = (folder/(sha+'.json')).read_bytes()
    monkeypatch.setattr(documents, 'read', lambda _: pytest.fail('A current parse must be reused.'))
    contracts.build(PROJECT, CUT, include_history=False)
    assert (folder/(sha+'.json')).read_bytes() == before


def test_disabling_pre_pin_refresh_reproduces_native_self_drift(pair, monkeypatch):
    import main
    retained(pair, monkeypatch, 11)
    monkeypatch.setattr(files, 'refresh_parse_cache', lambda *args: None)
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert result['ok'] is False and 'привязки изменились' in result['detail']


@pytest.mark.parametrize('scan', [
    {'kind': 'contract', 'confirmed_at': '2026-11-14T00:00:00+00:00', 'manual_note': 'Keep manual values'},
    {'kind': 'contract', 'confirmed_at': None, 'manual_note': 'Awaiting confirmation'},
])
def test_scan_cache_is_never_reparsed_or_confirmed(pair, monkeypatch, scan):
    folder, sha, _, value = retained(pair, monkeypatch, 12, scan=scan)
    before = (folder/(sha+'.json')).read_bytes()
    monkeypatch.setattr(documents, 'read', lambda _: pytest.fail('A scan must not enter the text reader.'))
    contracts.build(PROJECT, CUT, include_history=False)
    assert (folder/(sha+'.json')).read_bytes() == before
    assert files._stored(folder/(sha+'.json'))['scan'] == value['scan']


def test_removed_and_pending_markers_survive_cache_refresh(pair, monkeypatch):
    folder, sha, _, _ = retained(pair, monkeypatch, 11, removed=True, pending=True)
    contracts.build(PROJECT, CUT, include_history=False)
    fresh = files._stored(folder/(sha+'.json'))
    assert fresh['reader'] == documents.READER_VERSION
    assert fresh['removed_at'] == '2026-11-14T00:00:00+00:00' and fresh['gpr_pending'] is True


@pytest.mark.parametrize('change', ['links', 'deadline', 'source'])
def test_native_final_pin_still_refuses_owner_or_source_edit_during_read(pair, monkeypatch, change):
    import main
    folder, sha, _, _ = retained(pair, monkeypatch, 11)
    original, changed = files.listing, []
    def listing(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            changed.append(True)
            if change == 'links':
                files._json(folder/'links.json', {'choices': {}, 'external_note': 'New owner edit'})
            elif change == 'deadline':
                files._json(pair['root']/'cumulative_terms.json', {pair['new']: {'deadline': '2027-01-01', 'note': 'External edit'}})
            else:
                value = files._stored(folder/(sha+'.json'))
                value['external_source_edit'] = True
                files._json(folder/(sha+'.json'), value)
        return result
    monkeypatch.setattr(files, 'listing', listing)
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert result['ok'] is False and 'привязки изменились' in result['detail']


def test_nested_capture_retains_prior_pin_and_source_cache(pair, monkeypatch):
    folder, sha, _, _ = retained(pair, monkeypatch, 12)
    with pytest.raises((ownership.OwnershipProblem, contracts.ContractProblem), match='привязки изменились'):
        with ownership.read_scope(PROJECT, CUT) as context:
            contracts.build(PROJECT, CUT, include_history=False)
            pins = dict(context.binding_pins)
            cache = dict(context.source_cache)
            assert pins and context.parse_refresh_budget['files'] == 2
            contracts.build(PROJECT, CUT, include_history=False)
            assert context.binding_pins == pins
            assert all(context.source_cache[key] is value for key, value in cache.items())
            files._json(folder/'links.json', {'choices': {}, 'external_note': 'Nested owner edit'})
            contracts.build(PROJECT, CUT, include_history=False)


@pytest.mark.parametrize('damage', ['hash', 'missing', 'symlink', 'lock_symlink', 'budget'])
def test_refresh_fails_closed_on_invalid_source_lock_or_budget(pair, monkeypatch, damage, tmp_path):
    folder, sha, raw, _ = retained(pair, monkeypatch, 11)
    path = folder/(sha+'.json')
    before = path.read_bytes()
    if damage == 'hash':
        (folder/(sha+'.pdf')).write_bytes(raw+b'changed')
    elif damage == 'missing':
        (folder/(sha+'.pdf')).unlink()
    elif damage == 'symlink':
        target = tmp_path/'outside.pdf'
        target.write_bytes(raw)
        (folder/(sha+'.pdf')).unlink()
        (folder/(sha+'.pdf')).symlink_to(target)
    elif damage == 'lock_symlink':
        target = tmp_path/'outside.lock'
        target.write_bytes(b'leave unchanged')
        (folder/'.lock').unlink()
        (folder/'.lock').symlink_to(target)
    else:
        monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_BYTES', len(raw)-1)
    with pytest.raises((files.ContractFilesProblem, identity.IdentityProblem, contracts.ContractProblem)):
        contracts.build(PROJECT, CUT, include_history=False)
    assert path.read_bytes() == before, 'An invalid preflight cannot publish a partial cache upgrade.'
    if damage == 'lock_symlink':
        assert target.read_bytes() == b'leave unchanged'


def test_budget_is_aggregate_across_context_calls(pair, monkeypatch):
    folder, sha, raw, _ = retained(pair, monkeypatch, 11)
    budget = {'files': 0, 'bytes': len(raw), 'metadata_files': 0, 'metadata_bytes': 0}
    monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_BYTES', len(raw)*2-1)
    before = (folder/(sha+'.json')).read_bytes()
    with pytest.raises(files.ContractFilesProblem, match='предел'):
        files.refresh_parse_cache(PROJECT, [(tuple(sorted([pair['old'], pair['new']])), True)], budget)
    assert (folder/(sha+'.json')).read_bytes() == before


def _worker_read(start, output):
    original = documents.read
    def observed(raw):
        output.put(('parse', hashlib.sha256(raw).hexdigest()))
        return original(raw)
    documents.read = observed
    start.wait(10)
    try:
        result = contracts.build(PROJECT, CUT, include_history=False)
        output.put(('result', len(result['rows']) == 1))
    except Exception as exc:
        output.put(('error', type(exc).__name__))


def test_two_workers_refresh_one_cache_without_self_pin_drift(pair, monkeypatch):
    folder, sha, _, _ = retained(pair, monkeypatch, 11)
    context = multiprocessing.get_context('fork')
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_worker_read, args=(start, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.set()
    messages = [output.get(timeout=20) for _ in range(3)]
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0
    assert sorted(messages) == [('parse', sha), ('result', True), ('result', True)]
    assert files._stored(folder/(sha+'.json'))['reader'] == documents.READER_VERSION
