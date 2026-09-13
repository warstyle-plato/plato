"""Кем Платон думает — решает переключатель, а не наличие ключа.

Правило то же, что у маршрута Платона: «маршрут решает `PLATO_AI_URL`, а не
наличие ключа». Молчаливый выбор поставщика по тому, какой ключ нашёлся,
однажды увёл бы вопрос не туда — и снаружи это выглядело бы как обычный ответ.
Поэтому поставщик называется явно: `PLATO_MODEL_PROVIDER` = `openai` (умолчание)
или `anthropic`. Неизвестное значение — отказ с причиной, а не тихий откат.

Второй реализации цикла агента здесь нет и быть не должно. Цикл вызова
инструментов, кэш, билеты и очередь от поставщика не зависят вовсе — зависят
ровно четыре вещи: адрес вызова, форма запроса, форма ответа и схема
инструментов. Их и переводит этот модуль, оставляя движку его внутреннюю форму
(она совпадает с формой OpenAI Responses, потому что исторически была ею).

Обратный перевод обязан быть БЕЗ ПОТЕРЬ: Anthropic требует возвращать блоки
ответа неизменными — в том числе блоки размышления, — иначе следующий раунд
разговора считается по обрезанной истории. Поэтому сырые блоки едут вместе с
переведёнными элементами под служебными ключами и собираются обратно как есть.
"""

from __future__ import annotations

import json
import os
from typing import Any

# Умолчание — самая способная общедоступная модель Anthropic. Понижать её
# «ради экономии» нельзя: это решение владельца, а не наше.
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"

_TURN_KEY = "_provider_turn"
_BLOCKS_KEY = "_provider_blocks"

_KNOWN = ("openai", "anthropic")


class ProviderError(RuntimeError):
    """Отказ поставщика, доносимый до чата: причина в тексте, а не в логе."""


def provider_name() -> str:
    """Кто думает. Пустое значение — OpenAI: так работало до появления выбора."""
    raw = (os.getenv("PLATO_MODEL_PROVIDER", "") or "").strip().lower()
    if not raw:
        return "openai"
    if raw not in _KNOWN:
        raise ProviderError(
            f"PLATO_MODEL_PROVIDER={raw!r} — не из {' / '.join(_KNOWN)}. "
            "Поставщик задаётся явно: угадывать его по найденному ключу нельзя."
        )
    return raw


def anthropic_model(default_model: str = "") -> str:
    """Модель Anthropic. Имя модели OpenAI сюда не подставляется.

    `gpt-5.6` для Anthropic — не модель, а строка, и запрос с ней получил бы
    отказ, выглядящий как поломка связи.
    """
    named = (os.getenv("PLATO_ANTHROPIC_MODEL", "") or "").strip()
    if named:
        return named
    if default_model.startswith("claude"):
        return default_model
    return DEFAULT_ANTHROPIC_MODEL


def tools_for_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Схема инструментов: у OpenAI `parameters`, у Anthropic `input_schema`.

    Второго списка инструментов не заводим — переводится тот же самый
    `_AGENT_TOOLS`: разойдясь, два списка дали бы модели разные инструменты
    под одним именем.
    """
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        if tool.get("type") not in (None, "function"):
            # Серверные инструменты OpenAI переводу не подлежат: у них другой
            # исполнитель. Молча выбросить нельзя — это потеря возможности.
            raise ProviderError(
                f"Инструмент {tool.get('name') or tool.get('type')!r} не переводится "
                "на Anthropic: это не функция."
            )
        item: dict[str, Any] = {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "input_schema": tool.get("parameters") or {"type": "object", "properties": {}},
        }
        if tool.get("strict"):
            # `strict` требует `additionalProperties: false` и `required` —
            # у наших схем они уже есть, и проверять это должен не читатель.
            # Условие строгости — «схема закрыта», а не «список required непуст»:
            # у инструмента без параметров он пуст законно, и первая версия
            # проверки заворачивала как раз такой (`diagnose_project_logic`).
            schema = item["input_schema"]
            named = set((schema.get("properties") or {}).keys())
            required = set(schema.get("required") or [])
            if schema.get("additionalProperties") is not False or required != named:
                raise ProviderError(
                    f"У инструмента {item['name']!r} стоит strict, но схема не закрыта: "
                    "нужны additionalProperties=false и required, перечисляющий все свойства "
                    f"(нет в required: {sorted(named - required) or '—'})."
                )
            item["strict"] = True
        out.append(item)
    return out


def _text_of(content: Any) -> str:
    """Содержимое элемента разговора текстом, в какой бы форме оно ни пришло."""
    if isinstance(content, str):
        return content
    pieces: list[str] = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") in ("output_text", "text", "input_text") and part.get("text"):
            pieces.append(str(part["text"]))
    return "\n".join(pieces)


def messages_for_anthropic(input_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Разговор во внутренней форме → `messages` Anthropic.

    Ход ассистента собирается ОДНИМ сообщением из сохранённых сырых блоков:
    склеенный из переведённых кусков, он потерял бы блоки размышления, а
    потерянные блоки — это другой разговор, а не тот же самый короче.
    """
    messages: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []
    seen_turns: set[str] = set()

    def flush_results() -> None:
        if pending_results:
            messages.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for item in input_items or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")

        if kind == "function_call_output":
            pending_results.append({
                "type": "tool_result",
                "tool_use_id": str(item.get("call_id", "")),
                "content": str(item.get("output", "")),
            })
            continue

        flush_results()

        turn = item.get(_TURN_KEY)
        if turn:
            # Все элементы одного хода ассистента несут его блоки целиком;
            # берём ход один раз и пропускаем остальные его элементы.
            if turn in seen_turns:
                continue
            seen_turns.add(turn)
            blocks = item.get(_BLOCKS_KEY) or []
            if blocks:
                messages.append({"role": "assistant", "content": blocks})
            continue

        if kind == "function_call":
            # Ход, пришедший не от нас (например, из прежнего разговора на
            # OpenAI): восстанавливаем вызов инструмента как умеем.
            try:
                args = json.loads(item.get("arguments") or "{}")
            except Exception:
                args = {}
            messages.append({"role": "assistant", "content": [{
                "type": "tool_use",
                "id": str(item.get("call_id", "")),
                "name": str(item.get("name", "")),
                "input": args,
            }]})
            continue

        role = item.get("role")
        if role in ("user", "assistant"):
            text = _text_of(item.get("content"))
            if text.strip():
                messages.append({"role": role, "content": text})
            continue

        if kind == "message":
            text = _text_of(item.get("content"))
            if text.strip():
                messages.append({"role": "assistant", "content": text})

    flush_results()
    return messages


def response_to_internal(message: Any, turn_id: str) -> dict[str, Any]:
    """Ответ Anthropic → внутренняя форма, которую читает цикл агента.

    Сырые блоки едут рядом: они нужны следующему раунду неизменными.
    """
    blocks = [
        block.model_dump() if hasattr(block, "model_dump") else dict(block)
        for block in (getattr(message, "content", None) or [])
    ]
    output: list[dict[str, Any]] = []
    texts: list[str] = []

    for block in blocks:
        if block.get("type") == "text" and block.get("text"):
            texts.append(str(block["text"]))

    if texts:
        output.append({
            "type": "message",
            "content": [{"type": "output_text", "text": "\n".join(texts)}],
            _TURN_KEY: turn_id,
            _BLOCKS_KEY: blocks,
        })

    for block in blocks:
        if block.get("type") != "tool_use":
            continue
        output.append({
            "type": "function_call",
            "name": str(block.get("name", "")),
            "call_id": str(block.get("id", "")),
            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
            _TURN_KEY: turn_id,
            _BLOCKS_KEY: blocks,
        })

    if not output and blocks:
        # Ход без текста и без вызова инструмента (например, одно размышление)
        # обязан доехать до следующего раунда — иначе он потерян молча.
        output.append({
            "type": "message",
            "content": [],
            _TURN_KEY: turn_id,
            _BLOCKS_KEY: blocks,
        })

    return {
        "id": getattr(message, "id", "") or "",
        "output": output,
        "stop_reason": getattr(message, "stop_reason", "") or "",
    }
