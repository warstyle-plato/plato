"""Native consumers keep exact day-17 dates on monthly cash calendars."""
from __future__ import annotations

import copy
import io
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import openpyxl
import pytest

import hotel_presets
import hotel_workbook as hw
import main_legacy as core
import native_land_rent_book as native
import office_workbook as ow
from xlsx_eval import Evaluator


def _project(kind):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    for obj in core.STANDALONE_OBJECTS:
        x[obj.enabled_key] = False
    if kind == "hotel":
        x = hotel_presets.apply_preset(x, "hotel1")
    x.update(project_kind="hotel" if kind == "hotel" else "nonresidential",
             project_start="2027-01-17", ird_months=12, construction_months=12,
             land_right="lease", land_rights_cost_mln=0,
             land_rent_mode="manual", vri_region="msk", land_rent_cadastral_mln=100,
             land_rent_regime_start="2027-01-17",
             land_rent_rates=[{"year": 1, "rate_pct": 1}],
             land_rent_tail_rule="repeat_last", land_rent_vat_treatment="public_exempt")
    if kind != "hotel":
        prefix = "offices" if kind == "office" else "retail"
        x.update({prefix+"_enabled": True, prefix+"_gba_sqm": 5000,
                  prefix+"_saleable_sqm": 3500, prefix+"_strategy": "income",
                  prefix+"_rent_th_per_sqm_month": 5, prefix+"_occupancy_stable_pct": 95,
                  prefix+"_leaseup_months": 12, prefix+"_opex_pct": 18,
                  prefix+"_exit_cap_pct": 10, prefix+"_start": "2028-01-17",
                  prefix+"_months": 12})
    return x, copy.deepcopy(core.TEP_DEFAULT)


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date(1899, 12, 30) + timedelta(days=int(value))


def _hotel_evaluate(w):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    evaluator = Evaluator(w)
    for row in range(hw.FIRST_ROW, w[hw.CALC_SHEET].max_row+1):
        for column, _ in hw.COLUMNS.values():
            value = w[hw.CALC_SHEET][f"{column}{row}"].value
            if isinstance(value, str) and value.startswith("="):
                evaluator.cell(hw.CALC_SHEET, f"{column}{row}")
    return evaluator


def _daily_rent(end):
    """Independent Actual/Actual oracle on exact Jan-17 contract years."""
    start=date(2027,1,17)
    total=0.0
    day=start
    while day<end:
        year=day.year-(day<date(day.year,1,17))
        denominator=(date(year+1,1,17)-date(year,1,17)).days
        total+=1_000_000/denominator
        day+=timedelta(days=1)
    return total


@pytest.mark.parametrize('path_key,object_day,share_before,residual,last_month,expected',[
    ('ddu',17,85,6,29,date(2029,9,17)),
    ('ddu',31,85,6,29,date(2029,9,30)),
    ('ddu',31,100,0,23,date(2029,4,30)),
    ('direct',17,85,6,35,date(2030,4,1)),
    ('direct',31,85,6,35,date(2030,4,1)),
    ('presale',17,85,6,24,date(2029,5,17)),
    ('presale',31,85,6,24,date(2029,5,28)),
])
def test_native_sale_exit_preserves_own_date_convention(monkeypatch,path_key,object_day,share_before,residual,last_month,expected):
    x,t=_project('office')
    x.update(offices_strategy='ddu',offices_start=f'2028-01-{object_day:02d}',
             offices_share_before_rve_pct=share_before,offices_residual_months=residual)
    result=core._run_authoritative_model(x,t,[],{})['consolidated']
    engine_path=next(p for p in result['office_paths']['paths'] if p['key']==path_key)
    rental=engine_path['land_rent']
    exposure=rental['land_exposures'][0]
    assert exposure['lease_exit']==expected.isoformat()
    assert exposure['sale_exit_basis']==('last_delivery' if path_key=='ddu' else 'exclusive_direct_end')
    commissioning=date(2029,1,object_day)
    workbook=openpyxl.Workbook()
    calendar=workbook.active;calendar.title=ow.TIME_SHEET
    for cell,value in {'A1':date(2027,1,17),'B1':date(2028,1,object_day),
                       'C1':12,'D1':last_month,'E1':24,'F1':5000,
                       'I1':date.fromisoformat(exposure['sale_exit'])}.items():
        calendar[cell]=value
    for k in range(48):
        calendar.cell(3,4+k,core.add_months(date(2027,1,17),k))
    ref=lambda cell:f"'{ow.TIME_SHEET}'!${cell[0]}${cell[1:]}"
    bindings={'in.o1.start':'B1','in.o1.months':'C1','o1d.horizon':'D1',
              'o1d.comm':'E1','in.o1.total_area':'F1','o1d.last_delivery':'I1'}
    monkeypatch.setattr(ow,'ref',lambda name,*args:ref(bindings[name]))
    path={'code':'d','key':path_key,'strategy':engine_path['strategy'],'object_keys':{'offices'},
          'result_key':'office_paths','label':'Synthetic sale'}
    book=SimpleNamespace(wb=workbook,n=48,cell_ref=lambda name:ref('A1'),
        project_only=False,groups=[{'current':path_key,'paths':[path]}],paths=[path],
        rent_calendars={},rent_exposures={},pending=[])
    ow._rent_calendars(book,result,{'land_rent_inputs':x,'land_rent':rental},
        [{'key':'offices','code':'o1','ddu':True,'strategy':'ddu'}])
    evaluator=Evaluator(workbook)
    assert _date_value(evaluator.cell(native.SHEET,'B15'))==expected
    assert evaluator.cell(native.SHEET,'B19')*1e6==pytest.approx(_daily_rent(expected),abs=.01)
    metadata=book.rent_calendars['d'][0].layout['exposure_rows'][exposure['id']]['metadata']
    assert _date_value(evaluator.cell(native.SHEET,f'C{metadata}'))==commissioning
    assert evaluator.cell(native.SHEET,'D3')==(date(2027,1,1)-date(1899,12,30)).days


@pytest.mark.parametrize('sales_start,profile,share,residual,object_day,zero_price,expected',[
    ('2027-02-05','100%@30',85,6,17,False,'2029-11-05'),
    ('2027-02-25','100%@30',85,6,17,False,'2029-11-25'),
    ('2028-01-31','100%@13',85,6,17,False,'2029-05-28'),
    ('2029-03-05','',100,0,17,False,'2029-06-05'),
    ('2027-02-05','',85,6,17,False,'2029-09-17'),
    ('2027-02-25','',85,6,31,False,'2029-09-30'),
    ('2029-01-25','',50,1,17,False,'2029-04-25'),
    ('2029-03-25','',50,6,17,False,'2029-09-17'),
    ('2027-02-05','100%@30',85,6,17,True,'2029-11-05'),
])
def test_ddu_positive_delivery_date_producer_keeps_both_live_anchors(monkeypatch,sales_start,profile,share,residual,object_day,zero_price,expected):
    x,t=_project('office')
    x.update(offices_strategy='ddu',offices_start=f'2028-01-{object_day:02d}',
             offices_sales_start=sales_start,offices_sales_profile=profile,
             offices_share_before_rve_pct=share,offices_residual_months=residual)
    if zero_price:
        key=next(o.rate_price for o in core.STANDALONE_OBJECTS if o.key=='offices')
        x[key]=0;x['_class_manual']=[key]
    prepared=core.prepared_calculation(x,t,[])
    op=core.build_operating_model(prepared['x'],prepared['t'],prepared['rates'])
    rental=op['land_rent'];exposure=rental['land_exposures'][0]
    assert exposure['lease_exit']==expected
    quantities=op['quantity_product_schedules']['offices']
    assert sum(quantities.values())>0
    if zero_price:
        assert op['revenue_by_product'].get('offices',0)==0
    workbook=openpyxl.Workbook();calendar=workbook.active;calendar.title=ow.TIME_SHEET
    origin=date(2027,1,17);sale=date.fromisoformat(sales_start)
    price_start=(sale.year-origin.year)*12+sale.month-origin.month
    comm=24
    cells={'A1':origin,'B1':date(2028,1,object_day),'C1':12,'E1':comm,
           'F1':5000,'G1':sale,'H1':price_start,'J1':share/100,'K1':residual,
           'L1':max(1,comm-price_start)}
    for c,value in cells.items():calendar[c]=value
    ref=lambda c:f"'{ow.TIME_SHEET}'!${openpyxl.utils.cell.coordinate_from_string(c)[0]}${openpyxl.utils.cell.coordinate_from_string(c)[1]}"
    fields={'price_start':'H1','comm':'E1','share':'J1','residual':'K1','pre_n':'L1'}
    inputs={'sales_start':'G1','start':'B1','months':'C1'}
    positive=[]
    for k in range(48):
        column=openpyxl.utils.get_column_letter(4+k)
        month=core.add_months(origin,k)
        calendar[f'{column}3']=month;calendar[f'{column}4']=k
        quantity=quantities.get(month.replace(day=1),0)
        calendar[f'{column}5']=quantity
        if quantity>0:positive.append(k)
        b=lambda key:ref(f'{column}5') if key=='qty' else ref(fields[key])
        calendar[f'{column}6']='='+ow._ddu_delivery_date_formula(b,lambda key:ref(inputs[key]),ref(f'{column}4'),bool(profile))
    calendar['D1']=max(positive,default=-1)
    calendar['I1']='=MAX(D6:AY6)'
    bindings={'in.o1.start':'B1','in.o1.months':'C1','o1d.horizon':'D1',
              'o1d.comm':'E1','in.o1.total_area':'F1','o1d.last_delivery':'I1'}
    monkeypatch.setattr(ow,'ref',lambda name,*args:ref(bindings[name]))
    path={'code':'d','key':'ddu','strategy':'ddu','object_keys':{'offices'},'result_key':'office_paths','label':'Synthetic DDU'}
    book=SimpleNamespace(wb=workbook,n=48,cell_ref=lambda name:ref('A1'),project_only=False,
        groups=[{'current':'ddu','paths':[path]}],paths=[path],rent_calendars={},rent_exposures={},pending=[])
    ow._rent_calendars(book,{'office_paths':{'paths':[{'key':'ddu','land_rent':rental}]}},
        {'land_rent_inputs':x,'land_rent':rental},[{'key':'offices','code':'o1','ddu':True,'strategy':'ddu'}])
    evaluator=Evaluator(workbook)
    assert _date_value(evaluator.cell(native.SHEET,'B15'))==date.fromisoformat(expected)
    assert evaluator.cell(native.SHEET,'B19')*1e6==pytest.approx(_daily_rent(date.fromisoformat(expected)),abs=.01)
    # Moving only the day of the sales anchor keeps the cash buckets fixed,
    # but the exact delivery/registration dates must update without a rebuild.
    moved=sale.replace(day=25 if sale.day!=25 else 5)
    calendar['G1']=moved
    changed=copy.deepcopy(prepared['x']);changed['offices_sales_start']=moved.isoformat()
    fresh=core.build_operating_model(changed,copy.deepcopy(prepared['t']),prepared['rates'])['land_rent']
    end=date.fromisoformat(fresh['land_exposures'][0]['lease_exit'])
    assert _date_value(Evaluator(workbook).cell(native.SHEET,'B15'))==end


@pytest.mark.parametrize('sales_start,profile,share,residual,delivery,expected',[
    ('2027-02-05','100%@30',85,6,'2029-08-05','2029-11-05'),
    ('2027-02-25','100%@30',85,6,'2029-08-25','2029-11-25'),
    ('2029-03-05','',100,0,'2029-03-05','2029-06-05'),
    ('2028-01-31','100%@13',85,6,'2029-02-28','2029-05-28'),
])
def test_actual_native_ddu_anchor_export_keeps_all_variant_verdicts(sales_start,profile,share,residual,delivery,expected):
    x,t=_project('office')
    x.update(offices_strategy='ddu',offices_sales_start=sales_start,offices_sales_profile=profile,
             offices_share_before_rve_pct=share,offices_residual_months=residual)
    result=core._run_authoritative_model(x,t,[],{})['consolidated']
    rent=result['land_rent']
    assert rent['land_exposures'][0]['sale_exit']==delivery
    assert rent['rve']==expected
    amount=_daily_rent(date.fromisoformat(expected))
    assert rent['cash_total']==pytest.approx(amount,abs=.01)
    content,_,meta=core.build_project_workbook(x,t,[],{},project_name='Synthetic exact DDU delivery')
    workbook=openpyxl.load_workbook(io.BytesIO(content))
    evaluator=ow.evaluate(workbook)
    assert _date_value(evaluator.cell(native.SHEET,'B15'))==date.fromisoformat(expected)
    assert evaluator.cell(native.SHEET,'B19')*1e6==pytest.approx(amount,abs=.01)
    verdict,bad=ow.verdict(evaluator)
    assert verdict==ow.PASSED and bad==[],(verdict,bad)
    assert meta['checks']==ow.PASSED
    assert not any('расхождения' in str(item) for item in meta['missing'])


@pytest.mark.parametrize("kind", ["hotel", "office", "retail"])
def test_actual_native_export_conserves_day17_rent_and_finance(kind):
    x, t = _project(kind)
    result = core._run_authoritative_model(x, t, [], {})["consolidated"]
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Synthetic day17")
    w = openpyxl.load_workbook(io.BytesIO(content))
    assert meta.get("hotel_book") if kind == "hotel" else meta.get("nonres_book")
    rent=result["land_rent"]
    commissioning=date(2029,1,17)
    prefix='hotel' if kind=='hotel' else 'offices' if kind=='office' else 'retail'
    hold_years=int(x[prefix+'_hold_years'])
    lease_exit=date(commissioning.year+hold_years,1,1)
    expected=_daily_rent(lease_exit)
    assert rent["derived_rve"] == commissioning.isoformat()
    assert rent["rve"] == lease_exit.isoformat()
    assert rent["land_exposures"][0]["commissioning"]==commissioning.isoformat()
    assert rent["land_exposures"][0]["lease_exit"]==lease_exit.isoformat()
    assert rent["land_exposures"][0]["share"]==1
    assert rent["land_exposures"][0]["retained"]
    assert result["capex"]["land_rent"]==pytest.approx(2e6)
    assert rent["construction_total"]==pytest.approx(expected,abs=.01)
    assert rent["operating_cash_total"]==pytest.approx(expected-2e6,abs=.01)
    evaluator = _hotel_evaluate(w) if kind == "hotel" else ow.evaluate(w)
    assert _date_value(evaluator.cell(native.SHEET, "B14")) == date(2027, 1, 17)
    assert evaluator.cell(native.SHEET, "B19") * 1e6 == pytest.approx(expected,abs=.01)
    assert _date_value(evaluator.cell(native.SHEET,"B15"))==lease_exit
    # The same exact-day schedule crosses the capex / operation boundary once.
    for label,amount in (("Аренда в разработке: платежи",2e6),
                         ("Операционная аренда: платежи",expected-2e6)):
        row=next(r for r in range(1,w[native.SHEET].max_row+1) if w[native.SHEET][f"A{r}"].value==label)
        assert evaluator.cell(native.SHEET,f"B{row}")*1e6==pytest.approx(amount,abs=.01)
    assert evaluator.cell(native.SHEET, "D3") == (date(2027, 1, 1)-date(1899, 12, 30)).days
    if kind == "hotel":
        checks = w[hw.CHECK_SHEET]
        bad = [(checks[f"A{row}"].value, evaluator.cell(hw.CHECK_SHEET, f"F{row}"))
               for row in range(3, checks.max_row+1)
               if checks[f"B{row}"].value is not None
               and evaluator.cell(hw.CHECK_SHEET, f"F{row}") not in ("сходится", "—")]
        assert bad == []
        assert evaluator.cell(hw.CHECK_SHEET, "H3") == "ПРОЙДЕНО"
        assert _date_value(evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["start"]))) == date(2027, 1, 17)
        assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_total"])) == pytest.approx(result["capex"]["total"])
        assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["building_net"])) == pytest.approx(result["finance"]["hotel"]["kpi"]["building_net"])
    else:
        verdict, bad = ow.verdict(evaluator)
        assert verdict == ow.PASSED and bad == [], (verdict, bad)
        assert meta["checks"] == ow.PASSED
        assert not any("расхождения" in item for item in meta["missing"])
    qualifier = evaluator.cell(native.SHEET, "L13")
    assert qualifier  # the rental contract is not claimed to terminate at RVE.
