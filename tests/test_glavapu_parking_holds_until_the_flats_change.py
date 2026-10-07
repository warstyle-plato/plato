"""Подземный паркинг ГлавАПУ держится, пока площадь квартир та же, что у города.

«Донской» (прод, 07.10.2026): выгрузка — 44 постоянных и 5 гостевых, а расчёт
ставил 44 места на всё: 2118-ПП от тех же метров давала 40 + 4. Норма
пересчитывала места при ЛЮБОЙ площади квартир, хотя город посчитал их на том
же ТЭП. Решение владельца — «числа ГлавАПУ до правки»: пока площадь квартир та,
что пришла с выгрузкой, места — города; поправили метры — 2118-ПП от новых;
ручной ввод сильнее обоих. Основание строки называет, чьё число.

Движок и страница проверяются на одних вводных: правило у них одно.
"""

from __future__ import annotations

import json

import main_legacy as core
import page_blocks  # noqa: E402 — стенд страницы, лежит рядом с тестами

# Выгрузка «Донского». Площадь квартир выбрана так, чтобы 2118-ПП от неё давала
# не число города (40 постоянных против 44): иначе тест прошёл бы на любом коде.
_CITY_AREA = 3400.0
_IMPORT = {"normalized": {"parking_permanent": 44, "parking_guest": 5,
                          "parking_attached": 1, "parking_short_stop": 2,
                          "apartment_area_sqm": _CITY_AREA}}
_NORM = {"_glavapu_import": _IMPORT, "_parking_by_norm": ["underground"],
         "_parking_by_hand": []}


def _tep(apartments: float) -> dict:
    return {"apartments": {"saleable": apartments, "units": 56},
            "underground_parking": {"units": 44.0, "gns": 1760.0, "guest_units": 109.0}}


def _engine(inputs: dict, apartments: float) -> tuple[dict, dict | None]:
    full = {**core.DEFAULT_INPUTS, **inputs}
    tep = _tep(apartments)
    need = core.underground_parking_requirement(full, tep)
    core.apply_underground_tep_row(full, tep)
    return tep["underground_parking"], need


def test_the_city_numbers_hold_while_the_flats_are_the_city_ones() -> None:
    assert core.moscow_permanent_parking_2118(_CITY_AREA) == 40  # не число города
    row, need = _engine(_NORM, _CITY_AREA)
    assert (row["units"], row["guest_units"]) == (49, 5)
    assert core.underground_saleable_spaces(row) == 44
    assert need["basis"] == "норматив ГлавАПУ по нормативному ТЭП"


def test_edited_flats_bring_the_decree_back() -> None:
    row, need = _engine(_NORM, 5000.0)
    permanent = core.moscow_permanent_parking_2118(5000.0)
    assert (row["units"], row["guest_units"]) == (permanent + 6, 6)
    assert need["basis"] == "2118-ПП от 5 000 м² квартир"


def test_without_the_city_area_the_flats_are_not_called_unchanged() -> None:
    """Нет площади в выгрузке — совпадение не доказано, считает норма."""
    bare = {**_NORM, "_glavapu_import": {"normalized": {
        k: v for k, v in _IMPORT["normalized"].items() if k != "apartment_area_sqm"}}}
    row, need = _engine(bare, _CITY_AREA)
    assert row["units"] == 44 and need["basis"].startswith("2118-ПП")


def test_hand_typed_spaces_beat_both() -> None:
    row, _ = _engine({"_glavapu_import": _IMPORT, "_parking_by_hand": ["underground"],
                      "underground_manual_spaces": 60, "underground_manual_gns_sqm": 2100},
                     _CITY_AREA)
    assert row["units"] == 60 and row["guest_units"] == 5


def test_the_page_follows_the_same_rule() -> None:
    out = page_blocks.run_json(
        "let inputs=" + json.dumps(_NORM, ensure_ascii=False) + ";"
        "let tep={};",
        "const r=[];for(const a of [" + f"{_CITY_AREA},5000" + "]){"
        "tep={apartments:{saleable:a,units:56},underground_parking:{}};"
        "const g=getGlavapuUnderground();r.push([g.permanent,g.guest,g.basis])}"
        "console.log(JSON.stringify(r))")
    (city_p, city_g, city_basis), (new_p, new_g, new_basis) = out
    assert (city_p, city_g) == (44, 5) and city_basis == "норматив ГлавАПУ по нормативному ТЭП"
    _row, need = _engine(_NORM, 5000.0)
    assert (new_p, new_g) == (need["permanent"], need["guest"])
    assert new_basis.startswith("2118-ПП от ")
