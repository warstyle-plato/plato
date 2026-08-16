"""НДС считается, а не лежит полем-обманкой.

Поле «НДС 22%» на «Вводных» было, в книгу писалось, в PDF печаталось — и на
расчёт не влияло никак: ноль и двадцать два давали один ответ до копейки.
Нашлось это сверкой с чужой моделью на Вест Гардене: у неё в «Налогах» 1 628
млн, из них 1 373 налог на прибыль и 255 НДС, а у нас НДС не было вовсе.

Методика — решение владельца (15.08.2026), снята с той же чужой книги, где
ставка 22%, отдельная статья БДДС и «Начало уплаты НДС» ровно в дату РВЭ:

* жильё по ДДУ освобождено (пп. 23.1 п. 3 ст. 149 НК), нежилое облагается —
  ПСН, офисы, паркинг, кладовые;
* цена включает налог, поэтому он вынимается по 22/122;
* затраты заданы с НДС, входящий налог уже в них — и к вычету идёт **не весь**:
  доля, приходящаяся на освобождённые операции, остаётся в себестоимости
  (п. 4 ст. 170 НК). Отсюда частая ошибка «стройка 10 млрд — вернут 1,8»;
* начисление по передаче объекта: до раскрытия эскроу оплаты застройщику нет,
  база возникает актом после ввода (ст. 167 НК).

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

RATE = 22.0
GROSS_TO_TAX = RATE / (100 + RATE)


def build(**overrides):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000,
                  purchase_price_mln=700)
    inputs.update(overrides)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def flats_only(**overrides):
    """Проект из одних квартир: всё освобождено."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650, purchase_price_mln=700)
    inputs.update(overrides)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key in ("ground_commercial", "underground_parking", "storage",
                "offices", "standalone_retail", "above_parking"):
        for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            tep[key][field] = 0
    inputs["underground_parking_disabled"] = True
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


# --- поле больше не обманка ------------------------------------------------------

def test_the_rate_changes_the_answer():
    """Ноль и двадцать два обязаны давать разные числа."""
    with_vat = build(vat_pct=RATE)["summary"]
    without = build(vat_pct=0)["summary"]
    assert with_vat["total_expenses"] != without["total_expenses"]
    assert with_vat["net_profit"] < without["net_profit"]


def test_zero_rate_costs_nothing():
    assert build(vat_pct=0)["finance"]["vat"] == 0.0


# --- что облагается --------------------------------------------------------------

def test_flats_alone_pay_no_vat():
    """Жильё по ДДУ освобождено: проект из одних квартир НДС не платит."""
    assert flats_only(vat_pct=RATE)["finance"]["vat"] == pytest.approx(0.0)


def test_the_charge_is_taken_from_the_non_residential_revenue():
    """Начислено = выручка нежилого × 22/122, ни рублём больше."""
    result = build(vat_pct=RATE)
    taxable = sum(item["revenue"] for item in result["report"]["products"]
                  if item["key"] != "apartments")
    assert result["finance"]["vat_charged"] == pytest.approx(taxable * GROSS_TO_TAX, rel=1e-6)


def test_the_flats_revenue_is_not_in_the_base():
    """Если бы квартиры попали в базу, начисление выросло бы в разы."""
    result = build(vat_pct=RATE)
    everything = result["summary"]["revenue"] * GROSS_TO_TAX
    assert result["finance"]["vat_charged"] < everything * 0.5


# --- вычет: доля, а не всё --------------------------------------------------------

def test_the_deduction_is_only_the_taxable_share():
    """Главная ловушка темы: «стройка 10 млрд — вернут 1,8» неверно.

    Доля, приходящаяся на освобождённое жильё, к вычету не принимается и
    остаётся в себестоимости — она уже внутри заданных затрат."""
    result = build(vat_pct=RATE)
    finance = result["finance"]
    input_vat_if_all_deductible = result["summary"]["capex"] * GROSS_TO_TAX
    assert finance["vat_input_deductible"] < input_vat_if_all_deductible * 0.5


def test_the_payment_is_never_negative():
    """Возврата за жизнь проекта не бывает: считаем к уплате, не к возмещению."""
    assert build(vat_pct=RATE)["finance"]["vat"] >= 0.0


def test_more_non_residential_means_more_vat():
    """Чем больше доля нежилого, тем больше налог: растёт и начисление, и
    вычет, но начисление быстрее — продают дороже себестоимости."""
    poor = build(vat_pct=RATE, parking_price_th=1500)["finance"]["vat"]
    rich = build(vat_pct=RATE, parking_price_th=9000)["finance"]["vat"]
    assert rich > poor


def test_the_land_and_the_interest_give_no_deduction():
    """Покупка участка и проценты НДС не облагаются — вычета с них нет."""
    cheap = build(vat_pct=RATE, purchase_price_mln=100)["finance"]["vat_input_deductible"]
    dear = build(vat_pct=RATE, purchase_price_mln=5000)["finance"]["vat_input_deductible"]
    assert cheap == pytest.approx(dear, rel=1e-9)


# --- когда платится ---------------------------------------------------------------

def test_nothing_is_paid_before_the_completion():
    """Начисление возникает передачей объекта, а она после ввода."""
    result = build(vat_pct=RATE)
    rve = core.d(result["dates"]["rve"])
    early = [month for month, value in result["finance"]["vat_schedule"].items()
             if value > 0 and core.d(month) < rve]
    assert early == [], early


def test_the_schedule_adds_up_to_the_total():
    result = build(vat_pct=RATE)["finance"]
    assert sum(result["vat_schedule"].values()) == pytest.approx(result["vat"], rel=1e-9)


# --- налог на прибыль не задваивается ---------------------------------------------

def test_the_vat_leaves_the_profit_tax_base():
    """НДС — не доход: обложить его прибылью значит взять налог дважды."""
    with_vat = build(vat_pct=RATE)
    without = build(vat_pct=0)
    assert with_vat["finance"]["profit_tax"] < without["finance"]["profit_tax"]


def test_the_expenses_grow_by_the_vat_exactly():
    """НДС попадает в расходы ровно один раз."""
    with_vat = build(vat_pct=RATE)
    without = build(vat_pct=0)
    delta = (with_vat["summary"]["total_expenses"] - without["summary"]["total_expenses"])
    vat = with_vat["finance"]["vat"]
    tax_relief = without["finance"]["profit_tax"] - with_vat["finance"]["profit_tax"]
    assert delta == pytest.approx(vat - tax_relief, rel=1e-6)


# --- видно в отчёте ---------------------------------------------------------------

def test_the_report_shows_the_vat_line():
    """Статья растёт вместе с долей нежилого — прятать её внутри «налогов»
    значит скрыть от человека то, чем он управляет."""
    groups = {item["label"]: item["value"] for item in build(vat_pct=RATE)["report"]["expense_structure"]}
    assert "НДС" in groups
    assert groups["НДС"] == pytest.approx(build(vat_pct=RATE)["finance"]["vat"], rel=1e-9)


def test_the_llcr_feels_the_vat():
    """НДС — денежный расход: он обязан двигать покрытие долга."""
    assert build(vat_pct=RATE)["summary"]["llcr"] < build(vat_pct=0)["summary"]["llcr"]
