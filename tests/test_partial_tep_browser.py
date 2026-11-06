"""Native settings file flow preserves partial source facts on mobile and desktop."""
import json
import socket
from pathlib import Path
from urllib.parse import urlparse
import pytest
from browser import serve,chromium_or_skip
from playwright.sync_api import sync_playwright,expect
import main_legacy as core
import partial_tep


def source_file():
    return {'kind':partial_tep.KIND,'version':1,'name':'Синтетический неполный ТЭП',
            'source':{'label':'Синтетический документ <img src=x onerror=alert(1)>, стр.2'},'references':{'rnv_quarter':'2028-Q2'},
            'inputs':{'site_area_ha':.5,'storage_placement':'underground'},
            'tep':{'apartments':{'saleable':2000.,'units':10.},
                   'underground_parking':{'units':10.,'guest_units':2.}},
            'provenance':{'tep.apartments.saleable':{'origin':'source','pages':[2],'note':'Прямая площадь из синтетического документа'}}}


@pytest.mark.parametrize('width',[390,1440])
def test_import_edit_reload_export_and_resume_without_inference(tmp_path,monkeypatch,width):
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with serve(core.app,port) as base,sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page=browser.new_page(viewport={'width':width,'height':1000})
            errors=[];calculations=[];stale_routes=[]
            def partial_calls():return [item for item in calculations if "_partial_tep" in item.get("inputs",{})]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def routes(route):
                path=urlparse(route.request.url).path
                if not route.request.url.startswith(base):return route.abort()
                if path=='/' or path.startswith('/assets/'):return route.continue_()
                if path=='/projects/status':return route.fulfill(status=200,content_type='application/json',body=json.dumps({'configured':True,'calc_requires_login':True,'accepts_key':True}))
                if path in ['/calculate','/calculate-phased']:
                    calculations.append(route.request.post_data_json)
                    if '_partial_tep' not in route.request.post_data_json.get('inputs',{}):
                        stale_routes.append(route);return
                    return route.fulfill(status=422,content_type='application/json',body='{"detail":"Synthetic calculation intercepted after draft completion"}')
                return route.fulfill(status=200,content_type='application/json',body='{}')
            page.route('**/*',routes)
            page.add_init_script("localStorage.setItem('plato_projects_key','synthetic-local-only')")
            page.goto(base+'/',wait_until='domcontentloaded')
            page.wait_for_function('typeof preparePartialTep === "function" && projectsStorageReady && calcRun>0')
            # Seed a previous project's non-default figures; none may survive.
            page.evaluate('()=>{tep.apartments.gns=99999;tep.apartments.units=777;inputs.apartment_price_th=9999}')
            page.locator('#projectsButton').click()
            expect(page.get_by_role('button',name='Загрузить файл настроек',exact=True)).to_be_visible()
            page.once('dialog',lambda d:d.accept())
            page.locator('#settingsFileInput').set_input_files({'name':'synthetic-partial.json','mimeType':'application/json','buffer':json.dumps(source_file()).encode()})
            page.wait_for_function('partialTepMode()')
            assert page.evaluate('tep.apartments.saleable')==2000
            assert page.evaluate('tep.apartments.units')==10
            assert page.evaluate('tep.apartments.gns') is None
            assert page.evaluate('tep.underground_parking.gns') is None
            assert page.evaluate('tep.underground_parking.guest_units')==2
            assert page.evaluate('inputs.apartment_price_th') is None
            assert page.evaluate('inputs.main_above_th_per_sqm') is None
            assert page.evaluate('inputs.land_rights_cost_mln') is None
            assert page.locator('#partialTepNotice img').count()==0
            for guest in ['omitted',None]:
                value=source_file()
                if guest=='omitted':value['tep']['underground_parking'].pop('guest_units')
                else:value['tep']['underground_parking']['guest_units']=guest
                checked=page.evaluate('data=>preparePartialTep(data)',value)
                assert checked['tep']['underground_parking']['guest_units'] is None
                assert checked['inputs']['_partial_tep']['origins']['tep.underground_parking.guest_units']['origin']=='tbd'
            expect(page.locator('#partialTepNotice')).to_contain_text('заблокированы')
            expect(page.locator('#partialTepNotice')).to_contain_text('2028-Q2')
            row=page.locator('#tepBody tr').filter(has_text='Квартиры').first
            assert row.locator('input[type=number]').first.input_value()==''
            assert partial_calls()==[]
            assert stale_routes  # delayed response of the previous project's real request
            for pending in stale_routes:
                pending.fulfill(status=200,content_type='application/json',body=json.dumps({'summary':{},'tep':{'rows':[{'key':'apartments','gns':987654}]}}))
            page.wait_for_timeout(100)
            assert page.evaluate('lastResult') is None
            assert page.evaluate('tep.apartments.gns') is None
            page.evaluate('()=>{financeChart.innerHTML="<b>Previous economics must stay hidden</b>";openTab("finance")}')
            expect(page.locator('#financeChart')).not_to_be_visible()
            expect(page.locator('#finance .partial-tep-gate')).to_be_visible()
            page.get_by_role('button',name='ТЭП',exact=True).click()
            # A genuine manual edit changes only this field, not source units or area.
            expect(row.locator('input[type=number]').first).to_be_visible()
            page.screenshot(path=str(tmp_path/f'partial-synthetic-{width}.png'),full_page=True)
            row.locator('input[type=number]').first.fill('3000')
            row.locator('input[type=number]').first.dispatch_event('change')
            assert page.evaluate('tep.apartments.gns')==3000
            assert page.evaluate('tep.apartments.saleable')==2000
            assert page.evaluate('tep.apartments.units')==10
            assert page.evaluate("inputs._partial_tep.origins['tep.apartments.gns'].method")=='manual'
            assert partial_calls()==[]
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function('partialTepMode()')
            assert page.evaluate('tep.apartments.gns')==3000
            assert page.evaluate('tep.underground_parking.gns') is None
            assert page.evaluate("inputs._partial_tep.origins['tep.apartments.gns'].method")=='manual'
            page.locator('#projectsButton').click()
            with page.expect_download() as d:page.get_by_role('button',name='Скачать настройки текущего',exact=True).click()
            export=tmp_path/'export.json';d.value.save_as(str(export))
            saved=json.loads(export.read_text())
            assert saved['kind']==partial_tep.KIND
            assert saved['tep']['underground_parking']['gns'] is None
            assert saved['tep']['underground_parking']['guest_units']==2
            assert saved['inputs']['_partial_tep']['origins']['tep.apartments.gns']['method']=='manual'
            assert saved['inputs']['_partial_tep']['origins']['tep.apartments.saleable']['pages']==[2]
            page.once('dialog',lambda d:d.accept())
            page.locator('#settingsFileInput').set_input_files(str(export))
            assert page.evaluate('tep.apartments.units')==10
            assert page.evaluate('tep.underground_parking.gns') is None
            # Explicitly complete every missing source field as the user would.
            page.evaluate('''()=>{for(const item of partialTepMissing()){if(item.path.startsWith('tep.')){const [,key,col]=item.path.split('.');partialTepEditCell(key,col,['gns','total_area'].includes(col)?(key==='apartments'?'3000':'500'):col==='useful'&&key==='apartments'?'2000':'0')}else{const key=item.path.slice(7);partialTepEditInput(key,{value:key==='project_start'?'2027-01-01':'24',type:key==='project_start'?'date':'number'},key==='project_start'?'date':'number')}}}''')
            assert page.evaluate('partialTepMissing().length')==0
            assert partial_calls()==[]  # completion never starts money implicitly
            expect(page.locator('#partialTepNotice')).to_contain_text('по вашей команде')
            page.evaluate('calculate()')
            assert partial_calls()
            assert errors==[],errors
        finally:browser.close()
