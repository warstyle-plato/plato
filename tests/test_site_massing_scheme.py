"""Объёмная схема застройки: корпуса очередей на участке — движок, страница, PDF.

Решение владельца (22.10.2026): корпуса по очередям, пятно очереди
пропорционально её наземной ГНС; выше предела этажности (без предела — 25)
очередь делится на корпуса по пределу; корпус длиннее 100 м делится по длине.
Раскладка и картинка — один ответ движка (`tep.site_massing.scheme`): страница
и PDF рисуют его многоугольники.

Проверочные примеры: офис на Пролетарском проспекте, вл. 20 (участок 0,243 га,
наземная ГНС 22 842 м², 68 мест под землёй) и участок 8 га с тремя очередями и
пределом 17 этажей.

Запуск: python3 -m pytest tests/test_site_massing_scheme.py -q
"""

from __future__ import annotations

import copy
import io
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser

import main as _wrapper

core = _wrapper.core


def _office_inputs():
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind="nonresidential", project_class="business", site_area_ha=0.243,
             project_region="msk", vri_region="msk", offices_enabled=True,
             offices_gba_sqm=22842, offices_parking_under_spaces=68,
             _parking_by_hand=["offices"])
    return x, {"offices": {"gns": 22842.0, "total_area": 22842.0}}


def _office_bundle(**extra):
    x, t = _office_inputs()
    x.update(extra)
    return x, t, core._run_authoritative_model(x, t, [], {})


def _big_site_three_phases():
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(site_area_ha=8.0, max_storeys_allowed=17, building_footprint_sqm=7000)
    phasing = {"enabled": True, "phase_count": 3,
               "phases": [{"name": "О1"}, {"name": "О2"}, {"name": "О3"}]}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=x, tep=t, rates=[], phasing=phasing))


def _rect_area(rect):
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def test_the_proletarsky_office_is_one_building_of_fifteen_storeys():
    _, _, bundle = _office_bundle()
    m = bundle["consolidated"]["tep"]["site_massing"]
    layout = m["scheme"]["layout"]
    [b] = layout["buildings"]
    assert b["area_sqm"] == pytest.approx(m["footprint_sqm"])
    assert b["storeys_shown"] == 15 and b["storeys_origin"] == "estimate"
    assert b["label"] == "Здание, 15 этажей"
    assert _rect_area(b["rect_m"]) == pytest.approx(b["area_sqm"], rel=0.01)
    # Контура из ЕГРН нет — квадрат той же площади, и это сказано.
    assert layout["site_shape_origin"] == "square"
    assert any("квадратом той же площади" in n for n in layout["notes"])
    ax = m["scheme"]["axonometry"]
    assert [s["kind"] for s in ax["shapes"]].count("roof") == 1
    assert [g["text"] for g in ax["legend"]] == ["Здание, 15 этажей"]


def test_the_underground_levels_are_drawn_with_their_areas():
    """Под участком — плита на каждый уровень расчёта с его площадью."""
    _, _, bundle = _office_bundle()
    m = bundle["consolidated"]["tep"]["site_massing"]
    ax = m["scheme"]["axonometry"]
    rows = m["underground_level_rows"]
    assert len(rows) == 2
    plates = [s for s in ax["shapes"] if s["kind"] == "underground_level"]
    assert sorted(s["level"] for s in plates) == [-2, -1]
    texts = {t["level"]: t["text"] for t in ax["texts"]}
    assert texts == {-1: f"−1: {core._fmt_ru(rows[0]['area_sqm'])} м²",
                     -2: f"−2: {core._fmt_ru(rows[1]['area_sqm'])} м²"}
    # Неполный нижний уровень — плита меньше верхней.
    area = {s["level"]: abs(core._ring_area(s["points"])) for s in plates}
    assert area[-2] < area[-1]
    assert "два подземных уровня" in ax["caption"]


def test_a_big_site_with_three_phases_and_a_limit_of_17_gets_more_corpora_than_phases():
    bundle = _big_site_three_phases()
    m = bundle["consolidated"]["tep"]["site_massing"]
    buildings = m["scheme"]["layout"]["buildings"]
    assert {b["phase"] for b in buildings} == {1, 2, 3}
    assert len(buildings) > 3
    assert all(b["storeys_shown"] <= 17 for b in buildings)
    # Пятно очереди — пропорционально её наземной ГНС; этажность не выше предела.
    for item in bundle["phases"]:
        gns = core.project_above_gns(item["tep"])
        own = [b for b in buildings if b["phase"] == item["index"]]
        assert sum(b["area_sqm"] * b["storeys"] for b in own) == pytest.approx(gns)
    assert all(b["label"].startswith(f"Очередь {b['phase']}, корпус ") for b in buildings)


def test_a_corpus_is_not_longer_than_a_hundred_metres():
    m = {"site_sqm": 80000.0, "footprint_sqm": 12000.0, "setback_m": 3.0,
         "footprint_origin": "estimate"}
    layout = core.site_massing_layout({}, m, [{"phase": 1, "above_gns_sqm": 60000.0}])
    assert len(layout["buildings"]) == math.ceil(12000 / (18 * 100))
    assert all(b["storeys_shown"] == 5 for b in layout["buildings"])


def test_without_a_limit_the_threshold_is_twenty_five_storeys():
    m = {"site_sqm": 20000.0, "footprint_sqm": 1000.0, "setback_m": 3.0}
    layout = core.site_massing_layout({}, m, [{"phase": 1, "above_gns_sqm": 30000.0}])
    assert layout["storeys_limit"] == 25 and layout["storeys_limit_origin"] == "default"
    assert len(layout["buildings"]) == 2
    assert all(b["storeys_shown"] == 25 for b in layout["buildings"])
    assert any("предел участка не задан" in n for n in layout["notes"])


def test_the_corpora_stand_inside_the_egrn_contour_without_setbacks():
    """Контур из ЕГРН (веб-меркатор) — в метрах; корпуса внутри отступа."""
    lat = 55.70
    k = math.cos(math.radians(lat))
    y0 = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = 37.65 * 20037508.34 / 180
    shape = [(0, 0), (320, -30), (360, 180), (150, 260), (-20, 200)]
    ring = [[x0 + a / k, y0 + b / k] for a, b in shape]
    x = {"_land_lookup": {"results": [{"found": True, "contour_merc": [ring]}]}}
    site = abs(core._ring_area([list(p) for p in shape]))
    m = {"site_sqm": site, "footprint_sqm": 9000.0, "setback_m": 3.0}
    layout = core.site_massing_layout(x, m, [{"phase": 1, "above_gns_sqm": 90000.0},
                                             {"phase": 2, "above_gns_sqm": 60000.0}])
    assert layout["site_shape_origin"] == "contour"
    # Корпус на карте — то же место в меркаторе: внутри контура ЕГРН.
    for b in layout["buildings"]:
        for corner in b["ring_merc"]:
            assert core._inside(tuple(corner), [ring]), (b["label"], corner)
        assert abs(core._ring_area(b["ring_merc"])) * k * k == pytest.approx(
            _rect_area(b["rect_m"]), rel=0.01)
    contour = sum(abs(core._ring_area(r)) for r in layout["site_rings"])
    assert contour == pytest.approx(site, rel=0.01)
    inner = layout["underground_rings"]
    for b in layout["buildings"]:
        x0r, y0r, x1r, y1r = b["rect_m"]
        for corner in ((x0r, y0r), (x1r, y0r), (x1r, y1r), (x0r, y1r)):
            assert core._inside(corner, inner), (b["label"], corner)


def test_a_scheme_of_dozens_of_corpora_is_not_drawn():
    """Нагатино-подобный случай: 17,8 га, четыре очереди, десятки корпусов —
    схему не рисуем (владелец 23.10.2026), строка на очередь вместо неё."""
    m = {"site_sqm": 178110.0, "footprint_sqm": 125680.0, "setback_m": 3.0,
         "footprint_origin": "estimate", "underground_levels": 1}
    phases = [{"phase": i, "above_gns_sqm": gns} for i, gns in
              enumerate((120000.0, 110000.0, 110000.0, 103700.0), 1)]
    scheme = core.site_massing_scheme({}, m, phases)
    layout = scheme["layout"]
    assert len(layout["buildings"]) > core.LAYOUT_MAX_DRAWN_CORPORA
    assert scheme["axonometry"] == {}
    assert "Схему не рисуем" in layout["skipped"]
    assert len(layout["phase_lines"]) == 4
    assert layout["phase_lines"][0].startswith("Очередь 1: ")
    assert " корпус" in layout["phase_lines"][0] and "этаж" in layout["phase_lines"][0]
    assert not any("ring_merc" in b for b in layout["buildings"])
    # PDF печатает причину и строки, а не картинку.
    parts = core._site_massing_scheme_pdf(scheme, lambda text, style=None: text, None,
                                          lambda items: items, 1.0)
    assert parts == [["Объёмная схема застройки", layout["skipped"], *layout["phase_lines"]]]


def test_a_contour_of_another_size_is_not_drawn_as_the_site():
    """Контур из ЕГРН сильно другой площади — не вся территория: участок квадратом."""
    lat = 55.70
    k = math.cos(math.radians(lat))
    y0 = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = 37.65 * 20037508.34 / 180
    ring = [[x0 + a / k, y0 + b / k] for a, b in ((0, 0), (40, 0), (40, 300), (0, 300))]
    x = {"_land_lookup": {"results": [{"found": True, "contour_merc": [ring]}]}}
    m = {"site_sqm": 178110.0, "footprint_sqm": 9000.0, "setback_m": 3.0}
    layout = core.site_massing_layout(x, m, [{"phase": 1, "above_gns_sqm": 90000.0}])
    assert layout["site_shape_origin"] == "square"
    assert any("не вся территория проекта" in n for n in layout["notes"])
    assert not any("ring_merc" in b for b in layout["buildings"])


def test_the_pdf_draws_the_scheme():
    """В PDF — картинка схемы: многоугольники цвета очереди и номер корпуса."""
    pypdf = pytest.importorskip("pypdf")
    x, t, bundle = _office_bundle()
    pdf = core._build_developaid_pdf({
        "result": bundle["consolidated"], "phases": bundle.get("phases") or [],
        "inputs": x, "tep": t, "rates": [], "phasing": {}, "scenario": "base",
        "cadastral_numbers": []})
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = " ".join(" ".join(p.extract_text() for p in reader.pages).split())
    assert "Объёмная схема застройки" in text, text[:2000]
    assert "1 — Здание, 15 этажей" in text
    color = core.LAYOUT_PHASE_COLORS[0]
    roof = core._shade(color, 1.25)
    rgb = " ".join(f"{int(roof[i:i + 2], 16) / 255:.5g}".rstrip("0").rstrip(".")
                   for i in (1, 3, 5))
    streams = b"".join(p.get_contents().get_data() for p in reader.pages)
    fills = [line for line in streams.decode("latin-1").splitlines() if line.endswith(" rg")]
    assert any(_same_rgb(line, roof) for line in fills), (rgb, fills[:20])


def _same_rgb(line, color):
    try:
        parts = [float(v) for v in line.split()[:3]]
    except ValueError:
        return False
    want = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return len(parts) == 3 and all(abs(a - b) < 0.01 for a, b in zip(parts, want))


SETUP = """async ()=>{
 applyProjectKind('nonresidential'); closeProjectKindDialog(); await settledCalculate();
 setSiteArea(0.243); setSiteDensity(22842/0.243);
 applyDensityToObject('offices'); await settledCalculate();
 openTab('inputs'); renderInputs();
 document.querySelectorAll('#inputs details').forEach(d=>{d.open=true});
}"""

READ = """()=>{
 openTab('tep'); renderTep();
 const box=document.getElementById('siteMassingScheme');
 const svg=box&&box.querySelector('svg');
 const r=svg?svg.getBoundingClientRect():{width:0,height:0,right:0};
 return {roofs:svg?svg.querySelectorAll('polygon[data-kind="roof"]').length:0,
         under:svg?svg.querySelectorAll('polygon[data-kind="underground"]').length:0,
         marks:svg?Array.from(svg.querySelectorAll('.site-massing-mark')).map(n=>n.textContent):[],
         legend:Array.from(document.querySelectorAll('.site-massing-legend li')).map(n=>n.innerText),
         width:r.width,height:r.height,right:r.right,
         page:document.documentElement.scrollWidth,view:window.innerWidth,
         m:((lastResult.tep||{}).site_massing||{}).scheme||null};
}"""

def _office_contour_merc():
    """Квадрат 0,243 га у Пролетарского проспекта — контур в веб-меркаторе."""
    lat, lng = 55.645, 37.665
    k = math.cos(math.radians(lat))
    y0 = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = lng * 20037508.34 / 180
    side = math.sqrt(2430.0)
    return [[x0 + a / k, y0 + b / k] for a, b in ((0, 0), (side, 0), (side, side), (0, side))]


CONTOUR = """async (ring)=>{
 const data={query:'77:05:0000000:1',results:[{found:true,kind:'land',cadastral_number:'77:05:0000000:1',contour_merc:[ring]}]};
 inputs._land_lookup=cloneValue(data); landLookup=cloneValue(data);
 await settledCalculate();
 openTab('tep'); renderTep();
 const button=document.getElementById('siteMassingMapButton');
 if(button)button.click();
 const corpora=Array.from(document.querySelectorAll('#landMapStage .land-map-corpus')).map(n=>n.dataset.building);
 const m=(lastResult.tep||{}).site_massing||{};
 return {button:!!button, corpora:corpora, levels:Array.from(document.querySelectorAll('#siteMassingScheme .site-massing-level')).map(n=>n.textContent),
         layout:(m.scheme||{}).layout||null};
}"""

SKIPPED = """()=>{
 renderSiteMassingScheme({scheme:{axonometry:{},layout:{skipped:'Схему не рисуем: корпусов получилось 72.',
  phase_lines:['Очередь 1: 18 корпусов по 4 этажа, пятно 31 140 м²','Очередь 2: 18 корпусов по 4 этажа, пятно 31 140 м²']}}});
 const box=document.getElementById('siteMassingScheme');
 return {svg:box.querySelectorAll('svg').length, text:box.innerText,
         lines:box.querySelectorAll('.site-massing-legend li').length};
}"""

STRIP = """()=>{delete lastResult.tep.site_massing.scheme; renderTep();
 return document.querySelectorAll('#siteMassingScheme svg').length;}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18184) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 390, "height": 844})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            page.fill("#f_offices_parking_under_spaces", "68")
            page.dispatch_event("#f_offices_parking_under_spaces", "change")
            browser.wait_for_result(page)
            out["example"] = page.evaluate(READ)
            out["map"] = page.evaluate(CONTOUR, _office_contour_merc())
            out["skipped"] = page.evaluate(SKIPPED)
            out["stripped"] = page.evaluate(STRIP)
    return out


def test_the_page_draws_the_engine_corpora(seen):
    got = seen["example"]
    scheme = got["m"]
    assert scheme, "движок не вернул объёмную схему"
    buildings = scheme["layout"]["buildings"]
    assert got["roofs"] == len(buildings) == 1
    assert got["marks"] == [str(b["number"]) for b in buildings]
    assert got["under"] >= 1, "подземный контур не нарисован"
    legend = [t.replace("\xa0", " ") for t in got["legend"]]
    sqm = [f"{round(b['area_sqm']):,}".replace(",", " ") for b in buildings]
    assert legend == [f"{b['number']} — {b['label']}, пятно {a} м²"
                      for b, a in zip(buildings, sqm)], legend
    assert "15 этажей" in legend[0]


def test_the_scheme_reads_on_a_phone(seen):
    got = seen["example"]
    assert 300 <= got["width"] <= 390 and got["height"] > 150, got
    assert got["right"] <= got["view"] and got["page"] <= got["view"], got


def test_the_counterfeit_draws_nothing(seen):
    assert seen["stripped"] == 0


def test_the_page_draws_the_underground_levels(seen):
    m = seen["example"]["m"]
    texts = [t["text"] for t in m["axonometry"]["texts"]]
    assert len(texts) == 2
    levels = seen["map"]["levels"]
    assert [t.replace("\xa0", " ") for t in levels] == texts, levels


def test_the_corpora_stand_on_the_land_map(seen):
    got = seen["map"]
    layout = got["layout"]
    assert layout and layout["site_shape_origin"] == "contour"
    assert got["button"], "кнопки «Показать корпуса на карте участка» нет"
    assert got["corpora"] == [str(b["number"]) for b in layout["buildings"]]


def test_the_page_says_why_there_is_no_scheme(seen):
    got = seen["skipped"]
    assert got["svg"] == 0 and got["lines"] == 2
    assert "Схему не рисуем" in got["text"] and "Очередь 2: 18 корпусов" in got["text"]
