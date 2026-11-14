"""Known auth denial is authoritative even when its response body is unreadable."""
import pytest
from playwright.sync_api import expect
from browser import expand_gantt

from test_monitor_cumulative_controls import browser_page
from test_monitor_gpr_sections import monitor_view


@pytest.mark.parametrize('status', [200, 401, 403])
@pytest.mark.parametrize('body', ['invalid_json', 'abort', 'null_json'])
def test_real_page_post_scrubs_denied_bodies_and_never_returns_failed_success_body(status, body):
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>{currentView=v;renderDash(v);renderGantt(v);currentView.schedule.readiness={fixture:"private"};currentView.schedule.corpus_gpr={fixture:"private"};contractRegister={fixture:"private"};verifiedKey=""}', monitor_view())
        expand_gantt(page)
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        result = page.evaluate('''async ({status,body})=>{
            const original=window.fetch;
            let received='not-received',failure=null;
            window.fetch=async()=>({ok:status===200,status,json:async()=>{
                if(body==='null_json')return null;
                if(body==='abort')throw new DOMException('Synthetic interrupted response','AbortError');
                throw new SyntaxError('Synthetic unreadable JSON');
            }});
            try{received=await post('/monitor/denied-body-test',{});}catch(error){failure=error.name;}
            finally{window.fetch=original;}
            return {received,failure,rejected:keyRejected,verified:verifiedKey,
                retained:currentView!==null,readinessRetained:!!currentView?.schedule?.readiness,
                corpusRetained:!!currentView?.schedule?.corpus_gpr,contractsRetained:contractRegister!==null,
                privateVisible:!$('privateArea').classList.contains('hidden')};
        }''', {'status': status, 'body': body})
        assert result['failure'] and result['received'] == 'not-received'
        assert result['verified'] == ''
        if body == 'abort':
            assert result['failure'] == 'AbortError'
        if status in (401, 403):
            assert result['rejected'] is True
            assert result['readinessRetained'] is False and result['corpusRetained'] is False
            assert result['contractsRetained'] is False
            assert result['privateVisible'] is False
            expect(page.locator('#privateArea')).to_be_hidden()
            expect(page.locator('#ganttCard')).not_to_be_visible()
        else:
            assert result['rejected'] is False and result['retained'] is True
        assert errors == []


@pytest.mark.parametrize('status', [401, 403])
def test_a_late_denied_body_abort_cannot_revoke_a_new_key_context(status):
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>{currentView=v;renderDash(v);renderGantt(v)}', monitor_view())
        result = page.evaluate('''async status=>{
            const original=window.fetch;
            window.fetch=async()=>({ok:false,status,json:async()=>{
                const fresh=JSON.parse(JSON.stringify(currentView));
                clearCumulativeData();localStorage.setItem(ADMIN_KEY,'synthetic-replacement-key');
                authEpoch++;keyRejected=false;verifiedKey='';syncAuthUi();
                fresh.fixtureContext='replacement-key';currentView=fresh;renderDash(fresh);renderGantt(fresh);
                throw new DOMException('Synthetic old response interrupted','AbortError');
            }});
            let failure=null;
            try{await post('/monitor/late-denied-body-test',{});}catch(error){failure=error.name;}
            finally{window.fetch=original;}
            return {failure,rejected:keyRejected,retained:currentView?.fixtureContext==='replacement-key',
                privateVisible:!$('privateArea').classList.contains('hidden')};
        }''', status)
        assert result == {'failure': 'AbortError', 'rejected': False, 'retained': True, 'privateVisible': True}
        expand_gantt(page)
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        assert errors == []
