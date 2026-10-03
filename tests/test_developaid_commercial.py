"""Commercial beta is independent from residential escrow economics."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import developaid_commercial as commercial


def test_equity_only_has_no_debt_or_escrow():
    result = commercial.calculate(commercial.CommercialRequest(
        asset_type="office", strategy="income", financing_mode="equity", inputs={}
    ))
    assert result["uses_escrow"] is False
    assert result["kpi"]["peak_debt"] == 0
    assert result["kpi"]["financing_cost"] == 0
    assert "escrow" not in result["monthly"]


def test_partial_debt_reduces_initial_equity_need_and_accrues_interest():
    equity = commercial.calculate(commercial.CommercialRequest(
        asset_type="office", strategy="sale", financing_mode="equity", inputs={}
    ))
    leveraged = commercial.calculate(commercial.CommercialRequest(
        asset_type="office",
        strategy="sale",
        financing_mode="equity_debt",
        inputs={"debt_share_pct": 50, "debt_rate_pct": 15},
    ))
    assert leveraged["kpi"]["peak_debt"] > 0
    assert leveraged["kpi"]["financing_cost"] > 0
    assert leveraged["kpi"]["equity_required"] < equity["kpi"]["equity_required"]


def test_sale_strategy_is_direct_cash_without_terminal_value():
    result = commercial.calculate(commercial.CommercialRequest(
        asset_type="retail", strategy="sale", financing_mode="equity", inputs={}
    ))
    assert sum(result["monthly"]["sale_revenue"]) > 0
    assert sum(result["monthly"]["terminal_value"]) == 0
    sales = next(section for section in result["report"]["sections"] if section["name"] == "Продажи")
    assert sales["metrics"]["Эскроу, ₽"] == 0


def test_hotel_income_exposes_hotel_kpis():
    result = commercial.calculate(commercial.CommercialRequest(
        asset_type="hotel", strategy="income", financing_mode="equity", inputs={}
    ))
    assert result["operating"]["revpar"] > 0
    assert result["kpi"]["stabilized_noi_annual"] != 0
    assert result["report"]["title"] == "Гостиничная экономика"


def test_routes_are_separate_from_residential_calculate():
    app = FastAPI()
    commercial.install(app)
    client = TestClient(app)

    form = client.get("/api/v2/commercial/form")
    assert form.status_code == 200
    assert {item["value"] for item in form.json()["asset_types"]} == {
        "office", "retail", "hotel",
    }

    response = client.post("/api/v2/commercial/calculate", json={
        "asset_type": "office",
        "strategy": "sale",
        "financing_mode": "equity_debt",
        "inputs": {"debt_share_pct": 40},
    })
    assert response.status_code == 200
    assert response.json()["uses_escrow"] is False
