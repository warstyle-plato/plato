"""Пресеты проектов — витрина владельца; серверных предустановок ТЭП нет.

В пресетах лежат настоящие проекты с ценами, сроками и экономикой.
Показывать их каждому, кто открыл сайт, нельзя (решение владельца,
18.08.2026). Серверные предустановки ТЭП «Мишина» и «Мытищи» — тоже
настоящие проекты владельца: `/presets` закрыли, а `/v2` продолжал отдавать
их расчёт без входа через `/api/v2/projects/mishina`. Владелец решил
«Пресеты можно везде удалить» (23.10.2026). Здесь закреплено:

- маршрутов предустановок ТЭП нет ни на одной поверхности: адрес отвечает 404,
  потому что маршрута нет, а не потому, что обработчик промолчал;
- в каталоге `/v2` нет демонстрационных проектов, он открывается новым;
- пресеты проектов отвечают 403 тому, кто не владелец;
- владельца опознают двумя способами: ключ администратора и chat_id из списка;
- механизм честно выключен там, где владельца опознать нечем, — иначе на
  машине без настроек пресеты пропали бы у всех, включая самого владельца;
- страница на отказ убирает блок целиком, а не оставляет пустой список.

Запуск: python3 -m pytest tests/test_presets_are_for_the_owner.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402
import main_registry  # noqa: E402

core = _wrapper.core
client = TestClient(core.app)
# Собранное приложение прода (`uvicorn main_registry:app`): в нём и /v2.
product = TestClient(main_registry.app)

OWNER = 777
STRANGER = 12345

GONE = (
    "/presets",
    "/presets/mishina",
    "/presets/mytishchi",
    "/presets/mishina/download",
    "/presets/mytishchi/download",
    "/api/v2/projects/mishina",
    "/api/v2/projects/mytishchi",
    "/api/v2/prototype/projects/mishina",
    "/api/v2/prototype/projects/mytishchi",
)


@pytest.fixture()
def owned(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:presets-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(OWNER))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    return None


def _route_paths(app) -> set[str]:
    return {str(getattr(route, "path", "")) for route in app.router.routes}


def test_the_server_tep_presets_are_gone_from_the_engine():
    assert not hasattr(core, "SERVER_TEP_PRESETS")
    for name in ("Мишина_ТЭП.xlsx", "Мытищи_ТЭП.xlsx"):
        assert not (core.PRESET_DIR / name).exists(), name


@pytest.mark.parametrize("path", GONE)
def test_a_removed_route_is_gone_even_for_the_owner(owned, path):
    """404 — потому что маршрута нет: и у владельца, и у постороннего."""
    for params in ({}, {"key": "kluch"}):
        answer = product.get(path, params=params)
        assert answer.status_code == 404, (path, params, answer.status_code)
        assert answer.json().get("detail") == "Not Found", (path, answer.text[:200])
    paths = _route_paths(main_registry.app)
    assert not any(p.startswith("/presets") for p in paths)
    assert "/api/v2/projects/{slug}" not in paths
    assert "/api/v2/prototype/projects/{slug}" not in paths


def test_the_v2_catalog_opens_the_new_project_only():
    catalog = product.get("/api/v2/projects").json()
    assert [item["slug"] for item in catalog] == ["new"]
    assert catalog[0]["demo"] is False
    answer = product.get("/api/v2/projects/new", params={"sensitivity": "false"})
    assert answer.status_code == 200
    assert answer.json()["project"]["slug"] == "new"


def test_a_stranger_does_not_see_the_project_presets(owned):
    answer = client.get("/api/project-presets")
    assert answer.status_code == 403
    assert "владельца" in answer.json()["detail"]

    session = core._telegram_session(STRANGER, [])
    assert client.get("/api/project-presets", params={"session": session}).status_code == 403


def test_the_owner_sees_them_both_ways(owned):
    assert client.get("/api/project-presets", params={"key": "kluch"}).status_code == 200
    session = core._telegram_session(OWNER, [])
    assert client.get("/api/project-presets", params={"session": session}).status_code == 200


def test_without_settings_the_gate_is_honestly_off(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    assert client.get("/api/project-presets").status_code == 200


def test_the_page_has_no_server_tep_preset_picker():
    page = core.PAGE
    for gone in ("serverPresetSelect", "serverPresetDownload", "loadServerPreset(",
                 "loadPresetCatalog", "applyServerPresetProjectConfig",
                 "fetch('/presets", "mytishchi", "mishina", "_preset_expert_overrides"):
        assert gone not in page, gone


def test_the_page_hides_the_block_instead_of_showing_an_empty_list():
    page = core.PAGE
    fill = page[page.index("async function fillProjectPresets()"):]
    fill = fill[:fill.index("async function loadServerProjectPreset(")]
    assert "answer.status===403" in fill and "hidePresetsBlock()" in fill

    hider = page[page.index("function hidePresetsBlock()"):]
    assert "projectsExamples" in hider[:200], "прячется весь блок, а не один список"


def test_the_page_carries_identity_to_every_preset_route():
    page = core.PAGE
    query = page[page.index("function presetsQuery()"):]
    query = query[:query.index("function hidePresetsBlock()")]
    assert "activeSession()" in query and "projectsAdminKey" in query

    for call in ("fetch('/api/project-presets'+presetsQuery())",
                 "fetch('/api/project-presets/'+encodeURIComponent(id)+presetsQuery())"):
        assert call in page, call
