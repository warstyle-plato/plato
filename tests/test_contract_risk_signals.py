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


@pytest.mark.parametrize("amount,completed,comparable,why", [
    (None, None, False, "полной суммы договора"),
    (1000, None, True, "на дату среза не подтверждено"),
    (1000, 0, False, "несопоставимую базу НДС"),
])
def test_past_deadline_does_not_turn_unknown_completion_into_unfinished_work(amount, completed, comparable, why):
    result = risk.forecast(amount=amount, completed=completed, comparable=comparable, periods=[],
                           cut=dt.date.fromisoformat(CUT), deadline=dt.date(2026, 9, 1))
    assert result["status"] == "overdue" and result["label"] == "Срок договора прошёл"
    assert why in result["reason"] and "Завершение по накопительным неизвестно" in result["reason"]
    assert result["forecast_finish"] is None and result["delay_days"] is None
    assert result["remaining"] is None and "не завершены" not in result["label"]


@pytest.mark.parametrize("width", [390, 1440])
def test_unknown_zero_and_full_monetary_completion_keep_distinct_deadline_evidence(project, width):
    import developaid_management_report as report
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page

    book(project, [contract("UNKNOWN", deadline=dt.datetime(2026, 9, 1), amount=None),
                   contract("ZERO", deadline=dt.datetime(2026, 9, 1)),
                   contract("DONE", deadline=dt.datetime(2026, 9, 1))],
         acts={"ZERO": acts(("2026-10-31", 0)), "DONE": acts(("2026-10-31", 1000))})
    view = contracts.build(project, CUT)
    rows = by_number(view)
    assert [rows[key]["completed"] for key in ("UNKNOWN", "ZERO", "DONE")] == [None, 0, 1000]
    assert [rows[key]["completion_ratio"] for key in ("UNKNOWN", "ZERO", "DONE")] == [None, 0, 1]
    assert rows["UNKNOWN"]["risk"]["remaining"] is None
    zero = rows["ZERO"]["risk"]
    assert zero["remaining"] == 1000 and zero["delay_days"] == 66
    assert zero["forecast_finish"] is None and "неизвестно" not in zero["reason"]
    assert rows["DONE"]["risk"]["status"] == "done"
    assert rows["DONE"]["risk"]["remaining"] == 0
    assert "по накопительным достигло полной суммы договора" in rows["DONE"]["risk"]["reason"]
    assert view["risk_summary"]["counts"]["overdue"] == 2

    block = report.contract_risks(project, dt.date.fromisoformat(CUT))
    words = report._contract_risk_words(block)
    assert "срок договора прошёл: 2" in words and "работы не завершены" not in words
    assert "Срок прошёл на 66 дн." in report._contract_risks_html(block)
    assert "Задержка" not in report._contract_risks_html(block)
    assert all("не завершены" not in line for line in report._contract_risk_lines(block))

    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsRisk button').first).to_contain_text('Срок договора прошёл')
        expect(page.locator('#contractsRisk button').first.locator('b')).to_have_text('2')
        unknown_row = page.locator('#contractsRows tr', has_text='UNKNOWN')
        zero_row = page.locator('#contractsRows tr', has_text='ZERO')
        expect(unknown_row).to_contain_text('Для прогноза нужна полная сумма договора.')
        expect(zero_row).to_contain_text('Срок прошёл на 66 дн.')
        assert 'не завершены' not in page.locator('#contractsRisk').inner_text()
        assert 'задержка' not in zero_row.inner_text().casefold()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/plato1030-risk-evidence-{width}.png', full_page=True)
        assert not errors


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
    assert advance["paid"] is None and advance["payments_count"] == 2
    assert advance["confirmed_paid"] == 500
    assert advance["confirmed_paid_advance_labelled"] == 400
    assert advance["unworked"] is None
    assert advance["unmatched_candidates"] == 1 and advance["unmatched_amount"] == 55
    assert "без даты договора" in advance["reason"]
    summary = view["risk_summary"]
    assert summary["warning_count"] == 1 and summary["counts"]["late"] == 1
    assert summary["unworked_at_risk_total"] is None
    assert summary["unworked_at_risk_unknown_count"] == 1


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
    import developaid_management_report as report
    row = {"contractor": "Builder A", "contract": "X", "contract_date": "2026-01-01", "completed": 300.0}
    paid = [{"contractor": "builder a", "contract": "x", "contract_date": dt.date(2026, 1, 1),
             "amount": 500.0, "date": dt.date(2026, 2, 1), "advance_label": True}]
    result = risk.advance(row, paid, reference_key=contracts._reference_key, completed_basis="without_vat")
    assert result["paid"] == 500 and result["unworked"] is None and "НДС" in result["reason"]
    block = {'state': 'ok', 'total': 1, 'rows': [{**row, 'advance': result,
             'risk': {'status': 'late', 'label': 'Не успевает к сроку'}}]}
    assert 'НДС' in report._contract_risks_html(block)
    assert 'переплата не определена' in ' '.join(report._contract_risk_lines(block))


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
    assert "Договоры под угрозой срыва срока" in html and "24.02.2027" in html and "Задержка 86 дн." in html
    text = report.render_text(payload)
    assert "LATE" in text and "прогноз 24.02.2027" in text


def test_management_summary_names_a_missing_archive(project):
    import developaid_management_report as report
    block = report.contract_risks(project, dt.date(2026, 11, 6))
    assert block["state"] == "missing" and "накопительных" in block["reason"]
    assert "накопительных" in report._contract_risks_html(block)


def test_material_delivery_does_not_make_a_late_contract_look_on_time(project):
    base = {"contractor": "Builder A", "contract_date": dt.datetime(2026, 1, 1), "source": "Собственные средства"}
    book(project, [contract("MAT", deadline=dt.datetime(2026, 11, 30))],
         acts={"MAT": acts(("2026-09-15", 500), ("2026-10-31", 200))},
         payments=[dict(base, contract="MAT", purpose="Аванс", date=dt.datetime(2026, 2, 1), amount=800)])
    ledger = project.snapshots[-1]["ledgers"][0]
    # September: 100 of works and 400 of materials supply; October: 200 of works.
    for period, (work, material) in zip(ledger["items"][0]["periods"], [(100, 400), (200, 0)]):
        period.update(work_amount=work, material_amount=material, amount_split=True)
    row, = contracts.build(project, CUT)["rows"]
    assert (row["completed_works"], row["completed_materials"]) == (300, 400)
    result = row["risk"]
    # Works pace 300 per 47 days against 300 left -> 47 days; the total pace
    # (700 per 47 days) would have finished by 27.11 and looked on time.
    assert result["pace_basis"] == "works" and result["status"] == "late"
    assert result["forecast_finish"] == "2026-12-23" and result["delay_days"] == 23
    advance = row["advance"]
    assert advance["basis"] == "works" and advance["unworked"] == 500
    assert advance["unworked_with_materials"] == 100


def test_without_split_the_total_pace_is_named():
    periods = [(dt.date(2026, 10, 1), dt.date(2026, 10, 31), 300.0, None)]
    result = risk.forecast(amount=1000, completed=300, comparable=True, periods=periods,
                           cut=dt.date(2026, 11, 6), deadline=dt.date(2027, 6, 1))
    assert result["pace_basis"] == "total" and "не разделены" in result["reason"]


def payment(number='C-12/7', **changes):
    return {'contractor': 'ООО «Учебный подрядчик»', 'contract': number,
            'contract_date': dt.datetime(2026, 1, 1), 'date': dt.datetime(2026, 10, 31),
            'amount': 500, 'purpose': 'Аванс', **changes}


def alias_contract(number='C-12/7', **changes):
    return contract(number, deadline=dt.datetime(2026, 11, 7)) | {
        'contractor': 'ООО «Учебный подрядчик»', **changes}


@pytest.mark.parametrize('full_party,decorated_number', [(True, False), (False, True), (True, True)])
def test_payment_aliases_use_the_same_identity_as_rss_without_rekeying_headers(project, full_party, decorated_number):
    number = 'C-12/7'
    book(project, [alias_contract(number)], payments=[payment(number)],
         acts={number: acts(('2026-10-31', 300))})
    header = project.snapshots[-1]['ledgers'][0]
    if full_party:
        header['contractor'] = 'Общество с ограниченной ответственностью «Учебный подрядчик»'
    if decorated_number:
        header['contract'] = 'Договор подряда № C-12/7'
    expected_id, = [key for key, _ in contracts._groups([header], project)]
    row, = contracts.build(project, CUT)['rows']
    assert row['id'] == expected_id
    assert row['amount'] == 1000
    assert row['advance']['paid'] == 500 and row['advance']['unworked'] == 200
    assert row['advance']['sources'][0]['row'] == 10
    assert row['advance']['sources'][0]['sheet'] == 'Реестр платежей'


@pytest.mark.parametrize('different_customer', [True, False])
def test_one_payment_is_not_allocated_to_two_legacy_contract_ids(project, different_customer):
    first = alias_contract(customer='Developer A')
    second = alias_contract(customer='Developer B' if different_customer else 'Developer A')
    if not different_customer:
        second['contractor'] = 'Общество с ограниченной ответственностью «Учебный подрядчик»'
        second['contract'] = 'Договор подряда № C-12/7'
    book(project, [first, second], payments=[payment()],
         acts={first['contract']: acts(('2026-10-31', 300)),
               second['contract']: acts(('2026-10-31', 300))})
    view = contracts.build(project, CUT)
    assert len({row['id'] for row in view['rows']}) == 2
    for row in view['rows']:
        assert row['advance']['paid'] is None and row['advance']['unworked'] is None
        assert row['advance']['confirmed_paid'] is None
        assert 'нескольким договорам' in row['advance']['reason']
        assert row['advance']['sources']
    assert view['risk_summary']['unworked_total'] is None
    assert view['risk_summary']['unworked_unknown_count'] == 2


@pytest.mark.parametrize('field,value', [
    ('contractor', None), ('contract', None), ('contract_date', None), ('date', None),
    ('amount', None), ('amount', 'не рассчитано'), ('amount', 'nan'), ('amount', False),
])
def test_incomplete_payment_source_is_unknown_instead_of_a_zero_fact(project, field, value):
    book(project, [alias_contract()], payments=[payment(**{field: value})],
         acts={'C-12/7': acts(('2026-10-31', 300))})
    view = contracts.build(project, CUT)
    row, = view['rows']
    assert row['advance']['paid'] is None and row['advance']['unworked'] is None
    assert row['advance']['reason'] and row['advance']['unmatched_candidates'] == 1
    assert row['advance']['sources'][0]['row'] == 10
    assert view['risk_summary']['unworked_at_risk_total'] is None
    assert view['risk_summary']['unworked_at_risk_unknown_count'] == 1


def test_future_incomplete_payment_is_excluded_before_it_can_obscure_the_cut(project):
    book(project, [alias_contract()], payments=[payment(date=dt.datetime(2026, 12, 1), amount=None)],
         acts={'C-12/7': acts(('2026-10-31', 300))})
    row, = contracts.build(project, CUT)['rows']
    assert row['advance']['paid'] == 0 and row['advance']['unworked'] == 0
    assert not row['advance']['unmatched_candidates']


def test_missing_payment_register_stays_unknown_in_tile_and_management_summary(project):
    import developaid_management_report as report
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    book(project, [alias_contract()], acts={'C-12/7': acts(('2026-10-31', 300))})
    path = monitor._project_dir(project) / 'estimate' / f'{DAY}.xlsx'
    wb = openpyxl.load_workbook(path)
    del wb['Реестр платежей']
    wb.save(path)
    view = contracts.build(project, CUT)
    assert view['risk_summary']['unworked_at_risk_total'] is None
    with browser_page(390) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        tile = page.locator('#contractsRisk button').nth(3)
        expect(tile.locator('b')).to_have_text('—')
        expect(tile).to_contain_text('итог неизвестен')
        expect(page.locator('#contractsRows')).to_contain_text('итог не подтверждён')
        assert not errors
    block = report.contract_risks(project, dt.date.fromisoformat(CUT))
    assert 'итог оплаты сверх выполнения неизвестен' in report._contract_risk_words(block)
    assert 'Реестр платежей не прочитан' in report._contract_risks_html(block)


def test_partial_payment_coverage_has_a_known_part_without_a_false_complete_total(project):
    import developaid_management_report as report
    book(project, [alias_contract('KNOWN'), alias_contract('UNKNOWN')],
         payments=[payment('KNOWN'), payment('UNKNOWN', amount=None)],
         acts={'KNOWN': acts(('2026-10-31', 300)), 'UNKNOWN': acts(('2026-10-31', 300))})
    view = contracts.build(project, CUT)
    rows = by_number(view)
    assert rows['KNOWN']['advance']['paid'] == 500
    assert rows['UNKNOWN']['advance']['paid'] is None
    summary = view['risk_summary']
    assert summary['unworked_at_risk_total'] is None
    assert summary['unworked_at_risk_confirmed_total'] == 200
    assert summary['unworked_at_risk_unknown_count'] == 1
    words = report._contract_risk_words({'total': 2, 'summary': summary})
    assert 'неизвестен' in words and 'известная часть' in words and '200' in words


def test_unknown_forecast_is_not_reported_as_every_contract_being_on_time():
    import developaid_management_report as report
    words = report._contract_risk_words({'total': 1, 'summary': {
        'counts': {'unknown': 1, 'no_deadline': 0}, 'warning_count': 0}})
    assert 'не подтверждён' in words
    assert 'ни один не отстаёт' not in words
