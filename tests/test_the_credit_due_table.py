"""Погашение НКЛ: когда возникают обязательства и хватит ли на них эскроу.

Владелец, 27.10.2026 (ТЗ через «Контроль очерёдности PR»):
- обязательства — прямо из графиков договоров (доля × полный лимит), без модели
  выборок; ожидаемое увеличение лимита («Потребность в допфинансировании
  банка» сводки) — по графику и на условиях НКЛ 2025;
- проценты — в двух сценариях эскроу: по нынешнему темпу и по плану финмодели,
  с платой за лимит и накопленным за отсрочку; над таблицей — «Проценты сверх
  долга: X по темпу, Y по плану (разница Z)» и «хватает до … / первый недостаток»;
- по каждой дате словами: «гасим X (долг Y + проценты Z). На эскроу … будет W.
  Хватает / Не хватает N: их нужно внести из своих денег, иначе банк вправе
  объявить дефолт»; нарастающим итогом: остаток эскроу переходит дальше,
  внесённое своё учитывается; итог — «Всего своих денег понадобится S … (S0 без
  увеличения лимита)».

Запуск: python3 -m pytest tests/test_the_credit_due_table.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_credit_sources as sources  # noqa: E402
import developaid_management_report as report  # noqa: E402
from market_search import contracting  # noqa: E402
from test_credit_repayment_from_loaded_data import (  # noqa: E402,F401
    M, PROJECT, _isolated, _project)

SCHEDULE = [("2027-09-30", 0.61 * 5485.689), ("2027-12-30", 0.07 * 5485.689),
            ("2028-03-30", 0.07 * 5485.689), ("2028-06-30", 0.07 * 5485.689),
            ("2028-09-30", 0.08 * 5485.689), ("2028-12-30", 0.08 * 5485.689),
            ("2029-03-30", 0.02 * 5485.689 + 0.23 * 1125), ("2029-06-30", 0.39 * 1125),
            ("2029-09-30", 0.38 * 1125)]


def _built(monkeypatch):
    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"},
        "schedule": {"approved_finish": "2027-09-30"}}})
    return report.build(PROJECT, "week", "2026-10-18")


def test_obligations_come_from_the_contract_schedules(monkeypatch):
    """Доля × полный лимит по графикам НКЛ 2025 и НКЛ 2026: 6 610,7 млн ₽."""
    due = _built(monkeypatch)["credit_due"]
    assert due["state"] == "ok"
    assert [(row["date"], row["principal"]) for row in due["rows"]] == [
        (day, pytest.approx(amount * M)) for day, amount in SCHEDULE]
    assert due["rows"][0]["principal"] == pytest.approx(3346.27 * M, abs=0.01 * M)
    assert due["principal_total"] == pytest.approx(6610.689 * M)
    # В примере потребности по модели нет — увеличения лимита нет, и сказано почему.
    assert due["extra"] == 0.0 and due["extra_reason"]


def test_interest_in_two_escrow_scenarios_comes_from_the_forecast(monkeypatch):
    built = _built(monkeypatch)
    due = built["credit_due"]
    # По темпу — все проценты, плата и отложенное базового прогноза раздела, ни
    # одной не потеряно и не задвоено.
    base = built["credit"]["base"]["rows"]
    assert due["interest_total"]["pace"] == pytest.approx(
        sum(row["interest_and_fees"] for row in base))
    # По плану финмодели — тот же расчёт с рядом эскроу финмодели: эскроу
    # другое, значит и ставка по покрытию, и проценты другие.
    assert due["interest_total"]["fm"] is not None
    assert due["interest_total"]["fm"] != pytest.approx(due["interest_total"]["pace"])
    # Эскроу к дате — тот же прогноз, что «Эскроу по кварталам», и тот же ряд плана.
    escrow = built["funding"]["escrow"]
    first = due["rows"][0]
    assert first["escrow"]["pace"] == pytest.approx(
        contracting.keeping_at(escrow["queues"][0], "2027-09"))
    assert first["escrow"]["fm"] == pytest.approx(
        contracting.plan_on(escrow["plan_escrow"], "2027-09"))
    pace, fm = due["interest_total"]["pace"], due["interest_total"]["fm"]
    assert report.credit_interest_line(due) == (
        f"Проценты сверх основного долга: {report._rub(pace)} по нынешнему темпу продаж, "
        f"{report._rub(fm)} по плану финмодели (разница {report._rub(abs(pace - fm))}).")


def test_own_money_carries_the_escrow_over():
    """Эскроу 100 к первой дате, платежи 60, 60, 10: остаток 40 идёт на второй
    платёж (своих 20), третий — целиком своими (10). Сверка каждой даты
    отдельно с полным эскроу ошибочно сказала бы «хватает» трижды."""
    rows = [{"principal": amount, "principal_base": amount,
             "interest": {"pace": 0.0}, "interest_base": {"pace": 0.0},
             "escrow": {"pace": 100.0}, "total": {}, "left": {}, "own": {}}
            for amount in (60.0, 60.0, 10.0)]
    report._own_money(rows, "pace")
    assert [row["left"]["pace"] for row in rows] == [100.0, 40.0, 0.0]
    assert [row["own"]["pace"] for row in rows] == [0.0, 20.0, 10.0]


def _with_the_increase(built):
    funding = dict(built["funding"], limit={
        "known": True, "approved": 9000 * M, "need_basis": "model",
        "deficit_ladder": {"total": 2400 * M}})
    linked = (report.sales_link(PROJECT) or {}).get("sales_project") or ""
    plan = report._credit_on_plan(PROJECT, linked, None, report._date(built["end"]),
                                  {"schedule": {"approved_finish": "2027-09-30"}},
                                  {"credit": built["credit"], "funding": funding})
    return report.credit_due(built["credit"], funding, plan)


def test_the_limit_increase_is_on_the_first_loan_schedule(monkeypatch):
    built = _built(monkeypatch)
    plain, due = built["credit_due"], _with_the_increase(built)
    # Сумма — «Потребность в допфинансировании банка» сводки; график — НКЛ 2025.
    assert due["extra"] == pytest.approx(2400 * M)
    assert due["rows"][0]["principal_extra"] == pytest.approx(0.61 * 2400 * M)
    assert due["principal_total"] == pytest.approx((6610.689 + 2400) * M)
    # Без увеличения — ровно прежний расчёт.
    assert due["own_total"]["pace_base"] == pytest.approx(plain["own_total"]["pace"])
    assert due["interest_base_total"]["pace"] == pytest.approx(plain["interest_total"]["pace"])
    # Проценты увеличения — как у НКЛ 2025, в той же доле к её лимиту, но без
    # отложенного до даты РСС: тогда увеличения ещё не было.
    rows = built["credit"]["base"]["rows"]
    nkl = sum(report._loan_interest(row["loans"].get("nkl2025")) for row in rows)
    past = built["credit"]["opening_deferred"]["nkl2025"]
    assert past > 0
    assert due["interest_total"]["pace"] - due["interest_base_total"]["pace"] == \
        pytest.approx((nkl - past) * 2400 / 5485.689)
    own = due["own_total"]
    assert own["pace"] > own["pace_base"]
    assert report.credit_lines(due)[-1] == (
        f"Всего своих денег понадобится {report._rub(own['pace'])} по нынешнему темпу / "
        f"{report._rub(own['fm'])} по плану ФМ, пик — {report._day(due['peak'])}; это с "
        f"учётом увеличения лимита на 2,40 млрд ₽ ({report._rub(own['pace_base'])} без него).")
    page = report._credit_due_html(due)
    assert "<td>Без увеличения лимита</td>" in page
    assert "условия приняты как у НКЛ 2025" in page


def test_each_date_in_the_owner_words_and_the_same_lines_everywhere(monkeypatch):
    built = _built(monkeypatch)
    due = built["credit_due"]
    first = due["rows"][0]
    assert first["own"]["pace"] > 0.5  # в примере эскроу не хватает
    lines = report.credit_lines(due)
    assert len(lines) == len(due["rows"]) + 1
    assert lines[0] == (
        f"30.09.2027 гасим {report._rub(first['total']['pace'])} (долг "
        f"{report._rub(first['principal'])} + проценты {report._rub(first['interest']['pace'])})."
        f" На эскроу к этой дате скорее всего будет {report._rub(first['escrow']['pace'])} (по "
        f"нынешнему темпу; по плану ФМ было бы {report._rub(first['escrow']['fm'])}). Не "
        f"хватает {report._rub(first['own']['pace'])}: их нужно внести из своих денег, иначе "
        "банк вправе объявить дефолт.")
    verdict, main = report.credit_verdict(due), report.credit_main(due)
    assert verdict.startswith("Первый недостаток — 30.09.2027: не хватает ")
    assert "дефолт" in main and main.startswith("30.09.2027 гасим ")
    assert main.endswith(lines[-1])

    page = report.render_html(built)
    section = page[page.index("id='block-credit'"):]
    section = section[:section.index("<h2", 1)]
    # Две строки над таблицей, семь столбцов, текст по датам и одна строка допущений.
    table = section.index("<table class='credit-due'>")
    assert section.index(report.credit_interest_line(due)) < table
    assert section.index(verdict) < table
    for head in ("Дата", "Основной долг", "Проценты (темп)", "Проценты (план ФМ)",
                 "Эскроу к дате (темп)", "Эскроу к дате (план ФМ)", "Хватает / не хватает"):
        assert f"<th>{head}</th>" in section, head
    for line in lines:
        assert line in section
    assert "<details class='credit-more'><summary>Как посчитано" in section
    for word in ("выписка банка", "не загружены", "загрузите", "Статус не определён"):
        assert word not in section.split("<details")[0], word
    # «Главное» и сообщение — первая дата и итог; «Финансирование» и плитка — вывод.
    found = {item["topic"]: item for item in built["findings"]}
    assert found["Погашение кредитов"]["text"] == main
    assert f"Погашение кредитов: {main}" in report.render_text(built)
    assert f"Хватит ли эскроу на платежи по НКЛ с процентами: {verdict}" in page
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert tiles["Эскроу на платежи по НКЛ"]["value"] == \
        f"не хватает {report._rub(due['own_total']['pace'])}"


def test_a_project_without_credit_terms_says_why(monkeypatch):
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}, "schedule": {}}})
    built = report.build("Другой проект", "week", "2026-10-18")
    assert built["credit_due"]["state"] == "missing"
    assert built["credit_due"]["reason"] == built["credit"]["reason"]
    assert "Условия кредитов проекта «Другой проект» в системе не заведены" in \
        report.render_html(built)


def test_the_plan_scenario_raises_the_escrow_to_the_plan_only():
    """Эскроу по плану финмодели: после даты РСС — до плана каждого месяца, после
    раскрытия ряд не читается (он уже гасит кредит), выше плана — не вниз."""
    plan = {"series": {"2026-11": 50 * M, "2026-12": 120 * M, "2027-01": 200 * M,
                       "2027-02": 30 * M}, "cut": "2027-01"}
    got = sources._plan_forecast(plan, 80 * M, "2026-10-18", "2027-03-31")
    assert [(item["date"], item["amount"]) for item in got["contracts"]] == [
        ("2026-12-31", pytest.approx(40 * M)), ("2027-01-31", pytest.approx(80 * M))]
    assert got["sales"] == []


def test_without_interest_the_debt_and_escrow_are_still_told(monkeypatch):
    """Прод 27.10.2026, «Кутузов Сити»: «Хватит ли эскроу на платежи по НКЛ, не
    посчитано: не посчитаны проценты». Владелец: «Нет якобы данных» — графики
    НКЛ и эскроу известны. Без процентов сводка считает долг против эскроу,
    говорит «без процентов» и называет причину пустых процентов."""
    import developaid_credit_repayment as credit

    _project()
    credit.save(PROJECT, [{"name": "key_rate", "as_of": "2026-10-20", "source": "письмо банка",
                           "data": {"path": [{"from": "2026-01-01", "rate": 21.0}]}}],
                "проверка")
    monkeypatch.setattr(report, "_monitor_view", lambda p, e: {"dashboard": {
        "funding": {"known": False, "reason": "нет"},
        "schedule": {"approved_finish": "2027-09-30"}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    due = built["credit_due"]
    first = due["rows"][0]
    assert first["interest"]["pace"] is None
    reason = due["interest_reason"]["pace"]
    assert reason.startswith("Не нашлось: ключевой ставки на 01.05.2025"), reason
    # Долг и эскроу посчитаны: недостаток — по долгу, без процентов.
    assert first["own"]["pace"] == pytest.approx(
        max(0.0, first["principal"] - first["escrow"]["pace"]))
    verdict = report.credit_verdict(due)
    assert "не посчитано" not in verdict
    assert verdict.endswith(f" — без процентов: их не посчитали ({reason}).")
    main = report.credit_main(due)
    assert main.startswith(f"30.09.2027 гасим основной долг {report._rub(first['principal'])} и "
                           "проценты (их не посчитали), на эскроу к этой дате скорее всего будет ")
    assert report.credit_interest_line(due) == \
        f"Проценты сверх основного долга не посчитаны: {reason}."
    tiles = {item["label"]: item for item in report.tiles(built)}
    tile = tiles["Эскроу на платежи по НКЛ"]
    assert tile["value"] != "нет данных" and "без процентов — их не посчитали" in tile["note"]
