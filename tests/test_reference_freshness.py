"""Справочники устаревают тихо — про это должно напоминать.

Расчёт идёт, числа выглядят как обычно, а под ними прошлогодний тариф. Ни
ошибки, ни предупреждения: заметить можно только сверкой с первоисточником, до
которой обычно не доходит. Так и живут решения, принятые по устаревшей ставке.

Поэтому у каждого справочника объявлен срок жизни — квартал, год или четыре
года кадастровой оценки, — и раз в день сводка администраторам говорит, что
пора обновить. Проверка ничего не скачивает: она сравнивает объявленный срок с
календарём, а документ всё равно приносит человек.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import main as wrapper  # noqa: E402


def keys(rows):
    return {row["key"] for row in rows}


# --- что проверяется ------------------------------------------------------------

def test_every_reference_that_expires_is_watched():
    """Три источника, которые заменяются по календарю: цены Подмосковья,
    кадастровая оценка и Кзатр льготы МПТ."""
    watched = keys(core.reference_freshness(date(2026, 8, 14)))
    assert {"mo_market_price", "mo_upks_land", "mo_upks_oks", "mpt_kzatr"} <= watched


def test_each_row_says_what_it_is_and_until_when():
    for row in core.reference_freshness(date(2026, 8, 14)):
        assert row["title"] and row["current"]
        assert row["valid_until"], row["key"]
        assert row["hint"], row["key"]


def test_the_source_document_is_named():
    """Обновлять пойдут по документу, а не по названию справочника."""
    rows = {row["key"]: row for row in core.reference_freshness(date(2026, 8, 14))}
    assert "Комитет" in rows["mo_market_price"]["source"] or rows["mo_market_price"]["source"]
    assert "ДИиПП" in rows["mpt_kzatr"]["source"]


# --- срок наступает -------------------------------------------------------------

def test_the_cadastral_valuation_expires_on_its_own_date():
    """Новый тур оценки земли применяется с 01.01.2027 — до него старый годен."""
    before = {row["key"]: row for row in core.reference_freshness(date(2026, 12, 31))}
    after = {row["key"]: row for row in core.reference_freshness(date(2027, 1, 1))}
    assert before["mo_upks_land"]["stale"] is False
    assert after["mo_upks_land"]["stale"] is True


def test_the_oks_valuation_has_its_own_year():
    """У ОКС свой тур: он живёт на год дольше земельного."""
    rows = {row["key"]: row for row in core.reference_freshness(date(2027, 6, 1))}
    assert rows["mo_upks_land"]["stale"] is True
    assert rows["mo_upks_oks"]["stale"] is False


def test_the_market_prices_expire_with_the_year():
    """Распоряжение по ценам выходит на период; год сменился — нужен новый."""
    assert not [row for row in core.reference_freshness(date(2026, 8, 14))
                if row["key"] == "mo_market_price" and row["stale"]]
    assert [row for row in core.reference_freshness(date(2027, 3, 1))
            if row["key"] == "mo_market_price" and row["stale"]]


def test_the_kzatr_asks_for_the_quarterly_index():
    """Приказ от 10.03.2026 ввёл поквартальную корректировку с 2026-Q2:
    дальше значение обязано подставляться индексом, а не жить константой."""
    rows = {row["key"]: row for row in core.reference_freshness(date(2026, 8, 14))}
    assert rows["mpt_kzatr"]["stale"] is True
    assert "индекс" in rows["mpt_kzatr"]["hint"].lower()


# --- напоминание доходит --------------------------------------------------------

def test_the_endpoint_lists_what_is_stale():
    from fastapi.testclient import TestClient

    data = TestClient(core.app).get("/reference/freshness").json()
    assert data["checked_at"]
    assert isinstance(data["stale"], list)
    assert len(data["references"]) >= 4


def test_the_reminder_reaches_the_owner():
    """Напоминание, которое видно только в логе, — это напоминание, которого
    нет: строка уходит в `/status` и в суточную сводку администраторам."""
    line = wrapper._stale_reference_line()
    assert "Пора обновить справочники" in line
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert source.count("_stale_reference_line()") >= 3  # объявление + два места


def test_a_fresh_shelf_says_nothing(monkeypatch):
    """Ежедневное «всё в порядке» перестают читать через неделю.

    Патчим `wrapper.core`, а не `main_legacy`: обёртка грузит движок отдельным
    экземпляром модуля, и это разные объекты."""
    monkeypatch.setattr(wrapper.core, "stale_references", lambda *a, **kw: [])
    assert wrapper._stale_reference_line() == ""


def test_a_broken_check_does_not_break_the_status(monkeypatch):
    """Статус важнее напоминания: упало — молчим, а не роняем ответ."""
    def boom(*args, **kwargs):
        raise RuntimeError("справочник не читается")

    monkeypatch.setattr(wrapper.core, "stale_references", boom)
    assert wrapper._stale_reference_line() == ""


# --- вспомогательное ------------------------------------------------------------

@pytest.mark.parametrize("moment,expected", [
    (date(2026, 1, 1), "2026-Q1"), (date(2026, 4, 30), "2026-Q2"),
    (date(2026, 9, 30), "2026-Q3"), (date(2026, 12, 31), "2026-Q4"),
])
def test_the_quarter_is_calculated_right(moment, expected):
    assert core._quarter_of(moment) == expected


@pytest.mark.parametrize("quarter,steps,expected", [
    ("2026-Q1", 1, "2026-Q2"), ("2026-Q4", 1, "2027-Q1"),
    ("2027-Q1", -1, "2026-Q4"), ("2026-Q2", 4, "2027-Q2"),
])
def test_the_quarter_shift_crosses_the_year(quarter, steps, expected):
    assert core._quarter_shift(quarter, steps) == expected
