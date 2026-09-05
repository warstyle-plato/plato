"""Расчётный лимит БРИДЖа — цифра одного договора, и суммировать их нельзя.

Владелец, 04.09.2026: «это некорректное название, для очередных проектов, это
глупость а не расчетный бридж… при чем тут бридж и 7,5 в рассрочку? и пики
всех бриджей вместе взятых». У проекта с очередями договоров столько же,
сколько очередей, открыты они в разные годы — сложенные в одну сумму, они
дают лимит, которого не выдавал никто. То же правило, что «сумма под именем
момента — не свод, а бред».

Запуск: python3 -m pytest tests/test_the_bridge_limit_is_one_contract_per_queue.py -q
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def _phased_bundle() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 7500.0
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], {"enabled": True, "phase_count": 4})


def test_the_consolidated_limit_is_a_sum_of_separate_contracts() -> None:
    """Свод равен сумме лимитов очередей — значит показывать его нельзя."""
    bundle = _phased_bundle()
    phases = bundle["phases"]
    assert len(phases) == 4, "проверка бессмысленна на одной очереди"
    each = [
        float(((phase["result"].get("report") or {}).get("financing") or {}).get("calculated_bridge") or 0.0)
        for phase in phases
    ]
    total = float(bundle["consolidated"]["report"]["financing"]["calculated_bridge"])
    assert abs(sum(each) - total) < 1_000, (
        "свод перестал быть суммой очередей — правило про подпись надо перечитать")
    # Покупка целиком лежит на очереди, которая её платит, а не размазана.
    assert max(each) > 7_000_000_000, "цена входа ушла не в свою очередь"
    assert sum(1 for value in each if value > 7_000_000_000) == 1


def test_the_page_shows_the_limit_per_queue() -> None:
    """На своде очередей — блок на очередь, без итоговой суммы."""
    body = _function("renderResult")
    assert "bridgeLimitPhases" in body, "лимит по-прежнему рисуется одной таблицей"
    assert "Расчётный лимит БРИДЖа — по очередям" in body
    assert "Лимит БРИДЖа ${name}" in body
    head = body[body.index("bridgeLimitPhases"):body.index("bridgeActual=")]
    assert "Итого БРИДЖ" in head, "у одиночного проекта итог остаётся на месте"
    # Свод по очередям не печатается: суммировать лимиты договоров нечем.
    phased = head[head.index("if(bridgeLimitPhases)"):head.index("}else{")]
    assert "Итого БРИДЖ" not in phased


def test_the_report_says_the_same() -> None:
    """Отчёт носят в банк — расходиться с экраном ему нельзя."""
    source = inspect.getsource(core._build_developaid_pdf)
    assert "_bridge_limit_phases" in source
    assert "Расчётный лимит БРИДЖа - по очередям" in source
    assert "Лимит БРИДЖа " in source
    # Одна функция на обе ветки: две реализации разошлись бы молча.
    assert source.count("def _bridge_uses(") == 1


def test_the_limit_is_computed_once_for_the_page() -> None:
    """Страница считает состав лимита одной функцией на свод и на очередь."""
    body = _function("renderResult")
    assert body.count("function bridgeUsesOf(") == 1
    assert body.count("bridgeUsesOf(") >= 3
