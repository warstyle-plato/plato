"""Стенд страницы ждёт итог расчёта, а не время.

Расчёт страницы асинхронный и нумерованный: каждая правка поля и каждая
загрузка зовут `calculate` заново, ответ старшего номера отбрасывается, а
после `domcontentloaded` загрузка ещё идёт. На медленном раннере пауза
«на глаз» кончалась раньше первого ответа — проба читала `lastResult.tep` у
null, и за день это роняло доли шести PR подряд. Проба, звавшая `calculate()`
сама, получала null, когда её перебивал расчёт загрузки.

Ответ один — `browser.wait_for_result` (после загрузки и правок) и
`settledCalculate` (из проб): «загрузка дошла до конца, расчёта в пути нет,
итог есть». Здесь показано, что на задержанном расчёте прежняя пауза падает
той самой ошибкой CI, а ожидание проходит; что ожидание падает на странице,
которая не отвечает, — с названной причиной, а не зелёным; и что перебитая
проба всё равно получает итог.

Запуск: python3 -m pytest tests/test_the_page_wait_ends_with_the_result.py -q
"""

from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18995
SLOW_SECONDS = 4.0
OLD_PAUSE_MS = 1500
MAIN_PAGE_GOTO = (r'goto\((?:base[,)]|url[,)]|f"http://127\.0\.0\.1:\{PORT\}/?["?#]'
                  r'|f"\{base\}/(?:classic)?["?#])')


@contextlib.contextmanager
def _page(monkeypatch, calculate):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    monkeypatch.setattr(core, "calculate", calculate)
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            yield page
            page.close()


def _slow(seconds: float):
    real = core.calculate

    def calculate(req):
        time.sleep(seconds)
        return real(req)
    return calculate


def test_a_slow_calculation_is_awaited_not_timed(monkeypatch) -> None:
    """Движок отвечает 4 с: пауза в 1,5 с падает ошибкой CI, ожидание проходит."""
    from playwright.sync_api import Error as PlaywrightError

    with _page(monkeypatch, _slow(SLOW_SECONDS)) as page:
        page.wait_for_timeout(OLD_PAUSE_MS)  # пауза не про расчёт: это сама прежняя пауза, подделка
        with pytest.raises(PlaywrightError, match=r"reading 'tep'"):
            page.evaluate("lastResult.tep")
        browser.wait_for_result(page)
        state = page.evaluate(browser.CALC_STATE_JS)
        assert state["booted"] and state["result"] and state["run"] == state["settled"], state
        assert page.evaluate("Array.isArray(lastResult.tep.rows)")


def test_a_page_that_never_answers_fails_by_name(monkeypatch) -> None:
    """Подделка: ответа нет вовсе. Ожидание падает и называет, чего не дождалось."""
    release = threading.Event()
    real = core.calculate

    def calculate(req):
        release.wait(30)
        return real(req)
    try:
        with _page(monkeypatch, calculate) as page:
            with pytest.raises(AssertionError, match=r"не закончился за 3 с.*итог нет"):
                browser.wait_for_result(page, timeout_ms=3000)
    finally:
        release.set()


def test_a_refused_calculation_is_not_waited_for(monkeypatch) -> None:
    """Подделка: движок отвечает отказом. Ожидание падает сразу, а не по таймауту."""
    def calculate(req):
        raise core.HTTPException(status_code=401, detail="Расчёт экономики — после входа")
    with _page(monkeypatch, calculate) as page:
        started = time.monotonic()
        with pytest.raises(AssertionError, match=r"закрыт входом"):
            browser.wait_for_result(page, timeout_ms=30_000)
        assert time.monotonic() - started < 20, "отказ ждали до таймаута"


def test_a_probe_beaten_by_a_later_calculation_still_gets_the_result(monkeypatch) -> None:
    """Проба зовёт расчёт, следом его перебивает другой: `calculate` отдаёт null,
    `settledCalculate` — итог последнего."""
    with _page(monkeypatch, _slow(0.3)) as page:
        browser.wait_for_result(page)
        beaten = page.evaluate("async () => { const mine = calculate(); calculate(); "
                               "return await mine }")
        assert beaten is None, "перебитый расчёт должен отдавать null — иначе проверять нечего"
        got = page.evaluate("async () => { const mine = settledCalculate(); calculate(); "
                            "const r = await mine; return {rows: r.tep.rows.length, "
                            "idle: calcIdle(), same: r === lastResult} }")
        assert got["rows"] > 0 and got["idle"] and got["same"], got


def test_the_wait_is_the_one_used_by_the_page_tests() -> None:
    """Пауза «на глаз» в стенде страницы — второй ответ на «расчёт закончился».

    Стенды страницы ждут итог одним помощником. Пауза, которая не про расчёт
    (анимация шторки, прокрутка), остаётся с пометкой «пауза не про расчёт» в
    той же строке: тогда видно, что она ждёт, и её не примут за ожидание итога.
    """
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        # Стенд основной страницы: открывает корень поднятого приложения. Торги,
        # КРТ, страницы с диска (`file://`) считают иначе и сюда не входят.
        if "sync_playwright" not in text or not re.search(MAIN_PAGE_GOTO, text):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if "wait_for_timeout(" in line and "пауза не про расчёт" not in line:
                offenders.append(f"{path.name}:{number}")
    assert not offenders, "пауза вместо ожидания итога: " + ", ".join(offenders)
