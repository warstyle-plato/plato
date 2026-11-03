"""Выключенная очерёдность не диктует книге сроки.

Владелец прислал книгу проекта 77:09:0004014:13: восемь строк паритета красные,
и все — от одной цифры. Срок строительства в проекте 36 месяцев, а книга считала
24. Двадцать четыре пришли из очерёдности, которую в этом проекте выключили:
конфигурация осталась в сохранёнке с прежних времён, а блок очередей книги читал
`phases[0]` не глядя на признак `enabled`. Движок в этом случае даже не заходит в
обёртку очередей (`calculate_phased` при выключенной сразу зовёт `calculate`), —
поэтому расходились не мелочи, а РВЭ, горизонт, кривая CAPEX, пик ПФ и LLCR.

Молчаливо: сроки очередей на экране не показываются, пока очерёдность выключена.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

BASE = {**core.DEFAULT_INPUTS, "purchase_price_mln": 700, "land_rights_cost_mln": 0,
        "social_compensation_mln": 0, "ird_months": 1, "construction_months": 36}

STALE = {
    "enabled": False,
    "phase_count": 3,
    "phase_gap_months": 12,
    "phases": [
        {"name": "О1", "start_offset_months": 0, "construction_months": 24},
        {"name": "О2", "start_offset_months": 12, "construction_months": 24},
        {"name": "О3", "start_offset_months": 24, "construction_months": 24},
    ],
}


def workbook(phasing, **overrides):
    content, _, _ = core.build_project_workbook(
        {**BASE, **overrides}, core.TEP_DEFAULT, [], phasing, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def test_a_disabled_phasing_does_not_dictate_the_term():
    """Тридцать шесть месяцев вводных, двадцать четыре — в выключенной очереди."""
    assert v4_inputs.inputs(workbook(STALE))["F88"].value == 36


def test_a_disabled_phasing_does_not_shift_the_start():
    """Сдвиг старта — оттуда же и так же молча."""
    book = workbook({**STALE, "phases": [{"name": "О1", "start_offset_months": 18,
                                          "construction_months": 24}]})
    assert v4_inputs.inputs(book)["D88"].value == v4_inputs.inputs(book)["B8"].value


def test_an_absent_phasing_takes_the_term_from_the_inputs():
    """Контроль: без всякой очерёдности книга и раньше брала срок из вводных."""
    assert v4_inputs.inputs(workbook({}))["F88"].value == 36


def test_an_enabled_phasing_still_dictates_the_term():
    """Правило не переворачивается: включённая очерёдность сроки задаёт."""
    book = workbook({**STALE, "enabled": True})
    assert [v4_inputs.inputs(book)[f"F{row}"].value for row in range(88, 91)] == [24, 24, 24]


def test_the_engine_agrees_when_phasing_is_off():
    """Книга и движок считают один и тот же горизонт: движок при выключенной
    очерёдности в обёртку очередей не заходит вовсе."""
    engine = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(BASE), tep=core.TEP_DEFAULT, rates=[], phasing=dict(STALE)))
    assert engine["mode"] == "single"
    assert v4_inputs.inputs(workbook(STALE))["F88"].value == BASE["construction_months"]
