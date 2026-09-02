"""Присланный проект не наследует участок прошлого.

«Надо проверить, что из блока карточек КРТ на просчёт в модель идёт верная
информация. А не пара кадастров на 5 га при площади КРТ 15» (владелец,
02.09.2026). Вводные площадки приезжали верными — 15 га, ТЭП города, — а
разбор кадастра, контуры ЕГРН и скрининг НСПД прошлого участка оставались в
переменных страницы: они уезжали в PDF номерами участков, в подпись площади
(«из кадастра (ЕГРН)») и в имя проекта. Та же дыра у загрузки сохранённого
проекта и у файла настроек — все идут через `applyProjectSnapshot`, и
забывать территорию обязана она, а не каждый вызывающий по своему списку.

Проверяется в настоящем Chromium на живой странице: переменные `let` из
`PAGE` снаружи не видны, и строковый тест их не прочитает.

Запуск: python3 -m pytest tests/test_a_handed_over_project_forgets_the_old_parcel.py -q
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
from auction_search import bridge  # noqa: E402

core = wrapper.core
OLD = ["77:01:0004023:1", "77:01:0004023:2"]
PORT = 18233


def _function_body(name: str) -> str:
    start = core.PAGE.index(f"function {name}(")
    depth, index = 0, core.PAGE.index("{", start)
    for index in range(index, len(core.PAGE)):
        if core.PAGE[index] == "{":
            depth += 1
        elif core.PAGE[index] == "}":
            depth -= 1
            if depth == 0:
                return core.PAGE[start:index + 1]
    raise AssertionError(name)


# --- статика -----------------------------------------------------------------

def test_the_snapshot_forgets_the_territory_and_lifts_its_own() -> None:
    body = _function_body("applyProjectSnapshot")
    assert "forgetTerritoryState()" in body
    for restore in ("renderStoredCadastral()", "renderStoredLand()", "renderStoredMo()", "renderStoredGlavapu()"):
        assert restore in body, restore


def test_forgetting_covers_every_land_variable_and_the_screening_in_flight() -> None:
    body = _function_body("forgetTerritoryState")
    for name in ("cadastralAnalysis", "landLookup", "landScreeningLast", "LAND_MAP", "moResult", "glavapuImport"):
        assert re.search(r"\b" + name + r"\s*=\s*null", body), name
    assert "++landScreeningRun" in body, "опрос НСПД по прошлому участку дорисует чужие зоны"


def test_the_bridge_has_no_list_of_its_own() -> None:
    """Второй список полей территории разошёлся бы с первым."""
    script = bridge.BRIDGE_SCRIPT
    krt_branch = script[script.index("if(pending.krt_model){"):script.index("const preset=pending.project_preset;")]
    assert "applyProjectSnapshot(model)" in krt_branch
    # Лот торгов, наоборот, приносит свои номера участков и вписывает их в
    # поле — это его ветка, и она остаётся.
    assert "'cadastralNumbers'" not in krt_branch
    assert "landPreview" not in krt_branch
    assert "kind:'krt'" in krt_branch, "источник площади и ТЭП назван"


def test_reset_forgets_the_same_way() -> None:
    assert "forgetTerritoryState()" in _function_body("resetAll")


# --- живая страница -----------------------------------------------------------

def _old_project() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update({
        "site_area_ha": 5.0, "purchase_price_mln": 700,
        "_cadastral_analysis": {"recognized": OLD, "requested": OLD, "cadastral_numbers": OLD,
                                "territory": {"area_ha": 5.0}},
        "_land_lookup": {"query": ", ".join(OLD), "found_count": 2, "results": [
            {"cadastral_number": number, "found": True, "kind": "land", "area_sqm": 25000,
             "contour_merc": [[[0, 0], [1, 0], [1, 1]]]} for number in OLD]},
    })
    return {"inputs": inputs, "tep": core.TEP_DEFAULT, "phasing": None, "scenario": "base"}


def _krt_pending() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update({"site_area_ha": 15.0, "purchase_price_mln": 0.0,
                   "offices_gba_sqm": 0.0, "retail_gba_sqm": 0.0})
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return {"krt_model": {"inputs": inputs, "tep": tep, "phasing": None},
            "krt_name": "Площадка 15 га", "krt_slug": "site-15"}


READ_STATE = """() => ({
  site_area: inputs.site_area_ha,
  area_label: siteAreaSourceLabel(),
  tep_label: tepSourceLabel(!!inputs._manual_tep_import),
  cadastral: cadastralAnalysis ? (cadastralAnalysis.recognized||[]) : null,
  land: landLookup ? (landLookup.results||[]).map(x=>x.cadastral_number) : null,
  pdf_cads: currentPdfReportPayload().cadastral_numbers,
  project_cads: projectCadastral(),
  screening_shown: (document.getElementById('landScreening')||{}).style.display,
  cad_field: (document.getElementById('cadastralNumbers')||{}).value,
})"""


def test_in_a_real_browser_the_krt_site_arrives_without_the_old_parcel() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    # Мост стоит в PAGE только у сборки с модулем торгов (main_registry);
    # здесь он ставится тем же вызовом, что и там.
    bridge.install_page_bridge(core)
    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    fake_land = json.dumps({"parcels": [{"cadastral_number": n, "found": True, "findings": []} for n in OLD],
                            "verdict": {"status": "OK"}, "results": [], "found_count": 0})
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.route("**/land/**", lambda route: route.fulfill(
                status=200, content_type="application/json", body=fake_land))
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            page.evaluate("(s) => localStorage.setItem('plato_v04', JSON.stringify(s))", _old_project())
            # Предохранитель: прошлый участок действительно поднимается из хранилища.
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            before = page.evaluate(READ_STATE)
            page.evaluate("(p) => sessionStorage.setItem('developaid.auction.pending.v1', JSON.stringify(p))",
                          _krt_pending())
            page.goto(f"http://127.0.0.1:{PORT}/?krt_import=1", wait_until="networkidle")
            time.sleep(1.5)
            after = page.evaluate(READ_STATE)
            # Снимок со своей территорией поднимает её, а не пустоту: загрузка
            # сохранённого проекта идёт тем же путём.
            own = page.evaluate("(s) => { applyProjectSnapshot(s); return (" + READ_STATE + ")(); }",
                                {"inputs": _old_project()["inputs"], "tep": core.TEP_DEFAULT})
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert before["cadastral"] == OLD and before["site_area"] == 5, before
    assert after["site_area"] == 15
    assert after["cadastral"] is None and after["land"] is None, after
    assert after["pdf_cads"] == [] and after["project_cads"] == [], after
    assert after["screening_shown"] == "none" and after["cad_field"] == ""
    assert after["area_label"] == "из каталога КРТ (krt.mos.ru)", after["area_label"]
    assert after["tep_label"].startswith("Каталог КРТ"), after["tep_label"]
    assert own["cadastral"] == OLD and own["site_area"] == 5 and own["cad_field"] == ", ".join(OLD), own
