"""One canonical union drives display and snapshot dynamics across annual books."""
from __future__ import annotations

import copy

import pytest

import developaid_monitor_contract_history as history
from developaid_monitor_statement_union import statement_union
from test_contract_progress_history import calculate, register
from test_statement_union import row as source_row, source


def contract(*sources, day='2026-11-06'):
    result = source_row(*sources)
    result.update(id='current-contract-id', customer='ООО Заказчик', contractor='НУР ООО',
                  contract='A-12', contract_date='2025-01-01', source_date=day,
                  amount=None, completed=None, completion_ratio=None, monetary_comparable=True)
    result['statement_progress'] = statement_union(result)
    return result


def test_annual_union_is_the_exact_value_used_for_current_progress(monkeypatch):
    value = contract(source(2025, 'Old.xlsx', done=200), source(2026, 'New.xlsx', done=300))
    result, _ = calculate(monkeypatch, register(rows=[value]))
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == value['statement_progress']['ratio'] == .5
    assert progress['basis'] == 'statement_union' and progress['planned'] == 1000
    assert progress['source_years'] == [2025, 2026] and progress['source_count'] == 2


def test_union_preference_does_not_override_confirmed_contract_percentage(monkeypatch):
    value = contract(source())
    value.update(amount=2000, completed=400, completion_ratio=.2,
                 amount_basis='unspecified', completed_basis='unspecified')
    result, _ = calculate(monkeypatch, register(rows=[value]))
    assert result['rows'][0]['progress']['basis'] == 'contract_amount'
    assert result['rows'][0]['progress']['ratio'] == .2


def test_extending_year_coverage_compares_known_annual_sum_without_multiplying_the_plan(monkeypatch):
    prior = contract(source(2025, 'Old.xlsx', done=200), day='2026-10-06')
    current = contract(source(2025, 'Old.xlsx', done=200), source(2026, 'New.xlsx', done=300))
    result, _ = calculate(monkeypatch, register(rows=[current]),
                          {'2026-10-06': register('2026-10-06', [prior], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == .5 and progress['previous_ratio'] == .2
    assert progress['delta_percent_points'] == pytest.approx(30)
    assert progress['coverage_change'] == 'extended'
    assert progress['comparison_state'] == 'comparable'


def test_replacing_last_year_with_this_year_is_not_a_false_negative_delta(monkeypatch):
    prior = contract(source(2025, 'Old.xlsx', done=900), day='2025-11-06')
    current = contract(source(2026, 'New.xlsx', done=100))
    result, _ = calculate(monkeypatch, register(rows=[current]),
                          {'2025-11-06': register('2025-11-06', [prior], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == .1 and progress['series'][0]['ratio'] == .9
    assert progress['delta_percent_points'] is None
    assert progress['comparison_state'] == 'coverage_changed'


def test_losing_one_work_year_is_not_hidden_by_an_unchanged_global_year_set(monkeypatch):
    a_old = source(2025, 'A-old.xlsx', done=100, position='1')
    a_new = source(2026, 'A-new.xlsx', done=100, position='1')
    b_old = source(2025, 'B-old.xlsx', done=100, position='2')
    b_new = source(2026, 'B-new.xlsx', done=100, position='2')
    prior = contract(a_old, a_new, b_old, b_new, day='2026-10-06')
    current = contract(a_new, b_old, b_new)
    result, _ = calculate(monkeypatch, register(rows=[current]),
                          {'2026-10-06': register('2026-10-06', [prior], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['source_years'] == progress['series'][0]['source_years'] == [2025, 2026]
    assert progress['delta_percent_points'] is None
    assert progress['comparison_state'] == 'coverage_changed'


def test_a_changed_plan_blocks_year_expansion_even_if_both_percentages_exist(monkeypatch):
    prior = contract(source(2025, 'Old.xlsx', done=200), day='2026-10-06')
    current = contract(source(2025, 'Old.xlsx', done=200, plan=2000),
                       source(2026, 'New.xlsx', done=300, plan=2000))
    result, _ = calculate(monkeypatch, register(rows=[current]),
                          {'2026-10-06': register('2026-10-06', [prior], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == .25 and progress['previous_ratio'] is None
    assert progress['delta_percent_points'] is None and progress['comparison_state'] == 'scope_changed'


def test_explicit_unqualified_union_cannot_fall_back_to_one_good_source_while_ignoring_another(monkeypatch):
    value = contract(source(2025, 'Old.xlsx'), source(2026, 'New.xlsx'))
    value['physical_items'][1]['reported_completed_amount'] = None
    value['statement_progress'] = statement_union(value)
    assert value['reported_performance_sources'][0]['completion_ratio'] == .2
    result, _ = calculate(monkeypatch, register(rows=[value]))
    assert result['rows'][0]['progress']['ratio'] is None
    assert result['rows'][0]['progress']['state'] == 'incomparable'


def test_old_per_reference_fallback_does_not_silently_ignore_unqualified_sources(monkeypatch):
    from test_contract_progress_history import row
    value = row()
    other = copy.deepcopy(value['reported_performance_sources'][0])
    other.update(completion_ratio=None, monetary_comparable=False)
    value['reported_performance_sources'].append(other)
    result, _ = calculate(monkeypatch, register(rows=[value]))
    assert result['rows'][0]['progress']['ratio'] is None
    assert result['rows'][0]['progress']['state'] == 'partial_sources'


def test_source_binding_identity_is_used_without_manufacturing_a_contract_date(monkeypatch):
    import developaid_monitor_contracts as contracts
    value = contract(source())
    value['contract_date'] = None
    monkeypatch.setattr(contracts, '_source_identity', lambda row: ('source-bound', row['contract']), raising=False)
    assert history.contract_identity(value) == ('source-bound', 'A-12')
    assert value['contract_date'] is None
