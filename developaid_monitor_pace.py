"""Act-paced forecast overlay for DevelopAid Project Monitor.

The weekly RSS completed-works register is the recurring state/evidence source.
Accepted cost / EAC is used as an explicit management proxy for progress pace.
It does NOT overwrite the fixed ``schedule.rows`` baseline/approved forecast.
Pace results live in ``pace_*`` fields; only the derived management tree and
project dashboard expose them as the current forecast.
"""
from __future__ import annotations

import datetime
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_forecast as forecast
import developaid_monitor_schedule_graph as schedule_graph

_INSTALLED = False
_ORIGINAL_BUILD = None


# Формула прогноза и правило отбора seeds объявлены один раз — в
# `developaid_monitor_forecast`. Копия здесь отвечала иначе на завершённых
# задачах, и сценарий «Текущий темп» получал другую сеть, чем эта карточка.
_clamp = forecast._clamp
_pace_finish = forecast.pace_finish


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


def _effective_child_finish(child: dict[str, Any]) -> datetime.date | None:
    return (
        monitor._day(child.get("pace_forecast_finish"))
        or monitor._day(child.get("forecast_finish"))
        or monitor._day(child.get("plan_finish"))
    )


def _aggregate_management(nodes: list[dict[str, Any]]) -> None:
    """Roll pace forecast up on presentation nodes, leaving schedule.rows intact."""
    def visit(node: dict[str, Any]) -> None:
        children = [c for c in node.get("children", []) if isinstance(c, dict)]
        for child in children:
            visit(child)
        if not children:
            return
        known = any(bool(c.get("pace_forecast_known")) for c in children)
        node["pace_forecast_known"] = known
        if not known:
            return
        finishes = [_effective_child_finish(c) for c in children]
        finishes = [d for d in finishes if d]
        if not finishes:
            return
        forecast = max(finishes)
        finish = monitor._day(node.get("plan_finish"))
        delta = (forecast - finish).days if finish else None
        node["pace_forecast_finish"] = monitor._iso(forecast)
        node["pace_delta_days"] = delta
        # management is a derived presentation tree, so it may expose pace as
        # its current forecast while the auditable schedule.rows stay untouched.
        node["forecast_finish"] = monitor._iso(forecast)
        node["delta_days"] = delta
    for root in nodes:
        visit(root)


def _apply_pace(project: str, view: dict[str, Any], cut: datetime.date) -> dict[str, Any]:
    schedule = view.get("schedule") or {}
    rows = schedule.get("rows") or []
    if not rows:
        return view

    evidence = 0
    local_forecasts: dict[str, datetime.date] = {}
    local_methods: dict[str, str] = {}
    late_seeds: dict[str, datetime.date] = {}

    for row in rows:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        predicted, method = _pace_finish(row, cut)
        row["pace_progress"] = row.get("rss_accepted_ratio")
        row["pace_forecast_known"] = predicted is not None
        row["pace_forecast_method"] = method
        row["pace_status"] = (
            "КС — ТОЛЬКО СТОИМОСТНОЙ ИНДИКАТОР"
            if method == "mixed_lifecycle_rss"
            else _status(row, cut, predicted)
        )
        # Keep manager contract: progress_kind stays accepted_cost_ratio.
        if predicted is None:
            continue
        evidence += 1
        local_forecasts[tid] = predicted
        local_methods[tid] = method
        row["pace_forecast_finish"] = monitor._iso(predicted)
        finish = monitor._day(row.get("plan_finish"))
        row["pace_delta_days"] = (predicted - finish).days if finish else None
        if finish and predicted > finish:
            late_seeds[tid] = predicted

    # Approved rebaseline is propagated together with late current-pace seeds.
    for row in rows:
        if not (row.get("rebaseline_seed") or str(row.get("forecast_source") or "") == "approved_rebaseline"):
            continue
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        approved = monitor._day(row.get("forecast_finish"))
        if tid and approved:
            late_seeds[tid] = max(approved, late_seeds.get(tid, approved))

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
    affected = 0
    for tid, row in flat.items():
        own = local_forecasts.get(tid)
        network = (propagated.get(tid) or {}).get("forecast_finish") if propagated else None
        plan = monitor._day(row.get("plan_finish"))
        effective = own
        if network and plan and network > plan:
            effective = max([d for d in (own, network) if d]) if own else network
        if effective is None:
            continue
        row["pace_forecast_finish"] = monitor._iso(effective)
        row["pace_delta_days"] = (effective - plan).days if plan else None
        row["pace_forecast_method"] = (
            "acts_pace_plus_pm_dependencies"
            if network and plan and network > plan
            else local_methods.get(tid, row.get("pace_forecast_method", ""))
        )
        row["pace_forecast_known"] = True
        if network and plan and network > plan:
            affected += 1

    management = schedule.get("management") or []
    for node in _walk(management):
        tid = str(node.get("id") or node.get("wbs") or "").strip()
        src = flat.get(tid)
        if not src:
            continue
        for key in (
            "pace_progress", "pace_forecast_known", "pace_forecast_method",
            "pace_forecast_finish", "pace_delta_days", "pace_status",
        ):
            node[key] = src.get(key)
        if src.get("pace_forecast_known") and src.get("pace_forecast_finish"):
            node["forecast_finish"] = src["pace_forecast_finish"]
            node["delta_days"] = src.get("pace_delta_days")
            node["status"] = src.get("pace_status") or node.get("status")
    _aggregate_management(management)

    if evidence <= 0:
        return view

    if baseline_rnv is None:
        baseline_rnv = monitor._day(schedule.get("approved_end"))
    if network_rnv is None:
        roots = [_effective_child_finish(n) for n in management]
        roots = [d for d in roots if d]
        network_rnv = max(roots, default=baseline_rnv)

    graph = schedule.get("dependency_graph") or {}
    graph["pace_forecast_known"] = True
    graph["pace_forecast_source"] = (
        "КС / EAC proxy + PM dependencies"
        if pm.get("known") else "КС / EAC proxy; PM dependencies unavailable"
    )
    graph["pace_evidence_tasks"] = evidence
    graph["pace_network_affected_tasks"] = affected
    graph["pace_rnv_forecast"] = monitor._iso(network_rnv) if network_rnv else None
    graph["pace_rnv_delay_days"] = (
        (network_rnv - baseline_rnv).days
        if network_rnv and baseline_rnv else None
    )
    schedule["dependency_graph"] = graph
    schedule["pace_forecast_end"] = monitor._iso(network_rnv) if network_rnv else None

    dash_schedule = ((view.get("dashboard") or {}).get("schedule") or {})
    dash_schedule["forecast_known"] = True
    dash_schedule["forecast_finish"] = monitor._iso(network_rnv) if network_rnv else None
    dash_schedule["forecast_source"] = graph["pace_forecast_source"]
    dash_schedule["rnv_delay_days"] = graph["pace_rnv_delay_days"]
    return view


def _build(project: str, cut: Any, programme: dict[str, Any] | None = None, upto: str = "") -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("pace layer is not installed")
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    effective_cut = monitor._day(cut) or monitor._day(view.get("cut"))
    return _apply_pace(project, view, effective_cut) if effective_cut else view


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    monitor.build = _build
    _INSTALLED = True
