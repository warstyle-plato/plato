"""Гараж офиса без своего числа подземных мест строится по нормативу.

Владелец, 25.10.2026 (прод, офис ~34 500 м² ГНС, Москва): у офиса стоят 271
машино-место на первых этажах, а расчёт строил 420 — ещё 149 мест пришли
переносом подземного паркинга проекта из старого поля «Машино-места —
решение проекта». Решения:

* подземный гараж офиса без числа, вписанного руками, — по нормативу Москвы
  или области; места первых этажей засчитываются, под землю идёт остаток;
* вписанное руками число подземных мест сильнее всего;
* «Отказ от подземного паркинга» в нежилом проекте снимает подземные места;
* места проекта к офису больше не переносятся — число в поле проекта
  называется остатком вводных;
* происхождение числа видно человеку одной фразой движка.

Запуск: python3 -m pytest tests/test_office_garage_follows_the_norm.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

OFFICE = dict(
    project_kind=core.PROJECT_KIND_NONRESIDENTIAL, vri_region="moscow", offices_enabled=True,
    offices_gba_sqm=34500, offices_saleable_sqm=24000, purchase_price_mln=5,
    offices_cost_th_per_sqm=110, offices_price_th_per_sqm=273,
)


def _spec(**over) -> tuple[dict, dict]:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        x[key] = 0
    x.update(OFFICE)
    x.update(over)
    t.setdefault("offices", {}).update(gns=34500, total_area=32400, useful=24000, saleable=24000)
    return x, t


def _office(result: dict) -> dict:
    own = result["parking"]["own"]
    return next(item for item in own if item["prefix"] == "offices")


def _calc(**over) -> dict:
    x, t = _spec(**over)
    return core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))


def test_the_owner_case_builds_the_norm_not_the_old_project_field() -> None:
    """271 на первых этажах вписаны руками, подземных не задано, в поле
    проекта осталось 149: под землю идёт норматив минус 271, а не 149."""
    result = _calc(offices_parking_over_spaces=271, offices_parking_under_spaces=0,
                   underground_manual_spaces=149, underground_manual_gns_sqm=5215,
                   _parking_by_hand=["offices"])
    item = _office(result)
    required = item["required_spaces"]
    assert required > 271
    assert item["over_spaces"] == 271
    assert item["under_spaces"] == required - 271
    assert item["units"] == required
    assert item["under_origin"] == "norm_rest"
    assert item["origin_note"] == (f"По нормативу Москвы: {required} мест, из них 271 на "
                                   f"первых этажах, под землёй {required - 271}.")
    s = result["summary"]
    assert any("подземный паркинг проекта — места" in line for line in s["project_kind_leftovers"])
    line = (f"{item['label']}: по нормативу Москвы: {required} мест, из них 271 на "
            f"первых этажах, под землёй {required - 271}.")
    assert s["project_kind_parking"] == [line]
    # Отчёт «Объект и участок» и PDF печатают ту же фразу, а не свою.
    assert {"label": "Паркинг", "value": line, "unit": "text"} in core.project_kind_rows(s)


def test_first_floors_above_the_norm_leave_nothing_underground() -> None:
    item = _office(_calc(offices_parking_over_spaces=5000, offices_parking_under_spaces=0,
                         _parking_by_hand=["offices"]))
    assert item["under_spaces"] == 0 and item["over_spaces"] == 5000


def test_the_hand_number_underground_beats_the_norm() -> None:
    item = _office(_calc(offices_parking_over_spaces=271, offices_parking_under_spaces=40,
                         _parking_by_hand=["offices"]))
    assert item["under_spaces"] == 40 and item["under_origin"] == "hand"
    assert item["origin_note"] == "Задано руками: под землёй 40 мест, на первых этажах 271."


def test_no_hand_numbers_put_the_whole_norm_underground() -> None:
    item = _office(_calc(offices_parking_over_spaces=0, offices_parking_under_spaces=0,
                         underground_manual_spaces=149, _parking_by_hand=[]))
    assert item["by_norm"] and item["under_origin"] == "norm"
    assert item["under_spaces"] == item["required_spaces"] > 0


def test_refusing_underground_parking_clears_the_office_garage() -> None:
    """Прежде галочка в нежилом расчёте не меняла ничего."""
    for hand in ({"offices_parking_under_spaces": 120, "_parking_by_hand": ["offices"]},
                 {"_parking_by_hand": []},
                 {"offices_parking_over_spaces": 50, "_parking_by_hand": ["offices"]}):
        result = _calc(underground_parking_disabled=True, underground_manual_spaces=149, **hand)
        item = _office(result)
        assert item["under_spaces"] == 0 and item["under_gns"] == 0, hand
        assert item["under_origin"] == "refused"
        assert item["origin_note"].startswith("Отказ от подземного паркинга")


def test_the_refusal_does_not_touch_a_mixed_project_office() -> None:
    """В жилом проекте галочка — про паркинг дома; гараж офиса — его поля."""
    x, t = _spec(project_kind=core.PROJECT_KIND_MIXED, underground_parking_disabled=True,
                 offices_parking_under_spaces=120, _parking_by_hand=["offices"])
    item = next(i for i in core.apply_object_parking(x, t)["own"] if i["prefix"] == "offices")
    assert item["under_spaces"] == 120


def test_the_project_parking_is_no_longer_moved_to_the_office() -> None:
    assert not hasattr(core, "office_takes_project_parking")


# --- Страница: подпись у полей офиса и правка мест первых этажей ----------

PAGE_PRELUDE = """
const fields = {};
global.document = {getElementById: id => (fields[id] = fields[id] || {value: ''}),
                   activeElement: null};
const num = v => String(v);
let lastResult = %(result)s;
let inputs = %(inputs)s;
let phaseBundle = null;
"""


def _page(result: dict, inputs: dict, tail: str):
    import json  # noqa: PLC0415

    sys.path.insert(0, str(ROOT / "tests"))
    import page_blocks  # noqa: PLC0415

    return page_blocks.run_json(
        PAGE_PRELUDE % {"result": json.dumps(result, ensure_ascii=False, default=str),
                        "inputs": json.dumps(inputs, ensure_ascii=False, default=str)}, tail)


def test_the_page_names_where_the_office_spaces_come_from() -> None:
    """Подпись у полей офиса печатает фразу движка: норматив, из них первые
    этажи, под землёй остаток. Прежде под нулём стояло «ноль — гаража нет»."""
    result = _calc(offices_parking_over_spaces=271, offices_parking_under_spaces=0,
                   _parking_by_hand=["offices"])
    item = _office(result)
    note = _page({"parking": result["parking"]},
                 {"offices_enabled": True, "_parking_by_hand": ["offices"]},
                 "console.log(JSON.stringify(objectParkingFieldNote('offices')))")
    assert note.startswith(item["origin_note"])
    assert "под землёй — остаток" in note

    refused = _calc(underground_parking_disabled=True, _parking_by_hand=[])
    note = _page({"parking": refused["parking"]},
                 {"offices_enabled": True, "underground_parking_disabled": True},
                 "console.log(JSON.stringify(objectParkingFieldNote('offices')))")
    assert note.startswith("Отказ от подземного паркинга")


def test_typing_first_floor_spaces_frees_the_norm_written_underground() -> None:
    """Норматив стоял в поле подземных целиком; человек вписал места первых
    этажей — поле подземных очищается, иначе прежний норматив читался бы
    вписанным руками и места сложились бы дважды."""
    result = _calc(_parking_by_hand=[])
    item = _office(result)
    assert item["by_norm"]
    out = _page({"parking": result["parking"]},
                {"offices_enabled": True, "_parking_by_norm": ["offices"],
                 "offices_parking_under_spaces": item["under_spaces"],
                 "offices_parking_over_spaces": 271},
                "parkingFieldByHand('offices','offices_parking_over_spaces');"
                "console.log(JSON.stringify({under:inputs.offices_parking_under_spaces,"
                "hand:inputs._parking_by_hand}))")
    assert out == {"under": 0, "hand": ["offices"]}
    # Правка самого числа подземных мест его не трогает: это и есть решение.
    out = _page({"parking": result["parking"]},
                {"offices_enabled": True, "_parking_by_norm": ["offices"],
                 "offices_parking_under_spaces": 40},
                "parkingFieldByHand('offices','offices_parking_under_spaces');"
                "console.log(JSON.stringify(inputs.offices_parking_under_spaces))")
    assert out == 40
