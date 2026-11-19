"""Cash and the additional contract level are distinct source observations."""
import datetime as dt
import openpyxl
import pytest

import developaid_actuals as actuals
import developaid_budget_funding_source as funding
import developaid_monitor_contract_risk as risk
import developaid_monitor_contracts as contracts

DAY = dt.date(2026, 11, 1)


def native_book(tmp_path, edit=None):
    book = openpyxl.Workbook()
    pay = book.active
    pay.title = 'Реестр платежей'
    for col, value in {2: 'Наименование подрядчика', 3: '№ Договора', 4: 'Дата договора',
                       6: 'Назначение платежа', 7: 'Код из ССР', 9: 'Дата платежа',
                       10: 'Сумма в Рублях', 12: 'Контрагент', 13: 'Договор',
                       14: 'аванс/выполнение/ГУ'}.items():
        pay.cell(7, col, value)
    for col in (2, 3, 4, 9, 10):
        pay.cell(6, col, 'данные платежного поручения')
    for col, value in {2: 'Parent', 3: 'GP-1', 4: dt.date(2025, 1, 1),
                       6: 'Аванс', 7: '2.1.', 9: DAY, 10: 100,
                       12: 'Child', 13: 'SUB-1', 14: 'Выполнение'}.items():
        pay.cell(10, col, value)
    estimate = book.create_sheet('Расчет стоимости строительства')
    estimate['A7'] = 'руб.'
    estimate['E9'] = 'Общая сметная стоимость'
    for row, code in enumerate(['1', '1.1', '2', '2.1', '3', '3.1'], 10):
        estimate.cell(row, 1, code)
        estimate.cell(row, 5, 1000)
    if edit:
        edit(pay, estimate)
    path = tmp_path / 'native.xlsx'
    book.save(path)
    book.close()
    return path


def child(day=dt.date(2026, 2, 1)):
    return {'contractor': 'Child', 'contract': 'SUB-1', 'contract_date': day,
            'completed': 20}


def observe(path, row):
    payments, _ = risk.payments(path, DAY)
    return risk.advance(row, payments, reference_key=contracts._reference_key,
                        completed_basis='with_vat')


def test_additional_level_never_changes_cash_identity_sum_or_default_shape(tmp_path):
    path = native_book(tmp_path)
    plain = actuals.read_payments(path, include_incomplete=True)
    extended = actuals.read_payments(path, include_incomplete=True, include_contract_allocation=True)
    assert plain['total'] == extended['total'] == 100
    original, = plain['rows']
    assert original['contractor'] == 'Parent' and original['contract'] == 'GP-1'
    assert original['contract_date'] == dt.date(2025, 1, 1) and original['purpose'] == 'Аванс'
    assert 'contract_allocation' not in original and '_contract_allocation' not in original
    allocation = extended['rows'][0]['contract_allocation']
    assert allocation['contractor'] == 'Child' and allocation['contract'] == 'SUB-1'
    assert allocation['contract_date'] is None and allocation['purpose'] == 'Выполнение'
    assert allocation['source_cells'] == {'contractor': 'L10', 'contract': 'M10', 'purpose': 'N10', 'amount': 'J10'}
    allocation['contractor'] = 'MUTATED'
    assert actuals.read_payments(path, include_contract_allocation=True)['rows'][0]['contract_allocation']['contractor'] == 'Child'


@pytest.mark.parametrize('legal_day', [dt.date(2025, 1, 1), dt.date(2026, 2, 1)])
def test_parent_date_cannot_confirm_additional_contract_even_if_equal(tmp_path, legal_day):
    path = native_book(tmp_path)
    result = observe(path, child(legal_day))
    assert result['paid'] is None and result['unworked'] is None
    assert result['allocation_recorded_total'] == 100 and result['allocation_recorded_count'] == 1
    assert result['unmatched_candidates'] == 1 and result['unmatched_amount'] == 100
    assert 'без даты договора' in result['reason']
    parent = {'contractor': 'Parent', 'contract': 'GP-1', 'contract_date': dt.date(2025, 1, 1), 'completed': 20}
    assert observe(path, parent)['paid'] == 100  # The same cash row is counted once.


@pytest.mark.parametrize('purpose, expected', [('Аванс', True), ('Выполнение', False), ('ГУ', False), (None, None)])
def test_additional_purpose_never_inherits_parent_advance_label(tmp_path, purpose, expected):
    path = native_book(tmp_path, lambda pay, _: setattr(pay['N10'], 'value', purpose))
    rows, _ = risk.payments(path, DAY)
    allocation, = [p for p in rows if p['source'].get('kind') == 'contract_allocation']
    assert allocation['advance_label'] is expected
    assert rows[0]['advance_label'] is True


def test_unverified_additional_header_cannot_confirm_or_attribute_cash(tmp_path):
    path = native_book(tmp_path, lambda pay, _: setattr(pay['L7'], 'value', 'Unrelated notes'))
    result = observe(path, child())
    assert result['paid'] is None and result['allocation_recorded_total'] is None
    assert result['confirmed_paid'] == 0 and result['unmatched_candidates'] == 1


@pytest.mark.parametrize('dated', [False, True])
def test_one_cash_row_is_not_summed_across_identical_contract_levels(tmp_path, dated):
    def edit(pay, _):
        pay['B10'], pay['C10'] = 'Child', 'SUB-1'
        pay['D10'] = dt.date(2026, 2, 1) if dated else None
    path = native_book(tmp_path, edit)
    result = observe(path, child())
    assert result['allocation_recorded_total'] == 100
    assert len(result['sources']) == 2  # Both observed levels remain inspectable.
    if dated:
        assert result['paid'] == 100 and result['payments_count'] == 1
    else:
        assert result['paid'] is None and result['unmatched_amount'] == 100
        assert result['unmatched_candidates'] == 1


def test_different_cash_rows_are_not_deduplicated_by_equal_names_or_amounts(tmp_path):
    def edit(pay, _):
        for column in range(1, 15):
            pay.cell(11, column, pay.cell(10, column).value)
    path = native_book(tmp_path, edit)
    result = observe(path, child())
    assert result['paid'] is None and result['unmatched_candidates'] == 2
    assert result['unmatched_amount'] == result['allocation_recorded_total'] == 200


def test_contradictory_cash_observations_stay_unknown_instead_of_being_summed(tmp_path):
    def edit(pay, _):
        pay['B10'], pay['C10'], pay['D10'] = 'Child', 'SUB-1', None
    rows, _ = risk.payments(native_book(tmp_path, edit), DAY)
    allocation = next(p for p in rows if p['source'].get('kind') == 'contract_allocation')
    allocation['amount'] = 200
    result = risk.advance(child(), rows, reference_key=contracts._reference_key,
                          completed_basis='with_vat')
    assert result['paid'] is None and result['unworked'] is None
    assert result['unmatched_candidates'] == 1 and result['unmatched_amount'] is None
    assert result['allocation_recorded_total'] is None
    assert 'противоречат' in result['reason']


def test_native_headers_and_unused_lookup_rows_share_one_closed_definition(tmp_path):
    def edit(pay, _):
        pay['H11'] = 0  # Only the unused lookup is populated.
        pay['H12'], pay['B12'], pay['G12'], pay['I12'], pay['J12'] = 0, 'Zero payment', '2.1', DAY, 0
        pay['H13'], pay['M13'] = 0, 'An additional contract without an amount'
        pay['B14'], pay['G14'], pay['I14'] = 'Missing amount', '2.1', DAY
    path = native_book(tmp_path, edit)
    parsed = actuals.read_payments(path, include_incomplete=True)
    assert [r['source_row'] for r in parsed['rows']] == [10, 12, 13, 14]
    assert parsed['rows'][1]['amount'] == 0 and parsed['rows'][2]['amount'] is None
    bank = funding._bank(path.read_bytes(), DAY)
    assert bank['row_counts']['nonempty'] == 4 and bank['row_counts']['incomplete'] == 2
    assert all(role['state'] == 'observed' for role in bank['payment_role_evidence'].values())
    assert bank['limit_role_evidence']['state'] == 'observed'
    assert bank['payment_unit_evidence']['recognized_unit'] == 'руб.'
    assert [r['row'] for r in bank['incomplete_rows']] == [13, 14]
    assert bank['observed_payments_at_or_before_cut']['state'] == 'unknown'


def test_lookups_cannot_hide_a_real_zero_or_additional_contract():
    row = [None] * 14
    row[7] = 0
    assert actuals.unused_payment_lookup(row)
    for column in (1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 13):
        changed = list(row)
        changed[column] = 0
        assert not actuals.unused_payment_lookup(changed)
    row[7] = '0'
    assert not actuals.unused_payment_lookup(row)


@pytest.mark.parametrize('width', [390, 1440])
def test_actual_page_displays_recorded_allocation_without_paid_zero(tmp_path, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    path = native_book(tmp_path)
    result = observe(path, child())
    with browser_page(width) as (page, _, errors):
        page.evaluate("a => { const box=document.createElement('div'); box.id='allocation-proof'; box.innerHTML=contractAdvanceHtml({advance:a}); document.body.appendChild(box); }", result)
        box = page.locator('#allocation-proof')
        expect(box).to_contain_text('В РСС по подрядчику и номеру договора распределено:')
        expect(box).to_contain_text('100')
        expect(box).to_contain_text('Дата этого договора в строках распределения не указана')
        expect(box).to_contain_text('Оплачено: —')
        expect(box).not_to_contain_text('Оплачено: 0')
        assert not errors
