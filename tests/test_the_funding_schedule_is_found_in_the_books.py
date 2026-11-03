"""График финансирования — из книг, которые Монитор уже хранит.

Владелец, 27.10.2026, на «График финансирования не загружен в Монитор:
исполнять сверять не с чем»: «Откуда я возьму эти файлы и данные? Они все есть
или в НКЛ, или в РСС, или в модели. Ничего нового ты не получишь».

Проверки:
- лист «ГФ_до конца стр» в финмодели Монитора (baseline/finance.xlsx) — это
  график, без отдельной загрузки; сводка называет, откуда он взят;
- лист ищется по оглавлению книги, а не по имени файла: книга без листа — не
  график;
- отдельно загруженный график на ту же дату главнее;
- графика нет нигде — текст полной фразой называет, в каких книгах искали и
  куда загрузить, без «исполнять сверять» и без имени листа.

Запуск: python3 -m pytest tests/test_the_funding_schedule_is_found_in_the_books.py -q
"""
from __future__ import annotations

import datetime
import os
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
from test_the_funding_schedule_is_checked_against_payments import PAYMENTS, PROJECT  # noqa: E402

END = datetime.date(2026, 10, 25)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _finance_model(day="2026-10-01"):
    """Финмодель Монитора с листом графика среди своих листов."""
    place = monitor._project_dir(PROJECT) / "baseline" / "finance.xlsx"
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_bytes(fx.book())
    stamp = datetime.datetime.fromisoformat(day).timestamp()
    os.utime(place, (stamp, stamp))
    return place


def test_the_schedule_in_the_finance_model_needs_no_upload():
    monitor.store_estimate(PROJECT, fx.rss(PAYMENTS), "2026-10-25")
    _finance_model()
    got = fs.execution(PROJECT, END)
    assert got["state"] == "ok" and got["versions"] == ["2026-10-01"]
    assert got["sources"]["2026-10-01"] == {"where": "финмодель (финансовая база Монитора)",
                                            "file": "finance.xlsx"}
    september = next(m for m in got["months"] if m["month"] == "2026-09")
    assert september["plan"] == pytest.approx(231.85 * fx.M)
    words = report._schedule_sources(got)
    assert words == ("График взят из: финмодель (финансовая база Монитора) (файл "
                     "finance.xlsx), версия от 01.10.2026.")


def test_a_book_without_the_sheet_is_not_a_schedule():
    # Отчёт РСС лежит, листа графика в нём нет — графика нет.
    monitor.store_estimate(PROJECT, fx.rss(PAYMENTS), "2026-10-25")
    got = fs.execution(PROJECT, END)
    assert got["state"] == "missing"
    reason = got["reason"]
    assert reason.startswith("Графика финансирования нет ни в одной книге, которую хранит "
                             "Монитор, поэтому сравнить план оплат с оплаченным не с чем.")
    assert "Искали в книгах: отчёты РСС (1)." in reason
    # Сводке руководству имена листов не пишутся (docs/plain_language.md).
    assert "лист «" not in reason
    assert "Не загружены: финмодель (финансовая база Монитора)" in reason
    assert reason.endswith("блок «Бюджет месяца», кнопка «Загрузить график».")
    assert "исполнять сверять" not in reason
    # В сводке раздела нет, пока график не загружен (владелец, 28.10.2026: «Что это в
    # принципе такое и зачем оно нужно»): абзац о поиске руководству не нужен.
    assert got["absent"] and report._schedule_html(got) == ""
    # А загруженный, но не прочитанный график — раздел с причиной.
    broken = {"state": "missing", "reason": "Не загружен отчёт РСС с реестром платежей."}
    assert "Не загружен отчёт РСС" in report._schedule_html(broken)


def test_an_uploaded_schedule_wins_on_the_same_day():
    monitor.store_estimate(PROJECT, fx.rss(PAYMENTS), "2026-10-25")
    _finance_model("2026-09-23")
    fs.store(PROJECT, fx.book(), "2026-09-23", "График.xlsx")
    got = fs.execution(PROJECT, END)
    assert got["sources"]["2026-09-23"]["where"] == "загруженный график финансирования"
