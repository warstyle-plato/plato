"""Tiny fixed owner-only sidecar route, no collector or original catalogue I/O."""
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from market_search import krt_catalogue_observation as obs
from test_krt_catalogue_observation_storage import saved

PATH='/auctions/krt/audit/catalogue-observation'
KEY='SYNTHETIC-OWNER-OBSERVATION-ONLY'


@pytest.fixture
def client(monkeypatch,tmp_path):
    import main
    import auction_search.api as api
    class NoRegistry:
        def __getattr__(self,name):pytest.fail('tiny route touched Registry: '+name)
    app=FastAPI();app.state.market_discovery_service=SimpleNamespace(krt=NoRegistry())
    monkeypatch.setattr(api,'KrtRegistry',lambda *a,**k:pytest.fail('tiny route constructed Registry'))
    monkeypatch.setattr(api,'KrtRanking',lambda *a,**k:SimpleNamespace(path=tmp_path/'krt/ranking.json'))
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'ambient-path-is-not-used'))
    api.install(app)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    monkeypatch.setenv('MARKET_CABINET_KEY','synthetic-market-not-owner')
    monkeypatch.setenv('AUCTIONS_VIEW_KEY','synthetic-view-not-owner')
    monkeypatch.setattr(main.core,'usage_admin_ids',lambda:[777])
    monkeypatch.setattr(main.core,'VERSION','0.29.63');monkeypatch.setattr(main.core,'COMMIT','a'*40)
    return TestClient(app,raise_server_exceptions=False),tmp_path/'krt'


@pytest.mark.parametrize('body',[{}, {'key':'wrong','session':''},
    {'key':'synthetic-market-not-owner','session':''},
    {'key':'synthetic-view-not-owner','session':'invalid'}])
def test_owner_gate_precedes_every_diagnostic_read(client,monkeypatch,body):
    api,_=client
    monkeypatch.setattr(obs,'read_view',lambda *a:pytest.fail('diagnostic I/O before owner gate'))
    response=api.post(PATH,json=body,headers={'X-Market-Key':'synthetic-market-not-owner'})
    assert response.status_code==403 and response.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('body',[{'key':KEY}, {'key':KEY,'session':'','refresh':True},
    {'key':KEY,'session':'','path':'/private'}, {'key':KEY,'session':True},
    {'key':KEY,'session':'','purpose':'new-client-phase'}])
def test_unknown_or_wrong_request_fields_are_rejected_before_sidecar_io(client,monkeypatch,body):
    api,_=client
    monkeypatch.setattr(obs,'read_view',lambda *a:pytest.fail('sidecar read for invalid request'))
    response=api.post(PATH,json=body)
    assert response.status_code==400


def test_duplicate_query_and_oversize_selectors_do_not_reach_sidecar(client,monkeypatch):
    api,_=client
    monkeypatch.setattr(obs,'read_view',lambda *a:pytest.fail('sidecar read for invalid request'))
    response=api.post(PATH+'?refresh=true',json={'key':KEY,'session':''})
    assert response.status_code==400
    response=api.post(PATH,content=json.dumps({'key':KEY})[:-1]+',"session":"","session":""}')
    assert response.status_code==400
    response=api.post(PATH,content=b'x'*16385,headers={'X-Developaid-Admin-Key':KEY})
    assert response.status_code==413


def test_missing_metadata_is_absent_without_source_or_catalogue_access(client,monkeypatch):
    api,root=client
    opened=[];original=obs.os.open
    def opening(path,*a,**k):
        opened.append(str(path));return original(path,*a,**k)
    monkeypatch.setattr(obs.os,'open',opening)
    response=api.post(PATH,json={'key':KEY,'session':''})
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    value=response.json()
    assert value['state']=='absent' and value['diagnostic'] is None
    assert value['collector_started'] is value['source_files_written'] is value['production_acceptance'] is False
    assert value['reader_runtime']=={'commit':'a'*40,'version':'0.29.63'}
    assert opened==[str(root)] and not root.exists()


def test_authorized_cached_read_returns_only_closed_sidecar_and_catalogue_stat(client,monkeypatch):
    api,root=client
    store,_=saved(root.parent)
    before=store.path.read_bytes()
    sidecar=(root/obs.NAME).read_bytes()
    open_calls=[];original=obs.os.open
    def opening(path,*a,**k):
        open_calls.append(str(path))
        assert str(path)!='catalogue.json'
        return original(path,*a,**k)
    monkeypatch.setattr(obs.os,'open',opening)
    response=api.post(PATH,json={'key':'','session':''},headers={'X-Developaid-Admin-Key':KEY})
    assert response.status_code==200 and len(response.content)<=obs.VIEW_LIMIT
    value=response.json()
    assert value['state']=='present' and value['current_catalogue_binding_check']=='stat_identity_matches'
    assert value['binding_check_basis']=='stat_identity_only_not_current_payload_rehash'
    assert obs.validate(value['diagnostic'])
    assert open_calls.count(obs.NAME)==2
    assert store.path.read_bytes()==before and (root/obs.NAME).read_bytes()==sidecar
    assert KEY not in response.text


def test_bypass_applies_to_exact_POST_only(client,monkeypatch):
    api,_=client
    monkeypatch.setattr(obs,'read_view',lambda *a:pytest.fail('non-exact route bypassed market realm'))
    for method,path in [('GET',PATH),('POST',PATH+'/'),('POST',PATH+'-other')]:
        response=api.request(method,path,json={'key':KEY,'session':''},follow_redirects=False)
        assert response.status_code in {401,403,405,404}


def test_unconfigured_owner_is_closed_even_when_general_site_is_open(client,monkeypatch):
    import main
    api,_=client
    monkeypatch.delenv('DEVELOPAID_ADMIN_KEY')
    monkeypatch.setattr(main.core,'usage_admin_ids',lambda:[])
    monkeypatch.setattr(obs,'read_view',lambda *a:pytest.fail('unconfigured owner read sidecar'))
    assert api.post(PATH,json={'key':'','session':''}).status_code==403
