"""Cash excludes retained value; sale and hold remain independent Excel variants."""
import io

import pytest

from test_office_workbook import _book, _row, openpyxl, ow
from report_kpi_hints import REPORT_KPI_HINTS


@pytest.fixture(scope="module")
def held_book():
    return _book("аренда и удержание, погашение из NOI")[0]


def test_both_exit_variants_stay_distinct_when_the_excel_input_changes(held_book):
    book = openpyxl.load_workbook(io.BytesIO(held_book))
    report = book[ow.REPORT_SHEET]
    header = next(cell for row in report for cell in row if cell.value == "Показатель")
    cached = openpyxl.load_workbook(io.BytesIO(held_book), data_only=True)
    assert cached[ow.REPORT_SHEET][f"E{header.row}"].value == "Аренда и удержание здания"
    selected = _row(report, "Способ, выбранный в проекте")
    winner = _row(report, "Выгоднее по NPV среди вариантов книги")
    # Force rent to win without depending on a particular fixture's economics.
    for sheet_name, value in (("CF_ДДУ", -3), ("CF_ПДКП", -2), ("CF_Продажа", -1),
                              ("CF_Выход_продажа", -1), ("CF_Аренда", 1)):
        sheet = book[sheet_name]
        sheet[f"B{_row(sheet, 'NPV проекта')}"] = value
    inputs = book[ow.INPUTS_SHEET]
    exit_row = _row(inputs, "Выход в конце удержания")
    exit_cell = next(cell for cell in inputs[exit_row] if cell.value == ow.EXIT[ow.ns.EXIT_HOLD])
    for mode in (ow.ns.EXIT_HOLD, ow.ns.EXIT_SALE):
        exit_cell.value = ow.EXIT[mode]
        evaluator = ow.Evaluator(book)
        for address in (f"E{header.row}", f"B{selected}", f"B{winner}"):
            assert evaluator.cell(ow.REPORT_SHEET, address) == "Аренда и удержание здания"
        assert evaluator.cell(ow.REPORT_SHEET, f"F{header.row}") == "Аренда и продажа здания"


def test_receipts_exclude_valuation_but_project_npv_keeps_it(held_book):
    book = openpyxl.load_workbook(io.BytesIO(held_book))
    evaluator = ow.evaluate(book)
    sheet = book["CF_Аренда"]
    value = lambda label: evaluator.cell(sheet.title, f"B{_row(sheet, label)}")
    receipts = value("Выручка деньгами")
    residual = value("Оценка удержанного здания (не деньги)")
    assert residual > 0
    assert value("Выручка") == pytest.approx(receipts + residual)
    expected = (receipts + residual - value("Расходы продаж и эксплуатации")
                - value("НДС к уплате") - value("Затраты на создание") - value("Налог на прибыль к уплате"))
    assert value("Поток проекта до кредита") == pytest.approx(expected)
    assert ow.verdict(evaluator) == (ow.PASSED, [])


def test_shared_strategy_hints_explain_non_cash_valuation():
    for key in ("strategy_revenue", "strategy_net_profit", "strategy_npv"):
        assert "оценк" in REPORT_KPI_HINTS[key]
    assert "не поступление денег" in REPORT_KPI_HINTS["strategy_revenue"]
