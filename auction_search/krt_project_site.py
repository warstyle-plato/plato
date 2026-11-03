"""Территория КРТ проекта: опознать площадку, взять её контур и площадь.

Владелец (26.10.2026, «Пролетарская»): «по КРТ 0,77 га», а расчёт шёл по
2 430 м² — участкам ЕГРН по кадастровым номерам проекта. Контур территории КРТ
Москвы часто не совпадает с контурами существующих участков, и ЕГРН даёт
только её часть. Галочка «Проект в КРТ» на вкладке ТЭП берёт контур и площадь
у самой площадки.

Здесь три шага, и у каждого один владелец:
- `find_site` — контур площадки по слагу: сперва официальный полигон файла
  карты реестра (krt.mos.ru), иначе состав территории по проекту решения. Им же
  пользуются свод площадки и объекты контура (`auction_search/api.py`): второй
  дороги к контуру нет;
- `identify` — какая площадка у проекта: точка его участков внутри полигона
  файла карты или его номер в уже собранном перечне решения. Сеть здесь не
  трогается, только прочитанное;
- `gather` — оба шага и площадь контура (`krt_contour_area_sqm` движка).
  Долго (файл карты, ЕГРН по перечню) — только фоном (`start`), ответ странице
  читается с диска (`view`): воркеров два, память у них раздельная.

Отказ называет причину словами: «площадка не опознана», «опознано несколько»,
«контура нет» — и не превращается в площадь ноль.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from market_search.http import load_json, save_json

SCHEMA_VERSION = 1
RESULT_TTL_SECONDS = 24 * 3600
FAILURE_TTL_SECONDS = 10 * 60
STALL_SECONDS = 10 * 60
MAX_NUMBERS = 40
MAX_POINTS = 40

SOURCE_MAP = "официальный полигон реестра КРТ"
SOURCE_DECISION = "состав территории по проекту решения"

_LOCK = threading.Lock()
_RUNNING: set[str] = set()
_CADASTRAL_RE = re.compile(r"^\d{2}:\d{2}:\d{6,7}:\d+$")


def _rings(raw: Any) -> list[list[list[float]]]:
    return [ring for ring in (raw or []) if isinstance(ring, list) and len(ring) >= 3]


# --- контур площадки -----------------------------------------------------------

def find_site(registry: Any, slug: str, name: str, *,
              decision_outline: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    """Контур площадки: сперва файл карты города, потом перечень решения.

    `decision_outline` — синхронный сбор контура по перечню (`_decision_outline_now`
    маршрутов КРТ): ЕГРН он спрашивает путём движка.
    """
    lookup = getattr(registry, "map_lookup", None)
    found = (lookup(slug, name, None) or {}) if callable(lookup) else {}
    site = found.get("site") or {}
    rings = _rings(site.get("rings_merc"))
    if rings:
        return {"slug": slug, "name": str(site.get("name") or name),
                "rings_merc": rings, "matched": str(found.get("matched") or "map"),
                "source": "официальный файл карты реестра КРТ", "problem": ""}
    outline = decision_outline(slug) or {}
    rings = _rings(outline.get("rings_merc"))
    if rings:
        return {"slug": slug, "name": name, "rings_merc": rings,
                "matched": "decision",
                "source": "состав территории по проекту решения, "
                          "а не официальный полигон",
                "problem": str(outline.get("problem") or "")}
    # Обе дороги называют свою причину: по одной первой не понять, спрашивали
    # ли перечень решения вовсе.
    why = "; ".join(part for part in (str(found.get("problem") or ""),
                                      str(outline.get("problem") or "")) if part)
    return {"problem": why or "контур площадки не собрался: её нет ни в файле "
                              "карты города, ни в перечне проекта решения"}


# --- опознание площадки проекта ------------------------------------------------

def _inside(point: list[float], ring: list[list[float]]) -> bool:
    x, y = float(point[0]), float(point[1])
    inside = False
    for i in range(len(ring)):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[i - 1][0]), float(ring[i - 1][1])
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _covers(rings: list[list[list[float]]], point: list[float]) -> bool:
    """Точка внутри полигона из плоского списка колец (дыры — чётностью)."""
    return sum(1 for ring in rings if _inside(point, ring)) % 2 == 1


def clean_numbers(numbers: Any) -> list[str]:
    out: list[str] = []
    for raw in numbers or []:
        text = str(raw or "").strip()
        if _CADASTRAL_RE.match(text) and text not in out:
            out.append(text)
    return out[:MAX_NUMBERS]


def clean_points(points: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for raw in points or []:
        try:
            out.append([float(raw[0]), float(raw[1])])
        except (TypeError, ValueError, IndexError):
            continue
    return out[:MAX_POINTS]


def _outline_files(registry: Any) -> list[dict[str, Any]]:
    """Уже собранные контуры по перечням решений — с диска, без сети."""
    folder = getattr(registry, "outline_dir", None)
    if not folder:
        return []
    out = []
    for path in sorted(Path(folder).glob("*.json")):
        data = load_json(path)
        if isinstance(data, dict) and data.get("schema_version") == 1:
            out.append(data)
    return out


def identify(registry: Any, *, numbers: list[str], points_merc: list[list[float]],
             map_sites: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Площадка КРТ проекта по его участкам. Ответ — `status`:

    - `found` — одна площадка (`slug`, `name`, как опознана — `matched_by`);
    - `ambiguous` — несколько, на выбор человеку (`choices`);
    - `unknown` — ни одной, `problem` говорит почему.

    Сильнее — полигон файла карты: это официальная граница. Перечень решения
    спрашивается, только когда файл карты промолчал.
    """
    if not numbers and not points_merc:
        return {"status": "unknown", "choices": [],
                "problem": "у проекта нет ни кадастровых номеров, ни контура участков "
                           "из госреестра — площадку КРТ опознать не по чему"}
    by_map: dict[str, dict[str, Any]] = {}
    for site in map_sites or []:
        rings = _rings(site.get("rings_merc"))
        if rings and any(_covers(rings, point) for point in points_merc):
            slug = str(site.get("slug") or "")
            if slug:
                by_map[slug] = {"slug": slug, "name": str(site.get("name") or slug),
                                "matched_by": "участок проекта внутри официального полигона"}
    if len(by_map) == 1:
        return {"status": "found", "choices": [], "problem": "", **next(iter(by_map.values()))}
    if len(by_map) > 1:
        return {"status": "ambiguous", "choices": list(by_map.values()),
                "problem": "участки проекта лежат в границах нескольких площадок КРТ"}
    wanted = set(numbers)
    by_decision: dict[str, dict[str, Any]] = {}
    for outline in _outline_files(registry):
        slug = str(outline.get("slug") or "")
        named = {str(p.get("cadastral_number") or "") for p in outline.get("parcels") or []
                 if isinstance(p, dict)}
        rings = _rings(outline.get("rings_merc"))
        if slug and ((wanted & named)
                     or (rings and any(_covers(rings, point) for point in points_merc))):
            title = str((outline.get("decision") or {}).get("title") or "")
            by_decision[slug] = {"slug": slug, "name": title[:160] or slug,
                                 "matched_by": "номер проекта в перечне проекта решения"}
    if len(by_decision) == 1:
        return {"status": "found", "choices": [], "problem": "",
                **next(iter(by_decision.values()))}
    if len(by_decision) > 1:
        return {"status": "ambiguous", "choices": list(by_decision.values()),
                "problem": "номера проекта названы в перечнях нескольких площадок КРТ"}
    if not points_merc:
        why = ("контура участков проекта из госреестра нет, а в собранных перечнях "
               "решений его номеров нет")
    elif not map_sites:
        why = ("файл карты реестра КРТ не прочитан, а в собранных перечнях решений "
               "номеров проекта нет")
    else:
        why = ("участки проекта не лежат внутри ни одной площадки файла карты реестра "
               "КРТ, и в собранных перечнях решений их номеров нет")
    return {"status": "unknown", "choices": [], "problem": why}


# --- сбор целиком --------------------------------------------------------------

def gather(registry: Any, *, slug: str, name: str, numbers: list[str],
           points_merc: list[list[float]],
           decision_outline: Callable[[str], dict[str, Any]],
           area_sqm: Callable[[list[list[list[float]]]], float]) -> dict[str, Any]:
    """Опознать площадку (если слаг не выбран), взять контур и площадь. Долго."""
    data: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "collected_at": int(time.time()),
                            "status": "", "slug": "", "name": "", "choices": [],
                            "problem": "", "rings_merc": [], "area_sqm": None,
                            "source": "", "source_note": "", "matched_by": ""}
    if not slug:
        map_sites: list[dict[str, Any]] = []
        map_problem = ""
        try:
            map_sites = list((registry.map_dataset() or {}).get("sites") or [])
        except Exception as exc:  # noqa: BLE001 — неответ файла карты называется
            map_problem = f"файл карты реестра КРТ не прочитан: {type(exc).__name__}"
        who = identify(registry, numbers=numbers, points_merc=points_merc, map_sites=map_sites)
        if who["status"] != "found":
            data.update(status=who["status"], choices=who.get("choices") or [],
                        problem="; ".join(p for p in (who.get("problem"), map_problem) if p))
            return data
        slug, name = who["slug"], who["name"]
        data["matched_by"] = who.get("matched_by") or ""
    else:
        data["matched_by"] = "площадка выбрана в проекте"
    site = find_site(registry, slug, name, decision_outline=decision_outline)
    rings = _rings(site.get("rings_merc"))
    data.update(slug=slug, name=str(site.get("name") or name or slug))
    if not rings:
        data.update(status="no_contour",
                    problem=str(site.get("problem") or "контур площадки не собрался"))
        return data
    area = float(area_sqm(rings) or 0.0)
    if area <= 0:
        data.update(status="no_contour",
                    problem="контур площадки собрался, но его площадь не считается — "
                            "кольца вырождены")
        return data
    official = site.get("matched") != "decision"
    data.update(status="ready", rings_merc=rings, area_sqm=round(area, 1),
                source=SOURCE_MAP if official else SOURCE_DECISION,
                source_note=str(site.get("problem") or ""))
    return data


# --- диск и фон ----------------------------------------------------------------

def _root() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "market" / "krt" / "project_site"


def request_key(slug: str, numbers: list[str], points_merc: list[list[float]]) -> str:
    """Ключ ответа: выбранная площадка или участки проекта, а не сессия."""
    body = json.dumps({"slug": slug, "numbers": sorted(numbers),
                       "points": sorted([round(p[0]), round(p[1])] for p in points_merc)},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:24]


def _path(key: str) -> Path:
    return _root() / f"{key}.json"


def _pending(key: str) -> Path:
    return _root() / f"{key}.pending"


def cached(key: str) -> dict[str, Any] | None:
    data = load_json(_path(key))
    if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION:
        return data
    return None


def _fresh(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    # Фото схемы, с которого форма не снялась (Платон недоступен), — ответ
    # неполный: повторная загрузка спрашивает снова, а не берёт его с диска.
    whole = data.get("status") == "ready" and not data.get("shape_problem")
    ttl = RESULT_TTL_SECONDS if whole else FAILURE_TTL_SECONDS
    return time.time() - float(data.get("collected_at") or 0) < ttl


def _running(key: str) -> bool:
    with _LOCK:
        if key in _RUNNING:
            return True
    try:
        return time.time() - _pending(key).stat().st_mtime < STALL_SECONDS
    except OSError:
        return False


def _claim(key: str) -> bool:
    path = _pending(key)
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
        _RUNNING.add(key)
    return True


def _release(key: str) -> None:
    with _LOCK:
        _RUNNING.discard(key)
    try:
        _pending(key).unlink()
    except OSError:
        pass


def start(key: str, work: Callable[[], dict[str, Any]], *, refresh: bool = False) -> bool:
    """Завести фоновый сбор, если ответа нет или он протух. Запрос не ждёт."""
    if _running(key) or (not refresh and _fresh(cached(key))):
        return False
    if not _claim(key):
        return False

    def run() -> None:
        try:
            data = work()
        except Exception as exc:  # noqa: BLE001 — упавший сбор называет причину
            data = {"schema_version": SCHEMA_VERSION, "collected_at": int(time.time()),
                    "status": "failed", "choices": [], "rings_merc": [], "area_sqm": None,
                    "problem": f"сбор контура КРТ упал: {type(exc).__name__}: {exc}"[:300]}
        save_json(_path(key), data)
        _release(key)

    threading.Thread(target=run, name=f"krt-project-site-{key}", daemon=True).start()
    return True


def view(key: str) -> dict[str, Any]:
    """Ответ странице — с диска. Пока сбора нет — «ищем» и когда спросить снова."""
    data = cached(key)
    pending = _running(key)
    if data is None or (pending and not _fresh(data)):
        return {"status": "pending", "retry_after_seconds": 3, "problem": ""}
    out = dict(data)
    out["retry_after_seconds"] = None
    return out
