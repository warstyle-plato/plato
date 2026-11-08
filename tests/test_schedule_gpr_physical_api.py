"""GPR mapping endpoints retain current-admin admission and private errors."""
from __future__ import annotations

import pytest

import developaid_schedule_gpr_physical as physical
from test_monitor_cumulative_api import api, post, KEY  # noqa: F401
from test_schedule_gpr_physical import site, config, PROJECT, CUT  # noqa: F401


@pytest.fixture
def sources(api, site):
    client, _ = api
    return client, site[0], physical.catalog(PROJECT, CUT)


def payload(state):
    return {"project": PROJECT, **{key: state[key] for key in
            ("source_kind", "source_sha256", "snapshot_id", "revision")}, "configuration": config()}


@pytest.mark.parametrize("path", ["view", "save"])
@pytest.mark.parametrize("key,session", [("", ""), ("bad", ""), ("", "telegram"), ("", "demo")])
def test_admission_precedes_gpr_source_reads_and_writes(sources, monkeypatch, path, key, session):
    client, _, state = sources
    monkeypatch.setattr(physical, "catalog", lambda *a, **kw: pytest.fail("lookup before admission"))
    monkeypatch.setattr(physical, "save", lambda *a, **kw: pytest.fail("write before admission"))
    r = post(client, "schedule-gpr-physical/"+path, key=key, session=session, **payload(state))
    assert r.status_code == 403 and r.headers["cache-control"] == "private, no-store"


def test_round_trip_rotation_and_unset_admin_are_private(sources, monkeypatch):
    client, _, state = sources
    r = post(client, "schedule-gpr-physical/save", **payload(state))
    assert r.status_code == 200 and r.json()["model"]["tasks"][0]["progress"] == .5
    assert r.json()["source_kind"] == "gpr" and r.json()["revision"] == 1
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "rotated-owner-key")
    assert post(client, "schedule-gpr-physical/view", project=PROJECT, cut=CUT).status_code == 403
    assert post(client, "schedule-gpr-physical/view", key="rotated-owner-key", project=PROJECT, cut=CUT).status_code == 200
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "")
    r = post(client, "schedule-gpr-physical/view", key="rotated-owner-key", project=PROJECT, cut=CUT)
    assert r.status_code == 403 and r.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("changes,status", [({"source_kind": "pm"}, 422), ({"source_sha256": "bad"}, 422),
    ({"revision": True}, 422), ({"source_sha256": "a"*64}, 409), ({"snapshot_id": CUT+"-"+"c"*64}, 409)])
def test_invalid_and_substituted_tokens_leave_no_event(sources, changes, status):
    client, root, state = sources
    data = payload(state)
    data.update(changes)
    r = post(client, "schedule-gpr-physical/save", **data)
    assert r.status_code == status and r.headers["cache-control"] == "private, no-store"
    assert not list(root.rglob("gpr_physical_links/[0-9]*.json"))


def test_tampered_journal_returns_generic_private_failure(sources, caplog):
    client, root, state = sources
    assert post(client, "schedule-gpr-physical/save", **payload(state)).status_code == 200
    path = next(root.rglob("gpr_physical_links/[0-9]*.json"))
    path.write_text("PRIVATE-JOURNAL-CONTENT")
    r = post(client, "schedule-gpr-physical/view", project=PROJECT, cut=CUT)
    assert r.status_code == 503 and r.headers["cache-control"] == "private, no-store"
    assert "PRIVATE-JOURNAL-CONTENT" not in r.text+caplog.text
    assert KEY not in path.read_text()
