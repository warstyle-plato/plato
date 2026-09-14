"""В групповой чат бот не пишет ничего — и через ту дверь, в которую ходят.

Правило «у группы бот только читатель» закрыто 13.09.2026 и проверялось
`test_the_bot_is_silent_in_the_site_chat`. Проверка звала `core.
_telegram_handle_message` — дверь ДВИЖКА. Telegram ходит не туда: обёртка
перехватывает `_telegram_handle_update`, и её разбор команд стоит ВЫШЕ гейта.
Экран владельца 14.09.2026: шесть подряд «DevelopAid работает в личном чате с
ботом» в рабочем чате и следом две ошибки 429 — прод на 0.23.52, где гейта нет
вовсе, а на ветке с гейтом в группу по-прежнему отвечали `/help`, `/status`,
`/notify` и `/krt`.

Вторая половина — верхний перехват: он докладывал причину в ТОТ ЖЕ чат, минуя
правило. И доклад этот был про 429 «Too Many Requests», то есть про лишние
сообщения, — сделанный ещё одним сообщением. Ошибку по частоте не докладывают
сообщением ни в каком чате: доклад её усиливает, а исход остаётся в `/status`.

Запуск: python3 -m pytest tests/test_the_group_chat_gate_holds_at_the_real_door.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GROUP = -100500
AUTHOR = 4242
OWNER = 777


@pytest.fixture()
def bot(tmp_path, monkeypatch):
    import main as wrapper

    core = wrapper.core
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    core._PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path / "state")
    wrapper._STATE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_projects_remote_url", lambda path: "")
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {OWNER})
    monkeypatch.setattr(core, "_telegram_token", lambda: "t")
    sent: list[tuple[int, str]] = []

    def capture(chat, text, **kw):
        sent.append((int(chat), str(text)))
        return {"ok": True}

    monkeypatch.setattr(core, "_telegram_send_message", capture)
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat, text, **kw: capture(chat, text))
    wrapper.sent = sent  # type: ignore[attr-defined]
    return wrapper


def group(text: str) -> dict:
    return {"message": {"chat": {"id": GROUP, "type": "supergroup", "title": "Стройка"},
                        "from": {"id": AUTHOR}, "text": text, "date": 1757721600}}


def private(text: str, chat_id: int = OWNER) -> dict:
    return {"message": {"chat": {"id": chat_id, "type": "private"},
                        "from": {"id": chat_id}, "text": text, "date": 1757721600}}


def into_group(bot) -> list[str]:
    return [text for chat, text in bot.sent if chat == GROUP]


@pytest.mark.parametrize("text", ["привет всем", "/help", "/status", "/notify",
                                  "/krt", "/calc", "/stats", "/platon"])
def test_nothing_reaches_the_group_through_the_webhook_door(bot, text) -> None:
    """Дверь та же, в которую ходит Telegram: `_handle_update` обёртки.

    Четыре команды из этого списка отвечали в группу при живом гейте движка.
    """
    bot.sent.clear()
    bot._handle_update(group(text))
    assert into_group(bot) == [], text


def test_a_failure_is_not_reported_into_the_group(bot, monkeypatch) -> None:
    """Верхний перехват — не исключение из правила «в группу ничего»."""
    monkeypatch.setattr(bot.core, "_telegram_handle_update",
                        lambda update: (_ for _ in ()).throw(RuntimeError("боль")))
    bot.sent.clear()
    bot.core._telegram_process_update(group("привет"))
    assert into_group(bot) == []


def test_a_rate_limit_is_not_answered_with_another_message(bot, monkeypatch) -> None:
    """429 вызван лишними сообщениями, и доклад о нём — ещё одно сообщение."""
    monkeypatch.setattr(
        bot.core, "_telegram_handle_update",
        lambda update: (_ for _ in ()).throw(RuntimeError(
            'Telegram API: HTTP 429: {"ok":false,"error_code":429}')))
    bot.sent.clear()
    bot.core._telegram_process_update(private("привет"))
    assert bot.sent == [], "отказ по частоте не докладывают сообщением"
    assert "429" in bot.core._TELEGRAM_RUNTIME.get("last_error", ""), \
        "но и потеряться он не должен: исход виден в /status"


def test_a_private_chat_is_not_silenced(bot) -> None:
    """Предохранитель: молчащий на всё бот прошёл бы проверки выше."""
    bot.sent.clear()
    bot._handle_update(private("/help"))
    assert [chat for chat, _text in bot.sent] == [OWNER]


def test_an_ordinary_failure_still_reaches_the_person(bot, monkeypatch) -> None:
    """Ошибка, ушедшая только в лог, — это ошибка, которой нет.

    Хостинг закрыт, и причина по-прежнему доносится в личку: гейт снимает
    группу и частоту, а не доклад вообще.
    """
    monkeypatch.setattr(bot.core, "_telegram_handle_update",
                        lambda update: (_ for _ in ()).throw(RuntimeError("боль")))
    bot.sent.clear()
    bot.core._telegram_process_update(private("привет"))
    assert len(bot.sent) == 1 and "Не удалось завершить запрос" in bot.sent[0][1]


def test_the_gate_is_decided_in_one_place(bot) -> None:
    """Обёртка не заводит своего правила: она зовёт движковое.

    Два ответа на «групповой ли это чат» однажды разошлись бы, и оба выглядели
    бы верными — так уже расходились бот с сайтом и книга с движком.
    """
    source = Path(ROOT / "main.py").read_text(encoding="utf-8")
    assert "core._telegram_group_message(chat, message)" in source


def typeless(chat_id: int, text: str = "/help") -> dict:
    """Сообщение без `type` — так его собирает код, а не Telegram."""
    return {"message": {"chat": {"id": chat_id}, "from": {"id": abs(chat_id)},
                        "text": text, "date": 1757721600}}


def test_a_message_without_a_chat_type_does_not_silence_a_private_chat(bot) -> None:
    """«Не private» — не то же самое, что «группа».

    Первая редакция гейта читала отсутствующий `type` как «не личка» и онемляла
    её: три проверки Платона разом получили пустой ответ там, где бот обязан
    отвечать. Telegram `type` присылает всегда, а собранное в коде сообщение —
    нет, и умолчание «раз не сказано, значит группа» ломает ровно тот путь,
    который чинить не просили.
    """
    bot.sent.clear()
    bot._handle_update(typeless(4242))
    assert [chat for chat, _text in bot.sent] == [4242]


def test_a_negative_chat_id_is_a_group_even_without_a_type(bot) -> None:
    """Признак самой группы, а не догадка о её отсутствии: номер отрицательный."""
    bot.sent.clear()
    bot._handle_update(typeless(GROUP))
    assert into_group(bot) == []


@pytest.mark.parametrize("kind,is_group", [("private", False), ("group", True),
                                           ("supergroup", True), ("channel", True)])
def test_the_kind_is_read_positively(bot, kind, is_group) -> None:
    assert bot.core._telegram_is_group({"id": 1, "type": kind}) is is_group
