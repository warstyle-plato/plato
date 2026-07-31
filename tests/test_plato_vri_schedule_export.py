"""График платежей ВРИ доезжает в книгу, даже когда расчёт ВРИ выключен.

Сумма ВРИ попадала в книгу всегда, а окно платежей — только когда расчёт ВРИ
включён. Стоимость, введённую руками при выключенном расчёте, книга разносила
своими формулами: первый платёж в дату РнС и рассрочка на 72 месяца равными
долями. Движок платит по дате обязательства — по умолчанию за месяц до РнС,
то есть до открытия ПФ, и платёж несёт БРИДЖ, который на РнС рефинансируется
в ПФ.

Расхождение выходило не в графике, а в объёме долга: книга выбирала ПФ
6,87 млрд ₽ при затратах 8,08 млрд ₽ — на 1,2 млрд ₽ меньше расчёта, и следом
расходились проценты (451 против 746 млн ₽).

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "PLATO_template.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон ПЛАТО не поставляется")


def land_sheet(**overrides):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=0, land_rights_cost_mln=1276.304,
                  project_start="2027-01-01", ird_months=18)
    inputs.update(overrides)
    data, report = core.fill_plato_template(inputs, core.TEP_DEFAULT, project_name="Проверка")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    return workbook["ЗУ"], report


@pytest.mark.parametrize("vri_required", [True, False])
def test_the_payment_window_reaches_the_book(vri_required):
    """Ровно тот случай: сумма введена руками, расчёт ВРИ выключен."""
    sheet, report = land_sheet(vri_required=vri_required)
    labels = [item["label"] for item in report["filled"] if item.get("sheet") == "ЗУ"]

    assert "Первый платёж ВРИ" in labels
    assert isinstance(sheet.cell(62, 3).value, datetime), "в книге осталась её формула =ТЭП!J22"
    assert isinstance(sheet.cell(63, 3).value, datetime)


def test_the_default_date_is_a_month_before_the_permit():
    """Соглашение подписывается до РнС — платёж несёт БРИДЖ, а не ПФ."""
    sheet, _ = land_sheet(vri_required=False)
    permit = core.add_months(core.d("2027-01-01"), 18)

    assert sheet.cell(62, 3).value.date() == core.add_months(permit, -1)


def test_the_books_own_six_year_installment_is_replaced():
    """=C60/(12*6) — рассрочка шаблона на 72 месяца, к расчёту отношения не имеет."""
    sheet, _ = land_sheet(vri_required=False)

    assert sheet.cell(64, 3).value == "=C60/1"


def test_a_manual_date_wins_over_the_default():
    sheet, _ = land_sheet(vri_required=False, vri_obligation_date="2028-02-01")

    assert sheet.cell(62, 3).value.date() == core.d("2028-02-01")


def test_a_project_without_vri_leaves_the_sheet_alone():
    """Нулевая стоимость — писать нечего, формулы шаблона не трогаем."""
    sheet, report = land_sheet(land_rights_cost_mln=0, vri_required=False)
    labels = [item["label"] for item in report["filled"] if item.get("sheet") == "ЗУ"]

    assert "Первый платёж ВРИ" not in labels
    assert str(sheet.cell(62, 3).value).startswith("=")
