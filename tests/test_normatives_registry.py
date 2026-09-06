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


# Страница носит подвал документов ИП, а его состав разбирается из `PAGE`
# движка — второго списка ссылок у продукта нет. Значит и заглушка движка
# обязана нести `PAGE`: без него это не «страница без подвала», а движок,
# которого не бывает.
_PAGE = ('<footer class="legal"><span>© ИП</span>'
         '<a href="/policy">Политика</a><a href="/consent">Согласие</a></footer>')


def test_admin_button_is_not_rendered_for_public_user(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=lambda request: False, PAGE=_PAGE)

    page = registry._page(_request(), core)

    assert "Проверить источники" not in page
    assert "NORMATIVES_ADMIN_KEY" not in page


def test_admin_button_is_rendered_for_existing_admin(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=lambda request: True, PAGE=_PAGE)

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
