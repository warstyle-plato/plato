"""Visible role-limited catalogue scope, synthetic metadata only."""
import pytest
import developaid_contract_disk_source as disk
from test_contract_disk_source import setup,Client,source,URL


def test_only_observed_allowed_roots_are_scanned_and_omissions_are_explicit():
    class Observed(Client):
        def __init__(self,values):super().__init__(values);self.paths=[]
        def metadata(self,url,path='/',offset=0):
            self.paths.append(path)
            return super().metadata(url,path,offset)
    client=Observed({**source(),'/Служебные/ГПР/old.xlsx':b'old','/Бухгалтер/archive/hidden.xlsx':b'x','/Строитель/hidden.pdf':b'y'})
    scope={};files=disk.catalog(client,URL,coverage=scope)
    assert len(files)==1
    assert scope['scanned_roots']==['Юрист']
    assert scope['not_scanned_roots']==['Бухгалтер','Служебные','Строитель']
    assert scope['scanned_files']==1 and scope['not_scanned_file_count'] is None
    assert 'Сметчик' not in scope['scanned_roots'] and 'Общие по проекту' not in scope['scanned_roots']
    assert not any(path.startswith(('/Служебные','/Бухгалтер','/Строитель')) for path in client.paths)
    assert 'включая прежние папки ГПР' in disk.scope_notice(scope)


def test_unknown_roots_only_are_not_claimed_as_scanned():
    client=Client({'/Служебные/ГПР/unknown.xlsx':b'unknown'})
    scope={};assert disk.catalog(client,URL,coverage=scope)==[]
    assert scope['scanned_roots']==[] and scope['scanned_files']==0
    assert 'не найдены' in disk.scope_notice(scope)
    assert scope['not_scanned_roots']==['Служебные']


def test_paginated_root_scope_includes_every_observed_skipped_root():
    class Paged(Client):
        def metadata(self,url,path='/',offset=0):
            if path=='/':
                values=[dict(name='Юрист',type='dir'),dict(name='Служебные',type='dir'),dict(name='Строитель',type='dir')]
                return dict(type='dir',_embedded=dict(total=3,items=values[offset:offset+1]))
            return super().metadata(url,path,offset)
    scope={};files=disk.catalog(Paged(source()),URL,coverage=scope)
    assert len(files)==1 and scope['scanned_roots']==['Юрист']
    assert scope['not_scanned_roots']==['Служебные','Строитель']


def test_scope_is_pinned_and_returned_through_stage_and_apply(setup,monkeypatch):
    monkeypatch.setattr(disk,'check_pdf',lambda *args:{'kind':'pdf'})
    import developaid_contract_files as native
    monkeypatch.setattr(native,'store',lambda *args,**kw:dict(already=True,sha256='c'*64))
    client=Client({**source(),'/Служебные/ГПР/old.xlsx':b'old'})
    view=disk.scan('Fixture',URL,'2026-11-25',client=client)
    staged=disk.stage('Fixture',view['revision'],[view['entries'][0]['id']],client=client)
    applied=disk.apply('Fixture',staged['stage_token'])
    for value in (view,staged,applied):
        assert value['scope']==view['scope'] and value['scope_notice']==view['scope_notice']
        assert value['scope']['not_scanned_roots']==['Служебные']
    saved=disk.load(disk.folder('Fixture')/'catalogs'/(view['revision']+'.json'))
    assert saved['scope']==view['scope']


@pytest.mark.parametrize('kind',['catalogs','stages'])
def test_v3_cached_catalog_or_stage_cannot_hide_scope(setup,kind):
    body=dict(schema='contract-disk-intake-v3',project_scope=disk.ns.project_scope('Fixture'),cut='2026-11-25',entries=[])
    token=disk.ns.digest(body);disk.save(disk.folder('Fixture')/kind/(token+'.json'),body)
    with pytest.raises(disk.DiskSourceProblem,match='прежней версией'):
        if kind=='catalogs':disk.stage('Fixture',token,['a'*64])
        else:disk.apply('Fixture',token)
