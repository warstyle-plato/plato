"""Погашение НКЛ — простая таблица: когда и сколько обязаны погасить и сколько
к этим датам будет на эскроу.

Владелец, 27.10.2026, на «Данные по кредитам не загружены…» в сводке: «Тут
должна быть простая таблица. Сколько и когда обязаны погасить по НКЛ и сколько
по прогнозу будет на эскроу»; на вопрос, откуда долг: «Долг будет равен сумме
лимита! Посмотри в НКЛ период доступности. Он раньше РНВ».

Проверки:
- платежи — доли договоров от полного лимита на конец периода выборки
  (НКЛ 2025 — 5 485,689 млн ₽ на 30.06.2027: 61 % 30.09.2027 …; НКЛ 2026 —
  1 125 млн ₽ на 30.09.2027: 23 %, 39 %, остаток), всего 6 610,689 млн ₽;
- эскроу к дате платежа — тот же прогноз, что в «Финансировании»;
- «эскроу минус платежи» — против платежей нарастающим итогом;
- выбрано — по РСС, до конца выборки — лимит минус выбранное;
- выписки банка не нужны; проекту без условий кредитов — причина.

Запуск: python3 -m pytest tests/test_the_credit_due_table.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_credit_repayment as credit  # noqa: E402
import developaid_management_report as report  # noqa: E402
from market_search import contracting  # noqa: E402
from test_management_report_funding import _isolated, _project, _sales  # noqa: E402,F401
from test_management_report_model import M, PROJECT  # noqa: E402


def test_the_obligations_are_contract_shares_of_the_full_limit():
    plan = credit.obligations("kutuzov_city")
    rows = {row["date"]: row for row in plan["rows"]}
    assert rows["2027-09-30"]["loans"] == {"nkl2025": pytest.approx(5485.689 * 0.61 * M)}
    assert rows["2029-03-30"]["loans"] == {"nkl2025": pytest.approx(5485.689 * 0.02 * M),
                                           "nkl2026": pytest.approx(1125 * 0.23 * M)}
    # Последний платёж НКЛ 2026 — остаток, 38 %.
    assert rows["2029-09-30"]["loans"]["nkl2026"] == pytest.approx(1125 * 0.38 * M)
    assert plan["rows"][-1]["cumulative"] == pytest.approx(6610.689 * M)
    assert [loan["base"] for loan in plan["loans"]] == [pytest.approx(5485.689 * M),
                                                        pytest.approx(1125 * M)]


def _built(monkeypatch, project=PROJECT):
    monkeypatch.setitem(credit.PROJECT_PRESETS, project, "kutuzov_city")
    _project()
    _sales()
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"},
        "schedule": {"approved_finish": "2027-09-30"}}})
    return report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")


def test_the_table_reads_the_same_escrow_forecast(monkeypatch):
    built = _built(monkeypatch)
    due = built["credit_due"]
    assert due["state"] == "ok"
    basis = built["funding"]["escrow"]["queues"][0]
    first = due["rows"][0]
    assert first["date"] == "2027-09-30"
    assert first["escrow"] == pytest.approx(contracting.keeping_at(basis, "2027-09"))
    assert first["gap"] == pytest.approx(first["escrow"] - first["cumulative"])
    # Выбрано — по РСС, та же выборка с начала проекта, что в «Финансировании».
    drawn = built["funding"]["draws"]["total"]
    assert due["drawn"] == pytest.approx(drawn)
    assert due["to_draw"] == pytest.approx(6610.689 * M - drawn)

    page = report.render_html(built)
    for head in ("Платёж по НКЛ", "НКЛ 2025", "НКЛ 2026", "Всего в дату",
                 "Нарастающим итогом", "На эскроу по прогнозу", "Эскроу минус платежи"):
        assert head in page, head
    assert ("Долг — полный лимит (НКЛ 2025 — 5 485,7 млн ₽ на 30.06.2027, НКЛ 2026 — "
            "1 125,0 млн ₽ на 30.09.2027)") in page
    # Без данных банка таблица отвечает сама; «не загружены» рядом не пишется.
    assert "Данные по кредитам не загружены" not in page

    assert f"Выбрано на сегодня по РСС — {report._rub(drawn)}" in page
    text = report.render_text(built)
    assert (f"(выбрано по РСС {report._rub(drawn)}, до конца выборки — ещё "
            f"{report._rub(6610.689 * M - drawn)})") in text
    assert ("Погашение НКЛ: первый обязательный платёж 30.09.2027 — 3,35 млрд ₽; к этой "
            "дате на эскроу по прогнозу") in text
    found = {item["topic"]: item for item in built["findings"]}
    assert found["Погашение кредитов"]["text"].startswith("первый обязательный платёж 30.09.2027")


def test_a_project_without_credit_terms_says_why(monkeypatch):
    monkeypatch.setattr(credit, "PROJECT_PRESETS", {})
    _project()
    _sales()
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}, "schedule": {}}})
    built = report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")
    assert built["credit_due"]["state"] == "missing"
    assert f"Условия кредитов для проекта «{PROJECT}» не заданы" in report.render_html(built)
