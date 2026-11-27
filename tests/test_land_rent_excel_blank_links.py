"""Excel evaluates every AND argument, including arithmetic on linked empty text."""
from datetime import date
from xml.etree import ElementTree as ET

import openpyxl
import pytest

import developaid_land_rent as rent
import v4_land_rent as book
import xlsx_eval


@pytest.fixture
def excel_text_numbers(monkeypatch):
    """Keep the production evaluator, but do not coerce formula text to zero.

    Excel EDATE/ROUND/arithmetic reject a reference to a formula returning
    empty text. A genuinely empty referenced cell is still numeric zero.
    This narrow fixture is not a claim to run Microsoft Excel.
    """
    original = xlsx_eval._as_number

    def number(value):
        if isinstance(value, str) and value == "":
            raise xlsx_eval.ExcelError("#VALUE!: empty formula text is not a number")
        return original(value)

    monkeypatch.setattr(xlsx_eval, "_as_number", number)


def _sheet(workbook, name, xml):
    ns = {"m": book.NS}
    sheet = workbook.create_sheet(name)
    for cell in ET.fromstring(xml).findall("m:sheetData/m:row/m:c", ns):
        formula, value = cell.find("m:f", ns), cell.find("m:v", ns)
        if formula is not None:
            raw = "=" + formula.text
        elif cell.get("t") == "inlineStr":
            raw = "".join(cell.find("m:is", ns).itertext())
        elif value is not None and value.text is not None:
            raw = float(value.text)
        else:
            raw = None
        sheet[cell.get("r")] = raw
    return sheet


def _linked_book(*, lease=False):
    start, commissioning, end = date(2027, 1, 1), date(2027, 3, 1), date(2027, 7, 1)
    inputs = {"land_right": "owned", "land_rent_mode": "not_applicable"}
    if lease:
        inputs = {"land_right": "lease", "land_rent_mode": "manual", "vri_region": "msk",
                  "land_rent_cadastral_mln": 100, "land_rent_regime_start": start.isoformat(),
                  "land_rent_rates": [{"year": 1, "rate_pct": 1}],
                  "land_rent_tail_rule": "repeat_last", "land_rent_first_year_relation": "regular_only"}
    # The exposed retained parcel stays leased through the operating horizon;
    # compare that full interval with the canonical annual accrual.
    result = rent.build(inputs, start, end, end)
    result["land_exposures"] = [{"id": "office", "name": "Office", "share": 1,
                                 "retained": True, "total_area": 1000,
                                 "commissioning": commissioning.isoformat(), "lease_exit": end.isoformat()}]
    wb = openpyxl.Workbook()
    calendar = wb.active
    calendar.title = "Calendar"
    calendar.append([start, commissioning, end])
    options = dict(project_start_formula="'Calendar'!$A$1", rve_formula="'Calendar'!$B$1",
                   project_end_formula="'Calendar'!$C$1", months=6,
                   month_formulas=[f"EDATE('Calendar'!$A$1,{index})" for index in range(6)],
                   exposure_formulas={"office": {"share": "1", "commissioning": "'Calendar'!$B$1",
                                                  "lease_exit": "'Calendar'!$C$1"}})
    styles = dict.fromkeys(("amount", "date", "input", "input_date", "input_text"), 0)
    _sheet(wb, book.SHEET, book.build_sheet(inputs, result, styles, **options))
    layout = {}
    clone = _sheet(wb, "Аренда ЗУ · r", book.build_sheet(inputs, result, styles,
                   master_terms_sheet=book.SHEET, layout=layout, **options))
    return wb, clone, layout, result


def test_semantics_fixture_rejects_eager_and_but_preserves_real_blank(excel_text_numbers):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["B1"] = '=""', "=ROUND(A2,0)"
    ws["C1"] = "=IF(AND(COUNT(A1)=1,A1=ROUND(A1,0)),1,0)"
    ev = xlsx_eval.Evaluator(wb)
    assert ev.cell(ws.title, "B1") == 0
    assert ev.cell(ws.title, "A1") == ""
    with pytest.raises(xlsx_eval.ExcelError, match="#VALUE!"):
        ev.cell(ws.title, "C1")


@pytest.mark.parametrize("source", [None, '=""', "not a date"])
def test_linked_missing_contract_date_keeps_cash_cells_readable(source, excel_text_numbers):
    wb, ws, _, _ = _linked_book()
    wb[book.SHEET]["B10"] = source
    ev = xlsx_eval.Evaluator(wb)
    assert ev.cell(ws.title, "B10") == ""
    assert ev.cell(ws.title, "F17") == 0
    assert ev.cell(ws.title, "D6") == 0
    assert ev.cell(ws.title, "B19") == 0
    assert wb[book.SHEET]["B10"].value == source


@pytest.mark.parametrize("offset,amount,expected_error", [(None, None, 0), ('=""', None, 0),
                                                       ("invalid", 1, 1), (None, 1, 1), (0, 1, 0)])
def test_linked_payment_rows_guard_arithmetic_before_validation(offset, amount, expected_error,
                                                               excel_text_numbers):
    wb, ws, _, _ = _linked_book(lease=True)
    master = wb[book.SHEET]
    master["A125"], master["C125"] = offset, amount
    ev = xlsx_eval.Evaluator(wb)
    assert ev.cell(ws.title, "G125") == expected_error
    if offset == 0 and amount:
        assert ev.cell(ws.title, "H125") == date(2027, 2, 1)
    else:
        assert ev.cell(ws.title, "H125") == 0
    assert master["A125"].value == offset


def test_retained_zero_source_never_multiplies_a_missing_base(excel_text_numbers):
    wb, ws, layout, _ = _linked_book()
    ev = xlsx_eval.Evaluator(wb)
    assert ev.cell(ws.title, "B9") == ""
    row = layout["exposure_rows"]["office"]["construction_accrual"]
    assert ev.cell(ws.title, f"D{row}") == 0
    assert ev.cell(ws.title, f"D{row+3}") == 0  # operating accrual


@pytest.mark.parametrize("optional_date", [None, '=""'])
def test_complete_lease_matches_canonical_and_keeps_missing_source_text(optional_date, excel_text_numbers):
    wb, ws, layout, result = _linked_book(lease=True)
    wb[book.SHEET]["L15"] = optional_date
    ev = xlsx_eval.Evaluator(wb)
    assert ev.cell(book.SHEET, "I20") == "Заданы"
    assert ev.cell(book.SHEET, "B17") == 1
    assert ev.cell(ws.title, "L15") == ""
    assert ev.cell(ws.title, "I20") == "Заданы"
    assert ev.cell(ws.title, "B17") == 1
    assert ev.cell(ws.title, "B19") * 1e6 == pytest.approx(result["known_total"], abs=.01)
    row = layout["exposure_rows"]["office"]["construction_accrual"]
    assert ev.cell(ws.title, f"D{row}") > 0
    wb[book.SHEET]["B9"] = None
    ev = xlsx_eval.Evaluator(wb)
    assert ev.cell(ws.title, "B17") == 0
    assert ev.cell(ws.title, f"D{row}") == 0  # SUM ignores the explicitly unknown segments.
    dev_ref = ws[f"D{row}"].value.removeprefix("=SUM(").split(":", 1)[0]
    assert ev.cell(ws.title, dev_ref) == "Не рассчитано"
