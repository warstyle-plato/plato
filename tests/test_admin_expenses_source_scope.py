"""AHR snapshot cells need proved units; unknown date never becomes a cut fact."""
import io
import json

import openpyxl
import pytest

import developaid_admin_expenses as admin
import developaid_admin_expenses_source as proof
import developaid_monitor as monitor
from test_admin_expenses_visible_without_bank_reconciliation import _finmodel, ROWS


def workbook(unit):
    wb = openpyxl.load_workbook(io.BytesIO(_finmodel()))
    wb['cf_1_new']['B2'] = unit
    out = io.BytesIO(); wb.save(out); wb.close()
    return out.getvalue()


@pytest.mark.parametrize('unit,factor', [('руб.', 1), ('Все суммы в тыс. руб.', 1000), ('млн руб.', 1000000)])
def test_only_the_observed_header_scale_controls_ruble_conversion(unit, factor):
    result = admin.read(workbook(unit), taken_at='2026-11-01', cut='2026-11-13')
    assert result['total'] == 40 * factor and result['fact'] == 20 * factor
    assert result['source']['unit_factor_to_rubles'] == factor
    assert result['source']['unit_evidence']['state'] == 'observed'
    assert result['cut_eligibility'] == 'eligible'
    assert result['amounts_at_cut']['total'] == result['total']
    assert not result['financial_acceptance']


@pytest.mark.parametrize('unit', [None, 'руб./м²', 'тыс. руб. на 1 м²', 'тыс. руб. и млн руб.'])
def test_unknown_or_conflicting_units_never_assume_thousands(unit):
    result = admin.read(workbook(unit), taken_at='2026-11-01', cut='2026-11-13')
    assert result['state'] == 'unit_unknown'
    assert all(result[key] is None for key, _ in admin.FIELDS)
    assert all(value is None for value in result['amounts_at_cut'].values())
    assert all(tile['value'] == 'нет данных' for tile in admin.tiles(result))
    assert 'единиц' in result['reason'].lower()
    assert [row['code'] for row in result['rows']] == ['2.4.1']


def test_undated_current_snapshot_keeps_values_and_unknown_cut_membership_separate():
    result = admin.read(workbook('тыс. руб.'), cut='2026-11-13')
    assert result['state'] == 'current_source_only' and result['scope'] == 'raw_saved_snapshot'
    assert result['source_date_state'] == 'unknown' and result['source']['taken_at'] == ''
    assert result['total'] == 40000 and result['fact'] == 20000 and result['plan'] == 20000
    assert result['cut_eligibility'] == 'unknown' and not result['historical_eligibility_evaluated']
    assert all(value is None for value in result['amounts_at_cut'].values())
    assert all('не отнесены к выбранной дате' in tile['note'] for tile in admin.tiles(result))
    assert not result['financial_acceptance']
    assert {'bank_limit', 'gap', 'additional_financing'}.isdisjoint(result)


def test_a_known_future_source_never_supplies_historical_amounts():
    result = admin.read(workbook('млн руб.'), taken_at='2026-11-14', cut='2026-11-13')
    assert result['state'] == 'source_after_cut' and result['cut_eligibility'] == 'future'
    assert all(result[key] is None for key, _ in admin.FIELDS)
    assert all(row[key] is None for row in result['rows'] for key, _ in admin.FIELDS)
    assert all(value is None for value in result['amounts_at_cut'].values())
    assert 'позже выбранного среза' in result['reason']


def test_overflow_of_a_leaf_sum_is_unknown_and_json_remains_finite():
    rows = {**ROWS, '2.4.1': ('A', 1e308, 0, 0), '2.4.2': ('B', 1e308, 0, 0)}
    wb = openpyxl.load_workbook(io.BytesIO(_finmodel(rows))); wb['cf_1_new']['B2'] = 'руб.'
    out = io.BytesIO(); wb.save(out); wb.close()
    result = admin.read(out.getvalue(), taken_at='2026-11-01', cut='2026-11-13')
    assert result['total'] is None and result['total_known_part'] is None
    assert 'числовой диапазон' in result['reason']
    json.dumps(result, allow_nan=False)


def test_project_reader_uses_the_shared_bounded_projection_and_preserves_its_scope(monkeypatch):
    calls = []
    rows, headers, units = proof._cells(workbook('тыс. руб.'))
    projection = {'source': {'sha256': 'a'*64, 'version_date': None},
                  'scope': 'raw_saved_snapshot', 'rows': rows, 'header_cells': headers,
                  'unit_evidence': units, 'financial_acceptance': False}
    def capture(project, *, runtime):
        calls.append((project, runtime)); return projection
    monkeypatch.setattr(proof, 'capture_saved_snapshot', capture)
    result = admin.for_project('Synthetic project', '2026-11-13')
    assert calls == [('Synthetic project', {})]
    assert result['scope'] == 'raw_saved_snapshot' and result['cut_eligibility'] == 'unknown'
    assert result['total'] == 40000 and all(v is None for v in result['amounts_at_cut'].values())


def test_source_pair_replacement_during_projection_never_returns_old_amounts(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    original = workbook('тыс. руб.')
    monitor.replace_finance_baseline('Synthetic', original, '2026-11-01', 'synthetic.xlsx')
    real = proof._cells
    def changed(data):
        result = real(data)
        replacement = workbook('руб.')
        monitor.replace_finance_baseline('Synthetic', replacement, '2026-11-02', 'replacement.xlsx')
        return result
    monkeypatch.setattr(proof, '_cells', changed)
    result = admin.for_project('Synthetic', '2026-11-13')
    assert result['state'] == 'missing' and result['total'] is None
    assert 'меняется' in result['reason']


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('change', ['project', 'cut', 'denied'])
def test_current_snapshot_scope_stays_visible_and_private_context_changes_scrub_it(width, change):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    model = admin.read(workbook('тыс. руб.'), cut='2026-11-13')
    view = {'admin_expenses': model, 'admin_expenses_html': admin.render(model), 'dashboard': {}}
    with browser_page(width) as (page, responses, errors):
        page.evaluate("v=>{currentView=v;renderDash(v);selectMonitorTab('money')}", view)
        card = page.locator('#adminExpensesCard')
        expect(card).to_be_visible()
        expect(card).to_contain_text('Дата версии текущей сохранённой финмодели не указана')
        assert card.locator('small').filter(has_text='не отнесены к выбранной дате').count() == 3
        assert not page.evaluate('currentView.admin_expenses.financial_acceptance')
        if change == 'project':
            page.locator('#project').fill('Other synthetic project')
        elif change == 'cut':
            page.locator('#cut').fill('2026-10-31')
        else:
            page.evaluate("()=>checkAuthResponse({status:403,ok:false},'Synthetic denied',adminKey(),authEpoch)")
        expect(card).to_be_hidden()
        assert card.inner_text() == ''
        assert page.evaluate('!currentView || (!currentView.admin_expenses && !currentView.admin_expenses_html)')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


def test_unknown_source_scope_does_not_push_the_build_block_off_the_second_pdf_page():
    from browser import chromium_or_skip
    from test_management_report_analytics import _full
    import developaid_management_report as report
    import pymupdf
    from market_search import report_pdf
    model = admin.read(workbook(None), cut='2026-11-13')
    data = _full(); data['admin_expenses'] = model
    document = report_pdf.document(report.render_html(data), style=report.REPORT_STYLE, title='Synthetic AHR scope')
    raw = report_pdf.render(document, footer='Synthetic', executable_path=str(chromium_or_skip()))
    pdf = pymupdf.open(stream=raw, filetype='pdf')
    assert any(hit.y0 < 120 for hit in pdf[1].search_for('Стройка'))
    all_text = ' '.join(''.join(page.get_text() for page in pdf).split()).casefold()
    for label in ['АХР — всего', 'АХР — факт по финмодели', 'АХР — осталось по финмодели']:
        assert label.casefold() in all_text
    assert 'не отнесены к выбранной дате' in all_text


def test_an_invalid_metadata_date_is_not_repaired_from_a_date_prefix():
    result = admin.read(workbook('тыс. руб.'), taken_at='2026-11-01-not-a-version-date', cut='2026-11-13')
    assert result['source_date_state'] == 'unknown' and result['source']['taken_at'] == ''
    assert result['cut_eligibility'] == 'unknown' and result['amounts_at_cut']['total'] is None
