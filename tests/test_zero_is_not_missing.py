"""Ноль во вводной — это ноль, а не «значение не задали».

Владелец задал срок ИРД равным нулю: разрешение на строительство уже есть,
стройка начинается сразу после покупки. Движок посчитал по нулю — РнС в день
старта, БРИДЖ не нужен вовсе. А в книгу уехали восемнадцать месяцев, потому
что запись стояла так:

    float(x.get("ird_months") or 18)

Ноль в Python ложен, и `or` подставил умолчание. Книга посчитала БРИДЖ на
полтора года: 1,28 млрд ₽ тела и 190 млн ₽ процентов, которых в проекте нет.
Прибыль и LLCR у книги вышли ниже движка — по этому признаку владелец и понял,
что моё первое объяснение (будто книга не учла расход) неверно: не учтённый
расход поднял бы её прибыль, а не опустил.

Тем же способом умолчаниями подменялись срок стройки, лаг продаж и пять
параметров кривой ключевой ставки. Ноль осмыслен у всех: «строим сразу»,
«ставка не меняется», «нулевая цель».

Правильный способ прочитать число в движке уже был — `n(x, key, default)`:
она подменяет только None и пустую строку.

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

openpyxl = pytest.importorskip("openpyxl")

BASE = {**core.DEFAULT_INPUTS, "apartment_price_th": 650,
        "commercial_price_th": 650, "parking_price_th": 5000}


def workbook(**overrides):
    content, _, _ = core.build_project_workbook(
        {**BASE, **overrides}, core.TEP_DEFAULT, [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


@pytest.mark.parametrize("months", [0, 1, 6, 18, 24])
def test_the_permit_period_reaches_the_workbook(months):
    """Ровно то число, что задал человек, — включая ноль."""
    assert workbook(ird_months=months)["Вводные"]["E88"].value == months


@pytest.mark.parametrize("key,cell,divisor", [
    ("rate_start_pct", "B33", 100.0),
    ("rate_normalization_months", "B35", 1.0),
    ("rate_target_base_pct", "E8", 100.0),
    ("rate_target_low_pct", "F8", 100.0),
    ("rate_target_high_pct", "G8", 100.0),
])
def test_a_zero_rate_setting_is_not_replaced_by_a_default(key, cell, divisor):
    """Нулевая цель по ставке — заданный сценарий, а не пропуск."""
    assert workbook(**{key: 0})["Вводные"][cell].value == 0


def test_a_zero_construction_term_is_not_replaced():
    assert workbook(construction_months=0)["Вводные"]["F88"].value == 0


def test_a_missing_value_still_falls_back():
    """Подмена умолчанием остаётся там, где значения действительно нет."""
    x = {**BASE}
    x.pop("ird_months")
    assert workbook(**{"ird_months": None})["Вводные"]["E88"].value == 18


def test_the_parity_holds_on_a_non_default_permit_period():
    """Ради чего правка: книга и движок сходятся не только на умолчаниях."""
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    book = workbook(ird_months=6)
    evaluator = Evaluator(book)
    checks = book["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"C{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", str(checks[f"A{row}"].value)


def test_the_engine_reads_numbers_the_same_way():
    """`n()` — тот самый правильный способ: ноль остаётся нулём."""
    assert core.n({"k": 0}, "k", 18.0) == 0.0
    assert core.n({"k": None}, "k", 18.0) == 18.0
    assert core.n({"k": ""}, "k", 18.0) == 18.0
    assert core.n({}, "k", 18.0) == 18.0
