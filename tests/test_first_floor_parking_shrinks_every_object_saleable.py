"""Места первых этажей уменьшают ПРОДАННОЕ объекта, а не его строку ТЭП.

Правило одно (`standalone_object_saleable`, формула книги K26/K46/K129):
продаваемая = (ГНС вводных − места 1 эт. × площадь места) × продаваемая / ГНС.
Проект владельца (29.09.2026): офисы 186 180 м² ГНС, 1 000 подземных мест и
1 778 на первых этажах по 25 м² — под местами 44 450 м² ГНС здания, продаваемая
87 504,6 → 66 613,1 м².

Строка ТЭП — площадь здания: 87 504,6 м². Вычет живёт в структуре продукта —
продукт «Офисы», выручка, сводная продаваемая (владелец, 29.09.2026: «оставь в
структуре»).

Поломка была в том, ЧТО движок считал базой строки ТЭП. Страница после
расчёта кладёт в свою строку ответ движка — уже уменьшенный — и отправляет её
со следующим расчётом; движок вычитал места второй раз: строка ТЭП 50 709 м²
при выручке от 66 613. Базой служит вводная, а не присланная строка.

Запуск: python3 -m pytest tests/test_first_floor_parking_shrinks_every_object_saleable.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

GBA = 186_180.0
RAW = 87_504.6
UNDER = 1_000
OVER = 1_778
AFTER = (GBA - OVER * 25) * RAW / GBA  # 66 613,1

# Метровые объекты с гаражом: офисы 1…5, ТЦ 1…5, ФОК.
GARAGE_OBJECTS = [o for o in core.STANDALONE_OBJECTS
                  if o.garage and o.measure != "spaces"]


def _inputs(obj) -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    p = obj.prefix
    x.update({
        obj.enabled_key: True,
        f"{p}_gba_sqm": GBA,
        f"{p}_saleable_sqm": RAW,
        f"{p}_parking_under_spaces": UNDER,
        f"{p}_parking_over_spaces": OVER,
        f"{p}_parking_guest_pct": 10,
        "object_parking_over_area_per_space_sqm": 25,
        "_parking_by_hand": [p],
    })
    if obj.sale_gate:
        x[obj.sale_gate] = "sale"
    return x


def _tep(obj, saleable: float) -> dict:
    """Строка объекта в том виде, в каком её шлёт страница."""
    t = copy.deepcopy(core.TEP_DEFAULT)
    share = saleable / RAW
    t[obj.key].update(gns=GBA, total_area=GBA * 0.94 * share,
                      useful=saleable, saleable=saleable)
    return t


def _tep_row(result: dict, key: str) -> dict:
    return next(r for r in result["tep"]["rows"] if r["key"] == key)


def _product(result: dict, key: str) -> dict:
    hit = [r for r in result["report"]["products"] if r.get("key") == key]
    assert len(hit) == 1, (key, hit)
    return hit[0]


def test_the_owner_numbers() -> None:
    assert AFTER == pytest.approx(66_613.1)


@pytest.mark.parametrize("obj", GARAGE_OBJECTS, ids=lambda o: o.key)
@pytest.mark.parametrize("sent", [RAW, AFTER], ids=["raw_row", "row_from_last_answer"])
def test_tep_row_report_and_revenue_carry_one_saleable(obj, sent) -> None:
    x = _inputs(obj)
    result = core.calculate(core.CalcRequest(inputs=x, tep=_tep(obj, sent), rates=[]))

    owner = core.standalone_object_saleable(x, {obj.key: {"parking_over_units": OVER}}, obj.key)
    assert owner == pytest.approx(AFTER)
    row = _tep_row(result, obj.key)
    assert row["saleable"] == pytest.approx(RAW), "строка ТЭП — площадь здания"
    assert row["useful"] == pytest.approx(RAW)
    assert row["total_area"] == pytest.approx(GBA * 0.94)
    assert row["gns"] == pytest.approx(GBA), "ГНС объекта места не меняют"
    assert row["parking_saleable_after_sqm"] == pytest.approx(AFTER)
    assert _product(result, obj.key)["quantity"] == pytest.approx(AFTER), "отчёт «Продукт»"

    own = next(o for o in result["parking"]["own"] if o["tep_key"] == obj.key)
    assert own["over_gba_sqm"] == pytest.approx(OVER * 25)


def test_revenue_follows_the_reduced_saleable() -> None:
    obj = next(o for o in GARAGE_OBJECTS if o.key == "offices")
    x = _inputs(obj)
    reduced = core.calculate(core.CalcRequest(inputs=x, tep=_tep(obj, AFTER), rates=[]))
    all_under = copy.deepcopy(x)
    all_under.update(offices_parking_under_spaces=UNDER + OVER, offices_parking_over_spaces=0)
    plain = core.calculate(core.CalcRequest(inputs=all_under, tep=_tep(obj, RAW), rates=[]))
    ratio = _product(reduced, "offices")["revenue"] / _product(plain, "offices")["revenue"]
    assert ratio == pytest.approx(AFTER / RAW, rel=1e-9)


def test_a_repeated_answer_does_not_shrink_the_row_again() -> None:
    """Страница пишет ответ в строку и шлёт её снова — много раз подряд."""
    obj = next(o for o in GARAGE_OBJECTS if o.key == "offices")
    x = _inputs(obj)
    t = _tep(obj, RAW)
    for _ in range(3):
        result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(t), rates=[]))
        row = _tep_row(result, "offices")
        for field in ("gns", "total_area", "useful", "saleable"):
            t["offices"][field] = row[field]
        assert row["saleable"] == pytest.approx(RAW)
        assert row["parking_saleable_after_sqm"] == pytest.approx(AFTER)
        assert _product(result, "offices")["quantity"] == pytest.approx(AFTER)


def test_the_project_saleable_counts_what_is_sold() -> None:
    """Сводная продаваемая — проданные метры: строка ТЭП держит здание, и её
    сумма дала бы в продаваемую метры под машино-местами."""
    obj = next(o for o in GARAGE_OBJECTS if o.key == "offices")
    x = _inputs(obj)
    with_places = core.calculate(core.CalcRequest(inputs=x, tep=_tep(obj, RAW), rates=[]))
    none = copy.deepcopy(x)
    none.update(offices_parking_under_spaces=UNDER + OVER, offices_parking_over_spaces=0)
    without = core.calculate(core.CalcRequest(inputs=none, tep=_tep(obj, RAW), rates=[]))
    assert (without["summary"]["monetizable_saleable_sqm"]
            - with_places["summary"]["monetizable_saleable_sqm"]) == pytest.approx(RAW - AFTER)


def test_the_queue_summary_reads_the_same_saleable() -> None:
    obj = next(o for o in GARAGE_OBJECTS if o.key == "offices")
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=_inputs(obj), tep=_tep(obj, AFTER), rates=[],
        phasing={
            "enabled": True, "mode": "phased", "user_enabled": True,
            "phase_count": 2, "phase_gap_months": 12,
            "phases": [{"name": f"О{i + 1}", "start_offset_months": i * 12,
                        "construction_months": 24} for i in range(2)],
            "discrete": {"offices": 1}, "social_objects": [],
        },
    ))
    consolidated = bundle["consolidated"]
    assert _tep_row(consolidated, "offices")["saleable"] == pytest.approx(RAW)
    assert _product(consolidated, "offices")["quantity"] == pytest.approx(AFTER)
    own = next(o for o in consolidated["parking"]["own"] if o["tep_key"] == "offices")
    assert own["over_gba_sqm"] == pytest.approx(OVER * 25)
