"""Source-backed AHR presentation: mapping is neither coverage nor payment proof."""
import datetime

import pytest

import developaid_management_report as report
import developaid_monitor_dashboard as dashboard
import test_the_approved_budget_says_what_it_is_made_of as fixture


def read_with_map(tmp_path, monkeypatch, destinations):
    rows = dict(fixture.ROWS)
    rows['2.4.2'] = ('Юридические услуги', 60, 10, 50)
    # Keep the parent intentionally unrelated: only leaves count.
    rows['2.4'] = ('Административные расходы', 9999, 8888, 7777)
    mapping = [row for row in fixture.CROSSWALK if not row[0].startswith('2.4.1')]
    mapping += [('2.4.1.' + str(i), 'Управление', destination)
                for i, destination in enumerate(destinations, 1)]
    mapping += [('2.4.2.1', 'Юридические услуги', '3.7')]
    monkeypatch.setattr(fixture, 'CROSSWALK', mapping)
    return fixture._read(tmp_path, fixture._finmodel(rows))


@pytest.mark.parametrize('destinations', [['2.6'], ['3.7'], ['4.1']])
def test_a_single_dictionary_chapter_is_not_monetary_evidence(tmp_path, monkeypatch, destinations):
    source = read_with_map(tmp_path, monkeypatch, destinations)
    admin = dashboard._admin_expenses(source['budget_composition'], source['chapter_flow'])
    assert admin['chapters'] == {}
    assert admin['unallocated'] == {'total': 100_000, 'paid': 30_000, 'to_pay': 70_000}
    assert admin['total'] == 100_000
    assert admin['paid'] == 30_000
    assert admin['to_pay'] == 70_000
    assert not admin['allocation_known']
    assert source['approved'] == source['budget_composition']['total']
    assert all(item['source']['sheet'] == 'cf_1_new' for item in admin['items'])
    assert all(item['source']['row'] > 6 for item in admin['items'])
    assert admin['bank_coverage'] is None
    assert admin['paid_at_cut'] is None


@pytest.mark.parametrize('destinations', [['2.6', '2.6', '3.7'], []])
def test_mixed_or_missing_crosswalk_is_not_a_monetary_split(tmp_path, monkeypatch, destinations):
    source = read_with_map(tmp_path, monkeypatch, destinations)
    admin = dashboard._admin_expenses(source['budget_composition'], source['chapter_flow'])
    # Two map rows for chapter2 cannot turn into a 2/3 money share.
    assert admin['chapters'] == {}
    assert admin['unallocated'] == {'total': 100_000, 'paid': 30_000, 'to_pay': 70_000}
    assert not admin['allocation_known']
    assert admin['bank_coverage'] is None
    assert admin['included_in_deficit'] is None
    text = ' '.join(dashboard.admin_expense_lines(admin, report._rub))
    assert 'не распределено — 100 000 ₽' in text
    assert 'не подтверждены' in text


def test_replacement_schedule_cannot_claim_administrative_coverage(tmp_path, monkeypatch):
    source = read_with_map(tmp_path, monkeypatch, ['2.6'])
    comp, flow = source['budget_composition'], source['chapter_flow']
    schedule = {'chapter': '2', 'day': '2026-10-01', 'monthly': {'2026-11-01': 600_000},
                'owed': 600_000}
    original = dashboard._own_money(comp, fixture.SMETA, fixture.PAID, ['1', '2', '3'],
                                    datetime.date(2026, 10, 31), chapter_flow=flow,
                                    schedule=schedule)
    admin = original['admin']
    assert admin['replacement_schedule_applies']
    assert admin['included_in_replacement_schedule'] is None
    assert admin['included_in_deficit'] is None
    assert admin['added_to_deficit'] == 0
    assert any('график' in reason for reason in admin['reasons'])
    assert original['need'] == pytest.approx(sum(row['amount'] for row in original['rows']))
    # Shared chapter limits never become a second admin-specific deficit.
    assert original['need'] != sum(row['amount'] for row in original['rows']) + admin['to_pay']


def test_aggregate_fact_is_never_added_to_rss_or_bdds_payments(tmp_path, monkeypatch):
    source = read_with_map(tmp_path, monkeypatch, ['2.6'])
    a = dashboard._admin_expenses(source['budget_composition'], source['chapter_flow'])
    assert a['payment_basis'] == 'financial_model_fact'
    assert a['paid'] == 30_000
    assert a['paid_at_cut'] is None
    assert not a['reconciled']
    assert any('идентификаторам' in reason for reason in a['reasons'])


def test_missing_leaf_sources_do_not_become_a_confirmed_zero():
    comp = {'sections': [{'code': '2.4', 'total': 40, 'fact': 10, 'plan': 30}]}
    admin = dashboard._admin_expenses(comp, {'2': {'sections': {'2.4': 40}}})
    assert admin['chapters'] == {}
    assert admin['unallocated'] == {'total': 40, 'paid': 10, 'to_pay': 30}
    assert not admin['allocation_known']
    assert admin['bank_coverage'] is None
    assert admin['included_in_deficit'] is None
    assert admin['paid_at_cut'] is None
    assert dashboard._admin_expenses(None, None) is None


def test_management_report_uses_the_same_admin_object(tmp_path, monkeypatch):
    source = read_with_map(tmp_path, monkeypatch, ['2.6'])
    own = dashboard._own_money(source['budget_composition'], fixture.SMETA, fixture.PAID,
                              ['1', '2', '3'], datetime.date(2026, 10, 31),
                              chapter_flow=source['chapter_flow'])
    expected = dashboard.admin_expense_lines(own['admin'], report._rub)
    actual = report._own_money_lines({'own_money': own})
    assert all(line in actual for line in expected)
    assert all(line in dashboard.own_money_lines(own, report._rub) for line in expected)


def test_missing_cached_money_is_unknown_not_zero(tmp_path, monkeypatch):
    source = read_with_map(tmp_path, monkeypatch, ['2.6'])
    comp = source['budget_composition']
    comp['admin_items'][0]['known_fields']['plan'] = False
    comp['admin_items'][0]['plan'] = 0.0
    admin = dashboard._admin_expenses(comp, source['chapter_flow'])
    assert admin['to_pay'] is None
    assert admin['unallocated']['to_pay'] is None
    assert not admin['allocation_known']
    assert 'ПЛАН —' in ' '.join(dashboard.admin_expense_lines(admin, report._rub))


@pytest.mark.parametrize('width', [390, 1440])
def test_admin_uncertainty_survives_real_html_and_pdf(tmp_path, monkeypatch, width):
    import developaid_monitor as monitor
    import pymupdf
    from browser import chromium_or_skip
    from market_search import report_pdf
    from playwright.sync_api import sync_playwright
    from test_management_report_funding import PROJECT, _project

    source = read_with_map(tmp_path, monkeypatch, ['2.6', '3.7'])
    own = dashboard._own_money(source['budget_composition'], fixture.SMETA, fixture.PAID,
                              ['1', '2', '3'], datetime.date(2026, 10, 31),
                              chapter_flow=source['chapter_flow'])
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    _project()
    funding = {'known': True, 'need_basis': 'model', 'bank_limit': own['limit'],
               'paid_actual': own['paid'], 'paid_borrowed': own['borrowed'],
               'bank_remaining': own['left'], 'reserve': 0.,
               'approved': source['budget_composition']['total'],
               'approved_remaining': source['budget_composition']['plan'],
               'deficit_ladder': {'total': own['need']}, 'additional_financing': own['need'],
               'budget_composition': source['budget_composition'], 'own_money': own}
    monkeypatch.setattr(report, '_monitor_view', lambda *a: {'dashboard': {'funding': funding}})
    built = report.build(PROJECT, 'week', '2026-10-31')
    html = report.render_html(built)
    warning = 'Постатейное покрытие АХР и состав календарной программы не подтверждены'
    assert warning in report.render_text(built)
    chrome = str(chromium_or_skip())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.set_content(report_pdf.document(html, style=report.REPORT_STYLE,
                                                title='Синтетическая сверка АХР'))
            assert warning in page.locator('body').inner_text()
            assert 'не распределено' in page.locator('body').inner_text()
            if width == 1440:
                raw = page.pdf(format='A4', print_background=True)
                doc = pymupdf.open(stream=raw, filetype='pdf')
                text = ' '.join(' '.join(p.get_text().split()) for p in doc)
                assert warning in text
                assert 'не распределено' in text
        finally:
            browser.close()


@pytest.mark.parametrize('raw,known', [(None, False), ('', False), ('—', False),
                                       ('нет данных', False), (False, False),
                                       (0, True), ('0,00', True)])
def test_parser_distinguishes_missing_money_from_an_explicit_zero(tmp_path, raw, known):
    rows = dict(fixture.ROWS)
    rows['2.4.1'] = ('Управление', 40, 20, raw)
    source = fixture._read(tmp_path, fixture._finmodel(rows))
    admin = dashboard._admin_expenses(source['budget_composition'], source['chapter_flow'])
    assert admin['items'][0]['known_fields']['plan'] is known
    assert (admin['to_pay'] is not None) is known
    if known:
        assert admin['to_pay'] == 0
