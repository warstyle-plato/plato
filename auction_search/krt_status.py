"""Canonical KRT catalogue status and the shared model exclusion."""

from __future__ import annotations

from typing import Any


def status_kind(status: Any) -> str:
    """Keep the city's status distinct from our decision-only draft rows."""
    word = str(status or "").strip().casefold()
    if not word:
        return "draft"
    if "планируем" in word:
        return "planned"
    if "реализац" in word:
        return "running"
    return "unparsed"


def project_kind(project: dict[str, Any]) -> str:
    # A nonempty city value is authoritative, including an unparsed value.
    # A cached/derived kind must not relabel it as a planned project.
    if str(project.get("status") or "").strip():
        return status_kind(project["status"])
    kind = str(project.get("status_kind") or "").strip().casefold()
    if kind:
        return kind if kind in {"planned", "running", "draft", "unparsed"} else "unparsed"
    return "draft"


def running_kind(kind: Any) -> bool:
    return str(kind or "").strip().casefold() == "running"


def model_exclusion(project: dict[str, Any]) -> dict[str, Any] | None:
    """A running project can refresh observations, never its model/score."""
    if not running_kind(project_kind(project)):
        return None
    return {
        "available": False,
        "model_excluded": True,
        "status_kind": "running",
        "reason": ("Площадка в реализации: финансовая модель и инвестиционный балл "
                   "не пересчитываются. Сведения о рынке можно обновлять отдельно."),
    }
