"""Loan draws preserve unknown source scope/date/amount without guessing zero."""
import datetime as dt
import io

import openpyxl
import pytest

import developaid_management_report as report
import developaid_monitor as monitor
from test_management_report_funding import PROJECT, _rss_with_sources
from test_management_report_model import _gpr_book
from test_management_report_jobs import api, report_ui  # Native PAGE + authenticated local ASGI.

BOUNDS = report.period_bounds('week', '2026-10-18')


def row(day, amount, scope=True):
    return {'date': day, 'amount': amount, 'scope': scope, 'source_row': 10}


@pytest.mark.parametrize('gap', [row(dt.date(2026, 10, 15), 11, None),
                               row(dt.date(2026, 10, 15), None), row(None, 11)])
def test_unreadable_selected_rows_keep_unknown_totals_and_separate_known_parts(gap):
    got = report._sums([row(dt.date(2026, 10, 15), 12), gap], BOUNDS, lambda item: item['scope'])
    assert got['period'] is None and got['month'] is None and got['total'] is None
    assert got['known_part'] == {'period': 12, 'month': 12, 'total': 12}
    assert got['state'] == 'incomplete' and got['incomplete_rows']
    assert got['payments_complete_through_cut'] is None


def test_an_earlier_unknown_scope_does_not_poison_later_unaffected_time_windows():
    got = report._sums([row(dt.date(2026, 9, 15), 11, None),
                        row(dt.date(2026, 10, 15), 12)], BOUNDS, lambda item: item['scope'])
    assert got['period'] == got['month'] == 12
    assert got['total'] is None and got['known_part']['total'] == 12


def test_known_future_and_proven_outside_rows_are_excluded_before_unknown_validation():
    got = report._sums([row(dt.date(2026, 10, 19), None, None), row(None, None, False),
                        row(dt.date(2026, 10, 15), 0), row(dt.date(2026, 10, 15), 15),
                        row(dt.date(2026, 10, 15), -3)], BOUNDS, lambda item: item['scope'])
    assert got['period'] == got['month'] == got['total'] == 12
    assert got['state'] == 'observed' and not got['incomplete_rows']


def test_an_unknown_month_and_an_undated_payment_cannot_be_a_known_cumulative_zero():
    months = ['2026-09', '2026-10', '2026-11']
    assert report._cumulative_observed({'2026-09': 5, '2026-10': None}, months) == [5, None, None]
    assert report._cumulative_observed({'2026-09': 5}, months, undated=True) == [None, None, None]


@pytest.mark.parametrize('code', ['2.999', '4.999', None])
def test_actual_rss_report_and_tile_keep_unknown_draws_and_known_parts(tmp_path, monkeypatch, code):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    monitor.store_schedule(PROJECT, _gpr_book({}), None, '2026-07-01')
    book = openpyxl.load_workbook(io.BytesIO(_rss_with_sources()))
    payments = book['Реестр платежей']
    payments['G12'] = code  # Previously known 30m borrowed payment in the selected week.
    data = io.BytesIO()
    book.save(data)
    book.close()
    monitor.store_estimate(PROJECT, data.getvalue(), '2026-10-18')
    limit = {'known': True, 'chapters': ['2', '3'], 'bank_limit': 1000000000,
             'paid_actual': None, 'bank_remaining': 0, 'reserve': 0,
             'additional_financing': 0}
    view = {'dashboard': {'funding': limit}}
    monkeypatch.setattr(report, '_monitor_view', lambda *_: view)
    built = report.build(PROJECT, 'week', '2026-10-18')
    draws = built['funding']['draws']
    assert draws['total'] is None and draws['period'] is None
    assert draws['known_part']['total'] == 418000000
    assert built['funding']['draws_monthly']['2026-10'] is None
    tile = next(item for item in report.tiles(built) if item['label'] == 'Выбрано у банка')
    assert tile['value'] == 'нет данных'
    assert 'Известная часть' in tile['note'] and 'не полный итог' in tile['note']
    assert 'Известная часть' in report.render_html(built) and 'Известная часть' in report.render_text(built)


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('unknown', [False, True], ids=['known', 'unknown'])
def test_native_report_downloads_canonical_pdf_and_preserves_a_gap_in_loan_chart(
        report_ui, tmp_path, monkeypatch, width, unknown):
    import pymupdf
    from playwright.sync_api import expect
    import developaid_admin_expenses_cash as cash
    import developaid_monitor_dashboard as dashboard
    from test_funding_source_dates import source_case
    from test_management_report_jobs import core

    page, base = report_ui
    page.set_viewport_size({'width': width, 'height': 844})
    _, view = source_case(tmp_path, monkeypatch)
    rss = monitor._latest(PROJECT, 'estimate', '.xlsx', '2026-10-20')
    if unknown:
        book = openpyxl.load_workbook(rss)
        book['Реестр платежей']['G12'] = None
        stream = io.BytesIO(); book.save(stream); book.close()
        monitor.store_estimate(PROJECT, stream.getvalue(), '2026-10-19')
        rss = monitor._latest(PROJECT, 'estimate', '.xlsx', '2026-10-20')
    funding = dashboard._funding_risk(PROJECT, rss, dt.date(2026, 10, 20), {})
    view['dashboard']['funding'] = funding
    built = report.build(PROJECT, 'week', '2026-10-20')
    canonical = funding['reconciliation']
    assert built['funding']['limit']['reconciliation'] == canonical
    assert canonical['confirmed_additional'] is None and not canonical['financial_acceptance_performed']
    assert built['funding']['draws']['total'] == (None if unknown else 498_000_000)
    monkeypatch.setattr(core, '_monitor_report_projects', lambda: {
        'projects': [{'project': PROJECT}], 'sales_projects': []})
    page.goto(base + '/report')
    expect(page.locator('#reportBox h1')).to_contain_text(PROJECT, timeout=5_000)
    page.locator('#cut').fill('2026-10-20')
    page.locator('#cut').dispatch_event('change')
    expect(page.locator('#reportMsg')).to_be_empty()
    tiles = report.tiles(built)
    labels = page.locator('#reportBox .tile .k').all_text_contents()
    for _, label in cash.FIELDS:
        assert labels.count(label) == 0  # Main63 keeps cash values in printable details.
    cash_details = page.locator('#reportBox .admin-expenses-cash > details:not(.admin-fm-source) > p')
    assert cash_details.count() == 4
    assert cash_details.all_text_contents() == [
        f'{label}: {cash.money(built["admin_expenses_cash"].get(key))}' for key, label in cash.FIELDS]
    headline = page.locator('#reportBox .tile').filter(has=page.locator('.k', has_text='Потребность в допфинансировании'))
    expect(headline).to_have_count(1)
    expect(headline.locator('.v')).to_have_text('нет данных')
    for row in canonical['display_rows']:
        expect(page.locator('#reportBox')).to_contain_text(row['label'])
        if row['key'] in {'budget', 'bank_limit_total', 'paid_at_cut', 'available_bank_limit'}:
            expected = next(item for item in tiles if item['label'] == row['label'])
            tile = page.locator('#reportBox .tile').filter(has=page.locator('.k', has_text=row['label']))
            expect(tile.locator('.v')).to_have_text(expected['value'])
        else:
            assert row['label'] not in labels  # Diagnostics are retained in the canonical detail table.
        if row['key'] == 'calculated_additional':
            cell = page.locator('#reportBox').get_by_role('cell', name=row['label'], exact=True)
            expect(cell).to_have_count(1)
            expect(cell.locator('xpath=..').locator('td').nth(1)).to_have_text(report._rub(row['value']))
    figure = page.locator('#reportBox figure').filter(has=page.locator(
        'figcaption', has_text='Выборка кредита и эскроу нарастающим итогом по месяцам'))
    paths = figure.locator('svg path[stroke-width="2"]')
    assert paths.count() == 1
    assert paths.first.get_attribute('d').count('L') == (0 if unknown else 1)
    if unknown:
        expect(page.locator('#reportBox')).to_contain_text('Выборка кредита не определена полностью')
        expect(page.locator('#reportBox')).to_contain_text('Известная часть учтённых оплат')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    with page.expect_download() as downloaded:
        page.locator('#reportPdfBtn').click()
    path = tmp_path / f'canonical-{width}-{unknown}.pdf'
    downloaded.value.save_as(path)
    expect(page.locator('#reportMsg')).to_have_text('PDF скачан.')
    pdf = pymupdf.open(path)
    text = ' '.join(' '.join(sheet.get_text().split()) for sheet in pdf)
    cover = ' '.join(pdf[0].get_text().split())
    for key, label in cash.FIELDS:
        assert label in text and cash.money(built['admin_expenses_cash'].get(key)) in text
        if key != 'balance_after_observed_payments':
            assert label.casefold() not in cover.casefold()
    # Exact native main50 bfe439f9, with this same no-credit source DTO,
    # starts the construction block on page 3 (y=55.8). Its missing-credit
    # and other native findings already extend the cover to two pages.
    # Keep the separate cash/reference fixture's strict page-2 assertion.
    headings = [(index + 1, line['bbox'][1])
                for index, sheet in enumerate(pdf)
                for block in sheet.get_text('dict')['blocks'] if 'lines' in block
                for line in block['lines']
                if ''.join(span['text'] for span in line['spans']).strip() == 'Стройка']
    assert len(headings) == 1
    assert headings[0][0] <= 3 and headings[0][1] < 120
    for row in canonical['display_rows']:
        assert row['label'] in text
        if row['key'] == 'calculated_additional':
            assert report._rub(row['value']) in text
    assert 'Финансовая сверка первичных источников не завершена' in text
    assert ' '.join(built['credit_due']['reason'].split()) in text
    if unknown:
        assert 'Выборка кредита не определена полностью' in text
        assert 'Известная часть учтённых оплат' in text
    assert '<b>Административные расходы · статья 2.6</b>' not in report.render_text(built)
    page.screenshot(path=str(tmp_path / f'canonical-{width}-{unknown}.png'), full_page=True)
