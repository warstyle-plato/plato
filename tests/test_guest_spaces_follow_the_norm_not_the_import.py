"""Гостевые места считаются нормой от квартир и в ручной ветке паркинга.

Страница кладёт норму в поля «машино-места / площадь подземной парковки», и
движок видит их как заданные руками. В этой ветке гостевые не пересчитывались:
строка несла число выгрузки ГлавАПУ. На проекте с 69 местами (62 постоянных +
7 гостевых по 2118-ПП) в ТЭП стояло «из них гостевых 109», продаваемых мест
выходило ноль, и выручка подземного паркинга пропадала целиком.

Запуск: python3 -m pytest tests/test_guest_spaces_follow_the_norm_not_the_import.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _project():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["apartments"].update({"saleable": 5327.3, "gns": 7687.3, "units": 54})
    # Строка несёт гостевые прежнего, большого ТЭП выгрузки.
    tep["underground_parking"].update({"units": 1199, "guest_units": 109, "gns": 40000})
    inputs.update(
        underground_area_per_space_sqm=40,
        underground_manual_spaces=0,
        underground_manual_gns_sqm=0,
        _glavapu_import={"normalized": {"parking_permanent": 1090, "parking_guest": 109}},
    )
    return inputs, tep


@pytest.mark.parametrize("manual", [
    {},
    {"underground_manual_gns_sqm": 2760},
    {"underground_manual_spaces": 69},
    {"underground_manual_spaces": 69, "underground_manual_gns_sqm": 2760},
    {"underground_manual_spaces": 69, "underground_manual_gns_sqm": 2760,
     "_parking_by_norm": ["underground"]},
])
def test_guest_spaces_come_from_the_norm_in_every_branch(manual):
    inputs, tep = _project()
    inputs.update(manual)
    core.apply_underground_tep_row(inputs, tep)
    row = tep["underground_parking"]
    assert row["units"] == 69
    assert core.underground_guest_spaces(row) == 7
    assert core.underground_saleable_spaces(row) == 62


@pytest.mark.parametrize("spaces", [69, 300])
def test_a_garage_set_by_hand_takes_guest_spaces_from_the_norm_too(spaces):
    """Число строки не переживает ручной гараж: гостевые — требование нормы."""
    inputs, tep = _project()
    inputs.update(underground_manual_spaces=spaces, _parking_by_hand=["underground"])
    core.apply_underground_tep_row(inputs, tep)
    row = tep["underground_parking"]
    assert core.underground_guest_spaces(row) == 7
    assert core.underground_saleable_spaces(row) == spaces - 7


def test_guest_spaces_never_exceed_built_spaces():
    assert core.underground_guest_spaces({"units": 69, "guest_units": 109}) == 69
    assert core.underground_guest_spaces({"units": 400, "guest_units": 40}) == 40


def test_underground_parking_earns_revenue_when_the_page_stored_the_norm():
    inputs, tep = _project()
    inputs.update(underground_manual_spaces=69, underground_manual_gns_sqm=2760,
                  parking_price_th=20000)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    row = next(r for r in result["tep"]["rows"] if r["key"] == "underground_parking")
    assert row["guest_units"] == 7
    assert row["saleable_units"] == 62
    assert result["revenue"]["underground_parking"] > 62 * 20_000_000 * 0.99
