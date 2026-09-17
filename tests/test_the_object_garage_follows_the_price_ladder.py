# -*- coding: utf-8 -*-
"""Гараж объекта продаётся по той же лестнице цены, что и сам объект.

Движок ведёт места гаража ЛЕСТНИЦЕЙ: `sell_object_parking(..., plan["factor"])`
передаёт им множитель объекта, а `sales_schedule` при заданной лестнице
ежемесячный рост до РВЭ не применяет вовсе. Книга лестницу получала только в
строке «Цена реализации» (23/51/141), а строка «Паркинг объекта — выручка»
(33/61/151) продолжала начислять `(1+рост)^месяцев` — методика расходилась с
первого же заданного этапа, и обе половины выглядели верными.

Проверяется деньгами, а не текстом формулы: текст у сломанной и у починенной
книги отличается, но сказать по нему, ВЕРНО ли считает книга, нельзя.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as wrapper  # noqa: E402
from xlsx_eval import Evaluator  # noqa: E402

core = wrapper.core

# Офисник с гаражом и с лестницей цены: без лестницы ветка не проверяется
# вовсе, а без гаража проверять нечего.
INPUTS = {
    "offices_enabled": True,
    "retail_enabled": True,
    "sports_enabled": True,
    "offices_gba_sqm": 30000,
    "retail_gba_sqm": 20000,
    "sports_gba_sqm": 8000,
    "offices_parking_under_spaces": 200,
    "offices_parking_guest_spaces": 20,
    # Места ТЦ и ФОКа: они СТРОЯТСЯ и стоят денег, но не продаются
    # (владелец, 06.09.2026). Заданы нарочно — без них правило проверялось бы
    # на объектах без гаража, то есть не проверялось бы вовсе.
    "retail_parking_under_spaces": 150,
    "sports_parking_under_spaces": 80,
    "offices_growth_stage1_pct": 6,
    "offices_growth_stage2_pct": 10,
    "offices_growth_stage3_pct": 14,
    "offices_growth_stage4_pct": 18,
}
GARAGE_ROW = 33          # ОБЪЕКТЫ · «Паркинг объекта — выручка» офисника
PRICE_ROW = 23           # ОБЪЕКТЫ · «Цена реализации» офисника


@pytest.fixture(scope="module")
def built() -> tuple[bytes, dict]:
    inputs = {**core.DEFAULT_INPUTS, **INPUTS}
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    content, _name, _meta = core.build_project_workbook(
        inputs, tep, [], {}, project_name="Гараж")
    report = core.calculate(core.CalcRequest(inputs=inputs, tep=tep))
    return content, report


def _engine_garage_mln(report: dict) -> float:
    """Выручка гаражей объектов у движка, в млн ₽ — он считает в рублях."""
    return float((report.get("revenue") or {}).get("object_parking") or 0) / 1e6


def _row_total(book: openpyxl.Workbook, sheet: str, row: int) -> float:
    """Сумма помесячной строки — тем же вычислителем, что сверяет паритет."""
    evaluator = Evaluator(book)
    total = 0.0
    columns = book[sheet].max_column
    for index in range(4, columns + 1):
        letter = openpyxl.utils.get_column_letter(index)
        value = evaluator.cell(sheet, f"{letter}{row}")
        if isinstance(value, (int, float)):
            total += float(value)
    return total


def test_the_fixture_really_sets_a_ladder_and_a_garage(built) -> None:
    """Предохранитель: без лестницы и без мест проверка зелена на любом коде."""
    _content, report = built
    steps = [INPUTS[f"offices_growth_stage{k}_pct"] for k in (1, 2, 3, 4)]
    assert any(steps), "лестница не задана — ветка не проверяется"
    assert _engine_garage_mln(report) > 0, "выручки гаража нет — сверять нечего"


def test_the_book_prices_the_garage_the_way_the_engine_does(built) -> None:
    """Выручка гаража книги сходится с движком."""
    content, report = built
    book = openpyxl.load_workbook(io.BytesIO(content))
    engine = _engine_garage_mln(report)
    workbook = _row_total(book, "ОБЪЕКТЫ", GARAGE_ROW)
    assert abs(workbook - engine) <= max(0.5, abs(engine) * 0.005), (
        f"книга даёт {workbook:.2f} млн ₽ выручки гаража против {engine:.2f} "
        "у движка — лестница цены до строки гаража не доехала")


def test_the_garage_and_the_building_share_one_ladder(built) -> None:
    """У обеих строк множитель один: гараж не ведут отдельной ценой.

    Сверяется отношением, а не текстом: цена метра здания и цена места —
    разные величины, а ступени у них общие, и растут обе строки одинаково.
    """
    content, _report = built
    book = openpyxl.load_workbook(io.BytesIO(content))
    formula = str(book["ОБЪЕКТЫ"][f"D{GARAGE_ROW}"].value or "")
    price = str(book["ОБЪЕКТЫ"][f"D{PRICE_ROW}"].value or "")
    assert "ROUNDUP" in price, "в строке цены нет лестницы — фикстура не та"
    assert "ROUNDUP" in formula, (
        "строка выручки гаража идёт без лестницы: "
        "движок ведёт её ступенями, книга — месячным ростом")


# Строки выручки гаража по объектам: офисы 33, ТЦ 61, ФОК 151.
NO_SALE_ROWS = {"ТЦ": 61, "ФОК": 151}


def test_only_the_office_garage_sells_places(built) -> None:
    """Места в гараже ТЦ и ФОКа не продаются — решение владельца 06.09.2026.

    «Если это про обеспеченность ТЦ, то там конечно никто купить место не
    может. Если офисник, то там продаются, и остаётся немного гостевых.»
    Строятся они при этом у всех: признак гасит ВЫРУЧКУ, а не стройку,
    поэтому проверяется выручка, а не число мест.
    """
    content, report = built
    book = openpyxl.load_workbook(io.BytesIO(content))
    for label, row in NO_SALE_ROWS.items():
        assert _row_total(book, "ОБЪЕКТЫ", row) == pytest.approx(0.0, abs=1e-6), (
            f"книга продаёт места в гараже {label} — их там не покупают")
    office = _row_total(book, "ОБЪЕКТЫ", GARAGE_ROW)
    assert office > 0, "офисный гараж не продаётся — фикстура не та"
    assert office == pytest.approx(_engine_garage_mln(report), rel=0.005), (
        "вся выручка гаражей книги — офисная, и она обязана сойтись с движком")
