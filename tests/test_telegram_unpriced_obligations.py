"""Classification is retained without inventing a valuation; state is shared."""
import copy
import json
import time
import threading

import pytest

import document_intake as di
import main_legacy as core
import teaser_card as tc


def unpriced():
    question={'key':'','question':'Куда отнести передачу 180 м²?',
        'quote':'Передача 180 м².', 'options':['В цену сделки','В социальную нагрузку']}
    return tc.start({'fields':[],'questions':[question],'notes':[]},
        {'text':'[стр. 1]\nПередача 180 м².','pages':1},'example.pdf',
        presets=core.PROJECT_CLASS_PRESETS,current_class='')


@pytest.mark.parametrize('action',['skip','stop'])
@pytest.mark.parametrize('choice',[0,1])
def test_unpriced_skip_or_stop_keeps_routing_and_cash_unchanged(action,choice):
    state=unpriced();inputs={'purchase_price_mln':64,'social_compensation_mln':7}
    got=tc.answer(state,inputs,{},index=0,action=action,choice=choice,
        spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
    assert got['answer']['deferred']is True
    assert got['answer']['choice']==choice
    assert got['answer']['answer']==state['cards'][0]['options'][choice]['label']
    replay=tc.replay(state,inputs,{},spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
    assert replay['inputs']==inputs and replay['refused']
    assert 'не включено' in replay['refused'][0]['reason']
    assert 'parts' not in replay['ledger']


def test_invalid_manual_area_does_not_consume_the_selected_question():
    state=unpriced();before=copy.deepcopy(state)
    got=tc.answer(state,{}, {},index=0,action='answer',choice=0,value='180 м²',
        spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
    assert got['invalid']is True and state==before


def test_dialogue_disk_is_authoritative_over_two_worker_caches(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    a,b={},{}
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',a)
    core._telegram_dialog_save(123,{'step':'await_intake_answer','intake':{'id':'synthetic'}})
    old=core._telegram_dialog_get(123)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',b)
    newer=core._telegram_dialog_get(123)
    newer['intake']['pending_choice']={'index':0,'choice':1}
    core._telegram_dialog_save(123,newer)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',a)
    assert core._telegram_dialog_get(123)['intake']['pending_choice']=={'index':0,'choice':1}
    with pytest.raises(RuntimeError):core._telegram_dialog_save(123,old)
    assert core._telegram_dialog_get(123)['intake']['pending_choice']['choice']==1


def test_stale_legacy_revision_zero_cannot_resurrect_after_cancel(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    path=core._telegram_dialog_path(123)
    path.write_text(json.dumps({'step':'await_intake_answer','intake':{'id':'legacy'},
                               'updated_at':int(time.time())}))
    stale=core._telegram_dialog_get(123)
    assert '_revision'not in stale
    core._telegram_dialog_clear(123)
    with pytest.raises(RuntimeError):core._telegram_dialog_save(123,stale)
    assert not path.exists() and core._telegram_dialog_get(123)is None


def test_failed_intake_save_does_not_claim_a_memory_only_step(monkeypatch,tmp_path):
    import agent_access
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    def failed(*a,**k):raise OSError('synthetic disk refusal')
    monkeypatch.setattr(agent_access,'write_json',failed)
    with pytest.raises(RuntimeError):
        core._telegram_dialog_save(123,{'step':'await_intake_answer','intake':{'id':'synthetic'}})
    assert not core._TELEGRAM_DIALOGS and not core._telegram_dialog_path(123).exists()


def test_first_document_generation_cannot_survive_another_worker_cancel(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    a,b={},{}
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',a)
    nonce=core._telegram_intake_begin(123,'first.pdf')
    assert core._telegram_intake_current(123,nonce)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',b)
    core._telegram_dialog_clear(123)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',a)
    assert not core._telegram_intake_current(123,nonce)
    applied,result=core._telegram_intake_commit(123,nonce,lambda _:pytest.fail('cancelled publication'))
    assert applied is False and result is None


def test_loading_deadline_is_persisted_and_interrupted_without_provider_retry(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    core._telegram_dialog_save(123,{'step':'intake_card','intake':{'id':'saved-pointer'}})
    nonce=core._telegram_intake_begin(123,'new.pdf')
    raw=json.loads(core._telegram_dialog_path(123).read_text())
    active=raw['document_read']
    assert active['deadline_at']-active['started_at']==core._TELEGRAM_INTAKE_READ_SECONDS==240
    monkeypatch.setattr(core.time,'time',lambda:active['deadline_at']+1)
    failed=core._telegram_dialog_get(123)
    assert failed['document_read']['status']=='interrupted'
    assert failed['step']=='intake_document_failed'and failed['intake']['id']=='saved-pointer'
    assert not core._telegram_intake_current(123,nonce)
    assert core._telegram_intake_commit(123,nonce,lambda _:pytest.fail('expired publication'))==(False,None)


def test_legacy_loading_without_deadline_is_interrupted_on_resume(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    core._telegram_dialog_path(123).write_text(json.dumps({'step':'intake_document_reading',
        'document_read':{'id':'a'*32,'status':'loading'},'updated_at':int(time.time())}))
    assert core._telegram_dialog_get(123)['document_read']['status']=='interrupted'


def test_outgoing_telegram_io_occurs_after_the_chat_lock_is_released(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    entered,release=threading.Event(),threading.Event()
    def api(*a,**k):
        assert core._TELEGRAM_INTAKE_LOCKED.get()is None
        entered.set();assert release.wait(3)
    monkeypatch.setattr(core,'_telegram_api',api)
    nonce=core._telegram_intake_begin(123,'new.pdf')
    def commit(dialog):
        dialog['document_read']['status']='ready'
        core._telegram_dialog_save(123,dialog)
        core._telegram_send_message(123,'Synthetic result')
    errors=[]
    def publish():
        try:core._telegram_intake_commit(123,nonce,commit)
        except BaseException as error:errors.append(error)
    worker=threading.Thread(target=publish)
    worker.start()
    cancelled=threading.Event()
    cancel=None
    try:
        assert entered.wait(3)
        def clear():
            core._telegram_dialog_clear(123);cancelled.set()
        cancel=threading.Thread(target=clear);cancel.start()
        assert cancelled.wait(1),'cancel waited for outgoing Telegram IO'
        assert not core._telegram_intake_current(123,nonce)
    finally:
        release.set();worker.join(3)
        if cancel:cancel.join(3)
    assert not worker.is_alive()and not errors


def test_source_duplicate_is_one_question_but_equal_distinct_obligations_remain_two():
    item={'key':'','question':'Как учесть инфраструктурный платёж 17 млн руб.?',
          'quote':'Инфраструктурный платёж 17 млн руб.',
          'options':['В цену сделки','В социальную нагрузку']}
    state=tc.start({'fields':[],'questions':[item,copy.deepcopy(item)],'notes':[]},
        {'text':'[стр. 1]\nИнфраструктурный платёж 17 млн руб.','pages':1},'source.pdf',
        presets=core.PROJECT_CLASS_PRESETS,current_class='')
    assert len(state['cards'])==2  # one source obligation and the class question
    assert len(state['duplicate_questions'])==1
    tc.answer(state,{}, {},index=0,action='answer',choice=1,
        spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
    assert tc.replay(state,{}, {},spp_split=core.MKD_SPP_SPLIT,
        presets=core.PROJECT_CLASS_PRESETS)['inputs']['social_compensation_mln']==17
    other={**item,'question':'Как учесть другое подключение за 17 млн руб.?',
           'quote':'Другое подключение 17 млн руб.'}
    state=tc.start({'fields':[],'questions':[item,other],'notes':[]},
        {'text':'Инфраструктурный платёж 17 млн руб. Другое подключение 17 млн руб.','pages':1},
        'source.pdf',presets=core.PROJECT_CLASS_PRESETS,current_class='')
    assert len(state['cards'])==3 and not state['duplicate_questions']


def test_calc_overrides_preserve_manual_origin_from_the_shared_card():
    card={'to_engine':[{'path':'inputs.purchase_price_mln','value':8,
                        'unit':'млн ₽','source':'manual','origin':'Explicit manual amount.'}]}
    overrides=tc.calc_overrides(card)
    assert overrides['purchase_price_mln']==8
    assert overrides['_field_origin']['inputs.purchase_price_mln']['source']=='manual'


@pytest.mark.parametrize('unsafe',[float('nan'),float('inf'),'180 м²','1e309',10**1000])
def test_unsafe_legacy_calc_card_is_refused_instead_of_becoming_zero(unsafe):
    with pytest.raises(ValueError):
        tc.calc_overrides({'to_engine':[{'path':'inputs.purchase_price_mln','value':unsafe,
                                       'unit':'млн ₽','source':'document'}]})


@pytest.mark.parametrize('unsafe',[float('nan'),270])
def test_legacy_unpriced_area_cannot_reuse_cached_cash_and_preserves_later_answers(unsafe):
    state=unpriced();state.pop('validation_schema')
    state['cards'][0]['requires_manual']=False
    state['cards'][0]['options'][0]['value']=unsafe
    state['answers']=[{'index':0,'action':'answer','choice':0,'value':'','answer':'В цену сделки'},
                      {'index':1,'action':'answer','choice':0,'value':'','answer':'Выбран класс'}]
    state['index']=len(state['cards'])
    inputs={'purchase_price_mln':64}
    card=tc.build(state,inputs,{},spp_split=core.MKD_SPP_SPLIT,
                  presets=core.PROJECT_CLASS_PRESETS,defaults=core.DEFAULT_INPUTS)
    assert not card['ready'] and state['index']==0
    assert state['legacy_review_history'] and [a['index']for a in state['answers']]==[1]
    assert card['inputs']['purchase_price_mln']==64
    assert state['cards'][0]['options'][0]['value']is None
    # Explicit fresh manual valuation completes only the reopened question.
    tc.answer(state,inputs,{},index=0,action='answer',choice=0,value='8',mode='add',
              spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
    assert state['index']==len(state['cards'])
    refreshed=tc.build(state,inputs,{},spp_split=core.MKD_SPP_SPLIT,
        presets=core.PROJECT_CLASS_PRESETS,defaults=core.DEFAULT_INPUTS)
    assert refreshed['ready']and refreshed['inputs']['purchase_price_mln']==72
    json.dumps(refreshed,allow_nan=False)


def test_legacy_nonfinite_field_is_reopened_with_clear_review_and_no_invalid_json():
    state={'filename':'saved.pdf','fields':[{'key':'purchase_price_mln','value':float('nan'),
        'unit':'млн ₽','quote':'Цена 64 млн руб.','checked':True}],
        'cards':[],'answers':[],'index':0}
    card=tc.build(state,{}, {},spp_split=core.MKD_SPP_SPLIT,
        presets=core.PROJECT_CLASS_PRESETS,defaults=core.DEFAULT_INPUTS)
    assert not card['ready']and state['cards'][0]['requires_manual']
    assert state['fields'][0]['checked']is False and state['legacy_review_history']
    json.dumps(card,allow_nan=False)
