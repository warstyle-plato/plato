"""«Утверждённый бюджет» говорит, из чего он сложен и откуда взят.

Владелец (02.11.2026) не понимал, откуда берётся число на плитке: оно
показывало только главы сметы по карте «статьи_БДДС», а раздел
административных расходов с налогами, разнесённый по главам, видно не было.
Теперь у плитки есть подсказка «i»: разделы финмодели, налоги и проценты по
кредиту справкой (в бюджет не входят: «Налоги то зачем в бюджет включать»),
сверка «бюджет = ФАКТ + ПЛАН» и источник — имя файла и дата загрузки. Плашки
складываются: лимит банка (смета) = оплачено + остаток, бюджет = лимит + свои
деньги сверх сметы банка, и последнее разложено по разделам.

Все числа — синтетика.
"""
from __future__ import annotations

import datetime
import io
import os
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(__file__))

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_monitor_dashboard as dashboard  # noqa: E402

K = 1000.0
M = 1e6
# код: (название, ИТОГО, ФАКТ, ПЛАН) — в тысячах, как лист
ROWS = {
    "2.1": ("Приобретение проекта", 300, 300, 0),
    "2.1.1": ("Участок", 300, 300, 0),
    "2.2": ("Строительство", 1000, 400, 600),
    "2.2.1": ("Подготовка территории", 1000, 400, 600),
    "2.3": ("Коммерческие расходы", 100, 30, 70),
    "2.3.1": ("Реклама", 100, 30, 70),
    "2.4": ("Административно-хозяйственные расходы", 160, 60, 100),
    "2.4.1": ("Управление", 40, 20, 20),
    "2.4.5": ("Налоги", 120, 40, 80),
    "2.4.5.1": ("Налог на имущество", 70, 20, 50),
    "2.4.5.2": ("Земельный налог", 50, 20, 30),
    "3.1.4": ("Выплаты %% по кредитам и займам", 90, 10, 80),
}
CROSSWALK = [("2.1.1.1", "Участок", "1.1"), ("2.2.1.1", "Вырубка", "2.1"),
             ("2.3.1.1", "Реклама", "3.2"), ("2.4.1.1", "Управление", "2.6"),
             ("2.4.5.1.1", "Имущество", "2.6"), ("2.4.5.2.1", "Земля", "1.2")]


def _finmodel(rows: dict = ROWS) -> bytes:
    book = openpyxl.Workbook()
    book.active.title = "ОТЧЕТ"
    cf = book.create_sheet("cf_1_new")
    cf.cell(6, 9, "ИТОГО"), cf.cell(6, 10, "ФАКТ"), cf.cell(6, 11, "ПЛАН")
    cf.cell(5, 14, "план"), cf.cell(6, 14, datetime.datetime(2026, 11, 1))
    for r, (code, (name, total, fact, plan)) in enumerate(rows.items(), 7):
        cf.cell(r, 3, code), cf.cell(r, 4, name)
        cf.cell(r, 9, total), cf.cell(r, 10, fact), cf.cell(r, 11, plan)
        cf.cell(r, 14, plan)
    xw = book.create_sheet("статьи_БДДС")
    xw.cell(1, 7, "Код статьи"), xw.cell(2, 9, "Код РСС")
    for r, (bdds, name, est) in enumerate(CROSSWALK, 3):
        xw.cell(r, 7, bdds), xw.cell(r, 8, name), xw.cell(r, 9, est)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _read(tmp_path: Path, data: bytes) -> dict:
    path = tmp_path / "finance.xlsx"
    path.write_bytes(data)
    return dashboard._read_finance_baseline(path)


K_BUDGET = (300 + 1000 + 100 + 40) * K  # без налогов 2.4.5


def test_the_budget_leaves_the_taxes_and_the_interest_aside(tmp_path):
    got = _read(tmp_path, _finmodel())
    comp = got["budget_composition"]
    assert got["approved"] == pytest.approx(K_BUDGET)
    assert [item["code"] for item in comp["sections"]] == ["2.1", "2.2", "2.3", "2.4"]
    assert sum(item["total"] for item in comp["sections"]) == pytest.approx(got["approved"])
    assert comp["sections"][3]["total"] == pytest.approx(40 * K)
    assert comp["taxes"][0]["code"] == "2.4.5" and comp["taxes"][0]["total"] == pytest.approx(120 * K)
    assert comp["interest_outside"] == [{"code": "3.1.4", "name": "Выплаты %% по кредитам и займам",
                                         "total": pytest.approx(90 * K)}]
    # Налоги не попадают ни в главы, ни в оплаченное, ни в остаток.
    assert sum(got["approved_by_chapter"].values()) == pytest.approx(K_BUDGET)
    assert got["paid_at_baseline"] == pytest.approx(750 * K)
    assert got["completion_need_at_baseline"] == pytest.approx(690 * K)
    assert comp["fact"] + comp["plan"] == pytest.approx(got["approved"])

    lines = dashboard.budget_hint_lines({"budget_composition": comp}, report._rub)
    assert lines[0] == (
        "Утверждённый бюджет — сумма строк «ИТОГО» листа «cf_1_new» финмодели без налогов, "
        "1,4 млн ₽. По разделам: 2.1 «Приобретение проекта» — 300 000 ₽; 2.2 «Строительство» — "
        "1,0 млн ₽; 2.3 «Коммерческие расходы» — 100 000 ₽; 2.4 «Административно-"
        "хозяйственные расходы» — 40 000 ₽.")
    assert lines[1].startswith("Справочно: налоги («Налоги», 2.4.5) — 120 000 ₽ и проценты по "
                               "кредиту («Выплаты %% по кредитам и займам», 3.1.4) — 90 000 ₽ в бюджет "
                               "не входят.")
    assert lines[2] == ("Из бюджета уже оплачено по финмодели (ФАКТ) 750 000 ₽, осталось "
                        "оплатить (ПЛАН) 690 000 ₽; вместе — 1,4 млн ₽.")
    assert "не сохранились" in lines[3]


def test_a_book_whose_total_is_not_fact_plus_plan_is_named(tmp_path):
    rows = dict(ROWS)
    rows["2.3.1"] = ("Реклама", 110, 30, 70)
    comp = _read(tmp_path, _finmodel(rows))["budget_composition"]
    assert comp["difference"] == pytest.approx(10 * K)
    text = " ".join(dashboard.budget_hint_lines({"budget_composition": comp}, report._rub))
    assert "С бюджетом это расходится на 10 000 ₽" in text


def test_interest_inside_the_budget_is_not_called_absent(tmp_path):
    rows = dict(ROWS)
    rows["2.4.7"] = ("Проценты по займу", 5, 5, 0)
    comp = _read(tmp_path, _finmodel(rows))["budget_composition"]
    assert comp["interest_rows"] == ["2.4.7"]
    text = " ".join(dashboard.budget_hint_lines({"budget_composition": comp}, report._rub))
    assert "внутри бюджета есть строки с процентами — 2.4.7; они в сумму вошли" in text


def test_the_upload_keeps_the_file_name_and_the_day(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    assert monitor.finance_baseline_meta("demo") == {}
    monitor.replace_finance_baseline("demo", _finmodel(), "2026-10-23",
                                     file_name="C:\\Книги\\ФМ синтетика.xlsx")
    meta = monitor.finance_baseline_meta("demo")
    assert meta["file_name"] == "ФМ синтетика.xlsx"
    day = datetime.date.fromisoformat(meta["uploaded_at"][:10]).strftime("%d.%m.%Y")
    lines = dashboard.budget_hint_lines({"baseline_file": meta}, report._rub)
    assert lines == [f"Источник: файл «ФМ синтетика.xlsx», загружен {day}."]
    # Загрузка без имени — дата есть, имя названо отсутствующим, а не выдумано.
    monitor.replace_finance_baseline("demo", _finmodel(), "2026-10-24")
    lines = dashboard.budget_hint_lines({"baseline_file": monitor.finance_baseline_meta("demo")},
                                        report._rub)
    assert lines == [f"Источник: финансовая база загружена {day}; исходное имя файла при "
                     "загрузке не передано."]


# --- Плашки складываются: лимит = оплачено + остаток, бюджет = лимит + свои деньги.

SMETA = {"1": 250 * K, "2": 900 * K, "3": 80 * K}
PAID = {"1": {"total": 280 * K, "borrowed": 100 * K},   # по главе 1 оплачено больше сметы
        "2": {"total": 410 * K, "borrowed": 300 * K},   # реестр на 10 впереди «ФАКТ» книги
        "3": {"total": 30 * K, "borrowed": 20 * K}}


def _own(tmp_path):
    comp = _read(tmp_path, _finmodel())["budget_composition"]
    return comp, dashboard._own_money(comp, SMETA, PAID, ["1", "2", "3"],
                                      datetime.date(2026, 10, 20))


def test_limit_is_paid_plus_left_and_budget_is_limit_plus_own_money(tmp_path):
    comp, own = _own(tmp_path)
    assert own["matches"]
    assert own["limit"] == pytest.approx(1_230 * K)
    assert own["paid"] == pytest.approx(720 * K)
    assert own["left"] == pytest.approx(510 * K)
    assert own["limit"] == pytest.approx(own["paid"] + own["left"])
    assert own["left_by_chapter"] == {"1": pytest.approx(-30 * K), "2": pytest.approx(490 * K),
                                      "3": pytest.approx(50 * K)}
    assert own["need"] == pytest.approx(210 * K)
    assert own["budget"] == pytest.approx(own["limit"] + own["need"])
    rows = {row["section"]: row["amount"] for row in own["rows"]}
    # 210 = участок 30 + стройка 110 + коммерция 20 + административные 40 + даты 10
    assert rows == {"2.1": pytest.approx(30 * K), "2.2": pytest.approx(110 * K),
                    "2.3": pytest.approx(20 * K), "2.4": pytest.approx(40 * K)}
    assert own["dates"] == pytest.approx(10 * K)
    assert sum(rows.values()) + own["dates"] == pytest.approx(own["need"])
    # Первый месяц — водопад всех разделов против их глав: стройке не хватает в ноябре.
    assert own["from"] == "2026-11-01"

    lines = dashboard.own_money_lines(own, report._rub)
    assert lines[0].startswith("Утверждённый бюджет без налогов 1,4 млн ₽ минус лимит банка "
                               "1,2 млн ₽ — нужно своих денег сверх сметы банка 210 000 ₽, "
                               "первый месяц нехватки — ноябрь 2026.")
    assert "2.4 «Административно-хозяйственные расходы» — 40 000 ₽: в смете банка таких " \
           "расходов нет" in lines[1]
    assert "расхождение дат — 10 000 ₽: «ФАКТ» финмодели считает оплаты на дату книги, а " \
           "реестр РСС — на дату отчёта" in lines[1]


def test_a_forged_section_breaks_the_identity(tmp_path):
    comp, _ = _own(tmp_path)
    forged = {**comp, "total": comp["total"] + 5 * K}  # бюджет разошёлся с разделами
    own = dashboard._own_money(forged, SMETA, PAID, ["1", "2", "3"], datetime.date(2026, 10, 20))
    assert own["matches"] is False


def test_the_tiles_add_up_on_the_page(tmp_path, monkeypatch):
    from test_management_report_funding import PROJECT, _project

    comp, own = _own(tmp_path)
    funding = {
        "known": True, "need_basis": "model", "bank_limit": own["limit"],
        "paid_actual": own["paid"], "paid_borrowed": own["borrowed"],
        "bank_remaining": 540 * K, "reserve": 0.0, "approved": comp["total"],
        "approved_remaining": comp["plan"], "deficit_ladder": {"total": 130 * K},
        "additional_financing": 130 * K, "additional_financing_from": "2026-11-01",
        "budget_composition": comp, "own_money": own,
        "baseline_file": {"file_name": "ФМ синтетика.xlsx",
                          "uploaded_at": "2026-11-02T10:00:00+00:00"}}
    _project()
    monkeypatch.setattr(report, "_monitor_view",
                        lambda project, end: {"dashboard": {"funding": funding}})
    built = report.build(PROJECT, "week", "2026-10-18")
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert tiles["Утверждённый бюджет"]["value"] == report._rub(comp["total"])
    assert tiles["Утверждённый бюджет"]["note"] == (
        "по разделам финмодели 2.1, 2.2, 2.3, 2.4; без процентов по кредиту")
    assert "Источник: файл «ФМ синтетика.xlsx», загружен 02.11.2026." in \
        tiles["Утверждённый бюджет"]["hint"]
    assert tiles["Лимит банка"]["value"] == report._rub(own["limit"])
    assert tiles["Лимит банка"]["note"].startswith("смета банка: в неё засчитываются все оплаты")
    assert tiles["Оплачено с начала проекта"]["value"] == report._rub(own["paid"])
    assert tiles["Оплачено с начала проекта"]["note"] == (
        "из них кредитом 420 000 ₽, своими деньгами 300 000 ₽")
    assert tiles["Остаток лимита банка"]["value"] == report._rub(own["left"])
    assert tiles["Остаток лимита банка"]["note"] == (
        "лимит минус всё оплаченное; по главе 1 −30 000 ₽, по главе 2 490 000 ₽, "
        "по главе 3 50 000 ₽")
    need = tiles["Нужно своих денег сверх сметы банка"]
    assert need["value"] == report._rub(own["need"])
    assert need["note"].startswith("утверждённый бюджет минус лимит банка; первый месяц "
                                   "нехватки — ноябрь 2026")
    for gone in ("Потребность в допфинансировании банка", "Осталось по смете после всех оплат",
                 "Можно ещё выбрать у банка"):
        assert gone not in tiles
    found = {item["topic"]: item["text"] for item in built["findings"]}["Финансирование"]
    assert found.startswith("Нужно своих денег сверх сметы банка 210 000 ₽, первый месяц "
                            "нехватки — ноябрь 2026")
    page = report.render_html(built)
    assert ("<div class='k'>Утверждённый бюджет <span class='i' tabindex='0' role='note' "
            "title='Утверждённый бюджет — сумма") in page
    assert "Нужно своих денег сверх сметы банка</b>" in report._funding_html(built)
    assert "расхождение дат — 10 000 ₽" in report.render_text(built)
