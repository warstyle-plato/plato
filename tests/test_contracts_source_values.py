"""Known source totals stay visible without becoming dated execution or price.

All workbook/contract data here is synthetic. Customer documents remain outside
this repository; financial as-of checks are exercised through the real helpers.
"""
from __future__ import annotations

import copy
import io

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

import developaid_monitor_contracts as contracts
from test_monitor_cumulative_controls import browser_page, CONTRACT, KEY
from test_contracts_from_cumulative_headers import context, parsed, provide, rss_contract


def physical(*, amount=100, quantity=10, blank=None, end='2026-01-31'):
    periods = [{'date_start': '2026-01-01', 'date_end': end,
                'amount': 100, 'quantity': 10, 'material_quantity': None,
                'amount_basis': 'without_vat'}]
    if blank is not False:
        extra = {'date_start': '2026-02-01', 'date_end': '2026-02-28',
                 'amount': None, 'quantity': None, 'material_quantity': None,
                 'amount_basis': 'unspecified'}
        extra.update(blank or {})
        periods.append(extra)
    source = {'position': '1', 'name': 'Монтаж', 'scope': 'Корпус А', 'unit': 'м²',
              'plan_quantity': 20, 'completed_quantity': quantity,
              'completed_amount': amount, 'material_quantity': None, 'periods': periods}
    return contracts._physical(source, {'period_year': 2026, 'source_date': '2026-03-01'}, '2026-03-01')


def money(items):
    warnings = []
    result = contracts._cumulative_money(items, warnings)
    return result, warnings


def test_empty_period_cell_does_not_veto_a_strictly_reconciled_item():
    item = physical()
    assert item['completed_amount'] == 100
    before = copy.deepcopy(item)
    (value, basis), warnings = money([item])
    assert value == 100 and basis == 'without_vat'
    assert not warnings
    assert item == before
    assert item['periods'][1]['amount'] is None  # Never replaced by a made-up zero.


@pytest.mark.parametrize('blank', [
    {'quantity': 0}, {'quantity': 2}, {'material_quantity': 0},
    {'material_quantity': 3},
])
def test_unpriced_numeric_work_or_material_is_not_an_empty_period(blank):
    (value, _), warnings = money([physical(blank=blank)])
    assert value is None and warnings


@pytest.mark.parametrize('annual', [None, 101])
def test_unknown_or_unreconciled_annual_money_does_not_gain_an_execution(annual):
    item = physical(amount=annual)
    assert item['completed_amount'] is None
    assert money([item])[0][0] is None


def test_no_execution_record_is_not_an_explicit_zero_execution():
    item = physical(amount=0, quantity=0)
    item['completed_amount'] = 0
    item['periods'] = [item['periods'][1]]
    assert money([item])[0][0] is None
    item['periods'][0].update(amount=0, quantity=0)
    assert money([item])[0][0] == 0


def test_period_overlap_duplicates_and_vat_conflicts_still_block():
    first = physical(blank=False)
    other = copy.deepcopy(first)
    other['periods'][0].update(date_start='2026-01-15', date_end='2026-02-15')
    assert money([first, other])[0][0] is None
    other = copy.deepcopy(first)
    other['periods'][0]['amount'] = 101
    assert money([first, other])[0][0] is None
    other = copy.deepcopy(first)
    other['name'] = 'Другая работа'
    other['periods'][0]['amount_basis'] = 'with_vat'
    assert money([first, other])[0][0] is None
    # Identical evidence remains a single execution.
    assert money([first, copy.deepcopy(first)])[0][0] == 100


def test_nonempty_invalid_date_and_cut_intersection_remain_unknown():
    item = physical(blank=False)
    item['periods'][0]['date_start'] = '2026-02-28'
    assert money([item])[0][0] is None
    item['periods'][0]['date_start'] = None
    assert money([item])[0][0] is None
    assert physical(end='2026-03-31')['completed_amount'] is None


def annual_data(responses, count=1):
    row = responses.data['rows'][0]
    row.update(amount=None, completed=None, completion_ratio=None, remaining=None,
               source_date='2026-11-06', warnings=[], physical_items=[],
               reported_performance_sources=[
                   {'completed': 125_001, 'period_year': 2025, 'source_date': '2026-11-06',
                    'future_periods_excluded': False, 'period_dates_known': False, 'source': {'filename': 'private-ledger-A.xlsx', 'sheet': 'Работы', 'row': 22}},
                   {'completed': 230_002, 'period_year': 2026, 'source_date': '2026-11-05',
                    'future_periods_excluded': False, 'period_dates_known': False, 'source': {'filename': 'private-ledger-B.xlsx', 'sheet': 'Работы', 'row': 35}}])
    responses.data['rows'] = []
    for index in range(count):
        item = copy.deepcopy(row)
        item.update(id=f'{index+1:064x}', contract=f'DEMO-SOURCE-{index+1:02d}',
                    subject='Монтаж инженерных сетей и отделка помещений',
                    contractor='Учебный подрядчик для проверки плотности реестра')
        responses.data['rows'].append(item)
    return responses.data['rows']


@pytest.mark.parametrize('width', [360, 390, 1440])
def test_source_known_money_is_visible_without_opening_details_or_creating_ratio(width):
    with browser_page(width) as (page, responses, errors):
        rows = annual_data(responses)
        rows[0]['remaining'] = 50_000
        rows[0]['completion_ratio'] = .5  # A stale/contradictory ratio cannot price an annual total.
        page.locator('#contractsTab').click()
        row = page.locator('tr[data-contract-id]').first
        cell = row.locator('td').nth(3)
        expect(cell).to_contain_text('125\u00a0001 ₽')
        expect(cell).to_contain_text('230\u00a0002 ₽')
        expect(cell).to_contain_text('2025 год')
        expect(cell).to_contain_text('2026 год')
        expect(cell).to_contain_text('06.11.2026')
        expect(cell).to_contain_text('05.11.2026')
        expect(cell).to_contain_text('Дата выполнения не подтверждена')
        expect(cell).to_contain_text('Суммы не сложены')
        expect(cell).not_to_contain_text('355\u00a0003')
        assert cell.locator('.contract-progress').count() == 0
        assert '50%' not in cell.text_content()
        expect(row.locator('td').nth(2)).to_contain_text('Не подтверждена')
        assert row.locator('td').nth(4).text_content().strip() == '—'
        assert row.locator('.contract-sources').get_attribute('open') is None
        assert 'private-ledger' not in cell.text_content()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_explicit_zero_reference_is_visible_but_absent_reference_is_unknown():
    with browser_page() as (page, responses, errors):
        rows = annual_data(responses, count=2)
        rows[0]['reported_performance_sources'][0]['completed'] = 0
        rows[0]['reported_performance_sources'][1]['completed'] = None
        rows[1]['reported_performance_sources'] = []
        page.locator('#contractsTab').click()
        cells = page.locator('tr[data-contract-id] td:nth-child(4)')
        expect(cells.nth(0)).to_contain_text('0 ₽')
        expect(cells.nth(1)).to_contain_text('Данные выполнения не подтверждены')
        expect(cells.nth(1)).not_to_contain_text('0 ₽')
        assert not errors


def test_dated_execution_uses_the_confirmed_money_instead_of_annual_references():
    with browser_page() as (page, responses, errors):
        row = annual_data(responses)[0]
        row.update(amount=200_000, completed=100_000, completion_ratio=.5, remaining=100_000)
        page.locator('#contractsTab').click()
        cell = page.locator('tr[data-contract-id] td:nth-child(4)')
        expect(cell).to_contain_text('100\u00a0000 ₽')
        expect(cell).to_contain_text('50% суммы договора')
        expect(cell).not_to_contain_text('125\u00a0001')
        expect(cell).not_to_contain_text('Суммы позиций')
        assert not errors


def test_source_totals_are_printed_in_dense_a4_register_and_cleared_after_auth_rejection():
    with browser_page() as (page, responses, errors):
        annual_data(responses, count=18)
        page.locator('#contractsTab').click()
        expect(page.locator('tr[data-contract-id]')).to_have_count(18)
        pdf = PdfReader(io.BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        assert len(pdf.pages) >= 3
        for sheet in pdf.pages:
            assert float(sheet.mediabox.width) == pytest.approx(841.89, abs=2)
            assert float(sheet.mediabox.height) == pytest.approx(595.28, abs=2)
        text = ' '.join(' '.join((x.extract_text() or '').split()) for x in pdf.pages)
        for value in ['125 001', '230 002', '2025 год', '2026 год', '06.11.2026', 'Дата выполнения не подтверждена']:
            assert value in text
        assert 'private-ledger' not in text and KEY not in text
        assert all(f'DEMO-SOURCE-{index+1:02d}' in text for index in range(18))
        responses.reject_key = True
        page.locator('#contractsRefresh').click()
        expect(page.locator('#privateArea')).to_be_hidden()
        assert page.locator('#contractsRows').text_content() == ''
        assert not errors


@pytest.mark.parametrize('start,end', [('2026-12-01', '2026-12-31'), ('2026-11-01', '2026-11-30')])
def test_annual_reference_with_known_future_execution_is_not_exposed_on_earlier_cut(context, start, end):
    snapshot = parsed()
    for ledger in snapshot['ledgers']:
        for item in ledger['items']:
            for period in item['periods']:
                period.update(date_start=start, date_end=end)
    provide(context, snapshot, [rss_contract()])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['completed'] is None and row['completion_ratio'] is None
    assert row['reported_performance_sources']
    assert all(x['future_periods_excluded'] and x['completed'] is None
               for x in row['reported_performance_sources'])


def test_reference_source_year_and_metadata_do_not_expose_a_known_future_total():
    with browser_page() as (page, responses, errors):
        row = annual_data(responses)[0]
        row['reported_performance_sources'][0]['future_periods_excluded'] = True
        page.locator('#contractsTab').click()
        cell = page.locator('tr[data-contract-id] td:nth-child(4)')
        expect(cell).not_to_contain_text('125\u00a0001')
        expect(cell).to_contain_text('230\u00a0002')
        expect(cell).to_contain_text('Ведомость 2')
        row['reported_performance_sources'][1]['future_periods_excluded'] = True
        page.locator('#contractsRefresh').click()
        expect(cell).to_contain_text('Периоды позже среза исключены')
        expect(cell).not_to_contain_text('230\u00a0002')
        assert not errors


def test_old_reference_without_cut_safety_metadata_requires_refresh():
    with browser_page() as (page, responses, errors):
        row = annual_data(responses)[0]
        for ref in row['reported_performance_sources']:
            ref.pop('future_periods_excluded')
        page.locator('#contractsTab').click()
        cell = page.locator('tr[data-contract-id] td:nth-child(4)')
        expect(cell).to_contain_text('Обновите договоры, чтобы проверить периоды источников')
        expect(cell).not_to_contain_text('125\u00a0001')
        assert not errors


@pytest.mark.parametrize('width', [360, 390, 1440])
def test_long_realistic_work_titles_and_scopes_have_bounded_previews_and_full_details(width):
    with browser_page(width) as (page, responses, errors):
        row = annual_data(responses)[0]
        full = 'Подлинное наименование строительных работ ' * 20
        row['subject'] = full
        row['scope'] = [f'Участок {index}: ' + 'Сложная зона работ ' * 8 for index in range(9)]
        row['physical_items'] = [{'name': f'Исходная работа {index}: '+full,
                                  'scope': row['scope'][index % 9], 'warnings': []}
                                 for index in range(12)]
        page.locator('#contractsTab').click()
        work = page.locator('tr[data-contract-id] .contract-works')
        expect(work).to_contain_text('Ещё работ: 10')
        expect(work).to_contain_text('Ещё участков: 7')
        assert len(work.text_content()) < 500
        assert full not in work.text_content()
        page.locator('tr[data-contract-id] .contract-open').click()
        expect(page.locator('#contractsDetails')).to_contain_text(full)
        expect(page.locator('#contractsDetails')).to_contain_text('Исходная работа 11')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
