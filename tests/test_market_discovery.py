from __future__ import annotations

from pathlib import Path

from market_search.providers.domrf import DomRfProvider, haversine_km
from market_search.service import MarketDiscoveryService


def test_haversine_is_zero_for_same_point() -> None:
    assert haversine_km(55.0, 37.0, 55.0, 37.0) == 0


def test_domrf_normalises_official_links(tmp_path: Path) -> None:
    provider = DomRfProvider(tmp_path)
    marker = {"objId": 64438, "latitude": 55.8, "longitude": 37.5}
    detail = {
        "nameObj": "Тестовый корпус",
        "address": "Москва, тестовый адрес",
        "developer": {"devShortCleanNm": "Застройщик"},
        "objPriceAvg": 601000,
        "rpdNum": "77-000000",
        "rpdPdfLink": "https://example.test/declaration.pdf",
    }
    item = provider._normalise(marker, detail, 0.4, 64438)
    assert item.object_id == 64438
    assert item.domrf_url.endswith("/64438")
    assert item.project_declaration_number == "77-000000"
    assert item.average_price_sqm == 601000


def test_service_accepts_coordinates_without_geocoder(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    service.domrf.nearby = lambda point, radius_km, limit: []  # type: ignore[method-assign]
    result = service.discover(
        address="Москва, ул. Мишина, 46",
        latitude=55.8,
        longitude=37.5,
        radius_km=3,
        limit=20,
    )
    assert result["location"]["provider"] == "manual_coordinates"
    assert result["source"]["unit"] == "корпус"
