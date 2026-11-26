"""Owner's four-role structure; role hints never replace native body evidence."""
import copy
import hashlib

import pytest

import developaid_contract_disk_source as disk
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_contract_disk_source import setup, Client, URL, ROW


@pytest.mark.parametrize('path,kind,layout',[
    ('/Юрист/Фирма/88-ТСТ/Договор.pdf',disk.LEGAL_DOCUMENTS,'current'),
    ('/Юрист/Фирма/88-ТСТ/Доп1-1.pdf',disk.LEGAL_DOCUMENTS,'current'),
    ('/Юрист/Фирма/88-ТСТ/Доп1-2.pdf',disk.LEGAL_DOCUMENTS,'current'),
    ('/Юрист/Фирма/88-ТСТ/РДС.xlsx',disk.LEGAL_DOCUMENTS,'current'),
    ('/Юрист/Фирма/88-ТСТ/Приложения/ГПР.pdf',disk.LEGAL_DOCUMENTS,'current'),
    ('/Сметчик/Фирма/88-ТСТ/КС-2/Акт.pdf','КС-2','current'),
    ('/Сметчик/Фирма/88-ТСТ/КС-6/Книга.xlsm','КС-6а','current'),
    ('/Сметчик/Фирма/88-ТСТ/КС-6а/Книга.xlsx','КС-6а','legacy'),
    ('/Юрист/Фирма/88-ТСТ/Договор/Договор.pdf','Договор','legacy'),
    ('/Юрист/Фирма/88-ТСТ/Дополнительные соглашения/Доп.pdf','Дополнительные соглашения','legacy'),
    ('/Юрист/ГПР/Фирма/88-ТСТ/ГПР.pdf','ГПР','legacy'),
    ('/Сметчик/КС-6/Фирма/88-ТСТ/Книга.xlsx','КС-6а','legacy'),
    ('/Общие по проекту/Сводная по закрытию/Все.xlsx',disk.COMMON,'current'),
])
def test_current_owner_paths_and_explicit_legacy_paths(path,kind,layout):
    loc=disk.location(path)
    assert loc['kind']==kind and loc['layout']==layout


@pytest.mark.parametrize('path',[
    '/Сметчик/Фирма/88-ТСТ/Договор.pdf',
    '/Строитель/Фирма/88-ТСТ/ГПР.pdf',
    '/Бухгалтер/Фирма/88-ТСТ/Оплата.xlsx',
    '/Юрист/Фирма/88-ТСТ/Приложения/Новая папка/Файл.pdf',
    '/Юрист/Фирма/88-ТСТ/Доп 1-1/Приложение.pdf',
])
def test_unrecognized_or_structure_only_paths_never_promise_intake(path):
    assert disk.location(path) is None


def native_legal_pdf(kind):
    from tests.test_contract_pdf_intake import pdf,CUSTOMER,CONTRACTOR
    if kind in {'contract','agreement'}:
        return pdf(agreement=kind=='agreement')[0]
    from tests.test_contract_documents_are_read_from_their_tables import pymupdf,estimate_pdf,_text
    if kind=='rds':
        annex=estimate_pdf(title=('Приложение № 1 к Договору подряда № 88-ТСТ от 01.02.2026',
            'Расчёт договорной стоимости'),stamp=False)
    else:
        from tests.test_contract_documents_of_the_weekly_layout import weekly_pdf
        annex=weekly_pdf()
    raw=pdf()[0]
    with pymupdf.open(stream=raw,filetype='pdf') as document, pymupdf.open(stream=annex,filetype='pdf') as other:
        document.insert_pdf(other)
        return document.tobytes()


def native_act_pdf():
    from tests.test_contract_pdf_intake import CUSTOMER,CONTRACTOR
    from tests.test_contract_fact_dates_ks6_periods_by_acts import act_pdf
    from tests.test_contract_documents_are_read_from_their_tables import pymupdf,_text
    raw=act_pdf(contract='88-ТСТ',contract_date='01.02.2026')
    with pymupdf.open(stream=raw,filetype='pdf') as document:
        _text(document[0],40,40,CUSTOMER+', именуемое в дальнейшем «Заказчик»')
        _text(document[0],40,55,CONTRACTOR+', именуемое в дальнейшем «Подрядчик»')
        return document.tobytes()


def row_and_scan(setup,monkeypatch,raw,path):
    from tests.test_contract_pdf_intake import CUSTOMER,CONTRACTOR
    row={**ROW,'contract':'88-ТСТ','contract_date':'2026-02-01','customer':CUSTOMER,'contractor':CONTRACTOR}
    monkeypatch.setattr(disk,'rows',lambda *args:[row])
    client=Client({path:raw})
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert len(view['entries'])==1 and view['entries'][0]['status']=='new'
    return row,client,view


@pytest.mark.parametrize('kind,filename,types',[
    ('contract','Акт КС-2.pdf',['Документ договора']),
    ('agreement','Просто файл.pdf',['Дополнительное соглашение']),
    ('rds','Доп 1-2.pdf',['РДС']),
    ('gpr','Договор.pdf',['ГПР']),
])
def test_legal_semantic_type_comes_from_native_pdf_not_filename_or_type_folder(setup,monkeypatch,kind,filename,types):
    raw=native_legal_pdf(kind)
    path='/Юрист/Подрядчик Учебный/88-ТСТ/'+filename
    row,client,view=row_and_scan(setup,monkeypatch,raw,path)
    result=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    entry=result['entries'][0]
    assert entry['status']=='ready',entry.get('reason')
    assert entry['proof']['document_types']==types
    assert entry['proof']['semantic_basis']=='native_pdf_content'
    assert set(entry['proof']['parties'])=={'customer','contractor'}
    assert not list((monitor._project_dir('Fixture')/'contract_documents').glob('**/*.pdf'))
    assert not ledgers.list_snapshots('Fixture')
    assert len(client.downloads)==1


def test_native_act_body_is_accepted_only_in_smeta_ks2_even_when_filename_says_contract(setup,monkeypatch):
    raw=native_act_pdf()
    row,client,view=row_and_scan(setup,monkeypatch,raw,'/Сметчик/Подрядчик Учебный/88-ТСТ/КС-2/Договор.pdf')
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='ready',staged['entries'][0].get('reason')
    assert staged['entries'][0]['proof']['document_types']==['КС-2']
    assert not ledgers.list_snapshots('Fixture')


@pytest.mark.parametrize('family',['contract_in_ks2','act_in_legal','same_bytes_cross_roles'])
def test_native_body_refuses_wrong_role_or_mixed_purposes_before_apply(setup,monkeypatch,family):
    raw=native_act_pdf() if family=='act_in_legal' else native_legal_pdf('contract')
    path='/Юрист/Подрядчик Учебный/88-ТСТ/Приложение.pdf' if family=='act_in_legal' else '/Сметчик/Подрядчик Учебный/88-ТСТ/КС-2/Договор.pdf'
    row,client,view=row_and_scan(setup,monkeypatch,raw,path)
    if family=='same_bytes_cross_roles':
        client.files['/Юрист/Подрядчик Учебный/88-ТСТ/Договор.pdf']=raw
        view=disk.scan('Fixture',URL,'2026-11-25',client=client)
        assert len(view['entries'])==1 and len(view['entries'][0]['locations'])==2
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'КС-2' in staged['entries'][0]['reason']
    with pytest.raises(disk.DiskSourceProblem,match='Нет проверенных'):
        disk.apply('Fixture',staged['stage_token'])
    assert not ledgers.list_snapshots('Fixture')
    assert not list((monitor._project_dir('Fixture')/'contract_documents').glob('**/*.pdf'))


@pytest.mark.parametrize('path',[
    '/Сметчик/Учебный подрядчик/A-12/РДС/Расчёт.pdf',
    '/Юрист/Учебный подрядчик/A-12/КС-2/Акт.pdf',
    '/Юрист/Учебный подрядчик/A-12/КС-6а/Книга.xlsx',
])
def test_old_wrong_role_folders_are_visible_issues_without_download_or_admission(setup,path):
    client=Client({path:b'not-native-source'})
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert not view['entries'] and len(view['issues'])==1
    assert view['issues'][0]['status']=='review'
    assert not client.downloads


@pytest.mark.parametrize('path',[
    '/Юрист/Учебный подрядчик/A-12/ГПР.xlsx',
    '/Юрист/Учебный подрядчик/A-12/Приложения/РДС.xlsm',
    '/Сметчик/Учебный подрядчик/A-12/КС-2/Акт.xlsx',
    '/Сметчик/Учебный подрядчик/A-12/КС-6/Ведомость.pdf',
])
def test_wrong_file_family_is_held_without_reinterpreting_it_as_ks6(setup,path):
    client=Client({path:b'fixture'})
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert view['entries'][0]['status']=='review' and not view['entries'][0]['family']
    assert not client.downloads


def test_builder_and_accountant_are_structure_only_with_explicit_unknown_coverage(setup):
    client=Client({'/Строитель/Фирма/A-12/ГПР.pdf':b'x','/Бухгалтер/Фирма/A-12/Оплаты.xlsx':b'y'})
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert view['entries']==[] and view['scope']['scanned_files']==0
    assert view['scope']['not_scanned_roots']==['Бухгалтер','Строитель']
    assert view['scope']['not_scanned_file_count'] is None
    assert not client.downloads


@pytest.mark.parametrize('kind',['catalogs','stages'])
def test_old_v4_admission_cannot_skip_owner_role_policy(setup,kind):
    body=dict(schema='contract-disk-intake-v4',project_scope=disk.ns.project_scope('Fixture'),cut='2026-11-25',entries=[])
    token=disk.ns.digest(body);disk.save(disk.folder('Fixture')/kind/(token+'.json'),body)
    with pytest.raises(disk.DiskSourceProblem,match='прежней версией'):
        if kind=='catalogs':disk.stage('Fixture',token,['a'*64])
        else:disk.apply('Fixture',token)


def test_unknown_legal_attachment_does_not_invent_contract_agreement_tables_or_fact(setup,monkeypatch):
    from tests.test_contract_pdf_intake import CUSTOMER,CONTRACTOR
    from tests.test_contract_documents_are_read_from_their_tables import pymupdf,_page,_text
    import developaid_contract_documents as documents
    with pymupdf.open() as document:
        page=_page(document)
        for i,text in enumerate(['Сопроводительное письмо',
            'к Договору подряда № 88-ТСТ от 01.02.2026',
            CUSTOMER+', именуемое в дальнейшем «Заказчик»',
            CONTRACTOR+', именуемое в дальнейшем «Подрядчик»',
            'Приложения и изменения расчёта настоящим письмом не утверждаются.']):
            _text(page,40,40+18*i,text)
        raw=document.tobytes()
    native=documents.read(raw)
    assert native.get('agreement') is None and not native.get('estimates') and not native.get('schedule') and not native.get('act')
    row,client,view=row_and_scan(setup,monkeypatch,raw,'/Юрист/Подрядчик Учебный/88-ТСТ/Доп 1-1 ГПР.pdf')
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='ready',staged['entries'][0].get('reason')
    assert staged['entries'][0]['proof']['document_types']==['Документ договора']
    assert not ledgers.list_snapshots('Fixture')
    assert not list((monitor._project_dir('Fixture')/'contract_documents').glob('**/*.pdf'))


def test_retained_native_act_in_wrong_role_is_not_claimed_already_accepted(setup,monkeypatch):
    import developaid_contract_files as files
    raw=native_act_pdf()
    path='/Юрист/Подрядчик Учебный/88-ТСТ/Неизвестное приложение.pdf'
    row,client,view=row_and_scan(setup,monkeypatch,raw,path)
    stored=files.store('Fixture',row,'trusted-native-act.pdf',raw)
    assert not stored.get('already')
    refreshed=disk.scan('Fixture',URL,'2026-11-25',client=client)
    assert refreshed['entries'][0]['status']!='already'
    staged=disk.stage('Fixture',refreshed['revision'],[refreshed['entries'][0]['id']],client=client)
    assert staged['entries'][0]['status']=='review'
    assert 'КС-2' in staged['entries'][0]['reason']
    assert not ledgers.list_snapshots('Fixture')
