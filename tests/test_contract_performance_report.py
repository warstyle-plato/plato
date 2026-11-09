"""The executive contract block keeps every source record and its own metric."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import developaid_management_report as report
import developaid_monitor_contracts as contracts


def record(index=0, ratio=.4, **changes):
    day = '2026-11-06'
    progress = {'ratio': ratio, 'state': 'known' if ratio is not None else 'incomparable',
                'basis': 'statement_union', 'basis_label': 'стоимости работ по ведомостям',
                'origin': 'cumulative_statement', 'observation_date': day, 'date_basis': 'snapshot',
                'comparison_state': 'no_previous_snapshot', 'comparison_reason': 'Предыдущего снимка нет.',
                'reason': 'План одной работы изменился; общий процент не выбран.' if ratio is None else '',
                'delta_percent_points': None, 'period_days': None,
                'series': [{'observation_date': day, 'ratio': ratio,
                            'basis_label': 'стоимости работ по ведомостям'}]}
    value = {'id': f'record-{index}', 'source_kind': 'cumulative', 'contractor': f'Исполнитель {index}',
             'contract': f'КР{index:03}', 'contract_date': '2026-01-01', 'source_date': day,
             'source': {'filename': 'Example.xlsx', 'sheet': 'Работы', 'row': index+9},
             'amount': None, 'completed': None, 'completion_ratio': None, 'progress': progress,
             'statement_progress': {'ratio': ratio, 'state': progress['state'], 'why': progress['reason']},
             'deadline': '2026-12-31', 'risk': {'status': 'on_track', 'label': 'В срок'},
             'advance': {'paid': None}, 'reported_performance_sources': [],
             'warnings': ['INTERNAL-LONG-SOURCE-WARNING'], 'physical_items': [{'name': 'Detailed source work'}]}
    value.update(changes)
    return value


def registry(rows):
    return {'rows': rows, 'source_date': '2026-11-06', 'risk_summary': {'counts': {'overdue': 40}},
            'risk_basis': 'Existing alert basis'}


def make_block(monkeypatch, rows):
    data = registry(rows)
    original = copy.deepcopy(data)
    monkeypatch.setattr(contracts, 'build', lambda *_: data)
    block = report.contract_risks('Example', dt.date(2026, 11, 9))
    assert data == original
    return block


def test_all_records_survive_while_the_existing_alert_limit_and_counts_stay_intact(monkeypatch):
    rows = [record(i, risk={'status': 'overdue', 'label': 'Срок договора прошёл'}) for i in range(40)]
    rows += [record(40, 0), record(41, 1)]
    block = make_block(monkeypatch, rows)
    assert len(block['rows']) == report.CONTRACT_RISK_LIMIT == 30
    assert block['omitted'] == 10 and block['summary'] == registry(rows)['risk_summary']
    assert len(block['performance_rows']) == 42
    assert [row['id'] for row in block['performance_rows']] == [row['id'] for row in rows]
    assert all('physical_items' not in row for row in block['performance_rows'])
    block['performance_rows'][0]['progress']['series'][0]['ratio'] = .99
    assert rows[0]['progress']['series'][0]['ratio'] == .4
    assert block['rows'][0]['progress']['series'][0]['ratio'] == .4
    assert 'Срок договора прошёл' in ' '.join(report._contract_risk_lines(block))


def test_canonical_zero_full_and_unknown_annual_percentages_keep_their_scope(monkeypatch):
    unknown = record(2, None)
    unknown['reported_performance_sources'] = [
        {'period_year': year, 'completion_ratio': value, 'amount_scope': 'statement',
         'future_periods_excluded': False, 'monetary_comparable': True}
        for year, value in [(2025, .25), (2026, .6)]]
    closing = record(3, .5, source_kind='closing_summary')
    closing['progress'].update(origin='dated_closing_summary', basis='closing_summary_contract',
                               basis_label='суммы КС-2 по сводной')
    block = make_block(monkeypatch, [record(0, 0), record(1, 1), unknown, closing])
    assert block['performance_summary'] == {'records': 4, 'primary_known': 3,
        'source_only_known': 1, 'unknown': 0, 'source_percentages': 2}
    markup = report._contract_risks_html(block)
    assert '0,0% стоимости работ по ведомостям' in markup
    assert '100,0% стоимости работ по ведомостям' in markup
    assert '2025 — 25,0%' in markup and '2026 — 60,0%' in markup
    assert '50,0% суммы КС-2 по сводной' in markup
    assert 'План одной работы изменился' in markup and '+35,0 п.п.' not in markup
    assert 'Записей источников: 4' in markup and 'Договоров: 4' not in markup


def test_dynamics_use_only_the_canonical_change_and_label_snapshot_dates(monkeypatch):
    row = record()
    row['progress'].update(ratio=.375, comparison_state='comparable', change_kind='correction',
                           delta_percent_points=-2.5, period_days=31)
    row['progress']['series'].insert(0, {'observation_date': '2026-10-06', 'ratio': .4,
                                        'basis_label': 'стоимости работ по ведомостям'})
    markup = report._contract_risks_html(make_block(monkeypatch, [row]))
    assert '37,5% стоимости работ по ведомостям' in markup
    assert 'Корректировка: -2,5 п.п. за 31 дн.' in markup
    assert 'Снимок 06.11.2026' in markup and '06.10.2026' in markup
    assert 'Дата акта 06.11.2026' not in markup


def test_the_brief_reason_keeps_the_cause_after_a_positive_first_clause(monkeypatch):
    row = record(ratio=None)
    reason = 'Денежные итоги известны; объёмы позиций не подтверждены для объединения.'
    row['progress']['reason'] = reason
    markup = report._contract_risks_html(make_block(monkeypatch, [row]))
    assert "class='contract-caption'>Денежные итоги известны; объёмы позиций не подтверждены для объединения" in markup


def test_missing_records_keep_the_full_block_title_and_an_honest_reason(monkeypatch):
    monkeypatch.setattr(contracts, 'build', lambda *_: {'rows': [], 'empty_reason': 'Архив накопительных отсутствует.'})
    block = report.contract_risks('Example', '2026-11-09')
    markup = report._contract_risks_html(block)
    assert 'Договоры: выполнение и сроки' in markup and 'Архив накопительных отсутствует.' in markup
    assert block['performance_rows'] == []


@pytest.mark.parametrize('width', [390, 1440])
def test_full_compact_table_is_readable_on_screen_and_all_records_reach_pdf(monkeypatch, width, tmp_path):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip, serve
    from market_search import report_pdf
    import pymupdf

    rows = [record(i, 0 if i == 0 else 1 if i == 1 else .4) for i in range(35)]
    rows[2]['contractor'] = '<img src=x onerror="window.bad=true">'
    rows[3] = record(3, None, reported_performance_sources=[
        {'period_year': year, 'completion_ratio': value, 'amount_scope': 'statement',
         'future_periods_excluded': False, 'monetary_comparable': True}
        for year, value in [(2025, .25), (2026, .6)]])
    block = make_block(monkeypatch, rows)
    document = report_pdf.document(report._contract_risks_html(block), style=report.REPORT_STYLE,
                                   title='Договоры: выполнение и сроки')
    app = FastAPI()

    @app.get('/', response_class=HTMLResponse)
    def view():
        return document

    chrome = chromium_or_skip()
    with serve(app, 19041) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome), args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(url, wait_until='load')
            table = page.locator('table.contract-performance')
            expect(table.locator(':scope > thead > tr > th')).to_have_count(4)
            expect(table.locator(':scope > tbody > tr')).to_have_count(35)
            assert 'INTERNAL-LONG-SOURCE-WARNING' not in page.locator('body').inner_text()
            assert page.locator('img').count() == 0 and not page.evaluate('window.bad||false')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if width == 390:
                assert table.evaluate('(t)=>t.parentElement.scrollWidth<=t.parentElement.clientWidth')
                cells = table.locator(':scope > tbody > tr > td')
                assert cells.evaluate_all('(cells)=>cells.every(c=>{const b=c.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth})')
                assert cells.evaluate_all('(cells)=>cells.every(c=>parseFloat(getComputedStyle(c).fontSize)>=13)')
                assert cells.nth(0).evaluate('(c)=>getComputedStyle(c,"::before").content') == '"Подрядчик и договор"'
            else:
                assert table.locator(':scope > tbody > tr').first.evaluate('(r)=>getComputedStyle(r).display') == 'table-row'
            expect(table.locator(':scope > tbody > tr').first).to_contain_text('0,0%')
            expect(table.locator(':scope > tbody > tr').nth(1)).to_contain_text('100,0%')
            expect(table.locator(':scope > tbody > tr').last).to_contain_text('КР034')
            source_cell = table.locator(':scope > tbody > tr').nth(3).locator(':scope > td').nth(1)
            expect(source_cell).to_contain_text('2025 — 25,0%')
            expect(source_cell).to_contain_text('2026 — 60,0%')
            assert '0,0 п.п.' not in page.locator('body').inner_text()
            page.screenshot(path=str(tmp_path/f'contracts-{width}.png'), full_page=True)
        finally:
            browser.close()
    raw = report_pdf.render(document, footer='Учебный проект', executable_path=str(chrome))
    pdf = pymupdf.open(stream=raw, filetype='pdf')
    text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
    assert len(pdf) >= 2
    for row in rows:
        assert row['contract'] in text
    assert 'INTERNAL-LONG-SOURCE-WARNING' not in text
    assert '0,0%' in text and '100,0%' in text
    assert '25,0%' in text and '60,0%' in text
    assert all(0 <= word[0] < word[2] <= page.rect.width and 0 <= word[1] < word[3] <= page.rect.height
               for page in pdf for word in page.get_text('words'))
