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


def test_the_first_column_is_not_crushed_on_a_tablet():
    """На ширине планшета (760px) первая колонка таблицы с шестью столбцами
    сжималась до буквы в строку («Э-с-к-р-о-у»): у первой колонки есть
    минимальная ширина, слова в ней читаются."""
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    from test_management_report_funding import _project, _sales, PROJECT

    _project()
    _sales()
    body = report.render_html(report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК"))
    assert "Эскроу, очередь" in body
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 760, "height": 1200})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; "
                         "document.getElementById('privateArea').classList.remove('hidden') }", body)
            width, lines, outside = tab.evaluate("""() => {
                const th = [...document.querySelectorAll('#reportBox th')]
                    .find(c => c.textContent.trim() === 'Эскроу, очередь');
                const r = th.getBoundingClientRect();
                const edge = document.getElementById('reportBox').getBoundingClientRect().right;
                const out = [...document.querySelectorAll('#reportBox table')]
                    .filter(t => t.getBoundingClientRect().right > edge + 0.5).length;
                return [r.width, Math.round(r.height / (parseFloat(getComputedStyle(th).fontSize) * 1.4)), out] }""")
        finally:
            browser.close()
    assert width >= 100, f"первая колонка сжата до {width}px"
    assert lines <= 2, f"заголовок первой колонки разбит на {lines} строк"
    # Шесть колонок не влезают в 760px — таблица прокручивается внутри рамки, а не вылезает.
    assert outside == 0, "таблица вылезает за карточку отчёта"
