"""Live native calendar, paid/accrued split and blank-safe shared inputs."""
from datetime import date

import openpyxl
import pytest

import developaid_land_rent as rent
import native_land_rent_book as native
from xlsx_eval import Evaluator


def _book(*, payment="accrual", years=2, count=60):
    x = {"land_right": "lease", "land_rent_mode": "manual", "vri_region": "msk",
         "land_rent_cadastral_mln": 100, "land_rent_regime_start": "2027-01-01",
         "land_rent_rates": [{"year": 1, "rate_pct": 1}],
         "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt"}
    if payment == "advance":
        x.update(land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0")
    w = openpyxl.Workbook()
    ws = w.active
    ws.title = "Календарь"
    ws["A1"], ws["B1"], ws["C1"] = date(2027, 1, 1), 12, years
    start = "'Календарь'!$A$1"
    comm = f"EDATE({start},'Календарь'!$B$1)"
    end = f"EDATE({comm},'Календарь'!$C$1*12)"
    months = [f"EDATE({start},{k})" for k in range(count)]
    e = {"id": "hotel", "phase_index": 0, "object_key": "hotel", "share": 1,
         "commissioning": "2028-01-01", "lease_exit": f"{2028+years}-01-01",
         "retained": True, "policy": "income_horizon", "source": "Сценарий удержания"}
    result = rent.build(x, date(2027, 1, 1), date(2028, 1, 1), date(2028+years, 1, 1), exposures=[e])
    refs = native.add(w, {"land_rent_inputs": x, "land_rent": result}, start=start,
        rve=end, end=end, month_formulas=months,
        exposure_formulas={"hotel": {"share": "1", "commissioning": comm, "lease_exit": end}})
    e2 = {**e, "lease_exit": f"{2029+years}-01-01"}
    value = rent.build(x, date(2027, 1, 1), date(2028, 1, 1), date(2029+years, 1, 1), exposures=[e2])
    val_refs = native.add(w, {"land_rent_inputs": x, "land_rent": value}, start=start,
        rve=f"EDATE({end},12)", end=f"EDATE({end},12)", month_formulas=months,
        exposure_formulas={"hotel": {"share": "1", "commissioning": comm, "lease_exit": f"EDATE({end},12)"}},
        sheet_name="Оценка", master_terms_sheet=refs.sheet_name)
    return w, refs, val_refs, result


def _value(ev, ref):
    sheet, cell = ref.split("!", 1)
    return ev.cell(sheet.strip("'"), cell)


def test_retained_native_axis_and_exit_follow_edited_hold_beyond_180_months():
    w, paid, valuation, result = _book(years=16, count=252)
    ev = Evaluator(w)
    assert ev.cell(paid.sheet_name, "B19") * 1e6 == pytest.approx(result["cash_total"])
    assert _value(ev, paid.month(200, "operating_accrual")) > 0
    assert _value(ev, paid.month(204, "operating_accrual")) == 0
    assert _value(ev, valuation.month(204, "operating_accrual")) > 0
    w["Календарь"]["C1"] = 18
    ev = Evaluator(w)
    # Independent annual oracle: 1 pre-commissioning + 18 operating years.
    assert ev.cell(paid.sheet_name, "B19") == pytest.approx(19)
    assert _value(ev, paid.month(220, "operating_accrual")) > 0
    assert _value(ev, paid.month(228, "operating_accrual")) == 0
    assert _value(ev, valuation.month(228, "operating_accrual")) > 0


def test_operating_advance_is_paid_once_without_early_capitalization():
    w, paid, _, result = _book(payment="advance")
    ev = Evaluator(w)
    assert _value(ev, paid.month(0, "construction")) == pytest.approx(1)
    assert _value(ev, paid.month(0, "operating")) == pytest.approx(2)
    assert _value(ev, paid.month(0, "operating_accrual")) == 0
    assert _value(ev, paid.month(12, "operating_accrual")) > 0
    assert _value(ev, paid.month(12, "operating")) == 0
    assert result["development_cash_total"] == pytest.approx(1e6)


def test_secondary_calendar_preserves_unknown_rate_and_explicit_zero():
    w, paid, valuation, _ = _book()
    w[paid.sheet_name]["D22"] = None
    ev = Evaluator(w)
    assert ev.cell(valuation.sheet_name, "D22") == ""
    assert ev.cell(paid.sheet_name, "B17") == 0
    assert ev.cell(valuation.sheet_name, "B17") == 0
    w[paid.sheet_name]["D22"] = 0
    ev = Evaluator(w)
    assert ev.cell(valuation.sheet_name, "D22") == 0
    assert ev.cell(paid.sheet_name, "B17") == 1
    assert ev.cell(valuation.sheet_name, "B17") == 1
    assert ev.cell(valuation.sheet_name, "B19") == 0
