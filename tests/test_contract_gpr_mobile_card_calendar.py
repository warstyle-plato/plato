"""The native card shows the calendar on phones without hiding execution below it."""
import contextlib
import copy
import datetime as dt

import pytest
from playwright.sync_api import expect

from tests.test_monitor_cumulative_controls import CONTRACT, browser_page


LONG_NAME = ('Устройство НВФ: облицовка из алюминиевых панелей с декоралом; '
             'подсистема, утеплитель толщиной 100 мм и минераловатные плиты 50 мм. ' * 5)


def gpr_state(preview=False):
    rows = []
    for i in range(36):
        progress = None if i == 1 else {
            'cut': '2026-11-27', 'fact_quantity': 0 if i == 0 else 80,
            'contract_quantity': 100, 'unit': 'м²', 'fraction': 0 if i == 0 else .8,
            'planned_fraction': .6, 'delta_pp': -60 if i == 0 else 20,
            'lag_days': 30 if i == 0 else 0, 'age_days': 9,
            'last_confirmed_at': '2026-11-18', 'source_dates': ['2026-11-18'],
        }
        rows.append({'number': f'{i//12+1}.{i%12+1}', 'code': f'line-{i}',
                     'name': LONG_NAME if i < 2 else 'Монтаж светопрозрачных конструкций',
                     'section': f'Корпус {i//12+1}', 'start': '2026-08-01',
                     'finish': '2027-04-30', 'bars': [{'state': 'plan', 'start': 0, 'end': 273}],
                     'progress': progress, 'quantity': progress,
                     'position_key': ['estimate', str(i)]})
    presentation = {'start': '2026-08-01', 'length': 273, 'cut': '2026-11-27',
                    'ticks': [{'start': f'2026-{month:02d}-01',
                               'finish': f'2026-{month:02d}-28', 'label': f'{month:02d}.2026'}
                              for month in range(8, 13)] + [
                                  {'start': '2027-04-01', 'finish': '2027-04-30', 'label': '04.2027'}],
                    'rows': copy.deepcopy(rows), 'positions': copy.deepcopy(rows)}
    state = {'cut': '2026-11-27', 'source': {'sha256': 'f' * 64},
             'schedule': {'calendar_basis': 'calendar'}, 'presentation': presentation}
    if preview:
        state['source'] = None
        state['preview'] = {'schedule': state['schedule'], 'presentation': presentation,
                            'source': {'sha256': 'f' * 64},
                            'note': 'Несколько источников ГПР требуют выбора.'}
        state['pending'] = [{'title': 'Дополнительное соглашение № 1',
                             'filename': 'ГПР-приложение.pdf', 'source': {'sha256': 'f' * 64},
                             'choice_required': True, 'can_activate': True}]
    return state


@contextlib.contextmanager
def gpr_page(width, preview=False):
    state = gpr_state(preview)
    with browser_page(width) as (page, _, errors):
        page.route('**/monitor/contracts/documents', lambda route: route.fulfill(json={
            'ok': True, 'pending': False, 'documents': [], 'gpr': state}))
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractGprBody[aria-busy="false"]').wait_for(state='attached')
        page.locator('#contractGpr > summary').click()
        yield page, state, errors


@pytest.mark.parametrize('width', [390, 440, 1440])
def test_calendar_and_compact_names_leave_execution_reachable(width):
    with gpr_page(width) as (page, state, errors):
        plot = page.locator('.contract-gpr-scroll')
        expect(plot).to_be_visible()
        assert plot.bounding_box()['height'] <= 622
        assert plot.evaluate('(e)=>e.scrollHeight>e.clientHeight')
        first = page.locator('.contract-gpr-position').first
        name = first.locator('.contract-gpr-work')
        expect(name).not_to_have_attribute('open', '')
        assert name.bounding_box()['height'] < 85
        expect(first).to_contain_text('факт 0 %')
        expect(page.locator('.contract-gpr-position').nth(1)).to_contain_text('Нет сопоставленного объёма')
        if width <= 700:
            assert plot.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            track = first.locator('[data-track="source-plan"]')
            viewport = plot.bounding_box()
            box = track.bounding_box()
            assert box['x'] >= viewport['x'] and box['x'] + box['width'] <= viewport['x'] + viewport['width']
            assert box['width'] >= width - 125
            expect(first.locator('.contract-gpr-local-axis')).to_contain_text('01.08.2026')
            expect(first.locator('.contract-gpr-local-axis')).to_contain_text('30.04.2027')
            assert page.locator('.contract-gpr-heading').evaluate('(e)=>getComputedStyle(e).position') == 'static'
        name.locator('summary').click()
        expect(name).to_have_attribute('open', '')
        expect(name.locator('b')).to_have_text('1.1 ' + LONG_NAME)
        assert name.bounding_box()['height'] > 85
        page.locator('#contractExecution > summary').click()
        page.locator('#contractComparison').scroll_into_view_if_needed()
        expect(page.locator('#contractComparisonTitle')).to_be_in_viewport()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors


@pytest.mark.parametrize('width', [390, 440, 1440])
def test_unselected_preview_names_the_reason_and_choice_before_the_chart(width):
    with gpr_page(width, preview=True) as (page, state, errors):
        expect(page.locator('#contractGprTitle')).to_have_text('ГПР')
        expect(page.locator('#contractGprDownload')).to_have_text('Скачать ГПР, выполнение и численность')
        expect(page.locator('#contractGprDownload')).to_be_disabled()
        expect(page.locator('.contract-gpr-preview-note')).to_contain_text('выбор источника в программе, а не юридическая приёмка работ')
        expect(page.locator('.contract-gpr-preview-note')).to_contain_text('ещё не выбрана в программе для расчёта договора')
        choice = page.locator('.contract-gpr-source-selection')
        expect(choice.locator(':scope>summary')).to_have_text('Выбрать ГПР для расчёта (1)')
        assert choice.bounding_box()['y'] < page.locator('.contract-gpr-scroll').bounding_box()['y']
        choice.locator(':scope>summary').click()
        expect(choice.locator('[data-gpr-activate]')).to_be_visible()
        expect(choice.locator('[data-gpr-signed]')).not_to_be_checked()
        assert state['source'] is None
        page.evaluate('renderContractGpr(null)')
        expect(page.locator('#contractGprTitle')).to_have_text('ГПР')
        expect(page.locator('#contractGprBody')).to_contain_text('пока не загружен')
        expect(page.locator('#contractGprDownload')).to_be_disabled()
        assert not errors


@pytest.mark.parametrize('width', [440, 1440])
def test_print_has_no_clipped_calendar_or_scroll_height_limit(width):
    with gpr_page(width) as (page, _, errors):
        page.emulate_media(media='print')
        plot = page.locator('.contract-gpr-scroll')
        assert plot.evaluate('(e)=>getComputedStyle(e).maxHeight') == 'none'
        assert plot.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('basis', ['relative-unanchored', 'relative-anchored', 'absolute'])
def test_date_markers_need_a_calendar_origin_and_keep_a_known_zero_offset(width, basis):
    state = gpr_state()
    relative = basis.startswith('relative')
    anchored = basis != 'relative-unanchored'
    origin = '2026-11-27' if anchored else None
    row = {'number': '1', 'code': 'relative-work', 'name': 'Учебная работа по неделям',
           'bars': [{'state': 'plan', 'start': 0, 'end': 21}],
           'start': origin, 'finish': '2026-12-17' if anchored else None}
    columns = [{'start_day': i * 7 + 1, 'finish_day': (i + 1) * 7,
                'label': f'{i + 1} нед.'} for i in range(3)]
    state['schedule'] = {'calendar_basis': 'relative' if relative else 'calendar',
                         'columns': columns, 'anchor': {'handover_date': origin} if anchored and relative else {}}
    state['presentation'] = {'start': origin, 'length': 21, 'rows': [row],
                             'ticks': columns if relative and not anchored else [
                                 {'start': origin, 'finish': '2026-12-17', 'label': '27.11 — 17.12'}]}
    with gpr_page(width) as (page, _, errors):
        page.clock.install(time=dt.datetime(2026, 11, 27, 12, tzinfo=dt.timezone.utc))
        assert page.evaluate('(value)=>{const before=JSON.stringify(value);renderContractGpr(value);return before===JSON.stringify(value)}', state)
        plan = page.locator('[data-track="source-plan"] rect[fill="#D9D9D9"]')
        expect(plan).to_have_count(1)
        expect(plan).to_have_attribute('x', '0')
        expect(plan).to_have_attribute('width', '1000')
        markers = page.locator('.contract-gpr-date-marker')
        if anchored:
            # The origin date has legitimate offset zero; the data cut is drawn
            # at the end of that day, exactly as on an ordinary calendar.
            expect(markers).to_have_count(1)
            expect(markers).to_have_attribute('data-date', '2026-11-27')
            assert float(markers.get_attribute('x1')) == pytest.approx(1000 / 21)
        else:
            expect(markers).to_have_count(0)
            local_axis = page.locator('.contract-gpr-local-axis')
            expect(local_axis.locator('span').first).to_have_text('1 нед.')
            expect(local_axis.locator('span').last).to_have_text('3 нед.')
            if width == 390:
                expect(local_axis).to_be_visible()
            expect(page.locator('.contract-gpr-markers')).to_contain_text('после подтверждения начала ГПР')
            assert page.evaluate('contractGprState.presentation.start') is None
            assert page.evaluate('Object.keys(contractGprState.schedule.anchor).length') == 0
        assert not errors
