"""Caption arithmetic uses the same approved budget, RSS payments and limits."""
import copy

import pytest

import developaid_funding_reconciliation as reconciliation
import developaid_management_report as report
import developaid_monitor_dashboard as dashboard


def funding():
    r = {'bank_chapters': ['1', '2', '3'], 'cut': '2026-11-20',
         'budget': 1000, 'paid_at_cut': 200, 'bank_limit_total': 600,
         'available_bank_limit': 400, 'calculated_additional': 400,
         'calculation': {'budget': 1000, 'paid_at_cut': 200, 'bank_limit_total': 600,
                         'available_bank_limit': 400, 'calculated_additional': 400, 'partial': False},
         'observation_scope': 'raw_saved_sources', 'reasons': [],
         'components': [{'kind': 'unallocated_budget', 'amount': 50},
                        {'kind': 'outside_bank_scope', 'amount': 0}],
         'admin_expenses': {'rows': [{'label': 'Всего АХР', 'total': 90, 'model_plan': 60}]}}
    return {'known': True, 'reconciliation': r,
            'limit_by_chapter': {'1': 100, '2': 300, '3': 200},
            'approved_by_chapter': {'1': 100, '2': 600, '3': 250},
            'own_money': {'reconciliation': r, 'payment_observation': {'by_chapter': {
                '1': {'total': 50, 'complete': True}, '2': {'total': 100, 'complete': True},
                '3': {'total': 50, 'complete': True}}},
                'rows': [{'chapter': '2', 'budget': 9999, 'amount': 9999}]}}


def test_same_basis_bridge_keeps_unallocated_budget_and_ahr_separate():
    value = funding()
    before = copy.deepcopy(value)
    d = reconciliation.chapter_disclosure(value)
    assert [r['amount'] for r in d['bank_limits']] == [100, 300, 200]
    assert [r['amount'] for r in d['available_limits']] == [50, 200, 150]
    b = d['need_bridge']
    assert [r['amount'] for r in b['chapters']] == [0, 300, 50]
    assert b['unallocated_budget'] == 50
    assert sum(r['amount'] for r in b['chapters']) + b['unallocated_budget'] == 400
    summary = dashboard.funding_cash_summary(value, {'remaining_need': 9999}, report._rub)
    assert summary['amount'] == 400
    assert 'глава 2 — 300 ₽' in summary['note'] and 'без денежной главы — 50 ₽' in summary['note']
    assert 'Их бюджет — 90 ₽; план ФМ — 60 ₽' in summary['note']
    assert '9999' not in summary['note']
    assert value == before


def test_signed_chapter_balances_are_not_clipped_or_called_a_work_shortfall():
    value = funding()
    value['approved_by_chapter'].update({'1': 0, '3': 350})
    notes = reconciliation.chapter_disclosure_notes(value, report._rub)
    assert 'глава 1 — −100 ₽' in notes['need_bridge']
    assert reconciliation.chapter_disclosure(value)['need_bridge']['chapters'][0]['amount'] == -100
    assert 'подтвержд' not in notes['need_bridge'] and 'АХР' not in notes['need_bridge']


def test_global_zero_floor_is_explicit_instead_of_adding_positive_chapter_needs():
    value = funding()
    value['approved_by_chapter'].update({'1': 0, '2': 200, '3': 150})
    value['reconciliation']['calculation'].update(budget=400, calculated_additional=0)
    value['reconciliation'].update(budget=400, calculated_additional=0)
    result = reconciliation.chapter_disclosure(value)['need_bridge']
    assert result['zero_floor'] == 200
    assert 'Итог ограничен нулём' in reconciliation.chapter_disclosure_notes(value, report._rub)['need_bridge']
    assert dashboard.funding_cash_summary(value, {}, report._rub)['amount'] == 0


@pytest.mark.parametrize('bad', [None, True, float('nan'), float('inf')])
def test_unread_chapter_amounts_never_become_zero_or_a_residual_plug(bad):
    value = funding()
    value['approved_by_chapter']['2'] = bad
    result = reconciliation.chapter_disclosure(value)
    assert 'bank_limits' in result and 'available_limits' in result and 'need_bridge' not in result


@pytest.mark.parametrize('change', ['budget', 'paid', 'limit', 'available', 'unallocated', 'chapter_set'])
def test_mismatched_totals_reject_the_split_without_hiding_the_headline(change):
    value = funding()
    if change == 'unallocated':
        value['reconciliation']['components'][0]['amount'] = 49
    elif change == 'chapter_set':
        value['approved_by_chapter']['4'] = 0
    else:
        key = {'budget': 'budget', 'paid': 'paid_at_cut', 'limit': 'bank_limit_total',
               'available': 'available_bank_limit'}[change]
        value['reconciliation']['calculation'][key] += 1
    assert 'need_bridge' not in reconciliation.chapter_disclosure(value)
    assert dashboard.funding_cash_summary(value, {}, report._rub)['amount'] == 400


def test_incomplete_chapter_map_does_not_claim_to_explain_the_whole_limit():
    value = funding()
    value['limit_by_chapter'].pop('1')
    assert reconciliation.chapter_disclosure(value) == {}


@pytest.mark.parametrize('key', ['bank_limit_total', 'available_bank_limit', 'budget', 'paid_at_cut'])
def test_stale_direct_value_cannot_receive_a_split_of_another_visible_amount(key):
    value = funding()
    value['reconciliation'][key] += 1
    assert 'need_bridge' not in reconciliation.chapter_disclosure(value)


@pytest.mark.parametrize('key', ['available_bank_limit', 'paid_at_cut'])
def test_stale_saved_display_rows_cannot_receive_a_different_split(key):
    value = funding()
    value['reconciliation']['display_rows'] = [
        {'key': 'paid_at_cut', 'value': 200}, {'key': 'available_bank_limit', 'value': 400}]
    next(row for row in value['reconciliation']['display_rows'] if row['key'] == key)['value'] += 1
    assert 'need_bridge' not in reconciliation.chapter_disclosure(value)


def test_known_ahr_plan_is_kept_when_its_total_is_unknown():
    value = funding()
    value['reconciliation']['admin_expenses']['rows'][0]['total'] = None
    note = reconciliation.chapter_disclosure_notes(value, report._rub)['admin_budget']
    assert 'План ФМ по АХР — 60 ₽' in note and '0 ₽' not in note.replace('60 ₽', '')


def test_partial_payments_keep_the_same_qualifier_and_do_not_need_financial_acceptance():
    value = funding()
    value['reconciliation']['calculation']['partial'] = True
    value['reconciliation']['financial_acceptance_performed'] = False
    value['own_money']['payment_observation']['by_chapter']['2']['complete'] = False
    note = dashboard.funding_cash_summary(value, {}, report._rub)['note']
    assert 'Состав расчёта по главам РСС' in note and 'Расчёт по учтённым оплатам' in note
    assert dashboard.funding_cash_summary(value, {}, report._rub)['amount'] == 400
