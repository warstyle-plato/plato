"""Ставка льготы из НЦС не меняется вместе с бюджетом строительства."""
from copy import deepcopy
from decimal import Decimal
import io

import pytest
from openpyxl import load_workbook

import education_ncs
import mo_vri_benefits as benefits
import main_legacy as core


def configuration(kind='school', **changes):
    row = {'id': 'education', 'kind': kind, 'required_places': 400,
           'planned_places': 675, 'valuation_mode': 'ncs', 'ncs_table': '03-03-007'}
    row.update(changes)
    return {'schema': 1, 'rows': [row]}


def test_published_interpolation_example_uses_the_full_school_capacity():
    cfg = configuration(rub_per_place=99999999)
    result = benefits.estimate(cfg, inputs={'school_cost_mln_per_place': 99}, tep={})
    row, = result['rows']
    assert result['total_rub'] == 363_533_500  # 275 surplus × 1,321,940 rub/seat.
    assert row['unit_rate_rub'] == 1_321_940
    assert [p['places'] for p in row['ncs']['points']] == [550, 800]
    assert row['ncs']['price_date'] == '2026-01-01' and row['ncs']['vat'] == 'без НДС'
    assert row['source'].endswith('19032026_167_pr_sbornik_3.pdf')


@pytest.mark.parametrize('budget', [None, 0, 1, 4, 99])
def test_school_and_kindergarten_rates_do_not_use_the_project_budget(budget):
    school = benefits.estimate(configuration(), inputs={'school_cost_mln_per_place': budget}, tep={})
    dou = benefits.estimate(configuration('kindergarten', required_places=200,
        planned_places=250, ncs_table='03-01-001'),
        inputs={'kindergarten_cost_mln_per_place': budget}, tep={})
    assert school['total_rub'] == 363_533_500
    assert dou['total_rub'] == 68_220_000


def test_missing_selection_is_unknown_despite_an_available_budget():
    cfg = configuration()
    cfg['rows'][0].pop('ncs_table')
    result = benefits.estimate(cfg, inputs={'school_cost_mln_per_place': 3}, tep={})
    assert result['total_rub'] is None and not result['complete']
    assert result['rows'][0]['amount_rub'] is None and 'Выберите' in result['rows'][0]['error']


def test_project_total_is_not_assumed_to_be_the_capacity_of_one_ncs_building():
    cfg = configuration()
    cfg['rows'][0].pop('planned_places')
    result = benefits.estimate(cfg, inputs={'school_places': 1200}, tep={})
    assert result['total_rub'] is None
    assert 'одного здания' in result['rows'][0]['error']


def test_manual_rate_and_its_source_remain_an_explicit_choice():
    cfg = configuration(valuation_mode='manual', rub_per_place=2000000,
                        valuation_basis='Отдельный расчёт по документу')
    result = benefits.estimate(cfg, inputs={'school_cost_mln_per_place': 3}, tep={})
    assert result['total_rub'] == 550_000_000
    assert result['rows'][0]['valuation_basis'] == 'Отдельный расчёт по документу'
    assert 'ncs' not in result['rows'][0]


def test_new_manual_mode_requires_a_source_but_legacy_explicit_rates_still_open():
    cfg = configuration(valuation_mode='manual', rub_per_place=2000000)
    result = benefits.estimate(cfg, inputs={}, tep={})
    assert result['total_rub'] is None and 'источник' in result['rows'][0]['error']
    cfg['rows'][0].pop('valuation_mode')
    assert benefits.estimate(cfg, inputs={}, tep={})['total_rub'] == 550_000_000


@pytest.mark.parametrize('places,expected', [(117, 1534080), (130, 1534080), (1320, 1119400)])
def test_exact_and_ten_percent_edges_use_the_published_point(places, expected):
    assert education_ncs.rate('school', '03-03-001', Decimal(places))['rate'] == expected


@pytest.mark.parametrize('places', [116, 1321, 0, Decimal('125.5')])
def test_unsupported_capacity_needs_a_separate_valuation(places):
    with pytest.raises(ValueError):
        education_ncs.rate('school', '03-03-001', Decimal(places))


def test_kind_and_construction_selection_cannot_be_substituted():
    with pytest.raises(ValueError, match='Выберите'):
        education_ncs.rate('school', '03-01-001', Decimal(250))
    with pytest.raises(ValueError, match='Выберите'):
        education_ncs.rate('school', {'table': '03-03-001'}, Decimal(250))
    exposed = education_ncs.catalog()
    exposed['tables'][0]['points'][0]['thousand_rub_per_place'] = '0'
    assert education_ncs.rate('kindergarten', '03-01-001', Decimal(60))['rate'] == 2131470


def legacy_inputs():
    return {'vri_region': 'mo', 'school_places': 125, 'school_cost_mln_per_place': 3,
            'land_rights_cost_mln': 425, 'mo_vri_compensation_mln': 75,
            'mo_vri_benefits': {'schema': 1,
                'rows': [{'id': 'old', 'kind': 'school', 'required_places': 100}],
                'applied': {'gross_rub': 500_000_000, 'net_mln': 425},
                'result': {'complete': True, 'total_rub': 75_000_000,
                    'rows': [{'id': 'old', 'kind': 'school',
                              'valuation_basis': 'Ставка строительства из проекта'}]}}}


def test_saved_budget_based_application_is_retained_for_reference_and_unapplied():
    inputs = legacy_inputs()
    before = deepcopy(inputs['mo_vri_benefits'])
    update = core.apply_mo_vri_benefits(inputs, {})
    assert inputs['land_rights_cost_mln'] == 500
    assert update['vri']['compensation_rub'] is None
    assert update['vri']['benefits']['total_rub'] is None
    saved = inputs['mo_vri_benefits']
    assert 'applied' not in saved
    assert saved['suspended']['applied'] == before['applied']
    assert saved['suspended']['result'] == before['result']
    assert saved['rows'] == before['rows']
    assert core.apply_mo_vri_benefits(inputs, {}) == {}
    assert core.mo_vri_applied_details(inputs)['benefits']['complete'] is False


def test_user_replaced_fee_is_not_reset_by_the_saved_budget_application():
    inputs = legacy_inputs()
    inputs['land_rights_cost_mln'] = 123
    assert core.apply_mo_vri_benefits(inputs, {}) == {}
    assert inputs['land_rights_cost_mln'] == 123


def test_applied_ncs_valuation_recalculates_capacity_and_ignores_budget():
    cfg = configuration()
    cfg['applied'] = {'gross_rub': 500_000_000, 'net_mln': 136.4665}
    inputs = {'vri_region': 'mo', 'mo_vri_benefits': cfg, 'land_rights_cost_mln': 136.4665}
    first = core.apply_mo_vri_benefits(inputs, {})
    assert first['vri']['compensation_rub'] == 363_533_500
    inputs['school_cost_mln_per_place'] = 100
    assert core.apply_mo_vri_benefits(inputs, {})['vri'] == first['vri']
    inputs['mo_vri_benefits']['rows'][0]['planned_places'] = 800
    assert core.apply_mo_vri_benefits(inputs, {})['vri']['compensation_rub'] == 463_548_000


@pytest.mark.parametrize('legacy', [False, True])
def test_workbook_keeps_the_same_fee_and_valuation_source(legacy):
    if legacy:
        inputs = dict(core.DEFAULT_INPUTS, **legacy_inputs())
        expected, source = 500, 'Для НЦС укажите полную проектную мощность одного здания'
    else:
        cfg = configuration()
        cfg['applied'] = {'gross_rub': 500_000_000, 'net_mln': 136.4665}
        inputs = dict(core.DEFAULT_INPUTS, vri_region='mo', mo_vri_benefits=cfg,
                      land_rights_cost_mln=136.4665)
        expected, source = 136.4665, 'НЦС 81-02-03-2026'
    content, _, _ = core.build_project_workbook(inputs, deepcopy(core.TEP_DEFAULT), [], None,
                                               project_name='Стоимость мест по НЦС', cache_values=False)
    book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    fees = [r[1] for r in book['Вводные'].iter_rows(values_only=True)
            if r and str(r[0] or '').startswith('Плата за изменение ВРИ')]
    assert fees == [expected]
    assert source in ' '.join(str(c or '') for r in book['Источники'].iter_rows(values_only=True) for c in r)
    book.close()
