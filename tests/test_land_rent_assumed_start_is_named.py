"""A computed rent names its unconfirmed date; absent amounts stay unknown."""
import copy
from pathlib import Path

import pytest

import developaid_land_rent as rent
import main
from tests import browser
from tests.test_land_rent_result_clarity import rental_inputs

core = main.core
ASK_DATE = 'Предварительная экономика: подтвердите дату начала аренды'
ASK_RENT = 'Предварительная экономика: уточните аренду земли'


def calculated(**changes):
    inputs = rental_inputs(land_rent_regime_start=None, land_rights_cost_mln=0)
    inputs.update(changes)
    return core.calculate(core.CalcRequest(inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))


def test_computed_rent_keeps_unknown_state_and_names_its_assumed_start():
    result = calculated()
    source, state = result['land_rent'], result['summary']['land_rent_sum']
    assert source['construction_total'] == source['total'] == pytest.approx(3e6)
    assert source['regime_start_assumed'] is True and source['complete'] is True
    assert state['known'] is False and state['reason_code'] == 'regime_start'
    assert source['financial_complete'] is False and result['summary']['preliminary'] is True
    assert 'Дата начала аренды по договору не указана' in state['reason']
    assert result['report']['entry_price_verdict'] == {'title': ASK_DATE, 'tone': 'edge'}


@pytest.mark.parametrize('changes', [
    {'land_rent_rates': []},
    {'land_rent_termination_date': None},
    {'land_rent_cadastral_target_mln': None, 'land_rights_cost_mln': 100},
    {'land_rent_tail_rule': 'unknown'},
])
def test_an_assumed_start_never_hides_another_missing_amount_or_term(changes):
    result = calculated(**changes)
    assert result['summary']['land_rent_sum']['known'] is False
    assert 'reason_code' not in result['summary']['land_rent_sum']
    assert result['report']['entry_price_verdict'] == {'title': ASK_RENT, 'tone': 'edge'}


@pytest.mark.parametrize('source_change', [
    {'total': float('nan')}, {'complete': False}, {'regime_start_assumed': False},
    {'financial_missing': ['assumed start', 'another uncertainty']},
    {'financial_missing_codes': ['regime_start', 'conditions']},
])
def test_only_the_narrow_computed_start_assumption_gets_the_specific_reason(source_change):
    source = calculated()['land_rent']
    state = rent.sum_state({**source, **source_change})
    assert state['known'] is False and 'reason_code' not in state


@pytest.mark.parametrize('accepted_start', [None, 'not-a-date'])
def test_an_assumed_start_flag_without_a_valid_accepted_date_keeps_the_generic_warning(accepted_start):
    source = calculated()['land_rent']
    source['regime_start'] = accepted_start
    before = copy.deepcopy(source)
    state = rent.sum_state(source)
    assert state == {'known': False, 'reason': source['financial_missing'][0]}
    assert source == before
    assert core.entry_price_verdict({'consolidated': {
        'summary': {'preliminary': True, 'land_rent_sum': state}, 'land_rent': source,
    }}) == {'title': ASK_RENT, 'tone': 'edge'}


@pytest.mark.parametrize('width', [390, 1440])
def test_native_page_names_assumed_date_but_missing_rate_keeps_the_rent_warning(width, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from main_registry import app
    monkeypatch.setattr(core, '_telegram_token', lambda: '')
    monkeypatch.setattr(core, 'require_calc_access', lambda *a, **kw: {'allowed': True})
    with browser.serve(app, 18997) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={'width': width, 'height': 1000}, locale='ru-RU')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/ia/goal-seek', lambda route: route.fulfill(status=503, json={'reason': 'offline test'}))
            page.goto(base, wait_until='domcontentloaded')
            browser.wait_for_result(page)
            if page.locator('#iaFabHint button').count():
                page.locator('#iaFabHint button').click()
            page.evaluate('''async x=>{Object.assign(inputs,x);renderInputs();await settledCalculate()}''',
                          rental_inputs(land_rent_regime_start=None, land_rights_cost_mln=0))
            page.locator('.ia-nav').get_by_role('button', name='Результат', exact=True).click()
            expect(page.locator('#iaVerdictTitle')).to_have_text(ASK_DATE)
            assert not page.locator('#iaVerdict').evaluate("e=>e.classList.contains('pass')")
            row = page.locator('#projectParamsTable tr').filter(has=page.get_by_text('Аренда земли участка', exact=True))
            expect(row).to_contain_text('3 млн')
            expect(row).to_contain_text('Дата начала аренды по договору не указана')
            state = page.evaluate('({start:inputs.land_rent_regime_start,assumed:lastResult.land_rent.regime_start,known:lastResult.summary.land_rent_sum.known})')
            assert state == {'start': None, 'assumed': '2027-01-01', 'known': False}
            shots = Path('/tmp/plato-rent-assumed-date-20261114')
            shots.mkdir(mode=0o700, exist_ok=True)
            page.locator('#iaVerdict').screenshot(path=str(shots / f'assumed-date-headline-{width}.png'))
            row.screenshot(path=str(shots / f'assumed-date-amount-{width}.png'))
            page.evaluate('''async ()=>{inputs.land_rent_regime_start='2027-01-01';inputs.land_rent_rates=[];renderInputs();await settledCalculate()}''')
            expect(page.locator('#iaVerdictTitle')).to_have_text(ASK_RENT)
            expect(row).to_contain_text('Не определена')
            page.locator('#iaVerdict').screenshot(path=str(shots / f'missing-rate-headline-{width}.png'))
            assert page.evaluate('lastResult.land_rent.regime_start_assumed') is None
            assert page.evaluate('lastResult.land_rent.complete') is False
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            assert errors == []
