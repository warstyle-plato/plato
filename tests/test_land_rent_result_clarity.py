"""Аренда видна в затратах; известная сумма не скрывает предварительность."""
import copy
from pathlib import Path

import pytest

import main
from tests import browser

core = main.core


def rental_inputs(**overrides):
    return {**copy.deepcopy(core.DEFAULT_INPUTS),
            "land_right": "lease", "vri_region": "msk", "land_rent_mode": "manual",
            "land_rent_cadastral_mln": 100, "land_rent_regime_start": "2027-01-01",
            "project_start": "2027-01-01", "ird_months": 12, "construction_months": 12,
            "land_rent_rates": [{"year": 1, "rate_pct": 1.5}],
            "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt",
            **overrides}


@pytest.mark.parametrize("metric,value,title,tone", [
    ("llcr", 1.3, "экономика проходит", "edge"),
    ("llcr", 1.1, "экономика на границе", "edge"),
    ("llcr", .9, "экономика не проходит", "fail"),
    ("dscr", 1.3, "экономика проходит", "edge"),
    ("dscr", .9, "экономика не проходит", "fail"),
    (None, None, "экономика проходит по прибыли", "edge"),
])
def test_known_rent_names_the_economic_result_but_keeps_it_provisional(metric, value, title, tone):
    result = {"summary": {"preliminary": True, "llcr": value, "net_profit": 1},
              "land_rent": {"complete": True, "construction_total": 3e6},
              "report": {"layout": {"debt_metric": {"key": metric, "value": value}}}}
    assert core.entry_price_verdict({"consolidated": result}) == {
        "title": "Предварительно: " + title, "tone": tone}


@pytest.mark.parametrize("rent", [None, {}, {"complete": False, "construction_total": 3e6},
                                 {"complete": True, "construction_total": None}])
def test_missing_rent_does_not_pass_as_a_free_site(rent):
    bundle = {"consolidated": {"summary": {"preliminary": True, "llcr": 9}, "land_rent": rent}}
    assert core.entry_price_verdict(bundle) == {
        "title": "Предварительная экономика: уточните аренду земли", "tone": "edge"}


def test_known_zero_is_not_missing_and_confirmed_economics_keeps_normal_verdict():
    result = {"summary": {"preliminary": True, "llcr": 1.3},
              "land_rent": {"complete": True, "construction_total": 0}}
    assert core.entry_price_verdict({"consolidated": result}) == {
        "title": "Предварительно: экономика проходит", "tone": "edge"}
    result["summary"]["preliminary"] = False
    assert core.entry_price_verdict({"consolidated": result}) == {
        "title": "Экономика проходит", "tone": "pass"}


def test_default_mo_indices_are_an_estimate_until_replaced_with_contract_inputs():
    x = rental_inputs(vri_region="mo", land_rent_mode="mo_housing_new_2026",
        land_rent_contract_date="2027-01-01", land_rent_preset_confirmed=True,
        land_rent_public_scope="regional", land_rent_grant_basis="ordinary_nonauction",
        land_rent_calendar_indices=[{"year": 2028, "index_pct": 0}, {"year": 2029, "index_pct": 0}],
        land_rent_indices_origin={"2028": {"source": "default_estimate"}, "2029": {"source": "default_estimate"}})
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert result["land_rent"]["construction_total"] > 0
    assert "indices_estimate" in result["land_rent"]["financial_missing_codes"]
    assert not result["land_rent"]["financial_complete"]
    assert any("0%" in text and "текущих ценах" in text for text in result["land_rent"]["assumptions"])
    x["land_rent_indices_origin"] = {"2028": {"source": "manual"}, "2029": {"source": "manual"}}
    changed = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert "indices_estimate" not in changed["land_rent"]["financial_missing_codes"]


@pytest.mark.parametrize("phased", [False, True])
def test_actual_model_delivers_the_same_verdict_before_and_after_price_search(phased):
    args = dict(inputs=rental_inputs(), tep=copy.deepcopy(core.TEP_DEFAULT), rates=[])
    if phased:
        bundle = core.calculate_phased(core.PhasedCalcRequest(**args, phasing={
            "enabled": True, "user_enabled": True, "mode": "phased", "phase_count": 2,
            "phases": [{"name": "А", "site_area_ha": 1},
                       {"name": "Б", "site_area_ha": 2, "start_offset_months": 12}]}))
    else:
        bundle = {"consolidated": core.calculate(core.CalcRequest(**args))}
    results = [bundle["consolidated"], *[p["result"] for p in bundle.get("phases", [])]]
    for r in results:
        assert r["capex"]["land_rent"] > 0
        assert r["summary"]["preliminary"]
        block = core.entry_price_block({"consolidated": r}, args["inputs"], None)
        assert r["report"]["entry_price_verdict"] == block["verdict"]
        assert block["verdict"]["title"].startswith("Предварительно: экономика")
        assert r["summary"]["preliminary_reason"] in block["tiles"][0]["note"]


@pytest.mark.parametrize("width", [390, 1440])
def test_real_results_show_cost_unknown_zero_and_owned_land(width, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from main_registry import app as registry_app

    monkeypatch.setattr(core, "_telegram_token", lambda: "")
    monkeypatch.setattr(core, "require_calc_access", lambda *a, **k: {"allowed": True})
    with browser.serve(registry_app, 18889) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={"width": width, "height": 1000}, locale="ru-RU")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            # Проверяется и состояние до успешного подбора цены: он не должен
            # быть условием появления честного заголовка или оговорки.
            page.route("**/ia/goal-seek", lambda route: route.fulfill(status=503, json={"reason": "Синтетический отказ подбора"}))
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            hint = page.locator('#iaFabHint button')
            if hint.count():
                hint.click()
            page.evaluate("""async x=>{
                Object.assign(inputs,x);renderInputs();await settledCalculate();
            }""", rental_inputs())
            page.locator(".ia-nav").get_by_role("button", name="Результат", exact=True).click()
            line = page.locator("#projectParamsTable tr").filter(has=page.get_by_text("Аренда земли в затратах", exact=True))
            expect(line).to_contain_text("3 млн")
            expect(line).to_contain_text("Предварительный расчёт")
            expect(page.locator("#iaVerdictTitle")).to_have_text(
                page.evaluate("lastResult.report.entry_price_verdict.title"))
            assert page.locator("#iaVerdict").evaluate("e=>!e.classList.contains('pass')")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
            output = Path("/tmp/plato-land-rent-result-clarity")
            output.mkdir(mode=0o700, exist_ok=True)
            page.locator("#iaVerdict").screenshot(path=str(output / f"decision-{width}.png"))
            page.locator("#projectParamsTable").screenshot(path=str(output / f"parameters-{width}.png"))
            for values, text in [
                ({"land_rent_cadastral_mln": None}, "Не определена"),
                ({"land_rent_cadastral_mln": 100, "land_rent_rates": [{"year": 1, "rate_pct": 0}]}, "0 ₽"),
                ({"land_right": "ownership"}, "Не применяется"),
            ]:
                page.evaluate("async x=>{Object.assign(inputs,x);renderInputs();await settledCalculate()}", values)
                expect(line).to_contain_text(text)
            assert not errors, errors


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("region", ["msk", "mo"])
def test_first_regional_estimate_needs_no_contract_questionnaire(width, region, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from main_registry import app as registry_app

    monkeypatch.setattr(core, "_telegram_token", lambda: "")
    monkeypatch.setattr(core, "require_calc_access", lambda *a, **k: {"allowed": True})
    with browser.serve(registry_app, 18890) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={"width": width, "height": 1000}, locale="ru-RU")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            if page.locator('#iaFabHint button').count():
                page.locator('#iaFabHint button').click()
            page.evaluate("""async region=>{
                delete inputs._glavapu_import;delete inputs._mo_calc;
                Object.assign(inputs,{land_right:'lease',vri_region:region,land_rent_mode:'unspecified',
                  land_rent_simple_estimate:false,land_rent_cadastral_mln:null,
                  land_rent_cadastral_target_mln:null,land_rent_base_kind:'cadastral_percent',
                  land_rent_regime_start:null,land_rent_contract_date:null,
                  land_rent_payment_mode:'monthly_estimate',land_rent_calendar_indices:[],land_rent_indices_origin:{},
                  project_start:'2027-01-01',ird_months:12,construction_months:12,
                  land_rights_cost_mln:0,social_mode:'Денежная компенсация',social_compensation_mln:0});
                delete inputs._field_origin?.['inputs.land_rent_cadastral_mln'];
                if(region==='msk'){
                  inputs._glavapu_import={normalized:{cadastral_quarter:'77:01:0000001',site_area_ha:1},
                    recognized:['77:01:0000001:11'],mappings:{inputs:{vri_region:'msk'}}};
                  inputs._land_lookup={results:[{found:true,kind:'land',cadastral_number:'77:01:0000001:11',cadastral_value_mln:1000}]};
                }else inputs._mo_calc={vri:{parcels:[{cadastral_number:'50:01:0000001:11',cadastral_value_rub:1000000000}]},territory:{site_area_ha:1}};
                renderInputs();await settledCalculate();
            }""", region)
            browser.wait_for_result(page)
            browser.open_vri(page)
            root = page.locator('#landRentEditor')
            expect(root.locator('.lr-defaults')).to_contain_text('Москва' if region == 'msk' else 'Подмосковье')
            assert page.evaluate('inputs.land_rent_simple_estimate') is True
            assert page.evaluate('lastResult.land_rent.construction_total') > 0
            assert page.evaluate('lastResult.summary.preliminary') is True
            assert root.locator('input:visible,select:visible').count() <= 3
            assert not root.locator('[data-land-rent-advanced]').evaluate('e=>e.open')
            assert root.locator('#f_land_rent_cadastral_mln').input_value() == '1000'
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            page.wait_for_function("!document.querySelector('#iaToast.show')&&(!document.querySelector('#iaToast')||getComputedStyle(document.querySelector('#iaToast')).opacity==='0')")
            output=Path('/tmp/plato-land-rent-result-clarity');output.mkdir(mode=0o700,exist_ok=True)
            # Capture the whole component with floating page controls below it;
            # all responsive assertions above use the ordinary 1000px viewport.
            page.set_viewport_size({'width':width,'height':2500})
            root.screenshot(path=str(output/f'simple-{region}-{width}.png'))
            page.set_viewport_size({'width':width,'height':1000})
            root.get_by_role('link',name='Условия и уточнения').click()
            assert root.locator('[data-land-rent-advanced]').evaluate('e=>e.open')
            if region == 'mo':
                assert not root.locator('#f_land_rent_first_year_relation').count()
                assert not root.locator('#f_land_rent_premium_status').count()
                expect(root.locator('.lr-defaults')).to_contain_text('0%')
                before=page.evaluate('inputs.land_rent_calendar_indices')
                assert before and all(row['index_pct'] == 0 for row in before)
                page.reload(wait_until='domcontentloaded')
                browser.wait_for_result(page)
                browser.open_vri(page)
                assert page.evaluate('inputs.land_rent_simple_estimate') is True
                assert page.evaluate('inputs.land_rent_calendar_indices') == before
                assert page.evaluate('lastResult.land_rent.construction_total') > 0
                # Explicit unknown and nonzero saved values cannot be replaced by defaults.
                page.evaluate("""()=>{inputs.land_rent_calendar_indices=[{year:2028,index_pct:null},{year:2029,index_pct:7}];landRentFillSimpleIndices()}""")
                assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2028).index_pct') is None
                assert page.evaluate('inputs.land_rent_calendar_indices.find(r=>r.year===2029).index_pct') == 7
            else:
                assert not root.locator('#f_land_rent_contract_date').count()
                assert not root.locator('#f_land_rent_public_scope').count()
                assert not root.locator('[data-land-rent-detail=indices]').count()
            assert not errors, errors
