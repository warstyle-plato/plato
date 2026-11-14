"""Synthetic retained originals and immutable legacy bindings; no live calls."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import TimeoutError
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_contract_identity as identity
import developaid_contract_identity_store as journal
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import ks
from test_monitor_cumulative_ledgers import archive

PROJECT = 'Synthetic correction project'
CUT = '2026-11-13'
ACTOR = 'a'*64


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def pins(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and path.suffix != '.lock'
            and path.name not in {journal.LOG, '.lock'}}


@pytest.fixture
def retained(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    monkeypatch.setattr(contracts, '_read_rss', lambda *_: ([], None, []))
    ledgers.store_archive(PROJECT, archive([('Old.xlsx', ks(number='C-OLD'))]), '2026-11-06', 'old.zip')
    ledgers.store_archive(PROJECT, archive([('New.xlsx', ks(number='C-NEW'))]), CUT, 'new.zip')
    old = contracts.build(PROJECT, '2026-11-06', include_history=False)['rows'][0]['id']
    new = contracts.build(PROJECT, CUT, include_history=False)['rows'][0]['id']
    assert old != new
    return journal.project_root(PROJECT), old, new


def inspected(retained):
    _, old, new = retained
    return identity.inventory(PROJECT, [old, new], CUT)


def confirm(retained, checked=None, **overrides):
    _, old, new = retained
    checked = checked or inspected(retained)
    values = dict(expected_revision=checked['revision'], inventory_sha256=checked['inventory_sha256'],
                  source_tokens=[item['source_token'] for item in checked['source_versions']],
                  anchor_id=old, canonical_number='C-NEW', note='Owner confirmed number correction.', actor=ACTOR)
    values.update(overrides)
    return identity.confirm(PROJECT, [old, new], CUT, **values)


def test_inventory_is_bounded_two_raw_ids_without_originals_or_bindings_writes(retained, monkeypatch):
    root, old, new = retained
    write(root/'cumulative_terms.json', {old: {'deadline': '2026-12-01', 'note': 'synthetic-private-note', 'updated_at': '2026-11-13T12:00:00+00:00'}})
    write(root/'contract_documents'/old/('d'*64+'.json'), {'sha256': 'd'*64, 'contract': {'number': 'C-OLD', 'date': '2026-01-01'},
          'terms': {'deadline': None}, 'removed_at': '2026-11-13T13:00:00+00:00', 'scan': {'confirmed_at': None}})
    before = pins(root)
    checked = inspected(retained)
    assert checked['revision'] == 0 and checked['financial_acceptance'] is False
    assert {row['identity']['contract'] for row in checked['source_versions']} == {'C-OLD', 'C-NEW'}
    assert all(row['source_identity_complete'] for row in checked['source_versions'])
    assert len(checked['source_versions']) == 2 and checked['raw_ids'] == sorted([old, new])
    text = json.dumps(checked)
    assert 'synthetic-private-note' not in text and 'Устройство стены' not in text and 'periods' not in text
    assert 'Old.xlsx' not in text and 'New.xlsx' not in text
    assert checked['bindings']['cards'][0 if old < new else 1]['documents'][0]['withdrawal_marker_present']
    assert pins(root) == before and not (root/journal.LOG).exists()


def test_confirm_is_append_only_current_time_and_two_raw_addresses_resolve(retained, monkeypatch):
    root, old, new = retained
    before = pins(root)
    original_rows = contracts.build(PROJECT, CUT, include_history=False)
    monkeypatch.setattr(journal, '_now', lambda: '2026-11-14T15:00:00+00:00')
    saved = confirm(retained)
    assert saved['revision'] == 1 and saved['recorded_at'] == '2026-11-14T15:00:00+00:00'
    assert saved['financial_acceptance'] is False
    for raw_id in (old, new):
        found = identity.resolve(PROJECT, raw_id, CUT)
        assert found['status'] == 'confirmed' and found['logical_id'] == old
        assert found['raw_id'] == raw_id and found['member_ids'] == sorted([old, new])
        assert found['canonical_number'] == 'C-NEW' and found['decision_recorded_at'] == saved['recorded_at']
        assert found['financial_acceptance'] is False and found['legal_signature_status'] == 'unknown'
        assert found['binding_resolution'] == 'not_combined'
    # Ownership does not choose between financial editions or change either raw card.
    logical = contracts.build(PROJECT, CUT, include_history=False)
    assert contracts.raw_rows(logical) == original_rows['rows']
    assert len(logical['rows']) == 1
    assert logical['rows'][0]['id'] == old
    assert logical['rows'][0]['raw_member_ids'] == sorted([old, new])
    assert logical['rows'][0]['amount'] is None and logical['rows'][0]['completed'] is None
    assert {key: value for key, value in pins(root).items() if key != journal.LOG} == before
    historic = identity.resolve(PROJECT, old, '2026-11-06')
    assert historic['status'] == 'confirmed' and '2026-11-14' in historic['annotation']
    assert len(historic['source_versions']) == 1
    assert historic['source_versions'][0]['identity']['contract'] == 'C-OLD'
    assert historic['source_versions'][0]['source_date'] == '2026-11-06'


def test_no_record_preserves_raw_identity_and_foreign_project_is_rejected(retained):
    _, old, new = retained
    for identifier in (old, new):
        found = identity.resolve(PROJECT, identifier, CUT)
        assert found['status'] == 'raw' and found['logical_id'] == identifier
    with pytest.raises(identity.IdentityProblem, match='не найден'):
        identity.inventory('Foreign project', [old, new], CUT)
    with pytest.raises(identity.IdentityProblem):
        identity.resolve(PROJECT, 'f'*64, CUT)


@pytest.mark.parametrize('changed', ['deadline', 'document', 'worklink', 'source'])
def test_stale_inventory_rejects_changed_bindings_and_versions(retained, changed):
    root, old, new = retained
    checked = inspected(retained)
    if changed == 'deadline':
        write(root/'cumulative_terms.json', {old: {'deadline': '2026-12-01'}})
    elif changed == 'document':
        write(root/'contract_documents'/new/('d'*64+'.json'), {'removed_at': '2026-11-13T01:00:00+00:00'})
    elif changed == 'worklink':
        write(root/'contract_links.json', {'version': 1, 'links': {'evidence': {'contract_id': old, 'confirmed': False}}})
    else:
        ledgers.store_archive(PROJECT, archive([('Again.xlsx', ks(number='C-NEW', period='jan'))]), '2026-11-12', 'again.zip')
    with pytest.raises(identity.IdentityProblem, match='изменились'):
        confirm(retained, checked)
    assert not (root/journal.LOG).exists()


@pytest.mark.parametrize('key,value', [('anchor_id', 'f'*64), ('canonical_number', 'C-INVENTED'),
                                      ('expected_revision', True), ('inventory_sha256', 'b'*64),
                                      ('source_tokens', ['a'*64, 'b'*64])])
def test_confirm_rejects_wrong_anchor_number_revision_and_tokens(retained, key, value):
    with pytest.raises(identity.IdentityProblem):
        confirm(retained, **{key: value})
    assert journal.load(PROJECT)['revision'] == 0


@pytest.mark.parametrize('field,value', [('customer', 'ООО «Чужой заказчик»'),
                                        ('contractor', 'ООО «Чужой подрядчик»'),
                                        ('contract_date', '2026-01-02')])
def test_equal_names_or_number_typo_never_override_different_parties_or_date(retained, field, value):
    checked = inspected(retained)
    members = copy.deepcopy(checked['source_versions'])
    members[0]['identity'][field] = value
    members[0]['source_token'] = journal.digest({key: val for key, val in members[0].items() if key != 'source_token'})
    with pytest.raises(identity.IdentityProblem, match='Стороны или даты'):
        identity._validate_members(PROJECT, members, 'C-NEW', retained[1])


def test_new_unreviewed_version_is_explicit_unknown_not_automatic_alias(retained):
    confirm(retained)
    ledgers.store_archive(PROJECT, archive([('Newer.xlsx', ks(number='C-NEW', period='jan'))]), '2026-11-14', 'newer.zip')
    found = identity.resolve(PROJECT, retained[2], '2026-11-14')
    assert found['status'] == 'source_conflict' and found['logical_id'] is None
    assert found['financial_acceptance'] is False
    assert found['source_versions'] and 'непроверенная' in found['reason']


def test_new_archive_cannot_inherit_a_correction_even_without_a_matching_raw_id(retained):
    confirm(retained)
    ledgers.store_archive(PROJECT, archive([('Other.xlsx', ks(number='C-THIRD'))]), '2026-11-14', 'other.zip')
    found = identity.resolve(PROJECT, retained[2], '2026-11-14')
    assert found['status'] == 'source_conflict' and found['logical_id'] is None
    assert len(found['reviewed_archives']) == 3


def test_confirm_cannot_omit_one_available_version_from_its_reviewed_set(retained):
    ledgers.store_archive(PROJECT, archive([('OtherVersion.xlsx', ks(number='C-OLD', period='jan'))]), '2026-11-12', 'version.zip')
    checked = inspected(retained)
    assert len(checked['source_versions']) == 3
    with pytest.raises(identity.IdentityProblem, match='все проверенные версии'):
        confirm(retained, checked, source_tokens=[row['source_token'] for row in checked['source_versions'][:2]])
    assert journal.load(PROJECT)['revision'] == 0


def test_revoke_is_new_event_never_resurrects_previous_decision(retained, monkeypatch):
    root, old, new = retained
    first = confirm(retained)
    before = (root/journal.LOG).read_bytes()
    monkeypatch.setattr(journal, '_now', lambda: '2099-01-01T01:00:00+00:00')
    result = identity.revoke(PROJECT, expected_revision=1, decision_id=first['event_id'], note='Owner revoked.', actor=ACTOR)
    assert result['revision'] == 2 and (root/journal.LOG).read_bytes().startswith(before)
    assert journal.load(PROJECT)['active'] == []
    for identifier in (old, new):
        found = identity.resolve(PROJECT, identifier, CUT)
        assert found['status'] == 'revoked' and found['logical_id'] is None
    with pytest.raises(identity.IdentityProblem):
        identity.revoke(PROJECT, expected_revision=2, decision_id=first['event_id'], note='Again', actor=ACTOR)


def test_concurrent_confirmation_has_one_winner_and_stale_cas_rejection(retained):
    checked = inspected(retained)
    def attempt():
        try:
            return confirm(retained, checked)['revision']
        except identity.IdentityProblem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [1, 409]
    assert journal.load(PROJECT)['revision'] == 1


def test_binding_conflicts_are_returned_without_combining_or_resurrecting(retained):
    root, old, new = retained
    write(root/'cumulative_terms.json', {old: {'deadline': '2026-12-01'}, new: {'deadline': '2026-12-02'}})
    for identifier, removed, confirmed in [(old, None, None), (new, '2026-11-13T01:00:00+00:00', '2026-11-13T00:00:00+00:00')]:
        record = {'sha256': 'd'*64, 'contract': {'number': 'C-OLD', 'date': '2026-01-01'},
                  'scan': {'confirmed_at': confirmed}, 'removed_at': removed}
        write(root/'contract_documents'/identifier/('d'*64+'.json'), record)
    write(root/'contract_links.json', {'version': 1, 'links': {'work': {'contract_id': old, 'candidate_contract_ids': [old, new],
                                                                   'blocked_contract_ids': [new], 'confirmed': False}}})
    before = pins(root)
    confirm(retained)
    found = identity.resolve(PROJECT, old, CUT)
    assert found['status'] == 'confirmed' and found['binding_resolution'] == 'conflict_or_unknown'
    assert set(found['binding_conflicts']) >= {'manual_deadline_conflict', 'withdrawal_conflict',
                                               'scan_confirmation_conflict', 'work_link_requires_resolution'}
    assert len(found['bindings']['cards']) == 2 and found['financial_acceptance'] is False
    assert {key: value for key, value in pins(root).items() if key != journal.LOG} == before


@pytest.mark.parametrize('broken', ['truncated', 'changed_actor', 'bad_member', 'backdate'])
def test_journal_tamper_and_partial_append_fail_closed(retained, broken):
    root, _, _ = retained
    confirm(retained)
    path = root/journal.LOG
    raw = path.read_bytes()
    event = journal.strict_json(raw)
    if broken == 'truncated':
        path.write_bytes(raw[:-1])
    else:
        if broken == 'changed_actor':
            event['actor'] = 'c'*64  # Do not reseal, chain mismatch.
        elif broken == 'bad_member':
            event['payload']['members'][0]['raw_id'] = []
            event['event_id'] = journal.digest({key: value for key, value in event.items() if key != 'event_id'})
        else:
            event['recorded_at'] = '2026-11-14T00:00:00'  # No native UTC offset.
            event['event_id'] = journal.digest({key: value for key, value in event.items() if key != 'event_id'})
        path.write_bytes(journal.canonical(event)+b'\n')
    with pytest.raises(identity.IdentityProblem):
        identity.resolve(PROJECT, retained[1], CUT)


def test_metadata_and_source_caps_and_symlinks_fail_closed(retained, monkeypatch, tmp_path):
    root, old, new = retained
    target = tmp_path/'outside.json'
    target.write_text('{}')
    (root/'cumulative_terms.json').symlink_to(target)
    with pytest.raises(identity.IdentityProblem):
        inspected(retained)
    (root/'cumulative_terms.json').unlink()
    monkeypatch.setattr(identity, 'MAX_ARCHIVES', 1)
    with pytest.raises(identity.IdentityProblem, match='предел'):
        inspected(retained)


def test_store_validates_prospective_event_before_appending(retained):
    root, _, _ = retained
    with journal.locked(PROJECT), pytest.raises(identity.IdentityProblem):
        journal.append_locked(PROJECT, expected_revision=0, actor=ACTOR, action='confirm', payload={'members': []})
    assert not (root/journal.LOG).exists()


@pytest.mark.parametrize('change', ['missing', 'changed'])
def test_missing_or_changed_retained_original_cannot_authorize_a_decision(retained, change):
    root, _, _ = retained
    checked = inspected(retained)
    path = root/'cumulative'/(checked['source_versions'][0]['snapshot_id']+'.zip')
    if change == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'synthetic-untrusted-original')
    with pytest.raises(identity.IdentityProblem):
        confirm(retained, checked)
    assert not (root/journal.LOG).exists()


def test_revoked_pairs_cannot_become_transitive_chains_or_cycles(retained):
    root, _, new = retained
    saved = confirm(retained)
    identity.revoke(PROJECT, expected_revision=1, decision_id=saved['event_id'], note='Owner revoked', actor=ACTOR)
    payload = copy.deepcopy(journal.load(PROJECT)['events'][0]['payload'])
    for member in payload['members']:
        if member['raw_id'] == new:
            member['raw_id'] = 'f'*64
            member['source_token'] = journal.digest({key: value for key, value in member.items() if key != 'source_token'})
    before = (root/journal.LOG).read_bytes()
    with journal.locked(PROJECT), pytest.raises(identity.IdentityProblem, match='цепочку или цикл'):
        journal.append_locked(PROJECT, expected_revision=2, actor=ACTOR, action='confirm', payload=payload)
    assert (root/journal.LOG).read_bytes() == before


def test_first_native_document_upload_obeys_the_same_card_lock_as_inventory(retained, monkeypatch):
    import developaid_contract_files as files
    root, _, new = retained
    entered = threading.Event()
    started = threading.Event()
    content = b'%PDF synthetic in-process lock fixture'
    row = {'id': new, 'contract': 'C-NEW', 'contract_date': '2026-01-01'}
    def record(sha, filename, data, uploaded_at):
        entered.set()
        return {'sha256': sha, 'contract': {'number': 'C-NEW', 'date': '2026-01-01'},
                'filename': filename, 'uploaded_at': uploaded_at}
    monkeypatch.setattr(files, '_record', record)
    def upload():
        started.set()
        return files.store(PROJECT, row, 'Generic.pdf', content)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with identity._binding_locks(PROJECT, retained[1:]):
            pending = pool.submit(upload)
            assert started.wait(1)
            assert not entered.wait(.1), 'first upload bypassed the native card lock'
            with pytest.raises(TimeoutError):
                pending.result(timeout=.01)
        assert pending.result(timeout=2)['already'] is False
    assert entered.is_set()
    assert (root/'contract_documents'/new/(hashlib.sha256(content).hexdigest()+'.pdf')).read_bytes() == content


@pytest.mark.parametrize('raw_ids', [[[], 'a'*64], ['a'*64, 'a'*64], ['a'*64, True], ['a'*64]])
def test_malformed_raw_id_pairs_have_controlled_errors(retained, raw_ids):
    with pytest.raises(identity.IdentityProblem):
        identity.inventory(PROJECT, raw_ids, CUT)


def test_inventory_change_during_cas_second_read_rejects_without_append(retained, monkeypatch):
    checked = inspected(retained)
    read = identity.inventory
    calls = []
    def race(*args, **kwargs):
        calls.append(True)
        result = read(*args, **kwargs)
        if len(calls) == 2:
            result['inventory_sha256'] = '0'*64
        return result
    monkeypatch.setattr(identity, 'inventory', race)
    with pytest.raises(identity.IdentityProblem, match='во время проверки'):
        confirm(retained, checked)
    assert journal.load(PROJECT)['revision'] == 0


def test_invalid_legacy_dates_and_confirmation_markers_stay_unknown(retained):
    root, old, _ = retained
    write(root/'cumulative_terms.json', {old: {'deadline': '2026-99-99'}})
    write(root/'contract_documents'/old/('d'*64+'.json'), {'removed_at': False, 'scan': {'confirmed_at': '/tmp/synthetic-private-marker'}})
    confirm(retained)
    found = identity.resolve(PROJECT, old, CUT)
    assert set(found['binding_conflicts']) >= {'manual_deadline_conflict', 'withdrawal_unknown', 'scan_confirmation_unknown'}
    assert '/tmp/synthetic-private-marker' not in json.dumps(found)
    assert found['legal_signature_status'] == 'unknown' and found['financial_acceptance'] is False


def test_late_alias_retarget_cannot_append_under_another_revision_zero_project(retained, monkeypatch):
    root, _, _ = retained
    other = root.parent/'Synthetic-other-project'
    other.mkdir()
    checked = inspected(retained)
    append = journal.append_locked
    def retarget(*args, **kwargs):
        # Deliberately bypass the native merge lock to exercise the late pin guard.
        write(root.parent/monitor._ALIASES_FILE, {'aliases': {monitor._slug(PROJECT): other.name}})
        return append(*args, **kwargs)
    monkeypatch.setattr(journal, 'append_locked', retarget)
    with pytest.raises(identity.IdentityProblem, match='имени проекта изменилась'):
        confirm(retained, checked)
    assert not (root/journal.LOG).exists() and not (other/journal.LOG).exists()


def test_native_alias_merge_lock_cannot_retarget_namespace_during_a_decision(retained):
    import fcntl
    root, _, _ = retained
    started, acquired = threading.Event(), threading.Event()
    def merge_lock():
        started.set()
        with (root.parent/'.aliases.lock').open('a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            acquired.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with journal.namespace(PROJECT):
            pending = pool.submit(merge_lock)
            assert started.wait(1) and not acquired.wait(.1)
        pending.result(timeout=2)
    assert acquired.is_set()


@pytest.mark.parametrize('value', ['1e999', '-1e999', 'NaN', 'Infinity', '-Infinity'])
def test_strict_json_rejects_nonfinite_overflow_in_legacy_metadata(value):
    with pytest.raises(identity.IdentityProblem):
        journal.strict_json(('{"value":'+value+'}').encode())
