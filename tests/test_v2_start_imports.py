from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v2_starts_from_search_unless_a_result_was_explicitly_opened():
    source = (ROOT / "frontend_v2" / "start_imports.js").read_text(encoding="utf-8")

    assert "explicitView || 'tepsearch'" in source
    assert "requestedProject.startsWith('saved:')" in source
    assert "params.get('demo') === '1'" in source
    assert "section.id === `view-${target}`" in source


def test_v2_template_upload_reuses_the_existing_manual_tep_importer():
    source = (ROOT / "frontend_v2" / "start_imports.js").read_text(encoding="utf-8")
    core = (ROOT / "main_legacy.py").read_text(encoding="utf-8")

    assert "/import/manual-tep?filename=" in source
    assert "/templates/tep" in source
    assert "parsed.tep" in source
    assert "calculateImported" in source
    assert '@app.post("/import/manual-tep")' in core
    assert "parse_manual_tep_xlsx(data, filename)" in core


def test_v2_teaser_upload_keeps_the_existing_confirm_before_apply_flow():
    source = (ROOT / "frontend_v2" / "start_imports.js").read_text(encoding="utf-8")
    core = (ROOT / "main_legacy.py").read_text(encoding="utf-8")

    assert "content_b64" in source
    assert "'/agent/document'" in source
    assert "data-v2-teaser-index" in source
    assert "accept," in source
    assert "extraction: teaserExtraction" in source
    assert '@app.post("/agent/document")' in core
    assert "Ничего не подставляется молча" in core


def test_v2_shell_loads_import_bridge_before_stock_application():
    shell = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")

    imports = '<script src="/v2/assets/start-imports.js" defer></script>'
    injected = shell[shell.index("injected = ("):]

    assert "/v2/assets/start-imports.js" in shell
    assert imports in injected
    assert "+ marker" in injected
    assert injected.index(imports) < injected.index("+ marker")
