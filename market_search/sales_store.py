"""Разобранные источники продаж лежат на ядре, а не в браузере.

Файлов на один проект несколько, и приходят они порознь: выгрузка ЦФ несёт
контрактацию и оба плана, книга финмодели — квартирографию (владелец,
26.08.2026: «можно его подгружать будет просто потом дополнительно?»).
Просить оба файла при каждом открытии значит однажды получить два файла
разных дат и показать их как один проект.

Хранится РАЗОБРАННОЕ, а не сам файл: выгрузка ЦФ — это 25 МБ, а её свод —
сотни килобайт, и диск у нас уже кончался молча. Имён покупателей в
разобранном нет: читатель их не выносит из себя, остаётся только признак
юрлица.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

# Что умеем принимать. Ключ — как называется источник внутри, значение — как он
# называется человеку.
KINDS = {
    "contracting": "контрактация ЦФ",
    "ledger": "проводки 1С",
    "fm_plan": "план нашей финмодели",
    "bank_plan": "план банка",
    "pool": "квартирография книги",
}

_SLUG = re.compile(r"[^a-zа-яё0-9]+", re.I)


def slug(project: str) -> str:
    """Имя файла проекта. Пустое имя — тоже имя: у части выгрузок его нет."""
    out = _SLUG.sub("-", str(project or "").strip().lower()).strip("-")
    return out or "без-имени"


def _path(data_dir: Path, project: str) -> Path:
    return Path(data_dir) / "cabinet" / f"{slug(project)}.json"


def load(data_dir: Path, project: str) -> dict[str, Any]:
    place = _path(data_dir, project)
    if not place.exists():
        return {"project": project, "sources": {}}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        # Битый файл — это «нечего показать», а не «продаж не было».
        return {"project": project, "sources": {}, "broken": str(place.name)}
    got.setdefault("sources", {})
    return got


def save(data_dir: Path, project: str, parts: dict[str, Any], filename: str) -> dict[str, Any]:
    """Положить разобранные части рядом с уже лежащими.

    Кладётся то, что разобралось. Источник, которого в этом файле не было,
    остаётся прежним: иначе вторая загрузка стирала бы то, что принесла первая.
    """
    kept = load(data_dir, project)
    kept["project"] = project or kept.get("project") or ""
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for kind, payload in parts.items():
        if payload is None:
            continue
        kept["sources"][kind] = {"at": at, "file": filename, "data": payload}
    place = _path(data_dir, project)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps(kept, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    return kept


def projects(data_dir: Path) -> list[dict[str, Any]]:
    """Что уже лежит: имя проекта, источники и когда каждый принесён."""
    where = Path(data_dir) / "cabinet"
    if not where.exists():
        return []
    out = []
    for place in sorted(where.glob("*.json")):
        try:
            got = json.loads(place.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        sources = got.get("sources") or {}
        out.append({
            "project": got.get("project") or place.stem,
            "sources": [{"kind": kind, "name": KINDS.get(kind, kind),
                         "at": (value or {}).get("at"), "file": (value or {}).get("file")}
                        for kind, value in sorted(sources.items())],
        })
    return out
