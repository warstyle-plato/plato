"""Private, disk-backed management-report jobs shared by application workers.

The caller authenticates every admission/poll and supplies an opaque owner
binding. Tickets are identifiers, never access credentials. No request key,
session, project name or exception detail is persisted in job metadata.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

TICKET = re.compile(r"^[0-9a-f]{32}$")
TTL_SECONDS = 3600
MAX_ACTIVE = 2
MAX_RETAINED = 64
MAX_RESULT_BYTES = 16 * 1024 * 1024
FAILED = "Не удалось собрать сводку. Повторите запрос."
MISSING = "Сборка сводки не найдена или срок её хранения истёк. Запросите сводку снова."


class JobProblem(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _claim(handle, *, wait: bool = True):
    # Keep ordinary imports usable by the Windows client. The production job
    # service requires POSIX locks; unavailable platforms fail closed on use.
    try:
        import fcntl
    except ImportError:
        raise JobProblem(503, "Фоновая сборка сводки недоступна в этой среде.") from None
    fcntl.flock(handle, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))


def owner_binding(secret: str, session: str, profile: str) -> str:
    """A rotation invalidates both admission rights and old job ownership."""
    if not secret:
        raise JobProblem(403, "Доступ к сводке закрыт.")
    value = json.dumps(["management-report-v1", session, profile], ensure_ascii=False)
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, ticket: str, suffix: str) -> Path:
        if not TICKET.fullmatch(ticket):
            raise JobProblem(404, MISSING)
        path = (self.root / f"{ticket}.{suffix}").resolve()
        if path.parent != self.root.resolve():
            raise JobProblem(404, MISSING)
        return path

    def _open_lock(self, path: Path):
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        return os.fdopen(fd, "a+b")

    @contextlib.contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._open_lock(self.root / ".lock") as handle:
            _claim(handle)
            yield

    def _write(self, path: Path, data: bytes):
        fd, temp = tempfile.mkstemp(prefix=".write-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)

    def _meta(self, ticket: str) -> dict | None:
        try:
            return json.loads(self._path(ticket, "json").read_text())
        except FileNotFoundError:
            return None

    def _save(self, meta: dict):
        self._write(self._path(meta["ticket"], "json"), json.dumps(meta).encode())

    def _busy(self, ticket: str) -> bool:
        with self._open_lock(self._path(ticket, "run")) as handle:
            try:
                _claim(handle, wait=False)
            except BlockingIOError:
                return True
        return False

    def _entries(self) -> list[dict]:
        entries = []
        for path in self.root.glob("*.json"):
            if not TICKET.fullmatch(path.stem):
                continue
            meta = self._meta(path.stem)
            if meta is not None:
                entries.append(meta)
        return entries

    def _delete(self, meta: dict):
        for suffix in ("json", "result", "run"):
            self._path(meta["ticket"], suffix).unlink(missing_ok=True)

    def _sweep(self, now: float) -> list[dict]:
        for path in self.root.iterdir():
            # Interrupted atomic writes have no manifest; expire their private
            # bytes too. A live writer/claim is never collected.
            if now - path.stat().st_mtime <= TTL_SECONDS:
                continue
            if path.name.startswith(".write-"):
                path.unlink(missing_ok=True)
            elif (path.suffix in (".run", ".result") and TICKET.fullmatch(path.stem)
                  and self._meta(path.stem) is None and not self._busy(path.stem)):
                path.unlink(missing_ok=True)
        kept = []
        for meta in self._entries():
            if now - meta["created"] > TTL_SECONDS and not self._busy(meta["ticket"]):
                self._delete(meta)
            else:
                kept.append(meta)
        # Active workers retain their lock/slot, even after the response TTL.
        # Never delete a lock held by another process and create a second inode.
        for meta in sorted(kept, key=lambda item: item["created"]):
            if len(kept) < MAX_RETAINED:
                break
            if not self._busy(meta["ticket"]):
                self._delete(meta)
                kept.remove(meta)
        return kept

    def _state(self, meta: dict) -> dict:
        ticket = meta["ticket"]
        if time.time() - meta["created"] > TTL_SECONDS:
            raise JobProblem(404, MISSING)
        if meta["state"] == "done":
            result = json.loads(self._path(ticket, "result").read_text())
            return {"pending": False, "ticket": ticket, **result}
        if meta["state"] == "error" or not self._busy(ticket):
            raise JobProblem(500, FAILED)
        return {"pending": True, "ticket": ticket,
                "detail": "Собираю сводку. Можно оставить страницу открытой."}

    def poll(self, ticket: str, owner: str, profile: str) -> dict:
        with self._locked():
            meta = self._meta(ticket)
            if meta is None or not hmac.compare_digest(meta["owner"], owner) or meta["profile"] != profile:
                raise JobProblem(404, MISSING)
            return self._state(meta)

    def start(self, owner: str, profile: str, params: dict,
              builder: Callable[[], dict], ticket: str = "") -> dict:
        if ticket and not TICKET.fullmatch(ticket):
            raise JobProblem(400, "Неверный номер сборки сводки.")
        fingerprint = hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._locked():
            if ticket:
                meta = self._meta(ticket)
                if meta is not None:
                    if not hmac.compare_digest(meta["owner"], owner) or meta["profile"] != profile:
                        raise JobProblem(404, MISSING)
                    if meta["request"] != fingerprint:
                        raise JobProblem(409, "Эта сборка относится к другому запросу сводки.")
                    return self._state(meta)
            now = time.time()
            entries = self._sweep(now)
            active = [meta for meta in entries if self._busy(meta["ticket"])]
            for meta in active:
                if (meta["state"] == "pending" and meta["owner"] == owner and meta["profile"] == profile
                        and meta["request"] == fingerprint and now - meta["created"] <= TTL_SECONDS):
                    return self._state(meta)
            if len(active) >= MAX_ACTIVE or len(entries) >= MAX_RETAINED:
                raise JobProblem(429, "Сервер уже собирает сводки. Повторите запрос чуть позже.")
            ticket = ticket or secrets.token_hex(16)
            run_lock = self._open_lock(self._path(ticket, "run"))
            _claim(run_lock, wait=False)
            meta = {"ticket": ticket, "owner": owner, "profile": profile,
                    "request": fingerprint, "created": now, "state": "pending"}
            try:
                self._save(meta)
                threading.Thread(target=self._build, args=(meta, builder, run_lock),
                                 name="management-report", daemon=True).start()
            except Exception:
                run_lock.close()
                meta["state"] = "error"
                self._save(meta)
                raise JobProblem(503, FAILED) from None
            return {"pending": True, "ticket": ticket,
                    "detail": "Собираю сводку. Можно оставить страницу открытой."}

    def _build(self, meta: dict, builder: Callable[[], dict], run_lock):
        try:
            data = json.dumps(builder(), ensure_ascii=False, allow_nan=False).encode()
            if len(data) > MAX_RESULT_BYTES:
                raise ValueError("report result too large")
            with self._locked():
                self._write(self._path(meta["ticket"], "result"), data)
                meta["state"] = "done"
                self._save(meta)
        except Exception as exc:
            # Exceptions can contain source paths, client names or financial data.
            logging.getLogger(__name__).error("Management report job failed (%s)", type(exc).__name__)
            try:
                with self._locked():
                    meta["state"] = "error"
                    self._save(meta)
            except Exception:
                # Even a failed disk must not cause threading's traceback hook
                # to publish the original exception's private source details.
                logging.getLogger(__name__).error("Cannot persist management report job failure")
        finally:
            with contextlib.suppress(OSError):
                run_lock.close()
