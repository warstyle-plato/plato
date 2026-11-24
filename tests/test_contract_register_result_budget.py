"""Result transport policy, without loading the app or reading project sources."""
from __future__ import annotations

import ast
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import developaid_management_report_jobs as jobs
import developaid_monitor_ledgers as ledgers


OWNER = "synthetic-owner"
PROFILE = "monitor-cumulative-v1:contracts"
PARAMS = {"operation": "view", "click": "synthetic-click"}
PRIVATE = "PRIVATE_EXCEPTION_PATH_DOCUMENT_AND_PAYLOAD"
SOURCE_CONTEXT = {"namespace": "Synthetic", "generation": "c" * 64}
ROUTE_SOURCE = Path(__file__).resolve().parents[1] / "engine" / "monitor_cumulative.py"


def terminal(store, ticket):
    until = time.monotonic() + 10
    while time.monotonic() < until:
        result = store.poll(ticket, OWNER, PROFILE)
        if not result["pending"]:
            return result
        time.sleep(.005)
    pytest.fail("Synthetic transport job did not finish")


def test_extended_register_roundtrips_all_history_and_ownership_over_16_mib(tmp_path):
    # Repeated objects must remain present in each JSON location; no projection,
    # deduplication, pruning or replacement of source observations is allowed.
    observed = {"physical_items": [{"history_sources": [{"view": {"periods": [
        {"source_text": "я" * (5 * 1024 * 1024), "quantity": None}]}}]}]}
    register = {"rows": [{"raw_observations": [observed]}], "raw_rows": [observed]}
    payload = {"ok": True, "register": register}
    assert jobs.MAX_RESULT_BYTES < len(json.dumps(payload, ensure_ascii=False).encode()) < jobs.MAX_EXTENDED_RESULT_BYTES
    store = jobs.Store(tmp_path / "jobs")
    ticket = store.start(OWNER, PROFILE, PARAMS, lambda: payload,
                         result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)["ticket"]
    result = terminal(store, ticket)
    assert result == {"pending": False, "ticket": ticket, **payload}
    assert store._meta(ticket)["result_limit_bytes"] == jobs.MAX_EXTENDED_RESULT_BYTES


def test_default_16_mib_failure_cannot_be_upgraded_or_restarted(tmp_path):
    store = jobs.Store(tmp_path / "jobs")
    payload = {"unchanged": "x" * jobs.MAX_RESULT_BYTES}
    ticket = store.start(OWNER, PROFILE, PARAMS, lambda: payload)["ticket"]
    with pytest.raises(jobs.JobProblem) as failed:
        terminal(store, ticket)
    assert (failed.value.status, failed.value.code) == (500, "")
    original_meta = store._meta(ticket)
    assert set(original_meta) == {"ticket", "owner", "profile", "request", "created", "state"}
    with pytest.raises(jobs.JobProblem) as retry:
        store.start(OWNER, PROFILE, PARAMS, lambda: pytest.fail("Old failed ticket restarted"), ticket,
                    result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
    assert (retry.value.status, retry.value.code) == (500, "")
    assert store._meta(ticket) == original_meta
    assert not store._path(ticket, "result").exists()


def test_extended_result_still_fails_at_64_mib(tmp_path):
    store = jobs.Store(tmp_path / "jobs")
    ticket = store.start(OWNER, PROFILE, PARAMS,
                         lambda: {"full_payload": "x" * jobs.MAX_EXTENDED_RESULT_BYTES},
                         result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)["ticket"]
    with pytest.raises(jobs.JobProblem) as failed:
        terminal(store, ticket)
    assert (failed.value.status, failed.value.code) == (500, "result_too_large")
    assert store._meta(ticket)["failure_code"] == "result_too_large"
    assert not store._path(ticket, "result").exists()


@pytest.mark.parametrize("limit", [0, -1, True, 16.0, "67108864", jobs.MAX_EXTENDED_RESULT_BYTES + 1])
def test_invalid_server_budget_cannot_admit_a_job(tmp_path, limit):
    store = jobs.Store(tmp_path / "jobs")
    with pytest.raises(ValueError, match="invalid job result limit"):
        store.start(OWNER, PROFILE, PARAMS, lambda: pytest.fail("Invalid admission"), result_limit_bytes=limit)
    assert not store.root.exists()


@pytest.mark.parametrize("phase", ["builder_failed", "serialization_failed", "storage_failed"])
def test_new_failure_codes_never_include_exception_details(tmp_path, monkeypatch, caplog, phase):
    store = jobs.Store(tmp_path / "jobs")

    def build():
        if phase == "builder_failed":
            private_type = type(PRIVATE, (Exception,), {})
            raise private_type(PRIVATE)
        return {"value": float("nan")} if phase == "serialization_failed" else {"ok": True}

    write = store._write

    def fail_result_write(path, data):
        if path.suffix == ".result":
            raise OSError(PRIVATE)
        write(path, data)

    if phase == "storage_failed":
        monkeypatch.setattr(store, "_write", fail_result_write)
    ticket = store.start(OWNER, PROFILE, PARAMS, build,
                         result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)["ticket"]
    with pytest.raises(jobs.JobProblem) as failed:
        terminal(store, ticket)
    assert failed.value.code == phase
    assert PRIVATE not in str(failed.value) + caplog.text + json.dumps(store._meta(ticket))
    assert store._meta(ticket)["failure_code"] == phase


def test_missing_completed_extended_result_is_safe_storage_failure(tmp_path):
    store = jobs.Store(tmp_path / "jobs")
    ticket = store.start(OWNER, PROFILE, PARAMS, lambda: {"ok": True},
                         result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)["ticket"]
    terminal(store, ticket)
    store._path(ticket, "result").unlink()
    with pytest.raises(jobs.JobProblem) as failed:
        store.poll(ticket, OWNER, PROFILE)
    assert (failed.value.status, failed.value.code) == (500, "storage_failed")


@pytest.mark.parametrize("phase", ["storage_failed", "interrupted"])
def test_extended_admission_failure_is_safe_and_does_not_run_builder(tmp_path, monkeypatch, caplog, phase):
    store = jobs.Store(tmp_path / "jobs")

    def fail(*args, **kwargs):
        raise OSError(PRIVATE)

    if phase == "storage_failed":
        monkeypatch.setattr(store, "_save", fail)
    else:
        monkeypatch.setattr(jobs.threading.Thread, "start", fail)
    with pytest.raises(jobs.JobProblem) as failed:
        store.start(OWNER, PROFILE, PARAMS, lambda: pytest.fail("Failed admission ran builder"),
                    result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
    assert (failed.value.status, failed.value.code) == (503, phase)
    assert PRIVATE not in str(failed.value) + caplog.text


@pytest.mark.parametrize("extended", [False, True])
def test_interrupted_worker_is_typed_only_for_new_extended_jobs(tmp_path, monkeypatch, extended):
    class LostWorker:
        def __init__(self, *, args, **kwargs):
            self.lock = args[2]

        def start(self):
            # The persisted pending manifest outlives its worker/lock.
            self.lock.close()

    monkeypatch.setattr(jobs.threading, "Thread", LostWorker)
    store = jobs.Store(tmp_path / "jobs")
    policy = {"result_limit_bytes": jobs.MAX_EXTENDED_RESULT_BYTES} if extended else {}
    ticket = store.start(OWNER, PROFILE, PARAMS, lambda: pytest.fail("Lost worker ran"), **policy)["ticket"]
    with pytest.raises(jobs.JobProblem) as failed:
        store.poll(ticket, OWNER, PROFILE)
    assert (failed.value.status, failed.value.code) == (500, "interrupted" if extended else "")


def test_active_job_keeps_admitted_budget_owner_profile_locks_and_capacity(tmp_path, monkeypatch):
    store = jobs.Store(tmp_path / "jobs")
    release, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(jobs, "MAX_ACTIVE", 1)

    def build():
        entered.set()
        assert release.wait(10)
        return {"ok": True}

    ticket = store.start(OWNER, PROFILE, PARAMS, build)["ticket"]
    try:
        assert entered.wait(2)
        other = jobs.Store(store.root)
        assert other.poll(ticket, OWNER, PROFILE)["pending"]
        reused = other.start(OWNER, PROFILE, PARAMS, lambda: pytest.fail("Active job restarted"),
                             result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
        assert reused["ticket"] == ticket
        assert "result_limit_bytes" not in store._meta(ticket)
        for owner, profile in [("different-owner", PROFILE), (OWNER, "different-profile")]:
            with pytest.raises(jobs.JobProblem) as denied:
                other.poll(ticket, owner, profile)
            assert denied.value.status == 404 and denied.value.code == ""
            with pytest.raises(jobs.JobProblem) as denied:
                other.start(owner, profile, PARAMS, lambda: {}, ticket,
                            result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
            assert denied.value.status == 404
        with pytest.raises(jobs.JobProblem) as mismatch:
            other.start(OWNER, PROFILE, {"different": True}, lambda: {}, ticket,
                        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
        assert mismatch.value.status == 409
        with pytest.raises(jobs.JobProblem) as full:
            other.start(OWNER, PROFILE, {"different": True}, lambda: {},
                        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
        assert full.value.status == 429
    finally:
        release.set()
    assert terminal(store, ticket)["ok"]
    for path in store.root.iterdir():
        assert path.stat().st_mode & 0o077 == 0


def test_expired_extended_worker_keeps_its_slot_until_lock_is_released(tmp_path, monkeypatch):
    store = jobs.Store(tmp_path / "jobs")
    release, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(jobs, "MAX_ACTIVE", 1)
    monkeypatch.setattr(jobs, "MAX_RETAINED", 1)

    def build():
        entered.set()
        assert release.wait(10)
        return {"ok": True}

    ticket = store.start(OWNER, PROFILE, PARAMS, build,
                         result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)["ticket"]
    try:
        assert entered.wait(2)
        with store._locked():
            meta = store._meta(ticket)
            meta["created"] -= jobs.TTL_SECONDS + 1
            store._save(meta)
        with pytest.raises(jobs.JobProblem) as expired:
            store.poll(ticket, OWNER, PROFILE)
        assert expired.value.status == 404 and expired.value.code == ""
        with pytest.raises(jobs.JobProblem) as full:
            store.start(OWNER, PROFILE, {"other": True}, lambda: {},
                        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)
        assert full.value.status == 429
    finally:
        release.set()
    until = time.monotonic() + 5
    while store._busy(ticket) and time.monotonic() < until:
        time.sleep(.005)
    assert not store._busy(ticket)
    # The worker held its original metadata in memory; expire its completed
    # manifest too, then verify that ordinary retention collection frees it.
    with store._locked():
        meta = store._meta(ticket)
        meta["created"] -= jobs.TTL_SECONDS + 1
        store._save(meta)
    fresh = store.start(OWNER, PROFILE, {"other": True}, lambda: {"ok": True},
                        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)["ticket"]
    assert terminal(store, fresh)["ok"]
    assert store._meta(ticket) is None


def route_cases():
    tree = ast.parse(ROUTE_SOURCE.read_text())
    cases = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_monitor_cumulative_job":
                kwargs = {kw.arg: kw.value.value for kw in call.keywords if isinstance(kw.value, ast.Constant)}
                if "operation" in kwargs:
                    cases.append((node.name, kwargs["family"], kwargs["operation"]))
    return cases


def route_helper(monkeypatch, store_type):
    tree = ast.parse(ROUTE_SOURCE.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_monitor_cumulative_job")

    class Refused(Exception):
        def __init__(self, status, detail, headers=None):
            self.status, self.detail, self.headers = status, detail, headers

    monkeypatch.setattr(ledgers, "snapshot_job_context", lambda project: SOURCE_CONTEXT)
    monkeypatch.setattr(ledgers, "validate_snapshot_job_context", lambda context: None)
    monkeypatch.setattr(jobs, "Store", store_type)
    monkeypatch.setattr(jobs, "owner_binding", lambda *args: OWNER)
    namespace = {"Response": object, "HTTPException": Refused,
                 "JSONResponse": lambda **kwargs: kwargs,
                 "_require_admin_key": lambda *args: None, "_env_str": lambda *args: "",
                 "_monitor_cumulative_day": lambda value: value,
                 "_monitor_cumulative_execute": lambda *args: pytest.fail("No business builder in route-policy test"),
                 "developaid_monitor": SimpleNamespace(_SNAPSHOT_DIR=Path("synthetic-unused-directory")),
                 "base64": __import__("base64"), "logging": __import__("logging")}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTE_SOURCE), "exec"), namespace)
    return namespace[function.name], Refused


def request():
    return SimpleNamespace(key="", session="", ticket="a" * 32, project="Synthetic", cut="2026-11-16",
        taken_at="2026-11-16", filename="synthetic", content_base64="YQ==", contract_id="b" * 64,
        deadline="", contract_date="", note="", evidence_id="", confirmed=False, book_sha256=[], corpus_token="",
        sha256="", estimate=0, choices=[], clear=False, restore=False, source_sha256="", revision="",
        assignments=[], item_ids=[], management_article="", model_dump=lambda **kwargs: {},
        kind="synthetic", snapshot_id="", file_sha256="", sheet="", cell="", raw="",
        values=SimpleNamespace(model_dump=lambda: {}), result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)


@pytest.mark.parametrize("route,family,operation", route_cases())
def test_only_trusted_normal_view_receives_extended_budget(monkeypatch, route, family, operation):
    captured = []

    class Admission:
        def __init__(self, root, *, context_validator):
            assert context_validator is ledgers.validate_snapshot_job_context

        def start(self, owner, profile, fingerprint, build, ticket, *, context, **policy):
            assert context == SOURCE_CONTEXT
            assert fingerprint["source_context"] == SOURCE_CONTEXT
            captured.append(policy)
            return {"pending": True, "ticket": ticket}

    helper, _ = route_helper(monkeypatch, Admission)
    helper(request(), family=family, operation=operation)
    assert captured == ([{"result_limit_bytes": jobs.MAX_EXTENDED_RESULT_BYTES}] if operation == "view" else [{}])
    if operation == "view":
        assert (route, family) == ("monitor_contracts_build", "contracts")


def test_protected_source_operations_are_explicitly_covered():
    protected = {"source-review", "source-audit", "source-audit-page", "source-duplicate-proof", "source-prepared-index"}
    assert protected <= {operation for _, _, operation in route_cases()}


@pytest.mark.parametrize("code", ["", *sorted(jobs.FAILURE_CODES), PRIVATE])
def test_poll_header_is_only_an_enum_and_message_stays_plain(monkeypatch, code):
    class Failed:
        def __init__(self, root, *, context_validator):
            assert context_validator is ledgers.validate_snapshot_job_context

        def poll(self, *args):
            raise jobs.JobProblem(500, PRIVATE, code=code)

    helper, refused = route_helper(monkeypatch, Failed)
    with pytest.raises(refused) as response:
        helper(request(), family="contracts")
    assert response.value.detail == (jobs.SOURCE_CHANGED_DETAIL if code == "source_changed" else
                                     "Не удалось завершить операцию. Повторите запрос.")
    assert PRIVATE not in response.value.detail
    assert response.value.headers == {"Cache-Control": "private, no-store", **(
        {"X-Monitor-Job-Error": code} if code in jobs.FAILURE_CODES else {})}
