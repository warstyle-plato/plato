"""Поддомен «Пульса» входит сессией корневой базы, а закрытую дверь называет.

Прод 06.10.2026: `russia.pulsprodaj.ru` отдавал 403 с «Сайт находится в
разработке» и на карту, и на форму входа, а диагностика писала пять раз
«вход не удался». У каждой базы была своя банка кук и своя форма входа;
у поддомена формы для гостя нет. Сессия выдаётся при входе на
`pulsprodaj.ru` и уходит на поддомен, если кука выдана на `.pulsprodaj.ru`.

Банка кук здесь настоящая (`http.cookiejar`), куки ставятся заголовком
`Set-Cookie`, а «уйдёт ли кука» спрашивается тем же механизмом, которым
её отправляет urllib, — без подмены политики.
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

from market_search.pulse import PulseClient, PulseNetwork, make_pulse_client

RUSSIA = "https://russia.pulsprodaj.ru"
MOSCOW = "https://pulsprodaj.ru"
CLOSED_PAGE = (
    "<!doctype html><html><head><title>Сайт находится в разработке</title></head>"
    "<body><h1>Сайт находится в разработке</h1></body></html>"
)
LOGIN_PAGE = "<form><input name='csrfmiddlewaretoken' value='tok'></form>"


class _Response:
    def __init__(self, headers: list[tuple[str, str]]):
        self._message = email.message.Message()
        for key, value in headers:
            self._message[key] = value

    def info(self) -> email.message.Message:
        return self._message


def _set_cookie(jar, url: str, header: str) -> None:
    jar.extract_cookies(_Response([("Set-Cookie", header)]), urllib.request.Request(url))


def _sent(client: PulseClient, url: str) -> str:
    request = urllib.request.Request(url)
    client._build_opener()
    client._jar.add_cookie_header(request)
    return request.get_header("Cookie") or ""


def _forbidden(url: str, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 403, "Forbidden", email.message.Message(), io.BytesIO(body.encode()))


def _pair(tmp_path: Path, *, cookie_domain: str | None):
    """Корневая база с формой входа и поддомен, который отдаёт заглушку."""
    root = PulseClient(tmp_path, login="l", password="p", base=MOSCOW)
    sub = PulseClient(tmp_path, login="l", password="p", base=RUSSIA, auth=root)
    root._build_opener()
    calls: dict[str, list[str]] = {"root": [], "sub": []}

    def root_open(path, *, data=None, headers=None):
        calls["root"].append(path if data is None else f"POST {path}")
        if data is not None:
            domain = f"; Domain={cookie_domain}" if cookie_domain else ""
            _set_cookie(root._jar, MOSCOW + path, f"sessionid=s1; Path=/{domain}")
            _set_cookie(root._jar, MOSCOW + path, f"csrftoken=c1; Path=/{domain}")
        return LOGIN_PAGE.encode()

    def sub_open(path, *, data=None, headers=None):
        calls["sub"].append(path)
        raise _forbidden(RUSSIA + path, CLOSED_PAGE)

    root._open = root_open  # type: ignore[assignment]
    sub._open = sub_open  # type: ignore[assignment]
    return root, sub, calls


def test_a_domain_session_from_the_root_base_is_sent_to_the_subdomain(tmp_path: Path) -> None:
    root, sub, calls = _pair(tmp_path, cookie_domain=".pulsprodaj.ru")
    assert sub.sign_in() is True
    # Вход — формой корневой базы; своей формы у поддомена не спрашивали.
    assert calls["root"] == ["/accounts/login/", "POST /accounts/login/"]
    assert calls["sub"] == []
    assert sub._jar is root._jar
    assert sub._cookie("sessionid") == "s1"
    assert "sessionid=s1" in _sent(sub, RUSSIA + "/map/")


def test_our_answer_about_a_cookie_is_the_jars_own(tmp_path: Path) -> None:
    """«Уйдёт ли кука» решает банка, а не отдельная копия правила.

    Куку без домена `http.cookiejar` шлёт и на поддомен (браузер — нет): это
    оставлено нарочно, но диагностика обязана говорить то же, что уходит.
    """
    root, sub, _ = _pair(tmp_path, cookie_domain=None)
    assert sub.sign_in() is True
    assert ("sessionid=s1" in _sent(sub, RUSSIA + "/map/")) is (sub._cookie("sessionid") == "s1")
    record = sub._cookie_record("sessionid")
    assert record == {"domain": "pulsprodaj.ru", "for_subdomains": False, "sent_here": True}
    # Чужому домену кука не уходит ни по банке, ни по нашему ответу.
    other = PulseClient(tmp_path, login="l", password="p", base="https://example.ru", auth=root)
    assert other._cookie("sessionid") is None
    assert "sessionid" not in _sent(other, "https://example.ru/map/")


def test_the_stub_page_is_named_a_closed_subdomain_not_a_failed_login(tmp_path: Path) -> None:
    root, sub, calls = _pair(tmp_path, cookie_domain=".pulsprodaj.ru")
    assert sub.projects() == []
    said = " | ".join(sub.errors)
    assert ("поддомен russia.pulsprodaj.ru закрыт для нашего сервера: "
            "403 «Сайт находится в разработке»; сессия pulsprodaj.ru отправлена") in said, said
    assert "вход не удался" not in said
    assert "/accounts/login/" not in calls["sub"]
    report = sub.catalog_report()
    assert report["access"].startswith("поддомен russia.pulsprodaj.ru закрыт")
    assert report["auth_base"] == MOSCOW
    assert report["session_cookie"] == {"domain": ".pulsprodaj.ru", "for_subdomains": True, "sent_here": True}


def test_the_closed_reason_names_a_cookie_without_a_domain(tmp_path: Path) -> None:
    _, sub, _ = _pair(tmp_path, cookie_domain=None)
    sub.projects()
    assert sub.access_closed and "кука выдана без домена" in sub.access_closed, sub.errors


def test_an_ordinary_403_is_not_called_a_closed_subdomain(tmp_path: Path) -> None:
    """Контрпример: 403 от CSRF — это не закрытый поддомен."""
    client = PulseClient(tmp_path, login="l", password="p", base=MOSCOW)
    csrf = _forbidden(MOSCOW + "/api/x/", "<h1>Forbidden (403)</h1> CSRF verification failed.")
    assert client._closed(csrf) is None
    assert client._closed(urllib.error.URLError("timeout")) is None
    assert client.access_closed is None


def test_the_api_names_the_closed_subdomain_too(tmp_path: Path) -> None:
    root, sub, _ = _pair(tmp_path, cookie_domain=".pulsprodaj.ru")
    assert sub._post_json("/api/app/complex/price_stats/", {"complex_id": "50-1"}) is None
    assert "закрыт для нашего сервера" in sub.errors[-1]


def test_the_list_of_bases_ties_the_subdomain_to_the_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PULSE_AUTH_BASE_URL", raising=False)
    monkeypatch.setenv("PULSE_BASE_URL", f"{RUSSIA},{MOSCOW}")
    network = make_pulse_client(tmp_path)
    assert isinstance(network, PulseNetwork)
    russia, moscow = network.sites
    assert russia.auth is moscow and moscow.auth is None

    # Поддомен один в списке: связь только явной переменной, не по имени.
    monkeypatch.setenv("PULSE_BASE_URL", RUSSIA)
    alone = make_pulse_client(tmp_path)
    assert alone.auth is None
    monkeypatch.setenv("PULSE_AUTH_BASE_URL", MOSCOW)
    tied = make_pulse_client(tmp_path)
    assert tied.auth is not None and tied.auth.base == MOSCOW


def test_a_working_subdomain_reads_its_map_with_the_shared_session(tmp_path: Path) -> None:
    root, sub, calls = _pair(tmp_path, cookie_domain=".pulsprodaj.ru")
    collection = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "50-004184",
         "geometry": {"type": "Point", "coordinates": [55.66, 37.21]},
         "properties": {"name": "Одинцовские Кварталы"}}]}
    page = "<script>var d = " + json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + ";</script>"

    def sub_open(path, *, data=None, headers=None):
        calls["sub"].append(path)
        # Карта отдаётся только тому, чья сессия ушла с запросом.
        if "sessionid=s1" not in _sent(sub, RUSSIA + path):
            raise _forbidden(RUSSIA + path, CLOSED_PAGE)
        return page.encode()

    sub._open = sub_open  # type: ignore[assignment]
    assert [item.complex_id for item in sub.projects()] == ["50-004184"]
    assert sub.access_closed is None
    assert calls["root"][-1] == "POST /accounts/login/"


def test_a_reopened_subdomain_drops_the_old_closed_reason(tmp_path: Path) -> None:
    root, sub, calls = _pair(tmp_path, cookie_domain=".pulsprodaj.ru")
    sub.projects()
    assert sub.access_closed
    page = ('<script>var d = {"type":"FeatureCollection","features":[]};</script>')
    sub._open = lambda path, **kw: page.encode()  # type: ignore[assignment]
    sub.projects(refresh=True)
    assert sub.access_closed is None
    assert sub.catalog_report()["access"] == "открыт"
