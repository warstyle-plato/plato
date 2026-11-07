"""One owner of a work's readiness facts for the GPR chart and the summary.

Two sources are shown side by side (owner's decision):

* the GPR file — approved GPR, the weekly GPR file over it, a manual decision in
  Monitor over both (``manager._baseline_status``); origin and date are kept;
* cumulative KS-6a — natural quantities bound explicitly to this work
  (``developaid_schedule_physical``); a percent exists only for one component
  or a confirmed completion. Different units are never averaged.

A work is marked as divergent when both percents are known and differ by at
least ``DIVERGENCE_PP`` percentage points. Nothing here infers a mapping, a
percent or a date; a missing value carries its reason.
"""
from __future__ import annotations

from typing import Any

DIVERGENCE_PP = 0.10

GPR_ORIGINS = {
    "approved_gpr": "утверждённый ГПР",
    "weekly_gpr": "еженедельный файл ГПР",
    "manual": "решение в Мониторе",
}


def _ks(task: dict | None) -> dict[str, Any]:
    if not task or task.get("mode") in (None, "unknown"):
        return {"progress": None, "date": None, "origin": None,
                "reason": "Работа не сопоставлена с накопительными."}
    if task.get("mode") == "plan_duration":
        return {"progress": None, "date": None, "origin": None,
                "reason": "Для этой работы выбрана плановая длительность: натуральных объёмов нет."}
    components = [{"component_id": c.get("component_id"), "progress": c.get("progress"),
                   "unit": c.get("unit"), "date": c.get("period_end"), "reason": c.get("reason") or ""}
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
                "origin": "cumulative_quantities", "components": components, "reason": ""}
    if components and all(c.get("progress") is not None for c in components):
        reason = "Несколько компонентов разных объёмов: общий процент работы не выводится, доли — по компонентам."
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
               "reason": "" if gpr_progress is not None else "В файле ГПР процент не указан."}
        ks = _ks(tasks.get(tid))
        gap = (abs(ks["progress"] - gpr_progress)
               if ks["progress"] is not None and gpr_progress is not None else None)
        flag = gap is not None and gap >= DIVERGENCE_PP - 1e-9
        bound += ks["origin"] is not None
        divergent += flag
        works[tid] = {"gpr": gpr, "ks": ks, "gap": gap, "divergent": flag}
    return {"works": works, "divergence_pp": DIVERGENCE_PP,
            "counts": {"works": len(works), "with_ks": bound, "divergent": divergent},
            "source_note": ("Два факта рядом: процент по файлу ГПР (утверждённый ГПР, еженедельный файл, "
                            "решения в Мониторе) и процент по натуральным объёмам накопительных для "
                            "сопоставленных работ. Расхождение — разница от 10 процентных пунктов.")}
