"""A newer reading can supersede an older quantity without inventing act dates."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import developaid_cumulative_progress as progress
import developaid_report_schedule as report
import developaid_schedule_gpr_forecast as forecast
import developaid_schedule_gpr_physical as physical
import developaid_schedule_work_fact as work_fact
from test_gpr_cumulative_matching import CUT, snapshot, source, task

DAY = dt.date.fromisoformat


def quantities(day, basis):
    component = {'component_id': 'synthetic part', 'progress': .4, 'snapshot_date': CUT,
                 'progress_origin': 'cumulative_statement' if basis == 'snapshot' else 'cumulative_quantities'}
    component['observation_date' if basis == 'snapshot' else 'period_end'] = day
    return {'task_id': 'floor4', 'scope_confirmed': True, 'mode': 'quantities', 'progress': .4,
            'progress_origin': component['progress_origin'], 'progress_date': day, 'progress_date_basis': basis,
            'forecast_finish': None, 'components': [component], 'reason': 'Показание КС известно.'}


@pytest.mark.parametrize('basis', ['snapshot', 'execution_period'])
@pytest.mark.parametrize('ks_day,gpr_ratio,method', [('2026-11-04', 1., 'done'),
    ('2026-11-05', 1., 'source_conflict'), ('2026-11-06', 1., 'source_conflict'),
    ('2026-11-04', .8, 'cumulative'), (None, 1., 'cumulative')])
def test_direct_readings_use_both_dates_and_only_a_later_completed_gpr_changes_priority(basis, ks_day, gpr_ratio, method):
    ks = quantities(ks_day, basis)
    points = [(DAY('2026-11-05'), gpr_ratio, 'weekly_gpr')]
    before = copy.deepcopy((ks, points))
    result = forecast.work({}, points, DAY(CUT), ks)
    assert result['method'].startswith(method)
    if method == 'done':
        assert result['progress'] == 1 and result['progress_origin'] == 'weekly_gpr'
        assert result['progress_date'] == result['forecast_finish'] == '2026-11-05'
    else:
        assert result['progress'] == .4 and result['progress_date'] == ks_day
        assert result['forecast_finish'] is None
    side = work_fact.model([{'id': 'floor4', 'gpr_progress': gpr_ratio, 'gpr_progress_origin': 'weekly_gpr',
        'gpr_progress_date': '2026-11-05'}], {'tasks': [ks]})['works']['floor4']
    assert side['ks']['progress'] == .4 and side['ks']['date'] == ks_day
    assert side['gpr']['progress'] == gpr_ratio
    assert (ks, points) == before


def test_a_prior_completed_gpr_before_the_unfinished_ks_cannot_be_the_new_completion_date():
    ks = quantities('2026-11-04', 'snapshot')
    result = forecast.work({}, [(DAY('2026-10-01'), 1., 'approved_gpr'),
                               (DAY('2026-11-05'), 1., 'weekly_gpr')], DAY(CUT), ks)
    assert result['forecast_finish'] == result['progress_date'] == '2026-11-05'


def test_completed_dated_ks_keeps_its_own_completion_instead_of_a_later_gpr_observation():
    ks = quantities('2026-11-04', 'execution_period')
    ks.update(progress=1., forecast_finish='2026-11-04')
    ks['components'][0]['progress'] = 1.
    result = forecast.work({}, [(DAY('2026-11-05'), 1., 'weekly_gpr')], DAY(CUT), ks)
    assert result['method'] == 'cumulative_quantities' and result['forecast_finish'] == '2026-11-04'


def cohort(monkeypatch, *, gpr_days, unknown_weights=False, period_day=None):
    snap = snapshot(floor='3-4')
    snap.update(taken_at='2026-11-05', snapshot_id='2026-11-05-'+'b'*64)
    if period_day:
        snap['ledgers'][0]['items'][0]['periods'] = [{'quantity': 40,
            'date_start': '2026-10-01', 'date_end': period_day}]
    if unknown_weights:
        other = copy.deepcopy(snap['ledgers'][0]['items'][0])
        other.update(position='1.2', planned_work_amount=None)
        snap['ledgers'][0]['items'].append(other)
    plan = source(task('f3', floor=3), task('f4', floor=4))
    readings = {tid: [(DAY(day), 1., 'weekly_gpr')] for tid, day in zip(plan['tasks'], gpr_days)}
    monkeypatch.setattr(physical, '_history', lambda _: [])
    monkeypatch.setattr(forecast, 'history', lambda *_: readings)
    monkeypatch.setattr(progress, 'observation_index', lambda *_: ())
    before = copy.deepcopy((plan, snap, readings))
    state = physical._state('Synthetic', CUT, plan, snap)
    model = physical._view_model('Synthetic', CUT, plan, snap, state['configuration'], automatic=state['automatic_mapping'])
    assert (plan, snap, readings) == before
    return model, plan, readings


@pytest.mark.parametrize('unknown_weights', [False, True])
@pytest.mark.parametrize('gpr_days,conflict', [(('2026-11-04', '2026-11-04'), True),
    (('2026-11-05', '2026-11-05'), True), (('2026-11-06', '2026-11-06'), False),
    (('2026-11-04', '2026-11-06'), False)])
def test_a_shared_ks_needs_to_be_at_least_as_recent_as_every_joint_completed_gpr(monkeypatch, unknown_weights, gpr_days, conflict):
    model, plan, readings = cohort(monkeypatch, gpr_days=gpr_days, unknown_weights=unknown_weights)
    assert bool(model.get('source_conflicts')) is conflict
    assert model['source_cohorts'][0]['model']['progress'] == (None if unknown_weights else .4)
    for measured in model['tasks']:
        assert measured['progress'] is None
        result = forecast.work(plan['tasks'][measured['task_id']], readings[measured['task_id']], DAY(CUT), measured)
        assert result['progress'] == 1 and (result['forecast_finish'] is None) is conflict


@pytest.mark.parametrize('period_day,conflict', [('2026-11-04', False), ('2026-11-05', True)])
def test_a_cohort_execution_period_date_is_not_replaced_by_its_later_archive_date(monkeypatch, period_day, conflict):
    model, _, _ = cohort(monkeypatch, gpr_days=('2026-11-05', '2026-11-05'), period_day=period_day)
    assert bool(model.get('source_conflicts')) is conflict
    measured = model['source_cohorts'][0]['model']
    assert measured['progress_date'] == period_day and measured['progress_date_basis'] == 'execution_period'
    if conflict:
        assert model['source_conflicts'][0]['date'] == period_day
        assert model['source_conflicts'][0]['date_basis'] == 'execution_period'
    fact = report.model({'rnv': {'state': 'unknown'}, 'physical': model})['facts'][0]
    assert fact['date'] == period_day and fact['date_basis'] == 'execution_period'
    assert 'по датированным периодам на' in report.fact_text(fact)
