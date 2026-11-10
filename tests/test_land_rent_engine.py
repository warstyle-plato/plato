import copy
from datetime import date

import pytest

import main
import developaid_actuals

core = main.core


def inputs(**kw):
    return {**copy.deepcopy(core.DEFAULT_INPUTS), "land_right": "lease", "vri_region": "msk",
            "land_rent_mode": "manual", "land_rent_cadastral_mln": 100,
            "land_rent_regime_start": "2027-01-01", "project_start": "2027-01-01",
            "ird_months": 12, "construction_months": 12,
            "land_rent_rates": [{"year": 1, "rate_pct": 1.5}],
            "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt", **kw}


def op(x):
    p = core.prepared_calculation(x, copy.deepcopy(core.TEP_DEFAULT), [])
    return core.build_operating_model(p["x"], p["t"], p["rates"])


def test_land_rent_reaches_capex_months_and_cashflow_as_a_separate_cost():
    x = inputs()
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert result["capex"]["land_rent"] == pytest.approx(3e6)
    line = next(r for r in result["monthly"]["costs"] if r["key"] == "land_rent")
    assert line["total"] == pytest.approx(3e6)
    assert result["land_rent"]["applied_total"] == pytest.approx(3e6)
    assert result["summary"]["preliminary"]
    assert "аренд" in result["summary"]["preliminary_reason"].lower()


def test_construction_cost_scenario_does_not_change_contractual_rent():
    baseline, inflated = op(inputs()), op(inputs(scenario_cost_multiplier=1.2))
    assert baseline["capex_amounts"]["land_rent"] == inflated["capex_amounts"]["land_rent"]
    assert baseline["capex_by_article"]["land_rent"] == inflated["capex_by_article"]["land_rent"]
    assert inflated["capex_amounts"]["main_above"] > baseline["capex_amounts"]["main_above"]


@pytest.mark.parametrize("count", [2, 3])
def test_common_parcel_is_counted_once_through_latest_queue_rve(count):
    x = inputs(apartment_price_th=2000)
    phases = [{"name": str(i+1), "start_offset_months": i*24, "construction_months": 12} for i in range(count)]
    result = core.calculate_phased(core.PhasedCalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[],
        phasing={"enabled": True, "mode": "phased", "phase_count": count, "user_enabled": True, "phases": phases}))
    total = result["consolidated"]["capex"]["land_rent"]
    assert total == pytest.approx((2 + 2*(count-1))*1.5e6)
    assert sum(p["result"]["capex"]["land_rent"] for p in result["phases"]) == pytest.approx(total)
    assert result["consolidated"]["land_rent"]["applied_total"] == pytest.approx(total)
    assert [p["result"]["capex"]["land_rent"] > 0 for p in result["phases"]] == [True] + [False]*(count-1)
    first = result["phases"][0]["result"]
    late = [r for r in first["finance"]["rows"] if r["month"] > first["dates"]["rve"]]
    assert any(r["project_costs"] > 0 for r in late)
    # The first queue's repaid credit must not be fictitiously reopened.
    repaid = False
    for row in first["finance"]["rows"]:
        if repaid:
            assert row["pf_draw"] == 0
        if row["month"] >= first["dates"]["rve"] and row["pf_balance"] == 0:
            repaid = True
    assert repaid


def test_new_rent_fact_is_separate_from_vri_and_does_not_rescale_future_years():
    baseline = op(inputs())
    future = dict(baseline["capex_by_article"]["land_rent"])
    actuals = {"cut": "2027-03-01", "land_rent_mapping_version": 1,
               "capex_by_article": {"land_rent": {"2027-01-01": 200_000}}}
    merged = developaid_actuals.overlay(baseline, actuals)["op"]
    assert merged["capex_by_article"]["land_rent"][date(2027, 1, 1)] == 200_000
    assert {m:v for m,v in merged["capex_by_article"]["land_rent"].items() if m>=date(2027,3,1)} == {
        m:v for m,v in future.items() if m>=date(2027,3,1)}
    assert merged["capex_by_article"]["land_rights"] == baseline["capex_by_article"]["land_rights"]


def test_saved_legacy_land_rights_is_not_guessed_or_counted_again_as_past_rent():
    baseline = op(inputs())
    actuals = {"cut": "2027-07-01", "capex_by_article": {"land_rights": {"2027-01-01": 1e6}}}
    overlaid = developaid_actuals.overlay(baseline, actuals)
    merged = overlaid["op"]
    assert not any(m < date(2027,7,1) for m in merged["capex_by_article"]["land_rent"])
    assert not merged["land_rent"]["financial_complete"]
    assert any("Старый импорт" in n for n in overlaid["report"]["notes"])


def test_monthly_rent_bucket_does_not_rewrite_owner_project_start_date():
    x = inputs(project_start="2027-03-17")
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert result["dates"]["project_start"] == "2027-03-17"
    assert result["land_rent"]["project_start"] == "2027-03-17"
    assert "2027-03-01" in result["land_rent"]["monthly"]


def test_actual_land_tax_does_not_create_a_deductible_input_vat_amount():
    x = inputs(land_right="ownership")
    p = core.prepared_calculation(x, copy.deepcopy(core.TEP_DEFAULT), [])
    baseline = core.build_operating_model(p["x"], p["t"], p["rates"])
    tax = developaid_actuals.overlay(baseline, {"cut": "2027-02-01", "land_rent_mapping_version": 1,
        "capex_by_article": {"land_tax": {"2027-01-01": 12e6}}})["op"]
    before = core.simulate_financing(p["x"], p["t"], p["rates"], baseline)
    after = core.simulate_financing(p["x"], p["t"], p["rates"], tax)
    assert sum(tax["capex"].values()) - sum(baseline["capex"].values()) == pytest.approx(12e6)
    assert after["vat_input_deductible"] == pytest.approx(before["vat_input_deductible"])


def test_monthly_detail_keeps_common_rent_before_the_earliest_queue_start():
    x = inputs(land_rent_cadastral_mln=120, land_rent_rates=[{"year": 1, "rate_pct": 4}])
    result = core.calculate_phased(core.PhasedCalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[],
        phasing={"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
                 "phases": [{"name": "A", "start_offset_months": 12, "construction_months": 12},
                            {"name": "B", "start_offset_months": 36, "construction_months": 12}]}))
    first = result["phases"][0]["result"]
    line = next(r for r in first["monthly"]["costs"] if r["key"] == "land_rent")
    assert first["dates"]["project_start"] == "2028-01-01"
    assert first["monthly"]["months"][0] == first["cashflow"]["months"][0] == "2027-01-01"
    assert sum(line["values"]) == pytest.approx(line["total"], abs=0.1)


@pytest.mark.parametrize("kind", ["mixed", "nonresidential"])
def test_only_active_object_commissioning_extends_rental_cutoff_without_changing_housing_rve(kind):
    x = inputs(project_kind=kind, offices_enabled=True, offices_strategy="income",
        offices_gns_sqm=10000, offices_saleable_sqm=8000,
        offices_start="2028-01-01", offices_months=12)
    early = op(x)
    x["offices_months"] = 36
    late = op(x)
    assert late["rve"] == early["rve"]
    assert late["land_rent"]["rve"] == "2031-01-01"
    assert late["capex_amounts"]["land_rent"] > early["capex_amounts"]["land_rent"]
    x["offices_enabled"] = False
    disabled = op(x)
    assert disabled["land_rent"]["rve"] == disabled["rve"].isoformat()


def test_actual_cash_is_canonical_without_rewriting_accruals_for_other_payment_periods():
    baseline = op(inputs())
    after = developaid_actuals.overlay(baseline, {"cut": "2027-03-01", "land_rent_mapping_version": 1,
        "capex_by_article": {"land_rent": {"2027-01-01": 200000}}})["op"]
    assert after["land_rent"]["applied_total"] == after["land_rent"]["cash_total"]
    assert after["land_rent"]["applied_total"] == pytest.approx(sum(after["capex_by_article"]["land_rent"].values()))
    assert after["land_rent"]["construction_total"] == baseline["land_rent"]["construction_total"]
    assert after["land_rent"]["annual_rows"] == baseline["land_rent"]["annual_rows"]
    assert after["land_rent"]["applied_total"] != after["land_rent"]["construction_total"]


@pytest.mark.parametrize("source", ["aggregate", "budget"])
def test_old_total_or_budget_overlays_refresh_every_cash_consumer_and_qualify_unknown_rent(source):
    x = inputs(land_rent_cadastral_mln=120, land_rent_rates=[{"year": 1, "rate_pct": 4}],
        land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0", land_rent_termination_date="2029-01-01")
    baseline = op(x)
    assert baseline["land_rent"]["financial_complete"]
    actuals = {"cut": "2027-04-01"}
    if source == "budget":
        actuals["capex_budget"] = {"land_rent": 1e6}
    else:
        actuals["capex"] = {m.isoformat(): v*0.5 for m, v in baseline["capex"].items() if m<date(2027,4,1)}
    after = developaid_actuals.overlay(baseline, actuals)["op"]
    amount = sum(after["capex_by_article"]["land_rent"].values())
    assert after["capex_amounts"]["land_rent"] == pytest.approx(amount)
    assert after["land_rent"]["applied_total"] == pytest.approx(amount)
    assert sum(after["land_rent"]["monthly"].values()) == pytest.approx(amount)
    assert not after["land_rent"]["financial_complete"]
    assert "legacy_actuals" in after["land_rent"]["financial_missing_codes"]
    assert after["land_rent"]["construction_total"] == baseline["land_rent"]["construction_total"]


def test_phased_nonempty_actuals_is_rejected_instead_of_silently_ignored():
    req = core.PhasedCalcRequest(inputs=inputs(), tep=copy.deepcopy(core.TEP_DEFAULT), rates=[],
        phasing={"enabled": True, "phase_count": 2}, actuals={"cut": "2027-07-01", "capex": {"2027-01-01": 37e6}})
    with pytest.raises(core.HTTPException) as exc:
        core.calculate_phased(req)
    assert exc.value.status_code == 422
    assert "не применены" in exc.value.detail


def test_classified_same_total_rent_timing_reaches_income_object_financing():
    x = inputs(project_kind="nonresidential", land_rent_cadastral_mln=120,
        land_rent_rates=[{"year": 1, "rate_pct": 4}],
        land_rent_payment_mode="manual", land_rent_payment_schedule="100%@0",
        land_rent_termination_date="2029-01-01", construction_months=36)
    x.update({obj.enabled_key: False for obj in core.standalone_objects()})
    x.update(offices_enabled=True, offices_strategy="income", offices_start="2028-01-01",
             offices_months=12, offices_gba_sqm=10000, offices_saleable_sqm=8000)
    p = core.prepared_calculation(x, copy.deepcopy(core.TEP_DEFAULT), [])
    before = core.build_operating_model(p["x"], p["t"], p["rates"])
    cut = date(2027, 3, 1)
    # Preserve every other dated article: only the timing of rent changes.
    facts = {key: {m.isoformat(): v for m, v in series.items() if m < cut}
             for key, series in before["capex_by_article"].items()}
    facts["land_rent"] = {"2027-01-01": 4.8e6, "2027-02-01": 4.8e6}
    after = developaid_actuals.overlay(before, {"cut": cut.isoformat(),
        "land_rent_mapping_version": 1, "capex_by_article": facts})["op"]
    assert before["land_rent"]["financial_complete"]
    assert after["land_rent"]["financial_complete"]
    assert sum(after["capex"].values()) == pytest.approx(sum(before["capex"].values()))
    old_object = core.nonres_overlay(p["x"], p["rates"], before)["objects"]["offices"]
    new_object = core.nonres_overlay(p["x"], p["rates"], after)["objects"]["offices"]
    for month, expected in ((date(2027, 1, 1), -4.8e6), (date(2027, 2, 1), 4.8e6)):
        assert after["capex"][month] - before["capex"][month] == pytest.approx(expected)
        assert new_object["common_by_month"].get(month, 0) - old_object["common_by_month"].get(month, 0) == pytest.approx(expected)
    assert new_object["kpi"]["cost_total"] == pytest.approx(old_object["kpi"]["cost_total"])
    assert new_object["book"]["months"] != old_object["book"]["months"]


@pytest.mark.parametrize("kind", ["hotel", "nonresidential"])
def test_saved_manual_rent_does_not_charge_owned_land_or_change_native_vri_policy(kind):
    x = inputs(project_kind=kind, land_right="ownership", land_rights_cost_mln=5,
               land_rights_relief_mln=1)
    model = op(x)
    assert model["capex_amounts"]["land_rent"] == 0
    assert model["land_rent"]["status"] == "not_applicable"
    assert model["capex_amounts"].get("land_rights", 0) == 0
