"""The hotel calendar includes every dated amount without moving source events."""
import copy
from datetime import date

import pytest

import developaid_hotel_strategy as hotel
import hotel_presets
import main_legacy as core
from test_hotel_strategy import plan, run


def dated_plan(day, **params):
    source = plan()
    source['params'].update(params)
    source['start'] = source['start'].replace(day=day)
    source['commissioning'] = source['commissioning'].replace(day=day)
    for field in ('capex','capex_ffe','capex_land'):
        source[field] = {when.replace(day=day):amount for when,amount in source[field].items()}
    # Two legitimate payments in the same month must be added, never overwritten.
    when = min(source['capex'])
    if day != 1:
        amount = source['capex'][when]
        source['capex'][when] = amount*.75
        source['capex'][when.replace(day=1)] = amount*.25
    return source


@pytest.mark.parametrize('exit_mode',['sale','hold'])
@pytest.mark.parametrize('financing',['commercial','none'])
def test_hotel_dated_money_matches_the_same_monthly_economics(exit_mode,financing):
    first = run(dated_plan(1,exit_mode=exit_mode,financing=financing))
    source = dated_plan(17,exit_mode=exit_mode,financing=financing)
    before = copy.deepcopy(source)
    dated = run(source)
    assert source == before
    assert dated['commissioning'] == source['commissioning']
    assert all(month.day==1 for month in dated['months'])
    assert all(month.day==1 for series in dated['monthly'].values() for month in series)
    assert sum(dated['monthly']['capex'].values()) == pytest.approx(sum(source['capex'].values()))
    for key in ('capex','revenue','vat_refund','profit_tax','loan_draw','loan_interest',
                'loan_repayment','exit_revenue','residual_value','cash_to_equity'):
        assert dated['totals'][key] == pytest.approx(first['totals'][key]), key
    assert dated['kpi']['exit_value'] == pytest.approx(first['kpi']['exit_value'])
    assert dated['project_cf'] == pytest.approx(first['project_cf'])
    assert dated['equity_cf'] == pytest.approx(first['equity_cf'])
    if financing == 'commercial':
        assert dated['totals']['loan_draw'] > 0


def test_hotel_last_month_keeps_a_payment_after_the_first_day():
    source = dated_plan(17)
    end = hotel.plan_horizon_end(source)
    source['capex'][end.replace(day=17)] = 123456.
    source['capex'][hotel.add_months(end,1)] = 98765.
    result = run(source)
    assert result['monthly']['capex'][end] == 123456.
    assert result['totals']['capex'] == pytest.approx(sum(source['capex'].values())-98765.)
    assert result['warnings']


def test_public_hotel_cash_and_native_book_inputs_conserve_day_seventeen():
    results = []
    for day in [1,17]:
        inputs = hotel_presets.apply_preset(copy.deepcopy(core.DEFAULT_INPUTS),'hotel1')
        inputs.update(project_kind='hotel',project_start=f'2027-03-{day:02}',ird_months=12,construction_months=12)
        result = core.calculate(core.CalcRequest(inputs=inputs,tep=copy.deepcopy(core.TEP_DEFAULT),rates=[]))
        results.append(result)
    first, dated = results
    book = dated['finance']['hotel']['book']
    assert core.d(book['start']).day == 17
    assert core.d(book['commissioning']).day == 17
    assert sum(row['capex'] for row in book['months']) == pytest.approx(dated['capex']['total'])
    for field in ('project','equity','profit_tax'):
        assert dated['cashflow'][field] == pytest.approx(first['cashflow'][field]), field
    for field in ('capex','profit_tax','loan_drawn','exit_value'):
        assert dated['finance']['hotel']['kpi'][field] == pytest.approx(first['finance']['hotel']['kpi'][field]), field
    assert dated['finance']['hotel']['kpi']['loan_drawn'] > 0
    assert dated['finance']['hotel']['kpi']['profit_tax'] > 0
    assert dated['dates']['rve'] == '2029-03-17'
