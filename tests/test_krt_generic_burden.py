from __future__ import annotations

from pathlib import Path

import pytest

from auction_search import krt_investment_score as score


class FakeCore:
    def _land_lookup_by_numbers(self, numbers):
        rows = {
            "77:01:0000001:1": {
                "found": True,
                "cadastral_number": "77:01:0000001:1",
                "kind": "land",
                "ownership": "Частная собственность",
                "cadastral_value_rub": 100_000_000,
            },
            "77:01:0000001:2": {
                "found": True,
                "cadastral_number": "77:01:0000001:2",
                "kind": "building",
                "ownership": "Собственность города Москвы",
                "cadastral_value_rub": 500_000_000,
            },
        }
        return [rows[number] for number in numbers if number in rows]

    def _run_authoritative_model(self, inputs, tep, rates, phasing):
        social = (
            float(inputs.get("kindergarten_places") or 0)
            * float(inputs.get("kindergarten_cost_mln_per_place") or 0)
            + float(inputs.get("school_places") or 0)
            * float(inputs.get("school_cost_mln_per_place") or 0)
            + float(inputs.get("clinic_capacity") or 0)
            * float(inputs.get("clinic_cost_mln_per_unit") or 0)
        )
        demolition = (
            float(inputs.get("demolition_area_sqm") or 0)
            * float(inputs.get("demolition_cost_th_per_sqm") or 0) / 1000.0
        )
        burden = (
            float(inputs.get("purchase_price_mln") or 0)
            + social + demolition
            + float(inputs.get("resettlement_cost_mln") or 0)
            + float(inputs.get("social_compensation_mln") or 0)
            + float(inputs.get("land_rights_cost_mln") or 0)
        )
        capex_mln = 1000.0 + social + demolition
        llcr = 1.40 - burden / 1000.0
        return {
            "consolidated": {
                "summary": {
                    "capex": capex_mln * 1_000_000,
                    "llcr": llcr,
                    "revenue": 2_000_000_000,
                    "net_profit": 300_000_000,
                    "margin": 0.15,
                },
                "finance": {},
            },
            "phases": [],
        }


def screening(*, cadastral_value_missing: bool = False, conditional: int = 0):
    return {
        "available": True,
        "requirements": {
            "available": True,
            "decision_available": True,
            "cadastral_numbers": ["77:01:0000001:1", "77:01:0000001:2"],
            "cadastral_numbers_source": "appendix",
            "demolition_objects": 1,
            "demolition_known_area_objects": 1,
            "demolition_area_sqm": 1000.0,
            "conditional_objects": conditional,
            "resettlement": [],
            "unmodelled_construction": [],
        },
        "model_inputs": {
            "inputs": {
                "purchase_price_mln": 0.0,
                "land_rights_cost_mln": 0.0,
                "social_compensation_mln": 0.0,
                "resettlement_cost_mln": 0.0,
                "demolition_area_sqm": 1000.0,
                "demolition_cost_th_per_sqm": 0.0,
                "kindergarten_places": 100.0,
                "kindergarten_cost_mln_per_place": 2.0,
                "school_places": 0.0,
                "school_cost_mln_per_place": 3.0,
                "clinic_capacity": 0.0,
                "clinic_cost_mln_per_unit": 1.0,
                "vri_required": False,
                "vri_security_cost_mln": 0.0,
            },
            "tep": {
                "kindergarten": {"units": 1.0, "gns": 1000.0},
                "school": {"units": 0.0, "gns": 0.0},
                "clinic": {"units": 0.0, "gns": 0.0},
                "other_mandatory": {"units": 0.0, "gns": 0.0},
            },
            "phasing": {},
        },
    }


def test_generic_burden_uses_private_cadastral_value_and_zeroes_moscow(tmp_path: Path):
    core = FakeCore()
    result = score.generic_project_burden(
        core,
        {"slug": "decision:1"},
        screening(),
        cache_root=tmp_path,
        lookup_chunk=10,
        compute_entry_capacity=False,
    )

    assert result["available"] is True
    # 100 млн private buyout + 15 млн demolition + 200 млн kindergarten.
    assert result["burden_mln"] == pytest.approx(315.0)
    assert result["ordinary_capex_mln"] == pytest.approx(1000.0)
    assert result["burden_pct"] == pytest.approx(31.5)
    assert result["components"]["cadastral_buyout"]["moscow_zero_count"] == 1
    assert result["components"]["cadastral_buyout"]["paid_count"] == 1
    # Baseline LLCR is recalculated with the same burden, not the old zero-entry row.
    assert result["project_llcr_x"] == pytest.approx(1.085)


def test_generic_burden_stays_unknown_when_treatment_is_conditional(tmp_path: Path):
    result = score.generic_project_burden(
        FakeCore(),
        {"slug": "decision:2"},
        screening(conditional=1),
        cache_root=tmp_path,
        lookup_chunk=10,
        compute_entry_capacity=False,
    )

    assert result["available"] is False
    assert result["pending"] is False
    assert "снос/реконструкция" in result["reason"]


def test_generic_burden_reads_egrn_in_persistent_chunks(tmp_path: Path):
    core = FakeCore()
    first = score.generic_project_burden(
        core,
        {"slug": "decision:3"},
        screening(),
        cache_root=tmp_path,
        lookup_chunk=1,
        compute_entry_capacity=False,
    )
    second = score.generic_project_burden(
        core,
        {"slug": "decision:3"},
        screening(),
        cache_root=tmp_path,
        lookup_chunk=1,
        compute_entry_capacity=False,
    )

    assert first["available"] is False
    assert first["pending"] is True
    assert second["available"] is True


def test_ambiguous_public_ownership_is_not_assumed_to_be_moscow(tmp_path: Path):
    core = FakeCore()

    def lookup(numbers):
        return [{
            "found": True,
            "cadastral_number": number,
            "kind": "land",
            "ownership": "Собственность публично-правовых образований",
            "cadastral_value_rub": 50_000_000,
        } for number in numbers]

    core._land_lookup_by_numbers = lookup
    data = screening()
    data["requirements"]["cadastral_numbers"] = ["77:01:0000001:9"]

    result = score.generic_project_burden(
        core,
        {"slug": "decision:4"},
        data,
        cache_root=tmp_path,
        lookup_chunk=10,
        compute_entry_capacity=False,
    )

    assert result["available"] is False
    assert "собственность Москвы" in result["reason"]
