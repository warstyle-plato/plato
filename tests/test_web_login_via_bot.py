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
from engine_source import engine_source  # noqa: E402

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
    assert "start_payload.startswith(\"login_\")" in engine_source()


def test_the_login_is_visible_without_opening_anything():
    """Вход жил внутри личного кабинета и показывался только тем, у кого нет ни
    сессии, ни ключа: человек с непринятым ключом до него не доходил вовсе
    (замечание владельца, 18.08.2026). Кнопка стоит в шапке."""
    page = main.PAGE
    assert 'id="loginButton"' in page
    button = page[page.index('id="loginButton"'):]
    assert "Войти через Telegram" in button[:200]
    assert 'onclick="openLogin()"' in button[:200]

    body = page[page.index("function renderLoginButton()"):page.index("function openLogin()")]
    assert "projectsAcceptsLogin" in body, "нет бота — нечего и предлагать"
    assert "telegramSession" in body and "webSession()" in body
    assert "projectsAdminKey" in body


def test_the_bot_link_survives_a_blocked_popup():
    """Окно бота открывается после запроса к серверу, и браузер часто считает
    его непрошеным — Safari почти всегда. Тогда человек стоял перед пустым
    ожиданием: ссылки на бота на экране не было."""
    body = main.PAGE[main.PAGE.index("async function loginViaTelegram("):]
    body = body[:body.index("const money=")]
    assert "const opened=window.open(d.link" in body
    assert "Открыть бота" in body, "ссылка показывается всегда"
    assert "Браузер не дал открыть окно бота" in body
    assert "encodeURI(d.link)" in body


def test_the_link_leads_to_the_bot_with_the_code():
    data = start_login()
    assert data["link"].startswith("https://t.me/developaid_test_bot?start=login_")
    assert data["code"] in data["link"]


def test_a_missing_bot_name_is_said_out_loud():
    """Кнопка входа прячется, когда сервер бота не предлагает, и человек
    оставался перед панелью «войдите через бота» без самой кнопки — с одним
    только ключом администратора (замечание владельца, 18.08.2026)."""
    panel = main.PAGE[main.PAGE.index("function renderProjectsLogin("):]
    panel = panel[:panel.index("function hideProjectsLogin(")]
    assert "TELEGRAM_BOT_USERNAME" in panel, "причина названа именем переменной"
    assert "Пока доступен только ключ администратора" in panel


def test_the_status_tells_the_page_whether_the_bot_is_offered(monkeypatch):
    """Признак берётся с сервера: имя бота на ядре задаётся переменной, потому
    что getMe туда не проходит."""
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "")
    monkeypatch.setattr(main, "_TELEGRAM_RUNTIME", dict(main._TELEGRAM_RUNTIME, username=""))
    assert client.get("/projects/status").json()["accepts_login"] is False

    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "developaid_test_bot")
    assert client.get("/projects/status").json()["accepts_login"] is True


# --- вход с телефона, когда на компьютере нет Telegram ----------------------------

def test_the_qr_carries_the_same_link():
    """На десктопе без приложения ссылка t.me открывает «поставьте Telegram»,
    и вход упирается в тупик (замечание владельца, 18.08.2026). QR переносит
    тот же код на телефон — новых прав он не даёт."""
    data = start_login()
    answer = client.get("/auth/telegram/qr", params={"code": data["code"]})
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("image/svg+xml")
    assert answer.content.startswith(b"<?xml") and b"<svg" in answer.content
    assert answer.headers["cache-control"] == "no-store", "код одноразовый — не кэшируем"


def test_a_junk_code_gets_no_picture():
    """Код приходит снаружи: рисуем только то, что похоже на код, иначе QR
    станет способом закодировать чужую ссылку нашим адресом."""
    for bad in ("", "../../etc", "javascript:alert(1)", "https://example.com"):
        assert client.get("/auth/telegram/qr", params={"code": bad}).status_code == 400


def test_without_a_bot_name_there_is_nothing_to_encode(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "")
    monkeypatch.setattr(main, "_TELEGRAM_RUNTIME", dict(main._TELEGRAM_RUNTIME, username=""))
    answer = client.get("/auth/telegram/qr", params={"code": "abc123"})
    assert answer.status_code == 503
    assert "TELEGRAM_BOT_USERNAME" in answer.json()["detail"]


def test_the_page_shows_the_qr_and_survives_its_absence():
    body = main.PAGE[main.PAGE.index("async function loginViaTelegram("):]
    body = body[:body.index("const money=")]
    assert "/auth/telegram/qr?code=" in body
    assert "Наведите камеру телефона" in body
    assert "onerror=" in body, "образ без библиотеки не должен оставлять битую картинку"
    assert "Открыть бота" in body, "ссылка остаётся, даже если QR не отдался"


def test_the_library_is_declared():
    requirements = (Path(main.__file__).resolve().parent / "requirements.txt").read_text(encoding="utf-8")
    assert "segno" in requirements, "образ соберётся без QR, а маршрут ответит 503"



# --- Чужая ссылка входа ------------------------------------------------------
# Код входа запрашивает любой браузер. Если бот подтверждал вход сразу по
# «/start login_<код>», человек, открывший присланную кем-то ссылку, отдавал
# сессию своего чата тому, кто её прислал. Теперь бот спрашивает и показывает
# код для сверки, а вход подтверждает только кнопка «Да» в личном чате.

def _bot(monkeypatch):
    sent: list[dict] = []

    def fake_send(chat_id, text, *, reply_markup=None):
        sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    monkeypatch.setattr(main, "_telegram_send_message", fake_send)
    monkeypatch.setattr(main, "_telegram_api", lambda *a, **k: {})
    return sent


def _start_message(code: str, chat_id: int = CHAT_ID) -> dict:
    return {"message": {"chat": {"id": chat_id, "type": "private"},
                        "from": {"id": chat_id, "first_name": "Жертва"},
                        "text": f"/start login_{code}"}}


def _button(data: str, chat_id: int = CHAT_ID, user_id: int = CHAT_ID) -> dict:
    return {"callback_query": {"id": "q1", "data": data,
                               "from": {"id": user_id, "first_name": "Жертва"},
                               "message": {"chat": {"id": chat_id}}}}


def test_opening_a_login_link_alone_logs_nobody_in(monkeypatch):
    sent = _bot(monkeypatch)
    data = start_login()  # браузер того, кто прислал ссылку
    main._telegram_handle_update(_start_message(data["code"]))
    assert claim(data["code"]).json() == {"ready": False}
    question = sent[-1]
    assert data["display_code"] in question["text"]
    buttons = [b["callback_data"] for row in question["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == [f"login_ok:{data['code']}", f"login_no:{data['code']}"]


def test_only_the_yes_button_confirms(monkeypatch):
    _bot(monkeypatch)
    data = start_login()
    main._telegram_handle_update(_button(f"login_no:{data['code']}"))
    assert claim(data["code"]).json() == {"ready": False}
    main._telegram_handle_update(_button(f"login_ok:{data['code']}"))
    result = claim(data["code"]).json()
    assert result["ready"] and result["chat_id"] == CHAT_ID


def test_a_group_button_does_not_confirm(monkeypatch):
    _bot(monkeypatch)
    data = start_login()
    main._telegram_handle_update(_button(f"login_ok:{data['code']}", chat_id=-100500))
    main._telegram_handle_update(_button(f"login_ok:{data['code']}", user_id=CHAT_ID + 1))
    assert claim(data["code"]).json() == {"ready": False}


def test_the_wrapper_passes_the_login_button_to_the_bot(monkeypatch):
    # Прод зовёт обёртку main.py: кнопка не должна в ней потеряться.
    _bot(monkeypatch)
    monkeypatch.setattr(_wrapper, "_user_to_core", lambda *a, **k: None)
    data = start_login()
    _wrapper._handle_update(_button(f"login_ok:{data['code']}"))
    assert claim(data["code"]).json()["ready"]


def test_the_page_shows_the_code_to_compare():
    data = start_login()
    assert data["display_code"] == main._web_login_display(data["code"])
    assert "d.display_code" in main.PAGE and "коды совпадают" in main.PAGE
