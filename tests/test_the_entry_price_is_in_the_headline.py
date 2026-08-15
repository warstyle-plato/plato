"""Цена приобретения — в шапке отчёта, а не только в таблице ниже.

Владелец смотрел на «Экономику и ключевые показатели проекта» и не нашёл там
главного числа сделки: плитки показывали выручку, EBITDA, прибыль, LLCR и
БРИДЖ, а за сколько куплено — нет. При этом PDF печатал цену приобретения
первой строкой ключевой экономики, и таблица «Параметры проекта» ниже на той
же странице тоже её показывала. Экран и отчёт расходились по составу.

Число берётся из результата расчёта (`report.expense_structure`), тем же
способом, что и строка ниже, и что `_pdf_entry_cost_rows` в отчёте. Из формы
брать нельзя: она не знает ни о льготе по ВРИ, ни о доле очереди — в разрезе
одной очереди показала бы цену покупки всего проекта.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def render_source() -> str:
    match = re.search(r"function renderResult\(\)\{.*?\n\}", core.PAGE, re.S)
    assert match, "renderResult не найдена"
    return match.group(0)


def kpi_block() -> str:
    body = render_source()
    start = body.index("const reportKpis=[")
    return body[start:body.index("];", start)]


# --- плитка есть и стоит на своём месте ----------------------------------------

def test_the_entry_price_has_a_tile():
    assert "'Цена приобретения'" in kpi_block()


def test_it_stands_before_the_llcr():
    """Вход и то, как обслуживается взятый под него долг, читаются вместе."""
    block = kpi_block()
    assert block.index("Цена приобретения") < block.index("LLCR (расчётный)")


def test_it_stands_after_the_result_figures():
    """Выручка, EBITDA и прибыль — итог; цена входа не вклинивается между ними."""
    block = kpi_block()
    assert block.index("Маржинальность") < block.index("Цена приобретения")


# --- долг в шапке одним показателем --------------------------------------------

def test_the_headline_shows_one_bridge_not_two():
    """Решение владельца (14.08.2026): два БРИДЖа рядом читались как
    расхождение, а не как лимит банка и фактическая потребность. Остался один
    — фактический пик, он отвечает на вопрос «сколько денег нужно»."""
    block = kpi_block()
    assert "Пиковый БРИДЖ" in block
    for gone in ("Расчётный БРИДЖ", "Пиковая (непокрытая эскроу) задолженность ПФ"):
        assert gone not in block, f"«{gone}» вернулась в шапку"


def test_the_entry_is_shown_with_what_pays_for_it():
    """Цена входа без источников оплаты — половина картины: на Вест Гарден
    3,20 млрд из 4,35 внесены своими деньгами."""
    block = kpi_block()
    assert "Собственные средства до ПФ" in block
    assert block.index("Цена приобретения") < block.index("Собственные средства до ПФ")
    assert block.index("Собственные средства до ПФ") < block.index("Пиковый БРИДЖ")


def test_the_headline_stays_short():
    """Одиннадцатая плитка — повод спросить, показатель ли это общей оценки.

    Десятой стали «Расходы всего» — решение владельца (15.08.2026): выручка в
    шапке была, второй половины уравнения не было, и EBITDA появлялась из
    ниоткуда. На десяти шапка встаёт двумя ровными рядами по пять — следующая
    плитка начнёт третий ряд, и это тот момент, когда стоит спросить снова.
    """
    assert kpi_block().count("money(") + kpi_block().count("pct(") \
        + kpi_block().count("mult(") == 10


def test_the_own_funds_come_from_the_calculation():
    """Форма знает внесённую сумму, но не знает израсходованную: своих денег
    может хватить не на всё, и в шапке должно стоять потраченное."""
    block = kpi_block()
    assert "r.report.financing.own_funds" in block
    assert "pre_pf_own_funds_mln" not in block


def test_nothing_was_lost_only_moved():
    """Убрать из шапки — не то же, что убрать со страницы."""
    body = render_source()
    finance = body[body.index("reportFinanceTable.innerHTML="):]
    finance = finance[:finance.index("const sb=")]
    for moved in ("Расчётный БРИДЖ", "Фактический / пиковый БРИДЖ",
                  "Пиковая (непокрытая эскроу) задолженность ПФ"):
        assert moved in finance, f"«{moved}» пропала и из таблицы финансирования"


def test_the_report_still_prints_the_debt_figures():
    """PDF — отдельная поверхность, и состав шапки страницы её не меняет."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    for kept in ("Расчётный БРИДЖ", "Фактический пик БРИДЖ",
                 "Пиковая (непокрытая эскроу) задолженность ПФ"):
        assert f'["{kept}"' in source, kept


# --- число одно на все поверхности ---------------------------------------------

def test_the_tile_reads_the_calculation_not_the_form():
    """`inputs.purchase_price_mln` — это форма: ни льготы, ни доли очереди."""
    block = kpi_block()
    assert "expenseGroup('Цена приобретения')" in block
    assert "purchase_price_mln" not in block


def test_the_helper_is_declared_before_the_tiles():
    """`const` до объявления — ReferenceError, и отчёт не отрисуется вовсе."""
    body = render_source()
    assert body.index("const expenseGroup=") < body.index("const reportKpis=")


def test_the_tile_and_the_row_below_share_the_source():
    """Два похожих числа на одном экране хуже, чем одно."""
    body = render_source()
    assert body.count("expenseGroup('Цена приобретения')") == 2


def test_the_report_names_the_same_group():
    """PDF ищет ту же группу структуры расходов — по этой строке они и сходятся."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    entry = source[source.index("def _pdf_entry_cost_rows"):]
    assert '"Цена приобретения"' in entry[:1200]


def test_the_calculation_really_names_that_group():
    """Метка группы — договор между движком и тремя поверхностями."""
    result = core.calculate(core.CalcRequest(
        inputs={**core.DEFAULT_INPUTS, "purchase_price_mln": 1234.0},
        tep=core.TEP_DEFAULT, rates=[]))
    groups = {str(item["label"]): float(item["value"])
              for item in result["report"]["expense_structure"]}
    assert "Цена приобретения" in groups
    assert groups["Цена приобретения"] == pytest.approx(1234.0 * 1_000_000)
