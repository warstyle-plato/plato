"""Управленческая сводка собирается из тех же источников, что мониторинг и продажи.

Проверки:
- физическое выполнение берётся из процентов ГПР-факта, прирост — разница
  снимков на начало и конец периода; без снимка на начало прирост не
  выдаётся нулём;
- бюджет месяца — план «CF ПЛАН-ФАКТ» против реестра платежей РСС;
- продажи — договоры, подписанные в периоде, против плана финмодели и банка;
  договоры вне периода в факт не попадают;
- отсутствие источника названо причиной, а не нулём.

Запуск: python3 -m pytest tests/test_management_report_model.py -q
"""
from __future__ import annotations

import datetime
import io

import pytest
from openpyxl import Workbook

import developaid_management_report as report
import developaid_monitor as monitor
from market_search import sales_store

M = 1e6
PROJECT = "Гродненская"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _gpr_book(progress: dict[str, float], cash: bool = True) -> bytes:
    book = Workbook()
    gpr = book.active
    gpr.title = "ГПР"
    header = ["ID", "WBS", "Раздел", "Объект", "Наименование работ",
              "Тип строки", "% выполнения", "Начало", "Окончание", "Статус",
              "Длительность, р.д.", "Предшественники", "Связанный тендер",
              "Окончание тендера", "Резерв", "Увязка", "Код РСС",
              "Статья РСС", "Основание привязки"]
    for col, value in enumerate(header, 1):
        gpr.cell(row=4, column=col, value=value)
    works = [
        # id, объект, начало, конец: «Монолит» вдвое длиннее «Фасада».
        ("1", "Корпус 1", "Монолит", datetime.date(2026, 7, 1), datetime.date(2026, 12, 28)),
        ("2", "Корпус 2", "Фасад", datetime.date(2026, 9, 1), datetime.date(2026, 11, 29)),
    ]
    for line, (tid, obj, name, start, finish) in enumerate(works, 5):
        row = [tid, tid, "СМР", obj, name, "Работа", progress.get(tid, 0.0),
               start, finish, "", 10, "", "", "", "", "", "2.2.1.4", "", ""]
        for col, value in enumerate(row, 1):
            gpr.cell(row=line, column=col, value=value)
    if cash:
        sheet = book.create_sheet("CF ПЛАН-ФАКТ")
        for i, (month, plan) in enumerate(((datetime.date(2026, 9, 1), 300.0),
                                           (datetime.date(2026, 10, 1), 400.0))):
            col = 2 + i * 4
            sheet.cell(row=2, column=col, value=month)
            sheet.cell(row=4, column=col, value="План")
            sheet.cell(row=4, column=col + 1, value="Факт")
            sheet.cell(row=6, column=col, value=plan)
        sheet.cell(row=6, column=1, value="ИТОГО ПРОЕКТ")
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def _rss_book(payments) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Расчет стоимости строительства"
    sheet.cell(row=10, column=1, value="2.2.1.4")
    sheet.cell(row=10, column=4, value="Монолит")
    sheet.cell(row=10, column=5, value=1_000 * M)
    sheet.cell(row=12, column=4, value="Всего инвестиционные расходы")
    sheet.cell(row=12, column=5, value=1_000 * M)
    book.create_sheet("Реестр договоров")
    paid = book.create_sheet("Реестр платежей")
    for offset, (day, amount) in enumerate(payments):
        r = 10 + offset
        paid.cell(row=r, column=2, value="СтройКо")
        paid.cell(row=r, column=3, value="Д-1")
        paid.cell(row=r, column=7, value="2.2.1.4")
        paid.cell(row=r, column=9, value=day)
        paid.cell(row=r, column=10, value=amount)
    book.create_sheet("Реестр выполненных работ")
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def _contract(signed: str, product: str, area: float, amount: float) -> dict:
    return {"month": signed[:7], "signed": signed, "product": product,
            "unit": "", "kind": "", "rooms": "", "area": area, "contract": "",
            "contract_type": "", "state": "", "amount": amount, "units": 1.0,
            "payment_variant": "", "broker": "", "broker_fee": 0.0,
            "broker_rate": None, "sales_bonus_paid": 0.0, "escrow_paid": 0.0,
            "company_buyer": False, "escrow_schedule": []}


def _sales(contracts, bank: bool = True) -> None:
    parts = {
        "contracting": {"project": "ЖК Гродненская", "missing": [], "rows": contracts},
        "fm_plan": {"sheet": "ФМ", "plan": {
            "Итого": {"2026-10": {"amount": 100 * M}, "2026-11": {"amount": 150 * M},
                      "2026-12": {"amount": 50 * M}},
            "Квартира": {"2026-10": {"area": 400.0}, "2026-11": {"area": 600.0}}}},
    }
    if bank:
        parts["bank_plan"] = {"sheet": "Банк",
                              "gross_by_quarter": {"2026 Q3": 900 * M, "2026 Q4": 280 * M},
                              "area_by_quarter": {"2026 Q4": 1_100.0},
                              "price_by_quarter": {"2026 Q4": 255_000.0},
                              "revenue_by_quarter": {}}
    sales_store.save(sales_store.default_dir(), "ЖК Гродненская", parts, "test.xlsx")


def _project(with_before: bool = True) -> None:
    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    if with_before:
        monitor.store_schedule_fact(PROJECT, _gpr_book({"1": 0.40, "2": 0.10}, cash=False),
                                    "2026-10-09")
    monitor.store_schedule_fact(PROJECT, _gpr_book({"1": 0.55, "2": 0.40}, cash=False),
                                "2026-10-16")
    monitor.store_estimate(PROJECT, _rss_book([
        (datetime.date(2026, 9, 20), 280 * M),
        (datetime.date(2026, 10, 5), 120 * M),
        (datetime.date(2026, 10, 14), 30 * M),
    ]), "2026-10-16")


def test_physical_progress_is_the_gpr_percent_and_its_weekly_growth():
    _project()
    got = report.physical(PROJECT, "week", "2026-10-18")
    assert got["state"] == "ok"
    assert got["snapshot"] == "2026-10-16"
    assert got["snapshot_before"] == "2026-10-09"
    assert got["fresh"] is True
    # Монолит 180 дней, фасад 89: вес по длительности работ.
    w1, w2 = 180.0, 89.0
    fact = (w1 * 0.55 + w2 * 0.40) / (w1 + w2)
    before = (w1 * 0.40 + w2 * 0.10) / (w1 + w2)
    assert got["fact"] == pytest.approx(fact)
    assert got["delta"] == pytest.approx(fact - before)
    plan1 = (datetime.date(2026, 10, 18) - datetime.date(2026, 7, 1)).days / w1
    plan2 = (datetime.date(2026, 10, 18) - datetime.date(2026, 9, 1)).days / w2
    assert got["plan"] == pytest.approx((w1 * plan1 + w2 * plan2) / (w1 + w2))
    assert [o["object"] for o in got["objects"]] == ["Корпус 1", "Корпус 2"]
    assert got["objects"][1]["fact"] == pytest.approx(0.40)


def test_without_a_snapshot_before_the_period_growth_is_unknown_not_zero():
    _project(with_before=False)
    got = report.physical(PROJECT, "week", "2026-10-18")
    assert got["delta"] is None
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert "посчитать не из чего" in text


def test_an_old_snapshot_is_flagged_as_not_refreshed():
    _project()
    got = report.physical(PROJECT, "week", "2026-10-25")
    assert got["fresh"] is False
    assert got["delta"] == pytest.approx(0.0)
    text = report.render_text(report.build(PROJECT, "week", "2026-10-25"))
    assert "новый график с процентами не загружали" in text


def test_no_schedule_fact_is_a_named_reason():
    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    got = report.physical(PROJECT, "week", "2026-10-18")
    assert got["state"] == "missing"
    assert "ГПР-факт" in got["reason"]


def test_month_budget_is_plan_against_payments_of_that_month():
    _project()
    got = report.budget(PROJECT, "month", "2026-10-31")
    assert got["state"] == "ok"
    assert got["month"] == "2026-10-01"
    assert got["plan"] == pytest.approx(400 * M)
    assert got["fact"] == pytest.approx(150 * M)
    assert got["remaining"] == pytest.approx(250 * M)


def test_sales_take_only_contracts_signed_in_the_period():
    _project()
    _sales([
        _contract("2026-10-13", "Квартира", 50.0, 12.5 * M),
        _contract("2026-10-17", "Квартира", 70.0, 17.5 * M),
        _contract("2026-10-05", "Квартира", 100.0, 25 * M),
        _contract("2026-09-20", "Машиноместо", 0.0, 3 * M),
        # После конца периода — в сводку недели не входит.
        _contract("2026-10-19", "Квартира", 40.0, 10 * M),
    ])
    got = report.sales("ЖК Гродненская", "week", "2026-10-18")
    assert got["state"] == "ok"
    assert got["period"]["contracts"] == 2
    assert got["period"]["amount"] == pytest.approx(30 * M)
    assert got["period"]["area"] == pytest.approx(120.0)
    assert got["period"]["price_flats"] == pytest.approx(250_000.0)
    assert got["month"]["fact"]["contracts"] == 3
    assert got["month"]["fm"] == {"amount": 100 * M, "area": 400.0}
    assert got["quarter"]["key"] == "2026 Q4"
    assert got["quarter"]["fm"]["amount"] == pytest.approx(300 * M)
    assert got["quarter"]["bank"]["amount"] == pytest.approx(280 * M)
    assert got["quarter"]["fact"]["amount"] == pytest.approx(55 * M)


def test_sales_without_bank_plan_say_so():
    _project()
    _sales([_contract("2026-10-13", "Квартира", 50.0, 12.5 * M)], bank=False)
    got = report.sales("ЖК Гродненская", "week", "2026-10-18")
    assert got["quarter"]["bank"] is None
    assert got["quarter"]["bank_reason"] == "План банка не загружен."


def test_unlinked_or_empty_sales_are_named():
    assert report.sales("", "week", "2026-10-18")["state"] == "missing"
    got = report.sales("Нет такого", "week", "2026-10-18")
    assert got["state"] == "missing"
    assert "контрактация" in got["reason"]


def test_one_broken_block_does_not_hide_the_others(monkeypatch):
    _project()

    def broken(*_args, **_kwargs):
        raise ValueError("лист испорчен")

    monkeypatch.setattr(report, "budget", broken)
    got = report.build(PROJECT, "week", "2026-10-18")
    assert got["physical"]["state"] == "ok"
    assert got["budget"]["state"] == "missing"
    assert "лист испорчен" in got["budget"]["reason"]
    assert "лист испорчен" in report.render_text(got)


def test_message_carries_all_three_blocks():
    _project()
    _sales([_contract("2026-10-13", "Квартира", 50.0, 12.5 * M)])
    text = report.render_text(report.build(PROJECT, "month", "2026-10-31",
                                           sales_project="ЖК Гродненская"))
    assert "за октябрь 2026" in text
    assert "Бюджет на октябрь 2026: план 400,0 млн ₽, оплачено 150,0 млн ₽, " \
           "осталось 250,0 млн ₽." in text
    assert "План банка на квартал: 280,0 млн ₽" in text
    assert "Выполнено по графику работ" in text


def test_period_bounds():
    week = report.period_bounds("week", "2026-10-18")
    assert (week["start"], week["before"]) == (datetime.date(2026, 10, 12),
                                               datetime.date(2026, 10, 11))
    month = report.period_bounds("month", "2026-09-30")
    assert month["start"] == datetime.date(2026, 9, 1)
    with pytest.raises(ValueError):
        report.period_bounds("year", "2026-09-30")
