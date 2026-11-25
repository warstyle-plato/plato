"""The actual form can lease an office/retail/hotel site without housing fields."""
import pytest

import main
from tests import browser

core = main.core


def test_land_ownership_is_a_common_project_input():
    assert 'land_right' not in core.RESIDENTIAL_ONLY_INPUTS


@pytest.mark.parametrize('width', [390, 1440])
def test_nonresidential_lease_control_recounts_and_keeps_contract_terms(width, monkeypatch):
    from main_registry import app as registry_app
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setattr(core, '_telegram_token', lambda: '')
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **k: {'allowed': True})
    errors = []
    with browser.serve(registry_app, 18896) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={'width': width, 'height': 1000})
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until='domcontentloaded')
            browser.wait_for_result(page)
            for object_kind in ('offices', 'retail', 'hotel'):
                page.evaluate("""async kind => {
                    inputs.project_kind=kind==='hotel'?'hotel':'nonresidential';
                    for(const o of STANDALONE_OBJECTS)inputs[o.prefix+'_enabled']=o.prefix===kind;
                    Object.assign(inputs,{
                        land_right:'ownership',land_rent_mode:'manual',
                        land_rent_base_kind:'annual_amount',land_rent_annual_base_mln:1.2,
                        land_rent_regime_start:'2027-01-01',project_start:'2027-01-01',
                        land_rent_rates:[{year:1,rate_pct:100}],land_rent_tail_rule:'repeat_last',
                        land_rent_vat_treatment:'public_exempt',land_rent_forecast_index_pct:0,
                        land_rent_source:'Условный договор для проверки формы',
                        land_rent_termination_date:'2037-01-01'
                    });
                    syncTep(false);renderInputs();await settledCalculate();
                }""", object_kind)
                browser.open_vri(page)
                selector = page.locator('#landRentEditor #f_land_right')
                expect(selector).to_be_visible()
                expect(page.locator('#f_land_right')).to_have_count(1)
                expect(selector).to_have_value('ownership')
                assert page.evaluate('lastResult.capex.land_rent') == 0
                selector.select_option('lease')
                page.wait_for_function("lastResult.land_rent.status!=='not_applicable'")
                browser.wait_for_result(page)
                assert page.evaluate('lastResult.capex.land_rent') > 0
                assert page.evaluate('lastResult.land_rent.mode') == 'manual'
                assert page.evaluate('lastResult.vri.enabled') is False
                assert page.evaluate("inputs._field_origin['inputs.land_right'].source") == 'manual'
                lease_cost = page.evaluate('lastResult.capex.land_rent')
                terms = page.evaluate("({rate:inputs.land_rent_rates,start:inputs.land_rent_regime_start,amount:inputs.land_rent_annual_base_mln})")
                selector.select_option('ownership')
                page.wait_for_function("lastResult.land_rent.status==='not_applicable'")
                browser.wait_for_result(page)
                assert page.evaluate('lastResult.capex.land_rent') == 0
                page.locator('#landRentEditor #f_land_right').select_option('lease')
                page.wait_for_function("lastResult.land_rent.status!=='not_applicable'")
                browser.wait_for_result(page)
                assert page.evaluate('lastResult.capex.land_rent') == pytest.approx(lease_cost)
                assert page.evaluate("({rate:inputs.land_rent_rates,start:inputs.land_rent_regime_start,amount:inputs.land_rent_annual_base_mln})") == terms
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            assert not errors, errors
