"""Регрессия проекта «Проект»: свой паркинг офисника занимает существующую GBA.

22.09.2026 сравнение двух выгрузок одного проекта показало, что 1000 мест на
первых этажах отнимали 35 000 м² прямо из уже продаваемой площади. Это давало
ровно -25,104 млрд ₽ офисной выручки. Правило проекта другое:

    GBA_after = GBA - over_spaces * 25
    total = GBA_after * 94%
    saleable = total * 50%

Исходная GBA объекта не меняется; паркинг местами under/over не может её
увеличить. Подземные метры остаются отдельным CAPEX.
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

GBA = 186_180.0
TOTAL = GBA * 0.94
SALEABLE = TOTAL * 0.50
SPACES = 2_778
OVER = 1_000
UNDER = SPACES - OVER


def _inputs(under: int, over: int) -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(
        offices_enabled=True,
        offices_gba_sqm=GBA,
        offices_saleable_sqm=SALEABLE,
        offices_parking_under_spaces=under,
        offices_parking_over_spaces=over,
        object_parking_area_per_space_sqm=35,
        object_parking_over_area_per_space_sqm=25,
        offices_parking_guest_pct=10,
        _parking_by_hand=["offices"],
    )
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(
        gns=GBA,
        total_area=TOTAL,
        useful=SALEABLE,
        saleable=SALEABLE,
    )
    return t


def _product_revenue(result: dict, key: str) -> float:
    rows = result["report"]["products"]
    hit = [row for row in rows if row.get("key") == key]
    assert len(hit) == 1, (key, hit)
    return float(hit[0].get("revenue") or 0.0)


def test_project_reallocation_keeps_gba_and_recalculates_saleable_once() -> None:
    underground = _tep()
    overground = _tep()

    u = core.apply_object_parking(_inputs(SPACES, 0), underground)
    o = core.apply_object_parking(_inputs(UNDER, OVER), overground)

    assert underground["offices"]["gns"] == GBA
    assert overground["offices"]["gns"] == GBA
    assert u["own_units"] == o["own_units"] == SPACES

    footprint = OVER * 25
    expected_total = (GBA - footprint) * 0.94
    expected_saleable = expected_total * 0.50

    assert o["over_area_per_space_sqm"] == 25
    assert overground["offices"]["parking_over_gba_sqm"] == footprint
    assert overground["offices"]["total_area"] == pytest.approx(expected_total)
    assert overground["offices"]["saleable"] == pytest.approx(expected_saleable)
    assert overground["offices"]["parking_saleable_taken"] == pytest.approx(
        SALEABLE - expected_saleable)
    assert overground["offices"]["saleable"] == pytest.approx(75_754.6)

    # Повторный проход на той же копии ТЭП не вычитает первые этажи второй раз.
    core.apply_object_parking(_inputs(UNDER, OVER), overground)
    assert overground["offices"]["saleable"] == pytest.approx(expected_saleable)
    assert overground["offices"]["gns"] == GBA


def test_project_reallocation_keeps_parking_revenue_and_changes_only_office_quantity() -> None:
    under_result = core.calculate(core.CalcRequest(
        inputs=_inputs(SPACES, 0), tep=_tep(), rates=[]))
    over_result = core.calculate(core.CalcRequest(
        inputs=_inputs(UNDER, OVER), tep=_tep(), rates=[]))

    assert _product_revenue(over_result, "object_parking") == pytest.approx(
        _product_revenue(under_result, "object_parking"), rel=1e-12)

    office_under = _product_revenue(under_result, "offices")
    office_over = _product_revenue(over_result, "offices")
    assert office_over / office_under == pytest.approx(75_754.6 / 87_504.6, rel=1e-12)


def test_impossible_first_floor_layout_warns_instead_of_growing_gba() -> None:
    t = _tep()
    x = _inputs(0, 10_000)
    got = core.apply_object_parking(x, t)

    assert t["offices"]["gns"] == GBA
    assert t["offices"]["saleable"] == 0
    assert t["offices"]["parking_layout_overflow_sqm"] > 0
    assert got.get("warnings")
    assert "площадь объекта не увеличена" in got["note"]


def test_v4_book_uses_25sqm_footprint_before_saleable_ratio() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x = _inputs(UNDER, OVER)
    content, _, meta = core.build_project_workbook(
        x, _tep(), [], None, project_name="Проект")
    assert not [m for m in meta["missing"] if "паркинг объектов" in m], meta["missing"]

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    params = book["Параметры модели"]
    objects = book["ОБЪЕКТЫ"]

    assert params["K160"].value == 25
    assert "K162*$K$160" in str(params["K26"].value)
    assert "$K$158" not in str(objects["B13"].value)

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(book)
    assert evaluator.cell("ОБЪЕКТЫ", "B13") == pytest.approx(75_754.6)
    assert evaluator.cell("Параметры модели", "K168") == "OK"


def test_office_under_and_first_floor_places_can_have_different_sale_prices() -> None:
    same = _inputs(UNDER, OVER)
    same.update(
        parking_price_th=6_000,
        offices_parking_under_price_mln_per_space=6,
        offices_parking_over_price_mln_per_space=6,
    )
    split = _inputs(UNDER, OVER)
    split.update(
        parking_price_th=6_000,
        offices_parking_under_price_mln_per_space=6,
        offices_parking_over_price_mln_per_space=4,
    )

    same_result = core.calculate(core.CalcRequest(inputs=same, tep=_tep(), rates=[]))
    split_result = core.calculate(core.CalcRequest(inputs=split, tep=_tep(), rates=[]))

    same_revenue = _product_revenue(same_result, "object_parking")
    split_revenue = _product_revenue(split_result, "object_parking")
    weighted_mln = (UNDER * 6 + OVER * 4) / SPACES
    assert split_revenue / same_revenue == pytest.approx(weighted_mln / 6, rel=1e-12)


def test_parking_sale_price_fields_exist_only_for_sellable_office_garage() -> None:
    assert "offices_parking_under_price_mln_per_space" in core.DEFAULT_INPUTS
    assert "offices_parking_over_price_mln_per_space" in core.DEFAULT_INPUTS
    assert "retail_parking_under_price_mln_per_space" not in core.DEFAULT_INPUTS
    assert "retail_parking_over_price_mln_per_space" not in core.DEFAULT_INPUTS
    assert "sports_parking_under_price_mln_per_space" not in core.DEFAULT_INPUTS
    assert "sports_parking_over_price_mln_per_space" not in core.DEFAULT_INPUTS


def test_v4_book_uses_separate_office_parking_prices() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x = _inputs(UNDER, OVER)
    x.update(
        parking_price_th=6_000,
        offices_parking_under_price_mln_per_space=6,
        offices_parking_over_price_mln_per_space=4,
    )
    report = core.calculate(core.CalcRequest(inputs=dict(x), tep=_tep(), rates=[]))
    content, _, meta = core.build_project_workbook(
        dict(x), _tep(), [], None, project_name="Проект")
    assert not [m for m in meta["missing"] if "паркинг объектов" in m], meta["missing"]

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    params = book["Параметры модели"]
    objects = book["ОБЪЕКТЫ"]

    assert params["K169"].value == 6
    assert params["K170"].value == 4
    formula = str(objects["D33"].value)
    assert "$K$169" in formula and "$K$170" in formula

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(book)
    assert evaluator.cell("ОБЪЕКТЫ", "B33") == pytest.approx(
        _product_revenue(report, "object_parking") / 1_000_000, rel=1e-9)


def test_office_parking_reaches_tep_and_the_saleable_product_breakdown() -> None:
    result = core.calculate(core.CalcRequest(
        inputs=_inputs(UNDER, OVER), tep=_tep(), rates=[]))
    office = next(row for row in result["tep"]["rows"] if row["key"] == "offices")
    product = next(row for row in result["report"]["products"]
                   if row["key"] == "object_parking")

    assert office["parking_units"] == SPACES
    assert office["parking_saleable_units"] > 0
    assert office["under_gns"] == pytest.approx(UNDER * 35)
    assert product["quantity"] == pytest.approx(office["parking_saleable_units"])
    assert product["unit"] == "шт."
    assert product["revenue"] > 0


def test_page_prints_object_parking_as_a_separate_tep_child_row() -> None:
    page = core.PAGE
    assert "↳ Паркинг ·" in page
    assert "objectParkingTepRow" in page
    assert "parking_saleable_units" in page
