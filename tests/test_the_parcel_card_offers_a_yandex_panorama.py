"""Панорама Яндекса вокруг участка — бесплатный тариф JavaScript API.

Решение владельца 25.10.2026 (docs/yandex_maps.md): риск осознанный, но
условия тарифа соблюдаем сами —

- п. 6.1.2, **не больше 100 показов панорам в сутки**: счёт ведёт сервер на
  диске, под блокировкой (воркеров два), и при исчерпанном лимите страница
  показывает кнопку-ссылку на Яндекс Карты, а не панораму;
- п. 4.1.1, **не в проектах с оплатой или закрытым доступом**: встроенная
  панорама есть только в открытой карточке участка (`payload.panorama`), на
  прочих страницах — та же ссылка;
- **ссылка работает без ключа** и строится одним шаблоном
  (`YANDEX_PANORAMA_LINK`) для страницы и бота;
- **нет панорамы в точке — причина словами**, а не пустое окно.

Проверки страницы идут на отрисованной странице (Playwright), а сервер
отвечает настоящим приложением: подделка «счётчик исчерпан» — файл счётчика
на диске, а не подменённый ответ.

Запуск: python3 -m pytest tests/test_the_parcel_card_offers_a_yandex_panorama.py -q
"""

from __future__ import annotations

import json
import math
import multiprocessing
import sys
import urllib.parse
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
KREMLIN = (55.7505, 37.6175)


def _merc(lat: float, lon: float) -> list[float]:
    return [math.radians(lon) * R, R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))]


def _ring(lat: float, lon: float, d: float = 0.0008) -> list[list[float]]:
    return [_merc(lat, lon), _merc(lat, lon + d), _merc(lat + d, lon + d),
            _merc(lat + d, lon), _merc(lat, lon)]


@pytest.fixture()
def keyed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv(KEY_ENV, "test-key-123")
    return tmp_path


def _spend(data_dir: Path, count: int, day: str | None = None) -> None:
    path = data_dir / "maps" / "yandex_panorama_day.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"day": day or core._panorama_today(), "count": count}))


# --- ссылка ----------------------------------------------------------------

def test_the_link_opens_the_panorama_at_the_point_without_a_key(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    url = core.yandex_panorama_url(*KREMLIN)
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query)
    assert parts.netloc == "yandex.ru" and parts.path == "/maps/"
    # Яндекс Карты пишут пару «долгота, широта» — перепутанная уводит в океан.
    assert query["panorama[point]"] == ["37.617500,55.750500"]
    assert query["ll"] == ["37.617500,55.750500"]
    assert "apikey" not in url and "test-key" not in url
    assert core.yandex_panorama_url(None, 37.6) == ""
    assert core.yandex_panorama_url(155.0, 37.6) == ""


def test_the_page_and_the_bot_read_one_link_template():
    assert ("const LAND_PANORAMA_LINK=" + json.dumps(core.YANDEX_PANORAMA_LINK) + ";") in core.PAGE
    assert "__DEVELOPAID_PANORAMA_LINK__" not in core.PAGE
    assert "yandex.ru/maps" not in "".join(
        land_map._function(core.PAGE, name) for name in land_map.FUNCTIONS), \
        "у карты своя копия ссылки"


# --- суточный лимит ---------------------------------------------------------

def test_the_hundred_and_first_panorama_of_the_day_is_refused_with_words(keyed):
    client = TestClient(_wrapper.app)
    views = client.get("/land/basemap-views").json()["panorama"]
    assert views["available"] is True and views["left"] == 100
    assert views["script"].startswith("https://api-maps.yandex.ru/2.1/")
    for _ in range(100):
        assert client.post("/land/panorama/claim").json()["granted"] is True
    refused = client.post("/land/panorama/claim").json()
    assert refused["granted"] is False and refused["left"] == 0
    assert "100" in refused["reason"] and "Яндекс Картах" in refused["reason"]
    after = client.get("/land/basemap-views").json()["panorama"]
    assert after["available"] is False and after["reason"] == refused["reason"]


def test_a_new_day_starts_a_new_count(keyed):
    _spend(keyed, 100, day="2000-01-01")
    answer = TestClient(_wrapper.app).post("/land/panorama/claim").json()
    assert answer["granted"] is True and answer["left"] == 99


def _claim_many(data_dir: str, times: int, out) -> None:
    import os
    os.environ["DATA_DIR"] = data_dir
    out.put(sum(core._panorama_counter(claim=True)["granted"] for _ in range(times)))


def test_two_workers_share_one_limit(keyed):
    """Два процесса, как два воркера прода: лимит общий, а не по сотне на каждого."""
    ctx = multiprocessing.get_context("fork")
    out = ctx.Queue()
    workers = [ctx.Process(target=_claim_many, args=(str(keyed), 70, out)) for _ in range(2)]
    for worker in workers:
        worker.start()
    granted = sum(out.get(timeout=60) for _ in workers)
    for worker in workers:
        worker.join(timeout=60)
    assert granted == 100


def test_without_a_key_nothing_is_counted_and_the_reason_is_said(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    client = TestClient(_wrapper.app)
    views = client.get("/land/basemap-views").json()["panorama"]
    claim = client.post("/land/panorama/claim").json()
    assert views["available"] is False and claim["granted"] is False
    assert "ключ" in views["reason"] and "кнопка ниже" in views["reason"]
    assert not (tmp_path / "maps").exists()


def test_render_asks_the_core_and_a_silent_core_is_a_named_reason(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setattr(core, "_core_api_url", lambda path: "http://127.0.0.1:9" + path)
    client = TestClient(_wrapper.app)
    claim = client.post("/land/panorama/claim").json()
    assert claim["granted"] is False and "сервер расчётов не ответил" in claim["reason"]
    views = client.get("/land/basemap-views").json()["panorama"]
    assert views["available"] is False and "сервер расчётов не ответил" in views["reason"]


# --- бот ---------------------------------------------------------------------

def test_the_bot_sends_the_same_link(monkeypatch):
    sent: list[str] = []
    territory = {"parcel_count": 1, "area_ha": 1.2, "district": "Тверской",
                 "cadastral_quarter": "77:01:0001001",
                 "center": {"lat": KREMLIN[0], "lng": KREMLIN[1]}}
    monkeypatch.setattr(core, "cadastral_route", lambda numbers, analysis: "moscow")
    monkeypatch.setattr(core, "analyze_cadastral_territory",
                        lambda req: {"recognized": ["77:01:0001001:1"], "territory": territory})
    monkeypatch.setattr(core, "_telegram_dialog_save", lambda *a, **k: None)
    monkeypatch.setattr(core, "_telegram_send_message", lambda chat, text, *a, **k: sent.append(text))
    monkeypatch.setattr(core, "_telegram_territory_photo_async", lambda *a, **k: None)
    monkeypatch.setattr(core, "_telegram_cad_class_menu", lambda *a, **k: None)
    core._telegram_handle_cadastral_numbers(1, ["77:01:0001001:1"])
    message = next(text for text in sent if "Территория сформирована" in text)
    import html
    assert f'<a href="{html.escape(core.yandex_panorama_url(*KREMLIN))}">' \
           "Открыть панораму в Яндекс Картах</a>" in message


# --- отрисованная страница ---------------------------------------------------

FAKE_YMAPS = """
window.ymaps={
 ready(cb){cb()},
 Map:function(id,state){this.geoObjects={add(){}};this.behaviors={enable(){},disable(){}};
  this.getCenter=()=>state.center;this.getZoom=()=>state.zoom;this.destroy=()=>{}},
 Polygon:function(){this.events={add(){}}},
 panorama:{
  isSupported(){return true},
  locate(point){window.__located=point;
   return Promise.resolve(window.__noPanorama?[]:[{id:'pano'}])},
  Player:function(id,pano,opts){
   window.__player={id:id,pano:pano,destroyed:false};
   document.getElementById(id).setAttribute('data-yandex','panorama');
   this.destroy=()=>{window.__player.destroyed=true};
  },
 },
};
"""

# Настоящие функции главной страницы, которыми карточка участка открывает карту.
CARD_FUNCTIONS = ("landMapFromContour", "landCardHtml", "landCoords", "landDate")


def _browse(rings, *, panorama: bool, no_panorama: bool = False, card: bool = False):
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page = ui.auctions_page(core)
    client = TestClient(_wrapper.app)
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            asked: list[str] = []
            errors: list[str] = []
            tab.on("request", lambda r: asked.append(r.method + " " + r.url))
            tab.on("pageerror", lambda e: errors.append(str(e)))

            def server(route):
                # Отвечает настоящее приложение: счётчик — файл на диске.
                url = urllib.parse.urlsplit(route.request.url)
                if url.path == "/auctions":
                    return route.fulfill(body=page, content_type="text/html; charset=utf-8")
                if url.path in ("/land/basemap-views", "/land/panorama/claim"):
                    answer = client.request(route.request.method, url.path)
                    return route.fulfill(status=answer.status_code, body=answer.content,
                                         content_type="application/json")
                if url.path.startswith("/land/tiles/"):
                    return route.fulfill(body=b"", content_type="image/png")
                return route.fulfill(status=404, body="")

            tab.route("http://plato.test/**", server)
            tab.route("https://api-maps.yandex.ru/**", lambda route: route.fulfill(
                body=FAKE_YMAPS, content_type="application/javascript"))
            tab.goto("http://plato.test/auctions")
            if no_panorama:
                tab.evaluate("()=>{window.__noPanorama=true}")
            if card:
                tab.add_script_tag(content="\n".join(
                    land_map._function(core.PAGE, name) for name in CARD_FUNCTIONS)
                    + "\nfunction siteMassingMapShapes(){return []}\nlet landScreeningLast=null;")
                tab.evaluate("""rings=>{window.landLookup={results:[{found:true,
                    cadastral_number:'77:01:0001001:1',contour_merc:rings}]};landMapFromContour('77:01:0001001:1')}""",
                    rings)
            else:
                tab.evaluate("([rings,panorama])=>openLandMap({rings:rings,title:'Участок',panorama:panorama})",
                             [rings, panorama])
            tab.wait_for_function("()=>LAND_MAP&&LAND_MAP.views")
            yield tab, asked, errors
            tab.close()
        finally:
            browser.close()


def _press_panorama(tab):
    tab.click("#landMapLayers button[data-layer=panorama]")
    tab.wait_for_function("()=>document.getElementById('landMapPanoramaLink')||window.__player")
    return tab.evaluate("""()=>{const link=document.getElementById('landMapPanoramaLink');
        const box=link&&link.getBoundingClientRect();
        return {link:link?link.href:null,label:link?link.textContent:null,
          linkVisible:!!(box&&box.width>0&&box.height>0),
          reason:(document.getElementById('landMapPanoramaReason')||{}).textContent||'',
          player:!!document.querySelector('#landMapStage [data-yandex=panorama]'),
          note:document.getElementById('landMapNote').textContent,
          tiles:document.querySelectorAll('#landMapStage img').length}}""")


def _claims(asked):
    return [url for url in asked if url.startswith("POST ") and url.endswith("/land/panorama/claim")]


def test_the_open_card_shows_the_panorama_and_counts_it(keyed):
    for tab, asked, errors in _browse([_ring(*KREMLIN)], panorama=False, card=True):
        buttons = tab.evaluate("()=>[...document.querySelectorAll('#landMapLayers button')]"
                               ".map(b=>({text:b.textContent,visible:b.offsetWidth>0}))")
        assert [b["text"] for b in buttons] == ["Схема", "Гибрид", "Панорама"]
        assert all(b["visible"] for b in buttons)
        assert not _claims(asked), "показ потрачен до нажатия"
        seen = _press_panorama(tab)
        assert seen["player"] and seen["tiles"] == 0, "панорама не открылась"
        assert seen["link"] is None
        assert "Яндекс" in seen["note"]
        assert len(_claims(asked)) == 1
        assert json.loads((keyed / "maps" / "yandex_panorama_day.json").read_text())["count"] == 1
        # Точка — середина участка, пара «широта, долгота» (coordorder=latlong).
        lat, lng = tab.evaluate("()=>window.__located")
        assert abs(lat - (KREMLIN[0] + 0.0004)) < 1e-5 and abs(lng - (KREMLIN[1] + 0.0004)) < 1e-5

        tab.click("#landMapLayers button[data-layer=map]")
        back = tab.evaluate("()=>({destroyed:__player.destroyed,layer:LAND_MAP.layer,"
                            "tiles:document.querySelectorAll('#landMapStage img').length,"
                            "saved:localStorage.getItem('plato.basemap')})")
        assert back["destroyed"] and back["layer"] == "map" and back["tiles"] > 0
        assert back["saved"] != "panorama", "панорама запомнилась и тратила бы показ при открытии"
        assert not errors, errors


def test_a_spent_day_shows_the_link_instead_of_the_panorama(keyed):
    """Подделка: счётчик на диске уже исчерпан — вместо панорамы кнопка-ссылка."""
    _spend(keyed, 100)
    for tab, asked, errors in _browse([_ring(*KREMLIN)], panorama=True):
        seen = _press_panorama(tab)
        assert not seen["player"], "панорама показана сверх лимита"
        assert seen["label"] == "Открыть панораму в Яндекс Картах" and seen["linkVisible"]
        assert seen["link"].startswith("https://yandex.ru/maps/") and "panorama" in seen["link"]
        assert "100" in seen["reason"] and "закончились" in seen["reason"]
        assert not any("api-maps.yandex.ru" in url for url in asked), "API тронут сверх лимита"
        assert not errors, errors


def test_the_last_panorama_taken_by_someone_else_turns_into_the_link(keyed):
    """Окно открылось при 99, а последний показ успел взять другой посетитель."""
    _spend(keyed, 99)
    for tab, asked, errors in _browse([_ring(*KREMLIN)], panorama=True):
        _spend(keyed, 100)
        seen = _press_panorama(tab)
        assert not seen["player"] and seen["linkVisible"]
        assert len(_claims(asked)) == 1 and "закончились" in seen["reason"]


def test_no_panorama_at_the_point_is_a_reason_not_an_empty_window(keyed):
    for tab, asked, errors in _browse([_ring(*KREMLIN)], panorama=True, no_panorama=True):
        seen = _press_panorama(tab)
        assert not seen["player"] and seen["linkVisible"]
        assert "нет панорамы" in seen["reason"]


def test_without_a_key_only_the_link_works_and_the_reason_is_under_the_map(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    for tab, asked, errors in _browse([_ring(*KREMLIN)], panorama=True):
        seen = _press_panorama(tab)
        assert not seen["player"] and seen["linkVisible"]
        assert "ключ" in seen["reason"]
        assert not _claims(asked) and not any("api-maps.yandex.ru" in url for url in asked)


def test_a_closed_page_gets_the_link_not_the_panorama(keyed):
    """Без `payload.panorama` (торги, кабинет рынка) встроенной панорамы нет."""
    for tab, asked, errors in _browse([_ring(*KREMLIN)], panorama=False):
        seen = _press_panorama(tab)
        assert not seen["player"] and seen["linkVisible"]
        assert not _claims(asked) and not any("api-maps.yandex.ru" in url for url in asked)
        assert not (keyed / "maps" / "yandex_panorama_day.json").exists()
