#!/bin/sh
# Fixed private operator check; no file upload/helper installation.
if [ "${RENDER_SERVICE_ID:-}" != "srv-dbo2libm8hqs73fcuut0" ]; then
  printf '%s\n' '{"status":"wrong_service_or_unknown","expected_service":"plato-session-dispatcher-8qv0","inventory_executed":false}'
  exit 0
fi
if ! cd /app 2>/dev/null; then
  printf '%s\n' '{"status":"runtime_layout_unavailable","inventory_executed":false}'
  exit 0
fi
python -B - <<'PLATO_SDK_OPERATOR_PY'
"""Private fixed-purpose operator checks. No CLI paths or source imports for inventory."""
from __future__ import annotations

import contextlib
import hashlib
from importlib.metadata import PackageNotFoundError, version
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import sys
import time

# Generated only from git blobs at the two reviewed commits, never from the host.
SOURCES = {'target': {'source_sha': '70f47ed5764498b55e33f095903f0a24d44f23a6', 'files': {'scripts/plato_dispatcher/runtime.py': 'aec09c3d16b2cbfdf45ecff09cd5990062854eac9341df03fa3e9ee3acf5b66c', 'scripts/plato_dispatcher/store.py': 'bc8cb929bcb61e80efb467e5fbb4d537b450cb03e2d7348df7ae7f18554db821', 'scripts/plato_dispatcher/__main__.py': '0ea6f4dc228f7f50aa3890e9ff6601456c3efc06d04a68e7e6455c4ea8f46f81', 'scripts/plato_dispatcher/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'requirements.txt': '0d7ef2edb0c8ae184ebb155f7bde3daf87648c4fe9218d5a55f4a781faa4acb8', 'start-dispatcher.sh': 'ec2ae2166607dfbecad1873162ae8b9f44dbe26d84494331231022174c6220ac'}, 'build_source_files': {'scripts/plato_dispatcher_deploy/Dockerfile': '7ffe5ef8535d92fdd0f2f4491de54b8e305a92016b6c2a71802d5c69c7ba673c', 'scripts/plato_dispatcher_deploy/render.yaml': '7fb92dee53441eef654c504f8c6453841d8e19dbb46bca4db1700136292729dc'}}, 'previous': {'source_sha': 'dc4fb6577aacb6e9f2faa007c5afd8b71d306371', 'files': {'scripts/plato_dispatcher/runtime.py': '8f152b5455aa588b1ee837b3c757197a0663520d1f03afc21681602f88fbea62', 'scripts/plato_dispatcher/store.py': 'bc8cb929bcb61e80efb467e5fbb4d537b450cb03e2d7348df7ae7f18554db821', 'scripts/plato_dispatcher/__main__.py': '0ea6f4dc228f7f50aa3890e9ff6601456c3efc06d04a68e7e6455c4ea8f46f81', 'scripts/plato_dispatcher/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'requirements.txt': '0d7ef2edb0c8ae184ebb155f7bde3daf87648c4fe9218d5a55f4a781faa4acb8', 'start-dispatcher.sh': 'ec2ae2166607dfbecad1873162ae8b9f44dbe26d84494331231022174c6220ac'}, 'build_source_files': {'scripts/plato_dispatcher_deploy/Dockerfile': '7ffe5ef8535d92fdd0f2f4491de54b8e305a92016b6c2a71802d5c69c7ba673c', 'scripts/plato_dispatcher_deploy/render.yaml': '7fb92dee53441eef654c504f8c6453841d8e19dbb46bca4db1700136292729dc'}}}
SDK_VERSION = "0.167.0"
STATES = ("queued", "running", "completed", "auth_required", "needs_attention", "failed")
RUNTIME_FILES = frozenset((
    "scripts/plato_dispatcher/runtime.py", "scripts/plato_dispatcher/store.py",
    "scripts/plato_dispatcher/__main__.py", "scripts/plato_dispatcher/__init__.py",
    "requirements.txt", "start-dispatcher.sh",
))
MAX_DATABASE_BYTES = 16 * 1024 * 1024


def _signature(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink,
            s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _open(path: Path, directory=False, private=False):
    """No ancestor or final symlink follows; no blocking device/FIFO reads."""
    parts = path.absolute().parts
    if ".." in parts:
        raise ValueError("path_layout")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for i, name in enumerate(parts[1:]):
            last = i == len(parts) - 2
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not last or directory:
                flags |= os.O_DIRECTORY
            next_fd = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        s = os.fstat(fd)
        if not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)):
            raise ValueError("path_kind")
        if not directory and s.st_nlink != 1:
            raise ValueError("path_links")
        if private and (s.st_uid != os.getuid() or s.st_mode & 0o077):
            raise ValueError("private_permissions")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(path: Path, limit, private=False):
    fd = _open(path, private=private)
    try:
        before = os.fstat(fd)
        if before.st_size > limit:
            raise ValueError("file_limit")
        chunks, remaining = [], limit + 1
        while remaining:
            block = os.read(fd, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        data = b"".join(chunks)
        if len(data) > limit or _signature(before) != _signature(os.fstat(fd)):
            raise ValueError("file_changed")
        return data, _signature(before)
    finally:
        os.close(fd)


def _private_directory(path):
    fd = _open(path, directory=True, private=True)
    os.close(fd)


def _exists(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _sidecars(database):
    return any(_exists(Path(str(database) + suffix)) for suffix in ("-wal", "-shm", "-journal"))


def _code_identity(app):
    actual = {}
    for name in RUNTIME_FILES:
        try:
            data, _ = _read(app / name, 262144)
            actual[name] = hashlib.sha256(data).hexdigest()
        except (OSError, ValueError):
            actual[name] = None
    matched = [label for label, item in SOURCES.items()
               if set(item["files"]) == RUNTIME_FILES and item["files"] == actual]
    return matched[0] if len(matched) == 1 else None


def inventory(phase="predeploy", home=Path("/root/.codex"),
              workspace=Path("/workspace"), app=Path("/app"), package_version=version,
              configured_home=None):
    if phase not in ("predeploy", "postdeploy"):
        raise ValueError("invalid_phase")
    result = {
        "schema": "sdk_operator_inventory_v2", "phase": phase,
        "status": "inventory_unavailable", "read_only": True,
        "auth_content_read": False, "sdk_client_started": False,
        "model_turns_started": 0, "queue_written": False,
        "expected_target_source": SOURCES["target"]["source_sha"],
        "copied_runtime_file_count": len(RUNTIME_FILES), "code_source_known": False,
        "target_code_files_match": False, "observed_code_source": "unknown",
        "render_commit_live_verified": False, "whole_image_identity_verified": False,
        "package_versions_match": False, "host_home_selector_matches": False,
        "private_layout_valid": False,
        "auth_cache_present": False, "auth_cache_private": None,
        "queue_present": False, "queue_read": False, "counts": None,
        "queue_quiescent": False, "predeploy_inventory_admission": False,
        "postdeploy_inventory_admission": False, "owner_identity_confirmed": False,
    }
    try:
        selected = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) if configured_home is None else Path(configured_home)
        result["host_home_selector_matches"] = selected.absolute() == home.absolute()
        if not result["host_home_selector_matches"]:
            result["status"] = "host_home_selector_stop"
            return result
        label = _code_identity(app)
        result["code_source_known"] = label is not None
        result["observed_code_source"] = SOURCES[label]["source_sha"] if label else "unknown"
        result["target_code_files_match"] = label == "target"
        try:
            result["package_versions_match"] = all(package_version(p) == SDK_VERSION
                for p in ("openai-codex", "openai-codex-cli-bin"))
        except PackageNotFoundError:
            pass
        store = home / "plato-state"
        _private_directory(home)
        _private_directory(store)
        fd = _open(workspace, directory=True)
        os.close(fd)
        # _open rejected every symlink, so lexical absolute ancestry is enough.
        public = workspace.absolute()
        if any(public == p.absolute() or public in p.absolute().parents for p in (home, store)):
            raise ValueError("private_layout")
        result["private_layout_valid"] = True
        auth = home / "auth.json"
        result["auth_cache_present"] = _exists(auth)
        if result["auth_cache_present"]:
            # Metadata only: never open or read the authentication file.
            s = auth.lstat()
            result["auth_cache_private"] = bool(stat.S_ISREG(s.st_mode) and
                s.st_uid == os.getuid() and not s.st_mode & 0o077 and s.st_nlink == 1)
        database = store / "queue.sqlite3"
        result["queue_present"] = _exists(database)
        if not result["queue_present"]:
            result["status"] = "queue_absent_stop"
            return result
        if _sidecars(database):
            result["status"] = "queue_sidecar_stop"
            return result
        data, before = _read(database, MAX_DATABASE_BYTES, private=True)
        if len(data) < 100 or data[:16] != b"SQLite format 3\0" or data[18:20] != b"\x01\x01":
            result["status"] = "queue_format_stop"
            return result
        # Deserialize a bounded coherent read into an in-memory connection.
        # SQLite never opens the live database and cannot create any sidecar.
        db = sqlite3.connect(":memory:")
        try:
            db.deserialize(data)
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA query_only=ON")
            until = time.monotonic() + 3
            db.set_progress_handler(lambda: int(time.monotonic() > until), 1000)
            kinds = dict(db.execute("SELECT name,type FROM sqlite_schema WHERE name IN ('tasks','requests')"))
            if kinds != {"tasks": "table", "requests": "table"}:
                raise ValueError("queue_schema")
            required = {"tasks": {"task_key", "thread_id"},
                        "requests": {"task_key", "state", "turn_id", "result"}}
            for table, columns in required.items():
                actual = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
                if not columns <= actual:
                    raise ValueError("queue_schema")
            counts = {state: db.execute("SELECT COUNT(*) FROM requests WHERE state=?", (state,)).fetchone()[0]
                      for state in STATES}
            extras = {
                "unknown_state_count": db.execute("SELECT COUNT(*) FROM requests WHERE state IS NULL OR state NOT IN (?,?,?,?,?,?)", STATES).fetchone()[0],
                "task_count": db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                "bound_task_count": db.execute("SELECT COUNT(*) FROM tasks WHERE thread_id IS NOT NULL").fetchone()[0],
                "orphan_request_count": db.execute("SELECT COUNT(*) FROM requests r LEFT JOIN tasks t USING(task_key) WHERE t.task_key IS NULL").fetchone()[0],
                "completed_missing_evidence_count": db.execute("SELECT COUNT(*) FROM requests r JOIN tasks t USING(task_key) WHERE r.state='completed' AND (t.thread_id IS NULL OR r.turn_id IS NULL OR r.result IS NULL)").fetchone()[0],
            }
        finally:
            db.close()
        fd = _open(database, private=True)
        try:
            same = _signature(os.fstat(fd)) == before
        finally:
            os.close(fd)
        _private_directory(home)
        _private_directory(store)
        if not same or _sidecars(database):
            result["status"] = "queue_changed_stop"
            return result
        result.update(extras)
        result.update(queue_read=True, counts=counts)
        clear = (not any(counts[s] for s in ("queued", "running", "needs_attention", "auth_required"))
                 and not any(extras[k] for k in ("unknown_state_count", "orphan_request_count", "completed_missing_evidence_count")))
        result["queue_quiescent"] = clear
        safe = (clear and result["code_source_known"] and result["package_versions_match"]
                and result["auth_cache_private"] is not False)
        result["predeploy_inventory_admission"] = safe and phase == "predeploy"
        result["postdeploy_inventory_admission"] = safe and phase == "postdeploy" and result["target_code_files_match"]
        result["status"] = "inventory_pass" if (result["predeploy_inventory_admission"] or result["postdeploy_inventory_admission"]) else "inventory_stop"
        return result
    except (OSError, ValueError, sqlite3.Error, RuntimeError):
        result["status"] = "inventory_unavailable_stop"
        return result



def main(phase):
    try:
        value=inventory(phase)
    except Exception:
        value={"status":"operator_check_failed","model_turns_started":0,
               "queue_written":False,"owner_identity_confirmed":False}
    print(json.dumps(value,sort_keys=True))
    return 0 if value.get("status")=="inventory_pass" else 2

raise SystemExit(main('predeploy'))
PLATO_SDK_OPERATOR_PY
