"""Synthetic monetary counterexamples; these do not approve primary sources."""
import copy
import datetime

import pytest

import developaid_funding_reconciliation as reconciliation
import developaid_monitor_dashboard as dashboard
import developaid_management_report as report
import test_the_approved_budget_says_what_it_is_made_of as fixture
import test_admin_expense_reconciliation as admin_fixture

CUT = datetime.date(2026, 10, 31)


def model_and_paid(tmp_path):
    model = fixture._read(tmp_path, fixture._finmodel())
    paid = {ch: {'total': flow['fact'], 'borrowed': 0.0}
            for ch, flow in model['chapter_flow'].items() if ch in fixture.SMETA}
    return model, paid


def schedule(model, state=None):
    result = {'chapter': '2', 'day': '2026-10-01', 'source_sha256': 'b' * 64,
              'monthly': {'2026-11-01': 600_000.0}, 'owed': 600_000.0,
              'paid_since': 0.0, 'plan_known': True}
    if state:
        item = model['budget_composition']['admin_items'][0]
        result['admin_coverage'] = {
            'basis': 'reviewed_sources', 'cut': CUT.isoformat(),
            'budget_sha256': model['budget_composition']['source_sha256'],
            'schedule_sha256': result['source_sha256'],
            'items': [{'code': item['code'], 'source_row': item['source']['row'], 'state': state, 'bank_chapter': '2'}]}
    return result


def own(model, paid, replacement=None):
    return dashboard._own_money(model['budget_composition'], fixture.SMETA, paid,
                                ['1', '2', '3'], CUT,
                                chapter_flow=model['chapter_flow'], schedule=replacement)


def test_unknown_schedule_coverage_preserves_the_exact_admin_gap(tmp_path):
    model, paid = model_and_paid(tmp_path)
    original = own(model, paid)
    assert original['reconciliation']['budget'] == pytest.approx(
        original['paid'] + original['reconciliation']['available_bank_limit']
        + original['reconciliation']['calculated_additional'])
    replaced = own(model, paid, schedule(model))
    r = replaced['reconciliation']
    assert r['matches']
    assert r['budget'] == pytest.approx(r['rhs'])
    assert r['components'][1]['amount'] == 0
    assert replaced['admin']['to_pay'] == 20_000
    assert r['components'][0]['amount'] == 40_000
    assert r['admin_schedule']['items'][0]['state'] == 'unknown'
    assert r['admin_schedule']['items'][0]['model_remaining'] == 20_000
    assert r['confirmed_additional'] is None
    assert r['primary_source_gate'] == 'BLOCKED'
    assert r['calculated_additional'] == original['reconciliation']['calculated_additional']
    assert r['calculated_additional'] is not None
    assert not r['financial_acceptance_performed']


def test_proven_exclusion_adds_the_unpaid_admin_once_to_both_readers(tmp_path, monkeypatch):
    model, paid = model_and_paid(tmp_path)
    replacement = schedule(model, 'excluded')
    result = own(model, paid, replacement)
    r = result['reconciliation']
    assert result['admin']['added_to_need'] == 20_000
    assert result['admin']['added_to_deficit'] == 20_000
    assert r['budget'] == pytest.approx(r['paid_at_cut'] + r['available_bank_limit']
                                      + r['calculated_additional'])
    assert r['components'][1]['amount'] == -20_000
    monkeypatch.setattr(dashboard, '_paid_in_chapters',
                        lambda rss, estimate, chapters, **_: paid[chapters[0]])
    rows = dashboard._section_articles(model['sections'], {'by_code': {}}, None, CUT,
                                       chapter_flow=model['chapter_flow'], schedule=replacement,
                                       composition=model['budget_composition'])
    chapter = next(x for x in result['rows'] if x['chapter'] == '2')
    assert sum(rows['2']['monthly_need'].values()) == chapter['to_pay'] == 620_000
    assert 'включён в потребность один раз' in ' '.join(
        dashboard.own_money_lines(result, report._rub))


def test_proven_inclusion_never_adds_admin_again(tmp_path):
    model, paid = model_and_paid(tmp_path)
    replacement = schedule(model, 'included')
    replacement['monthly'] = {'2026-11-01': 620_000.0}
    result = own(model, paid, replacement)
    assert result['admin']['added_to_need'] == 0
    assert result['rows'][1]['to_pay'] == 620_000
    assert result['reconciliation']['matches']
    assert result['reconciliation']['components'][1]['amount'] == -20_000


@pytest.mark.parametrize('tamper', ['budget_sha256', 'schedule_sha256', 'cut', 'source_row', 'duplicate'])
def test_coverage_must_bind_to_exact_sources_cut_and_leaf(tmp_path, tamper):
    model, paid = model_and_paid(tmp_path)
    replacement = schedule(model, 'excluded')
    proof = replacement['admin_coverage']
    if tamper in ('budget_sha256', 'schedule_sha256'):
        proof[tamper] = 'c' * 64
    elif tamper == 'cut':
        proof['cut'] = '2026-11-01'
    elif tamper == 'source_row':
        proof['items'][0]['source_row'] += 1
    else:
        proof['items'].append(dict(proof['items'][0]))
    result = own(model, paid, replacement)
    assert result['admin']['added_to_need'] == 0
    assert result['reconciliation']['admin_schedule']['state'] == 'incomplete'


def test_chapter_payments_cannot_be_assigned_to_admin_by_guess(tmp_path):
    model, paid = model_and_paid(tmp_path)
    replacement = schedule(model, 'excluded')
    replacement['paid_since'] = 10_000
    result = own(model, paid, replacement)
    assert result['admin']['added_to_need'] == 0
    assert result['reconciliation']['admin_schedule']['items'][0]['state'] == 'unknown'
    assert 'Оплаты после даты' in result['reconciliation']['admin_schedule']['items'][0]['reason']
    assert result['reconciliation']['payment_identity_verified'] is None


def test_mixed_map_is_unallocated_in_admin_and_general_funding(tmp_path, monkeypatch):
    model = admin_fixture.read_with_map(tmp_path, monkeypatch, ['2.6', '2.6', '3.7'])
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert admin['unallocated']['total'] == 100_000
    assert model['chapter_flow']['2']['sections'].get('2.4', 0.0) == 0
    assert model['chapter_flow']['']['sections']['2.4'] == 100_000
    result = own(model, fixture.PAID)
    assert result['reconciliation']['components'][0]['amount'] == 100_000
    assert result['reconciliation']['unallocated_programme']['model_plan'] == 70_000
    assert sum(result['reconciliation']['unallocated_programme']['monthly'].values()) == 70_000
    assert result['reconciliation']['unallocated_programme']['funding_coverage'] is None
    assert result['reconciliation']['matches']


@pytest.mark.parametrize('raw, expected', [(None, None), ('неизвестно', None), (0, 1_400_000.0)])
def test_unknown_money_is_not_a_zero(tmp_path, raw, expected):
    rows = dict(fixture.ROWS)
    rows['2.4.1'] = ('Управление', raw, 0, 0)
    model = fixture._read(tmp_path, fixture._finmodel(rows))
    result = own(model, fixture.PAID)['reconciliation']
    assert result['budget'] == expected
    if raw != 0:
        assert result['calculated_additional'] is None
        assert not result['matches']
    assert dashboard._fmt_money(None) == '—'
    assert dashboard._fmt_money(0) != '—'


def test_surplus_is_not_a_negative_or_invented_additional_need(tmp_path):
    model, paid = model_and_paid(tmp_path)
    high_limits = {ch: 10_000_000 for ch in fixture.SMETA}
    result = dashboard._own_money(model['budget_composition'], high_limits, paid,
                                  ['1', '2', '3'], CUT, chapter_flow=model['chapter_flow'])
    r = result['reconciliation']
    assert r['calculated_additional'] == 0
    assert r['unused_capacity'] > 0
    assert r['budget'] == pytest.approx(r['rhs'])


def test_accounting_difference_is_explained_not_plugged_into_additional(tmp_path):
    model, _ = model_and_paid(tmp_path)
    result = own(model, fixture.PAID)
    r = result['reconciliation']
    assert r['components'][2]['amount'] == 10_000
    assert r['budget'] == pytest.approx(r['rhs'])
    assert r['calculated_additional'] == max(0, r['budget'] - r['paid_at_cut'] - r['available_bank_limit'])
    assert r['calculated_additional'] != r['budget'] - r['bank_limit_total']


def test_opposite_unresolved_components_do_not_disappear_from_lines(tmp_path):
    model, paid = model_and_paid(tmp_path)
    result = own(model, paid)
    r = copy.deepcopy(result['reconciliation'])
    r['components'][1]['amount'], r['components'][2]['amount'] = 20_000, -20_000
    lines = ' '.join(reconciliation.lines(r, report._rub))
    assert 'Различие бюджета' in lines and 'Факт финансовой базы' in lines


def test_unused_other_chapter_capacity_does_not_hide_a_monthly_shortage():
    result = reconciliation.build(
        {'paid': 20., 'left': 80., 'limit': 100., 'model_over_schedule': 0., 'accounting': 0.,
         'rows': [{'chapter': '2', 'to_pay': 30., 'left': 10., 'amount': 20.,
                   'monthly_need': {'2026-11-01': 10., '2026-12-01': 20.}},
                  {'chapter': '3', 'to_pay': 40., 'left': 70., 'amount': -30.,
                   'monthly_need': {'2026-11-01': 40.}}]},
        {'total': 90.}, {'2': {'total': 40.}, '3': {'total': 50.}}, CUT.isoformat())
    assert result['calculated_additional'] == 0
    assert result['unused_capacity'] == 10
    assert result['budget'] == result['rhs'] == 90
    breakdown = result['need_breakdown']
    assert breakdown['calculated_chapter_total'] == 20
    assert all(ch['matches'] for ch in breakdown['chapters'])
    months = breakdown['chapters'][0]['months']
    assert [(m['covered'], m['uncovered']) for m in months] == [(10., 0.), (0., 20.)]


def test_work_names_and_gross_balances_are_not_a_deficit_allocation(tmp_path):
    model, paid = model_and_paid(tmp_path)
    names = ['Благоустройство', 'Отделка МОП', 'Внутренние инженерные системы', 'Фасады']
    replacement = schedule(model)
    replacement['detail_rows'] = [
        {'code': f'2.{i}', 'name': name, 'source_remaining': 100_000,
         'source': {'sheet': 'ГФ_до конца стр', 'row': i + 5},
         'monthly_plan': {'2026-11-01': 100_000}}
        for i, name in enumerate(names, 1)]
    result = own(model, paid, replacement)['reconciliation']['need_breakdown']
    assert [row['name'] for row in result['schedule_articles']] == names
    assert all(row['uncovered'] is None and row['covered'] is None
               for row in result['schedule_articles'])
    assert not result['work_allocation_known']
    assert result['coverage_columns_state'] == 'not_read_by_supported_parser'
    assert all(row['uncovered'] is None for row in result['model_articles'])


@pytest.mark.parametrize('missing', ['limit', 'payment'])
def test_missing_chapter_amount_does_not_become_a_known_zero(tmp_path, missing):
    model, paid = model_and_paid(tmp_path)
    limits = dict(fixture.SMETA)
    if missing == 'limit':
        limits['2'] = None
    else:
        paid['2']['total'] = None
    result = dashboard._own_money(model['budget_composition'], limits, paid,
                                  ['1', '2', '3'], CUT, chapter_flow=model['chapter_flow'])
    r = result['reconciliation']
    assert r['remaining_bank_limit'] is None
    assert r['calculated_additional'] is None
    assert not r['matches']


@pytest.mark.parametrize('replacement', ['missing', 'incomplete', 'unknown_admin'])
def test_approved_budget_gap_does_not_depend_on_graph_or_article_coverage(tmp_path, replacement):
    model, paid = model_and_paid(tmp_path)
    base = own(model, paid)['reconciliation']
    graph = None if replacement == 'missing' else schedule(model)
    if replacement == 'incomplete':
        graph.update(plan_known=False, monthly={})
    actual = own(model, paid, graph)['reconciliation']
    assert actual['budget'] == base['budget'] == 1_440_000
    assert actual['calculated_additional'] == base['calculated_additional']
    assert actual['matches']
    assert actual['coverage_scope'] == 'aggregate'


def test_admin_economic_tag_and_bank_classification_are_independent(tmp_path):
    model, paid = model_and_paid(tmp_path)
    base = own(model, paid)['reconciliation']
    changed = copy.deepcopy(model)
    # Same real cost and same paid/available totals; only its bank chapter
    # classification moves. No majority map allocation or new own-funded sum.
    amount = 40_000
    changed['chapter_flow']['2']['total'] -= amount
    changed['chapter_flow']['3']['total'] += amount
    actual = own(changed, paid)['reconciliation']
    assert (actual['budget'], actual['paid_at_cut'], actual['calculated_additional']) == (
        base['budget'], base['paid_at_cut'], base['calculated_additional'])
    # A genuine split of one cost across two bank chapters still has one B.
    changed['chapter_flow']['2']['total'] += amount / 2
    changed['chapter_flow']['3']['total'] -= amount / 2
    split = own(changed, paid)['reconciliation']
    assert split['budget'] == base['budget']
    assert split['calculated_additional'] == base['calculated_additional']


def test_unallocated_admin_is_in_budget_without_automatic_own_funding(tmp_path, monkeypatch):
    model = admin_fixture.read_with_map(tmp_path, monkeypatch, ['2.6', '2.6', '3.7'])
    r = own(model, fixture.PAID)['reconciliation']
    assert r['components'][0]['amount'] == 100_000
    assert r['calculated_additional'] == max(0, r['budget'] - r['paid_at_cut'] - r['available_bank_limit'])
    assert r['matches']


def test_budget_gap_is_not_a_schedule_or_accounting_plug(tmp_path):
    model, paid = model_and_paid(tmp_path)
    comp = model['budget_composition']
    comp['known_fields']['monthly'] = False
    r = own(model, paid, schedule(model))['reconciliation']
    assert r['calculated_additional'] is not None
    assert r['matches']
    assert r['need_breakdown']['calculated_chapter_total'] is None


def test_paid_above_one_limit_is_not_negative_available_cash():
    r = reconciliation.build(
        {'paid': 120., 'left': -20., 'limit': 100., 'rows': [
            {'chapter': '2', 'paid': 120., 'left': -20., 'amount': 30.,
             'to_pay': 10., 'monthly_need': {'2026-11-01': 10.}}]},
        {'total': 130.}, {'2': {'total': 130.}}, CUT.isoformat())
    assert r['available_bank_limit'] == 0
    assert r['over_limit_paid'] == 20
    assert r['calculated_additional'] == 10
    assert r['matches']


def test_bank_source_candidates_do_not_allocate_the_same_admin_money(tmp_path, monkeypatch):
    model = admin_fixture.read_with_map(tmp_path, monkeypatch, ['2.6', '2.6', '3.7'])
    assert model['funding_scope'] == {'chapters': ['1', '2', '3'], 'basis': 'full_approved_project_budget'}
    admin = model['budget_composition']['admin_items'][0]
    assert {r['rss_code'] for r in admin['bank_source_candidates']} == {'2.6', '3.7'}
    assert all(r['amount'] is None and r['money_share'] is None and r['period'] is None
               for r in admin['bank_source_candidates'])
    assert admin['total'] == 40_000
