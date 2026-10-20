"""Бюджет месяца загружается со страницы мониторинга — проверка на отрисованной странице.

Владелец присылает план-факт БДДС раз в месяц; из него сводка руководству
берёт план стройки и коммерческих расходов. Кнопка должна быть видна в
блоке загрузок, файл — лечь в проект, а неверный файл — получить отказ с
причиной, а не молчание.

Запуск: python3 -m pytest tests/test_the_monitor_takes_the_month_budget.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_monitor as monitor  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402
from test_management_report_model import _rss_book, budget_book  # noqa: E402

PORT = 18797


def test_the_budget_is_uploaded_from_the_rendered_page(tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    good = tmp_path / "бюджет.xlsx"
    good.write_bytes(budget_book())
    wrong = tmp_path / "рсс.xlsx"
    wrong.write_bytes(_rss_book([]))

    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script(
                "localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/monitor", wait_until="domcontentloaded")
            tab.fill("#project", "Гродненская")
            if not tab.is_visible("#budgetBtn"):
                tab.click("#setupHead")
            assert tab.is_visible("#budgetBtn")
            assert tab.inner_text("#budgetBtn") == "Загрузить бюджет месяца"

            tab.set_input_files("#budget", str(wrong))
            tab.click("#budgetBtn")
            tab.wait_for_function(
                "document.getElementById('weeklyMsg').textContent.includes('шапки')")
            refused = tab.inner_text("#weeklyMsg")

            tab.set_input_files("#budget", str(good))
            tab.click("#budgetBtn")
            tab.wait_for_function(
                "document.getElementById('weeklyMsg').textContent.includes('Бюджет загружен')")
            stored = tab.inner_text("#weeklyMsg")
        finally:
            browser.close()

    assert not errors, errors
    assert "не нашлось шапки с месяцами" in refused
    assert stored == "Бюджет загружен, в нём месяцы: 2026-09, 2026-10."
    assert len(list((tmp_path / "monitor" / "Гродненская" / "budget").glob("*.xlsx"))) == 1
