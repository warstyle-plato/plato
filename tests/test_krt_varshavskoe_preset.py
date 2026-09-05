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
    assert (controls["residential_gns_m2"] + controls["shopping_center_gns_m2"]
            + controls["offices_gns_m2"]
            + controls["school_gfa_m2"] + controls["preschool_gfa_m2"]
            + controls["utility_gfa_m2"]) == 443700


def test_purchase_price_is_not_vri(imported):
    preset, data, _ = imported
    inputs = data["applied_inputs"]
    assert inputs["purchase_price_mln"] == pytest.approx(
        preset["validation_controls"]["purchase_price_rub"] / 1e6)
    assert inputs["land_rights_cost_mln"] == 0
    assert inputs["vri_required"] is False
    # The KRT source gives the acquisition right, not product prices/costs.
    # Service defaults may remain on the screen, but the preset must not
    # masquerade them as project data.
    assert set(preset["economics"]) == {"purchase_price_mln", "origins"}
    assert set(preset["economics"]["origins"]) == {"purchase_price_mln"}


def test_explicit_saleable_assumptions_replace_foreign_ratios(imported):
    preset, data, _ = imported
    tep = data["applied_tep"]
    assert tep["apartments"]["gns"] == pytest.approx(215720.6)
    assert tep["apartments"]["saleable"] == pytest.approx(140218.39)
    assert tep["ground_commercial"]["gns"] == pytest.approx(13769.4)
    assert tep["ground_commercial"]["saleable"] == pytest.approx(12392.46)
    assert tep["standalone_retail"]["gns"] == pytest.approx(92730)
    assert tep["standalone_retail"]["saleable"] == pytest.approx(52299.72)
    assert tep["offices"]["gns"] == pytest.approx(92730)
    assert tep["offices"]["saleable"] == pytest.approx(52299.72)
    apartment_source = preset["canonical_tep"]["products"]["apartments"]["ratio_source"]
    retail_source = preset["canonical_tep"]["products"]["shopping_center"]["ratio_source"]
    office_source = preset["canonical_tep"]["products"]["offices"]["ratio_source"]
    assert "ГлавАПУ" in apartment_source
    assert "Рабочая предпосылка" in retail_source
    assert "Рабочая предпосылка" in office_source
    assert tep["underground_parking"]["gns"] == pytest.approx(101710)
    assert tep["underground_parking"]["units"] == 2906
    assert not any(note["origin"] == "tbd" and "паркинг" in note["note"].lower()
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
    assert data["phasing"]["products"]["ground_commercial"] == [25, 25, 25, 25]
    assert data["phasing"]["products"]["underground_parking"] == pytest.approx([
        446 / 2906 * 100, 1051 / 2906 * 100, 445 / 2906 * 100, 964 / 2906 * 100,
    ])
    assert data["phasing"]["discrete"] == {"standalone_retail": 2, "offices": 4}
    assert all("apartments" not in (phase.get("products") or {}) for phase in phases)
    assert all("offices" not in (phase.get("products") or {}) for phase in phases)

    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=data["applied_inputs"], tep=tep, rates=[], phasing=data["phasing"]))
    assert [phase["tep"]["apartments"]["gns"] for phase in bundle["phases"]] == pytest.approx([53930.15] * 4)
    assert [phase["tep"]["apartments"]["saleable"] for phase in bundle["phases"]] == pytest.approx([35054.5975] * 4)
    assert [phase["tep"]["ground_commercial"]["gns"] for phase in bundle["phases"]] == pytest.approx([3442.35] * 4)
    assert [phase["tep"]["standalone_retail"]["gns"] for phase in bundle["phases"]] == [0, 92730, 0, 0]
    assert [phase["tep"]["offices"]["gns"] for phase in bundle["phases"]] == [0, 0, 0, 92730]
    assert [phase["tep"]["underground_parking"]["units"] for phase in bundle["phases"]] == [446, 1051, 445, 964]
    assert phases[2]["products"]["school"]["gns"] == 22220
    assert phases[1]["products"]["kindergarten"]["gns"] == 6300
    assert phases[2]["products"]["other_mandatory"]["gns"] == 230
    assert phases[2]["products"]["school"]["generates_revenue"] is False
    assert {item["type"]: item["phase"] for item in data["phasing"]["social_objects"]} == {
        "school": 3, "kindergarten": 2,
    }


def test_changed_shares_recalculate_queue_metres(imported):
    _, data, tep = imported
    phasing = copy.deepcopy(data["phasing"])
    phasing["products"]["apartments"] = [45, 30, 15, 10]
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=data["applied_inputs"], tep=tep, rates=[], phasing=phasing))
    assert [phase["tep"]["apartments"]["gns"] for phase in bundle["phases"]] == pytest.approx([
        97074.27, 64716.18, 32358.09, 21572.06,
    ])
    assert sum(phase["tep"]["apartments"]["gns"] for phase in bundle["phases"]) == pytest.approx(215720.6)


def test_site_preparation_is_separate_from_new_construction_tep(imported):
    preset, data, _ = imported
    preparation = preset["site_preparation"]
    assert preparation["scope"] == "demolition_or_reconstruction"
    assert preparation["phase"] == 1
    assert preparation["cost_mln"] == pytest.approx(823.0785)
    assert preparation["unit_cost_th_per_m2"] == 15
    assert preparation["owner_buyout_compensation_mln"] == "TBD"
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
    products = {row["key"]: row for row in bundle["consolidated"]["report"]["products"]}
    assert products["apartments"]["gns"] == pytest.approx(215720.6)
    assert products["apartments"]["saleable"] == pytest.approx(140218.39)
    assert products["apartments"]["revenue"] > 0
    assert products["ground_commercial"]["gns"] == pytest.approx(13769.4)
    assert products["standalone_retail"]["gns"] == pytest.approx(92730)
    assert products["offices"]["gns"] == pytest.approx(92730)
    assert products["offices"]["saleable"] == pytest.approx(52299.72)
    assert products["offices"]["revenue"] > 0
    assert products["school"]["gns"] == 22220
    assert products["kindergarten"]["gns"] == 6300
    assert products["other_mandatory"]["gns"] == 230
    # The PPT GNS remains 443,700 m².  Underground parking is a separate
    # 101,710 m² construction area and is never used to reconcile the PPT.
    official_gns = sum(products[key]["gns"] for key in (
        "apartments", "ground_commercial", "standalone_retail", "offices",
        "school", "kindergarten", "other_mandatory",
    ))
    assert official_gns == pytest.approx(443700)
    assert products["underground_parking"]["gns"] == pytest.approx(101710)
    # ГНС проекта — НАЗЕМНАЯ площадь, и она сходится с ППТ до метра: подземный
    # паркинг в неё не входит (решение владельца, 04.09.2026). Строительный
    # объём — их сумма, и он назван своим полем; пока ГНС включала подземную,
    # она была на 101 710 м² больше того, что стоит в документе города.
    summary = bundle["consolidated"]["summary"]
    assert summary["project_gns_sqm"] == pytest.approx(official_gns)
    assert summary["underground_gns_sqm"] == pytest.approx(
        products["underground_parking"]["gns"])
    assert summary["construction_volume_sqm"] == pytest.approx(
        official_gns + products["underground_parking"]["gns"])
    assert all(products[key]["revenue"] == 0
               for key in ("school", "kindergarten", "other_mandatory"))


def test_cadastral_list_is_explicit_and_deduplicated(imported):
    preset, data, _ = imported
    numbers = data["cadastral_numbers"]
    assert len(numbers) == preset["validation_controls"]["cadastral_numbers_count"]
    assert len(numbers) == len(set(numbers))
