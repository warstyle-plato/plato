"""Офис — одно здание, и пятно в ТЭП встаёт на участок схемы.

Случай владельца (25.10.2026, прод): участок 77:06:0003002:18, деловое
управление, 0,546 га, ТЭП от калькулятора ГлавАПУ (наземная площадь около
34 110 м²). Схема показывала один корпус и подпись «Здание: 3 корпуса по
9 этажей, пятно 3 790 м²; не поместились 2 из 3», а под ней — «Платон
предложил расстановку, но движок её не принял». Вопрос владельца: «Одно
здание и три корпуса — где тут?»

Решения владельца (AskUserQuestion, 25.10.2026):
- нежилой проект — одно здание, а не жилые секции 18 × 100 м;
- пятно, которое на участке не встаёт, расчёт сжимает до того, что встаёт,
  и поднимает этажность до предела; не встаёт и на пределе — говорит, сколько
  не хватает;
- о Платоне и «движке» посетителю под схемой не пишем.

На прежнем коде падает: здание режется на три корпуса, а на треугольном
участке пятно ТЭП больше суммы нарисованных корпусов.

Запуск: python3 -m pytest tests/test_an_office_is_one_building.py -q
"""

from __future__ import annotations

import copy
import io
import json
import math
import re
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402

import main as _wrapper  # noqa: E402

core = _wrapper.core

SITE_HA = 0.546
GNS = 34110.0


def _merc(shape, lat=55.70, lng=37.65):
    k = math.cos(math.radians(lat))
    y0 = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = lng * 20037508.34 / 180
    return [[x0 + a / k, y0 + b / k] for a, b in shape]


def _triangle():
    """Прямоугольный треугольник той же площади: квадрат 62 × 62 м в нём не встаёт."""
    leg = math.sqrt(2 * SITE_HA * 10000)
    return _merc([(0, 0), (leg, 0), (0, leg)])


def _office(contour=None, **extra):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind="nonresidential", project_class="business", site_area_ha=SITE_HA,
             project_region="msk", vri_region="msk", offices_enabled=True, offices_gba_sqm=GNS)
    if contour:
        x["_land_lookup"] = {"results": [{"found": True, "contour_merc": [contour]}]}
    x.update(extra)
    t = {"offices": {"gns": GNS, "total_area": GNS}}
    bundle = core._run_authoritative_model(x, t, [], {})
    return x, t, bundle, bundle["consolidated"]["tep"]["site_massing"]


def _kitchen(texts):
    return [t for t in texts if "Платон" in t or "движок" in t]


def test_the_office_of_the_owner_is_one_building_of_nine_storeys():
    _, _, _, m = _office()
    assert m["footprint_sqm"] == pytest.approx(3790, abs=1)
    buildings = m["scheme"]["layout"]["buildings"]
    assert len(buildings) == 1, [b["label"] for b in buildings]
    b = buildings[0]
    assert b["label"] == "Здание, 9 этажей" and b.get("ring_m"), b
    assert b["area_sqm"] == pytest.approx(m["footprint_sqm"], rel=1e-9)
    assert m["scheme"]["layout"]["unplaced_count"] == 0
    legend = [g["line"] for g in m["scheme"]["axonometry"]["legend"]]
    assert legend == ["1 — Здание, 9 этажей, пятно 3 790 м²"], legend
    assert not _kitchen(m["scheme"]["layout"]["notes"] + [m["scheme"]["axonometry"]["footer"]])


def test_a_housing_project_still_has_sections():
    """Контрпример: у жилья то же пятно по-прежнему — секции до 100 м длиной."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    layout = core.site_massing_layout(x, {"site_sqm": 20000.0, "footprint_sqm": 3790.0,
                                          "setback_m": 3.0},
                                      [{"phase": 1, "above_gns_sqm": 34110.0}])
    assert len(layout["buildings"]) == 3


def test_on_a_triangle_the_footprint_shrinks_and_the_storeys_rise():
    _, _, _, m = _office(_triangle())
    assert m["footprint_origin"] == "fit", m["footprint_origin"]
    assert 1000 < m["footprint_sqm"] < 3790
    assert m["average_storeys"] == pytest.approx(GNS / m["footprint_sqm"], rel=1e-9)
    assert m["average_storeys"] > 9
    layout = m["scheme"]["layout"]
    buildings = layout["buildings"]
    # Схема и ТЭП читают одно пятно: всё, что в расчёте, стоит на участке.
    assert len(buildings) == 1 and all(b.get("ring_m") for b in buildings)
    assert sum(b["area_sqm"] for b in buildings) == pytest.approx(m["footprint_sqm"], rel=1e-9)
    assert core.massing_check(buildings, layout["underground_rings"]) is None
    note = next(n for n in m["notes"] if "не встаёт" in n)
    shown = f"{round(m['footprint_sqm']):,}".replace(",", " ")
    assert "3 790 м²" in note and shown in note and "этажность выше" in note, note


def test_what_does_not_fit_at_the_limit_is_said_with_the_shortage():
    _, _, _, m = _office(_triangle(), max_storeys_allowed=9)
    assert m["footprint_origin"] == "limit"
    assert m["footprint_sqm"] == pytest.approx(GNS / 9, rel=1e-9)
    warning = next(w for w in m["warnings"] if "не помещается" in w)
    fit = f"{round(m['footprint_fit_sqm']):,}".replace(",", " ")
    lack = f"{round(GNS / 9 - m['footprint_fit_sqm']):,}".replace(",", " ")
    assert f"не больше {fit} м²" in warning and f"не хватает {lack} м²" in warning, warning
    assert "Даже на 9 этажах (предел участка)" in warning


def test_the_book_takes_the_fitted_footprint_like_the_engine():
    sys.setrecursionlimit(400000)
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t, bundle, m = _office(_triangle())
    assert m["footprint_origin"] == "fit"
    content, _, _ = core.build_project_workbook(
        x, t, [], None, project_name="Деловой центр",
        finance_hints=core._v4_finance_hints(bundle))
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    labels = {label: key for key, label, _ in core._massing_book.ROWS}
    cells = {}
    for name in ("Вводные", "ТЭП"):
        sheet = book[name]
        for row in range(1, sheet.max_row + 1):
            key = labels.get(str(sheet.cell(row, 1).value or ""))
            if key:
                cells[key] = (name, f"B{row}")
    evaluator = Evaluator(book)
    got = lambda key: float(evaluator.cell(*cells[key]) or 0)  # noqa: E731
    assert got("fit_sqm") == pytest.approx(m["footprint_fit_sqm"])
    assert got("footprint_sqm") == pytest.approx(m["footprint_sqm"], rel=1e-9)
    assert got("average_storeys") == pytest.approx(m["average_storeys"], rel=1e-9)
    assert got("footprint_shortage_sqm") == pytest.approx(m["footprint_shortage_sqm"], abs=1e-6)


# --- Отрисованная страница -------------------------------------------------

SETUP = """async ()=>{
 applyProjectKind('nonresidential'); closeProjectKindDialog(); await settledCalculate();
 setSiteArea(%s); setSiteDensity(%s/%s);
 applyDensityToObject('offices'); await settledCalculate();
}""" % (SITE_HA, GNS, SITE_HA)

CONTOUR = """async (ring)=>{
 const data={query:'77:06:0003002:18',results:[{found:true,kind:'land',cadastral_number:'77:06:0003002:18',contour_merc:[ring]}]};
 inputs._land_lookup=cloneValue(data); landLookup=cloneValue(data);
 await settledCalculate();
}"""

READ = """()=>{
 openTab('tep'); renderTep();
 const card=document.getElementById('siteMassingBody');
 const box=document.getElementById('siteMassingScheme');
 const svg=box&&box.querySelector('svg');
 const m=(lastResult.tep||{}).site_massing||{};
 return {roofs:svg?svg.querySelectorAll('polygon[data-kind="roof"]').length:0,
         legend:Array.from(document.querySelectorAll('.site-massing-legend li')).map(n=>n.innerText),
         card:card?card.innerText:'', scheme:box?box.innerText:'',
         footprint:m.footprint_sqm||0, storeys:m.average_storeys||0,
         drawn:(((m.scheme||{}).layout||{}).buildings||[]).filter(b=>b.ring_m)
               .reduce((s,b)=>s+b.area_sqm,0)};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18191) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            browser.wait_for_result(page)
            out["square"] = page.evaluate(READ)
            page.evaluate(CONTOUR, _triangle())
            browser.wait_for_result(page)
            out["triangle"] = page.evaluate(READ)
    return out


def test_the_page_shows_one_building_and_no_kitchen(seen):
    got = seen["square"]
    legend = [t.replace("\xa0", " ") for t in got["legend"]]
    assert got["roofs"] == 1 and legend == ["1 — Здание, 9 этажей, пятно 3 790 м²"], got
    text = got["card"] + got["scheme"]
    assert not re.search(r"\d корпус|корпус \d", text), text
    for words in ("не поместил", "Платон", "движок", "В расчёте они есть", "школы"):
        assert words not in text, (words, text)


def test_the_page_draws_what_the_tep_counts(seen):
    got = seen["triangle"]
    assert got["roofs"] == 1, got
    assert got["drawn"] == pytest.approx(got["footprint"], rel=1e-6), got
    assert got["storeys"] > 9
    card = got["card"].replace("\xa0", " ")
    assert "на участке не встаёт" in card and "этажность выше" in card, card
    assert "Платон" not in card and "движок" not in card


# --- Контур ЕГРН приходит после расчёта ---------------------------------------
# Замечание «Посадки» (25.10.2026, PR #918): после «Подставить в проект» схема
# рисовалась квадратом с подписью «контура из ЕГРН нет», хотя контур приходил
# через секунду, и настоящий появлялся только после любого пересчёта.

LATE = """async (ring)=>{
 const real=window.fetch;
 let release;
 const gate=new Promise(r=>{release=r});
 window.fetch=async (url,opts)=>{
  if(String(url).includes('/land/lookup')){
   await gate;
   const body={query:'77:06:0003002:18',found_count:1,
    results:[{found:true,kind:'land',cadastral_number:'77:06:0003002:18',contour_merc:[ring]}]};
   return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
  }
  return real(url,opts);
 };
 delete inputs._land_lookup; landLookup=null;
 const contour=drawLandPreviewQuiet('77:06:0003002:18');
 await settledCalculate();
 const m=(lastResult.tep||{}).site_massing||{};
 const before={origin:((m.scheme||{}).layout||{}).site_shape_origin,
               notes:((m.scheme||{}).layout||{}).notes||[]};
 release();
 await contour;
 return before;
}"""

SHAPE = """()=>{
 const m=(lastResult.tep||{}).site_massing||{};
 return {origin:((m.scheme||{}).layout||{}).site_shape_origin,
         notes:((m.scheme||{}).layout||{}).notes||[]};
}"""


@pytest.fixture(scope="module")
def late():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18192) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            browser.wait_for_result(page)
            out["before"] = page.evaluate(LATE, _merc([(0, 0), (74, 0), (74, 74), (0, 74)]))
            browser.wait_for_result(page)
            page.wait_for_function(
                "()=>((((lastResult||{}).tep||{}).site_massing||{}).scheme||{}).layout"
                "&&lastResult.tep.site_massing.scheme.layout.site_shape_origin==='contour'",
                timeout=20000)
            out["after"] = page.evaluate(SHAPE)
    return out


def test_while_the_contour_loads_the_scheme_says_so(late):
    got = late["before"]
    assert got["origin"] == "square", got
    text = " ".join(got["notes"])
    assert "ещё загружается" in text and "Контура участка из ЕГРН нет" not in text, text


def test_the_scheme_redraws_on_the_contour_by_itself(late):
    got = late["after"]
    assert got["origin"] == "contour", got
    assert not any("квадратом" in n for n in got["notes"]), got


# --- Форма здания по участку подбирает Платон --------------------------------
# Владелец (25.10.2026, AskUserQuestion): «если пятиугольный участок, наверняка
# есть возможность вместить не прямоугольник в одном углу» — форму подбирает
# Платон, движок проверяет. Пока плана нет, в расчёте пятно прямоугольника.

def _pentagon():
    """Контур 77:06:0003002:18, снятый со снимка карты владельца (≈ 5 460 м²)."""
    px = [(465, 1018), (492, 1045), (487, 1060), (531, 1084), (522, 1128), (466, 1185), (392, 1108)]
    pts = [(x * 100 / 152, -y * 100 / 152) for x, y in px]
    area = abs(core._ring_area([list(p) for p in pts]))
    k = math.sqrt(SITE_HA * 10000 / area)
    return _merc([(x * k, y * k) for x, y in pts], lat=55.69, lng=37.58)


@pytest.fixture
def plato(monkeypatch, tmp_path):
    monkeypatch.setenv("SITE_MASSING_PLATO", "1")
    monkeypatch.setattr(core, "_SITE_MASSING_PLAN_DIR", tmp_path)
    monkeypatch.setattr(core, "_plan_configured", lambda: True)
    # Ворота: тест может придержать ответ Платона, пока не снимет первый замер.
    state = {"answer": None, "briefs": [], "gate": threading.Event()}
    state["gate"].set()

    def fake(payload, budget_seconds=None):
        brief = json.loads(payload["input"][0]["content"].split("\n\n")[0])
        state["gate"].wait(60)
        state["briefs"].append(brief)
        return {"output_text": json.dumps(state["answer"](brief), ensure_ascii=False)}

    monkeypatch.setattr(core, "_openai_responses_request", fake)
    return state


def _wait_plans():
    for t in list(threading.enumerate()):
        if t.name.startswith("massing-plan-"):
            t.join(30)


def _by_the_site(brief):
    """Честный Платон: здание повторяет участок с отступом, срезанный до площади пятна."""
    [corpus] = brief["corpora"]
    inner = [list(p) for p in brief["site_inner_contour_m"][0]]
    inner = core.inset_ring(inner, 0.5)
    cx = sum(p[0] for p in inner) / len(inner)
    cy = sum(p[1] for p in inner) / len(inner)
    ring = core._clip_to_area(inner, corpus["footprint_sqm"], (cx, cy))
    return {"summary": "Здание повторяет форму участка.",
            "placements": [{"corpus": corpus["id"], "front": "", "offset_m": 0, "inset_m": 0,
                            "length_m": 0, "depth_m": 0, "ring_m": ring}]}


def test_without_plato_the_pentagon_gets_the_biggest_rectangle():
    _, _, _, m = _office(_pentagon())
    assert m["footprint_origin"] == "fit"
    assert 3000 < m["footprint_sqm"] < 3790
    assert "shape_plan" not in m
    assert not any("подбирает форму" in n for n in m["notes"])


def test_plato_fits_the_whole_footprint_by_the_shape_of_the_site(plato):
    plato["answer"] = _by_the_site
    _, _, _, first = _office(_pentagon())
    # План готовится: пока пятно прямоугольника, и посетитель знает, что оно временное.
    assert first["footprint_origin"] == "fit" and first["shape_plan"]["status"] == "pending"
    assert any("подбирает форму здания" in n for n in first["notes"])
    plan = first["scheme"]["layout"]["plan"]
    assert plan["status"] == "pending" and plan["key"] == first["shape_plan"]["key"]
    _wait_plans()
    [brief] = plato["briefs"]
    assert brief["corpora"][0]["free_shape"] is True
    assert brief["corpora"][0]["footprint_sqm"] == pytest.approx(3790, abs=1)
    _, _, _, m = _office(_pentagon())
    assert m["footprint_origin"] == "estimate", m["notes"]
    assert m["footprint_sqm"] == pytest.approx(3790, abs=1)
    assert m["average_storeys"] == pytest.approx(9.0, abs=0.01)
    layout = m["scheme"]["layout"]
    [b] = layout["buildings"]
    assert b["placement_origin"] == "plato" and len(b["ring_m"]) > 4
    assert abs(core._ring_area(b["ring_m"])) == pytest.approx(b["area_sqm"], rel=0.01)
    assert core.massing_check([b], layout["underground_rings"]) is None
    assert layout["plan"]["status"] == "ready"
    assert any("предложил помощник Платон" in n for n in layout["notes"])


def test_a_shape_outside_the_setback_keeps_the_rectangle(plato):
    def outside(brief):
        answer = _by_the_site(brief)
        ring = answer["placements"][0]["ring_m"]
        answer["placements"][0]["ring_m"] = [[x * 1.4, y * 1.4] for x, y in ring]
        return answer

    plato["answer"] = outside
    _office(_pentagon())
    _wait_plans()
    _, _, _, m = _office(_pentagon())
    assert m["footprint_origin"] == "fit" and "shape_plan" not in m
    plan = m["scheme"]["layout"]["plan"]
    assert plan.get("status") != "ready"
    text = " ".join(m["scheme"]["layout"]["notes"])
    assert "Платон" not in text


def test_a_housing_section_cannot_take_a_free_shape():
    corpus = {"id": "p1-1", "label": "Жилой дом, 17 этажей", "area_sqm": 1000.0, "phase": 1,
              "storeys_shown": 17}
    reason = core.massing_place_plan([corpus], [], [{"corpus": "p1-1", "ring_m": [[0, 0], [40, 0], [40, 25]]}])
    assert reason and "прямоугольник" in reason


PAGE_SHAPE = """()=>{
 const m=(lastResult.tep||{}).site_massing||{};
 const layout=(m.scheme||{}).layout||{};
 const box=document.getElementById('siteMassingScheme');
 openTab('tep'); renderTep();
 return {footprint:m.footprint_sqm||0, origin:m.footprint_origin||'',
         plan:(layout.plan||{}).status||'', points:((layout.buildings||[])[0]||{}).ring_m?
           layout.buildings[0].ring_m.length:0,
         roofs:box?box.querySelectorAll('polygon[data-kind="roof"]').length:0,
         card:(document.getElementById('siteMassingBody')||{}).innerText||''};
}"""


def test_the_page_waits_for_platos_shape_and_redraws(plato):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    plato["answer"] = _by_the_site
    plato["gate"].clear()
    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18193) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            browser.wait_for_result(page)
            page.evaluate(CONTOUR, _pentagon())
            browser.wait_for_result(page)
            first = page.evaluate(PAGE_SHAPE)
            plato["gate"].set()
            page.wait_for_function(
                "()=>(((lastResult||{}).tep||{}).site_massing||{}).footprint_origin==='estimate'",
                timeout=30000)
            browser.wait_for_result(page)
            later = page.evaluate(PAGE_SHAPE)
    assert first["origin"] == "fit" and first["plan"] == "pending", first
    assert "подбирает форму здания" in first["card"].replace("\xa0", " ")
    assert later["footprint"] == pytest.approx(3790, abs=1) and later["plan"] == "ready", later
    assert later["roofs"] == 1 and later["points"] > 4
    card = later["card"].replace("\xa0", " ")
    assert "не встаёт" not in card and "движок" not in card
