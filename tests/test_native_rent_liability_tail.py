"""Deferred lease payments keep their own cash date in editable native books."""
import copy
import io
import json
from datetime import date

import openpyxl
import pytest

import hotel_presets
import hotel_workbook as hw
import main_legacy as core
import native_land_rent_book as native
import office_workbook as ow
from test_native_land_rent_books import settings


@pytest.fixture(scope="module")
def deferred_hotel():
    inputs = hotel_presets.apply_preset(copy.deepcopy(core.DEFAULT_INPUTS), "hotel1")
    inputs.update(settings(), project_kind="hotel", project_start="2027-01-01",
                  ird_months=12, construction_months=12, land_rights_cost_mln=0,
                  hotel_hold_years=1, hotel_exit_mode="hold", hotel_valuation="gordon",
                  land_rent_vat_treatment="taxable", land_rent_payment_mode="manual",
                  land_rent_payment_schedule="100%@120")
    result = core._run_authoritative_model(copy.deepcopy(inputs),
        copy.deepcopy(core.TEP_DEFAULT), [], {})["consolidated"]
    prepared = core.prepared_calculation(copy.deepcopy(inputs), copy.deepcopy(core.TEP_DEFAULT), [])
    operating = core.build_operating_model(prepared["x"], prepared["t"], prepared["rates"])
    flows = core.hotel_overlay(prepared["x"], prepared["rates"], operating)["flows"]
    book = openpyxl.load_workbook(io.BytesIO(hw.build(result, "Synthetic deferred lease")))
    return inputs, result, book, flows


def test_hotel_late_cash_and_accrued_vat_match_engine_without_extending_asset(deferred_hotel):
    _, result, book, model = deferred_hotel
    evaluator = hw.evaluate(book)
    start = date(2027, 1, 1)
    late = date(2037, 1, 1)
    r = hw.FIRST_ROW + 120
    assert model["horizon_end"] < late
    assert evaluator.cell(hw.CALC_SHEET, f"{hw._c('in_h')}{r}") == -1
    for key in ("land_rent_construction_cash", "land_rent_operating_cash", "fcff", "equity_cf"):
        assert evaluator.cell(hw.CALC_SHEET, f"{hw._c(key)}{r}") == pytest.approx(model["monthly"][key][late])
    assert evaluator.cell(hw.CALC_SHEET, f"{hw._c('draw')}{r}") == 0
    assert evaluator.cell(hw.CALC_SHEET, f"{hw._c('bal_close')}{r}") == 0
    for key in ("land_rent_construction_input_vat", "land_rent_construction_vat_refund"):
        assert model["totals"][key] > 0
        for month, expected in model["monthly"][key].items():
            line = hw.FIRST_ROW + (month.year - start.year) * 12 + month.month - start.month
            assert evaluator.cell(hw.CALC_SHEET, f"{hw._c(key)}{line}") == pytest.approx(expected)
    for key in ("capex_total", "building_net", "exit_value"):
        expected = model["totals"]["capex"] if key == "capex_total" else model["kpi"][key]
        assert evaluator.cell(hw.INPUTS_SHEET, f"C{hw._ROWS[key]}") == pytest.approx(expected)
    checks = book[hw.CHECK_SHEET]
    differences = [(checks[f"A{line}"].value, evaluator.cell(hw.CHECK_SHEET, f"B{line}"),
                    checks[f"C{line}"].value)
        for line in range(3, checks.max_row + 1)
        if checks[f"F{line}"].data_type == "f"
        and evaluator.cell(hw.CHECK_SHEET, f"F{line}") not in ("сходится", "—")]
    assert not differences, differences


def test_hotel_payment_edit_changes_cash_but_not_building_or_gordon_value(deferred_hotel):
    _, _, original, _ = deferred_hotel
    book = copy.deepcopy(original)
    before = hw.evaluate(book)
    baseline = {key: before.cell(hw.INPUTS_SHEET, f"C{hw._ROWS[key]}")
                for key in ("capex_total", "building_net", "exit_value")}
    old_cash = before.cell(hw.CALC_SHEET, f"{hw._c('land_rent_construction_cash')}{hw.FIRST_ROW + 120}")
    assert old_cash > 0
    # The same debt is paid in the last operating year, with no regenerated book.
    book[native.SHEET]["A125"] = 30
    after = hw.evaluate(book)
    for key, expected in baseline.items():
        assert after.cell(hw.INPUTS_SHEET, f"C{hw._ROWS[key]}") == pytest.approx(expected)
    assert after.cell(hw.CALC_SHEET, f"{hw._c('land_rent_construction_cash')}{hw.FIRST_ROW + 120}") == 0
    assert after.cell(hw.CALC_SHEET, f"{hw._c('land_rent_construction_cash')}{hw.FIRST_ROW + 30}") == pytest.approx(old_cash)


def test_office_and_retail_keep_area_based_liabilities_out_of_common_cost_weights(tmp_path):
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    for obj in core.STANDALONE_OBJECTS:
        inputs[obj.enabled_key] = False
    inputs.update(settings(), project_kind="nonresidential", project_start="2027-01-01",
                  ird_months=12, construction_months=12, land_rights_cost_mln=0,
                  # A payment after both operating horizons is sufficient to
                  # expose common-cost allocation of independent liabilities.
                  # Month120 and editable long tails are covered above and in
                  # test_native_land_rent_books; avoid multiplying their full
                  # calendar across every office/retail comparison here.
                  land_rent_payment_mode="manual", land_rent_payment_schedule="100%@48")
    for prefix, cost in (("offices", 100), ("retail", 200)):
        inputs.update({prefix + "_enabled": True, prefix + "_gba_sqm": 5000,
            prefix + "_saleable_sqm": 3500, prefix + "_cost_th_per_sqm": cost,
            prefix + "_strategy": "income", prefix + "_rent_th_per_sqm_month": 5,
            prefix + "_occupancy_stable_pct": 95, prefix + "_leaseup_months": 6,
            prefix + "_opex_pct": 18, prefix + "_exit_cap_pct": 10,
            prefix + "_hold_years": 1, prefix + "_exit_mode": "hold",
            prefix + "_start": "2028-01-01", prefix + "_months": 12})
    tep = copy.deepcopy(core.TEP_DEFAULT)
    # Explicit parcel-allocation input, independent from construction volume.
    tep["offices"]["total_area"] = 5000
    tep["standalone_retail"]["total_area"] = 5000
    result = core._run_authoritative_model(copy.deepcopy(inputs), copy.deepcopy(tep), [], {})["consolidated"]
    shares = result["land_rent"]["land_exposures"]
    assert len(shares) == 2
    assert [e["share"] for e in shares] == pytest.approx([.5, .5])
    cash_date = date(2031, 1, 1)
    for exposure in shares:
        assert cash_date > date.fromisoformat(exposure["lease_exit"])
        assert set(exposure["monthly"]) == {cash_date.isoformat()}
        assert exposure["monthly"][cash_date.isoformat()] > 0
    prepared = core.prepared_calculation(copy.deepcopy(inputs), copy.deepcopy(tep), [])
    spec = core.nonres_book_spec(prepared, result, "Synthetic separate parcel liabilities")
    office_keys = {o.key for o in core.STANDALONE_OBJECTS if o.product == "offices"}
    content, report = ow.build(result, spec, office_keys)
    assert report["unresolved"] == 0, report["unresolved_examples"]
    if report["verdict"] != ow.PASSED:
        artifact = tmp_path / 'synthetic-mixed-office-retail.xlsx'
        artifact.write_bytes(content)
        cached = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        differences = [dict(zip(('section','metric','book','engine','difference','tolerance','verdict'),row[:7]))
            for row in cached[ow.CHECK_SHEET].iter_rows(min_row=5,values_only=True)
            if len(row) >= 7 and row[6] not in (None,ow.AGREE,'—')]
        artifact.with_suffix('.json').write_text(json.dumps(differences,ensure_ascii=False,indent=2))
        cached.close()
        pytest.fail(f'{report["mismatches"]}; численные расхождения: {artifact.with_suffix(".json")}')
