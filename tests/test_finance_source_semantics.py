"""Monetary source identity, observed unit scales and order-independent leaves."""
import concurrent.futures
import datetime as dt
import io

import openpyxl
import pytest

import developaid_actuals as actuals
import developaid_monitor_dashboard as dashboard
from test_finance_money_bridge import source as monetary_source, read as read_monetary_source
from test_funding_strict_source_readers import source_case
from test_the_approved_budget_says_what_it_is_made_of import _finmodel, ROWS


def model(unit):
    book = openpyxl.load_workbook(io.BytesIO(_finmodel()))
    book['cf_1_new']['B2'] = unit
    out = io.BytesIO()
    book.save(out)
    book.close()
    out.name = 'synthetic-unit.xlsx'
    return out


@pytest.mark.parametrize('unit', [None, 'PRIVATE-UNIT-CANARY', 'руб./м²', 'тыс. руб. и млн руб.'])
def test_missing_ambiguous_or_specific_units_do_not_produce_known_project_money(unit):
    got = dashboard._read_finance_baseline(model(unit))
    assert not got['known'] and 'единиц' in got['reason'].lower()
    assert got['unit_evidence']['state'] != 'observed'


@pytest.mark.parametrize('unit,factor', [('руб.', 1), ('тыс. руб.', 1000), ('млн руб.', 1000000)])
def test_unit_scale_is_local_and_shared_by_budget_and_monetary_formula_proof(unit, factor):
    got = read_monetary_source(monetary_source(unit=unit))
    assert got['known']
    assert got['approved'] == pytest.approx(360 * factor)
    comp = got['budget_composition']
    assert comp['unit_scale'] == factor
    assert comp['unit_evidence']['recognized_unit'] == unit
    admin = dashboard._admin_expenses(comp, got['chapter_flow'])
    assert admin['by_chapter']['2']['total'] == pytest.approx(275 * factor)
    assert admin['by_chapter']['3']['total'] == pytest.approx(77.5 * factor)
    assert admin['unallocated']['total'] == pytest.approx(7.5 * factor)
    assert sum(row['total'] for row in got['chapter_flow'].values()) == pytest.approx(got['approved'])


def test_parallel_projects_with_different_unit_scales_do_not_share_mutable_scale():
    units = [('руб.', 1), ('млн руб.', 1000000)] * 4
    def run(item):
        unit, factor = item
        got = dashboard._read_finance_baseline(model(unit))
        return got['approved'], factor
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        assert all(amount == 1440 * factor for amount, factor in executor.map(run, units))


def test_nonstandard_numbering_inside_one_rss_chapter_is_preserved(tmp_path, monkeypatch):
    rss, _ = source_case(tmp_path, monkeypatch)
    book = openpyxl.load_workbook(rss)
    sheet = book[actuals._ESTIMATE_SHEET]
    sheet['A13'] = '2.9'
    sheet['A14'], sheet['D14'] = '2.3.1', 'Synthetic numbering inside chapter two'
    # Remove the now displaced chapter3 child so hierarchy remains explicit.
    sheet['A15'] = None
    book.save(rss)
    book.close()
    estimate = actuals.read_estimate(rss)
    keep = dashboard.payment_in_chapters(estimate, ('2',))
    assert keep({'estimate_code': '2.3.1'}) is True


@pytest.mark.parametrize('code', ['2.6', '2'])
def test_duplicate_rss_code_cannot_establish_a_payment_money_chapter(tmp_path, monkeypatch, code):
    rss, _ = source_case(tmp_path, monkeypatch)
    book = openpyxl.load_workbook(rss)
    sheet = book[actuals._ESTIMATE_SHEET]
    sheet['A25'], sheet['D25'], sheet['E25'] = code, 'Synthetic duplicate', 123
    book.save(rss)
    book.close()
    estimate = actuals.read_estimate(rss)
    assert dashboard.payment_in_chapters(estimate, ('1', '2', '3'))({'estimate_code': '2.6'}) is None
    if code == '2':
        assert dashboard._rss_ch23(estimate, ('1', '2', '3'))['limit'] is None


@pytest.mark.parametrize('code', ['2.999', '4.999'])
def test_payment_code_absent_from_source_is_neither_inside_nor_proven_outside(tmp_path, monkeypatch, code):
    rss, funding = source_case(tmp_path, monkeypatch, [(dt.date(2026, 10, 31), 123, code)])
    estimate = actuals.read_estimate(rss)
    assert dashboard.payment_in_chapters(estimate, ('1', '2', '3'))({'estimate_code': code}) is None
    assert funding['reconciliation']['paid_at_cut'] is None


def test_parent_hierarchy_contradicting_explicit_chapter_is_not_a_money_allocation(tmp_path, monkeypatch):
    rss, _ = source_case(tmp_path, monkeypatch)
    book = openpyxl.load_workbook(rss)
    sheet = book[actuals._ESTIMATE_SHEET]
    sheet['A11'], sheet['A13'] = '2.6', '1.1'
    book.save(rss)
    book.close()
    estimate = actuals.read_estimate(rss)
    assert dashboard.payment_in_chapters(estimate, ('1', '2', '3'))({'estimate_code': '2.6'}) is None


def test_duplicate_fm_leaf_and_ambiguous_monetary_headers_fail_closed():
    for duplicate_header in (False, True):
        book = openpyxl.load_workbook(io.BytesIO(_finmodel()))
        sheet = book['cf_1_new']
        if duplicate_header:
            sheet['L6'] = 'ИТОГО'
        else:
            sheet.cell(sheet.max_row + 1, 3, '2.2.1')
        raw = io.BytesIO()
        book.save(raw)
        book.close()
        raw.name = 'synthetic-ambiguous.xlsx'
        assert not dashboard._read_finance_baseline(raw)['known']


def test_narrow_nbsp_is_read_in_the_actual_fm_leaf_total():
    book = openpyxl.load_workbook(io.BytesIO(_finmodel()))
    sheet = book['cf_1_new']
    sheet['I8'], sheet['J8'] = '1\u202f234,50', '1\u202f234,50'
    raw = io.BytesIO()
    book.save(raw)
    book.close()
    raw.name = 'synthetic-narrow-nbsp.xlsx'
    got = dashboard._read_finance_baseline(raw)
    assert got['budget_composition']['known_fields']['total']
    assert got['approved'] == 2374500


def test_undated_raw_source_scope_is_visible_in_canonical_rows_and_every_funding_tile(tmp_path, monkeypatch):
    import developaid_management_report as report
    from test_funding_source_dates import source_case as report_case
    built, view = report_case(tmp_path, monkeypatch, missing_dates=True)
    funding = view['dashboard']['funding']
    result = funding['reconciliation']
    assert result['observation_scope'] == 'raw_saved_sources'
    assert result['payments_complete_through_cut'] is None
    assert not result['financial_acceptance_performed']
    assert result['amounts_at_selected_cut'] is None
    note = result['source_scope_note']
    assert 'Дата версии' in note and 'не указана' in note and 'Полнота оплат' in note
    rows = {row['key']: row for row in result['display_rows']}
    for key in ('budget', 'paid_at_cut', 'available_bank_limit', 'calculated_additional'):
        assert note in rows[key]['note']
    tiles = {row['label']: row for row in report.tiles(built)}
    for label in ('Утверждённый бюджет', 'Лимит банка', 'Оплачено с начала проекта',
                  'Доступный остаток лимита банка', 'Расчётная дополнительная потребность'):
        assert tiles[label]['note'].count(note) == 1
    assert note in report.render_text(built) and note in report.render_html(built)


def test_reordered_fm_parent_has_the_same_membership_and_sum():
    names = list(reversed(ROWS))
    raw = io.BytesIO(_finmodel({code: ROWS[code] for code in names}))
    raw.name = 'synthetic-reversed.xlsx'
    got = dashboard._read_finance_baseline(raw)
    assert got['known'] and got['approved'] == 1440000
    assert {row['code'] for row in got['budget_composition']['budget_items']} == {'2.1.1', '2.2.1', '2.3.1', '2.4.1'}


def test_narrow_nbsp_and_invalid_saved_money_remain_distinct():
    assert actuals.money_value('1\u202f234,50') == actuals.money_value('1\u00a0234,50') == 1234.5
    assert actuals._money('1\u202f234,50') == 1234.5
    for value in (None, False, True, 'NaN', 'Infinity', 'PRIVATE-MONEY-CANARY'):
        assert actuals.money_value(value) is None
