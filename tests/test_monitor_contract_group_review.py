"""One source contract is one review packet, while all source works survive."""
import pytest

import developaid_cumulative_progress as progress
import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
from test_schedule_physical import item, CUT
from test_schedule_physical_review import EMPTY, TASKS, source_snapshot
from test_schedule_physical_page import state
from test_monitor_cumulative_controls import browser_page, MARKER


def contract_state(count=360, contracts=3):
    source=source_snapshot([(2026,item(position=str(i+1),system_scope=f'Система {i+1}')) for i in range(count)])
    for i,ledger in enumerate(source['ledgers']):
        ledger['contract']='Д-'+str(i%contracts+1)
    result=state(tasks=TASKS)
    result['review']=review.build(quantities._items(source),TASKS,EMPTY,CUT,
        snapshot=source,views=progress.quantity_views(source,CUT))
    return result


def test_360_source_works_become_three_contract_packets_without_summing_units():
    result=contract_state()['review']
    assert result['contract_count']==3 and result['group_count']==360
    assert sorted(len(p['group_ids']) for p in result['contracts'])==[120,120,120]
    assert len({g['group_id'] for g in result['groups']})==360
    assert all('progress' not in p and 'plan_quantity' not in p for p in result['contracts'])


@pytest.mark.parametrize('field,value',[('contractor','Другой подрядчик'),('customer','Другой заказчик'),
                                       ('contract_date','2025-02-01'),('contract','Д-2')])
def test_equal_contract_numbers_do_not_merge_different_identities(field,value):
    source=source_snapshot([(2026,item(position='1')),(2026,item(position='2'))])
    source['ledgers'][1][field]=value
    result=review.build(quantities._items(source),TASKS,EMPTY,CUT,snapshot=source,
                        views=progress.quantity_views(source,CUT))
    assert result['contract_count']==2


def test_unknown_contract_dates_preserve_source_boundaries_and_known_numbers():
    source=source_snapshot([(2026,item(position='1')),(2026,item(position='2'))])
    for i,ledger in enumerate(source['ledgers']):
        ledger.update(contract_date='',source={'filename':f'{i}.xlsx','sheet':'КС'})
    result=review.build(quantities._items(source),TASKS,EMPTY,CUT,snapshot=source,
                        views=progress.quantity_views(source,CUT))
    assert result['contract_count']==2
    assert all(p['contract']=='Д-1' and not p['date_verified'] for p in result['contracts'])


def test_unknown_customer_never_joins_contracts_from_independent_ledgers():
    source=source_snapshot([(2026,item(position='1')),(2026,item(position='2'))])
    for i,ledger in enumerate(source['ledgers']):
        ledger.update(customer='',source={'filename':f'{i}.xlsx','sheet':'КС'},file_sha256=str(i)*64)
    result=review.build(quantities._items(source),TASKS,EMPTY,CUT,snapshot=source,
                        views=progress.quantity_views(source,CUT))
    assert result['contract_count']==2
    assert all(p['contract']=='Д-1' and not p['identity_complete'] for p in result['contracts'])


@pytest.mark.parametrize('width',[390,1440])
def test_default_contract_screen_is_compact_and_batch_action_keeps_each_work(width):
    from playwright.sync_api import expect
    current=contract_state();writes=[]
    def respond(route):
        if route.request.url.endswith('/save'):writes.append(route.request.post_data_json)
        route.fulfill(json=current)
    with browser_page(width) as (page,responses,errors):
        page.route('**/monitor/schedule-gpr-physical/*',respond)
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        expect(page.locator('#physicalReviewView')).to_have_value('contracts')
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Договоров: 3. Работ внутри: 360.')
        expect(page.locator('.physical-contract')).to_have_count(3)
        expect(page.locator('.physical-group')).to_have_count(0)
        first=page.locator('.physical-contract').first
        first.get_by_role('button',name='Добавить предложения договора (120)',exact=True).click()
        assert page.evaluate('physicalDraft.components.length')==120
        assert page.evaluate('physicalDraft.tasks[0].scope_confirmed') is False
        assert not writes
        first.get_by_role('button',name='Показать работы (120)',exact=True).click()
        expect(page.locator('.physical-group')).to_have_count(25)
        expect(page.locator('.physical-scope-check')).to_be_disabled()
        # All remaining proposals can still be reviewed/added in one action.
        page.locator('#physicalReviewSelect').click()
        page.locator('#physicalReviewApply').click()
        assert page.evaluate('physicalDraft.components.length')==360
        expect(page.locator('.physical-scope-check')).to_have_count(1)
        expect(page.locator('.physical-scope-check')).to_be_enabled()
        page.locator('.physical-scope-check').check()
        assert page.evaluate('physicalDraft.tasks.every(t=>t.scope_confirmed)')
        page.locator('#physicalReviewGroups').evaluate('(e)=>e.scrollTop=0')
        page.locator('#physicalScheduleCard').screenshot(path=f'/tmp/contract-review-{width}.png')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


def test_questions_are_separate_and_do_not_reask_the_known_contract():
    from playwright.sync_api import expect
    current=contract_state(3,1)
    group=current['review']['groups'][0]
    group.update(status='unmatched',base_status='unmatched',suggested_task_id='',candidates=[],name='Спорная работа '+MARKER)
    with browser_page(1440) as (page,responses,errors):
        page.route('**/monitor/schedule-gpr-physical/view',lambda route:route.fulfill(json=current))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        expect(page.locator('.physical-contract')).to_have_count(1)
        page.get_by_role('button',name='Разобрать вопросы (1)',exact=True).click()
        expect(page.locator('#physicalReviewView')).to_have_value('questions')
        expect(page.locator('.physical-group')).to_have_count(1)
        expect(page.locator('.physical-group')).to_contain_text('Договор Д-1')
        expect(page.locator('.physical-group-target')).to_have_value('')
        page.locator('.physical-group-target').select_option('1')
        page.locator('.physical-group-check').check()
        page.locator('#physicalReviewApply').click()
        page.locator('#physicalReviewUnfocus').click()
        expect(page.locator('.physical-contract')).to_have_count(1)
        assert page.locator('#physicalReview img').count()==0
        assert not page.evaluate('window.untrustedRan||false')
        assert not errors


def test_360_gpr_confirmations_are_collected_into_three_explicit_contract_reviews():
    from playwright.sync_api import expect
    current=contract_state()
    current['tasks']=[]
    for i,group in enumerate(current['review']['groups']):
        tid=str(i+1)
        current['tasks'].append(dict(task_id=tid,name=f'Работа {tid}',object='Корпус 1'))
        group['suggested_task_id']=tid
        group['candidates']=[dict(task_id=tid,strong=True,score=2)]
    with browser_page(1440) as (page,responses,errors):
        page.route('**/monitor/schedule-gpr-physical/view',lambda route:route.fulfill(json=current))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewSelect').click()
        page.locator('#physicalReviewApply').click()
        assert page.evaluate('physicalDraft.tasks.length')==360
        expect(page.locator('.physical-scope-check')).to_have_count(3)
        page.locator('.physical-scope-check').first.check()
        assert page.evaluate('physicalDraft.tasks.filter(t=>t.scope_confirmed).length')==120
        assert not errors


def test_history_allows_reading_contract_works_without_enabling_mutations():
    from playwright.sync_api import expect
    current=contract_state(3,1);current['can_edit']=False
    with browser_page(390) as (page,responses,errors):
        page.route('**/monitor/schedule-gpr-physical/view',lambda route:route.fulfill(json=current))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        expect(page.get_by_role('button',name='Добавить предложения договора (3)',exact=True)).to_be_disabled()
        page.get_by_role('button',name='Показать работы (3)',exact=True).click()
        expect(page.locator('.physical-group')).to_have_count(3)
        expect(page.locator('#physicalSave')).to_be_disabled()
        expect(page.locator('.physical-group-check').first).to_be_disabled()
        assert page.evaluate('physicalDraft.components.length')==0
        assert not errors
