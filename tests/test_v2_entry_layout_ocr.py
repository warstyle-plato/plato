from pathlib import Path

import developaid_v2_account_projects as v2_entry


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


def test_v2_shell_loads_entry_layout_and_teaser_fallback_before_stock_app():
    shell = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")

    assert '@app.get("/v2/assets/entry-layout.js"' in shell
    assert '@app.get("/v2/assets/teaser-fallback.js"' in shell
    assert '@app.post("/api/v2/teaser-fallback"' in shell
    assert '<script src="/v2/assets/teaser-fallback.js" defer></script>' in shell
    assert '<script src="/v2/assets/entry-layout.js" defer></script>' in shell
    assert shell.index('<script src="/v2/assets/teaser-fallback.js" defer></script>') < shell.index('+ marker')
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


def test_timiryazevskaya_broker_teaser_has_local_resilience_parser(monkeypatch):
    text = """[стр. 1]
Проект жилого комплекса
г Москва, ул Тимирязевская, д 17
КН 77:09:0003021:158
Площадь 0,88 Га
Стоимость 1 650 000 000 ₽
Передача 1500 м², задаток 300 млн руб, остаток 1350 млн руб. на ППМ
СПП в ГНС (предварительно) 31 000 м²
"""
    monkeypatch.setattr(
        v2_entry.document_intake,
        "extract_text",
        lambda payload, filename: {
            "filename": filename,
            "text": text,
            "pages": 1,
            "pages_read": 1,
            "scanned": False,
            "recognized": False,
            "reason": "",
        },
    )

    parsed = v2_entry._quick_teaser_intake(b"pdf", "Тимирязевская.pdf")
    fields = {row["key"]: row for row in parsed["fields"]}

    assert fields["cadastral_numbers"]["value"] == "77:09:0003021:158"
    assert fields["site_area_ha"]["value"] == "0,88"
    assert fields["purchase_price_mln"]["value"] == "1 650 000 000"
    assert fields["apartments_gns_sqm"]["value"] == "31 000"
    assert fields["purchase_price_mln"]["quote"] == "Стоимость 1 650 000 000 ₽"
    assert any("Передача 1500 м²" in note for note in parsed["notes"])


def test_teaser_fallback_only_bypasses_parser_failures_not_auth_failures():
    source = (ROOT / "frontend_v2" / "teaser_fallback.js").read_text(encoding="utf-8")

    assert "response.status < 500" in source
    assert "if (body.accept || !body.content_b64)" in source
    assert "'/api/v2/teaser-fallback'" in source
    assert "parserRefused" in source
