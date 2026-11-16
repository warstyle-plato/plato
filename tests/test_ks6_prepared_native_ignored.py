"""Native ignored service metadata never substitutes for a parsed workbook."""
import copy
import hashlib
import io
from pathlib import Path
import zipfile

import pytest

import developaid_contract_prepared_index as proof
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_ledgers import book

DAY='2026-03-01'
PROJECT='Synthetic native ignored metadata'


def native_snapshot(ignored='__MACOSX/._Synthetic.xlsx'):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w')as archive:
        archive.writestr('Synthetic.xlsx',book())
        if ignored is not None:archive.writestr(ignored,b'synthetic metadata')
    raw=data.getvalue();sha=hashlib.sha256(raw).hexdigest()
    parsed=ledgers.parse_archive(raw,'Synthetic.zip')
    return dict(parsed,snapshot_id=DAY+'-'+sha,taken_at=DAY,sha256=sha,filename='Synthetic.zip')


def arguments(value):
    parsed=value['files'][0]
    assert parsed['filename']=='Synthetic.xlsx'and parsed['status']=='parsed'
    archives=[dict(snapshot_id=value['snapshot_id'],taken_at=DAY,
        files=[dict(filename_sha256=proof.text_sha256('Synthetic.xlsx'),file_sha256=parsed['sha256'])])]
    return dict(project=PROJECT,cut=DAY,snapshot_ids=[value['snapshot_id']],
        expected_project_scope=proof.digest(dict(namespace=monitor._slug(PROJECT))),
        expected_cached_source_roster_sha256=proof.source_roster_digest(DAY,archives),
        expected_source_content_sha256=proof.source_content_digest([ledgers._restore_period_dates(value)]),
        caller_reference_corpus_token=hashlib.sha256(b'synthetic reference not attested original').hexdigest())


def persist_synthetic(value,tmp_path,monkeypatch):
    base=tmp_path/'monitor';root=base/monitor._slug(PROJECT)/'cumulative';root.mkdir(parents=True)
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',base)
    monkeypatch.setattr(monitor,'_ALIAS_CACHE',{'key':None,'map':{}})
    path=root/(value['snapshot_id']+'.json');path.write_bytes(proof.canonical(value))
    (root/(value['snapshot_id']+'.zip')).write_bytes(b'SYNTHETIC CANARY NEVER READ')
    return root,path


def forbid_originals_and_writes(monkeypatch):
    def denied(*a,**kw):pytest.fail('prepared reader invoked original/parser/writer/consumer')
    for name in ['parse_archive','_current_archive','_read_workbook','read_snapshot','store_archive']:
        monkeypatch.setattr(ledgers,name,denied)
    monkeypatch.setattr(proof.contracts,'build',denied)
    opening=proof.os.open
    def readonly(name,flags,*a,**kw):
        assert not flags&(proof.os.O_WRONLY|proof.os.O_RDWR|proof.os.O_CREAT|proof.os.O_TRUNC)
        assert not str(name).endswith(('.zip','.xls','.xlsx','.xlsm'))
        return opening(name,flags,*a,**kw)
    monkeypatch.setattr(proof.os,'open',readonly)


@pytest.mark.parametrize('ignored',['__MACOSX/._Synthetic.xlsx','.DS_Store','folder/.DS_Store'])
def test_native_parsed_book_and_ignored_metadata_close_the_same_source_indices_and_full_manifest(ignored,tmp_path,monkeypatch):
    value=native_snapshot(ignored);before=copy.deepcopy(value)
    assert value['files'][1]==dict(filename=ignored,status='ignored',warnings=['Служебный файл архива.'])
    assert value['files_count']==1 and value['read_files']==['Synthetic.xlsx']and value['companion_files']==[ignored]
    control=copy.deepcopy(value);control['files'].pop()
    expected,_=proof._project([control],DAY)
    root,path=persist_synthetic(value,tmp_path,monkeypatch);args=arguments(value)
    files={p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns)for p in root.iterdir()}
    forbid_originals_and_writes(monkeypatch)
    result=proof.project_index(**args)
    assert result['complete']is True and result['truncated']is False
    assert result['counts']==dict(archives=1,files=1,sheets=1,records=1,positions=2)
    for field in ['files','sheets','records','position_index_rows']:assert result[field]==expected[field]
    assert result['source_content_sha256']==args['expected_source_content_sha256']
    assert result['cached_source_roster_sha256']==args['expected_cached_source_roster_sha256']
    assert result['manifests'][0]['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['manifests'][0]['sha256']!=hashlib.sha256(proof.canonical(control)).hexdigest()
    assert result['manifest_set_before_sha256']==result['manifest_set_after_sha256']
    assert result['original_bytes_read']==result['cache_writes']==0
    assert result['original_corpus_verified']is False and result['future_consumer_invoked']is False
    assert result['physical_binding_verified']is result['financial_complete']is result['consumer_complete']is None
    assert value==before and {p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns)for p in root.iterdir()}==files


@pytest.mark.parametrize('fault',['ordinary_book','extra_sha','extra_field','missing_warning','changed_warning','failed','not_read','unknown',
    'absolute','traversal','backslash','directory','case_prefix','noncanonical_unicode','invalid_unicode',
    'duplicate','case_duplicate','parsed_sha','ignored_record','missing_record','ignored_only'])
def test_only_exact_native_ignored_metadata_is_exempt_and_every_parsed_source_still_closes(fault):
    value=native_snapshot();metadata=value['files'][1]
    if fault=='ordinary_book':metadata['filename']='NotMetadata.xlsx'
    elif fault=='extra_sha':metadata['sha256']='a'*64
    elif fault=='extra_field':metadata['sheet']='not allowed'
    elif fault=='missing_warning':metadata.pop('warnings')
    elif fault=='changed_warning':metadata['warnings']=['Other reason']
    elif fault in {'failed','not_read','unknown'}:metadata['status']=fault
    elif fault=='absolute':metadata['filename']='/__MACOSX/._Synthetic.xlsx'
    elif fault=='traversal':metadata['filename']='__MACOSX/../Synthetic.xlsx'
    elif fault=='backslash':metadata['filename']='__MACOSX/\\Synthetic.xlsx'
    elif fault=='directory':metadata['filename']='__MACOSX/folder/'
    elif fault=='case_prefix':metadata['filename']='__macosx/._Synthetic.xlsx'
    elif fault=='noncanonical_unicode':metadata['filename']='__MACOSX/e\u0301'
    elif fault=='invalid_unicode':metadata['filename']='__MACOSX/\ud800'
    elif fault=='duplicate':value['files'].append(copy.deepcopy(metadata))
    elif fault=='case_duplicate':value['files'].append(dict(metadata,filename='__MACOSX/._SYNTHETIC.xlsx'))
    elif fault=='parsed_sha':value['files'][0].pop('sha256')
    elif fault=='ignored_record':value['ledgers'][0]['source']['filename']=metadata['filename']
    elif fault=='missing_record':value['ledgers']=[]
    else:value['files']=[metadata];value['ledgers']=[]
    with pytest.raises(proof.PreparedIndexProblem):proof._project([value],DAY)


def test_ignored_entries_consume_the_existing_total_file_budget(monkeypatch):
    first=native_snapshot();second=copy.deepcopy(first)
    second['snapshot_id']=DAY+'-'+'b'*64
    monkeypatch.setattr(proof,'MAX_FILES',3)
    with pytest.raises(proof.PreparedIndexProblem,match='Предел файлов'):proof._project([first,second],DAY)


def test_native_ignored_metadata_still_participates_in_full_before_after_manifest_seals(tmp_path,monkeypatch):
    value=native_snapshot();root,path=persist_synthetic(value,tmp_path,monkeypatch);args=arguments(value)
    original=proof._project
    def race(*a,**kw):
        projected=original(*a,**kw)
        changed=copy.deepcopy(value);changed['files'][1]['filename']='__MACOSX/._Other.xlsx'
        path.write_bytes(proof.canonical(changed))
        return projected
    forbid_originals_and_writes(monkeypatch);monkeypatch.setattr(proof,'_project',race)
    with pytest.raises(proof.PreparedIndexProblem,match='изменился'):proof.project_index(**args)
