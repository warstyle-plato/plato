"""Signed access is preserved; only freshly validated parameters may apply."""
import copy
import json
import subprocess
import shutil
from urllib.parse import parse_qs

import pytest
import main_legacy as core
import teaser_card as tc
from page_blocks import function


@pytest.fixture
def native(monkeypatch, tmp_path):
    from document_protocol_stub import compatible_document_core
    compatible_document_core(monkeypatch,core)
    monkeypatch.setattr(core, '_telegram_token', lambda: 'synthetic-test-signing-key')
    monkeypatch.setattr(core, '_telegram_allowed_user_ids', lambda: set())
    monkeypatch.setattr(core, '_PLATO_STAGE_DIR', tmp_path)
    monkeypatch.setattr(core, '_TELEGRAM_DIALOGS', {})
    return core


def data(token):
    return core.telegram_session_data(core.TelegramSessionRequest(session=token))


def token_from(markup):
    url=markup['inline_keyboard'][0][0]['web_app']['url']
    return parse_qs(url.split('#',1)[1])['telegram_session'][0]


def ready_card(native, chat=17):
    text='Покупка права — 42 млн руб.'
    extraction={'fields':[{'key':'purchase_price_mln','value':42,'unit':'млн руб.','quote':text}],
                'questions':[], 'notes':[]}
    request=native._telegram_agent_request(chat)
    card=native._intake_queue_start('synthetic.pdf',extraction,{'text':text,'pages':1},
        dict(native.DEFAULT_INPUTS),copy.deepcopy(native.TEP_DEFAULT),by_parcel=True,
        actor=request.scope['plato_actor'])
    queue=native._intake_queue_load(card['id'],request=request)
    tc.answer(queue,dict(native.DEFAULT_INPUTS),copy.deepcopy(native.TEP_DEFAULT),
        index=queue['index'],action='stop',spp_split=native.MKD_SPP_SPLIT,
        presets=native.PROJECT_CLASS_PRESETS)
    native._intake_queue_save(queue)
    return native.teaser_card_view(queue,dict(native.DEFAULT_INPUTS),copy.deepcopy(native.TEP_DEFAULT),
                                  by_parcel=True,parcel_region='')


@pytest.mark.parametrize('overrides',[{'purchase_price_mln':180},
    {'purchase_price_mln':float('nan')},{'purchase_price_mln':float('inf')},
    {'purchase_price_mln':42,'_field_origin':{'inputs.purchase_price_mln':{'source':'document'}}}])
def test_old_signed_nonempty_overrides_keep_access_but_require_review(native,overrides):
    token=native._telegram_session(17,['77:01:0000001:123'],calc_overrides=overrides)
    assert native._telegram_verify_session(token)['chat_id']==17
    got=data(token)
    assert got['cadastral_numbers']==['77:01:0000001:123']
    assert got['overrides_review_required']is True and got['calc_overrides']=={}


def test_empty_legacy_link_and_manual_access_are_unchanged(native):
    manual={'tep':{'apartments':{'saleable':240}},'project_name':'Synthetic'}
    token=native._telegram_session(17,[],manual_tep=manual)
    assert data(token)=={'cadastral_numbers':[],'manual_tep':manual,
                         'calc_overrides':{},'overrides_review_required':False}


def test_owned_current_card_proof_applies_exact_payload_and_cannot_be_reused(native):
    card=ready_card(native)
    token=token_from(native._telegram_intake_calc_markup(17,card))
    session=native._telegram_verify_session(token)
    assert session['overrides_application']['scope']=='confirmed_card'
    assert data(token)['calc_overrides']['purchase_price_mln']==42
    assert data(token)['overrides_review_required']is False
    changed=dict(session['calc_overrides'],purchase_price_mln=180)
    changed_token=native._telegram_session(17,[],calc_overrides=changed,
                                         application_proof=session['overrides_application'])
    assert data(changed_token)['overrides_review_required']is True
    # A generic issuer cannot stamp a signed legacy dictionary by itself.
    assert 'overrides_application'not in native._telegram_verify_session(
        native._telegram_session(17,[],calc_overrides=session['calc_overrides']))
    edited=native._telegram_web_app_url(17,[],calc_overrides=session['calc_overrides'],
        application_proof=native._telegram_carry_application_proof(session),mode='edit')
    assert data(parse_qs(edited.split('#',1)[1])['telegram_session'][0])['overrides_review_required']is False


def test_source_owner_and_current_replay_cannot_be_bypassed_by_saved_card_output(native):
    card=ready_card(native)
    assert native._telegram_intake_calc_markup(18,card)is None
    forged=copy.deepcopy(card)
    row=next(r for r in forged['to_engine']if r['path']=='inputs.purchase_price_mln')
    row['value']=180
    assert native._telegram_intake_calc_markup(17,forged)is None
    queue=native._intake_queue_load(card['id'],request=native._telegram_agent_request(17))
    queue['fields'][0]['value']=43
    native._intake_queue_save(queue)
    assert native._telegram_intake_calc_markup(17,card)is None


@pytest.mark.parametrize('mutation',[{'schema':True},{'scope':'saved_model'},
    {'binding':'/private/source/path'},{'sha256':'a'*64},{'extra':'value'}])
def test_proof_has_closed_schema_and_exact_digest(native,mutation):
    card=ready_card(native)
    session=native._telegram_verify_session(token_from(native._telegram_intake_calc_markup(17,card)))
    proof={**session['overrides_application'],**mutation}
    assert native._telegram_application_proof(session['calc_overrides'],proof)is None


def test_confirmed_patch_requires_validated_base_and_canonical_changed_fields(native):
    card=ready_card(native)
    session=native._telegram_verify_session(token_from(native._telegram_intake_calc_markup(17,card)))
    changed=dict(session['calc_overrides'],purchase_price_mln=44)
    proof=native._telegram_confirmed_patch_proof(session,changed,{'purchase_price_mln':44})
    assert proof and proof['scope']=='confirmed_patch'
    assert native._telegram_application_proof(changed,proof)
    legacy={'calc_overrides':session['calc_overrides']}
    assert native._telegram_confirmed_patch_proof(legacy,changed,{'purchase_price_mln':44})is None
    assert native._telegram_confirmed_patch_proof(session,changed,{'purchase_price_mln':'180 м²'})is None
    assert native._telegram_confirmed_patch_proof(session,changed,{'unknown':44})is None
    assert native._telegram_confirmed_patch_proof(session,dict(changed,other=1),{'purchase_price_mln':44})is None


@pytest.mark.parametrize('mode',['calc','intake','edit'])
def test_page_legacy_review_precedes_import_reset_apply_and_any_calculation(mode):
    node=shutil.which('node')
    assert node,'Node is required for the real PAGE application guard'
    bodies='\n'.join(function(name)for name in ['runTelegramLaunch','applyTelegramCalcOverrides','calculate'])
    js='''const assert=require('assert');
let telegramSession='synthetic',telegramMode=MODE,telegramCad='77:01:0000001:123';
let telegramOverridesReviewRequired=true,telegramCalcOverrides={},lastResult={old:true},phaseBundle={};
let notices=0,blocked=0;
const window={};const document={getElementById:()=>null};
const loadTelegramSessionData=async()=>({calc_overrides:{purchase_price_mln:180},overrides_review_required:true});
const telegramOverridesReviewNotice=()=>{notices++;return false};
const blankResultSurfaces=()=>{blocked++};
const resetAll=()=>{throw Error('reset before review')};
const applyTelegramManualTep=()=>{throw Error('import before review')};
'''.replace('MODE',json.dumps(mode))
    js+=bodies+'''
(async()=>{
 await runTelegramLaunch();
 assert.equal(telegramOverridesReviewRequired,true);assert.deepEqual(telegramCalcOverrides,{});
 assert.equal(applyTelegramCalcOverrides(),false);
 assert.equal(await calculate(),null);assert.equal(lastResult,null);assert.equal(phaseBundle,null);
 assert.equal(blocked,1);assert.ok(notices>=3);
})().catch(e=>{console.error(e);process.exit(1)});
'''
    done=subprocess.run([node,'-e',js],capture_output=True,text=True,timeout=10)
    assert done.returncode==0,done.stderr


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('legacy_response',[False,True])
def test_real_page_legacy_link_shows_review_and_never_calculates(native,width,legacy_response):
    from playwright.sync_api import sync_playwright
    import browser_launch
    token=native._telegram_session(17,[],calc_overrides={'purchase_price_mln':180})
    session_data=data(token)
    if legacy_response:
        # The exact pre-gate native shape: signed parameters, no review flag.
        session_data.pop('overrides_review_required')
        session_data['calc_overrides']=native._telegram_verify_session(token)['calc_overrides']
    calls=[]
    errors=[]
    def respond(route):
        path=route.request.url.split('?',1)[0]
        calls.append(path)
        if path.endswith('/calculate'):
            raise AssertionError('Unreviewed link reached calculation')
        if path=='http://127.0.0.1:18299/':
            route.fulfill(status=200,content_type='text/html',body=native.PAGE)
        elif path.endswith('/telegram/session-data'):
            route.fulfill(status=200,content_type='application/json',body=json.dumps(session_data))
        else:
            route.fulfill(status=200,content_type='application/json',body='{}')
    with sync_playwright()as pw:
        browser=browser_launch.launch(pw,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':width,'height':844})
        page.route('**/*',respond)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:18299/?telegram=1#telegram_session='+token,wait_until='domcontentloaded')
        page.wait_for_function('window.__developaidBooted===true')
        note=page.locator('#telegramOverridesReview')
        assert note.is_visible()
        assert 'Вход сохранён' in note.inner_text() and 'подтвердить заново' in note.inner_text()
        before=page.evaluate('({purchase:inputs.purchase_price_mln,applied:telegramCalcOverrides,result:lastResult})')
        assert before['applied']=={} and before['result']is None
        assert before['purchase']==native.DEFAULT_INPUTS['purchase_price_mln']
        assert page.evaluate('calculate()')is None
        assert all(not path.endswith('/calculate')for path in calls)
        assert not errors,errors
        browser.close()


def test_new_cad_confirmation_has_a_finite_price_basis(native,monkeypatch):
    sent=[]
    monkeypatch.setattr(native,'_telegram_send_message',lambda *a,**k:sent.append(k['reply_markup']))
    dialog={'data':{'cadastral_numbers':['77:01:0000001:123'],
        'project_class':next(iter(native.PROJECT_CLASS_PRESETS)),
        'apartment_price_th':240,'commercial_price_th':160,'parking_price_th':1800,
        'smr_th_per_sqm':105}}
    native._telegram_send_cad_calculate_button(17,dialog)
    token=token_from(sent[-1])
    assert data(token)['overrides_review_required']is False
    assert native._telegram_verify_session(token)['overrides_application']['scope']=='confirmed_cad'
    bad=copy.deepcopy(dialog)
    bad['data']['apartment_price_th']=float('nan')
    with pytest.raises(ValueError):native._telegram_send_cad_calculate_button(17,bad)


def test_valid_proof_cannot_authorize_nonfinite_or_huge_confirmed_changes(native):
    card=ready_card(native)
    session=native._telegram_verify_session(token_from(native._telegram_intake_calc_markup(17,card)))
    for unsafe in [float('nan'),float('inf'),10**1000,True,'180 м²']:
        changed=dict(session['calc_overrides'],purchase_price_mln=unsafe)
        assert native._telegram_confirmed_patch_proof(session,changed,{'purchase_price_mln':unsafe})is None


@pytest.mark.parametrize('flag',['missing',None,True,'false',0,{},[]])
def test_old_or_malformed_server_flag_never_promotes_nonempty_overrides(flag):
    # Missing/unknown flags do not attest application safety.
    response={'calc_overrides':{'purchase_price_mln':180}}
    if flag!='missing':response['overrides_review_required']=flag
    body=function('runTelegramLaunch')
    js="""const assert=require('assert');let telegramSession='synthetic',telegramMode='intake';
let telegramOverridesReviewRequired=true,telegramCalcOverrides={};let notices=0;
const window={};const loadTelegramSessionData=async()=>(RESPONSE);
const telegramOverridesReviewNotice=()=>{notices++};
const resetAll=()=>{throw Error('reset before review')};
""".replace('RESPONSE',json.dumps(response))
    js+=body+"""
(async()=>{await runTelegramLaunch();assert.equal(telegramOverridesReviewRequired,true);
assert.deepEqual(telegramCalcOverrides,{});assert.equal(notices,1)})().catch(e=>{console.error(e);process.exit(1)});"""
    done=subprocess.run([shutil.which('node'),'-e',js],capture_output=True,text=True,timeout=10)
    assert done.returncode==0,done.stderr


def test_empty_legacy_response_without_new_flag_keeps_its_access_path():
    body=function('runTelegramLaunch')
    js="""const assert=require('assert');let telegramSession='synthetic',telegramMode='calc',telegramCad='';
let telegramOverridesReviewRequired=true,telegramCalcOverrides={};
const window={};const loadTelegramSessionData=async()=>({calc_overrides:{}});
const telegramOverridesReviewNotice=()=>{throw Error('empty legacy link blocked')};
"""
    js+=body+"""
(async()=>{await runTelegramLaunch();assert.equal(telegramOverridesReviewRequired,false);
assert.deepEqual(telegramCalcOverrides,{})})().catch(e=>{console.error(e);process.exit(1)});"""
    done=subprocess.run([shutil.which('node'),'-e',js],capture_output=True,text=True,timeout=10)
    assert done.returncode==0,done.stderr


@pytest.mark.parametrize('bad_overrides',[[],[180],180,'180',None])
def test_false_flag_requires_an_actual_override_record(bad_overrides):
    response={'calc_overrides':bad_overrides,'overrides_review_required':False}
    body=function('runTelegramLaunch')
    js="""const assert=require('assert');let telegramSession='synthetic',telegramMode='intake';
let telegramOverridesReviewRequired=true,telegramCalcOverrides={};let notices=0;
const window={};const loadTelegramSessionData=async()=>(RESPONSE);
const telegramOverridesReviewNotice=()=>{notices++};
const resetAll=()=>{throw Error('invalid new response reached reset')};
""".replace('RESPONSE',json.dumps(response))
    js+=body+"""\n(async()=>{await runTelegramLaunch();assert.equal(telegramOverridesReviewRequired,true);
assert.deepEqual(telegramCalcOverrides,{});assert.equal(notices,1)})().catch(e=>{console.error(e);process.exit(1)});"""
    done=subprocess.run([shutil.which('node'),'-e',js],capture_output=True,text=True,timeout=10)
    assert done.returncode==0,done.stderr
