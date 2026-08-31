"""У кнопки, ставящей свои значения во все классы, должна быть обратная.

«Вставить данные из статистики» пишет свод модуля во ВСЕ классы разом и
сохраняет на сервере под аккаунтом. Снять их можно было только вручную,
ячейка за ячейкой: восемь статей на три класса — до двадцати четырёх штук.

Цена этой асимметрии вышла наружу 30.08.2026. Владелец нажал кнопку когда-то,
а потом смотрел на подземную часть и видел 175/210/306,3 вместо базы
88/152/240 — правка «подземка 0,8 наземной» из 0.20.59 в таблице не
показывалась вовсе. Своё значение сильнее базы и живёт на сервере, поэтому
переживает выкатку: со стороны это неотличимо от «правка не уехала».

Запуск: python3 -m pytest tests/test_the_class_overrides_can_be_taken_back.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _function(name: str) -> str:
    page = core.PAGE
    start = page.index(f"function {name}(")
    depth, index = 0, page.index("{", start)
    for position in range(index, len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                return page[start:position + 1]
    raise AssertionError(f"функция {name} не закрыта")


def test_the_button_is_next_to_the_one_that_sets_them() -> None:
    """Обратная кнопка стоит там же, где прямая, а не в другом углу."""
    page = core.PAGE
    at_fill = page.index("fillClassesFromStats()")
    at_clear = page.index("clearClassOverrides()")
    assert abs(at_clear - at_fill) < 600, "кнопки разъехались по разным местам"
    assert "Убрать мои значения" in page


def test_it_wipes_every_class_not_just_the_current_one() -> None:
    body = _function("clearClassOverrides")
    assert "CLASS_OVERRIDES={}" in body.replace(" ", "")
    # И стирает их в хранилище, иначе после перезагрузки они вернутся.
    assert "'/classes/overrides/save'" in body
    assert "payload:{}" in body.replace(" ", "")


def test_nothing_to_clear_is_said_and_not_saved() -> None:
    """Пустой список — не повод ходить в хранилище и не повод молчать."""
    body = _function("clearClassOverrides")
    assert "Своих значений классов нет" in body
    said = body.index("Своих значений классов нет")
    saved = body.index("'/classes/overrides/save'")
    assert said < saved, "сообщение должно стоять до сохранения, с возвратом"


def test_the_base_comes_back_in_a_real_browser() -> None:
    """Проверяется на живой странице: числа возвращаются к базам движка.

    Строковых проверок тут мало — база подставляется в страницу из движка, и
    вопрос ровно в том, что увидит человек после нажатия.
    """
    if not which("node"):
        pytest.skip("node недоступен")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")

    import threading
    import uvicorn

    config = uvicorn.Config(_wrapper.app, host="127.0.0.1", port=18219, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        import time
        time.sleep(0.05)
    assert server.started, "локальный сервер не поднялся"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto("http://127.0.0.1:18219/", wait_until="networkidle")
            page.evaluate("openClassDialog()")
            read = """(key) => {
              const row=[...document.querySelectorAll('#classDialogBody tr')].find(r=>{
                const i=r.querySelector('input');
                return i && (i.getAttribute('onchange')||'').includes("'"+key+"'");});
              return [...row.querySelectorAll('input')].map(i=>Number(i.value));
            }"""
            base = page.evaluate(read, "main_under_th_per_sqm")
            page.evaluate("""() => { CLASS_OVERRIDES={comfort:{main_under_th_per_sqm:175},
                business:{main_under_th_per_sqm:210}, elite:{main_under_th_per_sqm:306.3}};
                renderClassDialog(); }""")
            owned = page.evaluate(read, "main_under_th_per_sqm")
            page.evaluate("clearClassOverrides()")
            back = page.evaluate(read, "main_under_th_per_sqm")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    # Предохранитель: подмена обязана менять картину, иначе возврат ничего
    # не доказывает.
    assert owned[:3] == [175, 210, 306.3], owned
    assert owned[:3] != base[:3]
    assert back[:3] == base[:3], (back, base)
    # И это именно базы движка — 0,8 от наземной (владелец, 0.20.59).
    presets = core.PROJECT_CLASS_PRESETS
    assert back[:3] == [presets[key]["main_under_th_per_sqm"]
                        for key in ("comfort", "business", "elite")]
