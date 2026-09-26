"""Удельные расходы ОСЗ не делятся на площадь всего проекта.

Регрессия: строка «Отдельные объекты» показывала 132,7 / 244,1 тыс ₽/м²,
а её офисная подстрока — 316,2 / 672,7. Причина — одинаковый числитель
делился сначала на ГНС всего проекта, потом на площадь самого офисника.

Запуск: python3 -m pytest tests/test_standalone_expense_uses_own_area.py -q
"""

from __future__ import annotations

import copy
import inspect

import pytest

import main_legacy as core


def _office_report() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(
        offices_enabled=True,
        offices_gba_sqm=186_180.0,
        offices_saleable_sqm=87_504.6,
        offices_cost_th_per_sqm=200,
        offices_parking_under_spaces=0,
        offices_parking_over_spaces=0,
        _parking_by_hand=["offices"],
    )
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["offices"].update(
        gns=186_180.0,
        total_area=175_009.2,
        useful=87_504.6,
        saleable=87_504.6,
    )
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def test_standalone_group_uses_the_sum_of_its_own_object_areas() -> None:
    result = _office_report()
    group = next(row for row in result["report"]["expense_structure"]
                 if row["label"] == "Отдельные объекты")
    parts = [row for row in group["items"] if row["basis"] == "area"]
    assert parts and not [row for row in group["items"] if row["basis"] == "units"]

    own_gns = sum(row["gns_sqm"] for row in parts)
    own_saleable = sum(row["saleable_sqm"] for row in parts)
    assert group["per_gns_th"] == pytest.approx(group["value"] / own_gns / 1000)
    assert group["per_saleable_th"] == pytest.approx(
        group["value"] / own_saleable / 1000)

    project_gns = result["summary"]["project_gns_sqm"]
    assert own_gns < project_gns
    assert group["per_gns_th"] != pytest.approx(
        group["value"] / project_gns / 1000)


def test_mixed_square_metres_and_parking_spaces_have_no_fake_common_rate() -> None:
    parts = [
        {"basis": "area", "gns_sqm": 100_000, "saleable_sqm": 50_000},
        {"basis": "units", "units": 500},
    ]
    assert core._standalone_group_unit_metrics(30_000_000_000, parts) == (
        None, None)


def test_consolidation_reuses_the_same_standalone_basis_rule() -> None:
    source = inspect.getsource(core._consolidate_phase_results)
    assert "_standalone_group_unit_metrics" in source


def test_screen_and_pdf_render_a_missing_common_rate_as_dash() -> None:
    assert "expenseMetric=v=>(v===null||v===undefined)?'—':num2(v)" in core.PAGE
    source = inspect.getsource(core._build_developaid_pdf)
    assert "'—' if item.get(key) is None" in source
