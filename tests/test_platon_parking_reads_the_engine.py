"""Платон сверяет паркинг по ответу движка и нормативу проекта, а не по полю.

Проверка «паркинг не совпадает с ГлавАПУ» (`PARKING_MISMATCH`) и след метрики
«parking» читали присланный ТЭП — поле страницы, а не ответ расчёта, — и
держали 35 м² на место: при нормативе 37,5 паркинг, совпадающий с городом
место в место, объявлялся расхождением (201 × 2,5 = 502,5 м²).

Запуск: python3 -m pytest tests/test_platon_parking_reads_the_engine.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

APARTMENTS = {"gns": 15133.3, "total_area": 13620, "useful": 13620, "saleable": 13620,
              "transfer": 0, "units": 227}


def _project(spaces_in_the_field: float, by_hand: bool) -> tuple[dict, dict]:
    inputs = {**core.DEFAULT_INPUTS, "underground_area_per_space_sqm": 37.5,
              "_glavapu_import": {"normalized": {
                  "parking_permanent": 182, "parking_guest": 19,
                  "apartment_area_sqm": 13620, "apartment_units": 227}}}
    if by_hand:
        inputs.update({"_parking_by_hand": ["underground"],
                       "underground_manual_spaces": spaces_in_the_field})
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["apartments"] = dict(APARTMENTS)
    # Поле страницы — устаревшее: движок его пересчитывает.
    tep["underground_parking"] = {**tep["underground_parking"],
                                  "units": spaces_in_the_field, "gns": spaces_in_the_field * 35}
    return inputs, tep


def _run(inputs: dict, tep: dict) -> tuple[list[str], dict]:
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    request = core.AgentChatRequest(message="паркинг", inputs=inputs, tep=tep, rates=[], phasing={})
    codes = [a["code"] for a in core._tool_find_anomalies(request, bundle, "all")["anomalies"]]
    trace = core._tool_trace_metric(request, bundle, "parking", "all")
    return codes, trace


def test_a_garage_matching_the_city_is_not_a_mismatch() -> None:
    codes, trace = _run(*_project(150, by_hand=False))
    assert trace["model_value"]["spaces"] == 201, trace
    assert trace["model_value"]["gns_sqm"] == 7537.5, trace
    assert trace["model_value"]["guest_spaces"] == 19, trace
    assert "PARKING_MISMATCH" not in codes


def test_a_real_shortfall_is_still_named() -> None:
    codes, trace = _run(*_project(150, by_hand=True))
    assert trace["model_value"]["spaces"] == 150, trace
    assert "PARKING_MISMATCH" in codes
