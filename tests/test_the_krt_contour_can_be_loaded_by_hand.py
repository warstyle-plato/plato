"""Контур КРТ, загруженный вручную: каталог координат МСК-77 или фото страницы.

Владелец (26.10.2026): когда полигона реестра и контура по решению нет или он
неверный, человек загружает контур сам; форматы (AskUserQuestion) — каталог
координат из приложения к решению о КРТ (МСК-77) и фото или скан страницы.
Фото таблицы координат даёт точный контур, фото одной схемы без координат —
только площадь из текста, и форма называется приблизительной. Ручной контур
сильнее автоматического, автоматический не теряется; убрать загруженный —
вернуться к найденному или к прежней площади.

Без сети и без tesseract: распознавание подменено ответом распознавателя.

Запуск: python3 -m pytest tests/test_the_krt_contour_can_be_loaded_by_hand.py -q
"""

from __future__ import annotations

import base64
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

import browser  # noqa: E402

import main as _wrapper  # noqa: E402
from auction_search import krt_manual_contour as manual  # noqa: E402
from market_search import krt_registry as registry_mod  # noqa: E402

core = _wrapper.core

# Каталог 110 × 70 м = 7 700 м² в МСК-77 (X — на север, Y — на восток), с
# пробелами в тысячах и запятой, как в приложении к решению.
CATALOG = """Каталог координат характерных точек границ территории
№ точки   X           Y
1         8 000,00    10 000,00
2         8 000,00    10 110,00
3         8 070,00    10 110,00
4         8 070,00    10 000,00
1         8 000,00    10 000,00
"""
KRT_SQM = 110 * 70


def _centre(rings):
    pts = [p for r in rings for p in r]
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def _ground(a, b):
    """Расстояние на эллипсоиде WGS 84 на сотне метров (радиусы кривизны)."""
    lat = math.radians((a[0] + b[0]) / 2)
    e2 = 0.00669437999014
    m = 6378137.0 * (1 - e2) / (1 - e2 * math.sin(lat) ** 2) ** 1.5
    n = 6378137.0 / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return math.hypot(math.radians(b[0] - a[0]) * m,
                      math.radians(b[1] - a[1]) * n * math.cos(lat))


def _haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")


# --- каталог и перевод ----------------------------------------------------------

def test_the_catalog_area_is_exact_in_its_own_plane():
    got = manual.from_catalog(CATALOG)
    assert got["status"] == "ready"
    assert got["area_sqm"] == KRT_SQM
    assert got["points"] == 4 and not got["approximate"]
    assert got["source"] == "контур загружен вручную: каталог координат МСК-77"


def test_msk77_lands_in_moscow_at_ground_scale():
    lat0, lon0 = manual.msk77_to_wgs84(manual.MSK77_FALSE_EASTING, manual.MSK77_FALSE_NORTHING)
    # Начало системы — 55°40′, 37°30′ на Бесселе; переход к WGS 84 сдвигает его
    # на десятки метров, но не на километры.
    assert _haversine((lat0, lon0), (manual.MSK77_LAT0, manual.MSK77_LON0)) < 300
    a = manual.msk77_to_wgs84(10_000.0, 8_000.0)
    b = manual.msk77_to_wgs84(10_100.0, 8_000.0)
    c = manual.msk77_to_wgs84(10_000.0, 8_100.0)
    assert _ground(a, b) == pytest.approx(100.0, abs=0.05)
    assert _ground(a, c) == pytest.approx(100.0, abs=0.05)
    assert b[1] > a[1] and c[0] > a[0], "Y — на восток, X — на север"


def test_swapped_x_and_y_are_caught_by_the_project_parcel():
    right = manual.from_catalog(CATALOG)
    point = _centre(right["rings_merc"])
    swapped = "\n".join(
        f"{n} {x} {y}" for n, x, y in (("1", "10 000,00", "8 000,00"), ("2", "10 110,00", "8 000,00"),
                                       ("3", "10 110,00", "8 070,00"), ("4", "10 000,00", "8 070,00")))
    got = manual.from_catalog(swapped, points_merc=[point])
    assert got["status"] == "ready" and got["area_sqm"] == KRT_SQM
    assert "X и Y стояли в обратном порядке" in got["source_note"]
    assert _centre(got["rings_merc"]) == pytest.approx(point, abs=1.0)
    far = manual.from_catalog(CATALOG, points_merc=[[point[0] + 50_000, point[1]]])
    assert "не накрывает участки проекта" in far["source_note"]


def test_text_without_points_says_what_to_paste():
    got = manual.from_catalog("Площадь территории 0,77 га")
    assert got["status"] == "failed" and got["area_sqm"] is None
    assert "каталог координат" in got["problem"]


# --- фото и скан -------------------------------------------------------------------

def _ocr(monkeypatch, text):
    import developaid_v2_upgrade

    monkeypatch.setattr(developaid_v2_upgrade, "_ocr_image", lambda data: text)


def test_a_photo_of_the_catalog_gives_the_exact_contour(monkeypatch):
    _ocr(monkeypatch, CATALOG)
    got = manual.recognise(b"\x89PNG fake", "page.png")
    assert got["status"] == "ready" and got["area_sqm"] == KRT_SQM and not got["approximate"]
    assert got["source"].endswith("распознан с фото")
    assert "сверьте площадь" in got["source_note"]


def test_a_photo_of_the_scheme_gives_only_the_area_and_says_so(monkeypatch):
    _ocr(monkeypatch, "Схема границ территории. Площадь территории — 0,77 га.")
    got = manual.recognise(b"\x89PNG fake", "scheme.jpg")
    assert got["status"] == "ready" and got["approximate"] is True
    assert got["area_sqm"] == KRT_SQM and got["rings_merc"] == []
    assert "форма участка приблизительная" in got["source"]
    assert "точно не привязать" in got["source_note"]


def test_a_photo_with_neither_names_why(monkeypatch):
    _ocr(monkeypatch, "Схема границ")
    got = manual.recognise(b"\x89PNG fake", "x.jpg")
    assert got["status"] == "failed"
    assert "ни таблицы координат, ни площади" in got["problem"]


# --- схема посадки ------------------------------------------------------------------

def _layout(krt_site):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["_land_lookup"] = {"results": []}
    x["_krt_site"] = krt_site
    return core.site_massing_layout(x, {"site_sqm": float(KRT_SQM), "footprint_sqm": 900.0,
                                        "setback_m": 3.0},
                                    [{"phase": 1, "above_gns_sqm": 9000.0}])


def test_the_hand_loaded_contour_wins_over_the_found_one():
    hand = manual.from_catalog(CATALOG)
    found = manual.from_catalog(CATALOG.replace("10 110,00", "10 300,00"))
    layout = _layout({"on": True, "status": "ready", "rings_merc": found["rings_merc"],
                      "area_sqm": 21000, "source": "официальный полигон реестра КРТ",
                      "manual": {k: hand[k] for k in ("rings_merc", "area_sqm", "source",
                                                      "approximate")}})
    assert layout["site_shape_origin"] == "contour"
    area = sum(abs(core._ring_area(r)) for r in layout["site_rings"])
    assert area == pytest.approx(KRT_SQM, rel=0.01)
    assert any("каталог координат МСК-77" in n for n in layout["notes"]), layout["notes"]


def test_an_area_only_upload_draws_an_approximate_square():
    layout = _layout({"on": True, "manual": {"rings_merc": [], "area_sqm": KRT_SQM,
                                             "approximate": True,
                                             "source": manual.SOURCE_PHOTO_AREA}})
    assert layout["site_shape_origin"] == "square"
    assert any("Форма участка на схеме приблизительная" in n for n in layout["notes"])


# --- отрисованная страница ------------------------------------------------------------

PROBE = """async (args)=>{
 const [parcel, catalog, mode]=args;
 inputs._land_lookup={query:'77:04:0001001:10',results:[{found:true,kind:'land',
  cadastral_number:'77:04:0001001:10',contour_merc:[parcel]}]};
 landLookup=cloneValue(inputs._land_lookup);
 setSiteArea(0.243); await settledCalculate();
 openTab('tep'); renderSitePanel();
 const visible=n=>!!n&&n.getBoundingClientRect().height>0;
 const read=()=>{
  const layout=((((lastResult||{}).tep||{}).site_massing||{}).scheme||{}).layout||{};
  let area=0; (layout.site_rings||[]).forEach(r=>{let s=0;for(let i=0;i<r.length;i++){const a=r[i],b=r[(i+1)%r.length];s+=a[0]*b[1]-b[0]*a[1]}area+=Math.abs(s/2)});
  const st=document.getElementById('siteKrtStatus');
  return {area:document.getElementById('siteAreaHa').value,
   source:document.getElementById('siteAreaSource').innerText,
   status:visible(st)?st.innerText:'', shape:layout.site_shape_origin||'', scheme_area:area,
   notes:(layout.notes||[]).join(' | '),
   manualStatus:(document.getElementById('siteKrtManualStatus')||{}).innerText||''};
 };
 const waitFor=async test=>{for(let i=0;i<300&&!test();i++)await new Promise(ok=>setTimeout(ok,100))};
 document.getElementById('siteKrtToggle').click();
 await waitFor(()=>(inputs._krt_site||{}).status!=='pending');
 const fold=document.getElementById('siteKrtManual');
 const out={foldVisible:visible(fold)};
 fold.open=true;
 if(mode==='catalog'){
  document.getElementById('siteKrtCatalog').value=catalog;
  Array.from(fold.querySelectorAll('button')).find(b=>b.textContent.includes('по координатам')).click();
 }else{
  Array.from(fold.querySelectorAll('button')).find(b=>b.textContent.includes('Распознать')).click();
 }
 await waitFor(()=>!!((inputs._krt_site||{}).manual)||/не загружен|не распознано/.test(document.getElementById('siteKrtManualStatus').innerText));
 await settledCalculate();
 out.loaded=read();
 const remove=Array.from(document.querySelectorAll('#siteKrtStatus button')).find(b=>b.textContent.includes('Убрать'));
 if(remove){remove.click(); await settledCalculate(); out.removed=read();}
 return out;
}"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory):
    pytest.importorskip("playwright.sync_api")
    from types import SimpleNamespace

    from fastapi import FastAPI
    from playwright.sync_api import sync_playwright

    import developaid_v2_upgrade
    from auction_search.api import install

    path = browser.chromium_or_skip()
    hand = manual.from_catalog(CATALOG)
    c = _centre(hand["rings_merc"])
    k = 1.0 / math.cos(math.radians(55.74))
    parcel = [[c[0] - 20 * k, c[1] - 20 * k], [c[0] + 20 * k, c[1] - 20 * k],
              [c[0] + 20 * k, c[1] + 20 * k], [c[0] - 20 * k, c[1] + 20 * k]]
    photo = tmp_path_factory.mktemp("photo") / "scheme.png"
    photo.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    out: dict = {}
    mp = pytest.MonkeyPatch()
    try:
        for port, mode in ((18233, "catalog"), (18234, "photo")):
            data_dir = tmp_path_factory.mktemp(mode)
            mp.setenv("DATA_DIR", str(data_dir))
            mp.delenv("CORE_API_URL", raising=False)
            mp.setattr(core, "_MO_CALC_API_URL", "")
            mp.setitem(sys.modules, "developaid_core", core)
            mp.setattr(developaid_v2_upgrade, "_ocr_image",
                       lambda data: "Схема границ. Площадь территории 0,77 га")
            reg = registry_mod.KrtRegistry(data_dir / "market", fetch=lambda url: b"[]")
            reg.map_path.parent.mkdir(parents=True, exist_ok=True)
            reg.map_path.write_text(json.dumps({
                "schema_version": registry_mod.MAP_CACHE_SCHEMA_VERSION,
                "retrieved_at": int(time.time()), "source": "map2025.json", "step_m": 40.0,
                "stale": False, "count": 0, "bbox_merc": [0, 0, 1, 1], "sites": []}),
                encoding="utf-8")
            app = FastAPI()
            app.state.market_discovery_service = SimpleNamespace(krt=reg)
            install(app)
            app.mount("/", core.app)
            with browser.serve(app, port) as base, sync_playwright() as pw, \
                    pw.chromium.launch(executable_path=str(path)) as engine:
                page = engine.new_page(viewport={"width": 390, "height": 844})
                page.goto(base, wait_until="domcontentloaded")
                browser.wait_for_result(page)
                if mode == "photo":
                    page.set_input_files("#siteKrtPhoto", str(photo))
                out[mode] = page.evaluate(PROBE, [parcel, CATALOG, mode])
                page.close()
    finally:
        mp.undo()
    return out


def test_the_catalog_typed_on_the_page_sets_the_area_and_the_scheme(seen):
    got = seen["catalog"]
    assert got["foldVisible"], got
    loaded = got["loaded"]
    assert float(loaded["area"]) == pytest.approx(0.77, abs=0.0001), loaded
    assert loaded["source"] == "контур загружен вручную: каталог координат МСК-77", loaded
    assert "Контур загружен вручную" in loaded["status"], loaded
    assert loaded["shape"] == "contour", loaded
    assert loaded["scheme_area"] == pytest.approx(KRT_SQM, rel=0.02), loaded


def test_removing_the_hand_contour_brings_back_the_previous_area(seen):
    removed = seen["catalog"]["removed"]
    assert float(removed["area"]) == pytest.approx(0.243), removed
    assert removed["source"] == "введена вручную", removed


def test_a_scheme_photo_sets_only_the_area_and_calls_the_shape_approximate(seen):
    loaded = seen["photo"]["loaded"]
    assert float(loaded["area"]) == pytest.approx(0.77, abs=0.0001), loaded
    assert "форма участка приблизительная" in loaded["source"], loaded
    assert "Площадь загружена вручную" in loaded["status"], loaded
    assert loaded["shape"] == "square", loaded
    assert "Форма участка на схеме приблизительная" in loaded["notes"], loaded
