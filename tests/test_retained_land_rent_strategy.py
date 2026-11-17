"""Incurred rent, seller payments and buyer valuation have separate clocks."""
from copy import deepcopy
from datetime import date

import pytest

import developaid_finance_math as fm
import developaid_hotel_strategy as hotel
import developaid_nonres_strategy as nonres


OPEN = date(2030, 1, 1)
PREPAY = date(2028, 1, 1)


def series(start, count, amount):
    return {hotel.add_months(start, index): amount for index in range(count)}


def office_plan(**changes):
    plan = {
        'strategy': 'income', 'commissioning': OPEN,
        'capex': {date(2029, 1, 1): 100_000_000},
        'area_sqm': 1000, 'parking_spaces': 0,
        'params': {'hold_years': 2, 'exit_mode': 'sale', 'exit_cap_pct': 10,
                   'exit_cost_pct': 0, 'rent_th_per_sqm_month': 1,
                   'occupancy_start_pct': 100, 'occupancy_stable_pct': 100,
                   'leaseup_months': 1, 'rent_index_pct': 0, 'opex_pct': 20,
                   'loan_share_pct': 0, 'loan_fee_pct': 0,
                   'property_tax_pct': 2.2, 'depreciation_years': 30},
    }
    plan.update(changes)
    return plan


def hotel_plan(**changes):
    plan = {
        'commissioning': OPEN, 'start': date(2027, 1, 1),
        'capex': {date(2029, 1, 1): 100_000_000},
        'capex_land': {date(2029, 1, 1): 10_000_000},
        'capex_ffe': {date(2029, 1, 1): 10_000_000},
        'params': {
            'keys': 50, 'adr_rub': 12_000, 'adr_price_date': '2030-01-01',
            'index_pct': 0, 'occ_start_pct': 70, 'occ_target_pct': 70,
            'ramp_months': 1, 'fnb_pct': 0, 'other_pct': 0,
            'rooms_cost_pct': 10, 'fnb_cost_pct': 0, 'other_cost_pct': 0,
            'ag_pct': 0, 'sm_pct': 0, 'pom_pct': 0, 'utilities_pct': 0,
            'base_fee_pct': 0, 'incentive_fee_pct': 0, 'ffe_reserve_pct': 0,
            'insurance_pct': .1, 'hold_years': 2, 'financing': 'none',
            'exit_mode': 'sale', 'valuation': 'cap_rate', 'exit_cap_pct': 10,
            'exit_cost_pct': 0, 'property_tax_pct': 2.2,
        },
    }
    plan.update(changes)
    return plan


def run(kind, plan):
    if kind == 'office':
        return nonres.object_flows(plan, lambda month: .10, vat_rate=.22)
    return hotel.hotel_flows(plan, lambda month: .10, vat_rate=.22,
                            profit_tax_rate=.25, discount_rate=.15)


def fixture(kind, *, cash=None, valuation=None):
    plan = office_plan() if kind == 'office' else hotel_plan()
    paid = series(OPEN, 24, 100_000)
    value = {**paid, **series(date(2032, 1, 1), 12, 200_000)}
    plan.update(land_rent_operating=paid,
                land_rent_operating_cash=paid if cash is None else cash,
                land_rent_valuation=value if valuation is None else valuation)
    return plan


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_operating_land_rent_does_not_become_property_or_construction_loan(kind):
    base_plan = office_plan() if kind == 'office' else hotel_plan()
    before = run(kind, base_plan)
    plan = fixture(kind)
    original = deepcopy(plan)
    after = run(kind, plan)
    assert plan == original
    assert after['totals']['capex'] == before['totals']['capex']
    if kind == 'office':
        assert after['cost_basis'] == before['cost_basis']
        assert after['monthly']['cost_recognized'] == before['monthly']['cost_recognized']
        assert after['kpi']['cost_total'] == before['kpi']['cost_total']
    else:
        for field in ('building_net', 'ffe_net', 'capex_net', 'capex_vat', 'land'):
            assert after['kpi'][field] == before['kpi'][field]
        for field in ('depreciation', 'insurance'):
            assert after['monthly'][field] == before['monthly'][field]
    assert after['monthly']['property_tax'] == before['monthly']['property_tax']
    assert after['totals']['loan_draw'] == before['totals']['loan_draw']
    assert after['totals']['land_rent_operating'] == pytest.approx(2_400_000)
    assert after['totals']['opex'] - before['totals']['opex'] == pytest.approx(2_400_000)


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_prepayment_changes_cash_timing_not_accrual_noi_or_tax(kind):
    monthly = run(kind, fixture(kind))
    prepaid = run(kind, fixture(kind, cash={PREPAY: 2_400_000}))
    assert prepaid['monthly']['opex'] == monthly['monthly']['opex']
    assert prepaid['monthly']['tax_margin'] == monthly['monthly']['tax_margin']
    assert prepaid['monthly']['land_rent_operating'] == monthly['monthly']['land_rent_operating']
    assert prepaid['monthly']['land_rent_operating_cash'] == {PREPAY: 2_400_000}
    assert prepaid['monthly']['cash_to_equity'][PREPAY] == pytest.approx(-2_400_000)
    assert PREPAY not in prepaid['monthly']['land_rent_operating']
    assert prepaid['monthly']['cash_to_equity'][OPEN] - monthly['monthly']['cash_to_equity'][OPEN] == pytest.approx(100_000)
    assert prepaid['monthly']['operating_cash_before_tax'][OPEN] - monthly['monthly']['operating_cash_before_tax'][OPEN] == pytest.approx(100_000)
    assert prepaid['totals']['land_rent_operating_cash'] == pytest.approx(2_400_000)
    if kind == 'hotel':
        assert prepaid['monthly']['ebitda'] == monthly['monthly']['ebitda']
        assert prepaid['monthly']['profit_tax'] == monthly['monthly']['profit_tax']
        assert prepaid['kpi']['npv_project'] < monthly['kpi']['npv_project']
    else:
        assert prepaid['totals']['noi'] == monthly['totals']['noi']


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_buyer_forward_rent_reduces_valuation_without_becoming_seller_cash(kind):
    base = run(kind, office_plan() if kind == 'office' else hotel_plan())
    result = run(kind, fixture(kind))
    forward = 'forward_noi' if kind == 'office' else 'forward_ebitda'
    assert base['kpi'][forward] - result['kpi'][forward] == pytest.approx(2_400_000)
    assert base['kpi']['exit_value'] - result['kpi']['exit_value'] == pytest.approx(24_000_000)
    assert result['kpi']['exit_value_complete']
    assert max(result['months']) == date(2031, 12, 1)
    assert all(month <= date(2031, 12, 1) for month in result['monthly']['land_rent_operating_cash'])
    assert result['totals']['land_rent_operating_cash'] == pytest.approx(2_400_000)
    assert sum(result['land_rent_valuation'].values()) == pytest.approx(4_800_000)


def test_office_stabilized_noi_uses_its_own_service_year():
    base = run('office', office_plan())
    result = run('office', fixture('office'))
    assert base['kpi']['stabilized_noi'] - result['kpi']['stabilized_noi'] == pytest.approx(1_200_000)
    assert base['kpi']['forward_noi'] - result['kpi']['forward_noi'] == pytest.approx(2_400_000)


def test_accrual_rent_deducts_profit_tax_in_its_service_quarter():
    before = run('office', office_plan())
    after = run('office', fixture('office', cash={PREPAY: 2_400_000}))
    before_tax = fm.profit_tax_schedule(before['months'], before['monthly']['tax_margin'], {}, OPEN, .25)[0]
    after_tax = fm.profit_tax_schedule(after['months'], after['monthly']['tax_margin'], {}, OPEN, .25)[0]
    quarter = [date(2030, month, 1) for month in (1, 2, 3)]
    assert sum(before_tax.get(month, 0) - after_tax.get(month, 0)
               for month in quarter) == pytest.approx(75_000)
    assert after_tax.get(PREPAY, 0) == 0


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_missing_valuation_series_does_not_claim_a_complete_exit_value(kind):
    plan = fixture(kind)
    del plan['land_rent_valuation']
    result = run(kind, plan)
    assert result['land_rent_valuation_complete'] is False
    assert result['kpi']['exit_value_complete'] is False
    assert any('оценки стоимости выхода' in reason for reason in result['warnings'])


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_missing_payment_series_is_not_a_known_zero_payment(kind):
    plan = fixture(kind)
    del plan['land_rent_operating_cash']
    result = run(kind, plan)
    assert result['land_rent_operating_cash_complete'] is False
    assert any('Денежный график операционной аренды' in reason for reason in result['warnings'])


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_explicit_zero_cash_and_valuation_are_preserved_as_answers(kind):
    result = run(kind, fixture(kind, cash={}, valuation={}))
    assert result['land_rent_operating_cash_complete'] is True
    assert result['land_rent_valuation_complete'] is True
    assert result['totals']['land_rent_operating_cash'] == 0
    assert result['totals']['land_rent_operating'] == 2_400_000


@pytest.mark.parametrize('kind', ['office', 'hotel'])
@pytest.mark.parametrize('field,flag', [
    ('land_rent_operating', 'land_rent_operating_complete'),
    ('land_rent_operating_cash', 'land_rent_operating_cash_complete'),
    ('land_rent_valuation', 'land_rent_valuation_complete'),
])
def test_a_null_owner_series_is_unknown_instead_of_known_empty(kind, field, flag):
    plan = fixture(kind)
    plan[field] = None
    assert run(kind, plan)[flag] is False


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_parent_qualification_of_partial_future_rent_is_preserved(kind):
    plan = fixture(kind)
    plan.update(land_rent_valuation_complete=False,
                land_rent_valuation_missing=['Будущая кадастровая стоимость не определена.'])
    result = run(kind, plan)
    assert result['kpi']['exit_value_complete'] is False
    assert 'Будущая кадастровая стоимость не определена.' in result['warnings']


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_advance_operating_rent_does_not_expand_construction_draws(kind):
    monthly_plan = fixture(kind)
    if kind == 'office':
        monthly_plan['params'].update(loan_share_pct=60, debt_repayment='sweep')
    else:
        monthly_plan['params'].update(financing='commercial', loan_share_pct=60)
    prepaid_plan = deepcopy(monthly_plan)
    prepaid_plan['land_rent_operating_cash'] = {PREPAY: 2_400_000}
    monthly, prepaid = run(kind, monthly_plan), run(kind, prepaid_plan)
    assert prepaid['monthly']['loan_draw'] == monthly['monthly']['loan_draw']
    assert prepaid['monthly']['loan_interest_cap'] == monthly['monthly']['loan_interest_cap']
    assert not any(month > OPEN for month in prepaid['monthly']['loan_draw'])
    assert prepaid['monthly']['opex'] == monthly['monthly']['opex']
    assert prepaid['monthly']['loan_balance'][OPEN] < monthly['monthly']['loan_balance'][OPEN]
    assert prepaid['monthly']['opex_cash'][PREPAY] == 2_400_000
    assert monthly['monthly']['opex_cash'].get(PREPAY, 0) == 0


def test_hotel_annual_usali_keeps_incurred_rent_and_paid_cash_separate():
    result = run('hotel', fixture('hotel', cash={PREPAY: 2_400_000}))
    annual = {row['year']: row for row in result['annual']}
    assert annual[2028]['land_rent_operating_cash'] == 2_400_000
    assert annual[2028]['land_rent_operating'] == 0
    assert annual[2030]['land_rent_operating'] == 1_200_000
    assert annual[2030]['land_rent_operating_cash'] == 0


def test_gordon_keeps_recurring_rent_in_normalized_valuation_after_prepayment():
    monthly_plan = fixture('hotel')
    monthly_plan['params'].update(valuation='gordon', exit_mode='hold',
                                  gordon_growth_pct=2, gordon_rate_pct=15)
    prepaid_plan = deepcopy(monthly_plan)
    prepaid_plan['land_rent_operating_cash'] = {PREPAY: 2_400_000}
    monthly, prepaid = run('hotel', monthly_plan), run('hotel', prepaid_plan)
    assert prepaid['kpi']['exit_value'] == pytest.approx(monthly['kpi']['exit_value'])
    assert prepaid['kpi']['npv_project'] < monthly['kpi']['npv_project']


@pytest.mark.parametrize('kind', ['office', 'hotel'])
@pytest.mark.parametrize('paid', [date(2032, 6, 1), date(2033, 1, 1)])
def test_late_seller_liability_extends_cash_only_without_buyer_cash_or_asset_cost(kind, paid):
    monthly = run(kind, fixture(kind))
    late = run(kind, fixture(kind, cash={paid: 2_400_000}))
    assert late['horizon_end'] == monthly['horizon_end']
    assert late['kpi']['exit_month'] == monthly['kpi']['exit_month']
    assert late['kpi']['exit_value'] == monthly['kpi']['exit_value']
    forward = 'forward_noi' if kind == 'office' else 'forward_ebitda'
    assert late['kpi'][forward] == monthly['kpi'][forward]
    assert late['cash_horizon_end'] == paid
    assert max(late['months']) == paid
    assert late['totals']['land_rent_operating_cash'] == 2_400_000
    assert late['monthly']['land_rent_operating_cash'] == {paid: 2_400_000}
    assert late['monthly']['cash_to_equity'][paid] == -2_400_000
    assert late['monthly']['opex'] == monthly['monthly']['opex']
    assert late['monthly']['property_tax'] == monthly['monthly']['property_tax']
    assert late['monthly']['loan_draw'] == monthly['monthly']['loan_draw']
    basis_expense = 'cost_recognized' if kind == 'office' else 'depreciation'
    assert late['monthly'][basis_expense] == monthly['monthly'][basis_expense]
    assert not any(month > monthly['horizon_end'] for month in late['monthly'][basis_expense])


def test_cash_tail_does_not_depreciate_retained_office_after_asset_horizon():
    monthly_plan = fixture('office')
    monthly_plan['params']['exit_mode'] = 'hold'
    late_plan = deepcopy(monthly_plan)
    late_plan['land_rent_operating_cash'] = {date(2033, 1, 1): 2_400_000}
    monthly, late = run('office', monthly_plan), run('office', late_plan)
    assert late['monthly']['cost_recognized'] == monthly['monthly']['cost_recognized']
    assert late['monthly']['residual_value'] == monthly['monthly']['residual_value']


@pytest.mark.parametrize('kind', ['office', 'hotel'])
def test_actual_commissioning_date_preserved_while_monthly_cash_uses_first_day(kind):
    plan = fixture(kind)
    plan['commissioning'] = date(2030, 1, 17)
    plan['start'] = date(2027, 1, 17)
    result = run(kind, plan)
    assert result['commissioning'] == date(2030, 1, 17)
    assert result['horizon_end'] == date(2031, 12, 1)
    assert result['kpi']['exit_month'] == date(2031, 12, 1)
    assert result['monthly']['land_rent_operating'][OPEN] == 100_000
    assert result['totals']['land_rent_operating'] == 2_400_000
    assert all(month.day == 1 for month in result['months'])
    assert result['monthly']['exit_revenue'][date(2031, 12, 1)] > 0


def test_advance_sale_first_bucket_does_not_drop_midmonth_source_money():
    plan = office_plan(strategy='direct', commissioning=date(2030, 1, 17),
                       capex={}, price_rub_sqm=100_000)
    plan['params'].update(direct_sale_offset_months=-3, direct_sale_months=1)
    result = run('office', plan)
    assert result['commissioning'] == date(2030, 1, 17)
    assert result['months'][0] == date(2029, 10, 1)
    assert result['totals']['sale_revenue'] == 100_000_000
    assert result['monthly']['cash_to_equity'][date(2029, 10, 1)] > 0
