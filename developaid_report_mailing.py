"""Рассылка сводки руководству: приглашения, подписчики, расписание, очередь.

Решения владельца (20.10.2026): получатели подписываются по ссылке-приглашению
на бота, которую владелец создаёт для проекта; сводка приходит сообщением и
PDF — за неделю по понедельникам, за месяц 1-го числа, в 9:00 МСК; владелец
видит список и может отписать любого.

Устройство. Данные Монитора и печать PDF живут на ядре, а до Telegram
достаёт только бот на Render. Поэтому ядро само, в фоне, собирает сводку
каждого проекта с подписчиками один раз на срок рассылки и кладёт её в
очередь, а бот забирает очередь подписанным маршрутом и рассылает.

Двойной отправки нет при двух воркерах и там, и там:
- сборку срока делает тот, кто взял неблокирующий замок сборки; готовый файл
  очереди — отметка «собрано», второй раз срок не собирается;
- выдача боту — под замком: получатель переходит в «передано боту» в той же
  записи, где его забрали; второй воркер бота получает пустую очередь.
Чего бот не подтвердил, остаётся «отправка не подтверждена», а не «отправлено»:
повторять вслепую хуже, чем показать владельцу, что дошло не всё.

Всё лежит рядом с данными Монитора (`.mailing/` в каталоге снимков), а не на
диске бота: тот стирается при каждой выкатке.
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import re
import secrets
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import developaid_monitor as monitor

try:
    from zoneinfo import ZoneInfo

    MSK: datetime.tzinfo = ZoneInfo("Europe/Moscow")
except Exception:  # noqa: BLE001 — без базы поясов Москва — это UTC+3
    MSK = datetime.timezone(datetime.timedelta(hours=3))

HOUR = 9
# Сколько срок рассылки ждёт сборки и бота: ядро или бот, лежавшие в 9:00,
# досылают в тот же день, а не через неделю. Старше — уже не новость.
WINDOW = datetime.timedelta(hours=36)
RETRY = datetime.timedelta(hours=2)
START_PREFIX = "rep_"
STATES = {"pending": "ждёт отправки", "taken": "отправка не подтверждена",
          "sent": "отправлено", "failed": "не отправлено"}


def _root() -> Path:
    path = monitor._SNAPSHOT_DIR / ".mailing"
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextlib.contextmanager
def _locked(name: str = "lock", wait: bool = True) -> Iterator[bool]:
    """Замок на файл в каталоге рассылки; ``wait=False`` — не ждать, а сказать «занято»."""
    with (_root() / name).open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False)
    os.replace(tmp, path)


def _now(now: datetime.datetime | None = None) -> datetime.datetime:
    return (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(MSK)


def _stamp(now: datetime.datetime | None = None) -> str:
    return _now(now).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Приглашения и подписчики
# --------------------------------------------------------------------------

def _invites() -> Path:
    return _root() / "invites.json"


def _subscribers() -> Path:
    return _root() / "subscribers.json"


def invite(project: str, author: str, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Новая ссылка-приглашение проекта; прежняя перестаёт действовать.

    Ссылку пересылают дальше, и единственный способ её закрыть — выдать новую.
    Уже подписавшиеся при этом остаются подписаны.
    """
    token = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
    with _locked():
        invites = {key: value for key, value in _read(_invites(), {}).items()
                   if value.get("project") != project}
        invites[token] = {"project": project, "by": author, "at": _stamp(now)}
        _write(_invites(), invites)
    return {"token": token, "start": START_PREFIX + token, **invites[token]}


def current_invite(project: str) -> dict[str, Any] | None:
    for token, value in _read(_invites(), {}).items():
        if value.get("project") == project:
            return {"token": token, "start": START_PREFIX + token, **value}
    return None


def subscribe(start: str, chat_id: int, name: str,
              now: datetime.datetime | None = None) -> str:
    """Подписать чат по «/start rep_<код>»; вернуть проект."""
    token = str(start or "").removeprefix(START_PREFIX)
    if not re.fullmatch(r"[A-Za-z0-9]{8,40}", token) or not int(chat_id or 0):
        raise ValueError("Ссылка-приглашение повреждена.")
    with _locked():
        found = _read(_invites(), {}).get(token)
        if not found:
            raise KeyError("Эта ссылка-приглашение больше не действует: попросите "
                           "у владельца проекта новую.")
        project = found["project"]
        book = _read(_subscribers(), {})
        people = [row for row in book.get(project, []) if int(row["chat_id"]) != int(chat_id)]
        people.append({"chat_id": int(chat_id), "name": str(name or "").strip()[:120],
                       "at": _stamp(now)})
        book[project] = people
        _write(_subscribers(), book)
    return project


def unsubscribe(chat_id: int, project: str | None = None) -> list[str]:
    """Отписать чат от проекта (или ото всех); вернуть, от каких отписан."""
    gone = []
    with _locked():
        book = _read(_subscribers(), {})
        for name in list(book):
            if project is not None and name != project:
                continue
            kept = [row for row in book[name] if int(row["chat_id"]) != int(chat_id)]
            if len(kept) != len(book[name]):
                gone.append(name)
            book[name] = kept
        _write(_subscribers(), book)
    return gone


def subscribers(project: str) -> list[dict[str, Any]]:
    return list(_read(_subscribers(), {}).get(project, []))


# --------------------------------------------------------------------------
# Расписание
# --------------------------------------------------------------------------

def slots_on(day: datetime.date) -> list[dict[str, str]]:
    """Сроки рассылки, выпадающие на день: неделя — понедельник, месяц — 1-е."""
    out = []
    before = day - datetime.timedelta(days=1)
    if day.weekday() == 0:
        out.append({"slot": f"week-{before.isoformat()}", "kind": "week",
                    "end": before.isoformat()})
    if day.day == 1:
        out.append({"slot": f"month-{before:%Y-%m}", "kind": "month",
                    "end": before.isoformat()})
    for item in out:
        item["at"] = datetime.datetime.combine(day, datetime.time(HOUR), MSK).isoformat()
    return out


def due(now: datetime.datetime | None = None) -> list[dict[str, str]]:
    """Сроки, которые уже наступили и ещё не устарели."""
    moment = _now(now)
    out = []
    for back in (1, 0):
        for item in slots_on(moment.date() - datetime.timedelta(days=back)):
            start = datetime.datetime.fromisoformat(item["at"])
            if start <= moment < start + WINDOW:
                out.append(item)
    return out


def next_slot(now: datetime.datetime | None = None) -> dict[str, str]:
    moment = _now(now)
    day = moment.date()
    while True:
        for item in slots_on(day):
            if datetime.datetime.fromisoformat(item["at"]) > moment:
                return item
        day += datetime.timedelta(days=1)


# --------------------------------------------------------------------------
# Очередь: сборка на ядре, выдача боту
# --------------------------------------------------------------------------

def _outbox(slot: str, project: str) -> Path:
    return _root() / "outbox" / slot / f"{monitor._slug(project)}.json"


def build_due(make, now: datetime.datetime | None = None) -> list[str]:
    """Собрать наступившие сроки для проектов с подписчиками.

    ``make(project, kind, end)`` возвращает ``{"text", "pdf" (bytes|None),
    "filename", "error", "retry"}`` — сводку и её PDF (печать тяжёлая, поэтому сюда
    приходят из фонового потока, не из запроса). Замок сборки не ждётся:
    занят — значит, другой воркер уже собирает.
    """
    built = []
    with _locked("build.lock", wait=False) as mine:
        if not mine:
            return built
        book = _read(_subscribers(), {})
        for item in due(now):
            for project, people in sorted(book.items()):
                place = _outbox(item["slot"], project)
                if not people or place.exists():
                    continue
                got = make(project, item["kind"], item["end"])
                # Печать занята соседним PDF — попробуем в следующий проход; через
                # два часа ждать дальше незачем: уйдёт сообщение с причиной.
                if got.get("retry") and _now(now) < (
                        datetime.datetime.fromisoformat(item["at"]) + RETRY):
                    continue
                pdf_name = ""
                if got.get("pdf"):
                    pdf_name = place.with_suffix(".pdf").name
                    place.parent.mkdir(parents=True, exist_ok=True)
                    place.with_suffix(".pdf").write_bytes(got["pdf"])
                with _locked():
                    # Получатели — те, кто подписан к моменту сборки.
                    people = _read(_subscribers(), {}).get(project, [])
                    _write(place, {
                        "slot": item["slot"], "kind": item["kind"], "end": item["end"],
                        "at": item["at"], "project": project, "built_at": _stamp(now),
                        "text": got.get("text") or "", "pdf": pdf_name,
                        "filename": got.get("filename") or "svodka.pdf",
                        "error": got.get("error") or "",
                        "deliveries": {str(row["chat_id"]): {"state": "pending"}
                                       for row in people}})
                built.append(f"{item['slot']}:{project}")
    return built


def take(now: datetime.datetime | None = None) -> list[dict[str, Any]]:
    """Отдать боту неотправленное; отданное помечается «передано боту» сразу."""
    out = []
    live = {item["slot"] for item in due(now)}
    folder = _root() / "outbox"
    with _locked():
        for place in sorted(folder.glob("*/*.json")) if folder.exists() else []:
            if place.parent.name not in live:
                continue
            entry = _read(place, {})
            chats = [chat for chat, value in entry.get("deliveries", {}).items()
                     if value.get("state") == "pending"]
            if not chats:
                continue
            for chat in chats:
                entry["deliveries"][chat] = {"state": "taken", "at": _stamp(now)}
            _write(place, entry)
            pdf = place.with_name(entry["pdf"]) if entry.get("pdf") else None
            out.append({"slot": entry["slot"], "project": entry["project"],
                        "text": entry["text"], "filename": entry["filename"],
                        "error": entry["error"], "chats": [int(chat) for chat in chats],
                        "pdf": pdf.read_bytes() if pdf and pdf.exists() else None})
    return out


def confirm(slot: str, project: str, results: dict[str, str],
            now: datetime.datetime | None = None) -> None:
    """Что бот сделал с отданным: пустая строка — отправлено, иначе причина."""
    place = _outbox(slot, project)
    with _locked():
        entry = _read(place, None)
        if entry is None:
            raise KeyError(f"Рассылки {slot} по проекту «{project}» нет.")
        for chat, error in results.items():
            if str(chat) in entry["deliveries"]:
                entry["deliveries"][str(chat)] = {
                    "state": "failed" if error else "sent", "at": _stamp(now),
                    **({"error": str(error)[:300]} if error else {})}
        _write(place, entry)


def status(project: str, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Для страницы сводки: приглашение, получатели, последняя рассылка каждому."""
    folder = _root() / "outbox"
    last: dict[str, dict[str, Any]] = {}
    for place in sorted(folder.glob(f"*/{monitor._slug(project)}.json")) if folder.exists() else []:
        entry = _read(place, {})
        for chat, value in entry.get("deliveries", {}).items():
            if (last.get(chat) or {}).get("at_slot", "") <= entry.get("at", ""):
                last[chat] = dict(value, at_slot=entry.get("at", ""), slot=entry.get("slot"),
                                  label=STATES.get(value.get("state"), value.get("state")),
                                  pdf_error=entry.get("error", ""))
    people = [dict(row, last=last.get(str(row["chat_id"])))
              for row in subscribers(project)]
    return {"invite": current_invite(project), "subscribers": people,
            "next": next_slot(now)}
