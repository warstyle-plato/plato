from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from desktop_reference_pack import canonical


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("База создана более новой версией DevelopAid")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reference_packs (
                    version TEXT PRIMARY KEY, received_at TEXT NOT NULL,
                    source TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    reference_version TEXT NOT NULL REFERENCES reference_packs(version),
                    body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                    revision INTEGER NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_history (
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    revision INTEGER NOT NULL,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                    name TEXT NOT NULL, saved_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, revision));
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def put_pack(self, pack: dict, source: str) -> None:
        body = canonical(pack)
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO reference_packs VALUES (?, ?, ?, ?)",
                       (pack["version"], now(), source, body))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('active_pack', ?)",
                       (pack["version"],))

    def pack(self, version: str | None = None) -> dict | None:
        with self.connection() as db:
            if version is None:
                current = db.execute("SELECT value FROM settings WHERE key='active_pack'").fetchone()
                if not current:
                    return None
                version = current[0]
            row = db.execute("SELECT * FROM reference_packs WHERE version=?", (version,)).fetchone()
        if not row:
            raise KeyError("Версия справочников не найдена")
        return {"pack": json.loads(row["body"]), "received_at": row["received_at"],
                "source": row["source"]}

    def add_snapshot(self, body: dict, reference_version: str) -> dict:
        snapshot_id = uuid.uuid4().hex
        record = {**body, "snapshot_id": snapshot_id, "reference_version": reference_version}
        serialized = canonical(record)
        with self.connection() as db:
            db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                       (snapshot_id, now(), reference_version, serialized))
        return record

    def snapshot(self, snapshot_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT body FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError("Расчёт не найден")
        return json.loads(row[0])

    def save_project(self, name: str, snapshot_id: str, project_id: str | None = None,
                     revision: int = 0) -> dict:
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError("Название проекта: от 1 до 200 символов")
        self.snapshot(snapshot_id)
        stamp = now()
        with self.connection() as db:
            if project_id:
                cursor = db.execute(
                    "UPDATE projects SET name=?, snapshot_id=?, revision=revision+1, updated_at=? "
                    "WHERE id=? AND revision=?", (name, snapshot_id, stamp, project_id, revision))
                if cursor.rowcount != 1:
                    raise Conflict("Проект изменён в другом окне. Откройте его заново или сохраните копию.")
                revision += 1
            else:
                project_id, revision = uuid.uuid4().hex, 1
                db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
                           (project_id, name, snapshot_id, revision, stamp))
            db.execute("INSERT INTO project_history VALUES (?, ?, ?, ?, ?)",
                       (project_id, revision, snapshot_id, name, stamp))
        return {"id": project_id, "name": name, "snapshot_id": snapshot_id,
                "revision": revision, "updated_at": stamp}

    def projects(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY updated_at DESC")]

    def history(self, project_id: str) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM project_history WHERE project_id=? ORDER BY revision DESC", (project_id,))]
