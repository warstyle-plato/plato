"""ОКС и ЗУ в контуре площадки КРТ — по карте НСПД, а не только по перечню.

Здания площадки мы знали только из перечня проекта решения: не прочитано
решение или перечень неполон — зданий в контуре мы не видели, и снос с
выкупом считались по тому, что документ успел назвать (владелец, 29.09.2026:
«для любой площадки КРТ найти ОКС и ЗУ по контуру КРТ и считать по ним снос и
выкуп»). Здесь контур площадки (официальный полигон реестра или участки
перечня — выбирает `_krt_site_finder`) опрашивается слоями НСПД: участки,
здания, сооружения, объекты незавершённого строительства.

Один владелец у каждого ответа:

* запрос к НСПД — движок (`_land_contour_objects`), с Render он уходит на ядро;
* доля объекта в контуре — `nagatino_parcels.share_inside`, тот же замер, что у
  свода территории;
* собственник и кадастровая стоимость — `krt_investment_score._cached_cadastral_buyout`,
  тот же кэш ЕГРН и та же классификация «Москва / не Москва / не определён»,
  что у денежной нагрузки;
* площадь сноса ложится в штатную вводную `demolition_area_sqm` с
  происхождением (`_demolition_source`) — книга, отчёт и PDF читают её из
  движка, своего счёта сноса у них нет.

Модуль без сети: запрос слоя в рамке приходит параметром (`fetch`), поэтому
проверки гоняют сохранённый ответ НСПД.
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from market_search.http import load_json, save_json

from . import nagatino_parcels

SCHEMA_VERSION = 1

# Слои публичной кадастровой карты НСПД (кластер 36 тыс., каталог id снят с
# консоли карты — docs/land_screening_architecture.md). Роль объекта берётся из
# слоя, который спрашивали, — это явная карта, а не догадка по полям; вид,
# названный самим ответом (`categoryName`), сверяется с ролью, и расхождение
# называется, а не выбирается молча.
LAYERS: tuple[tuple[int, str], ...] = (
    (36048, "land"),
    (36049, "building"),
    (36328, "structure"),
    (36329, "unfinished"),
)
KIND_LABELS = {
    "land": "земельный участок",
    "building": "здание",
    "structure": "сооружение",
    "unfinished": "объект незавершённого строительства",
}

# Рамка одного запроса, м веб-меркатора (в Москве ≈ 280 м на местности).
# GetFeatureInfo отдаёт не больше FEATURE_CAP объектов на рамку: упёрлась —
# рамка делится на четыре. Дальше MAX_DEPTH не делим и говорим, что ответ
# неполон, — молча урезанный перечень читался бы как «больше зданий нет».
CELL_M = 500.0
FEATURE_CAP = 50
MAX_DEPTH = 3
MAX_REQUESTS = 600
WORKERS = 4

# Объект считается «в контуре», если внутри лежит не меньше половины его
# пятна. Меньше — «на границе»: такой объект называется списком, но в снос и
# выкуп не идёт, пока человек не решит иначе.
IN_CONTOUR_SHARE = 0.5

RESULT_TTL_SECONDS = 7 * 24 * 3600
FAILURE_TTL_SECONDS = 30 * 60
# Фоновый сбор, который не отчитался за этот срок, считается упавшим: второй
# воркер вправе начать заново.
STALL_SECONDS = 20 * 60
BUYOUT_ROUNDS = 40

_LOCK = threading.Lock()
_RUNNING: set[str] = set()


# --- геометрия ---------------------------------------------------------------

_R = 6378137.0


def merc_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """(lat, lng) точки веб-меркатора."""
    lng = math.degrees(x / _R)
    lat = math.degrees(2.0 * math.atan(math.exp(y / _R)) - math.pi / 2.0)
    return lat, lng


def _rings(raw: Any) -> list[list[list[float]]]:
    out: list[list[list[float]]] = []
    for ring in raw or []:
        if not isinstance(ring, list) or len(ring) < 3:
            continue
        points = [[float(p[0]), float(p[1])] for p in ring
                  if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(points) >= 3:
            out.append(points)
    return out


def _bbox(rings: list[list[list[float]]]) -> tuple[float, float, float, float] | None:
    points = [p for ring in rings for p in ring]
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _cell_touches(rings: list[list[list[float]]],
                  cell: tuple[float, float, float, float]) -> bool:
    """Задевает ли контур рамку: вершина контура в рамке или точка рамки в контуре."""
    west, south, east, north = cell
    for ring in rings:
        for x, y in ring:
            if west <= x <= east and south <= y <= north:
                return True
    for i in range(5):
        for j in range(5):
            x = west + (east - west) * i / 4.0
            y = south + (north - south) * j / 4.0
            if nagatino_parcels._inside_ring(rings, x, y):
                return True
    return False


def cells(rings: list[list[list[float]]], cell_m: float = CELL_M
          ) -> list[tuple[float, float, float, float]]:
    """Рамки, которыми опрашивается контур, — только задевающие его."""
    box = _bbox(rings)
    if not box:
        return []
    min_x, min_y, max_x, max_y = box
    cols = max(1, int(math.ceil((max_x - min_x) / cell_m)))
    rows = max(1, int(math.ceil((max_y - min_y) / cell_m)))
    step_x = (max_x - min_x) / cols or cell_m
    step_y = (max_y - min_y) / rows or cell_m
    out = []
    for i in range(cols):
        for j in range(rows):
            cell = (min_x + i * step_x, min_y + j * step_y,
                    min_x + (i + 1) * step_x, min_y + (j + 1) * step_y)
            if _cell_touches(rings, cell):
                out.append(cell)
    return out


def _wgs84_bounds(cell: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """(west, south, east, north) в градусах — так спрашивает `_nspd_getfeatureinfo`."""
    south, west = merc_to_wgs84(cell[0], cell[1])
    north, east = merc_to_wgs84(cell[2], cell[3])
    return west, south, east, north


# --- сбор с НСПД ---------------------------------------------------------------

Fetch = Callable[[int, tuple[float, float, float, float]], list[dict[str, Any]]]


def collect(rings_merc: Any, fetch: Fetch, *,
            layers: tuple[tuple[int, str], ...] = LAYERS,
            cell_m: float = CELL_M, cap: int = FEATURE_CAP,
            max_depth: int = MAX_DEPTH, max_requests: int = MAX_REQUESTS,
            workers: int = WORKERS) -> dict[str, Any]:
    """Опросить слои НСПД рамками по контуру и собрать объекты без дублей.

    `fetch(layer_id, (west, south, east, north))` — нормализованные движком
    объекты (`_normalize_nspd_feature`): номер, вид, площадь, назначение,
    кадастровая стоимость, `contour_merc`. Бросает — рамка не опрошена, и это
    записывается отказом: «НСПД не ответила» и «объектов нет» — разные ответы.
    """
    rings = _rings(rings_merc)
    result: dict[str, Any] = {
        "objects": [], "requests": 0, "failures": [], "truncated": [],
        "cells": 0, "problem": "",
    }
    if not rings:
        result["problem"] = "контура площадки нет — опрашивать НСПД нечем"
        return result
    grid = cells(rings, cell_m)
    result["cells"] = len(grid)
    budget = {"left": int(max_requests)}
    lock = threading.Lock()

    def ask(layer: int, cell: tuple[float, float, float, float], depth: int
            ) -> list[dict[str, Any]]:
        with lock:
            if budget["left"] <= 0:
                result["truncated"].append({"layer": layer, "reason": "исчерпан лимит запросов"})
                return []
            budget["left"] -= 1
            result["requests"] += 1
        try:
            found = [item for item in (fetch(layer, _wgs84_bounds(cell)) or [])
                     if isinstance(item, dict)]
        except Exception as exc:  # noqa: BLE001 — отказ рамки называется, а не молчит
            detail = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
            with lock:
                result["failures"].append({"layer": layer, "reason": str(detail)[:200]})
            return []
        if len(found) >= cap:
            if depth >= max_depth:
                with lock:
                    result["truncated"].append(
                        {"layer": layer, "reason": f"рамка отдала {len(found)} объектов — "
                                                   "потолок ответа НСПД, часть могла не прийти"})
                return found
            west, south, east, north = cell
            mid_x, mid_y = (west + east) / 2.0, (south + north) / 2.0
            parts = [(west, south, mid_x, mid_y), (mid_x, south, east, mid_y),
                     (west, mid_y, mid_x, north), (mid_x, mid_y, east, north)]
            out = list(found)
            for part in parts:
                if _cell_touches(rings, part):
                    out.extend(ask(layer, part, depth + 1))
            return out
        return found

    jobs = [(layer, role, cell) for layer, role in layers for cell in grid]
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        answers = list(pool.map(lambda job: (job[0], job[1], ask(job[0], job[2], 0)), jobs))

    by_number: dict[str, dict[str, Any]] = {}
    for layer, role, found in answers:
        for item in found:
            number = str(item.get("cadastral_number") or "").strip()
            if not number or number in by_number:
                continue
            own = _rings(item.get("contour_merc"))
            share = nagatino_parcels.share_inside(own, rings) if own else None
            if share is not None and share <= 0.0:
                # Рамка задела объект, а контур — нет: соседа не записываем.
                continue
            reported = str(item.get("kind") or "")
            conflict = ""
            if (role == "land") != (reported == "land") and reported in ("land", "building"):
                conflict = (f"слой «{KIND_LABELS[role]}», а ответ называет объект "
                            f"«{item.get('kind_label') or reported}»")
            by_number[number] = {
                "cadastral_number": number,
                "kind": role,
                "kind_label": KIND_LABELS[role],
                "kind_conflict": conflict,
                "layer": layer,
                "address": str(item.get("address") or "")[:300],
                "area_sqm": item.get("area_sqm") if isinstance(item.get("area_sqm"), (int, float)) else None,
                "purpose": str(item.get("purpose") or item.get("permitted_use") or "")[:200],
                "cadastral_value_rub": (item.get("cadastral_value_rub")
                                        if isinstance(item.get("cadastral_value_rub"), (int, float))
                                        else None),
                "ownership": str(item.get("ownership") or ""),
                "share": None if share is None else round(float(share), 3),
                "map_url": str(item.get("map_url") or ""),
            }
    result["objects"] = sorted(by_number.values(),
                               key=lambda row: (row["kind"], row["cadastral_number"]))
    if result["failures"]:
        result["problem"] = (f"НСПД не ответила на {len(result['failures'])} из "
                             f"{result['requests']} запросов: {result['failures'][0]['reason']}")
    return result


# --- сверка с перечнем решения, снос, выкуп ------------------------------------

def _in_contour(row: dict[str, Any]) -> bool:
    share = row.get("share")
    return isinstance(share, (int, float)) and share >= IN_CONTOUR_SHARE


def reconcile(objects: list[dict[str, Any]],
              requirements: dict[str, Any] | None) -> dict[str, Any]:
    """Три группы: в перечне и в контуре / только в контуре / только в перечне.

    Не объединяем молча: объект, которого документ не называет, мог быть
    пропущен распознаванием перечня, а мог лежать на границе. Границе и
    объектам без пятна — свои группы.
    """
    req = requirements if isinstance(requirements, dict) else {}
    listed = [str(n).strip() for n in (req.get("cadastral_numbers") or []) if str(n).strip()]
    listed_set = set(listed)
    inside = [row for row in objects if _in_contour(row)]
    border = [row for row in objects
              if isinstance(row.get("share"), (int, float)) and not _in_contour(row)]
    no_shape = [row for row in objects if row.get("share") is None]
    found = {row["cadastral_number"] for row in objects}
    return {
        "listed_available": bool(listed),
        "listed_source": str(req.get("cadastral_numbers_source") or "none"),
        "both": [row["cadastral_number"] for row in inside if row["cadastral_number"] in listed_set],
        "contour_only": [row["cadastral_number"] for row in inside
                         if row["cadastral_number"] not in listed_set],
        "list_only": [n for n in listed if n not in found],
        "border": [row["cadastral_number"] for row in border],
        "no_shape": [row["cadastral_number"] for row in no_shape],
    }


_FATES = {
    "demolition": "снос",
    "demolition_or_reconstruction": "снос или реконструкция",
    "reconstruction": "реконструкция",
    "preservation": "сохранение",
}


def demolition(objects: list[dict[str, Any]],
               requirements: dict[str, Any] | None) -> dict[str, Any]:
    """Площадь сносимого: судьба — из решения, где оно её называет.

    * решение называет «снос» — объект сносится, площадь решения (иначе ЕГРН);
    * «снос или реконструкция» — выбор не сделан, в площадь не идёт, назван;
    * «реконструкция» / «сохранение» — не сносится;
    * судьба не названа — здание в контуре считается под снос, и это названо
      допущением, а не выдано за требование документа;
    * сооружения (сети, дороги) и ОНС в площадь не идут: их «площадь» в ЕГРН —
      не площадь пола, а снос сетей — перекладка, не демонтаж здания;
    * здание перечня со сносом, не найденное в контуре, считается по решению —
      документ сильнее нашего неответа карты.
    """
    req = requirements if isinstance(requirements, dict) else {}
    actions: dict[str, dict[str, Any]] = {}
    for item in req.get("object_actions") or []:
        if isinstance(item, dict) and item.get("cadastral_number"):
            actions.setdefault(str(item["cadastral_number"]).strip(), item)
    rows: list[dict[str, Any]] = []
    total = 0.0
    counted = by_decision = assumed = no_area = 0
    seen: set[str] = set()
    for row in objects:
        if row.get("kind") != "building" or not _in_contour(row):
            continue
        number = row["cadastral_number"]
        seen.add(number)
        action = actions.get(number)
        category = str((action or {}).get("category") or "")
        entry = {"cadastral_number": number, "address": row.get("address") or "",
                 "fate": category or "unnamed", "area_sqm": None, "counted": False,
                 "basis": ""}
        if category in ("reconstruction", "preservation"):
            entry["basis"] = f"решение: {_FATES[category]}"
        elif category == "demolition_or_reconstruction":
            entry["basis"] = "решение: снос или реконструкция — выбор не сделан, в площадь не идёт"
        else:
            decision_area = (action or {}).get("area_sqm")
            area = (decision_area if isinstance(decision_area, (int, float)) and decision_area > 0
                    else row.get("area_sqm"))
            if category == "demolition":
                entry["basis"] = "решение: снос"
            else:
                entry["basis"] = "судьбу решение не называет — считаем под снос (допущение)"
            if isinstance(area, (int, float)) and area > 0:
                entry.update(area_sqm=float(area), counted=True)
                total += float(area)
                counted += 1
                if category == "demolition":
                    by_decision += 1
                else:
                    assumed += 1
            else:
                no_area += 1
                entry["basis"] += "; площадь не опубликована — в сумму не вошла"
        rows.append(entry)
    for number, action in actions.items():
        if number in seen or action.get("category") != "demolition":
            continue
        if any(row["cadastral_number"] == number for row in objects):
            # Найден, но не здание в контуре (граница, другой слой) — назван ниже.
            continue
        area = action.get("area_sqm")
        entry = {"cadastral_number": number, "address": str(action.get("label") or ""),
                 "fate": "demolition", "area_sqm": None, "counted": False,
                 "basis": "решение: снос; в контуре на карте НСПД не найден"}
        if isinstance(area, (int, float)) and area > 0:
            entry.update(area_sqm=float(area), counted=True)
            total += float(area)
            counted += 1
            by_decision += 1
        else:
            no_area += 1
            entry["basis"] += "; площадь не опубликована — в сумму не вошла"
        rows.append(entry)
    assumptions = []
    if assumed:
        assumptions.append(
            f"{assumed} зданий в контуре решение не называет — считаются под снос; "
            "сохраняемое здание уберите из расчёта, исправив площадь сноса вручную")
    if no_area:
        assumptions.append(f"у {no_area} сносимых зданий площадь не опубликована — "
                           "площадь сноса занижена на них")
    return {
        "area_sqm": round(total, 1),
        "objects": counted,
        "by_decision": by_decision,
        "assumed": assumed,
        "without_area": no_area,
        "rows": rows,
        "label": f"контур КРТ, {counted} ОКС",
        "assumptions": assumptions,
    }


def buyout_numbers(objects: list[dict[str, Any]],
                   requirements: dict[str, Any] | None) -> list[str]:
    """Номера, по которым считается выкуп: ЗУ и здания в контуре плюс перечень.

    Один список на карточку и на денежную нагрузку — тогда у них один кэш ЕГРН
    и один итог. Сооружения и ОНС из карты сюда не идут: сети и дороги не
    выкупают; перечень решения входит целиком — документ называет их составом.
    """
    req = requirements if isinstance(requirements, dict) else {}
    listed = [str(n).strip() for n in (req.get("cadastral_numbers") or []) if str(n).strip()]
    mapped = [row["cadastral_number"] for row in objects
              if row.get("kind") in ("land", "building") and _in_contour(row)]
    return list(dict.fromkeys(listed + mapped))


def apply_demolition(inputs: dict[str, Any], summary: dict[str, Any] | None) -> dict[str, Any]:
    """Положить площадь сноса во вводную — если человек не вписал свою.

    Ручное значение — это ненулевая площадь без отметки происхождения или с
    отметкой, число которой уже не совпадает с полем: человек его переписал.
    Такое не трогаем. Отметка `_demolition_source` едет вместе с вводными и
    говорит странице, откуда число, пока оно не исправлено.
    """
    out = dict(inputs or {})
    if not isinstance(summary, dict) or summary.get("area_sqm") is None:
        return out
    current = out.get("demolition_area_sqm")
    try:
        current_value = float(current or 0)
    except (TypeError, ValueError):
        current_value = 0.0
    marker = out.get("_demolition_source")
    auto = isinstance(marker, dict) and _same(marker.get("value"), current_value)
    if current_value > 0 and not auto:
        out["_demolition_source_skipped"] = {
            "value": summary.get("area_sqm"), "by": summary.get("label") or "контур КРТ",
            "reason": "площадь сноса вписана вручную — контур её не затирает",
        }
        return out
    area = float(summary.get("area_sqm") or 0.0)
    out["demolition_area_sqm"] = area
    out["_demolition_source"] = {"value": area, "by": str(summary.get("label") or "контур КРТ"),
                                 "kind": "krt_contour"}
    return out


def apply_buyout(inputs: dict[str, Any], buyout: dict[str, Any] | None) -> dict[str, Any]:
    """Положить оценку выкупа во вводную `land_buyout_mln` — если человек не вписал свою.

    Число — кадастровая стоимость не-московских ЗУ и ОКС контура без дублей
    (`_cached_cadastral_buyout`), подпись — «кадастровая стоимость, не цена
    сделки». Собственник не определён — не ноль: объекты перечисляются в
    отметке предупреждением, а в число входят только доказанные. Сбор не
    закончен (ЕГРН дочитывается) — вводная не трогается.
    """
    out = dict(inputs or {})
    if not isinstance(buyout, dict) or buyout.get("pending"):
        return out
    unknown = [str(n) for n in (buyout.get("unknown_numbers") or [])]
    if buyout.get("available"):
        value = buyout.get("amount_mln")
    elif unknown or buyout.get("known_paid_mln"):
        value = buyout.get("known_paid_mln")
    else:
        return out
    if not isinstance(value, (int, float)):
        return out
    current = out.get("land_buyout_mln")
    try:
        current_value = float(current or 0)
    except (TypeError, ValueError):
        current_value = 0.0
    marker = out.get("_land_buyout_source")
    auto = isinstance(marker, dict) and _same(marker.get("value"), current_value)
    if current_value > 0 and not auto:
        out["_land_buyout_source_skipped"] = {
            "value": round(float(value), 3),
            "reason": "выкуп вписан вручную — оценка по контуру его не затирает",
        }
        return out
    paid = int(buyout.get("paid_count") or 0)
    city = int(buyout.get("moscow_zero_count") or 0)
    by = (f"кадастровая стоимость, не цена сделки: {paid} объектов не Москвы"
          + (f", {city} у Москвы — 0" if city else ""))
    warn = ""
    if unknown:
        warn = (f"собственник не определён у {len(unknown)} объектов — в сумму не вошли, "
                f"выкуп занижен на них: {', '.join(unknown[:20])}")
    elif not buyout.get("available"):
        warn = str(buyout.get("reason") or "выкуп собран не полностью")
    out["land_buyout_mln"] = round(float(value), 3)
    out["_land_buyout_source"] = {"value": round(float(value), 3), "by": by,
                                  "kind": "krt_contour", "warn": warn,
                                  "unknown": unknown[:60]}
    return out


def _same(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.05
    except (TypeError, ValueError):
        return False


# --- диск и фон ---------------------------------------------------------------

def _root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "market" / "krt" / "contour"


def _safe(slug: str) -> str:
    safe = re.sub(r"[^0-9a-zа-яё_:.-]+", "-", str(slug or "").strip().lower(), flags=re.I)
    return safe.replace(":", "_").strip("-.")[:140] or "krt"


def cache_path(slug: str) -> Path:
    return _root() / f"{_safe(slug)}.json"


def _pending_path(slug: str) -> Path:
    return _root() / f"{_safe(slug)}.pending"


def cached(slug: str) -> dict[str, Any] | None:
    data = load_json(cache_path(slug))
    if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION:
        return data
    return None


def _fresh(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    ttl = FAILURE_TTL_SECONDS if data.get("problem") and not data.get("objects") else RESULT_TTL_SECONDS
    return time.time() - float(data.get("collected_at") or 0) < ttl


def running(slug: str) -> bool:
    """Идёт ли сбор — в этом воркере или в соседнем (отметка на диске)."""
    with _LOCK:
        if slug in _RUNNING:
            return True
    try:
        started = _pending_path(slug).stat().st_mtime
    except OSError:
        return False
    return time.time() - started < STALL_SECONDS


def _claim(slug: str) -> bool:
    """Взять сбор на себя. Воркеров два — отметка ставится атомарно на диске."""
    path = _pending_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - path.stat().st_mtime >= STALL_SECONDS:
            path.unlink()
    except OSError:
        pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as fh:
        fh.write(str(int(time.time())))
    with _LOCK:
        _RUNNING.add(slug)
    return True


def _release(slug: str) -> None:
    with _LOCK:
        _RUNNING.discard(slug)
    try:
        _pending_path(slug).unlink()
    except OSError:
        pass


def gather(slug: str, *, find_site: Callable[[], dict[str, Any]],
           contour_objects: Callable[[list[list[list[float]]]], dict[str, Any]],
           requirements: dict[str, Any] | None,
           lookup: Callable[[list[str]], list[dict[str, Any]]] | None,
           buyout: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Собрать объекты контура и дочитать ЕГРН для выкупа. Долго — только фоном."""
    site = find_site() or {}
    rings = _rings(site.get("rings_merc"))
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "slug": slug,
        "contour": {"source": str(site.get("source") or ""),
                    "matched": str(site.get("matched") or ""),
                    "problem": str(site.get("problem") or "")},
        "objects": [], "requests": 0, "failures": [], "truncated": [],
        "problem": "", "collected_at": int(time.time()),
    }
    if not rings:
        data["problem"] = str(site.get("problem") or "контур площадки не собрался")
        save_json(cache_path(slug), data)
        return data
    try:
        found = contour_objects(rings) or {}
    except Exception as exc:  # noqa: BLE001 — неответ ядра называется
        detail = getattr(exc, "detail", None) or f"{type(exc).__name__}: {exc}"
        data["problem"] = f"НСПД по контуру не спрошена: {detail}"[:300]
        save_json(cache_path(slug), data)
        return data
    for key in ("objects", "requests", "failures", "truncated", "cells"):
        if key in found:
            data[key] = found[key]
    data["problem"] = str(found.get("problem") or "")
    save_json(cache_path(slug), data)
    if buyout is not None and callable(lookup):
        numbers = buyout_numbers(data["objects"], requirements)
        for _ in range(BUYOUT_ROUNDS):
            state = buyout({"slug": slug}, numbers, lookup) or {}
            if not state.get("pending") or state.get("reason", "").startswith("ЕГРН не ответил"):
                break
    return data


def start(slug: str, **kwargs: Any) -> bool:
    """Завести фоновый сбор, если ответа нет или он протух. Запрос не ждёт."""
    if running(slug) or _fresh(cached(slug)):
        return False
    if not _claim(slug):
        return False

    def run() -> None:
        try:
            gather(slug, **kwargs)
        except Exception:  # noqa: BLE001 — упавший сбор снимает отметку, причина в кэше нет
            data = cached(slug) or {"schema_version": SCHEMA_VERSION, "slug": slug,
                                    "objects": []}
            data.update(problem="сбор объектов контура упал — повторим позже",
                        collected_at=int(time.time()))
            save_json(cache_path(slug), data)
        finally:
            _release(slug)

    threading.Thread(target=run, name=f"krt-contour-{_safe(slug)}", daemon=True).start()
    return True


def view(slug: str, requirements: dict[str, Any] | None,
         buyout: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ответ карточке и модели — из диска, без сети.

    Выкуп читается тем же `_cached_cadastral_buyout` без клиента ЕГРН: он
    отвечает из кэша, который дочитал фон, и не ходит в сеть сам.
    """
    data = cached(slug)
    if data is None:
        return {"available": False, "pending": running(slug),
                "reason": ("ищем ОКС и ЗУ в контуре на карте НСПД" if running(slug)
                           else "объекты в контуре ещё не искали")}
    objects = list(data.get("objects") or [])
    out: dict[str, Any] = {
        "available": bool(objects) or not data.get("problem"),
        "pending": running(slug),
        "collected_at": data.get("collected_at"),
        "contour": data.get("contour") or {},
        "problem": str(data.get("problem") or ""),
        "requests": data.get("requests"),
        "failures": len(data.get("failures") or []),
        "truncated": list(data.get("truncated") or [])[:5],
        "objects": objects,
        "counts": {kind: sum(1 for row in objects if row.get("kind") == kind and _in_contour(row))
                   for kind, _ in ((k, v) for k, v in KIND_LABELS.items())},
        "in_contour_share": IN_CONTOUR_SHARE,
        "reconcile": reconcile(objects, requirements),
        "demolition": demolition(objects, requirements),
    }
    if buyout is not None:
        numbers = buyout_numbers(objects, requirements)
        state = buyout({"slug": slug}, numbers, None) if numbers else {
            "available": False, "reason": "выкупать нечего: ни ЗУ, ни зданий в контуре"}
        out["buyout"] = {
            **{key: state.get(key) for key in (
                "available", "pending", "reason", "amount_mln", "known_paid_mln",
                "moscow_zero_count", "paid_count", "unknown_numbers", "read", "total")},
            "rows": list(state.get("rows") or []),
            "basis": "кадастровая стоимость, не цена сделки",
        }
    return out
