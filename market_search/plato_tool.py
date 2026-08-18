"""Оценка рынка конкурентов как инструмент Платона Сергеевича.

Коммерческий блок спрашивает не «покажи выдачу», а «почём соседи и что ставить
в цену квартир». Ответ на это уже считается конвейером v6; Платону нужен доступ
к нему, а не собственный поиск. Поэтому инструмент — тонкий: он берёт адрес,
зовёт общий расчёт и отдаёт то же, что видит панель, только без диагностики.

Числа считает движок, модель их пересказывает. Это то же правило, по которому
инструмент чувствительности будет читать результат ``/analysis/sensitivity``,
а не выводить его текстом.
"""

from __future__ import annotations

from typing import Any

from .assessment import address_from_inputs, assess, for_agent

TOOL_NAME = "market_analogues"

# Вход в инструмент со стороны человека. Кнопка живёт рядом с самим
# инструментом, а не в разметке движка: инструмента нет — нечего и предлагать,
# а кнопка, зовущая отсутствующий инструмент, выглядит как поломка агента.
_CHIP_ANCHOR = '<div class="ai-quick">'
_CHIP = (
    _CHIP_ANCHOR
    + "\n    <button class=\"ai-chip\" onclick=\"askAgentQuick("
    + "'Оцени рынок конкурентов вокруг площадки: какие жилые комплексы строятся и продаются рядом, "
    + "почём метр у каждого, чем они отличаются по классу и застройщику, и какая цена квартир "
    + "обоснована для нашего проекта.','market_analogues')\">Рынок конкурентов</button>"
)

# Правило выбора инструмента живёт там же, где сам инструмент. Набор Платону
# перечисляет, чем на что отвечать, и инструмент, не названный в этом списке,
# вызывается через раз: описание в схеме модель читает, а правило — исполняет.
_RULE_ANCHOR = "- Вопрос «как сделать», «с чего начать», «где кнопка» → get_user_guide"
_RULE = (
    "- «Почём рынок рядом», «какие конкуренты», «обоснована ли наша цена квартир», "
    "«насколько мы дороже соседей» → market_analogues. Адрес не выдумывай: инструмент "
    "берёт его из вводных модели, поэтому передавай пустую строку, а radius_km и limit — "
    "нулями, если пользователь не назвал свои. Не нашёл адреса — спроси, а не оценивай "
    "наугад. Цену предложения и официальную среднюю ЕИСЖС не смешивай: вторая — среднее "
    "по зарегистрированным сделкам, она отстаёт от рынка, и выдавать её за текущую цену "
    "нельзя. Аналоги в карантине в выводы не бери, но если их много — скажи, что выборка "
    "узкая.\n"
)

_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "Оценка рынка конкурентов вокруг площадки: строящиеся и продающиеся ЖК в радиусе, "
        "их цены предложения за м², класс, район, застройщик, темп продаж и экспозиция, "
        "плюс рекомендованная цена для поля «Цена квартир» в тыс. ₽/м². "
        "Обязательно использовать для вопросов «почём рынок рядом», «какие конкуренты», "
        "«обоснована ли цена квартир», «на сколько мы дороже соседей». "
        "Адрес оставь пустым — он берётся из вводных модели по кадастровому разбору."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "Адрес площадки. Пусто — взять из вводных модели.",
            },
            "radius_km": {
                "type": "number",
                "description": "Радиус поиска, км. 0 — по умолчанию 3 км.",
            },
            "limit": {
                "type": "integer",
                "description": "Сколько аналогов вернуть. 0 — по умолчанию 10.",
            },
        },
        "required": ["address", "radius_km", "limit"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _clamp(value: Any, *, default: float, low: float, high: float) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return max(low, min(high, number))


def run(service: Any, args: dict[str, Any], inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Выполнить инструмент. Вынесено из обёртки, чтобы тест звал то же самое."""
    address = " ".join(str(args.get("address") or "").split())
    source = "argument"
    if not address:
        address = address_from_inputs(inputs)
        source = "model_inputs"
    if not address:
        return {
            "available": False,
            "reason": (
                "Адрес площадки неизвестен: в модели нет кадастрового разбора, "
                "а в вопросе адрес не назван. Спроси адрес у пользователя."
            ),
        }
    assessment = assess(
        service,
        address=address,
        radius_km=_clamp(args.get("radius_km"), default=3.0, low=0.25, high=10.0),
        limit=int(_clamp(args.get("limit"), default=10.0, low=1.0, high=20.0)),
    )
    result = for_agent(assessment)
    result["address_source"] = source
    return result


def install(core: Any, service: Any) -> None:
    """Добавить инструмент в набор Платона и в разбор вызовов.

    Набор читается на каждом раунде и правится на месте, поэтому дописать в него
    достаточно. Разбор — обычная функция модуля: переопределение имени в
    ``core`` меняет и то, что видит цикл вызова, потому что он берёт её из
    глобалей того же модуля.
    """
    if getattr(core, "_MARKET_PLATO_TOOL_INSTALLED", False):
        return
    tools = getattr(core, "_AGENT_TOOLS", None)
    if not isinstance(tools, list):
        raise RuntimeError("В движке нет набора инструментов Платона (_AGENT_TOOLS)")
    if not any(str(item.get("name") or "") == TOOL_NAME for item in tools):
        tools.append(_TOOL_SPEC)

    instructions = getattr(core, "_AGENT_INSTRUCTIONS", None)
    if isinstance(instructions, str):
        if _RULE_ANCHOR not in instructions:
            raise RuntimeError(
                "В инструкциях Платона нет списка правил выбора инструментов: "
                "правило рынка не встало"
            )
        core._AGENT_INSTRUCTIONS = instructions.replace(_RULE_ANCHOR, _RULE + _RULE_ANCHOR, 1)

    page = getattr(core, "PAGE", None)
    if isinstance(page, str):
        if _CHIP_ANCHOR not in page:
            raise RuntimeError(
                "В странице нет блока быстрых вопросов Платона (ai-quick): "
                "кнопка рынка не встала, обновите подстановку вместе с разметкой"
            )
        core.PAGE = page.replace(_CHIP_ANCHOR, _CHIP, 1)

    previous = core._execute_agent_tool

    def execute_agent_tool(name: str, args: dict[str, Any], req: Any, bundle: dict[str, Any]) -> dict[str, Any]:
        if name == TOOL_NAME:
            return run(service, args, getattr(req, "inputs", None))
        return previous(name, args, req, bundle)

    core._execute_agent_tool = execute_agent_tool
    core._MARKET_PLATO_TOOL_INSTALLED = True
