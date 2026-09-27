"""Соцобъект уходит городу целиком — и метрами, и местами.

Строка ТЭП садика противоречила сама себе: рядом стояли «передано 5 600 м²» и
«продаётся 350 шт.». Механизм «строим, но не продаём» в движке есть — им
работают гостевые места паркинга и переданные машино-места, — но у ДОО, СОШ и
поликлиники переданное жило ТОЛЬКО в метрах, а `saleable_units` вычитает
переданные ШТУКИ. Ноль в них означал «продаются все».

Признака «продаётся / передаётся» у этих трёх нет и не будет (решение
владельца 15.09.2026): они безвозвратны по построению. Значит переданы всегда
все места, и второго механизма для этого не нужно.

Деньги правка не двигает: места соцобъекта ценой не обладают, и выручка с NPV
совпадают до знака после запятой. Здесь закреплено именно то, что стоит на
экране, — противоречие внутри одной строки.

Запуск: python3 -m pytest tests/test_a_social_object_is_handed_over_whole.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

SOCIAL = ("kindergarten", "school", "clinic")


def _result(**overrides):
    inputs = {**core.DEFAULT_INPUTS, "kindergarten_places": 350,
              "school_places": 1000, "clinic_capacity": 120, **overrides}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def _row(result, key):
    return next(r for r in result["tep"]["rows"] if r["key"] == key)


@pytest.mark.parametrize("key, places", [("kindergarten", 350), ("school", 1000),
                                         ("clinic", 120)])
def test_every_place_of_a_social_object_is_handed_over(key, places):
    """Построено — все места, продаётся — ни одного."""
    row = _row(_result(), key)
    assert row["units"] == places, row
    assert row["transfer_units"] == places, "места переданы не все"
    assert row["saleable_units"] == 0, "переданный объект продаётся"


def test_a_row_does_not_hand_over_metres_and_sell_places_at_once():
    """То, что видно на экране: «передано 5 600 м²» и «продаётся 350 шт.».

    Утверждение шире трёх соцобъектов нарочно: это свойство СТРОКИ, а не их
    списка. Заведётся четвёртый передаваемый продукт — проверка встретит его.
    """
    both = [(r["label"], r["transfer"], r["saleable_units"])
            for r in _result()["tep"]["rows"]
            if r["transfer"] > 0 and r["saleable_units"] > 0]
    assert not both, f"строка отдаёт метры и продаёт штуки разом: {both}"


def test_the_sold_total_counts_no_social_place():
    """Итог проданного не считает места ДОО, СОШ и поликлиники."""
    got = _result()
    social = sum(_row(got, key)["units"] for key in SOCIAL)
    assert social > 0, "в стенде нет ни одного соцобъекта — сверять нечего"
    sold = got["tep"]["total"]["saleable_units"]
    built = got["tep"]["total"]["units"]
    assert built - sold >= social, (
        "проданного меньше построенного не на все переданные места")


def test_the_money_does_not_know_about_this():
    """Места соцобъекта ценой не обладают: выручка от их передачи не зависит.

    Сверяется сдвигом самого признака, а не пересчётом с нуля: меняются
    переданные штуки — выручка обязана остаться прежней. Иначе правка,
    задуманная как смысловая, молча двигала бы экономику.
    """
    got = _result()
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    inputs = {**core.DEFAULT_INPUTS, "kindergarten_places": 350,
              "school_places": 1000, "clinic_capacity": 120}
    for key in SOCIAL:
        tep.setdefault(key, {})
    # Тот же расчёт, но признак снят руками у уже собранной строки.
    plain = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    assert got["summary"]["revenue"] == plain["summary"]["revenue"]


def test_money_instead_of_a_building_leaves_no_places():
    """Денежная компенсация — не объект: ни мест, ни переданных метров."""
    got = _result(social_mode="Денежная компенсация", social_compensation_mln=500)
    for key in SOCIAL:
        row = _row(got, key)
        assert row["units"] == 0 and row["transfer_units"] == 0, row
