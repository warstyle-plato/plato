"""A statement's known totals are useful even without dated KS-2 periods."""
from __future__ import annotations

import copy
import io
import json

import pytest
import openpyxl
from playwright.sync_api import expect
from pypdf import PdfReader

import developaid_monitor_contracts as contracts
from test_contracts_from_cumulative_headers import ARCHIVE_READER, context, parsed, provide
from test_monitor_cumulative_controls import browser_page
from test_monitor_cumulative_ledgers import archive, book
import developaid_monitor_ledgers as ledgers


def source_view(context, *, count=1):
    snapshot = parsed(*[(f'Statement-{i}.xlsx', book(split=True)) for i in range(count)])
    provide(context, snapshot)
    return contracts.build('Example', '2026-11-06')


def test_statement_percentage_keeps_unknown_dated_execution_and_source_price_separate(context):
    row, = source_view(context)['rows']
    source, = row['reported_performance_sources']
    assert row['amount'] is None and row['completed'] is None and row['completion_ratio'] is None
    assert row['risk']['forecast_finish'] is None
    assert source['amount_scope'] == 'statement'
    assert source['stated_contract_amount'] == 1000
    assert source['planned'] == 1020 and source['completed'] == 700
    assert source['completion_ratio'] == pytest.approx(700 / 1020)
    assert source['completed_works'] == 200 and source['completed_materials'] == 500
    work = row['physical_items'][0]
    assert work['completed_quantity'] is None and work['completion_ratio'] is None
    assert work['reported_completed_quantity'] == 4 and work['reported_completion_ratio'] == .4


@pytest.mark.parametrize('missing', ['planned_amount', 'completed_amount'])
def test_missing_statement_value_cannot_become_zero_or_complete_percentage(context, missing):
    snapshot = parsed(('Statement.xlsx', book(split=True)))
    snapshot['ledgers'][0]['items'][0][missing] = None
    provide(context, snapshot)
    row, = contracts.build('Example', '2026-11-06')['rows']
    source, = row['reported_performance_sources']
    assert source['completion_ratio'] is None


def test_future_period_does_not_leak_statement_percentage(context):
    snapshot = parsed(('Statement.xlsx', book(split=True)))
    for item in snapshot['ledgers'][0]['items']:
        for period in item['periods']:
            period.update(date_start='2026-12-01', date_end='2026-12-31')
    provide(context, snapshot)
    row, = contracts.build('Example', '2026-11-06')['rows']
    source, = row['reported_performance_sources']
    assert source['future_periods_excluded']
    assert source['completed'] is None and source['completion_ratio'] is None


def tax_mismatch_book():
    wb = openpyxl.load_workbook(io.BytesIO(book(split=True)))
    ws = wb.active
    ws['G6'] = 'Сметная (договорная) стоимость с НДС'
    for cell in ('J8', 'K8', 'P8', 'Q8'):
        ws[cell] = str(ws[cell].value) + ' без НДС'
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_explicit_different_tax_bases_do_not_create_a_statement_ratio(context):
    provide(context, parsed(('Statement.xlsx', tax_mismatch_book())))
    row, = contracts.build('Example', '2026-11-06')['rows']
    source, = row['reported_performance_sources']
    assert source['planned'] == 1020 and source['completed'] == 700
    assert source['monetary_comparable'] is False and source['completion_ratio'] is None


@pytest.mark.parametrize('original_available', [True, False])
def test_old_saved_import_does_not_lose_known_tax_mismatch(context, original_available):
    imported = ledgers.store_archive('Example', archive([('Statement.xlsx', tax_mismatch_book())]),
                                    '2026-03-01', 'Existing.zip')
    root = ledgers._root('Example')
    path = root / (imported['snapshot_id'] + '.json')
    saved = json.loads(path.read_text())
    saved.pop('parser_schema', None)
    for ledger in saved['ledgers']:
        for item in ledger['items']:
            item.pop('planned_amount_basis', None)
            item.pop('completed_amount_basis', None)
    path.write_text(json.dumps(saved, ensure_ascii=False))
    if not original_available:
        (root / (imported['snapshot_id'] + '.zip')).unlink()
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    row, = contracts.build('Example', '2026-03-01')['rows']
    source, = row['reported_performance_sources']
    assert source['completed'] == 700 and source['completion_ratio'] is None
    projected = ledgers.latest_snapshot('Example', '2026-03-01')
    assert projected['source_parse_state'] == ('refreshed' if original_available else 'original_unavailable')
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before


def test_overlapping_statement_copies_get_their_own_ratio_not_a_combined_execution(context):
    row, = source_view(context, count=2)['rows']
    assert row['completed'] is None and row['completion_ratio'] is None
    assert len(row['reported_performance_sources']) == 2
    assert all(x['completed'] == 700 and x['planned'] == 1020
               for x in row['reported_performance_sources'])


@pytest.mark.parametrize('width', [390, 1440])
def test_primary_register_and_physical_rows_show_statement_percentages(context, width):
    register = source_view(context)
    with browser_page(width) as (page, responses, errors):
        responses.data = copy.deepcopy(register)
        page.locator('#contractsTab').click()
        row = page.locator('tr[data-contract-id]').first
        expect(row.locator('td').nth(2)).to_contain_text('В ведомости')
        expect(row.locator('td').nth(2)).to_contain_text('1\u00a0000 ₽')
        expect(row.locator('td').nth(3)).to_contain_text('68,6% стоимости ведомости')
        expect(row.locator('td').nth(3)).to_contain_text('Работы и материалы')
        assert 'суммы договора' not in row.locator('td').nth(3).inner_text()
        assert 'Уточнить полную сумму договора' not in row.inner_text()
        expect(row.locator('.term')).to_contain_text('Для прогноза нужны даты КС-2 или предыдущий сопоставимый срез')
        row.locator('.contract-open').click()
        work = page.locator('.physical-main').first
        expect(work.locator('td').nth(2)).to_contain_text('4 м2')
        expect(work.locator('td').nth(3)).to_contain_text('8 м2')
        expect(work.locator('td').nth(4)).to_contain_text('40%')
        expect(work.locator('td').nth(4)).to_contain_text('По ведомости')
        assert '80%' not in work.locator('td').nth(4).inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            pdf = PdfReader(io.BytesIO(page.pdf(prefer_css_page_size=True)))
            content = ' '.join(' '.join(sheet.extract_text() or '' for sheet in pdf.pages).split())
            assert '68,6%' in content and 'стоимости ведомости' in content
        assert not errors
