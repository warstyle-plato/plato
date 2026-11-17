"""A queue's rent totals describe its own streams, never the whole parcel."""
from copy import deepcopy
from datetime import date,timedelta
import calendar

import pytest

import main_legacy as core


def inputs(**changes):
    return {**deepcopy(core.DEFAULT_INPUTS),'project_start':'2027-01-01','ird_months':12,
        'construction_months':12,'land_right':'lease','land_rights_cost_mln':0,
        'land_rent_mode':'manual','land_rent_cadastral_mln':100,
        'land_rent_regime_start':'2027-01-01','land_rent_rates':[{'year':1,'rate_pct':1.5}],
        'land_rent_tail_rule':'repeat_last','land_rent_vat_treatment':'public_exempt',
        'social_mode':'Денежная компенсация','social_compensation_mln':0,**changes}


def daily(exposures,phase):
    value=development=0.0
    for item in exposures:
        if item['phase_index']!=phase:
            continue
        day=date(2027,1,1)
        while day<date.fromisoformat(item['lease_exit']):
            money=1_500_000*item['share']/(366 if calendar.isleap(day.year) else 365)
            value+=money
            if not item.get('retained') or day<date.fromisoformat(item['commissioning']):
                development+=money
            day+=timedelta(days=1)
    return value,development


@pytest.mark.parametrize('manual',[False,True])
@pytest.mark.parametrize('retained',[False,True])
def test_unequal_phases_reconcile_own_cash_and_accrual_totals(manual,retained):
    x=inputs(land_rent_payment_mode='manual' if manual else 'monthly_estimate',
             land_rent_payment_schedule='100%@0')
    t=deepcopy(core.TEP_DEFAULT)
    p={'enabled':True,'phase_count':2,'phases':[
        {'name':'A','site_area_ha':35,'start_offset_months':0,'construction_months':12},
        {'name':'B','site_area_ha':65,'start_offset_months':12,'construction_months':12}]}
    if retained:
        x.update(offices_enabled=True,offices_strategy='income',offices_hold_years=2,
            offices_gba_sqm=10000,offices_saleable_sqm=8000,
            offices_start='2028-01-01',offices_months=12)
        t['offices']['total_area']=10000
        p['discrete']={'offices':2}
    before=deepcopy((x,t,p))
    bundle=core._run_authoritative_model(x,t,[],p)
    assert (x,t,p)==before
    whole=bundle['consolidated']['land_rent']
    assert [row['share'] for row in whole['phase_land']]==pytest.approx([.35,.65])
    own=[]
    for index,phase in enumerate(bundle['phases']):
        row=phase['result']['land_rent'];own.append(row)
        accrued,development=daily(whole['land_exposures'],index)
        assert row['cash_total']==pytest.approx(sum(row['monthly'].values()),abs=.01)
        assert row['applied_total']==pytest.approx(row['cash_total'],abs=.01)
        assert row['development_cash_total']==pytest.approx(sum(row['construction_monthly'].values()),abs=.01)
        assert row['operating_cash_total']==pytest.approx(sum(
            sum(values.values()) for values in row['operating_monthly_by_object'].values()),abs=.01)
        assert row['known_total']==pytest.approx(accrued,abs=.01)
        assert row['construction_total']==pytest.approx(accrued,abs=.01)  # retained legacy alias
        assert row['development_accrual_total']==pytest.approx(development,abs=.01)
        assert row['operating_accrual_total']==pytest.approx(accrued-development,abs=.01)
        assert phase['result']['dates']['rve']==['2029-01-01','2030-01-01'][index]
    for key in ('cash_total','applied_total','development_cash_total','operating_cash_total',
                'known_total','construction_total','development_accrual_total','operating_accrual_total'):
        assert sum(row[key] for row in own)==pytest.approx(whole[key],abs=.01),key
    assert whole['cash_total']==pytest.approx(sum(whole['monthly'].values()),abs=.01)
    if retained:
        assert whole['operating_cash_total']>0
        assert whole['development_accrual_total']<whole['construction_total']
    else:
        assert whole['known_total']==pytest.approx(4_344_863.013699,abs=.01)
        assert [row['cash_total'] for row in own]==pytest.approx([1_179_452.054795,3_165_410.958904],abs=.01)
