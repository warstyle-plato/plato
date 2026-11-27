"""Unchanged sources cannot readmit an older contract calculation method."""
import copy
import time

import pytest

import developaid_contract_control as control
import developaid_management_report_jobs as jobs
import developaid_monitor_ledgers as ledgers
from tests.test_monitor_cumulative_api import api, core, KEY, poll, post  # noqa:F401


def retained(root, result, *, ticket='a'*32, revision='', key=KEY, session='', project='Fixture'):
    profile='monitor-cumulative-v1:contracts'
    store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    store.start(jobs.owner_binding(key,session,profile),profile,{'synthetic':True},lambda:result,ticket,
                context=ledgers.snapshot_job_context(project),result_revision=revision,
                result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
    for _ in range(500):
        state=store.poll(ticket,jobs.owner_binding(key,session,profile),profile)
        if not state['pending']:
            return store
        time.sleep(.01)
    raise AssertionError('Synthetic retained calculation did not finish')


@pytest.mark.parametrize('body',[{'register':{}},{'register':{'rows':[]}},
    {'control':{'components':{'material':{'counted':120.0}}}},
    {'comparison':{'lines':[]}}, {'gpr':{'presentation':{'schema':'contract-gpr-known-state-v9'}}}])
@pytest.mark.parametrize('revision',[None,'contract-gpr-calendar-rds-plan-fact-v4',False,{},''])
def test_old_calculated_dto_refused_even_without_a_source_binding(api,body,revision):  # noqa:F811
    client,root=api
    result={'ok':True,**body}
    if revision is not None:result['contract_calculation_revision']=revision
    store=retained(root,result)
    before={suffix:store._path('a'*32,suffix).read_bytes() for suffix in ('json','result')}
    response=poll(client,'a'*32)
    assert response.status_code==409 and response.headers['x-monitor-job-error']=='calculation_changed'
    assert 'Обновить договоры' in response.json()['detail']
    assert {suffix:store._path('a'*32,suffix).read_bytes() for suffix in before}==before


@pytest.mark.parametrize('offset',[0,jobs.RESULT_PART_BYTES,3*jobs.RESULT_PART_BYTES])
def test_every_old_method_piece_refused_without_loading_or_rewriting_the_dto(api,monkeypatch,offset):  # noqa:F811
    client,root=api
    store=retained(root,{'ok':True,'register':{'rows':[]},'padding':'x'*(4*jobs.RESULT_PART_BYTES)})
    before={suffix:store._path('a'*32,suffix).read_bytes() for suffix in ('json','result')}
    monkeypatch.setattr(jobs.Store,'poll',lambda *a,**k:pytest.fail('Old piece must fail on bounded metadata'))
    response=post(client,'contracts/result-part',ticket='a'*32,offset=offset)
    assert response.status_code==409 and response.headers['x-monitor-job-error']=='calculation_changed'
    assert {suffix:store._path('a'*32,suffix).read_bytes() for suffix in before}==before
    assert post(client,'contracts/result-part',ticket='a'*32,offset=offset,key='wrong').status_code==403
    assert post(client,'contracts/result-part',ticket='a'*32,offset=offset,session='other').status_code==404


def test_fresh_producer_stamps_calculation_once_and_middle_piece_needs_no_full_decode(api,monkeypatch):  # noqa:F811
    client,root=api;calls=[]
    source={'ok':True,'register':{'rows':[]},'padding':'x'*(4*jobs.RESULT_PART_BYTES)}
    frozen=copy.deepcopy(source)
    def calculate(*args):calls.append(args);return source
    monkeypatch.setattr(core,'_monitor_cumulative_execute',calculate)
    response=post(client,'contracts/build',project='Fixture',cut='2026-11-27',ticket='b'*32)
    assert response.status_code==202
    fresh=poll(client,'b'*32)
    assert fresh.status_code==200 and fresh.json()['contract_calculation_revision']==control.CALCULATION_REVISION
    store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    assert store._meta('b'*32)['result_revision']==control.CALCULATION_REVISION
    monkeypatch.setattr(jobs.Store,'poll',lambda *a,**k:pytest.fail('Middle piece must use bounded metadata'))
    assert post(client,'contracts/result-part',ticket='b'*32,offset=jobs.RESULT_PART_BYTES).status_code==200
    assert len(calls)==1 and source==frozen


@pytest.mark.parametrize('result',[{'ok':True,'document':{'saved':True}}, {'ok':False,'detail':'Read failed'}])
def test_old_plain_acknowledgements_and_errors_remain_readable(api,result):  # noqa:F811
    client,root=api;retained(root,result)
    assert poll(client,'a'*32).status_code==200


def test_revision_policy_is_server_only_strict_and_does_not_rewrite_saved_ack(api):  # noqa:F811
    _,root=api;result={'ok':True,'document':{'saved':True}}
    store=retained(root,result)
    profile='monitor-cumulative-v1:contracts';owner=jobs.owner_binding(KEY,'',profile)
    before=store._meta('a'*32)
    ack=store.start(owner,profile,{'synthetic':True},lambda:pytest.fail('No repeated mutation'),'a'*32,
                    context=before['context'],result_revision=control.CALCULATION_REVISION)
    assert ack['document']==result['document'] and store._meta('a'*32)==before
    for invalid in (True,1,{},'x'*129,'bad\nvalue'):
        with pytest.raises(ValueError):
            store.start(owner,profile,{},lambda:result,result_revision=invalid)
        with pytest.raises(ValueError):
            store.poll_part('a'*32,owner,profile,required_result_revision=invalid)


def test_legacy_mutation_lost_ack_can_retry_the_same_post_without_a_second_write(api,monkeypatch):  # noqa:F811
    client,root=api;calls=[]
    native=jobs.Store.start
    def legacy(store,*args,**kwargs):
        kwargs.pop('result_revision',None)
        return native(store,*args,**kwargs)
    def execute(*args):calls.append(args);return {'ok':True,'link':{'confirmed':True}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    monkeypatch.setattr(jobs.Store,'start',legacy)
    body={'project':'Fixture','cut':'2026-11-27','contract_id':'c1','evidence_id':'e1','ticket':'d'*32}
    first=post(client,'contracts/link',**body)
    assert first.status_code==202
    saved=poll(client,'d'*32)
    assert saved.status_code==200 and saved.json()['link']['confirmed']
    store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    before={suffix:store._path('d'*32,suffix).read_bytes() for suffix in ('json','result')}
    monkeypatch.setattr(jobs.Store,'start',native)
    retry=post(client,'contracts/link',**body)
    assert retry.status_code==200 and retry.json()==saved.json() and len(calls)==1
    assert {suffix:store._path('d'*32,suffix).read_bytes() for suffix in before}==before


def test_current_graph_schema_does_not_bless_old_method_for_poll_or_excel(card,monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import developaid_monitor as monitor
    import developaid_monitor_contracts as contracts
    from tests.test_contract_relative_gpr_calendar import PROJECT,CUT,KEY as REL_KEY,ROW,finished
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',REL_KEY)
    monkeypatch.setattr(contracts,'build',lambda *a,**k:{'rows':[copy.deepcopy(ROW)],'cut':CUT})
    client=TestClient(main.app);session='synthetic-owner'
    body={'key':REL_KEY,'session':session,'project':PROJECT,'cut':CUT,'contract_id':ROW['id']}
    fresh=finished(client,client.post('/monitor/contracts/documents',json=body))
    assert fresh['contract_calculation_revision']==control.CALCULATION_REVISION
    old=copy.deepcopy(fresh)
    old.pop('contract_calculation_revision');old.pop('ticket');old.pop('pending')
    old['control'].setdefault('components',{}).setdefault('material',{})['counted']=120.0
    store=retained(monitor._SNAPSHOT_DIR.parent,old,ticket='c'*32,key=REL_KEY,session=session,project=PROJECT)
    before={suffix:store._path('c'*32,suffix).read_bytes() for suffix in ('json','result')}
    assert client.post('/monitor/contracts/result',json={'key':REL_KEY,'session':session,'ticket':'c'*32}).status_code==409
    for route,meta in [('gpr.xlsx','gpr_export'),('comparison.xlsx','comparison_export')]:
        request={**body,'ticket':'c'*32,'revision':fresh[meta].get('revision') or '0'*64}
        if route=='comparison.xlsx':request['selected_tokens']=[]
        response=client.post('/monitor/contracts/'+route,json=request)
        assert response.status_code==409 and 'Обновить договоры' in response.json()['detail']
    assert {suffix:store._path('c'*32,suffix).read_bytes() for suffix in before}==before
    assert client.post('/monitor/contracts/gpr.xlsx',json={**body,'ticket':fresh['ticket'],
        'revision':fresh['gpr_export']['revision']}).status_code==200


def test_native_page_discards_old_pending_ticket_after_method_changed_without_retry_loop():
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    with browser_page(390) as (page,responses,errors):
        admitted=[]
        def build(route):
            admitted.append(route.request.post_data_json['ticket'])
            responses(route)
        def part(route):
            if len(admitted)==1:
                return route.fulfill(status=409,json={'detail':jobs.CALCULATION_CHANGED_DETAIL},
                    headers={'X-Monitor-Job-Error':'calculation_changed'})
            responses(route)
        page.route('**/monitor/contracts/build',build)
        page.route('**/monitor/contracts/result-part',part)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_contain_text('Расчёт договоров обновлён')
        assert len(admitted)==1 and page.locator('#contractsRows .contract-row').count()==0
        page.locator('#contractsRefresh').click()
        expect(page.locator('#contractsRows .contract-row')).to_have_count(2)
        assert len(admitted)==2 and admitted[0]!=admitted[1] and not errors


from tests.test_contract_relative_gpr_calendar import card  # noqa:E402,F401
