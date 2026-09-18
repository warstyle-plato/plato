"""Offline parity, durable snapshots, transactional updates and loopback access."""
import copy
import hashlib
import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from desktop.app import create_app
from desktop.runtime import load_engine
from desktop.storage import Conflict, Store
from desktop_reference_pack import canonical, make_pack, validate_pack


@pytest.fixture
def desktop(tmp_path):
    # load_engine configures a dedicated desktop process. Keep its environment
    # isolated when the repository runs these tests in the main pytest process.
    with patch.dict(os.environ, dict(os.environ), clear=True):
        core = load_engine(tmp_path)
    store = Store(tmp_path / 'desktop.sqlite3')
    app = create_app(core, store, 'test-token', 'http://127.0.0.1:8765')
    with TestClient(app, base_url='http://127.0.0.1:8765',
                    headers={'X-DevelopAid-Token': 'test-token'}) as client:
        yield core, store, client


def request_for(client):
    boot = client.get('/api/bootstrap').json()
    return {**boot['form']['defaults'], 'rates': [], 'sensitivity': False,
            'project_name': 'Тестовый проект',
            'reference_version': boot['references']['pack']['version']}


def test_local_calculation_matches_the_same_engine_without_network(desktop, monkeypatch):
    core, store, client = desktop
    def offline(*args, **kwargs):
        raise AssertionError('Calculation must not access the network')
    monkeypatch.setattr('urllib.request.urlopen', offline)
    request = request_for(client)
    expected = core._run_authoritative_model(request['inputs'], request['tep'], [], request['phasing'])
    response = client.post('/api/calculate', json=request)
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['result']['summary'] == expected['consolidated']['summary']
    assert record['result']['engine_version'] == core.VERSION
    # Opening persisted calculations never recomputes them.
    monkeypatch.setattr(core, '_run_authoritative_model', offline)
    saved = client.post('/api/projects', json={'name':'Тест', 'snapshot_id':record['snapshot_id']}).json()
    reopened = Store(store.path)
    assert reopened.projects()[0]['id'] == saved['id']
    assert client.get('/api/snapshots/' + saved['snapshot_id']).json() == record


def test_reference_update_is_atomic_and_does_not_rewrite_projects(desktop, monkeypatch):
    core, store, client = desktop
    result = client.post('/api/calculate', json=request_for(client)).json()
    saved = client.post('/api/projects', json={'name':'Старая модель', 'snapshot_id':result['snapshot_id']}).json()
    pack = make_pack(core)
    first = next(iter(pack['class_presets'].values()))
    first['apartment_price_th'] += 1
    pack['version'] = hashlib.sha256(canonical({k:v for k,v in pack.items() if k!='version'}).encode()).hexdigest()
    monkeypatch.setattr('desktop.app.fetch_pack', lambda:pack)
    response = client.post('/api/references/update', json={})
    assert response.status_code == 200
    assert response.json()['pack']['version'] != result['reference_version']
    assert store.snapshot(saved['snapshot_id'])['reference_version'] == result['reference_version']
    assert store.snapshot(saved['snapshot_id'])['result'] == result['result']
    # A failed or damaged update leaves the last good pack active.
    pack['version'] = 'bad'
    assert client.post('/api/references/update', json={}).status_code == 503
    assert store.pack()['pack']['version'] == response.json()['pack']['version']


def test_offline_update_keeps_the_bundled_database(desktop, monkeypatch):
    _, store, client = desktop
    before = store.pack()
    def offline():
        raise OSError('No network')
    monkeypatch.setattr('desktop.app.fetch_pack', offline)
    assert client.post('/api/references/update', json={}).status_code == 503
    assert store.pack() == before


def test_local_api_rejects_other_sites_missing_tokens_and_rebinding(desktop):
    _, _, client = desktop
    assert client.get('/api/bootstrap', headers={'X-DevelopAid-Token':''}).status_code == 403
    assert client.get('/api/bootstrap', headers={'Origin':'https://example.com'}).status_code == 403
    assert client.get('/', headers={'Host':'example.com'}).status_code == 403
    assert client.get('/').status_code == 200
    assert client.get('/telegram/webhook').status_code == 404
    assert client.get('/static/unknown').status_code == 404


def test_save_conflict_and_revision_history(desktop):
    _, store, client = desktop
    s = client.post('/api/calculate', json=request_for(client)).json()['snapshot_id']
    p = store.save_project('Один', s)
    store.save_project('Два', s, p['id'], 1)
    with pytest.raises(Conflict):
        store.save_project('Устаревшее окно', s, p['id'], 1)
    assert [r['name'] for r in store.history(p['id'])] == ['Два', 'Один']
    assert Store(store.path).projects()[0]['name'] == 'Два'


def test_exports_share_the_saved_bundle_without_another_calculation(desktop, monkeypatch):
    core, _, client = desktop
    request = request_for(client)
    request['tep']['apartments']['transfer'] = 5000
    record = client.post('/api/calculate', json=request).json()
    def no_second_calculation(*args, **kwargs):
        raise AssertionError('The saved authoritative bundle must be reused')
    monkeypatch.setattr(core, '_run_authoritative_model', no_second_calculation)
    base = '/api/snapshots/' + record['snapshot_id'] + '/export/'
    pdf = client.get(base+'pdf')
    assert pdf.status_code == 200, pdf.text[:400] if pdf.status_code != 200 else ''
    assert pdf.content.startswith(b'%PDF')
    # Formulas in Excel are evaluated separately by the existing workbook evaluator.
    xlsx = client.get(base+'xlsx')
    assert xlsx.status_code == 200, xlsx.text[:400] if xlsx.status_code != 200 else ''
    assert xlsx.content.startswith(b'PK')
    assert client.get(base+'json').json()['result'] == record['result']


def test_exports_refuse_to_relabel_old_engine_results(desktop, monkeypatch):
    core, _, client = desktop
    record = client.post('/api/calculate', json=request_for(client)).json()
    monkeypatch.setattr(core, 'VERSION', 'future-version')
    base = '/api/snapshots/' + record['snapshot_id'] + '/export/'
    assert client.get(base+'pdf').status_code == 409
    assert client.get(base+'xlsx').status_code == 409
    assert client.get(base+'json').status_code == 200


def test_reference_pack_contains_public_allowlisted_data_only(desktop):
    core, _, _ = desktop
    pack = make_pack(core)
    assert set(pack) == {'schema_version','engine_version','class_presets','field_units','normatives','version'}
    assert validate_pack(pack, core) == pack
    broken = copy.deepcopy(pack)
    broken['engine_version'] = 'future-version'
    broken['version'] = hashlib.sha256(canonical({k:v for k,v in broken.items() if k!='version'}).encode()).hexdigest()
    with pytest.raises(ValueError, match='версия приложения'):
        validate_pack(broken, core)


def test_site_lookup_filters_parcels_and_rejects_partial_numbers(desktop, monkeypatch):
    from desktop import site
    _, _, client = desktop
    calls=[]
    def fake(path, payload):
        calls.append((path,payload))
        return {'results': [
            {'found':True,'kind':'land','cadastral_number':'77:09:0004014:13','address':'Москва'},
            {'found':True,'kind':'building','cadastral_number':'77:09:0004014:14'},
            {'found':False,'kind':'land','cadastral_number':'77:09:0004014:15'}],
            'warnings':['Проверьте состав территории']}
    monkeypatch.setattr(site,'remote',fake)
    result=client.post('/api/site/lookup',json={'query':'Москва, Мишина, 46'})
    assert result.status_code==200
    assert [x['cadastral_number'] for x in result.json()['items']]==['77:09:0004014:13']
    assert result.json()['warnings']==['Проверьте состав территории']
    assert client.post('/api/site/lookup',json={'query':'77:09:0004014:13, 77:09:ошибка'}).status_code==400
    assert len(calls)==1


def test_site_preview_is_explicit_and_does_not_mutate_saved_projects(desktop, monkeypatch):
    from desktop import site
    core,store,client=desktop
    before=client.get('/api/bootstrap').json()
    number='77:09:0004014:13'
    def fake(path,payload):
        if path=='/cadastral/analyze':
            return {'recognized':[number],'territory':{'inside_moscow':True,'area_ha':.6509}}
        assert path=='/cadastral/tep-server'
        assert payload['cadastral_analysis']['recognized']==[number]
        return {'normalized':{'site_area_ha':.6509},'source':{'format':'Штатный калькулятор ГлавАПУ'},
                'mappings':{'inputs':{'land_rights_cost_mln':12},
                            'tep':{'apartments':{'saleable':5000,'gns':8000}}},'warnings':[]}
    monkeypatch.setattr(site,'remote',fake)
    response=client.post('/api/site/preview',json={'cadastral_numbers':[number]})
    assert response.status_code==200,response.text
    p=response.json();assert p['inputs_patch']['purchase_price_mln']==0
    assert p['inputs_patch']['land_rights_cost_mln']==12
    assert 'apartment_price_th' not in p['inputs_patch']
    assert p['tep']['apartments']['saleable']==5000
    assert p['tep']['offices']['gns']==0
    assert p['inputs_patch']['_desktop_site']['cadastral_numbers']==[number]
    assert client.get('/api/bootstrap').json()==before
    monkeypatch.setattr(site,'remote',lambda *_:{'recognized':[],'territory':{}})
    assert client.post('/api/site/preview',json={'cadastral_numbers':[number]}).status_code==400
    assert client.get('/api/bootstrap').json()==before


def test_site_mo_retains_server_provenance_and_requires_all_parcels(desktop, monkeypatch):
    from desktop import site
    _,_,client=desktop
    number='50:01:0000001:1'
    data={'territory':{'cadastral_numbers':[number],'site_area_ha':2},
          'inputs':{'land_rights_cost_mln':7},'tep':{'apartments':{'gns':100,'saleable':70}},
          'density_sqm_per_ha':30000,'warnings':['Предварительный расчёт']}
    monkeypatch.setattr(site,'remote',lambda path,payload:data)
    p=client.post('/api/site/preview',json={'cadastral_numbers':[number],'region':'mo'}).json()
    assert p['inputs_patch']['vri_region']=='mo'
    assert p['inputs_patch']['_mo_calc']['territory']['site_area_ha']==2
    assert p['warnings']==data['warnings']
    data['territory']['cadastral_numbers']=[]
    assert client.post('/api/site/preview',json={'cadastral_numbers':[number],'region':'mo'}).status_code==400
