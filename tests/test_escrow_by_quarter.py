"""Эскроу по кварталам: план банка, план финмодели, факт или прогноз — одной таблицей.

Владелец, 26.10.2026, на снимке блока «Финансирование»:
- «Что за очередь 1?» — при одной очереди её имя не пишется нигде;
- «Сравнивать с планом банка, а не только ФМ, и желательно оба сравнения — с
  прогнозом и планом до конца».

Проверки:
- строки по кварталам до квартала ввода и раскрытия: прошедший — факт,
  текущий и будущие — прогноз при нынешнем темпе, отклонения к обоим планам;
  нет плана — «нет данных», а не ноль;
- текст сводки берёт те же числа; прежние таблицы «Эскроу против плана
  банка», «Эскроу, очередь» и «Эскроу к вводу» сведены в эту и в «Покрытие
  кредита эскроу», покрытие к вводу и к раскрытию на месте;
- «1 очередь» не пишется; при двух очередях имена есть;
- на телефоне таблица прокручивается в своей рамке, страница не шире экрана.

Запуск: python3 -m pytest tests/test_escrow_by_quarter.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from market_search import sales_store  # noqa: E402
from test_management_report_funding import _isolated, _project, _sales  # noqa: E402,F401
from test_management_report_model import M, PROJECT  # noqa: E402

SCHEDULE = {"approved_finish": "2026-12-31"}


def _built(monkeypatch, bank: bool = True):
    _project()
    _sales(bank=bank)
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}, "schedule": SCHEDULE}})
    return report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")


def test_quarters_carry_both_plans_and_fact_or_forecast(monkeypatch):
    rows = {row["quarter"]: row for row in
            _built(monkeypatch)["funding"]["escrow_track"]["rows"]}
    assert list(rows) == ["2026 Q3", "2026 Q4", "2027 Q1"]
    closed, current, last = rows["2026 Q3"], rows["2026 Q4"], rows["2027 Q1"]
    # Прошедший квартал — факт против обоих планов.
    assert closed["state"] == "closed" and closed["forecast"] is None
    assert (closed["fact"], closed["bank"], closed["fm"]) == (
        pytest.approx(60 * M), pytest.approx(70 * M), pytest.approx(45 * M))
    assert (closed["gap_bank"], closed["gap_fm"]) == (pytest.approx(-10 * M), pytest.approx(15 * M))
    # Текущий — накоплено на сейчас и прогноз на конец квартала; квартал ввода.
    assert current["state"] == "current" and current["marks"] == ["ввод 31.12.2026"]
    assert current["fact"] == pytest.approx(65 * M)
    assert current["forecast"] == pytest.approx(120 * M)
    assert current["gap_bank"] == pytest.approx(0.0)
    # До раскрытия: плана банка на этот квартал нет — это «нет данных», не ноль.
    assert last["marks"] == ["раскрытие эскроу, январь 2027"]
    assert last["bank"] is None and last["gap_bank"] is None
    assert last["forecast"] == pytest.approx(180 * M) and last["gap_fm"] == pytest.approx(60 * M)


def test_the_text_and_the_table_tell_the_same_numbers(monkeypatch):
    built = _built(monkeypatch)
    text = report.render_text(built)
    page = report.render_html(built)
    assert ("Эскроу на конец 2026 Q3: накоплено 60,0 млн ₽; план банка 70,0 млн ₽ "
            "(меньше на 10,0 млн ₽), план финмодели 45,0 млн ₽ (больше на 15,0 млн ₽).") in text
    assert ("В 2026 Q4 (квартал не закрыт) на октябрь 2026 накоплено 65,0 млн ₽; к концу "
            "квартала при нынешнем темпе будет 120,0 млн ₽ — план банка 120,0 млн ₽ "
            "(как в плане), план финмодели 90,0 млн ₽ (больше на 30,0 млн ₽).") in text
    assert ("К концу 2027 Q1 (раскрытие эскроу, январь 2027) при нынешнем темпе будет "
            "180,0 млн ₽ — план банка — нет данных, план финмодели 120,0 млн ₽ "
            "(больше на 60,0 млн ₽).") in text
    assert "2026 Q4 — ввод 31.12.2026 (квартал не закрыт, накоплено на октябрь 2026)" in page
    assert "нет данных" in page
    # Прежние таблицы сведены сюда; покрытие кредита осталось.
    for gone in ("Эскроу против плана банка", "Эскроу, очередь", "Эскроу к вводу"):
        assert gone not in page, gone
    assert "Покрытие кредита эскроу" in page
    assert "к раскрытию (январь 2027)" in page and "к вводу 31.12.2026 (утверждённый срок)" in page
    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert "эскроу на конец 2026 Q3 ниже плана банка на 10,0 млн ₽" in found["Финансирование"]


def test_one_queue_is_not_named(monkeypatch):
    built = _built(monkeypatch)
    text = report.render_text(built)
    page = report.render_html(built)
    for said in (text, page):
        assert "1 очередь" not in said and "очереди" not in said


def test_two_queues_are_named(monkeypatch):
    _project()
    _sales()
    kept = sales_store.load(sales_store.default_dir(), "ЖК")
    parts = {name: source["data"] for name, source in kept["sources"].items()}
    first = parts["credit"]["queues"][0]
    parts["credit"]["queues"].append(dict(first, queue="2 очередь"))
    sales_store.save(sales_store.default_dir(), "ЖК", parts, "test.xlsx")
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}, "schedule": SCHEDULE}})
    built = report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    page = report.render_html(built)
    assert "Эскроу 1-й очереди: к раскрытию" in page and "Эскроу 2-й очереди: к раскрытию" in page


def test_without_a_bank_plan_the_cells_say_no_data(monkeypatch):
    built = _built(monkeypatch, bank=False)
    rows = built["funding"]["escrow_track"]["rows"]
    assert all(row["bank"] is None and row["gap_bank"] is None for row in rows)
    page = report.render_html(built)
    assert page.count("нет данных") >= len(rows)
    assert "План банка не загружен" in page


def test_the_table_scrolls_in_its_frame_on_a_phone(monkeypatch):
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from developaid_report_page import REPORT_PAGE

    body = report.render_html(_built(monkeypatch))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 844})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; "
                         "document.getElementById('privateArea').classList.remove('hidden') }", body)
            got = tab.evaluate("""() => {
                const th = [...document.querySelectorAll('#reportBox th')]
                    .find(c => c.textContent.trim() === 'Эскроу по кварталам');
                const table = th.closest('table');
                const edge = document.getElementById('reportBox').getBoundingClientRect().right;
                return {page: document.documentElement.scrollWidth,
                        right: table.getBoundingClientRect().right, edge,
                        scroll: table.scrollWidth, width: table.clientWidth,
                        rows: table.querySelectorAll('tr').length,
                        overflow: getComputedStyle(table).overflowX} }""")
        finally:
            browser.close()
    assert got["page"] <= 390, got
    assert got["right"] <= got["edge"] + 0.5, got
    assert got["rows"] == 4, got
    assert got["overflow"] in ("auto", "scroll") and got["scroll"] > got["width"], got
