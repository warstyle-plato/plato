"""Множители цены и затрат очереди (S/T 88–91) — формула от даты старта.

Ревизия книги v4 (docs/excel_book_audit_2026-10-15.md, вопрос 4): множители
стояли числами движка, и правка даты старта очереди прямо в книге их не
двигала — поздняя очередь продавала и строила по ценам прежнего сдвига.

Закреплено:
- на числах движка множители книги равны множителям движка
  (`sales_price_inflation_factor`, `cost_inflation_factor`), в том числе
  у первой очереди со своим сдвигом: сдвиг считается от начала горизонта B8,
  как offset_months движка, а не от старта первой очереди;
- правка даты старта очереди сдвигает её множители, ставка правится одной
  ячейкой на проект;
- инфляция не прибавляется второй раз: AE/AF шаблона пусты, и его
  коэффициенты AG/AH, которые читатели умножают на S/T, равны единице.

Запуск: python3 -m pytest tests/test_the_queue_multipliers_follow_the_start_date.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")
from xlsx_eval import Evaluator  # noqa: E402

PARAMS = "Параметры модели"
QUEUE_ROWS = (88, 89, 90)

# Ставки цены и затрат разные, а у первой очереди свой сдвиг: на одинаковых
# ставках перепутанные S и T и на нулевом сдвиге О1 «сдвиг от первой очереди»
# прошли бы незамеченными.
PHASING = {
    "enabled": True, "phase_count": 3,
    "phases": [{"start_offset_months": 3, "construction_months": 24},
               {"start_offset_months": 15, "construction_months": 24},
               {"start_offset_months": 33, "construction_months": 24}],
    "products": {key: [40, 35, 25] for key in ("apartments", "ground_commercial",
                                               "underground_parking", "storage")},
    "shared_allocation": {}, "cost_inflation_pct": 6, "sales_price_inflation_pct": 9,
}


@pytest.fixture(scope="module")
def built():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(inputs, tep, [], copy.deepcopy(PHASING))
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], copy.deepcopy(PHASING), project_name="Множители",
        finance_hints=core._v4_finance_hints(bundle))
    return bundle, content, meta


def _book(content: bytes):
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def _value(workbook, coord: str) -> float:
    return float(Evaluator(workbook).cell(PARAMS, coord))


def test_the_multipliers_are_formulas_of_the_start_date(built) -> None:
    _, content, meta = built
    assert not [m for m in meta["missing"] if "инфляц" in m or "множител" in m], meta["missing"]
    sheet = v4_inputs.inputs(_book(content))
    for row in QUEUE_ROWS:
        for column in ("S", "T"):
            formula = str(sheet[f"{column}{row}"].value)
            assert formula.startswith("="), f"{column}{row} числом: {formula}"
            assert f"D{row}" in formula and "$B$8" in formula, formula


def test_on_engine_numbers_the_book_carries_the_engine_factors(built) -> None:
    bundle, content, _ = built
    phases = bundle["phases"]
    assert len(phases) == 3
    workbook = _book(content)
    for row, phase in zip(QUEUE_ROWS, phases):
        assert _value(workbook, f"S{row}") == pytest.approx(
            phase["sales_price_inflation_factor"], rel=1e-12), row
        assert _value(workbook, f"T{row}") == pytest.approx(
            phase["cost_inflation_factor"], rel=1e-12), row
    # Контрпример к «сдвигу от первой очереди»: у О1 свой сдвиг в три месяца.
    assert phases[0]["sales_price_inflation_factor"] > 1.0


def _entry_target(workbook, coord: str) -> tuple[str, str]:
    """Куда на самом деле вводят: ячейка параметров читает лист ввода."""
    raw = str(workbook[PARAMS][coord].value)
    found = re.fullmatch(r"='([^']+)'!\$?([A-Z]+)\$?(\d+)", raw)
    assert found, f"{coord} не читалка листа ввода: {raw}"
    return found.group(1), found.group(2) + found.group(3)


def test_moving_the_start_moves_the_multipliers(built) -> None:
    _, content, _ = built
    workbook = _book(content)
    before_s, before_t = _value(workbook, "S90"), _value(workbook, "T90")
    sheet, coord = _entry_target(workbook, "D90")
    # Старт третьей очереди на год позже: 33 → 45 месяцев от B8.
    workbook[sheet][coord].value = date(2027 + 3, 10, 1)
    start = Evaluator(workbook).cell(PARAMS, "B8")
    assert (start.year, start.month) == (2027, 1), start
    assert _value(workbook, "S90") == pytest.approx(1.09 ** (45 / 12), rel=1e-12)
    assert _value(workbook, "T90") == pytest.approx(1.06 ** (45 / 12), rel=1e-12)
    assert _value(workbook, "S90") > before_s and _value(workbook, "T90") > before_t
    # Соседняя очередь не сдвинулась.
    assert _value(workbook, "S89") == pytest.approx(1.09 ** (15 / 12), rel=1e-12)


def test_the_annual_rate_is_one_cell_per_project(built) -> None:
    _, content, _ = built
    workbook = _book(content)
    params = workbook[PARAMS]
    assert params["AW88"].value == pytest.approx(0.09)
    assert params["AX88"].value == pytest.approx(0.06)
    params["AW88"].value = 0.0
    params["AX88"].value = 0.0
    for row in QUEUE_ROWS:
        assert _value(workbook, f"S{row}") == pytest.approx(1.0)
        assert _value(workbook, f"T{row}") == pytest.approx(1.0)


def test_the_rate_stays_off_the_entry_sheet(built) -> None:
    """Сторож «лист ввода не менялся» суммирует числа «Вводных»: ставка между
    очередями туда не переезжает, а S/T перестали быть числами ввода."""
    _, content, _ = built
    workbook = _book(content)
    params = workbook[PARAMS]
    for coord in ("AW88", "AX88"):
        assert not str(params[coord].value).startswith("="), coord
    entry = workbook[v4_inputs.ENTRY]
    labels = {str(cell.value) for line in entry.iter_rows() for cell in line
              if isinstance(cell.value, str)}
    assert not {"Множ. цены", "Множ. затрат"} & labels


def test_inflation_is_not_added_twice(built) -> None:
    """Читатели берут цену как S×AG и затраты как T×AH: AG/AH шаблона ведут
    инфляцию AE/AF от даты базы цен. Пока множители S/T несут индексацию
    очереди, AE/AF пусты и AG/AH — единица, иначе вторая очередь
    проиндексировалась бы дважды."""
    bundle, content, _ = built
    workbook = _book(content)
    evaluator = Evaluator(workbook)
    for row, phase in zip(QUEUE_ROWS, bundle["phases"]):
        for column in ("AE", "AF"):
            assert float(evaluator.cell(PARAMS, f"{column}{row}")) == 0.0, (column, row)
        for column in ("AG", "AH"):
            assert float(evaluator.cell(PARAMS, f"{column}{row}")) == pytest.approx(1.0), (column, row)
        price = float(evaluator.cell(PARAMS, f"S{row}")) * float(evaluator.cell(PARAMS, f"AG{row}"))
        cost = float(evaluator.cell(PARAMS, f"T{row}")) * float(evaluator.cell(PARAMS, f"AH{row}"))
        assert price == pytest.approx(phase["sales_price_inflation_factor"], rel=1e-12)
        assert cost == pytest.approx(phase["cost_inflation_factor"], rel=1e-12)
