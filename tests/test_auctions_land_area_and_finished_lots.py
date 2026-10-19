"""Торги: фильтр «участок от N га» и завершённые торги за три месяца.

Владелец: «Можно ли посмотреть в секции Торги отдельный фильтр для ЗУ от 0,5 га
в Москве и найти даже завершившиеся торги за последние 3 месяца от даты?»

Фильтру нужна площадь УЧАСТКА, а ГИС Торги клали «Общую площадь» в площадь
здания даже у лота рубрики «Земельные участки» — фильтр по участку ничего бы
не увидел. Лот без площади участка не выкидывается: отсутствие числа — не
ноль. Завершённые торги берутся отдельным запросом с теми же проверками
Москвы, а площадка, которая так не умеет, говорит это сама.

Запуск: python3 -m pytest tests/test_auctions_land_area_and_finished_lots.py -q
"""

from __future__ import annotations

import copy
import json
import sys
import urllib.parse
from datetime import date
from pathlib import Path

import pytest

from browser import chromium_or_skip, serve

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters import torgi_gov  # noqa: E402
from auction_search.models import LotKind  # noqa: E402

PORT = 18831
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "torgi_gov_lotcard.json"


def _card() -> dict:
    """Настоящая карточка ГИС Торгов (здание, живой ответ 24.08.2026)."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _land_card(value: str = "5200", **extra) -> dict:
    """Та же настоящая карточка, переведённая в рубрику «Земельные участки».

    Живого ответа по земле из песочницы не получить (torgi.gov.ru отвечает
    сбросом соединения), поэтому меняется только рубрика и предмет — оболочка,
    коды и типы строк остаются настоящими.
    """
    card = _card()
    card["category"] = {"code": "2", "name": "Земельные участки"}
    card["lotName"] = "Земельный участок, г. Москва"
    card["subjectRFCode"] = "77"
    card["characteristics"] = [
        {**item, "characteristicValue": value} if item["code"] == "totalAreaRealty" else item
        for item in card["characteristics"] if item["code"] in ("totalAreaRealty", "cadastralNumberRealty")
    ]
    card.update(extra)
    return card


# --- площадь участка и здания -------------------------------------------------

def test_the_real_building_card_keeps_its_area_as_building():
    lot = torgi_gov.to_lot(_card(), "t")
    assert lot.building_area_sqm == 86.3
    assert lot.land_area_sqm is None, "метры здания — не метры участка"
    assert lot.provenance["building_area_sqm"].source_section == "characteristics:totalAreaRealty"


def test_a_land_lot_puts_its_area_into_the_land_field():
    lot = torgi_gov.to_lot(_land_card("5200"), "t")
    assert lot.lot_kind is LotKind.LAND_SALE
    assert lot.land_area_sqm == 5200, "у лота рубрики «Земельные участки» предмет — участок"
    assert lot.building_area_sqm is None
    assert lot.provenance["land_area_sqm"].raw_value == "5200"


def test_a_separate_land_row_and_its_unit_are_read_by_code():
    card = _card()
    card["characteristics"].append({"code": "SquareZU", "name": "Площадь земельного участка",
                                    "characteristicValue": "0,75",
                                    "unit": {"code": "059", "name": "Гектар"}})
    lot = torgi_gov.to_lot(card, "t")
    assert lot.land_area_sqm == 7500
    assert lot.building_area_sqm == 86.3, "здание остаётся зданием"


def test_several_parcels_of_one_lot_add_up_and_one_parcel_is_not_counted_twice():
    card = _land_card("4000")
    card["characteristics"] += [
        {"code": "SquareZU", "name": "Площадь земельного участка", "characteristicValue": "3000",
         "unit": {"code": "055"}},
        {"code": "SquareZU", "name": "Площадь земельного участка", "characteristicValue": "2500",
         "unit": {"code": "055"}},
    ]
    lot = torgi_gov.to_lot(card, "t")
    assert lot.land_area_sqm == 5500, "два участка лота — сумма; «Общая площадь» о них же не прибавляется"
    assert lot.provenance["land_area_sqm"].source_section == "characteristics:SquareZU ×2"


def test_an_unknown_unit_leaves_the_area_empty_instead_of_guessing():
    card = _land_card("12")
    card["characteristics"][0]["unit"] = {"code": "999", "name": "сотка"}
    assert torgi_gov.to_lot(card, "t").land_area_sqm is None


def test_the_description_gives_land_metres_only_to_a_land_lot():
    text = "Земельный участок площадью участка 6 500 кв. м, вид разрешённого использования…"
    card = _land_card(lotDescription=text)
    card["characteristics"] = []
    lot = torgi_gov.to_lot(card, "t")
    assert lot.land_area_sqm == 6500
    assert lot.provenance["land_area_sqm"].source_section == "lotDescription"
    building = _card()
    building["lotDescription"] = text
    assert torgi_gov.to_lot(building, "t").land_area_sqm is None, \
        "у здания число из прозы не становится площадью участка"


# --- завершённые торги ГИС Торгов --------------------------------------------

def _finished(lot_id: str, status: str, end: str | None, published: str = "2026-09-01T10:00:00Z",
              **extra) -> dict:
    card = _land_card("6000", id=lot_id, lotStatus=status,
                      noticeFirstVersionPublicationDate=published, **extra)
    card.pop("biddEndTime", None)
    if end:
        card["biddEndTime"] = end
    return card


class _Pages(torgi_gov.TorgiGovAdapter):
    def __init__(self, pages: list[list[dict]]):
        super().__init__(discovery_filters=(("земельные участки", "2", ""),))
        self.pages, self.urls = pages, []

    def _fetch_raw(self, url, *, deadline=None):
        self.urls.append(url)
        page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["page"][0])
        content = self.pages[page] if page < len(self.pages) else []
        return 200, "application/json", json.dumps(
            {"content": content, "totalPages": len(self.pages), "totalElements": 99})


def test_finished_lots_are_asked_by_finished_statuses_inside_the_window():
    adapter = _Pages([[
        _finished("A1", "SUCCEED", "2026-09-10T12:00:00Z", priceFin=91_000_000),
        _finished("A2", "FAILED", "2026-08-01T12:00:00Z"),
        _finished("OLD", "CANCELED", "2026-05-01T12:00:00Z"),
        _finished("NODATE", "SUCCEED", None),
        _finished("LIVE", "PUBLISHED", "2026-09-10T12:00:00Z"),
        {**_finished("ELSE", "SUCCEED", "2026-09-10T12:00:00Z"), "subjectRFCode": "50"},
    ]])
    lots = adapter.discover_moscow_finished(date(2026, 7, 19), date(2026, 10, 19))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(adapter.urls[0]).query)
    assert sorted(query["lotStatus"]) == sorted(torgi_gov.FINISHED_LOT_STATUSES)
    assert query["dynSubjRF"] == ["78"]
    got = {lot.source.external_lot_id: lot for lot in lots}
    assert set(got) == {"A1", "A2"}, "вне окна, без даты, живой и чужой регион не проходят"
    assert got["A1"].status == "Состоялся" and got["A1"].status_code == "SUCCEED"
    assert got["A1"].result_price_rub == 91_000_000
    assert got["A2"].status == "Не состоялся" and got["A2"].result_price_rub is None
    report = adapter.last_report
    assert report["undated"] == 1 and "без даты" in report["reason"]
    assert report["outside_window_before"] == 1 and report["outside_window_after"] == 0
    assert report["window"]["since"] == "2026-07-19"


def test_the_history_stops_at_notices_too_old_for_the_window():
    old = "2025-12-01T10:00:00Z"
    adapter = _Pages([[_finished(f"P{i}", "SUCCEED", "2026-01-10T00:00:00Z", published=old)]
                      for i in range(5)])
    adapter.discover_moscow_finished(date(2026, 7, 19), date(2026, 10, 19))
    assert len(adapter.urls) == 1, "страницы старше окна с запасом не листаются"


def test_land_history_reads_deeper_than_the_other_filters_and_says_where_it_stopped():
    pages = [[_finished(f"P{page}x{i}", "SUCCEED", "2026-09-10T12:00:00Z", published="2026-09-01T10:00:00Z")
              for i in range(10)] for page in range(torgi_gov.HISTORY_MAX_PAGES_BY_FILTER["земельные участки"] + 5)]
    land = _Pages(pages)
    land.discovery_filters = (("земельные участки", "2", ""), ("здания", "7", "здание"))
    land.discover_moscow_finished(date(2026, 7, 19), date(2026, 10, 19))
    by_filter = {row["filter"]: row for row in land.last_report["filters"]}
    assert by_filter["земельные участки"]["pages"] == torgi_gov.HISTORY_MAX_PAGES_BY_FILTER["земельные участки"]
    assert by_filter["здания"]["pages"] == torgi_gov.HISTORY_MAX_PAGES_PER_FILTER
    assert "предел" in by_filter["земельные участки"]["stopped"]


def test_the_probe_asks_finished_statuses_and_extra_date_params_without_overriding_its_own():
    adapter = _Pages([[_finished("A1", "SUCCEED", "2026-09-10T12:00:00Z")]])
    seen = adapter.probe(0, statuses=torgi_gov.FINISHED_LOT_STATUSES, size=100,
                         sort="biddEndTime,desc", extra="biddEndFrom=2026-07-19&page=7")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert sorted(query["lotStatus"]) == sorted(torgi_gov.FINISHED_LOT_STATUSES)
    assert query["biddEndFrom"] == ["2026-07-19"]
    assert query["page"] == ["0"], "добавочный параметр не подменяет свой"
    assert query["size"] == ["100"] and query["sort"] == ["biddEndTime,desc"]
    assert seen["dates_seen"][0]["lotStatus"] == "SUCCEED"


def test_the_selection_funnel_of_the_history_is_reported():
    from auction_search.service import AuctionSearchService

    torgi = _Pages([[_finished("A1", "SUCCEED", "2026-09-10T12:00:00Z")]])
    service = AuctionSearchService([torgi])
    shown = service.discover_moscow_finished(date(2026, 7, 19), date(2026, 10, 19), budget_seconds=5)
    report = service.last_quality_report
    assert report["seen"] == 1, "сколько отдала площадка — до отбора"
    assert report["accepted"] == len(shown)


def test_live_discovery_still_asks_only_live_statuses():
    adapter = _Pages([[_land_card(id="L1", lotStatus="PUBLISHED")]])
    adapter.discover_moscow()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(adapter.urls[0]).query)
    assert sorted(query["lotStatus"]) == sorted(torgi_gov.ACTIVE_LOT_STATUSES)


def test_a_platform_without_history_says_so_in_its_coverage_row():
    from auction_search.adapters.roseltorg import RoseltorgAdapter
    from auction_search.service import AuctionSearchService

    other = RoseltorgAdapter()
    torgi = _Pages([[_finished("A1", "SUCCEED", "2026-09-10T12:00:00Z")]])
    service = AuctionSearchService([torgi, other])
    lots = service.discover_moscow_finished(date(2026, 7, 19), date(2026, 10, 19),
                                            include_noise=True, budget_seconds=5)
    assert [lot.source.external_lot_id for lot in lots] == ["A1"]
    assert other.last_report["finished_available"] is False
    assert "недоступны" in other.last_report["reason"]
    assert torgi.last_report["finished_available"] is True


# --- маршрут ------------------------------------------------------------------

def _app(tmp_path, monkeypatch, calls: list):
    from fastapi import FastAPI

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from auction_search import api

    def adapters(source):
        calls.append(source)
        return [_Pages([[_finished("A1", "SUCCEED", "2026-09-10T12:00:00Z")]])]

    monkeypatch.setattr(api, "_discovery_adapters", adapters)
    app = FastAPI()
    api.install(app)
    return app


def test_the_route_answers_the_window_and_keeps_the_answer_on_disk(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    calls: list = []
    client = TestClient(_app(tmp_path, monkeypatch, calls))
    first = client.get("/auctions/finished", params={"as_of": "2026-10-19", "include_noise": "true"}).json()
    assert first["window"] == {"since": "2026-07-19", "until": "2026-10-19", "months": 3}
    assert [lot["source"]["external_lot_id"] for lot in first["lots"]] == ["A1"]
    assert first["lots"][0]["finished"] is True and first["lots"][0]["land_area_sqm"] == 6000
    assert first["cached"] is False
    assert first["quality"]["seen"] == 1, "воронка допуска в ответе истории"
    second = client.get("/auctions/finished", params={"as_of": "2026-10-19", "include_noise": "true"}).json()
    assert second["cached"] is True and len(calls) == 1, "второй запрос читает диск, а не площадку"
    assert client.get("/auctions/finished", params={"as_of": "19.10.2026"}).status_code == 422


def test_a_cache_written_by_another_release_is_not_served(tmp_path, monkeypatch):
    """Прод, 19.10.2026: после выкатки #754 три часа отдавался ответ старого кода.

    Запись без версии (так писал прежний код) и запись другой версии выпуска
    не отдаются — ответ собирается заново; своя запись читается с диска.
    """
    import sys
    import time
    import types

    from fastapi.testclient import TestClient

    core = types.ModuleType("developaid_core")
    core.VERSION = "9.9.1"
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    calls: list = []
    client = TestClient(_app(tmp_path, monkeypatch, calls))
    params = {"as_of": "2026-10-19", "include_noise": "true"}
    path = tmp_path / "market" / "auctions" / "finished_all_2026-10-19_3m_1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = {"lots": [], "count": 0, "window": {}, "coverage": []}
    path.write_text(json.dumps({"saved_at": time.time(), "complete": True, "payload": stale}),
                    encoding="utf-8")
    first = client.get("/auctions/finished", params=params).json()
    assert first["cached"] is False and len(calls) == 1, "запись без версии не отдаётся"
    assert first["count"] == 1 and "quality" in first
    assert client.get("/auctions/finished", params=params).json()["cached"] is True
    core.VERSION = "9.9.2"
    assert client.get("/auctions/finished", params=params).json()["cached"] is False, \
        "новый выпуск собирает ответ заново"
    assert len(calls) == 2


# --- отрисованная страница ------------------------------------------------------

def _lot(url: str, title: str, *, land=None, building=None, **extra) -> dict:
    return {
        "title": title, "address": "", "cadastral_numbers": [], "lot_kind": "land_sale",
        "origin": "city", "land_area_sqm": land, "building_area_sqm": building,
        "current_price_rub": 10_000_000, "application_deadline": "", "status": "Приём заявок",
        "documents": [], "source": {"lot_url": url, "source_name": "ГИС Торги", "external_lot_id": url[-4:]},
        "screening": {"why_here": "земля"}, "quality": {"accepted": True}, "main_selection": True, **extra,
    }


LIVE = [
    _lot("https://torgi.gov.ru/lot/BIG1", "Участок 0,6 га", land=6000),
    _lot("https://torgi.gov.ru/lot/SML1", "Участок 0,2 га", land=2000),
    _lot("https://torgi.gov.ru/lot/NOA1", "Здание без площади участка", building=900,
         lot_kind="property_complex"),
]
FINISHED = [
    _lot("https://torgi.gov.ru/lot/FIN1", "Участок 1 га, торги прошли", land=10_000,
         status="Состоялся", status_code="SUCCEED", result_price_rub=91_000_000, finished=True),
]

READ = """() => ({
  names: [...document.querySelectorAll('#sheetRows tr.sheetrow td.k-name')].map(td => td.textContent),
  area: document.getElementById('areaNote').innerText,
  areaShown: getComputedStyle(document.getElementById('areaNote')).display !== 'none',
  finished: document.getElementById('finishedNote').innerText,
  finishedShown: getComputedStyle(document.getElementById('finishedNote')).display !== 'none',
  asOf: document.getElementById('finishedAsOf').value,
})"""


def _rows(page, count: int) -> dict:
    page.wait_for_function(
        f"document.querySelectorAll('#sheetRows tr.sheetrow').length === {count}")
    return page.evaluate(READ)


@pytest.mark.timeout(240)
def test_in_a_real_browser_the_area_filter_and_finished_lots(tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    asked: list[str] = []
    finished_answer = {"body": {"lots": FINISHED, "count": 1, "cached": False,
                                "window": {"since": "2026-07-19", "until": "2026-10-19", "months": 3},
                                "coverage": [
                                    {"source": "ГИС Торги (torgi.gov.ru)", "kept": 1, "cards": 40,
                                     "finished_available": True, "reason": ""},
                                    {"source": "Росэлторг", "finished_available": False,
                                     "reason": "завершённые торги по этой площадке на странице недоступны"}]},
                       "status": 200}

    def finished(route):
        asked.append(route.request.url)
        route.fulfill(status=finished_answer["status"], content_type="application/json",
                      body=json.dumps(finished_answer["body"], ensure_ascii=False))

    with serve(_app(tmp_path, monkeypatch, []), PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("**/auctions/discover*", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"lots": LIVE, "coverage": [], "quality": {}, "count": 3},
                                ensure_ascii=False)))
            page.route("**/auctions/finished*", finished)
            page.goto(f"{base}/auctions", wait_until="domcontentloaded")
            page.click("#refresh")
            seen = _rows(page, 3)
            assert not seen["areaShown"], "без фильтра площади пометки нет"

            # Быстрый выбор 0,5 га: маленький участок уходит, лот без площади
            # участка остаётся — последним и с пометкой.
            page.click("#landHalfHa")
            seen = _rows(page, 2)
            assert "Участок 0,6 га" in seen["names"][0]
            assert "Здание без площади участка" in seen["names"][1]
            assert "Площадь участка не указана" in seen["names"][1]
            assert not any("0,2 га" in name for name in seen["names"])
            assert seen["areaShown"] and "подходит 1 лот" in seen["area"]
            assert "площадь участка неизвестна" in seen["area"]
            # Подделка: фильтр, который молча выкидывает лот без площади, ловится.
            page.evaluate("state.filtered = state.filtered.filter(l => l.land_area_sqm); loadSheet()")
            fake = _rows(page, 1)
            assert not any("Площадь участка не указана" in name for name in fake["names"])
            page.fill("#landMinHa", "0,5")
            page.dispatch_event("#landMinHa", "input")
            _rows(page, 2)
            # Участок от 0,5 га спрятан выбором типа — пояснение это называет.
            page.evaluate("state.auctionKinds=new Set(['property_complex']);filter()")
            hidden = _rows(page, 1)
            assert "подходит 0 лот" in hidden["area"]
            assert "скрыты другими фильтрами (Продажа земли)" in hidden["area"], hidden["area"]
            page.evaluate("state.auctionKinds=new Set();filter()")
            _rows(page, 2)

            # Завершённые торги: дата по умолчанию — сегодня, лот помечен,
            # площадка без истории названа.
            assert seen["asOf"], "дата «на дату» пустая"
            page.check("#showFinished")
            seen = _rows(page, 3)
            assert asked and "as_of=" in asked[-1]
            finished_row = next(name for name in seen["names"] if "торги прошли" in name)
            assert "Торги завершены: Состоялся" in finished_row
            assert "91 млн ₽" in finished_row
            assert "найдено 1" in seen["finished"]
            assert "Росэлторг: по этой площадке завершённые торги недоступны" in seen["finished"]

            page.fill("#finishedAsOf", "2026-09-30")
            page.dispatch_event("#finishedAsOf", "change")
            page.wait_for_function("state.finished.loading === false")
            assert any("as_of=2026-09-30" in url for url in asked)

            # Площадка не ответила — причина на экране, текущие торги на месте.
            # Площадка отдала 48 завершённых, отбор «интересные» снял все:
            # на экране причина, а не голое «найдено 0» (прод, 19.10.2026).
            finished_answer["body"] = {
                **finished_answer["body"], "lots": [], "count": 0,
                "quality": {"seen": 48, "accepted": 0, "incomplete": 40, "outside_profile": 8, "noise": 0},
                "coverage": [{"source": "ГИС Торги (torgi.gov.ru)", "kept": 48, "cards": 106,
                              "finished_available": True, "reason": "",
                              "outside_window_before": 36, "outside_window_after": 22,
                              "filters": [{"filter": "земельные участки", "cards": 60,
                                           "total_elements": 1461,
                                           "stopped": "прочитано 6 страниц — это предел для одной выборки"}]}]}
            page.fill("#finishedAsOf", "2026-09-29")
            page.dispatch_event("#finishedAsOf", "change")
            page.wait_for_function("document.getElementById('finishedNote').innerText.includes('Площадка отдала')")
            seen = page.evaluate(READ)
            assert "найдено 0" in seen["finished"]
            assert "Площадка отдала 48 завершённых" in seen["finished"]
            assert "не хватает данных у 40" in seen["finished"]
            assert "«Интересные + неполные и шум»" in seen["finished"]
            assert "60 из 1461" in seen["finished"], "предел листания назван"
            assert "36 лот(ов) закончились раньше, у 22 дата торгов позже" in seen["finished"]
            assert page.evaluate("document.getElementById('finishedNote').classList.contains('warn')")

            finished_answer.update(status=502, body={"detail": "torgi.gov.ru не ответил"})
            page.fill("#finishedAsOf", "2026-10-01")
            page.dispatch_event("#finishedAsOf", "change")
            page.wait_for_function("document.getElementById('finishedNote').innerText.includes('не получены')")
            seen = _rows(page, 2)
            assert "torgi.gov.ru не ответил" in seen["finished"]

            page.uncheck("#showFinished")
            seen = _rows(page, 2)
            assert not seen["finishedShown"]

            # Телефон: новая строка фильтров не распирает страницу.
            page.set_viewport_size({"width": 390, "height": 844})
            width = page.evaluate("()=>[document.documentElement.scrollWidth, innerWidth]")
            assert width[0] <= width[1] + 1, width
            assert not errors, errors
        finally:
            browser.close()


# --- одна площадь участка на фильтр, таблицу и книгу ---------------------------

def test_the_land_area_in_the_title_reaches_the_filter_not_only_the_table(tmp_path, monkeypatch):
    """Лот «здание 634,4 м² + участок 396 м²» — с площадью участка в выдаче.

    Прод, 19.10.2026: таблица показывала 396 м² (их достраивал `export_areas`
    из названия), а фильтр читал пустое поле площадки, и лот проходил фильтр
    0,5 га с пометкой «площадь участка не указана».
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search import api

    title = ("Продажа единым лотом имущества, находящегося в собственности города Москвы: "
             "нежилое здание площадью 634,4 кв. м и земельный участок площадью 396 кв. м")
    card = _card()
    card.update(id="ROW1", lotName=title, lotDescription=title, subjectRFCode="77")
    card["characteristics"] = [{**item, "characteristicValue": "634.4"} if item["code"] == "totalAreaRealty"
                               else item for item in card["characteristics"]]

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(api, "_discovery_adapters", lambda source: [_Pages([[card]])])
    app = FastAPI()
    api.install(app)
    lot = TestClient(app).get("/auctions/discover", params={"include_noise": "true"}).json()["lots"][0]
    assert lot["land_area_sqm"] == 396, "площадь участка из названия дошла до лота выдачи"
    assert lot["building_area_sqm"] == 634.4
    assert lot["area_from_title"] == ["land_area_sqm"]
    # Тот же лот в книге — то же число: правило одно.
    from auction_search.export_areas import export_areas
    assert export_areas({"name": title, "url": lot["source"]["lot_url"],
                         "land_area_sqm": lot["land_area_sqm"],
                         "building_area_sqm": lot["building_area_sqm"]}).land_area_sqm == 396


# --- площадь участков лота из НСПД --------------------------------------------

def _points(**by_number):
    return {number.replace("_", ":"): point for number, point in by_number.items()}


LAND_A, LAND_B, BUILD = "77:04:0002004:86", "77:04:0002004:29", "77:04:0002004:1062"


def test_nspd_adds_up_the_land_parcels_of_a_lot_and_skips_the_building():
    from auction_search.api import _nspd_land_area

    data = {"title": "нежилое здание пл.2020,9кв.м", "cadastral_numbers": [BUILD, LAND_A, LAND_B],
            "land_area_sqm": None, "building_area_sqm": 2020.9}
    points = {BUILD: {"kind": "building", "area_sqm": 2020.9, "map_url": "x", "under_parcels": []},
              LAND_A: {"kind": "land", "area_sqm": 3200.0, "map_url": "x"},
              LAND_B: {"kind": "land", "area_sqm": 2100.0, "map_url": "x"}}
    _nspd_land_area(data, points)
    assert data["land_area_sqm"] == 5300, "участки лота — сумма, здание не участок"
    assert data["land_area_source"] == "НСПД, участков 2"
    assert data["land_area_partial"] is False and data["land_area_pending"] == 0


def test_nspd_marks_a_lot_partial_while_some_parcels_are_not_known():
    from auction_search.api import _nspd_land_area

    data = {"cadastral_numbers": [LAND_A, LAND_B], "land_area_sqm": None}
    _nspd_land_area(data, {LAND_A: {"kind": "land", "area_sqm": 3200.0, "map_url": "x"}})
    assert data["land_area_sqm"] == 3200
    assert data["land_area_partial"] is True, "второй участок не спрошен — сумма неполная"
    assert data["land_area_pending"] == 1


def test_nspd_does_not_shrink_a_named_area_and_widens_it_only_when_complete():
    from auction_search.api import _nspd_land_area

    named = {"cadastral_numbers": [LAND_A, LAND_B], "land_area_sqm": 396.0,
             "area_from_title": ["land_area_sqm"]}
    _nspd_land_area(named, {LAND_A: {"kind": "land", "area_sqm": 300.0, "map_url": "x"}})
    assert named["land_area_sqm"] == 396 and named["land_area_source"] == "название лота"
    wider = {"cadastral_numbers": [LAND_A, LAND_B], "land_area_sqm": 396.0,
             "area_from_title": ["land_area_sqm"]}
    _nspd_land_area(wider, {LAND_A: {"kind": "land", "area_sqm": 396.0, "map_url": "x"},
                            LAND_B: {"kind": "land", "area_sqm": 5000.0, "map_url": "x"}})
    assert wider["land_area_sqm"] == 5396, "НСПД знает оба участка — берём полную сумму"


def test_the_background_asks_every_seen_lot_and_once_more_for_old_points(tmp_path):
    from auction_search import lot_notes as rules

    store = rules.LotNotes(tmp_path / "market")
    soon = "2099-01-10T12:00:00+03:00"
    store.remember_lots([{"title": "Здание", "cadastral_numbers": [BUILD, LAND_A],
                          "application_deadline_iso": soon,
                          "source": {"lot_url": "https://torgi.gov.ru/lot/1"}}])
    store.request([{"section": "Торги", "name": "Лот выгрузки", "cadastre": LAND_B,
                    "application_deadline_iso": soon, "url": "https://etp/lot/2"}])
    assert store.points_queue() == [LAND_B, BUILD, LAND_A], "лот выгрузки — первым, лот сбора — тоже в очереди"
    store.save_point(BUILD, {"asked_at": 1, "map_url": "x"})  # запись до площадей
    store.save_point(LAND_A, {"asked_at": 1, "map_url": "x", "kind": "land", "area_sqm": 3200.0})
    assert store.points_queue() == [LAND_B, BUILD], "старая запись без вида переспрашивается один раз"


def test_the_point_keeps_the_kind_and_the_area_of_the_parcel(tmp_path, monkeypatch):
    import sys
    import types

    from fastapi import FastAPI

    from auction_search import api
    from auction_search import lot_notes as rules

    href = "https://nspd.gov.ru/map?thematic=PKK&zoom=17&coordinate_x=1&coordinate_y=2"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    core = types.ModuleType("developaid_core")
    core._land_lookup_by_numbers = lambda numbers: [
        {"found": True, "cadastral_number": numbers[0], "map_url": href, "kind": "land", "area_sqm": 3200.0}]
    core._core_api_url = lambda path: ""
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    app = FastAPI()
    app.state.market_discovery_service = types.SimpleNamespace(search=None, krt=None)
    api.install(app)
    store = rules.LotNotes(tmp_path / "market")
    store.remember_lots([{"title": "Участок", "cadastral_numbers": [LAND_A],
                          "application_deadline_iso": "2099-01-10T12:00:00+03:00",
                          "source": {"lot_url": "https://torgi.gov.ru/lot/1"}}])
    assert app.state.auction_nspd_points_once() == 1
    point = store.points()[LAND_A]
    assert point["kind"] == "land" and point["area_sqm"] == 3200.0


def test_on_the_page_a_partial_area_below_the_threshold_stays_with_its_note():
    from auction_search import ui
    from tests import page_blocks

    lots = [_lot("https://torgi.gov.ru/lot/P1", "Два участка, известен один", land=3200,
                 land_area_partial=True, land_area_pending=1),
            _lot("https://torgi.gov.ru/lot/S1", "Маленький участок", land=3200),
            _lot("https://torgi.gov.ru/lot/U1", "Без площади", land_area_pending=2)]
    out, _ = page_blocks.run(
        "const LOTS=%s;" % json.dumps(lots, ensure_ascii=False),
        "state.lots=LOTS;state.areaUnknown=new Set();"
        "const kept=LOTS.filter(l=>landAreaUnsure(l,5000));"
        "kept.forEach(l=>state.areaUnknown.add(l));"
        "console.log(JSON.stringify(kept.map(l=>[l.title,areaUnknownLine(l)])))",
        page=ui.auctions_page())
    got = json.loads(out.strip().splitlines()[-1])
    titles = [title for title, _note in got]
    assert titles == ["Два участка, известен один", "Без площади"], "известный маленький участок уходит"
    assert "известна не по всем участкам" in got[0][1]
    assert "уточняем её в НСПД" in got[1][1]


# --- честная цена в отборе «Интересные» -----------------------------------------

def test_a_symbolic_price_and_an_auction_start_price_are_not_compared_with_deals():
    from auction_search.profile_fit import comparable_price, profile_fit

    maip = {"land_area_sqm": 9094, "current_price_rub": 1.0, "procedure_type": "Иной вид торгов · Аукцион"}
    price, note = comparable_price(maip)
    assert price is None and note.startswith("цена 1 ₽ — символическая")
    fit = profile_fit(maip)
    assert fit["fit"] == 1.0 and fit["misses"] == [], "участок 0,9 га — не «ниже сделок в 48 млн раз»"
    start = {"land_area_sqm": 6964, "current_price_rub": 78_971.76,
             "procedure_type": "Аренда и продажа земельных участков · Электронный аукцион"}
    assert comparable_price(start)[0] is None and "стартовая цена аукциона" in comparable_price(start)[1]
    sold = {**start, "land_area_sqm": 50_000, "current_price_rub": 543_000, "result_price_rub": 25_010_580}
    assert comparable_price(sold) == (25_010_580, ""), "у завершённых торгов — итоговая цена"
    offer = {"land_area_sqm": 900, "current_price_rub": 2_000_000,
             "procedure_type": "Продажа имущества · Публичное предложение"}
    assert comparable_price(offer) == (2_000_000, ""), "цена публичного предложения — цена, не нижняя граница"


def test_the_main_selection_keeps_large_land_with_a_symbolic_price():
    card = _finished("MAIP", "FAILED", "2026-09-10T12:00:00Z")
    card["characteristics"][0]["characteristicValue"] = "9094"
    card.update(priceMin=1, lotName="Право заключения договора о реализации масштабного инвестиционного проекта, "
                                    "земельный участок, г. Москва")
    lot = torgi_gov.to_lot(card, "t")
    from auction_search.catalogue_quality import catalogue_quality

    quality = catalogue_quality(lot)
    assert quality["accepted"] is True, quality
    assert quality["notes"] and "символическая" in quality["notes"][0]


# --- участок под зданием -------------------------------------------------------

def test_the_parcel_under_a_building_gives_the_lot_its_land_area():
    from auction_search.api import _nspd_land_area

    data = {"cadastral_numbers": [BUILD], "land_area_sqm": None, "building_area_sqm": 595.8}
    _nspd_land_area(data, {BUILD: {"kind": "building", "map_url": "x"}})
    assert data["land_area_sqm"] is None and data["land_area_pending"] == 1, \
        "участок под зданием ещё не искали — «уточняется»"
    _nspd_land_area(data, {BUILD: {"kind": "building", "map_url": "x", "under_parcels": [
        {"cadastral_number": LAND_A, "area_sqm": 440.0, "method": "building_center"}]}})
    assert data["land_area_sqm"] == 440
    assert data["land_area_source"].endswith("в том числе под зданием")
    both = {"cadastral_numbers": [BUILD, LAND_A], "land_area_sqm": None}
    _nspd_land_area(both, {BUILD: {"kind": "building", "map_url": "x", "under_parcels": [
        {"cadastral_number": LAND_A, "area_sqm": 440.0}]},
        LAND_A: {"kind": "land", "area_sqm": 440.0, "map_url": "x"}})
    assert both["land_area_sqm"] == 440, "участок, стоящий в лоте своим номером, не считается дважды"


def test_the_background_looks_for_the_parcel_under_a_building(tmp_path, monkeypatch):
    import sys
    import types

    from fastapi import FastAPI

    from auction_search import api
    from auction_search import lot_notes as rules

    href = "https://nspd.gov.ru/map?thematic=PKK&zoom=17&coordinate_x=1&coordinate_y=2"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    core = types.ModuleType("developaid_core")
    core._land_lookup_by_numbers = lambda numbers: [
        {"found": True, "cadastral_number": numbers[0], "map_url": href, "kind": "building", "area_sqm": 595.8}]
    core._core_api_url = lambda path: ""
    core._land_lot_context = lambda numbers: {"land_parcels": [
        {"cadastral_number": LAND_A, "area_sqm": 440.0, "lookup_methods": ["building_center"]}]}
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    app = FastAPI()
    app.state.market_discovery_service = types.SimpleNamespace(search=None, krt=None)
    api.install(app)
    store = rules.LotNotes(tmp_path / "market")
    store.remember_lots([{"title": "Здание", "cadastral_numbers": [BUILD],
                          "application_deadline_iso": "2099-01-10T12:00:00+03:00",
                          "source": {"lot_url": "https://torgi.gov.ru/lot/1"}}])
    assert app.state.auction_nspd_points_once() == 1
    point = store.points()[BUILD]
    assert point["under_parcels"] == [{"cadastral_number": LAND_A, "area_sqm": 440.0,
                                       "method": "building_center"}]
    assert store.points_queue() == [], "здание с найденным участком больше не спрашивается"


# --- страница: что скрыто другими фильтрами ------------------------------------

def test_on_the_page_lots_hidden_by_the_kind_are_named_and_shares_are_not_unknown():
    from auction_search import ui
    from tests import page_blocks

    lots = [_lot("https://rts/lot/K1", "КРТ 22 га", land=227_900, lot_kind="krt"),
            _lot("https://torgi.gov.ru/lot/B1", "Здание без участка", building=595.8,
                 lot_kind="property_complex", land_area_pending=1),
            _lot("https://lot-online/lot/E1", "Пакет акций 50%", lot_kind="equity_stake")]
    out, _ = page_blocks.run(
        "const LOTS=%s;" % json.dumps(lots, ensure_ascii=False),
        "const list=LOTS.filter(l=>['property_complex','equity_stake'].some(k=>lotMatchesKind(l,k)));"
        "const pick=areaSelection(LOTS,list,5000);"
        "console.log(JSON.stringify({rows:pick.list.map(l=>l.title),area:pick.summary}))",
        page=ui.auctions_page())
    got = json.loads(out.strip().splitlines()[-1])
    assert got["rows"] == ["Здание без участка"], "доля в обществе — не «площадь неизвестна»"
    assert got["area"]["hidden"] == 1 and got["area"]["hiddenKinds"] == ["КРТ"]
    assert got["area"]["noParcel"] == 1 and got["area"]["matched"] == 0
