"""Calculated funding remains visible; AHR cash is not added twice."""
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
def test_existing_ahr_contribution_is_identified_without_attesting_remaining_cash(
        tmp_path, schedule, unmapped, paid_since, expected):
    model = _read(tmp_path, _finmodel())
    flows = copy.deepcopy(model['chapter_flow'])
    # This positive split control supplies an explicit monetary allocation.
    # The article map alone leaves these AHR amounts outside the bank chapters.
    unallocated = flows.pop('')
    assert unallocated['sections'] == {'2.4': 40_000}
    admin = {key: copy.deepcopy(unallocated[key]) for key in ('total', 'fact', 'plan', 'monthly')}
    for key in ('total', 'fact', 'plan'):
        flows['2'][key] += admin[key]
    for month, value in admin['monthly'].items():
        flows['2']['monthly'][month] = flows['2']['monthly'].get(month, 0) + value
    for flow in flows.values():
        flow['admin_expenses'] = {'total': 0, 'fact': 0, 'plan': 0, 'monthly': {}}
    flows['2']['sections']['2.4'] = admin['total']
    flows['2']['admin_expenses'] = admin
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
    result = cash.funding_summary(own['need_without_admin_expenses'], _partial_cash(), cash.money)
    assert result['amount'] == pytest.approx(max(0, own['need_without_admin_expenses']))
    assert result['scope'] == 'bank_only'
    assert 'отдельно от остатка АХР' in result['note']
    assert result['amount'] != pytest.approx(max(0, own['need_without_admin_expenses'])
                                               + _partial_cash()['balance_after_observed_payments'])
    assert own['matches']


def test_unqualified_article_map_does_not_supply_a_known_ahr_split(tmp_path):
    model = _read(tmp_path, _finmodel())
    flows = model['chapter_flow']
    assert flows['']['sections'] == {'2.4': 40_000}
    assert 'admin_expenses' not in flows['']
    own = dashboard._own_money(
        model['budget_composition'], SMETA, PAID, ['1', '2', '3'], dt.date(2026, 10, 20),
        paid_since={'2': 0}, chapter_flow=flows)
    assert 'admin_expenses_included' not in own
    assert 'need_without_admin_expenses' not in own
    assert own['admin']['bank_coverage'] is None
    assert own['reconciliation']['confirmed_additional'] is None
    assert cash.funding_base(own, _partial_cash()) is None


def _partial_cash():
    from test_admin_expenses_cash import calc, payment, doc
    budget = cash.fm_budget(_finmodel())['budget']
    return calc([payment(budget / 2)], {'2026-09-01': doc(None)}, budget=budget)


@pytest.mark.parametrize('balance_state', ['positive', 'zero', 'negative', 'unknown'])
@pytest.mark.parametrize('known_observed_period', [False, True])
def test_observed_balance_never_changes_the_separately_computed_bank_need(balance_state, known_observed_period):
    model = _partial_cash()
    balance = model['balance_after_observed_payments']
    model['balance_after_observed_payments'] = {
        'positive': balance, 'zero': balance - balance,
        'negative': -balance, 'unknown': None}[balance_state]
    model['coverage']['known_for_observed_period'] = known_observed_period
    model['state'] = 'ok' if known_observed_period else 'partial'
    before = copy.deepcopy(model)
    for base in (None, balance - balance, balance):
        result = cash.funding_summary(base, model, cash.money)
        assert result['amount'] == (None if base is None else max(0, base))
        assert result['scope'] == ('unconfirmed_total' if base is None else 'bank_only')
        assert model == before
        assert ('Не определена базовая потребность' if base is None else 'отдельно от остатка АХР') in result['note']
        assert 'нужно на АХР' not in result['note']
        if balance_state != 'unknown':
            assert cash.money(model['balance_after_observed_payments']) in result['note']


def test_report_has_one_calculated_tile_and_keeps_partial_ahr_in_details(tmp_path, monkeypatch):
    from test_funding_source_dates import source_case
    built, _ = source_case(tmp_path, monkeypatch)
    model = _partial_cash()
    built['admin_expenses_cash'] = model
    tiles = report.tiles(built)
    summary, = [tile for tile in tiles if tile.get('group') == 'additional_funding']
    assert summary['label'] == 'Расчётная потребность в допфинансировании'
    calculation = built['funding']['limit']['reconciliation']['calculation']
    assert calculation['calculated_additional'] == 0
    assert summary['value'] == '0 ₽' and summary['tone'] == 'good'
    assert 'Утверждённый бюджет уже включает АХР' in summary['note']
    assert 'финансовая сверка' not in summary['note'].lower()
    assert not any(tile.get('group') == 'admin_expenses_cash' for tile in tiles)
    assert summary['note'] in report.render_text(built)
    assert summary['note'] in report.render_html(built)
    finding, = [f for f in report.findings(built) if f['topic'] == 'Финансирование']
    assert finding['tone'] == '' and 'нужно на АХР' not in finding['text']
    assert 'расчётная потребность в допфинансировании 0 ₽' in finding['text'].lower()


def test_no_observed_cash_keeps_only_the_separately_named_bank_component():
    model = {key: None for key, _ in cash.FIELDS}
    model.update(state='partial', remaining_need=None)
    base = _partial_cash()['budget']
    result = cash.funding_summary(base, model, cash.money)
    assert result['scope'] == 'bank_only' and result['amount'] == base
    html = cash.render_funding(result, cash.render(model))
    assert 'Потребность по смете банка' in html
    assert 'Потребность в допфинансировании</small>' not in html
    assert model['remaining_need'] is None
    assert 'Потребность по смете банка показана отдельно от остатка АХР' in result['note']


def test_old_own_money_without_ahr_split_does_not_claim_a_combined_total():
    model = _partial_cash()
    base = cash.funding_base({'need': model['budget']}, model)
    result = cash.funding_summary(base, model, cash.money)
    assert base is None and result['amount'] is None
    assert 'Не определена базовая потребность' in result['note']


def test_monitor_build_uses_the_same_calculated_need(tmp_path, monkeypatch):
    from test_funding_source_dates import source_case
    built, view = source_case(tmp_path, monkeypatch)
    limit = built['funding']['limit']
    model = _partial_cash()
    monkeypatch.setattr(dashboard, '_ORIGINAL_BUILD', lambda *a, **kw: view)
    monkeypatch.setattr(dashboard.schedule_graph, 'apply', lambda p, v: v)
    monkeypatch.setattr(dashboard, '_dashboard', lambda *a: {'funding': limit})
    monkeypatch.setattr(cash, 'for_project', lambda *a: model)
    result = dashboard._build(built['project'], built['end'])
    assert '>0,00 ₽</div>' in result['admin_expenses_html']
    assert result['admin_expenses_html'].count('class="additional-funding"') == 1
    assert 'Утверждённый бюджет уже включает АХР' in result['admin_expenses_html']
    assert 'нужно на АХР' not in result['admin_expenses_html']


@pytest.mark.parametrize('with_own', [True, False])
def test_partial_ahr_does_not_hide_a_known_zero_calculated_need(with_own, tmp_path, monkeypatch):
    from test_funding_source_dates import source_case
    built, view = source_case(tmp_path, monkeypatch)
    limit = built['funding']['limit']
    model = _partial_cash()
    empty = model['budget'] - model['budget']
    if with_own:
        limit['own_money'].update(need=empty, need_without_admin_expenses=empty)
    else:
        limit.pop('own_money')
    limit.update(deficit_ladder={'total': empty})
    built['admin_expenses_cash'] = model
    tile, = [t for t in report.tiles(built) if t.get('group') == 'additional_funding']
    assert tile['value'] == '0 ₽' and tile['tone'] == 'good'
    assert 'Утверждённый бюджет уже включает АХР' in tile['note']
    finding, = [f for f in report.findings(built) if f['topic'] == 'Финансирование']
    assert 'расчётная потребность в допфинансировании 0 ₽' in finding['text'].lower()
    assert finding['tone'] == ''
    assert cash.funding_base_for_limit(limit, model) == (empty if with_own else None)
    monkeypatch.setattr(dashboard, '_ORIGINAL_BUILD', lambda *a, **kw: view)
    monkeypatch.setattr(dashboard.schedule_graph, 'apply', lambda p, v: v)
    monkeypatch.setattr(dashboard, '_dashboard', lambda *a: {'funding': limit})
    monkeypatch.setattr(cash, 'for_project', lambda *a: model)
    result = dashboard._build(built['project'], built['end'])
    assert '>0,00 ₽</div>' in result['admin_expenses_html']
    assert 'нужно на АХР' not in result['admin_expenses_html']


@pytest.mark.parametrize('width', [390, 1440])
def test_rendered_report_has_one_calculated_total_and_no_duplicate_ahr_tiles(width, tmp_path, monkeypatch):
    import re
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    from developaid_report_page import REPORT_PAGE
    from test_funding_source_dates import source_case
    built, _ = source_case(tmp_path, monkeypatch)
    built['admin_expenses_cash'] = _partial_cash()
    styles = re.search(r'<style>(.*?)</style>', REPORT_PAGE, re.S)[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()),
                                     args=['--no-sandbox'], headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 950})
        page.set_content('<meta charset="utf-8">' + styles + '<main id="reportBox">'
                         + report._tiles_html(report.tiles(built)) + '</main>')
        tile = page.locator('.tile').filter(has_text='Потребность в допфинансировании')
        expect(tile).to_have_count(1)
        expect(tile.locator('.v')).to_have_text('0 ₽')
        expect(tile).to_contain_text('Утверждённый бюджет уже включает АХР')
        expect(tile).not_to_contain_text('финансовая сверка')
        for _, label in cash.FIELDS:
            expect(page.locator('.tile .k').filter(has_text=label)).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert tile.evaluate('(e)=>e.scrollWidth <= e.clientWidth')
        page.screenshot(path=str(tmp_path / f'single-funding-{width}.png'), full_page=True)
        browser.close()
