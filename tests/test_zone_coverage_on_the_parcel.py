"""Зоны накладываются на участок: не «зона есть», а сколько участка она съела.

Скрининг спрашивает НСПД в одной точке — центре участка. На вопрос «есть ли
зона» этого хватает, на вопрос сделки — нет: зона, срезающая угол, в центр не
попадает вовсе, а накрывшая центр выглядит одинаково и при пяти процентах, и
при ста (замечание владельца, 18.08.2026). Геометрия зоны приходит тем же
ответом GetFeatureInfo и раньше выбрасывалась.

Здесь закреплено:

- доля считается настоящей геометрией: половина — половина, угол — угол;
- дыра в контуре участка из площади вычитается;
- зона без геометрии даёт `None`, а не ноль: «не проверяли» не равно «не
  накрывает»;
- справочные слои (территориальные зоны) свободного пятна не отнимают;
- подзоны одного ограничения не складываются — берётся наибольшая;
- WGS84 и метры веб-меркатора считаются одинаково.

Запуск: python3 -m pytest tests/test_zone_coverage_on_the_parcel.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def square(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


PARCEL = square(0, 0, 1000, 1000)          # метры веб-меркатора


def test_half_is_half_and_a_corner_is_a_corner():
    got = core._land_coverage_shares(PARCEL, [
        square(0, 0, 500, 1000),           # ровно половина
        square(-100, -100, 200, 200),      # угол: 200×200 из 1000×1000 = 4%
        square(-1e4, -1e4, 1e4, 1e4),      # целиком
    ])
    half, corner, whole = got["shares"]
    assert 0.47 < half < 0.53
    assert 0.02 < corner < 0.07
    assert whole == 1.0
    assert got["free"] == 0.0


def test_a_zone_beside_the_parcel_is_not_a_flag_share():
    got = core._land_coverage_shares(PARCEL, [square(2000, 2000, 3000, 3000)])
    assert got["shares"][0] == 0.0
    assert got["free"] == 1.0


def test_a_hole_in_the_parcel_is_not_its_area():
    donut = {"type": "Polygon", "coordinates": [
        [[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]],
        [[400, 400], [600, 400], [600, 600], [400, 600], [400, 400]]]}
    solid = core._land_coverage_shares(PARCEL, [square(300, 300, 700, 700)])["shares"][0]
    holed = core._land_coverage_shares(donut, [square(300, 300, 700, 700)])["shares"][0]
    assert holed < solid, "дыра в контуре не может увеличить долю под зоной"


def test_a_zone_without_geometry_is_unknown_not_zero():
    got = core._land_coverage_shares(PARCEL, [None, square(0, 0, 1000, 1000)])
    assert got["shares"][0] is None
    assert got["shares"][1] == 1.0


def test_nothing_to_measure_gives_nothing():
    assert core._land_coverage_shares(None, [square(0, 0, 10, 10)]) == {}
    assert core._land_coverage_shares(PARCEL, []) == {"shares": [], "free": 1.0,
                                                      "samples": core._LAND_COVERAGE_GRID ** 2}


def test_a_reference_layer_does_not_eat_the_buildable_spot():
    """Территориальная зона накрывает участок целиком — это не значит, что
    строить негде."""
    got = core._land_coverage_shares(
        PARCEL, [square(0, 0, 500, 1000), square(-1e4, -1e4, 1e4, 1e4)],
        counted=[True, False])
    assert got["shares"][1] == 1.0
    assert 0.47 < got["free"] < 0.53


def test_degrees_and_metres_agree():
    """НСПД отдаёт то меркатор, то WGS84 — доля не имеет права зависеть от этого."""
    in_degrees = {"type": "Polygon", "coordinates": [
        [[37.60, 55.75], [37.62, 55.75], [37.62, 55.76], [37.60, 55.76], [37.60, 55.75]]]}
    zone = {"type": "Polygon", "coordinates": [
        [[37.60, 55.75], [37.61, 55.75], [37.61, 55.76], [37.60, 55.76], [37.60, 55.75]]]}
    share = core._land_coverage_shares(in_degrees, [zone])["shares"][0]
    assert 0.45 < share < 0.55


def test_the_subzones_do_not_add_up_to_two_hundred_percent():
    findings = [
        {"type_zone": "Приаэродромная территория", "name": "Третья подзона",
         "reg_number": "1", "flag_class": "economic", "geometry": square(0, 0, 300, 1000)},
        {"type_zone": "Приаэродромная территория", "name": "Пятая подзона",
         "reg_number": "2", "flag_class": "economic", "geometry": square(0, 0, 700, 1000)},
    ]
    core._land_apply_coverage(findings, PARCEL)
    grouped = core._land_group_findings(findings)
    assert len(grouped) == 1
    assert 65 < grouped[0]["coverage_pct"] < 75, grouped[0]["coverage_pct"]
    assert 25 < grouped[0]["free_pct"] < 35


def test_the_geometry_does_not_travel_to_the_page():
    """Контуры зон весят сотни килобайт: в ответе они не нужны, нужен процент."""
    findings = [{"type_zone": "Охранная зона", "name": "Зона", "reg_number": "1",
                 "flag_class": "economic", "geometry": square(0, 0, 500, 1000)}]
    core._land_apply_coverage(findings, PARCEL)
    assert "geometry" not in findings[0]
    assert findings[0]["coverage_pct"] > 0


def test_the_verdict_carries_the_free_spot():
    findings = [{"flag_class": "economic", "name": "Зона", "free_pct": 30.0},
                {"flag_class": "economic", "name": "Другая", "free_pct": 30.0}]
    verdict = core._land_screening_verdict(findings)
    assert verdict["free_pct"] == 30.0
    assert core._land_screening_verdict([])["free_pct"] is None


def test_the_worst_parcel_sets_the_free_spot():
    """У нескольких участков сводка не имеет права выглядеть лучше самого
    стеснённого из них."""
    findings = [{"flag_class": "economic", "name": "А", "free_pct": 80.0},
                {"flag_class": "killer", "name": "Б", "free_pct": 12.0}]
    assert core._land_screening_verdict(findings)["free_pct"] == 12.0


def test_the_block_and_the_report_show_the_share():
    page = core.PAGE
    assert "% участка" in page and "free_pct" in page
    assert "свободно от ограничений" in page

    engine = Path(core.__file__).read_text(encoding="utf-8")
    report = engine[engine.index('story.append(_PdfSection("screening"))'):]
    report = report[:report.index('story.append(_PdfSection("summary"))')]
    assert "накрывает ~" in report
    assert "Свободно от ограничений" in report
    assert "точность порядка процента" in report, "оценка названа оценкой"
