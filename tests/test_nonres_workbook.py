"""Книга нежилого проекта: живые формулы сходятся с движком.

Владелец (04.10.2026): у нежилого проекта без ДДУ своя книга. Её формулы —
построчный пересказ `developaid_nonres_strategy.object_flows`, а лист «Сверка»
сравнивает итоги формул с итогами движка. Формулы здесь вычисляет pycel — без
Excel; проверка обязана падать на подделке (испорченная вводная книги).

Запуск: python3 -m pytest tests/test_nonres_workbook.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import nonres_workbook as nw  # noqa: E402

pycel = pytest.importorskip("pycel")
openpyxl = pytest.importorskip("openpyxl")

OFFICE = dict(offices_enabled=True, offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
              offices_parking_under_spaces=200, offices_parking_over_spaces=40,
              offices_parking_guest_pct=10)


def _project(nonresidential: bool = True, **over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(OFFICE)
    x.update(over)
    for obj in core.STANDALONE_OBJECTS:
        gba = float(x.get(f"{obj.prefix}_gba_sqm") or 0)
        if not x.get(f"{obj.prefix}_enabled") or gba <= 0:
            continue
        saleable = float(x.get(f"{obj.prefix}_saleable_sqm") or 0)
        t.setdefault(obj.key, {}).update(gns=gba, total_area=round(gba * 0.94, 2),
                                         useful=saleable, saleable=saleable)
    if nonresidential:
        for key in core.MKD_PRODUCTS:
            for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
                if key in t:
                    t[key][col] = 0
        x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    return x, t


def _evaluate(content: bytes, tmp_path: Path, tamper=None) -> tuple[str, list]:
    path = tmp_path / "book.xlsx"
    if tamper:
        book = openpyxl.load_workbook(io.BytesIO(content))
        tamper(book)
        book.save(path)
    else:
        path.write_bytes(content)
    from pycel import ExcelCompiler
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))
    compiler = ExcelCompiler(filename=str(path))
    book = openpyxl.load_workbook(path)
    # Долг строки читает предыдущую — считаем сверху вниз, чтобы не упереться
    # в глубину рекурсии вычислителя.
    for name in book.sheetnames:
        if not name.startswith("Объект"):
            continue
        sheet = book[name]
        for row in range(nw.FIRST_ROW, sheet.max_row + 1):
            for letter, _ in nw.COLUMNS.values():
                value = sheet[f"{letter}{row}"].value
                if isinstance(value, str) and value.startswith("="):
                    compiler.evaluate(f"'{name}'!{letter}{row}")
    checks = book["Сверка"]
    bad = [(checks[f"B{row}"].value, compiler.evaluate(f"Сверка!C{row}"), checks[f"D{row}"].value)
           for row in range(3, checks.max_row + 1)
           if compiler.evaluate(f"Сверка!G{row}") == "РАСХОЖДЕНИЕ"]
    return compiler.evaluate("Сверка!I3"), bad


VARIANTS = {
    "аренда и продажа, аннуитет": dict(offices_strategy="income"),
    "удержание, погашение из NOI": dict(offices_strategy="income", offices_exit_mode="hold",
                                        offices_debt_repayment="sweep"),
    "прямая продажа до ввода": dict(offices_strategy="direct", offices_direct_sale_offset_months=-6,
                                    offices_direct_sale_curve="bell"),
}


@pytest.mark.parametrize("name", list(VARIANTS))
def test_the_book_formulas_agree_with_the_engine(name, tmp_path) -> None:
    x, t = _project(**VARIANTS[name])
    content, filename, meta = core.build_project_workbook(x, t, [], {}, project_name="Офис")
    assert meta.get("nonres_book") is True and "нежилой" in filename
    verdict, bad = _evaluate(content, tmp_path)
    assert bad == [] and verdict == "ПРОЙДЕНО"


def test_a_tampered_book_is_caught(tmp_path) -> None:
    """Подделка: ставка аренды в книге не та, что у движка, — сверка красная."""
    x, t = _project(offices_strategy="income")
    content, _, _ = core.build_project_workbook(x, t, [], {})

    def tamper(book):
        book["Объект 1"][f"B{nw.INPUTS['rent'][0]}"] = book["Объект 1"][f"B{nw.INPUTS['rent'][0]}"].value * 1.1

    verdict, bad = _evaluate(content, tmp_path, tamper)
    assert verdict == "ЕСТЬ РАСХОЖДЕНИЯ"
    assert {"Арендная выручка", "NOI за срок удержания"} <= {label for label, _, _ in bad}


def test_the_book_marks_what_the_engine_counted(tmp_path) -> None:
    x, t = _project(offices_strategy="income")
    content, _, _ = core.build_project_workbook(x, t, [], {})
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book.sheetnames[:2] == ["Свод", "Сверка"] and "Объект 1" in book.sheetnames
    sheet = book["Объект 1"]
    assert sheet[f"C{nw.FIRST_ROW - 2}"].value == "СЧИТАЕТ ДВИЖОК"
    assert str(sheet[f"{nw.COLUMNS['rent'][0]}{nw.FIRST_ROW}"].value).startswith("=")
    assert book["Свод"]["C4"].value == "СЧИТАЕТ ДВИЖОК"


def test_a_project_with_ddu_keeps_the_v4_book() -> None:
    for x, t in (_project(nonresidential=False, offices_strategy="income"),
                 _project(offices_strategy="ddu")):
        _, filename, meta = core.build_project_workbook(x, t, [], {})
        assert not meta.get("nonres_book") and "нежилой" not in filename
