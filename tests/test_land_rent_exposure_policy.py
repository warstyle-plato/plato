"""Owner's registration/retention policy uses one parcel and two cost clocks."""
import copy
from datetime import date, timedelta
import calendar
import io

import openpyxl
import pytest

import developaid_land_rent as rent
import hotel_presets
import main_legacy as core
import v4_land_rent as sheet
from xlsx_eval import Evaluator


START=date(2027,1,1)
OPEN=date(2029,1,1)


def inputs(**changes):
    return {**copy.deepcopy(core.DEFAULT_INPUTS),"project_start":"2027-01-01","ird_months":12,
        "construction_months":12,"land_right":"lease","land_rights_cost_mln":0,
        "land_rent_mode":"manual","land_rent_cadastral_mln":100,
        "land_rent_regime_start":"2027-01-01","land_rent_rates":[{"year":1,"rate_pct":1.5}],
        "land_rent_tail_rule":"repeat_last","land_rent_vat_treatment":"public_exempt",
        "social_mode":"Денежная компенсация","social_compensation_mln":0,**changes}


def daily(items):
    answer=0.
    day=START
    while day < max(date.fromisoformat(p['lease_exit']) for p in items):
        active=sum(p['share'] for p in items if day < date.fromisoformat(p['lease_exit']))
        answer+=1_500_000*active/(366 if calendar.isleap(day.year) else 365)
        day+=timedelta(days=1)
    return answer


@pytest.mark.parametrize('value,months,missing',[(None,3,False),('',3,False),(0,0,False),
    (6,6,False),(-1,3,True),(.5,3,True),(float('nan'),3,True)])
def test_registration_default_is_signed_and_zero_is_an_explicit_scenario(value,months,missing):
    x=inputs(land_rent_registration_months=value)
    exposed,reasons=rent.planning_exposures(x,OPEN,housing_area=1000,objects=[])
    assert rent.registration_months(x)==months
    assert bool(reasons)==missing
    assert exposed[0]['commissioning']=='2029-01-01'
    result=rent.qualify_exposures(rent.build(x,START,OPEN,date(2030,1,1),exposures=exposed),reasons)
    assert result['known_total']==pytest.approx(daily(exposed),abs=.01)
    assert rent.sum_state(result)['known'] is not missing


@pytest.mark.parametrize('comm,expected',[(date(2028,11,30),'2029-02-28'),
    (date(2029,1,31),'2029-04-30'),(date(2029,1,17),'2029-04-17')])
def test_registration_keeps_actual_days_and_absolute_overrides(comm,expected):
    exposed,_=rent.planning_exposures(inputs(),comm,housing_area=1000,objects=[])
    assert exposed[0]['lease_exit']==expected
    x=inputs(land_rent_registration_months=6,land_rent_manual_cutoff='2029-02-02',
             land_rent_termination_date='2029-02-01')
    exposed,_=rent.planning_exposures(x,comm,housing_area=1000,objects=[])
    assert exposed[0]['commissioning']==comm.isoformat()
    assert exposed[0]['lease_exit']=='2029-02-01'


def mixed_exposures(x):
    return rent.planning_exposures(x,OPEN,housing_area=700,objects=[{
        'id':'offices','object_key':'offices','name':'Офис','total_area':300,
        'commissioning':OPEN.isoformat(),'lease_exit':'2034-01-01',
        'policy':'income_horizon','retained':True,'source':'Операционный срок: 5 лет'}])[0]


def test_mixed_parcel_does_not_keep_all_housing_on_lease_for_the_office_horizon():
    x=inputs(); exposed=mixed_exposures(x)
    result=rent.build(x,START,OPEN,date(2034,1,1),exposures=exposed)
    assert [p['share'] for p in exposed]==[.7,.3]
    assert [p['lease_exit'] for p in exposed]==['2029-04-01','2034-01-01']
    assert result['known_total']==pytest.approx(5_508_904.109589,abs=.01)
    assert result['known_total']==pytest.approx(daily(exposed),abs=.01)
    assert result['operating_cash_total']==pytest.approx(2_250_000,abs=.01)
    assert result['development_cash_total']+result['operating_cash_total']==pytest.approx(result['cash_total'])
    assert sum(result['phase_monthly'][0].values())==pytest.approx(result['cash_total'])


def test_unknown_mixed_allocation_is_named_instead_of_a_false_zero_tail():
    x=inputs()
    exposed,reasons=rent.planning_exposures(x,OPEN,housing_area=None,objects=[{
        'id':'offices','object_key':'offices','total_area':300,'commissioning':OPEN.isoformat(),
        'lease_exit':'2034-01-01','policy':'income_horizon'}])
    result=rent.qualify_exposures(rent.build(x,START,OPEN,date(2034,1,1),exposures=exposed),reasons)
    assert reasons and 'land_exposures' in result['financial_missing_codes']
    assert not rent.sum_state(result)['known'] and not result['financial_complete']


def test_prepayment_does_not_capitalize_future_retained_rent_or_expense_it_all_at_start():
    x=inputs(land_rent_payment_mode='manual',land_rent_payment_schedule='100%@0')
    exposed,_=rent.planning_exposures(x,OPEN,housing_area=0,housing=False,objects=[{
        'id':'hotel','object_key':'hotel','total_area':1000,'commissioning':OPEN.isoformat(),
        'lease_exit':'2034-01-01','policy':'income_horizon','retained':True}])
    result=rent.build(x,START,OPEN,date(2034,1,1),exposures=exposed)
    own=result['land_exposures'][0]
    assert result['cash_total']==pytest.approx(10_500_000)
    assert result['development_cash_total']==pytest.approx(3_000_000)
    assert own['operating_monthly']==pytest.approx({'2027-01-01':7_500_000})
    assert sum(v for m,v in own['operating_accrual_monthly'].items() if m<'2029-01-01')==0
    assert sum(own['operating_accrual_monthly'].values())==pytest.approx(7_500_000)


@pytest.mark.parametrize('region',['msk','mo'])
@pytest.mark.parametrize('phased',[False,True])
@pytest.mark.parametrize('target',[None,200])
def test_full_vri_relief_does_not_erase_the_cadastral_event(region,phased,target):
    p={'enabled':True,'phase_count':2,'phases':[
        {'name':'A','site_area_ha':35,'start_offset_months':0,'construction_months':12},
        {'name':'B','site_area_ha':65,'start_offset_months':12,'construction_months':12}]} if phased else {}
    results=[]
    for relief in (0,100):
        x=inputs(vri_region=region,land_rights_cost_mln=50,vri_relief_mode='percent',vri_relief_pct=relief,
            vri_obligation_date='2027-07-01',land_rent_cadastral_target_mln=target)
        results.append(core._run_authoritative_model(x,copy.deepcopy(core.TEP_DEFAULT),[],copy.deepcopy(p))['consolidated'])
    before,after=results
    assert before['land_rent']['accrual_monthly']==after['land_rent']['accrual_monthly']
    assert after['capex']['land_rights']==0
    if target is None:
        assert 'cadastral_change' in after['land_rent']['financial_missing_codes']
        assert not after['summary']['land_rent_sum']['known'] and after['summary']['preliminary']
    else:
        assert after['land_rent']['cadastral_switch']==before['land_rent']['cadastral_switch']
        assert after['land_rent']['cadastral_switch']['date']=='2027-07-01'
        assert after['summary']['land_rent_sum']['known']


@pytest.mark.parametrize('region',['msk','mo'])
def test_no_gross_vri_event_keeps_the_old_scope_even_with_a_saved_target(region):
    result=core._run_authoritative_model(inputs(vri_region=region,land_rent_cadastral_target_mln=200,
        vri_obligation_date='2027-07-01'),copy.deepcopy(core.TEP_DEFAULT),[],{})['consolidated']
    assert result['land_rent']['cadastral_switch'] is None
    assert 'cadastral_change' not in result['land_rent']['financial_missing_codes']


@pytest.mark.parametrize('payment',['monthly_estimate','manual'])
def test_actual_hotel_operating_rent_stays_out_of_building_basis(payment):
    x=hotel_presets.apply_preset(inputs(),'hotel1')
    x.update({key:value for key,value in inputs().items() if not key.startswith('hotel_')})
    x.update(project_kind='hotel',hotel_hold_years=5,land_rent_payment_mode=payment,
             land_rent_payment_schedule='100%@0')
    result=core._run_authoritative_model(x,copy.deepcopy(core.TEP_DEFAULT),[],{})['consolidated']
    rent_result=result['land_rent']
    assert rent_result['land_exposures'][0]['lease_exit']=='2034-01-01'
    assert result['capex']['land_rent']==pytest.approx(3_000_000,abs=.01)
    assert rent_result['operating_cash_total']==pytest.approx(7_500_000,abs=.01)
    rows=result['finance']['rows']
    if payment=='manual':
        first=next(row for row in rows if row['month']=='2027-01-01')
        assert first['nonres_costs']==pytest.approx(7_500_000,abs=.01)
    assert result['finance']['hotel']['kpi']['building_net']>0


@pytest.mark.parametrize('region,phased,target,preset',[
    ('msk',False,None,False),('msk',True,200,False),
    ('mo',False,200,False),('mo',True,None,False),('msk',True,200,True)])
def test_real_v4_keeps_gross_vri_event_zero_cash_and_future_base_qualification(region,phased,target,preset):
    x=inputs(vri_region=region,land_rights_cost_mln=50,vri_relief_mode='percent',vri_relief_pct=100,
             vri_obligation_date='2027-07-01',land_rent_cadastral_target_mln=target)
    if preset:
        x.update(land_rent_mode='msk_mkd_3_2',land_rent_preset_confirmed=True,
                 land_rent_premium_status='unknown')
    p={'enabled':True,'phase_count':2,'phases':[
        {'name':'A','site_area_ha':35,'start_offset_months':0,'construction_months':12},
        {'name':'B','site_area_ha':65,'start_offset_months':12,'construction_months':12}]} if phased else {}
    bundle=core._run_authoritative_model(x,copy.deepcopy(core.TEP_DEFAULT),[],p)
    expected=bundle['consolidated']['land_rent']
    content,_,meta=core.build_project_workbook(x,copy.deepcopy(core.TEP_DEFAULT),[],p,
        finance_hints=core._v4_finance_hints(bundle),cache_values=False)
    assert meta['land_rent']['workbook_supported'],meta['land_rent']
    book=openpyxl.load_workbook(io.BytesIO(content)); ev=Evaluator(book)
    assert ev.cell(sheet.SHEET,'L20')==50  # gross obligation, not zero payable
    for i in range(2 if phased else 1):
        row=core._V4_VRI_PRINCIPAL_ROW+core._V4_VRI_BLOCK_STRIDE*i
        assert ev.cell('ВРИ',f'B{row}')==0
    assert ev.cell(sheet.SHEET,'B19')*1e6==pytest.approx(expected['cash_total'],abs=.01)
    assert sum(ev.cell('CAPEX',f'B{145+i}')*1e6 for i in range(2 if phased else 1))==pytest.approx(expected['development_cash_total'],abs=.01)
    if target is None:
        assert 'Кадастровая стоимость участка после смены ВРИ' in ev.cell(sheet.SHEET,'L14')
        assert ev.cell(sheet.SHEET,'L13')
        assert not bundle['consolidated']['summary']['land_rent_sum']['known']
    if preset:
        assert 'premium' in expected['financial_missing_codes']
        assert 'доплата первого года' in ev.cell(sheet.SHEET,'L13')


def test_shared_strategy_terms_preserve_blank_vs_explicit_zero():
    from openpyxl.worksheet._reader import WorksheetReader
    x=inputs()
    start,comm,end=date(2027,1,1),date(2027,2,1),date(2027,6,1)
    exposed,_=rent.planning_exposures(x,comm,housing_area=1000,objects=[])
    result=rent.build(x,start,comm,end,exposures=exposed)
    book=openpyxl.Workbook();book.remove(book.active)
    layouts=[]
    for name,master in [('Terms',None),('Alternative','Terms')]:
        ws=book.create_sheet(name);layout={}
        xml=sheet.build_sheet(x,result,{key:0 for key in ('amount','date','input','input_date','input_text')},
            project_start_formula='DATE(2027,1,1)',rve_formula='DATE(2027,2,1)',
            project_end_formula='DATE(2027,6,1)',hostvri_amount_formula='0',months=6,
            month_formulas=[f'DATE(2027,{i+1},1)' for i in range(6)],
            exposure_formulas={'housing':{'share':'1','commissioning':'DATE(2027,2,1)',
                'lease_exit':'EDATE({commissioning},$N$15)'}},master_terms_sheet=master,layout=layout)
        WorksheetReader(ws,io.BytesIO(xml),[],False,False).bind_all();layouts.append(layout)
    target=next(cell.coordinate for row in book['Terms'] for cell in row if cell.value=='Кадастровая стоимость после смены ВРИ, млн ₽')
    target='B'+''.join(c for c in target if c.isdigit())
    ev=Evaluator(book)
    assert ev.cell('Alternative',target)==''
    book['Terms'][target]=0
    book['Terms']['N15']=0
    ev=Evaluator(book)
    assert ev.cell('Alternative',target)==0
    assert ev.cell('Alternative','N15')==0
    book['Terms']['D22']=None
    assert Evaluator(book).cell('Alternative','D22')==''
    assert layouts[1]['exposure_rows']['housing']['operating_accrual']
