"""All works of one contract and building go to one GPR work in one checked action."""
import copy

import pytest

import developaid_cumulative_progress as progress
import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
from test_schedule_physical import item, CUT
from test_schedule_physical_review import TASKS, source_snapshot
from test_schedule_physical_page import state
from test_monitor_cumulative_controls import browser_page


def bulk_state(configuration=None):
    rows = [(2026, item(name='Монтаж', position='1')), (2026, item(name='Кладка стен', position='2')),
            (2026, item(name='Штукатурка', position='3')), (2026, item(name='Монтаж', position='4', scope='Корпус 2')),
            (2026, item(name='Отделка', position='5', periods=[], completed_quantity=None)),
            (2026, item(name='Кровля', position='6'))]
    configuration = configuration or {'tasks': [{'task_id': '2', 'mode': 'quantities', 'scope_confirmed': True,
                                                  'actual_finish': ''}],
                                      'components': [{'task_id': '2', 'component_id': 'Кровля', 'item_ids': ['5:0']}],
                                      'note': ''}
    source = source_snapshot(rows)
    result = state(tasks=TASKS, configuration=configuration)
    result['review'] = review.build(quantities._items(source), TASKS, configuration, CUT,
                                    snapshot=source, views=progress.quantity_views(source, CUT))
    return result


def open_page(page, current, writes):
    def respond(route):
        if route.request.url.endswith('/save'):
            writes.append(route.request.post_data_json)
        route.fulfill(json=current)
    page.route('**/monitor/schedule-gpr-physical/*', respond)
    page.evaluate('void loadPhysicalSchedule()')
    page.locator('#dataTab').click()


@pytest.mark.parametrize('width', [390, 1440])
def test_whole_building_of_a_contract_binds_to_one_work_after_its_composition_is_shown(width):
    from playwright.sync_api import expect
    current, writes = bulk_state(), []
    with browser_page(width) as (page, responses, errors):
        open_page(page, current, writes)
        card = page.locator('.physical-contract')
        expect(card).to_have_count(1)
        expect(card.locator('.physical-bulk-scope option')).to_have_text(
            ['Выберите корпус или участок', 'Корпус 1 (работ: 5)', 'Корпус 2 (работ: 1)'])
        card.locator('.physical-bulk-scope').select_option('Корпус 1')
        expect(card.get_by_role('button', name='Показать состав')).to_be_disabled()
        card.locator('.physical-bulk-task').select_option('3')
        card.get_by_role('button', name='Показать состав').click()
        listing = card.locator('.physical-bulk-list')
        expect(listing).to_contain_text('войдут работы: 3 из 5. Строк накопительной: 3.')
        expect(card.locator('.physical-bulk-row')).to_have_count(3)
        for name in ('Монтаж', 'Кладка стен', 'Штукатурка'):
            expect(listing).to_contain_text(name + '. План: 100 м². Выполнено: 50 м².')
        expect(card.locator('.physical-bulk-row.warn')).to_have_count(3)
        expect(card.locator('.physical-bulk-skip')).to_have_text([
            'Отделка: Выполненный годовой объём неизвестен или отрицателен.',
            'Кровля: Работа уже привязана к графику.'])
        assert 'Корпус 2' not in listing.inner_text()
        # Another choice drops the shown composition; it has to be shown again.
        card.locator('.physical-bulk-task').select_option('1')
        expect(card.locator('.physical-bulk-list')).to_have_count(0)
        expect(card.locator('.physical-bulk-task option').nth(1)).to_have_attribute('value', '1')
        card.get_by_role('button', name='Показать состав').click()
        expect(card.locator('.physical-bulk-row.warn')).to_have_count(2)
        card.get_by_role('button', name='Привязать работы (3) к «Корпус 1 — Монтаж»').click()
        draft = page.evaluate('physicalDraft')
        added = [c for c in draft['components'] if c['task_id'] == '1']
        assert sorted(c['item_ids'][0] for c in added) == ['0:0', '1:0', '2:0']
        assert all(len(c['item_ids']) == 1 for c in added) and len(draft['components']) == 4
        task, = [t for t in draft['tasks'] if t['task_id'] == '1']
        assert task['mode'] == 'quantities' and task['scope_confirmed'] is False
        assert [t['scope_confirmed'] for t in draft['tasks'] if t['task_id'] == '2'] == [True]
        expect(page.locator('#physicalMsg')).to_contain_text('Проверьте полный состав работ и сохраните')
        expect(card.locator('.physical-bulk-list')).to_have_count(0)
        assert not writes
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


def test_a_composition_changed_after_it_was_shown_is_not_bound():
    from playwright.sync_api import expect
    current, writes = bulk_state(), []
    with browser_page(1440) as (page, responses, errors):
        open_page(page, current, writes)
        card = page.locator('.physical-contract')
        card.locator('.physical-bulk-scope').select_option('Корпус 1')
        card.locator('.physical-bulk-task').select_option('1')
        card.get_by_role('button', name='Показать состав').click()
        page.evaluate("physicalDraft.components.push({task_id:'2',component_id:'Ручная',item_ids:['1:0']})")
        card.get_by_role('button', name='Привязать работы (3) к «Корпус 1 — Монтаж»').click()
        expect(page.locator('#physicalMsg')).to_contain_text('Состав изменился')
        assert page.evaluate("physicalDraft.components.filter(c=>c.task_id==='1').length") == 0
        assert not writes and not errors


def test_a_work_with_another_forecast_basis_is_not_offered_for_binding():
    from playwright.sync_api import expect
    configuration = {'tasks': [{'task_id': '3', 'mode': 'plan_duration', 'scope_confirmed': True,
                                'actual_finish': ''}], 'components': [], 'note': ''}
    current, writes = bulk_state(copy.deepcopy(configuration)), []
    with browser_page(1440) as (page, responses, errors):
        open_page(page, current, writes)
        card = page.locator('.physical-contract')
        card.locator('.physical-bulk-scope').select_option('Корпус 1')
        card.locator('.physical-bulk-task').select_option('3')
        card.get_by_role('button', name='Показать состав').click()
        expect(card).to_contain_text('уже выбрано другое основание прогноза')
        expect(card.get_by_role('button', name='Привязать работы (4) к «Корпус 1 — Строительство сетей»')).to_have_count(0)
        assert not writes and not errors
