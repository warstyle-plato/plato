"""Display excerpts preserve full native source identity and delivery wires."""
import copy
from html.parser import HTMLParser

import pytest

from test_document_qualification import core, document, qual, CHAT
from test_document_qualification_outputs import text_pdf


class NativeMessage(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True)
        self.tags=[];self.plain=[];self.feed(text);self.close()
        assert not self.tags
        assert len(''.join(self.plain).encode('utf-16-le'))//2<=4096
    def handle_starttag(self,tag,attrs):self.tags.append(tag)
    def handle_endtag(self,tag):assert self.tags.pop()==tag
    def handle_data(self,text):self.plain.append(text)


@pytest.mark.parametrize('size',[499,500,501,10000])
def test_disclosure_excerpt_boundary_keeps_short_text_exact_and_long_text_explicitly_bounded(document,size):
    queue=copy.deepcopy(document()['queue']);text='я'*size
    queue['cards'][0]['question']=text
    item=qual.obligations(queue)[0]
    assert len(item['question'])<=500 and item['quote']==item['question']
    if size<=500:assert item['question']==text
    else:assert 'сокращено'in item['question']and 'полный текст — в карточке документа'in item['question']


def test_long_question_retains_a_short_exact_quote_and_oversize_quote_refusal(document):
    queue=copy.deepcopy(document()['queue']);queue['cards'][0]['question']='x'*1000
    queue['cards'][0]['quote']='Передача 275 м² городу'
    assert qual.obligations(queue)[0]['quote']=='Передача 275 м² городу'
    queue['cards'][0]['quote']='x'*501
    with pytest.raises(qual.QualificationError):qual.obligations(queue)


def test_excerpt_does_not_hide_a_control_byte_or_remove_total_metadata_bounds(document):
    queue=copy.deepcopy(document()['queue']);queue['cards'][0]['question']='x'*1000+'\x00'
    with pytest.raises(qual.QualificationError):qual.obligations(queue)
    queue=copy.deepcopy(document()['queue'])
    queue['cards']=[copy.deepcopy(queue['cards'][0])for _ in range(qual.MAX_ITEMS)]
    queue['answers']=[]
    for card in queue['cards']:card['question']='я'*500;card['quote']='ю'*500
    with pytest.raises(qual.QualificationError):qual.obligations(queue)


def test_native_long_question_keeps_full_chunked_question_callbacks_and_signed_source_identity(document,monkeypatch):
    item=document();queue=item['queue'];question='Передача 275 м² без денежной оценки. '+'Сверить & <границу> 😀 '*350
    queue['cards'][0]['question']=question
    core._intake_queue_save(queue);durable=core._intake_queue_path(queue['id']).read_bytes();sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append({'text':text,**kw}))
    core._telegram_dialog_save(CHAT,{'step':'intake_ready','intake':{'id':queue['id'],'region':''}})
    core._telegram_intake_ask_next(CHAT,core._telegram_dialog_get(CHAT))
    def buttons():return [button for message in sent for row in (message.get('reply_markup')or{}).get('inline_keyboard',[])for button in row]
    review=next(button['callback_data']for button in buttons()if button.get('callback_data','').startswith('intake2_review:'))
    core._telegram_intake_callback(CHAT,review)
    option=next(button['callback_data']for button in reversed(buttons())if button.get('callback_data','').startswith('intake2_opt:')and 'социальную'in button['text'])
    start=len(sent);core._telegram_intake_callback(CHAT,option)
    assert question in ''.join(''.join(NativeMessage(msg['text']).plain)for msg in sent[start:])
    defer=next(button['callback_data']for button in reversed(buttons())if button.get('text')=='Уточнить стоимость позже')
    core._telegram_intake_callback(CHAT,defer)
    for message in sent:NativeMessage(message['text'])
    current=core._intake_queue_load(queue['id'],request=core._telegram_agent_request(CHAT))
    assert current['cards'][0]['question']==question and core._telegram_dialog_get(CHAT)['step']=='intake_ready'
    card=core.teaser_card_view(current,dict(core.DEFAULT_INPUTS),copy.deepcopy(item['tep']),by_parcel=True,parcel_region='')
    record=card['calculation_qualification_record'];overrides=core.teaser_card.calc_overrides(card)
    assert record['status']=='conditional'and len(record['obligations'][0]['question'])<=500
    assert 'сокращено'in record['obligations'][0]['question']and overrides['purchase_price_mln']==73.5
    assert 'social_compensation_mln'not in overrides
    assert record['queue_sha256']==current._intake_snapshot['sha256']
    assert qual.validate(record,core._intake_qualification_key('telegram'))==record
    # A change beyond the excerpt still changes native identity/signature.
    current['cards'][0]['question']+=' Новый хвост источника.';core._intake_queue_save(current)
    newcard=core.teaser_card_view(current,dict(core.DEFAULT_INPUTS),copy.deepcopy(item['tep']),by_parcel=True,parcel_region='')
    newer=newcard['calculation_qualification_record']
    assert newer['obligations']==record['obligations']
    assert newer['queue_sha256']!=record['queue_sha256']and newer['binding']!=record['binding']and newer['signature']!=record['signature']
    assert durable!=core._intake_queue_path(queue['id']).read_bytes()


def test_full_pdf_displays_literal_source_punctuation_without_double_escaping(document):
    item=document();queue=item['queue'];quote='Передача 275 м² <проверка> & условия'
    queue['cards'][0]['quote']=quote;core._intake_queue_save(queue)
    card=core.teaser_card_view(queue,dict(core.DEFAULT_INPUTS),copy.deepcopy(item['tep']),by_parcel=True,parcel_region='')
    inputs={**item['inputs'],qual.KEY:card['calculation_qualification_record']}
    result=core._run_authoritative_model(inputs,item['tep'],[],{})['consolidated']
    rendered=text_pdf(core._build_developaid_pdf({'inputs':inputs,'tep':item['tep'],'rates':[],
        'phasing':{},'result':result,'project_name':'Synthetic punctuation qualification'}))
    assert quote in ' '.join(rendered.split())
    assert '&lt;проверка&gt;'not in rendered and '&amp; условия'not in rendered


def test_a_real_key_rotation_still_refuses_the_old_card_and_numeric_application(document,monkeypatch):
    item=document();signed=core._telegram_verify_session(item['token'])
    monkeypatch.setattr(core,'_telegram_token',lambda:'123:rotated-synthetic-key')
    assert core._telegram_intake_calc_markup(CHAT,item['card'])is None
    assert core._intake_qualification_state(item['overrides'])['status']=='review_required'
    token=core._telegram_session(CHAT,[],calc_overrides=item['overrides'],
        application_proof=signed['overrides_application'])
    assert core._telegram_verify_session(token)['chat_id']==CHAT
    admitted=core.telegram_session_data(core.TelegramSessionRequest(session=token))
    assert admitted['overrides_review_required']is True and admitted['calc_overrides']=={}
