"""Гостевые места выводятся из своего гаража, а не переживают его.

Проект «Донской» (прод, 07.10.2026): импорт ГлавАПУ — 44 постоянных и 5
гостевых, а в строке ТЭП 44 места и 109 гостевых. Пару «места ↔ площадь»
заполнила НОРМА и пометила это (`_parking_by_norm`), но движок читал всякое
непустое поле как ручное: строка шла от пары, гостевые не пересчитывались, и
выживало чужое 109. Потолок «гостевых не больше мест» превращал это в 44 из 44
и ноль продаваемых — числа другие, ошибка та же.

* Пара нормы — строку считает норма: места и гостевые из одного расчёта.
* Пара руками — гостевые выводятся из мест (S/11, решение владельца), а не
  берутся из прежней строки.
"""

from __future__ import annotations

import main_legacy as core

# Выгрузка ГлавАПУ «Донского»: площадь квартир нормативного ТЭП даёт по 2118-ПП
# ровно её 44 постоянных; гостевые — десятая часть вверх, 5.
_IMPORT = {"normalized": {"parking_permanent": 44, "parking_guest": 5,
                          "parking_attached": 1, "parking_short_stop": 2,
                          "apartment_area_sqm": 3800.0}}


def _row(inputs: dict, apartments: float = 3800.0) -> dict:
    tep = {"apartments": {"saleable": apartments, "units": 56},
           "underground_parking": {"units": 44.0, "gns": 1760.0, "guest_units": 109.0}}
    core.apply_underground_tep_row({**core.DEFAULT_INPUTS, **inputs}, tep)
    return tep["underground_parking"]


def test_a_pair_filled_by_the_norm_is_counted_by_the_norm() -> None:
    row = _row({"_glavapu_import": _IMPORT, "project_class": "comfort",
                "underground_manual_spaces": 44, "underground_manual_gns_sqm": 1760,
                "_parking_by_norm": ["underground"], "_parking_by_hand": []})
    assert row["units"] == 49 and row["guest_units"] == 5
    assert core.underground_guest_spaces(row) == 5
    assert core.underground_saleable_spaces(row) == 44


def test_hand_typed_spaces_get_their_own_eleventh() -> None:
    row = _row({"underground_manual_spaces": 44, "underground_manual_gns_sqm": 1760,
                "_parking_by_hand": ["underground"]})
    assert row["units"] == 44 and row["gns"] == 1760
    assert core.underground_guest_spaces(row) == 4
    assert core.underground_saleable_spaces(row) == 40


def test_a_project_without_marks_keeps_the_typed_pair() -> None:
    """Бот, API, проект до пометок: непустое поле — человеческое, как и было."""
    row = _row({"_glavapu_import": _IMPORT,
                "underground_manual_spaces": 60, "underground_manual_gns_sqm": 2100})
    assert row["units"] == 60 and row["gns"] == 2100
    assert core.underground_guest_spaces(row) == 5


def test_the_hand_mark_beats_the_norm_mark() -> None:
    assert core.underground_parking_by_hand(
        {"_parking_by_hand": ["underground"], "_parking_by_norm": ["underground"]})
    assert not core.underground_parking_by_hand({"_parking_by_norm": ["underground"]})
    # Список руки без подземного — ещё не «норма»: посев его не проходит.
    assert core.underground_parking_by_hand({"_parking_by_hand": ["offices"]})
