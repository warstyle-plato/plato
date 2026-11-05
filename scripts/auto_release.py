#!/usr/bin/env python3
"""One-shot release queue. Only trusted main code may dispatch release-merge.yml.

The control status is an attestation, not something this script can grant itself.
An append-only dispatch status is reserved BEFORE dispatch; ambiguous failures
stay reserved for a human to investigate instead of retrying a release forever.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APPROVED = "control/release-approved"
DISPATCHED = "control/release-dispatched"
RELEASE_WORKFLOW = "release-merge.yml"
TEST_WORKFLOW = "tests-on-pr.yml"
VERSION_WORKFLOW = "version-guard.yml"
ACTIVE_RUN_STATES = ("queued", "in_progress", "waiting", "pending", "requested")
OPTIONAL_SKIPS = {"Сборка preview-образа", "Preview-образ готов"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
ATTESTATION = re.compile(r"pr=([1-9][0-9]*) head=([0-9a-f]{40})(?: base=([0-9a-f]{40}))? reviewed\Z")
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
    statuses = latest_statuses(snapshot["statuses"])
    approval = statuses.get(APPROVED) or {}
    if approval.get("state") != "success":
        return "no successful control attestation"
    creator = (approval.get("creator") or {}).get("login", "").lower()
    if (creator not in actors or creator.endswith("[bot]")
            or (approval.get("creator") or {}).get("type") == "Bot"):
        return "attestation creator is not a configured control actor"
    match = ATTESTATION.fullmatch(approval.get("description") or "")
    if not match or match.groups()[:2] != (str(pull["number"]), source):
        return "attestation does not bind this PR and head"
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
            decisions[(review.get("user") or {}).get("login")] = review["state"]
    return "changes requested by a reviewer" if "CHANGES_REQUESTED" in decisions.values() else ""


def run_order(run: dict) -> tuple:
    # Re-running an old workflow preserves its id. The attempt's timestamps
    # decide recency; an older id must not hide a newer pending/failed retry.
    times = [datetime.datetime.fromisoformat(run[key].replace("Z", "+00:00"))
             for key in ("run_started_at", "updated_at", "created_at") if run.get(key)]
    if not times:
        raise ValueError("Missing CI attempt timestamps; release refused")
    return max(times), int(run["id"]), int(run.get("run_attempt") or 1)


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
        if context not in {APPROVED, DISPATCHED} and status.get("state") != "success":
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
        if not any(p.get("number") == pull["number"] and (p.get("head") or {}).get("sha") == head
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
                "statuses": api.items(f"/commits/{head}/statuses") if SHA.fullmatch(head) else []}
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
    if (os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") not in {"schedule", "workflow_run"}
            or not os.environ.get("GITHUB_WORKFLOW_REF", "").endswith(
                "/.github/workflows/auto-release.yml@refs/heads/main")):
        raise SystemExit("Auto release executes only the main workflow on scheduled/CI events")
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
