"""Стратегия discovery и приоритет источников цены — контракт v6.

Файл продолжает прежний test_market_v5_strategy: проверки, пережившие ревизию,
перенесены, а те, что описывали удалённые модули (candidates_v5, service_v5,
service_v51, ui_v5), заменены на проверки их преемников. Регрессия по классам
найденных ошибок живёт отдельно, в test_market_forensic_v6.
"""

from __future__ import annotations

import json
from pathlib import Path

from market_search.candidates_v6 import extract_candidates
from market_search.recommendation import market_recommendation
from market_search.service_v6 import MarketDiscoveryService as ServiceV6
from market_search.ui_v6 import install
from market_search.yandex_search import SearchDoc


class FakeCore:
    PAGE = """
    <html><head></head><body>
      <input id="apartment_price_th" type="number" value="500">
      <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
      <div id="report" class="panel"></div>
    </body></html>
    """


def test_discovery_queries_cover_multiple_market_channels() -> None:
    queries = ServiceV6._discovery_queries(
        "Москва, Саввинская набережная, 25", "Москва", "Хамовники район"
    )
    joined = "\n".join(queries)
    assert queries[0].startswith("site:cian.ru")
    assert '"Хамовники"' in joined
    assert "site:realty.yandex.ru" in joined
    assert "site:domclick.ru" in joined
    assert "site:novostroy.ru/buildings" in joined
    assert "клубные дома" in joined
    assert "элитные новостройки" in joined
    assert "новостройки рядом" in joined
    assert len(queries) == len(set(queries)), "повторный запрос — лишний вызов Search API"


def test_extractor_keeps_branded_premium_projects_without_zhk_prefix() -> None:
    """Recall v5 сохранён: премиальные проекты часто не пишут «ЖК» вовсе."""
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
            url="https://www.cian.ru/zhiloy-kompleks-dom-xxii-4463213/",
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
    names = {item.canonical_name for item in extract_candidates(docs)}
    assert "Хамовники 12" in names
    assert "ДОМ XXII" in names
    assert "Клубный квартал Фрунзенский" in names


def test_extractor_rejects_listing_and_commercial_noise() -> None:
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
            url="https://example.ru/proekty/savvinsky",
            domain="example.ru",
            snippet="Офисы в аренду",
            rank=2,
        ),
    ]
    assert extract_candidates(docs) == []


def test_verified_asking_price_wins_over_lagging_official_average(tmp_path: Path) -> None:
    """Официальная средняя ЕИСЖС отстаёт от рынка и базой рекомендации не служит."""
    service = ServiceV6(tmp_path)
    asking = {
        "available": True,
        "verified": True,
        "basis": "verified_project_page_asking",
        "price_per_sqm": 601_000,
    }
    result = service._with_official_fallback(asking, entity=None, cards=[{"object_id": 1}], locality="Москва")
    assert result is asking
    assert result["basis"] == "verified_project_page_asking"


def test_official_average_is_used_only_as_a_matched_card_fallback(tmp_path: Path, monkeypatch) -> None:
    service = ServiceV6(tmp_path)

    class Entity:
        canonical_name = "Хамовники 12"

    monkeypatch.setattr(
        service.official_prices,
        "project_price",
        lambda name, locality, cards: {
            "available": True,
            "price_per_sqm": 218_245,
            "observation_count": 2,
            "min_price_per_sqm": 210_000,
            "max_price_per_sqm": 226_000,
        },
    )
    missing = {"available": False, "verified": False, "basis": "none"}

    assert service._with_official_fallback(missing, Entity(), [], "Москва") is missing

    result = service._with_official_fallback(missing, Entity(), [{"object_id": 2079406}], "Москва")
    assert result["available"] is True
    assert result["basis"] == "official_domrf_fallback"
    assert result["price_per_sqm"] == 218_245
    assert result["quality"] == "low"
    assert result["sources"] == ["Наш.Дом.РФ"]


def test_recommendation_does_not_require_domrf_confirmation() -> None:
    # Официальное подтверждение по-прежнему не условие. Условием стало другое —
    # доказанная привязка цены к проекту (`price_verified`), поэтому строки её
    # несут явно: отсутствующий ключ означает «не доказано», а не «доказано».
    def row(name, distance, confirmed, sources, price):
        return {
            "name": name,
            "within_radius": True,
            "geo_status": "resolved",
            "price_verified": True,
            "distance_km": distance,
            "confirmed": confirmed,
            "market_source_count": sources,
            "market_price": {"available": True, "price_per_sqm": price},
        }

    result = market_recommendation(
        [
            row("A", 0.5, False, 2, 1_000_000),
            row("B", 1.0, True, 2, 1_100_000),
            row("C", 1.5, False, 1, 1_200_000),
            row("outlier", 0.7, True, 1, 4_800_000),
        ]
    )
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


def test_ui_no_longer_treats_domrf_as_hard_gate() -> None:
    core = FakeCore()
    install(core)
    assert "Не подтверждён — в расчёт цены не идёт" not in core.PAGE
    assert "на попадание в выборку не влияет" in core.PAGE
    assert "market-v6-style" in core.PAGE
