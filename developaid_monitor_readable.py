"""Readable Project Monitor layer: RSS progress -> schedule variance + corpus view.

This layer deliberately uses accepted construction acts as the operational
progress proxy requested for Project Monitor. It does *not* extrapolate the
last 3 months of money into years of calendar duration. Instead it compares the
accepted-cost progress with the linear position of the approved task on the
cut date and converts that progress gap into schedule days.

Example: a 200-day task should be 60% complete but RSS acts show 50%.
The 10 pp gap equals 20 schedule days, so its local forecast finish is plan +20d.
Positive local delays are then propagated through the real PM dependency graph.
"""
from __future__ import annotations

import copy
import datetime
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
import developaid_monitor_manager as manager
import developaid_monitor_schedule_graph as schedule_graph

_INSTALLED = False
_ORIGINAL_BUILD = None


def _day(value: Any) -> datetime.date | None:
    return monitor._day(value)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, number))


def _plan_progress(start: datetime.date, finish: datetime.date, cut: datetime.date) -> float:
    if cut < start:
        return 0.0
    if cut >= finish:
        return 1.0
    duration = max(1, (finish - start).days)
    return max(0.0, min(1.0, (cut - start).days / duration))


def _progress_forecast(
    start: datetime.date,
    finish: datetime.date,
    cut: datetime.date,
    progress: float | None,
    last_act: datetime.date | None = None,
) -> dict[str, Any]:
    """Translate RSS progress vs approved linear plan into local schedule days.

    The future is assumed to continue at the approved task pace. This gives a
    stable schedule variance without the previous volatile recent-money-rate
    extrapolation. Ahead-of-plan progress produces a negative delta; lagging
    progress produces a positive delta.
    """
    plan = _plan_progress(start, finish, cut)
    if progress is None:
        return {
            "known": False,
            "plan_progress": plan,
            "equivalent_date": None,
            "forecast_finish": finish,
            "delta_days": None,
            "status": "НЕТ ДАННЫХ КС",
        }

    p = max(0.0, min(1.0, progress))
    duration = max(1, (finish - start).days)
    equivalent = start + datetime.timedelta(days=round(duration * p))

    if p >= 0.999999:
        actual_finish = last_act or min(cut, finish)
        delta = (actual_finish - finish).days
        return {
            "known": True,
            "plan_progress": plan,
            "equivalent_date": actual_finish,
            "forecast_finish": actual_finish,
            "delta_days": delta,
            "status": "ЗАВЕРШЕНО",
        }

    if cut < start:
        # Work is not yet due. Do not invent a delay from a zero act balance.
        return {
            "known": True,
            "plan_progress": 0.0,
            "equivalent_date": equivalent if p > 0 else None,
            "forecast_finish": finish,
            "delta_days": 0,
            "status": "БУДУЩАЯ ЗАДАЧА",
        }

    variance_days = (cut - equivalent).days
    forecast = finish + datetime.timedelta(days=variance_days)
    # An incomplete task cannot forecast a finish in the past relative to the cut.
    if forecast < cut:
        forecast = cut
    delta = (forecast - finish).days
    if delta > 3:
        status = "ОТСТАВАНИЕ"
    elif delta < -3:
        status = "ОПЕРЕЖЕНИЕ"
    else:
        status = "В СРОК"
    return {
        "known": True,
        "plan_progress": plan,
        "equivalent_date": equivalent,
        "forecast_finish": forecast,
        "delta_days": delta,
        "status": status,
    }


def _apply_rss_schedule_forecast(schedule: dict[str, Any], cut: datetime.date) -> int:
    seeds = 0
    for row in schedule.get("rows") or []:
        start = _day(row.get("plan_start"))
        finish = _day(row.get("plan_finish"))
        if start is None or finish is None:
            continue
        progress = _clamp(row.get("rss_accepted_ratio"))
        if progress is None:
            # On builds where the manager sanitiser has not run, keep the base
            # RSS progress rather than losing the fact source.
            progress = _clamp(row.get("actual_progress"))
        last_act = _day(row.get("last_act"))
        result = _progress_forecast(start, finish, cut, progress, last_act)
        row["actual_progress"] = progress
        row["plan_progress"] = result["plan_progress"]
        row["actual_equivalent_date"] = monitor._iso(result["equivalent_date"])
        row["forecast_finish"] = monitor._iso(result["forecast_finish"])
        row["delta_days"] = result["delta_days"]
        row["status"] = result["status"]
        row["progress_kind"] = "accepted_cost_progress_proxy"
        row["progress_label"] = "КС / лимит статьи"
        row["forecast_source"] = "rss_progress_vs_plan" if result["known"] else ""
        row["schedule_variance_days"] = result["delta_days"]
        if result["known"] and result["delta_days"] not in (None, 0):
            seeds += 1
    schedule["forecast_method"] = (
        "КС/лимит статьи как proxy выполнения → сравнение с линейным плановым % "
        "на дату среза → отклонение в днях → PM-зависимости и float"
    )
    return seeds


def _corpus_label(task: dict[str, Any]) -> str:
    fields = [task.get("object"), task.get("section"), task.get("name")]
    patterns = (
        r"\bкорпус\s*[№#-]?\s*([0-9]+(?:[.-][0-9]+)?)",
        r"\bкорп\.?\s*[№#-]?\s*([0-9]+(?:[.-][0-9]+)?)",
        r"\bк\.?\s*([1-9][0-9]?)\b",
    )
    for value in fields:
        text = _norm(value)
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return f"Корпус {match.group(1).replace('-', '.')}"
    obj = str(task.get("object") or "").strip()
    if obj and len(obj) <= 80:
        return obj
    return "Общие работы"


def _natural(value: Any) -> tuple:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.findall(r"\d+|[^\d]+", str(value or ""))
    )


def _summary_node(name: str, key: str, level: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    starts = [_day(item.get("plan_start")) for item in children]
    finishes = [_day(item.get("plan_finish")) for item in children]
    forecasts = [_day(item.get("forecast_finish")) for item in children]
    starts = [d for d in starts if d]
    finishes = [d for d in finishes if d]
    forecasts = [d for d in forecasts if d]
    start = min(starts) if starts else None
    finish = max(finishes) if finishes else None
    forecast = max(forecasts) if forecasts else finish
    delta = (forecast - finish).days if forecast and finish else None
    if delta is None:
        status = "—"
    elif delta > 3:
        status = "ОТСТАВАНИЕ"
    elif delta < -3:
        status = "ОПЕРЕЖЕНИЕ"
    else:
        status = "В СРОК"
    return {
        "key": key,
        "level": level,
        "name": name,
        "plan_start": monitor._iso(start),
        "plan_finish": monitor._iso(finish),
        "forecast_finish": monitor._iso(forecast),
        "delta_days": delta,
        "status": status,
        "children": children,
    }


def _split_main_objects(management: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Show project bodies one after another instead of mixing repeated RSS rows."""
    result: list[dict[str, Any]] = []
    for root in management:
        if root.get("name") != "Основные объекты":
            result.append(root)
            continue

        rss_nodes: list[dict[str, Any]] = []
        for detail in root.get("children") or []:
            for rss in detail.get("children") or []:
                if isinstance(rss, dict) and rss.get("level") == "rss":
                    clone = copy.deepcopy(rss)
                    clone["_detail_name"] = detail.get("name") or "Работы"
                    rss_nodes.append(clone)

        code_corpuses: dict[str, set[str]] = {}
        pieces: dict[str, list[dict[str, Any]]] = {}
        for rss in rss_nodes:
            tasks = [item for item in rss.get("children") or [] if isinstance(item, dict)]
            by_corpus: dict[str, list[dict[str, Any]]] = {}
            for task in tasks:
                by_corpus.setdefault(_corpus_label(task), []).append(task)
            for corpus, corpus_tasks in by_corpus.items():
                code = str(rss.get("code") or "")
                if code:
                    code_corpuses.setdefault(code, set()).add(corpus)
                item = copy.deepcopy(rss)
                item["children"] = corpus_tasks
                item["object"] = corpus
                item["key"] = f"{rss.get('key','rss')}:{corpus}"
                starts = [_day(t.get("plan_start")) for t in corpus_tasks]
                finishes = [_day(t.get("plan_finish")) for t in corpus_tasks]
                forecasts = [_day(t.get("forecast_finish")) for t in corpus_tasks]
                starts = [d for d in starts if d]
                finishes = [d for d in finishes if d]
                forecasts = [d for d in forecasts if d]
                if starts:
                    item["plan_start"] = monitor._iso(min(starts))
                if finishes:
                    item["plan_finish"] = monitor._iso(max(finishes))
                if forecasts:
                    item["forecast_finish"] = monitor._iso(max(forecasts))
                pf = _day(item.get("plan_finish")); ff = _day(item.get("forecast_finish"))
                item["delta_days"] = (ff - pf).days if pf and ff else None
                pieces.setdefault(corpus, []).append(item)

        corpus_nodes: list[dict[str, Any]] = []
        for corpus in sorted(pieces, key=_natural):
            by_detail: dict[str, list[dict[str, Any]]] = {}
            for rss in pieces[corpus]:
                code = str(rss.get("code") or "")
                shared = len(code_corpuses.get(code, set())) > 1
                rss["finance_scope"] = (
                    "общий RSS-код; суммы не разделены по корпусам" if shared else "корпус"
                )
                if shared:
                    rss["shared_finance"] = True
                by_detail.setdefault(str(rss.pop("_detail_name", "Работы")), []).append(rss)
            details: list[dict[str, Any]] = []
            for detail_name, rss_children in sorted(by_detail.items(), key=lambda x: _natural(x[0])):
                rss_children.sort(key=lambda x: _natural(x.get("code")))
                details.append(_summary_node(
                    detail_name,
                    f"corpus-detail:{corpus}:{detail_name}",
                    "detail",
                    rss_children,
                ))
            corpus_nodes.append(_summary_node(
                corpus,
                f"corpus:{corpus}",
                "corpus",
                details,
            ))

        if corpus_nodes:
            result.append(_summary_node(
                "Основные объекты",
                "control:Основные объекты",
                "control",
                corpus_nodes,
            ))
        else:
            result.append(root)
    return result


def _walk(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        out.append(node)
        out.extend(_walk([c for c in node.get("children") or [] if isinstance(c, dict)]))
    return out


def _attach_financial_bars(
    project: str,
    rss: Path,
    cut: datetime.date,
    nodes: list[dict[str, Any]],
    funding: dict[str, Any],
) -> None:
    baseline = dashboard._finance_baseline(project)
    base_articles = baseline.get("articles") or {}
    waterfall = {
        str(item.get("code") or ""): item
        for item in (funding.get("articles") or [])
        if item.get("code")
    }
    paid_by_code = dashboard._payment_by_code(rss)
    cut_month = cut.replace(day=1)

    for node in _walk(nodes):
        if node.get("level") != "rss":
            continue
        code = str(node.get("code") or "").rstrip(".")
        source = base_articles.get(code) or {}
        wf = waterfall.get(code) or {}
        limit = float(source.get("rss_limit") or node.get("eac") or 0.0)
        paid = float(paid_by_code.get(code) or (node.get("payments") or {}).get("fact_total") or 0.0)
        need = 0.0
        for month, amount in (source.get("monthly_need") or {}).items():
            day = _day(month)
            if day and day >= cut_month:
                need += max(0.0, float(amount or 0.0))
        node["finance"] = {
            "limit": limit,
            "paid": paid,
            "need": need,
            "remaining_limit": float(wf.get("opening_limit") or max(0.0, limit - paid)),
            "first_reserve_month": wf.get("first_reserve_month") or "",
            "paid_ratio": paid / limit if limit > 0 else None,
            "need_ratio": need / limit if limit > 0 else None,
            "overflow": max(0.0, need - max(0.0, limit - paid)),
            "scope": node.get("finance_scope") or "RSS",
        }


def _sync_dashboard(view: dict[str, Any]) -> None:
    schedule = view.get("schedule") or {}
    graph = schedule.get("dependency_graph") or {}
    dash = view.get("dashboard") or {}
    d_schedule = dash.get("schedule") or {}
    d_schedule.update({
        "approved_finish": schedule.get("approved_end"),
        "forecast_finish": schedule.get("forecast_end"),
        "forecast_known": graph.get("forecast_known", False),
        "forecast_source": graph.get("forecast_source", ""),
        "rnv_delay_days": graph.get("rnv_delay_days"),
    })
    dash["schedule"] = d_schedule
    view["dashboard"] = dash
    if view.get("financing") is not None:
        view["financing"]["forecast_to"] = schedule.get("forecast_end") or schedule.get("approved_end")
        if dash.get("funding") is not None:
            dash["funding"]["forecast_to"] = view["financing"]["forecast_to"]


def _build(project: str, cut: Any, programme: dict[str, Any] | None = None, upto: str = "") -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("readable monitor layer is not installed")
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    cut_date = _day(cut) or _day(view.get("cut"))
    rss = monitor._latest(project, "estimate", ".xlsx", upto or monitor._iso(cut_date))
    if cut_date is None or rss is None:
        return view

    _apply_rss_schedule_forecast(view.get("schedule") or {}, cut_date)
    # Re-run the PM graph with the RSS-derived local delays as explicit seeds.
    view = schedule_graph.apply(project, view)

    management = manager._management(project, rss, view["schedule"])
    cash = manager._payments(project, rss)
    manager._attach_payments(management, cash)
    management = _split_main_objects(management)
    _attach_financial_bars(project, rss, cut_date, management, view.get("financing") or {})
    view["schedule"]["management"] = monitor._plain(management)
    view["payments"] = monitor._plain(cash)
    _sync_dashboard(view)
    return view


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    monitor.build = _build
    _INSTALLED = True
