"""Темп продаж: на странице — переключатель мер, в документе — три графика подряд.

«На странице переключением как в отчёте о продажах, а в пдф подряд три
графика» (владелец, 22.10.2026). Разметка одна; что видно — решает стиль:
страница показывает одну панель и кнопки, документ — все панели без кнопок.

Запуск: python3 -m pytest tests/test_report_sales_pace_switch.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_analytics import _full  # noqa: E402

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
from developaid_report_page import REPORT_PAGE  # noqa: E402

VISIBLE = """() => [...document.querySelectorAll('.switch-charts .pane')]
    .filter(p => p.getBoundingClientRect().height > 0).map(p => p.dataset.pane)"""
BUTTONS = """() => [...document.querySelectorAll('.switch-charts .switch button')]
    .filter(b => b.getBoundingClientRect().height > 0).length"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_the_page_switches_measures_and_the_document_shows_all_three():
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    body = report.render_html(_full())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1100, "height": 900})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; "
                         "document.getElementById('privateArea').classList.remove('hidden') }", body)
            assert tab.evaluate(VISIBLE) == ["area"]
            assert tab.evaluate(BUTTONS) == 3
            tab.click("#reportBox .switch-charts .switch button[data-pane='units']")
            assert tab.evaluate(VISIBLE) == ["units"]
            assert tab.evaluate("document.querySelector('.switch button.on').dataset.pane") == "units"
            tab.click("#reportBox .switch-charts .switch button[data-pane='amount']")
            assert tab.evaluate(VISIBLE) == ["amount"]
            # Документ — тот же стиль, что печатает PDF: все меры подряд, кнопок нет.
            doc = browser.new_page()
            doc.set_content(f"<style>{report.REPORT_STYLE}</style>{body}")
            assert doc.evaluate(VISIBLE) == ["area", "units", "amount"]
            assert doc.evaluate(BUTTONS) == 0
        finally:
            browser.close()
