"""Тесты платы за изменение ВРИ: график платежей, проценты и источники оплаты.

Плата за смену ВРИ меняет базовую логику денежного потока: размер БРИДЖа,
собственный капитал до ПФ, даты возникновения расходов, стоимость рассрочки,
проценты и потребность в лимите ПФ. Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

PERMIT = date(2028, 7, 1)
AMOUNT = 3_000_000_000.0


def settings(**overrides) -> dict:
    return {"rate_start_pct": 12.0, **overrides}


def schedule(**overrides) -> dict:
    return main.build_vri_schedule(settings(**overrides), AMOUNT, PERMIT)


def model(**overrides) -> dict:
    x = copy.deepcopy(main.DEFAULT_INPUTS)
    x["land_rights_cost_mln"] = AMOUNT / 1_000_000
    x.update(overrides)
    return main.calculate(main.CalcRequest(inputs=x, tep=main.TEP_DEFAULT, rates=[]))


# --- обязательство и график ------------------------------------------------

def test_lump_payment_is_a_single_row_on_the_obligation_date():
    result = schedule()
    assert result["enabled"] is True
    assert [row["date"] for row in result["rows"]] == [PERMIT.isoformat()]
    assert result["totals"]["principal"] == pytest.approx(AMOUNT)
    assert result["totals"]["interest"] == 0.0


def test_obligation_date_can_differ_from_the_permit():
    result = schedule(vri_obligation_date="2027-04-01")
    assert result["rows"][0]["date"] == "2027-04-01"


def test_moscow_six_year_installment_is_quarterly():
    result = schedule(vri_payment_mode="installment", vri_installment_years=6)
    assert len(result["rows"]) == 24
    assert result["rows"][0]["date"] == "2028-10-01"
    assert result["rows"][-1]["date"] == "2034-07-01"
    assert result["totals"]["principal"] == pytest.approx(AMOUNT)
    assert result["rows"][-1]["balance_after"] == pytest.approx(0.0)


def test_moscow_term_is_snapped_to_one_three_or_six_years():
    assert schedule(vri_payment_mode="installment", vri_installment_years=4)["settings"]["years"] == 3
    assert schedule(vri_payment_mode="installment", vri_installment_years=5)["settings"]["years"] == 6
    assert schedule(vri_payment_mode="installment", vri_installment_years=1)["settings"]["years"] == 1


def test_moscow_interest_accrues_on_the_outstanding_balance():
    result = schedule(vri_payment_mode="installment", vri_installment_years=3)
    rows = result["rows"]
    # Ключевая 12% плюс спред 3 п.п., квартал на полном остатке.
    assert rows[0]["interest"] == pytest.approx(AMOUNT * 0.15 / 12 * 3)
    # Остаток падает — проценты следующего периода меньше.
    assert rows[1]["interest"] < rows[0]["interest"]
    assert result["totals"]["interest"] == pytest.approx(sum(row["interest"] for row in rows))


def test_interest_spread_is_a_parameter():
    base = schedule(vri_payment_mode="installment")["totals"]["interest"]
    wider = schedule(vri_payment_mode="installment", vri_interest_spread_pp=6.0)["totals"]["interest"]
    assert wider > base


def test_interest_can_be_switched_off_explicitly():
    result = schedule(vri_payment_mode="installment", vri_interest_enabled="0")
    assert result["totals"]["interest"] == 0.0


# --- Московская область ----------------------------------------------------

def test_moscow_region_has_no_automatic_interest():
    result = schedule(vri_region="mo", vri_payment_mode="installment", vri_installment_years=3)
    assert result["region"] == "mo"
    assert result["totals"]["interest"] == 0.0


def test_moscow_region_without_ranges_warns_and_keeps_the_entered_term():
    result = schedule(vri_region="mo", vri_payment_mode="installment", vri_installment_years=2,
                      vri_periodicity_months=6)
    assert result["settings"]["years"] == 2
    assert result["settings"]["periodicity"] == 6
    assert len(result["rows"]) == 4
    assert any("Диапазоны рассрочки" in text for text in result["warnings"])


def test_moscow_region_range_by_amount_sets_term_and_periodicity():
    ranges = [
        {"limit_mln": 1000, "years": 1, "periodicity_months": 3},
        {"limit_mln": None, "years": 5, "periodicity_months": 6},
    ]
    result = schedule(vri_region="mo", vri_payment_mode="installment", vri_mo_ranges=ranges)
    assert result["settings"]["years"] == 5
    assert result["settings"]["periodicity"] == 6
    assert len(result["rows"]) == 10
    assert not any("Диапазоны рассрочки" in text for text in result["warnings"])


def test_moscow_region_interest_by_agreement_is_reported():
    result = schedule(vri_region="mo", vri_payment_mode="installment", vri_interest_enabled="1")
    assert result["totals"]["interest"] > 0
    assert any("Московской области" in text for text in result["warnings"])


# --- источники оплаты ------------------------------------------------------

def test_payments_before_pf_go_to_the_bridge():
    result = schedule(vri_obligation_date="2027-01-01")
    row = result["rows"][0]
    assert row["before_pf"] is True
    assert row["bridge"] == pytest.approx(AMOUNT)
    assert row["pf"] == 0.0


def test_payments_after_pf_go_to_project_finance():
    result = schedule()
    row = result["rows"][0]
    assert row["before_pf"] is False
    assert row["pf"] == pytest.approx(AMOUNT)


def test_outside_the_bank_budget_the_payment_stays_on_equity():
    result = schedule(vri_in_bank_budget=False)
    assert result["totals"]["equity"] == pytest.approx(AMOUNT)
    assert result["totals"]["pf"] == 0.0


def test_explicit_shares_split_the_payment():
    result = schedule(vri_financing_mode="shares", vri_share_bridge_pct=20,
                      vri_share_pf_pct=50, vri_share_equity_pct=30)
    totals = result["totals"]
    assert totals["bridge"] == pytest.approx(AMOUNT * 0.2)
    assert totals["pf"] == pytest.approx(AMOUNT * 0.5)
    assert totals["equity"] == pytest.approx(AMOUNT * 0.3)


def test_pf_share_before_pf_is_carried_by_the_bridge():
    result = schedule(vri_obligation_date="2027-01-01", vri_financing_mode="shares",
                      vri_share_pf_pct=100)
    assert result["totals"]["bridge"] == pytest.approx(AMOUNT)
    assert result["totals"]["pf"] == 0.0


def test_early_repayment_after_pf_closes_the_balance_at_once():
    result = schedule(vri_payment_mode="installment", vri_installment_years=6,
                      vri_early_repay_after_pf=True)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["principal"] == pytest.approx(AMOUNT)
    assert result["rows"][0]["balance_after"] == pytest.approx(0.0)


def test_security_cost_is_a_separate_row_on_the_obligation_date():
    result = schedule(vri_security_cost_mln=25)
    first = result["rows"][0]
    assert first["security"] is True
    assert first["total"] == pytest.approx(25_000_000)
    assert result["totals"]["security_cost"] == pytest.approx(25_000_000)
    assert result["totals"]["principal"] == pytest.approx(AMOUNT)


# --- ручной график ---------------------------------------------------------

def test_manual_schedule_is_used_as_entered():
    rows = [{"date": "2029-01-01", "principal_mln": 1000},
            {"date": "2030-01-01", "principal_mln": 2000}]
    result = schedule(vri_schedule_mode="manual", vri_manual_schedule=rows)
    assert [row["date"] for row in result["rows"]] == ["2029-01-01", "2030-01-01"]
    assert result["totals"]["principal"] == pytest.approx(AMOUNT)


def test_manual_schedule_mismatch_is_reported():
    rows = [{"date": "2029-01-01", "principal_mln": 1000}]
    result = schedule(vri_schedule_mode="manual", vri_manual_schedule=rows)
    assert any("не совпадает" in text for text in result["warnings"])
    assert any("непогашенный остаток" in text for text in result["warnings"])


def test_empty_manual_schedule_falls_back_to_automatic():
    result = schedule(vri_schedule_mode="manual", vri_manual_schedule=[])
    assert len(result["rows"]) == 1
    assert any("не заданы" in text for text in result["warnings"])


# --- отключение ------------------------------------------------------------

def test_vri_can_be_switched_off():
    result = schedule(vri_required=False)
    assert result["enabled"] is False
    assert result["rows"] == []
    assert result["totals"]["cash"] == 0.0


def test_zero_amount_yields_an_empty_block():
    assert main.build_vri_schedule(settings(), 0.0, PERMIT)["enabled"] is False


# --- влияние на модель -----------------------------------------------------

def test_lump_default_keeps_the_previous_cash_flow():
    result = model()
    permit = result["dates"]["permit"]
    monthly = {row["key"]: row for row in result["monthly"]["costs"]}
    land = monthly["land_rights"]
    months = result["monthly"]["months"]
    assert land["values"][months.index(permit)] == pytest.approx(AMOUNT)
    assert land["total"] == pytest.approx(AMOUNT)


def test_installment_spreads_land_rights_over_the_schedule():
    result = model(vri_payment_mode="installment", vri_installment_years=6)
    monthly = {row["key"]: row for row in result["monthly"]["costs"]}
    paid_months = [value for value in monthly["land_rights"]["values"] if value > 1]
    assert len(paid_months) > 1
    assert monthly["land_rights"]["total"] == pytest.approx(AMOUNT, rel=1e-6)


def test_installment_interest_is_its_own_cost_article():
    result = model(vri_payment_mode="installment", vri_installment_years=6)
    assert result["capex"]["vri_interest"] > 0
    monthly = {row["key"]: row for row in result["monthly"]["costs"]}
    assert "vri_interest" in monthly
    assert monthly["vri_interest"]["total"] == pytest.approx(result["capex"]["vri_interest"], rel=1e-6)


def test_installment_lowers_peak_project_finance():
    lump = model()
    spread = model(vri_payment_mode="installment", vri_installment_years=6)
    assert spread["finance"]["peak_pf"] < lump["finance"]["peak_pf"]


def test_early_obligation_raises_the_bridge():
    late = model()
    early = model(vri_obligation_date="2027-03-01")
    assert early["finance"]["peak_bridge"] > late["finance"]["peak_bridge"]


def test_equity_funded_vri_is_excluded_from_debt_financing():
    bank = model()
    own = model(vri_in_bank_budget=False)
    assert own["vri"]["totals"]["equity"] == pytest.approx(AMOUNT)
    assert own["finance"]["peak_pf"] < bank["finance"]["peak_pf"]
    # CAPEX проекта не меняется — меняется только источник денег.
    assert own["capex"]["land_rights"] == pytest.approx(bank["capex"]["land_rights"])


def test_report_carries_the_vri_block():
    result = model(vri_payment_mode="installment", vri_installment_years=3)
    assert result["vri"]["enabled"] is True
    labels = {item["label"] for item in result["report"]["expense_structure"]}
    assert "Проценты по рассрочке ВРИ" in labels


# --- очерёдность -----------------------------------------------------------

def phased(**overrides) -> dict:
    x = copy.deepcopy(main.DEFAULT_INPUTS)
    x["land_rights_cost_mln"] = AMOUNT / 1_000_000
    x.update(overrides)
    phasing = {
        "enabled": True,
        "phase_gap_months": 12,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        ],
        "shared_cash": {"land_rights": [50.0, 50.0]},
    }
    return main.calculate_phased(main.PhasedCalcRequest(
        inputs=x, tep=main.TEP_DEFAULT, rates=[], phasing=phasing))


def test_vri_installment_keeps_one_calendar_across_phases():
    bundle = phased(vri_payment_mode="installment", vri_installment_years=6)
    dates_by_phase = [
        [row["date"] for row in item["result"]["vri"]["rows"]]
        for item in bundle["phases"]
    ]
    # Обязательство одно на проект: даты платежей у очередей совпадают.
    assert dates_by_phase[0] == dates_by_phase[1]
    assert len(dates_by_phase[0]) == 24


def test_consolidated_vri_sums_the_phase_shares():
    bundle = phased(vri_payment_mode="installment", vri_installment_years=6)
    summary = bundle["vri"]
    assert summary["enabled"] is True
    assert summary["totals"]["principal"] == pytest.approx(AMOUNT, rel=1e-6)
    assert len(summary["rows"]) == 24
    first = summary["rows"][0]
    assert set(first["by_phase"]) == {"О1", "О2"}
    assert first["by_phase"]["О1"] == pytest.approx(first["by_phase"]["О2"], rel=1e-6)
    assert summary["rows"][-1]["balance_after"] == pytest.approx(0.0, abs=1.0)


def test_phase_payments_before_its_own_pf_are_carried_by_its_bridge():
    bundle = phased(vri_payment_mode="installment", vri_installment_years=6)
    second = bundle["phases"][1]["result"]["vri"]
    # Вторая очередь стартует позже, её ПФ открывается позже — ранние платежи
    # по общему графику она несёт БРИДЖем.
    assert second["totals"]["bridge"] > 0
    assert any(row["before_pf"] for row in second["rows"])


def test_payment_before_a_phase_start_is_moved_to_its_first_month():
    bundle = phased(vri_obligation_date="2027-01-01")
    second = bundle["phases"][1]["result"]
    monthly = {row["key"]: row for row in second["monthly"]["costs"]}
    assert monthly["land_rights"]["total"] == pytest.approx(AMOUNT / 2, rel=1e-6)
    assert any("до старта расчёта" in text for text in second["vri"]["warnings"])

# --- льгота ----------------------------------------------------------------

def test_percent_relief_cuts_the_obligation():
    result = model(vri_relief_mode="percent", vri_relief_pct=30)
    totals = result["vri"]["totals"]
    assert totals["gross"] == pytest.approx(AMOUNT)
    assert totals["relief"] == pytest.approx(AMOUNT * 0.3)
    assert totals["amount"] == pytest.approx(AMOUNT * 0.7)
    assert result["capex"]["land_rights"] == pytest.approx(AMOUNT * 0.7)


def test_fixed_amount_relief():
    result = model(vri_relief_mode="amount", vri_relief_mln=500)
    assert result["vri"]["totals"]["amount"] == pytest.approx(AMOUNT - 500_000_000)


def test_relief_cannot_exceed_the_obligation():
    result = model(vri_relief_mode="amount", vri_relief_mln=99_999)
    assert result["vri"]["totals"]["relief"] == pytest.approx(AMOUNT)
    assert result["capex"]["land_rights"] == pytest.approx(0.0)
    assert result["vri"]["enabled"] is False


def test_relief_is_applied_before_overheads_and_interest():
    full = model(vri_payment_mode="installment", vri_installment_years=6)
    cut = model(vri_payment_mode="installment", vri_installment_years=6,
                vri_relief_mode="percent", vri_relief_pct=30)
    # Резерв считается от суммы к оплате, а не от валового обязательства.
    assert cut["capex"]["reserve"] < full["capex"]["reserve"]
    # Проценты по рассрочке — тоже.
    assert cut["capex"]["vri_interest"] == pytest.approx(full["capex"]["vri_interest"] * 0.7, rel=1e-6)


def test_no_relief_by_default():
    totals = model()["vri"]["totals"]
    assert totals["relief"] == 0.0
    assert totals["gross"] == pytest.approx(totals["amount"])


def test_relief_is_not_applied_twice_across_phases():
    bundle = phased(vri_relief_mode="percent", vri_relief_pct=30)
    assert bundle["vri"]["totals"]["gross"] == pytest.approx(AMOUNT)
    assert bundle["vri"]["totals"]["relief"] == pytest.approx(AMOUNT * 0.3)
    paid = sum(item["result"]["capex"]["land_rights"] for item in bundle["phases"])
    assert paid == pytest.approx(AMOUNT * 0.7, rel=1e-6)


# --- дата обязательства и первый взнос --------------------------------------

def test_obligation_date_modes():
    base = {"project_start": "2027-01-01"}
    assert main.vri_obligation_date(base, PERMIT)[0] == PERMIT
    assert main.vri_obligation_date({**base, "vri_obligation_date_mode": "before_rns_1m"}, PERMIT)[0] == date(2028, 6, 1)
    assert main.vri_obligation_date({**base, "vri_obligation_date_mode": "before_rns_3m"}, PERMIT)[0] == date(2028, 4, 1)
    assert main.vri_obligation_date(
        {**base, "vri_obligation_date_mode": "after_purchase", "vri_months_after_purchase": 12}, PERMIT
    )[0] == date(2028, 1, 1)


def test_explicit_date_wins_and_is_not_estimated():
    when, basis, estimated = main.vri_obligation_date({"vri_obligation_date": "2027-05-01"}, PERMIT)
    assert when == date(2027, 5, 1)
    assert estimated is False
    assert "вручную" in basis


def test_estimated_dates_are_flagged_with_a_reason():
    for mode in ("at_rns", "before_rns_1m", "before_rns_3m"):
        _, basis, estimated = main.vri_obligation_date({"vri_obligation_date_mode": mode}, PERMIT)
        assert estimated is True
        assert basis.startswith("Оценочная дата")


def test_manual_mode_without_a_date_falls_back_to_the_permit():
    when, basis, estimated = main.vri_obligation_date({"vri_obligation_date_mode": "manual"}, PERMIT)
    assert when == PERMIT
    assert estimated is True
    assert "не задана" in basis


def test_obligation_before_the_permit_moves_the_payment_to_the_bridge():
    late = model()
    early = model(vri_obligation_date_mode="before_rns_3m")
    assert early["vri"]["rows"][0]["before_pf"] is True
    assert early["vri"]["totals"]["bridge"] == pytest.approx(AMOUNT)
    assert early["finance"]["peak_bridge"] > late["finance"]["peak_bridge"]


def test_initial_payment_is_paid_on_the_obligation_date():
    result = schedule(vri_payment_mode="installment", vri_installment_years=3, vri_initial_pct=25)
    rows = result["rows"]
    assert rows[0]["date"] == PERMIT.isoformat()
    assert rows[0]["principal"] == pytest.approx(AMOUNT * 0.25)
    # Остаток дробится на регулярные платежи графика.
    assert len(rows) == 13
    assert rows[1]["principal"] == pytest.approx(AMOUNT * 0.75 / 12)
    assert result["totals"]["principal"] == pytest.approx(AMOUNT)
    assert rows[-1]["balance_after"] == pytest.approx(0.0)


def test_initial_payment_lowers_the_installment_interest():
    plain = schedule(vri_payment_mode="installment", vri_installment_years=3)["totals"]["interest"]
    with_initial = schedule(vri_payment_mode="installment", vri_installment_years=3,
                            vri_initial_pct=25)["totals"]["interest"]
    assert with_initial < plain


def test_initial_payment_is_ignored_for_a_lump_sum():
    result = schedule(vri_initial_pct=25)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["principal"] == pytest.approx(AMOUNT)
