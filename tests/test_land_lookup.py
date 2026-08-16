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

# main.py — тонкая обёртка Telegram-слоя; расчётное ядро и эндпоинты живут
# в main_legacy.py, который обёртка загружает как модуль core.
import main as _wrapper  # noqa: E402

main = _wrapper.core


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
    # По адресу остаются только земельные участки, ОКС уходит в скрытые.
    assert [item["kind"] for item in result["results"]] == ["land"]
    assert result["hidden"] == {"building": 1}
    # Со снятым фильтром возвращаются оба, участок по-прежнему первым.
    both = main.land_lookup(main.LandLookupRequest(
        query="Мытищи, улица Мира, 1", include_premises=True
    ))
    assert [item["kind"] for item in both["results"]] == ["land", "building"]


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


def test_point_fallback_is_wms_get_feature_info(monkeypatch):
    """Точечный запрос — WMS GetFeatureInfo слоя ЗУ, а не мёртвый intersects.

    Текстовый поиск «lat lng» и GET /intersects на точках отвечают пустотой;
    рабочий путь — запрос, которым карта НСПД отвечает на клик. Тест пинует
    маршрут, слой и попадание точки в BBOX/пиксель тайла.
    """
    lat, lng = 55.802, 37.573  # Мишина, 46 — участок 77:09:0004014:13 есть
    seen: list[str] = []

    def fetch(url, *, service, **kwargs):
        seen.append(url)
        return {"type": "FeatureCollection", "features": [MYTISHCHI_FEATURE]}

    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [])
    monkeypatch.setattr(main, "_land_fetch_json", fetch)
    features = main._nspd_point_features(lat, lng)
    assert features == [MYTISHCHI_FEATURE]
    assert len(seen) == 1
    url = seen[0]
    assert f"/api/aeggis/v3/{main._NSPD_LANDS_LAYER_ID}/wms?" in url
    import urllib.parse as _up

    params = dict(_up.parse_qsl(_up.urlsplit(url).query))
    assert params["REQUEST"] == "GetFeatureInfo"
    assert params["INFO_FORMAT"] == "application/json"
    assert params["QUERY_LAYERS"] == str(main._NSPD_LANDS_LAYER_ID)
    west, south, east, north = (float(x) for x in params["BBOX"].split(","))
    assert west <= lng <= east and south <= lat <= north
    size = int(params["WIDTH"])
    assert params["WIDTH"] == params["HEIGHT"]
    assert 0 <= int(params["I"]) <= size and 0 <= int(params["J"]) <= size
    assert params["FEATURE_COUNT"] != "1"


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


# --- маршрутизация Москва / Московская область ------------------------------

def test_new_moscow_number_stays_on_glavapu():
    """У Новой Москвы кадастры тоже 50:*, один префикс не выбирает область."""
    moscow = {"territory": {"inside_moscow": True}}
    assert main.cadastral_route(["50:20:0010101:1"], moscow) == "moscow"


def test_region_number_falls_back_to_the_region_calculator():
    outside = {"territory": {"inside_moscow": False}}
    assert main.cadastral_route(["50:20:0010101:1"], outside) == "mo"


def test_region_number_uses_the_region_calculator_when_glavapu_fails():
    assert main.cadastral_route(["50:20:0010101:1"], None) == "mo"


def test_moscow_number_without_glavapu_is_an_error():
    assert main.cadastral_route(["77:01:0001001:1"], None) == "error"


def test_mixed_numbers_are_not_treated_as_region_only():
    outside = {"territory": {"inside_moscow": False}}
    assert main.cadastral_route(["50:20:1:1", "77:01:1:1"], outside) == "moscow"


def test_empty_list_without_analysis_is_an_error():
    assert main.cadastral_route([], None) == "error"


# --- транспорт НСПД ---------------------------------------------------------

def test_nspd_requests_carry_browser_headers():
    captured = {}

    class Response:
        def read(self, _limit): return b'{"data":{"features":[]}}'
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_urlopen(request, timeout=None, context=None):
        captured["headers"] = dict(request.headers)
        captured["url"] = request.full_url
        return Response()

    original = main.urllib.request.urlopen
    main.urllib.request.urlopen = fake_urlopen
    try:
        main._land_fetch_json(main._NSPD_BASE_URL + "/api/x", service="Сервис НСПД")
    finally:
        main.urllib.request.urlopen = original
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert "Chrome" in headers["User-agent".lower()]
    assert headers["Referer".lower()].startswith("https://nspd.gov.ru")
    assert headers["Origin".lower()] == "https://nspd.gov.ru"


def test_other_hosts_keep_the_plain_user_agent():
    captured = {}

    class Response:
        def read(self, _limit): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_urlopen(request, timeout=None, context=None):
        captured["headers"] = dict(request.headers)
        return Response()

    original = main.urllib.request.urlopen
    main.urllib.request.urlopen = fake_urlopen
    try:
        main._land_fetch_json("https://example.org/api", service="Тест")
    finally:
        main.urllib.request.urlopen = original
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["User-agent".lower()] == main._LAND_LOOKUP_USER_AGENT
    assert "referer" not in headers


def test_search_query_asks_for_wgs84():
    captured = {}

    def fake_fetch(url, *, service, **kwargs):
        captured["url"] = url
        return {"data": {"features": []}}

    original = main._land_fetch_json
    main._land_fetch_json = fake_fetch
    try:
        main._nspd_search_features("50:20:0010101:1")
    finally:
        main._land_fetch_json = original
    assert "CRS=EPSG%3A4326" in captured["url"]


def test_providers_report_the_tls_state():
    state = main.land_lookup_providers()["nspd_tls"]
    assert set(state) == {"fallback_allowed", "verification_disabled"}
    assert state["fallback_allowed"] is True


def test_tls_failure_retries_once_without_verification_and_is_reported():
    """Сертификат НСПД выпущен национальным УЦ: повторяем без проверки, но явно."""
    import ssl as ssl_module

    calls = []

    class Response:
        def read(self, _limit): return b'{"data":{"features":[]}}'
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_urlopen(request, timeout=None, context=None):
        calls.append(context)
        if len(calls) == 1:
            raise main.urllib.error.URLError(ssl_module.SSLError("CERTIFICATE_VERIFY_FAILED"))
        return Response()

    original = main.urllib.request.urlopen
    was_insecure = main._nspd_tls_insecure
    main._nspd_tls_insecure = False
    main.urllib.request.urlopen = fake_urlopen
    try:
        main._land_fetch_json(main._NSPD_BASE_URL + "/api/x", service="Сервис НСПД")
        assert len(calls) == 2
        assert calls[0] is None
        assert calls[1].verify_mode == ssl_module.CERT_NONE
        assert main.land_lookup_providers()["nspd_tls"]["verification_disabled"] is True
    finally:
        main.urllib.request.urlopen = original
        main._nspd_tls_insecure = was_insecure


def test_plain_network_failure_is_not_retried_insecurely():
    calls = []

    def fake_urlopen(request, timeout=None, context=None):
        calls.append(context)
        raise main.urllib.error.URLError("connection refused")

    original = main.urllib.request.urlopen
    was_insecure = main._nspd_tls_insecure
    main._nspd_tls_insecure = False
    main.urllib.request.urlopen = fake_urlopen
    try:
        with pytest.raises(HTTPException):
            main._land_fetch_json(main._NSPD_BASE_URL + "/api/x", service="Сервис НСПД")
        assert len(calls) == 1
        assert main._nspd_tls_insecure is False
    finally:
        main.urllib.request.urlopen = original
        main._nspd_tls_insecure = was_insecure


# --- помещения в поиске по адресу -------------------------------------------

def feature(number: str, label: str, area: float) -> dict:
    return {"properties": {"cad_num": number, "categoryName": label, "land_record_area": area}}


ADDRESS_FEATURES = [
    feature("50:12:0100131:497", "Земельные участки", 10181.8),
    feature("50:12:0100131:1001", "Помещения", 62.5),
    feature("50:12:0100131:1002", "Помещения", 13.2),
    feature("50:12:0100131:900", "Здания", 4200.0),
]


def test_premises_are_classified_apart_from_buildings():
    kinds = {
        item["cadastral_number"]: item["kind"]
        for item in (main._normalize_nspd_feature(f) for f in ADDRESS_FEATURES)
    }
    assert kinds["50:12:0100131:497"] == "land"
    assert kinds["50:12:0100131:1001"] == "premise"
    assert kinds["50:12:0100131:900"] == "building"


def test_address_search_hides_flats_and_parking(monkeypatch):
    """По адресу в ЕГРН стоят сотни помещений, а нужен участок."""
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: ADDRESS_FEATURES)
    result = main.land_lookup(main.LandLookupRequest(query="Мытищи, улица Мира, 1"))
    assert [item["kind"] for item in result["results"]] == ["land"]
    assert result["hidden"] == {"premise": 2, "building": 1}
    assert result["hidden_count"] == 3
    assert any("Показаны только земельные участки" in text for text in result["warnings"])


def test_hidden_premises_can_be_asked_for(monkeypatch):
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: ADDRESS_FEATURES)
    result = main.land_lookup(main.LandLookupRequest(
        query="Мытищи, улица Мира, 1", include_premises=True
    ))
    assert len(result["results"]) == 4
    assert result["hidden"] == {}


def test_a_premise_asked_by_its_number_is_never_hidden(monkeypatch):
    """Спросили квартиру по кадастровому номеру — обязаны её показать."""
    monkeypatch.setattr(main, "_nspd_search_features", lambda query: [
        {"properties": {"cad_num": "50:12:0100131:1001", "categoryName": "Помещения",
                        "build_record_area": 62.5}}
    ])
    result = main.land_lookup(main.LandLookupRequest(query="50:12:0100131:1001"))
    assert [item["kind"] for item in result["results"]] == ["premise"]
    assert result["hidden"] == {}


def test_unknown_category_is_not_taken_for_a_parcel():
    """Незнакомая категория не должна попадать в площадь территории."""
    kind = main._nspd_object_kind(
        {"properties": {"categoryName": "Что-то новое от НСПД"}},
        {"land_record_area": 100.0},
    )
    assert kind == "other"


@pytest.mark.parametrize("label, expected", [
    ("Земельные участки", "land"),
    ("Земельный участок", "land"),
    ("Помещения", "premise"),
    ("Машино-места", "premise"),
    ("Квартиры", "premise"),
    ("Здания", "building"),
    ("Сооружения", "building"),
    ("Объекты незавершённого строительства", "building"),
    ("Единый недвижимый комплекс", "building"),
])
def test_category_label_decides_the_kind(label, expected):
    assert main._nspd_object_kind({"properties": {"categoryName": label}}, {}) == expected


def test_fields_decide_only_when_there_is_no_label():
    assert main._nspd_object_kind({"properties": {}}, {"land_record_area": 100.0}) == "land"
    assert main._nspd_object_kind({"properties": {}}, {"build_record_area": 100.0}) == "building"


def test_no_hidden_limit_of_five_or_ten_anywhere():
    """Лимиты расходились: карточка ЕГРН слала 5, эндпоинт МО по умолчанию 10.
    Страница обещает до 30 участков — столько и должно браться везде."""
    assert main._LAND_LOOKUP_MAX_RESULTS == 30
    assert main.LandLookupRequest().limit == 30
    assert main.MoCalculateRequest().limit == 30
    assert "limit:5" not in main.PAGE
    assert main.PAGE.count("limit:30") >= 2


# --- капризы НСПД: промах — это повтор, а не приговор ------------------------
# Из 22 участков Мытищ в расчёт вошли 20: НСПД ответил пусто на два номера,
# пустой ответ прилип в кэш на 15 минут, и площадь территории молча потеряла
# восемь гектаров — вместе с квартирами, населением и социалкой.

def nspd_search_payload():
    return {"data": {"features": [MYTISHCHI_FEATURE]}}


def test_an_empty_nspd_answer_is_not_cached(monkeypatch):
    """Пустой ответ — чаще сбой портала, чем отсутствие сведений."""
    answers = [{"data": {"features": []}}, nspd_search_payload()]
    monkeypatch.setattr(main, "_land_fetch_json", lambda url, service="": answers.pop(0))

    assert main._nspd_search_features("50:12:0080205:123") == []
    assert main._nspd_search_features("50:12:0080205:123"), \
        "промах прилип в кэше — повторный запрос не дошёл до НСПД"


def test_a_missed_parcel_is_retried_before_giving_up(monkeypatch):
    """Параллельный опрос теряет часть номеров — второй заход обязателен."""
    calls: dict[str, int] = {}

    def flaky(number):
        calls[number] = calls.get(number, 0) + 1
        # Первый запрос второго участка — «пусто», повторный — находит.
        if number.endswith(":2") and calls[number] == 1:
            return []
        feature = {**MYTISHCHI_FEATURE, "properties": {
            **MYTISHCHI_FEATURE["properties"],
            "options": {**MYTISHCHI_FEATURE["properties"]["options"], "cad_num": number},
        }}
        return [feature]

    monkeypatch.setattr(main, "_nspd_search_features", flaky)
    results = main._land_lookup_by_numbers(["50:12:0080205:1", "50:12:0080205:2"])

    assert [item["found"] for item in results] == [True, True], \
        "участок выпал из расчёта без повторной попытки"
    assert calls["50:12:0080205:2"] == 2


def test_the_card_shouts_about_missing_parcels():
    """Площадь занижена — предупреждение стоит рядом с площадью, а не в логе."""
    import inspect
    module_source = inspect.getsource(main)
    card = module_source[module_source.index("Участок в Московской области") - 4000:]
    card = card[:card.index("Социальная нагрузка")]
    assert "занижены" in card, "карточка МО молчит о потерянных участках"
