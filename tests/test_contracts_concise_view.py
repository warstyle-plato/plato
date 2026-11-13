"""Users see answers and missing inputs; calculation evidence opens on demand."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from contract_rows import opened
from test_monitor_cumulative_controls import CONTRACT, browser_page


@pytest.mark.parametrize('width', [390, 1440])
def test_contract_answers_are_visible_and_calculation_details_are_optional(width):
    with browser_page(width) as (page, responses, errors):
        row = responses.data['rows'][0]
        row.update(subject='Монтаж инженерных сетей', amount=1_000_000, completed=250_000,
                   completion_ratio=.25, remaining=750_000, deadline='2026-11-30',
                   deadline_passed=False, warnings=[])
        row['risk'] = {'status': 'late', 'label': 'Не успевает к сроку',
                       'forecast_finish': '2026-12-15', 'delay_days': 15,
                       'pace_per_day': 2500, 'pace_window': ['2026-09-01', '2026-10-31'],
                       'pace_basis': 'works', 'reason': 'Проверочное основание расчёта срока.'}
        row['advance'] = {'paid': 400_000, 'unworked': 150_000,
                          'basis': 'works', 'reason': 'Проверочное основание сверки платежей.'}
        row['source'] = {'filename': 'technical-source.xlsx', 'row': 41}
        row['physical_items'][0]['quantity_basis'] = 'Проверочное происхождение объёма.'
        row['reconciliation']['issues'] = ['Проверочное замечание к исходному сообщению.']
        page.locator('#contractsTab').click()
        first = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(first.locator('.term')).to_contain_text('15.12.2026')
        visible = first.inner_text()
        assert '25%' in visible and 'задержка 15 дн.' in visible
        for private in ('technical-source.xlsx', 'Темп работ', 'Проверочное основание', '01.09.2026'):
            assert private not in visible
        assert 'Что входит в реестр' not in page.locator('#contractsPanel').inner_text()
        assert len(page.locator('.contract-register-note').inner_text()) < 110
        # All secondary evidence starts closed in the single modal.
        first.locator('.contract-open').click()
        more=page.locator('#contractsDetails')
        shown = more.inner_text()
        for private in ('technical-source.xlsx', 'Темп работ', 'Проверочное основание'):
            assert private not in shown
        more.locator('#contractFinancialSources > summary').click()
        more.locator('#contractRecordSources > summary').click()
        more.locator('#contractRecordSources > .contract-sources > summary').click()
        expect(more.locator('#contractRecordSources')).to_contain_text('technical-source.xlsx')
        assert 'Темп работ' in more.inner_text()
        assert 'Проверочное основание расчёта срока.' in more.inner_text()
        more.locator('#contractPhysicalSources > summary').click()
        assert '35%' in more.inner_text() and '100 м²' in more.inner_text()
        assert 'Проверочное происхождение объёма.' not in more.inner_text()
        assert 'Проверочное замечание к исходному сообщению.' not in more.inner_text()
        physical = more.locator('.physical-source .contract-sources')
        physical.locator('summary').click()
        assert 'Проверочное происхождение объёма.' in more.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/contracts-concise-{width}.png', full_page=True)
        assert not errors


def test_missing_forecast_inputs_have_short_specific_explanations():
    with browser_page() as (page, responses, errors):
        row = responses.data['rows'][0]
        row.update(amount=None, completed=None, completion_ratio=None, remaining=None)
        row['risk'] = {'status': 'unknown', 'label': 'Прогноз неизвестен',
                       'reason': 'Длинное техническое пояснение. ' * 20}
        page.locator('#contractsTab').click()
        first = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        assert first.locator('.term .contract-risk').get_attribute('title') == 'Для прогноза нужна полная сумма договора.'
        more = opened(page, CONTRACT)
        expect(more.locator('.contract-money-forecast')).to_contain_text('Для прогноза нужна полная сумма договора.')
        for shown in (first, more):
            assert 'Длинное техническое пояснение' not in shown.inner_text()
        assert not errors


@pytest.mark.parametrize(('amount', 'reason', 'expected'), [
    (0, 'Нет подтверждённой полной суммы договора.', 'Для прогноза нужна полная сумма договора.'),
    (1_000_000, 'В последних периодах нет положительного выполнения.', 'В последних периодах нет выполнения.'),
    (1_000_000, 'При текущем темпе остаток займёт больше 100 лет; прогноз не показывается.',
     'Текущего темпа недостаточно для прогноза окончания.'),
])
def test_forecast_short_reason_distinguishes_missing_price_from_zero_pace(amount, reason, expected):
    with browser_page() as (page, responses, errors):
        row = responses.data['rows'][0]
        row.update(amount=amount, completed=0, completion_ratio=None, remaining=None)
        row['risk'] = {'status': 'unknown', 'label': 'Прогноз неизвестен', 'reason': reason}
        page.locator('#contractsTab').click()
        term = opened(page, CONTRACT).locator('.contract-money-forecast')
        expect(term).to_contain_text(expected)
        assert 'свежие данные' not in term.inner_text()
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_contract_tab_hides_unrelated_navigation_and_monitor_restores_it(width):
    with browser_page(width) as (page, responses, errors):
        navigation = page.locator('nav.contour')
        navigation_menu = page.locator('.monitor-app-nav')
        expect(navigation_menu).to_be_visible()
        expect(navigation).to_be_hidden()
        navigation_menu.locator('summary').click()
        expect(navigation).to_be_visible()
        page.locator('#contractsTab').click()
        expect(page.locator('tr[data-contract-id]')).to_have_count(2)
        expect(navigation_menu).to_be_hidden()
        expect(navigation).to_be_hidden()
        assert 'Коммерции' not in page.locator('body').inner_text()
        page.screenshot(path=f'/tmp/contracts-focused-{width}.png', full_page=True)
        page.locator('#monitorTab').click()
        expect(navigation_menu).to_be_visible()
        expect(navigation).to_be_visible()
        expect(navigation).to_contain_text('Коммерции')
        navigation_menu.locator('summary').click()
        expect(navigation).to_be_hidden()
        assert not errors
