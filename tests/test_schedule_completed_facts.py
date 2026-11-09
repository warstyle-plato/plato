"""Remaining plans never erase evidence or reassign a completed old cell ID."""
import copy
import datetime as dt
import hashlib
import json

import pytest

import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_schedule_versions as versions
import developaid_schedule_gpr_physical as physical
import developaid_schedule_completed_facts as completed
import developaid_report_schedule as reports
from test_monitor_management_gantt import _gpr_book
from test_schedule_physical import snapshot, item
from test_gpr_corpus_preview import book as corpus_book

PROJECT = 'Учебный остаточный план'
OLD_DAY, TODAY = '2026-11-08', '2026-11-09'


def book(name='Завершённый фасад', progress=.3, finish='2028-01-01'):
    return _gpr_book([(1, name, progress, dt.date(2026, 10, 1), dt.date.fromisoformat(finish),
                       'В работе', '2.2.1.1')])


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2026,11,9,12,tzinfo=dt.timezone.utc))
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026,11,8,12,tzinfo=dt.timezone.utc))
    source = book()
    monitor.store_schedule(PROJECT, source, None, '2026-11-01')
    snap = snapshot()
    monkeypatch.setattr(physical.ledgers, 'effective_snapshot', lambda *a, **k: copy.deepcopy(snap))
    return tmp_path, snap, source


def approve(data):
    preview = monitor.schedule_version_preview(PROJECT, data, TODAY)
    return monitor.approve_schedule_version(PROJECT, data, TODAY,
        expected_previous_sha256=preview['expected_previous_sha256'],
        expected_source_sha256=preview['source_sha256'])


def inventory():
    return physical.catalog(PROJECT, TODAY)['model']['completed_facts']


def confirm(mode='completed'):
    state = physical.catalog(PROJECT, OLD_DAY)
    config = {'tasks':[{'task_id':'1','mode':mode,'scope_confirmed':True,
                       'actual_finish':'2026-11-05' if mode=='completed' else ''}],
              'components':([] if mode=='completed' else
                  [{'task_id':'1','component_id':'Полный объём','item_ids':['0:0']}]),
              'note':'Проверены работа, участок и полный состав.'}
    return physical.save(PROJECT, **{k:state[k] for k in
        ('source_kind','source_sha256','snapshot_id','revision')}, configuration=config)


def test_omitted_finished_work_retains_its_identity_and_explicit_actual_date(site):
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],OLD_DAY)
    confirm()
    before = {str(p):p.read_bytes() for p in site[0].rglob('*.json')
              if 'work_fact' in str(p) or 'gpr_physical_links' in str(p)}
    old_rows = monitor.build(PROJECT, OLD_DAY)['schedule']['rows']
    approve(book('Оставшаяся кровля', .25, '2027-01-15'))
    view = monitor.build(PROJECT, TODAY)
    facts = view['schedule']['completed_facts']
    fact, = facts['qualified_task_completions']
    assert fact['name'] == 'Завершённый фасад' and fact['object'] == 'Корпус 1'
    assert fact['source_sha256'] == hashlib.sha256(site[2]).hexdigest()
    assert fact['actual_finish'] == '2026-11-05'
    assert view['schedule']['rows'][0]['name'] == 'Оставшаяся кровля'
    assert view['schedule']['rows'][0]['gpr_progress'] == .25
    assert view['schedule']['work_fact']['completed_facts'] == facts
    assert reports.model(view['schedule']['dependency_timeline'])['completed_facts'] == facts
    assert not any('plan' in key or 'forecast' in key for key in fact)
    assert facts['overall_progress'] is None
    assert monitor.build(PROJECT, OLD_DAY)['schedule']['rows'] == old_rows
    assert before == {str(p):p.read_bytes() for p in site[0].rglob('*.json')
                      if 'work_fact' in str(p) or 'gpr_physical_links' in str(p)}


def test_manual_100_is_a_dated_observation_not_a_finish_date(site):
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],OLD_DAY)
    approve(book('Оставшаяся кровля'))
    fact, = inventory()['qualified_task_completions']
    assert fact['observed_complete_by'] == OLD_DAY and fact['actual_finish'] is None
    assert '100% на дату '+OLD_DAY in completed.render(inventory())


@pytest.mark.parametrize('change',['no_fact','partial','reopened','unknown_id','future','foreign_source'])
def test_removed_or_unqualified_rows_never_become_completed_works(site, change):
    if change != 'no_fact':
        monitor.store_work_fact(PROJECT,[{'id':'1' if change!='unknown_id' else '99',
            'progress':.6 if change=='partial' else 1}], '2026-11-07')
        path = monitor._project_dir(PROJECT)/'work_fact'/'2026-11-07.json'
        if change=='reopened':
            monitor.store_work_fact(PROJECT,[{'id':'1','progress':.6}],OLD_DAY)
        elif change=='foreign_source':
            record=json.loads(path.read_text());record['source_sha256']='f'*64
            path.write_text(json.dumps(record))
        elif change=='future':
            path.rename(path.with_name('2026-11-10.json'))
    approve(book('Оставшаяся кровля'))
    assert inventory()['qualified_task_completions'] == []


def test_raw_old_plan_100_is_not_confirmed_completion(site):
    # Replace only before a new version exists, to construct an immutable old
    # source that says100. No confirmed fact is stored.
    monitor._baseline_file(PROJECT).write_bytes(book(progress=1))
    approve(book('Оставшаяся кровля'))
    assert inventory()['qualified_task_completions'] == []


@pytest.mark.parametrize('origin',['before_revision','after_revision'])
def test_unbound_legacy_fact_requires_proved_revision_zero_on_its_date(site, origin):
    if origin=='before_revision':
        monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],OLD_DAY)
        path=monitor._project_dir(PROJECT)/'work_fact'/(OLD_DAY+'.json')
        record=json.loads(path.read_text());record.pop('source_sha256');path.write_text(json.dumps(record))
    approve(book('Оставшаяся кровля'))
    if origin=='after_revision':
        folder=monitor._project_dir(PROJECT)/'work_fact';folder.mkdir(exist_ok=True)
        (folder/(TODAY+'.json')).write_text(json.dumps({'rows':[{'id':'1','progress':1}]}))
    assert len(inventory()['qualified_task_completions']) == (origin=='before_revision')


def test_explicit_revocation_does_not_revive_an_older_completion(site):
    saved=confirm()
    physical.save(PROJECT, **{k:saved[k] for k in
        ('source_kind','source_sha256','snapshot_id','revision')},
        configuration={'tasks':[],'components':[],'note':'Подтверждение снято.'})
    approve(book('Оставшаяся кровля'))
    assert inventory()['qualified_task_completions'] == []


def test_ks_full_quantity_has_no_invented_actual_finish(site):
    row=site[1]['ledgers'][0]['items'][0]
    row.update(completed_quantity=100,periods=[])
    confirm('quantities')
    approve(book('Оставшаяся кровля'))
    facts=inventory();work,=facts['qualified_task_completions']
    assert work['actual_finish'] is None and work['observed_complete_by']=='2026-11-06'
    assert facts['counts']['ks_positions']==1
    assert facts['completed_ks_positions'][0]['scope_kind']=='ks_position'


@pytest.mark.parametrize('change',['full','money_only','partial','unitless','unverified_copy'])
def test_completed_source_positions_are_not_whole_gpr_work_markers(site,change):
    row=site[1]['ledgers'][0]['items'][0]
    row.update(completed_quantity=100,periods=[])
    if change=='money_only':row.update(plan_quantity=None,completed_quantity=None,planned_amount=1000,completed_amount=1000)
    elif change=='partial':row['completed_quantity']=50
    elif change=='unitless':row['unit']=''
    elif change=='unverified_copy':row['is_duplicate']=True
    facts=inventory()
    assert facts['qualified_task_completions']==[]
    assert facts['counts']['ks_positions'] == (change=='full')
    assert facts['overall_progress'] is None
    assert 'class="completed-work-marker"' not in completed.render(facts)


def test_selected_approved_corpus_takes_priority_over_an_archived_upload(site):
    import developaid_gpr_corpus as corpus
    name='Другой корпусный проект'
    old,new=corpus_book(name='Архивный фасад'),corpus_book(name='Текущая кровля')
    monitor.store_schedule(name,old,None,'2026-11-06')
    corpus.store(name,old,'2026-11-06',corpus.read(old))
    preview=monitor.schedule_version_preview(name,new,TODAY)
    monitor.approve_schedule_version(name,new,TODAY,
        expected_previous_sha256=preview['expected_previous_sha256'],expected_source_sha256=preview['source_sha256'])
    value=corpus.for_view(name,TODAY,baseline_sha256=hashlib.sha256(new).hexdigest())
    assert value['baseline_approved'] and value['sha256']==hashlib.sha256(new).hexdigest()
    assert corpus.latest(name,TODAY)['sha256']==hashlib.sha256(old).hexdigest()
    assert corpus.for_view(name,OLD_DAY,baseline_sha256=hashlib.sha256(old).hexdigest())['sha256']==hashlib.sha256(old).hexdigest()
