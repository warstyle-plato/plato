"""Product, period and cash reconciliation of office disclosures."""
import copy
import io
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_nonres_debt_metric import _nonres_inputs, core


def run(strategy='direct', **over):
    x, t = _nonres_inputs(offices_strategy=strategy,
        offices_parking_under_price_mln_per_space=3,
        offices_parking_over_price_mln_per_space=2, **over)
    r = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    return x, t, r, r['report']['office_results']


@pytest.mark.parametrize('strategy', ['direct', 'ddu', 'income'])
def test_products_and_periods_reconcile_to_authoritative_cash(strategy):
    _, _, r, d = run(strategy)
    assert d['reconciliation_gap'] == pytest.approx(0, abs=.01)
    assert sum(p['revenue'] for p in d['products']) + d['valuation'] == pytest.approx(r['summary']['revenue'])
    assert sum(p['share'] for p in d['products']) == pytest.approx(1)
    for p in d['products']:
        rows = p['rows']
        if not rows or p['strategy'] == 'Аренда':
            continue
        assert sum(row['quantity'] for row in rows) == pytest.approx(p['quantity'])
        assert sum(row['revenue'] for row in rows) == pytest.approx(p['revenue'])
        assert rows[-1]['remaining'] == pytest.approx(0, abs=1e-8)
        assert p['average_price'] == pytest.approx(p['revenue'] / p['quantity'])
    if strategy == 'direct':
        authoritative = {row['month'][:7]: row['nonres_revenue'] for row in r['finance']['rows']}
        for month in {row['month'] for p in d['products'] for row in p['rows']}:
            assert sum(row['revenue'] for p in d['products'] for row in p['rows'] if row['month'] == month) == pytest.approx(authoritative[month])


@pytest.mark.parametrize('strategy', ['direct','ddu'])
def test_parking_types_prices_and_guests_are_real_model_categories(strategy):
    _, _, _, d = run(strategy)
    under, over = [p for p in d['products'] if ':parking:' in p['key']]
    assert (under['quantity'], over['quantity']) == (180,36)
    assert under['base_price'] == 3e6 and over['base_price'] == 2e6
    assert under['first_price'] / over['first_price'] == pytest.approx(1.5)
    assert under['revenue'] / over['revenue'] == pytest.approx(7.5)
    assert under['reference_date'] and len(under['reference_date']) == 7
    assert under['first_date'] <= under['last_date']


def test_first_last_and_weighted_prices_differ_for_shifted_sales():
    _, _, _, d = run(offices_direct_sale_offset_months=6, offices_growth_pre_pct=1, offices_growth_post_pct=.5)
    p = d['products'][0]
    assert p['base_price'] < p['first_price'] < p['average_price'] < p['last_price']
    assert 'не рассчитывается' in p['price_end_note']


def test_hold_separates_cash_and_non_cash_value():
    _, _, r, d = run('income',offices_exit_mode='hold')
    assert d['valuation'] > 0
    assert not any(p['strategy']=='Выход' for p in d['products'])
    assert d['cash_revenue'] + d['valuation'] == pytest.approx(r['summary']['revenue'])
    from office_results import blocks
    income, _, _ = blocks(d)
    assert any('без сделки' in row['label'] for row in income[1]['rows'])


def test_zero_and_missing_are_distinct_and_no_parking_is_not_invented():
    import office_results
    x, t, r, _ = run(offices_parking_guest_pct=100)
    assert not any(':parking:' in p['key'] for p in r['report']['office_results']['products'])
    x.pop('offices_price_th_per_sqm', None)
    # Disclosure consumes known zero schedules but must not claim a missing price was given as zero.
    op=core.build_operating_model(x,t,[])
    fin=copy.deepcopy(r['finance'])
    fin['nonres']['objects'][0]['book']['price_rub_sqm']=0
    d=office_results.build(x,t,op,fin,[],core.STANDALONE_OBJECTS)
    p=d['products'][0]
    assert p['base_price'] is None and p['first_price'] is None and p['average_price'] is None
    assert 'не различены' in p['origin']


def test_zero_type_price_uses_disclosed_existing_model_fallback():
    x,t,r,_=run()
    x['offices_parking_under_price_mln_per_space']=0
    r=core.calculate(core.CalcRequest(inputs=x,tep=t,rates=[]))
    p=next(p for p in r['report']['office_results']['products'] if p['key'].endswith('parking:under'))
    assert p['base_price']==x['parking_price_th']*1000
    assert 'правило модели' in p['origin']


def test_cost_chart_and_table_are_identical_and_total_is_not_charted_twice():
    _, _, r, _ = run()
    s=next(s for s in r['report']['object_report']['sections'] if s['key']=='costs')
    b=s['blocks'][0]
    assert b['charts'][0]['rows']==b['years'][:-1]
    assert sum(p['value'] for p in b['charts'][0]['rows'])==pytest.approx(r['summary']['total_expenses'])


def test_pdf_exports_long_monthly_plans_with_labels():
    from pypdf import PdfReader
    x,t,r,_=run(offices_direct_sale_months=72)
    pdf=core._build_developaid_pdf({'result':r,'inputs':x,'tep':t,'rates':[]})
    text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    for phrase in ['Состав денежной выручки','Последняя продажа','Остаток','Подземные места','Места на первых этажах','расчётный план продаж']:
        assert phrase.lower() in text.lower()


def test_rental_exit_has_a_date_price_and_cash_period():
    _, _, _, d = run('income')
    p = next(p for p in d['products'] if p['strategy']=='Выход')
    assert len(p['rows']) == 1 and p['quantity']==1
    assert p['first_date']==p['last_date']
    assert p['first_price']==p['last_price']==p['average_price']==p['revenue']
    assert p['rows'][0]['revenue']==p['revenue']


def test_ddu_rejected_profile_is_not_claimed_as_applied():
    _,_,_,d = run('ddu',offices_sales_profile='невалидный профиль',
        _field_origin={'inputs.offices_growth_pre_pct': {'source':'manual','text':'Гипотеза владельца'}})
    p=d['products'][0]
    assert 'не распознан' in p['note'] and 'не применён' in p['note']
    assert 'Гипотеза владельца' in p['note']


def test_missing_exit_cap_is_not_a_free_sale_of_one_building():
    _,_,_,d = run('income',offices_exit_cap_pct=0)
    p=next(p for p in d['products'] if p['strategy']=='Выход')
    assert p['quantity'] is None and p.get('first_price') is None
    assert 'капитализации' in p['missing_reason']
    assert d['reconciliation_gap']==pytest.approx(0,abs=.01)
