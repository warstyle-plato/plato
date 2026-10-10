"""Книга гостиничного проекта: живые формулы сходятся с движком.

Формулы листа «Расчёт» — построчный пересказ
`developaid_hotel_strategy.hotel_flows`; «USALI по годам» и «Итоги» — их
свод; «Сверка» сравнивает итоги книги с движком. Формулы вычисляет pycel —
без Excel. Проверка обязана падать на подделке (испорченная вводная книги).

Запуск: python3 -m pytest tests/test_hotel_workbook.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hotel_presets  # noqa: E402
import hotel_workbook as hw  # noqa: E402
import main_legacy as core  # noqa: E402

pycel = pytest.importorskip("pycel")
openpyxl = pytest.importorskip("openpyxl")

ALLOWED = {"IF", "AND", "OR", "MIN", "MAX", "SUM", "SUMIF", "COUNT", "COUNTIF", "ABS"}


def _project(preset: str | None = "hotel1", **over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = core.PROJECT_KIND_HOTEL
    if preset:
        x = hotel_presets.apply_preset(x, preset)
    x.update(over)
    return x, t


def _book(**over) -> tuple[bytes, str, dict]:
    x, t = _project(**over)
    return core.build_project_workbook(x, t, [], {}, project_name="Отель")


def _evaluate(content: bytes, tmp_path: Path, tamper=None) -> tuple[str, list]:
    path = tmp_path / "hotel.xlsx"
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
    # Долг и налог строки читают предыдущую — считаем сверху вниз, чтобы не
    # упереться в глубину рекурсии вычислителя.
    sheet = book[hw.CALC_SHEET]
    for row in range(hw.FIRST_ROW, sheet.max_row + 1):
        for letter, _ in hw.COLUMNS.values():
            value = sheet[f"{letter}{row}"].value
            if isinstance(value, str) and value.startswith("="):
                compiler.evaluate(f"'{hw.CALC_SHEET}'!{letter}{row}")
    checks = book[hw.CHECK_SHEET]
    bad = [(checks[f"A{row}"].value, compiler.evaluate(f"'{hw.CHECK_SHEET}'!B{row}"),
            checks[f"C{row}"].value)
           for row in range(3, checks.max_row + 1)
           if compiler.evaluate(f"'{hw.CHECK_SHEET}'!F{row}") not in ("сходится", "—")]
    return compiler.evaluate(f"'{hw.CHECK_SHEET}'!H3"), bad


@pytest.fixture(scope="module")
def dombai() -> tuple[bytes, str, dict]:
    return _book(hotel_hold_years=6)


def test_the_kind_chooses_the_hotel_book(dombai) -> None:
    content, name, meta = dombai
    assert name.startswith("DevelopAid_гостиница_") and meta["hotel_book"]
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book.sheetnames[:2] == [hw.TOTALS_SHEET, hw.INPUTS_SHEET]
    assert {hw.CALC_SHEET, hw.USALI_SHEET, hw.CHECK_SHEET} <= set(book.sheetnames)


def test_the_book_agrees_with_the_engine(dombai, tmp_path) -> None:
    verdict, bad = _evaluate(dombai[0], tmp_path)
    assert bad == [] and verdict == "ПРОЙДЕНО"


def test_another_financing_and_exit_also_agree(tmp_path) -> None:
    """Обычный кредит с лимитом и отсрочкой, аннуитет, удержание по ставке."""
    content, _, _ = _book(hotel_hold_years=5, hotel_financing="commercial",
                          hotel_loan_spread_pp=4, hotel_repayment="annuity",
                          hotel_loan_limit_th_per_key=9000, hotel_grace_months=30,
                          hotel_exit_mode="hold", hotel_valuation="cap_rate",
                          hotel_exit_cap_pct=10, hotel_vat_relief_years=0)
    verdict, bad = _evaluate(content, tmp_path)
    assert bad == [] and verdict == "ПРОЙДЕНО"


def test_the_check_fails_on_a_forged_input(dombai, tmp_path) -> None:
    def forge(book) -> None:
        sheet = book[hw.INPUTS_SHEET]
        cell = f"C{hw._ROWS['adr']}"
        sheet[cell] = float(sheet[cell].value) * 1.05

    verdict, bad = _evaluate(dombai[0], tmp_path, forge)
    assert verdict == "ЕСТЬ РАСХОЖДЕНИЯ"
    assert any(label == "Выручка всего" for label, _, _ in bad)


def test_inputs_carry_their_origin(dombai) -> None:
    book = openpyxl.load_workbook(io.BytesIO(dombai[0]))
    sheet = book[hw.INPUTS_SHEET]
    origin = {sheet[f"E{row}"].value: sheet[f"H{row}"].value for row in range(4, 4 + 60)
              if sheet[f"E{row}"].value}
    assert origin["Стартовая загрузка"] == "ориентир: Отель 1 5*, Предпосылки!E393"
    x, t = _project(hotel_hold_years=6)
    del x["hotel_property_tax_pct"]
    content, _, _ = core.build_project_workbook(x, t, [], {}, project_name="Отель")
    sheet = openpyxl.load_workbook(io.BytesIO(content))[hw.INPUTS_SHEET]
    origin = {sheet[f"E{row}"].value: sheet[f"H{row}"].value for row in range(4, 4 + 60)
              if sheet[f"E{row}"].value}
    assert origin["Налог на имущество"].startswith("умолчание: НК РФ")


def test_a_project_saved_with_the_old_names_prints_the_current_ones() -> None:
    x, t = _project(hotel_hold_years=6)
    x["hotel_origins"] = {
        k: {**v, "preset": "dombai", "text": v["text"].replace("Отель 1", "Домбай"),
            "cells": [c.replace("hotel1:", "dombai:") for c in v["cells"]]}
        for k, v in x["hotel_origins"].items()}
    content, _, _ = core.build_project_workbook(x, t, [], {}, project_name="Отель")
    sheet = openpyxl.load_workbook(io.BytesIO(content))[hw.INPUTS_SHEET]
    texts = [str(sheet[f"H{row}"].value or "") for row in range(4, 4 + 60)]
    assert any(text.startswith("ориентир: Отель 1 5*") for text in texts)
    assert not any("Домбай" in text for text in texts)


def test_the_formulas_use_only_what_the_checker_computes(dombai) -> None:
    book = openpyxl.load_workbook(io.BytesIO(dombai[0]))
    used: set[str] = set()
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    used |= set(re.findall(r"([A-Z][A-Z0-9.]*)\(", cell.value))
    assert used <= ALLOWED, used - ALLOWED


def test_an_empty_hotel_book_names_the_gaps() -> None:
    content, _, meta = _book(preset=None)
    book = openpyxl.load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Гостиница"]
    assert "не заданы" in book["Гостиница"]["A1"].value
    assert any("ADR" in item for item in meta["missing"])
