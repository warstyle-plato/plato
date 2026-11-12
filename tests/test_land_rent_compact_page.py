"""Actual PAGE: one readable rental table with honest state and editable disclosures."""
import re
from pathlib import Path

import pytest

import main
from tests import browser

core=main.core
OUTPUT=Path('/tmp/plato-land-rent-compact-proof')


@pytest.fixture(params=[(390,'/'),(1440,'/'),(390,'/classic'),(1440,'/classic')],
                ids=['390-main','1440-main','390-classic','1440-classic'])
def rental_page(request,monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from main_registry import app as registry_app
    width,surface=request.param
    view=f"{width}-{'main' if surface=='/' else 'classic'}"
    monkeypatch.setattr(core,'_telegram_token',lambda:'')
    monkeypatch.setattr(core,'require_calc_access',lambda *a,**k:{'allowed':True})
    with browser.serve(registry_app,18887) as base,sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page=chromium.new_page(viewport={'width':width,'height':1000},locale='ru-RU')
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base.rstrip('/')+surface,wait_until='domcontentloaded')
            browser.wait_for_result(page)
            # Поверхность та, что заказана: корень — со слоем IA, /classic — без.
            if surface=='/':
                expect(page.locator('body')).to_have_class(re.compile(r'\bia-on\b'))
            else:
                assert not page.locator('body.ia-on').count()
            page.clock.set_fixed_time('2026-11-09T12:00:00Z')
            page.evaluate("""async()=>{
                Object.assign(inputs,{land_right:'lease',vri_region:'msk',land_rent_mode:'msk_mkd_3_2',
                  land_rent_preset_confirmed:true,land_rent_cadastral_mln:1000,
                  land_rent_regime_start:'2027-01-01',land_rent_manual_cutoff:'2030-01-01',
                  land_rent_termination_date:'2030-01-01',land_rent_payment_mode:'monthly_estimate',
                  land_rent_premium_status:'not_applicable',land_rent_premium_source:'Синтетическое основание',
                  land_rent_rates:[{year:1,rate_pct:2},{year:2,rate_pct:3}],
                  land_rent_tail_rule:'repeat_last',land_rent_vat_treatment:'public_exempt',
                  land_rent_source:'Синтетический договор',land_rent_forecast_index_pct:null,
                  project_start:'2027-01-01',ird_months:12,construction_months:24,
                  social_mode:'Денежная компенсация',social_compensation_mln:0,
                  _glavapu_import:{normalized:{cadastral_quarter:'77:01:0000001',site_area_ha:1},
                    recognized:['77:01:0000001:11'],mappings:{inputs:{vri_region:'msk'}}},
                  _field_origin:{'inputs.land_rent_cadastral_mln':{source:'document',text:'Из синтетического договора'}}});
                renderInputs();await settledCalculate();
            }""")
            browser.open_vri(page)
            yield page,view,errors
            assert not errors,errors


def open_detail(page,name):
    target=page.locator(f'#landRentEditor details[data-land-rent-detail="{name}"]')
    if not target.evaluate('(e)=>e.open'):
        target.locator('summary').first.click()
    return target


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert page.locator('#landRentEditor').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')


def test_compact_actual_component_shows_one_table_status_and_readable_money(rental_page):
    from playwright.sync_api import expect
    page,view,errors=rental_page
    root=page.locator('#landRentEditor')
    expect(root.locator('.lr-amount')).to_have_text('60 млн ₽')
    expect(root.locator('.lr-cutoff')).to_contain_text('01.01.2030')
    expect(root.locator('.lr-status')).to_contain_text('Предварительный расчёт')
    expect(root).to_contain_text('Из синтетического договора')
    rows=root.locator('.lr-main-table tbody tr')
    assert rows.count()==3
    assert [r.locator('td').last.inner_text() for r in rows.all()]==['15 млн ₽','15 млн ₽','30 млн ₽']
    assert root.locator('table:visible').count()==1
    assert root.locator('details[open]').count()==0
    assert 'млрд' not in root.locator('#landRentSummary').inner_text()
    assert root.locator('.lr-tools .hint').evaluate('''e=>{
        const range=document.createRange();range.selectNodeContents(e);
        const box=e.closest('#landRentEditor').getBoundingClientRect();
        return [...range.getClientRects()].every(r=>r.left>=box.left-1&&r.right<=box.right+1);
    }''')
    fits(page)
    assert root.bounding_box()['height']<1150
    OUTPUT.mkdir(mode=0o700,exist_ok=True)
    root.screenshot(path=str(OUTPUT/f'actual-{view}.png'))
    page.locator('#landRentEditor').scroll_into_view_if_needed()
    page.screenshot(path=str(OUTPUT/f'context-vri-{view}.png'),full_page=True)
    conditions=open_detail(page,'conditions')
    expect(conditions).to_contain_text('273-ПП')
    expect(conditions).to_contain_text('6-й год: 8%')
    assert conditions.locator('a[href^="https://"]').count()==1
    assert conditions.locator('a[href^="https://www.mos.ru/authority/documents/"]').count()==1
    expect(conditions).to_contain_text('Открыть текст акта: 273-ПП на mos.ru')
    page.evaluate("window.savedLandRentControl=document.getElementById('f_land_rent_cadastral_mln')")
    page.evaluate('async()=>{await settledCalculate()}')
    assert page.evaluate("savedLandRentControl===document.getElementById('f_land_rent_cadastral_mln')")
    page.locator('#f_land_rent_cadastral_mln').fill('900')
    page.get_by_role('button',name='Изменить ставки вручную',exact=True).click()
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_mode')=='manual'
    assert page.evaluate('inputs.land_rent_cadastral_mln')==900
    assert page.evaluate('inputs.land_rent_rates.map(r=>r.rate_pct)')==page.evaluate('LAND_RENT_SPEC.presets.msk_mkd_3_2.rates')
    fits(page)


def test_real_blur_edit_keeps_unknown_zero_origins_and_mode_confirmation_separate(rental_page):
    from playwright.sync_api import expect
    page,view,errors=rental_page
    open_detail(page,'conditions')
    page.locator('#f_land_rent_mode').select_option('msk_mkd_arch_confirmed')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_preset_confirmed') is False
    # Counted, but preliminary until the regional rates are checked against the contract.
    expect(page.locator('.lr-status')).to_contain_text('Предварительный расчёт')
    expect(page.locator('.lr-status')).to_contain_text('договор с ними ещё не сверен')
    assert page.evaluate('lastResult.land_rent.construction_total')>0
    conditions=open_detail(page,'conditions')
    conditions.locator('#f_land_rent_preset_confirmed').check()
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_preset_confirmed') is True
    page.locator('#f_land_rent_mode').select_option('manual')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_preset_confirmed') is False
    assert page.evaluate('inputs.land_rent_rates')==[{'year':1,'rate_pct':2},{'year':2,'rate_pct':3}]
    rate=page.locator("input[aria-label='Ставка за 1 год']")
    rate.fill('');rate.press('Tab')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_rates[0].rate_pct') is None
    expect(page.locator('.lr-amount')).to_have_text('Не определено')
    rate=page.locator("input[aria-label='Ставка за 1 год']")
    rate.fill('0');rate.press('Tab')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_rates[0].rate_pct')==0
    assert page.evaluate("inputs._field_origin['inputs.land_rent_rates'].source")=='manual'
    assert page.evaluate('lastResult.land_rent.construction_total') is not None
    page.locator('#f_land_rent_cadastral_mln').fill('900')
    scope=open_detail(page,'scope')
    browser.wait_for_result(page)
    assert page.evaluate("inputs._field_origin['inputs.land_rent_cadastral_mln'].source")=='manual'
    scope.locator('#f_land_rent_manual_cutoff').fill('2029-12-17')
    scope.locator('#f_land_rent_manual_cutoff').press('Tab')
    browser.wait_for_result(page)
    expect(page.locator('.lr-cutoff')).to_contain_text('17.12.2029')
    payments=open_detail(page,'payments')
    payments.locator('#f_land_rent_payment_mode').select_option('manual')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_payment_mode')=='manual'
    assert page.locator('#f_land_rent_termination_date').input_value()=='2030-01-01'
    fits(page)


def test_mo_unknown_indices_explicit_zero_forecast_and_other_form_collection(rental_page):
    from playwright.sync_api import expect
    page,view,errors=rental_page
    page.evaluate("""async()=>{
        delete inputs._glavapu_import;
        Object.assign(inputs,{vri_region:'mo',land_rent_mode:'mo_housing_new_2026',
          _mo_calc:{vri:{parcels:[{cadastral_number:'50:01:0000001:11',cadastral_value_rub:1000000000}]},territory:{site_area_ha:1}},
          land_rent_contract_date:'2027-01-01',land_rent_public_scope:'regional',
          land_rent_grant_basis:'ordinary_nonauction',land_rent_mo_cadastral_unchanged:true,
          land_rent_preset_confirmed:true,land_rent_calendar_indices:[{year:2028,index_pct:null},{year:2029,index_pct:null}],
          land_rent_indices_origin:{},land_rent_forecast_index_pct:null});
        renderInputs();await settledCalculate();
    }""")
    conditions=open_detail(page,'conditions')
    conditions.locator('#f_land_rent_preset_confirmed').check()
    browser.wait_for_result(page)
    indices=open_detail(page,'indices')
    assert indices.locator('#f_land_rent_forecast_index_pct').input_value()==''
    assert page.evaluate('inputs.land_rent_forecast_index_pct') is None
    expect(indices.locator('.lr-index-origin').first).to_have_text('Индекс не задан')
    zero=indices.locator("input[aria-label='Индекс МО на 2028 год']")
    zero.fill('0');zero.press('Tab')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2028).index_pct')==0
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2029).index_pct') is None
    forecast=page.locator('#f_land_rent_forecast_index_pct')
    forecast.fill('4');forecast.press('Tab')
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2029).index_pct') is None
    page.get_by_role('button',name='Заполнить пустые будущие годы моим прогнозом').click()
    browser.wait_for_result(page)
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2028).index_pct')==0
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2029).index_pct')==4
    assert page.evaluate('inputs.land_rent_indices_origin[2029].source')=='forecast'
    expect(page.locator('#landRentEditor .lr-index-table')).to_contain_text('Прогноз пользователя')
    page.locator('#f_ird_months').evaluate("e=>e.value='13'")
    page.evaluate('async()=>{await settledCalculate()}')
    assert page.evaluate('inputs.ird_months')==13
    assert page.evaluate('inputs.land_rent_forecast_index_pct')==4
    assert page.locator('#f_land_rent_regime_start').input_value()=='2027-01-01'
    fits(page)
    OUTPUT.mkdir(mode=0o700,exist_ok=True)
    expect(page.locator('.lr-main-table thead')).to_contain_text('Базовая ставка')
    expect(page.locator('.lr-index-note')).to_contain_text('Суммы включают календарные индексы')
    expect(page.locator('.lr-amount')).to_have_text('182,4 млн ₽')
    assert [row.locator('td').last.inner_text() for row in page.locator('.lr-main-table tbody tr').all()]==['60 млн ₽','60 млн ₽','62,4 млн ₽']
    if conditions.evaluate('(e)=>e.open'):
        conditions.locator('summary').first.click()
    page.locator('#landRentEditor').screenshot(path=str(OUTPUT/f'mo-expanded-{view}.png'))
    page.locator('#landRentEditor details[data-land-rent-detail="indices"] > summary').click()
    page.locator('#landRentEditor').screenshot(path=str(OUTPUT/f'mo-collapsed-{view}.png'))
    page.reload(wait_until='domcontentloaded')
    browser.wait_for_result(page)
    browser.open_vri(page)
    assert page.evaluate('landRentTerritory().region')=='mo'
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2028).index_pct')==0
    assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2029).index_pct')==4
    assert page.evaluate('inputs.land_rent_indices_origin[2029].source')=='forecast'


@pytest.mark.parametrize('territory_kind',['moscow77','new_moscow50','mo50','other66'])
def test_region_comes_from_applied_territory_not_cadastral_prefix_or_a_region_switch(rental_page,territory_kind):
    page,view,errors=rental_page
    state=page.evaluate("""kind=>{
        for(const key of ['_glavapu_import','_mo_calc','_other_region','_cadastral_analysis','_land_lookup'])delete inputs[key];
        inputs.land_rent_mode='unspecified';inputs.land_rent_preset_confirmed=true;
        inputs.land_rent_cadastral_mln=null;delete inputs._field_origin['inputs.land_rent_cadastral_mln'];
        if(kind==='moscow77'||kind==='new_moscow50'){
          const prefix=kind==='moscow77'?'77':'50';inputs.vri_region='msk';
          inputs._glavapu_import={normalized:{cadastral_quarter:prefix+':01:0000001',site_area_ha:1},
            recognized:[prefix+':01:0000001:11'],mappings:{inputs:{vri_region:'msk'}}};
          inputs._cadastral_analysis={territory:{inside_moscow:true}};
          // ЕГРН lookup: the applied parcel and a stranger that is not part of the territory.
          inputs._land_lookup={results:[{found:true,kind:'land',cadastral_number:prefix+':01:0000001:11',cadastral_value_mln:345.6},
            {found:true,kind:'land',cadastral_number:prefix+':01:0000009:99',cadastral_value_mln:1000}]};
        }else if(kind==='mo50'){
          inputs.vri_region='mo';inputs._mo_calc={territory:{site_area_ha:1},
            vri:{parcels:[{cadastral_number:'50:01:0000001:11',cadastral_value_rub:123000000}]}};
        }else{
          inputs.vri_region='other';inputs._other_region={region:'Свердловская область',
            numbers:['66:01:0000001:11'],area_ha:1,cadastral_value_mln:234};
        }
        renderInputs();
        return {region:landRentTerritory().region,mode:inputs.land_rent_mode,
          confirmed:inputs.land_rent_preset_confirmed,base:inputs.land_rent_cadastral_mln};
    }""",territory_kind)
    conditions=open_detail(page,'conditions')
    values=conditions.locator('#f_land_rent_mode option').evaluate_all('(opts)=>opts.map(o=>o.value)')
    assert state['confirmed'] is False
    if territory_kind in ['moscow77','new_moscow50']:
        assert state['region']=='msk' and state['mode']=='msk_mkd_3_2'
        assert 'msk_mkd_3_2' in values and 'mo_housing_new_2026' not in values
        assert state['base']==345.6  # Moscow is filled from ЕГРН too
    elif territory_kind=='mo50':
        assert state['region']=='mo' and state['mode']=='mo_housing_new_2026'
        assert 'mo_housing_new_2026' in values and not any(v.startswith('msk_') for v in values)
        assert state['base']==123
    else:
        assert state['region']=='other' and state['mode']=='manual'
        assert not any(v in ['mo_housing_new_2026','msk_mkd_3_2','msk_mkd_arch_confirmed'] for v in values)
        assert state['base']==234
    assert page.locator('#landRentEditor > .fields #f_land_rent_mode').count()==0
    fits(page)


def test_unknown_preview_manual_import_and_explicit_zero_do_not_become_regional_defaults(rental_page):
    page,view,errors=rental_page
    preview=page.evaluate("""()=>{
        inputs._cadastral_analysis={recognized:['50:01:0000001:12'],territory:{inside_moscow:false}};
        moResult={inputs:{vri_region:'mo'},vri:{parcels:[{cadastral_number:'50:01:0000001:12',cadastral_value_rub:456000000}]}};
        renderInputs();return {region:landRentTerritory().region,mode:inputs.land_rent_mode,
          base:inputs.land_rent_cadastral_mln,confirmed:inputs.land_rent_preset_confirmed,rates:inputs.land_rent_rates};
    }""")
    assert preview=={'region':'msk','mode':'msk_mkd_3_2','base':1000,'confirmed':True,
                     'rates':[{'year':1,'rate_pct':2},{'year':2,'rate_pct':3}]}
    state=page.evaluate("""()=>{
        for(const key of ['_glavapu_import','_mo_calc','_other_region'])delete inputs[key];
        inputs.vri_region='msk';inputs.land_rent_mode='unspecified';
        inputs._cadastral_analysis={recognized:['77:01:0000001:11'],territory:{inside_moscow:true}};
        renderInputs();return {region:landRentTerritory().region,mode:inputs.land_rent_mode};
    }""")
    assert state=={'region':None,'mode':'unspecified'}
    conditions=open_detail(page,'conditions')
    values=conditions.locator('#f_land_rent_mode option').evaluate_all('(opts)=>opts.map(o=>o.value)')
    assert values==['unspecified','manual','not_applicable']
    state=page.evaluate("""()=>{
        inputs.land_rent_mode='manual';inputs.land_rent_cadastral_mln=0;
        inputs.land_rent_rates=[{year:1,rate_pct:null},{year:2,rate_pct:0}];
        inputs.land_rent_regime_start='2027-01-17';inputs.land_rent_source='Импортированный договор';
        inputs._field_origin['inputs.land_rent_cadastral_mln']={source:'manual',text:'вписано вручную'};
        inputs._manual_tep_import={source:{label:'Синтетический импорт'}};
        inputs._cadastral_analysis={recognized:['50:01:0000001:12'],territory:{inside_moscow:false}};
        renderInputs();return {mode:inputs.land_rent_mode,base:inputs.land_rent_cadastral_mln,
          rates:inputs.land_rent_rates,start:inputs.land_rent_regime_start};
    }""")
    assert state=={'mode':'manual','base':0,'rates':[{'year':1,'rate_pct':None},{'year':2,'rate_pct':0}],'start':'2027-01-17'}
    # An applied MO source may offer a cadastral base; explicit manual zero still owns its field.
    state=page.evaluate("""()=>{
        inputs.vri_region='mo';inputs._mo_calc={vri:{parcels:[{cadastral_number:'50:01:0000001:11',cadastral_value_rub:123000000}]}};
        renderInputs();return {mode:inputs.land_rent_mode,base:inputs.land_rent_cadastral_mln,rates:inputs.land_rent_rates};
    }""")
    assert state=={'mode':'manual','base':0,'rates':[{'year':1,'rate_pct':None},{'year':2,'rate_pct':0}]}
    value=page.evaluate("""()=>{
        inputs.land_rent_cadastral_mln=null;delete inputs._field_origin['inputs.land_rent_cadastral_mln'];
        inputs._mo_calc.vri.parcels.push({cadastral_number:'50:01:0000001:12',cadastral_value_rub:456000000});
        renderInputs();return {base:inputs.land_rent_cadastral_mln,origin:inputs._field_origin['inputs.land_rent_cadastral_mln'].text};
    }""")
    assert value['base']==579 and '50:01:0000001:11, 50:01:0000001:12' in value['origin']
    # A parcel that is not leased leaves the sum; the owner's typed value is never replaced.
    page.locator('#landRentEditor [data-land-rent-parcel="50:01:0000001:11"]').uncheck()
    page.wait_for_function("inputs.land_rent_cadastral_mln===456")
    assert 'Не в аренде: 50:01:0000001:11' in page.evaluate("inputs._field_origin['inputs.land_rent_cadastral_mln'].text")
    field=page.locator('#landRentEditor #f_land_rent_cadastral_mln')
    field.fill('500');field.press('Tab')
    page.locator('#landRentEditor [data-land-rent-parcel="50:01:0000001:11"]').check()
    page.wait_for_function("(inputs.land_rent_parcels_excluded||[]).length===0")
    assert page.evaluate('inputs.land_rent_cadastral_mln')==500
    field=page.locator('#landRentEditor #f_land_rent_cadastral_mln')
    field.fill('');field.press('Tab')
    page.wait_for_function("inputs.land_rent_cadastral_mln===579")
    assert page.evaluate("()=>{inputs.vri_region='';return landRentTerritory().region}") is None
    fits(page)


@pytest.mark.parametrize('new_silent',[False,True])
def test_same_mo_silent_recalculation_keeps_contract_but_another_applied_parcel_clears_it(rental_page,new_silent):
    page,view,errors=rental_page
    state=page.evaluate("""async()=>{
        delete inputs._glavapu_import;
        const parcel={cadastral_number:'50:01:0000001:11',cadastral_value_rub:123000000};
        inputs.vri_region='mo';inputs.land_right='lease';
        inputs._mo_calc={query:parcel.cadastral_number,vri:{parcels:[parcel]},territory:{site_area_ha:1}};
        Object.assign(inputs,{land_rent_mode:'manual',land_rent_rates:[{year:1,rate_pct:0},{year:2,rate_pct:null}],
          land_rent_cadastral_mln:321,land_rent_regime_start:'2027-01-17',
          land_rent_source:'Синтетический договор для этого участка'});
        inputs._field_origin['inputs.land_rent_cadastral_mln']={source:'manual',text:'Моя подтверждённая база'};
        const savedTep=JSON.parse(JSON.stringify(tep));
        moResult={query:parcel.cadastral_number,inputs:{vri_region:'mo',land_right:'lease'},
          territory:{site_area_ha:1},vri:{parcels:[parcel]},tep:savedTep,density_sqm_per_ha:30000};
        // Очерёдность — решение пользователя: тихий пересчёт того же участка её не сбрасывает.
        phasing=makeDefaultPhasing(2);
        await applyMo({silent:true});
        return {mode:inputs.land_rent_mode,rates:inputs.land_rent_rates,base:inputs.land_rent_cadastral_mln,
          start:inputs.land_rent_regime_start,origin:inputs._field_origin['inputs.land_rent_cadastral_mln'],
          phases:phasing.phase_count};
    }""")
    assert state=={'mode':'manual','rates':[{'year':1,'rate_pct':0},{'year':2,'rate_pct':None}],
                   'base':321,'start':'2027-01-17','origin':{'source':'manual','text':'Моя подтверждённая база'},
                   'phases':2}
    state=page.evaluate("""async silent=>{
        const parcel={cadastral_number:'50:01:0000001:12',cadastral_value_rub:456000000};
        moResult={query:parcel.cadastral_number,inputs:{vri_region:'mo',land_right:'lease'},
          territory:{site_area_ha:2},vri:{parcels:[parcel]},tep:JSON.parse(JSON.stringify(tep)),density_sqm_per_ha:30000};
        await applyMo({silent});
        return {mode:inputs.land_rent_mode,rates:inputs.land_rent_rates??null,base:inputs.land_rent_cadastral_mln,
          start:inputs.land_rent_regime_start??null,confirmed:inputs.land_rent_preset_confirmed};
    }""",new_silent)
    assert state=={'mode':'mo_housing_new_2026','rates':None,'base':456,'start':None,'confirmed':False}
    fits(page)


def test_opening_another_saved_project_keeps_its_own_confirmed_contract(rental_page):
    """Открытый проект приносит свой участок и свой договор: это не смена участка.

    Участок прошлого проекта (Москва) не должен доживать до открытого (МО):
    иначе его подтверждённые условия читались бы как унаследованные от другого
    участка и снимались, а расчёт аренды прятался бы как чужой.
    """
    page,view,errors=rental_page
    assert page.evaluate('landRentTerritory().region')=='msk'
    state=page.evaluate("""async()=>{
        const other=JSON.parse(JSON.stringify(projectStorePayload().payload));
        delete other.inputs._glavapu_import;
        Object.assign(other.inputs,{vri_region:'mo',land_rent_mode:'mo_housing_new_2026',land_rent_preset_confirmed:true,
          _mo_calc:{vri:{parcels:[{cadastral_number:'50:01:0000001:11',cadastral_value_rub:1000000000}]},territory:{site_area_ha:1}},
          land_rent_contract_date:'2027-01-01',land_rent_public_scope:'regional',
          land_rent_grant_basis:'ordinary_nonauction',land_rent_mo_cadastral_unchanged:true});
        applyProjectSnapshot(other);await settledCalculate();
        return {region:landRentTerritory().region,mode:inputs.land_rent_mode,
          confirmed:inputs.land_rent_preset_confirmed,shown:landRentShownResult()?.mode||null};
    }""")
    assert state=={'region':'mo','mode':'mo_housing_new_2026','confirmed':True,'shown':'mo_housing_new_2026'}


@pytest.mark.parametrize('kind',['hotel','nonresidential'])
def test_current_project_type_excludes_housing_presets_before_any_new_result(rental_page,kind):
    page,view,errors=rental_page
    state=page.evaluate("""kind=>{
        const previous=lastResult.land_rent.mode;
        inputs.project_kind=kind;renderInputs();
        return {previous,current:inputs.land_rent_mode,confirmed:inputs.land_rent_preset_confirmed,
          manual:inputs.land_rent_rates};
    }""",kind)
    assert state['previous']=='msk_mkd_3_2'
    assert state['current']=='manual' and state['confirmed'] is False
    assert state['manual']==[{'year':1,'rate_pct':2},{'year':2,'rate_pct':3}]
    conditions=open_detail(page,'conditions')
    values=conditions.locator('#f_land_rent_mode option').evaluate_all('(opts)=>opts.map(o=>o.value)')
    assert values==['unspecified','manual','not_applicable']


def test_queues_replace_single_cutoff_and_premium_question_uses_composition_evidence(rental_page):
    page,view,errors=rental_page
    # A calculated fee with no composition evidence keeps the question visible.
    page.evaluate("""async()=>{inputs.land_rights_cost_mln=50;inputs.land_rent_premium_status='unknown';delete inputs._field_origin['inputs.land_rights_cost_mln'];
        renderInputs();await settledCalculate()}""")
    browser.open_vri(page)
    open_detail(page,'payments')
    assert page.locator('#f_land_rent_premium_status').count()==1
    assert page.locator('#f_land_rent_cadastral_target_mln').count()==1
    # Explicit source semantics answer composition without asking the owner.
    page.evaluate("""async()=>{fieldOrigins()['inputs.land_rights_cost_mln']={source:'document',
        rent_premium:{schema:2,included_in_vri:false,fee_mln:50,method:'vri_manual_payment',land_right:'lease',source:'Состав расчёта: доплата отдельно'}};
        await settledCalculate();renderInputs()}""")
    browser.open_vri(page)
    open_detail(page,'payments')
    assert page.locator('#f_land_rent_premium_status').count()==0
    assert 'доплата отдельно' in page.locator('.lr-premium').inner_text()
    # Removing the proof restores the editable owner answer.

    page.evaluate("""async()=>{fieldOrigins()['inputs.land_rights_cost_mln']={source:'manual'};
        renderInputs();await settledCalculate()}""")
    browser.open_vri(page)
    open_detail(page,'payments')
    assert page.locator('#f_land_rent_premium_status').count()==1
    scope=open_detail(page,'scope')
    assert scope.locator('#f_land_rent_manual_cutoff').count()==1
    page.evaluate("""async()=>{phasing=makeDefaultPhasing(2);phasing.enabled=true;phasing.user_enabled=true;
        renderInputs();await settledCalculate()}""")
    page.wait_for_function("()=>(landRentResult()?.phase_land||[]).length===2",timeout=60000)
    browser.open_vri(page)
    scope=open_detail(page,'scope')
    assert scope.locator('#f_land_rent_manual_cutoff').count()==0
    assert scope.locator('.lr-phase-table tbody tr').count()==2
    expect_basis=scope.locator('.lr-phases').inner_text()
    assert 'пропорционально общей площади объектов каждой очереди' in expect_basis
    assert 'м² общей площади' in expect_basis
    assert 'ещё не введены, в том числе ещё не начатыми' in scope.inner_text()


def test_default_dates_follow_the_economics_until_typed_and_queues_add_up(rental_page):
    page,view,errors=rental_page
    set_value="""([sel,v])=>{const el=document.querySelector(sel);el.value=v;el.dispatchEvent(new Event('change',{bubbles:true}))}"""
    page.evaluate("""async()=>{delete inputs.land_rent_regime_start;delete inputs.land_rent_manual_cutoff;
        renderInputs();await settledCalculate()}""")
    browser.open_vri(page)
    # Начало аренды видно в поле, но во вводные не пишется и следует за стартом проекта.
    assert page.locator('#f_land_rent_regime_start').input_value()=='2027-01-01'
    assert 'По умолчанию — дата начала проекта' in page.locator('#landRentEditor').inner_text()
    page.evaluate("""async()=>{inputs.project_start='2027-03-01';renderInputs();await settledCalculate()}""")
    browser.open_vri(page)
    assert page.locator('#f_land_rent_regime_start').input_value()=='2027-03-01'
    assert page.evaluate("()=>inputs.land_rent_regime_start")is None
    assert page.evaluate("()=>landRentResult().regime_start")=='2027-03-01'
    page.evaluate(set_value,['#f_land_rent_regime_start','2027-05-01'])
    page.evaluate("async()=>{await settledCalculate()}")
    assert page.evaluate("()=>inputs.land_rent_regime_start")=='2027-05-01'
    assert 'Дата указана вручную' in page.locator('[data-land-rent-hint="land_rent_regime_start"]').inner_text()
    browser.open_vri(page)
    page.evaluate(set_value,['#f_land_rent_regime_start',''])
    page.evaluate("async()=>{await settledCalculate()}")
    browser.open_vri(page)
    assert page.evaluate("()=>inputs.land_rent_regime_start")is None
    assert page.locator('#f_land_rent_regime_start').input_value()=='2027-03-01'
    # «Учитывать аренду до» показывает дату ввода из экономики.
    scope=open_detail(page,'scope')
    derived=page.evaluate("()=>landRentResult().derived_rve")
    assert derived and scope.locator('#f_land_rent_manual_cutoff').input_value()==derived
    assert page.evaluate("()=>inputs.land_rent_manual_cutoff")is None
    assert 'граница расчёта, а не прекращение договора' in scope.inner_text()
    # Очереди: таблица долей с метрами, итог по участку равен сумме очередей.
    page.evaluate("""async()=>{phasing=makeDefaultPhasing(2);phasing.enabled=true;phasing.user_enabled=true;
        renderInputs();await settledCalculate()}""")
    page.wait_for_function("()=>(landRentResult()?.phase_land||[]).length===2",timeout=60000)
    rent=page.evaluate("()=>landRentResult()")
    assert rent['phase_share_basis']=='total_area'
    assert sum(p['share'] for p in rent['phase_land'])==pytest.approx(1)
    assert sum(p['accrual_total'] for p in rent['phase_land'])==pytest.approx(rent['known_total'])
    assert sum(p['cash_total'] for p in rent['phase_land'])==pytest.approx(rent['cash_total'])
    browser.open_vri(page)
    scope=open_detail(page,'scope')
    assert scope.locator('.lr-phase-table tbody tr').count()==2
    assert scope.locator('.lr-phase-years tbody tr').count()>=1
    first=rent['phase_land'][0]
    assert scope.locator('[data-land-rent-release="0"]').input_value()==first['derived_rve']
    # Дата выхода доли — только для аренды: ввод очереди не меняется, очистка возвращает его.
    # Вводим как человек: поле в фокусе, потом уход из него; таблица на экране
    # обязана обновиться без повторного открытия блока.
    field=scope.locator('[data-land-rent-release="0"]')
    field.fill('2027-12-01')
    page.evaluate("async()=>{await settledCalculate()}")
    moved=page.evaluate("()=>landRentResult().phase_land[0]")
    assert moved['rve']=='2027-12-01' and moved['release_origin']=='manual'
    assert moved['commissioning']==first['commissioning']
    field.blur()
    row=scope.locator('.lr-phase-table tbody tr').first
    page.wait_for_function("()=>document.querySelector('.lr-phase-table tbody tr').innerText.includes('Ваша дата')",timeout=10000)
    assert page.evaluate("()=>landRentMoney(landRentResult().phase_land[0].accrual_total)") in row.inner_text()
    assert scope.locator('[data-land-rent-release="0"]').input_value()=='2027-12-01'
    scope.locator('[data-land-rent-release="0"]').fill('')
    page.evaluate("async()=>{await settledCalculate()}")
    scope.locator('[data-land-rent-release="0"]').blur()
    back=page.evaluate("()=>[phasing.phases[0].land_rent_release_date,landRentResult().phase_land[0]]")
    assert back[0] is None and back[1]['release_origin']=='derived' and back[1]['rve']==first['rve']
    page.wait_for_function("d=>document.querySelector('[data-land-rent-release=\"0\"]').value===d",arg=first['derived_rve'],timeout=10000)
    assert 'Ваша дата' not in scope.locator('.lr-phase-table tbody tr').first.inner_text()
    assert not page.evaluate("()=>document.documentElement.scrollWidth>window.innerWidth")
