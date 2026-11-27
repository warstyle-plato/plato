"""A cumulative observation has a quantity and a cut, not production dates."""
import copy
import datetime as dt
import io

import pytest
from openpyxl import load_workbook

import developaid_contract_gpr_export as export
import developaid_contract_files as files
from tests.test_contract_relative_gpr_calendar import card, change, ROW, PROJECT, CUT


@pytest.mark.parametrize('fraction,start,finish', [
    (.8155644465, '2026-08-01', '2027-02-28'),
    (0, '2026-08-01', '2027-02-28'),
    (1, '2026-08-01', '2027-02-28'),
    (1, '2026-12-01', '2027-02-28'),
    (.4, '2026-01-01', '2026-02-28'),
])
def test_quantities_never_generate_any_past_or_future_production_interval(fraction, start, finish):
    line = {'code': '4.4.1', 'name': 'Учебный физический объём', 'start': start, 'finish': finish}
    overlay = {'fact_fraction': fraction, 'planned_fraction': .5, 'fact_quantity': fraction*100,
               'contract_quantity': 100, 'unit': 'м2', 'lag_days': 4}
    shown = export.presentation({'lines': [line]}, {'4.4.1': overlay}, '2026-11-24')
    row, = shown['rows']
    assert all(bar['state']=='plan' if bar['start']>shown['cut_offset'] else bar['state']=='unknown' for bar in row['bars'])
    assert all(state=='plan' if shown['ticks'][i]['start']>'2026-11-24' else state=='unknown' for i,state in export.cell_states(line,shown['ticks'],overlay,'2026-11-24').items())
    assert row['progress']['fraction'] == fraction
    assert row['progress']['fact_quantity'] == fraction*100
    assert row['progress']['cut'] == '2026-11-24'
    assert row['progress']['production_history_available'] is False
    assert not any(key in row['progress'] for key in ('start', 'finish', 'actual_start', 'actual_finish'))
    assert shown['start'] <= '2026-11-24' and shown['cut_offset'] >= 0


@pytest.mark.parametrize('anchored', [False, True])
def test_relative_source_gaps_remain_plan_only_for_zero_and_complete_quantities(anchored):
    line = {'code': 'R', 'name': 'Относительная работа', 'relative_segments': [
        {'start_day': 1, 'finish_day': 7, 'start_offset': 0, 'end_offset': 7},
        {'start_day': 15, 'finish_day': 21, 'start_offset': 14, 'end_offset': 21}]}
    if anchored:
        line.update(start='2026-11-01', finish='2026-11-21', segments=[
            {'start':'2026-11-01','finish':'2026-11-07'}, {'start':'2026-11-15','finish':'2026-11-21'}])
    schedule = {'calendar_basis':'relative', 'anchor':{'handover_date':'2026-11-01'} if anchored else None,
        'columns':[{'period':1,'start_day':1,'finish_day':21}], 'lines':[line]}
    for fraction in (0, 1):
        overlay = {'fact_fraction':fraction,'planned_fraction':.8,'fact_quantity':fraction*100,
                   'contract_quantity':100,'unit':'м3','lag_days':4}
        shown = export.presentation(schedule, {'R':overlay}, '2026-11-24')
        assert [(bar['start'],bar['end'],bar['state']) for bar in shown['rows'][0]['bars']] == [(0,7,'unknown' if anchored else 'plan'),(14,21,'unknown' if anchored else 'plan')]
        assert shown['rows'][0]['progress']['fraction'] == fraction
        assert (shown['start'] is not None) is anchored


def test_progress_preserves_separate_units_and_has_no_invented_calendar_binding():
    positions = [{'code':str(index),'number':str(index),'name':unit,'quantity':{
        'fact_quantity':actual,'contract_quantity':total,'fraction':actual/total,'unit':unit},'physical':None}
        for index,(actual,total,unit) in enumerate([(4,10,'м2'),(3,5,'м3'),(0,2,'шт')])]
    shown = export.presentation({'lines':[]},{},'2026-11-24',positions)
    assert [(r['progress']['fact_quantity'],r['progress']['unit']) for r in shown['positions']] == [(4,'м2'),(3,'м3'),(0,'шт')]
    assert all(not row['bars'] and row['progress']['planned_fraction'] is None for row in shown['positions'])
    assert all(row['progress']['delta_pp'] is None for row in shown['positions'])
    assert export.physical_progress({'quantity':100},None,'2026-11-24') is None


def test_future_relative_anchor_keeps_real_cut_before_source_day_one():
    schedule = {'calendar_basis':'relative','anchor':{'handover_date':'2026-12-01'},
        'columns':[{'period':1,'start_day':1,'finish_day':7}],
        'lines':[{'code':'R','name':'Будущий план','relative_segments':[
            {'start_day':1,'finish_day':7,'start_offset':0,'end_offset':7}]}]}
    shown = export.presentation(schedule,{},'2026-11-24')
    assert shown['start'] == '2026-11-24' and shown['cut_offset'] == 0
    assert [(bar['start'],bar['end']) for bar in shown['rows'][0]['bars']] == [(7,14)]
    assert all(state == 'plan' for state in export.cell_states(schedule['lines'][0],shown['ticks'],None).values())


def test_excel_quantity_scale_and_dynamic_today_are_outside_calendar_cells(card):
    listed = change(files.listing(PROJECT,ROW['id'],CUT))
    line = {'code':'4.4.1','name':'Учебная работа 81,6%','start':'2026-08-01','finish':'2027-02-28'}
    overlay = {'fact_fraction':.8155644465,'planned_fraction':.5,'fact_quantity':81.55644465,
               'contract_quantity':100,'unit':'м2','lag_days':0}
    listed['gpr'].update(schedule={'lines':[line]},overlays={'4.4.1':overlay})
    listed['rds_comparison'] = {'available':False,'detail':'Учебная РДС не передавалась.'}
    meta = export.bind_snapshot(PROJECT,'2026-11-24',ROW['id'],listed,ROW)
    raw = export.workbook(meta,listed)
    book = load_workbook(io.BytesIO(raw))
    assert book.sheetnames == ['ГПР','Выполнение','Численность подрядчика']
    sheet = book['ГПР'];row = next(row for row in sheet if row[1].value == line['name'])
    assert row[4].value == overlay['fact_fraction'] and row[4].number_format == '0.0%'
    assert not any(cell.fill.fgColor.rgb in {'0070AD47','00E06666'} for cell in row[6:])
    rules = [(str(area.sqref),rule) for area,values in sheet.conditional_formatting._cf_rules.items() for rule in values]
    assert any(area == row[4].coordinate and rule.type == 'dataBar' for area,rule in rules)
    assert all(area.startswith('E') for area,rule in rules if rule.type == 'dataBar')
    assert any(rule.type == 'expression' and 'TODAY()' in ''.join(rule.formula) for _,rule in rules)
    formulas = [cell.value for cells in sheet for cell in cells if cell.data_type == 'f']
    assert len(formulas) == 1 and 'TODAY()' in formulas[0] and 'DATE(2026,11,24)' in formulas[0]
    # The required staffing sheet has its own guarded deviation formulas;
    # absent staffing does not become a zero in their cached values.
    staffing = load_workbook(io.BytesIO(raw),data_only=True)['Численность подрядчика']
    assert all(staffing.cell(5,column).value is None for column in range(2,8))
    assert staffing['H5'].value
    assert any(cell.border.left and cell.border.left.color and cell.border.left.color.rgb == '00111111' for cell in row[6:])
    assert all(cell.border.bottom.style == 'thin' for cell in row[6:])
    assert all(page.freeze_panes is None for page in book)


@pytest.mark.parametrize('zone,instant,today', [
    ('Pacific/Honolulu','2026-11-25T00:30:00+00:00','2026-11-24'),
    ('Pacific/Kiritimati','2026-11-25T00:30:00+00:00','2026-11-25'),
    ('Pacific/Kiritimati','2026-11-25T23:30:00+00:00','2026-11-26'),
])
def test_native_page_today_uses_local_calendar_without_changing_data_cut(card, monkeypatch, zone, instant, today):
    from playwright.sync_api import Browser, expect
    from tests.test_monitor_cumulative_controls import browser_page
    original = Browser.new_page
    monkeypatch.setattr(Browser,'new_page',lambda self,**kwargs:original(self,**{**kwargs,'timezone_id':zone}))
    state = change(files.listing(PROJECT,ROW['id'],CUT))['gpr']
    state['cut'] = '2026-11-24'
    state['presentation'] = export.presentation(state['schedule'],{},state['cut'])
    state['presentation']['statement'] = {'total':100,'work':20,'material':80,'source_dates':['2026-11-18'],
        'current':{'total':100},'after_cut':{'total':0},'undated':{'total':0}}
    with browser_page(390) as (page,responses,errors):
        page.clock.install(time=dt.datetime.fromisoformat(instant))
        responses.data['rows'] = [copy.deepcopy(ROW)]
        page.route('**/monitor/contracts/documents',lambda route:route.fulfill(json={'ok':True,'pending':False,'gpr':state}))
        page.locator('#contractsTab').click()
        page.locator('tr[data-contract-id="'+ROW['id']+'"] .contract-open').click()
        page.evaluate('(value)=>renderContractGpr(value)',state)
        assert page.evaluate('contractGprToday()') == today
        expect(page.locator('.contract-gpr-markers')).to_contain_text('24.11.2026')
        expect(page.locator('.contract-gpr-markers')).to_contain_text('.'.join(reversed(today.split('-'))))
        expect(page.locator('.contract-gpr-statement')).to_contain_text('18.11.2026')
        if today == state['cut']:
            expect(page.locator('.contract-gpr-markers')).to_contain_text('Сегодня и срез')
            assert page.locator('.contract-gpr-date-marker[data-date-kind="today-cut"]').count() > 0
            assert page.locator('.contract-gpr-date-marker[data-date-kind="today"]').count() == 0
        else:
            assert page.locator('.contract-gpr-date-marker[data-date-kind="today"][data-date="'+today+'"]').count() > 0
            assert page.locator('.contract-gpr-date-marker[data-date-kind="cut"][data-date="2026-11-24"]').count() > 0
        assert not page.locator('.contract-gpr-track rect[fill="#70AD47"]').count()
        assert not page.locator('.contract-gpr-track [data-report-state="overdue"]').count()
        assert page.locator('.contract-gpr-track [data-report-state="overdue_unclosed"]').count()>0
        assert not errors


def test_retained_previous_runtime_ticket_is_rejected_without_reimport_or_rescan(card, monkeypatch):
    import main
    import developaid_monitor_contracts as contracts
    from fastapi.testclient import TestClient
    from tests.test_contract_relative_gpr_calendar import KEY, finished
    original_presentation = export.presentation
    current_guard = main.core._monitor_contract_gpr_current
    def previous_presentation(*args, **kwargs):
        result = original_presentation(*args, **kwargs)
        result.pop('schema')
        result['rows'][0]['bars'].append({'start':0,'end':100,'state':'fact'})
        return result
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    monkeypatch.setattr(contracts,'build',lambda *a,**k:{'rows':[copy.deepcopy(ROW)],'cut':CUT})
    client = TestClient(main.app)
    body = {'key':KEY,'session':'synthetic-owner','project':PROJECT,'cut':CUT,'contract_id':ROW['id']}
    # Model an already retained ticket from the previous runtime, which had no
    # semantic gate. Sources stay byte-identical across the runtime transition.
    monkeypatch.setattr(export,'presentation',previous_presentation)
    monkeypatch.setattr(main.core,'_monitor_contract_gpr_current',lambda value:None)
    old = finished(client,client.post('/monitor/contracts/documents',json=body))
    monkeypatch.setattr(export,'presentation',original_presentation)
    monkeypatch.setattr(main.core,'_monitor_contract_gpr_current',current_guard)
    source_bytes = {path.name:path.read_bytes() for path in card[0].glob('*.json')}
    retained = client.post('/monitor/contracts/result',json={'key':KEY,'session':'synthetic-owner','ticket':old['ticket']})
    assert retained.status_code == 409
    assert client.post('/monitor/contracts/gpr.xlsx',json={**body,'ticket':old['ticket'],
        'revision':old['gpr_export']['revision']}).status_code == 409
    fresh = finished(client,client.post('/monitor/contracts/documents',json=body))
    assert fresh['gpr']['presentation']['schema'] == export.PRESENTATION_SCHEMA
    assert all(bar['state'] not in {'fact','lag'} for row in fresh['gpr']['presentation']['rows'] for bar in row['bars'])
    assert {path.name:path.read_bytes() for path in card[0].glob('*.json')} == source_bytes
