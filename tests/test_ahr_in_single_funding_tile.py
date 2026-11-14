"""AHR is an unpaid component of one funding need, counted exactly once."""
import copy
import datetime as dt

import pytest

import developaid_admin_expenses_cash as cash
import developaid_management_report as report
import developaid_monitor_dashboard as dashboard
from test_the_approved_budget_says_what_it_is_made_of import _read, _finmodel, SMETA, PAID


@pytest.mark.parametrize('schedule,unmapped,paid_since,expected', [
    (False, False, 0, 20_000),
    (True, False, 0, 0),
    (False, True, 0, 40_000),
    (False, False, 610_000, 10_000),
    (False, False, 650_000, 0),
])
def test_existing_ahr_contribution_is_removed_before_cash_is_added(
        tmp_path, schedule, unmapped, paid_since, expected):
    model = _read(tmp_path, _finmodel())
    flows = copy.deepcopy(model['chapter_flow'])
    if unmapped:
        admin = flows['2']['admin_expenses']
        flows[''] = {**admin, 'sections': {'2.4': admin['total']}, 'admin_expenses': admin}
        flows['2'] = {**flows['2'],
            **{key: flows['2'][key] - admin[key] for key in ('total', 'fact', 'plan')},
            'monthly': {month: amount - admin['monthly'].get(month, 0)
                        for month, amount in flows['2']['monthly'].items()},
            'sections': {'2.2': 1_000_000},
            'admin_expenses': {'total': 0, 'fact': 0, 'plan': 0, 'monthly': {}}}
    own = dashboard._own_money(
        model['budget_composition'], SMETA, PAID, ['1', '2', '3'], dt.date(2026, 10, 20),
        paid_since={'2': paid_since}, chapter_flow=flows,
        schedule={'chapter': '2', 'monthly': {'2026-11-01': 600_000}} if schedule else None)
    assert own['admin_expenses_included'] == pytest.approx(expected)
    assert own['need_without_admin_expenses'] == pytest.approx(own['need'] - expected)
    result = cash.funding_summary(own['need_without_admin_expenses'],
                                  {'balance_after_observed_payments': 25_000}, cash.money)
    assert result['amount'] == pytest.approx(max(0, own['need'] - expected) + 25_000)
    assert own['matches']


@pytest.mark.parametrize('base,balance,amount', [
    (1_800_000_000, 200_000_000, 2_000_000_000),
    (100, 0, 100), (100, -10, 100), (None, 10, None), (100, None, 100),
    (-100, None, 0),
])
def test_remaining_cash_and_missing_or_overspent_ahr(base, balance, amount):
    model = {'budget': 350_000_000, 'paid_observed_net': 150_000_000,
             'balance_after_observed_payments': balance, 'remaining_need': None}
    before = copy.deepcopy(model)
    result = cash.funding_summary(base, model, cash.money)
    assert result['amount'] == amount and model == before
    if balance is None:
        assert 'пока не рассчитан' in result['note']
    else:
        assert 'полнота' in result['note']


def test_report_has_one_combined_tile_with_the_same_total_in_text(tmp_path, monkeypatch):
    from test_funding_source_dates import source_case
    built, _ = source_case(tmp_path, monkeypatch)
    own = built['funding']['limit']['own_money']
    built['admin_expenses_cash'] = {'balance_after_observed_payments': 200_000_000}
    tiles = report.tiles(built)
    summary, = [tile for tile in tiles if tile.get('group') == 'additional_funding']
    expected = max(0, own['need_without_admin_expenses']) + 200_000_000
    assert summary['value'] == report._rub(expected)
    assert f'ещё {report._rub(200_000_000)} нужно на АХР' in summary['note']
    assert not any(tile.get('group') == 'admin_expenses_cash' for tile in tiles)
    assert summary['value'] in report.render_text(built)
    assert summary['note'] in report.render_html(built)


def test_old_own_money_without_ahr_split_does_not_claim_a_combined_total():
    model = {'balance_after_observed_payments': 25}
    base = cash.funding_base({'need': 100}, model)
    result = cash.funding_summary(base, model, cash.money)
    assert result['amount'] is None
    assert 'потребность без АХР пока не рассчитана' in result['note']


def test_monitor_build_uses_the_same_combined_need(tmp_path, monkeypatch):
    from test_funding_source_dates import source_case
    built, view = source_case(tmp_path, monkeypatch)
    limit = built['funding']['limit']
    model = {'balance_after_observed_payments': 200_000_000}
    monkeypatch.setattr(dashboard, '_ORIGINAL_BUILD', lambda *a, **kw: view)
    monkeypatch.setattr(dashboard.schedule_graph, 'apply', lambda p, v: v)
    monkeypatch.setattr(dashboard, '_dashboard', lambda *a: {'funding': limit})
    monkeypatch.setattr(cash, 'for_project', lambda *a: model)
    result = dashboard._build(built['project'], built['end'])
    amount = max(0, limit['own_money']['need_without_admin_expenses']) + 200_000_000
    assert cash.money(amount, compact=True) in result['admin_expenses_html']
    assert result['admin_expenses_html'].count('class="additional-funding"') == 1
    assert 'В том числе ещё' in result['admin_expenses_html']


@pytest.mark.parametrize('with_own', [True, False])
def test_ahr_only_shortage_is_bad_and_legacy_monitor_matches_report(with_own, tmp_path, monkeypatch):
    from test_funding_source_dates import source_case
    built, view = source_case(tmp_path, monkeypatch)
    limit = built['funding']['limit']
    if with_own:
        limit['own_money'].update(need=0, need_without_admin_expenses=0)
    else:
        limit.pop('own_money')
    # These are different contours: RSS has a shortage, the approved budget does not.
    limit.update(approved=1_000, additional_financing=50, deficit_ladder={'total': 0})
    model = {'balance_after_observed_payments': 100}
    built['admin_expenses_cash'] = model
    tile, = [t for t in report.tiles(built) if t.get('group') == 'additional_funding']
    assert tile['value'] == report._rub(100) and tile['tone'] == 'bad'
    finding, = [f for f in report.findings(built) if f['topic'] == 'Финансирование']
    assert f'потребность в допфинансировании {report._rub(100)}'.casefold() in finding['text'].casefold()
    assert finding['tone'] == 'bad'
    monkeypatch.setattr(dashboard, '_ORIGINAL_BUILD', lambda *a, **kw: view)
    monkeypatch.setattr(dashboard.schedule_graph, 'apply', lambda p, v: v)
    monkeypatch.setattr(dashboard, '_dashboard', lambda *a: {'funding': limit})
    monkeypatch.setattr(cash, 'for_project', lambda *a: model)
    result = dashboard._build(built['project'], built['end'])
    assert '100,00 ₽</div>' in result['admin_expenses_html']
    assert '150,00 ₽</div>' not in result['admin_expenses_html']


@pytest.mark.parametrize('width', [390, 1440])
def test_rendered_report_has_one_total_and_no_separate_ahr_tiles(width, tmp_path, monkeypatch):
    import re
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    from developaid_report_page import REPORT_PAGE
    from test_funding_source_dates import source_case
    built, _ = source_case(tmp_path, monkeypatch)
    built['admin_expenses_cash'] = {'balance_after_observed_payments': 200_000_000}
    styles = re.search(r'<style>(.*?)</style>', REPORT_PAGE, re.S)[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()),
                                     args=['--no-sandbox'], headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 950})
        page.set_content('<meta charset="utf-8">' + styles + '<main id="reportBox">'
                         + report._tiles_html(report.tiles(built)) + '</main>')
        tile = page.locator('.tile').filter(has_text='Нужно своих денег сверх сметы банка')
        expect(tile).to_have_count(1)
        expect(tile).to_contain_text('В том числе ещё 200,0 млн ₽ нужно на АХР')
        for _, label in cash.FIELDS:
            expect(page.locator('.tile .k').filter(has_text=label)).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert tile.evaluate('(e)=>e.scrollWidth <= e.clientWidth')
        page.screenshot(path=str(tmp_path / f'single-funding-{width}.png'), full_page=True)
        browser.close()
