"""Exercise the actual /v2 upload, questions, stale-card gate and calculation."""
import json

import pytest

from browser import chromium_or_skip, serve


@pytest.mark.parametrize("width,gns", [(390, 31000), (1440, 31000), (390, 100.25)])
def test_v2_applies_only_the_ready_current_server_card(monkeypatch, tmp_path, width, gns):
    import main_registry
    import main as wrapper
    import document_intake
    from playwright.sync_api import sync_playwright

    core = wrapper.core
    monkeypatch.setattr(core, "_PLATO_STAGE_DIR", tmp_path)
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "require_calc_access", lambda *_a, **_k: {})
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    quote = f"Цена 400 млн руб.\nКвартиры {gns} м²\nЛьгота МПТ 2,57 млрд руб."
    monkeypatch.setattr(document_intake, "extract_text", lambda _data, name:
                        {"text": "[стр. 1]\n" + quote, "pages": 1, "filename": name})
    fields = [
        {"key": "purchase_price_mln", "value": "400", "unit": "млн руб.", "quote": "Цена 400 млн руб."},
        {"key": "apartments_gns_sqm", "value": str(gns), "unit": "м²", "quote": f"Квартиры {gns} м²"},
        {"key": "vri_relief_mln", "value": "2,57", "unit": "млрд руб.", "quote": "Льгота МПТ 2,57 млрд руб."},
    ]
    monkeypatch.setattr(core, "plato_answer", lambda *_a:
                        {"answer": json.dumps({"fields": fields, "questions": [], "notes": []})})
    calculated = []
    with serve(main_registry.app, 18371 + (width == 390)) as base:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("request", lambda req: calculated.append(req.post_data_json)
                    if req.method == "POST" and req.url.endswith("/api/v2/calculate") else None)
            page.goto(base + "/v2", wait_until="networkidle")
            page.set_input_files("#v2TeaserUpload", {"name": "test.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-test"})
            page.get_by_role("button", name="Перейти к вопросам (2)").wait_for(timeout=15000)
            assert page.locator("#v2TeaserApply").count() == 0
            assert not calculated
            page.get_by_role("button", name="Перейти к вопросам (2)").click()
            page.locator('#v2TeaserQuestion [data-teaser-choice="1"]').click()  # explicitly take relief
            page.locator("#v2TeaserQuestion").get_by_role("button", name="Бизнес", exact=True).click()
            page.locator("#v2TeaserApply").wait_for()
            assert not calculated
            page.evaluate("() => { form.draft.inputs.purchase_price_mln = 999; }")
            page.locator("#v2TeaserApply").click()
            page.locator("#v2ImportStatus").filter(has_text="Вводные изменились").wait_for()
            assert not calculated
            page.locator("#v2TeaserApply").click()
            page.locator("#v2ImportStatus").filter(has_text="проект пересчитан").wait_for(state="attached", timeout=30000)
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            assert len(calculated) == 1
            sent = calculated[0]
            assert sent["inputs"]["purchase_price_mln"] == 400
            assert sent["inputs"]["vri_relief_mln"] == 2570
            assert sent["inputs"]["vri_relief_mode"] == "amount"
            assert sent["tep"]["apartments"]["gns"] == gns
            assert sent["tep"]["apartments"]["saleable"] < gns
            assert sent["inputs"]["_field_origin"]["inputs.purchase_price_mln"]["source"] == "document"
            assert not errors, errors
            browser.close()
