"""Real Monitor JS: source-bound mapping and one physical RNV across surfaces."""
import copy

import pytest

from test_monitor_cumulative_controls import browser_page, KEY, MARKER
from test_schedule_physical import config, CUT


def state(**changes):
    result=dict(pm_sha256='a'*64,snapshot_id=CUT+'-'+'b'*64,revision=0,
                configuration={'tasks':[],'components':[],'note':''},recorded_at=None,
                source_changed=False,can_edit=True,
                tasks=[dict(task_id='1',name=MARKER+' Корпус 1')],
                items=[dict(item_id='0:0',name=MARKER,scope='Корпус 1',unit='м²',plan_quantity=100,
                            completed_quantity=50,period_year=2026,contract='Д-1',contractor='Учебный')],
                item_count=1,offset=0,model={'state':'unknown','tasks':[]})
    result.update(changes);return result


@pytest.mark.parametrize('width',[390,1440])
def test_mapping_save_reload_revoke_and_escape_with_actual_page(width):
    from playwright.sync_api import expect
    current=state();writes=[]
    def respond(route):
        nonlocal current
        body=route.request.post_data_json
        assert body['key']==KEY and 'key=' not in route.request.url
        if route.request.url.endswith('/save'):
            writes.append(body)
            current=state(configuration=body['configuration'],revision=current['revision']+1,
                          recorded_at='2026-11-06T12:00:00+00:00')
        route.fulfill(json=current)
    with browser_page(width, init='window.DEVELOPAID_PM_ENABLED=true') as (page,responses,errors):
        page.route('**/monitor/schedule-physical/*',respond)
        page.evaluate('void loadPhysicalSchedule()')
        expect(page.locator('#physicalSave')).to_be_enabled()
        page.locator('#physicalScheduleCard summary').click()
        page.locator('#physicalScope').check()
        page.locator('#physicalApplyTask').click()
        page.locator('#physicalItems').select_option(['0:0'])
        page.locator('#physicalComponent').fill('Корпус 1 '+MARKER)
        page.locator('#physicalAddComponent').click()
        page.locator('#physicalNote').fill('Проверила Анна: полный объём работ корпуса 1.')
        page.locator('#physicalSave').click()
        expect(page.locator('#physicalScheduleState')).to_contain_text('Последняя привязка')
        assert writes[0]['pm_sha256']=='a'*64 and writes[0]['snapshot_id']==CUT+'-'+'b'*64
        assert writes[0]['configuration']['components'][0]['item_ids']==['0:0']
        page.reload()
        expect(page.locator('#physicalBindings')).to_contain_text('Корпус 1')
        expect(page.locator('#physicalNote')).to_have_value('Проверила Анна: полный объём работ корпуса 1.')
        page.locator('#physicalScheduleCard summary').click()
        page.locator('#physicalClear').click()
        page.locator('#physicalNote').fill('Привязка снята до повторной проверки.')
        page.locator('#physicalSave').click()
        expect(page.locator('#physicalSave')).to_be_enabled()
        assert writes[-1]['configuration']['components']==[] and writes[-1]['revision']==1
        assert page.locator('#physicalScheduleCard img').count()==0
        assert not page.evaluate('window.untrustedRan||false')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
        page.screenshot(path=f'/tmp/gpr-physical-{width}.png',full_page=True)


def test_stale_read_or_logout_cannot_restore_physical_sources():
    from playwright.sync_api import expect
    with browser_page(init='window.DEVELOPAID_PM_ENABLED=true') as (page,responses,errors):
        held=[]
        page.route('**/monitor/schedule-physical/view',lambda route:held.append(route))
        with page.expect_request('**/monitor/schedule-physical/view'):
            page.evaluate('void loadPhysicalSchedule()')
        page.locator('#project').fill('Другой проект')
        held.pop().fulfill(json=state())
        expect(page.locator('#physicalScheduleCard')).to_be_hidden()
        assert page.locator('#physicalItems option').count()==0
        with page.expect_request('**/monitor/schedule-physical/view'):
            page.evaluate('void loadPhysicalSchedule()')
        page.evaluate("localStorage.removeItem('plato_projects_key');syncAuthUi()")
        held.pop().fulfill(json=state())
        expect(page.locator('#physicalScheduleCard')).to_be_hidden()
        assert not errors


def test_history_and_conflict_require_fresh_source_revision():
    from playwright.sync_api import expect
    with browser_page() as (page,responses,errors):
        page.evaluate('(state)=>renderPhysicalSchedule(state)',state(can_edit=False))
        expect(page.locator('#physicalSave')).to_be_disabled()
        page.route('**/monitor/schedule-physical/save',lambda route:route.fulfill(status=409,json={'detail':'Источник изменился.'}))
        page.evaluate('(state)=>renderPhysicalSchedule(state)',state())
        page.locator('#physicalScheduleCard summary').click()
        page.locator('#physicalNote').fill('Проверено.')
        page.locator('#physicalSave').click()
        expect(page.locator('#physicalMsg')).to_contain_text('Перечитать')
        expect(page.locator('#physicalSave')).to_be_disabled()
        assert not errors


def test_physical_complete_forecast_cannot_render_old_cost_scenario():
    from playwright.sync_api import expect
    with browser_page() as (page,responses,errors):
        page.evaluate("""()=>{currentView={schedule:{dependency_timeline:{rnv:{state:'complete',approved:'2027-02-01',forecast:'2027-02-13',delay_days:12,driving_chain:[{name:'Физическая цепочка'}]}}}};renderForecast({schedule:{current_pace_rnv:'2099-01-01'},funding:{}});}""")
        expect(page.locator('#forecastHeadline')).to_contain_text('13.02.2027')
        assert '2099' not in page.locator('#forecastCard').inner_text()
        page.evaluate("renderForecastFallback('нет денежного сценария')")
        expect(page.locator('#forecastHeadline')).to_contain_text('13.02.2027')
        page.evaluate("currentView.schedule.dependency_timeline.rnv.state='partial';renderForecastFallback('ошибка сценария')")
        expect(page.locator('#forecastCard')).to_be_hidden()
        assert not errors


@pytest.mark.parametrize('completed_conflict', [False, True])
def test_report_pdf_contains_the_same_physical_quantities(tmp_path, completed_conflict):
    import fitz
    import developaid_management_report as report
    import developaid_schedule_physical as physical
    import developaid_schedule_timeline as timeline
    from test_schedule_physical import snapshot
    from test_schedule_dependency_timeline import network,day
    from browser import chromium_or_skip
    from playwright.sync_api import sync_playwright
    pm=network();cfg=config()
    if completed_conflict:
        cfg['tasks'][1].update(mode='completed',actual_finish='2026-10-31')
    model=physical.evaluate(pm,snapshot(),cfg,CUT)
    block=timeline.model(pm,{tid:day(value) for tid,value in model['seeds'].items()},evidence=True,
                         actual_finishes={tid:day(value) for tid,value in model['actual_finishes'].items()})
    block['physical']=model
    payload={'project':'Учебный проект','kind':'week','start':'2026-11-01','end':CUT,
             'gantt':{'state':'missing','dependency_timeline':block}}
    path=tmp_path/'physical.pdf'
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()),args=['--no-sandbox'])
        page=browser.new_page();page.route('**/*',lambda route:route.abort())
        page.set_content(report.render_html(payload),wait_until='load')
        page.pdf(path=str(path),format='A4');browser.close()
    with fitz.open(path) as pdf:text=' '.join(page.get_text() for page in pdf)
    assert 'Физическое выполнение' in text and '50 / 100' in text
    if completed_conflict:
        assert block['rnv']['forecast'] is None
        assert 'противоречит' in text
    else:
        assert '13.02.2027' in text


def test_saved_revocation_cannot_leave_an_old_forecast_when_refresh_fails():
    from playwright.sync_api import expect
    with browser_page() as (page,responses,errors):
        page.evaluate("""()=>{currentView={schedule:{dependency_timeline:{rnv:{state:'complete',approved:'2027-02-01',forecast:'2027-02-13'}}},dashboard:{schedule:{forecast_known:true,forecast_finish:'2027-02-13'},summary:['Срок. Прежний срок 13.02.2027.']}};renderForecast({});}""")
        expect(page.locator('#forecastHeadline')).to_contain_text('13.02.2027')
        page.route('**/monitor/schedule-physical/save',lambda route:route.fulfill(json=state(revision=1)))
        page.evaluate('(state)=>renderPhysicalSchedule(state)',state())
        page.locator('#physicalScheduleCard summary').click()
        page.locator('#physicalNote').fill('Снять привязки.')
        page.locator('#physicalSave').click()
        expect(page.locator('#forecastCard')).to_be_hidden()
        expect(page.locator('#summaryBody')).not_to_contain_text('13.02.2027')
        assert page.evaluate('currentView.dashboard.schedule.forecast_known') is False
        assert page.evaluate('currentView.schedule.dependency_timeline.rnv.state')=='unknown'
        assert not errors


def test_changed_sources_immediately_invalidate_the_previous_qualified_forecast():
    from playwright.sync_api import expect
    with browser_page() as (page,responses,errors):
        page.evaluate("""()=>{currentView={schedule:{physical_progress:{pm_sha256:'a'.repeat(64),snapshot_id:'old'},dependency_timeline:{rnv:{state:'complete',forecast:'2027-02-13'}}},dashboard:{schedule:{forecast_known:true,forecast_finish:'2027-02-13'},summary:[]}};renderForecast({});}""")
        page.evaluate('(state)=>renderPhysicalSchedule(state)',state(source_changed=True))
        expect(page.locator('#forecastCard')).to_be_hidden()
        expect(page.locator('#viewMsg')).to_contain_text('Исходные данные изменились')
        assert page.evaluate('currentView.dashboard.schedule.forecast_finish') is None
        assert not errors
