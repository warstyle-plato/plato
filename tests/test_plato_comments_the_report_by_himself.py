"""Разбор Платона приходит сам, а не по кнопке внизу страницы.

«А можно обновлять разбор в режиме онлайн Платоном? Загрузил отчёт и он его
пересчитал» (владелец, 06.09.2026). Комментарий был, но за кнопкой в самом низу
кабинета: человек, собравший отчёт, о нём не узнавал вовсе.

Запуск: python3 -m pytest tests/test_plato_comments_the_report_by_himself.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import cabinet  # noqa: E402


PAGE = cabinet.cabinet_page("market")


def _body(name: str) -> str:
    """Тело функции по скобкам, а не по соседней строке.

    Функция — контракт: она либо есть, либо её нет, и второе настоящая поломка.
    Границу считаем скобками, иначе проверка падает при правке соседа.
    """
    start = PAGE.index(f"function {name}(")
    depth, opened = 0, False
    for index in range(start, len(PAGE)):
        if PAGE[index] == "{":
            depth += 1
            opened = True
        elif PAGE[index] == "}":
            depth -= 1
            if opened and depth == 0:
                return PAGE[start:index + 1]
    raise AssertionError(f"не нашёл конца функции {name}")


def test_the_comment_is_asked_for_right_after_the_report_is_drawn() -> None:
    """Кнопка внизу отвечала только тому, кто о ней догадался."""
    assert re.search(r"render\(d\);\s*(//[^\n]*\n\s*)*platoBrief\(d\);", PAGE), (
        "разбор не зовётся сразу за отрисовкой отчёта"
    )
    # И карточка стоит в разметке отчёта: звать некуда, если её там нет.
    assert "html+=briefCard();" in PAGE


def test_a_late_answer_of_a_previous_report_is_dropped() -> None:
    """Отчёт пересобирают, не дождавшись прежнего ответа.

    Опоздавший ответ прежнего объекта уверенно встал бы под числами нового —
    та же защита, что у длинных ответов Платона везде.
    """
    body = _body("platoBrief")
    assert "const run=++briefRun" in body
    assert "if(run!==briefRun) return" in body


def test_the_waiting_card_does_not_go_to_paper() -> None:
    """Пустая карточка в PDF читается как «Платону сказать нечего»."""
    assert 'class="card noprint" id="briefcard"' in _body("briefCard")
    body = _body("platoBrief")
    assert "classList.toggle('noprint', !done)" in body


def test_silence_is_explained_instead_of_being_shown_as_emptiness() -> None:
    """«Комментария нет» и «Платон недоступен» на экране выглядят одинаково."""
    body = _body("platoBrief")
    assert "Платон не ответил" in body
    assert "Платон Сергеевич читает отчёт" in _body("briefCard")


def test_the_question_forbids_a_second_count_of_the_same_numbers() -> None:
    """Числа посчитаны движком; пересчитанные Платоном разошлись бы с экраном."""
    ask = PAGE[PAGE.index("const BRIEF_ASK="):]
    ask = ask[:ask.index(";\n")]
    assert "не пересчитывай" in ask
    assert "не выдумывай" in ask
    assert "в сравнении с соседями" in ask


def test_the_card_appears_and_waits_in_a_real_browser(tmp_path) -> None:
    """Спор «появляется или нет» решает экран, а не строка в исходнике."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    file = tmp_path / "market.html"
    file.write_text(PAGE.replace("__DEVELOPAID_VERSION__", "test"), encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            seen = tab.evaluate(
                """async () => {
                    document.querySelector('#out').innerHTML = briefCard();
                    // Ответа не будет: сеть в пробе закрыта. Проверяем, что до
                    // ответа карточка ждёт видимо и на бумагу не идёт.
                    const waiting = {
                        text: document.querySelector('#brief').textContent,
                        print: document.querySelector('#briefcard').classList.contains('noprint'),
                    };
                    // Опоздавший ответ прежнего запуска в окно не попадает.
                    briefRun = 7;
                    const stale = platoBrief({});
                    return {waiting, stale: typeof stale};
                }"""
            )
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert "читает отчёт" in seen["waiting"]["text"]
    assert seen["waiting"]["print"] is True, "карточка ожидания уходит в PDF"
