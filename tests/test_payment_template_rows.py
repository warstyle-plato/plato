"""A cached work-label lookup zero is different from a zero payment amount."""
import datetime as dt
import io
import re
import zipfile

import openpyxl

import developaid_actuals as actuals
import developaid_monitor_contract_risk as risk
from developaid_monitor_contracts import _reference_key


def payment_book(path, rows):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = actuals._PAYMENTS_SHEET
    for line, cells in rows.items():
        sheet.cell(line, 1, line - 9)
        for column, value in cells.items():
            sheet[f"{column}{line}"] = value
    raw = io.BytesIO()
    book.save(raw)
    book.close()
    # openpyxl does not calculate formula results. Preserve the native Excel
    # situation: H is a prefilled lookup formula with a saved numeric zero.
    output = io.BytesIO()
    with zipfile.ZipFile(raw) as source, zipfile.ZipFile(output, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode()
                text = re.sub(r'(<c r="H\d+"[^>]*><f>[^<]+</f><v>)</v>',
                              r'\g<1>0</v>', text)
                data = text.encode()
            target.writestr(item, data)
    path.write_bytes(output.getvalue())
    return path


DAY = dt.date(2026, 10, 31)
CONTRACT_DAY = dt.date(2024, 1, 2)
LOOKUP = '=IFERROR(VLOOKUP(G10,A1:B2,2,FALSE),0)'


def test_unused_lookup_rows_do_not_invent_incomplete_payments(tmp_path):
    path = payment_book(tmp_path / "rss.xlsx", {
        10: {"H": LOOKUP},
        11: {"I": DAY, "J": 125, "G": "2.6", "K": "Заемные средства"},
        12: {"I": DAY, "J": 0, "G": "2.6", "K": "Заемные средства"},
        13: {"I": DAY, "J": -25, "G": "2.6", "K": "Заемные средства"},
    })
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        assert book[actuals._PAYMENTS_SHEET]["H10"].value == 0
    finally:
        book.close()
    book = openpyxl.load_workbook(path, data_only=False, read_only=True)
    try:
        assert book[actuals._PAYMENTS_SHEET]["H10"].data_type == "f"
    finally:
        book.close()
    strict = actuals.read_payments(path, include_incomplete=True)
    assert [row["source_row"] for row in strict["rows"]] == [11, 12, 13]
    assert [row["amount"] for row in strict["rows"]] == [125, 0, -25]
    assert strict["total"] == 100
    legacy = actuals.read_payments(path)
    assert [row["amount"] for row in legacy["rows"]] == [125, -25]
    assert legacy["total"] == strict["total"]


def test_any_other_payment_evidence_keeps_the_incomplete_row(tmp_path):
    path = payment_book(tmp_path / "rss.xlsx", {
        10: {"H": 0},
        11: {"H": 0, "I": DAY, "G": "2.6", "K": "Заемные средства"},
        12: {"H": 0, "B": "Учебный подрядчик"},
        13: {"H": 0, "J": 0},
        14: {"H": "Неполная строка"},
        15: {"H": "0"},
        16: {"H": False},
    })
    strict = actuals.read_payments(path, include_incomplete=True)
    assert [row["source_row"] for row in strict["rows"]] == list(range(11, 17))
    assert [row["amount"] for row in strict["rows"]] == [None, None, 0, None, None, None]
    assert strict["total"] is None


def test_unused_template_does_not_make_a_complete_contract_payment_unknown(tmp_path):
    path = payment_book(tmp_path / "rss.xlsx", {
        10: {"B": "ООО Учебный подрядчик", "C": "Д-1", "D": CONTRACT_DAY,
             "F": "Аванс", "G": "2.6", "I": DAY, "J": 125,
             "K": "Заемные средства"},
        11: {"H": LOOKUP},
    })
    payments, warnings = risk.payments(path, DAY)
    assert not warnings
    row = {"contractor": "ООО Учебный подрядчик", "contract": "Д-1",
           "contract_date": CONTRACT_DAY, "completed": 100}
    advance = risk.advance(row, payments, reference_key=_reference_key,
                           completed_basis="with_vat")
    assert advance["paid"] == advance["confirmed_paid"] == 125
    assert advance["unworked"] == 25
    assert advance["unmatched_candidates"] == 0
    assert advance["payments_count"] == 1
    assert advance["sources"][0]["row"] == 10
