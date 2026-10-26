"""Эскроу против кредита на дату ввода — по нынешнему темпу и по плану финмодели.

Владелец, 26.10.2026: «В блоке финансирование не хватает прогноза
достаточности эскроу на момент ввода». Сводка отвечала только «к раскрытию»
(месяц перед погашением). Ответ к вводу берёт тот же темп поступлений и тот же
план финмодели, на месяц ввода: прогноз Монитора, без него — утверждённый срок.

Данные: накоплено 60 млн ₽ на сентябрь 2026, темп 20 млн ₽ в месяц; план
эскроу на декабрь — 90 млн ₽, кредит по плану — 100 млн ₽; ввод по прогнозу
Монитора — 31.12.2026. К вводу: 60 + 3 × 20 = 120 млн ₽ — 1,20×; по плану 0,90×.

Запуск: python3 -m pytest tests/test_the_escrow_is_told_at_commissioning.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from market_search import contracting  # noqa: E402
from test_management_report_funding import _isolated, _project, _sales  # noqa: E402,F401
from test_management_report_model import M, PROJECT  # noqa: E402


def _view(schedule):
    return lambda project, end: {"dashboard": {"funding": {"known": False, "reason": "нет"},
                                               "schedule": schedule}}


def _built(monkeypatch, schedule):
    _project()
    _sales()
    monkeypatch.setattr(report, "_monitor_view", _view(schedule))
    return report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")


def test_the_escrow_at_the_forecast_commissioning(monkeypatch):
    built = _built(monkeypatch, {"approved_finish": "2026-11-30",
                                 "forecast_finish": "2026-12-31"})
    at = built["funding"]["escrow"]["queues"][0]["at_commissioning"]
    assert (at["date"], at["source"]) == ("2026-12-31", "прогноз Монитора")
    assert at["keeping_escrow"] == pytest.approx(120 * M)
    assert at["plan_pf"] == pytest.approx(100 * M)
    assert at["keeping_coverage"] == pytest.approx(1.2)
    assert at["plan_coverage"] == pytest.approx(0.9)

    text = report.render_text(built)
    assert ("К вводу 31.12.2026 (прогноз Монитора) при нынешнем темпе на эскроу будет "
            "120,0 млн ₽ — покрывает кредит 100,0 млн ₽ (1,20×); по плану финмодели — "
            "90,0 млн ₽, 0,90×.") in text, text
    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert ("к вводу 31.12.2026 при нынешнем темпе эскроу покроет кредит (1,20×), "
            "по плану финмодели — 0,90×") in found["Финансирование"], found["Финансирование"]

    page = report.render_html(built)
    assert "Эскроу к вводу 31.12.2026 (прогноз Монитора)" in page
    assert "1,20×" in page and "0,90×" in page


def test_without_a_forecast_the_approved_date_is_used_and_named(monkeypatch):
    built = _built(monkeypatch, {"approved_finish": "2026-11-30", "forecast_finish": None})
    at = built["funding"]["escrow"]["queues"][0]["at_commissioning"]
    assert (at["date"], at["source"]) == ("2026-11-30", "утверждённый срок")
    assert at["keeping_escrow"] == pytest.approx(100 * M)
    assert "К вводу 30.11.2026 (утверждённый срок)" in report.render_text(built)


def test_a_short_pace_is_told_as_not_covering():
    block = {"measured_at": "2026-09", "actual": 60 * M, "pace": 5 * M}
    queue = {"escrow": {"2026-12": 90 * M}, "pf": {"2026-12": 100 * M}}
    at = contracting.escrow_at(block, queue, "2026-12")
    assert at["keeping_coverage"] == pytest.approx(0.75)
    words = report._commissioning_words({"at_commissioning": dict(
        at, date="2026-12-31", source="прогноз Монитора")})
    assert "НЕ покрывает кредит 100,0 млн ₽ (0,75×)" in words
    # Ввод не впереди замера — прогноза нет, а не «покрывает».
    assert contracting.escrow_at(block, queue, "2026-09") is None
