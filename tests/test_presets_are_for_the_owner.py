"""Готовые примеры и пресеты проектов — витрина владельца, не посторонних.

В предустановках ТЭП и пресетах лежат настоящие проекты с ценами, сроками и
экономикой. Показывать их каждому, кто открыл сайт, нельзя (решение владельца,
18.08.2026). Здесь закреплено:

- маршруты примеров и пресетов отвечают 403 тому, кто не владелец;
- владельца опознают двумя способами: ключ администратора и chat_id из списка;
- механизм честно выключен там, где владельца опознать нечем, — иначе на
  машине без настроек примеры пропали бы у всех, включая самого владельца;
- страница на отказ убирает блок целиком, а не оставляет пустой список.

Запуск: python3 -m pytest tests/test_presets_are_for_the_owner.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app)

OWNER = 777
STRANGER = 12345


@pytest.fixture()
def owned(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:presets-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(OWNER))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    return None


def test_a_stranger_does_not_see_the_examples(owned):
    for path in ("/presets", "/api/project-presets"):
        answer = client.get(path)
        assert answer.status_code == 403, path
        assert "владельца" in answer.json()["detail"]

    session = core._telegram_session(STRANGER, [])
    assert client.get("/presets", params={"session": session}).status_code == 403


def test_the_owner_sees_them_both_ways(owned):
    assert client.get("/presets", params={"key": "kluch"}).status_code == 200
    session = core._telegram_session(OWNER, [])
    assert client.get("/api/project-presets", params={"session": session}).status_code == 200


def test_the_file_of_an_example_is_not_handed_out_either(owned):
    """Список закрыт, а ссылка на файл оставалась открытой — так закрывать
    нечего: имя файла видно в разметке."""
    answer = client.get("/presets/mishina/download")
    assert answer.status_code in (403, 404)
    if answer.status_code == 403:
        assert "владельца" in answer.json()["detail"]


def test_without_settings_the_gate_is_honestly_off(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    assert client.get("/presets").status_code == 200


def test_the_page_hides_the_block_instead_of_showing_an_empty_list():
    page = core.PAGE
    body = page[page.index("async function loadPresetCatalog()"):]
    body = body[:body.index("async function loadServerPreset(")]
    assert "response.status===403" in body and "hidePresetsBlock()" in body

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

    for call in ("fetch('/presets'+presetsQuery())",
                 "fetch('/presets/'+encodeURIComponent(id)+presetsQuery())",
                 "fetch('/api/project-presets'+presetsQuery())",
                 "fetch('/api/project-presets/'+encodeURIComponent(id)+presetsQuery())"):
        assert call in page, call
    assert "(opt.dataset.download||'#')+presetsQuery()" in page, "ссылка на файл — тоже дверь"
