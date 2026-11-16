"""The1050 native status population survives passive acquisition observation."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest
from market_search import krt_registry as source
from market_search import krt_catalogue_observation as obs
from auction_search.krt_status import model_exclusion

OLD='8139471534871b4f5142d389e4ed21f0fede7f98'
ROOT=Path(__file__).resolve().parents[1]


def native1050():
    name='market_search._native1050_policy';module=importlib.util.module_from_spec(importlib.util.spec_from_loader(name,loader=None));sys.modules[name]=module
    raw=subprocess.check_output(['git','show',OLD+':market_search/krt_registry.py'],cwd=ROOT)
    exec(compile(raw,'exact8139nativepolicy','exec'),module.__dict__)
    return module


def run_policy(module,root,mode,monkeypatch,observation):
    calls=[];writes=[];saved=module.save_json
    def row(status):return module.KrtTerritory(slug='running',name='Synthetic status',url='https://example.test/running',status=status)
    def direct(text):
        if text=='p':return [row('Планируемый')],None if mode in {'planned_after_running','renderer_conflict'}else'https://example.test/page2'
        if text=='r':return [row('В реализации')],None
        return [row('Нераспознанное значение')],None
    def renderer(text):
        # Preserve native repeated-slug-page termination; both source statuses
        # coexist on a returned page and must reach unseen before repetition.
        return [row('Планируемый'),row('В реализации')]
    def fetch(url):
        calls.append(url)
        rendered=url.startswith(module.JINA_PREFIX);second='PAGEN_1=2'in url or url.endswith('page2')
        if mode=='prior_retained':raise OSError('synthetic failure')
        if rendered:return b'p'if not second and 'PAGEN_1=3'not in url else b'r'
        if mode=='renderer_conflict'or mode=='mixed_partial'and second:raise OSError('synthetic failure')
        return b'u'if mode=='unknown_after_running'else b'r'if second else b'p'
    def record(path,payload,**kw):
        result=saved(path,payload,**kw);writes.append(Path(path).read_bytes());return result
    with monkeypatch.context()as patch:
        patch.setattr(module,'parse_catalogue',direct);patch.setattr(module,'parse_catalogue_markdown',renderer)
        patch.setattr(module.time,'time',lambda:1700000000)
        patch.setattr(module,'save_json',record)
        if observation=='off':patch.setattr(obs,'start',lambda *a:None)
        if observation=='fault':patch.setattr(obs.Walk,'receipt',lambda *a:(_ for _ in ()).throw(ValueError('synthetic observer fault')))
        store=module.KrtRegistry(root,fetch=fetch)
        if mode in {'unknown_after_running','planned_after_running','prior_retained'}:
            original=module.parse_catalogue
            patch.setattr(module,'parse_catalogue',lambda text:([row('В реализации')],None))
            store.fetch=lambda url:b'r';store.projects(refresh=True)
            patch.setattr(module,'parse_catalogue',original);store.fetch=fetch
        calls.clear();writes.clear()
        rows=store.projects(refresh=True,max_pages=3)
    return store,calls,writes,[row.to_dict()for row in rows]


@pytest.mark.parametrize('mode',['official_conflict','renderer_conflict','mixed_partial','unknown_after_running','planned_after_running','prior_retained'])
def test_native1050_policy_calls_and_every_saved_byte_equal_observer_off_on_and_fault(monkeypatch,tmp_path,mode):
    _,calls,writes,rows=run_policy(native1050(),tmp_path/'stock',mode,monkeypatch,'off')
    for observing in ['off','on','fault']:
        store,actual_calls,actual_writes,actual_rows=run_policy(source,tmp_path/observing,mode,monkeypatch,observing)
        assert(actual_calls,actual_writes,actual_rows)==(calls,writes,rows)
        if 'conflict'in mode or mode=='mixed_partial':
            assert len(actual_rows)==2 and {r['status']for r in actual_rows}=={'Планируемый','В реализации'}
            assert all(r['model_status_conflict']and model_exclusion(r)for r in actual_rows)
        else:
            assert len(actual_rows)==1
            assert bool(model_exclusion(actual_rows[0]))is(mode!='planned_after_running')
        if observing=='on':
            view=obs.read_view(store.path.parent);assert view['state']=='present'
            data=view['diagnostic'];receipt=data['latest_attempt'];result=receipt['walk_result']
            assert receipt['HTTP_attempts_seen']is None
            if mode=='prior_retained':assert not result['catalogue_written']and result['prior_catalogue_retained']
            else:
                assert result['catalogue_written']
                assert result['direct_rows_added']+result['renderer_rows_added']==len(actual_rows)
                assert data['current_catalogue_binding']['written_payload_sha256']==hashlib.sha256(store.path.read_bytes()).hexdigest()
            assert view['current_catalogue_binding_check']=='stat_identity_matches'


def test_a_current_complete_cache_hit_does_not_start_observation_or_fetch(monkeypatch,tmp_path):
    store,_,_,rows=run_policy(source,tmp_path,'official_conflict',monkeypatch,'on')
    raw=(store.path.parent/obs.NAME).read_bytes();catalogue=store.path.read_bytes()
    monkeypatch.setattr(source,'fresh',lambda *a:True)
    monkeypatch.setattr(obs,'start',lambda *a:pytest.fail('cachehit created acquisition'))
    store.fetch=lambda *a:pytest.fail('cachehit fetched')
    assert[r.to_dict()for r in store.projects()]==rows
    assert(store.path.parent/obs.NAME).read_bytes()==raw and store.path.read_bytes()==catalogue


@pytest.mark.parametrize('state',['running','unknown_after_running','conflict'])
def test_native_composed_weekly_path_visits_market_but_never_restamps_financial_state(monkeypatch,tmp_path,state):
    from test_running_krt_models_are_excluded import RUNNING,PLANNED,UNKNOWN_RUNNING,_app,_keep_old_model,_synchronous_worker,_one_pass
    projects=[dict(UNKNOWN_RUNNING)]if state=='unknown_after_running'else[dict(RUNNING)]
    if state=='conflict':projects.insert(0,dict(PLANNED,slug='running'))
    before=copy.deepcopy(projects)
    _,ranking,loops,models,markets,requirements=_app(tmp_path,monkeypatch,projects)
    old=_keep_old_model(ranking)
    monkeypatch.setattr(ranking,'due',lambda *a:True)
    _synchronous_worker(monkeypatch,ranking);_one_pass(monkeypatch,loops['krt-weekly'])
    assert not models and not requirements and len(markets)==1
    assert ranking.report_path('running').read_bytes()==old
    row=ranking.stored_row('running')
    assert row['computed_at']==100 and row['investment_rating']['score']==77 and row['entry_capacity_mln']==123
    assert ranking.progress()['done']==1 and ranking.progress()['model_skipped']==1
    assert projects==before
