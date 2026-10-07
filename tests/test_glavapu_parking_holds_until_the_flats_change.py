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

# Выгрузка «Донского»: 55 квартир. Площадь выбрана так, чтобы 2118-ПП
# пунктом 1 от неё давала не число города (40 постоянных против 44): иначе
# тест прошёл бы на любом коде.
_CITY_AREA = 3400.0
_CITY_FLATS = 55
_IMPORT = {"normalized": {"parking_permanent": 44, "parking_guest": 5,
                          "parking_attached": 1, "parking_short_stop": 2,
                          "apartment_area_sqm": _CITY_AREA,
                          "apartment_units": _CITY_FLATS}}
_NORM = {"_glavapu_import": _IMPORT, "_parking_by_norm": ["underground"],
         "_parking_by_hand": []}


def _tep(apartments: float, flats: float) -> dict:
    return {"apartments": {"saleable": apartments, "units": flats},
            "underground_parking": {"units": 44.0, "gns": 1760.0, "guest_units": 109.0}}


def _engine(inputs: dict, apartments: float = _CITY_AREA,
            flats: float = _CITY_FLATS) -> tuple[dict, dict | None]:
    full = {**core.DEFAULT_INPUTS, **inputs}
    tep = _tep(apartments, flats)
    need = core.underground_parking_requirement(full, tep)
    core.apply_underground_tep_row(full, tep)
    return tep["underground_parking"], need


def test_the_city_numbers_hold_while_the_flats_are_the_city_ones() -> None:
    assert core.moscow_permanent_parking_2118(_CITY_AREA) == 40  # не число города
    row, need = _engine(_NORM)
    assert (row["units"], row["guest_units"]) == (49, 5)
    assert core.underground_saleable_spaces(row) == 44
    assert need["basis"] == "норматив ГлавАПУ по нормативному ТЭП"


def test_fewer_flats_on_the_same_area_recount_by_the_average_flat() -> None:
    """«Меняю количество квартир до 24 — почему не меняется количество машиномест»."""
    row, need = _engine(_NORM, flats=24)
    permanent, basis = core.moscow_permanent_parking_by_average(_CITY_AREA, 24)
    assert (row["units"], row["guest_units"]) == (permanent + 4, 4) == (43, 4)
    assert need["basis"] == basis
    assert "пункт 2 по средней квартире 141.7 м²" in basis


def test_edited_area_recounts_by_the_same_rule_as_without_the_city() -> None:
    row, need = _engine(_NORM, apartments=5000.0)
    alone = core.underground_parking_requirement(
        {**core.DEFAULT_INPUTS}, _tep(5000.0, _CITY_FLATS))
    assert (need["permanent"], need["guest"]) == (alone["permanent"], alone["guest"])
    assert row["units"] == need["permanent"] + need["guest"] == 73
    assert "пункт 2 по средней квартире" in need["basis"]


def test_without_the_city_area_the_flats_are_not_called_unchanged() -> None:
    """Нет площади в выгрузке — совпадение не доказано, считает норма."""
    bare = {**_NORM, "_glavapu_import": {"normalized": {
        k: v for k, v in _IMPORT["normalized"].items() if k != "apartment_area_sqm"}}}
    _row, need = _engine(bare)
    # Число мест здесь может совпасть с городским — решает основание: считала норма.
    assert need["basis"].startswith("приложение 5 к 945-ПП")


def test_hand_typed_spaces_beat_both() -> None:
    row, _ = _engine({"_glavapu_import": _IMPORT, "_parking_by_hand": ["underground"],
                      "underground_manual_spaces": 60, "underground_manual_gns_sqm": 2100})
    assert row["units"] == 60 and row["guest_units"] == 5


def test_the_page_follows_the_same_rule() -> None:
    cases = [(_CITY_AREA, _CITY_FLATS), (_CITY_AREA, 24), (5000.0, _CITY_FLATS)]
    out = page_blocks.run_json(
        "let inputs=" + json.dumps(_NORM, ensure_ascii=False) + ";"
        "let tep={};",
        "const r=[];for(const [a,f] of " + json.dumps(cases) + "){"
        "tep={apartments:{saleable:a,units:f},underground_parking:{}};"
        "const g=getGlavapuUnderground();r.push([g.permanent,g.guest,g.basis])}"
        "console.log(JSON.stringify(r))")
    (city_p, city_g, city_basis), *edited = out
    assert (city_p, city_g) == (44, 5) and city_basis == "норматив ГлавАПУ по нормативному ТЭП"
    for (area, flats), (p, g, basis) in zip(cases[1:], edited):
        _row, need = _engine(_NORM, apartments=area, flats=flats)
        assert (p, g) == (need["permanent"], need["guest"])
        assert basis.startswith("2118-ПП, п. 2 по средней квартире")
