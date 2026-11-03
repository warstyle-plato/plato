"""Недельный срез: где проект по деньгам, по объёмам и по графику.

Всё считается из одного набора выгрузок, поэтому обновляется их заменой: раз в
неделю кладутся свежие РСС и книга, и картина пересобирается сама.

Отставание меряется по производственной программе РСС — шахматке справа от
сметы: сколько работ должно было быть принято к срезу и сколько принято на
самом деле.

Проверки здесь про то, на чём такой монитор врёт: программа складывается с
главами и задваивается, отставание считается там, где сравнивать нечего, а
отставшая выгрузка продаж читается как «не продавали».
"""

from __future__ import annotations

import datetime

import pytest

import developaid_actuals as actuals


def _estimate(total):
    return {"rows": [], "by_code": {}, "total": {"estimate": total}}


def _payments(rows):
    return {"rows": rows, "total": sum(r["amount"] for r in rows),
            "undated": 0.0, "own_funds": 0.0, "first": None, "last": None}


def _works(rows):
    return {"rows": rows, "total": sum(r["amount"] for r in rows),
            "dated": 0.0, "undated": 0.0, "construction_dated": 0.0}


def _contracts(amount, paid, advances, outstanding, completed):
    return {"rows": [], "amount": amount, "paid": paid, "advances": advances,
            "outstanding": outstanding, "completed": completed}


def _act(month, amount, construction=True):
    return {"code": "2.2.1.4", "document": "Акт", "contractor": "СтройКо",
            "contract": "№1", "object": "МФК", "amount": amount,
            "date": datetime.date(month[0], month[1], 15),
            "construction": construction}


def _programme(months, amounts):
    return {
        "by_code": {"2.2.1.4": {datetime.date(*m, 1): a
                                for m, a in zip(months, amounts)}},
        "leaves": {"2.2.1.4"},
        "months": [datetime.date(*m, 1) for m in months],
        "first": datetime.date(*months[0], 1),
        "last": datetime.date(*months[-1], 1),
        "total": sum(amounts),
    }


def test_money_shows_what_was_paid_ahead_of_the_work():
    """Оплачено больше принятого — это авансы, и их надо видеть отдельно.

    Деньги из кассы вышли и проценты по ним идут, а работы ещё не приняты. На
    Гродненской так ушло вперёд 1 525,9 млн ₽.
    """
    report = actuals.monitor(
        _estimate(6810e6),
        _payments([{"amount": 4077e6, "date": datetime.date(2026, 5, 1),
                    "contractor": "", "contract": "", "estimate_code": "2.2.1.4"}]),
        _works([_act((2026, 5), 2551e6)]),
        _contracts(5613e6, 4077e6, 1264e6, 1536e6, 3432e6),
        cut="2026-07-01")
    money = report["money"]

    assert money["paid_ahead"] == pytest.approx(4077e6 - 2551e6)
    assert money["left_to_budget"] == pytest.approx(6810e6 - 4077e6)


def test_nothing_to_compare_is_said_out_loud_not_shown_as_zero():
    """Программа начинается там, где кончается факт — это не «отставание 100%».

    Показать нулём значило бы объявить срыв графика в первую же неделю.
    """
    report = actuals.monitor(
        _estimate(6810e6), _payments([]), _works([]),
        _contracts(0, 0, 0, 0, 0), cut="2026-07-01",
        programme=_programme([(2026, 7), (2026, 8)], [373e6, 407e6]))

    assert report["schedule"]["comparable"] is False
    assert "сравнивать ещё нечего" in report["schedule"]["reason"]


def test_being_behind_is_measured_against_the_programme():
    """Принято меньше, чем должно быть по программе, — это отставание."""
    programme = _programme([(2026, 7), (2026, 8), (2026, 9)],
                           [400e6, 400e6, 400e6])
    report = actuals.monitor(
        _estimate(6810e6), _payments([]),
        _works([_act((2026, 7), 300e6), _act((2026, 8), 250e6)]),
        _contracts(0, 0, 0, 0, 0), cut="2026-09-01", programme=programme)
    schedule = report["schedule"]

    assert schedule["comparable"] is True
    assert schedule["months_due"] == 2
    assert schedule["due"] == pytest.approx(800e6)
    assert schedule["done"] == pytest.approx(550e6)
    assert schedule["gap"] == pytest.approx(-250e6)
    assert schedule["ratio"] == pytest.approx(0.6875)


def test_being_ahead_reads_as_a_positive_gap():
    """Опережение — та же величина с другим знаком, а не отдельный случай."""
    programme = _programme([(2026, 7)], [400e6])
    report = actuals.monitor(
        _estimate(0), _payments([]), _works([_act((2026, 7), 500e6)]),
        _contracts(0, 0, 0, 0, 0), cut="2026-08-01", programme=programme)

    assert report["schedule"]["gap"] == pytest.approx(100e6)
    assert report["schedule"]["ratio"] > 1


def test_only_acts_count_towards_the_programme():
    """Плата городу и комиссии банка выполнением работ не являются.

    Сложенные с актами, они показали бы график выполненным там, где стройка
    стоит.
    """
    programme = _programme([(2026, 7)], [400e6])
    report = actuals.monitor(
        _estimate(0), _payments([]),
        _works([_act((2026, 7), 100e6),
                _act((2026, 7), 470e6, construction=False)]),
        _contracts(0, 0, 0, 0, 0), cut="2026-08-01", programme=programme)

    assert report["schedule"]["done"] == pytest.approx(100e6)


def test_a_stale_sales_export_is_not_zero_sales():
    """Месяц до среза без факта продаж — «выгрузка отстала», а не «не продавали».

    На Гродненской при срезе 01.07.2026 таких месяцев три: факт продаж идёт
    только по март.
    """
    sales = {"rows": [
        {"month": datetime.date(2026, 2, 1), "fact": True, "units": 3,
         "area": 61.3, "price": 359_200.0, "revenue": 22.0e6},
        {"month": datetime.date(2026, 3, 1), "fact": True, "units": 3,
         "area": 317.9, "price": 834_100.0, "revenue": 265.2e6},
        {"month": datetime.date(2026, 4, 1), "fact": False, "units": 3,
         "area": 130.2, "price": 739_366.0, "revenue": 96.3e6},
        {"month": datetime.date(2026, 5, 1), "fact": False, "units": 2,
         "area": 110.7, "price": 695_370.0, "revenue": 77.0e6},
    ]}
    report = actuals.monitor(
        _estimate(0), _payments([]), _works([]), _contracts(0, 0, 0, 0, 0),
        cut="2026-07-01", sales=sales)
    sold = report["sales"]

    assert sold["area"] == pytest.approx(379.2)
    assert sold["last_fact"] == datetime.date(2026, 3, 1)
    assert sold["months_without_fact"] == 2


def test_a_cut_without_a_date_is_refused():
    """Без даты среза монитор не собирается — гадать не из чего."""
    with pytest.raises(ValueError):
        actuals.monitor(_estimate(0), _payments([]), _works([]),
                        _contracts(0, 0, 0, 0, 0), cut=None)


def test_the_programme_needs_its_first_month_from_outside():
    """В шапке программы стоит «июль» без года — додумывать год нельзя.

    Ошибка на двенадцать месяцев не видна ни в одной сумме.
    """
    with pytest.raises(ValueError):
        actuals.read_programme("не важно", start=None)
