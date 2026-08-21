from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from developaid_cost_aggregation import _candidate_from_cell, build_cost_recommendation
from statistics_feature import install


PROFSOYUZNAYA_TEP = {
    "gba_sqm": 60322,
    "sellable_sqm": 31526,
    "underground_gns_sqm": 12915,
}

# Full project area, not the 7,711 m² remaining-sales plan from the 2026 control model.
GRODNENSKAYA_TEP = {
    "gba_sqm": 22032.9,
    "sellable_sqm": 13710,
}


def test_business_recommendation_keeps_exact_developaid_bases():
    result = build_cost_recommendation("Москва", "business", as_of=date(2026, 8, 21))
    by_key = {row["key"]: row for row in result["recommendations"]}

    main = by_key["main_above"]
    assert main["recommended_rub_m2"] == 168816.78
    assert main["unit"] == "above_ground"
    assert main["source_count"] == 1
    assert main["grade_counts"] == {"A": 1, "B": 0, "C": 0}

    underground = by_key["main_under"]
    assert underground["recommended_rub_m2"] == 592526.29
    assert underground["unit"] == "underground"

    # A project-specific zero must not become a market recommendation.
    assert by_key["commissioning"]["recommended_rub_m2"] is None


def test_sellable_source_is_converted_through_target_project_tep():
    result = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    by_key = {row["key"]: row for row in result["recommendations"]}

    assert result["target_areas"]["above_ground_gns_sqm"] == 47407

    design = by_key["design"]
    assert design["source_count"] == 1
    assert design["recommended_rub_m2"] == pytest.approx(4442.34, abs=0.01)
    core = design["included_sources"][0]
    assert core["source_id"] == "core-xp-moscow-business-2024-09"
    assert core["grade"] == "B"
    assert core["source_unit"] == "sellable"
    assert core["unit"] == "gba"
    assert core["conversion_factor"] == pytest.approx(31526 / 60322, abs=1e-6)


def test_article_consensus_uses_multiple_independent_sources_not_simple_listing():
    result = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    utilities = next(row for row in result["recommendations"] if row["key"] == "external_utilities")

    assert utilities["source_count"] == 2
    assert utilities["recommended_rub_m2"] == pytest.approx(7242.69, abs=0.02)
    assert {x["source_id"] for x in utilities["included_sources"]} == {
        "developaid-grodnenskaya-structure-2026-07",
        "core-xp-moscow-business-2024-09",
    }
    assert utilities["recommended_rub_m2"] != utilities["baseline_rub_m2"]


def test_same_market_sources_normalize_differently_for_grodnenskaya_and_profsoyuznaya():
    prof = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    grod = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=GRODNENSKAYA_TEP
    )
    prof_rows = {row["key"]: row for row in prof["recommendations"]}
    grod_rows = {row["key"]: row for row in grod["recommendations"]}

    # CORE.XP is published per sellable m². The same market rate must therefore
    # normalize to a different GNS rate for projects with different efficiency.
    prof_design = prof_rows["design"]
    grod_design = grod_rows["design"]
    assert prof_design["recommended_rub_m2"] == pytest.approx(4442.34, abs=0.02)
    assert grod_design["recommended_rub_m2"] == pytest.approx(5289.14, abs=0.02)
    assert prof_design["recommended_rub_m2"] < grod_design["recommended_rub_m2"]

    # Where both the internal project observation and CORE.XP are comparable,
    # the result is a real weighted consensus, not a copied source value.
    assert prof_rows["preparation"]["recommended_rub_m2"] == pytest.approx(3972.76, abs=0.03)
    assert grod_rows["preparation"]["recommended_rub_m2"] == pytest.approx(4329.17, abs=0.03)
    assert prof_rows["external_utilities"]["recommended_rub_m2"] == pytest.approx(7242.69, abs=0.03)
    assert grod_rows["external_utilities"]["recommended_rub_m2"] == pytest.approx(7429.38, abs=0.03)
    assert prof_rows["landscaping"]["recommended_rub_m2"] == pytest.approx(5948.00, abs=0.03)
    assert grod_rows["landscaping"]["recommended_rub_m2"] == pytest.approx(6100.75, abs=0.03)


def test_core_class_slices_from_one_study_get_one_vote():
    result = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    utilities = next(row for row in result["recommendations"] if row["key"] == "external_utilities")

    core_included = [x for x in utilities["included_sources"] if x["source_id"].startswith("core-xp-")]
    core_excluded = [x for x in utilities["excluded_sources"] if x["source_id"].startswith("core-xp-")]
    assert [x["source_id"] for x in core_included] == ["core-xp-moscow-business-2024-09"]
    assert len(core_excluded) == 2
    assert all("та же выборка" in x["reason"] for x in core_excluded)


def test_core_smr_is_not_fake_split_above_and_below_ground():
    result = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    by_key = {row["key"]: row for row in result["recommendations"]}

    for key in ("main_above", "main_under"):
        core = next(
            x for x in by_key[key]["excluded_sources"] if x["source_id"] == "core-xp-moscow-business-2024-09"
        )
        assert core["grade"] == "D"
        assert "более широкий итог" in core["reason"]


def test_wrong_scope_is_visible_but_excluded_from_construction_capex():
    result = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    capex = next(row for row in result["recommendations"] if row["key"] == "construction_capex")
    core = next(source for source in capex["excluded_sources"] if source["source_id"] == "core-xp-moscow-business-2024-09")

    assert core["grade"] == "D"
    assert core["included"] is False
    assert "scope" in core["reason"]


def test_class_adjustment_downgrades_direct_point_to_b():
    source = {
        "source_id": "x",
        "source_group": "x",
        "source": "x",
        "source_kind": "industry_benchmark",
        "base_class": "comfort",
        "target_class": "business",
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
        "class_adjustment_ratio": 1.25,
    }
    candidate = _candidate_from_cell(source, "design", cell, as_of=date(2026, 8, 21))
    assert candidate["grade"] == "B"
    assert candidate["value_rub_m2"] == 125000
    assert candidate["included"] is True


def test_combined_share_is_not_fake_split_into_two_articles():
    result = build_cost_recommendation(
        "Москва", "business", as_of=date(2026, 8, 21), target_areas=PROFSOYUZNAYA_TEP
    )
    by_key = {row["key"]: row for row in result["recommendations"]}
    for key in ("external_utilities", "landscaping"):
        sis = next(source for source in by_key[key]["excluded_sources"] if source["source_id"] == "sis-erz-moscow-2026-04")
        assert sis["grade"] == "D"
        assert "совместную долю" in sis["reason"]


def test_recommendation_api_and_page_expose_audit_chain_for_both_project_shapes():
    app = FastAPI()
    install(app)
    client = TestClient(app)

    project_params = [
        {
            "region": "Москва",
            "class": "business",
            "gba_sqm": 60322,
            "sellable_sqm": 31526,
            "underground_gns_sqm": 12915,
        },
        {
            "region": "Москва",
            "class": "business",
            "gba_sqm": 22032.9,
            "sellable_sqm": 13710,
        },
    ]

    for params in project_params:
        response = client.get("/api/statistics/cost-recommendation", params=params)
        assert response.status_code == 200
        payload = response.json()
        assert payload["methodology_version"] == "3.2"
        assert payload["model_parameters_th_rub_m2"]["main_above_th_per_sqm"] == pytest.approx(168.817, abs=0.001)

        page = client.get("/statistics", params=params)
        assert page.status_code == 200
        assert "Рекомендация DevelopAid" in page.text
        assert "Источники и нормализация" in page.text
        assert "CORE.XP" in page.text
        assert "как опубликовано → статья → класс → база площади" in page.text

    prof_payload = client.get("/api/statistics/cost-recommendation", params=project_params[0]).json()
    assert prof_payload["target_areas"]["above_ground_gns_sqm"] == 47407
