"""Контур КРТ с картинки решения без координат: обводка Платона + привязка.

Владелец (27.10.2026, «Пролетарский пр-т, вл. 20», ЮАО): загрузил Приложение 1
к решению — граница синей линией на спутниковом снимке, «площадью 0,77 га»,
таблицы координат нет — и получил квадрат без карты корпусов. Решение владельца
(AskUserQuestion): «Форма с картинки + привязка» — Платон обводит контур,
движок масштабирует его до площади из текста и ставит на карту по участкам
проекта и улицам снимка; везде пометка «границы приблизительные» с погрешностью.
Каталог координат по-прежнему сильнее фото.

Модель подменена ответом с обводкой образца владельца
(`tests/fixtures/krt_proletarsky_20_scheme_photo.jpg`); проверка обводки по
линии на картинке — настоящая.

Запуск: python3 -m pytest tests/test_krt_outline_from_scheme_photo.py -q
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

import browser  # noqa: E402

import main as _wrapper  # noqa: E402
import plato_provider  # noqa: E402
from auction_search import krt_manual_contour as manual  # noqa: E402
from auction_search import krt_photo_outline as outline  # noqa: E402
from market_search import krt_registry as registry_mod  # noqa: E402

core = _wrapper.core

PHOTO = ROOT / "tests" / "fixtures" / "krt_proletarsky_20_scheme_photo.jpg"
KRT_SQM = 7700.0
LEGEND = ("Условные обозначения: Границы территории нежилой застройки города Москвы, "
          "подлежащей комплексному развитию, площадью 0,77 га.")
# Углы синей линии на образце (картинка 1320 × 1714 px), снятые глазами; модели
# картинка уходит уменьшенной до `MAX_SIDE_PX`, ответ — в её пикселях.
CORNERS_PX = [[535, 769], [611, 912], [520, 963], [472, 806]]
STREETS_PX = [("Пролетарский пр-т", [[540, 700], [700, 1000]]),
              ("Кавказский б-р", [[1100, 1460], [1240, 1330]])]
ADDRESS = "г. Москва, Пролетарский пр-т, вл. 20"
# Найденный участок площадки «Пролетарский пр-т, вл. 20» — 1 563,8 м², часть
# территории (Царицыно, 55,62° с. ш.).
LAT, LON = 55.6215, 37.6735


def _merc(lat, lon):
    return [math.radians(lon) * 6378137.0,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137.0]


def _parcel():
    x, y = _merc(LAT, LON)
    k = math.cos(math.radians(LAT))
    return [[x + dx / k, y + dy / k] for dx, dy in ((0, 0), (40.1, 0), (40.1, 39.0), (0, 39.0))]


def _model_answer(scale, corners=CORNERS_PX, found=True):
    return {"found": found, "problem": "" if found else "линии границы не видно",
            "outline_px": [[x * scale, y * scale] for x, y in corners],
            "line_rgb": [90, 152, 188], "north_deg": 0, "area_text": "площадью 0,77 га",
            "streets": [{"name": n, "points_px": [[x * scale, y * scale] for x, y in pts]}
                        for n, pts in STREETS_PX]}


def _scale():
    return outline.MAX_SIDE_PX / 1714


def _fake_ask(corners=CORNERS_PX, calls=None):
    def ask(payload):
        if calls is not None:
            calls.append(payload)
        image = payload["input"][0]["content"][1]
        assert image["type"] == "input_image" and image["image_url"].startswith("data:image/jpeg")
        return json.dumps(_model_answer(_scale(), corners), ensure_ascii=False)
    return ask


def _ocr(monkeypatch, text):
    import developaid_v2_upgrade

    monkeypatch.setattr(developaid_v2_upgrade, "_ocr_image", lambda data: text)


def _area_m(ring_merc):
    k = math.cos(math.radians(LAT))
    pts = [[p[0] * k, p[1] * k] for p in ring_merc]
    return abs(outline._ring_area(pts))


def _inside(point, ring):
    return bool(outline._inside_many(__import__("numpy").array([point[0]]),
                                     __import__("numpy").array([point[1]]), ring)[0])


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")


# --- обводка и проверка движком ----------------------------------------------------------

def test_the_engine_accepts_the_outline_lying_on_the_blue_line():
    _jpeg, pixels = outline.prepare_image(PHOTO.read_bytes())
    ring, problem = outline.check_outline(_model_answer(_scale()), pixels)
    assert problem == "" and len(ring) == 4


def test_the_engine_rejects_an_outline_that_is_not_on_the_line():
    # Контрпример: модель «обвела» квадрат рядом — на линии его периметра нет.
    _jpeg, pixels = outline.prepare_image(PHOTO.read_bytes())
    moved = [[x - 160, y + 300] for x, y in CORNERS_PX]
    ring, problem = outline.check_outline(_model_answer(_scale(), moved), pixels)
    assert ring == [] and ("не совпала с линией границы" in problem
                           or "не выделяется на картинке" in problem), problem
    _r, problem = outline.check_outline(_model_answer(_scale(), found=False), pixels)
    assert "не нашёл на картинке линию границы" in problem


def test_the_shape_is_scaled_to_the_area_from_the_text():
    shape, k, _c = outline.shape_metres([[x * 0.9, y * 0.9] for x, y in CORNERS_PX], KRT_SQM)
    assert abs(outline._ring_area(shape)) == pytest.approx(KRT_SQM, rel=1e-9)
    assert 0.5 < k < 1.2, "около метра на пиксель картинки 0,77 га"


def test_the_shape_is_placed_over_the_project_parcel_with_an_error_named():
    got = outline.from_photo(PHOTO.read_bytes(), KRT_SQM, _fake_ask(), model="m",
                             rings_merc=[_parcel()], addresses=[ADDRESS])
    assert got["status"] == "ready" and len(got["rings_merc"]) == 1
    ring = got["rings_merc"][0]
    assert len(ring) == 4 and _area_m(ring) == pytest.approx(KRT_SQM, rel=0.01)
    assert all(_inside(p, ring) for p in _parcel()), "участок проекта внутри территории"
    assert 10 <= got["anchor_error_m"] <= 100, got
    assert "улице «Пролетарский пр-т»" in got["anchored_by"]


def test_a_parcel_bigger_than_the_outline_does_not_anchor_it():
    x, y = _merc(LAT, LON)
    k = math.cos(math.radians(LAT))
    big = [[x, y], [x + 200 / k, y], [x + 200 / k, y + 200 / k], [x, y + 200 / k]]
    got = outline.from_photo(PHOTO.read_bytes(), KRT_SQM, _fake_ask(), model="m", rings_merc=[big])
    assert got["status"] == "ready" and got["rings_merc"] == []
    assert "не ложатся внутрь обводки" in got["map_problem"]
    assert len(got["shape_m"][0]) == 4


# --- распознавание страницы целиком ---------------------------------------------------------

def test_the_scheme_photo_gives_the_shape_and_its_place(monkeypatch):
    _ocr(monkeypatch, LEGEND)
    got = manual.recognise(PHOTO.read_bytes(), "scheme.jpg", anchor_rings_merc=[_parcel()],
                           addresses=[ADDRESS], ask=_fake_ask(), model="m")
    assert got["status"] == "ready" and got["origin"] == "photo_outline", got
    assert got["approximate"] is True and got["area_sqm"] == KRT_SQM
    assert got["rings_merc"] and got["anchor_error_m"]
    assert got["source"] == outline.SOURCE_PHOTO_OUTLINE
    assert "Платон обвёл границу" in got["source_note"]


def test_the_area_comes_from_the_model_when_the_text_was_not_read(monkeypatch):
    _ocr(monkeypatch, "")
    got = manual.recognise(PHOTO.read_bytes(), "scheme.jpg", anchor_rings_merc=[_parcel()],
                           ask=_fake_ask(), model="m")
    assert got["origin"] == "photo_outline" and got["area_sqm"] == KRT_SQM


def test_the_catalog_on_the_photo_still_wins(monkeypatch):
    catalog = ("№ X Y\n1 8 000,00 10 000,00\n2 8 000,00 10 110,00\n"
               "3 8 070,00 10 110,00\n4 8 070,00 10 000,00\n1 8 000,00 10 000,00\n")
    _ocr(monkeypatch, catalog + LEGEND)
    calls: list = []
    got = manual.recognise(PHOTO.read_bytes(), "page.jpg", anchor_rings_merc=[_parcel()],
                           ask=_fake_ask(calls=calls), model="m")
    assert got["status"] == "ready" and not got["approximate"] and got.get("origin") is None
    assert got["area_sqm"] == 110 * 70
    assert calls == [], "каталог точнее — Платона не спрашивают"


# Владелец 28.10.2026: с той же картинки распознаватель собрал «каталог» из
# случайных чисел — 0,8 м², «контур не накрывает участки проекта», а площадь
# поля стала 0,0001 га. Числа без названной таблицы — не каталог; распознанный
# каталог, не сходящийся с площадью из текста, — тоже.
OCR_NOISE = ("ЮАО, район Царицыно\n1 0,12 0,34\n2 1,05 0,30\n3 0,98 1,61\n"
             "Условные обозначения: Границы территории нежилой застройки, подлежащей "
             "комплексному развитию, плошадью 0.77 га.")


def test_random_numbers_on_the_scheme_are_not_a_catalog(monkeypatch):
    assert manual.parse_catalog(OCR_NOISE)["points"] == 3, "контрпример: точки там есть"
    _ocr(monkeypatch, OCR_NOISE)
    got = manual.recognise(PHOTO.read_bytes(), "scheme.jpg", anchor_rings_merc=[_parcel()],
                           addresses=[ADDRESS], ask=_fake_ask(), model="m")
    assert got["origin"] == "photo_outline", got
    assert got["area_sqm"] == KRT_SQM, "«плошадью» распознавателя — тоже площадь"


def test_a_recognised_catalog_that_disagrees_with_the_text_is_refused(monkeypatch):
    catalog = ("Каталог координат\n1 8 000,00 10 000,00\n2 8 000,00 10 010,00\n"
               "3 8 010,00 10 010,00\n4 8 010,00 10 000,00\n")
    _ocr(monkeypatch, catalog + LEGEND)
    got = manual.recognise(PHOTO.read_bytes(), "page.jpg", anchor_rings_merc=[_parcel()],
                           ask=_fake_ask(), model="m")
    assert got["origin"] == "photo_outline" and got["area_sqm"] == KRT_SQM, got
    assert "100 м², а в тексте решения — 7 700 м²" in got["source_note"], got["source_note"]


def test_a_typed_catalog_of_a_few_square_metres_is_refused():
    got = manual.from_catalog("1 0,12 0,34\n2 1,05 0,30\n3 0,98 1,61\n")
    assert got["status"] == "failed" and "это не территория" in got["problem"]


def test_a_pdf_of_the_decision_gives_the_shape_from_its_scheme_page(monkeypatch):
    import io

    import document_intake
    from PIL import Image

    out = io.BytesIO()
    Image.open(PHOTO).convert("RGB").save(out, format="PDF", resolution=150)
    monkeypatch.setattr(document_intake, "extract_text", lambda data, name="": {"text": OCR_NOISE})
    got = manual.recognise(out.getvalue(), "decision.pdf", anchor_rings_merc=[_parcel()],
                           addresses=[ADDRESS], ask=_fake_ask(), model="m")
    assert got["origin"] == "photo_outline" and got["area_sqm"] == KRT_SQM, got
    assert got["rings_merc"], got


def test_a_new_parsing_version_does_not_reuse_the_old_answer_on_disk(monkeypatch):
    # Ответ разбора лежит на диске сутки: без версии в ключе исправленный разбор
    # отдавал бы владельцу прежний ложный каталог.
    import base64

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search import krt_project_site
    from auction_search.api import install

    monkeypatch.setitem(sys.modules, "developaid_core", core)
    monkeypatch.setattr(krt_project_site, "start", lambda key, work, **kw: False)
    app = FastAPI()
    install(app)
    client = TestClient(app)
    body = {"file_b64": base64.b64encode(PHOTO.read_bytes()).decode(), "filename": "s.jpg"}
    first = client.post("/krt/manual-contour", json=body).json()["key"]
    monkeypatch.setattr(manual, "RECOGNISE_VERSION", manual.RECOGNISE_VERSION + 1)
    second = client.post("/krt/manual-contour", json=body).json()["key"]
    assert first.startswith("manual-") and first != second


def test_the_owner_picture_read_by_tesseract_gives_the_area():
    import shutil

    if not shutil.which("tesseract"):
        pytest.skip("на этой машине нет tesseract")
    from developaid_v2_upgrade import _ocr_image

    text = _ocr_image(PHOTO.read_bytes())
    assert manual.area_from_text(text) == KRT_SQM, text
    assert manual.recognised_catalog(text, KRT_SQM)["status"] == "failed"


def test_a_model_outage_keeps_the_area_and_names_why_there_is_no_shape(monkeypatch):
    from fastapi import HTTPException

    _ocr(monkeypatch, LEGEND)

    def down(payload):
        raise HTTPException(status_code=503, detail="AI-прокси Render не настроен")

    got = manual.recognise(PHOTO.read_bytes(), "scheme.jpg", ask=down, model="m")
    assert got["status"] == "ready" and got["approximate"] and got["rings_merc"] == []
    assert "Платон недоступен: AI-прокси Render не настроен" in got["shape_problem"]
    assert "форму с картинки снять не вышло" in got["source_note"]


# --- схема посадки и PDF ---------------------------------------------------------------------

def _photo_site(anchored=True):
    got = outline.from_photo(PHOTO.read_bytes(), KRT_SQM, _fake_ask(), model="m",
                             rings_merc=[_parcel()] if anchored else None, addresses=[ADDRESS])
    return {"on": True, "status": "failed", "manual": {
        "rings_merc": got["rings_merc"], "area_sqm": KRT_SQM, "approximate": True,
        "origin": "photo_outline", "shape_m": got["shape_m"],
        "anchor_error_m": got["anchor_error_m"], "anchored_by": got["anchored_by"],
        "map_problem": got["map_problem"], "source": outline.SOURCE_PHOTO_OUTLINE}}


def _inputs(krt_site):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["_land_lookup"] = {"results": []}
    x["_krt_site"] = krt_site
    return x


MASSING = {"site_sqm": KRT_SQM, "footprint_sqm": 900.0, "setback_m": 3.0}
PHASES = [{"phase": 1, "above_gns_sqm": 9000.0}]


def test_the_scheme_follows_the_photo_shape_and_the_map_gets_the_buildings():
    layout = core.site_massing_layout(_inputs(_photo_site()), dict(MASSING), PHASES)
    assert layout["site_shape_origin"] == "contour"
    assert len(layout["site_rings"]) == 1 and len(layout["site_rings"][0]) == 4
    area = abs(core._ring_area(layout["site_rings"][0]))
    assert area == pytest.approx(KRT_SQM, rel=0.01)
    assert any(b.get("ring_merc") for b in layout["buildings"]), "корпуса есть на карте"
    note = layout["approximate_note"]
    assert note.startswith("Границы территории КРТ приблизительные")
    assert "погрешность привязки — около" in note and note in layout["notes"]
    assert layout["map_note"] == ""


def test_without_anchoring_the_scheme_keeps_the_shape_and_names_why_no_map():
    layout = core.site_massing_layout(_inputs(_photo_site(anchored=False)), dict(MASSING), PHASES)
    assert layout["site_shape_origin"] == "contour", "форма с картинки, а не квадрат"
    assert len(layout["site_rings"][0]) == 4
    assert not any(b.get("ring_merc") for b in layout["buildings"])
    assert "форму территории КРТ с картинки решения не удалось поставить на карту" in layout["map_note"]
    assert "участков проекта на карте нет" in layout["map_note"]
    assert "На карту её поставить не вышло" in layout["approximate_note"]


def test_the_pdf_scheme_carries_the_approximate_note():
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import KeepTogether, Paragraph

    x = _inputs(_photo_site())
    scheme = core.site_massing_scheme(x, dict(MASSING), PHASES)
    small = getSampleStyleSheet()["Normal"]
    story = core._site_massing_scheme_pdf(scheme, Paragraph, small, KeepTogether, 2.83)
    texts = [getattr(f, "text", "") for block in story for f in block._content]
    assert any(t.startswith("Границы территории КРТ приблизительные") for t in texts), texts


# --- Anthropic видит картинку ------------------------------------------------------------------

def test_the_image_reaches_anthropic_as_an_image_block():
    payload = outline.outline_request(b"\xff\xd8jpeg", 10, 10, "m")
    messages = plato_provider.messages_for_anthropic(payload["input"])
    blocks = messages[0]["content"]
    assert blocks[0]["type"] == "text" and "Обведи границу" in blocks[0]["text"]
    assert blocks[1]["type"] == "image" and blocks[1]["source"]["media_type"] == "image/jpeg"


# --- отрисованная страница -----------------------------------------------------------------------

PROBE = """async (args)=>{
 const [parcel, address]=args;
 inputs._land_lookup={query:'77:05:0004005:20',results:[{found:true,kind:'land',
  cadastral_number:'77:05:0004005:20',address:address,contour_merc:[parcel]}]};
 landLookup=cloneValue(inputs._land_lookup);
 setSiteArea(0.15638); await settledCalculate();
 openTab('tep'); renderSitePanel();
 const waitFor=async test=>{for(let i=0;i<300&&!test();i++)await new Promise(ok=>setTimeout(ok,100))};
 document.getElementById('siteKrtToggle').click();
 await waitFor(()=>(inputs._krt_site||{}).status!=='pending');
 const fold=document.getElementById('siteKrtManual');
 fold.open=true;
 Array.from(fold.querySelectorAll('button')).find(b=>b.textContent.includes('Распознать')).click();
 await waitFor(()=>!!((inputs._krt_site||{}).manual)||/не загружен|не распознано/.test(document.getElementById('siteKrtManualStatus').innerText));
 await settledCalculate();
 const layout=((((lastResult||{}).tep||{}).site_massing||{}).scheme||{}).layout||{};
 const ring=(layout.site_rings||[])[0]||[];
 let area=0;for(let i=0;i<ring.length;i++){const a=ring[i],b=ring[(i+1)%ring.length];area+=a[0]*b[1]-b[0]*a[1]}
 const scheme=document.getElementById('siteMassingScheme');
 const out={shape:layout.site_shape_origin||'',corners:ring.length,area:Math.abs(area/2),
  haField:document.getElementById('siteAreaHa').value,
  status:document.getElementById('siteKrtStatus').innerText,
  manualStatus:document.getElementById('siteKrtManualStatus').innerText,
  schemeText:scheme?scheme.innerText:'',approximateNote:String(layout.approximate_note||''),
  mapButton:!!document.getElementById('siteMassingMapButton')};
 const button=document.getElementById('siteMassingMapButton');
 if(button){
  button.click();
  await new Promise(ok=>setTimeout(ok,300));
  const dialog=document.getElementById('landMapDialog');
  out.mapOpen=dialog&&dialog.style.display!=='none';
  out.mapTitle=document.getElementById('landMapTitle').innerText;
  out.mapNote=document.getElementById('landMapNote').innerText;
  out.mapCorpora=document.querySelectorAll('#landMapDialog .land-map-corpus').length;
 }
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
    calls: list = []
    mp = pytest.MonkeyPatch()
    try:
        data_dir = tmp_path_factory.mktemp("photo-outline")
        mp.setenv("DATA_DIR", str(data_dir))
        mp.delenv("CORE_API_URL", raising=False)
        mp.setattr(core, "_MO_CALC_API_URL", "")
        mp.setitem(sys.modules, "developaid_core", core)
        mp.setattr(developaid_v2_upgrade, "_ocr_image", lambda data: LEGEND)
        ask = _fake_ask(calls=calls)
        mp.setattr(core, "_openai_responses_request",
                   lambda payload, budget=None: {"output_text": ask(payload)})
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
        with browser.serve(app, 18241) as base, sync_playwright() as pw, \
                pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 390, "height": 844})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.set_input_files("#siteKrtPhoto", str(PHOTO))
            out = page.evaluate(PROBE, [_parcel(), ADDRESS])
            page.close()
    finally:
        mp.undo()
    out["calls"] = len(calls)
    return out


def test_the_owner_photo_gives_a_four_corner_scheme_not_a_square(seen):
    assert seen["calls"] == 1, seen
    assert float(seen["haField"]) == pytest.approx(0.77, abs=0.0001), seen
    assert seen["shape"] == "contour", seen
    assert seen["corners"] == 4, seen
    assert seen["area"] == pytest.approx(KRT_SQM, rel=0.02), seen
    assert "Контур снят с картинки решения, границы приблизительные" in seen["status"], seen


def test_the_approximate_note_is_seen_on_the_scheme_and_on_the_map(seen):
    note = seen["approximateNote"]
    assert note.startswith("Границы территории КРТ приблизительные"), seen
    assert "погрешность привязки — около" in note, seen
    assert note in seen["schemeText"], seen
    assert seen["mapButton"] and seen["mapOpen"], seen
    assert seen["mapTitle"] == "Территория КРТ и окружение", seen
    assert seen["mapNote"].startswith(note), seen
    assert seen["mapCorpora"] >= 1, seen


# --- сохранённый ложный каталог (владелец 28.10.2026, прод 0.28.29) ---------------------

def test_the_minimum_territory_is_one_number():
    assert manual.MIN_CATALOG_SQM == core.KRT_TERRITORY_MIN_SQM


JUNK_PROBE = """async ()=>{
 inputs._krt_site={on:true,status:'failed',problem:'',choices:[],rings_merc:[],
  manual:{rings_merc:[[[0,0],[1,0],[0,1.6]]],area_sqm:0.8,approximate:false,
  source:'контур загружен вручную: каталог координат МСК-77, распознан с фото',source_note:''}};
 openTab('tep'); renderSitePanel();
 return document.getElementById('siteKrtStatus').innerText;
}"""


def test_a_saved_contour_of_a_square_metre_is_called_out_on_the_page():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18242) as base, sync_playwright() as pw, \
            pw.chromium.launch(executable_path=str(path)) as engine:
        page = engine.new_page(viewport={"width": 390, "height": 844})
        page.goto(base, wait_until="domcontentloaded")
        browser.wait_for_result(page)
        text = page.evaluate(JUNK_PROBE)
        page.close()
    assert "Этот контур — не территория КРТ" in text, text
    assert "Уберите контур кнопкой ниже" in text, text
