import hashlib
import json
import pytest
import developaid_contract_disk_source as disk
import developaid_contract_files as files
import developaid_contract_identity_store as ns
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_contract_disk_source import setup,Client,source,URL,ROW
from tests.test_contract_pdf_intake import pdf,CUSTOMER,CONTRACTOR

@pytest.fixture
def pdf_case(setup,monkeypatch):
    raw,_=pdf()
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    return row,raw,hashlib.sha256(raw).hexdigest()

def staged(row,raw):
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    checked=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert checked['entries'][0]['status']=='ready',checked['entries'][0].get('reason')
    return checked,client

def native_remove(row,raw):
    sha=hashlib.sha256(raw).hexdigest()
    files.store('Fixture',row,'native.pdf',raw)
    files.remove('Fixture',row['id'],sha,cut='2026-11-25',acts={'document_source_ids':row.get('document_source_ids') or []})
    return monitor._project_dir('Fixture')/'contract_documents'/row['id']/(sha+'.json')

def test_retained_removed_source_in_native_family_is_unchanged(pdf_case,monkeypatch):
    row,raw,sha=pdf_case
    row['document_source_ids']=['b'*64]
    checked,client=staged(row,raw)
    target=native_remove({**row,'id':'b'*64,'document_source_ids':[]},raw)
    before=target.read_bytes()
    result=disk.apply('Fixture',checked['stage_token'])
    assert result['entries'][0]['status']=='already'
    assert target.read_bytes()==before and json.loads(before)['removed_at']
    rescanned=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert rescanned['entries'][0]['status']=='already'
    assert not (target.parent.parent/ROW['id']/(sha+'.pdf')).exists()

def test_family_retarget_after_stage_is_not_silent(pdf_case):
    row,raw,_=pdf_case
    checked,_=staged(row,raw)
    row['document_source_ids']=['b'*64]
    with pytest.raises(disk.DiskSourceProblem,match='Реквизиты договора изменились'):
        disk.apply('Fixture',checked['stage_token'])

def test_native_remove_during_adapter_preflight_cannot_restore(pdf_case,monkeypatch):
    row,raw,_=pdf_case
    checked,_=staged(row,raw)
    original=disk.check_pdf
    target=[]
    def racing(*args):
        value=original(*args)
        target.append(native_remove(row,raw))
        return value
    monkeypatch.setattr(disk,'check_pdf',racing)
    result=disk.apply('Fixture',checked['stage_token'])
    assert result['entries'][0]['status']=='already'
    assert result['entries'][0]['preserved_removed'] is True
    assert json.loads(target[0].read_bytes())['removed_at']

def test_native_remove_inside_locked_parser_window_fails_cas(pdf_case,monkeypatch):
    row,raw,_=pdf_case
    checked,_=staged(row,raw)
    original_record=files._record
    enabled=[True]
    target=[]
    def racing(*args,**kwargs):
        value=original_record(*args,**kwargs)
        if enabled[0]:
            enabled[0]=False
            target.append(native_remove(row,raw))
        return value
    # Skip the adapter preflight; exercise the native core's parser window.
    monkeypatch.setattr(disk,'check_pdf',lambda *a:{'kind':'pdf'})
    monkeypatch.setattr(files,'_record',racing)
    result=disk.apply('Fixture',checked['stage_token'])
    assert result['entries'][0]['status']=='review'
    assert 'во время разбора' in result['entries'][0]['reason']
    assert json.loads(target[0].read_bytes())['removed_at']

def test_source_state_changes_between_stage_and_apply_block_new_write(pdf_case):
    row,raw,_=pdf_case
    checked,_=staged(row,raw)
    root=monitor._project_dir('Fixture')
    (root/'cumulative_terms.json').write_text(json.dumps({row['id']:{'deadline':'2027-01-01'}}))
    result=disk.apply('Fixture',checked['stage_token'])
    assert result['entries'][0]['status']=='review'
    assert 'Состояние исходников изменилось' in result['entries'][0]['reason']
    assert not list((root/'contract_documents'/row['id']).glob('*.pdf'))

def test_default_manual_store_keeps_its_restore_behavior(pdf_case):
    row,raw,_=pdf_case
    target=native_remove(row,raw)
    result=files.store('Fixture',row,'native.pdf',raw)
    assert result['already'] and result['restored']
    assert 'removed_at' not in json.loads(target.read_bytes())


def test_active_operational_source_selection_requires_native_admission(pdf_case):
    row,raw,_=pdf_case
    row['_disk_source_correction']={'event_id':'f'*64,'roles':{'documents_raw_id':'b'*64}}
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert view['entries'][0]['status']=='review'
    assert 'операционного допуска' in view['entries'][0]['reason']


def test_identity_role_decision_after_stage_is_a_native_commit_guard(pdf_case,monkeypatch):
    row,raw,_=pdf_case
    checked,_=staged(row,raw)
    original=ns.load
    monkeypatch.setattr(ns,'load',lambda project:{**original(project),'head':'e'*64})
    result=disk.apply('Fixture',checked['stage_token'])
    assert result['entries'][0]['status']=='review'
    assert 'Состояние исходников изменилось' in result['entries'][0]['reason']


def ks_case(monkeypatch):
    from test_contracts_from_cumulative_headers import ks
    raw=ks();archive=disk.archive_bytes([('KS.xlsx',raw)])
    data=ledgers.parse_archive(archive,'fixture.zip')['ledgers'][0]
    row={**ROW,**{k:data.get(k) for k in ('contractor','customer','contract','contract_date')}}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    path='/Сметчик/'+row['contractor']+'/'+row['contract']+'/КС-6а/KS.xlsx'
    client=Client({path:raw});view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    checked=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert checked['entries'][0]['status']=='ready'
    return checked,archive


def remove_snapshot(snapshot):
    inventory=ledgers.snapshot_inventory('Fixture')
    ledgers.change_snapshot_activity('Fixture',snapshot['snapshot_id'],inventory['revision'])


def test_concurrent_ks6_import_and_remove_cannot_reintroduce_book(setup,monkeypatch):
    checked,archive=ks_case(monkeypatch)
    original=disk.check_ks6
    def racing(*args):
        result=original(*args)
        saved=ledgers.store_archive('Fixture',archive,'2026-11-24','manual.zip')
        remove_snapshot(saved)
        return result
    monkeypatch.setattr(disk,'check_ks6',racing)
    result=disk.apply('Fixture',checked['stage_token'],taken_at='2026-11-25')
    assert result['entries'][0]['status']=='review'
    assert 'Состав снимков изменился' in result['entries'][0]['reason']
    snapshots=ledgers.list_snapshots('Fixture',include_removed=True)
    assert len(snapshots)==1 and not ledgers.list_snapshots('Fixture')


def test_fresh_archive_pin_still_never_reimports_excluded_source(setup,monkeypatch):
    _,archive=ks_case(monkeypatch)
    saved=ledgers.store_archive('Fixture',archive,'2026-11-24','manual.zip');remove_snapshot(saved)
    pin=ledgers.snapshot_inventory('Fixture')['revision']
    with ns.locked('Fixture'),pytest.raises(ledgers.LedgerConflict,match='уже сохранена'):
        ledgers.store_archive('Fixture',archive,'2026-11-25','different.zip',source_policy={'archive_revision':pin})
    assert len(ledgers.list_snapshots('Fixture',include_removed=True))==1
    # Explicit legacy/manual intake retains its original semantics.
    ledgers.store_archive('Fixture',archive,'2026-11-25','manual-new-date.zip')
    assert len(ledgers.list_snapshots('Fixture'))==1


def test_cooperative_native_writer_waits_for_the_entire_source_family(pdf_case,monkeypatch):
    import threading
    row,raw,sha=pdf_case
    row['document_source_ids']=['b'*64]
    old,_=pdf(extra='Другой сохранённый исходник')
    old_sha=hashlib.sha256(old).hexdigest()
    sibling={**row,'id':'b'*64,'document_source_ids':[]}
    files.store('Fixture',sibling,'old.pdf',old)
    checked,_=staged(row,raw)
    entered,attempted,proceed,finished=(threading.Event() for _ in range(4))
    original=files._record
    results,errors=[],[]
    def hooked(*args,**kwargs):
        record=original(*args,**kwargs)
        if args[0]==sha:
            entered.set()
            assert proceed.wait(10)
        return record
    monkeypatch.setattr(files,'_record',hooked)
    monkeypatch.setattr(disk,'check_pdf',lambda *a:{'kind':'pdf'})
    def apply_():
        try:
            results.append(disk.apply('Fixture',checked['stage_token']))
        except BaseException as exc:
            errors.append(exc)
    def remove_():
        attempted.set()
        try:
            files.remove('Fixture','b'*64,old_sha,cut='2026-11-25')
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()
    applying=threading.Thread(target=apply_)
    removing=threading.Thread(target=remove_)
    applying.start()
    try:
        assert entered.wait(10)
        removing.start()
        assert attempted.wait(10)
        assert not finished.wait(.05), 'native sibling writer escaped the family lock'
    finally:
        proceed.set()
        applying.join(10)
        if removing.ident:
            removing.join(10)
    assert not errors and not applying.is_alive() and not removing.is_alive()
    assert results[0]['entries'][0]['status']=='imported'
    path=monitor._project_dir('Fixture')/'contract_documents'/('b'*64)/(old_sha+'.json')
    assert json.loads(path.read_bytes())['removed_at']
