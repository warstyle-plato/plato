"""Deterministic what-if engine for Platon in Project Monitor.

The language layer only selects a scenario and presents this result. Dates and
money are calculated here from the immutable GPR/PM baseline, the selected RSS
snapshot and the approved financing programme.
"""
from __future__ import annotations

import datetime
import math
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
import developaid_monitor_schedule_graph as graph


KINDS = {"current_pace", "delay_wbs", "accelerate_wbs"}


def _shift_month(value: str, days: int) -> str:
    day = monitor._day(value)
    if day is None:
        return value
    shifted = day + datetime.timedelta(days=days)
    return shifted.replace(day=1).isoformat()


def _pace_finish(row: dict[str, Any], cut: datetime.date) -> datetime.date | None:
    progress = row.get("rss_accepted_ratio")
    rate = row.get("rss_act_cost_rate_3m")
    if progress is None:
        progress = row.get("actual_progress")
    if rate is None:
        rate = row.get("rate_3m")
    if progress is None or float(progress) >= 1:
        return None
    if rate is None or float(rate) <= 1e-9:
        return None
    months = max(0.0, (1.0 - max(0.0, float(progress))) / float(rate))
    return cut + datetime.timedelta(days=round(months * 30.4375))


def _target_ids(pm: dict[str, Any], wbs: str) -> list[str]:
    wanted = str(wbs or "").strip().lower()
    if not wanted:
        return []
    exact = [tid for tid in pm["tasks"] if tid.lower() == wanted]
    if exact:
        return exact
    return [
        tid for tid, task in pm["tasks"].items()
        if wanted in tid.lower() or wanted in str(task.get("name") or "").lower()
    ]


def _scenario_seeds(
    view: dict[str, Any], pm: dict[str, Any], cut: datetime.date, kind: str,
    target_ids: list[str], days: int, acceleration_pct: float,
) -> tuple[dict[str, datetime.date], dict[str, datetime.date]]:
    rows = {
        str(row.get("id") or row.get("wbs") or "").strip(): row
        for row in (view.get("schedule") or {}).get("rows") or []
    }
    current: dict[str, datetime.date] = {}
    for tid, task in pm["tasks"].items():
        pace = _pace_finish(rows.get(tid, {}), cut)
        existing = monitor._day(rows.get(tid, {}).get("forecast_finish"))
        candidate = max((d for d in (pace, existing) if d), default=task["finish"])
        if candidate > task["finish"]:
            current[tid] = candidate

    changed = dict(current)
    if kind == "delay_wbs":
        for tid in target_ids:
            base = current.get(tid, pm["tasks"][tid]["finish"])
            changed[tid] = base + datetime.timedelta(days=days)
    elif kind == "accelerate_wbs":
        factor = 1.0 + max(0.0, acceleration_pct) / 100.0
        for tid in target_ids:
            base = current.get(tid, pm["tasks"][tid]["finish"])
            remaining = max(0, (base - cut).days)
            recovered = cut + datetime.timedelta(days=math.ceil(remaining / factor))
            changed[tid] = max(pm["tasks"][tid]["finish"], recovered)
    return current, changed


def _network_rnv(pm: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> datetime.date:
    if pm.get("rnv_id") and pm["rnv_id"] in tasks:
        return tasks[pm["rnv_id"]]["forecast_finish"]
    return max(task["forecast_finish"] for task in tasks.values())


def _article_shifts(
    view: dict[str, Any], pm: dict[str, Any], base_tasks: dict[str, dict[str, Any]],
    scenario_tasks: dict[str, dict[str, Any]],
) -> dict[str, int]:
    rows = {
        str(row.get("id") or row.get("wbs") or "").strip(): row
        for row in (view.get("schedule") or {}).get("rows") or []
    }
    shifts: dict[str, int] = {}
    for tid in pm["tasks"]:
        delta = (scenario_tasks[tid]["forecast_finish"] - base_tasks[tid]["forecast_finish"]).days
        if not delta:
            continue
        for code in monitor._codes(rows.get(tid, {}).get("code")):
            shifts[code] = max(shifts.get(code, -10**9), delta)
    return shifts


def _shift_articles(
    articles: dict[str, Any], shifts: dict[str, int], cut: datetime.date | None = None
) -> dict[str, Any]:
    """Rephase only future need; past plan must never become future need again."""
    cut_month = cut.replace(day=1) if cut else None
    result: dict[str, Any] = {}
    for code, item in articles.items():
        relevant = [days for root, days in shifts.items() if code == root or code.startswith(root + ".") or root.startswith(code + ".")]
        days = max(relevant, default=0)
        monthly: dict[str, float] = {}
        for month, amount in (item.get("monthly_need") or {}).items():
            source_month = monitor._day(month)
            # The waterfall already ignores months before the cut. Keeping a
            # past month in place is essential: shifting it beyond the cut
            # would resurrect already executed plan and count it for a second
            # time on top of actual payments.
            key = (
                month
                if cut_month and source_month and source_month < cut_month
                else _shift_month(month, days)
            )
            monthly[key] = monthly.get(key, 0.0) + float(amount or 0.0)
        result[code] = {**item, "monthly_need": monthly}
    return result


def _answer(kind: str, target: str, delta: int, rnv: datetime.date,
            baseline_rnv: datetime.date, funding: dict[str, Any],
            current_funding: dict[str, Any]) -> str:
    label = {
        "current_pace": "При сохранении текущего темпа",
        "delay_wbs": f"При задержке WBS {target} на {delta} дн.",
        "accelerate_wbs": f"При ускорении WBS {target}",
    }[kind]
    slip = (rnv - baseline_rnv).days
    need = float(funding.get("additional_financing") or 0.0)
    reserve = funding.get("reserve_exhaustion")
    current_reserve = current_funding.get("reserve_exhaustion")
    timing = f"РНВ: {monitor._iso(rnv)} ({slip:+d} дн. к утверждённому сроку)."
    money = f"Непокрытая потребность: {need / 1e6:,.1f} млн ₽.".replace(",", " ")
    reserve_text = ""
    if reserve and current_reserve:
        reserve_text = (
            f" По утверждённому ДДС резерв исчерпывается "
            f"{monitor._iso(current_reserve)}, в сценарии — {monitor._iso(reserve)}."
        )
    elif reserve:
        reserve_text = f" В сценарии резерв исчерпывается {monitor._iso(reserve)}."
    return f"{label}. {timing} {money}{reserve_text}"


def run(project: str, cut: Any, kind: str, wbs: str = "", days: int = 0,
        acceleration_pct: float = 20.0) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError("неизвестный сценарий")
    cut_date = monitor._day(cut)
    if cut_date is None:
        raise ValueError("дата среза нужна в виде ГГГГ-ММ-ДД")
    if kind == "delay_wbs" and days <= 0:
        raise ValueError("задержка должна быть больше нуля")
    if kind == "accelerate_wbs" and acceleration_pct <= 0:
        raise ValueError("ускорение должно быть больше нуля")

    view = monitor.build(project, cut=cut_date)
    pm = graph._load_pm(project)
    if not pm.get("known"):
        raise ValueError("для сценария нужен сырой PM с зависимостями")
    targets = _target_ids(pm, wbs) if kind != "current_pace" else []
    if kind != "current_pace" and not targets:
        raise ValueError(f"WBS «{wbs}» не найден в PM-графике")

    current_seeds, scenario_seeds = _scenario_seeds(
        view, pm, cut_date, kind, targets, int(days), float(acceleration_pct)
    )
    base_tasks = graph._propagate(pm, current_seeds)
    scenario_tasks = graph._propagate(pm, scenario_seeds)
    approved_tasks = graph._propagate(pm, {})
    baseline_rnv = _network_rnv(pm, approved_tasks)
    current_rnv = _network_rnv(pm, base_tasks)
    scenario_rnv = _network_rnv(pm, scenario_tasks)

    finance = dashboard._finance_baseline(project)
    if not finance.get("known"):
        raise ValueError(finance.get("reason") or "не загружен финансовый baseline")
    rss = monitor._latest(project, "estimate", ".xlsx", monitor._iso(cut_date))
    if rss is None:
        raise FileNotFoundError("нет снимка РСС на дату сценария")
    estimate = dashboard.actuals.read_estimate(rss)
    current_finance = dashboard._rss_ch23(estimate)
    paid_actual = dashboard._payment_total_ch23(rss, estimate)
    # The cash programme is approved-baseline data. Therefore every scenario,
    # including "current pace", shifts it against approved PM dates (while the
    # headline schedule impact is still shown against today's forecast).
    shifts = _article_shifts(view, pm, approved_tasks, scenario_tasks)
    paid_by_code = dashboard._payment_by_code(rss)
    baseline_funding = dashboard._article_waterfall(
        finance.get("articles") or {}, float(finance.get("reserve") or 0.0),
        cut_date, paid_by_code,
    )
    articles = _shift_articles(finance.get("articles") or {}, shifts, cut_date)
    funding = dashboard._article_waterfall(
        articles, float(finance.get("reserve") or 0.0), cut_date,
        paid_by_code,
    )
    funding = {**funding,
        "reserve_start": monitor._iso(funding.get("reserve_start")),
        "reserve_exhaustion": monitor._iso(funding.get("reserve_exhaustion")),
    }
    baseline_funding = {**baseline_funding,
        "reserve_start": monitor._iso(baseline_funding.get("reserve_start")),
        "reserve_exhaustion": monitor._iso(baseline_funding.get("reserve_exhaustion")),
    }
    baseline_reserve = monitor._day(baseline_funding.get("reserve_exhaustion"))
    scenario_reserve = monitor._day(funding.get("reserve_exhaustion"))
    target_rows = [{
        "id": tid, "name": pm["tasks"][tid]["name"],
        "finish_before": monitor._iso(base_tasks[tid]["forecast_finish"]),
        "finish_after": monitor._iso(scenario_tasks[tid]["forecast_finish"]),
    } for tid in targets]
    return monitor._plain({
        "scenario": {"kind": kind, "wbs": wbs, "days": days,
                     "acceleration_pct": acceleration_pct},
        "state": {
            "cut": cut_date, "baseline_gpr": True, "rss_snapshot": rss.name,
            "pm_tasks": len(pm["tasks"]), "finance_source": finance.get("source"),
            "approved_budget": finance.get("approved"),
            "approved_budget_remaining": max(
                0.0, float(finance.get("approved") or 0.0) - paid_actual
            ),
            "completion_need": finance.get("completion_need_at_baseline"),
            "rss_bank_limit": current_finance.get("limit"),
            "paid_actual": paid_actual,
        },
        "schedule": {
            "approved_rnv": baseline_rnv, "current_pace_rnv": current_rnv,
            "scenario_rnv": scenario_rnv,
            "impact_vs_current_days": (scenario_rnv - current_rnv).days,
            "delay_vs_approved_days": (scenario_rnv - baseline_rnv).days,
            "targets": target_rows,
        },
        "funding": {
            "current_dds": {
                "reserve_start": baseline_funding.get("reserve_start"),
                "reserve_exhaustion": baseline_funding.get("reserve_exhaustion"),
                "additional_financing": baseline_funding.get("additional_financing"),
            },
            "scenario_dds": {
                "reserve_start": funding.get("reserve_start"),
                "reserve_exhaustion": funding.get("reserve_exhaustion"),
                "additional_financing": funding.get("additional_financing"),
            },
            "reserve_exhaustion_change_days": (
                (scenario_reserve - baseline_reserve).days
                if baseline_reserve and scenario_reserve else None
            ),
            "additional_financing_change": (
                float(funding.get("additional_financing") or 0.0)
                - float(baseline_funding.get("additional_financing") or 0.0)
            ),
            "remaining_article_limits": funding.get("remaining_article_limits"),
            "reserve_balance": funding.get("reserve_balance"),
            "reserve_exhaustion": funding.get("reserve_exhaustion"),
            "additional_financing": funding.get("additional_financing"),
            "monthly_unfunded": funding.get("monthly_unfunded"),
            "scope_note": (
                "Переносится только будущая потребность от даты среза. "
                "Прошлый план повторно не учитывается. Стоимость продления "
                "срока (проценты ПФ и дополнительные накладные) в этот контур "
                "пока не включена."
            ),
        },
        "answer": _answer(
            kind, wbs, days, scenario_rnv, baseline_rnv, funding,
            baseline_funding,
        ),
    })
