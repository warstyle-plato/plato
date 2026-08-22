"""КРТ Варшавское / Нагатинская: source TEP, not Rumyantsevo ratios."""

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

PRESET_PATH = ROOT / "presets" / "КРТ_Варшавское_Нагатинская.json"
client = TestClient(core.app)


@pytest.fixture(scope="module")
def imported():
    preset = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
    response = client.post("/api/project-presets/import", json={
        "preset": preset,
        "mode": "apply",
        "inputs": copy.deepcopy(core.DEFAULT_INPUTS),
        "tep": {},
    })
    assert response.status_code == 200, response.text
    data = response.json()
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, values in data["applied_tep"].items():
        tep.setdefault(key, {}).update(values)
    return preset, data, tep


def test_source_components_reconcile_to_ppt_gns(imported):
    preset, _, _ = imported
    controls = preset["validation_controls"]
    assert controls["components_sum_m2"] == 443700
    assert (controls["residential_gns_m2"] + controls["offices_gns_m2"]
            + controls["school_gfa_m2"] + controls["preschool_gfa_m2"]
            + controls["utility_gfa_m2"]) == 443700


def test_purchase_price_is_not_vri(imported):
    preset, data, _ = imported
    inputs = data["applied_inputs"]
    assert inputs["purchase_price_mln"] == pytest.approx(
        preset["validation_controls"]["purchase_price_rub"] / 1e6)
    assert inputs["land_rights_cost_mln"] == 0
    assert inputs["vri_required"] is False
    assert inputs["apartment_price_th"] == 500
    assert inputs["offices_price_th_per_sqm"] == 350
    assert inputs["main_above_th_per_sqm"] == 110
    assert inputs["offices_cost_th_per_sqm"] == 200


def test_explicit_saleable_assumptions_replace_foreign_ratios(imported):
    preset, data, _ = imported
    tep = data["applied_tep"]
    assert tep["apartments"]["gns"] == 229490
    assert tep["apartments"]["saleable"] == 170000
    assert tep["offices"]["gns"] == 185460
    assert tep["offices"]["saleable"] == 150000
    apartment_source = preset["canonical_tep"]["products"]["apartments"]["ratio_source"]
    office_source = preset["canonical_tep"]["products"]["offices"]["ratio_source"]
    assert "explicit user input" in apartment_source
    assert "explicit user input" in office_source
    assert "not a Rumyantsevo coefficient" in apartment_source
    assert "not a Rumyantsevo coefficient" in office_source
    assert tep["underground_parking"]["gns"] == 0
    assert tep["underground_parking"]["units"] == 0
    assert any(note["origin"] == "tbd" and "паркинг" in note["note"].lower()
               for note in data["notes"])


def test_separate_social_objects_keep_their_exact_gfa(imported):
    _, data, _ = imported
    assert data["applied_tep"]["school"]["total_area"] == 22220
    assert data["applied_tep"]["kindergarten"]["total_area"] == 6300


def test_real_product_tep_reaches_every_queue(imported):
    _, data, tep = imported
    phases = data["phasing"]["phases"]
    assert len(phases) == 4
    assert data["phasing"]["products"]["apartments"] == [25, 25, 25, 25]
    assert data["phasing"]["products"]["offices"] == [0, 50, 0, 50]
    assert all("apartments" not in (phase.get("products") or {}) for phase in phases)
    assert all("offices" not in (phase.get("products") or {}) for phase in phases)

    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=data["applied_inputs"], tep=tep, rates=[], phasing=data["phasing"]))
    assert [phase["tep"]["apartments"]["gns"] for phase in bundle["phases"]] == [57372.5] * 4
    assert [phase["tep"]["apartments"]["saleable"] for phase in bundle["phases"]] == [42500] * 4
    assert [phase["tep"]["offices"]["gns"] for phase in bundle["phases"]] == [0, 92730, 0, 92730]
    assert [phase["tep"]["offices"]["saleable"] for phase in bundle["phases"]] == [0, 75000, 0, 75000]
    assert phases[2]["products"]["school"]["gns"] == 22220
    assert phases[2]["products"]["kindergarten"]["gns"] == 6300
    assert phases[2]["products"]["other_mandatory"]["gns"] == 230
    assert phases[2]["products"]["school"]["generates_revenue"] is False
    assert data["phasing"]["social_objects"][0]["phase"] == 3


def test_changed_shares_recalculate_queue_metres(imported):
    _, data, tep = imported
    phasing = copy.deepcopy(data["phasing"])
    phasing["products"]["apartments"] = [45, 30, 15, 10]
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=data["applied_inputs"], tep=tep, rates=[], phasing=phasing))
    assert [phase["tep"]["apartments"]["gns"] for phase in bundle["phases"]] == pytest.approx([
        103270.5, 68847, 34423.5, 22949,
    ])
    assert sum(phase["tep"]["apartments"]["gns"] for phase in bundle["phases"]) == 229490


def test_site_preparation_is_separate_from_new_construction_tep(imported):
    preset, data, _ = imported
    preparation = preset["site_preparation"]
    assert preparation["scope"] == "demolition_or_reconstruction"
    assert preparation["phase"] == 1
    assert preparation["cost_mln"] == "TBD"
    assert preparation["generates_revenue"] is False
    assert preparation["included_in_new_construction_gns"] is False
    assert preparation["included_in_saleable_area"] is False
    assert preparation["unique_capital_objects_count"] == 39
    assert len(preparation["objects"]) == 39
    assert sum(item["listed_area_m2"] for item in preparation["objects"]) == pytest.approx(54871.9)
    phase_preparation = data["phasing"]["phases"][0]["preparation_scope"]
    assert phase_preparation["listed_existing_area_m2"] == 54871.9


def test_consolidation_is_bottom_up_from_queue_products(imported):
    _, data, tep = imported
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=data["applied_inputs"], tep=tep, rates=[], phasing=data["phasing"]))
    assert [phase["result"]["summary"]["project_gns_sqm"] for phase in bundle["phases"]] == [
        57372.5, 150102.5, 86122.5, 150102.5,
    ]
    assert bundle["consolidated"]["summary"]["project_gns_sqm"] == 443700
    products = {row["key"]: row for row in bundle["consolidated"]["report"]["products"]}
    assert products["apartments"]["gns"] == 229490
    assert products["apartments"]["saleable"] == 170000
    assert products["apartments"]["revenue"] > 0
    assert products["offices"]["gns"] == 185460
    assert products["offices"]["saleable"] == 150000
    assert products["offices"]["revenue"] > 0
    assert products["school"]["gns"] == 22220
    assert products["kindergarten"]["gns"] == 6300
    assert products["other_mandatory"]["gns"] == 230
    assert all(products[key]["revenue"] == 0
               for key in ("school", "kindergarten", "other_mandatory"))


def test_cadastral_list_is_explicit_and_deduplicated(imported):
    preset, data, _ = imported
    numbers = data["cadastral_numbers"]
    assert len(numbers) == preset["validation_controls"]["cadastral_numbers_count"]
    assert len(numbers) == len(set(numbers))
