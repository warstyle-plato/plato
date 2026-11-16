"""График ГПР на телефоне: у каждой строки полоса во всю ширину экрана,
под ней подписаны даты начала и окончания, над корпусами — шкала дат
с отметкой среза. На широком экране график прежний."""
import copy
import datetime as dt

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
        expect(page.locator('#gprFactMatrix [data-work-id]')).to_have_count(4)
        assert page.locator('#gprCalendar').get_attribute('open') is None
        page.locator('#gprCalendar > summary').click()
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
        expect(first.locator('.g-dates')).to_have_text('по плану: начало 01.10.2026окончание 01.12.2026')
        expect(second.locator('.g-dates')).to_have_text('по плану: начало 10.01.2027окончание 01.03.2027')
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


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('cut_kind', ['historical', 'today'])
@pytest.mark.parametrize('calendar', ['before', 'within', 'after', 'one-day'])
def test_cut_label_stays_on_axis_without_changing_dates_or_marker(width, cut_kind, calendar, monkeypatch, tmp_path):
    import developaid_monitor as monitor
    from test_monitor_management_gantt import _gpr_book

    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    cut = dt.date(2026, 11, 8) if cut_kind == 'historical' else dt.date(2026, 11, 12)
    start, finish = {
        'before': (dt.date(2027, 1, 10), dt.date(2027, 3, 1)),
        'within': (dt.date(2026, 10, 1), dt.date(2026, 12, 1)),
        'after': (dt.date(2026, 7, 1), dt.date(2026, 8, 1)),
        'one-day': (cut, cut),
    }[calendar]
    data = _gpr_book([(1, 'Работа с границами', 0, start, finish, 'В работе', '2.2.1.1')])
    project = 'Учебный график среза'
    monitor.store_schedule(project, data, None, min(start,cut).isoformat())
    view = monitor.build(project, cut.isoformat())
    # The existing axis has 15 days of padding and clamps the marker to it.
    # These independent date expectations must survive a label-only fix.
    first, last = start - dt.timedelta(days=15), finish + dt.timedelta(days=15)
    position = lambda day: max(0, min(100, (day-first).days / (last-first).days * 100))
    with browser_page(width) as (page, responses, errors):
        page.clock.set_fixed_time('2026-11-12T12:00:00Z')
        page.evaluate('(v)=>{currentView=v;renderDash(v);renderGantt(v)}', view)
        expand_gantt(page)
        axis = page.locator('#gantt .g-axis .axis')
        marker = axis.locator('.cut')
        label = axis.locator('.al-today')
        expect(label).to_have_text('сегодня' if cut_kind == 'today' else 'на 08.11.2026')
        assert marker.evaluate('e=>parseFloat(e.style.left)') == pytest.approx(position(cut), abs=.0001)
        task = page.locator('#gantt .g-row.lvl-task', has_text='Работа с границами')
        expect(task.locator('.planbar')).to_be_visible()
        plan = task.locator('.planbar').evaluate('e=>({left:parseFloat(e.style.left),width:parseFloat(e.style.width)})')
        assert plan['left'] == pytest.approx(position(start), abs=.0001)
        assert plan['width'] == pytest.approx(max(1, position(finish)-position(start)), abs=.0001)
        assert axis.locator('.tick').evaluate_all('(es)=>es.map(e=>parseFloat(e.style.left))') == pytest.approx([i/6*100 for i in range(7)], abs=.0001)
        if width == 390:
            expect(label).to_be_visible()
            frame, cut_box, text = box(axis), box(marker), box(label)
            ideal = max(frame['x'], min(cut_box['x']-text['width']/2, frame['x']+frame['width']-text['width']))
            assert abs(text['x']-ideal) < 1, {'axis':frame,'cut':cut_box,'label':text}
            assert text['x'] >= frame['x']-.5
            assert text['x']+text['width'] <= frame['x']+frame['width']+.5
            assert label.evaluate('e=>e.scrollWidth<=e.clientWidth && getComputedStyle(e).whiteSpace==="nowrap"')
            expect(task.locator('.g-dates')).to_have_text(
                f'по плану: начало {start:%d.%m.%Y}окончание {finish:%d.%m.%Y}')
        else:
            expect(label).to_be_hidden()
            expect(axis.locator('.al-cut')).to_be_visible()
            assert len(page.locator('#gantt .g-axis').evaluate('e=>getComputedStyle(e).gridTemplateColumns').split()) == 3
            expect(task.locator('.g-dates')).to_be_hidden()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_a_browser_without_container_units_keeps_the_cut_label_centred_on_the_marker():
    # Браузер без cqw не применяет правило под @supports; убираем его и проверяем прежний вид.
    with browser_page(390) as (page, responses, errors):
        view = two_corpus_view()
        view['cut'] = '2026-11-08'
        page.evaluate("(v)=>{currentView=v;renderGantt(v)}", view)
        page.locator('#gprCalendar > summary').click()
        removed = page.evaluate("""()=>{let n=0;for(const sheet of document.styleSheets){const rules=[...sheet.cssRules];
          for(let i=rules.length-1;i>=0;i--){const r=rules[i];
            if(r instanceof CSSSupportsRule&&/cqw/.test(r.conditionText)&&/al-today/.test(r.cssText)){sheet.deleteRule(i);n++}}}
          return n}""")
        assert removed == 1, 'прижатие подписи к краям шкалы должно стоять под @supports(cqw)'
        label = page.locator('#gantt .axis .al-today')
        marker = page.locator('#gantt .axis .cut')
        expect(label).to_be_visible()
        text, cut = box(label), box(marker)
        assert abs(text['x'] + text['width'] / 2 - (cut['x'] + cut['width'] / 2)) < 1, {'label': text, 'cut': cut}
        assert not errors
