"""Счётчик Метрики: один раз на каждой HTML-странице, нигде больше.

Прослойка стоит на выходе приложения, поэтому проверка идёт по маршрутам
самого приложения, а не по списку «страниц, где мы его ставили»: следующая
страница попадает под проверку тем, что появилась. Список владельца
(корень, `/classic`, `/ia`, торги, Нагатино, мониторинг, статистика,
нормативы) проверяется отдельно и обязателен — если прослойка пропустит хоть
одну из них, тест красный.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import yandex_metrika

CID = "113133252"
TAG = "mc.yandex.ru/metrika/tag.js"

# Поверхности из решения владельца. Каждая обязана отдать HTML со счётчиком.
REQUIRED = ["/", "/classic", "/ia", "/auctions", "/krt/nagatino", "/monitor",
            "/statistics", "/normatives", "/v2", "/guide"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, CID)
    import main_registry
    return TestClient(main_registry.app)


def _html_routes() -> list[str]:
    import main_registry
    from fastapi.routing import APIRoute

    paths = set(REQUIRED)
    for route in main_registry.app.routes:
        if not isinstance(route, APIRoute) or "GET" not in (route.methods or set()):
            continue
        if route.param_convertors:
            continue
        if "HTML" in getattr(route.response_class, "__name__", ""):
            paths.add(route.path)
    return sorted(paths)


def test_every_html_page_carries_exactly_one_counter(client):
    checked, missing = [], []
    for path in _html_routes():
        response = client.get(path)
        if "text/html" not in response.headers.get("content-type", ""):
            assert path not in REQUIRED, f"{path}: ждали HTML, пришло {response.headers.get('content-type')}"
            continue
        body = response.text
        if "</head>" not in body.lower():
            # Страница без <head> (вход в кабинет) не падает и остаётся без счётчика.
            assert TAG not in body
            continue
        if body.count(TAG) != 1 or body.count(f"ym({CID},'init'") != 1:
            missing.append(f"{path}: {body.count(TAG)}")
            continue
        head_end = body.lower().find("</head>")
        assert body.find(TAG) < head_end, f"{path}: счётчик не в <head>"
        assert int(response.headers["content-length"]) == len(response.content)
        checked.append(path)
    assert not missing, f"счётчик не ровно один раз: {missing}"
    for path in REQUIRED:
        assert path in checked, f"{path}: обязательная страница осталась без счётчика"


def test_no_variable_no_counter(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, "")
    import main_registry
    client = TestClient(main_registry.app)
    for path in REQUIRED:
        body = client.get(path).text
        assert "mc.yandex.ru" not in body, path
        assert "Yandex.Metrika" not in body, path


def test_garbage_in_the_variable_is_not_a_counter(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, "1');alert(1)//")
    assert yandex_metrika.counter_id() == ""


def test_non_html_responses_are_untouched(client, monkeypatch):
    for path in ["/defaults", "/ia/assets/overlay.js", "/health"]:
        response = client.get(path)
        if response.status_code == 404:
            continue
        assert "mc.yandex.ru" not in response.text, path
    monkeypatch.setenv(yandex_metrika.ENV_NAME, "")
    import main_registry
    plain = TestClient(main_registry.app).get("/defaults")
    monkeypatch.setenv(yandex_metrika.ENV_NAME, CID)
    assert client.get("/defaults").content == plain.content


def _run(app, method="GET"):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": "/", "headers": []}
    asyncio.run(yandex_metrika.YandexMetrikaMiddleware(app)(scope, receive, send))
    return sent


def _app(ctype: bytes, chunks: list[bytes], extra=()):
    async def app(scope, receive, send):
        headers = [(b"content-type", ctype), *extra]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk,
                        "more_body": index < len(chunks) - 1})
    return app


def test_streams_and_binaries_pass_message_by_message(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, CID)
    parts = [b"%PDF-1.7 </head>", b"tail"]
    sent = _run(_app(b"application/pdf", parts))
    assert [m.get("body") for m in sent[1:]] == parts
    assert [m.get("more_body") for m in sent[1:]] == [True, False]
    gz = _run(_app(b"text/html", [b"<head></head>"], [(b"content-encoding", b"gzip")]))
    assert gz[1]["body"] == b"<head></head>"


def test_html_split_across_chunks_gets_one_counter(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, CID)
    sent = _run(_app(b"text/html; charset=utf-8", [b"<html><head><title>x</title></he", b"ad><body></body></html>"],
                     [(b"content-length", b"999")]))
    body = sent[1]["body"]
    assert body.count(TAG.encode()) == 1
    assert body.index(TAG.encode()) < body.index(b"</head>")
    lengths = [v for k, v in sent[0]["headers"] if k == b"content-length"]
    assert lengths == [str(len(body)).encode()]


def test_page_without_head_does_not_fail(monkeypatch):
    monkeypatch.setenv(yandex_metrika.ENV_NAME, CID)
    sent = _run(_app(b"text/html", [b"<p>no head</p>"]))
    assert sent[1]["body"] == b"<p>no head</p>"


def test_counter_already_present_is_not_doubled():
    once = yandex_metrika.inject(b"<head></head>", CID)
    assert yandex_metrika.inject(once, CID) == once


def test_init_keeps_owner_parameters():
    code = yandex_metrika.snippet(CID)
    for option in ["ssr:true", "webvisor:true", "clickmap:true", 'ecommerce:"dataLayer"',
                   "referrer:document.referrer", "url:location.href",
                   "accurateTrackBounce:true", "trackLinks:true"]:
        assert option in code, option
    assert f"https://mc.yandex.ru/watch/{CID}" in code
    assert "ym-disable-keys" in code
    # Маскировка ставится раньше, чем запускается Вебвизор.
    assert code.index("ym-disable-keys") < code.index("'init'")


# --- в браузере -----------------------------------------------------------

_DYNAMIC = """<!doctype html><html><head><title>t</title></head><body>
<input id="a" value="секрет"><textarea id="b"></textarea>
<script>setTimeout(function(){var i=document.createElement('input');i.id='late';
document.body.appendChild(i);},50)</script></body></html>"""


def _browser_state(url_or_file, fragment: str):
    playwright = pytest.importorskip("playwright.sync_api")
    import browser_launch

    with playwright.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # pragma: no cover - окружение без браузера
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            requested = []

            def route(r):
                if "mc.yandex.ru" in r.request.url:
                    requested.append(r.request.url)
                    r.fulfill(status=200, content_type="application/javascript", body="")
                elif r.request.url.startswith("file:"):
                    r.continue_()
                else:
                    r.abort()

            tab.route("**/*", route)
            tab.goto(url_or_file.as_uri() + fragment)
            tab.wait_for_timeout(300)
            state = tab.evaluate("""() => ({
                ym: typeof window.ym,
                calls: (window.ym && window.ym.a || []).map(a => Array.from(a).map(x => typeof x === 'object' ? JSON.stringify(x) : String(x))),
                inputs: Array.from(document.querySelectorAll('input,textarea,select')).length,
                unmasked: Array.from(document.querySelectorAll('input,textarea,select'))
                    .filter(e => !e.classList.contains('ym-disable-keys')).map(e => e.id || e.name || e.tagName),
            })""")
            state["requested"] = requested
            return state
        finally:
            browser.close()


def _write(tmp_path, name: str, html: str):
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return path


def test_browser_runs_counter_and_masks_every_field(tmp_path, client):
    page = _write(tmp_path, "root.html", client.get("/").text)
    state = _browser_state(page, "")
    assert state["ym"] == "function"
    assert any(call[:2] == [CID, "init"] and '"webvisor":true' in call[2] for call in state["calls"])
    assert state["requested"], "загрузчик tag.js не запрошен"
    assert state["inputs"] > 0
    assert state["unmasked"] == [], f"поля без маскировки: {state['unmasked'][:10]}"

    dynamic = _write(tmp_path, "dyn.html", yandex_metrika.inject(_DYNAMIC.encode(), CID).decode())
    late = _browser_state(dynamic, "")
    assert late["inputs"] == 3 and late["unmasked"] == []


@pytest.mark.parametrize("fragment", ["#telegram_session=abc", "#x=1&cad=77:01:0001001:1",
                                      "#tgWebAppData=query_id%3D1"])
def test_browser_in_telegram_does_not_start_counter(tmp_path, client, fragment):
    page = _write(tmp_path, "root.html", client.get("/").text)
    state = _browser_state(page, fragment)
    assert state["ym"] == "undefined", fragment
    assert state["requested"] == [], fragment
