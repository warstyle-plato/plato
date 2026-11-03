from __future__ import annotations

from pathlib import Path

from market_search.service import MarketDiscoveryService
from market_search.ui import install


class FakeCore:
    PAGE = """
    <html><head></head><body>
      <input id="apartment_price_th" type="number" value="500">
      <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
      <div id="report" class="panel"></div>
    </body></html>
    """


def test_same_name_other_region_does_not_confirm_moscow_project(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    khabarovsk = {
        "title": "ЖК СВОЙ",
        "snippet": "Жилой комплекс СВОЙ, Хабаровск, Хабаровский край",
    }
    assert service._official_card_matches(
        "СВОЙ", None, khabarovsk, locality="Москва"
    ) is False

    moscow = {
        "title": "ЖК СВОЙ",
        "snippet": "Жилой комплекс СВОЙ, Москва, Можайский район",
    }
    assert service._official_card_matches(
        "СВОЙ", None, moscow, locality="Москва"
    ) is True


def test_strong_address_match_can_confirm_without_marketing_name(tmp_path: Path) -> None:
    service = MarketDiscoveryService(tmp_path)
    card = {
        "title": "Жилой дом",
        "snippet": "Москва, улица Мишина, дом 46",
    }
    assert service._official_card_matches(
        "Проект без маркетингового имени",
        "Москва, улица Мишина, 46",
        card,
        locality="Москва",
    ) is True


def test_market_ui_has_apply_to_model_and_hides_technical_search_links() -> None:
    core = FakeCore()
    install(core)
    assert "applyMarketPriceToModel" in core.PAGE
    assert "apartment_price_th" in core.PAGE
    assert "Применить " in core.PAGE
    assert "Источник поиска</a>" not in core.PAGE
    assert "Источник discovery:" not in core.PAGE
    assert "Официально · Наш.Дом.РФ" in core.PAGE
    assert "Корпусов/объектов в ЕИСЖС" in core.PAGE
