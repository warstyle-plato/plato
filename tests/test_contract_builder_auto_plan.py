import datetime as dt
import io
import pytest
from openpyxl import Workbook,load_workbook
from developaid_contract_physical_sheets import write_builder_template
from developaid_contract_builder_plan import BuilderEvaluator,cache_builder_formulas
from tests.test_contract_gpr_earned_plan_equivalent import view,event


def sheet_fixture():
    book=Workbook()
    schedule={'lines':[{'code':'G','start':'2026-11-01','finish':'2026-11-30','segments':[
        {'start':'2026-11-01','finish':'2026-11-10'},{'start':'2026-11-21','finish':'2026-11-30'}]}]}
    row={'number':'1.1','name':'Монтаж','unit':'м2','contract_quantity':100,'estimate':0,'index':0,
         'physical_audit':{'gpr_binding':{'status':'confirmed','lines':[{'code':'G','share':1}]}}}
    sheet=write_builder_template(book,{'cut':'2026-11-10','rows':[row]},schedule)
    return book,sheet


def test_auto_plan_uses_active_intervals_and_visible_cut_while_fact_is_blank():
    book,sheet=sheet_fixture();ev=BuilderEvaluator(book)
    assert sheet['I1'].value==dt.date(2026,11,10)
    assert ev.cell(sheet.title,'J4')==50
    assert ev.cell(sheet.title,'K4')==.5
    assert sheet['L4'].value==0 and ev.cell(sheet.title,'M4')==0
    assert ev.cell(sheet.title,'N4')==-50
    assert ev.cell(sheet.title,'O4')==-50
    assert sheet['J5'].value is None  # no fictional delivery schedule
    sheet['I4']=dt.date(2026,11,24);sheet['L4']=40
    ev=BuilderEvaluator(book)
    assert ev.cell(sheet.title,'J4')==70
    assert ev.cell(sheet.title,'N4')==-30
    assert ev.cell(sheet.title,'O4')==pytest.approx(-30)
    assert ev.cell(sheet.title,'M4')==.4


def test_new_formula_results_have_caches_for_excel_readers():
    book,sheet=sheet_fixture();buf=io.BytesIO();book.save(buf)
    raw=cache_builder_formulas(buf.getvalue(),book)
    cached=load_workbook(io.BytesIO(raw),data_only=True)
    assert cached[sheet.title]['J4'].value==50
    assert cached[sheet.title]['L4'].value==0


def test_retrospective_assessment_does_not_claim_production_start_or_daily_fact():
    row=view(10,[event(10,'2026-11-10')])
    early=[b for b in row['reporting']['bars'] if b['range_kind']=='retrospective_report_assessment']
    assert [(b['start'],b['end']) for b in early]==[(0,9)]
    assert all(b['comparison_date']=='2026-11-10' and not b['carried_forward'] and b['not_actual_dates'] for b in early)
    assert early[0]['state']=='warning'
    assert early[0]['planned_fraction_start']==pytest.approx(1/3)
    assert all('actual_start' not in cp for cp in row['reporting']['checkpoints'])
