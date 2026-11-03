"""Страница площадки отдаётся целиком и только с официального хоста.

Разбор даты торгов пишется по живой карточке. Проба Росэлторга отдавала
первые 900 символов текста — подпись даты стоит дальше, — а из песочницы
площадки закрыты. `/auctions/source-page` снимает образец на ядре: ответ как
есть, без обрезки, но только с хостов площадок и без редиректа на чужие.
Сети здесь нет: ответ площадки подменён.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from auction_search.adapters import source_page


@pytest.mark.parametrize("url,ok", [
    ("https://www.roseltorg.ru/procedure/178fz0001", True),
    ("https://roseltorg.ru/x", True),
    ("https://catalog.lot-online.ru/index.php?x=1", True),
    ("https://etpgpb.ru/api/v2/procedures/1/", True),
    ("https://evil-roseltorg.ru/x", False),
    ("https://roseltorg.ru.evil.com/x", False),
    ("http://127.0.0.1:8080/auctions", False),
    ("file:///etc/passwd", False),
    ("", False),
])
def test_only_official_platform_hosts(url: str, ok: bool) -> None:
    assert source_page.allowed(url) is ok


def test_a_foreign_host_is_refused_without_a_request(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("запрос к чужому хосту не должен уйти")
    monkeypatch.setattr(urllib.request, "build_opener", boom)
    answer = source_page.fetch("http://127.0.0.1:8080/")
    assert "официального хоста" in answer["reason"]
    assert "body" not in answer


def test_a_redirect_off_the_platform_is_refused() -> None:
    handler = source_page._StayOnPlatform()
    request = urllib.request.Request("https://www.roseltorg.ru/procedure/1")
    with pytest.raises(urllib.error.HTTPError, match="чужой адрес"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", {},
                                 "http://169.254.169.254/latest/meta-data/")
    same = handler.redirect_request(request, io.BytesIO(), 302, "Found", {},
                                    "https://www.roseltorg.ru/procedure/2")
    assert same is not None and same.full_url.endswith("/procedure/2")


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200
        self.headers = _Headers()

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]

    def geturl(self) -> str:
        return "https://www.roseltorg.ru/procedure/1"

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Headers(dict):
    def get_content_charset(self):
        return "utf-8"

    def get(self, key, default=None):
        return "text/html; charset=utf-8" if key == "Content-Type" else default


def _serve(monkeypatch, body: bytes) -> None:
    class Opener:
        def open(self, request, timeout):
            return _Response(body)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_h: Opener())


def test_the_whole_card_comes_back_not_the_head(monkeypatch) -> None:
    card = ("<html><body>" + "шапка " * 400
            + "<dt>Дата проведения аукциона</dt><dd>15.10.2026 10:00</dd>"
            + "</body></html>").encode()
    _serve(monkeypatch, card)
    answer = source_page.fetch("https://www.roseltorg.ru/procedure/1")
    assert answer["http_status"] == 200 and answer["truncated"] is False
    assert "Дата проведения аукциона" in answer["body"]
    assert answer["bytes"] == len(card) and answer["fetched_at"]


def test_an_oversized_page_says_it_was_cut(monkeypatch) -> None:
    monkeypatch.setattr(source_page, "MAX_BYTES", 10)
    _serve(monkeypatch, b"x" * 50)
    answer = source_page.fetch("https://etpgpb.ru/api/v2/procedures/1/")
    assert answer["truncated"] is True and answer["bytes"] == 10
