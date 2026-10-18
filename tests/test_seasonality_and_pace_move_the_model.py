"""Сезонность и корректировка темпа меняют расчёт, а не только подпись поля.

Проверка жила рядом со сверкой шаблона ПЛАТО (`test_template_agreement`); шаблон
удалён, а вопрос о движке остался.

Запуск: python3 -m pytest tests/test_seasonality_and_pace_move_the_model.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core


def test_seasonality_and_pace_actually_move_the_model():
    """Поля есть в интерфейсе — значит должны менять расчёт, а не только выгрузку."""
    base = main._run_authoritative_model(main.DEFAULT_INPUTS, main.TEP_DEFAULT, [], {})
    flat = main._run_authoritative_model(
        {**main.DEFAULT_INPUTS, "seasonal_reduction_pct": 0, "pace_adjustment_pct": 0},
        main.TEP_DEFAULT, [], {},
    )
    assert base["consolidated"]["summary"]["revenue"] != flat["consolidated"]["summary"]["revenue"]
