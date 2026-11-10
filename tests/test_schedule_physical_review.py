"""Grouping does not approve scope or silently count repeated cumulative values."""
import copy

import pytest

import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
import developaid_cumulative_progress as progress
from test_schedule_physical import item, snapshot, CUT
from test_schedule_gpr_physical import site, PROJECT, save  # noqa: F401
import developaid_schedule_gpr_physical as physical


TASKS = [{'task_id': '1', 'name': 'Монтаж', 'object': 'Корпус 1'},
         {'task_id': '2', 'name': 'Монтаж', 'object': 'Корпус 11'},
         {'task_id': '3', 'name': 'Строительство сетей', 'object': 'Корпус 1'}]
EMPTY = {'tasks': [], 'components': [], 'note': ''}


def source_snapshot(rows=None):
    result = snapshot(rows)
    for ledger in result['ledgers']:
        ledger['customer'] = 'Учебный заказчик'
        for row in ledger['items']:
            row.setdefault('position', '1')
    return result


def model(rows=None, tasks=TASKS, config=EMPTY, rules=()):
    source = source_snapshot(rows)
    return review.build(quantities._items(source), tasks, config, CUT, rules,
                        snapshot=source, views=progress.quantity_views(source, CUT))


def test_annual_group_counts_full_plan_once_and_proposes_only_matching_corpus():
    group = model([(2025, item(2025, 10)), (2026, item())])['groups'][0]
    assert group['item_ids'] == ['0:0', '1:0']
    assert group['plan_quantity'] == 100 and group['completed_quantity'] == 60
    assert group['suggested_task_id'] == '1' and group['status'] == 'proposed'
    assert not any(c['task_id'] in {'2', '3'} for c in group['candidates'])
    assert EMPTY == {'tasks': [], 'components': [], 'note': ''}


@pytest.mark.parametrize('change', [dict(scope='Корпус 11'), dict(name='Монтаж 16 этажа')])
def test_different_units_places_and_work_names_stay_separate(change):
    assert model([(2025, item(2025, 10)), (2026, item(**change))])['group_count'] == 2


@pytest.mark.parametrize('change,reason', [
    ({'plan_quantity': 110}, 'план'), ({'unit': 'т'}, 'единицы'),
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
    rows = progress.quantity_views(source_snapshot(), CUT)
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
    assert group['status'] == 'review' and not group['can_bind']
    assert current['configuration'] == EMPTY
    assert not current['model']['physical_evidence']
    assert not current['model']['tasks'][0]['scope_confirmed']


@pytest.mark.parametrize('change', [dict(periods=[]), dict(completed_quantity=51)])
def test_known_statement_quantities_remain_reviewable_without_inventing_execution_dates(change):
    group = model([(2026, item(**change))])['groups'][0]
    assert group['can_bind'] and group['completed_quantity'] == change.get('completed_quantity', 50)
    assert group['progress_basis'] == 'По ведомости'
    assert group['rows'][0]['reported_completion_ratio'] == group['progress']
    assert group['quantity_reason']


@pytest.mark.parametrize('field,left,right', [
    ('system_scope', 'Отопление', 'Холодоснабжение'),
    ('object_scope', 'Главный дом', 'Склад'),
    ('site_scope', 'Внутренние сети', 'Наружные сети'),
    ('section_path', [{'position': '1', 'name': 'Отопление'}], [{'position': '1', 'name': 'Холодоснабжение'}]),
])
def test_independent_source_work_never_becomes_a_completed_cross_year_component(field, left, right):
    a, b = item(2025, 50), item(2026, 50)
    a[field], b[field] = left, right
    source = source_snapshot([(2025, a), (2026, b)])
    for ledger in source['ledgers']:
        ledger['items'][0].update(planned_work_amount=1000, planned_cost_split=True,
                                  planned_work_amount_basis='without_vat')
    groups = review.build(quantities._items(source), TASKS, EMPTY, CUT, snapshot=source,
                          views=progress.quantity_views(source, CUT))['groups']
    assert len(groups) == 2 and all(g['can_bind'] and g['progress'] == .5 for g in groups)
    config = {'tasks': [{'task_id': '1', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}],
              'components': [{'component_id': g['component_id'], 'task_id': '1', 'item_ids': g['item_ids']}
                             for g in groups], 'note': 'Проверены две самостоятельные системы.'}
    evaluated = physical.evaluate({'tasks': {'1': TASKS[0]}}, source, config, CUT)['tasks'][0]
    assert evaluated['progress'] == pytest.approx(.5)
    assert not evaluated.get('actual_finish') and not evaluated['known']


def test_different_customers_are_distinct_source_work_even_with_the_same_short_name_and_plan():
    source = source_snapshot([(2025, item(2025, 50)), (2026, item())])
    source['ledgers'][1]['customer'] = 'Другой учебный заказчик'
    groups = review.build(quantities._items(source), TASKS, EMPTY, CUT, snapshot=source,
                          views=progress.quantity_views(source, CUT))['groups']
    assert len(groups) == 2 and all(g['progress'] == .5 for g in groups)


def test_changed_annual_plan_is_unknown_and_keeps_each_source_percentage():
    groups = model([(2025, item(2025, 50)), (2026, item(plan_quantity=200))])['groups']
    assert len(groups) == 1
    group = groups[0]
    assert not group['can_bind'] and group['progress'] is None
    assert [r['completion_ratio'] for r in group['rows']] == [.5, .25]


def test_unknown_cross_year_identity_is_not_guessed_from_names_and_equal_plans():
    source = snapshot([(2025, item(2025, 50)), (2026, item())])
    groups = review.build(quantities._items(source), TASKS, EMPTY, CUT, snapshot=source,
                          views=progress.quantity_views(source, CUT))['groups']
    assert len(groups) == 2 and all(not g['can_bind'] for g in groups)
    assert all(g['rows'][0]['completion_ratio'] == .5 for g in groups)


def test_structural_headers_and_proven_copies_use_full_canonical_membership_before_grouping():
    from test_gpr_proven_duplicate_membership import sources
    _, source = sources()
    child = source['ledgers'][0]['items'][0]
    source['ledgers'][0]['items'].append(dict(child, name='Раздел ведомости', is_group=True,
        group_basis='zero_cost_structured_heading', planned_amount=0, completed_amount=0,
        completed_quantity=0, source=dict(child['source'], row=7)))
    views = progress.quantity_views(source, CUT)
    eligible = {id(row) for row in review.ledgers.aggregation_members(list(views.values()))}
    result = review.build(quantities._items(source), TASKS, EMPTY, CUT, snapshot=source, views=views)
    assert result['excluded_group_rows'] > 0 and result['excluded_duplicate_rows'] == 2
    included = {key for g in result['groups'] for key in g['item_ids']}
    assert included == {key for key, row in views.items() if id(row) in eligible}
    assert all(not views[key]['is_group'] and not views[key]['is_duplicate'] for key in included)


def test_forged_copy_flag_remains_visible_and_cannot_be_batch_bound():
    source = source_snapshot()
    source['ledgers'][0]['items'][0]['is_duplicate'] = True
    result = review.build(quantities._items(source), TASKS, EMPTY, CUT, snapshot=source,
                          views=progress.quantity_views(source, CUT))
    assert result['eligible_row_count'] == 1 and result['excluded_duplicate_rows'] == 0
    group = result['groups'][0]
    assert not group['can_bind'] and group['progress'] is None and group['quantity_reason']


def test_conflicting_preceding_context_does_not_prove_annual_continuity_or_independence():
    a, b = item(2025, 50), item(2026, 50)
    a['context_headings'], b['context_headings'] = [{'name': 'Отопление'}], [{'name': 'Холодоснабжение'}]
    group = model([(2025, a), (2026, b)])['groups'][0]
    assert not group['can_bind'] and group['progress'] is None
    assert 'заголовки' in group['quantity_reason']
    assert [row['completion_ratio'] for row in group['rows']] == [.5, .5]
    # Equal proved ancestry owns the identity; arbitrary preceding context
    # cannot defeat that proof or become a second independent denominator.
    a['section_path'] = b['section_path'] = [{'position': '1', 'name': 'Система отопления'}]
    group = model([(2025, a), (2026, b)])['groups'][0]
    assert group['can_bind'] and group['progress'] == 1


def test_a_manual_checkbox_cannot_reintroduce_the_old_false_completed_component():
    source = source_snapshot([(2025, item(2025, 50, system_scope='Отопление')),
                              (2026, item(system_scope='Холодоснабжение'))])
    config = {'tasks': [{'task_id': '1', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}],
              'components': [{'component_id': 'Проверенный состав', 'task_id': '1', 'item_ids': ['0:0', '1:0']}],
              'note': 'Подтверждение задачи не изменяет исходную идентичность.'}
    evaluated = physical.evaluate({'tasks': {'1': TASKS[0]}}, source, config, CUT)['tasks'][0]
    assert evaluated['progress'] is None and not evaluated['known'] and not evaluated.get('actual_finish')
    assert 'идентичность' in evaluated['reason']


def test_partial_operation_is_only_a_soft_candidate_and_never_preselected():
    group = model([(2026, item(name='Монтаж радиаторов'))],
                  tasks=[{'task_id': 'whole', 'name': 'Монтаж радиаторов и трубопроводов', 'object': 'Корпус 1'}])['groups'][0]
    assert group['candidates'][0]['task_id'] == 'whole'
    assert not group['candidates'][0]['strong'] and not group['suggested_task_id']
    assert group['status'] == 'review'


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
