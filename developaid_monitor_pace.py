"""Act-paced forecast layer for DevelopAid Project Monitor.

The weekly RSS completed-works register is the only recurring evidence source.
For management purposes its accepted-cost ratio is used as an explicit proxy
for completion pace.  This module never calls that ratio a measured physical
quantity: it is labelled ``КС / EAC proxy`` everywhere.

The proxy is used for two things:

* show whether an active WBS/RSS scope is running ahead or behind its approved
  duration;
* seed only *late* finishes into the PM dependency graph, so float and
  successors determine the impact on project RNV.  Early proxy finishes are
  displayed locally but are not allowed to pull successors earlier.
"""
from __future__ import annotations

import datetime
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_schedule_graph as schedule_graph

_INSTALLED = False
_ORIGINAL_BUILD = None


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, number))


def _pace_finish(row: dict[str, Any], cut: datetime.date) -> tuple[datetime.date | None, str]:
    """Forecast one WBS finish from accepted-cost progress and observed pace.

    Prefer the rolling three-month accepted-cost rate already calculated from
    dated construction acts.  If there is not enough recent history, use the
    average accepted-cost pace since the approved task start.  The fallback is
    deliberately conservative: zero progress after planned start has no
    calculable finish rather than an invented remote date.
    """
    start = monitor._day(row.get("plan_start"))
    finish = monitor._day(row.get("plan_finish"))
    progress = _clamp(row.get("rss_accepted_ratio"))
    if not start or not finish or progress is None:
        return None, ""
    if cut < start:
        return None, "future"
    if progress >= 0.999999:
        return cut, "accepted_complete"

    rate_3m = row.get("rss_act_cost_rate_3m")
    try:
        monthly_rate = float(rate_3m or 0.0)
    except (TypeError, ValueError):
        monthly_rate = 0.0
    method = "rolling_3m_acts"

    if monthly_rate <= 1e-9:
        elapsed_days = max(0, (cut - start).days)
        if progress <= 1e-9 or elapsed_days <= 0:
            return None, "no_pace"
        elapsed_months = elapsed_days / 30.4375
        monthly_rate = progress / max(elapsed_months, 1 / 30.4375)
        method = "average_acts_since_start"

    if monthly_rate <= 1e-9:
        return None, "no_pace"
    remaining_months = max(0.0, (1.0 - progress) / monthly_rate)
    return cut + datetime.timedelta(days=round(remaining_months * 30.4375)), method


def _status(row: dict[str, Any], cut: datetime.date, predicted: datetime.date | None) -> str:
    start = monitor._day(row.get("plan_start"))
    finish = monitor._day(row.get("plan_finish"))
    progress = _clamp(row.get("rss_accepted_ratio"))
    if not start or not finish:
        return str(row.get("status") or "")
    if cut < start:
        return "БУДУЩАЯ ЗАДАЧА"
    if progress is not None and progress >= 0.999999:
        return "ЗАВЕРШЕНО ПО КС"
    if predicted is None:
        if progress is not None and progress <= 1e-9:
            return "НЕТ ТЕМПА КС / РИСК"
        return "НЕТ ДОСТАТОЧНОГО ТЕМПА ДЛЯ FORECAST"
    delta = (predicted - finish).days
    if delta > 1:
        return "ОТСТАВАНИЕ ПО ТЕМПУ КС"
    if delta < -1:
        return "ОПЕРЕЖЕНИЕ ПО ТЕМПУ КС"
    return "В СРОК ПО ТЕМПУ КС"


def _walk(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        out.append(node)
        out.extend(_walk([c for c in node.get("children", []) if isinstance(c, dict)]))
    return out


def _aggregate_management(nodes: list[dict[str, Any]]) -> None:
    def visit(node: dict[str, Any]) -> None:
        children = [c for c in node.get("children", []) if isinstance(c, dict)]
        for child in children:
            visit(child)
        if not children:
            return
        forecasts = [monitor._day(c.get("forecast_finish")) for c in children]
        forecasts = [d for d in forecasts if d]
        if forecasts:
            node["forecast_finish"] = monitor._iso(max(forecasts))
        finish = monitor._day(node.get("plan_finish"))
        forecast = monitor._day(node.get("forecast_finish"))
        if finish and forecast:
            node["delta_days"] = (forecast - finish).days
        node["pace_forecast_known"] = any(bool(c.get("pace_forecast_known")) for c in children)
    for root in nodes:
        visit(root)


def _apply_pace(project: str, view: dict[str, Any], cut: datetime.date) -> dict[str, Any]:
    schedule = view.get("schedule") or {}
    rows = schedule.get("rows") or []
    if not rows:
        return view

    evidence = 0
    late_seeds: dict[str, datetime.date] = {}
    own_forecasts: dict[str, datetime.date] = {}
    own_methods: dict[str, str] = {}

    for row in rows:
        predicted, method = _pace_finish(row, cut)
        row["pace_forecast_known"] = predicted is not None
        row["pace_forecast_method"] = method
        row["pace_progress"] = row.get("rss_accepted_ratio")
        row["progress_kind"] = "accepted_cost_proxy"
        row["progress_label"] = "КС / EAC proxy"
        if predicted is None:
            row["pace_status"] = _status(row, cut, None)
            continue
        evidence += 1
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        own_forecasts[tid] = predicted
        own_methods[tid] = method
        row["pace_forecast_finish"] = monitor._iso(predicted)
        finish = monitor._day(row.get("plan_finish"))
        if finish:
            row["pace_delta_days"] = (predicted - finish).days
            if predicted > finish:
                late_seeds[tid] = predicted
        row["pace_status"] = _status(row, cut, predicted)

    pm = schedule_graph._load_pm(project)
    propagated: dict[str, dict[str, Any]] = {}
    baseline_rnv = None
    network_rnv = None
    if pm.get("known"):
        propagated = schedule_graph._propagate(pm, late_seeds)
        rnv = propagated.get(pm.get("rnv_id")) if pm.get("rnv_id") else None
        baseline_rnv = rnv.get("finish") if rnv else max(
            (task["finish"] for task in propagated.values()), default=None
        )
        network_rnv = rnv.get("forecast_finish") if rnv else max(
            (task["forecast_finish"] for task in propagated.values()), default=None
        )

    flat = {str(row.get("id") or row.get("wbs") or "").strip(): row for row in rows}
    for tid, row in flat.items():
        own = own_forecasts.get(tid)
        network = (propagated.get(tid) or {}).get("forecast_finish") if propagated else None
        approved_rebaseline = (
            monitor._day(row.get("forecast_finish"))
            if str(row.get("forecast_source") or "") == "approved_rebaseline"
            else None
        )
        candidates = [d for d in (own, network, approved_rebaseline) if d]
        if candidates:
            # A PM-propagated late constraint must win.  An early local proxy is
            # still visible when there is no later network constraint.
            chosen = max(candidates) if any(d > (monitor._day(row.get("plan_finish")) or d) for d in candidates) else min(candidates)
            row["forecast_finish"] = monitor._iso(chosen)
            finish = monitor._day(row.get("plan_finish"))
            row["delta_days"] = (chosen - finish).days if finish else None
        row["status"] = row.get("pace_status") or row.get("status")
        row["forecast_source"] = (
            "КС/темп + PM dependencies" if propagated else "КС/темп"
        ) if row.get("pace_forecast_known") else row.get("forecast_source", "")

    management = schedule.get("management") or []
    for node in _walk(management):
        tid = str(node.get("id") or node.get("wbs") or "").strip()
        if not tid or tid not in flat:
            continue
        src = flat[tid]
        for key in (
            "forecast_finish", "delta_days", "status", "pace_status",
            "pace_forecast_finish", "pace_delta_days", "pace_forecast_known",
            "pace_forecast_method", "pace_progress", "progress_label",
        ):
            node[key] = src.get(key)
    _aggregate_management(management)

    forecast_known = evidence > 0
    if baseline_rnv is None:
        baseline_rnv = monitor._day(schedule.get("approved_end"))
    if network_rnv is None and forecast_known:
        # Without PM relationships the management tree can still show a proxy
        # finish, but the source is labelled accordingly.
        roots = [monitor._day(n.get("forecast_finish")) for n in management]
        roots = [d for d in roots if d]
        network_rnv = max(roots, default=baseline_rnv)

    if forecast_known:
        schedule["forecast_end"] = monitor._iso(network_rnv or baseline_rnv)
    graph = schedule.get("dependency_graph") or {}
    graph["forecast_known"] = forecast_known
    graph["forecast_source"] = (
        "КС / EAC proxy + PM dependencies" if pm.get("known") else "КС / EAC proxy; PM dependencies unavailable"
    ) if forecast_known else graph.get("forecast_source", "")
    graph["pace_evidence_tasks"] = evidence
    if baseline_rnv:
        graph["rnv_baseline"] = monitor._iso(baseline_rnv)
    if forecast_known and network_rnv:
        graph["rnv_forecast"] = monitor._iso(network_rnv)
        graph["rnv_delay_days"] = max(0, (network_rnv - baseline_rnv).days) if baseline_rnv else None
    schedule["dependency_graph"] = graph

    dash_schedule = ((view.get("dashboard") or {}).get("schedule") or {})
    if dash_schedule is not None:
        dash_schedule["approved_finish"] = monitor._iso(baseline_rnv) if baseline_rnv else dash_schedule.get("approved_finish")
        dash_schedule["forecast_finish"] = monitor._iso(network_rnv) if forecast_known and network_rnv else None
        dash_schedule["forecast_known"] = forecast_known
        dash_schedule["forecast_source"] = graph.get("forecast_source", "")
        dash_schedule["rnv_delay_days"] = graph.get("rnv_delay_days")
    return view


def _build(project: str, cut: Any, programme: dict[str, Any] | None = None, upto: str = "") -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("pace layer is not installed")
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    effective_cut = monitor._day(cut) or monitor._day(view.get("cut"))
    if effective_cut is None:
        return view
    return _apply_pace(project, view, effective_cut)


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    monitor.build = _build
    _INSTALLED = True
