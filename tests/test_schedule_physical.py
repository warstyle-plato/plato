"""Natural units, annual identity and dated periods govern physical forecasting."""
import copy
import datetime as dt
import json

import pytest

import developaid_schedule_physical as physical
import developaid_schedule_timeline as timeline
from test_schedule_dependency_timeline import network, day

CUT = '2026-11-06'


def item(year=2026, done=50, **changes):
    result = dict(name='Монтаж', scope='Корпус 1', unit='м²', plan_quantity=100,
                  completed_quantity=done, quantity_kind='installation', material_quantity=10000,
                  periods=[dict(date_start=f'{year}-10-01', date_end=f'{year}-10-31', quantity=done)],
                  source={'filename': 'synthetic.xlsx', 'sheet': 'КС', 'row': 8})
    result.update(changes)
    return result


def snapshot(rows=None):
    rows = rows or [(2026, item())]
    return {'snapshot_id': CUT+'-'+'b'*64, 'ledgers': [
        {'period_year': year, 'contractor': 'Учебный подрядчик', 'contract': 'Д-1',
         'contract_date': '2025-01-01', 'items': [row]} for year, row in rows]}


def config(item_ids=None):
    return {'tasks': [dict(task_id='1', mode='quantities', scope_confirmed=True, actual_finish='')]
            + [dict(task_id=t, mode='plan_duration', scope_confirmed=True, actual_finish='') for t in ['2', '3', '4']],
            'components': [dict(component_id='Корпус 1 — монтаж', task_id='1', item_ids=item_ids or ['0:0'])],
            'note': 'Проверены полный объём и участок; прочие этапы не имеют натуральных объёмов.'}


def test_calendar_day_pace_uses_quantities_and_shared_dependency_timeline():
    pm = network()
    got = physical.evaluate(pm, snapshot(), config(), CUT)
    assert got['state'] == 'complete'
    row = got['tasks'][0]
    assert row['progress'] == .5
    assert row['forecast_finish'] == '2026-12-07'
    c = row['components'][0]
    assert c['rate_per_day'] == pytest.approx(50/31)
    assert c['rate_window_start'] == '2026-10-01'
    result = timeline.model(pm, {k: day(v) for k,v in got['seeds'].items()}, evidence=True)
    assert result['rnv']['state'] == 'complete'
    assert result['rnv']['delay_days'] == 12
    changed = snapshot()
    changed['ledgers'][0]['items'][0].update(material_quantity=1e15, completed_amount=1e20)
    assert physical.evaluate(pm, changed, config(), CUT) == got


def test_annual_rows_count_plan_once_and_periods_once():
    old = item(2025, 10)
    old['periods'] = [dict(date_start='2025-12-01', date_end='2025-12-31', quantity=10)]
    got = physical.evaluate(network(), snapshot([(2025,old),(2026,item())]), config(['0:0','1:0']), CUT)
    c = got['tasks'][0]['components'][0]
    assert c['completed_quantity'] == 60 and c['plan_quantity'] == 100
    assert c['progress'] == .6 and c['rate_per_day'] == pytest.approx(50/31)
    assert c['forecast_finish'] == '2026-12-01'


@pytest.mark.parametrize('change', [
    dict(completed_quantity=None), dict(completed_quantity=60), dict(completed_quantity=-1),
    dict(plan_quantity=None), dict(plan_quantity=True), dict(plan_quantity=0),
    dict(plan_quantity=float('nan')), dict(completed_quantity=200),
    dict(periods=[dict(date_start=None,date_end=None,quantity=50)]),
    dict(periods=[dict(date_start='2026-10-01',date_end='2026-10-31',quantity=None)]),
    dict(periods=[dict(date_start='2026-10-01',date_end='2026-10-31',quantity=-1)]),
    dict(periods=[dict(date_start='2026-10-01',date_end='2026-10-31',quantity=25),
                  dict(date_start='2026-10-15',date_end='2026-10-31',quantity=25)]),
    dict(periods=[dict(date_start='2025-10-01',date_end='2025-10-31',quantity=50)]),
])
def test_unknown_or_inconsistent_evidence_cannot_certify_rnv(change):
    got = physical.evaluate(network(), snapshot([(2026,item(**change))]), config(), CUT)
    assert got['state'] == 'unknown' and not got['seeds']
    assert got['tasks'][0]['components'][0]['reason']


def test_future_positive_volume_and_empty_future_column_are_distinct():
    row=item()
    row['periods'].append(dict(date_start='2026-11-01',date_end='2026-11-30',quantity=20))
    row['completed_quantity']=70
    assert physical.evaluate(network(),snapshot([(2026,row)]),config(),CUT)['state']=='unknown'
    for value in [None,0]:
        row['periods'][-1]['quantity']=value;row['completed_quantity']=50
        assert physical.evaluate(network(),snapshot([(2026,row)]),config(),CUT)['state']=='complete'


@pytest.mark.parametrize('second', [item(unit='100 м²'), item(plan_quantity=200)])
def test_cross_year_units_and_full_plan_must_match(second):
    got=physical.evaluate(network(),snapshot([(2025,item(2025)),(2026,second)]),config(['0:0','1:0']),CUT)
    assert got['state']=='unknown'


def test_duplicate_annual_row_is_not_extra_production():
    got=physical.evaluate(network(),snapshot([(2026,item()),(2026,item())]),config(['0:0','1:0']),CUT)
    assert got['state']=='unknown'


def test_zero_or_stale_pace_does_not_use_cost_progress():
    for row in [item(done=0), item(periods=[dict(date_start='2026-06-01',date_end='2026-06-30',quantity=50)])]:
        got=physical.evaluate(network(),snapshot([(2026,row)]),config(),CUT)
        assert got['state']=='unknown' and not got['seeds']
        assert got['tasks'][0]['components'][0]['progress'] is not None


def test_a_recently_ended_annual_period_is_not_a_recent_ninety_day_pace():
    row=item(periods=[dict(date_start='2026-01-01',date_end='2026-10-31',quantity=50)])
    got=physical.evaluate(network(),snapshot([(2026,row)]),config(),CUT)
    component=got['tasks'][0]['components'][0]
    assert component['progress']==.5 and component['rate_per_day'] is None
    assert got['state']=='unknown' and '90 дней' in component['reason']


def test_complete_quantity_is_actual_finish_not_another_pace_extrapolation():
    got=physical.evaluate(network(),snapshot([(2026,item(done=100))]),config(),CUT)
    assert got['tasks'][0]['forecast_finish']=='2026-10-31'
    assert got['tasks'][0]['components'][0]['method']=='completed_quantities'


def test_mixed_components_never_become_one_meaningless_percent():
    cfg=config();cfg['components'].append(dict(component_id='Корпус 1 — бетон',task_id='1',item_ids=['1:0']))
    got=physical.evaluate(network(),snapshot([(2026,item()),(2026,item(unit='м³',plan_quantity=200,completed_quantity=100,
                 periods=[dict(date_start='2026-10-01',date_end='2026-10-31',quantity=100)]))]),cfg,CUT)
    assert got['state']=='complete' and got['tasks'][0]['progress'] is None
    assert len(got['tasks'][0]['components'])==2


def test_missing_task_coverage_or_confirmations_stays_partial():
    for kind in ['missing','unconfirmed']:
        cfg=config()
        if kind=='missing':cfg['tasks']=cfg['tasks'][:-1]
        else:cfg['tasks'][1]['scope_confirmed']=False
        got=physical.evaluate(network(),snapshot(),cfg,CUT)
        assert got['state']=='partial' and got['reasons']


def test_confirmed_historical_completion_requires_actual_date():
    pm=network();pm['tasks']['2']['finish']=day('2026-10-31');pm['tasks']['2']['predecessors']=[]
    got=physical.evaluate(pm,snapshot(),config(),CUT)
    assert got['state']=='unknown'
    cfg=config();cfg['tasks'][1].update(mode='completed',actual_finish='2026-10-31')
    got=physical.evaluate(pm,snapshot(),cfg,CUT)
    assert got['state']=='complete' and got['tasks'][1]['progress']==1


def test_unrelated_physical_work_does_not_certify_the_rnv_chain():
    pm=network();pm['tasks']['2']['predecessors']=[]
    got=physical.evaluate(pm,snapshot(),config(),CUT)
    assert not got['physical_evidence'] and got['state']=='unknown'


def test_confirmed_plan_duration_can_shift_from_an_overdue_predecessor():
    pm=network();pm['tasks']['2']['start']=day('2026-10-26');pm['tasks']['2']['finish']=day('2026-10-31')
    pm['tasks']['2']['duration_days']=5
    got=physical.evaluate(pm,snapshot(),config(),CUT)
    assert got['state']=='complete' and got['tasks'][1]['known']


def test_render_escapes_component_work_names_and_reasons():
    cfg=config();cfg['components'][0]['component_id']='<img src=x onerror=alert(1)>'
    got=physical.evaluate(network(),snapshot(),cfg,CUT)
    body=physical.render(got)
    assert '<img' not in body and '&lt;img' in body
    assert '50 / 100 м²' in body


@pytest.mark.parametrize('change', [
    {'components':[dict(component_id='x',task_id='1',item_ids=['0:0','0:0'])]},
    {'components':[dict(component_id='x',task_id='1',item_ids=['../../secret'])]},
    {'note':''}, {'tasks':[dict(task_id='1',mode='quantities',scope_confirmed='true',actual_finish='')]},
])
def test_invalid_configuration_is_rejected(change):
    cfg=config();cfg.update(change)
    with pytest.raises(physical.PhysicalProblem):physical._validate(cfg)


def test_physical_rnv_and_summary_do_not_inherit_cost_pace_seeds(monkeypatch):
    import developaid_monitor_pace as pace
    pm=network()
    model=physical.evaluate(pm,snapshot(),config(),CUT)
    monkeypatch.setattr(pace.schedule_graph,'_load_pm',lambda *_:pm)
    monkeypatch.setattr(pace.schedule_confirmation,'qualify',lambda project,source,cut:source)
    monkeypatch.setattr(pace.schedule_physical,'build',lambda *a:model)
    monkeypatch.setattr(pace.corpus_gpr,'latest',lambda *a:None)
    for cost_rate in [.001,.9]:
        view={'schedule':{'rows':[dict(id='1',plan_start='2026-11-01',plan_finish='2026-11-20',
                                      rss_accepted_ratio=.1,rss_act_cost_rate_3m=cost_rate)],'management':[]},
              'dashboard':{'schedule':{},'summary':['Финансы. Не меняются.']}}
        pace._apply_pace('Synthetic',view,day(CUT))
        q=view['schedule']['dependency_timeline']['rnv']
        assert q['state']=='complete' and q['forecast']=='2027-02-13'
        assert view['dashboard']['schedule']['forecast_finish']=='2027-02-13'
        assert 'Финансы. Не меняются.' in view['dashboard']['summary']


def test_manual_completion_is_not_painted_as_a_quantity_percentage():
    pm=network();model=physical.evaluate(pm,snapshot(),config(),CUT)
    model['tasks'][1].update(mode='completed',progress=1.0)
    block=timeline.model(pm,{k:day(v) for k,v in model['seeds'].items()},evidence=True)
    block['physical']=model
    text=timeline.render(block)
    assert text.count('Подтверждённый натуральный объём:')==1
    assert 'Подтверждённый натуральный объём: 50.0%' in text
