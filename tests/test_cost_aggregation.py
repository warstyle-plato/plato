from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from developaid_cost_aggregation import _candidate_from_cell, build_cost_recommendation
from statistics_feature import install


def test_business_recommendation_aggregates_by_developaid_article():
    result = build_cost_recommendation("Москва", "business", as_of=date(2026, 8, 21))
    by_key = {row["key"]: row for row in result["recommendations"]}

    main = by_key["main_above"]
    assert main["recommended_rub_m2"] == 168816.78
    assert main["unit"] == "gba"
    assert main["source_count"] == 1
    assert main["grade_counts"] == {"A": 1, "B": 0, "C": 0}
    assert main["confidence"] == "pilot"

    underground = by_key["main_under"]
    assert underground["recommended_rub_m2"] == 592526.29
    assert underground["unit"] == "underground"


def test_wrong_area_denominator_is_visible_but_excluded():
    result = build_cost_recommendation("Москва", "business", as_of=date(2026, 8, 21))
    capex = next(row for row in result["recommendations"] if row["key"] == "construction_capex")
    ncsm = next(source for source in capex["excluded_sources"] if source["source_id"] == "mke-ncsm-apartments-2025-09")

    assert ncsm["grade"] == "D"
    assert ncsm["included"] is False
    assert "не совпадает" in ncsm["reason"]


def test_class_adjustment_downgrades_direct_point_to_b():
    source = {
        "source_id": "x",
        "source": "x",
        "source_kind": "industry_benchmark",
        "reference_date": "2026-07-01",
        "comparability": "direct",
        "published": {"unit": "gba"},
    }
    cell = {
        "status": "value",
        "unit": "gba",
        "value_rub_m2": 100000,
        "adjusted_value_rub_m2": 125000,
        "class_adjusted": True,
    }
    candidate = _candidate_from_cell(source, "design", cell, as_of=date(2026, 8, 21))
    assert candidate["grade"] == "B"
    assert candidate["value_rub_m2"] == 125000
    assert candidate["included"] is True


def test_combined_share_is_not_fake_split_into_two_articles():
    result = build_cost_recommendation("Москва", "business", as_of=date(2026, 8, 21))
    by_key = {row["key"]: row for row in result["recommendations"]}
    for key in ("external_utilities", "landscaping"):
        sis = next(source for source in by_key[key]["excluded_sources"] if source["source_id"] == "sis-erz-moscow-2026-04")
        assert sis["grade"] == "D"
        assert "совместную долю" in sis["reason"]


def test_recommendation_api_and_page_expose_audit_chain():
    app = FastAPI()
    install(app)
    client = TestClient(app)

    response = client.get("/api/statistics/cost-recommendation", params={"region": "Москва", "class": "business"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["methodology_version"] == "3.1"
    assert payload["applyable_count"] > 0

    page = client.get("/statistics", params={"region": "Москва", "class": "business"})
    assert page.status_code == 200
    assert "Рекомендация DevelopAid" in page.text
    assert "Источники и нормализация" in page.text
    assert "A — прямое совпадение" in page.text
    assert "как опубликовано → нормализация" in page.text
