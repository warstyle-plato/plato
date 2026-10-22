"""Плашка cookie: Метрика запускается только после «Согласен».

Решение владельца 22.10.2026: Яндекс.Метрика с Вебвизором ставит свои cookie,
поэтому без согласия посетителя она не запускается. Плашка одна на все
HTML-страницы и вставляется той же прослойкой, что и счётчик
(`yandex_metrika.py`). Здесь закреплено на отрисованной странице:

- до выбора плашка видна, `ym` не определён и `tag.js` не запрошен;
- «Согласен» — `ym(…,'init')` вызван, загрузчик запрошен, плашка ушла и после
  перезагрузки не возвращается, а счётчик запускается сам;
- «Только необходимые» — Метрики нет ни сейчас, ни после перезагрузки;
- без `YANDEX_METRIKA_ID` плашки нет; в мини-приложении Telegram — тоже;
- на странице политики «Изменить выбор о cookie» показывает плашку снова.

Подделка, на которой это падает: `init` вне `start()` — тогда `ym` есть до
выбора, и первая же проверка красная.

Запуск: python3 -m pytest tests/test_cookie_consent_banner.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yandex_metrika  # noqa: E402

CID = "113133252"
PORT = 18941
BAR = "#" + yandex_metrika.BANNER_ID

STATE_JS = """() => ({
    ym: typeof window.ym,
    inits: (window.ym && window.ym.a || []).filter(a => a[1] === 'init').map(a => String(a[0])),
    bar: !!document.getElementById('%s'),
    choice: (() => { try { return localStorage.getItem('%s'); } catch (e) { return 'error'; } })(),
})""" % (yandex_metrika.BANNER_ID, yandex_metrika.CHOICE_KEY)


@pytest.fixture(scope="module")
def site():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser
    import main_registry

    path = browser.chromium_or_skip()
    with browser.serve(main_registry.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            yield base, engine


@pytest.fixture
def counter(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, CID)


class Visit:
    """Одна вкладка в своём профиле: свой `localStorage`, свой счёт загрузок."""

    def __init__(self, base, engine):
        self.base = base
        self.context = engine.new_context(viewport={"width": 390, "height": 800})
        self.tab = self.context.new_page()
        self.loads: list[str] = []
        self.errors: list[str] = []
        self.tab.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.tab.route("**/*", self._route)

    def _route(self, route):
        url = route.request.url
        if "mc.yandex.ru" in url:
            self.loads.append(url)
            route.fulfill(status=200, content_type="application/javascript", body="")
        elif url.startswith(self.base):
            route.continue_()
        else:
            route.abort()

    def open(self, path: str):
        self.tab.goto(self.base + path, wait_until="domcontentloaded")
        self.tab.wait_for_timeout(300)
        return self.state()

    def reload(self):
        self.tab.reload(wait_until="domcontentloaded")
        self.tab.wait_for_timeout(300)
        return self.state()

    def state(self):
        return self.tab.evaluate(STATE_JS)

    def close(self):
        self.context.close()


@pytest.fixture
def visit(site):
    opened: list[Visit] = []

    def make():
        v = Visit(*site)
        opened.append(v)
        return v

    yield make
    for v in opened:
        assert not v.errors, v.errors
        v.close()


@pytest.mark.parametrize("path", ["/guide", "/"])
def test_before_choice_no_metrika_and_agree_starts_it(visit, counter, path):
    v = visit()
    before = v.open(path)
    assert before["bar"], f"{path}: плашки нет"
    assert v.tab.locator(BAR).is_visible()
    assert before["ym"] == "undefined", f"{path}: Метрика запущена до согласия"
    assert v.loads == [], f"{path}: tag.js запрошен до согласия"

    v.tab.click(f"{BAR} [data-cookie-choice=all]")
    after = v.state()
    assert after["ym"] == "function"
    assert after["inits"] == [CID]
    assert not after["bar"]
    assert after["choice"] == "all"
    assert any("tag.js" in url for url in v.loads)

    again = v.reload()
    assert not again["bar"], "согласие не запомнилось"
    assert again["inits"] == [CID], "после перезагрузки счётчик не запустился сам"


def test_only_necessary_keeps_metrika_off_after_reload(visit, counter):
    v = visit()
    v.open("/guide")
    v.tab.click(f"{BAR} [data-cookie-choice=necessary]")
    state = v.state()
    assert state["ym"] == "undefined" and not state["bar"]
    assert state["choice"] == "necessary"

    again = v.reload()
    assert again["ym"] == "undefined", "после отказа Метрика запустилась при перезагрузке"
    assert not again["bar"], "после отказа плашка спрашивает снова"
    assert v.loads == []


def test_banner_speaks_plainly_and_links_the_policy(visit, counter):
    v = visit()
    v.open("/guide")
    text = v.tab.inner_text(BAR)
    for words in ("Мы используем файлы cookie", "Технические нужны для работы сайта",
                  "Яндекс.Метрика", "как улучшить сервис", "Согласен", "Только необходимые"):
        assert words in text, words
    assert v.tab.locator(f"{BAR} a[href='/privacy']").count() == 1
    # Плашка не шире экрана телефона.
    box = v.tab.locator(BAR).bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390


def test_no_counter_variable_no_banner(visit, monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, "")
    v = visit()
    for path in ("/guide", "/privacy"):
        state = v.open(path)
        assert not state["bar"], path
        assert state["ym"] == "undefined", path
    # Кнопке «Изменить выбор» без Метрики показывать нечего.
    assert not v.tab.locator("[data-cookie-reset]").is_visible()


@pytest.mark.parametrize("fragment", ["#telegram_session=abc", "#tgWebAppData=query_id%3D1"])
def test_telegram_mini_app_has_no_banner(visit, counter, fragment):
    v = visit()
    state = v.open("/guide" + fragment)
    assert not state["bar"], fragment
    assert state["ym"] == "undefined", fragment
    assert v.loads == [], fragment


def test_policy_page_lets_change_the_choice(visit, counter):
    v = visit()
    v.open("/privacy")
    v.tab.click(f"{BAR} [data-cookie-choice=all]")
    assert v.state()["inits"] == [CID]

    reset = v.tab.locator("[data-cookie-reset] button")
    assert reset.is_visible()
    reset.click()
    assert v.tab.locator(BAR).is_visible()
    v.tab.click(f"{BAR} [data-cookie-choice=necessary]")
    # Отказ после согласия перезагружает страницу, чтобы Метрика остановилась.
    v.tab.wait_for_load_state("domcontentloaded")
    v.tab.wait_for_timeout(300)
    state = v.state()
    assert state["ym"] == "undefined"
    assert state["choice"] == "necessary"
    assert not state["bar"]
