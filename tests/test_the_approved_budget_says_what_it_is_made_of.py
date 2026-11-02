"""«Утверждённый бюджет» говорит, из чего он сложен и откуда взят.

Владелец (02.11.2026) не понимал, откуда берётся число на плитке: оно
показывало только главы сметы по карте «статьи_БДДС», а раздел
административных расходов с налогами, разнесённый по главам, видно не было.
Теперь у плитки есть подсказка «i»: разделы финмодели (налоги отдельно),
«без процентов по кредиту», сверка «бюджет = ФАКТ + ПЛАН» и источник —
исходное имя файла и дата загрузки.

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
    "3.1.4": ("Проценты по кредитам", 90, 10, 80),
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


def test_the_sections_add_up_to_the_budget_with_the_taxes_apart(tmp_path):
    got = _read(tmp_path, _finmodel())
    comp = got["budget_composition"]
    assert [item["code"] for item in comp["sections"]] == ["2.1", "2.2", "2.3", "2.4"]
    assert sum(item["total"] for item in comp["sections"]) == pytest.approx(got["approved"])
    assert comp["sections"][3]["total"] == pytest.approx(160 * K)
    assert comp["taxes"] == [{"code": "2.4.5", "name": "Налоги", "total": pytest.approx(120 * K),
                              "fact": pytest.approx(40 * K), "plan": pytest.approx(80 * K)}]
    # Проценты (3.1.4) — не строка «2.…» и в бюджет не входят.
    assert comp["interest_rows"] == []
    assert comp["fact"] + comp["plan"] == pytest.approx(got["approved"])
    assert comp["difference"] == pytest.approx(0.0)
    # Глав сметы три, а раздел 2.4 по ним разнесён: глава 1 — участок и земельный налог.
    assert got["approved_by_chapter"]["1"] == pytest.approx(350 * K)

    lines = dashboard.budget_hint_lines({"budget_composition": comp}, report._rub)
    assert lines[0] == (
        "Утверждённый бюджет — сумма строк «ИТОГО» листа «cf_1_new» финмодели, 1,6 млн ₽. "
        "По разделам: 2.1 «Приобретение проекта» — 300 000 ₽; 2.2 «Строительство» — "
        "1,0 млн ₽; 2.3 «Коммерческие расходы» — 100 000 ₽; 2.4 «Административно-"
        "хозяйственные расходы» — 160 000 ₽, из них «Налоги» — 120 000 ₽.")
    assert lines[1].startswith("Проценты по кредиту в эту сумму не входят")
    assert lines[2] == ("Из бюджета уже оплачено по финмодели (ФАКТ) 790 000 ₽, осталось "
                        "оплатить (ПЛАН) 770 000 ₽; вместе — 1,6 млн ₽.")
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
    assert "Проценты по кредиту в эту сумму входят: строки 2.4.7." in text
    assert "не входят" not in text


def test_the_upload_keeps_the_file_name_and_the_day(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    assert monitor.finance_baseline_meta("demo") == {}
    monitor.replace_finance_baseline("demo", _finmodel(), "2026-10-23",
                                     file_name="C:\\Книги\\ФМ синтетика.xlsx")
    meta = monitor.finance_baseline_meta("demo")
    assert meta["file_name"] == "ФМ синтетика.xlsx"
    assert meta["uploaded_at"][:4] == str(datetime.datetime.now(datetime.timezone.utc).year)
    day = datetime.date.fromisoformat(meta["uploaded_at"][:10]).strftime("%d.%m.%Y")
    lines = dashboard.budget_hint_lines({"baseline_file": meta}, report._rub)
    assert lines == [f"Источник: файл «{meta['file_name']}», загружен {day}."]
    # Загрузка без имени — дата есть, имя названо отсутствующим, а не выдумано.
    monitor.replace_finance_baseline("demo", _finmodel(), "2026-10-24")
    lines = dashboard.budget_hint_lines({"baseline_file": monitor.finance_baseline_meta("demo")},
                                        report._rub)
    assert lines == [f"Источник: финансовая база загружена {day}; исходное имя файла при "
                     "загрузке не передано."]


def test_the_tile_and_the_page_carry_the_composition(monkeypatch, tmp_path):
    from test_management_report_funding import PROJECT, _project

    comp = _read(tmp_path, _finmodel())["budget_composition"]
    _project()
    funding = {
        "known": True, "need_basis": "model", "bank_limit": 1_400 * M, "paid_actual": 700 * M,
        "paid_borrowed": 500 * M, "bank_remaining": 600 * M, "reserve": 0.0,
        "approved": 1_560 * M, "approved_remaining": 770 * M,
        "deficit_ladder": {"total": 170 * M},
        "budget_composition": comp,
        "baseline_file": {"file_name": "ФМ синтетика.xlsx",
                          "uploaded_at": "2026-11-02T10:00:00+00:00"}}
    monkeypatch.setattr(report, "_monitor_view",
                        lambda project, end: {"dashboard": {"funding": funding}})
    built = report.build(PROJECT, "week", "2026-10-18")
    tile = {item["label"]: item for item in report.tiles(built)}["Утверждённый бюджет"]
    assert tile["note"] == "по разделам финмодели 2.1, 2.2, 2.3, 2.4; без процентов по кредиту"
    assert "из них «Налоги»" in tile["hint"]
    assert "Проценты по кредиту в эту сумму не входят" in tile["hint"]
    assert "Источник: файл «ФМ синтетика.xlsx», загружен 02.11.2026." in tile["hint"]
    page = report.render_html(built)
    tiles_html = page[page.index("<div class='tiles'>"):]
    assert ("<div class='k'>Утверждённый бюджет <span class='i' tabindex='0' role='note' "
            "title='Утверждённый бюджет — сумма") in tiles_html
    assert "оплачено по финмодели (ФАКТ)" in report._funding_html(built)


# --- Плашки одной цепочкой по финмодели (решение владельца, 02.11.2026).

def _chain_funding(comp: dict) -> dict:
    from test_the_extra_financing_is_split_by_chapter import _overpaid_rec

    rec = _overpaid_rec()  # главы 2–3: осталось достроить 175, остаток 100, излишек 35
    return {
        "known": True, "need_basis": "model", "bank_limit": 1_400 * K, "paid_actual": 700 * K,
        "paid_borrowed": 500 * K, "bank_remaining": rec["tiles"]["remaining"], "reserve": 0.0,
        "approved": comp["total"], "approved_remaining": comp["plan"],
        "deficit_ladder": {"total": rec["total"]["gap"]},
        "additional_financing": rec["total"]["gap"],
        "additional_financing_from": "2027-01-01",
        "budget_composition": comp, "limit_reconciliation": rec,
        "baseline_file": {}}


def test_each_tile_is_the_previous_ones_subtracted(tmp_path, monkeypatch):
    from test_management_report_funding import PROJECT, _project

    comp = _read(tmp_path, _finmodel())["budget_composition"]
    funding = _chain_funding(comp)
    _project()
    monkeypatch.setattr(report, "_monitor_view",
                        lambda project, end: {"dashboard": {"funding": funding}})
    built = report.build(PROJECT, "week", "2026-10-18")
    drawn = built["funding"]["draws"]["total"]
    chain = dashboard.funding_chain(funding, drawn)
    assert chain["to_pay"] == pytest.approx(chain["budget"] - chain["paid"])
    assert chain["bank_gives"] == pytest.approx(chain["bank_limit"] - chain["borrowed"])
    assert chain["short"] == pytest.approx(chain["to_pay"] - chain["bank_gives"])
    assert chain["bridge"]["matches"]

    shown = [item for item in report.tiles(built)
             if item["label"] in ("Утверждённый бюджет", "Оплачено по финмодели",
                                  "Осталось оплатить", "Лимит банка", "Выбрано у банка",
                                  "Банк ещё даст", "Не хватает")]
    assert [item["label"] for item in shown] == [
        "Утверждённый бюджет", "Оплачено по финмодели", "Осталось оплатить", "Лимит банка",
        "Выбрано у банка", "Банк ещё даст", "Не хватает"]
    value = {item["label"]: item["value"] for item in shown}
    assert value["Утверждённый бюджет"] == report._rub(comp["total"])
    assert value["Оплачено по финмодели"] == report._rub(comp["fact"])
    assert value["Осталось оплатить"] == report._rub(comp["total"] - comp["fact"])
    assert value["Выбрано у банка"] == report._rub(drawn)
    assert value["Банк ещё даст"] == report._rub(1_400 * K - drawn)
    short = (comp["total"] - comp["fact"]) - (1_400 * K - drawn)
    assert value["Не хватает"] == (report._rub(short) if short > 0 else "нет")
    labels = {item["label"] for item in report.tiles(built)}
    for gone in ("Осталось по смете после всех оплат", "Можно ещё выбрать у банка",
                 "Потребность в допфинансировании банка"):
        assert gone not in labels

    text = report.render_text(built)
    assert "Как складываются плашки." in text
    assert "Потребность в допфинансировании банка — 75 ₽" in text
    assert "«Не хватает» получается из неё так: плюс " in text
    assert "Как складываются плашки" in report._funding_html(built)


def test_the_chain_bridge_adds_up_to_the_bank_need_exactly():
    # Синтетика без книги: осталось оплатить 900, банк даст 300, не хватает 600;
    # потребность банка по главам 2–3 — 75 (из _overpaid_rec: 50 по главе 2, 25 по главе 3).
    from test_the_extra_financing_is_split_by_chapter import _overpaid_rec

    rec = _overpaid_rec()
    funding = {"known": True, "bank_limit": 800.0, "additional_financing": rec["total"]["gap"],
               "limit_reconciliation": rec,
               "budget_composition": {"sections": [{"code": "2.2"}], "total": 1_000.0,
                                      "fact": 100.0, "plan": 900.0}}
    chain = dashboard.funding_chain(funding, 500.0)
    assert (chain["to_pay"], chain["bank_gives"], chain["short"]) == (900.0, 300.0, 600.0)
    bridge = chain["bridge"]
    assert bridge["matches"]
    # 600 = 75 + (900 − 175) − (300 − 100)
    assert bridge["outside"] == pytest.approx(725.0)
    assert bridge["bank_vs_remaining"] == pytest.approx(200.0)
    line = dashboard.chain_lines(chain, report._rub)[-1]
    assert line == ("Потребность в допфинансировании банка — 75 ₽: это нехватка банковских "
                    "денег на главы 2–3, по каждой главе отдельно. «Не хватает» получается из "
                    "неё так: плюс 725 ₽ — осталось оплатить вне стройки и коммерции (глав "
                    "2–3): участок, административные расходы, налоги и прочее; минус 200 ₽ — "
                    "разница между тем, что банк ещё даст, и остатком по смете глав 2–3: в "
                    "лимите есть другие главы, а смета уменьшается и на оплаты своими "
                    "деньгами.")
    # Подделка: итог водопада разошёлся с главами сверки — разложение не сходится.
    forged = dict(funding, additional_financing=rec["total"]["gap"] + 7.0)
    assert dashboard.funding_chain(forged, 500.0)["bridge"]["matches"] is False
