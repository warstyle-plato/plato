"""Test page «ГПР — новый вид»: the brief arranges the Monitor view, the page shows it."""
import contextlib
import copy
import http.server
import json
import threading

import pytest
from playwright.sync_api import expect, sync_playwright

import developaid_gpr_brief as brief
import developaid_monitor_pace as pace
from browser import chromium_or_skip
from developaid_gpr_preview_page import PAGE
from test_monitor_cumulative_api import KEY, api, post
from test_schedule_readiness import DAY, PROJECT, activate, site


def row(id_, name, obj, plan, fact, done=False):
    shown = {} if fact is None else {'value': fact, 'date': DAY, 'label': 'Выполнено по ГПР'}
    return {'id': id_, 'name': name, 'object': obj, 'plan_progress': plan, 'display_progress': shown,
            'work_done': done, 'plan_finish': '2026-12-01'}


def view():
    rows = [row('1', 'Монолит', 'Корпус 1', .8, .2), row('2', 'Монолит', 'Корпус 2', .8, .75),
            row('3', 'Фасад', 'Корпус 1', .5, None), row('4', 'Кровля', 'Корпус 2', .3, 1.0),
            row('5', 'Озеленение', 'Корпус 1', .9, .1)]
    cell = lambda ids: {'work_ids': ids, 'progress': None}
    return {'cut': DAY, 'schedule': {'rows': rows, 'readiness': {
        'matrix_objects': ['Корпус 1', 'Корпус 2'],
        # Work 5 sits in no cell: it is outside the matrix, whatever its name says.
        'matrix': [{'stage': 'Каркас', 'cells': [cell(['1']), cell(['2'])]},
                   {'stage': 'Отделка', 'cells': [cell(['3']), cell(['4'])]}],
        'corpora': [{'name': 'Корпус 1', 'progress': .4, 'forecast': {'plan_finish': '2026-12-01'}},
                    {'name': 'Корпус 2', 'progress': .9, 'forecast': {'plan_finish': '2026-11-30'}}],
        'project': {'progress': None, 'reason': 'Нет подтверждённого полного состава и весов.'},
        'reason': 'Нет подтверждённого полного состава и весов.'}},
        'dashboard': {'schedule': {'qualified_rnv': {'plan_date': '2026-12-01', 'plan_label': 'План ввода',
                                                     'reasons': ['Нет подтверждённого полного состава и весов.']}}}}


def test_brief_keeps_absent_fact_apart_and_reads_stages_only_from_the_matrix():
    b = brief.build(view())
    states = {w['id']: w['state'] for s in b['matrix']['stages'] for l in s['lines']
              for ws in l['by_object'].values() for w in ws}
    # 75% against 80% is within the rule; an absent fact is never «behind» or zero.
    assert states == {'1': 'behind', '2': 'on_plan', '3': 'no_reading', '4': 'done'}
    assert b['counts'] == {'total': 4, 'done': 1, 'behind': 1, 'no_reading': 1}
    assert b['outside_matrix'] == 1 and 'Озеленение' not in json.dumps(b, ensure_ascii=False)
    assert [s['stage'] for s in b['matrix']['stages']] == ['Каркас', 'Отделка']
    frame = b['matrix']['stages'][0]
    assert [l['name'] for l in frame['lines']] == ['Монолит']           # one line for both corpora
    assert set(frame['lines'][0]['by_object']) == {'Корпус 1', 'Корпус 2'}
    assert b['attention'] == {'items': [{'name': 'Монолит', 'works': [b['matrix']['stages'][0]['lines'][0]['by_object']['Корпус 1'][0]]}], 'total': 1}
    assert b['plan_finish'] == {'date': '2026-12-01', 'label': 'План ввода'}
    assert b['expected_finish']['state'] == 'pending' and b['progress']['value'] is None
    assert b['notes'] == ['Нет подтверждённого полного состава и весов.']
    assert [(c['name'], c['behind'], c['no_reading']) for c in b['corpora']] == [('Корпус 1', 1, 1), ('Корпус 2', 0, 0)]


def test_brief_moves_a_work_when_the_matrix_moves_it():
    moved = view()
    stages = moved['schedule']['readiness']['matrix']
    stages[0]['cells'][0]['work_ids'], stages[1]['cells'][0]['work_ids'] = ['3'], ['1']
    b = brief.build(moved)
    assert [l['name'] for l in b['matrix']['stages'][0]['lines']] == ['Фасад', 'Монолит']
    assert [(s['behind'], s['no_reading'], s['done']) for s in b['matrix']['stages']] == [(0, 1, 0), (1, 0, 1)]


def test_brief_and_page_routes_keep_monitor_access(api, site):
    client, _ = api
    good = post(client, 'gpr-brief', project=PROJECT, cut=DAY)
    assert good.status_code == 200 and good.headers['cache-control'] == 'private, no-store'
    assert good.json() == json.loads(json.dumps(brief.build(pace.schedule_view(PROJECT, DAY)), default=str))
    denied = post(client, 'gpr-brief', key='wrong-key', project=PROJECT, cut=DAY)
    assert denied.status_code == 403 and 'counts' not in denied.text
    missing = post(client, 'gpr-brief', project='Нет такого', cut=DAY).json()
    assert missing['empty'] and missing['empty_reason'] == 'Утверждённый график работ не загружен.'
    assert missing['notes'][0] == missing['empty_reason'] and missing['counts']['total'] == 0
    bad_cut = post(client, 'gpr-brief', project=PROJECT, cut='не дата')
    assert bad_cut.status_code in (400, 422) and bad_cut.headers['cache-control'] == 'private, no-store'
    page = client.get('/gpr-preview')
    assert page.status_code == 200 and 'ГПР — новый вид' in page.text and '__VERSION__' not in page.text


@contextlib.contextmanager
def preview(width, data, key=KEY):
    html = PAGE.replace('__VERSION__', 'test').encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    calls = []

    def answer(route):
        body = json.loads(route.request.post_data or '{}')
        calls.append((route.request.url.rsplit('/', 1)[-1], body))
        if body.get('key') != KEY:
            return route.fulfill(status=403, json={'detail': 'Нужен ключ администратора.'})
        if route.request.url.endswith('/report/projects'):
            return route.fulfill(json={'projects': [{'project': 'Другой'}, {'project': PROJECT}]})
        return route.fulfill(json=data)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chromium_or_skip()), headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': width, 'height': 900})
            page.set_default_timeout(5000)
            if key:
                page.add_init_script(f"localStorage.setItem('plato_projects_key',{json.dumps(key)});"
                                     f"localStorage.setItem('monitor_project',{json.dumps(PROJECT)})")
            page.route('**/monitor/report/projects', answer)
            page.route('**/monitor/gpr-brief', answer)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/gpr-preview#cut={DAY}')
            yield page, calls, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('width', [390, 1440])
def test_rendered_preview_shows_deadlines_attention_and_an_opening_matrix(site, width):
    data = json.loads(json.dumps(brief.build(view())))
    with preview(width, data) as (page, calls, errors):
        expect(page.locator('#deadlines')).to_contain_text('План ввода')
        expect(page.locator('#deadlines')).to_contain_text('01.12.2026')
        expect(page.locator('#expected')).to_contain_text('единая оценка срока')
        expect(page.locator('#deadlines')).to_contain_text('1 из 4')
        expect(page.locator('#factDates')).to_contain_text('на 12.11.2026')
        corpus = page.locator('.corpora tbody tr').first
        expect(corpus).to_contain_text('Корпус 1')
        expect(corpus.locator('td').nth(4)).to_have_text('1')
        if width <= 700:
            assert 'Без показания' in corpus.locator('td').nth(4).evaluate("e=>getComputedStyle(e,'::before').content")
        assert calls[-1] == ('gpr-brief', {'key': KEY, 'session': '', 'project': PROJECT, 'cut': DAY})
        attention = page.locator('#attention li')
        expect(attention).to_have_count(1)
        expect(attention).to_contain_text('Монолит')
        expect(attention).to_contain_text('выполнено 20%, по плану 80%')
        lines = page.locator('#matrix tr.lines').first
        expect(lines).to_be_hidden()
        page.locator('#matrix td.stage', has_text='Каркас').click()
        expect(lines).to_be_visible()
        expect(page.locator('#matrix')).to_contain_text('нет показания' if width > 700 else 'Каркас')
        if width <= 700:
            # One corpus at a time on the phone; the switcher shows the other one.
            expect(page.locator('#matrix thead th')).to_have_count(2)
            page.locator('#objectSwitch [data-object="Корпус 2"]').click()
            expect(page.locator('#matrix thead th').nth(1)).to_have_text('Корпус 2')
        else:
            expect(page.locator('#matrix thead th')).to_have_count(3)
        page.locator('#onlyBehind').check()
        expect(page.locator('#matrix .stage-row')).to_have_count(1)
        # The opened stage stays open through the filter and the corpus switch.
        expect(page.locator('#matrix tr.lines').first).to_be_visible()
        page.locator('#matrix td.stage', has_text='Каркас').click()
        expect(page.locator('#matrix tr.lines').first).to_be_hidden()
        expect(page.locator('#method')).not_to_have_attribute('open', '')
        page.locator('#method summary').click()
        expect(page.locator('#method')).to_contain_text('Работ вне матрицы: 1.')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        # The corpus table fits the screen itself instead of hiding behind its own scroll.
        assert page.evaluate("[...document.querySelectorAll('.scroll')].every(e=>e.scrollWidth<=e.clientWidth)")
        assert not errors


def test_rendered_preview_shows_real_readiness_and_asks_for_a_key(site):
    activate(site)
    data = json.loads(json.dumps(brief.build(pace.schedule_view(PROJECT, DAY)), default=str))
    with preview(1440, data) as (page, _, errors):
        expect(page.locator('#deadlines')).to_contain_text('Готовность проекта (оценочная)')
        expect(page.locator('#deadlines')).to_contain_text('70%')
        assert not errors
    with preview(390, data, key='') as (page, calls, errors):
        expect(page.locator('#msg')).to_contain_text('войдите в текущий Монитор')
        assert calls == [] and page.locator('#deadlines').count() == 0 and not errors


def test_rendered_preview_names_the_reason_when_no_schedule_is_loaded(api):
    client, _ = api
    data = post(client, 'gpr-brief', project='Нет такого', cut=DAY).json()
    with preview(390, data) as (page, _, errors):
        expect(page.locator('#deadlines')).to_contain_text('Утверждённый график работ не загружен.')
        assert page.locator('#matrix').count() == 0 and not errors
