"""Правка мест подземного паркинга в /v2 пересчитывает гостевые.

Ячейка мест оставляла в строке прежнее `guest_units` записи: на 44 местах
стояло 109 гостевых — число давно сменившихся вводных, больше самих мест.
Гостевые — производное мест, и отвечает за них движок (`underground_tep_row`).

Запуск: python3 -m pytest tests/test_v2_parking_edit_recounts_the_guests.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
from developaid_v2_account_projects import TepSyncRequest, _sync_tep  # noqa: E402


def _edit(field: str, value: float, **inputs) -> dict:
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["underground_parking"].update({"guest_units": 109, "guest_units_stale": 109})
    return _sync_tep(core, TepSyncRequest(
        inputs={**core.DEFAULT_INPUTS, "_parking_by_norm": ["underground"], **inputs},
        tep=tep, row_key="underground_parking", field_key=field, value=value))


@pytest.mark.parametrize("field, value", [("units", 44), ("gns", 44 * 35)])
def test_moscow_guests_follow_the_edited_spaces(field, value) -> None:
    got = _edit(field, value, vri_region="msk")
    row = got["tep"]["underground_parking"]
    assert row["units"] == 44
    want = core.underground_guest_spaces({"units": 44})
    assert want == 4
    assert row["guest_units"] == want
    assert "guest_units_stale" not in row
    # Правка — решение человека: движок читает пару как ручную.
    assert core.underground_parking_by_hand(got["inputs"])


def test_the_engine_reads_the_same_guests() -> None:
    got = _edit("units", 44, vri_region="msk")
    bundle = core._run_authoritative_model(got["inputs"], got["tep"], [], None)
    row = next(r for r in bundle["consolidated"]["tep"]["rows"]
               if r["key"] == "underground_parking")
    assert (row["units"], row["guest_units"]) == (44, got["tep"]["underground_parking"]["guest_units"])


def test_the_moscow_oblast_has_no_guests() -> None:
    row = _edit("units", 44, vri_region="mo")["tep"]["underground_parking"]
    assert row["guest_units"] == 0
