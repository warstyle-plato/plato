"""Fictional project: project reliefs are deducted before the queue split, once.

Exercise native calculate/calculate_phased and the formulas of a generated v4
book. No saved project, original upload, provider or external service is used.
"""
from __future__ import annotations

import copy
import io
import sys

import openpyxl
import pytest

import main as wrapper
from xlsx_eval import Evaluator

core = wrapper.core


def project(**overrides):
    inputs = {**copy.deepcopy(core.DEFAULT_INPUTS),
              "vri_region": "mo", "land_right": "ownership",
              "land_rights_cost_mln": 90, "mo_vri_compensation_mln": 10,
              "vri_transfer_offset_mln": 30,
              "vri_obligation_date": "2028-06-01", "vri_payment_mode": "lump",
              "social_mode": "Денежная компенсация", "social_compensation_mln": 0,
              "kindergarten_places": 0, **overrides}
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["apartments"]["transfer"] = 1234.5
    # Monetary social compensation builds no social object. Keep the fictional
    # raw TEP canonical too, including the base before queue preparation.
    for key in ("kindergarten", "school", "clinic"):
        tep[key] = {"gns": 0, "total_area": 0, "saleable": 0, "units": 0}
    return inputs, tep


def phasing(weights):
    return {"enabled": True, "phase_count": len(weights),
            "phases": [{"name": f"Fictional {index + 1}",
                        "start_offset_months": index * 12, "construction_months": 24}
                       for index in range(len(weights))],
            "shared_cash": {"land_rights": weights},
            "cost_inflation_pct": 0, "sales_price_inflation_pct": 0}


CASES = [
    ([100], "ownership", 90, 30),
    ([100, 0], "lease", 90, 30),  # previously 60m allocated, then 30m deducted again
    ([40, 60], "ownership", 90, 30),
    ([17, 29, 54], "lease", 90, 30),
    ([40, 60], "lease", 90, 0),
    ([17, 29, 54], "ownership", 90, 0),
    ([40, 60], "ownership", 90, 150),
    ([17, 29, 54], "lease", 90, 150),
    ([40, 60], "lease", 0.000001, 0.00000025),  # 1 ruble less 25 kopecks
    ([17, 29, 54], "ownership", 12.34567875, 1.23456725),
]


@pytest.mark.parametrize("weights,right,fee,offset", CASES)
def test_native_phase_principal_conserves_the_master(weights, right, fee, offset):
    x, t = project(land_right=right, land_rights_cost_mln=fee,
                   vri_transfer_offset_mln=offset)
    before = (x["land_rights_cost_mln"], x["vri_transfer_offset_mln"], t["apartments"]["transfer"])
    master = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    req = core.PhasedCalcRequest(inputs=x, tep=t, rates=[], phasing=phasing(weights))
    bundle = core.calculate_phased(req)
    expected = max(0, fee - offset) * 1e6
    assert master["capex"]["land_rights"] == pytest.approx(expected, abs=1e-5, rel=0)
    assert bundle["consolidated"]["capex"]["land_rights"] == pytest.approx(expected, abs=1e-5, rel=0)
    assert bundle["consolidated"]["vri"]["totals"]["principal"] == pytest.approx(expected, abs=0.02, rel=0)
    assert (req.inputs["land_rights_cost_mln"], req.inputs["vri_transfer_offset_mln"],
            req.tep["apartments"]["transfer"]) == before
    assert (x["land_rights_cost_mln"], x["vri_transfer_offset_mln"],
            t["apartments"]["transfer"]) == before, "calculation must not erase the user's offset or TEP"
    for item, weight in zip(bundle["phases"], weights):
        assert item["inputs"]["vri_transfer_offset_mln"] == offset
        assert item["result"]["capex"]["land_rights"] == pytest.approx(expected * weight / 100, abs=1e-5, rel=0)
        assert item["result"]["vri"]["totals"]["relief"] == 0


@pytest.mark.parametrize("mode,extra,expected", [
    ("master", {}, 60),  # an explicit user mode is not proof of internal netting
    ("percent", {"vri_relief_pct": 20}, 42),
    ("amount", {"vri_relief_mln": 20}, 40),
    ("off", {}, 60),
])
def test_manual_modes_and_other_reliefs_keep_their_semantics(mode, extra, expected):
    x, t = project(vri_relief_mode=mode, **extra)
    assert core.vri_relief(x, 90e6, t)[1] == expected * 1e6
    # A stray private marker alone must not suppress the user's normal relief.
    if mode != "master":
        assert core.vri_relief({**x, "_vri_relief_applied_at_project": True}, 90e6, t)[1] == expected * 1e6
    result = core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=t, rates=[], phasing=phasing([17, 29, 54])))
    assert result["consolidated"]["capex"]["land_rights"] == pytest.approx(expected * 1e6, abs=1e-5, rel=0)


@pytest.mark.parametrize("region", ["mo", "msk"])
def test_installment_interest_and_principal_use_the_net_obligation_once(region):
    x, t = project(vri_region=region, vri_relief_mode="off",
                   vri_payment_mode="installment", vri_installment_years=3,
                   vri_periodicity_months=3, vri_interest_enabled="1")
    master = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=t, rates=[], phasing=phasing([17, 29, 54])))
    assert master["vri"]["totals"]["interest"] > 0
    for key in ("principal", "interest", "cash"):
        assert bundle["vri"]["totals"][key] == pytest.approx(master["vri"]["totals"][key], abs=0.03, rel=0)
    assert bundle["vri"]["totals"]["principal"] == 60e6


def test_fee_only_compensation_and_phases_share_the_same_final_amount(monkeypatch):
    monkeypatch.setattr(core, "require_calc_access", lambda *args, **kwargs: None)
    x, t = project(land_rights_cost_mln=777)
    preview = core.mo_vri_compensation_preview(core.MoVriCompensationRequest(
        inputs=x, tep=t, payment_before_compensation_rub=100e6, compensation_rub=10e6,
        session="fictional-local-session", access_key="fictional-local-key"))["vri"]
    assert preview["payment_used_rub"] == 90e6
    assert preview["payment_after_reliefs_rub"] == 60e6
    x["land_rights_cost_mln"] = preview["payment_used_mln"]
    for weights in ([100], [100, 0], [40, 60], [17, 29, 54]):
        result = core.calculate_phased(core.PhasedCalcRequest(
            inputs=x, tep=t, rates=[], phasing=phasing(weights)))
        assert result["consolidated"]["vri"]["totals"]["principal"] == preview["payment_after_reliefs_rub"]
        assert x["vri_transfer_offset_mln"] == 30


def test_the_regression_case_detects_a_consumer_that_ignores_net_origin(monkeypatch):
    real_relief = core.vri_relief

    def old_consumer(inputs, gross, tep=None):
        # The previous implementation saw mode=master, but still deducted
        # the offset copied from the project. Reproduce that exact behaviour.
        unmarked = {k: value for k, value in inputs.items()
                    if k != "_vri_relief_applied_at_project"}
        return real_relief(unmarked, gross, tep)

    monkeypatch.setattr(core, "vri_relief", old_consumer)
    with pytest.raises(AssertionError):
        test_native_phase_principal_conserves_the_master([100, 0], "lease", 90, 30)


def test_moscow_calculated_mpt_and_transfer_reliefs_stay_project_wide():
    x, t = project(vri_region="msk", land_rights_cost_mln=5000,
                   offices_enabled=True, offices_gba_sqm=22000, offices_saleable_sqm=19800,
                   _cadastral_analysis={"recognized": ["77:00:0000000:1"],
                       "territory": {"district": "Нагатино-Садовники", "inside_ttc": False,
                                     "cadastral_quarter": "77:05:0004001"}})
    t["offices"] = {"gns": 22000, "total_area": 19800, "saleable": 19800}
    master = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    benefits = master["vri"]["benefits"]
    assert benefits["mpt_mln"] > 0 and benefits["transfer_mln"] > 0
    assert master["vri"]["totals"]["relief"] == pytest.approx((benefits["total_mln"] + 30) * 1e6, abs=0.02, rel=0)
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=t, rates=[], phasing=phasing([17, 29, 54])))
    assert bundle["consolidated"]["capex"]["land_rights"] == pytest.approx(
        master["capex"]["land_rights"], abs=1e-5, rel=0), {
            name: {"mpt": block["mpt_mln"], "transfer": block["transfer_mln"],
                   "rows": [(row["key"], row.get("area_sqm"), row["benefit_mln"])
                            for row in block["rows"]]}
            for name, block in (("master", benefits), ("phased", bundle["vri"]["benefits"]))}
    assert bundle["vri"]["totals"]["relief"] == master["vri"]["totals"]["relief"]


@pytest.mark.parametrize("weights,right,fee,offset", [CASES[i] for i in (0, 1, 2, 3, 6, 9)])
def test_generated_v4_formula_principal_matches_native_phases(weights, right, fee, offset):
    x, t = project(land_right=right, land_rights_cost_mln=fee,
                   vri_transfer_offset_mln=offset)
    p = phasing(weights)
    native = core.calculate_phased(core.PhasedCalcRequest(inputs=x, tep=t, rates=[], phasing=p))
    content, _, meta = core.build_project_workbook(x, t, [], p, project_name="Fictional offset")
    assert not meta["missing"], meta["missing"]
    wb = openpyxl.load_workbook(io.BytesIO(content))
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(wb)
    expected = max(0, fee - offset) * 1e6
    amounts = []
    for index, weight in enumerate(weights):
        row = core._V4_VRI_PRINCIPAL_ROW + core._V4_VRI_BLOCK_STRIDE * index
        assert wb["ВРИ"][f"B{row}"].data_type == "f"
        amount = float(evaluator.cell("ВРИ", f"B{row}")) * 1e6
        # Native workbook inputs historically round relief to a whole ruble.
        assert amount == pytest.approx(expected * weight / 100, abs=0.51, rel=0)
        amounts.append(amount)
    assert sum(amounts) == pytest.approx(native["consolidated"]["capex"]["land_rights"], abs=0.51, rel=0)


def test_a_phase_book_keeps_internal_net_basis_without_erasing_the_offset():
    x, t = project()
    result = core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=t, rates=[], phasing=phasing([40, 60])))
    phase = result["phases"][1]
    content, _, meta = core.build_project_workbook(
        phase["inputs"], phase["tep"], [], {}, project_name="Fictional allocated phase")
    assert not meta["missing"], meta["missing"]
    wb = openpyxl.load_workbook(io.BytesIO(content))
    sys.setrecursionlimit(400000)
    assert float(Evaluator(wb).cell("ВРИ", "B12")) * 1e6 == pytest.approx(36e6, abs=0.01, rel=0)
    assert phase["inputs"]["vri_transfer_offset_mln"] == x["vri_transfer_offset_mln"] == 30
