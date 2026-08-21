"""Гостевые машино-места не продаются.

По нормативу они обслуживают посетителей и остаются общим имуществом. Модель
продавала весь подземный паркинг целиком: на 369 местах это 34 несуществующие
продажи (владелец, 21.08.2026). В книгу правило было записано давно — строка
«Гостевые парковки» обнуляется в ТЭП!I33, — а движок его не исполнял, и
обещание книги расходилось с расчётом.

Запуск: python3 -m pytest tests/test_guest_parking_is_not_for_sale.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_owners_case_to_the_space():
    """369 мест — 34 гостевых, продаётся 335."""
    row = {"units": 369}
    assert core.underground_guest_spaces(row) == 34
    assert core.underground_saleable_spaces(row) == 335


def test_the_exact_count_from_the_export_wins_over_the_ratio():
    """Когда число гостевых известно из выгрузки, доля не выдумывается."""
    assert core.underground_guest_spaces({"units": 369, "guest_units": 20}) == 20
    assert core.underground_saleable_spaces({"units": 369, "guest_units": 20}) == 349


def test_the_ratio_follows_the_norm_not_a_round_number():
    """Гостевые — десятая часть постоянных, значит S/11 от всех мест."""
    for permanent in (100, 250, 897):
        guest = -(-permanent // 10)
        total = permanent + guest
        assert core.underground_guest_spaces({"units": total}) == guest, total


def test_an_empty_row_is_not_a_crash():
    assert core.underground_guest_spaces({}) == 0
    assert core.underground_saleable_spaces({}) == 0.0
    assert core.underground_guest_spaces({"units": "—"}) == 0


def test_the_revenue_and_the_report_agree_on_what_is_sold():
    """Показанное количество и посчитанная выручка — про одни и те же места."""
    x = dict(core.DEFAULT_INPUTS)
    x.update(underground_manual_spaces=369, apartment_price_th=600)
    result = core.calculate(core.CalcRequest(
        inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    parking = {p["label"]: p for p in result["report"]["products"]}["Подземный паркинг"]
    assert round(parking["quantity"]) == 335, (
        "в отчёте показано не то, что продано — расхождение внутри одной строки")
    assert parking["revenue"] > 0


def test_the_book_is_sold_the_same_spaces_as_the_engine():
    """Книга получает продаваемые места, а не все построенные.

    Прежде в строку «Постоянные парковки» шло `units` — все места разом,
    включая гостевые, а строка гостевых обнулялась. Движок тогда продавал
    столько же, и паритет книги с движком проходил: обе стороны ошибались
    одинаково. Согласие — не правильность, и проверка, сверяющая две
    реализации одной ошибки, молчит именно тогда, когда нужна.
    """
    tep = {"underground_parking": {"units": 369}}
    assert core._plato_tep_value(tep, "underground_parking.saleable_units") == 335
    # Гостевые строятся, но в сумму продаж ТЭП!I33 не входят.
    assert core._plato_tep_value(tep, "underground_parking.guest_units") == 0.0
    paths = [path for _, path in core._PLATO_TEP_ROWS]
    assert "underground_parking.units" not in paths, (
        "в продажи книги снова уехали все места, включая гостевые")
