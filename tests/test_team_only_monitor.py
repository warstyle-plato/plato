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
- с ключом администратора (полем тела или заголовком) пропуск проходит;
  контроль ответов продаж дополнительно требует действующее разрешение
  владельца точной группе/проекту и связь с отчётом продаж.

Запуск: python3 -m pytest tests/test_team_only_monitor.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app, raise_server_exceptions=False)
OWNER, CLIENT = 777, 5050
KEY = "kluch"
_SALES_GROUP = -100987654
_SALES_PROJECT = "Синтетические продажи"
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
_PDF_INTAKE_PAYLOAD = {
    "contract_number": "SYNTHETIC-PDF",
    "customer": {"name": "ООО «Учебный заказчик»", "designation": "Заказчик", "page": 1,
                 "quote": "ООО «Учебный заказчик», именуемое в дальнейшем «Заказчик»"},
    "contractor": {"name": "ООО «Учебный подрядчик»", "designation": "Подрядчик", "page": 1,
                   "quote": "ООО «Учебный подрядчик», именуемое в дальнейшем «Подрядчик»"},
}
_ENDPOINT_PAYLOADS = {
    ("POST", "/monitor/cumulative/remove"): {"expected_revision": "a" * 64, "restore": False},
    ("POST", "/monitor/sales-followups"): {"chat_id": _SALES_GROUP},
    ("POST", "/monitor/finance-allocation/apply"): {"assignments": [{"row_id": "a" * 64, "bank_code": "2.6"}]},
    ("POST", "/monitor/finance-management/apply"): {"item_ids": ["a" * 64], "management_article": "2.6"},
    ("POST", "/monitor/contracts/source-review"): {"contract_id": "a" * 64},
    ("POST", "/monitor/contracts/source-audit-page"): {
        "book_sha256": ["a" * 64], "corpus_token": "b" * 64},
    ("POST", "/monitor/contracts/source-duplicate-proof"): {
        "book_sha256": ["a" * 64], "corpus_token": "b" * 64},
    ("POST", "/monitor/contracts/source-prepared-index"): {
        "cut": "2036-08-19", "snapshot_ids": ["2036-07-01-" + "a" * 64],
        "expected_project_scope": "b" * 64, "expected_cached_source_roster_sha256": "c" * 64,
        "expected_source_content_sha256": "d" * 64, "caller_reference_corpus_token": "e" * 64},
    ("POST", "/monitor/schedule-gpr-physical/save"): {"source_kind": "gpr"},
    ("POST", "/monitor/contracts/documents"): {"contract_id": "a" * 64},
    ("POST", "/monitor/contracts/comparison.xlsx"): {
        "cut": "2036-08-19", "ticket": "1" * 32, "contract_id": "a" * 64,
        "revision": "b" * 64, "selected_tokens": []},
    ("POST", "/monitor/contracts/gpr-change"): {
        "cut": "2036-08-19", "contract_id": "a" * 64, "source_sha256": "b" * 64,
        "expected_guard": "c" * 64, "action": "anchor", "note": "Synthetic guarded GPR date fixture."},
    ("POST", "/monitor/contracts/gpr.xlsx"): {
        "cut": "2036-08-19", "ticket": "1" * 32, "contract_id": "a" * 64, "revision": "b" * 64},
    ("POST", "/monitor/contracts/disk/scan"): {
        "cut": "2036-08-19", "source": "https://disk.yandex.ru/d/synthetic-auth-fixture"},
    ("POST", "/monitor/contracts/disk/stage"): {
        "cut": "2036-08-19", "revision": "a" * 64, "item_ids": ["b" * 64]},
    ("POST", "/monitor/contracts/disk/apply"): {
        "cut": "2036-08-19", "stage_token": "c" * 64, "taken_at": "2036-08-19"},
    ("POST", "/monitor/contracts/document-upload"): {"contract_id": "a" * 64},
    ("POST", "/monitor/contracts/pdf-intake/preview"): _PDF_INTAKE_PAYLOAD,
    ("POST", "/monitor/contracts/pdf-intake/commit"): {
        **_PDF_INTAKE_PAYLOAD, "filename": "synthetic.pdf", "expected_revision": 0, "preview_token": "b" * 64},
    ("POST", "/monitor/contracts/document-links"): {
        "contract_id": "a" * 64, "sha256": "b" * 64, "estimate": 0, "choices": [{"index": 0}]},
    ("POST", "/monitor/contracts/document-remove"): {"contract_id": "a" * 64, "sha256": "b" * 64},
    ("POST", "/monitor/contracts/document-confirm"): {
        "contract_id": "a" * 64, "sha256": "b" * 64, "kind": "act", "values": {}},
    ("POST", "/monitor/contracts/identity/inventory"): {"raw_ids": ["a" * 64, "b" * 64]},
    ("POST", "/monitor/contracts/identity/confirm"): {
        "raw_ids": ["a" * 64, "b" * 64], "expected_revision": 0,
        "inventory_sha256": "c" * 64, "source_tokens": ["d" * 64, "e" * 64],
        "anchor_id": "a" * 64, "canonical_number": "SYNTHETIC-C-01", "note": "Synthetic owner review."},
    ("POST", "/monitor/contracts/identity/revoke"): {
        "decision_id": "f" * 64, "expected_revision": 1, "note": "Synthetic owner revocation."},
    ("POST", "/monitor/contracts/identity/resolve"): {"contract_id": "a" * 64},
    ("POST", "/monitor/schedule/version-preview"): {
        "effective_from": "2026-10-22", "gpr_base64": "eA=="},
    ("POST", "/monitor/schedule/version-approve"): {
        "effective_from": "2026-10-22", "gpr_base64": "eA==",
        "expected_previous_sha256": "a" * 64, "expected_source_sha256": "b" * 64},
}
_CORRECTION_PREVIEW = {"raw_ids": ["a" * 64, "b" * 64], "canonical_source_token": "c" * 64,
                       "execution_token": "d" * 64, "price_token": None, "documents_raw_id": "a" * 64}
_ENDPOINT_PAYLOADS.update({
    ("POST", "/monitor/contracts/identity/correction-inventory"): {"raw_ids": ["a" * 64, "b" * 64]},
    ("POST", "/monitor/contracts/identity/correction-preview"): _CORRECTION_PREVIEW,
    ("POST", "/monitor/contracts/identity/correct-sources"): {
        **_CORRECTION_PREVIEW, "expected_revision": 0, "expected_decision_head": "0" * 64,
        "inventory_sha256": "e" * 64, "preview_sha256": "f" * 64,
        "source_tokens": ["1" * 64, "2" * 64], "note": "Synthetic reviewed sources."},
})



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
    out.update(_ENDPOINT_PAYLOADS.get((method, path), {}))
    if path in {'/monitor/schedule/saved-source-preview', '/monitor/schedule/saved-source-approve'}:
        out = {'project': 'проверка', 'session': session, 'key': key, 'source_sha256': 'a'*64,
               'expected_active_sha256': 'b'*64, 'expected_revision': 0, 'effective_from': '2026-11-12'}
    elif path in {'/monitor/audit/budget-funding/layout', '/monitor/audit/budget-funding/layout/result'}:
        out = {'key': key, 'session': session, 'purpose': 'budget_funding_layout_proof_v1', 'ticket': '1'*32}
        if path.endswith('/layout'):
            out.update(project='Synthetic', cut='2026-11-13', scope='rss_estimate_only', expected={
                'runtime_commit': 'a'*40, 'producer_sha256': {name: 'b'*64 for name in (
                    'budget_source', 'layout_proof', 'monitor_routes', 'cached_source_reader', 'admin_source_reader')},
                'finance_sha256': 'c'*64, 'rss_sha256': 'd'*64,
                'namespace_sha256': 'e'*64, 'aliases_sha256': None})
    elif path == '/monitor/readiness/editor':
        out = {'project': 'проверка', 'session': session, 'key': key}
    elif path in {'/monitor/readiness/profile-preview', '/monitor/readiness/profile-save'}:
        out = {'project': 'проверка', 'session': session, 'key': key, 'configuration': {},
               'expected_source_sha256': 'a'*64, 'expected_source_revision': 0, 'expected_revision': 0}
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
            if model.model_config.get('extra') == 'forbid':
                out = {k: v for k, v in out.items() if k in model.model_fields}
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


def _prepare_sales_followup_scope():
    """Настоящие разрешение и связь в изолированном состоянии теста.

    Ключ администратора не заменяет разрешение группе. Положительный smoke
    обязан создать оба основания, а не обходить новый маршрут заглушкой.
    """
    import developaid_management_report as management
    from market_search import sales_store

    where = sales_store.default_dir()
    sales_store.save(where, _SALES_PROJECT, {"contracting": {"rows": []}}, "SYNTHETIC.xlsx")
    management.link_sales("проверка", _SALES_PROJECT, "synthetic ACL fixture", where)
    granted = client.post("/monitor/site-chats/authorize", json={
        "key": KEY, "chat_id": _SALES_GROUP, "project": "проверка"})
    assert granted.status_code == 200, granted.text


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
def test_the_admin_key_passes(method, path, monkeypatch):
    if path == "/monitor/sales-followups":
        _prepare_sales_followup_scope()
    identity_operation = path.startswith("/monitor/contracts/identity/") and not path.endswith("/result")
    if identity_operation:
        import developaid_management_report_jobs as jobs
        start = jobs.Store.start
        def authorized_job(store, owner, profile, params, builder, ticket="", **policy):
            # Admission, strict models and the native job store stay real.
            # This auth smoke does not confirm/revoke any source identity.
            if profile == "monitor-cumulative-v1:contract-identity":
                import developaid_monitor_ledgers as ledgers
                assert policy.get('context') == ledgers.snapshot_job_context(params['project'])
                assert params['source_context'] == policy['context']
                builder = lambda: {"ok": True}
            return start(store, owner, profile, params, builder, ticket, **policy)
        monkeypatch.setattr(jobs.Store, "start", authorized_job)
    # Заголовком ключ едет на GET-маршрутах (страница так не кладёт его в адрес).
    answers = [call(method, path, key=KEY)]
    if method == "GET":
        answers.append(call(method, path, headers={"X-Developaid-Admin-Key": KEY}))
    for answer in answers:
        assert answer.status_code not in (401, 403), f"{method} {path}: {answer.text[:200]}"
        if identity_operation:
            assert answer.status_code in (200, 202)
            assert answer.headers["cache-control"] == "private, no-store"
            deadline = time.monotonic() + 5
            while answer.status_code == 202 and time.monotonic() < deadline:
                answer = client.post("/monitor/contracts/identity/result", json={
                    "key": KEY, "session": "", "ticket": answer.json()["ticket"]})
                assert answer.headers["cache-control"] == "private, no-store"
                if answer.status_code == 202:
                    time.sleep(.005)
            assert answer.status_code == 200, "synthetic identity worker did not finish before fixture teardown"
            assert answer.json().get('ok') is True


def test_sales_followups_need_both_admin_key_and_current_exact_owner_scope():
    path = "/monitor/sales-followups"
    # Even the correct owner key cannot manufacture a missing group grant.
    missing = call("POST", path, key=KEY)
    assert missing.status_code == 403 and "не авторизована владельцем" in missing.text
    assert missing.headers["cache-control"] == "private, no-store"

    _prepare_sales_followup_scope()
    accepted = call("POST", path, key=KEY)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["scope"]["chat_id"] == _SALES_GROUP
    assert accepted.json()["scope"]["sales_project"] == _SALES_PROJECT
    assert accepted.headers["cache-control"] == "private, no-store"
    # A real grant does not open the owner route to a transport signature,
    # Telegram admin identity, market key or absent/wrong owner key.
    for answer in (
        call("POST", path),
        call("POST", path, key="wrong-key"),
        call("POST", path, session=core._telegram_session(OWNER, [])),
        call("POST", path, headers={"X-Market-Key": "team-test-key"}),
        client.post(path, json={"chat_id": _SALES_GROUP, "project": "проверка",
                                "sign": core._web_login_sign("sales-followups", 0)}),
    ):
        assert _refused(answer), answer.text

    for mismatch in ({"chat_id": _SALES_GROUP - 1}, {"project": "Другой проект"}):
        answer = client.post(path, json={"key": KEY, "chat_id": _SALES_GROUP,
                                        "project": "проверка", **mismatch})
        assert answer.status_code == 403, answer.text
    changed_link = client.post(path, json={"key": KEY, "chat_id": _SALES_GROUP,
                                          "project": "проверка", "sales_project": "Другие продажи"})
    assert changed_link.status_code == 409, changed_link.text

    revoked = client.post("/monitor/site-chats/revoke", json={
        "key": KEY, "chat_id": _SALES_GROUP, "project": "проверка"})
    assert revoked.status_code == 200, revoked.text
    after = call("POST", path, key=KEY)
    assert after.status_code == 403 and "не авторизована владельцем" in after.text
    assert after.headers["cache-control"] == "private, no-store"


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
