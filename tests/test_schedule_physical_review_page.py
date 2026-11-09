"""Real Monitor page: batch proposals remain drafts until explicit scope/save."""
import copy

import pytest

import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
from test_monitor_cumulative_controls import browser_page, MARKER
from test_schedule_physical_page import state
from test_schedule_physical import item, snapshot, CUT


def review_state(count=30, **changes):
    rows = [(2026, item(name=f'Монтаж {i+1} этажа')) for i in range(count)]
    rows += [(2026, item(name='Непривязанные сети '+MARKER))]
    tasks = [dict(task_id='1', name='Монтаж', object='Корпус 1'),
             dict(task_id='2', name='Монтаж', object='Корпус 11')]
    result = state(tasks=tasks, **changes)
    result['review'] = review.build(quantities._items(snapshot(rows)), tasks, result['configuration'], CUT)
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
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Строк в архиве: 31. Групп объёмов: 31.')
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
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Привязано в текущем составе: 30.')
        page.locator('#physicalScheduleCard').screenshot(path=f'/tmp/volume-review-{width}.png')
        assert not errors


def test_filters_manual_choice_and_new_component_revoke_scope_confirmation():
    from playwright.sync_api import expect
    with browser_page(1440) as (page, responses, errors):
        page.route('**/monitor/schedule-gpr-physical/view', lambda route: route.fulfill(json=review_state(2)))
        page.evaluate('void loadPhysicalSchedule()')
        page.locator('#dataTab').click()
        page.locator('#physicalReviewSearch').fill('1 этажа')
        expect(page.locator('.physical-group')).to_have_count(1)
        page.locator('.physical-group-check').check()
        page.locator('#physicalReviewApply').click()
        page.locator('.physical-scope-check').check()
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
        expect(page.locator('#physicalReviewSummary')).to_contain_text('Строк в архиве: 1191.')
        page.locator('#physicalReviewSelect').click()
        expect(page.locator('#physicalReviewSelection')).to_contain_text('Выбрано групп: 1190.')
        page.locator('#physicalReviewApply').click()
        expect(page.locator('#physicalReviewScopes')).to_contain_text('Добавлено групп объёмов: 1190.')
        assert page.evaluate('physicalDraft.tasks[0].scope_confirmed') is False
        assert not errors
