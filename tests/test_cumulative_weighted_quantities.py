"""Explicit SMR prices weight known natural fractions, never materials."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import developaid_cumulative_progress as progress
import developaid_schedule_gpr_physical as physical


def member(key='a', *, ratio=.5, weight=100, unit='м²', **changes):
    value = {'member_key': key, 'progress': ratio, 'unit': unit,
             'planned_work_amount': weight, 'planned_cost_split': True,
             'planned_work_amount_basis': 'with_vat', 'valuation_key': ('source.xlsx', 'КС', 2026)}
    value.update(changes)
    return value


def test_different_units_use_explicit_work_cost_weights_and_keep_all_members():
    values = [member('a', ratio=.5, weight=100, unit='м²'), member('b', ratio=.2, weight=300, unit='шт')]
    before = copy.deepcopy(values)
    result = progress.aggregate_quantities(values)
    assert result['ratio'] == pytest.approx(.275)
    assert result['basis'] == 'smr_cost_weighted_quantities' and result['complete_coverage']
    assert set(result['member_keys']) == {'a', 'b'} and not result['all_complete']
    assert values == before


def test_single_natural_component_needs_no_monetary_weight():
    result = progress.aggregate_quantities([member(weight=None, planned_cost_split=False)])
    assert result['ratio'] == .5 and result['basis'] == 'natural_quantity'


@pytest.mark.parametrize('changes', [
    {'planned_work_amount': None}, {'planned_work_amount': -1}, {'planned_cost_split': False},
    {'progress': None}, {'unit': ''}, {'planned_work_amount_basis': 'without_vat'},
])
def test_unknown_or_incompatible_member_prevents_an_aggregate(changes):
    result = progress.aggregate_quantities([member('a'), member('b', **changes)])
    assert result['ratio'] is None and not result['complete_coverage']


def test_proven_rollup_is_excluded_but_zero_cost_real_leaf_is_not():
    complete = member('a', ratio=1)
    incomplete_zero = member('b', ratio=0, weight=0)
    group = member('g', ratio=0, is_group=True)
    result = progress.aggregate_quantities([complete, incomplete_zero, group])
    assert result['ratio'] == 1 and result['requires_reconciliation'] and not result['all_complete']
    assert result['members'] == 2 and result['excluded_groups'] == 1
    assert set(result['member_keys']) == {'a', 'b'}


def test_unknown_quantity_zero_cost_leaf_still_prevents_full_coverage():
    result = progress.aggregate_quantities([member('a', ratio=1), member('b', ratio=None, weight=0)])
    assert result['ratio'] is None and not result['complete_coverage']


def test_material_values_do_not_change_the_weighted_natural_percentage():
    rows = [member('a'), member('b', ratio=.1)]
    before = progress.aggregate_quantities(rows)
    rows[0].update(material_quantity=1e12, completed_materials=1e15, completed_amount=1e18)
    assert progress.aggregate_quantities(rows) == before


def test_overrun_is_visible_and_row_order_does_not_change_weight_identity():
    rows = [member('a', ratio=1.25), member('b', ratio=1)]
    result = progress.aggregate_quantities(rows)
    assert result['ratio'] == 1.125 and result['requires_reconciliation'] and not result['all_complete']
    assert progress.aggregate_quantities(list(reversed(rows)))['weight_fingerprint'] == result['weight_fingerprint']


def test_unknown_tax_bases_from_distinct_valuations_are_not_assumed_equal():
    rows = [member('a', planned_work_amount_basis='unspecified'),
            member('b', planned_work_amount_basis='unspecified', valuation_key=('other.xlsx', 'КС', 2026))]
    assert progress.aggregate_quantities(rows)['ratio'] is None


def test_gpr_source_retains_unambiguous_parent_hierarchy_and_article_fields(monkeypatch, tmp_path):
    path = tmp_path/'gpr.xlsx'
    path.write_bytes(b'synthetic-source')
    parent = {'id': '10', 'wbs': '2.1', 'name': 'Кладка стен и перегородок', 'is_work': False}
    work = {'id': '11', 'wbs': '2.1.1', 'name': '1-ый этаж', 'section': 'Строительные работы',
            'object': 'Корпус 4', 'estimate_code': '2.3.4', 'estimate_name': 'Кладка',
            'start': dt.date(2026, 1, 1), 'finish': dt.date(2026, 2, 1)}
    monkeypatch.setattr(physical.monitor, '_baseline_file', lambda _: path)
    monkeypatch.setattr(physical.monitor, '_read_baseline_gpr_bytes', lambda _: {'rows': [parent, work], 'works': [work]})
    task = physical._source('Synthetic')['tasks']['11']
    assert task['section'] == 'Строительные работы' and task['estimate_code'] == '2.3.4'
    assert task['parent_path'] == [{'id': '10', 'wbs': '2.1', 'name': 'Кладка стен и перегородок'}]
    assert not task['hierarchy_ambiguous']
