from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import developaid_v2_account_projects as account_projects


ROOT = Path(__file__).resolve().parents[1]


def test_v2_saved_projects_use_existing_account_store():
    source = (ROOT / "frontend_v2" / "account_projects.js").read_text(encoding="utf-8")

    assert "developaid_web_session" in source
    assert "'/projects/list'" in source
    assert "'/projects/open'" in source
    assert "'/api/v2/form'" in source
    assert "'/api/v2/calculate'" in source
    assert "SAVED_SLUG_PREFIX = 'saved:'" in source


def test_v2_old_demo_query_does_not_override_neutral_start():
    source = (ROOT / "frontend_v2" / "account_projects.js").read_text(encoding="utf-8")

    assert "neutralizeStaleDemoQuery" in source
    assert "url.searchParams.delete('project')" in source
    assert "projects.unshift(neutralProject())" in source
    assert "url.searchParams.get('demo') === '1'" in source


def test_v2_account_bridge_is_loaded_before_stock_application():
    registry = (ROOT / "main_registry.py").read_text(encoding="utf-8")
    app = FastAPI()
    account_projects.install(app)
    html = TestClient(app).get("/v2/").text

    upgrade = '<script src="/v2/assets/upgrade.js" defer></script>'
    accounts = '<script src="/v2/assets/account-projects.js" defer></script>'
    stock = '<script src="/v2/assets/app.js" defer></script>'

    assert html.index(upgrade) < html.index(accounts) < html.index(stock)
    assert "install_v2_account_projects(app)" in registry
