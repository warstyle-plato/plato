from fastapi import HTTPException

from market_analysis import MarketAnalysisRequest, analyse_market


def test_mishina_reference_returns_price_recommendation() -> None:
    result = analyse_market(MarketAnalysisRequest(
        address="Москва, ул. Мишина, д. 46",
        sale_start_date="2027-06-01",
        saleable_area_sqm=15150,
        annual_price_growth=0.06,
        sales_duration_months=42,
    ))

    assert result["mode"] == "pilot_reference"
    assert result["recommended_launch_price"] == 625000
    assert result["market_price_today"] == 625000
    assert result["weighted_average_project_price"] > result["recommended_launch_price"]
    assert result["market"]["projects"] == 2
    assert result["market"]["total_area_sqm"] == 210000
    assert result["market"]["project_share_of_nearby_area"] > 0


def test_unknown_address_is_not_invented() -> None:
    try:
        analyse_market(MarketAnalysisRequest(address="Москва, Тверская, 1"))
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "Мишина" in str(exc.detail)
    else:
        raise AssertionError("unknown address must fail until a live provider is connected")
