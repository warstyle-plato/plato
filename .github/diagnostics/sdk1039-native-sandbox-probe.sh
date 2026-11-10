#!/bin/sh
set -eu
cd /app
exec python -I -B - <<'PLATO_SDK1039_FIXED_PILOT'
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


ACCOUNT_CHILD = r'''
import contextlib,io,json,os
from pathlib import Path
result={"schema":"sdk_operator_account_v2","status":"account_probe_failed",
"auth_ready":False,"auth_mode_chatgpt":False,"owner_identity_confirmed":False,
"model_turns_started":0,"queue_written":False,"refresh_token_requested":False}
try:
    # No SDK/child log or account identifier is copied to the operator receipt.
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        from scripts.plato_dispatcher.runtime import SDKAdapter,AuthRequired
        from scripts.plato_dispatcher.store import SafeError
        try:
            with SDKAdapter(Path('/workspace'),Path('/root/.codex/plato-state')) as adapter:
                account=adapter.client.account(refresh_token=False).account
                account=getattr(account,'root',account)
                result.update(auth_ready=account is not None,
                    auth_mode_chatgpt=getattr(account,'type',None)=='chatgpt',status='account_checked')
        except AuthRequired:result['status']='auth_required'
        except SafeError as exc:
            allowed={'private_workspace_required','host_configuration_blocked','private_permissions_required','sdk_version_mismatch'}
            result['status']=exc.code if exc.code in allowed else 'account_probe_failed'
except BaseException:pass
print(json.dumps(result,sort_keys=True))
'''


def account_check(preflight=None, launcher=subprocess.Popen):
    result = {"schema": "sdk_operator_account_v2", "status": "inventory_gate_stop",
        "auth_ready": False, "auth_mode_chatgpt": False, "owner_identity_confirmed": False,
        "model_turns_started": 0, "queue_written": False, "refresh_token_requested": False,
        "render_commit_live_verified": False, "whole_image_identity_verified": False}
    gate = inventory("postdeploy") if preflight is None else preflight
    result["inventory"] = gate
    if gate.get("postdeploy_inventory_admission") is not True:
        return result
    process = None
    try:
        process = launcher([sys.executable, "-B", "-c", ACCOUNT_CHILD], cwd="/app",
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True)
        raw, _ = process.communicate(timeout=30)
        if process.returncode != 0 or len(raw) > 4096:
            raise ValueError("account_protocol")
        child = json.loads(raw)
        keys = {"schema", "status", "auth_ready", "auth_mode_chatgpt", "owner_identity_confirmed",
                "model_turns_started", "queue_written", "refresh_token_requested"}
        statuses = {"account_checked", "auth_required", "private_workspace_required",
                    "host_configuration_blocked", "private_permissions_required",
                    "sdk_version_mismatch", "account_probe_failed"}
        if not isinstance(child, dict) or set(child) != keys or child["schema"] != result["schema"] or child["status"] not in statuses:
            raise ValueError("account_protocol")
        if any(type(child[k]) is not bool for k in ("auth_ready", "auth_mode_chatgpt", "owner_identity_confirmed", "queue_written", "refresh_token_requested")):
            raise ValueError("account_protocol")
        if type(child["model_turns_started"]) is not int or child["model_turns_started"] != 0 or any(child[k] for k in ("owner_identity_confirmed", "queue_written", "refresh_token_requested")):
            raise ValueError("account_protocol")
        result.update(child)
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        result["status"] = "account_probe_timeout"
    except Exception:
        result["status"] = "account_probe_failed"
    return result


def main(phase):
    try:
        value = account_check() if phase == "account" else inventory(phase)
    except Exception:
        value = {"status": "operator_check_failed", "model_turns_started": 0,
                 "queue_written": False, "owner_identity_confirmed": False}
    print(json.dumps(value, sort_keys=True))
    return 0 if value.get("status") in ("inventory_pass", "account_checked", "auth_required") else 2


"""Fixed three-request admission; only the already running native serve executes turns."""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import time

checks = sys.modules[__name__]

APP = Path('/app')
WORKSPACE = Path('/workspace')
HOME = Path('/root/.codex')
STATE = HOME / 'plato-state'
CHECKPOINT = STATE / 'sdk1039-pilot.json'
LOCK = STATE / 'sdk1039-pilot.lock'
MARKER = WORKSPACE / '.plato-sdk1039-sandbox-probe'
TASK = 'sdk1039-fixed-synthetic-pilot-v1'
REQUESTS = tuple(f'sdk1039-fixed-synthetic-{n}-v1' for n in (1, 2, 3))
ANSWER = 'PLATO_SYNTHETIC_CONTINUITY_OK'
PROMPTS = (
    'Reply with exactly PLATO_SYNTHETIC_CONTINUITY_OK. Do not use tools.',
    'Reply with the exact token from my previous message. Do not use tools.',
    'Reply with the exact token from my first message. Do not use tools.',
)
STAGES = {'new', 'await_first', 'first_complete', 'await_second',
          'before_complete', 'await_third', 'complete', 'stopped'}
STEP = 'private_layout'


def step(value):
    global STEP
    STEP = value


class Stop(Exception):
    pass


def require(value):
    if not value:
        raise Stop()


def digest(salt, value):
    return hashlib.sha256(bytes.fromhex(salt) + value.encode()).hexdigest()


def save(cp):
    """Atomic private checkpoint; never follow or overwrite an unknown object."""
    checks._private_directory(STATE)
    if checks._exists(CHECKPOINT):
        checks._read(CHECKPOINT, 8192, private=True)
    temporary = STATE / '.sdk1039-pilot-checkpoint.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        raw = (json.dumps(cp, sort_keys=True) + '\n').encode()
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        os.replace(temporary, CHECKPOINT)
        parent = checks._open(STATE, directory=True, private=True)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        os.close(fd)
        # Only the O_EXCL-created temporary owned by this invocation.
        if checks._exists(temporary):
            temporary.unlink()


def load():
    if not checks._exists(CHECKPOINT):
        return None
    raw, _ = checks._read(CHECKPOINT, 8192, private=True)
    cp = json.loads(raw)
    require(isinstance(cp, dict) and set(cp) ==
            {'schema', 'stage', 'salt', 'host_before', 'host_after', 'thread', 'turns',
             'native_sandbox_verified', 'external_render_restart_verified'})
    require(cp['schema'] == 1 and cp['stage'] in STAGES)
    require(type(cp['salt']) is str and len(bytes.fromhex(cp['salt'])) == 32)
    require(cp['external_render_restart_verified'] is False)
    require(cp['native_sandbox_verified'] is True)
    require(isinstance(cp['turns'], list) and len(cp['turns']) <= 3)
    require(all(type(s) is str and len(s) == 64 and bytes.fromhex(s) for s in cp['turns']))
    require(cp['thread'] is None or (type(cp['thread']) is str and len(cp['thread']) == 64))
    for host in (cp['host_before'], cp['host_after']):
        require(host is None or (type(host) is dict and set(host) == {'pid', 'start'}
                and all(type(host[k]) is int and host[k] > 0 for k in host)))
    require(cp['host_before'] is not None)
    if cp['stage'] in {'before_complete', 'complete'}:
        require(len(cp['turns']) == (2 if cp['stage'] == 'before_complete' else 3))
    return cp


def native_host():
    """Observe the fixed native host, never launch a second worker."""
    expected = ['-m', 'scripts.plato_dispatcher', '--store-dir', str(STATE),
                '--workspace', str(WORKSPACE), 'serve', '--poll-seconds', '5']
    found = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            args = [v.decode() for v in args if v]
            if args[1:] != expected:
                continue
            require(entry.stat().st_uid == os.getuid())
            require((entry / 'exe').resolve() == Path(sys.executable).resolve())
            require((entry / 'cwd').resolve() == APP)
            data = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            found.append({'pid': int(entry.name), 'start': int(data[19])})
        except (FileNotFoundError, ProcessLookupError):
            continue
    require(len(found) == 1)
    return found[0]


def isolated(command, *, timeout=20, cwd=WORKSPACE):
    """Only no-model CLI probes; timeout cannot stop the native serve."""
    from scripts.plato_dispatcher.runtime import ENV_ALLOW
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOW}
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        raw = bytearray()
        until = time.monotonic() + timeout
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = until - time.monotonic()
                require(remaining > 0)
                if not ready.select(remaining):
                    raise Stop()
                chunk = os.read(process.stdout.fileno(), min(4096, 32769-len(raw)))
                if not chunk:
                    require(process.wait(timeout=max(0.01, until-time.monotonic())) == 0)
                    return bytes(raw)
                raw.extend(chunk)
                require(len(raw) <= 32768)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    finally:
        process.stdout.close()


# This code performs no SDK/account/model/network operation. O_EXCL prevents
# touching existing objects; on unexpected successful write it cleans its own inode.
DENIAL_PROBE = r'''
import errno,os,stat
p='/workspace/.plato-sdk1039-sandbox-probe'
try:
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
except OSError as e:
    print('DENIED' if e.errno in (errno.EACCES,errno.EPERM,errno.EROFS) else 'UNPROVEN')
else:
    try:
        own=os.fstat(fd); now=os.lstat(p)
        if (own.st_dev,own.st_ino)==(now.st_dev,now.st_ino) and stat.S_ISREG(now.st_mode):os.unlink(p)
    finally:os.close(fd)
    print('WRITABLE')
'''


def sandbox_check():
    from codex_cli_bin import bundled_codex_path
    from scripts.plato_dispatcher.runtime import OVERRIDES, host_preflight
    host_preflight(WORKSPACE, STATE)
    cli = str(bundled_codex_path())
    step('native_sandbox_version')
    require(isolated([cli, '--version']).strip() == b'codex-cli 0.167.0')
    step('native_sandbox_help')
    help_text = isolated([cli, 'sandbox', '--help'])
    require(b'Full command args to run under the Linux sandbox' in help_text
            and b'--config' in help_text and b'--sandbox-state-json' in help_text)
    # Control proves ordinary host permissions allow this exact synthetic write.
    step('native_sandbox_control')
    require(not checks._exists(MARKER))
    fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        own = os.fstat(fd)
        require((MARKER.lstat().st_dev, MARKER.lstat().st_ino) == (own.st_dev, own.st_ino))
        MARKER.unlink()
    finally:
        os.close(fd)
    command = [cli, 'sandbox', '-c', 'sandbox_mode="read-only"',
               '-c', 'approval_policy="never"']
    for override in OVERRIDES:
        command += ['-c', override]
    command += ['--', sys.executable, '-I', '-B', '-c', DENIAL_PROBE]
    step('native_sandbox_probe')
    require(isolated(command).strip() == b'DENIED')
    require(not checks._exists(MARKER))


def rows(db, cp, *, expected=None, active=False):
    """Private comparisons only; unknown/concurrent work always blocks admission."""
    tasks = db.execute('SELECT task_key,thread_id FROM tasks').fetchall()
    items = db.execute('SELECT request_id,task_key,input,digest,state,turn_id,result '
                       'FROM requests ORDER BY sequence').fetchall()
    require(len(items) <= 3 and len(tasks) == bool(items))
    if expected is not None:
        require(len(items) == expected)
    if tasks:
        require(tasks[0][0] == TASK)
    thread = tasks[0][1] if tasks else None
    turns = []
    for n, row in enumerate(items):
        request, task, content, content_hash, state, turn, result = row
        require(request == REQUESTS[n] and task == TASK and content == PROMPTS[n])
        require(content_hash == hashlib.sha256(PROMPTS[n].encode()).hexdigest())
        require(state == 'completed' or (active and n == len(items)-1 and state in {'queued','running'}))
        if state == 'completed':
            require(type(thread) is str and bool(thread) and type(turn) is str and bool(turn))
            require(type(result) is str and result.strip() == ANSWER)
            turns.append(digest(cp['salt'], turn))
    require(len(set(turns)) == len(turns))
    require(turns[:len(cp['turns'])] == cp['turns'])
    if cp['thread'] is not None:
        require(type(thread) is str and digest(cp['salt'], thread) == cp['thread'])
    return {'count': len(items), 'completed': len(turns), 'turns': turns,
            'thread': digest(cp['salt'], thread) if thread else None}


def inspect(store, cp, **kwargs):
    with store.connect() as db:
        db.execute('PRAGMA busy_timeout=0')
        return rows(db, cp, **kwargs)


def submit(store, cp, n, duplicate=False):
    # Store.submit's own BEGIN IMMEDIATE is the atomic admission boundary.
    # Check the entire real queue inside that same transaction, before insertion.
    native_connect = store.connect
    class Admission:
        def __init__(self, db): self.db = db
        def execute(self, sql, *args):
            result = self.db.execute(sql, *args)
            if sql == 'BEGIN IMMEDIATE':
                rows(self.db, cp, expected=n+1 if duplicate else n, active=duplicate)
            return result
    @contextlib.contextmanager
    def guarded():
        with native_connect() as db:
            yield Admission(db)
    store.connect = guarded
    try:
        value = store.submit(TASK, REQUESTS[n], PROMPTS[n], continuation=n > 0)
        require(value.get('created') is (not duplicate))
    finally:
        store.connect = native_connect


def observe(store, cp, count, host, deadline):
    while True:
        step('observe')
        require(time.monotonic() < deadline)
        require(native_host() == host)
        seen = inspect(store, cp, expected=count, active=True)
        if seen['completed'] == count:
            cp.update(turns=seen['turns'], thread=seen['thread'])
            return
        time.sleep(min(1, max(0, deadline-time.monotonic())))


def pilot(phase):
    step('source_inventory')
    require(phase in {'before', 'after'})
    require(not any(os.environ.get(k) for k in
                    ('PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH')))
    gate = checks.inventory('postdeploy')
    require(gate.get('postdeploy_inventory_admission') is True)
    require(gate.get('auth_cache_present') is True and gate.get('auth_cache_private') is True)
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from scripts.plato_dispatcher.store import Store
    from scripts.plato_dispatcher.runtime import host_preflight
    step('host_preflight')
    host_preflight(WORKSPACE, STATE)
    step('native_host')
    host = native_host()
    step('checkpoint')
    cp = load()
    store = Store(STATE)
    if cp is None:
        require(phase == 'before')
        cp = dict(schema=1, stage='new', salt=secrets.token_hex(32), host_before=host,
                  host_after=None, thread=None, turns=[], native_sandbox_verified=True,
                  external_render_restart_verified=False)
        step('queue_admission')
        inspect(store, cp, expected=0)
        sandbox_check()
        save(cp)
    require(cp['stage'] != 'stopped')
    # A crash or unknown outcome never authorizes another request.
    require(cp['stage'] in {'new', 'before_complete', 'complete'})
    try:
        step('auth_check')
        account = checks.account_check()
        require(account.get('auth_ready') is True and account.get('auth_mode_chatgpt') is True)
        if phase == 'before' and cp['stage'] in {'before_complete', 'complete'}:
            inspect(store, cp, expected=len(cp['turns']))
            return receipt(cp, 'before_complete')
        if phase == 'after' and cp['stage'] == 'complete':
            inspect(store, cp, expected=3)
            return receipt(cp, 'complete')
        deadline = time.monotonic() + 120
        if phase == 'before':
            require(cp['stage'] == 'new' and host == cp['host_before'])
            for n, pending, done in ((0, 'await_first', 'first_complete'),
                                     (1, 'await_second', 'before_complete')):
                step('before_submit')
                require(time.monotonic() < deadline)
                require(native_host() == host)
                inspect(store, cp, expected=n)
                cp['stage'] = pending
                save(cp)
                submit(store, cp, n)
                if n == 0:
                    submit(store, cp, n, duplicate=True)
                observe(store, cp, n+1, host, deadline)
                cp['stage'] = done
                save(cp)
        else:
            step('restart_gate')
            require(cp['stage'] == 'before_complete' and len(cp['turns']) == 2)
            require(host != cp['host_before'])
            inspect(store, cp, expected=2)
            # Root separately verifies actual Render restart/LIVE source metadata.
            # This local helper cannot certify those external facts.
            sandbox_check()
            cp.update(stage='await_third', host_after=host)
            save(cp)
            step('before_submit')
            require(time.monotonic() < deadline)
            submit(store, cp, 2)
            observe(store, cp, 3, host, deadline)
            cp['stage'] = 'complete'
            save(cp)
        inspect(store, cp, expected=len(cp['turns']))
        return receipt(cp, cp['stage'])
    except BaseException:
        cp['stage'] = 'stopped'
        save(cp)
        raise


def receipt(cp, status):
    return dict(status=status, completed_count=len(cp['turns']),
                auth_ready=True, auth_mode_chatgpt=True,
                same_thread_verified=cp['thread'] is not None,
                known_turns_verified=len(cp['turns']) == len(set(cp['turns'])),
                results_verified=True, queue_quiescent=True,
                native_sandbox_verified=cp['native_sandbox_verified'],
                native_restart_observed=cp['host_after'] is not None,
                external_render_restart_verified=False,
                automatic_retry_performed=False, duplicate_submit_verified=len(cp['turns']) >= 2)


def main(phase):
    step('private_layout')
    os.umask(0o077)
    fd = None
    try:
        checks._private_directory(HOME)
        checks._private_directory(STATE)
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        private = os.fstat(fd)
        require(stat.S_ISREG(private.st_mode) and private.st_uid == os.getuid()
                and not private.st_mode & 0o077 and private.st_nlink == 1)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # SDK/subprocess output is captured in existing account helper; the pilot
        # itself never invokes Adapter.start/run or a manual Dispatcher.
        value = pilot(phase)
        result = 0
    except BaseException:
        value = dict(status='pilot_stopped', automatic_retry_performed=False,
                     stop_step=STEP,
                     observation_timeout_kills_native_host=False)
        result = 2
    finally:
        if fd is not None:
            os.close(fd)
    print(json.dumps(value, sort_keys=True), flush=True)
    return result


def probe_main():
    """Independent zero-model prerequisite, without Store/account/checkpoint creation."""
    os.umask(0o077)
    step('source_inventory')
    try:
        require(not any(os.environ.get(k) for k in
                        ('PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH')))
        gate = checks.inventory('postdeploy')
        require(gate.get('postdeploy_inventory_admission') is True)
        sys.path.insert(0, str(APP))
        step('native_host')
        native_host()
        sandbox_check()
        value = dict(status='native_sandbox_pass', native_sandbox_verified=True,
                     model_turns_started=0, sdk_account_read_performed=False, queue_written=False)
        code = 0
    except BaseException:
        value = dict(status='native_sandbox_stop', native_sandbox_verified=False,
                     stop_step=STEP, model_turns_started=0,
                     sdk_account_read_performed=False, queue_written=False)
        code = 2
    print(json.dumps(value, sort_keys=True), flush=True)
    return code

raise SystemExit(probe_main())
PLATO_SDK1039_FIXED_PILOT
