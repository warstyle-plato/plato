"""Fault-injected queue conflicts preserve proposals, never replay an answer."""
import copy

import pytest
from fastapi import HTTPException
import main_legacy as core
import teaser_card as tc


@pytest.fixture
def shown(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic-test-key')
    sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append((text,kw)))
    # This fixture injects only the accepted native API boundary, not its CAS
    # implementation. Real storage/race predicates have their own native tests.
    monkeypatch.setattr(core,'_intake_question_token',lambda queue:'a'*64,raising=False)
    monkeypatch.setattr(core,'_intake_queue_expect',lambda *a:None,raising=False)
    request=core._telegram_agent_request(17)
    extraction={'fields':[],'questions':[{'key':'','question':'Передача 80 м²: куда отнести?',
        'quote':'Передача 80 м².', 'options':['В цену сделки','В социальную нагрузку']}],'notes':[]}
    first=core._intake_queue_start('synthetic.pdf',extraction,{'text':'Передача 80 м².','pages':1},
        dict(core.DEFAULT_INPUTS),copy.deepcopy(core.TEP_DEFAULT),actor=request.scope['plato_actor'])
    dialog={'step':'await_intake_answer','intake':{'id':first['id']}}
    core._telegram_dialog_save(17,dialog)
    core._telegram_intake_ask_next(17,dialog)
    return first['id'],request,sent


def saved(shown):
    return core._intake_queue_load(shown[0],request=shown[1])


def test_precondition_conflict_keeps_unapplied_value_and_refreshes_question(monkeypatch,shown):
    before=copy.deepcopy(saved(shown))
    def conflict(*a):raise HTTPException(409,'synthetic conflict')
    monkeypatch.setattr(core,'_intake_queue_expect',conflict)
    core._telegram_intake_answer(17,core._telegram_dialog_get(17),index=0,
        action='answer',choice=0,value='2,5',mode='replace')
    assert saved(shown)==before
    dialog=core._telegram_dialog_get(17)
    proposal=dialog['intake']['unapplied_answer']
    assert proposal['value']=='2,5'and proposal['status']=='not_applied_queue_changed'
    assert 'pending_choice'not in dialog['intake']
    assert any('не применён'in text for text,_ in shown[2])


def test_save_conflict_does_not_publish_mutated_memory_or_resubmit(monkeypatch,shown):
    before=copy.deepcopy(saved(shown));calls=[]
    def conflict(queue):calls.append(copy.deepcopy(queue));raise HTTPException(409,'synthetic conflict')
    monkeypatch.setattr(core,'_intake_queue_save',conflict)
    core._telegram_intake_answer(17,core._telegram_dialog_get(17),index=0,
        action='answer',choice=1,value='2,5',mode='replace')
    assert len(calls)==1 and calls[0]['answers']
    assert saved(shown)==before
    assert core._telegram_dialog_get(17)['intake']['unapplied_answer']['value']=='2,5'


def test_competing_committed_answer_is_preserved_after_refresh(monkeypatch,shown):
    original_save=core._intake_queue_save;calls=[]
    def lost_race(queue):
        calls.append(1)
        competing=saved(shown)
        tc.answer(competing,dict(core.DEFAULT_INPUTS),copy.deepcopy(core.TEP_DEFAULT),
            index=0,action='stop',spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
        original_save(competing)
        raise HTTPException(409,'synthetic competing commit')
    monkeypatch.setattr(core,'_intake_queue_save',lost_race)
    core._telegram_intake_answer(17,core._telegram_dialog_get(17),index=0,
        action='answer',choice=0,value='2,5',mode='replace')
    current=saved(shown)
    assert calls==[1]and len(current['answers'])==1
    assert current['answers'][0]['action']=='stop'
    assert current['answers'][0]['value']==''
    assert core._telegram_dialog_get(17)['intake']['unapplied_answer']['value']=='2,5'


def test_access_denial_is_not_reclassified_as_a_revision_conflict(monkeypatch,shown):
    def denied(*a):raise HTTPException(403,'synthetic denied')
    monkeypatch.setattr(core,'_intake_queue_expect',denied)
    with pytest.raises(HTTPException)as error:
        core._telegram_intake_answer(17,core._telegram_dialog_get(17),index=0,
            action='answer',choice=0,value='2,5',mode='replace')
    assert error.value.status_code==403
    assert 'unapplied_answer'not in core._telegram_dialog_get(17)['intake']


def test_stale_display_token_refreshes_without_selecting_a_route(shown):
    before=copy.deepcopy(saved(shown))
    data=core._telegram_intake_callback_data(shown[0],'opt',0,0,'b'*8)
    core._telegram_intake_callback(17,data)
    assert saved(shown)==before
    assert 'pending_choice'not in core._telegram_dialog_get(17)['intake']
    assert any('не применён'in text for text,_ in shown[2])


def test_route_and_defer_buttons_remain_bounded_and_source_bound(shown):
    data=core._telegram_intake_callback_data(shown[0],'opt',0,1,'a'*8)
    core._telegram_intake_callback(17,data)
    pending=core._telegram_dialog_get(17)['intake']['pending_choice']
    assert pending['question_token']=='a'*64 and pending['queue_revision']==0
    buttons=[button for _,kw in shown[2]for row in (kw.get('reply_markup')or{}).get('inline_keyboard',[])for button in row]
    assert buttons and all(len(button['callback_data'].encode())<=64 for button in buttons if 'callback_data'in button)
    defer=next(button['callback_data']for button in buttons if button.get('callback_data','').startswith('intake2_defer:'))
    core._telegram_intake_callback(17,defer)
    current=saved(shown)
    assert current['answers'][0]['deferred']is True and current['answers'][0]['choice']==1
    replay=tc.replay(current,{'purchase_price_mln':64,'social_compensation_mln':7},{},
        spp_split=core.MKD_SPP_SPLIT,presets=core.PROJECT_CLASS_PRESETS)
    assert replay['inputs']['purchase_price_mln']==64
    assert replay['inputs']['social_compensation_mln']==7
    assert replay['refused']


def test_second_snapshot_is_rechecked_before_route_selection(monkeypatch,shown):
    checks=[]
    def changed_after_first_read(*a):
        checks.append(1)
        if len(checks)==2:raise HTTPException(409,'synthetic second-snapshot change')
    monkeypatch.setattr(core,'_intake_queue_expect',changed_after_first_read)
    core._telegram_intake_callback(17,core._telegram_intake_callback_data(shown[0],'opt',0,0,'a'*8))
    assert len(checks)==2
    assert not saved(shown)['answers']
    assert 'pending_choice'not in core._telegram_dialog_get(17)['intake']
    assert core._telegram_dialog_get(17)['intake']['unapplied_answer']['status']=='not_applied_queue_changed'


def test_persisted_loading_does_not_claim_a_reader_is_active(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path)
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append(text))
    core._telegram_intake_begin(17,'synthetic.pdf')
    core._TELEGRAM_DIALOGS.clear()  # A new worker has only persisted state.
    assert core._telegram_handle_dialog_text(17,'→')is True
    core._telegram_intake_callback(17,core._telegram_intake_callback_data('a'*32,'questions'))
    assert len(sent)==2
    assert all('читается'not in text.lower()for text in sent)
    assert 'не завершён'in sent[0]and 'не получен'in sent[1]
