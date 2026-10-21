"""Сводка на телефоне не вылезает за край страницы.

«И вылезает эта история за границы» (владелец, 21.10.2026, снимок с телефона):
таблица бюджета месяца по статьям раздвигала страницу вбок. На узком экране
широкая таблица прокручивается внутри своей рамки, а страница остаётся по
ширине экрана.

Запуск: python3 -m pytest tests/test_report_fits_a_phone.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_budget_articles import _setup  # noqa: E402

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
from developaid_report_page import REPORT_PAGE  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_the_report_fits_a_phone_screen():
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    body = report.render_html(_setup())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 844})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; document.getElementById('privateArea').classList.remove('hidden') }", body)
            visible = tab.evaluate("""() => [...document.querySelectorAll('#reportBox table')]
                .filter(t => t.getBoundingClientRect().width > 0).length""")
            # Первая колонка читается словами, а не буквой в строку.
            narrow = tab.evaluate("""() => Math.min(...[...document.querySelectorAll(
                '#reportBox table td:first-child')].filter(c => c.textContent.trim().length > 12)
                .map(c => c.getBoundingClientRect().width))""")
            page_width = tab.evaluate("document.documentElement.scrollWidth")
            box = tab.evaluate("document.getElementById('reportBox').getBoundingClientRect().right")
            # Каждая таблица — в пределах карточки (широкая прокручивается внутри).
            outside = tab.evaluate("""() => {
                const edge = document.getElementById('reportBox').getBoundingClientRect().right;
                return [...document.querySelectorAll('#reportBox table')]
                    .filter(t => t.getBoundingClientRect().right > edge + 0.5).length }""")
        finally:
            browser.close()
    assert "По статьям" in body or "статья" in body.lower()
    assert page_width <= 390, f"страница шире экрана: {page_width}px"
    assert box <= 390
    assert visible > 5, "отчёт должен быть виден, иначе проверка пустая"
    assert outside == 0, "таблица вылезает за карточку отчёта"
    assert narrow >= 120, f"первая колонка сжата до {narrow}px"
