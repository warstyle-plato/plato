"""Absolute product TEP in queues is authoritative; legacy weights still work."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main_legacy as core  # noqa: E402


def project():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return inputs, tep


def test_absolute_queue_tep_overrides_initial_percentages():
    inputs, tep = project()
    total = float(tep["apartments"]["saleable"])
    phasing = {
        "enabled": True, "phase_count": 2,
        "products": {"apartments": [50, 50]},
        "phases": [
            {"name": "О1", "products": {"apartments": {
                "gns": 60000, "saleable": 45000, "assumption_source": "ППТ"}}},
            {"name": "О2", "products": {"apartments": {
                "gns": 40000, "saleable": 30000, "assumption_source": "ППТ"}}},
        ],
    }
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))
    rows = [next(row for row in item["result"]["tep"]["rows"]
                 if row["key"] == "apartments") for item in bundle["phases"]]
    assert [row["saleable"] for row in rows] == pytest.approx([45000, 30000])
    assert bundle["consolidated"]["summary"]["apartment_saleable_sqm"] == pytest.approx(75000)
    assert total != pytest.approx(75000), "свод должен идти снизу вверх, а не возвращаться к ТЭП проекта"
    assert bundle["phases"][0]["products"]["apartments"]["assumption_source"] == "ППТ"


def test_non_revenue_product_cannot_create_saleable_area():
    inputs, tep = project()
    phasing = {"enabled": True, "phase_count": 2, "phases": [
        {"name": "О1", "products": {"school": {
            "gns": 22220, "total_area": 22220, "saleable": 999,
            "units": 1000, "generates_revenue": False,
            "assumption_source": "условия КРТ"}}},
        {"name": "О2"},
    ]}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))
    school = next(row for row in bundle["phases"][0]["result"]["tep"]["rows"]
                  if row["key"] == "school")
    assert school["saleable"] == 0
    assert school["gns"] == pytest.approx(22220)


def test_office_absolute_tep_reaches_atomic_inputs_and_revenue():
    inputs, tep = project()
    inputs.update(offices_enabled=True, offices_gba_sqm=10000,
                  offices_saleable_sqm=7000, offices_price_th_per_sqm=300)
    tep["offices"].update(gns=10000, total_area=10000, saleable=7000)
    phasing = {"enabled": True, "phase_count": 2, "phases": [
        {"name": "О1", "products": {"offices": {
            "gns": 12000, "saleable": 8000, "generates_revenue": True,
            "assumption_source": "обмер"}}},
        {"name": "О2", "products": {"offices": {
            "gns": 5000, "saleable": 3000, "generates_revenue": True,
            "assumption_source": "обмер"}}},
    ]}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))
    assert [item["inputs"]["offices_saleable_sqm"] for item in bundle["phases"]] == [8000, 3000]
    office = next(item for item in bundle["consolidated"]["report"]["products"]
                  if item["key"] == "offices")
    assert office["quantity"] == pytest.approx(11000)
    assert office["revenue"] > 0


def test_product_result_has_requested_economic_columns():
    inputs, tep = project()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    apartments = next(item for item in result["report"]["products"]
                      if item["key"] == "apartments")
    assert {"gns", "saleable", "avg_price_th", "revenue", "cost", "margin"} <= apartments.keys()
    assert apartments["cost"] > 0


def test_main_tabs_expose_real_phase_tep_and_product_economics():
    """The feature belongs to the production Очередность/Результат tabs."""
    page = core.PAGE
    assert 'id="phaseTepHead"' in page and 'id="phaseTepBody"' in page
    assert "Реальные ТЭП очередей" in page
    assert "setPhaseProductTep" in page
    assert "Продаваемая, м²" in page
    assert "Себестоимость" in page and "Маржа" in page


def test_phase_share_editor_rebalances_all_queues_and_recalculates_real_tep():
    """Edits lock left queues; only queues on the right absorb the remainder."""
    page = core.PAGE
    assert "rebalancePhaseProductShares" in page
    assert "lockedTotal=out.slice(0,index)" in page
    assert "j>index" in page
    assert "phasing.products[k]=rebalancePhaseProductShares" in page
    assert "['gns','total_area','useful','saleable','transfer','units']" in page
    assert "syncPhaseProductSharesFromTep(key,field,index)" in page
    assert "phase.products[key][field]=x" in page
    assert "x/total*100" in page
    assert 'value="${Number(value.toFixed(2))}"' in page
    assert 'readonly title="Автоматический остаток до 100%"' in page
    assert "<small>остаток</small>" in page
    assert "renderPhasing();calculate()" in page


def test_real_tep_editor_caps_values_at_the_remaining_project_total():
    """A queue cannot consume more GNS, saleable area, or units than remain."""
    page = core.PAGE
    assert "function phaseProductTepLimit(key,field,index)" in page
    assert "phaseProductTepValues(key,field).slice(0,index)" in page
    assert "Math.min(limit,requested)" in page
    assert "function clampPhaseProductTepRight(key,field,index)" in page
    assert "rightTotal<=remaining+1e-6" in page
    assert 'max="${Number(limit.toFixed(6))}"' in page
    assert "Значение ограничено до" in page
    assert 'id="phaseTepWarning"' in page
