from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TelegramUserRegistry:
    """Persistent Telegram user registry backed by SQLite.

    A connection is opened per operation so multiple uvicorn workers can share
    one database on the persistent ``data`` volume. WAL and UPSERT keep writes
    short and atomic.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS telegram_users (
                        user_id INTEGER PRIMARY KEY,
                        chat_id INTEGER NOT NULL DEFAULT 0,
                        username TEXT NOT NULL DEFAULT '',
                        first_name TEXT NOT NULL DEFAULT '',
                        last_name TEXT NOT NULL DEFAULT '',
                        language_code TEXT NOT NULL DEFAULT '',
                        is_bot INTEGER NOT NULL DEFAULT 0,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        callback_count INTEGER NOT NULL DEFAULT 0,
                        platon_count INTEGER NOT NULL DEFAULT 0,
                        model_export_count INTEGER NOT NULL DEFAULT 0,
                        calculation_count INTEGER NOT NULL DEFAULT 0,
                        last_action TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_telegram_users_last_seen
                    ON telegram_users(last_seen DESC);
                    """
                )
            self._schema_ready = True

    def record(
        self,
        profile: dict[str, Any],
        *,
        chat_id: int = 0,
        seen_at: str | None = None,
        messages: int = 0,
        callbacks: int = 0,
        platon: int = 0,
        model_exports: int = 0,
        calculations: int = 0,
        last_action: str = "",
    ) -> None:
        user_id = int(profile.get("id") or 0)
        if user_id <= 0:
            return
        timestamp = seen_at or self.utc_now()
        self.ensure_schema()
        values = {
            "user_id": user_id,
            "chat_id": int(chat_id or user_id),
            "username": str(profile.get("username") or "").strip(),
            "first_name": str(profile.get("first_name") or "").strip(),
            "last_name": str(profile.get("last_name") or "").strip(),
            "language_code": str(profile.get("language_code") or "").strip(),
            "is_bot": 1 if profile.get("is_bot") else 0,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "message_count": max(0, int(messages)),
            "callback_count": max(0, int(callbacks)),
            "platon_count": max(0, int(platon)),
            "model_export_count": max(0, int(model_exports)),
            "calculation_count": max(0, int(calculations)),
            "last_action": str(last_action or "")[:120],
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_users (
                    user_id, chat_id, username, first_name, last_name,
                    language_code, is_bot, first_seen, last_seen,
                    message_count, callback_count, platon_count,
                    model_export_count, calculation_count, last_action
                ) VALUES (
                    :user_id, :chat_id, :username, :first_name, :last_name,
                    :language_code, :is_bot, :first_seen, :last_seen,
                    :message_count, :callback_count, :platon_count,
                    :model_export_count, :calculation_count, :last_action
                )
                ON CONFLICT(user_id) DO UPDATE SET
                    chat_id = CASE WHEN excluded.chat_id != 0 THEN excluded.chat_id ELSE telegram_users.chat_id END,
                    username = CASE WHEN excluded.username != '' THEN excluded.username ELSE telegram_users.username END,
                    first_name = CASE WHEN excluded.first_name != '' THEN excluded.first_name ELSE telegram_users.first_name END,
                    last_name = CASE WHEN excluded.last_name != '' THEN excluded.last_name ELSE telegram_users.last_name END,
                    language_code = CASE WHEN excluded.language_code != '' THEN excluded.language_code ELSE telegram_users.language_code END,
                    is_bot = excluded.is_bot,
                    last_seen = CASE WHEN excluded.last_seen > telegram_users.last_seen THEN excluded.last_seen ELSE telegram_users.last_seen END,
                    message_count = telegram_users.message_count + excluded.message_count,
                    callback_count = telegram_users.callback_count + excluded.callback_count,
                    platon_count = telegram_users.platon_count + excluded.platon_count,
                    model_export_count = telegram_users.model_export_count + excluded.model_export_count,
                    calculation_count = telegram_users.calculation_count + excluded.calculation_count,
                    last_action = CASE WHEN excluded.last_action != '' THEN excluded.last_action ELSE telegram_users.last_action END
                """,
                values,
            )

    def backfill(self, user_id: int, *, seen_at: str | None = None) -> None:
        self.record({"id": int(user_id)}, chat_id=int(user_id), seen_at=seen_at)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_users WHERE user_id = ?", (int(user_id),)
            ).fetchone()
        return dict(row) if row else None

    def list_users(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        active_since: str | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        sql = "SELECT * FROM telegram_users"
        params: list[Any] = []
        if active_since:
            sql += " WHERE last_seen >= ?"
            params.append(active_since)
        sql += " ORDER BY last_seen DESC, user_id ASC LIMIT ? OFFSET ?"
        params.extend([max(1, min(100, int(limit))), max(0, int(offset))])
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def count(self, *, active_since: str | None = None) -> int:
        self.ensure_schema()
        sql = "SELECT COUNT(*) FROM telegram_users"
        params: tuple[Any, ...] = ()
        if active_since:
            sql += " WHERE last_seen >= ?"
            params = (active_since,)
        with self._connect() as connection:
            return int(connection.execute(sql, params).fetchone()[0])

    def missing_profiles(self, *, limit: int = 50) -> list[int]:
        self.ensure_schema()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id FROM telegram_users
                WHERE username = '' AND first_name = '' AND last_name = ''
                ORDER BY last_seen DESC LIMIT ?
                """,
                (max(1, min(200, int(limit))),),
            ).fetchall()
        return [int(row[0]) for row in rows]
