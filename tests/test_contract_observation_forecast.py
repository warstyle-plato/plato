"""Snapshot cost forecasts keep scope, source dates and contractual risks apart."""
from __future__ import annotations

import copy

import pytest

from developaid_monitor_contract_history import observation_forecast


def point(day, ratio, **changes):
    value = {'observation_date': day, 'snapshot_id': day+'-'+'a'*64,
             'ratio': ratio, 'state': 'known', 'date_basis': 'snapshot',
             'origin': 'cumulative_statement', 'basis': 'statement_union',
             'scope_fingerprint': 'scope', 'basis_fingerprint': 'basis',
             'coverage': [('work', 2026)], 'requires_reconciliation': False}
    value.update(changes)
    return value


def row(points=None):
    points = points if points is not None else [point('2026-11-01', .2), point('2026-11-11', .4)]
    current = points[-1] if points else point('2026-11-11', .4)
    return {'deadline': '2026-12-01', 'risk': {'status': 'unknown', 'forecast_finish': None,
            'reason': 'Датированных периодов недостаточно.'},
            'progress': dict(copy.deepcopy(current), planned=1000, remaining=600,
                             series=copy.deepcopy(points))}


def forecast(value=None, cut='2026-11-11'):
    value = value or row()
    before = copy.deepcopy(value)
    result = observation_forecast(value, cut)
    assert value == before
    return result


def test_two_qualified_snapshots_produce_only_an_indicative_source_cost_forecast():
    result = forecast()
    assert result['eligible'] and result['state'] == 'estimated'
    assert result['forecast_finish'] == '2026-12-11'
    assert result['pace_per_day'] == pytest.approx(20)
    assert result['pace_percent_points_per_day'] == pytest.approx(2)
    assert result['remaining'] == pytest.approx(600)
    assert result['pace_window'] == ['2026-11-01', '2026-11-11']
    assert result['scope'] == 'uploaded_statements' and result['indicative'] is True
    assert result['metric'] == 'statement_monetary_progress' and result['date_basis'] == 'snapshot'
    assert result['delay_days'] == 10 and result['deadline_relation'] == 'after'


def test_multiple_qualified_observations_use_the_complete_selected_interval():
    result = forecast(row([point('2026-10-20', .1), point('2026-11-01', .2), point('2026-11-11', .4)]))
    assert result['forecast_finish'] == '2026-12-25'  # .3/22 per day, .6 still covered => 44 days.
    assert result['point_count'] == 3 and result['pace_window'][0] == '2026-10-20'


def test_dated_contract_forecast_and_contractual_risk_are_never_replaced():
    value = row()
    value['risk'].update(status='late', forecast_finish='2026-12-03', delay_days=2)
    result = forecast(value)
    assert result['state'] == 'dated_forecast_available' and result['forecast_finish'] is None
    assert value['risk']['forecast_finish'] == '2026-12-03'


@pytest.mark.parametrize('points,state', [
    ([point('2026-11-11', .4)], 'single_snapshot'),
    ([point('2026-11-01', .4), point('2026-11-11', .3)], 'correction'),
    ([point('2026-10-20', .4), point('2026-11-01', .3), point('2026-11-11', .5)], 'correction'),
    ([point('2026-10-20', .1), point('2026-11-01', .4), point('2026-11-11', .4)], 'no_recent_growth'),
    ([point('2026-11-01', 0), point('2026-11-11', 0)], 'no_recent_growth'),
    ([point('2026-11-01', .2), point('2026-11-06', None, state='history_unavailable'), point('2026-11-11', .4)], 'comparison_gap'),
    ([point('2026-11-01', .2), point('2026-11-06', .3, basis_fingerprint='other'), point('2026-11-11', .4)], 'basis_changed'),
    ([point('2026-11-01', .2), point('2026-11-06', .3, coverage=[('work', 2025)]), point('2026-11-11', .4)], 'coverage_changed'),
    ([point('2026-11-01', .2), point('2026-11-06', .3, requires_reconciliation=True), point('2026-11-11', .4)], 'requires_reconciliation'),
])
def test_no_forecast_crosses_a_correction_or_unqualified_intermediate_snapshot(points, state):
    result = forecast(row(points))
    assert not result['eligible'] and result['forecast_finish'] is None
    assert result['state'] == state


def test_a_new_qualified_interval_can_start_after_an_old_break_without_crossing_it():
    value = row([point('2026-10-20', .1), point('2026-11-01', None, state='ambiguous_contract'),
                 point('2026-11-06', .3), point('2026-11-11', .4)])
    result = forecast(value)
    assert result['eligible'] and result['pace_window'] == ['2026-11-06', '2026-11-11']
    assert result['window_reset_reason'] == 'comparison_gap' and result['point_count'] == 2


def test_coverage_extension_cannot_supply_a_fake_pace_from_newly_added_old_years():
    old = point('2026-11-01', .2, coverage=[('work', 2025)])
    current = point('2026-11-11', .4, coverage=[('work', 2025), ('work', 2026)])
    result = forecast(row([old, current]))
    assert result['state'] == 'coverage_changed' and not result['eligible']


@pytest.mark.parametrize('cut,eligible,state', [('2026-12-26', True, 'estimated'),
                                              ('2026-12-27', False, 'stale'),
                                              ('2026-11-10', False, 'future_source')])
def test_freshness_and_calculation_dates_are_separate_from_observation_dates(cut, eligible, state):
    result = forecast(cut=cut)
    assert result['eligible'] is eligible and result['state'] == state
    assert result['source_observation_date'] == '2026-11-11'
    if eligible:
        assert result['forecast_finish'] == '2027-01-25'  # Conservatively measured from the calculation cut.


def test_points_older_than_the_ninety_day_window_do_not_supply_a_current_pace():
    result = forecast(row([point('2026-08-12', .2), point('2026-11-11', .4)]))
    assert result['state'] == 'single_snapshot' and not result['eligible']


@pytest.mark.parametrize('change,state', [
    ({'ratio': 1}, 'source_scope_complete'),
    ({'ratio': 1.2}, 'requires_reconciliation'),
    ({'requires_reconciliation': True}, 'requires_reconciliation'),
    ({'ratio': None}, 'current_unknown'),
    ({'basis': 'contract_amount', 'origin': 'dated_cumulative'}, 'not_statement_observation'),
    ({'coverage': None}, 'coverage_unverified'),
    ({'planned': None}, 'basis_unverified'),
    ({'snapshot_id': 'another-source'}, 'current_binding_changed'),
])
def test_incomplete_or_already_complete_current_inputs_do_not_create_a_finish_date(change, state):
    value = row()
    value['progress'].update(change)
    result = forecast(value)
    assert result['state'] == state and result['forecast_finish'] is None


def test_ambiguous_dates_repeated_source_and_future_observation_are_rejected():
    value = row([point('2026-11-11', .2), point('2026-11-11', .4)])
    assert forecast(value)['state'] == 'ambiguous_dates'
    value = row()
    value['progress']['series'][0]['snapshot_id'] = value['progress']['snapshot_id']
    assert forecast(value)['state'] == 'ambiguous_snapshots'
    value = row()
    value['progress']['series'].insert(1, point('2026-11-12', .3))
    assert forecast(value)['state'] == 'future_source'


def test_future_source_year_and_unknown_reconciliation_qualification_are_not_extrapolated():
    value = row()
    for data in [value['progress'], *value['progress']['series']]:
        data['coverage'] = [('work', 2027)]
    assert forecast(value)['state'] == 'future_year'
    value = row()
    value['progress']['series'][0].pop('requires_reconciliation')
    assert forecast(value)['state'] == 'requires_reconciliation'


def test_missing_deadline_preserves_a_source_scope_estimate_without_an_invented_delay():
    value = row()
    value['deadline'] = None
    result = forecast(value)
    assert result['eligible'] and result['forecast_finish'] == '2026-12-11'
    assert result['delay_days'] is None and result['deadline_relation'] is None


def test_century_projection_is_not_shown_even_if_the_tiny_positive_pace_is_known():
    result = forecast(row([point('2026-11-01', .2), point('2026-11-11', .200001)]))
    assert result['state'] == 'pace_too_low' and not result['eligible']
    assert result['forecast_finish'] is None and result['pace_per_day'] > 0


def test_a_subnormal_positive_change_does_not_overflow_the_horizon_guard():
    result = forecast(row([point('2026-11-01', 0), point('2026-11-11', 1e-320)]))
    assert result['state'] == 'pace_too_low' and result['forecast_finish'] is None


def test_a_calendar_overflow_is_unknown_instead_of_a_broken_contract_view():
    result = forecast(row([point('9999-12-10', .2), point('9999-12-20', .4)]), cut='9999-12-20')
    assert result['state'] == 'forecast_date_out_of_range' and result['forecast_finish'] is None


def test_enrich_attaches_the_estimate_without_changing_the_dated_risk_or_source(monkeypatch):
    from test_contract_progress_history import calculate, register
    from test_statement_union import source
    from test_statement_union_history import contract
    previous = contract(source(done=200), day='2026-11-01')
    current = contract(source(done=400), day='2026-11-11')
    current['risk'] = {'status': 'overdue', 'forecast_finish': None, 'reason': 'Договорный срок прошёл.'}
    result, _ = calculate(monkeypatch, register('2026-11-11', [current]),
        {'2026-11-01': register('2026-11-01', [previous], 'b')}, cut='2026-11-11')
    record = result['rows'][0]
    assert record['observation_forecast']['eligible']
    assert record['observation_forecast']['forecast_finish'] == '2026-12-11'
    assert record['risk'] == current['risk']
