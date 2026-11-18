"""Cadastral estimates keep the registration/retention clocks of lease 1191."""
import calendar
import copy
from datetime import date, timedelta
import io

import openpyxl
import pytest

import developaid_land_rent as rent
import main_legacy as core
import native_land_rent_book as native
import v4_land_rent as sheet
from tests.test_rent_cadastral_excel import settings
from xlsx_eval import Evaluator


START = date(2027, 1, 1)
CHANGE = date(2028, 2, 17)
SHARES = [.28, .22, .19, .16, .15]


def oracle(exposures, *, target=300, change=CHANGE, phase=None):
    monthly = {}
    selected = [p for p in exposures if phase is None or p['phase_index'] == phase]
    day = START
    while day < max(date.fromisoformat(p['lease_exit']) for p in selected):
        share = sum(p['share'] for p in selected if day < date.fromisoformat(p['lease_exit']))
        base = 100 if day < change else target
        key = day.replace(day=1).isoformat()
        monthly[key] = monthly.get(key, 0) + base * 1e6 * .015 * share / (366 if calendar.isleap(day.year) else 365)
        day += timedelta(days=1)
    return monthly


@pytest.fixture(scope='module')
def five_queue_estimate():
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), **settings('msk'),
        'land_rent_mode': 'manual', 'land_rent_rates': [{'year': 1, 'rate_pct': 1.5}],
        'land_rent_tail_rule': 'repeat_last', 'land_rent_vat_treatment': 'public_exempt',
        'land_rent_regime_start': START.isoformat(), 'project_start': START.isoformat(),
        'ird_months': 12, 'construction_months': 24,
        'social_mode': 'Денежная компенсация', 'social_compensation_mln': 0,
        'land_rights_cost_mln': 50, 'vri_relief_mode': 'percent', 'vri_relief_pct': 100,
        'land_rent_vri_change': True, 'land_rent_cadastral_change_date': CHANGE.isoformat()}
    for p in x['land_rent_cadastral_parameters']:
        p.update(target_use='Синтетическая жилая группа', valuation_territory='Москва, синтетическая территория')
    phasing = {'enabled': True, 'user_enabled': True, 'phase_count': 5,
        'phases': [{'name': f'О{i+1}', 'start_offset_months': i*12,
                    'construction_months': 24, 'site_area_ha': share*100}
                   for i, share in enumerate(SHARES)],
        'products': {key: [p*100 for p in SHARES] for key in
            ('apartments', 'ground_commercial', 'underground_parking', 'storage')}}
    bundle = core._run_authoritative_model(x, copy.deepcopy(core.TEP_DEFAULT), [], phasing)
    payload, _, meta = core.build_project_workbook(x, copy.deepcopy(core.TEP_DEFAULT), [], phasing,
        project_name='Synthetic cadastral registration policy',
        finance_hints=core._v4_finance_hints(bundle), cache_values=False)
    assert meta['land_rent']['workbook_supported'], {
        key: meta['land_rent'].get(key) for key in ('workbook_error', 'workbook_reason')}
    return bundle, openpyxl.load_workbook(io.BytesIO(payload), data_only=False)


def test_five_unequal_shares_keep_registration_and_live_cadastral_formulas(five_queue_estimate):
    bundle, wb = five_queue_estimate
    model = bundle['consolidated']['land_rent']
    exposures = model['land_exposures']
    assert [p['share'] for p in exposures] == pytest.approx(SHARES)
    assert [p['commissioning'] for p in exposures] == [f'{2030+i}-01-01' for i in range(5)]
    assert [p['lease_exit'] for p in exposures] == [f'{2030+i}-04-01' for i in range(5)]
    assert bundle['consolidated']['capex']['land_rights'] == 0
    expected = oracle(exposures)
    assert model['accrual_monthly'] == pytest.approx(expected, abs=.01)
    ev = Evaluator(wb)
    ws = wb[sheet.SHEET]
    parameter = next(c.row+1 for row in ws for c in row if c.value == 'Арендуемый участок')
    by_phase = [oracle(exposures, phase=i) for i in range(5)]
    for offset in range(100):
        month = rent._add_months(START, offset).isoformat()
        col = openpyxl.utils.get_column_letter(4+offset)
        assert ev.cell(sheet.SHEET, f'{col}4')*1e6 == pytest.approx(expected.get(month, 0), abs=.01)
        own = [monthly.get(month, 0) for monthly in by_phase]
        for block, amount in enumerate(own[:3]+[sum(own[3:])]):
            assert ev.cell('CAPEX', f'{col}{145+block}')*1e6 == pytest.approx(amount, abs=.01)
    # The first parcel's UPKS changes the future total from 300 to 400 mln.
    changed = copy.deepcopy(wb)
    changed[sheet.SHEET][f'C{parameter}'] = 20000
    moved = Evaluator(changed)
    expected = oracle(exposures, target=400)
    for offset in (0, 13, 14, 36, 39, 75, 87, 90):
        month = rent._add_months(START, offset).isoformat()
        col = openpyxl.utils.get_column_letter(4+offset)
        assert moved.cell(sheet.SHEET, f'{col}4')*1e6 == pytest.approx(expected.get(month, 0), abs=.01)
    assert [p['result']['dates']['rve'] for p in bundle['phases']] == [f'{2030+i}-01-01' for i in range(5)]


def test_single_v4_route_without_finance_hints_keeps_the_authoritative_event_and_exposure():
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), **settings('msk'),
        'land_rent_mode': 'manual', 'land_rent_rates': [{'year': 1, 'rate_pct': 1.5}],
        'land_rent_regime_start': START.isoformat(), 'project_start': START.isoformat(),
        'ird_months': 12, 'construction_months': 24,
        'land_rent_tail_rule': 'repeat_last', 'land_rent_vat_treatment': 'public_exempt',
        'land_rent_cadastral_change_date': CHANGE.isoformat(), 'land_rent_vri_change': True,
        'land_rights_cost_mln': 50, 'vri_relief_mode': 'percent', 'vri_relief_pct': 100}
    _, _, meta = core.build_project_workbook(x, copy.deepcopy(core.TEP_DEFAULT), [], {}, cache_values=False)
    model = meta['land_rent']
    assert model['workbook_supported'], model.get('workbook_error')
    assert model['cadastral_switch']['date'] == CHANGE.isoformat()
    assert model['cadastral_switch']['target_mln'] == 300
    assert model['land_exposures'][0]['commissioning'] == '2030-01-01'
    assert model['land_exposures'][0]['lease_exit'] == '2030-04-01'


@pytest.mark.parametrize('region', ['msk', 'mo'])
def test_native_estimate_inputs_are_shared_but_retention_and_valuation_dates_are_separate(region):
    x = {**settings(region), 'land_rent_mode': 'manual',
        'land_rent_regime_start': START.isoformat(), 'land_rent_rates': [{'year': 1, 'rate_pct': 1.5}],
        'land_rent_tail_rule': 'repeat_last', 'land_rent_vat_treatment': 'public_exempt',
        'land_rent_cadastral_change_date': CHANGE.isoformat()}
    wb = openpyxl.Workbook()
    wb.active.title = 'Сроки'
    wb['Сроки']['A1'] = START
    wb['Сроки']['B1'] = date(2029, 1, 1)
    wb['Сроки']['C1'] = 2
    months = [f"EDATE('Сроки'!$A$1,{i})" for i in range(72)]
    calendars = []
    for name, years in [('Аренда ЗУ', 2), ('Оценка', 3)]:
        exit_day = date(2029+years, 1, 1)
        own = {'id': 'offices', 'object_key': 'offices', 'phase_index': 0, 'share': 1,
            'commissioning': '2029-01-01', 'lease_exit': exit_day.isoformat(),
            'retained': True, 'policy': 'income_horizon'}
        result = rent.build(x, START, date(2029, 1, 1), exit_day,
            cadastral_switch=CHANGE, exposures=[own])
        end = "EDATE('Сроки'!$B$1,('Сроки'!$C$1" + ('+1' if years == 3 else '') + ')*12)'
        calendars.append(native.add(wb, {'land_rent_inputs': x, 'land_rent': result},
            start="'Сроки'!$A$1", rve=end, end=end, month_formulas=months, sheet_name=name,
            exposure_formulas={'offices': {'share': '1', 'commissioning': "'Сроки'!$B$1", 'lease_exit': end}},
            master_terms_sheet='Аренда ЗУ' if years == 3 else None))
    primary, valuation = calendars
    p = primary.layout['cadastral_parameter_rows'][0]
    target = primary.layout['cadastral_target_row']
    ev = Evaluator(wb)
    assert ev.cell(primary.sheet_name, f'B{target}') == 300
    before = ev.cell(valuation.sheet_name, 'B19')
    wb[primary.sheet_name][f'C{p}' if region == 'msk' else f'D{p}'] = 20000 if region == 'msk' else 200
    updated = Evaluator(wb)
    assert updated.cell(primary.sheet_name, f'B{target}') == 400
    assert updated.cell(valuation.sheet_name, f'B{target}') == 400
    assert updated.cell(valuation.sheet_name, f'C{p}' if region == 'msk' else f'D{p}') == (20000 if region == 'msk' else 200)
    assert updated.cell(valuation.sheet_name, 'B19') > before
    # Primary retention ends in Jan 2031; valuation keeps the extra own year.
    assert updated.cell(primary.sheet_name, primary.month(48).split('!')[1]) == 0
    assert updated.cell(valuation.sheet_name, valuation.month(48).split('!')[1]) > 0
    wb['Сроки']['C1'] = 3
    edited = Evaluator(wb)
    assert edited.cell(primary.sheet_name, primary.month(48).split('!')[1]) > 0
    assert edited.cell(primary.sheet_name, primary.month(60).split('!')[1]) == 0
    assert edited.cell(valuation.sheet_name, valuation.month(60).split('!')[1]) > 0
