#!/usr/bin/env python3
"""One-shot release queue. Only trusted main code may dispatch release-merge.yml.

The human control workflow run is an attestation this script cannot grant itself.
An append-only dispatch status is reserved BEFORE dispatch; ambiguous failures
stay reserved for a human to investigate instead of retrying a release forever.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APPROVAL_WORKFLOW = "release-approval.yml"
DISPATCHED = "control/release-dispatched"
RELEASE_WORKFLOW = "release-merge.yml"
TEST_WORKFLOW = "tests-on-pr.yml"
VERSION_WORKFLOW = "version-guard.yml"
ACTIVE_RUN_STATES = ("queued", "in_progress", "waiting", "pending", "requested")
OPTIONAL_SKIPS = {"Сборка preview-образа", "Preview-образ готов"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
CONTROL_BINDING = re.compile(r"release-control pr=([1-9][0-9]*) head=([0-9a-f]{40}) ")
ATTESTATION = re.compile(
    r"release-control pr=([1-9][0-9]*) head=([0-9a-f]{40}) decision=(approve|revoke) reviewed\Z")
ROOT = Path(__file__).resolve().parent.parent


class GitHub:
    def __init__(self, repo: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository")
        self.repo, self.token = repo, token

    def request(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request("https://api.github.com/repos/" + self.repo + path,
                                     data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as answer:
                return json.loads(answer.read().decode() or "null")
        except urllib.error.HTTPError as exc:
            # Never print credentials, raw API bodies, or private PR contents.
            raise RuntimeError(f"GitHub {method} {path}: HTTP {exc.code}") from None

    def items(self, path: str, key: str | None = None, **query) -> list:
        out = []
        for page in range(1, 101):
            result = self.request("GET", path + "?" + urllib.parse.urlencode(
                {**query, "per_page": 100, "page": page}))
            batch = result[key] if key else result
            if not isinstance(batch, list):
                raise ValueError("Unexpected paginated response")
            out.extend(batch)
            if len(batch) < 100:
                return out
        raise RuntimeError("Pagination limit reached; release refused")


def latest_statuses(statuses: list[dict]) -> dict[str, dict]:
    latest = {}
    for status in sorted(statuses, key=lambda x: int(x["id"])):
        latest[status["context"]] = status
    return latest


def control_workflow_id(api: GitHub) -> int:
    workflow = api.request("GET", f"/actions/workflows/{APPROVAL_WORKFLOW}")
    if (workflow.get("path") != ".github/workflows/" + APPROVAL_WORKFLOW
            or type(workflow.get("id")) is not int or workflow["id"] <= 0):
        raise ValueError("Cannot identify the canonical control workflow")
    return workflow["id"]


def control_record_refusal(run: dict, repo: str, workflow_id: int, actors: set[str],
                           number: int, head: str, require_complete: bool = True) -> str:
    """One validator for the read-only producer and both release gates."""
    match = ATTESTATION.fullmatch(run.get("display_title") or "")
    if not match or match.groups()[:2] != (str(number), head):
        return "control run title does not bind this PR and head"
    path = ".github/workflows/" + APPROVAL_WORKFLOW
    if (run.get("workflow_id") != workflow_id or run.get("path") not in {path, path + "@refs/heads/main"}
            or run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
            or (run.get("repository") or {}).get("full_name") != repo
            or (run.get("head_repository") or {}).get("full_name") != repo):
        return "control run is not the canonical main workflow in this repository"
    for field in ("actor", "triggering_actor"):
        actor = run.get(field) or {}
        login = actor.get("login", "").lower()
        if actor.get("type") != "User" or login not in actors or login.endswith("[bot]"):
            return "control run actor is not a configured human control actor"
    if require_complete and (run.get("status") != "completed" or run.get("conclusion") != "success"):
        return "latest control decision is pending or unsuccessful"
    return ""


def control_refusal(snapshot: dict, actors: set[str], number: int, head: str) -> str:
    # IDs order HUMAN dispatch decisions. Re-running an old approval cannot
    # make it newer than a subsequently dispatched revocation.
    matching = [run for run in snapshot["approvals"]
                if (match := CONTROL_BINDING.match(run.get("display_title") or ""))
                and match.groups() == (str(number), head)]
    if not matching:
        return "no successful human control attestation"
    latest = max(matching, key=lambda run: int(run["id"]))
    reason = control_record_refusal(latest, snapshot["repo"], snapshot["approval_workflow_id"],
                                    actors, number, head)
    if reason:
        return reason
    if ATTESTATION.fullmatch(latest["display_title"]).group(3) == "revoke":
        return "latest control decision revokes release"
    return ""


def source_refusal(snapshot: dict, actors: set[str], own_intent: int | None = None) -> str:
    """Cheap checks, also repeated immediately before dispatch."""
    pull, main = snapshot["pull"], snapshot["main"]
    head = pull.get("head") or {}
    source = snapshot.get("source_head") or head.get("sha") or ""
    base = pull.get("base") or {}
    if pull.get("state") != "open" or pull.get("merged") or pull.get("draft"):
        return "PR is closed, merged, or draft"
    if base.get("ref") != "main" or not SHA.fullmatch(main):
        return "main is not the release base"
    if any((side.get("repo") or {}).get("full_name") != snapshot["repo"] for side in (head, base)):
        return "cross-repository PR is not supported"
    if not SHA.fullmatch(head.get("sha") or ""):
        return "invalid PR head"
    if snapshot.get("source_head") and head["sha"] != snapshot.get("expected_actual_head"):
        return "actual PR head changed during the consumer gate"
    reason = control_refusal(snapshot, actors, pull["number"], source)
    if reason:
        return reason
    statuses = latest_statuses(snapshot["statuses"])
    intent = statuses.get(DISPATCHED)
    if intent and intent["id"] != own_intent:
        return "dispatch intent already exists for this SHA; control must investigate"
    if own_intent is not None and (not intent or intent["id"] != own_intent):
        return "dispatch intent is not visible; refusing an ambiguous release"
    return ""


def latest_review_refusal(reviews: list[dict]) -> str:
    decisions = {}
    for review in sorted(reviews, key=lambda x: int(x["id"])):
        # A later COMMENTED review does not cancel CHANGES_REQUESTED.
        if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            user = review.get("user") or {}
            if type(user.get("id")) is int and user["id"] > 0:
                identity = ("id", user["id"])
            elif isinstance(user.get("login"), str) and user["login"].strip():
                identity = ("login", user["login"].lower())
            else:
                return "reviewer identity is unavailable; release refused"
            decisions[identity] = review["state"]
    return "changes requested by a reviewer" if "CHANGES_REQUESTED" in decisions.values() else ""


def run_order(run: dict) -> tuple:
    # An old, long-running success may finish after a newer failed attempt.
    # GitHub updates run_started_at for retries while preserving run id.
    if not run.get("run_started_at"):
        raise ValueError("Missing CI attempt start; release refused")
    started = datetime.datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
    if started.tzinfo is None:
        raise ValueError("CI attempt start has no timezone; release refused")
    return started, int(run["id"]), int(run.get("run_attempt") or 1)


def association_repo(side: dict, repo: str) -> bool:
    """REST PR associations may carry repo.url/id instead of repo.full_name."""
    metadata = side.get("repo") or {}
    full_name, url = metadata.get("full_name"), metadata.get("url")
    return bool(full_name or url) and (not full_name or full_name == repo) and (
        not url or url == "https://api.github.com/repos/" + repo)


def refusal(snapshot: dict, actors: set[str], required_jobs: set[str],
            own_intent: int | None = None) -> str:
    reason = source_refusal(snapshot, actors, own_intent)
    if reason:
        return reason
    pull = snapshot["pull"]
    head = snapshot.get("source_head") or pull["head"]["sha"]
    states = {"clean"}
    if snapshot.get("source_head") and pull["head"]["sha"] != snapshot["source_head"]:
        # _settled/merge pin the consumer's generated version commit. Its
        # skipped CI can be unstable; all approved SOURCE checks still gate.
        states.add("unstable")
    if pull.get("mergeable") is not True or pull.get("mergeable_state") not in states:
        return "PR is not clean and mergeable"
    if snapshot["active_release"]:
        return "release-merge workflow is active"
    reason = latest_review_refusal(snapshot["reviews"])
    if reason:
        return reason
    if any(r.get("status") != "completed" for r in snapshot["all_runs"]):
        return "a latest PR workflow is pending or unsuccessful"
    latest_runs = {}
    for run in sorted(snapshot["all_runs"], key=run_order):
        latest_runs[run["workflow_id"]] = run
    if any(r.get("status") != "completed" or r.get("conclusion") != "success"
           for r in latest_runs.values()):
        return "a latest PR workflow is pending or unsuccessful"
    for context, status in latest_statuses(snapshot["statuses"]).items():
        # The retired user-status channel neither grants nor revokes release.
        if context not in {DISPATCHED, "control/release-approved"} and status.get("state") != "success":
            return "a commit status is pending or failed"
    checks = snapshot["checks"]
    if not checks or any(c.get("status") != "completed" or not (
            c.get("conclusion") == "success" or
            (c.get("name") in OPTIONAL_SKIPS and c.get("conclusion") == "skipped")) for c in checks):
        return "a check is absent, incomplete, or unsuccessful"
    if not {"Полный набор", "version"} <= {c.get("name") for c in checks}:
        return "full test verdict or version check is missing"
    for workflow, required in ((TEST_WORKFLOW, required_jobs), (VERSION_WORKFLOW, {"version"})):
        runs = snapshot["runs"][workflow]
        if not runs:
            return "required CI workflow has not run"
        if any(r.get("status") != "completed" for r in runs):
            return "latest required CI is stale, pending, or unsuccessful"
        run = max(runs, key=run_order)
        if (run.get("head_sha") != head or run.get("event") != "pull_request"
                or run.get("path", "").split("@")[0] != ".github/workflows/" + workflow
                or (run.get("head_repository") or {}).get("full_name") != snapshot["repo"]
                or run.get("status") != "completed" or run.get("conclusion") != "success"):
            return "latest required CI is stale, pending, or unsuccessful"
        # run.head_sha is immutable. pull_requests[].head.sha is a LIVE PR
        # association and can already contain the consumer's version commit.
        associated_heads = {head, pull["head"]["sha"]}
        if not any(p.get("number") == pull["number"]
                   and (p.get("head") or {}).get("sha") in associated_heads
                   and association_repo(p.get("head") or {}, snapshot["repo"])
                   and association_repo(p.get("base") or {}, snapshot["repo"])
                   and SHA.fullmatch((p.get("base") or {}).get("sha") or "")
                   for p in run.get("pull_requests") or []):
            return "CI did not verify this PR head"
        jobs = snapshot["jobs"][workflow]
        if not required <= {j.get("name") for j in jobs} or any(
                j.get("status") != "completed" or j.get("conclusion") != "success" for j in jobs):
            return "required CI jobs are absent, incomplete, or unsuccessful"
    return ""


def test_jobs(root: Path) -> set[str]:
    """Read the shard declaration from trusted main, not another copy of its count."""
    text = (root / ".github/workflows/tests-on-pr.yml").read_text(encoding="utf-8")
    matches = re.findall(r"^\s+shard:\s*(\[[^\n]+\])\s*$", text, flags=re.M)
    if len(matches) != 1:
        raise ValueError("Cannot read the trusted full-test shard matrix")
    shards = json.loads(matches[0])
    if not shards or any(type(s) is not int or s <= 0 for s in shards) or len(set(shards)) != len(shards):
        raise ValueError("Invalid trusted shard matrix")
    return {"Полный набор", *(f"Доля {shard}" for shard in shards)}


def active_release(api: GitHub, exclude_run_id: str = "") -> bool:
    # Query active states explicitly: an old waiting run must not disappear
    # behind the first page of newer, completed runs.
    return any(any(str(run.get("id")) != exclude_run_id for run in api.items(
        f"/actions/workflows/{RELEASE_WORKFLOW}/runs", "workflow_runs", status=state))
               for state in ACTIVE_RUN_STATES)


def inspect(api: GitHub, number: int, actors: set[str], own_intent: int | None = None,
            source_head: str = "", actual_head: str = "", exclude_run_id: str = "") -> dict:
    pull = api.request("GET", f"/pulls/{number}")
    head = source_head or (pull.get("head") or {}).get("sha") or ""
    snapshot = {"repo": api.repo, "pull": pull,
                "main": api.request("GET", "/git/ref/heads/main")["object"]["sha"],
                "statuses": api.items(f"/commits/{head}/statuses") if SHA.fullmatch(head) else [],
                "approval_workflow_id": control_workflow_id(api),
                "approvals": api.items(f"/actions/workflows/{APPROVAL_WORKFLOW}/runs", "workflow_runs",
                                       event="workflow_dispatch", branch="main")}
    if source_head:
        snapshot.update(source_head=source_head, expected_actual_head=actual_head)
    if source_refusal(snapshot, actors, own_intent):
        return snapshot
    snapshot.update({"reviews": api.items(f"/pulls/{number}/reviews"),
                     "checks": api.items(f"/commits/{head}/check-runs", "check_runs", filter="latest"),
                     "active_release": active_release(api, exclude_run_id), "runs": {}, "jobs": {}})
    snapshot["all_runs"] = [r for r in api.items("/actions/runs", "workflow_runs", head_sha=head,
                                               event="pull_request")
                            if any(p.get("number") == number for p in r.get("pull_requests") or [])]
    for workflow in (TEST_WORKFLOW, VERSION_WORKFLOW):
        runs = api.items(f"/actions/workflows/{workflow}/runs", "workflow_runs", head_sha=head,
                         event="pull_request")
        # A shared commit can occur in multiple PRs. Never borrow another PR's CI.
        runs = [r for r in runs if any(p.get("number") == number for p in r.get("pull_requests") or [])]
        snapshot["runs"][workflow] = runs
        latest = max(runs, key=run_order) if runs else None
        snapshot["jobs"][workflow] = (api.items(f"/actions/runs/{latest['id']}/jobs", "jobs", filter="latest")
                                      if latest else [])
    return snapshot


def control_actors(repo: str, configured: str) -> set[str]:
    return {a.strip().lower() for a in (configured.strip() or repo.split("/")[0]).split(",") if a.strip()}


def validate_control_run() -> int:
    """Read-only approval producer. Its successful native run is the record."""
    if (os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or not os.environ.get("GITHUB_WORKFLOW_REF", "").endswith(
                "/.github/workflows/release-approval.yml@refs/heads/main")):
        raise SystemExit("Control attestation executes only the main workflow")
    number, head = os.environ.get("CONTROL_PR", ""), os.environ.get("CONTROL_HEAD", "")
    decision = os.environ.get("CONTROL_DECISION", "")
    if (not re.fullmatch(r"[1-9][0-9]*", number) or not SHA.fullmatch(head)
            or decision not in {"approve", "revoke"}):
        raise SystemExit("Invalid control PR, source SHA, or decision")
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not token or not run_id.isdigit():
        raise SystemExit("No read-only workflow token or run id")
    api = GitHub(repo, token)
    run = api.request("GET", f"/actions/runs/{run_id}")
    actors = control_actors(repo, os.environ.get("RELEASE_CONTROL_ACTORS", ""))
    reason = control_record_refusal(run, repo, control_workflow_id(api), actors, int(number), head, False)
    if reason:
        raise SystemExit(reason)
    if run["display_title"] != f"release-control pr={number} head={head} decision={decision} reviewed":
        raise SystemExit("Control inputs differ from the immutable native run title")
    print(f"Human control decision validated: PR #{number}, source {head}, {decision}")
    return 0


def validate_approved_source(api: GitHub, number: int, source_head: str, actual_head: str,
                             actors: set[str], required_jobs: set[str], run_id: str) -> str:
    """Consumer gate: review/CI stay on the approved source, not the version bump.

    The caller independently pins the generated actual head by _settled + merge
    SHA. A revoked attestation, new review, or CI rerun must still stop this gate.
    """
    statuses = latest_statuses(api.items(f"/commits/{source_head}/statuses"))
    intent = statuses.get(DISPATCHED)
    if not intent:
        return "no durable auto-release intent exists for the approved source"
    snapshot = inspect(api, number, actors, int(intent["id"]), source_head, actual_head, run_id)
    return refusal(snapshot, actors, required_jobs, int(intent["id"]))


def dispatch(api: GitHub, candidate: dict, actors: set[str], required_jobs: set[str], run_url: str) -> str:
    number, head, base = candidate["pull"]["number"], candidate["pull"]["head"]["sha"], candidate["main"]
    # Re-read every gate, not only the snapshot selected earlier in the cron job.
    fresh = inspect(api, number, actors)
    if fresh["pull"]["head"]["sha"] != head or fresh["main"] != base:
        return "PR head or main changed after selection"
    reason = refusal(fresh, actors, required_jobs)
    if reason:
        return reason
    intent = api.request("POST", f"/statuses/{head}", {
        "context": DISPATCHED, "state": "success", "target_url": run_url,
        "description": f"One-shot intent: pr={number} head={head} base={base}"})
    # A crash, visibility error, new push, revoked approval, or ambiguous POST
    # leaves the intent in place. No automatic retry consumes the same SHA.
    final = inspect(api, number, actors, int(intent["id"]))
    if final["pull"]["head"]["sha"] != head or final["main"] != base:
        return "PR head or main changed after intent; control must investigate"
    reason = refusal(final, actors, required_jobs, int(intent["id"]))
    if reason:
        return reason
    api.request("POST", f"/actions/workflows/{RELEASE_WORKFLOW}/dispatches", {
        "ref": "main", "inputs": {"pr": str(number), "method": "squash",
                                    "expected_head": head, "expected_base": base}})
    print(f"PR #{number}: release-merge dispatched for {head}; intent {intent['id']}")
    return ""


def main() -> int:
    if sys.argv[1:] == ["--validate-control-run"]:
        return validate_control_run()
    if (os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") not in {"schedule", "workflow_run", "workflow_dispatch"}
            or not os.environ.get("GITHUB_WORKFLOW_REF", "").endswith(
                "/.github/workflows/auto-release.yml@refs/heads/main")):
        raise SystemExit("Auto release executes only the main workflow on supported queue events")
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
    if not token:
        raise SystemExit("No workflow token")
    api = GitHub(repo, token)
    checked_out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if checked_out != api.request("GET", "/git/ref/heads/main")["object"]["sha"]:
        raise SystemExit("Trusted checkout is no longer current main; next poll will retry")
    actors = control_actors(repo, os.environ.get("RELEASE_CONTROL_ACTORS", ""))
    required_jobs = test_jobs(ROOT)
    if active_release(api):
        print("An existing release is active; waiting for the next poll")
        return 0
    for pull in sorted(api.items("/pulls", state="open", base="main"), key=lambda p: p["number"]):
        snapshot = inspect(api, pull["number"], actors)
        reason = refusal(snapshot, actors, required_jobs)
        if reason:
            print(f"PR #{pull['number']}: {reason}")
            continue
        reason = dispatch(api, snapshot, actors, required_jobs,
                          f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
        if reason:
            print(f"PR #{pull['number']}: {reason}")
        # At most one attempted release per serialized queue execution.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
