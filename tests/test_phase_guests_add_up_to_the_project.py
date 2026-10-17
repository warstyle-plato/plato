"""Гостевые места по очередям в сумме равны гостевым проекта.

Очереди делили места подземного паркинга наибольшим остатком, а гостевые —
округлением каждой доли отдельно: 44 места и 4 гостевых на трёх очередях
15/15/14 давали по одному гостевому на очередь, три вместо четырёх, и место
уходило в продажу. Решение владельца (16.10.2026): сумма по очередям = числу
проекта, тем же наибольшим остатком.

Запуск: python3 -m pytest tests/test_phase_guests_add_up_to_the_project.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402

PARKING_PRODUCTS = ("apartments", "ground_commercial", "underground_parking", "storage")


def _phasing(weights: list[float]) -> dict:
    count = len(weights)
    return {
        "enabled": True, "phase_count": count,
        "phases": [{"start_offset_months": 12 * i, "construction_months": 24}
                   for i in range(count)],
        "products": {k: list(weights) for k in PARKING_PRODUCTS},
        "shared_allocation": {}, "cost_inflation_pct": 8, "sales_price_inflation_pct": 8,
    }


def _underground(rows: list[dict]) -> dict:
    return {r["key"]: r for r in rows}["underground_parking"]


@pytest.mark.parametrize("weights", [[34, 33, 33], [28, 22, 19, 16, 15]])
def test_engine_phase_guests_sum_to_the_project(weights) -> None:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update({"vri_region": "msk", "underground_manual_spaces": 44,
                   "_parking_by_hand": ["underground"]})
    single = core._run_authoritative_model(dict(inputs), copy.deepcopy(core.TEP_DEFAULT),
                                           [], None)
    project = _underground(single["consolidated"]["tep"]["rows"])
    assert (project["units"], project["guest_units"]) == (44, 4)

    bundle = core._run_authoritative_model(dict(inputs), copy.deepcopy(core.TEP_DEFAULT),
                                           [], _phasing(weights))
    phases = [_underground(item["result"]["tep"]["rows"]) for item in bundle["phases"]]
    assert sum(p["units"] for p in phases) == 44
    assert sum(p["guest_units"] for p in phases) == 4
    assert all(p["guest_units"] == int(p["guest_units"]) for p in phases)
    consolidated = _underground(bundle["consolidated"]["tep"]["rows"])
    assert consolidated["guest_units"] == 4
    assert consolidated["saleable_units"] == project["saleable_units"]


def test_every_split_keeps_the_total_and_fits_the_phase() -> None:
    for units in range(1, 300, 3):
        for guest in range(0, units + 1, 5):
            for weights in ([55, 45], [34, 33, 33], [32, 26, 22, 20], [28, 22, 19, 16, 15]):
                row = {"units": float(units), "guest_units": float(guest),
                       "transfer_units": float(guest // 2), "gns": units * 37.5}
                allocations = core._integer_phase_allocations(units, weights)
                parts = [core._scale_tep_row_by_units(row, allocations, i)
                         for i in range(len(weights))]
                for key, want in (("guest_units", guest), ("transfer_units", guest // 2)):
                    assert sum(p[key] for p in parts) == want, (units, guest, weights, key)
                for part, allocated in zip(parts, allocations):
                    assert part["guest_units"] <= allocated
