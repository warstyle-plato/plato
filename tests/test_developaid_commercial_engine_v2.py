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


def test_retail_default_uses_the_scalar_web_inputs():
    base = calc("retail", financing="equity")
    higher_rent = calc(
        "retail", financing="equity",
        rent_rub_sqm_month=base["inputs"]["rent_rub_sqm_month"] * 1.25,
    )
    higher_sales = calc(
        "retail", financing="equity",
        sales_rub_sqm_month=base["inputs"]["sales_rub_sqm_month"] * 1.25,
    )
    assert base["operating"]["tenant_segments"] == []
    assert higher_rent["operating"]["base_rent"] > base["operating"]["base_rent"]
    assert higher_sales["operating"]["turnover_rent"] > base["operating"]["turnover_rent"]


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


def test_custom_retail_mix_is_actually_segmented():
    result = calc(
        "retail",
        financing="equity",
        tenant_mix=[
            {
                "name": "Anchor",
                "share_pct": 30,
                "base_rent_rub_sqm_month": 1800,
                "sales_rub_sqm_month": 35000,
                "turnover_rent_pct": 6,
                "occupancy_pct": 96,
            },
            {
                "name": "Inline",
                "share_pct": 70,
                "base_rent_rub_sqm_month": 5200,
                "sales_rub_sqm_month": 70000,
                "turnover_rent_pct": 8,
                "occupancy_pct": 95,
            },
        ],
    )
    operating = result["operating"]
    assert len(operating["tenant_segments"]) == 2
    assert sum(row["area"] for row in operating["tenant_segments"]) == pytest.approx(
        result["inputs"]["income_area_sqm"], rel=1e-9
    )


def test_office_stabilized_noi_matches_manual_formula_without_growth_or_lease_cost():
    result = calc(
        "office",
        financing="equity",
        income_area_sqm=10000,
        rent_rub_sqm_month=5000,
        opening_occupancy_pct=100,
        occupancy_pct=100,
        stabilization_months=1,
        rent_growth_pct=0,
        other_income_pct=0,
        opex_pct=20,
        leasing_cost_pct=0,
    )
    expected = 10000 * 5000 * 12 * 0.80
    assert result["kpi"]["stabilized_noi_annual"] == pytest.approx(expected, rel=1e-9)


def test_hotel_stabilized_noi_matches_manual_formula():
    result = calc(
        "hotel",
        financing="equity",
        keys=100,
        adr_rub=10000,
        opening_occupancy_pct=70,
        occupancy_pct=70,
        stabilization_months=1,
        adr_growth_pct=0,
        other_revenue_pct=20,
        opex_pct=50,
        management_fee_pct=3,
        ffe_reserve_pct=2,
    )
    revenue = 100 * 10000 * 365 * 0.70 * 1.20
    expected_noi = revenue * (1 - 0.50 - 0.03 - 0.02)
    assert result["kpi"]["stabilized_noi_annual"] == pytest.approx(expected_noi, rel=1e-9)


def test_exit_cost_reduces_cash_but_not_gross_exit_valuation():
    no_cost = calc("office", financing="equity", exit_cost_pct=0)
    with_cost = calc("office", financing="equity", exit_cost_pct=2)
    assert with_cost["kpi"]["exit_value"] == pytest.approx(no_cost["kpi"]["exit_value"])
    assert with_cost["kpi"]["exit_cost"] == pytest.approx(
        with_cost["kpi"]["exit_value"] * 0.02
    )
    assert with_cost["kpi"]["net_exit_proceeds"] < with_cost["kpi"]["exit_value"]
    assert sum(with_cost["monthly"]["project_cashflow"]) < sum(no_cost["monthly"]["project_cashflow"])


def test_peak_debt_tracks_balance_before_same_month_sale_repayment():
    result = calc(
        "office",
        strategy="sale",
        financing="equity_debt",
        land_cost_rub=1000,
        gross_area_sqm=0,
        construction_cost_rub_sqm=0,
        soft_cost_pct=0,
        contingency_pct=0,
        construction_months=1,
        sale_start_month=0,
        sale_months=1,
        saleable_area_sqm=1,
        sale_price_rub_sqm=10000,
        selling_cost_pct=0,
        debt_share_pct=60,
        debt_rate_pct=0,
        loan_fee_pct=0,
        sales_cash_sweep_pct=100,
    )
    assert result["kpi"]["peak_debt"] == pytest.approx(600.0)
    assert result["monthly"]["debt_balance"][0] == 0
    assert result["checks"]["peak_debt_within_limit"] is True


def test_equity_only_project_and_equity_cashflows_are_identical():
    result = calc("office", financing="equity", loan_fee_pct=0, debt_rate_pct=0)
    assert result["monthly"]["equity_cashflow"] == pytest.approx(
        result["monthly"]["project_cashflow"], abs=0.01
    )
    assert result["kpi"]["equity_irr"] == pytest.approx(result["kpi"]["project_irr"], rel=1e-9)


def test_npv_hurdles_are_calculated_and_reconcile_checks_pass():
    result = calc("office", financing="equity_debt")
    assert isinstance(result["kpi"]["project_npv"], float)
    assert isinstance(result["kpi"]["equity_npv"], float)
    assert result["checks"]["project_cashflow_reconciles"] is True


def test_sale_price_growth_changes_total_proceeds():
    flat = calc(
        "office", strategy="sale", financing="equity",
        sale_price_growth_pct=0,
    )
    growing = calc(
        "office", strategy="sale", financing="equity",
        sale_price_growth_pct=12,
    )
    assert sum(growing["monthly"]["sale_revenue"]) > sum(flat["monthly"]["sale_revenue"])


def test_monthly_cost_channels_are_not_double_counted():
    result = calc("office", strategy="sale", financing="equity", selling_cost_pct=3)
    assert sum(result["monthly"]["operating_cost"]) == pytest.approx(0.0)
    assert sum(result["monthly"]["selling_cost"]) > 0
    annual_selling = sum(row["selling_cost"] for row in result["annual"])
    assert annual_selling == pytest.approx(sum(result["monthly"]["selling_cost"]), abs=0.01)


def test_durable_payback_does_not_report_temporary_early_crossing():
    from developaid_commercial_engine import _payback_month
    assert _payback_month([-100, 150, -100, 100]) == 3


@pytest.mark.parametrize("asset", ["office", "retail", "hotel"])
@pytest.mark.parametrize("strategy", ["income", "sale"])
@pytest.mark.parametrize("financing", ["equity", "equity_debt"])
def test_all_twelve_core_combinations_reconcile(asset, strategy, financing):
    result = calc(asset, strategy=strategy, financing=financing)
    assert result["uses_escrow"] is False
    assert result["checks"]["development_spend_reconciles"] is True
    assert result["checks"]["project_cashflow_reconciles"] is True
    assert result["checks"]["ending_debt_zero"] is True
    assert result["checks"]["peak_debt_within_limit"] is True
    assert min(result["monthly"]["debt_balance"]) >= -0.01
    assert len(result["monthly"]["months"]) == len(result["monthly"]["project_cashflow"])
    assert len(result["annual"]) >= 1
    for key in (
        "development_cost", "total_cost", "total_revenue", "equity_required",
        "peak_debt",
    ):
        assert result["kpi"][key] >= 0


def test_sale_quantity_is_conserved_and_price_growth_hits_price_not_quantity():
    result = calc(
        "office", strategy="sale", financing="equity",
        saleable_area_sqm=12000,
        sale_price_rub_sqm=300000,
        sale_price_growth_pct=12,
    )
    assert sum(result["monthly"]["sale_quantity"]) == pytest.approx(12000, abs=1e-6)
    prices = [value for value in result["monthly"]["sale_price"] if value > 0]
    assert prices[-1] > prices[0]
    assert result["checks"]["sale_quantity_reconciles"] is True


def test_simple_one_year_sale_has_exact_irr_and_equity_multiple():
    result = calc(
        "office",
        strategy="sale",
        financing="equity",
        land_cost_rub=1000,
        gross_area_sqm=0,
        construction_cost_rub_sqm=0,
        soft_cost_pct=0,
        contingency_pct=0,
        construction_months=1,
        sale_start_month=12,
        sale_months=1,
        sales_curve="flat",
        sale_price_growth_pct=0,
        saleable_area_sqm=1,
        sale_price_rub_sqm=1210,
        selling_cost_pct=0,
        exit_cost_pct=0,
    )
    assert result["kpi"]["project_irr"] == pytest.approx(0.21, abs=1e-6)
    assert result["kpi"]["equity_irr"] == pytest.approx(0.21, abs=1e-6)
    assert result["kpi"]["equity_multiple"] == pytest.approx(1.21, abs=1e-9)


def test_simple_debt_waterfall_records_equity_and_repayment():
    result = calc(
        "office",
        strategy="sale",
        financing="equity_debt",
        land_cost_rub=1000,
        gross_area_sqm=0,
        construction_cost_rub_sqm=0,
        soft_cost_pct=0,
        contingency_pct=0,
        construction_months=1,
        sale_start_month=1,
        sale_months=1,
        sales_curve="flat",
        saleable_area_sqm=1,
        sale_price_rub_sqm=2000,
        selling_cost_pct=0,
        debt_share_pct=60,
        debt_rate_pct=0,
        loan_fee_pct=0,
        sales_cash_sweep_pct=100,
    )
    assert result["monthly"]["debt_draw"][0] == pytest.approx(600)
    assert result["monthly"]["equity_injection"][0] == pytest.approx(400)
    assert result["monthly"]["debt_repayment"][1] == pytest.approx(600)
    assert result["monthly"]["debt_balance"][1] == pytest.approx(0)
    assert result["kpi"]["equity_required"] == pytest.approx(400)
    assert result["checks"]["ending_debt_zero"] is True
