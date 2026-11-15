"""Synthetic persisted JSON only: no workbook, original source or production state."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import developaid_contract_prepared_index as proof
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers

PROJECT = 'Synthetic cache index'
CUT = '2036-08-19'


def row(number, *, group=False):
    return dict(source=dict(filename='Synthetic.xlsx', sheet='Synthetic', row=number),
        position=str(number), name='Synthetic row', unit='', plan_quantity=0,
        completed_quantity=None, is_group=group, periods=[],
        planned_amount_basis='unspecified', completed_amount_basis='unspecified')


def snapshot(day):
    archive_sha = hashlib.sha256(('synthetic archive ' + day).encode()).hexdigest()
    file_sha = hashlib.sha256(('synthetic book ' + day).encode()).hexdigest()
    ledger = dict(source=dict(filename='Synthetic.xlsx', sheet='Synthetic', row=2),
        file_sha256=file_sha, identity_source={}, party_evidence={}, period_year=2036,
        customer='Synthetic owner', contractor='Synthetic vendor', contract='SYN',
        contract_date='2036-01-02', items=[row(9), row(10, group=True)],
        period_dates_known=False, warnings=[])
    return dict(snapshot_id=day+'-'+archive_sha, taken_at=day, sha256=archive_sha,
        filename='Synthetic.zip', parser_schema=ledgers.PARSER_SCHEMA, identity_schema=4,
        files=[dict(filename='Synthetic.xlsx', status='parsed', sha256=file_sha)],
        ledgers=[ledger], summary_contracts=[])


def arguments(snapshots):
    archives = [dict(snapshot_id=s['snapshot_id'], taken_at=s['taken_at'], files=[
        dict(filename_sha256=proof.text_sha256(f['filename']), file_sha256=f['sha256']) for f in s['files']])
        for s in snapshots]
    prepared = [ledgers._restore_period_dates(s) for s in snapshots]
    return dict(project=PROJECT, cut=CUT, snapshot_ids=[s['snapshot_id']for s in snapshots],
        expected_project_scope=proof.digest(dict(namespace=monitor._resolved_slug(PROJECT))),
        expected_cached_source_roster_sha256=proof.source_roster_digest(CUT, archives),
        expected_source_content_sha256=proof.source_content_digest(prepared),
        caller_reference_corpus_token=hashlib.sha256(b'synthetic retained corpus reference').hexdigest())


@pytest.fixture
def cache(tmp_path, monkeypatch):
    base = tmp_path/'monitor'; base.mkdir()
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', base)
    root = base/monitor._resolved_slug(PROJECT)/'cumulative'; root.mkdir(parents=True)
    snapshots = [snapshot('2036-07-01'), snapshot('2036-08-01')]
    for value in snapshots:
        (root/(value['snapshot_id']+'.json')).write_bytes(proof.canonical(value))
        (root/(value['snapshot_id']+'.zip')).write_bytes(b'SYNTHETIC CANARY: NEVER READ')
    return root, snapshots, arguments(snapshots)


@pytest.fixture
def forbidden_sources(monkeypatch):
    def denied(*a, **k):
        pytest.fail('cache-only proof tried an original/parser/cache writer/consumer')
    for name in ('parse_archive', '_current_archive', '_read_workbook', 'read_snapshot', 'store_archive'):
        monkeypatch.setattr(ledgers, name, denied)
    monkeypatch.setattr(proof.contracts, 'build', denied)
    original = os.open
    def read_only(name, flags, *a, **k):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        assert not str(name).endswith(('.zip', '.xlsx', '.xls'))
        return original(name, flags, *a, **k)
    monkeypatch.setattr(proof.os, 'open', read_only)


def all_files(root):
    return {str(p): (p.read_bytes(), p.stat().st_ino, p.stat().st_mode, p.stat().st_mtime_ns)
            for p in root.parent.parent.rglob('*')if p.is_file()}


def test_current_cache_closed_ordinals_content_and_independent_roster(cache, forbidden_sources):
    root, snapshots, args = cache; before = all_files(root)
    result = proof.project_index(**args)
    assert result['schema']==proof.SCHEMA and result['complete']is True and result['truncated']is False
    assert result['counts']==dict(archives=2,files=2,sheets=2,records=2,positions=4)
    assert result['files'][0][2]==hashlib.sha256(b'Synthetic.xlsx').hexdigest()
    assert result['records'][0][5:7]==[0,0]
    assert [r[2:6]for r in result['position_index_rows'][:2]]==[[0,0,0,0],[0,1,0,1]]
    assert result['future_consumer_invoked']is False
    assert result['cached_source_roster_sha256']==args['expected_cached_source_roster_sha256']
    assert result['source_content_sha256']==args['expected_source_content_sha256']
    assert result['cached_source_roster_sha256']!=result['caller_reference_corpus_token']
    assert result['original_corpus_verified']is False
    assert result['original_bytes_read']==result['cache_writes']==0
    assert result['physical_binding_verified']is result['financial_complete']is result['consumer_complete']is None
    assert result['manifest_set_before_sha256']==result['manifest_set_after_sha256']
    assert all(a['observed_stored_parse_state']is None for a in result['archive_states'])
    pin=result.pop('projection_sha256');assert pin==proof.digest(result)
    assert len(proof.canonical(result))+1024<=262144 and all_files(root)==before
    def closed(value):
        if isinstance(value,dict):
            assert not {'filename','sheet','name','items','periods','formula','amount','quantity','raw'}&value.keys()
            for child in value.values():closed(child)
        elif isinstance(value,list):
            for child in value:closed(child)
    closed(result)


@pytest.mark.parametrize('fault',['parser_missing','parser_old','parser_float','identity_float','basis','party','parse_state',
    'effective','file_sha','file_duplicate','source_duplicate','item_duplicate','foreign_row','kind_bool',
    'items_unknown','periods_unknown','date_bool'])
def test_stale_unknown_ambiguous_foreign_or_reparse_cache_holds(cache, forbidden_sources, fault):
    root, values, args=cache; changed=copy.deepcopy(values[0]);ledger=changed['ledgers'][0]
    if fault=='parser_missing':changed.pop('parser_schema')
    elif fault=='parser_old':changed['parser_schema']-=1
    elif fault=='parser_float':changed['parser_schema']=float(changed['parser_schema'])
    elif fault=='identity_float':changed['identity_schema']=4.0
    elif fault=='basis':ledger['items'][0].pop('planned_amount_basis')
    elif fault=='party':ledger.pop('party_evidence')
    elif fault=='parse_state':changed['source_parse_state']='original_unavailable'
    elif fault=='effective':ledger['date_confirmation']={}
    elif fault=='file_sha':ledger['file_sha256']='a'*64
    elif fault=='file_duplicate':changed['files'].append(copy.deepcopy(changed['files'][0]))
    elif fault=='source_duplicate':changed['ledgers'].append(copy.deepcopy(ledger))
    elif fault=='item_duplicate':ledger['items'].append(copy.deepcopy(ledger['items'][0]))
    elif fault=='foreign_row':ledger['items'][0]['source']['filename']='Foreign.xlsx'
    elif fault=='kind_bool':ledger['items'][0]['is_group']=0
    elif fault=='items_unknown':ledger['items']=None
    elif fault=='periods_unknown':ledger['items'][0]['periods']=None
    elif fault=='date_bool':ledger['items'][0]['periods']=[dict(label='June 2036',date_start=False,date_end=None)]
    (root/(changed['snapshot_id']+'.json')).write_bytes(proof.canonical(changed))
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('fault',['scope','roster','content','missing_sid','extra_sid','duplicate_sid','bad_cut','bad_hash'])
def test_wrong_private_expected_context_is_never_echoed_as_native(cache, forbidden_sources, fault):
    root, values, args=cache;args=copy.deepcopy(args)
    if fault in {'scope','roster','content'}:
        args[{'scope':'expected_project_scope','roster':'expected_cached_source_roster_sha256','content':'expected_source_content_sha256'}[fault]]='a'*64
    elif fault=='missing_sid':args['snapshot_ids'].pop()
    elif fault=='extra_sid':args['snapshot_ids'].append('2036-06-01-'+'a'*64)
    elif fault=='duplicate_sid':args['snapshot_ids'].append(args['snapshot_ids'][0])
    elif fault=='bad_cut':args['cut']=''
    elif fault=='bad_hash':args['expected_project_scope']=False
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('field',['plan_quantity','completed_quantity','is_group'])
def test_shared_typed_content_distinguishes_zero_false_and_none(cache, field):
    _,values,_=cache;first=copy.deepcopy(values);second=copy.deepcopy(values)
    first[0]['ledgers'][0]['items'][0][field]=0
    second[0]['ledgers'][0]['items'][0][field]=False
    third=copy.deepcopy(first);third[0]['ledgers'][0]['items'][0][field]=None
    assert len({proof.source_content_digest(v)for v in (first,second,third)})==3


def test_content_is_order_independent_but_observed_index_map_is_not(cache):
    root,values,args=cache;before=proof.project_index(**args)
    changed=copy.deepcopy(values[0]);changed['ledgers'][0]['items'].reverse()
    (root/(changed['snapshot_id']+'.json')).write_bytes(proof.canonical(changed))
    after=proof.project_index(**args)
    assert before['source_content_sha256']==after['source_content_sha256']
    assert before['position_index_rows']!=after['position_index_rows']
    assert before['manifest_set_before_sha256']!=after['manifest_set_before_sha256']


def test_typed_audit_annotation_inverse_matches_cache_content(cache):
    _,values,_=cache;record=copy.deepcopy(values[0]['ledgers'][0]);audit=copy.deepcopy(record)
    audit.update(header_cells=[{'cell':'B1','kind':'text','value':'Synthetic'}],headers_truncated=False,
        formula_text_omitted=False,source_coordinates_scope='relative_to_this_file_sha256',identity_state='recognized_source_identity',
        contract_date_cut_qualification='on_or_before_cut',source_identity_sha256='a'*64,
        periods_scope='raw_source_periods_not_filtered_as_fact',binding_verified=None)
    for item in audit['items']:item['raw_quantity_cells']={}
    assert proof.record_content_view(record)==proof.record_content_view(audit)
    audit['items'][0]['plan_quantity']=None
    assert proof.record_content_view(record)!=proof.record_content_view(audit)


@pytest.mark.parametrize('fault',['manifest','manifest_replaced','alias_replaced','added','removed','header','alias','root','producer','late_serialize'])
def test_every_before_after_state_and_code_drift_holds(cache, monkeypatch, fault):
    root,values,args=cache;ordinary=proof._project
    if fault=='alias_replaced':
        (root.parent.parent/monitor._ALIASES_FILE).write_bytes(b'{"aliases":{}}')
    def changed(*a,**k):
        result=ordinary(*a,**k)
        path=root/(values[0]['snapshot_id']+'.json')
        if fault=='manifest':path.write_bytes(path.read_bytes()+b' ')
        elif fault=='manifest_replaced':
            replacement=root/'replacement';replacement.write_bytes(path.read_bytes());replacement.replace(path)
        elif fault=='alias_replaced':
            path=root.parent.parent/monitor._ALIASES_FILE
            replacement=path.with_name('replacement');replacement.write_bytes(path.read_bytes());replacement.replace(path)
        elif fault=='added':(root/('2036-08-02-'+'c'*64+'.json')).write_bytes(b'{}')
        elif fault=='removed':path.unlink()
        elif fault=='header':(root.parent/'cumulative_header_dates.json').write_bytes(b'{}')
        elif fault=='alias':monkeypatch.setattr(monitor,'_slug',lambda *a:'foreign')
        elif fault=='root':root.rename(root.with_name('moved'));root.mkdir()
        elif fault=='producer':monkeypatch.setattr(proof,'_producer',lambda:{'changed':True})
        return result
    monkeypatch.setattr(proof,'_project',changed)
    if fault=='late_serialize':
        canonical=proof.canonical
        def late(value):
            result=canonical(value)
            if isinstance(value,dict)and value.get('schema')==proof.SCHEMA:
                path=root/(values[0]['snapshot_id']+'.json');path.write_bytes(path.read_bytes()+b' ')
            return result
        monkeypatch.setattr(proof,'canonical',late)
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('cap',['MAX_ARCHIVES','MAX_FILES','MAX_SHEETS','MAX_RECORDS','MAX_POSITIONS','MAX_ENTRIES','MAX_MANIFEST_BYTES','MAX_TOTAL_BYTES','MAX_RESULT_BYTES','MAX_NODES','MAX_DEPTH'])
def test_every_cap_holds_without_partial_output(cache, monkeypatch, cap):
    _,_,args=cache;monkeypatch.setattr(proof,cap,0)
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('fault',['symlink','hardlink','fifo','orphan_zip','header_present'])
def test_native_file_namespace_and_missing_cache_guards(cache, fault):
    root,values,args=cache;path=root/(values[0]['snapshot_id']+'.json')
    if fault=='symlink':data=path.read_bytes();path.unlink();target=root/'other';target.write_bytes(data);path.symlink_to(target)
    elif fault=='hardlink':os.link(path,root/'other')
    elif fault=='fifo':path.unlink();os.mkfifo(path)
    elif fault=='orphan_zip':(root/('2036-06-01-'+'c'*64+'.zip')).write_bytes(b'never read')
    elif fault=='header_present':(root.parent/'cumulative_header_dates.json').write_bytes(b'{}')
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


def deny_legacy_alias_io(monkeypatch):
    def forbidden(*a,**k):
        pytest.fail('proof called an unsealed legacy alias/path reader')
    for name in ('_aliases','_resolved_slug','_project_dir'):
        monkeypatch.setattr(monitor,name,forbidden)


@pytest.mark.parametrize('body',[
    b'{', b'{"aliases":{},"aliases":{}}', b'{"aliases":{"a":"b","a":"b"}}',
    b'{"aliases":{},"unexpected":NaN}', b'null', b'[]', b'{"unexpected":{}}',
    b'{"aliases":null}', b'{"aliases":[]}', b'{"aliases":{"a":false}}',
    b'{"aliases":{"a":42}}', b'{"aliases":{"a":{}}}', b'{"aliases":{"a":"../b"}}',
    b'{"aliases":{"a":""}}', b'{"aliases":{"":"a"}}', b'{"aliases":{"a":"\\ud800"}}',
])
def test_namespace_strict_held_alias_bytes_reject_before_project_cache(cache,monkeypatch,body):
    root,_,args=cache
    (root.parent.parent/monitor._ALIASES_FILE).write_bytes(body)
    monkeypatch.setattr(monitor,'_ALIAS_CACHE',dict(key=None,map={}))
    deny_legacy_alias_io(monkeypatch)
    monkeypatch.setattr(proof,'_project',lambda *a,**k:pytest.fail('invalid aliases reached project data'))
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('state',['cold','different_key','warm_matching','missing_warm'])
def test_namespace_resolution_uses_exact_FD_map_and_only_observes_native_cache(cache,monkeypatch,state):
    root,_,args=cache;args=copy.deepcopy(args);base=root.parent.parent
    slug=monitor._slug(PROJECT);alias=base/monitor._ALIASES_FILE
    if state=='missing_warm':
        cache_state=dict(key=(str(alias),1,123),map={slug:'old-target'})
        expected_branch='missing_alias_file_empty_map'
    else:
        target='Synthetic-target'
        root.parent.rename(base/target)
        alias_map={slug:target,target:'not-recursively-selected'}
        alias.write_bytes(proof.canonical(dict(aliases=alias_map)))
        info=alias.stat();key=(str(alias),info.st_mtime_ns,info.st_size)
        cache_state=(dict(key=key,map=alias_map)if state=='warm_matching'else
                     dict(key=None,map={})if state=='cold'else
                     dict(key=(str(alias),0,0),map={slug:'old-target'}))
        args['expected_project_scope']=proof.digest(dict(namespace=target))
        expected_branch='warm_key_matching_fd'if state=='warm_matching'else'would_reload'
    monkeypatch.setattr(monitor,'_ALIAS_CACHE',copy.deepcopy(cache_state));cache_object=monitor._ALIAS_CACHE
    deny_legacy_alias_io(monkeypatch)
    result=proof.project_index(**args);observed=result['namespace_resolution']
    assert result['complete']is True and observed['branch']==expected_branch
    assert observed['legacy_resolver_invoked']is observed['current_native_consumer_invoked']is False
    assert observed['native_cache_key_matches_fd']is(state=='warm_matching')
    assert observed['native_cache_before_sha256']==observed['native_cache_after_sha256']==proof.digest(cache_state)
    assert monitor._ALIAS_CACHE is cache_object and monitor._ALIAS_CACHE==cache_state
    assert result['future_consumer_invoked']is False and result['namespace_preimage_observed']is False


def test_namespace_same_key_sealed_bravo_vs_warm_alpha_is_HOLD_not_silent_reload(cache,monkeypatch):
    root,_,args=cache;args=copy.deepcopy(args);base=root.parent.parent
    slug=monitor._slug(PROJECT);alias=base/monitor._ALIASES_FILE
    old=proof.canonical(dict(aliases={slug:'alpha'}));new=proof.canonical(dict(aliases={slug:'bravo'}))
    assert len(old)==len(new)
    alias.write_bytes(old);info=alias.stat()
    cache_state=dict(key=(str(alias),info.st_mtime_ns,info.st_size),map={slug:'alpha'})
    monkeypatch.setattr(monitor,'_ALIAS_CACHE',copy.deepcopy(cache_state))
    alias.write_bytes(new);os.utime(alias,ns=(info.st_atime_ns,info.st_mtime_ns))
    args['expected_project_scope']=proof.digest(dict(namespace='bravo'))
    deny_legacy_alias_io(monkeypatch)
    with pytest.raises(proof.PreparedIndexProblem,match='при том же ключе'):proof.project_index(**args)
    assert monitor._ALIAS_CACHE==cache_state


@pytest.mark.parametrize('mutation',['map','key','object','pure_slug'])
def test_namespace_observed_native_cache_and_pure_slug_prepost_drift_HOLD(cache,monkeypatch,mutation):
    _,_,args=cache;state=dict(key=None,map={});monkeypatch.setattr(monitor,'_ALIAS_CACHE',state)
    deny_legacy_alias_io(monkeypatch);ordinary=proof._project
    def changed(*a,**k):
        value=ordinary(*a,**k)
        if mutation=='map':state['map']['changed']='different'
        elif mutation=='key':state['key']=('/synthetic/old',0,0)
        elif mutation=='object':monkeypatch.setattr(monitor,'_ALIAS_CACHE',copy.deepcopy(state))
        elif mutation=='pure_slug':monkeypatch.setattr(monitor,'_slug',lambda *a:'different')
        return value
    monkeypatch.setattr(proof,'_project',changed)
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('state',[None,[],{},dict(key=None,map=None),dict(key=False,map={}),
    dict(key=('bad',True,0),map={}),dict(key=None,map={'a':False})])
def test_namespace_unknown_native_cache_fact_containers_HOLD(cache,monkeypatch,state):
    _,_,args=cache;monkeypatch.setattr(monitor,'_ALIAS_CACHE',state);deny_legacy_alias_io(monkeypatch)
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)


@pytest.mark.parametrize('cap',['MAX_ALIAS_ENTRIES','MAX_ALIASES_BYTES'])
def test_namespace_alias_caps_hold_without_fallback_or_cache_repair(cache,monkeypatch,cap):
    root,_,args=cache;(root.parent.parent/monitor._ALIASES_FILE).write_bytes(b'{"aliases":{"a":"b"}}')
    state=dict(key=None,map={});monkeypatch.setattr(monitor,'_ALIAS_CACHE',state)
    monkeypatch.setattr(proof,cap,0);deny_legacy_alias_io(monkeypatch)
    with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)
    assert monitor._ALIAS_CACHE==state


@pytest.mark.parametrize('change_cwd',[False,True])
def test_namespace_relative_native_stat_key_is_exact_and_cwd_drift_holds(cache,monkeypatch,change_cwd):
    root,_,args=cache;base=root.parent.parent;alias=base/monitor._ALIASES_FILE
    slug=monitor._slug(PROJECT);alias_map={slug:slug};alias.write_bytes(proof.canonical(dict(aliases=alias_map)))
    monkeypatch.chdir(base.parent);configured=Path(base.name);monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',configured)
    info=alias.stat();state=dict(key=(str(configured/monitor._ALIASES_FILE),info.st_mtime_ns,info.st_size),map=alias_map)
    monkeypatch.setattr(monitor,'_ALIAS_CACHE',copy.deepcopy(state));deny_legacy_alias_io(monkeypatch)
    if change_cwd:
        ordinary=proof._project
        def changed(*a,**k):
            value=ordinary(*a,**k);monkeypatch.chdir(base);return value
        monkeypatch.setattr(proof,'_project',changed)
        with pytest.raises(proof.PreparedIndexProblem):proof.project_index(**args)
    else:assert proof.project_index(**args)['namespace_resolution']['branch']=='warm_key_matching_fd'
    assert monitor._ALIAS_CACHE==state
