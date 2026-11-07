"""Deadline warnings and unworked advances for the legal team's register.

All data is synthetic. The forecast is from accepted money pace of dated
cumulative periods; payments join only by exact contractor, number and date.
"""
from __future__ import annotations

import datetime as dt

import openpyxl
import pytest
from test_monitor_contract_register import (  # noqa: F401  (fixture)
    primary_ledger,
    project,
)

import developaid_monitor as monitor
import developaid_monitor_contract_risk as risk
import developaid_monitor_contracts as contracts

CUT = "2026-11-06"
DAY = "2026-11-01"
DEADLINE_HEADER = {13: "Срок исполнения"}


def book(project, contracts_rows, payments=(), acts=None):
    """RSS workbook with contracts and «Реестр платежей», plus explicit KS periods."""
    folder = monitor._project_dir(project) / "estimate"
    folder.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Реестр договоров"
    ws.cell(1, 1, "Заказчик")
    ws.cell(1, 2, "Developer A")
    ws.cell(6, 4, "Дата договора")
    ws.cell(6, 8, "Сумма договора")
    ws.cell(6, 12, "Выполнено по реестру")
    ws.cell(6, 13, "Срок исполнения")
    for i, row in enumerate(contracts_rows, 9):
        for field, index in {"contractor": 2, "contract": 3, "contract_date": 4, "subject": 5,
                             "amount": 8, "completed": 12, "deadline": 13}.items():
            if field in row:
                ws.cell(i, index, row[field])
    pay = wb.create_sheet("Реестр платежей")
    for i, row in enumerate(payments, 10):
        for field, index in {"contractor": 2, "contract": 3, "contract_date": 4, "purpose": 6,
                             "date": 9, "amount": 10, "source": 11}.items():
            if field in row:
                pay.cell(i, index, row[field])
    wb.save(folder / f"{DAY}.xlsx")
    wb.close()
    ledgers = []
    for row in contracts_rows:
        ledger = primary_ledger(row, acts=(acts or {}).get(row["contract"], []))
        ledger["items"][0]["periods"] = [dict(p, amount_basis="with_vat") for p in ledger["items"][0]["periods"]]
        ledgers.append(ledger)
    project.snapshots.append({"taken_at": DAY, "ledgers": ledgers, "summary_contracts": []})


def contract(number, *, deadline, amount=1000):
    return {"contractor": "Builder A", "contract": number, "contract_date": dt.datetime(2026, 1, 1),
            "subject": "Работы", "amount": amount, "deadline": deadline}


def acts(*pairs):
    return [{"date": day, "amount": amount} for day, amount in pairs]


def by_number(view):
    return {row["contract"]: row for row in view["rows"]}


def test_deadline_statuses_from_recent_money_pace(project):
    recent = acts(("2026-09-15", 100), ("2026-10-31", 200))
    book(project, [contract("LATE", deadline=dt.datetime(2026, 11, 30)),
                   contract("OK", deadline=dt.datetime(2027, 6, 1)),
                   contract("OVER", deadline=dt.datetime(2026, 10, 1)),
                   contract("STOP", deadline=dt.datetime(2027, 6, 1)),
                   contract("DONE", deadline=dt.datetime(2026, 12, 1), amount=300)],
         acts={"LATE": recent, "OK": recent, "OVER": recent, "DONE": recent,
               "STOP": acts(("2026-07-20", 300))})
    rows = by_number(contracts.build(project, CUT))
    late = rows["LATE"]["risk"]
    # 700 left at 300 per 47 calendar days -> 110 days after the cut.
    assert late["status"] == "late" and late["forecast_finish"] == "2027-02-24"
    assert late["delay_days"] == 86 and late["pace_window"] == ["2026-09-15", "2026-10-31"]
    assert rows["OK"]["risk"]["status"] == "on_track"
    assert rows["OVER"]["risk"]["status"] == "overdue" and rows["OVER"]["risk"]["delay_days"] == 146
    stop = rows["STOP"]["risk"]
    assert stop["status"] == "stalled" and stop["forecast_finish"] is None and "90 дней" in stop["reason"]
    assert rows["DONE"]["risk"]["status"] == "done"


def test_long_old_period_is_not_a_recent_pace():
    long_period = [(dt.date(2026, 1, 1), dt.date(2026, 10, 31), 900.0)]
    result = risk.forecast(amount=1000, completed=900, comparable=True, periods=long_period,
                           cut=dt.date(2026, 11, 6), deadline=dt.date(2026, 12, 31))
    assert result["status"] == "stalled" and result["forecast_finish"] is None


@pytest.mark.parametrize("amount,completed,comparable", [(None, 100, True), (1000, None, True), (1000, 100, False)])
def test_missing_price_execution_or_vat_basis_is_unknown_with_a_reason(amount, completed, comparable):
    periods = [(dt.date(2026, 10, 1), dt.date(2026, 10, 31), 100.0)]
    result = risk.forecast(amount=amount, completed=completed, comparable=comparable, periods=periods,
                           cut=dt.date(2026, 11, 6), deadline=dt.date(2027, 1, 1))
    assert result["status"] == "unknown" and result["forecast_finish"] is None and result["reason"]


def test_payments_join_by_exact_identity_and_cut_and_show_unworked_advance(project):
    base = {"contractor": "Builder A", "contract": "LATE", "contract_date": dt.datetime(2026, 1, 1),
            "source": "Собственные средства"}
    book(project, [contract("LATE", deadline=dt.datetime(2026, 11, 30))],
         acts={"LATE": acts(("2026-09-15", 100), ("2026-10-31", 200))},
         payments=[dict(base, purpose="Аванс по договору", date=dt.datetime(2026, 2, 1), amount=400),
                   dict(base, purpose="Оплата выполненных работ", date=dt.datetime(2026, 10, 5), amount=100),
                   dict(base, purpose="Аванс", date=dt.datetime(2026, 11, 20), amount=999),  # after the cut
                   dict(base, contract_date=dt.datetime(2025, 5, 5), purpose="Аванс",  # another contract
                        date=dt.datetime(2026, 3, 1), amount=777),
                   dict({k: v for k, v in base.items() if k != "contract_date"}, purpose="Аванс",
                        date=dt.datetime(2026, 3, 2), amount=55),
                   dict(base, contractor="Builder B", purpose="Аванс", date=dt.datetime(2026, 3, 3), amount=888)])
    view = contracts.build(project, CUT)
    row, = view["rows"]
    advance = row["advance"]
    assert advance["paid"] == 500 and advance["payments_count"] == 2
    assert advance["paid_advance_labelled"] == 400
    assert advance["unworked"] == 200
    assert advance["unmatched_candidates"] == 1 and advance["unmatched_amount"] == 55
    assert "без даты договора" in advance["reason"]
    summary = view["risk_summary"]
    assert summary["warning_count"] == 1 and summary["counts"]["late"] == 1
    assert summary["unworked_at_risk_total"] == 200 and summary["unworked_at_risk_count"] == 1


def test_missing_payment_register_is_named_not_zero(project):
    book(project, [contract("LATE", deadline=dt.datetime(2026, 11, 30))],
         acts={"LATE": acts(("2026-10-31", 300))})
    path = monitor._project_dir(project) / "estimate" / f"{DAY}.xlsx"
    wb = openpyxl.load_workbook(path)
    del wb["Реестр платежей"]
    wb.save(path)
    view = contracts.build(project, CUT)
    row, = view["rows"]
    assert row["advance"]["paid"] is None and row["advance"]["unworked"] is None
    assert any("Реестр платежей" in w for w in view["warnings"])


def test_execution_without_vat_is_not_compared_with_cash_payments():
    row = {"contractor": "Builder A", "contract": "X", "contract_date": "2026-01-01", "completed": 300.0}
    paid = [{"contractor": "builder a", "contract": "x", "contract_date": dt.date(2026, 1, 1),
             "amount": 500.0, "date": dt.date(2026, 2, 1), "advance_label": True}]
    result = risk.advance(row, paid, contract_number=contracts._contract_number, completed_basis="without_vat")
    assert result["paid"] == 500 and result["unworked"] is None and "НДС" in result["reason"]


@pytest.mark.parametrize("width", [390, 1440])
def test_real_page_shows_signal_strip_risk_filter_and_unworked_advance(project, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    base = {"contractor": "Builder A", "contract_date": dt.datetime(2026, 1, 1), "source": "Собственные средства"}
    recent = acts(("2026-09-15", 100), ("2026-10-31", 200))
    book(project, [contract("LATE", deadline=dt.datetime(2026, 11, 30)),
                   contract("OK", deadline=dt.datetime(2027, 6, 1)),
                   contract("STOP", deadline=dt.datetime(2027, 6, 1))],
         acts={"LATE": recent, "OK": recent, "STOP": acts(("2026-07-20", 300))},
         payments=[dict(base, contract="LATE", purpose="Аванс", date=dt.datetime(2026, 2, 1), amount=500),
                   dict(base, contract="OK", purpose="Оплата", date=dt.datetime(2026, 2, 1), amount=100)])
    view = contracts.build(project, CUT)
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        strip = page.locator('#contractsRisk')
        expect(strip).to_contain_text('Не успевают к сроку')
        expect(strip.locator('button').nth(1)).to_contain_text('1')
        expect(strip.locator('button').nth(3)).to_contain_text('200')
        late = page.locator('tr', has_text='LATE')
        expect(late).to_contain_text('Не успевает к сроку')
        expect(late).to_contain_text('Прогноз окончания: 24.02.2027')
        expect(late).to_contain_text('риск неотработки аванса')
        expect(page.locator('tr', has_text='OK')).to_contain_text('Оплачено не больше выполненного')
        strip.locator('button').first.click()
        expect(page.locator('#contractsFilter')).to_have_value('risk')
        rows = page.locator('#contractsRows tbody tr')
        expect(rows).to_have_count(2)
        assert 'LATE' in rows.nth(0).inner_text() and 'STOP' in rows.nth(1).inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/contract-risk-{width}.png', full_page=True)
        assert not errors


def test_management_summary_reads_the_same_register_signals(project):
    import developaid_management_report as report
    base = {"contractor": "Builder A", "contract_date": dt.datetime(2026, 1, 1), "source": "Собственные средства"}
    book(project, [contract("LATE", deadline=dt.datetime(2026, 11, 30)),
                   contract("OK", deadline=dt.datetime(2027, 6, 1))],
         acts={"LATE": acts(("2026-09-15", 100), ("2026-10-31", 200)),
               "OK": acts(("2026-09-15", 100), ("2026-10-31", 200))},
         payments=[dict(base, contract="LATE", purpose="Аванс", date=dt.datetime(2026, 2, 1), amount=500)])
    block = report.contract_risks(project, dt.date(2026, 11, 6))
    assert block["state"] == "ok" and block["total"] == 2
    row, = block["rows"]
    register = by_number(contracts.build(project, CUT))["LATE"]
    assert row["risk"] == register["risk"] and row["advance"] == register["advance"]
    payload = {"project": "Synthetic", "kind": "week", "start": "2026-11-01", "end": CUT,
               "contract_risks": block}
    payload["findings"] = report.findings(payload)
    main, = [f for f in payload["findings"] if f.get("topic") == "Договоры"]
    assert "не успевают к сроку: 1" in main["text"] and "200" in main["text"]
    html = report.render_html(payload)
    assert "Договоры под угрозой срыва срока" in html and "24.02.2027" in html and "+86 дн" in html
    text = report.render_text(payload)
    assert "LATE" in text and "прогноз 24.02.2027" in text


def test_management_summary_names_a_missing_archive(project):
    import developaid_management_report as report
    block = report.contract_risks(project, dt.date(2026, 11, 6))
    assert block["state"] == "missing" and "накопительных" in block["reason"]
    assert "накопительных" in report._contract_risks_html(block)
