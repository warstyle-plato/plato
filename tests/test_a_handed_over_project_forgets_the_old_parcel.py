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
    """Второй список полей территории разошёлся бы с первым.

    Прежде это проверялось тем, что ветка КРТ поля участка не трогает вовсе, —
    и это было верно, пока у площадки не было кадастровых номеров. Проект
    решения называет их поимённо, и поле теперь заполняется. Утверждение
    осталось прежним: ЧИСТИТ территорию по-прежнему только подмена проекта, у
    моста своего списка полей нет — он лишь вписывает то, что ему прислали.
    """
    script = bridge.BRIDGE_SCRIPT
    krt_branch = script[script.index("if(pending.krt_model){"):script.index("const preset=pending.project_preset;")]
    assert "applyProjectSnapshot(model)" in krt_branch
    assert "field.value=''" not in krt_branch, "мост завёл свой список чистки"
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


def _krt_pending(source: dict | None = None) -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update({"site_area_ha": 15.0, "purchase_price_mln": 0.0,
                   "offices_gba_sqm": 0.0, "retail_gba_sqm": 0.0})
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    pending = {"krt_model": {"inputs": inputs, "tep": tep, "phasing": None},
               "krt_name": "Площадка 15 га", "krt_slug": "site-15"}
    if source is not None:
        pending["krt_source"] = source
    return pending


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
            # Та же передача, но площадкой БЕЗ карточки каталога: 298 строк из
            # 580 приходят проектом решения с mos.ru, и подпись обязана назвать
            # его, а не соседнюю половину списка.
            page.evaluate("(p) => sessionStorage.setItem('developaid.auction.pending.v1', JSON.stringify(p))",
                          _krt_pending({"name": "проект решения на mos.ru",
                                        "short": "mos.ru: проект решения",
                                        "open": "Открыть проект решения"}))
            page.goto(f"http://127.0.0.1:{PORT}/?krt_import=1", wait_until="networkidle")
            time.sleep(1.5)
            decision = page.evaluate(READ_STATE)
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
    # Подпись называет источник ТОЙ площадки, что приехала: половина каталога
    # КРТ — площадки без карточки, у них это проект решения на mos.ru.
    assert after["area_label"] == "из площадки КРТ (карточка krt.mos.ru)", after["area_label"]
    assert after["tep_label"].startswith("Площадка КРТ"), after["tep_label"]
    assert "карточка krt.mos.ru" in after["tep_label"], after["tep_label"]
    assert own["cadastral"] == OLD and own["site_area"] == 5 and own["cad_field"] == ", ".join(OLD), own
    assert decision["area_label"] == "из площадки КРТ (проект решения на mos.ru)", decision["area_label"]
    assert "проект решения на mos.ru" in decision["tep_label"], decision["tep_label"]
    assert "krt.mos.ru" not in decision["tep_label"], decision["tep_label"]
