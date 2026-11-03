"""Непонятая формула не превращается в ноль внутри IFERROR.

Ревизия книги 29.09.2026: в сохранённых значениях (их читают Telegram, Quick
Look, телефон) стояли нулями все темпы продаж ОТЧЕТА, «Статус» строк темпов и
ставки БРИДЖ/ПФ на CF. Excel считал их верно. Причина — вычислитель в IFERROR
ловил и свой собственный пробел («не число: [массив]» — арифметику диапазонов
он не умел) и отдавал запасное значение, то есть ноль. Правило кэша «непонятое
остаётся пустым, а не врёт» обходилось через IFERROR.

Отсюда два утверждения:
* IFERROR ловит ошибки, которые дал бы Excel (#VALUE!, #N/A, #DIV/0!), но не
  пробел вычислителя;
* арифметика диапазонов считается так же, как в Excel, включая растяжение
  строки на блок, — и на собранной книге темпы продаж не нули.

Запуск: python3 -m pytest tests/test_the_cache_does_not_turn_gaps_into_zeros.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xlsx_eval import Evaluator, FormulaError  # noqa: E402


def _sheet(formulas: dict[str, str]):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Л"
    for column, values in (("A", (1, 2, 3)), ("B", (10, 20, 30)), ("C", (0, 5, 0))):
        for row, value in enumerate(values, start=1):
            sheet[f"{column}{row}"] = value
    # Строка из трёх и блок 2×3 — для растяжения строки на блок.
    for column, value in zip("DEF", (1, 2, 3)):
        sheet[f"{column}1"] = value
    for row in (2, 3):
        for column, value in zip("DEF", (10, 20, 30)):
            sheet[f"{column}{row}"] = value * row
    sheet["G1"] = "подпись"
    for coord, formula in formulas.items():
        sheet[coord] = formula
    return Evaluator(book)


def test_range_arithmetic_is_elementwise():
    ev = _sheet({"H1": "=SUMPRODUCT((A1:A3+B1:B3)*A1:A3)",
                 "H2": "=SUMPRODUCT(B1:B3,--(C1:C3>0))",
                 "H3": "=SUMPRODUCT(-A1:A3)"})
    assert ev.cell("Л", "H1") == 11 * 1 + 22 * 2 + 33 * 3
    assert ev.cell("Л", "H2") == 20
    assert ev.cell("Л", "H3") == -6


def test_a_row_stretches_over_a_block_like_excel():
    """1×3 + 2×3 = 2×3: строка складывается с каждой строкой блока."""
    ev = _sheet({"H1": "=SUMPRODUCT(D1:F1+D2:F3)"})
    assert ev.cell("Л", "H1") == 2 * 6 + (20 + 40 + 60) + (30 + 60 + 90)


def test_iferror_still_catches_what_excel_would_catch():
    ev = _sheet({"H1": "=IFERROR(A1/0,7)",
                 "H2": "=IFERROR(G1*2,8)",
                 "H3": '=IFERROR(MATCH("нет",G1:G1,0),9)'})
    assert ev.cell("Л", "H1") == 7
    assert ev.cell("Л", "H2") == 8
    assert ev.cell("Л", "H3") == 9


def test_iferror_does_not_hide_an_evaluator_gap():
    """Пробел вычислителя обязан дойти до кэша, а тот оставит клетку пустой.

    Контрпример: неизвестная функция внутри IFERROR. На прежнем вычислителе
    здесь выходил ноль — ровно та болезнь, что стояла в ОТЧЕТЕ.
    """
    ev = _sheet({"H1": "=IFERROR(NOSUCHFUNCTION(A1),0)",
                 "H2": "=IFERROR(SUMPRODUCT(A1:A3*D2:F3),0)"})
    with pytest.raises(FormulaError):
        ev.cell("Л", "H1")
    with pytest.raises(FormulaError):
        ev.cell("Л", "H2")


@pytest.fixture(scope="module")
def default_book():
    sys.setrecursionlimit(400000)
    import main as wrapper
    core = wrapper.core
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    content, _, meta = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS), tep, [], {}, cache_values=True)
    import io
    return openpyxl.load_workbook(io.BytesIO(content), data_only=True), meta


def test_sales_pace_is_not_a_cached_zero(default_book):
    """В дефолтном проекте квартиры продаются — темп не может быть нулём."""
    book, meta = default_book
    assert not [m for m in meta.get("missing") or [] if "сохранённые значения" in str(m)]
    report = book["ОТЧЕТ"]
    for coord in ("B65", "B66", "B67", "F67", "G20"):
        value = report[coord].value
        assert isinstance(value, (int, float)) and value > 0, (coord, value)
    for sheet in ("CF_1",):
        for coord in ("B31", "B41"):
            value = book[sheet][coord].value
            assert isinstance(value, (int, float)) and value > 0, (sheet, coord, value)
