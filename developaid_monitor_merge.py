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
- точечные факты работ за один день (`work_fact/<день>.json`) — строки обоих
  только при доказанном одинаковом источнике ГПР; главный имеет приоритет;
- другой источник факта и его история версий остаются в отдельном архиве,
  не получают SHA главного плана и не активируются совпадением ID работ;
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
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import developaid_monitor as monitor


def _legacy_sha(root: Path) -> str:
    path = monitor._legacy_baseline_file(root.name)
    return _digest(path) if path is not None else ''


def _fact_sha(path: Path, root: Path) -> str:
    """Keep the recorded source, including the immutable basis of legacy facts."""
    metadata = path if path.suffix == '.json' else path.with_suffix('.source.json')
    if metadata.exists():
        try:
            payload = json.loads(metadata.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                return ''
            if 'source_sha256' in payload:
                value = payload['source_sha256']
                return value if isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) else ''
        except (OSError,ValueError):
            return ''
    return _legacy_sha(root)


def _target_fact_sha(path: Path, source: Path, target: Path) -> str:
    day = path.name[:10]
    if not monitor._day(day) or monitor._day(day).isoformat() != day:
        return ''
    selected = monitor._baseline_state(target.name,day)
    if selected['path'] is None:
        selected = monitor._baseline_state(source.name,day)
    return selected['source_sha256']


def _gpr_authority(rel: Path) -> bool:
    return (rel.parts[0] == 'schedule' or rel.parts[0] == 'baseline' and (
        len(rel.parts) > 1 and rel.parts[1] in {'gpr.xlsx','meta.json','schedule_versions.json','schedule_sources'}))


def _plan(source: Path, target: Path) -> list[dict[str, str]]:
    out = []
    target_has_gpr = bool(_legacy_sha(target))
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        rel = path.relative_to(source)
        if any(part.startswith(".") for part in rel.parts) or path.name.endswith(".tmp"):
            continue  # кэши разбора и недописанные файлы — не данные проекта
        there = target / rel
        fact = rel.parts[0] in {'work_fact','schedule_fact'} and path.suffix in {'.json','.xlsx'}
        source_sha = _fact_sha(path,source) if fact else ''
        target_sha = _target_fact_sha(path,source,target) if fact else ''
        if there.exists() and _digest(path) == _digest(there):
            action = "same"
        elif target_has_gpr and _gpr_authority(rel):
            # A missing authority file is not permission to activate the other
            # project's plan or version chain over the main project's source.
            action = 'conflict'
        elif fact and (not source_sha or source_sha != target_sha):
            action = 'conflict'
        elif not there.exists():
            action = "move"
        elif path.suffix == ".jsonl":
            action = "append"
        elif rel.parts[0] == "work_fact" and path.suffix == ".json":
            action = 'combine' if _fact_sha(there,target) == source_sha else 'conflict'
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


def _combine(source: Path, target: Path, source_root: Path, target_root: Path) -> None:
    mine = json.loads(target.read_text(encoding="utf-8"))
    theirs = json.loads(source.read_text(encoding="utf-8"))
    source_sha = _fact_sha(source,source_root)
    if not source_sha or _fact_sha(target,target_root) != source_sha:
        raise ValueError('Ручные факты относятся к разным источникам ГПР; автоматическое объединение не выполнено.')
    rows = {str(row.get("id")): row for row in theirs.get("rows") or []}
    rows.update({str(row.get("id")): row for row in mine.get("rows") or []})
    mine["rows"] = list(rows.values())
    mine['source_sha256'] = source_sha
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
                    _combine(here, there,src,dst)
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
