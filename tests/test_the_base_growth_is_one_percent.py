"""Рост цены квартир до РВЭ по умолчанию — 1 %/мес. (владелец, 29.09.2026).

Умолчание одно: `DEFAULT_INPUTS`. Его видит форма, и его же берёт расчёт,
когда поля во вводных нет, — своей константы у расчёта нет. Сохранённый
проект накладывается на умолчание: явно сохранённые 1,5 остаются 1,5, а
проект без поля получает 1,0. Рост после РВЭ и рост объектов ОСЗ не меняются.
Запуск: python3 -m pytest tests/test_the_base_growth_is_one_percent.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
import test_saved_state_migration as saved_state  # noqa: E402

KEY = "monthly_growth_pre_pct"


def _inputs(**extra):
    x = dict(core.DEFAULT_INPUTS)
    x.update({"purchase_price_mln": 1000})
    x.update(extra)
    return x


def _tep():
    return {key: dict(value) for key, value in core.TEP_DEFAULT.items()}


def _apartments(x):
    return core.build_operating_model(x, _tep(), [])["revenue_by_product"]["apartments"]


def test_the_default_is_one_percent_and_the_rest_stays():
    assert core.DEFAULT_INPUTS[KEY] == 1.0
    assert core.DEFAULT_INPUTS["monthly_growth_post_pct"] == 0.25
    # Объекты ОСЗ ведут свой рост и правкой квартир не задеты.
    for prefix, pre, post in (("offices", 1.5, 0.25), ("retail", 1.5, 0.25),
                              ("sports", 1.5, 0.25), ("above_parking", 0.75, 0.2)):
        assert core.DEFAULT_INPUTS[f"{prefix}_growth_pre_pct"] == pre, prefix
        assert core.DEFAULT_INPUTS[f"{prefix}_growth_post_pct"] == post, prefix


def test_a_calculation_without_the_field_takes_the_default():
    missing = _inputs()
    missing.pop(KEY)
    assert _apartments(missing) == pytest.approx(_apartments(_inputs(**{KEY: 1.0})))
    assert _apartments(missing) != pytest.approx(_apartments(_inputs(**{KEY: 1.5})))
    # Пустое поле — тоже «нет значения», а не ноль.
    assert _apartments(_inputs(**{KEY: ""})) == pytest.approx(_apartments(missing))


def test_the_fallback_reads_the_one_default(monkeypatch):
    """Подделка: своя константа в расчёте прошла бы тест выше, но не этот."""
    monkeypatch.setitem(core.DEFAULT_INPUTS, KEY, 2.0)
    missing = _inputs()
    missing.pop(KEY)
    assert _apartments(missing) == pytest.approx(_apartments(_inputs(**{KEY: 2.0})))


def test_the_page_carries_the_same_default():
    restored = saved_state.restore({"inputs": {}, "tep": {}, "scenario": "base"})["inputs"]
    assert restored[KEY] == 1.0


def test_a_saved_project_keeps_its_own_growth():
    kept = saved_state.restore(
        {"inputs": {KEY: 1.5, "apartment_price_th": 420}, "tep": {}, "scenario": "base"})["inputs"]
    assert kept[KEY] == 1.5
    fresh = saved_state.restore(
        {"inputs": {"apartment_price_th": 420}, "tep": {}, "scenario": "base"})["inputs"]
    assert fresh[KEY] == 1.0


def test_the_rendered_form_shows_one():
    """То, что видно: поле формы на отрисованной странице, а не литерал."""
    import browser as browser_helper

    chrome = browser_helper.chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import uvicorn

    import main as wrapper

    config = uvicorn.Config(wrapper.app, host="127.0.0.1", port=18751, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "локальный сервер не поднялся"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto("http://127.0.0.1:18751/", wait_until="networkidle")
            shown = page.evaluate(
                f"() => (document.querySelector('.field[data-field=\"{KEY}\"] input') || {{}}).value")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not errors, errors
    assert shown is not None, "поля роста до РВЭ на форме нет"
    assert float(shown.replace(",", ".")) == 1.0, shown
