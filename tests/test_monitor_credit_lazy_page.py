"""The native Monitor defers credit until requested and owns every response."""
import json

import pytest
from playwright.sync_api import expect

from test_monitor_cumulative_controls import KEY, browser_page
from test_monitor_gpr_sections import monitor_view


STRESS = dict(inflow_cut_pct='20', disclosure_delay_months='3', key_rate_pp='2')
CUT = '2026-11-08'


def answer(label='CURRENT CREDIT'):
    return dict(state='ok', status=dict(color='green'), html='<p>'+label+'</p>')


class Requests:
    def __init__(self, page):
        self.page = page
        self.full = []
        self.quick = []
        self._credit = []
        self._upload = []
        self.admitted = {}
        expect(page.locator('#refresh')).to_be_enabled()
        page.locator('#cut').fill(CUT)
        page.evaluate('''()=>{window.creditNativeStarts=[];window.creditNativeUploads=[];
          window.creditRoutesSeen={credit:0,upload:0};const original=window.fetch.bind(window);
          window.fetch=(path,options)=>{if(path==='/monitor/credit')creditNativeStarts.push(JSON.parse(options.body));
            if(path==='/monitor/credit/data')creditNativeUploads.push(JSON.parse(options.body));
            return original(path,options)};}''')
        # Both replacement synthetic credentials below are valid in this fake
        # service. Access-control enforcement is tested by the native API suite.
        page.route('**/monitor/**', lambda route: route.fulfill(json={}))
        page.route('**/monitor/view', self.admit)
        page.route('**/monitor/view/result', lambda route: self.full.append(route))
        page.route('**/monitor/gpr-view', lambda route: self.quick.append(route))
        page.route('**/monitor/credit', lambda route: self.capture(route, 'credit'))
        page.route('**/monitor/credit/data', lambda route: self.capture(route, 'upload'))

    def capture(self, route, kind):
        (self._credit if kind == 'credit' else self._upload).append(route)
        self.page.evaluate('kind=>{creditRoutesSeen[kind]++}', kind)

    @property
    def credit(self):
        # request events precede paused-route callbacks; await the fake HTTP
        # service's acknowledgement, rather than assuming callback ordering.
        self.page.wait_for_function('creditRoutesSeen.credit===creditNativeStarts.length')
        return self._credit

    @property
    def upload(self):
        self.page.wait_for_function('creditRoutesSeen.upload===creditNativeUploads.length')
        return self._upload

    def admit(self, route):
        body = route.request.post_data_json
        self.admitted[body['ticket']] = body
        route.fulfill(status=202, json=dict(pending=True, ticket=body['ticket']))

    def start(self):
        with self.page.expect_request('**/monitor/view/result'):
            self.page.locator('#refresh').click()
        expect(self.page.locator('#refresh')).to_be_disabled()

    def finish(self, index=-1):
        route = self.full[index]
        value = monitor_view()
        value['cut'] = self.admitted[route.request.post_data_json['ticket']]['cut']
        route.fulfill(json=dict(pending=False, snapshot=value))
        expect(self.page.locator('#refresh')).to_be_enabled()

    def money(self):
        self.page.locator('#moneyTab').click()

    def done(self, label='CURRENT CREDIT', index=-1):
        self.credit[index].fulfill(json=answer(label))
        expect(self.page.locator('#creditBody')).to_have_text(label)
        expect(self.page.locator('#creditRun')).to_be_enabled()


@pytest.mark.parametrize('width', [390, 1440])
def test_initial_gpr_and_quick_response_never_request_credit(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start()
        quick = monitor_view(); quick['cut'] = CUT
        calls.quick[-1].fulfill(json=quick)
        expect(page.locator('#ganttCard')).to_be_visible()
        assert calls.credit == []
        calls.finish()
        expect(page.locator('#ganttCard')).to_be_visible()
        assert calls.credit == [] and page.evaluate('creditNativeStarts.length') == 0
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_money_waits_for_full_then_deduplicates_tabs_and_explicit_run_is_fresh(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start()
        calls.money()
        expect(page.locator('#creditUpload')).to_be_enabled()
        expect(page.locator('#creditRun')).to_be_disabled()
        assert calls.credit == []
        with page.expect_request('**/monitor/credit'):
            calls.finish()
        assert len(calls.credit) == 1
        body = calls.credit[0].request.post_data_json
        assert body['stress'] == STRESS and body['key'] == KEY
        assert 'cut' not in body
        expect(page.locator('#creditRun')).to_be_disabled()
        page.locator('#monitorTab').click(); calls.money()
        assert len(calls.credit) == 1
        calls.done()
        page.locator('#monitorTab').click(); calls.money()
        assert len(calls.credit) == 1
        expect(page.locator('#creditCard')).to_contain_text('Выбранный срез ГПР к ней не применяется.')
        with page.expect_request('**/monitor/credit'):
            page.locator('#creditRun').click()
        assert len(calls.credit) == 2
        page.locator('#creditRun').dispatch_event('click')
        assert len(calls.credit) == 2
        calls.done('EXPLICIT CREDIT')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_money_after_full_starts_once_and_late_quick_does_not_restart_it(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        assert calls.credit == []
        with page.expect_request('**/monitor/credit'):
            calls.money()
        calls.done()
        quick = monitor_view(); quick['cut'] = CUT
        calls.quick[-1].fulfill(json=quick)
        page.locator('#monitorTab').click(); calls.money()
        assert len(calls.credit) == 1
        expect(page.locator('#creditBody')).to_have_text('CURRENT CREDIT')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('failure', ['http', 'network', 'json', 'shape', 'missing'])
def test_failed_credit_is_not_cached_and_can_retry(width, failure):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        with page.expect_request('**/monitor/credit'):
            calls.money()
        route = calls.credit[-1]
        if failure == 'http': route.fulfill(status=503, json=dict(detail='Synthetic busy'))
        elif failure == 'network': route.abort('connectionfailed')
        elif failure == 'json': route.fulfill(body='{broken', content_type='application/json')
        elif failure == 'shape': route.fulfill(json=dict(state='ok', status=dict(color='green')))
        else: route.fulfill(json=dict(state='missing', reason='Synthetic missing inputs'))
        expect(page.locator('#creditRun')).to_be_enabled()
        page.locator('#monitorTab').click()
        with page.expect_request('**/monitor/credit'):
            calls.money()
        assert len(calls.credit) == 2
        calls.done('RETRIED CREDIT')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_stress_change_ignores_old_response_and_does_not_post_on_typing(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        with page.expect_request('**/monitor/credit'):
            calls.money()
        old = calls.credit[-1]
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        page.locator('#creditCut').fill('35')
        page.locator('#creditDelay').fill('5')
        page.locator('#creditRate').fill('1.5')
        assert len(calls.credit) == 1
        old.fulfill(json=answer('OLD STRESS'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditBody')).not_to_contain_text('OLD STRESS')
        with page.expect_request('**/monitor/credit'):
            page.locator('#creditRun').click()
        assert calls.credit[-1].request.post_data_json['stress'] == dict(
            inflow_cut_pct='35', disclosure_delay_months='5', key_rate_pp='1.5')
        calls.done('NEW STRESS')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_refresh_drops_old_response_and_waits_for_new_full_generation(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        with page.expect_request('**/monitor/credit'):
            calls.money()
        old = calls.credit[-1]
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        calls.start()
        assert len(calls.credit) == 1
        old.fulfill(json=answer('OLD VIEW'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditBody')).not_to_contain_text('OLD VIEW')
        with page.expect_request('**/monitor/credit'):
            calls.finish()
        assert len(calls.credit) == 2
        calls.done('NEW VIEW')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('change', ['project', 'date', 'key', 'session', 'logout', 'source'])
@pytest.mark.parametrize('failure', [False, True])
def test_changed_context_cannot_apply_stale_success_error_or_finally(width, change, failure):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        with page.expect_request('**/monitor/credit'):
            calls.money()
        old = calls.credit[-1]
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        if change == 'project': page.locator('#project').fill('Another synthetic project')
        elif change == 'date': page.locator('#cut').fill('2026-11-09')
        elif change == 'logout': page.locator('#logoutBtn').click()
        elif change == 'source': page.evaluate('invalidatePhysicalForecast()')
        else:
            storage_key = 'plato_projects_key' if change == 'key' else 'developaid_web_session'
            page.evaluate('''key=>{localStorage.setItem(key,'synthetic-replacement');
              window.dispatchEvent(new StorageEvent('storage',{key}))}''', storage_key)
        if change != 'logout':
            calls.start()
            with page.expect_request('**/monitor/credit'): calls.finish()
        if failure: old.fulfill(status=503, json=dict(detail='STALE CREDIT ERROR'))
        else: old.fulfill(json=answer('STALE CREDIT HTML'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditBody')).not_to_contain_text('STALE CREDIT HTML')
        expect(page.locator('#creditMsg')).not_to_contain_text('STALE CREDIT ERROR')
        assert len(calls.credit) == (1 if change == 'logout' else 2)
        if change != 'logout':
            expect(page.locator('#creditRun')).to_be_disabled()
            body = calls.credit[-1].request.post_data_json
            actual = page.evaluate('({project:$("project").value.trim(),key:adminKey(),session:session()})')
            assert all(body[key] == value for key, value in actual.items())
            calls.done('CURRENT CONTEXT')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_old_finally_cannot_unlock_a_new_credit_request(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        with page.expect_request('**/monitor/credit'): calls.money()
        old = calls.credit[-1]
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        calls.start()
        with page.expect_request('**/monitor/credit'): calls.finish()
        old.fulfill(status=503, json=dict(detail='OLD ERROR'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditRun')).to_be_disabled()
        expect(page.locator('#creditMsg')).not_to_contain_text('OLD ERROR')
        calls.done('NEW REQUEST')
        assert not errors


def choose_upload(page):
    page.locator('#creditFile').set_input_files(dict(name='synthetic.json', mimeType='application/json',
        buffer=json.dumps(dict(datasets=[])).encode()))


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('order', ['before', 'after'])
def test_explicit_upload_is_available_without_full_view_and_deduplicates_automatic_load(width, order):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.money(); choose_upload(page)
        with page.expect_request('**/monitor/credit/data'):
            page.locator('#creditUpload').click()
        expect(page.locator('#creditUpload')).to_be_disabled()
        body = calls.upload[-1].request.post_data_json
        assert body['stress'] == STRESS and body['content_base64'] and body['key'] == KEY
        assert 'cut' not in body
        if order == 'after': calls.finish()
        calls.upload[-1].fulfill(json=answer('UPLOADED CREDIT'))
        expect(page.locator('#creditBody')).to_have_text('UPLOADED CREDIT')
        if order == 'before': calls.finish()
        assert calls.credit == []
        page.locator('#monitorTab').click(); calls.money()
        assert calls.credit == [] and len(calls.upload) == 1
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('change', ['project', 'date', 'key', 'session', 'logout'])
def test_upload_rechecks_context_after_file_read_before_post(width, change):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.money(); choose_upload(page)
        page.evaluate('''()=>{window.FileReader=class{
          readAsDataURL(){window.finishCreditRead=()=>{
            this.result='data:application/json;base64,e30=';this.onload();
          }}
        }}''')
        page.locator('#creditUpload').click()
        page.wait_for_function("typeof window.finishCreditRead==='function'")
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        def unexpected(route):
            calls.capture(route, 'upload')
            route.fulfill(json=answer('UNEXPECTED UPLOAD'))
        page.route('**/monitor/credit/data', unexpected)
        if change == 'project': page.locator('#project').fill('Another synthetic project')
        elif change == 'date': page.locator('#cut').fill('2026-11-09')
        elif change == 'logout': page.locator('#logoutBtn').click()
        else:
            key = 'plato_projects_key' if change == 'key' else 'developaid_web_session'
            page.evaluate("key=>{localStorage.setItem(key,'replacement');window.dispatchEvent(new StorageEvent('storage',{key}))}", key)
        page.evaluate("finishCreditRead('e30=')")
        page.evaluate('async()=>{await window.previousCreditRequest}')
        assert calls.upload == []
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_upload_response_from_previous_refresh_cannot_replace_new_calculation(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.money(); choose_upload(page)
        with page.expect_request('**/monitor/credit/data'):
            page.locator('#creditUpload').click()
        expect(page.locator('#creditUpload')).to_be_disabled()
        old = calls.upload[-1]
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        calls.start()
        with page.expect_request('**/monitor/credit'): calls.finish()
        old.fulfill(json=answer('OLD UPLOAD'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditBody')).not_to_contain_text('OLD UPLOAD')
        expect(page.locator('#creditRun')).to_be_disabled()
        calls.done('NEW CALCULATION')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_upload_can_replace_pending_calculation_and_old_finally_cannot_unlock_it(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.finish()
        with page.expect_request('**/monitor/credit'): calls.money()
        old = calls.credit[-1]
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        expect(page.locator('#creditUpload')).to_be_enabled()
        choose_upload(page)
        with page.expect_request('**/monitor/credit/data'):
            page.locator('#creditUpload').click()
        expect(page.locator('#creditUpload')).to_be_disabled()
        old.fulfill(status=503, json=dict(detail='OLD CALCULATION ERROR'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditUpload')).to_be_disabled()
        expect(page.locator('#creditMsg')).not_to_contain_text('OLD CALCULATION ERROR')
        calls.upload[-1].fulfill(json=answer('CORRECTED CREDIT'))
        expect(page.locator('#creditBody')).to_have_text('CORRECTED CREDIT')
        page.locator('#monitorTab').click(); calls.money()
        assert len(calls.credit) == 1 and len(calls.upload) == 1
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_stress_edit_during_upload_waits_for_the_write_without_applying_old_stress(width):
    with browser_page(width) as (page, _, errors):
        calls = Requests(page)
        calls.start(); calls.money(); choose_upload(page)
        with page.expect_request('**/monitor/credit/data'):
            page.locator('#creditUpload').click()
        expect(page.locator('#creditUpload')).to_be_disabled()
        page.evaluate('()=>{window.previousCreditRequest=creditPending.promise}')
        page.locator('#creditCut').fill('35')
        calls.finish()
        assert calls.credit == []
        expect(page.locator('#creditUpload')).to_be_disabled()
        calls.upload[-1].fulfill(json=answer('OLD UPLOAD STRESS'))
        page.evaluate('async()=>{await window.previousCreditRequest}')
        expect(page.locator('#creditBody')).not_to_contain_text('OLD UPLOAD STRESS')
        expect(page.locator('#creditUpload')).to_be_enabled()
        with page.expect_request('**/monitor/credit'):
            page.locator('#creditRun').click()
        assert calls.credit[-1].request.post_data_json['stress']['inflow_cut_pct'] == '35'
        calls.done('NEW PARAMETERS')
        assert not errors
