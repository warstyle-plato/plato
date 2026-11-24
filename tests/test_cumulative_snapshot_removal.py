"""Reversible removal selects active immutable sources, never deletes evidence."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_management_report_jobs as jobs

PROJECT = 'Учебный архив'


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    folder = ledgers._root(PROJECT, create=True)
    result = []
    for day, raw in [('2026-01-10', b'earlier immutable source'), ('2026-01-20', b'later immutable source')]:
        sha = hashlib.sha256(raw).hexdigest()
        sid = day + '-' + sha
        item = dict(snapshot_id=sid, taken_at=day, sha256=sha, filename=day+'.zip',
                    loaded_at=day+'T12:00:00+00:00', files_count=1, ledgers_count=0,
                    quantity_rows_count=0, warnings_count=0, parser_schema=ledgers.PARSER_SCHEMA,
                    ledgers=[], summary_contracts=[], files=[], warnings=[])
        (folder/(sid+'.json')).write_text(json.dumps(item))
        (folder/(sid+'.zip')).write_bytes(raw)
        result.append(item)
    return folder, result


def change(sid, *, restore=False, revision=None):
    return ledgers.change_snapshot_activity(PROJECT, sid, revision or ledgers.snapshot_inventory(PROJECT)['revision'], restore=restore)


def test_remove_restore_and_date_selection_preserve_every_original_byte(sources):
    folder, (old, new) = sources
    original = {p.name:p.read_bytes() for p in folder.iterdir() if p.suffix in {'.json','.zip'}}
    result = change(new['snapshot_id'])
    assert result['active_snapshot_id'] == old['snapshot_id']
    assert len(result['snapshots']) == 2 and result['snapshots'][0]['removed'] is True
    assert ledgers.latest_snapshot(PROJECT, '2026-02-01')['snapshot_id'] == old['snapshot_id']
    assert ledgers.latest_snapshot(PROJECT, '2026-01-09') is None
    assert [s['snapshot_id'] for s in ledgers.list_snapshots(PROJECT)] == [old['snapshot_id']]
    assert ledgers.removed_snapshot_ids(PROJECT) == {new['snapshot_id']}
    assert all((folder/name).read_bytes()==raw for name,raw in original.items())
    with pytest.raises(ledgers.LedgerConflict, match='удалён'):
        ledgers.read_snapshot(PROJECT, new['snapshot_id'])
    with pytest.raises(ledgers.LedgerConflict, match='удалён'):
        ledgers.verified_archive(PROJECT, new['snapshot_id'])
    restored = change(new['snapshot_id'], restore=True)
    assert restored['active_snapshot_id'] == new['snapshot_id']
    assert ledgers.latest_snapshot(PROJECT)['snapshot_id'] == new['snapshot_id']
    assert [e['action'] for e in ledgers._activity(folder)['events']] == ['remove','restore']
    assert all((folder/name).read_bytes()==raw for name,raw in original.items())


def test_removing_every_import_is_missing_source_not_zero_or_reupload(sources):
    _, (old,new) = sources
    change(old['snapshot_id']); change(new['snapshot_id'])
    assert ledgers.list_snapshots(PROJECT) == []
    assert ledgers.latest_snapshot(PROJECT) is None
    assert len(ledgers.snapshot_inventory(PROJECT)['snapshots']) == 2


def test_cas_rejects_double_click_stale_roster_and_cross_project(sources):
    folder, (old,new) = sources
    token = ledgers.snapshot_inventory(PROJECT)['revision']
    change(new['snapshot_id'], revision=token)
    with pytest.raises(ledgers.LedgerConflict, match='Список'):
        change(old['snapshot_id'], revision=token)
    assert ledgers.list_snapshots(PROJECT)[0]['snapshot_id'] == old['snapshot_id']
    other = 'Другой проект'
    ledgers._root(other, create=True)
    before = ledgers.snapshot_inventory(other)
    with pytest.raises(ledgers.LedgerProblem, match='не найден'):
        ledgers.change_snapshot_activity(other, new['snapshot_id'], before['revision'])
    assert not (ledgers._root(other)/ledgers._ACTIVITY_FILE).exists()
    assert len(ledgers._activity(folder)['events']) == 1


def test_two_workers_with_one_cas_token_commit_one_event(sources):
    folder, (_,new) = sources
    token=ledgers.snapshot_inventory(PROJECT)['revision']
    def attempt(_):
        try:change(new['snapshot_id'], revision=token);return 'changed'
        except ledgers.LedgerConflict:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ['changed','stale']
    assert len(ledgers._activity(folder)['events']) == 1


@pytest.mark.parametrize('target', ['../other', '2026-01-20', '2026-01-20-'+'g'*64])
def test_identifier_is_validated_before_write(sources, target):
    folder,_=sources
    with pytest.raises(ledgers.LedgerProblem):change(target)
    assert not (folder/ledgers._ACTIVITY_FILE).exists()


def test_corrupt_or_symlink_journal_fails_closed(sources, tmp_path):
    folder,(_,new)=sources
    path=folder/ledgers._ACTIVITY_FILE
    path.write_text('broken')
    with pytest.raises(ledgers.LedgerProblem, match='История'):
        ledgers.list_snapshots(PROJECT)
    path.unlink();outside=tmp_path/'outside';outside.write_text('unchanged');path.symlink_to(outside)
    with pytest.raises(ledgers.LedgerProblem):change(new['snapshot_id'])
    assert outside.read_text()=='unchanged'


def test_upload_cannot_silently_reactivate_removed_original(sources, monkeypatch):
    _,(_,new)=sources
    change(new['snapshot_id'])
    monkeypatch.setattr(ledgers,'parse_archive',lambda *_:{'ledgers':[], 'summary_contracts':[]})
    with pytest.raises(ledgers.LedgerConflict, match='удалён'):
        ledgers.store_archive(PROJECT,b'later immutable source',new['taken_at'])
    assert ledgers.removed_snapshot_ids(PROJECT)=={new['snapshot_id']}


def test_original_without_summary_is_not_itself_a_removal_rule(sources):
    _,(_,new)=sources
    assert new['summary_contracts']==[]
    assert ledgers.latest_snapshot(PROJECT)['snapshot_id']==new['snapshot_id']


def test_removed_source_does_not_reappear_as_an_orphan_in_project_audit(sources, monkeypatch):
    import developaid_contract_source_review as review
    _,(old,new)=sources
    change(new['snapshot_id'])
    seen=[]
    def inspect(project,cut,root,descriptor,guard,snapshots):
        seen.extend(s['snapshot_id'] for s in snapshots);return {'pass':True}
    monkeypatch.setattr(review,'_project_audit',inspect)
    assert review.project_audit(PROJECT,'2026-02-01')=={'pass':True}
    assert seen==[old['snapshot_id']]


def test_removed_confirmation_is_not_rebound_to_identical_fallback_indices(sources, monkeypatch):
    import developaid_schedule_gpr_physical as physical
    _,(old,new)=sources
    event={'source_sha256':'a'*64,'snapshot_id':new['snapshot_id'],
           'recorded_at':'2026-01-21T12:00:00+00:00',
           'configuration':{'tasks':[{'task_id':'1','mode':'quantities','scope_confirmed':True}],
                            'components':[{'component_id':'part','task_id':'1','item_ids':['0:0']}], 'note':''}}
    monkeypatch.setattr(physical,'_history',lambda _:[copy.deepcopy(event)])
    change(new['snapshot_id'])
    source={'source_sha256':'a'*64,'tasks':{'1':{'task_id':'1'}},'state':'approved_gpr'}
    state=physical._state(PROJECT,'2026-02-01',source,ledgers.latest_snapshot(PROJECT))
    assert state['source_changed'] and not state['binding_projected']
    assert state['configuration']['components']==[]
    assert state['binding_confirmed_snapshot_id'] is None
    # Restoration makes the saved exact-source decision usable again.
    change(new['snapshot_id'],restore=True)
    state=physical._state(PROJECT,'2026-02-01',source,ledgers.latest_snapshot(PROJECT))
    assert not state['source_changed'] and state['configuration']==event['configuration']


def _finish(store, owner, profile, response):
    limit=time.monotonic()+5
    while response['pending'] and time.monotonic()<limit:
        time.sleep(.01);response=store.poll(response['ticket'],owner,profile)
    assert not response['pending']
    return response


def test_job_context_revokes_old_pending_completed_parts_and_explicit_retries(sources,tmp_path):
    _,(_,new)=sources
    context=ledgers.snapshot_job_context(PROJECT)
    store=jobs.Store(tmp_path/'jobs',context_validator=ledgers.validate_snapshot_job_context)
    started=store.start('owner','private',{'same':'params'},lambda:{'value':'old'},context=context)
    ticket=_finish(store,'owner','private',started)['ticket']
    change(new['snapshot_id'])
    for request in (lambda:store.poll(ticket,'owner','private'),
                    lambda:store.poll_part(ticket,'owner','private'),
                    lambda:store.start('owner','private',{'same':'params'},lambda:{},ticket,
                                       context=ledgers.snapshot_job_context(PROJECT))):
        with pytest.raises(jobs.JobProblem) as error:request()
        assert error.value.status==409 and error.value.code=='source_changed'
    # A new click with identical business parameters can always build current data.
    fresh=store.start('owner','private',{'same':'params'},lambda:{'value':'current'},
                      context=ledgers.snapshot_job_context(PROJECT))
    assert fresh['ticket']!=ticket
    assert _finish(store,'owner','private',fresh)['value']=='current'
    # Restoring the import does not revive any pre-removal output.
    change(new['snapshot_id'],restore=True)
    with pytest.raises(jobs.JobProblem):store.poll(ticket,'owner','private')


def test_legacy_job_is_not_current_but_generic_store_behavior_is_unchanged(sources,tmp_path):
    folder=tmp_path/'jobs'
    generic=jobs.Store(folder)
    result=_finish(generic,'owner','ordinary',generic.start('owner','ordinary',{},lambda:{'ok':True}))
    assert generic.poll(result['ticket'],'owner','ordinary')['ok']
    guarded=jobs.Store(folder,context_validator=ledgers.validate_snapshot_job_context)
    with pytest.raises(jobs.JobProblem) as error:guarded.poll(result['ticket'],'owner','ordinary')
    assert error.value.status==409
    assert generic.poll(result['ticket'],'owner','ordinary')['ok']


def test_empty_namespace_without_ks_has_stable_admission_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'not-created-yet')
    context=ledgers.snapshot_job_context('Новый проект без КС')
    ledgers.validate_snapshot_job_context(context)
    assert context==ledgers.snapshot_job_context('Новый проект без КС')
    assert ledgers.list_snapshots('Новый проект без КС')==[]


def test_native_endpoint_requires_current_admin_and_rejects_stale_exact_target(sources, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    key='synthetic-removal-administrator'
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',key)
    folder,(_,new)=sources
    payload={'project':PROJECT,'snapshot_id':new['snapshot_id'],
             'expected_revision':ledgers.snapshot_inventory(PROJECT)['revision']}
    client=TestClient(main.app)
    for bad in ('','wrong'):
        response=client.post('/monitor/cumulative/remove',json=dict(payload,key=bad,session='claimed-demo'))
        assert response.status_code==403 and response.headers['cache-control']=='private, no-store'
        assert not (folder/ledgers._ACTIVITY_FILE).exists()
    response=client.post('/monitor/cumulative/remove',json=dict(payload,key=key))
    assert response.status_code==200 and response.json()['snapshots'][0]['removed']
    assert response.headers['cache-control']=='private, no-store'
    stale=client.post('/monitor/cumulative/remove',json=dict(payload,key=key))
    assert stale.status_code==409 and stale.headers['cache-control']=='private, no-store'
    invalid=client.post('/monitor/cumulative/remove',json=dict(payload,key=key,restore='false'))
    assert invalid.status_code==422 and invalid.headers['cache-control']=='private, no-store'
    duplicate=client.post('/monitor/cumulative/remove',content='{"key":"x","key":"y"}',headers={'Content-Type':'application/json'})
    assert duplicate.status_code==422 and duplicate.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('width',[390,1440])
def test_actual_page_remove_confirmation_restore_and_markup_safety(width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page, MARKER
    old='2026-01-10-'+'a'*64;new='2026-01-20-'+'b'*64
    deleted=False;revision='c'*64;calls=[];dialogs=[]
    def handle(route):
        nonlocal deleted,revision
        path=route.request.url.split('?')[0].split('/monitor/')[-1]
        if path not in ('cumulative/list','cumulative/remove'):return route.fallback()
        payload=route.request.post_data_json
        if path=='cumulative/remove':
            calls.append(payload)
            assert payload['expected_revision']==revision and payload['snapshot_id']==new
            deleted=not payload['restore'];revision='d'*64 if deleted else 'e'*64
        return route.fulfill(json={'revision':revision,'snapshots':[
            {'snapshot_id':new,'taken_at':'2026-01-20','filename':MARKER+'.zip','files_count':2,'removed':deleted},
            {'snapshot_id':old,'taken_at':'2026-01-10','filename':'Предыдущий.zip','files_count':17,'removed':False}]})
    with browser_page(width=width) as (page,responses,errors):
        page.route('**/monitor/**',handle)
        page.locator('#dataTab').click()
        page.evaluate('loadCumulativeHistory()')
        expect(page.locator('#cumulativeHistory button').first).to_have_text('Удалить')
        def dismiss(dialog):dialogs.append(dialog.message);dialog.dismiss()
        page.once('dialog',dismiss);page.locator('#cumulativeHistory button').first.click()
        assert not calls and 'Учебный проект' in dialogs[-1] and '20.01.2026' in dialogs[-1]
        def accept(dialog):dialogs.append(dialog.message);dialog.accept()
        page.once('dialog',accept);page.locator('#cumulativeHistory button').first.click()
        expect(page.locator('#cumulativeHistory button').first).to_have_text('Восстановить')
        expect(page.locator('#cumulativeHistory')).to_contain_text('удалён из расчётов')
        assert len(calls)==1 and calls[0]['restore'] is False
        assert page.locator('#cumulativeHistory img').count()==0
        assert page.evaluate('window.untrustedRan') is None
        page.once('dialog',accept);page.locator('#cumulativeHistory button').first.click()
        expect(page.locator('#cumulativeHistory button').first).to_have_text('Удалить')
        assert len(calls)==2 and calls[1]['restore'] is True
        assert not errors


@pytest.mark.parametrize('failure',['abort_after_commit','stale'])
def test_actual_page_uncertain_commit_clears_old_views_without_second_post(failure):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    removed=False;calls=[];sid='2026-01-20-'+'b'*64
    def route_handler(route):
        nonlocal removed
        path=route.request.url.split('?')[0].split('/monitor/')[-1]
        if path not in ('cumulative/list','cumulative/remove'):return route.fallback()
        if path=='cumulative/remove':
            calls.append(route.request.post_data_json);removed=True
            if failure=='abort_after_commit':return route.abort('failed')
            return route.fulfill(status=409,json={'detail':'Список архивов изменился. Обновите его.'})
        return route.fulfill(json={'revision':('d' if removed else 'c')*64,'snapshots':[
            {'snapshot_id':sid,'taken_at':'2026-01-20','filename':'Учебный.zip','removed':removed}]})
    with browser_page() as (page,responses,errors):
        page.route('**/monitor/**',route_handler);page.locator('#dataTab').click();page.evaluate('loadCumulativeHistory()')
        expect(page.locator('#cumulativeHistory button')).to_have_text('Удалить')
        page.evaluate("currentView={old:true};contractRegister={old:true};document.getElementById('dashCard').classList.remove('hidden')")
        page.once('dialog',lambda d:d.accept());page.locator('#cumulativeHistory button').click()
        expect(page.locator('#cumulativeHistory button')).to_have_text('Восстановить')
        assert len(calls)==1
        assert page.evaluate('currentView===null&&contractRegister===null')
        expect(page.locator('#dashCard')).to_be_hidden()
        assert not errors


def test_removed_date_accepts_corrected_zip_but_restore_cannot_create_two_active_versions(sources,monkeypatch):
    folder,(_,old)=sources
    original={p.name:p.read_bytes() for p in folder.iterdir() if p.suffix in {'.zip','.json'}}
    monkeypatch.setattr(ledgers,'parse_archive',lambda *_:{'ledgers':[], 'summary_contracts':[],
                       'files':[],'warnings':[]})
    change(old['snapshot_id'])
    new=ledgers.store_archive(PROJECT,b'replacement for the same snapshot date',old['taken_at'],'Corrected.zip')
    assert new['snapshot_id']!=old['snapshot_id']
    assert ledgers.latest_snapshot(PROJECT)['snapshot_id']==new['snapshot_id']
    with pytest.raises(ledgers.LedgerConflict,match='действующий'):
        change(old['snapshot_id'],restore=True)
    change(new['snapshot_id']);change(old['snapshot_id'],restore=True)
    assert ledgers.latest_snapshot(PROJECT)['snapshot_id']==old['snapshot_id']
    assert all((folder/name).read_bytes()==raw for name,raw in original.items())


@pytest.mark.parametrize('family',['contracts','view','report'])
def test_native_cached_consumer_and_export_do_not_serve_deleted_generation(sources,monkeypatch,family):
    from fastapi.testclient import TestClient
    import main
    key='synthetic-removal-job-owner';monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',key)
    monkeypatch.setattr(main.core,'_monitor_cumulative_execute',lambda *_:{'ok':True,'register':{'rows':[]}})
    monkeypatch.setattr(monitor,'build',lambda *_a,**_k:{'project':PROJECT,'schedule':{'rows':[]}})
    monkeypatch.setattr(main.core,'_monitor_report_body',lambda *_a,**_k:{'report':{'project':PROJECT},'text':'saved','html':'saved'})
    paths={'contracts':('/monitor/contracts/build','/monitor/contracts/result',{'cut':'2026-02-01'}),
           'view':('/monitor/view','/monitor/view/result',{'cut':'2026-02-01','background':True}),
           'report':('/monitor/report/build','/monitor/report/result',{'end':'2026-02-01','kind':'week'})}
    start,poll,params=paths[family];client=TestClient(main.app)
    response=client.post(start,json=dict(params,key=key,project=PROJECT))
    assert response.status_code in (200,202),response.text
    ticket=response.json()['ticket'];limit=time.monotonic()+5
    while response.status_code==202 and time.monotonic()<limit:
        time.sleep(.01);response=client.post(poll,json={'key':key,'ticket':ticket})
    assert response.status_code==200,response.text
    change(sources[1][1]['snapshot_id'])
    response=client.post(poll,json={'key':key,'ticket':ticket})
    assert response.status_code==409 and response.headers['cache-control']=='private, no-store'
    if family=='contracts':
        assert client.post('/monitor/contracts/result-part',json={'key':key,'ticket':ticket,'offset':0}).status_code==409
        export=client.post('/monitor/contracts/comparison.xlsx',json={'key':key,'project':PROJECT,'cut':'2026-02-01',
            'contract_id':'a'*64,'revision':'c'*64,'selected_tokens':[],'ticket':ticket})
        assert export.status_code==409 and export.headers['cache-control']=='private, no-store'


def test_inventory_token_cannot_remove_same_snapshot_in_a_cloned_project(sources):
    folder,(_,new)=sources
    other='Другой клонированный проект';clone=ledgers._root(other,create=True)
    for path in folder.iterdir():
        if path.suffix in {'.json','.zip'}:(clone/path.name).write_bytes(path.read_bytes())
    token=ledgers.snapshot_inventory(PROJECT)['revision']
    assert ledgers.snapshot_inventory(other)['revision']!=token
    with pytest.raises(ledgers.LedgerConflict,match='Список'):
        ledgers.change_snapshot_activity(other,new['snapshot_id'],token)
    assert not (folder/ledgers._ACTIVITY_FILE).exists()
    assert not (clone/ledgers._ACTIVITY_FILE).exists()
    assert ledgers.latest_snapshot(PROJECT)['snapshot_id']==ledgers.latest_snapshot(other)['snapshot_id']==new['snapshot_id']
