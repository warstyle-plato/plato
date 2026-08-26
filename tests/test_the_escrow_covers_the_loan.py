"""Хватит ли эскроу к погашению ПФ — по плану и по нынешнему темпу.

«Прогноза по динамике продаж и достаточности эскроу для погашения ПФ нет»
(владелец, 26.08.2026). План лежит на листе «КРЕДИТЫ» книги финмодели:
помесячно накопленное эскроу, остаток ПФ, их отношение и дата погашения — по
каждой очереди. Факт берётся из графика поступлений по договорам, который уже
читается для свода: второго счёта той же величины здесь нет.

Два ответа, и они разные. План отвечает за себя. Второй — что будет, если темп
останется нынешним; это ПРОДОЛЖЕНИЕ ТЕМПА, а не прогноз, и названо так же.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from market_search import contracting

SOURCE = Path(__file__).resolve().parent.parent / "market_search" / "contracting.py"


def _queue(escrow: dict, pf: dict, repay: str = "2027-09") -> dict:
    return {"sheet": "КРЕДИТЫ", "empty_queues": [],
            "queues": [{"queue": "1 очередь", "escrow": escrow, "pf": pf,
                        "coverage": {}, "rate": {},
                        "drawn_from": "2025-05", "repay_from": repay}]}


def _rows(schedule: dict) -> list[dict]:
    return [{"escrow_schedule": [{"month": m, "amount": a} for m, a in schedule.items()]}]


def test_a_queue_of_ninety_seven_zeroes_is_not_financed() -> None:
    """Словарь нулей истинен: проверка «есть ли ключи» пропустила бы его."""
    source = SOURCE.read_text()
    body = source[source.index("def read_credit_plan("):source.index("def escrow_actual(")]
    assert "def has_money(" in body, "живость очереди решается числами, а не ключами"
    assert "any(value for value in" in body


def test_the_partial_month_is_left_out_of_the_pace() -> None:
    """Выгрузка снята серединой месяца: он занижает темп молча."""
    got = contracting.escrow_sufficiency(
        {}, _rows({"2026-05": 100e6, "2026-06": 100e6, "2026-07": 100e6, "2026-08": 5e6}),
        _queue({"2026-07": 500e6, "2027-08": 2000e6}, {"2026-07": 1000e6, "2027-08": 3000e6}))
    queue = got["queues"][0]
    assert got["partial_month"] == "2026-08"
    assert queue["measured_at"] == "2026-07"
    assert queue["pace"] == pytest.approx(100e6), "неполный месяц попал в темп"


def test_the_plan_pace_stands_next_to_the_actual_one() -> None:
    """Без темпа плана «0,36×» читается как приговор продажам.

    А это в первую очередь утверждение о плане: он требует ускорения в
    несколько раз.
    """
    got = contracting.escrow_sufficiency(
        {}, _rows({"2026-05": 100e6, "2026-06": 100e6, "2026-07": 100e6, "2026-08": 1e6}),
        _queue({"2026-07": 300e6, "2027-07": 1500e6}, {"2026-07": 900e6, "2027-07": 2000e6}))
    queue = got["queues"][0]
    assert queue["plan_pace"] == pytest.approx(100e6), "план: 1200 млн за 12 месяцев"
    assert queue["pace_ratio"] == pytest.approx(1.0)
    assert queue["keeping_pace_coverage"] is not None


def test_the_forecast_is_named_a_continuation_not_a_prediction() -> None:
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    start = page.index("function salesEscrowBlock(")
    block = page[start:page.index("\n// Спрос против витрины", start)]
    assert "при нынешнем темпе" in block
    assert "не прогноз" in block, "продолжение темпа выдано за прогноз"
    # Экран не считает: ряд, покрытие и темп приходят посчитанными.
    for forbidden in ("/q.plan_pf_at", "q.actual/", "*q.pace"):
        assert forbidden not in block, f"экран считает сам: {forbidden}"


def test_the_continuation_is_drawn_only_forward() -> None:
    """Назад продолжение темпа спорило бы с фактом, который уже случился."""
    got = contracting.escrow_sufficiency(
        {}, _rows({"2026-06": 50e6, "2026-07": 50e6, "2026-08": 1e6}),
        _queue({"2026-06": 100e6, "2026-07": 200e6, "2027-01": 900e6},
               {"2026-07": 500e6, "2027-01": 900e6}))
    line = got["queues"][0]["line"]
    before = [r for r in line if r["month"] <= "2026-07"]
    assert all(r["keeping"] is None for r in before)
    assert any(r["keeping"] for r in line if r["month"] > "2026-07")


def test_the_series_starts_where_the_money_starts() -> None:
    """Полтора года нулей до первой выборки занимают половину картинки."""
    got = contracting.escrow_sufficiency(
        {}, _rows({"2026-06": 50e6, "2026-07": 50e6, "2026-08": 1e6}),
        _queue({"2024-01": 0.0, "2025-01": 0.0, "2026-06": 100e6, "2026-07": 200e6},
               {"2026-07": 500e6}))
    line = got["queues"][0]["line"]
    assert line[0]["month"] == "2026-06", "ряд начинается с нулей"


def test_without_the_book_it_says_what_is_missing() -> None:
    """Отсутствие плана — «не загружено», а не «покрытия нет»."""
    got = contracting.escrow_sufficiency({}, [], None)
    assert got["missing"] and "КРЕДИТЫ" in got["missing"][0]
    got = contracting.escrow_sufficiency({}, [], {"queues": [{"queue": "1", "escrow": {}, "pf": {}}]})
    assert got["missing"], "без графика поступлений тоже сказано вслух"
