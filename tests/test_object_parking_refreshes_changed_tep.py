from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _inputs() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(
        offices_enabled=True,
        offices_parking_under_spaces=0,
        offices_parking_over_spaces=40,
        object_parking_over_area_per_space_sqm=25,
        offices_parking_guest_pct=10,
        _parking_by_hand=["offices"],
    )
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(
        gns=10_000.0,
        total_area=9_400.0,
        useful=6_000.0,
        saleable=6_000.0,
    )
    return t


def test_fresh_tep_on_same_object_replaces_cached_parking_base() -> None:
    """Повторный паркинг не имеет права откатывать свежий пересчёт ТЭП."""
    x = _inputs()
    t = _tep()

    core.apply_object_parking(x, t)
    assert t["offices"]["saleable"] == pytest.approx(5_400.0)

    # Имитируем настоящий сценарий страницы/книги: ТЭП пересчитался, но та же
    # структура dict живёт дальше. Это НОВАЯ база, а не результат прошлого
    # применения паркинга.
    t["offices"].update(
        gns=12_000.0,
        total_area=11_280.0,
        useful=7_200.0,
        saleable=7_200.0,
    )

    core.apply_object_parking(x, t)
    ratio = (12_000.0 - 40 * 25) / 12_000.0
    assert t["offices"]["total_area"] == pytest.approx(11_280.0 * ratio)
    assert t["offices"]["useful"] == pytest.approx(7_200.0 * ratio)
    assert t["offices"]["saleable"] == pytest.approx(7_200.0 * ratio)

    # И следующий проход без нового ТЭП должен быть идемпотентным.
    once = (
        t["offices"]["total_area"],
        t["offices"]["useful"],
        t["offices"]["saleable"],
    )
    core.apply_object_parking(x, t)
    assert (
        t["offices"]["total_area"],
        t["offices"]["useful"],
        t["offices"]["saleable"],
    ) == pytest.approx(once)
