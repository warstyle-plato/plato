"""Legacy numeric fallback preserves its scope and explicit missing inputs."""
import copy

import pytest

import developaid_monitor_dashboard as dashboard


@pytest.mark.parametrize('flag', ['payments_known', 'limits_known'])
@pytest.mark.parametrize('need', [0, 120000])
@pytest.mark.parametrize('cash', [{}, {'budget': 40000, 'balance_after_observed_payments': 20000}])
def test_explicit_missing_legacy_input_cannot_become_zero_through_any_fallback(flag, need, cash):
    funding = {'known': True, 'own_money': {
        'need': need, 'need_without_admin_expenses': need, flag: False}}
    before = copy.deepcopy(funding)
    result = dashboard.funding_cash_summary(funding, cash, str)
    assert result['amount'] is None
    assert ('оплат' if flag == 'payments_known' else 'лимитов') in result['note']
    assert 'сверка' not in result['note']
    assert funding == before


@pytest.mark.parametrize('flags', [{}, {'payments_known': True, 'limits_known': True}])
@pytest.mark.parametrize('need', [0, 120000])
def test_absent_legacy_flags_or_explicit_known_zero_preserve_a_complete_result(flags, need):
    result = dashboard.funding_cash_summary({'known': True, 'own_money': {
        'need': need, **flags}}, {}, str)
    assert result['amount'] == need
    assert result['scope'] == 'existing_total'


def test_canonical_observed_calculation_dominates_a_legacy_falsezero():
    funding = {'known': True, 'own_money': {'need': 0, 'payments_known': False},
               'reconciliation': {'primary_source_gate': 'BLOCKED',
                   'calculation': {'calculated_additional': 500, 'partial': True}}}
    result = dashboard.funding_cash_summary(funding, {}, str)
    assert result['amount'] == 500 and result['scope'] == 'calculated_total'
    assert result['partial'] is True
    assert 'Утверждённый бюджет уже включает АХР' in result['note']


@pytest.mark.parametrize('canonical', [True, False])
def test_compact_date_cannot_replace_an_explicitly_unknown_canonical_date(canonical):
    funding = {'baseline_file': {'taken_at': '2026-10-01'}}
    if canonical:
        funding['source_dates'] = {'budget': {'data_date': None, 'file': 'unknown-date.xlsx'}}
    short = dashboard.funding_source_tile_notes(funding)['budget']
    full = dashboard.funding_source_notes(funding)['budget']
    if canonical:
        assert short == 'ФМ: дата не указана.' and 'дата данных не указана' in full
        assert '01.10.2026' not in short + full
    else:
        assert short == 'ФМ: 01.10.2026.' and '01.10.2026' in full


def test_bank_only_finding_retains_chapter_amounts_months_and_excluded_ahr(monkeypatch):
    import developaid_management_report as report
    from test_management_report_funding import PROJECT, _project
    from test_the_extra_financing_is_split_by_chapter import _limit

    _project()
    funding = _limit()
    monkeypatch.setattr(report, '_monitor_view', lambda *_: {'dashboard': {'funding': funding}})
    built = report.build(PROJECT, 'week', '2026-10-18')
    built['funding']['limit']['own_money'] = {
        'need': 410000000, 'need_without_admin_expenses': 370000000}
    built['admin_expenses_cash'] = {'budget': 40000000,
                                    'balance_after_observed_payments': 20000000}
    summary = dashboard.funding_cash_summary(built['funding']['limit'],
                                             built['admin_expenses_cash'], report._rub)
    assert summary['scope'] == 'bank_only' and summary['amount'] == 370000000
    finding, = [item for item in report.findings(built) if item['topic'] == 'Финансирование']
    text = finding['text']
    assert 'Потребность по банковской смете 370,0 млн ₽ с января 2027' in text
    assert 'на стройку по главе 2 — 300,0 млн ₽ с января 2027' in text
    assert 'на коммерцию по главе 3 — 70,0 млн ₽ с марта 2027' in text
    assert 'АХР: остаток после учтённых оплат — 20,0 млн ₽' in text
    assert 'отдельно от остатка АХР' in text
    assert '390,0 млн ₽' not in text  # The observed AHR balance is not added to bank need.
