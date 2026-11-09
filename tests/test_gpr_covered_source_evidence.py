"""Covered source facts are useful without claiming a whole corpus package."""
from __future__ import annotations

import copy

import pytest

import developaid_gpr_cumulative_matching as matching
import developaid_monitor as monitor
import developaid_schedule_gpr_physical as physical
import developaid_schedule_visual as visual
from test_gpr_cumulative_matching import source, snapshot, task

CUT = '2026-11-06'


def evidence():
    plan = source(task('package4', corpus=4, name='Монолит надземной части', source_format='corpus-gpr-v1'),
                  task('package5', corpus=5, name='Монолит надземной части', source_format='corpus-gpr-v1'))
    snap = snapshot(corpus=4)
    ledger = snap['ledgers'][0]
    ledger['source_complete'] = True
    first = ledger['items'][0]
    first.update(name='Устройство монолитных железобетонных стен 3-го этажа',
        section_path=[{'name': 'Монолитные конструкции Корпуса 4', 'source': {'row': 20, 'cell': 'C20'}},
                      {'name': 'Устройство монолитных железобетонных конструкций надземной части',
                       'source': {'row': 29, 'cell': 'C29'}}],
        scope='Корпус 4, 3-й этаж', parent_row=29)
    second = copy.deepcopy(first)
    second.update(name='Устройство монолитной плиты перекрытия 3-го этажа',
                  position='1.2', completed_quantity=80, completed_amount=800,
                  periods=[{'label': 'КС-2 № 1', 'quantity': 80, 'amount': 800}])
    second['source']['row'] = 32
    ledger['items'].append(second)
    return plan, snap


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)


def model(plan, snap):
    automatic = matching.suggest(plan, snap, CUT)
    return physical._view_model('Учебный источник', CUT, plan, snap, automatic['configuration'], automatic=automatic)


def test_whole_source_subtree_uses_canonical_smr_weights_and_retains_natural_components():
    plan, snap = evidence()
    before = copy.deepcopy((plan, snap))
    result = model(plan, snap)
    group, = result['covered_source_groups']
    assert group['item_ids'] == ['0:0', '0:1']
    assert group['candidate_task_ids'] == ['package4']  # source never claims another building
    assert group['coverage'] == {'source_positions': 2, 'known_positions': 2,
                                  'source_complete': True, 'target_scope_confirmed': False}
    assert group['model']['progress'] == pytest.approx(.6)
    assert group['model']['progress_date'] == CUT and group['model']['progress_date_basis'] == 'snapshot'
    assert [c['progress'] for c in group['model']['components']] == [.4, .8]
    assert all(c['name'] and c['source']['row'] in (31, 32) for c in group['model']['components'])
    assert all(t['mode'] == 'unknown' and t['progress'] is None for t in result['tasks'])
    assert not result['seeds'] and not result['actual_finishes'] and not result['automatic_bindings']
    assert (plan, snap) == before
    assert '60%' in visual.physical_summary(result)
    assert 'Полнота всего пакета ГПР' in visual.physical_summary(result)


def test_changing_materials_cannot_change_the_covered_work_percentage():
    plan, snap = evidence()
    before = model(plan, snap)['covered_source_groups'][0]['model']['progress']
    for item in snap['ledgers'][0]['items']:
        item.update(material_quantity=1e9, planned_material_amount=1e18, completed_material_amount=1e18)
    assert model(plan, snap)['covered_source_groups'][0]['model']['progress'] == before


@pytest.mark.parametrize('change', ['unread', 'missing_plan'])
def test_an_incomplete_source_or_unproved_aggregate_cannot_get_one_percentage(change):
    plan, snap = evidence()
    if change == 'unread':
        snap['ledgers'][0]['source_complete'] = False
        snap['ledgers'][0]['unread_rows_count'] = 1
    elif change == 'missing_plan':
        snap['ledgers'][0]['items'][1]['plan_quantity'] = None
    group, = model(plan, snap)['covered_source_groups']
    assert group['model']['progress'] is None and group['model']['reason']
    assert group['model']['components'][0]['progress'] == .4


def test_global_context_is_not_a_stack_of_active_ancestor_chapters():
    plan = source(task('itp4', corpus=4, name='ИТП', source_format='corpus-gpr-v1'),
                  task('itp5', corpus=5, name='ИТП', source_format='corpus-gpr-v1'))
    snap = snapshot(corpus=4)
    snap['ledgers'][0]['source_complete'] = True
    item = snap['ledgers'][0]['items'][0]
    item.update(name='Монтаж насоса', scope='', section_path=[],
                context_headings=[{'name': 'Раздел 1. Индивидуальный тепловой пункт. Тепломеханическая часть',
                                   'source': {'row': 20, 'cell': 'C20'}}])
    source_group, = matching.covered_subtrees(plan, snap, CUT)
    assert not source_group['location_known'] and not source_group['target_scope_confirmed']
    assert set(source_group['candidate_task_ids']) == {'itp4', 'itp5'}
    assert 'распределение между корпусами' in source_group['scope_reason']
    item['context_headings'].append({'name': 'Раздел 2. Другой объект', 'source': {'row': 30, 'cell': 'C30'}})
    assert matching.covered_subtrees(plan, snap, CUT) == []


def test_a_future_source_does_not_expose_covered_progress():
    plan, snap = evidence()
    snap['taken_at'] = '2026-11-07'
    assert matching.covered_subtrees(plan, snap, CUT) == []


def test_discovery_can_retain_a_qualified_parking_part_but_not_another_number_or_object_type():
    assert matching._covered_location_possible({'object:parking:underground:unspecified'},
                                               {'object:parking:unspecified:unspecified'})
    assert not matching._covered_location_possible({'object:parking:underground:1'},
                                                   {'object:parking:underground:2'})
    assert not matching._covered_location_possible({'object:parking:underground:1'},
                                                   {'object:stylobate:underground:1'})


def test_unknown_financial_fields_outside_the_subtree_do_not_hide_its_known_quantities():
    plan, snap = evidence()
    snap['ledgers'][0].update(source_complete=False, unread_rows_count=0, incomplete_rows_count=1)
    outside = copy.deepcopy(snap['ledgers'][0]['items'][0])
    outside.update(name='Другая денежная строка без объёма', section_path=[], scope='', plan_quantity=None, unit='')
    outside['source']['row'] = 99
    snap['ledgers'][0]['items'].append(outside)
    group, = model(plan, snap)['covered_source_groups']
    assert not group['ledger_source_complete'] and group['source_complete']
    assert group['model']['progress'] == pytest.approx(.6) and len(group['model']['components']) == 2


def test_independent_work_and_its_separately_budgeted_child_are_not_reclassified_as_totals():
    plan, snap = evidence()
    snap['ledgers'][0]['items'][1]['section_path'].append(
        {'name': snap['ledgers'][0]['items'][0]['name'], 'source': {'row': 31, 'cell': 'C31'}})
    snap['ledgers'][0]['items'][1]['parent_row'] = 31
    group, = model(plan, snap)['covered_source_groups']
    assert group['model']['progress'] == pytest.approx(.6)
    assert len(group['model']['components']) == 2
    # The canonical parser's proved total is excluded; the real child remains.
    snap['ledgers'][0]['items'][0]['is_group'] = True
    group, = model(plan, snap)['covered_source_groups']
    assert group['model']['progress'] == .8 and len(group['model']['components']) == 1
