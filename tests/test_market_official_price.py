from __future__ import annotations

from pathlib import Path

from market_search.official_price import OfficialPriceEnricher
from market_search.service import MarketDiscoveryService


def test_official_domrf_label_price_is_parsed() -> None:
    values = OfficialPriceEnricher._extract_prices(
        "Верейская 41. Средняя цена за 1 м² — 585 706 ₽. Сдача III кв. 2026"
    )
    assert 585_706 in values


def test_official_domrf_thousand_format_is_parsed() -> None:
    values = OfficialPriceEnricher._extract_prices(
        "Средняя цена за 1 м²: 585,7 тыс. ₽"
    )
    assert 585_700 in values


def test_official_price_wins_over_conflicting_external_market(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    combined = service._combine_price_sources(
        {
            "available": True,
            "method": "official_domrf_average",
            "price_per_sqm": 585_706,
        },
        {
            "available": True,
            "method": "indexed_asking_prices",
            "price_per_sqm": 395_925,
            "min_price_per_sqm": 395_925,
            "max_price_per_sqm": 395_925,
        },
    )
    assert combined["available"] is True
    assert combined["basis"] == "official_domrf_average"
    assert combined["price_per_sqm"] == 585_706
    assert combined["asking_price_per_sqm"] == 395_925
    assert combined["asking_discrepancy_pct"] == 32.4
    assert combined["asking_conflict"] is True


def test_external_market_is_fallback_when_official_price_missing(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    combined = service._combine_price_sources(
        {"available": False, "method": "official_domrf_average"},
        {
            "available": True,
            "method": "indexed_asking_prices",
            "price_per_sqm": 598_500,
        },
    )
    assert combined["basis"] == "indexed_asking_prices"
    assert combined["price_per_sqm"] == 598_500
