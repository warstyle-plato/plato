"""Площадь гаража, заданная руками, одна и та же в одиночном расчёте и в очередях.

Замер на 77:07:0013006 (10.09.2026): `underground_manual_spaces=666`,
`underground_manual_gns_sqm=15540`, а присланная строка ТЭП несёт норматив
23 310 м². Одиночный расчёт брал 15 540, свод очередей — пропорциональную долю
ПРИСЛАННОЙ строки (23 310): строку делили до того, как привести её к вводным.

Соседние сторожа (`test_phasing_keeps_the_project_tep.py`,
`test_workbook_agrees_with_the_engine_on_queues.py`) кладут в строку то же
число, что и в поле, — на них порядок «делить, потом приводить» неотличим от
верного. Здесь строка и поле расходятся нарочно, как на живом проекте.

Запуск: python3 -m pytest tests/test_manual_garage_reaches_the_queues.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

MANUAL_SPACES = 666
MANUAL_GNS = 15540.0
SENT_GNS = 23310.0  # норматив 35 м²/место — то, что приносит строка ТЭП


def _project() -> tuple[dict, dict]:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(underground_manual_spaces=MANUAL_SPACES,
                  underground_manual_gns_sqm=MANUAL_GNS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["underground_parking"].update(units=MANUAL_SPACES, gns=SENT_GNS,
                                      total_area=SENT_GNS)
    return inputs, tep


def _phasing() -> dict:
    return {
        "enabled": True, "phase_count": 2, "phase_gap_months": 12,
        "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                    "construction_months": 24} for i in range(2)],
        "products": {key: [55, 45] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [], "discrete": {},
    }


def _garage(result: dict) -> dict:
    return next(row for row in result["tep"]["rows"] if row["key"] == "underground_parking")


@pytest.fixture(scope="module")
def surfaces() -> dict:
    inputs, tep = _project()
    single = core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(tep), rows=[]))
    phased = core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(tep), rows=[], phasing=_phasing()))
    return {"single": single, "phased": phased}


def test_the_single_run_takes_the_manual_area(surfaces) -> None:
    row = _garage(surfaces["single"])
    assert row["gns"] == pytest.approx(MANUAL_GNS)
    assert row["units"] == MANUAL_SPACES


def test_the_queues_share_the_manual_area_not_the_sent_row(surfaces) -> None:
    queues = [_garage(phase["result"]) for phase in surfaces["phased"]["phases"]]
    # Предохранитель: одна очередь — не деление, проверка была бы пустой.
    assert len(queues) == 2 and all(row["gns"] > 0 for row in queues)
    assert sum(row["gns"] for row in queues) == pytest.approx(MANUAL_GNS, abs=0.2)
    assert sum(row["units"] for row in queues) == MANUAL_SPACES
    # Свод — то, что читают отчёт и PDF.
    consolidated = _garage(surfaces["phased"]["consolidated"])
    assert consolidated["gns"] == pytest.approx(MANUAL_GNS, abs=0.2)


def test_the_book_writes_the_same_queue_areas() -> None:
    """Книга пишет площадь подземки очереди в «Вводные» (строка «База ГНС
    подземная»): её сумма обязана быть той же заданной руками площадью."""
    openpyxl = pytest.importorskip("openpyxl")
    inputs, tep = _project()
    data, _name, _meta = core.build_project_workbook(inputs, tep, [], _phasing())
    sheet = openpyxl.load_workbook(io.BytesIO(data))["Вводные"]
    row = next(r for r in range(1, sheet.max_row + 1)
               if str(sheet.cell(r, 1).value or "").strip() == "База ГНС подземная")
    values = [float(sheet.cell(row, col).value or 0.0) for col in range(2, 6)]
    assert sum(1 for value in values if value > 0) == 2, values
    assert sum(values) == pytest.approx(MANUAL_GNS, abs=0.2), values
