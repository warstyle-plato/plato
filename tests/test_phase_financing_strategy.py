"""Queue funding strategies share one dated, auditable cash waterfall."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


@pytest.fixture(scope="module")
def nagatino():
    preset = json.loads((
        ROOT / "presets" / "КРТ_Варшавское_Нагатинская.json"
    ).read_text(encoding="utf-8"))
    imported = TestClient(core.app).post("/api/project-presets/import", json={
        "preset": preset,
        "mode": "apply",
        "inputs": copy.deepcopy(core.DEFAULT_INPUTS),
        "tep": {},
    }).json()
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, values in imported["applied_tep"].items():
        tep.setdefault(key, {}).update(values)
    return imported, tep


def calculate_nagatino(nagatino, strategy: str, fourth_offset: int | None = None):
    imported, tep = nagatino
    phasing = copy.deepcopy(imported["phasing"])
    phasing["financing_strategy"] = strategy
    if fourth_offset is not None:
        phasing["phases"][3]["start_offset_months"] = fourth_offset
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=imported["applied_inputs"], tep=tep, rates=[], phasing=phasing))


def test_default_nagatino_does_not_spend_future_cash(nagatino):
    """O1 releases cash only when O4 reaches RNS, so none is used beforehand."""
    independent = calculate_nagatino(nagatino, "independent")
    unified = calculate_nagatino(nagatino, "unified_project_cash")
    funding = unified["phase_financing"]

    assert funding["strategy"] == "unified_project_cash"
    assert funding["totals"]["project_cash_used"] == 0.0
    assert funding["transfers"] == []
    assert funding["totals"]["new_bridge"] == pytest.approx(
        independent["phase_financing"]["totals"]["new_bridge"])
    assert unified["consolidated"]["summary"]["financing_cost"] == pytest.approx(
        independent["consolidated"]["summary"]["financing_cost"])


def test_partial_project_cash_leaves_only_the_remainder_to_new_bridge(nagatino):
    bundle = calculate_nagatino(nagatino, "independent", fourth_offset=60)
    phase = bundle["phases"][3]
    inputs = copy.deepcopy(phase["inputs"])
    inputs["_phase_project_cash_schedule"] = {
        phase["result"]["dates"]["project_start"]: 400_000_000.0,
    }
    result = core.calculate(core.CalcRequest(
        inputs=inputs, tep=copy.deepcopy(phase["tep"]), rates=[]))
    finance = result["finance"]
    permit = result["dates"]["permit"]
    pre_rns = sum(
        row["project_costs"] for row in finance["rows"] if row["month"] < permit)

    assert finance["project_cash_used"] == pytest.approx(400_000_000.0, abs=1.0)
    assert finance["bridge_draw_total"] == pytest.approx(
        pre_rns - finance["project_cash_used"] - finance["own_funds_used"], abs=1.0)


def test_cash_received_at_rns_is_not_backdated_into_pre_rns_costs(nagatino):
    bundle = calculate_nagatino(nagatino, "independent", fourth_offset=60)
    phase = bundle["phases"][3]
    inputs = copy.deepcopy(phase["inputs"])
    inputs["_phase_project_cash_schedule"] = {
        phase["result"]["dates"]["permit"]: 400_000_000.0,
    }
    result = core.calculate(core.CalcRequest(
        inputs=inputs, tep=copy.deepcopy(phase["tep"]), rates=[]))
    assert result["finance"]["project_cash_used"] == 0.0


def test_escrow_and_bank_limits_do_not_create_distributable_cash():
    result = {
        "cashflow": {"months": ["2030-01-01"], "equity": [0.0]},
        "finance": {
            "peak_escrow": 1_000_000_000.0,
            "pf_limit": 2_000_000_000.0,
            "calculated_bridge_limit": 3_000_000_000.0,
        },
    }
    assert core._phase_free_cash_schedule(result) == []


def test_earned_cash_replaces_later_queue_bridge_and_recalculates_economics(nagatino):
    """A delayed O4 can use already released O1 cash, not its bank facility."""
    independent = calculate_nagatino(nagatino, "independent", fourth_offset=60)
    unified = calculate_nagatino(nagatino, "unified_project_cash", fourth_offset=60)
    off_row = independent["phase_financing"]["rows"][3]
    on_row = unified["phase_financing"]["rows"][3]

    # Product TEP may change the absolute requirement; the invariant is that
    # already-earned cash replaces exactly the bridge the queue otherwise
    # would have drawn, never a hard-coded historical preset amount.
    assert off_row["new_bridge"] > 0
    assert on_row["project_cash_used"] == pytest.approx(off_row["new_bridge"], abs=1.0)
    assert on_row["new_bridge"] == pytest.approx(0.0, abs=1.0)
    assert on_row["pre_rns_costs"] == pytest.approx(
        on_row["project_cash_used"] + on_row["own_funds"] + on_row["new_bridge"],
        abs=1.0,
    )
    assert on_row["peak_pf"] < off_row["peak_pf"]
    assert unified["consolidated"]["summary"]["financing_cost"] < (
        independent["consolidated"]["summary"]["financing_cost"])
    assert unified["consolidated"]["summary"]["net_profit"] > (
        independent["consolidated"]["summary"]["net_profit"])

    transfers = unified["phase_financing"]["transfers"]
    assert transfers
    assert all(item["from_phase"] < item["to_phase"] for item in transfers)
    assert all(item["cash_month"] <= item["month"] for item in transfers)
    assert sum(item["amount"] for item in transfers) == pytest.approx(
        on_row["project_cash_used"])
    assert set(unified["phase_financing"]["excluded_sources"]) == {
        "escrow", "bridge_limit", "pf_limit", "bank_debt", "future_profit",
    }


def test_first_queue_does_not_receive_all_project_pre_rns_costs(nagatino):
    bundle = calculate_nagatino(nagatino, "independent")
    rows = bundle["phase_financing"]["rows"]
    assert rows[0]["pre_rns_costs"] < sum(row["pre_rns_costs"] for row in rows)
    for phase in bundle["phases"]:
        finance_rows = phase["result"]["finance"]["rows"]
        assert finance_rows[0]["month"] == phase["result"]["dates"]["project_start"]
    consolidated = bundle["consolidated"]["finance"]
    assert consolidated["ending_pf"] == pytest.approx(sum(
        phase["result"]["finance"]["ending_pf"] for phase in bundle["phases"]))
    assert consolidated["peak_pf"] <= sum(
        phase["result"]["finance"]["peak_pf"] for phase in bundle["phases"])


def test_strategy_is_explicit_and_independent_by_default_in_queue_tab():
    page = core.PAGE
    assert "financing_strategy:'independent'" in page
    assert 'id="phaseFinancingIndependent"' in page
    assert 'id="phaseFinancingUnified"' in page
    assert "Независимое финансирование очередей" in page
    assert "Единый денежный поток проекта" in page
    assert "Затраты до РНС" in page
    assert "Свободный cash проекта" in page
    assert "Собственные средства" in page
    assert "Новый БРИДЖ" in page
    assert "ПФ после РНС" in page
    assert "будущая прибыль" in page


def test_preset_import_keeps_strategy_and_defaults_to_independent():
    from project_preset import map_phasing

    base = {
        "enabled": True,
        "phase_count": 2,
        "phases": [{"name": "О1"}, {"name": "О2"}],
    }
    phasing, _ = map_phasing({"phasing": {
        **base, "financing_strategy": "unified_project_cash",
    }})
    assert phasing["financing_strategy"] == "unified_project_cash"

    defaulted, _ = map_phasing({"phasing": base})
    assert defaulted["financing_strategy"] == "independent"
