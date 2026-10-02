"""«Продаваемая площадь» — то, что реально продаётся метрами.

Отчёт считал её по списку продуктов и не видел проданного ФОК, а тизер,
первая страница PDF и бот складывали колонку «Продаваемая» всех строк ТЭП,
не спрашивая, продаётся ли строка («то, что реально продаётся», владелец,
29.09.2026). Ответ один — `sold_saleable_sqm`, и все поверхности читают его.

Запуск: python3 -m pytest tests/test_the_saleable_area_is_what_is_sold.py -q
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _tep() -> dict:
    return {
        "apartments": {"saleable": 1000.0},
        "ground_commercial": {"saleable": 100.0},
        "offices": {"saleable": 50.0},
        "sports": {"saleable": 30.0},
        "underground_parking": {"saleable": 999.0},
        "storage": {"saleable": 7.0},
        "kindergarten": {"saleable": 5.0},
    }


def test_a_sold_sports_centre_is_sold_by_the_metre() -> None:
    sold = {"sports_enabled": True, "sports_disposition": core.SPORTS_DISPOSITION_SALE}
    assert core.sold_saleable_sqm(_tep(), sold) == pytest.approx(1180.0)


def test_a_transferred_sports_centre_is_not_sold() -> None:
    given = {"sports_enabled": True, "sports_disposition": core.SPORTS_DISPOSITION_TRANSFER}
    assert core.sold_saleable_sqm(_tep(), given) == pytest.approx(1150.0)
    # Отсутствующий признак — не «продаём»: движок читает его передачей.
    assert core.sold_saleable_sqm(_tep(), {"sports_enabled": True}) == pytest.approx(1150.0)
    # Выключенный объект не продаётся, что бы ни стояло в признаке.
    off = {"sports_enabled": False, "sports_disposition": core.SPORTS_DISPOSITION_SALE}
    assert core.sold_saleable_sqm(_tep(), off) == pytest.approx(1150.0)


def test_every_surface_reads_the_same_answer() -> None:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    report = core._run_authoritative_model(inputs, tep, [], None)
    summary = report["consolidated"]["summary"]
    model = core.project_presentation(report, inputs, tep, None)
    assert model["tep"]["saleable_sqm"] == pytest.approx(summary["monetizable_saleable_sqm"])
    result = core.calculate(core.CalcRequest(inputs=copy.deepcopy(inputs),
                                             tep=copy.deepcopy(tep), rates=[]))
    assert result["summary"]["monetizable_saleable_sqm"] == pytest.approx(
        core.sold_saleable_sqm(tep, inputs))
