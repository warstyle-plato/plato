"""Блок «Финансирование» сводки: выборка кредита, услуги банка, лимит, эскроу.

«Я же ставил задачу по PDF для отчёта с блоками по стройке, продажам,
финансированию и бюджету» (владелец, 20.10.2026). Блок собирается из того,
что уже есть в данных:
- выборка кредита — платежи РСС из заёмных средств (банк платит подрядчикам
  со счёта ПФ): за период, с начала месяца, с начала проекта;
- услуги банка — статья 3.5 РСС (в ней проценты);
- лимит, остаток и дефицит — тот же расчёт, что в карточке финансирования
  Монитора; нет финкниги — причина, а не нули;
- эскроу и покрытие кредита — план финмодели (лист «КРЕДИТЫ») против
  поступлений по договорам, из отчёта о продажах.
Порядок блоков: стройка → продажи → финансирование → бюджет → общая
информация — и в сообщении, и в документе.

Запуск: python3 -m pytest tests/test_management_report_funding.py -q
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
import developaid_monitor as monitor  # noqa: E402
from market_search import sales_store  # noqa: E402
from test_management_report_model import (  # noqa: E402
    M, PROJECT, _contract, _gpr_book, _rss_book)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _rss_with_sources() -> bytes:
    from openpyxl import load_workbook
    import io

    data = _rss_book([
        (datetime.date(2026, 9, 20), 280 * M),
        (datetime.date(2026, 10, 5), 120 * M),
        (datetime.date(2026, 10, 14), 30 * M),
        (datetime.date(2026, 10, 15), 16 * M, "3.5"),
        (datetime.date(2026, 10, 15), 2 * M, "3.5.1"),
        (datetime.date(2026, 10, 16), 7 * M, "3.1"),
        # После конца недели — не в сводке недели.
        (datetime.date(2026, 10, 19), 50 * M),
    ])
    book = load_workbook(io.BytesIO(data))
    paid = book["Реестр платежей"]
    for r in range(10, paid.max_row + 1):
        if paid.cell(row=r, column=10).value is not None:
            paid.cell(row=r, column=11, value="Заемные средства")
    # Реклама оплачена из собственных средств — это не выборка кредита.
    for r in range(10, paid.max_row + 1):
        if paid.cell(row=r, column=7).value == "3.1":
            paid.cell(row=r, column=11, value="Собственные средства")
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def _project() -> None:
    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    monitor.store_estimate(PROJECT, _rss_with_sources(), "2026-10-18")


def _sales(credit: bool = True, bank: bool = False) -> None:
    rows = [_contract("2026-07-10", "Квартира", 100.0, 25 * M),
            _contract("2026-08-10", "Квартира", 100.0, 25 * M)]
    rows[0]["escrow_schedule"] = [{"month": "2026-07", "amount": 10 * M},
                                  {"month": "2026-08", "amount": 10 * M}]
    rows[1]["escrow_schedule"] = [{"month": "2026-08", "amount": 20 * M},
                                  {"month": "2026-09", "amount": 20 * M},
                                  {"month": "2026-10", "amount": 5 * M}]
    parts = {"contracting": {"project": "ЖК", "missing": [], "rows": rows}}
    if credit:
        months = [f"2026-{m:02d}" for m in range(7, 13)] + ["2027-01", "2027-02"]
        parts["credit"] = {"sheet": "КРЕДИТЫ", "queues": [{
            "queue": "1 очередь",
            "escrow": {m: 15 * M * (i + 1) for i, m in enumerate(months)},
            "pf": {m: 100 * M for m in months},
            "coverage": {}, "rate": {}, "drawn_from": "2026-01", "repay_from": "2027-02"}]}
    if bank:
        # Лист банка в тысячах рублей, остатки на эскроу — нарастающим по кварталам.
        parts["bank_plan"] = {"sheet": "План банка_new", "quarters": ["2026 Q3", "2026 Q4"],
                              "lines": [
            {"label": "Итого остатки на эскроу накопительным итогом (расчетное)",
             "values": {"2026 Q3": 999_000.0, "2026 Q4": 999_000.0}},
            {"label": "Итого остатки на эскроу накопительным итогом (утверждено по CF)",
             "values": {"2026 Q3": 70_000.0, "2026 Q4": 120_000.0}}]}
    sales_store.save(sales_store.default_dir(), "ЖК", parts, "test.xlsx")


def test_draws_and_bank_services_are_split_by_period():
    _project()
    got = report.funding(PROJECT, "week", "2026-10-18")
    assert got["state"] == "ok"
    # Выборка — только заёмные: 3.1 из собственных средств не входит.
    assert got["draws"]["period"] == pytest.approx(30 * M + 18 * M)
    assert got["draws"]["month"] == pytest.approx(120 * M + 30 * M + 18 * M)
    assert got["draws"]["total"] == pytest.approx(280 * M + 168 * M)
    assert got["interest"]["period"] == pytest.approx(18 * M)
    assert got["interest"]["total"] == pytest.approx(18 * M)


def test_without_finance_book_the_limit_names_the_reason():
    _project()
    got = report.funding(PROJECT, "week", "2026-10-18")
    assert got["limit"]["known"] is False
    assert got["limit"]["reason"]
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert "Лимит и дефицит не посчитаны:" in text


def test_the_limit_is_the_monitor_finance_card(monkeypatch):
    _project()
    seen = {}

    def view(project, end):
        seen.setdefault("args", []).append((project, end))
        return {"dashboard": {"funding": {
            "known": True, "bank_limit": 3_970 * M, "paid_actual": 2_100 * M,
            "bank_remaining": 1_500 * M, "reserve": 138 * M,
            "additional_financing": 230 * M, "additional_financing_from": "2027-03-01"}}}

    # Срез Монитора — один расчёт на всю сводку (срок, корпуса, финансирование).
    monkeypatch.setattr(report, "_monitor_view", view)
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert seen["args"] == [(PROJECT, datetime.date(2026, 10, 18))]
    assert ("Лимит банка по смете РСС (главы 2–3): 3,97 млрд ₽; остаток лимитов статей "
            "1,50 млрд ₽ — лимит минус всё оплаченное 2,10 млрд ₽ (кредитом 448,0 млн ₽, "
            "своими деньгами 1,65 млрд ₽); резерв 138,0 млн ₽.") in text
    assert "По РСС не хватает: 230,0 млн ₽, начиная с марта 2027." in text
    assert "Утверждённый бюджет не загружен" in text


def test_escrow_against_the_credit_plan():
    _project()
    _sales()
    got = report.funding(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    queue = got["escrow"]["queues"][0]
    # Последний месяц данных (октябрь) неполный — измеряется сентябрь.
    assert queue["measured_at"] == "2026-09"
    assert queue["actual"] == pytest.approx(60 * M)
    assert queue["plan"] == pytest.approx(45 * M)
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК"))
    assert "Эскроу, очередь «1 очередь»: на сентябрь 2026 накоплено 60,0 млн ₽ при плане " \
           "финмодели (лист «КРЕДИТЫ») 45,0 млн ₽ (больше плана на 15,0 млн ₽)." in text


def test_no_credit_plan_is_named():
    _project()
    _sales(credit=False)
    got = report.funding(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    assert got["escrow"]["state"] == "missing"
    assert "КРЕДИТЫ" in got["escrow"]["reason"]


def test_blocks_go_in_the_owners_order():
    _project()
    built = report.build(PROJECT, "week", "2026-10-18")
    order = ["Стройка", "Продажи", "Финансирование", "Бюджет месяца", "Общая информация"]
    text = report.render_text(built)
    assert [text.index(f"<b>{name}</b>") for name in order] == \
        sorted(text.index(f"<b>{name}</b>") for name in order)
    page = report.render_html(built)
    assert [page.index(f">{name}</h2>") for name in order] == \
        sorted(page.index(f">{name}</h2>") for name in order)


def test_escrow_against_the_bank_plan():
    # «План по эскроу 1,98 млрд не соответствует плану банка. Откуда тянется?»
    # (финансист, 21.10.2026): план брался из листа «КРЕДИТЫ» финмодели, а план
    # банка лежит в книге на листе «План банка_new».
    _project()
    _sales(bank=True)
    got = report.funding(PROJECT, "week", "2026-10-18", sales_project="ЖК")["escrow_bank"]
    assert got["closed"] == {"quarter": "2026 Q3", "plan": pytest.approx(70 * M),
                             "actual": pytest.approx(60 * M), "gap": pytest.approx(-10 * M)}
    assert got["current"]["plan"] == pytest.approx(120 * M)
    assert got["current"]["actual"] == pytest.approx(65 * M)
    built = report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    text = report.render_text(built)
    assert ("Эскроу по плану банка (лист «План банка_new», утверждено по CF): на конец "
            "2026 Q3 план 70,0 млн ₽, накоплено 60,0 млн ₽ — меньше плана на 10,0 млн ₽.") in text
    assert "План банка на конец 2026 Q4 — 120,0 млн ₽; на октябрь 2026 накоплено 65,0 млн ₽." in text
    assert "План банка" in report.render_html(built)


def test_no_bank_plan_is_named():
    _project()
    _sales()
    got = report.funding(PROJECT, "week", "2026-10-18", sales_project="ЖК")["escrow_bank"]
    assert got["state"] == "missing" and "План банка_new" in got["reason"]


def test_the_renamed_bank_sheet_is_read():
    import io

    from openpyxl import Workbook

    from market_search import contracting

    book = Workbook()
    sheet = book.active
    sheet.title = "План банка_new"
    sheet.append([None, "ЖК", "2026 Q3", "2026 Q4"])
    sheet.append(["Эскроу", contracting.BANK_ESCROW_LABEL, 1_628_540.0, 2_172_270.0])
    data = io.BytesIO()
    book.save(data)
    got = contracting.read_bank_plan(data.getvalue())
    assert got["sheet"] == "План банка_new"
    assert contracting.bank_escrow_plan(got) == {"2026 Q3": pytest.approx(1_628_540_000.0),
                                                 "2026 Q4": pytest.approx(2_172_270_000.0)}


def test_the_approved_budget_and_its_deficit_come_from_the_monitor(monkeypatch):
    # «В мониторе есть бюджет строительства по утверждённому бюджету, 6 с
    # лишним млрд. Где это учтено?» (владелец, 21.10.2026): в сводке его не было.
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "bank_limit": 3_970 * M, "paid_actual": 2_100 * M,
        "bank_remaining": 1_500 * M, "reserve": 138 * M, "additional_financing": 0.0,
        "approved": 6_200 * M, "approved_remaining": 4_100 * M,
        "deficit_ladder": {"total": 2_462 * M}}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    text = report.render_text(built)
    assert ("Утверждённый бюджет (главы 2–3, финмодель): 6,20 млрд ₽; остаток потребности "
            "(бюджет минус оплаченное) 4,10 млрд ₽ при лимитах статей и резерве 1,64 млрд ₽ — "
            "не хватает по утверждённому бюджету 2,46 млрд ₽.") in text
    assert "По РСС лимитов и резерва хватает до ввода" in text
    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert "по утверждённому бюджету 6,20 млрд ₽ не хватает на достройку 2,46 млрд ₽" \
        in found["Финансирование"].lower()
    page = report.render_html(built)
    assert "Не хватает по утверждённому бюджету" in page and "2,46 млрд ₽" in page
    # Плашки сверху — деньги стройки пятью числами подряд (владелец, 21.10.2026).
    money = {item["label"]: item["value"] for item in report.tiles(built)}
    assert [money[label] for label in ("Утверждённый бюджет", "Лимит банка",
                                       "Остаток лимита банка", "Дефицит на достройку")] == [
        "6,20 млрд ₽", "3,97 млрд ₽", "1,50 млрд ₽", "2,46 млрд ₽"]
    assert money["Выбрано у банка"] == report._rub(built["funding"]["draws"]["total"])


def test_escrow_at_the_current_pace_leads():
    # «Эскроу НЕ покрывает кредит в текущем темпе, это важнее, что по плану
    # 0,95» (владелец, 21.10.2026).
    _project()
    _sales()
    built = report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    queue = built["funding"]["escrow"]["queues"][0]
    tile = next(item for item in report.tiles(built) if item["label"].startswith("Эскроу"))
    assert tile["label"] == "Эскроу при нынешнем темпе"
    assert tile["value"] == report._times(queue["keeping_pace_coverage"])
    assert "по плану финмодели" in tile["note"]
    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert "при нынешнем темпе эскроу очереди «1 очередь»" in found["Финансирование"].lower()


def test_the_chapter_label_comes_from_the_monitor(monkeypatch):
    # Глава 1 РСС (владелец, 21.10.2026): подписи «главы 1–3» — из расчёта Монитора.
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "bank_limit": 4_100 * M, "paid_actual": 2_200 * M, "chapters_label": "1–3",
        "bank_remaining": 1_500 * M, "reserve": 138 * M, "additional_financing": 0.0,
        "approved": 6_500 * M, "approved_remaining": 4_300 * M,
        "deficit_ladder": {"total": 2_662 * M}}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    text = report.render_text(built)
    assert "Лимит банка по смете РСС (главы 1–3)" in text
    assert "Утверждённый бюджет (главы 1–3, финмодель)" in text and "2–3" not in text
    notes = {item["label"]: item["note"] for item in report.tiles(built)}
    assert notes["Лимит банка"] == "смета РСС, главы 1–3"


def test_the_draws_follow_the_chapters_of_the_limit(monkeypatch):
    """«Лимит 4,64, выбрано 4,80, остаток 1,00 — так не сходится» (владелец,
    22.10.2026): выборка считалась по всем главам РСС, лимит — по главам
    Монитора. Теперь выборка — по тем же главам, что лимит, а плашка остатка
    говорит, из чего он получился."""
    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    # В РСС стенда у платежей коды 2.x и 3.x; глава 1 — отдельный платёж.
    import io
    from openpyxl import load_workbook
    data = _rss_with_sources()
    book = load_workbook(io.BytesIO(data))
    paid = book["Реестр платежей"]
    r = paid.max_row + 1
    for c, v in ((2, "ЗемКо"), (3, "З-1"), (7, "1.1"), (9, datetime.date(2026, 10, 13)),
                 (10, 900 * M), (11, "Заемные средства")):
        paid.cell(row=r, column=c, value=v)
    blob = io.BytesIO(); book.save(blob)
    monitor.store_estimate(PROJECT, blob.getvalue(), "2026-10-18")

    def card(chapters):
        return {"dashboard": {"funding": {
            "known": True, "chapters": chapters, "chapters_label": "–".join((chapters[0], chapters[-1])),
            "bank_limit": 1_000 * M, "paid_actual": 1_448 * M, "paid_borrowed": 1_348 * M,
            "bank_remaining": 1_000 * M, "reserve": 306 * M, "additional_financing": 1_060 * M,
            "additional_financing_from": "2026-11-01",
            "remaining_check": {"plain": -260 * M, "overpaid": 1_200 * M, "book_gap": 60 * M,
                                "remaining": 1_000 * M}}}}

    monkeypatch.setattr(report, "_monitor_view", lambda project, end: card(["2", "3"]))
    built = report.build(PROJECT, "week", "2026-10-18")
    assert built["funding"]["draws"]["total"] == pytest.approx(280 * M + 168 * M)
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: card(["1", "2", "3"]))
    built = report.build(PROJECT, "week", "2026-10-18")
    assert built["funding"]["draws"]["total"] == pytest.approx(280 * M + 168 * M + 900 * M)
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert tiles["Выбрано у банка"]["note"].startswith("кредитом, главы 1–3; за неделю")
    assert "больше лимита на 348,0 млн ₽" in tiles["Выбрано у банка"]["note"]
    assert tiles["Выбрано у банка"]["tone"] == "bad"
    note = tiles["Остаток лимита банка"]["note"]
    assert note == ("лимит минус всё оплаченное 1,45 млрд ₽ (кредитом 1,35 млрд ₽, "
                    "своими деньгами 100,0 млн ₽); резерв 306,0 млн ₽; по РСС не хватает "
                    "1,06 млрд ₽ с ноября 2026")
    text = report.render_text(built)
    assert ("перерасход по статьям 1,20 млрд ₽ остаток не уменьшает; лимиты статей в "
            "финкниге больше сметы РСС на 60,0 млн ₽") in text
    assert "с ноябрь" not in text
    page = report.render_html(built)
    assert "в том числе кредитом" in page and "Перерасход по статьям" in page
    assert "с ноября 2026" in page and "с ноябрь" not in page


def test_without_chapter_one_the_reason_is_named(monkeypatch):
    """Нет строки главы 1 в финкниге — подпись «2–3» с причиной, а не молча."""
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "chapters": ["2", "3"], "chapters_label": "2–3",
        "chapters_reason": "без главы 1: в финансовой книге нет строки главы 1",
        "bank_limit": 4_640 * M, "paid_actual": 2_000 * M, "bank_remaining": 2_640 * M,
        "reserve": 0.0, "additional_financing": 0.0}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    notes = {item["label"]: item["note"] for item in report.tiles(built)}
    assert notes["Лимит банка"] == ("смета РСС, главы 2–3 (без главы 1: в финансовой книге "
                                    "нет строки главы 1)")
