"""Паркинг ОСЗ виден как продукт, а удельные не смешивают разные базы.

Регрессии по экрану проекта 25.09.2026:
- офис 186 180 м² ГНС, свой гараж 2 778 мест не был виден отдельной строкой ТЭП;
- корзина «Отдельные объекты» показывала проектные 132,7 / 244,1 рядом с
  316,2 / 672,7 по самому офису — разные базы выглядели одним показателем;
- повторный расчёт паркинга мог восстановить старую площадь после нового ТЭП.
"""

from __future__ import annotations

import copy

import pytest

import main_legacy as core


GBA = 186_180.0
TOTAL = 175_009.2
SALEABLE = 87_504.6
UNDER = 1_000
OVER = 1_778
SPACES = UNDER + OVER


def _inputs() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(
        offices_enabled=True,
        offices_gba_sqm=GBA,
        offices_saleable_sqm=SALEABLE,
        offices_parking_under_spaces=UNDER,
        offices_parking_over_spaces=OVER,
        offices_parking_guest_pct=10,
        object_parking_area_per_space_sqm=35,
        object_parking_over_area_per_space_sqm=25,
        offices_cost_th_per_sqm=200,
        _parking_by_hand=["offices"],
    )
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(
        gns=GBA, total_area=TOTAL, useful=SALEABLE, saleable=SALEABLE,
    )
    return t


@pytest.fixture(scope="module")
def result() -> dict:
    return core.calculate(core.CalcRequest(inputs=_inputs(), tep=_tep(), rates=[]))


def test_office_parking_reaches_tep_as_a_named_quantity(result: dict) -> None:
    office = next(row for row in result["tep"]["rows"] if row["key"] == "offices")
    assert office["parking_units"] == SPACES
    assert office["parking_under_units"] == UNDER
    assert office["parking_over_units"] == OVER
    assert office["parking_guest_units"] == round(SPACES * 0.10)
    assert office["parking_saleable_units"] == SPACES - round(SPACES * 0.10)
    assert office["under_gns"] == pytest.approx(UNDER * 35)


def test_office_parking_reaches_sold_products(result: dict) -> None:
    products = {row["key"]: row for row in result["report"]["products"]}
    expected = SPACES - round(SPACES * 0.10)
    assert products["object_parking"]["quantity"] == expected
    assert products["object_parking"]["revenue"] > 0

    office_tep = next(row for row in result["tep"]["rows"] if row["key"] == "offices")
    # После мест на первых этажах продаваемая офиса уменьшается. В отчёте
    # о продуктах должна стоять эта площадь, а не исходная вводная.
    assert products["offices"]["quantity"] == pytest.approx(office_tep["saleable"])
    assert products["offices"]["quantity"] < SALEABLE


def test_standalone_expense_bucket_has_no_fake_common_unit(result: dict) -> None:
    row = next(
        item for item in result["report"]["expense_structure"]
        if item["label"] == "Отдельные объекты"
    )
    assert row["value"] > 0
    assert row["per_gns_th"] is None
    assert row["per_saleable_th"] is None
    office = next(item for item in row["items"] if item["key"] == "offices")
    assert office["per_own_gns_th"] > 0
    assert office["per_own_saleable_th"] > 0
    assert "разные физические базы" in row["items_note"]


def test_a_new_tep_value_becomes_the_new_parking_base() -> None:
    t = _tep()
    x = _inputs()
    core.apply_object_parking(x, t)

    # Новый ТЭП после первого расчёта — не наш старый результат.
    t["offices"].update(
        gns=150_000.0,
        total_area=141_000.0,
        useful=72_000.0,
        saleable=72_000.0,
    )
    core.apply_object_parking(x, t)

    ratio = (150_000.0 - OVER * 25.0) / 150_000.0
    assert t["offices"]["total_area"] == pytest.approx(141_000.0 * ratio)
    assert t["offices"]["useful"] == pytest.approx(72_000.0 * ratio)
    assert t["offices"]["saleable"] == pytest.approx(72_000.0 * ratio)

    # Ещё один проход без новых правок остаётся идемпотентным.
    before = t["offices"]["saleable"]
    core.apply_object_parking(x, t)
    assert t["offices"]["saleable"] == pytest.approx(before)


def test_both_tep_surfaces_render_object_parking_as_a_row() -> None:
    page = core.PAGE
    assert page.count("tep-parking-sub") >= 2
    assert "parking_under_units" in page
    assert "parking_over_units" in page
    assert "parking_guest_units" in page


def test_composite_expense_units_render_as_dash() -> None:
    page = core.PAGE
    assert "x.per_gns_th==null?\'—\':num2(x.per_gns_th)" in page
    assert "x.per_saleable_th==null?\'—\':num2(x.per_saleable_th)" in page
