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
            assert "не указала площадь участка" in seen["area"]
            # Подделка: фильтр, который молча выкидывает лот без площади, ловится.
            page.evaluate("state.filtered = state.filtered.filter(l => l.land_area_sqm); loadSheet()")
            fake = _rows(page, 1)
            assert not any("Площадь участка не указана" in name for name in fake["names"])
            page.fill("#landMinHa", "0,5")
            page.dispatch_event("#landMinHa", "input")
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
