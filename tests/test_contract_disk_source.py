from __future__ import annotations
import hashlib
import json
import pytest
import developaid_contract_disk_source as disk
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import ks

URL='https://disk.yandex.ru/d/fixture-source'
ROW=dict(id='a'*64,contractor='ООО «Учебный подрядчик»',customer='ООО «Заказчик»',contract='A-12',contract_date='2026-01-01')

class Client:
    def __init__(self,files):
        self.files,self.downloads=files,[]
    def metadata(self,url,path='/',offset=0):
        children={}
        for name,raw in self.files.items():
            prefix=path.rstrip('/')+'/'
            if not name.startswith(prefix):
                continue
            tail=name[len(prefix):]
            first,sep,_=tail.partition('/')
            children[first]=dict(name=first,type='dir') if sep else dict(name=first,type='file',size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),modified='2026-11-25T10:00:00Z')
        values=list(children.values())
        return dict(type='dir',_embedded=dict(total=len(values),items=values[offset:offset+100]))
    def download(self,url,path,sha,size):
        self.downloads.append(path)
        return self.files[path]

@pytest.fixture
def setup(monkeypatch,tmp_path):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path)
    monitor._project_dir('Fixture').mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(disk,'rows',lambda *a:[dict(ROW)])
    return monkeypatch,tmp_path

def source(raw=b'%PDF-fixture',role='Юрист',party='Учебный подрядчик',number='A-12',kind='Договор'):
    return {f'/{role}/{party}/{number}/{kind}/file.pdf':raw}

def test_same_source_in_two_roles_is_one_item(setup):
    result=disk.scan('Fixture',URL,'2026-11-25',client=Client({**source(),**source(role='Сметчик')}))
    assert len(result['entries'])==1
    assert len(result['entries'][0]['locations'])==2
    assert result['entries'][0]['status']=='new'
    assert not list((monitor._project_dir('Fixture')/'contract_documents').glob('**/*.pdf'))

def test_same_bytes_in_other_contract_never_autoassigns(setup):
    mp,_=setup
    mp.setattr(disk,'rows',lambda *a:[ROW,{**ROW,'id':'b'*64,'contract':'B-22'}])
    result=disk.scan('Fixture',URL,'2026-11-25',client=Client({**source(),**source(number='B-22')}))
    assert len(result['entries'])==2
    assert all(x['status']=='review' for x in result['entries'])

@pytest.mark.parametrize('path,kind,layout',[
 ('/Юрист/Учебный подрядчик/A-12/ГПР/a.pdf','ГПР','current'),
 ('/Сметчик/КС-6/Учебный подрядчик/A-12/a.xlsx','КС-6а','legacy'),
 ('/Общие по проекту/Сводная по закрытию/all.xlsx',disk.COMMON,'current')])
def test_explicit_layouts(path,kind,layout):
    assert disk.location(path)['kind']==kind
    assert disk.location(path)['layout']==layout

@pytest.mark.parametrize('url',['http://disk.yandex.ru/d/fixture','https://evil.test/d/fixture','https://disk.yandex.ru@evil.test/d/fixture','https://disk.yandex.ru/d/fixture?token=private','https://disk.yandex.ru/d/fixture#fragment','https://disk.yandex.ru:443/d/fixture','https://127.0.0.1/d/fixture'])
def test_unsupported_source_fails_before_reads(setup,monkeypatch,url):
    monkeypatch.setattr(disk,'rows',lambda *a:pytest.fail('read before URL validation'))
    with pytest.raises(disk.DiskSourceProblem):
        disk.scan('Fixture',url,'2026-11-25')

def test_changed_and_missing_files_preserve_previous_checks(setup):
    first=disk.scan('Fixture',URL,'2026-11-25',client=Client(source(b'old')))
    second=disk.scan('Fixture',URL,'2026-11-25',client=Client(source(b'new')))
    assert second['entries'][0]['status']=='changed'
    third=disk.scan('Fixture',URL,'2026-11-25',client=Client({}))
    assert third['missing_previous_files']
    assert disk.load(disk.folder('Fixture')/'catalogs'/(first['revision']+'.json'))['entries'][0]['sha256']==hashlib.sha256(b'old').hexdigest()

def test_unknown_contract_is_held_for_native_initial_intake(setup,monkeypatch):
    monkeypatch.setattr(disk,'rows',lambda *a:[])
    result=disk.scan('Fixture',URL,'2026-11-25',client=Client(source()))
    assert result['entries'][0]['status']=='review'
    assert 'исходного PDF' in result['entries'][0]['reason']

def test_changed_download_never_reaches_native_parser(setup,monkeypatch):
    client=Client(source())
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    client.files={key:b'changed' for key in client.files}
    monkeypatch.setattr(disk,'check_pdf',lambda *a:pytest.fail('changed source admitted'))
    with pytest.raises(disk.DiskSourceProblem,match='не совпал'):
        disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)

def test_ks6_native_preflight_apply_and_hash_idempotency(setup,monkeypatch):
    raw=ks()
    parsed=ledgers.parse_archive(disk.archive_bytes([('KS.xlsx',raw)]),'fixture.zip')
    ledger=parsed['ledgers'][0]
    row={**ROW,**{k:ledger.get(k) for k in ('contractor','customer','contract','contract_date')}}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    path='/Сметчик/'+row['contractor']+'/'+row['contract']+'/КС-6а/KS.xlsx'
    client=Client({path:raw})
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert view['entries'][0]['status']=='new'
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='ready'
    assert not ledgers.list_snapshots('Fixture')
    with pytest.raises(disk.DiskSourceProblem,match='дату снимка'):
        disk.apply('Fixture',staged['stage_token'])
    applied=disk.apply('Fixture',staged['stage_token'],taken_at='2026-11-25')
    assert applied['entries'][0]['status']=='imported'
    assert len(ledgers.list_snapshots('Fixture'))==1
    repeated=disk.apply('Fixture',staged['stage_token'],taken_at='2026-11-26')
    assert repeated['entries'][0]['status']=='already'
    assert len(ledgers.list_snapshots('Fixture'))==1
    assert disk.scan('Fixture',URL,'2026-11-25',client=client)['entries'][0]['status']=='already'

def test_row_change_between_preview_and_apply_fails_before_write(setup,monkeypatch):
    client=Client(source())
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    monkeypatch.setattr(disk,'check_pdf',lambda *a:{'kind':'pdf'})
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    monkeypatch.setattr(disk,'rows',lambda *a:[{**ROW,'contract_date':'2026-02-02'}])
    with pytest.raises(disk.DiskSourceProblem,match='Реквизиты договора изменились'):
        disk.apply('Fixture',staged['stage_token'])
    assert not list((monitor._project_dir('Fixture')/'contract_documents').glob('**/*.pdf'))

def test_corrupted_or_cross_project_stage_cannot_be_applied(setup,monkeypatch):
    client=Client(source())
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    monkeypatch.setattr(disk,'check_pdf',lambda *a:{'kind':'pdf'})
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    path=disk.folder('Fixture')/'stages'/(staged['stage_token']+'.json')
    content=disk.load(path);content['project_scope']='f'*64;disk.save(path,content)
    with pytest.raises(disk.DiskSourceProblem,match='не подтверждена'):
        disk.apply('Fixture',staged['stage_token'])

def test_storage_symlink_is_refused(setup,tmp_path):
    target=tmp_path/'elsewhere';target.mkdir()
    (monitor._project_dir('Fixture')/'.contract_disk_sources').symlink_to(target,target_is_directory=True)
    with pytest.raises(disk.DiskSourceProblem):
        disk.scan('Fixture',URL,'2026-11-25',client=Client(source()))
    assert list(target.iterdir())==[]

def test_pdf_native_parties_preflight_and_retained_store(setup,monkeypatch):
    from tests.test_contract_pdf_intake import pdf,CUSTOMER,CONTRACTOR
    raw,_=pdf()
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='ready'
    assert set(staged['entries'][0]['proof']['parties'])=={'customer','contractor'}
    assert not list((monitor._project_dir('Fixture')/'contract_documents').glob('**/*.pdf'))
    result=disk.apply('Fixture',staged['stage_token'])
    assert result['entries'][0]['status']=='imported'
    sha=hashlib.sha256(raw).hexdigest()
    target=monitor._project_dir('Fixture')/'contract_documents'/ROW['id']/(sha+'.pdf')
    assert target.read_bytes()==raw
    assert disk.apply('Fixture',staged['stage_token'])['entries'][0]['status']=='already'


def test_reused_pdf_number_does_not_prove_another_counterparty(setup,monkeypatch):
    from tests.test_contract_pdf_intake import pdf,CUSTOMER
    raw,_=pdf()
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    client=Client(source(raw,number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'Роль и полное наименование' in staged['entries'][0]['reason']
    with pytest.raises(disk.DiskSourceProblem,match='Нет проверенных'):
        disk.apply('Fixture',staged['stage_token'])


def test_xlsx_in_gpr_folder_is_visible_and_held_not_imported_as_ks6(setup):
    client=Client({'/Сметчик/Учебный подрядчик/A-12/ГПР/Gantt.xlsx':b'xlsx-fixture'})
    result=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert len(result['entries'])==1
    assert result['entries'][0]['status']=='review'
    assert result['entries'][0]['family']==''
    assert not client.downloads


def test_two_legal_forms_with_same_folder_alias_stay_ambiguous(setup,monkeypatch):
    monkeypatch.setattr(disk,'rows',lambda *a:[ROW,{**ROW,'id':'b'*64,'contractor':'АО «Учебный подрядчик»'}])
    result=disk.scan('Fixture',URL,'2026-11-25',client=Client(source()))
    assert result['entries'][0]['status']=='review'
    assert not result['entries'][0]['contract_id']

def test_missing_contract_date_cannot_be_proved_by_folder_name(setup,monkeypatch):
    from tests.test_contract_pdf_intake import pdf,CUSTOMER,CONTRACTOR
    raw,_=pdf()
    row={**ROW,'contract':'88-ТСТ','contract_date':None,'customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'Дата договора не подтверждена' in staged['entries'][0]['reason']


def test_native_ks6_customer_mismatch_is_not_overruled_by_folder(setup,monkeypatch):
    raw=ks();parsed=ledgers.parse_archive(disk.archive_bytes([('KS.xlsx',raw)]),'fixture.zip')
    ledger=parsed['ledgers'][0]
    row={**ROW,**{k:ledger.get(k) for k in ('contractor','contract','contract_date')},'customer':'ООО «Другой заказчик»'}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    path='/Сметчик/'+row['contractor']+'/'+row['contract']+'/КС-6а/KS.xlsx'
    client=Client({path:raw});view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'Реквизиты внутри КС-6а' in staged['entries'][0]['reason']
    assert not ledgers.list_snapshots('Fixture')


def test_native_pdf_negated_party_role_is_held(setup,monkeypatch):
    from tests.test_contract_pdf_intake import CUSTOMER,CONTRACTOR
    from tests.test_contract_pdf_intake_integrity import custom_pdf
    raw,_=custom_pdf(contractor_clause=f'{CONTRACTOR}, не именуемое в дальнейшем «Подрядчик»')
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'Роль и полное наименование' in staged['entries'][0]['reason']


def test_retained_pdf_hash_name_does_not_prove_changed_original(setup,monkeypatch):
    from tests.test_contract_pdf_intake import pdf,CUSTOMER,CONTRACTOR
    raw,_=pdf();sha=hashlib.sha256(raw).hexdigest()
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    disk.apply('Fixture',staged['stage_token'])
    target=monitor._project_dir('Fixture')/'contract_documents'/ROW['id']/(sha+'.pdf')
    target.write_bytes(b'changed')
    with pytest.raises(disk.DiskSourceProblem,match='PDF не совпал'):
        disk.scan('Fixture',URL,'2026-11-25',client=client)


def test_native_cover_letter_without_contract_header_never_reaches_store(setup,monkeypatch):
    from tests.test_contract_pdf_intake import CUSTOMER,CONTRACTOR
    from tests.test_contract_pdf_intake_integrity import custom_pdf
    import developaid_contract_files as files
    raw,_=custom_pdf(header='Сопроводительное письмо по общим вопросам')
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    assert files._record(hashlib.sha256(raw).hexdigest(),'cover.pdf',raw,'now')['contract'] is None
    client=Client(source(raw,party='Подрядчик Учебный',number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'номер и дата договора' in staged['entries'][0]['reason']
    monkeypatch.setattr(files,'store',lambda *a,**kw:pytest.fail('headerless source assigned from folder'))
    with pytest.raises(disk.DiskSourceProblem,match='Нет проверенных'):
        disk.apply('Fixture',staged['stage_token'])


@pytest.mark.parametrize('parsed_contract',[
 None,{},[],True,'88-ТСТ',{'number':'88-ТСТ'},{'date':'2026-02-01'},
 {'number':'','date':'2026-02-01'},{'number':'   ','date':'2026-02-01'},
 {'number':True,'date':'2026-02-01'},{'number':['88-ТСТ'],'date':'2026-02-01'},
 {'number':'88-ТСТ','date':None},{'number':'88-ТСТ','date':'01.02.2026'},
 {'number':'88-ТСТ','date':{'date':'2026-02-01'}},
 {'number':'88-ТСТ','date':'2026-02-30'}])
def test_partial_or_malformed_parsed_contract_is_not_autoassigned(setup,monkeypatch,parsed_contract):
    import developaid_contract_files as files
    raw=b'%PDF-synthetic-header-case'
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01'}
    monkeypatch.setattr(disk,'rows',lambda *a:[row])
    monkeypatch.setattr(files,'_record',lambda *a,**kw:{'contract':parsed_contract,'scan':None})
    monkeypatch.setattr(disk,'pdf_party_proofs',lambda *a:pytest.fail('party names cannot supply missing header'))
    monkeypatch.setattr(files,'store',lambda *a,**kw:pytest.fail('malformed header reached native store'))
    client=Client(source(raw,number='88-ТСТ'))
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'номер и дата договора' in staged['entries'][0]['reason']
    with pytest.raises(disk.DiskSourceProblem,match='Нет проверенных'):
        disk.apply('Fixture',staged['stage_token'])
