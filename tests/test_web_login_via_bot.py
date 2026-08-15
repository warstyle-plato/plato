"""Вход на сайт через телеграм-бота: код → подтверждение → сессия.

Личность пользователя уже есть у бота — chat_id; вход доносит её до сайта без
второй регистрации. Здесь закреплено устройство и его края:

- код одноразовый и короткоживущий, сгорает при выдаче сессии;
- подтверждение принимается только с подписью токеном бота;
- выданная сессия открывает хранилище проектов владельцу — любому chat_id,
  не только администратору;
- Платон и PDF с сайта — за входом (мягкий гейт), но без токена бота гейт
  честно выключен: проверять подпись нечем, и порядок остаётся прежним.

Запуск: python3 -m pytest tests/test_web_login_via_bot.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core
client = TestClient(main.app)

CHAT_ID = 424242


@pytest.fixture(autouse=True)
def login_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:web-login-test-token")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "developaid_test_bot")
    monkeypatch.setattr(main, "_PROJECTS_DIR", tmp_path / "projects")
    yield


def start_login() -> dict:
    response = client.post("/auth/telegram/start")
    assert response.status_code == 200, response.text
    return response.json()


def claim(code: str):
    return client.post("/auth/telegram/claim", json={"code": code})


def test_the_full_circle_issues_an_owner_session():
    data = start_login()
    assert data["link"] == f"https://t.me/developaid_test_bot?start=login_{data['code']}"
    # До подтверждения сессии нет — страница ждёт, а не получает чужое.
    assert claim(data["code"]).json() == {"ready": False}
    main._web_login_confirm(data["code"], CHAT_ID)
    result = claim(data["code"]).json()
    assert result["ready"] and result["chat_id"] == CHAT_ID
    # Сессия входа и сессия мини-приложения — одна проверка и один владелец.
    assert main._project_owner(session=result["session"]) == CHAT_ID


def test_the_code_burns_on_claim():
    data = start_login()
    main._web_login_confirm(data["code"], CHAT_ID)
    assert claim(data["code"]).json()["ready"]
    assert claim(data["code"]).status_code == 404


def test_an_expired_code_is_refused():
    data = start_login()
    path = main._web_login_path(data["code"])
    path.write_text(json.dumps({"created": time.time() - 10_000}), encoding="utf-8")
    assert claim(data["code"]).status_code == 410


def test_confirmation_needs_the_bot_signature():
    data = start_login()
    bad = client.post("/auth/telegram/confirm",
                      json={"code": data["code"], "chat_id": CHAT_ID, "sign": "не та"})
    assert bad.status_code == 403
    good = client.post("/auth/telegram/confirm",
                       json={"code": data["code"], "chat_id": CHAT_ID,
                             "sign": main._web_login_sign(data["code"], CHAT_ID)})
    assert good.status_code == 200 and good.json() == {"ok": True}


def test_any_bot_user_owns_their_projects(monkeypatch):
    """Хранилище открыто владельцу сессии, а не только администратору."""
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    session = main._telegram_session(CHAT_ID, [])
    assert main._project_owner(session=session) == CHAT_ID


def test_platon_and_pdf_ask_for_login():
    chat = client.post("/agent/chat", json={"message": "привет", "inputs": {}, "tep": {}})
    assert chat.status_code == 401 and "Telegram" in chat.json()["detail"]
    pdf = client.post("/report/pdf", json={"result": {}})
    assert pdf.status_code == 401 and "Telegram" in pdf.json()["detail"]


def test_the_gate_accepts_session_and_admin_key(monkeypatch):
    session = main._telegram_session(CHAT_ID, [])
    main._require_web_access(session, "", "Проверка")  # не бросает
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "секрет")
    main._require_web_access("", "секрет", "Проверка")
    with pytest.raises(HTTPException):
        main._require_web_access("", "не тот", "Проверка")


def test_without_a_bot_token_the_gate_is_off(monkeypatch):
    """Без токена проверять подпись нечем — порядок прежний, а не заперт."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    main._require_web_access("", "", "Проверка")  # не бросает


def test_the_page_wires_the_login_in():
    """Функции входа без проводки — мёртвый груз: страница обязана их звать."""
    page = main.PAGE
    assert "function loginViaTelegram" in page
    assert page.count("session:activeSession()") >= 3, "сессию входа шлют не все поверхности"
    assert "renderProjectsLogin();" in page
    assert "appendAiLoginButton();" in page
    assert "start_payload.startswith(\"login_\")" in Path(main.__file__).read_text(encoding="utf-8")
