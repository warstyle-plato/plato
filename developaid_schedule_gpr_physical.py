"""Source-qualified GPR-work ↔ natural cumulative quantities, without PM.

The binding is private, versioned and tied to the exact approved GPR bytes and
cumulative snapshot. Initial derived bindings require a closed operation rule
and the complete explicit work scope; a name or contractor alone is not enough.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_schedule_physical as quantities
import developaid_schedule_gpr_forecast as gpr_forecast
import developaid_cumulative_progress as cumulative_progress
import developaid_gpr_cumulative_matching as cumulative_matching

PhysicalProblem = quantities.PhysicalProblem
SOURCE_KIND = "gpr"


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _source(project, cut=""):
    path = monitor._baseline_file(project)
    if path is None:
        import developaid_gpr_corpus as corpus_gpr
        corpus = corpus_gpr.latest(project, cut)
        reason = ("Корпусный ГПР доступен для просмотра. Чтобы привязать накопительные, "
                  "нужно явно утвердить состав работ или сопоставить пакет и корпус с работой утверждённого ГПР."
                  if corpus else "Утверждённый ГПР не загружен.")
        return {"source_sha256": "", "tasks": {}, "reason": reason,
                "state": "unapproved_corpus" if corpus else "missing"}
    data = path.read_bytes()
    parsed = monitor._read_baseline_gpr_bytes(data)
    hierarchy = {}
    for row in parsed.get("rows") or []:
        wbs = str(row.get("wbs") or "").strip().rstrip(".")
        if wbs:
            hierarchy.setdefault(wbs, []).append(row)
    tasks = {}
    for row in parsed.get("works") or []:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        if not tid or tid in tasks:
            raise PhysicalProblem("В утверждённом ГПР нет уникальных идентификаторов работ.")
        wbs = str(row.get("wbs") or "").strip().rstrip(".")
        prefixes = [".".join(wbs.split(".")[:depth]) for depth in range(1, len(wbs.split(".")))]
        ambiguous = any(len(hierarchy.get(prefix) or []) > 1 for prefix in prefixes)
        parents = [hierarchy[prefix][0] for prefix in prefixes if len(hierarchy.get(prefix) or []) == 1]
        tasks[tid] = {"task_id": tid, "name": row.get("name") or tid,
                      "object": row.get("object") or "",
                      "wbs": wbs, "section": row.get("section") or "",
                      "estimate_code": row.get("estimate_code") or "",
                      "estimate_name": row.get("estimate_name") or "",
                      "parent_path": ([{"id": str(parent.get("id") or ""),
                                        "wbs": str(parent.get("wbs") or ""),
                                        "name": str(parent.get("name") or "")}
                                       for parent in parents] if not ambiguous else []),
                      "hierarchy_ambiguous": ambiguous,
                      "plan_start": monitor._iso(row.get("start")),
                      "plan_finish": monitor._iso(row.get("finish"))}
    return {"source_sha256": hashlib.sha256(data).hexdigest(), "tasks": tasks, "reason": "",
            "state": "approved_gpr"}


def _history(project):
    events = []
    folder = monitor._project_dir(project) / "gpr_physical_links"
    for revision, path in enumerate(sorted(folder.glob("[0-9]*.json")), 1):
        event = json.loads(path.read_text(encoding="utf-8"))
        if (type(event.get("revision")) is not int or event["revision"] != revision
                or path.stem != f"{revision:012d}" or event.get("source_kind") != SOURCE_KIND
                or not re.fullmatch(r"[0-9a-f]{64}", event.get("source_sha256") or "")
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{64}", event.get("snapshot_id") or "")
                or dt.datetime.fromisoformat(event["recorded_at"]).utcoffset() != dt.timedelta(0)):
            raise ValueError("invalid GPR quantity mapping history")
        quantities._validate(event["configuration"])
        events.append(event)
    return events


def _snapshot(project, cut):
    snapshot = ledgers.effective_snapshot(project, cut)
    if snapshot is not None:
        sid = snapshot.get("snapshot_id") or ""
        if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{64}", sid)
                or quantities._day(sid[:10]) is None or sid[:10] > cut
                or snapshot.get("taken_at", sid[:10]) != sid[:10]
                or snapshot.get("sha256", sid[11:]) != sid[11:]):
            raise PhysicalProblem("Не подтверждены дата или идентичность архива накопительных.")
    return snapshot


def _state(project, cut, source, snapshot):
    events = _history(project)
    sha, sid = source["source_sha256"], (snapshot or {}).get("snapshot_id") or ""
    matching = [event for event in events if event["source_sha256"] == sha and event["snapshot_id"] == sid
                and dt.datetime.fromisoformat(event["recorded_at"]).date().isoformat() <= cut]
    latest = matching[-1] if matching else None
    applicable = [event for event in events if event["recorded_at"][:10] <= cut]
    projected_from = None
    unresolved_projection = []
    configuration = latest["configuration"] if latest else {"tasks": [], "components": [], "note": ""}
    if not latest and sha and sid:
        prior = [event for event in events if event["source_sha256"] == sha
                 and event["snapshot_id"] != sid and event["snapshot_id"][:10] <= sid[:10]
                 and dt.datetime.fromisoformat(event["recorded_at"]).date().isoformat() <= cut]
        candidate = prior[-1] if prior else None
        # An explicit revoke is the most recent decision; do not revive an
        # older positive mapping. A different GPR revision cannot project.
        if candidate and candidate["configuration"]["tasks"]:
            try:
                previous = ledgers.effective_snapshot(project, cut,
                    snapshot=ledgers.read_snapshot(project, candidate["snapshot_id"]))
                projected = cumulative_progress.project_configuration(previous, snapshot, candidate["configuration"])
            except (OSError, ValueError, KeyError, TypeError):
                projected = None
            if projected is not None:
                configuration, latest, projected_from = projected, candidate, candidate["snapshot_id"]
                unresolved_projection = [task["task_id"] for task in configuration["tasks"]
                    if not task["scope_confirmed"] and any(original["task_id"] == task["task_id"]
                        and original["scope_confirmed"] for original in candidate["configuration"]["tasks"])]
    automatic = None
    if not applicable and source.get("state") == "approved_gpr" and snapshot:
        automatic = cumulative_matching.suggest(source, snapshot, cut)
        configuration = automatic["configuration"]
    return {"source_kind": SOURCE_KIND, "source_sha256": sha, "snapshot_id": sid,
            "revision": len(events), "recorded_at": latest["recorded_at"] if latest else None,
            "source_changed": bool(applicable and not latest),
            "binding_automatic": bool(automatic and (automatic["bindings"] or automatic["cohorts"])),
            "automatic_mapping": automatic,
            "binding_projected": projected_from is not None, "binding_source_snapshot_id": projected_from,
            "binding_projection_unresolved_tasks": unresolved_projection,
            "can_edit": bool(sha and sid and source["tasks"]) and cut == _now().date().isoformat(),
            "configuration": configuration}


def _observed_component(component, result, items, views, snapshot, cut, observation_index):
    """Retain known statement quantities when execution dates cannot give pace."""
    if result.get("progress") is not None or result.get('excluded_duplicate_item_ids'):
        return result
    selected = [items.get(key) for key in component["item_ids"]]
    observed = [views.get(key) for key in component["item_ids"]]
    day = cumulative_progress.snapshot_date(snapshot)
    if not day or day > cut or not selected or any(row is None for row in selected + observed):
        return result
    units = {quantities._unit(row.get("unit")) for row in selected}
    plans = [quantities._number(view.get("plan_quantity")) for view in observed]
    years = [row.get("period_year") for row in selected]
    if (len(units) != 1 or "" in units or any(p is None or p <= 0 for p in plans)
            or any(abs(p-plans[0]) > max(1e-6, plans[0]*1e-7) for p in plans)
            or len(set(years)) != len(years) or any(type(y) is not int or y <= 0 or y > int(day[:4]) for y in years)):
        return result
    if len(selected) > 1:
        # The protected canonical views retain customer and raw-date evidence;
        # _items is a minimal quantity dictionary and cannot qualify identity.
        identities = {cumulative_progress.contract_identity(view) for view in observed}
        if len(identities) != 1 or not all(next(iter(identities))):
            return result
    values = []
    for view in observed:
        if view.get("future_periods_excluded") is not False:
            return result
        value = quantities._number(view.get("completed_quantity"))
        if value is None:
            value = quantities._number(view.get("reported_completed_quantity"))
        if value is None or value < 0:
            return result
        values.append(value)
    done, plan = math.fsum(values), plans[0]
    overrun = done > plan + max(1e-6, plan*1e-7)
    result = dict(result, unit=selected[0]["unit"], plan_quantity=plan,
                  completed_quantity=done, progress=done/plan,
                  progress_origin="cumulative_statement", progress_date_basis="snapshot",
                  progress_basis="По ведомости", observation_date=day, period_end=None,
                  reason="Объём известен по ведомости; даты выполнения КС-2 не указаны.")
    history = cumulative_progress.component_history(
        [view.get("position_key") for view in observed], observation_index, result, cut)
    result["observation_history"] = history
    result["reason"] = history["reason"]
    if overrun:
        return dict(result, requires_reconciliation=True, known=False, forecast_finish=None,
                    reason="По ведомости выполненный объём превышает полный план; требуется сверка.")
    if done >= plan - max(1e-6, plan*1e-7):
        return dict(result, reason="По ведомости объём выполнен; дата завершения не указана.")
    pace = history.get("rate_per_day")
    if history.get("forecast_eligible") and pace and pace > 0:
        remaining = (plan-done)/pace
        if math.isfinite(remaining) and remaining <= 36500:
            try:
                finish = (quantities._day(cut)+dt.timedelta(days=math.ceil(remaining-1e-10))).isoformat()
            except OverflowError:
                return result
            result.update(known=True, forecast_finish=finish, method="statement_observation_pace",
                          rate_per_day=pace, rate_window_start=history["rate_window_start"],
                          rate_window_end=history["rate_window_end"], pace_basis="snapshot_observations")
    return result


def evaluate(source, snapshot, configuration, cut, *, observation_index=()):
    """Own natural pace only; there are no network edges or inherited delays."""
    day = quantities._day(cut)
    if day is None:
        raise PhysicalProblem("Укажите существующую дату среза.")
    items = quantities._items(snapshot)
    views = cumulative_progress.quantity_views(snapshot, cut)
    configs = {row["task_id"]: row for row in configuration["tasks"]}
    components = [_observed_component(component, quantities._component(component, items, day),
                                     items, views, snapshot, cut, observation_index)
                  for component in configuration["components"]]
    observation_date = cumulative_progress.snapshot_date(snapshot)
    hierarchy = cumulative_progress.source_hierarchy(views)
    for component, binding in zip(components, configuration["components"]):
        selected = [views[key] for key in binding["item_ids"] if key in views]
        if not selected:
            continue
        latest = max(selected, key=lambda view: view.get("period_year") or 0)
        keys = [view.get("position_key") for view in selected]
        member_key = hashlib.sha256(json.dumps(sorted(str(key) for key in keys)
            if all(keys) else [snapshot.get("snapshot_id"), binding["item_ids"]], sort_keys=True).encode()).hexdigest()
        component["quantity_member"] = {"member_key": member_key, "item_keys": keys,
            "progress": component.get("progress"), "unit": component.get("unit") or latest.get("unit"),
            "is_group": any(view.get("is_group") is True for view in selected),
            "source_rows": [hierarchy[key] for key in binding["item_ids"] if key in hierarchy],
            **{field: latest.get(field) for field in
               ("planned_work_amount", "planned_cost_split", "planned_work_amount_basis", "valuation_key")}}
        if component.get("observation_history"):
            component["statement_history"] = component["observation_history"]
        elif component.get("progress") is not None and observation_date:
            component["statement_history"] = cumulative_progress.component_history(
                keys, observation_index, dict(component, observation_date=observation_date), cut)
    tasks, seeds, actual_finishes = [], {}, {}
    for tid, task in source["tasks"].items():
        config = configs.get(tid)
        own = [component for component in components if component["task_id"] == tid]
        result = {"task_id": tid, "name": task["name"], "mode": config["mode"] if config else "unknown",
                  "scope_confirmed": bool(config and config["scope_confirmed"]),
                  "components": own if config and config["scope_confirmed"] else [],
                  "known": False, "progress": None, "progress_date": None,
                  "forecast_finish": None, "reason": "Нет подтверждённой привязки накопительных к этой работе ГПР."}
        if config and config["scope_confirmed"]:
            if config["mode"] == "quantities":
                result["progress"] = own[0].get("progress") if len(own) == 1 else None
                observed = any(c.get("progress_origin") == "cumulative_statement" for c in own)
                result["progress_origin"] = "cumulative_statement" if observed else "cumulative_quantities"
                result["progress_date_basis"] = "snapshot" if observed else "execution_period"
                result["progress_basis"] = "По ведомости" if observed else "По датированным периодам"
                result["requires_reconciliation"] = any(c.get("requires_reconciliation") for c in own)
                result["progress_date"] = max((c.get("observation_date") or c.get("period_end") for c in own
                                                if c.get("observation_date") or c.get("period_end")), default=None)
                if len(own) == 1 and own[0].get("observation_history"):
                    result["observation_history"] = own[0]["observation_history"]
                if own and all(c["known"] for c in own):
                    result.update(known=True, forecast_finish=max(c["forecast_finish"] for c in own), reason="")
                    if all(c.get("method") == "completed_quantities" for c in own):
                        result["actual_finish"] = result["forecast_finish"]
                else:
                    result["reason"] = next((c["reason"] for c in own if c.get("reason")),
                                            "Нет подтверждённых натуральных объёмов этой работы.")
                if len(own) > 1:
                    metric = cumulative_progress.aggregate_bound_quantities([c.get("quantity_member") or {} for c in own])
                    result["quantity_metric"] = metric
                    if metric["ratio"] is not None:
                        result.update(progress=metric["ratio"], progress_origin="cumulative_statement",
                                      progress_date_basis="snapshot", progress_date=observation_date,
                                      progress_basis=metric["label"], observation_history=cumulative_progress.weighted_history(
                                          own, observation_index, metric, observation_date))
                    elif any(c.get("progress") is not None for c in own):
                        result["reason"] = metric["reason"]
                    if metric.get("requires_reconciliation"):
                        result.update(known=False, forecast_finish=None, requires_reconciliation=True,
                                      reason=metric.get("reason") or "В объёмах работ есть превышение плана; требуется сверка.")
                        result.pop("actual_finish", None)
            elif config["mode"] == "completed":
                finish = quantities._day(config["actual_finish"])
                if finish and finish <= day:
                    result.update(known=True, progress=1.0, progress_date=finish.isoformat(),
                                  forecast_finish=finish.isoformat(), actual_finish=finish.isoformat(), reason="")
                else:
                    result["reason"] = "Дата фактического завершения отсутствует или позже среза."
            else:
                result["reason"] = "Для работы выбрана плановая длительность; натуральные объёмы не заданы."
        elif config:
            result["reason"] = "Не подтверждены полный состав и участок работы."
        if result["known"] and result["forecast_finish"]:
            seeds[tid] = result["forecast_finish"]
        if result.get("actual_finish"):
            actual_finishes[tid] = result["actual_finish"]
        tasks.append(result)
    evidence = any(t["mode"] in {"quantities", "completed"} and (t["known"] or t["progress"] is not None
                   or any(c.get("progress") is not None for c in t.get("components") or []))
                   for t in tasks)
    reasons = [] if evidence else [source.get("reason") or "Нет подтверждённых привязок накопительных к работам ГПР."]
    return {"state": "partial" if evidence else "unknown", "basis": "gpr", "tasks": tasks,
            "seeds": seeds, "actual_finishes": actual_finishes, "physical_evidence": evidence,
            "reasons": reasons, "binding_state": "bound" if configuration["tasks"] else "unbound"}


def _view_model(project, cut, source, snapshot, configuration, *, automatic=None):
    views = cumulative_progress.quantity_views(snapshot, cut)
    keys = {views[key].get("position_key") for component in configuration["components"]
            for key in component["item_ids"] if key in views}
    observation_index = cumulative_progress.observation_index(project, cut, snapshot, keys)
    gpr_history = gpr_forecast.history(project, quantities._day(cut))
    model = gpr_forecast.qualify_quantities(
        evaluate(source, snapshot, configuration, cut, observation_index=observation_index),
        gpr_history, quantities._day(cut))
    if automatic is not None:
        cohorts = automatic.get("cohorts") or []
        cohort_tasks = {cohort["cohort_id"]: {"task_id": cohort["cohort_id"],
            "name": cohort.get("source_scope") or cohort.get("source_name") or "Общий объём по КС"} for cohort in cohorts}
        cohort_configuration = {"tasks": [{"task_id": cid, "mode": "quantities", "scope_confirmed": True,
            "actual_finish": ""} for cid in cohort_tasks],
            "components": [component for cohort in cohorts for component in cohort.get("source_components") or []],
            "note": "Общий источник на несколько работ; распределение по отдельным работам не задано."}
        cohort_keys = {views[key].get("position_key") for component in cohort_configuration["components"]
                       for key in component["item_ids"] if key in views}
        cohort_index = cumulative_progress.observation_index(project, cut, snapshot, cohort_keys)
        cohort_model = evaluate({"tasks": cohort_tasks}, snapshot, cohort_configuration, cut,
                                observation_index=cohort_index)
        by_id = {task["task_id"]: task for task in cohort_model["tasks"]}
        model["source_cohorts"] = [dict(cohort, model=by_id.get(cohort["cohort_id"])) for cohort in cohorts]
        model["mapping_candidates"] = automatic.get("candidates") or []
        model["mapping_coverage"] = automatic.get("coverage") or {}
        model["automatic_bindings"] = automatic.get("bindings") or {}
        model["cohort_evidence"] = any((cohort.get("model") or {}).get("progress") is not None
            or any(component.get("progress") is not None for component in
                   (cohort.get("model") or {}).get("components") or []) for cohort in model["source_cohorts"])
        if model["cohort_evidence"]:
            model.update(physical_evidence=True, state="partial", binding_state="shared_scope"
                         if not configuration["tasks"] else "bound_and_shared_scope")
            model["reasons"] = ["Объём КС относится к общей группе; отдельные проценты работ не выделены."]
        for task in model["tasks"]:
            tid = task["task_id"]
            related_cohorts = [cohort for cohort in cohorts if tid in cohort["task_ids"]]
            candidates = [candidate for candidate in model["mapping_candidates"] if tid in candidate["candidate_task_ids"]]
            task["mapping_state"] = ("automatic" if tid in model["automatic_bindings"] else "shared_scope"
                                     if related_cohorts else "candidate" if candidates else "unmatched")
            task["source_cohort_ids"] = [cohort["cohort_id"] for cohort in related_cohorts]
            if task["mode"] == "unknown":
                task["reason"] = ("Выполнение известно общим объёмом группы; процент этой отдельной работы в КС не выделен."
                                  if related_cohorts else
                                  "Позиции КС найдены; участок, состав или база общего процента требуют уточнения."
                                  if candidates else "Автоматическое соответствие этой работы с позициями КС пока не определено.")
        for cohort in model["source_cohorts"]:
            measurement = cohort.get("model") or {}
            ratio = measurement.get("progress")
            readings = {tid: (gpr_history.get(tid) or [])[-1] for tid in cohort["task_ids"] if gpr_history.get(tid)}
            incomplete_components = [reading for reading in gpr_forecast.quantity_readings(measurement, quantities._day(cut))
                if (reading["progress"] < 1.0-1e-7 or reading.get("requires_reconciliation"))
                and gpr_forecast.reading_not_older(reading, [point[0] for point in readings.values()], quantities._day(cut))]
            if (not incomplete_components or len(readings) != len(cohort["task_ids"])
                    or any(reading[1] < gpr_forecast.DONE for reading in readings.values())):
                continue
            bases = {reading["date_basis"] for reading in incomplete_components}
            proof_basis = next(iter(bases)) if len(bases) == 1 else "mixed"
            proof_date = max(reading["date"] for reading in incomplete_components)
            reason = ("В ГПР все работы общей группы отмечены как завершённые. "
                      + ("В общей КС есть незавершённые позиции; общий процент не выделен. " if ratio is None else
                         "По ведомости от " + proof_date + " — " + f"{ratio*100:g}%. " if proof_basis == "snapshot" else
                         "В датированных периодах КС на " + proof_date + " есть незавершённые позиции. ")
                      + "Распределение по отдельным работам не задано; оценка окончания снята до сверки.")
            conflict = {"state": "source_conflict", "scope": "source_cohort", "cohort_id": cohort["cohort_id"],
                        "task_ids": list(cohort["task_ids"]), "progress": ratio, "date_basis": proof_basis,
                        "incomplete_components": incomplete_components,
                        "date": proof_date, "reason": reason,
                        "action": "Сверьте завершение работ и общий объём КС по этой группе."}
            cohort["source_conflict"] = conflict
            model.setdefault("cohort_source_conflicts", []).append(conflict)
            for task in model["tasks"]:
                if task["task_id"] not in readings:
                    continue
                reading = readings[task["task_id"]]
                qualified = dict(conflict, task_id=task["task_id"], name=task.get("name"), quantities=[],
                                 gpr={"date": reading[0].isoformat(), "progress": reading[1], "origin": reading[2]})
                task.update(source_conflict=qualified, known=False, forecast_finish=None,
                            requires_reconciliation=True, reason=reason)
                task.pop("actual_finish", None)
                model.get("seeds", {}).pop(task["task_id"], None)
                model.get("actual_finishes", {}).pop(task["task_id"], None)
                model.setdefault("source_conflicts", []).append(qualified)
            model.update(state="source_conflict", forecast_state="source_conflict")
            model["reasons"] = list(dict.fromkeys([*(model.get("reasons") or []), reason]))
        # Cohort seeds are intentionally absent from the individual GPR work
        # forecasts. One shared quantity cannot certify every leaf's finish.
    return model


def catalog(project, cut, query="", offset=0):
    if not quantities._day(cut):
        raise PhysicalProblem("Укажите существующую дату среза.")
    source, snapshot = _source(project, cut), _snapshot(project, cut)
    state = _state(project, cut, source, snapshot)
    query = query.casefold().strip()
    rows = [dict(item_id=key, **{field: item.get(field) for field in
            ("name", "scope", "unit", "plan_quantity", "completed_quantity", "period_year",
             "contract", "contract_date", "contractor", "source", "completion_ratio",
             "reported_completed_quantity", "reported_completion_ratio", "reported_material_quantity",
             "snapshot_date", "quantity_date", "quantity_basis", "future_periods_excluded", "position", "customer",
             "section_path", "object_scope", "system_scope", "is_group", "parent_row",
             "is_duplicate", "duplicate_of", "duplicate_note",
             "site_scope", "scope_evidence", "context_headings", "planned_cost_method",
             "contract_date_evidence", "source_date_key", "file_sha256", "ledger_source",
             "planned_work_amount", "planned_material_amount", "planned_cost_split",
             "planned_work_amount_basis", "valuation_key")})
            for key, item in cumulative_progress.quantity_views(snapshot, cut).items()
            if not query or query in " ".join(str(item.get(k) or "") for k in
                                               ("name", "scope", "contract", "contractor")).casefold()]
    return dict(state, source_state=source["state"], source_reason=source["reason"],
                tasks=list(source["tasks"].values()), items=rows[offset:offset+200],
                item_count=len(rows), offset=offset,
                model=_view_model(project, cut, source, snapshot, state["configuration"], automatic=state["automatic_mapping"]))


def save(project, source_kind, source_sha256, snapshot_id, revision, configuration):
    if source_kind != SOURCE_KIND:
        raise PhysicalProblem("Выберите работу утверждённого ГПР; привязки MS Project не применяются.")
    configuration = quantities._validate(configuration)
    folder = monitor._project_dir(project) / "gpr_physical_links"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    fd = os.open(folder / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cut = _now().date().isoformat()
        source, snapshot = _source(project, cut), _snapshot(project, cut)
        state = _state(project, cut, source, snapshot)
        if not state["can_edit"]:
            raise PhysicalProblem(source["reason"] or "Загрузите утверждённый ГПР и архив накопительных.")
        if (source_sha256 != state["source_sha256"] or snapshot_id != state["snapshot_id"]
                or type(revision) is not int or revision != state["revision"]):
            raise PhysicalProblem("Исходные данные или привязки изменились. Обновите страницу.", 409)
        items = quantities._items(snapshot)
        if any(t["task_id"] not in source["tasks"] for t in configuration["tasks"]):
            raise PhysicalProblem("В ГПР нет выбранной работы. Обновите данные.", 409)
        if any(i not in items for c in configuration["components"] for i in c["item_ids"]):
            raise PhysicalProblem("В архиве нет выбранной строки накопительной. Обновите данные.", 409)
        modes = {t["task_id"]: t["mode"] for t in configuration["tasks"]}
        if any(modes[c["task_id"]] != "quantities" for c in configuration["components"]):
            raise PhysicalProblem("Компоненты привязываются только к работам с натуральными объёмами.")
        if any(t["mode"] == "completed" and t["actual_finish"] > cut for t in configuration["tasks"]):
            raise PhysicalProblem("Дата завершения не может быть в будущем.")
        event = {"source_kind": SOURCE_KIND, "source_sha256": source_sha256, "snapshot_id": snapshot_id,
                 "revision": revision+1, "recorded_at": _now().isoformat(),
                 "actor": "administrator", "configuration": configuration}
        fd, temporary = tempfile.mkstemp(prefix=".event-", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(event, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / f"{revision+1:012d}.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
    return catalog(project, cut)


def build(project, cut):
    """Fail closed for corrupt/missing source evidence without exposing it."""
    try:
        source, snapshot = _source(project, cut), _snapshot(project, cut)
        state = _state(project, cut, source, snapshot)
        result = _view_model(project, cut, source, snapshot, state["configuration"], automatic=state["automatic_mapping"])
        return dict(result, evidence_status=evidence_status(project, cut, source, snapshot, state, result),
                    source_kind=SOURCE_KIND, source_sha256=state["source_sha256"],
                    snapshot_id=state["snapshot_id"], recorded_at=state["recorded_at"],
                    source_changed=state["source_changed"], source_state=source["state"],
                    binding_projected=state["binding_projected"],
                    binding_source_snapshot_id=state["binding_source_snapshot_id"],
                    binding_projection_unresolved_tasks=state["binding_projection_unresolved_tasks"],
                    binding_automatic=state["binding_automatic"],
                    source_reason=source["reason"])
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return {"state": "unknown", "basis": "gpr", "tasks": [], "seeds": {}, "actual_finishes": {},
                "physical_evidence": False, "binding_state": "unavailable",
                "evidence_status": {"state": "unavailable", "archive": "unknown", "mapping": "unavailable",
                                    "reason": "Сохранённые источники натуральных объёмов сейчас не читаются.",
                                    "action": "Команде: проверьте сохранённые источники в Мониторе."},
                "reasons": ["Привязки ГПР и накопительных сейчас не читаются. Перечитайте исходные данные."]}


def evidence_status(project, cut, source, snapshot, state, model):
    """Explain actual source availability; absence of a forecast is not absence of work.

    This status never authorizes a binding or changes quantity/pace calculations.
    The caller supplies the same validated snapshot and dated configuration used
    by evaluate(). Counts describe rows, not an aggregate physical percentage.
    """
    items = quantities._items(snapshot)
    quantity_views = cumulative_progress.quantity_views(snapshot, cut)
    reported = sum(view.get("future_periods_excluded") is False
                   and view.get("reported_completed_quantity") is not None for view in quantity_views.values())
    dated = sum(any(quantities._day(p.get("date_start")) and quantities._day(p.get("date_end"))
                    and p["date_start"] <= p["date_end"] <= cut
                    and quantities._number(p.get("quantity")) is not None
                    and quantities._number(p.get("quantity")) >= 0
                    for p in row.get("periods") or []) for row in items.values())
    tasks = model.get("tasks") or []
    measured = [t for t in tasks if t.get("progress") is not None or t.get("actual_finish")
                or any(c.get("progress") is not None for c in t.get("components") or [])]
    configs = state["configuration"]["tasks"]
    events = _history(project)
    dated_events = [event for event in events if event["recorded_at"][:10] <= cut]
    # _state already selected the last applicable event at this cut, including
    # an explicit revoke. A later edit must not override that dated selection.
    later_binding = not state.get("recorded_at") and not state.get("binding_automatic") and any(
        e["source_sha256"] == source["source_sha256"]
        and e["snapshot_id"] == state["snapshot_id"]
        and e["recorded_at"][:10] > cut for e in events)
    source_changed = bool(dated_events and not state.get("recorded_at"))
    status = {"archive": "available" if snapshot else "missing", "dated_rows": dated,
              "reported_rows": reported, "snapshot_date": cumulative_progress.snapshot_date(snapshot),
              "source_cohorts": len(model.get("source_cohorts") or []),
              "measured_tasks": len(measured), "mapping": "confirmed" if measured else "unbound"}

    def finish(code, reason, action, mapping=None):
        return dict(status, state=code, reason=reason, action=action,
                    mapping=mapping or status["mapping"])

    if not snapshot:
        later = any(str(s.get("taken_at") or "") > cut for s in ledgers.list_snapshots(project))
        if later:
            status["archive"] = "after_cut"
            return finish("historical", "Архив накопительных загружен после даты сводки.",
                          "Команде: откройте сводку на дату архива или позже.", "after_cut")
        # A manual confirmed finish can exist without an archive.
        if not measured:
            return finish("no_archive", "Архив накопительных не загружен.",
                          "Команде: добавьте архив в разделе «Данные и настройки» Монитора.")
    if later_binding:
        return finish("historical", "Соответствия работ подтверждены после даты сводки.",
                      "Команде: откройте сводку на дату подтверждения или позже.", "after_cut")
    if source.get("state") != "approved_gpr":
        return finish("gpr_unapproved", "Для накопительных ещё не подтверждён состав работ ГПР.",
                      "Команде: подтвердите состав работ и соответствия в Мониторе.")
    if source_changed:
        return finish("source_changed", "Исходные файлы изменились; прежние соответствия не применяются.",
                      "Команде: проверьте и подтвердите соответствия заново.", "source_changed")
    if model.get("source_conflicts"):
        conflict = model["source_conflicts"][0]
        prefix = "По общей группе: " if conflict.get("scope") == "source_cohort" else (
            "По работе «" + str(conflict.get("name") or conflict["task_id"]) + "»: ")
        return finish("source_conflict", prefix + conflict["reason"], "Команде: " + conflict["action"], "confirmed")
    if snapshot and not dated and not measured and not reported:
        return finish("no_dated_quantities", "Архив загружен, но датированные натуральные объёмы на эту дату не найдены.",
                      "Команде: проверьте даты периодов и натуральные объёмы в накопительных.")
    if not configs and model.get("source_cohorts") and not model.get("source_conflicts"):
        return finish("shared_scope", "Общий объём КС сопоставлен с группами работ; проценты отдельных работ не выделены.",
                      "Команде: сравнивайте общий объём группы; для отдельных процентов нужен отдельный состав работ.", "cohort")
    if not configs and not model.get("source_conflicts"):
        return finish("unmapped", "Накопительные загружены; позиции ещё не сопоставлены с работами ГПР.",
                      "Команде: сопоставьте позиции и подтвердите полный объём работ в Мониторе.")
    if not measured and any(not t["scope_confirmed"] for t in configs):
        return finish("unconfirmed", "Соответствия выбраны, но полный состав работ ещё не подтверждён.",
                      "Команде: проверьте и подтвердите полный состав работ в Мониторе.", "unconfirmed")
    if not measured:
        return finish("quantities_need_review", "Соответствия сохранены, но натуральный факт по ним пока не определён.",
                      "Команде: проверьте объёмы, единицы и даты выбранных позиций.", "confirmed")
    if any(not t.get("known") for t in measured):
        if any(t.get("progress_origin") == "cumulative_statement" for t in measured):
            return finish("statement_observations", "Объём и процент известны по ведомости; для прогноза нужен сопоставимый темп.",
                          "Команде: сравните сопоставимые снимки накопительных.")
        return finish("pace_unknown", "Объём выполненных работ известен; текущего темпа для оценки окончания нет.",
                      "Команде: проверьте последние закрытые периоды и обновите оценку оставшихся работ.")
    if any(t.get("mode") == "unknown" or not t.get("scope_confirmed") for t in tasks):
        return finish("partial_mapping", "Натуральный факт подтверждён только по части работ.",
                      "Команде: проверьте соответствия по остальным работам ГПР.", "partial")
    return finish("confirmed", "Натуральный факт подтверждён по выбранным работам.", "")
