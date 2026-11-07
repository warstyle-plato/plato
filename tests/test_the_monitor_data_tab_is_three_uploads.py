"""Вкладка «Данные проекта» — основные загрузки на виду, прочее свёрнуто.

«Сейчас вкладка данных по проекту в Мониторе перегружена, это были частные
случаи. По факту нужен ГПР с динамикой, РСС и бюджеты. Отчёт со стройки читает
бот» (владелец, 20.10.2026). Решения владельца: ручной отчёт со стройки и
продажи убраны; финансовая книга — на виду рядом с ГПР; PM, rebaseline,
реестр ГУ и монолитный цикл — в свёрнутом блоке «Прочие загрузки».

Новое поручение владельца: накопительные ведомости загружаются одним
ZIP-архивом в Монитор. Это четвёртая основная форма рядом с РСС.

Проверяется отрисованная страница: что видно, что спрятано, что убрано, и что
ни один обработчик не ссылается на убранное поле (иначе скрипт падает и
ломает все кнопки разом).

Запуск: python3 -m pytest tests/test_the_monitor_data_tab_is_three_uploads.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from browser import chromium_or_skip, serve  # noqa: E402

PORT = 18800
VISIBLE = ["gpr", "finance", "baselineBtn", "gprFact", "gprFactBtn", "finRepl",
           "finReplBtn", "rss", "rssBtn", "cumulativeFile", "cumulativeDate",
           "cumulativeUpload", "budget", "budgetBtn"]
FOLDED = ["rebase", "rebaseBtn", "retention", "retentionBtn", "stageObj", "stageBtn"]
# PM is off by owner decision: its upload stays hidden even in the folded block.
HIDDEN = ["pm"]
GONE = ["sales", "salesBtn", "salesMonth", "salesRowBtn", "dailyText", "dailyBtn"]


def test_the_data_tab_on_the_rendered_page(monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)

    # Монитор — только по ключу администратора (решение владельца 02.11.2026).

    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "browser-admin-key")
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба');localStorage.setItem('plato_projects_key','browser-admin-key')")
            tab.goto(f"{base}/monitor", wait_until="domcontentloaded")
            tab.wait_for_function("document.getElementById('budgetBtn')!==null")
            if not tab.is_visible("#budgetBtn"):
                tab.click("#setupHead")
            titles = tab.eval_on_selector_all(
                "#setupCard .box > b", "els=>els.map(e=>e.textContent)")
            shown = {name: tab.is_visible(f"#{name}") for name in VISIBLE + FOLDED}
            present = {name: tab.locator(f"#{name}").count() for name in GONE}
            tab.click("#otherUploads summary")
            opened = {name: tab.is_visible(f"#{name}") for name in FOLDED}
            hidden = {name: tab.is_visible(f"#{name}") for name in HIDDEN}
        finally:
            browser.close()

    assert not errors, errors
    assert titles == ["ГПР и финансовая книга", "РСС · каждую неделю",
                      "Накопительные · КС-6а", "Бюджет месяца · раз в месяц"]
    assert all(shown[name] for name in VISIBLE), shown
    assert not any(shown[name] for name in FOLDED), shown
    assert all(opened.values()), opened
    assert not any(hidden.values()), hidden
    assert not any(present.values()), present
