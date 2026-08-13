from datetime import date

from mpt_calculator import MptInput, calculate_mpt_benefit

TODAY = date(2026, 8, 8)


def test_hotel_uses_eligible_premises_area_and_excludes_only_parking_and_garages():
    result = calculate_mpt_benefit(
        MptInput(
            category="hotel",
            district="Ясенево",
            area_sqm=5_000,
            parking_sqm=200,
            garages_sqm=100,
            warehouse_inside_sqm=1_000,
            warehouse_yard_sqm=500,
        ),
        today=TODAY,
    )
    assert result.eligible_area_sqm == 4_700
    assert result.excluded_area_sqm == 300
    assert result.warehouse_excluded_sqm == 0
    assert result.kmest == 0.5


def test_hotel_warns_that_base_area_must_already_be_normatively_eligible():
    result = calculate_mpt_benefit(
        MptInput(
            category="hotel",
            district="Ясенево",
            area_sqm=5_000,
            warehouse_inside_sqm=1,
        ),
        today=TODAY,
    )
    assert any("базовая площадь должна включать только помещения" in warning.lower()
               for warning in result.warnings)
