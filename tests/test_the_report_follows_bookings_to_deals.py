"""Брони из отчёта отдела продаж: какие стали договорами, какие сорвались.

Владелец (24.10.2026): «и надо следить, сколько броней не вышло в сделку в
итоге». Отчёт в чате каждый день перечисляет текущие брони; бронь, пропавшая
из списка, ищется в контрактации по номеру квартиры и площади.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from market_search import salesroom, sales_store  # noqa: E402
import developaid_management_report as report  # noqa: E402
from test_management_report_model import M, _contract  # noqa: E402


def _report(*lots: str) -> str:
    lines = "\n".join(f"- квартира № {lot}" for lot in lots)
    return ("Отчёт\nВстречи за день - 1\nЦО за день - 2\nДДУ на регистрации: 0\n"
            f"Текущих броней: {len(lots)}\n{lines}")


def _chat() -> dict:
    read = None
    for day, lots in (("2026-10-01", ("20, башня Гармония, 5 этаж, 90,2 кв.м.",
                                      "63, башня Сфера, 3 этаж, 61,9 кв.м.",
                                      "45, башня Гармония, 2 этаж, 50,0 кв.м.")),
                      ("2026-10-10", ("20, башня Гармония, 5 этаж, 90,2 кв.м.",
                                      "45, башня Гармония, 2 этаж, 50,0 кв.м.")),
                      ("2026-10-20", ("20, башня Гармония, 5 этаж, 90,2 кв.м.",))):
        read = salesroom.append_message(read, day, "Мария", _report(*lots))
    return read


def _deal(unit: str, area: float, signed: str) -> dict:
    return dict(_contract(signed, "Квартира", area, 30 * M), unit=unit)


DEALS = [_deal("корп 2 кв.63", 61.9, "2026-10-08"),
         # Тот же номер в другом корпусе и с другой площадью — не та квартира.
         _deal("корп 1 кв.45", 72.3, "2026-10-19")]


def test_the_booking_list_is_read_item_by_item():
    lots = salesroom.booked_lots(_report("20, башня Гармония, 5 этаж, 90,2 кв.м.",
                                         "63, башня Сфера, 3 этаж, 61,9 кв.м."))
    assert lots == [{"apartment": "20", "area": 90.2, "tower": "башня Гармония", "manager": ""},
                    {"apartment": "63", "area": 61.9, "tower": "башня Сфера", "manager": ""}]
    assert salesroom.booked_lots("Встречи за день - 1") is None
    assert salesroom.booked_lots("Текущих броней: 0") == []


def test_a_gone_booking_is_a_deal_or_a_drop():
    got = salesroom.booking_outcomes(_chat(), DEALS, "2026-10-24", "2026-10-18", "2026-10-24")
    assert got["since"] == "2026-10-01" and got["latest"] == "2026-10-20"
    assert got["total"] == {"deal": 1, "dropped": 1, "unknown": 0}
    [gone] = got["period"]
    assert (gone["apartment"], gone["outcome"], gone["gone"], gone["days"]) == ("45", "dropped",
                                                                               "2026-10-20", 19)
    assert [lot["apartment"] for lot in got["held"]] == ["20"]
    # Контрактация старше ухода брони: отсутствие договора — ещё не срыв.
    old = salesroom.booking_outcomes(_chat(), DEALS, "2026-10-15", "2026-10-18", "2026-10-24")
    assert old["total"] == {"deal": 1, "dropped": 0, "unknown": 1}


def test_the_report_says_how_many_bookings_failed():
    sales_store.save(sales_store.default_dir(), "ЖК Брони", {
        "contracting": {"project": "ЖК Брони", "missing": [], "rows": DEALS},
        "salesroom": _chat()}, "test.xlsx")
    got = report.sales("ЖК Брони", "week", "2026-10-24")
    line = report._bookings_line(got["bookings"], "week")
    assert line.startswith("Брони за неделю: из списка ушли 1 — 1 снята без сделки "
                           "(кв. 45, 50,0 м², держалась 19 дней).")
    assert "С 01.10.2026 из 2 закрытых броней договорами стали 1 (50,0%), без сделки — 1." in line
    assert "Сейчас в списке 1 бронь, самая давняя — кв. 20, 90,2 м², с 01.10.2026 (19 дней)." in line


def test_the_line_reaches_the_message_and_the_page():
    from test_management_report_analytics import _full

    built = _full()
    built["sales"]["bookings"] = salesroom.booking_outcomes(
        _chat(), DEALS, "2026-10-24", "2026-10-18", "2026-10-24")
    for page in (report.render_text(built), report.render_html(built)):
        assert "Брони за неделю: из списка ушли 1 — 1 снята без сделки" in page
        assert "договорами стали 1 (50,0%)" in page
