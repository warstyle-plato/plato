"""One annual denominator needs one source work; independent components keep weights."""
from __future__ import annotations

import copy

import pytest

import developaid_cumulative_progress as progress
import developaid_schedule_gpr_physical as physical

CUT = '2026-11-06'
TASK = {'task_id': '1', 'name': 'Монтаж', 'object': 'Корпус 1'}
SOURCE = {'tasks': {'1': TASK}}


def snapshot(*, left=50, right=50, undated=False):
    ledgers = []
    for year, done in ((2025, left), (2026, right)):
        row = dict(position='1', name='Монтаж', scope='Корпус 1', unit='м²',
            plan_quantity=100, completed_quantity=done,
            planned_work_amount=1000, planned_cost_split=True, planned_work_amount_basis='without_vat',
            source={'filename': f'example-{year}.xlsx', 'sheet': 'КС', 'row': 8},
            periods=[dict(label='КС-2 № 1', quantity=done,
                date_start=None if undated else f'{year}-10-01',
                date_end=None if undated else f'{year}-10-31')])
        ledgers.append(dict(customer='Учебный заказчик', contractor='Учебный подрядчик',
            contract='А-1', contract_date='2025-01-01', period_year=year, items=[row]))
    return dict(taken_at=CUT, snapshot_id=CUT+'-'+'b'*64, sha256='b'*64, ledgers=ledgers)


def configuration(*, separate=False):
    return {'tasks': [dict(task_id='1', mode='quantities', scope_confirmed=True, actual_finish='')],
            'components': ([dict(component_id='Первая система', task_id='1', item_ids=['0:0']),
                            dict(component_id='Вторая система', task_id='1', item_ids=['1:0'])] if separate else
                           [dict(component_id='Один годовой компонент', task_id='1', item_ids=['0:0', '1:0'])]),
            'note': 'Полнота задачи не изменяет идентичность исходных работ.'}


def evaluated(snapshot, *, separate=False):
    return physical.evaluate(SOURCE, snapshot, configuration(separate=separate), CUT)['tasks'][0]


@pytest.mark.parametrize('field,left,right', [
    ('system_scope', 'Отопление', 'Холодоснабжение'),
    ('section_path', [{'position': '1', 'name': 'Отопление'}], [{'position': '1', 'name': 'Холодоснабжение'}]),
    ('object_scope', 'Корпус 1', 'Паркинг 1'),
    ('object_scope', 'Паркинг 1', 'Стилобат 1'),
    ('object_scope', 'Паркинг 1', 'Паркинг 2'),
    ('site_scope', 'Внутренние сети', 'Наружные сети'),
])
@pytest.mark.parametrize('undated', [False, True])
def test_different_works_cannot_be_collapsed_into_one_annual_plan(field, left, right, undated):
    data = snapshot(undated=undated)
    a, b = (ledger['items'][0] for ledger in data['ledgers'])
    a[field], b[field] = left, right
    before = copy.deepcopy(data)
    views = progress.quantity_views(data, CUT)
    assert views['0:0']['annual_work_key'] != views['1:0']['annual_work_key']
    result = evaluated(data)
    assert result['progress'] is None and not result['known'] and not result.get('actual_finish')
    assert result['forecast_finish'] is None and result['requires_reconciliation']
    assert 'идентичность' in result['reason']
    assert [component.get('progress') for component in result['components']] == [None]
    assert [(view['completion_ratio'] if view['completion_ratio'] is not None else
             view['reported_completion_ratio']) for view in views.values()] == [.5, .5]
    assert data == before


def test_customer_is_part_of_the_annual_work_identity():
    data = snapshot()
    data['ledgers'][1]['customer'] = 'Другой учебный заказчик'
    result = evaluated(data)
    assert result['progress'] is None and not result.get('actual_finish')


def test_missing_source_identity_does_not_become_a_completed_annual_component():
    data = snapshot()
    for ledger in data['ledgers']:
        ledger.pop('customer')
    result = evaluated(data)
    assert result['progress'] is None and not result['known'] and not result.get('actual_finish')


@pytest.mark.parametrize('right,weight,unit,expected', [(50, 1000, 'м²', .5), (25, 3000, 'шт', .3125)])
def test_independent_components_retain_their_known_percentages_and_explicit_smr_weights(right, weight, unit, expected):
    data = snapshot(right=right)
    a, b = (ledger['items'][0] for ledger in data['ledgers'])
    a['system_scope'], b['system_scope'] = 'Отопление', 'Холодоснабжение'
    b.update(planned_work_amount=weight, unit=unit)
    result = evaluated(data, separate=True)
    assert [component['progress'] for component in result['components']] == [.5, right/100]
    assert result['progress'] == pytest.approx(expected)
    metric = result['quantity_metric']
    assert metric['ratio'] == pytest.approx(expected) and metric['complete_coverage']
    assert metric['basis'] == 'smr_cost_weighted_quantities' and metric['members'] == 2
    assert not result.get('actual_finish') and not result.get('requires_reconciliation')


def test_two_fully_completed_independent_components_can_still_confirm_the_whole_task():
    data = snapshot(left=100, right=100)
    a, b = (ledger['items'][0] for ledger in data['ledgers'])
    a['system_scope'], b['system_scope'] = 'Отопление', 'Холодоснабжение'
    result = evaluated(data, separate=True)
    assert result['known'] and result['progress'] == 1
    assert result['actual_finish'] == '2026-10-31'
    assert result['quantity_metric']['complete_coverage'] and result['quantity_metric']['all_complete']
    assert not result['requires_reconciliation']


@pytest.mark.parametrize('undated', [False, True])
def test_one_qualified_work_uses_its_annual_plan_once_without_inventing_dates(undated):
    result = evaluated(snapshot(left=10, undated=undated))
    assert result['progress'] == pytest.approx(.6)
    component, = result['components']
    assert component['plan_quantity'] == 100 and component['completed_quantity'] == 60
    assert not result.get('actual_finish')
    if undated:
        assert not result['known'] and result['forecast_finish'] is None
        assert result['progress_basis'] == 'По ведомости'
    else:
        assert result['known'] and result['forecast_finish'] == '2026-12-01'


def test_preceding_context_is_uncertainty_until_common_ancestry_is_proved():
    data = snapshot()
    a, b = (ledger['items'][0] for ledger in data['ledgers'])
    a['context_headings'], b['context_headings'] = [{'name': 'Отопление'}], [{'name': 'Холодоснабжение'}]
    result = evaluated(data)
    assert result['progress'] is None and 'заголовки' in result['reason']
    a['section_path'] = b['section_path'] = [{'position': '1', 'name': 'Один доказанный раздел'}]
    result = evaluated(data)
    assert result['known'] and result['progress'] == 1 and result['actual_finish'] == '2026-10-31'
