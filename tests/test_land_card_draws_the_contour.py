"""Карточка участка рисует границы из ЕГРН своим SVG.

Контур — вариант «день ноль»: форма участка без внешних карт, работает и в
телеграм-WebView, и при недоступной НСПД. Здесь закреплено:

- движок кладёт внешние кольца геометрии в ответ (`contour_merc`), приводя
  градусы к веб-меркатору тем же признаком величин, что `_geometry_center`;
- страница строит SVG настоящей функцией `landContourSvg` (гоняется через
  node, не пересказ): путь, viewBox, подпись ширины через cos(широты) —
  меркаторный метр растянут, и без пересчёта подпись врала бы в 1,8 раза
  на широте Москвы;
- пустая или битая геометрия не рисует ничего и ничего не роняет.

Запуск: python3 -m pytest tests/test_land_card_draws_the_contour.py -q
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core
NODE = shutil.which("node")

MERC_RING = [[4200000.0, 7550000.0], [4200100.0, 7550000.0],
             [4200100.0, 7550100.0], [4200000.0, 7550100.0], [4200000.0, 7550000.0]]


def test_the_engine_ships_the_contour_in_mercator():
    rings = main._geometry_contours_merc({"type": "Polygon", "coordinates": [MERC_RING]})
    assert rings == [MERC_RING]


def test_degrees_are_converted_like_the_center():
    ring_deg = [[37.57, 55.80], [37.58, 55.80], [37.58, 55.81], [37.57, 55.81], [37.57, 55.80]]
    rings = main._geometry_contours_merc({"type": "Polygon", "coordinates": [ring_deg]})
    assert len(rings) == 1
    x, y = rings[0][0]
    assert math.isclose(x, 37.57 * 20037508.34 / 180.0, rel_tol=1e-6)
    assert 7_000_000 < y < 8_000_000, "широта Москвы в меркаторе — около 7,5 млн м"


def test_holes_and_junk_do_not_leak():
    multi = {"type": "MultiPolygon",
             "coordinates": [[MERC_RING, [[0, 0], [1, 0], [1, 1], [0, 0]]], "мусор"]}
    rings = main._geometry_contours_merc(multi)
    assert rings == [MERC_RING], "во внешние кольца попала дыра или мусор"
    assert main._geometry_contours_merc(None) == []
    assert main._geometry_contours_merc({"type": "Point", "coordinates": [1, 2]}) == []


def test_the_lookup_result_carries_the_contour():
    feature = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [MERC_RING]},
        "properties": {"categoryName": "Земельные участки ЕГРН",
                       "options": {"cad_num": "50:12:0080205:123", "land_record_area": 10000.0}},
    }
    normalized = main._normalize_nspd_feature(feature)
    assert normalized["contour_merc"] == [MERC_RING]


def _svg_harness() -> str:
    match = re.search(r"(function landContourSvg\(item\)\{.*?\n\})\n\nfunction landCardHtml",
                      main.PAGE, re.S)
    assert match, "landContourSvg не найдена на странице"
    return match.group(1)


def run_svg(item: dict) -> str:
    if not NODE:
        pytest.skip("node недоступен")
    script = _svg_harness() + f"""
console.log(JSON.stringify(landContourSvg({json.dumps(item, ensure_ascii=False)})));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_the_page_draws_the_polygon():
    svg = run_svg({"contour_merc": [MERC_RING], "center": {"lat": 55.9105, "lng": 37.7365}})
    assert svg.startswith('<div class="land-contour"><div class="land-contour-stage"')
    assert '<path d="M' in svg and svg.count(" L ") >= 4
    assert "Границы по сведениям ЕГРН" in svg
    # Подложка карты просится тем же bbox, что и контур; при отказе карта
    # снимает себя и честно правит подпись — обещать подложку, которой нет,
    # подпись не имеет права.
    assert '<img class="land-contour-map" src="/land/map-image?bbox=' in svg
    assert 'onerror="landMapLost(this)"' in svg
    # Меркаторные 100 м на широте Мытищ — около 56 настоящих метров.
    width = re.search(r"~(\d+)", svg)
    assert width and 50 <= int(width.group(1)) <= 60, svg


def test_an_empty_geometry_draws_nothing():
    assert run_svg({"contour_merc": []}) == ""
    assert run_svg({}) == ""
    assert run_svg({"contour_merc": [[[1, 2]]]}) == ""


def test_a_lost_map_fixes_the_caption():
    """landMapLost снимает картинку и переписывает подпись про подложку."""
    match = re.search(r"(function landMapLost\(img\)\{.*?\n\})", main.PAGE, re.S)
    assert match, "landMapLost не найдена на странице"
    body = match.group(1)
    assert "img.remove()" in body
    assert "карта НСПД не ответила" in body
    assert "подложка — публичная карта НСПД" in body, "замена ищет не ту подпись"


def test_the_card_includes_the_contour():
    card = main.PAGE[main.PAGE.index("function landCardHtml"):]
    card = card[:card.index("function renderLandLookup")]
    assert "landContourSvg(item)" in card, "карточка не зовёт отрисовку контура"


def _territory_harness() -> str:
    match = re.search(r"(function landTerritorySvg\(found\)\{.*?\n\})\n\nfunction landContourSvg",
                      main.PAGE, re.S)
    assert match, "landTerritorySvg не найдена на странице"
    return "const escapeHtml=s=>String(s);\n" + match.group(1)


def run_territory(found: list) -> str:
    if not NODE:
        pytest.skip("node недоступен")
    script = _territory_harness() + f"""
console.log(JSON.stringify(landTerritorySvg({json.dumps(found, ensure_ascii=False)})));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_several_parcels_share_one_scale():
    """Территория из нескольких участков рисуется одной посадкой."""
    second = [[p[0] + 120, p[1]] for p in MERC_RING]
    svg = run_territory([
        {"cadastral_number": "50:12:0080205:123", "contour_merc": [MERC_RING]},
        {"cadastral_number": "50:12:0080205:124", "contour_merc": [second]},
    ])
    assert svg.count("<path") == 2, "участки слились или потерялись"
    assert "<title>50:12:0080205:124</title>" in svg
    assert "Территория из 2 участков" in svg
    assert '<img class="land-contour-map"' in svg


def test_a_single_parcel_needs_no_territory_view():
    """Один участок — миниатюра в карточке, общая посадка не дублирует её."""
    assert run_territory([{"cadastral_number": "x", "contour_merc": [MERC_RING]}]) == ""
    assert run_territory([]) == ""


def test_the_territory_keeps_its_proportions():
    """max-width привязывает высоту к истинному аспекту: без него сцена с
    max-height и width:100% сплющивалась по высоте (замечание владельца,
    17.08.2026 — «высота маленькая, непропорционально»)."""
    second = [[p[0] + 120, p[1]] for p in MERC_RING]  # шире, чем выше
    svg = run_territory([
        {"cadastral_number": "a", "contour_merc": [MERC_RING]},
        {"cadastral_number": "b", "contour_merc": [second]},
    ])
    aspect = re.search(r"aspect-ratio:([\d.]+) / ([\d.]+)", svg)
    max_w = re.search(r"max-width:(\d+)px", svg)
    assert aspect and max_w, "у сцены нет аспекта и max-width"
    w, h = float(aspect.group(1)), float(aspect.group(2))
    # Ширина, при которой высота ровно 240px, — 240·w/h. Тогда потолок высоты
    # не искажает форму: и подложка, и контур сохраняют пропорции.
    assert int(max_w.group(1)) == round(240 * w / h)


def test_every_tep_path_draws_the_land_card():
    """Карточка участка рисуется при любом пути получения ТЭП, а не только
    при поиске по адресу: кадастровый «Получить ТЭП» оставлял человека без
    картинки участка (замечание владельца, 16.08.2026)."""
    helper = main.PAGE[main.PAGE.index("async function drawLandPreviewQuiet"):]
    helper = helper[:helper.index("\nfunction landNum")]
    assert "'/land/lookup'" in helper
    assert "renderLandLookup(data)" in helper
    for owned in ("cadastralStatus", "cadastralAnalyzeButton"):
        assert owned not in helper, f"тихая карточка трогает чужое: {owned}"
    server_path = main.PAGE[main.PAGE.index("async function obtainServerTep"):]
    server_path = server_path[:server_path.index("async function obtainCadastralTep")]
    assert "drawLandPreviewQuiet()" in server_path
    iframe_path = main.PAGE[main.PAGE.index("async function obtainCadastralTep"):]
    iframe_path = iframe_path[:iframe_path.index("function renderCadastralPreview")]
    assert "drawLandPreviewQuiet()" in iframe_path
    mo_path = main.PAGE[main.PAGE.index("async function calculateMo"):]
    mo_path = mo_path[:mo_path.index("async function applyMo")]
    assert "drawLandPreviewQuiet(query)" in mo_path


def test_the_list_renders_the_territory_first():
    body = main.PAGE[main.PAGE.index("function renderLandLookup"):]
    body = body[:body.index("function useLandForTep")]
    assert "landTerritorySvg(found)+" in body, "список карточек не начинается с посадки"


def test_many_parcels_drop_the_per_card_map():
    """Несколько участков — общий вид один на всех, карточки без своих мини-карт:
    иначе на 30 участков вышло бы 30 повторов той же подложки (замечание
    владельца, 17.08.2026). Один участок — миниатюра в карточке остаётся."""
    body = main.PAGE[main.PAGE.index("function renderLandLookup"):]
    body = body[:body.index("function useLandForTep")]
    assert "found.length<2" in body, "нет признака единственного участка"
    assert "landCardHtml(x,single)" in body, "карточки не получают признак общего вида"

    if not NODE:
        pytest.skip("node недоступен")
    contour = re.search(r"(function landContourSvg\(item\)\{.*?\n\})\n\nfunction landCardHtml",
                        main.PAGE, re.S)
    card = re.search(r"(function landCardHtml\(item,showContour\)\{.*?\n\})\n\nfunction renderLandLookup",
                     main.PAGE, re.S)
    assert contour and card, "не найдены landContourSvg / landCardHtml"
    harness = (
        "const escapeHtml=s=>String(s==null?'':s);\n"
        "const landNum=(v,d)=>String(v);\n"
        "const landCoords=c=>'x';\n"
        "const landDate=v=>String(v);\n"
        + contour.group(1) + "\n" + card.group(1) + "\n"
    )
    item = {"found": True, "cadastral_number": "50:12:0080205:1",
            "contour_merc": [MERC_RING], "center": {"lat": 55.7, "lng": 37.6}}
    script = harness + f"""
const item={json.dumps(item, ensure_ascii=False)};
console.log(JSON.stringify({{
  on: landCardHtml(item, true).includes('land-contour'),
  off: landCardHtml(item, false).includes('land-contour'),
  fallback: landCardHtml(item).includes('land-contour'),
}}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(result.stdout)
    assert got["on"] is True, "одиночная карточка потеряла миниатюру"
    assert got["off"] is False, "карточка в наборе всё ещё рисует свою карту"
    assert got["fallback"] is True, "без флага карточка обязана рисовать контур"


def test_the_map_backdrop_endpoint_speaks_wms(monkeypatch):
    """Подложка: bbox проверяется, уходит в НСПД тем же меркатором
    (EPSG:3857 — единственный формат, который НСПД приняла пробой),
    прозрачность выравнивается на светлый фон, ответ кэшируется."""
    import io as io_module

    from fastapi.testclient import TestClient
    from PIL import Image
    client = TestClient(main.app)
    calls = []

    def fake_png(west, south, east, north, width, height):
        calls.append((west, south, east, north, width, height))
        buffer = io_module.BytesIO()
        Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(buffer, format="PNG")
        return buffer.getvalue()

    monkeypatch.setattr(main, "_nspd_wms_map_png", fake_png)
    main._NSPD_MAP_CACHE.clear()
    assert client.get("/land/map-image", params={"bbox": "мусор"}).status_code == 400
    assert client.get("/land/map-image", params={"bbox": "0,0,99999999,1"}).status_code == 400
    bbox = "4199990,7549990,4200110,7550110"
    ok = client.get("/land/map-image", params={"bbox": bbox})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert ok.content.startswith(b"\x89PNG")
    west, south, east, north, width, height = calls[0]
    # Меркатор уходит в НСПД без пересчёта в градусы — пиксель в пиксель с SVG.
    assert (west, south, east, north) == (4199990.0, 7549990.0, 4200110.0, 7550110.0)
    assert width == 640 and height == 640, "квадратный bbox обязан дать квадратную картинку"
    # Прозрачный слой НСПД выровнен на светлый фон: фото бота при конвертации
    # в RGB иначе получило бы чёрный.
    image = Image.open(io_module.BytesIO(ok.content)).convert("RGB")
    assert image.getpixel((5, 5)) == (245, 245, 243)
    # Повтор — из кэша, без второго похода в НСПД.
    client.get("/land/map-image", params={"bbox": bbox})
    assert len(calls) == 1


def test_the_map_retries_without_tls_verification_like_the_lookup(monkeypatch):
    """Сертификат НСПД — российский УЦ: карта повторяет запрос без проверки.

    Поиск участков этот фолбэк имел, а карта только читала флаг — и в воркере,
    где ещё не искали, падала с CERTIFICATE_VERIFY_FAILED (скриншот владельца,
    16.08.2026). Флаг взводится и картой, и только по правилу NSPD_TLS_FALLBACK.
    """
    import ssl as ssl_module
    import urllib.error

    calls = []
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 16

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return png

    def fake_urlopen(request, timeout=0, context=None):
        calls.append(context)
        if context is None:
            raise urllib.error.URLError(ssl_module.SSLError("self-signed certificate"))
        return _Response()

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main, "_nspd_tls_insecure", False)
    assert main._nspd_wms_map_png(37.5, 55.7, 37.6, 55.8, 640, 640) == png
    assert calls[0] is None and calls[1] is not None, "повтор не отключил проверку"
    assert main._nspd_tls_insecure, "флаг не взведён — следующий воркер упадёт снова"


def test_the_stroke_is_screen_pixels_not_metres():
    """non-scaling-stroke мерит толщину в пикселях экрана: ширина, посчитанная
    от размаха территории в метрах, на 22 участках Мытищ давала кляксы."""
    big = [[4200000.0, 7550000.0], [4202000.0, 7550000.0],
           [4202000.0, 7552000.0], [4200000.0, 7552000.0], [4200000.0, 7550000.0]]
    second = [[p[0] + 2500, p[1]] for p in big]
    svg = run_territory([
        {"cadastral_number": "a", "contour_merc": [big]},
        {"cadastral_number": "b", "contour_merc": [second]},
    ])
    assert 'stroke-width="2"' in svg, "толщина уехала от константы в пиксели-метры"
    single = run_svg({"contour_merc": [big], "center": {"lat": 55.9, "lng": 37.7}})
    assert 'stroke-width="2.5"' in single


def test_the_map_probe_tries_every_candidate_format(monkeypatch):
    """Диагностика формата WMS: четыре кандидата (v3/v4 × 3857/4326-порядки),
    ответ говорит, кто отдал PNG. С телефона формат не проверить — WAF НСПД
    отдаёт Forbidden, поэтому перебор живёт на ядре."""
    from fastapi.testclient import TestClient

    asked: list[str] = []
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 10

    class _Response:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return self.body

    def fake_urlopen(request, timeout=0, context=None):
        asked.append(request.full_url)
        if "EPSG%3A3857" in request.full_url and "/v3/" in request.full_url:
            return _Response(png)
        import urllib.error
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main, "_nspd_tls_insecure", True)
    client = TestClient(main.app)
    payload = client.get("/land/map-probe").json()
    probe = payload["probe"]
    assert set(probe) == {"v3_3857_merc", "v4_3857_merc", "v3_4326_latlon", "v3_4326_lonlat"}
    assert probe["v3_3857_merc"] == {"ok": True, "bytes": len(png), "head": "PNG"}
    assert probe["v4_3857_merc"] == {"ok": False, "http": 404}
    lat_lon = [url for url in asked if "v3" in url and "EPSG%3A4326" in url]
    assert len(lat_lon) == 2, "оба порядка осей 4326 должны пробоваться"


def test_a_dead_nspd_leaves_the_plain_contour(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(main.app)

    def broken(*args):
        raise ValueError("НСПД молчит")

    monkeypatch.setattr(main, "_nspd_wms_map_png", broken)
    main._NSPD_MAP_CACHE.clear()
    response = client.get("/land/map-image", params={"bbox": "4199990,7549990,4200110,7550110"})
    assert response.status_code == 502


def test_overlay_probe_draws_the_contour_on_the_backdrop(monkeypatch):
    """Диагностика совмещения: контур рисуется на растре НСПД той же формулой,
    что SVG страницы, — ответ говорит, в данных сдвиг или в отрисовке. Живой
    НСПД закрыт для песочницы, поэтому проверяется композиция, а не сеть."""
    from fastapi.testclient import TestClient
    from PIL import Image

    client = TestClient(main.app)
    monkeypatch.setattr(main, "_core_api_url", lambda path: "")

    # Пустой номер — 400, а не попытка сходить в НСПД.
    assert client.get("/land/overlay-probe").status_code == 400

    ring = [[4181302.0, 7518174.0], [4181542.0, 7518174.0],
            [4181542.0, 7518414.0], [4181302.0, 7518414.0], [4181302.0, 7518174.0]]
    monkeypatch.setattr(main, "_nspd_search_features", lambda q: [
        {"properties": {"options": {"cad_num": "77:09:0004014:13"}},
         "geometry": {"type": "Polygon", "coordinates": [ring]}}])

    captured: dict[str, float] = {}

    def fake_png(west, south, east, north, width, height):
        captured.update(west=west, south=south, east=east, north=north)
        buffer = __import__("io").BytesIO()
        Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0)).save(buffer, format="PNG")
        return buffer.getvalue()

    monkeypatch.setattr(main, "_nspd_wms_map_png", fake_png)
    response = client.get("/land/overlay-probe", params={"cad": "77:09:0004014:13"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    # bbox подложки = контур ± pad (6% большей стороны) — тот же, что у карточки.
    assert captured["west"] == pytest.approx(4181302.0 - 240 * 0.06)
    assert captured["north"] == pytest.approx(7518414.0 + 240 * 0.06)
    # Синяя линия контура действительно легла на картинку.
    image = Image.open(__import__("io").BytesIO(response.content)).convert("RGB")
    pixels = image.tobytes()
    assert any(pixels[i + 2] > 180 and pixels[i] < 80
               for i in range(0, len(pixels), 3)), "контур не нарисован"
