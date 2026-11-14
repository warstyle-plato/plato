"""Execute the actual page through slow admission/polling and source fallback."""
import pytest

import developaid_gpr_corpus as corpus
from test_gpr_corpus_preview import book
from browser import expand_gantt
from test_monitor_cumulative_controls import browser_page, KEY
from test_monitor_gpr_sections import monitor_view


@pytest.mark.parametrize('width', [390, 1440])
def test_all_source_packages_are_accessible_while_the_approved_view_is_pending(width):
    from playwright.sync_api import expect
    source = corpus.read(book(name='Решения Сталко', bad_date='30.06.2027'))
    source['baseline_approved'] = True
    source['packages'][1]['name'] = 'Монтаж другого подрядчика'
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(r)=>{currentView=null;renderCorpusGprSource(r)}',
                      {'source': source, 'html': corpus.render_overview(source, '2026-11-10')})
        expect(page.locator('#gprEmptyText')).to_contain_text('Утверждённый ГПР загружен')
        expect(page.locator('#gprEmptyText')).not_to_contain_text('добавьте')
        titles = page.locator('.corpus-gpr-package > summary')
        assert titles.all_text_contents() == ['Решения Сталко', 'Монтаж другого подрядчика']
        titles.nth(1).click()
        expect(page.locator('.corpus-gpr-package').nth(1)).to_contain_text('КОРПУС 1')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_pending_job_polls_then_renders_full_view_instead_of_one_source_package():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        held = []
        starts = []
        # A successful view loads this authenticated GET. The general fixture
        # checks POST body keys only, so give this endpoint its real admission.
        def daily_summary(route):
            assert route.request.method == 'GET'
            assert route.request.headers.get('x-developaid-admin-key') == KEY
            route.fulfill(json={'rows': []})
        page.route('**/monitor/daily/summary*', daily_summary)
        def admission(route):
            starts.append(route.request.post_data_json)
            route.fulfill(status=202, json={'pending': True, 'ticket': 'a'*32})
        page.route('**/monitor/view', admission)
        page.route('**/monitor/view/result', lambda route: held.append(route))
        with page.expect_request('**/monitor/view/result'):
            page.locator('#refresh').click()
        expect(page.locator('#viewMsg')).to_contain_text('в фоне')
        expect(page.locator('#refresh')).to_be_disabled()
        assert starts[0]['background'] is True
        for route in held:
            route.fulfill(json={'pending': False, 'snapshot': monitor_view()})
        expect(page.locator('#gprFactMatrix [data-work-id]')).to_have_count(3)
        page.locator('#gprCalendar > summary').click()
        expect(page.locator('#gantt .lvl-corpus').first).to_be_visible()
        expect(page.locator('#refresh')).to_be_enabled()
        expand_gantt(page)
        expect(page.locator('#gantt .lvl-task')).to_have_count(3)
        expect(page.locator('#gantt')).to_contain_text('Внутренние работы')
        assert len(starts) == 1 and not errors


@pytest.mark.parametrize('change', ['project', 'date', 'auth'])
def test_a_late_result_cannot_restore_the_previous_project_and_504_never_blames_fields(change):
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        held = []
        page.route('**/monitor/view', lambda route: route.fulfill(status=202, json={'pending': True, 'ticket': 'b'*32}))
        page.route('**/monitor/view/result', lambda route: held.append(route))
        with page.expect_request('**/monitor/view/result'):
            page.locator('#refresh').click()
        if change == 'project':
            page.locator('#project').fill('Новый проект')
        elif change == 'date':
            page.locator('#cut').fill('2026-11-10')
        else:
            page.locator('#logoutBtn').click()
        for route in held:
            route.fulfill(json={'pending': False, 'snapshot': monitor_view()})
        expect(page.locator('#gantt .lvl-task')).to_have_count(0)
        expect(page.locator('#refresh')).to_be_enabled()
        expect(page.locator('#refresh')).to_have_text('Обновить')
        page.route('**/monitor/test-504', lambda route: route.fulfill(status=504, body='Gateway timeout'))
        message = page.evaluate("post('/monitor/test-504',{}).catch(e=>e.message)")
        assert 'Сервер не успел' in message and 'поля' not in message
        assert 'повторная загрузка файлов не требуется' not in message
        assert not errors
