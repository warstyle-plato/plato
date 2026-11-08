"""Isolated host tests: no model calls, auth mutations, network, or app-server."""
import errno
import importlib
from pathlib import Path
import json
import multiprocessing
import os
import signal
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.plato_dispatcher.store import Store, SafeError, private_input
from scripts.plato_dispatcher.runtime import AuthRequired, Dispatcher, SDKAdapter, StopRequested
from scripts.plato_dispatcher.__main__ import main


class Crash(BaseException):
    pass


class FakeAdapter:
    def __init__(self, *, auth=True, crash=None, reconcile_state="unknown"):
        self.auth, self.crash, self.reconcile_state = auth, crash, reconcile_state
        self.starts, self.resumes, self.reconciles = [], [], []
        self.thread_count = 0

    def __enter__(self):
        if not self.auth:
            raise AuthRequired()
        return self

    def __exit__(self, *args):
        pass

    def thread(self, thread_id):
        self.resumes.append(thread_id)
        self.thread_count += 1
        return SimpleNamespace(id=thread_id or f"private-thread-{self.thread_count}")

    def start(self, thread, content):
        self.starts.append((thread.id, content))
        if self.crash == "unknown_turn":
            raise Crash("secret path and token")
        if self.crash == "late_auth":
            raise AuthRequired()
        return SimpleNamespace(id="private-turn-id")

    def wait(self, handle):
        if self.crash == "known_turn":
            raise Crash("secret result")
        if self.crash == "error":
            raise RuntimeError("private bearer token /private/path")
        if self.crash == "stop":
            raise StopRequested()
        return "completed", "private result"

    def reconcile(self, thread, turn):
        self.reconciles.append((thread, turn))
        return self.reconcile_state, "private recovered result"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "private")


def enqueue(store, request="r1", task="t1", content="private prompt"):
    return store.submit(task, request, content)


def test_idle_does_not_construct_sdk(store):
    def fail():
        pytest.fail("idle host must not touch SDK/auth")
    assert Dispatcher(store, fail).run_once() == {"status": "idle", "claimed": False}


def test_restart_idempotency_and_followup_share_thread(store):
    assert enqueue(store)["created"]
    fake = FakeAdapter()
    assert Dispatcher(store, lambda: fake).run_once()["status"] == "completed"
    restarted = Store(store.directory)
    assert enqueue(restarted) == {"status": "completed", "created": False}
    assert restarted.submit("t1", "r2", "next private prompt", continuation=True)["created"]
    assert Dispatcher(restarted, lambda: fake).run_once()["status"] == "completed"
    assert fake.resumes == [None, "private-thread-1"]
    assert len(fake.starts) == 2
    assert Dispatcher(restarted, lambda: fake).run_once()["status"] == "idle"
    assert len(fake.starts) == 2


def test_separate_tasks_get_separate_threads(store):
    enqueue(store)
    enqueue(store, task="t2", request="r2")
    fake = FakeAdapter()
    worker = Dispatcher(store, lambda: fake)
    worker.run_once()
    worker.run_once()
    assert [t for t, _ in fake.starts] == ["private-thread-1", "private-thread-2"]


@pytest.mark.parametrize("task,request_key,content,continuation,code", [
    ("t1", "r1", "changed", False, "idempotency_conflict"),
    ("other", "r1", "private prompt", False, "idempotency_conflict"),
    ("t1", "r2", "private prompt", False, "task_exists"),
    ("t1", "r2", "private prompt", True, "continuation_blocked"),
    ("missing", "r2", "private prompt", True, "continuation_blocked"),
])
def test_conflicts_and_unfinished_continuation_blocked(store, task, request_key, content, continuation, code):
    enqueue(store)
    with pytest.raises(SafeError, match=code):
        store.submit(task, request_key, content, continuation=continuation)


@pytest.mark.parametrize("phase,known", [("unknown_turn", False), ("known_turn", True)])
def test_crash_recovery_never_repeats_remote_turn(store, phase, known):
    enqueue(store)
    fake = FakeAdapter(crash=phase)
    with pytest.raises(Crash):
        Dispatcher(store, lambda: fake).run_once()
    assert store.status(request="r1")["status"] == "running"
    restarted = Store(store.directory)
    worker = Dispatcher(restarted, lambda: fake)
    assert worker.run_once()["status"] == "needs_attention"
    assert restarted.status(request="r1")["status"] == "needs_attention"
    assert restarted.status(request="r1")["turn_known"] is known
    assert len(fake.starts) == 1
    assert worker.reconcile("r1") == {"status": "needs_attention", "changed": False}
    assert len(fake.reconciles) == int(known)
    assert restarted.retry_auth("r1")["changed"] is False


def test_reconcile_known_completed_turn_without_starting_another(store):
    enqueue(store)
    fake = FakeAdapter(crash="known_turn", reconcile_state="completed")
    worker = Dispatcher(store, lambda: fake)
    with pytest.raises(Crash):
        worker.run_once()
    assert worker.reconcile("r1") == {"status": "completed", "changed": True}
    assert len(fake.starts) == 1
    assert store.status(request="r1")["result_available"]


def test_auth_required_explicit_retry_only(store):
    enqueue(store)
    fake = FakeAdapter(auth=False)
    worker = Dispatcher(store, lambda: fake)
    assert worker.run_once()["status"] == "auth_required"
    assert not fake.starts
    assert worker.run_once()["status"] == "auth_required"
    assert store.retry_auth("r1")["changed"]
    fake.auth = True
    assert worker.run_once()["status"] == "completed"


def test_auth_error_after_remote_submission_is_uncertain(store):
    enqueue(store)
    fake = FakeAdapter(crash="late_auth")
    assert Dispatcher(store, lambda: fake).run_once()["status"] == "needs_attention"
    assert not store.retry_auth("r1")["changed"]


def test_errors_are_redacted_and_not_retried(store, capsys):
    enqueue(store)
    fake = FakeAdapter(crash="error")
    worker = Dispatcher(store, lambda: fake)
    assert worker.run_once()["status"] == "needs_attention"
    assert worker.run_once()["status"] == "needs_attention"
    assert capsys.readouterr() == ("", "")
    public = json.dumps(store.status()) + json.dumps(store.status(request="r1"))
    for secret in ("private", "token", "prompt", "thread-id", "/private/path"):
        assert secret not in public


def test_stop_during_active_turn_marks_attention(store):
    enqueue(store)
    with pytest.raises(StopRequested):
        Dispatcher(store, lambda: FakeAdapter(crash="stop")).run_once()
    assert store.status(request="r1")["status"] == "needs_attention"


def _claim_worker(path, barrier, output):
    store = Store(Path(path))
    barrier.wait()
    output.put(bool(store.claim()))


def test_process_claim_race_has_exactly_one_winner(store):
    enqueue(store)
    context = multiprocessing.get_context("fork")
    barrier, output = context.Barrier(2), context.Queue()
    processes = [context.Process(target=_claim_worker, args=(str(store.directory), barrier, output)) for _ in range(2)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(10)
        assert p.exitcode == 0
    assert sorted(output.get(timeout=2) for _ in processes) == [False, True]


def test_active_worker_not_recovered_by_competitor(store):
    enqueue(store)
    with store.worker():
        assert store.claim()
        with pytest.raises(SafeError, match="busy"):
            Dispatcher(Store(store.directory), lambda: FakeAdapter()).run_once()
        assert store.status(request="r1")["status"] == "running"


def test_private_store_input_and_symlinks(tmp_path, store):
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    source = tmp_path / "prompt"
    source.write_text("secret")
    source.chmod(0o600)
    assert private_input(source) == "secret"
    source.chmod(0o644)
    with pytest.raises(SafeError, match="private_permissions_required"):
        private_input(source)
    source.chmod(0o600)
    link = tmp_path / "symlink"
    link.symlink_to(source)
    with pytest.raises(OSError):
        private_input(link)
    store.directory.chmod(0o755)
    with pytest.raises(SafeError, match="private_permissions_required"):
        Store(store.directory)


def test_limits_are_enforced_before_insert(store):
    for content in ("", "x" * 65537):
        with pytest.raises(SafeError, match="input_limit"):
            enqueue(store, content=content)
    assert store.status()["counts"]["queued"] == 0


def test_cli_status_and_parse_errors_do_not_echo_secrets(tmp_path, capsys):
    base = ["--store-dir", str(tmp_path / "store"), "--workspace", str(tmp_path)]
    assert main(base + ["status", "--task", "secret-task-id"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == {"exists": False, "status": "missing"}
    assert out.err == ""
    assert main(base + ["secret-token-path"]) == 2
    out = capsys.readouterr()
    assert json.loads(out.out) == {"status": "invalid_arguments"}
    assert out.err == ""


def test_sigterm_stops_idle_polling_without_sdk(tmp_path):
    command = [sys.executable, "-m", "scripts.plato_dispatcher", "--store-dir", str(tmp_path / "store"), "--workspace", str(tmp_path), "serve", "--poll-seconds", "300"]
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert json.loads(process.stdout.readline()) == {"status": "idle", "claimed": False}
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0
        assert stderr == ""
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_unknown_remote_turn_blocks_other_queued_work(store):
    enqueue(store)
    enqueue(store, task="t2", request="r2")
    fake = FakeAdapter(crash="unknown_turn")
    worker = Dispatcher(store, lambda: fake)
    with pytest.raises(Crash):
        worker.run_once()
    assert worker.run_once()["status"] == "needs_attention"
    assert store.status(request="r2")["status"] == "queued"
    assert len(fake.starts) == 1


def test_result_and_queue_limits_fail_closed(store, monkeypatch):
    from scripts.plato_dispatcher import store as store_module
    monkeypatch.setattr(store_module, "MAX_REQUESTS", 1)
    enqueue(store)
    with pytest.raises(SafeError, match="queue_limit"):
        enqueue(store, task="t2", request="r2")
    assert enqueue(store)["created"] is False  # idempotency still works at limit
    store.claim()
    assert store.finish("r1", "completed", "x" * 262145) == "needs_attention"
    assert not store.status(request="r1")["result_available"]


def test_sdk_adapter_exact_boundary_without_launching_runtime(tmp_path, monkeypatch):
    from scripts.plato_dispatcher import runtime
    calls = []
    read_only, deny_all = object(), object()
    class Config:
        def __init__(self, **kwargs):
            self.options = kwargs
    class External:
        def __init__(self, **kwargs):
            self.options = kwargs
    class Thread:
        def __init__(self, client=None, thread_id="private-sdk-thread"):
            self.id = thread_id
        def turn(self, message, **kwargs):
            calls.append(("turn", message, kwargs))
            return SimpleNamespace(id="private-sdk-turn", run=lambda: SimpleNamespace(status=SimpleNamespace(value="completed"), final_response="private-result"))
        def read(self, **kwargs):
            calls.append(("read", kwargs))
            return SimpleNamespace(thread=SimpleNamespace(turns=[SimpleNamespace(id="private-sdk-turn", status=SimpleNamespace(value="completed"), model_dump_json=lambda: '{"private":"result"}')]))
    class Client:
        def __init__(self, config):
            calls.append(("config", config.options))
            self._client = self
        def account(self, **kwargs):
            calls.append(("account", kwargs))
            return SimpleNamespace(account=object())
        def thread_start(self, **kwargs):
            calls.append(("start", kwargs))
            return Thread()
        def thread_resume(self, thread_id, **kwargs):
            calls.append(("resume", thread_id, kwargs))
            return Thread(thread_id=thread_id)
        def close(self):
            calls.append(("close",))
    fake = SimpleNamespace(Codex=Client, CodexConfig=Config, ExternalMessage=External, Thread=Thread, ApprovalMode=SimpleNamespace(deny_all=deny_all), Sandbox=SimpleNamespace(read_only=read_only))
    monkeypatch.setitem(sys.modules, "openai_codex", fake)
    monkeypatch.setattr(runtime, "version", lambda name: "0.167.0")
    monkeypatch.setattr(runtime, "host_preflight", lambda workspace, store: workspace)
    monkeypatch.setenv("PLATO_TEST_PRIVATE_TOKEN", "DO-NOT-FORWARD")
    workspace = tmp_path / "workspace"
    with SDKAdapter(workspace, tmp_path / "store") as adapter:
        thread = adapter.thread(None)
        resumed = adapter.thread(thread.id)
        handle = adapter.start(resumed, "untrusted external content")
        assert adapter.wait(handle) == ("completed", "private-result")
        assert adapter.reconcile(thread.id, handle.id)[0] == "completed"
    config = calls[0][1]
    assert config["env"]["PLATO_TEST_PRIVATE_TOKEN"] == ""
    assert "HOME" not in config["env"] and "CODEX_HOME" not in config["env"]
    assert config["cwd"] == str(workspace)
    assert "features.shell_tool=false" in config["config_overrides"]
    assert "features.unified_exec=false" in config["config_overrides"]
    assert "features.apps=false" in config["config_overrides"]
    assert "features.plugins=false" in config["config_overrides"]
    assert ("account", {"refresh_token": False}) in calls
    for call in calls:
        if call[0] in ("start", "resume", "turn"):
            assert call[-1]["sandbox"] is read_only
            assert call[-1]["approval_mode"] is deny_all
    turn = next(call for call in calls if call[0] == "turn")
    assert isinstance(turn[1], External)
    assert turn[1].options == {"tool_name": "plato_local_queue", "content": "untrusted external content"}
    assert calls[-2:] == [("read", {"include_turns": True}), ("close",)]


def test_host_preflight_rejects_custom_config_without_reading_auth(tmp_path, monkeypatch):
    from scripts.plato_dispatcher import runtime
    workspace, home = tmp_path / "workspace", tmp_path / "home"
    workspace.mkdir()
    auth = home / ".codex"
    auth.mkdir(parents=True, mode=0o700)
    (auth / "config.toml").write_text("private config must not be echoed")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # This fixture's accessor avoids the current environment's CODEX_HOME,
    # without overriding either HOME or CODEX_HOME in any process environment.
    class Env:
        def get(self, key, default):
            return default
    monkeypatch.setattr(runtime, "os", SimpleNamespace(environ=Env()))
    with pytest.raises(SafeError, match="host_configuration_blocked"):
        runtime.host_preflight(workspace, tmp_path / "store")


@pytest.fixture
def preflight_host(tmp_path, monkeypatch):
    from scripts.plato_dispatcher import runtime
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    home = tmp_path / "root" / ".codex"
    home.mkdir(mode=0o700, parents=True)
    store = Store(home / "plato-state")
    env = {"CODEX_HOME": str(home)}
    monkeypatch.setattr(runtime, "os", SimpleNamespace(environ=env))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home.parent))
    # Inspect only this synthetic host, including config metadata. Never use
    # the running executor's home, auth, or /etc/codex configuration.
    exists, is_symlink = Path.exists, Path.is_symlink
    monkeypatch.setattr(Path, "exists", lambda p: p.is_relative_to(tmp_path) and exists(p))
    monkeypatch.setattr(Path, "is_symlink", lambda p: p.is_relative_to(tmp_path) and is_symlink(p))
    return SimpleNamespace(runtime=runtime, workspace=workspace, home=home,
                           store=store, env=env)


@pytest.mark.parametrize("private", ["store", "home"])
@pytest.mark.parametrize("spelling", ["direct", "parent-alias", "parent-dotdot", "same"])
def test_host_preflight_rejects_canonical_private_containment(preflight_host, tmp_path, private, spelling):
    host = preflight_host
    if spelling == "parent-alias":
        alias = tmp_path / "alias"
        alias.symlink_to(host.workspace, target_is_directory=True)
        path = alias / "private"
    elif spelling == "parent-dotdot":
        other = tmp_path / "other"
        other.mkdir()
        path = other / ".." / "workspace" / "private"
    else:
        path = host.workspace if spelling == "same" else host.workspace / "private"
    if private == "store":
        host.store = Store(path)
        assert host.store.path.resolve().is_relative_to(host.workspace.resolve())
        assert stat.S_IMODE(host.store.path.stat().st_mode) == 0o600
    else:
        path.mkdir(mode=0o700, exist_ok=True)
        host.env["CODEX_HOME"] = str(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    with pytest.raises(SafeError, match="^private_workspace_required$"):
        host.runtime.host_preflight(host.workspace, host.store.directory)


@pytest.mark.parametrize("spelling", ["direct", "parent-alias", "parent-dotdot", "default-home", "workspace-alias"])
def test_host_preflight_accepts_disjoint_blueprint_layout(preflight_host, tmp_path, spelling):
    host = preflight_host
    store = host.store.directory
    if spelling == "parent-alias":
        alias = tmp_path / "root-alias"
        alias.symlink_to(host.home.parent, target_is_directory=True)
        home = alias / ".codex"
        host.env["CODEX_HOME"], store = str(home), home / "plato-state"
    elif spelling == "parent-dotdot":
        other = tmp_path / "other"
        other.mkdir()
        home = other / ".." / "root" / ".codex"
        host.env["CODEX_HOME"], store = str(home), home / "plato-state"
    elif spelling == "default-home":
        host.env.clear()
    workspace = host.workspace
    if spelling == "workspace-alias":
        workspace = tmp_path / "workspace-alias"
        workspace.symlink_to(host.workspace, target_is_directory=True)
    assert host.runtime.host_preflight(workspace, store) == host.workspace.resolve()


@pytest.mark.parametrize("spelling", ["direct", "missing-dotdot", "relative-alias"])
def test_host_preflight_allows_absent_disjoint_home(preflight_host, tmp_path, spelling):
    host = preflight_host
    home = tmp_path / "not-created" / ".codex"
    if spelling == "missing-dotdot":
        home = tmp_path / "missing" / ".." / "not-created" / ".codex"
    elif spelling == "relative-alias":
        home = tmp_path / "home-alias"
        home.symlink_to(Path("not-created") / ".codex", target_is_directory=True)
    host.env["CODEX_HOME"] = str(home)
    assert host.runtime.host_preflight(host.workspace, host.store.directory) == host.workspace.resolve()


@pytest.mark.parametrize("spelling", ["absolute-target", "relative-target", "missing-dotdot"])
def test_host_preflight_rejects_absent_home_inside_workspace(preflight_host, tmp_path, spelling):
    host = preflight_host
    alias = tmp_path / "dangling-home"
    target = host.workspace / "not-created" / ".codex"
    if spelling == "relative-target":
        target = Path("workspace") / "not-created" / ".codex"
    if spelling == "missing-dotdot":
        alias = tmp_path / "missing" / ".." / "workspace" / "not-created" / ".codex"
    else:
        alias.symlink_to(target, target_is_directory=True)
    host.env["CODEX_HOME"] = str(alias)
    with pytest.raises(SafeError, match="^private_workspace_required$"):
        host.runtime.host_preflight(host.workspace, host.store.directory)


@pytest.mark.parametrize("private", ["workspace", "store", "home"])
@pytest.mark.parametrize("blocker", ["symlink-loop", "not-directory"])
def test_host_preflight_fails_closed_on_unresolvable_paths(preflight_host, tmp_path, private, blocker):
    host = preflight_host
    path = tmp_path / "blocker"
    if blocker == "symlink-loop":
        path.symlink_to(path)
    else:
        path.write_text("synthetic regular file")
    invalid = path / "private"
    workspace, store = host.workspace, host.store.directory
    if private == "workspace":
        workspace = invalid
    elif private == "store":
        store = invalid
    else:
        host.env["CODEX_HOME"] = str(invalid)
    with pytest.raises(SafeError, match="^private_workspace_required$"):
        host.runtime.host_preflight(workspace, store)


@pytest.mark.parametrize("private", ["workspace", "store", "home"])
@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO])
def test_host_preflight_fails_closed_on_resolution_os_errors(preflight_host, tmp_path, monkeypatch, private, error):
    host = preflight_host
    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o700)
    lstat = os.lstat
    def inaccessible(path, *args, **kwargs):
        if Path(path) == blocked:
            raise OSError(error, "synthetic resolution failure")
        return lstat(path, *args, **kwargs)
    monkeypatch.setattr(os, "lstat", inaccessible)
    workspace, store = host.workspace, host.store.directory
    if private == "workspace":
        workspace = blocked
    elif private == "store":
        store = blocked / "queue"
    else:
        host.env["CODEX_HOME"] = str(blocked / ".codex")
    with pytest.raises(SafeError, match="^private_workspace_required$"):
        host.runtime.host_preflight(workspace, store)


def test_host_preflight_still_rejects_final_home_symlink(preflight_host, tmp_path):
    host = preflight_host
    alias = tmp_path / "home-alias"
    alias.symlink_to(host.home, target_is_directory=True)
    host.env["CODEX_HOME"] = str(alias)
    with pytest.raises(SafeError, match="^private_permissions_required$"):
        host.runtime.host_preflight(host.workspace, host.store.directory)


def test_sigterm_during_active_cli_run_persists_attention(store, tmp_path, capsys, monkeypatch):
    from scripts.plato_dispatcher import __main__ as cli
    enqueue(store)
    fake = FakeAdapter()
    def stop(handle):
        signal.raise_signal(signal.SIGTERM)
        pytest.fail("SIGTERM should unwind active wait")
    fake.wait = stop
    monkeypatch.setattr(cli, "SDKAdapter", lambda *args: fake)
    assert main(["--store-dir", str(store.directory), "--workspace", str(tmp_path), "run-once"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "stopping"}
    assert store.status(request="r1")["status"] == "needs_attention"


def test_resume_rejects_unexpected_thread_identity(store):
    enqueue(store)
    fake = FakeAdapter()
    worker = Dispatcher(store, lambda: fake)
    worker.run_once()
    store.submit("t1", "r2", "followup", continuation=True)
    fake.thread = lambda thread_id: SimpleNamespace(id="unexpected-other-thread")
    assert worker.run_once()["status"] == "needs_attention"
    assert len(fake.starts) == 1


def test_private_sqlite_sidecar_rejected(store):
    sidecar = Path(str(store.path) + "-journal")
    sidecar.write_text("private")
    sidecar.chmod(0o644)
    with pytest.raises(SafeError, match="private_permissions_required"):
        store.status()


def test_sdk_missing_account_closes_client_without_thread_calls(tmp_path, monkeypatch):
    from scripts.plato_dispatcher import runtime
    calls = []
    class Client:
        def __init__(self, config):
            calls.append("constructed")
        def account(self, **kwargs):
            assert kwargs == {"refresh_token": False}
            return SimpleNamespace(account=None)
        def close(self):
            calls.append("closed")
    module = SimpleNamespace(Codex=Client, CodexConfig=lambda **kwargs: kwargs)
    monkeypatch.setitem(sys.modules, "openai_codex", module)
    monkeypatch.setattr(runtime, "version", lambda name: "0.167.0")
    monkeypatch.setattr(runtime, "host_preflight", lambda workspace, store: workspace)
    with pytest.raises(AuthRequired):
        with SDKAdapter(tmp_path / "workspace", tmp_path / "store"):
            pytest.fail("missing account must not permit a turn")
    assert calls == ["constructed", "closed"]


def test_public_cli_help_new_namespace_without_store_or_sdk():
    result = subprocess.run([sys.executable, "-m", "scripts.plato_dispatcher", "--help"], cwd=ROOT, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stderr == ""
    assert "Private PLATO SDK queue host" in result.stdout
    assert "submit,resume,status,run-once,retry-auth,reconcile,serve" in result.stdout
    assert "--input-file" not in result.stdout  # no private argument values
