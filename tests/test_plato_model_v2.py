"""Финансовая модель DevelopAid считает то же, что и движок, — своими формулами.

Шаблон ПЛАТО сводили с расчётом восемью правками, и каждая проверялась чужим
пересчётом: посчитать книгу здесь нечем. Так жить нельзя — правка формулы
уезжала к аналитику непроверенной.

Эта книга собирается с нуля: тринадцать листов — вводные, ТЭП, сроки, продажи,
себестоимость, ставки, эскроу, кредитование, налоги, CF, LLCR, ВРИ и отчёт.
Значениями приходят только драйверы сценария; весь финансовый контур —
формулы, и здесь они считаются прямо в тесте и сверяются с движком помесячно.
Расхождение допускается только на уровне порядка сложения чисел с плавающей
точкой.

Заодно закреплено, ради чего книга и собиралась: аналитик меняет вводную, и
книга пересчитывается сама, а не показывает выгруженное движком число.

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


def column(index: int) -> str:
    return get_column_letter(2 + index)


# --- состав книги ----------------------------------------------------------

def test_the_workbook_has_the_sheets_a_model_is_made_of(book):
    """Три листа — это выгрузка, а не финмодель."""
    workbook, _, _, _ = book

    assert workbook.sheetnames == [
        "ОТЧЁТ", "Вводные", "ТЭП", "СРОКИ", "ПРОДАЖИ", "СЕБЕСТОИМОСТЬ", "СТАВКИ",
        "ЭСКРОУ", "КРЕДИТОВАНИЕ", "НАЛОГИ", "CF", "LLCR", "ВРИ",
    ]


# --- помесячный расчёт -----------------------------------------------------

# Лист и строка книги -> та же величина в строке движка и её масштаб.
MONTHLY = [
    ("ЭСКРОУ", "escrow", "balance", "escrow", 1e6),
    ("ЭСКРОУ", "escrow", "release", "escrow_release", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "bridge_draw", "bridge_draw", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "bridge_balance", "bridge_balance", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "bridge_interest", "bridge_interest", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "bridge_cap", "bridge_capitalization", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "bridge_refinance", "bridge_repayment", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "pf_draw", "pf_draw", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "pf_repayment", "pf_repayment", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "pf_balance", "pf_balance", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "coverage", "coverage", 1.0),
    ("КРЕДИТОВАНИЕ", "credit", "pf_rate", "pf_rate", 1.0),
    ("КРЕДИТОВАНИЕ", "credit", "pf_interest", "pf_interest", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "pf_cap", "pf_interest_capitalization", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "limit_fee", "limit_fee", 1e6),
    ("КРЕДИТОВАНИЕ", "credit", "interest_payment", "interest_payment", 1e6),
    ("НАЛОГИ", "tax", "tax", "profit_tax", 1e6),
]


@pytest.mark.parametrize("sheet,grid,row_key,engine_key,scale", MONTHLY)
def test_the_monthly_row_matches_the_engine(book, sheet, grid, row_key, engine_key, scale):
    _, evaluator, engine, meta = book
    line = meta["layout"][grid][row_key]

    for index, item in enumerate(engine["finance"]["rows"]):
        got = evaluator.cell(sheet, f"{column(index)}{line}")
        expected = float(item.get(engine_key) or 0.0) / scale
        assert close(got, expected), (
            f"{sheet}·{row_key} в {item['month']}: книга {got}, движок {expected}"
        )


@pytest.mark.parametrize("row_key,engine_key", [("project", "project"), ("equity", "equity")])
def test_the_cash_flow_matches_the_engine(book, row_key, engine_key):
    _, evaluator, engine, meta = book
    line = meta["layout"]["cf"][row_key]
    series = engine["cashflow"][engine_key]

    for index, month in enumerate(engine["cashflow"]["months"]):
        got = evaluator.cell("CF", f"{column(index)}{line}")
        assert close(got, float(series[index]) / 1e6), f"CF·{row_key} в {month}"


def test_the_coverage_is_taken_before_the_escrow_is_released(book):
    """На РВЭ покрытие считается по накопленному эскроу, а не по нулю после раскрытия.

    Это тот самый порядок внутри месяца: сначала выборка ПФ, потом покрытие,
    ставка и проценты, и только затем раскрытие и погашение. Возьми покрытие
    после раскрытия — на РВЭ оно обнулится, ставка подскочит к базовой, и
    проценты уедут вверх на весь остаток проекта.
    """
    _, evaluator, engine, meta = book
    rve = engine["dates"]["rve"]
    index = [i for i, r in enumerate(engine["finance"]["rows"]) if r["month"] == rve]
    assert index, "месяц РВЭ не найден в расчёте"
    letter = column(index[0])

    coverage = evaluator.cell("КРЕДИТОВАНИЕ", f"{letter}{meta['layout']['credit']['coverage']}")
    escrow_after = evaluator.cell("ЭСКРОУ", f"{letter}{meta['layout']['escrow']['balance']}")

    assert escrow_after == pytest.approx(0.0, abs=KOPECK), "эскроу на РВЭ не раскрыто"
    assert coverage > 0.5, f"покрытие на РВЭ схлопнулось до {coverage}"
    assert coverage == pytest.approx(engine["finance"]["rows"][index[0]]["coverage"])


def test_the_escrow_holds_the_money_until_the_permit_to_occupy(book):
    """До РВЭ выручка на эскроу и в поток на собственный капитал не попадает."""
    _, evaluator, engine, meta = book
    rve = engine["dates"]["rve"]
    cash_in = meta["layout"]["cf"]["cash_in"]

    for index, item in enumerate(engine["finance"]["rows"]):
        if item["month"] >= rve:
            continue
        assert evaluator.cell("CF", f"{column(index)}{cash_in}") == pytest.approx(0.0), (
            f"в {item['month']} деньги дошли до акционера раньше раскрытия эскроу"
        )


# --- отчёт -----------------------------------------------------------------

def test_the_report_agrees_with_its_own_control_column(book):
    """Колонка D — разница между формулами книги и расчётом DevelopAid."""
    workbook, evaluator, _, _ = book
    sheet = workbook["ОТЧЁТ"]

    checked = 0
    for row in range(4, 4 + len(core._M2_REPORT_KEYS)):
        expected = sheet.cell(row=row, column=3).value
        got = evaluator.cell("ОТЧЁТ", f"B{row}")
        assert close(got, float(expected)), (
            f"{sheet.cell(row=row, column=1).value}: книга {got}, движок {expected}"
        )
        assert close(evaluator.cell("ОТЧЁТ", f"D{row}"), 0.0)
        checked += 1

    assert checked == len(core._M2_REPORT_KEYS)


def test_the_llcr_sheet_shows_its_own_arithmetic(book):
    """LLCR — не одно число в отчёте, а числитель, знаменатель и их состав."""
    _, evaluator, engine, _ = book

    numerator = evaluator.cell("LLCR", "B9")
    denominator = evaluator.cell("LLCR", "B12")
    llcr = evaluator.cell("LLCR", "B13")

    assert close(numerator, engine["finance"]["llcr_numerator"] / 1e6)
    assert close(denominator, engine["finance"]["llcr_denominator"] / 1e6)
    assert llcr == pytest.approx(engine["summary"]["llcr"], rel=1e-9)
    assert evaluator.cell("ОТЧЁТ", f"B{4 + core._M2_REPORT_KEYS.index('llcr')}") == pytest.approx(llcr)


# --- живая книга -----------------------------------------------------------

def test_changing_a_spread_moves_the_report(book):
    """Ради этого книга и собиралась: вводная меняется — считает книга, не движок."""
    workbook, _, _, meta = book
    fresh = _reopen(workbook)
    row = 4 + core._M2_REPORT_KEYS.index("financing_cost")
    was = Evaluator(fresh).cell("ОТЧЁТ", f"B{row}")

    line = meta["layout"]["inputs"]["pf_spread_pp"]
    fresh["Вводные"][f"B{line}"] = fresh["Вводные"][f"B{line}"].value + 0.02

    after = Evaluator(fresh).cell("ОТЧЁТ", f"B{row}")
    assert after > was + 100, f"плюс 2 п.п. к спреду ПФ не сдвинули проценты: {was} → {after}"


def test_the_rate_sheet_feeds_the_credit_sheet(book):
    """Спред живёт на «Вводных», ставка — на «СТАВКАХ», кредит их читает."""
    workbook, _, _, meta = book
    fresh = _reopen(workbook)
    rate_row = meta["layout"]["credit"]["pf_base_rate"]
    was = Evaluator(fresh).cell("КРЕДИТОВАНИЕ", f"C{rate_row}")

    line = meta["layout"]["inputs"]["pf_spread_pp"]
    fresh["Вводные"][f"B{line}"] = fresh["Вводные"][f"B{line}"].value + 0.01

    assert Evaluator(fresh).cell("КРЕДИТОВАНИЕ", f"C{rate_row}") == pytest.approx(was + 0.01)


def test_the_tax_rate_reaches_the_llcr(book):
    workbook, _, _, meta = book
    fresh = _reopen(workbook)
    row = 4 + core._M2_REPORT_KEYS.index("llcr")
    was = Evaluator(fresh).cell("ОТЧЁТ", f"B{row}")

    fresh["Вводные"][f"B{meta['layout']['inputs']['profit_tax_pct']}"] = 0.0

    assert Evaluator(fresh).cell("ОТЧЁТ", f"B{row}") > was


# Драйверы — это сценарий: объёмы, выручка по продуктам, статьи затрат, прогноз
# ставки, налоговая маржа. Всё прочее на помесячных листах обязано быть формулой.
DRIVER_ROWS = {
    "ПРОДАЖИ": ("quantity_", "revenue_"),
    "СЕБЕСТОИМОСТЬ": ("cost_", "operating", "debt"),
    "СТАВКИ": ("key_rate",),
    "ЭСКРОУ": (),
    "КРЕДИТОВАНИЕ": (),
    "НАЛОГИ": ("margin", "adjust"),
    "CF": (),
}
GRID_OF = {"ПРОДАЖИ": "sales", "СЕБЕСТОИМОСТЬ": "costs", "СТАВКИ": "rates",
           "ЭСКРОУ": "escrow", "КРЕДИТОВАНИЕ": "credit", "НАЛОГИ": "tax", "CF": "cf"}


@pytest.mark.parametrize("sheet", list(DRIVER_ROWS))
def test_the_financial_block_is_formulas_and_not_numbers(book, sheet):
    """Захардкоженное число вместо формулы — это возврат к мёртвой выгрузке."""
    workbook, _, engine, meta = book
    page = workbook[sheet]
    months = len(engine["finance"]["rows"])
    drivers = DRIVER_ROWS[sheet]

    checked = 0
    for key, line in meta["layout"][GRID_OF[sheet]].items():
        if any(key == name or key.startswith(name) for name in drivers):
            continue
        for index in range(months):
            value = page.cell(row=line, column=2 + index).value
            assert isinstance(value, str) and value.startswith("="), (
                f"{sheet}·{key} в колонке {column(index)} — не формула: {value!r}"
            )
        checked += 1

    assert checked, f"на листе {sheet} не осталось ни одной расчётной строки"


def test_every_formula_is_understood(book):
    """Вычислитель узкий нарочно: непонятная формула должна ломать тест."""
    workbook, evaluator, _, _ = book

    total = 0
    for name in workbook.sheetnames:
        sheet = workbook[name]
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    total += 1
                    try:
                        evaluator.cell(name, cell.coordinate)
                    except FormulaError as exc:
                        pytest.fail(f"{name}!{cell.coordinate}: {exc}\n{cell.value}")

    assert total > 1000, f"формул подозрительно мало: {total}"


# --- вспомогательное -------------------------------------------------------

def _reopen(workbook):
    """Свежая копия: вычислитель кэширует значения, править надо чистую книгу."""
    buffer = io.BytesIO()
    workbook.save(buffer)
    return openpyxl.load_workbook(io.BytesIO(buffer.getvalue()))
