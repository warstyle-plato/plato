"""Демо-ссылка по разделам и на срок (решение владельца 25.10.2026).

Ссылка открывает галочками любой набор из шести разделов («Расчёт», «Личный
кабинет», «Монитор стройки», «Сводка руководству», «Торги и КРТ», «Рынок») или
все шесть, на 1, 5 или 30 дней. В мониторе, сводке, торгах и рынке человек по
ссылке видит настоящие данные владельца, но только читает. Здесь закреплено:

- раздел, которого нет в ссылке, отвечает отказом с названием раздела, а
  раздел из ссылки читается;
- любой записывающий маршрут команды демо отказывает, даже по полной ссылке,
  и запись не происходит; монитор — по всем своим маршрутам, кроме явно
  названных чтением;
- споры и претензии закрыты демо всегда: и маршрутами, и в самой сводке;
- истёкшая и отозванная ссылка не пускает ни сессией, ни кукой;
- срок — только 1, 5 или 30 дней, без разделов ссылки нет; старая запись без
  поля разделов — прежнее умолчание (расчёт и кабинет), а не «ничего»;
- журнал пишет, кто выдал, какие разделы, срок и каждый вход;
- админ-форма на отрисованной странице выдаёт ссылку с выбранными разделами.

Запуск: python3 -m pytest tests/test_demo_scope.py -q
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402
import main_registry  # noqa: E402,F401  — торги и кабинет рынка на том же приложении

core = _wrapper.core
client = TestClient(core.app, raise_server_exceptions=False)
OWNER = 777
ALL = ["calc", "cabinet", "monitor", "report", "auctions", "market"]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:demo-scope-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(OWNER))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setenv("MARKET_CABINET_KEY", "team-market-key")
    monkeypatch.delenv("DEVELOPAID_TEAM_IDS", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core._DEMO_ALIVE_CACHE.clear()
    yield


def invite(blocks: list[str], days: int = 5) -> str:
    answer = client.post("/access/admin/demo/create",
                         json={"key": "kluch", "note": "проверка", "days": days,
                               "blocks": blocks})
    assert answer.status_code == 200, answer.text
    return answer.json()["code"]


def claim(code: str) -> tuple[str, TestClient]:
    """Сессия демо и браузер с её кукой — как после перехода по ссылке."""
    browser = TestClient(core.app, raise_server_exceptions=False)
    answer = browser.post("/demo/claim", json={"code": code})
    assert answer.status_code == 200, answer.text
    assert browser.cookies.get(core.DEMO_COOKIE), "кука демо не поставлена"
    return answer.json()["session"], browser


_FILL = {str: "проверка", int: 1, float: 1.0, bool: True, list: [], dict: {}}


def body(session: str, path: str = "") -> dict:
    """Тело, которое модель маршрута примет: отказ доступа обязан прийти
    после разбора тела, а не спрятаться за 422. Поля — по самой модели."""
    out: dict = {"session": session, "project": "проверка", "message": "что со сроками?",
                 "text": "запись", "topic": "тема"}
    route = next((r for r in core.app.routes
                  if getattr(r, "path", "") == path and "POST" in getattr(r, "methods", ())), None)
    for param in getattr(getattr(route, "dependant", None), "body_params", []) or []:
        model = getattr(param.field_info, "annotation", None) or param.type_
        for name, field in getattr(model, "model_fields", {}).items():
            if field.is_required() and name not in out:
                kind = getattr(field.annotation, "__origin__", None) or field.annotation
                out[name] = _FILL.get(kind, "проверка")
    return out


# --- раздел: без него отказ с названием, с ним — чтение ---------------------------

def calc(session: str, browser: TestClient):
    return browser.post("/calculate", json={
        "session": session, "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {key: dict(value) for key, value in core.TEP_DEFAULT.items()}})


def cabinet(session: str, browser: TestClient):
    return browser.post("/projects/list", json={"session": session})


def monitor(session: str, browser: TestClient):
    return browser.get("/monitor/snapshots", params={"project": "проверка", "session": session})


def report(session: str, browser: TestClient):
    return browser.post("/monitor/report/projects", json={"session": session})


def auctions(session: str, browser: TestClient):
    return browser.get("/auctions/krt/watch")


def market(session: str, browser: TestClient):
    return browser.get("/cabinet/market", headers={"accept": "text/html"})


READS = {"calc": (calc, "Расчёт"), "cabinet": (cabinet, "Личный кабинет"),
         "monitor": (monitor, "Монитор стройки"), "report": (report, "Сводка руководству"),
         "auctions": (auctions, "Торги и КРТ"), "market": (market, "Рынок")}


@pytest.mark.parametrize("block", ALL)
def test_a_link_without_the_section_is_refused_by_name(block):
    others = [name for name in ALL if name != block]
    session, browser = claim(invite(others))
    reader, name = READS[block]
    answer = reader(session, browser)
    assert answer.status_code == 403, (block, answer.status_code, answer.text[:300])
    assert f"не открывает раздел «{name}»" in answer.text


@pytest.mark.parametrize("block", ALL)
def test_a_link_with_the_section_reads_it(block):
    session, browser = claim(invite([block]))
    reader, _name = READS[block]
    answer = reader(session, browser)
    assert answer.status_code == 200, (block, answer.status_code, answer.text[:300])
    assert "не открывает раздел" not in answer.text and "только для просмотра" not in answer.text


def test_the_access_plaque_names_the_closed_calc_section():
    """Плашка до расчёта (`/access/check`, без списания) отвечает решением с
    причиной, а не отказом: её читает страница, не маршрут расчёта."""
    session, browser = claim(invite(["cabinet"]))
    answer = browser.post("/access/check", json={"session": session, "inputs": {}})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["allowed"] is False and data["code"] == "demo_section"
    assert "не открывает раздел «Расчёт»" in data["detail"]


def test_the_report_reads_real_projects_of_the_owner():
    session, browser = claim(invite(["report"]))
    team = client.post("/monitor/report/projects", json={"key": "kluch"}).json()
    seen = browser.post("/monitor/report/projects", json={"session": session}).json()
    assert seen == team, "демо видит не те проекты, что команда"


# --- запись: отказ всегда, и ничего не записано ------------------------------------

_GATE = re.compile(
    r'@app\.(get|post)\("(?P<path>/monitor[^"]*)".*?\n(?:.*\n){0,40}?.*?'
    r'_require_team_access\((?P<args>[^)]*)\)', re.MULTILINE)


def monitor_routes() -> dict[str, bool]:
    """Маршрут монитора → «только читает» по тексту его проверки."""
    text = (ROOT / "engine" / "monitor.py").read_text(encoding="utf-8")
    routes = {}
    for match in _GATE.finditer(text):
        args = match.group("args")
        routes[match.group("path")] = "write=False" in args.replace(" ", "")
    return routes


# Чтение монитора и сводки — названо явно. Новый маршрут попадает в запись,
# пока его не перенесли сюда; лишнее «чтение» в коде роняет эту проверку.
MONITOR_READS = {"/monitor/snapshots", "/monitor/view", "/monitor/rewritten", "/monitor/ask",
                 "/monitor/doubts", "/monitor/crew", "/monitor/daily/summary",
                 "/monitor/photo", "/monitor/report/projects", "/monitor/report",
                 "/monitor/report.pdf", "/monitor/gantt", "/monitor/scenario"}
# Чтение или запись по содержимому запроса: отметка снимка, новая запись.
MONITOR_MIXED = {"/monitor/photos", "/monitor/notes"}


def test_the_monitor_reads_are_exactly_the_named_ones():
    routes = monitor_routes()
    assert len(routes) > 30, "разбор маршрутов монитора не нашёл их"
    reads = {path for path, read in routes.items() if read}
    assert reads == MONITOR_READS


WRITES = sorted(path for path, read in monitor_routes().items()
                if not read and path not in MONITOR_MIXED)


@pytest.mark.parametrize("path", WRITES)
def test_a_full_link_never_writes_to_the_monitor(path):
    session, browser = claim(invite(ALL))
    answer = browser.post(path, json=body(session, path))
    assert answer.status_code == 403, (path, answer.status_code, answer.text[:300])
    detail = answer.json()["detail"]
    assert "только для просмотра" in detail or "Споры и претензии" in detail or \
        "закрыт" in detail, detail


def test_a_demo_note_is_refused_and_not_stored(monkeypatch):
    stored = []
    import developaid_project_notes as notes

    monkeypatch.setattr(notes, "add", lambda *a, **k: stored.append(a))
    monkeypatch.setattr(notes, "notes", lambda project: [])
    session, browser = claim(invite(ALL))
    listed = browser.post("/monitor/notes", json={"project": "проверка", "session": session})
    assert listed.status_code == 200, listed.text
    added = browser.post("/monitor/notes", json={"project": "проверка", "session": session,
                                                 "topic": "Срок", "text": "сдвиг"})
    assert added.status_code == 403 and "только для просмотра" in added.json()["detail"]
    assert stored == [], "запись демо дошла до хранилища"


def test_a_demo_cannot_mark_a_photo_but_sees_the_feed(monkeypatch):
    import developaid_site_photos as photos

    chosen = []
    monkeypatch.setattr(photos, "select", lambda *a, **k: chosen.append(a))
    monkeypatch.setattr(photos, "photos", lambda *a, **k: [])
    session, browser = claim(invite(["report"]))
    feed = browser.post("/monitor/photos", json={"project": "проверка", "session": session})
    assert feed.status_code == 200, feed.text
    mark = browser.post("/monitor/photos", json={"project": "проверка", "session": session,
                                                 "photo_id": "a1", "chosen": True})
    assert mark.status_code == 403 and chosen == []


@pytest.mark.parametrize("method,path", [
    ("post", "/auctions/krt/demo-slug/tender-order"),
    ("post", "/auctions/ingest"),
    ("post", "/auctions/lot-notes/request"),
    ("post", "/auctions/krt/ranking/refresh"),
    # Пишут в общее хранилище: лоты площадки и отчёт Платона на карточке.
    ("post", "/auctions/krt/tenders"),
    ("post", "/auctions/krt/demo-slug/plato"),
    ("post", "/auctions/krt/demo-slug/plato?trace_id=abc"),
    # Маршрута нет в перечне чтения — значит запись, даже если он новый.
    ("post", "/auctions/some-new-route"),
    ("get", "/auctions/krt/demo-slug/investment-score?ensure_model=1"),
    ("get", "/auctions/torgi/probe"),
    ("get", "/auctions/krt/watch?refresh=1"),
    ("post", "/cabinet/contracting"),
    ("post", "/market/pulse/regions/run"),
    ("post", "/cabinet/plan"),
    ("get", "/market/bnmap/probe"),
])
def test_a_full_link_never_writes_to_auctions_or_market(method, path):
    _session, browser = claim(invite(ALL))  # переход по ссылке: несёт только куку
    answer = getattr(browser, method)(path, **({"json": {}} if method == "post" else {}))
    assert answer.status_code == 403, (path, answer.status_code, answer.text[:300])
    assert "только для просмотра" in answer.json()["detail"]


def test_the_market_key_still_writes_where_the_demo_cannot():
    """Подделка «всё запрещено» не пройдёт: команда тем же маршрутом проходит замок."""
    answer = client.post("/auctions/krt/demo-slug/tender-order", json={},
                         headers={"X-Market-Key": "team-market-key"})
    assert answer.status_code not in (401, 403), answer.text[:300]


@pytest.mark.parametrize("path", ["/monitor/legal", "/monitor/legal/doc",
                                  "/monitor/legal/export"])
def test_disputes_stay_closed_even_for_a_full_link(path):
    session, browser = claim(invite(ALL))
    answer = browser.post(path, json=body(session, path))
    assert answer.status_code == 403
    assert "Споры и претензии" in answer.json()["detail"]


def test_the_report_has_no_disputes_for_a_demo(monkeypatch):
    import developaid_management_report as management_report

    def fake_build(project, kind, end, sales_project=None):
        return {"project": project, "legal": {"state": "ok", "open": [{"card": {}}],
                                              "recorded": True}}

    monkeypatch.setattr(management_report, "build", fake_build)
    monkeypatch.setattr(management_report, "render_text", lambda report: "")
    monkeypatch.setattr(management_report, "render_html", lambda report: "")
    session, browser = claim(invite(["report"]))
    demo = browser.post("/monitor/report", json={"project": "проверка", "session": session})
    assert demo.status_code == 200, demo.text
    assert demo.json()["report"]["legal"]["state"] == "closed"
    team = client.post("/monitor/report", json={"project": "проверка", "key": "kluch"}).json()
    assert team["report"]["legal"]["state"] == "ok", "команда споры видит"


def test_the_closed_disputes_read_as_a_reason_in_the_report():
    import developaid_management_report as management_report

    closed = {"state": "closed", "reason": core.DEMO_DISPUTES_CLOSED}
    assert core.DEMO_DISPUTES_CLOSED in management_report._legal_html(closed)


def test_admin_and_access_stay_closed_for_a_full_link():
    session, browser = claim(invite(ALL))
    for path in ("/access/admin/overview", "/access/admin/demo/list",
                 "/access/admin/demo/create", "/monitor/report/mailing"):
        answer = browser.post(path, json={"session": session, "project": "проверка",
                                          "days": 5, "blocks": ALL})
        assert answer.status_code == 403, (path, answer.text)


# --- срок, отзыв, старые записи -----------------------------------------------------

def test_a_revoked_link_closes_the_session_and_the_cookie():
    code = invite(ALL)
    session, browser = claim(code)
    assert monitor(session, browser).status_code not in (401, 403)
    client.post("/access/admin/demo/revoke", json={"key": "kluch", "code": code})
    assert monitor(session, browser).status_code in (401, 403)
    answer = auctions(session, browser)
    assert answer.status_code == 403 and "закончился" in answer.json()["detail"]
    assert market(session, browser).status_code == 403


def test_an_expired_link_lets_nobody_in():
    code = invite(ALL)
    session, browser = claim(code)
    record = core._demo_read(code)
    record["expires"] = time.time() - 1
    core._demo_write(record)
    core._DEMO_ALIVE_CACHE.clear()
    assert core._web_identity_chat_id(session) == 0
    assert report(session, browser).status_code in (401, 403)
    assert auctions(session, browser).status_code == 403
    assert client.post("/demo/claim", json={"code": code}).status_code == 410


@pytest.mark.parametrize("days", [0, 2, 14, 60])
def test_only_three_terms_are_issued(days):
    answer = client.post("/access/admin/demo/create",
                         json={"key": "kluch", "days": days, "blocks": ALL})
    assert answer.status_code == 400 and "1, 5 или 30" in answer.json()["detail"]


@pytest.mark.parametrize("days", [1, 5, 30])
def test_each_term_sets_its_expiry(days):
    code = invite(["calc"], days)
    record = core._demo_read(code)
    assert abs(record["expires"] - record["created"] - days * 86400) < 1


def test_a_link_needs_at_least_one_known_section():
    for blocks in ([], ["admin"]):
        answer = client.post("/access/admin/demo/create",
                             json={"key": "kluch", "days": 5, "blocks": blocks})
        assert answer.status_code == 400, blocks


def test_an_old_link_without_sections_keeps_calc_and_cabinet():
    code = invite(["monitor"])
    record = core._demo_read(code)
    del record["blocks"]
    core._demo_write(record)
    session, browser = claim(code)
    assert cabinet(session, browser).status_code == 200
    assert "не открывает раздел «Монитор стройки»" in monitor(session, browser).text


# --- журнал и кабинет ----------------------------------------------------------------

def test_the_journal_names_who_what_term_and_entries():
    code = invite(["monitor", "report"], 30)
    claim(code)
    claim(code)
    chat = core._demo_read(code)["chat"]
    events = [e for e in core.access_journal_read(500) if e.get("chat") == chat]
    created = [e for e in events if e["event"] == "demo_create"]
    assert created and created[0]["by"] == OWNER and created[0]["days"] == 30
    assert created[0]["blocks"] == ["monitor", "report"]
    assert len([e for e in events if e["event"] == "demo_claim"]) == 2
    listed = client.post("/access/admin/demo/list", json={"key": "kluch"}).json()
    row = next(r for r in listed["invites"] if r["code"] == code)
    assert row["claims"] == 2 and len(row["entries"]) == 2
    assert row["blocks"] == ["monitor", "report"]


def test_the_cabinet_lists_the_open_sections():
    session, browser = claim(invite(["calc", "monitor"]))
    me = browser.post("/access/me", json={"session": session}).json()
    assert [(x["name"], x["read_only"]) for x in me["demo_sections"]] == [
        ("Расчёт", False), ("Монитор стройки", True)]


# --- на отрисованной странице -----------------------------------------------------

def test_the_admin_issues_a_link_with_chosen_sections_in_a_browser():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    admin = core._telegram_session(OWNER, [])
    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18992) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 390, "height": 844})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.add_init_script(
                f"localStorage.setItem('developaid_web_session', {json.dumps(admin)})")
            page.goto(base, wait_until="networkidle")
            page.click("#tariffsButton")
            page.wait_for_selector("#demoInviteBlocks .demo-block")
            labels = page.locator("#demoInviteBlocks label").all_inner_texts()
            assert [x.strip() for x in labels] == [
                "Полный доступ", "Расчёт", "Личный кабинет", "Монитор стройки",
                "Сводка руководству", "Торги и КРТ", "Рынок"]
            days = page.locator("#demoInviteDays button").all_inner_texts()
            assert days == ["1 день", "5 дней", "30 дней"]
            # Без разделов ссылка не выдаётся — причина на экране.
            page.click("#demoInviteDays button:has-text('1 день')")
            assert "Отметьте разделы" in page.inner_text("#demoInviteStatus")
            # «Полный доступ» отмечает все шесть, снятая галочка его снимает.
            page.check("#demoBlockAll")
            assert page.locator("#demoInviteBlocks .demo-block:checked").count() == 6
            page.uncheck("#demoInviteBlocks .demo-block[value='market']")
            assert not page.is_checked("#demoBlockAll")
            page.uncheck("#demoInviteBlocks .demo-block[value='calc']")
            page.uncheck("#demoInviteBlocks .demo-block[value='cabinet']")
            page.uncheck("#demoInviteBlocks .demo-block[value='auctions']")
            page.click("#demoInviteDays button:has-text('30 дней')")
            page.wait_for_function(
                "document.getElementById('demoInviteStatus').textContent.includes('Ссылка создана')")
            row = page.inner_text("#demoInviteList tr:first-child")
            assert "Разделы: Монитор стройки, Сводка руководству" in row
            page.close()
    assert not errors, errors
    newest = client.post("/access/admin/demo/list", json={"key": "kluch"}).json()["invites"][0]
    assert newest["blocks"] == ["monitor", "report"]
    assert abs(newest["expires"] - newest["created"] - 30 * 86400) < 1
