"""Общая информация по проекту: записи, которые вводятся руками.

Статус арбитража с подрядчиком, спор с соседом, решение собственника — то,
чего нет ни в РСС, ни в ГПР, но что руководство должно видеть в сводке.

Записи хранятся журналом: каждая правка — новая строка с датой и автором,
прежние строки не переписываются. Текущее состояние записи — её последняя
версия. Журнал лежит в каталоге проекта мониторинга; дописывание идёт под
замком файла, потому что воркеров два.
"""

from __future__ import annotations

import datetime
import fcntl
import json
import uuid
from pathlib import Path
from typing import Any

import developaid_monitor as monitor

STATUSES = {"open": "Вопрос открыт", "closed": "Вопрос закрыт"}
_MAX_TOPIC = 200
_MAX_TEXT = 4000


def _log(project: str) -> Path:
    folder = monitor._project_dir(project) / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "log.jsonl"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _clean(value: Any, limit: int, what: str) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"{what} длиннее {limit} знаков")
    return text


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            # Недописанная строка — след оборванной записи; остальное цело.
            continue
    return rows


def _append(path: Path, entry: dict[str, Any], check=None) -> dict[str, Any]:
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            if check is not None:
                check(_read(path))
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    return entry


def add(project: str, topic: str, text: str, author: str,
        status: str = "open", at: str = "") -> dict[str, Any]:
    """Новая запись. Тема и текст обязательны: пустая запись — не новость."""
    topic = _clean(topic, _MAX_TOPIC, "тема")
    text = _clean(text, _MAX_TEXT, "текст")
    if not topic or not text:
        raise ValueError("нужны тема и текст записи")
    if status not in STATUSES:
        raise ValueError(f"неизвестный статус записи: {status!r}")
    entry = {"id": uuid.uuid4().hex[:12], "at": at or _now(),
             "author": str(author or "").strip() or "не указан",
             "topic": topic, "text": text, "status": status, "version": 1}
    return _append(_log(project), entry)


def update(project: str, note_id: str, author: str, text: str | None = None,
           status: str | None = None, at: str = "") -> dict[str, Any]:
    """Новая версия записи: новый текст и/или статус. Прежняя остаётся в журнале."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"неизвестный статус записи: {status!r}")
    if text is not None:
        text = _clean(text, _MAX_TEXT, "текст")
        if not text:
            raise ValueError("текст записи не может быть пустым")
    path = _log(project)
    entry: dict[str, Any] = {}

    def build(rows: list[dict[str, Any]]) -> None:
        versions = [row for row in rows if row.get("id") == note_id]
        if not versions or versions[-1].get("deleted"):
            raise KeyError(f"записи {note_id} в проекте нет")
        last = versions[-1]
        entry.update({
            "id": note_id, "at": at or _now(),
            "author": str(author or "").strip() or "не указан",
            "topic": last["topic"],
            "text": text if text is not None else last["text"],
            "status": status if status is not None else last["status"],
            "version": len(versions) + 1})
        if (entry["text"], entry["status"]) == (last["text"], last["status"]):
            raise ValueError("в записи ничего не изменилось")

    return _append(path, entry, build)


def remove(project: str, note_id: str, author: str, at: str = "") -> dict[str, Any]:
    """Удалить запись (владелец, 22.10.2026: «это был тест, как его удалить»).

    Журнал ничего не теряет: удаление — последняя версия с пометкой `deleted`,
    в ней кто и когда удалил. Список и сводка такую запись не показывают.
    """
    path = _log(project)
    entry: dict[str, Any] = {}

    def build(rows: list[dict[str, Any]]) -> None:
        versions = [row for row in rows if row.get("id") == note_id]
        if not versions or versions[-1].get("deleted"):
            raise KeyError(f"записи {note_id} в проекте нет")
        last = versions[-1]
        entry.update({"id": note_id, "at": at or _now(),
                      "author": str(author or "").strip() or "не указан",
                      "topic": last["topic"], "text": last["text"], "status": last["status"],
                      "version": len(versions) + 1, "deleted": True})

    return _append(path, entry, build)


def notes(project: str) -> list[dict[str, Any]]:
    """Текущие записи: последняя версия каждой, с датой создания и автором первой."""
    current: dict[str, dict[str, Any]] = {}
    for row in _read(_log(project)):
        first = current.get(row["id"], {})
        current[row["id"]] = dict(row, created_at=first.get("created_at", row["at"]),
                                  created_by=first.get("created_by", row["author"]))
    out = [row for row in current.values() if not row.get("deleted")]
    # Открытые выше закрытых, свежие правки выше старых.
    open_rows = sorted([r for r in out if r["status"] == "open"],
                       key=lambda r: r["at"], reverse=True)
    closed = sorted([r for r in out if r["status"] != "open"],
                    key=lambda r: r["at"], reverse=True)
    return open_rows + closed


def for_period(project: str, start: datetime.date,
               end: datetime.date) -> dict[str, Any]:
    """Что попадает в сводку: все открытые и закрытые за период.

    Версия считается по состоянию на конец периода: правка, сделанная позже,
    в сводку периода не идёт.
    """
    edge = end.isoformat()
    current: dict[str, dict[str, Any]] = {}
    for row in _read(_log(project)):
        if row["at"][:10] > edge:
            continue
        current[row["id"]] = row
    first = start.isoformat()
    rows = sorted((r for r in current.values() if not r.get("deleted")),
                  key=lambda r: r["at"], reverse=True)
    return {
        # Открытые — все; «changed» отмечает новые и поправленные за период.
        "open": [dict(r, changed=r["at"][:10] >= first)
                 for r in rows if r["status"] == "open"],
        "closed": [r for r in rows if r["status"] != "open"
                   and r["at"][:10] >= first],
    }
