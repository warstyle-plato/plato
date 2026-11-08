"""Annual execution is additive; planned scope and source copies are not."""
from __future__ import annotations

import copy

import pytest

from developaid_monitor_statement_union import statement_union


def source(year=2026, name='A.xlsx', *, done=200, plan=1000, position='1', scope='Корпус 1',
           unit='м2', quantity_plan=100, quantity=None, **changes):
    ref = {'source': {'filename': name, 'sheet': 'Работы'}, 'period_year': year,
           'source_date': '2026-11-06', 'future_periods_excluded': False,
           'monetary_comparable': True, 'planned_amount_basis': 'unspecified',
           'completed_amount_basis': 'unspecified', 'amount_scope': 'statement',
           'source_complete': True, 'planned': plan, 'completed': done,
           'completion_ratio': done/plan if plan else None}
    item = {'source': {'filename': name, 'sheet': 'Работы', 'row': 10},
            'period_year': year, 'position': position, 'name': 'Монтаж', 'scope': scope,
            'unit': unit, 'plan_quantity': quantity_plan, 'planned_amount': plan,
            'snapshot_date': '2026-11-06', 'future_periods_excluded': False,
            'completed_amount': None, 'reported_completed_amount': done,
            'reported_completed_quantity': done/10 if quantity is None else quantity,
            'reported_material_quantity': None, 'completed_quantity': None,
            'material_quantity': None, 'is_group': False, 'parent_row': None}
    item.update(changes)
    return ref, item


def row(*sources):
    refs, items = zip(*(sources or [source()]))
    return {'source_date': '2026-11-06', 'reported_performance_sources': copy.deepcopy(list(refs)),
            'physical_items': copy.deepcopy(list(items))}


def union(value):
    before = copy.deepcopy(value)
    result = statement_union(value)
    assert value == before
    return result


def test_one_source_agrees_with_canonical_statement_percentage():
    value = row()
    result = union(value)
    assert result['ratio'] == value['reported_performance_sources'][0]['completion_ratio']
    assert result['planned'] == 1000 and result['completed'] == 200 and result['remaining'] == 800
    assert result['basis'] == 'statement_union' and result['state'] == 'known'


def test_disjoint_years_add_execution_once_and_use_one_work_plan():
    result = union(row(source(2025, 'Old.xlsx', done=200), source(2026, 'New.xlsx', done=300)))
    assert result['planned'] == 1000 and result['completed'] == 500 and result['ratio'] == .5
    assert result['source_years'] == [2025, 2026] and result['source_count'] == 2
    assert result['position_count'] == 1 and result['annual_position_count'] == 2
    assert len(result['coverage']) == 2 and result['duplicate_count'] == 0


def test_no_zero_is_invented_for_a_work_missing_in_another_year():
    result = union(row(source(2025, 'Old.xlsx', done=200),
                       source(2026, 'New.xlsx', done=50, plan=500, position='2')))
    assert result['planned'] == 1500 and result['completed'] == 250
    assert result['annual_position_count'] == 2  # Not a fabricated 2x2 year/work grid.
    assert len(result['coverage']) == 2


def test_identical_copies_of_the_same_year_do_not_multiply_execution_or_plan():
    result = union(row(source(name='A.xlsx'), source(name='Copy.xlsx', unit='м²')))
    assert result['ratio'] == .2 and result['completed'] == 200 and result['planned'] == 1000
    assert result['source_count'] == 2 and result['annual_position_count'] == 1
    assert result['duplicate_count'] == 1


@pytest.mark.parametrize('change,code', [
    ({'done': 201}, 'annual_evidence_conflict'),
    ({'quantity': 30}, 'annual_evidence_conflict'),
    ({'plan': 2000}, 'plan_changed'),
    ({'quantity_plan': 200}, 'plan_changed'),
])
def test_repeated_year_requires_identical_evidence_and_work_definition(change, code):
    result = union(row(source(name='A.xlsx'), source(name='Other.xlsx', **change)))
    assert result['ratio'] is None and result['problems'][0]['code'] == code


def test_plans_cannot_change_just_because_source_year_changed():
    result = union(row(source(2025, 'Old.xlsx'), source(2026, 'New.xlsx', plan=2000)))
    assert result['ratio'] is None and result['problems'][0]['code'] == 'plan_changed'


def test_group_costs_are_not_counted_twice_and_zero_cost_leaf_is_retained():
    reference, parent = source(done=500)
    parent.update(is_group=True, source={'filename': 'A.xlsx', 'sheet': 'Работы', 'row': 9})
    children = []
    for index, (plan, done) in enumerate([(300, 100), (700, 400), (0, 0)], 1):
        _, child = source(plan=plan, done=done, position=f'1.{index}', name='A.xlsx')
        child.update(parent_row=9, source={'filename': 'A.xlsx', 'sheet': 'Работы', 'row': 9+index})
        children.append(child)
    value = row((reference, parent))
    value['physical_items'].extend(children)
    result = union(value)
    assert result['planned'] == 1000 and result['completed'] == 500 and result['ratio'] == .5
    assert result['position_count'] == 3  # The genuinely free third leaf is present.


def test_a_group_marker_without_child_evidence_cannot_discard_a_position():
    result = union(row(source(is_group=True)))
    assert result['ratio'] is None and result['problems'][0]['code'] == 'unproven_group'


@pytest.mark.parametrize('changes,code', [
    ({'planned_amount': None}, 'planned_amount_unknown'),
    ({'planned_amount': -1}, 'planned_amount_unknown'),
    ({'plan_quantity': None}, 'quantity_plan_unknown'),
    ({'plan_quantity': 0}, 'quantity_plan_unknown'),
    ({'reported_completed_amount': None}, 'completed_amount_unknown'),
    ({'future_periods_excluded': True}, 'future_or_unverified_periods'),
    ({'future_periods_excluded': None}, 'future_or_unverified_periods'),
    ({'period_year': None}, 'position_source_unverified'),
])
def test_a_partial_position_cannot_be_silently_dropped_or_zeroed(changes, code):
    result = union(row(source(**changes)))
    assert result['ratio'] is None and result['problems'][0]['code'] == code


def test_future_year_is_not_an_annual_fact_even_without_explicit_period_dates():
    result = union(row(source(2027)))
    assert result['ratio'] is None and result['problems'][0]['code'] == 'future_year'


def test_an_explicit_earlier_cut_cannot_gain_the_later_annual_total():
    result = union(row(source(quantity_cut='2025-12-31')))
    assert result['ratio'] is None and result['problems'][0]['code'] == 'future_year'


@pytest.mark.parametrize('change,code', [
    ({'source_complete': False}, 'partial_source'),
    ({'unread_rows_count': 1}, 'partial_source'),
    ({'planned_amount_basis': None}, 'tax_basis_unverified'),
    ({'planned_amount_basis': 'with_vat', 'completed_amount_basis': 'without_vat'}, 'tax_basis_mismatch'),
    ({'monetary_comparable': False}, 'tax_basis_unverified'),
])
def test_source_qualification_is_required_even_when_a_numeric_ratio_exists(change, code):
    value = row()
    value['reported_performance_sources'][0].update(change)
    result = union(value)
    assert result['ratio'] is None and result['problems'][0]['code'] == code


def test_tax_basis_must_be_stable_across_source_years_without_implicit_conversion():
    value = row(source(2025, 'Old.xlsx'), source(2026, 'New.xlsx'))
    value['reported_performance_sources'][1].update(planned_amount_basis='with_vat', completed_amount_basis='with_vat')
    result = union(value)
    assert result['ratio'] is None and result['problems'][0]['code'] == 'tax_basis_changed'


def test_no_qualified_source_can_disappear_from_the_union_without_its_positions():
    value = row(source(name='A.xlsx'), source(name='B.xlsx'))
    value['physical_items'].pop()
    result = union(value)
    assert result['ratio'] is None and result['problems'][0]['code'] == 'source_positions_missing'


def test_same_name_at_another_section_is_a_separate_work_not_a_duplicate():
    a, b = source(name='A.xlsx'), source(name='B.xlsx')
    a[1]['section_path'] = ['Корпус 1', 'Помещение 1']
    b[1]['section_path'] = ['Корпус 1', 'Помещение 2']
    result = union(row(a, b))
    assert result['planned'] == 2000 and result['completed'] == 400
    assert result['position_count'] == 2 and result['duplicate_count'] == 0


def test_hierarchy_source_row_changes_do_not_rekey_the_same_annual_work():
    previous, current = source(2025, 'Old.xlsx'), source(2026, 'New.xlsx', done=300)
    previous[1]['section_path'] = [{'position': '1', 'name': 'Монтаж сетей',
                                   'source': {'row': 9, 'cell': 'C9'}}]
    current[1]['section_path'] = [{'position': '1', 'name': 'Монтаж сетей',
                                  'source': {'row': 19, 'cell': 'C19'}}]
    result = union(row(previous, current))
    assert result['planned'] == 1000 and result['completed'] == 500
    assert result['position_count'] == 1


def test_room_context_is_not_lost_when_a_structural_section_path_also_exists():
    a, b = source(name='A.xlsx'), source(name='B.xlsx')
    for _, item in (a, b):
        item['section_path'] = [{'position': '1', 'name': 'Устройство полов'}]
    a[1]['context_headings'] = [{'position': '', 'name': 'Помещение 101'}]
    b[1]['context_headings'] = [{'position': '', 'name': 'Помещение 102'}]
    result = union(row(a, b))
    assert result['planned'] == 2000 and result['position_count'] == 2


@pytest.mark.parametrize('done', [0, -100, 1200])
def test_explicit_zero_corrections_and_overruns_stay_numbers_without_clamping(done):
    result = union(row(source(done=done)))
    assert result['ratio'] == done/1000 and result['completed'] == done
    assert result['requires_reconciliation'] is (done < 0 or done > 1000)


def test_scope_and_basis_signature_do_not_reset_when_year_coverage_is_extended():
    previous = union(row(source(2025, 'Old.xlsx')))
    current = union(row(source(2025, 'Old.xlsx'), source(2026, 'New.xlsx', done=300)))
    assert previous['scope_fingerprint'] == current['scope_fingerprint']
    assert previous['basis_signature'] == current['basis_signature']
    assert set(map(tuple, previous['coverage'])) < set(map(tuple, current['coverage']))
