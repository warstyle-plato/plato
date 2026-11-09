"""Synthetic monthly monetary sources override dictionary classification."""
import datetime as dt
import io
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
import pytest
from openpyxl.worksheet.table import Table

import developaid_monitor_dashboard as dashboard


def source(*, coefficient=.25, formula_suffix=None, cached_fact=None, invalid_bank=False, amount=100_000, plan_formula=None, missing_aggregate=None, total_override=None, bank_code=None, future_bank='2.6'):
    wb = openpyxl.Workbook()
    cf = wb.active
    cf.title = 'cf_1_new'
    cf['I6'], cf['J6'], cf['K6'] = 'ИТОГО', 'ФАКТ', 'ПЛАН'
    cf['M5'], cf['N5'] = 'факт', 'план'
    cf['M6'], cf['N6'] = dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1)
    cf['C7'], cf['D7'] = '2.4.1', 'Административные расходы'
    cf['A51'] = coefficient
    fact = 160 * (1 - coefficient) if cached_fact is None else cached_fact
    cf['I7'], cf['J7'], cf['K7'] = fact + 240, fact, 240
    suffix = '*(1-$A$51)' if formula_suffix is None else formula_suffix
    cf['M7'] = '=SUMIFS(Payments[Amount],Payments[Model],$C7,Payments[Month],M$6)/1000' + suffix
    cf['N7'] = '=SUMPRODUCT(Funding!$D$2:$D$3*(Funding!$A$2:$A$3=$C7)*(Funding!$D$1:$D$1=N$6))/1000'
    if plan_formula is not None:
        cf['N7'] = plan_formula
    if missing_aggregate:
        cf[missing_aggregate] = None
    if total_override is not None:
        cf['I7'] = total_override
    ledger = wb.create_sheet('History')
    ledger.append(['Amount', 'Model', 'Month', 'Код банк'])
    ledger.append([amount, '2.4.1', dt.datetime(2026, 1, 1), '2.6'])
    ledger.append([50_000, '2.4.1', dt.datetime(2026, 1, 1), bank_code if bank_code is not None else '#REF!' if invalid_bank else '3.1'])
    ledger.append([10_000, '2.4.1', dt.datetime(2026, 1, 1), None])
    ledger.add_table(Table(displayName='Payments', ref='A1:D4'))
    future = wb.create_sheet('Funding')
    future.append(['Model', 'Unused', 'Код банк', dt.datetime(2026, 2, 1)])
    future.append(['2.4.1', None, future_bank, 200_000])
    future.append(['2.4.1', None, '3.1', 40_000])
    mapping = wb.create_sheet('статьи_БДДС')
    mapping.cell(3, 7, '2.4.1.1')
    mapping.cell(3, 8, 'Только справочник')
    mapping.cell(3, 9, '2.6')
    raw = io.BytesIO()
    wb.save(raw)
    # openpyxl cannot write formula caches. Populate only the two synthetic
    # caches, matching a saved/recalculated Excel input, without evaluating it.
    out = io.BytesIO()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(out, 'w') as dest:
        for member in src.infolist():
            content = src.read(member.filename)
            if member.filename == 'xl/worksheets/sheet1.xml':
                root = ET.fromstring(content)
                for cell in root.findall('{*}sheetData/{*}row/{*}c'):
                    if cell.attrib['r'] in ('M7', 'N7'):
                        value = cell.find('{*}v')
                        value.text = str(fact if cell.attrib['r'] == 'M7' else 240)
                content = ET.tostring(root)
            dest.writestr(member, content)
    return out.getvalue()


def read(raw):
    stream = io.BytesIO(raw)
    stream.name = 'synthetic.xlsx'
    return dashboard._read_finance_baseline(stream)


@pytest.mark.parametrize('coefficient', [.25, .4])
def test_formula_sources_supply_money_in_two_chapters_despite_single_dictionary_chapter(coefficient):
    model = read(source(coefficient=coefficient))
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    factor = 1 - coefficient
    assert admin['by_chapter']['2'] == pytest.approx({'total': 100_000 * factor + 200_000,
                                                    'paid': 100_000 * factor, 'to_pay': 200_000})
    assert admin['by_chapter']['3'] == pytest.approx({'total': 50_000 * factor + 40_000,
                                                    'paid': 50_000 * factor, 'to_pay': 40_000})
    assert admin['unallocated'] == pytest.approx({'total': 10_000 * factor, 'paid': 10_000 * factor, 'to_pay': 0})
    assert not admin['allocation_known']  # blank bank code is a monetary unknown
    assert model['approved'] == admin['total'] == sum(f['total'] for f in model['chapter_flow'].values())
    assert admin['items'][0]['dictionary_chapter_candidates'] == ['2']
    assert admin['items'][0]['chapter_candidates'] == ['2', '3']
    proof = admin['items'][0]['money_allocation']['proofs'][0]
    assert proof['sources'][0]['coefficient_sources'] == [{'sheet': 'cf_1_new', 'cell': 'A51', 'value': coefficient}]
    assert admin['paid_at_cut'] is None and admin['bank_coverage'] is None


@pytest.mark.parametrize('suffix', ['*(1-$A$51)^2', '*0.75', '+123', '/0'])
def test_unsupported_formula_keeps_verified_future_and_an_explicit_historic_residual(suffix):
    model = read(source(formula_suffix=suffix))
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert admin['total'] == 360_000
    assert admin['by_chapter']['2'] == {'total': 200_000, 'paid': 0, 'to_pay': 200_000}
    assert admin['by_chapter']['3'] == {'total': 40_000, 'paid': 0, 'to_pay': 40_000}
    assert admin['unallocated'] == {'total': 120_000, 'paid': 120_000, 'to_pay': 0}
    assert any('не поддержана' in reason for reason in admin['reasons'])
    assert not admin['allocation_known']


def test_cached_month_disagreement_does_not_proportionally_force_a_match():
    model = read(source(cached_fact=121))
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert admin['total'] == 361_000
    assert admin['unallocated']['paid'] == 121_000
    assert admin['by_chapter']['2']['paid'] == admin['by_chapter']['3']['paid'] == 0
    assert any('не равны сохранённой сумме' in reason for reason in admin['reasons'])
    assert sum(row['total'] for row in admin['by_chapter'].values()) + admin['unallocated']['total'] == admin['total']


def test_missing_bank_code_is_not_outside_the_bank_and_does_not_block_known_global_gap():
    model = read(source(invalid_bank=True))
    own = dashboard._own_money(model['budget_composition'], {'1': 0, '2': 200_000, '3': 50_000},
        {c: {'total': 0, 'borrowed': 0} for c in ('1', '2', '3')}, ['1', '2', '3'], dt.date(2026, 2, 28),
        chapter_flow=model['chapter_flow'])
    admin = own['admin']
    assert admin['unallocated']['total'] == 45_000
    assert own['reconciliation']['budget'] == 360_000
    assert own['reconciliation']['calculated_additional'] == 110_000
    components = {row['kind']: row['amount'] for row in own['reconciliation']['components']}
    assert components['unallocated_budget'] == 45_000
    assert components['outside_bank_scope'] == 0
    assert own['reconciliation']['matches']


@pytest.mark.parametrize('amount', ['100000', '#REF!', True])
def test_non_numeric_source_cells_never_acquire_a_monetary_bank_split(amount):
    model = read(source(amount=amount))
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert admin['unallocated']['paid'] == 120_000
    assert admin['by_chapter']['2']['paid'] == admin['by_chapter']['3']['paid'] == 0
    assert any('нечисловое' in reason for reason in admin['reasons'])


def test_all_unsupported_expressions_cannot_restore_a_dictionary_money_chapter():
    model = read(source(formula_suffix='*0.75', plan_formula='=123+117'))
    item = model['budget_composition']['admin_items'][0]
    assert item['chapter'] == ''
    assert item['chapter_candidates'] == []
    assert item['dictionary_chapter_candidates'] == ['2']
    assert model['chapter_flow']['']['total'] == model['approved'] == 360_000
    assert model['chapter_flow']['']['monthly'] == {'2026-02-01': 240_000}
    assert model['approved_by_chapter'].get('2', 0) == 0


@pytest.mark.parametrize('cell, field', [('I7', 'total'), ('J7', 'fact'), ('K7', 'plan')])
def test_missing_aggregate_is_not_added_again_as_a_legacy_zero(cell, field):
    model = read(source(missing_aggregate=cell))
    assert not model['budget_composition']['known_fields'][field]
    assert sum(split['total'] for split in model['chapter_flow'].values()) == 360_000
    assert model['budget_composition']['admin_items'][0]['money_allocation']['by_chapter']['']['total'] == 7_500
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert admin[{'total': 'total', 'fact': 'paid', 'plan': 'to_pay'}[field]] is None
    if field != 'plan':
        assert admin['by_chapter']['2']['to_pay'] == 200_000
        assert admin['by_chapter']['3']['to_pay'] == 40_000
    if field != 'fact':
        assert admin['by_chapter']['2']['paid'] == 75_000
        assert admin['by_chapter']['3']['paid'] == 37_500


@pytest.mark.parametrize('total', [100, 500])
def test_aggregate_contradiction_is_not_a_signed_unallocated_plug(total):
    model = read(source(total_override=total))
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert admin['total'] == admin['unallocated']['total'] == total * 1000
    assert admin['by_chapter'] == {}
    assert sum(split['total'] for split in model['chapter_flow'].values()) == total * 1000
    assert not admin['allocation_known']
    assert any('противоречие итогов' in reason for reason in admin['reasons'])


def test_unrecognized_numeric_bank_chapter_is_unknown_not_outside_bank():
    model = read(source(bank_code='9.99'))
    admin = dashboard._admin_expenses(model['budget_composition'], model['chapter_flow'])
    assert set(admin['by_chapter']) == {'2', '3'}
    assert admin['unallocated']['paid'] == 45_000
    assert '9' not in model['chapter_flow']
    parts = admin['items'][0]['money_allocation']['parts']
    assert any(p['bank_code'] == '9.99' and p['bank_chapter'] == '' for p in parts)


def test_historical_admin_chapter_cannot_move_a_verified_future_plan_to_the_wrong_schedule():
    from developaid_funding_reconciliation import admin_schedule_policy
    model = read(source(future_bank='3.1'))
    comp = model['budget_composition']
    schedule = {'source_sha256': 'b' * 64, 'paid_since': 0,
        'admin_coverage': {'basis': 'reviewed_sources', 'cut': '2026-02-28',
            'budget_sha256': comp['source_sha256'], 'schedule_sha256': 'b' * 64,
            'items': [{'code': '2.4.1', 'source_row': 7, 'bank_chapter': '2', 'state': 'excluded'}]}}
    result = admin_schedule_policy(comp, schedule, '2', '2026-02-28')
    assert result['items'] == []
    assert result['added_to_need'] == 0


def test_a_review_record_cannot_put_an_entire_verified_split_plan_into_one_chapter():
    from developaid_funding_reconciliation import admin_schedule_policy
    model = read(source())
    comp = model['budget_composition']
    schedule = {'source_sha256': 'b' * 64, 'paid_since': 0,
        'admin_coverage': {'basis': 'reviewed_sources', 'cut': '2026-02-28',
            'budget_sha256': comp['source_sha256'], 'schedule_sha256': 'b' * 64,
            'items': [{'code': '2.4.1', 'source_row': 7, 'bank_chapter': '2', 'state': 'excluded'}]}}
    result = admin_schedule_policy(comp, schedule, '2', '2026-02-28')
    assert result['items'][0]['state'] == 'unknown'
    assert result['added_to_need'] == 0


@pytest.mark.parametrize('width', [390, 1440])
def test_verified_admin_money_remains_visible_in_the_real_monitor_and_report(width):
    import developaid_management_report as report
    from test_monitor_cumulative_controls import browser_page

    model = read(source())
    own = dashboard._own_money(model['budget_composition'], {'1': 0, '2': 200_000, '3': 50_000},
        {c: {'total': 0, 'borrowed': 0} for c in ('1', '2', '3')}, ['1', '2', '3'], dt.date(2026, 2, 28),
        chapter_flow=model['chapter_flow'])
    r = own['reconciliation']
    assert r['admin_expenses']['rows'] == [
        {'label': 'Всего АХР', 'total': 360_000, 'model_fact': 120_000, 'model_plan': 240_000},
        {'label': 'Статьи главы 2', 'total': 275_000, 'model_fact': 75_000, 'model_plan': 200_000},
        {'label': 'Статьи главы 3', 'total': 77_500, 'model_fact': 37_500, 'model_plan': 40_000},
        {'label': 'Банковская статья не уточнена', 'total': 7_500, 'model_fact': 7_500, 'model_plan': 0}]
    with browser_page(width) as (page, responses, errors):
        page.evaluate('''r=>{
          currentView={dashboard:{funding:{known:true,reconciliation:r}}};
          renderDash(currentView);selectMonitorTab('money');
        }''', r)
        detail = page.locator('.funding-admin-breakdown')
        detail.locator('summary').click()
        rows = detail.locator('tbody tr').all_text_contents()
        assert len(rows) == 4
        assert 'Статьи главы 2' in rows[1] and 'Статьи главы 3' in rows[2]
        assert 'Банковская статья не уточнена' in rows[3]
        assert 'Факт модели' in detail.inner_text() and 'План модели' in detail.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
    funding = {'own_money': own, 'reconciliation': r}
    block = {'kind': 'week', 'funding': {'state': 'ok', 'limit': funding, 'rss': None,
        'draws': dict.fromkeys(('period', 'month', 'total')),
        'interest': dict.fromkeys(('period', 'month', 'total'))}}
    html = report._funding_html(block)
    assert 'АХР в составе бюджета' in html and 'Факт модели' in html and 'План модели' in html
    assert '275 000 ₽' in html and '77 500 ₽' in html and '7 500 ₽' in html
    assert html.count('Статьи главы 2') == html.count('Статьи главы 3') == 1
