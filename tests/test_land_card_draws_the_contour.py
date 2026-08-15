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
    assert svg.startswith('<div class="land-contour"><svg viewBox="0 0 ')
    assert '<path d="M' in svg and svg.count(" L ") >= 4
    assert "Границы по сведениям ЕГРН" in svg
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
