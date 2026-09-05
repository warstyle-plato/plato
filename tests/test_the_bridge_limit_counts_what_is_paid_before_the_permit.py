"""БРИДЖем банк считает то, что существует ДО РнС.

«Почему мы все 7.5 включаем в расчётный бридж если по графику ясно, что часть
будет уже в ПФ?» (владелец, 04.09.2026) — и следом решение: «банк конечно
считаем бриджем то что существует до рнс».

Лимит брал ВСЮ цену покупки, не глядя на график платежей. Замерено на графике
«40% в сделку, 60% через 30 мес.» при РнС на 18-м месяце: лимит выходил
10,10 млрд, где вся покупка 7,50, — при том что 4,50 из неё платится уже после
РнС, то есть из ПФ. Лимит завышался ровно на эту часть.

Рядом чинится вторая болезнь того же места: состав лимита («Приобретение
проекта») экран и печать выводили ВЫЧИТАНИЕМ — «итог минус социалка минус П
минус РД». Два вычитания на одну величину однажды разошлись бы, и обе строки
выглядели бы верными; теперь состав считает движок один раз, а поверхности его
рисуют.

Запуск: python3 -m pytest tests/test_the_bridge_limit_counts_what_is_paid_before_the_permit.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PRICE_MLN = 7500.0
IRD_MONTHS = 18          # РнС на 18-м месяце
SCHEDULE = "40%@0; 60%@30"   # 3,0 млрд в сделку и 4,5 млрд через 30 мес.


def _run(schedule: str = SCHEDULE) -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update({"purchase_price_mln": PRICE_MLN, "ird_months": IRD_MONTHS,
              "purchase_schedule": schedule})
    return core._run_authoritative_model(x, copy.deepcopy(core.TEP_DEFAULT), [], {})["consolidated"]


def _paid_before_permit(result: dict, article: str = "purchase") -> float:
    permit = str(result["dates"]["permit"])
    months = result["monthly"]["months"]
    row = next(c for c in result["monthly"]["costs"] if c["key"] == article)
    return sum(v for m, v in zip(months, row["values"]) if str(m) < permit)


def test_the_limit_takes_only_the_part_paid_before_the_permit() -> None:
    """Ровно та поломка: в лимит уезжали все 7,5 при 3,0 до РнС."""
    result = _run()
    parts = result["report"]["financing"]["calculated_bridge_parts"]
    before = _paid_before_permit(result)
    assert before == pytest.approx(3_000_000_000, rel=1e-6), "график прочитан не так"
    assert parts["purchase"] == pytest.approx(before, rel=1e-9), (
        "лимит считает покупку не по графику платежей")
    assert parts["purchase"] < PRICE_MLN * 1_000_000 * 0.9, (
        "в лимит по-прежнему уезжает вся цена")


def test_a_purchase_paid_at_the_deal_keeps_the_whole_price() -> None:
    """Без рассрочки правка не двигает ничего: вся цена платится до РнС."""
    result = _run("")
    parts = result["report"]["financing"]["calculated_bridge_parts"]
    assert parts["purchase"] == pytest.approx(PRICE_MLN * 1_000_000, rel=1e-6)


def test_the_parts_add_up_to_the_limit() -> None:
    """Состав лимита складывается в сам лимит — иначе это два разных числа."""
    financing = _run()["report"]["financing"]
    parts = financing["calculated_bridge_parts"]
    assert sum(parts.values()) == pytest.approx(financing["calculated_bridge"], rel=1e-9)


def test_the_surfaces_read_the_parts_and_do_not_subtract() -> None:
    """Экран и печать выводили состав вычитанием — двумя разными вычитаниями."""
    import inspect

    page = core.PAGE
    assert "calculated_bridge_parts" in page, "экран не читает состав лимита"
    assert "bridgeTotal-bridgeSocial" not in page, "экран всё ещё вычитает состав"
    printed = inspect.getsource(core._build_developaid_pdf)
    assert "calculated_bridge_parts" in printed, "печать не читает состав лимита"
    assert "bridge_total - bridge_social" not in printed, "печать всё ещё вычитает"


def test_the_workbook_uses_the_same_methodology() -> None:
    """Методику меняют в двух местах: в движке и в книге."""
    import io

    openpyxl = pytest.importorskip("openpyxl")
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update({"purchase_price_mln": PRICE_MLN, "ird_months": IRD_MONTHS,
              "purchase_schedule": SCHEDULE})
    built = core.build_plato_model_v2(x, copy.deepcopy(core.TEP_DEFAULT), [], {})
    content = built[0] if isinstance(built, tuple) else built
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    formula = str(book["Вводные"].cell(row=_bridge_limit_row(book), column=2).value or "")
    assert "SUMIF" in formula, "книга по-прежнему берёт итог статьи, а не платежи до РнС"
    assert "EDATE" in formula, "в книге не выражен месяц РнС"


def _bridge_limit_row(book) -> int:
    sheet = book["Вводные"]
    for row in range(1, sheet.max_row + 1):
        if str(sheet.cell(row=row, column=1).value or "").startswith("Расчётный лимит БРИДЖ"):
            return row
    raise AssertionError("строка расчётного лимита БРИДЖ в книге не найдена")
