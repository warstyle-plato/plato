"""Synthetic bounded lineage, preserving accepted classifier and every cash value."""
import copy
import datetime as dt
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import pytest

import developaid_actuals as actuals
import developaid_admin_expenses_cash as cash
import developaid_admin_expenses_classification_audit as audit

BASE='762b0850ae08420ba490aaf7cf3b92146731af27'
FIXTURE_SHA256='bac0e6f82fbc443deba51afcec65b1f09d1b0101ce9a81243e204f88d81b6644'
SOURCE_SHA256={'developaid_actuals.py':'09b3cb69373c66767b90a32897a8702c8077373c525ab02264ccb2ea20d8777d',
               'developaid_admin_expenses_cash.py':'6e7dd38e4e4e6cd96d876b0596989baf34fe11a9d47041df969c8bbfa211e857'}
REG={'rows':[{'counterparty':'Admin','contract':'A','estimate_code':'2.6','bdds_code':'2.4.1'}]}
OFFICIAL={'articles_by_estimate_code':{'2.6':{'project_management'}}}


def pay(amount=10,row=10,day='2023-01-10',party='Admin',contract='A',code='2.6',source='own'):
    return {'source_row':row,'amount':amount,'date':dt.date.fromisoformat(day) if day else None,
            'contractor':party,'contract':contract,'estimate_code':code,'source':source}


def calculate(rows=None,reg=None,crosswalk=OFFICIAL,bdds=None):
    return cash.calculate({'budget':1000},{'rows':rows or [pay(),pay(row=11)]},reg or REG,crosswalk,bdds or {},'2023-02-15')


@pytest.fixture(scope='module')
def accepted():
    raw=(Path(__file__).parent/'fixtures'/'admin_expenses_classification_base44.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==FIXTURE_SHA256
    result=json.loads(raw)
    assert result['schema']=='admin_expenses_accepted_oracle_v1'
    assert result['base_commit']==BASE and result['source_sha256']==SOURCE_SHA256
    return result


def _canonical(value):
    """Preserve types and date keys without calculating financial expectations."""
    if value is None:return ['none']
    if type(value)is bool:return ['bool',value]
    if type(value)is int:return ['int',value]
    if type(value)is float:
        assert math.isfinite(value)
        return ['float',value.hex()]
    if type(value)is str:return ['str',value]
    if type(value)is dt.datetime:return ['datetime',value.isoformat()]
    if type(value)is dt.date:return ['date',value.isoformat()]
    if type(value)is Decimal:return ['decimal',str(value)]
    if type(value)is dict:
        items=[[_canonical(key),_canonical(item)]for key,item in value.items()]
        items.sort(key=lambda item:json.dumps(item[0],sort_keys=True,ensure_ascii=True,separators=(',',':')))
        return ['dict',items]
    if type(value)in (list,tuple):return [type(value).__name__,[_canonical(item)for item in value]]
    if type(value)in (set,frozenset):
        items=[_canonical(item)for item in value]
        items.sort(key=lambda item:json.dumps(item,sort_keys=True,ensure_ascii=True,separators=(',',':')))
        return [type(value).__name__,items]
    raise TypeError('unsupported synthetic oracle type: '+type(value).__name__)


@pytest.mark.parametrize('mode',['contract','party','code','mixed','tax','refund','missing_amount','undated','blank'])
def test_default_mapper_legacy_events_and_all_cash_fields_equal_accepted(accepted,mode):
    reg=copy.deepcopy(REG);rows=[pay(),pay(row=11)];crosswalk=copy.deepcopy(OFFICIAL)
    if mode=='party':
        for row in rows:row['contract']='Other'
    elif mode=='code':
        for row in rows:row.update(contractor='Unknown',contract='Other')
    elif mode=='mixed':
        reg['rows'].append({'counterparty':'Admin','contract':'A','estimate_code':'2.6','bdds_code':'2.4.5'})
        crosswalk['articles_by_estimate_code']['2.6']={'project_management','tax'}
    elif mode=='tax':reg['rows'][0]['bdds_code']='2.4.5'
    elif mode=='refund':rows[1]['amount']=-5
    elif mode=='missing_amount':rows[1]['amount']=None
    elif mode=='undated':rows[1]['date']=None
    elif mode=='blank':
        reg['rows'][0].update(counterparty='—',contract='№')
        for row in rows:row.update(contractor='—',contract='№')
    new_events=[];payments={'rows':rows,'total':None};expected=accepted['cases'][mode]
    assert _canonical({'payments':payments,'register':reg,'crosswalk':crosswalk,'budget':{'budget':1000},'bdds':{},'cut':'2023-02-15'})==expected['inputs']
    new=actuals.payments_by_article(copy.deepcopy(payments),copy.deepcopy(reg),crosswalk=copy.deepcopy(crosswalk),classification_observer=new_events.append)
    assert _canonical(new)==expected['default_mapper'] and _canonical(new_events)==expected['legacy_observer']
    new_cash=cash.calculate({'budget':1000},copy.deepcopy(payments),copy.deepcopy(reg),copy.deepcopy(crosswalk),{},'2023-02-15')
    new_cash.pop('classification_audit')
    assert _canonical(new_cash)==expected['cash']


@pytest.mark.parametrize('official,state',[(None,'unavailable'),({},'missing'),
    ({'2.6':{'project_management','tax'}},'ambiguous'),({'2.6':{'project_management'}},'same_unique_article'),
    ({'2.6':{'tax'}},'different_unique_article')])
def test_competing_official_states_are_evidence_not_an_automatic_wrong_payment_verdict(official,state):
    crosswalk=None if official is None else {'articles_by_estimate_code':official}
    result=calculate(crosswalk=crosswalk);detail=result['classification_audit']
    assert result['paid_known_part']==20
    assert {case['official_code']['state'] for case in detail['cases']}=={state}
    assert all(not case['official_code']['is_wrong_payment_verdict'] for case in detail['cases'])
    assert not detail['financial_acceptance'] and detail['confirmed_excess'] is None


def test_group_is_only_its_counted_subset_not_the_whole_focus_month():
    result=calculate([pay(),pay(row=11),pay(100,row=12)])
    detail=result['classification_audit'];group,=detail['duplicate_groups']
    assert detail['focus_paid_observed_net']==120 and detail['focus_selected_ahr']['signed_amount']==120
    assert group['cardinality']==2 and group['member_source_rows']==[10,11]
    assert group['included_ahr']['signed_amount']==20 and group['confirmed_excess'] is None
    assert detail['cases'][0]['duplicate_group_token']==detail['cases'][1]['duplicate_group_token']==group['token']
    assert detail['cases'][2]['duplicate_group_token'] is None


def test_only_unresolved_duplicate_group_keeps_its_members_without_counting_them_as_ahr_paid():
    rows=[pay(10,row=10),pay(7,row=11,party='Unknown',contract='?'),pay(7,row=12,party='Unknown',contract='?')]
    crosswalk={'articles_by_estimate_code':{'2.6':{'project_management','tax'}}}
    result=calculate(rows,crosswalk=crosswalk);detail=result['classification_audit'];group,=detail['duplicate_groups']
    assert result['paid_known_part']==10 and detail['focus_selected_ahr']['signed_amount']==10
    assert detail['focus_selected_ahr_cases']==1 and detail['unresolved_duplicate_evidence_cases']==2
    assert group['included_ahr_cases']==0 and group['included_ahr']['signed_amount']==0
    assert group['unresolved_members']==2 and group['unresolved']['signed_amount']==14
    assert len(detail['cases'])==3 and group['confirmed_excess'] is None


def test_unknown_amount_duplicate_members_stay_unknown_and_are_not_false_conflicts():
    result=calculate([pay(10,row=10),pay(None,row=11),pay(None,row=12)])
    detail=result['classification_audit'];group,=detail['duplicate_groups']
    assert group['unresolved']['signed_amount'] is None and group['unresolved']['unknown_amount_count']==2
    assert [case['official_code']['state'] for case in detail['cases'][1:]]==['unique_unselected']*2
    assert result['paid_known_part']==10


def test_bdds_replaced_month_and_future_rows_cannot_become_audit_focus_or_paid_cases():
    rows=[pay(10000,row=10),pay(10000,row=11),pay(10,row=12,day='2023-02-10'),pay(10,row=13,day='2023-02-10'),
          pay(90000,row=14,day='2023-02-16'),pay(90000,row=15,day='2023-02-16')]
    result=calculate(rows,bdds={'2023-01-01':{'fact':5,'source':{}}});detail=result['classification_audit']
    assert result['paid_known_part']==25 and detail['focus_month']=='2023-02-01'
    assert [case['source_row'] for case in detail['cases']]==[12,13]
    assert result['coverage']['future_rows_excluded']==2


def test_focus_abs_tie_is_deterministic_and_signed_refunds_are_preserved():
    rows=[pay(-10,row=10),pay(-10,row=11),pay(10,row=12,day='2023-02-10'),pay(10,row=13,day='2023-02-10')]
    detail=calculate(rows)['classification_audit']
    assert detail['focus_month']=='2023-01-01' and detail['focus_paid_observed_net']==-20
    assert detail['duplicate_groups'][0]['included_ahr']['signed_amount']==-20


def test_blank_placeholder_binding_is_visible_without_showing_the_text():
    reg={'rows':[{'counterparty':'—','contract':'№','estimate_code':'2.6','bdds_code':'2.4.1'}]}
    detail=calculate([pay(party='—',contract='№'),pay(row=11,party='—',contract='№')],reg)['classification_audit']
    flags=detail['cases'][0]['binding_flags']
    assert flags=={'party_present':True,'contract_present':True,'party_normalized_empty':True,
                   'contract_normalized_empty':True,'pair_normalized_empty':True}
    assert detail['cases'][0]['selected_basis']=='contract_and_estimate'


def test_party_candidate_is_only_present_when_that_basis_is_selected():
    detail=calculate([pay(contract='Other'),pay(row=11,contract='Other')])['classification_audit']
    assert all(case['party_when_used']['codes']==['2.4.1'] for case in detail['cases'])
    assert calculate()['classification_audit']['cases'][0]['party_when_used'] is None


def test_hmac_links_work_within_build_and_are_unlinkable_across_builds():
    first=calculate()['classification_audit'];second=calculate()['classification_audit']
    a,b=first['cases']
    assert a['pair_token']==b['pair_token'] and a['contract_token']==b['contract_token']
    assert a['pair_token']!=a['contract_token'] and a['pair_token']!=a['duplicate_group_token']
    assert a['pair_token']!=second['cases'][0]['pair_token']


def test_nested_sensitive_canaries_and_noncanonical_codes_never_enter_audit(monkeypatch):
    reg={'rows':[{'counterparty':'PRIVATE-PARTY','contract':'PRIVATE-CONTRACT','estimate_code':'PRIVATE-ESTIMATE','bdds_code':'2.4.PRIVATE-BDDS'}]}
    rows=[pay(party='PRIVATE-PARTY',contract='PRIVATE-CONTRACT',code='PRIVATE-ESTIMATE',source='PRIVATE-SOURCE'),
          pay(row=11,party='PRIVATE-PARTY',contract='PRIVATE-CONTRACT',code='PRIVATE-ESTIMATE',source='PRIVATE-SOURCE')]
    monkeypatch.setattr(audit.secrets,'token_bytes',lambda n:b'PRIVATE-HMAC-KEY-NEVER-EXPORTED!!!'[:n])
    detail=calculate(rows,reg,crosswalk=None)['classification_audit'];text=json.dumps(detail,ensure_ascii=False)
    assert 'PRIVATE' not in text and detail['cases'][0]['estimate_code'] is None
    assert detail['cases'][0]['exact_pair_estimate']['redacted_codes']==1
    bound=audit.bind_sources(detail,{'fm':{'sha256':'PRIVATE-SHA','version_date':'/PRIVATE/PATH','metadata_bound_to_bytes':'PRIVATE'},'rss':{}},{})
    assert 'PRIVATE' not in json.dumps(bound) and bound['source_binding']['fm']['version_date'] is None


def test_source_unavailable_or_changed_strips_details_without_claiming_lost_cases_are_emitted():
    detail=calculate()['classification_audit']
    for errors,state in [({'rss':'unavailable'},'source_unavailable'),({'rss':'changed_or_unavailable'},'source_changed')]:
        result=audit.bind_sources(detail,{'fm':{},'rss':{}},errors)
        assert result['state']==state and result['cases']==result['duplicate_groups']==[]
        assert result['emitted_cases']==0 and result['omitted_cases']==result['total_cases']


def test_cardinality_caps_preserve_precap_population_and_signed_total(monkeypatch):
    monkeypatch.setattr(audit,'MAX_BYTES',2*1024*1024)  # Isolate cardinality gate; production limit is tested below.
    detail=calculate([pay(1,row=row) for row in range(10,150)])['classification_audit']
    assert detail['focus_paid_observed_net']==140 and detail['total_cases']==140
    assert detail['emitted_cases']==128 and detail['omitted_cases']==12 and detail['truncated']
    group,=detail['duplicate_groups']
    assert group['cardinality']==140 and group['emitted_members']==128 and group['omitted_members']==12
    assert group['included_ahr']['signed_amount']==140


def test_candidate_set_cap_and_byte_fallback_are_explicit(monkeypatch):
    reg={'rows':[{'counterparty':'Admin','contract':'A','estimate_code':'2.6','bdds_code':'2.4.'+str(i)} for i in range(1,25)]}
    detail=calculate(reg=reg)['classification_audit'];candidate=detail['cases'][0]['exact_pair_estimate']
    assert candidate['total_codes']==24 and candidate['emitted_codes']==16 and candidate['omitted_codes']==8 and candidate['truncated']
    monkeypatch.setattr(audit,'MAX_BYTES',2500)
    detail=calculate()['classification_audit']
    assert detail['state']=='byte_limit' and detail['cases']==detail['duplicate_groups']==[]
    assert detail['total_cases']==detail['omitted_cases']==2 and detail['emitted_cases']==0
    assert len(json.dumps(detail,ensure_ascii=False,separators=(',',':')).encode())<=2500


@pytest.mark.parametrize('method',['fingerprint','record_candidates','build'])
def test_diagnostic_failure_never_changes_known_cash_or_classifier_results(monkeypatch,accepted,method):
    def fail(*args,**kwargs):raise RuntimeError('PRIVATE-DIAGNOSTIC-ERROR')
    monkeypatch.setattr(audit.AuditEvents,method,fail)
    result=calculate();detail=result.pop('classification_audit')
    expected=accepted['diagnostic_failure_expected']
    assert _canonical(result)==expected and detail['state']=='diagnostic_unavailable'
    assert 'PRIVATE' not in json.dumps(detail)


def test_one_mapper_call_and_no_source_reader_call_for_the_diagnostic(monkeypatch):
    real=actuals.payments_by_article;calls=[]
    def counted(*args,**kwargs):calls.append(True);return real(*args,**kwargs)
    monkeypatch.setattr(actuals,'payments_by_article',counted)
    def forbidden(*args,**kwargs):pytest.fail('pure diagnostic read a source')
    monkeypatch.setattr(cash.source,'_copy',forbidden);monkeypatch.setattr(cash.rss_source,'_rss_copy',forbidden)
    assert calculate()['classification_audit']['total_cases']==2 and len(calls)==1


def test_group_cap_and_production_byte_cap_keep_full_counts_and_focus_total(monkeypatch):
    rows=[]
    for i in range(65):rows += [pay(i+1,row=10+2*i),pay(i+1,row=11+2*i)]
    with monkeypatch.context() as context:
        context.setattr(audit,'MAX_BYTES',2*1024*1024)
        detail=calculate(rows)['classification_audit']
    assert detail['total_groups']==65 and detail['emitted_groups']==64 and detail['omitted_groups']==1
    assert detail['total_cases']==130 and detail['focus_paid_observed_net']==4290 and detail['truncated']
    detail=calculate(rows)['classification_audit']
    assert audit.MAX_BYTES==131072
    assert len(json.dumps(detail,ensure_ascii=False,separators=(',',':')).encode())<=131072
    assert detail['total_cases']==130 and detail['total_groups']==65 and detail['focus_paid_observed_net']==4290
    if detail['state']=='byte_limit':
        assert detail['cases']==detail['duplicate_groups']==[] and detail['omitted_cases']==130 and detail['omitted_groups']==65


def test_unknown_or_ambiguous_row_identity_does_not_invent_group_money():
    for rows in ([pay(row=None),pay(row=None)],[pay(row=10),pay(row=10)]):
        result=calculate(rows);detail=result['classification_audit']
        assert result['paid_known_part']==20 and detail['state']=='source_row_identity_unavailable'
        assert detail['cases']==detail['duplicate_groups']==[]


def test_noncanonical_official_article_is_redacted_without_a_false_conflict():
    detail=calculate(crosswalk={'articles_by_estimate_code':{'2.6':{'PRIVATE-ARTICLE'}}})['classification_audit']
    assert detail['cases'][0]['official_code']['state']=='redacted_or_unmapped'
    assert 'PRIVATE' not in json.dumps(detail)


def test_diagnostic_state_and_flags_do_not_offer_a_free_text_channel():
    assert 'PRIVATE' not in json.dumps(audit.unavailable('PRIVATE-STATE'))
    collector=audit.AuditEvents(cash.number,cash.scalar)
    event={'source_row':10,'date':dt.date(2023,1,10),'amount':1,'article':'project_management',
           'basis':'по договору','estimate_code':'2.6','possible_articles':['project_management'],'scope_unknown':False}
    collector.record_candidates(event,exact_codes={'2.4'},contract_codes={'2.4'},party_codes=None,
        official_articles={'project_management'},normalized_pair='PRIVATE-PAIR',normalized_contract='PRIVATE-CONTRACT',
        flags={'party_present':'PRIVATE-FLAG','contract_present':False,'private_key':'PRIVATE-NESTED'})
    case=collector._case(event)
    assert case['binding_flags']=={'party_present':None,'contract_present':False}
    assert 'PRIVATE' not in json.dumps(case)
