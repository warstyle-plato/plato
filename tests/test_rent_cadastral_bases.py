"""Saved normalized land records are enough; no new ЕГРН requests."""
import copy
from datetime import date

import pytest
import developaid_land_cadastral as cadastral
import developaid_land_rent as rent


def settings(region='msk'):
    numbers = ['77:01:0000001:11', '77:01:0000001:12'] if region=='msk' else ['50:01:0000001:11', '50:01:0000001:12']
    x = dict(land_right='lease', vri_region=region, land_rent_mode='manual',
        land_rent_regime_start='2027-01-01',land_rent_rates=[{'year':1,'rate_pct':6}],
        land_rent_tail_rule='repeat_last',land_rent_vat_treatment='public_exempt')
    rows = [dict(cadastral_number=n, area_sqm=(i+1)*10000,
        cadastral_value_rub=(i+1)*100e6,cadastral_value_mln=(i+1)*100,
        cadastral_value_new_rub=(i+1)*200e6,upks_target=20000,found=True,kind='land') for i,n in enumerate(numbers)]
    if region=='msk':
        x.update(_glavapu_import={'recognized':numbers,'normalized':{'cadastral_quarter':'77:01:0000001'},'mappings':{}},
            _land_lookup={'results':rows},land_rent_cadastral_parameters=[dict(number=n,upks_rub_sqm=20000,
            source='Сценарный показатель земли',source_date='2026-11-17') for n in numbers])
    else:
        x['_mo_calc']={'vri':{'parcels':rows}}
    return x


@pytest.mark.parametrize('region',['msk','mo'])
def test_bases_recompute_selected_land_without_changing_saved_record(region):
    x=settings(region);saved=copy.deepcopy(x)
    auto=cadastral.prepare(x)
    assert x==saved
    assert auto['land_rent_cadastral_mln']==300
    assert auto['land_rent_cadastral_target_mln']==600
    origin=auto['_field_origin']['inputs.land_rent_cadastral_target_mln']
    assert origin['kind']=='land_rent_estimate' and origin['source']=='calculated'
    assert 'не ЕГРН' in origin['text']
    auto['land_rent_parcels_excluded']=[cadastral.parcels(x)[0]['number']]
    auto=cadastral.prepare(auto)
    assert auto['land_rent_cadastral_mln']==200
    assert auto['land_rent_cadastral_target_mln']==400
    assert len(auto['_land_rent_cadastral_estimate']['parcels'])==1


@pytest.mark.parametrize('region',['msk','mo'])
def test_unknown_parcel_does_not_become_a_zero_or_partial_base(region):
    x=cadastral.prepare(settings(region))
    if region=='msk':
        x['land_rent_cadastral_parameters'][0]['upks_rub_sqm']=None
    else:
        x['_mo_calc']['vri']['parcels'][0]['cadastral_value_new_rub']=None
    result=cadastral.prepare(x)
    assert result['land_rent_cadastral_target_mln'] is None
    assert result['_land_rent_cadastral_estimate']['total_mln'] is None
    r=rent.build(result,date(2027,1,1),date(2028,1,1),cadastral_switch=date(2027,7,15))
    assert 'cadastral_change' in r['financial_missing_codes']
    assert r['cadastral_change']['date']=='2027-07-15'
    assert not r['financial_complete']


def test_moscow_area_upks_inputs_recalculate_but_manual_and_official_values_survive():
    x=cadastral.prepare(settings())
    x['land_rent_cadastral_parameters'][0].update(area_sqm=15000,upks_rub_sqm=30000)
    x=cadastral.prepare(x)
    assert x['land_rent_cadastral_target_mln']==850
    x.update(land_rent_cadastral_target_mln=900,land_rent_cadastral_target_kind='official_egrn',
        land_rent_cadastral_target_source='Выписка № пример',land_rent_cadastral_target_source_date='2027-07-15')
    x['_field_origin']['inputs.land_rent_cadastral_target_mln']={'source':'manual','text':'Подтверждено'}
    x['land_rent_parcels_excluded']=[cadastral.parcels(x)[0]['number']]
    result=rent.build(x,date(2027,1,1),date(2028,1,1),cadastral_switch=date(2027,7,15))
    assert result['base_value_mln']==200
    assert result['cadastral_switch']['target_mln']==900
    assert result['target_cadastral_kind']=='official_egrn'
    assert 'Официальная новая КС из ЕГРН' in result['target_cadastral_origin']['text']
    assert not result['cadastral_estimate']['applied']


def test_unlabelled_saved_values_are_preserved_and_equal_bases_keep_event():
    x=settings();x.update(land_rent_cadastral_mln=1234.567,land_rent_cadastral_target_mln=1234.567)
    result=rent.build(x,date(2027,1,1),date(2028,1,1),cadastral_switch=date(2027,7,15))
    assert result['base_value_mln']==1234.567
    assert result['cadastral_switch']['date']=='2027-07-15'
    assert result['cadastral_switch']['target_mln']==1234.567


def test_saved_manual_evidence_and_dates_survive_missing_new_editor_metadata():
    x=settings()
    current={'source':'manual','kind':'manual','text':'Сохранённая выписка о текущей КС','source_date':'2026-04-03'}
    target={'source':'manual','kind':'manual','text':'Сохранённая выписка о новой КС',
            'source_date':'2027-03-02','value_type':'official_egrn'}
    x.update(land_rent_cadastral_mln=111,land_rent_cadastral_target_mln=777,
        _field_origin={'inputs.land_rent_cadastral_mln':current,'inputs.land_rent_cadastral_target_mln':target})
    prepared=cadastral.prepare(x)
    assert prepared['land_rent_cadastral_mln']==111
    assert prepared['land_rent_cadastral_target_mln']==777
    assert prepared['_field_origin']==x['_field_origin']
    result=rent.build(x,date(2027,1,1),date(2028,1,1),cadastral_switch=date(2027,7,15))
    assert result['target_cadastral_kind']=='official_egrn'
    assert result['target_cadastral_origin']==target


def test_explicit_manual_source_wins_over_a_stale_automatic_kind():
    x=settings()
    x.update(land_rent_cadastral_mln=111,land_rent_cadastral_target_mln=777,
        _field_origin={'inputs.land_rent_cadastral_mln':{'source':'manual','kind':'land_rent_egrn'},
                       'inputs.land_rent_cadastral_target_mln':{'source':'manual','kind':'land_rent_estimate'}})
    result=cadastral.prepare(x)
    assert result['land_rent_cadastral_mln']==111 and result['land_rent_cadastral_target_mln']==777
    assert not result['_land_rent_cadastral_estimate']['applied']


def test_one_missing_record_is_not_a_partial_sum_for_the_accepted_territory():
    x=settings();x['_land_lookup']['results'].pop()
    prepared=cadastral.prepare(x)
    assert prepared['land_rent_cadastral_mln'] is None
    assert prepared['land_rent_cadastral_target_mln'] is None
    assert len(cadastral.parcels(x))==2


def test_recognized_glavapu_metrics_are_not_parcel_ids():
    x=settings()
    x['_glavapu_import']['recognized']=[{'label':'Площадь','key':'site_area_ha',
        'value':3,'display':'3','unit':'га','target':'inputs.site_area_ha'}]
    result=cadastral.prepare(x)
    assert len(cadastral.parcels(x))==2
    assert result['land_rent_cadastral_mln']==300
    assert result['land_rent_cadastral_target_mln']==600


@pytest.mark.parametrize('case', ['ambiguous', 'unapplied', 'region_mismatch', 'empty_acceptance', 'other_source'])
def test_server_does_not_autofill_a_territory_rejected_by_the_page(case):
    x=settings('mo' if case=='ambiguous' else 'msk')
    if case=='ambiguous':
        x['_glavapu_import']=settings()['_glavapu_import']
    elif case=='unapplied':
        x['_glavapu_import']={'unrelated_note':'not an applied territory'}
    elif case=='region_mismatch':
        x['vri_region']='mo'
    elif case=='empty_acceptance':
        x['_glavapu_import']={'mappings':{},'normalized':{},'recognized':[]}
    else:
        x['_other_region']={'numbers':['66:01:0000001:11'],'region':'Синтетический другой регион'}
    result=cadastral.prepare(x)
    assert result['vri_region']==x['vri_region']
    assert result.get('land_rent_cadastral_mln') is None
    assert result.get('land_rent_cadastral_target_mln') is None
    assert cadastral.parcels(x)==[]


@pytest.mark.parametrize('manual', [False, True, 'unlabelled'])
@pytest.mark.parametrize('region', ['msk','mo','other'])
def test_invalidated_acceptance_clears_only_automatic_bases(manual,region):
    x=cadastral.prepare(settings())
    before=copy.deepcopy(x['_field_origin'])
    if manual:
        x.update(land_rent_cadastral_mln=111,land_rent_cadastral_target_mln=777)
        if manual=='unlabelled':
            x.pop('_field_origin')
        else:
            x['_field_origin']={key:{'source':'manual','kind':'manual','text':'Сохранённое подтверждение'}
                                for key in before}
            before=copy.deepcopy(x['_field_origin'])
    x['_glavapu_import']={'unrelated_note':'not an applied territory'}
    x['vri_region']=region
    result=cadastral.prepare(x)
    assert result['vri_region']==region
    assert result['land_rent_cadastral_mln']==(111 if manual else None)
    assert result['land_rent_cadastral_target_mln']==(777 if manual else None)
    assert result['_land_rent_cadastral_estimate']['parcels']==[]
    if manual is True:
        assert result['_field_origin']==before


@pytest.mark.parametrize('region,alias', [('msk','Москва'),('mo','Московская область')])
def test_accepted_empty_mapping_and_region_alias_follow_the_page_without_mutating_region(region,alias):
    x=settings(region)
    x['vri_region']=alias
    result=cadastral.prepare(x)
    assert result['vri_region']==alias
    assert result['land_rent_cadastral_mln']==300
    assert result['land_rent_cadastral_target_mln']==600


@pytest.mark.parametrize('region',['msk','mo'])
def test_removing_the_normalized_territory_invalidates_only_automatic_bases(region):
    x=cadastral.prepare(settings(region))
    x.pop('_mo_calc' if region=='mo' else '_glavapu_import')
    x.pop('_land_lookup',None)
    result=cadastral.prepare(x)
    assert result['land_rent_cadastral_mln'] is None
    assert result['land_rent_cadastral_target_mln'] is None
    assert not result['_land_rent_cadastral_estimate']['parcels']
    x['land_rent_cadastral_mln']=500
    x['_field_origin']['inputs.land_rent_cadastral_mln']={'source':'manual'}
    assert cadastral.prepare(x)['land_rent_cadastral_mln']==500
