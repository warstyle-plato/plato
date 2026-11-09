"""Source report spellings use one bounded, register-scoped party resolver."""
from __future__ import annotations

import copy
import datetime

import pytest

import developaid_monitor_contract_links as links
from test_monitor_contract_links import (
    CUT, FIRST, PROJECT, SECOND, evidence, install_register, isolated, register, report,
)


def own_register(name='ООО «Мастер»', *, two=False):
    data = register(two=two)
    for row in data['rows']:
        row.update(contractor=name, subject='Устройство кладки стен',
                   scope=['Корпуса 1 и 2, 2–13 этажа Корпуса 3'], physical_items=[])
    return data


@pytest.mark.parametrize('source,target,basis', [
    ('Мастер( кладка)', 'ООО «Мастер»', 'work_context'),
    ('Мастер', 'ООО «Мастер Инж»', 'short_name'),
    ('Мастер', 'ООО «СК Мастер»', 'short_name'),
])
def test_supported_report_spellings_resolve_without_changing_source_ids(source, target, basis):
    data = own_register(target)
    report('Корпус 3 — 2,4,6 эт.', party=source)
    raw, = links._evidence(PROJECT, data, CUT)
    before = copy.deepcopy(data)
    result = evidence(data)
    assert result['unmatched_works'] == []
    item, = result['rows'][0]['reconciliation']['daily_evidence']
    assert item['id'] == raw['id'] and item['reported_contractor'] == source
    assert item['scope'] == 'Корпус 3' and not item.get('scope_ambiguous')
    assert item['contract_id'] == FIRST and item['link_basis'] == 'party_alias'
    assert item['party_match_basis'] == basis
    assert data == before and not links._path(PROJECT).exists()


@pytest.mark.parametrize('source,target', [
    ('Маст', 'ООО «Мастер Инж»'),
    ('Мастер Строй', 'ООО «Мастер»'),
    ('ООО Мастер', 'ООО «Мастер Инж»'),
    ('ИП Мастер', 'ООО «СК Мастер»'),
    ('Мастер( вентиляция)', 'ООО «Мастер»'),
    ('ИП Мастер( кладка)', 'ООО «Мастер»'),
])
def test_source_name_words_and_legal_forms_cannot_be_dropped(source, target):
    data = own_register(target)
    report(party=source)
    item, = evidence(data)['unmatched_works']
    assert item['selectable_contract_ids'] == [] and not item['contract_id']


def test_a_short_name_never_picks_a_legal_entity_after_scope_filtering(monkeypatch):
    data = own_register('ООО «Мастер Инж»', two=True)
    data['rows'][1].update(contractor='ООО «Мастер Строй»', scope=['Корпус 2'])
    install_register(monkeypatch, data)
    report('Корпус 1 бетонирование', party='Мастер')
    item, = evidence(data)['unmatched_works']
    assert item['party_match_basis'] == 'ambiguous_alias'
    assert item['selectable_contract_ids'] == [FIRST]
    assert item['match_status'] == 'proposed' and not item['contract_id']
    links.set_link(PROJECT, FIRST, item['id'], CUT)
    assert evidence(data)['unmatched_works'] == []


def test_two_contracts_of_the_same_aliased_party_require_a_real_selection(monkeypatch):
    data = install_register(monkeypatch, own_register('ООО «Мастер Инж»', two=True))
    report(party='Мастер')
    item, = evidence(data)['unmatched_works']
    assert item['selectable_contract_ids'] == [FIRST, SECOND]
    assert item['match_status'] == 'ambiguous' and not item['suggested_contract_id']
    links.set_link(PROJECT, SECOND, item['id'], CUT)
    assert evidence(data)['unmatched_works'] == []
    links.set_link(PROJECT, SECOND, item['id'], CUT, confirmed=False)
    assert evidence(data)['unmatched_works'][0]['match_status'] == 'ambiguous'


def test_a_display_annotation_cannot_erase_the_named_source_party():
    data = own_register('ООО «СК Мастер»')
    source = {'date': '2026-10-14', 'parsed': {
        'contractors': [{'name': 'Мастер (ИТП)'}],
        'works': [{'contractor': 'Другой', 'line': 'Мастер — Корпус 1 бетонирование'}],
    }}
    result = evidence(data, _reports=[source], _parties=['Мастер (ИТП)'])
    assert result['unmatched_works'] == []
    item, = result['rows'][0]['reconciliation']['daily_evidence']
    assert item['reported_contractor'] == 'Мастер' and item['contractor'] == 'Мастер (ИТП)'
    assert item['contract_id'] == FIRST


@pytest.mark.parametrize('source,scope', [
    ('Корпус 3 — 2,4,6 эт.', {'3'}),
    ('Корпус 3 - 2,3,4, эт', {'3'}),
    ('Корпус 3 - 1,,20,21,22 эт.(затраты)', {'3'}),
    ('Корпуса 1 и 2, 2–13 этажа Корпуса 3', {'1', '2', '3'}),
    ('Корпуса 1, 2,3 этажи, Корпус 2', {'1', '2'}),
])
def test_explicitly_named_floors_do_not_become_corpus_numbers(source, scope):
    assert links._scope_info(source) == (scope, False)


@pytest.mark.parametrize('source', ['Корпус 1-2', 'Корпус 3 - 2,4,6', 'Корпус 1/2'])
def test_unlabelled_number_ranges_stay_ambiguous(source):
    assert links._scope_info(source)[1]


def test_corrected_scope_retains_the_original_persisted_evidence_id():
    data = own_register()
    line = 'Корпус 3, 2,4,6 эт.'
    report(line, party='Мастер')
    item, = links._evidence(PROJECT, data, CUT)
    old = {**item, 'scope': 'Корпус 2, Корпус 3, Корпус 4, Корпус 6'}
    expected_signature = links._signature(old, source_text=line, source_contractor='Мастер')
    assert item['scope'] == 'Корпус 3'
    assert item['signature'] == expected_signature
    assert item['id'] == links._digest([links._project_key(PROJECT), item['date'], expected_signature])


def test_legacy_manual_confirmation_and_revocation_survive_the_new_alias_rule(monkeypatch):
    data = install_register(monkeypatch, own_register())
    report(party='Мастер( кладка)')
    item, = links._evidence(PROJECT, data, CUT)
    with links._locked(PROJECT):
        links._write(PROJECT, {'version': 1, 'links': {item['id']: {
            'signature': item['signature'], 'evidence_id': item['id'],
            'contract_id': FIRST, 'confirmed': True, 'source_date': item['date'],
            'confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'basis': 'manual', 'candidate_contract_ids': [],
        }}})
    found, = evidence(data)['rows'][0]['reconciliation']['daily_evidence']
    assert found['id'] == item['id'] and found['link_basis'] == 'manual'
    links.set_link(PROJECT, FIRST, found['id'], CUT, confirmed=False)
    remaining, = evidence(data)['unmatched_works']
    assert remaining['id'] == item['id'] and remaining['match_status'] == 'proposed'
    assert not links._read(PROJECT)['links'][item['id']]['confirmed']


def test_the_report_uses_the_same_resolved_party_and_contract_progress():
    data = own_register('ООО «СК Мастер»')
    report('Корпус 1 бетонирование', party='Мастер')
    resolved = evidence(data)
    groups = [{'contractor': 'ООО «СК Мастер»', 'lines': [
        {'line': 'Корпус 1 бетонирование', 'days': ['2026-10-14']}]}]
    result = links.enrich_report_works(PROJECT, groups, '2026-10-12', CUT,
                                      context={'register': resolved})
    found, = result[0]['lines'][0]['contract_links']
    assert found['id'] == FIRST and found['completion_ratio'] == .25
    assert result[0]['lines'][0]['contract_status'] == 'Договор определён'


def test_a_sole_contract_identity_does_not_allocate_unqualified_work_quantities():
    data = own_register('ООО «Мастер Инж»')
    data['rows'][0]['physical_items'] = [{'name': 'Бетонирование', 'scope': 'Корпус 3', 'unit': 'м3',
                                         'plan_quantity': 10, 'completed_quantity': 8, 'completion_ratio': .8}]
    report('Корпус 3 — 2,4,6', party='Мастер')
    before = copy.deepcopy(data)
    resolved = evidence(data)
    assert resolved['unmatched_works'] == []
    item, = resolved['rows'][0]['reconciliation']['daily_evidence']
    assert item['contract_id'] == FIRST and item['scope_ambiguous']
    assert not item['scope_confirmed'] and not links._scope_covers(item, data['rows'][0])
    assert 'объёмы' in item['scope_note'] and data == before
    groups = [{'contractor': 'Мастер', 'lines': [
        {'line': item['text'], 'days': [item['date']]}]}]
    found, = links.enrich_report_works(PROJECT, groups, '2026-10-12', CUT,
                                       context={'register': resolved})[0]['lines'][0]['contract_links']
    assert found['id'] == FIRST and found['completion_ratio'] == .25
    assert not found['scope_confirmed'] and found['scope_review_dates'] == [item['date']]
    assert found['scope_note'] == 'Договор определён; корпусный состав сообщений требует уточнения.'
    assert 'всему договору' not in found['scope_note']
    assert not {'physical_items', 'plan_quantity', 'completed_quantity'} & found.keys()
    assert resolved['rows'][0]['physical_items'] == before['rows'][0]['physical_items']


def test_unknown_corpus_range_cannot_choose_between_two_same_party_contracts(monkeypatch):
    data = install_register(monkeypatch, own_register('ООО «Мастер Инж»', two=True))
    report('Корпус 3 — 2,4,6', party='Мастер')
    item, = evidence(data)['unmatched_works']
    assert not item['selectable_contract_ids'] and not item['contract_id']
    with pytest.raises(links.LinkProblem, match='Корпус'):
        links.set_link(PROJECT, FIRST, item['id'], CUT)


def test_a_proven_foreign_corpus_is_still_a_blocker_with_one_contract():
    data = own_register('ООО «Мастер Инж»')
    report('Корпус 4 — 2,4,6', party='Мастер')
    item, = evidence(data)['unmatched_works']
    assert not item['selectable_contract_ids'] and not item['contract_id']


def test_a_foreign_legacy_manual_choice_is_not_replaced_by_the_new_alias_rule(monkeypatch):
    data = own_register(two=True)
    data['rows'][1]['contractor'] = 'ООО «Другой»'
    install_register(monkeypatch, data)
    report(party='Мастер( кладка)')
    item, = links._evidence(PROJECT, data, CUT)
    with links._locked(PROJECT):
        links._write(PROJECT, {'version': 1, 'links': {item['id']: {
            'signature': item['signature'], 'evidence_id': item['id'],
            'contract_id': SECOND, 'confirmed': True, 'source_date': item['date'],
            'confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'basis': 'manual', 'candidate_contract_ids': [SECOND],
        }}})
    unresolved, = evidence(data)['unmatched_works']
    assert unresolved['id'] == item['id'] and unresolved['link_basis'] == 'manual_review'
    assert not unresolved['contract_id'] and unresolved['manual_contract_id'] == SECOND
    assert unresolved['selectable_contract_ids'] == [FIRST]
    assert links._read(PROJECT)['links'][item['id']]['confirmed']


def test_contract_aliases_do_not_invoke_recursive_acronym_inference(monkeypatch):
    import developaid_monitor_crew as crew
    monkeypatch.setattr(crew, 'is_acronym', lambda *_: pytest.fail('An acronym is not party proof'))
    source = ' '.join(['Повтор'] * 20)
    data = own_register('ООО «' + source + ' Дополнение»')
    choices, basis = links._party_rows(source, data['rows'])
    assert [row['id'] for row in choices] == [FIRST] and basis == 'short_name'
