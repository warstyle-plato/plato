"""Private durable queue. Never print its rows, inputs, results, or identifiers."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

MAX_INPUT_BYTES = 65536
MAX_REQUESTS = 512
MAX_RESULT_BYTES = 262144
STATES = ("queued", "running", "completed", "auth_required", "needs_attention", "failed")


class SafeError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def private_path(path: Path, *, directory: bool = False) -> None:
    s = path.lstat()
    expected = stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)
    if not expected or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise SafeError("private_permissions_required")
    if not directory and s.st_nlink != 1:
        raise SafeError("private_permissions_required")


def private_input(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077 or s.st_nlink != 1:
            raise SafeError("private_permissions_required")
        data = os.read(fd, MAX_INPUT_BYTES + 1)
        if not data or len(data) > MAX_INPUT_BYTES:
            raise SafeError("input_limit")
        return data.decode("utf-8")
    finally:
        os.close(fd)


def identifier(value: str) -> None:
    if not value or len(value) > 128 or not value.isprintable():
        raise SafeError("invalid_identifier")


class Store:
    def __init__(self, directory: Path):
        self.directory = Path(directory).absolute()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_path(self.directory, directory=True)
        self.path = self.directory / "queue.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        private_path(self.path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_key TEXT PRIMARY KEY, thread_id TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS requests (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE, task_key TEXT NOT NULL,
                    input TEXT NOT NULL, digest TEXT NOT NULL,
                    state TEXT NOT NULL, turn_id TEXT, result TEXT,
                    FOREIGN KEY(task_key) REFERENCES tasks(task_key));
                CREATE UNIQUE INDEX IF NOT EXISTS single_running
                    ON requests(state) WHERE state='running';
            """)

    def connect(self):
        # The containing directory and SQLite sidecars are private; never use WAL.
        private_path(self.path)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                private_path(sidecar)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return _Connection(db)

    @contextlib.contextmanager
    def worker(self):
        path = self.directory / "worker.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            private_path(path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SafeError("busy") from None
            yield
        finally:
            os.close(fd)

    def submit(self, task: str, request: str, content: str, *, continuation=False):
        identifier(task)
        identifier(request)
        raw = content.encode("utf-8")
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise SafeError("input_limit")
        digest = hashlib.sha256(raw).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM requests WHERE request_id=?", (request,)).fetchone()
            if old:
                if old["task_key"] != task or old["digest"] != digest:
                    raise SafeError("idempotency_conflict")
                return {"status": old["state"], "created": False}
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= MAX_REQUESTS:
                raise SafeError("queue_limit")
            known = db.execute("SELECT * FROM tasks WHERE task_key=?", (task,)).fetchone()
            if continuation:
                last = db.execute("SELECT state FROM requests WHERE task_key=? ORDER BY sequence DESC LIMIT 1", (task,)).fetchone()
                if not known or not known["thread_id"] or not last or last["state"] != "completed":
                    raise SafeError("continuation_blocked")
            elif known:
                raise SafeError("task_exists")
            else:
                db.execute("INSERT INTO tasks(task_key) VALUES (?)", (task,))
            db.execute("INSERT INTO requests(request_id,task_key,input,digest,state) VALUES (?,?,?,?, 'queued')", (request, task, content, digest))
            return {"status": "queued", "created": True}

    def status(self, task=None, request=None):
        with self.connect() as db:
            if request is not None or task is not None:
                clause, value = ("request_id", request) if request is not None else ("task_key", task)
                row = db.execute(f"SELECT r.*,t.thread_id FROM requests r JOIN tasks t USING(task_key) WHERE r.{clause}=? ORDER BY sequence DESC LIMIT 1", (value,)).fetchone()
                if not row:
                    return {"status": "missing", "exists": False}
                if row["state"] not in STATES:
                    raise SafeError("store_invalid")
                return {"status": row["state"], "exists": True, "thread_bound": row["thread_id"] is not None, "turn_known": row["turn_id"] is not None, "result_available": row["result"] is not None}
            counts = {s: 0 for s in STATES}
            for row in db.execute("SELECT state,COUNT(*) AS n FROM requests GROUP BY state"):
                counts[row["state"]] = row["n"]
            state = "needs_attention" if counts["needs_attention"] else "pending" if counts["running"] or counts["queued"] else "auth_required" if counts["auth_required"] else "idle"
            return {"status": state, "counts": counts}

    def recover(self):
        # Only call while holding worker flock: another live worker is never stolen.
        with self.connect() as db:
            db.execute("UPDATE requests SET state='needs_attention' WHERE state='running'")

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM requests WHERE state IN ('running','needs_attention')").fetchone():
                return None
            row = db.execute("SELECT r.*,t.thread_id FROM requests r JOIN tasks t USING(task_key) WHERE state='queued' ORDER BY sequence LIMIT 1").fetchone()
            if row and db.execute("UPDATE requests SET state='running' WHERE request_id=? AND state='queued'", (row["request_id"],)).rowcount == 1:
                return dict(row)
            return None

    def bind(self, request, thread):
        with self.connect() as db:
            row = db.execute("SELECT t.thread_id FROM tasks t JOIN requests r USING(task_key) WHERE r.request_id=? AND r.state='running'", (request,)).fetchone()
            if row is None or (row["thread_id"] is not None and row["thread_id"] != thread):
                raise SafeError("thread_mismatch")
            db.execute("UPDATE tasks SET thread_id=? WHERE task_key=(SELECT task_key FROM requests WHERE request_id=? AND state='running') AND thread_id IS NULL", (thread, request))

    def turn(self, request, turn):
        with self.connect() as db:
            db.execute("UPDATE requests SET turn_id=? WHERE request_id=? AND state='running'", (turn, request))

    def finish(self, request, state, result=None):
        if state not in STATES or state in ("running", "queued"):
            raise SafeError("invalid_state")
        if result is not None and len(result.encode("utf-8")) > MAX_RESULT_BYTES:
            state, result = "needs_attention", None
        with self.connect() as db:
            db.execute("UPDATE requests SET state=?,result=? WHERE request_id=? AND state IN ('running','needs_attention')", (state, result, request))
        return state

    def retry_auth(self, request):
        with self.connect() as db:
            changed = db.execute("UPDATE requests SET state='queued' WHERE request_id=? AND state='auth_required' AND turn_id IS NULL", (request,)).rowcount
            return {"status": "queued" if changed else "retry_blocked", "changed": bool(changed)}

    def attention(self, request):
        with self.connect() as db:
            row = db.execute("SELECT r.*,t.thread_id FROM requests r JOIN tasks t USING(task_key) WHERE request_id=? AND state='needs_attention'", (request,)).fetchone()
            return dict(row) if row else None


class _Connection:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.db.commit()
            else:
                self.db.rollback()
        finally:
            self.db.close()
