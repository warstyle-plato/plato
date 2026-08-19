"""Зоны видно на участке, а не только процентом.

«Зона накрывает 71%» — число; где именно она лежит, число не говорит, а
решение принимают по месту: угол или середина, вдоль улицы или поперёк.
Рисунок делается тем же меркатором, что и миниатюра участка, без внешних карт
— он работает и в телеграм-WebView.

Здесь закреплено:

- очертания зон снимаются там же, где считается доля: второй раз просить
  геометрию у НСПД — платить за то же самое дважды;
- на страницу едут прореженные кольца и только те, что задевают участок:
  полные контуры весят сотни килобайт, а на марке различима сотня точек;
- подзоны одного ограничения рисуются все разом — одна из них не ограничение,
  а его кусок;
- рисунок появляется только там, где есть и контур участка, и зоны.

Запуск: python3 -m pytest tests/test_zones_are_drawn_on_the_parcel.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
NODE = shutil.which("node")


def square(x0, y0, x1, y1, points: int = 4):
    if points <= 4:
        ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    else:
        ring = [[x0 + (x1 - x0) * i / points, y0] for i in range(points)]
        ring += [[x1, y0 + (y1 - y0) * i / points] for i in range(points)]
        ring += [[x1 - (x1 - x0) * i / points, y1] for i in range(points)]
        ring += [[x0, y1 - (y1 - y0) * i / points] for i in range(points)]
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


PARCEL = square(0, 0, 1000, 1000)


def test_the_outline_is_taken_where_the_share_is_counted():
    findings = [{"type_zone": "Охранная зона", "name": "Зона", "reg_number": "1",
                 "flag_class": "economic", "geometry": square(0, 0, 400, 1000)}]
    core._land_apply_coverage(findings, PARCEL)
    assert findings[0]["outline_merc"], "очертания сняты вместе с долей"
    assert "geometry" not in findings[0], "сырая геометрия на страницу не едет"


def test_a_zone_far_away_gets_no_outline():
    findings = [{"type_zone": "Далёкая", "name": "Далеко", "reg_number": "2",
                 "flag_class": "economic", "geometry": square(90000, 90000, 91000, 91000)}]
    core._land_apply_coverage(findings, PARCEL)
    assert findings[0]["coverage_pct"] == 0.0
    assert not findings[0].get("outline_merc"), "чего не видно на рисунке, того и не рисуем"


def test_a_huge_ring_is_thinned():
    """У приаэродромной десятки тысяч вершин: на марке различима сотня."""
    big = square(-500, -500, 1500, 1500, points=900)
    outline = core._land_zone_outline(big, (0.0, 0.0, 1000.0, 1000.0))
    assert outline and len(outline[0]) <= core._LAND_ZONE_RING_POINTS + 2
    assert outline[0][0] == outline[0][-1], "кольцо остаётся замкнутым"


def test_the_subzones_are_drawn_together():
    findings = [
        {"type_zone": "Приаэродромная территория", "name": "Третья подзона",
         "reg_number": "1", "flag_class": "economic", "geometry": square(0, 0, 300, 1000)},
        {"type_zone": "Приаэродромная территория", "name": "Пятая подзона",
         "reg_number": "2", "flag_class": "economic", "geometry": square(0, 0, 700, 1000)},
    ]
    core._land_apply_coverage(findings, PARCEL)
    grouped = core._land_group_findings(findings)
    assert len(grouped) == 1
    assert len(grouped[0]["outline_merc"]) == 2, "обе подзоны на рисунке"


def test_the_screening_answer_carries_the_parcel_contour():
    source = Path(core.__file__).read_text(encoding="utf-8")
    body = source[source.index('def land_screening('):]
    body = body[:body.index("def _land_zouit_findings(")]
    assert '"contour_merc": contour' in body


def _draw(parcel) -> str:
    if not NODE:
        pytest.skip("node недоступен")
    page = core.PAGE
    body = page[page.index("function screeningSpotSvg(parcel){"):page.index("function screeningFlagLabel(")]
    script = ("const escapeHtml=s=>String(s==null?'':s);\n"
              "const landNum=(v,d)=>String(Math.round(Number(v)));\n"
              + body + f"console.log(screeningSpotSvg({json.dumps(parcel)}));")
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return done.stdout


def test_the_drawing_shows_the_parcel_over_the_zones():
    svg = _draw({
        "contour_merc": [[[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]]],
        "findings": [{"name": "Приаэродромная", "flag_class": "economic", "coverage_pct": 71,
                      "outline_merc": [[[0, 0], [700, 0], [700, 1000], [0, 1000], [0, 0]]]}],
    })
    assert "<svg" in svg and "land-spot" in svg
    assert svg.index("fill-opacity") < svg.index('fill="none"'), (
        "зона под контуром: границы участка обязаны остаться читаемыми")
    assert "Приаэродромная" in svg and "71%" in svg, "легенда называет зону и долю"
    assert "Наложение приблизительное" in svg, "оценка названа оценкой"


def test_without_zones_there_is_nothing_to_draw():
    assert _draw({"contour_merc": [[[0, 0], [10, 0], [10, 10], [0, 0]]], "findings": []}).strip() == ""
    assert _draw({"contour_merc": [], "findings": [{"outline_merc": [[[0, 0]]]}]}).strip() == ""


def test_the_block_puts_the_drawing_under_the_list():
    body = core.PAGE[core.PAGE.index("function renderLandScreening(data){"):]
    body = body[:body.index("function landNum(")]
    assert "screeningSpotSvg(found[0])" in body
    assert "body+spot+" in body, "рисунок идёт после списка ограничений"
