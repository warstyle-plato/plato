"""Рост цены квартир до РВЭ по умолчанию — 1% в месяц, а не 1,5%.

Решение владельца (29.09.2026): «по умолчанию в базовом сценарии делать рост
цены 1, а не 1,5 в месяц по квартирам». Умолчание живёт в `DEFAULT_INPUTS`;
запасное значение расчёта и текст скрининга КРТ читают его же, а не свой
литерал. Рост объектов ОСЗ — отдельные вводные, их правка не касается.

Запуск: python3 -m pytest tests/test_the_flat_price_grows_one_percent_by_default.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_default_is_one_percent_a_month() -> None:
    assert core.DEFAULT_INPUTS["monthly_growth_pre_pct"] == 1.0


def test_the_objects_keep_their_own_growth() -> None:
    for obj in core.STANDALONE_OBJECTS:
        assert core.DEFAULT_INPUTS.get(f"{obj.prefix}_growth_pre_pct",
                                       obj.growth_pre_default) == obj.growth_pre_default


def test_no_reader_keeps_the_old_literal() -> None:
    engine = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert '"monthly_growth_pre_pct", 1.5)' not in engine
    screening = (ROOT / "auction_search" / "krt_screening.py").read_text(encoding="utf-8")
    assert "1,5% в месяц до РВЭ" not in screening


def test_the_screening_names_the_rate_it_used() -> None:
    from auction_search import krt_screening

    assert krt_screening._pct_word({}, core, "monthly_growth_pre_pct") == "1"
    assert krt_screening._pct_word({"monthly_growth_post_pct": 0.25}, core,
                                   "monthly_growth_post_pct") == "0,25"
