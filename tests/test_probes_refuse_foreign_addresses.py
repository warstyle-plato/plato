"""Пробы источников не открывают чужие и внутренние адреса.

Проба bnMAP входит на открытую страницу под нашим логином и паролем. Проверка
адреса по началу строки пропускала `https://bnmap.pro.чужой.сайт/`: браузер
открыл бы чужую страницу и ввёл в её форму наш доступ, а ссылку на такую пробу
достаточно было подсунуть владельцу кабинета (кука кабинета уходит и с
перехода по ссылке). Остальные пробы показывают ответ присланного адреса и без
проверки читали бы служебные адреса изнутри сервера.
"""

from __future__ import annotations

import pytest

from auction_search import krt_api_probe
from auction_search.adapters import browser_probe
from market_search import bnmap
from market_search.http import public_url_problem


@pytest.mark.parametrize("url", [
    "https://bnmap.pro.evil.example/",
    "https://bnmap.pro@evil.example/",
    "https://user:pass@bnmap.pro/",
    "https://bnmap.pro:8443/",
    "http://bnmap.pro/",
    "https://evil.example/?https://bnmap.pro",
    "https://notbnmap.pro/",
    "https://bnmap.pro\\@evil.example/",
])
def test_bnmap_refuses_lookalike_addresses(url):
    assert not bnmap.own_url(url)


@pytest.mark.parametrize("url", [
    "https://bnmap.pro/", "https://bnmap.pro/msk/projects", "https://api.bnmap.pro/x",
    bnmap.ENTRY_PAGE,
])
def test_bnmap_accepts_its_own_addresses(url):
    assert bnmap.own_url(url)


def test_the_bnmap_route_uses_the_strict_check():
    import inspect
    from market_search import api

    source = inspect.getsource(api)
    assert "bnmap.own_url(target)" in source
    assert 'startswith(f"https://{bnmap.HOST}")' not in source


def test_bnmap_does_not_sign_in_where_the_page_ended_up_elsewhere(monkeypatch):
    seen = {}

    def fake_probe(url, *, seconds, save_to, after_load, secrets):
        class Page:
            url = "https://evil.example/login"
        seen["step"] = after_load(Page())
        return {"ok": True}

    monkeypatch.setattr(bnmap, "available", lambda: True)
    monkeypatch.setattr(bnmap, "credentials", lambda: ("login", "password"))
    monkeypatch.setattr(bnmap, "browser_probe", fake_probe)
    monkeypatch.setattr(bnmap, "_sign_in", lambda *a: pytest.fail("ввели доступ на чужой странице"))
    bnmap.probe_browser("https://bnmap.pro/")
    assert seen["step"]["signed_in"] is False


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8080/monitor",
    "https://localhost/",
    "https://169.254.169.254/latest/meta-data/",
    "https://10.0.0.5/",
    "https://[::1]/",
    "http://example.com/",
    "file:///etc/passwd",
    "https://user@example.com/",
])
def test_internal_and_odd_addresses_are_refused(url):
    assert public_url_problem(url)


def test_the_browser_probe_refuses_before_opening_a_browser():
    got = browser_probe.probe_browser("https://169.254.169.254/latest/meta-data/")
    assert got["ok"] is False and "внутреннюю сеть" in got["reason"]


def test_the_krt_probe_asks_only_the_krt_portal(monkeypatch):
    monkeypatch.setattr(krt_api_probe, "request_bytes",
                        lambda *a, **k: pytest.fail("ушли по чужому адресу"))
    for url in ("https://127.0.0.1/", "https://evil.example/", "http://api.krt.mos.ru/"):
        got = krt_api_probe.probe(url)
        assert got["asked"] == 0 and got["reason"]
