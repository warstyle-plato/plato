"""Synthetic XLSX -> actual readers -> canonical funding; no primary acceptance."""
import datetime
import io

import openpyxl
import pytest

import developaid_actuals as actuals
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_management_report_model import _rss_book
from test_the_approved_budget_says_what_it_is_made_of import _finmodel, SMETA

CUT = datetime.date(2026, 10, 31)


def source_case(tmp_path, monkeypatch, payments=(), limits=None):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    model = tmp_path / 'model.xlsx'
    model.write_bytes(_finmodel())
    # Both the budget and RSS are parsed by real readers. Only project file
    # lookup is isolated, never payment/estimate values or aggregation.
    baseline = dashboard._read_finance_baseline(model)
    monkeypatch.setattr(dashboard, '_finance_baseline', lambda _: baseline)
    rss = tmp_path / 'rss.xlsx'
    book = openpyxl.load_workbook(io.BytesIO(_rss_book(payments)))
    sheet = book[actuals._ESTIMATE_SHEET]
    sheet.delete_rows(1, sheet.max_row)
    limits = dict(SMETA) if limits is None else limits
    for offset, (code, parent) in enumerate([('1', ''), ('1.1', '1'), ('2', ''),
                                            ('2.6', '2'), ('3', ''), ('3.7', '3')], 10):
        sheet.cell(offset, 1, code)
        sheet.cell(offset, 4, 'Учебная статья ' + code)
        value = limits.get(code if not parent else parent)
        if value is not None:
            sheet.cell(offset, 5, value)
        for column in [6, 7, 11]:
            sheet.cell(offset, column, 0)
    paid_sheet = book[actuals._PAYMENTS_SHEET]
    for row in range(10, paid_sheet.max_row + 1):
        paid_sheet.cell(row, 11, 'Заемные средства')
    book.save(rss)
    return rss, dashboard._funding_risk('demo', rss, CUT, {})


@pytest.mark.parametrize('value', [None, 'неизвестно', True, 'NaN', 'inf'])
def test_invalid_payment_amount_survives_xlsx_as_unknown(tmp_path, monkeypatch, value):
    rss, funding = source_case(tmp_path, monkeypatch, [(CUT, value, '2.6')])
    rows = actuals.read_payments(rss, include_incomplete=True)['rows']
    assert rows[0]['amount'] is None
    r = funding['reconciliation']
    assert funding['paid_actual'] is None
    assert r['paid_at_cut'] is None
    assert r['available_bank_limit'] is None
    assert r['calculated_additional'] is None
    assert not r['matches']
    assert funding['own_money']['source_completeness']['payments']['2'] == [
        {'source_row': 10, 'fields': ['amount']}]
    assert r['primary_source_gate'] == 'BLOCKED'


@pytest.mark.parametrize('value', [None, 'неизвестно', True, 'NaN', '-inf'])
def test_invalid_limit_survives_legacy_estimate_conversion(tmp_path, monkeypatch, value):
    limits = {**SMETA, '2': value}
    rss, funding = source_case(tmp_path, monkeypatch, [(CUT, 20_000, '2.6')], limits)
    estimate = actuals.read_estimate(rss)
    assert estimate['by_code']['2']['money_values']['estimate'] is None
    assert estimate['by_code']['2']['source']['columns']['estimate'] == 5
    assert dashboard._rss_ch23(estimate, ('1', '2', '3'))['limit'] is None
    r = funding['reconciliation']
    assert funding['bank_limit'] is None
    assert r['bank_limit_total'] is None
    assert r['available_bank_limit'] is None
    assert r['calculated_additional'] is None
    assert r['paid_at_cut'] == 20_000
    assert not r['matches']


@pytest.mark.parametrize('future_amount', [1_000_000, 'неизвестно', None])
def test_future_payment_is_filtered_before_amount_validation(tmp_path, monkeypatch, future_amount):
    rss, funding = source_case(tmp_path, monkeypatch, [
        (CUT, 20_000, '2.6'), (datetime.date(2026, 11, 2), future_amount, '2.6')])
    r = funding['reconciliation']
    assert funding['paid_actual'] == r['paid_at_cut'] == 20_000
    assert r['calculated_additional'] == 210_000
    assert r['matches']
    assert dashboard._paid_since(rss, actuals.read_estimate(rss), '2',
                                 datetime.date(2026, 10, 1), CUT) == 20_000


@pytest.mark.parametrize('day', [None, 'неизвестно', True])
def test_undated_target_payment_is_not_lost(tmp_path, monkeypatch, day):
    rss, funding = source_case(tmp_path, monkeypatch, [(day, 20_000, '2.6')])
    assert funding['reconciliation']['paid_at_cut'] is None
    assert funding['reconciliation']['calculated_additional'] is None
    assert dashboard._paid_since(rss, actuals.read_estimate(rss), '2',
                                 datetime.date(2026, 10, 1), CUT) is None
    assert not funding['reconciliation']['need_breakdown']['work_allocation_known']


def test_zero_and_refunds_are_preserved_with_closed_date_bounds(tmp_path, monkeypatch):
    rss, funding = source_case(tmp_path, monkeypatch, [
        (datetime.date(2026, 9, 30), 500, '2.6'),
        (datetime.date(2026, 10, 1), 25_000, '2.6'),
        (datetime.date(2026, 10, 15), 0, '2.6'),
        (CUT, -5_000, '2.6'),
        (datetime.date(2026, 11, 1), 1_000_000, '2.6')])
    estimate = actuals.read_estimate(rss)
    assert len(actuals.read_payments(rss, include_incomplete=True)['rows']) == 5
    assert funding['reconciliation']['paid_at_cut'] == 20_500
    assert dashboard._paid_since(rss, estimate, '2', datetime.date(2026, 10, 1), CUT) == 20_000
    assert dashboard._paid_in_chapters(rss, estimate, ('2',), cut=CUT)['total'] == 20_500
    assert dashboard._plan_still_owed({'2026-10-01': 100.}, datetime.date(2026, 10, 1),
                                      -5., CUT) == {'2026-10-01': 105.}


def test_unknown_amount_before_baseline_does_not_poison_the_delta(tmp_path, monkeypatch):
    rss, _ = source_case(tmp_path, monkeypatch, [
        (datetime.date(2026, 9, 30), 'неизвестно', '2.6'), (CUT, 20_000, '2.6')])
    assert dashboard._paid_since(rss, actuals.read_estimate(rss), '2',
                                 datetime.date(2026, 10, 1), CUT) == 20_000


def test_confirmed_zero_payment_and_limit_stay_known(tmp_path, monkeypatch):
    rss, funding = source_case(tmp_path, monkeypatch, [(CUT, 0, '2.6')],
                               {**SMETA, '2': 0})
    r = funding['reconciliation']
    assert r['paid_at_cut'] == 0
    assert r['bank_limit_total'] == 330_000
    assert r['calculated_additional'] == 1_110_000
    assert r['matches']
