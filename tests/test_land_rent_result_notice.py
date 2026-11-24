"""Detailed lease qualifications belong to the calculator, with one result link."""
import copy
import socket

import pytest

import main
from tests import browser
from tests.test_land_rent_result_clarity import rental_inputs

core=main.core
DETAIL='Учебное условие договора: 6% после ввода; проверить дату и сведения собственника.'


def open_results(page,surface):
    if surface=='/':
        hint=page.locator('#iaFabHint button')
        if hint.count(): hint.click()
        page.locator('.ia-nav').get_by_role('button',name='Результат',exact=True).click()
    else:
        page.locator('button[data-tab="report"]').click()


def projection(page):
    return page.evaluate('''()=>JSON.stringify({inputs,summary:lastResult.summary,
        capex:lastResult.capex,finance:lastResult.finance,land_rent:lastResult.land_rent,
        financing:lastResult.report.financing})''')


def test_backend_tiles_keep_document_qualifications_and_leave_model_and_inputs_unchanged():
    x=rental_inputs(land_rent_regime_start=None,land_rights_cost_mln=0)
    result=core.calculate(core.CalcRequest(inputs=x,tep=copy.deepcopy(core.TEP_DEFAULT),rates=[]))
    result['summary']['preliminary_reason']=DETAIL
    before=copy.deepcopy((result,x))
    block=core.entry_price_block({'consolidated':result},x,None)
    assert block['verdict']==core._entry_price_metric_verdict({'consolidated':result})
    assert all(DETAIL not in t['note'] for t in block['tiles'])
    assert (result,x)==before
    result['summary']['intake_qualification']={'status':'conditional','reason':'Учебный документ: проверить обязательства.'}
    block=core.entry_price_block({'consolidated':result},x,None)
    for index in [0,2,3]:
        assert 'Учебный документ: проверить обязательства.' in block['tiles'][index]['note']
    assert 'неоценённые обязательства' in block['verdict']['title']


@pytest.mark.parametrize('surface',['/','/classic'],ids=['native','classic'])
@pytest.mark.parametrize('width',[390,1440])
def test_actual_result_has_one_notice_and_opens_the_lease_conditions(width,surface,monkeypatch,tmp_path):
    from playwright.sync_api import expect,sync_playwright
    from main_registry import app
    monkeypatch.setattr(core,'_telegram_token',lambda:'')
    monkeypatch.setattr(core,'require_calc_access',lambda *a,**kw:{'allowed':True})
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    with browser.serve(app,port) as base,sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chrome:
            page=chrome.new_page(viewport={'width':width,'height':1000},locale='ru-RU')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            pending=[]
            page.route('**/ia/goal-seek',lambda route:pending.append(route))
            page.goto(base+surface,wait_until='domcontentloaded');browser.wait_for_result(page)
            # Real model first; only its display qualification is made distinctive.
            page.evaluate('''async x=>{Object.assign(inputs,x);renderInputs();await settledCalculate()}''',
                          rental_inputs(land_rent_regime_start=None,land_rights_cost_mln=0))
            page.evaluate('''detail=>{
                lastResult.land_rent.missing=[];lastResult.land_rent.financial_missing=[detail];
                lastResult.summary.preliminary_reason=detail;
                lastResult.summary.land_rent_sum.reason=detail;renderResult();
            }''',DETAIL)
            before=projection(page)
            page.evaluate('()=>{renderResult();renderResult()}')
            assert projection(page)==before
            open_results(page,surface)
            notice=page.locator('#landRentResultNotice')
            expect(notice).to_have_count(1)
            expect(notice).to_have_text('Расчёт с допущениями по аренде. Проверить аренду')
            row=page.locator('#projectParamsTable tr').filter(has=page.get_by_text('Аренда земли участка',exact=True))
            expect(row).to_contain_text('Учтённая часть суммы.')
            for host in ['#reportKpi','#projectParamsTable']+(['#iaVerdict'] if surface=='/' else []):
                assert DETAIL not in page.locator(host).inner_text()
            if surface=='/':
                expect(page.locator('#iaVerdictTitle')).to_have_text(page.evaluate('lastResult.report.entry_price_verdict.title'))
                assert page.locator('#iaVerdict').evaluate("e=>e.classList.contains('pass')") == (page.evaluate('lastResult.report.entry_price_verdict.tone') == 'pass')
                assert pending
                result=page.evaluate('lastResult');x=page.evaluate('inputs')
                goal={'available':True,'target_metric':'llcr','target_llcr':1.2,
                      'current':{'variable':100},'solution':{'variable':150,'change_abs':50},
                      'engine_version':'synthetic-local','computed_at':'2026-11-17T20:30:00+00:00'}
                block=core.entry_price_block({'consolidated':result},x,goal)
                pending[-1].fulfill(json={**goal,**block,'fingerprint':'synthetic-local-goal'})
                expect(page.locator('#iaVerdictStamp')).to_contain_text('synthetic-local')
                expect(page.locator('#iaVerdictTitle')).to_have_text(page.evaluate('lastResult.report.entry_price_verdict.title'))
                assert DETAIL not in page.locator('#iaVerdictGrid').inner_text()
                assert projection(page)==before
            page.screenshot(path=str(tmp_path/f'rent-result-{surface.strip("/") or "main"}-{width}.png'))
            notice.get_by_role('button',name='Проверить аренду',exact=True).click()
            root=page.locator('#landRentEditor')
            expect(root).to_be_visible()
            assert root.evaluate('e=>e.open')
            assert root.locator('[data-land-rent-advanced]').evaluate('e=>e.open')
            assert root.locator('[data-land-rent-detail="conditions"]').evaluate('e=>e.open')
            expect(page.locator('#landRentSummary')).to_contain_text(DETAIL)
            assert page.locator('#vri').evaluate("e=>e.classList.contains('active')")
            if surface=='/':
                expect(page.locator('.ia-nav button.active')).to_have_text('Экономика')
                assert 'ВРИ' in page.locator('#iaSub button.active').inner_text()
            assert projection(page)==before
            page.screenshot(path=str(tmp_path/f'rent-conditions-{surface.strip("/") or "main"}-{width}.png'))
            # Known zero and absent sum remain distinct at the same native row.
            page.evaluate('''()=>{lastResult.capex.land_rent=0;lastResult.summary.land_rent_sum={known:true,reason:''};renderResult()}''')
            open_results(page,surface)
            expect(row).to_contain_text('0 ₽')
            page.evaluate('''()=>{lastResult.summary.land_rent_sum={known:false,reason:'Учебная причина'};renderResult()}''')
            expect(row).to_contain_text('Не определена.')
            assert '0 ₽' not in row.inner_text()
            page.evaluate("async()=>{inputs.land_right='ownership';renderInputs();await settledCalculate()}")
            expect(notice).to_have_count(0)
            expect(row).to_have_count(0)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            assert not errors,errors


@pytest.mark.parametrize('surface',['/','/classic'],ids=['native','classic'])
def test_nonrent_document_and_default_warnings_remain_literal_and_visible(surface,monkeypatch):
    from playwright.sync_api import expect,sync_playwright
    from main_registry import app
    monkeypatch.setattr(core,'_telegram_token',lambda:'')
    monkeypatch.setattr(core,'require_calc_access',lambda *a,**kw:{'allowed':True})
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    with browser.serve(app,port) as base,sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chrome:
            page=chrome.new_page(viewport={'width':1440,'height':1000},locale='ru-RU')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            pending=[]
            page.route('**/ia/goal-seek',lambda route:pending.append(route))
            page.goto(base+surface,wait_until='domcontentloaded');browser.wait_for_result(page)
            document='Проверить обязательства <em id="syntheticUnsafeDoc">учебного документа</em>.'
            page.evaluate('''reason=>{
                phaseBundle=null;
                lastResult.summary.intake_qualification={status:'conditional',reason};
                lastResult.report.financing.rve_unpaid=1000000;
                lastResult.report.financing.default_date='2030-01-01';
                renderResult();
            }''',document)
            open_results(page,surface)
            profit=page.locator('#reportKpi .kpi').filter(has=page.get_by_text('Чистая прибыль',exact=True))
            expect(profit).to_contain_text(document)
            expect(profit).to_contain_text('условная: в модели дефолт')
            assert not page.locator('#syntheticUnsafeDoc').count()
            assert page.evaluate('lastResult.summary.intake_qualification.reason')==document
            if surface=='/':
                assert pending
                result=page.evaluate('lastResult');x=page.evaluate('inputs')
                goal={'available':True,'target_metric':'llcr','target_llcr':1.2,
                      'current':{'variable':100},'solution':{'variable':150,'change_abs':50},
                      'engine_version':'synthetic-qualified','computed_at':'2026-11-17T20:30:00+00:00'}
                block=core.entry_price_block({'consolidated':result},x,goal)
                pending[-1].fulfill(json={**goal,**block,'fingerprint':'synthetic-qualified-goal'})
                expect(page.locator('#iaVerdictStamp')).to_contain_text('synthetic-qualified')
                assert not page.locator('#syntheticUnsafeDoc').count()
                expect(page.locator('#iaVerdictGrid')).to_contain_text(document)
            assert not errors,errors
