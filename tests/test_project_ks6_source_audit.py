"""Project-wide raw KS evidence: synthetic retained originals, no current cards."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import threading
from pathlib import Path
import zipfile

import openpyxl
import pytest

import developaid_contract_source_review as review
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
import developaid_management_report_jobs as jobs
from test_monitor_cumulative_api import api, post, poll, KEY, core  # noqa: F401
from test_monitor_cumulative_ledgers import archive, book, summary

PROJECT='Учебная полная опись КС'
CUT='2036-08-19'


def ks(number='S-01', *, missing_header=False, split=False, actual=0, formula=False, unknown_unit=False):
    wb=openpyxl.load_workbook(io.BytesIO(book(split=split,actual=actual,formula=formula)))
    ws=wb.active
    ws['B3']=number
    ws['B4']=None if missing_header else dt.date(2036,1,4)
    ws['H7']='КС-2 №1' if split else 'Выполнение №1 (01.06.2036 - 30.06.2036)'
    ws['N7']='2036 год'
    if not split:ws['K7']='Выполнение №2 (01.12.2036 - 31.12.2036)'
    if unknown_unit:ws['D9']=None
    out=io.BytesIO();wb.save(out);wb.close();return out.getvalue()


def retain(raw, day, *, filename='Учебный архив.zip'):
    """A historical retained import may include a since-unsupported companion."""
    root=ledgers._root(PROJECT,create=True)
    sid=day+'-'+hashlib.sha256(raw).hexdigest()
    (root/(sid+'.zip')).write_bytes(raw)
    (root/(sid+'.json')).write_text(json.dumps(dict(snapshot_id=sid,taken_at=day,
        filename=filename,loaded_at=day+'T12:00:00',parser_schema=1),ensure_ascii=False))
    return sid


def closing_book():
    wb=openpyxl.load_workbook(io.BytesIO(summary()))
    wb.active.append(['ИТОГО',None,None,None,None,500])
    out=io.BytesIO();wb.save(out);wb.close();return out.getvalue()


def snapshot_bytes():
    root=ledgers._root(PROJECT)
    return {p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def all_records(result):
    return [r for b in result['books'] for s in b['sheets'] for r in s['records']]


def test_all_old_only_and_unresolved_sources_survive_without_a_current_register(api,monkeypatch):
    old=ks('S-OLD');new=ks('S-NEW',missing_header=True)
    first=retain(archive([('Same.xlsx',old)]),'2036-06-01')
    second=retain(archive([('Same.xlsx',new)]),'2036-07-01')
    third=retain(archive([('Renamed.xlsx',old)]),'2036-08-01')
    fourth=retain(archive([('Closing.xlsx',closing_book())]),'2036-08-02')
    before=snapshot_bytes()
    monkeypatch.setattr(contracts,'build',lambda *a,**k:pytest.fail('current register cannot gate the source universe'))
    monkeypatch.setattr(contracts,'_read_rss',lambda *a,**k:pytest.fail('no RSS/financial reads'))
    original=ledgers._read_workbook;calls=[]
    def decode(name,payload,*a,**k):
        calls.append(hashlib.sha256(payload).hexdigest());return original(name,payload,*a,**k)
    monkeypatch.setattr(ledgers,'_read_workbook',decode)
    result=review.project_audit(PROJECT,CUT)
    assert result['read_complete'], [(b['state'],[(s['state'],[r.get('headers_truncated') for r in s['records']]) for s in b['sheets']]) for b in result['books']]
    assert not result['recognition_complete']
    assert result['state']=='read_with_issues'
    assert result['counts']['eligible_archives']==4
    assert result['counts']['eligible_book_observations']==4
    assert result['counts']['unique_book_fingerprints']==3
    assert result['counts']['reused_same_hash_observations']==1
    assert len(calls)==len(set(calls))==3
    assert {a['snapshot_id'] for a in result['archives']}=={first,second,third,fourth}
    records=all_records(result)
    assert {'S-OLD','S-NEW'} <= {r['contract'] for r in records}
    unresolved=next(r for r in records if r['contract']=='S-NEW')
    assert unresolved['identity_state']=='unresolved_header' and unresolved['contract_date'] is None
    assert unresolved['items'] and unresolved['header_cells']
    assert all(r['binding_verified'] is None for r in records)
    assert result['financial_complete'] is result['binding_verified'] is None
    assert snapshot_bytes()==before
    assert 'raw_zip' not in result and 'content_base64' not in json.dumps(result)
    duplicate=result['archives'][2]['files'][0]
    assert duplicate['duplicate_proof']=='same_sha256_and_size'
    assert duplicate['file_sha256']==result['archives'][0]['files'][0]['file_sha256']
    assert result['archives'][1]['files'][0]['file_sha256']!=duplicate['file_sha256']


def test_raw_zero_blank_unknown_unit_future_dates_and_uncached_formula_are_distinct(api):
    retain(archive([('Zero.xlsx',ks(actual=0)),('Formula.xlsx',ks('S-F',formula=True)),
                    ('Unknown.xlsx',ks('S-U',unknown_unit=True)),('Split.xlsx',ks('S-S',split=True))]),'2036-08-01')
    data=review.project_audit(PROJECT,CUT)
    records={r['contract']:r for r in all_records(data)}
    zero=records['S-01']['items'][0]
    formula=records['S-F']['items'][0]
    split=records['S-S']['items'][0]
    assert zero['completed_quantity']==0
    assert formula['completed_quantity'] is None
    assert formula['raw_quantity_cells']['completed_quantity_cell']['kind']=='formula_without_cached_value'
    assert zero['raw_quantity_cells']['completed_quantity_cell']['value']==0
    assert records['S-U']['items'][0]['unit']==''
    assert data['counts']['unknown_units']>=1 and data['counts']['formula_without_cached_value_cells']>=1
    assert {p['cut_qualification'] for p in zero['periods']}=={'on_or_before_cut','future'}
    assert records['S-01']['periods_scope']=='raw_source_periods_not_filtered_as_fact'
    assert records['S-S']['periods_scope']=='raw_source_periods_not_filtered_as_fact'
    assert split['completed_work_amount']==200 and split['completed_material_amount']==500
    assert split['periods'][0]['work_amount']==200 and split['periods'][0]['material_amount']==500
    assert split['material_quantity']==8 and split['completed_quantity']==0
    assert 'physical_progress' not in data and 'completion_ratio' not in data
    assert '=H9+K9' not in json.dumps(data)


def test_unsupported_pdf_is_inventoried_without_opening_and_nonks_sheet_is_visible(api,monkeypatch):
    wb=openpyxl.Workbook();wb.active['A1']='Учебная нераспознанная таблица';out=io.BytesIO();wb.save(out)
    retain(archive([('Known.xlsx',ks()),('Other.xlsx',out.getvalue()),('Companion.pdf',b'%PDF-do-not-open')]),'2036-08-01')
    original=zipfile.ZipFile.open;opened=[]
    def no_pdf(self,name,*a,**k):
        value=name.filename if isinstance(name,zipfile.ZipInfo) else name
        opened.append(value)
        assert not str(value).endswith('.pdf')
        return original(self,name,*a,**k)
    monkeypatch.setattr(zipfile.ZipFile,'open',no_pdf)
    data=review.project_audit(PROJECT,CUT)
    assert not data['read_complete'] and data['state']=='partial'
    assert data['counts']['unsupported_file_observations']==1
    assert data['counts']['unrecognized_sheets']==1
    files=data['archives'][0]['files']
    assert len(files)==3 and files[-1]['status']=='unsupported' and files[-1]['file_sha256'] is None
    assert data['archives'][0]['files_inventory_complete']
    assert data['books'][1]['sheets'][0]['state']=='not_recognized'


def test_future_archives_are_listed_but_never_opened(api,monkeypatch):
    current=retain(archive([('Current.xlsx',ks())]),'2036-08-01')
    future=retain(archive([('Future.xlsx',ks('S-FUTURE'))]),'2036-09-01')
    original=review._original;opened=[]
    def read(project,sid,**kwargs):
        opened.append(sid);return original(project,sid,**kwargs)
    monkeypatch.setattr(review,'_original',read)
    data=review.project_audit(PROJECT,CUT)
    assert set(opened)=={current} and future not in opened
    assert data['future_archives'][0]['snapshot_id']==future
    assert data['future_archives'][0]['state']=='not_read_after_cut'
    assert data['counts']['future_archives']==1


@pytest.mark.parametrize('failure',['missing','hash','archive_symlink','root_symlink','manifest_symlink'])
def test_unavailable_or_unsafe_original_is_never_a_complete_audit(api,tmp_path,failure):
    sid=retain(archive([('Known.xlsx',ks())]),'2036-08-01');root=ledgers._root(PROJECT);path=root/(sid+'.zip')
    if failure=='missing':path.unlink()
    elif failure=='hash':path.write_bytes(b'changed')
    elif failure=='archive_symlink':
        target=tmp_path/'original.zip';target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
    elif failure=='root_symlink':
        moved=root.with_name('outside');root.rename(moved);root.symlink_to(moved,target_is_directory=True)
    else:
        path=root/(sid+'.json');target=tmp_path/'manifest.json';target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
    if failure in {'root_symlink','manifest_symlink'}:
        with pytest.raises(review.SourceReviewProblem):review.project_audit(PROJECT,CUT)
    else:
        data=review.project_audit(PROJECT,CUT)
        assert not data['read_complete'] and not data['counts_complete']
        assert data['archives'][0]['state'] in {'error','unavailable'}
        assert data['books']==[]


def test_original_hash_is_rechecked_even_if_all_workbook_bytes_were_reused(api,monkeypatch):
    raw=archive([('Same.xlsx',ks())]);retain(raw,'2036-06-01');retain(raw,'2036-07-01')
    original=review._original;calls=[]
    def read(project,sid,**kwargs):calls.append(sid);return original(project,sid,**kwargs)
    monkeypatch.setattr(review,'_original',read)
    data=review.project_audit(PROJECT,CUT)
    assert data['read_complete'] and len(calls)==4
    assert data['counts']['reused_same_hash_observations']==1


@pytest.mark.parametrize('limit', ['archives','archive_bytes','books','cells','sheets','items','periods','headers','details','result'])
def test_every_global_cap_is_explicit_and_cannot_claim_complete(api,monkeypatch,limit):
    retain(archive([('One.xlsx',ks()),('Two.xlsx',ks('S-02'))]),'2036-07-01')
    retain(archive([('Three.xlsx',ks('S-03'))]),'2036-08-01')
    constants={'archives':('MAX_ARCHIVES',1),'archive_bytes':('MAX_TOTAL_ARCHIVE_BYTES',1),
        'books':('PROJECT_MAX_BOOKS',1),'cells':('PROJECT_MAX_CELLS',1),'sheets':('PROJECT_MAX_SHEETS',1),
        'items':('PROJECT_MAX_ITEMS',1),'periods':('PROJECT_MAX_PERIODS',1),
        'headers':('PROJECT_MAX_HEADER_CELLS',1),'details':('PROJECT_MAX_DETAIL_BYTES',1),
        'result':('PROJECT_MAX_RESULT_BYTES',6000)}
    name,value=constants[limit];monkeypatch.setattr(review,name,value)
    data=review.project_audit(PROJECT,CUT)
    assert data['state']=='partial' and not data['read_complete'] and not data['counts_complete']
    assert data['counts']['eligible_archives']==2
    assert data['counts_scope']=='retained_read_sources_only_not_the_whole_corpus'
    assert len(json.dumps(data,ensure_ascii=False).encode())<=review.PROJECT_MAX_RESULT_BYTES
    if limit=='cells':assert data['counts']['materialized_cell_reads']<=1
    if limit=='archives':assert data['counts']['omitted_archives']==1


def test_shared_materialized_cell_budget_refuses_before_retaining_the_next_row():
    budget=dict(text_bytes=0,max_materialized_cells=3,materialized_cells=0)
    assert ledgers._bounded_row([1,2],budget)==[1,2]
    with pytest.raises(ledgers.LedgerProblem,match='предел ячеек'):
        ledgers._bounded_row([3,4],budget)
    assert budget['materialized_cells']==2 and budget['cell_limit_reached']
    assert ledgers._bounded_row([1,2,3],dict(text_bytes=0))==[1,2,3]  # old caller unchanged


def test_native_job_has_durable_result_exact_parameters_and_no_source_writes(api,monkeypatch):
    client,tmp=api;retain(archive([('Old.xlsx',ks('S-OLD'))]),'2036-07-01')
    before=snapshot_bytes()
    response=post(client,'contracts/source-audit',project=PROJECT,cut=CUT,ticket='5'*32)
    assert response.status_code in (200,202) and response.headers['cache-control']=='private, no-store'
    result=response if response.status_code==200 else poll(client,response.json()['ticket'])
    assert result.json()['ok'] and result.json()['source_audit']['read_complete']
    assert result.json()['runtime']==dict(version=core.VERSION,commit=core.COMMIT)
    # A separate Store instance reads the same existing durable result.
    owner=jobs.owner_binding(KEY,'','monitor-cumulative-v1:contracts')
    stored=jobs.Store(tmp/'monitor'/'.cumulative_jobs').poll('5'*32,owner,'monitor-cumulative-v1:contracts')
    assert stored['source_audit']==result.json()['source_audit']
    assert post(client,'contracts/source-audit',project='Other',cut=CUT,ticket='5'*32).status_code==409
    assert snapshot_bytes()==before
    metadata=(tmp/'monitor'/'.cumulative_jobs'/('5'*32+'.json')).read_bytes()
    assert KEY.encode() not in metadata


@pytest.mark.parametrize('extra',[{'path':'/etc/passwd'},{'url':'https://example.invalid'}, {'filename':'A.xlsx'},
    {'sheet':'KS'},{'range':'A1:ZZ9999'},{'contract_id':'a'*64},{'snapshot_id':'a'*64},{'callback':'https://example.invalid'}])
def test_strict_request_forbids_every_caller_source_selector(api,extra):
    client,_=api
    r=client.post('/monitor/contracts/source-audit',json=dict(key=KEY,project=PROJECT,cut=CUT,**extra))
    assert r.status_code==422 and r.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('key,session',[('', ''),('wrong',''),('market-key',''),('', 'claimed-team'),('', 'demo-link')])
def test_denied_access_happens_before_source_or_job_lookup(api,monkeypatch,key,session):
    client,tmp=api
    monkeypatch.setattr(review,'project_audit',lambda *a,**k:pytest.fail('source read before admin'))
    monkeypatch.setattr(jobs.Store,'poll',lambda *a,**k:pytest.fail('job read before admin'))
    r=post(client,'contracts/source-audit',project=PROJECT,cut=CUT,key=key,session=session)
    assert r.status_code==403 and r.headers['cache-control']=='private, no-store'
    assert not (tmp/'monitor'/'.cumulative_jobs').exists()


@pytest.mark.parametrize('retarget',['alias','root','inventory'])
def test_namespace_root_and_snapshot_inventory_cannot_change_during_the_audit(api,monkeypatch,retarget):
    sid=retain(archive([('Old.xlsx',ks('S-OLD'))]),'2036-07-01')
    root=ledgers._root(PROJECT)
    original=ledgers._read_workbook
    decoded=[]
    def change(name,payload,*args,**kwargs):
        decoded.append(hashlib.sha256(payload).hexdigest())
        result=original(name,payload,*args,**kwargs)
        if retarget=='alias':
            base=ledgers.monitor._SNAPSHOT_DIR
            (base/'other-source-project'/'cumulative').mkdir(parents=True)
            (base/ledgers.monitor._ALIASES_FILE).write_text(json.dumps({'aliases':{
                ledgers.monitor._slug(PROJECT):'other-source-project'}}))
        elif retarget=='root':
            root.rename(root.with_name('retained-originals'))
            root.mkdir()
            (root/(sid+'.zip')).write_bytes(b'substituted root content must not be decoded')
        else:
            retain(archive([('New.xlsx',ks('S-LATE'))]),'2036-08-01')
        return result
    monkeypatch.setattr(ledgers,'_read_workbook',change)
    with pytest.raises(review.SourceReviewProblem,match='измени|изменил'):
        review.project_audit(PROJECT,CUT)
    assert len(decoded)==1  # No workbook from the substituted corpus was read.


def test_original_drift_is_explicit_and_never_accepted_from_the_decoded_cache(api,monkeypatch):
    sid=retain(archive([('Original.xlsx',ks())]),'2036-08-01')
    original=ledgers._read_workbook
    def change(*args,**kwargs):
        value=original(*args,**kwargs)
        (ledgers._root(PROJECT)/(sid+'.zip')).write_bytes(b'changed during read')
        return value
    monkeypatch.setattr(ledgers,'_read_workbook',change)
    result=review.project_audit(PROJECT,CUT)
    assert not result['read_complete']
    assert result['archives'][0]['state']=='error'
    assert all(f['read_state']=='source_verification_failed' for f in result['archives'][0]['files'])


def test_an_unreadable_book_and_a_valid_old_book_both_have_inventory_entries(api):
    retain(archive([('Bad.xlsx',b'not an Excel workbook'),('Good.xlsx',ks())]),'2036-08-01')
    result=review.project_audit(PROJECT,CUT)
    assert not result['read_complete']
    states={f['filename']:f['status'] for f in result['archives'][0]['files']}
    assert states=={'Bad.xlsx':'unreadable','Good.xlsx':'read'}
    assert any(r['contract']=='S-01' for r in all_records(result))


def test_missing_manifest_original_is_visible_and_not_a_complete_catalog(api):
    sid=retain(archive([('Orphan.xlsx',ks('S-ORPHAN'))]),'2036-08-01')
    (ledgers._root(PROJECT)/(sid+'.json')).unlink()
    result=review.project_audit(PROJECT,CUT)
    assert result['counts']['eligible_archives']==1
    assert result['counts']['missing_archive_manifests']==1
    assert not result['read_complete']
    assert result['archives'][0]['archive_date_basis']=='snapshot_id_only_manifest_missing'
    assert all_records(result)[0]['contract']=='S-ORPHAN'


def test_blank_quantity_is_unknown_and_separate_from_uncached_formula(api):
    wb=openpyxl.load_workbook(io.BytesIO(ks(actual=0)))
    wb.active['N9']=None
    out=io.BytesIO();wb.save(out);wb.close()
    retain(archive([('Blank.xlsx',out.getvalue())]),'2036-08-01')
    result=review.project_audit(PROJECT,CUT)
    item=all_records(result)[0]['items'][0]
    assert item['completed_quantity'] is None
    assert item['raw_quantity_cells']['completed_quantity_cell']['kind']=='blank'
    assert result['counts']['formula_without_cached_value_cells']==0


def test_source_provenance_is_relative_to_book_hash_and_each_observation_is_retained(api):
    raw=ks()
    retain(archive([('Name-A.xlsx',raw)]),'2036-07-01')
    retain(archive([('Name-B.xlsx',raw)]),'2036-08-01')
    result=review.project_audit(PROJECT,CUT)
    book,=result['books'];record,=all_records(result)
    assert record['file_sha256']==book['file_sha256']==hashlib.sha256(raw).hexdigest()
    assert record['source_coordinates_scope']=='relative_to_this_file_sha256'
    assert record['items'][0]['source']['row']==9
    assert {a['files'][0]['filename'] for a in result['archives']}=={'Name-A.xlsx','Name-B.xlsx'}
    assert result['counts']['retained_position_observations']==2*result['counts']['retained_unique_positions']


def test_native_duplicate_annotations_keep_all_raw_rows_but_never_export_formula_text(api):
    from test_cumulative_proven_duplicates import duplicate_book
    retain(archive([('Duplicates.xlsx',duplicate_book())]),'2036-08-01')
    result=review.project_audit(PROJECT,CUT)
    record,=all_records(result)
    assert len(record['items'])==4 and result['counts']['retained_unique_positions']==4
    assert record['duplicate_rows_count']==2 and record['formula_text_omitted']
    encoded=json.dumps(result,ensure_ascii=False)
    assert '=SUM(' not in encoded and '"formula":' not in encoded


def test_supported_extension_changes_do_not_poison_the_single_hash_decode(api,monkeypatch):
    raw=ks()
    retain(archive([('Misnamed.xls',raw),('Correct.xlsx',raw)]),'2036-08-01')
    original=ledgers._read_workbook;calls=[]
    def read(name,*args,**kwargs):calls.append(name);return original(name,*args,**kwargs)
    monkeypatch.setattr(ledgers,'_read_workbook',read)
    result=review.project_audit(PROJECT,CUT)
    assert result['read_complete'] and len(calls)==1
    assert result['counts']['reused_same_hash_observations']==1
    assert {f['filename'] for f in result['archives'][0]['files']}=={'Misnamed.xls','Correct.xlsx'}


def test_global_text_budget_stops_remaining_workbook_decodes_with_visible_status(api,monkeypatch):
    retain(archive([('First.xlsx',ks('S-01')),('Second.xlsx',ks('S-02'))]),'2036-08-01')
    original=ledgers._read_workbook;calls=[]
    def read(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(ledgers,'MAX_MATERIALIZED_TEXT_BYTES',32)
    monkeypatch.setattr(ledgers,'_read_workbook',read)
    result=review.project_audit(PROJECT,CUT)
    assert not result['read_complete'] and len(calls)==1
    assert all(f['read_state']=='not_read_budget' for f in result['archives'][0]['files'])


def test_special_original_is_rejected_before_opening_it(api,monkeypatch):
    import os
    sid=retain(archive([('Known.xlsx',ks())]),'2036-08-01')
    path=ledgers._root(PROJECT)/(sid+'.zip')
    path.unlink();os.mkfifo(path)
    monkeypatch.setattr(review,'_original',lambda *a,**k:pytest.fail('nonregular archive reached source open'))
    result=review.project_audit(PROJECT,CUT)
    assert result['state']=='partial' and not result['read_complete']
    assert result['archives'][0]['state']=='error'
    assert not result['archives'][0]['original_sha_verified'] and result['books']==[]


def test_regular_to_fifo_race_requires_nonblocking_open_and_never_reads(api,monkeypatch):
    import os
    import stat
    sid=retain(archive([('Known.xlsx',ks())]),'2036-08-01')
    path=ledgers._root(PROJECT)/(sid+'.zip')
    original_review,original_open,original_fdopen=review._original,os.open,os.fdopen
    calls=[]
    class NoRead:
        def __init__(self,handle):self.handle=handle
        def __enter__(self):return self
        def __exit__(self,*args):self.handle.close()
        def fileno(self):return self.handle.fileno()
        def read(self,*args):pytest.fail('FIFO data read attempted')
    def safe_open(name,flags,*args,**kwargs):
        if name==sid+'.zip':
            # The unchanged parent fails this assertion before any potentially
            # blocking syscall; the child can safely open the temp FIFO.
            assert flags & os.O_NONBLOCK
            calls.append(flags)
        return original_open(name,flags,*args,**kwargs)
    def checked_fdopen(fd,mode,*args,**kwargs):
        value=original_fdopen(fd,mode,*args,**kwargs)
        return NoRead(value) if mode=='rb' and stat.S_ISFIFO(os.fstat(fd).st_mode) else value
    def raced(project,snapshot_id,**kwargs):
        path.unlink();os.mkfifo(path)
        return original_review(project,snapshot_id,**kwargs)
    monkeypatch.setattr(review,'_original',raced)
    monkeypatch.setattr(review.os,'open',safe_open)
    monkeypatch.setattr(review.os,'fdopen',checked_fdopen)
    result=review.project_audit(PROJECT,CUT)
    assert len(calls)==1 and result['archives'][0]['state']=='error'
    assert not result['read_complete'] and result['books']==[]


@pytest.mark.parametrize('kind',['directory','device_metadata'])
def test_other_nonregular_original_types_fail_before_any_source_open(api,monkeypatch,kind):
    import stat
    from types import SimpleNamespace
    sid=retain(archive([('Known.xlsx',ks())]),'2036-08-01')
    path=ledgers._root(PROJECT)/(sid+'.zip')
    if kind=='directory':
        path.unlink();path.mkdir()
    else:
        original_stat=review.os.stat
        def device_stat(name,*args,**kwargs):
            if name==sid+'.zip' and kwargs.get('dir_fd') is not None:
                return SimpleNamespace(st_mode=stat.S_IFCHR|0o600)
            return original_stat(name,*args,**kwargs)
        monkeypatch.setattr(review.os,'stat',device_stat)
    monkeypatch.setattr(review,'_original',lambda *a,**k:pytest.fail('nonregular original opened'))
    result=review.project_audit(PROJECT,CUT)
    assert result['archives'][0]['state']=='error' and not result['read_complete']
    assert result['books']==[] and result['counts']['verified_original_bytes']==0
