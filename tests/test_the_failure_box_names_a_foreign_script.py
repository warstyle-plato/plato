"""Плашка отличает ошибку из чужого скрипта от смерти нашей страницы.

Экран владельца 21.09.2026 (Safari, iPhone): поверх страницы красное
«Страница не доработала до конца. Script error. страница:0:0 — пришлите этот
текст, по нему видно точное место». Места по нему не видно и быть не может:
«Script error.» без файла и строки браузер выдаёт, когда ошибка произошла в
скрипте ДРУГОГО источника и её содержимое не раскрывается. Внешних скриптов
на нашей странице нет ни одного, а сама она в это время работала — значит
плашка звала поломкой чужое расширение и отправляла человека искать её у нас.

Утверждений здесь три:

  — внешних скриптов на странице нет (на этом держится сам вывод);
  — «Script error.» без места названа тем, что она есть, и наша плашка
    говорит, докуда дошла загрузка;
  — настоящая ошибка нашего кода по-прежнему называет файл, строку и столбец.

Проверяется настоящим браузером: в исходнике обе ветки выглядят одинаково.

Запуск: python3 -m pytest tests/test_the_failure_box_names_a_foreign_script.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18951


def test_the_page_has_no_foreign_scripts() -> None:
    """Вывод плашки держится на этом: внешних скриптов у нас нет.

    Появится хоть один — «значит это расширение браузера» станет неправдой,
    и плашка начнёт уводить от настоящей причины.
    """
    external = re.findall(r"<script[^>]*\ssrc=", core.PAGE)
    assert external == [], external


PROBE = """() => {
  const box = () => (document.getElementById('pageFailure') || {}).textContent || '';
  // Чужой скрипт: браузер отдаёт «Script error.» без файла и строки.
  window.dispatchEvent(new ErrorEvent('error', {message: 'Script error.',
                                                filename: '', lineno: 0, colno: 0}));
  const foreign = box();
  const node = document.getElementById('pageFailure');
  if (node) node.remove();
  // Наша ошибка: место известно.
  window.dispatchEvent(new ErrorEvent('error', {message: 'x is not defined',
                                                filename: 'http://local/page', lineno: 42, colno: 7}));
  return {foreign: foreign, ours: box(), booted: !!window.__developaidBooted};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            got = page.evaluate(PROBE)
            page.close()
    return got


def test_the_foreign_error_is_named_foreign(seen) -> None:
    text = seen["foreign"]
    assert text, "плашка промолчала"
    assert "другого источника" in text, text
    # Того, чего браузер не дал, плашка не выдумывает и не требует.
    assert "страница:0:0" not in text
    assert "по нему видно точное место" not in text, "плашка обещает место, которого нет"
    # Докуда дошла загрузка — измерение, а не догадка.
    assert ("загрузилась целиком" in text) == seen["booted"], text


def test_our_own_error_still_names_the_place(seen) -> None:
    """Предохранитель: настоящая поломка по-прежнему называет место."""
    text = seen["ours"]
    assert "Страница не доработала до конца" in text, text
    assert "x is not defined" in text and ":42:7" in text, text
