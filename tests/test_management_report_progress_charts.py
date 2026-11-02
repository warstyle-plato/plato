"""Графики выполнения ГПР в сводке появляются только со второго замера.

Владелец (02.11.2026) о разделе «Стройка»: при одном ГПР-факте график
«план и факт на дату каждого ГПР-факта» — одна точка, а не динамика. Графики
(кривая и «Разделы графика») скрыты, пока дат ГПР-факта меньше двух; таблицы
«План к дате / Выполнено / Отставание» остаются. Проверяется отрисованная
страница (тот же ``render_html`` уходит в PDF). Данные — синтетика.

Запуск: python3 -m pytest tests/test_management_report_progress_charts.py -q
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
from browser import chromium_or_skip  # noqa: E402
from test_management_report_model import PROJECT, _gpr_book  # noqa: E402

CURVE = "Выполнение по графику работ: план и факт на дату каждого ГПР-факта"
SECTIONS = "Разделы графика: план и факт выполнения"
NOTE = "График выполнения появится, когда будет второй замер"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _two_sections(progress: dict[str, float], cash: bool = True) -> bytes:
    """Книга ГПР с двумя разделами — чтобы рисовался и график разделов."""
    book = load_workbook(io.BytesIO(_gpr_book(progress, cash=cash)))
    book["ГПР"].cell(row=6, column=3, value="Фасадные работы")
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def _built(fact_days: list[str]) -> dict:
    monitor.store_schedule(PROJECT, _two_sections({}), None, "2026-07-01")
    for share, day in enumerate(fact_days, 1):
        monitor.store_schedule_fact(
            PROJECT, _two_sections({"1": 0.2 * share, "2": 0.1 * share}, cash=False), day)
    return report.build(PROJECT, "week", "2026-10-18")


def _rendered(page_html: str) -> dict:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page()
            page.set_content(page_html)
            return page.evaluate("""() => ({
                captions: [...document.querySelectorAll('figure')]
                    .filter(f => f.getBoundingClientRect().height > 0)
                    .map(f => (f.querySelector('figcaption') || {}).textContent || ''),
                text: document.body.innerText,
            })""")
        finally:
            browser.close()


def test_one_measurement_shows_tables_without_charts():
    built = _built(["2026-10-16"])
    assert not report.progress_charts_shown(built["physical"])
    seen = _rendered(report.render_html(built))
    assert CURVE not in seen["captions"] and SECTIONS not in seen["captions"]
    # Таблицы остаются, вместо графика — одна понятная фраза.
    assert "План к дате" in seen["text"] and "По разделам графика работ" in seen["text"]
    assert NOTE in seen["text"]


def test_two_measurements_bring_both_charts_back():
    built = _built(["2026-10-09", "2026-10-16"])
    assert report.progress_charts_shown(built["physical"])
    seen = _rendered(report.render_html(built))
    assert CURVE in seen["captions"] and SECTIONS in seen["captions"]
    assert NOTE not in seen["text"]


def test_the_predicate_counts_distinct_days():
    # Подделка: две записи одной даты — всё ещё один замер.
    same_day = {"series": {"fact": [{"day": "2026-10-16", "plan": 0.2, "fact": 0.3}] * 2}}
    assert not report.progress_charts_shown(same_day)
    assert report._physical_chart(same_day) == ""
    assert not report.progress_charts_shown({})
