"""Статья графика «… (учтено в п.X)» сверяется внутри статьи X, а раздел сводки
показывает статьи одной таблицей нарастающим итогом.

Владелец, 28.10.2026, на сводку: «4!!! разных блока в Исполнении графика …
зачем 4 и откуда эти 4???». В графике от 23.09 строки «2.2.2.1 Монолит
надземной части (учтено в п.2.2.1.4)» и подобные — без плана: план стоит в
названной статье. Отдельной строкой они давали «оплачено без плана», а
названная статья — недоплату.

Запуск: python3 -m pytest tests/test_the_funding_schedule_folds_lines_counted_elsewhere.py -q
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_funding_schedule as fs  # noqa: E402
import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import funding_schedule_fixture as fx  # noqa: E402
from test_the_funding_schedule_is_checked_against_payments import END, PROJECT  # noqa: E402

M = fx.M
D = datetime.date
ROWS = fx.ROWS + [("2.2.2.1.", "Монолит надземной части\n(учтено в п.2.2.1.7)", "", None,
                   None, None, None, None)]
PAYMENTS = [(D(2026, 9, 5), 4 * M, "2.2.1.7"), (D(2026, 9, 6), 6 * M, "2.2.2.1"),
            (D(2026, 10, 6), 2 * M, "2.2.2.1"), (D(2026, 9, 7), 100 * M, "2.2.2.6")]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _run():
    monitor.store_estimate(PROJECT, fx.rss(PAYMENTS), "2026-10-25")
    fs.store(PROJECT, fx.book(rows=ROWS), "2026-09-01", "График финансирования.xlsx")
    return fs.execution(PROJECT, END)


def test_a_line_counted_elsewhere_is_checked_inside_that_line():
    got = _run()
    september = next(m for m in got["months"] if m["month"] == "2026-09")
    codes = {line["code"]: line for line in september["lines"]}
    assert "2.2.2.1" not in codes
    monolith = codes["2.2.1.7"]
    assert monolith["plan"] == pytest.approx(13 * M)
    assert monolith["fact"] == pytest.approx(10 * M)
    assert any("с оплатами по 2.2.2.1" in note for note in monolith["notes"])


def test_the_report_shows_articles_once_cumulatively():
    page = report._schedule_html(_run())
    assert page.count("По статьям графика") == 1
    # Монолит: план сен+окт 13+23=36, оплачено 4+6+2=12 — нарастающим итогом.
    row = next(chunk for chunk in page.split("<tr>") if "2.2.1.7 Монолитные работы" in chunk)
    assert "36,0 млн ₽" in row and "12,0 млн ₽" in row
    assert "2.2.2.1 Монолит надземной части" not in page


def test_both_tables_end_with_a_total():
    """Владелец, 28.10.2026: «Итого где строка»."""
    got = _run()
    page = report._schedule_html(got)
    months = [m for m in got["months"] if m.get("plan") is not None]
    plan = sum(m["plan"] for m in months)
    fact = sum(m["fact"] for m in got["months"])
    total = next(chunk for chunk in page.split("<tr>") if "<b>Итого</b>" in chunk)
    assert report._rub(plan) in total and report._rub(fact) in total
    lines = next(chunk for chunk in page.split("<tr>")
                 if "Итого по всем статьям графика" in chunk)
    # Оплачено по статьям — то же, что по месяцам: статьи и месяцы одной сверки.
    assert report._rub(fact) in lines
