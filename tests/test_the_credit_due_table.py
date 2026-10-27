"""Погашение НКЛ — простая таблица: когда и сколько обязаны погасить и сколько
к этим датам будет на эскроу. Один источник с подробным расчётом раздела.

Владелец, 27.10.2026, на «Данные по кредитам не загружены…» в сводке: «Тут
должна быть простая таблица. Сколько и когда обязаны погасить по НКЛ и сколько
по прогнозу будет на эскроу»; «Все данные есть в НКЛ… Какие выписки и зачем они
нужны?! Все выборки есть в РСС, будущие к РНВ = лимиту».

Проверки:
- платежи основного долга — те же, что в базовом прогнозе раздела кредитов
  (`credit_repayment.for_project`: условия НКЛ, выдачи по РСС, план выдач
  финмодели), второго графика нет; по НКЛ в сумме — всего в дату;
- эскроу к дате платежа — тот же прогноз, что в «Финансировании»;
- «эскроу минус платежи» — против платежей нарастающим итогом;
- выбрано — по РСС, до лимита — лимит минус выбранное;
- никаких выписок и «не загружены»; проекту без условий — причина раздела.

Запуск: python3 -m pytest tests/test_the_credit_due_table.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from market_search import contracting  # noqa: E402
from test_credit_repayment_from_loaded_data import (  # noqa: E402,F401
    M, PROJECT, _isolated, _project)


def _built(monkeypatch):
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"},
        "schedule": {"approved_finish": "2027-09-15"}}})
    return report.build(PROJECT, "week", "2026-10-18")


def test_the_table_reads_the_same_forecast_as_the_credit_section(monkeypatch):
    built = _built(monkeypatch)
    due = built["credit_due"]
    assert due["state"] == "ok"
    # Платежи основного долга — ровно те, что в базовом прогнозе раздела.
    paid = [(row["date"], row["principal"]) for row in built["credit"]["base"]["rows"]
            if (row.get("principal") or 0.0) > 0.5]
    assert [(row["date"], row["total"]) for row in due["rows"]] == [
        (day, pytest.approx(amount)) for day, amount in paid]
    for row in due["rows"]:
        assert sum(row["loans"].values()) == pytest.approx(row["total"])
    assert due["rows"][-1]["cumulative"] == pytest.approx(sum(a for _, a in paid))
    # Эскроу — тот же прогноз, что в «Финансировании».
    basis = built["funding"]["escrow"]["queues"][0]
    first = due["rows"][0]
    assert first["escrow"] == pytest.approx(contracting.keeping_at(basis, first["date"][:7]))
    assert first["gap"] == pytest.approx(first["escrow"] - first["cumulative"])
    # Выбрано — по РСС, та же выборка с начала проекта, что в «Финансировании».
    drawn = built["funding"]["draws"]["total"]
    assert due["drawn"] == pytest.approx(drawn)
    assert due["to_draw"] == pytest.approx((5485.689 + 1125) * M - drawn)


def test_the_page_text_and_main_say_it_simply(monkeypatch):
    built = _built(monkeypatch)
    due = built["credit_due"]
    page = report.render_html(built)
    for head in ("Платёж по НКЛ", "НКЛ 2025", "НКЛ 2026", "Всего в дату",
                 "Нарастающим итогом", "На эскроу по прогнозу", "Эскроу минус платежи"):
        assert head in page, head
    assert f"Выбрано на сегодня по РСС — {report._rub(due['drawn'])}" in page
    # Погашение в день раскрытия эскроу (утверждённый ввод) подписано.
    assert due["rows"][0]["disclosure"] and "15.09.2027 — раскрытие эскроу" in page
    assert "Долг на конец выборки — выбрано по РСС плюс выдачи по плану финмодели" in page
    section = page[page.index("id='block-credit'"):]
    section = section[:section.index("<h2", 1)]
    for word in ("выписка банка", "выписки банка", "не загружены", "загрузите"):
        assert word not in section.lower(), word

    first = due["rows"][0]
    text = report.render_text(built)
    assert (f"Погашение НКЛ: первый обязательный платёж {report._day(first['date'])} — "
            f"{report._rub(first['total'])}") in text
    assert (f"(выбрано по РСС {report._rub(due['drawn'])}, до лимита — ещё "
            f"{report._rub(due['to_draw'])})") in text
    found = {item["topic"]: item for item in built["findings"]}
    assert found["Погашение кредитов"]["text"].startswith("первый обязательный платёж")


def test_a_project_without_credit_terms_says_why(monkeypatch):
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}, "schedule": {}}})
    built = report.build("Другой проект", "week", "2026-10-18")
    assert built["credit_due"]["state"] == "missing"
    assert built["credit_due"]["reason"] == built["credit"]["reason"]
    assert "Условия кредитов проекта «Другой проект» в системе не заведены" in \
        report.render_html(built)
