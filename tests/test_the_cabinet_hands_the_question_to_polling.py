"""Кабинет спрашивает Платона так же, как окно, а не как бот.

Цепочка ядро → Render → OpenAI одним соединением не держится: у nginx свои
шестьдесят секунд, у мобильного Safari свои, и вопрос, гоняющий модель с
инструментами, не укладывается ни в один. Работа при этом доходит до конца и
уносится в никуда, а в браузер приезжает страница ошибки — «комментарии
Платона так и не подключились» (владелец, 26.08.2026).

`plato_answer` ждёт ответ целиком, и это верно ровно для одного случая — бота:
он живёт в этом же процессе, ждёт в своём потоке, и забирать результат ему
неоткуда. Всем, кто спрашивает из браузера, нужен `plato_answer_handoff`:
соединение держится до передачи работы опросу, дальше ответ забирают по номеру
запуска.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_cabinet_uses_the_handoff_not_the_bot_path() -> None:
    source = (ROOT / "main_registry.py").read_text()
    body = source[source.index("def _plato_ask("):]
    body = body[:body.index("\n\n\n")]
    assert "plato_answer_handoff" in body, "кабинет держит соединение до конца ответа"
    assert "core.plato_answer(" not in body, "это путь бота, а не окна"


def test_the_handoff_returns_a_ticket_when_the_work_is_slow(monkeypatch) -> None:
    import main_legacy

    never = threading.Event()
    monkeypatch.setattr(main_legacy, "_PLATO_CHAT_HANDOFF_SECONDS", 0.05)
    monkeypatch.setattr(main_legacy, "_plato_chat_launch",
                        lambda req, request: ("abcd1234", never, {}))
    got = main_legacy.plato_answer_handoff(object(), object())
    assert got == {"pending": True, "trace_id": "abcd1234"}


def test_the_fast_answer_comes_back_on_the_same_request(monkeypatch) -> None:
    """Опрос платится только за долгую работу."""
    import main_legacy

    done = threading.Event()
    done.set()
    monkeypatch.setattr(main_legacy, "_plato_chat_launch",
                        lambda req, request: ("abcd1234", done, {"reply": "готово"}))
    monkeypatch.setattr(main_legacy, "_plato_chat_result",
                        lambda trace_id, outcome: {"reply": outcome["reply"]})
    assert main_legacy.plato_answer_handoff(object(), object()) == {"reply": "готово"}


def test_one_implementation_of_the_handoff() -> None:
    """Две копии передачи работы однажды разойдутся на сроке ожидания."""
    source = (ROOT / "main_legacy.py").read_text()
    assert source.count("def plato_answer_handoff(") == 1
    chat = source[source.index("def agent_chat("):]
    chat = chat[:chat.index("\n\ndef ")]
    assert "plato_answer_handoff(" in chat, "маршрут окна зовёт её же"
    assert '"pending": True' not in chat, "передача работы описана дважды"


def test_the_bot_keeps_waiting_in_its_own_thread() -> None:
    """Боту «работа принята» бесполезна: забирать результат ему неоткуда."""
    source = (ROOT / "main_legacy.py").read_text()
    body = source[source.index("def plato_answer("):]
    body = body[:body.index("\n\n@app.post")]
    assert "_PLATO_AGENT_WAIT_SECONDS" in body
    assert "pending" not in body


def test_the_page_takes_the_ticket_and_polls() -> None:
    page = (ROOT / "market_search" / "cabinet.py").read_text()
    body = page[page.index("async function platoAnswer("):]
    body = body[:body.index("\n}")]
    assert "/agent/result/" in body, "за долгим ответом ходят по номеру запуска"
    assert "d.trace_id" in body
