"""Проект передаётся другому человеку набором параметров, а не PDF.

«А если я другому пользователю хочу скинуть проект, посчитанный мной? Не PDF,
а именно набор параметров для дальнейшей работы» (владелец, 20.08.2026).
Решение владельца: ссылку открывает любой, кто её получил, и живёт она
бессрочно.

Ссылка отдаёт снимок, а не сам проект: получатель видит присланное, и правки
автора задним числом эту картину не меняют. Копия, а не общий доступ — двое,
уверенные, что смотрят одно и то же, худший исход для финмодели.

Запуск: python3 -m pytest tests/test_sharing_a_project.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

OWNER = 777
GUEST = 778


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / f"{OWNER}.json").write_text(json.dumps({
        "chat_id": OWNER, "name": "Владислав", "company": "ПЛАТО",
        "source": "сам", "consent": True}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(core, "_project_owner", lambda session="", key="": (
        GUEST if session == "гость" else OWNER))
    return TestClient(core.app)


def _save(client, name="Мишина 46", purchase=1234.0):
    return client.post("/projects/save", json={
        "session": "s", "name": name,
        "payload": {"inputs": {"purchase_price_mln": purchase}, "tep": {},
                    "phasing": {}, "scenario": "base"},
        "summary": {"revenue_mln": 1000, "net_profit_mln": 100, "llcr": 1.2},
        "cadastral": ["77:09:0004014:13"]}).json()


def test_anyone_with_the_link_opens_it(client):
    """Решение владельца: любой и бессрочно. Значит — без входа."""
    card = _save(client)
    share = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()
    answer = client.post("/projects/shared", json={"id": share["code"]})
    assert answer.status_code == 200, answer.text
    snapshot = answer.json()
    assert snapshot["name"] == "Мишина 46"
    assert snapshot["payload"]["inputs"]["purchase_price_mln"] == 1234.0
    assert snapshot["cadastral"] == ["77:09:0004014:13"]
    # Кто прислал — из знакомства: получателю нужно понимать, чей это расчёт.
    assert snapshot["author"] == "Владислав (ПЛАТО)"


def test_the_code_is_not_guessable(client):
    """Ссылка вечная и открытая — значит, её не должно быть видно насквозь."""
    card = _save(client)
    code = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()["code"]
    assert len(code) >= 16, code
    assert re.fullmatch(r"[A-Za-z0-9_-]+", code), code
    # Идентификатор проекта в ссылку не попадает: он короче и предсказуем.
    assert card["id"] not in code


def test_sharing_twice_keeps_one_link(client):
    """У проекта одна ссылка: повтор обновляет снимок, а не плодит адреса."""
    card = _save(client)
    first = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()
    _save(client, purchase=2000.0)  # правка проекта не трогает ссылку
    again = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()
    assert again["code"] == first["code"]


def test_the_snapshot_does_not_follow_the_author(client):
    """Получатель видит присланное. Правки автора в чужую вкладку не уезжают."""
    card = _save(client)
    code = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()["code"]
    client.post("/projects/save", json={
        "session": "s", "id": card["id"], "name": "Мишина 46",
        "payload": {"inputs": {"purchase_price_mln": 9999.0}, "tep": {}},
        "summary": {}, "cadastral": []})
    snapshot = client.post("/projects/shared", json={"id": code}).json()
    assert snapshot["payload"]["inputs"]["purchase_price_mln"] == 1234.0
    # Обновить картину можно тем же «Поделиться» — это и есть выключатель
    # неожиданности: автор решает, когда получатель увидит новое.
    client.post("/projects/share", json={"session": "s", "id": card["id"]})
    fresh = client.post("/projects/shared", json={"id": code}).json()
    assert fresh["payload"]["inputs"]["purchase_price_mln"] == 9999.0


def test_a_link_can_be_revoked(client):
    """У вечной открытой ссылки без выключателя нет способа передумать."""
    card = _save(client)
    code = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()["code"]
    client.post("/projects/unshare", json={"session": "s", "id": card["id"]})
    gone = client.post("/projects/shared", json={"id": code})
    assert gone.status_code == 404
    assert "отозвали" in gone.json()["detail"]
    # Сам проект остался у автора: отзыв ссылки — не удаление.
    names = [p["name"] for p in client.post("/projects/list", json={"session": "s"}).json()["projects"]]
    assert names == ["Мишина 46"]


def test_a_stranger_cannot_share_someone_elses_project(client):
    """Ссылку выпускает владелец проекта, а не любой вошедший."""
    card = _save(client)
    answer = client.post("/projects/share", json={"session": "гость", "id": card["id"]})
    assert answer.status_code == 404, answer.text


def test_the_code_cannot_walk_out_of_its_directory(client):
    """Код превращается в имя файла — значит, «../../» отвергается."""
    for bad in ("../../etc/passwd", "коротко", "a" * 200, ""):
        answer = client.post("/projects/shared", json={"id": bad})
        assert answer.status_code in (400, 404), (bad, answer.status_code)


def test_the_page_offers_the_link_and_the_way_back():
    """Кнопка «Поделиться» есть в списке, отзыв — рядом, а не в консоли."""
    page = core.PAGE
    assert "shareProject(" in page and "Поделиться" in page
    assert "'/projects/share'" in page and "'/projects/unshare'" in page
    body = page[page.index("async function shareProject("):]
    body = body[:body.index("\n}\n")]
    assert "?shared=" in body
    assert "Отмена — отозвать" in body, "отозвать можно там же, где поделились"
    # Молчаливое «скопировано», когда не скопировалось, хуже отсутствия кнопки.
    assert "copied" in body


def test_the_page_opens_a_received_link():
    page = core.PAGE
    body = page[page.index("async function openSharedProject("):]
    body = body[:body.index("\n}\n")]
    # Присланное накладывается на умолчания, а не подменяет их: снимок мог быть
    # сделан версией, где поля ещё не было.
    assert "applyProjectSnapshot(data)" in body, "наложение живёт одной функцией"
    assert "history.replaceState" in body, "ссылка уходит из адреса после открытия"
    assert "checkSharedLink();" in page


def test_the_link_is_checked_after_the_local_state_is_restored():
    """Сначала своё состояние, потом вопрос «заменить присланным?»."""
    page = core.PAGE
    assert page.index("loadLocal();") < page.index("checkSharedLink();")


def test_editing_a_project_keeps_its_link(client):
    """Правка проекта не должна выпускать вторую ссылку.

    Код хранился в записи проекта, а сохранение собирало запись заново — код
    терялся. «Поделиться» после правки выдавало новый адрес, а старый
    продолжал жить и показывать прежние числа: две живые ссылки на один
    проект, и та, что уже у получателя, — устаревшая.
    """
    card = _save(client)
    code = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()["code"]
    client.post("/projects/save", json={
        "session": "s", "id": card["id"], "name": "Мишина 46",
        "payload": {"inputs": {"purchase_price_mln": 4321.0}, "tep": {}},
        "summary": {}, "cadastral": []})
    again = client.post("/projects/share", json={"session": "s", "id": card["id"]}).json()
    assert again["code"] == code, "правка проекта выпустила вторую ссылку"
    fresh = client.post("/projects/shared", json={"id": code}).json()
    assert fresh["payload"]["inputs"]["purchase_price_mln"] == 4321.0
