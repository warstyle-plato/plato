"""Rent qualifications remain visible while the decision evaluates model economics."""
import copy
import socket

import pytest

import main
from tests import browser
from tests.test_land_rent_result_clarity import rental_inputs

core = main.core


@pytest.mark.parametrize('known', [False, True])
@pytest.mark.parametrize('metric,value,profit,title,tone', [
    ('llcr', 1.3, 100, 'Экономика проходит', 'pass'),
    ('llcr', 1.1, 100, 'Экономика на границе', 'edge'),
    ('llcr', .9, 100, 'Экономика не проходит', 'fail'),
    ('llcr', None, 100, 'LLCR не рассчитан', ''),
    ('dscr', 1.3, 100, 'Экономика проходит', 'pass'),
    ('dscr', .9, 100, 'Экономика не проходит', 'fail'),
    (None, None, 100, 'Экономика проходит по прибыли', 'edge'),
    (None, None, -100, 'Экономика не проходит', 'fail'),
])
def test_rent_confirmation_does_not_change_economic_thresholds(known, metric, value, profit, title, tone):
    bundle = {'consolidated': {
        'summary': {'preliminary': True, 'llcr': value, 'net_profit': profit,
                    'land_rent_sum': {'known': known, 'reason': 'Проверить договор аренды.'}},
        'land_rent': {'financial_complete': False, 'construction_total': 3e6},
        'report': {'layout': {'debt_metric': {'key': metric, 'value': value}}},
    }}
    before = copy.deepcopy(bundle)
    assert core.entry_price_verdict(bundle) == {'title': title, 'tone': tone}
    assert bundle == before


@pytest.mark.parametrize('status,title', [
    ('conditional', 'Предварительная экономика: есть неоценённые обязательства'),
    ('review', 'Предварительная экономика: перепроверьте условия документа'),
])
def test_nonrent_document_qualifications_still_apply(status, title):
    bundle = {'consolidated': {'summary': {
        'llcr': 9, 'preliminary': True, 'land_rent_sum': {'known': False},
        'intake_qualification': {'status': status, 'reason': 'Обязательство по строительству школы.'},
    }}}
    assert core.entry_price_verdict(bundle) == {'title': title, 'tone': 'edge'}


@pytest.mark.parametrize('price,title,tone', [
    (500, 'Экономика проходит', 'pass'),
    (300000, 'Экономика не проходит', 'fail'),
])
def test_real_model_keeps_rental_costs_and_its_economic_verdict(price, title, tone):
    x = rental_inputs(land_rent_regime_start=None, purchase_price_mln=price, apartment_price_th=900, land_rent_cadastral_target_mln=100)
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert result['summary']['preliminary'] is True
    assert result['summary']['land_rent_sum']['known'] is False
    assert result['capex']['land_rent'] == pytest.approx(3e6)
    before = copy.deepcopy((result, x))
    block = core.entry_price_block({'consolidated': result}, x, None)
    assert block['verdict'] == {'title': title, 'tone': tone}
    assert result['report']['entry_price_verdict'] == block['verdict']
    assert (result, x) == before
    # Changing the rent amount still changes the genuine financial calculation.
    dearer = core.calculate(core.CalcRequest(
        inputs={**x, 'land_rent_cadastral_mln': 1000, 'land_rent_cadastral_target_mln': 1000},
        tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert dearer['capex']['land_rent'] == pytest.approx(30e6)
    assert dearer['summary']['net_profit'] < result['summary']['net_profit']


@pytest.mark.parametrize('width', [390, 1440])
def test_native_result_shows_feasibility_and_separate_rental_notice(width, monkeypatch, tmp_path):
    from main_registry import app
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setattr(core, '_telegram_token', lambda: '')
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **kw: {'allowed': True})
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    with browser.serve(app, port) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chrome:
            page = chrome.new_page(viewport={'width': width, 'height': 1000}, locale='ru-RU')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            # The verdict must be correct even before or without price search.
            page.route('**/ia/goal-seek', lambda route: route.fulfill(status=503, json={'reason': 'Synthetic unavailable price search'}))
            page.goto(base, wait_until='domcontentloaded')
            browser.wait_for_result(page)
            hint = page.locator('#iaFabHint button')
            if hint.count():
                hint.click()
            for price, title, tone in [(500, 'Экономика проходит', 'pass'),
                                       (300000, 'Экономика не проходит', 'fail')]:
                page.evaluate('''async x=>{
                    Object.assign(inputs,x);renderInputs();await settledCalculate();
                }''', rental_inputs(land_rent_regime_start=None, purchase_price_mln=price, apartment_price_th=900, land_rent_cadastral_target_mln=100))
                page.locator('.ia-nav').get_by_role('button', name='Результат', exact=True).click()
                expect(page.locator('#iaVerdictTitle')).to_have_text(title)
                assert page.locator('#iaVerdict').evaluate('(e,tone)=>e.classList.contains(tone)', tone)
                expect(page.locator('#landRentResultNotice')).to_have_text(
                    'Расчёт с допущениями по аренде. Проверить аренду')
                assert page.evaluate('lastResult.summary.preliminary') is True
                assert page.evaluate('lastResult.summary.land_rent_sum.known') is False
                assert page.evaluate('lastResult.capex.land_rent') == pytest.approx(3e6)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                page.locator('#iaVerdict').screenshot(path=str(tmp_path / f'decision-{width}-{tone}.png'))
            assert not errors, errors
