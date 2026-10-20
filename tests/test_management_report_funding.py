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


def _sales(credit: bool = True) -> None:
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

    def card(project, end):
        seen["args"] = (project, end)
        return {"known": True, "bank_limit": 3_970 * M, "paid_actual": 2_100 * M,
                "bank_remaining": 1_500 * M, "reserve": 138 * M,
                "additional_financing": 230 * M, "additional_financing_from": "2027-03-01"}

    monkeypatch.setattr(report, "_monitor_funding", card)
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert seen["args"] == (PROJECT, datetime.date(2026, 10, 18))
    assert ("Лимит банка по РСС (главы 2–3): 3,97 млрд ₽, оплачено с начала проекта "
            "2,10 млрд ₽, остаток лимитов статей 1,50 млрд ₽, резерв 138,0 млн ₽.") in text
    assert "Не хватает на достройку: 230,0 млн ₽, начиная с март 2027." in text


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
           "45,0 млн ₽ (больше плана на 15,0 млн ₽)." in text


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
    assert [page.index(f"<h2>{name}</h2>") for name in order] == \
        sorted(page.index(f"<h2>{name}</h2>") for name in order)
