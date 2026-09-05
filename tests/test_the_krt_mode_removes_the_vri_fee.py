"""Режим «Требование КРТ» плату за смену ВРИ убирает, а не запирает.

«Когда включаем режим КРТ для соц объектов, почему не убирается из расчёта
ВРИ?» (владелец, 05.09.2026). Не убиралось: поле `land_rights_cost_mln` стоит
в `KRT_REQUIREMENT_INPUTS`, и это значило ровно одно — нормативный пересчёт его
больше не переписывает. Число, попавшее туда раньше (из выгрузки ГлавАПУ или
прошлого пересчёта), оставалось и шло в CAPEX, в расчётный лимит БРИДЖа, в
график платежей ВРИ и в книгу. На экране разницы нет никакой: поле выглядит
одинаково и с посчитанной платой, и с платой, которой быть не должно.
«Не тронули» читается как «убрали».

Закреплено:
- переключение в режим КРТ обнуляет плату и НАЗЫВАЕТ убранное — молчаливое
  обнуление врёт не меньше молчаливого сохранения;
- поле остаётся правимым: площадка, где плата всё-таки есть, вписывает её;
- проект, пришедший файлом или ссылкой, страницу не проходил — там движок
  говорит об оставшейся плате предупреждением, но сам её не трогает: вводная
  принадлежит человеку, а не расчёту.

Запуск: python3 -m pytest tests/test_the_krt_mode_removes_the_vri_fee.py -q
"""

from __future__ import annotations

import copy
import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PORT = 18251


def _report(mode: str, fee_mln: float) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(social_area_source=mode, land_rights_cost_mln=fee_mln)
    return core.calculate(core.CalcRequest(
        inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))


def _vri_warnings(report: dict) -> list[str]:
    return list((report.get("vri") or {}).get("warnings") or [])


def test_the_engine_names_a_fee_that_survived_the_krt_mode() -> None:
    kept = [note for note in _vri_warnings(_report("manual", 2864.3))
            if "плата за смену ВРИ" in note]
    assert kept, "плата осталась, а движок молчит"
    assert "2 864 млн ₽" in kept[0], kept[0]
    # Разделитель разрядов меняется у ЧИСЛА: применённый к фразе целиком, он
    # съедает и запятые прозы.
    assert "требованием КРТ, а плата" in kept[0], kept[0]


def test_the_engine_stays_silent_where_there_is_nothing_to_say() -> None:
    assert not [n for n in _vri_warnings(_report("manual", 0.0)) if "смену ВРИ" in n]
    assert not [n for n in _vri_warnings(_report("norm", 2864.3)) if "смену ВРИ" in n]


def test_the_engine_does_not_zero_the_field_itself() -> None:
    """Вводная принадлежит человеку: движок называет, но не правит.

    Молчаливое обнуление на сервере — это второй ответ о том же числе, и
    сохранённый проект менялся бы от одного открытия.
    """
    report = _report("manual", 2864.3)
    assert report["capex"]["land_rights"] == pytest.approx(2864.3 * 1e6, rel=1e-6)


def test_the_page_clears_the_fee_and_says_so() -> None:
    page = core.PAGE
    assert "function krtClearsVriFee()" in page
    body = page[page.index("function krtClearsVriFee()"):]
    body = body[:body.index("\nfunction ")]
    assert "inputs.land_rights_cost_mln=0" in body, "плата не обнуляется"
    assert "inputs._krt_vri_cleared_mln=was" in body, "убранное не запомнено — сказать нечего"
    # Правило одно и стоит там, куда приходит смена режима.
    handler = page[page.index("el.onchange=()=>{"):]
    handler = handler[:handler.index("\n")]
    assert "id==='social_area_source'&&krtClearsVriFee()" in handler, handler[:200]


def test_the_page_shows_what_it_removed() -> None:
    page = core.PAGE
    assert "Режим «Требование КРТ»: платы за смену ВРИ здесь нет" in page
    assert "Убрано ${num(wasVri)} млн ₽." in page, "убранное число не названо"
    assert "впишите её, она пойдёт в расчёт как есть" in page, (
        "поле обязано остаться правимым: площадка с платой должна её вписать")


def test_in_a_real_browser_switching_the_mode_clears_the_fee() -> None:
    """Строковый тест проходит и на сломанной странице: скрипт там один блок,
    и любая ошибка внутри не даёт браузеру определить ни одной функции."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():  # pragma: no cover
        pytest.skip("chromium в образе не найден")
    import uvicorn

    import main as wrapper

    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            before = page.evaluate(
                "() => { inputs.social_area_source='norm';"
                " inputs.land_rights_cost_mln=2864.3; renderInputs();"
                " return {fee: inputs.land_rights_cost_mln,"
                "  note: document.body.innerText.indexOf('платы за смену ВРИ здесь нет')>=0}; }")
            after = page.evaluate(
                "() => { const el=document.getElementById('f_social_area_source');"
                " el.value='manual'; el.onchange();"
                " return {fee: inputs.land_rights_cost_mln,"
                "  was: inputs._krt_vri_cleared_mln,"
                "  note: document.body.innerText.indexOf('платы за смену ВРИ здесь нет')>=0,"
                "  amount: (document.body.innerText.match(/Убрано [^.]+/)||[''])[0]}; }")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert before["fee"] == pytest.approx(2864.3) and before["note"] is False, before
    assert after["fee"] == 0, after
    assert after["was"] == pytest.approx(2864.3), after
    assert after["note"] is True, "поле обнулено молча — это та же ошибка с другой стороны"
    # Неразрывный пробел — разделитель разрядов страницы, а не наш.
    assert "2\u00a0864" in str(after["amount"]), after
