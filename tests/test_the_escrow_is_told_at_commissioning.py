"""Эскроу против кредита на дату ввода — по нынешнему темпу и по плану финмодели.

Владелец, 26.10.2026: «В блоке финансирование не хватает прогноза
достаточности эскроу на момент ввода». Сводка отвечала только «к раскрытию»
(месяц перед погашением). Ответ к вводу берёт тот же темп поступлений и тот же
план финмодели, на месяц ввода — утверждённого (владелец, 27.10.2026: «Ввод —
утверждённый, прогноз отдельно»); прогноз Монитора — отдельной строкой,
`test_the_commissioning_is_approved_and_the_forecast_apart.py`.

Данные: накоплено 65 млн ₽ на октябрь 2026, остаток к оплате по договорам
(рассрочка) 5 млн ₽, новые продажи — 16,7 млн ₽ в месяц (50 млн за июль —
сентябрь); план эскроу на декабрь — 90 млн ₽, кредит по плану — 100 млн ₽;
утверждённый ввод — 31.12.2026. К вводу: 65 + 5 + 2 × 16,7 = 103,3 млн ₽ —
1,03×; по плану 0,90×. К вводу: 60 + 3 × 20 = 120 млн ₽ — 1,20×; по плану 0,90×.

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


def test_the_escrow_at_the_approved_commissioning(monkeypatch):
    """Ввод к эскроу — утверждённый срок, даже когда прогноз Монитора позже
    (владелец, 27.10.2026: «Ввод — утверждённый, прогноз отдельно»)."""
    built = _built(monkeypatch, {"approved_finish": "2026-12-31",
                                 "forecast_finish": "2027-06-30"})
    at = built["funding"]["escrow"]["queues"][0]["at_commissioning"]
    assert (at["date"], at["source"]) == ("2026-12-31", "утверждённый срок")
    assert at["keeping_escrow"] == pytest.approx((65 + 5 + 2 * 50 / 3) * M)
    assert at["plan_pf"] == pytest.approx(100 * M)
    assert at["keeping_coverage"] == pytest.approx(1.0333, abs=1e-4)
    assert at["plan_coverage"] == pytest.approx(0.9)

    text = report.render_text(built)
    assert ("к вводу 31.12.2026 (утверждённый срок) по прогнозу на эскроу будет "
            "103,3 млн ₽ — покрывает кредит 100,0 млн ₽ (1,03×); по плану финмодели — "
            "90,0 млн ₽, 0,90×.") in text, text
    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert ("к вводу 31.12.2026 по прогнозу эскроу покроет кредит (1,03×), "
            "по плану финмодели — 0,90×") in found["Финансирование"], found["Финансирование"]

    page = report.render_html(built)
    assert "к вводу 31.12.2026 (утверждённый срок)" in page and "Покрытие кредита эскроу" in page
    assert "1,03×" in page and "0,90×" in page


def test_without_an_approved_date_there_is_no_answer_at_commissioning(monkeypatch):
    """Прогноз Монитора не подставляется вместо утверждённого срока."""
    built = _built(monkeypatch, {"forecast_finish": "2026-12-31"})
    assert built["funding"]["escrow"]["queues"][0]["at_commissioning"] is None
    text = report.render_text(built)
    assert "(утверждённый срок)" not in text
    assert ("Утверждённого срока ввода в данных Монитора нет; по темпу работ ввод — "
            "31.12.2026 (прогноз Монитора).") in text


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
