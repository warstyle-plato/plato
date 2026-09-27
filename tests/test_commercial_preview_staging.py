from fastapi.testclient import TestClient

import commercial_preview


def test_current_developaid_root_contains_commercial_tab():
    client = TestClient(commercial_preview.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Нежилая экономика β" in response.text
    assert 'id="commercial" class="panel"' in response.text
    assert 'src="/commercial-beta"' in response.text


def test_embedded_commercial_page_runs_beta2_engine():
    client = TestClient(commercial_preview.app)
    response = client.get("/commercial-beta")
    assert response.status_code == 200
    assert "Ключевые показатели" in response.text
    assert "Project IRR" in response.text
    assert "Годовой cash flow" in response.text


def test_commercial_api_on_current_site_surface():
    client = TestClient(commercial_preview.app)
    response = client.post("/api/commercial/calculate", json={
        "asset_type": "office",
        "strategy": "income",
        "financing_mode": "equity",
        "inputs": {},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "commercial-beta-2"
    assert body["uses_escrow"] is False
