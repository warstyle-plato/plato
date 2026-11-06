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

# Монитор и сводка — только по ключу администратора (решение владельца
# 02.11.2026): страница и маршруты открываются ключом, а не сессией.
ADMIN_TEST_KEY = "browser-admin-key"


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", ADMIN_TEST_KEY)


def _october_november() -> bytes:
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    for column, name in ((5, "Октябрь 2026"), (8, "Ноябрь 2026")):
        sheet.cell(row=4, column=column, value=name)
        sheet.cell(row=5, column=column, value="ПЛАН")
        sheet.cell(row=5, column=column + 1, value="ФАКТ")
    for r, name in enumerate(("Стоимость строительства и проектирования",
                              "Содержание службы заказчика", "Коммерческие расходы"), 6):
        sheet.cell(row=r, column=1, value=name)
        sheet.cell(row=r, column=5, value=-1e6)
        sheet.cell(row=r, column=8, value=-1e6)
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def test_the_budget_is_uploaded_from_the_rendered_page(tmp_path, monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    good = tmp_path / "бюджет.xlsx"
    good.write_bytes(budget_book())
    later = tmp_path / "бюджет-ноябрь.xlsx"
    later.write_bytes(_october_november())
    wrong = tmp_path / "рсс.xlsx"
    wrong.write_bytes(_rss_book([]))

    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script(
                "localStorage.setItem('developaid_web_session','проба');localStorage.setItem('plato_projects_key','browser-admin-key')")
            tab.goto(f"{base}/monitor", wait_until="domcontentloaded")
            tab.fill("#project", "Гродненская")
            if not tab.is_visible("#budgetBtn"):
                tab.click("#setupHead")
            assert tab.is_visible("#budgetBtn")
            assert tab.inner_text("#budgetBtn") == "Загрузить бюджет месяца"

            tab.set_input_files("#budget", str(wrong))
            tab.click("#budgetBtn")
            tab.wait_for_function(
                "document.getElementById('budgetMsg').textContent.includes('шапки')")
            refused = tab.inner_text("#budgetMsg")

            tab.set_input_files("#budget", str(good))
            tab.click("#budgetBtn")
            tab.wait_for_function(
                "document.getElementById('budgetMsg').textContent.includes('Бюджет загружен')")
            stored = tab.inner_text("#budgetMsg")
            tab.wait_for_function(
                "document.getElementById('budgetList').textContent.includes('Убрать')")
            first_list = tab.inner_text("#budgetList")

            # Второй файл — «октябрь–ноябрь»: загружен последним, план октября
            # теперь его. Ошибочный — убирается кнопкой и возвращается.
            tab.set_input_files("#budget", str(later))
            tab.click("#budgetBtn")
            tab.wait_for_function(
                "document.getElementById('budgetList').textContent.includes('Месяцы 10.2026, 11.2026')")
            both = tab.inner_text("#budgetList")
            tab.once("dialog", lambda dialog: dialog.accept())
            tab.click("[data-budget-remove$='2026-10_2026-11.xlsx']")
            tab.wait_for_function(
                "document.getElementById('budgetList').textContent.includes('Убранные')")
            after_remove = tab.inner_text("#budgetList")
            removed_msg = tab.inner_text("#budgetMsg")
            tab.click("[data-budget-restore]")
            tab.wait_for_function(
                "!document.getElementById('budgetList').textContent.includes('Убранные')")
            restored = tab.inner_text("#budgetList")
        finally:
            browser.close()

    assert not errors, errors
    assert "не нашлось шапки с месяцами" in refused
    assert stored == ("Бюджет загружен, лист «Sheet», в нём месяцы: 2026-09, 2026-10. "
                      "План этих месяцев сводка теперь берёт из этого файла.")
    assert "план в сводку: 09.2026, 10.2026" in first_list
    # Загруженный последним забирает октябрь; у первого остаётся сентябрь.
    assert "план в сводку: 10.2026, 11.2026" in both
    assert "план в сводку: 09.2026 " in both
    assert "Убранные бюджеты" in after_remove
    assert "план в сводку: 09.2026, 10.2026" in after_remove
    assert removed_msg.startswith("Бюджет убран из расчёта")
    assert "план в сводку: 10.2026, 11.2026" in restored
    folder = tmp_path / "monitor" / "Гродненская" / "budget"
    assert len(list(folder.glob("*.xlsx"))) == 2
