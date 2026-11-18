"""Synthetic MO fee relief and accepted cadastral rent sources share ownership safely."""
from copy import deepcopy
import io

import openpyxl
import pytest
from xlsx_eval import Evaluator

import developaid_land_cadastral as cadastral
from tests.test_mo_vri_full_page import served, full_page
from tests.test_mo_vri_territory import add_hotel, apply_preview, NEW_TERRITORY
from tests.test_rent_cadastral_bases import settings
from tests.test_vri_phase_offset_once import core, phasing


def project():
    x={**deepcopy(core.DEFAULT_INPUTS),**settings('mo'),
       'project_start':'2027-01-01','ird_months':12,'construction_months':24,
       'land_rent_mode':'manual','land_rent_rates':[{'year':1,'rate_pct':1.5}],
       'land_rent_cadastral_mln':None,'land_rent_cadastral_target_mln':None,
       'land_rent_vri_change':True,'land_rent_cadastral_change_date':'2028-02-17',
       'land_rights_cost_mln':320,'vri_transfer_offset_mln':30,'vri_relief_mode':'off',
       'mo_vri_benefits':{'schema':1,'rows':[{'id':'hotel','kind':'investment',
           'object_type':'hotel_4','area_sqm':1000,'index_mode':'base'}],
           'applied':{'gross_rub':500e6,'net_mln':320}}}
    x['_mo_calc']['vri'].update(payment_before_compensation_rub=500e6,
        payment_used_rub=320e6,payment_used_mln=320,compensation_rub=180e6)
    core.apply_mo_vri_benefits(x,deepcopy(core.TEP_DEFAULT))
    x['_field_origin']={
        'inputs.land_rights_cost_mln':{'source':'mo_vri_compensation'},
        'inputs.mo_vri_compensation_mln':{'source':'mo_vri_compensation'}}
    return cadastral.prepare(x)


def test_native_and_evaluated_book_detach_mo_fee_but_keep_accepted_cadastral_source():
    x=project();t=deepcopy(core.TEP_DEFAULT)
    parcels=deepcopy(x['_mo_calc']['vri']['parcels'])
    assert x['land_rent_cadastral_mln']==300 and x['land_rent_cadastral_target_mln']==600
    native=core.calculate(core.CalcRequest(inputs=deepcopy(x),tep=deepcopy(t),rates=[]))
    assert native['vri']['totals']['principal']==290e6
    assert native['land_rent']['cadastral_switch']['target_mln']==600
    assert native['land_rent']['cadastral_switch']['date']=='2028-02-17'
    assert native['land_rent']['land_exposures'][0]['commissioning']=='2030-01-01'
    assert native['land_rent']['land_exposures'][0]['lease_exit']=='2030-04-01'
    x['vri_region']='msk'
    core.apply_mo_vri_benefits(x,t)
    assert x['_mo_calc']['vri']=={'parcels':parcels}
    assert x['land_rights_cost_mln']==500
    assert not x.get('_mo_vri_relief') and not x.get('mo_vri_compensation_mln')
    assert not x['mo_vri_benefits'].get('applied')
    bundle=core.calculate_phased(core.PhasedCalcRequest(inputs=deepcopy(x),tep=deepcopy(t),
        rates=[],phasing=phasing([40,60])))
    assert bundle['consolidated']['vri']['totals']['principal']==470e6
    assert bundle['consolidated']['land_rent']['base_value_mln'] is None
    assert bundle['consolidated']['land_rent']['cadastral_estimate']['total_mln'] is None
    data,_,meta=core.build_project_workbook(x,t,[],phasing([40,60]),cache_values=False)
    assert meta['land_rent']['base_value_mln'] is None
    assert meta['land_rent']['cadastral_estimate']['total_mln'] is None
    wb=openpyxl.load_workbook(io.BytesIO(data));ev=Evaluator(wb)
    assert ev.cell('Аренда ЗУ','B9') in ('',None)
    assert sum(float(ev.cell('ВРИ',f'B{core._V4_VRI_PRINCIPAL_ROW+core._V4_VRI_BLOCK_STRIDE*i}'))*1e6
        for i in range(2))==pytest.approx(470e6,abs=.51,rel=0)
    assert 'Гостиница 4' not in str(wb['Источники']['I7'].value)
    x['vri_region']='mo'
    returned=core.calculate(core.CalcRequest(inputs=x,tep=t,rates=[]))
    assert x['land_rights_cost_mln']==500 and not x['mo_vri_benefits'].get('applied')
    assert returned['vri']['totals']['principal']==470e6
    assert returned['land_rent']['base_value_mln']==300
    assert returned['land_rent']['cadastral_switch']['target_mln']==600
    assert returned['land_rent']['cadastral_switch']['date']=='2028-02-17'
    assert returned['land_rent']['land_exposures'][0]['lease_exit']=='2030-04-01'


@pytest.mark.parametrize('width',[390,1440])
def test_page_region_roundtrip_retains_parcels_but_new_territory_replaces_them(served,width):
    with full_page(served,width) as (page,_,__):
        source=project()['_mo_calc']
        page.evaluate('''async source=>{inputs._mo_calc=source;
          inputs.land_rent_cadastral_mln=null;inputs.land_rent_cadastral_target_mln=null;
          landRentAppliedTerritoryKey=null;renderInputs();await settledCalculate();openTab('vri')}''',source)
        add_hotel(page);apply_preview(page)
        assert page.evaluate('inputs.land_rights_cost_mln')==320
        assert page.evaluate('inputs.land_rent_cadastral_mln')==300
        assert page.evaluate('inputs.land_rent_cadastral_target_mln')==600
        parcels=page.evaluate('inputs._mo_calc.vri.parcels')
        page.locator('#f_vri_region').select_option('msk');page.wait_for_function('calcIdle()')
        assert page.evaluate('inputs.land_rights_cost_mln')==500
        assert page.evaluate('inputs._mo_calc.vri')=={'parcels':parcels}
        assert page.evaluate('inputs.land_rent_cadastral_mln') is None
        assert page.evaluate('inputs.land_rent_cadastral_target_mln') is None
        assert page.evaluate('phaseBundle.consolidated.vri.totals.principal')==470e6
        page.locator('#f_vri_region').select_option('mo');page.wait_for_function('calcIdle()')
        assert page.evaluate('inputs.land_rent_cadastral_mln')==300
        assert page.evaluate('inputs.land_rent_cadastral_target_mln')==600
        assert page.evaluate('inputs.land_rights_cost_mln')==500
        assert page.evaluate('inputs.mo_vri_benefits.applied||null') is None
        # The next accepted parcel replaces the preserved source and its editor.
        page.evaluate(NEW_TERRITORY)
        assert page.evaluate('inputs._mo_calc.vri.parcels||null') is None
        assert page.evaluate('moVriBenefitsDraft')==[]
        assert page.evaluate('inputs.land_rent_cadastral_mln') is None
        assert page.evaluate('inputs.land_rent_cadastral_target_mln') is None
        assert page.evaluate('inputs.land_rights_cost_mln')==777
        # A valid accepted Moscow source cannot coexist ambiguously with old MO.
        msk=settings('msk')
        page.evaluate('''async({value,oldMo})=>{inputs._mo_calc=oldMo;inputs.vri_region='msk';
          sendTelegramResult=async()=>{};
          glavapuImport={source:{name:'Синтетический московский участок'},
            normalized:value._glavapu_import.normalized,recognized:value._glavapu_import.recognized,
            mappings:{inputs:{vri_region:'msk',land_rights_cost_mln:888},
              tep:{apartments:{gns:40000,saleable:30000,transfer:2000}}},warnings:[]};
          await applyGlavapu();inputs._land_lookup=value._land_lookup;
          inputs.land_rent_cadastral_parameters=value.land_rent_cadastral_parameters;
          renderInputs();await settledCalculate();openTab('vri')}''',{'value':msk,'oldMo':source})
        assert page.evaluate('inputs._mo_calc||null') is None
        assert page.evaluate('landRentTerritory().region')=='msk'
        assert page.evaluate('inputs.land_rent_cadastral_mln')==300
        assert page.evaluate('inputs.land_rent_cadastral_target_mln')==600
