"""Собственная книга DevelopAid считает то же, что и движок, — своими формулами.

Шаблон ПЛАТО сводили с расчётом восемью правками, и каждая проверялась чужим
пересчётом: посчитать книгу здесь нечем. Так жить нельзя — правка формулы
уезжала к аналитику непроверенной.

Эта книга собирается с нуля, и её формулы проверяются прямо в тесте: вводные и
помесячные драйверы приходят значениями, а весь финансовый контур — эскроу,
БРИДЖ, ПФ, покрытие, ставка, проценты, налог, LLCR — считается формулами и
сверяется с движком помесячно. Расхождение допускается только на уровне порядка
сложения чисел с плавающей точкой.

Заодно здесь закреплено, ради чего книга и собиралась: аналитик меняет вводную,
и книга пересчитывается сама, а не показывает выгруженное движком число.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
from xlsx_eval import Evaluator, FormulaError  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")

from openpyxl.utils import get_column_letter  # noqa: E402

# Книга считает в миллионах: 1e-5 — это копейки на миллиардах, столько даёт
# разный порядок сложения. Всё, что больше, — уже методика.
KOPECK = 1e-5


@pytest.fixture(scope="module")
def book():
    data, meta = core.build_plato_model_v2(
        dict(core.DEFAULT_INPUTS), dict(core.TEP_DEFAULT), [], project_name="Проверка",
    )
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    engine = core.calculate(core.CalcRequest(
        inputs=dict(core.DEFAULT_INPUTS), tep=dict(core.TEP_DEFAULT), rates=[],
    ))
    return workbook, Evaluator(workbook), engine, meta


def close(got: float, expected: float) -> bool:
    return abs(got - expected) <= max(KOPECK, abs(expected) * 1e-9)


# --- помесячный расчёт -----------------------------------------------------

# Строка книги -> та же величина в строке движка и её масштаб.
MONTHLY = [
    ("escrow", "escrow", 1e6),
    ("escrow_release", "escrow_release", 1e6),
    ("bridge_draw", "bridge_draw", 1e6),
    ("bridge_balance", "bridge_balance", 1e6),
    ("bridge_interest", "bridge_interest", 1e6),
    ("bridge_cap", "bridge_capitalization", 1e6),
    ("pf_draw", "pf_draw", 1e6),
    ("pf_repayment", "pf_repayment", 1e6),
    ("pf_balance", "pf_balance", 1e6),
    ("coverage", "coverage", 1.0),
    ("pf_rate", "pf_rate", 1.0),
    ("pf_interest", "pf_interest", 1e6),
    ("pf_cap", "pf_interest_capitalization", 1e6),
    ("limit_fee", "limit_fee", 1e6),
    ("interest_payment", "interest_payment", 1e6),
    ("profit_tax", "profit_tax", 1e6),
]


@pytest.mark.parametrize("row_key,engine_key,scale", MONTHLY)
def test_the_monthly_row_matches_the_engine(book, row_key, engine_key, scale):
    _, evaluator, engine, _ = book
    rows = engine["finance"]["rows"]
    line = core._M2[row_key]

    for index, item in enumerate(rows):
        column = get_column_letter(2 + index)
        got = evaluator.cell("Расчёт", f"{column}{line}")
        expected = float(item.get(engine_key) or 0.0) / scale
        assert close(got, expected), (
            f"{row_key} в {item['month']}: книга {got}, движок {expected}"
        )


def test_the_coverage_is_taken_before_the_escrow_is_released(book):
    """На РВЭ покрытие считается по накопленному эскроу, а не по нулю после раскрытия.

    Это тот самый порядок внутри месяца: сначала выборка ПФ, потом покрытие,
    ставка и проценты, и только затем раскрытие и погашение. Возьми покрытие
    после раскрытия — на РВЭ оно обнулится, ставка подскочит к базовой, и
    проценты уедут вверх на весь остаток проекта.
    """
    _, evaluator, engine, _ = book
    rve = engine["dates"]["rve"]
    index = [i for i, r in enumerate(engine["finance"]["rows"]) if r["month"] == rve]
    assert index, "месяц РВЭ не найден в расчёте"
    column = get_column_letter(2 + index[0])

    coverage = evaluator.cell("Расчёт", f"{column}{core._M2['coverage']}")
    escrow_after = evaluator.cell("Расчёт", f"{column}{core._M2['escrow']}")

    assert escrow_after == pytest.approx(0.0, abs=KOPECK), "эскроу на РВЭ не раскрыто"
    assert coverage > 0.5, f"покрытие на РВЭ схлопнулось до {coverage}"
    assert coverage == pytest.approx(engine["finance"]["rows"][index[0]]["coverage"])


# --- отчёт -----------------------------------------------------------------

def test_the_report_agrees_with_its_own_control_column(book):
    """Колонка D — разница между формулами книги и расчётом DevelopAid."""
    workbook, evaluator, _, _ = book
    sheet = workbook["ОТЧЁТ"]

    checked = 0
    for row in range(4, sheet.max_row + 1):
        expected = sheet.cell(row=row, column=3).value
        if expected is None:
            continue
        got = evaluator.cell("ОТЧЁТ", f"B{row}")
        assert close(got, float(expected)), (
            f"{sheet.cell(row=row, column=1).value}: книга {got}, движок {expected}"
        )
        assert close(evaluator.cell("ОТЧЁТ", f"D{row}"), 0.0)
        checked += 1

    assert checked == len(core._M2_REPORT_KEYS)


def test_the_llcr_is_the_engine_number(book):
    _, evaluator, engine, _ = book
    row = 4 + core._M2_REPORT_KEYS.index("llcr")

    assert evaluator.cell("ОТЧЁТ", f"B{row}") == pytest.approx(
        engine["summary"]["llcr"], rel=1e-9)


# --- живая книга -----------------------------------------------------------

def test_changing_a_spread_moves_the_report(book):
    """Ради этого книга и собиралась: вводная меняется — считает книга, не движок."""
    workbook, _, _, _ = book
    fresh = openpyxl.load_workbook(io.BytesIO(_saved(workbook)))
    before = Evaluator(fresh)
    row = 4 + core._M2_REPORT_KEYS.index("financing_cost")
    was = before.cell("ОТЧЁТ", f"B{row}")

    spread = _input_row(fresh, "Спред ПФ")
    fresh["Вводные"][f"B{spread}"] = fresh["Вводные"][f"B{spread}"].value + 0.02
    after = Evaluator(fresh).cell("ОТЧЁТ", f"B{row}")

    assert after > was + 100, f"плюс 2 п.п. к спреду ПФ не сдвинули проценты: {was} → {after}"


def test_the_tax_rate_reaches_the_llcr(book):
    workbook, _, _, _ = book
    fresh = openpyxl.load_workbook(io.BytesIO(_saved(workbook)))
    row = 4 + core._M2_REPORT_KEYS.index("llcr")
    was = Evaluator(fresh).cell("ОТЧЁТ", f"B{row}")

    tax = _input_row(fresh, "Налог на прибыль")
    fresh["Вводные"][f"B{tax}"] = 0.0

    assert Evaluator(fresh).cell("ОТЧЁТ", f"B{row}") > was


def test_the_financial_block_is_formulas_and_not_numbers(book):
    """Захардкоженное число вместо формулы — это возврат к мёртвой выгрузке."""
    workbook, _, engine, _ = book
    sheet = workbook["Расчёт"]
    months = len(engine["finance"]["rows"])
    drivers = {"month", "key_rate", "revenue", "capex", "operating",
               "debt_costs", "tax_margin", "tax_adjust"}

    for key, line in core._M2.items():
        if key in drivers:
            continue
        for index in range(months):
            value = sheet.cell(row=line, column=2 + index).value
            assert isinstance(value, str) and value.startswith("="), (
                f"{key} в колонке {get_column_letter(2 + index)} — не формула: {value!r}"
            )


def test_every_formula_is_understood(book):
    """Вычислитель узкий нарочно: непонятная формула должна ломать тест."""
    workbook, evaluator, _, _ = book

    for name in ("Вводные", "Расчёт", "ОТЧЁТ"):
        sheet = workbook[name]
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    try:
                        evaluator.cell(name, cell.coordinate)
                    except FormulaError as exc:
                        pytest.fail(f"{name}!{cell.coordinate}: {exc}\n{cell.value}")


# --- вспомогательное -------------------------------------------------------

def _saved(workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _input_row(workbook, label: str) -> int:
    sheet = workbook["Вводные"]
    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row=row, column=1).value == label:
            return row
    raise AssertionError(f"вводная «{label}» не найдена")
