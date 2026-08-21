from datetime import date
from urllib.parse import parse_qs, urlparse

from auction_search.adapters.roseltorg import RoseltorgAdapter
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind


def _source():
    return AuctionSource(
        platform=SourceKind.ROSELTORG,
        lot_url="https://www.roseltorg.ru/procedure/test/1",
        external_lot_id="test/1",
        fetched_at="2026-08-21T18:00:00Z",
        source_name="Росэлторг",
    )


def test_public_discovery_uses_official_tags_parameter():
    url = RoseltorgAdapter._discovery_url("земельный участок")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.hostname == "www.roseltorg.ru"
    assert parsed.path == "/procedures/search"
    assert query["tags[]"] == ["земельный участок"]


def test_public_discovery_has_separate_krt_tag():
    assert "комплексное развитие" in RoseltorgAdapter.DISCOVERY_TAGS
    assert "земельный участок" in RoseltorgAdapter.DISCOVERY_TAGS


def test_search_parser_keeps_only_official_procedure_links():
    links = [
        ("/procedure/24000035200000000011", "КРТ Москва"),
        ("/procedure/24000035200000000011/1", "Лот 1"),
        ("https://www.roseltorg.ru/procedure/22000005070000000483", "земля"),
        ("https://example.com/procedure/1", "чужой сайт"),
        ("/procedures/search?tags%5B%5D=x", "поиск"),
    ]
    urls = RoseltorgAdapter._procedure_urls(RoseltorgAdapter.SEARCH_URL, links)
    assert "https://www.roseltorg.ru/procedure/24000035200000000011" in urls
    assert "https://www.roseltorg.ru/procedure/24000035200000000011/1" in urls
    assert "https://www.roseltorg.ru/procedure/22000005070000000483" in urls
    assert all(urlparse(url).hostname == "www.roseltorg.ru" for url in urls)


def test_moscow_detection_uses_lot_region_not_platform_footer():
    sakhalin = AuctionLot(
        source=_source(),
        lot_kind=LotKind.LAND_LEASE,
        title="Земельный участок с кадастровым номером 65:25:0000004:545",
        raw={
            "lot_region_code": "65",
            # This reproduces the dangerous footer fact that appears on every page.
            "page_text": "65. Сахалинская область ... Москва, ул Кожевническая 14, стр. 5",
        },
    )
    assert RoseltorgAdapter._confirmed_moscow(sakhalin) is False

    moscow = AuctionLot(
        source=_source(),
        lot_kind=LotKind.KRT,
        title="Комплексное развитие территории города Москвы",
        raw={"lot_region_code": "77", "page_text": "Москва, ул Кожевническая 14, стр. 5"},
    )
    assert RoseltorgAdapter._confirmed_moscow(moscow) is True


def test_region_code_is_taken_from_lot_block():
    text = (
        "Процедура 123 Организатор торгов ... "
        "Лот 1 Прием заявок Земельный участок Теги бета земельный участок "
        "65. Сахалинская область 1 200 000,00 ₽ Обеспечение заявки 100 000 ₽ "
        "... footer Москва, ул Кожевническая 14"
    )
    assert RoseltorgAdapter._lot_region_code(text, "1") == "65"


def test_status_is_taken_from_lot_block_not_generic_lifecycle_footer():
    active = (
        "Лот 1 Прием заявок Земельный участок Теги бета 77. г. Москва 100 ₽ "
        "Этапы процедуры Публикация извещения Прием заявок Работа комиссии Процедура завершена"
    )
    archived = (
        "Лот 1 Заключение договора КРТ Теги бета 77. г. Москва 0 ₽ "
        "Этапы процедуры Публикация извещения Прием заявок Работа комиссии Процедура завершена"
    )
    assert RoseltorgAdapter._status(active, "1") == "Прием заявок"
    assert RoseltorgAdapter._status(archived, "1") == "Заключение договора"
    assert RoseltorgAdapter._is_actionable_status(RoseltorgAdapter._status(active, "1")) is True
    assert RoseltorgAdapter._is_actionable_status(RoseltorgAdapter._status(archived, "1")) is False


def test_krt_public_card_shape_classifies_from_method_and_title():
    title = "Комплексное развитие территории нежилой застройки города Москвы"
    method = "Конкурс (комплексное развитие территории)"
    from auction_search.classifier import classify_lot

    assert classify_lot(title, method, []) == LotKind.KRT


def test_roseltorg_publication_date_supports_two_digit_year():
    published = RoseltorgAdapter._published_at("Публикация извещения | 30.04.25 23:59:00 (МСК)")
    assert published is not None
    assert published.date() == date(2025, 4, 30)
    assert published.utcoffset().total_seconds() == 3 * 60 * 60


def test_roseltorg_history_requires_explicit_official_cards(monkeypatch):
    adapter = RoseltorgAdapter()
    calls = []

    def fetch(url):
        calls.append(url)
        return AuctionLot(
            source=AuctionSource(SourceKind.ROSELTORG, url, "known/1", "now"),
            lot_kind=LotKind.KRT,
            title="КРТ, город Москва",
            raw={
                "lot_region_code": "77",
                "page_text": "Публикация извещения | 15.05.26 12:00:00 (МСК)",
            },
        )

    monkeypatch.setattr(adapter, "fetch_lot", fetch)
    assert adapter.discover_moscow_history(date(2026, 2, 21), date(2026, 8, 21)) == []
    lots = adapter.discover_moscow_history(
        date(2026, 2, 21),
        date(2026, 8, 21),
        candidate_urls=("https://www.roseltorg.ru/procedure/known", "https://example.com/procedure/no"),
    )
    assert len(lots) == 1
    assert calls == ["https://www.roseltorg.ru/procedure/known"]
    assert lots[0].raw["discovery_mode"] == "history"
