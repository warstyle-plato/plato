"""Почти нулевой темп актов не растягивает РНВ на десятилетия.

На Кутузов Сити сводка показала прогноз РНВ 26.04.2045 — «на 6418 дн.
позже»: остаток работы делился на почти нулевой темп актов её статьи, и
прогноз одной работы, ушедший за горизонт, по сети уводил ввод. Решение
владельца (21.10.2026): такой темп не экстраполировать — работа «почти стоит»,
если по темпу закончилась бы позже трёх своих плановых длительностей после
плана; РНВ она числом не двигает, а называется отдельно как риск.

Правило одно для Монитора (слой темпа), сценариев и сводки:
`developaid_monitor_forecast.pace_finish`.

Запуск: python3 -m pytest tests/test_monitor_pace_does_not_divide_by_zero.py -q
"""
from __future__ import annotations

import datetime

import developaid_management_report as report
import developaid_monitor_forecast as forecast
import developaid_monitor_pace as pace

d = datetime.date
CUT = d(2026, 10, 21)

# Почти стоящая работа: принято 20 %, за три месяца актировали 0,37 % статьи
# в месяц — на старом коде это 216 месяцев, РНВ около 2044 года.
STALLED = {"id": "A", "name": "Демонтаж башенных кранов К-1,2", "object": "Корпус 1",
           "plan_start": "2026-03-01", "plan_finish": "2026-09-30",
           "rss_accepted_ratio": 0.20, "rss_act_cost_rate_3m": 0.0037}
# Обычное опоздание: темп есть, прогноз разумный — он и должен двигать РНВ.
LATE = {"id": "B", "name": "Фасад", "object": "Корпус 2",
        "plan_start": "2026-06-01", "plan_finish": "2027-03-31",
        "rss_accepted_ratio": 0.30, "rss_act_cost_rate_3m": 0.06}


def _pm():
    task = {"predecessors": [], "free_float_days": 0, "total_float_days": 0}
    return {"known": True, "rnv_id": "R", "tasks": {
        "A": {**task, "id": "A", "name": STALLED["name"], "start": d(2026, 3, 1),
              "finish": d(2026, 9, 30), "duration_days": 213},
        "B": {**task, "id": "B", "name": "Фасад", "start": d(2026, 6, 1),
              "finish": d(2027, 3, 31), "duration_days": 303},
        "R": {**task, "id": "R", "name": "Получение РНВ", "start": d(2027, 9, 30),
              "finish": d(2027, 9, 30), "duration_days": 0,
              "predecessors": [{"id": "A", "type": "FS", "lag_days": 0},
                               {"id": "B", "type": "FS", "lag_days": 0}]},
    }}


def test_a_near_zero_pace_is_not_extrapolated():
    finish, method = forecast.pace_finish(dict(STALLED), CUT)
    assert (finish, method) == (None, "stalled_pace")
    assert pace._status(dict(STALLED), CUT, None) == "ПОЧТИ СТОИТ: ТЕМП НЕ ЭКСТРАПОЛИРУЕТСЯ"
    # Обычное опоздание по-прежнему считается числом.
    late, how = forecast.pace_finish(dict(LATE), CUT)
    assert how == "rolling_3m_acts" and d(2027, 4, 1) < late < d(2028, 1, 1)


def test_the_rnv_is_not_pulled_to_2044_and_the_stalled_work_is_named(monkeypatch):
    monkeypatch.setattr(pace.schedule_graph, "_load_pm", lambda _p: _pm())
    rows = [dict(STALLED), dict(LATE)]
    view = {"schedule": {"rows": rows, "management": []},
            "dashboard": {"schedule": {"approved_finish": "2027-09-30"}}}
    pace._apply_pace("Кутузов Сити", view, CUT)
    dash = view["dashboard"]["schedule"]
    rnv = d.fromisoformat(dash["forecast_finish"])
    assert rnv < d(2029, 1, 1), f"РНВ ушёл за горизонт: {rnv}"
    assert dash["rnv_delay_days"] < 365
    assert [item["name"] for item in dash["stalled"]] == [STALLED["name"]]
    assert "почти стоят" in dash["forecast_source"]
    by_id = {row["id"]: row for row in rows}
    # Почти стоящей работе не подставлен плановый срок — остановка не спрятана.
    assert not by_id["A"].get("pace_forecast_known")
    assert by_id["A"]["pace_status"] == "ПОЧТИ СТОИТ: ТЕМП НЕ ЭКСТРАПОЛИРУЕТСЯ"

    # Сценарный контур («Текущий темп») даёт ту же дату — правило одно.
    same = forecast.current_forecast({"schedule": {"rows": [dict(STALLED), dict(LATE)]}},
                                     _pm(), CUT)
    assert same["current_forecast_rnv"] == rnv
    assert [item["id"] for item in same["stalled"]] == ["A"]

    # Сводка говорит об этом словами, а не датой 2044 года.
    block = report.schedule(view["dashboard"])
    text = " ".join(item["text"] for item in report.findings({"kind": "week", "end": "2026-10-25", "schedule": block}))
    assert "почти стоят" in text and "Демонтаж башенных кранов К-1,2" in text
    assert "2044" not in text and "2045" not in text
