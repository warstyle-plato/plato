"""Conditional principal must include draws on dates without this loan's payment."""
import pytest

import credit_repayment_fixture as fx
import developaid_credit_repayment as credit

M = credit.M


def drawn_between_dates(amount=1125.0):
    return fx.inputs({
        'facts.nkl2025': {'debt':5485.689,'drawn':5485.689,'accrued_interest':0.0,'accrued_fee':0.0},
        'facts.nkl2026': {'debt':0.0,'drawn':0.0,'accrued_interest':0.0,'accrued_fee':0.0},
        'plan.nkl2025': {'draws':[],'prepayments':[]},
        'plan.nkl2026': {'draws':[{'date':'2027-08-15','amount':amount}],'prepayments':[]},
        'disclosure': {'items':[]}})


def test_forecast_draw_is_in_aggregate_before_first_own_payment():
    result = credit.forecast(drawn_between_dates())
    a,b = result['loans']
    row = next(r for r in result['rows'] if r['date'] == '2027-09-30')
    assert row['date'] not in b['payments']
    assert row['debt_after'] == pytest.approx(a['payments'][row['date']]['debt_after'] + 1125*M)
    # This exact query date is neither a payment nor a sparse mark requested by callers.
    assert '2027-08-16' not in b['marks'] and '2027-08-16' not in b['payments']
    assert credit._debt_between(b,'2027-08-14') == 0.0
    assert credit._debt_between(b,'2027-08-15') == 1125*M
    assert credit._debt_between(b,'2027-08-16') == 1125*M


def test_principal_history_is_sparse_exact_and_keeps_subruble_change():
    result = credit.forecast(drawn_between_dates(0.0000001))
    b = result['loans'][1]
    history = b['principal_timeline']
    assert history[fx.AS_OF] == 0.0
    assert history['2027-08-15'] == pytest.approx(0.1,abs=1e-10)
    assert credit._debt_between(b,'2027-08-16') == history['2027-08-15']
    assert len(history) < 10
    values = list(history.values())
    assert all(before != after for before,after in zip(values,values[1:]))


def test_postday_history_matches_native_settlement_disclosure_prepay_and_final_zero():
    result = credit.forecast(fx.inputs({'plan.nkl2026': {
        'draws':[], 'prepayments':[{'date':'2027-03-02','amount':10.0}]}}))
    for loan in result['loans']:
        for day,payment in loan['payments'].items():
            assert credit._debt_between(loan,day) == payment['debt_after']
        assert list(loan['principal_timeline']) == sorted(loan['principal_timeline'])
        assert loan['principal_timeline'][max(loan['principal_timeline'])] == 0.0
        assert credit._debt_between(loan,'2030-01-01') == 0.0


def test_future_opening_facts_are_unknown_on_other_loans_earlier_dates():
    inputs = drawn_between_dates()
    inputs['datasets']['plan.nkl2025']['data']['prepayments'] = [
        {'date':'2026-11-01','amount':10*M}]
    inputs['datasets']['facts.nkl2026']['as_of'] = '2027-01-15'
    inputs['datasets']['facts.nkl2026']['data'].update(debt=200*M,drawn=200*M)
    result = credit.forecast(inputs)
    b = result['loans'][1]
    assert credit._debt_between(b,'2027-01-14') is None
    assert credit._debt_between(b,'2027-01-15') == 200*M
    earlier = next(r for r in result['rows'] if r['date'] == '2026-11-01')
    assert earlier['debt_after'] is None


def test_legacy_dto_fallback_keeps_payments_but_never_leaks_future_facts():
    loan = {'payments':{'2027-02-01':{'debt_after':10.0}},'debt_now':20.0,
            'facts_as_of':'2027-01-01'}
    assert credit._debt_between(loan,'2026-12-31') is None
    assert credit._debt_between(loan,'2027-01-01') == 20.0
    assert credit._debt_between(loan,'2027-02-02') == 10.0
    assert credit._debt_between({'payments':{},'debt_now':7.0},'2027-01-01') == 7.0


def test_missing_schedule_base_keeps_existing_unknown_between_payment_dates():
    inputs = fx.inputs()
    for name in ('facts.nkl2025','facts.nkl2026'):
        inputs['datasets'][name]['as_of'] = '2027-10-01'
    result = credit.forecast(inputs)
    a = result['loans'][0]
    assert a['payments']['2027-12-30']['debt_after'] is None
    assert a['principal_timeline']['2027-12-30'] is None
    assert credit._debt_between(a,'2027-12-31') is None


def test_timeline_zero_is_known_and_empty_history_is_unknown():
    assert credit._debt_between({'principal_timeline':{'2027-01-01':0.0}},'2027-01-02') == 0.0
    assert credit._debt_between({'principal_timeline':{},'debt_now':99},'2027-01-02') is None
