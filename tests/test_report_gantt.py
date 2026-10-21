"""График сводки по корпусам: укрупнённые статьи, план, прогноз и РНВ.

«График как в мониторе, но с укрупнёнными статьями по корпусам с планом и
прогнозом окончания работ и РНВ» (владелец, 20.10.2026).

Проверки:
- корпус определяется тем же правилом, что в Ганте Монитора;
- статья корпуса — работы одной статьи РСС: план — от первого начала до
  последнего окончания, прогноз — по работам с известным темпом;
- неизвестный прогноз — «нет прогноза», а не плановая дата;
- сводка берёт дерево из среза Монитора: сроки корпусов те же, что у него;
- в документе — SVG с полосами плана и прогноза и вехой РНВ, в сообщении —
  строка на корпус.

Запуск: python3 -m pytest tests/test_report_gantt.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import PROJECT, _project

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_report_gantt as gantt


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _task(name, obj, start, finish, forecast=None, known=False):
    return {"level": "task", "name": name, "object": obj, "plan_start": start,
            "plan_finish": finish, "forecast_finish": forecast or finish,
            "pace_forecast_known": known}


def _rss(code, name, *tasks):
    return {"level": "rss", "code": code, "name": name, "children": list(tasks)}


TREE = [{"level": "control", "name": "Основные объекты", "children": [
    {"level": "detail", "name": "Подземная часть", "children": [
        _rss("2.2.1.4", "Каркас",
             _task("Монолит 1-5 эт", "Корпус 1", "2026-07-01", "2026-12-28", "2027-01-15", True),
             _task("Монолит 6-10 эт", "Корпус 1", "2026-08-01", "2027-02-01", "2027-02-20", True),
             _task("Монолит", "Корпус 2", "2026-07-01", "2026-11-30", "2026-11-20", True))]},
    {"level": "detail", "name": "Надземная часть", "children": [
        _rss("2.2.2.5", "Фасады",
             _task("Фасад", "корп. 1", "2027-01-10", "2027-05-30"),
             _task("Фасад", "Корпус 10", "2027-01-10", "2027-04-30"))]}]}]


def test_the_corpus_rule_is_the_monitor_one():
    from developaid_monitor_page import MONITOR_PAGE

    assert f"m=parts.match(/{gantt.CORPUS_PATTERN}/i)" in MONITOR_PAGE
    assert gantt.corpus_of({"object": "корп. 2", "name": "Фасад"}) == "Корпус 2"
    assert gantt.corpus_of({"object": "Наружные сети"}) == "Наружные сети"
    assert gantt.corpus_of({"name": "Охрана"}) == "Общие работы"


def test_articles_by_corpus_with_plan_and_pace_forecast():
    got = gantt.model(TREE)
    assert got["state"] == "ok"
    names = [corpus["name"] for corpus in got["corpora"]]
    assert names == ["Корпус 1", "Корпус 2", "Корпус 10"]  # естественный порядок
    first = got["corpora"][0]
    frame, facade = first["articles"]
    assert (frame["code"], frame["name"]) == ("2.2.1.4", "Каркас")
    assert (frame["plan_start"], frame["plan_finish"]) == ("2026-07-01", "2027-02-01")
    assert frame["forecast_finish"] == "2027-02-20" and frame["delta_days"] == 19
    # Фасад ещё не начат: прогноза нет, плановая дата его не подменяет.
    assert facade["forecast_known"] is False and facade["forecast_finish"] is None
    assert facade["delta_days"] is None
    # Корпус: план до конца фасада, прогноз — только по известной части.
    assert first["plan_finish"] == "2027-05-30" and first["forecast_partial"] is True
    # Опоздание корпуса — по статьям с прогнозом против их же плана: общий
    # прогноз (20.02) раньше общего плана (30.05) только из-за не начатого фасада.
    assert first["delta_days"] == 19
    second = got["corpora"][1]
    assert second["delta_days"] == -10


def test_svg_draws_plan_forecast_and_rnv():
    model = gantt.model(TREE)
    picture = gantt.svg(model, "2026-10-18", {"approved": "2027-06-30",
                                              "forecast": "2027-08-15", "delay_days": 46})
    assert picture.startswith("<svg") and picture.endswith("</svg>")
    assert picture.count('stroke-dasharray="4 2"') >= 6   # план — пунктир у каждой строки
    assert "РНВ (разрешение на ввод)" in picture and "+46 дн." in picture
    assert "нет прогноза" in picture and "сегодня" in picture
    assert "+19 дн." in picture
    without_plan = gantt.notes(model, {"forecast": "2027-08-15"})
    assert any("Утверждённой даты РНВ" in line for line in without_plan)
    lines = gantt.text_lines(model)
    assert lines[0].endswith("по известным — опоздание до 19 дн.")
    assert lines[1] == ("Корпус 2: окончание работ по графику 30.11.2026, прогноз "
                        "20.11.2026 (раньше на 10 дн.).")
    assert lines[2].endswith("прогноза пока нет.")


def test_empty_tree_is_a_named_gap():
    got = gantt.model([])
    assert got["state"] == "missing" and "графика" in got["reason"]
    assert gantt.svg(got) == ""


def test_the_report_takes_the_monitor_tree():
    _project()
    got = report.build(PROJECT, "week", "2026-10-18")
    block = got["gantt"]
    assert block["state"] == "ok"
    by_name = {corpus["name"]: corpus for corpus in block["corpora"]}
    assert set(by_name) == {"Корпус 1", "Корпус 2"}
    # Те же даты, что прогноз темпа Монитора по работам этих корпусов.
    assert by_name["Корпус 1"]["forecast_finish"] == "2027-01-15"
    assert by_name["Корпус 2"]["delta_days"] == 28
    page = report.render_html(got)
    assert "Сроки работ по корпусам" in page and 'class="chart gantt"' in page
    text = report.render_text(got)
    assert "Корпус 2: окончание работ по графику 29.11.2026, прогноз 27.12.2026 (+28 дн.)." in text
    found = [item for item in got["findings"] if item["topic"] == "Корпуса"]
    assert found and "Корпус 2" in found[0]["text"] and "28 дн." in found[0]["text"]
