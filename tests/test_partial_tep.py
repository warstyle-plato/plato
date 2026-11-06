"""Opt-in partial source drafts never calculate from missing source geometry."""
import copy
import pytest
from fastapi.testclient import TestClient
import partial_tep
import main_legacy as core


def draft():
    return {'inputs': {'_partial_tep': {'kind': partial_tep.KIND, 'version': 1,
                       'rows': ['apartments', 'underground_parking'], 'origins': {}}},
            'tep': {'apartments': {'saleable': 2000., 'units': 10.},
                    'underground_parking': {'units': 10., 'guest_units': 2.}}, 'rates': []}


def complete():
    data = draft()
    for row in data['tep'].values():
        for field in partial_tep.FIELDS:
            row.setdefault(field, 0.)
        row['gns'] = 3000. if row is data['tep']['apartments'] else 500.
        row['total_area'] = row['gns']
    data['inputs'].update({key: 0. for key in partial_tep.required_inputs(['apartments', 'underground_parking'])})
    data['inputs'].update(project_start='2027-01-01', construction_months=24)
    return data


def test_missing_is_not_zero_and_direct_values_remain_unchanged():
    data = draft();before = copy.deepcopy(data)
    missing = partial_tep.missing(data['inputs'], data['tep'])
    assert any(r['path'] == 'tep.apartments.gns' for r in missing)
    assert any(r['path'] == 'tep.underground_parking.gns' for r in missing)
    assert data == before
    assert data['tep']['apartments']['saleable'] == 2000
    assert data['tep']['underground_parking']['units'] == 10
    assert 'gns' not in data['tep']['underground_parking']


@pytest.mark.parametrize('value', [None, '', False, float('nan'), float('inf'), -1])
def test_invalid_or_unknown_critical_values_are_not_ready(value):
    data=complete();data['tep']['apartments']['gns']=value
    with pytest.raises(partial_tep.PartialTepError):
        partial_tep.require_complete(data['inputs'],data['tep'])


def test_manual_completion_and_literal_zero_are_accepted():
    data=complete()
    assert partial_tep.missing(data['inputs'],data['tep']) == []
    data['inputs']['purchase_price_mln']=None
    assert partial_tep.missing(data['inputs'],data['tep'])
    data['inputs']['purchase_price_mln']=0.
    assert partial_tep.missing(data['inputs'],data['tep']) == []


def test_ready_flag_cannot_waive_missing_source_values():
    data=draft();data['inputs']['_partial_tep'].update(ready=True,missing=[],rows=['apartments','underground_parking'])
    with pytest.raises(partial_tep.PartialTepError):partial_tep.require_complete(data['inputs'],data['tep'])


@pytest.mark.parametrize('path', ['/calculate','/calculate-phased','/report/workbook','/report/pdf','/report/teaser'])
def test_all_http_financial_surfaces_preflight_before_access_or_jobs(monkeypatch,path):
    def forbidden(*a, **k):raise AssertionError('Incomplete draft reached paid access or a job')
    monkeypatch.setattr(core,'require_calc_access',forbidden)
    monkeypatch.setattr(core,'require_payload_access',forbidden)
    data=draft();data.update(phasing={},result={'summary':{'revenue':123}})
    response=TestClient(core.app).post(path,json=data)
    assert response.status_code==422,response.text
    assert 'Черновик ТЭП' in response.json()['detail']
    assert 'ticket' not in response.json()


def test_direct_authoritative_and_calc_entrypoints_cannot_bypass_preflight():
    data=draft()
    for fn in [lambda:core.calculate(core.CalcRequest(**data)),
               lambda:core.calculate_phased(core.PhasedCalcRequest(**data,phasing={})),
               lambda:core._run_authoritative_model(data['inputs'],data['tep'],[],{}),
               lambda:core.prepared_calculation(data['inputs'],data['tep'],[]),
               lambda:core.build_project_workbook(data['inputs'],data['tep'])]:
        with pytest.raises(core.HTTPException) as failure:fn()
        assert failure.value.status_code==422


def test_legacy_inputs_remain_outside_partial_contract():
    assert partial_tep.missing({'project_class':'comfort'},{'apartments':{'saleable':2000}})==[]
    partial_tep.require_complete({}, {})


@pytest.mark.parametrize('change', [
    lambda d: d['inputs'].update(offices_enabled=True),
    lambda d: d['tep'].update(offices={'gns': 100.}),
    lambda d: d['inputs'].update(construction_months=0),
    lambda d: d['inputs'].update(construction_months=1.5),
    lambda d: d['inputs'].update(project_start='2027-02-30'),
])
def test_supported_scope_and_server_missing_contract_are_not_client_ready_flags(change):
    data=complete()
    change(data)
    with pytest.raises(partial_tep.PartialTepError):
        partial_tep.require_complete(data['inputs'],data['tep'])


def test_omitted_active_row_cannot_waive_missing_gross():
    data=complete();data['inputs']['_partial_tep']['rows']=['apartments']
    data['tep']['underground_parking']['gns']=None
    with pytest.raises(partial_tep.PartialTepError):
        partial_tep.require_complete(data['inputs'],data['tep'])


def test_completed_draft_calculates_exact_declared_geometry_without_default_objects():
    data=complete()
    x=copy.deepcopy(core.DEFAULT_INPUTS);x.update(data['inputs'])
    t=copy.deepcopy(core.TEP_DEFAULT)
    for row in t.values():
        for field in partial_tep.FIELDS:row[field]=0.
    for key,row in data['tep'].items():t[key].update(row)
    t['underground_parking']['guest_units']=2.
    # Deliberately disagree with the old 35m² norm and default social capacity.
    x.update(underground_manual_spaces=10.,underground_manual_gns_sqm=500.,
             _parking_by_hand=['underground'],underground_area_per_space_sqm=35.)
    result=core.calculate(core.CalcRequest(inputs=x,tep=t,rates=[]))
    rows={row['key']:row for row in result['tep']['rows']}
    assert rows['apartments']['saleable']==2000.
    assert rows['apartments']['units']==10.
    assert rows['underground_parking']['gns']==500.
    assert rows['underground_parking']['units']==10.
    assert rows['underground_parking']['guest_units']==2.
    assert rows['kindergarten']['gns']==0.
    assert rows['kindergarten']['units']==0.


def test_declared_absent_product_in_phase_is_not_missing_unknown():
    data=complete()
    data['tep']['underground_parking']={key:0. for key in (*partial_tep.FIELDS,'guest_units')}
    assert partial_tep.missing(data['inputs'],data['tep'])==[]
    data['tep']['underground_parking']['gns']=None
    assert partial_tep.missing(data['inputs'],data['tep'])


@pytest.mark.parametrize('value',[None,False,11.,-1.])
def test_unknown_or_invalid_guest_count_cannot_fall_back_to_the_norm(value):
    data=complete();data['tep']['underground_parking']['guest_units']=value
    with pytest.raises(partial_tep.PartialTepError):
        partial_tep.require_complete(data['inputs'],data['tep'])


def test_partial_workbook_mapping_gaps_are_not_delivered_as_a_finished_model(monkeypatch):
    monkeypatch.setattr(core,'_build_project_workbook',lambda *a,**k:(b'wrong-source-model','draft.xlsx',{'missing':['synthetic mapping gap']}))
    data=complete()
    with pytest.raises(core.HTTPException) as failure:
        core.build_project_workbook(data['inputs'],data['tep'])
    assert failure.value.status_code==422
    # The existing legacy export warning contract is unchanged.
    assert core.build_project_workbook({}, {})[0]==b'wrong-source-model'
