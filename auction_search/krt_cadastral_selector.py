"""Spatial selector for cadastral OCS inside a KRT contour.

Discovery supplies candidate cadastral rows. This module verifies which rows
belong to the KRT outline and aggregates cadastral value without turning
missing geometry, ownership, or value into zero.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
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

    inside_lands = [r for r in land_rows if r["krt_state"] == "inside"]
    valued_objects = [
        r for r in inside_rows
        if str(r.get("kind") or "").strip().lower() not in ("premise", "room", "помещение")
    ]
    # Земля и ОКС входят в кадастровый выкуп раздельно. КН дедуплицируется
    # глобально: один объект не должен попасть в сумму дважды из разных источников.
    valued_by_cn: dict[str, dict[str, Any]] = {}
    anonymous_valued: list[dict[str, Any]] = []
    for row in [*inside_lands, *valued_objects]:
        number = str(row.get("cadastral_number") or "").strip()
        if number:
            valued_by_cn.setdefault(number, row)
        else:
            anonymous_valued.append(row)
    valued = list(valued_by_cn.values()) + anonymous_valued

    private_rub = city_rub = other_public_rub = gross_known_rub = 0.0
    private_land_rub = private_ocs_rub = 0.0
    unknown_value: list[str] = []
    unknown_owner: list[str] = []
    for row in valued:
        value = _num(row.get("cadastral_value_rub"))
        number = str(row.get("cadastral_number") or "")
        owner = row.get("owner") or {}
        group = str(owner.get("group") or row.get("owner_group") or "").strip().lower()
        owner_name = str(owner.get("name") or row.get("owner_name") or "").strip()
        owner_state = str(owner.get("state") or row.get("owner_state") or "").strip().lower()
        if value is None:
            unknown_value.append(number)
            continue
        gross_known_rub += value
        if group == "moscow":
            city_rub += value
        elif group in ("federal", "public", "other_public"):
            other_public_rub += value
        elif owner_name or group in ("private", "other", "non_moscow", "bryntsalov"):
            private_rub += value
            kind = str(row.get("kind") or "").strip().lower()
            if kind == "land" or row in inside_lands:
                private_land_rub += value
            else:
                private_ocs_rub += value
        else:
            # Пустой собственник и «имя не раскрыто» — не частная собственность
            # по умолчанию. Методика требует unknown, а не превращение пробела в выкуп.
            unknown_owner.append(number)


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
            "gross_known_rub": round(gross_known_rub, 2),
            "private_land_rub": round(private_land_rub, 2),
            "private_ocs_rub": round(private_ocs_rub, 2),
            "unknown_value_count": len(unknown_value),
            "unknown_value_numbers": unknown_value,
            "unknown_owner_count": len(unknown_owner),
            "unknown_owner_numbers": unknown_owner,
            "complete": not unknown_value and not unknown_owner and not unresolved_rows,
            "rule": "private/non-Moscow land+OCS=cadastral value; Moscow=0; other public separate; unknown owner/value stays unknown; no premise/building double count",
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


# Spatial discovery cache.  A catalogue page must never wait for dozens of
# NSPD requests; it reads the last snapshot and starts a background refresh.
_SPATIAL_LOCK = threading.Lock()
_SPATIAL_READING: set[str] = set()
SPATIAL_TTL_SECONDS = 7 * 24 * 3600
NSPD_LAND_LAYERS = ("Земельные участки из ЕГРН",)
NSPD_OCS_LAYERS = (
    "Здания",
    "Сооружения",
    "Объекты незавершенного строительства",
    "Единые недвижимые комплексы",
)


def inverse_mercator(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 -> (lon, lat) EPSG:4326."""
    lon = float(x) * 180.0 / MERCATOR_HALF
    lat = (180.0 / math.pi) * (
        2.0 * math.atan(math.exp(float(y) * math.pi / MERCATOR_HALF)) - math.pi / 2.0
    )
    return lon, lat


def _contour_shape(krt_rings):
    """Build one shapely geometry from KRT mercator rings."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    polygons = []
    for ring in krt_rings or []:
        if not isinstance(ring, list) or len(ring) < 3:
            continue
        coords = []
        for point in ring:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            x, y = _num(point[0]), _num(point[1])
            if x is None or y is None:
                continue
            coords.append(inverse_mercator(x, y))
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        try:
            poly = Polygon(coords)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if not poly.is_empty:
                polygons.append(poly)
        except Exception:
            continue
    if not polygons:
        raise ValueError("контур КРТ не содержит валидных колец")
    return unary_union(polygons)


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            got = dump()
            return dict(got) if isinstance(got, dict) else {}
        except Exception:
            return {}
    return {}


def _geojson_rings_merc(geometry: Any) -> list[list[list[float]]]:
    raw = _model_dump(geometry)
    if not raw and isinstance(geometry, dict):
        raw = geometry
    kind = str(raw.get("type") or "")
    coords = raw.get("coordinates") or []
    rings: list[list[list[float]]] = []

    def add_ring(ring) -> None:
        converted = []
        for point in ring or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            lng, lat = _num(point[0]), _num(point[1])
            if lng is None or lat is None:
                continue
            x, y = mercator(lng, lat)
            converted.append([x, y])
        if len(converted) >= 3:
            rings.append(converted)

    if kind == "Polygon":
        for ring in coords:
            add_ring(ring)
    elif kind == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                add_ring(ring)
    return rings


def _feature_row(feature: Any, *, kind: str, layer: str) -> dict[str, Any]:
    props = getattr(feature, "properties", None)
    options = getattr(props, "options", None)
    opt = _model_dump(options)
    if not opt:
        opt = _model_dump(props).get("options") or {}
    cad = str(
        opt.get("cad_num")
        or opt.get("cadastral_number")
        or opt.get("cn")
        or ""
    ).strip()
    value = (
        opt.get("cost_value")
        if opt.get("cost_value") is not None
        else opt.get("cadastral_cost")
    )
    area = (
        opt.get("specified_area")
        if opt.get("specified_area") is not None
        else opt.get("declared_area")
    )
    if area is None:
        area = opt.get("area")
    address = str(
        opt.get("readable_address")
        or opt.get("address")
        or opt.get("object_address")
        or ""
    ).strip()
    return {
        "cadastral_number": cad,
        "kind": kind,
        "layer": layer,
        "address": address,
        "area_sqm": _num(area),
        "cadastral_value_rub": _num(value),
        "owner": {},
        "rings_merc": _geojson_rings_merc(getattr(feature, "geometry", None)),
        "source": "НСПД · пространственный поиск по контуру КРТ",
    }


def discover_nspd(*, krt_rings, max_features: int = 2500) -> dict[str, Any]:
    """Enumerate cadastral land and OCS intersecting a KRT contour.

    The search is independent from the KRT decision/auction object list, so it
    works as a completeness control.  Ownership is intentionally not invented:
    NSPD exposes cadastre/geometry, while owner classification is merged later
    from EGRN records when available.
    """
    try:
        from pynspd import Nspd, NspdFeature
    except Exception as exc:
        return {
            "available": False,
            "complete": False,
            "problem": f"pynspd недоступен: {type(exc).__name__}: {exc}",
            "lands": [],
            "objects": [],
            "layers": {},
        }

    try:
        contour = _contour_shape(krt_rings)
    except Exception as exc:
        return {
            "available": False,
            "complete": False,
            "problem": f"контур КРТ не собран: {type(exc).__name__}: {exc}",
            "lands": [],
            "objects": [],
            "layers": {},
        }

    lands: dict[str, dict[str, Any]] = {}
    objects: dict[str, dict[str, Any]] = {}
    layers: dict[str, dict[str, Any]] = {}
    truncated = False

    try:
        client = Nspd(client_timeout=25, client_retries=2)
    except TypeError:
        client = Nspd()
    try:
        for title, kind, bucket in [
            *[(title, "land", lands) for title in NSPD_LAND_LAYERS],
            *[(title, "building", objects) for title in NSPD_OCS_LAYERS],
        ]:
            count = 0
            problem = ""
            try:
                layer_def = NspdFeature.by_title(title)
                iterator = client.search_in_contour_iter(
                    contour, layer_def, only_intersects=True
                )
                for feature in iterator:
                    row = _feature_row(feature, kind=kind, layer=title)
                    number = row.get("cadastral_number")
                    if not number:
                        continue
                    bucket.setdefault(number, row)
                    count += 1
                    if len(lands) + len(objects) >= max_features:
                        truncated = True
                        break
            except Exception as exc:
                problem = f"{type(exc).__name__}: {exc}"[:300]
            layers[title] = {"count": count, "problem": problem}
            if truncated:
                break
    finally:
        try:
            client.close()
        except Exception:
            pass

    layer_errors = [name for name, row in layers.items() if row.get("problem")]
    return {
        "available": True,
        "complete": not truncated and not layer_errors,
        "partial": bool(truncated or layer_errors),
        "problem": (
            ("лимит объектов достигнут; " if truncated else "")
            + (("ошибки слоёв: " + ", ".join(layer_errors)) if layer_errors else "")
        ).strip("; "),
        "lands": list(lands.values()),
        "objects": list(objects.values()),
        "layers": layers,
        "counts": {"lands": len(lands), "objects": len(objects)},
        "source": "НСПД search_in_contour_iter · only_intersects=True",
    }


def _cache_path(slug: str, root: Path | None = None) -> Path:
    base = root or Path(os.getenv("DATA_DIR", "data"))
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(slug))
    return base / "market" / "krt" / "spatial" / f"{safe}.json"


def load_spatial(slug: str, *, root: Path | None = None) -> dict[str, Any]:
    path = _cache_path(slug, root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "cached": False, "reading": reading(slug)}
    if not isinstance(payload, dict):
        return {"available": False, "cached": False, "reading": reading(slug)}
    age = time.time() - float(payload.get("saved_at") or 0)
    return {
        **payload,
        "cached": True,
        "stale": age > SPATIAL_TTL_SECONDS,
        "reading": reading(slug),
    }


def save_spatial(slug: str, payload: dict[str, Any], *, root: Path | None = None) -> None:
    path = _cache_path(slug, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    body = {**payload, "saved_at": time.time(), "slug": slug}
    tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def reading(slug: str) -> bool:
    with _SPATIAL_LOCK:
        return str(slug) in _SPATIAL_READING


def refresh_spatial_in_background(
    slug: str,
    *,
    krt_rings,
    root: Path | None = None,
    force: bool = False,
) -> bool:
    """Start one background NSPD polygon scan per KRT slug."""
    slug = str(slug)
    current = load_spatial(slug, root=root)
    if not force and current.get("cached") and not current.get("stale"):
        return False
    with _SPATIAL_LOCK:
        if slug in _SPATIAL_READING:
            return False
        _SPATIAL_READING.add(slug)

    def run() -> None:
        try:
            save_spatial(slug, discover_nspd(krt_rings=krt_rings), root=root)
        finally:
            with _SPATIAL_LOCK:
                _SPATIAL_READING.discard(slug)

    threading.Thread(
        target=run,
        name=f"krt-spatial-{slug[:30]}",
        daemon=True,
    ).start()
    return True



def merge_official(spatial: dict[str, Any], territory: dict[str, Any]) -> dict[str, Any]:
    """Merge NSPD spatial candidates with official/EGRN territory rows by KN.

    NSPD is the completeness layer (what intersects the contour). Official KRT
    documents and EGRN records are the evidence layer for fate, ownership and
    verified cadastral attributes. Neither source silently deletes the other.
    """
    def merge_rows(spatial_rows, official_rows):
        by_cn: dict[str, dict[str, Any]] = {}
        anonymous: list[dict[str, Any]] = []

        for row in spatial_rows or []:
            item = dict(row or {})
            cn = str(item.get("cadastral_number") or "").strip()
            if cn:
                by_cn[cn] = item
            else:
                anonymous.append(item)

        for row in official_rows or []:
            official = dict(row or {})
            cn = str(official.get("cadastral_number") or "").strip()
            if not cn:
                anonymous.append(official)
                continue
            base = dict(by_cn.get(cn) or {})
            # Geometry from spatial discovery is useful when the official row
            # has not yet received a contour. Evidence fields from the official
            # row otherwise win.
            discovered_rings = list(base.get("rings_merc") or [])
            merged = {**base, **official}
            if not merged.get("rings_merc") and discovered_rings:
                merged["rings_merc"] = discovered_rings
            merged["spatially_discovered"] = cn in by_cn
            merged["officially_listed"] = True
            by_cn[cn] = merged

        for cn, row in by_cn.items():
            row.setdefault("spatially_discovered", True)
            row.setdefault("officially_listed", False)

        return list(by_cn.values()) + anonymous

    return {
        **dict(spatial or {}),
        "lands": merge_rows(
            (spatial or {}).get("lands") or [],
            (territory or {}).get("lands") or [],
        ),
        "objects": merge_rows(
            (spatial or {}).get("objects") or [],
            (territory or {}).get("objects") or [],
        ),
    }


def spatial_selection(
    slug: str,
    *,
    krt_rings,
    territory: dict[str, Any] | None = None,
    root: Path | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    """Return current KRT cadastral selection and trigger refresh if needed."""
    cached = load_spatial(slug, root=root)
    started = False
    if refresh and krt_rings:
        started = refresh_spatial_in_background(
            slug, krt_rings=krt_rings, root=root, force=False
        )
        if started:
            cached["reading"] = True

    if not cached.get("cached"):
        return {
            "available": False,
            "cached": False,
            "reading": bool(cached.get("reading") or started),
            "problem": cached.get("problem") or (
                "пространственный обход НСПД ещё не завершён"
                if (cached.get("reading") or started)
                else "пространственный обход НСПД ещё не запускался"
            ),
            "counts": {"lands": 0, "objects": 0},
            "selection": None,
        }

    merged = merge_official(cached, territory or {})
    chosen = select(
        krt_rings=krt_rings,
        lands=merged.get("lands") or [],
        objects=merged.get("objects") or [],
    )
    return {
        "available": True,
        "cached": True,
        "stale": bool(cached.get("stale")),
        "reading": bool(cached.get("reading") or started),
        "complete_scan": bool(cached.get("complete")),
        "partial_scan": bool(cached.get("partial")),
        "problem": str(cached.get("problem") or ""),
        "source": cached.get("source") or "",
        "layers": cached.get("layers") or {},
        "counts": cached.get("counts") or {},
        "selection": chosen,
    }
