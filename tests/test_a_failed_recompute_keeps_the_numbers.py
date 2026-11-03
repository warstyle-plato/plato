"""Неудавшийся пересчёт не затирает удавшийся.

Правило «посчитанное не выбрасывают» было записано в одну сторону: отчёт лёг
файлом рядом с баллом, чтобы карточка не считала второй раз. Обратную сторону
оно не закрывало — строка с числами молча заменялась строкой «модель не
считалась».

23.08.2026 это выстрелило целиком. Прогон по календарю (воскресенье, 3 часа по
Москве) впервые прошёл по всему каталогу, и посчитанное руками исчезло разом:
на экране остались одни баллы по ТЭП, будто модель не запускали никогда
(владелец: «слетели все расчёты»). Числа недельной давности — это «посчитано
тогда-то», и это несравнимо лучше пустоты.

Вторая половина того же случая: причина отказа была, но нигде не показывалась.
Двадцать строк «модель не считалась» и ни слова о том, почему, — отказ без
причины ничем не отличается от отсутствующей проверки.

Запуск: python3 -m pytest tests/test_a_failed_recompute_keeps_the_numbers.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import krt_ranking  # noqa: E402
from auction_search.krt_ranking import KrtRanking, keep_computed, score_row  # noqa: E402
from auction_search import ui as auction_ui  # noqa: E402


PROJECT = {"slug": "nagatino", "name": "КРТ Нагатино", "okrug": "ЮАО",
           "district": "Нагатино-Садовники", "status": "Планируемый",
           "area_ha": 12.0, "housing_gfa_sqm": 215720.6}

GOOD = {
    "available": True,
    "traffic_light": {"tone": "ok", "label": "Операционный сценарий проходит"},
    "metrics": {"project_llcr_x": 1.31, "weakest_phase_llcr_x": 1.19,
                "margin_pct": 14.8, "net_profit_mln": 17_084.9},
    "phasing": {"count": 3, "saleable_sqm": 140_218.4},
    "market": {"recommended_segment": "комфорт", "start_price_rub_sqm": 442_050},
    "entry_capacity": {"available": True, "amount_mln": 4_180.0},
}
FAILED = {"available": False, "reason": "Расчёт не выполнен: рынок не ответил"}


@pytest.fixture
def ranking(tmp_path) -> KrtRanking:
    return KrtRanking(tmp_path)


def test_a_failed_recompute_keeps_the_numbers() -> None:
    counted = score_row(PROJECT, GOOD)
    kept = keep_computed(counted, score_row(PROJECT, FAILED))
    assert kept["available"] is True
    assert kept["project_llcr_x"] == 1.31
    assert kept["entry_capacity_rub_per_sqm"] == counted["entry_capacity_rub_per_sqm"]


def test_the_failure_is_named_and_dated() -> None:
    kept = keep_computed(score_row(PROJECT, GOOD), score_row(PROJECT, FAILED))
    assert "рынок не ответил" in kept["recompute_reason"]
    assert kept["recompute_failed_at"] > 0


def test_the_date_of_the_numbers_does_not_move() -> None:
    """Иначе на экране «посчитано минуту назад» рядом с прошлыми числами."""
    counted = score_row(PROJECT, GOOD)
    kept = keep_computed(counted, score_row(PROJECT, FAILED))
    assert kept["computed_at"] == counted["computed_at"]


def test_the_catalogue_passport_still_updates() -> None:
    """Статус и ТЭП приходят от krt.mos.ru и к нашему счёту отношения не имеют."""
    counted = score_row(PROJECT, GOOD)
    moved = dict(PROJECT, status="В реализации", housing_gfa_sqm=230_000.0)
    kept = keep_computed(counted, score_row(moved, FAILED))
    assert kept["status"] == "В реализации"
    assert kept["housing_gfa_sqm"] == 230_000.0


def test_a_success_clears_the_failure() -> None:
    kept = keep_computed(score_row(PROJECT, GOOD), score_row(PROJECT, FAILED))
    fresh = keep_computed(kept, score_row(PROJECT, GOOD))
    assert "recompute_reason" not in fresh
    assert "recompute_failed_at" not in fresh


def test_a_first_failure_is_not_dressed_up_as_a_result() -> None:
    """Не считали ни разу — значит «не считали», а не выдуманная строка."""
    first = keep_computed(None, score_row(PROJECT, FAILED))
    assert first["available"] is False
    assert first["reason"]


def test_the_whole_run_does_not_wipe_the_catalogue(ranking) -> None:
    """Тот самый воскресный прогон: он падает на всех, а числа остаются."""
    ranking._run([PROJECT], lambda project: dict(GOOD))
    before = ranking.rows()[0]
    assert before["available"] is True

    def boom(project):
        raise RuntimeError("рынок не ответил")

    ranking._run([PROJECT], boom)
    after = ranking.rows()[0]
    assert after["available"] is True
    assert after["project_llcr_x"] == before["project_llcr_x"]
    assert "рынок не ответил" in after["recompute_reason"]


def test_one_site_recomputed_from_the_card_follows_the_same_rule(ranking) -> None:
    ranking.upsert_row(score_row(PROJECT, GOOD))
    ranking.upsert_row(score_row(PROJECT, FAILED))
    row = ranking.rows()[0]
    assert row["available"] is True
    assert row["recompute_reason"]


def test_the_report_of_a_counted_site_survives_a_failure(ranking) -> None:
    ranking.save_failure_or_report(
        "nagatino", GOOD, {"project": PROJECT, "screening": dict(GOOD)})
    ranking.save_failure_or_report(
        "nagatino", FAILED, {"project": PROJECT, "screening": dict(FAILED)})
    report = ranking.report("nagatino")
    assert report["screening"]["available"] is True
    assert "рынок не ответил" in report["recompute"]["reason"]


def test_a_failure_without_a_previous_report_is_still_written(ranking) -> None:
    """«Не посчитали и вот почему» — тоже ответ, и карточка обязана его показать."""
    ranking.save_failure_or_report(
        "nagatino", FAILED, {"project": PROJECT, "screening": dict(FAILED)})
    report = ranking.report("nagatino")
    assert report["screening"]["available"] is False
    assert report["screening"]["reason"]


def test_the_list_says_why_the_model_was_not_counted() -> None:
    """Причина приходила в строке рейтинга и просто не выводилась."""
    page = auction_ui.auctions_page()
    assert "rank.reason" in page
    assert "модель не считалась'+(sc.reason?': '+sc.reason:'')" in page


def test_the_list_says_the_numbers_are_from_the_previous_count() -> None:
    page = auction_ui.auctions_page()
    assert "rank.recompute_reason" in page
    assert "пересчёт не удался" in page
    assert "числа от " in page
