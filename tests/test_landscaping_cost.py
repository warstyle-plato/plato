from __future__ import annotations

import pytest

import developaid_landscaping as landscaping


def test_legacy_formula_is_unchanged_without_physical_inputs():
    result = landscaping.calculate({"landscaping_th_per_sqm": 15.5}, 100_000)
    assert result["mode"] == "legacy_gns"
    assert result["amount_rub"] == pytest.approx(1_550_000_000)
    assert result["equivalent_gns_th_per_sqm"] == pytest.approx(15.5)


def test_explicit_physical_area_becomes_authoritative_only_with_physical_rate():
    result = landscaping.calculate(
        {
            "landscaping_th_per_sqm": 15.5,
            "landscaping_area_sqm": 12_000,
            "landscaping_site_th_per_sqm": 18,
        },
        100_000,
    )
    assert result["mode"] == "physical"
    assert result["amount_rub"] == pytest.approx(216_000_000)
    assert result["equivalent_gns_th_per_sqm"] == pytest.approx(2.16)


def test_site_minus_footprint_derives_landscaping_area():
    result = landscaping.calculate(
        {
            "site_area_ha": 2.0,
            "building_footprint_sqm": 7_000,
            "landscaping_site_th_per_sqm": 18,
            "landscaping_th_per_sqm": 15.5,
        },
        50_000,
    )
    assert result["basis_source"] == "site_minus_footprint"
    assert result["landscaping_area_sqm"] == pytest.approx(13_000)
    assert result["amount_rub"] == pytest.approx(234_000_000)


def test_green_area_is_component_not_a_second_capex_article():
    plain = landscaping.calculate(
        {
            "landscaping_area_sqm": 10_000,
            "landscaping_site_th_per_sqm": 18,
        },
        50_000,
    )
    with_green = landscaping.calculate(
        {
            "landscaping_area_sqm": 10_000,
            "landscaping_green_area_sqm": 4_000,
            "landscaping_site_th_per_sqm": 18,
        },
        50_000,
    )
    assert with_green["amount_rub"] == pytest.approx(plain["amount_rub"])
    assert with_green["green_share_pct"] == pytest.approx(40.0)


def test_area_without_physical_rate_keeps_legacy_cost():
    result = landscaping.calculate(
        {
            "landscaping_th_per_sqm": 11.5,
            "landscaping_area_sqm": 10_000,
            "landscaping_site_th_per_sqm": 0,
        },
        80_000,
    )
    assert result["mode"] == "legacy_gns"
    assert result["amount_rub"] == pytest.approx(920_000_000)


def test_legacy_template_adapter_preserves_physical_total():
    tep = {
        "apartments": {"gns": 40_000},
        "ground_commercial": {"gns": 5_000},
        "underground_parking": {"gns": 5_000},
        "storage": {"gns": 0},
    }
    adapted, calc = landscaping.legacy_template_inputs(
        {
            "landscaping_th_per_sqm": 11.5,
            "landscaping_area_sqm": 10_000,
            "landscaping_site_th_per_sqm": 18,
        },
        tep,
    )
    assert calc["amount_rub"] == pytest.approx(180_000_000)
    assert adapted["landscaping_th_per_sqm"] == pytest.approx(3.6)
    assert (
        landscaping.core_gns_sqm(tep)
        * adapted["landscaping_th_per_sqm"]
        * 1000
    ) == pytest.approx(calc["amount_rub"])


def test_phase_allocation_weight_can_use_total_project_gns_without_double_counting():
    master = {
        "apartments": {"gns": 80_000},
        "ground_commercial": {"gns": 10_000},
        "underground_parking": {"gns": 10_000},
    }
    phase_1 = {
        "apartments": {"gns": 48_000},
        "ground_commercial": {"gns": 6_000},
        "underground_parking": {"gns": 6_000},
    }
    phase_2 = {
        "apartments": {"gns": 32_000},
        "ground_commercial": {"gns": 4_000},
        "underground_parking": {"gns": 4_000},
    }
    total = landscaping.project_gns_sqm(master)
    a1 = 13_000 * landscaping.project_gns_sqm(phase_1) / total
    a2 = 13_000 * landscaping.project_gns_sqm(phase_2) / total
    assert a1 + a2 == pytest.approx(13_000)



def test_authoritative_engine_keeps_legacy_default_and_switches_only_explicitly():
    import main as wrapper

    core = wrapper.core
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}

    legacy_inputs = dict(core.DEFAULT_INPUTS)
    legacy = core.calculate(core.CalcRequest(inputs=legacy_inputs, tep=tep, rates=[]))
    core_gns = (
        float(legacy["tep"]["core_above_gns"])
        + float(legacy["tep"]["core_under_gns"])
    )
    assert legacy["landscaping"]["mode"] == "legacy_gns"
    assert legacy["capex"]["landscaping"] == pytest.approx(
        core_gns * legacy_inputs["landscaping_th_per_sqm"] * 1000
    )

    physical_inputs = dict(legacy_inputs)
    physical_inputs.update(
        site_area_ha=2.0,
        building_footprint_sqm=7_000,
        landscaping_site_th_per_sqm=18.0,
    )
    physical = core.calculate(
        core.CalcRequest(
            inputs=physical_inputs,
            tep={key: dict(value) for key, value in core.TEP_DEFAULT.items()},
            rates=[],
        )
    )
    assert physical["landscaping"]["mode"] == "physical"
    assert physical["landscaping"]["landscaping_area_sqm"] == pytest.approx(13_000)
    assert physical["capex"]["landscaping"] == pytest.approx(234_000_000)


def test_phased_engine_does_not_repeat_the_site_landscaping_area():
    import main as wrapper

    core = wrapper.core
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(
        site_area_ha=2.0,
        building_footprint_sqm=7_000,
        landscaping_site_th_per_sqm=18.0,
    )
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core.calculate_phased(
        core.PhasedCalcRequest(
            inputs=inputs,
            tep=tep,
            rates=[],
            phasing={"enabled": True, "phase_count": 2, "phase_gap_months": 12},
        )
    )
    areas = [
        float(item["result"]["landscaping"]["landscaping_area_sqm"])
        for item in bundle["phases"]
    ]
    assert sum(areas) == pytest.approx(13_000)
    assert all(area > 0 for area in areas)
