"""Physical source values must remain inspectable without fabricating accepted zeros."""
import datetime as dt
from openpyxl import Workbook
from developaid_contract_physical_audit import position_audit
from developaid_contract_physical_sheets import write_builder_template, write_audit
from tests.test_contract_gpr_earned_plan_equivalent import view, event


def test_no_report_day_resets_quantity_and_plan_can_overtake_it():
    row = view(60,[event(60,'2026-11-10')])
    model = row['reporting']
    states = {day:bar for bar in model['bars'] if bar['range_kind']!='retrospective_report_assessment' for day in range(bar['start'],bar['end'])}
    assert set(states) == set(range(9,24))  # every day from observation to cut
    assert states[9]['state']=='fact' and states[23]['state']=='warning'
    assert all(bar['fact_quantity']==60 and bar['report_date']=='2026-11-10' for bar in states.values())
    assert not any(day>=24 for day in states)  # future never green
    assert all(p['date']=='2026-11-10' for p in model['checkpoints'])


def test_later_catchup_preserves_all_earlier_daily_states():
    a=view(10,[event(10,'2026-11-10')],cut='2026-11-19')['reporting']
    b=view(90,[event(10,'2026-11-10'),event(80,'2026-11-20',label='second')])['reporting']
    expand=lambda m:{day:bar['state'] for bar in m['bars'] for day in range(bar['start'],bar['end'])}
    assert all(expand(a)[day]==expand(b)[day] for day in expand(a))


def test_source_cached_zero_is_visible_but_not_accepted_as_work():
    p={'number':'1','name':'Монтаж','unit':'м2','quantity':10}
    current={'estimates':[{'positions':[p]}], 'estimate_sha256':'a'*64}
    raw={'position':'1','name':'Монтаж','unit':'м2','completed_quantity':0,'source':{'row':4,'completed_quantity_cell':'AV4'}}
    audit=position_audit(p,(0,0),current,{'physical_source_rows':[raw]},None,None,'2026-11-24')
    assert audit['sources'][0]['reported_work_quantity']==0
    assert audit['accepted_work_quantity'] is None
    assert audit['state']=='known_source_value_unaccepted'
    accepted=position_audit(p,(0,0),current,{}, {'work_observed':True,'work_quantity':0},None,'2026-11-24')
    assert accepted['state']=='confirmed_zero'


def test_entry_sheet_defaults_to_zero_and_separates_work_from_delivery():
    book=Workbook();r={'number':'1','name':'Монтаж','unit':'м2','contract_quantity':10,'estimate':0,'index':0,'fact_quantity':3}
    data={'rows':[r],'headings':[{'name':'Корпус 2','before_position':0}],'estimate_sha256':'a'*64}
    write_builder_template(book,data);write_audit(book,data);sheet=book['Физфакт строителей']
    assert sheet['A5'].value==sheet['A6'].value=='Корпус 2'
    assert [sheet['D5'].value,sheet['D6'].value]==['Монтаж','Поставка']
    assert sheet['L5'].value==0 and sheet['L6'].value==0
    assert sheet['I5'].value is None
    assert sheet['I1'].value is not None
    assert all(s.freeze_panes is None for s in book)
    assert len(sheet.data_validations.dataValidation)==2


def test_unit_conflict_keeps_the_known_source_number_visible():
    p={'number':'1','name':'Монтаж','unit':'м2','quantity':10}
    raw={'position':'1','name':'Монтаж','unit':'т','completed_quantity':7,'source':{'row':4}}
    audit=position_audit(p,(0,0),{'estimates':[{'positions':[p]}]},
                         {'physical_source_rows':[raw]},None,None,'2026-11-24')
    assert audit['state']=='unit_conflict'
    assert audit['sources'][0]['reported_work_quantity']==7
    assert audit['sources'][0]['source']['row']==4
    assert audit['accepted_work_quantity'] is None


def test_zero_from_cost_does_not_become_confirmed_physical_zero():
    p={'number':'1','name':'Монтаж','unit':'м2','quantity':10}
    raw={'position':'1','name':'Монтаж','unit':'м2','reported_completed_quantity':0,
         'source':{'row':4},'undated_periods':[{'quantity':0,'quantity_basis':'Нулевой объём подтверждён нулевой суммой при положительной цене компонента.'}]}
    audit=position_audit(p,(0,0),{'estimates':[{'positions':[p]}]},
                         {'physical_source_rows':[raw]}, {'work_observed':True,'work_quantity':0},None,'2026-11-24')
    assert audit['state']=='accounted_zero_physical_unknown'
    assert audit['accepted_work_quantity'] is None and audit['accounted_work_quantity']==0


def test_hierarchy_visibly_separates_corpus_and_number_depth():
    from developaid_contract_hierarchy import style_row
    book=Workbook();sheet=book.active
    for i,no in enumerate(['','1','1.1','1.1.1'],1):
        sheet.append([no,'Название'])
        style_row(sheet,i,no,corpus=i==1)
    assert len({sheet.cell(i,2).fill.fgColor.rgb for i in range(1,5)})==4
    assert [sheet.cell(i,2).alignment.indent for i in range(2,5)]==[0,1,2]
    assert sheet['B1'].font.color.rgb[-6:]=='FFFFFF'


def test_material_only_zero_increment_cannot_backfill_a_physical_baseline():
    material={**event(0,'2026-11-03'), 'physical_quantity_basis':'Нулевой объём подтверждён нулевой суммой при положительной цене компонента.'}
    positive=event(60,'2026-11-10',label='physical')
    result=view(60,[material,positive])['reporting']
    assert result['history_available']
    assert result['checkpoints'][0]['date']=='2026-11-10'
    assert min(b['start'] for b in result['bars'] if b['carried_forward'])==9
    assert all(b['report_date']!='2026-11-03' for b in result['bars'])
