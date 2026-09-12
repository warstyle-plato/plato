from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_search_is_visually_first_in_both_navigations():
    source = (ROOT / "frontend_v2" / "entry_layout.js").read_text(encoding="utf-8")

    assert "moveFirst(document.querySelector('.main-nav'), '[data-view=\"tepsearch\"]')" in source
    assert "moveFirst(document.querySelector('.mobile-tabs'), '[data-view=\"tepsearch\"]')" in source


def test_photo_input_lives_on_search_and_keeps_tep_form_rendered_for_apply():
    source = (ROOT / "frontend_v2" / "entry_layout.js").read_text(encoding="utf-8")

    assert "#view-tepsearch .tep-search-panel" in source
    assert "searchPanel.insertAdjacentElement('afterend', photoPanel)" in source
    assert "photoPanel.hidden = false" in source
    assert "#v2CameraButton, #v2GalleryButton, #v2PhotoApply" in source
    assert "block.kind === 'tep'" in source
    assert "form.step = index" in source
    assert "renderStep()" in source


def test_v2_shell_loads_entry_layout_before_stock_app():
    shell = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")

    assert '@app.get("/v2/assets/entry-layout.js"' in shell
    assert '<script src="/v2/assets/entry-layout.js" defer></script>' in shell
    assert shell.index('<script src="/v2/assets/entry-layout.js" defer></script>') < shell.index('+ marker')


def test_container_build_cannot_publish_without_photo_ocr_binary_and_languages():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "tesseract-ocr" in dockerfile
    assert "tesseract-ocr-rus" in dockerfile
    assert "tesseract-ocr-eng" in dockerfile
    assert "command -v tesseract" in dockerfile
    assert "tesseract --version" in dockerfile
    assert "tesseract --list-langs | grep -qx 'rus'" in dockerfile
    assert "tesseract --list-langs | grep -qx 'eng'" in dockerfile
