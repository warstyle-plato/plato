"""A displayed project-start fallback needs an explicit, independent contract action."""
from pathlib import Path

import pytest

import main
from tests import browser
from tests.test_land_rent_result_clarity import rental_inputs

core = main.core


@pytest.mark.parametrize('surface', ['/', '/classic'], ids=['main', 'classic'])
@pytest.mark.parametrize('width', [390, 1440])
def test_same_start_date_has_explicit_contract_confirmation_without_confirming_rates(width, surface, monkeypatch):
    from main_registry import app
    from playwright.sync_api import sync_playwright

    monkeypatch.setattr(core, '_telegram_token', lambda: '')
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **k: {'allowed': True})
    monkeypatch.setattr(core, 'fetch_current_cbr_key_rate', lambda: {
        'rate': 14, 'date': '2026-07-24', 'source': 'offline fixture'})
    requests, errors = [], []
    with browser.serve(app, 18979) as url, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chrome:
            page = chrome.new_page(viewport={'width': width, 'height': 1000}, locale='ru-RU')
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.post_data_json)
                    if r.url.endswith('/calculate') else None)
            page.route('**/ia/goal-seek', lambda r: r.fulfill(status=503, json={'reason': 'offline fixture'}))
            page.goto(url + surface, wait_until='domcontentloaded')
            browser.wait_for_result(page)
            x = rental_inputs(land_rent_mode='msk_mkd_3_2', land_rent_preset_confirmed=False,
                land_rent_regime_start=None, land_rights_cost_mln=0, land_rent_premium_status='not_applicable')
            page.evaluate('async x=>{Object.assign(inputs,x);renderInputs();await settledCalculate()}', x)
            browser.open_vri(page)
            date = page.locator('#f_land_rent_regime_start')
            button = page.get_by_role('button', name='Подтвердить эту дату по договору', exact=True)
            assert date.input_value() == x['project_start']
            assert button.is_visible()
            assert 'Для расчёта взята дата проекта 01.01.2027; по договору дата ещё не подтверждена.' in page.locator('#landRentEditor').inner_text()
            count = len(requests)
            # A real unchanged-value keyboard acceptance is not an input edit.
            date.focus();date.press('Enter');date.press('Tab')
            assert page.evaluate('inputs.land_rent_regime_start') is None
            assert len(requests) == count
            assert page.evaluate('lastResult.land_rent.regime_start_assumed') is True
            button.click()
            browser.wait_for_result(page)
            assert len(requests) > count
            assert requests[-1]['inputs']['land_rent_regime_start'] == x['project_start']
            assert requests[-1]['inputs']['land_rent_preset_confirmed'] is False
            assert page.evaluate('inputs._field_origin["inputs.land_rent_regime_start"]') == {
                'source': 'manual', 'text': 'вписано вручную'}
            assert page.evaluate('lastResult.land_rent.regime_start_assumed') is None
            assert page.evaluate('lastResult.summary.land_rent_sum.known') is False
            assert 'conditions' in page.evaluate('lastResult.land_rent.financial_missing_codes')
            assert 'regime_start' not in page.evaluate('lastResult.land_rent.financial_missing_codes')
            assert 'договор с ними ещё не сверен' in page.locator('#landRentSummary').inner_text()
            assert not button.is_visible()

            page.locator('#landRentEditor [data-land-rent-advanced] > summary').click()
            page.locator('#landRentEditor details[data-land-rent-detail="conditions"] > summary').click()
            page.locator('#f_land_rent_preset_confirmed').check()
            browser.wait_for_result(page)
            assert page.evaluate('lastResult.summary.land_rent_sum.known') is True
            assert 'договор с ними ещё не сверен' not in page.locator('#landRentSummary').inner_text()
            assert page.evaluate('inputs.land_rent_regime_start') == x['project_start']
            page.reload(wait_until='domcontentloaded')
            browser.wait_for_result(page)
            browser.open_vri(page)
            assert page.evaluate('inputs.land_rent_regime_start') == x['project_start']
            assert page.evaluate('inputs.land_rent_preset_confirmed') is True
            assert not page.locator('[data-land-rent-confirm-start]').is_visible()

            # A subsequent project start does not overwrite the manually confirmed date.
            page.evaluate('async()=>{inputs.project_start="2027-02-01";renderInputs();await settledCalculate()}')
            assert date.input_value() == x['project_start']
            assert not page.locator('[data-land-rent-confirm-start]').is_visible()
            # Clearing it restores a new visible fallback and the explicit action.
            date.fill('');browser.wait_for_result(page)
            assert page.evaluate('inputs.land_rent_regime_start') is None
            assert date.input_value() == '2027-02-01'
            assert button.is_visible()
            shots = Path('/tmp/plato-rent-same-date-ui');shots.mkdir(exist_ok=True)
            date.locator('..').screenshot(path=str(shots/f'pending-date-{width}-{surface.strip("/") or "main"}.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')

            # Neither a malformed manual value nor an absent fallback can be confirmed.
            run = page.evaluate('calcRun')
            for raw in ['not-a-date', False, 0]:
                page.evaluate('raw=>{inputs.land_rent_regime_start=raw;renderLandRentEditor();landRentConfirmStartDate(document.querySelector("[data-land-rent-confirm-start]"))}', raw)
                assert page.evaluate('inputs.land_rent_regime_start') == raw
                assert not page.locator('[data-land-rent-confirm-start]').is_visible()
                assert page.evaluate('calcRun') == run
            page.evaluate('()=>{inputs.land_rent_regime_start=null;inputs.project_start="invalid";renderLandRentEditor();landRentConfirmStartDate(document.querySelector("[data-land-rent-confirm-start]"))}')
            assert page.evaluate('inputs.land_rent_regime_start') is None
            assert not page.locator('[data-land-rent-confirm-start]').is_visible()
            assert page.evaluate('calcRun') == run
            assert not errors, errors
