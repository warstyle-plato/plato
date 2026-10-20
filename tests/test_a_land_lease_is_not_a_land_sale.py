"""Право аренды участка — аренда земли, а не продажа; аренда помещения — не ЗИК.

Формулировки взяты с живой выдачи «Торги · Москва» (прод 0.26.51). Рубрика
процедуры «Аренда и продажа земельных участков» общая — вид решает название
лота. Аренда — только когда её ПРАВО продаётся; «помещение сдано в аренду» —
обременение, а не аренда земли. Фильтр «участок от N га» читает признак
сервера «участок — предмет лота»: у помещения участок под домом — справка.

Запуск: python3 -m pytest tests/test_a_land_lease_is_not_a_land_sale.py -q
"""
import json
import socket
import urllib.parse
from datetime import date
from pathlib import Path

import pytest

from auction_search.adapters import torgi_gov
from auction_search.adapters.efrsb import _plain
from auction_search.adapters.torgi_gov import classify
from auction_search.classifier import classify_lot, land_in_deal
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PORT = 18849

LAND_PROCEDURE = {"code": "ZK", "name": "Аренда и продажа земельных участков · Электронный аукцион"}
LEASE_PROCEDURE = {"code": "PA", "name": "Аренда, безвозмездное пользование, доверительное управление имуществом"}


def card(name, description="", category="Земельные участки", bidd=LAND_PROCEDURE):
    return {"lotName": name, "lotDescription": description,
            "category": {"name": category}, "biddType": bidd}


def test_the_right_to_lease_a_parcel_is_a_land_lease():
    kind, _ = classify(card(
        "Право заключения договора аренды земельного участка по адресу: город Москва, "
        "вн.тер.г. муниципальный округ Ново-Переделкино"))
    assert kind is LotKind.LAND_LEASE


def test_a_parcel_sold_under_the_shared_procedure_stays_a_sale():
    kind, _ = classify(card(
        "Продажа земельного участка, Московская область, г.о. Наро-Фоминский, Бекасово",
        "Участок расположен рядом с земельным участком, находящимся в аренде"))
    assert kind is LotKind.LAND_SALE


def test_a_premises_lease_is_not_a_property_complex():
    for name in ("Аренда нежилого помещения площадью 54,3 кв. м",
                 "Право заключения договора аренды имущества"):
        kind, _ = classify(card(name, category="Нежилые помещения", bidd=LEASE_PROCEDURE))
        assert kind is LotKind.OTHER, name


def test_other_platforms_read_the_same_rule():
    procedure = "Аренда и продажа земельных участков"
    assert classify_lot("Продажа земельного участка", procedure) is LotKind.LAND_SALE
    assert classify_lot("Право на заключение договора аренды земельного участка", procedure) \
        is LotKind.LAND_LEASE
    assert classify_lot("Аренда нежилого помещения") is LotKind.OTHER


MAIP = ("Право заключения договора (соглашения) о реализации масштабного инвестиционного "
        "проекта по адресу: город Москва, вн.тер.г. муниципальный округ Внуково")


def test_a_large_investment_project_is_a_land_lease_not_a_sale():
    kind, _ = classify(card(MAIP))
    assert kind is LotKind.LAND_LEASE
    assert classify_lot(MAIP, "Аренда и продажа земельных участков") is LotKind.LAND_LEASE


def test_a_premises_let_to_a_tenant_is_not_a_land_lease():
    # ЕФРСБ: помещение продаётся, «сдано в аренду» — обременение.
    text = ("Помещение, назначение: нежилое, площадь 391,1 кв. м, этаж № 1, кадастровый номер: "
            "77:01:0001029:4076, адрес: РФ, Москва, вн. тер. г. муниципальный округ Басманный, "
            "Лялин переулок, д. 19, корп. 1, пом. 5/1. По сведениям, предоставленным Финансовым "
            "управляющим, помещение сдано в аренду сроком до 31.12.2026")
    assert classify_lot(text, "банкротство") is not LotKind.LAND_LEASE
    buildings = ("Недвижимое имущество: Здание, назначение: нежилое, пл. 29 750 кв.м., кад. "
                 "№77:05:0005004:6431 Вид права, доля в праве: собственность. Имеются ограничения "
                 "прав (запрещение регистрации, аренда); Здание, назначение: нежилое, пл. 48,4 кв.м.")
    assert classify_lot(buildings, "банкротство") is not LotKind.LAND_LEASE


def test_buildings_with_the_right_to_lease_their_parcel_are_a_property_complex():
    text = ("Недвижимое имущество в составе: 1) Нежилое помещение общей площадью 638,6 кв.м., "
            "кадастровый №77:01:0003035:2437, адрес: г.Москва, ул.Лобачика, д.2, стр.1, пом.1/1; "
            "2) Право аренды земельного участка, общей площадью 451 кв.м., кадастровый номер "
            "77:01:0003035:55. Основание аренды: Договор аренды земельного участка")
    assert classify_lot(text, "банкротство") is LotKind.PROPERTY_COMPLEX
    # Инжтехсвязь: двадцать зданий «Имеется аренда» и право аренды участка.
    raw = json.loads((FIXTURES / "efrsb" / "bidding_cbb43d13_lots.json").read_text(encoding="utf-8"))
    objects = list(_trade_objects(raw))
    assert objects and classify_lot(_plain(objects[0]), "банкротство") is LotKind.PROPERTY_COMPLEX


def test_the_parcel_is_the_subject_only_where_the_winner_gets_it():
    for title in ("нежилые помещения",
                  "Нежилое помещение, расположенное по адресу: г. Москва, ул. Спортивной Авиации, дом 3",
                  "- часть помещения XIII (комнаты № 1, 2, 4-10, 13, 14) площадью 160,1 кв. метра",
                  "Аукцион в электронной форме на право заключения договора аренды имущества"):
        assert land_in_deal(LotKind.PROPERTY_COMPLEX, title) is False, title
    for title in ("Нежилое здание пл. 595.8 кв.м. по адресу: г.Москва, ул.Авиамоторная, д.33",
                  "Недвижимое имущество в составе: 1) Нежилое помещение; 2) Право аренды земельного участка"):
        assert land_in_deal(LotKind.PROPERTY_COMPLEX, title) is True, title
    assert land_in_deal(LotKind.LAND_LEASE, MAIP) is True
    assert land_in_deal(LotKind.EQUITY_STAKE, "Пакет акций 50%") is False
    lot = AuctionLot(AuctionSource(SourceKind.TORGI_GOV, "https://torgi.gov.ru/lot/1", "1", "", "ГИС Торги"),
                     LotKind.PROPERTY_COMPLEX, "нежилые помещения", land_area_sqm=6142)
    assert lot.to_dict()["land_in_deal"] is False


def _trade_objects(value):
    if isinstance(value, dict):
        if "tradeObject" in value:
            yield value["tradeObject"]
        for item in value.values():
            yield from _trade_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _trade_objects(item)


class _Flaky(torgi_gov.TorgiGovAdapter):
    def __init__(self, failures: int):
        super().__init__(discovery_filters=(("земельные участки", "2", ""),))
        self.failures, self.urls = failures, []

    def _fetch_raw(self, url, *, deadline=None):
        self.urls.append(url)
        if self.failures:
            self.failures -= 1
            raise socket.timeout("timed out")
        page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["page"][0])
        return 200, "application/json", json.dumps({"content": [], "totalPages": 1, "totalElements": 0,
                                                    "page": page})


def test_a_timed_out_history_page_is_asked_once_more():
    once = _Flaky(1)
    once.discover_moscow_finished(date(2026, 7, 20), date(2026, 10, 20))
    assert len(once.urls) == 2 and not once.last_report["filters"][0]["reason"]
    twice = _Flaky(2)
    twice.discover_moscow_finished(date(2026, 7, 20), date(2026, 10, 20))
    assert len(twice.urls) == 2 and "timed out" in twice.last_report["filters"][0]["reason"]


# --- отрисованная страница ------------------------------------------------------

def _lot(url, title, *, land=None, kind="land_sale", **extra):
    return {"title": title, "address": "", "cadastral_numbers": [], "lot_kind": kind, "origin": "city",
            "land_area_sqm": land, "building_area_sqm": None, "current_price_rub": 10_000_000,
            "application_deadline": "", "status": "Приём заявок", "documents": [],
            "source": {"lot_url": url, "source_name": "ГИС Торги", "external_lot_id": url[-4:]},
            "screening": {"why_here": "земля"}, "quality": {"accepted": True}, "main_selection": True,
            **extra}


LIVE = [
    _lot("https://torgi.gov.ru/lot/BIG1", "Участок 0,6 га", land=6000, land_in_deal=True),
    _lot("https://torgi.gov.ru/lot/PRM1", "Право заключения договора аренды нежилых помещений 67,4 кв. м",
         land=5144, kind="property_complex", land_in_deal=False),
]
FINISHED = [_lot(f"https://torgi.gov.ru/lot/F{i:03d}", f"Участок {i}, торги прошли", land=500 + i * 80,
                 status="Состоялся", status_code="SUCCEED", land_in_deal=True) for i in range(21)]


@pytest.mark.timeout(240)
def test_in_a_real_browser_the_half_hectare_filter_hides_premises_and_names_small_finished(
        tmp_path, monkeypatch):
    from browser import chromium_or_skip, serve
    from fastapi import FastAPI
    from playwright.sync_api import sync_playwright

    chrome = chromium_or_skip()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from auction_search import api
    app = FastAPI()
    api.install(app)
    finished = {"lots": FINISHED, "count": 21, "cached": False,
                "window": {"since": "2026-07-20", "until": "2026-10-20", "months": 3},
                "coverage": [{"source": "ГИС Торги (torgi.gov.ru)", "kept": 21, "cards": 126,
                              "finished_available": True, "reason": "",
                              "filters": [{"filter": "земельные участки", "cards": 80, "total_elements": 8774,
                                           "stopped": "", "reason": "страница 8: <urlopen error timed out>"}]}]}
    read = """() => ({
      names: [...document.querySelectorAll('#sheetRows tr.sheetrow td.k-name')].map(td => td.textContent),
      area: document.getElementById('areaNote').innerText,
      finished: document.getElementById('finishedNote').innerText,
    })"""
    with serve(app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("**/auctions/discover*", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"lots": LIVE, "coverage": [], "quality": {}, "count": 2}, ensure_ascii=False)))
            page.route("**/auctions/finished*", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(finished, ensure_ascii=False)))
            page.goto(f"{base}/auctions", wait_until="domcontentloaded")
            page.click("#refresh")
            page.wait_for_function("document.querySelectorAll('#sheetRows tr.sheetrow').length === 2")
            page.click("#landHalfHa")
            page.wait_for_function("document.querySelectorAll('#sheetRows tr.sheetrow').length === 1")
            seen = page.evaluate(read)
            assert "Участок 0,6 га" in seen["names"][0]
            assert not any("помещений" in name for name in seen["names"]), "аренда помещения прошла фильтр участка"
            assert "участок не продаётся и не сдаётся в аренду (1)" in seen["area"], seen["area"]

            page.check("#showFinished")
            page.wait_for_function("document.getElementById('finishedNote').innerText.includes('найдено 21')")
            seen = page.evaluate(read)
            assert len(seen["names"]) == 1, "мелкие завершённые участки не должны пройти фильтр 0,5 га"
            assert "под выбранные фильтры подходит 0" in seen["finished"], seen["finished"]
            assert "у 21 площадь участка меньше 0,5 га" in seen["finished"], seen["finished"]
            assert "Они показаны" not in seen["finished"]
            assert "80 из 8774" in seen["finished"] and "не ответила вовремя" in seen["finished"]
            assert "крупные участки" in seen["finished"]

            # Фильтр снят — все 21 на экране, и плашка говорит «показаны».
            page.fill("#landMinHa", "")
            page.dispatch_event("#landMinHa", "input")
            page.wait_for_function("document.querySelectorAll('#sheetRows tr.sheetrow').length === 23")
            seen = page.evaluate(read)
            assert "найдено 21. Они показаны" in seen["finished"], seen["finished"]
            assert not errors, errors
        finally:
            browser.close()
