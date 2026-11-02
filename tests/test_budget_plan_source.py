"""План месяца сводки — из того бюджета, который назван, а не молча из другого.

Владелец (02.11.2026): «Почему тут остаётся 27 млн план? Загрузил вот этот
бюджет октября из файла». Файл той формы читается верно (план коммерции
октября — сумма её статей); план шёл из другого места: лист не «П-Ф»,
прежняя версия тех же месяцев с более поздней датой, файл с более поздним
периодом. Решение владельца: план месяца — из файла, загруженного последним;
ошибочный файл убирают кнопкой. Данные — синтетика той же формы, не данные
проекта.

Запуск: python3 -m pytest tests/test_budget_plan_source.py -q
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_monthly_budget as monthly_budget  # noqa: E402

M = 1_000_000.0
PROJECT = "Синтетика"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _fill(sheet, october_commercial: float) -> None:
    """Форма файла: месяцы в строке 4 (E, H, «Итого» в K), в строке 5 по три
    колонки ПЛАН / ФАКТ / Отклонение абс.; факт второго месяца пуст."""
    for column, name in ((5, "Сентябрь 2026"), (8, "Октябрь 2026"), (11, "Итого")):
        sheet.cell(row=4, column=column, value=name)
        for shift, sub in enumerate(("ПЛАН", "ФАКТ", "Отклонение абс.")):
            sheet.cell(row=5, column=column + shift, value=sub)
    # (имя, план сентября, факт сентября, план октября); отклонение = план − факт.
    rows = [("Стоимость строительства и проектирования", 200, 150, 400),
            ("Содержание службы заказчика", 6, 6, 8),
            ("Коммерческие расходы", 40, 14, october_commercial),
            ("Расходы на персонал отдела продаж (КС) - Группа", None, None, None),
            ("Расходы отдела продаж на содержание офиса (КС) - Группа", 4, 1, 5),
            ("Реклама и PR (КС) - Группа", 16, 6, 15),
            ("Расходы на продажу (КС) - Группа", 20, 7, october_commercial - 20),
            ("Брокерские (КС)", 19, 7, october_commercial - 21)]
    for r, (name, plan, fact, october) in enumerate(rows, 6):
        sheet.cell(row=r, column=1, value=name)
        for column, value in ((5, plan), (6, fact), (8, october)):
            if value is not None:
                sheet.cell(row=r, column=column, value=-value * M)
        if plan is not None:
            sheet.cell(row=r, column=7, value=(plan - fact) * M)
            sheet.cell(row=r, column=10, value=october * M)


def budget(october_commercial: float = 40, decoy: float | None = None) -> bytes:
    book = Workbook()
    first = book.active
    if decoy is not None:
        # Впереди — прежняя версия на другом листе: её план читать нельзя.
        first.title = "Свод"
        _fill(first, decoy)
        first = book.create_sheet("П-Ф")
    else:
        first.title = "П-Ф"
    _fill(first, october_commercial)
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def test_the_october_plan_is_the_sum_of_its_articles():
    parsed = monthly_budget.read_budget(budget(40))
    october = parsed["months"]["2026-10-01"]
    assert october["commercial"]["plan"] == pytest.approx(40 * M)
    assert october["commercial"]["fact"] is None  # колонка факта пуста — не ноль
    commercial = [key for key, item in monthly_budget._ARTICLE.items()
                  if item["line"] == "commercial"]
    assert sum(october["articles"][key]["plan"] or 0 for key in commercial
               if key in october["articles"]) == pytest.approx(40 * M)
    # Отклонение сентября (26) не читается планом октября.
    assert october["commercial"]["plan"] != pytest.approx(26 * M)


def test_the_plan_fact_sheet_is_taken_by_its_name():
    parsed = monthly_budget.read_budget(budget(40, decoy=27))
    assert parsed["sheet"] == "П-Ф"
    assert parsed["months"]["2026-10-01"]["commercial"]["plan"] == pytest.approx(40 * M)


def _later_budget(commercial: float) -> bytes:
    """Файл «октябрь–ноябрь»: период кончается позже, чем у «сентябрь–октябрь»."""
    book = Workbook()
    sheet = book.active
    sheet.title = "П-Ф"
    for column, name in ((5, "Октябрь 2026"), (8, "Ноябрь 2026")):
        sheet.cell(row=4, column=column, value=name)
        sheet.cell(row=5, column=column, value="ПЛАН")
        sheet.cell(row=5, column=column + 1, value="ФАКТ")
    for r, (name, value) in enumerate((("Стоимость строительства и проектирования", 392),
                                       ("Содержание службы заказчика", 0),
                                       ("Коммерческие расходы", commercial)), 6):
        sheet.cell(row=r, column=1, value=name)
        sheet.cell(row=r, column=5, value=-value * M)
        sheet.cell(row=r, column=8, value=-value * M)
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def _october() -> float:
    return monthly_budget._plan(PROJECT, "2026-10-01", "2026-11-02")["plan"]["commercial"]


def test_the_last_uploaded_file_gives_the_plan():
    # Решение владельца (02.11.2026): «брать последний» — загруженный последним,
    # а не тот, где дата среза в имени позже или период кончается позже.
    monthly_budget.store_budget(PROJECT, budget(27), "2026-11-01")
    monthly_budget.store_budget(PROJECT, _later_budget(27), "2026-10-20")
    monthly_budget.store_budget(PROJECT, budget(40), "2026-10-18")
    assert _october() == pytest.approx(40 * M)
    # Ноябрь есть только в файле «октябрь–ноябрь» — он берётся оттуда.
    november = monthly_budget._plan(PROJECT, "2026-11-01", "2026-11-02")
    assert november["plan"]["commercial"] == pytest.approx(27 * M)
    listed = monthly_budget.list_budgets(PROJECT)
    supplies = {item["name"]: item["supplies"] for item in listed["files"]}
    assert supplies == {"2026-10-18_2026-09_2026-10.xlsx": ["2026-09", "2026-10"],
                        "2026-10-20_2026-10_2026-11.xlsx": ["2026-11"],
                        "2026-11-01_2026-09_2026-10.xlsx": []}
    assert [item["name"] for item in listed["files"]][0] == "2026-10-18_2026-09_2026-10.xlsx"


def test_a_wrong_upload_is_removed_and_can_be_restored():
    monthly_budget.store_budget(PROJECT, budget(40), "2026-10-18")
    monthly_budget.store_budget(PROJECT, budget(27), "2026-11-01")
    assert _october() == pytest.approx(27 * M)
    got = monthly_budget.remove_budget(PROJECT, "2026-11-01_2026-09_2026-10.xlsx")
    assert [item["name"] for item in got["removed"]] == ["2026-11-01_2026-09_2026-10.xlsx"]
    assert _october() == pytest.approx(40 * M)
    monthly_budget.restore_budget(PROJECT, "2026-11-01_2026-09_2026-10.xlsx")
    # Возвращённый файл встаёт на своё прежнее место по времени загрузки.
    assert _october() == pytest.approx(27 * M)
    with pytest.raises(FileNotFoundError):
        monthly_budget.remove_budget(PROJECT, "нет-такого.xlsx")
    with pytest.raises(ValueError):
        monthly_budget.remove_budget(PROJECT, "../../uploads.json")


def test_the_trend_note_names_the_budget_of_each_month():
    trend = [{"month": "2026-09-01", "plan_file": {"file": "2026-11-01",
                                                    "period": "2026-09–2026-10"}},
             {"month": "2026-10-01", "plan_file": {"file": "2026-10-20",
                                                    "period": "2026-10–2026-11"}}]
    assert report._plan_sources_words(trend) == (
        "План по месяцам взят из загруженных бюджетов: сентябрь 2026 — из бюджета "
        "от 01.11.2026 (сентябрь 2026–октябрь 2026); октябрь 2026 — из бюджета от "
        "20.10.2026 (октябрь 2026–ноябрь 2026).")
