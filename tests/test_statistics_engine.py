from pathlib import Path

from developaid_statistics import (
    NormalizedBenchmark,
    build_benchmark,
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
    assert payload["methodology_version"] == "2.0"
    assert payload["recommended"] == 168817
    assert payload["n"] == 1
    assert payload["confidence"] == "pilot"
