"""Private report admission/polling never repeats a long calculation."""
from __future__ import annotations

import json
import copy
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import main as wrapper

core = wrapper.core
KEY = "private-report-fixture-key"
PARAMS = {"project": "Fixture", "kind": "week", "end": "2026-11-06", "sales_project": None}
RESULT = {"report": {"fixture": 1}, "text": "Fixture", "html": "<h1>Fixture report</h1>"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    return TestClient(core.app), tmp_path


def call(client, path, *, key=KEY, session="", **body):
    return client.post("/monitor/report/" + path, json={"key": key, "session": session, **body})


def done(client, ticket, **auth):
    until = time.monotonic() + 10
    while time.monotonic() < until:
        response = call(client, "result", ticket=ticket, **auth)
        if response.status_code != 202:
            return response
        time.sleep(0.01)
    raise AssertionError("Fixture job did not finish")


def test_admission_and_poll_do_not_wait_or_repeat_the_builder(api, monkeypatch):
    client, _ = api
    release = threading.Event()
    calls = []

    def build(req, **policy):
        if "hide_legal" in policy:  # Background worker, not the legacy synchronous call.
            assert req.key == req.session == ""
        calls.append(req.project)
        release.wait(10)
        return RESULT

    monkeypatch.setattr(core, "_monitor_report_body", build)
    try:
        before = time.monotonic()
        start = call(client, "build", **PARAMS, ticket="1" * 32)
        assert time.monotonic() - before < 1
        assert start.status_code == 202
        assert start.headers["cache-control"] == "private, no-store"
        ticket = start.json()["ticket"]
        before = time.monotonic()
        assert call(client, "result", ticket=ticket).status_code == 202
        assert time.monotonic() - before < 1
        assert call(client, "build", **PARAMS, ticket=ticket).json()["ticket"] == ticket
        assert call(client, "build", **PARAMS, ticket="2" * 32).json()["ticket"] == ticket
    finally:
        release.set()
    result = done(client, ticket)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert {k: result.json()[k] for k in RESULT} == RESULT
    assert calls == ["Fixture"]
    legacy = client.post("/monitor/report", json={"key": KEY, **PARAMS})
    assert legacy.status_code == 200
    assert {k: result.json()[k] for k in RESULT} == legacy.json()


def test_ticket_lookup_always_requires_current_key_and_matching_owner(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(core, "_monitor_report_body", lambda *a, **k: RESULT)
    ticket = call(client, "build", session="person-A", **PARAMS).json()["ticket"]
    assert done(client, ticket, session="person-A").status_code == 200
    assert call(client, "result", key="", session="person-A", ticket=ticket).status_code == 403
    assert call(client, "result", session="person-B", ticket=ticket).status_code == 404
    assert call(client, "build", session="person-B", ticket=ticket, **PARAMS).status_code == 404
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "rotated-fixture-key")
    assert call(client, "result", session="person-A", ticket=ticket).status_code == 403
    assert call(client, "result", key="rotated-fixture-key", session="person-A", ticket=ticket).status_code == 404


def test_new_click_after_completion_gets_new_data_but_exact_retry_does_not(api, monkeypatch):
    client, _ = api
    calls = []

    def build(*a, **k):
        calls.append(1)
        return {**RESULT, "text": str(len(calls))}

    monkeypatch.setattr(core, "_monitor_report_body", build)
    first = call(client, "build", **PARAMS, ticket="3" * 32).json()["ticket"]
    assert done(client, first).json()["text"] == "1"
    retry = call(client, "build", **PARAMS, ticket=first)
    assert retry.json()["text"] == "1"
    fresh = call(client, "build", **PARAMS, ticket="4" * 32).json()["ticket"]
    assert fresh != first
    assert done(client, fresh).json()["text"] == "2"
    assert len(calls) == 2


def test_canonical_dates_and_explicit_empty_sales_link_are_distinct(api, monkeypatch):
    client, _ = api
    release = threading.Event()
    seen = []

    def build(req, **policy):
        seen.append(req)
        release.wait(10)
        return RESULT

    monkeypatch.setattr(core, "_monitor_report_body", build)
    try:
        one = call(client, "build", **{**PARAMS, "end": ""}).json()["ticket"]
        two = call(client, "build", **{**PARAMS, "end": "", "sales_project": ""}).json()["ticket"]
        assert one != two
    finally:
        release.set()
    assert done(client, one).status_code == done(client, two).status_code == 200
    assert all(req.end and req.end != "" for req in seen)
    assert {req.sales_project for req in seen} == {None, ""}


def test_demo_policy_is_bound_and_frozen_before_the_background_build(api, monkeypatch):
    client, _ = api
    import developaid_management_report as report
    release = threading.Event()
    active = {"demo": True}
    monkeypatch.setattr(core, "demo_session_chat", lambda session: 5 if session == "demo" and active["demo"] else 0)
    monkeypatch.setattr(report, "render_text", lambda r: json.dumps(r))
    monkeypatch.setattr(report, "render_html", lambda r: "<h1>Fixture</h1>" + json.dumps(r))

    def build(*a, **k):
        release.wait(10)
        active["demo"] = False  # Session expires while the private report is built.
        return {"project": "Fixture", "legal": {"state": "ok", "private": "ADMIN_CASE_MARKER"}}

    monkeypatch.setattr(report, "build", build)
    ticket = call(client, "build", session="demo", **PARAMS).json()["ticket"]
    release.set()
    # Poll needs the same currently recognised profile. A changed profile is
    # refused; restoring it lets us inspect that the stored result stayed demo.
    until = time.monotonic() + 2
    while active["demo"] and time.monotonic() < until:
        time.sleep(.01)
    assert call(client, "result", session="demo", ticket=ticket).status_code == 404
    active["demo"] = True
    result = done(client, ticket, session="demo")
    assert result.status_code == 200
    assert "ADMIN_CASE_MARKER" not in result.text
    assert result.json()["report"]["legal"]["state"] == "closed"
    assert call(client, "result", session="", ticket=ticket).status_code == 404


@pytest.mark.parametrize("mode", ["legacy", "background", "background-expired"])
def test_demo_removes_legal_findings_from_json_text_and_html(api, monkeypatch, mode):
    client, _ = api
    import developaid_management_report as report

    marker = "LEGAL_PRIVATE_FIXTURE_FINDING_81d4"
    other = "NON_LEGAL_FIXTURE_FINDING"
    raw = {"project": "Fixture", "kind": "week", "start": "2026-11-01", "end": "2026-11-06",
           "legal": {"state": "ok", "recorded": 1, "open": [{
               "card": {"counterparty": marker, "subject": "Fixture legal subject",
                        "status": "claim", "deadline": None}, "totals": {}}]}}
    raw["findings"] = report.findings(raw)
    raw["findings"].append({"topic": "Fixture other", "text": other, "source": "fixture", "tone": ""})
    assert any(marker in item["text"] for item in raw["findings"] if item["topic"] == "Споры")
    alive = {"demo": True}
    release, returned = threading.Event(), threading.Event()
    release.set()
    monkeypatch.setattr(core, "demo_session_chat", lambda session: 5 if session == "demo" and alive["demo"] else 0)

    def build(*a, **k):
        release.wait(10)
        if mode == "background-expired":
            alive["demo"] = False
        returned.set()
        return copy.deepcopy(raw)

    monkeypatch.setattr(report, "build", build)
    admin = client.post("/monitor/report", json={"key": KEY, **PARAMS})
    assert admin.status_code == 200
    for channel in [json.dumps(admin.json()["report"]), admin.json()["text"], admin.json()["html"]]:
        assert marker in channel
    alive["demo"] = True
    if mode == "legacy":
        result = client.post("/monitor/report", json={"key": KEY, "session": "demo", **PARAMS})
    else:
        release.clear()
        returned.clear()
        ticket = call(client, "build", session="demo", **PARAMS).json()["ticket"]
        release.set()
        assert returned.wait(2)
        if mode == "background-expired":
            assert call(client, "result", session="demo", ticket=ticket).status_code == 404
            alive["demo"] = True
        result = done(client, ticket, session="demo")
    assert result.status_code == 200
    output = result.json()
    for channel in [json.dumps(output["report"]), output["text"], output["html"]]:
        assert marker not in channel
        assert other in channel
    assert output["report"]["legal"]["state"] == "closed"
    assert output["report"]["findings"] == [item for item in raw["findings"] if item["topic"] != "Споры"]


def test_job_errors_and_metadata_never_expose_credentials_or_internal_details(api, monkeypatch, caplog):
    client, tmp = api
    private = "INTERNAL_CASE_AND_MONEY_MARKER"

    def build(*a, **k):
        raise ValueError(private)

    monkeypatch.setattr(core, "_monitor_report_body", build)
    ticket = call(client, "build", session="SESSION_SECRET_MARKER", **PARAMS).json()["ticket"]
    response = done(client, ticket, session="SESSION_SECRET_MARKER")
    assert response.status_code == 500
    assert response.headers["cache-control"] == "private, no-store"
    assert private not in response.text + caplog.text
    for path in (tmp / "monitor" / ".report_jobs").iterdir():
        data = path.read_bytes()
        assert KEY.encode() not in data and b"SESSION_SECRET_MARKER" not in data and private.encode() not in data
        assert path.stat().st_mode & 0o077 == 0


def test_another_process_polls_and_reuses_the_active_job(tmp_path):
    store = jobs.Store(tmp_path / "jobs")
    release = threading.Event()
    owner = jobs.owner_binding(KEY, "", "admin")
    start = store.start(owner, "admin", PARAMS, lambda: (release.wait(10), RESULT)[1], "5" * 32)
    script = """
import json, sys
from pathlib import Path
from developaid_management_report_jobs import Store
store=Store(Path(sys.argv[1]))
print(json.dumps([store.poll(sys.argv[2],sys.argv[3],'admin'),
    store.start(sys.argv[3],'admin',json.loads(sys.argv[4]),lambda: 1/0,'6'*32)]))
"""
    try:
        response = subprocess.run([sys.executable, "-c", script, str(store.root), start["ticket"],
                                   owner, json.dumps(PARAMS)], capture_output=True, text=True,
                                  cwd=Path(__file__).resolve().parent.parent, check=True, timeout=10)
        polled, retried = json.loads(response.stdout)
        assert polled["pending"] and retried["ticket"] == start["ticket"]
    finally:
        release.set()


def test_capacity_orphans_and_expiry_fail_closed_without_starting_more_workers(tmp_path, monkeypatch):
    store = jobs.Store(tmp_path / "jobs")
    release = threading.Event()
    owner = jobs.owner_binding(KEY, "", "admin")
    monkeypatch.setattr(jobs, "MAX_ACTIVE", 1)
    ticket = store.start(owner, "admin", PARAMS, lambda: (release.wait(10), RESULT)[1])["ticket"]
    try:
        with pytest.raises(jobs.JobProblem) as full:
            store.start(owner, "admin", {**PARAMS, "project": "Other"}, lambda: RESULT)
        assert full.value.status == 429
        meta = store._meta(ticket)
        meta["created"] -= jobs.TTL_SECONDS + 1
        with store._locked():
            store._save(meta)
        with pytest.raises(jobs.JobProblem) as expired:
            store.poll(ticket, owner, "admin")
        assert expired.value.status == 404
        with pytest.raises(jobs.JobProblem) as still_full:
            store.start(owner, "admin", {**PARAMS, "project": "Other"}, lambda: RESULT)
        assert still_full.value.status == 429
    finally:
        release.set()
    orphan = "7" * 32
    with store._locked():
        store._save({"ticket": orphan, "owner": owner, "profile": "admin", "created": time.time(),
                     "request": "fixture", "state": "pending"})
    with pytest.raises(jobs.JobProblem) as dead:
        store.poll(orphan, owner, "admin")
    assert dead.value.status == 500


@pytest.fixture
def report_ui(api, monkeypatch):
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(Path(__file__).parent))
    from browser import chromium_or_skip, serve

    monkeypatch.setattr(core, "_monitor_report_projects", lambda: {
        "projects": [{"project": "Fixture A"}, {"project": "Fixture B"}], "sales_projects": []})
    with serve(core.app, 18849) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(chromium_or_skip())) as browser:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.add_init_script("localStorage.setItem('plato_projects_key'," + json.dumps(KEY) + ")")
            yield page, base


def test_the_page_shows_pending_and_repeated_show_does_not_duplicate_build(report_ui, monkeypatch):
    from playwright.sync_api import expect
    page, base = report_ui
    release = threading.Event()
    calls = []

    def build(req, **policy):
        calls.append(req.project)
        release.wait(10)
        return RESULT

    monkeypatch.setattr(core, "_monitor_report_body", build)
    try:
        with page.expect_response("**/monitor/report/build"):
            page.goto(base + "/report")
        expect(page.locator("#reportMsg")).to_have_class("msg warn")
        expect(page.locator("#reportBox h1")).to_have_count(0)
        for _ in range(2):
            with page.expect_response("**/monitor/report/build"):
                page.locator("#reportBtn").click()
        assert calls == ["Fixture A"]
    finally:
        release.set()
    expect(page.locator("#reportBox h1")).to_have_text("Fixture report", timeout=5_000)
    expect(page.locator("#reportMsg")).to_be_empty()


@pytest.mark.parametrize("change", ["project", "date", "empty", "auth", "stored-key"])
def test_a_late_admission_cannot_replace_a_changed_report_or_login(report_ui, monkeypatch, change):
    from playwright.sync_api import expect
    page, base = report_ui
    held = []
    monkeypatch.setattr(core, "_monitor_report_body", lambda *a, **k: {
        **RESULT, "html": "<h1>New project report</h1>"})

    def intercept(route):
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route("**/monitor/report/build", intercept)
    page.goto(base + "/report")
    expect(page.locator("#project")).to_have_value("Fixture A")
    if change == "project":
        page.locator("#project").select_option("Fixture B")
    elif change == "date":
        page.locator("#cut").fill("2026-11-07")
        page.locator("#cut").dispatch_event("change")
    elif change == "empty":
        page.evaluate("() => { const p=document.getElementById('project');"
                      " p.add(new Option('Выберите проект',''));p.value='';p.dispatchEvent(new Event('change')); }")
    elif change == "auth":
        page.route("**/monitor/notes", lambda route: route.fulfill(
            status=403, content_type="application/json", body='{"detail":"Fixture denied"}'))
        page.evaluate("async()=>{try{await post('/monitor/notes',{project:'Fixture A'})}catch(e){}}")
    else:
        page.evaluate("window.dispatchEvent(new StorageEvent('storage',{key:'plato_projects_key'}))")
    if change in ("project", "date"):
        expect(page.locator("#reportBox h1")).to_have_text("New project report", timeout=5_000)
    else:
        expect(page.locator("#reportBox h1")).to_have_count(0)
    assert len(held) == 1
    held[0].fulfill(status=200, content_type="application/json", body=json.dumps({
        "pending": False, "ticket": "8" * 32, "html": "<h1>Stale project report</h1>"}))
    page.evaluate("async () => { await new Promise(requestAnimationFrame); }")
    if change in ("project", "date"):
        expect(page.locator("#reportBox h1")).to_have_text("New project report")
    else:
        expect(page.locator("#reportBox h1")).to_have_count(0)
        if change in ("auth", "stored-key"):
            expect(page.locator("#privateArea")).to_be_hidden()


@pytest.mark.parametrize("change", ["project", "date", "period"])
def test_old_financial_tiles_disappear_while_a_changed_report_is_pending(report_ui, monkeypatch, change):
    from playwright.sync_api import expect
    page, base = report_ui
    monkeypatch.setattr(core, "_monitor_report_body", lambda *a, **k: {
        **RESULT, "html": "<h1>Предыдущий бюджет и дефицит</h1>"})
    page.goto(base + "/report")
    expect(page.locator("#reportBox h1")).to_have_text("Предыдущий бюджет и дефицит", timeout=5_000)
    release = threading.Event()

    def changed(req, **policy):
        release.wait(10)
        return {**RESULT, "html": "<h1>Новый бюджет и дефицит</h1>"}

    monkeypatch.setattr(core, "_monitor_report_body", changed)
    try:
        with page.expect_response("**/monitor/report/build") as response:
            if change == "project":
                page.locator("#project").select_option("Fixture B")
            elif change == "date":
                page.locator("#cut").fill("2026-11-07")
                page.locator("#cut").dispatch_event("change")
            else:
                page.locator("#reportKind").select_option("month")
        assert response.value.status == 202
        expect(page.locator("#reportBox h1")).to_have_count(0, timeout=2_000)
        expect(page.locator("#reportMsg")).to_have_class("msg warn")
    finally:
        release.set()
    expect(page.locator("#reportBox h1")).to_have_text("Новый бюджет и дефицит", timeout=5_000)


def test_latest_selection_waits_for_real_capacity_without_extra_workers(report_ui, monkeypatch):
    """Intermediate selections fill both slots; the final selection must recover."""
    from playwright.sync_api import expect
    page, base = report_ui
    release = threading.Event()
    calls, admissions = [], []

    def build(req, **policy):
        calls.append((req.project, req.kind, req.end))
        assert release.wait(10)
        return {**RESULT, "html": f"<h1>{req.project} / {req.kind} / {req.end}</h1>"}

    def response(r):
        if r.url.endswith('/monitor/report/build'):
            admissions.append((r.status, r.request.post_data_json))

    monkeypatch.setattr(core, "_monitor_report_body", build)
    page.on('response', response)
    try:
        with page.expect_response('**/monitor/report/build') as first:
            page.goto(base + '/report')
        assert first.value.status == 202
        with page.expect_response('**/monitor/report/build') as second:
            page.select_option('#project', 'Fixture B')
        assert second.value.status == 202
        with page.expect_response('**/monitor/report/build') as full:
            page.select_option('#reportKind', 'month')
        assert full.value.status == 429
        expect(page.locator('#reportMsg')).to_have_class('msg warn')
        # A further change invalidates the old waiting admission as well.
        with page.expect_response('**/monitor/report/build') as latest:
            page.fill('#cut', '2026-10-31')
        assert latest.value.status == 429
        with page.expect_response('**/monitor/report/build', timeout=3_000) as retry:
            pass
        assert retry.value.status == 429
        assert len(calls) == 2  # No worker/queue item for rejected admissions.
        last_request = admissions[-1][1]
        assert last_request == admissions[-2][1]  # Exact payload and nonce retry.
        release.set()
        expect(page.locator('#reportBox h1')).to_have_text(
            'Fixture B / month / 2026-10-31', timeout=6_000)
        expect(page.locator('#reportMsg')).to_be_empty()
        assert calls[-1] == ('Fixture B', 'month', '2026-10-31')
        assert len(calls) == 3
        # The stale month/today admission never retried after the date changed.
        assert sum(body['ticket'] == admissions[2][1]['ticket'] for _, body in admissions) == 1
    finally:
        release.set()


@pytest.mark.parametrize('status, expected_requests', [(429, 61), (403, 1), (409, 1), (500, 1)])
def test_admission_retries_are_bounded_and_only_for_capacity(report_ui, status, expected_requests):
    from playwright.sync_api import expect
    page, base = report_ui
    requests = []
    # Advance only the report wait; the production retry budget remains intact.
    page.add_init_script("""const originalTimeout=window.setTimeout;
        window.setTimeout=(fn,ms,...args)=>originalTimeout(fn,ms===1500?0:ms,...args);""")

    def refused(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=status, content_type='application/json',
                      body=json.dumps({'detail': 'Fixture admission refusal'}))

    page.route('**/monitor/report/build', refused)
    page.goto(base + '/report')
    message = '#loginMsg' if status == 403 else '#reportMsg'
    expect(page.locator(message)).to_have_class('msg bad', timeout=10_000)
    expect(page.locator(message)).to_have_text('Fixture admission refusal')
    assert len(requests) == expected_requests
    assert all(request == requests[0] for request in requests)
    assert page.evaluate('reportJob') is None
    if status == 403:
        expect(page.locator('#privateArea')).to_be_hidden()


@pytest.mark.parametrize('change', ['project', 'empty', 'auth', 'stored-key'])
def test_a_waiting_capacity_retry_is_cancelled_by_selection_or_auth_change(report_ui, change):
    from playwright.sync_api import expect
    page, base = report_ui
    requests = []
    # Keep the timer pending so cancellation can be checked without a race.
    page.add_init_script("""window.reportWaits=[];const originalTimeout=window.setTimeout;
        window.setTimeout=(fn,ms,...args)=>ms===1500?reportWaits.push(fn):originalTimeout(fn,ms,...args);""")

    def admission(route):
        payload = route.request.post_data_json
        requests.append(payload)
        if payload['project'] == 'Fixture A':
            route.fulfill(status=429, content_type='application/json',
                          body='{"detail":"Fixture busy"}')
        else:
            route.fulfill(status=200, content_type='application/json', body=json.dumps({
                'pending': False, 'html': '<h1>Latest report</h1>'}))

    page.route('**/monitor/report/build', admission)
    page.goto(base + '/report')
    expect(page.locator('#reportMsg')).to_have_class('msg warn')
    page.wait_for_function('reportWaits.length===1')
    if change == 'project':
        page.select_option('#project', 'Fixture B')
        expect(page.locator('#reportBox h1')).to_have_text('Latest report')
    elif change == 'empty':
        page.evaluate("const p=$('project');p.add(new Option('Choose',''));p.value='';p.dispatchEvent(new Event('change'))")
    elif change == 'auth':
        page.evaluate("requireLogin('Fixture login changed')")
    else:
        page.evaluate("window.dispatchEvent(new StorageEvent('storage',{key:'plato_projects_key'}))")
    page.evaluate('async()=>{reportWaits.splice(0).forEach(fn=>fn());await new Promise(requestAnimationFrame)}')
    assert [r['project'] for r in requests] == (['Fixture A', 'Fixture B'] if change == 'project' else ['Fixture A'])
    if change == 'project':
        expect(page.locator('#reportBox h1')).to_have_text('Latest report')
    else:
        expect(page.locator('#reportBox h1')).to_have_count(0)
