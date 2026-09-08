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


def test_registry_does_not_treat_a_mosru_draft_as_current_law():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-2152-pp"]

    assert "projects/" not in item["source_url"]
    assert "61-ПП" in item["latest_amendment"]
    assert item["status"] == "review_required"


def test_registry_tracks_the_latest_known_depr_index_document():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-depr-index"]

    assert "ДПР-Р-20/26" in item["title"]
    assert "ДПРР-18-26" not in item["title"]


def test_mpt_card_exposes_the_july_2026_review_gap():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-1874-pp"]

    assert "2072-ПП" in item["latest_amendment"]
    assert "1965-ПП" in item["latest_amendment"]
    assert item["status"] == "review_required"


def test_a_source_link_carries_no_click_id():
    """Метка перехода в ссылке источника — факт о нашем поиске, а не о документе.

    08.09.2026 ссылка на 214-ФЗ пришла из выдачи Яндекса с хвостом `ysclid`.
    Такой хвост протухает вместе с сессией поиска, а в реестре живёт вечно и
    выглядит частью адреса документа. Хуже того, он рассказывает, где мы искали,
    в публичном репозитории.

    Проверка держит утверждение, а не список: запрещены параметры перехода у
    ЛЮБОЙ карточки, включая те, что появятся позже.
    """
    import urllib.parse

    junk = {"ysclid", "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "gclid", "fbclid", "yclid", "_openstat"}
    found = []
    for row in registry._load_registry():
        query = urllib.parse.urlsplit(row.get("source_url") or "").query
        marks = sorted(set(urllib.parse.parse_qs(query)) & junk)
        if marks:
            found.append((row.get("id"), marks))
    assert not found, f"в ссылке источника осталась метка перехода: {found}"


def test_the_click_id_guard_fails_on_a_forged_link(monkeypatch):
    """Сторож обязан падать на поломке — иначе он не сторож.

    Правило проверяется подделкой: карточка с `ysclid` должна быть найдена.
    Без этого «нарушений нет» означало бы, что не сработал сам обход.
    """
    forged = [{"id": "поддельная", "source_url": "http://example.org/doc?nd=1&ysclid=abc"}]
    monkeypatch.setattr(registry, "_load_registry", lambda: forged)
    import pytest
    with pytest.raises(AssertionError, match="метка перехода"):
        test_a_source_link_carries_no_click_id()
