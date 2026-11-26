"""Owner superseded earned-duration colouring with dated report-state colouring.

The old tests intentionally allowed future green in a separate model track.
The new contract keeps all future source-plan cells grey, with earned quantity
reported numerically and independent warnings/expired-deadline states.
"""
import copy
import datetime as dt
import hashlib
import io
import json

import pytest
from openpyxl import load_workbook

import developaid_contract_gpr as gpr
import developaid_contract_gpr_export as export
import developaid_contract_gpr_reporting as reporting
import developaid_contract_files as files
from tests.test_contract_relative_gpr_calendar import card, change, ROW, PROJECT, CUT, operation_projection_case


def event(quantity, end, start=None, *, label='КС-2 № 1', source=None):
    witness = {'source':source or {'file_sha256':'a'*64,'row':1,'quantity_cell':'M1'},
               'label':label,'start':start,'end':end}
    return {**witness,'id':hashlib.sha256(json.dumps(witness,sort_keys=True,
        ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
        'quantity_kind':'increment','work_quantity':quantity,
        'date_basis':'reported_period' if start else 'document_observation','preliminary':not bool(start)}


def view(quantity=40, events=(), cut='2026-11-24', finish='2026-11-30', source_dates=(), segments=None):
    line={'code':'G','name':'Физическая работа','start':'2026-11-01','finish':finish,
          'reporting_events':list(events)}
    if segments:line['segments']=segments
    from developaid_contract_plan import done
    planned=done(line,dt.date.fromisoformat(cut))
    overlay={'fact_quantity':quantity,'contract_quantity':100,'unit':'м2',
             'fact_fraction':quantity/100,'planned_fraction':planned,'lag_days':4}
    return export.presentation({'lines':[line]},{'G':overlay},cut,source_dates=source_dates)['rows'][0]


def test_initial_source_plan_is_grey_without_physical_report():
    row=export.presentation({'lines':[{'code':'G','name':'Работа','start':'2026-11-01',
        'finish':'2026-12-31'}]},{},'2026-11-24')['rows'][0]
    assert row['bars']==[{'start':0,'end':24,'state':'unknown'}, {'start':24,'end':61,'state':'plan'}]
    assert row['reporting']['bars']==[]
    assert export.COLORS['plan']=='D9D9D9' and export.COLORS['unknown']!='D9D9D9'


def test_yellow_old_period_survives_green_catchup_and_future_never_green():
    before=[event(10,'2026-11-10','2026-11-01')]
    first=view(10,before,cut='2026-11-10')['reporting']
    latest=view(80,before+[event(70,'2026-11-20','2026-11-11',label='КС-2 № 2')])['reporting']
    assert first['history_available'] and latest['history_available']
    assert latest['checkpoints'][0]==first['checkpoints'][0]
    assert [p['state'] for p in latest['checkpoints']]==['warning','fact']
    assert [(bar['start'],bar['end'],bar['state']) for bar in latest['bars']]==[(9,19,'warning'),(19,24,'fact')]
    assert all(bar['end']<=24 for bar in latest['bars'])
    assert latest['current']['delta_pp']==pytest.approx(0)


def test_overdue_is_red_only_after_dated_postdeadline_evidence():
    row=view(40,[event(40,'2026-11-15','2026-11-01')],finish='2026-11-10')
    red=[bar for bar in row['reporting']['bars'] if bar['state']=='overdue']
    assert red and max(bar['end'] for bar in red)==24
    assert min(bar['start'] for bar in red)==14
    assert red[-1]['range_kind']=='overdue_extension'
    stale=view(40,finish='2026-11-20',source_dates=['2026-11-18'])
    assert stale['deadline_status']['state']=='deadline_passed_unconfirmed'
    assert stale['reporting']['current']['state']=='closure_unconfirmed'
    assert not any(bar['state']=='overdue' for bar in stale['reporting']['bars'])
    fresh=view(40,finish='2026-11-20',source_dates=['2026-11-23'])
    assert fresh['deadline_status']['state']=='overdue_incomplete'
    assert max(bar['end'] for bar in fresh['reporting']['bars'])==24
    assert fresh['deadline_status']['days_after_planned_finish']==4


def test_equal_deadline_is_yellow_and_complete_has_no_on_time_claim():
    at=view(40,[event(40,'2026-11-10','2026-11-01')],cut='2026-11-10',finish='2026-11-10')
    assert at['reporting']['checkpoints'][0]['state']=='warning'
    complete=view(100,[event(100,'2026-11-15')],finish='2026-11-10')
    assert complete['deadline_status']['state']=='quantity_complete_date_unknown'
    assert complete['deadline_status']['actual_finish'] is None
    assert all(p['state']=='fact' for p in complete['reporting']['checkpoints'])
    assert 'actual_finish' not in complete['reporting'] and 'on_time' not in complete['reporting']


def test_document_observation_stays_a_point_but_its_quantity_persists_forward():
    row=view(80,[event(10,'2026-11-10'),event(70,'2026-11-20',label='КС-2 № 2')])
    assert [(bar['start'],bar['end']) for bar in row['reporting']['bars']]==[(9,19),(19,24)]
    assert all(p['start']==p['date'] for p in row['reporting']['checkpoints'])
    assert all(b['carried_forward'] and b['not_actual_dates'] for b in row['reporting']['bars'])
    assert all(p['date_basis']=='document_observation' for p in row['reporting']['checkpoints'])


def test_latest_total_without_increments_cannot_reconstruct_previous_reports():
    row=view(81.5,source_dates=['2026-11-18'])
    model=row['reporting']
    assert not model['history_available']
    assert [(b['start'],b['end'],b['range_kind']) for b in model['bars']]==[(17,24,'known_state')]
    assert model['last_confirmed_at']=='2026-11-18' and model['age_days']==6
    assert model['checkpoints'][0]['planned_fraction']==.6
    assert model['current']['planned_fraction']==.8
    assert model['checkpoints'][0]['date']=='2026-11-18'
    no_dates=view(81.5)['reporting']
    assert not no_dates['bars'] and not no_dates['checkpoints']


def test_known_zero_is_yellow_but_missing_quantity_is_grey():
    zero=view(0,[event(0,'2026-11-10','2026-11-01')])['reporting']
    assert zero['history_available'] and zero['checkpoints'][0]['state']=='warning'
    missing=reporting.project({'finish':'2026-11-10'},None,[(0,10)],'2026-11-01','2026-11-24')
    assert not missing['bars'] and missing['current'] is None


def test_duplicates_not_double_counted_and_conflicting_id_is_not_history():
    one=event(40,'2026-11-10','2026-11-01')
    a=view(40,[one,copy.deepcopy(one)])['reporting']
    assert a['history_available'] and a['checkpoints'][0]['fact_quantity']==40
    b=view(40,[one,{**one,'work_quantity':90}])['reporting']
    assert not b['history_available'] and not b['bars']


@pytest.mark.parametrize('bad',[True,float('nan'),-1,None])
def test_bad_increment_cannot_create_history(bad):
    model=view(40,[event(bad,'2026-11-10')])['reporting']
    assert not model['history_available'] and not model['bars']


def test_future_and_cumulative_inputs_never_become_increments():
    future=event(80,'2026-12-01')
    current=event(40,'2026-11-10')
    model=view(40,[future,current])['reporting']
    assert model['history_available'] and [p['date'] for p in model['checkpoints']]==['2026-11-10']
    bad=view(40,[{**current,'quantity_kind':'cumulative'}])['reporting']
    assert not bad['history_available'] and not bad['bars']


def test_gaps_remain_uncoloured_and_out_of_order_events_sort_by_report():
    parts=[{'start':'2026-11-01','finish':'2026-11-10'}, {'start':'2026-11-21','finish':'2026-11-30'}]
    events=[event(40,'2026-11-24','2026-11-21',label='КС-2 № 2'),event(10,'2026-11-10','2026-11-01')]
    model=view(50,events,segments=parts)['reporting']
    assert model['history_available']
    assert [p['date'] for p in model['checkpoints']]==['2026-11-10','2026-11-24']
    assert all(bar['end']<=10 or bar['start']>=20 for bar in model['bars'])


def test_excel_has_one_main_plan_track_grey_future_and_report_comments(card):
    listed=change(files.listing(PROJECT,ROW['id'],CUT))
    listed['gpr'].update(schedule={'lines':[{'code':'G','name':'Учебная работа',
        'start':'2026-11-01','finish':'2026-11-30',
        'reporting_events':[event(10,'2026-11-10','2026-11-01'),event(70,'2026-11-20','2026-11-11',label='КС-2 № 2')]}]},
        overlays={'G':{'fact_quantity':80,'contract_quantity':100,'unit':'м2','fact_fraction':.8,
            'planned_fraction':.8,'lag_days':0}})
    listed['rds_comparison']={'available':False}
    meta=export.bind_snapshot(PROJECT,'2026-11-24',ROW['id'],listed,ROW)
    before=copy.deepcopy(listed)
    book=load_workbook(io.BytesIO(export.workbook(meta,listed)));sheet=book['ГПР']
    assert listed==before
    row=next(row for row in sheet if row[1].value=='Учебная работа')
    assert 'reporting' in row[1].comment.text
    colors={c.fill.fgColor.rgb for c in row[6:]}
    assert {'00D9D9D9','0070AD47','00FFD966'}<=colors
    assert '00E06666' not in colors
    assert all(c.fill.fgColor.rgb=='00D9D9D9' for c in row[6+24:6+30])
    assert all(s.freeze_panes is None for s in book)
    assert not any('Выполненный объём в шкале плана' in str(c.value) for r in sheet for c in r)
    assert all(json.loads(c.comment.text.split('\n',1)[1])['not_actual_dates'] for c in row[6:] if c.comment)
