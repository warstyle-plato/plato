from pathlib import Path


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
    shell = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")
    registry = (ROOT / "main_registry.py").read_text(encoding="utf-8")

    upgrade = '<script src="/v2/assets/upgrade.js" defer></script>'
    accounts = '<script src="/v2/assets/account-projects.js" defer></script>'
    stock = '<script src="/v2/assets/app.js" defer></script>'

    assert "/v2/assets/account-projects.js" in shell
    assert upgrade in shell
    assert accounts in shell
    assert stock in shell
    assert shell.index(upgrade) < shell.index(accounts) < shell.index(stock)
    assert "install_v2_account_projects(app)" in registry
