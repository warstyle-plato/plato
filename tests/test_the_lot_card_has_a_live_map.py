"""У карточки лота — живая карта участка, как у КРТ: двигается и масштабируется.

«Почему картинки на живой карте как в КРТ на аукционных карточках нет?» —
«На живой» (владелец, 04.10.2026). Прежде карточка лота показывала карту только
по кнопке, встроенной страницей OSM по адресу, без границ участка.

Теперь: тайлы — серверная подложка `/land/basemap` ровно на bbox тайла, контуры —
кольца НСПД из проверки `/land/lot-context`, которую карточка и так делает. Лот
без кадастрового номера получает точку по адресу и причину, почему контура нет.

Запуск: python3 -m pytest tests/test_the_lot_card_has_a_live_map.py -q
"""

from __future__ import annotations

import base64
import json
import math
import sys
import urllib.parse
from pathlib import Path

import pytest

from browser import chromium_or_skip, serve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_the_auction_page_shows_the_book_columns import LOTS, _app  # noqa: E402

PORT = 18814
MERC = 20037508.342789244
# Квадрат 80×60 м у Тверской, меркаторные метры.
X0, Y0 = 4187900.0, 7509300.0
RING = [[X0, Y0], [X0 + 80, Y0], [X0 + 80, Y0 + 60], [X0, Y0 + 60], [X0, Y0]]
CONTEXT = {"land_parcels": [{"cadastral_number": "77:01:0001001:1001", "area_sqm": 4800,
                             "contour_merc": [RING], "lookup_methods": []}],
           "buildings": [], "other_objects": [], "warnings": []}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
NO_NUMBER = dict(LOTS[0], cadastral_numbers=[], title="Нежилое здание по адресу: г. Москва, ул. Арбат, д. 2",
                 source=dict(LOTS[0]["source"], lot_url="https://torgi.gov.ru/lot/NO-CAD"))


def _open(page, base: str, lots: list[dict], tiles: list[str]) -> None:
    page.route("**/auctions/discover*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"lots": lots, "coverage": [], "quality": {}, "count": len(lots)})))
    page.route("**/land/lot-context", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(CONTEXT)))
    page.route("**/auctions/lot-point", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"latitude": 55.7495, "longitude": 37.5925, "address": "Москва, Арбат, 2"})))

    def tile(route):
        tiles.append(route.request.url)
        route.fulfill(status=200, content_type="image/png", body=PNG)
    page.route("**/land/basemap*", tile)
    page.goto(f"{base}/auctions", wait_until="domcontentloaded")
    page.click("#refresh")
    page.wait_for_function(f"document.querySelectorAll('#sheetRows tr.sheetrow').length === {len(lots)}")


def _path_box(page) -> dict:
    """Геометрия контура в пикселях кадра — без толщины обводки."""
    box = page.evaluate("""() => {
      const svg = document.querySelector('#lotLiveMap svg.lm-shapes').getBoundingClientRect();
      const b = document.querySelector('#lotLiveMap path.lm-land').getBBox();
      return {x: svg.left + b.x, y: svg.top + b.y, width: b.width, height: b.height};
    }""")
    return box


@pytest.mark.timeout(240)
def test_the_lot_card_draws_the_parcel_on_a_live_map(tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    tiles: list[str] = []
    with serve(_app(tmp_path, monkeypatch), PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, base, [LOTS[0]], tiles)
            page.click("#sheetRows tr.sheetrow >> nth=0")
            page.wait_for_selector("#lotLiveMap path.lm-land")
            mapbox = page.locator("#lotLiveMap .livemap").bounding_box()
            box = _path_box(page)
            # Контур в кадре целиком.
            assert mapbox["x"] <= box["x"] and box["x"] + box["width"] <= mapbox["x"] + mapbox["width"]
            assert mapbox["y"] <= box["y"] and box["y"] + box["height"] <= mapbox["y"] + mapbox["height"]
            # Тайл — bbox ровно одного тайла OSM текущего масштаба (сервер возьмёт тот же масштаб).
            z = page.evaluate("$('lotLiveMap').querySelector('.lm-host')._liveMap.z")
            page.wait_for_timeout(200)
            assert tiles, "подложка не запрошена"
            for url in tiles:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                minx, miny, maxx, maxy = map(float, query["bbox"][0].split(","))
                assert query["width"] == ["256"]
                assert maxx - minx == pytest.approx(2 * MERC / 2 ** z, rel=1e-9)
                assert round(math.log2(2 * MERC / 256 / ((maxx - minx) / 256))) == z
            page.screenshot(path=str(tmp_path / "card.png"))

            # Перетаскивание сдвигает контур ровно на столько же.
            cx, cy = mapbox["x"] + mapbox["width"] / 2, mapbox["y"] + mapbox["height"] / 2
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx - 100, cy + 40, steps=5)
            page.mouse.up()
            moved = _path_box(page)
            assert moved["x"] == pytest.approx(box["x"] - 100, abs=1.5)
            assert moved["y"] == pytest.approx(box["y"] + 40, abs=1.5)

            # Колесо отдаляет: масштаб на шаг меньше, контур вдвое мельче;
            # «+» возвращает шаг.
            page.mouse.move(cx, cy)
            page.mouse.wheel(0, 120)
            smaller = _path_box(page)
            assert page.evaluate("$('lotLiveMap').querySelector('.lm-host')._liveMap.z") == z - 1
            assert smaller["width"] == pytest.approx(moved["width"] / 2, rel=0.05)
            page.click("#lotLiveMap .lm-ctl button[data-z='1']")
            assert page.evaluate("$('lotLiveMap').querySelector('.lm-host')._liveMap.z") == z
            # «К участку» возвращает кадр на контур.
            page.click("#lotLiveMap .lm-ctl button[data-fit]")
            back = _path_box(page)
            assert back["width"] == pytest.approx(box["width"], rel=0.05)
            assert back["x"] == pytest.approx(box["x"], abs=1.5)
            assert not errors, errors
        finally:
            browser.close()


@pytest.mark.timeout(240)
def test_a_lot_without_a_number_gets_a_point_and_the_reason(tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    tiles: list[str] = []
    with serve(_app(tmp_path, monkeypatch), PORT + 1) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            errors: list[str] = []
            phone.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(phone, base, [NO_NUMBER], tiles)
            phone.click("#sheetRows tr.sheetrow >> nth=0")
            phone.wait_for_selector("#lotLiveMap circle.lm-point")
            text = phone.inner_text("#lotLiveMap")
            assert "не указала кадастровый номер" in text, text
            assert "Москва, Арбат, 2" in text
            assert phone.locator("#lotLiveMap path.lm-land").count() == 0
            box = phone.locator("#lotLiveMap .livemap").bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 390, box
            width = phone.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            assert width[0] <= width[1], width
            # Палец тянет карту, а не страницу.
            assert phone.evaluate(
                "getComputedStyle(document.querySelector('#lotLiveMap .livemap')).touchAction") == "none"
            phone.screenshot(path=str(tmp_path / "phone.png"))
            assert not errors, errors
        finally:
            browser.close()
