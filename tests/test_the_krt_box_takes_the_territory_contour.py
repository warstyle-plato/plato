"""Галочка «Проект в КРТ»: площадь и схема посадки — по контуру территории КРТ.

Владелец (26.10.2026, «Пролетарская», офисы, Москва): «по КРТ 0,77 га», а
расчёт шёл по 2 430 м² — участкам ЕГРН по кадастровым номерам проекта. Контур
территории КРТ часто не совпадает с существующими участками, и ЕГРН даёт только
её часть: на 0,243 га подземка не помещалась, здание не вставало.

Решения:
- галочка на вкладке ТЭП (карточка «Участок и плотность»); включена — площадка
  КРТ опознаётся по участкам проекта, контур — официальный полигон файла карты
  реестра, иначе состав по проекту решения (один владелец —
  `krt_project_site.find_site`); площадь — площадь контура
  (`krt_contour_area_sqm`) с подписью источника;
- схема посадки рисует контур КРТ, а не участки ЕГРН;
- снятие галочки возвращает прежнюю площадь; контура нет — площадь прежняя,
  причина видна, площадку можно выбрать.

Без сети: файл карты реестра и перечни решений — сохранённые образцы на диске.
На прежнем коде падает: ни маршрута, ни галочки, ни чтения `_krt_site` схемой.

Запуск: python3 -m pytest tests/test_the_krt_box_takes_the_territory_contour.py -q
"""

from __future__ import annotations

import copy
import json
import math
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser

import main as _wrapper
from auction_search import krt_project_site
from market_search import krt_registry as registry_mod

core = _wrapper.core

LAT, LNG = 55.725, 37.66
_R = 6378137.0


def _merc(shape):
    """Метры на местности от точки (LAT, LNG) → веб-меркатор."""
    k = math.cos(math.radians(LAT))
    x0 = math.radians(LNG) * _R
    y0 = math.log(math.tan(math.pi / 4 + math.radians(LAT) / 2)) * _R
    return [[x0 + a / k, y0 + b / k] for a, b in shape]


def _rect(x0, y0, w, h):
    return _merc([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)])


# Территория КРТ 0,77 га (110 × 70 м) и участок проекта 2 430 м² внутри неё.
KRT_RING = _rect(0, 0, 110, 70)
PARCEL_RING = _rect(10, 10, 54, 45)
KRT_SQM = 110 * 70


def _registry(tmp_path, sites):
    reg = registry_mod.KrtRegistry(tmp_path, fetch=lambda url: b"[]")
    payload = {
        "schema_version": registry_mod.MAP_CACHE_SCHEMA_VERSION,
        "retrieved_at": int(time.time()), "source": "map2025.json", "step_m": 40.0,
        "stale": False, "count": len(sites), "bbox_merc": [0, 0, 1, 1], "sites": sites,
    }
    reg.map_path.parent.mkdir(parents=True, exist_ok=True)
    reg.map_path.write_text(json.dumps(payload), encoding="utf-8")
    return reg


SITE = {"slug": "proletarskaya", "name": "Пролетарская, вл. 1", "rings_merc": [KRT_RING],
        "centre_merc": KRT_RING[0], "area_ha": 0.77}
ELSEWHERE = {"slug": "elsewhere", "name": "Варшавское ш., вл. 37",
             "rings_merc": [_rect(5000, 5000, 100, 100)], "centre_merc": None}


def _no_decision(slug):
    return {"rings_merc": [], "problem": "в проекте решения нет кадастровых номеров участков"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")


# --- движок ---------------------------------------------------------------------

def test_the_contour_area_is_measured_on_the_ground_and_holes_are_cut():
    assert core.krt_contour_area_sqm([KRT_RING]) == pytest.approx(KRT_SQM, rel=0.002)
    hole = _rect(20, 20, 10, 10)
    assert core.krt_contour_area_sqm([KRT_RING, hole]) == pytest.approx(KRT_SQM - 100, rel=0.002)
    # Меркатор без поправки на широту дал бы втрое больше: это и проверяем.
    raw = abs(core._ring_area(KRT_RING))
    assert raw > 3 * KRT_SQM


def _layout(krt_site):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["_land_lookup"] = {"results": [{"found": True, "kind": "land",
                                      "cadastral_number": "77:04:0001001:10",
                                      "contour_merc": [PARCEL_RING]}]}
    if krt_site is not None:
        x["_krt_site"] = krt_site
    return core.site_massing_layout(x, {"site_sqm": float(KRT_SQM), "footprint_sqm": 900.0,
                                        "setback_m": 3.0},
                                    [{"phase": 1, "above_gns_sqm": 9000.0}])


def test_the_scheme_draws_the_krt_contour_when_the_box_is_on():
    on = _layout({"on": True, "rings_merc": [KRT_RING], "name": "Пролетарская",
                  "source": krt_project_site.SOURCE_MAP})
    assert on["site_shape_origin"] == "contour"
    area = sum(abs(core._ring_area(r)) for r in on["site_rings"])
    assert area == pytest.approx(KRT_SQM, rel=0.01)
    assert any("территории КРТ «Пролетарская»" in n for n in on["notes"]), on["notes"]
    # Галочка снята — контур КРТ не читается, схема по участку ЕГРН.
    off = _layout({"on": False, "rings_merc": [KRT_RING]})
    assert not any("территории КРТ" in n for n in off["notes"])
    # Участок ЕГРН (2 430 м²) не сходится с площадью расчёта — квадрат, не контур КРТ.
    assert off["site_shape_origin"] == "square"


# --- опознание площадки по сохранённым данным ------------------------------------

POINT = [sum(p[0] for p in PARCEL_RING) / 4, sum(p[1] for p in PARCEL_RING) / 4]


def test_the_site_is_found_by_the_project_parcel_inside_the_official_polygon(tmp_path):
    reg = _registry(tmp_path, [SITE, ELSEWHERE])
    data = krt_project_site.gather(reg, slug="", name="", numbers=["77:04:0001001:10"],
                                   points_merc=[POINT], decision_outline=_no_decision,
                                   area_sqm=core.krt_contour_area_sqm)
    assert data["status"] == "ready", data
    assert data["slug"] == "proletarskaya"
    assert data["source"] == "официальный полигон реестра КРТ"
    assert data["area_sqm"] == pytest.approx(KRT_SQM, rel=0.002)
    assert "официального полигона" in data["matched_by"]


def test_two_sites_are_offered_to_choose(tmp_path):
    twin = dict(SITE, slug="proletarskaya-2", name="Пролетарская, вл. 2")
    reg = _registry(tmp_path, [SITE, twin])
    data = krt_project_site.gather(reg, slug="", name="", numbers=[], points_merc=[POINT],
                                   decision_outline=_no_decision,
                                   area_sqm=core.krt_contour_area_sqm)
    assert data["status"] == "ambiguous"
    assert {c["slug"] for c in data["choices"]} == {"proletarskaya", "proletarskaya-2"}
    assert data["area_sqm"] is None


def test_an_unknown_site_names_why_and_gives_no_area(tmp_path):
    reg = _registry(tmp_path, [ELSEWHERE])
    data = krt_project_site.gather(reg, slug="", name="", numbers=["77:04:0001001:10"],
                                   points_merc=[POINT], decision_outline=_no_decision,
                                   area_sqm=core.krt_contour_area_sqm)
    assert data["status"] == "unknown"
    assert "не лежат внутри ни одной площадки" in data["problem"]
    assert data["area_sqm"] is None and data["rings_merc"] == []


def test_a_decision_site_is_found_by_its_list_and_signed_as_such(tmp_path):
    """Площадки нет в файле карты — номер проекта в собранном перечне решения."""
    reg = _registry(tmp_path, [ELSEWHERE])
    reg.outline_dir.mkdir(parents=True, exist_ok=True)
    outline = {"schema_version": 1, "slug": "decision-777",
               "decision": {"title": "Проект решения о КРТ «Пролетарская»"},
               "parcels": [{"cadastral_number": "77:04:0001001:10", "area_sqm": 2430}],
               "rings_merc": [KRT_RING], "problem": ""}
    (reg.outline_dir / "decision-777.json").write_text(json.dumps(outline), encoding="utf-8")
    data = krt_project_site.gather(reg, slug="", name="", numbers=["77:04:0001001:10"],
                                   points_merc=[], decision_outline=lambda slug: outline,
                                   area_sqm=core.krt_contour_area_sqm)
    assert data["status"] == "ready", data
    assert data["slug"] == "decision-777"
    assert data["source"] == "состав территории по проекту решения"


def test_a_picked_site_without_a_contour_says_why(tmp_path):
    reg = _registry(tmp_path, [ELSEWHERE])
    data = krt_project_site.gather(reg, slug="nowhere", name="Нигде", numbers=[],
                                   points_merc=[], decision_outline=_no_decision,
                                   area_sqm=core.krt_contour_area_sqm)
    assert data["status"] == "no_contour"
    assert "кадастровых номеров" in data["problem"]


def test_the_route_finders_share_one_owner():
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    body = source[source.index("def _krt_site_finder("):]
    body = body[: body.index("return find\n")]
    assert "krt_project_site.find_site" in body
    assert "map_lookup" not in body, "второй путь к контуру в маршрутах КРТ"
    route = source[source.index("async def krt_project_site_route("):]
    route = route[: route.index("\n    @app.")]
    # С Render — на ядро; тяжёлое — фоном, ответ с диска.
    assert '_core_api_url("/krt/project-site")' in route
    assert "krt_project_site.start(" in route and "krt_project_site.view" in route


# --- отрисованная страница --------------------------------------------------------

PROBE = """async (args)=>{
 const [parcel, mode]=args;
 inputs._land_lookup={query:'77:04:0001001:10',results:[{found:true,kind:'land',
  cadastral_number:'77:04:0001001:10',contour_merc:[parcel]}]};
 landLookup=cloneValue(inputs._land_lookup);
 setSiteArea(0.243); await settledCalculate();
 openTab('tep'); renderSitePanel();
 const toggle=document.getElementById('siteKrtToggle');
 const visible=n=>!!n&&n.getBoundingClientRect().height>0;
 const read=()=>{
  const layout=((((lastResult||{}).tep||{}).site_massing||{}).scheme||{}).layout||{};
  const rings=layout.site_rings||[];
  let area=0; rings.forEach(r=>{let s=0;for(let i=0;i<r.length;i++){const a=r[i],b=r[(i+1)%r.length];s+=a[0]*b[1]-b[0]*a[1]}area+=Math.abs(s/2)});
  const status=document.getElementById('siteKrtStatus');
  return {checked:toggle.checked, area:document.getElementById('siteAreaHa').value,
   source:document.getElementById('siteAreaSource').innerText,
   status:visible(status)?status.innerText:'', shape:layout.site_shape_origin||'',
   scheme_area:area, notes:(layout.notes||[]).join(' | ')};
 };
 const out={toggleVisible:visible(toggle)};
 toggle.click();
 for(let i=0;i<200&&((inputs._krt_site||{}).status==='pending');i++)await new Promise(ok=>setTimeout(ok,100));
 await settledCalculate();
 out.on=read();
 if(mode==='ready'){
  toggle.click(); await settledCalculate();
  out.off=read();
 }
 return out;
}"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory):
    pytest.importorskip("playwright.sync_api")
    from types import SimpleNamespace

    from fastapi import FastAPI
    from playwright.sync_api import sync_playwright

    from auction_search.api import install

    path = browser.chromium_or_skip()
    out: dict = {}
    mp = pytest.MonkeyPatch()
    try:
        for port, mode, sites in ((18231, "ready", [SITE, ELSEWHERE]),
                                  (18232, "unknown", [ELSEWHERE])):
            data_dir = tmp_path_factory.mktemp(mode)
            mp.setenv("DATA_DIR", str(data_dir))
            mp.delenv("CORE_API_URL", raising=False)
            mp.setattr(core, "_MO_CALC_API_URL", "")
            mp.setitem(sys.modules, "developaid_core", core)
            # Маршруты КРТ — своим приложением поверх страницы: на общем
            # `core.app` их нет (ставит `main_registry`), а образец реестра —
            # файл карты на диске, без сети.
            app = FastAPI()
            app.state.market_discovery_service = SimpleNamespace(
                krt=_registry(data_dir / "market", sites))
            install(app)
            app.mount("/", core.app)
            with browser.serve(app, port) as base, sync_playwright() as pw:
                with pw.chromium.launch(executable_path=str(path)) as engine:
                    page = engine.new_page(viewport={"width": 390, "height": 844})
                    page.goto(base, wait_until="domcontentloaded")
                    browser.wait_for_result(page)
                    out[mode] = page.evaluate(PROBE, [PARCEL_RING, mode])
                    page.close()
    finally:
        mp.undo()
    return out


def test_the_box_takes_the_area_and_the_scheme_from_the_krt_contour(seen):
    got = seen["ready"]
    assert got["toggleVisible"], got
    on = got["on"]
    assert on["checked"], on
    assert float(on["area"]) == pytest.approx(KRT_SQM / 10000, abs=0.0002), on
    assert "по контуру КРТ: официальный полигон реестра КРТ" in on["source"], on
    assert "Пролетарская, вл. 1" in on["status"], on
    assert on["shape"] == "contour", on
    assert on["scheme_area"] == pytest.approx(KRT_SQM, rel=0.02), on
    assert "территории КРТ" in on["notes"], on


def test_unchecking_brings_back_the_previous_area(seen):
    off = seen["ready"]["off"]
    assert not off["checked"]
    assert float(off["area"]) == pytest.approx(0.243), off
    assert off["source"] == "введена вручную", off
    assert "территории КРТ" not in off["notes"], off


def test_without_a_site_the_reason_is_shown_and_the_area_stays(seen):
    on = seen["unknown"]["on"]
    assert on["checked"], on
    assert float(on["area"]) == pytest.approx(0.243), on
    assert "Площадку КРТ проекта опознать не удалось" in on["status"], on
    assert "не лежат внутри ни одной площадки" in on["status"], on
    assert "Площадь участка осталась прежней" in on["status"], on
