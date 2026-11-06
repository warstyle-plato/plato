"""Owner-authorized Telegram group scopes, separate from legacy chat metadata.

Only the core stores these grants. A bot transport signature, subscription or
Telegram user ID cannot mint one. Key rotation invalidates every old signature.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile


ACTIONS = ("daily", "photo", "sales:report", "sales:reply", "sales:delivered", "sales:send", "status")


class AccessDenied(ValueError):
    pass


def _signature(grant: dict, owner_key: str) -> str:
    payload = json.dumps(grant, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(owner_key.encode(), ("plato-site-chat-v1\n" + payload).encode(), hashlib.sha256).hexdigest()


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save(path: Path, grants: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(grants, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _current_state(path: Path, owner_key: str) -> dict:
    if not owner_key:
        if path.exists() and load(path):
            _save(path, {})
        raise AccessDenied("Ключ администратора не настроен; доступ групп закрыт.")
    key_id = hmac.new(owner_key.encode(), b"plato-site-chat-key-generation-v1", hashlib.sha256).hexdigest()
    state = load(path)
    if state.get("_key_id") != key_id or not isinstance(state.get("_generation"), str):
        # Observing rotation retires the previous generation permanently. Going
        # back to a former key must not silently revive its old authorizations.
        state = {"_key_id": key_id, "_generation": secrets.token_hex(16)}
        _save(path, state)
    return state


def project(grants: dict, owner_key: str, chat_id: int, action: str) -> str:
    entry = grants.get(str(chat_id))
    if not owner_key or chat_id >= 0 or not isinstance(entry, dict):
        raise AccessDenied("Группа не авторизована владельцем в закрытом кабинете.")
    grant = entry.get("grant")
    if (not isinstance(grant, dict) or grant.get("version") != 1
            or not grants.get("_generation") or grant.get("generation") != grants["_generation"]
            or grant.get("chat_id") != chat_id or not isinstance(grant.get("project"), str)
            or not grant["project"] or not isinstance(grant.get("actions"), list)
            or action not in grant["actions"]
            or not hmac.compare_digest(str(entry.get("signature") or "").encode("utf-8"),
                                       _signature(grant, owner_key).encode("ascii"))):
        raise AccessDenied("Доступ группы отозван или требует повторной авторизации владельцем.")
    return grant["project"]


def authorize(path: Path, owner_key: str, chat_id: int, name: str) -> None:
    if not owner_key or chat_id >= 0 or not name:
        raise AccessDenied("Укажите проект и отрицательный Telegram ID группы.")
    with locked(path):
        grants = _current_state(path, owner_key)
        grant = {"version": 1, "generation": grants["_generation"], "chat_id": chat_id,
                 "project": name, "actions": list(ACTIONS)}
        grants[str(chat_id)] = {"grant": grant, "signature": _signature(grant, owner_key)}
        _save(path, grants)


def revoke(path: Path, chat_id: int, name: str) -> None:
    with locked(path):
        grants = load(path)
        entry = grants.get(str(chat_id)) or {}
        if (entry.get("grant") or {}).get("project") != name:
            raise AccessDenied("У группы нет разрешения на указанный проект.")
        grants.pop(str(chat_id), None)
        _save(path, grants)


@contextmanager
def access(path: Path, owner_key: str, chat_id: int, action: str, expected_project: str = ""):
    # Revoke and data operations share the cross-worker lock. An accepted
    # operation finishes before revocation returns; later operations fail.
    with locked(path):
        name = project(_current_state(path, owner_key), owner_key, chat_id, action)
        if expected_project and expected_project != name:
            raise AccessDenied("Проект запроса не совпадает с разрешением группы.")
        yield name
