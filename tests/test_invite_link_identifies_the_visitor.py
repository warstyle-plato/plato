"""Заход по приглашению: кто пришёл, известно с первого нажатия.

Ссылку выкладывают в брокерский канал на пятьсот человек, адреса сайта они
заранее не знают. Если положить туда ссылку на сайт, от публикации останется
счётчик заходов без единого имени: спросить потом будет некого, а по анкете
отзовутся двое из двадцати, и не самые типичные.

Поэтому в канал идёт ссылка на бота — `t.me/<бот>?start=<метка>`. Одно нажатие
Start, и известно всё нужное: chat_id, имя, метка источника. Человек не вводит
ни телефона, ни почты; сайт открывается кнопкой с уже готовой сессией.

Метка приходит снаружи, поэтому в журнал попадает только то, что похоже на
метку. И подтверждение входа на сайт (`login_…`) меткой не считается — это
другой сценарий, он был раньше и работает по-прежнему.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


# --- метка источника ---------------------------------------------------------------

@pytest.mark.parametrize("payload,expected", [
    ("brokers", "brokers"),
    ("chat-2026_08", "chat-2026_08"),
    ("", ""),
    ("login_a1b2c3", ""),                 # это вход на сайт, а не приглашение
    ("brokers channel", ""),              # с пробелом — не метка
    ("<script>alert(1)</script>", ""),    # снаружи приходит что угодно
    ("a" * 33, ""),                       # длинное не пускаем
])
def test_the_source_is_taken_only_when_it_looks_like_one(payload, expected):
    assert core._telegram_invite_source(payload) == expected


def test_the_login_payload_is_not_an_invite():
    """Подтверждение входа и приглашение — разные сценарии. Спутать их значит
    записать в журнал одноразовый код как источник."""
    assert core._telegram_invite_source("login_deadbeef") == ""


# --- имя для журнала ---------------------------------------------------------------

def test_the_name_joins_what_telegram_gives():
    assert core._telegram_sender_name(
        {"from": {"first_name": "Иван", "last_name": "Петров",
                  "username": "ipetrov"}}) == "Иван Петров @ipetrov"
    assert core._telegram_sender_name({"from": {"first_name": "Иван"}}) == "Иван"
    assert core._telegram_sender_name({"from": {"username": "ipetrov"}}) == "@ipetrov"
    assert core._telegram_sender_name({}) == ""


# --- приглашённый получает кнопку сайта первой -------------------------------------

def test_an_invited_visitor_gets_the_site_button_first(monkeypatch):
    """Он не знает ни адреса, ни того, что здесь есть. Меню бота из восьми
    сценариев он читать не станет — ему нужен расчёт."""
    sent: list[dict] = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append({"text": text, **kw}))
    monkeypatch.setattr(core, "_telegram_web_app_url",
                        lambda chat_id, cads, **kw: "https://example.test/#telegram_session=x")
    monkeypatch.setattr(core, "_telegram_dialog_clear", lambda chat_id: None)

    core._telegram_start_message(1, 1, source="brokers")
    keyboard = sent[-1]["reply_markup"]["inline_keyboard"]
    assert "web_app" in keyboard[0][0], "кнопка сайта должна быть первой"
    assert "Открыть DevelopAid" in keyboard[0][0]["text"]
    assert "не сходится с вашей практикой" in sent[-1]["text"]


def test_without_an_invite_the_menu_is_unchanged(monkeypatch):
    """Обычный /start остаётся прежним: приглашение ничего не ломает тем, кто
    пришёл сам."""
    sent: list[dict] = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append({"text": text, **kw}))
    monkeypatch.setattr(core, "_telegram_web_app_url",
                        lambda chat_id, cads, **kw: "https://example.test/")
    monkeypatch.setattr(core, "_telegram_dialog_clear", lambda chat_id: None)

    core._telegram_start_message(1, 1)
    keyboard = sent[-1]["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0].get("callback_data") == "flow_cad_yes"
    assert "Спасибо, что зашли" not in sent[-1]["text"]
    assert sent[-1]["text"].startswith("<b>Добро пожаловать")


# --- переход попадает в журнал -----------------------------------------------------

def test_the_arrival_is_recorded_with_its_source(monkeypatch):
    """Событие пишется до всего остального: человек мог нажать Start и уйти,
    и это тоже результат публикации, который надо видеть."""
    written: list[tuple] = []
    monkeypatch.setattr(core, "usage_track",
                        lambda kind, **kw: written.append((kind, kw)))
    monkeypatch.setattr(core, "_telegram_start_message",
                        lambda chat_id, user_id, source="": None)
    monkeypatch.setattr(core, "_telegram_dialog_clear", lambda chat_id: None)

    core._telegram_handle_message({
        "chat": {"id": 77, "type": "private"},
        "from": {"id": 77, "first_name": "Иван", "username": "ipetrov"},
        "text": "/start brokers",
    })
    kinds = [kind for kind, _ in written]
    assert "invite" in kinds
    payload = next(kw for kind, kw in written if kind == "invite")
    assert payload["source"] == "brokers"
    assert payload["chat_id"] == 77
    assert "Иван" in payload["name"]


def test_a_plain_start_records_no_source(monkeypatch):
    written: list[tuple] = []
    monkeypatch.setattr(core, "usage_track",
                        lambda kind, **kw: written.append((kind, kw)))
    monkeypatch.setattr(core, "_telegram_start_message",
                        lambda chat_id, user_id, source="": None)
    monkeypatch.setattr(core, "_telegram_dialog_clear", lambda chat_id: None)

    core._telegram_handle_message({
        "chat": {"id": 77, "type": "private"},
        "from": {"id": 77, "first_name": "Иван"},
        "text": "/start",
    })
    assert "invite" not in [kind for kind, _ in written]
