"""Законченная работа ГПР и дата «100% на дату» — одно правило для всех.

Слой темпа Монитора (`developaid_monitor_pace._apply_gpr`) решает по прогнозу
работы, закончена ли она (`work_done`) и является ли её дата лишь первым
показанием 100% в ГПР (`observed_complete_by`), и пишет эти поля в строку и в
дерево `schedule.management`. Срок раздела, корпуса и РНВ, сводка руководству
и страница Монитора читают только эти поля, а не выводят их заново.
"""

from __future__ import annotations

from typing import Any

DONE_METHODS = frozenset({"done", "confirmed_completion"})


def work_done(item: dict[str, Any]) -> bool:
    """Прогноз ГПР говорит, что работа закончена (по ГПР или подтверждённо)."""
    return (item.get("method") in DONE_METHODS
            or item.get("progress_origin") == "confirmed_completion")


def reading_only(item: dict[str, Any], actual_finish: Any = None) -> bool:
    """Дата прогноза — первое показание 100% в ГПР, а не окончание работы."""
    return item.get("method") == "done" and not actual_finish


def observed_only(node: dict[str, Any]) -> bool:
    """Дата строки или узла помечена как показание 100% (`observed_complete_by`)."""
    return bool(node.get("observed_complete_by"))
