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
    got = _read(tmp_path, _finmodel())
    comp = got["budget_composition"]
    return comp, dashboard._own_money(comp, SMETA, PAID, ["1", "2", "3"],
                                      datetime.date(2026, 10, 20),
                                      chapter_flow=got["chapter_flow"])


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
    rows = {row["chapter"]: row["amount"] for row in own["rows"]}
    # Карта «статьи_БДДС» кладёт административные расходы (2.4.1 → 2.6) в главу 2.
    # 210 = глава 1: 0 − (−30) + глава 2: 620 − 490 + глава 3: 70 − 50 + расхождение 30
    assert rows == {"1": pytest.approx(30 * K), "2": pytest.approx(130 * K),
                    "3": pytest.approx(20 * K)}
    assert own["rows"][1]["sections"] == {"2.2": pytest.approx(1_000 * K),
                                          "2.4": pytest.approx(40 * K)}
    assert own["dates"] == pytest.approx(30 * K)
    assert sum(rows.values()) + own["dates"] == pytest.approx(own["need"])
    # Первый месяц — водопад глав: главе 2 не хватает в ноябре.
    assert own["from"] == "2026-11-01"

    lines = dashboard.own_money_lines(own, report._rub)
    assert lines[0].startswith("Утверждённый бюджет без налогов 1,4 млн ₽ минус лимит банка "
                               "1,2 млн ₽ — нужно своих денег сверх сметы банка 210 000 ₽, "
                               "первый месяц нехватки — ноябрь 2026.")
    assert ("глава 2 (стройка) — 130 000 ₽: осталось оплатить по финмодели 620 000 ₽ минус "
            "остаток лимита главы 490 000 ₽; бюджет главы по карте «статьи_БДДС» — разделы "
            "2.2 1,0 млн ₽ + 2.4 40 000 ₽") in lines[1]
    assert "расхождение «ФАКТ» финмодели с реестром РСС — 30 000 ₽: финмодель считает " \
           "оплаченным больше" in lines[1]


def test_a_forged_section_breaks_the_identity(tmp_path):
    got = _read(tmp_path, _finmodel())
    forged = {**got["budget_composition"], "total": got["approved"] + 5 * K}  # бюджет разошёлся
    own = dashboard._own_money(forged, SMETA, PAID, ["1", "2", "3"], datetime.date(2026, 10, 20),
                               chapter_flow=got["chapter_flow"])
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
    assert "расхождение «ФАКТ» финмодели с реестром РСС — 30 000 ₽" in report.render_text(built)


# --- Нехватка не прыгает при смене месяца сводки.

PLAN = {"2026-10-01": 60.0, "2026-11-01": 30.0, "2026-12-01": 20.0, "2027-01-01": 10.0}
BOOK = datetime.date(2026, 10, 1)


@pytest.mark.parametrize("cut", [datetime.date(2026, 10, 27), datetime.date(2026, 11, 2),
                                 datetime.date(2026, 12, 15)])
def test_the_plan_still_owed_does_not_depend_on_the_cut(cut):
    # После даты книги по реестру оплачено 70: октябрь (60) и 10 из ноября.
    owed = dashboard._plan_still_owed(PLAN, BOOK, 70.0, cut)
    assert sum(owed.values()) == pytest.approx(120.0 - 70.0)
    # Неоплаченное прошлых месяцев переносится на месяц среза, а не выпадает.
    assert min(owed) == cut.replace(day=1).isoformat()
    assert all(day >= cut.replace(day=1).isoformat() for day in owed)


def test_the_monitor_gap_is_the_same_in_october_and_in_november(monkeypatch):
    """Настоящий расчёт Монитора на двух датах среза — без новых оплат."""
    from pathlib import Path

    import test_the_monitor_takes_the_finmodel_as_its_finance_book as fm

    sections = {ch: {**row, "monthly": {"2026-10-01": 120.0, "2026-11-01": 150.0,
                                        "2026-12-01": 100.0}}
                for ch, row in fm.SECTIONS.items()}
    fm._finmodel_funding(monkeypatch, sections, fm.ESTIMATE, fm.PAID)  # ставит заглушки книги
    reader = dashboard._finance_baseline
    monkeypatch.setattr(dashboard, "_finance_baseline",
                        lambda project: {**reader(project), "plan_from": BOOK})
    # По реестру после даты книги оплачено 40 по каждой главе.
    monkeypatch.setattr(dashboard, "_paid_since", lambda rss, est, ch, since: 40.0)
    view = {"schedule": {"approved_end": "2027-09-30", "forecast_end": None}}
    got = {cut.month: dashboard._funding_risk("demo", Path("rss.xlsx"), cut, view)
           for cut in (datetime.date(2026, 10, 27), datetime.date(2026, 11, 2))}
    assert got[10]["additional_financing"] == pytest.approx(got[11]["additional_financing"])
    assert got[10]["remaining_need"] == pytest.approx(got[11]["remaining_need"])
    # 2 главы × (370 плана − 40 оплачено после даты книги)
    assert got[11]["remaining_need"] == pytest.approx(2 * (370.0 - 40.0))


def test_an_unpaid_past_month_moves_to_the_cut():
    owed = dashboard._plan_still_owed(PLAN, BOOK, 0.0, datetime.date(2026, 12, 5))
    assert owed["2026-12-01"] == pytest.approx(60.0 + 30.0 + 20.0)
    assert owed["2027-01-01"] == pytest.approx(10.0)


def test_the_bank_gap_takes_the_chapter_by_the_crosswalk(monkeypatch):
    """Административные расходы, которые карта кладёт в главу 2, — потребность главы 2."""
    from pathlib import Path

    import test_the_monitor_takes_the_finmodel_as_its_finance_book as fm

    fm._finmodel_funding(monkeypatch, fm.SECTIONS, fm.ESTIMATE, fm.PAID)
    reader = dashboard._finance_baseline
    flow = {"2": {"monthly": {"2026-11-01": 250.0 + 40.0, "2026-12-01": 100.0}},  # + 2.4 → 2.6
            "3": {"monthly": {"2026-11-01": 30.0, "2027-01-01": 50.0}}}
    monkeypatch.setattr(dashboard, "_finance_baseline",
                        lambda project: {**reader(project), "chapter_flow": flow})
    view = {"schedule": {"approved_end": "2027-09-30", "forecast_end": None}}
    got = dashboard._funding_risk("demo", Path("rss.xlsx"), datetime.date(2026, 10, 20), view)
    assert got["need_by_chapter"]["2"]["need"] == pytest.approx(390.0)
    # Без карты прежний расчёт взял бы только раздел 2.2 (350) — и недосчитал 40.
    assert got["need_by_chapter"]["2"]["gap"] == pytest.approx(390.0 - 50.0)
