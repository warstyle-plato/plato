"""Городская приватизация: стоящий лот входит в выборку, мелочь — нет, с причиной.

Владелец прислал лот Росэлторга 178fz30102600019 — продажу 100% доли ООО
«Фонвизина 8» за 596 млн ₽, — которого в выборке не было: раздел приватизации
мы не спрашивали, а вид «доля» и «Продажа доли» прежние шаги отсекали молча.
Решение (02.11.2026): собирать приватизацию, но только стоящие лоты — Москва и
МО, земля от 0,5 га, здание от 1 000 м², цена от 10 млн ₽, доли — по правилу
для долей; гаражи, машино-места и помещения — нет, и с причиной.

Все лоты здесь синтетические: номера, названия и цены выдуманы по образцу.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from auction_search import privatization, ui
from auction_search.adapters import torgi_gov
from auction_search.adapters.roseltorg import RoseltorgAdapter
from auction_search.catalogue_quality import catalogue_quality
from auction_search.models import AuctionLot, AuctionSource, LotKind, LotOrigin, SourceKind
from tests import page_blocks

FUTURE = (datetime.now() + timedelta(days=20)).strftime("%d.%m.%Y")
PAST = (datetime.now() - timedelta(days=3)).strftime("%d.%m.%Y")

# Меню площадки стоит на каждой странице, и в нём есть и «Организатор торгов»,
# и «178-ФЗ», и «Способ проведения» в разметке для поисковиков. Разбор по
# первому вхождению брал отсюда куски меню.
CHROME = (
    '<script type="application/ld+json">{"additionalProperty": [{"@type": "PropertyValue",'
    ' "name": "Способ проведения", "value": "Конкурс" }]}</script>'
    "<div>Вы хотите зарегистрироваться на площадке как Организатор торгов Получает "
    "предложения в качестве или в интересах Заказчика и(или) Продавца</div>"
    "<div>Торги по реализации имущества и торги в соответствии с 178-ФЗ</div>"
)


def _card(pid: str, title: str, *, price: str, until: str, status: str = "Прием заявок",
          extra: str = "") -> str:
    return (
        f"<html><head><title>{pid}</title></head><body>{CHROME}"
        f"<div>Процедура {pid}</div>"
        f"<div>Лот 1 {status} Имущественные торги (178-ФЗ) {title} Показать полностью</div>"
        f"<div>Начальная цена {price} ₽ Окончание приема заявок {until} в 15:00</div>"
        f"{extra}"
        "<div>Организатор торгов Название организации ДЕПАРТАМЕНТ ГОРОДА МОСКВЫ ПО "
        "КОНКУРЕНТНОЙ ПОЛИТИКЕ (ИНН 7704515009) Посмотреть объекты</div>"
        "<div>Дополнительная информация Способ проведения Конкурс Торговая секция "
        "Имущественные торги (178-ФЗ), 178fz.roseltorg.ru Подробнее</div>"
        "</body></html>"
    )


SHARE = "178fzTEST00001"
SHARE_TITLE = ("Продажа доли, составляющей 100% уставного капитала ООО «Тестовая 1», "
               "принадлежащей Тестовому фонду города")
CARDS = {
    SHARE: _card(SHARE, SHARE_TITLE, price="595 986 000,00", until=FUTURE),
    # Доля, у которой приём заявок закончился: лот существует, торгов нет.
    "178fzTEST00002": _card("178fzTEST00002", "Продажа 100 % доли в уставном капитале "
                            "ООО «Тестовая 2»", price="100 000 000,00", until=PAST,
                            status="Работа комиссии"),
    # Помещение: строка списка молчит («Показать еще 8 фото»), решает карточка.
    "21000005000000099001": _card("21000005000000099001",
                                  "Нежилое помещение площадью 2 300 кв.м в здании",
                                  price="120 000 000,00", until=FUTURE),
    # Участок МО от 0,5 га — стоящий.
    "21000030950000099002": _card(
        "21000030950000099002", "Земельный участок, 12 000 кв.м", price="45 000 000,00",
        until=FUTURE, extra="<div>Расположение Московская обл., г.о. Тестовый, д. Тестовая "
                            "Показать на карте</div>"),
}
LISTING = (
    "<html><body>"
    f'<a href="/procedure/{SHARE}/1">{SHARE_TITLE}</a>'
    '<a href="/procedure/178fzTEST00002/1">Продажа 100 % доли ООО «Тестовая 2»</a>'
    '<a href="/procedure/21000005000000099001/1">Показать еще 8 фото</a>'
    '<a href="/procedure/21000030950000099002/1">Земельный участок, 12 000 кв.м</a>'
    # Названы прямо в списке — карточку не открываем.
    '<a href="/procedure/21000005000000099003/1">Машино-место 13,6 кв.м</a>'
    '<a href="/procedure/21000005000000099004/1">Гараж, бокс № 7</a>'
    '<a href="/procedure/21000030950000099005/1">Земельный участок, 1 250 кв.м</a>'
    # Коммерческая секция площадки — не городская приватизация.
    '<a href="/procedure/COM01012600001/1">Земельный участок, 59 634 кв.м</a>'
    "</body></html>"
)


@pytest.fixture
def discovered(monkeypatch):
    opened: list[str] = []

    def fake_read(cls, url, timeout, **_kw):
        if "/procedure/" in url:
            pid = url.split("/procedure/", 1)[1].split("/", 1)[0]
            opened.append(pid)
            return CARDS[pid]
        if "page=" in url:
            return "<html></html>"
        if url == RoseltorgAdapter.PRIVATIZATION_LISTS[0][1]:
            return LISTING
        return "<html></html>"

    monkeypatch.setattr(RoseltorgAdapter, "_read", classmethod(fake_read))
    adapter = RoseltorgAdapter()
    lots = adapter.discover_moscow()
    return adapter, {lot.source.external_lot_id: lot for lot in lots}, opened


def test_a_city_share_like_the_owners_lot_enters_the_selection(discovered):
    adapter, lots, _opened = discovered
    lot = lots.get(f"{SHARE}/1")
    assert lot is not None, adapter.last_report
    assert lot.lot_kind is LotKind.EQUITY_STAKE
    assert lot.start_price_rub == 595_986_000
    # Москву называет организатор, а не слово «Московский» у продавца.
    assert lot.raw["privatization_region"].startswith("Москва (организатор")
    # Цену доли решает правило владельца для долей: 500 млн ₽ за 100%.
    assert catalogue_quality(lot)["accepted"] is True


def test_the_card_fields_are_read_by_their_label_not_the_menu(discovered):
    _adapter, lots, _opened = discovered
    lot = lots[f"{SHARE}/1"]
    assert lot.organizer == ("ДЕПАРТАМЕНТ ГОРОДА МОСКВЫ ПО КОНКУРЕНТНОЙ ПОЛИТИКЕ "
                             "(ИНН 7704515009)")
    assert lot.procedure_type == "Конкурс"
    assert lot.raw["trading_section_clean"].startswith("Имущественные торги (178-ФЗ)")


def test_a_worthy_oblast_parcel_is_taken(discovered):
    _adapter, lots, _opened = discovered
    lot = lots.get("21000030950000099002/1")
    assert lot is not None
    assert lot.land_area_sqm == 12_000
    assert lot.raw["privatization_region"].startswith("Московская область")


def test_garages_premises_and_closed_lots_are_dropped_with_a_reason(discovered):
    adapter, lots, opened = discovered
    assert set(lots) == {f"{SHARE}/1", "21000030950000099002/1"}
    report = adapter.last_report
    assert report["privatization_dropped"] == {
        privatization.REASON_CLOSED: 1,
        "отдельное помещение — не земля и не здание": 1,
    }
    assert report["privatization_listing_dropped"] == {
        "машино-место — не земля и не здание": 1,
        "гараж — не земля и не здание": 1,
        privatization.REASON_LAND_SMALL: 1,
    }
    # Названное в списке не читается: карточка — запрос в общий срок каталога.
    assert not {"21000005000000099003", "21000005000000099004",
                "21000030950000099005", "COM01012600001"} & set(opened)
    assert report["privatization_lists"][0]["not_178"] == 1


def test_the_share_on_a_second_page_after_an_empty_answer_is_still_found(monkeypatch):
    """Площадка отвечает через раз, а страницы считает с нуля.

    Лот владельца стоял на ВТОРОЙ странице тега «уставный капитал» (`page=1`),
    а первая на том же запросе пришла пустой (ядро, 02.11.2026). Обход,
    который кончал список на пустой странице или начинал вторую с `page=2`,
    его не видел.
    """
    tag_url = next(url for label, url in RoseltorgAdapter.PRIVATIZATION_LISTS
                   if "уставный капитал" in label)
    second = RoseltorgAdapter._page_from_zero(tag_url, 1)
    assert second.endswith("page=1")

    def fake_read(cls, url, timeout, **_kw):
        if "/procedure/" in url:
            return CARDS[SHARE]
        if url == second:
            return f'<html><a href="/procedure/{SHARE}/1">{SHARE_TITLE}</a></html>'
        return "<html></html>"

    monkeypatch.setattr(RoseltorgAdapter, "_read", classmethod(fake_read))
    adapter = RoseltorgAdapter()
    ids = [lot.source.external_lot_id for lot in adapter.discover_moscow()]
    assert ids == [f"{SHARE}/1"]
    row = next(row for row in adapter.last_report["privatization_lists"]
               if "уставный капитал" in row["name"])
    assert row["empty_pages"] == 2 and row["procedure_links"] == 1


def _lot(title: str, kind: LotKind, **fields) -> AuctionLot:
    base = dict(
        source=AuctionSource(platform=SourceKind.ROSELTORG,
                             lot_url="https://www.roseltorg.ru/procedure/178fzX/1",
                             external_lot_id="178fzX/1", fetched_at="2026-11-02T00:00:00Z",
                             source_name="Росэлторг"),
        lot_kind=kind, title=title, status="Прием заявок",
        application_deadline=f"{FUTURE} 15:00", start_price_rub=50_000_000.0,
        raw={"lot_region_code": "77"},
    )
    base.update(fields)
    return AuctionLot(**base)


@pytest.mark.parametrize("title,kind,fields,reason", [
    ("Земельный участок 4 999 кв.м", LotKind.LAND_SALE, {"land_area_sqm": 4_999.0},
     privatization.REASON_LAND_SMALL),
    ("Нежилое здание 999 кв.м", LotKind.PROPERTY_COMPLEX, {"building_area_sqm": 999.0},
     privatization.REASON_BUILDING_SMALL),
    ("Нежилое здание 1 500 кв.м", LotKind.PROPERTY_COMPLEX,
     {"building_area_sqm": 1_500.0, "start_price_rub": 9_999_999.0}, privatization.REASON_CHEAP),
    ("Земельный участок 6 000 кв.м", LotKind.LAND_SALE,
     {"land_area_sqm": 6_000.0, "raw": {"lot_region_code": "65"}}, privatization.REASON_REGION),
    ("Земельный участок 6 000 кв.м", LotKind.LAND_SALE,
     {"land_area_sqm": 6_000.0, "raw": {}}, privatization.REASON_REGION_UNKNOWN),
    ("Земельный участок 6 000 кв.м", LotKind.LAND_SALE,
     {"land_area_sqm": 6_000.0, "application_deadline": f"{PAST} 15:00"},
     privatization.REASON_CLOSED),
    ("Машино-место № 12 в здании", LotKind.PROPERTY_COMPLEX, {"building_area_sqm": 5_000.0},
     "машино-место — не земля и не здание"),
])
def test_each_threshold_drops_the_lot_just_below_it(title, kind, fields, reason):
    assert privatization.verdict(_lot(title, kind, **fields)) == reason


@pytest.mark.parametrize("title,kind,fields", [
    ("Земельный участок 5 000 кв.м", LotKind.LAND_SALE,
     {"land_area_sqm": 5_000.0, "start_price_rub": 10_000_000.0}),
    ("Нежилое здание 1 000 кв.м", LotKind.PROPERTY_COMPLEX, {"building_area_sqm": 1_000.0}),
    # Небольшое здание на участке от 0,5 га — тоже площадка.
    ("Нежилое здание 600 кв.м", LotKind.PROPERTY_COMPLEX,
     {"building_area_sqm": 600.0, "land_area_sqm": 7_000.0}),
    ("Земельный участок 9 000 кв.м", LotKind.LAND_SALE,
     {"land_area_sqm": 9_000.0, "raw": {"lot_region_code": "50"}}),
])
def test_a_lot_exactly_at_the_threshold_passes(title, kind, fields):
    assert privatization.verdict(_lot(title, kind, **fields)) == ""


def test_the_178_in_the_platform_menu_does_not_make_a_lot_privatization():
    lot = _lot("Продажа оборудования", LotKind.OTHER,
               source=AuctionSource(platform=SourceKind.ROSELTORG,
                                    lot_url="https://www.roseltorg.ru/procedure/COM1/1",
                                    external_lot_id="COM1/1", fetched_at="x",
                                    source_name="Росэлторг"),
               raw={"trading_section": "Торги в соответствии с 178-ФЗ меню площадки"})
    assert privatization.is_privatization(lot) is False


def _torgi_card(**overrides) -> dict:
    card = {
        "id": "21000005000000099100_1", "lotName": "Нежилое здание", "subjectRFCode": "77",
        "biddType": {"code": "178FZ", "name": "Продажа (приватизация) государственного и "
                                              "муниципального имущества"},
        "biddForm": {"code": "EA", "name": "Электронный аукцион"},
        "category": {"name": "Здания"}, "priceMin": 249_090_000,
        "lotStatus": "APPLICATIONS_SUBMISSION",
        "biddEndTime": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%dT15:00:00"),
        "characteristics": [{"code": "totalAreaRealty", "characteristicValue": 1676.1}],
    }
    card.update(overrides)
    return card


def test_gis_torgi_keeps_a_big_building_and_drops_a_parking_space(monkeypatch):
    big = _torgi_card()
    parking = _torgi_card(id="21000005000000099101_1",
                          lotName="Машино-место: РФ, г.Москва, пр-т Тестовый",
                          priceMin=96_000,
                          characteristics=[{"code": "totalAreaRealty",
                                            "characteristicValue": 13.6}])
    small_land = _torgi_card(
        id="21000005000000099102_1", lotName="Продажа земельного участка, г. Москва",
        biddType={"code": "ZK", "name": "Аренда и продажа земельных участков"},
        category={"name": "Земельные участки"}, priceMin=1_812_880,
        characteristics=[{"code": "totalAreaRealty", "characteristicValue": 482}])
    # Договор о масштабном инвестпроекте по цене 1 ₽ — не продажа участка, и
    # правило приватизации его не трогает.
    mip = _torgi_card(
        id="21000005000000099103_1",
        lotName="Право заключения договора (соглашения) о реализации масштабного "
                "инвестиционного проекта, аренда земельного участка",
        biddType={"code": "OTHER", "name": "Иной вид торгов"},
        category={"name": "Земельные участки"}, priceMin=1,
        characteristics=[{"code": "totalAreaRealty", "characteristicValue": 9244}])
    lots = [torgi_gov.to_lot(card, "2026-11-02T00:00:00Z")
            for card in (big, parking, small_land, mip)]

    def fake_sweep(self, statuses, **_kw):
        return list(lots), {"pages": 1, "cards": 4, "kept": 4, "reason": ""}

    monkeypatch.setattr(torgi_gov.TorgiGovAdapter, "_sweep", fake_sweep)
    adapter = torgi_gov.TorgiGovAdapter()
    kept = {lot.source.external_lot_id for lot in adapter.discover_moscow()}
    assert kept == {"21000005000000099100_1", "21000005000000099103_1"}
    report = adapter.last_report
    assert report["privatization_seen"] == 3
    assert report["privatization_dropped"] == {
        "машино-место — не земля и не здание": 1,
        privatization.REASON_LAND_SMALL: 1,
    }
    assert lots[3].lot_kind is LotKind.LAND_LEASE and lots[3].origin is not LotOrigin.BANKRUPTCY


def test_the_coverage_line_names_the_privatization_reasons_in_plain_words():
    row = {"source": "ГИС Торги", "kept": 2, "privatization_seen": 4, "privatization_kept": 1,
           "privatization_dropped": {"машино-место — не земля и не здание": 3}}
    prelude = "const ROW=%s;\n" % json.dumps(row, ensure_ascii=False)
    out, _ = page_blocks.run(prelude, "console.log(coverageLine(ROW).said);",
                             page=ui.auctions_page())
    assert "приватизация и продажа городской земли: в выборке 1 из 4" in out
    assert "не взято, потому что машино-место — не земля и не здание: 3" in out
