"""Платон предлагает то, что законно, а не то, что красиво считается.

На вопрос «при каких параметрах проект станет рентабельным» он выдал сценарий
«социалка = 0, LLCR 1,2422». Арифметика верна, смысл — нет: 788 млн ₽
социальной нагрузки вытекают из градостроительной документации, и в Москве их
не обнуляют — строить не дадут.

Причина была не в понимании, а в наборе инструментов. Среди переменных, которыми
агент мог двигать, стояла `social_compensation_mln`, а льготы по плате за смену
ВРИ и рассрочки не было вовсе. Он предложил единственный доступный рычаг такого
масштаба.

Теперь рычаги настоящие: льгота (её получают через места приложения труда) и
рассрочка платежа. А сценарии, трогающие обязательства, возвращают оговорку из
самого инструмента — правило «упоминай предупреждения инструмента» агент
соблюдает, а помнить инструкцию под конец длинного разбора не обязан.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _request(**inputs):
    return core.AgentChatRequest(
        message="проверка", inputs={**core.DEFAULT_INPUTS, **inputs},
        tep={key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        rates=[], phasing={}, history=[], selected_view="all")


# --- законные рычаги доступны агенту -----------------------------------------

def test_the_relief_and_instalment_are_in_the_toolbox():
    """Пока их не было, единственным рычагом такого масштаба оставалась
    социальная компенсация — отсюда и совет её обнулить."""
    for variable in ("vri_relief_pct", "vri_relief_mln",
                     "vri_installment_years", "vri_initial_pct"):
        assert variable in core._PATCH_VARIABLES, variable


def test_the_relief_share_switches_its_mode_on():
    """Льгота в процентах без режима «доля от суммы» осталась бы нулём."""
    inputs = dict(core.DEFAULT_INPUTS, vri_relief_mode="none")
    core._apply_patch_value(inputs, "vri_relief_pct", 30.0)
    assert inputs["vri_relief_pct"] == 30.0
    assert inputs["vri_relief_mode"] == "percent"


def test_the_relief_amount_switches_its_own_mode():
    inputs = dict(core.DEFAULT_INPUTS, vri_relief_mode="none")
    core._apply_patch_value(inputs, "vri_relief_mln", 400.0)
    assert inputs["vri_relief_mode"] == "amount"


def test_the_instalment_switches_the_payment_mode():
    """Срок рассрочки без режима «рассрочка» остался бы единовременным платежом."""
    inputs = dict(core.DEFAULT_INPUTS, vri_payment_mode="lump")
    core._apply_patch_value(inputs, "vri_installment_years", 6.0)
    assert inputs["vri_payment_mode"] == "installment"


def test_a_zero_relief_does_not_switch_anything():
    """Ноль — это «льготы нет», а не «включи режим льготы»."""
    inputs = dict(core.DEFAULT_INPUTS, vri_relief_mode="none")
    core._apply_patch_value(inputs, "vri_relief_pct", 0.0)
    assert inputs["vri_relief_mode"] == "none"


def test_the_relief_actually_reduces_the_payment():
    """Рычаг обязан работать в движке, а не только в списке переменных."""
    gross = 1000.0
    relief, net = core.vri_relief(
        {"vri_relief_mode": "percent", "vri_relief_pct": 30.0}, gross)
    assert relief == pytest.approx(300.0)
    assert net == pytest.approx(700.0)


# --- обязательства не выдаются за способ оздоровления ------------------------

def test_zeroing_the_social_load_comes_with_a_caveat():
    """Сценарий считается, но называется пределом, а не решением."""
    notes = core._regulated_notes(["social_compensation_mln"])
    assert notes and "обнулять её нельзя" in notes[0]
    assert "форма исполнения" in notes[0]


def test_the_vri_payment_caveat_points_at_the_lawful_levers():
    notes = core._regulated_notes(["land_rights_cost_mln"])
    assert notes and "места приложения труда" in notes[0]
    assert "рассрочк" in notes[0]


def test_an_ordinary_variable_carries_no_caveat():
    """Оговорка на всё подряд обесценила бы оговорку."""
    assert core._regulated_notes(["main_above_th_per_sqm", "apartment_price_th"]) == []


def test_the_simulation_returns_the_caveat_to_the_agent():
    """Правило «упоминай предупреждения инструмента» агент соблюдает, а помнить
    инструкцию под конец длинного разбора не обязан — поэтому оговорку выдаёт
    сам инструмент."""
    bundle = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()}, [], {})
    result = core._tool_simulate_change(
        _request(), bundle,
        [{"variable": "social_compensation_mln", "value": 0.0}], "consolidated")
    assert result["available"] is True
    assert result["regulatory_notes"], "сценарий с обязательством обязан нести оговорку"


def test_the_goal_seek_carries_it_too():
    import inspect
    source = inspect.getsource(core._tool_goal_seek)
    assert '"regulatory_notes": _regulated_notes([variable])' in source


# --- знание о московской специфике -------------------------------------------

def test_the_knowledge_base_knows_the_lawful_levers():
    rules = {rule["id"]: rule["rule"] for rule in core._DevelopAid_METHODOLOGY}
    assert "SOCIAL_IS_AN_OBLIGATION" in rules
    assert "строить не дадут" in rules["SOCIAL_IS_AN_OBLIGATION"]
    assert "VRI_RELIEF" in rules
    assert "места приложения труда" in rules["VRI_RELIEF"]


def test_the_knowledge_base_knows_the_new_parking_rules():
    """2118-ПП: обеспеченность считается от площади квартир, и это прямо
    поднимает подземную часть и себестоимость."""
    rules = {rule["id"]: rule["rule"] for rule in core._DevelopAid_METHODOLOGY}
    assert "PARKING_2118PP" in rules
    text = rules["PARKING_2118PP"]
    for part in ("2118-ПП", "0,8", "1,2", "1,6", "05.08.2026", "ПЗЗ"):
        assert part in text, part
    # Источник — краткое изложение: утверждать норматив как проверенный факт
    # по документу, которого агент не видел, нельзя.
    assert "сверить с текстом" in text
    assert "PARKING_2118PP_ECONOMY" in rules


def test_the_instructions_name_the_lawful_levers():
    text = core._AGENT_INSTRUCTIONS
    assert "обнулить социалку нельзя" in text
    assert "места приложения труда" in text
    assert "vri_relief_pct" in text and "vri_installment_years" in text
