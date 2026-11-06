"""Канал брони: прямая или через агентов — и почему встреч больше, чем звонков.

Владелец (02.11.2026): «В анализе воронки продаж из чата есть нюанс:
получается встреч больше, чем звонков. Чем объясняется?» и «в переписке
менеджеров чётко стоит напротив брони „Агентская“. Значит это не по звонку».
Данные — синтетика: живой чат в публичный репозиторий не кладётся.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from market_search import salesroom  # noqa: E402
import developaid_management_report as report  # noqa: E402
from test_management_report_model import M, _contract  # noqa: E402


@pytest.mark.parametrize("mark, channel", [
    ("АГЕНТСКАЯ (Петров Пётр)", "agent"),
    ("агентская", "agent"),
    ("Агент. Иванов", "agent"),
    ("через агента", "agent"),
    ("АН Этажи (Петров Пётр)", "agent"),
    ("агентство Пример", "agent"),
    ("не агентская", "direct"),
    ("без агента", "direct"),
    ("прямая (Петров Пётр)", "direct"),
    ("собственная", "direct"),
    # Неизвестная пометка — не агентская, но и не «прямая»: канал не указан.
    ("(Петров Пётр)", ""),
    ("ипотека Сбер", ""),
    # «ан» строчными — часть обычного слова, не агентство.
    ("Иван Степанов, план", ""),
    ("ДАН", ""),
])
def test_the_channel_is_read_from_the_mark_at_the_booking(mark, channel):
    assert salesroom.booking_channel(f"квартира № 7, башня Тест, 3 этаж, 40 кв.м. {mark}") == channel


def _report(day: str, lots: list[str], calls: str = "ЦО за день - 1",
            meetings: str = "Встречи за день - 3") -> str:
    return (f"Отчёт за {day}.11.2026 г. {calls} {meetings} Брокер тур за день - 1 "
            f"ДДУ на регистрации: 0 Текущих броней: {len(lots)} " + " ".join(lots))


A1 = "- квартира № 101, башня Тест, 2 этаж, 40,0 кв.м. Агентская (Петров Пётр)"
A1_BARE = "- квартира № 101, башня Тест, 2 этаж, 40,0 кв.м. (Петров Пётр)"
D2 = "- квартира № 102, башня Тест, 3 этаж, 55,0 кв.м. (Петров Пётр)"
D3 = "- квартира № 103, башня Тест, 4 этаж, 60,0 кв.м. прямая (Сидорова Анна)"


def _chat(days: list[tuple[str, str]]) -> dict:
    read = None
    for day, text in days:
        read = salesroom.append_message(read, f"2026-11-{day}", "Дежурный", text)
    return read


def test_agent_bookings_leave_the_call_path_and_the_deal_inherits_the_channel():
    read = _chat([("01", _report("01", [])),
                  # Пометка стоит в первый день и пропала назавтра — канал
                  # хранится у брони, и договор его наследует.
                  ("02", _report("02", [A1, D2])),
                  ("03", _report("03", [A1_BARE, D2, D3])),
                  ("04", _report("04", [D2, D3]))])
    deals = [dict(_contract("2026-11-04", "Квартира", 40.0, 30 * M), unit="корп 1 кв.101")]
    got = salesroom.sales_funnel(read, deals, "2026-11-02", "2026-11-04")
    assert (got["direct"]["bookings"], got["direct"]["deals"]) == (2, 0)
    assert (got["agent"]["bookings"], got["agent"]["deals"]) == (1, 1)
    assert got["agent"]["broker_tours"] == 3.0
    # 102 без пометки: посчитана прямой, но названа отдельно.
    assert got["unmarked"] == 1
    assert any("у 1 новой брони канал не указан" in note for note in got["notes"])
    people = {row["author"]: row for row in got["managers"]}
    assert (people["Петров Пётр"]["agent_bookings"], people["Петров Пётр"]["direct_bookings"],
            people["Петров Пётр"]["agent_deals"]) == (1, 1, 1)
    line = report._managers_line({"pipeline": got})
    assert "Петров Пётр — 2 новые брони (прямых 1, через агентов 1) и 1 договор " \
           "(через агентов 1)" in line


def test_more_meetings_than_calls_is_explained_not_shown_as_a_percent():
    read = _chat([("01", _report("01", [])), ("02", _report("02", [D2]))])
    got = salesroom.sales_funnel(read, [], "2026-11-01", "2026-11-02")
    assert got["direct"]["calls"] == 2.0 and got["direct"]["meetings"] == 6.0
    assert got["direct"]["meetings_share"] is None and got["direct"]["more_meetings"]
    line = report._funnel_line({"pipeline": got}, "week")
    assert "300" not in line and "встречи 6 →" in line
    assert ("Встреч больше, чем целевых звонков: часть клиентов пришла без звонка "
            "(агенты, брокер-туры, повторные встречи).") in line
    figure = report._funnel_figure({"pipeline": got}, "week")
    assert "300" not in figure and "часть клиентов пришла без звонка" in figure


def test_fewer_meetings_than_calls_keeps_the_conversion():
    read = _chat([("01", _report("01", [], calls="ЦО за день - 4", meetings="Встречи за день - 2"))])
    got = salesroom.sales_funnel(read, [], "2026-11-01", "2026-11-01")
    assert got["direct"]["meetings_share"] == 0.5 and not got["direct"]["more_meetings"]
    assert got["more_meetings_text"] == ""


def test_reports_without_a_calls_line_are_named_with_dates():
    read = _chat([("01", _report("01", [])),
                  ("02", _report("02", [D2], calls="Звонки: были")),
                  ("03", _report("03", [D2], calls="", meetings="")),
                  ("04", _report("04", [D2]))])
    got = salesroom.sales_funnel(read, [], "2026-11-01", "2026-11-04")
    assert got["gaps"] == {"calls": ["2026-11-02", "2026-11-03"], "meetings": ["2026-11-03"]}
    notes = "; ".join(got["notes"])
    assert "в 2 из 4 дневных отчётов строка целевых звонков не распознана (02.11, 03.11)" in notes
    assert "в 1 из 4 дневных отчётов строка встреч не распознана (03.11)" in notes
    assert "строка целевых звонков не распознана" in report._managers_line({"pipeline": got})
