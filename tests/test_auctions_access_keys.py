"""Личный ключ области «auctions»: только раздел «Торги», проверка на сервере.

Ключ — ограничение всего сайта для браузера, который им вошёл: расчёт,
проекты, Excel, PDF, общий чат Платона и бот отвечают отказом, а страница
торгов не показывает кнопок, ведущих туда. Платон по торгам открыт — своим
маршрутом с дневным лимитом и рамкой темы. Отозванный ключ не действует.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auction_search import access_keys


DENIED = access_keys.DENIED

# Маршруты, которые ключ торгов открывать не должен: метод, путь, тело.
CLOSED = (
    ("GET", "/", None),
    ("GET", "/classic", None),
    ("GET", "/ia", None),
    ("POST", "/calculate", {}),
    ("POST", "/mo/calculate", {}),
    ("POST", "/projects/list", {}),
    ("POST", "/projects/save", {}),
    ("POST", "/report/workbook", {}),
    ("POST", "/report/pdf", {}),
    ("POST", "/agent/chat", {"message": "привет"}),
    ("GET", "/agent/status", None),
    ("POST", "/telegram/session-data", {}),
    ("GET", "/cabinet", None),
    ("GET", "/market", None),
    ("POST", "/auctions/krt/ranking/refresh", {}),
    ("POST", "/auctions/krt/press/run", {}),
    ("POST", "/auctions/ingest", {}),
    ("GET", "/auctions/krt?refresh=true", None),
)


@pytest.fixture()
def registry_app(monkeypatch):
    import main_registry

    access_keys._CACHE.update(sig=None, data=None)
    return main_registry.app


def _enter(client: TestClient, secret: str):
    return client.post(access_keys.ENTER_PATH, json={"key": secret})


def _request(client: TestClient, method: str, path: str, body):
    if method == "GET":
        return client.get(path, headers={"Accept": "application/json"})
    return client.post(path, json=body)


def _assert_closed(client: TestClient) -> None:
    """Каждый закрытый маршрут отвечает отказом ключа, а не своим ответом."""
    for method, path, body in CLOSED:
        response = _request(client, method, path, body)
        assert response.status_code == 403, (method, path, response.status_code)
        assert response.json().get("detail"), (method, path)


def test_auctions_key_opens_auctions_and_closes_the_rest(registry_app):
    record, secret = access_keys.issue("Проверочный Человек", issued_by="1")
    client = TestClient(registry_app)

    # Без входа расчёт открыт как раньше: сайт публичный, ключ — ограничение.
    assert client.get("/", headers={"Accept": "text/html"}).status_code == 200

    entered = _enter(client, secret)
    assert entered.status_code == 200, entered.text
    cookie = client.cookies.get(access_keys.COOKIE_NAME)
    assert cookie and secret not in cookie, "в cookie не сам ключ"

    _assert_closed(client)
    assert client.post("/calculate", json={}).json()["detail"] == DENIED

    page = client.get("/", headers={"Accept": "text/html"})
    assert page.status_code == 403 and "Нет доступа" in page.text
    assert "/auctions" in page.text

    auctions = client.get("/auctions")
    assert auctions.status_code == 200
    assert 'data-access="auctions"' in auctions.text
    assert 'class="contour"' not in auctions.text
    assert '<a class="brand" href="/auctions"' in auctions.text

    # Запросы, без которых страница торгов не работает, пропускаются.
    for method, path in (("GET", "/auctions/krt"), ("GET", "/land/basemap"),
                         ("POST", "/land/lot-context")):
        response = _request(client, method, path, {})
        assert not (response.status_code == 403
                    and response.json().get("detail") == DENIED), path

    listed = access_keys.listing()
    assert listed[0]["logins"] == 1 and listed[0]["last_login_at"]
    assert "hash" not in listed[0]
    raw = access_keys.store_path().read_text("utf-8")
    assert secret not in raw, "на диске только хеш"


def test_the_check_fails_on_an_app_without_the_gate():
    """Контрпример: приложение без гейта, где /calculate отвечает 200.

    Если бы `_assert_closed` проходил и здесь, зелёный тест выше ничего бы не
    доказывал."""
    bare = FastAPI()

    @bare.api_route("/{rest:path}", methods=["GET", "POST"])
    def anything(rest: str):
        return {"ok": True}

    with pytest.raises(AssertionError):
        _assert_closed(TestClient(bare))


def test_revoked_key_stops_working(registry_app):
    record, secret = access_keys.issue("Уходящий")
    _other, _ = access_keys.issue("Остающийся")  # раздел остаётся закрытым
    client = TestClient(registry_app)
    assert _enter(client, secret).status_code == 200
    assert client.get("/auctions").status_code == 200

    revoked, problem = access_keys.revoke(record["id"])
    assert not problem and revoked["revoked_at"]

    # Старая cookie больше ничего не открывает: торги просят ключ заново.
    locked = client.get("/auctions")
    assert locked.status_code == 401
    assert 'data-access="auctions"' not in locked.text
    assert client.get("/auctions/krt", headers={"Accept": "application/json"}).status_code == 401
    # И войти по ссылке снова нельзя.
    again = TestClient(registry_app)
    refused = _enter(again, secret)
    assert refused.status_code == 401
    assert "отозван" in refused.json()["detail"]
    assert again.cookies.get(access_keys.COOKIE_NAME) is None


def test_key_expires_after_five_days(registry_app, monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr(access_keys, "_now", lambda: now[0])
    record, secret = access_keys.issue("На пять дней")
    # Общий ключ держит раздел закрытым и после срока личного: иначе 401 ниже
    # нечем было бы отличить от «раздел открыт всем».
    monkeypatch.setenv("AUCTIONS_VIEW_KEY", "shared-view-key-for-test")
    assert record["expires_at"] - record["issued_at"] == 5 * 24 * 3600

    client = TestClient(registry_app)
    entered = _enter(client, secret)
    assert entered.status_code == 200
    max_age = re.search(r"Max-Age=(\d+)", entered.headers["set-cookie"])
    assert max_age and int(max_age.group(1)) <= 5 * 24 * 3600, "cookie не дольше ключа"

    now[0] += 5 * 24 * 3600 - 60
    assert client.get("/auctions").status_code == 200, "за минуту до срока ещё действует"

    now[0] += 120
    assert client.get("/auctions").status_code == 401, "после срока cookie не действует"
    refused = _enter(TestClient(registry_app), secret)
    assert refused.status_code == 401 and "срок" in refused.json()["detail"]


def test_forged_cookie_is_not_a_key(registry_app):
    record, _secret = access_keys.issue("Настоящий")
    client = TestClient(registry_app)
    for forged in (f"{record['id']}.{'0' * 64}", f"{record['id']}.", "zzzz.abc", ""):
        client.cookies.set(access_keys.COOKIE_NAME, forged)
        assert client.get("/auctions").status_code == 401, forged
    assert access_keys.find_by_key("ak_" + "x" * 32) is None
    assert access_keys.find_by_key(_secret[:-1]) is None


def test_internal_route_requires_fresh_signature(registry_app, monkeypatch):
    import main as wrapper

    monkeypatch.setattr(wrapper.core, "_telegram_token", lambda: "test-bot-token")
    client = TestClient(registry_app)
    ts = int(time.time())
    body = {"action": "list", "holder": "", "ident": "", "by": "", "ts": ts}
    assert client.post("/internal/auctions/keys",
                       json={**body, "sign": "nope"}).status_code == 403
    old = ts - 3600
    stale = {**body, "ts": old,
             "sign": wrapper._auction_keys_sign("list", "", "", "", old)}
    assert client.post("/internal/auctions/keys", json=stale).status_code == 403
    good = {**body, "sign": wrapper._auction_keys_sign("list", "", "", "", ts)}
    response = client.post("/internal/auctions/keys", json=good)
    assert response.status_code == 200 and response.json()["keys"] == []


def test_owner_issues_lists_and_revokes_from_the_bot(registry_app, monkeypatch):
    import main as wrapper

    sent: list[str] = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "42")
    monkeypatch.setenv("AUCTIONS_PUBLIC_URL", "https://site.example")

    wrapper._auction_key_command(7, 7, "/auction_key", "Чужой")
    assert "только владелец" in sent[-1]
    assert access_keys.listing() == []

    wrapper._auction_key_command(42, 42, "/auction_key", "Иван Петров")
    link = re.search(r"https://site\.example/auctions/enter#k=(\S+)", sent[-1])
    assert link, sent[-1]
    secret = link.group(1)
    assert "Действует 5 дней" in sent[-1]
    client = TestClient(registry_app)
    assert _enter(client, secret).status_code == 200

    wrapper._auction_key_command(42, 42, "/auction_keys", "")
    assert "Иван Петров" in sent[-1] and "входов 1" in sent[-1]
    assert "действует до" in sent[-1]
    assert "действует до" in sent[-1]
    assert secret not in sent[-1]

    wrapper._auction_key_command(42, 42, "/auction_revoke", "Иван Петров")
    assert "отозван" in sent[-1]
    assert access_keys.find_by_key(secret) is None


# --- отрисованная страница ----------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_rendered_auctions_page_hides_and_server_refuses(registry_app):
    """Браузер вошёл по ссылке: контура и кнопок расчёта не видно, запросы к
    расчёту из той же страницы получают отказ сервера, а Платон спрашивается
    через `/auctions/ask`."""
    play = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    import browser_launch

    _record, secret = access_keys.issue("Браузер")
    asked: list[str] = []
    service = registry_app.state.market_discovery_service

    def fake_ask(message, request, history=None):
        asked.append(message)
        return {"reply": "Ответ про торги"}

    original_ask = service.plato_ask
    service.plato_ask = fake_ask
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(registry_app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    try:
        with play.sync_playwright() as pw:
            try:
                browser = browser_launch.launch(pw)
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"Chromium недоступен: {exc}")
            try:
                tab = browser.new_page()
                seen: list[str] = []
                tab.on("request", lambda r: seen.append(r.url))
                tab.route("**/*", lambda route: route.continue_()
                          if route.request.url.startswith(base) else route.abort())
                tab.goto(f"{base}{access_keys.ENTER_PATH}#k={secret}")
                tab.wait_for_url(f"{base}/auctions", timeout=15000)
                tab.wait_for_timeout(500)
                assert not any(secret in url for url in seen), "ключ ушёл в запрос"
                assert secret not in tab.url

                state = tab.evaluate("""()=>({
                  scope: document.body.dataset.access,
                  fab: !!document.getElementById('platoFab'),
                  fabHiddenByScope: (document.getElementById('accessScope')?.textContent
                                     || '').includes('platoFab'),
                  contour: !!document.querySelector('nav.contour'),
                  brand: document.querySelector('a.brand')?.getAttribute('href'),
                  calcLinks: [...document.querySelectorAll('a[href]')]
                     .filter(a => a.offsetParent !== null)
                     .map(a => new URL(a.href, location.href))
                     .filter(u => u.origin === location.origin
                                  && !u.pathname.startsWith('/auctions'))
                     .map(u => u.pathname),
                })""")
                assert state["scope"] == "auctions"
                assert state["fab"] is True and state["fabHiddenByScope"] is False, \
                    "Платон по торгам открыт — кнопка не прячется"
                assert state["contour"] is False
                assert state["brand"] == "/auctions"
                # Видимая ссылка не ведёт туда, где ключ получит отказ: каждую
                # проверяет сам сервер, а не список в тесте.
                refused = tab.evaluate("""async(paths)=>{
                  const bad=[];
                  for (const p of paths) {
                    const r=await fetch(p,{headers:{Accept:'text/html'}});
                    if (r.status===403) bad.push(p);
                  }
                  return bad}""", state["calcLinks"])
                assert refused == [], refused
                assert not {"/", "/classic", "/guide", "/normatives"} & set(state["calcLinks"])

                probes = tab.evaluate("""async()=>{
                  const out={};
                  for (const [m,p] of [['POST','/calculate'],['POST','/projects/list'],
                                       ['POST','/report/workbook'],['POST','/agent/chat'],
                                       ['GET','/']]) {
                    const r=await fetch(p,{method:m,headers:{'Content-Type':'application/json'},
                                           body:m==='POST'?'{}':undefined});
                    out[m+' '+p]=r.status;
                  }
                  return out}""")
                assert set(probes.values()) == {403}, probes

                reply = tab.evaluate("()=>platoAsk('Когда торги по лоту?', [])")
                assert reply == "Ответ про торги"
                assert asked and asked[-1].startswith(access_keys.PLATO_FRAME)
                assert any(url.endswith("/auctions/ask") for url in seen)
                assert not any("/cabinet/ask" in url for url in seen)

                tab.goto(f"{base}/")
                assert "Нет доступа" in tab.content()
                assert tab.locator("#calcBtn, #tep, .calc").count() == 0
            finally:
                browser.close()
    finally:
        service.plato_ask = original_ask
        server.should_exit = True
        thread.join(timeout=10)


def test_broken_registry_closes_and_names_the_reason(registry_app):
    """Битый реестр — не «ключей нет»: раздел закрыт, причина названа, а
    подробности исключения наружу не уходят."""
    path = access_keys.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{битый", "utf-8")
    access_keys._CACHE.update(sig=None, data=None)
    client = TestClient(registry_app)
    client.cookies.set(access_keys.COOKIE_NAME, "abc.def")
    response = client.get("/auctions", headers={"Accept": "application/json"})
    assert response.status_code == 503
    assert response.json()["detail"] == access_keys.REGISTRY_BROKEN
    refused = TestClient(registry_app).post(access_keys.ENTER_PATH, json={"key": "ak_x"})
    assert refused.status_code == 503
    assert path.name not in refused.text


def test_gate_is_installed_even_into_an_already_started_app(monkeypatch):
    """Приложение уже обслужило запрос, а модуль торгов ставится после.

    Раньше гейт в таком случае молча не ставился, и ключ «auctions» открывал
    всё (так падала доля CI, где соседний тест раньше запускал движок)."""
    import sys

    from auction_search.api import install

    monkeypatch.delitem(sys.modules, "developaid_core", raising=False)
    access_keys._CACHE.update(sig=None, data=None)
    app = FastAPI()

    @app.post("/calculate")
    def calculate():
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/calculate").status_code == 200  # стек собран
    install(app)
    _record, secret = access_keys.issue("Поздний")
    assert _enter(client, secret).status_code == 200
    refused = client.post("/calculate", json={})
    assert refused.status_code == 403 and refused.json()["detail"] == DENIED


def test_plato_on_auctions_is_open_with_a_daily_limit(registry_app, monkeypatch):
    """Платон по торгам: свой маршрут, рамка темы, лимит на ключ в сутки.

    Общий чат расчёта (`/agent/chat`) при этом закрыт, а без входа Платон не
    отвечает никому."""
    monkeypatch.setenv(access_keys.PLATO_DAILY_ENV, "2")
    service = registry_app.state.market_discovery_service
    asked: list[str] = []
    monkeypatch.setattr(service, "plato_ask",
                        lambda message, request, history=None:
                        asked.append(message) or {"reply": "ок"}, raising=False)
    _record, secret = access_keys.issue("Спрашивающий")
    client = TestClient(registry_app)

    anonymous = TestClient(registry_app).post(access_keys.ASK_PATH, json={"message": "?"})
    assert anonymous.status_code == 401, "без входа Платон не отвечает"

    assert _enter(client, secret).status_code == 200
    for n in (1, 2):
        answer = client.post(access_keys.ASK_PATH, json={"message": f"вопрос {n}"})
        assert answer.status_code == 200 and answer.json()["reply"] == "ок"
    assert all(m.startswith(access_keys.PLATO_FRAME) for m in asked)
    assert asked[0].endswith("вопрос 1")

    over = client.post(access_keys.ASK_PATH, json={"message": "третий"})
    assert over.status_code == 429 and "2 из 2" in over.json()["detail"]
    assert len(asked) == 2, "сверх лимита модель не спрашивается"

    # Общий чат расчёта и обновление рекомендации по площадке — закрыты.
    assert client.post("/agent/chat", json={"message": "x"}).status_code == 403
    assert client.post("/auctions/krt/any/plato?refresh=1").status_code == 403
    # Номер запуска забирается — иначе долгий ответ не дошёл бы.
    assert client.get("/agent/result/abc").status_code != 403
