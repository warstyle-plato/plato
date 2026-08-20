"""Project Monitor contract: fixed PM/GPR baseline, weekly RSS 6.1.2 only."""

from __future__ import annotations

import datetime
import io

import pytest
from openpyxl import Workbook

import developaid_monitor as monitor


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")


def _baseline_book() -> bytes:
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
    row = ["1", "1.1", "СМР", "Корпус 1", "Монолит", "Работа", 0,
           "2026-07-01", "2026-09-30", "", 65, "", "", "", "", "",
           "2.2.1.4.", "Монолит", "ручная привязка"]
    for col, value in enumerate(row, 1):
        gpr.cell(row=5, column=col, value=value)

    # Payment baseline in the same four-column layout used by Project Control:
    # each month repeats Plan / Fact / Delta / Status, and ИТОГО ПРОЕКТ carries
    # the monthly plan in the Plan column.
    cash = book.create_sheet("CF ПЛАН-ФАКТ")
    months = [datetime.date(2026, 7, 1), datetime.date(2026, 8, 1),
              datetime.date(2026, 9, 1)]
    plans = [100.0, 200.0, 300.0]  # Project Control sheet is in million RUB.
    for i, (month, plan) in enumerate(zip(months, plans)):
        col = 2 + i * 4
        cash.cell(row=2, column=col, value=month)
        cash.cell(row=4, column=col, value="План")
        cash.cell(row=4, column=col + 1, value="Факт")
        cash.cell(row=6, column=col, value=plan)
    cash.cell(row=6, column=1, value="ИТОГО ПРОЕКТ")

    blob = io.BytesIO(); book.save(blob); return blob.getvalue()


def _rss_book(*, acts=(), payments=(), estimate=1_000e6) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Расчет стоимости строительства"
    # One RSS leaf used by the baseline GPR.
    sheet.cell(row=10, column=1, value="2.2.1.4")
    sheet.cell(row=10, column=4, value="Монолит")
    sheet.cell(row=10, column=5, value=estimate)
    sheet.cell(row=10, column=6, value=estimate)
    sheet.cell(row=10, column=7, value=sum(v for _, v in payments))
    sheet.cell(row=10, column=11, value=sum(v for _, v in acts))
    sheet.cell(row=12, column=4, value="Всего инвестиционные расходы")
    sheet.cell(row=12, column=5, value=estimate)
    sheet.cell(row=12, column=6, value=estimate)
    sheet.cell(row=12, column=7, value=sum(v for _, v in payments))
    sheet.cell(row=12, column=11, value=sum(v for _, v in acts))

    book.create_sheet("Реестр договоров")
    paid = book.create_sheet("Реестр платежей")
    for offset, (day, amount) in enumerate(payments):
        r = 10 + offset
        paid.cell(row=r, column=2, value="СтройКо")
        paid.cell(row=r, column=3, value="Д-1")
        paid.cell(row=r, column=7, value="2.2.1.4")
        paid.cell(row=r, column=9, value=day)
        paid.cell(row=r, column=10, value=amount)
        paid.cell(row=r, column=11, value="заёмные")

    works = book.create_sheet("Реестр выполненных работ")
    for offset, (day, amount) in enumerate(acts):
        r = 9 + offset
        works.cell(row=r, column=2, value="Акт КС-2")
        works.cell(row=r, column=3, value=f"{offset + 1} от {day}")
        works.cell(row=r, column=7, value="2.2.1.4")
        works.cell(row=r, column=9, value=amount)
        works.cell(row=r, column=11, value="СтройКо")
        works.cell(row=r, column=12, value="Д-1")

    blob = io.BytesIO(); book.save(blob); return blob.getvalue()


def _setup_baseline():
    return monitor.store_schedule("Гродненская", _baseline_book(), None,
                                  "2026-07-01")


def test_baseline_is_created_once_and_not_refreshed_weekly():
    created = _setup_baseline()
    assert created["baseline"] is True
    assert created["works"] == 1
    assert created["payment_plan"] is True
    with pytest.raises(FileExistsError):
        _setup_baseline()


def test_weekly_input_is_one_rss_file_for_progress_and_payments():
    _setup_baseline()
    rss = _rss_book(
        acts=[("15.07.2026", 200e6), ("10.08.2026", 200e6)],
        payments=[(datetime.date(2026, 7, 15), 90e6),
                  (datetime.date(2026, 8, 10), 150e6)],
    )
    monitor.store_estimate("Гродненская", rss, "2026-08-15")
    view = monitor.build("Гродненская", cut="2026-08-15")

    work = view["schedule"]["rows"][0]
    assert work["actual_progress"] == pytest.approx(0.4)
    assert work["accepted"] == pytest.approx(400e6)
    assert work["status"] == "ОТСТАВАНИЕ"
    assert view["money"]["payment_fact"] == pytest.approx(240e6)
    cash = {row["month"]: row for row in view["payments"]["rows"]}
    assert cash["2026-07-01"]["plan"] == pytest.approx(100e6)
    assert cash["2026-07-01"]["fact"] == pytest.approx(90e6)
    assert cash["2026-08-01"]["plan"] == pytest.approx(200e6)
    assert cash["2026-08-01"]["fact"] == pytest.approx(150e6)


def test_next_rss_snapshot_updates_fact_without_touching_baseline():
    _setup_baseline()
    monitor.store_estimate("Гродненская", _rss_book(
        acts=[("15.07.2026", 200e6)], payments=[]), "2026-07-31")
    first = monitor.build("Гродненская", cut="2026-07-31")
    monitor.store_estimate("Гродненская", _rss_book(
        acts=[("15.07.2026", 200e6), ("15.08.2026", 250e6)], payments=[]),
        "2026-08-31")
    second = monitor.build("Гродненская", cut="2026-08-31")

    assert first["schedule"]["rows"][0]["plan_finish"] == "2026-09-30"
    assert second["schedule"]["rows"][0]["plan_finish"] == "2026-09-30"
    assert first["schedule"]["rows"][0]["actual_progress"] == pytest.approx(0.2)
    assert second["schedule"]["rows"][0]["actual_progress"] == pytest.approx(0.45)
    assert monitor.snapshots("Гродненская")["estimate"] == ["2026-07-31", "2026-08-31"]


def test_a_weekly_rss_snapshot_is_never_overwritten():
    _setup_baseline()
    data = _rss_book()
    monitor.store_estimate("Гродненская", data, "2026-08-15")
    with pytest.raises(FileExistsError):
        monitor.store_estimate("Гродненская", data, "2026-08-15")


def test_proposals_programme_and_sales_do_not_change_monitor_result():
    """Legacy endpoints may exist during rollout, but are not Monitor inputs."""
    _setup_baseline()
    monitor.store_estimate("Гродненская", _rss_book(
        acts=[("15.07.2026", 200e6)], payments=[]), "2026-08-15")
    before = monitor.build("Гродненская", cut="2026-08-15")

    monitor.store_programme("Гродненская", b"not used", "2026-07", "2026-08-01")
    monitor.store_proposal("Гродненская", b"not used", "sheet", "2026-07",
                           "2.2.1.4", "2026-08-02")
    monitor.store_sales("Гродненская", [{"month": "2026-08", "revenue": 1}],
                        "2026-08-03")
    after = monitor.build("Гродненская", cut="2026-08-15")

    assert after["schedule"] == before["schedule"]
    assert after["payments"] == before["payments"]


def test_rewritten_history_is_still_visible_between_rss_snapshots():
    _setup_baseline()
    monitor.store_estimate("Гродненская", _rss_book(
        acts=[("15.05.2026", 272.7e6), ("15.06.2026", 76.6e6)]), "2026-06-30")
    monitor.store_estimate("Гродненская", _rss_book(
        acts=[("15.05.2026", 148.4e6), ("15.06.2026", 114.7e6)]), "2026-08-20")
    moved = monitor.moved_between_snapshots("Гродненская", "2026-06-30", "2026-08-20")
    by_month = {row["month"]: row for row in moved["rows"]}
    assert by_month["2026-05"]["delta"] == pytest.approx(-124.3e6)
    assert by_month["2026-06"]["delta"] == pytest.approx(38.1e6)


def test_the_routes_are_hidden_and_gated():
    import main_legacy as engine
    routes = [route for route in engine.app.routes if "/monitor" in getattr(route, "path", "")]
    assert routes
    assert not any(getattr(route, "include_in_schema", True) for route in routes)
