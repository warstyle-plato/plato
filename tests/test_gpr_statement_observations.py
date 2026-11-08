"""Known KS quantities and snapshot dynamics are not invented act dates."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import developaid_cumulative_progress as progress
import developaid_monitor as monitor
import developaid_report_schedule as report_schedule
import developaid_schedule_gpr_physical as physical
import developaid_schedule_work_fact as work_fact
from test_schedule_gpr_physical import CUT, PROJECT, config, save, site


def snapshot(day=CUT, done=40, *, token='b', **changes):
    row = {'position': '1.1', 'name': 'Монтаж', 'scope': 'Корпус 1', 'unit': 'м²',
           'plan_quantity': 100, 'completed_quantity': done, 'material_quantity': 90,
           'planned_amount': 1000, 'completed_amount': done*10,
           'periods': [{'label': 'КС-2 № 1', 'quantity': done, 'amount': done*10,
                        'date_start': None, 'date_end': None}],
           'source': {'filename': 'statement.xlsx', 'sheet': 'КС', 'row': 31}}
    row.update(changes)
    return {'snapshot_id': day+'-'+token*64, 'taken_at': day, 'sha256': token*64,
            'ledgers': [{'customer': 'ООО «Учебный заказчик»', 'contractor': 'ООО «Учебный подрядчик»',
                         'contract': 'А-1', 'contract_date': '2025-01-01', 'period_year': 2026,
                         'items': [row]}]}


def source():
    return {'source_sha256': 'a'*64, 'state': 'approved_gpr', 'reason': '',
            'tasks': {'1': {'task_id': '1', 'name': 'Монтаж', 'object': 'Корпус 1',
                            'plan_start': '2026-09-01', 'plan_finish': '2026-12-01'}}}


def history(monkeypatch, snapshots):
    by_id = {s['snapshot_id']: copy.deepcopy(s) for s in snapshots}
    monkeypatch.setattr(progress.ledgers, 'list_snapshots', lambda project: [
        {'snapshot_id': s['snapshot_id'], 'taken_at': s['taken_at']} for s in snapshots])
    monkeypatch.setattr(progress.ledgers, 'read_snapshot', lambda project, sid: copy.deepcopy(by_id[sid]))


def evaluate(monkeypatch, snapshots):
    history(monkeypatch, snapshots)
    current = snapshots[-1]
    views = progress.quantity_views(current, CUT)
    index = progress.observation_index(PROJECT, CUT, current, [v['position_key'] for v in views.values()])
    return physical.evaluate(source(), current, config(), CUT, observation_index=index)


def test_one_undated_statement_exposes_the_same_quantity_percentage_without_forecast(monkeypatch):
    current = snapshot()
    before = copy.deepcopy(current)
    model = evaluate(monkeypatch, [current])
    task, = model['tasks']
    component, = task['components']
    assert task['progress'] == .4 and task['progress_origin'] == 'cumulative_statement'
    assert task['progress_date'] == CUT and task['progress_date_basis'] == 'snapshot'
    assert not task['known'] and task['forecast_finish'] is None
    assert component['completed_quantity'] == 40 and component['plan_quantity'] == 100
    assert component['period_end'] is None and component['observation_date'] == CUT
    assert 'actual_finish' not in task and not model['seeds'] and model['physical_evidence']
    assert component['observation_history']['state'] == 'single_snapshot'
    assert current == before


def test_two_comparable_snapshots_drive_quantity_dynamics_and_qualified_forecast(monkeypatch):
    model = evaluate(monkeypatch, [snapshot('2026-10-01', 20, token='c'), snapshot()])
    task, = model['tasks']
    observation = task['observation_history']
    assert observation['delta_quantity'] == 20 and observation['delta_progress'] == pytest.approx(.2)
    assert observation['basis'] == 'snapshot_observations' and observation['forecast_eligible']
    assert task['known'] and task['forecast_finish'] == '2027-02-22'
    assert task['components'][0]['method'] == 'statement_observation_pace'
    assert 'actual_finish' not in task


@pytest.mark.parametrize('before,expected', [(40, 'unchanged'), (60, 'correction')])
def test_zero_growth_and_corrections_remain_visible_and_do_not_invent_pace(monkeypatch, before, expected):
    task, = evaluate(monkeypatch, [snapshot('2026-10-01', before, token='c'), snapshot()])['tasks']
    assert task['progress'] == .4 and task['observation_history']['state'] == expected
    assert task['observation_history']['delta_quantity'] == 40-before
    assert task['forecast_finish'] is None and not task['known']


def test_changed_scope_or_plan_cannot_be_a_comparable_growth(monkeypatch):
    old = snapshot('2026-10-01', 20, token='c', plan_quantity=120)
    task, = evaluate(monkeypatch, [old, snapshot()])['tasks']
    assert task['progress'] == .4
    assert task['observation_history']['state'] == 'single_snapshot'
    assert task['forecast_finish'] is None


def test_material_delivery_and_source_money_do_not_change_physical_dynamics(monkeypatch):
    old = snapshot('2026-10-01', 40, token='c', material_quantity=1)
    current = snapshot(material_quantity=1e10, completed_amount=1e12)
    task, = evaluate(monkeypatch, [old, current])['tasks']
    assert task['progress'] == .4 and task['observation_history']['delta_quantity'] == 0
    assert task['forecast_finish'] is None


def test_complete_statement_does_not_make_the_snapshot_an_actual_finish_date(monkeypatch):
    task, = evaluate(monkeypatch, [snapshot(done=100)])['tasks']
    assert task['progress'] == 1 and task['forecast_finish'] is None
    assert 'actual_finish' not in task


def test_known_future_execution_suppresses_annual_statement_percentage(monkeypatch):
    current = snapshot(periods=[{'date_start': '2026-11-01', 'date_end': '2026-11-30', 'quantity': 40}])
    task, = evaluate(monkeypatch, [current])['tasks']
    assert task['progress'] is None and task['forecast_finish'] is None


def test_mixed_units_remain_separate_components_not_a_work_average(monkeypatch):
    current = snapshot()
    second = copy.deepcopy(current['ledgers'][0]['items'][0])
    second.update(position='1.2', name='Бетонирование', unit='м³', plan_quantity=200,
                  completed_quantity=20, periods=[{'label': 'КС-2 № 1', 'quantity': 20}])
    current['ledgers'][0]['items'].append(second)
    cfg = config()
    cfg['components'].append({'component_id': 'Корпус 1 — бетон', 'task_id': '1', 'item_ids': ['0:1']})
    model = physical.evaluate(source(), current, cfg, CUT)
    task, = model['tasks']
    assert task['progress'] is None
    assert [c['progress'] for c in task['components']] == [.4, .1]
    assert model['physical_evidence']


def test_monitor_work_facts_and_report_reuse_the_observation_with_visible_date_basis(site, monkeypatch):
    _, snap, _ = site
    snap.clear()
    snap.update(snapshot())
    history(monkeypatch, [snap])
    saved = save()
    assert saved['model']['tasks'][0]['progress'] == .4
    view = monitor.build(PROJECT, CUT)
    row = view['schedule']['rows'][0]
    assert row['actual_progress'] == .4 and row['gpr_progress'] == .8
    assert row['progress_kind'] == 'cumulative_statement'
    assert row['progress_source']['date_basis'] == 'snapshot'
    assert row['forecast_finish'] is None
    facts = work_fact.model([row], view['schedule']['physical_progress'])['works']['1']
    assert facts['ks']['progress'] == .4 and facts['ks']['date_basis'] == 'snapshot'
    assert facts['gpr']['progress'] == .8
    summary = report_schedule.model({'rnv': {'state': 'unknown'}, 'physical': saved['model']})
    fact, = summary['facts']
    assert fact['done'] == 40 and fact['progress'] == .4
    assert 'по ведомости от 06.11.2026' in report_schedule.fact_text(fact)


def test_new_snapshot_projects_an_explicit_mapping_only_through_exact_positions(site, monkeypatch):
    _, snap, _ = site
    old = snapshot('2026-10-01', 20, token='c')
    snap.clear()
    snap.update(old)
    history(monkeypatch, [old])
    save()
    current = snapshot()
    snap.clear()
    snap.update(current)
    history(monkeypatch, [old, current])
    state = physical.catalog(PROJECT, CUT)
    assert state['binding_projected'] and state['binding_source_snapshot_id'] == old['snapshot_id']
    assert state['configuration']['components'][0]['item_ids'] == ['0:0']
    assert state['model']['tasks'][0]['progress'] == .4
    assert state['model']['tasks'][0]['observation_history']['delta_quantity'] == 20
    assert not state['source_changed']


@pytest.mark.parametrize('field,value', [('scope', 'Корпус 2'), ('plan_quantity', 200), ('unit', 'т')])
def test_mapping_projection_rejects_a_changed_component(field, value):
    old = snapshot('2026-10-01', 20, token='c')
    current = snapshot(**{field: value})
    assert progress.project_configuration(old, current, config()) is None


def test_duplicate_position_and_explicit_revoke_cannot_be_resurrected(site, monkeypatch):
    previous = snapshot('2026-10-01', 20, token='c')
    current = snapshot()
    current['ledgers'][0]['items'].append(copy.deepcopy(current['ledgers'][0]['items'][0]))
    assert progress.project_configuration(previous, current, config()) is None
    previous['ledgers'][0]['items'].append(copy.deepcopy(previous['ledgers'][0]['items'][0]))
    assert progress.project_configuration(previous, snapshot(), config()) is None
    _, snap, _ = site
    snap.clear()
    snap.update(snapshot('2026-10-01', 20, token='c'))
    history(monkeypatch, [snap])
    save()
    save(configuration={'tasks': [], 'components': [], 'note': 'Прежние соответствия отозваны.'})
    old = copy.deepcopy(snap)
    snap.clear()
    snap.update(snapshot())
    history(monkeypatch, [old, snap])
    state = physical.catalog(PROJECT, CUT)
    assert not state['binding_projected'] and state['configuration']['tasks'] == []


def test_one_changed_work_does_not_erase_another_exact_work_mapping():
    old, current = snapshot('2026-10-01', 20, token='c'), snapshot()
    for source in (old, current):
        row = copy.deepcopy(source['ledgers'][0]['items'][0])
        row.update(position='2', name='Вторая работа')
        source['ledgers'][0]['items'].append(row)
    current['ledgers'][0]['items'][1]['scope'] = 'Корпус 2'
    cfg = config()
    cfg['tasks'].append({'task_id': '2', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''})
    cfg['components'].append({'component_id': 'Вторая работа', 'task_id': '2', 'item_ids': ['0:1']})
    projected = progress.project_configuration(old, current, cfg)
    assert projected is not None
    assert projected['tasks'][0]['scope_confirmed'] and not projected['tasks'][1]['scope_confirmed']
    assert [c['task_id'] for c in projected['components']] == ['1']


def test_unreadable_history_does_not_erase_the_current_known_percentage(monkeypatch):
    def unavailable(_project):
        raise ValueError('PRIVATE-ERROR')
    monkeypatch.setattr(progress.ledgers, 'list_snapshots', unavailable)
    current = snapshot()
    view = progress.quantity_views(current, CUT)['0:0']
    index = progress.observation_index(PROJECT, CUT, current, [view['position_key']])
    task, = physical.evaluate(source(), current, config(), CUT, observation_index=index)['tasks']
    assert task['progress'] == .4 and task['forecast_finish'] is None
    assert task['observation_history']['state'] == 'previous_unavailable'
    assert 'PRIVATE-ERROR' not in str(task)


def test_statement_source_conflict_qualifies_the_date_as_a_snapshot(monkeypatch):
    import developaid_schedule_gpr_forecast as forecast
    task, = evaluate(monkeypatch, [snapshot()])['tasks']
    conflict = forecast.quantity_conflict([(dt.date(2026, 11, 6), 1.0, 'weekly_gpr')], task, dt.date(2026, 11, 6))
    assert conflict['quantities'][0]['date_basis'] == 'snapshot'
    assert '40% по ведомости от 06.11.2026' in conflict['reason']
