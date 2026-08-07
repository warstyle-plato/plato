from __future__ import annotations

import json
from pathlib import Path

from market_search.candidates_v5 import extract_project_candidates_v5
from market_search.recommendation import market_recommendation
from market_search.service_v5 import MarketDiscoveryService
from market_search.ui_v5 import install
from market_search.yandex_search import SearchDoc


class FakeCore:
    PAGE = """
    <html><head></head><body>
      <input id="apartment_price_th" type="number" value="500">
      <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
      <div id="report" class="panel"></div>
    </body></html>
    """


def test_v5_queries_cover_multiple_market_channels() -> None:
    queries = MarketDiscoveryService._discovery_queries(
        "Москва, Саввинская набережная, 25",
        "Москва",
        "Хамовники район",
    )
    joined = "\n".join(queries)
    assert "site:cian.ru" in joined
    assert "site:domclick.ru" in joined
    assert "site:realty.yandex.ru" in joined
    assert "клубный дом" in joined
    assert "элитные новостройки" in joined


def test_v5_extracts_branded_premium_projects_without_zhk_prefix() -> None:
    docs = [
        SearchDoc(
            title="Хамовники 12 — квартиры в готовом клубном доме",
            url="https://realty.yandex.ru/moskva_i_moskovskaya_oblast/kupit/novostrojka/hamovniki-12-3186893/",
            domain="realty.yandex.ru",
            snippet="Новостройка в Хамовниках. Квартиры от застройщика.",
            rank=1,
        ),
        SearchDoc(
            title="ДОМ XXII — квартиры от застройщика",
            url="https://www.cian.ru/kupit-kvartiru-zhiloy-kompleks-dom-xxii-4463213/",
            domain="cian.ru",
            snippet="Строящийся элитный жилой дом на Погодинской улице.",
            rank=2,
        ),
        SearchDoc(
            title="Клубный квартал Фрунзенский — цены и планировки",
            url="https://zhk-frunzenskaya-naberezhnaya-i.cian.ru/",
            domain="zhk-frunzenskaya-naberezhnaya-i.cian.ru",
            snippet="Квартиры в продаже от застройщика Sminex.",
            rank=3,
        ),
    ]
    candidates = extract_project_candidates_v5(docs)
    names = {item["name"] for item in candidates}
    assert "Хамовники 12" in names
    assert "ДОМ XXII" in names
    assert "Клубный квартал Фрунзенский" in names


def test_v5_extractor_rejects_listing_and_commercial_noise() -> None:
    docs = [
        SearchDoc(
            title="Купить квартиру 58 м² в Хамовниках",
            url="https://realty.yandex.ru/offer/123/",
            domain="realty.yandex.ru",
            snippet="Вторичный рынок",
            rank=1,
        ),
        SearchDoc(
            title="Бизнес-центр Savvinsky",
            url="https://example.ru/project/savvinsky",
            domain="example.ru",
            snippet="Офисы в аренду",
            rank=2,
        ),
    ]
    assert extract_project_candidates_v5(docs) == []


def test_recommendation_does_not_require_domrf_confirmation() -> None:
    projects = [
        {
            "name": "A",
            "within_radius": True,
            "distance_km": 0.5,
            "confirmed": False,
            "market_source_count": 2,
            "market_price": {"available": True, "price_per_sqm": 1_000_000},
        },
        {
            "name": "B",
            "within_radius": True,
            "distance_km": 1.0,
            "confirmed": True,
            "market_source_count": 2,
            "market_price": {"available": True, "price_per_sqm": 1_100_000},
        },
        {
            "name": "C",
            "within_radius": True,
            "distance_km": 1.5,
            "confirmed": False,
            "market_source_count": 1,
            "market_price": {"available": True, "price_per_sqm": 1_200_000},
        },
        {
            "name": "outlier",
            "within_radius": True,
            "distance_km": 0.7,
            "confirmed": True,
            "market_source_count": 1,
            "market_price": {"available": True, "price_per_sqm": 4_800_000},
        },
    ]
    result = market_recommendation(projects)
    assert result is not None
    assert result["analogue_count"] == 3
    assert "A" in result["projects"]
    assert result["price_per_sqm"] < 1_300_000


def test_savvinskaya_golden_dataset_has_required_projects() -> None:
    path = Path(__file__).parent / "fixtures" / "market_golden_savvinskaya25.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {item["name"] for item in data["must_find"]}
    assert "Хамовники 12" in names
    assert "Саввинская 27" in names
    assert "ДОМ XXII" in names
    assert "Клубный квартал Фрунзенский" in names
    assert data["acceptance"]["minimum_recall_must_find"] >= 0.8
    assert data["acceptance"]["runtime_must_not_read_fixture"] is True


def test_v5_ui_no_longer_treats_domrf_as_hard_gate() -> None:
    core = FakeCore()
    install(core)
    assert "отсутствие проиндексированной карточки больше не исключает" in core.PAGE
    assert "Не подтверждён — в расчёт цены не идёт" not in core.PAGE
    assert "Карточка Наш.Дом.РФ не найдена — рыночная цена учитывается" in core.PAGE
    assert "market-v5-style" in core.PAGE
