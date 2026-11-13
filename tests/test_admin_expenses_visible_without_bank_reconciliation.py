"""Known AHR stays visible without bank matching; no new cost or invented zero."""
import io

import openpyxl
import pytest

import developaid_admin_expenses as admin
import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_the_approved_budget_says_what_it_is_made_of import ROWS, _finmodel


def book(change=None):
    raw = _finmodel()
    if change is None:
        return raw
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    change(wb)
    target = io.BytesIO()
    wb.save(target)
    wb.close()
    return target.getvalue()


def test_leaf_totals_exclude_parent_and_taxes_without_any_bank_dictionary():
    raw = book(lambda wb: wb.remove(wb['статьи_БДДС']))
    got = admin.read(raw, taken_at='2026-11-01', cut='2026-11-13')
    assert (got['total'], got['fact'], got['plan']) == (40000, 20000, 20000)
    assert [r['code'] for r in got['rows']] == ['2.4.1']
    assert got['management_article'] == '2.6'
    assert got['difference'] == 0 and got['source']['unit'] == 'тыс. ₽'
    assert {'bank_limit', 'gap', 'additional_financing'}.isdisjoint(got)


@pytest.mark.parametrize('value', [None, '', 'неизвестно', True, '=1+2', 'NaN', 'inf', 1e308])
def test_missing_or_uncached_fact_never_becomes_zero(value):
    rows = {**ROWS, '2.4.1': ('Управление', 40, value, 20)}
    got = admin.read(_finmodel(rows))
    assert got['fact'] is None and got['fact_missing'] == 1
    assert got['total'] == 40000 and got['plan'] == 20000
    assert admin.tiles(got)[1]['value'] == 'нет данных'


def test_real_zero_and_known_partial_sum_are_distinct():
    rows = {**ROWS, '2.4.2': ('Администрация', 100, 0, 100)}
    got = admin.read(_finmodel(rows))
    assert got['fact'] == 20000 and got['rows'][-1]['fact'] == 0
    rows['2.4.1'] = ('Управление', 40, None, 20)
    got = admin.read(_finmodel(rows))
    assert got['fact'] is None and got['fact_known_part'] == 0
    assert 'Известная часть: 0 ₽' in admin.tiles(got)[1]['note']


def test_source_difference_is_named_and_no_total_is_repaired():
    rows = {**ROWS, '2.4.1': ('Управление', 40, 20, 25)}
    got = admin.read(_finmodel(rows))
    assert got['total'] == 40000 and got['plan'] == 25000 and got['difference'] == -5000
    assert 'ИТОГО отличается' in admin.render(got)


def test_a_parent_with_only_tax_children_does_not_count_tax_as_ahr():
    rows = {code: value for code, value in ROWS.items() if code != '2.4.1'}
    got = admin.read(_finmodel(rows))
    assert got['total'] is None and not got['rows']


def test_a_future_source_is_not_presented_as_the_historical_fact():
    got = admin.read(_finmodel(), taken_at='2026-11-01', cut='2026-10-31')
    assert got['total'] is None and 'позже' in got['reason']


def test_duplicate_codes_do_not_double_the_total():
    def duplicate(wb):
        ws = wb['cf_1_new']; r = ws.max_row + 1
        for col, value in ((3, '2.4.1'), (4, 'Дубль'), (9, 40), (10, 20), (11, 20)):
            ws.cell(r, col, value)
    got = admin.read(book(duplicate))
    assert got['total'] is None and 'повторяются' in got['reason']


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    path = monitor._project_dir('Учебный АХР') / 'baseline' / 'finance.xlsx'
    path.parent.mkdir(parents=True)
    raw = _finmodel(); path.write_bytes(raw)
    return path, raw


def test_dashboard_without_rss_or_gpr_keeps_ahr_and_source_bytes(stored, monkeypatch):
    path, raw = stored
    monkeypatch.setattr(dashboard, '_ORIGINAL_BUILD', lambda *_a, **_k: {'cut': '2026-11-13'})
    monkeypatch.setattr(dashboard.schedule_graph, 'apply', lambda _p, view: view)
    got = dashboard._build('Учебный АХР', '2026-11-13')
    assert got['admin_expenses']['total'] == 40000
    assert '40 000 ₽' in got['admin_expenses_html']
    assert path.read_bytes() == raw and 'financing' not in got


def test_report_shows_the_same_ahr_when_financial_and_schedule_blocks_are_missing(stored, monkeypatch):
    path, raw = stored
    model = admin.for_project('Учебный АХР', '2026-11-13')
    monkeypatch.setattr(report, '_monitor_view', lambda *_a: {'admin_expenses': model})
    got = report.build('Учебный АХР', 'week', '2026-11-13')
    assert got['admin_expenses'] is model
    actual = [t for t in report.tiles(got) if t['label'].startswith('АХР —')]
    assert actual == admin.tiles(model)
    output = report.render_html(got)
    assert admin.render(model, show_tiles=False) in output
    assert '40 000 ₽' in output and 'Повторно' not in output
    assert 'АХР — всего: 40 000 ₽' in report.render_text(got)
    assert path.read_bytes() == raw


@pytest.mark.parametrize('width', [390, 1440])
def test_real_monitor_shows_source_and_ahr_without_financial_readiness_and_clears_old_project(width, tmp_path):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    model = admin.read(_finmodel(), filename='<img src=x onerror="window.unsafeAhr=true">')
    view = {'admin_expenses_html': admin.render(model), 'admin_expenses': model,
            'dashboard': {'funding': {'known': False, 'reason': 'РСС не загружена'}}}
    with browser_page(width) as (page, responses, errors):
        calls = []
        page.on('request', lambda req: calls.append(req.url) if '/agent/' in req.url or '/monitor/ask' in req.url else None)
        page.evaluate("v=>{currentView=v;renderDash(v);selectMonitorTab('money')}", view)
        card = page.locator('#adminExpensesCard')
        expect(card).to_be_visible()
        expect(card).to_contain_text('40 000 ₽')
        expect(card).to_contain_text('20 000 ₽')
        expect(card).to_contain_text('повторно к расходам или дефициту не прибавляются')
        expect(page.locator('#kpis')).to_contain_text('финмодель прочитана')
        assert card.locator('img').count() == 0 and page.evaluate('window.unsafeAhr') is None
        card.locator('summary').click()
        expect(card.locator('tbody tr')).to_have_count(1)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path / f'ahr-{width}.png'), full_page=True)
        page.locator('#project').fill('Другой проект')
        expect(card).to_be_hidden()
        assert card.inner_text() == '' and not errors and not calls
