"""Ввод к эскроу — утверждённый, прогноз Монитора — отдельной строкой с работой.

Владелец, 27.10.2026: «Откуда в сводке взят ввод этот? Ввод в сентябре 2027».
Сводка считала эскроу к прогнозу Монитора по темпу работ (15.12.2028), а
утверждённый ввод — сентябрь 2027. Решение: «Ввод — утверждённый, прогноз
отдельно»:
- таблица эскроу по кварталам и «Покрытие кредита эскроу к вводу» — к
  утверждённому сроку; прогноз таблицу не удлиняет;
- прогноз — строкой рядом: «по темпу работ ввод может сдвинуться на …» с
  работой, которая тянет срок, и вторым числом покрытия к этой дате;
- работу называет Монитор следом по той же сети, что дала прогноз;
- отдельного покрытия «к раскрытию» нет: покрытие одно — вывод таблицы
  погашения НКЛ.

Данные сводки: накоплено 65 млн ₽ на октябрь 2026, рассрочка 5 млн ₽, новые
продажи 50/3 млн ₽ в месяц; кредит по плану 100 млн ₽, погашение с февраля 2027
(раскрытие — январь 2027). Ввод уехал на 30.06.2027 — рассрочку гасят к нему:
65 + 5 + 8 × 50/3 = 203,3 млн ₽ (своего покрытия у этой строки нет).

Запуск: python3 -m pytest tests/test_the_commissioning_is_approved_and_the_forecast_apart.py -q
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
import developaid_monitor_pace as pace  # noqa: E402
from test_management_report_funding import _isolated, _project, _sales  # noqa: E402,F401
from test_management_report_model import M, PROJECT  # noqa: E402

DRIVER = {"id": "A", "name": "Фасады", "object": "Корпус 2", "rss_codes": ["2.2.2.6"],
          "plan_finish": "2026-10-31", "forecast_finish": "2027-06-30", "progress": 0.12,
          "rnv_delay_days": 212}


def _built(monkeypatch, schedule, fresh: bool = True):
    if fresh:
        _project()
        _sales()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}, "schedule": schedule}})
    return report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")


def _late(monkeypatch, approved="2026-11-30", fresh: bool = True):
    return _built(monkeypatch, {"approved_finish": approved, "forecast_finish": "2027-06-30",
                                "rnv_delay_days": 212, "driver": DRIVER}, fresh)


def test_the_escrow_is_counted_to_the_approved_date(monkeypatch):
    funding = _late(monkeypatch)["funding"]
    at = funding["escrow"]["queues"][0]["at_commissioning"]
    assert (at["date"], at["source"]) == ("2026-11-30", "утверждённый срок")
    assert at["keeping_escrow"] == pytest.approx((65 + 5 + 50 / 3) * M)
    rows = funding["escrow_track"]["rows"]
    # Квартал ввода — утверждённого; прогноз (2027 Q2) таблицу не удлиняет.
    assert [row["quarter"] for row in rows] == ["2026 Q3", "2026 Q4", "2027 Q1"]
    assert rows[1]["marks"] == ["ввод 30.11.2026"]


def test_the_forecast_is_told_apart_with_the_work_that_drives_it(monkeypatch):
    built = _late(monkeypatch)
    later = built["funding"]["escrow"]["queues"][0]["at_forecast"]
    assert later["keeping_escrow"] == pytest.approx((65 + 5 + 8 * 50 / 3) * M)
    assert later["credit"] == pytest.approx(100 * M) and later["credit_at"] == "2027-01"
    assert later["keeping_coverage"] == pytest.approx(2.0333, abs=1e-4)

    text = report.render_text(built)
    assert ("По темпу работ ввод может сдвинуться на 30.06.2027 (прогноз Монитора) — срок "
            "тянет работа «Фасады» (Корпус 2; статья сметы 2.2.2.6): принято 12 % объёма, "
            "по нынешнему темпу закончится 30.06.2027 вместо 31.10.2026 по плану.") in text, text
    # Без своего покрытия: покрытие в сводке одно — вывод таблицы погашения
    # (владелец, 27.10.2026: «три разных покрытия»).
    assert ("Если ввод сдвинется, к 30.06.2027 по прогнозу на эскроу будет "
            "203,3 млн ₽.") in text, text
    assert "2,03×" not in text

    page = report.render_html(built)
    assert "срок тянет работа «Фасады»" in page and "2,03×" not in page

    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert "Срок тянет работа «Фасады» (Корпус 2; статья сметы 2.2.2.6)" in found["Срок"]


def test_no_forecast_line_when_the_forecast_is_not_later(monkeypatch):
    built = _built(monkeypatch, {"approved_finish": "2026-11-30",
                                 "forecast_finish": "2026-11-30", "rnv_delay_days": 0})
    assert built["funding"]["commissioning_shift"] is None
    assert built["funding"]["escrow"]["queues"][0]["at_forecast"] is None
    assert "ввод может сдвинуться" not in report.render_text(built)


def test_no_separate_cover_at_disclosure(monkeypatch):
    """Покрытие «к раскрытию» и пояснение, почему раскрытие раньше ввода, ушли
    вместе с отдельной таблицей покрытия: покрытие одно — вывод таблицы
    погашения НКЛ (владелец, 27.10.2026)."""
    built = _late(monkeypatch, approved="2027-02-28")
    for said in (report.render_text(built), report.render_html(built)):
        assert "к раскрытию" not in said
        assert "Погашение кредита из эскроу по плану финмодели начинается" not in said


def test_the_monitor_names_the_work_that_drives_the_forecast(monkeypatch):
    """Две опаздывающие работы перед вехой ввода: тянет та, что позже, — её
    находит след от вехи назад по той же сети, что дала прогноз."""
    d = datetime.date
    cut = d(2026, 8, 22)
    task = {"free_float_days": 0, "total_float_days": 0}
    pm = {"known": True, "rnv_id": "R", "tasks": {
        "A": {"id": "A", "name": "Фасады", "start": d(2026, 7, 1), "finish": d(2026, 12, 31),
              "duration_days": 183, "predecessors": [], **task},
        "B": {"id": "B", "name": "Кровля", "start": d(2026, 7, 1), "finish": d(2026, 12, 31),
              "duration_days": 183, "predecessors": [], **task},
        "R": {"id": "R", "name": "Ввод", "start": d(2027, 1, 1), "finish": d(2027, 1, 1),
              "duration_days": 0, "predecessors": [{"id": "A", "type": "FS", "lag_days": 0},
                                                   {"id": "B", "type": "FS", "lag_days": 0}],
              **task},
    }}
    monkeypatch.setattr(pace.schedule_graph, "_load_pm", lambda _p: pm)
    rows = [
        {"id": "A", "name": "Фасады", "object": "Корпус 2", "code": "2.2.2.6",
         "plan_start": "2026-07-01", "plan_finish": "2026-12-31",
         "rss_accepted_ratio": 0.25, "rss_act_cost_rate_3m": 0.05},
        {"id": "B", "name": "Кровля", "plan_start": "2026-07-01", "plan_finish": "2026-12-31",
         "rss_accepted_ratio": 0.5, "rss_act_cost_rate_3m": 0.1},
        {"id": "R", "name": "Ввод", "plan_start": "2027-01-01", "plan_finish": "2027-01-01"},
    ]
    view = {"cut": "2026-08-22", "schedule": {"rows": rows, "management": [],
                                               "approved_end": "2027-01-01"},
            "dashboard": {"schedule": {"approved_finish": "2027-01-01"}}}
    pace._apply_pace("Проект", view, cut)
    block = view["dashboard"]["schedule"]
    driver = block["driver"]
    assert driver["name"] == "Фасады" and driver["object"] == "Корпус 2"
    assert driver["rss_codes"] == ["2.2.2.6"] and driver["progress"] == 0.25
    assert driver["rnv_delay_days"] == block["rnv_delay_days"] > 0
    # Работа тянет ровно на свой сдвиг: веха ввода стоит сразу за ней.
    assert driver["forecast_finish"] == block["forecast_finish"]
    assert driver["plan_finish"] == "2026-12-31"


def test_the_monitor_names_nobody_when_the_forecast_is_on_time(monkeypatch):
    d = datetime.date
    pm = {"known": True, "rnv_id": "", "tasks": {
        "A": {"id": "A", "name": "Фасады", "start": d(2026, 7, 1), "finish": d(2026, 12, 31),
              "duration_days": 183, "predecessors": [], "free_float_days": 0,
              "total_float_days": 0}}}
    monkeypatch.setattr(pace.schedule_graph, "_load_pm", lambda _p: pm)
    rows = [{"id": "A", "name": "Фасады", "plan_start": "2026-07-01", "plan_finish": "2026-12-31",
             "rss_accepted_ratio": 0.8, "rss_act_cost_rate_3m": 0.35}]
    view = {"cut": "2026-08-22", "schedule": {"rows": rows, "management": []},
            "dashboard": {"schedule": {"approved_finish": "2026-12-31"}}}
    pace._apply_pace("Проект", view, d(2026, 8, 22))
    assert view["dashboard"]["schedule"]["driver"] is None


def test_the_trace_goes_back_to_the_work_whose_own_delay_starts_the_chain():
    """«Фасады» опаздывают сами, «Отделка» сдвинута ими, ввод — «Отделкой»:
    тянет «Фасады». Если «Отделка» опаздывает сама сильнее — тянет она."""
    import developaid_monitor_schedule_graph as graph

    d = datetime.date
    task = {"free_float_days": 0, "total_float_days": 0}
    pm = {"known": True, "rnv_id": "R", "tasks": {
        "A": {"id": "A", "name": "Фасады", "start": d(2026, 7, 1), "finish": d(2026, 12, 31),
              "duration_days": 183, "predecessors": [], **task},
        "B": {"id": "B", "name": "Отделка", "start": d(2027, 1, 1), "finish": d(2027, 3, 1),
              "duration_days": 59, "predecessors": [{"id": "A", "type": "FS", "lag_days": 0}],
              **task},
        "R": {"id": "R", "name": "Ввод", "start": d(2027, 3, 1), "finish": d(2027, 3, 1),
              "duration_days": 0, "predecessors": [{"id": "B", "type": "FS", "lag_days": 0}],
              **task},
    }}
    pushed = graph._propagate(pm, {"A": d(2027, 6, 30)})
    assert pushed["B"]["inherited_delay_days"] > 0
    assert graph.driver(pushed, "R") == "A"
    own = graph._propagate(pm, {"A": d(2027, 1, 31), "B": d(2027, 12, 31)})
    assert graph.driver(own, "R") == "B"
    assert graph.driver(graph._propagate(pm, {}), "R") is None
