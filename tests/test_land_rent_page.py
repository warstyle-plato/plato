from pathlib import Path

import pytest

import main
from tests import browser

core = main.core


# Корень прода — со слоем IA, /classic — прежний вид: проверяются оба, и какой
# из них откроется, решает параметр, а не порядок сбора тестов.
@pytest.mark.parametrize("surface", ["/", "/classic"], ids=["main", "classic"])
@pytest.mark.parametrize("width", [390, 1440])
def test_rental_editor_uses_real_page_retains_rates_and_recalculates(width, surface, monkeypatch):
    import re

    from playwright.sync_api import expect, sync_playwright
    from main_registry import app as registry_app

    monkeypatch.setattr(core, "_telegram_token", lambda: "")
    monkeypatch.setattr(core, "require_calc_access", lambda *a, **k: {"allowed": True})
    errors = []
    with browser.serve(registry_app, 18862) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={"width": width, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base.rstrip("/") + surface, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            if surface == "/":
                expect(page.locator("body")).to_have_class(re.compile(r"\bia-on\b"))
            else:
                assert not page.locator("body.ia-on").count()
            page.evaluate("""async()=>{
                Object.assign(inputs,{land_right:'lease',vri_region:'msk',land_rent_mode:'manual',
                  land_rent_cadastral_mln:100,land_rent_regime_start:'2027-01-01',
                  land_rent_rates:[{year:1,rate_pct:1.5},{year:2,rate_pct:3}],
                  land_rent_tail_rule:'repeat_last',land_rent_vat_treatment:'public_exempt',
                  land_rent_source:'Синтетический договор — пример',
                  _glavapu_import:{normalized:{cadastral_quarter:'77:01:0000001',site_area_ha:1},
                    recognized:['77:01:0000001:11'],mappings:{inputs:{vri_region:'msk'}}},
                  project_start:'2027-01-01',ird_months:12,construction_months:12,
                  social_mode:'Денежная компенсация',social_compensation_mln:0});
                renderInputs();await settledCalculate();
            }""")
            browser.open_vri(page)
            assert page.locator("#landRentEditor").is_visible()
            assert page.locator("#f_land_rent_cadastral_mln").input_value() == "100"
            assert page.evaluate("lastResult.land_rent.construction_total") == pytest.approx(4.5e6)
            page.locator('#landRentEditor details[data-land-rent-detail="conditions"] > summary').click()
            page.locator("#f_land_rent_mode").select_option("msk_mkd_3_2")
            browser.wait_for_result(page)
            assert "Подтвердите" in page.locator("#landRentSummary").inner_text()
            page.locator("#f_land_rent_mode").select_option("manual")
            browser.wait_for_result(page)
            assert page.evaluate("inputs.land_rent_rates") == [{"year": 1, "rate_pct": 1.5}, {"year": 2, "rate_pct": 3}]
            field = page.locator("input[aria-label='Ставка за 1 год']")
            field.fill("2");field.dispatch_event("change")
            browser.wait_for_result(page)
            assert page.evaluate("lastResult.land_rent.construction_total") == pytest.approx(5e6)
            page.reload(wait_until="domcontentloaded")
            browser.wait_for_result(page)
            browser.open_vri(page)
            assert page.evaluate("inputs.land_rent_rates[0].rate_pct") == 2
            assert page.locator("#f_land_rent_regime_start").input_value() == "2027-01-01"
            assert page.locator("#landRentSummary").get_by_text("Начислено по ставкам:", exact=False).count() > 0
            if width == 390:
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
            target = Path("/tmp/plato-land-rent-ui-acceptance")
            target.mkdir(mode=0o700, exist_ok=True)
            page.locator("#landRentEditor").screenshot(path=str(target / f"land-rent-{width}-{surface.strip('/') or 'main'}.png"))
            assert not errors, errors


def test_telegram_displays_existing_qualification_without_recalculating_or_sending(monkeypatch):
    sent = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id":42,"cad":[]})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda chat: True)
    monkeypatch.setattr(core, "calc_access_for_chat", lambda *a, **k: {"allowed":True})
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.invalid/")
    monkeypatch.setattr(core, "_telegram_send_message", lambda chat,text,**k: sent.append(text))
    def unexpected(*a, **k):
        raise AssertionError("Telegram must consume the computed status, not calculate again")
    monkeypatch.setattr(core, "calculate", unexpected)
    reason = "Предварительный расчёт: аренда земли не определена <пример>."
    core.telegram_result(core.TelegramResultRequest(session="synthetic", summary={
        "purchase_price_mln":6500,"net_profit_mln":900,"llcr":1.3,"preliminary_reason":reason}))
    assert len(sent) == 1
    assert "аренда земли не определена &lt;пример&gt;" in sent[0]
