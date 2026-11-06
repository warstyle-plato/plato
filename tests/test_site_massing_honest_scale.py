"""Схема застройки в настоящем размере, подземные уровни под корпусами и итог пятен.

Жалоба владельца (23.10.2026, КРТ «Нагатино», телефон, вкладка «ТЭП»): корпуса на
схеме были «уменьшены в 3,7 раза», подземная часть — плашкой «−1: 55 160 м²» сбоку,
а сумма пятен не сводилась с балансом. Решения владельца:
- корпус на схеме не уменьшается никогда; что не встало — названо числом;
- подземные уровни — плитами, раздвинутыми по высоте, как раньше, но каждая плита
  лежит там, где этот уровень под участком: под корпусами и двором, без участков
  школы и сада (`massing_underground_plan`);
- офисы — 12 этажей, глубина корпуса 24 м;
- в карточке — «Всего под зданиями на участке» (`built_sqm`), тот же итог, что
  сумма корпусов на схеме.

Запуск: python3 -m pytest tests/test_site_massing_honest_scale.py -q
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser
from test_site_massing_strip_plan import _nagatino

import main as _wrapper

core = _wrapper.core


def _small_strip(share=0.45):
    """Та же полоса, что «Нагатино», но площадью 45 %: все корпуса не встают."""
    x, m, phases = _nagatino()
    rings = x["_land_lookup"]["results"]
    pts = [p for r in rings for p in r["contour_merc"][0]]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    k = math.sqrt(share)
    for r in rings:
        r["contour_merc"] = [[[cx + (p[0] - cx) * k, cy + (p[1] - cy) * k]
                              for p in r["contour_merc"][0]]]
    # Участки школы и сада — как у типовых зданий калькулятора (`site_objects`).
    m["objects"][0]["plot_sqm"] = 32.0 * 350
    m["objects"][1]["plot_sqm"] = 14.0 * 1000
    m = {**m, "site_sqm": m["site_sqm"] * share,
         "underground_levels": 2,
         "underground_level_rows": [{"level": -1, "area_sqm": 32000.0},
                                    {"level": -2, "area_sqm": 8000.0}],
         "underground_contour_sqm": m["site_sqm"] * share * 0.9}
    return x, m, phases


def _centre(ring):
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


def test_what_does_not_fit_is_named_and_the_rest_is_drawn_at_full_size():
    x, m, phases = _small_strip()
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    buildings = layout["buildings"]
    drawn = [b for b in buildings if b.get("ring_m")]
    missing = [b for b in buildings if not b.get("ring_m")]
    assert missing, "контрпример должен не помещаться целиком"
    assert layout["unplaced_count"] == len(missing)
    # Каждый нарисованный корпус — своей площади, внутри участка без отступов,
    # без наложений и не ближе 12 м к соседу.
    for b in drawn:
        assert abs(core._ring_area(b["ring_m"])) == pytest.approx(b["area_sqm"], rel=0.01)
    assert core.massing_check(drawn, layout["underground_rings"]) is None
    assert "schema_shrink" not in layout
    note = next(n for n in layout["notes"] if n.startswith("На участке встают"))
    assert f"встают {len(drawn)} из {len(buildings)} корпусов" in note
    assert "уменьшены" not in " ".join(layout["notes"])
    # Пропавший корпус назван в строке своей группы.
    ax = core.site_massing_axonometry(layout)
    assert any("не поместил" in g["line"] for g in ax["legend"])
    assert [s["kind"] for s in ax["shapes"]].count("roof") == len(drawn)


def test_the_underground_plates_lie_under_the_homes_and_not_under_the_school():
    x, m, phases = _small_strip()
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    plan = {r["level"]: r for r in layout["underground_plan"]}
    assert sorted(plan) == [-2, -1]
    for level, row in plan.items():
        # Плита — полезная площадь ÷ доля полезной части контура.
        assert row["contour_sqm"] == pytest.approx(row["area_sqm"] / m["underground_use_factor"],
                                                   rel=0.01)
        assert sum(abs(core._ring_area(r)) for r in row["rings"]) == pytest.approx(
            row["contour_sqm"], rel=0.001)
    # Нижний уровень — внутри верхнего.
    for ring in plan[-2]["rings"]:
        assert core._inside(_centre(ring), plan[-1]["rings"])
    drawn = [b for b in layout["buildings"] if b.get("ring_m")]
    homes = [b for b in drawn if b["phase"] > 0]
    under = sum(core._inside(_centre(b["ring_m"]), plan[-1]["rings"]) for b in homes)
    assert under >= 0.8 * len(homes), (under, len(homes))
    for b in drawn:
        if b.get("object") in ("school", "kindergarten"):
            assert not core._inside(_centre(b["ring_m"]), plan[-1]["rings"]), b["label"]
    # Плиты на картинке — те же контуры, не сжатые к центру участка.
    ax = core.site_massing_axonometry(layout)
    plates = [s for s in ax["shapes"] if s["kind"] == "underground_level" and s["level"] == -1]
    assert len(plates) == len(plan[-1]["rings"])
    total = sum(abs(core._ring_area(s["points"])) for s in plates)
    site = sum(abs(core._ring_area(s["points"])) for s in ax["shapes"] if s["kind"] == "site")
    site_sqm = sum(abs(core._ring_area(r)) for r in layout["site_rings"])
    assert total / site == pytest.approx(plan[-1]["contour_sqm"] / site_sqm, rel=0.01)
    assert {t["level"] for t in ax["texts"]} == {-1, -2}
    assert not any(n.startswith("Подземный уровень") for n in layout["notes"])


def test_a_level_that_does_not_fit_under_the_homes_is_named():
    x, m, phases = _small_strip()
    m["underground_level_rows"] = [{"level": -1, "area_sqm": 50000.0}]
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    [row] = layout["underground_plan"]
    assert row["contour_sqm"] < row["need_sqm"]
    note = next(n for n in layout["notes"] if n.startswith("Подземный уровень −1"))
    assert core._fmt_ru(row["contour_sqm"]) in note


def test_an_office_corpus_is_twenty_four_metres_deep():
    x, m, phases = _nagatino()
    m["objects"][2]["footprint_sqm"] = 15515.0
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    offices = [b for b in layout["buildings"] if b.get("object") == "offices"]
    assert len(offices) == math.ceil(15515 / (24 * 100)) == 7
    assert all(b["depth_m"] == 24.0 for b in offices)
    school = [b for b in layout["buildings"] if b.get("object") == "school"]
    assert all(b["depth_m"] == 18.0 for b in school)


def test_the_footprints_add_up_to_the_balance_of_the_saved_nagatino():
    """Эталон «Нагатино» 0.25.91: пятна корпусов схемы = «Всего под зданиями»,
    а он — пятно жилья плюс пятна отдельных зданий; участки сходятся с балансом."""
    saved = json.loads((ROOT / "tests" / "fixtures"
                        / "project_settings_nagatino_krt_0_25_91.json").read_text(encoding="utf-8"))
    inputs = {**copy.deepcopy(core.DEFAULT_INPUTS), **saved["inputs"]}
    tep = {k: v for k, v in saved["tep"].items() if isinstance(v, dict)}
    m = core.site_massing(inputs, tep)
    objects = {o["key"]: o for o in m["objects"]}
    assert objects["offices"]["storeys"] == 12
    assert objects["offices"]["footprint_sqm"] == pytest.approx(
        objects["offices"]["gns_sqm"] / 12)
    built = m["footprint_sqm"] + sum(o["footprint_sqm"] for o in m["objects"])
    assert m["built_sqm"] == pytest.approx(built)
    assert m["built_share"] == pytest.approx(built / m["site_sqm"])
    # Участок = участки отдельных зданий + жилая территория; жилая территория =
    # пятно + проезды + стоянки + отступы + земля у домов.
    assert m["objects_plot_sqm"] + m["residential_site_sqm"] == pytest.approx(m["site_sqm"])
    assert (m["footprint_sqm"] + m["driveways_sqm"] + m["surface_parking_sqm"]
            + m["residential_setbacks_sqm"] + m["yard_ground_sqm"]) == pytest.approx(
        m["residential_site_sqm"])
    scheme = core.site_massing_scheme(inputs, m, [{"phase": 1,
                                                   "above_gns_sqm": m["residential_gns_sqm"]}])
    assert sum(b["area_sqm"] for b in scheme["layout"]["buildings"]) == pytest.approx(
        m["built_sqm"], rel=1e-6)


# --- Страница ----------------------------------------------------------------

MEASURE = """(scheme)=>{
 openTab('tep');
 renderSiteMassingScheme({scheme});
 const svg=document.querySelector('#siteMassingScheme svg');
 const poly=el=>el.getAttribute('points').trim().split(/\\s+/).map(p=>p.split(',').map(Number));
 const area=pts=>Math.abs(pts.reduce((s,p,i)=>{const q=pts[(i+1)%pts.length];return s+p[0]*q[1]-q[0]*p[1]},0))/2;
 const storeys={};(scheme.layout.buildings||[]).forEach(b=>{storeys[b.number]=b.storeys_shown});
 const inner=Array.from(svg.querySelectorAll('polygon[data-kind="underground"]'));
 const sites=Array.from(svg.querySelectorAll('polygon[data-kind="site"]'));
 const pt=svg.createSVGPoint();
 const inside=(els,p)=>els.some(el=>{pt.x=p[0];pt.y=p[1];return el.isPointInFill(pt)});
 // Пол корпуса = крыша, опущенная на высоту (3 м на этаж в единицах схемы).
 const grounds=Array.from(svg.querySelectorAll('polygon[data-kind="roof"]')).map(el=>{
  const h=3*storeys[el.dataset.building];return poly(el).map(p=>[p[0],p[1]+h])});
 const cross=(a,b)=>{const pin=(p,ring)=>{let c=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){
   const [xi,yi]=ring[i],[xj,yj]=ring[j];if((yi>p[1])!==(yj>p[1])&&p[0]<(xj-xi)*(p[1]-yi)/(yj-yi)+xi)c=!c}return c};
  const ca=a.reduce((s,p)=>[s[0]+p[0]/a.length,s[1]+p[1]/a.length],[0,0]);
  const cb=b.reduce((s,p)=>[s[0]+p[0]/b.length,s[1]+p[1]/b.length],[0,0]);
  return a.some(p=>pin(p,b))||b.some(p=>pin(p,a))||pin(ca,b)||pin(cb,a)};
 let overlaps=0;for(let i=0;i<grounds.length;i++)for(let j=i+1;j<grounds.length;j++)if(cross(grounds[i],grounds[j]))overlaps++;
 return {siteArea:sites.reduce((s,el)=>s+area(poly(el)),0),
  groundAreas:grounds.map(area),
  // Угол корпуса стоит в 5 см от границы, а точки схемы округлены до сотых:
  // проверяем углы, сдвинутые к середине корпуса на 1 %.
  outside:grounds.filter(g=>{const c=g.reduce((s,p)=>[s[0]+p[0]/g.length,s[1]+p[1]/g.length],[0,0]);
   return !g.every(p=>inside(inner,[c[0]+(p[0]-c[0])*0.99,c[1]+(p[1]-c[1])*0.99]))}).length,
  overlaps,
  plates:svg.querySelectorAll('polygon[data-kind="underground_level"]').length,
  text:document.getElementById('siteMassingScheme').innerText};
}"""


@pytest.fixture(scope="module")
def measured():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    x, m, phases = _small_strip()
    scheme = core.site_massing_scheme(x, m, phases)
    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18189) as base, sync_playwright() as pw, \
            pw.chromium.launch(executable_path=str(path)) as engine:
        page = engine.new_page(viewport={"width": 390, "height": 900})
        page.goto(base, wait_until="domcontentloaded")
        browser.wait_for_result(page)
        got = page.evaluate(MEASURE, scheme)
        page.close()
    return scheme, got


def test_the_page_draws_corpora_at_full_size_inside_the_site_without_overlaps(measured):
    scheme, got = measured
    layout = scheme["layout"]
    drawn = sorted((b for b in layout["buildings"] if b.get("ring_m")),
                   key=lambda b: b["area_sqm"])
    site_sqm = sum(abs(core._ring_area(r)) for r in layout["site_rings"])
    # Изометрия сохраняет отношение площадей на земле: пол корпуса к участку на
    # отрисованной схеме — как пятно корпуса к участку (масштаб 1:1).
    got_ratios = sorted(a / got["siteArea"] for a in got["groundAreas"])
    want = [b["area_sqm"] / site_sqm for b in drawn]
    assert got_ratios == pytest.approx(want, rel=0.02)
    assert got["outside"] == 0
    assert got["overlaps"] == 0
    assert got["plates"] >= len(layout["underground_plan"])
    assert "не поместил" in got["text"]
    assert "уменьшены" not in got["text"]
