"""Досрочное в день взноса: зачёт ближайшего ещё номинального платежа."""
from __future__ import annotations

import copy
import datetime

import pytest

import credit_repayment_fixture as fx
import developaid_credit_repayment as credit

M = credit.M
A_BASE = 5485.689 * M
A_FIRST = A_BASE * .61


def _inputs(*, disclosure=None, prepay=None, historical=None):
    changes = {
        "facts.nkl2025": {"debt": 5485.689, "drawn": 5485.689,
                          "accrued_interest": 0, "accrued_fee": 0},
        "facts.nkl2026": {"debt": 1125, "drawn": 1125,
                          "accrued_interest": 0, "accrued_fee": 0},
        "plan.nkl2025": {"draws": [], "prepayments": prepay or []},
        "plan.nkl2026": {"draws": [], "prepayments": []},
        "deferred.nkl2025": {"deferred": 0, "interest_on_deferred": 0},
        "deferred.nkl2026": {"deferred": 0, "interest_on_deferred": 0},
        "terms.nkl2025": {"rate": {"value": "model", "source": "нулевая тестовая ставка"}},
        "terms.nkl2026": {"rate": {"value": "model", "source": "нулевая тестовая ставка"}},
        "key_rate": {"path": [{"from": "2026-01-01", "rate": 0}]},
        "escrow": {"balance": 10000},
        "contracts": {"payments": []}, "sales": {"payments": []},
        "refunds": {"payments": []},
        "free_cash": {"items": []}, "extra": {"items": []},
        "disclosure": {"items": disclosure or []}}
    if historical:
        changes.update(historical)
    return fx.inputs(changes)


@pytest.mark.parametrize("order,amount,today,future,left", [
    ("nearest", 30, 30, 40, 0),
    ("nearest", 80, 0, 20, 0),
    ("from_last", 30, 60, 10, 0),
    ("from_last", 80, 20, 0, 0),
    ("pro_rata", 30, 42, 28, 0),
    ("pro_rata", 120, 0, 0, 20),
])
def test_current_unsettled_installment_is_explicit(order, amount, today, future, left):
    schedule = [{"date": "2027-09-29", "amount": 10},
                {"date": "2027-09-30", "amount": 60},
                {"date": "2027-12-30", "amount": 40}]
    day = datetime.date(2027, 9, 30)
    remaining = credit._reduce(schedule, amount, day, order, include_current=True)
    assert [i["amount"] for i in schedule] == pytest.approx([10, today, future])
    assert remaining == pytest.approx(left)
    # Уже исполненный/отсечённый взнос нельзя снова зачитывать.
    closed = [{"date": "2027-09-30", "amount": 60},
              {"date": "2027-12-30", "amount": 40}]
    credit._reduce(closed, 30, day, order, include_current=False)
    assert [i["amount"] for i in closed] == pytest.approx([60, 10])


@pytest.mark.parametrize("amount", [1000, A_FIRST / M, 4000])
def test_disclosure_below_equal_above_the_same_day_61_percent_counts_once(amount):
    result = credit.forecast(_inputs(disclosure=[{
        "date": "2027-09-30", "amount": amount, "confirmed": True, "final": False}]))
    loan = result["loans"][0]
    payment = loan["payments"]["2027-09-30"]
    assert payment["principal"] == pytest.approx(max(A_FIRST, amount * M))
    assert payment["debt_after"] == pytest.approx(A_BASE - max(A_FIRST, amount * M))
    assert sum(p["principal"] for p in loan["payments"].values()) == pytest.approx(A_BASE)
    assert sum(p["from_disclosure"] for p in loan["payments"].values()) == pytest.approx(amount * M)
    assert sum(row["disclosed_used"] for row in result["rows"]) == pytest.approx(amount * M)
    for row in result["rows"]:
        assert row["disclosed_used"] + row["other_used"] + row["deficit"] == pytest.approx(row["total"])
    # Только доступное раскрытие покрывает платёж; остальной взнос не объявлен оплаченным.
    row = next(r for r in result["rows"] if r["date"] == "2027-09-30")
    assert row["deficit"] == pytest.approx(max(0, A_FIRST - amount * M))


@pytest.mark.parametrize("day", ["2027-09-29", "2027-09-30", "2027-10-01", "2029-03-30"])
def test_own_cash_prepay_before_on_after_installment_and_at_maturity(day):
    result = credit.forecast(_inputs(prepay=[{"date": day, "amount": 100}]))
    loan = result["loans"][0]
    paid = loan["payments"]
    assert sum(p["principal"] for p in paid.values()) == pytest.approx(A_BASE)
    if day == "2027-09-29":
        assert paid["2027-09-30"]["principal"] == pytest.approx(A_FIRST - 100 * M)
    elif day == "2027-09-30":
        assert paid[day]["principal"] == pytest.approx(A_FIRST)
    elif day == "2027-10-01":
        assert paid["2027-09-30"]["principal"] == pytest.approx(A_FIRST)
        assert paid["2027-12-30"]["principal"] == pytest.approx(.07 * A_BASE - 100 * M)
    else:
        assert paid[day]["principal"] == pytest.approx(.02 * A_BASE)
    assert list(paid.values())[-1]["debt_after"] == pytest.approx(0)


def test_historical_same_day_prepay_reconstructs_nominal_current_before_cutoff():
    principal_from_disclosure = 3000.0  # Синтетическое погашение, млн ₽.
    inputs = _inputs(historical={"facts.nkl2025": {
        "debt": 2139.41871, "drawn": 5485.689, "schedule_base": 5485.689,
        "accrued_interest": 0, "accrued_fee": 0, "operations": [{
            "date": "2027-09-30", "kind": "prepay", "amount": principal_from_disclosure}]}})
    for dataset in inputs["datasets"].values():
        dataset["as_of"] = "2027-09-30"
    loan = credit.forecast(inputs)["loans"][0]
    assert "2027-09-30" not in loan["payments"]
    assert loan["payments"]["2027-12-30"]["principal"] == pytest.approx(.07 * A_BASE)
    assert sum(p["principal"] for p in loan["payments"].values()) == pytest.approx(2139.41871 * M)


def test_prepay_on_base_is_reflected_in_debt_base_but_subtracted_from_drawn_base_once():
    inputs = _inputs(prepay=[{"date": "2027-06-30", "amount": 100}])
    inputs["datasets"]["plan.nkl2026"]["data"]["prepayments"] = [{
        "date": "2027-10-01", "amount": 100 * M}]
    result = credit.forecast(inputs)
    a, b = result["loans"]
    assert a["base"]["amount"] == pytest.approx(A_BASE - 100 * M)
    assert a["payments"]["2027-09-30"]["principal"] == pytest.approx(.61 * (A_BASE - 100 * M))
    assert b["base"]["amount"] == pytest.approx(1125 * M)
    assert b["payments"]["2029-03-30"]["principal"] == pytest.approx(158.75 * M)
    assert sum(p["principal"] for p in b["payments"].values()) == pytest.approx(1125 * M)
    # До базы B та же операция переносится через pending_prepay.
    before = copy.deepcopy(inputs)
    before["datasets"]["plan.nkl2026"]["data"]["prepayments"][0]["date"] = "2027-09-30"
    b_before = credit.forecast(before)["loans"][1]
    assert b_before["payments"]["2029-03-30"]["principal"] == pytest.approx(158.75 * M)


def test_conditional_debt_label_does_not_claim_unfunded_payment_was_made():
    result = credit.analyse(_inputs())
    page = credit.render_html(result)
    assert "Долг при выполнении графика" in page
    assert "нулевой остаток графика не означает, что кредит фактически погашен" in page
    assert result["base"]["top"]["deficit_total"]["value"] > 0
