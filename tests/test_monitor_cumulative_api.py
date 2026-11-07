"""Current-key admission and bounded, credential-free background operations."""
from __future__ import annotations

import base64
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import developaid_monitor as monitor
import main as wrapper

core = wrapper.core
KEY = "synthetic-cumulative-owner-key"


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    return TestClient(core.app), tmp_path


def post(client, path, *, key=KEY, session="", **data):
    return client.post("/monitor/" + path, json={"key": key, "session": session, **data})


def poll(client, ticket, family="contracts", **auth):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = post(client, family + "/result", ticket=ticket, **auth)
        if response.status_code != 202:
            return response
        time.sleep(.01)
    raise AssertionError("synthetic operation failed to finish")


@pytest.mark.parametrize("path,data", [
    ("cumulative/upload", {"project": "Fixture", "taken_at": "2026-11-06", "content_base64": "invalid"}),
    ("cumulative/list", {"project": "Fixture"}),
    ("cumulative/result", {"ticket": "a" * 32}),
    ("contracts/build", {"project": "Fixture"}),
    ("contracts/result", {"ticket": "a" * 32}),
    ("contracts/term", {"project": "Fixture", "contract_id": "c1"}),
    ("contracts/link", {"project": "Fixture", "contract_id": "c1", "evidence_id": "e1"}),
    ("contracts/header-date", {"project": "Fixture", "snapshot_id": "2026-11-06-"+"a"*64,
                              "filename": "KS.xlsx", "file_sha256": "b"*64,
                              "sheet": "Работы", "cell": "B4", "raw": "03.07.124",
                              "contract_date": "2024-07-03"}),
])
@pytest.mark.parametrize("key", ["", "wrong-key"])
def test_current_key_is_required_even_without_bot_configuration(api, monkeypatch, path, data, key):
    client, root = api
    monkeypatch.setattr(core, "_monitor_cumulative_execute", lambda *a: pytest.fail("worker before authentication"))
    response = post(client, path, key=key, session="claimed-team-or-demo-session", **data)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert not (root / "monitor" / ".cumulative_jobs").exists()


def test_short_admission_and_poll_do_not_repeat_mutation_or_capture_credentials(api, monkeypatch):
    client, root = api
    release = threading.Event()
    calls = []
    def execute(operation, payload, archive):
        assert "session" not in payload and "key" not in payload
        calls.append((operation, payload, archive))
        assert release.wait(10)
        return {"ok": True, "link": {"confirmed": True}}
    monkeypatch.setattr(core, "_monitor_cumulative_execute", execute)
    data = {"project": "Fixture", "cut": "2026-11-06", "contract_id": "c1", "evidence_id": "e1", "ticket": "1" * 32}
    try:
        before = time.monotonic()
        response = post(client, "contracts/link", session="fixture-owner", **data)
        assert response.status_code == 202 and time.monotonic()-before < 1
        assert post(client, "contracts/result", session="fixture-owner", ticket=response.json()["ticket"]).status_code == 202
        assert post(client, "contracts/link", session="fixture-owner", **data).json()["ticket"] == data["ticket"]
    finally:
        release.set()
    result = poll(client, data["ticket"], session="fixture-owner")
    assert result.status_code == 200 and result.json()["link"]["confirmed"] is True
    assert len(calls) == 1
    private_bytes = b"".join(p.read_bytes() for p in (root / "monitor" / ".cumulative_jobs").iterdir() if p.is_file())
    assert KEY.encode() not in private_bytes and b"fixture-owner" not in private_bytes


def test_owner_family_rotation_and_ticket_parameters_fail_closed(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(core, "_monitor_cumulative_execute", lambda *a: {"ok": True, "register": {"rows": []}})
    response = post(client, "contracts/build", project="Fixture", session="person-A", cut="2026-11-06", ticket="2" * 32)
    ticket = response.json()["ticket"]
    assert poll(client, ticket, session="person-A").status_code == 200
    assert post(client, "contracts/result", ticket=ticket, session="person-B").status_code == 404
    assert post(client, "cumulative/result", ticket=ticket, session="person-A").status_code == 404
    assert post(client, "contracts/build", project="Other", session="person-A", ticket=ticket).status_code == 409
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "rotated-synthetic-key")
    assert post(client, "contracts/result", ticket=ticket, session="person-A").status_code == 403
    assert post(client, "contracts/result", key="rotated-synthetic-key", ticket=ticket, session="person-A").status_code == 404


def test_a_fresh_view_does_not_reuse_an_older_inflight_view(api, monkeypatch):
    client, _ = api
    release = threading.Event()
    first_entered = threading.Event()
    calls = []
    def execute(*args):
        version = len(calls)+1
        calls.append(version)
        first_entered.set()
        assert release.wait(10)
        return {"ok": True, "register": {"version": version}}
    monkeypatch.setattr(core, "_monitor_cumulative_execute", execute)
    try:
        first = post(client, "contracts/build", project="Fixture", ticket="3" * 32)
        assert first_entered.wait(2)
        second = post(client, "contracts/build", project="Fixture", ticket="4" * 32)
        assert first.status_code == second.status_code == 202
        assert first.json()["ticket"] != second.json()["ticket"]
        assert post(client, "contracts/build", project="Fixture", ticket="4" * 32).json()["ticket"] == second.json()["ticket"]
    finally:
        release.set()
    assert poll(client, first.json()["ticket"]).json()["register"]["version"] == 1
    assert poll(client, second.json()["ticket"]).json()["register"]["version"] == 2


def test_upload_checks_envelope_before_worker_and_preserves_bytes(api, monkeypatch):
    client, _ = api
    calls = []
    monkeypatch.setattr(core, "_monitor_cumulative_execute", lambda *a: calls.append(a) or {"ok": True, "snapshot": {}})
    common = {"project": "Fixture", "taken_at": "2026-11-06", "filename": "fixture.zip"}
    assert post(client, "cumulative/upload", content_base64="@bad", **common).status_code == 400
    assert post(client, "cumulative/upload", content_base64="", **common).status_code == 413
    assert post(client, "cumulative/upload", content_base64="UEs=", **dict(common, taken_at="2026-02-30")).status_code == 400
    assert not calls
    blob = b"synthetic-worker-archive"
    response = post(client, "cumulative/upload", content_base64=base64.b64encode(blob).decode(), **common)
    result = poll(client, response.json()["ticket"], family="cumulative")
    assert result.status_code == 200 and result.json()["ok"] is True
    assert calls[0][2] == blob


def test_worker_failure_is_generic_and_validation_is_not_cacheable(api, monkeypatch, caplog):
    client, _ = api
    marker = "private-document-path-and-financial-marker"
    def fail(*args):
        raise RuntimeError(marker)
    monkeypatch.setattr(core, "_monitor_cumulative_execute", fail)
    response = post(client, "contracts/build", project="Fixture")
    result = poll(client, response.json()["ticket"])
    assert result.status_code == 500
    assert marker not in result.text and marker not in caplog.text
    invalid = post(client, "contracts/build")
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("surface", ["history", "poll"])
def test_unexpected_storage_shape_errors_remain_private(api, monkeypatch, caplog, surface):
    import developaid_monitor_ledgers as ledgers
    import developaid_management_report_jobs as jobs
    client, _ = api
    marker = "synthetic-private-storage-content"
    def fail(*args):
        raise AttributeError(marker)
    if surface == "history":
        monkeypatch.setattr(ledgers, "list_snapshots", fail)
        response = post(client, "cumulative/list", project="Fixture")
    else:
        monkeypatch.setattr(jobs.Store, "poll", fail)
        response = post(client, "contracts/result", ticket="a" * 32)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"
    assert marker not in response.text and marker not in caplog.text
