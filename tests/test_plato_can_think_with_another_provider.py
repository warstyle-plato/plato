"""Платон умеет думать не только одним поставщиком, и выбор объявлен вслух.

08.09.2026 у владельца без объяснения причины деактивировали аккаунт ChatGPT.
Платон при этом живёт не на подписке, а на ключе платформы — но выяснилось, что
поставщик у него ровно один и запасного пути нет вовсе. Отсюда правило:
поставщик называется ЯВНО (`PLATO_MODEL_PROVIDER`), как маршрут называется
`PLATO_AI_URL`. Молчаливый выбор по найденному ключу увёл бы вопрос не туда, и
снаружи это выглядело бы обычным ответом.

Проверяется здесь то, что нельзя проверить чтением кода:

* перевод разговора ТУДА и ОБРАТНО без потерь — блоки размышления обязаны
  доехать до следующего раунда неизменными, иначе разговор считается по
  обрезанной истории;
* схема инструментов переводится из ТОГО ЖЕ `_AGENT_TOOLS` — второй список
  дал бы модели разные инструменты под одним именем;
* цикл агента поставщика не знает: подделанный ответ Anthropic проходит его
  насквозь, вызывает инструмент и возвращает текст;
* неизвестное значение переключателя — отказ с причиной, а не тихий откат.

Запуск: python3 -m pytest tests/test_plato_can_think_with_another_provider.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import plato_provider  # noqa: E402


class _Block(dict):
    """Блок ответа: у настоящего SDK есть `model_dump`, у словаря — нет."""

    def model_dump(self):  # noqa: D401 - форма настоящего блока
        return dict(self)


class _Message:
    def __init__(self, content, stop_reason="end_turn", ident="msg_1"):
        self.content = content
        self.stop_reason = stop_reason
        self.id = ident


def test_the_provider_is_named_and_not_guessed(monkeypatch):
    monkeypatch.delenv("PLATO_MODEL_PROVIDER", raising=False)
    assert plato_provider.provider_name() == "openai", "умолчание обязано остаться прежним"
    monkeypatch.setenv("PLATO_MODEL_PROVIDER", "anthropic")
    assert plato_provider.provider_name() == "anthropic"
    monkeypatch.setenv("PLATO_MODEL_PROVIDER", "нечто")
    with pytest.raises(plato_provider.ProviderError) as exc:
        plato_provider.provider_name()
    assert "нечто" in str(exc.value), "отказ обязан назвать, что именно задано"


def test_an_openai_model_name_never_reaches_anthropic(monkeypatch):
    """`gpt-5.6` для Anthropic не модель, а строка: запрос получил бы отказ."""
    monkeypatch.delenv("PLATO_ANTHROPIC_MODEL", raising=False)
    assert plato_provider.anthropic_model("gpt-5.6").startswith("claude")
    assert plato_provider.anthropic_model("").startswith("claude")
    assert plato_provider.anthropic_model("claude-sonnet-5") == "claude-sonnet-5"
    monkeypatch.setenv("PLATO_ANTHROPIC_MODEL", "claude-haiku-4-5")
    assert plato_provider.anthropic_model("gpt-5.6") == "claude-haiku-4-5"


def test_the_tools_are_translated_from_the_engine_list():
    """Второго списка инструментов нет — переводится тот же самый."""
    import main_legacy as core

    translated = plato_provider.tools_for_anthropic(core._AGENT_TOOLS)
    assert len(translated) == len(core._AGENT_TOOLS)
    for source, item in zip(core._AGENT_TOOLS, translated):
        assert item["name"] == source["name"]
        assert item["input_schema"] == source["parameters"], "схема обязана доехать целиком"
        assert "parameters" not in item, "имя поля у Anthropic другое"


def test_a_strict_tool_with_an_open_schema_is_refused():
    """`strict` без закрытой схемы — отказ, а не молча снятая строгость."""
    with pytest.raises(plato_provider.ProviderError):
        plato_provider.tools_for_anthropic([{
            "type": "function", "name": "x", "description": "",
            "parameters": {"type": "object", "properties": {}},
            "strict": True,
        }])


def test_a_round_trip_keeps_the_thinking_blocks():
    """Блоки размышления доезжают до следующего раунда НЕИЗМЕННЫМИ."""
    message = _Message([
        _Block({"type": "thinking", "thinking": "считаю LLCR", "signature": "sig-1"}),
        _Block({"type": "text", "text": "Сейчас посчитаю."}),
        _Block({"type": "tool_use", "id": "toolu_1", "name": "explain_metric",
                "input": {"metric": "llcr", "scope": "selected"}}),
    ], stop_reason="tool_use")

    internal = plato_provider.response_to_internal(message, turn_id="t1")
    calls = [item for item in internal["output"] if item["type"] == "function_call"]
    assert len(calls) == 1, "цикл агента ищет вызовы именно так"
    assert calls[0]["name"] == "explain_metric"
    assert json.loads(calls[0]["arguments"]) == {"metric": "llcr", "scope": "selected"}

    history = [{"role": "user", "content": "почему LLCR такой?"}]
    history.extend(internal["output"])
    history.append({"type": "function_call_output", "call_id": "toolu_1",
                    "output": json.dumps({"llcr": 1.07}, ensure_ascii=False)})

    messages = plato_provider.messages_for_anthropic(history)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == [dict(block) for block in message.content], (
        "ход ассистента обязан вернуться блок в блок — включая размышление")
    assert messages[2]["content"][0]["type"] == "tool_result"
    assert messages[2]["content"][0]["tool_use_id"] == "toolu_1"


def test_one_assistant_turn_is_one_message():
    """Текст и вызов одного хода — одно сообщение, а не два."""
    message = _Message([
        _Block({"type": "text", "text": "Считаю."}),
        _Block({"type": "tool_use", "id": "a", "name": "explain_metric", "input": {}}),
        _Block({"type": "tool_use", "id": "b", "name": "goal_seek", "input": {}}),
    ], stop_reason="tool_use")
    internal = plato_provider.response_to_internal(message, turn_id="t2")
    assert len(internal["output"]) == 3, "текст и два вызова"
    messages = plato_provider.messages_for_anthropic(internal["output"])
    assert len(messages) == 1, "три элемента одного хода — одно сообщение ассистента"
    assert len(messages[0]["content"]) == 3


def test_several_tool_results_go_in_one_message():
    """Разбитые по сообщениям результаты отучают модель звать инструменты разом."""
    history = [
        {"type": "function_call_output", "call_id": "a", "output": "{}"},
        {"type": "function_call_output", "call_id": "b", "output": "{}"},
    ]
    messages = plato_provider.messages_for_anthropic(history)
    assert len(messages) == 1 and len(messages[0]["content"]) == 2


def test_a_turn_without_text_is_not_lost():
    """Ход из одного размышления обязан доехать: иначе он потерян молча."""
    message = _Message([_Block({"type": "thinking", "thinking": "…", "signature": "s"})])
    internal = plato_provider.response_to_internal(message, turn_id="t3")
    assert internal["output"], "ход исчез"
    messages = plato_provider.messages_for_anthropic(internal["output"])
    assert messages and messages[0]["content"][0]["type"] == "thinking"


def test_the_agent_loop_does_not_know_the_provider(monkeypatch):
    """Подделанный ответ Anthropic проходит цикл агента насквозь.

    Проверяется не пересказ, а сам круг: вызов инструмента и текст ответа.
    """
    import main_legacy as core

    monkeypatch.setenv("PLATO_MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    turns = [
        _Message([
            _Block({"type": "thinking", "thinking": "нужен расчёт", "signature": "s1"}),
            _Block({"type": "tool_use", "id": "toolu_1", "name": "explain_metric",
                    "input": {"metric": "llcr", "scope": "selected"}}),
        ], stop_reason="tool_use"),
        _Message([_Block({"type": "text", "text": "LLCR держится на 1,07x."})]),
    ]
    seen: list[dict] = []

    class _Messages:
        def create(self, **request):
            seen.append(request)
            return turns[len(seen) - 1]

    class _Client:
        def __init__(self, **_kw):
            self.messages = _Messages()

    fake = type(sys)("anthropic")
    fake.Anthropic = _Client
    fake.APIStatusError = type("APIStatusError", (Exception,), {"status_code": 500})
    fake.APIConnectionError = type("APIConnectionError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    first = core._openai_direct_request({
        "model": "gpt-5.6",
        "instructions": "ты Платон",
        "input": [{"role": "user", "content": "почему LLCR такой?"}],
        "tools": core._AGENT_TOOLS,
        "max_output_tokens": 2600,
        "reasoning": {"effort": "low"},
    })
    calls = [item for item in first["output"] if item["type"] == "function_call"]
    assert calls and calls[0]["name"] == "explain_metric"

    assert seen[0]["model"].startswith("claude"), "имя модели OpenAI до Anthropic не доезжает"
    assert seen[0]["system"] == "ты Платон"
    assert seen[0]["thinking"] == {"type": "adaptive"}
    assert seen[0]["output_config"] == {"effort": "low"}
    assert seen[0]["max_tokens"] == 2600
    assert "input_schema" in seen[0]["tools"][0]

    history = [{"role": "user", "content": "почему LLCR такой?"}]
    history.extend(first["output"])
    history.append({"type": "function_call_output", "call_id": "toolu_1",
                    "output": json.dumps({"llcr": 1.07})})
    second = core._openai_direct_request({
        "model": "gpt-5.6", "instructions": "ты Платон", "input": history,
        "tools": core._AGENT_TOOLS, "max_output_tokens": 2600,
    })
    assert core._extract_openai_text(second) == "LLCR держится на 1,07x."
    assert seen[1]["messages"][1]["content"][0]["type"] == "thinking", (
        "размышление первого хода не доехало до второго")


def test_a_missing_key_names_where_to_get_it(monkeypatch):
    """Отказ говорит, чего не хватает и где это берут, а не «ошибка»."""
    import main_legacy as core
    from fastapi import HTTPException

    monkeypatch.setenv("PLATO_MODEL_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        core._openai_direct_request({"input": [{"role": "user", "content": "?"}]})
    assert "ANTHROPIC_API_KEY" in str(exc.value.detail)
    assert "console.anthropic.com" in str(exc.value.detail)


def test_the_openai_path_is_untouched(monkeypatch):
    """Умолчание обязано остаться прежним: сегодня ничего не меняется."""
    import main_legacy as core
    from fastapi import HTTPException

    monkeypatch.delenv("PLATO_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        core._openai_direct_request({"input": []})
    assert "OPENAI_API_KEY" in str(exc.value.detail), "ушли не по тому пути"
