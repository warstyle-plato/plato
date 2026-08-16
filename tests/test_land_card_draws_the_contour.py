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
    # Подложка карты просится тем же bbox, что и контур, и молча исчезает
    # по onerror — подложка украшение, а не данные.
    assert '<img class="land-contour-map" src="/land/map-image?bbox=' in svg
    assert 'onerror="this.remove()"' in svg
    # Меркаторные 100 м на широте Мытищ — около 56 настоящих метров.
    width = re.search(r"~(\d+)", svg)
    assert width and 50 <= int(width.group(1)) <= 60, svg


def test_an_empty_geometry_draws_nothing():
    assert run_svg({"contour_merc": []}) == ""
    assert run_svg({}) == ""
    assert run_svg({"contour_merc": [[[1, 2]]]}) == ""


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


def test_the_map_backdrop_endpoint_speaks_wms(monkeypatch):
    """Подложка: bbox проверяется, градусы считаются как в центре, кэшируется."""
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    calls = []

    def fake_png(west, south, east, north, width, height):
        calls.append((west, south, east, north, width, height))
        return b"\x89PNG\r\n\x1a\n" + b"x" * 32

    monkeypatch.setattr(main, "_nspd_wms_map_png", fake_png)
    main._NSPD_MAP_CACHE.clear()
    assert client.get("/land/map-image", params={"bbox": "мусор"}).status_code == 400
    assert client.get("/land/map-image", params={"bbox": "0,0,99999999,1"}).status_code == 400
    bbox = "4199990,7549990,4200110,7550110"
    ok = client.get("/land/map-image", params={"bbox": bbox})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert ok.content.startswith(b"\x89PNG")
    west, south, east, north, width, height = calls[0]
    assert west < east and south < north
    assert 50 < south < 60, "широта Мытищ потерялась при переводе из меркатора"
    # Повтор — из кэша, без второго похода в НСПД.
    client.get("/land/map-image", params={"bbox": bbox})
    assert len(calls) == 1


def test_a_dead_nspd_leaves_the_plain_contour(monkeypatch):
    from fastapi.testclient import TestClient
    client = TestClient(main.app)

    def broken(*args):
        raise ValueError("НСПД молчит")

    monkeypatch.setattr(main, "_nspd_wms_map_png", broken)
    main._NSPD_MAP_CACHE.clear()
    response = client.get("/land/map-image", params={"bbox": "4199990,7549990,4200110,7550110"})
    assert response.status_code == 502
