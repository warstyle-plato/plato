import json
import threading
import time
import pytest
from fastapi.testclient import TestClient
import main as wrapper
import developaid_contract_disk_source as disk
import developaid_monitor as monitor

KEY='synthetic-disk-owner-key'
@pytest.fixture
def api(monkeypatch,tmp_path):
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','')
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    monitor._project_dir('Fixture')
    return TestClient(wrapper.core.app),tmp_path

def post(client,path,**payload):
    return client.post('/monitor/contracts/disk/'+path,json=dict(key=KEY,project='Fixture',cut='2026-11-25',**payload))

def poll(client,ticket,**auth):
    for _ in range(200):
        response=client.post('/monitor/contracts/disk/result',json=dict(key=KEY,ticket=ticket,**auth))
        if response.status_code!=202:
            return response
        time.sleep(.01)
    raise AssertionError('worker did not finish')

@pytest.mark.parametrize('path,fields',[
 ('scan',dict(source='https://disk.yandex.ru/d/fixture-source')),
 ('stage',dict(revision='a'*64,item_ids=['b'*64])),
 ('apply',dict(stage_token='c'*64,taken_at='2026-11-25')),
 ('result',dict(ticket='d'*32))])
def test_current_key_is_checked_before_any_disk_read(api,monkeypatch,path,fields):
    client,_=api
    monkeypatch.setattr(wrapper.core,'_monitor_cumulative_execute',lambda *a:pytest.fail('worker before current key'))
    data=dict(key='wrong',**fields)
    if path!='result':
        data.update(project='Fixture',cut='2026-11-25')
    response=client.post('/monitor/contracts/disk/'+path,json=data)
    assert response.status_code==403
    assert response.headers['cache-control']=='private, no-store'


def test_background_job_is_scoped_and_does_not_persist_credentials(api,monkeypatch):
    client,root=api
    release=threading.Event();calls=[]
    def scan(**values):
        assert 'key' not in values and 'session' not in values
        calls.append(values)
        assert release.wait(10)
        return dict(revision='a'*64,entries=[],issues=[],missing_previous_files=[],notice='checked')
    monkeypatch.setattr(disk,'scan',scan)
    body=dict(source='https://disk.yandex.ru/d/fixture-source',ticket='1'*32,session='synthetic-session')
    try:
        before=time.monotonic();response=post(client,'scan',**body)
        assert response.status_code==202 and time.monotonic()-before<1
        assert post(client,'scan',**body).json()['ticket']=='1'*32
    finally:
        release.set()
    completed=poll(client,'1'*32,session='synthetic-session')
    assert completed.status_code==200 and completed.json()['disk_source']['revision']=='a'*64
    assert len(calls)==1
    foreign=client.post('/monitor/contracts/result',json=dict(key=KEY,ticket='1'*32,session='synthetic-session'))
    assert foreign.status_code==404
    private=b''.join(p.read_bytes() for p in (root/'monitor'/'.cumulative_jobs').iterdir() if p.is_file())
    assert KEY.encode() not in private and b'synthetic-session' not in private

@pytest.mark.parametrize('item_ids',[['bad'],['a'*64,'a'*64],['b'*64]*21])
def test_stage_accepts_only_bounded_unique_catalog_ids(api,item_ids):
    client,_=api
    assert post(client,'stage',revision='c'*64,item_ids=item_ids).status_code==422


def test_scan_error_does_not_print_or_return_the_share_token(api,monkeypatch):
    client,_=api
    monkeypatch.setattr(disk,'scan',lambda **kw:(_ for _ in ()).throw(disk.DiskSourceProblem('Диск не отдал папку или файл.')))
    token='privateSourceSuffix'
    response=post(client,'scan',source='https://disk.yandex.ru/d/'+token,ticket='2'*32)
    result=poll(client,'2'*32)
    assert result.status_code==200 and result.json()['ok'] is False
    assert token not in result.text


@pytest.mark.parametrize('private',['_source_policy','_disk_context','_disk_owner_guard','row_provider','document_commit','book_commit'])
def test_public_disk_request_rejects_server_internal_policy(api,private):
    client,_=api
    response=post(client,'apply',stage_token='c'*64,**{private:{'forged':True}})
    assert response.status_code==422


def test_normal_document_upload_cannot_supply_internal_disk_policy(api,monkeypatch):
    import base64
    client,root=api;seen=[]
    def execute(operation,payload,archive=b''):
        seen.append(payload)
        return {'ok':True,'document':{'sha256':'f'*64}}
    monkeypatch.setattr(wrapper.core,'_monitor_cumulative_execute',execute)
    response=client.post('/monitor/contracts/document-upload',json=dict(key=KEY,project='Fixture',cut='2026-11-25',
        contract_id='a'*64,filename='test.pdf',content_base64=base64.b64encode(b'%PDF-synthetic').decode(),ticket='3'*32,
        _source_policy={'family':['b'*64]},_disk_context={'view':'operational'},_disk_owner_guard='f'*64))
    assert response.status_code==202
    for _ in range(100):
        final=client.post('/monitor/contracts/result',json=dict(key=KEY,ticket='3'*32))
        if final.status_code!=202:break
        time.sleep(.01)
    assert final.status_code==200 and final.json()['ok']
    assert seen and not any(key.startswith('_disk') or key=='_source_policy' for key in seen[0])
