"""Owner-controlled, fixed-file configuration for qualified document links.

This stores an operator decision; it never establishes rollout completion.
The original positive protocol validator remains the reader's authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

import document_intake_protocol as protocol

PATH = "/internal/document-core-admission"
FILENAME = "document_core_admission.json"
LOCKNAME = ".document_core_admission.lock"
LIMIT = 4096
PUBLIC_ORIGINS = frozenset({"https://developaid.ru",
    "https://plato-development-investment-model.onrender.com"})
_AUTHORITY = object()
_SECURITY_HEADERS = frozenset({"host", "x-developaid-admin-key", "origin", "sec-fetch-site",
    "content-type", "content-encoding", "content-length", "transfer-encoding", "if-match",
    "if-none-match", "x-developaid-expected-commit", "x-developaid-expected-version"})


class ConfigHold(ValueError):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        message = ("Не удалось подтвердить результат сохранения настройки. "
                   "Не повторяйте запись до проверки владельцем." if code == "publication_unknown" else
                   "Настройка подтверждения ядра не применена. Требуется проверка владельца.")
        super().__init__(message)


def data_root(environ) -> Path:
    """Same data-root rule as health; no mkdir, resolve, source read or selector."""
    path = Path(environ.get("DEVELOPAID_DATA_DIR") or "data")
    return path if path.is_absolute() else Path.cwd() / path


def validate(raw: bytes, target: str) -> dict:
    """A valid stored false is a config/CAS state, never positive admission."""
    if type(raw) is not bytes or not raw or len(raw) > LIMIT:
        raise ConfigHold("configuration_invalid", 422)
    try:
        text = raw.decode("utf-8", "strict")
        value = protocol._closed_json(text)
        origin = protocol.target_origin(target)
        if origin not in PUBLIC_ORIGINS:
            raise ValueError
        if value.get("completed_rollout") is True:
            protocol.admitted_origin(text, target)
        elif (set(value) != {"schema", "origin", "protocol", "core_commit", "completed_rollout"}
                or type(value["schema"]) is not int or value["schema"] != 1
                or value["protocol"] != protocol.PROTOCOL
                or type(value["core_commit"]) is not str
                or not re.fullmatch(r"[0-9a-f]{40}", value["core_commit"])
                or type(value["origin"]) is not str or value["origin"] != origin
                or value["completed_rollout"] is not False):
            raise ValueError
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ConfigHold("configuration_invalid", 422) from None


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private_file(info):
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_size > LIMIT):
        raise ConfigHold("configuration_unsafe")


def _open_root(root: Path) -> int:
    """Open the existing operator-configured shared data root without aliases.

    Host ownership and trusted deployment-group write are legitimate across a
    container bind mount. Directory UID is not HTTP authority. World-write is
    refused except for system-owned sticky ancestors (e.g. /tmp), never the
    final root. Config, lock and temporary files retain private app ownership.
    """
    if (not root.is_absolute() or ".." in root.parts or len(str(root)) > 4096
            or any(ord(c) < 32 for c in str(root))):
        raise ConfigHold("configuration_unsafe")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    system_uid = os.fstat(fd).st_uid
    try:
        for part in root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if (info.st_mode & 0o002 and not
                    (info.st_uid == system_uid and info.st_mode & stat.S_ISVTX)):
                raise ConfigHold("configuration_unsafe")
        info = os.fstat(fd)
        if info.st_mode & 0o002:
            raise ConfigHold("configuration_unsafe")
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def _root_current(root: Path, directory: int):
    current = _open_root(root)
    try:
        old, new = os.fstat(directory), os.fstat(current)
        if (old.st_dev, old.st_ino) != (new.st_dev, new.st_ino):
            raise ConfigHold("configuration_changed")
    finally:
        os.close(current)


def _read(directory: int) -> bytes | None:
    try:
        fd = os.open(FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        _private_file(before)
        pieces, count = [], 0
        while count <= LIMIT:
            piece = os.read(fd, LIMIT + 1 - count)
            if not piece:
                break
            pieces.append(piece)
            count += len(piece)
        after = os.fstat(fd)
        named = os.stat(FILENAME, dir_fd=directory, follow_symlinks=False)
        if count > LIMIT or _identity(before) != _identity(after) or _identity(after) != _identity(named):
            raise ConfigHold("configuration_changed")
        return b"".join(pieces)
    finally:
        os.close(fd)


def admission_raw(environ, root: Path, target: str) -> str:
    if protocol.ADMISSION_ENV in environ:
        try:
            return environ[protocol.ADMISSION_ENV]
        except KeyError:
            raise protocol.ProtocolHold("root_admission") from None
    directory = -1
    try:
        directory = _open_root(root)
        raw = _read(directory)
        if raw is None:
            raise ConfigHold("configuration_absent")
        validate(raw, target)
        _root_current(root, directory)
        return raw.decode("utf-8", "strict")
    except (OSError, ConfigHold):
        raise protocol.ProtocolHold("root_admission") from None
    finally:
        if directory >= 0:
            os.close(directory)


class _Write:
    def __init__(self, expected, length):
        self.authority, self.expected, self.length = _AUTHORITY, expected, length


def preflight(raw_headers, *, require_admin, environ, scheme, query,
              local_mode, local_commit, local_version):
    """Only fixed server code supplies the native admin-check callable.

    Raw singleton Host is required; http/https are ordinary backend transport.
    The explicit owner key grants authority, never scheme, peer or forwarded
    claims. The operator uses verified public HTTPS and refuses redirects.
    """
    headers = {}
    for name, value in raw_headers:
        key = name.lower()
        if key.decode("ascii", "ignore") not in _SECURITY_HEADERS:
            continue
        try:
            key, value = key.decode("ascii"), value.decode("ascii")
        except UnicodeError:
            raise ConfigHold("request_headers", 400) from None
        if key in headers:
            raise ConfigHold("request_headers", 403 if key == "x-developaid-admin-key" else 400)
        if len(value) > LIMIT or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ConfigHold("request_headers", 400)
        headers[key] = value
    key = headers.get("x-developaid-admin-key", "")
    require_admin(key)
    if not key:
        raise ConfigHold("owner_key_required", 403)
    if protocol.ADMISSION_ENV in environ:
        raise ConfigHold("environment_has_priority")
    if (type(scheme) is not str or scheme not in {"http", "https"}
            or query != "" or headers.get("host") not in {"developaid.ru", "developaid.ru:443"}
            or type(local_mode) is not str or local_mode != ""):
        raise ConfigHold("core_realm")
    if (type(local_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", local_commit)
            or type(local_version) is not str or not local_version
            or headers.get("x-developaid-expected-commit") != local_commit
            or headers.get("x-developaid-expected-version") != local_version):
        raise ConfigHold("local_runtime_changed")
    if ("origin" in headers and headers["origin"] != "https://developaid.ru"
            or "sec-fetch-site" in headers and headers["sec-fetch-site"] not in {"same-origin", "none"}):
        raise ConfigHold("owner_realm", 403)
    if (headers.get("content-type") not in {"application/json", "application/json; charset=utf-8"}
            or headers.get("content-encoding", "identity") != "identity" or "transfer-encoding" in headers):
        raise ConfigHold("request_encoding", 415)
    length = headers.get("content-length")
    if length is not None and (not re.fullmatch(r"0|[1-9][0-9]{0,3}", length) or int(length) > LIMIT):
        raise ConfigHold("request_size", 413)
    initial, replace = headers.get("if-none-match"), headers.get("if-match")
    if initial == "*" and replace is None:
        expected = None
    elif initial is None and replace is not None and re.fullmatch(r'"[0-9a-f]{64}"', replace):
        expected = replace[1:-1]
    else:
        raise ConfigHold("configuration_precondition", 428)
    return _Write(expected, None if length is None else int(length))


async def request_bytes(request, prepared) -> bytes:
    if type(prepared) is not _Write or prepared.authority is not _AUTHORITY:
        raise ConfigHold("owner_key_required", 403)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > LIMIT:
            raise ConfigHold("request_size", 413)
        chunks.append(chunk)
    if prepared.length is not None and size != prepared.length:
        raise ConfigHold("request_size", 400)
    return b"".join(chunks)


@contextmanager
def _writer_lock(directory):
    fd = os.open(LOCKNAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
    try:
        _private_file(os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ConfigHold("configuration_busy") from None
        _lock_current(directory, fd)
        yield fd
    finally:
        os.close(fd)


def _lock_current(directory, lock):
    if _identity(os.fstat(lock)) != _identity(os.stat(LOCKNAME, dir_fd=directory, follow_symlinks=False)):
        raise ConfigHold("configuration_changed")


def _current(directory, target):
    raw = _read(directory)
    if raw is not None:
        validate(raw, target)
    return raw


def store(prepared, raw: bytes, *, root: Path, target: str, environ) -> dict:
    if type(prepared) is not _Write or prepared.authority is not _AUTHORITY:
        raise ConfigHold("owner_key_required", 403)
    if protocol.ADMISSION_ENV in environ:
        raise ConfigHold("environment_has_priority")
    value = validate(raw, target)
    canonical = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    directory, temporary, temporary_inode, publication_attempted = -1, None, None, False
    try:
        directory = _open_root(root)
        with _writer_lock(directory) as lock:
            previous = _current(directory, target)
            actual = None if previous is None else hashlib.sha256(previous).hexdigest()
            if actual != prepared.expected:
                raise ConfigHold("configuration_conflict")
            temporary = ".document_core_admission." + secrets.token_hex(16) + ".tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                info = os.fstat(fd)
                temporary_inode = (info.st_dev, info.st_ino)
                _private_file(info)
                remaining = memoryview(canonical)
                while remaining:
                    written = os.write(fd, remaining)
                    if not written:
                        raise OSError("Incomplete configuration write")
                    remaining = remaining[written:]
                os.fsync(fd)
                complete = os.fstat(fd)
                _private_file(complete)
                if complete.st_size != len(canonical):
                    raise ConfigHold("configuration_changed")
            finally:
                os.close(fd)
            _root_current(root, directory)
            _lock_current(directory, lock)
            if _current(directory, target) != previous:
                raise ConfigHold("configuration_changed")
            if _identity(os.stat(temporary, dir_fd=directory, follow_symlinks=False)) != _identity(complete):
                raise ConfigHold("configuration_changed")
            # A namespace syscall can publish yet report an I/O error. From
            # this boundary onward, neither failure nor cleanup proves absence.
            publication_attempted = True
            if previous is None:
                os.link(temporary, FILENAME, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                os.unlink(temporary, dir_fd=directory)
            else:
                os.replace(temporary, FILENAME, src_dir_fd=directory, dst_dir_fd=directory)
            temporary = None
            os.fsync(directory)
            if _current(directory, target) != canonical:
                raise ConfigHold("configuration_changed")
            _root_current(root, directory)
            _lock_current(directory, lock)
            return {"schema": 1, "stored": True, "sha256": hashlib.sha256(canonical).hexdigest()}
    except ConfigHold:
        if publication_attempted:
            raise ConfigHold("publication_unknown") from None
        raise
    except OSError:
        raise ConfigHold("publication_unknown" if publication_attempted else "configuration_hold") from None
    finally:
        if directory >= 0:
            if temporary is not None and temporary_inode is not None and not publication_attempted:
                try:
                    info = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == temporary_inode:
                        os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass
            os.close(directory)
