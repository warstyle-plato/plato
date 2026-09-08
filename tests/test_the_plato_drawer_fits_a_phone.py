"""Ящик Платона на телефоне открывается целиком — вместе со своим низом.

Владелец 07.09.2026, снимок Safari на iPhone: «На телефоне окно Платона не
удобно не видно низ». На экране было видно шапку, подсказки и белое поле до
самого края — поля ввода и кнопки «Спросить» не было вовсе.

Причина не в вёрстке ящика, а в единице высоты. `100vh` на iOS Safari —
это БОЛЬШОЕ окно, вместе с полосой браузера внизу: страница объявляет себя
выше того, что человек видит, и низ ящика уезжает под полосу. Отвечает на
«сколько видно сейчас» другая единица — `dvh`, динамическое окно. Она есть в
Safari с 15.4 и в Chrome с 108, поэтому `100vh` остаётся ПЕРЕД ней запасным:
браузер, не знающий `dvh`, вторую строку пропустит и возьмёт первую. Порядок
здесь и есть утверждение — переставь их, и старый Safari останется без высоты
вовсе.

Проверяется это стилем, а не браузером, и вот почему: в Chromium `dvh` равен
`vh` — полосы, которая съедает низ, там нет. Замер на телефонном окне
390×664 показал одно и то же на исправном и на сломанном коде, то есть
браузером эту поломку не отличить. Поэтому здесь два разных сторожа:
объявление высоты держит разбор стиля (и он проверен на подделке — иначе
«нарушений нет» значило бы, что не сработал сам разбор), а браузер держит
другое, тоже настоящее: поле ввода не выталкивается из ящика содержимым
ленты.

Заодно снят второй вопрос того же снимка — домашняя полоса iPhone под полем
ввода: её высоту отдаёт сам браузер (`env(safe-area-inset-bottom)`), гадать
про неё числом нельзя.

Запуск: python3 -m pytest tests/test_the_plato_drawer_fits_a_phone.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plato_question  # noqa: E402


def _drawer_rule(css: str) -> str:
    """Тело правила `.ai-drawer{…}` — по своим скобкам, а не по соседней строке."""
    at = css.find(".ai-drawer{")
    assert at >= 0, "в стилях ящика нет правила .ai-drawer"
    end = css.index("}", at)
    return css[at + len(".ai-drawer{"):end]


def _heights(rule: str) -> list[str]:
    return [v.strip() for v in re.findall(r"(?:^|;)\s*height\s*:\s*([^;]+)", rule)]


def test_the_drawer_height_comes_from_the_dynamic_viewport() -> None:
    """Высота — от видимого окна, а `100vh` стоит перед ней запасным."""
    import main_legacy

    rule = _drawer_rule(plato_question.drawer_css(main_legacy))
    assert _heights(rule) == ["100vh", "100dvh"], (
        "высота ящика объявлена не парой «запасная, потом динамическая»: "
        f"{_heights(rule)}"
    )


def test_the_height_guard_falls_over_on_a_break() -> None:
    """Сторож высоты обязан отвергать обе поломки, иначе он ничего не значит."""
    broken = {
        "только 100vh (низ уедет под полосу Safari)": "height:100vh;",
        "только 100dvh (Safari до 15.4 останется без высоты)": "height:100dvh;",
        "запасная после динамической — она её и затрёт": "height:100dvh;height:100vh;",
    }
    for name, rule in broken.items():
        assert _heights(rule) != ["100vh", "100dvh"], f"сторож пропустил: {name}"


def test_the_compose_leaves_room_for_the_home_bar() -> None:
    """Под полем ввода — отступ, который называет сам браузер, а не мы числом."""
    import main_legacy

    css = plato_question.drawer_css(main_legacy)
    at = css.find(".ai-compose{")
    assert at >= 0, "в стилях ящика нет правила .ai-compose"
    rule = css[at + len(".ai-compose{"):css.index("}", at)]
    assert "env(safe-area-inset-bottom" in rule, (
        "низ поля ввода не знает о домашней полосе телефона: " + rule
    )


HARNESS = """<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{margin:0}__CSS__</style>
__DRAWER__
"""


@pytest.fixture(scope="module")
def phone(tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover - в песочнице без playwright
        pytest.skip("playwright недоступен")
    chrome = None
    for guess in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")):
        chrome = guess
    if chrome is None or not chrome.exists():  # pragma: no cover
        pytest.skip("chromium в образе не найден")

    import main_legacy

    markup = plato_question.drawer_markup(plato_question.DRAWER_IDS)
    markup = markup.replace('class="ai-drawer"', 'class="ai-drawer open"')
    page_file = tmp_path_factory.mktemp("drawer") / "phone.html"
    page_file.write_text(
        HARNESS.replace("__CSS__", plato_question.drawer_css(main_legacy))
        .replace("__DRAWER__", markup),
        encoding="utf-8",
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        # Окно телефона владельца за вычетом полосы Safari — то, что он видит.
        page = browser.new_page(viewport={"width": 390, "height": 664})
        page.goto(page_file.as_uri())
        yield page
        browser.close()


def test_the_field_is_not_pushed_out_by_the_conversation(phone) -> None:
    """Длинный разговор ленту прокручивает, а поле ввода с экрана не сгоняет."""
    phone.evaluate(
        """() => {
      const box = document.getElementById('platoOut');
      for (let i = 0; i < 60; i += 1) {
        const line = document.createElement('div');
        line.className = 'ai-msg';
        line.textContent = 'строка разговора номер ' + i;
        box.appendChild(line);
      }
    }"""
    )
    seen = phone.evaluate(
        """() => {
      const rect = sel => {
        const el = document.querySelector(sel);
        const box = el.getBoundingClientRect();
        return {top: box.top, bottom: box.bottom, height: box.height};
      };
      return {view: window.innerHeight, compose: rect('.ai-compose'),
              field: rect('#platoField'), send: rect('#platoSend')};
    }"""
    )
    view = seen["view"]
    assert seen["compose"]["bottom"] <= view + 1, (
        f"низ поля ввода за краем экрана: {seen['compose']['bottom']} при окне {view}"
    )
    for name, key in (("поле", "field"), ("кнопка «Спросить»", "send")):
        box = seen[key]
        assert box["height"] > 0 and 0 <= box["top"] and box["bottom"] <= view + 1, (
            f"{name} не видно на телефонном экране: {box} при окне {view}"
        )
