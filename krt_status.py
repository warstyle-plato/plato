"""Canonical KRT status, its last confirmed state, and model exclusion."""

from __future__ import annotations

from typing import Any


_KNOWN = {"planned", "running"}


def model_cohort(projects: list[dict[str, Any]], *, unique: bool = False) -> list[dict[str, Any]]:
    """Keep raw statuses; conflicting identities cannot authorize a model.

    A source may publish planned and running rows for the same slug. Neither
    row is evidence of a transition while both coexist in one snapshot.
    """
    kinds: dict[str, set[str]] = {}
    for project in projects:
        slug = str(project.get("slug") or "")
        kinds.setdefault(slug, set()).add(project_kind(project))
    out, seen = [], set()
    for project in projects:
        row = dict(project)
        slug = str(row.get("slug") or "")
        if slug and "running" in kinds[slug] and len(kinds[slug]) > 1:
            row["model_status_conflict"] = True
        if not unique or not slug or slug not in seen:
            out.append(row)
        seen.add(slug)
    return out


def status_kind(status: Any) -> str:
    word = str(status or "").strip().casefold()
    if not word:
        return "draft"
    if "планируем" in word:
        return "planned"
    if "реализац" in word:
        return "running"
    return "unparsed"


def project_kind(project: dict[str, Any]) -> str:
    # The city's nonempty value stays authoritative, even when unparsed.
    if str(project.get("status") or "").strip():
        return status_kind(project["status"])
    kind = str(project.get("status_kind") or "").strip().casefold()
    return kind if kind in {*_KNOWN, "draft", "unparsed"} else ("unparsed" if kind else "draft")


def running_kind(kind: Any) -> bool:
    return str(kind or "").strip().casefold() == "running"


def with_last_known_status(
    project: dict[str, Any], previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Unknown is not a transition; a recognized new status updates history."""
    out = dict(project)
    current = project_kind(out)
    if current in _KNOWN:
        out["status_kind"] = current
        out["last_known_status_kind"] = current
        return out
    previous = previous or {}
    previous_history = str(previous.get("last_known_status_kind") or "").strip().casefold()
    if previous_history in _KNOWN:
        prior_current = project_kind(previous)
        if prior_current in _KNOWN:
            previous_history = prior_current
    # Explicit source history supersedes an older model row. A persisted
    # history in that row supersedes a stale, derived status_kind hint.
    candidates = (
        out.get("last_known_status_kind"), previous_history,
        out.get("status_kind"), project_kind(previous),
    )
    for value in candidates:
        known = str(value or "").strip().casefold()
        if known in _KNOWN:
            out["last_known_status_kind"] = known
            break
    out["status_kind"] = current
    return out


def model_exclusion(project: dict[str, Any]) -> dict[str, Any] | None:
    """Only confirmed running, or its unconfirmed transition, blocks models."""
    project = with_last_known_status(project)
    current = project_kind(project)
    if project.get("model_status_conflict"):
        reason = ("В одном снимке источника для площадки указаны разные статусы, "
                  "включая «В реализации». Переход статуса не подтверждён; "
                  "модель и балл не пересчитываются до устранения противоречия.")
    elif running_kind(current):
        reason = ("Площадка в реализации: финансовая модель и инвестиционный балл "
                  "не пересчитываются. Сведения о рынке можно обновлять отдельно.")
    elif current not in _KNOWN and running_kind(project.get("last_known_status_kind")):
        reason = ("Новый статус площадки не распознан. Последний известный статус — "
                  "«В реализации»; прекращение реализации не подтверждено. "
                  "Модель и балл не пересчитываются; сведения о рынке можно обновлять отдельно.")
    else:
        return None
    return {"available": False, "model_excluded": True, "status_kind": current,
            "last_known_status_kind": "running", "reason": reason}
