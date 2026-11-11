"""A nonresidential object's monthly funding never drops dated source payments."""
import copy

import pytest

import developaid_nonres_strategy as nonres
import main_legacy as core
from test_nonres_strategy_switch import _plan
from test_nonres_object_result import _spec


def dated_plan(day,strategy,**params):
    source = _plan(strategy,**params)
    source['commissioning'] = source['commissioning'].replace(day=day)
    source['price_start'] = source['price_start'].replace(day=day)
    source['permit'] = core.d(f'2027-06-{day:02}')
    source['capex'] = {m.replace(day=day):v for m,v in source['capex'].items()}
    when = min(source['capex'])
    source['common_capex'] = {when:10e6}
    if day!=1:
        value = source['capex'][when]
        source['capex'][when] = value*.75
        source['capex'][when.replace(day=1)] = value*.25
        source['common_capex'][when] = 7e6
        source['common_capex'][when.replace(day=1)] = 3e6
    return source


@pytest.mark.parametrize('strategy',['direct','income'])
@pytest.mark.parametrize('exit_mode',['sale','hold'])
def test_object_keeps_all_monthly_money_and_source_commissioning(strategy,exit_mode):
    first = nonres.object_flows(dated_plan(1,strategy,exit_mode=exit_mode),lambda _:0.1,vat_rate=.22)
    source = dated_plan(17,strategy,exit_mode=exit_mode)
    before = copy.deepcopy(source)
    dated = nonres.object_flows(source,lambda _:0.1,vat_rate=.22)
    assert source == before
    assert dated['commissioning'] == source['commissioning']
    assert all(month.day==1 for month in dated['months'])
    for field in ('capex_by_month','common_by_month'):
        assert all(month.day==1 for month in dated[field])
    assert sum(dated['capex_by_month'].values()) == pytest.approx(sum(source['capex'].values()))
    assert sum(dated['common_by_month'].values()) == pytest.approx(sum(source['common_capex'].values()))
    for key in ('capex','revenue','vat_paid','loan_draw','loan_interest','loan_repayment','loan_fee',
                'exit_revenue','residual_value','tax_margin','noi'):
        assert dated['totals'][key] == pytest.approx(first['totals'][key]), key
    assert dated['totals']['loan_draw'] > 0
    first_result = core.object_result(first,start=core.d('2027-01-01'),discount_rate=.2,tax_rate=.25)
    dated_result = core.object_result(dated,start=core.d('2027-01-17'),discount_rate=.2,tax_rate=.25)
    for key in ('profit_tax','npv'):
        assert dated_result[key] == pytest.approx(first_result[key]),key


def test_one_month_direct_sale_releases_credit_and_keeps_raw_date():
    source = dated_plan(17,'direct',direct_sale_offset_months=0,direct_sale_months=1)
    flows = nonres.object_flows(source,lambda _:0.1,vat_rate=.22)
    financing = core.object_financing(flows)
    assert flows['commissioning'] == source['commissioning']
    assert financing['commissioning'] == source['commissioning']
    assert financing['rate_at_commissioning'] > 0
    assert financing['debt_at_commissioning'] == pytest.approx(
        flows['monthly']['loan_balance'].get(core.month_key(source['commissioning']),0))
    assert financing['repaid_total'] > 0
    assert financing['repaid_total'] == pytest.approx(financing['draw_total']+financing['interest_capitalized'])


def test_public_objects_with_their_own_day_seventeen_dates_match_monthly_cash():
    results=[]
    for day in [1,17]:
        raw=f'2028-03-{day:02}'
        inputs,tep=_spec(project_start=f'2027-03-{day:02}',ird_months=12,construction_months=12,
                         offices_start=raw,offices_sales_start=raw,retail_start=raw,retail_sales_start=raw)
        results.append(core.calculate(core.CalcRequest(inputs=inputs,tep=tep,rates=[])))
    first,dated=results
    for field in ('project','equity','profit_tax'):
        assert dated['cashflow'][field] == pytest.approx(first['cashflow'][field]),field
    first_objects={x['key']:x for x in first['finance']['nonres']['objects']}
    for obj in dated['finance']['nonres']['objects']:
        old=first_objects[obj['key']]
        assert core.d(obj['commissioning']).day==17
        assert core.d(obj['financing']['commissioning']).day==17
        assert obj['book']['commissioning'] == obj['commissioning']
        assert sum(row['capex'] for row in obj['book']['months']) == pytest.approx(obj['totals']['capex'])
        for field in ('revenue','loan_draw','loan_interest','loan_repayment','loan_fee','vat_paid','noi'):
            assert obj['totals'][field] == pytest.approx(old['totals'][field]),field
        assert obj['financing']['draw_total'] > 1e6
        assert obj['financing']['rate_at_commissioning'] > 0
