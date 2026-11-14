"""A slow HTTP200 body cannot become a successful empty Monitor snapshot."""
import pytest
from playwright.sync_api import expect

from test_monitor_cumulative_controls import browser_page
from test_monitor_gpr_sections import monitor_view


@pytest.mark.parametrize('kind', ['abort','invalid_json'])
def test_success_response_body_errors_are_never_swallowed(kind):
    with browser_page() as (page, responses, errors):
        result=page.evaluate("""async kind=>{
          const original=window.fetch;
          window.fetch=async()=>({ok:true,status:200,json:async()=>{
            if(kind==='abort')throw new DOMException('Synthetic body abort','AbortError');
            return JSON.parse('{invalid');
          }});
          try{return await post('/monitor/body-test',{}).then(v=>({resolved:true}),e=>({name:e.name,message:e.message}))}
          finally{window.fetch=original}
        }""",kind)
        assert not result.get('resolved')
        if kind=='abort': assert result['name']=='AbortError'
        else: assert 'прочитан не полностью' in result['message']
        assert not errors


@pytest.mark.parametrize('width',[390,1440])
def test_gpr_renders_while_full_financial_view_is_still_pending(width):
    with browser_page(width) as (page,responses,errors):
        held=[]
        page.route('**/monitor/view',lambda route:route.fulfill(status=202,json={'pending':True,'ticket':'a'*32}))
        page.route('**/monitor/view/result',lambda route:held.append(route))
        view=monitor_view()
        page.route('**/monitor/gpr-view',lambda route:route.fulfill(json=view))
        with page.expect_request('**/monitor/view/result'):
            page.locator('#refresh').click()
        expect(page.locator('#ganttCard')).to_be_visible()
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        expect(page.locator('#gantt')).to_contain_text('40%')
        assert page.evaluate('currentView.schedule.management.length')>0
        expect(page.locator('#refresh')).to_be_disabled()  # Financial body still pending.
        page.route('**/monitor/gpr-view',lambda route:route.fulfill(json={}))
        assert held
        for route in held: route.fulfill(status=503,json={'detail':'Synthetic finance failure'})
        expect(page.locator('#refresh')).to_be_enabled()
        expect(page.locator('#ganttCard')).to_be_visible()
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


def test_large_result_body_has_its_own_read_timeout_and_renders_the_full_snapshot():
    with browser_page() as (page,responses,errors):
        page.route('**/monitor/gpr-view',lambda route:route.fulfill(json={}))
        page.route('**/monitor/view',lambda route:route.fulfill(status=202,json={'pending':True,'ticket':'b'*32}))
        page.route('**/monitor/view/result',lambda route:route.fulfill(json={'pending':False,'snapshot':monitor_view()}))
        page.evaluate("""()=>{
          const timer=window.setTimeout.bind(window),fetch=window.fetch.bind(window);
          window.setTimeout=(fn,delay,...args)=>timer(fn,delay===15000?200:delay===90000?1500:delay,...args);
          window.fetch=async(path,options={})=>{
            const response=await fetch(path,options);
            if(path!=='/monitor/view/result')return response;
            return {ok:response.ok,status:response.status,json:()=>new Promise((resolve,reject)=>{
              options.signal?.addEventListener('abort',()=>reject(new DOMException('Synthetic slow body','AbortError')),{once:true});
              timer(()=>response.json().then(resolve,reject),350);
            })};
          };
        }""")
        page.locator('#refresh').click()
        expect(page.locator('#refresh')).to_be_enabled()
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        assert page.evaluate('Boolean(currentView?.schedule)')
        assert not errors


def test_late_fast_view_does_not_overwrite_an_already_rendered_full_view():
    with browser_page() as (page,responses,errors):
        held=[]
        page.route('**/monitor/gpr-view',lambda route:held.append(route))
        page.route('**/monitor/view',lambda route:route.fulfill(json={'snapshot':monitor_view()}))
        with page.expect_request('**/monitor/gpr-view'):
            page.locator('#refresh').click()
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        expect(page.locator('#refresh')).to_be_enabled()
        stale=monitor_view();stale['schedule']['management'][0]['name']='LATE LIGHT RESPONSE'
        for route in held: route.fulfill(json=stale)
        expect(page.locator('#gantt')).not_to_contain_text('LATE LIGHT RESPONSE')
        assert page.evaluate('currentView.schedule.management[0].name')=='Стройка'
        assert not errors


@pytest.mark.parametrize('change',['project','date','auth'])
def test_fast_gpr_response_cannot_restore_a_previous_source_context(change):
    with browser_page() as (page,responses,errors):
        held=[];full=[]
        page.route('**/monitor/gpr-view',lambda route:held.append(route))
        page.route('**/monitor/view',lambda route:full.append(route))
        with page.expect_request('**/monitor/gpr-view'):
            page.locator('#refresh').click()
        if change=='project': page.locator('#project').fill('Another project')
        elif change=='date': page.locator('#cut').fill('2026-11-10')
        else: page.locator('#logoutBtn').click()
        for route in held: route.fulfill(json=monitor_view())
        for route in full: route.fulfill(json={'snapshot':monitor_view()})
        expect(page.locator('#gantt .lvl-task')).to_have_count(0)
        assert not errors
