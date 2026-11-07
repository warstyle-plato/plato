"""Single local worker; never retries an uncertain remote turn."""
from __future__ import annotations

from importlib.metadata import version
import os
from pathlib import Path

from .store import SafeError, Store, private_path

SDK_VERSION = "0.167.0"
# Names verified with the packaged 0.167.0 `features list`; no custom commands.
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "unified_exec_tty", "shell_snapshot",
    "apps", "plugins", "remote_plugin", "plugin_discovery_prefetch",
    "skill_search", "skill_mcp_dependency_install", "multi_agent", "multi_agent_v2",
    "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "browser_annotation_api", "computer_use", "in_app_browser", "code_mode",
    "code_mode_host", "code_mode_prewarm", "enable_mcp_apps",
)
OVERRIDES = tuple(f"features.{name}=false" for name in DISABLED_FEATURES) + (
    "features.skip_host_skill_discovery=true", 'web_search="disabled"',
)
# The SDK merges env overlays. Empty unapproved names rather than forwarding
# their values. HOME/CODEX_HOME are deliberately neither changed nor copied.
ENV_ALLOW = frozenset(("HOME", "CODEX_HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"))


class AuthRequired(SafeError):
    def __init__(self):
        super().__init__("auth_required")


class StopRequested(Exception):
    pass


def host_preflight(workspace: Path, store: Path):
    """Require a dedicated clean host; do not read/copy/change its auth content."""
    workspace = workspace.resolve(strict=True)
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).absolute()
    if workspace == store or workspace in store.parents or workspace == home or workspace in home.parents:
        raise SafeError("private_workspace_required")
    # Existing custom configuration could launch MCP servers or inject tools.
    # This bounded pilot accepts the stock host only, rather than guessing how
    # to merge or sanitize another application's settings.
    configs = [home / "config.toml", Path("/etc/codex/config.toml"), Path("/etc/codex/managed_config.toml")]
    configs += [p / ".codex" / "config.toml" for p in (workspace, *workspace.parents)]
    if any(p.exists() or p.is_symlink() for p in configs):
        raise SafeError("host_configuration_blocked")
    if home.exists():
        private_path(home, directory=True)
        if (home / "auth.json").exists() or (home / "auth.json").is_symlink():
            private_path(home / "auth.json")
    return workspace


class SDKAdapter:
    """Official SDK boundary. Construction here is lazy until a queued request.

    No login, logout, account mutation, environment directory override, or
    app-server HTTP listener. SDK thread IDs are private, not UI chat IDs.
    """
    def __init__(self, workspace: Path, store: Path):
        self.workspace, self.store = workspace, store
        self.client = None

    def __enter__(self):
        workspace = host_preflight(self.workspace, self.store)
        if any(version(package) != SDK_VERSION for package in ("openai-codex", "openai-codex-cli-bin")):
            raise SafeError("sdk_version_mismatch")
        from openai_codex import Codex, CodexConfig
        overlay = {key: "" for key in os.environ if key not in ENV_ALLOW}
        self.client = Codex(CodexConfig(cwd=str(workspace), env=overlay, config_overrides=OVERRIDES))
        try:
            if self.client.account(refresh_token=False).account is None:
                raise AuthRequired()
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def __exit__(self, *args):
        self.close()

    def thread(self, thread_id):
        from openai_codex import ApprovalMode, Sandbox
        options = dict(cwd=str(self.workspace), sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all)
        return self.client.thread_resume(thread_id, **options) if thread_id else self.client.thread_start(**options)

    def start(self, thread, content):
        from openai_codex import ApprovalMode, ExternalMessage, Sandbox
        return thread.turn(ExternalMessage(tool_name="plato_local_queue", content=content), sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all)

    def wait(self, handle):
        result = handle.run()
        return result.status.value, result.final_response

    def reconcile(self, thread_id, turn_id):
        # Reading history never resumes, starts, joins, steers, or repeats a turn.
        from openai_codex import Thread
        # 0.167.0 has no Codex.thread_read facade. The pinned public Thread
        # wrapper needs its client connection; keep this private bridge here.
        thread = Thread(self.client._client, thread_id)
        for turn in thread.read(include_turns=True).thread.turns:
            if turn.id == turn_id:
                return turn.status.value, turn.model_dump_json()
        return "unknown", None


class Dispatcher:
    def __init__(self, store: Store, adapter_factory):
        self.store, self.adapter_factory = store, adapter_factory

    def run_once(self):
        with self.store.worker():
            self.store.recover()
            request = self.store.claim()
            if request is None:
                return {"status": self.store.status()["status"], "claimed": False}
            key = request["request_id"]
            before_turn = True
            try:
                with self.adapter_factory() as adapter:
                    thread = adapter.thread(request["thread_id"])
                    self.store.bind(key, thread.id)
                    # Remote turn can start before this call returns its ID.
                    # Any error from this point is uncertain, never retryable.
                    before_turn = False
                    handle = adapter.start(thread, request["input"])
                    self.store.turn(key, handle.id)
                    state, result = adapter.wait(handle)
                    state = "completed" if state == "completed" else "failed" if state in ("failed", "interrupted") else "needs_attention"
                    state = self.store.finish(key, state, result)
                    return {"status": state, "claimed": True}
            except AuthRequired:
                state = "auth_required" if before_turn else "needs_attention"
                self.store.finish(key, state)
                return {"status": state, "claimed": True}
            except (StopRequested, KeyboardInterrupt):
                self.store.finish(key, "needs_attention")
                raise
            except Exception:
                self.store.finish(key, "needs_attention")
                return {"status": "needs_attention", "claimed": True}

    def reconcile(self, request_id):
        with self.store.worker():
            self.store.recover()
            row = self.store.attention(request_id)
            if row is None or not row["thread_id"] or not row["turn_id"]:
                return {"status": "needs_attention", "changed": False}
            try:
                with self.adapter_factory() as adapter:
                    state, result = adapter.reconcile(row["thread_id"], row["turn_id"])
                if state in ("completed", "failed", "interrupted"):
                    state = "completed" if state == "completed" else "failed"
                    state = self.store.finish(request_id, state, result)
                    return {"status": state, "changed": True}
            except (StopRequested, KeyboardInterrupt):
                raise
            except Exception:
                pass
            return {"status": "needs_attention", "changed": False}
