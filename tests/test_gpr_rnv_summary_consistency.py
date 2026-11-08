"""The source qualification must reach prebuilt schedule prose as well as cards."""
import datetime as dt

import pytest

import developaid_monitor_dashboard as dashboard
import developaid_monitor_pace as pace
from test_schedule_dependency_timeline import network


@pytest.mark.parametrize('state', ['missing_milestone', 'unknown_calendar', 'no_evidence'])
def test_pace_refreshes_prebuilt_schedule_words_without_touching_financial_words(monkeypatch, state):
    pm = network()
    if state == 'missing_milestone':
        pm['rnv_id'] = ''
    elif state == 'unknown_calendar':
        pm.pop('calendar_confirmed')
    monkeypatch.setattr(pace.schedule_graph, '_load_pm', lambda *_: pm)
    monkeypatch.setattr(pace.corpus_gpr, 'latest', lambda *_: None)
    row = {'id': '1', 'plan_start': '2026-11-01', 'plan_finish': '2026-11-20',
           'rss_accepted_ratio': .25, 'rss_act_cost_rate_3m': .15}
    if state == 'no_evidence':
        row.pop('rss_act_cost_rate_3m')
        row['rss_accepted_ratio'] = None
    view = {'cut': '2026-11-06', 'schedule': {'rows': [row], 'management': []},
            'dashboard': {'schedule': {'approved_finish': '2027-02-01',
                                       'forecast_finish': '2027-02-16', 'rnv_delay_days': 15}}}
    view['dashboard']['summary'] = dashboard._summary(view, {'known': False}, {})
    previous_other = [line for line in view['dashboard']['summary'] if not line.startswith('Срок.')]
    assert any('модель ждёт' in line for line in view['dashboard']['summary'])
    pace._apply_pace('Synthetic', view, dt.date(2026, 11, 6))
    qualified = view['dashboard']['schedule']['qualified_rnv']
    assert qualified['state'] in {'partial', 'unknown'}
    assert not qualified['forecast']
    summary = view['dashboard']['summary']
    assert not any('модель ждёт' in line for line in summary)
    assert [line for line in summary if not line.startswith('Срок.')] == previous_other
    assert sum(line.startswith('Срок.') for line in summary) == 1
    assert dashboard._summary(view, {'known': False}, {}) == summary


def test_complete_qualified_summary_uses_qualified_dates_not_old_prebuilt_dates():
    schedule = {'approved_finish': '2027-02-01', 'forecast_finish': '2027-02-16',
                'qualified_rnv': {'state': 'complete', 'approved': '2027-03-01',
                                  'forecast': '2027-03-04', 'delay_days': 3}}
    text = dashboard._schedule_summary(schedule)
    assert '01.03.2027' in text and '04.03.2027' in text and '3 дней' in text
    assert '16.02.2027' not in text and '01.02.2027' not in text


@pytest.mark.parametrize('state', ['partial', 'unknown'])
def test_report_keeps_stalled_work_risk_when_final_rnv_is_not_known(state):
    import developaid_management_report as report

    block = report.schedule({'schedule': {
        'qualified_rnv': {'state': state, 'approved': '2027-02-01', 'forecast': None,
                          'reasons': ['Учебная цепочка не подтверждена.']},
        'stalled': [{'id': 'A', 'name': '<b>Synthetic risk</b>', 'object': 'Учебный корпус'}]}})
    payload = {'project': 'Synthetic', 'kind': 'week', 'start': '2026-11-01',
               'end': '2026-11-06', 'schedule': block}
    payload['findings'] = report.findings(payload)
    assert any('почти стоят' in item['text'] and '<b>Synthetic risk</b>' in item['text']
               for item in payload['findings'])
    text = report.render_html(payload)
    assert 'почти стоят' in text and '&lt;b&gt;Synthetic risk&lt;/b&gt;' in text
    assert '<b>Synthetic risk</b>' not in text and 'модель ждёт' not in text
