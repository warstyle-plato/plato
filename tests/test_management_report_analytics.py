"""Сводка руководству — документ для решений: «Главное», графики, динамика.

«А где графики? Аналитика?» (владелец, 20.10.2026, о PDF из четырёх таблиц).
Первая страница — выводы простым языком, каждый с числом и источником,
посчитанные из тех же блоков; дальше блоки с графиками (встроенный SVG — одна
разметка для страницы и PDF) и динамикой к предыдущему периоду.

Запуск: python3 -m pytest tests/test_management_report_analytics.py -q
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_monthly_budget as monthly_budget  # noqa: E402
import developaid_project_notes as notes  # noqa: E402
import developaid_report_charts as charts  # noqa: E402
from test_management_report_funding import _rss_with_sources, _sales as _credit_sales  # noqa: E402
from test_management_report_model import PROJECT, _gpr_book, _project, budget_book  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _full() -> dict:
    _project()
    monitor.store_estimate(PROJECT, _rss_with_sources(), "2026-10-18")
    monitor.store_schedule_fact(PROJECT, _gpr_book({"1": 0.30, "2": 0.0}, cash=False),
                                "2026-10-02")
    monthly_budget.store_budget(PROJECT, budget_book(), "2026-10-02")
    _credit_sales()
    notes.add(PROJECT, "Арбитраж с подрядчиком", "Иск подан", "Иванов",
              at="2026-10-14T09:00:00+00:00")
    return report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")


def test_the_lag_and_its_change_over_the_period():
    built = _full()
    block = built["physical"]
    assert block["lag"] == pytest.approx(block["fact"] - block["plan"])
    assert block["lag_before"] == pytest.approx(block["fact_before"] - block["plan_before"])
    # Три ГПР-факта — три точки S-кривой, каждая со своим планом на дату.
    assert [p["day"] for p in block["series"]["fact"]] == [
        "2026-10-02", "2026-10-09", "2026-10-16"]
    first = block["series"]["fact"][0]
    assert first["plan"] < block["plan"]


def test_findings_carry_numbers_and_sources():
    built = _full()
    found = {item["topic"]: item for item in built["findings"]}
    assert list(found) == ["Стройка", "Люди на площадке", "Отстающие работы", "Срок",
                           "Бюджет месяца", "Продажи", "Финансирование", "Открытые вопросы"]
    assert "прогноз Монитора по темпу работ" == found["Срок"]["source"]
    lag = built["physical"]["lag"]
    assert f"отставание {report._pp(-lag)[1:]}" in found["Стройка"]["text"]
    assert "ГПР-факт от 16.10.2026" == found["Стройка"]["source"]
    assert "оплачено 200,0 млн ₽ из 400,0 млн ₽ (50,0%)" in found["Бюджет месяца"]["text"]
    assert "Выборка кредита за неделю — 48,0 млн ₽ (за предыдущий такой же период — " \
           "120,0 млн ₽)" in found["Финансирование"]["text"]
    assert "«Арбитраж с подрядчиком»" in found["Открытые вопросы"]["text"]
    # Нет данных — вывод говорит об этом, а не молчит.
    empty = report.build("Пусто", "week", "2026-10-18")
    assert {item["tone"] for item in empty["findings"]} == {"missing"}


def test_the_document_opens_with_findings_and_has_charts():
    built = _full()
    page = report.render_html(built)
    assert page.index("Главное за период") < page.index("<h2>Стройка</h2>")
    assert "pagebreak" in page[:page.index("<h2>Стройка</h2>")]
    titles = re.findall(r"<figcaption>([^<]+)</figcaption>", page)
    assert titles == [
        "Выполнение по графику работ: план и факт на дату каждого ГПР-факта",
        "Продажи нарастающим итогом по кварталам, сумма договоров",
        "Выборка кредита и эскроу нарастающим итогом по месяцам",
        "Бюджет на октябрь 2026: план и оплачено по статьям",
    ]
    # Числа графика — те же, что в таблице блока: столбец «Оплачено» стройки.
    budget = page[page.index("Бюджет на октябрь 2026"):]
    assert ">200,0<" in budget and ">400,0<" in budget
    text = report.render_text(built)
    assert text.index("<b>Главное</b>") < text.index("<b>Стройка</b>")
    assert "п. п.." not in text and "п. п.." not in page


def test_charts_survive_missing_data():
    built = report.build("Пусто", "week", "2026-10-18")
    assert "<svg" not in report.render_html(built)
    assert charts.line_chart("t", [], [], "%") == ""
    assert charts.bar_chart("t", ["a"], [{"name": "x", "values": [None]}], "%") == ""


def test_axis_ticks_cover_the_data():
    for high in (0.73, 412.5, 17, 1, 2_999):
        ticks = charts._ticks(0, high)
        assert ticks[0] <= 0 and ticks[-1] >= high, (high, ticks)


REPORT = """Добрый день.
1. СПМ : Итр- 3чел., Рабочие - 6 чел.
2. НУР:ИТР- 11чел.;
Рабочие - 54чел.;
3. Клодо ( кладка) - Итр- 2 чел.Рабочие - 12чел.
По работам:
1. НУР: Корпус 1 монолит
"""


def test_people_on_site_from_the_bots_reports():
    import developaid_monitor_daily as daily

    _full()
    for day in ("2026-10-06", "2026-10-07", "2026-10-13", "2026-10-15"):
        daily.store_daily_report(PROJECT, REPORT, day)
    daily.store_daily_report(PROJECT, REPORT.replace("54чел", "24чел"), "2026-10-16")
    got = report.crew(PROJECT, "week", "2026-10-18")
    # Три отчёта за неделю: 72, 72, 42 рабочих; дни без отчёта не нули.
    assert got["now"]["days"] == 3
    assert got["now"]["workers_avg"] == pytest.approx((72 + 72 + 42) / 3)
    assert got["now"]["workers_max"] == 72
    assert got["previous"]["days"] == 2
    assert got["previous"]["workers_avg"] == pytest.approx(72)
    nur = next(row for row in got["by_contractor"] if "НУР" in row["name"])
    assert nur["workers_avg"] == pytest.approx((54 + 54 + 24) / 3)
    points = {p["day"]: p["workers"] for p in got["series"]}
    assert points["2026-10-14"] is None and points["2026-10-16"] == 42
    built = report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    found = {item["topic"]: item for item in built["findings"]}
    assert "В среднем 62 рабочих" in found["Люди на площадке"]["text"]
    assert "в предыдущий такой же период — 72 (−14%)" in found["Люди на площадке"]["text"]
    page = report.render_html(built)
    assert "Рабочих на площадке по дням" in page
    assert "Плановой численности в графике работ нет" in page


def test_no_reports_is_a_reason_not_zero():
    _full()
    got = report.crew(PROJECT, "week", "2026-10-18")
    assert got["state"] == "missing"
    assert "отчёты со стройки не приходили" in got["reason"].lower()


def test_breakdown_by_works():
    built = _full()
    breakdown = built["physical"]["breakdown"]
    # Обе работы отстают: «Фасад» (40% при плане ~54%) сильнее «Монолита».
    names = [row["name"] for row in breakdown["laggards"]]
    assert names[0] == "Фасад"
    assert breakdown["laggards"][0]["lag"] < breakdown["laggards"][1]["lag"]
    found = {item["topic"]: item for item in built["findings"]}
    assert found["Отстающие работы"]["text"].startswith("Больше всего отстают: Фасад (Корпус 2)")


def test_a_work_without_growth_is_flagged():
    _project()
    # Неделя назад и сейчас у «Монолита» 55% — прироста нет при идущем плане.
    monitor.store_schedule_fact(PROJECT, _gpr_book({"1": 0.55, "2": 0.30}, cash=False),
                                "2026-10-23")
    built = report.build(PROJECT, "week", "2026-10-25")
    stalled = built["physical"]["breakdown"]["stalled"]
    assert [row["name"] for row in stalled] == ["Монолит"]
