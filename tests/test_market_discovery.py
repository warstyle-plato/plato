from __future__ import annotations

import base64
import json
from pathlib import Path

from market_search.geocoder import GeoPoint, GeocodingError
from market_search.price import MarketPriceEnricher, weighted_market_price
from market_search.service import MarketDiscoveryService, haversine_km
from market_search.yandex_search import (
    SearchDoc,
    YandexSearchClient,
    extract_project_candidates,
    official_cards_from_docs,
)


def test_haversine_is_zero_for_same_point() -> None:
    assert haversine_km(55.0, 37.0, 55.0, 37.0) == 0


def _search_xml() -> bytes:
    return b'''<?xml version="1.0" encoding="utf-8"?>
    <yandexsearch><response><results><grouping><group><doc>
      <url>https://domclick.ru/complexes/test</url>
      <domain>domclick.ru</domain>
      <title>\xd0\x96\xd0\x9a <hlword>Symphony 34</hlword> \xe2\x80\x94 \xd0\xba\xd0\xb2\xd0\xb0\xd1\x80\xd1\x82\xd0\xb8\xd1\x80\xd1\x8b</title>
      <passages><passage>\xd0\x96\xd0\xb8\xd0\xbb\xd0\xbe\xd0\xb9 \xd0\xba\xd0\xbe\xd0\xbc\xd0\xbf\xd0\xbb\xd0\xb5\xd0\xba\xd1\x81 \xd0\xb2 \xd0\x9c\xd0\xbe\xd1\x81\xd0\xba\xd0\xb2\xd0\xb5</passage></passages>
    </doc></group></grouping></results></response></yandexsearch>'''


def test_yandex_search_rest_raw_data_is_decoded() -> None:
    xml = _search_xml()
    body = json.dumps({"rawData": base64.b64encode(xml).decode("ascii")}).encode("utf-8")
    assert YandexSearchClient._decode_rest_response(body) == xml


def test_yandex_search_xml_is_parsed() -> None:
    docs = YandexSearchClient._parse_response(_search_xml())
    assert len(docs) == 1
    assert docs[0].title.startswith("ЖК Symphony 34")
    assert docs[0].domain == "domclick.ru"


def test_candidate_name_is_extracted_from_domclick_project_result() -> None:
    docs = [
        SearchDoc(
            title="ЖК Symphony 34 — квартиры от застройщика",
            url="https://domclick.ru/complexes/symphony34",
            domain="domclick.ru",
            snippet="Жилой комплекс в Москве",
            rank=1,
        )
    ]
    candidates = extract_project_candidates(docs)
    assert candidates[0]["name"] == "Symphony 34"


def test_domclick_flat_listing_is_not_a_project_candidate() -> None:
    docs = [
        SearchDoc(
            title="Купить 1-комнатную квартиру, 35.8 м² по адресу Москва, Писцовая",
            url="https://domclick.ru/card/sale__flat__12345",
            domain="domclick.ru",
            snippet="1-комнатная квартира в Савёловском районе",
            rank=1,
        ),
        SearchDoc(
            title="Башиловская улица, 23 к4",
            url="https://domclick.ru/building/12345",
            domain="domclick.ru",
            snippet="Квартиры в доме",
            rank=2,
        ),
    ]
    assert extract_project_candidates(docs) == []


def test_official_domrf_card_is_recognised_without_fetching_page() -> None:
    docs = [
        SearchDoc(
            title="Объект строительства",
            url="https://наш.дом.рф/сервисы/проверка_новостроек/64438",
            domain="наш.дом.рф",
            snippet="Официальная карточка ЕИСЖС",
            rank=1,
        )
    ]
    cards = official_cards_from_docs(docs)
    assert cards[0]["object_id"] == 64438
    assert cards[0]["url"].endswith("/64438")


def test_non_object_domrf_page_is_not_an_official_card() -> None:
    docs = [
        SearchDoc(
            title="Наш.Дом.РФ",
            url="https://наш.дом.рф/сервисы/проверка_новостроек",
            domain="наш.дом.рф",
            snippet="Каталог новостроек",
            rank=1,
        )
    ]
    assert official_cards_from_docs(docs) == []


def test_price_enricher_extracts_price_range_and_offers(tmp_path: Path) -> None:
    search = YandexSearchClient(tmp_path)
    docs = [
        SearchDoc(
            title="ЖК Symphony 34 — квартиры от застройщика",
            url="https://domclick.ru/complexes/symphony34",
            domain="domclick.ru",
            snippet="140 квартир. Цена за м² от 518 940 ₽/м² до 664 000 ₽/м²",
            rank=1,
        ),
        SearchDoc(
            title="ЖК Symphony 34 — новостройка",
            url="https://realty.yandex.ru/complex/symphony34",
            domain="realty.yandex.ru",
            snippet="Средняя цена 601 000 ₽/м², 139 предложений",
            rank=2,
        ),
    ]
    search.search = lambda query, groups_on_page=10: docs  # type: ignore[method-assign]
    price = MarketPriceEnricher(search).project_price("Symphony 34", "Москва")
    assert price["available"] is True
    assert price["min_price_per_sqm"] == 518_940
    assert price["max_price_per_sqm"] == 664_000
    assert price["price_per_sqm"] == 601_000
    assert price["offers_count"] == 140


def test_weighted_market_price_uses_confirmed_analogues_only() -> None:
    result = weighted_market_price(
        [
            {
                "name": "A",
                "confirmed": True,
                "distance_km": 1.0,
                "market_price": {"available": True, "price_per_sqm": 600_000},
            },
            {
                "name": "B",
                "confirmed": True,
                "distance_km": 2.0,
                "market_price": {"available": True, "price_per_sqm": 700_000},
            },
            {
                "name": "C",
                "confirmed": False,
                "distance_km": 0.1,
                "market_price": {"available": True, "price_per_sqm": 1_500_000},
            },
        ]
    )
    assert result is not None
    assert result["analogue_count"] == 2
    assert result["price_per_sqm"] == 633_333


def test_official_card_requires_name_or_address_match(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    wrong = {
        "title": "ЖК Городские истории",
        "snippet": "Москва, Бескудниковский район, Дмитровское шоссе, дом 89",
    }
    assert service._official_card_matches("Symphony 34", None, wrong) is False

    right_by_name = {
        "title": "ЖК Symphony 34",
        "snippet": "Официальный объект строительства",
    }
    assert service._official_card_matches("Symphony 34", None, right_by_name) is True

    right_by_address = {
        "title": "Жилой дом",
        "snippet": "Москва, улица Мишина, дом 46",
    }
    assert service._official_card_matches("Проект без маркетингового имени", "Москва, улица Мишина, 46", right_by_address) is True


def test_service_filters_by_radius_and_requires_official_confirmation(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)

    discovery = [
        SearchDoc(
            title="ЖК Symphony 34 — квартиры от застройщика",
            url="https://domclick.ru/complexes/symphony34",
            domain="domclick.ru",
            snippet="Москва",
            rank=1,
        )
    ]
    official = [
        SearchDoc(
            title="Symphony 34",
            url="https://наш.дом.рф/сервисы/проверка_новостроек/64438",
            domain="наш.дом.рф",
            snippet="Официальный объект",
            rank=1,
        )
    ]

    service.search.search = lambda query, groups_on_page=10: official if "site:наш.дом.рф" in query else discovery  # type: ignore[method-assign]
    service.geocoder.geocode = lambda query: GeoPoint(55.795, 37.575, query, "test", "exact")  # type: ignore[method-assign]

    result = service.discover(
        address="Москва, ул. Мишина, 46",
        latitude=55.795,
        longitude=37.575,
        radius_km=3,
        limit=10,
    )
    assert result["count"] == 1
    assert result["confirmed_count"] == 1
    assert result["projects"][0]["confirmed"] is True
    assert result["source"]["discovery"] == "Yandex Search API"


def test_service_drops_candidate_without_coordinates(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    discovery = [
        SearchDoc(
            title="ЖК Unknown Place — квартиры",
            url="https://domclick.ru/complexes/unknown",
            domain="domclick.ru",
            snippet="Москва",
            rank=1,
        )
    ]
    service.search.search = lambda query, groups_on_page=10: [] if "site:наш.дом.рф" in query else discovery  # type: ignore[method-assign]

    def no_geo(query: str) -> GeoPoint:
        raise GeocodingError("не найдено")

    service.geocoder.geocode = no_geo  # type: ignore[method-assign]
    result = service.discover(
        address="Москва, ул. Мишина, 46",
        latitude=55.795,
        longitude=37.575,
        radius_km=3,
        limit=10,
    )
    assert result["count"] == 0
    assert result["confirmed_count"] == 0
