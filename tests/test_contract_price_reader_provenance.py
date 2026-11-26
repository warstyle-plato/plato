"""A reader upgrade is neither a new human price approval nor a signature."""
import copy
import hashlib

import pytest

import developaid_contract_correction as correction
import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_identity as identity
import developaid_contract_identity_store as journal
import developaid_contract_ownership as ownership
import developaid_contract_price_provenance as provenance
import developaid_monitor_contracts as contracts
from tests.test_contract_logical_ownership import pair, PROJECT, CUT
from tests.test_contract_source_correction import confirm
from tests.test_contract_price_follows_its_agreements import _pdf


def approved_price(pair, monkeypatch, version=14):
    current = documents.READER_VERSION
    monkeypatch.setattr(documents, 'READER_VERSION', version)
    row = next(row for row in pair['before']['rows'] if row['id'] == pair['new'])
    raw = _pdf('Договор подряда № SOURCE-B от 01.01.2026',
               '3.1. Цена Договора составляет 2 000 рублей с НДС.')
    sha = files.store(PROJECT, row, 'synthetic-native-price.pdf', raw)['sha256']
    folder = pair['root']/'contract_documents'/pair['new']
    path = folder/(sha+'.json')
    old = files._stored(path)
    old.pop('signature_evidence', None)
    assert provenance.FIELD not in old
    files._json(path, old)
    confirm(pair)
    event = copy.deepcopy(journal.load(PROJECT)['active'][0])
    assert set(event['payload']['price_document_evidence']) == set(correction.DOCUMENT_EVIDENCE_FIELDS)
    assert event['payload']['selected_values']['price']['amount'] == 2000
    assert provenance.FIELD not in files._stored(path)
    state = copy.deepcopy(journal.load(PROJECT))
    monkeypatch.setattr(documents, 'READER_VERSION', current)
    return folder, sha, raw, old, event, state


def current_row():
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    return row


@pytest.mark.parametrize('version', [11, 12, 13, 14, 15])
def test_legacy_native_document_price_survives_two_independent_reads(pair, monkeypatch, version):
    folder, sha, raw, old, event, state = approved_price(pair, monkeypatch, version)
    first = current_row()
    refreshed = files._stored(folder/(sha+'.json'))
    assert refreshed['reader'] == documents.READER_VERSION
    assert provenance.component(old) == provenance.component(refreshed)
    marker = refreshed[provenance.FIELD]
    assert marker['event_id'] == event['event_id']
    assert journal.digest(marker['approved_bindings']) == event['payload']['bindings_sha256']
    assert marker['from_reader'] == version and marker['to_reader'] == documents.READER_VERSION
    assert first['source_correction']['fresh'] and first['amount'] == 2000
    second = current_row()
    assert second['source_correction']['fresh'] and second['amount'] == 2000
    assert journal.load(PROJECT) == state, 'The entire immutable human journal must remain unchanged.'
    assert (folder/(sha+'.pdf')).read_bytes() == raw


@pytest.mark.parametrize('change', ['price', 'terms', 'contract', 'agreement', 'confirmation',
                                   'withdrawal', 'pdf', 'marker', 'saved_price', 'event'])
def test_component_or_source_mutation_cannot_reuse_price_witness(pair, monkeypatch, change):
    folder, sha, _, _, event, state = approved_price(pair, monkeypatch)
    assert current_row()['source_correction']['fresh']
    path = folder/(sha+'.json')
    record = files._stored(path)
    if change in {'price', 'terms'}:
        record[change]['changed_semantics'] = True
    elif change == 'contract':
        record['contract']['number'] = 'OTHER'
    elif change == 'agreement':
        record['agreement'] = {'number': '9', 'date': '2026-11-01'}
    elif change == 'confirmation':
        record['scan'] = {'confirmed_at': '2026-11-14T00:00:00+00:00'}
    elif change == 'withdrawal':
        record['removed_at'] = '2026-11-14T00:00:00+00:00'
    elif change == 'pdf':
        (folder/(sha+'.pdf')).write_bytes(b'%PDF-changed')
    elif change == 'marker':
        record[provenance.FIELD]['approved_bindings']['cards'][0]['manual_deadline'] = '2027-01-01'
    elif change == 'saved_price':
        projection = identity.metadata_inventory(PROJECT, [pair['old'], pair['new']], correction=True)
        doc = next(d for c in projection['cards'] for d in c['documents'] if d['document_sha256'] == sha)
        selected = copy.deepcopy(event['payload']['selected_values']['price'])
        selected['amount_source_label'] = 'Changed whole saved operand'
        assert not provenance.accepts(doc[provenance.FIELD], event, selected)
        return
    else:
        projection = identity.metadata_inventory(PROJECT, [pair['old'], pair['new']], correction=True)
        doc = next(d for c in projection['cards'] for d in c['documents'] if d['document_sha256'] == sha)
        replaced = copy.deepcopy(event)
        replaced['event_id'] = 'f'*64
        assert not provenance.accepts(doc[provenance.FIELD], replaced, event['payload']['selected_values']['price'])
        return
    if change != 'pdf':
        files._json(path, record)
    row = current_row()
    assert not row['source_correction']['fresh']
    assert journal.load(PROJECT) == state


@pytest.mark.parametrize('change', ['deadline', 'links'])
def test_unrelated_owner_edit_between_reads_preserves_price_component(pair, monkeypatch, change):
    folder, sha, _, _, _, state = approved_price(pair, monkeypatch)
    assert current_row()['source_correction']['fresh']
    if change == 'deadline':
        files._json(pair['root']/'cumulative_terms.json', {pair['new']: {'deadline': '2027-01-01'}})
    else:
        files._json(folder/'links.json', {'choices': {}, 'note': 'A separate owner work mapping edit'})
    assert current_row()['source_correction']['fresh']
    assert journal.load(PROJECT) == state
    assert provenance.FIELD in files._stored(folder/(sha+'.json'))


@pytest.mark.parametrize('change', ['deadline', 'links', 'metadata'])
def test_concurrent_owner_edits_keep_full_read_cas(pair, monkeypatch, change):
    import main
    folder, sha, _, _, _, _ = approved_price(pair, monkeypatch)
    original, changed = files.listing, []
    def listing(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            changed.append(True)
            if change == 'deadline':
                files._json(pair['root']/'cumulative_terms.json', {pair['new']: {'deadline': '2027-01-01'}})
            elif change == 'links':
                files._json(folder/'links.json', {'choices': {}, 'note': 'Concurrent owner edit'})
            else:
                record = files._stored(folder/(sha+'.json'))
                record['external_edit'] = True
                files._json(folder/(sha+'.json'), record)
        return result
    monkeypatch.setattr(files, 'listing', listing)
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert changed, 'The native operational read must reach the intercepted document enrichment.'
    assert result['ok'] is False and 'привязки изменились' in result['detail']


@pytest.mark.parametrize('change', ['deadline', 'links', 'metadata', 'pdf'])
def test_owner_or_source_edit_inside_parser_cannot_be_absorbed_by_initial_pin(pair, monkeypatch, change):
    folder, sha, _, _, _, state = approved_price(pair, monkeypatch)
    reader = documents.read
    def changed_during_parse(raw):
        parsed = reader(raw)
        if change == 'deadline':
            files._json(pair['root']/'cumulative_terms.json', {pair['new']: {'deadline': '2027-01-01'}})
        elif change == 'links':
            files._json(folder/'links.json', {'choices': {}, 'note': 'Owner edit during parser'})
        elif change == 'metadata':
            record = files._stored(folder/(sha+'.json'))
            record['external_edit_during_parse'] = True
            files._json(folder/(sha+'.json'), record)
        else:
            (folder/(sha+'.pdf')).write_bytes(raw+b'changed during parse')
        return parsed
    monkeypatch.setattr(documents, 'read', changed_during_parse)
    with pytest.raises((files.ContractFilesProblem, contracts.ContractProblem), match='привязки изменились|PDF изменился'):
        current_row()
    assert journal.load(PROJECT) == state
    if change == 'metadata':
        assert files._stored(folder/(sha+'.json'))['external_edit_during_parse'] is True


def test_old_operational_guard_is_rejected_then_fresh_register_opens_without_loop(pair, monkeypatch):
    import main
    _, _, _, _, _, state = approved_price(pair, monkeypatch, 14)
    monkeypatch.setattr(documents, 'READER_VERSION', 14)
    old = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert old['ok'], old
    old_row, = old['register']['rows']
    assert old_row['source_correction']['fresh']
    selected = old_row['source_correction']
    payload = dict(project=PROJECT, cut=CUT, contract_id=old_row['id'], view='operational',
        correction_id=selected['decision_id'], correction_guard=selected['read_guard'])
    monkeypatch.setattr(documents, 'READER_VERSION', 15)
    denied = main.core._monitor_cumulative_execute('documents', payload)
    assert denied['ok'] is False and denied['detail'] == ('Данные карточки отличаются от списка договоров. '
        'Закройте карточку, обновите страницу Монитора и откройте договор снова.')
    current = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert current['ok'], current
    row, = current['register']['rows']
    assert row['source_correction']['fresh'] and row['amount'] == 2000
    assert row['source_correction']['decision_id'] == selected['decision_id']
    assert row['source_correction']['read_guard'] != selected['read_guard']
    for _ in range(2):
        opened = main.core._monitor_cumulative_execute('documents', {**payload,
            'correction_guard': row['source_correction']['read_guard']})
        assert opened['ok'], opened
        assert opened['documents_raw_id'] == pair['new']
    assert journal.load(PROJECT) == state


@pytest.mark.parametrize('case', ['already_overwritten', 'overwritten_to_native14',
                                 'overwritten_to_current', 'before_changed'])
def test_missing_historical_witness_is_explicitly_unsupported(pair, monkeypatch, case):
    folder, sha, _, _, _, state = approved_price(pair, monkeypatch, 13)
    if case in {'already_overwritten', 'overwritten_to_native14', 'overwritten_to_current'}:
        # Reproduces an upgrade already performed by native14 without a witness.
        record = files._stored(folder/(sha+'.json'))
        record['reader'] = (documents.READER_VERSION if case == 'overwritten_to_current'
                            else 14 if case == 'overwritten_to_native14' else 15)
        files._json(folder/(sha+'.json'), record)
    else:
        files._json(folder/'links.json', {'choices': {}, 'note': 'Changed before historical proof was saved'})
    row = current_row()
    assert not row['source_correction']['fresh']
    assert 'свидетельства' in row['source_correction']['warning']
    assert provenance.FIELD not in files._stored(folder/(sha+'.json'))
    assert journal.load(PROJECT) == state


def test_raw_history_prepares_before_any_legacy_overwrite(pair, monkeypatch):
    folder, sha, _, _, _, state = approved_price(pair, monkeypatch, 13)
    with ownership.raw_history():
        contracts.build(PROJECT, CUT, include_history=False)
    assert provenance.FIELD in files._stored(folder/(sha+'.json'))
    assert current_row()['source_correction']['fresh']
    assert journal.load(PROJECT) == state


def test_price_approval_does_not_activate_newly_discovered_graph(pair, monkeypatch):
    folder, sha, _, old, _, state = approved_price(pair, monkeypatch)
    reader = documents.read
    def discovered(raw):
        result = reader(raw)
        result['schedule'] = {'calendar_basis': 'relative', 'columns': [], 'resources': [],
            'lines': [{'code': '1', 'name': 'Newly discovered graph', 'start': None, 'finish': None,
                       'relative_segments': [{'start_day': 1, 'finish_day': 7}]}]}
        return result
    monkeypatch.setattr(documents, 'read', discovered)
    assert not (old.get('schedule') or {}).get('lines')
    row = current_row()
    assert row['source_correction']['fresh'] and row['amount'] == 2000
    record = files._stored(folder/(sha+'.json'))
    assert record['gpr_pending'] is True and record[provenance.FIELD]
    listing = files.listing(PROJECT, pair['new'], CUT)
    assert listing['gpr']['source'] is None
    assert listing['gpr']['preview']['source']['sha256'] == sha
    assert listing['gpr']['history'] == []
    assert current_row()['source_correction']['fresh']
    assert journal.load(PROJECT) == state


def test_subset_native_lock_fails_before_overwrite_instead_of_expanding_locks(pair, monkeypatch):
    folder, sha, _, _, _, _ = approved_price(pair, monkeypatch)
    before = (folder/(sha+'.json')).read_bytes()
    with files._locked(folder):
        with pytest.raises((files.ContractFilesProblem, contracts.ContractProblem), match='полная блокировка'):
            current_row()
    assert (folder/(sha+'.json')).read_bytes() == before


def test_revoke_and_reconfirm_do_not_carry_old_event_witness(pair, monkeypatch):
    _, _, _, _, event, _ = approved_price(pair, monkeypatch)
    assert current_row()['source_correction']['fresh']
    state = journal.load(PROJECT)
    identity.revoke(PROJECT, expected_revision=state['revision'], decision_id=event['event_id'],
                    note='Native review revoked.', actor='a'*64)
    assert len(contracts.build(PROJECT, CUT, include_history=False)['rows']) == 2
    confirm(pair)
    active = journal.load(PROJECT)['active'][0]
    assert active['event_id'] != event['event_id']
    row = current_row()
    assert row['source_correction']['fresh']
    assert active['payload']['price_document_evidence']['reader_version_sha256'] == journal.digest(documents.READER_VERSION)


def test_current_reader_native_approval_needs_no_derived_witness(pair, monkeypatch):
    folder, sha, raw, _, _, state = approved_price(pair, monkeypatch, documents.READER_VERSION)
    for _ in range(2):
        row = current_row()
        assert row['source_correction']['fresh'] and row['amount'] == 2000
        assert provenance.FIELD not in files._stored(folder/(sha+'.json'))
    assert journal.load(PROJECT) == state
    assert (folder/(sha+'.pdf')).read_bytes() == raw


@pytest.mark.parametrize(('origin', 'intermediate'),
    [(origin, target) for target in (15, 16) for origin in range(11, target)])
@pytest.mark.parametrize('change', [None, 'deadline', 'links'])
def test_verified_reviewed_witness_advances_without_new_human_approval(pair, monkeypatch, change, origin, intermediate):
    current = documents.READER_VERSION
    monkeypatch.setattr(documents, 'READER_VERSION', intermediate)
    folder, sha, raw, old, event, state = approved_price(pair, monkeypatch, origin)
    assert current_row()['source_correction']['fresh']
    previous = copy.deepcopy(files._stored(folder/(sha+'.json'))[provenance.FIELD])
    assert previous['from_reader'] == origin and previous['to_reader'] == intermediate
    if change == 'deadline':
        files._json(pair['root']/'cumulative_terms.json', {pair['new']: {'deadline': '2027-01-01'}})
    elif change == 'links':
        files._json(folder/'links.json', {'choices': {}, 'note': 'Unrelated work mapping after verified reader'})
    monkeypatch.setattr(documents, 'READER_VERSION', current)
    for _ in range(2):
        row = current_row()
        assert row['source_correction']['fresh'] and row['amount'] == 2000
    refreshed = files._stored(folder/(sha+'.json'))
    marker = refreshed[provenance.FIELD]
    assert refreshed['reader'] == current and marker['to_reader'] == current
    assert {k:v for k,v in marker.items() if k != 'to_reader'} == {k:v for k,v in previous.items() if k != 'to_reader'}
    assert provenance.component(refreshed) == provenance.component(old)
    assert marker['event_id'] == event['event_id'] and journal.load(PROJECT) == state
    assert (folder/(sha+'.pdf')).read_bytes() == raw


@pytest.mark.parametrize('change', ['price', 'terms', 'contract', 'agreement', 'confirmation',
                                   'withdrawal', 'pdf', 'marker', 'saved_price', 'event'])
@pytest.mark.parametrize('intermediate', [15, 16])
def test_mutated_reviewed_witness_cannot_be_promoted(pair, monkeypatch, change, intermediate):
    current = 17
    monkeypatch.setattr(documents, 'READER_VERSION', intermediate)
    folder, sha, raw, _, event, state = approved_price(pair, monkeypatch, 14)
    assert current_row()['source_correction']['fresh']
    path = folder/(sha+'.json')
    record = files._stored(path)
    if change in {'price', 'terms'}:
        record[change]['changed_semantics'] = True
    elif change == 'contract':
        record['contract']['number'] = 'OTHER'
    elif change == 'agreement':
        record['agreement'] = {'number': '9', 'date': '2026-11-01'}
    elif change == 'confirmation':
        record['scan'] = {'confirmed_at': '2026-11-14T00:00:00+00:00'}
    elif change == 'withdrawal':
        record['removed_at'] = '2026-11-14T00:00:00+00:00'
    elif change == 'pdf':
        (folder/(sha+'.pdf')).write_bytes(b'%PDF-changed')
    elif change == 'marker':
        record[provenance.FIELD]['approved_bindings']['cards'][0]['manual_deadline'] = '2027-01-01'
    else:
        changed_event = copy.deepcopy(event)
        if change == 'saved_price':
            changed_event['payload']['selected_values']['price']['amount'] = 9999
        else:
            changed_event['event_id'] = 'e'*64
        monkeypatch.setattr(documents, 'READER_VERSION', current)
        before = identity.metadata_inventory(PROJECT, [pair['old'], pair['new']], correction=True)
        fresh = files._record(sha, record['filename'], raw, record['uploaded_at'])
        assert provenance.build(record, fresh, sha, pair['new'], raw,
            hashlib.sha256(path.read_bytes()).hexdigest(), changed_event, before) is None
        assert journal.load(PROJECT) == state
        return
    if change != 'pdf':
        files._json(path, record)
    monkeypatch.setattr(documents, 'READER_VERSION', current)
    if change == 'pdf':
        with pytest.raises((identity.IdentityProblem, contracts.ContractProblem, files.ContractFilesProblem)):
            current_row()
    else:
        assert not current_row()['source_correction']['fresh']
        assert provenance.FIELD not in files._stored(path) or files._stored(path)['reader'] != current
    assert journal.load(PROJECT) == state


def test_unreviewed_future_reader_does_not_inherit_price_witness(pair, monkeypatch):
    folder, sha, _, _, _, state = approved_price(pair, monkeypatch, 15)
    assert current_row()['source_correction']['fresh']
    monkeypatch.setattr(documents, 'READER_VERSION', 18)
    assert not current_row()['source_correction']['fresh']
    assert provenance.FIELD not in files._stored(folder/(sha+'.json'))
    assert journal.load(PROJECT) == state


@pytest.mark.parametrize('damage', ['symlink', 'budget'])
def test_second_read_source_validation_remains_no_follow_and_bounded(pair, monkeypatch, tmp_path, damage):
    folder, sha, raw, _, _, _ = approved_price(pair, monkeypatch)
    assert current_row()['source_correction']['fresh']
    if damage == 'symlink':
        target = tmp_path/'outside.pdf'
        target.write_bytes(raw)
        (folder/(sha+'.pdf')).unlink()
        (folder/(sha+'.pdf')).symlink_to(target)
        with pytest.raises((identity.IdentityProblem, contracts.ContractProblem)):
            current_row()
    else:
        monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_BYTES', len(raw)-1)
        with pytest.raises((ownership.OwnershipProblem, contracts.ContractProblem), match='объём|Объём'):
            current_row()


@pytest.mark.parametrize('origin', [11, 12, 13, 14, 15, 16])
def test_reviewed_reader17_preserves_exact_approved_component(pair, monkeypatch, origin):
    # Controlled native event fixture; actual PDF component parity is admitted separately.
    monkeypatch.setattr(documents, 'READER_VERSION', 17)
    folder, sha, raw, old, event, state = approved_price(pair, monkeypatch, origin)
    for _ in range(2):
        row = current_row()
        assert row['source_correction']['fresh'] and row['amount'] == 2000
    refreshed = files._stored(folder/(sha+'.json'))
    marker = refreshed[provenance.FIELD]
    assert refreshed['reader'] == 17 and marker['to_reader'] == 17
    assert marker['from_reader'] == origin and marker['event_id'] == event['event_id']
    assert provenance.component(refreshed) == provenance.component(old)
    assert journal.load(PROJECT) == state
    assert (folder/(sha+'.pdf')).read_bytes() == raw
