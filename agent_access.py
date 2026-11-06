"""Server-owned identity and ACL metadata for Platon runs and documents.

Credentials stay in the request/worker only. Persistent records contain hashes,
never session tokens or administrator keys. No client-supplied role is trusted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets

from fastapi import HTTPException

COOKIE = "plato_owner"
BOT_CAPABILITY = object()
NONCE = re.compile(r"^[0-9a-f]{32}$")


def secret(directory: Path) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".owner-signing-key"
    try:
        value = path.read_bytes()
    except FileNotFoundError:
        # Linking a fully written temporary file publishes it atomically; a
        # second worker can never read a partially created signing key.
        tmp = directory / (".owner-key-" + secrets.token_hex(16))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(secrets.token_bytes(32))
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
        finally:
            tmp.unlink(missing_ok=True)
        value = path.read_bytes()
    if len(value) != 32:
        raise RuntimeError("Platon identity signing key is invalid")
    return value


def digest(directory: Path, value: str) -> str:
    return hmac.new(secret(directory), value.encode(), hashlib.sha256).hexdigest()


def browser_owner(directory: Path, cookie: str) -> tuple[str, str | None]:
    token, _, signature = str(cookie or "").partition(".")
    if re.fullmatch(r"[0-9a-f]{64}", token) and hmac.compare_digest(
            signature.encode(), digest(directory, "browser:" + token).encode()):
        return "browser:" + token, None
    token = secrets.token_hex(32)
    return "browser:" + token, token + "." + digest(directory, "browser:" + token)


@dataclass(frozen=True)
class Actor:
    owner: str
    surface: str
    private: bool
    acl: str
    # Transient credential, deliberately omitted from all metadata and repr.
    key: str = field(default="", repr=False, compare=False)

    def metadata(self) -> dict:
        return {"version": 1, "owner": self.owner, "surface": self.surface,
                "private": self.private, "acl": self.acl}


def write_json(path: Path, value) -> None:
    """Publish complete state with private filesystem permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + "." + secrets.token_hex(16) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, ensure_ascii=False)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def bind_bot(request, chat_id: int) -> None:
    # This capability is an object in Python memory, never accepted from HTTP.
    request.scope["plato_bot_actor"] = (BOT_CAPABILITY, int(chat_id))


def claim(directory: Path, trace_id: str, actor: Actor) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("access_" + trace_id + ".json")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Even the same owner cannot overwrite a running job with this ID.
        raise HTTPException(409, "Этот номер запроса уже используется. Повторите вопрос.")
    with os.fdopen(fd, "w") as out:
        json.dump(actor.metadata(), out)


def load(directory: Path, trace_id: str) -> dict:
    if not NONCE.fullmatch(trace_id):
        raise HTTPException(400, "Неверный идентификатор запроса.")
    try:
        data = json.loads((directory / ("access_" + trace_id + ".json")).read_text())
    except (OSError, ValueError):
        raise HTTPException(404, "Запрос не найден.")
    if not isinstance(data, dict) or data.get("version") != 1:
        raise HTTPException(404, "Запрос не найден.")
    return data


def public_reply_signature(directory: Path, slug: str, surface: str, text: str) -> str:
    # Domain separation also prevents reusing browser-cookie signatures here.
    message = json.dumps(["public-source-v1", slug, surface, text], ensure_ascii=False)
    return digest(directory, message)
