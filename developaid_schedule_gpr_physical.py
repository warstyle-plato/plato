"""Explicit GPR-work ↔ natural cumulative quantities, without PM identities.

The binding is private, versioned and tied to the exact approved GPR bytes and
cumulative snapshot. No name, financial code or contract match creates a link.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_schedule_physical as quantities
import developaid_schedule_gpr_forecast as gpr_forecast

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
    tasks = {}
    for row in parsed.get("works") or []:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        if not tid or tid in tasks:
            raise PhysicalProblem("В утверждённом ГПР нет уникальных идентификаторов работ.")
        tasks[tid] = {"task_id": tid, "name": row.get("name") or tid,
                      "object": row.get("object") or "",
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
    snapshot = ledgers.latest_snapshot(project, cut)
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
    return {"source_kind": SOURCE_KIND, "source_sha256": sha, "snapshot_id": sid,
            "revision": len(events), "recorded_at": latest["recorded_at"] if latest else None,
            "source_changed": bool(events and not matching),
            "can_edit": bool(sha and sid and source["tasks"]) and cut == _now().date().isoformat(),
            "configuration": latest["configuration"] if latest else {"tasks": [], "components": [], "note": ""}}


def evaluate(source, snapshot, configuration, cut):
    """Own natural pace only; there are no network edges or inherited delays."""
    day = quantities._day(cut)
    if day is None:
        raise PhysicalProblem("Укажите существующую дату среза.")
    items = quantities._items(snapshot)
    configs = {row["task_id"]: row for row in configuration["tasks"]}
    components = [quantities._component(component, items, day) for component in configuration["components"]]
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
                result["progress_date"] = max((c["period_end"] for c in own if c.get("period_end")), default=None)
                if own and all(c["known"] for c in own):
                    result.update(known=True, forecast_finish=max(c["forecast_finish"] for c in own), reason="")
                    if all(c.get("method") == "completed_quantities" for c in own):
                        result["actual_finish"] = result["forecast_finish"]
                else:
                    result["reason"] = next((c["reason"] for c in own if c.get("reason")),
                                            "Нет подтверждённых натуральных объёмов этой работы.")
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
    evidence = any(t["mode"] in {"quantities", "completed"} and (t["known"] or t["progress"] is not None)
                   for t in tasks)
    reasons = [] if evidence else [source.get("reason") or "Нет подтверждённых привязок накопительных к работам ГПР."]
    return {"state": "partial" if evidence else "unknown", "basis": "gpr", "tasks": tasks,
            "seeds": seeds, "actual_finishes": actual_finishes, "physical_evidence": evidence,
            "reasons": reasons, "binding_state": "bound" if configuration["tasks"] else "unbound"}


def _view_model(project, cut, source, snapshot, configuration):
    return gpr_forecast.qualify_quantities(
        evaluate(source, snapshot, configuration, cut),
        gpr_forecast.history(project, quantities._day(cut)), quantities._day(cut))


def catalog(project, cut, query="", offset=0):
    if not quantities._day(cut):
        raise PhysicalProblem("Укажите существующую дату среза.")
    source, snapshot = _source(project, cut), _snapshot(project, cut)
    state = _state(project, cut, source, snapshot)
    query = query.casefold().strip()
    rows = [dict(item_id=key, **{field: item.get(field) for field in
            ("name", "scope", "unit", "plan_quantity", "completed_quantity", "period_year",
             "contract", "contract_date", "contractor", "source")})
            for key, item in quantities._items(snapshot).items()
            if not query or query in " ".join(str(item.get(k) or "") for k in
                                               ("name", "scope", "contract", "contractor")).casefold()]
    return dict(state, source_state=source["state"], source_reason=source["reason"],
                tasks=list(source["tasks"].values()), items=rows[offset:offset+200],
                item_count=len(rows), offset=offset,
                model=_view_model(project, cut, source, snapshot, state["configuration"]))


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
        result = _view_model(project, cut, source, snapshot, state["configuration"])
        return dict(result, evidence_status=evidence_status(project, cut, source, snapshot, state, result),
                    source_kind=SOURCE_KIND, source_sha256=state["source_sha256"],
                    snapshot_id=state["snapshot_id"], recorded_at=state["recorded_at"],
                    source_changed=state["source_changed"], source_state=source["state"],
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
    later_binding = not state.get("recorded_at") and any(
        e["source_sha256"] == source["source_sha256"]
        and e["snapshot_id"] == state["snapshot_id"]
        and e["recorded_at"][:10] > cut for e in events)
    source_changed = bool(dated_events and not state.get("recorded_at"))
    status = {"archive": "available" if snapshot else "missing", "dated_rows": dated,
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
    if snapshot and not dated and not measured:
        return finish("no_dated_quantities", "Архив загружен, но датированные натуральные объёмы на эту дату не найдены.",
                      "Команде: проверьте даты периодов и натуральные объёмы в накопительных.")
    if not configs:
        return finish("unmapped", "Накопительные загружены; позиции ещё не сопоставлены с работами ГПР.",
                      "Команде: сопоставьте позиции и подтвердите полный объём работ в Мониторе.")
    if not measured and any(not t["scope_confirmed"] for t in configs):
        return finish("unconfirmed", "Соответствия выбраны, но полный состав работ ещё не подтверждён.",
                      "Команде: проверьте и подтвердите полный состав работ в Мониторе.", "unconfirmed")
    if not measured:
        return finish("quantities_need_review", "Соответствия сохранены, но натуральный факт по ним пока не определён.",
                      "Команде: проверьте объёмы, единицы и даты выбранных позиций.", "confirmed")
    if model.get("source_conflicts"):
        conflict = model["source_conflicts"][0]
        return finish("source_conflict", ("По работе «" + str(conflict.get("name") or conflict["task_id"])
                      + "»: " + conflict["reason"]), "Команде: " + conflict["action"], "confirmed")
    if any(not t.get("known") for t in measured):
        return finish("pace_unknown", "Объём выполненных работ известен; текущего темпа для оценки окончания нет.",
                      "Команде: проверьте последние закрытые периоды и обновите оценку оставшихся работ.")
    if any(t.get("mode") == "unknown" or not t.get("scope_confirmed") for t in tasks):
        return finish("partial_mapping", "Натуральный факт подтверждён только по части работ.",
                      "Команде: проверьте соответствия по остальным работам ГПР.", "partial")
    return finish("confirmed", "Натуральный факт подтверждён по выбранным работам.", "")
