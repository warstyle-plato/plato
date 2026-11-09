"""The actual page can start from a GPR and cumulative archive, with explicit links."""
import copy
from urllib.parse import urlparse

from test_monitor_cumulative_controls import browser_page, KEY
from test_monitor_management_gantt import _gpr_book
from test_monitor_cumulative_ledgers import archive, book
from test_schedule_physical_page import state


def test_upload_gpr_without_finance_then_archive_and_explicitly_confirm_quantities():
    from playwright.sync_api import expect
    saved = {'gpr': False, 'configuration': {'tasks': [], 'components': [], 'note': ''}, 'revision': 0}
    writes, schedules = [], []
    with browser_page() as (page, responses, errors):
        def catalog():
            ready = saved['gpr'] and responses.uploaded
            return state(source_sha256='a'*64 if saved['gpr'] else None,
                         snapshot_id='2026-11-08-'+'b'*64 if responses.uploaded else None,
                         can_edit=ready, items=state()['items'] if ready else [],
                         item_count=1 if ready else 0,
                         configuration=copy.deepcopy(saved['configuration']), revision=saved['revision'],
                         recorded_at='2026-11-08T12:00:00+00:00' if saved['revision'] else None)

        def respond(route):
            payload = route.request.post_data_json
            assert payload['key'] == KEY
            path = urlparse(route.request.url).path
            if path == '/monitor/schedule':
                schedules.append(payload)
                saved['gpr'] = True
                return route.fulfill(json={'ok': True})
            if path.endswith('/save'):
                writes.append(payload)
                saved['configuration'] = payload['configuration']
                saved['revision'] += 1
            return route.fulfill(json=catalog())

        page.route('**/monitor/daily/summary**', lambda route: route.fulfill(json={'available': False}))
        page.route('**/monitor/schedule', respond)
        page.route('**/monitor/schedule-gpr-physical/*', respond)
        page.route('**/monitor/view', lambda route: route.fulfill(json={
            'cut': '2026-11-08', 'schedule': {'management': [], 'physical_progress': {
                'source_kind': 'gpr', 'source_sha256': catalog()['source_sha256'],
                'snapshot_id': catalog()['snapshot_id']}}, 'dashboard': {}}))
        page.locator('#dataTab').click()
        page.locator('#gpr').set_input_files({'name': 'ГПР.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'buffer': _gpr_book([('1', 'Монтаж', .5, '2026-10-01', '2026-12-01', 'В работе', '2.2')])})
        assert page.locator('#finance').evaluate('(e)=>e.files.length') == 0
        page.locator('#baselineBtn').click()
        expect(page.locator('#baselineMsg')).to_contain_text('Утверждённый план сохранён')
        assert len(schedules) == 1 and 'pm_base64' not in schedules[0]
        assert schedules[0]['gpr_base64']
        expect(page.locator('#physicalSave')).to_be_disabled()
        page.locator('#cumulativeFile').set_input_files({'name': 'Накопительные.zip', 'mimeType': 'application/zip',
            'buffer': archive([('Ведомость.xlsx', book())])})
        page.locator('#cumulativeUpload').click()
        expect(page.locator('#cumulativeMsg')).to_contain_text('Архив обработан')
        expect(page.locator('#physicalSave')).to_be_enabled()
        assert not writes  # loading sources never confirms a match
        page.locator('#physicalScheduleCard summary').click()
        page.locator('#physicalScope').check()
        page.locator('#physicalApplyTask').click()
        page.locator('#physicalItems').select_option(['0:0'])
        page.locator('#physicalComponent').fill('Монтаж корпуса 1')
        page.locator('#physicalAddComponent').click()
        assert not writes  # the draft isn't a saved acceptance
        # Changing the component set requires a fresh, explicit scope check.
        expect(page.locator('#physicalScope')).not_to_be_checked()
        page.locator('#physicalScope').check()
        page.locator('#physicalApplyTask').click()
        page.locator('#physicalNote').fill('Проверен полный объём монтажа корпуса 1 по ведомости.')
        page.locator('#physicalSave').click()
        expect(page.locator('#physicalScheduleState')).to_contain_text('Последняя привязка сохранена')
        assert len(writes) == 1
        assert writes[0]['source_kind'] == 'gpr' and writes[0]['source_sha256'] == 'a'*64
        assert 'pm_sha256' not in writes[0]
        assert writes[0]['configuration']['tasks'][0]['scope_confirmed'] is True
        assert writes[0]['configuration']['components'][0]['item_ids'] == ['0:0']
        assert not any(path.startswith('/monitor/schedule-physical') for path, *_ in responses.calls)
        assert not errors


def test_old_pm_catalog_cannot_restore_links_in_the_gpr_mapping_form():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        page.locator('#dataTab').click()
        legacy = state()
        legacy.pop('source_kind')
        legacy['pm_sha256'] = legacy.pop('source_sha256')
        page.evaluate('(s)=>{++physicalRequest;renderPhysicalSchedule(s)}', legacy)
        expect(page.locator('#physicalScheduleCard')).to_be_hidden()
        assert page.locator('#physicalItems option').count() == 0
        assert not errors


def test_changed_gpr_drops_unsaved_bindings_and_requires_new_explicit_confirmation():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        page.evaluate('(s)=>{++physicalRequest;renderPhysicalSchedule(s)}', state())
        page.locator('#dataTab').click()
        page.locator('#physicalScheduleCard summary').click()
        page.locator('#physicalScope').check()
        page.locator('#physicalApplyTask').click()
        expect(page.locator('#physicalBindings')).to_contain_text('состав подтверждён')
        page.evaluate('(s)=>renderPhysicalSchedule(s,true)', state(source_sha256='c'*64, source_changed=True))
        expect(page.locator('#physicalBindings')).to_be_empty()
        expect(page.locator('#physicalScope')).not_to_be_checked()
        expect(page.locator('#physicalScheduleState')).to_contain_text('Исходные файлы изменились')
        assert not any(path.endswith('/schedule-gpr-physical/save') for path, *_ in responses.calls)
        assert not errors


def test_gpr_only_money_is_unknown_and_a_known_zero_remains_zero():
    from playwright.sync_api import expect
    from test_monitor_gpr_sections import monitor_view, render
    with browser_page() as (page, responses, errors):
        view = monitor_view()
        view['money'] = {'known': False, 'payment_fact': None, 'reason': 'Выгрузка РСС ещё не загружена.'}
        view['dashboard'].update(physical={'accepted': None}, construction={'approved': None, 'contracted': None},
                                 funding={'known': False, 'paid_actual': None})
        render(page, view)
        expect(page.locator('#ganttCard')).to_be_visible()
        page.locator('#moneyTab').click()
        expect(page.locator('#financeBars')).to_have_text('Выгрузка РСС ещё не загружена.')
        assert page.locator('#fundingCompare b').all_text_contents() == ['—', '—', '—']
        assert '0 млн' not in page.locator('#financeCard').inner_text()
        assert page.locator('#kpis .kpi').evaluate_all('(xs)=>xs.every(x=>{const r=x.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})')
        expect(page.locator('#kpis')).to_contain_text('Оценка по ГПР')
        expect(page.locator('#moneyChart')).to_be_empty()
        page.screenshot(path='/tmp/plato1041-no-rss-money-390.png', full_page=True)
        view['money'] = {'known': True, 'payment_fact': 0}
        view['dashboard'].update(physical={'accepted': 0}, construction={'approved': None, 'contracted': 0},
                                 funding={'known': True, 'paid_actual': 0})
        render(page, view)
        assert page.locator('#fundingCompare b').all_text_contents() == ['0 млн ₽', '0 млн ₽', '0 млн ₽']
        assert not errors


def test_unapproved_corpus_source_names_the_missing_approval_instead_of_an_empty_form():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        reason = 'Подтвердите состав и соответствие пакетов и корпусов работам утверждённого ГПР.'
        catalog = state(can_edit=False, tasks=[], items=[], item_count=0,
                        source_state='unapproved_corpus', source_reason=reason)
        page.evaluate('(s)=>{++physicalRequest;renderPhysicalSchedule(s)}', catalog)
        page.locator('#dataTab').click()
        expect(page.locator('#physicalScheduleState')).to_have_text(reason)
        expect(page.locator('#physicalSave')).to_be_disabled()
        assert not errors
