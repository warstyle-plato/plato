"""Calendar buckets conserve money while contractual event dates keep their day."""
import copy
from datetime import date, datetime

import pytest

import developaid_actuals as actuals
import main_legacy as core


def case(day=17, **overrides):
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(project_start=f'2027-03-{day:02}', ird_months=12,
                  construction_months=12, **overrides)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return inputs, tep


def calculate(day=17, **overrides):
    inputs, tep = case(day, **overrides)
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


@pytest.fixture(scope='module')
def pair():
    return calculate(1), calculate(17)


def test_monthly_sum_preserves_collisions_refunds_and_business_dates():
    values = {date(2027,3,1):100., date(2027,3,17):25.,
              date(2027,3,31):-7., date(2027,4,17):9.}
    before = dict(values)
    result = core.monthly_sum(values)
    assert result == {date(2027,3,1):118.,date(2027,4,1):9.}
    assert sum(result.values()) == sum(values.values())
    assert values == before
    assert core.d('2027-03-17') == date(2027,3,17)
    assert core.add_months('2027-03-17',1) == date(2027,4,17)
    assert core.month_key(datetime(2027,3,17,12,30)) == date(2027,3,1)


def test_operating_series_use_one_calendar_without_moving_milestones():
    inputs, tep = case()
    op = core.build_operating_model(inputs,tep,[])
    for field in ('project_start','permit','sales_start','rve','social_cash_date'):
        assert op[field].day == 17, field
    for field in ('revenue','capex','debt_capex','operating','vri_equity'):
        assert all(month.day == 1 for month in op[field]), field
    for field in ('capex_by_article','revenue_product_schedules','quantity_product_schedules'):
        assert all(month.day == 1 for series in op[field].values() for month in series), field
    first_inputs, first_tep = case(1)
    first = core.build_operating_model(first_inputs,first_tep,[])
    for field in ('revenue','capex','debt_capex','operating','vri_equity'):
        assert sum(op[field].values()) == pytest.approx(sum(first[field].values())), field
    for article, series in op['capex_by_article'].items():
        assert sum(series.values()) == pytest.approx(sum(first['capex_by_article'][article].values())), article


def test_day_seventeen_retains_financing_interest_disclosure_and_cash(pair):
    first, seventeenth = pair
    for field in ('peak_bridge','peak_pf','peak_escrow','bridge_draw_total','pf_draw_total',
                  'bridge_interest','pf_interest','financing_cost','rve_escrow_release','vat',
                  'profit_tax','financing_tax_deductions'):
        assert seventeenth['finance'][field] == pytest.approx(first['finance'][field]), field
    assert seventeenth['finance']['peak_bridge'] > 1e6
    assert seventeenth['finance']['rve_escrow_release'] > 1e6
    for field in ('project','equity','profit_tax'):
        assert seventeenth['cashflow'][field] == pytest.approx(first['cashflow'][field]), field
    for field in ('project_start','permit','sales_start','rve','social_cash'):
        assert core.d(seventeenth['dates'][field]).day == 17, field
    assert seventeenth['finance']['escrow_cover']['rve'] == seventeenth['dates']['rve']


def test_cash_conservation_includes_vat_tax_and_finance(pair):
    _, result = pair
    inputs, tep = case()
    op = core.build_operating_model(inputs,tep,[])
    finance = result['finance']
    base_cash = (sum(op['revenue'].values()) - sum(op['capex'].values())
                 - sum(op['operating'].values()) - finance['vat']
                 - sum(result['cashflow']['profit_tax']))
    assert sum(result['cashflow']['project']) == pytest.approx(base_cash,abs=.01)
    rows = finance['rows']
    debt_cash = sum(row['bridge_draw']+row['pf_draw']-row['bridge_repayment']-row['pf_repayment'] for row in rows)
    paid_finance = sum(row['interest_payment'] for row in rows)+finance['bridge_fee']+finance['pf_reservation_fee']
    assert sum(result['cashflow']['equity']) == pytest.approx(base_cash+debt_cash-paid_finance,abs=.01)
    assert sum(float(v) for v in finance['vat_ddu_schedule'].values()) == pytest.approx(finance['vat'])


def test_first_day_actuals_replace_seventeenth_day_plan_without_double_count(pair):
    inputs, tep = case()
    op = core.build_operating_model(inputs,tep,[])
    cut = date(2028,3,1)
    fact = {month.isoformat():value for month,value in op['capex'].items() if month<cut}
    overlaid = actuals.overlay(op,{'cut':cut.isoformat(),'capex':fact})['op']
    assert sum(overlaid['capex'].values()) == pytest.approx(sum(op['capex'].values()))
    assert {m:v for m,v in overlaid['capex'].items() if m<cut} == {core.d(m):v for m,v in fact.items()}
    assert all(month.day==1 for month in overlaid['capex'])
    result = core.calculate(core.CalcRequest(inputs=inputs,tep=tep,rates=[],actuals={'cut':cut.isoformat(),'capex':fact}))
    assert result['cashflow']['project'] == pytest.approx(pair[1]['cashflow']['project'])
    assert result['finance']['financing_cost'] == pytest.approx(pair[1]['finance']['financing_cost'])


def test_dated_queue_cash_and_sweeps_keep_every_amount_in_the_month(pair):
    result = calculate(_phase_project_cash_funds_costs=True,
                       _phase_project_cash_schedule={'2027-03-01':1e6,'2027-03-17':2e6})
    assert result['finance']['project_cash_used'] == pytest.approx(3e6)
    assert pair[1]['finance']['bridge_draw_total']-result['finance']['bridge_draw_total'] == pytest.approx(3e6)
    swept = calculate(_phase_bank_sweep_schedule={'2028-03-01':1e6,'2028-03-17':2e6})
    assert swept['finance']['project_cash_sweep'] == pytest.approx(3e6)


@pytest.mark.parametrize('day',[1,17])
def test_queue_tax_recognition_uses_rve_month_while_date_remains_exact(day):
    result = {'dates':{'rve':'2029-03-17'},'finance':{'rows':[
        {'month':f'2029-02-{day:02}','taxable_margin':100.,'financing_tax_deduction':3.},
        {'month':f'2029-03-{day:02}','taxable_margin':25.,'financing_tax_deduction':2.}]}}
    assert core._phase_margins_at_own_rve([result]) == {date(2029,3,1):125.}
    assert core._phase_recognized_base(result) == {'2029-02-01':-3.,'2029-03-01':123.}
    assert result['dates']['rve'] == '2029-03-17'


def test_nonres_aggregate_joins_keep_object_money_on_the_project_axis():
    from test_nonres_object_result import _spec
    inputs, tep = _spec(project_start='2027-03-17',ird_months=12,construction_months=12)
    result = core.calculate(core.CalcRequest(inputs=inputs,tep=tep,rates=[]))
    finance = result['finance']
    totals = finance['nonres']['totals']
    for field in ('nonres_revenue','nonres_costs','nonres_loan_draw','nonres_loan_interest',
                  'nonres_loan_repayment','nonres_cash_to_equity'):
        assert totals[field] != 0, field
        assert sum(row[field] for row in finance['rows']) == pytest.approx(totals[field]), field
    prepared = core.prepared_calculation(inputs,tep,[])
    op = core.build_operating_model(prepared['x'],prepared['t'],prepared['rates'])
    expected = {key:plan['commissioning'].isoformat() for key,plan in op['nonres_plans'].items()}
    assert {item['key']:item['commissioning'] for item in finance['nonres']['objects']} == expected
    assert core.d(result['dates']['rve']).day == 17
