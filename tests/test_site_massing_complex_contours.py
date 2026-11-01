"""Посадка жилья на сложных контурах: разбор участка, дома из секций, варианты.

Жалоба владельца (31.10.2026): «посадка на сложных контурах реализована плохо,
аналитики нет, квадраты какие-то вписанные куском, без анализа реальных
посадок». Прежняя расстановка ставила плиты 18 × 100 м подряд от одного края:
на Г-образном участке все дома вставали в одно крыло, на КРТ из трёх участков
— на первый участок, а целый кусок сбоку оставался пустым.

Решение владельца (AskUserQuestion 31.10.2026): сложная посадка допустима,
пустого куска сбоку быть не должно; Платон выбирает из вариантов движка;
разрывы и проезды — допущения с подписью (`engine/site_massing_variants.py`,
`docs/site_massing.md`, `docs/site_massing_practice.md`).

Проверки падают на прежней расстановке: она остаётся вариантом «рядами вдоль
участка», и тесты меряют его теми же мерками.

Запуск: python3 -m pytest tests/test_site_massing_complex_contours.py -q
"""

from __future__ import annotations

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

LAT, LNG = 55.70, 37.60
K = math.cos(math.radians(LAT))
Y0 = math.log(math.tan((90 + LAT) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
X0 = LNG * 20037508.34 / 180

# Контуры в метрах на местности: x — на восток, y — на север.
L_SHAPE = [[(0, 0), (420, 0), (420, 140), (140, 140), (140, 380), (0, 380)]]
L_SMALL = [[(0, 0), (260, 0), (260, 80), (80, 80), (80, 240), (0, 240)]]
NOTCHED = [[(0, 0), (220, 0), (220, 70), (160, 70), (160, 110), (220, 110), (220, 180),
            (0, 180), (0, 120), (60, 120), (60, 60), (0, 60)]]
KRT_THREE = [[(0, 0), (150, 0), (150, 120), (0, 120)],
             [(150, -20), (330, -20), (330, 60), (150, 60)],
             [(160, 60), (260, 60), (240, 200), (170, 210)]]
ELONGATED = [[(0, 0), (420, 0), (420, 90), (0, 90)]]


def _merc(ring):
    return [[X0 + x / K, Y0 + y / K] for x, y in ring]


def _area(rings):
    return sum(abs(core._ring_area([list(p) for p in r])) for r in rings)


def _scheme(rings, gns_per_ha=28000.0, storeys=17.0):
    site = _area(rings)
    gns = site / 10000 * gns_per_ha
    fp = gns / storeys
    m = {"site_sqm": site, "footprint_sqm": fp, "setback_m": 3.0, "footprint_origin": "estimate",
         "objects": [], "underground_levels": 1,
         "underground_level_rows": [{"level": -1, "area_sqm": fp}],
         "underground_contour_sqm": site * 0.9, "underground_use_factor": 0.85}
    x = {"_land_lookup": {"results": [{"found": True, "contour_merc": [_merc(r)]} for r in rings]}}
    return core.site_massing_scheme(x, m, [{"phase": 1, "above_gns_sqm": gns}])


def _to_ground(layout, point):
    """Точка схемы → метры на местности (север вверху): схема повёрнута, а
    `layout.north` — север в её координатах."""
    nx, ny = layout["north"]
    return (point[0] * ny - point[1] * nx, point[0] * nx + point[1] * ny)


def _centres(layout, rings_m):
    """Середины домов в метрах исходного контура (сдвиг — центр рамки контура)."""
    pts = [p for r in rings_m for p in r]
    cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
    cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    out = []
    for b in layout["buildings"]:
        ring = b.get("ring_m")
        if not ring:
            continue
        mx = sum(p[0] for p in ring) / len(ring)
        my = sum(p[1] for p in ring) / len(ring)
        gx, gy = _to_ground(layout, (mx, my))
        out.append((gx + cx, gy + cy))
    return out


def _wings_with_houses(centres, corner=140):
    """Крылья Г-образного участка (внутренний угол в (corner, corner)), в
    которых есть дом."""
    up = any(x < corner and y > corner for x, y in centres)
    right = any(x > corner and y < corner for x, y in centres)
    return {"вертикальное": up, "горизонтальное": right}


# --- Движок -------------------------------------------------------------------

@pytest.mark.parametrize("rings, corner, density", [
    (L_SHAPE, 140, 28000.0), (L_SMALL, 80, 20000.0)])
def test_on_an_l_shaped_site_both_wings_get_houses_and_nothing_is_left_empty(rings, corner, density):
    scheme = _scheme(rings, gns_per_ha=density)
    layout = scheme["layout"]
    assert layout["unplaced_count"] == 0
    assert layout["plan"]["variant"] != "rows"
    wings = _wings_with_houses(_centres(layout, rings), corner)
    assert all(wings.values()), wings
    m = layout["plan"]["variants"][layout["plan"]["variant"]]
    assert m["empty_share"] <= core.LAYOUT_EMPTY_SHARE, m
    # Прежняя расстановка («рядами вдоль участка») — та, на которую жаловался
    # владелец: мерка её ловит — пустой кусок сбоку назван.
    old = layout["plan"]["variants"]["rows"]
    assert old["empty_share"] > core.LAYOUT_EMPTY_SHARE and old.get("empty_where"), old
    assert old["reach_m"] > m["reach_m"] + 30


def test_the_old_layout_left_a_wing_empty_and_the_check_sees_it():
    """Подделка: та же проверка крыльев на прежней расстановке падает."""
    scheme = _scheme(L_SMALL, gns_per_ha=20000.0)
    layout = scheme["layout"]
    corpora = [{k: v for k, v in b.items() if k not in ("ring_m", "block", "front", "shape", "place")}
               for b in layout["buildings"]]
    inner = layout["underground_rings"]
    axis = core.massing_strip_axis(inner)
    core.massing_place_engine(corpora, core.massing_blocks(inner, axis), axis)
    wings = _wings_with_houses(_centres({**layout, "buildings": corpora}, L_SMALL), 80)
    assert not all(wings.values()), wings


def test_each_parcel_of_a_three_parcel_krt_site_gets_a_house():
    scheme = _scheme(KRT_THREE)
    layout = scheme["layout"]
    assert layout["unplaced_count"] == 0
    centres = _centres(layout, KRT_THREE)
    for ring in KRT_THREE:
        poly = [list(p) for p in ring]
        assert any(core._inside(c, [poly]) for c in centres), (ring, centres)


def test_a_notched_site_is_split_into_parts_and_houses_stay_inside():
    scheme = _scheme(NOTCHED)
    layout = scheme["layout"]
    pv = layout["plan_view"]
    # Вырезы делят участок на части; разбор называет их.
    assert len(pv["blocks"]) >= 3
    assert any("делится на" in line for line in layout["analysis"])
    assert core.massing_check(layout["buildings"], layout["underground_rings"]) is None
    m = layout["plan"]["variants"][layout["plan"]["variant"]]
    assert m["unplaced"] == 0 and m["empty_share"] <= core.LAYOUT_EMPTY_SHARE, m


def test_houses_are_sections_and_corners_follow_the_contour():
    scheme = _scheme(NOTCHED)
    layout = scheme["layout"]
    for b in layout["buildings"]:
        sec = b["sections"]
        assert sec["count"] >= 1
        assert abs(core._ring_area(b["ring_m"])) == pytest.approx(b["area_sqm"], rel=0.01)
    corners = [b for b in layout["buildings"] if b["shape"] == "corner"]
    if corners:
        assert all(b["sections"]["corner"] == 1 and len(b["ring_m"]) == 6 for b in corners)
    text = " ".join(layout["analysis"])
    assert "секци" in text


def test_long_sides_facing_each_other_need_more_than_ends():
    """Разрыв: длинные стороны друг против друга — не меньше 20 м и 0,8 высоты;
    торцы — 12 м. Подделка: два 17-этажных дома в 15 м друг от друга."""
    def house(x0, y0, w, h, storeys=17):
        return {"ring_m": [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]],
                "depth_m": 18.0, "storeys_shown": storeys, "label": f"дом {x0}"}
    a = house(0, 0, 90, 18)
    b = house(0, 33, 90, 18)
    need, kind, have = core.massing_required_gap(a, b)
    assert kind == "длинные стороны" and have == pytest.approx(15.0)
    assert need == pytest.approx(0.8 * 17 * 3)
    gaps = core.massing_min_gaps([a, b])
    assert gaps["short"] and gaps["short"]["need_m"] == pytest.approx(40.8)
    c = house(102, 0, 90, 18)
    need, kind, have = core.massing_required_gap(a, c)
    assert kind == "торец" and need == core.LAYOUT_GAP_IN_ROW_M and have == pytest.approx(12.0)
    # В выбранной посадке разрывы соблюдены.
    for rings in (L_SHAPE, NOTCHED, KRT_THREE):
        layout = _scheme(rings)["layout"]
        assert core.massing_min_gaps(layout["buildings"])["short"] is None


def test_meridional_rows_run_north_south():
    layout = _scheme(ELONGATED, gns_per_ha=20000.0)["layout"]
    variants = layout["plan"]["variants"]
    assert "meridional" in variants
    if layout["plan"]["variant"] == "meridional":
        north = layout["north"]
        for b in layout["buildings"]:
            u = core._mv_long_axis(b["ring_m"])
            assert core._mv_meridian_deg(u, north) <= core.LAYOUT_MERIDIONAL_DEG


def test_without_a_map_contour_the_sides_of_the_world_are_not_guessed():
    site = 40000.0
    m = {"site_sqm": site, "footprint_sqm": 5000.0, "setback_m": 3.0, "footprint_origin": "estimate",
         "objects": [], "underground_levels": 0, "underground_level_rows": []}
    layout = core.site_massing_scheme({}, m, [{"phase": 1, "above_gns_sqm": 85000.0}])["layout"]
    assert layout["north"] is None
    assert "meridional" not in layout["plan"]["variants"]
    assert any("Стороны света на схеме неизвестны" in line for line in layout["analysis"])


def test_the_analysis_names_assumptions_not_norms():
    layout = _scheme(L_SHAPE)["layout"]
    text = " ".join(layout["analysis"])
    for words in ("допущение", "не норма", "СП 4.13130.2013", "а не расчёт инсоляции",
                  "Не проверяли: красные линии"):
        assert words in text, words


def test_the_brief_is_the_chosen_variant_the_houses_and_the_empty_piece():
    """Владелец 01.11.2026: «стоит там часть текста свернуть». Итог — те же
    фразы разбора, только выбор варианта, дома и пустой кусок; разбор частей,
    разрывы, проезды и допущения в итог не входят."""
    layout = _scheme(L_SHAPE)["layout"]
    brief, lines = layout["analysis_brief"], layout["analysis"]
    assert 2 <= len(brief) <= 4, brief
    assert all(t in lines for t in brief), brief
    assert brief[0].startswith("Выбрана застройка"), brief
    assert any(t.startswith("Жилых домов на схеме") for t in brief), brief
    assert any(t.startswith(("Дома разнесены по всему участку", "Кусок участка")) for t in brief), brief
    for words in ("Участок без отступов", "Разрывы между домами", "Пожарный проезд",
                  "Проезды — наше допущение", "Не проверяли", "По солнцу"):
        assert not any(t.startswith(words) for t in brief), words
        assert any(t.startswith(words) for t in lines), words


# --- Баланс земли и «ниже и плотнее» (владелец 31.10.2026: «почему столько
# пустого пространства остаётся») ------------------------------------------------

def _balanced(rings, gns_per_ha, storeys=17.0):
    site = _area(rings)
    gns = site / 10000 * gns_per_ha
    fp = gns / storeys
    yard = 0.12 * site
    drive = 0.15 * site
    setbacks = 0.04 * site
    m = {"site_sqm": site, "footprint_sqm": fp, "setback_m": 3.0, "footprint_origin": "estimate",
         "objects": [], "underground_levels": 0, "underground_level_rows": [],
         "residential_gns_sqm": gns, "above_gns_sqm": gns, "typical_storeys": storeys,
         "coverage_sqm": 0.3 * site, "built_sqm": fp, "yard_sqm": yard, "driveways_sqm": drive,
         "setbacks_sqm": setbacks, "surface_parking_sqm": 0.0}
    x = {"_land_lookup": {"results": [{"found": True, "contour_merc": [_merc(r)]} for r in rings]}}
    return x, m, [{"phase": 1, "above_gns_sqm": gns}]


def test_the_land_balance_names_what_the_empty_land_is():
    x, m, phases = _balanced(L_SHAPE, 15000.0)
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    b = layout["land_balance"]
    assert sum(r["sqm"] for r in b["rows"]) == pytest.approx(m["site_sqm"], abs=len(b["rows"]))
    free = [r for r in b["rows"] if r.get("free")]
    assert free and free[0]["sqm"] == b["free_sqm"] > 0.2 * m["site_sqm"]
    # Пятно упёрлось в процент застройки — разбор называет это и что поправить.
    m2 = {**m, "footprint_origin": "coverage", "coverage_pct": 30.0, "coverage_origin": "default"}
    lines = core.site_massing_scheme(x, m2, phases)["layout"]["analysis"]
    assert any(line.startswith("Свободно около") and "процент застройки 30 % (наше умолчание)" in line
               for line in lines), lines


def test_with_much_free_land_a_lower_denser_layout_is_offered():
    x, m, phases = _balanced(L_SHAPE, 15000.0)
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    offer = layout["denser"]
    assert offer, layout["land_balance"]
    assert offer["storeys"] < m["typical_storeys"] and offer["storeys"] in core.LAYOUT_DENSER_STOREYS
    assert offer["footprint_sqm"] > m["footprint_sqm"]
    assert offer["free_sqm_after"] < offer["free_sqm_now"]
    assert offer["plan_view"]["buildings"]
    assert "только если нажать кнопку" in offer["text"]


def test_a_tight_site_gets_no_denser_offer():
    """Подделка: свободной земли мало — предложения нет."""
    x, m, phases = _balanced(L_SHAPE, 15000.0)
    m["yard_sqm"] = m["site_sqm"] - m["built_sqm"] - m["driveways_sqm"] - m["setbacks_sqm"]
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    assert layout["land_balance"]["free_share"] < core.LAYOUT_FREE_SHARE_OFFER
    assert layout["denser"] is None
    assert not any(line.startswith("Свободно около") for line in layout["analysis"])


def test_the_land_map_draws_the_balance_areas_in_their_places():
    """Владелец 31.10.2026: «сможешь нарисовать, чем занята земля? Двор, дороги,
    парковки». Площади слоёв — те же, что в таблице баланса; двор — у домов,
    стоянки — дальше от домов, чем двор."""
    x, m, phases = _balanced(L_SHAPE, 15000.0)
    m["surface_parking_sqm"] = 0.03 * m["site_sqm"]
    layout = core.site_massing_scheme(x, m, phases)["layout"]
    pv = layout["plan_view"]
    legend = {r["key"]: r for r in pv["land_legend"]}
    assert {"road", "yard", "parking", "setback", "free"} <= set(legend), legend
    cell = 2 * max(2.0, math.sqrt(m["site_sqm"] / core.LAYOUT_LAND_CELLS)) ** 2
    for key in ("road", "yard", "parking"):
        assert legend[key]["drawn_sqm"] == pytest.approx(legend[key]["sqm"], abs=cell), legend[key]
    homes = [b["ring_m"] for b in layout["buildings"] if b.get("ring_m")]
    nx, ny = layout["north"]

    def back(p):  # вид сверху → координаты схемы
        return (p[0] * ny + p[1] * nx, -p[0] * nx + p[1] * ny)

    def mean_dist(key):
        rects = pv["land"][key]
        ds = []
        for r in rects:
            cx = sum(back(p)[0] for p in r) / 4
            cy = sum(back(p)[1] for p in r) / 4
            ds.append(min(core._mv_poly_dist([[cx, cy], [cx + 0.01, cy], [cx, cy + 0.01]], h)
                          for h in homes))
        return sum(ds) / len(ds)

    assert mean_dist("yard") < mean_dist("parking")
    assert mean_dist("yard") < mean_dist("free")


# --- Отрисованная страница -----------------------------------------------------

SETUP = """async ([ring, ha])=>{
 await settledCalculate();
 setSiteArea(ha); await settledCalculate();
 const data={query:'77:01:0000000:1',results:[{found:true,kind:'land',cadastral_number:'77:01:0000000:1',contour_merc:[ring]}]};
 inputs._land_lookup=cloneValue(data); landLookup=cloneValue(data);
 await settledCalculate();
}"""

READ = """()=>{
 openTab('tep'); renderTep();
 const box=document.getElementById('siteMassingAnalysis');
 if(!box)return {missing:true};
 const svg=box.querySelector('svg.site-massing-plan');
 const site=svg.querySelector('.pv-site').getBoundingClientRect();
 const houses=Array.from(svg.querySelectorAll('.pv-house')).map(p=>{const r=p.getBoundingClientRect();
   return [(r.left+r.right)/2-site.left,(r.top+r.bottom)/2-site.top]});
 const m=(lastResult.tep||{}).site_massing||{};
 const layout=((m.scheme||{}).layout)||{};
 const shown=n=>n.checkVisibility();
 const det=document.getElementById('siteMassingDetails');
 const fold={brief:Array.from(box.querySelectorAll('#siteMassingBrief li')).filter(shown).map(n=>n.innerText),
   shownItems:Array.from(box.querySelectorAll('li')).filter(shown).map(n=>n.innerText),
   open:det?det.open:null, summary:det?det.querySelector('summary').innerText:'',
   landShown:!!document.querySelector('#siteMassingLand')&&shown(document.querySelector('#siteMassingLand'))};
 if(det){det.querySelector('summary').click();
   fold.afterClick=Array.from(det.querySelectorAll('li')).filter(shown).map(n=>n.innerText);
   fold.landAfter=shown(document.querySelector('#siteMassingLand'));
   renderTep(); fold.keptOpen=document.getElementById('siteMassingDetails').open;}
 return {fold, houses, site:[site.width,site.height], north:!!svg.querySelector('.pv-north'),
         sections:svg.querySelectorAll('.pv-section').length, lanes:svg.querySelectorAll('.pv-lane').length,
         items:Array.from(box.querySelectorAll('li')).map(n=>n.innerText), text:box.innerText,
         placed:(layout.buildings||[]).filter(b=>b.ring_m).length,
         page:document.documentElement.scrollWidth, view:window.innerWidth,
         svgWidth:svg.getBoundingClientRect().width,
         denser:!!document.getElementById('siteMassingDenserButton'),
         offer:layout.denser?layout.denser.storeys:0, storeys:m.typical_storeys||0,
         built:m.built_sqm||0,
         land:Array.from(svg.querySelectorAll('.pv-land')).map(n=>n.getAttribute('data-land')),
         landLegend:Array.from(box.querySelectorAll('.site-massing-land-legend li')).map(n=>n.innerText),
         landRows:Array.from(document.querySelectorAll('#siteMassingLand tr')).map(n=>n.innerText)};
}"""

ASSUME = """async (driveways)=>{
 inputs.site_coverage_max_pct=90; markFieldManual('inputs.site_coverage_max_pct');
 inputs.site_driveways_pct=driveways; markFieldManual('inputs.site_driveways_pct');
 await settledCalculate();
 const m=(lastResult.tep||{}).site_massing||{};
 const l=(m.scheme||{}).layout||{};
 return {fp:m.footprint_sqm||0, storeys:m.average_storeys||0, origin:m.footprint_origin,
         drawn:(l.buildings||[]).filter(b=>b.ring_m).reduce((s,b)=>s+b.area_sqm,0)};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    ha = _area(L_SHAPE) / 10000
    with browser.serve(core.app, 18193) as base, sync_playwright() as pw, \
            pw.chromium.launch(executable_path=str(path)) as engine:
        for width in (390, 1280):
            page = engine.new_page(viewport={"width": width, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP, [_merc(L_SHAPE[0]), ha])
            browser.wait_for_result(page)
            out[width] = page.evaluate(READ)
            if width == 1280:
                out["assumption"] = (page.evaluate(ASSUME, 15), page.evaluate(ASSUME, 5))
            page.close()
    return out


@pytest.mark.parametrize("width", [390, 1280])
def test_the_page_shows_the_plan_from_above_with_both_wings_built(seen, width):
    got = seen[width]
    assert not got.get("missing"), got
    assert got["placed"] >= 2 and len(got["houses"]) == got["placed"], got
    assert got["north"], "нет стрелки на север"
    # Север вверху: вертикальное крыло — слева сверху, горизонтальное — справа снизу.
    w, h = got["site"]
    up = [c for c in got["houses"] if c[0] < w / 3 and c[1] < h * 0.63]
    right = [c for c in got["houses"] if c[0] > w / 3 and c[1] > h * 0.63]
    assert up and right, got["houses"]
    text = got["text"]
    assert "Разбор участка и посадки" in text
    assert any(i.startswith("Участок без отступов от границ делится на") for i in got["items"]), got["items"]
    assert any(i.startswith("Выбрана застройка") for i in got["items"]), got["items"]
    assert "движок" not in text
    assert got["page"] <= got["view"] and got["svgWidth"] <= width, got


@pytest.mark.parametrize("width", [390, 1280])
def test_the_page_folds_the_details_and_shows_the_brief(seen, width):
    """Сразу видны вид сверху и короткий итог; разбор частей участка, баланс
    земли, разрывы и проезды — под закрытым «Подробнее о разборе участка»."""
    fold = seen[width]["fold"]
    assert fold["open"] is False, fold
    assert fold["summary"] == "Подробнее о разборе участка", fold
    assert fold["brief"] and fold["brief"][0].startswith("Выбрана застройка"), fold
    analysis = [i for i in seen[width]["items"] if i not in seen[width]["landLegend"]]
    shown = [i for i in fold["shownItems"] if i not in seen[width]["landLegend"]]
    assert shown == fold["brief"] and len(shown) <= 4, shown
    for words in ("Участок без отступов", "Разрывы между домами", "Пожарный проезд", "Не проверяли"):
        assert not any(i.startswith(words) for i in shown), words
    assert not fold["landShown"], "баланс земли виден до раскрытия"
    # По щелчку раскрывается весь остальной разбор, и пересчёт его не сворачивает.
    assert set(fold["brief"]) | set(fold["afterClick"]) == set(analysis), fold
    assert any(i.startswith("Участок без отступов") for i in fold["afterClick"]), fold
    assert fold["landAfter"] and fold["keptOpen"], fold


def test_the_page_names_the_land_and_the_footprint_follows_the_assumptions(seen):
    """Владелец 31.10.2026: «меняю допущения, а пятно не меняется». Пятно —
    свободная земля: на отрисованной странице проезды меньше — пятно больше."""
    got = seen[1280]
    assert got["landRows"] and got["landRows"][0].startswith("Под домами"), got["landRows"]
    assert {"road", "yard", "setback"} <= set(got["land"]), got["land"]
    assert any(t.startswith("Двор у домов") and "м²" in t for t in got["landLegend"]), got["landLegend"]
    before, after = seen["assumption"]
    assert after["fp"] > before["fp"] + 100, (before, after)
    assert after["drawn"] > before["drawn"], (before, after)
    assert after["storeys"] < before["storeys"], (before, after)
