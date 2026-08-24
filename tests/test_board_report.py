"""Отчёт правлению: что продано, что оплачено, что построено.

Такие сводки в книге собирают руками на формулах — вафли по площадям, бублик
«продано / оплачено», полосы освоения бюджета. Числа там уже посчитаны, а наш
отчёт о рынке их не знал и показывал только продажи по ДДУ.

Главное здесь — что «продано» и «оплачено» разные величины. На книге владельца
законтрактовано 1 728,6 млн ₽, а на эскроу пришло 943,5: 13% против 7%,
дебиторка 785 млн. Банк смотрит на второе.

Запуск: python3 -m pytest tests/test_board_report.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import board  # noqa: E402
from market_search.plan import PlanNotFound  # noqa: E402


def _sales_book() -> bytes:
    """Лист «график продажи_1»: два одинаковых по подписям блока подряд.

    Сверху физические объёмы, снизу деньги, и продукты в них называются
    одинаково. Без границы между блоками метры молча становятся миллионами.
    """
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "график продажи_1"
    wide = [None] * 18
    sheet.append(wide + ["Все объекты (физ. объёмы)"])
    sheet.append(wide + [None, "Продано", "Оплачено", "ВСЕГО"])
    sheet.append(wide + ["КВ", 2526.9, 1343.4, 13428.9])
    sheet.append(wide + ["ПСН", 0, 0, 281.2])
    sheet.append(wide + ["М/М", 11, 11, 73])
    sheet.append(wide + ["КЛД", 1, 0, 15])
    sheet.append([None])
    sheet.append(wide + ["Мониторинг денежных средств"])
    sheet.append([None, None, "Квартиры, штуки", None, None, None,
                  "Продано, шт", "Оплачено, шт", None, "Продано, %",
                  "Продано, кв.м", "Продано, т.руб", "Цена", "Оплачено, руб",
                  None, None, None, None, None, "Продано", "Оплачено", "ВСЕГО"])
    sheet.append([None, None, "28,3 - 40", "a", None, None, 21, 13.0, 51, 0.4118,
                  730.9, 449113.5, 614.5, 278349.6, None, None, None, None,
                  "КВ", 1670.8, 888.3, 12332.9])
    sheet.append([None, None, "40 - 55", "b", None, None, 7, 4.2, 60, 0.1167,
                  333.1, 214685.3, 644.5, 129793.9, None, None, None, None,
                  "ПСН", 0, 0, 216.5])
    sheet.append([None] * 18 + ["М/М", 55.2, 55.2, 544.8])
    sheet.append([None] * 18 + ["КЛД", 2.6, 0, 40.4])
    sheet.append([None] * 18 + ["ВСЕГО", 1728.6, 943.5, 13134.7])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _status_book() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "гр.статус"
    import datetime
    sheet.append([None, "Дата", None, None, datetime.date(2026, 5, 1)])
    sheet.append([None])
    sheet.append([None, "Бюджет проекта", "2023-10-01", "2028-07-01", 201.7, 11717.5])
    sheet.append([None, "СМР ЖК 1 оч", "2025-06-01", "2028-04-01", 19.2, 4359.3])
    sheet.append([None, "Вход в проект", "2023-10-01", "2024-02-01", 200.9, 950.0])
    sheet.append([None])
    sheet.append(["84", "Бюджет проекта", "(11 717,5 млн.р)", "↙35% (4 119,0 из)", 4119.0])
    sheet.append(["84", "СМР ЖК 1 оч", "(4 359,3 млн.р)", "↙23% (1 023,9 из)", 1023.9])
    sheet.append(["84", "Вход в проект", "(950,0 млн.р)", "#N/A", "#N/A"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# --- продажи ----------------------------------------------------------------

def test_volumes_and_money_are_two_different_blocks() -> None:
    """Подписи продуктов в них одинаковые, и на экране метры сойдут за миллионы."""
    got = board.parse_board_sales(_sales_book())
    assert got["volume"]["products"]["apartments"]["sold"] == 2526.9
    assert got["money"]["products"]["apartments"]["sold"] == 1670.8


def test_paid_is_not_the_same_as_sold() -> None:
    """13% законтрактовано и 7% оплачено — это разные ответы про одни деньги."""
    got = board.parse_board_sales(_sales_book())
    totals = got["money"]["totals"]
    assert totals["sold"] == 1728.6
    assert totals["paid"] == 943.5
    assert round(totals["sold"] - totals["paid"], 1) == 785.1


def test_every_product_is_read_not_only_apartments() -> None:
    got = board.parse_board_sales(_sales_book())
    assert set(got["money"]["products"]) == {"apartments", "commercial", "parking", "storage"}


def test_apartment_brackets_survive() -> None:
    """По одной средней цене не видно, какой формат уходит, а какой стоит."""
    got = board.parse_board_sales(_sales_book())
    first = got["brackets"][0]
    assert first["range"] == "28,3 - 40"
    assert first["sold_units"] == 21
    assert round(first["share"], 4) == 0.4118
    assert first["price"] == 614.5


def _function(name: str):
    """Разбор функции деревом, а не строками.

    Строковая проверка ловила собственные оговорки в комментариях и путала
    распаковку словаря `**record` с умножением. Умножение и деление — это узлы
    дерева, и искать их надо там.
    """
    import ast
    tree = ast.parse(Path("market_search/board.py").read_text(encoding="utf-8"))
    return next(item for item in tree.body
                if isinstance(item, ast.FunctionDef) and item.name == name)


def _code_of(name: str) -> str:
    import ast
    node = _function(name)
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return "\n".join(ast.unparse(item) for item in body)


def test_nothing_is_recomputed_from_the_book() -> None:
    """Доли и цены берутся как есть: второй счёт разошёлся бы с первым."""
    import ast
    for name in ("parse_board_sales", "_apartment_brackets"):
        for node in ast.walk(_function(name)):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
                raise AssertionError(f"в {name} появилась арифметика: {ast.unparse(node)}")


def test_a_book_without_the_sheet_says_so() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "Просто лист"
    buffer = io.BytesIO()
    book.save(buffer)
    with pytest.raises(PlanNotFound):
        board.parse_board_sales(buffer.getvalue())


# --- освоение бюджета -------------------------------------------------------

def test_stages_join_budget_and_spent_by_name() -> None:
    """Бюджет и освоенное лежат в разных блоках; связывает их только имя."""
    got = board.parse_board_status(_status_book())
    stages = {item["stage"]: item for item in got["stages"]}
    assert stages["Бюджет проекта"]["budget_mln"] == 11717.5
    assert stages["Бюджет проекта"]["done_mln"] == 4119.0
    assert round(stages["Бюджет проекта"]["share"] * 100) == 35


def test_a_stage_without_a_number_is_not_a_zero() -> None:
    """«#N/A» в книге значит «этап вне окна», а ноль значил бы «не начинали»."""
    got = board.parse_board_status(_status_book())
    entry = next(item for item in got["stages"] if item["stage"] == "Вход в проект")
    assert entry["done_mln"] is None
    assert entry["share"] is None


def test_the_cut_off_date_is_read() -> None:
    got = board.parse_board_status(_status_book())
    assert got["as_of"] == "2026-05"


def test_the_budget_is_not_parsed_out_of_a_chart_label() -> None:
    """«(11 717,5 млн.р)» — текст для диаграммы, он рассыплется от формата."""
    assert "млн" not in _code_of("parse_board_status")


# --- кабинет ----------------------------------------------------------------

def test_the_cabinet_shows_the_board_card() -> None:
    source = Path("market_search/cabinet.py").read_text(encoding="utf-8")
    assert "Отчёт правлению" in source
    assert "boardCard(planData)" in source


def test_the_cabinet_names_the_difference_between_sold_and_paid() -> None:
    source = Path("market_search/cabinet.py").read_text(encoding="utf-8")
    assert "Оплачено — пришло на эскроу" in source


def test_one_upload_reads_everything() -> None:
    """Просить загрузить книгу дважды значит однажды получить два разных файла."""
    source = Path("market_search/api.py").read_text(encoding="utf-8")
    assert "board.parse_board_sales" in source
    assert "board.parse_board_status" in source


def test_a_missing_board_is_not_an_error_on_the_whole_upload() -> None:
    """У книги без листов статуса есть план, и это законный отчёт."""
    source = Path("market_search/api.py").read_text(encoding="utf-8")
    assert "board_missing" in source
