"""Monitor: реальный отказ администратора, замена ключа и сохранение файла."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser import chromium_or_skip, serve

KEY='monitor-browser-admin-key'
ROTATED='monitor-browser-rotated-key'


@pytest.fixture
def monitor_server(monkeypatch, tmp_path):
    import main_legacy as core
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setattr(core.developaid_monitor, 'build',
                        lambda *a, **kw: {'cut': '2026-11-05', 'schedule': {'management': []}})
    monkeypatch.setattr(core.developaid_monitor, 'trend', lambda *a, **kw: {})
    stored=[]
    def store(*args):
        stored.append(args)
        return {'saved': True}
    monkeypatch.setattr(core.developaid_monitor, 'store_estimate', store)
    with serve(core.app, 18849) as base:
        yield base, stored


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            yield browser.new_page(viewport={'width':1280,'height':900})
        finally:
            browser.close()


def enter_key(page, key):
    page.once('dialog', lambda dialog: dialog.accept(key))
    page.locator('#keyBtn').click()


def saved(page, key=KEY, storage_key='plato_projects_key', project=True):
    page.add_init_script(f"if(!sessionStorage.getItem('seeded')){{localStorage.setItem({json.dumps(storage_key)},{json.dumps(key)});"
                         + ("localStorage.setItem('monitor_project','Синтетический проект');" if project else '')
                         + "sessionStorage.setItem('seeded','1');}")


@pytest.mark.parametrize('storage_key',['plato_projects_key','key','developaid_key'])
def test_a_saved_wrong_key_can_be_replaced(monitor_server, page, storage_key):
    from playwright.sync_api import expect
    base, stored=monitor_server
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    saved(page,'wrong-key',storage_key)
    with page.expect_response('**/monitor/view') as denied:
        page.goto(base+'/monitor')
    assert denied.value.status==403
    expect(page.locator('#keyBtn')).to_be_visible()
    expect(page.locator('#privateArea')).to_be_hidden()
    expect(page.locator('#loginMsg')).to_contain_text('ключу администратора')
    expect(page.locator('#loginMsg')).to_contain_text('Сохранённый ключ не принят сервером')
    expect(page.locator('#loginState')).to_have_text('Доступ не подтверждён')
    # Синхронизация UI не должна заново открыть данные по наличию той же строки.
    page.evaluate('syncAuthUi()')
    expect(page.locator('#privateArea')).to_be_hidden()
    with page.expect_response('**/monitor/view') as accepted:
        enter_key(page,'  '+KEY+'  ')
    assert accepted.value.status==200
    expect(page.locator('#privateArea')).to_be_visible()
    expect(page.locator('#keyBtn')).to_have_text('Сменить ключ')
    expect(page.locator('#loginState')).to_have_text('Доступ подтверждён')
    assert page.evaluate("localStorage.getItem('plato_projects_key')")==KEY
    with page.expect_response('**/monitor/view') as reopened:
        page.reload()
    assert reopened.value.status==200
    assert stored==[] and errors==[]


@pytest.mark.parametrize('width',[390,1280])
def test_rejected_rss_upload_keeps_file_project_and_date(monitor_server,page,monkeypatch,width):
    from playwright.sync_api import expect
    base,stored=monitor_server
    page.set_viewport_size({'width':width,'height':900})
    saved(page)
    with page.expect_response('**/monitor/view'):
        page.goto(base+'/monitor')
    page.locator('#dataTab').click()
    expect(page.locator('#rss')).to_be_visible()
    page.locator('#rss').set_input_files({'name':'synthetic.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':b'synthetic'})
    page.locator('#rssDate').fill('2026-11-05')
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', ROTATED)
    with page.expect_response('**/monitor/estimate') as denied:
        page.locator('#rssBtn').click()
    assert denied.value.status==403
    assert denied.value.request.post_data_json['key']==KEY
    expect(page.locator('#keyBtn')).to_be_visible()
    expect(page.locator('#privateArea')).to_be_hidden()
    assert stored==[]
    with page.expect_response('**/monitor/view') as accepted:
        enter_key(page, ROTATED)
    assert accepted.value.status==200
    assert page.locator('#rss').evaluate('(e)=>e.files[0].name')=='synthetic.xlsx'
    expect(page.locator('#project')).to_have_value('Синтетический проект')
    expect(page.locator('#rssDate')).to_have_value('2026-11-05')
    assert stored==[]  # Исправление ключа само не повторяет запись.
    page.locator('#dataTab').click()
    expect(page.locator('#rssBtn')).to_be_visible()
    with page.expect_response('**/monitor/estimate') as uploaded:
        page.locator('#rssBtn').click()
    assert uploaded.value.status==200
    assert uploaded.value.request.post_data_json['key']==ROTATED
    assert len(stored)==1
    assert stored[0][0:3]==('Синтетический проект', b'synthetic', '2026-11-05')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_presence_of_a_key_is_not_labelled_successful_login(monitor_server,page):
    from playwright.sync_api import expect
    base,_=monitor_server
    saved(page,project=False)
    page.goto(base+'/monitor')
    expect(page.locator('#loginState')).to_have_text('Ключ сохранён; доступ ещё не проверен')
    expect(page.locator('#keyBtn')).to_be_visible()


@pytest.mark.parametrize('action,url',[('renderPeople()','**/monitor/daily/summary?*'),
                                     ("showCrew('2026-11-05')",'**/monitor/crew?*')])
def test_a_rejected_header_get_also_restores_key_entry(monitor_server,page,monkeypatch,action,url):
    from playwright.sync_api import expect
    base,_=monitor_server
    saved(page)
    with page.expect_response('**/monitor/view'):
        page.goto(base+'/monitor')
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', ROTATED)
    # Initial refresh starts the same GET in the background. Its previously
    # admitted 200 can finish after rotation; observe the newly issued request
    # rather than mistaking that older response for the denial under test.
    page.evaluate("""prefix=>{const original=window.fetch;window.fetch=(url,options={})=>{
      if(String(url).startsWith(prefix))options={...options,headers:{...options.headers,'X-Plato-Key-Retry-Probe':'current'}};
      return original(url,options);
    }}""",url.removeprefix('**').split('?')[0])
    with page.expect_response(lambda response:
            response.request.headers.get('x-plato-key-retry-probe')=='current') as denied:
        page.evaluate(action)
    assert denied.value.status==403
    expect(page.locator('#keyBtn')).to_be_visible()
    expect(page.locator('#privateArea')).to_be_hidden()


@pytest.mark.parametrize('next_key',[KEY,ROTATED])
def test_an_old_denial_does_not_reject_the_new_key(monitor_server,page,monkeypatch,next_key):
    from playwright.sync_api import expect
    base,_=monitor_server
    saved(page)
    with page.expect_response('**/monitor/view'):
        page.goto(base+'/monitor')
    delayed=[]
    page.route('**/monitor/delayed-test', lambda route:delayed.append(route))
    page.evaluate("()=>{window.oldResult=post('/monitor/delayed-test',{}).catch(()=>null)}")
    page.wait_for_timeout(50)
    assert len(delayed)==1
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',next_key)
    with page.expect_response('**/monitor/view') as accepted:
        enter_key(page,next_key)
    assert accepted.value.status==200
    delayed[0].fulfill(status=403,content_type='application/json',body=json.dumps({'detail':'old denial'}))
    page.evaluate('window.oldResult')
    expect(page.locator('#privateArea')).to_be_visible()
    expect(page.locator('#loginState')).to_have_text('Доступ подтверждён')


def test_a_file_validation_error_does_not_reject_the_key(monitor_server,page,monkeypatch):
    import main_legacy as core
    from playwright.sync_api import expect
    base,_=monitor_server
    saved(page)
    with page.expect_response('**/monitor/view'):
        page.goto(base+'/monitor')
    def invalid(*args):
        raise ValueError('В файле нет нужного листа')
    monkeypatch.setattr(core.developaid_monitor,'store_estimate',invalid)
    with page.expect_response('**/monitor/estimate') as failed:
        page.evaluate("post('/monitor/estimate',{project:'Синтетический проект',taken_at:'2026-11-05',content_base64:'eA=='}).catch(e=>e.message)")
    assert failed.value.status==400
    expect(page.locator('#privateArea')).to_be_visible()
    expect(page.locator('#loginState')).to_have_text('Доступ подтверждён')


@pytest.mark.parametrize('width', [390, 1440])
def test_contract_data_is_cleared_when_current_key_is_rejected(monitor_server, page, monkeypatch, width):
    """The new lawyer tab must not retain a previous authorized result on denial."""
    from playwright.sync_api import expect
    base, _ = monitor_server
    page.set_viewport_size({'width': width, 'height': 900})
    saved(page)
    page.route('**/monitor/contracts/build', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({'register': {
            'rows': [{'id': 'a' * 32, 'contractor': 'Синтетический подрядчик',
                      'contract': 'Тестовый договор', 'amount': 100, 'completed': 25,
                      'completion_ratio': .25, 'remaining': 75}],
        }})))
    with page.expect_response('**/monitor/view'):
        page.goto(base + '/monitor')
    page.locator('#contractsTab').click()
    expect(page.locator('#contractsRows')).to_contain_text('Синтетический подрядчик')
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', ROTATED)
    page.evaluate("post('/monitor/cumulative/list', {project:'Синтетический проект'}).catch(()=>null)")
    expect(page.locator('#privateArea')).to_be_hidden()
    expect(page.locator('#contractsRows')).to_be_empty()
    expect(page.locator('#keyBtn')).to_be_visible()
    page.unroute('**/monitor/contracts/build')
    enter_key(page, ROTATED)
    expect(page.locator('#privateArea')).to_be_visible()
    expect(page.locator('#loginState')).to_have_text('Доступ подтверждён')
    expect(page.locator('#contractsRows')).not_to_contain_text('Синтетический подрядчик')


def test_short_job_requests_keep_timeout_and_admission_status(monitor_server, page):
    """Updating the auth helper must retain the background job HTTP contract."""
    base, _ = monitor_server
    saved(page)
    with page.expect_response('**/monitor/view'):
        page.goto(base + '/monitor')
    page.route('**/monitor/test-admission', lambda route: route.fulfill(
        status=429, content_type='application/json', body=json.dumps({'detail': 'Занято'})))
    result = page.evaluate("post('/monitor/test-admission',{}, {timeout:1000}).catch(e=>({status:e.status,message:e.message}))")
    assert result == {'status': 429, 'message': 'Занято'}
    delayed = []
    page.route('**/monitor/test-short-timeout', lambda route: delayed.append(route))
    result = page.evaluate("post('/monitor/test-short-timeout',{}, {timeout:50}).catch(e=>e.name)")
    assert result == 'AbortError'
    assert delayed
