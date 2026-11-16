"""The actual Monitor page keeps cumulative uploads and contract review private.

Synthetic responses exercise the browser UI; service and financial tests cover
those responses separately. No customer workbook is kept in this fixture.
"""
from __future__ import annotations

import contextlib
import copy
import http.server
import io
import json
import sys
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from browser import chromium_or_skip
from developaid_monitor_page import MONITOR_PAGE
import management_contour
import plato_question

KEY = 'synthetic-current-admin-key'
CONTRACT = 'a' * 64
OTHER = 'b' * 64
MARKER = '<img src=x onerror="window.untrustedRan=true">'


def register(project='Учебный проект'):
    return {'cut': '2026-11-06', 'source_date': '2026-10-21', 'rows': [
        {'id': CONTRACT, 'contractor': 'Подрядчик ' + project, 'customer': 'Заказчик',
         'contract': 'Д-01', 'contract_date': '2026-01-01', 'subject': MARKER,
         'amount': 1_000_000, 'completed': 1_977_700, 'completion_ratio': 1.9777,
         'remaining': -977_700, 'deadline': None, 'deadline_source': None,
         'source_date': '2026-10-21', 'source': {'filename': 'РСС.xlsx', 'sheet': 'Договоры', 'row': 9},
         'warnings': ['Выполнение превышает сумму договора'],
         'physical_items': [{'name': 'Монтаж', 'scope': 'Корпус 1', 'unit': 'м²',
                             'plan_quantity': 100, 'completed_quantity': 35,
                             'material_quantity': 100, 'completion_ratio': .35,
                             'source': {'filename': 'КС.xlsx', 'row': 41}, 'warnings': [],
                             'quantity_date': '2026-10-20', 'quantity_cut': '2026-11-06',
                             'quantity_basis': 'По датированным периодам.', 'snapshot_date': '2026-11-06'}],
         'reconciliation': {'status': 'Требуется подтверждение',
                            'source_dates': {'КС': '2026-10-21'},
                            'daily_evidence': [{'id': 'evidence-01', 'date': '2026-11-02',
                                                'text': MARKER, 'contractor': 'Подрядчик',
                                                'match_status': 'proposed',
                                                'candidate_contract_ids': [CONTRACT],
                                                'selectable_contract_ids': [CONTRACT],
                                                'suggested_contract_id': CONTRACT,
                                                'source': {'kind': 'daily_report', 'date': '2026-11-02', 'line_index': 1}}],
                            'issues': ['Текст сообщения не подтверждает приёмку']}},
        {'id': OTHER, 'contractor': 'Другой подрядчик', 'contract': 'Д-02',
         'amount': None, 'completed': 0, 'completion_ratio': None, 'remaining': None,
         'deadline': None, 'warnings': [], 'physical_items': [],
         'source_date': None},
    ], 'unmatched_works': [{'id': 'unmatched-01', 'date': '2026-11-03',
                            'text': 'Работы без договора', 'match_status': 'unmatched'}], 'warnings': []}


@contextlib.contextmanager
def page_server():
    html = (MONITOR_PAGE.replace('__DEVELOPAID_CONTOUR_STYLE__', management_contour.STYLE)
            .replace(management_contour.PLACEHOLDER, management_contour.markup('/monitor'))
            .replace(plato_question.PLACEHOLDER, plato_question.SCRIPT))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/monitor'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class Responses:
    def __init__(self):
        self.calls = []
        self.jobs = {}
        self.uploaded = False
        self.upload_failure = False
        self.reject_build_once = False
        self.reject_key = False
        self.reject_poll = False
        self.pending_projects = set()
        self.terms = []
        self.links = []
        self.data = register()

    def __call__(self, route):
        path = urlparse(route.request.url).path
        try:
            body = route.request.post_data_json or {}
        except Exception:
            body = {}
        self.calls.append((path, body, route.request.url))
        request_key = body.get('key')
        if path == '/monitor/daily/summary' and route.request.method == 'GET':
            request_key = route.request.headers.get('x-developaid-admin-key')
        if self.reject_key or request_key != KEY:
            return route.fulfill(status=403, json={'detail': 'Нужен ключ администратора'})
        if path == '/monitor/daily/summary':
            return route.fulfill(json={'rows': []})
        if path == '/monitor/view':
            return route.fulfill(status=400, json={'detail': 'Для учебного проекта ещё нет ГПР'})
        if path == '/monitor/cumulative/list':
            return route.fulfill(json={'snapshots': [{'taken_at': '2026-11-06', 'filename': MARKER+'.zip', 'files_count': 2}] if self.uploaded else []})
        if path in ['/monitor/contracts/build', '/monitor/contracts/term', '/monitor/contracts/link', '/monitor/cumulative/upload']:
            if self.reject_build_once:
                self.reject_build_once = False
                return route.fulfill(status=429, json={'detail': 'Сервер занят'})
            ticket = body['ticket']
            assert len(ticket) == 32
            self.jobs[ticket] = (path, body)
            return route.fulfill(status=202, json={'pending': True, 'ticket': ticket})
        if path in ['/monitor/contracts/result', '/monitor/cumulative/result']:
            if self.reject_poll:
                return route.abort('connectionfailed')
            job, params = self.jobs[body['ticket']]
            if params.get('project') in self.pending_projects:
                return route.fulfill(status=202, json={'pending': True, 'ticket': body['ticket']})
            if job == '/monitor/cumulative/upload':
                if self.upload_failure:
                    return route.fulfill(json={'pending': False, 'ok': False, 'detail': 'Не удалось прочитать один файл. Архив не сохранён.', 'files': [
                        {'filename': 'Читаемый.xlsx', 'status': 'parsed'},
                        {'filename': 'Примечания.txt', 'status': 'ignored'},
                        {'filename': MARKER+'.xlsx', 'status': 'failed', 'warnings': [MARKER]},
                        {'filename': 'Следующий.xlsx', 'status': 'not_read'},
                    ]})
                self.uploaded = True
                return route.fulfill(json={'pending': False, 'ok': True, 'snapshot': {
                    'taken_at': params['taken_at'], 'filename': params['filename'],
                    'files': [{'filename': MARKER+'.xlsx', 'status': 'Прочитан', 'warnings': [MARKER]}],
                    'warnings': ['Проценты ГПР не менялись'], 'issues': [{'filename': 'Ведомость.xlsx', 'sheet': 'Работы', 'row': 41, 'message': 'Объём требует проверки'}], 'issues_count': 1, 'issues_overflow_count': 0}})
            if job == '/monitor/contracts/term':
                self.terms.append(params)
                self.data['rows'][0]['deadline'] = params['deadline'] or None
                self.data['rows'][0]['deadline_source'] = {'label': 'Внесено вручную', 'note': params['note']}
                return route.fulfill(json={'pending': False, 'ok': True, 'term': {'deadline': params['deadline']}})
            if job == '/monitor/contracts/link':
                self.links.append(params)
                evidence = self.data['rows'][0]['reconciliation']['daily_evidence'][0]
                evidence['match_status'] = 'confirmed' if params['confirmed'] else 'proposed'
                evidence['contract_id'] = params['contract_id'] if params['confirmed'] else ''
                evidence['link_basis'] = 'manual' if params['confirmed'] else 'candidate'
                return route.fulfill(json={'pending': False, 'ok': True, 'link': {}})
            data = copy.deepcopy(self.data)
            if data['rows']:
                data['rows'][0]['contractor'] = 'Подрядчик ' + params['project']
            return route.fulfill(json={'pending': False, 'ok': True, 'register': data})
        return route.fulfill(json={})


@contextlib.contextmanager
def browser_page(width=390, hash_='', init=''):
    from playwright.sync_api import sync_playwright
    chrome = chromium_or_skip()
    responses = Responses()
    with page_server() as url, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome), headless=True,
                                     args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': width, 'height': 950})
        page.set_default_timeout(5000)
        page.add_init_script(f"localStorage.setItem('plato_projects_key',{json.dumps(KEY)});localStorage.setItem('monitor_project','Учебный проект');")
        if init:
            page.add_init_script(init)
        page.route('**/monitor/**', responses)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url+hash_)
        page.locator('#privateArea').wait_for(state='visible', timeout=5000)
        try:
            yield page, responses, errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [390, 1440])
def test_contracts_render_exact_money_unknowns_and_separate_physics(width):
    from playwright.sync_api import expect
    with browser_page(width) as (page, responses, errors):
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsRows')).to_contain_text('197,8%')
        row = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(row).to_contain_text('1\u00a0000\u00a0000 ₽')
        expect(row.locator('.term')).to_contain_text('Нужен срок')
        from contract_rows import opened
        expect(page.locator(f'tr[data-contract-id="{OTHER}"]')).to_contain_text('выполнено 0 ₽')
        assert page.locator(f'tr[data-contract-id="{OTHER}"] .contract-main-money').all_text_contents() == ['—']
        other = opened(page, OTHER)
        expect(other.locator('#contractCardSummary [data-label="Сумма договора"]')).to_contain_text('Не подтверждена')
        expect(other.locator('[data-label="Выполнено по накопительным"]')).to_contain_text('0 ₽')
        expect(other).to_contain_text('Доля не рассчитана')
        opened(page, CONTRACT)
        page.locator('#contractPhysicalSources > summary').click()
        page.locator('.contract-chat-evidence > summary').click()
        expect(page.locator('#contractsDetails')).to_contain_text('35%')
        expect(page.locator('#contractsDetails')).to_contain_text('100 м²')
        expect(page.locator('#contractsDetails')).to_contain_text('не заменяет акт приёмки')
        expect(page.locator('#contractsDetails .contract-source').filter(has_text='Ежедневный отчёт')).to_contain_text('строка 1')
        expect(page.locator('#contractsDetails .contract-source').filter(has_text='Ежедневный отчёт')).not_to_contain_text('строка 2')
        assert page.locator('#contractsRows img, #contractsDetails img').count() == 0
        assert page.evaluate('window.untrustedRan') is None
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/monitor-contracts-{width}.png', full_page=True)
        page.locator('#contractDialogClose').click()
        page.locator('#contractsSearch').fill('Другой')
        expect(page.locator('#contractsRows')).not_to_contain_text('Д-01')
        expect(page.locator('#contractsRows')).to_contain_text('Д-02')
        assert not errors
        assert all(KEY not in url for _, _, url in responses.calls)


def test_archive_uses_one_admission_and_polls_without_executing_markup():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        page.locator('#dataTab').click()
        expect(page.locator('#setupCard')).to_be_visible()
        expect(page.locator('#setupCard')).to_have_class('card setup-card open')
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('Ведомость.xlsx', b'synthetic-only')
        page.locator('#cumulativeFile').set_input_files({'name': 'Накопительные.zip', 'mimeType': 'application/zip', 'buffer': data.getvalue()})
        page.locator('#cumulativeUpload').click()
        expect(page.locator('#cumulativeMsg')).to_contain_text('Архив обработан', timeout=10000)
        expect(page.locator('#cumulativeProtocol')).to_contain_text(MARKER+'.xlsx')
        assert page.locator('#cumulativeProtocol img').count() == 0
        expect(page.locator('#cumulativeProtocol')).to_contain_text('Требуют проверки: 1')
        page.locator('#cumulativeProtocol summary').click()
        expect(page.locator('#cumulativeProtocol')).to_contain_text('строка 41')
        calls = [p for path, p, _ in responses.calls if path == '/monitor/cumulative/upload']
        assert len(calls) == 1
        assert calls[0]['project'] == 'Учебный проект'
        assert calls[0]['key'] == KEY
        assert calls[0]['filename'] == 'Накопительные.zip'
        assert calls[0]['taken_at']
        assert not errors


def test_429_keeps_same_nonce_and_stale_project_cannot_render():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        responses.reject_build_once = True
        responses.pending_projects.add('Учебный проект')
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_contain_text('Сервер занят')
        expect(page.locator('#contractsMsg')).to_contain_text('Обрабатываю данные', timeout=6000)
        admissions = [p for path, p, _ in responses.calls if path == '/monitor/contracts/build']
        assert len(admissions) == 2
        assert admissions[0]['ticket'] == admissions[1]['ticket']
        page.locator('#project').fill('Другой проект')
        expect(page.locator('#contractsRows')).to_contain_text('Подрядчик Другой проект', timeout=10000)
        responses.pending_projects.clear()
        page.wait_for_timeout(1200)
        expect(page.locator('#contractsRows')).not_to_contain_text('Подрядчик Учебный проект')
        assert not errors


def test_term_and_each_evidence_link_require_explicit_actions():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        page.locator('#contractsTab').click()
        row = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        row.wait_for()
        assert responses.links == []
        from contract_rows import opened
        opened(page, CONTRACT).locator('.contract-term').click()
        assert page.locator('#contractsTermDate').input_value() == ''
        page.locator('#contractsTermDate').fill('2027-02-01')
        page.locator('#contractsTermNote').fill('Пункт 4.2 договора')
        page.locator('#contractsTermSave').click()
        expect(row).to_contain_text('01.02.2027', timeout=10000)
        assert len(responses.terms) == 1
        assert responses.terms[0]['contract_id'] == CONTRACT
        row.locator('.contract-open').click()
        page.locator('.contract-chat-evidence > summary').click()
        choice = page.locator('#contractsDetails .evidence-choice')
        assert choice.locator('select').input_value() == ''
        choice.locator('button').click()
        assert responses.links == []
        choice.locator('select').select_option(CONTRACT)
        choice.locator('button').click()
        expect(page.locator('#contractsDetails')).to_contain_text('Связь подтверждена', timeout=10000)
        assert len(responses.links) == 1
        assert responses.links[0]['evidence_id'] == 'evidence-01'
        assert responses.links[0]['confirmed'] is True
        page.locator('.contract-chat-evidence > summary').click()
        page.locator('#contractsDetails .evidence-remove').click()
        expect(page.locator('#contractsDetails')).to_contain_text('Предложен договор:', timeout=10000)
        assert len(responses.links) == 2
        assert responses.links[1]['confirmed'] is False
        assert not errors


def test_wrong_current_key_clears_private_lists_and_deep_link_has_no_key():
    from playwright.sync_api import expect
    with browser_page(hash_=f'#tab=contracts&project=Учебный%20проект&contract={CONTRACT}') as (page, responses, errors):
        expect(page.locator('#contractDialogTitle')).to_contain_text('Д-01', timeout=10000)
        page.locator('#contractDialogClose').click()
        responses.reject_key = True
        page.locator('#contractsRefresh').click()
        expect(page.locator('#privateArea')).to_be_hidden()
        assert page.locator('#contractsRows').text_content() == ''
        assert page.locator('#contractsDetails').text_content() == ''
        assert KEY not in page.url
        assert not errors


def test_failed_poll_does_not_restart_archive_upload():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        page.locator('#dataTab').click()
        expect(page.locator('#setupCard')).to_be_visible()
        expect(page.locator('#setupCard')).to_have_class('card setup-card open')
        page.locator('#cumulativeFile').set_input_files({'name': 'Снимок.zip', 'mimeType': 'application/zip', 'buffer': b'fake-zip'})
        responses.reject_poll = True
        page.locator('#cumulativeUpload').click()
        expect(page.locator('#cumulativeMsg')).to_have_class('msg bad', timeout=10000)
        assert len([1 for p, _, _ in responses.calls if p == '/monitor/cumulative/upload']) == 1
        assert not errors


def test_failed_archive_shows_each_file_status_and_keeps_previous_snapshot():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        page.locator('#dataTab').click()
        expect(page.locator('#setupCard')).to_be_visible()
        expect(page.locator('#setupCard')).to_have_class('card setup-card open')
        page.locator('#cumulativeFile').set_input_files({'name': 'Годный.zip', 'mimeType': 'application/zip', 'buffer': b'good-synthetic'})
        page.locator('#cumulativeUpload').click()
        expect(page.locator('#cumulativeMsg')).to_contain_text('Архив обработан', timeout=10000)
        expect(page.locator('#cumulativeProtocol')).to_contain_text('Годный.zip')
        expect(page.locator('#cumulativeHistory')).to_contain_text('Сохранённые снимки')
        previous_history = page.locator('#cumulativeHistory').text_content()
        responses.upload_failure = True
        page.locator('#cumulativeFile').set_input_files({'name': 'Ошибка.zip', 'mimeType': 'application/zip', 'buffer': b'bad-synthetic'})
        expect(page.locator('#cumulativeProtocol')).to_contain_text('Годный.zip')
        page.locator('#cumulativeUpload').click()
        expect(page.locator('#cumulativeMsg')).to_contain_text('Архив не сохранён', timeout=10000)
        protocol = page.locator('#cumulativeFailureProtocol')
        expect(protocol).to_contain_text('Прочитано: 1')
        expect(protocol).to_contain_text('Сопутствующие файлы: 1')
        expect(protocol).to_contain_text('Не прочитано: 2')
        expect(protocol).to_contain_text('Читаемый.xlsx — Прочитан')
        expect(protocol).to_contain_text('Примечания.txt — Сопутствующий файл')
        expect(protocol).to_contain_text(MARKER+'.xlsx — Ошибка разбора')
        expect(protocol).to_contain_text('Следующий.xlsx — Не прочитан')
        assert protocol.locator('img').count() == 0
        assert page.evaluate('window.untrustedRan') is None
        expect(page.locator('#cumulativeProtocol')).to_contain_text('Годный.zip')
        expect(page.locator('#cumulativeProtocol')).not_to_contain_text('Ошибка.zip')
        expect(page.locator('#cumulativeHistory')).to_have_text(previous_history)
        assert len([1 for path, _, _ in responses.calls if path == '/monitor/cumulative/upload']) == 2
        assert not errors


def test_undated_quantity_and_later_manual_deadline_are_only_references():
    from playwright.sync_api import expect
    with browser_page(390) as (page, responses, errors):
        data = responses.data['rows'][0]
        data['manual_deadline_reference'] = {'deadline': '2027-02-01', 'updated_at': '2026-11-10T10:00:00Z',
                                             'note': MARKER, 'applicable_to_cut': False}
        item = data['physical_items'][0]
        item.update(completed_quantity=None, material_quantity=None, completion_ratio=None,
                    quantity_date=None, quantity_basis='Накопительный итог без дат выполнения.',
                    snapshot_date='2026-11-06', reported_completed_quantity=50,
                    reported_material_quantity=80, reported_completion_ratio=.5,
                    reported_quantity_basis='Дата выполнения не подтверждена; не факт на дату среза.',
                    future_periods_excluded=False)
        page.locator('#contractsTab').click()
        row = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        row.wait_for()
        expect(row.locator('.term')).to_contain_text('Нужен срок')
        expect(row.locator('.term')).not_to_contain_text('01.02.2027')
        assert page.evaluate('document.querySelector("#contractsRows").scrollWidth <= document.querySelector("#contractsRows").clientWidth')
        row.locator('.contract-open').click()
        page.locator('#contractPhysicalSources > summary').click()
        page.locator('#contractRecordSources > summary').click()
        main = page.locator('.contract-physical .physical-main')
        expect(main.locator('td.numeric').nth(0)).to_have_text('100 м²')
        expect(main.locator('td.numeric').nth(1)).to_contain_text('50 м²')
        expect(main.locator('td.numeric').nth(2)).to_contain_text('80 м²')
        expect(main.locator('td.numeric').nth(3)).to_contain_text('50%')
        assert all('По ведомости' in cell for cell in main.locator('td.numeric').all_text_contents()[1:])
        expect(main.locator('.physical-source')).to_contain_text('Дата выполнения не подтверждена')
        expect(main.locator('.physical-source')).to_contain_text('Архив от 06.11.2026')
        expect(main.locator('.physical-source')).to_contain_text('не дата выполнения')
        assert page.locator('.physical-reference').count() == 0
        manual = page.locator('.manual-deadline-reference')
        expect(manual).to_contain_text('01.02.2027')
        expect(manual).to_contain_text('не подтверждает срок договора на выбранную дату среза')
        assert manual.locator('img').count() == 0
        from contract_rows import opened
        opened(page, CONTRACT).locator('.contract-term').click()
        assert page.locator('#contractsTermDate').input_value() == '2027-02-01'
        expect(page.locator('#contractsTermMsg')).to_contain_text('текущую ручную отметку')
        assert not errors


def test_dated_quantity_stays_at_cut_and_future_total_never_replaces_it():
    from playwright.sync_api import expect
    with browser_page(1440) as (page, responses, errors):
        item = responses.data['rows'][0]['physical_items'][0]
        item.update(completed_quantity=35, material_quantity=40, completion_ratio=.35,
                    quantity_date='2026-10-20', quantity_cut='2026-11-06',
                    quantity_basis='По датированным периодам, завершённым не позднее даты среза.',
                    snapshot_date='2026-11-06', future_periods_excluded=True,
                    warnings=['Выполнение периодов позже даты среза исключено.'],
                    reported_completed_quantity=100, reported_material_quantity=100,
                    reported_completion_ratio=1.0)
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractPhysicalSources > summary').click()
        main = page.locator('.contract-physical .physical-main')
        assert main.locator('td.numeric').all_text_contents() == ['100 м²', '35 м²', '40 м²', '35%']
        expect(main.locator('.physical-source')).to_contain_text('Последний учтённый период: 20.10.2026')
        expect(main.locator('.physical-source')).to_contain_text('Архив от 06.11.2026')
        expect(main.locator('.physical-source')).to_contain_text('позже даты среза исключено')
        assert page.locator('.physical-reference').count() == 0
        expect(page.locator('#contractsRows .contract-scroll-hint')).to_be_hidden()
        assert not errors
