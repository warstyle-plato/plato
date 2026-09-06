from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

import normatives_registry as registry


def _request() -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/normatives",
        "raw_path": b"/normatives",
        "query_string": b"",
        "headers": [],
        "client": ("test", 1),
        "server": ("developaid", 443),
    })


def test_normatives_reuse_the_developaid_admin_checker():
    request = _request()
    seen = []
    core = SimpleNamespace(_is_admin_request=lambda value: seen.append(value) or True)

    assert registry._is_admin(request, core) is True
    assert seen == [request]


def test_normatives_do_not_invent_a_second_admin_secret(monkeypatch):
    monkeypatch.setenv("NORMATIVES_ADMIN_KEY", "must-not-be-used")
    core = SimpleNamespace(_is_admin_request=lambda request: False)

    assert registry._is_admin(_request(), core) is False


def test_admin_button_is_not_rendered_for_public_user(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=lambda request: False)

    page = registry._page(_request(), core)

    assert "Проверить источники" not in page
    assert "NORMATIVES_ADMIN_KEY" not in page


def test_admin_button_is_rendered_for_existing_admin(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=lambda request: True)

    page = registry._page(_request(), core)

    assert "Режим администратора DevelopAid" in page
    assert "Проверить источники" in page
