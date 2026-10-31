"""Расстановка корпусов на полосе и план от Платона.

Жалоба владельца (23.10.2026, КРТ «Нагатино»): на длинной изогнутой полосе из
нескольких участков 24 корпуса стояли в одном углу, уменьшенные в 3,7 раза, с
наложенными номерами. Решение: полоса режется на кварталы, корпуса — секциями
по периметру квартала, очереди подряд вдоль полосы; расстановку предлагает
Платон фоном, движок проверяет и хранит план по отпечатку входов
(`engine/site_massing_blocks.py`, `engine/site_massing_plan.py`).

Модель в тестах — заглушка; сети нет.

Запуск: python3 -m pytest tests/test_site_massing_strip_plan.py -q
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser

import main as _wrapper

core = _wrapper.core


def _strip_merc():
    """Изогнутая лента ≈ 1,5 км × 80–150 м из трёх участков ЕГРН, как Нагатино."""
    lat, lng = 55.683, 37.640
    k = math.cos(math.radians(lat))
    y0 = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = lng * 20037508.34 / 180
    radius, span = 1300.0, 1500.0 / 1300.0

    def width(t):
        return 80 + 70 * math.sin(math.pi * t) ** 2

    def at(t, r):
        a = -span / 2 + span * t
        return r * math.cos(a), r * math.sin(a)

    rings = []
    cuts = [0.0, 0.3, 0.68, 1.0]
    for a, b in itertools.pairwise(cuts):
        ts = [a + (b - a) * i / 24 for i in range(25)]
        outer = [at(t, radius + width(t) / 2) for t in ts]
        inner = [at(t, radius - width(t) / 2) for t in reversed(ts)]
        rings.append([[x0 + px / k, y0 + py / k] for px, py in outer + inner])
    return rings, k


def _nagatino(storeys_phase_1=85000.0):
    """Сад 2 × 3 этажа, школа 4 × 4, офисы 9 × 12 (пятно 15 515 м²), четыре
    очереди по 2–3 корпуса по 17 этажей."""
    rings, k = _strip_merc()
    site = sum(abs(core._ring_area([[p[0] * k, p[1] * k] for p in r])) for r in rings)
    objects = [
        {"key": "kindergarten", "kind": "social", "label": "Детский сад", "footprint_sqm": 2600.0,
         "storeys": 3, "gns_sqm": 7800.0},
        {"key": "school", "kind": "social", "label": "Школа", "footprint_sqm": 6400.0,
         "storeys": 4, "gns_sqm": 25600.0},
        {"key": "offices", "kind": "other", "label": "Офисы", "footprint_sqm": 15515.0,
         "storeys": 12, "gns_sqm": 186180.0},
    ]
    phases = [{"phase": i, "above_gns_sqm": g}
              for i, g in enumerate((storeys_phase_1, 90000.0, 60000.0, 75000.0), 1)]
    m = {"site_sqm": site, "footprint_sqm": (sum(p["above_gns_sqm"] for p in phases) - storeys_phase_1
                                             + 85000.0) / 17,
         "setback_m": 3.0, "footprint_origin": "estimate", "objects": objects,
         "underground_levels": 1, "underground_level_rows": [{"level": -1, "area_sqm": 30000.0}],
         "underground_contour_sqm": site * 0.9, "underground_use_factor": 0.8}
    x = {"_land_lookup": {"results": [{"found": True, "contour_merc": [r]} for r in rings]}}
    return x, m, phases


def _wait_plan_threads():
    for t in list(threading.enumerate()):
        if t.name.startswith("massing-plan-"):
            t.join(30)


def test_on_a_curved_strip_no_corpus_is_shrunk_and_phases_run_along_it():
    x, m, phases = _nagatino()
    scheme = core.site_massing_scheme(x, m, phases)
    layout = scheme["layout"]
    buildings = layout["buildings"]
    assert len(buildings) >= 24
    assert layout["unplaced_count"] == 0
    assert not any("уменьшены" in n for n in layout["notes"])
    # Площадь каждого пятна — та, что в подписи; внутри участка без отступов,
    # без наложений и не ближе 12 м — общая проверка движка.
    for b in buildings:
        assert abs(core._ring_area(b["ring_m"])) == pytest.approx(b["area_sqm"], rel=0.01), b["label"]
        assert b["placement_origin"] == "engine"
    assert core.massing_check(buildings, layout["underground_rings"]) is None
    # Корпуса стоят по многим кварталам, а не в одном углу.
    assert len({b["block"] for b in buildings}) >= 5
    # Очереди подряд вдоль оси полосы: середины очередей идут по порядку.
    axis = core.massing_strip_axis(layout["underground_rings"])
    ux, uy = math.cos(axis["angle"]), math.sin(axis["angle"])

    def along(b):
        ring = b["ring_m"]
        return sum(p[0] * ux + p[1] * uy for p in ring) / len(ring)

    means = [sum(along(b) for b in buildings if b["phase"] == p)
             / sum(1 for b in buildings if b["phase"] == p) for p in (1, 2, 3, 4)]
    assert means == sorted(means) or means == sorted(means, reverse=True), means
    # Номера на крышах (по одному на группу) не налезают друг на друга.
    ax = scheme["axonometry"]
    r = ax["label_radius"]
    labels = ax["labels"]
    assert len(labels) == len({b["number"] for b in buildings})
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            assert math.hypot(a["x"] - b["x"], a["y"] - b["y"]) >= 2 * r, (a, b)


# --- План Платона: заглушка модели ------------------------------------------

@pytest.fixture
def plato(monkeypatch, tmp_path):
    """Платон включён, ответ — из `answers` (функция от брифа)."""
    monkeypatch.setenv("SITE_MASSING_PLATO", "1")
    monkeypatch.setattr(core, "_SITE_MASSING_PLAN_DIR", tmp_path)
    monkeypatch.setattr(core, "_plan_configured", lambda: True)
    calls = []
    state = {"answer": None}

    def fake(payload, budget_seconds=None):
        brief = json.loads(payload["input"][0]["content"].split("\n\n")[0])
        calls.append(payload)
        return {"output_text": json.dumps(state["answer"](brief), ensure_ascii=False)}

    monkeypatch.setattr(core, "_openai_responses_request", fake)
    return state, calls


def _echo(brief):
    """Честный ответ: вариант, где встали все дома, и не тот, что выбрал бы
    движок (если такой есть), — так видно, чей выбор на схеме."""
    best = min(v["houses_not_placed"] for v in brief["variants"])
    fit = [v["id"] for v in brief["variants"] if v["houses_not_placed"] == best]
    other = [v for v in fit if v != brief["engine_choice"]]
    return {"variant": (other or fit)[0],
            "summary": "Очереди идут вдоль полосы, дворы закрыты домами."}


def _l_site():
    """Г-образный участок 9,2 га, жильё 28 000 м²/га, 17 этажей: у него
    несколько вариантов, где встают все дома."""
    lat = 55.70
    k = math.cos(math.radians(lat))
    y0 = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    x0 = 37.60 * 20037508.34 / 180
    ring = [(0, 0), (420, 0), (420, 140), (140, 140), (140, 380), (0, 380)]
    site = abs(core._ring_area([list(p) for p in ring]))
    gns = site / 10000 * 28000
    m = {"site_sqm": site, "footprint_sqm": gns / 17, "setback_m": 3.0, "footprint_origin": "estimate",
         "objects": [], "underground_levels": 1,
         "underground_level_rows": [{"level": -1, "area_sqm": gns / 17}],
         "underground_contour_sqm": site * 0.9, "underground_use_factor": 0.85}
    x = {"_land_lookup": {"results": [{"found": True, "contour_merc": [
        [[x0 + px / k, y0 + py / k] for px, py in ring]]}]}}
    return x, m, [{"phase": 1, "above_gns_sqm": gns}]


def _ask(x, m, phases):
    first = core.site_massing_scheme(x, m, phases)
    _wait_plan_threads()
    return first, core.site_massing_scheme(x, m, phases)


def test_plato_chooses_one_of_the_engine_variants_and_it_is_drawn(plato):
    """Решение владельца 31.10.2026: жильё сажает движок вариантами, Платон
    выбирает вариант и объясняет выбор; корпуса сам он не ставит."""
    state, calls = plato
    state["answer"] = _echo
    x, m, phases = _l_site()
    first, second = _ask(x, m, phases)
    # Пока выбора нет — вариант движка и фраза «готовится»; расчёт не ждёт.
    assert first["layout"]["plan"]["status"] == "pending"
    engine_pick = first["layout"]["plan"]["variant"]
    # Внутренняя кухня (готовится, не принят) посетителю не видна (владелец 25.10.2026).
    assert not any("Платон" in n or "движок" in n for n in first["layout"]["notes"])
    brief = json.loads(calls[0]["input"][0]["content"])
    assert {v["id"] for v in brief["variants"]} >= {"perimeter", "meridional", "mixed", "rows"}
    assert brief["engine_choice"] == engine_pick
    assert brief["site"]["parts"], brief["site"]
    plan = second["layout"]["plan"]
    assert plan["status"] == "ready" and plan["origin"] == "plato", plan
    assert plan["variant"] != engine_pick and plan["variant"] == _echo(brief)["variant"]
    assert all(b["placement_origin"] == "plato" for b in second["layout"]["buildings"])
    assert any("выбрал помощник Платон" in n for n in second["layout"]["notes"])
    assert "дворы закрыты домами" in plan["note"]
    assert second["axonometry"]["footer"].startswith("Вариант посадки выбрал помощник Платон")
    assert core.massing_check(second["layout"]["buildings"], second["layout"]["underground_rings"]) is None
    # Один запрос на одни входы: повторный расчёт читает выбор с диска.
    core.site_massing_scheme(x, m, phases)
    assert len(calls) == 1
    assert core.site_massing_plan_status(plan["key"])["status"] == "ready"


def _missing(brief):
    return {"variant": "towers", "summary": "Башни."}


def _fewer_houses(brief):
    worst = max(brief["variants"], key=lambda v: v["houses_not_placed"])
    assert worst["houses_not_placed"] > 0
    return {"variant": worst["id"], "summary": "Ряды."}


def _not_a_name(brief):
    return {"variant": 5, "summary": ""}


@pytest.mark.parametrize("fake, words", [
    (_missing, "которого нет"),
    (_fewer_houses, "встаёт меньше домов"),
    (_not_a_name, "которого нет"),
])
def test_a_forged_choice_is_rejected_with_its_reason(plato, fake, words):
    state, calls = plato
    state["answer"] = fake
    x, m, phases = _nagatino()
    _, second = _ask(x, m, phases)
    plan = second["layout"]["plan"]
    assert plan["status"] == "rejected", plan
    assert words in plan["reason"], plan["reason"]
    # Причина — в ответе для команды, посетителю о ней не пишем (владелец 25.10.2026).
    assert not any(words in n or "не принял" in n or "движок" in n
                   for n in second["layout"]["notes"])
    assert all(b["placement_origin"] == "engine" for b in second["layout"]["buildings"])
    assert core.massing_check(second["layout"]["buildings"], second["layout"]["underground_rings"]) is None
    # Вторая попытка — с причиной отказа.
    assert len(calls) == 2 and "не прошёл проверку движка" in calls[1]["input"][0]["content"]


def test_a_plan_for_other_inputs_is_not_shown_as_fresh(plato):
    state, _ = plato
    state["answer"] = _echo
    x, m, phases = _nagatino()
    _, ready = _ask(x, m, phases)
    assert ready["layout"]["plan"]["status"] == "ready"
    # Поменяли площадь и этажность первой очереди — план прежних входов устарел.
    x2, m2, phases2 = _nagatino(storeys_phase_1=70000.0)
    state["answer"] = lambda brief: (_ for _ in ()).throw(RuntimeError("модель молчит"))
    later = core.site_massing_scheme(x2, m2, phases2)
    plan = later["layout"]["plan"]
    assert plan["key"] != ready["layout"]["plan"]["key"]
    assert plan["status"] == "pending" and plan["stale"] is True
    assert not any("устарел" in n for n in later["layout"]["notes"])
    assert all(b["placement_origin"] == "engine" for b in later["layout"]["buildings"])
    _wait_plan_threads()
    failed = core.site_massing_scheme(x2, m2, phases2)["layout"]["plan"]
    assert failed["status"] == "failed" and "модель молчит" in failed["reason"]
    assert failed["note"] == ""


def test_without_plato_the_visitor_reads_no_kitchen():
    """Платон выключен — схема молчит о нём и о «движке» (владелец 25.10.2026)."""
    x, m, phases = _nagatino()
    scheme = core.site_massing_scheme(x, m, phases)
    plan = scheme["layout"]["plan"]
    assert plan["status"] == "off" and plan["origin"] == "engine"
    assert plan["note"] == ""
    seen = " ".join(scheme["layout"]["notes"]) + scheme["axonometry"]["footer"]
    assert "Платон" not in seen and "движок" not in seen


def test_the_pdf_draws_the_same_strip_scheme():
    x, m, phases = _nagatino()
    scheme = core.site_massing_scheme(x, m, phases)
    parts = core._site_massing_scheme_pdf(scheme, lambda text, style=None: text, None,
                                          lambda items: items, 1.0)
    items = parts[0]
    drawing = items[1]
    polygons = [c for c in drawing.contents if type(c).__name__ == "Polygon"]
    assert len(polygons) == len(scheme["axonometry"]["shapes"])
    # Пояснения схемы — те же строки, что на странице (Платон выключен — их может не быть).
    assert all(n in items for n in scheme["layout"]["notes"])
    assert scheme["axonometry"]["footer"] in items
    lines = [g["line"] for g in scheme["axonometry"]["legend"]]
    assert all(line in items for line in lines)
    # Разбор участка и вид сверху — тот же ответ движка, что на странице.
    analysis = parts[1]
    assert analysis[0] == "Разбор участка и посадки"
    assert all(line in analysis for line in scheme["layout"]["analysis"])
    plan = analysis[1]
    houses = [c for c in plan.contents if type(c).__name__ == "Polygon"]
    assert len(houses) >= len(scheme["layout"]["plan_view"]["buildings"])


# --- Страница: снимок на ширине телефона и планшета --------------------------

DRAW = """(scheme)=>{
 openTab('tep');
 renderSiteMassingScheme({scheme});
 const box=document.getElementById('siteMassingScheme');
 const svg=box.querySelector('svg');
 const r=svg.getBoundingClientRect();
 const marks=Array.from(svg.querySelectorAll('.site-massing-mark circle')).map(c=>{const b=c.getBoundingClientRect();return [b.left,b.top,b.right,b.bottom]});
 return {width:r.width,height:r.height,roofs:svg.querySelectorAll('polygon[data-kind="roof"]').length,
         marks, page:document.documentElement.scrollWidth, view:window.innerWidth,
         text:box.innerText};
}"""


@pytest.fixture(scope="module")
def drawn():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    x, m, phases = _nagatino()
    scheme = core.site_massing_scheme(x, m, phases)
    path = browser.chromium_or_skip()
    out: dict = {"scheme": scheme}
    with browser.serve(core.app, 18187) as base, sync_playwright() as pw, \
            pw.chromium.launch(executable_path=str(path)) as engine:
        for width in (390, 760):
            page = engine.new_page(viewport={"width": width, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            out[width] = page.evaluate(DRAW, scheme)
            page.close()
    return out


@pytest.mark.parametrize("width", [390, 760])
def test_the_page_draws_the_strip_and_numbers_do_not_overlap(drawn, width):
    got = drawn[width]
    scheme = drawn["scheme"]
    assert got["roofs"] == len(scheme["layout"]["buildings"])
    assert got["width"] <= width and got["page"] <= got["view"], got
    marks = got["marks"]
    assert len(marks) == len(scheme["axonometry"]["labels"])
    for i, a in enumerate(marks):
        for b in marks[i + 1:]:
            apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
            assert apart, (a, b)
    assert "Корпуса расставлены для наглядности" in got["text"]
    assert "движок" not in got["text"] and "Платон" not in got["text"]
