"""An old ownership project must send the complete lease inputs on a real change."""
import copy
from pathlib import Path

import pytest

import main
from tests import browser

core = main.core


@pytest.mark.parametrize('surface', ['/', '/classic'], ids=['main', 'classic'])
@pytest.mark.parametrize('width', [390, 1440])
def test_legacy_ownership_switch_rebuilds_before_recalc_and_keeps_confirmation(width, surface, monkeypatch):
    from main_registry import app
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setattr(core, '_telegram_token', lambda: '')
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **k: {'allowed': True})
    monkeypatch.setattr(core, 'fetch_current_cbr_key_rate', lambda: {
        'rate': 14, 'date': '2026-07-24', 'source': 'offline fixture'})
    requests, errors = [], []
    with browser.serve(app, 18977) as url, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chrome:
            page = chrome.new_page(viewport={'width': width, 'height': 1000}, locale='ru-RU')
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.url.endswith('/calculate') else None)
            page.route('**/ia/goal-seek', lambda r: r.fulfill(status=503, json={'reason': 'offline fixture'}))
            page.goto(url + surface, wait_until='domcontentloaded')
            browser.wait_for_result(page)
            page.evaluate("""async()=>{
                const saved=projectStorePayload().payload;
                Object.keys(saved.inputs).filter(k=>k.startsWith('land_rent_')).forEach(k=>delete saved.inputs[k]);
                Object.assign(saved.inputs,{land_right:'ownership',vri_region:'msk',land_rights_cost_mln:0,
                    project_start:'2027-01-01',ird_months:12,construction_months:12,
                    social_mode:'Денежная компенсация',social_compensation_mln:0,
                    _glavapu_import:{normalized:{cadastral_quarter:'77:01:0000001',site_area_ha:1},
                        recognized:['77:01:0000001:11'],mappings:{inputs:{vri_region:'msk'}}},
                    _land_lookup:{results:[{cadastral_number:'77:01:0000001:11',found:true,
                        kind:'land',cadastral_value_mln:100}]}});
                applyProjectSnapshot(saved);await settledCalculate();
            }""")
            browser.open_vri(page)
            before = copy.deepcopy(requests[-1])
            assert page.evaluate('lastResult.land_rent.status') == 'not_applicable'
            count = len(requests)
            page.locator('#f_land_right').select_option('lease')
            browser.wait_for_result(page)
            assert len(requests) > count
            after = requests[-1]
            assert after['inputs']['land_right'] == 'lease'
            assert after['inputs']['land_rent_cadastral_mln'] == 100
            assert after['inputs']['land_rent_mode'] == 'msk_mkd_3_2'
            assert after['inputs']['land_rent_preset_confirmed'] is False
            assert core._calculation_fingerprint(before['inputs'], before['tep'], None) != core._calculation_fingerprint(after['inputs'], after['tep'], None)
            assert page.locator('#f_land_rent_regime_start').is_visible()
            assert page.evaluate('lastResult.land_rent.construction_total') > 0
            assert page.evaluate('lastResult.capex.land_rent') > 0
            assert 'Аренда земли участка' in page.locator('#projectParamsTable').inner_text()
            assert 'аренда не начисляется' not in page.locator('#landRentEditor').inner_text()

            page.locator('#landRentEditor [data-land-rent-advanced] > summary').click()
            page.locator('#landRentEditor details[data-land-rent-detail="conditions"] > summary').click()
            assert page.locator('label[for=f_land_rent_preset_confirmed]').inner_text() == 'Подтверждены ставки аренды по договору'
            assert 'подтверждает только ставки' in page.locator('#landRentEditor').inner_text()
            page.get_by_role('button',name='Проверить дату начала аренды',exact=True).click()
            assert page.evaluate("document.activeElement.id") == 'f_land_rent_regime_start'
            assert page.evaluate('inputs.land_rent_regime_start') is None
            page.locator('#f_land_rent_preset_confirmed').check()
            browser.wait_for_result(page)
            assert requests[-1]['inputs']['land_rent_preset_confirmed'] is True
            assert page.evaluate('inputs.land_rent_regime_start') is None
            assert page.evaluate('lastResult.land_rent.regime_start_assumed') is True
            assert page.evaluate('lastResult.summary.land_rent_sum.known') is False
            assert 'Дата начала аренды' in page.evaluate('lastResult.summary.land_rent_sum.reason')
            assert 'Дата начала аренды' in page.evaluate('lastResult.summary.preliminary_reason')
            assert 'договор с ними ещё не сверен' not in page.locator('#landRentSummary').inner_text()
            assert 'conditions' not in page.evaluate('lastResult.land_rent.financial_missing_codes')
            evidence=Path('/tmp/plato-rent-legacy-ui');evidence.mkdir(exist_ok=True)
            page.locator('#landRentEditor').screenshot(path=str(evidence/f'confirmed-rates-{width}-{surface.strip("/") or "main"}.png'))
            # Explicit synthetic contract data removes only the other two gaps.
            # Rates confirmation alone must never create this date-only verdict.
            page.locator('#landRentEditor details[data-land-rent-detail="payments"] > summary').click()
            page.locator('#f_land_rent_premium_status').select_option('not_applicable')
            browser.wait_for_result(page)
            page.locator('#landRentEditor details[data-land-rent-detail="scope"] > summary').click()
            end = page.evaluate('lastResult.land_rent.rve')
            page.locator('#f_land_rent_termination_date').fill(end)
            page.locator('#f_land_rent_termination_date').dispatch_event('change')
            browser.wait_for_result(page)
            assert page.evaluate('lastResult.summary.land_rent_sum.reason_code') == 'regime_start'
            title = 'Предварительная экономика: подтвердите дату начала аренды'
            assert page.evaluate('lastResult.report.entry_price_verdict.title') == title
            assert 'договор с ними ещё не сверен' not in page.locator('#landRentSummary').inner_text()
            if surface == '/':
                if page.locator('#iaFabHint button').count():
                    page.locator('#iaFabHint button').click()
                page.locator('.ia-nav').get_by_role('button', name='Результат', exact=True).click()
                expect(page.locator('#iaVerdictTitle')).to_have_text(title)
                assert not page.locator('#iaVerdict').evaluate("e=>e.classList.contains('pass')")
                page.locator('#iaVerdict').screenshot(path=str(evidence/f'date-only-headline-{width}.png'))
            saved = page.evaluate('projectStorePayload().payload')
            assert saved['inputs']['land_rent_preset_confirmed'] is True
            page.reload(wait_until='domcontentloaded')
            browser.wait_for_result(page)
            assert page.evaluate('inputs.land_rent_preset_confirmed') is True
            assert page.evaluate('inputs.land_rent_regime_start') is None
            assert page.evaluate('lastResult.summary.land_rent_sum.known') is False
            assert requests[-1]['inputs']['land_rent_preset_confirmed'] is True
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            # A missing cadastral source remains unknown after the same real switch.
            page.evaluate('''async()=>{
                const unknown=projectStorePayload().payload;
                unknown.inputs.land_right='ownership';unknown.inputs.land_rent_cadastral_mln=null;
                delete unknown.inputs._field_origin?.['inputs.land_rent_cadastral_mln'];
                unknown.inputs._land_lookup.results[0].cadastral_value_mln=null;
                applyProjectSnapshot(unknown);await settledCalculate();
            }''')
            browser.open_vri(page)
            page.locator('#f_land_right').select_option('lease');browser.wait_for_result(page)
            assert requests[-1]['inputs']['land_rent_cadastral_mln'] is None
            assert page.evaluate('lastResult.land_rent.construction_total') is None
            assert page.evaluate('lastResult.summary.land_rent_sum.known') is False
            assert 'Не определена' in page.locator('#projectParamsTable').inner_text()
            assert not errors, errors
