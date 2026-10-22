"""Пятно застройки и подземные уровни в книгах: формулы книги = методика движка.

Блок «Пятно застройки, этажность и подземные уровни» жилой книги v4 и
нежилой книги считает отступы, пятно, уровни и надбавку за глубину ФОРМУЛАМИ
(`site_massing_book`), и ставка подземной части в CAPEX читает надбавку из
блока. Книга пересчитывается `xlsx_eval` — openpyxl формул не считает.

Запуск: python3 -m pytest tests/test_site_massing_book.py -q
"""

from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as _wrapper  # noqa: E402

core = _wrapper.core

SETTINGS = json.loads((ROOT / "tests" / "fixtures" / "project_settings_donskoy_0_25_78.json")
                      .read_text(encoding="utf-8"))


def _housing() -> tuple[dict, dict]:
    """«Донской» на участке 0,2 га со ставкой класса: подземка — два уровня."""
    x = {**core.DEFAULT_INPUTS, **copy.deepcopy(SETTINGS["inputs"])}
    base = core.class_base_preset(x["project_class"], "msk", x.get("project_kind"))
    x["main_under_th_per_sqm"] = base["main_under_th_per_sqm"]
    x.update(_class_manual=[], _field_origin={}, site_area_ha=0.2, building_footprint_sqm=700)
    return x, copy.deepcopy(SETTINGS["tep"])


def _block(book, sheet_name: str) -> dict[str, str]:
    sheet = book[sheet_name]
    labels = {label: key for key, label, _ in core._massing_book.ROWS}
    out = {}
    for row in range(1, sheet.max_row + 1):
        key = labels.get(str(sheet.cell(row, 1).value or ""))
        if key:
            out[key] = f"B{row}"
    return out


def test_the_housing_book_counts_levels_and_the_depth_markup():
    sys.setrecursionlimit(400000)
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t = _housing()
    bundle = core._run_authoritative_model(x, t, [], None)
    m = bundle["consolidated"]["tep"]["site_massing"]
    assert m["underground_levels"] == 2 and m["underground_depth_factor"] > 1.0, m
    content, _, meta = core.build_project_workbook(
        x, t, [], None, project_name="Донской",
        finance_hints=core._v4_finance_hints(bundle))
    assert not [s for s in meta.get("missing") or [] if "глубин" in s or "подземн" in s], meta
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    cells = _block(book, "Параметры модели")
    assert set(cells) == {key for key, _, _ in core._massing_book.ROWS}, cells
    evaluator = Evaluator(book)
    got = lambda key: float(evaluator.cell("Параметры модели", cells[key]) or 0)  # noqa: E731
    assert got("underground_levels") == 2
    assert got("footprint_sqm") == pytest.approx(700)
    assert got("average_storeys") == pytest.approx(m["average_storeys"], rel=1e-6)
    assert got("setbacks_sqm") == pytest.approx(m["setbacks_sqm"], rel=1e-6)
    assert got("depth_factor") == pytest.approx(m["underground_depth_factor"], rel=1e-9)
    # Ставка в CAPEX очереди — с надбавкой, и формула читает ячейку блока.
    formula = str(book["CAPEX"]["B22"].value)
    assert f"'Параметры модели'!$B$45*'Параметры модели'!${cells['depth_factor'][0]}$" \
        f"{cells['depth_factor'][1:]}" in formula, formula
    prepared = core.prepared_calculation(x, t, [])
    op = core.build_operating_model(prepared["x"], prepared["t"], [])
    assert op["capex_amounts"]["main_under"] > op["core_under_gns"] * float(
        x["main_under_th_per_sqm"]) * 1000


def test_a_hand_rate_has_no_markup_in_the_book():
    sys.setrecursionlimit(400000)
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t = _housing()
    x["_class_manual"] = ["main_under_th_per_sqm"]
    bundle = core._run_authoritative_model(x, t, [], None)
    content, _, _ = core.build_project_workbook(
        x, t, [], None, project_name="Донской",
        finance_hints=core._v4_finance_hints(bundle))
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    cells = _block(book, "Параметры модели")
    evaluator = Evaluator(book)
    assert float(evaluator.cell("Параметры модели", cells["depth_factor"])) == 1.0
    assert float(evaluator.cell("Параметры модели", cells["underground_levels"])) == 2


def _office() -> tuple[dict, dict]:
    """Проверочный пример владельца: офис на Пролетарском, 68 мест под землёй."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind="nonresidential", project_class="business", site_area_ha=0.243,
             offices_enabled=True, offices_gba_sqm=22842, offices_parking_under_spaces=68,
             _parking_by_hand=["offices"])
    base = core.class_base_preset("business", "msk", "nonresidential")
    x["main_under_th_per_sqm"] = base["main_under_th_per_sqm"]
    return x, {"offices": {"gns": 22842.0, "total_area": 22842.0}}


def test_the_nonresidential_book_counts_the_same_levels():
    sys.setrecursionlimit(400000)
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t = _office()
    bundle = core._run_authoritative_model(x, t, [], None)
    m = bundle["consolidated"]["tep"]["site_massing"]
    assert m["underground_levels"] == 2 and m["underground_depth_factor"] > 1.0, m
    content, _, meta = core.build_project_workbook(
        x, t, [], None, project_name="Пролетарский",
        finance_hints=core._v4_finance_hints(bundle))
    assert meta.get("nonres_book"), meta
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    cells = _block(book, "Вводные")
    assert set(cells) == {key for key, _, _ in core._massing_book.ROWS}, cells
    evaluator = Evaluator(book)
    got = lambda key: float(evaluator.cell("Вводные", cells[key]) or 0)  # noqa: E731
    assert got("underground_sqm") == pytest.approx(2380.0)
    assert got("footprint_sqm") == pytest.approx(m["footprint_sqm"], rel=1e-9)
    assert got("average_storeys") == pytest.approx(m["average_storeys"], rel=1e-9)
    assert got("underground_levels") == 2
    assert got("depth_factor") == pytest.approx(m["underground_depth_factor"], rel=1e-9)
    # Гараж офиса в «Затратах» — по ставке с надбавкой, как в движке.
    costs = book["Затраты"]
    row = next(r for r in range(1, costs.max_row + 1)
               if "подземный гараж" in str(costs.cell(r, 1).value or ""))
    rate = float(x["main_under_th_per_sqm"])
    assert float(evaluator.cell("Затраты", f"E{row}")) == pytest.approx(
        2380.0 * rate * m["underground_depth_factor"] * 1000, rel=1e-9)


@pytest.mark.parametrize("extra, origin", [({"max_storeys_allowed": 9}, "limit"),
                                           ({"site_coverage_max_pct": 50}, "coverage")])
def test_the_book_takes_the_footprint_like_the_engine(extra, origin):
    """Пятно по пределу этажности и по проценту застройки — книга = движок."""
    sys.setrecursionlimit(400000)
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t = _office()
    x.update(extra)
    bundle = core._run_authoritative_model(x, t, [], None)
    m = bundle["consolidated"]["tep"]["site_massing"]
    assert m["footprint_origin"] == origin, m
    content, _, _ = core.build_project_workbook(
        x, t, [], None, project_name="Пролетарский",
        finance_hints=core._v4_finance_hints(bundle))
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    cells = _block(book, "Вводные")
    evaluator = Evaluator(book)
    got = lambda key: float(evaluator.cell("Вводные", cells[key]) or 0)  # noqa: E731
    assert got("footprint_sqm") == pytest.approx(m["footprint_sqm"], rel=1e-9)
    assert got("footprint_shortage_sqm") == pytest.approx(m["footprint_shortage_sqm"], rel=1e-9)
    assert got("average_storeys") == pytest.approx(m["average_storeys"], rel=1e-9)
    assert got("coverage_sqm") == pytest.approx(m["coverage_sqm"], rel=1e-9)
