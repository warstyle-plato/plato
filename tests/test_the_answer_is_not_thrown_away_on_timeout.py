"""Окно сдалось — работа на сервере продолжается, и ответ можно забрать.

Экран владельца 14.09.2026: «Ответ не пришёл за 6 мин 24 с. Последняя стадия:
Сервис модели считает · 108 с». Ответ при этом готовится дальше и ложится на
сервере под тем же номером запуска — окно просто перестало за ним ходить.
Выбросить принятую работу значит потерять посчитанное: человеку остаётся
задать вопрос заново, то есть заказать ВТОРУЮ работу вместо начатой.

Здесь закреплено: отказ по времени несёт номер запуска, а рядом с ним встаёт
кнопка «Забрать ответ», которая ходит за готовым по тому же номеру.

Почему браузером: `awaitAgentResult` и отрисовка кнопки живут в скрипте
страницы, и в исходнике сломанная версия выглядит как исправная.

Запуск: python3 -m pytest tests/test_the_answer_is_not_thrown_away_on_timeout.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import browser  # noqa: E402

# Часы страницы подменяются на прыгающие: цикл ожидания живёт минутами, а
# проверка обязана укладываться в секунды. Подменяется только счётчик внутри
# вызова — сама механика («стадия не меняется — сдаёмся») остаётся настоящей.
_FAKE_CLOCK = """
(() => {
  let now = 1_700_000_000_000;
  Date.now = () => { now += 60000; return now; };
})()
"""

_PENDING_FETCH = """
window.fetch = async (url) => ({
  ok: true,
  json: async () => String(url).includes('/agent/trace/')
    ? {stage: 'ai_wait', label: ''}
    : {pending: true},
});
"""

_READY_FETCH = """
window.fetch = async (url) => ({
  ok: true,
  json: async () => String(url).includes('/agent/trace/')
    ? {stage: 'done', label: ''}
    : {pending: false, answer: 'Двор 5 715 м² — это 15 м²/чел.'},
});
"""


@pytest.fixture(scope="module")
def page_url():
    import main as wrapper
    with browser.serve(wrapper.app, 18117) as url:
        yield url


def _open(playwright, url: str):
    chrome = browser.chromium_or_skip()
    browser_obj = playwright.chromium.launch(executable_path=str(chrome))
    page = browser_obj.new_page()
    page.goto(url, wait_until="domcontentloaded")
    return browser_obj, page


def test_the_timeout_keeps_the_ticket_and_says_the_work_goes_on(page_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser_obj, page = _open(playwright, page_url)
        try:
            page.evaluate(_FAKE_CLOCK)
            page.evaluate(_PENDING_FETCH)
            answer = page.evaluate("awaitAgentResult('trace-xyz', null, true)")
        finally:
            browser_obj.close()

    assert answer["timedOut"] is True
    # Номер запуска уезжает вместе с отказом — по нему и забирают готовое.
    assert answer["traceId"] == "trace-xyz"
    assert "Работа на сервере продолжается" in answer["detail"]


def test_the_resume_button_brings_the_answer_that_arrived_late(page_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser_obj, page = _open(playwright, page_url)
        try:
            # Кнопка живёт в ящике Платона — открываем его, как человек.
            page.evaluate("toggleAgent(true)")
            page.evaluate("appendAiResumeButton('trace-xyz')")
            button = page.get_by_role("button", name="Забрать ответ")
            assert button.count() == 1, "кнопки «Забрать ответ» на экране нет"
            page.evaluate(_READY_FETCH)
            button.click()
            page.wait_for_function(
                "() => document.getElementById('aiMessages')"
                ".textContent.includes('15 м²/чел.')", timeout=15000)
            # Забрав ответ, кнопка уходит: оставшись, она предлагала бы
            # забрать то, что уже на экране.
            assert page.get_by_role("button", name="Забрать ответ").count() == 0
        finally:
            browser_obj.close()
