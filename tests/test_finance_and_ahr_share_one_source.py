"""The composed financial view keeps one budget and one independent AHR widget set."""
import datetime as dt
import hashlib
import io

import openpyxl
import pytest

import developaid_admin_expenses as admin
import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_funding_source_dates import source_case
from test_management_report_funding import PROJECT


def composed(tmp_path, monkeypatch, *, unknown_payment=False):
    _, view = source_case(tmp_path, monkeypatch, missing_dates=True)
    if unknown_payment:
        original = monitor._latest(PROJECT, 'estimate', '.xlsx', '2026-10-20')
        book = openpyxl.load_workbook(io.BytesIO(original.read_bytes()))
        sheet = book['Реестр платежей']
        row = sheet.max_row + 1
        for column, value in ((2, 'Synthetic payer'), (7, '2.999'),
                              (9, dt.date(2026, 10, 15)), (10, 123), (11, 'Заемные средства')):
            sheet.cell(row, column, value)
        data = io.BytesIO()
        book.save(data)
        book.close()
        monitor.store_estimate(PROJECT, data.getvalue(), '2026-10-19')
    cut = dt.date(2026, 10, 20)
    rss = monitor._latest(PROJECT, 'estimate', '.xlsx', cut.isoformat())
    funding = dashboard._funding_risk(PROJECT, rss, cut, {})
    model = admin.for_project(PROJECT, cut.isoformat())
    view['dashboard']['funding'] = funding
    view['dashboard']['construction']['approved'] = funding.get('approved')
    view.update(admin_expenses=model, admin_expenses_html=admin.render(model))
    monkeypatch.setattr(report, '_monitor_view', lambda *_: view)
    return report.build(PROJECT, 'week', cut.isoformat()), view, rss


@pytest.mark.parametrize('unknown_payment', [False, True])
def test_one_source_has_one_budget_and_three_ahr_tiles_without_a_second_expense(tmp_path, monkeypatch, unknown_payment):
    built, view, rss = composed(tmp_path, monkeypatch, unknown_payment=unknown_payment)
    funding = view['dashboard']['funding']
    reconciliation = funding['reconciliation']
    model = view['admin_expenses']
    assert reconciliation['budget'] == 1440000
    assert funding['budget_composition']['total'] == 1440000
    assert model['total'] == 40000 and model['fact'] == model['plan'] == 20000
    assert model['source']['sha256'] == funding['budget_composition']['source_sha256']
    assert model['scope'] == 'raw_saved_snapshot' and model['cut_eligibility'] == 'unknown'
    assert reconciliation['observation_scope'] == 'raw_saved_sources'
    assert reconciliation['amounts_at_selected_cut'] is None
    assert not model['financial_acceptance'] and not reconciliation['financial_acceptance_performed']
    assert all(value is None for value in model['amounts_at_cut'].values())
    tiles = [item for item in report.tiles(built) if item.get('group') == 'admin_expenses']
    assert [item['label'] for item in tiles] == [label for _, label in admin.FIELDS]
    assert [item['value'] for item in tiles] == ['40 000 ₽', '20 000 ₽', '20 000 ₽']
    assert 'повторно к расходам или дефициту не прибавляются' in report.render_html(built)
    if unknown_payment:
        assert reconciliation['paid_at_cut'] is None
        assert reconciliation['available_bank_limit'] is None
        assert reconciliation['calculated_additional'] is None
        assert built['funding']['draws']['total'] is None
    paths = [monitor._project_dir(PROJECT) / 'baseline/finance.xlsx',
             monitor._project_dir(PROJECT) / 'baseline' / monitor.FINANCE_META,
             rss, rss.with_suffix('.json')]
    before = {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
    admin.for_project(PROJECT, '2026-10-20')
    report.build(PROJECT, 'week', '2026-10-20')
    assert before == {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}


@pytest.mark.parametrize('width', [390, 1440])
def test_real_monitor_keeps_ahr_before_canonical_financial_return_and_clears_the_context(tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    _, view, _ = composed(tmp_path, monkeypatch, unknown_payment=True)
    with browser_page(width) as (page, responses, errors):
        page.evaluate("view=>{currentView=view;renderDash(view);selectMonitorTab('money')}", view)
        card = page.locator('#adminExpensesCard')
        expect(card).to_be_visible()
        assert card.locator('.admin-expenses > div > div').count() == 3
        assert card.locator('details .admin-expenses > div > div').count() == 0
        for _, label in admin.FIELDS:
            assert page.get_by_text(label, exact=True).count() == 1
        block = page.locator('.funding-reconciliation')
        expect(block).to_be_visible()
        expect(block).to_contain_text(view['dashboard']['funding']['source_scope_note'])
        expect(page.locator('#financeBars')).to_be_empty()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#project').fill('Another synthetic project')
        expect(card).to_be_hidden()
        assert card.inner_text() == ''
        assert page.evaluate('!currentView || (!currentView.admin_expenses && !currentView.admin_expenses_html)')
        assert not errors
