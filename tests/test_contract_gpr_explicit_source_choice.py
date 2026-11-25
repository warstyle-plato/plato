"""Exact explicit source choice resolves a latest-edition GPR ambiguity only."""
import copy
import hashlib
import io
import json
import multiprocessing

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import developaid_contract_files as files
import developaid_contract_gpr as gpr
import developaid_contract_gpr_export as export
import developaid_monitor_contracts as contracts
from tests.test_contract_relative_gpr_calendar import (card, record, ROW, PROJECT, CUT, KEY, finished)


def twins(card, pending=False):
    folder, original, _ = card
    older, _ = record(folder, 'initial-copy')
    agreement = {'number':'1','date':'2026-02-05'}
    first, _ = record(folder, 'DS1-main', agreement, pending=pending)
    second, _ = record(folder, 'DS1-separate-GPR', agreement, pending=pending)
    return folder, original, older, first, second


def activate(listed, source, signed=True):
    return gpr.save(PROJECT,ROW,CUT,source,listed['gpr']['guard'],'activate',
        'Учебная проверка точного файла и подписи контрагента, страница 1','synthetic-test-only',counterparty_signed=signed)


def test_old_recognised_twins_are_not_guessed_but_latest_exact_source_can_be_chosen(card):
    folder, old, old_copy, first, second = twins(card)
    before=files.listing(PROJECT,ROW['id'],CUT)
    assert before['gpr']['source'] is None
    choices={x['source']['sha256']:x for x in before['gpr']['pending']}
    assert choices[first]['can_activate'] and choices[second]['can_activate']
    assert not choices[old]['can_activate'] and not choices[old_copy]['can_activate']
    source_bytes={p.name:p.read_bytes() for p in folder.glob('*.json')}
    after=activate(before,second)
    assert after['gpr']['source']['sha256']==second
    assert files._schedule_identity(after['documents'],CUT)['sha256']==second
    counted=gpr.counted(after['documents'])
    assert [x['sha256'] for x in counted if (x.get('schedule') or {}).get('lines')]==[second]
    assert {p.name:p.read_bytes() for p in folder.glob('*.json') if p.name!=gpr.EVENTS}==source_bytes
    event=gpr.events(folder)[0];proof=event['source_choice']
    assert event['source']['sha256']==second and event['cryptographically_validated'] is False
    assert {x['source']['sha256'] for x in proof['candidates']}=={first,second}
    assert proof['guard_before']==before['gpr']['guard'] and proof['history_event_ids_before']==[]
    assert proof['candidates_sha256']==gpr.digest(proof['candidates'])
    again=activate(after,first)
    assert again['gpr']['source']['sha256']==first
    assert gpr.events(folder)[1]['source_choice']['history_event_ids_before']==[event['event_id']]


def test_choice_never_drops_other_peer_price_terms_or_estimates(card):
    folder,_,_,first,second=twins(card)
    before=files._stored(folder/(first+'.json'))
    # Projection retains document components verbatim even while its GPR is excluded.
    before['price']={'source_fact':'same full source price'}
    before['terms']={'source_fact':'same full source terms'}
    before['estimates']=[{'source_fact':'same native RDS payload'}]
    projected=gpr.project_records([before,files._stored(folder/(second+'.json'))],[])
    assert all(x['gpr_status']=='conflicting_edition' for x in projected)
    counted=gpr.counted(projected)
    retained=next(x for x in counted if x['sha256']==first)
    assert retained['schedule'] is None
    for key in ('price','terms','estimates'):assert retained[key]==before[key]


def test_passive_new_pending_peer_preserves_choice_and_full_new_set_needs_fresh_guard(card):
    folder,_,_,first,second=twins(card)
    chosen=activate(files.listing(PROJECT,ROW['id'],CUT),second)
    third,_=record(folder,'newly-discovered-peer',{'number':'1','date':'2026-02-05'},pending=True)
    current=files.listing(PROJECT,ROW['id'],CUT)
    assert current['gpr']['source']['sha256']==second
    with pytest.raises(files.ContractFilesProblem,match='изменились'):activate(chosen,third)
    newer=activate(current,third)
    assert newer['gpr']['source']['sha256']==third
    assert len(gpr.events(folder)[-1]['source_choice']['candidates'])==3
    assert activate(newer,first)['gpr']['source']['sha256']==first


@pytest.mark.parametrize('which',['older','future','unsigned','removed','unconfirmed','malformed_confirmation'])
def test_older_future_removed_unconfirmed_or_unsigned_cannot_be_selected(card,which):
    folder,old,_,first,second=twins(card)
    wanted=old if which=='older' else second
    if which=='future':
        wanted,_=record(folder,'future',{'number':'2','date':'2027-01-01'},pending=True)
    elif which in {'removed','unconfirmed','malformed_confirmation'}:
        value=files._stored(folder/(wanted+'.json'))
        if which=='removed':value['removed_at']='2026-02-10T00:00:00+00:00'
        else:value['scan']={'confirmed_at':'not-a-timestamp' if which=='malformed_confirmation' else None,'manual_note':'not confirmed'}
        files._json(folder/(wanted+'.json'),value)
    current=files.listing(PROJECT,ROW['id'],CUT)
    with pytest.raises(files.ContractFilesProblem):activate(current,wanted,signed=which!='unsigned')
    assert gpr.events(folder)==[]


def test_later_pending_graph_and_DS_without_graph_do_not_replace_choice(card):
    folder,_,_,_,second=twins(card)
    chosen=activate(files.listing(PROJECT,ROW['id'],CUT),second)
    record(folder,'DS2-without-GPR',{'number':'2','date':'2026-02-06'},schedule=False)
    assert files.listing(PROJECT,ROW['id'],CUT)['gpr']['source']['sha256']==second
    latest,_=record(folder,'DS3-pending',{'number':'3','date':'2026-02-07'},pending=True)
    current=files.listing(PROJECT,ROW['id'],CUT)
    assert current['gpr']['source']['sha256']==second
    with pytest.raises(files.ContractFilesProblem,match='последней'):activate(current,second)
    assert activate(current,latest)['gpr']['source']['sha256']==latest


@pytest.mark.parametrize('change',['graph','confirmation','withdrawal','source_identity'])
def test_recorded_choice_component_change_requires_new_review(card,change):
    folder,_,_,first,second=twins(card)
    activate(files.listing(PROJECT,ROW['id'],CUT),second)
    path=folder/(second+'.json');value=files._stored(path)
    if change=='graph':value['schedule']['lines'][0]['name']='Changed source meaning'
    elif change=='confirmation':value['scan']={'confirmed_at':'2026-02-08T00:00:00+00:00'}
    elif change=='withdrawal':value['removed_at']='2026-02-10T00:00:00+00:00'
    else:value['agreement']['number']='9'
    files._json(path,value)
    assert (files.listing(PROJECT,ROW['id'],CUT)['gpr']['source'] or {}).get('sha256')!=second


@pytest.mark.parametrize('kind',['different_contract','different_legal_DS'])
def test_same_sort_order_is_not_same_legal_identity(card,kind):
    folder,_,_,first,second=twins(card)
    for sha,number in [(first,'A'),(second,'B')]:
        value=files._stored(folder/(sha+'.json'))
        if kind=='different_legal_DS':value['agreement']['number']=number
        elif sha==second:value['contract']['number']='OTHER'
        files._json(folder/(sha+'.json'),value)
    current=files.listing(PROJECT,ROW['id'],CUT)
    assert all(not x['can_activate'] for x in current['gpr']['pending'])
    with pytest.raises(files.ContractFilesProblem,match='реквизиты'):activate(current,first)


@pytest.mark.parametrize('damage',['hash','missing','symlink','peer_hash','history_during_check'])
def test_exact_source_pdf_and_full_preaction_history_are_guarded(card,damage,monkeypatch,tmp_path):
    folder,_,_,first,second=twins(card);current=files.listing(PROJECT,ROW['id'],CUT)
    wanted=folder/((first if damage=='peer_hash' else second)+'.pdf')
    if damage in {'hash','peer_hash'}:wanted.write_bytes(wanted.read_bytes()+b'changed')
    elif damage=='missing':wanted.unlink()
    elif damage=='symlink':
        outside=tmp_path/'outside.pdf';outside.write_bytes(wanted.read_bytes());wanted.unlink();wanted.symlink_to(outside)
    else:
        verify=gpr._verify_candidate_pdfs
        def raced(*args):
            verify(*args)
            files._json(folder/'links.json',{'choices':{},'external_owner_edit':True})
        monkeypatch.setattr(gpr,'_verify_candidate_pdfs',raced)
    # Reopen after source corruption so SHA verification, not just stale guard,
    # must reject the attempted source choice.
    with pytest.raises((files.ContractFilesProblem,ValueError,OSError)):
        guard=gpr.guard([folder]);current['gpr']['guard']=guard
        activate(current,second)
    assert gpr.events(folder)==[]


def test_anchor_changes_do_not_invalidate_source_choice_component(card):
    _,_,_,_,second=twins(card)
    chosen=activate(files.listing(PROJECT,ROW['id'],CUT),second)
    changed=gpr.save(PROJECT,ROW,CUT,second,chosen['gpr']['guard'],'anchor',
        'Учебный акт передачи площадки','synthetic-test-only',handover_date='2026-02-02')
    assert changed['gpr']['source']['sha256']==second
    assert changed['gpr']['schedule']['lines'][0]['start']=='2026-02-02'
    assert files.listing(PROJECT,ROW['id'],CUT)['gpr']['source']['sha256']==second


def test_single_source_V1_activation_compatibility(card):
    folder,sha,value=card;value['gpr_pending']=True;files._json(folder/(sha+'.json'),value)
    current=files.listing(PROJECT,ROW['id'],CUT)
    chosen=activate(current,sha)
    event=gpr.events(folder)[0];event.pop('source_choice');event.pop('event_id');event['event_id']=gpr.digest(event)
    files._json(folder/gpr.EVENTS,[event])
    assert files.listing(PROJECT,ROW['id'],CUT)['gpr']['source']['sha256']==sha


def test_native_admin_choice_refreshes_control_and_denies_old_ticket(card,monkeypatch):
    import main
    _,_,_,_,second=twins(card)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    monkeypatch.setattr(contracts,'build',lambda *a,**k:{'rows':[copy.deepcopy(ROW)],'cut':CUT})
    client=TestClient(main.app);base={'key':KEY,'session':'synthetic-owner','project':PROJECT,'cut':CUT,'contract_id':ROW['id']}
    opened=finished(client,client.post('/monitor/contracts/documents',json=base))
    assert opened['gpr']['source'] is None
    updated=finished(client,client.post('/monitor/contracts/gpr-change',json={**base,'action':'activate',
        'source_sha256':second,'expected_guard':opened['gpr']['guard'],'counterparty_signed':True,
        'note':'Учебная проверка точного файла и подписи, страница 1'}))
    assert updated['ok'] and updated['gpr']['source']['sha256']==second
    assert files._schedule_identity(updated['documents'],CUT)['sha256']==second
    assert client.post('/monitor/contracts/result',json={'key':KEY,'session':'synthetic-owner','ticket':opened['ticket']}).status_code==409
    exported=client.post('/monitor/contracts/gpr.xlsx',json={**base,'ticket':updated['ticket'],'revision':updated['gpr_export']['revision']})
    assert exported.status_code==200 and load_workbook(io.BytesIO(exported.content)).sheetnames==['ГПР','Выполнение']


@pytest.mark.parametrize('width',[390,1440])
def test_popup_shows_exact_latest_choices_and_requires_explicit_signed_reference(card,width):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    folder,old,old_copy,first,second=twins(card);calls=[]
    def snapshot():
        result=files.listing(PROJECT,ROW['id'],CUT)
        result['gpr']['presentation']=export.presentation(result['gpr']['schedule'] or {},{},CUT)
        result.update(ok=True,pending=False,ticket='e'*32)
        result['gpr_export']=export.bind_snapshot(PROJECT,CUT,ROW['id'],result,ROW)
        return result
    def change(route):
        body=route.request.post_data_json;calls.append(body)
        gpr.save(PROJECT,ROW,CUT,body['source_sha256'],body['expected_guard'],'activate',body['note'],
                 'synthetic-browser',counterparty_signed=body.get('counterparty_signed'))
        route.fulfill(json=snapshot())
    with browser_page(width) as (page,responses,errors):
        responses.data['rows']=[copy.deepcopy(ROW)]
        page.route('**/monitor/contracts/documents',lambda route:route.fulfill(json=snapshot()))
        page.route('**/monitor/contracts/gpr-change',change)
        page.locator('#contractsTab').click();page.locator('tr[data-contract-id="'+ROW['id']+'"] .contract-open').click()
        expect(page.locator('[data-gpr-activate]')).to_have_count(2)
        box=page.locator('[data-gpr-pending]').filter(has_text=second)
        expect(box).to_contain_text('DS1-separate-GPR.pdf')
        expect(box).to_contain_text('цена, условия и РДС остальных файлов сохраняются')
        box.locator('[data-gpr-activate]').click();assert calls==[]
        box.locator('[data-gpr-signed]').check()
        box.locator('[data-gpr-sign-reference]').fill('Учебная проверка подписи контрагента, страница 1')
        box.locator('[data-gpr-activate]').click()
        expect(page.locator('#contractGprDownload')).to_be_enabled()
        assert page.evaluate('contractGprState.source.sha256')==second
        assert len(calls)==1 and calls[0]['source_sha256']==second
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors



def _race_choice(root, guard, sha, start, output):
    import developaid_monitor as monitor
    monitor._SNAPSHOT_DIR=root
    start.wait(10)
    try:
        gpr.save(PROJECT,ROW,CUT,sha,guard,'activate','Учебная подпись и точный файл, страница 1',
                 'synthetic-worker',counterparty_signed=True)
        output.put('saved')
    except files.ContractFilesProblem:
        output.put('stale')


def test_two_workers_cannot_choose_different_sources_with_one_guard(card):
    import developaid_monitor as monitor
    folder,_,_,first,second=twins(card);current=files.listing(PROJECT,ROW['id'],CUT)
    context=multiprocessing.get_context('fork');start=context.Event();output=context.Queue()
    workers=[context.Process(target=_race_choice,args=(monitor._SNAPSHOT_DIR,current['gpr']['guard'],sha,start,output))
             for sha in (first,second)]
    for worker in workers:worker.start()
    start.set();results=[output.get(timeout=15) for _ in workers]
    for worker in workers:worker.join(15);assert worker.exitcode==0
    assert sorted(results)==['saved','stale'] and len(gpr.events(folder))==1
    assert files.listing(PROJECT,ROW['id'],CUT)['gpr']['source']==gpr.events(folder)[0]['source']


def test_source_history_append_during_validation_is_not_overwritten(card,monkeypatch):
    folder,_,_,_,second=twins(card);current=files.listing(PROJECT,ROW['id'],CUT)
    verify=gpr._verify_candidate_pdfs
    def append_history(*args):
        verify(*args)
        value={'sequence':1,'previous':'','schema':gpr.SCHEMA,'project':PROJECT,'contract_id':ROW['id'],
               'source':next(x['source'] for x in current['gpr']['pending'] if x['source']['sha256']==second),
               'action':'anchor','recorded_at':'2026-02-10T00:00:00+00:00','actor':'external-synthetic-owner',
               'origin':'manual_document_reference','note':'Concurrent synthetic date reference','handover_date':'2026-02-02',
               'advance_date':'','counterparty_signed':None,'cryptographically_validated':False}
        value['event_id']=gpr.digest(value);files._json(folder/gpr.EVENTS,[value])
    monkeypatch.setattr(gpr,'_verify_candidate_pdfs',append_history)
    with pytest.raises(files.ContractFilesProblem,match='история ГПР изменились'):activate(current,second)
    assert len(gpr.events(folder))==1 and gpr.events(folder)[0]['actor']=='external-synthetic-owner'


def test_malformed_persistent_choice_cannot_fall_back_to_legacy_peer(card):
    folder,_,_,_,second=twins(card);activate(files.listing(PROJECT,ROW['id'],CUT),second)
    event=gpr.events(folder)[0];event['source_choice']['history_sha256_before']='f'*64
    event.pop('event_id');event['event_id']=gpr.digest(event);files._json(folder/gpr.EVENTS,[event])
    assert files.listing(PROJECT,ROW['id'],CUT)['gpr']['source'] is None


def test_different_graphs_are_not_merged_or_chosen_by_equivalence(card):
    folder,_,_,first,second=twins(card)
    value=files._stored(folder/(first+'.json'));value['schedule']['lines'][0]['name']='Different actual source graph'
    value['schedule']['lines'][0]['relative_segments']=[{'start_day':8,'finish_day':14,'start_offset':7,'end_offset':14}]
    files._json(folder/(first+'.json'),value)
    current=files.listing(PROJECT,ROW['id'],CUT);assert current['gpr']['source'] is None
    selected=activate(current,first)
    assert selected['gpr']['source']['sha256']==first
    assert selected['gpr']['schedule']['lines'][0]['name']=='Different actual source graph'
    assert files._stored(folder/(second+'.json'))['schedule']['lines'][0]['name']=='Учебная работа'
