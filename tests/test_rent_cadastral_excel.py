"""Editable cadastral estimates and daily rent use one date in the workbook."""
from datetime import date, timedelta
import io
import zipfile

import openpyxl
import pytest

import developaid_land_rent as rent
import v4_land_rent as book
from xlsx_eval import Evaluator

START, END, CHANGE = date(2028, 1, 1), date(2028, 7, 1), date(2028, 2, 17)
RELEASE = [date(2028, month, 11) for month in range(2, 6)] + [END]
NUMBERS = ["77:01:0000001:11", "77:01:0000001:12"]


def settings(region):
    rows = [{"cadastral_number": n, "area_sqm": area,
             "cadastral_value_rub": value * 1e6,
             "cadastral_value_new_rub": area * 10000,
             "upks_target": 10000, "cadastral_value_date": "2026-01-01"}
            for n, area, value in zip(NUMBERS, (10000, 20000), (40, 60))]
    result = dict(land_right="lease", vri_region=region,
        land_rent_mode="msk_mkd_3_2" if region == "msk" else "mo_housing_new_2026",
        land_rent_preset_confirmed=True, land_rent_regime_start=START.isoformat(),
        land_rent_contract_date=START.isoformat(), land_rent_public_scope="regional",
        land_rent_grant_basis="ordinary_nonauction", land_rent_premium_status="not_applicable",
        land_rent_cadastral_parameters=[dict(number=n, area_sqm=area, upks_rub_sqm=10000,
            source="Синтетический земельный показатель", source_date="2026-01-01")
            for n, area in zip(NUMBERS, (10000, 20000))])
    if region == "mo":
        result["_mo_calc"] = {"vri": {"parcels": rows}}
    else:
        result["_glavapu_import"] = {"recognized": NUMBERS, "normalized": {"site_area_ha": 3}, "mappings": {}}
        result["_land_lookup"] = {"results": [{**r, "found": True, "kind": "land",
            "cadastral_value_mln": r["cadastral_value_rub"] / 1e6} for r in rows]}
    return result


def workbook(inputs, result):
    """Use the real XML writer, real formula interpreter and a small month axis."""
    wb = openpyxl.Workbook()
    wb.active.title = book.SHEET
    buf = io.BytesIO()
    wb.save(buf)
    layout = {}
    payload = book.build_sheet(inputs, result,
        {name: 0 for name in ("amount", "date", "input", "input_date", "input_text")},
        project_start_formula=str(book._serial(START)), rve_formula=str(book._serial(END)),
        project_end_formula=str(book._serial(END)), months=6,
        month_formulas=[str(book._serial(date(2028, month, 1))) for month in range(1, 7)],
        phase_rve_formulas=[str(book._serial(day)) for day in RELEASE], layout=layout)
    out = io.BytesIO()
    with zipfile.ZipFile(buf) as src, zipfile.ZipFile(out, "w") as dest:
        for name in src.namelist():
            dest.writestr(name, payload if name == "xl/worksheets/sheet1.xml" else src.read(name))
    return openpyxl.load_workbook(io.BytesIO(out.getvalue()), data_only=False), layout


def calculated(inputs):
    return rent.build(inputs, START, END, END, cadastral_switch=CHANGE,
        phase_land=[{"share": .2, "rve": day.isoformat()} for day in RELEASE])


@pytest.mark.parametrize("region", ["msk", "mo"])
@pytest.mark.parametrize("relief", [0, 100])
def test_each_month_and_five_queues_match_daily_bases_despite_zero_fee(region, relief):
    inputs = settings(region)
    inputs.update(land_rights_cost_mln=50, vri_relief_mode="percent", vri_relief_pct=relief)
    result = calculated(inputs)
    wb, layout = workbook(inputs, result)
    ev = Evaluator(wb)
    expected = {}
    day = START
    rate = .015 if region == "msk" else .06
    while day < END:
        share = .2 * sum(day < release for release in RELEASE)
        base = 300e6 if day >= CHANGE else 100e6
        month = day.replace(day=1).isoformat()
        expected[month] = expected.get(month, 0) + share * base * rate / 366
        day += timedelta(days=1)
    for month, amount in expected.items():
        col = openpyxl.utils.get_column_letter(3 + int(month[5:7]))
        assert result["accrual_monthly"].get(month, 0) == pytest.approx(amount, abs=.01)
        assert ev.cell(book.SHEET, f"{col}4") * 1e6 == pytest.approx(amount, abs=.01)
    assert ev.cell(book.SHEET, "B9") == 100
    assert ev.cell(book.SHEET, f"B{layout['cadastral_target_row']}") == 300
    assert ev.cell(book.SHEET, f"B{layout['cadastral_change_row']}") == book._serial(CHANGE)
    assert len(layout["phase_cash_rows"]) == 5
    assert "Расчётная" in ev.cell(book.SHEET, f"A{layout['cadastral_target_row']}")


def test_workbook_parameter_edit_recalculates_future_months_and_keeps_missing_unknown():
    inputs = settings("msk")
    result = calculated(inputs)
    wb, layout = workbook(inputs, result)
    before = Evaluator(wb)
    jan, mar = before.cell(book.SHEET, "D4"), before.cell(book.SHEET, "F4")
    row = layout["cadastral_parameter_rows"][0]
    wb[book.SHEET][f"C{row}"] = 20000
    after = Evaluator(wb)
    assert after.cell(book.SHEET, "D4") == jan
    assert after.cell(book.SHEET, "F4") == pytest.approx(mar * 4/3)
    assert after.cell(book.SHEET, f"B{layout['cadastral_target_row']}") == 400
    assert "Расчётная" in after.cell(book.SHEET, f"A{layout['cadastral_target_row']}")
    wb[book.SHEET][f"B{layout['cadastral_change_row']}"] = book._serial(date(2028, 3, 17))
    moved = Evaluator(wb)
    # February has 10 days with all five shares, then 19 days with four.
    assert moved.cell(book.SHEET, "E4") == pytest.approx(100 * .015 * (10 + 19*.8) / 366)
    assert moved.cell(book.SHEET, "D4") == jan
    wb[book.SHEET][f"C{row}"] = None
    unknown = Evaluator(wb)
    assert unknown.cell(book.SHEET, f"D{row}") == ""
    assert unknown.cell(book.SHEET, f"B{layout['cadastral_target_row']}") == ""
    assert unknown.cell(book.SHEET, "L18") == 0
    assert "неизвестна" in unknown.cell(book.SHEET, f"C{layout['cadastral_change_row']+1}")
    wb[book.SHEET][f"B{layout['cadastral_target_row']}"] = 500
    override = Evaluator(wb)
    assert "изменённая вручную" in override.cell(book.SHEET, f"A{layout['cadastral_target_row']}")
    assert override.cell(book.SHEET, f"C{layout['cadastral_target_row']}") == "Изменено вручную в этой книге"


def test_confirmed_official_total_survives_an_available_estimate_and_is_labelled_separately():
    inputs = settings("msk")
    inputs.update(land_rent_cadastral_target_mln=450,
        land_rent_cadastral_target_kind="official_egrn",
        land_rent_cadastral_target_source="Синтетическая выписка ЕГРН",
        land_rent_cadastral_target_source_date="2028-02-10",
        _field_origin={"inputs.land_rent_cadastral_target_mln": {"source": "manual", "kind": "manual"}})
    result = calculated(inputs)
    wb, layout = workbook(inputs, result)
    target = layout["cadastral_target_row"]
    assert wb[book.SHEET][f"B{target}"].value == 450
    ev = Evaluator(wb)
    assert ev.cell(book.SHEET, f"A{target}") == "Официальная новая КС из ЕГРН, млн ₽"
    assert "Синтетическая выписка ЕГРН" in ev.cell(book.SHEET, f"C{target}")
    assert wb[book.SHEET][f"D{target}"].value == "2028-02-10"
    wb[book.SHEET][f"B{target}"] = 500
    assert Evaluator(wb).cell(book.SHEET, f"C{target}") == "Изменено вручную в этой книге"
    assert "изменённая вручную" in Evaluator(wb).cell(book.SHEET, f"A{target}")


def test_selected_parcel_only_and_equal_new_base_keep_the_event_date():
    inputs = settings("msk")
    inputs["land_rent_parcels_excluded"] = [NUMBERS[1]]
    # The future and current value of the remaining parcel are both 40 mln.
    inputs["land_rent_cadastral_parameters"][0]["upks_rub_sqm"] = 4000
    result = calculated(inputs)
    wb, layout = workbook(inputs, result)
    assert len(layout["cadastral_parameter_rows"]) == 1
    ev = Evaluator(wb)
    assert ev.cell(book.SHEET, "B9") == 40
    assert ev.cell(book.SHEET, f"B{layout['cadastral_target_row']}") == 40
    assert ev.cell(book.SHEET, f"B{layout['cadastral_change_row']}") == book._serial(CHANGE)


def test_saved_mo_estimate_is_preserved_when_its_displayed_parameters_were_rounded():
    inputs = settings("mo")
    rows = inputs["_mo_calc"]["vri"]["parcels"]
    rows[0].update(area_sqm=10000.12, upks_target=10000.12,
                   cadastral_value_new_rub=100002460.02)
    result = calculated(inputs)
    wb, layout = workbook(inputs, result)
    first = layout["cadastral_parameter_rows"][0]
    target = layout["cadastral_target_row"]
    ev = Evaluator(wb)
    assert wb[book.SHEET][f"D{first}"].value == 100.00246002
    assert ev.cell(book.SHEET, f"B{target}") == pytest.approx(result["cadastral_switch"]["target_mln"], abs=1e-9)
    # Rounded diagnostic parameters cannot rewrite the saved authoritative
    # estimate. The future value itself remains explicitly editable.
    wb[book.SHEET][f"C{first}"] = 1
    assert Evaluator(wb).cell(book.SHEET, f"B{target}") == ev.cell(book.SHEET, f"B{target}")
    wb[book.SHEET][f"D{first}"] = 150
    assert Evaluator(wb).cell(book.SHEET, f"B{target}") == 350


def test_export_keeps_methodology_date_and_the_parcels_target_use():
    inputs = settings("msk")
    result = calculated(inputs)
    methodology = {"text": "Синтетическая проверка формулы по релевантной группе оценки",
        "url": "https://publication.pravo.gov.ru/", "as_of": "2026-11-17"}
    result["cadastral_estimate"]["methodology"] = methodology
    result["cadastral_estimate"]["parcels"][0]["target_use"] = "2.6: многоэтажная жилая застройка"
    result["cadastral_estimate"]["parcels"][0]["valuation_territory"] = "Синтетическая территория оценки"
    wb, layout = workbook(inputs, result)
    values = [cell.value for row in wb[book.SHEET] for cell in row]
    assert all(value in values for value in methodology.values())
    first = layout["cadastral_parameter_rows"][0]
    assert wb[book.SHEET][f"G{first}"].value == "2.6: многоэтажная жилая застройка"
    assert wb[book.SHEET][f"H{first}"].value == "Синтетическая территория оценки"


def test_annual_contract_amount_does_not_require_a_future_cadastral_value():
    inputs = dict(land_right="lease", vri_region="msk", land_rent_mode="manual",
        land_rent_base_kind="annual_amount", land_rent_annual_base_mln=10,
        land_rent_regime_start=START.isoformat(), land_rent_rates=[{"year": 1, "rate_pct": 100}],
        land_rent_tail_rule="repeat_last", land_rent_vat_treatment="public_exempt",
        land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0")
    result = calculated(inputs)
    assert result["financial_complete"], result["financial_missing"]
    assert result["cadastral_change"]["date"] == CHANGE.isoformat()
    assert result["cadastral_switch"] is None
    wb, _ = workbook(inputs, result)
    ev = Evaluator(wb)
    assert ev.cell(book.SHEET, "L18") == 1
    assert ev.cell(book.SHEET, "B19") * 1e6 == pytest.approx(result["cash_total"], abs=.01)
    assert ev.cell(book.SHEET, "B18") * 1e6 == pytest.approx(result["total"], abs=.01)
    for month in range(1, 7):
        key = date(2028, month, 1).isoformat()
        col = openpyxl.utils.get_column_letter(3 + month)
        assert ev.cell(book.SHEET, f"{col}4") * 1e6 == pytest.approx(result["accrual_monthly"].get(key, 0), abs=.01)
        assert ev.cell(book.SHEET, f"{col}6") * 1e6 == pytest.approx(result["monthly"].get(key, 0), abs=.01)
