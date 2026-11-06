"""Synthetic authorization counterexamples: real routes and captured fake LLM."""
import base64
import copy
import json
import os
from pathlib import Path
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import agent_access
import main as wrapper
import project_knowledge as knowledge

core = wrapper.core
PRIVATE = "SYNTHETIC_INTERNAL_AMOUNT=987654321.09"
KEY = "synthetic-admin-key"


@pytest.fixture(autouse=True)
def runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:synthetic-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.setenv("DEVELOPAID_PAYWALL", "1")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    monkeypatch.setattr(core, "_agent_rate_limit", lambda *a: None)
    monkeypatch.setattr(core, "_run_authoritative_model", lambda *a: {"consolidated": {}})
    monkeypatch.setattr(core, "_telegram_api", lambda *a, **kw: {})
    core._ACCESS_REMOTE_CACHE.clear()
    core._DEMO_ALIVE_CACHE.clear()
    root = tmp_path / "knowledge"
    (root / "docs" / "normative").mkdir(parents=True)
    (root / "docs" / "CLAUDE_HISTORY_SYNTHETIC.md").write_text(
        "## syntheticboundary internal finance\n" + PRIVATE + ". " * 90)
    (root / "docs" / "questions_backlog.md").write_text(
        "## syntheticboundary internal backlog\n" + PRIVATE + ". " * 90)
    (root / "docs" / "normative" / "public.md").write_text(
        "## syntheticboundary public norm\nPublic regulatory method. " * 8)
    (root / "docs" / "glossary.md").write_text(
        "## syntheticboundary definition\nPublic terminology definition. " * 8)
    monkeypatch.setattr(knowledge, "_ROOT", root)
    monkeypatch.setattr(knowledge, "NORMATIVE_DIR", root / "docs" / "normative")


def session(kind="paid", chat=6060):
    if kind == "demo":
        chat = core.demo_create(1, 777, "synthetic", blocks=["calc"])["chat"]
    if kind == "paid":
        core.access_grant(chat, plot=core.access_plot(body()["inputs"]), payment_id="synthetic")
    else:
        assert core.access_use(chat, core.access_plot(body()["inputs"]))["allowed"]
    return core._telegram_session(chat, [])


def body(**extra):
    return {"message": "syntheticboundary query", "inputs": {"_project_uid": "p0123456789ab"},
            "tep": {}, **extra}


def fake_search(monkeypatch, source="rules"):
    captures = []
    def llm(payload, **kwargs):
        captures.append(copy.deepcopy(payload))
        if len(captures) % 2:
            return {"output": [{"type": "function_call", "name": "search_project_knowledge",
                                "call_id": "synthetic", "arguments": json.dumps(
                                    {"query": "syntheticboundary", "source": source})}]}
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "synthetic final answer"}]}]}
    monkeypatch.setattr(core, "_openai_responses_request", llm)
    return captures


def poll_headers(token="", key=""):
    return {"X-Plato-Session": token, "X-Developaid-Admin-Key": key}


@pytest.mark.parametrize("kind", ["free", "paid", "demo"])
@pytest.mark.parametrize("source", ["rules", "backlog", "all"])
def test_external_roles_never_read_or_send_private_sources(kind, source, monkeypatch):
    captures = fake_search(monkeypatch, source)
    original = knowledge._file_entries
    def read(source, path):
        assert source not in {"rules", "backlog"}, "Private source read before authorization"
        return original(source, path)
    monkeypatch.setattr(knowledge, "_file_entries", read)
    token = session(kind)
    with TestClient(core.app) as client:
        response = client.post("/agent/chat", json=body(session=token,
            is_admin=True, scope="admin", caller="monitor", chat_id=777,
            _agent_actor={"private": True}))
    assert response.status_code == 200, response.text
    assert len(captures) == 2
    assert PRIVATE not in json.dumps(captures)
    if source == "all":
        assert "Public regulatory method" in json.dumps(captures)


@pytest.mark.parametrize("token", ["", "forged.telegram.session"])
def test_login_gate_still_rejects_missing_or_forged_session(token, monkeypatch):
    monkeypatch.setattr(core, "_openai_responses_request", lambda *a, **kw: pytest.fail("LLM called"))
    response = TestClient(core.app).post("/agent/chat", json=body(session=token))
    assert response.status_code == 401


def test_direct_tool_and_search_fail_closed_before_private_file_read(monkeypatch):
    monkeypatch.setattr(knowledge, "_file_entries", lambda *a: pytest.fail("Private file read"))
    args = {"query": "syntheticboundary", "source": "rules"}
    assert not core._execute_agent_tool("search_project_knowledge", args, None, {})["available"]
    assert not core._tool_search_project_knowledge("syntheticboundary", "backlog")["available"]
    assert not knowledge.search("syntheticboundary", source="rules")["available"]
    assert not knowledge.entries("rules")


def test_current_admin_key_is_required_for_private_sources_and_polls(monkeypatch):
    captures = fake_search(monkeypatch)
    client = TestClient(core.app)
    response = client.post("/agent/chat", json=body(access_key=KEY))
    assert response.status_code == 200, response.text
    trace = response.json()["trace_id"]
    assert PRIVATE in json.dumps(captures)
    assert KEY not in json.dumps(captures)
    assert "Set-Cookie" in response.headers
    assert "HttpOnly" in response.headers["set-cookie"]
    for route in ("result", "trace"):
        url = f"/agent/{route}/{trace}"
        assert client.get(url).status_code == 403
        assert TestClient(core.app).get(url, headers=poll_headers(key=KEY)).status_code == 403
        own = client.get(url, headers=poll_headers(key=KEY))
        assert own.status_code == 200
        assert own.headers["cache-control"] == "no-store"
    for file in core._PLATO_STAGE_DIR.iterdir():
        if file.is_file():
            assert KEY.encode() not in file.read_bytes()
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "rotated-synthetic-key")
    for candidate in (KEY, "rotated-synthetic-key", ""):
        assert client.get(f"/agent/result/{trace}", headers=poll_headers(key=candidate)).status_code == 403


def test_monitor_inherits_actor_and_cannot_seed_public_cache(monkeypatch):
    captures = fake_search(monkeypatch)
    client = TestClient(core.app)
    monitor = client.post("/monitor/ask", json={"message": "syntheticboundary query", "key": KEY})
    assert monitor.status_code == 200, monitor.text
    trace = monitor.json()["trace_id"]
    assert PRIVATE in json.dumps(captures)
    assert client.get(f"/agent/result/{trace}", headers=poll_headers(key=KEY)).status_code == 200
    token = session()
    outsider = TestClient(core.app)
    assert outsider.get(f"/agent/result/{trace}", headers=poll_headers(token)).status_code == 403
    captures.clear()
    public = outsider.post("/agent/chat", json=body(session=token))
    assert public.status_code == 200
    assert not public.json()["cached"]
    assert PRIVATE not in json.dumps(captures)


def test_cache_owner_trace_collision_and_own_poll(monkeypatch):
    calls = []
    def answer(*args, **kw):
        calls.append(1)
        return {"answer": "OWN_SYNTHETIC_" + str(len(calls)), "model": "fake"}
    monkeypatch.setattr(core, "_call_openai_tool_agent", answer)
    a, b = TestClient(core.app), TestClient(core.app)
    sa, sb = session(chat=6060), session(chat=7070)
    trace = "0123456789abcdef" * 2
    first = a.post("/agent/chat", json=body(session=sa, trace_id=trace))
    assert first.status_code == 200
    assert a.get("/agent/result/" + trace, headers=poll_headers(sa)).json()["answer"] == "OWN_SYNTHETIC_1"
    assert b.get("/agent/result/" + trace, headers=poll_headers(sb)).status_code == 403
    collision = b.post("/agent/chat", json=body(session=sb, trace_id=trace, message="overwrite"))
    assert collision.status_code == 409
    assert a.get("/agent/result/" + trace, headers=poll_headers(sa)).json()["answer"] == "OWN_SYNTHETIC_1"
    assert a.post("/agent/chat", json=body(session=sa, trace_id=trace)).status_code == 409
    second = b.post("/agent/chat", json=body(session=sb))
    assert not second.json()["cached"]
    assert second.json()["answer"] == "OWN_SYNTHETIC_2"
    cached = a.post("/agent/chat", json=body(session=sa))
    assert cached.json()["cached"]
    cached_trace = cached.json()["trace_id"]
    assert a.get("/agent/result/" + cached_trace, headers=poll_headers(sa)).json()["answer"] == "OWN_SYNTHETIC_1"


def test_anonymous_public_owners_and_forged_cookie_are_isolated(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DEVELOPAID_PAYWALL", raising=False)
    calls = []
    monkeypatch.setattr(core, "_call_openai_tool_agent", lambda *a, **kw:
        calls.append(1) or {"answer": "own", "model": "fake"})
    a, b = TestClient(core.app), TestClient(core.app)
    first = a.post("/agent/chat", json=body())
    assert first.status_code == 200
    trace = first.json()["trace_id"]
    assert len(trace) == 32
    assert a.get("/agent/result/" + trace).status_code == 200
    assert b.get("/agent/result/" + trace).status_code == 403
    b.cookies.set(agent_access.COOKIE, "f" * 64 + ".forged")
    assert b.get("/agent/trace/" + trace).status_code == 403
    assert not b.post("/agent/chat", json=body()).json()["cached"]
    assert len(calls) == 2


def test_ownerless_run_and_intake_are_never_served(monkeypatch):
    trace = "deadbeef" * 4
    core._plato_answer_put("run" + trace, {"answer": PRIVATE})
    core._plato_trace_write(trace, "done", PRIVATE)
    client = TestClient(core.app)
    assert client.get("/agent/result/" + trace).status_code == 404
    assert client.get("/agent/trace/" + trace).status_code == 404
    core._intake_queue_save({"id": trace, "filename": PRIVATE})
    response = client.post("/agent/document/card", json={"intake_id": trace, "session": session()})
    assert response.status_code == 404
    assert PRIVATE not in response.text


def test_own_uploaded_document_works_other_paid_user_cannot_read_or_answer(monkeypatch):
    monkeypatch.setattr(core.document_intake, "extract_text", lambda *a: {"text": "OWN_DOCUMENT", "filename": "own.txt"})
    monkeypatch.setattr(core, "document_intake_read", lambda *a: {"notes": [PRIVATE], "fields": [], "questions": []})
    a, b = TestClient(core.app), TestClient(core.app)
    sa, sb = session(chat=6060), session(chat=7070)
    response = a.post("/agent/document", json={"session": sa, "filename": "own.txt",
        "content_b64": base64.b64encode(b"own").decode(),
        "inputs": dict(core.DEFAULT_INPUTS), "tep": copy.deepcopy(core.TEP_DEFAULT)})
    assert response.status_code == 200, response.text
    trace = response.json()["card"]["id"]
    own = a.post("/agent/document/card", json={"session": sa, "intake_id": trace})
    assert own.status_code == 200 and PRIVATE in own.text
    for route in ("card", "answer"):
        denied = b.post("/agent/document/" + route, json={"session": sb, "intake_id": trace, "index": 0})
        assert denied.status_code == 403
        assert PRIVATE not in denied.text


def test_private_key_rotation_during_run_prevents_result_release(monkeypatch):
    def rotate(*a, **kw):
        monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-key")
        return {"answer": PRIVATE, "model": "fake"}
    monkeypatch.setattr(core, "_call_openai_tool_agent", rotate)
    client = TestClient(core.app)
    response = client.post("/agent/chat", json=body(access_key=KEY))
    assert response.status_code == 403
    assert PRIVATE not in response.text
    assert all(PRIVATE.encode() not in p.read_bytes() for p in core._PLATO_STAGE_DIR.glob("answer_*.json"))


def test_real_document_reader_inherits_actor_and_does_not_send_credentials(monkeypatch):
    captures = fake_search(monkeypatch)
    monkeypatch.setattr(core.document_intake, "extract_text", lambda *a: {"text": "OWN_DOCUMENT", "filename": "own.txt"})
    client = TestClient(core.app)
    result = client.post("/agent/document", json={"access_key": KEY, "filename": "own.txt",
        "content_b64": base64.b64encode(b"own").decode()})
    assert result.status_code == 200, result.text
    assert PRIVATE in json.dumps(captures)
    assert KEY not in json.dumps(captures)


def test_trusted_bot_adapter_never_inherits_server_admin_key(monkeypatch):
    req = core.AgentChatRequest(**body(access_key=KEY))
    request = wrapper._request_for_agent(6060)
    actor = core._agent_bind_actor(req, request)
    assert actor.surface == "telegram" and not actor.private
    assert not core._execute_agent_tool("search_project_knowledge",
        {"query": "syntheticboundary", "source": "rules"}, req, {})["available"]
    forged = Request({"type": "http", "method": "POST", "path": "/agent/chat",
        "headers": [], "query_string": b"", "plato_bot_actor": ("client-claimed", 777)})
    assert not core._agent_resolve_actor(None, forged).private


def test_signing_key_survives_cleanup_is_private_and_shared_across_workers():
    with TestClient(core.app) as client:
        assert client.get("/agent/status").status_code == 200
        cookie = client.cookies.get(agent_access.COOKIE)
    key = core._PLATO_STAGE_DIR / ".owner-signing-key"
    assert key.stat().st_mode & 0o777 == 0o600
    before = key.read_bytes()
    os.utime(key, (1, 1))
    core._plato_stage_cleanup()
    assert key.read_bytes() == before
    owner, renewed = agent_access.browser_owner(core._PLATO_STAGE_DIR, cookie)
    assert owner.startswith("browser:") and renewed is None


def test_admin_telegram_login_alone_cannot_read_internal_notes(monkeypatch):
    captures = fake_search(monkeypatch)
    token = core._telegram_session(777, [])
    response = TestClient(core.app).post("/agent/chat", json=body(session=token))
    assert response.status_code == 200
    assert PRIVATE not in json.dumps(captures)


def test_own_document_question_and_history_are_still_sent_without_private_key(monkeypatch):
    captures = fake_search(monkeypatch)
    token = session()
    response = TestClient(core.app).post("/agent/chat", json=body(session=token,
        message="Продажи моего проекта OWN_SALES_AMOUNT=123.45: объясни мою модель",
        history=[{"role": "user", "content": "OWN_PRIOR_QUESTION"}],
        document={"filename": "own.txt", "text": "OWN_DOCUMENT_AMOUNT=567.89"}))
    assert response.status_code == 200
    encoded = json.dumps(captures, ensure_ascii=False)
    assert "OWN_SALES_AMOUNT=123.45" in encoded
    assert "OWN_PRIOR_QUESTION" in encoded
    assert "OWN_DOCUMENT_AMOUNT=567.89" in encoded
    assert PRIVATE not in encoded


def test_poll_does_not_bill_or_recalculate_and_old_private_cache_is_not_reused(monkeypatch):
    captures = fake_search(monkeypatch)
    client = TestClient(core.app)
    response = client.post("/agent/chat", json=body(access_key=KEY))
    trace = response.json()["trace_id"]
    with monkeypatch.context() as polling:
        polling.setattr(core, "require_calc_access", lambda *a, **kw: pytest.fail("poll billed credits"))
        polling.setattr(core, "_run_authoritative_model", lambda *a, **kw: pytest.fail("poll recalculated"))
        for route in ("result", "trace"):
            assert client.get(f"/agent/{route}/{trace}", headers=poll_headers(key=KEY)).status_code == 200
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-synthetic-key")
    captures.clear()
    fresh = client.post("/agent/chat", json=body(access_key="new-synthetic-key"))
    assert fresh.status_code == 200 and not fresh.json()["cached"]
    assert len(captures) == 2


def test_rotation_before_private_tool_prevents_private_read_and_next_llm(monkeypatch):
    captures = []
    def rotate(payload, **kw):
        captures.append(copy.deepcopy(payload))
        monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-synthetic-key")
        return {"output": [{"type": "function_call", "name": "search_project_knowledge",
                            "call_id": "synthetic", "arguments": json.dumps(
                                {"query": "syntheticboundary", "source": "rules"})}]}
    monkeypatch.setattr(core, "_openai_responses_request", rotate)
    monkeypatch.setattr(knowledge, "_file_entries", lambda *a: pytest.fail("private source read after rotation"))
    response = TestClient(core.app).post("/agent/chat", json=body(access_key=KEY))
    assert response.status_code == 403
    assert len(captures) == 1
    assert PRIVATE not in json.dumps(captures)


def test_owner_cookie_survives_initial_worker_failure(monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("synthetic model failure")
    monkeypatch.setattr(core, "_call_openai_tool_agent", fail)
    client = TestClient(core.app)
    token = session()
    trace = "aabbccdd" * 4
    failed = client.post("/agent/chat", json=body(session=token, trace_id=trace))
    assert failed.status_code == 500
    assert agent_access.COOKIE in client.cookies
    stored = client.get("/agent/result/" + trace, headers=poll_headers(token))
    assert stored.status_code == 200 and "synthetic model failure" in stored.json()["error"]


def test_public_adapter_cookie_handoff_and_sink_rejects_private_runs(monkeypatch):
    import main_registry
    from fastapi import FastAPI
    from starlette.requests import Request

    app = FastAPI()
    app.middleware("http")(core._agent_owner_cookie)
    def adapter(request: Request):
        trace = request.query_params.get("trace")
        if trace:
            return main_registry._plato_result(trace, request)
        return main_registry._plato_ask("syntheticboundary query", request)
    app.add_api_route("/synthetic-adapter/ask", adapter, methods=["POST"])
    app.add_api_route("/agent/result/{trace_id}", core.agent_result, methods=["GET"])
    app.add_api_route("/agent/chat", core.agent_chat, methods=["POST"])
    waiting, release = threading.Event(), threading.Event()
    observed = []
    def answer(req, bundle, **kw):
        observed.append(core._agent_actor_current(req))
        waiting.set()
        assert release.wait(2)
        return {"answer": "PUBLIC_ADAPTER_ANSWER", "model": "fake"}
    monkeypatch.setattr(core, "_call_openai_tool_agent", answer)
    monkeypatch.setattr(core, "_PLATO_CHAT_HANDOFF_SECONDS", 0)
    client = TestClient(app)
    pending = client.post("/synthetic-adapter/ask", headers=poll_headers(key=KEY))
    assert pending.status_code == 200 and pending.json()["pending"]
    assert agent_access.COOKIE in client.cookies
    assert pending.headers["cache-control"] == "no-store"
    assert waiting.wait(1)
    assert not observed[0].private
    release.set()
    trace = pending.json()["trace_id"]
    # The actual adapter now forwards Request and checks the sink's scope.
    for _ in range(100):
        stored = client.post("/synthetic-adapter/ask?trace=" + trace)
        if not stored.json().get("pending"):
            break
    assert stored.status_code == 200 and stored.json()["answer"] == "PUBLIC_ADAPTER_ANSWER"
    forbidden = TestClient(app).post("/synthetic-adapter/ask?trace=" + trace)
    assert forbidden.status_code == 403
    private = client.post("/agent/chat", json=body(access_key=KEY))
    private_trace = private.json()["trace_id"]
    relabel = client.post("/synthetic-adapter/ask?trace=" + private_trace, headers=poll_headers(key=KEY))
    assert relabel.status_code == 403


def test_private_intake_key_rotation_and_unauthorized_read_fail_before_content_load(monkeypatch):
    monkeypatch.setattr(core.document_intake, "extract_text", lambda *a: {"text": "OWN_DOCUMENT", "filename": "own.txt"})
    monkeypatch.setattr(core, "document_intake_read", lambda *a: {"notes": [PRIVATE], "fields": [], "questions": []})
    client = TestClient(core.app)
    response = client.post("/agent/document", json={"access_key": KEY, "filename": "own.txt",
        "content_b64": base64.b64encode(b"own").decode()})
    assert response.status_code == 200
    intake_id = response.json()["card"]["id"]
    assert client.post("/agent/document/card", json={"access_key": KEY, "intake_id": intake_id}).status_code == 200
    monkeypatch.setattr(core, "_intake_queue_path", lambda *a: pytest.fail("unauthorized private document read"))
    other = TestClient(core.app)
    denied = other.post("/agent/document/card", json={"session": session(), "intake_id": intake_id})
    assert denied.status_code == 403
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-synthetic-key")
    denied = client.post("/agent/document/card", json={"access_key": "new-synthetic-key", "intake_id": intake_id})
    assert denied.status_code == 403


def test_signing_key_atomic_creation_across_competing_workers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    directory = tmp_path / "new-state"
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: agent_access.secret(directory), range(32)))
    assert len(set(values)) == 1
    assert len(values[0]) == 32
    assert not list(directory.glob(".owner-key-*"))


def test_public_report_proof_is_bound_to_verified_public_run_and_content():
    slug = "synthetic"
    request = Request({"type": "http", "method": "POST", "path": "/auctions/krt/synthetic/plato",
                       "headers": [], "query_string": b""})
    req = core.AgentChatRequest(**body(access_key=KEY))
    actor = core._agent_bind_actor(req, request)
    assert not actor.private
    public_trace = "11223344" * 4
    agent_access.claim(core._PLATO_STAGE_DIR, public_trace, actor)
    proof = core._agent_public_reply_stamp(public_trace, request, slug, "safe public reply")
    payload = {"text": "safe public reply", **proof}
    assert core._agent_public_reply_valid(slug, payload)
    assert not core._agent_public_reply_valid(slug, {**payload, "text": PRIVATE})
    assert not core._agent_public_reply_valid("different-lot", payload)
    assert not core._agent_public_reply_valid(slug, {"text": PRIVATE, "public_sources_version": 1})
    private_actor = core._agent_bind_actor(req, request, private_surface="monitor")
    private_trace = "55667788" * 4
    agent_access.claim(core._PLATO_STAGE_DIR, private_trace, private_actor)
    with pytest.raises(core.HTTPException) as denied:
        core._agent_public_reply_stamp(private_trace, request, slug, PRIVATE)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("body_current,header_current", [(False,True),(True,False)])
def test_monitor_key_conflict_binds_the_credential_that_actually_passed_gate(monkeypatch, body_current, header_current):
    fake_search(monkeypatch)
    client=TestClient(core.app)
    response=client.post("/monitor/ask",json={"message":"syntheticboundary query",
        "key":KEY if body_current else "stale-body-key"},
        headers={"X-Developaid-Admin-Key":KEY if header_current else "stale-header-key"})
    assert response.status_code==200,response.text
    trace=response.json()["trace_id"]
    metadata=agent_access.load(core._PLATO_STAGE_DIR,trace)
    assert metadata["surface"]=="monitor" and metadata["private"] is True
    assert metadata["acl"]!="public"
    assert client.get("/agent/result/"+trace).status_code==403
    assert client.get("/agent/result/"+trace,headers=poll_headers(key=KEY)).status_code==200
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY","rotated-synthetic-key")
    for route in ("result","trace"):
        for key in ("",KEY,"rotated-synthetic-key"):
            denied=client.get(f"/agent/{route}/{trace}",headers=poll_headers(key=key))
            assert denied.status_code==403
            assert PRIVATE not in denied.text


def test_monitor_actor_never_silently_becomes_public(monkeypatch):
    request=Request({"type":"http","method":"POST","path":"/monitor/ask",
                     "headers":[],"query_string":b""})
    with pytest.raises(core.HTTPException) as denied:
        core._agent_resolve_actor(None,request,surface="monitor")
    assert denied.value.status_code==403
