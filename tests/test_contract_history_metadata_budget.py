"""Native multi-group history must spend IO on proofs, not repeated cuts.

Synthetic membership decisions deliberately do not approve financial sources.
"""
import hashlib
import json

import pytest

import developaid_contract_documents as documents
import developaid_contract_identity as identity
import developaid_contract_identity_store as store
import developaid_contract_ownership as ownership
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import ks
from test_monitor_cumulative_ledgers import archive

PROJECT = 'Synthetic multi-group metadata budget'
CUT = '2026-11-25'


def retained(monkeypatch, tmp_path, groups, document_count):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    monkeypatch.setattr(contracts, '_read_rss', lambda *_: ([], None, []))
    names = [f'G{i}-{side}' for i in range(groups) for side in ('OLD', 'NEW')]
    names += [f'OTHER-{i}' for i in range(34-len(names))]
    books = [(name+'.xlsx', ks(number=name)) for name in names]
    for day in ['2026-11-01', '2026-11-06', '2026-11-13', '2026-11-18', CUT]:
        # Each grouped contract keeps its one approved source snapshot.
        ledgers.store_archive(PROJECT, archive(books if day == '2026-11-01' else books[-1:]),
                              day, 'synthetic.zip')
    raw = contracts.build(PROJECT, CUT, include_history=False)
    by_number = {row['contract']: row['id'] for row in raw['rows']}
    root, pairs = store.project_root(PROJECT), []
    identifiers = [by_number[name] for name in names[:groups*2]]
    for index in range(document_count):
        identifier = identifiers[index % len(identifiers)]
        folder = root/'contract_documents'/identifier
        folder.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(f'{identifier}-{index}'.encode()).hexdigest()
        record = {'sha256': sha, 'reader': documents.READER_VERSION,
                  'contract': {'number': 'SYNTHETIC', 'date': '2026-01-01'},
                  'price': None, 'terms': {'deadline': None}}
        (folder/(sha+'.json')).write_text(json.dumps(record))
    for i in range(groups):
        pair = sorted([by_number[f'G{i}-OLD'], by_number[f'G{i}-NEW']])
        pairs.append(pair)
        checked = identity.inventory(PROJECT, pair, CUT)
        identity.confirm(PROJECT, pair, CUT,
            expected_revision=checked['revision'], inventory_sha256=checked['inventory_sha256'],
            source_tokens=[member['source_token'] for member in checked['source_versions']],
            anchor_id=pair[0], canonical_number=f'G{i}-NEW',
            note='Synthetic membership only; no financial source chosen.', actor='a'*64)
    return root, pairs


@pytest.mark.parametrize(('groups', 'count'), [(7, 42), (8, 64)])
def test_native_view_history_keeps_complete_register_with_unchanged_io_cap(monkeypatch, tmp_path, groups, count):
    import main
    root, pairs = retained(monkeypatch, tmp_path, groups, count)
    journal = (root/store.LOG).read_bytes()
    approved = [identity.metadata_inventory(PROJECT, pair) for pair in pairs]
    native, reads = store.read_bytes, []
    def observed(path, *args, **kwargs):
        raw = native(path, *args, **kwargs)
        if raw is not None and path.suffix == '.json' and 'contract_documents' in path.parts:
            reads.append((path, len(raw)))
        return raw
    monkeypatch.setattr(store, 'read_bytes', observed)
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert result['ok'], result
    register = result['register']
    assert len(register['rows']) == 34-groups
    assert len(contracts.raw_rows(register)) == 34
    assert len(reads) == 4*count <= identity.MAX_FILES
    assert len({path for path, _ in reads}) == count
    assert sum(size for _, size in reads) <= identity.MAX_METADATA_BYTES
    # Read accounting is never written into an old source decision/preimage.
    assert (root/store.LOG).read_bytes() == journal
    assert [identity.metadata_inventory(PROJECT, pair) for pair in pairs] == approved
    parents = [row for row in register['rows'] if row.get('logical_ownership')]
    assert len(parents) == groups
    assert all(row['amount'] is None and row['completed'] is None for row in parents)


def test_distinct_native_reads_still_obey_aggregate_cap(monkeypatch, tmp_path):
    import main
    root, _ = retained(monkeypatch, tmp_path, 8, 65)
    journal = (root/store.LOG).read_bytes()
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert not result['ok']
    assert result['detail'] == 'Общий объём метаданных уточнений превышает предел одной сборки.'
    assert (root/store.LOG).read_bytes() == journal


@pytest.mark.parametrize('change', ['document', 'new_document', 'links', 'deadline'])
def test_history_deferral_still_rejects_metadata_changes(monkeypatch, tmp_path, change):
    import main
    import developaid_contract_files as files
    root, pairs = retained(monkeypatch, tmp_path, 7, 42)
    journal = (root/store.LOG).read_bytes()
    folder = root/'contract_documents'/pairs[0][0]
    native, changed = contracts._composition, []
    def composition(*args, **kwargs):
        value = native(*args, **kwargs)
        if ownership.is_raw_history() and not changed:
            changed.append(True)
            path = next(folder.glob('*.json'))
            if change == 'document':
                files._json(path, {**files._stored(path), 'owner_note': 'new edit'})
            elif change == 'new_document':
                files._json(folder/('f'*64+'.json'), {**files._stored(path), 'sha256': 'f'*64})
            elif change == 'links':
                files._json(folder/'links.json', {'choices': {}, 'owner_note': 'new edit'})
            else:
                files._json(root/'cumulative_terms.json', {pairs[0][0]: {'deadline': '2027-01-01'}})
        return value
    monkeypatch.setattr(contracts, '_composition', composition)
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert changed and not result['ok']
    assert 'привязки изменились' in result['detail']
    assert (root/store.LOG).read_bytes() == journal


@pytest.mark.parametrize('change', ['downgraded_reader', 'new_pdf'])
def test_late_lazy_refresh_is_refused_before_parsing_or_writing(monkeypatch, tmp_path, change):
    import main
    import developaid_contract_files as files
    from test_contract_documents_are_read_from_their_tables import schedule_pdf
    root, pairs = retained(monkeypatch, tmp_path, 7, 42)
    folder = root/'contract_documents'/pairs[0][0]
    journal = (root/store.LOG).read_bytes()
    native, changed = contracts._composition, []
    def composition(*args, **kwargs):
        value = native(*args, **kwargs)
        if ownership.is_raw_history() and not changed:
            path = next(folder.glob('*.json'))
            record = {**files._stored(path), 'reader': 11, 'owner_note': 'late source edit'}
            if change == 'new_pdf':
                raw = schedule_pdf(title=('Договор № SYNTHETIC', 'График производства работ'))
                sha = hashlib.sha256(raw).hexdigest()
                (folder/(sha+'.pdf')).write_bytes(raw)
                path, record['sha256'] = folder/(sha+'.json'), sha
            files._json(path, record)
            changed.append((path, path.read_bytes()))
        return value
    monkeypatch.setattr(contracts, '_composition', composition)
    monkeypatch.setattr(documents, 'read', lambda _: pytest.fail('Pinned metadata cannot trigger a lazy write.'))
    result = main.core._monitor_cumulative_execute('view', {'project': PROJECT, 'cut': CUT})
    assert changed and not result['ok']
    assert 'привязки изменились' in result['detail']
    assert all(path.read_bytes() == raw for path, raw in changed)
    assert (root/store.LOG).read_bytes() == journal
