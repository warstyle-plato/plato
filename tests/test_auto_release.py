"""A control attestation permits one guarded dispatch, never an automatic approval."""
from __future__ import annotations

import base64
import copy
import io
import json
import sys
import textwrap
from pathlib import Path

import pytest

from scripts import auto_release as queue

ROOT = Path(__file__).resolve().parent.parent
HEAD, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40
REPO, ACTORS = "owner/repo", {"owner"}
JOBS = queue.test_jobs(ROOT)


def control_run(run_id=100, decision="approve", **extra):
    return {"id": run_id, "workflow_id": 501, "run_attempt": 1,
            "display_title": f"release-control pr=42 head={HEAD} decision={decision} reviewed",
            "event": "workflow_dispatch", "path": ".github/workflows/release-approval.yml",
            "head_branch": "main", "head_sha": BASE,
            "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO},
            "actor": {"login": "owner", "type": "User"},
            "triggering_actor": {"login": "owner", "type": "User"},
            "status": "completed", "conclusion": "success",
            "run_started_at": "2026-11-05T12:00:00Z", **extra}


def ready():
    pull = {"number": 42, "state": "open", "merged": False, "draft": False,
            "mergeable": True, "mergeable_state": "clean",
            "head": {"sha": HEAD, "repo": {"full_name": REPO}},
            "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPO}}}
    runs, jobs = {}, {}
    for i, (workflow, names) in enumerate(((queue.TEST_WORKFLOW, JOBS),
                                         (queue.VERSION_WORKFLOW, {"version"})), 10):
        runs[workflow] = [{"id": i, "workflow_id": i, "run_attempt": 1, "event": "pull_request",
                           "run_started_at": "2026-11-05T12:00:00Z", "updated_at": "2026-11-05T13:00:00Z",
                           "head_sha": HEAD, "head_repository": {"full_name": REPO},
                           "path": ".github/workflows/" + workflow, "status": "completed",
                           "conclusion": "success", "pull_requests": [copy.deepcopy(pull)]}]
        jobs[workflow] = [{"name": name, "status": "completed", "conclusion": "success"}
                          for name in names]
    return {"repo": REPO, "main": BASE, "pull": pull, "active_release": False,
            "statuses": [], "approvals": [control_run()], "approval_workflow_id": 501,
            "checks": [{"name": name, "status": "completed", "conclusion": "success"}
                       for name in JOBS | {"version"}], "reviews": [], "runs": runs, "jobs": jobs,
            "all_runs": [copy.deepcopy(runs[w][0]) for w in runs]}


@pytest.mark.parametrize("mutation,reason", [
    (lambda s: s.update(approvals=[]), "no successful human control"),
    (lambda s: s["approvals"][0].update(actor={"login": "author", "type": "User"}), "actor"),
    (lambda s: s["approvals"][0].update(display_title=f"release-control pr=42 head={OTHER} decision=approve reviewed"), "no successful human control"),
    (lambda s: s["approvals"][0].update(display_title=f"release-control pr=43 head={HEAD} decision=approve reviewed"), "no successful human control"),
    (lambda s: s["pull"]["head"].update(sha=OTHER), "no successful human control"),
    (lambda s: s["pull"].update(merged=True), "closed, merged"),
    (lambda s: s["pull"].update(draft=True), "closed, merged"),
    (lambda s: s["pull"].update(mergeable=None), "mergeable"),
    (lambda s: s["pull"].update(mergeable_state="behind"), "mergeable"),
    (lambda s: s["pull"].update(mergeable_state="blocked"), "mergeable"),
    (lambda s: s["checks"][0].update(status="in_progress", conclusion=None), "incomplete"),
    (lambda s: s["checks"][0].update(conclusion="failure"), "unsuccessful"),
    (lambda s: s.update(checks=[c for c in s["checks"] if c["name"] != "version"]), "version check"),
    (lambda s: s.update(checks=[c for c in s["checks"] if c["name"] != "Полный набор"]), "full test verdict"),
    (lambda s: s.update(active_release=True), "release-merge workflow is active"),
    (lambda s: s["statuses"].append({"id": 2, "context": "security", "state": "pending"}), "commit status"),
    (lambda s: s["statuses"].append({"id": 2, "context": queue.DISPATCHED, "state": "error"}), "intent already"),
    (lambda s: s["reviews"].extend([
        {"id": 1, "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"},
        {"id": 2, "user": {"login": "reviewer"}, "state": "COMMENTED"}]), "changes requested"),
    (lambda s: s["runs"][queue.TEST_WORKFLOW].append({**s["runs"][queue.TEST_WORKFLOW][0],
        "id": 99, "status": "in_progress", "conclusion": None}), "latest required CI"),
    (lambda s: s["runs"][queue.TEST_WORKFLOW][0].update(head_sha=OTHER), "latest required CI"),
    (lambda s: s["jobs"][queue.TEST_WORKFLOW].pop(), "CI jobs"),
    (lambda s: s["jobs"][queue.TEST_WORKFLOW][0].update(conclusion="skipped"), "CI jobs"),
])
def test_release_is_refused(mutation, reason):
    snapshot = ready()
    mutation(snapshot)
    assert reason in queue.refusal(snapshot, ACTORS, JOBS)


def test_latest_attestation_and_review_control_the_decision():
    snapshot = ready()
    snapshot["approvals"].insert(0, control_run(99, conclusion="failure"))
    snapshot["reviews"] = [
        {"id": 1, "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"},
        {"id": 2, "user": {"login": "reviewer"}, "state": "APPROVED"}]
    assert queue.refusal(snapshot, ACTORS, JOBS) == ""
    snapshot["approvals"].append(control_run(101, status="queued", conclusion=None))
    assert "latest control decision is pending" in queue.refusal(snapshot, ACTORS, JOBS)


@pytest.mark.parametrize("change", [
    {"workflow_id": 999}, {"path": ".github/workflows/foreign.yml"},
    {"event": "push"}, {"head_branch": "untrusted"},
    {"repository": {"full_name": "stranger/repo"}}, {"head_repository": {"full_name": "stranger/repo"}},
    {"actor": {"login": "owner", "type": "Bot"}},
    {"triggering_actor": {"login": "github-actions[bot]", "type": "Bot"}},
    {"triggering_actor": {"login": "stranger", "type": "User"}},
    {"display_title": None}, {"display_title": f"release-control pr=42 head={HEAD} decision=invalid reviewed"},
    {"status": "queued", "conclusion": None, "run_started_at": None},
    {"status": "in_progress", "conclusion": None}, {"status": "completed", "conclusion": "failure"},
])
def test_control_run_provenance_and_completion_are_mandatory(change):
    api = FakeGitHub()
    api.snapshot["approvals"][0].update(change)
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes


def test_old_native_approval_status_is_not_an_alternative_admission_or_revocation_channel():
    snapshot = ready()
    snapshot["approvals"] = []
    snapshot["statuses"] = [{"id": 9, "context": "control/release-approved", "state": "success",
                             "creator": {"login": "owner", "type": "User"},
                             "description": f"pr=42 head={HEAD} reviewed"}]
    assert "no successful human control" in queue.refusal(snapshot, ACTORS, JOBS)
    snapshot["approvals"] = [control_run()]
    snapshot["statuses"][0]["state"] = "failure"
    assert queue.refusal(snapshot, ACTORS, JOBS) == ""


@pytest.mark.parametrize("status,conclusion", [("queued", None), ("in_progress", None),
                                             ("completed", "failure"), ("completed", "success")])
def test_new_revocation_holds_an_older_approval_even_when_the_older_run_is_retried_later(status, conclusion):
    api = FakeGitHub()
    api.snapshot["approvals"] = [
        control_run(100, run_attempt=2, run_started_at="2026-11-06T23:00:00Z"),
        control_run(101, "revoke", status=status, conclusion=conclusion,
                    run_started_at="2026-11-05T12:00:00Z")]
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes
    # Only a NEW explicit human dispatch (new immutable id) grants again.
    api.snapshot["approvals"].append(control_run(102))
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run") == ""


def test_control_producer_must_execute_its_runtime_guard_instead_of_skipping_the_job():
    flow = (ROOT / ".github/workflows/release-approval.yml").read_text()
    job_header = flow.split("jobs:\n", 1)[1].split("    steps:", 1)[0]
    assert not any(line.strip().startswith("if:") for line in job_header.splitlines())


@pytest.mark.parametrize("case", ["approve", "revoke", "bot", "wrong_ref", "wrong_input", "wrong_native_sha"])
def test_read_only_control_workflow_executes_the_shared_validator_at_its_main_sha(monkeypatch, case):
    flow = (ROOT / ".github/workflows/release-approval.yml").read_text()
    assert "actions/checkout" not in flow and ": write" not in flow
    assert "contents: read" in flow and "actions: read" in flow
    bootstrap = textwrap.dedent(flow.split("python3 - <<'PY'\n", 1)[1].rsplit("          PY", 1)[0])
    decision = "revoke" if case == "revoke" else "approve"
    record = control_run(decision=decision, status="in_progress", conclusion=None)
    if case == "bot":
        record["actor"] = {"login": "github-actions[bot]", "type": "Bot"}
    if case == "wrong_native_sha":
        record["head_sha"] = OTHER
    env = {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_WORKFLOW_REF": REPO + "/.github/workflows/release-approval.yml@refs/heads/main",
           "GITHUB_REPOSITORY": REPO, "GITHUB_SHA": BASE, "GITHUB_RUN_ID": "100",
           "GH_TOKEN": "synthetic-read-only-token", "CONTROL_PR": "42", "CONTROL_HEAD": HEAD,
           "CONTROL_DECISION": decision, "RELEASE_CONTROL_ACTORS": "owner"}
    if case == "wrong_ref":
        # GitHub can report head_branch='main' for a TAG named main too.
        # It must execute/fail the guard, never become all-skipped success.
        env["GITHUB_REF"] = "refs/tags/main"
        env["GITHUB_WORKFLOW_REF"] = REPO + "/.github/workflows/release-approval.yml@refs/tags/main"
    if case == "wrong_input":
        env["CONTROL_HEAD"] = OTHER
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["bootstrap"])
    requests = []
    def respond(request, timeout):
        assert request.get_method() == "GET"
        requests.append(request.full_url)
        if "/contents/" in request.full_url:
            assert request.full_url.endswith("/scripts/auto_release.py?ref=" + BASE)
            result = {"path": "scripts/auto_release.py", "type": "file", "encoding": "base64",
                      "content": base64.encodebytes((ROOT / "scripts/auto_release.py").read_bytes()).decode()}
        elif request.full_url.endswith("/actions/runs/100"):
            result = record
        else:
            assert request.full_url.endswith("/actions/workflows/release-approval.yml")
            result = {"id": 501, "path": ".github/workflows/release-approval.yml"}
        return io.BytesIO(json.dumps(result).encode())
    monkeypatch.setattr(queue.urllib.request, "urlopen", respond)
    with pytest.raises(SystemExit) as result:
        exec(compile(bootstrap, "release-approval bootstrap", "exec"), {})
    assert (result.value.code == 0) == (case in {"approve", "revoke"})
    assert len(requests) == (0 if case == "wrong_ref" else 2 if case == "wrong_native_sha" else 3)
    if case == "wrong_native_sha":
        assert "Native control run SHA differs" in str(result.value)


@pytest.mark.parametrize("later", ["APPROVED", "DISMISSED"])
def test_unknown_reviewers_cannot_clear_an_unknown_request_for_changes(later):
    api = FakeGitHub()
    api.snapshot["reviews"] = [
        {"id": 1, "user": None, "state": "CHANGES_REQUESTED"},
        {"id": 2, "user": None, "state": later}]
    assert "reviewer identity is unavailable" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes


def test_native_review_user_ids_do_not_merge_different_missing_logins():
    reviews = [{"id": 1, "user": {"id": 7}, "state": "CHANGES_REQUESTED"},
               {"id": 2, "user": {"id": 8}, "state": "APPROVED"}]
    assert "changes requested" in queue.latest_review_refusal(reviews)
    reviews[1]["user"]["id"] = 7
    assert queue.latest_review_refusal(reviews) == ""


def test_later_main_does_not_revoke_the_same_source_head_acceptance():
    snapshot = ready()
    snapshot["main"] = OTHER
    # CI and the attestation retain the previously tested base. Branch protection
    # can still report behind/blocked, which is independently rejected above.
    assert queue.refusal(snapshot, ACTORS, JOBS) == ""


def test_explicit_control_actor_is_supported_but_the_queue_cannot_approve_itself():
    snapshot = ready()
    for field in ("actor", "triggering_actor"):
        snapshot["approvals"][0][field]["login"] = "release-control"
    assert queue.refusal(snapshot, {"release-control"}, JOBS) == ""
    snapshot["approvals"][0]["actor"] = {"login": "github-actions[bot]", "type": "Bot"}
    assert "actor" in queue.refusal(snapshot, {"github-actions[bot]"}, JOBS)


def test_only_the_two_optional_preview_checks_may_be_skipped():
    snapshot = ready()
    snapshot["checks"].extend({"name": name, "status": "completed", "conclusion": "skipped"}
                              for name in queue.OPTIONAL_SKIPS)
    assert queue.refusal(snapshot, ACTORS, JOBS) == ""
    for name in JOBS | {"version", "security"}:
        changed = copy.deepcopy(snapshot)
        changed["checks"].append({"name": name, "status": "completed", "conclusion": "skipped"})
        assert "unsuccessful" in queue.refusal(changed, ACTORS, JOBS)
    snapshot["checks"][-1]["conclusion"] = "failure"
    assert "unsuccessful" in queue.refusal(snapshot, ACTORS, JOBS)


@pytest.mark.parametrize("creator", [{"login": "control", "type": "Bot"},
                                    {"login": "control[bot]", "type": "User"}])
def test_a_configured_bot_cannot_attest_independent_acceptance(creator):
    snapshot = ready()
    snapshot["approvals"][0]["actor"] = creator
    assert "actor" in queue.refusal(snapshot, {creator["login"]}, JOBS)


class FakeGitHub:
    repo = REPO

    def __init__(self, snapshot=None):
        self.snapshot, self.writes = snapshot or ready(), []
        self.after_intent = lambda: None
        self.fail_dispatch = False

    def request(self, method, path, body=None):
        if method == "GET":
            if path == "/pulls/42":
                return copy.deepcopy(self.snapshot["pull"])
            if path == "/git/ref/heads/main":
                return {"object": {"sha": self.snapshot["main"]}}
            if path == "/actions/workflows/release-approval.yml":
                return {"id": self.snapshot["approval_workflow_id"], "path": ".github/workflows/release-approval.yml"}
            if path == "/actions/runs/100":
                return copy.deepcopy(self.snapshot["approvals"][0])
            raise AssertionError(path)
        self.writes.append((path, body))
        if path == f"/statuses/{HEAD}":
            intent = {**body, "id": 200, "creator": {"login": "github-actions[bot]"}}
            self.snapshot["statuses"].append(intent)
            self.after_intent()
            return intent
        assert path == "/actions/workflows/release-merge.yml/dispatches"
        if self.fail_dispatch:
            raise RuntimeError("ambiguous dispatch timeout")

    def items(self, path, key=None, **query):
        s = self.snapshot
        if path.endswith("/statuses"):
            return copy.deepcopy(s["statuses"])
        if path.endswith("/check-runs"):
            return copy.deepcopy(s["checks"])
        if path == "/pulls/42/reviews":
            return copy.deepcopy(s["reviews"])
        if path == "/actions/workflows/release-approval.yml/runs":
            return copy.deepcopy(s["approvals"])
        if path == "/actions/workflows/release-merge.yml/runs":
            return [{"status": query["status"]}] if s["active_release"] else []
        if path == "/actions/runs":
            return copy.deepcopy(s["all_runs"])
        if path == "/pulls":
            return [copy.deepcopy(s["pull"])]
        for workflow, runs in s["runs"].items():
            if path == f"/actions/workflows/{workflow}/runs":
                return copy.deepcopy(runs)
            if path == f"/actions/runs/{runs[0]['id']}/jobs":
                return copy.deepcopy(s["jobs"][workflow])
        raise AssertionError(path)


def test_a_qualified_release_records_one_intent_then_calls_only_the_standard_workflow():
    api = FakeGitHub()
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "https://github.com/owner/repo/actions/runs/7") == ""
    assert len(api.writes) == 2
    assert api.writes[0][0] == f"/statuses/{HEAD}"
    assert api.writes[0][1]["context"] == queue.DISPATCHED
    assert api.writes[1] == ("/actions/workflows/release-merge.yml/dispatches", {
        "ref": "main", "inputs": {"pr": "42", "method": "squash",
                                    "expected_head": HEAD, "expected_base": BASE}})
    assert "intent already" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert len(api.writes) == 2


@pytest.mark.parametrize("change", ["head", "main", "approval", "active"])
def test_a_change_after_intent_stops_dispatch_and_does_not_remove_the_reservation(change):
    api = FakeGitHub()
    def changed():
        if change == "head":
            api.snapshot["pull"]["head"]["sha"] = OTHER
        elif change == "main":
            api.snapshot["main"] = OTHER
        elif change == "approval":
            api.snapshot["approvals"].append(control_run(101, status="queued", conclusion=None))
        else:
            api.snapshot["active_release"] = True
    api.after_intent = changed
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert len(api.writes) == 1 and api.writes[0][1]["context"] == queue.DISPATCHED


def test_ambiguous_dispatch_is_not_retried_automatically():
    api = FakeGitHub()
    api.fail_dispatch = True
    with pytest.raises(RuntimeError, match="ambiguous"):
        queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    api.fail_dispatch = False
    assert "intent already" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert len(api.writes) == 2


@pytest.mark.parametrize("late_change,reason", [
    ("none", ""), ("approval", "latest control decision revokes"),
    ("review", "changes requested"), ("checks", "incomplete"),
    ("rerun", "latest PR workflow"), ("head", "actual PR head changed"),
    ("blocked", "mergeable"),
])
def test_consumer_rechecks_the_original_source_even_after_its_version_push(late_change, reason):
    api = FakeGitHub()
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run") == ""
    api.snapshot["pull"]["head"]["sha"] = OTHER
    api.snapshot["pull"]["mergeable_state"] = "unstable"
    if late_change == "approval":
        api.snapshot["approvals"].append(control_run(101, "revoke"))
    elif late_change == "review":
        api.snapshot["reviews"].append({"id": 9, "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"})
    elif late_change == "checks":
        api.snapshot["checks"][0].update(status="in_progress", conclusion=None)
    elif late_change == "rerun":
        api.snapshot["all_runs"].append({**api.snapshot["all_runs"][0], "id": 99,
                                         "status": "queued", "conclusion": None})
    elif late_change == "head":
        api.snapshot["pull"]["head"]["sha"] = "d" * 40
    elif late_change == "blocked":
        api.snapshot["pull"]["mergeable_state"] = "blocked"
    result = queue.validate_approved_source(api, 42, HEAD, OTHER, ACTORS, JOBS, "7")
    assert (result == "") if not reason else (reason in result)
    assert len(api.writes) == 2  # consumer gate is read-only


@pytest.mark.parametrize("fault", [None, "run_head", "association_head", "association_pr", "association_repo"])
def test_consumer_accepts_live_issued_head_associations_but_pins_immutable_run_source(fault):
    api = FakeGitHub()
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run") == ""
    api.snapshot["pull"]["head"]["sha"] = OTHER
    api.snapshot["pull"]["mergeable_state"] = "unstable"
    for run in api.snapshot["all_runs"] + [r for runs in api.snapshot["runs"].values() for r in runs]:
        assert run["head_sha"] == HEAD
        association = run["pull_requests"][0]
        association["head"]["sha"] = OTHER  # native REST association follows LIVE PR HEAD
        for side in ("head", "base"):
            association[side]["repo"] = {"id": 1, "name": "repo",
                                         "url": "https://api.github.com/repos/" + REPO}
    target = api.snapshot["runs"][queue.TEST_WORKFLOW][0]
    if fault == "run_head":
        target["head_sha"] = OTHER
    elif fault == "association_head":
        target["pull_requests"][0]["head"]["sha"] = "d" * 40
    elif fault == "association_pr":
        target["pull_requests"][0]["number"] = 43
    elif fault == "association_repo":
        target["pull_requests"][0]["head"]["repo"]["url"] = "https://api.github.com/repos/stranger/repo"
    result = queue.validate_approved_source(api, 42, HEAD, OTHER, ACTORS, JOBS, "7")
    assert bool(result) == bool(fault)
    assert len(api.writes) == 2


def test_no_intent_is_written_for_a_stale_selected_head():
    api = FakeGitHub()
    api.snapshot["pull"]["head"]["sha"] = OTHER
    assert "changed after selection" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert api.writes == []


def test_an_old_waiting_release_blocks_the_queue_without_scanning_only_recent_history():
    queried = []
    class Runs:
        def items(self, path, key, **query):
            queried.append(query["status"])
            return [{"id": 1, "status": "waiting"}] if query["status"] == "waiting" else []
    assert queue.active_release(Runs())
    assert queried == ["queued", "in_progress", "waiting"]


def test_consumer_excludes_its_own_run_but_not_a_competing_release():
    class Runs:
        def __init__(self, ids): self.ids = ids
        def items(self, path, key, **query):
            return [{"id": n, "status": "in_progress"} for n in self.ids] if query["status"] == "in_progress" else []
    assert not queue.active_release(Runs([7]), "7")
    assert queue.active_release(Runs([7, 8]), "7")


def test_a_missing_shard_cannot_be_hidden_by_a_successful_rollup():
    api = FakeGitHub()
    api.snapshot["jobs"][queue.TEST_WORKFLOW] = [j for j in api.snapshot["jobs"][queue.TEST_WORKFLOW]
                                                 if j["name"] != "Доля 3"]
    assert "CI jobs" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes


def test_a_new_pending_workflow_blocks_even_before_it_creates_check_runs():
    api = FakeGitHub()
    newer = {**api.snapshot["all_runs"][0], "id": 99, "workflow_id": 99,
             "status": "queued", "conclusion": None}
    api.snapshot["all_runs"].append(newer)
    assert "latest PR workflow" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes
    # Completed older failures do not replace the latest successful rerun.
    api.snapshot["all_runs"][-1].update(status="completed", conclusion="failure")
    api.snapshot["all_runs"].append({**newer, "id": 100, "status": "completed", "conclusion": "success"})
    assert queue.dispatch(api, ready(), ACTORS, JOBS, "run") == ""


@pytest.mark.parametrize("status,conclusion", [("queued", None), ("completed", "failure")])
def test_retry_of_an_older_run_is_newer_than_a_larger_successful_run_id(status, conclusion):
    api = FakeGitHub()
    prior = copy.deepcopy(api.snapshot["all_runs"][0])
    # run 10 attempt 2 happens after run 20, even though its id is smaller.
    success = {**prior, "id": 20, "run_started_at": "2026-11-05T20:00:00Z",
               "updated_at": "2026-11-05T21:00:00Z"}
    retry = {**prior, "id": 10, "run_attempt": 2, "status": status, "conclusion": conclusion,
             "run_started_at": "2026-11-05T23:00:00Z", "updated_at": "2026-11-05T23:01:00Z"}
    api.snapshot["all_runs"] = [retry, success, api.snapshot["all_runs"][1]]
    api.snapshot["runs"][queue.TEST_WORKFLOW] = [retry, success]
    assert "latest PR workflow" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes
    if status == "completed":
        # Only a verifiably later success can supersede that failed retry.
        success.update(run_started_at="2026-11-06T00:00:00Z", updated_at="2026-11-06T01:00:00Z")
        api.snapshot["runs"][queue.TEST_WORKFLOW] = [success]
        # FakeGitHub's jobs endpoint now follows the selected run id 20.
        assert queue.dispatch(api, ready(), ACTORS, JOBS, "run") == ""


def test_late_completion_of_an_old_success_does_not_hide_a_newer_failed_attempt():
    api = FakeGitHub()
    prior = copy.deepcopy(api.snapshot["all_runs"][0])
    old_success = {**prior, "id": 20, "run_started_at": "2026-11-05T20:00:00Z",
                   "updated_at": "2026-11-05T23:00:00Z"}
    new_failure = {**prior, "id": 10, "run_attempt": 2, "conclusion": "failure",
                   "created_at": "2026-11-05T18:00:00Z",
                   "run_started_at": "2026-11-05T22:00:00Z", "updated_at": "2026-11-05T22:30:00Z"}
    api.snapshot["all_runs"] = [old_success, new_failure, api.snapshot["all_runs"][1]]
    api.snapshot["runs"][queue.TEST_WORKFLOW] = [new_failure, old_success]
    assert "latest PR workflow" in queue.dispatch(api, ready(), ACTORS, JOBS, "run")
    assert not api.writes


def test_completion_timestamp_cannot_replace_a_missing_attempt_start():
    run = {"id": 10, "run_attempt": 2, "updated_at": "2026-11-05T23:00:00Z"}
    with pytest.raises(ValueError, match="Missing CI attempt start"):
        queue.run_order(run)


def test_pagination_does_not_hide_a_later_failed_status(monkeypatch):
    api = queue.GitHub(REPO, "synthetic")
    requests = []
    def page(method, path, body=None):
        requests.append(path)
        return ([{"id": n, "context": f"check-{n}", "state": "success"} for n in range(100)]
                if path.endswith("&page=1") else [{"id": 100, "context": "last", "state": "failure"}])
    monkeypatch.setattr(api, "request", page)
    statuses = api.items(f"/commits/{HEAD}/statuses")
    assert len(requests) == 2 and len(statuses) == 101
    snapshot = ready()
    snapshot["statuses"].extend(statuses[1:])
    assert "commit status" in queue.refusal(snapshot, ACTORS, JOBS)


def test_workflow_uses_only_main_code_and_minimal_release_permissions():
    workflow = (ROOT / ".github/workflows/auto-release.yml").read_text()
    assert 'cron: "*/5 * * * *"' in workflow
    assert "ref: main" in workflow and "persist-credentials: false" in workflow
    assert "contents: read" in workflow and "pull-requests: read" in workflow
    assert "statuses: write" in workflow and "actions: write" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "pull_request_target:" not in workflow and "secrets." not in workflow
    assert "download-artifact" not in workflow and "github.event.workflow_run.head_sha" not in workflow


@pytest.mark.parametrize("ref,event", [("refs/heads/attacker", "workflow_run"),
                                       ("refs/heads/attacker", "workflow_dispatch"),
                                       ("refs/heads/main", "pull_request")])
def test_untrusted_invocation_is_rejected_before_any_api_call(monkeypatch, ref, event):
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    with pytest.raises(SystemExit, match="only the main workflow"):
        queue.main()


def test_manual_main_queue_run_still_skips_every_pr_without_human_admission(monkeypatch, capsys):
    api = FakeGitHub()
    api.snapshot["approvals"] = []
    for key, value in {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_WORKFLOW_REF": REPO + "/.github/workflows/auto-release.yml@refs/heads/main",
                       "GITHUB_REPOSITORY": REPO, "GH_TOKEN": "synthetic", "GITHUB_RUN_ID": "7"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("RELEASE_CONTROL_ACTORS", "owner")
    monkeypatch.setattr(queue, "GitHub", lambda *a: api)
    monkeypatch.setattr(queue.subprocess, "check_output", lambda *a, **k: BASE)
    assert queue.main() == 0
    assert "no successful human control" in capsys.readouterr().out
    assert api.writes == []
