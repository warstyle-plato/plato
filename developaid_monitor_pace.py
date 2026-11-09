"""One current work forecast for Monitor and report readers.

With PM disabled the GPR and explicitly bound natural cumulative quantities
own all public progress/forecast fields, including legacy API aliases.
The previous PM/act-cost implementation remains isolated for compatibility.
"""
from __future__ import annotations

import datetime
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_forecast as forecast
import developaid_monitor_reason as reason
import developaid_monitor_schedule_graph as schedule_graph
import developaid_schedule_timeline as schedule_timeline
import developaid_gpr_corpus as corpus_gpr
import developaid_schedule_confirmation as schedule_confirmation
import developaid_schedule_gpr_forecast as gpr_forecast
import developaid_schedule_gpr_physical as gpr_physical
import developaid_schedule_physical as schedule_physical
import developaid_schedule_work_fact as schedule_work_fact

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
        if forecast.pace_finish(row, cut)[1] == "stalled_pace":
            return "ПОЧТИ СТОИТ: ТЕМП НЕ ЭКСТРАПОЛИРУЕТСЯ"
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


_GPR_STATUS = {
    "done": "ЗАВЕРШЕНО ПО ГПР", "gpr_pace": "ПРОГНОЗ ПО ТЕМПУ ГПР",
    "cumulative_quantities": "ПРОГНОЗ ПО НАКОПИТЕЛЬНЫМ", "plan": "ПО ПЛАНУ ГПР",
    "cumulative_statement": "ВЫПОЛНЕНИЕ ПО ВЕДОМОСТИ",
    "cumulative_statement_pace": "ПРОГНОЗ ПО ДИНАМИКЕ ВЕДОМОСТЕЙ",
    "confirmed_completion": "ЗАВЕРШЕНИЕ ПОДТВЕРЖДЕНО", "cumulative_unknown": "НЕТ ТЕМПА ПО НАКОПИТЕЛЬНЫМ",
    "stalled": "СТОИТ: ПРОЦЕНТ НЕ РАСТЁТ", "stale": "НЕТ СВЕЖЕГО ГПР", "no_pace": "НЕТ ТЕМПА",
    "source_conflict": "РАСХОЖДЕНИЕ ГПР И НАКОПИТЕЛЬНЫХ",
}


def _aggregate_gpr(nodes: list[dict[str, Any]]) -> None:
    """Aggregate dates, never unlike work quantities or monetary percentages."""
    for node in nodes:
        children = node.get("children") or []
        _aggregate_gpr(children)
        if not children and node.get("level") == "task":
            continue
        known = [child for child in children if child.get("forecast_known")
                 and monitor._day(child.get("forecast_finish"))]
        finish = max((child["forecast_finish"] for child in known), default=None)
        partial = bool(known) and any(not child.get("forecast_known") or child.get("forecast_partial")
                                      for child in children)
        deltas = [child["delta_days"] for child in known if child.get("delta_days") is not None]
        node.update(actual_progress=None, actual_equivalent_date=None, pace_progress=None,
                    progress_kind="not_aggregated", progress_label="",
                    progress_reason="Разные работы не складываются в общий физический процент.",
                    progress_source={"kind": "not_aggregated", "date": None, "label": ""},
                    forecast_finish=finish, pace_forecast_finish=finish,
                    forecast_known=bool(known), pace_forecast_known=bool(known), forecast_partial=partial,
                    delta_days=max(deltas) if deltas else None,
                    forecast_source="gpr_children", pace_forecast_method="gpr_children",
                    forecast_reason=("Не у всех работ есть прогноз." if partial else
                                     "Позднейшая дата работ раздела." if known else
                                     "По работам раздела нет прогноза."))
        node["pace_forecast_reason"] = node["forecast_reason"]


def _apply_gpr(project: str, view: dict[str, Any], cut: datetime.date) -> dict[str, Any]:
    """PM is off (owner): forecasts from the GPR and cumulative KS, never money."""
    schedule = view.setdefault("schedule", {})
    rows = schedule.get("rows") or []
    physical = gpr_physical.build(project, cut.isoformat())
    ks = {task["task_id"]: task for task in physical.get("tasks") or []
          if (task.get("scope_confirmed") and task.get("mode") in {"quantities", "completed"})
          or (task.get("source_conflict") or {}).get("scope") == "source_cohort"}
    works = gpr_forecast.forecasts(project, cut, rows, ks)
    stalled = []
    for row in rows:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        item = works.get(tid) or {}
        finish = monitor._day(item.get("forecast_finish"))
        plan = monitor._day(row.get("plan_finish"))
        row["pace_progress"] = item.get("progress")
        row["pace_forecast_known"] = finish is not None
        row["pace_forecast_method"] = item.get("method")
        row["pace_forecast_reason"] = item.get("reason")
        row["pace_forecast_finish"] = monitor._iso(finish) if finish else None
        row["pace_delta_days"] = (finish - plan).days if finish and plan else None
        row["pace_status"] = _GPR_STATUS.get(item.get("method"), "НЕТ ДАННЫХ ГПР")
        origin = item.get("progress_origin")
        label = schedule_work_fact.GPR_ORIGINS.get(origin, "по ведомости" if origin == "cumulative_statement" else
                    "накопительные" if origin == "cumulative_quantities" else
                    "подтверждённое завершение" if origin == "confirmed_completion" else "ГПР")
        progress_reason = ""
        if item.get("progress") is None:
            bound = ks.get(tid) or {}
            progress_reason = ((bound.get("reason") or "Разные натуральные компоненты не складываются в общий процент.")
                               if origin in {"cumulative_quantities", "cumulative_statement"} else
                               item.get("reason") if item.get("method") == "unknown" else
                               "Нет датированного процента в ГПР.")
        # These public fields are the same facts as pace_*. Historical RSS
        # aliases must not keep a second forecast or a monetary physical fact.
        row.update(actual_progress=item.get("progress"), actual_equivalent_date=None,
                   progress_kind=origin if origin in {"cumulative_quantities", "cumulative_statement", "confirmed_completion"} else "gpr_percent",
                   progress_label=label, progress_source={"kind": origin, "date": item.get("progress_date"), "label": label,
                                                        "date_basis": item.get("progress_date_basis")},
                   progress_date_basis=item.get("progress_date_basis"), progress_basis=item.get("progress_basis"),
                   observation_history=item.get("observation_history"),
                   requires_reconciliation=item.get("requires_reconciliation") is True,
                   progress_reason=progress_reason,
                   forecast_finish=monitor._iso(finish) if finish else None,
                   forecast_known=finish is not None, forecast_source=item.get("method"),
                   source_conflict=item.get("source_conflict"),
                   forecast_reason=item.get("reason"), delta_days=row["pace_delta_days"],
                   status=row["pace_status"])
        # The display and the side-by-side evidence model use one dated GPR
        # reading, including an explicit unknown; never inherit an RSS ratio.
        if origin not in {"cumulative_quantities", "cumulative_statement", "confirmed_completion"}:
            row.update(gpr_progress=item.get("progress"), gpr_progress_origin=origin,
                       gpr_progress_date=item.get("progress_date"))
        row.pop("dependencies", None)
        row.pop("delay_reason", None)
        if item.get("method") == "stalled":
            stalled.append({"id": tid, "name": str(row.get("name") or ""),
                            "object": str(row.get("object") or ""),
                            "plan_finish": monitor._iso(plan), "progress": item.get("progress"),
                            "monthly_rate": None, "basis": "gpr", "method": item.get("method"),
                            "reason": item.get("reason")})
    by_id = {str(r.get("id") or r.get("wbs") or "").strip(): r for r in rows}
    for node in _walk(schedule.get("management") or []):
        src = by_id.get(
            str(node.get("id") or node.get("wbs") or "").strip())
        if not src:
            continue
        for key in ("pace_progress", "pace_forecast_known", "pace_forecast_method",
                    "pace_forecast_finish", "pace_delta_days", "pace_status", "pace_forecast_reason",
                    "actual_progress", "actual_equivalent_date", "progress_kind", "progress_label",
                    "progress_source", "progress_reason", "gpr_progress", "gpr_progress_origin", "gpr_progress_date",
                    "progress_date_basis", "progress_basis", "observation_history",
                    "requires_reconciliation",
                    "forecast_finish", "forecast_known", "forecast_source", "forecast_reason", "delta_days", "status"):
            node[key] = src.get(key)
        node["source_conflict"] = src.get("source_conflict")
        node.pop("dependencies", None)
        node.pop("delay_reason", None)
    _aggregate_gpr(schedule.get("management") or [])
    dash = view.setdefault("dashboard", {}).setdefault("schedule", {})
    approved = ((dash or {}).get("approved_finish") or schedule.get("approved_end")
                or max((r.get("plan_finish") for r in rows if r.get("plan_finish") and (str(r.get("code") or "").strip() or r.get("construction_work") is True)), default=None))
    qualified = gpr_forecast.rnv(rows, works, approved,
        missing_calendar=physical.get("source_calendar_missing") or [])
    schedule["dependency_timeline"] = {"state": "ok", "rows": [], "edges": [], "rnv": qualified,
                                       "confirmation": {}, "basis": "gpr", "physical": physical}
    schedule["physical_progress"] = physical
    schedule["work_fact"] = schedule_work_fact.model(rows, physical)
    schedule["gpr_forecasts"] = works
    schedule.update(basis="gpr", forecast_state=qualified["state"],
                    forecast_end=qualified.get("forecast"), pace_forecast_end=qualified.get("forecast"),
                    indicative_forecast_end=qualified.get("indicative_forecast"),
                    fact_source="Проценты ГПР, решения в Мониторе и явно сопоставленные натуральные накопительные.",
                    forecast_method="По собственному темпу работ ГПР, без MS Project и денежного темпа КС.",
                    risks=sum(1 for row in rows if (row.get("delta_days") or 0) > 0 or
                              (monitor._day(row.get("plan_finish")) and monitor._day(row["plan_finish"]) < cut
                               and not row.get("forecast_known"))))
    view["by_code"] = rows
    schedule["dependency_timeline_html"] = schedule_timeline.render(schedule["dependency_timeline"])
    schedule["corpus_gpr"] = corpus_gpr.for_view(project, cut.isoformat(),
        baseline_sha256=physical.get("source_sha256") or "")
    schedule["corpus_gpr_html"] = corpus_gpr.render_overview(schedule["corpus_gpr"], cut.isoformat())
    if isinstance(dash, dict):
        driver = (qualified.get("driving_chain") or [None])[0]
        dash.update(qualified_rnv=qualified, stalled=stalled,
                    forecast_known=qualified["state"] == "estimate",
                    forecast_finish=qualified.get("forecast"),
                    forecast_source="ГПР, без цепочки до разрешения",
                    rnv_delay_days=qualified.get("delay_days") if qualified["state"] == "estimate" else None,
                    driver={"id": driver["id"], "name": driver["name"]} if driver else None)
        from developaid_monitor_dashboard import refresh_schedule_summary
        refresh_schedule_summary(view)
    return view


def _apply_pace(project: str, view: dict[str, Any], cut: datetime.date) -> dict[str, Any]:
    schedule = view.get("schedule") or {}
    rows = schedule.get("rows") or []
    # One decision point: the PM reader itself says that PM is off.
    if schedule_graph._load_pm(project).get("disabled"):
        return _apply_gpr(project, view, cut)
    if not rows:
        return view

    evidence = 0
    local_forecasts: dict[str, datetime.date] = {}
    local_methods: dict[str, str] = {}
    late_seeds: dict[str, datetime.date] = {}
    stalled: list[dict[str, Any]] = []

    for row in rows:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        predicted, method = _pace_finish(row, cut)
        if method == "stalled_pace":
            stalled.append(forecast.stalled_item(row))
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
        method = None
        if network and plan and network > plan:
            effective = max([d for d in (own, network) if d]) if own else network
        stalled_row = row.get("pace_forecast_method") == "stalled_pace"
        if (effective is None and network and plan and not row.get("baseline_closed")
                and not stalled_row):
            # Работа, которая почти стоит, «по плану» не идёт: подставить ей
            # плановый срок значило бы спрятать остановку.
            # Работа без собственного темпа КС — не «без прогноза»: её прогноз
            # строится от плановой длительности, а старт сдвигается задержкой
            # предшественников по PM-сети (сдвинутые ловятся веткой выше, здесь
            # остаётся «сеть не двигает — идёт по плану»). Прогноз в прошлом
            # прогнозом не считается: просроченная работа без актов — риск.
            if plan >= cut:
                effective = plan
                method = "plan_duration_shifted_by_predecessors"
        if effective is None:
            continue
        row["pace_forecast_finish"] = monitor._iso(effective)
        row["pace_delta_days"] = (effective - plan).days if plan else None
        if method is None:
            method = (
                "acts_pace_plus_pm_dependencies"
                if network and plan and network > plan
                else local_methods.get(tid, row.get("pace_forecast_method", ""))
            )
        row["pace_forecast_method"] = method
        row["pace_forecast_known"] = True
        if method == "plan_duration_shifted_by_predecessors":
            row["pace_status"] = "ПО ПЛАНУ (ТЕМПА КС НЕТ)"
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

    qualified_pm = schedule_confirmation.qualify(project, pm, cut.isoformat())
    physical = schedule_physical.build(project, cut.isoformat(), pm)
    qualified_pm['validation_issues'] = list(qualified_pm.get('validation_issues') or [])
    qualified_pm['validation_issues'].extend(physical['reasons'])
    # Legacy cost/EAC remains a separately qualified management indicator.
    # Once natural evidence exists, it exclusively seeds the physical timeline;
    # a cost-derived delay can never leak into a certified physical RNV.
    timeline_seeds = late_seeds
    if physical['physical_evidence']:
        timeline_seeds = {tid: monitor._day(value) for tid, value in physical['seeds'].items()}
        for row in rows:
            if row.get('rebaseline_seed') or row.get('forecast_source') == 'approved_rebaseline':
                tid = str(row.get('id') or row.get('wbs') or '').strip()
                value = monitor._day(row.get('forecast_finish'))
                if tid and value:
                    timeline_seeds[tid] = max(value, timeline_seeds.get(tid, value))
    else:
        qualified_pm['validation_issues'].append(
            'Натуральная выработка КС и её сопоставление с работами графика ещё не подтверждены. '
            'Стоимостный темп КС не доказывает физическую готовность.')
    schedule["dependency_timeline"] = schedule_timeline.model(
        qualified_pm, timeline_seeds, evidence=bool(physical['physical_evidence'] or evidence or late_seeds),
        actual_finishes={tid: monitor._day(value) for tid, value in physical.get('actual_finishes', {}).items()})
    schedule['dependency_timeline']['physical'] = physical
    rnv_block = schedule['dependency_timeline'].get('rnv') or {}
    if not rnv_block.get('approved'):
        # Without a PM milestone (PM is off) the approved RNV is still the GPR
        # plan; a missing network must not erase it from cards and summary.
        dash_plan = ((view.get('dashboard') or {}).get('schedule') or {}).get('approved_finish')
        approved = monitor._day(dash_plan or schedule.get('approved_end'))
        if approved:
            rnv_block['approved'] = approved.isoformat()
            rnv_block['approved_source'] = 'утверждённый ГПР'
            schedule['dependency_timeline']['rnv'] = rnv_block
    schedule['physical_progress'] = physical
    # One owner of both readiness facts per work, read by the chart and summary.
    schedule['work_fact'] = schedule_work_fact.model(rows, physical)
    if isinstance((view.get("dashboard") or {}).get("schedule"), dict):
        view["dashboard"]["schedule"]["qualified_rnv"] = schedule["dependency_timeline"]["rnv"]
        # A prebuilt summary may have been produced before RNV qualification.
        # Refresh its schedule sentence from the same source as the cards,
        # without recalculating or rewriting any financial paragraph.
        from developaid_monitor_dashboard import refresh_schedule_summary
        refresh_schedule_summary(view)
    schedule["dependency_timeline_html"] = schedule_timeline.render(schedule["dependency_timeline"])
    schedule["corpus_gpr"] = corpus_gpr.latest(project, cut.isoformat())
    schedule["corpus_gpr_html"] = corpus_gpr.render_overview(schedule["corpus_gpr"], cut.isoformat())
    if evidence <= 0:
        return _physical_dashboard(view)

    if baseline_rnv is None:
        baseline_rnv = monitor._day(schedule.get("approved_end"))
    if network_rnv is None:
        roots = [_effective_child_finish(n) for n in management]
        roots = [d for d in roots if d]
        network_rnv = max(roots, default=baseline_rnv)

    graph = schedule.get("dependency_graph") or {}
    graph["pace_forecast_known"] = True
    graph["pace_forecast_source"] = (
        "темп актов КС + PM-зависимости"
        if pm.get("known") else "темп актов КС; PM-выгрузки нет"
    )
    if stalled:
        graph["pace_forecast_source"] += (
            f"; без {len(stalled)} работ, которые почти стоят — их темп не экстраполируется")
    graph["pace_stalled"] = stalled
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
    dash_schedule["stalled"] = stalled
    dash_schedule["driver"] = _driver(pm, propagated, network_rnv, baseline_rnv, rows)
    return _physical_dashboard(view)


def _physical_dashboard(view):
    timeline = (view.get('schedule') or {}).get('dependency_timeline') or {}
    physical = timeline.get('physical') or {}
    if physical.get('physical_evidence'):
        qualified = timeline['rnv']
        schedule = (view.get('dashboard') or {}).get('schedule')
        if isinstance(schedule, dict):
            schedule.update(forecast_known=qualified['state'] == 'complete',
                            forecast_finish=qualified['forecast'],
                            forecast_source='натуральные объёмы, подтверждённые факты и цепочка PM',
                            rnv_delay_days=qualified['delay_days'] if qualified['state'] == 'complete' else None,
                            driver=None, physical_driving_chain=qualified['driving_chain'])
    return view


def _driver(pm: dict[str, Any], propagated: dict[str, dict[str, Any]],
            network_rnv: datetime.date | None, baseline_rnv: datetime.date | None,
            rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Работа, которая тянет прогноз ввода.

    Владелец, 27.10.2026: рядом с прогнозом ввода назвать работу, которая
    тянет срок. С PM-сетью — след от вехи ввода назад по той же сети, что дала
    прогноз (`schedule_graph.driver`); без сети РНВ — самый поздний финиш строк,
    и тянет его строка с этим финишем. Ввод в срок — называть некого.
    """
    if not network_rnv or not baseline_rnv or network_rnv <= baseline_rnv:
        return None
    by_id = {forecast._row_id(row): row for row in rows}
    if propagated:
        end = pm.get("rnv_id") if pm.get("rnv_id") in propagated else max(
            propagated, key=lambda tid: propagated[tid]["forecast_finish"])
        tid = schedule_graph.driver(propagated, end)
        if not tid:
            return None
        task = propagated[tid]
        row = by_id.get(tid, {})
        name = task.get("name") or row.get("name")
        plan, finish = task["finish"], task["forecast_finish"]
    else:
        late = [row for row in rows if row.get("pace_forecast_finish")
                and monitor._day(row["pace_forecast_finish"]) == network_rnv]
        if not late:
            return None
        row = late[0]
        tid, name = forecast._row_id(row), row.get("name")
        plan = monitor._day(row.get("plan_finish"))
        finish = monitor._day(row["pace_forecast_finish"])
    return {"id": tid, "name": str(name or ""), "object": str(row.get("object") or ""),
            "rss_codes": monitor._codes(row.get("code")),
            "plan_finish": monitor._iso(plan), "forecast_finish": monitor._iso(finish),
            "progress": row.get("rss_accepted_ratio"), "pace_3m": row.get("rss_act_cost_rate_3m"),
            "method": row.get("pace_forecast_method") or "",
            "rnv_delay_days": (network_rnv - baseline_rnv).days}


def _build(project: str, cut: Any, programme: dict[str, Any] | None = None, upto: str = "") -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("pace layer is not installed")
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    effective_cut = monitor._day(cut) or monitor._day(view.get("cut"))
    if effective_cut:
        view = _apply_pace(project, view, effective_cut)
    # Причина сдвига проставляется последней: она читает уже посчитанные
    # числа — свой сдвиг, унаследованный, запас — и ничего не считает сама.
    # Красный хвост без объяснения читается как сдвиг ниоткуда, особенно у
    # работы, по которой фактов нет вовсе (владелец, 29.08.2026).
    return reason.annotate(view)


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    monitor.build = _build
    _INSTALLED = True
