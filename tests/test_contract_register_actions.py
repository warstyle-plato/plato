"""Register asks for an action; a partial calculation cannot condemn a contract."""
import copy
import json
import pytest

from developaid_monitor_page import MONITOR_PAGE
from tests import page_blocks


def full_control(state='behind'):
    return {'state': state, 'documents': 2, 'lag_days': 255, 'readiness': 0.969,
        'plan_done': 0.969, 'overdue_days': 129, 'data_gaps': [], 'incomplete': False,
        'coverage': {'source_known': True, 'calculated': 2, 'source_works': 2, 'partial': False},
        'forecast_scope': 'matched_works', 'whole_contract_finish': '2026-03-10',
        'finish': '2026-03-10', 'done': state == 'done'}


def rendered(row):
    return page_blocks.run_json('const row=' + json.dumps(row) + ';const before=JSON.stringify(row);',
        'console.log(JSON.stringify({graph:contractScheduleBrief(row),term:contractTermBrief(row),'
        'attention:contractAttentionBrief(row),unchanged:before===JSON.stringify(row)}));',page=MONITOR_PAGE)


def test_partial_match_displays_a_verification_action_without_technical_counts_or_false_delay():
    s=full_control()
    s.update(incomplete=True, whole_contract_finish=None,
             data_gaps=['Выполнение по 360 позициям не сопоставлено с действующим планом.'])
    s['coverage'].update(calculated=44,source_works=140,partial=True)
    row={'schedule_control':s,'deadline':'2026-03-01','deadline_passed':True,
         'amount':1000,'completed':969,'remaining':31,'source_kind':'closing_summary'}
    result=rendered(row)
    assert 'Сверить с КС-6а' in result['graph']
    for number in ['255','129','44','140','360','96,9']:
        assert number not in result['graph']
    assert 'отста' not in result['graph'] and 'Сверить с КС-6а' not in result['attention']
    assert 'Срок прошёл' in result['attention']
    assert 'Прогноз' not in result['term']
    assert result['unchanged']


def test_physically_complete_work_with_lower_final_sum_has_no_live_delay():
    row={'schedule_control':full_control('done'),'deadline':'2026-03-01','deadline_passed':True,
         'amount':1000,'completed':900,'remaining':100}
    result=rendered(row)
    assert 'Работы завершены' in result['graph']
    assert 'Сверить сумму договора' in result['attention']
    assert '255' not in result['graph'] and 'Проверить срок' not in result['attention']
    assert result['unchanged']


def test_genuinely_incomplete_fully_covered_work_keeps_its_schedule_warning():
    result=rendered({'schedule_control':full_control(),'deadline':'2026-03-01',
                     'deadline_passed':True,'amount':1000,'completed':500,'remaining':500})
    assert 'Есть отставание' in result['graph'] and 'risk-bad' in result['graph']
    assert 'Срок прошёл' in result['attention']
    assert result['unchanged']


@pytest.mark.parametrize('width',[390,1440])
def test_native_register_shows_only_the_verification_action_for_partial_results(width):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT
    with browser_page(width) as (page,responses,errors):
        row=responses.data['rows'][0]
        s=full_control()
        s.update(incomplete=True,whole_contract_finish=None)
        s['coverage'].update(calculated=44,source_works=140,partial=True)
        row['schedule_control']=s
        row.update(deadline='2026-07-11', deadline_passed=True, warnings=[])
        page.locator('#contractsTab').click()
        graph=page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-schedule')
        expect(graph).to_have_text('Сверить с КС-6а')
        line = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(line.locator('.contract-attention')).to_contain_text('Срок прошёл')
        expect(line.locator('.term')).to_contain_text('11.07.2026')
        assert len(graph.inner_text())<30
        assert not errors
