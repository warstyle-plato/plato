"""Мои проекты: вкладки кабинета, порядок и поиск — на отрисованной странице.

Здесь закреплено:

- кабинет разложен вкладками «Мои проекты», «Тарифы и доступ»,
  «Администрирование»; последнюю видит только тот, кого сервер назвал
  администратором (`is_admin` из `/access/me`);
- по умолчанию сверху последние изменённые; смена порядка меняет порядок строк,
  а выбранный порядок браузер помнит после перезагрузки;
- поиск одной строкой по части названия или кадастрового номера оставляет
  нужные проекты и говорит, когда не нашлось ничего.

Запуск: python3 -m pytest tests/test_the_cabinet_finds_and_orders_projects.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper

core = _wrapper.core
CHAT, ADMIN = 9191, 778


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:cabinet-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    yield


def _names(page) -> list[str]:
    return page.eval_on_selector_all("#projectsBody tr td:first-child b", "els => els.map(e => e.textContent)")


def test_projects_are_ordered_and_found_on_the_drawn_page():
    pytest.importorskip("playwright.sync_api")
    import browser
    from playwright.sync_api import sync_playwright

    # Сохраняются по очереди: «Бутово» — раньше всех, «Нагатино» — последним.
    for name, cadastral in (("Бутово", ["50:21:0110101:15"]),
                            ("Абрамцево", ["50:05:0070101:42"]),
                            ("Нагатино", ["77:05:0002001:1001", "77:05:0002001:1002"])):
        core.project_save(CHAT, name, {"inputs": {}}, {}, cadastral)
        time.sleep(0.01)
    session = core._telegram_session(CHAT, [])
    path = browser.chromium_or_skip()
    with (browser.serve(core.app, 18978) as base, sync_playwright() as pw,
          pw.chromium.launch(executable_path=str(path)) as engine):
        page = engine.new_page(viewport={"width": 1200, "height": 900})
        page.add_init_script(
            f"localStorage.setItem('developaid_web_session', {json.dumps(session)})")
        page.goto(base, wait_until="networkidle")
        page.click("#projectsButton")
        page.wait_for_function("document.querySelectorAll('#projectsBody tr td b').length === 3")
        assert page.locator("#cabTabProjects").is_visible()
        assert not page.locator("#cabTabAdmin").is_visible(), "не администратору вкладка не нужна"
        assert _names(page) == ["Нагатино", "Абрамцево", "Бутово"]

        page.select_option("#projectsSort", "name")
        assert _names(page) == ["Абрамцево", "Бутово", "Нагатино"]
        page.select_option("#projectsSort", "saved_asc")
        assert _names(page) == ["Бутово", "Абрамцево", "Нагатино"]

        page.fill("#projectsSearch", "0002001:100")
        assert _names(page) == ["Нагатино"]
        page.fill("#projectsSearch", "абрам")
        assert _names(page) == ["Абрамцево"]
        page.fill("#projectsSearch", "Мытищи")
        assert _names(page) == []
        assert "ничего не нашлось" in page.inner_text("#projectsBody")

        # Порядок помнит браузер.
        page.reload(wait_until="networkidle")
        page.click("#projectsButton")
        page.wait_for_function("document.querySelectorAll('#projectsBody tr td b').length === 3")
        assert page.input_value("#projectsSort") == "saved_asc"
        assert _names(page) == ["Бутово", "Абрамцево", "Нагатино"]

        # «Тарифы» открывают свою вкладку; проектов на ней нет.
        page.click(".cab-close")
        page.click("#tariffsButton")
        page.wait_for_function("document.getElementById('tariffsBox').textContent.includes('Подписка')")
        assert page.locator("#tariffsBox").is_visible()
        assert not page.locator("#projectsBody").is_visible()
        page.close()


def test_the_admin_tab_is_shown_only_to_the_admin():
    pytest.importorskip("playwright.sync_api")
    import browser
    from playwright.sync_api import sync_playwright

    session = core._telegram_session(ADMIN, [])
    path = browser.chromium_or_skip()
    with (browser.serve(core.app, 18979) as base, sync_playwright() as pw,
          pw.chromium.launch(executable_path=str(path)) as engine):
        page = engine.new_page(viewport={"width": 1200, "height": 900})
        page.add_init_script(
            f"localStorage.setItem('developaid_web_session', {json.dumps(session)})")
        page.goto(base, wait_until="networkidle")
        page.click("#tariffsButton")
        page.wait_for_selector("#cabTabAdmin", state="visible")
        assert not page.locator(".grant-form").is_visible(), "выдача доступа — на своей вкладке"
        page.click("#cabTabAdmin")
        assert page.locator(".grant-form").is_visible()
        assert not page.locator("#tariffsBox").is_visible()
        page.close()
