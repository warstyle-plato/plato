"""Калькулятор МПТ на странице проекта берёт площади из ТЭП, а не ждёт ручного ввода.

Владелец на проде 0.25.80, проект КРТ Нагатино: «Рассчитать льготу» — и в
панели «Поле «area_sqm»: Input should be greater than 0». Район и кадастр уже
подставлены из участка, а «Общая площадь МПТ» пустая — 10000 там только
подсказка. «Так смысл то в том чтобы брать площадь из ТЭП уже введенных а не
вбивать вручную».

Площади, категорию, район и ТТК калькулятор берёт у того же владельца, что
автоматическая льгота: `vri_benefits.compute` → `vri.benefits.calculator`
(строки `rows` с `area_sqm`/`area_origin`/`category` и `site_position`).
Страница площадей не считает. Встроенная коммерция 1 этажа и выключенные
объекты в Sмпт не идут. Ошибка расчёта — по-русски, подписью поля.

Запуск: python3 -m pytest tests/test_the_mpt_calculator_takes_the_tep.py -q
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

import mpt_calculator  # noqa: E402
import vri_benefits  # noqa: E402

FEE_MLN = 10170.0
ANALYSIS = json.loads((ROOT / "tests" / "fixtures" / "nagatino_cadastral_analysis.json")
                      .read_text("utf-8"))


@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    import main_registry
    return TestClient(main_registry.app)


def _nagatino(core):
    import golden_snapshot
    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], vri_required=True, vri_region="msk",
                  vri_relief_mode="none", land_rights_cost_mln=FEE_MLN,
                  parking_district="", parking_inside_ttk="",
                  _cadastral_analysis=copy.deepcopy(ANALYSIS))
    inputs.pop("_glavapu_import", None)
    return inputs, case["tep"]


@pytest.fixture(scope="module")
def nagatino(core):
    inputs, tep = _nagatino(core)
    result = core._calculate_economics(core.CalcRequest(inputs=inputs, tep=tep))
    return inputs, tep, result["vri"]["benefits"]


def _payload(prefill: dict, benefits: dict) -> dict:
    return {**prefill["values"], "district": prefill["district"],
            "ttk_position": prefill["ttk_position"], "mode": "new",
            "cadastral_number": prefill["cadastral"], "kzatr": benefits["kzatr"]["value"],
            "kzatr_quarter": benefits["kzatr"]["quarter"]}


# --- владелец площадей: движок ----------------------------------------------

def test_nagatino_offices_retail_kindergarten_and_school_come_from_the_tep(nagatino) -> None:
    _inputs, tep, benefits = nagatino
    prefill = benefits["calculator"]
    rows = {row["key"]: row for row in benefits["rows"]}
    by_key = {item["key"]: item for item in prefill["objects"]}
    assert set(by_key) == {"offices", "standalone_retail", "kindergarten", "school"}
    # Площадь — та же, что у автоматической льготы, с её подписью.
    for key, item in by_key.items():
        assert item["area_sqm"] == rows[key]["area_sqm"] > 0
        assert item["area_origin"] == rows[key]["area_origin"]
    business = rows["offices"]["area_sqm"] + rows["standalone_retail"]["area_sqm"]
    social = rows["kindergarten"]["area_sqm"] + rows["school"]["area_sqm"]
    values = prefill["values"]
    assert values["category"] == "office"
    assert values["area_business_sqm"] == pytest.approx(business, abs=0.1)
    assert values["area_social_sqm"] == pytest.approx(social, abs=0.1)
    assert values["area_sqm"] == pytest.approx(business + social, abs=0.2)
    # Встроенная коммерция 1 этажа в Sмпт не идёт — и сказано почему.
    assert "ground_commercial" in tep and "ground_commercial" not in by_key
    assert any(x["key"] == "ground_commercial" and "встроенные" in x["reason"]
               for x in prefill["skipped"])
    assert prefill["text"].startswith("из ТЭП проекта: ")
    for label in ("Офисы", "Коммерция ОСЗ", "ДОО", "СОШ"):
        assert label in prefill["text"]
    assert prefill["district"] == "Нагатино-Садовники"
    assert prefill["ttk_position"] == "outside"


def test_the_prefilled_calculator_counts_a_nonzero_relief_equal_to_the_auto_one(
        nagatino, client) -> None:
    """Без ручного ввода: подстановка из ТЭП → ненулевая льгота, та же, что у движка."""
    _inputs, _tep, benefits = nagatino
    assert benefits["auto_mpt_mln"] > 0, benefits.get("mpt_reason")
    response = client.post("/api/mpt/calculate",
                           json=_payload(benefits["calculator"], benefits))
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["benefit_rub"] > 0 and not data["blockers"]
    assert data["eligible_area_sqm"] == pytest.approx(
        benefits["calculator"]["values"]["area_sqm"], abs=0.1)
    # Кмест графы 3 и графы 4/7 пропорционально площади — то же, что сумма
    # по объектам у автоматической льготы.
    assert data["benefit_rub"] / 1e6 == pytest.approx(benefits["auto_mpt_mln"], abs=0.002)


def test_kindergarten_and_school_fit_graph_4_without_changing_the_sum() -> None:
    """ДОО и СОШ — графа 7; калькулятор делит только между 3 и 4.

    Их перенос в графу 4 честен, пока Кмест и порог графы 7 совпадают с
    графой 4 во всех районах. Изменится таблица — упадёт здесь.
    """
    assert vri_benefits.CALCULATOR_GRAPH[mpt_calculator.COLUMN_MEDEDU] == "social"
    assert mpt_calculator.MIN_AREA_SQM["mededu"] == mpt_calculator.MIN_AREA_SQM["social"]
    for district in mpt_calculator.metadata()["districts"]:
        assert (mpt_calculator.kmest_for("mededu", district)[0]
                == mpt_calculator.kmest_for("social", district)[0]), district


def _owner_project() -> tuple[dict, dict, list[dict]]:
    """Рабочий проект владельца (снимок ТЭП 15.10.2026): включены только «Офисы»."""
    tep = {
        "apartments": {"label": "Квартиры", "gns": 385473, "total_area": 346926,
                       "sale_area": 250558},
        "ground_commercial": {"label": "Коммерция 1 этажа", "gns": 24605,
                              "total_area": 22144, "sale_area": 22144},
        "offices": {"label": "Офисы", "gns": 186000, "total_area": 174840, "sale_area": 87420},
        # Выключенные объекты с площадью в ТЭП — чтобы «не взят» значило
        # «выключен», а не «пустой».
        "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 30000, "total_area": 27000},
        "standalone_retail2": {"label": "Коммерция ОСЗ 2", "gns": 20000, "total_area": 18000},
        "offices2": {"label": "Офисы 2", "gns": 50000, "total_area": 47000},
    }
    objects = [
        {"key": "offices", "product": "offices", "label": "Офисы", "enabled": True},
        {"key": "offices2", "product": "offices", "label": "Офисы 2", "enabled": False},
        {"key": "standalone_retail", "product": "standalone_retail",
         "label": "Коммерция ОСЗ", "enabled": False},
        {"key": "standalone_retail2", "product": "standalone_retail",
         "label": "Коммерция ОСЗ 2", "enabled": False},
    ]
    inputs = {"vri_region": "msk", "_cadastral_analysis": copy.deepcopy(ANALYSIS)}
    return inputs, tep, objects


def test_the_owner_project_puts_the_enabled_offices_in_graph_3_and_skips_the_disabled() -> None:
    inputs, tep, objects = _owner_project()
    got = vri_benefits.compute(inputs, tep, objects, today=date(2026, 10, 15))
    prefill = got["calculator"]
    assert [item["key"] for item in prefill["objects"]] == ["offices"]
    offices = prefill["objects"][0]
    # База — общая площадь строки ТЭП, как у автольготы, и она подписана.
    assert offices["area_sqm"] == 174840
    assert offices["area_origin"] == "общая площадь строки ТЭП"
    assert prefill["values"] == {"category": "office", "area_sqm": 174840.0,
                                 "area_business_sqm": 174840.0, "area_social_sqm": 0.0}
    assert "Офисы — 174 840 м² (общая площадь строки ТЭП, графа 3)" in prefill["text"]
    for label in ("Офисы 2", "Коммерция ОСЗ"):
        assert label not in prefill["text"]
    assert [x["key"] for x in prefill["skipped"]] == ["ground_commercial"]


def test_an_applied_calculator_follows_the_tep_unless_edited_by_hand() -> None:
    """Значение из ТЭП после сохранения не ручное: ТЭП изменился — пересчитано."""
    inputs, tep, objects = _owner_project()
    today = date(2026, 10, 15)
    first = vri_benefits.compute(inputs, tep, objects, today=today)
    payload = _payload(first["calculator"], first)
    tep_origin = {"category": "tep", "area_sqm": "tep", "area_business_sqm": "tep",
                  "area_social_sqm": "tep"}
    bigger = copy.deepcopy(tep)
    bigger["offices"]["total_area"] = 200000

    applied = dict(inputs, vri_mpt_override={"payload": dict(payload), "origin": tep_origin})
    before = vri_benefits.compute(applied, tep, objects, today=today)["override"]
    after = vri_benefits.compute(applied, bigger, objects, today=today)["override"]
    assert before["payload"]["area_sqm"] == 174840
    assert after["payload"]["area_sqm"] == 200000
    assert after["payload"]["area_business_sqm"] == 200000
    assert after["benefit_mln"] > before["benefit_mln"] > 0
    assert after["from_tep"] == list(tep_origin)

    # Поправлено руками — остаётся, сколько бы ТЭП ни менялся.
    manual = dict(payload, area_sqm=150000, area_business_sqm=0, area_social_sqm=0)
    hand = dict(inputs, vri_mpt_override={
        "payload": manual, "origin": dict(tep_origin, area_sqm="manual",
                                          area_business_sqm="", area_social_sqm="")})
    kept = vri_benefits.compute(hand, bigger, objects, today=today)["override"]
    assert kept["payload"]["area_sqm"] == 150000
    assert kept["payload"]["area_business_sqm"] == 0
    assert not kept.get("error")


# --- ошибка по-русски ---------------------------------------------------------

def test_an_empty_area_is_refused_in_russian_with_the_field_label(client) -> None:
    for area in (0, -5):
        response = client.post("/api/mpt/calculate", json={
            "category": "office", "district": "Нагатино-Садовники", "area_sqm": area,
            "ttk_position": "outside"})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Общая площадь МПТ" in detail and "больше 0" in detail, detail
        assert "area_sqm" not in detail and "Input should" not in detail, detail
    missing = client.post("/api/mpt/calculate", json={"district": "Нагатино-Садовники",
                                                      "area_sqm": 100})
    assert missing.json()["detail"] == "«Тип МПТ»: не заполнено."


# --- страница: подстановка (настоящий код панели на node) ---------------------

def _plan(steps: list[dict]) -> list[dict]:
    import page_blocks
    from mpt_extension import _MPT_FRAGMENT

    tail = (
        f"const steps={json.dumps(steps, ensure_ascii=False)};\n"
        "let current={category:'office',area_sqm:'',area_business_sqm:'0',area_social_sqm:'0'};\n"
        "let origin={category:'',area_sqm:'',area_business_sqm:'',area_social_sqm:''};\n"
        "const out=[];\n"
        "for(const step of steps){\n"
        "  for(const [key,value] of Object.entries(step.edit||{})){current[key]=value;origin[key]='manual';}\n"
        "  const got=tepPlan(step.prefill,step.benefits===undefined?step.prefill&&{}:step.benefits,current,origin);\n"
        "  out.push(JSON.parse(JSON.stringify(got))); current={...got.values}; origin={...got.origin};\n"
        "}\n"
        "console.log(JSON.stringify(out));"
    )
    out, _taken = page_blocks.run("", tail, page=_MPT_FRAGMENT)
    return json.loads(out)


def _prefill(offices: float, social: float = 0.0) -> dict:
    inputs, tep, objects = _owner_project()
    tep = copy.deepcopy(tep)
    tep["offices"]["total_area"] = offices
    if social:
        tep["kindergarten"] = {"label": "ДОО", "gns": social, "total_area": social, "units": 300}
    return vri_benefits.compute(inputs, tep, objects, today=date(2026, 10, 15))["calculator"]


def test_the_panel_fills_the_areas_and_follows_a_changed_tep() -> None:
    first, second = _plan([{"prefill": _prefill(174840)},
                           {"prefill": _prefill(180000, social=6000)}])
    assert first["values"] == {"category": "office", "area_sqm": "174840",
                               "area_business_sqm": "174840", "area_social_sqm": "0"}
    assert set(first["origin"].values()) == {"tep"}
    assert "из ТЭП проекта: Офисы — 174 840 м²" in first["note"]
    assert "Коммерция 1 этажа" in first["note"]
    assert second["values"]["area_sqm"] == "186000"
    assert second["values"]["area_social_sqm"] == "6000"


def test_a_hand_edit_survives_the_tep_and_a_hand_area_drops_the_tep_split() -> None:
    _first, edited, later = _plan([
        {"prefill": _prefill(174840)},
        {"prefill": _prefill(174840), "edit": {"area_sqm": "20000"}},
        {"prefill": _prefill(190000)},
    ])
    assert edited["values"]["area_sqm"] == "20000"
    assert edited["origin"]["area_sqm"] == "manual"
    # Деление ТЭП между графами к ручной площади не относится.
    assert edited["values"]["area_business_sqm"] == "0"
    assert later["values"]["area_sqm"] == "20000"
    assert "введено вручную" in later["note"]


def test_without_the_tep_the_panel_says_why_and_clears_only_what_it_filled() -> None:
    filled, gone = _plan([{"prefill": _prefill(174840)},
                          {"prefill": None, "benefits": None}])
    assert filled["values"]["area_sqm"] == "174840"
    assert gone["values"]["area_sqm"] == ""
    assert "ТЭП проекта ещё не посчитан" in gone["note"]


# --- страница: то, что видит человек ------------------------------------------

def test_in_a_real_browser_the_nagatino_panel_counts_without_hand_input(core) -> None:
    from browser import chromium_or_skip, serve
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_registry

    inputs, tep = _nagatino(core)
    seen: dict[str, object] = {}
    with serve(main_registry.app, 18421) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("() => window.__developaidBooted", timeout=60000)
        page.evaluate(
            "([x,t]) => {Object.keys(inputs).forEach(k=>delete inputs[k]);Object.assign(inputs,x);"
            "Object.keys(tep).forEach(k=>delete tep[k]);Object.assign(tep,t);"
            "renderInputs();calculate();openTab('vri');}", [inputs, tep])
        page.wait_for_function(
            "() => lastResult && lastResult.vri && lastResult.vri.benefits"
            " && lastResult.vri.benefits.calculator", timeout=60000)
        page.evaluate("() => {const d=document.getElementById('mpt-benefit-panel');"
                      " d.open=true; d.scrollIntoView();}")
        page.wait_for_function("() => document.getElementById('mpt-area').value!==''",
                               timeout=20000)
        seen["expected"] = page.evaluate("() => lastResult.vri.benefits.calculator.values")
        seen["fields"] = page.evaluate(
            "() => ['mpt-category','mpt-area','mpt-area-business','mpt-area-social']"
            ".map(id=>document.getElementById(id).value)")
        seen["area_tag"] = page.locator("#mpt-area-origin").inner_text()
        seen["note"] = page.locator("#mpt-tep-note").inner_text()
        seen["note_visible"] = page.locator("#mpt-tep-note").is_visible()
        seen["district"] = page.input_value("#mpt-district")
        page.click("#mpt-calc")
        page.wait_for_function(
            "() => !/Считаю/.test(document.getElementById('mpt-warnings').textContent)",
            timeout=30000)
        seen["benefit"] = page.locator("#mpt-benefit").inner_text()
        seen["auto"] = page.evaluate("() => lastResult.vri.benefits.auto_mpt_mln")
        # Нулевая площадь руками: подсветка и понятный текст до отправки.
        # (Стёртое поле снова берётся из ТЭП — пустое ручное не ручное.)
        page.fill("#mpt-area", "0")
        page.dispatch_event("#mpt-area", "change")
        page.click("#mpt-calc")
        page.wait_for_timeout(200)
        seen["empty_text"] = page.locator("#mpt-warnings").inner_text()
        seen["empty_marked"] = page.evaluate(
            "() => document.getElementById('mpt-area').classList.contains('mpt-invalid')")
        seen["empty_tag"] = page.locator("#mpt-area-origin").inner_text()
        browser.close()

    assert not errors, errors
    want = seen["expected"]
    assert seen["fields"][0] == "office"
    assert [float(v) for v in seen["fields"][1:]] == [
        want["area_sqm"], want["area_business_sqm"], want["area_social_sqm"]], seen
    assert want["area_sqm"] > 0
    assert seen["area_tag"] == "из ТЭП проекта"
    assert seen["note_visible"] and "из ТЭП проекта: " in seen["note"], seen["note"]
    for label in ("Офисы", "ДОО", "СОШ"):
        assert label in seen["note"]
    assert seen["district"] == "Нагатино-Садовники"
    digits = int("".join(ch for ch in str(seen["benefit"]) if ch.isdigit()) or 0)
    assert digits > 0, seen["benefit"]
    assert digits / 1e6 == pytest.approx(seen["auto"], abs=0.01)
    assert "больше нуля" in seen["empty_text"] and "area_sqm" not in seen["empty_text"], seen
    assert seen["empty_marked"] is True
    assert seen["empty_tag"] == "введено вручную"


def test_the_empty_vri_schedule_names_its_real_reason() -> None:
    """«Не требуется или ноль» читалось и как «льгота съела плату», и как
    «плата потерялась». Льгота больше платы до этой строки не доходит: тогда
    виден блок «до льготы − льгота = 0»."""
    import page_blocks

    cases = [
        {"totals": {"gross": 0}, "settings": {"required": True}},
        {"totals": {"gross": 0}, "settings": {"required": False}},
    ]
    out, _taken = page_blocks.run(
        "", f"console.log(JSON.stringify({json.dumps(cases)}.map(vriEmptyReason)));")
    zero, off = json.loads(out)
    assert "Плата за изменение ВРИ в проекте равна нулю" in zero and "ни при чём" in zero
    assert "не требуется" in off and "Требуется изменение ВРИ" in off
