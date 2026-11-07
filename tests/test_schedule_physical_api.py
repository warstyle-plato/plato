"""Private mapping journal: current key before lookup, source revisions and history."""
import copy
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_monitor as monitor
import developaid_schedule_physical as physical
import developaid_monitor_schedule_graph as graph
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_api import api, post, KEY
from test_schedule_dependency_timeline import network
from test_schedule_physical import CUT, config, snapshot


@pytest.fixture
def sources(api, monkeypatch):
    client, root = api
    pm = dict(network(), source_sha256='a'*64)
    snap = snapshot()
    monkeypatch.setattr(graph, '_load_pm', lambda project: copy.deepcopy(pm))
    monkeypatch.setattr(ledgers, 'latest_snapshot', lambda project, cut='': copy.deepcopy(snap))
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc))
    return client, root, pm, snap


def payload(**changes):
    result = dict(project='Учебный проект', pm_sha256='a'*64,
                  snapshot_id=CUT+'-'+'b'*64, revision=0, configuration=config())
    result.update(changes)
    return result


@pytest.mark.parametrize('path', ['view', 'save'])
@pytest.mark.parametrize('key,session', [('', ''), ('bad', ''), ('', 'telegram'), ('', 'demo')])
def test_authentication_precedes_private_lookup_and_mutation(api, monkeypatch, path, key, session):
    client, _ = api
    monkeypatch.setattr(physical,'catalog',lambda *a,**kw: pytest.fail('lookup before admission'))
    monkeypatch.setattr(physical,'save',lambda *a,**kw: pytest.fail('mutation before admission'))
    r=post(client,'schedule-physical/'+path,key=key,session=session,**payload())
    assert r.status_code==403 and r.headers['cache-control']=='private, no-store'


def test_save_reload_historical_cut_and_explicit_revocation(sources):
    client, root, _, _=sources
    r=post(client,'schedule-physical/save',**payload())
    assert r.status_code==200 and r.json()['revision']==1
    assert r.json()['model']['state']=='complete'
    historical=post(client,'schedule-physical/view',project='Учебный проект',cut='2026-11-05').json()
    assert historical['configuration']['tasks']==[] and not historical['can_edit']
    revoke=config();revoke.update(tasks=[],components=[],note='Привязки сняты после проверки.')
    r=post(client,'schedule-physical/save',**payload(revision=1,configuration=revoke))
    assert r.status_code==200 and not r.json()['model']['physical_evidence']
    assert post(client,'schedule-physical/view',project='Учебный проект',cut=CUT).json()['configuration']['tasks']==[]
    files=list(root.rglob('physical_schedule_links/*.json'))
    assert len(files)==2 and all(KEY not in f.read_text() for f in files)
    assert all(f.stat().st_mode&0o777==0o600 for f in files)


@pytest.mark.parametrize('change', [dict(pm_sha256='c'*64),dict(snapshot_id=CUT+'-'+'c'*64),dict(revision=1)])
def test_stale_source_or_editor_cannot_save(sources,change):
    client,root,_,_=sources
    r=post(client,'schedule-physical/save',**payload(**change))
    assert r.status_code==409 and not list(root.rglob('physical_schedule_links/*.json'))


def test_source_replacement_and_project_isolation(sources):
    client,_,pm,snap=sources
    assert post(client,'schedule-physical/save',**payload()).status_code==200
    assert post(client,'schedule-physical/view',project='Другой проект',cut=CUT).json()['configuration']['tasks']==[]
    pm['source_sha256']='c'*64
    state=post(client,'schedule-physical/view',project='Учебный проект',cut=CUT).json()
    assert state['source_changed'] and not state['model']['physical_evidence']
    pm['source_sha256']='a'*64;snap['snapshot_id']=CUT+'-'+'d'*64
    state=post(client,'schedule-physical/view',project='Учебный проект',cut=CUT).json()
    assert state['source_changed'] and not state['model']['physical_evidence']


def test_physical_mapping_reads_the_same_archive_as_the_contract_register(api, monkeypatch):
    """Clarified header dates and re-read parties must reach the mapping too."""
    import developaid_monitor_contracts as contracts
    from test_cumulative_header_date_confirmations import stored, fields
    snapshot = stored('Fixture')
    today = dt.date.today().isoformat()
    contracts.confirm_header_date('Fixture', today, **fields(snapshot))
    monkeypatch.setattr(graph, '_load_pm', lambda project: dict(network(), source_sha256='a'*64))
    row, = contracts.build('Fixture', today)['rows']
    catalog = physical.catalog('Fixture', today)
    assert catalog['snapshot_id'] == snapshot['snapshot_id'] and catalog['items']
    assert {(x['contractor'], x['contract'], x['contract_date']) for x in catalog['items']} == {
        (row['contractor'], row['contract'], '2024-07-03')}

def test_only_one_process_shared_revision_can_commit(sources):
    _,root,_,_=sources
    def save():
        try:
            return physical.save('Учебный проект','a'*64,CUT+'-'+'b'*64,0,config())['revision']
        except physical.PhysicalProblem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=6) as pool: outcomes=list(pool.map(lambda _:save(),range(6)))
    assert outcomes.count(1)==1 and outcomes.count(409)==5
    assert len(list(root.rglob('physical_schedule_links/*.json')))==1


def test_corrupt_history_fails_closed_without_disclosing_data(sources, caplog):
    client,root,_,_=sources
    assert post(client,'schedule-physical/save',**payload()).status_code==200
    event=next(root.rglob('physical_schedule_links/*.json'))
    event.write_text('PRIVATE-CUSTOMER-PATH')
    r=post(client,'schedule-physical/view',project='Учебный проект',cut=CUT)
    assert r.status_code==503
    assert 'PRIVATE-CUSTOMER-PATH' not in r.text+caplog.text
    got=physical.build('Учебный проект',CUT,dict(network(),source_sha256='a'*64))
    assert got['state']=='unknown' and not got['seeds']


@pytest.mark.parametrize('change', [dict(revision=True),dict(pm_sha256='bad')])
def test_invalid_input_does_not_change_history(sources,change):
    client,root,_,_=sources
    r=post(client,'schedule-physical/save',**payload(**change))
    assert r.status_code==422 and r.headers['cache-control']=='private, no-store'
    assert not list(root.rglob('physical_schedule_links/*.json'))


def test_rotation_unset_gate_and_method_are_private(sources,monkeypatch):
    client,_,_,_=sources
    assert post(client,'schedule-physical/save',**payload()).status_code==200
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','rotated-synthetic')
    assert post(client,'schedule-physical/view',project='Учебный проект',cut=CUT).status_code==403
    assert post(client,'schedule-physical/view',key='rotated-synthetic',project='Учебный проект',cut=CUT).status_code==200
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','')
    r=post(client,'schedule-physical/view',key='rotated-synthetic',project='Учебный проект',cut=CUT)
    assert r.status_code==403
    r=client.get('/monitor/schedule-physical/view')
    assert r.status_code==405 and r.headers['cache-control']=='private, no-store'


def test_manual_future_completion_or_foreign_rows_cannot_be_saved(sources):
    client,_,_,_=sources
    cfg=config();cfg['tasks'][1].update(mode='completed',actual_finish='2026-11-07')
    assert post(client,'schedule-physical/save',**payload(configuration=cfg)).status_code==400
    cfg=config();cfg['components'][0]['item_ids']=['9:9']
    assert post(client,'schedule-physical/save',**payload(configuration=cfg)).status_code==409


def test_catalog_search_pagination_and_markup_remain_data(sources):
    client,_,_,snap=sources
    snap['ledgers'][0]['items']=snap['ledgers'][0]['items']*205
    snap['ledgers'][0]['items'][0]['name']='<img src=x onerror=alert(1)>'
    first=post(client,'schedule-physical/view',project='Учебный проект',cut=CUT).json()
    second=post(client,'schedule-physical/view',project='Учебный проект',cut=CUT,offset=200).json()
    assert len(first['items'])==200 and len(second['items'])==5 and first['item_count']==205
    assert first['items'][0]['name'].startswith('<img')
    found=post(client,'schedule-physical/view',project='Учебный проект',cut=CUT,query='not-present').json()
    assert found['items']==[]


def test_separate_workers_cannot_commit_the_same_revision(sources):
    import subprocess
    import sys
    from pathlib import Path
    _, root, _, _=sources
    code='''
import sys, datetime as dt
from pathlib import Path
import developaid_monitor as monitor
import developaid_schedule_physical as physical
from test_schedule_physical import config,snapshot,CUT
from test_schedule_dependency_timeline import network
monitor._SNAPSHOT_DIR=Path(sys.argv[1])/'monitor'
physical.graph._load_pm=lambda _:dict(network(),source_sha256='a'*64)
import developaid_monitor_ledgers as ledgers
ledgers.latest_snapshot=lambda *a: snapshot()
physical._now=lambda:dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc)
try:
    physical.save('Учебный проект','a'*64,CUT+'-'+'b'*64,0,config())
    print('saved')
except physical.PhysicalProblem as error:
    assert error.status==409
    print('conflict')
'''
    project=Path(__file__).resolve().parents[1]
    import os
    env={**os.environ,'PYTHONPATH':str(project)+os.pathsep+str(project/'tests')}
    def run():
        return subprocess.run([sys.executable,'-c',code,str(root)],cwd=project,env=env,
                              capture_output=True,text=True,check=True,timeout=40).stdout.strip()
    with ThreadPoolExecutor(max_workers=4) as pool: outcomes=list(pool.map(lambda _:run(),range(4)))
    assert outcomes.count('saved')==1 and outcomes.count('conflict')==3
    assert len(list(root.rglob('physical_schedule_links/*.json')))==1
