"""Real descriptor IO and corpus bounds stay finite across fresh proofs."""
import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_identity as identity
import developaid_contract_identity_store as store
import developaid_contract_metadata_budget as proof
import developaid_contract_ownership as ownership
from test_contract_logical_ownership import pair, PROJECT, CUT
from test_contract_bounded_parse_preparation import source_set


def budget():
    return proof.MetadataBudget({'metadata_files': 0, 'metadata_bytes': 0, 'files': 0, 'bytes': 0})


def test_fresh_phases_charge_actual_reads_and_refuse_tenth_phase(tmp_path, monkeypatch):
    path = tmp_path/'metadata.json'
    path.write_bytes(b'{}')
    found, native, reads = budget(), store.read_bytes, []
    def observed(*args):
        reads.append(args[0])
        return native(*args)
    monkeypatch.setattr(store, 'read_bytes', observed)
    for _ in range(proof.MAX_PHASES):
        phase = found.phase()
        assert phase.read(path) == phase.read(path) == b'{}'
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        found.phase()
    assert len(reads) == found.totals['metadata_files'] == proof.MAX_PHASES
    assert found.totals['metadata_bytes'] == 2*proof.MAX_PHASES
    assert len(found.paths) == 1 and found.corpus_bytes == 2


def test_missing_paths_and_growth_cannot_hide_corpus_or_caller_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, 'MAX_METADATA_BYTES', 16)
    found, path = budget(), tmp_path/'metadata.json'
    assert found.phase().read(path) is None
    path.write_bytes(b'12345678')
    phase = found.phase()
    assert phase.read(path) == b'12345678'
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        phase.read(path, 4)
    path.write_bytes(b'1'*17)
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        found.phase().read(path)
    assert found.corpus_bytes == 8 and len(found.paths) == 1
    assert found.totals['metadata_bytes'] == 8


def test_missing_paths_also_consume_bounded_attempted_path_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, 'MAX_FILES', 2)
    found = budget()
    assert found.phase().read(tmp_path/'one') is None
    assert found.phase().read(tmp_path/'two') is None
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        found.phase().read(tmp_path/'three')
    assert found.totals['metadata_files'] == 2


@pytest.mark.parametrize('kind', ['metadata', 'price_pdf'])
def test_failed_descriptor_keeps_capacity_reserved_and_aborts_ownership_proof(tmp_path, monkeypatch, kind):
    path = tmp_path/'source'
    path.write_bytes(b'{}')
    found = budget()
    def raced(*args):
        raise store.IdentityProblem('Synthetic descriptor changed after a bounded read.')
    monkeypatch.setattr(store, 'read_bytes', raced)
    with pytest.raises(ownership.OwnershipProblem, match='descriptor changed'):
        phase = found.phase()
        (phase.read if kind == 'metadata' else phase.price_pdf)(path)
    if kind == 'metadata':
        assert found.totals['metadata_bytes'] == phase.bytes == 4*1024*1024
        assert found.totals['metadata_files'] == 1
    else:
        assert found.totals['bytes'] == 20*1024*1024
        assert found.totals['files'] == 1


@pytest.mark.parametrize('limit', ['files', 'bytes'])
def test_price_pdf_budget_stays_global_across_phases(tmp_path, monkeypatch, limit):
    path = tmp_path/'source.pdf'
    path.write_bytes(b'PDF source')
    found = budget()
    if limit == 'files':
        monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_FILES', 1)
    else:
        monkeypatch.setattr(files, 'MAX_PARSE_REFRESH_BYTES', len(path.read_bytes()))
    assert found.phase().price_pdf(path) == b'PDF source'
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        found.phase().price_pdf(path)
    assert found.totals['bytes'] == len(path.read_bytes())


def test_phase_inventory_keeps_complete_native_preimage_and_counters(pair, monkeypatch):
    source_set(pair, monkeypatch, count=2)
    ids = sorted([pair['old'], pair['new']])
    expected = identity.metadata_inventory(PROJECT, ids, correction=True)
    found = budget()
    phase = found.phase()
    one = identity.metadata_inventory(PROJECT, ids, correction=True, _read=phase.inventory())
    two = identity.metadata_inventory(PROJECT, ids, correction=True, _read=phase.inventory())
    assert one == two == expected
    assert store.digest(one) == store.digest(expected)
    assert found.totals['metadata_bytes'] == expected['metadata_bytes_read']


def test_refresh_reserves_write_cas_and_after_phases_before_any_cache_write(pair, monkeypatch):
    folder, _, state = source_set(pair, monkeypatch, count=2)
    before = {path: path.read_bytes() for path in folder.glob('*.json')}
    found = budget()
    for _ in range(proof.MAX_PHASES-3):
        found.phase()
    monkeypatch.setattr(documents, 'read', lambda _: pytest.fail('Phase exhaustion must precede parsing/writing.'))
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        files.refresh_parse_cache(PROJECT, [(tuple(sorted([pair['old'], pair['new']])), True)],
                                  found.totals, _proof_budget=found)
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert store.load(PROJECT) == state


@pytest.mark.parametrize('limit', ['corpus', 'per_file'])
def test_all_parsed_output_growth_is_reserved_before_first_batch_publication(pair, monkeypatch, limit):
    folder, _, state = source_set(pair, monkeypatch, count=2)
    before = {path: path.read_bytes() for path in folder.glob('*.json')}
    native, parsed = files._record, []
    if limit == 'corpus':
        monkeypatch.setattr(identity, 'MAX_METADATA_BYTES', sum(map(len, before.values()))+100_000)
    def record(*args, **kwargs):
        fresh = native(*args, **kwargs)
        parsed.append(True)
        if len(parsed) == 2:
            fresh['derived_notes'] = 'x'*(200_000 if limit == 'corpus' else 4*1024*1024)
        return fresh
    monkeypatch.setattr(files, '_record', record)
    monkeypatch.setattr(files, '_json', lambda *args: pytest.fail('Growth refusal must precede every own write.'))
    found = budget()
    with pytest.raises(ownership.OwnershipProblem, match='предел'):
        files.refresh_parse_cache(PROJECT, [(tuple(sorted([pair['old'], pair['new']])), True)],
                                  found.totals, _proof_budget=found)
    assert len(parsed) == 2
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert store.load(PROJECT) == state


def test_nested_capture_reserves_first_pin_before_refresh_can_publish(pair, monkeypatch):
    import developaid_monitor_contracts as contracts
    folder, _, state = source_set(pair, monkeypatch, count=2)
    before = {path: path.read_bytes() for path in folder.glob('*.json')}
    monkeypatch.setattr(documents, 'read', lambda _: pytest.fail('Missing first-pin phase must refuse before parsing.'))
    with pytest.raises((ownership.OwnershipProblem, contracts.ContractProblem), match='предел'):
        with ownership.read_scope(PROJECT, CUT) as context:
            for _ in range(4):
                context.metadata_budget.phase()
            contracts.build(PROJECT, CUT, include_history=False)
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert store.load(PROJECT) == state
