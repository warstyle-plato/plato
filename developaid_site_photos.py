"""Фото со стройки из чата площадки — для сводки руководству.

Бот уже читает привязанный чат стройки (ежедневные отчёты); фото оттуда он
тоже забирает: на Render качает средний размер снимка и отдаёт ядру
подписанным маршрутом — ядро до api.telegram.org не достаёт. Здесь — только
хранение на ядре и выбор.

Какие фото попадут в сводку, решает человек на странице «Сводка руководству»
(владелец, 20.10.2026: «фото из чата тоже выборочно брать и вставлять», выбор —
на странице). Автоматически не попадает ничего: не отмеченное фото в сводке
не появляется, а отсутствие отметки не равно «снято» — это просто «не выбрано».

Журнал тот же, что у записей «Общая информация» (`developaid_project_notes`):
дописывание под замком файла, воркеров два. Снимок — файлом рядом, имя —
постоянный идентификатор Telegram, поэтому повторно присланный вебхук не
плодит копий.
"""

from __future__ import annotations

import base64
import datetime
import re
from pathlib import Path
from typing import Any

import developaid_monitor as monitor
from developaid_project_notes import _append, _now, _read

MAX_BYTES = 5 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_MAX_CAPTION = 1000


def _folder(project: str) -> Path:
    folder = monitor._project_dir(project) / "photos"
    (folder / "files").mkdir(parents=True, exist_ok=True)
    return folder


def _file(project: str, photo_id: str) -> Path:
    if not _ID.match(str(photo_id or "")):
        raise ValueError("неверный идентификатор фото")
    folder = _folder(project) / "files"
    return monitor._inside(folder, f"{photo_id}.jpg")


def _is_image(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"


def store(project: str, data: bytes, photo_id: str, day: str, author: str = "",
          caption: str = "", at: str = "", message_id: int = 0) -> dict[str, Any]:
    """Положить снимок из чата. Повтор того же снимка — не новая запись."""
    if not data or len(data) > MAX_BYTES:
        raise ValueError(f"снимок пустой или больше {MAX_BYTES // (1024 * 1024)} МБ")
    if not _is_image(data):
        raise ValueError("это не снимок JPEG или PNG")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day or "")):
        raise ValueError("дата снимка нужна в виде ГГГГ-ММ-ДД")
    path = _file(project, photo_id)
    log = _folder(project) / "log.jsonl"
    entry = {"kind": "photo", "id": photo_id, "day": day, "at": at or _now(),
             "author": str(author or "").strip()[:200],
             "caption": str(caption or "").strip()[:_MAX_CAPTION],
             "message_id": int(message_id or 0), "size": len(data)}
    duplicate = {}

    def check(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if row.get("kind") == "photo" and row.get("id") == photo_id:
                duplicate.update(row)
                raise FileExistsError(photo_id)

    # Файл — раньше строки журнала: строка без файла читалась бы как снимок,
    # которого нет. Повтор пишет те же байты поверх — вреда нет.
    path.write_bytes(data)
    try:
        _append(log, entry, check)
    except FileExistsError:
        return {**duplicate, "duplicate": True}
    return entry


def select(project: str, photo_id: str, chosen: bool, by: str) -> dict[str, Any]:
    """Отметить фото для сводки или снять отметку. Каждая отметка — строка журнала."""
    log = _folder(project) / "log.jsonl"

    def check(rows: list[dict[str, Any]]) -> None:
        if not any(row.get("kind") == "photo" and row.get("id") == photo_id for row in rows):
            raise KeyError(f"фото {photo_id} не найдено")

    return _append(log, {"kind": "select", "id": photo_id, "chosen": bool(chosen),
                         "by": str(by or "").strip()[:200], "at": _now()}, check)


def photos(project: str, start: Any = None, end: Any = None) -> list[dict[str, Any]]:
    """Снимки за период (по дню в чате) с последней отметкой выбора."""
    folder = monitor._project_dir(project) / "photos"
    rows = _read(folder / "log.jsonl")
    first = monitor._iso(start) if start else ""
    last = monitor._iso(end) if end else "9999-12-31"
    items: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("kind") == "photo" and row.get("id") not in items:
            items[row["id"]] = {**row, "chosen": False, "chosen_by": ""}
        elif row.get("kind") == "select" and row.get("id") in items:
            items[row["id"]]["chosen"] = bool(row.get("chosen"))
            items[row["id"]]["chosen_by"] = row.get("by") or ""
    return sorted((item for item in items.values() if first <= item["day"] <= last),
                  key=lambda item: (item["day"], item["at"]))


def read(project: str, photo_id: str) -> bytes:
    path = _file(project, photo_id)
    if not path.exists():
        raise KeyError(f"файла фото {photo_id} нет")
    return path.read_bytes()


def for_report(project: str, start: datetime.date, end: datetime.date) -> dict[str, Any]:
    """Выбранные фото периода — встраиваются в документ строкой data URI."""
    found = photos(project, start, end)
    chosen = [item for item in found if item["chosen"]]
    items = []
    for item in chosen:
        try:
            data = read(project, item["id"])
        except KeyError:
            continue
        kind = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        items.append({**item, "src": f"data:{kind};base64,"
                      + base64.b64encode(data).decode("ascii")})
    return {"total": len(found), "items": items}
