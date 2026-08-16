"""Кзатр льготы МПТ: база приказа × утверждённый квартальный индекс ДЭПР.

Приказ ДИиПП от 10.03.2026: Кзатр = 166,23078 с 01.01.2026, со второго
квартала 2026 года — ежеквартальная корректировка на обобщённый индекс
изменения стоимости строительства за последний месяц предыдущего квартала
к декабрю 2025 года. Индексы утверждает распоряжение ДЭПР № ДПРР-18-26 от
29.07.2026 (строка «Строительство»): март 1,0072 → Q2, июнь 1,0229 → Q3.

Здесь закреплено:

- значение квартала считается, а не зашивается: Q1 — база, Q2/Q3 — база ×
  индекс, квартал без утверждённого индекса — None, потому что старое число
  выглядело бы как посчитанное;
- дефолт в интерфейсе МПТ — значение текущего квартала вместе с самим
  кварталом, чтобы расчёт не ругался «не сверено» на собственный дефолт;
- напоминание /status молчит, пока индекс квартала принесён, и загорается
  при смене квартала без нового распоряжения.

Запуск: python3 -m pytest tests/test_kzatr_quarterly_index.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
import mpt_calculator  # noqa: E402

core = wrapper.core


def test_the_quarter_value_is_computed_not_hardcoded():
    assert mpt_calculator.kzatr_for_quarter("2026-Q1") == pytest.approx(166.23078)
    assert mpt_calculator.kzatr_for_quarter("2026-Q2") == pytest.approx(167.42764)
    assert mpt_calculator.kzatr_for_quarter("2026-Q3") == pytest.approx(170.03746)
    assert mpt_calculator.kzatr_for_quarter("2026-Q4") is None, (
        "квартал без утверждённого индекса не имеет права на число"
    )
    assert mpt_calculator.kzatr_for_quarter("") is None


def test_the_metadata_defaults_to_the_current_quarter(monkeypatch):
    monkeypatch.setattr(mpt_calculator, "quarter_of", lambda day: "2026-Q3")
    meta = mpt_calculator.metadata()
    assert meta["kzatr_default"] == pytest.approx(170.03746)
    assert meta["kzatr_default_quarter"] == "2026-Q3"
    assert "ДПРР-18-26" in meta["kzatr_source"]
    assert meta["kzatr_indices_to_dec2025"]["2026-Q3"] == pytest.approx(1.0229)


def test_an_unknown_quarter_falls_back_loudly(monkeypatch):
    monkeypatch.setattr(mpt_calculator, "quarter_of", lambda day: "2026-Q4")
    meta = mpt_calculator.metadata()
    assert meta["kzatr_default"] == pytest.approx(166.23078), "дефолт — база, не чужой квартал"
    assert meta["kzatr_default_quarter"] == "", "квартал не подставляется — значение не сверено"
    assert "не принесён" in meta["kzatr_source"]


def test_the_status_reminder_follows_the_known_quarters():
    rows = {item["key"]: item for item in core.reference_freshness(date(2026, 8, 16))}
    kzatr = rows["mpt_kzatr"]
    assert kzatr["stale"] is False, "индекс Q3 принесён — напоминание должно молчать"
    assert "170.03746" in kzatr["current"]
    assert "2026-Q4" in kzatr["valid_until"]
    stale_rows = {item["key"]: item for item in core.reference_freshness(date(2026, 10, 5))}
    assert stale_rows["mpt_kzatr"]["stale"] is True, (
        "квартал сменился без нового распоряжения — напоминание обязано загореться"
    )
