"""Shared editable ground-rent formulas reach native books and their CF/VAT."""
import copy
import io
from datetime import date

import openpyxl
import pytest
from openpyxl.utils import get_column_letter

import developaid_land_rent as rent
import hotel_presets
import hotel_workbook as hw
import main_legacy as core
import native_land_rent_book as native
import office_workbook as ow
from xlsx_eval import Evaluator


def settings(**over):
    values = {"land_right": "lease", "land_rent_mode": "manual", "vri_region": "msk",
              "land_rent_cadastral_mln": 100, "land_rent_regime_start": "2027-01-01",
              "land_rent_rates": [{"year": 1, "rate_pct": 1}],
              "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt"}
    return {**values, **over}


def workbook(inputs=None, months=360, construction=240, start_day=1):
    inputs = inputs or settings()
    w = openpyxl.Workbook()
    dates = w.active
    dates.title = "Календарь"
    dates["A1"], dates["B1"], dates["C1"] = date(2027, 1, start_day), construction, 12
    start = "'Календарь'!$A$1"
    rve = f"EDATE({start},'Календарь'!$B$1)"
    result = rent.build(inputs, date(2027, 1, start_day), core.add_months(date(2027, 1, start_day), construction),
                        core.add_months(date(2027, 1, start_day), construction+12))
    ref = native.add(w, {"land_rent_inputs": inputs, "land_rent": result},
        start=start, rve=rve, end=f"EDATE({rve},'Календарь'!$C$1)",
        month_formulas=[f"EDATE({start},{k})" for k in range(months)])
    return w, ref, result


def test_shared_native_sheet_is_editable_beyond_month_180():
    w, ref, result = workbook()
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "B19") * 1e6 == pytest.approx(result["construction_total"])
    sheet, coord = native.SHEET, ref(190).split("!", 1)[1]
    assert evaluator.cell(sheet, coord) > 0
    previous = evaluator.cell(sheet, "B19")
    w["Календарь"]["B1"] = 252  # RVE moves by a year, no regenerated workbook.
    assert Evaluator(w).cell(sheet, "B19") == pytest.approx(previous + 1)
    w[sheet]["B9"] = 200
    assert Evaluator(w).cell(sheet, "B19") == pytest.approx((previous + 1) * 2)
    w[sheet]["D22"] = 2  # first lease year, independently editable rate.
    assert Evaluator(w).cell(sheet, "B19") == pytest.approx((previous + 1) * 4)


def test_unknown_rate_stays_visible_and_known_part_remains_numeric():
    w, _, _ = workbook(settings(land_rent_tail_rule="unknown"), months=36, construction=24)
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "B19") == pytest.approx(1)
    assert evaluator.cell(native.SHEET, "B17") == 0
    assert isinstance(evaluator.cell(native.SHEET, "B18"), str)
    native.qualify(w["Календарь"])
    qualifier = Evaluator(w).cell(native.SHEET, "L13")
    assert qualifier and qualifier in Evaluator(w).cell("Календарь", "A2")


def test_exact_project_day_survives_native_month_bucketing():
    w, _, result = workbook(settings(land_rent_rates=[{"year": 1, "rate_pct": 1},
                                                     {"year": 2, "rate_pct": 2}]),
                            months=36, construction=12, start_day=17)
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "B19") * 1e6 == pytest.approx(result["construction_total"])
    assert evaluator.cell(native.SHEET, "D4") * 1e6 == pytest.approx(result["accrual_monthly"]["2027-01-01"])
    assert evaluator.cell(native.SHEET, "D3") == (date(2027, 1, 1)-date(1899, 12, 30)).days
    assert evaluator.cell(native.SHEET, "B14") == date(2027, 1, 17)


def test_native_monthly_cash_does_not_require_invented_termination():
    w, _, _ = workbook(settings(land_rent_payment_mode="manual",
                                land_rent_payment_schedule="0.3@0;0.7@6"), months=36, construction=12)
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "F18") == 0  # post-RVE is still unknown.
    assert evaluator.cell(native.SHEET, "F17") == 1
    assert evaluator.cell(native.SHEET, "D6") == pytest.approx(0.3)
    assert evaluator.cell(native.SHEET, "J6") == pytest.approx(0.7)
    assert evaluator.cell(native.SHEET, "E6") == 0
    w[native.SHEET]["C126"] = 0.8  # second row of the editable payment table.
    assert Evaluator(w).cell(native.SHEET, "F17") == 0


def test_native_mo_indices_follow_calendar_year_and_remain_editable():
    x = settings(land_rent_mode="mo_housing_new_2026", vri_region="mo",
                 land_rent_preset_confirmed=True, land_rent_contract_date="2027-01-02",
                 land_rent_regime_start="2027-07-01", land_rent_public_scope="regional",
                 land_rent_grant_basis="ordinary_nonauction", land_rent_mo_cadastral_unchanged=True,
                 land_rent_calendar_indices=[{"year": 2028, "index_pct": 10}])
    w, _, result = workbook(x, months=36, construction=24)
    assert result["construction_total"] is not None, result["missing"]
    before = Evaluator(w).cell(native.SHEET, "B19")
    assert before * 1e6 == pytest.approx(result["construction_total"])
    index_row = next(r for r in range(628, 728) if w[native.SHEET][f"A{r}"].value == 2028)
    w[native.SHEET][f"B{index_row}"] = 20
    assert Evaluator(w).cell(native.SHEET, "B19") == pytest.approx(before + 0.6)
    w[native.SHEET][f"B{index_row}"] = None
    partial = Evaluator(w)
    assert partial.cell(native.SHEET, "B17") == 0
    assert partial.cell(native.SHEET, "B19") == pytest.approx(6 * 184/365)


def test_manual_cash_horizon_retains_its_day_after_a_nonfirst_cutoff():
    w = openpyxl.Workbook()
    dates = w.active
    dates.title = "Календарь"
    dates["A1"], dates["B1"] = date(2027, 1, 5), date(2029, 1, 17)
    x = settings(land_rent_payment_mode="manual", land_rent_payment_schedule="100%@37")
    result = rent.build(x, date(2027, 1, 5), date(2029, 1, 17), date(2030, 2, 1))
    spec = {"land_rent_inputs": x, "land_rent": result}
    native.add(w, spec, start="'Календарь'!A1", rve="'Календарь'!B1",
        end=native.end_formula(spec, "'Аренда ЗУ'!$B$15"),
        month_formulas=[f"EDATE('Календарь'!A1,{k})" for k in range(48)])
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "F11") == (date(2030, 2, 1)-date(1899, 12, 30)).days
    assert evaluator.cell(native.SHEET, "F17") == 0  # Feb5 is outside the exact Feb1 fence.
    w[native.SHEET]["A125"] = 36  # Jan5 is inside; post-RVE unknown does not erase cash.
    assert Evaluator(w).cell(native.SHEET, "F17") == 1


def test_unsupported_native_phases_do_not_freeze_common_rent():
    x = settings()
    result = rent.build(x, date(2027, 1, 1), date(2030, 1, 1))
    result["phase_shares"] = [1.0, 0.0]
    with pytest.raises(ValueError, match="Нативная книга отражает одну очередь"):
        native.add(openpyxl.Workbook(), {"land_rent_inputs": x, "land_rent": result},
                   start="1", rve="2", end="3", month_formulas=["1"])


def test_native_manual_cutoff_is_editable_and_matches_the_canonical_scope():
    w, _, _ = workbook(months=36, construction=24)
    w[native.SHEET]["L15"] = date(2028, 7, 1)
    x = settings(land_rent_manual_cutoff="2028-07-01")
    expected = rent.build(x, date(2027, 1, 1), date(2029, 1, 1), date(2030, 1, 1))
    assert Evaluator(w).cell(native.SHEET, "B19") * 1e6 == pytest.approx(expected["construction_total"])
    w[native.SHEET]["L15"] = date(2026, 12, 1)
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "B17") == 1
    assert evaluator.cell(native.SHEET, "B19") == 0


@pytest.fixture(scope="module")
def hotel():
    x = hotel_presets.apply_preset(copy.deepcopy(core.DEFAULT_INPUTS), "hotel1")
    x.update(settings(), project_kind="hotel", project_start="2027-01-01", ird_months=12,
             construction_months=12, land_rights_cost_mln=0)
    result = core._run_authoritative_model(x, copy.deepcopy(core.TEP_DEFAULT), [], {})["consolidated"]
    content = hw.build(result, "Synthetic lease")
    return x, result, openpyxl.load_workbook(io.BytesIO(content))


def test_native_hotel_includes_rent_in_capex_not_land_asset(hotel):
    _, result, w = hotel
    evaluator = Evaluator(w)
    assert evaluator.cell(native.SHEET, "B19") * 1e6 == pytest.approx(result["capex"]["land_rent"])
    assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_total"])) == pytest.approx(result["capex"]["total"])
    assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["land_total"])) == 0
    assert evaluator.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["building_net"])) == pytest.approx(result["finance"]["hotel"]["kpi"]["building_net"])
    qualifier = evaluator.cell(native.SHEET, "L13")
    assert qualifier and qualifier in evaluator.cell(hw.TOTALS_SHEET, "A2")


def test_native_hotel_vat_and_cost_change_with_edited_rent(hotel):
    _, _, original = hotel
    w = copy.deepcopy(original)
    before = Evaluator(w)
    old_capex = before.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_total"]))
    old_vat = before.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_vat"]))
    w[native.SHEET]["B9"] = 200
    after = Evaluator(w)
    assert after.cell(hw.CHECK_SHEET, "H4") > 0  # the original engine snapshot no longer applies.
    assert after.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_total"])) == pytest.approx(old_capex + 2e6)
    assert after.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_vat"])) == pytest.approx(old_vat)
    w[native.SHEET]["I18"] = "Облагается НДС"
    taxable = Evaluator(w)
    assert taxable.cell(hw.INPUTS_SHEET, "C"+str(hw._ROWS["capex_vat"])) > old_vat


@pytest.fixture(scope="module", params=["retail", "office"])
def retail(request):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    for obj in core.STANDALONE_OBJECTS:
        x[obj.enabled_key] = False
    x.update(settings(), project_kind="nonresidential", project_start="2027-01-01",
             ird_months=12, construction_months=12, land_rights_cost_mln=0)
    prefix = "offices" if request.param == "office" else "retail"
    x.update({prefix+"_enabled": True,
              prefix+"_gba_sqm": 5000, prefix+"_saleable_sqm": 3500,
              prefix+"_strategy": "income", prefix+"_rent_th_per_sqm_month": 5,
              prefix+"_occupancy_stable_pct": 95, prefix+"_leaseup_months": 12,
              prefix+"_opex_pct": 18, prefix+"_exit_cap_pct": 10,
              prefix+"_start": "2028-01-01", prefix+"_months": 12})
    t = copy.deepcopy(core.TEP_DEFAULT)
    result = core._run_authoritative_model(x, t, [], {})["consolidated"]
    prepared = core.prepared_calculation(copy.deepcopy(x), copy.deepcopy(t), [])
    spec = core.nonres_book_spec(prepared, result, "Synthetic retail lease")
    assert spec["land_rent_inputs"]["land_rent_mode"] == "manual"
    assert spec["land_rent"] == result["land_rent"]
    office_keys = {o.key for o in core.STANDALONE_OBJECTS if o.product == "offices"} if request.param == "office" else set()
    content, report = ow.build(result, spec, office_keys)
    return result, report, openpyxl.load_workbook(io.BytesIO(content))


def test_native_retail_cash_and_finance_consume_editable_rent(retail):
    result, report, w = retail
    evaluator = ow.evaluate(w)
    assert not report["unresolved"], report["unresolved_examples"]
    assert report["verdict"] == ow.PASSED, report["mismatches"]
    assert evaluator.cell(native.SHEET, "B19") * 1e6 == pytest.approx(result["capex"]["land_rent"])
    sheet = w[ow.CAPEX_SHEET]
    row = next(r for r in range(1, sheet.max_row+1) if sheet[f"A{r}"].value == "Аренда земельного участка")
    assert evaluator.cell(ow.CAPEX_SHEET, f"B{row}") == pytest.approx(2)
    old = evaluator.cell(ow.CAPEX_SHEET, f"B{row}")
    w[native.SHEET]["B9"] = 200
    assert ow.evaluate(w).cell(ow.CAPEX_SHEET, f"B{row}") == pytest.approx(old * 2)
    report_sheet = report["comparisons"][0]["report"] if report["comparisons"] else ow.REPORT_SHEET
    qualifier = evaluator.cell(native.SHEET, "L13")
    assert qualifier and qualifier in ow.evaluate(w).cell(report_sheet, "A2")
    # Only the active object's build duration changes, not project/RnS or
    # holding/exit dates. Its later commissioning prolongs the common lease.
    w[native.SHEET]["B9"] = 100
    inputs = w[ow.INPUTS_SHEET]
    months_row = next(r for r in range(1, inputs.max_row+1) if inputs[f"A{r}"].value == "Срок стройки")
    inputs[f"B{months_row}"] = 24
    assert ow.evaluate(w).cell(ow.CAPEX_SHEET, f"B{row}") == pytest.approx(3)
