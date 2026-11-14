"""Loan draws preserve unknown source scope/date/amount without guessing zero."""
import datetime as dt
import io

import openpyxl
import pytest

import developaid_management_report as report
import developaid_monitor as monitor
from test_management_report_funding import PROJECT, _rss_with_sources
from test_management_report_model import _gpr_book

BOUNDS = report.period_bounds('week', '2026-10-18')


def row(day, amount, scope=True):
    return {'date': day, 'amount': amount, 'scope': scope, 'source_row': 10}


@pytest.mark.parametrize('gap', [row(dt.date(2026, 10, 15), 11, None),
                               row(dt.date(2026, 10, 15), None), row(None, 11)])
def test_unreadable_selected_rows_keep_unknown_totals_and_separate_known_parts(gap):
    got = report._sums([row(dt.date(2026, 10, 15), 12), gap], BOUNDS, lambda item: item['scope'])
    assert got['period'] is None and got['month'] is None and got['total'] is None
    assert got['known_part'] == {'period': 12, 'month': 12, 'total': 12}
    assert got['state'] == 'incomplete' and got['incomplete_rows']
    assert got['payments_complete_through_cut'] is None


def test_an_earlier_unknown_scope_does_not_poison_later_unaffected_time_windows():
    got = report._sums([row(dt.date(2026, 9, 15), 11, None),
                        row(dt.date(2026, 10, 15), 12)], BOUNDS, lambda item: item['scope'])
    assert got['period'] == got['month'] == 12
    assert got['total'] is None and got['known_part']['total'] == 12


def test_known_future_and_proven_outside_rows_are_excluded_before_unknown_validation():
    got = report._sums([row(dt.date(2026, 10, 19), None, None), row(None, None, False),
                        row(dt.date(2026, 10, 15), 0), row(dt.date(2026, 10, 15), 15),
                        row(dt.date(2026, 10, 15), -3)], BOUNDS, lambda item: item['scope'])
    assert got['period'] == got['month'] == got['total'] == 12
    assert got['state'] == 'observed' and not got['incomplete_rows']


def test_an_unknown_month_and_an_undated_payment_cannot_be_a_known_cumulative_zero():
    months = ['2026-09', '2026-10', '2026-11']
    assert report._cumulative_observed({'2026-09': 5, '2026-10': None}, months) == [5, None, None]
    assert report._cumulative_observed({'2026-09': 5}, months, undated=True) == [None, None, None]


@pytest.mark.parametrize('code', ['2.999', '4.999', None])
def test_actual_rss_report_and_tile_keep_unknown_draws_and_known_parts(tmp_path, monkeypatch, code):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    monitor.store_schedule(PROJECT, _gpr_book({}), None, '2026-07-01')
    book = openpyxl.load_workbook(io.BytesIO(_rss_with_sources()))
    payments = book['Реестр платежей']
    payments['G12'] = code  # Previously known 30m borrowed payment in the selected week.
    data = io.BytesIO()
    book.save(data)
    book.close()
    monitor.store_estimate(PROJECT, data.getvalue(), '2026-10-18')
    limit = {'known': True, 'chapters': ['2', '3'], 'bank_limit': 1000000000,
             'paid_actual': None, 'bank_remaining': 0, 'reserve': 0,
             'additional_financing': 0}
    view = {'dashboard': {'funding': limit}}
    monkeypatch.setattr(report, '_monitor_view', lambda *_: view)
    built = report.build(PROJECT, 'week', '2026-10-18')
    draws = built['funding']['draws']
    assert draws['total'] is None and draws['period'] is None
    assert draws['known_part']['total'] == 418000000
    assert built['funding']['draws_monthly']['2026-10'] is None
    tile = next(item for item in report.tiles(built) if item['label'] == 'Выбрано у банка')
    assert tile['value'] == 'нет данных'
    assert 'Известная часть' in tile['note'] and 'не полный итог' in tile['note']
    assert 'Известная часть' in report.render_html(built) and 'Известная часть' in report.render_text(built)
