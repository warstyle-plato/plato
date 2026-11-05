"""A control attestation permits one guarded dispatch, never an automatic approval."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts import auto_release as queue

ROOT = Path(__file__).resolve().parent.parent
HEAD, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40
REPO, ACTORS = "owner/repo", {"owner"}
JOBS = queue.test_jobs(ROOT)


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
            "statuses": [{"id": 1, "context": queue.APPROVED, "state": "success",
                          "creator": {"login": "owner"},
                          "description": f"pr=42 head={HEAD} reviewed"}],
            "checks": [{"name": name, "status": "completed", "conclusion": "success"}
                       for name in JOBS | {"version"}], "reviews": [], "runs": runs, "jobs": jobs,
            "all_runs": [copy.deepcopy(runs[w][0]) for w in runs]}


@pytest.mark.parametrize("mutation,reason", [
    (lambda s: s.update(statuses=[]), "no successful control"),
    (lambda s: s["statuses"][0].update(creator={"login": "author"}), "creator"),
    (lambda s: s["statuses"][0].update(description=f"pr=42 head={OTHER} reviewed"), "does not bind"),
    (lambda s: s["statuses"][0].update(description=f"pr=43 head={HEAD} reviewed"), "does not bind"),
    (lambda s: s["pull"]["head"].update(sha=OTHER), "does not bind"),
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
    snapshot["statuses"].insert(0, {**snapshot["statuses"][0], "id": 0, "state": "failure"})
    snapshot["reviews"] = [
        {"id": 1, "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED"},
        {"id": 2, "user": {"login": "reviewer"}, "state": "APPROVED"}]
    assert queue.refusal(snapshot, ACTORS, JOBS) == ""
    snapshot["statuses"].append({**snapshot["statuses"][1], "id": 2, "state": "pending"})
    assert "no successful control" in queue.refusal(snapshot, ACTORS, JOBS)


def test_later_main_does_not_revoke_the_same_source_head_acceptance():
    snapshot = ready()
    snapshot["statuses"][0]["description"] = f"pr=42 head={HEAD} base={BASE} reviewed"
    snapshot["main"] = OTHER
    # CI and the attestation retain the previously tested base. Branch protection
    # can still report behind/blocked, which is independently rejected above.
    assert queue.refusal(snapshot, ACTORS, JOBS) == ""


def test_explicit_control_actor_is_supported_but_the_queue_cannot_approve_itself():
    snapshot = ready()
    snapshot["statuses"][0]["creator"]["login"] = "release-control"
    assert queue.refusal(snapshot, {"release-control"}, JOBS) == ""
    snapshot["statuses"][0]["creator"]["login"] = "github-actions[bot]"
    assert "creator" in queue.refusal(snapshot, {"github-actions[bot]"}, JOBS)


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
    snapshot["statuses"][0]["creator"] = creator
    assert "creator" in queue.refusal(snapshot, {creator["login"]}, JOBS)


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
        if path == "/actions/workflows/release-merge.yml/runs":
            return [{"status": query["status"]}] if s["active_release"] else []
        if path == "/actions/runs":
            return copy.deepcopy(s["all_runs"])
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
            api.snapshot["statuses"][0]["state"] = "pending"
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
    ("none", ""), ("approval", "no successful control"),
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
        api.snapshot["statuses"][0]["state"] = "failure"
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
                                       ("refs/heads/main", "pull_request")])
def test_untrusted_invocation_is_rejected_before_any_api_call(monkeypatch, ref, event):
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    with pytest.raises(SystemExit, match="only the main workflow"):
        queue.main()
