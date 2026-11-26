"""Only synthetic native two-source cards; no Disk network or business imports."""
import hashlib
import json
import pymupdf
import pytest
import main
import developaid_contract_disk_source as disk
import developaid_contract_files as files
import developaid_contract_identity as identity
import developaid_contract_identity_store as journal
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contract_logical_ownership import pair,PROJECT,CUT,changed_book
from test_contract_source_correction import confirm
from test_contract_disk_source import Client,URL,source
from test_contracts_from_cumulative_headers import ks
from tests.test_contract_documents_are_read_from_their_tables import _page,_text


def pdf_for(row, extra=''):
    doc=pymupdf.open(); page=_page(doc)
    date='.'.join(reversed(row['contract_date'].split('-')))
    values=[f"Договор подряда № {row['contract']} от {date}",
            f"{row['customer']}, именуемое в дальнейшем «Заказчик»",
            f"{row['contractor']}, именуемое в дальнейшем «Подрядчик»",extra]
    for i,text in enumerate(values): _text(page,40,45+i*24,text)
    raw=doc.tobytes();doc.close();return raw


@pytest.fixture
def operational(pair):
    confirm(pair)
    return pair


def prepare(pair, *, raw=None, kind='Договор'):
    row,=main.core._monitor_contract_disk_rows(PROJECT,CUT)
    assert not row.get('_disk_review_reason'),row
    raw=raw or pdf_for(disk.native_owner(row))
    catalog=source(raw,role='Сметчик' if kind=='КС-6а' else 'Юрист',party='Учебный исполнитель',number='SOURCE-B',kind=kind)
    if kind=='КС-6а': catalog={key.replace('.pdf','.xlsx'):value for key,value in catalog.items()}
    client=Client(catalog)
    with journal.namespace(PROJECT):
        scanned=disk.scan(PROJECT,URL,CUT,client=client,row_provider=main.core._monitor_contract_disk_rows)
        entry,=scanned['entries'];assert entry['status']=='new',entry
        staged=disk.stage(PROJECT,scanned['revision'],[entry['id']],client=client,row_provider=main.core._monitor_contract_disk_rows)
    ready,=staged['entries'];assert ready['status']=='ready',ready
    return row,raw,staged,client


def apply(staged, **kw):
    with journal.namespace(PROJECT):
        return disk.apply(PROJECT,staged['stage_token'],row_provider=main.core._monitor_contract_disk_rows,
            document_commit=kw.pop('document_commit',main.core._monitor_contract_disk_document_commit),
            book_commit=main.core._monitor_contract_disk_book_commit,**kw)


@pytest.mark.parametrize('documents_old',[False,True])
def test_native_operational_pdf_targets_selected_document_owner(operational,documents_old):
    if documents_old:
        event=journal.load(PROJECT)
        identity.revoke(PROJECT,expected_revision=event['revision'],decision_id=event['active'][0]['event_id'],note='Synthetic role correction.',actor='a'*64)
        confirm(operational,documents_raw_id=operational['old'])
    row,raw,staged,_=prepare(operational)
    sha=hashlib.sha256(raw).hexdigest();before=journal.load(PROJECT)['head']
    result=apply(staged);outcome,=result['entries']
    assert outcome['status']=='imported',outcome
    owner=operational['old' if documents_old else 'new']
    assert (operational['root']/'contract_documents'/owner/(sha+'.pdf')).read_bytes()==raw
    other=operational['new' if documents_old else 'old']
    assert not (operational['root']/'contract_documents'/other/(sha+'.pdf')).exists()
    assert journal.load(PROJECT)['head']==before
    saved=json.loads((operational['root']/'contract_documents'/owner/(sha+'.json')).read_bytes())
    assert not saved.get('confirmed_scan')
    assert row['_disk_operational']['roles']['execution_raw_id']==operational['old']
    assert row['_disk_operational']['roles']['price_raw_id']==operational['new']


def test_ks6_preflight_and_import_use_execution_not_canonical_or_price(operational):
    raw=changed_book(ks(number='SOURCE-A'),{'C1':'ООО «Учебный заказчик»','C2':'ООО «Учебный исполнитель»','N9':5,'O9':500})
    row,raw,staged,_=prepare(operational,raw=raw,kind='КС-6а')
    entry,=staged['entries']
    assert entry['identity']==disk.legal_identity(disk.native_owner(row,execution=True))
    assert entry['identity']!=disk.legal_identity(disk.native_owner(row))
    before=journal.load(PROJECT)['head']
    result=apply(staged,taken_at='2026-11-14');outcome,=result['entries']
    assert outcome['status']=='imported',outcome
    snapshot=json.loads((ledgers._root(PROJECT)/(outcome['snapshot_id']+'.json')).read_bytes())
    assert snapshot['ledgers'][0]['contract']=='SOURCE-A'
    assert journal.load(PROJECT)['head']==before


def test_stale_role_change_between_preflight_and_native_commit_is_review(operational):
    row,raw,staged,_=prepare(operational)
    def raced(*args):
        state=journal.load(PROJECT)
        identity.revoke(PROJECT,expected_revision=state['revision'],decision_id=state['active'][0]['event_id'],note='Synthetic new selection.',actor='a'*64)
        confirm(operational,documents_raw_id=operational['old'])
        return main.core._monitor_contract_disk_document_commit(*args)
    result=apply(staged,document_commit=raced)
    entry,=result['entries'];assert entry['status']=='review' and 'источников изменился' in entry['reason'],entry
    assert not list((operational['root']/'contract_documents').glob('*/*.pdf'))


def test_changed_native_guard_after_stage_has_no_automatic_rebase(operational):
    _,_,staged,_=prepare(operational)
    (operational['root']/'cumulative_terms.json').write_text(json.dumps({operational['old']:{'deadline':'2028-01-01'}}))
    with pytest.raises(disk.DiskSourceProblem,match='Реквизиты договора изменились'):
        apply(staged)
    assert not list((operational['root']/'contract_documents').glob('*/*.pdf'))


def test_native_removed_source_during_callback_is_not_restored(operational):
    row,raw,staged,_=prepare(operational);owner=disk.native_owner(row)
    sha=hashlib.sha256(raw).hexdigest();saved=[]
    def raced(*args):
        files.store(PROJECT,owner,'manual.pdf',raw)
        files.remove(PROJECT,owner['id'],sha,cut=CUT,acts={'document_source_ids':owner.get('document_source_ids') or []})
        path=operational['root']/'contract_documents'/owner['id']/(sha+'.json')
        saved.append((path,path.read_bytes()))
        return main.core._monitor_contract_disk_document_commit(*args)
    result=apply(staged,document_commit=raced)
    assert result['entries'][0]['status']=='review'
    assert saved[0][0].read_bytes()==saved[0][1] and json.loads(saved[0][1])['removed_at']


def test_retained_removed_source_in_current_operational_family_is_already(operational):
    row,=main.core._monitor_contract_disk_rows(PROJECT,CUT);owner=disk.native_owner(row)
    raw=pdf_for(owner);sha=hashlib.sha256(raw).hexdigest()
    files.store(PROJECT,owner,'manual.pdf',raw)
    files.remove(PROJECT,owner['id'],sha,cut=CUT,acts={'document_source_ids':owner.get('document_source_ids') or []})
    path=operational['root']/'contract_documents'/owner['id']/(sha+'.json');before=path.read_bytes()
    client=Client(source(raw,party='Учебный исполнитель',number='SOURCE-B'))
    with journal.namespace(PROJECT):
        view=disk.scan(PROJECT,URL,CUT,client=client,row_provider=main.core._monitor_contract_disk_rows)
    assert view['entries'][0]['status']=='already'
    assert path.read_bytes()==before


def test_pdf_matching_execution_but_wrong_documents_contract_is_review(operational):
    row,=main.core._monitor_contract_disk_rows(PROJECT,CUT)
    raw=pdf_for(disk.native_owner(row,execution=True))
    client=Client(source(raw,party='Учебный исполнитель',number='SOURCE-B'))
    with journal.namespace(PROJECT):
        view=disk.scan(PROJECT,URL,CUT,client=client,row_provider=main.core._monitor_contract_disk_rows)
        staged=disk.stage(PROJECT,view['revision'],[view['entries'][0]['id']],client=client,row_provider=main.core._monitor_contract_disk_rows)
    assert staged['entries'][0]['status']=='review'
    assert 'SOURCE-A' in staged['entries'][0]['reason'] and 'SOURCE-B' in staged['entries'][0]['reason']
    assert not list((operational['root']/'contract_documents').glob('*/*.pdf'))


def test_private_raw_callback_cannot_bypass_native_operational_selection(operational):
    register=contracts.build(PROJECT,CUT,include_history=False)
    rawrow=contracts.find_raw_row(register,operational['new']);raw=pdf_for(rawrow)
    entry={'filename':'wrong-route.pdf','native_context':None}
    with journal.namespace(PROJECT):
        policy=disk.capture_source_guard(PROJECT,rawrow,pdf=True)
        with pytest.raises(disk.DiskSourceProblem,match='операционный допуск'):
            main.core._monitor_contract_disk_document_commit(PROJECT,CUT,rawrow,entry,raw,policy)
    assert not list((operational['root']/'contract_documents').glob('*/*.pdf'))


def test_foreign_private_owner_or_context_is_rejected(operational):
    row,raw,staged,_=prepare(operational);entry=staged['entries'][0]
    bad={**entry,'native_context':{**entry['native_context'],'roles':{**entry['native_context']['roles'],'documents_raw_id':operational['old']}}}
    with journal.namespace(PROJECT):
        with pytest.raises(disk.DiskSourceProblem,match='выбор источников изменился'):
            main.core._monitor_contract_disk_document_commit(PROJECT,CUT,row,bad,raw,entry['source_policy'])
    assert not list((operational['root']/'contract_documents').glob('*/*.pdf'))


def test_partial_native_lock_set_cannot_expand_after_pins(operational):
    row,raw,staged,_=prepare(operational);entry=staged['entries'][0];owner=disk.native_owner(row)
    wanted=identity.binding_lock_paths(PROJECT,files.source_family(PROJECT,owner),correction=True)
    with journal.namespace(PROJECT),journal.locked(PROJECT):
        token=journal._HELD_NATIVE_LOCKS.set(frozenset({str(wanted[-1])}))
        try:
            with pytest.raises(files.ContractFilesProblem,match='Неполная блокировка'):
                files.store(PROJECT,owner,'partial.pdf',raw,source_policy=entry['source_policy'])
        finally:journal._HELD_NATIVE_LOCKS.reset(token)
    assert not list((operational['root']/'contract_documents').glob('*/*.pdf'))


def test_second_pdf_cannot_rebase_operational_guard_after_first_write(operational):
    row,=main.core._monitor_contract_disk_rows(PROJECT,CUT)
    first=pdf_for(disk.native_owner(row),'Приложение первое')
    second=pdf_for(disk.native_owner(row),'Приложение второе')
    client=Client({**source(first,party='Учебный исполнитель',number='SOURCE-B'),
                  **{path.replace('file.pdf','second.pdf'):data for path,data in source(second,party='Учебный исполнитель',number='SOURCE-B').items()}})
    with journal.namespace(PROJECT):
        view=disk.scan(PROJECT,URL,CUT,client=client,row_provider=main.core._monitor_contract_disk_rows)
        staged=disk.stage(PROJECT,view['revision'],[entry['id'] for entry in view['entries']],client=client,row_provider=main.core._monitor_contract_disk_rows)
    assert [entry['status'] for entry in staged['entries']]==['ready','ready']
    result=apply(staged)
    assert [entry['status'] for entry in result['entries']]==['imported','review']
    assert len(list((operational['root']/'contract_documents').glob('*/*.pdf')))==1


def test_legal_scope_includes_customer_for_retained_ks6():
    row=dict(contractor='ООО «Подрядчик»',customer='ООО «Первый заказчик»',contract='8',contract_date='2026-01-01')
    assert disk.legal_identity(row)!=disk.legal_identity({**row,'customer':'ООО «Второй заказчик»'})
