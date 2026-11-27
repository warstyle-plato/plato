"""An existing source candidate is visible without silently accepting a scope mismatch."""
import developaid_contract_schedule_links as links


def test_different_source_qualification_keeps_both_names_and_an_unaccepted_candidate():
    rds_name='Покрытие испытательное марки Т9 (участок А)'
    gpr_name='Покрытие испытательное марки Т9 (участок Б)'
    estimate={'positions':[{'number':'7.4.2','name':rds_name,'unit':'м2','quantity':10,
                            'amount':{'total':100},'group':None,'section':None}]}
    schedule={'lines':[{'code':'7.4.2','name':gpr_name,'start':'2026-05-01','finish':'2026-05-10'}]}
    # A qualification difference is authoritative: no plan or fact is
    # manufactured merely because the full source number is the same.
    row=links.propose(estimate,schedule)['positions'][0]
    assert row['status']=='review' and row['lines']==[]
    assert row['suggested']==[]
    assert [x['code'] for x in row['source_candidates']]==['7.4.2']
    assert rds_name in row['reason'] and gpr_name in row['reason']


def test_repeated_full_numbers_do_not_create_a_false_unique_candidate():
    estimate={'positions':[{'number':'7.4.2','name':'Другая операция','unit':'м2','quantity':10,
                            'amount':{'total':100},'group':None,'section':None}]}
    schedule={'lines':[{'code':'7.4.2','name':'Операция А','start':'2026-05-01','finish':'2026-05-10'},
                       {'code':'7.4.2, повтор','printed':'7.4.2','name':'Операция Б','start':'2026-05-01','finish':'2026-05-10'}]}
    row=links.propose(estimate,schedule)['positions'][0]
    assert row['status']=='review' and row['lines']==[] and row['suggested']==[]
