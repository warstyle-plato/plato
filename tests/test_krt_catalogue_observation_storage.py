"""Closed, bounded sidecar snapshots; no catalogue-body or source reader."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import threading
from types import ModuleType

import pytest

from market_search import http
from market_search import krt_registry as registry
from market_search import krt_catalogue_observation as obs
from test_krt_catalogue_observation import SECRET, html, markdown, read_receipt, baseline


def saved(tmp_path):
    store=registry.KrtRegistry(tmp_path,fetch=lambda url:html())
    store.projects(refresh=True)
    view,_=read_receipt(store)
    return store,view['diagnostic']


def test_saved_receipt_hashes_the_actual_same_json_dump_fragments_and_keeps_return_semantics(tmp_path):
    old,_=baseline('http')
    payload={'unicode':'Привет 🌳','array':[1,2.25,None,False],'nested':{'b':'x','a':3}}
    first=tmp_path/'ordinary.json';second=tmp_path/'observed.json';receipt={}
    assert old.save_json(first,payload) is None
    assert http.save_json(second,payload,_saved_receipt=receipt) is None
    assert receipt.pop('_replaced') is True
    assert second.read_bytes()==first.read_bytes()
    info=second.stat()
    assert receipt=={'written_payload_sha256':hashlib.sha256(first.read_bytes()).hexdigest(),
        'written_bytes':len(first.read_bytes()),'inode':info.st_ino,'mtime_ns':info.st_mtime_ns}


@pytest.mark.parametrize('diagnostic_fault',['hash_constructor','fstat'])
def test_optional_write_receipt_fault_does_not_change_catalogue_write(monkeypatch,tmp_path,diagnostic_fault):
    expected=tmp_path/'base.json';actual=tmp_path/'observed.json';payload={'x':'точные байты'}
    http.save_json(expected,payload)
    if diagnostic_fault=='hash_constructor':
        monkeypatch.setattr(http,'_HashingJSONWriter',lambda *a:(_ for _ in ()).throw(OSError(SECRET)))
    else:
        original=http.os.fstat
        def diagnostic_only(fd):
            if inspect.currentframe().f_back.f_code.co_name=='_save_json_observed':raise OSError(SECRET)
            return original(fd)
        monkeypatch.setattr(http.os,'fstat',diagnostic_only)
    receipt={};assert http.save_json(actual,payload,_saved_receipt=receipt) is None
    assert actual.read_bytes()==expected.read_bytes() and receipt=={'_replaced':True}


def test_native_write_failure_still_raises_and_retains_previous_file(tmp_path):
    for observed in (False,True):
        path=tmp_path/str(observed)/'catalogue.json';http.save_json(path,{'old':'kept'})
        before=path.read_bytes();receipt={}
        with pytest.raises(TypeError):http.save_json(path,{'bad':object()},**({'_saved_receipt':receipt} if observed else {}))
        assert path.read_bytes()==before and receipt=={}
        assert list(path.parent.glob('*.tmp'))==[]


def test_replaced_catalogue_is_bound_even_if_original_temp_cleanup_then_raises(monkeypatch,tmp_path):
    original=Path.unlink
    def cleanup(path,*a,**k):
        if path.name.startswith('.catalogue.json.') and path.name.endswith('.tmp'):
            raise OSError(SECRET)
        return original(path,*a,**k)
    monkeypatch.setattr(Path,'unlink',cleanup)
    store=registry.KrtRegistry(tmp_path,fetch=lambda url:html())
    with pytest.raises(OSError):store.projects(refresh=True,max_pages=1)
    view,receipt=read_receipt(store)
    assert receipt['walk_result']['catalogue_written'] is True
    assert view['current_catalogue_binding_check']=='stat_identity_matches'
    assert view['diagnostic']['current_catalogue_binding']['written_payload_sha256']==hashlib.sha256(store.path.read_bytes()).hexdigest()


def test_last_attempt_timeout_does_not_reuse_earlier_returned_HTTP_status(monkeypatch,tmp_path):
    calls=0
    class Broken:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def geturl(self):return registry.CATALOGUE_URL
        def read(self):raise TimeoutError(SECRET)
    def opener(*a,**k):
        nonlocal calls
        calls+=1
        if calls==1:return Broken()
        raise TimeoutError(SECRET)
    monkeypatch.setattr(http,'_trust_context',lambda:None)
    monkeypatch.setattr(http,'urlopen',opener);monkeypatch.setattr(http.time,'sleep',lambda *a:None)
    store=registry.KrtRegistry(tmp_path);store.projects(refresh=True,max_pages=1)
    _,receipt=read_receipt(store)
    assert receipt['page_receipts'][0][3] is None
    assert receipt['last_failure_phases']['phases']['HTTP']=='not_observed'


def test_no_observation_or_sidecar_write_on_a_normal_cache_hit(monkeypatch,tmp_path):
    store,_=saved(tmp_path);before=(store.path.parent/obs.NAME).read_bytes()
    monkeypatch.setattr(obs,'start',lambda *a:pytest.fail('cache hit started a walk'))
    store.fetch=lambda url:pytest.fail('cache hit fetched source')
    assert store.projects() and (store.path.parent/obs.NAME).read_bytes()==before


def test_unexpected_parser_failure_propagates_and_finally_keeps_typed_parse_failure(monkeypatch,tmp_path):
    error=ValueError(SECRET)
    monkeypatch.setattr(registry,'parse_catalogue',lambda *a:(_ for _ in ()).throw(error))
    store=registry.KrtRegistry(tmp_path,fetch=lambda url:html())
    with pytest.raises(ValueError) as raised:store.projects(refresh=True)
    assert raised.value is error and obs.current_fetch() is None
    _,receipt=read_receipt(store)
    assert receipt['state']=='finished' and receipt['page_receipts'][0][9:] == ['failed',None,None]
    assert receipt['last_failure_phases']['phases']['parse']=='failed'
    assert receipt['failure_samples'][-1]['kind']=='parse_error'


def test_two_threads_keep_fetch_context_and_receipt_sources_separate(tmp_path):
    barrier=threading.Barrier(2)
    def run(index):
        walk=obs.Walk(tmp_path/str(index)/'catalogue.json',False)
        with obs.fetch_scope(walk,'official' if index==1 else 'renderer',index) as fetch:
            barrier.wait(timeout=5)
            assert obs.current_fetch() is fetch
            fetch.decoded();fetch.parsed(index);fetch.contributed(index)
        assert obs.current_fetch() is None
        return walk.receipt(True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first,second=list(pool.map(run,(1,2)))
    assert first['page_receipts'][0][0]=='official' and second['page_receipts'][0][0]=='renderer'
    assert first['walk_result']['direct_rows_added']==1 and second['walk_result']['renderer_rows_added']==2


def test_disabled_nested_walk_does_not_reuse_an_outer_fetch_observer(tmp_path):
    walk=obs.Walk(tmp_path/'catalogue.json',False)
    with obs.fetch_scope(walk,'official',1) as outer:
        with obs.fetch_scope(None,'renderer',1):assert obs.current_fetch() is None
        assert obs.current_fetch() is outer
    assert obs.current_fetch() is None


def test_failed_started_diagnostic_is_retained_as_closed_IO_gap_if_final_write_succeeds(monkeypatch,tmp_path):
    original=obs.write_envelope;calls=0
    def write(*args):
        nonlocal calls
        calls+=1
        return False if calls==1 else original(*args)
    monkeypatch.setattr(obs,'write_envelope',write)
    store=registry.KrtRegistry(tmp_path,fetch=lambda url:html());assert store.projects(refresh=True)
    view,receipt=read_receipt(store)
    assert calls==2 and view['current_catalogue_binding_check']=='stat_identity_matches'
    assert receipt['failure_samples'][0]['boundary']=='diagnostic_IO'
    assert receipt['failure_samples'][0]['fetch_ordinal']==0


def test_diagnostic_write_failure_never_rolls_back_new_business_catalogue_or_fakes_binding(monkeypatch,tmp_path):
    store,_=saved(tmp_path);sidecar=(store.path.parent/obs.NAME).read_bytes()
    store.fetch=lambda url:html('different-generation')
    monkeypatch.setattr(obs,'write_envelope',lambda *a:False)
    rows=store.projects(refresh=True)
    assert rows[0].slug=='different-generation'
    assert (store.path.parent/obs.NAME).read_bytes()==sidecar
    assert obs.read_view(store.path.parent)['current_catalogue_binding_check']=='mismatch'


def test_partial_new_rows_cannot_replace_retained_complete_generation(tmp_path):
    store,old=saved(tmp_path);before=store.path.read_bytes()
    def fetch(url):
        if url==registry.CATALOGUE_URL:return html('new-partial','/projects/?PAGEN_1=2')
        raise OSError(SECRET)
    store.fetch=fetch;rows=store.projects(refresh=True,max_pages=2)
    assert [row.slug for row in rows]==['new-partial'] and store.path.read_bytes()==before
    view,receipt=read_receipt(store)
    assert view['diagnostic']['current_catalogue_acquisition']==old['current_catalogue_acquisition']
    assert receipt['walk_result']['prior_catalogue_retained'] and not receipt['walk_result']['catalogue_written']


def test_detail_capping_preserves_all_fetch_counts_and_failure_chain_after_omission(monkeypatch,tmp_path):
    monkeypatch.setattr(obs.time,'monotonic',lambda:10.0)
    walk=obs.Walk(tmp_path/'catalogue.json',False)
    for index in range(210):
        with obs.fetch_scope(walk,'official',index+1) as fetch:
            fetch.context_start();fetch.attempt_start(1)
            fetch.failure(TimeoutError(SECRET),'open_response')
    receipt=walk.receipt(True)
    assert receipt['fetches_seen']==210 and receipt['HTTP_attempts_seen']==210
    assert len(receipt['page_receipts'])==200 and len(receipt['failure_samples'])==8
    assert receipt['details_omitted']==212 and receipt['detail_truncated']
    assert not receipt['numeric_overflow']
    before=receipt['metadata_chain_sha256']
    with obs.fetch_scope(walk,'official',211) as fetch:
        fetch.context_start();fetch.attempt_start(1);fetch.failure(ConnectionRefusedError(),'open_response')
    assert walk.receipt(True)['metadata_chain_sha256']!=before
    # A smaller metadata-only cap exercises compaction without changing a
    # fetch count, budget, source request, receipt chain or business write.
    envelope={'schema':obs.ENVELOPE,'scope':obs.SCOPE,'current_catalogue_acquisition':None,
        'latest_attempt':walk.receipt(True),'current_catalogue_binding':obs._binding()}
    chain=envelope['latest_attempt']['metadata_chain_sha256']
    monkeypatch.setattr(obs,'LIMIT',4096)
    assert obs.write_envelope(tmp_path,envelope)
    raw=(tmp_path/obs.NAME).read_bytes();assert len(raw)<=4096
    parsed=json.loads(raw);assert obs.validate(parsed)
    assert parsed['latest_attempt']['metadata_chain_sha256']==chain
    assert parsed['latest_attempt']['fetches_seen']==211
    assert parsed['latest_attempt']['details_omitted']>receipt['details_omitted']


def test_numeric_overflow_is_explicit_unknown_not_zero(tmp_path):
    walk=obs.Walk(tmp_path/'catalogue.json',False)
    walk.fetches=obs.I32+1;walk.attempts=obs.I32+2;walk.omitted=obs.I32+3
    receipt=walk.receipt(True)
    assert receipt['numeric_overflow'] and receipt['detail_truncated']
    assert all(receipt[key] is None for key in ('fetches_seen','HTTP_attempts_seen','details_omitted'))
    assert receipt['walk_result']['direct_rows_added'] is None
    assert receipt['walk_result']['renderer_rows_added'] is None
    assert obs.write_envelope(tmp_path,{'schema':obs.ENVELOPE,'scope':obs.SCOPE,
        'current_catalogue_acquisition':None,'latest_attempt':receipt,'current_catalogue_binding':obs._binding()})


@pytest.mark.parametrize('mutate',[lambda value:value.update(extra=SECRET),
    lambda value:value['latest_attempt'].update(fetches_seen=True),
    lambda value:value['latest_attempt']['last_failure_phases']['phases'].update(extra='failed'),
    lambda value:value['latest_attempt']['walk_result'].update(source_updated_at='2026-11-15'),
    lambda value:value['current_catalogue_binding'].update(acquisition_receipt_sha256='a'*64),
    lambda value:value['latest_attempt'].update(acquisition_runtime={'commit':'a'*40,'version':SECRET}),
    lambda value:value['current_catalogue_binding'].update(inode=-1)])
def test_closed_reader_refuses_unknown_fields_types_runtime_or_self_hash_mutations(tmp_path,mutate):
    store,value=saved(tmp_path);mutate(value)
    (store.path.parent/obs.NAME).write_bytes(obs.canonical(value))
    view=obs.read_view(store.path.parent)
    assert view['state']=='corrupt' and view['diagnostic'] is None
    assert SECRET not in json.dumps(view)


@pytest.mark.parametrize('body',[b'{}',b'{"schema":1,"schema":2}',b'{"schema":NaN}',b'x'*(obs.LIMIT+1)])
def test_malformed_duplicate_nonfinite_or_oversize_diagnostic_is_never_projected(tmp_path,body):
    tmp_path.mkdir(exist_ok=True);(tmp_path/obs.NAME).write_bytes(body)
    result=obs.read_view(tmp_path)
    assert result['state']=='corrupt' and result['diagnostic'] is None


@pytest.mark.parametrize('unsafe',['symlink','hardlink','directory'])
def test_unsafe_diagnostic_file_is_refused_without_following_or_reading(tmp_path,unsafe):
    root=tmp_path/'krt';root.mkdir();target=tmp_path/'private';target.write_bytes(b'private')
    path=root/obs.NAME
    if unsafe=='symlink':path.symlink_to(target)
    elif unsafe=='hardlink':os.link(target,path)
    else:path.mkdir()
    assert obs.read_view(root)['state']=='corrupt'
    assert target.read_bytes()==b'private'


def test_reader_double_pass_budget_only_reads_fixed_diagnostic_and_catalogue_stat(monkeypatch,tmp_path):
    store,_=saved(tmp_path)
    old_open,old_read=obs.os.open,obs.os.read;read_bytes=0;opened=[]
    def opening(path,*a,**k):
        opened.append(str(path))
        assert str(path)!='catalogue.json','reader opened catalogue payload'
        return old_open(path,*a,**k)
    def reading(fd,size):
        nonlocal read_bytes
        assert size<=obs.LIMIT
        body=old_read(fd,size);read_bytes+=len(body);return body
    monkeypatch.setattr(obs.os,'open',opening);monkeypatch.setattr(obs.os,'read',reading)
    view=obs.read_view(store.path.parent)
    assert view['state']=='present' and opened.count(obs.NAME)==2
    assert read_bytes==2*(store.path.parent/obs.NAME).stat().st_size<=2*obs.LIMIT


@pytest.mark.parametrize('change',['replace','remove'])
def test_changed_between_double_reads_fails_closed(monkeypatch,tmp_path,change):
    store,_=saved(tmp_path);original=obs._read_pass;calls=0
    def read(directory):
        nonlocal calls
        result=original(directory);calls+=1
        if calls==1:
            path=store.path.parent/obs.NAME
            if change=='replace':
                replacement=path.with_suffix('.replacement');replacement.write_bytes(path.read_bytes());replacement.replace(path)
            else:path.unlink()
        return result
    monkeypatch.setattr(obs,'_read_pass',read)
    result=obs.read_view(store.path.parent)
    assert result['state']=='changed_during_read' and result['diagnostic'] is None


def test_catalogue_stat_mismatch_and_missing_are_explicit_and_never_rehashed(tmp_path):
    store,_=saved(tmp_path)
    store.path.write_bytes(b'different catalogue bytes')
    assert obs.read_view(store.path.parent)['current_catalogue_binding_check']=='mismatch'
    store.path.unlink()
    assert obs.read_view(store.path.parent)['current_catalogue_binding_check']=='missing'


def test_runtime_only_uses_already_loaded_attributes_and_invalid_values_are_null():
    module=ModuleType('loaded');module.VERSION='0.29.63';module.COMMIT='a'*40
    assert obs.runtime({'developaid_core':module})=={'commit':'a'*40,'version':'0.29.63'}
    module.VERSION=SECRET;module.COMMIT=True
    assert obs.runtime({'developaid_core':module})=={'commit':None,'version':None}
