"""Единый контур текущего прогноза РНВ для Project Monitor.

Верхняя карточка состояния, «Платон · управленческий прогноз», сценарий
«Текущий темп» и база сравнения для задержки и ускорения обязаны показывать
одну дату: это один и тот же вопрос — «когда объект будет введён при нынешнем
темпе». Пока ответ считался в двух местах, они расходились, и на Гродненской
верхняя дата не совпадала с нижней.

Расхождение было не в подписи и не в округлении, а в двух независимых
реализациях одной формулы:

* `developaid_monitor_pace._pace_finish` при принятом объёме 100% возвращала
  «готово на дату среза», а копия в `developaid_monitor_scenarios` — «прогноза
  нет»; одна и та же завершённая задача двигала сеть по-разному;
* pace сеял только опоздания против `plan_finish` и отдельно добавлял
  утверждённый rebaseline, а сценарии подмешивали `forecast_finish` строки и
  сравнивали с финишем PM-задачи;
* поэтому наборы seeds были разными, а `_propagate` — одинаковым: два честных
  расчёта по разным входам.

Здесь формула объявлена один раз. Оба контура берут её отсюда, вместе с
правилом отбора seeds и одним и тем же снимком: дата среза, строки WBS, факт
РСС, утверждённые rebaseline и исключение РСС 2.1.
"""
from __future__ import annotations

import datetime
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_schedule_graph as schedule_graph

# РСС 2.1 — смешанная статья жизненного цикла: подготовка площадки, содержание
# и демобилизация идут до конца стройки. Её темп по принятому объёму — годная
# стоимостная улика, но календарным прогнозом WBS она быть не может: именно так
# на Гродненской появлялся многолетний «Подготовительный период». Исключение
# обязано действовать одинаково в обоих контурах, поэтому живёт здесь.
MIXED_LIFECYCLE_PREFIX = "2.1"
_MONTH_DAYS = 30.4375


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, number))


def is_mixed_lifecycle(row: dict[str, Any]) -> bool:
    """Строка целиком относится к смешанной статье РСС 2.1."""
    codes = monitor._codes(row.get("code"))
    return bool(codes) and all(
        str(code).startswith(MIXED_LIFECYCLE_PREFIX) for code in codes)


def pace_finish(row: dict[str, Any], cut: datetime.date) -> tuple[datetime.date | None, str]:
    """Прогноз финиша одной задачи по принятому объёму и наблюдаемому темпу.

    Единственная реализация: копия в сценарном движке отвечала иначе на
    завершённых задачах и на строках без планового финиша, и из-за этого
    сценарий «Текущий темп» получал другую сеть, чем верхняя карточка.
    """
    start = monitor._day(row.get("plan_start"))
    progress = _clamp(row.get("rss_accepted_ratio"))
    if progress is None:
        progress = _clamp(row.get("actual_progress"))
    if progress is None:
        return None, ""
    if row.get("baseline_closed"):
        return None, "baseline_closed"
    # Плановый финиш формуле не нужен: опоздание судит тот, кто сеет seeds.
    # Пока он был обязателен, строка без него не давала прогноза вовсе — а
    # копия в сценарном движке давала, и сети расходились.
    if start is not None and cut < start:
        return None, "future"
    if is_mixed_lifecycle(row):
        return None, "mixed_lifecycle_rss"
    if progress >= 0.999999:
        return cut, "accepted_complete"

    try:
        monthly_rate = float(row.get("rss_act_cost_rate_3m") or row.get("rate_3m") or 0.0)
    except (TypeError, ValueError):
        monthly_rate = 0.0
    method = "rolling_3m_acts"

    if monthly_rate <= 1e-9:
        # Запасной темп — средний с начала работ: без даты начала его не из
        # чего считать, и это честное «нет прогноза», а не ноль.
        if start is None:
            return None, "no_pace"
        elapsed_days = max(0, (cut - start).days)
        if progress <= 1e-9 or elapsed_days <= 0:
            return None, "no_pace"
        monthly_rate = progress / max(elapsed_days / _MONTH_DAYS, 1 / _MONTH_DAYS)
        method = "average_acts_since_start"

    if monthly_rate <= 1e-9:
        return None, "no_pace"
    remaining_months = max(0.0, (1.0 - progress) / monthly_rate)
    return cut + datetime.timedelta(days=round(remaining_months * _MONTH_DAYS)), method


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("wbs") or "").strip()


def current_seeds(rows: list[dict[str, Any]], cut: datetime.date) -> dict[str, Any]:
    """Seeds текущего темпа: опоздания против плана плюс утверждённый rebaseline.

    Возвращает и сами прогнозы, и способ их получения — верхняя карточка
    подписывает ими строки, а сценарный движок ранжирует по ним драйверы.
    Считать это дважды нельзя: подписи и сеть разъедутся.
    """
    seeds: dict[str, datetime.date] = {}
    forecasts: dict[str, datetime.date] = {}
    methods: dict[str, str] = {}
    excluded: list[str] = []

    for row in rows:
        tid = _row_id(row)
        if not tid:
            continue
        if is_mixed_lifecycle(row):
            excluded.append(tid)
        predicted, method = pace_finish(row, cut)
        if predicted is not None:
            forecasts[tid] = predicted
            methods[tid] = method
            plan = monitor._day(row.get("plan_finish"))
            if plan and predicted > plan:
                seeds[tid] = predicted

    # Утверждённый rebaseline — это решение, а не темп: он двигает сеть вместе
    # с опозданиями, но не выдаёт себя за прогноз по факту.
    for row in rows:
        if not (row.get("rebaseline_seed")
                or str(row.get("forecast_source") or "") == "approved_rebaseline"):
            continue
        tid = _row_id(row)
        approved = monitor._day(row.get("forecast_finish"))
        if tid and approved:
            seeds[tid] = max(approved, seeds.get(tid, approved))

    return {"seeds": seeds, "forecasts": forecasts, "methods": methods,
            "excluded_rss_codes": sorted(set(excluded))}


def network_rnv(pm: dict[str, Any], tasks: dict[str, dict[str, Any]],
                field: str = "forecast_finish") -> datetime.date | None:
    """РНВ сети: веха РНВ, если она объявлена, иначе самый поздний финиш."""
    if pm.get("rnv_id") and pm["rnv_id"] in tasks:
        return tasks[pm["rnv_id"]].get(field)
    values = [task.get(field) for task in tasks.values() if task.get(field)]
    return max(values, default=None)


def current_forecast(view: dict[str, Any], pm: dict[str, Any],
                     cut: datetime.date, *, rss_snapshot: str = "") -> dict[str, Any]:
    """Текущий прогноз: сеть по нынешнему темпу и её РНВ.

    Один вход для верхней карточки и для сценарного движка. Возвращает и
    контекст расчёта — по нему сразу видно, если два экрана считают по разным
    срезам или снимкам РСС, а не гадать по совпадению дат.
    """
    rows = (view.get("schedule") or {}).get("rows") or []
    built = current_seeds(rows, cut)
    approved_tasks = schedule_graph._propagate(pm, {}) if pm.get("known") else {}
    current_tasks = (schedule_graph._propagate(pm, built["seeds"])
                     if pm.get("known") else {})
    approved_rnv = network_rnv(pm, approved_tasks, "finish") if approved_tasks else None
    forecast_rnv = network_rnv(pm, current_tasks) if current_tasks else None
    return {
        "seeds": built["seeds"],
        "forecasts": built["forecasts"],
        "methods": built["methods"],
        "approved_tasks": approved_tasks,
        "current_tasks": current_tasks,
        "approved_rnv": approved_rnv,
        "current_forecast_rnv": forecast_rnv,
        "context": {
            "cut": monitor._iso(cut),
            "rss_snapshot": rss_snapshot,
            "pm_source": str(pm.get("source") or ("known" if pm.get("known") else "unknown")),
            "forecast_method": "current_pace_network",
            "pace_seed_count": len(built["seeds"]),
            "excluded_rss_codes": built["excluded_rss_codes"] or [MIXED_LIFECYCLE_PREFIX],
        },
    }
