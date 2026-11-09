"""Grouping does not approve scope or silently count repeated cumulative values."""
import copy

import pytest

import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
from test_schedule_physical import item, snapshot, CUT
from test_schedule_gpr_physical import site, PROJECT, save  # noqa: F401
import developaid_schedule_gpr_physical as physical


TASKS = [{'task_id': '1', 'name': 'Монтаж', 'object': 'Корпус 1'},
         {'task_id': '2', 'name': 'Монтаж', 'object': 'Корпус 11'},
         {'task_id': '3', 'name': 'Строительство сетей', 'object': 'Корпус 1'}]
EMPTY = {'tasks': [], 'components': [], 'note': ''}


def model(rows=None, tasks=TASKS, config=EMPTY, rules=()):
    items = quantities._items(snapshot(rows))
    return review.build(items, tasks, config, CUT, rules)


def test_annual_group_counts_full_plan_once_and_proposes_only_matching_corpus():
    group = model([(2025, item(2025, 10)), (2026, item())])['groups'][0]
    assert group['item_ids'] == ['0:0', '1:0']
    assert group['plan_quantity'] == 100 and group['completed_quantity'] == 60
    assert group['suggested_task_id'] == '1' and group['status'] == 'proposed'
    assert not any(c['task_id'] in {'2', '3'} for c in group['candidates'])
    assert EMPTY == {'tasks': [], 'components': [], 'note': ''}


@pytest.mark.parametrize('change', [dict(unit='т'), dict(scope='Корпус 11'), dict(name='Монтаж 16 этажа')])
def test_different_units_places_and_work_names_stay_separate(change):
    assert model([(2025, item(2025, 10)), (2026, item(**change))])['group_count'] == 2


@pytest.mark.parametrize('change,reason', [
    ({'plan_quantity': 110}, 'план'), ({'completed_quantity': 51}, 'Сумма'),
    ({'periods': []}, 'Сумма'),
])
def test_bad_plans_or_unreconciled_periods_cannot_be_bulk_bound(change, reason):
    group = model([(2025, item(2025, 10)), (2026, item(**change))])['groups'][0]
    assert not group['can_bind'] and group['status'] == 'review'
    assert reason.casefold() in ' '.join(group['issues']).casefold()


def test_duplicate_year_is_an_exception_not_two_quantities_to_sum():
    group = model([(2026, item()), (2026, item())])['groups'][0]
    assert not group['can_bind'] and group['completed_quantity'] is None
    assert 'год' in ' '.join(group['issues'])


def test_same_name_with_ambiguous_gpr_work_never_preselects():
    tasks = TASKS + [{'task_id': '4', 'name': 'Монтаж', 'object': 'Корпус 1'}]
    group = model(tasks=tasks)['groups'][0]
    assert group['status'] == 'review' and not group['suggested_task_id']


def test_floor_and_section_conflicts_are_excluded():
    tasks = [{'task_id': 'a', 'name': 'Монтаж 16 этажа', 'object': 'Корпус 1 секция 2'},
             {'task_id': 'b', 'name': 'Монтаж 15 этажа', 'object': 'Корпус 1 секция 3'}]
    group = model([(2026, item(name='Монтаж 15 этажа', scope='Корпус 1 секция 2'))], tasks=tasks)['groups'][0]
    assert not group['candidates'] and not group['suggested_task_id']


@pytest.mark.parametrize('left,right', [
    ('Этаж 15', 'Этаж 16'), ('15-го этажа', '16-го этажа'),
    ('секции 1', 'секции 2'), ('корпуса 1', 'корпуса 2'),
    ('этажи 1–3', 'этажи 1–4'), ('секции 1, 2', 'секции 1, 3'),
    ('в корпусах 1 и 2', 'в корпусах 3 и 4'),
    ('между секциями 1 и 2', 'между секциями 3 и 4'),
    ('по этажам 1–3', 'по этажам 4–6'),
])
def test_declensions_reverse_labels_and_ranges_cannot_propose_a_different_place(left, right):
    task = [{'task_id': 'wrong', 'name': 'Монтаж. '+right, 'object': 'Корпус 1'}]
    group = model([(2026, item(name='Монтаж. '+left))], tasks=task)['groups'][0]
    assert group['status'] != 'proposed' and not group['suggested_task_id']


def test_unrecognized_place_requires_manual_choice_instead_of_a_strong_proposal():
    group = model([(2026, item(name='Монтаж секции Б'))])['groups'][0]
    assert group['status'] == 'review' and not group['suggested_task_id']


def test_unknown_word_form_with_a_location_root_does_not_mean_no_location():
    group = model([(2026, item(name='Монтаж. Этажность неизвестна'))])['groups'][0]
    assert group['status'] == 'review' and not group['suggested_task_id']


@pytest.mark.parametrize('left,right', [('Этаж 15', '15-го этажа'), ('этажи 1-3', 'этажи 1–3'),
                                      ('Корпуса 3', 'корпус 3')])
def test_equivalent_place_spellings_remain_useful_proposals(left, right):
    task = [{'task_id': 'same', 'name': 'Монтаж. '+right, 'object': 'Корпус 1'}]
    group = model([(2026, item(name='Монтаж. '+left))], tasks=task)['groups'][0]
    assert group['status'] == 'proposed' and group['suggested_task_id'] == 'same'


def test_remembered_rules_ignore_row_indices_but_detect_changed_plan():
    rows = quantities._items(snapshot())
    config = {'tasks': [], 'components': [{'task_id': '3', 'item_ids': ['0:0']}]}
    remembered = review.rules(config, rows)
    group = review.build({'7:42': rows['0:0']}, TASKS, EMPTY, CUT, remembered)['groups'][0]
    assert group['suggested_task_id'] == '3' and group['item_ids'] == ['7:42']
    changed = copy.deepcopy(rows['0:0']);changed['plan_quantity'] = 101
    group = review.build({'7:42': changed}, TASKS, EMPTY, CUT, remembered)['groups'][0]
    assert group['status'] == 'review' and not group['suggested_task_id']
    assert any('изменились' in x for x in group['issues'])


def test_new_snapshot_remembers_a_saved_decision_but_requires_scope_approval_again(site):
    saved = save()
    assert saved['review']['groups'][0]['status'] == 'bound'
    site[1]['snapshot_id'] = CUT + '-' + 'e'*64
    current = physical.catalog(PROJECT, CUT)
    group = current['review']['groups'][0]
    assert group['suggested_task_id'] == '1' and group['status'] == 'proposed'
    assert current['configuration'] == EMPTY
    assert not current['model']['physical_evidence']
    assert not current['model']['tasks'][0]['scope_confirmed']


def test_groups_cover_all_1190_rows_even_when_raw_catalog_is_paginated(site):
    site[1]['ledgers'][0]['items'] = [item(name=f'Монтаж позиции {i}') for i in range(1190)]
    catalog = physical.catalog(PROJECT, CUT, query='позиции 1189')
    assert len(catalog['items']) == 1
    assert catalog['review']['row_count'] == 1190 and catalog['review']['group_count'] == 1190


def test_all_1190_distinct_groups_can_be_saved_without_approving_scope(site):
    site[1]['ledgers'][0]['items'] = [item(name=f'Монтаж позиции {i}') for i in range(1190)]
    state = physical.catalog(PROJECT, CUT)
    config = {'tasks': [{'task_id': '1', 'mode': 'quantities', 'scope_confirmed': False, 'actual_finish': ''}],
              'components': [{'task_id': '1', 'component_id': g['component_id'], 'item_ids': g['item_ids']}
                             for g in state['review']['groups']], 'note': 'Проверены привязки. Полнота ещё проверяется.'}
    saved = save(configuration=config)
    assert len(saved['configuration']['components']) == 1190
    assert not saved['model']['physical_evidence']
    assert physical.catalog(PROJECT, CUT)['revision'] == 1
