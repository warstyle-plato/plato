"""VRI changes the rent base even when relief removes the entire payment."""
import copy
from datetime import date, timedelta

import pytest

import main

core = main.core


def inputs(region="msk", **changes):
    return {**copy.deepcopy(core.DEFAULT_INPUTS),
            "land_right": "lease", "vri_region": region,
            "land_rent_mode": "manual", "land_rent_cadastral_mln": 100,
            "land_rent_cadastral_target_mln": 300,
            "land_rent_regime_start": "2027-01-01", "project_start": "2027-01-01",
            "ird_months": 12, "construction_months": 12,
            "land_rent_rates": [{"year": 1, "rate_pct": 12}],
            "land_rent_tail_rule": "repeat_last", "land_rent_vat_treatment": "public_exempt",
            "social_mode": "Денежная компенсация", "social_compensation_mln": 0,
            "land_rights_cost_mln": 50, "vri_required": True,
            "vri_obligation_date": "2027-01-16", "vri_relief_mode": "percent",
            "vri_relief_pct": 0, **changes}


def operating(values):
    p = core.prepared_calculation(values, copy.deepcopy(core.TEP_DEFAULT), [])
    return core.build_operating_model(p["x"], p["t"], p["rates"])


@pytest.mark.parametrize("region", ["msk", "mo"])
@pytest.mark.parametrize("relief", [0, 100])
def test_relief_does_not_remove_midmonth_cadastral_change(region, relief):
    model = operating(inputs(region, vri_relief_pct=relief))
    rent = model["land_rent"]
    assert model["capex_amounts"]["land_rights"] == pytest.approx(50e6 * (1-relief/100))
    assert rent["cadastral_switch"]["date"] == "2027-01-16"
    # Independent daily obligation: fifteen days at 100m, sixteen at 300m.
    expected = (100e6 * 15 + 300e6 * 16) * .12 / 365
    assert rent["accrual_monthly"]["2027-01-01"] == pytest.approx(expected, abs=.01)
    assert rent["accrual_monthly"]["2027-02-01"] == pytest.approx(300e6 * 28 * .12 / 365, abs=.01)


@pytest.mark.parametrize("region", ["msk", "mo"])
def test_zero_original_fee_can_still_have_a_vri_change(region):
    model = operating(inputs(region, land_rights_cost_mln=0, land_rent_vri_change=True))
    assert model["capex_amounts"]["land_rights"] == 0
    assert model["land_rent"]["cadastral_switch"]["date"] == "2027-01-16"


def test_event_decision_is_separate_from_the_legacy_payment_flag():
    permit = date(2028, 1, 1)
    assert core.vri_cadastral_change_date(inputs(vri_required=False), permit) == date(2027, 1, 16)
    assert core.vri_cadastral_change_date(inputs(land_rights_cost_mln=0), permit) == date(2027, 1, 16)
    assert core.vri_cadastral_change_date(inputs(land_rent_vri_change=False), permit) is None
    assert core.vri_cadastral_change_date(
        {"vri_required": False, "land_rights_cost_mln": 0}, permit) is None


def test_confirmed_date_overrides_scenario_and_malformed_date_is_not_replaced():
    permit = date(2028, 1, 1)
    assert core.vri_cadastral_change_date(inputs(
        land_rent_cadastral_change_date="2027-02-12"), permit) == date(2027, 2, 12)
    assert core.vri_cadastral_change_date(inputs(
        land_rent_cadastral_change_date="invalid"), permit) is None
    result = operating(inputs(land_rent_cadastral_change_date="invalid"))["land_rent"]
    assert result["cadastral_switch"] is None and result["cadastral_change"] is None
    assert not result["financial_complete"]
    assert any("Не распознана дата применения" in text for text in result["missing"])


@pytest.mark.parametrize("region", ["msk", "mo"])
@pytest.mark.parametrize("relief", [0, 100])
def test_phases_keep_one_cadastral_date_and_release_their_own_share(region, relief):
    x = inputs(region, vri_relief_pct=relief, apartment_price_th=2000,
               land_rent_cadastral_change_date="2027-02-12")
    result = core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[],
        phasing={"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
                 "phases": [{"name": "A", "start_offset_months": 0, "construction_months": 12,
                             "site_area_ha": 1},
                            {"name": "B", "start_offset_months": 12, "construction_months": 12,
                             "site_area_ha": 3}]}))
    rent = result["consolidated"]["land_rent"]
    assert rent["cadastral_switch"]["date"] == "2027-02-12"
    assert [p["commissioning"] for p in rent["phase_land"]] == ["2029-01-01", "2030-01-01"]
    assert all(p["result"]["land_rent"]["cadastral_switch"]["date"] == "2027-02-12"
               for p in result["phases"])
    # Housing keeps its own share for the default three registration months.
    assert [p["lease_exit"] for p in rent["land_exposures"]] == ["2029-04-01", "2030-04-01"]
    assert rent["accrual_monthly"]["2029-01-01"] == pytest.approx(300e6 * .12 * 31 / 365, abs=.01)
    assert rent["accrual_monthly"]["2029-04-01"] == pytest.approx(300e6 * .75 * .12 * 30 / 365, abs=.01)
    day, expected = date(2027, 1, 1), 0.
    while day < date(2030, 4, 1):
        value = 100e6 if day < date(2027, 2, 12) else 300e6
        share = 1 if day < date(2029, 4, 1) else .75
        expected += value * share * .12 / (366 if day.year == 2028 else 365)
        day += timedelta(days=1)
    assert rent["construction_total"] == pytest.approx(expected, abs=.01)
    assert sum(p["result"]["capex"]["land_rent"] for p in result["phases"]) == pytest.approx(expected, abs=.01)
