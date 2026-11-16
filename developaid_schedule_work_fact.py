"""One owner of a work's readiness facts for the GPR chart and the summary.

Two sources are shown side by side (owner's decision):

* the GPR file — approved GPR, the weekly GPR file over it, a manual decision in
  Monitor over both (``manager._baseline_status``); origin and date are kept;
* cumulative KS-6a — natural quantities bound explicitly to this work
  (``developaid_schedule_physical``); the canonical quantity model supplies a
  single-component fraction or an explicit SMR-weighted aggregate. Shared
  source cohorts stay separate from the individual work's percentage.

A work is marked as divergent when both percents are known and differ by at
least ``DIVERGENCE_PP`` percentage points. Nothing here infers a mapping, a
percent or a date; a missing value carries its reason.
"""
from __future__ import annotations

from typing import Any
import math

DIVERGENCE_PP = 0.10

GPR_ORIGINS = {
    "approved_gpr": "утверждённый ГПР",
    "weekly_gpr": "еженедельный файл ГПР",
    "manual": "решение в Мониторе",
}


def primary_fact(row: dict) -> dict:
    """The dated fact used by the work bar, readiness and reports; never money."""
    kind = row.get('progress_kind')
    value = row.get('actual_progress')
    source = row.get('progress_source') or {}
    if kind not in {'gpr_percent', 'cumulative_quantities', 'cumulative_statement', 'confirmed_completion'}:
        value = None
    if value is None and row.get('gpr_progress') is not None:
        value, kind = row['gpr_progress'], 'gpr_percent'
        source = {'label': 'ГПР', 'date': row.get('gpr_progress_date')}
    if kind not in {'gpr_percent', 'cumulative_quantities', 'cumulative_statement', 'confirmed_completion'}:
        value = None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        value = None
    return {'value': value, 'basis': kind,
            'label': {'cumulative_statement': 'По ведомости', 'cumulative_quantities': 'Объём по накопительной',
                      'confirmed_completion': 'Выполнение подтверждено'}.get(kind, 'Выполнено по ГПР'),
            'source': source.get('label') or '', 'date': source.get('date'),
            'reason': row.get('progress_reason') or '',
            'requires_reconciliation': row.get('requires_reconciliation') is True or bool(row.get('source_conflict'))}


def _ks(task: dict | None) -> dict[str, Any]:
    if not task or task.get("mode") in (None, "unknown"):
        return {"progress": None, "date": None, "origin": None,
                "reason": (task or {}).get("reason") or "Работа не сопоставлена с накопительными."}
    if task.get("mode") == "plan_duration":
        return {"progress": None, "date": None, "origin": None,
                "reason": "Для этой работы выбрана плановая длительность: натуральных объёмов нет."}
    components = [{"component_id": c.get("component_id"), "progress": c.get("progress"),
                   "unit": c.get("unit"), "date": c.get("observation_date") or c.get("period_end"),
                   "date_basis": c.get("progress_date_basis"), "origin": c.get("progress_origin"),
                   "reason": c.get("reason") or "", "observation_history": c.get("observation_history")}
                  for c in task.get("components") or []]
    if task.get("mode") == "completed":
        if task.get("known"):
            return {"progress": 1.0, "date": task.get("actual_finish") or task.get("forecast_finish"),
                    "origin": "confirmed_completion", "components": components, "reason": ""}
        return {"progress": None, "date": None, "origin": None, "components": components,
                "reason": task.get("reason") or "Факт завершения не подтверждён."}
    if task.get("progress") is not None:
        dates = [c["date"] for c in components if c.get("date")]
        return {"progress": float(task["progress"]), "date": max(dates) if dates else None,
                "origin": task.get("progress_origin") or "cumulative_quantities", "components": components,
                "date_basis": task.get("progress_date_basis"), "label": task.get("progress_basis"),
                "requires_reconciliation": task.get("requires_reconciliation") is True,
                "observation_history": task.get("observation_history"), "reason": ""}
    if components and all(c.get("progress") is not None for c in components):
        reason = task.get("reason") or "Несколько компонентов разных объёмов: общий процент работы не выводится, доли — по компонентам."
    else:
        reason = task.get("reason") or "Натуральный объём по накопительным не подтверждён."
    return {"progress": None, "date": None, "origin": None, "components": components, "reason": reason}


def model(rows: list[dict], physical: dict | None) -> dict[str, Any]:
    """Per-work facts keyed by the GPR work id, plus counters."""
    tasks = {str(t.get("task_id")): t for t in (physical or {}).get("tasks") or []}
    works, divergent, bound = {}, 0, 0
    for row in rows or []:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        if not tid:
            continue
        gpr_progress = row.get("gpr_progress")
        origin = row.get("gpr_progress_origin")
        gpr = {"progress": gpr_progress, "origin": origin,
               "label": GPR_ORIGINS.get(origin or "", "файл ГПР"),
               "date": row.get("gpr_progress_date"),
               "reason": "" if gpr_progress is not None else
                         row.get("gpr_progress_reason") or "В файле ГПР процент не указан."}
        ks = _ks(tasks.get(tid))
        related = [cohort for cohort in (physical or {}).get("source_cohorts") or []
                   if tid in cohort.get("task_ids", [])]
        if related:
            ks["shared_scope"] = [{"cohort_id": cohort["cohort_id"],
                "name": cohort.get("source_scope") or cohort.get("source_name"),
                "progress": (cohort.get("model") or {}).get("progress"),
                "date": (cohort.get("model") or {}).get("progress_date"), "date_basis": "snapshot",
                "basis": (cohort.get("model") or {}).get("progress_basis"),
                "task_ids": cohort.get("task_ids") or [],
                "observation_history": (cohort.get("model") or {}).get("observation_history"),
                "source_conflict": cohort.get("source_conflict"),
                "reason": "Общий объём группы; доля этой отдельной работы не выделена."} for cohort in related]
        gap = (abs(ks["progress"] - gpr_progress)
               if ks["progress"] is not None and gpr_progress is not None else None)
        flag = gap is not None and gap >= DIVERGENCE_PP - 1e-9
        bound += ks["origin"] is not None
        divergent += flag
        works[tid] = {"gpr": gpr, "ks": ks, "gap": gap, "divergent": flag,
                      "primary": primary_fact(row),
                      "name": row.get('name') or tid, "object": row.get('object') or '',
                      "section": row.get('section') or '', "wbs": row.get('wbs') or '',
                      "source_conflict": (tasks.get(tid) or {}).get("source_conflict")}
    return {"works": works, "divergence_pp": DIVERGENCE_PP,
            "completed_facts": (physical or {}).get("completed_facts"),
            "covered_source_groups": (physical or {}).get("covered_source_groups") or [],
            "covered_source_coverage": (physical or {}).get("covered_source_coverage") or {},
            "counts": {"works": len(works), "with_ks": bound, "divergent": divergent},
            "source_note": ("Два факта рядом: процент по файлу ГПР (утверждённый ГПР, еженедельный файл, "
                            "решения в Мониторе) и процент по натуральным объёмам накопительных для "
                            "сопоставленных работ. Расхождение — разница от 10 процентных пунктов.")}
