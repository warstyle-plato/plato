"""Real PAGE: parcel values, future estimates and owner overrides survive edits."""
from pathlib import Path

import pytest

import main
from tests import browser

core = main.core


def parcel_numbers(region):
    prefix = "77:01:0000001" if region == "msk" else "50:01:0000001"
    return [prefix + ":11", prefix + ":12"]


def open_payment(page):
    browser.open_vri(page)
    root = page.locator("#landRentEditor")
    advanced = root.locator("[data-land-rent-advanced]")
    if not advanced.evaluate("e=>e.open"):
        advanced.locator("summary").first.click()
    payments = root.locator('[data-land-rent-detail="payments"]')
    if not payments.evaluate("e=>e.open"):
        payments.locator("summary").first.click()
    return payments


def blur_edit(page, selector, value):
    field = page.locator(selector)
    field.fill(value)
    field.press("Tab")
    browser.wait_for_result(page)


def state(page):
    return page.evaluate("""()=>({current:inputs.land_rent_cadastral_mln,
        target:inputs.land_rent_cadastral_target_mln, origins:inputs._field_origin,
        rent:lastResult.land_rent, excluded:inputs.land_rent_parcels_excluded||[]})""")


@pytest.mark.parametrize("region", ["msk", "mo"])
@pytest.mark.parametrize("width,surface", [(390, "/"), (1440, "/classic")])
def test_parcel_sources_future_estimate_manual_override_and_reload(region, width, surface, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from main_registry import app as registry_app

    monkeypatch.setattr(core, "_telegram_token", lambda: "")
    monkeypatch.setattr(core, "require_calc_access", lambda *a, **k: {"allowed": True})
    numbers = parcel_numbers(region)
    errors = []
    with browser.serve(registry_app, 18904) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={"width": width, "height": 1000}, locale="ru-RU")
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            # This browser checks a local synthetic project. The Python
            # server's sockets are already guarded by tests/conftest.py;
            # guard Chromium's own requests independently as well.
            local_origin = base.rstrip("/") + "/"
            page.route("**/*", lambda route: route.continue_()
                if route.request.url.startswith(local_origin) else route.abort())
            page.route("**/ia/goal-seek", lambda route: route.fulfill(status=503,
                json={"reason": "Синтетическая проверка аренды"}))
            page.goto(base.rstrip("/") + surface, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate("""async({region,numbers})=>{
                Object.assign(inputs,{land_right:'ownership',vri_region:region,land_rent_mode:'manual',
                  land_rent_cadastral_mln:null,land_rent_cadastral_target_mln:null,
                  land_rent_cadastral_target_kind:null,land_rent_cadastral_parameters:[],
                  land_rent_vri_change:true,land_rent_parcels_excluded:[],
                  land_rent_regime_start:'2027-01-01',project_start:'2027-01-01',
                  ird_months:12,construction_months:12,land_rent_termination_date:'2029-01-01',
                  land_rent_rates:[{year:1,rate_pct:12}],land_rent_tail_rule:'repeat_last',
                  land_rent_vat_treatment:'public_exempt',land_rights_cost_mln:50,
                  vri_required:true,vri_obligation_date:'2027-01-16',
                  vri_relief_mode:'percent',vri_relief_pct:100,
                  social_mode:'Денежная компенсация',social_compensation_mln:0,
                  _field_origin:{}});
                delete inputs._glavapu_import;delete inputs._mo_calc;delete inputs._other_region;
                if(region==='msk'){
                  inputs._glavapu_import={normalized:{cadastral_quarter:'77:01:0000001',site_area_ha:.3},
                    recognized:numbers,mappings:{inputs:{vri_region:region}}};
                  inputs._land_lookup={results:numbers.map((number,i)=>({cadastral_number:number,
                    found:true,kind:'land',area_sqm:1000*(i+1),cadastral_value_mln:100*(i+1)}))};
                }else{
                  inputs._mo_calc={vri:{parcels:numbers.map((number,i)=>({cadastral_number:number,
                    area_sqm:1000*(i+1),cadastral_value_rub:100e6*(i+1),
                    upks_target:200000,cadastral_value_new_rub:200e6*(i+1)}))}};
                }
                phasing.enabled=false;renderInputs();await settledCalculate();
            }""", {"region": region, "numbers": numbers})
            browser.open_vri(page)
            page.locator("#f_land_right").select_option("lease")
            browser.wait_for_result(page)
            assert state(page)["current"] == 300
            expect(page.locator("#f_land_rent_cadastral_mln")).to_have_value("300")
            assert state(page)["origins"]["inputs.land_rent_cadastral_mln"]["kind"] == "land_rent_egrn"
            payment = open_payment(page)
            if region == "msk":
                assert state(page)["target"] is None
                assert "cadastral_change" in state(page)["rent"]["financial_missing_codes"]
                expect(payment).to_contain_text("площадь арендуемого участка")
                expect(payment).to_contain_text("Параметры платы за ВРИ сюда не переносятся")
                expect(payment.get_by_role("link", name="Официальный текст методики")).to_have_attribute(
                    "href", "http://publication.pravo.gov.ru/document/0001202112200041")
                expect(payment).to_contain_text("17.11.2026")
                for number in numbers:
                    for parameter, value in [("upks_rub_sqm", "200000"),
                                             ("target_use", "Синтетический целевой ВРИ и группа оценки"),
                                             ("valuation_territory", "Синтетическая территория оценки Москвы"),
                                             ("source", "Синтетический земельный УПКС для проверки"),
                                             ("source_date", "2026-11-17")]:
                        open_payment(page)
                        blur_edit(page, f'[data-cadastral-parcel="{number}"][data-cadastral-parameter="{parameter}"]', value)
            assert state(page)["target"] == 600
            assert state(page)["origins"]["inputs.land_rent_cadastral_target_mln"]["kind"] == "land_rent_estimate"
            open_payment(page)
            expect(page.locator("#f_land_rent_cadastral_target_kind")).to_have_value("estimate")
            assert state(page)["rent"]["cadastral_switch"]["date"] == "2027-01-16"
            assert state(page)["rent"]["cadastral_switch"]["target_mln"] == 600
            assert page.evaluate("lastResult.capex.land_rights") == 0
            # Recompute from an actual parameter edit. MO gets the updated
            # normalized parcel calculation, which is its authoritative input.
            if region == "msk":
                open_payment(page)
                blur_edit(page, f'[data-cadastral-parcel="{numbers[0]}"][data-cadastral-parameter="upks_rub_sqm"]', "300000")
                assert state(page)["target"] == 700
                open_payment(page)
                blur_edit(page, f'[data-cadastral-parcel="{numbers[1]}"][data-cadastral-parameter="upks_rub_sqm"]', "")
                assert state(page)["target"] is None
                assert "cadastral_change" in state(page)["rent"]["financial_missing_codes"]
                open_payment(page)
                blur_edit(page, f'[data-cadastral-parcel="{numbers[1]}"][data-cadastral-parameter="upks_rub_sqm"]', "200000")
                # An explicitly cleared area remains empty after the editor
                # redraws. It must not fall back to the imported parcel area
                # or turn the missing future value into a zero.
                area_selector = f'[data-cadastral-parcel="{numbers[0]}"][data-cadastral-parameter="area_sqm"]'
                open_payment(page)
                blur_edit(page, area_selector, "")
                open_payment(page)
                expect(page.locator(area_selector)).to_have_value("")
                empty_area = state(page)
                assert empty_area["target"] is None
                assert empty_area["current"] == 300
                assert empty_area["origins"]["inputs.land_rent_cadastral_target_mln"]["kind"] == "land_rent_estimate"
                assert "cadastral_change" in empty_area["rent"]["financial_missing_codes"]
                blur_edit(page, area_selector, "1000")
                assert state(page)["target"] == 700
            else:
                page.evaluate("async()=>{inputs._mo_calc.vri.parcels[0].cadastral_value_new_rub=300e6;renderInputs();await settledCalculate()}")
                assert state(page)["target"] == 700
            open_payment(page)
            blur_edit(page, "#f_land_rent_cadastral_target_mln", "777")
            blur_edit(page, "#f_land_rent_cadastral_mln", "333")
            page.locator(f'[data-land-rent-parcel="{numbers[1]}"]').uncheck()
            browser.wait_for_result(page)
            assert state(page)["current"] == 333
            assert state(page)["target"] == 777
            assert state(page)["excluded"] == [numbers[1]]
            page.reload(wait_until="domcontentloaded")
            browser.wait_for_result(page)
            open_payment(page)
            assert state(page)["current"] == 333 and state(page)["target"] == 777
            assert state(page)["excluded"] == [numbers[1]]
            # Clearing overrides restores the auto sum over the selected land.
            blur_edit(page, "#f_land_rent_cadastral_mln", "")
            open_payment(page)
            blur_edit(page, "#f_land_rent_cadastral_target_mln", "")
            assert state(page)["current"] == 100
            assert state(page)["target"] == 300
            page.reload(wait_until="domcontentloaded")
            browser.wait_for_result(page)
            open_payment(page)
            restored = state(page)
            assert restored["current"] == 100 and restored["target"] == 300
            assert restored["excluded"] == [numbers[1]]
            expect(page.locator(f'[data-land-rent-parcel="{numbers[1]}"]')).not_to_be_checked()
            expect(page.locator("#f_land_rent_cadastral_mln")).to_have_value("100")
            expect(page.locator("#f_land_rent_cadastral_target_mln")).to_have_value("300")
            assert restored["rent"]["cadastral_switch"]["target_mln"] == 300
            assert "ЕГРН" not in restored["origins"]["inputs.land_rent_cadastral_target_mln"]["text"].replace("не ЕГРН", "")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
            assert page.locator("#landRentEditor").evaluate("e=>e.scrollWidth<=e.clientWidth+1")
            output = Path("/tmp/plato-rent-cadastral-ui")
            output.mkdir(mode=0o700, exist_ok=True)
            page.locator("#landRentEditor").screenshot(path=str(output / f"{region}-{width}.png"))
            if region == "msk" and width == 1440:
                # An official value is an explicit claim backed by the
                # owner's document, and has its own source and effective date.
                page.locator("#f_land_rent_cadastral_target_kind").select_option("official_egrn")
                browser.wait_for_result(page)
                open_payment(page)
                blur_edit(page, "#f_land_rent_cadastral_target_source", "Синтетическая выписка ЕГРН для проверки")
                blur_edit(page, "#f_land_rent_cadastral_target_source_date", "2026-11-17")
                blur_edit(page, "#f_land_rent_cadastral_change_date", "2027-02-12")
                official = state(page)["rent"]
                assert official["target_cadastral_origin"]["value_type"] == "official_egrn"
                assert official["target_cadastral_origin"]["source_date"] == "2026-11-17"
                assert "Официальная новая КС из ЕГРН" in official["target_cadastral_origin"]["text"]
                assert official["cadastral_switch"]["date"] == "2027-02-12"
                expect(page.locator(".lr-cadastral-result")).to_contain_text("Официальная новая КС из ЕГРН")
            assert not errors, errors
