"""КС-6а under the works of the new GPR tab: confirmed, «не подтверждено» and a change of binding."""
import copy

import pytest
from playwright.sync_api import expect

import developaid_cumulative_progress as progress
import developaid_monitor_pace as pace
import developaid_schedule_physical as quantities
import developaid_schedule_physical_review as review
from test_gpr_preview_page import open_preview, plain, show
from test_schedule_physical import item, CUT
from test_schedule_physical_page import state
from test_schedule_physical_review import source_snapshot
from test_schedule_readiness import DAY, PROJECT, activate, site

TASKS = [{'task_id': '2', 'name': 'Synthetic work 2', 'object': 'Корпус 1'},
         {'task_id': '3', 'name': 'Synthetic work 3', 'object': 'Корпус 2'}]
BOUND = {'tasks': [{'task_id': '3', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}],
         'components': [{'task_id': '3', 'component_id': 'Корпус 2', 'item_ids': ['1:0']}], 'note': 'Проверено.'}


def catalog(view, configuration=BOUND):
    """The page's physical state for the view's own GPR, with the real review."""
    rows = [(2026, item(name='Synthetic work 2', position='1')),
            (2026, item(name='Synthetic work 3', position='2', scope='Корпус 2')),
            (2026, item(name='Synthetic work монтаж', position='3', done=20))]
    source, observed = source_snapshot(rows), view['schedule']['physical_progress']
    result = state(tasks=TASKS, configuration=copy.deepcopy(configuration),
                   source_sha256=observed['source_sha256'], snapshot_id=observed['snapshot_id'])
    result['review'] = plain(review.build(quantities._items(source), TASKS, configuration, CUT,
                                          snapshot=source, views=progress.quantity_views(source, CUT)))
    return result


def open_works(page, current, writes):
    def respond(route):
        if route.request.url.endswith('/save'):
            writes.append(route.request.post_data_json)
        route.fulfill(json=current)
    page.route('**/monitor/schedule-gpr-physical/*', respond)
    page.evaluate('loadPhysicalSchedule()')
    page.locator('#ganttExpand').click()


def box(page, task):
    return page.locator(f'#gantt .gb-ks[data-task="{task}"]')


@pytest.mark.parametrize('width', [390, 1440])
def test_positions_under_a_work_are_confirmed_or_marked_unconfirmed(monkeypatch, site, width):
    activate(site)
    value = plain(pace.schedule_view(PROJECT, DAY))
    current, writes = catalog(value), []
    with open_preview(monkeypatch, value, width) as (page, _, errors):
        show(page, value)
        open_works(page, current, writes)
        # Right below its own Gantt row, never inside another work.
        for task in ('2', '3'):
            assert box(page, task).evaluate('e=>e.previousElementSibling.dataset.workId') == task
        expect(box(page, '2').locator('.gb-ks-toggle')).to_have_text('▸ Позиции КС-6а: подтверждено 0, не подтверждено 2')
        expect(box(page, '3').locator('.gb-ks-toggle')).to_have_text('▸ Позиции КС-6а: подтверждено 1, не подтверждено 0')
        box(page, '2').locator('.gb-ks-toggle').click()
        items = box(page, '2').locator('.gb-ks-item')
        expect(items).to_have_count(2)
        expect(items.locator('.gb-ks-tag')).to_have_text(['не подтверждено', 'не подтверждено'])
        expect(items.first).to_contain_text('Synthetic work 2')
        expect(items.first).to_contain_text('Выполнено 50 м² из 100 м² (50%).')
        expect(items.first).to_contain_text('Совпадают корпус и название работ.')
        expect(items.first).to_contain_text('не входит в выполнение работы и в прогноз')
        expect(items.nth(1)).to_contain_text('Проверьте участок и состав работы.')
        box(page, '3').locator('.gb-ks-toggle').click()
        expect(box(page, '3').locator('.gb-ks-tag')).to_have_text(['подтверждено'])
        expect(box(page, '3').get_by_role('button', name='Подтвердить для этой работы')).to_have_count(0)
        # Opening a block is kept over the next redraw of the Gantt.
        page.evaluate('renderGantt(currentView)')
        expect(box(page, '2').locator('.gb-ks-item')).to_have_count(2)
        # The Gantt print hides these lists; the A4 print stays as it was.
        page.evaluate("document.body.classList.add('gpr-print-mode')")
        expect(box(page, '2')).to_be_hidden()
        page.evaluate("document.body.classList.remove('gpr-print-mode')")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not writes and not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_a_candidate_is_confirmed_and_a_confirmed_position_moves_to_another_work(monkeypatch, site, width):
    activate(site)
    value = plain(pace.schedule_view(PROJECT, DAY))
    current, writes = catalog(value), []
    with open_preview(monkeypatch, value, width) as (page, _, errors):
        show(page, value)
        open_works(page, current, writes)
        box(page, '2').locator('.gb-ks-toggle').click()
        first = box(page, '2').locator('.gb-ks-item').first
        first.get_by_role('button', name='Подтвердить для этой работы').click()
        expect(first.locator('.gb-ks-form')).to_contain_text('Полный состав работы нужно будет подтвердить заново')
        first.get_by_role('button', name='Сохранить').click()
        expect(box(page, '2').locator('.gb-ks-msg')).to_have_text('Укажите, кто проверил и на каком основании.')
        assert not writes
        # A different draft in «Данные и настройки» is never overwritten silently.
        page.evaluate("physicalDraft.components.push({task_id:'3',component_id:'Черновик',item_ids:['2:0']})")
        first = box(page, '2').locator('.gb-ks-item').first
        first.locator('.gb-ks-note').fill('Проверил инженер по акту.')
        first.get_by_role('button', name='Сохранить').click()
        expect(box(page, '2').locator('.gb-ks-msg')).to_contain_text('есть несохранённые изменения привязок')
        assert not writes
        page.evaluate("physicalDraft.components.pop()")
        box(page, '2').locator('.gb-ks-item').first.get_by_role('button', name='Сохранить').click()
        expect(box(page, '2').locator('.gb-ks-msg')).to_contain_text('Привязка сохранена')
        sent = writes[-1]
        assert (sent['source_kind'], sent['revision'], sent['snapshot_id']) == ('gpr', 0, current['snapshot_id'])
        assert sent['configuration']['note'] == 'Проверил инженер по акту.'
        group = next(g for g in current['review']['groups'] if g['name'] == 'Synthetic work 2')
        assert [c for c in sent['configuration']['components'] if c['task_id'] == '2'] == [
            {'task_id': '2', 'component_id': group['component_id'], 'item_ids': group['item_ids']}]
        assert {t['task_id']: t['scope_confirmed'] for t in sent['configuration']['tasks']} == {'3': True, '2': False}
        assert quantities._validate(sent['configuration'], max_bindings=quantities.MAX_ROWS)
        # The confirmed position of work 3 goes to work 2; work 3 keeps nothing.
        box(page, '3').locator('.gb-ks-toggle').click()
        moved = box(page, '3').locator('.gb-ks-item')
        moved.get_by_role('button', name='Привязать к другой работе').click()
        moved.locator('.gb-ks-target').select_option('2')
        moved.locator('.gb-ks-note').fill('Позиция относится к корпусу 1 по акту.')
        moved.get_by_role('button', name='Сохранить').click()
        expect(box(page, '2').locator('.gb-ks-msg')).to_contain_text('Привязка сохранена')
        configuration = writes[-1]['configuration']
        assert [(c['task_id'], c['item_ids']) for c in configuration['components']] == [('2', ['1:0'])]
        assert configuration['tasks'] == [{'task_id': '2', 'mode': 'quantities', 'scope_confirmed': False,
                                           'actual_finish': ''}]
        assert quantities._validate(configuration, max_bindings=quantities.MAX_ROWS)
        assert not errors


def test_unbind_keeps_other_works_and_a_foreign_source_shows_nothing(monkeypatch, site):
    activate(site)
    value = plain(pace.schedule_view(PROJECT, DAY))
    current, writes = catalog(value), []
    with open_preview(monkeypatch, value, 390) as (page, _, errors):
        show(page, value)
        open_works(page, current, writes)
        # A new position for a work whose full composition was confirmed withdraws that mark.
        box(page, '2').locator('.gb-ks-toggle').click()
        weak = box(page, '2').locator('.gb-ks-item').nth(1)
        weak.get_by_role('button', name='Привязать к другой работе').click()
        weak.locator('.gb-ks-target').select_option('3')
        weak.locator('.gb-ks-note').fill('Монтаж корпуса 2 по акту.')
        weak.get_by_role('button', name='Сохранить').click()
        expect(box(page, '3').locator('.gb-ks-msg')).to_contain_text('Привязка сохранена')
        configuration = writes[-1]['configuration']
        assert [(c['task_id'], c['item_ids']) for c in configuration['components']] == [('3', ['1:0']), ('3', ['2:0'])]
        assert [(t['task_id'], t['scope_confirmed']) for t in configuration['tasks']] == [('3', False)]
        box(page, '3').locator('.gb-ks-toggle').click()
        position = box(page, '3').locator('.gb-ks-item')
        position.get_by_role('button', name='Отвязать от работы').click()
        position.locator('.gb-ks-note').fill('Ошибочная привязка.')
        position.get_by_role('button', name='Сохранить').click()
        expect(box(page, '3').locator('.gb-ks-msg')).to_contain_text('Позиция отвязана')
        assert writes[-1]['configuration'] == {'tasks': [], 'components': [], 'note': 'Ошибочная привязка.'}
        # Without the right to change, the positions are shown without buttons.
        page.evaluate('s=>renderPhysicalSchedule(s)', dict(current, can_edit=False))
        expect(box(page, '2').locator('.gb-ks-item')).to_have_count(2)
        expect(box(page, '2').locator('button.btn')).to_have_count(0)
        # Positions of another GPR version are not laid under these works.
        other = dict(current, source_sha256='f' * 64)
        page.evaluate('s=>renderPhysicalSchedule(s)', other)
        page.evaluate('renderGantt(currentView)')
        expect(page.locator('#gantt .g-row.lvl-task').first).to_be_attached()
        expect(page.locator('#gantt .gb-ks')).to_have_count(0)
        assert not errors
