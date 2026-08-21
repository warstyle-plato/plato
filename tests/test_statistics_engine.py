from pathlib import Path

from developaid_cost_structure import build_cost_structure_matrix, class_adjustment_catalog
from developaid_statistics import (
    NormalizedBenchmark,
    build_benchmark,
    index_source_catalog,
    load_normalized_benchmarks,
    result_to_dict,
)


def point(**overrides):
    data = {
        "source": "test",
        "source_kind": "internal_project",
        "external_id": "test-1",
        "region": "Москва",
        "city": "Москва",
        "housing_class": "business",
        "reference_date": "2026-07-01",
        "value_rub_m2": 170000,
        "unit": "gba",
        "metric_type": "main_construction",
        "cost_scope": "above_ground_main",
        "source_url": None,
        "quality": 1.0,
        "active": True,
        "notes": "",
    }
    data.update(overrides)
    return NormalizedBenchmark(**data)


def test_does_not_mix_units_metrics_or_classes():
    rows = [
        point(),
        point(
            external_id="mass-full",
            source="СИС",
            source_kind="industry_benchmark",
            housing_class="mass_market",
            value_rub_m2=191692,
            unit="apartments",
            metric_type="full_construction_cost",
            cost_scope="developer_full_cost",
        ),
        point(
            external_id="comfort-main",
            housing_class="comfort",
            value_rub_m2=120000,
        ),
    ]
    result = build_benchmark(
        [],
        [],
        normalized=rows,
        region="Москва",
        housing_class="business",
        unit="gba",
        metric_type="main_construction",
    )
    assert result.n == 1
    assert round(result.recommended or 0) == 170000
    assert result.confidence == "pilot"
    assert len(result.comparable_points) == 1
    assert any(x["external_id"] == "mass-full" for x in result.external_benchmarks)


def test_wrong_unit_does_not_convert_silently():
    result = build_benchmark(
        [],
        [],
        normalized=[point()],
        region="Москва",
        housing_class="business",
        unit="sellable",
        metric_type="main_construction",
    )
    assert result.n == 0
    assert result.recommended is None


def test_no_silent_class_substitution():
    result = build_benchmark(
        [],
        [],
        normalized=[point(housing_class="business")],
        region="Москва",
        housing_class="premium",
        unit="gba",
        metric_type="main_construction",
    )
    assert result.n == 0
    assert result.recommended is None


def test_curated_moscow_business_seed_is_loaded():
    rows = load_normalized_benchmarks()
    result = build_benchmark(
        [],
        [],
        normalized=rows,
        region="Москва",
        housing_class="business",
        unit="gba",
        metric_type="main_construction",
    )
    payload = result_to_dict(result)
    assert payload["methodology_version"] == "2.1"
    assert payload["recommended"] == 168817
    assert payload["n"] == 1
    assert payload["confidence"] == "pilot"


def test_official_moscow_ncsm_is_packaged_as_two_distinct_denominators():
    rows = load_normalized_benchmarks()
    ncsm = [x for x in rows if x.source_kind == "official_normative" and x.region == "Москва"]
    assert {x.unit for x in ncsm} == {"apartments", "building_total"}
    apartments = next(x for x in ncsm if x.unit == "apartments")
    building = next(x for x in ncsm if x.unit == "building_total")
    assert apartments.value_low_rub_m2 == 139450
    assert apartments.value_high_rub_m2 == 147310
    assert building.value_low_rub_m2 == 90620
    assert building.value_high_rub_m2 == 100790


def test_moscow_declared_cost_is_not_gba():
    rows = load_normalized_benchmarks()
    declared = next(x for x in rows if x.external_id == "ac-moscow-eiszh-declared-cost-2025-06")
    assert declared.value_rub_m2 == 148000
    assert declared.unit == "building_total"
    assert declared.metric_type == "declared_construction_cost"


def test_index_sources_are_metadata_only_until_numeric_series_is_verified():
    rows = index_source_catalog()
    assert any(x["source"] == "Росстат" for x in rows)
    assert any(x["source"] == "Мосстат" and x["region"] == "Москва" for x in rows)
    assert all(x["automatic"] is False for x in rows)


def test_class_adjustment_is_explicit_expert_layer_with_comfort_base():
    cfg = class_adjustment_catalog()
    assert cfg["status"] == "expert_provisional"
    assert cfg["base_class"] == "comfort"
    assert cfg["components"]["main_above"]["comfort"] == 1.0
    assert cfg["components"]["main_above"]["business"] == 1.5
    assert cfg["components"]["landscaping"]["business"] == 1.35
    assert cfg["components"]["technical_connection"]["business"] == 1.0


def test_cost_structure_matrix_uses_developaid_rows_and_keeps_units():
    matrix = build_cost_structure_matrix(region="Москва", housing_class="business")
    assert matrix["methodology_version"] == "3.1"
    assert matrix["canonical_unit"] == "gba"
    keys = [x["key"] for x in matrix["components"]]
    assert "main_above" in keys
    assert "external_utilities" in keys
    assert "landscaping" in keys
    assert "construction_capex" in keys

    by_id = {x["source_id"]: x for x in matrix["sources"]}
    grodno = by_id["developaid-grodnenskaya-structure-2026-07"]
    assert grodno["cells"]["main_above"]["adjusted_value_rub_m2"] == 168816.78
    assert grodno["cells"]["main_above"]["unit"] == "above_ground"
    assert grodno["cells"]["main_under"]["unit"] == "underground"

    ncsm = by_id["mke-ncsm-apartments-2025-09"]
    assert ncsm["published"]["unit"] == "apartments"
    assert ncsm["published_class_adjusted"] is True
    assert ncsm["published_adjustment_ratio"] == 1.45
    assert ncsm["published_adjusted_value_rub_m2"] == 211975.5
    assert ncsm["published"]["unit"] != matrix["canonical_unit"]


def test_sis_combined_networks_and_landscaping_are_not_fake_split():
    matrix = build_cost_structure_matrix(region="Москва", housing_class="business")
    sis = next(x for x in matrix["sources"] if x["source_id"] == "sis-erz-moscow-2026-04")
    networks = sis["cells"]["external_utilities"]
    landscaping = sis["cells"]["landscaping"]
    assert networks["status"] == "combined_share"
    assert landscaping["status"] == "combined_share"
    assert networks["group"] == landscaping["group"] == "networks_landscaping"
    assert networks["share_low_pct"] == landscaping["share_low_pct"] == 8.0
    assert networks["share_high_pct"] == landscaping["share_high_pct"] == 12.0
