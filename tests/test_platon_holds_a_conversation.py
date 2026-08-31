"""Платон помнит сказанное — на всех поверхностях, а не на одной.

«Платон должен везде уметь вести диалог, а не один ответ» (владелец,
30.08.2026). Разговор держала только главная страница: она слала `history` в
`/agent/chat`. Кабинет рынка, свод продаж, торги и монитор спрашивали его с
чистого листа каждый раз — уточнить сказанное было нельзя, потому что
сказанного он не помнил. Свод продаж при этом СКЛАДЫВАЛ ответы на экране, и
выглядело это разговором: человек видел стопку реплик и вправе был ждать, что
собеседник их помнит.

Правило разговора объявлено один раз (`plato_question.platoThread`) и
подставляется на страницы, как контур, подвал и версия. История несёт
РАЗГОВОР, а не данные: числа едут свежими в самом вопросе, потому что источник
мог смениться между репликами, а движок каждую реплику истории обрезает по
длине — свод, уехавший в неё целиком, вернулся бы обрубком и выглядел бы
полным.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plato_question  # noqa: E402


def _surfaces() -> dict[str, str]:
    """Поверхности, на которых Платона спрашивают, — по одной сборке каждая."""
    import auction_search.ui as auction_ui
    import main_legacy
    import market_search.cabinet as cabinet

    return {
        "торги": auction_ui.auctions_page(),
        "кабинет рынка": cabinet.cabinet_page("market"),
        "свод продаж": cabinet.cabinet_page("sales"),
        "монитор": main_legacy.MONITOR_PAGE_HTML,
    }


def test_every_surface_carries_the_one_conversation_rule() -> None:
    """Правило разговора одно на все поверхности: копию негде обновлять."""
    for name, page in _surfaces().items():
        assert "function platoThread(" in page, f"{name}: разговора нет вовсе"
        assert plato_question.PLACEHOLDER not in page, (
            f"{name}: плейсхолдер остался строкой на экране")
        # Своей памяти у поверхности быть не должно — иначе их станет две.
        assert page.count("function platoThread(") == 1, (
            f"{name}: разговор объявлен дважды")


def test_every_surface_sends_the_conversation_with_the_question() -> None:
    """Помнить нечего, если история не уезжает вместе с вопросом."""
    for name, page in _surfaces().items():
        # Разговор доехал до вопроса: кабинет отдаёт его своему `platoAnswer`
        # третьим доводом, торги и монитор — прямо в теле запроса.
        assert re.search(r"\w+Talk\.history\(\)", page), (
            f"{name}: вопрос уходит без истории — Платон отвечает с чистого листа")
        # И до сервера: тело запроса несёт поле, иначе история никуда не идёт.
        assert re.search(r"history:\s*(history\s*\|\||\w+Talk\.history\(\))", page), (
            f"{name}: тело запроса истории не несёт")
        assert re.search(r"\w+Talk\.said\(", page), (
            f"{name}: ответ не запоминается")


def test_the_conversation_carries_replies_not_the_data() -> None:
    """В историю уходит вопрос человека, а не сообщение со сводом.

    Движок обрезает каждую реплику истории по длине: свод, уехавший в неё
    целиком, вернулся бы обрубком — и выглядел бы полным. Числа поэтому едут
    свежими в самом вопросе, а история несёт разговор.
    """
    import market_search.cabinet as cabinet

    page = cabinet.cabinet_page("sales")
    for call in re.findall(r"\w+Talk\.said\(([^,]+),", page):
        assert "message" not in call, (
            f"в историю уехало сообщение со сводом, а не вопрос: {call.strip()}")


def test_a_new_source_ends_the_conversation_about_the_old_one() -> None:
    """Сменился источник — Платон помнил бы то, чего в своде уже нет."""
    import market_search.cabinet as cabinet

    page = cabinet.cabinet_page("sales")
    assert "salesTalk.reset()" in page, "новый источник разговор не обрывает"
    assert "marketTalk.reset()" in cabinet.cabinet_page("market"), (
        "новый объект разговор не обрывает")


def test_the_conversation_behaves_like_a_conversation() -> None:
    """Правило гоняется настоящим кодом, а не его пересказом."""
    script = plato_question.SCRIPT + """
const talk = platoThread();
const said = [];
said.push(['новый пустой', talk.rounds() === 0 && talk.history().length === 0]);
talk.said('первый вопрос', 'первый ответ');
const first = talk.history();
said.push(['вопрос ролью user', first[0].role === 'user'
  && first[0].content === 'первый вопрос']);
said.push(['ответ ролью assistant', first[1].role === 'assistant']);
for (let i = 0; i < 10; i++) talk.said('в' + i, 'о' + i);
said.push(['разговор не растёт без конца', talk.turns.length === 12]);
said.push(['в движок едет шесть реплик', talk.history().length === 6]);
said.push(['последний обмен на месте',
  talk.turns[talk.turns.length - 2].content === 'в9']);
talk.reset();
said.push(['сброс сбрасывает', talk.rounds() === 0]);
console.log(JSON.stringify(said));
"""
    tools = ROOT / "tests" / "_conversation.js"
    tools.write_text(script, encoding="utf-8")
    try:
        run = subprocess.run([_node(), str(tools)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tools.unlink(missing_ok=True)
    assert run.returncode == 0, run.stderr
    for name, ok in json.loads(run.stdout.strip().splitlines()[-1]):
        assert ok, f"разговор ведёт себя не как разговор: {name}"


def _node() -> str:
    from shutil import which

    node = which("node")
    if not node:
        pytest.skip("node в образе нет — проверить настоящий код нечем")
    return node


def test_the_route_forwards_the_conversation_to_the_engine(monkeypatch) -> None:
    """Кабинет и монитор отдают историю движку, а не роняют её у себя.

    Поле, которого нет в карте запроса, молча остаётся пустым — и разговор
    выглядит ведущимся, пока Платон отвечает с чистого листа.
    """
    import main_legacy
    import main_registry

    talk = [{"role": "user", "content": "первый вопрос"},
            {"role": "assistant", "content": "первый ответ"},
            {"role": "system", "content": "чужая роль"},
            {"role": "user", "content": "  "}]

    seen: list[Any] = []
    monkeypatch.setattr(main_registry.core, "plato_answer_handoff",
                        lambda payload, request: seen.append(payload) or {"reply": "ok"})
    main_registry._plato_ask("вопрос", object(), talk)
    assert seen, "кабинет движок не позвал"
    assert [item["content"] for item in seen[0].history] == [
        "первый вопрос", "первый ответ", "чужая роль", "  "], (
        "кабинет отдал не то, что ему дали")

    seen.clear()
    monkeypatch.setattr(main_legacy, "_require_web_access",
                        lambda session, key, what: None)
    monkeypatch.setattr(main_legacy, "plato_answer_handoff",
                        lambda payload, request: seen.append(payload) or {"reply": "ok"})
    main_legacy.monitor_ask(
        main_legacy.MonitorAskRequest(message="вопрос", history=talk), object())
    assert seen, "монитор движок не позвал"
    # Чужая роль и пустая реплика до движка не едут: он читает историю как
    # разговор, и «system» в ней — не реплика собеседника.
    assert [(item["role"], item["content"]) for item in seen[0].history] == [
        ("user", "первый вопрос"), ("assistant", "первый ответ")]


def test_the_monitor_hands_the_question_to_polling() -> None:
    """Спрашивает браузер — соединение держится до передачи работы опросу.

    Правило было выведено на кабинете рынка, а в мониторе жил `plato_answer`,
    ждущий ответ целиком, — при том что его же строка обещала опрос.
    """
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def monitor_ask("):]
    body = body[:body.index("\n\n\n")]
    assert "plato_answer_handoff(" in body, "монитор держит соединение до конца ответа"
    assert "return plato_answer(" not in body, "это путь бота, а не окна"


def test_the_cabinet_route_takes_the_conversation_but_not_junk(monkeypatch) -> None:
    """`/cabinet/ask` принимает историю и чистит её на входе.

    Роль решает движок, а не страница: «system» в истории — не реплика
    собеседника, а пустая реплика в разговоре не значит ничего. И берутся
    последние шесть: дальше движок всё равно не смотрит.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    seen: list[Any] = []
    app = FastAPI()
    service = install(app)
    # Платон приходит к модулю рынка крючком от движка (`main_registry`), а не
    # своей реализацией: здесь на его место встаёт запись вызова.
    service.plato_ask = (lambda message, request, history=None:
                         seen.append((message, history)) or {"reply": "ответ"})
    client = TestClient(app)

    talk = [{"role": "system", "content": "чужая роль"},
            {"role": "user", "content": "  "}]
    talk += [{"role": "user", "content": f"в{i}"} for i in range(8)]
    got = client.post("/cabinet/ask", json={"message": "вопрос", "history": talk},
                      headers={"X-Market-Key": "test-key"})
    assert got.status_code == 200, got.text
    assert seen, "маршрут Платона не позвал"
    message, history = seen[0]
    assert message == "вопрос"
    assert [item["content"] for item in history] == ["в2", "в3", "в4", "в5", "в6", "в7"], (
        "маршрут отдал движку чужие роли, пустые реплики или больше шести")

    # Вопрос без истории по-прежнему проходит: разговор начинается с первой
    # реплики, а не требует её заранее.
    seen.clear()
    plain = client.post("/cabinet/ask", json={"message": "вопрос"},
                        headers={"X-Market-Key": "test-key"})
    assert plain.status_code == 200, plain.text
    assert seen[0][1] == []
