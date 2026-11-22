"""Qualified intake cannot silently enter a legacy API or an unadmitted core."""
import copy
import email.message
import io
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
import document_intake_protocol as protocol
from test_document_qualification import document


def admission(**changes):
    value = {'schema': 1, 'origin': 'https://core.example', 'protocol': protocol.PROTOCOL,
             'core_commit': 'a' * 40, 'completed_rollout': True}
    value.update(changes)
    return json.dumps(value)


@pytest.mark.parametrize('value', ['', '{}', admission(schema=True), admission(completed_rollout=False),
    admission(protocol='legacy'), admission(origin='https://other.example'), admission(core_commit='A' * 40),
    admission(extra=True), admission(origin='https://core.example/')])
def test_root_admission_is_closed_explicit_and_bound_to_the_configured_origin(value):
    with pytest.raises(protocol.ProtocolHold):
        protocol.admitted_origin(value, 'https://core.example/ui')


def test_compatible_releases_keep_initial_promotion_evidence_without_commit_equality():
    assert protocol.admitted_origin(admission(core_commit='b' * 40), 'https://CORE.example:443/ui') == 'https://core.example'
    protocol.check_capability(protocol.capability())
    assert 'commit' not in protocol.capability()


@pytest.mark.parametrize('target', ['http://core.example', 'https://u:p@core.example',
    'https://core.example/?other=1', 'https://core.example/#other', 'https://core.\nexample'])
def test_target_origin_does_not_accept_ambiguous_or_credentialled_urls(target):
    with pytest.raises(protocol.ProtocolHold): protocol.admitted_origin(admission(), target)


class CapabilityResponse(io.BytesIO):
    status = 200
    def __init__(self, body, url, *, status=200, content_type='application/json'):
        super().__init__(body); self.url=url; self.status=status
        self.headers=email.message.Message(); self.headers['Content-Type']=content_type
    def geturl(self): return self.url


@pytest.fixture
def target(monkeypatch):
    import main
    core=main.core; calls=[]
    monkeypatch.setattr(core, '_TELEGRAM_WEB_APP_BASE_URL', 'https://core.example')
    monkeypatch.setenv(protocol.ADMISSION_ENV, admission())
    def install(body=None, **changes):
        body=json.dumps(protocol.capability()).encode() if body is None else body
        def open_(request, timeout):
            calls.append(request)
            assert timeout==5 and request.data is None
            assert not any(k.lower() in {'authorization','cookie'} for k in request.headers)
            return CapabilityResponse(body, changes.get('url', request.full_url),
                status=changes.get('status',200), content_type=changes.get('content_type','application/json'))
        monkeypatch.setattr(core.urllib.request, 'build_opener', lambda *a:
                            type('SyntheticOpener',(),{'open':staticmethod(open_),'close':lambda self:None})())
    install()
    return core,calls,install


def test_default_qualified_handoff_HOLD_occurs_before_lookup_or_session_signing(target,monkeypatch):
    core,calls,_=target; monkeypatch.delenv(protocol.ADMISSION_ENV)
    monkeypatch.setattr(core,'_telegram_session',lambda *a,**k:pytest.fail('a held link must not be signed'))
    with pytest.raises(protocol.ProtocolHold):
        core._telegram_web_app_url(17,[],calc_overrides={'_intake_qualification':{}})
    assert calls==[]


@pytest.mark.parametrize('body,changes',[
    (b'{"schema":1,"protocol":"legacy"}',{}), (b'{"schema":true,"protocol":"qualified-intake-cas-v1"}',{}),
    (b'{"schema":1,"protocol":"qualified-intake-cas-v1","extra":1}',{}),
    (b'{"schema":1,"schema":1,"protocol":"qualified-intake-cas-v1"}',{}),
    (b'x'*4097,{}), (None,{'status':404}), (None,{'url':'https://other.example/'}),
    (None,{'content_type':'text/html'})])
def test_current_target_capability_is_required_without_legacy_fallback(target,body,changes):
    core,calls,install=target; install(body,**changes)
    with pytest.raises(protocol.ProtocolHold): core._telegram_document_target()
    assert len(calls)==1 and calls[0].full_url=='https://core.example'+protocol.CAPABILITY_PATH


def test_qualified_URL_uses_new_entry_and_ordinary_links_keep_their_existing_path(target,monkeypatch):
    core,calls,_=target; signed=[]
    monkeypatch.setattr(core,'_telegram_session',lambda *a,**k:signed.append(k)or'SYNTHETIC_TOKEN')
    url=core._telegram_web_app_url(17,[],calc_overrides={'_intake_qualification':{}},mode='edit')
    assert urlsplit(url).path==protocol.ENTRY_PATH and len(calls)==1
    assert 'telegram_session=SYNTHETIC_TOKEN' in url and signed[0]['calc_overrides']=={'_intake_qualification':{}}
    monkeypatch.delenv(protocol.ADMISSION_ENV)
    ordinary=core._telegram_web_app_url(17,[],manual_tep={'tep':{}})
    assert urlsplit(ordinary).path=='/' and len(calls)==1


def test_new_entry_and_session_delegate_keep_auth_and_do_not_expose_old_PAGE_fallback(monkeypatch):
    import main
    import main_registry
    core=main.core; client=TestClient(core.app)
    page=client.get(protocol.ENTRY_PATH)
    assert page.status_code==200 and 'window.PlatoQualifiedDocumentEntry=true' in page.text
    assert page.headers['Cache-Control'].startswith('no-store')
    assert page.headers['X-DevelopAid-Surface']=='ia-main'
    assert 'window.PlatoQualifiedDocumentEntry=true'not in client.get('/').text
    assert client.get(protocol.CAPABILITY_PATH).json()==protocol.capability()
    # The versioned session reader is the same authenticated native authority.
    assert client.post(protocol.SESSION_PATH,json={'session':'not-signed'}).status_code in {403,503}
    client.close()


def test_capability_fastpath_does_not_initialize_or_read_browser_owner_state(monkeypatch,tmp_path):
    import main
    core=main.core
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'must-stay-absent')
    monkeypatch.setattr(core._agent_access,'browser_owner',lambda *a,**k:pytest.fail('capability must not touch owner state'))
    client=TestClient(core.app)
    response=client.get(protocol.CAPABILITY_PATH)
    assert response.status_code==200 and response.json()==protocol.capability()
    assert response.headers['Cache-Control']=='no-store' and 'set-cookie'not in response.headers
    assert not core._PLATO_STAGE_DIR.exists()
    client.close()


@pytest.mark.parametrize('path',['/agent/document/answer','/agent/document/apply'])
@pytest.mark.parametrize('body,reason',[(b'','пуст'),(b'not-json','не разобрано'),
    (b'{"session":','не разобрано'),(b'[1,2]','объект JSON'),
    (b'"BODY_SECRET_SENTINEL"','объект JSON'),(b'\xff','не разобрано')])
def test_legacy_malformed_body_uses_named_refusal_before_owner_or_queue_IO(path,body,reason,monkeypatch,tmp_path):
    import main
    core=main.core
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'must-stay-absent')
    auth_calls=[];native_auth=core._require_web_access
    def auth(*a,**k):auth_calls.append(1);return native_auth(*a,**k)
    def forbidden(*a,**k):pytest.fail('a malformed legacy request must not enter owner/queue operations')
    monkeypatch.setattr(core,'_require_web_access',auth)
    monkeypatch.setattr(core._agent_access,'browser_owner',forbidden)
    monkeypatch.setattr(core,'_intake_queue_load',forbidden)
    monkeypatch.setattr(core,'_intake_queue_save',forbidden)
    client=TestClient(core.app)
    try:response=client.post(path,content=body)
    finally:client.close()
    assert response.status_code==422 and reason in response.json()['detail']
    assert response.headers['Cache-Control']=='no-store'and 'set-cookie'not in response.headers
    assert 'BODY_SECRET_SENTINEL'not in response.text and not core._PLATO_STAGE_DIR.exists()
    assert auth_calls==[]


@pytest.mark.parametrize('path',['/agent/document/answer','/agent/document/apply'])
def test_legacy_HTTP_authenticates_then_refuses_without_owner_queue_or_source_IO(path,monkeypatch,tmp_path):
    import main
    core=main.core;key='synthetic-refresh-admin'
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic-refresh-signing')
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',key)
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'must-stay-absent')
    def forbidden(*a,**k):pytest.fail('a legacy refusal must not enter owner/queue/document operations')
    monkeypatch.setattr(core._agent_access,'browser_owner',forbidden)
    monkeypatch.setattr(core,'_intake_queue_load',forbidden)
    monkeypatch.setattr(core,'_intake_queue_save',forbidden)
    monkeypatch.setattr(core.teaser_card,'answer',forbidden)
    client=TestClient(core.app)
    invalid=client.post(path,json={'intake_id':'a'*32,'session':'not-signed','access_key':'wrong'})
    assert invalid.status_code in {401,403} and invalid.status_code!=409
    accepted_auth=client.post(path,json={'intake_id':'a'*32,'access_key':key})
    assert accepted_auth.status_code==409 and accepted_auth.json()=={'detail':protocol.REFRESH_MESSAGE}
    assert not core._PLATO_STAGE_DIR.exists()and 'set-cookie'not in accepted_auth.headers
    client.close()


def test_versioned_answer_apply_preserve_native_owner_CAS_and_signed_card(monkeypatch,tmp_path):
    import main
    core=main.core; chat=900001237
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'native-stage')
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic-protocol-signing')
    monkeypatch.setattr(core,'_telegram_allowed_user_ids',lambda:set())
    monkeypatch.setattr(core,'usage_track',lambda *a,**k:None)
    monkeypatch.setenv('DEVELOPAID_PAYWALL','0');monkeypatch.setenv('DEVELOPAID_ADMIN_IDS',str(chat))
    token=core._telegram_session(chat,[]); other=core._telegram_session(chat+1,[])
    inputs=dict(core.DEFAULT_INPUTS);tep=copy.deepcopy(core.TEP_DEFAULT)
    request=core.Request({'type':'http','headers':[],'scheme':'http','server':('testserver',80),
                          'path':'/agent/document/start','client':('testclient',123)})
    actor=core._agent_bind_actor(core.AgentDocumentRequest(session=token),request,private_surface='web')
    card=core._intake_queue_start('synthetic.pdf',{'fields':[],'questions':[]},
        {'text':'Synthetic source'},inputs,tep,actor=actor)
    body=dict(intake_id=card['id'],index=card['questions']['index'],action='stop',choice=-1,
        queue_revision=card['queue_revision'],question_token=card['question_token'],inputs=inputs,tep=tep,session=token)
    client=TestClient(core.app)
    denied=client.post(protocol.ANSWER_PATH,json={**body,'session':other})
    assert denied.status_code in {403,404} and 'card'not in str(denied.json())
    answered=client.post(protocol.ANSWER_PATH,json=body)
    assert answered.status_code==200,answered.text
    result=answered.json();assert result['document_protocol']==protocol.capability()
    assert 'document_protocol'not in result['card']
    replay=client.post(protocol.ANSWER_PATH,json=body)
    assert replay.status_code==409 and replay.json()['detail']['document_protocol']==protocol.capability()
    ready=result['card'];assert ready['ready']
    applied=client.post(protocol.APPLY_PATH,json=dict(intake_id=ready['id'],card_key=ready['card_key'],
        inputs=inputs,tep=tep,session=token))
    assert applied.status_code==200,applied.text
    got=applied.json();assert got['document_protocol']==protocol.capability()
    assert got['card']['card_key']==ready['card_key']
    assert got['inputs']['_intake_qualification']['status']=='verified_empty'
    # An old client on the new server still cannot omit displayed CAS bindings.
    legacy={k:v for k,v in body.items()if k not in ('queue_revision','question_token')}
    assert client.post('/agent/document/answer',json=legacy).status_code==409
    client.close()


@pytest.mark.parametrize('scenario',['old_card','old_capability','new_card_old_worker','missing_response_tag'])
def test_real_shared_JS_never_posts_to_legacy_routes_or_accepts_an_old_worker(scenario):
    node=shutil.which('node');assert node,'node is required for the protocol adapter check'
    source=(Path(__file__).resolve().parents[1]/'document_client.js').read_text()
    program=r"""
const vm=require('vm');const calls=[];
const config=CONFIG;
const response=(status,data)=>({ok:status===200,status,json:async()=>data});
const ctx={window:{PlatoDocumentProtocol:config},setTimeout,clearTimeout,
 fetch:async(path,options={})=>{calls.push({path,method:options.method||'GET'});
 if(path===config.capabilityPath)return response(200,SCENARIO==='old_capability'?{schema:1,protocol:'legacy'}:{schema:1,protocol:config.protocol});
 if(path===config.answerPath)return response(SCENARIO==='new_card_old_worker'?404:200,{});
 throw new Error('LEGACY_REQUEST');}};
vm.createContext(ctx);vm.runInContext(SOURCE,ctx);
(async()=>{const card={id:'a'.repeat(32),queue_revision:0,question_token:'b'.repeat(64)};
if(SCENARIO==='old_card')delete card.question_token;
try{await ctx.window.PlatoDocumentClient.answer(card,{intake_id:card.id,queue_revision:0,question_token:'b'.repeat(64)});
throw new Error('OLD_RESPONSE_ACCEPTED');}catch(e){if(!e.message.includes('Модель обновляется'))throw e;}
console.log(JSON.stringify(calls));})().catch(e=>{console.error(e);process.exit(1)});
""".replace('CONFIG',json.dumps(protocol.client_contract())).replace('SCENARIO',json.dumps(scenario)).replace('SOURCE',json.dumps(source))
    completed=subprocess.run([node,'-e',program],capture_output=True,text=True,timeout=10)
    assert completed.returncode==0,completed.stderr
    calls=json.loads(completed.stdout)
    assert not any(call['path']in('/agent/document/answer','/agent/document/apply')for call in calls)
    if scenario=='old_card':assert calls==[]
    elif scenario=='old_capability':assert len(calls)==1
    else:assert [c['path']for c in calls]==[protocol.CAPABILITY_PATH,protocol.ANSWER_PATH]


@pytest.mark.parametrize('width',[390,1440])
def test_qualified_entry_refuses_old_target_before_overrides_or_calculation(document,monkeypatch,width):
    import main
    import main_registry
    from browser import serve,chromium_or_skip
    from playwright.sync_api import sync_playwright,expect
    item=document();core=main.core
    monkeypatch.setenv('DEVELOPAID_PAYWALL','0')
    monkeypatch.setattr(core,'fetch_current_cbr_key_rate',lambda:{'rate':14.0,'date':'2026-11-15','live':False,'source':'Synthetic'})
    posts=[]
    with serve(main_registry.app,18451+(width==390))as base,sync_playwright()as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page=browser.new_page(viewport={'width':width,'height':900})
        page.route('**'+protocol.CAPABILITY_PATH,lambda route:route.fulfill(status=404,
            content_type='application/json',body='{"detail":"Not Found"}'))
        page.on('request',lambda req:posts.append(req.url)if req.method=='POST'else None)
        page.goto(base+protocol.ENTRY_PATH+'#telegram_session='+item['token'],wait_until='networkidle')
        expect(page.locator('#glavapuStatus')).to_contain_text('Модель обновляется')
        expect(page.locator('#glavapuStatus')).to_be_visible()
        # Profile/class bootstrap reads precede this existing launch gate.
        assert all(urlsplit(url).path in {'/profile/get','/classes/overrides/get'}for url in posts)
        assert page.evaluate('() => lastResult')is None
        assert page.evaluate('() => inputs._intake_qualification||null')is None
        browser.close()


def _origin_projection(base,source='TELEGRAM_WEBAPP_URL'):
    import ast
    text=(Path(__file__).resolve().parents[1]/'engine/bot_telegram.py').read_text()
    function=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)
                  and n.name=='_telegram_document_origin_metadata')
    namespace=dict(document_protocol=protocol,Any=object,
                   _TELEGRAM_WEB_APP_BASE_URL=base,_TELEGRAM_WEB_APP_BASE_SOURCE=source)
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<native public-origin projection>','exec'),namespace)
    return namespace['_telegram_document_origin_metadata']()


@pytest.mark.parametrize('settings,base,source,reads',[
    ({},'https://plato-development-investment-model.onrender.com','default_public',
     ['TELEGRAM_PUBLIC_BASE_URL','RENDER_EXTERNAL_URL','TELEGRAM_WEBAPP_URL','TELEGRAM_WEB_APP_BASE_URL']),
    ({'TELEGRAM_PUBLIC_BASE_URL':'https://developaid.ru///'},'https://developaid.ru','TELEGRAM_PUBLIC_BASE_URL',
     ['TELEGRAM_PUBLIC_BASE_URL','TELEGRAM_WEBAPP_URL','TELEGRAM_WEB_APP_BASE_URL']),
    ({'RENDER_EXTERNAL_URL':'https://plato-development-investment-model.onrender.com/'},
     'https://plato-development-investment-model.onrender.com','RENDER_EXTERNAL_URL',
     ['TELEGRAM_PUBLIC_BASE_URL','RENDER_EXTERNAL_URL','TELEGRAM_WEBAPP_URL','TELEGRAM_WEB_APP_BASE_URL']),
    ({'TELEGRAM_WEB_APP_BASE_URL':'https://developaid.ru/legacy/'},'https://developaid.ru/legacy','TELEGRAM_WEB_APP_BASE_URL',
     ['TELEGRAM_PUBLIC_BASE_URL','RENDER_EXTERNAL_URL','TELEGRAM_WEBAPP_URL','TELEGRAM_WEB_APP_BASE_URL']),
    ({'TELEGRAM_PUBLIC_BASE_URL':'https://developaid.ru/public','RENDER_EXTERNAL_URL':'https://ignored.invalid',
      'TELEGRAM_WEBAPP_URL':'https://developaid.ru/primary///','TELEGRAM_WEB_APP_BASE_URL':'https://ignored.invalid'},
     'https://developaid.ru/primary','TELEGRAM_WEBAPP_URL',['TELEGRAM_PUBLIC_BASE_URL','TELEGRAM_WEBAPP_URL']),
    ({'TELEGRAM_WEBAPP_URL':' ','TELEGRAM_WEB_APP_BASE_URL':'https://developaid.ru'},' ','TELEGRAM_WEBAPP_URL',
     ['TELEGRAM_PUBLIC_BASE_URL','RENDER_EXTERNAL_URL','TELEGRAM_WEBAPP_URL']),
])
def test_origin_source_capture_preserves_import_time_reads_and_base_exactly(settings,base,source,reads):
    import ast
    import types
    names={'_TELEGRAM_PUBLIC_BASE_URL','_TELEGRAM_PUBLIC_BASE_SOURCE',
           '_TELEGRAM_WEB_APP_BASE_URL','_TELEGRAM_WEB_APP_BASE_SOURCE'}
    text=(Path(__file__).resolve().parents[1]/'engine/bot_telegram.py').read_text()
    statements=[n for n in ast.parse(text).body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name)and t.id in names for t in n.targets)]
    called=[]
    class Settings:
        def get(self,key):called.append(key);return settings.get(key)
    namespace=dict(os=types.SimpleNamespace(environ=Settings()))
    exec(compile(ast.Module(body=statements,type_ignores=[]),'<native URL import-time assignments>','exec'),namespace)
    assert namespace['_TELEGRAM_WEB_APP_BASE_URL']==base
    assert namespace['_TELEGRAM_WEB_APP_BASE_SOURCE']==source and called==reads


@pytest.mark.parametrize('base,origin',[
    ('https://developaid.ru','https://developaid.ru'),
    ('https://DEVELOPAID.RU:443/private/path','https://developaid.ru'),
    ('https://plato-development-investment-model.onrender.com/path',
     'https://plato-development-investment-model.onrender.com'),
    ('http://developaid.ru',None),('https://developaid.ru:8443',None),
    ('https://user:SECRET@developaid.ru',None),('https://developaid.ru/?SECRET=1',None),
    ('https://developaid.ru/#SECRET',None),('https://unknown.example.org',None),
    ('https://127.0.0.1',None),('https://8.8.8.8',None),('https://[::1]',None),
    ('https://service.internal',None),('https://developaid.ru.attacker.example',None),
    ('https://developaid.ru.',None),
    ('https://developaid.ru/SECRET path',None),(None,None),([],None),
])
def test_origin_metadata_discloses_only_exact_known_public_origins(base,origin,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('origin disclosure must not resolve DNS'))
    result=_origin_projection(base)
    assert result=={'origin':origin,'source':'TELEGRAM_WEBAPP_URL'}
    assert 'SECRET'not in json.dumps(result)and set(result)=={'origin','source'}


@pytest.mark.parametrize('source',[None,[],{},'unrecognized'])
def test_origin_metadata_source_is_a_closed_token(source):
    assert _origin_projection('https://developaid.ru',source)=={'origin':None,'source':'unavailable'}


def test_exact_origin_metadata_GET_is_private_bounded_and_has_no_owner_or_callback_IO(monkeypatch,tmp_path):
    import main
    core=main.core
    monkeypatch.setattr(core,'_TELEGRAM_WEB_APP_BASE_URL','https://developaid.ru/private/path')
    monkeypatch.setattr(core,'_TELEGRAM_WEB_APP_BASE_SOURCE','TELEGRAM_WEBAPP_URL')
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'must-remain-absent')
    def forbidden(*a,**k):pytest.fail('metadata must not enter owner/auth/queue/Telegram/provider callbacks')
    monkeypatch.setattr(core._agent_access,'browser_owner',forbidden)
    for name in ['_require_web_access','_intake_queue_load','_intake_queue_save','_telegram_token',
                 '_telegram_allowed_user_ids','_telegram_document_target','_telegram_session',
                 '_telegram_api','_openai_responses_request']:
        monkeypatch.setattr(core,name,forbidden)
    client=TestClient(core.app)
    try:response=client.get('/telegram/status?document_origin_only=1')
    finally:client.close()
    assert response.status_code==200 and response.json()=={'origin':'https://developaid.ru','source':'TELEGRAM_WEBAPP_URL'}
    assert response.headers['X-DevelopAid-Metadata']=='document-origin-v1'
    assert response.headers['Cache-Control']=='private, no-store'and 'set-cookie'not in response.headers
    assert len(response.content)<=512 and not core._PLATO_STAGE_DIR.exists()


@pytest.mark.parametrize('method,path,query',[
    ('GET','/telegram/status',''),('GET','/telegram/status','document_origin_only=0'),
    ('GET','/telegram/status','document_origin_only=%31'),
    ('GET','/telegram/status','document_origin_only=1&extra=1'),
    ('GET','/telegram/status','document_origin_only=1&document_origin_only=1'),
    ('POST','/telegram/status','document_origin_only=1'),
    ('HEAD','/telegram/status','document_origin_only=1'),
    ('GET','/telegram/status/','document_origin_only=1'),
])
def test_origin_metadata_fastpath_does_not_change_other_requests(method,path,query):
    import ast
    import asyncio
    import types
    import document_core_admission
    text=(Path(__file__).resolve().parents[1]/'engine/agent_routes.py').read_text()
    function=next(n for n in ast.parse(text).body if isinstance(n,ast.AsyncFunctionDef)
                  and n.name=='_document_protocol_metadata')
    function.decorator_list=[]
    namespace=dict(Request=object,document_protocol=protocol,
        document_core_admission=document_core_admission,
        _telegram_document_origin_metadata=lambda:pytest.fail('other requests must retain their original path'))
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<native exact metadata routing>','exec'),namespace)
    request=types.SimpleNamespace(method=method,url=types.SimpleNamespace(path=path,query=query));calls=[]
    async def next_(value):calls.append(value);return 'unchanged'
    assert asyncio.run(namespace['_document_protocol_metadata'](request,next_))=='unchanged'and calls==[request]
