"""Посчитанная льгота предлагается там, где выбирают льготу; калькулятор МПТ
отказывает по-русски.

Владелец на проде 0.25.80, проект Нагатино: в «Льгота по плате» стояла
ручная «Доля от суммы» 100%. Посчитанная льгота (22 136,6 млн ₽) была, а
кнопка «Вернуться к посчитанной» — внизу вкладки, и её не нашли. Владелец
пошёл в калькулятор «по другому участку», нажал «Рассчитать льготу» с пустой
площадью и получил «Поле «area_sqm»: Input should be greater than 0». Под
итогами при этом стояло «Изменение ВРИ не требуется или сумма обязательства
равна нулю», хотя плату сняла льгота.

Решение владельца («Только подсказки», 15.10.2026):
- у поля «Льгота по плате» — кнопка «Применить посчитанную (N млн ₽)», тот же
  обработчик, что у «Вернуться к посчитанной»;
- в шапке калькулятора — одна строка о том, что льгота по участку проекта уже
  посчитана и где её применить;
- ошибки калькулятора — по-русски, подписью поля; пустая площадь ловится до
  отправки;
- строка про график говорит, что плату сняла льгота.

Запуск: python3 -m pytest tests/test_the_project_relief_is_offered_where_the_relief_is_chosen.py -q
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

FEE_MLN = 10170.0


@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    import main_registry
    return TestClient(main_registry.app)


# --- ошибка калькулятора по-русски --------------------------------------------

def test_an_empty_area_is_refused_in_russian_with_the_field_label(client) -> None:
    for area in (0, -5):
        response = client.post("/api/mpt/calculate", json={
            "category": "office", "district": "Нагатино-Садовники", "area_sqm": area,
            "ttk_position": "outside"})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail == "«Общая площадь МПТ, м²»: должно быть больше 0.", detail
    missing = client.post("/api/mpt/calculate", json={"district": "Нагатино-Садовники",
                                                      "area_sqm": 100})
    assert missing.json()["detail"] == "«Тип МПТ»: не заполнено."
    word = client.post("/api/mpt/calculate", json={
        "category": "office", "district": "Нагатино-Садовники", "area_sqm": 100,
        "ttk_position": "outside", "kzatr": "много"})
    assert word.json()["detail"] == "«Кзатр»: нужно число."


# --- правила страницы (настоящий код на node) ---------------------------------

def _run(expr: str):
    import page_blocks
    out, _taken = page_blocks.run("", f"console.log(JSON.stringify({expr}));")
    return json.loads(out)


def test_the_offer_appears_only_when_a_hand_relief_covers_a_counted_one() -> None:
    cases = [
        {"totals": {"relief_basis": basis}, "benefits": {"applicable": True, "total_mln": total}}
        for basis, total in (("percent", 22136.6), ("amount", 5.0), ("off", 1.0),
                             ("project_benefits", 22136.6), ("percent", 0))
    ]
    got = _run(f"{json.dumps(cases)}.map(vriProjectReliefOffer)")
    assert got[0]["text"] == "22 136,6 млн ₽"
    assert got[1] and got[2]
    # Посчитанная уже действует или её нет — предлагать нечего.
    assert got[3] is None and got[4] is None


def test_a_fee_removed_by_the_relief_is_named_so() -> None:
    cases = [
        {"totals": {"gross": 10170e6, "relief": 10170e6}, "settings": {"required": True}},
        {"totals": {"gross": 0, "relief": 0}, "settings": {"required": True}},
        {"totals": {"gross": 0, "relief": 0}, "settings": {"required": False}},
    ]
    removed, zero, off = _run(f"{json.dumps(cases)}.map(vriEmptyReason)")
    assert removed.startswith("Плата за изменение ВРИ 10 170 млн ₽ снята льготой полностью")
    assert "не требуется" not in removed
    assert "равна нулю" in zero and "не задана" in zero
    assert "Требуется изменение ВРИ" in off


# --- то, что видит человек ----------------------------------------------------

def test_in_a_real_browser_the_counted_relief_is_one_click_from_the_field(core) -> None:
    from browser import chromium_or_skip, serve
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import golden_snapshot
    import main_registry

    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], vri_required=True, vri_region="msk", social_area_source="norm",
                  land_rights_cost_mln=FEE_MLN, parking_district="Нагатино-Садовники",
                  parking_inside_ttk="outside", vri_relief_mode="percent", vri_relief_pct=100)
    inputs.pop("_cadastral_analysis", None)
    inputs.pop("_glavapu_import", None)
    seen: dict[str, object] = {}
    posted: list[str] = []
    with serve(main_registry.app, 18421) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("request", lambda req: posted.append(req.url)
                if req.url.endswith("/api/mpt/calculate") else None)
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("() => window.__developaidBooted", timeout=60000)
        page.evaluate(
            "([x,t]) => {Object.keys(inputs).forEach(k=>delete inputs[k]);Object.assign(inputs,x);"
            "Object.keys(tep).forEach(k=>delete tep[k]);Object.assign(tep,t);"
            "renderInputs();calculate();}", [inputs, case["tep"]])
        page.wait_for_function(
            "() => lastResult && lastResult.vri.totals.relief_basis==='percent'", timeout=60000)
        page.wait_for_timeout(200)
        seen["total_mln"] = page.evaluate("() => lastResult.vri.benefits.total_mln")
        # Кнопка — у самого поля «Льгота по плате» (вкладка ВРИ).
        page.evaluate("() => openTab('vri')")
        button = page.locator("#vriReliefOffer button")
        seen["button_visible"] = button.is_visible()
        seen["button"] = button.inner_text() if seen["button_visible"] else ""
        seen["beside_field"] = page.evaluate(
            "() => { const b=document.querySelector('#vriReliefOffer button');"
            " const f=document.getElementById('f_vri_relief_mode');"
            " return !!(b&&f&&b.parentNode.parentNode===f.parentNode); }")
        # Строка о графике и строка в калькуляторе — там же.
        page.evaluate("() => {const d=document.getElementById('mpt-benefit-panel');"
                      " d.open=true; d.scrollIntoView();}")
        seen["empty_visible"] = page.locator("#vriTabEmptyNote").is_visible()
        seen["empty"] = page.locator("#vriTabEmptyNote").inner_text()
        seen["mpt_line_visible"] = page.locator("#mpt-project-relief").is_visible()
        seen["mpt_line"] = page.locator("#mpt-project-relief").inner_text()
        # Пустая площадь — подсветка и текст до отправки, запроса нет.
        page.click("#mpt-calc")
        page.wait_for_timeout(200)
        seen["calc_text"] = page.locator("#mpt-warnings").inner_text()
        seen["area_marked"] = page.evaluate(
            "() => document.getElementById('mpt-area').classList.contains('mpt-invalid')")
        seen["posted"] = len(posted)
        page.fill("#mpt-area", "20000")
        seen["area_cleared"] = not page.evaluate(
            "() => document.getElementById('mpt-area').classList.contains('mpt-invalid')")
        # Кнопка у поля применяет посчитанную.
        page.click("#vriReliefOffer button")
        page.wait_for_function(
            "() => lastResult.vri.totals.relief_basis==='project_benefits'", timeout=60000)
        page.wait_for_timeout(200)
        seen["after_mode"] = page.evaluate("() => inputs.vri_relief_mode")
        seen["after_button"] = page.locator("#vriReliefOffer button").count()
        seen["after_line_visible"] = page.locator("#mpt-project-relief").is_visible()
        browser.close()

    assert not errors, errors
    total = f"{seen['total_mln']:,.1f}".replace(",", " ").replace(".", ",")
    assert seen["total_mln"] > 0
    assert seen["button_visible"] and seen["beside_field"], seen
    assert seen["button"] == f"Применить посчитанную ({total} млн ₽)", seen["button"]
    assert seen["empty_visible"], seen
    assert "снята льготой полностью" in seen["empty"] and "10 170 млн ₽" in seen["empty"], seen
    assert "не требуется" not in seen["empty"]
    assert seen["mpt_line_visible"], seen
    assert seen["mpt_line"] == (f"Льгота по участку проекта уже посчитана: {total} млн ₽ — "
                                "применить её можно кнопкой у «Льгота по плате».")
    assert "больше нуля" in seen["calc_text"] and "area_sqm" not in seen["calc_text"], seen
    assert seen["area_marked"] is True and seen["posted"] == 0, seen
    assert seen["area_cleared"]
    assert seen["after_mode"] == "none"
    assert seen["after_button"] == 0 and seen["after_line_visible"] is False, seen
