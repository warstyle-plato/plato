"""Spatial selector for cadastral OCS inside a KRT contour.

Discovery supplies candidate cadastral rows. This module verifies which rows
belong to the KRT outline and aggregates cadastral value without turning
missing geometry, ownership, or value into zero.
"""
from __future__ import annotations

import math
from typing import Any

MERCATOR_HALF = 20037508.342789244


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def mercator(lng: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = float(lng) * MERCATOR_HALF / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * MERCATOR_HALF / math.pi
    return x, y


def inside(rings: list[list[list[float]]], x: float, y: float) -> bool:
    hits = 0
    for ring in rings or []:
        if not isinstance(ring, list) or len(ring) < 3:
            continue
        for i, a in enumerate(ring):
            b = ring[(i + 1) % len(ring)]
            try:
                ax, ay = float(a[0]), float(a[1])
                bx, by = float(b[0]), float(b[1])
            except (TypeError, ValueError, IndexError):
                continue
            if (ay > y) == (by > y):
                continue
            if ax + (y - ay) * (bx - ax) / (by - ay) > x:
                hits += 1
    return hits % 2 == 1


def _ring_points(rings: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for ring in rings or []:
        if not isinstance(ring, list):
            continue
        for p in ring:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            x, y = _num(p[0]), _num(p[1])
            if x is not None and y is not None:
                out.append((x, y))
    return out


def _object_center_merc(row: dict[str, Any]) -> tuple[float, float] | None:
    center = row.get("center") or {}
    lat, lng = _num(center.get("lat")), _num(center.get("lng"))
    if lat is not None and lng is not None:
        return mercator(lng, lat)
    rings = row.get("rings_merc") or row.get("contour_merc") or []
    pts = _ring_points(rings)
    if pts:
        return (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )
    return None


def _sample_overlap(object_rings, krt_rings, grid: int = 12) -> float | None:
    pts = _ring_points(object_rings)
    if not pts or not krt_rings:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    if maxx <= minx or maxy <= miny:
        return None
    own = hit = 0
    for i in range(grid):
        x = minx + (maxx - minx) * (i + 0.5) / grid
        for j in range(grid):
            y = miny + (maxy - miny) * (j + 0.5) / grid
            if not inside(object_rings, x, y):
                continue
            own += 1
            if inside(krt_rings, x, y):
                hit += 1
    return None if own == 0 else hit / own


def _related_lands(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("lands", "site_cadastral_numbers", "related_lands"):
        raw = row.get(key) or []
        if isinstance(raw, str):
            raw = [raw]
        for item in raw:
            if isinstance(item, dict):
                item = item.get("cadastral_number")
            value = str(item or "").strip()
            if value and value not in values:
                values.append(value)
    relation = str(row.get("land_parcel") or "").strip()
    if relation and relation not in values:
        values.append(relation)
    return values


def classify(row: dict[str, Any], krt_rings, *, lands_inside: set[str] | None = None) -> dict[str, Any]:
    out = dict(row)
    number = str(row.get("cadastral_number") or "").strip()
    rings = row.get("rings_merc") or row.get("contour_merc") or []
    center = _object_center_merc(row)
    share = _sample_overlap(rings, krt_rings) if rings else None
    center_inside = bool(center and inside(krt_rings, center[0], center[1]))
    related = _related_lands(row)
    related_inside = sorted(set(related) & set(lands_inside or set()))

    if share is not None and share > 0:
        state, basis = "inside", "object_geometry_intersects_krt"
    elif center_inside:
        state, basis = "inside", "object_center_inside_krt"
    elif related_inside:
        state, basis = "inside", "related_land_inside_krt"
    elif share == 0 or (center is not None and not center_inside):
        state, basis = "outside", "object_geometry_outside_krt"
    else:
        state, basis = "unresolved", "no_geometry_or_verified_land_relation"

    out.update({
        "cadastral_number": number,
        "krt_state": state,
        "krt_basis": basis,
        "krt_overlap_share": None if share is None else round(share, 4),
        "related_lands_inside": related_inside,
    })
    return out


def select(*, krt_rings, lands=None, objects=None) -> dict[str, Any]:
    lands = list(lands or [])
    objects = list(objects or [])

    land_rows: list[dict[str, Any]] = []
    lands_inside: set[str] = set()
    for row in lands:
        checked = classify(row, krt_rings)
        land_rows.append(checked)
        if checked["krt_state"] == "inside" and checked.get("cadastral_number"):
            lands_inside.add(checked["cadastral_number"])

    dedup: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in objects:
        checked = classify(row, krt_rings, lands_inside=lands_inside)
        number = checked.get("cadastral_number")
        if not number:
            anonymous.append(checked)
            continue
        current = dedup.get(number)
        if current is None:
            dedup[number] = checked
            continue
        rank = {"unresolved": 0, "outside": 1, "inside": 2}
        if rank.get(checked["krt_state"], 0) > rank.get(current["krt_state"], 0):
            dedup[number] = checked

    object_rows = list(dedup.values()) + anonymous
    inside_rows = [r for r in object_rows if r["krt_state"] == "inside"]
    outside_rows = [r for r in object_rows if r["krt_state"] == "outside"]
    unresolved_rows = [r for r in object_rows if r["krt_state"] == "unresolved"]

    valued = [
        r for r in inside_rows
        if str(r.get("kind") or "").strip().lower() not in ("premise", "room", "помещение")
    ]
    private_rub = city_rub = other_public_rub = 0.0
    unknown_value: list[str] = []
    for row in valued:
        value = _num(row.get("cadastral_value_rub"))
        number = str(row.get("cadastral_number") or "")
        owner = row.get("owner") or {}
        group = str(owner.get("group") or row.get("owner_group") or "").strip().lower()
        if value is None:
            unknown_value.append(number)
            continue
        if group == "moscow":
            city_rub += value
        elif group in ("federal", "public", "other_public"):
            other_public_rub += value
        else:
            private_rub += value

    return {
        "lands": land_rows,
        "objects": object_rows,
        "inside": inside_rows,
        "outside": outside_rows,
        "unresolved": unresolved_rows,
        "counts": {
            "lands": len(land_rows),
            "objects": len(object_rows),
            "inside": len(inside_rows),
            "outside": len(outside_rows),
            "unresolved": len(unresolved_rows),
        },
        "cadastral": {
            "private_buyout_rub": round(private_rub, 2),
            "moscow_excluded_rub": round(city_rub, 2),
            "other_public_rub": round(other_public_rub, 2),
            "unknown_value_count": len(unknown_value),
            "unknown_value_numbers": unknown_value,
            "complete": not unknown_value and not unresolved_rows,
            "rule": "private/non-Moscow OCS=cadastral value; Moscow=0; other public separate; no premise/building double count",
        },
    }


def candidate_numbers(requirements: dict[str, Any], territory: dict[str, Any]) -> dict[str, list[str]]:
    lands: list[str] = []
    objects: list[str] = []

    def add(bucket: list[str], value: Any) -> None:
        value = str(value or "").strip()
        if value and value not in bucket:
            bucket.append(value)

    for row in territory.get("lands") or []:
        add(lands, (row or {}).get("cadastral_number"))
        for obj in (row or {}).get("objects") or []:
            add(objects, (obj or {}).get("cadastral_number") if isinstance(obj, dict) else obj)
    for row in territory.get("objects") or []:
        add(objects, (row or {}).get("cadastral_number"))

    for value in requirements.get("cadastral_numbers") or []:
        add(lands, value)
    for row in requirements.get("object_actions") or []:
        if isinstance(row, dict):
            add(objects, row.get("cadastral_number"))

    return {"lands": lands, "objects": objects}
