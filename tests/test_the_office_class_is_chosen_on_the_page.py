"""Свой выбор класса офиса на странице (владелец, 22.10.2026 и 25.10.2026).

«А где выбор офисников по классу?» Шкала класса офиса B / B+ / A / A+ жила в
движке и в книге офиса, а на странице класс офиса жёстко шёл за классом
проекта, и A+ выбрать было нельзя. Теперь у каждого офиса поле «Класс офиса»:
пусто — класс идёт за классом проекта, иначе выбран человеком. Класс ставит
аренду, заполняемость, срок заполнения, эксплуатацию, ставку капитализации,
себестоимость здания (A+ — 250, владелец 25.10.2026) и в нежилом проекте цену
продажи. Число, вписанное руками, сильнее класса.

Проверяется на отрисованной странице и тем же правилом в движке: страница и
расчёт отвечают одним классом (`office_class_choice`, `apply_office_classes`).

Запуск: python3 -m pytest tests/test_the_office_class_is_chosen_on_the_page.py -q
"""

from __future__ import annotations

import copy
import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import developaid_nonres_strategy as ns  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18571
FIELDS = ("rent_th_per_sqm_month", "occupancy_stable_pct", "leaseup_months", "opex_pct", "exit_cap_pct")


def _step(cls: str) -> dict[str, float]:
    return {f"offices_{k}": v for k, v in ns.office_class_followed_values(cls).items()}


# --- движок -------------------------------------------------------------------

def test_the_class_comes_from_the_choice_or_from_the_project() -> None:
    assert ns.office_class_choice({"project_class": "business"}, "offices") == {
        "office_class": "B+", "source": ns.OFFICE_CLASS_BY_PROJECT_SOURCE, "text": "по классу проекта"}
    chosen = ns.office_class_choice({"project_class": "business", "offices_office_class": "A+"}, "offices")
    assert (chosen["office_class"], chosen["source"]) == ("A+", ns.OFFICE_CLASS_CHOSEN)
    # Чужое значение — не выбор.
    assert ns.office_class_choice({"project_class": "elite", "offices_office_class": "Z"},
                                  "offices")["office_class"] == "A"
    assert ns.office_class_choice({"project_class": "custom"}, "offices")["source"] == ns.OFFICE_CLASS_DEFAULT_SOURCE


def test_the_a_plus_building_costs_250() -> None:
    assert {cls: ns.OFFICE_CLASS_SCALE[cls]["cost_th_per_sqm"] for cls in ns.OFFICE_CLASSES} == {
        "B": 175.0, "B+": 200.0, "A": 225.0, "A+": 250.0}
    # Профиль класса проекта берёт себестоимость из той же шкалы.
    assert {k: v["cost_th_per_sqm"] for k, v in core.OFFICE_CLASS_BY_PROJECT_CLASS.items()} == {
        "comfort": 175, "business": 200, "elite": 225}


def test_a_project_saved_before_the_choice_gets_its_class_scale() -> None:
    """Бизнес-проект, сохранённый с умолчаниями класса B, считается по B+."""
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), "project_class": "business"}
    core.apply_office_classes(x)
    assert {k: x[k] for k in _step("B+")} == _step("B+")
    assert x["_field_origin"]["inputs.offices_exit_cap_pct"]["source"] == ns.OFFICE_CLASS_ORIGIN


def test_a_typed_number_is_stronger_than_the_class() -> None:
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), "project_class": "business", "offices_office_class": "A+",
         "offices_exit_cap_pct": 8.0,
         "_field_origin": {"inputs.offices_exit_cap_pct": {"source": "manual", "text": "вписано вручную"}}}
    core.apply_office_classes(x)
    assert x["offices_exit_cap_pct"] == 8.0
    assert x["offices_rent_th_per_sqm_month"] == _step("A+")["offices_rent_th_per_sqm_month"]


def test_a_shifted_class_number_is_not_reset() -> None:
    """Сдвиг подбора или сценария — уже не число класса: пересчёт его не сбрасывает,
    даже если он попал на ступень другого класса (торнадо двигает ставку на шаг)."""
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), "project_class": "comfort"}
    core.apply_office_classes(x)
    x["offices_exit_cap_pct"] = _step("B+")["offices_exit_cap_pct"]
    core.apply_office_classes(x)
    assert x["offices_exit_cap_pct"] == _step("B+")["offices_exit_cap_pct"]


def test_a_chosen_class_is_not_a_deviation_from_the_project_class() -> None:
    """Цена и себестоимость выбранного класса — база, а не отклонение от неё."""
    base = core.class_base_preset("business", "msk", core.PROJECT_KIND_NONRESIDENTIAL,
                                  {"offices_office_class": "A+"})
    x = {"project_class": "business", "project_kind": core.PROJECT_KIND_NONRESIDENTIAL,
         "offices_office_class": "A+", "offices_price_th_per_sqm": base["offices_price_th_per_sqm"],
         "offices_cost_th_per_sqm": base["offices_cost_th_per_sqm"]}
    assert base["offices_price_th_per_sqm"] == 1000.0
    fields = {row["field"] for row in core.project_class_deviations(x)["rows"]}
    assert not {"offices_price_th_per_sqm", "offices_cost_th_per_sqm"} & fields


def test_the_report_names_the_class_and_where_it_came_from() -> None:
    x = {"project_class": "business", "offices_enabled": True, "offices_gba_sqm": 10000}
    assert core.office_class_rows(x)[0]["text"] == "B+ — как у класса проекта «Бизнес»"
    x["offices_office_class"] = "A+"
    row = core.office_class_rows(x)[0]
    assert (row["label"], row["text"]) == ("Класс офиса", "A+ — выбран у офиса")
    # Офиса нет в проекте — строки нет.
    assert core.office_class_rows({"project_class": "business"}) == []


# --- страница -----------------------------------------------------------------

SET = r"""([id, value]) => {
  const el = document.getElementById('f_' + id);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.dispatchEvent(new Event('change'));
}"""

STATE = r"""() => {
  const sel = document.getElementById('f_offices_office_class');
  const shown = {};
  for (const k of %s) {
    const el = document.getElementById('f_offices_' + k);
    shown['offices_' + k] = el ? Number(el.value) : null;
  }
  const note = document.getElementById('officeClassNote_offices');
  return {options: sel ? [...sel.options].map(o => [o.value, o.textContent]) : null,
          value: sel ? sel.value : null, shown, note: note ? note.textContent : '',
          price: inputs.offices_price_th_per_sqm, cost: inputs.offices_cost_th_per_sqm,
          inputs, tep, preview: (document.getElementById('projectClassPreview') || {}).textContent || ''};
}""" % json.dumps(list(FIELDS))


def _post(base: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/calculate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="module")
def walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate("()=>{try{applyProjectKind('nonresidential')}catch(e){}"
                          "try{closeProjectKindDialog()}catch(e){}}")
            browser.wait_for_result(page)

            def step(name: str, *actions: tuple[str, object]) -> None:
                for field, value in actions:
                    page.evaluate(SET, [field, value])
                    browser.wait_for_result(page)
                page.evaluate("()=>settledCalculate()")
                out[name] = page.evaluate(STATE)

            step("comfort", ("offices_enabled", True), ("offices_strategy", "income"))
            # В нежилом проекте класс проекта — класс офиса.
            page.evaluate("()=>{const s=document.getElementById('projectClassSelect');"
                          "s.value='office:B+';s.dispatchEvent(new Event('change'))}")
            browser.wait_for_result(page)
            step("business")
            step("chosen", ("offices_office_class", "A+"))
            # Ставка капитализации вписана руками; новый класс спрашивает, и
            # человек оставляет своё.
            page.evaluate("()=>{window.confirm=()=>false}")
            step("typed", ("offices_exit_cap_pct", 8), ("offices_office_class", "A"))
            step("back", ("offices_office_class", ""))
            out["engine"] = _post(base, {"inputs": out["back"]["inputs"], "tep": out["back"]["tep"],
                                         "rates": []})
            # Теперь человек соглашается заменить вписанное значениями класса.
            page.evaluate("()=>{window.confirm=()=>true}")
            step("replaced", ("offices_office_class", "A+"))
            out["errors"] = errors
            page.close()
    return out


def test_the_office_has_a_class_choice_with_a_plus(walk) -> None:
    assert walk["comfort"]["options"] == [["", "Как у класса проекта"], ["B", "B"], ["B+", "B+"],
                                          ["A", "A"], ["A+", "A+"]]
    assert walk["comfort"]["value"] == ""
    assert walk["errors"] == []


def test_by_default_the_class_follows_the_project_class(walk) -> None:
    assert walk["comfort"]["shown"] == _step("B")
    assert walk["business"]["shown"] == _step("B+")
    assert "класс офиса B+" in walk["business"]["note"] and "класс проекта" in walk["business"]["note"]
    assert walk["business"]["price"] == ns.OFFICE_CLASS_SCALE["B+"]["price_th_per_sqm"]


def test_a_chosen_class_sets_the_scale_price_and_cost(walk) -> None:
    got = walk["chosen"]
    assert got["value"] == "A+"
    assert got["shown"] == _step("A+")
    assert got["price"] == 1000.0
    # Нежилой проект: себестоимость — СМР здания из «под ключ» 250 по ставкам класса.
    assert got["cost"] == core.class_base_preset(
        "business", "msk", core.PROJECT_KIND_NONRESIDENTIAL, {"offices_office_class": "A+"})[
        "offices_cost_th_per_sqm"]
    assert "выбран вами" in got["note"]
    assert "A+ (выбран у офиса)" in got["preview"]
    assert got["inputs"]["_field_origin"]["inputs.offices_rent_th_per_sqm_month"]["text"] == "по классу офиса A+"


def test_a_typed_field_survives_a_class_change(walk) -> None:
    got = walk["typed"]["shown"]
    assert got["offices_exit_cap_pct"] == 8
    assert got["offices_rent_th_per_sqm_month"] == _step("A")["offices_rent_th_per_sqm_month"]


def test_back_to_the_project_class(walk) -> None:
    got = walk["back"]
    assert got["value"] == ""
    assert got["shown"]["offices_rent_th_per_sqm_month"] == _step("B+")["offices_rent_th_per_sqm_month"]
    assert got["shown"]["offices_exit_cap_pct"] == 8
    assert got["price"] == ns.OFFICE_CLASS_SCALE["B+"]["price_th_per_sqm"]


def test_replacing_a_typed_field_returns_it_to_the_class(walk) -> None:
    got = walk["replaced"]
    assert got["shown"] == _step("A+")
    assert got["inputs"]["_field_origin"]["inputs.offices_exit_cap_pct"]["source"] == ns.OFFICE_CLASS_ORIGIN


def test_the_engine_reads_the_same_class_as_the_page(walk) -> None:
    """Страница и движок — одно правило: вводные страницы движок не двигает."""
    page_inputs = walk["back"]["inputs"]
    x = copy.deepcopy(page_inputs)
    core.apply_office_classes(x)
    assert {f"offices_{k}": x[f"offices_{k}"] for k in FIELDS} == {
        f"offices_{k}": page_inputs[f"offices_{k}"] for k in FIELDS}
    rows = walk["engine"]["office_classes"]
    assert [(r["prefix"], r["office_class"], r["source"]) for r in rows] == [
        ("offices", "B+", ns.OFFICE_CLASS_BY_PROJECT_SOURCE)]


def test_an_unmarked_number_of_another_class_is_somebodys_own() -> None:
    """Без пометки за классом идёт только нетронутое умолчание: ступень A,
    вписанная в поле (эталон «офис класса A», вызов API), — своя."""
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), "project_class": "comfort", **_step("A")}
    core.apply_office_classes(x)
    assert {k: x[k] for k in _step("A")} == _step("A")


# --- PDF и тизер ----------------------------------------------------------------

def _housing_with_office() -> tuple[dict, dict]:
    """Жилой проект со встроенным офисом, класс офиса выбран своим."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(project_class="business", offices_enabled=True, offices_gba_sqm=6000,
             offices_saleable_sqm=4000, offices_office_class="A+")
    t["offices"].update(gns=6000, total_area=5600, saleable=4000)
    return x, t


def test_the_pdf_and_the_teaser_name_the_chosen_class() -> None:
    pytest.importorskip("reportlab")
    from pypdf import PdfReader
    import io
    from market_search.krt_requirements import pdf_text

    x, t = _housing_with_office()
    bundle = core._run_authoritative_model(x, t, [], {})
    assert [(r["office_class"], r["source"]) for r in bundle["consolidated"]["office_classes"]] == [
        ("A+", ns.OFFICE_CLASS_CHOSEN)]
    report = " ".join(pdf_text(core._build_developaid_pdf({
        "result": bundle["consolidated"], "inputs": x, "tep": t, "rates": [], "phasing": {},
        "scenario": "base", "project_name": "Проверка"})).split())
    assert "Класс офиса A+ — выбран у офиса" in report
    teaser = core.build_teaser_pdf(bundle, x, t, None)
    text = " ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(teaser)).pages).split())
    assert "Класс офиса. A+ — выбран у офиса" in text


# --- класс нежилого проекта — класс офиса ----------------------------------------

KIND_STATE = r"""() => {
  const sel = document.getElementById('projectClassSelect');
  return {options: [...sel.options].map(o => [o.value, o.textContent]), value: sel.value,
          project_class: inputs.project_class, nonres: inputs.nonres_office_class || '',
          parking: inputs.parking_price_th, under: inputs.main_under_th_per_sqm,
          price: inputs.offices_price_th_per_sqm, cost: inputs.offices_cost_th_per_sqm,
          rent: inputs.offices_rent_th_per_sqm_month, office: inputs.offices_office_class || '',
          elite_under: classValue('elite', 'main_under_th_per_sqm'),
          note: (document.getElementById('officeClassNote_offices') || {}).textContent || '',
          preview: (document.getElementById('projectClassPreview') || {}).textContent || ''};
}"""


@pytest.fixture(scope="module")
def kinds() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT + 1) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SET, ["offices_enabled", True])
            browser.wait_for_result(page)
            page.evaluate("()=>{const s=document.getElementById('projectClassSelect');"
                          "s.value='business';s.dispatchEvent(new Event('change'))}")
            browser.wait_for_result(page)
            out["housing"] = page.evaluate(KIND_STATE)
            page.evaluate("()=>{try{applyProjectKind('nonresidential')}catch(e){}"
                          "try{closeProjectKindDialog()}catch(e){}}")
            browser.wait_for_result(page)
            out["nonres"] = page.evaluate(KIND_STATE)
            page.evaluate("()=>{const s=document.getElementById('projectClassSelect');"
                          "s.value='office:A+';s.dispatchEvent(new Event('change'))}")
            browser.wait_for_result(page)
            page.evaluate("()=>settledCalculate()")
            out["a_plus"] = page.evaluate(KIND_STATE)
            out["a_plus_inputs"] = page.evaluate("()=>inputs")
            page.evaluate("()=>{try{applyProjectKind('mixed')}catch(e){}"
                          "try{closeProjectKindDialog()}catch(e){}}")
            browser.wait_for_result(page)
            out["back_to_housing"] = page.evaluate(KIND_STATE)
            out["errors"] = errors
            page.close()
    return out


def test_housing_keeps_comfort_business_elite(kinds) -> None:
    got = kinds["housing"]
    assert [v for v, _ in got["options"]] == ["comfort", "business", "elite", "custom"]
    assert got["value"] == "business"
    assert "«Бизнес»" in got["note"] and "B+" in got["note"]
    assert kinds["errors"] == []


def test_a_nonresidential_project_chooses_the_office_class(kinds) -> None:
    got = kinds["nonres"]
    assert [v for v, _ in got["options"]] == ["office:B", "office:B+", "office:A", "office:A+", "custom"]
    # Бизнес становится B+ — тот же класс, те же числа.
    assert got["value"] == "office:B+"
    assert got["price"] == ns.OFFICE_CLASS_SCALE["B+"]["price_th_per_sqm"]


def test_a_plus_takes_the_elite_garage_and_its_own_office_step(kinds) -> None:
    got = kinds["a_plus"]
    assert (got["value"], got["project_class"], got["nonres"]) == ("office:A+", "elite", "A+")
    assert got["parking"] == core.PROJECT_CLASS_PRESETS["elite"]["parking_price_th"]
    assert got["under"] == got["elite_under"]
    assert got["price"] == 1000.0
    assert got["rent"] == _step("A+")["offices_rent_th_per_sqm_month"]
    # Свой выбор у офиса не ставится: класс офиса — класс проекта.
    assert got["office"] == "" and "класс проекта" in got["note"]
    assert "офисы класса A+" in got["preview"]
    # Движок отвечает тем же классом и той же ценой.
    x = kinds["a_plus_inputs"]
    assert core.nonres_strategy.nonres_project_class(x) == "A+"
    assert core.class_base_preset(x["project_class"], "msk", core.PROJECT_KIND_NONRESIDENTIAL, x)[
        "offices_price_th_per_sqm"] == 1000.0
    assert core.project_class_view(x)["label"] == "A+"


def test_back_to_housing_shows_the_housing_class(kinds) -> None:
    got = kinds["back_to_housing"]
    assert got["value"] == "elite"
    assert [v for v, _ in got["options"]][0] == "comfort"


def test_an_old_nonresidential_project_keeps_its_class() -> None:
    """Нежилой проект, сохранённый с классом жилья, открывается с тем же классом."""
    for key, cls in ns.OFFICE_CLASS_BY_PROJECT.items():
        x = {"project_kind": core.PROJECT_KIND_NONRESIDENTIAL, "project_class": key}
        assert ns.nonres_project_class(x) == cls
        assert core.class_base_preset(key, "msk", core.PROJECT_KIND_NONRESIDENTIAL, x)[
            "offices_price_th_per_sqm"] == core.NONRES_KIND_CLASS_PRICES[key]["offices_price_th_per_sqm"]
