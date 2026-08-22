from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from auction_search.adapters.investmoscow import InvestMoscowDiscoveryAdapter
from auction_search.api import _discovery_adapters
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind


def _lot(url: str) -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(SourceKind.ROSELTORG, url, "1", "now"),
        lot_kind=LotKind.LAND_SALE,
        title="Продажа земельного участка",
        address="г. Москва",
        application_deadline=(datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(days=2)).isoformat(),
    )


def test_city_catalogue_extracts_only_official_tender_cards():
    html = """
    <a href="/tenders/tender/20009267?procedure_zakupki=sale">Земельный участок</a>
    <a href="https://investmoscow.ru/tenders/tendercard/?TenderId=18493038">КРТ</a>
    <a href="https://example.com/tenders/tender/1">Чужой сайт</a>
    <a href="/news/1">Новость</a>
    """

    urls = InvestMoscowDiscoveryAdapter._city_card_urls("https://investmoscow.ru/tenders/", html)

    assert urls == [
        "https://investmoscow.ru/tenders/tender/20009267?procedure_zakupki=sale",
        "https://investmoscow.ru/tenders/tendercard?TenderId=18493038",
    ]


def test_city_discovery_is_available_separately_and_in_all_sources():
    city = _discovery_adapters("investmoscow")
    all_sources = _discovery_adapters("all")

    assert len(city) == 1
    assert isinstance(city[0], InvestMoscowDiscoveryAdapter)
    assert any(isinstance(adapter, InvestMoscowDiscoveryAdapter) for adapter in all_sources)


def test_city_card_extracts_whitelisted_official_etp_links_only():
    html = """
    <a href="https://www.roseltorg.ru/procedure/2400000000001">Участвовать</a>
    <a href="https://utp.sberbank-ast.ru/AP/NBT/PurchaseView/1/0/0/0">ЭТП</a>
    <a href="https://aggregator.example/lot/1">Копия</a>
    """

    urls = InvestMoscowDiscoveryAdapter._official_etp_urls("https://investmoscow.ru/tenders/tender/1", html)

    assert urls == [
        "https://www.roseltorg.ru/procedure/2400000000001",
        "https://utp.sberbank-ast.ru/AP/NBT/PurchaseView/1/0/0/0",
    ]


def test_city_discovery_returns_only_verified_current_etp_lots(monkeypatch):
    adapter = InvestMoscowDiscoveryAdapter()
    monkeypatch.setattr(adapter, "_search_urls", lambda: ["https://investmoscow.ru/tenders/"])
    pages = {
        "https://investmoscow.ru/tenders/": '<a href="/tenders/tender/1">Лот</a>',
        "https://investmoscow.ru/tenders/tender/1": (
            '<a href="https://www.roseltorg.ru/procedure/official">ЭТП</a>'
        ),
    }
    monkeypatch.setattr(adapter, "_read_html", pages.__getitem__)

    class OfficialAdapter:
        def fetch_lot(self, url):
            return _lot(url)

    monkeypatch.setattr(adapter, "_adapter_for_etp", lambda _url: OfficialAdapter())

    lots = adapter.discover_moscow()

    assert len(lots) == 1
    assert lots[0].source.platform == SourceKind.ROSELTORG
    assert lots[0].raw["discovery_url"] == "https://investmoscow.ru/tenders/tender/1"
    assert adapter.last_report["verified_lots"] == 1


def test_city_discovery_reports_unsupported_etp_instead_of_inventing_facts(monkeypatch):
    adapter = InvestMoscowDiscoveryAdapter()
    monkeypatch.setattr(adapter, "_search_urls", lambda: ["https://investmoscow.ru/tenders/"])
    pages = {
        "https://investmoscow.ru/tenders/": '<a href="/tenders/tender/1">Лот</a>',
        "https://investmoscow.ru/tenders/tender/1": (
            '<a href="https://utp.sberbank-ast.ru/AP/NBT/PurchaseView/1/0/0/0">ЭТП</a>'
        ),
    }
    monkeypatch.setattr(adapter, "_read_html", pages.__getitem__)

    assert adapter.discover_moscow() == []
    assert adapter.last_report["unsupported_etp_hosts"] == ["utp.sberbank-ast.ru"]
    assert adapter.last_report["unresolved_city_cards"] == 1
