"""Счётчик увиденного в группах виден там, где на `/status` отвечают.

14.09.2026 владелец спросил «ты уверен?» — и был прав. Гейт «в группу ничего»
уехал на прод (0.23.62), а проверить его было нечем: строка «Группы: …»
печаталась в `/status` ДВИЖКА, тогда как отвечает на `/status` ОБЁРТКА — она
перехватывает разбор команд, и до движкового обработчика управление не доходит
никогда. Счётчик считал и показать себя не мог, то есть на вопрос «дошла ли
сводка из чата» ответа не было вовсе.

Тот же промах, что и в самом гейте, только зеркальный: там правило стояло не у
той двери, здесь — ответ о его работе. Отсюда и форма проверки: она зовёт
`_handle_update` обёртки — ровно то, что зовёт Telegram, — а не функцию, у
которой строка объявлена. Проверка, спрашивающая движок, была бы зелёной на
сломанном коде: строка там есть и никуда не делась.

Запуск: python3 -m pytest tests/test_the_group_counter_shows_itself.py -q
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
    # Счёт живёт в памяти воркера и переживает тесты: без чистки соседний
    # прогон видит чужие группы, и «не видел ни одного» не воспроизводится.
    monkeypatch.setattr(core.app.state, "telegram_group_seen", {}, raising=False)
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


def private(text: str) -> dict:
    return {"message": {"chat": {"id": OWNER, "type": "private"},
                        "from": {"id": OWNER}, "text": text, "date": 1757721600}}


def status_of(bot) -> str:
    bot.sent.clear()
    bot._handle_update(private("/status"))
    answers = [text for chat, text in bot.sent if chat == OWNER]
    assert answers, "на /status в личке бот обязан отвечать"
    return answers[-1]


def test_status_says_nothing_seen_when_nothing_was_seen(bot) -> None:
    """Пустой счёт — это ответ, а не прочерк: privacy mode виден только так."""
    answer = status_of(bot)
    assert "Группы:" in answer
    assert "ни одного" in answer


def test_status_carries_what_the_group_gave(bot) -> None:
    """Сообщение из группы дошло — значит в `/status` есть её имя и счёт."""
    bot._handle_update(group("доброе утро"))
    answer = status_of(bot)
    assert "Стройка" in answer, answer


def test_the_binding_outcome_reaches_status(bot, monkeypatch) -> None:
    """Исход разбора важнее счёта: по нему и видно, куда легла сводка."""
    monkeypatch.setattr(bot.core, "_site_chat_store",
                        lambda chat_id, text, taken_at, project="": {"bound": project})
    bot._handle_update(group("/site Кутузов Сити"))
    answer = status_of(bot)
    assert "Кутузов Сити" in answer, answer


def test_the_line_is_read_from_the_engine(bot) -> None:
    """Строка объявлена один раз — в движке; обёртка её только печатает.

    Своя копия расходится молча: у неё нет ни счёта, ни оговорки про два
    воркера, а выглядит она так же.
    """
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "core._telegram_group_seen_line()" in source
    assert "Группы:" not in source, "второй копии строки быть не должно"
