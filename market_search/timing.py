"""Сроки конкурентов против наших: ввод, окно продаж, цены той же стадии.

Числа здесь не добываются заново. Ввод, старт продаж и стадия каждого соседа
приходят готовыми полями `MarketDiscoveryService.analog_timing` — теми же, что
показывает «Как посчитана цена». Модуль только сопоставляет их с нашим
проектом, и каждое правило сопоставления объявлено здесь одним местом:

* «одновременно» по вводу — разница не больше квартала (`SAME_TIME_MONTHS`);
* окно продаж проекта — от старта продаж до планового ввода последнего
  корпуса. Сосед без даты старта, но с действующей ценой, продаёт сейчас:
  его окно начинается сегодня. Остаток ноль — распродан, окна нет;
* «той же стадии» — тот же код стадии строительства, что у нашего проекта.
  Своей стадии у площадки нет, и тогда она берётся подсказкой
  `stage.suggest_project_stage` — по нашим срокам или «котлован» для старта.

Чего не хватает — называется причиной, а не прочерком.
"""

from __future__ import annotations

import statistics
from typing import Any

from . import stage

SAME_TIME_MONTHS = 3
SALES_WINDOW_RULE = (
    "окно продаж — от старта продаж до планового ввода последнего корпуса; "
    "у соседа без даты старта, но с действующей ценой — с сегодняшнего дня"
)


def _from_months(value: int) -> str:
    year, month = divmod(value - 1, 12)
    return f"{year:04d}-{month + 1:02d}"


def _window(row: dict[str, Any], today_m: int, *, peer: bool) -> tuple[int | None, int | None, str | None]:
    """Окно продаж в месяцах и причина, если его нет."""
    if peer and row.get("remaining_units") == 0:
        return None, None, "остаток ноль — проект распродан"
    end = stage._months(row.get("commissioning"))
    if end is None:
        return None, None, row.get("commissioning_reason") or "нет планового ввода"
    start = stage._months(row.get("sales_start"))
    if start is None:
        if peer and row.get("price_per_sqm"):
            start = today_m
        else:
            return None, None, "нет даты старта продаж"
    if end < start:
        return None, None, "плановый ввод раньше старта продаж — окна нет"
    return start, end, None


def compare(subject: dict[str, Any], peers: list[dict[str, Any]], today: str) -> dict[str, Any]:
    """Сопоставление сроков; пишет `vs_ours` в строки соседей и отдаёт свод."""
    today_m = stage._months(today) or 0
    ours_end = stage._months(subject.get("commissioning"))
    ours_start, ours_stop, ours_window_reason = _window(subject, today_m, peer=False)

    # Наша стадия: своя у проекта из Пульса, иначе — объявленная подсказка.
    if subject.get("construction_stage"):
        our_stage = {
            "code": subject["construction_stage"],
            "label": subject.get("construction_stage_label"),
            "reason": "стадия проекта у Пульса"
            + (f" ({subject['construction_stage_origin_title']})"
               if subject.get("construction_stage_origin_title") else ""),
        }
    else:
        our_stage = stage.suggest_project_stage(
            subject.get("sales_start"), subject.get("commissioning"), today
        )

    earlier = same = later = unknown = 0
    gaps: list[int] = []
    overlapping: list[dict[str, Any]] = []
    overlap_unknown = 0
    same_stage: list[dict[str, Any]] = []
    stage_unknown = 0
    for row in peers:
        vs: dict[str, Any] = {}
        peer_end = stage._months(row.get("commissioning"))
        if ours_end is None:
            vs["commissioning_reason"] = "нашего ввода нет"
        elif peer_end is None:
            vs["commissioning_reason"] = row.get("commissioning_reason") or "нет планового ввода"
            unknown += 1
        else:
            gap = peer_end - ours_end
            gaps.append(gap)
            vs["gap_months"] = gap
            if abs(gap) <= SAME_TIME_MONTHS:
                vs["relation"] = "одновременно с нами"
                same += 1
            elif gap < 0:
                vs["relation"] = "раньше нас"
                earlier += 1
            else:
                vs["relation"] = "позже нас"
                later += 1

        p_start, p_stop, p_reason = _window(row, today_m, peer=True)
        if ours_start is None:
            vs["overlap"] = None
            vs["overlap_reason"] = f"нашего окна продаж нет: {ours_window_reason}"
        elif p_start is None:
            vs["overlap"] = None
            vs["overlap_reason"] = p_reason
            if p_reason and "распродан" in p_reason:
                vs["overlap"] = False
            else:
                overlap_unknown += 1
        else:
            months = min(ours_stop, p_stop) - max(ours_start, p_start) + 1
            vs["overlap"] = months > 0
            vs["overlap_months"] = max(months, 0)
            vs["window"] = {"from": _from_months(p_start), "to": _from_months(p_stop)}
            if months > 0:
                overlapping.append({
                    "complex_id": row.get("complex_id"),
                    "name": row.get("name"),
                    "months": months,
                    "price_per_sqm": row.get("price_per_sqm"),
                })

        code = row.get("construction_stage")
        if not code:
            vs["same_stage"] = None
            stage_unknown += 1
        else:
            vs["same_stage"] = code == our_stage["code"]
            if vs["same_stage"] and row.get("price_per_sqm"):
                same_stage.append({
                    "complex_id": row.get("complex_id"),
                    "name": row.get("name"),
                    "price_per_sqm": row.get("price_per_sqm"),
                    "origin_title": row.get("construction_stage_origin_title"),
                })
        row["vs_ours"] = vs

    commissioning: dict[str, Any]
    if ours_end is None:
        commissioning = {
            "available": False,
            "reason": subject.get("commissioning_reason") or "нашего планового ввода нет",
        }
    else:
        known = earlier + same + later
        commissioning = {
            "available": bool(known),
            "ours": subject.get("commissioning"),
            "earlier": earlier, "same": same, "later": later, "unknown": unknown,
            # Медиана разницы — своя: `stage.median` выбрасывает нули, а ноль
            # здесь — «вводимся в один месяц», самый важный ответ.
            "median_gap_months": int(round(statistics.median(gaps))) if gaps else None,
            "rule": f"«одновременно» — разница вводов не больше {SAME_TIME_MONTHS} мес.",
        }
        if not known:
            commissioning["reason"] = "ни у одного соседа нет планового ввода"

    if ours_start is None:
        overlap = {"available": False, "reason": f"нашего окна продаж нет: {ours_window_reason}",
                   "rule": SALES_WINDOW_RULE}
    else:
        overlap = {
            "available": True,
            "window": {"from": _from_months(ours_start), "to": _from_months(ours_stop)},
            "count": len(overlapping),
            "unknown": overlap_unknown,
            "peers": sorted(overlapping, key=lambda r: -r["months"]),
            "rule": SALES_WINDOW_RULE,
        }

    prices = [float(r["price_per_sqm"]) for r in same_stage]
    median = stage.median(prices)
    same_block: dict[str, Any] = {
        "stage": our_stage,
        "count": len(same_stage),
        "without_stage": stage_unknown,
        "peers": same_stage,
        "median_price_per_sqm": int(round(median)) if median else None,
    }
    if not same_stage:
        same_block["reason"] = (
            f"среди соседей с ценой нет стадии «{our_stage['label']}»"
            + (f"; у {stage_unknown} стадия не указана" if stage_unknown else "")
        )
    return {
        "subject": {
            "sales_start": subject.get("sales_start"),
            "commissioning": subject.get("commissioning"),
            "commissioning_first": subject.get("commissioning_first"),
            "origin": subject.get("origin"),
            "origin_title": subject.get("origin_title"),
            "reason": subject.get("commissioning_reason"),
        },
        "commissioning": commissioning,
        "overlap": overlap,
        "same_stage": same_block,
    }
