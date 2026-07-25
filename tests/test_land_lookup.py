"""Тесты федерального поиска участка (/land/lookup).

Внешние сервисы не вызываются: сетевой слой подменяется фикстурами
с ответами НСПД и геокодеров. Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


# --- фикстуры ответов НСПД --------------------------------------------------

MYTISHCHI_FEATURE = {
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [4200000.0, 7550000.0],
            [4200100.0, 7550000.0],
            [4200100.0, 7550100.0],
            [4200000.0, 7550100.0],
            [4200000.0, 7550000.0],
        ]],
    },
    "properties": {
        "categoryName": "Земельные участки ЕГРН",
        "options": {
            "cad_num": "50:12:0080205:123",
            "readable_address": "Московская область, г. Мытищи, ул. Мира, д. 1",
            "land_record_area": 12500.0,
            "land_record_category_type": "Земли населённых пунктов",
            "permitted_use_established_by_document": "Многоэтажная жилая застройка",
            "cost_value": "45 000 000,50",
            "cost_application_date": "2024-01-01",
            "land_record_reg_date": "2005-06-14",
            "status": "Актуальный",
            "quarter_cad_number": "50:12:0080205",
            "ownership_type": "Частная собственность",
            "subject_rf": "Московская область",
        },
    },
}

BUILDING_FEATURE = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [37.6173, 55.7558]},
    "properties": {
        "categoryName": "Здания",
        "options": {
            "cad_num": "77:01:0001001:9999",
            "readable_address": "г. Москва, ул. Тверская, д. 1",
            "build_record_area": 3200.0,
            "year_built": "1998",
        },
    },
}


def payload(*features: dict) -> dict:
    return {"data": {"type": "FeatureCollection", "features": list(features)}}


@pytest.fixture(autouse=True)
def clear_cache():
    main._land_lookup_cache.clear()
    yield
    main._land_lookup_cache.clear()


# --- разбор кадастрового номера --------------------------------------------

def test_cadastral_parts_resolve_region_and_quarter():
    parts = main._cadastral_number_parts("50:12:0080205:123")
    assert parts["district_code"] == "50"
    assert parts["region_hint"] == "Московская область"
    assert parts["quarter"] == "50:12:0080205"


def test_cadastral_parts_unknown_district_is_empty():
    assert main._cadastral_number_parts("99:01:0000001:1")["region_hint"] == ""


# --- геометрия --------------------------------------------------------------

def test_mercator_center_converts_to_plausible_wgs84():
    center = main._geometry_center(MYTISHCHI_FEATURE["geometry"])
    assert 55.0 < center["lat"] < 57.0
    assert 37.0 < center["lng"] < 38.0
    assert center["merc_x"] == pytest.approx(4200050.0, abs=1.0)


def test_wgs84_geometry_is_not_reprojected():
    center = main._geometry_center(BUILDING_FEATURE["geometry"])
    assert center["lat"] == pytest.approx(55.7558, abs=1e-4)
    assert center["lng"] == pytest.approx(37.6173, abs=1e-4)


def test_geometry_without_coordinates_returns_none():
    assert main._geometry_center({"type": "Polygon", "coordinates": []}) is None
    assert main._geometry_center(None) is None


# --- нормализация ответа ЕГРН ----------------------------------------------

def test_normalized_land_feature_exposes_egrn_fields():
    item = main._normalize_nspd_feature(MYTISHCHI_FEATURE)
    assert item["found"] is True
    assert item["kind"] == "land"
    assert item["cadastral_number"] == "50:12:0080205:123"
    assert item["address"].startswith("Московская область")
    assert item["area_sqm"] == 12500.0
    assert item["area_ha"] == 1.25
    assert item["category"] == "Земли населённых пунктов"
    assert item["permitted_use"] == "Многоэтажная жилая застройка"
    assert item["cadastral_value_rub"] == pytest.approx(45_000_000.50)
    assert item["cadastral_value_mln"] == pytest.approx(45.0, abs=0.001)
    assert item["unit_value_rub_per_sqm"] == pytest.approx(3600.0, abs=0.1)
    assert item["ownership"] == "Частная собственность"
    assert item["region"] == "Московская область"
    assert item["map_url"].startswith(main._NSPD_BASE_URL)


def test_building_feature_is_classified_as_oks():
    item = main._normalize_nspd_feature(BUILDING_FEATURE)
    assert item["kind"] == "building"
    assert item["kind_label"] == "Объект капитального строительства"
    assert item["area_sqm"] == 3200.0


def test_region_falls_back_to_district_code():
    feature = {
        "type": "Feature",
        "geometry": None,
        "properties": {"categoryName": "Земельные участки ЕГРН", "options": {"cad_num": "23:43:0100000:5"}},
    }
    assert main._normalize_nspd_feature(feature)["region"] == "Краснодарский край"


# --- поиск по кадастровому номеру ------------------------------------------

def test_lookup_by_cadastral_number(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [MYTISHCHI_FEATURE])
    result = main.land_lookup(main.LandLookupRequest(query="50:12:0080205:123"))
    assert result["mode"] == "cadastral"
    assert result["found_count"] == 1
    assert result["results"][0]["area_ha"] == 1.25


def test_several_numbers_in_one_query(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [MYTISHCHI_FEATURE])
    result = main.land_lookup(
        main.LandLookupRequest(query="50:12:0080205:123, 50:12:0080205:124\n50:12:0080205:123")
    )
    # дубликаты убираются, оба уникальных номера обработаны
    assert [item["cadastral_number"] for item in result["results"]] == [
        "50:12:0080205:123",
        "50:12:0080205:123",
    ]


def test_missing_number_keeps_offline_hints(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [])
    result = main.land_lookup(main.LandLookupRequest(query="66:41:0000000:1"))
    item = result["results"][0]
    assert item["found"] is False
    assert item["region"] == "Свердловская область"
    assert item["quarter"] == "66:41:0000000"
    assert result["found_count"] == 0


def test_nspd_failure_is_reported_per_number(monkeypatch):
    def boom(query: str):
        raise HTTPException(status_code=502, detail="Сервис НСПД временно недоступен.")

    monkeypatch.setattr(main, "_nspd_search_features", boom)
    result = main.land_lookup(main.LandLookupRequest(query="77:01:0001001:1"))
    assert result["results"][0]["found"] is False
    assert "НСПД" in result["results"][0]["note"]


def test_number_limit_warns(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [])
    query = ", ".join(f"50:12:0080205:{i}" for i in range(8))
    result = main.land_lookup(main.LandLookupRequest(query=query, limit=3))
    assert len(result["results"]) == 3
    assert any("показаны первые 3" in w for w in result["warnings"])


# --- поиск по адресу --------------------------------------------------------

def test_address_found_directly_in_nspd(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [BUILDING_FEATURE, MYTISHCHI_FEATURE])
    result = main.land_lookup(main.LandLookupRequest(query="Мытищи, улица Мира, 1"))
    assert result["mode"] == "address"
    # земельные участки показываются раньше ОКС
    assert result["results"][0]["kind"] == "land"
    assert result["results"][1]["kind"] == "building"


def test_address_falls_back_to_geocoder_and_point_search(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [])
    monkeypatch.setattr(
        main,
        "_geocode_address",
        lambda address, limit: (
            [{"lat": 55.9105, "lng": 37.7365, "label": "Мытищи, Мира 1", "provider": "OpenStreetMap"}],
            [],
        ),
    )
    monkeypatch.setattr(main, "_nspd_point_features", lambda lat, lng: [MYTISHCHI_FEATURE])
    result = main.land_lookup(main.LandLookupRequest(query="Мытищи, улица Мира, 1"))
    assert result["found_count"] == 1
    assert result["results"][0]["matched_address"] == "Мытищи, Мира 1"
    assert result["results"][0]["geocoder"] == "OpenStreetMap"


def test_address_with_dadata_cadastral_number(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [MYTISHCHI_FEATURE] if ":" in query else [])
    monkeypatch.setattr(
        main,
        "_geocode_address",
        lambda address, limit: (
            [{
                "lat": 55.91,
                "lng": 37.73,
                "label": "Мытищи, Мира 1",
                "provider": "DaData",
                "cadastral_number": "50:12:0080205:123",
            }],
            [],
        ),
    )
    result = main.land_lookup(main.LandLookupRequest(query="Мытищи улица Мира 1"))
    assert result["results"][0]["cadastral_number"] == "50:12:0080205:123"


def test_unresolvable_address_warns(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [])
    monkeypatch.setattr(main, "_geocode_address", lambda address, limit: ([], []))
    result = main.land_lookup(main.LandLookupRequest(query="куда-то туда"))
    assert result["results"] == []
    assert any("Адрес не распознан" in w for w in result["warnings"])


# --- поиск по координатам ---------------------------------------------------

def test_coordinate_query(monkeypatch):
    seen: list[tuple[float, float]] = []

    def point_features(lat, lng):
        seen.append((lat, lng))
        return [MYTISHCHI_FEATURE]

    monkeypatch.setattr(main, "_nspd_point_features", point_features)
    result = main.land_lookup(main.LandLookupRequest(query="55.9105, 37.7365"))
    assert result["mode"] == "point"
    assert seen == [(55.9105, 37.7365)]
    assert result["found_count"] == 1


def test_out_of_range_coordinates_rejected(monkeypatch):
    monkeypatch.setattr(main, "_nspd_point_features", lambda lat, lng: [])
    with pytest.raises(HTTPException) as exc:
        main.land_lookup(main.LandLookupRequest(query="95.5, 37.7"))
    assert exc.value.status_code == 400


# --- валидация и кеш --------------------------------------------------------

def test_empty_query_rejected():
    with pytest.raises(HTTPException) as exc:
        main.land_lookup(main.LandLookupRequest(query="  "))
    assert exc.value.status_code == 400


def test_too_long_query_rejected():
    with pytest.raises(HTTPException) as exc:
        main.land_lookup(main.LandLookupRequest(query="а" * 501))
    assert exc.value.status_code == 400


def test_search_result_is_cached(monkeypatch):
    calls: list[str] = []

    def fetch(url, **kwargs):
        calls.append(url)
        return payload(MYTISHCHI_FEATURE)

    monkeypatch.setattr(main, "_land_fetch_json", fetch)
    first = main._nspd_search_features("50:12:0080205:123")
    second = main._nspd_search_features("50:12:0080205:123")
    assert first == second
    assert len(calls) == 1


def test_model_calculation_is_untouched_by_lookup_keys():
    # Ключи вида _land_lookup хранятся в inputs проекта и не должны ломать расчёт.
    request = main.CalcRequest(
        inputs={**main.DEFAULT_INPUTS, "_land_lookup": {"query": "50:12:0080205:123"}},
        tep=main.TEP_DEFAULT,
        rates=[],
    )
    baseline = main.calculate(main.CalcRequest(inputs=main.DEFAULT_INPUTS, tep=main.TEP_DEFAULT, rates=[]))
    assert main.calculate(request)["summary"] == baseline["summary"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
