"""Сверка посчитанной книги ПЛАТО с расчётом движка.

Шаблон — живая книга на формулах, и ошибиться он может независимо от нас:
ячейка тянет значение не оттуда, остаётся хвост прежней методики, ломается
ссылка. Расхождение по социальной нагрузке — 0,6 млн ₽ против 193,2 млн ₽ —
искалось глазами полтора десятка шагов. Такое надо измерять.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")


def book(values: dict[str, float]) -> bytes:
    """Книга с листом «ОТЧЕТ» — как её сохраняет Excel после пересчёта."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "ОТЧЕТ"
    for index, (label, value) in enumerate(values.items(), start=4):
        sheet.cell(row=index, column=2, value=label)
        sheet.cell(row=index, column=3, value=value)
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def project():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 700
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return inputs, tep


def engine(inputs, tep):
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    return bundle["consolidated"]["summary"]


def test_a_workbook_that_agrees_reports_no_mismatch():
    inputs, tep = project()
    summary = engine(inputs, tep)
    report = core.audit_plato_workbook(book({
        "Поступления": summary["revenue"] / 1e6,
        "Вход": -inputs["purchase_price_mln"],
        "LLCR": summary["llcr"],
    }), inputs, tep)

    assert report["recalculated"] is True
    assert report["mismatched"] == []
    assert "не найдено" in report["verdict"]


def test_the_sign_of_an_expense_does_not_matter():
    """Шаблон пишет расходы отрицательными, движок — положительными."""
    inputs, tep = project()
    summary = engine(inputs, tep)
    report = core.audit_plato_workbook(
        book({"Расходы": -summary["total_expenses"] / 1e6}), inputs, tep)

    assert [item["name"] for item in report["mismatched"]] == []


def test_a_wrong_social_cost_is_caught():
    """Ровно та ошибка, что нашлась в присланной модели."""
    inputs, tep = project()
    report = core.audit_plato_workbook(
        book({"Строительство соцобъектов": -0.628}), inputs, tep)

    caught = [item for item in report["mismatched"] if item["name"] == "социальная нагрузка"]
    assert caught, report["items"]
    assert caught[0]["model"] == pytest.approx(0.628, abs=0.001)
    assert caught[0]["engine"] > 100


def test_the_worst_discrepancy_is_named_first():
    inputs, tep = project()
    summary = engine(inputs, tep)
    report = core.audit_plato_workbook(book({
        "Чистая прибыль": summary["net_profit"] / 1e6 + 900,
        "Коммерческие": -summary["commercial_costs"] / 1e6 - 5,
    }), inputs, tep)

    assert report["mismatched"][0]["name"] == "чистая прибыль"
    assert "чистая прибыль" in report["verdict"]


def test_an_uncalculated_workbook_is_named_as_such():
    """openpyxl формул не считает: пустую книгу нельзя выдать за совпадение."""
    inputs, tep = project()
    report = core.audit_plato_workbook(book({}), inputs, tep)

    assert report["recalculated"] is False
    assert "не пересчитана" in report["verdict"]
    assert report["mismatched"] == []


def test_a_foreign_workbook_is_refused():
    workbook = openpyxl.Workbook()
    stream = io.BytesIO()
    workbook.save(stream)
    inputs, tep = project()

    with pytest.raises(HTTPException) as failure:
        core.audit_plato_workbook(stream.getvalue(), inputs, tep)

    assert "ОТЧЕТ" in str(failure.value.detail)


def test_the_tolerance_is_respected():
    inputs, tep = project()
    summary = engine(inputs, tep)
    off = book({"Поступления": summary["revenue"] / 1e6 * 1.005})

    assert core.audit_plato_workbook(off, inputs, tep, tolerance_pct=1.0)["mismatched"] == []
    assert core.audit_plato_workbook(off, inputs, tep, tolerance_pct=0.1)["mismatched"]
