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


@pytest.mark.parametrize("months", [1, 6, 18, 24])
def test_the_permit_period_reaches_the_workbook(months):
    """Ровно то число, что задал человек."""
    assert workbook(ird_months=months)["Вводные"]["E88"].value == months


def test_the_permit_period_has_a_floor_of_one_month():
    """Ноль модель не считает: на нулевом периоде у книги и движка расходятся
    сами базы для накладных и налога — до 3,0 млрд ₽ по CAPEX. Минимум в один
    месяц — решение владельца (13.08.2026)."""
    assert core.IRD_MONTHS_MIN == 1
    assert workbook(ird_months=0)["Вводные"]["E88"].value == 1


def test_the_field_says_the_minimum():
    """Ограничение объясняется у поля, до ввода. Заметки в расчёте нет —
    решение владельца (13.08.2026): предупреждать после того, как человек уже
    посчитал, поздно и шумно."""
    assert "минимум 1" in core.PAGE
    result = core.calculate(core.CalcRequest(
        inputs={**BASE, "ird_months": 0}, tep=core.TEP_DEFAULT, rates=[]))
    assert "ird_months" not in result["notes"]


@pytest.mark.parametrize("key", [
    "rate_start_pct", "rate_normalization_months",
    "rate_target_base_pct", "rate_target_low_pct", "rate_target_high_pct",
])
def test_a_zero_rate_setting_is_not_replaced_by_a_default(key):
    """Нулевая цель по ставке — заданный сценарий, а не пропуск.

    Ячейка ищется по ключу, а не по координате: три целевые ставки переехали
    из сценарных колонок `E8/F8/G8` в блок кривой (в строке 8 свободной ячейки
    под ключ нет вовсе, и строка 8 теперь их читает). Утверждение от переезда
    не изменилось — изменился адрес, и проверка обязана держаться за контракт
    «ключ стоит рядом со значением», а не за координату.
    """
    sheet = workbook(**{key: 0})["Вводные"]
    row = next((cell.row for line in sheet.iter_rows() for cell in line
                if isinstance(cell.value, str) and cell.value.strip() == key), None)
    assert row, f"{key}: ключа нет на листе «Вводные»"
    assert sheet[f"B{row}"].value == 0


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
