"""Earned volume is a labelled plan model, never dated production history."""
import copy
import io
import json

import pytest
from openpyxl import load_workbook

import developaid_contract_gpr as gpr
import developaid_contract_gpr_export as export
import developaid_contract_files as files
from tests.test_contract_relative_gpr_calendar import card, change, ROW, PROJECT, CUT, operation_projection_case


def view(fraction, planned=.5, *, start='2026-08-01', finish='2027-02-28', cut='2026-11-24', segments=None):
    line = {'code':'G','name':'Учебный объём','start':start,'finish':finish}
    if segments:
        line['segments'] = segments
    overlay = {'fact_fraction':min(fraction,1),'planned_fraction':planned,
        'fact_quantity':fraction*100,'contract_quantity':100,'unit':'м2','lag_days':4}
    return export.presentation({'lines':[line]},{'G':overlay},cut)['rows'][0]


def test_green_after_cut_is_closed_typed_volume_equivalence_not_calendar_fact():
    row = view(.8155644465364399,116/212)
    assert row['bars'] == [{'start':0,'end':212,'state':'plan'}]
    model = row['earned_equivalent']
    assert model['basis'] == 'earned_plan_equivalent' and model['production_history_available'] is False
    assert 'не фактические даты' in model['assumption'] and 'активным интервалам' in model['assumption']
    assert model['bars'][0]['end'] == pytest.approx(172.89966266572526)
    assert model['bars'][0]['end'] > 116 and model['bars'][0]['state'] == 'earned_volume'
    assert not any(bar['state']=='quantity_shortfall' for bar in model['bars'])
    assert row['deadline_status']['state'] == 'not_due'
    assert row['progress']['delta_pp'] == pytest.approx(26.83946352156852)


@pytest.mark.parametrize('fraction',[0,.25])
def test_red_is_only_the_quantity_shortfall_to_data_cut_not_future_remainder(fraction):
    row = view(fraction,116/212)
    red = [bar for bar in row['earned_equivalent']['bars'] if bar['state']=='quantity_shortfall']
    assert red == [{'start':fraction*212,'end':116,'state':'quantity_shortfall'}]
    assert all(bar['end'] <= 116 for bar in red)
    assert all(bar['state']=='plan' for bar in row['bars'])


def test_source_gaps_are_excluded_from_uniform_earned_and_shortfall_lengths():
    row = view(.7,.75,finish='2026-09-10',cut='2026-09-05',segments=[
        {'start':'2026-08-01','finish':'2026-08-10'},
        {'start':'2026-09-01','finish':'2026-09-10'}])
    assert row['earned_equivalent']['bars'] == [
        {'start':0,'end':10,'state':'earned_volume'},
        {'start':31,'end':35,'state':'earned_volume'},
        {'start':35,'end':36,'state':'quantity_shortfall'}]
    assert all(bar['end']<=10 or bar['start']>=31 for bar in row['earned_equivalent']['bars'])


@pytest.mark.parametrize('fraction',[1,1.4])
def test_known_full_or_excess_volume_never_claims_actual_completion_date_or_on_time(fraction):
    row = view(fraction,0,start='2026-12-01')
    model = row['earned_equivalent']
    assert row['progress']['fraction'] == fraction and model['fact_fraction'] == fraction
    assert sum(bar['end']-bar['start'] for bar in model['bars'] if bar['state']=='earned_volume') == 90
    assert not any(bar['state']=='quantity_shortfall' for bar in model['bars'])
    assert row['deadline_status']['state'] == 'quantity_complete_date_unknown'
    assert row['deadline_status']['actual_finish'] is None and 'on_time' not in row['deadline_status']


def test_past_deadline_known_incomplete_has_remaining_quantity_and_elapsed_days():
    row = view(.4,1,start='2026-10-01',finish='2026-10-31')
    status = row['deadline_status']
    assert status['state'] == 'overdue_incomplete'
    assert (status['remaining_quantity'],status['remaining_fraction'],status['days_after_planned_finish']) == (60,.6,24)
    assert all(bar['end']<=31 for bar in row['earned_equivalent']['bars'])
    assert not any(bar['state'] in {'fact','lag'} for bar in row['bars'])
    assert view(.4,1,finish='2026-11-24')['deadline_status']['state'] == 'not_due'


def test_unknown_is_not_zero_or_proven_deficit_and_unattributable_quantity_has_no_date_model():
    line = {'code':'G','name':'Неизвестный факт','start':'2026-10-01','finish':'2026-10-31'}
    unknown = export.presentation({'lines':[line]},{},'2026-11-24')['rows'][0]
    assert unknown['progress'] is unknown['earned_equivalent'] is None
    assert unknown['deadline_status']['state'] == 'overdue_unknown'
    assert 'remaining_quantity' not in unknown['deadline_status']
    line.update(quantity={'fact_quantity':40,'contract_quantity':100,'unit':'м2','fraction':.4})
    unbound = export.presentation({'lines':[line]},{},'2026-11-24')['rows'][0]
    assert unbound['progress']['fraction'] == .4 and unbound['earned_equivalent'] is None
    assert unbound['deadline_status']['state'] == 'deadline_comparison_unconfirmed'
    assert 'remaining_quantity' not in unbound['deadline_status']
    missing_plan=view(.4,None)
    assert missing_plan['progress']['fraction']==.4 and missing_plan['earned_equivalent'] is None


def test_relative_without_anchor_does_not_gain_calendar_equivalence():
    line={'code':'G','name':'Относительный план','relative_segments':[{'start_day':1,'finish_day':7,'start_offset':0,'end_offset':7}]}
    overlay={'fact_fraction':.5,'planned_fraction':None,'fact_quantity':50,'contract_quantity':100,'unit':'м2'}
    row=export.presentation({'calendar_basis':'relative','columns':[{'period':1,'start_day':1,'finish_day':7}],
        'lines':[line]},{'G':overlay},'2026-11-24')['rows'][0]
    assert row['progress']['fraction']==.5 and row['earned_equivalent'] is None


def test_past_plan_clock_headroom_contains_current_timezone_days_without_extending_source():
    schedule={'lines':[{'code':'G','name':'Прошлый план','start':'2026-08-17','finish':'2026-10-31'}]}
    old=copy.deepcopy(schedule)
    shown=export.presentation(schedule,{},'2026-11-24',_include_day='2026-11-25',_headroom_days=14)
    assert shown['ticks'][-1]['finish']=='2026-12-09'
    assert shown['start']=='2026-08-17' and schedule==old
    row,=shown['rows']
    assert row['bars']==[{'start':0,'end':76,'state':'unknown'}]
    assert any(tick['start']<='2026-11-26'<=tick['finish'] for tick in shown['ticks'])
    assert all(shown['ticks'][index]['finish']<='2026-10-31'
        for index in export.cell_states(schedule['lines'][0],shown['ticks'],None))


def test_display_prioritises_overdue_but_does_not_reorder_original_rds():
    listed,rds,schedule=operation_projection_case()
    rds['rows'][0].update(start='2026-12-01',finish='2026-12-31')
    positions=gpr.position_projections(listed,rds,schedule)
    # Keep the accepted past source dates for the second (known-zero) row.
    ordered=export.ordered_positions(positions,'2026-02-25')
    assert ordered[0]['number']=='1.2'
    assert [row['number'] for row in rds['rows']]==['1.1','1.2']


def test_excel_source_plan_and_equivalent_are_distinct_rows_with_closed_provenance(card):
    listed=change(files.listing(PROJECT,ROW['id'],CUT))
    binding,rds,schedule=operation_projection_case();listed['plan']['editions']=binding['plan']['editions']
    from developaid_contract_rds import FIELDS
    rds.update(layout=export.LAYOUT,cut='2026-02-25')
    rds['rows']=[{**{key:None for key in FIELDS},**row} for row in rds['rows']]
    listed.update(rds_comparison=rds);listed['gpr'].update(schedule=schedule,overlays={})
    meta=export.bind_snapshot(PROJECT,rds['cut'],ROW['id'],listed,ROW)
    book=load_workbook(io.BytesIO(export.workbook(meta,listed)));sheet=book['ГПР']
    source=next(row for row in sheet if str(row[1].value or '').startswith('Монтаж каркаса'))
    model=list(sheet)[source[0].row]
    source_pin=json.loads(source[1].comment.text);model_pin=json.loads(model[1].comment.text)
    assert source_pin['track']=='source_plan' and model_pin['track']=='earned_plan_equivalent'
    assert source_pin['position_key']==model_pin['position_key']==[0,0]
    assert 'модель, не даты выполнения' in model[1].value
    assert source[4].value==.4 and model[4].value is None
    assert not any(cell.fill.fgColor.rgb in {'0070AD47','00E06666'} for cell in source[6:])
    colored=[cell for cell in model[6:] if cell.fill.fgColor.rgb in {'0070AD47','00E06666'}]
    assert colored and all(json.loads(cell.comment.text)['not_actual_dates'] is True for cell in colored)
    assert source[5].font.color is None or source[5].font.color.type!='rgb' or source[5].font.color.rgb!='00E06666'
    assert 'вне диапазона календаря; обновите выгрузку' in next(cell.value for row in sheet for cell in row if cell.data_type=='f')
