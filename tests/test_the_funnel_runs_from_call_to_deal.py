"""Воронка продаж целиком — звонок, встреча, бронь, договор — и по менеджерам.

Владелец (24.10.2026): «Почему в воронке нет целевых звонков? Звонок — встреча
— бронь»; «и плюс статистика менеджеров». Формат — из живой выгрузки чата
отдела продаж: в старых отчётах «Целевые звонки - 4 шт.» (разбор искал только
«целевых звонков» и ступень терял), в новых «ЦО за день - 1»; отчёт за день —
сводка отдела, пишет её дежурный; менеджер стоит в скобках у самой брони.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from market_search import cabinet, salesroom, sales_store  # noqa: E402
import developaid_management_report as report  # noqa: E402
from test_management_report_model import M, _contract  # noqa: E402

OLD = ("Отчёт за {day}.09.2026 г. Сделки на регистрации: 0 шт. Текущих броней: 0 шт. "
       "Встреч в офисе - 2 1. Брокер тур Trendagent. Целевые звонки - 4 шт.")


def _new(day: str, calls: int, meetings: int, lots: list[str]) -> str:
    return (f"Отчёт за {day}.10.2026 г. Количество ЦО: ЦО за день - {calls} ЦО за месяц -27 "
            f"Встречи: Встречи за день - {meetings} Встречи за месяц - 23 "
            f"ДДУ на регистрации: 0 Текущих броней: {len(lots)} " + " ".join(lots))


ROOM_20 = ("- квартира № 20, башня Гармония, 5 этаж, 90,2 кВ.м. Цена лота 64 913 192 р. "
           "АГЕНТСКАЯ (Помазанова Александра)")
ROOM_41 = "- квартира № 41, башня Гармония, 11 этаж, {area} кВ.м. АГЕНТСКАЯ (Мария Вольпи)"
ROOM_63 = "- квартира № 63, башня Сфера, 3 этаж, 61,9 кВ.м. (Вольпи Мария)"


def _chat() -> dict:
    read = None
    # Дежурные разные — автор сообщения не менеджер сделки.
    for day, author, text in (
            ("19", "Стас Б", _new("19", 2, 1, [ROOM_20])),
            ("20", ".", _new("20", 1, 3, [ROOM_20, ROOM_41.format(area="126")])),
            ("21", "Андрей", _new("21", 0, 1, [ROOM_20, ROOM_41.format(area="121.1"), ROOM_63])),
            ("22", ".", _new("22", 3, 2, [ROOM_20, ROOM_41.format(area="121.1")]))):
        read = salesroom.append_message(read, f"2026-10-{day}", author, text)
    return read


DEALS = [dict(_contract("2026-10-22", "Квартира", 61.9, 40 * M), unit="корп 2 кв.63"),
         dict(_contract("2026-10-21", "Квартира", 50.0, 30 * M), unit="корп 1 кв.5")]


def test_the_old_wording_of_calls_is_counted():
    read = salesroom.append_message(None, "2026-09-01", "Мария Вольпи", OLD.format(day="01"))
    got = salesroom.funnel(read, "2026-09-01", "2026-09-30")
    assert got["calls"] == 4.0 and got["meetings"] == 2.0


def test_the_funnel_goes_call_meeting_booking_deal():
    got = salesroom.sales_funnel(_chat(), DEALS, "2026-10-20", "2026-10-26")
    # Звонки и встречи — за 20–22.10; новые брони — 41 и 63 (20 была в первом
    # отчёте); 41 при уточнённой площади — та же бронь; договоры по подписанию — 2.
    assert got["total"] == {"calls": 4.0, "meetings": 6.0, "bookings": 2, "deals": 2,
                            "meetings_share": 1.5, "bookings_share": 2 / 6, "deals_share": 1.0}
    line = report._funnel_line({"pipeline": got, "funnel": salesroom.funnel(
        _chat(), "2026-10-20", "2026-10-26")}, "week")
    assert line.startswith("Воронка за неделю: целевые звонки 4 → встречи 6 (150,0%) → "
                           "новые брони 2 (33,3%) → договоры 2 (100,0%).")


def test_a_missing_stage_is_named_not_skipped():
    words = report._stage_words({"calls": None, "meetings": 3.0, "bookings": 1, "deals": 0})
    assert words[0] == "целевые звонки — в отчётах не названы"


def test_managers_come_from_the_booking_not_from_the_author():
    got = salesroom.sales_funnel(_chat(), DEALS, "2026-10-20", "2026-10-26")
    names = {row["author"]: row for row in got["managers"]}
    # «Мария Вольпи» и «Вольпи Мария» — один человек; дежурные («.», «Андрей»,
    # «Стас Б») менеджерами не стали.
    assert set(names) == {"Мария Вольпи"}
    assert (names["Мария Вольпи"]["bookings"], names["Мария Вольпи"]["deals"]) == (2, 1)
    assert any("только по отделу" in note for note in got["notes"])
    assert any("договоров без брони в отчётах чата — 1" in note for note in got["notes"])
    line = report._managers_line({"pipeline": got})
    assert line.startswith("По менеджерам (по имени у брони): Мария Вольпи — новые брони 2, "
                           "договоры 1.")


def test_a_corrected_area_does_not_split_a_booking():
    got = salesroom.booking_outcomes(_chat(), DEALS, "2026-10-24", "2026-10-20", "2026-10-26")
    gone = {item["apartment"]: item["outcome"] for item in got["period"]}
    # 41 держится (126 → 121,1 м² — та же квартира), 63 ушла в договор.
    assert gone == {"63": "deal"}
    assert sorted(lot["apartment"] for lot in got["held"]) == ["20", "41"]


def test_the_report_and_the_cabinet_read_one_count(tmp_path):
    sales_store.save(sales_store.default_dir(), "ЖК Воронка", {
        "contracting": {"project": "ЖК Воронка", "missing": [], "rows": DEALS},
        "salesroom": _chat()}, "test.xlsx")
    block = report.sales("ЖК Воронка", "week", "2026-10-25")
    assert block["pipeline"] == salesroom.sales_funnel(_chat(), DEALS, "2026-10-19", "2026-10-25")
    api = (os.path.join(os.path.dirname(os.path.dirname(__file__)), "market_search", "api.py"))
    assert "salesroom.sales_funnel(room, contracts.get(\"rows\")" in open(api, encoding="utf-8").read()


def test_the_cabinet_draws_the_funnel_and_the_managers(tmp_path):
    import importlib

    import pytest

    play = pytest.importorskip("playwright.sync_api")
    import browser_launch

    got = importlib.import_module("test_contracting_summary")._summary()
    pipe = salesroom.sales_funnel(_chat(), DEALS, "2026-10-20", "2026-10-26")
    pipe["managers"].append(dict(pipe["managers"][0], author="Кочеткова Мария"))
    got["salesroom"] = {"months": [{"month": "2026-10", "meetings_per_day": 1.5,
                                    "calls_per_day": 1.0, "bookings_at_once": 2.0}],
                        "topics": [], "objections": [], "asked": {}, "rivals": [],
                        "bands": [], "notes": [],
                        "pipeline": dict(pipe, first="2026-10-20", last="2026-10-26")}
    file = tmp_path / "cabinet.html"
    file.write_text(cabinet.cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test"),
                    encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            text = tab.evaluate("(d)=>{renderSales(d); return salesPrintHtml()}", got)
        finally:
            browser.close()
    assert "Воронка и менеджеры с 2026-10-20 по 2026-10-26" in text
    assert "Целевые звонки" in text and "Новые брони" in text
    assert "Отдел продаж" in text and "Мария Вольпи" in text and "Кочеткова Мария" in text
    assert "только по отделу" in text
