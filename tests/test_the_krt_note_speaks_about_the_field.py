"""Надпись о плате за ВРИ говорит о ПОЛЕ, а не только о режиме.

«Надпись противоречит 10 млрд» (владелец, 07.09.2026, экран калькулятора): в
поле «Оформление земельных правоотношений / смена ВРИ» стояло 10 166,649 млн ₽,
а прямо над ним — «Режим „Требование КРТ": платы за смену ВРИ здесь нет».
Число верное: заданная плата идёт в расчёт как есть — в CAPEX, в расчётный
лимит БРИДЖа, в график платежей и в книгу. Неверна была надпись: утверждение о
методике КРТ она подавала как утверждение о текущем состоянии поля.

Правка 05.09.2026 закрыла только ПЕРЕКЛЮЧЕНИЕ режима (`krtClearsVriFee` зовётся
из `onchange`). Всё, что кладёт плату при УЖЕ включённом режиме, проходило мимо,
и главный такой путь — выгрузка ГлавАПУ: `applyGlavapu` писала
`mappings.inputs` в `inputs` через `Object.assign`, то есть мимо
`KRT_REQUIREMENT_INPUTS`, и не говорила ни слова.

Закреплено:
- поле заполнено — надпись называет число и куда оно идёт, и даёт кнопку убрать;
- поле пусто — надпись говорит методику, как раньше;
- убирает человек нажатием, а не мы за него: молчаливое обнуление врёт не
  меньше молчаливого сохранения;
- замок держит и против выгрузки ГлавАПУ, а не тронутое ею — называется.

Проверяется настоящим Chromium: обе ветки надписи есть в исходнике всегда, и
строковый тест был бы зелёным на сломанном экране.

Запуск: python3 -m pytest tests/test_the_krt_note_speaks_about_the_field.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PORT = 18262
FEE = 10166.649


def _function_body(page: str, declaration: str) -> str:
    """Границей куска кода служат скобки, а не соседняя строка.

    Проверка, вырезающая «от объявления до следующего комментария», ломается,
    когда рядом что-то переписали, и падает не о том, что сломалось.
    """
    start = page.index(declaration)
    open_brace = page.index("{", start + len(declaration) - 1)
    depth = 0
    for i in range(open_brace, len(page)):
        if page[i] == "{":
            depth += 1
        elif page[i] == "}":
            depth -= 1
            if depth == 0:
                return page[start:i + 1]
    raise AssertionError(f"тело {declaration} не закрыто скобкой")


def test_the_glavapu_import_respects_the_krt_lock() -> None:
    """Ловится ВЫЗОВ: есть общий писатель вводных — звать обязаны его.

    Поведенческая проверка тут была бы зелёной и на сломанном коде: замок
    держит только те ключи, которые ему передали, а `Object.assign` до него
    не доходит вовсе.
    """
    body = _function_body(core.PAGE, "async function applyGlavapu()")
    assert "applyDerivedInputs(glavapuImport.mappings.inputs" in body, (
        "выгрузка пишет вводные мимо замка «Требования КРТ»")
    assert "Object.assign(inputs,glavapuImport.mappings.inputs" not in body, (
        "прежний писатель остался рядом с новым — два ответа на один вопрос")
    assert "glavapuSkipped" in body, "не тронутое замком не названо"


def test_both_branches_of_the_note_exist() -> None:
    body = _function_body(core.PAGE, "function krtVriFeeNote()")
    assert "платы за смену ВРИ здесь нет" in body, "ветка пустого поля потеряна"
    assert "эта плата идёт в расчёт как есть" in body, "ветка заполненного поля потеряна"
    assert "clearKrtVriFee()" in body, "кнопки убрать нет"


def _browser():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():  # pragma: no cover
        pytest.skip("chromium в образе не найден")
    return sync_playwright, chrome


def test_in_a_real_browser_the_note_names_the_fee_that_stands_in_the_field() -> None:
    sync_playwright, chrome = _browser()
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
    # Подпись читается у САМОГО поля: вкладка вводных может быть не активной, и
    # скрытый текст в `innerText` не попадает — проверка падала бы от того,
    # какая вкладка открыта, а не от того, работает ли правка.
    read = ("(() => { const box=document.getElementById('f_land_rights_cost_mln')"
            ".closest('.field'); const text=box?box.textContent:'';"
            " return {fee: inputs.land_rights_cost_mln,"
            "  denies: text.indexOf('платы за смену ВРИ здесь нет')>=0,"
            "  names: text.indexOf('эта плата идёт в расчёт как есть')>=0,"
            "  amount: (text.match(/В поле стоит [^—]+/)||[''])[0],"
            "  button: !!(box&&box.querySelector('button[onclick*=\"clearKrtVriFee\"]'))"
            " }; })()")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            filled = page.evaluate(
                "() => { inputs.social_area_source='manual';"
                f" inputs.land_rights_cost_mln={FEE}; renderInputs();"
                " return " + read + "; }")
            cleared = page.evaluate(
                "() => { clearKrtVriFee(); return " + read + "; }")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert filled["fee"] == pytest.approx(FEE), filled
    assert filled["names"] is True, "надпись не называет плату, которая стоит в поле"
    assert filled["denies"] is False, (
        "надпись отрицает плату, стоящую тут же — ровно то противоречие, "
        "на которое пожаловался владелец")
    # Неразрывный пробел — разделитель разрядов страницы, а не наш.
    assert "10 166,6" in str(filled["amount"]), filled["amount"]
    assert filled["button"] is True, "убрать плату нечем"

    assert cleared["fee"] == 0, cleared
    assert cleared["denies"] is True, "после уборки надпись обязана вернуться к методике"
    assert cleared["names"] is False, cleared
