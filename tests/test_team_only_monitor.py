"""Монитор, сводка руководству и споры — только по ключу администратора.

Решение владельца 02.11.2026: «Надо убрать доступ к блоку report и monitor для
всех кроме обладателя ключа администратор». Здесь закреплено:

- маршруты берутся из регистрации `app` (все `/monitor*` и `/report`, кроме
  подписанных ботом `/internal/*` и выгрузок расчёта `/report/pdf|teaser|workbook`),
  а не списком руками: новый маршрут, оставшийся открытым, роняет тест;
- без ключа администратора — 403 с причиной «только по ключу администратора»
  для всех: сессия команды и админа по chat_id, ключ кабинета рынка, демо-ссылка
  с этими разделами, обычный вошедший, никто — и без токена бота тоже;
- не задан `DEVELOPAID_ADMIN_KEY` — закрыто для всех, и это видно в /health;
- с ключом администратора (полем тела или заголовком) пропуск проходит.

Запуск: python3 -m pytest tests/test_team_only_monitor.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app, raise_server_exceptions=False)
OWNER, CLIENT = 777, 5050
KEY = "kluch"
# Страницы-оболочки без данных (числа приходят с маршрутов ниже) и выгрузки
# расчёта участка — не сводка руководству, у них своё право (`require_calc_access`).
SHELLS = {"/monitor", "/report"}
NOT_MANAGEMENT = ("/report/pdf", "/report/teaser", "/report/workbook")


def _gated_routes() -> list[tuple[str, str]]:
    out = []
    for route in core.app.routes:
        path = getattr(route, "path", "")
        if not (path.startswith("/monitor") or path.startswith("/report")):
            continue
        if path in SHELLS or path.startswith(NOT_MANAGEMENT):
            continue
        for method in sorted(getattr(route, "methods", ()) or ()):
            if method in ("GET", "POST"):
                out.append((method, path))
    return sorted(set(out))


ROUTES = _gated_routes()
_FILL = {str: "проверка", int: 1, float: 1.0, bool: False, list: [], dict: {}}


def _route(method: str, path: str):
    return next(r for r in core.app.routes
                if getattr(r, "path", "") == path and method in getattr(r, "methods", ()))


def call(method: str, path: str, session: str = "", key: str = "",
         headers: dict | None = None, browser: TestClient = client):
    """Запрос, который модель маршрута примет: отказ доступа обязан прийти
    раньше разбора дела, а не прятаться за 422."""
    out: dict = {"project": "проверка", "session": session, "key": key,
                 "source": "проверка", "target": "проверка", "first": "a", "second": "b",
                 "date": "2026-10-22", "taken_at": "2026-10-22", "content_base64": "",
                 "file_sha256": "a" * 64, "contract_date": "2024-07-03",
                 "source_sha256": "a" * 64, "pm_sha256": "a" * 64,
                 "snapshot_id": "2026-10-22-" + "a" * 64,
                 "calendar_basis": "unconfirmed"}
    route = _route(method, path)
    dependant = getattr(route, "dependant", None)
    if method == "GET":
        for param in getattr(dependant, "query_params", []) or []:
            out.setdefault(param.name, "проверка")
        # GET credentials belong in the documented header, never the URL.
        # The route need not expose a query-key parameter to accept its owner.
        out.pop("key", None)
        get_headers = dict(headers or {})
        if key and not any(name.lower() == "x-developaid-admin-key" for name in get_headers):
            get_headers["X-Developaid-Admin-Key"] = key
        return browser.get(path, params=out, headers=get_headers)
    for param in getattr(dependant, "body_params", []) or []:
        model = getattr(param.field_info, "annotation", None) or param.type_
        for name, field in getattr(model, "model_fields", {}).items():
            if field.is_required() and name not in out:
                kind = getattr(field.annotation, "__origin__", None) or field.annotation
                out[name] = _FILL.get(kind, "проверка")
        if getattr(model, "model_fields", None):
            # Невалидная заготовка не проверяет доступ: FastAPI вернёт 422
            # ещё до вызова маршрута. Отличаем поломку стенда от отказа ключа.
            model.model_validate(out)
    return browser.post(path, json=out, headers=headers or {})


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:team-only-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(OWNER))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("MARKET_CABINET_KEY", "team-test-key")
    monkeypatch.setenv("DEVELOPAID_TEAM_IDS", str(CLIENT))
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core._DEMO_ALIVE_CACHE.clear()
    yield


def _refused(answer) -> bool:
    return (answer.status_code == 403
            and core.ADMIN_KEY_ONLY_DENIED in str(answer.json().get("detail")))


def test_the_routes_are_found_from_the_app():
    paths = {path for _m, path in ROUTES}
    for must in ("/monitor/view", "/monitor/report", "/monitor/report.pdf",
                 "/monitor/legal/export", "/monitor/crew", "/monitor/report/mailing"):
        assert must in paths, must
    assert len(ROUTES) >= 40, ROUTES


def _demo_session() -> tuple[str, TestClient]:
    made = client.post("/access/admin/demo/create",
                       json={"key": KEY, "note": "проверка", "days": 5,
                             "blocks": ["monitor", "report"]})
    assert made.status_code == 200, made.text
    browser = TestClient(core.app, raise_server_exceptions=False)
    claimed = browser.post("/demo/claim", json={"code": made.json()["code"]})
    assert claimed.status_code == 200, claimed.text
    return claimed.json()["session"], browser


@pytest.mark.parametrize("method,path", ROUTES)
def test_nobody_but_the_admin_key_gets_in(method, path):
    demo, browser = _demo_session()
    tries = {
        "никто": call(method, path),
        "админ по chat_id": call(method, path, session=core._telegram_session(OWNER, [])),
        "команда DEVELOPAID_TEAM_IDS": call(method, path,
                                            session=core._telegram_session(CLIENT, [])),
        "ключ кабинета рынка": call(method, path, headers={"X-Market-Key": "team-test-key"}),
        "неверный ключ": call(method, path, key="wrong-key"),
        "демо-ссылка с разделами": call(method, path, session=demo, browser=browser),
    }
    opened = {who: a.status_code for who, a in tries.items() if not _refused(a)}
    assert not opened, f"{method} {path} открыт: {opened}"


@pytest.mark.parametrize("method,path", ROUTES)
def test_without_the_bot_token_it_stays_closed(method, path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(core, "_telegram_token", lambda: "")
    assert _refused(call(method, path)), f"{method} {path} открыт без токена бота"


@pytest.mark.parametrize("method,path", ROUTES)
def test_without_the_admin_key_setting_it_is_closed_for_everyone(method, path, monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    assert _refused(call(method, path, key=KEY))
    assert _refused(call(method, path, session=core._telegram_session(OWNER, [])))


@pytest.mark.parametrize("method,path", ROUTES)
def test_the_admin_key_passes(method, path):
    # Заголовком ключ едет на GET-маршрутах (страница так не кладёт его в адрес).
    answers = [call(method, path, key=KEY)]
    if method == "GET":
        answers.append(call(method, path, headers={"X-Developaid-Admin-Key": KEY}))
    for answer in answers:
        assert answer.status_code not in (401, 403), f"{method} {path}: {answer.text[:200]}"


def test_health_names_the_closed_gate(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    gate = client.get("/health").json()["admin_key_sections"]
    assert gate["admin_key_configured"] is False and "не задан" in gate["reason"]
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    gate = client.get("/health").json()["admin_key_sections"]
    assert gate["admin_key_configured"] is True and KEY not in str(gate)


def test_the_gate_fails_on_a_forgery(monkeypatch):
    """Контрпример: прежнее правило «команда» должно ронять тест выше."""
    monkeypatch.setattr(core, "ADMIN_KEY_ONLY_SECTIONS", frozenset())
    answer = call("POST", "/monitor/report/projects",
                  headers={"X-Market-Key": "team-test-key"})
    assert not _refused(answer)
