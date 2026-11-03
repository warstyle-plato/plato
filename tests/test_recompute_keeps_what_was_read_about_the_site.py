"""Пересчёт площадки не стирает прочитанное о ней.

«Так и не хранятся данные о уже просчитанных проектах — заново надо считать
всё, что реновация, что занято» (владелец, 03.09.2026). Застройщик и
реновация с карточки города и занятость из публикаций живут в строке
рейтинга. Строка при пересчёте собирается заново (`score_row`), а скрининг
из карточки этих фактов не несёт — пустое поле вставало на место
прочитанного при каждом «Пересчитать сейчас». Пустота прочитанное не
затирает; новые непустые факты — да.

Запуск: python3 -m pytest tests/test_recompute_keeps_what_was_read_about_the_site.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_ranking as kr  # noqa: E402

PROJECT = {"slug": "s", "name": "Площадка", "status": "Планируемый", "area_ha": 15.0}
FACTS = {
    "card_facts": {"developer": "АО «Главстрой»", "renovation": True},
    "press_facts": {"available": True, "taken": True, "operator": "Оператор",
                    "rules_version": 5},
}


def _screening(available: bool = True) -> dict:
    if not available:
        return {"available": False, "reason": "рынок не ответил"}
    return {"available": True, "traffic_light": {"label": "Проходит"},
            "phasing": {"saleable_sqm": 100_000, "count": 2},
            "metrics": {"project_llcr_x": 1.3},
            "entry_capacity": {"available": True, "amount_mln": 500}}


def test_a_successful_recompute_from_the_card_keeps_the_facts() -> None:
    previous = {**kr.score_row(PROJECT, _screening()), **FACTS}
    fresh = kr.score_row(PROJECT, _screening())  # скрининг из карточки — без фактов
    assert fresh["card_facts"] == {} and fresh["press_facts"] == {}
    merged = kr.keep_computed(previous, fresh)
    assert merged["card_facts"] == FACTS["card_facts"]
    assert merged["press_facts"] == FACTS["press_facts"]
    assert merged["available"] is True and merged["entry_capacity_mln"] == 500.0


def test_a_failed_recompute_keeps_the_facts_too() -> None:
    previous = {**kr.score_row(PROJECT, _screening()), **FACTS}
    merged = kr.keep_computed(previous, kr.score_row(PROJECT, _screening(False)))
    assert merged["card_facts"] == FACTS["card_facts"]
    assert merged["press_facts"] == FACTS["press_facts"]
    assert merged["recompute_reason"] == "рынок не ответил"


def test_fresh_facts_replace_the_old_ones() -> None:
    previous = {**kr.score_row(PROJECT, _screening()), **FACTS}
    newer = dict(_screening())
    newer["card_facts"] = {"developer": "КП «КРТ»", "renovation": False}
    merged = kr.keep_computed(previous, kr.score_row(PROJECT, newer))
    assert merged["card_facts"] == {"developer": "КП «КРТ»", "renovation": False}
    # Публикации новый скрининг не читал — прежние остаются.
    assert merged["press_facts"] == FACTS["press_facts"]


def test_the_merge_between_workers_keeps_the_facts_in_both_orders() -> None:
    stored = {**kr.score_row(PROJECT, _screening()), **FACTS, "computed_at": 100}
    ours = {**kr.score_row(PROJECT, _screening()), "computed_at": 200}
    assert kr.merge_row(stored, ours)["press_facts"] == FACTS["press_facts"]
    assert kr.merge_row(ours, stored)["press_facts"] == FACTS["press_facts"]


def test_a_recompute_through_the_store_keeps_the_facts(tmp_path) -> None:
    ranking = kr.KrtRanking(tmp_path)
    ranking.upsert_row(kr.score_row(PROJECT, _screening()))
    ranking.remember("s", FACTS)
    ranking.upsert_row(kr.score_row(PROJECT, _screening()))
    row = ranking.stored_row("s")
    assert row["press_facts"]["taken"] is True and row["card_facts"]["renovation"] is True
