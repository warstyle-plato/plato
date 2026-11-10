"""Production v4 matches monthly cash without changing business dates."""
import copy
import io
from datetime import date, datetime, timedelta

import openpyxl
import pytest

import developaid_land_rent as rent
import main_legacy as core
import v4_dashboard as dashboard
import v4_land_rent as book
from xlsx_eval import Evaluator


def day(value):
    if isinstance(value,datetime):
        return value.date()
    return value if isinstance(value,date) else date(1899,12,30)+timedelta(days=int(value))


@pytest.fixture(scope="module",params=[1,17])
def production(request):
    start=date(2027,5,request.param)
    rve=date(2030,5,request.param)
    x={**copy.deepcopy(core.DEFAULT_INPUTS),"project_start":start.isoformat(),
       "ird_months":12,"construction_months":24,"land_right":"lease",
       "land_rights_cost_mln":132,"land_rent_mode":"manual",
       "land_rent_cadastral_mln":100,"land_rent_regime_start":start.isoformat(),
       "land_rent_rates":[{"year":1,"rate_pct":3}],"land_rent_tail_rule":"repeat_last",
       "land_rent_payment_mode":"manual","land_rent_payment_schedule":"100%@0",
       "land_rent_vat_treatment":"public_exempt","land_rent_termination_date":rve.isoformat()}
    t=copy.deepcopy(core.TEP_DEFAULT)
    result=core._run_authoritative_model(x,t,[],{})
    canonical=result["consolidated"]["land_rent"]
    assert canonical["construction_total"] == pytest.approx(9e6)
    assert canonical["cash_total"] == pytest.approx(9e6)
    assert canonical["financial_complete"]
    content,_,meta=core.build_project_workbook(x,t,[],{},
        finance_hints=core._v4_finance_hints(result),cache_values=False)
    assert not meta["missing"],meta["missing"]
    w=openpyxl.load_workbook(io.BytesIO(content),data_only=False)
    return x,start,rve,w,Evaluator(w),canonical


def test_real_v4_keeps_nine_million_cash_accrual_and_all_source_days(production):
    _,start,rve,w,ev,canonical=production
    assert day(ev.cell("CF_1","B6")) == start
    assert day(ev.cell("CF_1","B8")) == rve
    assert day(ev.cell("Ставки","D3")) == start
    assert day(ev.cell(book.SHEET,"B14")) == start
    assert day(ev.cell(book.SHEET,"B10")) == start
    assert day(ev.cell(book.SHEET,"B15")) == rve
    assert day(ev.cell(book.SHEET,"B125")) == start
    for index in range(book.MONTHS):
        col=openpyxl.utils.get_column_letter(4+index)
        month=rent._add_months(start.replace(day=1),index).isoformat()
        assert day(ev.cell(book.SHEET,f"{col}3")).isoformat() == month
        assert ev.cell(book.SHEET,f"{col}4")*1e6 == pytest.approx(canonical["accrual_monthly"].get(month,0),abs=.01)
        assert ev.cell(book.SHEET,f"{col}6")*1e6 == pytest.approx(canonical["monthly"].get(month,0),abs=.01)
    for index,row in enumerate(canonical["annual_rows"],book.FIRST_YEAR_ROW):
        assert ev.cell(book.SHEET,f"H{index}")*1e6 == pytest.approx(row["amount"],abs=.01)
    assert ev.cell(book.SHEET,"L17") == pytest.approx(9)
    assert ev.cell(book.SHEET,"B19") == pytest.approx(9)
    assert ev.cell(book.SHEET,"L13") == ""
    assert ev.cell("CAPEX","B145") == pytest.approx(9)
    labels=[label for label,_ in dashboard.STRUCTURE_ITEMS]
    row=dashboard.STRUCTURE_FIRST_ROW+labels.index("Аренда земельного участка")
    assert ev.cell(dashboard.DATA_SHEET,f"B{row}") == pytest.approx(9)


@pytest.mark.parametrize("rate",[4,None])
def test_live_rate_and_blank_preserve_the_same_production_calendar(production,rate):
    x,start,rve,source,_,_=production
    w=copy.deepcopy(source)
    w[book.SHEET]["D22"]=rate
    expected=rent.build({**x,"land_rent_rates":[{"year":1,"rate_pct":rate}]},start,rve)
    ev=Evaluator(w)
    assert day(ev.cell(book.SHEET,"B14")) == start
    assert day(ev.cell(book.SHEET,"B15")) == rve
    assert ev.cell(book.SHEET,"L17")*1e6 == pytest.approx(expected["known_total"],abs=.01)
    assert ev.cell(book.SHEET,"B19")*1e6 == pytest.approx(expected["cash_total"],abs=.01)
    assert bool(ev.cell(book.SHEET,"B17")) == expected["complete"]
    if rate is None:
        assert ev.cell("CAPEX","D145") == "Не рассчитано"
