"""Вводные объекта приносит его строка реестра, а не литерал.

Умолчаний у объекта 17–20, и на четырёх объектах это 76 полей руками. Пока
они стояли литералом, «поставить пару ОСЗ» означало вписать ещё 72 — то есть
завести второй список там, где состав уже объявлен один раз. Копия молчит по
привычке: она не падает, пока поля совпадают, и заговорит ровно в тот день,
когда объект заведут, а поле забудут, — на экране это выглядит как «объект
есть, а считать его нечем».

Проверка ищет не совпадение списков, а ПРОИСХОЖДЕНИЕ: объект, выброшенный из
реестра, обязан перестать приносить свои поля. Без этого диверсанта проверка
зелена и на литерале — он даёт ровно те же ключи.

Запуск: python3 -m pytest tests/test_an_object_brings_its_own_defaults.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _built(roster: tuple[Any, ...]) -> dict[str, Any]:
    """Вводные, собранные из литерала и названного набора объектов."""
    out = dict(core._DEFAULT_INPUTS_LITERAL)
    for obj in roster:
        out.update(core.standalone_object_defaults(obj))
    return out


def test_the_defaults_of_the_engine_are_the_ones_the_roster_builds() -> None:
    """Умолчания движка — это литерал плюс реестр, без ручного остатка."""
    assert _built(core.STANDALONE_OBJECTS) == core.DEFAULT_INPUTS


def test_the_literal_carries_no_object_field_at_all() -> None:
    """Поле объекта, оставшееся в литерале, — тот самый второй список.

    Оно не расходится сразу: значение совпадает, пока его не правят. Поэтому
    ловится не расхождение, а само присутствие.
    """
    left = core.standalone_object_field_keys() & set(core._DEFAULT_INPUTS_LITERAL)
    assert left == set(), f"поля объектов остались литералом: {sorted(left)}"


def test_an_object_dropped_from_the_roster_stops_bringing_its_fields() -> None:
    """Диверсант: без строки реестра полей объекта нет вовсе.

    Ровно этим отличается порождение от совпадения с прежним литералом.
    """
    dropped = core.standalone_objects(("offices",))[0]
    rest = tuple(o for o in core.STANDALONE_OBJECTS if o.key != "offices")
    assert len(rest) == len(core.STANDALONE_OBJECTS) - 1, "объект из реестра не выброшен"

    without = _built(rest)
    gone = set(core.standalone_object_defaults(dropped)) - set(without)
    assert "offices_gba_sqm" in gone, "поля объекта пришли не из реестра"
    assert gone == set(core.standalone_object_defaults(dropped))


def test_a_new_roster_line_brings_its_whole_form() -> None:
    """Пятый объект приносит всю форму вводных, а не половину.

    Это и есть цена, ради которой реестр заводился: строка вместо двадцати.
    """
    extra = core.StandaloneObject(
        "offices2", "offices2", "офисы 2", 3, True, True, "sqm",
        "offices2_cost_th_per_sqm", "offices2_price_th_per_sqm",
        defaults={"gba_sqm": 1, "saleable_sqm": 1,
                  "cost_th_per_sqm": 1, "price_th_per_sqm": 1})
    grown = _built(core.STANDALONE_OBJECTS + (extra,))
    added = set(grown) - set(core.DEFAULT_INPUTS)

    # Форма сверяется с уже живущим объектом той же меры и с тем же гаражом:
    # свой список «каким полям быть» разошёлся бы с генератором молча.
    offices = core.standalone_objects(("offices",))[0]
    expected = {key.replace("offices_", "offices2_", 1)
                for key in core.standalone_object_defaults(offices)}
    assert added == expected


def test_the_calendar_and_the_growth_come_from_the_roster_line() -> None:
    """Срок и рост берутся у строки реестра, а не переписываются в поле."""
    for obj in core.STANDALONE_OBJECTS:
        made = core.standalone_object_defaults(obj)
        assert made[f"{obj.prefix}_months"] == obj.default_months
        assert made[f"{obj.prefix}_growth_pre_pct"] == obj.growth_pre_default
        assert made[f"{obj.prefix}_growth_post_pct"] == obj.growth_post_default

    # Предохранитель: у наземного паркинга свой календарь, и если он сравняется
    # с остальными, проверка выше перестанет что-либо различать.
    parking = core.standalone_objects(("above_parking",))[0]
    offices = core.standalone_objects(("offices",))[0]
    assert parking.default_months != offices.default_months


def test_the_garage_fields_are_brought_by_the_garage_flag() -> None:
    """Поля гаража заводит признак, а не память о том, у кого он есть.

    У наземного паркинга своего гаража нет вовсе, а доля гостевых стоит
    только там, где места продаются (решение владельца 06.09.2026).
    """
    seen_garage = seen_bare = False
    for obj in core.STANDALONE_OBJECTS:
        made = core.standalone_object_defaults(obj)
        has_under = f"{obj.prefix}_parking_under_spaces" in made
        has_guest = f"{obj.prefix}_parking_guest_pct" in made
        assert has_under is obj.garage
        assert has_guest is (obj.garage and obj.garage_sellable)
        seen_garage = seen_garage or obj.garage
        seen_bare = seen_bare or not obj.garage
    assert seen_garage and seen_bare, "в реестре нет обоих случаев — сверять нечего"


def test_the_disposition_stands_only_where_the_object_goes_one_way() -> None:
    """Признак «что с объектом дальше» — только у объекта с таким выбором."""
    for obj in core.STANDALONE_OBJECTS:
        made = core.standalone_object_defaults(obj)
        assert (f"{obj.prefix}_disposition" in made) is bool(obj.sale_gate)
    assert any(o.sale_gate for o in core.STANDALONE_OBJECTS)
    assert any(not o.sale_gate for o in core.STANDALONE_OBJECTS)
