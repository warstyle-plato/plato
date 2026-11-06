"""Живая карта: «Схема / Гибрид». Гибрид — снимок Яндекса с улицами и подписями.

Решение владельца: к карте улиц добавить гибрид Яндекса. Законный путь у
Яндекса один: JavaScript API 2.1 в браузере и с ключом. Серверные API (Static,
Tiles) отдают только схему, а условия (п. 5.1.2, 5.1.6) запрещают сохранять
полученные картинки. Поэтому гибрид — вид живой карты, а `/land/basemap`
(печать, PDF, бот) остаётся картой улиц и на `layer=hybrid` отвечает причиной.

Что здесь закреплено:

- **без ключа гибрид не предлагается, и причина названа словами**, а не 502 и
  не схема молча вместо снимка;
- **ключ берётся из окружения и уходит только в адрес скрипта Яндекса**;
- **контур ложится на снимок**: тайлы Яндекса в эллиптическом меркаторе
  (EPSG:3395), наши контуры — в сферическом (EPSG:3857). Контур уходит в API
  широтой и долготой, переведёнными обратной формулой той же сферы. Подмена
  формулы эллиптической уводит участок в Москве на десятки километров,
  а пиксельная накладка — на сотни метров; проверка падает на такой подмене;
- **переключатель виден на отрисованной странице и меняет картинку.**

Запуск: python3 -m pytest tests/test_the_map_offers_a_yandex_hybrid.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402
from auction_search import land_map, ui  # noqa: E402

core = _wrapper.core
KEY_ENV = "YANDEX_MAPS_API_KEY"

R = 6378137.0
E = 0.0818191908426  # эксцентриситет WGS 84
# Знакомое место: Соборная площадь Кремля.
KREMLIN = (55.7505, 37.6175)


def _merc(lat: float, lon: float) -> list[float]:
    return [math.radians(lon) * R, R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))]


def _elliptic_lat(y: float) -> float:
    """Широта из y ЭЛЛИПТИЧЕСКОГО меркатора — та формула, которой здесь быть не должно."""
    t = math.exp(-y / R)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(12):
        s = E * math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(t * ((1 - s) / (1 + s)) ** (E / 2))
    return math.degrees(phi)


def _ring(lat: float, lon: float, d: float = 0.0008) -> list[list[float]]:
    return [_merc(lat, lon), _merc(lat, lon + d), _merc(lat + d / 2, lon + d),
            _merc(lat + d / 2, lon), _merc(lat, lon)]


# --- сервер ---------------------------------------------------------------

def test_without_a_key_the_hybrid_is_not_offered_and_the_reason_is_said(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    views = TestClient(_wrapper.app).get("/land/basemap-views").json()
    assert views["map"]["available"] is True
    assert views["hybrid"]["available"] is False
    assert views["hybrid"]["script"] == ""
    assert "ключ" in views["hybrid"]["reason"] and "Карта улиц" in views["hybrid"]["reason"]


def test_with_a_key_the_hybrid_is_offered_through_the_yandex_script(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "test-key-123")
    views = TestClient(_wrapper.app).get("/land/basemap-views").json()
    hybrid = views["hybrid"]
    assert hybrid["available"] is True and hybrid["reason"] == ""
    assert hybrid["script"].startswith("https://api-maps.yandex.ru/2.1/")
    # Порядок пары задан явно: перепутанная пара молча зеркалит полигон.
    assert "coordorder=latlong" in hybrid["script"]
    assert hybrid["script"].endswith("apikey=test-key-123")


def test_render_asks_the_core_and_a_silent_core_is_a_named_reason(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setattr(core, "_core_api_url", lambda path: "http://127.0.0.1:9" + path)
    hybrid = TestClient(_wrapper.app).get("/land/basemap-views").json()["hybrid"]
    assert hybrid["available"] is False
    assert "сервер расчётов не ответил" in hybrid["reason"]


def test_the_server_stitch_refuses_the_hybrid_with_words_not_a_bare_502(monkeypatch):
    called = []
    monkeypatch.setattr(core, "_basemap_png", lambda *a, **k: called.append(a) or b"png")
    client = TestClient(_wrapper.app)
    answer = client.get("/land/basemap", params={
        "bbox": "4187000,7509000,4189000,7511000", "layer": "hybrid"})
    assert answer.status_code == 422
    assert "условия" in answer.json()["detail"] and "карта улиц" in answer.json()["detail"]
    assert not called, "вместо гибрида молча склеена карта улиц"
    assert client.get("/land/basemap", params={
        "bbox": "4187000,7509000,4189000,7511000", "layer": "satellite"}).status_code == 400


def test_the_auctions_key_lets_the_map_ask_which_views_exist():
    from auction_search import access_keys
    assert "/land/basemap-views" in access_keys._EXTRA_GET


def test_the_hybrid_kit_travels_with_the_engine_map():
    script = land_map.script(core)
    for name in ("landMapGeo", "landMapSetLayer", "landMapHybridOpen", "landMapViews"):
        assert f"function {name}(" in script
    assert 'id="landMapLayers"' in land_map.markup(core)


# --- проекция -------------------------------------------------------------

def test_the_elliptic_trap_is_real_in_moscow():
    """Подмена проекции не мелочь: на широте Москвы это заметный сдвиг."""
    lat, lon = KREMLIN
    x, y = _merc(lat, lon)
    shift_m = (_elliptic_lat(y) - lat) * 111_320
    assert shift_m > 10_000, shift_m
    # Пиксельная накладка: те же тайлы на одном масштабе разъезжаются на
    # разницу масштабов проекций — сотни метров на поле в несколько километров.
    scale_gap = 1 - math.sqrt(1 - (E * math.sin(math.radians(lat))) ** 2)
    assert scale_gap * 50_000 > 50


# --- отрисованная страница -------------------------------------------------

FAKE_YMAPS = """
window.ymaps={
 ready(cb){cb()},
 Map:function(id,state,opts){
  window.__ymap={id:id,state:state,opts:opts||null,destroyed:false};
  const me=this;
  this.geoObjects={add(o){(window.__polys=window.__polys||[]).push(o)}};
  this.behaviors={enable(n){window.__ruler=n},disable(){window.__ruler=null}};
  this.getCenter=()=>state.center;this.getZoom=()=>state.zoom;this.setZoom=z=>{state.zoom=z};
  this.destroy=()=>{window.__ymap.destroyed=true};
  const box=document.getElementById(id);box.setAttribute('data-yandex','hybrid');
 },
 Polygon:function(coords,props,opts){this.coords=coords;this.opts=opts;this.events={add(){}}},
};
"""


def _open(views: dict, rings: list):
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page = ui.auctions_page(core)
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            asked: list[str] = []
            tab.on("request", lambda r: asked.append(r.url))
            tab.route("http://plato.test/auctions", lambda route: route.fulfill(
                body=page, content_type="text/html; charset=utf-8"))
            tab.route("http://plato.test/land/basemap-views", lambda route: route.fulfill(
                json=views))
            tab.route("http://plato.test/land/tiles/**", lambda route: route.fulfill(
                body=b"", content_type="image/png"))
            tab.route("https://api-maps.yandex.ru/**", lambda route: route.fulfill(
                body=FAKE_YMAPS, content_type="application/javascript"))
            tab.route("http://plato.test/**", lambda route: route.fulfill(
                status=404, body="") if "/land/" not in route.request.url
                and not route.request.url.endswith("/auctions") else route.fallback())
            tab.goto("http://plato.test/auctions")
            tab.evaluate("()=>{try{localStorage.removeItem('plato.basemap')}catch(e){}}")
            tab.evaluate("rings=>openLandMap({rings:rings,title:'Участок'})", rings)
            tab.wait_for_function("()=>LAND_MAP&&LAND_MAP.views")
            yield tab, asked
            tab.close()
        finally:
            browser.close()


def test_the_switch_is_visible_and_changes_the_picture():
    ring = _ring(*KREMLIN)
    views = {"map": {"available": True},
             "hybrid": {"available": True, "reason": "",
                        "print_reason": "В отчёт уходит карта улиц.",
                        "script": "https://api-maps.yandex.ru/2.1/?lang=ru_RU&coordorder=latlong&apikey=k"}}
    for tab, asked in _open(views, [ring]):
        bar = tab.evaluate("""()=>[...document.querySelectorAll('#landMapLayers button')]
            .map(b=>({text:b.textContent,disabled:b.disabled,visible:b.offsetWidth>0,
                      pressed:b.getAttribute('aria-pressed')}))""")
        # «Панорама» — третья кнопка того же переключателя (test_the_parcel_card_offers_a_yandex_panorama).
        assert [b["text"] for b in bar] == ["Схема", "Гибрид", "Панорама"]
        assert all(b["visible"] for b in bar), "переключатель не виден"
        assert bar[0]["pressed"] == "true" and not bar[1]["disabled"]
        before = tab.evaluate("()=>document.querySelectorAll('#landMapStage img').length")
        assert before > 0, "схема без тайлов"

        tab.click("#landMapLayers button[data-layer=hybrid]")
        tab.wait_for_function("()=>window.__ymap")
        state = tab.evaluate("""()=>({type:__ymap.state.type,opts:__ymap.opts,
            projection:'projection' in __ymap.state,
            tiles:document.querySelectorAll('#landMapStage img').length,
            yandex:!!document.querySelector('#landMapStage [data-yandex=hybrid]'),
            ring:__polys[__polys.length-1].coords[0],
            note:document.getElementById('landMapNote').textContent,
            saved:localStorage.getItem('plato.basemap')})""")
        assert state["type"] == "yandex#hybrid"
        assert state["yandex"] and state["tiles"] == 0, "картинка не сменилась"
        assert not state["projection"] and not (state["opts"] or {}).get("projection"), (
            "проекция Яндекса подменена: снимок в EPSG:3395 разойдётся с контуром")
        assert "Яндекс" in state["note"], "источник снимка не назван"
        assert "В отчёт уходит карта улиц." in state["note"], "причину печати сказал не сервер"
        assert state["saved"] == "hybrid"
        assert any(url.startswith("https://api-maps.yandex.ru/2.1/") for url in asked)

        # Контур ушёл широтой и долготой той же сферы — и лёг на место.
        lat, lon = state["ring"][0]
        assert abs(lat - KREMLIN[0]) * 111_320 < 1, "контур съехал по широте"
        assert abs(lon - KREMLIN[1]) * 111_320 * math.cos(math.radians(lat)) < 1
        # Подмена на эллиптическую формулу дала бы другой ответ — проверка его ловит.
        assert abs(_elliptic_lat(ring[0][1]) - lat) * 111_320 > 100

        tab.click("#landMapLayers button[data-layer=map]")
        back = tab.evaluate("""()=>({tiles:document.querySelectorAll('#landMapStage img').length,
            destroyed:__ymap.destroyed,layer:LAND_MAP.layer})""")
        assert back == {"tiles": back["tiles"], "destroyed": True, "layer": "map"}
        assert back["tiles"] > 0, "схема не вернулась"


def test_without_a_key_the_switch_says_why_and_stays_on_the_map():
    reason = "Вид со снимком со спутника пока не подключён: нужен ключ."
    views = {"map": {"available": True},
             "hybrid": {"available": False, "reason": reason, "script": ""}}
    for tab, asked in _open(views, [_ring(*KREMLIN)]):
        hybrid = tab.evaluate("""()=>{const b=document.querySelector(
            '#landMapLayers button[data-layer=hybrid]');return {disabled:b.disabled,title:b.title}}""")
        assert hybrid == {"disabled": True, "title": reason}
        tab.evaluate("()=>landMapSetLayer('hybrid')")
        after = tab.evaluate("""()=>({layer:LAND_MAP.layer,
            note:document.getElementById('landMapNote').textContent,
            tiles:document.querySelectorAll('#landMapStage img').length})""")
        assert after["layer"] == "map" and after["tiles"] > 0
        assert reason in after["note"], "причина не названа"
        assert not any("api-maps.yandex.ru" in url for url in asked)


def test_the_market_neighbours_open_the_same_live_map_with_the_switch():
    """Кабинет рынка: «Где соседи» открывает ту же движковую карту со «Схема / Гибрид»."""
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch
    from market_search import cabinet

    page = cabinet.cabinet_page("market")
    assert "function openLandMap(" in page and 'id="landMapLayers"' in page
    subject = {"latitude": 55.7505, "longitude": 37.6175, "project_name": "Объект"}
    market = [{"name": "Сосед А", "latitude": 55.755, "longitude": 37.62, "segment": "Бизнес"},
              {"name": "Сосед Б", "latitude": 55.745, "longitude": 37.61, "segment": "Комфорт"}]
    views = {"map": {"available": True},
             "hybrid": {"available": False, "reason": "Нужен ключ.", "script": ""}}
    errors: list[str] = []
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.route("http://plato.test/**", lambda route: route.fulfill(
                body=page, content_type="text/html; charset=utf-8")
                if route.request.url.endswith("/market") else route.fulfill(
                    json=views) if route.request.url.endswith("/land/basemap-views")
                else route.fulfill(status=404, body=""))
            tab.goto("http://plato.test/market")
            tab.evaluate("""([m,s])=>{const box=document.createElement('div');
                box.id='geoProbe';box.innerHTML=geoCard(m,s,m);document.body.appendChild(box)}""",
                         [market, subject])
            tab.click("#geoProbe button")
            tab.wait_for_function("()=>LAND_MAP&&LAND_MAP.views")
            seen = tab.evaluate("""()=>({open:document.getElementById('landMapDialog').style.display,
                buttons:[...document.querySelectorAll('#landMapLayers button')].map(b=>b.textContent),
                shapes:document.querySelectorAll('#landMapStage path[data-pick]').length})""")
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert seen == {"open": "flex", "buttons": ["Схема", "Гибрид", "Панорама"], "shapes": len(market)}


def test_the_new_parcel_page_takes_the_same_map_by_address():
    """Новый интерфейс участка берёт ту же карту скриптом, а не своей копией."""
    import main_registry  # маршруты торгов вешает прод-вход, как в Dockerfile

    answer = TestClient(main_registry.app).get("/land/live-map.js")
    assert answer.status_code == 200
    assert "javascript" in answer.headers["content-type"]
    assert "function landMapSetLayer(" in answer.text and "landMapLayers" in answer.text
    source = (ROOT / "frontend_v2" / "entry_layout.js").read_text(encoding="utf-8")
    assert "/land/live-map.js" in source and 'data-map-layer="hybrid"' in source
    # Своей формулы гибрида у нового интерфейса нет: снимок — только в общей карте.
    assert "api-maps.yandex.ru" not in source and "yandex#hybrid" not in source


def test_the_shared_script_mounts_the_map_on_a_bare_page():
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    script = land_map.standalone(core)
    views = {"map": {"available": True},
             "hybrid": {"available": False, "reason": "Нужен ключ Яндекс Карт.", "script": ""}}
    errors: list[str] = []
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            tab.on("pageerror", lambda e: errors.append(str(e)))
            def answer(route):
                url = route.request.url
                if url.endswith("/v2"):
                    return route.fulfill(body="<!doctype html><html><body><h1>v2</h1></body></html>",
                                         content_type="text/html")
                if url.endswith("/land/live-map.js"):
                    return route.fulfill(body=script, content_type="application/javascript")
                if url.endswith("/land/basemap-views"):
                    return route.fulfill(json=views)
                return route.fulfill(status=404, body="")
            tab.route("http://plato.test/**", answer)
            tab.goto("http://plato.test/v2")
            tab.add_script_tag(url="http://plato.test/land/live-map.js")
            tab.evaluate("()=>localStorage.setItem('plato.basemap','hybrid')")
            tab.evaluate("rings=>openLandMap({rings:rings,title:'Участок'})", [_ring(*KREMLIN)])
            tab.wait_for_function("()=>LAND_MAP&&LAND_MAP.views")
            seen = tab.evaluate("""()=>({open:document.getElementById('landMapDialog').style.display,
                layer:LAND_MAP.layer,note:document.getElementById('landMapNote').textContent,
                hybrid:document.querySelector('#landMapLayers button[data-layer=hybrid]').disabled})""")
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert seen["open"] == "flex" and seen["layer"] == "map" and seen["hybrid"] is True
    assert "Нужен ключ Яндекс Карт." in seen["note"], "выбранный гибрид молча стал схемой"
