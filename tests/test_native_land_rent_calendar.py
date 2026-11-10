"""Native consumers keep exact day-17 dates on monthly cash calendars."""
from __future__ import annotations

import copy
import io
import sys
from datetime import date, datetime, timedelta

import openpyxl
import pytest

import hotel_presets
import hotel_workbook as hw
import main_legacy as core
import native_land_rent_book as native
import office_workbook as ow
from xlsx_eval import Evaluator


def _project(kind):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    for obj in core.STANDALONE_OBJECTS:
        x[obj.enabled_key] = False
    if kind == "hotel":
        x = hotel_presets.apply_preset(x, "hotel1")
    x.update(project_kind="hotel" if kind == "hotel" else "nonresidential",
             project_start="2027-01-17", ird_months=12, construction_months=12,
             land_right="lease", land_rights_cost_mln=0,
             land_rent_mode="manual", vri_region="msk", land_rent_cadastral_mln=100,
             land_rent_regime_start="2027-01-17",
             land_rent_rates=[{"year": 1, "rate_pct": 1}],
             land_rent_tail_rule="repeat_last", land_rent_vat_treatment="public_exempt")
    if kind != "hotel":
        prefix = "offices" if kind == "office" else "retail"
        x.update({prefix+"_enabled": True, prefix+"_gba_sqm": 5000,
                  prefix+"_saleable_sqm": 3500, prefix+"_strategy": "income",
                  prefix+"_rent_th_per_sqm_month": 5, prefix+"_occupancy_stable_pct": 95,
                  prefix+"_leaseup_months": 12, prefix+"_opex_pct": 18,
                  prefix+"_exit_cap_pct": 10, prefix+"_start": "2028-01-17",
                  prefix+"_months": 12})
    return x, copy.deepcopy(core.TEP_DEFAULT)


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date(1899, 12, 30) + timedelta(days=int(value))


def _hotel_evaluate(w):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    evaluator = Evaluator(w)
    for row in range(hw.FIRST_ROW, w[hw.CALC_SHEET].max_row+1):
        for column, _ in hw.COLUMNS.values():
            value = w[hw.CALC_SHEET][f"{column}{row}"].value
            if isinstance(value, str) and value.startswith("="):
                evaluator.cell(hw.CALC_SHEET, f"{column}{row}")
    return evaluator


@pytest.mark.parametrize("kind", ["hotel", "office", "retail"])
def test_actual_native_export_conserves_day17_rent_and_finance(kind):
    x, t = _project(kind)
    result = core._run_authoritative_model(x, t, [], {})["consolidated"]
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Synthetic day17")
    w = openpyxl.load_workbook(io.BytesIO(content))
    assert meta.get("hotel_book") if kind == "hotel" else meta.get("nonres_book")
    assert result["land_rent"]["construction_total"] == pytest.approx(2e6)
    assert result["land_rent"]["rve"] == "2029-01-17"
    evaluator = _hotel_evaluate(w) if kind == "hotel" else ow.evaluate(w)
    assert _date_value(evaluator.cell(native.SHEET, "B14")) == date(2027, 1, 17)
    assert evaluator.cell(native.SHEET, "B19") * 1e6 == pytest.approx(result["capex"]["land_rent"])
    assert evaluator.cell(native.SHEET, "D3") == (date(2027, 1, 1)-date(1899, 12, 30)).days
    if kind == "hotel":
        checks = w[hw.CHECK_SHEET]
        bad = [(checks[f"A{row}"].value, evaluator.cell(hw.CHECK_SHEET, f"F{row}"))
               for row in range(3, checks.max_row+1)
               if checks[f"B{row}"].value is not None
               and evaluator.cell(hw.CHECK_SHEET, f"F{row}") not in ("сходится", "—")]
        assert bad == []
        assert evaluator.cell(hw.CHECK_SHEET, "H3") == "ПРОЙДЕНО"
        assert _date_value(evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["start"]))) == date(2027, 1, 17)
        assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_total"])) == pytest.approx(result["capex"]["total"])
        assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["building_net"])) == pytest.approx(result["finance"]["hotel"]["kpi"]["building_net"])
    else:
        verdict, bad = ow.verdict(evaluator)
        assert verdict == ow.PASSED and bad == [], (verdict, bad)
        assert meta["checks"] == ow.PASSED
        assert not any("расхождения" in item for item in meta["missing"])
    qualifier = evaluator.cell(native.SHEET, "L13")
    assert qualifier  # the rental contract is not claimed to terminate at RVE.
