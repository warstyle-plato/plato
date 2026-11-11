"""График ГПР на телефоне: у каждой строки полоса во всю ширину экрана,
под ней подписаны даты начала и окончания, над корпусами — шкала дат
с отметкой среза. На широком экране график прежний."""
import copy

import pytest
from playwright.sync_api import expect

from browser import expand_gantt
from test_monitor_cumulative_controls import browser_page
from test_monitor_gpr_sections import monitor_view


def two_corpus_view():
    view = monitor_view('partial')
    rss = view['schedule']['management'][0]['children'][0]['children'][0]
    later = dict(copy.deepcopy(rss['children'][0]), id='9', wbs='2.1', object='Корпус 2',
                 name='Кровля', plan_start='2027-01-10', plan_finish='2027-03-01',
                 forecast_finish='2027-03-01', delta_days=0)
    rss['children'].append(later)
    return view


def render(page):
    page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", two_corpus_view())


def box(locator):
    b = locator.bounding_box()
    assert b, 'элемент не отрисован'
    return b


def row(page, name):
    return page.locator('#gantt .g-row', has=page.locator('.g-label .title', has_text=name)).first


def test_phone_rows_have_full_width_bar_with_signed_dates_under_a_date_axis():
    with browser_page(390) as (page, responses, errors):
        render(page)
        rows = page.locator('#gantt .g-row')
        expect(rows.first).to_be_visible()
        axis = page.locator('#gantt .g-axis .axis')
        expect(axis).to_be_visible()
        # Шкала дат стоит над свёрнутыми корпусами, а не прячется.
        assert box(axis)['y'] + box(axis)['height'] <= box(rows.first)['y'] + 1
        assert page.locator('#gantt .axis .tick:visible').count() >= 3
        today = page.locator('#gantt .axis .al-today')
        expect(today).to_be_visible()
        expect(today).to_have_text('на 08.11.2026')
        cut = box(page.locator('#gantt .axis .cut'))
        assert abs(box(today)['x'] + box(today)['width'] / 2 - cut['x']) < 3
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

        for state in ('свёрнуто', 'раскрыто'):
            width = box(page.locator('#gantt'))['width']
            assert width >= 390 - 2 * 20, width
            visible = [rows.nth(i) for i in range(rows.count()) if rows.nth(i).is_visible()]
            assert len(visible) >= 2, state
            for r in visible:
                line = r.locator(':scope > .g-label + div')
                assert box(line)['width'] >= width - 2 * 12 - 2, state
                # Полоса и шкала дат — одна система координат.
                frame = r.locator('.planbar').evaluate(
                    "el=>{const b=el.offsetParent.getBoundingClientRect();return {x:b.x,width:b.width}}")
                assert abs(frame['x'] - box(axis)['x']) < 2 and abs(frame['width'] - box(axis)['width']) < 2, state
                expect(r.locator('.planbar')).to_be_visible()
                dates = r.locator('.g-dates')
                expect(dates).to_be_visible()
                expect(dates).to_contain_text('начало ')
                expect(dates).to_contain_text('окончание ')
                # Подписи стоят под полосой, а не над ней.
                assert box(dates)['y'] >= box(r.locator('.planbar'))['y']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), state
            if state == 'свёрнуто':
                expand_gantt(page)

        first, second = row(page, 'Монтаж фасада'), row(page, 'Кровля')
        expect(first.locator('.g-dates')).to_have_text('начало 01.10.2026окончание 01.12.2026')
        expect(second.locator('.g-dates')).to_have_text('начало 10.01.2027окончание 01.03.2027')
        # Полосы привязаны к общей шкале: поздняя работа начинается правее конца ранней.
        a, b = box(first.locator('.planbar')), box(second.locator('.planbar'))
        assert b['x'] > a['x'] + a['width']
        assert not errors


def test_wide_screen_gantt_keeps_its_three_columns_and_no_phone_labels():
    with browser_page(1440) as (page, responses, errors):
        render(page)
        expand_gantt(page)
        expect(page.locator('#gantt .g-axis > div').first).to_have_text('Корпус, этап и работа')
        expect(page.locator('#gantt .axis .al-cut')).to_be_visible()
        expect(page.locator('#gantt .axis .al-today')).to_be_hidden()
        assert page.locator('#gantt .g-dates').count() >= 2
        assert page.locator('#gantt .g-dates:visible').count() == 0
        tracks = page.evaluate("getComputedStyle(document.querySelector('#gantt .g-row')).gridTemplateColumns")
        assert len(tracks.split()) == 3, tracks
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('cut,label', [(None, 'сегодня'), ('2026-11-08', 'на 08.11.2026')])
def test_phone_axis_says_today_only_when_the_cut_is_today(cut, label):
    with browser_page(390) as (page, responses, errors):
        view = two_corpus_view()
        view['cut'] = cut or page.evaluate("new Date().toLocaleDateString('sv')")
        page.evaluate("(v)=>{currentView=v;renderGantt(v)}", view)
        expect(page.locator('#gantt .axis .al-today')).to_have_text(label)
        assert not errors
