"""Signed document uncertainty survives model edits, storage and real outputs."""
from __future__ import annotations
import base64
import copy
import hashlib
import hmac
import io
import json
from urllib.parse import parse_qs
import zipfile

import pytest
import main
import intake_qualification as qual

core=main.core
CHAT=900000275
TEXT='Цена покупки 73,5 млн руб. Передача 275 м² городу, денежная оценка не указана.'


@pytest.fixture
def document(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'stage')
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    monkeypatch.setattr(core,'_telegram_token',lambda:'123:synthetic-qualification')
    monkeypatch.setattr(core,'_telegram_allowed_user_ids',lambda:set())
    monkeypatch.setattr(core,'usage_track',lambda *a,**k:None)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','synthetic-qualification-admin')
    def make(priced=False):
        request=core._telegram_agent_request(CHAT)
        inputs=dict(core.DEFAULT_INPUTS);tep=copy.deepcopy(core.TEP_DEFAULT)
        first=core._intake_queue_start('synthetic-conditions.pdf',{
            'fields':[{'key':'purchase_price_mln','value':'73,5','unit':'млн руб.', 'quote':'Цена покупки 73,5 млн руб.'}],
            'questions':[{'key':'','question':'Как учитывать передачу 275 м² городу?',
                'quote':'Передача 275 м² городу', 'options':['В цену сделки','В социальную нагрузку']}], 'notes':[]},
            {'text':TEXT,'pages':1,'source':{'kind':'upload','sha256':hashlib.sha256(TEXT.encode()).hexdigest()}},inputs,tep,
            actor=request.scope['plato_actor'])
        queue=core._intake_queue_load(first['id'],request=request)
        got=core.teaser_card.answer(queue,inputs,tep,index=0,action='answer'if priced else'skip',choice=1,
            value='3,25 млн'if priced else'',spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
        assert not got.get('confirm')and not got.get('invalid')
        core._intake_queue_save(queue)
        core.teaser_card.answer(queue,inputs,tep,index=1,action='answer',choice=0,
            spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
        core._intake_queue_save(queue)
        card=core.teaser_card_view(queue,inputs,tep,by_parcel=True,parcel_region='')
        markup=core._telegram_intake_calc_markup(CHAT,card)
        assert markup
        token=parse_qs(markup['inline_keyboard'][0][0]['web_app']['url'].split('#',1)[1])['telegram_session'][0]
        overrides=core.telegram_session_data(core.TelegramSessionRequest(session=token))['calc_overrides']
        model_inputs={**inputs,**{k:copy.deepcopy(v)for k,v in overrides.items()if k!='_tep'}}
        return {'queue':queue,'card':card,'token':token,'overrides':overrides,'inputs':model_inputs,'tep':tep,
                'markup':markup,'record':overrides[qual.KEY]}
    return make


def test_signed_handoff_names_excluded_obligation_without_inventing_cash(document):
    item=document()
    assert item['overrides']==core.teaser_card.calc_overrides(item['card'])
    assert item['overrides']['purchase_price_mln']==73.5
    assert 'social_compensation_mln'not in item['overrides']
    state=core._intake_qualification_state(item['inputs'])
    assert state['verified']is True and state['status']=='conditional'
    assert '275 м²'in state['reason']and 'не включена'in state['reason']
    assert 'В социальную нагрузку'in state['reason']
    record=item['record']
    assert record['revision']==2 and record['intake_id']==item['queue']['id']
    assert record['queue_sha256']==item['queue']._intake_snapshot['sha256']
    assert record['source']['sha256']==hashlib.sha256(TEXT.encode()).hexdigest()
    assert len(record['owner'])==len(record['recipient'])==64
    assert '123:synthetic'not in json.dumps(record)and 'synthetic-qualification-admin'not in json.dumps(record)
    assert 'неуточнённых'in item['markup']['inline_keyboard'][0][0]['text']


def test_fully_priced_card_has_explicit_verified_empty_and_ordinary_label(document):
    item=document(True);state=core._intake_qualification_state(item['inputs'])
    assert state=={'status':'verified_empty','verified':True,'obligations':[],'reason':''}
    assert item['overrides']['purchase_price_mln']==73.5 and item['overrides']['social_compensation_mln']==3.25
    assert item['markup']['inline_keyboard'][0][0]['text']=='Всё верно, считать'


@pytest.mark.parametrize('field,value',[('status','verified_empty'),('obligations',[]),('owner','a'*64),
    ('binding','b'*64),('source',{'kind':'file','sha256':'c'*64}),('recipient','d'*64),('extra',True)])
def test_mutated_qualification_is_unverified_and_cannot_receive_an_application_proof(document,field,value):
    item=document();changed=copy.deepcopy(item['overrides']);changed[qual.KEY][field]=value
    state=core._intake_qualification_state(changed)
    assert state['status']=='review_required'and state['verified']is False
    signed=core._telegram_verify_session(item['token'])
    token=core._telegram_session(CHAT,[],calc_overrides=changed,application_proof=signed['overrides_application'])
    assert core._telegram_verify_session(token)['chat_id']==CHAT
    assert core.telegram_session_data(core.TelegramSessionRequest(session=token))['overrides_review_required']is True


def test_generic_issuer_and_another_recipient_cannot_promote_the_signed_record(document):
    item=document();session=core._telegram_verify_session(item['token'])
    for chat,proof in [(CHAT,None),(CHAT+1,session['overrides_application'])]:
        token=core._telegram_session(chat,[],calc_overrides=item['overrides'],application_proof=proof)
        assert core._telegram_verify_session(token)['chat_id']==chat
        admitted=core.telegram_session_data(core.TelegramSessionRequest(session=token))
        assert admitted['overrides_review_required']is True and admitted['calc_overrides']=={}


def test_old_signed_nonempty_document_proof_preserves_login_but_requires_review(document):
    item=document();overrides={k:v for k,v in item['overrides'].items()if k not in {qual.KEY,qual.PACKET}}
    proof={'schema':1,'scope':'confirmed_card','binding':'a'*64,'sha256':core._telegram_overrides_digest(overrides)}
    body={'chat_id':CHAT,'cad':[],'exp':int(core.time.time())+3600,'calc_overrides':overrides,'overrides_application':proof}
    raw=base64.urlsafe_b64encode(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).rstrip(b'=')
    signature=hmac.new(core._telegram_token().encode(),raw,hashlib.sha256).digest()[:20]
    token=raw.decode()+'.'+base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
    assert core._telegram_verify_session(token)['chat_id']==CHAT
    got=core.telegram_session_data(core.TelegramSessionRequest(session=token))
    assert got['overrides_review_required']is True and got['calc_overrides']=={}


def test_confirmed_ordinary_patch_preserves_the_same_qualification_without_restamping(document):
    item=document();session=core._telegram_verify_session(item['token'])
    changed={**copy.deepcopy(item['overrides']),'purchase_price_mln':74.5}
    proof=core._telegram_confirmed_patch_proof(session,changed,{'purchase_price_mln':74.5})
    assert proof and proof['scope']=='confirmed_patch'
    token=core._telegram_session(CHAT,[],calc_overrides=changed,application_proof=proof)
    admitted=core.telegram_session_data(core.TelegramSessionRequest(session=token))
    assert admitted['overrides_review_required']is False
    assert admitted['calc_overrides'][qual.KEY]==item['record']
    assert admitted['calc_overrides']['purchase_price_mln']==74.5
    assert '275 м²'in core._intake_qualification_state(admitted['calc_overrides'])['reason']


def test_disclosure_only_edit_session_does_not_manufacture_numeric_admission(document):
    item=document()
    token=core._telegram_session(CHAT,[],calculation_qualification=item['record'])
    admitted=core.telegram_session_data(core.TelegramSessionRequest(session=token))
    assert admitted['calc_overrides']=={}and admitted['overrides_review_required']is False
    assert admitted['calculation_qualification']==item['record']
    assert 'overrides_application'not in core._telegram_verify_session(token)
    broken=copy.deepcopy(item['record']);broken['obligations']=[]
    refused=core._telegram_session(CHAT,[],calculation_qualification=broken)
    assert core._telegram_verify_session(refused)['chat_id']==CHAT
    assert core.telegram_session_data(core.TelegramSessionRequest(session=refused))['qualification_review_required']is True


def test_stale_loaded_queue_cannot_seal_a_new_qualification_after_another_write(document):
    item=document();stale=copy.deepcopy(item['queue'])
    current=core._intake_queue_load(stale['id'],request=core._telegram_agent_request(CHAT))
    current['notes']=['A newer source review'];core._intake_queue_save(current)
    with pytest.raises(core.HTTPException)as conflict:
        core.teaser_card_view(stale,dict(core.DEFAULT_INPUTS),copy.deepcopy(core.TEP_DEFAULT))
    assert conflict.value.status_code==409


@pytest.mark.parametrize('metadata',[{qual.KEY:None},{qual.KEY:{}},{qual.PACKET:{'kind':'teaser_card','intake_id':'a'*32}}])
def test_missing_document_qualification_is_never_verified_empty(metadata):
    assert core._intake_qualification_state(metadata)['status']=='review_required'


def test_plain_model_has_no_document_claim_and_legacy_oversize_fields_are_closed(document):
    assert core._intake_qualification_state(dict(core.DEFAULT_INPUTS))is None
    item=document();state=copy.deepcopy(item['queue']);state['cards'][0]['quote']='x'*501
    with pytest.raises(ValueError):qual.obligations(state)
    record=copy.deepcopy(item['record']);record['obligations'][0]['index']=True
    assert qual.validate(record,core._intake_qualification_key('telegram'))is None


def test_existing_project_storage_keeps_signed_qualification_through_ordinary_edit(document):
    item=document();payload={'inputs':item['inputs'],'tep':item['tep'],'phasing':{},'scenario':'base'}
    saved=core.project_save(CHAT,'Synthetic qualified project',payload)
    opened=core.project_open(CHAT,saved['id'])
    assert opened['payload']['inputs'][qual.KEY]==item['record']
    opened['payload']['inputs']['purchase_price_mln']=74.5
    core.project_save(CHAT,'Synthetic qualified project',opened['payload'],project_id=saved['id'])
    restored=core.project_open(CHAT,saved['id'])['payload']['inputs']
    assert restored[qual.KEY]==item['record']and restored['purchase_price_mln']==74.5
    assert '275 м²'in core._intake_qualification_state(restored)['reason']


def test_real_calculation_keeps_known_cash_and_composes_specific_disclosure(document):
    item=document();inputs=copy.deepcopy(item['inputs']);tep=copy.deepcopy(item['tep'])
    ordinary={k:v for k,v in inputs.items()if k not in {qual.KEY,qual.PACKET,'_field_origin'}}
    known=core.calculate(core.CalcRequest(inputs=ordinary,tep=copy.deepcopy(tep),rates=[]))
    qualified=core.calculate(core.CalcRequest(inputs=inputs,tep=copy.deepcopy(tep),rates=[]))
    for key in ['revenue','capex','net_profit','npv','irr_project','llcr']:
        assert qualified['summary'][key]==known['summary'][key],key
    assert qualified['deal']==known['deal']
    assert qualified['summary']['preliminary']is True
    assert '275 м²'in qualified['summary']['preliminary_reason']
    assert qualified['summary']['intake_qualification']['status']=='conditional'
    verdict=qualified['report']['entry_price_verdict']
    assert 'обязательства'in verdict['title']and verdict['tone']=='edge'
    empty=document(True)
    priced=core.calculate(core.CalcRequest(inputs=empty['inputs'],tep=copy.deepcopy(tep),rates=[]))
    assert priced['summary']['intake_qualification']['status']=='verified_empty'
    assert '275 м²'not in priced['summary'].get('preliminary_reason','')


@pytest.mark.parametrize('outcome,expected',[('OSError: /private/path/token read-only file system','только для чтения'),
    ('PermissionError: /private/path/token permission denied','недостаточно прав'),
    ('OSError: /private/path/token no space left on device','недостаточно свободного места'),
    ('UnexpectedError: /private/path/token secret=secret-value','недоступно')])
def test_history_failure_has_a_closed_truthful_cause_without_diagnostics(outcome,expected):
    reason=core._telegram_document_memory_reason(outcome)
    assert expected in reason
    assert '/private'not in reason and 'token'not in reason and 'secret'not in reason and 'Error'not in reason



def test_a_valid_disclosure_cannot_attest_unsigned_different_money(document):
    item=document();changed=copy.deepcopy(item['overrides']);changed['purchase_price_mln']=999.25
    for scope in ['confirmed_card','confirmed_patch','confirmed_cad']:
        # All visible hashes are forgeable by a client; none is an issuer.
        fake={'schema':1,'scope':scope,'binding':item['record']['binding'],
            'sha256':core._telegram_overrides_digest(changed)}
        token=core._telegram_session(CHAT,[],calc_overrides=changed,application_proof=fake)
        assert core._telegram_verify_session(token)['chat_id']==CHAT
        assert core.telegram_session_data(core.TelegramSessionRequest(session=token))['overrides_review_required']is True



def test_oversize_qualification_refuses_visibly_without_losing_the_durable_card(document,monkeypatch):
    item=document();state=item['queue'];state['cards'][0]['quote']='x'*501
    core._intake_queue_save(state)
    before=core._intake_queue_path(state['id']).read_bytes();sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append((text,kw)))
    dialog={'intake':{'id':state['id']},'step':'intake_ready'}
    core._telegram_dialog_save(CHAT,dialog)
    core._telegram_intake_ask_next(CHAT,core._telegram_dialog_get(CHAT))
    assert any('Кнопка расчёта не выдана'in text for text,_ in sent)
    assert not any((kw.get('reply_markup')or{}).get('inline_keyboard')for _,kw in sent)
    assert core._intake_queue_path(state['id']).read_bytes()==before
    assert core._telegram_dialog_get(CHAT)['intake']['id']==state['id']


@pytest.mark.parametrize('record',[None,{},[],False,{'key_scope':[]},{'key_scope':{}},
    {'key_scope':True},{'key_scope':'stage','schema':[]},{'key_scope':'telegram','source':[]}])
def test_malformed_qualification_shape_is_a_closed_visible_review(record):
    state=core._intake_qualification_state({qual.KEY:record})
    assert state['status']=='review_required'and state['verified']is False and state['reason']


@pytest.mark.parametrize('scope',[[],{},None,True])
def test_malformed_application_scope_is_closed(scope):
    assert core._telegram_application_proof({}, {'schema':1,'scope':scope,'binding':'a'*64,'sha256':'b'*64})is None


def native_resolution(item):
    request=core._telegram_agent_request(CHAT)
    card=item['card']
    reopened=core.agent_document_answer(core.AgentDocumentAnswerRequest(intake_id=card['id'],
        queue_revision=card['queue_revision'],question_token=card['question_token'],index=0,action='review',
        inputs=dict(core.DEFAULT_INPUTS),tep=copy.deepcopy(item['tep']),session=item['token']),request)['card']
    assert reopened['questions']['index']==0 and not reopened['ready']
    resolved=core.agent_document_answer(core.AgentDocumentAnswerRequest(intake_id=card['id'],
        queue_revision=reopened['queue_revision'],question_token=reopened['question_token'],index=0,
        action='answer',choice=1,value='3,25 млн',inputs=dict(core.DEFAULT_INPUTS),
        tep=copy.deepcopy(item['tep']),session=item['token']),request)['card']
    assert resolved['ready']
    applied=core.agent_document_apply(core.AgentDocumentApplyRequest(intake_id=card['id'],
        card_key=resolved['card_key'],inputs=dict(core.DEFAULT_INPUTS),tep=copy.deepcopy(item['tep']),
        session=item['token']),request)
    assert applied['calculation_session']
    return applied


def test_explicit_native_same_lineage_resolution_needs_fresh_application_and_keeps_other_answers(document,monkeypatch):
    item=document();old_answers=copy.deepcopy(item['queue']['answers']);sent=[];attachments=[]
    monkeypatch.setattr(core,'_telegram_send_intake_text',lambda *a,**k:sent.append((a,k)))
    monkeypatch.setattr(core,'_telegram_send_attachments',lambda *a,**k:attachments.append((a,k)))
    applied=native_resolution(item);candidate=applied['inputs'][qual.KEY]
    assert candidate['status']=='verified_empty'and candidate['revision']==item['record']['revision']+2
    current=core._intake_queue_load(item['queue']['id'],request=core._telegram_agent_request(CHAT))
    assert current['answers'][0]==old_answers[1]
    summary={'purchase_price_mln':73.5,'report_payload':{'inputs':applied['inputs'],'tep':applied['tep'],'result':{}}}
    with pytest.raises(core.HTTPException)as refused:
        core.telegram_result(core.TelegramResultRequest(session=item['token'],summary=summary))
    assert refused.value.status_code==409 and not sent and not attachments
    assert core.telegram_result(core.TelegramResultRequest(session=item['token'],summary=summary,
        qualification_session=applied['calculation_session']))=={'ok':True}
    url=sent[-1][1]['reply_markup']['inline_keyboard'][0][0]['web_app']['url']
    token=parse_qs(url.split('#',1)[1])['telegram_session'][0]
    signed=core._telegram_verify_session(token)
    assert 'overrides_application'not in signed and 'calc_overrides'not in signed
    assert signed['calculation_qualification']==candidate
    assert attachments[0][0][1]['inputs'][qual.KEY]==candidate


def test_valid_other_document_even_with_its_fresh_application_cannot_clear_current_unknown(document,monkeypatch):
    item=document();other=document(True);sent=[]
    monkeypatch.setattr(core,'_telegram_send_intake_text',lambda *a,**k:sent.append((a,k)))
    with pytest.raises(core.HTTPException)as refused:
        core.telegram_result(core.TelegramResultRequest(session=item['token'],qualification_session=other['token'],
            summary={'report_payload':{'inputs':other['inputs'],'tep':other['tep'],'result':{}}}))
    assert refused.value.status_code==409 and not sent


def test_review_requires_native_current_cas_and_can_only_reopen_unresolved_item(document):
    item=document();card=item['card'];request=core._telegram_agent_request(CHAT)
    req=core.AgentDocumentAnswerRequest(intake_id=card['id'],queue_revision=card['queue_revision'],
        question_token=card['question_token'],index=0,action='review',inputs=dict(core.DEFAULT_INPUTS),
        tep=item['tep'],session=item['token'])
    first=core.agent_document_answer(req,request)
    before=core._intake_queue_path(card['id']).read_bytes()
    with pytest.raises(core.HTTPException)as stale:core.agent_document_answer(req,request)
    assert stale.value.status_code==409 and core._intake_queue_path(card['id']).read_bytes()==before
    fresh=first['card'];req.queue_revision=fresh['queue_revision'];req.question_token=fresh['question_token'];req.index=1
    with pytest.raises(core.HTTPException)as unrelated:core.agent_document_answer(req,request)
    assert unrelated.value.status_code==409 and core._intake_queue_path(card['id']).read_bytes()==before


def test_shown_bot_review_button_reopens_only_its_unresolved_item_and_old_button_is_stale(document,monkeypatch):
    item=document();sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append((text,kw)))
    core._telegram_dialog_save(CHAT,{'step':'intake_ready','intake':{'id':item['queue']['id'],'region':''}})
    core._telegram_intake_ask_next(CHAT,core._telegram_dialog_get(CHAT))
    callback=next(button['callback_data']for _,opts in sent for row in (opts.get('reply_markup')or{}).get('inline_keyboard',[])
        for button in row if button.get('callback_data','').startswith('intake2_review:'))
    core._telegram_intake_callback(CHAT,callback)
    queue=core._intake_queue_load(item['queue']['id'],request=core._telegram_agent_request(CHAT))
    assert queue['index']==0 and queue['answers']==item['queue']['answers'][1:]
    before=core._intake_queue_path(queue['id']).read_bytes()
    core._telegram_intake_callback(CHAT,callback)
    assert core._intake_queue_path(queue['id']).read_bytes()==before


def test_unsaved_memory_queue_cannot_issue_a_qualification_bound_to_other_durable_contents(document):
    item=document();queue=copy.deepcopy(item['queue'])
    queue['answers'][0]['deferred']=False
    queue['answers'][0]['action']='answer';queue['answers'][0]['value']='3,25 млн'
    before=core._intake_queue_path(queue['id']).read_bytes()
    with pytest.raises(core.HTTPException)as conflict:
        core.teaser_card_view(queue,dict(core.DEFAULT_INPUTS),copy.deepcopy(item['tep']))
    assert conflict.value.status_code==409
    assert core._intake_queue_path(queue['id']).read_bytes()==before
