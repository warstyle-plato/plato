"""Real Monitor page: batch proposals remain drafts until explicit scope/save."""
import copy

import pytest

import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
import developaid_cumulative_progress as progress
from test_schedule_physical_review import source_snapshot
from test_monitor_cumulative_controls import browser_page, MARKER
from test_schedule_physical_page import state
from test_schedule_physical import item, snapshot, CUT


def review_state(count=30, **changes):
    # Large catalog coverage does not require fictitious four-digit floors;
    # each explicitly named system/position is an independent source work.
    rows = ([(2026, item(position=str(i+1), system_scope=f'Система {i+1}')) for i in range(count)]
            if count > 99 else [(2026, item(name=f'Монтаж {i+1} этажа')) for i in range(count)])
    rows += [(2026, item(name='Непривязанные сети '+MARKER))]
    tasks = [dict(task_id='1', name='Монтаж', object='Корпус 1'),
             dict(task_id='2', name='Монтаж', object='Корпус 11')]
    result = state(tasks=tasks, **changes)
    source = source_snapshot(rows)
    result['review'] = review.build(quantities._items(source), tasks, result['configuration'], CUT,
                                   snapshot=source, views=progress.quantity_views(source, CUT))
    return result


@pytest.mark.parametrize('width', [390, 1440])
def test_batch_proposals_across_pages_scope_and_save_are_separate_actions(width):
    from playwright.sync_api import expect
    current = review_state();writes = []
    def respond(route):
        nonlocal current
        body = route.request.post_data_json
        if route.request.url.endswith('/save'):
            writes.append(copy.deepcopy(body))
            current = review_state(configuration=body['configuration'], revision=1,
                                   recorded_at='2026-11-06T12:00:00+00:00')
        route.fulfill(json=current)
    with browser_page(width) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/*', respond)
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Договоров: 1. Работ внутри: 31.')
        assert page.locator('.physical-group').count() == 25
        page.locator('#physicalReviewSelect').click()
        expect(page.locator('#physicalReviewSelection')).to_contain_text('Выбрано групп: 30.')
        page.locator('#physicalReviewNext').click()
        assert page.locator('.physical-group-check:checked').count() == 5
        page.locator('#physicalReviewApply').click()
        assert not writes
        assert page.evaluate('physicalDraft.components.length') == 30
        assert page.evaluate('physicalDraft.tasks[0].scope_confirmed') is False
        assert page.evaluate('physicalDraft.tasks[0].task_id') == '1'
        expect(page.locator('#physicalReviewScopes')).to_contain_text('Добавлено групп объёмов: 30.')
        page.locator('.physical-scope-check').check()
        page.locator('#physicalNote').fill('Анна проверила договор, корпус и полный состав работы.')
        page.locator('#physicalSave').click()
        expect(page.locator('#physicalScheduleState')).to_contain_text('Последняя привязка')
        assert len(writes) == 1 and writes[0]['configuration']['tasks'][0]['scope_confirmed']
        assert len(writes[0]['configuration']['components']) == 30
        assert page.locator('#physicalReview img').count() == 0
        assert not page.evaluate('window.untrustedRan||false')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#physicalReviewFilter').select_option('bound')
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Привязано работ: 30.')
        page.locator('#physicalScheduleCard').screenshot(path=f'/tmp/volume-review-{width}.png')
        assert not errors


def test_filters_manual_choice_and_new_component_revoke_scope_confirmation():
    from playwright.sync_api import expect
    with browser_page(1440) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/view', lambda route: route.fulfill(json=review_state(2)))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        page.locator('#physicalReviewSearch').fill('1 этажа')
        expect(page.locator('.physical-group')).to_have_count(1)
        page.locator('.physical-group-check').check()
        page.locator('#physicalReviewApply').click()
        expect(page.locator('.physical-scope-check')).to_be_disabled()
        page.locator('#physicalManual summary').click()
        page.locator('#physicalScope').check()
        page.locator('#physicalApplyTask').click()
        page.locator('#physicalReviewSearch').fill('2 этажа')
        page.locator('.physical-group-check').check()
        page.locator('#physicalReviewApply').click()
        expect(page.locator('.physical-scope-check')).not_to_be_checked()
        page.locator('#physicalReviewSearch').fill('')
        page.locator('#physicalReviewFilter').select_option('unmatched')
        expect(page.locator('.physical-group')).to_have_count(1)
        page.locator('.physical-group-target').select_option('1')
        page.locator('.physical-group-check').check()
        page.locator('#physicalReviewApply').click()
        assert page.evaluate('physicalDraft.components.length') == 3
        page.locator('#physicalReviewFilter').select_option('bound')
        page.locator('#physicalReviewSearch').fill('Непривязанные сети')
        expect(page.locator('.physical-group')).to_contain_text('Привязана к работе: Корпус 1 — Монтаж (ID 1).')
        assert not errors


def test_source_conflict_disables_group_mutations_and_logout_clears_private_review():
    from playwright.sync_api import expect
    with browser_page(390) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/view', lambda route: route.fulfill(json=review_state(1)))
        page.route('**/monitor/schedule-gpr-physical/save', lambda route: route.fulfill(status=409,json={'detail':'Данные изменились.'}))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        page.locator('#physicalReviewSelect').click()
        page.locator('#physicalReviewApply').click()
        page.locator('#physicalNote').fill('Проверены исходные данные.')
        page.locator('#physicalSave').click()
        expect(page.locator('#physicalMsg')).to_contain_text('Перечитать')
        expect(page.locator('#physicalReviewApply')).to_be_disabled()
        expect(page.locator('#physicalReviewSelect')).to_be_disabled()
        page.evaluate('clearPhysicalSchedule()')
        expect(page.locator('#physicalReviewGroups')).to_be_empty()
        expect(page.locator('#physicalReviewScopes')).to_be_empty()
        assert not errors


def test_1190_proposals_can_be_added_in_one_draft_action():
    from playwright.sync_api import expect
    with browser_page(1440) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/view', lambda route: route.fulfill(json=review_state(1190)))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Строк в архиве: 1191.')
        page.locator('#physicalReviewSelect').click()
        expect(page.locator('#physicalReviewSelection')).to_contain_text('Выбрано групп: 1190.')
        page.locator('#physicalReviewApply').click()
        expect(page.locator('#physicalReviewScopes')).to_contain_text('Добавлено групп объёмов: 1190.')
        assert page.evaluate('physicalDraft.tasks[0].scope_confirmed') is False
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_system_context_and_conflicting_plan_source_percentages_survive_review(width):
    from playwright.sync_api import expect
    source = source_snapshot([(2025, item(2025, 50, system_scope='Отопление')),
                              (2026, item(system_scope='Холодоснабжение')),
                              (2025, item(2025, 50, name='Монтаж стен')),
                              (2026, item(name='Монтаж стен', plan_quantity=200))])
    tasks = [dict(task_id='1', name='Монтаж', object='Корпус 1')]
    current = state(tasks=tasks)
    current['review'] = review.build(quantities._items(source), tasks, current['configuration'], CUT,
                                    snapshot=source, views=progress.quantity_views(source, CUT))
    with browser_page(width) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/view', lambda route: route.fulfill(json=current))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        page.locator('#physicalReviewFilter').select_option('all')
        expect(page.locator('.physical-group')).to_have_count(3)
        expect(page.locator('.physical-group').filter(has_text='Отопление')).to_have_count(1)
        expect(page.locator('.physical-group').filter(has_text='Холодоснабжение')).to_have_count(1)
        conflict = page.locator('.physical-group').filter(has_text='Монтаж стен')
        expect(conflict.locator('.physical-group-check')).to_be_disabled()
        conflict.get_by_role('button', name='Показать исходные строки').click()
        expect(conflict.locator('.source-row').nth(0)).to_contain_text('50%')
        expect(conflict.locator('.source-row').nth(1)).to_contain_text('25%')
        page.locator('#physicalReviewSelect').click()
        page.locator('#physicalReviewApply').click()
        assert page.evaluate('physicalDraft.components.length') == 2
        expect(page.locator('.physical-scope-check')).to_be_disabled()
        page.locator('#physicalManual summary').click()
        page.locator('#physicalScope').check()
        page.locator('#physicalApplyTask').click()
        page.get_by_role('button', name='Убрать компонент', exact=True).first.click()
        expect(page.locator('.physical-scope-check')).not_to_be_checked()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


def test_changed_draft_does_not_claim_the_saved_automatic_source_proof():
    from playwright.sync_api import expect
    current = review_state(2)
    first = current['review']['groups'][0]
    current['configuration'] = {'tasks': [{'task_id': '1', 'mode': 'quantities', 'scope_confirmed': True,
                                          'actual_finish': ''}],
        'components': [{'task_id': '1', 'component_id': first['component_id'], 'item_ids': first['item_ids']}],
        'note': 'Сохранён точный участок.'}
    current['model']['automatic_bindings'] = {'1': {'basis': 'closed_operation_and_exact_scope'}}
    with browser_page(1440) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/view', lambda route: route.fulfill(json=current))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        page.locator('#physicalManual summary').click()
        expect(page.locator('#physicalBindings')).to_contain_text('по точному участку КС')
        page.locator('#physicalReviewSelect').click()
        page.locator('#physicalReviewApply').click()
        expect(page.locator('#physicalBindings')).not_to_contain_text('по точному участку КС')
        expect(page.locator('.physical-scope-check')).not_to_be_checked()
        page.locator('.physical-scope-check').check()
        expect(page.locator('#physicalBindings')).not_to_contain_text('по точному участку КС')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('second_unit', ['шт', 'м²', None])
def test_original_rows_show_their_own_units_in_conflicting_and_normal_groups(width, second_unit):
    from playwright.sync_api import expect
    source = source_snapshot([(2025, item(2025, 50)), (2026, item(unit=second_unit))])
    tasks = [dict(task_id='1', name='Монтаж', object='Корпус 1')]
    current = state(tasks=tasks)
    current['review'] = review.build(quantities._items(source), tasks, current['configuration'], CUT,
                                    snapshot=source, views=progress.quantity_views(source, CUT))
    group, = current['review']['groups']
    assert [row['unit'] for row in group['rows']] == ['м²', second_unit]
    assert group['can_bind'] is (second_unit == 'м²')
    if second_unit != 'м²':
        assert group['progress'] is None
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(s)=>renderPhysicalSchedule(s)', current)
        page.locator('#dataTab').click()
        page.locator('#physicalReviewView').select_option('works')
        card = page.locator('#physicalReviewGroups .physical-group')
        expect(card).to_have_count(1)
        if second_unit != 'м²':
            expect(card).to_contain_text('разные или неизвестные единицы')
            expect(card.locator('.physical-group-check')).to_be_disabled()
        card.get_by_role('button', name='Показать исходные строки').click()
        rows = card.locator('.source-row')
        expect(rows.nth(0)).to_contain_text('План: 100 м². Годовой итог: 50 м².')
        if second_unit:
            expect(rows.nth(1)).to_contain_text(f'План: 100 {second_unit}. Годовой итог: 50 {second_unit}.')
        else:
            expect(rows.nth(1)).to_contain_text('План: 100. Годовой итог: 50.')
            expect(rows.nth(1)).not_to_contain_text('м²')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
