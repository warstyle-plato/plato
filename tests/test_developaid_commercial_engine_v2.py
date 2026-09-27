"""Tests for the authoritative beta-2 commercial underwriting engine."""

import pytest

import developaid_commercial as commercial


def calc(asset="office", strategy="income", financing="equity_debt", **inputs):
    return commercial.calculate(commercial.CommercialRequest(
        asset_type=asset,
        strategy=strategy,
        financing_mode=financing,
        inputs=inputs,
    ))


def test_beta2_is_the_public_engine_and_reconciles_development_spend():
    result = calc("office")
    assert result["version"] == "commercial-beta-2"
    assert result["checks"]["development_spend_reconciles"] is True
    assert sum(result["monthly"]["development_spend"]) == pytest.approx(
        result["kpi"]["development_cost"], abs=0.01
    )


def test_development_uses_an_s_curve_not_flat_monthly_spend():
    result = calc("office", financing="equity")
    spend = result["monthly"]["development_spend"][1:31]
    assert spend[0] < spend[len(spend)//2]
    assert spend[-1] < spend[len(spend)//2]
    assert len({round(value, 2) for value in spend}) > 5


def test_office_lease_up_and_growth_change_monthly_economics():
    result = calc(
        "office",
        financing="equity",
        opening_occupancy_pct=40,
        occupancy_pct=90,
        stabilization_months=12,
        rent_growth_pct=6,
    )
    construction = int(result["inputs"]["construction_months"])
    first = construction + 1
    stabilized = construction + 12
    later = construction + 24
    assert result["monthly"]["occupancy"][first] < result["monthly"]["occupancy"][stabilized]
    assert result["monthly"]["rate_metric"][later] > result["monthly"]["rate_metric"][stabilized]
    assert result["monthly"]["operating_noi"][stabilized] > result["monthly"]["operating_noi"][first]


def test_retail_uses_segment_mix_and_exposes_base_and_turnover_rent():
    result = calc("retail", financing="equity")
    operating = result["operating"]
    assert operating["tenant_segments"]
    assert sum(row["area"] for row in operating["tenant_segments"]) == pytest.approx(
        result["inputs"]["income_area_sqm"], rel=1e-9
    )
    assert operating["base_rent"] > 0
    assert operating["turnover_rent"] > 0


def test_retail_custom_mix_is_normalized_but_warned():
    result = calc(
        "retail",
        financing="equity",
        tenant_mix=[
            {
                "name": "Anchor",
                "share_pct": 70,
                "base_rent_rub_sqm_month": 2000,
                "sales_rub_sqm_month": 40000,
                "turnover_rent_pct": 6,
                "occupancy_pct": 95,
            },
            {
                "name": "Inline",
                "share_pct": 50,
                "base_rent_rub_sqm_month": 5000,
                "sales_rub_sqm_month": 70000,
                "turnover_rent_pct": 8,
                "occupancy_pct": 94,
            },
        ],
    )
    assert any("нормализовал" in warning for warning in result["warnings"])
    assert sum(row["area"] for row in result["operating"]["tenant_segments"]) == pytest.approx(
        result["inputs"]["income_area_sqm"], rel=1e-9
    )


def test_hotel_pnl_contains_gop_management_fee_ffe_and_revpar():
    result = calc("hotel", financing="equity")
    operating = result["operating"]
    assert operating["room_revenue"] > 0
    assert operating["management_fee"] > 0
    assert operating["ffe_reserve"] > 0
    assert operating["gop"] > operating["noi"]
    assert operating["revpar"] > 0
    assert operating["gop_margin"] is not None
    assert operating["noi_margin"] is not None


def test_sale_strategy_uses_curve_and_no_terminal_value():
    result = calc("office", strategy="sale", financing="equity", sales_curve="bell")
    sales = [value for value in result["monthly"]["sale_revenue"] if value > 0]
    assert sales
    assert len({round(value, 2) for value in sales}) > 3
    assert sales[0] < max(sales)
    assert sales[-1] < max(sales)
    assert sum(result["monthly"]["terminal_value"]) == 0


def test_sale_debt_sweep_uses_net_sale_cash_and_closes_residual_debt():
    result = calc(
        "office",
        strategy="sale",
        financing="equity_debt",
        debt_share_pct=60,
        selling_cost_pct=10,
        sales_cash_sweep_pct=100,
    )
    month = next(i for i, value in enumerate(result["monthly"]["sale_revenue"]) if value > 0)
    gross = result["monthly"]["sale_revenue"][month]
    selling = result["monthly"]["selling_cost"][month]
    repayment = result["monthly"]["debt_repayment"][month]
    assert repayment <= gross - selling + 0.01
    assert result["checks"]["ending_debt_zero"] is True


def test_income_debt_metrics_are_exposed_without_escrow():
    result = calc("office", strategy="income", financing="equity_debt")
    kpi = result["kpi"]
    assert result["uses_escrow"] is False
    assert kpi["peak_debt"] > 0
    assert kpi["ltc"] is not None
    assert kpi["exit_ltv"] is not None
    assert kpi["interest_cover"] is not None
    assert kpi["debt_yield"] is not None
    assert kpi["equity_multiple"] is not None


def test_equity_only_has_no_financing_cost_or_debt_metrics():
    result = calc("hotel", financing="equity")
    assert result["kpi"]["peak_debt"] == 0
    assert result["kpi"]["financing_cost"] == 0
    assert result["kpi"]["ltc"] == 0
    assert result["kpi"]["exit_ltv"] == 0
    assert result["kpi"]["interest_cover"] is None
    assert result["kpi"]["debt_yield"] is None


def test_annual_summary_reconciles_to_monthly_cashflow():
    result = calc("retail", financing="equity")
    annual_cf = sum(row["project_cashflow"] for row in result["annual"])
    assert annual_cf == pytest.approx(sum(result["monthly"]["project_cashflow"]), abs=0.01)
