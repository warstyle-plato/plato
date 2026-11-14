"""Synthetic canonical register facts stay visible without a comparison plan."""
from __future__ import annotations

import contextlib
import copy
import json

import pytest

import developaid_contract_files as files
from tests.browser import chromium_or_skip
from tests.test_monitor_cumulative_controls import (
    CONTRACT, KEY, MARKER, OTHER, Responses, page_server, register,
)


@contextlib.contextmanager
def execution_page(width, row, listing):
    from playwright.sync_api import sync_playwright

    responses = Responses()
    responses.data = register()
    responses.data['rows'][0] = copy.deepcopy(row)
    with page_server() as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()),
                                     headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': width, 'height': 950})
        page.set_default_timeout(5000)
        page.add_init_script(
            f"localStorage.setItem('plato_projects_key',{json.dumps(KEY)});"
            "localStorage.setItem('monitor_project','Учебный проект');")
        # Only the genuine local PAGE is fetched; every API request is mocked,
        # and every other browser request is aborted before it reaches a host.
        page.route('**/*', lambda route: route.continue_()
                   if route.request.url == url else route.abort())
        page.route('**/monitor/**', responses)
        page.route('**/monitor/contracts/documents', lambda route: route.fulfill(
            json={'pending': False, 'ok': True, **copy.deepcopy(listing)}))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractComparison[aria-busy="false"]').wait_for(state='attached')
        try:
            yield page, responses, errors
        finally:
            browser.close()


@pytest.fixture
def no_plan():
    # Use the native listing/comparison projection, including its real reason.
    result = files.listing('Учебный', CONTRACT, '2026-04-09')
    assert result['comparison']['lines'] == []
    assert not result['control']['total']
    return result


def summary_row(state='known', completed=99_000, ratio=.275):
    row = register()['rows'][0]
    row.update(contractor='Учебный подрядчик', contract='УЧ-73',
               source_kind='closing_summary', amount=360_000,
               completed=None, completion_ratio=None, physical_items=[],
               source_date='2026-04-08', warnings=[], reconciliation={},
               progress={'state': state, 'completed': completed, 'planned': 360_000,
                         'ratio': ratio, 'basis_label': 'суммы договора по сводной',
                         'reason': 'Показатель источника требует проверки.'})
    return row


def visible_execution(page):
    return page.locator('#contractCardSummary [data-label="Денежное выполнение"]')


@pytest.mark.parametrize('width', [390, 1440])
def test_summary_money_is_visible_without_a_plan_and_uses_the_register_reader(no_plan, width):
    from playwright.sync_api import expect

    with execution_page(width, summary_row(), no_plan) as (page, _, errors):
        execution = visible_execution(page)
        expect(execution).to_be_visible()
        expect(execution).to_contain_text('27,5%')
        expect(execution).to_contain_text('99 000 ₽ из 360 000 ₽')
        expect(execution).to_contain_text('КС-2 по сводной')
        expect(execution).to_contain_text('Источник на 08.04.2026')
        expect(execution).to_contain_text('не является физической готовностью')
        expect(execution).to_contain_text('Объёмы КС-6а к этой записи не привязаны')
        # This is the actual shared PAGE helper, not a copied calculation.
        assert execution.evaluate("""(e,id)=>{const expected=document.createElement('div');
            expected.innerHTML=contractCompletedHtml(contractById(id),null);
            return e.textContent.includes(expected.textContent)}""", CONTRACT)
        expect(page.locator('#contractCardSummary [data-label="Срок договора"]')).to_contain_text('Не определён')
        expect(page.locator('#contractCardSummary [data-label="Прогноз окончания"]')).to_contain_text('Не рассчитан')
        expect(page.locator('#contractComparisonInfo')).to_contain_text('Это не означает нулевое выполнение')
        expect(page.locator('#contractComparisonInfo')).not_to_contain_text('В расчёте 0 работ')
        expect(page.locator('#contractFinancialSources')).not_to_have_attribute('open', '')
        assert page.locator('#contractCardSummary > .contract-card-pills > section').count() == 4
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('source', ['closing_summary', 'cumulative'])
@pytest.mark.parametrize('known', [True, False])
def test_known_zero_and_missing_stay_distinct_and_raw_observations_do_not_restore_money(no_plan, source, known):
    from playwright.sync_api import expect

    row = summary_row('known' if known else 'unknown', 0 if known else None, 0 if known else None)
    row['source_kind'] = source
    if source == 'cumulative':
        row.update(completed=0 if known else None, completion_ratio=0 if known else None)
    row['raw_observations'] = [{'amount': 7_654_321, 'completed': 6_543_210,
                                'completion_ratio': .8547}]
    row['financial_source_choice_required'] = not known
    with execution_page(390, row, no_plan) as (page, _, errors):
        execution = visible_execution(page)
        expect(execution).to_be_visible()
        if known:
            expect(execution).to_contain_text('0 ₽')
            expect(execution).to_contain_text('0%')
        else:
            expect(execution.locator('.contract-main-money')).to_have_text('—')
            expect(execution).not_to_contain_text('0%')
            expect(execution).not_to_contain_text('0 ₽')
        expect(execution).not_to_contain_text('6 543 210')
        expect(execution).not_to_contain_text('85,47')
        assert not errors


def test_logical_parent_does_not_claim_an_unselected_source_or_resurrect_raw_money(no_plan):
    from playwright.sync_api import expect

    row = summary_row('unknown', None, None)
    row.update(source_kind='logical_ownership', amount=None, source_date=None,
               raw_observations=[summary_row()], financial_sources=[],
               reported_performance_sources=[])
    with execution_page(390, row, no_plan) as (page, _, errors):
        execution = visible_execution(page)
        expect(execution).to_contain_text('источник не подтверждён')
        expect(execution.locator('.contract-main-money')).to_have_text('—')
        expect(execution).not_to_contain_text('КС-2 по сводной')
        expect(execution).not_to_contain_text('накопительная КС-6а')
        expect(execution).not_to_contain_text('27,5%')
        expect(page.locator('#contractCardSummary [data-label="Сумма договора"]')).to_contain_text('Не подтверждена')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_native_physical_rows_are_accessible_without_a_comparison_plan(no_plan, width):
    from playwright.sync_api import expect

    row = register()['rows'][0]
    row['source_kind'] = 'cumulative'
    physical = row['physical_items'][0]
    physical.update(name='Учебный монтаж ' + MARKER, plan_quantity=80,
                    completed_quantity=17, completion_ratio=.2125,
                    quantity_date='2026-04-07', quantity_cut='2026-04-09',
                    snapshot_date='2026-04-08')
    row['physical_items'] += [
        {**physical, 'name': 'Известный ноль', 'completed_quantity': 0, 'completion_ratio': 0},
        {**physical, 'name': 'Будущий период', 'completed_quantity': None,
         'completion_ratio': None, 'reported_completed_quantity': 91,
         'reported_completion_ratio': .91, 'future_periods_excluded': True,
         'warnings': ['Период после среза исключён.']},
        {**physical, 'name': 'Дата не подтверждена', 'completed_quantity': None,
         'completion_ratio': None, 'reported_completed_quantity': 53,
         'future_periods_excluded': None, 'quantity_date': None},
        {**physical, 'name': 'Справочная ведомость', 'completed_quantity': None,
         'completion_ratio': None, 'reported_completed_quantity': 29,
         'future_periods_excluded': False, 'quantity_date': None},
        {**physical, 'name': 'Сохранённый повтор', 'is_duplicate': True,
         'duplicate_note': 'Повтор исходной строки; не учтён.'},
    ]
    with execution_page(width, row, no_plan) as (page, _, errors):
        button = visible_execution(page).get_by_role('button', name='Открыть исходные объёмы КС-6а (6)')
        expect(button).to_be_visible()
        expect(page.locator('#contractComparisonInfo')).to_contain_text('Это не означает нулевое выполнение')
        button.click()
        source = page.locator('#contractPhysicalSources')
        expect(source).to_have_attribute('open', '')
        expect(source.locator('tr.physical-main').first.locator('[data-label="Выполнено / смонтировано"]')).to_have_text('17 м²')
        expect(source.locator('tr.physical-main').filter(has_text='Известный ноль').locator('[data-label="Выполнено / смонтировано"]')).to_have_text('0 м²')
        for name in ['Будущий период', 'Дата не подтверждена']:
            expect(source.locator('tr.physical-main').filter(has_text=name).locator('[data-label="Выполнено / смонтировано"]')).to_have_text('—')
        reference = source.locator('tr.physical-main').filter(has_text='Справочная ведомость')
        expect(reference.locator('[data-label="Выполнено / смонтировано"]')).to_contain_text('29 м²')
        expect(reference).to_contain_text('По ведомости')
        expect(source.locator('.physical-duplicate')).to_contain_text('Повтор исходной строки; не учтён')
        source.locator('.physical-duplicate summary').click()
        expect(source.locator('.physical-duplicate')).to_contain_text('Исходная строка сохранена')
        future = source.locator('tr.physical-main').filter(has_text='Будущий период')
        future.locator('summary').click()
        expect(future).to_contain_text('Период после среза исключён')
        assert page.locator('#contractsDetails img').count() == 0
        assert page.evaluate('window.untrustedRan') is None
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_print_keeps_visible_money_without_expanding_raw_sources(no_plan, width):
    from playwright.sync_api import expect

    with execution_page(width, summary_row(), no_plan) as (page, _, errors):
        page.emulate_media(media='print')
        expect(visible_execution(page)).to_be_visible()
        expect(visible_execution(page)).to_contain_text('27,5%')
        expect(page.locator('#contractPhysicalSources')).not_to_be_visible()
        expect(page.locator('#contractFinancialSources')).not_to_be_visible()
        expect(page.locator('#contractComparisonInfo')).to_contain_text('не означает нулевое выполнение')
        assert not errors


@pytest.mark.parametrize('change', ['project', 'cut', 'key', 'card'])
def test_context_reset_or_another_card_removes_the_previous_execution(no_plan, change):
    from playwright.sync_api import expect

    with execution_page(390, summary_row(), no_plan) as (page, _, errors):
        expect(visible_execution(page)).to_contain_text('27,5%')
        if change == 'card':
            page.locator('#contractDialogClose').click()
            page.locator(f'tr[data-contract-id="{OTHER}"] .contract-open').click()
            expect(visible_execution(page)).to_contain_text('0 ₽')
            expect(visible_execution(page)).not_to_contain_text('27,5%')
        elif change == 'key':
            page.evaluate("localStorage.removeItem('plato_projects_key');window.dispatchEvent(new StorageEvent('storage',{key:'plato_projects_key'}))")
            expect(page.locator('#contractsDetails')).to_be_empty()
        else:
            page.locator('#' + change).evaluate(
                "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}))}",
                'Учебный второй' if change == 'project' else '2026-04-06')
            expect(page.locator('#contractsDetails')).to_be_empty()
        assert not errors
