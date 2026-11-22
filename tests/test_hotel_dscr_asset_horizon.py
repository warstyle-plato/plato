"""A seller cash liability does not turn the asset's final balloon into DSCR service."""
from collections import defaultdict
from copy import deepcopy
from datetime import date

import pytest

import developaid_hotel_strategy as hotel
import hotel_presets


@pytest.mark.parametrize('commissioning',[date(2030,1,1),date(2030,7,1)])
def test_hotel_cash_tail_preserves_asset_year_dscr_and_actual_seller_cash(commissioning):
    params=hotel.params_from_inputs(hotel_presets.apply_preset({},'hotel1'))
    params.update(hold_years=1,exit_mode='hold',valuation='gordon',
                  financing='commercial',loan_share_pct=60,grace_months=120,
                  loan_limit_th_per_key=1_000_000)
    incurred={hotel.add_months(date(2027,1,1),i):100_000 for i in range(24)}
    operating={hotel.add_months(commissioning,i):100_000 for i in range(12)}
    late=date(2037,1,1)
    plan={'commissioning':commissioning,'start':date(2027,1,1),
          'capex':{date(2027,1,1):100_000_000},'params':params,
          'land_rent_construction_incurred':incurred,
          'land_rent_construction_cash':{late:2_400_000},
          'land_rent_construction_input_vat_base':incurred,
          'land_rent_construction_vat_exempt':False,
          'land_rent_operating':operating,
          'land_rent_operating_cash':{late:1_200_000},
          'land_rent_valuation':{hotel.add_months(commissioning,i):100_000 for i in range(24)}}
    before=deepcopy(plan)
    result=hotel.hotel_flows(plan,lambda month:.10,vat_rate=.22,
                             profit_tax_rate=.25,discount_rate=.15)
    assert plan==before
    asset_end=hotel.month_key(result['horizon_end'])
    assert asset_end<late==result['cash_horizon_end']
    assert result['monthly']['loan_repayment'][asset_end]>0
    asset_months=[month for month in result['months'] if month<=asset_end]
    # Identical monthly operations and debt: only the seller cash calendar
    # extends beyond the asset. The old two-argument API on the asset span
    # preserves its established EBITDA/regular-service definition.
    expected=hotel.annual_table(asset_months,defaultdict(dict,deepcopy(result['monthly'])))
    asset_row=next(row for row in result['annual'] if row['year']==asset_end.year)
    expected_row=next(row for row in expected if row['year']==asset_end.year)
    assert asset_row['debt_service']==pytest.approx(expected_row['debt_service'])
    assert asset_row['dscr']==pytest.approx(expected_row['dscr'])
    assert result['kpi']['dscr_min']==pytest.approx(min(
        row['dscr'] for row in expected if row['dscr'] is not None))
    tail=next(row for row in result['annual'] if row['year']==late.year)
    assert tail['dscr'] is None and tail['debt_service']==0
    assert tail['capex']==2_400_000
    assert tail['land_rent_operating_cash']==1_200_000
    assert result['monthly']['land_rent_construction_cash'][late]==2_400_000
    assert result['monthly']['land_rent_operating_cash'][late]==1_200_000


@pytest.mark.parametrize('tail',[date(2029,9,1),date(2037,1,1)])
def test_annual_dscr_excludes_asset_balloon_even_with_cash_later_in_same_year(tail):
    asset_end=date(2029,6,1)
    months=[date(2029,i,1) for i in range(1,7)]+[tail]
    m=defaultdict(dict)
    for month in months[:6]:
        m['rooms_available'][month]=10
        m['ebitda'][month]=100
        m['loan_interest_paid'][month]=5
        m['loan_repayment'][month]=20
        if month<asset_end:
            m['loan_cash_sweep'][month]=2
    m['loan_repayment'][asset_end]=500
    m['loan_vat_prepayment'][asset_end]=50
    m['capex'][tail]=900
    before=deepcopy(m)
    rows=hotel.annual_table(months,m,asset_horizon_end=asset_end)
    row=next(row for row in rows if row['year']==2029)
    # 30 interest + (600 total repayment - 50 VAT - 10 cash sweep - 450 exit).
    assert row['debt_service']==120
    assert row['dscr']==5
    assert sum(row['capex'] for row in rows)==900
    assert all(m[key]==values for key,values in before.items())
