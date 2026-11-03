"""Пятый элемент поля значит разное, и читать его надо по типу поля.

У «select» там варианты парами, у «schedule» — настройки редактора словарём.
Сборка книги v2 разбирала его по наличию, а не по типу: словарь настроек
разваливался на `too many values to unpack`, и книга не собиралась ВОВСЕ —
восемь проверок методики упали, девяносто три не дошли до счёта. Поломка при
этом жила не в графике и не в книге, а в одной строке разбора поля.

Запуск: python3 -m pytest tests/test_the_fifth_element_of_a_field_is_read_by_kind.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

FIELDS = [f for _group, items in core.FIELD_GROUPS for f in items]


def test_only_a_select_carries_pairs_in_the_fifth_place() -> None:
    """Список пар — принадлежность «select»; у прочих там что угодно своё."""
    for field in FIELDS:
        if len(field) <= 4 or not field[4]:
            continue
        if field[3] == "select":
            for pair in field[4]:
                assert len(list(pair)) == 2, f"{field[0]}: вариант не пара"
        else:
            assert isinstance(field[4], dict), (
                f"{field[0]}: пятый элемент не словарь настроек и не варианты «select»")
