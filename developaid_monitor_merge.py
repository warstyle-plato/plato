"""Один проект под двумя именами — свести в один каталог Монитора.

«Почему разница между Гродненской и Кутузов Сити? Это один проект»
(владелец, 21.10.2026; главное имя — «Кутузов Сити»). Файлы проекта загружали
под двумя названиями, и в Мониторе лежало два каталога с разными снимками:
сводка по одному имени не видела того, что лежит под другим.

Объединение переносит в главный каталог всё, чего там нет, и ничего в нём не
перезаписывает:
- файла нет в главном — переезжает;
- файл такой же — второй экземпляр не нужен;
- журнал (`*.jsonl`: записи «Общей информации», фото) — дописываются строки,
  которых в главном нет;
- точечные факты работ за один день (`work_fact/<день>.json`) — строки обоих,
  при одной работе в обоих побеждает главный;
- остальное разное (например, второй утверждённый ГПР) — не трогает главный,
  а кладётся рядом в `.merged-from-<имя>/` и называется в отчёте: выбрать между
  двумя утверждёнными графиками должен человек.

Старое имя становится псевдонимом (`developaid_monitor._aliases`): чат
стройки, привязанный к нему, бот и ссылки продолжают работать и попадают в
главный каталог. Прежний каталог не удаляется, а уходит в `.merged/` — откат
возможен руками. Подписчики рассылки сводки старого имени переходят к главному.
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import developaid_monitor as monitor


def _plan(source: Path, target: Path) -> list[dict[str, str]]:
    out = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        rel = path.relative_to(source)
        if any(part.startswith(".") for part in rel.parts) or path.name.endswith(".tmp"):
            continue  # кэши разбора и недописанные файлы — не данные проекта
        there = target / rel
        if not there.exists():
            action = "move"
        elif _digest(path) == _digest(there):
            action = "same"
        elif path.suffix == ".jsonl":
            action = "append"
        elif rel.parts[0] == "work_fact" and path.suffix == ".json":
            action = "combine"
        else:
            action = "conflict"
        out.append({"file": rel.as_posix(), "action": action})
    return out


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> None:
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(tmp, path)


def _append(source: Path, target: Path) -> None:
    have = set(target.read_text(encoding="utf-8").splitlines())
    extra = [line for line in source.read_text(encoding="utf-8").splitlines()
             if line.strip() and line not in have]
    if extra:
        with target.open("a", encoding="utf-8") as out:
            out.write(("" if target.read_text(encoding="utf-8").endswith("\n") else "\n")
                      + "\n".join(extra) + "\n")


def _combine(source: Path, target: Path) -> None:
    mine = json.loads(target.read_text(encoding="utf-8"))
    theirs = json.loads(source.read_text(encoding="utf-8"))
    rows = {str(row.get("id")): row for row in theirs.get("rows") or []}
    rows.update({str(row.get("id")): row for row in mine.get("rows") or []})
    mine["rows"] = list(rows.values())
    _write(target, json.dumps(mine, ensure_ascii=False))


def merge(source: str, target: str, author: str, apply: bool = False,
          now: datetime.datetime | None = None) -> dict[str, Any]:
    """Свести проект ``source`` в ``target``; без ``apply`` — только показать план."""
    names = {item["project"]: item for item in monitor.projects()}
    if source not in names or target not in names:
        missing = source if source not in names else target
        raise KeyError(f"В Мониторе нет проекта «{missing}».")
    if monitor._slug(source) == monitor._slug(target):
        raise ValueError("Это один и тот же проект.")
    base = monitor._SNAPSHOT_DIR
    src, dst = base / monitor._slug(source), base / monitor._slug(target)
    lock = base / ".aliases.lock"
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            plan = _plan(src, dst)
            counts: dict[str, int] = {}
            for item in plan:
                counts[item["action"]] = counts.get(item["action"], 0) + 1
            report = {"source": source, "target": target, "applied": False,
                      "counts": counts, "files": plan,
                      "conflicts": [item["file"] for item in plan
                                    if item["action"] == "conflict"]}
            if not apply:
                return report
            aside = dst / f".merged-from-{src.name}"
            for item in plan:
                here, there = src / item["file"], dst / item["file"]
                if item["action"] == "move":
                    there.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(here, there)
                elif item["action"] == "append":
                    _append(here, there)
                elif item["action"] == "combine":
                    _combine(here, there)
                elif item["action"] == "conflict":
                    (aside / item["file"]).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(here, aside / item["file"])
            stamp = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(
                timespec="seconds")
            aliases = dict(monitor._aliases())
            aliases[src.name] = dst.name
            # Псевдоним на псевдоним сводится сразу к главному.
            aliases = {name: (dst.name if main == src.name else main)
                       for name, main in aliases.items()}
            _write(base / monitor._ALIASES_FILE,
                   json.dumps({"aliases": aliases}, ensure_ascii=False, indent=1))
            parked = base / ".merged" / f"{src.name}-{stamp[:19].replace(':', '')}"
            parked.parent.mkdir(parents=True, exist_ok=True)
            src.rename(parked)
            with (base / ".merged" / "log.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps({"at": stamp, "by": author, "source": source,
                                      "target": target, "counts": counts,
                                      "conflicts": report["conflicts"],
                                      "parked": parked.name}, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    import developaid_report_mailing as mailing
    report["subscribers_moved"] = mailing.rename_project(source, target)
    report["applied"] = True
    return report
