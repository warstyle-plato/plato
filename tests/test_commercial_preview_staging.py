"""Staging uses the real root application and native commercial panel."""
import pytest
from fastapi.testclient import TestClient
import commercial_preview
from developaid_commercial_form import field_keys

client = TestClient(commercial_preview.app)


def test_current_developaid_root_contains_native_commercial_tab():
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['X-DevelopAid-Surface'] == 'ia-main'
    assert 'Нежилая экономика' in response.text
    assert 'id="commercial" class="panel"' in response.text
    assert 'id="ce-form"' in response.text
    assert 'src="/commercial-beta"' not in response.text
    assert '/ia/assets/overlay.js' in response.text
    assert 'id="ce-monthly-details"' in response.text
    assert client.get('/commercial-beta').status_code == 404


def test_form_schema_is_relevant_and_defaults_cover_all_visible_fields():
    schema = client.get('/api/commercial/form').json()
    for asset in ('office', 'retail', 'hotel'):
        for strategy in ('income', 'sale'):
            for financing in ('equity', 'equity_debt'):
                keys = field_keys(asset, strategy, financing)
                assert set(keys) <= set(schema['defaults'][asset])
                assert ('debt_rate_pct' in keys) == (financing == 'equity_debt')
                assert ('exit_cap_rate_pct' in keys) == (strategy == 'income')
                assert ('sales_cash_sweep_pct' in keys) == (strategy == 'sale' and financing == 'equity_debt')
                assert ('preopening_cost_rub' in keys) == (asset == 'hotel')


@pytest.mark.parametrize('asset', ['office','retail','hotel'])
@pytest.mark.parametrize('strategy', ['income','sale'])
@pytest.mark.parametrize('financing', ['equity','equity_debt'])
def test_commercial_api_on_current_site_surface(asset, strategy, financing):
    response = client.post('/api/commercial/calculate', json={
        'asset_type':asset,'strategy':strategy,'financing_mode':financing,'inputs':{}})
    assert response.status_code == 200
    body=response.json()
    assert body['version']=='commercial-beta-2'
    assert body['uses_escrow'] is False
    assert body['kpi']['operating_revenue']==pytest.approx(sum(body['monthly']['operating_revenue']))
    assert body['kpi']['net_sale_proceeds']==pytest.approx(sum(body['monthly']['sale_revenue'])-sum(body['monthly']['selling_cost']))
    assert body['monthly']['debt_balance'][-1]==pytest.approx(0)


@pytest.mark.parametrize('inputs', [
    {'construction_months':100000}, {'hold_years':1.5},
    {'occupancy_pct':101}, {'rent_rub_sqm_month':None},
    {'exit_cap_rate_pct':0}, {'debt_share_pct':96},
])
def test_api_rejects_invalid_values_instead_of_silent_clamping(inputs):
    response=client.post('/api/commercial/calculate',json={'inputs':inputs})
    assert response.status_code==400


def test_site_assets_are_served_and_commercial_routes_are_unique():
    for path in ('/commercial-beta.js','/commercial.css'):
        response=client.get(path)
        assert response.status_code==200
        assert 'no-store' in response.headers['cache-control']
    routes=[r.path for r in commercial_preview.app.routes]
    assert routes.count('/api/commercial/calculate')==1
