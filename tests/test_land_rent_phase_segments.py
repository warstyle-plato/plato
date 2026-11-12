"""Daily independent obligations at rate, exclusion and parcel boundaries."""
from datetime import date, timedelta
import io

import openpyxl
import pytest

import developaid_land_rent as rent
import v4_land_rent as book
from xlsx_eval import Evaluator

START = date(2028, 1, 1)
END = date(2028, 3, 1)
RELEASE = (date(2028, 1, 15), END)


def settings(**changes):
    return dict(land_right='lease', vri_region='msk', land_rent_mode='manual',
        land_rent_cadastral_mln=100, land_rent_regime_start='2027-01-20',
        land_rent_rates=[{'year':1,'rate_pct':1},{'year':2,'rate_pct':10}],
        land_rent_tail_rule='repeat_last', land_rent_vat_treatment='public_exempt',
        **changes)


def daily_obligations(*, excluded=False, switch=None, termination=END, second_rate=.10):
    # The definition is day-by-day contractual responsibility, independent of
    # production interval splitting and monthly proportions. Jan20 crosses a
    # 365-day first contractual year into a 366-day second one.
    totals = [0., 0.]
    day = START
    while day < min(END, termination):
        first = day < date(2028, 1, 20)
        rate = 0 if first and excluded else .01 if first else second_rate
        denominator = 365 if first else 366
        base = 300e6 if switch and day >= switch else 100e6
        for p, release in enumerate(RELEASE):
            if day < release:
                totals[p] += .5 * base * rate / denominator
        day += timedelta(days=1)
    return totals


def editable_book(inputs, result):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    params = workbook.create_sheet('Параметры модели')
    for n, value in enumerate((START, END, END, 0, *RELEASE), 1):
        params.cell(n, 2, value)
    rates = workbook.create_sheet('Ставки')
    capex = workbook.create_sheet('CAPEX')
    for p in range(4):
        cf = workbook.create_sheet(f'CF_{p+1}')
        total = 32 + p*34
        for n in range(180):
            col = openpyxl.utils.get_column_letter(4+n)
            rates.cell(3, 4+n, rent._add_months(START, n))
            capex.cell(total, 4+n, '=10')
            cf.cell(17, 4+n, f"='CAPEX'!{col}{total}")
            cf.cell(20, 4+n, f'={col}17')
            cf.cell(21, 4+n, '=(SUM($D$20:$GA$20)-0)*0.2')
    blob = io.BytesIO()
    workbook.save(blob)
    output = book.apply(blob.getvalue(), inputs, result,
        project_start_formula="'Параметры модели'!B1", rve_formula="'Параметры модели'!B2",
        project_end_formula="'Параметры модели'!B3", hostvri_amount_formula="'Параметры модели'!B4",
        phase_rve_formulas=["'Параметры модели'!B5", "'Параметры модели'!B6"],
        phase_shares=result['phase_shares'])
    return openpyxl.load_workbook(io.BytesIO(output), data_only=False)


@pytest.mark.parametrize('excluded,switch,termination', [
    (False, None, END), (True, None, END),
    (False, date(2028,1,9), date(2028,2,15)), (True, date(2028,1,9), END)])
def test_each_phase_owes_only_its_own_days_and_segment_rate(excluded, switch, termination):
    inputs = settings(land_rent_first_year_relation='full_year_in_vri' if excluded else 'regular_only',
        land_rent_first_year_confirmed=True, land_rent_termination_date=termination.isoformat())
    if switch:
        inputs['land_rent_cadastral_target_mln'] = 300
    result = rent.build(inputs, START, END, cadastral_switch=switch,
        phase_land=[{'share':.5, 'rve':release.isoformat()} for release in RELEASE])
    expected = daily_obligations(excluded=excluded, switch=switch, termination=termination)
    assert [p['accrual_total'] for p in result['phase_land']] == pytest.approx(expected, abs=.01)
    assert result['known_total'] == pytest.approx(sum(expected), abs=.01)
    ev = Evaluator(editable_book(inputs, result))
    assert [ev.cell('CAPEX',f'B{145+p}')*1e6 for p in range(2)] == pytest.approx(expected, abs=.01)
    for month, amount in result['accrual_monthly'].items():
        assert sum(own.get(month,0) for own in result['phase_accrual_monthly']) == pytest.approx(amount)


def test_editing_workbook_rate_changes_only_the_charged_phase_after_anniversary():
    inputs = settings(land_rent_first_year_relation='full_year_in_vri', land_rent_first_year_confirmed=True)
    result = rent.build(inputs,START,END,phase_land=[{'share':.5,'rve':d.isoformat()} for d in RELEASE])
    workbook = editable_book(inputs,result)
    workbook[book.SHEET]['D23'] = 20  # live second-year rate
    ev = Evaluator(workbook)
    expected = daily_obligations(excluded=True,second_rate=.20)
    assert [ev.cell('CAPEX',f'B{145+p}')*1e6 for p in range(2)] == pytest.approx(expected, abs=.01)
    assert expected[0] == 0
