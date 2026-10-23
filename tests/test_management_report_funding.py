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
    assert ("Лимит банка: 3,97 млрд ₽; остаток лимитов "
            "1,50 млрд ₽ — лимит минус всё оплаченное 2,10 млрд ₽ (кредитом 448,0 млн ₽, "
            "своими деньгами 1,65 млрд ₽); резерв 138,0 млн ₽.") in text
    assert "По РСС не хватает: 230,0 млн ₽, начиная с марта 2027." in text
    # В «Главном» регистр аббревиатур цел: capitalize() давал «по рсс» (владелец, 22.10.2026).
    found = {item["topic"]: item["text"] for item in
             report.build(PROJECT, "week", "2026-10-18")["findings"]}
    assert "По РСС не хватает 230,0 млн ₽ с марта 2027" in found["Финансирование"]
    assert found["Финансирование"][:1].isupper()
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
           "финмодели 45,0 млн ₽ (больше плана на 15,0 млн ₽)." in text


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
    assert ("Эскроу по плану банка: на конец "
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
    assert ("Утверждённый бюджет: 6,20 млрд ₽; остаток потребности "
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


def test_the_report_names_no_chapters_sheets_or_codes(monkeypatch):
    """«Зачем эти технические пояснения руководству? И здесь и везде по тексту»
    (владелец, 22.10.2026): главы РСС, имена листов, коды статей и «утверждено
    по CF» — для команды на странице Монитора, не в сводке."""
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "bank_limit": 4_100 * M, "paid_actual": 2_200 * M, "chapters_label": "1–3",
        "bank_remaining": 1_500 * M, "reserve": 138 * M, "additional_financing": 0.0,
        "approved": 6_500 * M, "approved_remaining": 4_300 * M,
        "deficit_ladder": {"total": 2_662 * M}}}})
    _sales(bank=True)
    built = report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    text = report.render_text(built)
    page = report.render_html(built)
    for banned in ("главы 1–3", "главы 2–3", "глава 1", "лист «", "по CF", "статья 3.5",
                   "финкниг", "КРЕДИТЫ", "заёмных средств", "по смете и оплатам"):
        assert banned not in text, banned
        assert banned not in page, banned
    assert "Лимит банка: 4,10 млрд ₽" in text and "Утверждённый бюджет: 6,50 млрд ₽" in text
    assert "Эскроу по плану банка: " in text and "Услуги банка и проценты" in page
    notes = {item["label"]: item["note"] for item in report.tiles(built)}
    assert notes["Лимит банка"] == "по смете РСС; резерв 138,0 млн ₽"
    assert notes["Утверждённый бюджет"] == "по финмодели"


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
    assert tiles["Выбрано у банка"]["note"].startswith("из них за неделю 948,0 млн ₽ и за месяц 1,07 млрд ₽")
    assert "больше лимита на 348,0 млн ₽" in tiles["Выбрано у банка"]["note"]
    assert tiles["Выбрано у банка"]["tone"] == "bad"
    note = tiles["Остаток лимита банка"]["note"]
    assert note == "лимит без оплаченного 1,45 млрд ₽; по РСС не хватает 1,06 млрд ₽ с ноября 2026"
    text = report.render_text(built)
    assert ("перерасход по статьям 1,20 млрд ₽ остаток не уменьшает; лимиты по статьям "
            "больше общего лимита на 60,0 млн ₽") in text
    assert "с ноябрь" not in text
    page = report.render_html(built)
    assert "в том числе кредитом" in page and "Перерасход по статьям" in page
    assert "с ноября 2026" in page and "с ноябрь" not in page


def test_a_gap_equal_to_the_reserve_is_not_shown(monkeypatch):
    """«Зачем эта запись?» (владелец, 22.10.2026) — строка «Лимиты статей финкниги
    против сметы РСС −306,2 млн ₽» равнялась резерву 306,1 млн ₽: Монитор
    теперь учитывает резерв, а сводка строку с нулевой разницей не печатает."""
    import developaid_monitor_dashboard as dashboard

    waterfall = {"opening_bank_remaining": 1_240 * M, "opening_article_deficit": 0.0}
    check = dashboard._remaining_check(6_810 * M, 5_264 * M, waterfall, reserve=306.1 * M)
    assert abs(check["book_gap"]) < 0.001 * 6_810 * M
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "chapters": ["1", "2", "3"], "chapters_label": "1–3",
        "bank_limit": 6_810 * M, "paid_actual": 5_264 * M, "bank_remaining": 1_240 * M,
        "reserve": 306.1 * M, "additional_financing": 1_080 * M,
        "additional_financing_from": "2026-11-01", "remaining_check": check}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    assert "Лимиты по статьям против общего лимита" not in report.render_html(built)
    assert "лимиты по статьям" not in report.render_text(built)


def test_without_chapter_one_the_report_stays_plain(monkeypatch):
    """Причина «без главы 1» — для команды в Мониторе; сводка её не печатает."""
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "chapters": ["2", "3"], "chapters_label": "2–3",
        "chapters_reason": "без главы 1: в финансовой книге нет строки главы 1",
        "bank_limit": 4_640 * M, "paid_actual": 2_000 * M, "bank_remaining": 2_640 * M,
        "reserve": 0.0, "additional_financing": 0.0}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    notes = {item["label"]: item["note"] for item in report.tiles(built)}
    assert notes["Лимит банка"] == "по смете РСС"
    assert "главы 2–3" not in report.render_html(built)


def test_the_money_tiles_name_chapters_reserves_and_periods(monkeypatch):
    """«Слишком много текста. Лучше писать из них по 2 главе и по 3 главе
    столько-то в лимитах РСС. И отдельно резервы такие-то. Выбрано у банка
    можно писать из них за неделю и за месяц» (владелец, 22.10.2026)."""
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "chapters": ["1", "2", "3"], "chapters_label": "1–3",
        "bank_limit": 6_810 * M, "paid_actual": 5_264 * M, "bank_remaining": 1_240 * M,
        "limit_by_chapter": {"1": 1_200 * M, "2": 5_100 * M, "3": 510 * M},
        "reserve": 306.1 * M, "reserve_parts": {"2.8": 209.7 * M, "2.9": 96.4 * M},
        "reserve_names": {"2.8": "Непредвиденные расходы", "2.9": "Резерв на удорожание"},
        "additional_financing": 1_080 * M, "additional_financing_from": "2026-11-01",
        "approved": 8_810 * M, "approved_remaining": 3_546 * M,
        "approved_by_chapter": {"1": 1_300 * M, "2": 6_900 * M, "3": 610 * M},
        "deficit_ladder": {"total": 2_000 * M}}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    notes = {item["label"]: item["note"] for item in report.tiles(built)}
    assert notes["Утверждённый бюджет"] == ("из них по 1 главе 1,30 млрд ₽, по 2 главе 6,90 млрд ₽, "
                                             "по 3 главе 610,0 млн ₽")
    assert notes["Лимит банка"] == ("из них по 1 главе 1,20 млрд ₽, по 2 главе 5,10 млрд ₽, "
                                    "по 3 главе 510,0 млн ₽; резервы: Непредвиденные расходы "
                                    "209,7 млн ₽ и Резерв на удорожание 96,4 млн ₽")
    draws = built["funding"]["draws"]
    assert notes["Выбрано у банка"] == (f"из них за неделю {report._rub(draws['period'])} и "
                                        f"за месяц {report._rub(draws['month'])}")
    assert notes["Остаток лимита банка"] == ("лимит без оплаченного 5,26 млрд ₽; по РСС не хватает "
                                             "1,08 млрд ₽ с ноября 2026")
    # В месячной сводке «за неделю» нет — только за месяц.
    month = report.build(PROJECT, "month", "2026-10-18")
    notes = {item["label"]: item["note"] for item in report.tiles(month)}
    assert notes["Выбрано у банка"].startswith("из них за месяц ") and "за неделю" not in notes["Выбрано у банка"]
