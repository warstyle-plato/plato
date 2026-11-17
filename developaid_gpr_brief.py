"""Short manager view of the GPR block for the test page «ГПР — новый вид».

The brief arranges the result of ``developaid_monitor_pace.schedule_view``; it
does not calculate readiness, stage membership or a finish estimate of its own.
Stage membership is the readiness matrix (its cell ``work_ids``), corpus
readiness is ``readiness.corpora``, the plan date is the dashboard tile and the
fact of each work is its ``display_progress`` — the same readers as the
Monitor. The expected finish stays a placeholder until the single project
estimate lands (owner, 17.11.2026, test page «А»): a seventh estimate here
would be one more date to disagree with.

The only rule declared here is «behind plan on the cut date»: the planned share
of the work by the cut exceeds its dated fact by ``LAG_PP`` points or more. It
compares two observed numbers and is not a forecast. An absent fact is «нет
показания», never zero.
"""
from __future__ import annotations

from typing import Any

LAG_PP = 10
ATTENTION_LIMIT = 5
EXPECTED_PENDING = ("Ожидаемая дата окончания появится здесь, когда будет подключена "
                    "единая оценка срока. Пока её можно посмотреть в текущем Мониторе.")
LAG_RULE = (f"Работа отстаёт, если к дате среза по плану должно быть выполнено на {LAG_PP} "
            "процентных пунктов больше, чем показывает последнее датированное выполнение. "
            "Работа без показания выполнения не считается ни отстающей, ни выполненной.")


def _share(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def work(row: dict) -> dict[str, Any]:
    """One work as the page shows it: plan share, dated fact and the lag rule."""
    shown = row.get("display_progress") or {}
    fact, plan = _share(shown.get("value")), _share(row.get("plan_progress"))
    done = row.get("work_done") is True or (fact is not None and fact >= 1 - 1e-9)
    gap = round((plan - fact) * 100, 1) if plan is not None and fact is not None else None
    if done:
        state = "done"
    elif fact is None:
        state = "no_reading"
    elif gap is not None and gap >= LAG_PP - 1e-9:
        state = "behind"
    else:
        state = "on_plan" if plan is not None else "no_plan"
    return {"id": str(row.get("id") or ""), "name": row.get("name") or "Работа без названия",
            "object": row.get("object") or "Общие работы",
            "plan_start": row.get("plan_start") or None, "plan_finish": row.get("plan_finish") or None,
            "plan": plan, "fact": fact, "fact_date": shown.get("date") or None,
            "fact_label": shown.get("label") or "", "gap_pp": gap if state == "behind" else None,
            "state": state}


def _count(works: list[dict]) -> dict[str, int]:
    out = {"total": len(works), "done": 0, "behind": 0, "no_reading": 0}
    for item in works:
        if item["state"] in out:
            out[item["state"]] += 1
    return out


def _notes(view: dict, readiness: dict) -> list[str]:
    tile = ((view.get("dashboard") or {}).get("schedule") or {}).get("qualified_rnv") or {}
    raw = [(view.get("schedule") or {}).get("reason"), readiness.get("reason"), (readiness.get("project") or {}).get("reason"), *(tile.get("reasons") or [])]
    out: list[str] = []
    for text in raw:
        text = " ".join(str(text or "").split())
        if text and text not in out:
            out.append(text)
    return out


def build(view: dict) -> dict[str, Any]:
    schedule = view.get("schedule") or {}
    readiness = schedule.get("readiness") or {}
    rows = {str(r.get("id")): r for r in [*(schedule.get("rows") or []), *(schedule.get("undated_works") or [])]
            if r.get("id") is not None}
    objects = list(readiness.get("matrix_objects") or [])
    stages, works_by_object, seen = [], {}, set()
    for stage in readiness.get("matrix") or []:
        cells, members = [], []
        for name, cell in zip(objects, stage.get("cells") or []):
            items = [work(rows[i]) for i in cell.get("work_ids") or [] if i in rows]
            seen.update(item["id"] for item in items)
            works_by_object.setdefault(name, []).extend(items)
            members.extend(items)
            cells.append({"object": name, "progress": _share(cell.get("progress")), **_count(items)})
        # One line per work name: the same work in several corpora is one row.
        grouped: dict[str, dict] = {}
        for item in members:
            line = grouped.setdefault(item["name"], {"name": item["name"], "by_object": {}})
            line["by_object"].setdefault(item["object"], []).append(item)
        lines = [dict(line, behind=any(x["state"] == "behind" for v in line["by_object"].values() for x in v))
                 for line in grouped.values()]
        stages.append({"stage": stage.get("stage") or "Без раздела", "cells": cells, "lines": lines,
                       **_count(members)})
    behind = [item for items in works_by_object.values() for item in items if item["state"] == "behind"]
    attention: dict[str, dict] = {}
    for item in behind:
        entry = attention.setdefault(item["name"], {"name": item["name"], "works": []})
        entry["works"].append(item)
    ranked = sorted(attention.values(), key=lambda e: (-max(x["gap_pp"] for x in e["works"]), e["name"]))
    corpora = []
    for corpus in readiness.get("corpora") or []:
        name = corpus.get("name") or "Общие работы"
        corpora.append({"name": name, "progress": _share(corpus.get("progress")),
                        "plan_finish": (corpus.get("forecast") or {}).get("plan_finish"),
                        **_count(works_by_object.get(name, []))})
    project = readiness.get("project") or {}
    tile = ((view.get("dashboard") or {}).get("schedule") or {}).get("qualified_rnv") or {}
    dates = sorted({item["fact_date"] for items in works_by_object.values() for item in items if item["fact_date"]})
    return {
        "cut": view.get("cut") or schedule.get("cut"),
        # No works at all: the page says why instead of showing empty tiles.
        "empty": not rows,
        "empty_reason": schedule.get("reason") or "",
        "plan_finish": {"date": tile.get("plan_date") or schedule.get("baseline_end"),
                        "label": tile.get("plan_label") or "План окончания работ"},
        "expected_finish": {"state": "pending", "text": EXPECTED_PENDING},
        "progress": {"value": _share(project.get("progress")), "estimated": bool(readiness.get("estimated")),
                     "reason": project.get("reason") or ""},
        "fact_dates": dates,
        "counts": _count([item for items in works_by_object.values() for item in items]),
        "corpora": corpora,
        "attention": {"items": ranked[:ATTENTION_LIMIT], "total": len(ranked)},
        "matrix": {"objects": objects, "stages": stages, "truncated": bool(readiness.get("matrix_truncated"))},
        "outside_matrix": len(set(rows) - seen),
        "notes": _notes(view, readiness),
        "lag_rule": LAG_RULE,
    }
