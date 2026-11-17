"""Fictional Moscow project: native MPT geography must reach v4 relief B82."""
from __future__ import annotations

import copy
import io
import json
import sys

import openpyxl
import pytest

import main as wrapper
from xlsx_eval import Evaluator

core = wrapper.core


def fictional(source="analysis", right="ownership", offset=37):
    x = {**copy.deepcopy(core.DEFAULT_INPUTS),
         "vri_region": "msk", "land_right": right,
         "land_rights_cost_mln": 6000, "vri_transfer_offset_mln": offset,
         "vri_payment_mode": "lump", "vri_obligation_date": "2028-05-15",
         "social_mode": "Денежная компенсация", "social_compensation_mln": 0,
         "kindergarten_places": 0, "school_places": 0, "clinic_capacity": 0,
         "offices_enabled": True, "offices_gba_sqm": 24000, "offices_saleable_sqm": 21600}
    territory = {"district": "Нагатино-Садовники", "inside_ttc": False,
                 "cadastral_quarter": "77:05:0004001"}
    if source == "analysis":
        x["_cadastral_analysis"] = {"recognized": ["77:00:0000000:2"], "territory": territory}
    elif source == "import":
        x["_glavapu_import"] = {"territory": territory,
                                "normalized": {"cadastral_quarter": territory["cadastral_quarter"]}}
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["apartments"]["transfer"] = 937.25
    t["offices"] = {"gns": 24000, "total_area": 21600, "saleable": 21600}
    for key in ("kindergarten", "school", "clinic"):
        t[key] = {"gns": 0, "total_area": 0, "saleable": 0, "units": 0}
    return x, t


@pytest.mark.parametrize("source,right", [("analysis", "ownership"), ("import", "lease")])
def test_actual_v4_mpt_relief_and_principal_match_native(source, right):
    x, t = fictional(source, right)
    before = copy.deepcopy((x, t))
    native = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    benefits = native["vri"]["benefits"]
    assert benefits["mpt_mln"] > 0 and benefits["transfer_mln"] > 0
    assert native["capex"]["land_rights"] == pytest.approx(
        (6000 - benefits["total_mln"] - 37) * 1e6, abs=0.02, rel=0)
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Fictional MPT geography")
    assert not meta["missing"], meta["missing"]
    wb = openpyxl.load_workbook(io.BytesIO(content))
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(wb)
    assert wb["ВРИ"]["B12"].data_type == "f"
    assert float(evaluator.cell("ВРИ", "B12")) * 1e6 == pytest.approx(
        native["capex"]["land_rights"], abs=0.51, rel=0)
    assert (x, t) == before


@pytest.mark.parametrize("inputs", [
    {},
    {"_cadastral_analysis": {"recognized": ["77:00:0000000:2"], "territory": {
        "district": "Нагатино-Садовники", "inside_ttc": False, "cadastral_quarter": "77:05:0004001"}}},
    {"_cadastral_analysis": {"requested": ["77:00:0000000:3"], "territory": {"inside_ttc": True}}},
    {"_glavapu_import": {"territory": {"district": "Даниловский", "inside_ttc": False},
                         "normalized": {"cadastral_quarter": "77:05:0004001"}}},
    {"_glavapu_import": {"normalized": {"district": "Даниловский", "cadastral_quarter": "77:05:0004001"}}},
    {"_cadastral_analysis": {"territory": {"inside_ttc": False, "inside_ttc_known": False}}},
    {"_cadastral_analysis": {"territory": {"district": "Нагатино-Садовники", "inside_ttc_known": False,
                                          "cadastral_quarter": "77:05:0004001"}},
     "_glavapu_import": {"territory": {"district": "Даниловский", "inside_ttc": True},
                         "normalized": {"cadastral_quarter": "77:05:0004002"}}},
    {"parking_district": "Даниловский", "parking_inside_ttk": "inside",
     "_cadastral_analysis": {"territory": {"district": "Нагатино-Садовники", "inside_ttc": False}}},
    {"parking_inside_ttk": "outside", "_glavapu_import": {"territory": {"inside_ttc": True}}},
    {"_cadastral_analysis": {"territory": None}, "_glavapu_import": {"territory": {"inside_ttc": False}}},
])
def test_projection_keeps_canonical_priorities_unknowns_and_provenance(inputs):
    x = copy.deepcopy(inputs)
    x["_unrelated_private"] = "DROP_THIS_CONTEXT"
    for source in ("_cadastral_analysis", "_glavapu_import"):
        if isinstance(x.get(source), dict):
            x[source]["unrelated_money_or_document"] = "DROP_THIS_CONTEXT"
            for section in ("territory", "normalized"):
                if isinstance(x[source].get(section), dict):
                    x[source][section]["unrelated"] = "DROP_THIS_CONTEXT"
    before = copy.deepcopy(x)
    snapshot = core.site_position.source_inputs(x)
    reduced = {key: value for key, value in x.items() if not key.startswith("_")}
    reduced.update(snapshot)
    assert core.site_position.site_position(reduced) == core.site_position.site_position(x)
    assert set(snapshot) <= {"_cadastral_analysis", "_glavapu_import"}
    assert "DROP_THIS_CONTEXT" not in json.dumps(snapshot)
    assert x == before
    for value in snapshot.values():
        if isinstance(value, dict):
            value["fictional_mutation"] = True
    assert x == before, "projection must not alias the caller's source dictionaries"


def test_manual_inside_ttk_still_blocks_mpt_in_actual_v4():
    x, t = fictional()
    x["parking_inside_ttk"] = "inside"
    native = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    assert native["vri"]["benefits"]["mpt_mln"] == 0
    assert native["vri"]["benefits"]["transfer_mln"] > 0
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Fictional manual TTK")
    assert not meta["missing"], meta["missing"]
    wb = openpyxl.load_workbook(io.BytesIO(content))
    sys.setrecursionlimit(400000)
    assert float(Evaluator(wb).cell("ВРИ", "B12")) * 1e6 == pytest.approx(
        native["capex"]["land_rights"], abs=0.51, rel=0)


def test_actual_phased_v4_geography_agrees_with_native_without_the_separate_offset_bug():
    # The independent once-offset repair is deliberately not part of this
    # branch. Zero offset isolates cadastral MPT geography on current main.
    x, t = fictional(offset=0)
    weights = [23, 35, 42]
    p = {"enabled": True, "phase_count": 3,
         "phases": [{"name": f"Fictional {index + 1}", "start_offset_months": index * 9,
                     "construction_months": 24} for index in range(3)],
         "shared_cash": {"land_rights": weights}, "cost_inflation_pct": 0, "sales_price_inflation_pct": 0}
    native = core.calculate_phased(core.PhasedCalcRequest(inputs=x, tep=t, rates=[], phasing=p))
    assert native["vri"]["benefits"]["mpt_mln"] > 0
    content, _, meta = core.build_project_workbook(x, t, [], p, project_name="Fictional phased MPT")
    assert not meta["missing"], meta["missing"]
    wb = openpyxl.load_workbook(io.BytesIO(content))
    sys.setrecursionlimit(400000)
    ev = Evaluator(wb)
    for index, item in enumerate(native["phases"]):
        coordinate = f"B{12 + 13 * index}"
        assert wb["ВРИ"][coordinate].data_type == "f"
        assert float(ev.cell("ВРИ", coordinate)) * 1e6 == pytest.approx(
            item["result"]["capex"]["land_rights"], abs=0.51, rel=0)
