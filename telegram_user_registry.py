from __future__ import annotations

import html
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_users(
 user_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL,
 username TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
 last_name TEXT NOT NULL DEFAULT '', language_code TEXT NOT NULL DEFAULT '',
 first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
 messages INTEGER NOT NULL DEFAULT 0, callbacks INTEGER NOT NULL DEFAULT 0,
 platon_requests INTEGER NOT NULL DEFAULT 0, model_exports INTEGER NOT NULL DEFAULT 0,
 last_command TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'telegram');
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON telegram_users(last_seen DESC);
"""


def _ids(raw: str) -> set[int]:
    out = set()
    for part in str(raw or "").replace(";", ",").split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if value:
            out.add(value)
    return out


def _sender(update: dict[str, Any]) -> tuple[dict[str, Any], int, str, str]:
    message = update.get("message") if isinstance(update, dict) else None
    if isinstance(message, dict):
        user = message.get("from") or {}
        chat = message.get("chat") or {}
        return user, int(chat.get("id") or user.get("id") or 0), str(message.get("text") or ""), "message"
    query = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(query, dict):
        user = query.get("from") or {}
        chat = (query.get("message") or {}).get("chat") or {}
        return user, int(chat.get("id") or user.get("id") or 0), str(query.get("data") or ""), "callback"
    return {}, 0, "", ""


def _command(text: str) -> tuple[str, str]:
    text = str(text or "").strip()
    if not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    return parts[0].split("@", 1)[0].lower(), parts[1].strip() if len(parts) > 1 else ""


def _when(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%d.%m.%Y %H:%M") if ts else "—"


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def touch(self, user: dict[str, Any], chat_id: int, event: str, *, command: str = "", platon: int = 0,
              model_export: int = 0, source: str = "telegram") -> None:
        user_id = int(user.get("id") or chat_id or 0)
        if not user_id or not chat_id:
            return
        now = int(time.time())
        values = {
            "user_id": user_id, "chat_id": chat_id,
            "username": str(user.get("username") or ""),
            "first_name": str(user.get("first_name") or ""),
            "last_name": str(user.get("last_name") or ""),
            "language_code": str(user.get("language_code") or ""),
            "first_seen": now, "last_seen": now,
            "messages": int(event == "message"), "callbacks": int(event == "callback"),
            "platon_requests": int(platon), "model_exports": int(model_export),
            "last_command": command[:120], "source": source[:32],
        }
        with self.connect() as db:
            db.execute("""INSERT INTO telegram_users VALUES(
             :user_id,:chat_id,:username,:first_name,:last_name,:language_code,
             :first_seen,:last_seen,:messages,:callbacks,:platon_requests,:model_exports,:last_command,:source)
             ON CONFLICT(user_id) DO UPDATE SET
             chat_id=excluded.chat_id,
             username=CASE WHEN excluded.username<>'' THEN excluded.username ELSE telegram_users.username END,
             first_name=CASE WHEN excluded.first_name<>'' THEN excluded.first_name ELSE telegram_users.first_name END,
             last_name=CASE WHEN excluded.last_name<>'' THEN excluded.last_name ELSE telegram_users.last_name END,
             language_code=CASE WHEN excluded.language_code<>'' THEN excluded.language_code ELSE telegram_users.language_code END,
             last_seen=MAX(telegram_users.last_seen,excluded.last_seen),
             messages=telegram_users.messages+excluded.messages,
             callbacks=telegram_users.callbacks+excluded.callbacks,
             platon_requests=telegram_users.platon_requests+excluded.platon_requests,
             model_exports=telegram_users.model_exports+excluded.model_exports,
             last_command=CASE WHEN excluded.last_command<>'' THEN excluded.last_command ELSE telegram_users.last_command END,
             source=CASE WHEN telegram_users.source='backfill' THEN excluded.source ELSE telegram_users.source END""", values)

    def get(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM telegram_users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def list(self, *, since: int | None = None, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        where, params = ("WHERE last_seen>=?", [since]) if since else ("", [])
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM telegram_users {where} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                              [*params, limit, offset]).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> tuple[int, int, int, int]:
        now = int(time.time())
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(*) total,
             SUM(last_seen>=?) day,SUM(last_seen>=?) week,SUM(last_seen>=?) month FROM telegram_users""",
                             (now-86400, now-7*86400, now-30*86400)).fetchone()
        return tuple(int(row[key] or 0) for key in ("total", "day", "week", "month"))


def _name(row: dict[str, Any]) -> str:
    full = " ".join(x for x in (str(row.get("first_name") or ""), str(row.get("last_name") or "")) if x)
    username = str(row.get("username") or "")
    if full and username:
        return f"{html.escape(full)} · @{html.escape(username)}"
    return html.escape(full) if full else ("@" + html.escape(username) if username else f"ID {row['user_id']}")


def _line(number: int, row: dict[str, Any]) -> str:
    return (f"<b>{number}. {_name(row)}</b>\nID: <code>{row['user_id']}</code> · {_when(row['last_seen'])}\n"
            f"Сообщения {row['messages']} · Платон {row['platon_requests']} · модели {row['model_exports']}")


def _detail(row: dict[str, Any]) -> str:
    return (f"<b>{_name(row)}</b>\nTelegram ID: <code>{row['user_id']}</code>\nChat ID: <code>{row['chat_id']}</code>\n"
            f"Первый вход: {_when(row['first_seen'])}\nПоследняя активность: {_when(row['last_seen'])}\n"
            f"Язык: {html.escape(row['language_code'] or '—')}\n\nСообщения: <b>{row['messages']}</b>\n"
            f"Нажатия: <b>{row['callbacks']}</b>\nЗапросы Платону: <b>{row['platon_requests']}</b>\n"
            f"Выгрузки модели: <b>{row['model_exports']}</b>\nПоследняя команда: <code>{html.escape(row['last_command'] or '—')}</code>")


def _send(core: Any, chat_id: int, text: str) -> None:
    for start in range(0, max(1, len(text)), 3900):
        core._telegram_api("sendMessage", {"chat_id": chat_id, "text": text[start:start+3900] or "—",
                                           "parse_mode": "HTML", "disable_web_page_preview": True})


def _state_ids(path: Path) -> set[int]:
    found: set[int] = set()
    for file in path.glob("*.json") if path.is_dir() else []:
        try:
            stack = [json.loads(file.read_text(encoding="utf-8"))]
        except Exception:
            continue
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key in ("chat_id", "user_id"):
                    try:
                        value = int(item.get(key) or 0)
                    except (TypeError, ValueError):
                        value = 0
                    if value:
                        found.add(value)
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return found


def restore_from_core(base: Any, registry: "Registry") -> int:
    """Наполнить таблицу бота реестром ядра. Возвращает, сколько восстановлено.

    Реестр ядра — единственная копия, пережившая выкатку. Своё, что записано
    после старта, не затирается: `touch` только дописывает, а первый визит
    берётся самый ранний из двух.
    """
    core = getattr(base, "core", None)
    if core is None:
        return 0
    try:
        remote = core._projects_remote_url("/internal/users/list")
    except Exception:
        return 0
    if not remote:
        return 0
    try:
        answer = core._core_post(remote, {"sign": core._web_login_sign("users-list", 0)}, 30.0)
    except Exception as exc:
        core._PLATON_LOG.warning("Реестр с ядра не пришёл: %s: %s",
                                 type(exc).__name__, exc)
        return 0
    restored = 0
    for record in (answer or {}).get("users") or []:
        if not isinstance(record, dict):
            continue
        chat = int(record.get("chat") or 0)
        if not chat or registry.get(chat):
            continue
        name = str(record.get("name") or "")
        first, _, last = name.partition(" ")
        registry.touch({"id": chat, "first_name": first, "last_name": last},
                       chat, "", source="core")
        try:
            with registry.connect() as db:
                db.execute("UPDATE telegram_users SET first_seen=?, last_seen=? "
                           "WHERE user_id=?",
                           (int(float(record.get("first_seen") or 0)),
                            int(float(record.get("last_seen") or 0)), chat))
        except Exception:
            pass
        restored += 1
    return restored


def install(base: Any) -> Registry:
    if getattr(base, "_TELEGRAM_USER_REGISTRY_INSTALLED", False):
        return base._TELEGRAM_USER_REGISTRY
    root = Path(getattr(base, "_ROOT", Path(__file__).resolve().parent))
    registry = Registry(Path(os.getenv("TELEGRAM_USER_DB", "") or root/"data"/"telegram_users.sqlite3"))
    # Одна роль — один владелец, но переменных исторически две: /users открывал
    # TELEGRAM_ADMIN_IDS, а /stats, /survey и сводка — DEVELOPAID_ADMIN_IDS.
    # Заполнишь одну — половина учёта останется запертой, и не поймёшь почему.
    admins = _ids(os.getenv("TELEGRAM_ADMIN_IDS", ""))
    try:
        admins |= set(base.core.usage_admin_ids())
    except Exception:
        pass
    original = base.core._telegram_handle_update

    def handle(update: dict[str, Any]) -> None:
        user, chat_id, text, event = _sender(update)
        command, arg = _command(text) if event == "message" else ("", "")
        callback = text if event == "callback" else ""
        platon = int(command in {"/platon", "/платон", "/comment", "/тэп_комментарий"}
                      or callback in {"ask_platon", "platon_tep"})
        if event == "message" and text and not command:
            try:
                platon = int(base._dialog_active(chat_id))
            except Exception:
                pass
        registry.touch(user, chat_id, event, command=command or callback, platon=platon,
                       model_export=int(command in {"/model", "/модель"} or callback == "send_model"))
        admin = int(user.get("id") or chat_id or 0) in admins
        if admin and command in {"/users", "/users_today", "/users_week", "/user"}:
            if command == "/user":
                try:
                    row = registry.get(int(arg))
                except ValueError:
                    row = None
                _send(base.core, chat_id, _detail(row) if row else "Пользователь не найден. Формат: <code>/user 123456789</code>")
                return
            page = max(1, int(arg)) if command == "/users" and arg.isdigit() else 1
            since = int(time.time()) - (86400 if command == "/users_today" else 7*86400) if command != "/users" else None
            title = {"/users": "Пользователи Платона", "/users_today": "Активные за сутки",
                     "/users_week": "Активные за 7 дней"}[command]
            rows = registry.list(since=since, offset=(page-1)*10)
            total, day, week, month = registry.stats()
            lines = [f"<b>{title}</b>\nВсего {total} · сутки {day} · 7 дней {week} · 30 дней {month}"]
            lines.extend(_line((page-1)*10+i+1, row) for i, row in enumerate(rows))
            if not rows:
                lines.append("Записей нет.")
            if command == "/users":
                lines.append(f"Страница {page}. Следующая: <code>/users {page+1}</code>")
            _send(base.core, chat_id, "\n\n".join(lines))
            return
        original(update)
        if admin and command == "/status":
            total, day, week, month = registry.stats()
            _send(base.core, chat_id, f"<b>Реестр пользователей</b>\nВсего: <b>{total}</b>\n"
                                      f"Сутки: <b>{day}</b> · 7 дней: <b>{week}</b> · 30 дней: <b>{month}</b>")

    base.core._telegram_handle_update = handle

    @base.app.on_event("startup")
    def backfill() -> None:
        # Сначала — история с ядра. Таблица живёт на диске Render и умирает с
        # каждой выкаткой, а реестр ядра лежит в смонтированном томе: без этого
        # «сколько у нас пользователей» отвечает «сколько пришло с четверга».
        restore_from_core(base, registry)
        state = Path(os.getenv("PLATON_STATE_DIR", "") or root/"data"/"platon_state")
        for chat_id in _state_ids(state):
            if registry.get(chat_id):
                continue
            user: dict[str, Any] = {"id": chat_id}
            try:
                reply = base.core._telegram_api("getChat", {"chat_id": chat_id}) or {}
                data = reply.get("result") or {}
                user.update({"username": data.get("username") or "",
                             "first_name": data.get("first_name") or data.get("title") or "",
                             "last_name": data.get("last_name") or ""})
            except Exception:
                pass
            registry.touch(user, chat_id, "", source="backfill")

    base._TELEGRAM_USER_REGISTRY_INSTALLED = True
    base._TELEGRAM_USER_REGISTRY = registry
    return registry
