from datetime import date

import pytest

from mpt_calculator import (
    MptCalculationError,
    MptInput,
    SPECIAL_OFFICE_QUARTERS,
    calculate_mpt_benefit,
    cadastral_quarter,
    kmest_for,
)

TODAY = date(2026, 8, 8)


def test_industrial_warehouse_cap_and_exclusions():
    result = calculate_mpt_benefit(
        MptInput(
            category="industrial",
            district="Хорошево-Мневники",
            area_sqm=10_000,
            parking_sqm=300,
            garages_sqm=200,
            warehouse_inside_sqm=3_000,
            warehouse_yard_sqm=250,
        ),
        today=TODAY,
    )
    assert result.warehouse_counted_sqm == 2_500
    assert result.warehouse_excluded_sqm == 500
    assert result.eligible_area_sqm == 8_750
    assert result.kmest == 0.8


def test_nonindustrial_warehouse_is_excluded():
    result = calculate_mpt_benefit(
        MptInput(
            category="social",
            district="Ясенево",
            area_sqm=5_000,
            warehouse_inside_sqm=500,
        ),
        today=TODAY,
    )
    assert result.eligible_area_sqm == 4_500
    assert result.warehouse_counted_sqm == 0
    assert result.warehouse_excluded_sqm == 500


def test_group_2_office_requires_ttk():
    with pytest.raises(MptCalculationError):
        kmest_for("office", "Хорошевский")


def test_group_2_office_inside_outside_ttk():
    assert kmest_for("office", "Хорошевский", ttk_position="inside")[0] == 0
    assert kmest_for("office", "Хорошевский", ttk_position="outside")[0] == 0.7


def test_group_2_industrial_inside_outside_ttk():
    assert kmest_for("industrial", "Хорошевский", ttk_position="inside")[0] == 0
    assert kmest_for("industrial", "Хорошевский", ttk_position="outside")[0] == 0.8


def test_special_office_quarter_overrides_district_ttk_rule():
    kmest, source = kmest_for(
        "office",
        "Хорошевский",
        cadastral_number="77:04:0001008:1234",
    )
    assert kmest == 0.8
    assert "таблица 2" in source


def test_cadastral_number_extracts_quarter():
    assert cadastral_quarter("77:04:0001008:1234") == "77:04:0001008"


def test_ons_readiness_factor():
    result = calculate_mpt_benefit(
        MptInput(
            category="sport",
            district="Ясенево",
            area_sqm=4_000,
            mode="ons",
            ons_readiness_pct=25,
            ons_registered_before_2019_11_01=True,
        ),
        today=TODAY,
    )
    expected = 1000 * 4000 * 0.75 * 166.23078 * 0.8
    assert result.readiness_factor == 0.75
    assert result.benefit_rub == pytest.approx(expected)


def test_ons_requires_old_registration():
    with pytest.raises(MptCalculationError):
        calculate_mpt_benefit(
            MptInput(
                category="sport",
                district="Ясенево",
                area_sqm=4_000,
                mode="ons",
                ons_readiness_pct=25,
                ons_registered_before_2019_11_01=False,
            ),
            today=TODAY,
        )


def test_kterm_multiplier():
    base = calculate_mpt_benefit(
        MptInput(category="sport", district="Ясенево", area_sqm=4_000, kterm=1.0),
        today=TODAY,
    )
    fast = calculate_mpt_benefit(
        MptInput(category="sport", district="Ясенево", area_sqm=4_000, kterm=1.1),
        today=TODAY,
    )
    assert fast.benefit_rub == pytest.approx(base.benefit_rub * 1.1)


def test_minimum_area_warning_does_not_hide_calculation():
    result = calculate_mpt_benefit(
        MptInput(category="office", district="Ясенево", area_sqm=4_000),
        today=TODAY,
    )
    assert result.eligible_for_minimum is False
    assert result.benefit_rub > 0
    assert any("минимального порога" in warning for warning in result.warnings)


def test_special_quarter_count_is_99():
    assert len(SPECIAL_OFFICE_QUARTERS) == 99


def test_special_office_quarter_does_not_override_industrial_ttk_rule():
    with pytest.raises(MptCalculationError):
        kmest_for(
            "industrial",
            "Хорошевский",
            cadastral_number="77:04:0001008:1234",
        )
