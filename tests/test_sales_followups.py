"""Owner text is a fixture. Bank data and delivery callbacks are synthetic."""
import datetime as dt
import multiprocessing
import pytest
from market_search import sales_dialogue as dialogue, sales_followups as follow, sales_questions as questions, sales_store as store

STAMP=int(dt.datetime(2026,11,23,18,tzinfo=follow.MOSCOW).timestamp())
DUE=dt.datetime(2026,11,27,9,tzinfo=follow.MOSCOW)
OWNER_TEXT=('Добрый вечер Платон Сергеевич!\n1. кв96 сделка не зарегистрировалась, ожидаем 26.11\n'
            '2. Мм0009/мг переподписание ДДУ\n3. Мм0010/мг переподписание ДДУ')


def setup(where,scope=None):
    scope=scope or dict(chat_id=-10012345,monitor_project='Монитор',sales_project='Продажи',grant_sha256='grant1',link_sha256='link1')
    rows=[dict(contract=name,signed='2026-11-16',product=product,unit=unit,amount=amount,area=100,escrow_paid=0)
          for name,product,unit,amount in [('ДДУ-96','Квартира','корп.3 кв.96',100_000_000),
            ('Мм0009/мг','Машиноместо','',10_000_000),('Мм0010/мг','Машиноместо','',9_000_000)]]
    source={'rows':rows};store.save(where,'Продажи',{'contracting':source},'SYNTHETIC.xlsx')
    items=questions._no_money(rows,dt.date(2026,11,23))
    for item in items:item['baseline']['source_sha256']=follow.digest(source)
    bid=dialogue.prepare(where,'Продажи',scope['chat_id'],items,'2026-11-23')
    dialogue.delivered(where,'Продажи',scope['chat_id'],bid,100)
    return scope,rows,bid,dialogue.load(where,'Продажи')['batches'][bid]


def answer(where,scope,batch,text=OWNER_TEXT,mid=101,candidate=False):
    return follow.ingest(where,'Продажи',scope,message_id=mid,reply_to_id=100,quoted=batch['text'],
        text=text,author_id=4242,author='Менеджер',telegram_date=STAMP,candidate=candidate)


def test_owner_points_and_safe_ordinary_candidate(tmp_path):
    scope,rows,bid,batch=setup(tmp_path);before=store.load(tmp_path,'Продажи')
    assert answer(tmp_path,scope,batch,candidate=True)['candidate']
    assert not follow.load(tmp_path,'Продажи')['events']
    answer(tmp_path,scope,batch,candidate=True,mid=102)
    notices=list(follow.load(tmp_path,'Продажи')['deliveries'].values())
    assert len(notices)==1 and 'не связа' in notices[0]['text'] and 'https://t.me/c/12345/100' in notices[0]['text']
    assert answer(tmp_path,scope,batch,mid=103)['events']==3
    events=list(follow.load(tmp_path,'Продажи')['events'].values())
    assert events[0]['event_kind']=='registration' and events[0]['event_date']=='2026-11-26'
    assert events[0]['due_at']==DUE.isoformat() and events[0]['baseline_quality']=='reported_unverified'
    assert [e['state'] for e in events]==['scheduled','waiting_deadline','waiting_deadline']
    assert all(e['due_at'] is None for e in events[1:])
    assert events[0]['provenance']['author_id']==4242 and 'не зарегистрировалась' in events[0]['quote']
    assert store.load(tmp_path,'Продажи')==before and answer(tmp_path,scope,batch,mid=103)['events']==0


@pytest.mark.parametrize('text,kind,date',[
    ('26.11.2026','registration','2026-11-26'),('до 26.11','payment','2026-11-26'),
    ('завтра','payment','2026-11-24'),('послезавтра','resigning','2026-11-25'),
    ('оплату ждём 26.11.2026','','2026-11-26'),('26.11 и 27.11','payment',None),
    ('если зарегистрируют 26.11','registration',None),('до 02.01','payment',None),
    ('до 21.11','payment',None),('на неделе','payment',None),('26.11.25','payment',None),
    ('2026-11-26','registration','2026-11-26'),('Ожидаем оплату 26.11 млн ₽','payment',None),
    ('Оплата по договору №26.11','payment',None),('26.11%','payment',None),('26.11 м²','payment',None),
    ('Договор №2026-11-26','payment',None),('ID A2026-11-26B','payment',None),
    ('26.11.2026.','payment','2026-11-26')])
def test_dates(text,kind,date):assert follow.extract(text,STAMP,kind)['event_date']==date


def test_bare_date_inherits_only_exact_previous_event(tmp_path):
    scope,_,_,batch=setup(tmp_path);answer(tmp_path,scope,batch)
    data=follow.load(tmp_path,'Продажи');mm=list(data['events'].values())[1]
    delivery=next(x for x in data['deliveries'].values() if x['question']['key']==mm['question_key'])
    claim=next(x for x in follow.poll(tmp_path,'Продажи',scope,DUE) if x['id']==delivery['id'])
    permitted=follow.begin(tmp_path,'Продажи',scope,claim['id'],claim['claim_id'],DUE)
    follow.receipt(tmp_path,'Продажи',scope,claim['id'],permitted['attempt_id'],200)
    b=dialogue.load(tmp_path,'Продажи')['batches'][delivery['batch_id']]
    follow.ingest(tmp_path,'Продажи',scope,message_id=201,reply_to_id=200,quoted=b['text'],text='26.11.2026',author_id=4242,author='Менеджер',telegram_date=STAMP)
    e=follow.load(tmp_path,'Продажи')['events'][mm['key']]
    assert e['revision']==2 and e['event_kind']=='resigning' and e['due_at']==DUE.isoformat()


def test_done_claims_and_nonmoney_explanation(tmp_path):
    scope,_,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. оплатили\n2. зарегистрировали\n3. не оплатили')
    events=list(follow.load(tmp_path,'Продажи')['events'].values())
    assert [e['state'] for e in events]==['scheduled','scheduled','waiting_deadline']
    assert all(e.get('event_mode')=='reported_completion' and e.get('claim')=='unverified' for e in events[:2])
    item={'key':'price:unit','kind':'price','text':'Почему скидка?'}
    bid=dialogue.prepare(tmp_path,'Продажи',scope['chat_id'],[item],'2026-11-23');dialogue.delivered(tmp_path,'Продажи',scope['chat_id'],bid,300)
    q=dialogue.load(tmp_path,'Продажи')['batches'][bid]['text']
    follow.ingest(tmp_path,'Продажи',scope,message_id=301,reply_to_id=300,quoted=q,text='Скидка из-за отделки',author_id=1,author='Тест',telegram_date=STAMP)
    assert follow.load(tmp_path,'Продажи')['events'][follow._event_id(scope,item['key'])]['state']=='answered'


def event_data(where,paid=0,baseline=0,known=True):
    scope,rows,_,batch=setup(where);initial_sha=follow.digest({'rows':rows});target=follow.identity(rows[0])
    raw=dialogue.load(where,'Продажи');next(iter(raw['batches'].values()))['questions'][0]['baseline']['escrow_paid']=baseline
    dialogue._save(where,'Продажи',raw);answer(where,scope,batch)
    event=next(iter(follow.load(where,'Продажи')['events'].values()))
    rows[0]['escrow_paid']=paid;current={'rows':rows}
    att=dict(source_sha256=follow.digest(current),target=target,as_of='2026-11-27',observed=True,complete_scope=True)
    initial=dict(source_sha256=initial_sha,target=target,as_of='2026-11-23',observed=known,complete_scope=True)
    return scope,event,current,att,initial


@pytest.mark.parametrize('paid,baseline,known,state,delta',[
    (500_000,500_000,True,'unchanged',0),(600_000,500_000,True,'partial',100_000),
    (400_000,500_000,True,'decreased',-100_000),(100_000_000,100_000_000,True,'full',0),
    (500_000,0,False,'partial_current',None),(100_000_000,None,False,'full',None)])
def test_observed_baseline(tmp_path,paid,baseline,known,state,delta):
    _,e,c,a,i=event_data(tmp_path,paid,baseline,known);r=follow.evaluate(e,c,follow.digest(c),a,DUE,i)
    assert r['state']==state and r['delta']==delta and r['baseline_quality']==('observed' if known else 'reported_unverified')


@pytest.mark.parametrize('change',['missing','stale','future','partial','unobserved','fingerprint','conflict','negative','nonfinite'])
def test_unknown_never_means_no_money(tmp_path,change):
    _,e,c,a,i=event_data(tmp_path);sha=follow.digest(c)
    if change=='missing':c=None
    elif change=='stale':a['as_of']='2026-11-26'
    elif change=='future':a['as_of']='2026-11-28'
    elif change=='partial':a['complete_scope']=False
    elif change=='unobserved':a['observed']=False
    elif change=='fingerprint':a['source_sha256']='old'
    elif change=='conflict':c['rows'].append(dict(c['rows'][0],escrow_paid=1))
    elif change=='negative':c['rows'][0]['escrow_paid']=-1
    else:c['rows'][0]['escrow_paid']=float('nan')
    assert follow.evaluate(e,c,sha,a,DUE,i)['state']=='unknown'


def _worker(where,scope,queue):queue.put(follow.poll(where,'Продажи',scope,DUE))


def test_multiworker_lost_ack_and_receipt_retry(tmp_path):
    scope,_,_,b=setup(tmp_path);answer(tmp_path,scope,b,text='1. ожидаем оплату 26.11')
    ctx=multiprocessing.get_context('fork');queue=ctx.Queue();workers=[ctx.Process(target=_worker,args=(tmp_path,scope,queue)) for _ in range(2)]
    for p in workers:p.start()
    results=[queue.get(timeout=10) for _ in workers]
    for p in workers:p.join(10);assert p.exitcode==0
    assert sum(map(len,results))==1
    c=next(x for r in results for x in r);s=follow.begin(tmp_path,'Продажи',scope,c['id'],c['claim_id'],DUE)
    assert s['authorized'] and not follow.begin(tmp_path,'Продажи',scope,c['id'],c['claim_id'],DUE)['authorized']
    assert follow.poll(tmp_path,'Продажи',scope,DUE+dt.timedelta(seconds=200))==[]
    assert follow.receipt(tmp_path,'Продажи',scope,c['id'],s['attempt_id'],900)
    assert follow.receipt(tmp_path,'Продажи',scope,c['id'],s['attempt_id'],900)


@pytest.fixture
def native(monkeypatch,tmp_path):
    import main
    import developaid_management_report as management
    import developaid_monitor as monitor
    import site_chat_access
    core=main.core
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','SYNTHETIC-OWNER-ONLY')
    monkeypatch.setattr(core,'_PROJECTS_DIR',tmp_path/'projects')
    monkeypatch.setattr(core,'_USAGE_DIR',tmp_path/'usage')
    monkeypatch.setattr(core,'_telegram_token',lambda:'123:synthetic')
    monkeypatch.setattr(core,'_telegram_webhook_enabled',lambda:True)
    monkeypatch.setattr(core,'_core_api_url',lambda path:'')
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    monkeypatch.setattr(core,'_telegram_group_seen',lambda *a,**kw:None)
    where=store.default_dir();setup(where);monitor._project_dir('Монитор')
    management.link_sales('Монитор','Продажи','synthetic',where)
    site_chat_access.authorize(core._site_chat_grants_path(),'SYNTHETIC-OWNER-ONLY',-10012345,'Монитор')
    with core._site_chat_access(-10012345,'sales:send','Монитор'):
        scope=core._sales_followup_scope('Монитор',-10012345)
    sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append((chat,text)) or {'message_id':900+len(sent)})
    return main,core,where,scope,sent


def test_native_http_reply_poll_and_no_real_messages(native,monkeypatch):
    from fastapi.testclient import TestClient
    main,core,where,scope,sent=native
    batch=next(iter(dialogue.load(where,'Продажи')['batches'].values()))
    msg={'chat':{'id':scope['chat_id'],'type':'supergroup'},'from':{'id':4242,'first_name':'Менеджер'},
         'message_id':101,'date':STAMP,'text':OWNER_TEXT,
         'reply_to_message':{'message_id':100,'text':batch['text'],'from':{'id':123,'is_bot':True}}}
    core._telegram_group_message(msg['chat'],msg)
    assert len(follow.load(where,'Продажи')['events'])==3
    api=TestClient(core.app)
    args={'chat_id':scope['chat_id'],'project':'Монитор'}
    denied=api.post('/monitor/sales-followups',json=args)
    assert denied.status_code==403 and denied.headers['cache-control']=='private, no-store'
    assert api.post('/internal/monitor/sales-followups',json={'action':'poll','sign':'bad'}).status_code==403
    result=api.post('/monitor/sales-followups',json=dict(args,key='SYNTHETIC-OWNER-ONLY'))
    assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
    assert len(result.json()['state']['events'])==3
    monkeypatch.setattr(follow,'_now',lambda value=None:DUE if value is None else value.astimezone(follow.MOSCOW))
    assert main._deliver_sales_followups()['items']
    assert len(sent)==3
    main._deliver_sales_followups();assert len(sent)==3


def test_nonce_and_cancel_stop_old_intents(native):
    import site_chat_access
    import developaid_management_report as management
    main,core,where,scope,sent=native
    batch=next(iter(dialogue.load(where,'Продажи')['batches'].values()));answer(where,scope,batch)
    site_chat_access.revoke(core._site_chat_grants_path(),scope['chat_id'],'Монитор')
    site_chat_access.authorize(core._site_chat_grants_path(),'SYNTHETIC-OWNER-ONLY',scope['chat_id'],'Монитор')
    management.link_sales('Монитор','Продажи','synthetic',where)
    with core._site_chat_access(scope['chat_id'],'sales:send','Монитор'):
        current=core._sales_followup_scope('Монитор',scope['chat_id'])
    assert current['grant_sha256']!=scope['grant_sha256'] and current['link_sha256']!=scope['link_sha256']
    assert follow.poll(where,'Продажи',current,DUE)==[]
    assert all(e['state']=='cancelled' for e in follow.load(where,'Продажи')['events'].values())
    assert not sent


def test_native_source_metadata_avoids_mandatory_admin_attestation(tmp_path):
    scope,e,c,a,i=event_data(tmp_path,paid=500_000,known=False)
    c.update(as_of='2026-11-27',as_of_provenance='uploader_declared')
    c['rows'][0]['escrow_observed']=True
    sha=follow.digest(c)
    native=follow.native_attestation(c,sha,e['target'])
    assert follow.evaluate(e,c,sha,native,DUE)['state']=='partial_current'
    c['rows'][0]['escrow_observed']=False
    assert follow.native_attestation(c,follow.digest(c),e['target'])=={}


def test_waiting_data_once_then_full_notification_is_not_a_question(tmp_path):
    scope,rows,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. ожидаем оплату 26.11')
    assert follow.poll(tmp_path,'Продажи',scope,DUE-dt.timedelta(seconds=1))==[]
    follow.poll(tmp_path,'Продажи',scope,DUE);follow.poll(tmp_path,'Продажи',scope,DUE+dt.timedelta(seconds=10))
    assert len([k for k in follow.load(tmp_path,'Продажи')['deliveries'] if k.startswith('unknown:')])==1
    rows[0].update(escrow_paid=100_000_000,escrow_observed=True)
    source={'rows':rows,'as_of':'2026-11-27','as_of_provenance':'uploader_declared'}
    store.save(tmp_path,'Продажи',{'contracting':source},'SYNTHETIC-FUTURE.xlsx')
    follow.poll(tmp_path,'Продажи',scope,DUE)
    data=follow.load(tmp_path,'Продажи')
    assert next(iter(data['events'].values()))['state']=='resolved'
    final=next(v for k,v in data['deliveries'].items() if k.startswith('result:'))
    assert not final['question'] and not final['batch_id']


def test_legacy_key_restores_identity_without_inventing_old_balance(tmp_path):
    scope,rows,bid,batch=setup(tmp_path)
    raw=dialogue.load(tmp_path,'Продажи')
    raw['batches'][bid]['questions']=[{k:q[k] for k in ('key','kind','text')} for q in batch['questions']]
    dialogue._save(tmp_path,'Продажи',raw)
    batch=raw['batches'][bid]
    assert answer(tmp_path,scope,batch,candidate=True)['candidate']
    answer(tmp_path,scope,batch,mid=102)
    event=next(iter(follow.load(tmp_path,'Продажи')['events'].values()))
    assert event['state']=='scheduled' and event['baseline_paid'] is None
    assert event['question']['subject_provenance']=='current_source_exact_question_key'
    assert 'subject' not in dialogue.load(tmp_path,'Продажи')['batches'][bid]['questions'][0]


def test_conflicted_legacy_identity_waits_for_clarification(tmp_path):
    scope,rows,bid,batch=setup(tmp_path)
    raw=dialogue.load(tmp_path,'Продажи');raw['batches'][bid]['questions']=[{k:q[k] for k in ('key','kind','text')} for q in batch['questions']]
    dialogue._save(tmp_path,'Продажи',raw);batch=raw['batches'][bid]
    rows.append(dict(rows[0],escrow_paid=100))
    store.save(tmp_path,'Продажи',{'contracting':{'rows':rows}},'SYNTHETIC-CONFLICT.xlsx')
    answer(tmp_path,scope,batch)
    event=next(iter(follow.load(tmp_path,'Продажи')['events'].values()))
    assert event['state']=='waiting_identity' and event['due_at']==DUE.isoformat()


def test_partial_keeps_payment_issue_open_and_baseline_unknown_is_not_inflow(tmp_path):
    scope,rows,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. ожидаем оплату 26.11')
    rows[0].update(escrow_paid=500_000,escrow_observed=True)
    store.save(tmp_path,'Продажи',{'contracting':{'rows':rows,'as_of':'2026-11-27','as_of_provenance':'uploader_declared'}},'SYNTHETIC.xlsx')
    follow.poll(tmp_path,'Продажи',scope,DUE)
    data=follow.load(tmp_path,'Продажи');event=next(iter(data['events'].values()))
    assert event['state']=='awaiting_remainder_date' and event['check_state']=='completed'
    assert event['evaluation']['delta'] is None
    text=next(v['text'] for k,v in data['deliveries'].items() if k.startswith('result:'))
    assert 'прирост не рассчитан' in text and 'срок оплаты остатка' in text and 'Поступление частичное' not in text


def test_superseded_deadline_prompt_is_cancelled_and_claim_lease_can_retry(tmp_path):
    scope,_,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. переподписание ДДУ')
    claimed=follow.poll(tmp_path,'Продажи',scope,DUE)[0]
    retried=follow.poll(tmp_path,'Продажи',scope,DUE+dt.timedelta(seconds=91))[0]
    assert retried['claim_id']!=claimed['claim_id']
    assert not follow.begin(tmp_path,'Продажи',scope,claimed['id'],claimed['claim_id'],DUE+dt.timedelta(seconds=91))['authorized']
    answer(tmp_path,scope,batch,text='1. переподпишем 28.11',mid=102)
    assert not follow.begin(tmp_path,'Продажи',scope,retried['id'],retried['claim_id'],DUE+dt.timedelta(seconds=91))['authorized']


def test_booking_registration_timeline_without_contract_is_not_closed(tmp_path):
    scope,_,_,_=setup(tmp_path)
    item={'key':'dropped:96','kind':'dropped','text':'Бронь снята или договор оформляется?'}
    bid=dialogue.prepare(tmp_path,'Продажи',scope['chat_id'],[item],'2026-11-23');dialogue.delivered(tmp_path,'Продажи',scope['chat_id'],bid,400)
    q=dialogue.load(tmp_path,'Продажи')['batches'][bid]['text']
    follow.ingest(tmp_path,'Продажи',scope,message_id=401,reply_to_id=400,quoted=q,text='Подаём на регистрацию 26.11',author_id=1,author='Тест',telegram_date=STAMP)
    e=follow.load(tmp_path,'Продажи')['events'][follow._event_id(scope,item['key'])]
    assert e['state']=='waiting_identity' and e['event_date']=='2026-11-26'


def test_corrupt_scope_does_not_block_other_groups(tmp_path):
    scope,_,_,batch=setup(tmp_path);answer(tmp_path,scope,batch)
    path=follow._path(tmp_path,'Повреждённый');path.write_text('{broken')
    scopes,errors=follow.scopes(tmp_path)
    assert scopes and len(errors)==1 and 'Повреждённый' not in str(errors)
    assert follow.poll(tmp_path,'Продажи',scope,DUE)


def test_native_security_and_cancel_between_claim_and_send(native,monkeypatch):
    from fastapi.testclient import TestClient
    main,core,where,scope,sent=native
    batch=next(iter(dialogue.load(where,'Продажи')['batches'].values()));answer(where,scope,batch,text='1. ожидаем оплату 26.11')
    monkeypatch.setattr(follow,'_now',lambda value=None:DUE if value is None else value.astimezone(follow.MOSCOW))
    api=TestClient(core.app)
    sign=core._web_login_sign('sales-followups',0)
    assert api.post('/internal/monitor/sales-followups',json={'action':'attest','sign':sign,'chat_id':scope['chat_id'],'project':'Монитор','sales_project':'Продажи'}).status_code==400
    pending=api.post('/internal/monitor/sales-followups',json={'action':'poll','sign':sign}).json()['items'][0]
    args=dict(chat_id=scope['chat_id'],project='Монитор',sales_project='Продажи')
    assert api.post('/monitor/sales-followups',json=dict(args,key='SYNTHETIC-OWNER-ONLY',action='attest',details={'observed':True})).status_code==409
    assert api.post('/monitor/sales-followups',json=dict(args,key='SYNTHETIC-OWNER-ONLY',action='cancel')).status_code==200
    begin=api.post('/internal/monitor/sales-followups',json=dict(args,sign=sign,action='begin',delivery_id=pending['id'],claim_id=pending['claim_id']))
    assert begin.status_code==200 and begin.json()['authorized'] is False and not sent


@pytest.mark.parametrize('sender',[{'id':124,'is_bot':True},{'id':123,'is_bot':False}])
def test_foreign_bot_or_forged_question_does_not_create_even_candidate(native,sender):
    main,core,where,scope,sent=native
    batch=next(iter(dialogue.load(where,'Продажи')['batches'].values()))
    msg={'chat':{'id':scope['chat_id'],'type':'supergroup'},'from':{'id':4242},'message_id':101,
         'date':STAMP,'text':OWNER_TEXT,'reply_to_message':{'message_id':100,'text':batch['text'],'from':sender}}
    core._telegram_group_message(msg['chat'],msg)
    assert not follow.load(where,'Продажи')['events'] and not follow.load(where,'Продажи')['deliveries'] and not sent


def test_reported_completion_schedules_now_and_waits_for_source_not_a_new_deadline(tmp_path):
    scope,rows,_,batch=setup(tmp_path)
    answer(tmp_path,scope,batch,text='1. оплатили\n2. зарегистрировали')
    event=next(iter(follow.load(tmp_path,'Продажи')['events'].values()))
    assert dt.datetime.fromisoformat(event['due_at']).timestamp()==STAMP
    assert not any(k.startswith('deadline:') for k in follow.load(tmp_path,'Продажи')['deliveries'])
    follow.poll(tmp_path,'Продажи',scope,dt.datetime.fromtimestamp(STAMP,follow.MOSCOW))
    assert event['claim']=='unverified'
    assert next(iter(follow.load(tmp_path,'Продажи')['events'].values()))['state']=='waiting_data'


def test_source_baseline_presence_evidence_allows_delta_without_manual_attest(tmp_path):
    scope,rows,bid,batch=setup(tmp_path)
    q=batch['questions'][0]
    raw=dialogue.load(tmp_path,'Продажи')
    raw['batches'][bid]['questions'][0]['baseline'].update(observed=True,as_of='2026-11-23',as_of_provenance='uploader_declared')
    dialogue._save(tmp_path,'Продажи',raw);answer(tmp_path,scope,batch,text='1. ожидаем оплату 26.11')
    rows[0].update(escrow_paid=600_000,escrow_observed=True)
    current={'rows':rows,'as_of':'2026-11-27','as_of_provenance':'uploader_declared'}
    store.save(tmp_path,'Продажи',{'contracting':current},'SYNTHETIC-FUTURE.xlsx')
    follow.poll(tmp_path,'Продажи',scope,DUE)
    data=follow.load(tmp_path,'Продажи');e=next(iter(data['events'].values()))
    assert e['evaluation']['delta']==600_000 and e['evaluation']['baseline_quality']=='observed'
    text=next(v['text'] for k,v in data['deliveries'].items() if k.startswith('result:'))
    assert '600 000,00 ₽' in text and '100 000 000,00 ₽' in text


@pytest.mark.parametrize('old_paid,new_paid',[(100_000_000,0),(0,100_000_000)])
def test_changed_source_between_poll_and_begin_invalidates_old_disclosure(tmp_path,old_paid,new_paid):
    scope,rows,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. ожидаем оплату 26.11')
    rows[0].update(escrow_paid=old_paid,escrow_observed=True)
    payload={'rows':rows,'as_of':'2026-11-27','as_of_provenance':'uploader_declared'}
    store.save(tmp_path,'Продажи',{'contracting':payload},'SYNTHETIC-A.xlsx')
    old=follow.poll(tmp_path,'Продажи',scope,DUE)[0]
    rows[0]['escrow_paid']=new_paid
    store.save(tmp_path,'Продажи',{'contracting':payload},'SYNTHETIC-B.xlsx')
    assert not follow.begin(tmp_path,'Продажи',scope,old['id'],old['claim_id'],DUE)['authorized']
    current=follow.poll(tmp_path,'Продажи',scope,DUE)[0]
    begin=follow.begin(tmp_path,'Продажи',scope,current['id'],current['claim_id'],DUE)
    assert begin['authorized'] and follow._money(new_paid) in begin['text']


def test_attestation_change_before_begin_invalidates_old_source_quality_claim(tmp_path):
    scope,rows,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. ожидаем оплату 26.11')
    contracts,sha=follow.source(tmp_path,'Продажи');target=follow.identity(rows[0])
    declaration=dict(source_sha256=sha,target=target,as_of='2026-11-27',observed=True,complete_scope=True)
    follow.attest(tmp_path,'Продажи',declaration,DUE)
    old=follow.poll(tmp_path,'Продажи',scope,DUE)[0]
    follow.attest(tmp_path,'Продажи',dict(declaration,as_of='2026-11-26'),DUE)
    assert not follow.begin(tmp_path,'Продажи',scope,old['id'],old['claim_id'],DUE)['authorized']
    claims=follow.poll(tmp_path,'Продажи',scope,DUE)
    assert len(claims)==1 and claims[0]['id'].startswith('unknown:')


def test_nonfinite_reported_baseline_does_not_block_future_current_verification(tmp_path):
    _,e,c,a,_=event_data(tmp_path,paid=100_000_000,baseline=float('nan'),known=False)
    assert e['state']=='scheduled' and e['baseline_paid'] is None
    assert follow.evaluate(e,c,follow.digest(c),a,DUE)['state']=='full'


def test_native_xlsx_upload_to_reply_to_auto_poll_needs_no_manual_attestation(native,monkeypatch):
    import io
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from openpyxl import Workbook
    from market_search import api,contracting
    main,core,where,scope,sent=native
    batch=next(iter(dialogue.load(where,'Продажи')['batches'].values()))
    answer(where,scope,batch,text='1. оплатили')
    book=Workbook();sheet=book.active;sheet.title='Контрактация'
    sheet['A3']='Название проекта:';sheet['E3']='Продажи'
    values=dict(product='Квартира',unit='корп.3 кв.96',date='16.11.2026',contract='ДДУ-96',
                area=100,amount=100_000_000,units=1,price_per_sqm=1_000_000,escrow_total=100_000_000,
                payment_variant='100% оплата')
    for column,(key,title) in enumerate(contracting._COLUMNS.items(),1):
        sheet.cell(6,column,title);sheet.cell(7,column,values.get(key))
    data=io.BytesIO();book.save(data);book.close()
    monkeypatch.setenv('MARKET_CABINET_KEY','SYNTHETIC-CABINET')
    app=FastAPI();api.install(app);client=TestClient(app)
    response=client.post('/cabinet/contracting',params={'project':'Продажи','escrow_as_of':'2026-11-23'},
                        headers={'X-Market-Key':'SYNTHETIC-CABINET'},content=data.getvalue())
    assert response.status_code==200,response.text
    current=store.load(where,'Продажи')['sources']['contracting']['data']
    assert current['as_of_provenance']=='uploader_declared' and current['rows'][0]['escrow_observed']
    now=dt.datetime.fromtimestamp(STAMP,follow.MOSCOW)+dt.timedelta(minutes=1)
    monkeypatch.setattr(follow,'_now',lambda value=None:now if value is None else value.astimezone(follow.MOSCOW))
    # This fixture checks completion reported on23, so the source cut23 is sufficient.
    main._deliver_sales_followups()
    state=follow.load(where,'Продажи');event=next(iter(state['events'].values()))
    assert event['state']=='resolved' and not state['attestations']
    assert len(sent)==1 and '100 000 000,00 ₽' in sent[0][1]


def test_write_ahead_survives_raw_journal_failure_and_duplicate_delivery(native,monkeypatch):
    main,core,where,scope,sent=native
    batch=next(iter(dialogue.load(where,'Продажи')['batches'].values()))
    args=dict(chat_id=scope['chat_id'],project='Монитор',action='reply',message_id=101,reply_to_id=100,
              reply_text=batch['text'],reply_from_id=123,reply_is_bot=True,text=OWNER_TEXT,
              author_id=4242,author='Менеджер',telegram_date=STAMP,sign=core._web_login_sign('monitor-sales',scope['chat_id']))
    original=dialogue.reply
    monkeypatch.setattr(dialogue,'reply',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('simulated crash after write-ahead')))
    with pytest.raises(RuntimeError):core.internal_monitor_sales_chat(core.SalesChatRequest(**args))
    durable=follow.load(where,'Продажи')
    assert len(durable['events'])==3 and durable['ingestions'][f"{scope['chat_id']}:101"]['text']==OWNER_TEXT
    assert next(iter(durable['events'].values()))['due_at']==DUE.isoformat()
    monkeypatch.setattr(dialogue,'reply',original)
    core.internal_monitor_sales_chat(core.SalesChatRequest(**args))
    assert len(next(iter(dialogue.load(where,'Продажи')['batches'].values()))['replies'])==1
    assert len(follow.load(where,'Продажи')['events'])==3


def test_completion_registration_text_does_not_invent_a_promised_date(tmp_path):
    scope,rows,_,batch=setup(tmp_path);answer(tmp_path,scope,batch,text='1. зарегистрировали')
    rows[0].update(escrow_paid=100_000_000,escrow_observed=True)
    source={'rows':rows,'as_of':'2026-11-23','as_of_provenance':'uploader_declared'}
    store.save(tmp_path,'Продажи',{'contracting':source},'SYNTHETIC-COMPLETION.xlsx')
    follow.poll(tmp_path,'Продажи',scope,dt.datetime.fromtimestamp(STAMP,follow.MOSCOW))
    text=next(v['text'] for k,v in follow.load(tmp_path,'Продажи')['deliveries'].items() if k.startswith('result:'))
    assert 'В ответе сообщили о регистрации' in text and 'Регистрацию ожидали' not in text


def test_native_construction_report_keeps_priority_over_answer_candidate(native,monkeypatch):
    import developaid_monitor_daily as daily
    main,core,where,scope,sent=native
    text=('Добрый день.\n1. Первый : Итр- 1чел., Рабочие - 6 чел.\n'
          '2. Второй:ИТР- 11чел.;\nРабочие - 50чел.;\nПримечание: регистрация и оплата документов ожидаются.')
    assert len(daily.parse_daily_report(text)['contractors'])==2 and follow.looks_like_answer(text)
    calls=[];candidates=[]
    monkeypatch.setattr(core,'_site_chat_store',lambda chat,text,date,**kw:calls.append((chat,text,date)) or {'bound':'Монитор'})
    monkeypatch.setattr(core,'_sales_chat_store',lambda *a,**kw:candidates.append(kw) or {'candidate':False})
    chat={'id':scope['chat_id'],'type':'supergroup'}
    core._telegram_group_message(chat,{'chat':chat,'from':{'id':4242},'message_id':999,'date':STAMP,'text':text})
    assert len(calls)==1 and calls[0][1]==text and not candidates and not sent


def test_same_question_key_in_two_groups_keeps_distinct_scope_state(tmp_path):
    first,_,_,batch1=setup(tmp_path)
    second=dict(first,chat_id=-10023456)
    _,_,_,batch2=setup(tmp_path,second)
    answer(tmp_path,first,batch1);answer(tmp_path,second,batch2)
    events=follow.load(tmp_path,'Продажи')['events']
    assert len(events)==6
    follow.stop(tmp_path,'Продажи',first['chat_id'])
    remaining=follow.load(tmp_path,'Продажи')['events'].values()
    assert all(e['state']=='cancelled' for e in remaining if e['scope']['chat_id']==first['chat_id'])
    assert any(e['state']=='scheduled' for e in remaining if e['scope']['chat_id']==second['chat_id'])
