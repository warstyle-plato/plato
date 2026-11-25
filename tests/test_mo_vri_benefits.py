"""Предметные сценарии 1310: ставки МО, порог, отсутствие данных, пересчёт."""
from copy import deepcopy
import pytest
from fastapi import HTTPException
import mo_vri_benefits as benefits
import main_legacy as core


def config(*rows):
    return {'schema': 1, 'rows': [{'id': str(i), **r} for i, r in enumerate(rows)]}


def investment(**changes):
    return {'kind': 'investment', 'object_type': 'hotel_4', 'area_sqm': 10000,
            'index_mode': 'base', **changes}


def test_all_investment_types_have_the_rates_from_the_official_933_table():
    expected = [100000, 90000, 190000, 110000, 180000, 240000, 120000, 90000, 110000, 60000]
    assert [r['rub_per_sqm'] for r in benefits.catalog()['investment_types']] == expected
    for key, rate in zip(benefits.INVESTMENT_TYPES, expected):
        result = benefits.estimate(config(investment(object_type=key)), inputs={}, tep={})
        assert result['complete'] and result['total_rub'] == 10000 * rate
        assert result['rows'][0]['source'] == benefits.RATE_SOURCE


def test_indexed_hotel_and_municipality_uplift_are_explicit_and_do_not_use_old_point_eight():
    row = investment(index_mode='indexed', price_index=1.025, index_basis='Росстат, сентябрь 2026',
                     municipality_uplift=True, uplift_basis='Подтверждённый муниципалитет, перечень 151/2004-ОЗ')
    result = benefits.estimate(config(row), inputs={}, tep={})
    assert result['total_rub'] == 2_214_000_000
    row.pop('index_basis')
    result = benefits.estimate(config(row), inputs={}, tep={})
    assert result['total_rub'] is None and not result['complete']
    assert 'источник' in result['rows'][0]['error']


@pytest.mark.parametrize('planned,eligible,amount', [(110, 0, 0), (111, 11, 33000000), (125, 25, 75000000)])
def test_social_surplus_requires_strictly_more_than_ten_percent(planned, eligible, amount):
    result = benefits.estimate(config({'kind': 'school', 'required_places': 100, 'rub_per_place': 3000000}),
                               inputs={'school_places': planned, 'school_cost_mln_per_place': 3}, tep={})
    row = result['rows'][0]
    assert row['eligible_places'] == eligible and result['total_rub'] == amount
    if amount:
        assert row['valuation_basis'] == 'Ставка места введена пользователем'
        assert 'Предварительно' in ' '.join(row['notes'])


def test_agreed_eligible_capacity_and_rate_replace_project_estimate():
    result = benefits.estimate(config({'kind': 'school', 'required_places': 100, 'planned_places': 125,
                                       'eligible_places': 15, 'rub_per_place': 2000000}), inputs={}, tep={})
    assert result['total_rub'] == 30_000_000


def test_missing_data_stays_missing_and_cannot_be_hidden_by_another_known_row():
    result = benefits.estimate(config(investment(), {'kind': 'resettlement'}), inputs={}, tep={})
    assert result['total_rub'] is None
    assert result['known_subtotal_rub'] == 1_800_000_000
    assert result['rows'][1]['amount_rub'] is None


def test_resettlement_uses_only_the_exact_municipality_price():
    cfg = config({'kind': 'resettlement', 'area_sqm': 5000, 'district': 'Тест'})
    prices = {'Тест': {'price': 200000, 'basis': 'округ', 'document': 'КЦТ, дата'}}
    result = benefits.estimate(cfg, inputs={}, tep={}, market_prices=prices)
    assert result['total_rub'] == 1_000_000_000
    prices['Тест']['basis'] = 'среднее по области'
    result = benefits.estimate(cfg, inputs={}, tep={}, market_prices=prices)
    assert result['total_rub'] is None


def test_duplicate_social_capacity_and_row_ids_cannot_reduce_the_fee_twice():
    row = {'kind': 'school', 'required_places': 100, 'planned_places': 125, 'rub_per_place': 1}
    result = benefits.estimate(config(row, row), inputs={}, tep={})
    assert not result['complete'] and result['total_rub'] is None
    cfg = config(investment(), investment())
    cfg['rows'][1]['id'] = cfg['rows'][0]['id']
    with pytest.raises(ValueError, match='идентификатор'):
        benefits.estimate(cfg, inputs={}, tep={})


@pytest.mark.parametrize('value', [True, -1, 'nan', 'inf', [], {}, '1e25', '1e309'])
def test_malformed_or_negative_area_is_not_a_zero_benefit(value):
    result = benefits.estimate(config(investment(area_sqm=value)), inputs={}, tep={})
    assert result['total_rub'] is None and not result['complete']


def test_malformed_category_is_a_validation_error_not_an_unhandled_exception():
    with pytest.raises(ValueError, match='основание'):
        benefits.estimate(config({'kind': []}), inputs={}, tep={})
    result = benefits.estimate(config(investment(object_type=[])), inputs={}, tep={})
    assert result['total_rub'] is None and not result['complete']


def test_route_computes_the_sum_on_the_server_and_can_estimate_without_a_vri_fee(monkeypatch):
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **k: None)
    cfg = config(investment())
    req = core.MoVriCompensationRequest(inputs={'vri_region': 'mo'}, benefits=cfg)
    result = core.mo_vri_compensation_preview(req)
    assert result['vri'] is None and result['benefits']['total_rub'] == 1_800_000_000
    req.payment_before_compensation_rub = 2_000_000_000
    req.compensation_rub = 1  # ручная сумма не складывается с оценкой
    result = core.mo_vri_compensation_preview(req)
    assert result['vri']['payment_used_rub'] == 200_000_000
    assert result['vri']['compensation_rub'] == 1_800_000_000


def test_an_applied_social_estimate_recalculates_from_the_original_fee_without_freezing():
    cfg = config({'kind': 'school', 'required_places': 100, 'rub_per_place': 3000000})
    cfg['applied'] = {'gross_rub': 500_000_000, 'net_mln': 425}
    inputs = {'vri_region': 'mo', 'mo_vri_benefits': cfg, 'school_places': 125,
              'school_cost_mln_per_place': 3, 'land_rights_cost_mln': 425}
    before = deepcopy(cfg)
    inputs['school_places'] = 130
    update = core.apply_mo_vri_benefits(inputs, {})
    assert update['vri']['compensation_rub'] == 90_000_000
    assert inputs['land_rights_cost_mln'] == 410
    again = core.apply_mo_vri_benefits(inputs, {})
    assert again['vri']['payment_used_rub'] == 410_000_000
    assert cfg == before  # входная конфигурация не изменяется по ссылке
    inputs['school_places'] = 110
    core.apply_mo_vri_benefits(inputs, {})
    assert inputs['land_rights_cost_mln'] == 500
    assert core.mo_vri_applied_details(inputs)['benefits']['total_rub'] == 0
    inputs['land_rights_cost_mln'] = 123
    assert core.apply_mo_vri_benefits(inputs, {}) == {}  # осознанный ручной ввод


def test_queue_fee_is_not_reduced_by_master_obligations_again():
    inputs = {'vri_region': 'mo', 'mo_vri_benefits': {'schema': 1, 'applied': {}},
              '_vri_relief_applied_at_project': True}
    assert core.apply_mo_vri_benefits(inputs, {}) == {}


def test_unknown_housing_does_not_turn_the_whole_school_into_a_benefit():
    result = core.mo_vri_benefit_estimate(config({'kind': 'school'}),
        {'school_places': 125, 'school_cost_mln_per_place': 3}, {})
    assert not result['complete'] and result['total_rub'] is None
    assert 'потребность' in result['rows'][0]['error']


def test_automatic_recalculation_also_checks_resettlement_double_credit():
    cfg = config({'kind': 'resettlement', 'area_sqm': 100, 'rub_per_sqm': 200000})
    cfg['applied'] = {'gross_rub': 100_000_000, 'net_mln': 80}
    inputs = {'vri_region': 'mo', 'mo_vri_benefits': cfg, 'land_rights_cost_mln': 80,
              'vri_transfer_offset_mln': 10}
    with pytest.raises(HTTPException) as error:
        core.apply_mo_vri_benefits(inputs, {})
    assert error.value.status_code == 422
    cfg['separate_transfer_offset'] = True
    assert core.apply_mo_vri_benefits(inputs, {})['vri']['payment_used_rub'] == 80_000_000


def test_book_receives_the_recalculated_fee_and_the_object_valuation():
    import io
    from openpyxl import load_workbook
    cfg = config(investment(area_sqm=5000))
    cfg['applied'] = {'gross_rub': 1_900_000_000, 'net_mln': 100}
    inputs = dict(core.DEFAULT_INPUTS, vri_region='mo', mo_vri_benefits=cfg,
                  land_rights_cost_mln=100)
    content, _, _ = core.build_project_workbook(inputs, deepcopy(core.TEP_DEFAULT), [], None,
                                               project_name='Оценка льготы 1310', cache_values=False)
    book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    fee_rows = [row for row in book['Вводные'].iter_rows(values_only=True)
                if row and str(row[0] or '').startswith('Плата за изменение ВРИ')]
    assert len(fee_rows) == 1 and fee_rows[0][1] == 1000
    source = ' '.join(str(cell.value or '') for row in book['Источники'].iter_rows() for cell in row)
    assert 'Гостиница 4★' in source and '180000' in source and '933-ПП' in source
    assert 'Предварительная оценка' in source and 'вписанную пользователем' not in source


def test_route_rejects_a_possible_double_credit_for_resettlement(monkeypatch):
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **k: None)
    req = core.MoVriCompensationRequest(payment_before_compensation_rub=100_000_000,
        inputs={'vri_region': 'mo', 'vri_transfer_offset_mln': 30},
        benefits=config({'kind': 'resettlement', 'area_sqm': 100, 'rub_per_sqm': 200000}))
    with pytest.raises(HTTPException) as error:
        core.mo_vri_compensation_preview(req)
    assert error.value.status_code == 422
