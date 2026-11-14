"""Synthetic missing identities cannot become qualified contract matches."""
import copy
import datetime as dt

import pytest

import developaid_actuals as actuals
import developaid_admin_expenses_cash as cash
from test_payments_join_the_contract_register import _row

PARTY='Example counterparty'
DAY=dt.date(2026,10,7)

def payment(amount=120,*,party=PARTY,contract='',code='3.5',day=DAY,row=1):
    return {'contractor':party,'contract':contract,'estimate_code':code,'amount':amount,
            'date':day,'source_row':row,'source':'own'}

def register(*rows):return {'rows':list(rows)}
def official(articles):return {'articles_by_estimate_code':{'3.5':set(articles)}}

def mapped(rows,reg,*,crosswalk=None,gns=None):
    events=[]
    out=actuals.payments_by_article({'rows':rows,'total':sum(x['amount']for x in rows if x['amount']is not None)},
        reg,gns,crosswalk,classification_observer=events.append)
    return out,events


@pytest.mark.parametrize('contract',[None,'','   ','№ — / ()'])
@pytest.mark.parametrize('mixed_party',[False,True])
def test_empty_contract_never_overrides_unique_official_financing(contract,mixed_party):
    rows=[_row(PARTY,'','2.4.1','2.6')]
    if mixed_party:rows.append(_row(PARTY,'Other-B','2.3.1','2.6'))
    out,events=mapped([payment(contract=contract)],register(*rows),crosswalk=official({'financing'}))
    assert out['matched']=={'по коду РСС':120}
    assert out['other_by_article']=={'financing':{DAY.replace(day=1):120}}
    assert not out['capex_by_article'] and events[0]['possible_articles']==['financing']
    assert events[0]['basis']=='по коду РСС' and events[0]['scope_unknown']is False


@pytest.mark.parametrize('party',[None,'','   ','— () /'])
def test_missing_party_cannot_form_a_contract_pair_or_counterparty_join(party):
    reg=register(_row('','Known-A','2.4.1','2.6'))
    out,events=mapped([payment(party=party,contract='Known-A')],reg,crosswalk=official({'financing'}))
    assert out['matched']=={'по коду РСС':120} and events[0]['article']=='financing'


@pytest.mark.parametrize('pay_code,expected_basis',[('2.6','по договору и коду РСС'),('3.5','по договору')])
def test_qualified_contract_keeps_priority_over_different_official_article(pay_code,expected_basis):
    reg=register(_row(PARTY,'Known-A','2.4.1','2.6'))
    crosswalk={'articles_by_estimate_code':{pay_code:{'financing'}}}
    out,events=mapped([payment(contract='Known-A',code=pay_code)],reg,crosswalk=crosswalk)
    assert out['matched']=={expected_basis:120} and events[0]['article']=='project_management'
    assert out['capex_by_article']['project_management'][DAY.replace(day=1)]==120


@pytest.mark.parametrize('articles',[set(),{'project_management'},{'project_management','financing'},{'financing','tax'}])
def test_unbound_party_fallback_without_a_unique_official_contradiction_is_preserved(articles):
    reg=register(_row(PARTY,'Known-A','2.4.1','2.6'))
    out,events=mapped([payment()],reg,crosswalk=official(articles))
    assert out['matched']=={'по контрагенту':120} and events[0]['article']=='project_management'
    assert 'project_management'in events[0]['possible_articles']


def test_register_derived_code_is_not_promoted_to_explicit_crosswalk_authority():
    reg=register(_row(PARTY,'Known-A','2.4.1','2.6'),_row('Another party','Known-B','3.1','3.5'))
    out,_=mapped([payment()],reg)
    assert out['matched']=={'по контрагенту':120}


def test_unknown_official_category_does_not_override_valid_weak_evidence():
    reg=register(_row(PARTY,'Known-A','2.4.1','2.6'))
    out,_=mapped([payment()],reg,crosswalk=official({'not_a_native_article'}))
    assert out['matched']=={'по контрагенту':120}


def test_unbound_gns_party_split_cannot_override_unique_official_article():
    reg=register(_row(PARTY,'Known-A','2.2.2.1','2.6'))
    out,_=mapped([payment()],reg,crosswalk=official({'financing'}),gns={'above':3,'under':1})
    assert out['other_by_article']=={'financing':{DAY.replace(day=1):120}} and out['capex_by_article']=={}
    qualified,_=mapped([payment(contract='Known-A')],reg,crosswalk=official({'financing'}),gns={'above':3,'under':1})
    assert qualified['capex_by_article']=={'main_above':{DAY.replace(day=1):90},'main_under':{DAY.replace(day=1):30}}


def test_undated_and_missing_amount_keep_admissible_ahr_possibilities():
    reg=register(_row(PARTY,'Known-A','2.4.1','2.6'))
    crosswalk=official({'financing','tax'})
    rows=[payment(7,day=None),payment(None,row=2)]
    _,events=mapped(rows,reg,crosswalk=crosswalk)
    assert all('project_management'in e['possible_articles']for e in events)
    assert all(e['article']is None for e in events)
    result=cash.calculate({'budget':100},{'rows':rows},reg,crosswalk,{},'2026-11-14')
    assert result['paid_known_part']is None
    assert result['coverage']['unknown_date_possible_ahr_rows']==1
    assert result['coverage']['possible_ahr_unresolved_by_month']=={'2026-10-01':1}


def test_observer_does_not_expose_invalid_pair_candidates_as_contract_evidence():
    reg=register(_row(PARTY,'','2.4.1','2.6'))
    rows=[payment(),payment(row=2)]
    result=cash.calculate({'budget':100},{'rows':rows},reg,official({'project_management'}),{},'2026-11-14')
    audit=result['classification_audit']
    assert audit['focus_selected_ahr']['signed_amount']==240
    assert audit['cases'][0]['selected_basis']=='party'
    assert all(c['whole_contract']['total_codes']==c['exact_pair_estimate']['total_codes']==0 for c in audit['cases'])
    assert all(c['binding_flags']['contract_normalized_empty']for c in audit['cases'])
    assert result['coverage']['classified_not_strong_months']==['2026-10-01']


@pytest.mark.parametrize('contract',[None,''])
def test_partial_raw_identity_is_diagnostic_only_and_keeps_legacy_normalization(contract):
    class Observer(list):
        def __init__(self):super().__init__();self.evidence=[]
        def __call__(self,event):self.append(event)
        def record_candidates(self,event,**evidence):self.evidence.append(evidence)
    observer=Observer();row=payment(contract=contract)
    actuals.payments_by_article({'rows':[row],'total':120},register(_row(PARTY,'','2.4.1','2.6')),
                               crosswalk=official({'financing'}),classification_observer=observer)
    evidence=observer.evidence[0]
    assert evidence['normalized_pair']=='examplecounterparty'+(''if contract is None else '|')
    assert evidence['normalized_contract']==(None if contract is None else '')
    assert evidence['exact_codes']==evidence['contract_codes']==set()
    assert evidence['flags']['contract_normalized_empty']is True


def test_signed_zero_and_refund_rows_are_not_deduplicated_or_dropped():
    reg=register(_row(PARTY,'','2.4.1','2.6'))
    rows=[payment(12),payment(-3,row=2),payment(0,row=3),payment(12,row=4)]
    before=copy.deepcopy(rows)
    out,events=mapped(rows,reg,crosswalk=official({'financing'}))
    assert rows==before and out['matched']=={'по коду РСС':21}
    assert [e['amount']for e in events]==[12,-3,0,12] and out['mapped']==21


def test_bdds_replacement_and_known_part_semantics_are_unchanged():
    reg=register(_row(PARTY,'Known-A','2.4.1','2.6'))
    crosswalk={'articles_by_estimate_code':{'2.6':{'project_management'},'3.5':{'financing'}}}
    rows=[payment(20,contract='Known-A',code='2.6'),payment(-5,contract='Known-A',code='2.6',row=2),payment(90,day=dt.date(2026,11,2),row=3)]
    bdds={'2026-10-01':{'fact':35,'source':{'sha256':'a'*64}}}
    result=cash.calculate({'budget':100},{'rows':rows},reg,crosswalk,bdds,'2026-11-14')
    october=result['months'][0]
    assert october['paid']==35 and october['rss_observed_context']==15 and october['budget_fact_included']
    assert result['paid_known_part']==35 and result['balance_after_observed_payments']==65
    assert result['coverage']['excluded_non_ahr_classified_rows']==1
    assert result['remaining_need']is None and result['financial_acceptance']is False
