"""Synthetic offline proofs at the real wrapper and core authorization boundaries."""
import base64
import copy
import datetime
import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from market_search import sales_dialogue, sales_store
from test_platon_asks_the_sales_chat import _report, _row
from test_the_bot_is_silent_in_the_site_chat import REPORT as DAILY

KEY = "synthetic-owner-key-for-tests"
PROJECT = "Synthetic Private Project"
SALES = "Synthetic Private Sales"
MARKER = "PRIVATE_OTHER_PROJECT_UNIT_SENTINEL"
GROUP = -10099999
OTHER_GROUP = -10088888


@pytest.fixture()
def bot(monkeypatch, tmp_path):
    import main as wrapper
    import developaid_monitor as monitor
    import developaid_management_report as management

    core = wrapper.core
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "101")
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(core, "_USAGE_DIR", tmp_path / "usage")
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setattr(core, "_telegram_token", lambda: "123:synthetic-token")
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "usage_track", lambda *a, **kw: None)
    monkeypatch.setattr(wrapper, "_user_to_core", lambda *a, **kw: None)
    monkeypatch.setattr(core, "_telegram_api", lambda *a, **kw: {})
    sent, model = [], []
    def send(chat, text, **kwargs):
        sent.append((chat, text))
        return {"message_id": 888}
    monkeypatch.setattr(core, "_telegram_send_message", send)
    monkeypatch.setattr(wrapper, "_send_message", send)
    monkeypatch.setattr(core, "_openai_responses_request", lambda payload, **kw: model.append(copy.deepcopy(payload)))
    monkeypatch.setattr(core, "_site_photo_async", core._site_photo_job)
    data = io.BytesIO()
    Image.new("RGB", (4, 4)).save(data, format="JPEG")
    monkeypatch.setattr(core, "_telegram_file_bytes", lambda *a: data.getvalue())
    today = datetime.date.today()
    row = _row((today-datetime.timedelta(days=30)).isoformat(), MARKER, "1K", 40, 8000000, 0)
    sales_store.save(sales_store.default_dir(), SALES, {"contracting": {"rows": [row]}}, "synthetic.xlsx")
    monitor._project_dir(PROJECT)
    management.link_sales(PROJECT, SALES, "synthetic test")
    core.app.state.telegram_group_seen = {}
    wrapper.fixture = dict(sent=sent, model=model, jpeg=data.getvalue(), root=tmp_path)
    return wrapper


def update(bot, text="", chat=GROUP, **extras):
    msg = {"chat": {"id": chat, "type": "supergroup", "title": "Untrusted group"},
           "from": {"id": 909, "first_name": "Outsider"}, "text": text,
           "date": int(time.time()), "message_id": 777}
    msg.update(extras)
    bot._handle_update({"message": msg})


def authorize(bot, chat=GROUP, project=PROJECT, key=KEY):
    return bot.core.monitor_site_chat_authorize(bot.core.SiteChatAccessRequest(
        chat_id=chat, project=project, key=key))


def revoke(bot, chat=GROUP, project=PROJECT):
    return bot.core.monitor_site_chat_revoke(bot.core.SiteChatAccessRequest(
        chat_id=chat, project=project, key=KEY))


def sales_report():
    return _report(datetime.date.today().strftime("%d.%m.%Y"), [])


def business_files(bot):
    """Record bytes, not only response codes: no hidden journal/report writes."""
    root = bot.fixture["root"]
    return {str(p.relative_to(root)): p.read_bytes() for top in (root / "data", root / "monitor")
            for p in top.rglob("*") if p.is_file() and p.suffix != ".lock"}


def test_outsider_site_known_project_cannot_read_or_write_any_closed_source(bot):
    import developaid_report_mailing as mailing

    assert not bot.core._telegram_user_allowed(909)
    assert mailing.subscribed_projects(909) == []
    before = business_files(bot)
    update(bot, "/site " + PROJECT)
    assert bot.core._site_chat_project(GROUP) == ""
    assert not bot.core._site_chats_path().exists()
    update(bot, "/audit@synthetic_bot " + sales_report())
    update(bot, DAILY)
    update(bot, photo=[{"file_id": "image", "file_unique_id": "photo1", "width": 4, "height": 4}])
    update(bot, "untrusted reply", reply_to_message={"message_id": 888,
           "from": {"id": 123, "is_bot": True},
           "text": "Извините, это Платон Сергеевич Федоскин, у меня возник вопрос. Когда оплата?"})
    assert business_files(bot) == before
    assert MARKER not in json.dumps(bot.fixture["sent"] + bot.fixture["model"])
    assert not [text for chat, text in bot.fixture["sent"] if chat == GROUP]
    assert bot.fixture["model"] == []
    assert any(str(GROUP) in text and "кабинете" in text for _, text in bot.fixture["sent"])


def test_legacy_binding_paid_subscription_and_forged_actor_are_not_grants(bot):
    import developaid_report_mailing as mailing

    core = bot.core
    core._site_chat_bind(GROUP, PROJECT, "Old group")
    mailing.subscribe(mailing.invite(PROJECT, "synthetic")["start"], 909, "")
    assert core._site_chat_project(GROUP) == ""
    before = business_files(bot)
    for endpoint, model, code, extra in (
        (core.internal_monitor_daily, core.SiteChatReportRequest, "monitor-daily", {"project": PROJECT, "text": DAILY}),
        (core.internal_monitor_photo, core.SitePhotoRequest, "monitor-photo", {"project": PROJECT, "data": base64.b64encode(bot.fixture["jpeg"]).decode()}),
        (core.internal_monitor_sales_chat, core.SalesChatRequest, "monitor-sales", {"project": PROJECT, "text": sales_report()}),
    ):
        req = model(chat_id=GROUP, sign=core._web_login_sign(code, GROUP),
                    caller="owner", is_admin=True, author_id=101, key=KEY, **extra)
        with pytest.raises(core.HTTPException) as caught:
            endpoint(req)
        assert caught.value.status_code == 403
    update(bot, "/site " + PROJECT, **{"from": {"id": 101, "is_admin": True}})
    update(bot, sales_report(), **{"from": {"id": 101, "is_admin": True}})
    assert business_files(bot) == before
    assert MARKER not in json.dumps(bot.fixture["sent"] + bot.fixture["model"])


def test_current_owner_authorizes_exact_group_and_project_and_preserves_history(bot):
    core = bot.core
    authorize(bot)
    serialized = core._site_chat_grants_path().read_text()
    assert KEY not in serialized
    assert core._site_chat_project(GROUP) == PROJECT
    update(bot, sales_report())
    question = next(text for chat, text in bot.fixture["sent"] if chat == GROUP)
    assert MARKER in question
    where = sales_store.default_dir()
    journal = sales_dialogue.load(where, SALES)
    assert len(journal["batches"]) == 1
    update(bot, DAILY)
    update(bot, photo=[{"file_id": "image", "file_unique_id": "photo1", "width": 4, "height": 4}])
    import developaid_monitor as monitor
    import developaid_site_photos as photos
    assert list((monitor._project_dir(PROJECT) / "daily").glob("*.json"))
    assert len(photos.photos(PROJECT)) == 1
    # A group message cannot replace an approved mapping with another project.
    update(bot, "/site Other Project")
    assert core._site_chat_project(GROUP) == PROJECT
    # Reauthorization resumes the durable asked/reply journal, without repetition.
    revoke(bot)
    authorize(bot)
    bot.fixture["sent"].clear()
    update(bot, sales_report())
    assert not [text for chat, text in bot.fixture["sent"] if chat == GROUP]
    update(bot, "Synthetic team answer", reply_to_message={"message_id": 888,
           "from": {"id": 123, "is_bot": True}, "text": question})
    after = sales_dialogue.load(where, SALES)
    assert len(after["batches"]) == 1
    assert len(next(iter(after["batches"].values()))["replies"]) == 1
    assert bot.fixture["model"] == []


@pytest.mark.parametrize("mode", ["other-chat", "other-project", "tamper-project", "tamper-action", "rotate", "missing-key", "revoke"])
def test_scope_tampering_key_rotation_and_revoke_fail_closed(bot, monkeypatch, mode):
    core = bot.core
    authorize(bot)
    if mode == "rotate":
        monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-synthetic-key")
    elif mode == "missing-key":
        monkeypatch.delenv("DEVELOPAID_ADMIN_KEY")
    elif mode == "revoke":
        revoke(bot)
    elif mode.startswith("tamper"):
        path = core._site_chat_grants_path()
        raw = json.loads(path.read_text())
        grant = raw[str(GROUP)]["grant"]
        grant["project" if mode == "tamper-project" else "actions"] = "Other Project" if mode == "tamper-project" else ["sales:send"]
        path.write_text(json.dumps(raw))
    chat = OTHER_GROUP if mode == "other-chat" else GROUP
    project = "Other Project" if mode == "other-project" else PROJECT
    before = business_files(bot)
    for endpoint, model, code, extra in (
        (core.internal_monitor_daily, core.SiteChatReportRequest, "monitor-daily", {"text": DAILY}),
        (core.internal_monitor_photo, core.SitePhotoRequest, "monitor-photo", {"data": base64.b64encode(bot.fixture["jpeg"]).decode()}),
        (core.internal_monitor_sales_chat, core.SalesChatRequest, "monitor-sales", {"text": sales_report()}),
        (core.internal_monitor_sales_chat, core.SalesChatRequest, "monitor-sales", {"action": "send"}),
        (core.internal_monitor_sales_chat, core.SalesChatRequest, "monitor-sales", {"action": "reply"}),
        (core.internal_monitor_sales_chat, core.SalesChatRequest, "monitor-sales", {"action": "delivered"}),
    ):
        with pytest.raises(core.HTTPException) as caught:
            endpoint(model(chat_id=chat, project=project, sign=core._web_login_sign(code, chat), **extra))
        assert caught.value.status_code == 403
    assert business_files(bot) == before
    assert MARKER not in json.dumps(bot.fixture["sent"] + bot.fixture["model"])


def test_owner_api_checks_current_key_over_real_http_and_lists_legacy_for_migration(bot):
    core = bot.core
    core._site_chat_bind(GROUP, PROJECT, "Legacy group")
    body = {"chat_id": GROUP, "project": PROJECT, "caller": "owner", "is_admin": True}
    with TestClient(core.app) as client:
        for suffix in ("authorize", "revoke"):
            denied = client.post("/monitor/site-chats/" + suffix, json=body)
            assert denied.status_code == 403
            assert denied.headers["cache-control"] == "private, no-store"
        denied = client.get("/monitor/site-chats/access")
        assert denied.status_code == 403
        assert denied.headers["cache-control"] == "private, no-store"
        headers = {"x-developaid-admin-key": KEY}
        assert client.get("/monitor/site-chats/access", headers=headers).json()["chats"] == [
            {"chat_id": GROUP, "project": PROJECT, "title": "Legacy group", "authorized": False}]
        approved = client.post("/monitor/site-chats/authorize", json=body, headers=headers)
        assert approved.status_code == 200
        assert approved.headers["cache-control"] == "private, no-store"
        listing = client.get("/monitor/site-chats/access", headers=headers)
        assert listing.headers["cache-control"] == "private, no-store"
        assert all(secret not in listing.text for secret in (KEY, "signature", "_key_id", "_generation"))
        invalid = client.post("/monitor/site-chats/authorize", json={}, headers=headers)
        assert invalid.status_code == 422
        assert invalid.headers["cache-control"] == "private, no-store"
        assert client.get("/monitor/site-chats/access", headers=headers).json()["chats"][0]["authorized"]
        assert client.post("/monitor/site-chats/revoke", json=body, headers=headers).status_code == 200
        assert not client.get("/monitor/site-chats/access", headers=headers).json()["chats"][0]["authorized"]
        assert client.post("/monitor/site-chats/authorize", json={**body, "chat_id": 909}, headers=headers).status_code == 400
        assert client.post("/monitor/site-chats/authorize", json={**body, "project": "../private"}, headers=headers).status_code == 400


def test_group_send_rechecks_current_authorization_after_generation(bot, monkeypatch):
    core = bot.core
    authorize(bot)
    original = core._sales_chat_store
    def revoke_after_report(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("action", "report") == "report":
            revoke(bot)
        return result
    monkeypatch.setattr(core, "_sales_chat_store", revoke_after_report)
    update(bot, sales_report())
    assert not [text for chat, text in bot.fixture["sent"] if chat == GROUP]
    assert MARKER not in json.dumps(bot.fixture["sent"] + bot.fixture["model"])


def test_observed_key_rotation_permanently_retires_the_previous_generation(bot, monkeypatch):
    core = bot.core
    authorize(bot)
    old = json.loads(core._site_chat_grants_path().read_text())
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-synthetic-key")
    assert core._site_chat_project(GROUP) == ""
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    assert core._site_chat_project(GROUP) == ""
    # Replaying an individual old record into the current generation is refused.
    path = core._site_chat_grants_path()
    current = json.loads(path.read_text())
    current[str(GROUP)] = old[str(GROUP)]
    path.write_text(json.dumps(current))
    assert core._site_chat_project(GROUP) == ""
    authorize(bot)
    assert core._site_chat_project(GROUP) == PROJECT


def test_exact_group_scope_does_not_read_another_projects_records_or_journal(bot, monkeypatch):
    import developaid_monitor as monitor
    import developaid_management_report as management
    core = bot.core
    authorize(bot)
    other = "Other Project"
    other_sales = "Other Sales"
    monitor._project_dir(other)
    sales_store.save(sales_store.default_dir(), other_sales, {"contracting": {"rows": []}}, "synthetic.xlsx")
    management.link_sales(other, other_sales, "synthetic")
    authorize(bot, OTHER_GROUP, other)
    original_load = sales_store.load
    def scoped_load(where, project, *args, **kw):
        assert project != other_sales, "status read a project outside the group grant"
        return original_load(where, project, *args, **kw)
    monkeypatch.setattr(sales_store, "load", scoped_load)
    req = core.SiteChatsRequest(chat_id=GROUP, sign=core._web_login_sign("monitor-chats", GROUP))
    assert [item["project"] for item in core.internal_monitor_site_chats(req)["projects"]] == [PROJECT]
    # A broken foreign journal would fail the old global reply_project scan.
    foreign = sales_dialogue._path(sales_store.default_dir(), other_sales)
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("{broken")
    update(bot, sales_report())
    quote = next(text for chat, text in bot.fixture["sent"] if chat == GROUP)
    update(bot, "Scope-local answer", reply_to_message={"message_id": 888,
           "from": {"id": 123, "is_bot": True}, "text": quote})
    assert len(next(iter(sales_dialogue.load(sales_store.default_dir(), SALES)["batches"].values()))["replies"]) == 1


def test_question_send_requires_an_explicit_positive_core_recheck(bot, monkeypatch):
    core = bot.core
    authorize(bot)
    original = core._sales_chat_store
    def missing_confirmation(*args, **kwargs):
        if kwargs.get("action") == "send":
            return {}
        return original(*args, **kwargs)
    monkeypatch.setattr(core, "_sales_chat_store", missing_confirmation)
    update(bot, sales_report())
    assert not [text for chat, text in bot.fixture["sent"] if chat == GROUP]
    assert MARKER not in json.dumps(bot.fixture["sent"] + bot.fixture["model"])


def test_equal_group_titles_cannot_mix_private_status_outcomes(bot):
    core = bot.core
    authorize(bot)
    core.app.state.telegram_group_seen = {
        str(GROUP): {"title": "Shared title", "count": 1, "outcome": "Own group", "project": PROJECT},
        str(OTHER_GROUP): {"title": "Shared title", "count": 99, "outcome": "FOREIGN_STATUS_SENTINEL"},
    }
    core._site_chat_title_seen(GROUP, "Shared title")
    answer = core._telegram_bindings_line(GROUP)
    assert "Own group" in answer
    assert "FOREIGN_STATUS_SENTINEL" not in answer


def test_cached_status_outcome_from_a_former_project_is_not_reused(bot):
    core = bot.core
    authorize(bot)
    core.app.state.telegram_group_seen = {
        str(GROUP): {"title": "Same group", "count": 1,
                     "outcome": "FORMER_PROJECT_STATUS_SENTINEL", "project": "Former Project"}}
    answer = core._telegram_bindings_line(GROUP)
    assert "FORMER_PROJECT_STATUS_SENTINEL" not in answer
    assert PROJECT in answer


def test_observed_missing_key_retires_old_grants_and_old_key_cannot_mint_after_rotation(bot, monkeypatch):
    core = bot.core
    authorize(bot)
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY")
    assert core._site_chat_project(GROUP) == ""
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    assert core._site_chat_project(GROUP) == ""
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "new-synthetic-key")
    with pytest.raises(core.HTTPException) as caught:
        authorize(bot, key=KEY)
    assert caught.value.status_code == 403
