"""Native CI/browser coverage for notice lifecycle; synthetic local backend only."""
import copy,json
from urllib.parse import urlsplit
import pytest
from fastapi.testclient import TestClient
from browser import chromium_or_skip,wait_for_result
from test_document_qualification import core,document

ORIGIN='https://developaid.ru'
KEY='synthetic-qualification-admin'


@pytest.fixture
def notice_page(monkeypatch,document,tmp_path):
    import main_registry
    from playwright.sync_api import sync_playwright
    monkeypatch.setenv('DEVELOPAID_PAYWALL','0');monkeypatch.setenv('DEVELOPAID_ADMIN_IDS','777')
    monkeypatch.setattr(core,'_PROJECTS_DIR',tmp_path/'projects');monkeypatch.setattr(core,'_MO_CALC_API_URL','')
    monkeypatch.setattr(core,'fetch_current_cbr_key_rate',lambda:{'rate':14.,'date':'2026-11-15','live':False,'source':'Synthetic'})
    def forbidden(*a,**kw):pytest.fail('Notice lifecycle must not call a source/provider/Telegram')
    monkeypatch.setattr(core,'_openai_responses_request',forbidden);monkeypatch.setattr(core,'_telegram_api',forbidden)
    client=TestClient(main_registry.app);transport={'mode':'normal','held':[]}
    with sync_playwright()as pw:
        with pw.chromium.launch(executable_path=str(chromium_or_skip()),headless=True,args=['--no-sandbox'])as browser:
            def open_page(width):
                page=browser.new_page(viewport={'width':width,'height':900})
                def route(r):
                    req=r.request;u=urlsplit(req.url)
                    if u.scheme!='https'or u.netloc!='developaid.ru':r.abort();return
                    assert not u.path.startswith(('/agent/document','/telegram/result'))
                    payload=req.post_data_json if req.post_data else None
                    if u.path in {'/calculate','/calculate-phased'}:
                        if transport['mode']=='hold':transport['held'].append((r,u.path,payload));return
                        if transport['mode']=='refuse':r.fulfill(status=401,json={'detail':'Synthetic expired access'});return
                    answer=client.request(req.method,u.path+('?' +u.query if u.query else''),json=payload)
                    r.fulfill(status=answer.status_code,body=answer.content,headers={'content-type':answer.headers.get('content-type','application/json')})
                page.route('**/*',route)
                page.add_init_script("localStorage.setItem('plato_projects_key',"+json.dumps(KEY)+")")
                page.goto(ORIGIN,wait_until='networkidle');wait_for_result(page)
                return page
            yield open_page,client,transport
    client.close()


def show_old_generic(page):
    page.evaluate("async()=>{inputs._intake_qualification={key_scope:[]};await calculate()}")
    wait_for_result(page)
    assert page.evaluate("()=>lastResult.summary.intake_qualification.status")=='review_required'


def test_native_project_replacement_clears_old_notice_before_response_and_current_conditional_reappears(notice_page,document):
    from playwright.sync_api import expect
    open_page,client,transport=notice_page;page=open_page(390)
    clean=page.evaluate('()=>projectStorePayload().payload')
    saved=client.post('/projects/save',json={'key':KEY,'name':'Synthetic clean project','payload':clean})
    assert saved.status_code==200,saved.text
    show_old_generic(page);expect(page.locator('#documentQualificationNotice')).to_be_visible()
    transport['mode']='hold'
    page.evaluate('id=>loadProject(id)',saved.json()['id'])
    expect(page.locator('#documentQualificationNotice')).to_have_count(0)
    assert page.evaluate('()=>Object.hasOwn(inputs,"_intake_qualification")')is False
    page.wait_for_function('()=>calcRun>calcSettled')
    assert transport['held']
    transport['mode']='normal'
    for route,path,payload in transport['held']:
        assert '_intake_qualification'not in payload['inputs']
        answer=client.post(path,json=payload)
        route.fulfill(status=answer.status_code,body=answer.content,headers={'content-type':'application/json'})
    transport['held'].clear();wait_for_result(page)
    expect(page.locator('#documentQualificationNotice')).to_have_count(0)
    item=document();model={'inputs':copy.deepcopy(item['inputs']),'tep':copy.deepcopy(item['tep'])}
    page.evaluate('async model=>{applyProjectSnapshot(model);await calculate()}',model);wait_for_result(page)
    expect(page.locator('#documentQualificationNotice')).to_contain_text('275 м²')
    expect(page.locator('#documentQualificationNotice')).to_contain_text('не включена')
    assert page.evaluate('()=>inputs._intake_qualification')==item['record']


def test_native_calc_refusal_clears_orphan_notice_but_success_recreates_invalid_record_warning(notice_page):
    from playwright.sync_api import expect
    open_page,_client,transport=notice_page;page=open_page(1440)
    show_old_generic(page);expect(page.locator('#documentQualificationNotice')).to_be_visible()
    record=page.evaluate('()=>inputs._intake_qualification')
    transport['mode']='refuse';page.evaluate('()=>calculate()')
    assert page.evaluate('()=>lastResult')is None
    expect(page.locator('#documentQualificationNotice')).to_have_count(0)
    assert page.evaluate('()=>inputs._intake_qualification')==record
    transport['mode']='normal';page.evaluate('()=>calculate()');wait_for_result(page)
    expect(page.locator('#documentQualificationNotice')).to_contain_text('условия учёта обязательств')
    assert page.evaluate('()=>inputs._intake_qualification')==record
