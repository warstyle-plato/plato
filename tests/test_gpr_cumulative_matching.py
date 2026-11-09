"""Initial bindings require a whole operation and the complete declared scope."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import developaid_cumulative_progress as progress
import developaid_gpr_cumulative_matching as matching
import developaid_monitor as monitor
import developaid_monitor_pace as pace
import developaid_report_schedule as report
import developaid_schedule_gpr_forecast as forecast
import developaid_schedule_gpr_physical as physical
from test_gpr_statement_observations import history

CUT = '2026-11-06'


def task(tid='floor4', *, floor=4, corpus=4, name=None, **changes):
    value = {'task_id': tid, 'name': name or f'{floor}-ый этаж верт констр', 'object': f'Корпус {corpus}',
             'plan_start': '2026-09-01', 'plan_finish': '2026-12-31'}
    value.update(changes)
    return value


def source(*tasks):
    return {'tasks': {row['task_id']: row for row in tasks or [task()]},
            'source_sha256': 'a'*64, 'state': 'approved_gpr', 'reason': ''}


def snapshot(*, floor='4-го', corpus=4, items=None, **ledger_changes):
    item = {'position': '1.1', 'name': f'Устройство монолитных железобетонных вертикальных конструкций {floor} этажа',
            'scope': f'Раздел 2. Монолитные железобетонные конструкции Корпуса {corpus}',
            'unit': 'м³', 'plan_quantity': 100, 'completed_quantity': 40,
            'planned_amount': 1000, 'completed_amount': 400,
            'planned_work_amount': 700, 'planned_material_amount': 300, 'planned_cost_split': True,
            'planned_work_amount_basis': 'with_vat',
            'periods': [{'label': 'КС-2 № 1', 'quantity': 40, 'amount': 400}],
            'source': {'filename': 'private-synthetic.xlsx', 'sheet': 'КС', 'row': 31}}
    ledger = {'customer': 'ООО Учебный заказчик', 'contractor': 'ООО Учебный подрядчик',
              'contract': 'СИНТ-1', 'contract_date': '2025-01-01', 'period_year': 2026,
              'items': copy.deepcopy(items) if items is not None else [item]}
    ledger.update(ledger_changes)
    return {'snapshot_id': CUT+'-'+'b'*64, 'taken_at': CUT, 'sha256': 'b'*64, 'ledgers': [ledger]}


def test_closed_operation_and_equal_explicit_scope_can_form_a_binding_without_writes():
    plan, snap = source(), snapshot()
    before = copy.deepcopy((plan, snap))
    result = matching.suggest(plan, snap, CUT)
    assert result['configuration']['tasks'] == [
        {'task_id': 'floor4', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}]
    assert result['configuration']['components'][0]['item_ids'] == ['0:0']
    assert result['bindings']['floor4']['basis'] == 'closed_operation_and_exact_scope'
    assert result['bindings']['floor4']['metric']['ratio'] == .4
    assert (plan, snap) == before


@pytest.mark.parametrize('change', ['location', 'floor', 'unapproved', 'contract_future'])
def test_one_similar_name_does_not_override_missing_or_conflicting_scope(change):
    plan, snap = source(), snapshot()
    if change == 'location':
        snap['ledgers'][0]['items'][0]['scope'] = ''
    elif change == 'floor':
        snap['ledgers'][0]['items'][0]['name'] = 'Устройство монолитных железобетонных вертикальных конструкций 7-го этажа'
    elif change == 'unapproved':
        plan['state'] = 'unapproved_corpus'
    else:
        snap['ledgers'][0]['contract_date'] = '2030-01-01'
    result = matching.suggest(plan, snap, CUT)
    assert result['configuration']['tasks'] == [] and result['coverage']['candidate_positions'] == 1


def test_a_single_itp_task_is_not_positive_evidence_of_plant_location():
    plan = source(task(name='Монтаж ИТП. Тепломеханическая часть'))
    snap = snapshot()
    row = snap['ledgers'][0]['items'][0]
    row.update(name='Теплообменник', scope='Раздел 1. Индивидуальный тепловой пункт. Тепломеханическая часть')
    before = matching.suggest(plan, snap, CUT)
    assert before['configuration']['tasks'] == []
    assert before['candidates'][0]['reason'] == 'location_unknown'
    snap['ledgers'][0]['object_scope'] = 'Индивидуальный тепловой пункт. Корпус 4'
    after = matching.suggest(plan, snap, CUT)
    assert len(after['configuration']['tasks']) == 1


def test_numbered_plants_and_negative_floor_are_not_collapsed():
    plan = source(task(name='Монтаж ИТП № 2. Тепломеханическая часть'))
    snap = snapshot(object_scope='ИТП № 1. Корпус 4')
    snap['ledgers'][0]['items'][0].update(name='Теплообменник', scope='ИТП № 1. Тепломеханическая часть')
    assert matching.suggest(plan, snap, CUT)['configuration']['tasks'] == []
    assert matching._floors('-1 этаж') == frozenset()
    assert matching._floors('−1 этаж') == frozenset()
    assert matching._floors('3-го и 4-го этажа') == frozenset({'3', '4'})
    assert matching._floors('этажи 3, 4') == frozenset({'3', '4'})
    assert matching.task_descriptor(task(name='Вертикальные конструкции пятого этажа'))['ambiguous']
    assert matching.item_descriptor({}, {'name': 'Устройство монолитных железобетонных вертикальных конструкций -1, 1 этажей',
                                         'scope': 'Корпус 4'})['ambiguous']


def test_shared_floor_quantity_is_one_cohort_not_a_percent_on_every_leaf():
    plan = source(task('floor3', floor=3), task('floor4', floor=4))
    snap = snapshot(floor='3-4')
    result = matching.suggest(plan, snap, CUT)
    assert result['configuration']['tasks'] == []
    cohort, = result['cohorts']
    assert cohort['task_ids'] == ['floor3', 'floor4'] and cohort['leaf_allocation'] == 'not_provided'
    assert cohort['source_metric']['ratio'] == .4
    assert cohort['source_components'][0]['item_ids'] == ['0:0']


def test_uncovered_floor_does_not_become_a_single_leaf_binding():
    result = matching.suggest(source(task('floor3', floor=3)), snapshot(floor='3-4'), CUT)
    assert result['configuration']['tasks'] == [] and result['cohorts'] == []
    assert result['candidates'][0]['reason'] == 'incomplete_or_shared_target_scope'


def test_mixed_corpus_floor_relations_are_candidates_not_a_cartesian_allocation():
    snap = snapshot(floor='3-4')
    snap['ledgers'][0]['items'][0]['scope'] = '3-4 этажа Корпуса 4 и Корпуса 5'
    result = matching.suggest(source(task('a', floor=3), task('b', floor=4, corpus=5)), snap, CUT)
    assert result['configuration']['tasks'] == [] and result['cohorts'] == []


def test_explicit_zones_and_floor_scope_are_not_ignored():
    assert matching._zones('Фундаменты АС 7.1, 8 захватка')[0] == frozenset({'7.1', '8'})
    target = task('parking', name='Устройство фундаментных плит захватки 1, 3', object='Паркинг / стилобат')
    snap = snapshot()
    snap['ledgers'][0]['items'][0].update(name='Устройство монолитной железобетонной фундаментной плиты',
                                         scope='Подземная автостоянка')
    assert matching.suggest(source(target), snap, CUT)['configuration']['tasks'] == []


def test_numbered_source_reference_does_not_hide_the_actual_operation():
    assert matching._operation('(Ф8.4) Устройство фасадов со штукатуркой') == 'facade_plaster'
    assert matching._operation('(демонтаж) Устройство фасадов со штукатуркой') is None
    assert matching.task_descriptor(task(name='7-ый этаж верт ПП'))['family'] is None
    assert matching.item_descriptor({}, {'name': 'Демонтаж', 'scope': 'Устройство монолитных железобетонных вертикальных конструкций'})['family'] is None


def test_multi_component_binding_requires_explicit_compatible_smr_weights():
    snap = snapshot()
    first = snap['ledgers'][0]['items'][0]
    second = copy.deepcopy(first)
    second.update(position='1.2', name=first['name']+' второго участка', unit='шт', planned_work_amount=300,
                  completed_quantity=20, periods=[{'quantity': 20}], planned_amount=500)
    snap['ledgers'][0]['items'].append(second)
    result = matching.suggest(source(), snap, CUT)
    assert result['bindings']['floor4']['metric']['ratio'] == pytest.approx(.34)
    second['planned_work_amount'] = None
    assert matching.suggest(source(), snap, CUT)['configuration']['tasks'] == []


def test_annual_books_use_one_full_plan_and_the_canonical_full_contract_identity(monkeypatch, tmp_path):
    snap = snapshot()
    annual = copy.deepcopy(snap['ledgers'][0])
    annual['period_year'] = 2025
    annual['items'][0].update(completed_quantity=10, periods=[{'quantity': 10}])
    snap['ledgers'].append(annual)
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    history(monkeypatch, [snap])
    monkeypatch.setattr(physical, '_history', lambda _: [])
    plan = source()
    state = physical._state('Synthetic', CUT, plan, snap)
    model = physical._view_model('Synthetic', CUT, plan, snap, state['configuration'], automatic=state['automatic_mapping'])
    measured, = model['tasks']
    assert measured['progress'] == .5 and measured['components'][0]['plan_quantity'] == 100
    assert measured['components'][0]['completed_quantity'] == 50 and measured['forecast_finish'] is None
    snap['ledgers'][1]['customer'] = 'ООО Другой заказчик'
    assert not matching.suggest(plan, snap, CUT)['bindings']


def test_proven_groups_are_not_double_weighted_and_real_zero_leaf_blocks_done_claim():
    snap = snapshot()
    first = snap['ledgers'][0]['items'][0]
    first.update(completed_quantity=100, periods=[{'quantity': 100}])
    group = copy.deepcopy(first)
    group.update(is_group=True, position='1', completed_quantity=0, periods=[{'quantity': 0}])
    zero = copy.deepcopy(first)
    zero.update(position='1.3', name=first['name']+' отдельного участка', planned_work_amount=0,
                completed_quantity=0, periods=[{'quantity': 0}])
    snap['ledgers'][0]['items'].extend([group, zero])
    metric = matching.suggest(source(), snap, CUT)['bindings']['floor4']['metric']
    assert metric['ratio'] == 1 and not metric['all_complete'] and metric['requires_reconciliation']


def test_auto_state_is_derived_and_an_explicit_manual_revoke_wins(monkeypatch, tmp_path):
    snap, plan = snapshot(), source()
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(physical, '_history', lambda _: [])
    state = physical._state('Synthetic', CUT, plan, snap)
    assert state['binding_automatic'] and state['recorded_at'] is None and state['revision'] == 0
    assert not list(tmp_path.rglob('*.json'))
    event = {'source_kind': 'gpr', 'source_sha256': plan['source_sha256'], 'snapshot_id': snap['snapshot_id'],
             'revision': 1, 'recorded_at': CUT+'T10:00:00+00:00',
             'configuration': {'tasks': [], 'components': [], 'note': 'Соответствия сняты после проверки.'}}
    monkeypatch.setattr(physical, '_history', lambda _: [event])
    revoked = physical._state('Synthetic', CUT, plan, snap)
    assert not revoked['binding_automatic'] and revoked['configuration']['tasks'] == []


def test_cohort_model_preserves_known_shared_percent_and_never_populates_leafs(monkeypatch, tmp_path):
    snap = snapshot(floor='3-4')
    plan = source(task('floor3', floor=3), task('floor4', floor=4))
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    history(monkeypatch, [snap])
    monkeypatch.setattr(physical, '_history', lambda _: [])
    state = physical._state('Synthetic', CUT, plan, snap)
    model = physical._view_model('Synthetic', CUT, plan, snap, state['configuration'], automatic=state['automatic_mapping'])
    assert all(task['progress'] is None for task in model['tasks'])
    cohort, = model['source_cohorts']
    assert cohort['model']['progress'] == .4 and cohort['model']['forecast_finish'] is None
    assert cohort['task_ids'] == ['floor3', 'floor4'] and model['seeds'] == {}
    assert model['physical_evidence'] and model['cohort_evidence']
    status = physical.evidence_status('Synthetic', CUT, plan, snap, state, model)
    assert status['state'] == 'shared_scope'
    summary = report.model({'rnv': {'state': 'unknown'}, 'physical': model})
    fact, = summary['facts']
    assert fact['kind'] == 'source_cohort' and fact['progress'] == .4
    assert '40%' in report.fact_text(fact) and 'общий объём для 2 работ' in report.fact_text(fact)


@pytest.mark.parametrize('field,value', [('scope', '3-го этажа Корпуса 4'), ('system_scope', 'ИТП № 2')])
def test_conflicting_explicit_source_scopes_are_not_ignored(field, value):
    snap = snapshot()
    if field == 'system_scope':
        snap['ledgers'][0]['items'][0].update(name='Монтаж ИТП № 1. Тепломеханическая часть', scope='Корпус 4')
    snap['ledgers'][0]['items'][0][field] = value
    assert matching.item_descriptor(snap['ledgers'][0], snap['ledgers'][0]['items'][0])['ambiguous']


def test_duplicate_leaf_scope_cannot_certify_a_complete_shared_group():
    plan = source(task('floor3a', floor=3), task('floor3b', floor=3), task('floor4', floor=4))
    result = matching.suggest(plan, snapshot(floor='3-4'), CUT)
    assert not result['cohorts'] and not result['configuration']['tasks']


def test_two_contracts_cannot_both_claim_the_same_complete_shared_scope():
    snap = snapshot(floor='3-4')
    another = copy.deepcopy(snap['ledgers'][0])
    another['contract'] = 'СИНТ-2'
    snap['ledgers'].append(another)
    result = matching.suggest(source(task('floor3', floor=3), task('floor4', floor=4)), snap, CUT)
    assert not result['cohorts'] and not result['configuration']['tasks']
    assert result['coverage']['reasons']['overlapping_source_scopes'] == 2


def test_nested_leaf_and_shared_scope_require_explicit_source_decomposition():
    snap = snapshot(floor='3-4')
    floor3 = copy.deepcopy(snap['ledgers'][0]['items'][0])
    floor3.update(position='2.1', name='Устройство монолитных железобетонных вертикальных конструкций 3-го этажа')
    snap['ledgers'][0]['items'].append(floor3)
    result = matching.suggest(source(task('floor3', floor=3), task('floor4', floor=4)), snap, CUT)
    assert not result['cohorts'] and not result['configuration']['tasks']


def multi_snapshot(done_first=40, done_second=20, *, day=CUT, weight=700):
    snap = snapshot()
    snap.update(snapshot_id=day+'-'+('c' if day != CUT else 'b')*64, taken_at=day,
                sha256=('c' if day != CUT else 'b')*64)
    first = snap['ledgers'][0]['items'][0]
    first.update(completed_quantity=done_first, periods=[{'quantity': done_first}], planned_work_amount=weight)
    second = copy.deepcopy(first)
    second.update(position='1.2', name=first['name']+' второго участка', unit='шт',
                  planned_work_amount=300, completed_quantity=done_second, periods=[{'quantity': done_second}])
    snap['ledgers'][0]['items'].append(second)
    return snap


@pytest.mark.parametrize('old_weight,expected', [(700, 'growing'), (500, 'basis_changed')])
def test_runtime_uses_one_weighted_quantity_metric_for_current_and_snapshot_dynamics(monkeypatch, tmp_path, old_weight, expected):
    old, current = multi_snapshot(10, 10, day='2026-10-01', weight=old_weight), multi_snapshot()
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    history(monkeypatch, [old, current])
    monkeypatch.setattr(physical, '_history', lambda _: [])
    plan = source()
    state = physical._state('Synthetic', CUT, plan, current)
    model = physical._view_model('Synthetic', CUT, plan, current, state['configuration'], automatic=state['automatic_mapping'])
    measured, = model['tasks']
    assert measured['progress'] == pytest.approx(.34)
    assert measured['quantity_metric']['ratio'] == measured['progress']
    assert measured['observation_history']['state'] == expected
    if expected == 'growing':
        assert measured['observation_history']['delta_progress'] == pytest.approx(.24)
    else:
        assert measured['observation_history']['delta_progress'] is None
    weighted, *_ = report.model({'rnv': {'state': 'unknown'}, 'physical': model})['facts']
    assert weighted['kind'] == 'weighted_quantity' and weighted['progress'] == measured['progress']


def cohort_runtime(monkeypatch, tmp_path, *, gpr=(1., 1.), exact=True, weighted_unknown=False):
    snap = snapshot(floor='3-4' if exact else '3-5')
    plan = source(task('floor3', floor=3), task('floor4', floor=4))
    if weighted_unknown:
        second = copy.deepcopy(snap['ledgers'][0]['items'][0])
        second.update(position='1.2', planned_work_amount=None)
        snap['ledgers'][0]['items'].append(second)
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    history(monkeypatch, [snap])
    monkeypatch.setattr(physical, '_history', lambda _: [])
    points = {tid: [(dt.date.fromisoformat(CUT), value, 'approved_gpr')]
              for tid, value in zip(plan['tasks'], gpr) if value is not None}
    monkeypatch.setattr(forecast, 'history', lambda *_: points)
    state = physical._state('Synthetic', CUT, plan, snap)
    model = physical._view_model('Synthetic', CUT, plan, snap, state['configuration'], automatic=state['automatic_mapping'])
    return plan, snap, state, model, points


def test_shared_ks_conflict_blocks_group_finish_and_preserves_every_original_gpr_reading(monkeypatch, tmp_path):
    plan, snap, state, model, points = cohort_runtime(monkeypatch, tmp_path)
    assert model['state'] == 'source_conflict' and model['seeds'] == {} and model['actual_finishes'] == {}
    assert model['source_cohorts'][0]['model']['progress'] == .4
    for measured in model['tasks']:
        assert measured['progress'] is None and measured['source_conflict']['gpr']['progress'] == 1
        result = forecast.work(plan['tasks'][measured['task_id']], points[measured['task_id']], dt.date.fromisoformat(CUT), measured)
        assert result['progress'] == 1 and result['progress_origin'] == 'approved_gpr'
        assert result['forecast_finish'] is None and result['method'] == 'source_conflict'
    assert physical.evidence_status('Synthetic', CUT, plan, snap, state, model)['state'] == 'source_conflict'
    monkeypatch.setattr(physical, 'build', lambda *_: model)
    rows = [dict(row, id=tid, code='2.1') for tid, row in plan['tasks'].items()]
    view = pace._apply_gpr('Synthetic', {'schedule': {'rows': rows}}, dt.date.fromisoformat(CUT))
    assert all(row['actual_progress'] == row['gpr_progress'] == 1 and not row['forecast_known'] for row in rows)
    rnv = view['schedule']['dependency_timeline']['rnv']
    assert rnv['forecast'] is None and any('общей группы' in reason for reason in rnv['reasons'])
    work_fact = view['schedule']['work_fact']['works']['floor3']
    assert work_fact['ks']['progress'] is None and work_fact['ks']['shared_scope'][0]['progress'] == .4
    assert work_fact['gpr']['progress'] == 1 and work_fact['source_conflict']['scope'] == 'source_cohort'
    assert 'отдельным работам' in work_fact['ks']['reason']


@pytest.mark.parametrize('changes', [{'gpr': (1., .9)}, {'gpr': (1., None)}, {'exact': False}, {'weighted_unknown': True}])
def test_shared_source_conflict_requires_complete_exact_link_and_a_known_common_metric(monkeypatch, tmp_path, changes):
    _, _, _, model, _ = cohort_runtime(monkeypatch, tmp_path, **changes)
    assert not model.get('source_conflicts')


def test_catalog_and_runtime_matcher_use_the_same_canonical_rows_even_with_raw_date_identity():
    snap = snapshot(contract_date=None, contract_date_evidence=[{'raw': '01.01.025', 'source': {'cell': 'C7'}}])
    plan = source()
    views = progress.quantity_views(snap, CUT)
    catalog = {'source_state': plan['state'], 'source_sha256': plan['source_sha256'],
               'snapshot_id': snap['snapshot_id'], 'tasks': list(plan['tasks'].values()),
               'items': [dict(view, item_id=key) for key, view in views.items()]}
    direct, projected = matching.suggest(plan, snap, CUT), matching.suggest_catalog(catalog, CUT)
    assert direct['coverage'] == projected['coverage']
    assert direct['configuration'] == projected['configuration']
    assert direct['bindings']['floor4']['metric']['ratio'] == projected['bindings']['floor4']['metric']['ratio'] == .4


def test_new_explicit_scope_changes_the_stable_position_key_and_prevents_history_carry():
    before, after = snapshot(), snapshot(object_scope='Корпус 5')
    first, second = before['ledgers'][0], after['ledgers'][0]
    assert progress.position_identity(first, first['items'][0]) != progress.position_identity(second, second['items'][0])
