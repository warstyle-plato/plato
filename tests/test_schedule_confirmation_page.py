"""Real Monitor JS: confirmation, revocation, stale responses and private UI."""
import pytest

from test_monitor_cumulative_controls import browser_page, KEY, MARKER


def state(**changes):
    result = dict(source_sha256='a'*64, revision=0, calendar_basis='unconfirmed',
                  rnv_chain_complete=False, note='', recorded_at=None, can_edit=True)
    result.update(changes)
    return result


@pytest.mark.parametrize('width', [390, 1440])
def test_save_reload_and_revoke_with_actual_monitor_script(width):
    from playwright.sync_api import expect
    current = state()
    writes = []
    def respond(route):
        nonlocal current
        body = route.request.post_data_json
        assert body['key'] == KEY
        if route.request.url.endswith('/save'):
            writes.append(body)
            current = state(**{key: body[key] for key in ['calendar_basis', 'rnv_chain_complete', 'note']},
                            revision=current['revision']+1, recorded_at='2026-11-06T12:00:00+00:00')
        route.fulfill(json=current)
    with browser_page(width, init='window.DEVELOPAID_PM_ENABLED=true') as (page, responses, errors):
        page.route('**/monitor/schedule-confirmation/*', respond)
        page.evaluate('void loadScheduleConfirmation()')
        expect(page.locator('#scheduleConfirmationSave')).to_be_enabled()
        page.locator('#scheduleCalendar').select_option('calendar_days')
        page.locator('#scheduleChain').check()
        page.locator('#scheduleConfirmationNote').fill(MARKER)
        page.locator('#scheduleConfirmationSave').click()
        expect(page.locator('#scheduleConfirmationState')).to_contain_text('Последняя проверка')
        expect(page.locator('#scheduleConfirmationSave')).to_be_enabled()
        assert writes[0]['source_sha256'] == 'a'*64 and writes[0]['revision'] == 0
        assert writes[0]['rnv_chain_complete'] is True
        page.reload()
        expect(page.locator('#scheduleChain')).to_be_checked()
        expect(page.locator('#scheduleConfirmationNote')).to_have_value(MARKER)
        assert page.locator('#scheduleConfirmationCard img').count() == 0
        page.locator('#scheduleCalendar').select_option('unconfirmed')
        page.locator('#scheduleChain').uncheck()
        page.locator('#scheduleConfirmationNote').fill('В графике не хватает этапа приёмки.')
        page.locator('#scheduleConfirmationSave').click()
        expect(page.locator('#scheduleConfirmationSave')).to_be_enabled()
        assert writes[-1]['revision'] == 1 and writes[-1]['rnv_chain_complete'] is False
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#scheduleConfirmationCard').bounding_box()['width'] <= width
        assert not page.evaluate('window.untrustedRan||false')
        assert not errors
        page.screenshot(path=f'/tmp/gpr-confirmation-{width}.png', full_page=True)


def test_stale_read_after_project_change_or_logout_cannot_restore_private_form():
    from playwright.sync_api import expect
    with browser_page(init='window.DEVELOPAID_PM_ENABLED=true') as (page, responses, errors):
        held = []
        page.route('**/monitor/schedule-confirmation/view', lambda route: held.append(route))
        with page.expect_request('**/monitor/schedule-confirmation/view'):
            page.evaluate('void loadScheduleConfirmation()')
        page.locator('#project').fill('Другой проект')
        held.pop().fulfill(json=state(note=MARKER))
        expect(page.locator('#scheduleConfirmationCard')).to_be_hidden()
        assert page.locator('#scheduleConfirmationNote').input_value() == ''
        with page.expect_request('**/monitor/schedule-confirmation/view'):
            page.evaluate('void loadScheduleConfirmation()')
        page.evaluate("localStorage.removeItem('plato_projects_key');syncAuthUi()")
        held.pop().fulfill(json=state(note=MARKER))
        expect(page.locator('#scheduleConfirmationCard')).to_be_hidden()
        assert page.locator('#scheduleConfirmationNote').input_value() == ''
        assert not errors


def test_history_is_read_only_and_conflict_requires_a_fresh_read():
    from playwright.sync_api import expect
    with browser_page(init='window.DEVELOPAID_PM_ENABLED=true') as (page, responses, errors):
        page.evaluate('(state)=>renderScheduleConfirmation(state)', state(can_edit=False, note='Проверка на дату среза.'))
        expect(page.locator('#scheduleConfirmationSave')).to_be_disabled()
        expect(page.locator('#scheduleChain')).to_be_disabled()
        page.route('**/monitor/schedule-confirmation/save', lambda r: r.fulfill(status=409, json={'detail':'График изменился.'}))
        page.evaluate('(state)=>renderScheduleConfirmation(state)', state())
        page.locator('#scheduleConfirmationNote').fill('Проверено.')
        page.locator('#scheduleConfirmationSave').click()
        expect(page.locator('#scheduleConfirmationMsg')).to_contain_text('Нажмите «Обновить»')
        expect(page.locator('#scheduleConfirmationSave')).to_be_disabled()
        assert not errors


def test_real_report_pdf_contains_confirmation_provenance(tmp_path):
    import fitz
    from playwright.sync_api import sync_playwright
    from browser import chromium_or_skip
    import developaid_management_report as report
    import developaid_schedule_timeline as timeline
    from test_schedule_dependency_timeline import day, network

    pm = network()
    pm['confirmation'] = state(calendar_basis='calendar_days', rnv_chain_complete=True,
                               recorded_at='2026-11-06T12:00:00+00:00',
                               note='Synthetic calendar evidence 2026')
    block = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    payload = {'project': 'Учебный проект', 'kind': 'week', 'start': '2026-11-01',
               'end': '2026-11-06', 'gantt': {'state': 'missing', 'dependency_timeline': block}}
    path = tmp_path / 'synthetic-confirmation-report.pdf'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()), headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content(report.render_html(payload), wait_until='load')
        page.pdf(path=str(path), format='A4', print_background=True)
        browser.close()
    with fitz.open(path) as pdf:
        text = ' '.join(page.get_text() for page in pdf)
    assert 'Synthetic calendar evidence 2026' in text
    assert '06.11.2026' in text and 'Проверка исходного графика' in text
