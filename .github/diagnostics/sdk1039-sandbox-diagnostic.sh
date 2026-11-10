#!/bin/sh
set -eu
cd /app
exec python -I -B - <<'PLATO_SDK1039_SANDBOX_DIAGNOSTIC'
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


from pathlib import Path
import os,sys
APP=Path("/app")
WORKSPACE=Path("/workspace")
STATE=Path("/root/.codex/plato-state")

class Stop(Exception):
    pass

def require(value):
    if not value:
        raise Stop()

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

"""One fixed zero-model sandbox rerun; only enum/boolean/count diagnostics escape."""

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

checks = sys.modules[__name__]


MARKER = WORKSPACE / '.plato-sdk1039-sandbox-probe'
LIMIT = 32768


def capture(command, env, *, timeout=20, cwd=WORKSPACE):
    """Aggregate stdout+stderr cap; kill only this new zero-model process group."""
    process = None
    streams = {'stdout': bytearray(), 'stderr': bytearray()}
    timed_out = exceeded = launch_failed = False
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        until = time.monotonic() + timeout
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ, 'stdout')
            ready.register(process.stderr, selectors.EVENT_READ, 'stderr')
            while ready.get_map():
                remaining = until - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                events = ready.select(remaining)
                if not events:
                    timed_out = True
                    break
                for key, _ in events:
                    available = LIMIT - sum(map(len, streams.values()))
                    chunk = os.read(key.fileobj.fileno(), min(4096, available+1))
                    if not chunk:
                        ready.unregister(key.fileobj)
                        continue
                    streams[key.data].extend(chunk[:available])
                    if len(chunk) > available:
                        exceeded = True
                        break
                if exceeded:
                    break
        if not timed_out and not exceeded:
            try:
                process.wait(timeout=max(0.001, until-time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    except Exception:
        launch_failed = True
    finally:
        if process is not None:
            if timed_out or exceeded or launch_failed or process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            process.stdout.close()
            process.stderr.close()
    return dict(stdout=bytes(streams['stdout']), stderr=bytes(streams['stderr']),
                exit_code=process.returncode if process is not None else None,
                timed_out=timed_out, output_limit_exceeded=exceeded,
                launch_failed=launch_failed)


def summary(raw):
    """Fixed literal markers are evidence categories, never a kernel diagnosis."""
    stderr = raw['stderr'].lower()
    appserver = (b'socket directory' in stderr and
                 any(v in stderr for v in (b'0700', b'user-owned', b'permission')))
    invalid = any(v in stderr for v in (b'unexpected argument', b'unrecognized option',
        b'invalid value', b'error parsing', b'failed to parse', b'unknown field',
        b'invalid configuration', b'unknown config key'))
    landlock = b'landlock' in stderr and any(v in stderr for v in
        (b'not supported', b'unsupported', b'unavailable', b'failed',
         b'operation not permitted', b'function not implemented'))
    namespace = any(v in stderr for v in (b'bwrap', b'bubblewrap', b'unshare', b'user namespace')) and any(
        v in stderr for v in (b'operation not permitted', b'permission denied',
                             b'creating new namespace', b'unshare', b'user namespace'))
    category = ('appserver_socket_permissions' if appserver else
                'invalid_config_or_flag' if invalid else
                'landlock_unavailable' if landlock else
                'bwrap_namespace_or_permission' if namespace else 'unknown')
    stdout = raw['stdout'].strip()
    return dict(exit_code=raw['exit_code'], timed_out=raw['timed_out'],
        output_limit_exceeded=raw['output_limit_exceeded'], launch_failed=raw['launch_failed'],
        stdout_kind=stdout.decode('ascii') if stdout in (b'DENIED',b'WRITABLE',b'UNPROVEN') else 'other',
        probe_child_report_seen=stdout in (b'DENIED',b'WRITABLE',b'UNPROVEN'),
        unsafe_write_observed=stdout==b'WRITABLE', write_denial_observed=stdout==b'DENIED',
        known_error_category=category, stdout_present=bool(raw['stdout']), stderr_present=bool(raw['stderr']),
        stdout_captured_bytes=len(raw['stdout']),stderr_captured_bytes=len(raw['stderr']),
        appserver_socket_marker=appserver, invalid_config_or_flag_marker=invalid,
        landlock_marker=landlock, bwrap_namespace_or_permission_marker=namespace)


def run():
    result = dict(status='sandbox_diagnostic_stop', stop_step='source_inventory',
        source_inventory_pass=False, native_host_verified=False, pinned_cli_verified=False,
        pinned_help_verified=False, control_writable=False, probe_was_run=False,
        native_sandbox_verified=False, marker_absent_after=False,
        model_turns_started=0, sdk_account_read_performed=False,
        queue_written=False, checkpoint_written=False)
    result.update(summary(dict(stdout=b'',stderr=b'',exit_code=None,timed_out=False,
                               output_limit_exceeded=False,launch_failed=False)))
    try:
        require(not any(os.environ.get(k) for k in
                        ('PYTHONPATH','PYTHONHOME','LD_PRELOAD','LD_LIBRARY_PATH')))
        require(checks.inventory('postdeploy').get('postdeploy_inventory_admission') is True)
        result['source_inventory_pass'] = True
        sys.path.insert(0,str(APP))
        result['stop_step'] = 'native_host'
        host = native_host()
        result['native_host_verified'] = True
        result['stop_step'] = 'host_preflight'
        from scripts.plato_dispatcher.runtime import ENV_ALLOW, OVERRIDES, host_preflight
        host_preflight(WORKSPACE,STATE)
        from codex_cli_bin import bundled_codex_path
        cli = str(bundled_codex_path())
        env = {k:v for k,v in os.environ.items() if k in ENV_ALLOW}
        for step, command in [('native_sandbox_version',[cli,'--version']),
                              ('native_sandbox_help',[cli,'sandbox','--help'])]:
            result['stop_step'] = step
            raw = capture(command,env)
            result.update(summary(raw))
            require(raw['exit_code']==0 and not any(raw[k] for k in
                    ('timed_out','output_limit_exceeded','launch_failed')))
            if step == 'native_sandbox_version':
                require(raw['stdout'].strip()==b'codex-cli 0.167.0')
                result['pinned_cli_verified'] = True
            else:
                require(b'Full command args to run under the Linux sandbox' in raw['stdout']
                        and b'--config' in raw['stdout'] and b'--sandbox-state-json' in raw['stdout'])
                result['pinned_help_verified'] = True
        result['stop_step'] = 'native_sandbox_control'
        require(not checks._exists(MARKER))
        fd=os.open(MARKER,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            own=os.fstat(fd); now=MARKER.lstat()
            require((own.st_dev,own.st_ino)==(now.st_dev,now.st_ino))
            MARKER.unlink()
        finally:
            os.close(fd)
        result['control_writable'] = True
        command=[cli,'sandbox','-c','sandbox_mode="read-only"','-c','approval_policy="never"']
        for override in OVERRIDES:
            command += ['-c',override]
        command += ['--',sys.executable,'-I','-B','-c',DENIAL_PROBE]
        result['stop_step'] = 'native_sandbox_probe'
        result['probe_was_run'] = True
        raw=capture(command,env)
        result.update(summary(raw))
        result['marker_absent_after'] = not checks._exists(MARKER)
        result['stop_step'] = 'native_host_postcheck'
        require(native_host()==host)
        result['native_sandbox_verified'] = (raw['exit_code']==0 and
            not any(raw[k] for k in ('timed_out','output_limit_exceeded','launch_failed')) and
            result['stdout_kind']=='DENIED' and result['marker_absent_after'])
        result.update(status='sandbox_diagnostic_complete',stop_step='complete')
    except BaseException:
        pass
    return result


def main():
    os.umask(0o077)
    try:
        result=run()
    except BaseException:
        result=dict(status='sandbox_diagnostic_stop',stop_step='local_error',model_turns_started=0,
                    sdk_account_read_performed=False,queue_written=False,checkpoint_written=False)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 0 if result.get('status')=='sandbox_diagnostic_complete' else 2

raise SystemExit(main())
PLATO_SDK1039_SANDBOX_DIAGNOSTIC
