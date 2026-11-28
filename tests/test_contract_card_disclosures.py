"""The actual Monitor card opens short and keeps independent native disclosures."""
import copy
import datetime as dt

import pytest
from playwright.sync_api import expect

from tests.test_contract_gpr_mobile_card_calendar import gpr_state
from tests.test_monitor_cumulative_controls import CONTRACT, browser_page


def card(preview=True):
    state = gpr_state(preview)
    # Daily ticks reproduce the skipped final date in a dense source calendar.
    start = dt.date(2026, 8, 1)
    presentation = (state.get('preview') or state)['presentation']
    presentation['ticks'] = [{'start': str(start + dt.timedelta(days=i)),
                              'finish': str(start + dt.timedelta(days=i)),
                              'label': (start + dt.timedelta(days=i)).strftime('%d.%m')}
                             for i in range(273)]
    state['workforce'] = {'available': True, 'contractor': 'Учебный подрядчик',
                          'company_rows': [{'date': '2026-11-27', 'workers': 4,
                                            'itr': 1, 'candidates': []}]}
    return {'ok': True, 'pending': False, 'documents': [], 'gpr': state,
            'gpr_export': {'schema': 'contract-gpr-performance-xlsx-v13',
                           'available': True, 'mode': 'preview' if preview else 'active',
                           'draft': preview, 'revision': 'd' * 64,
                           'filename': 'synthetic-draft.xlsx',
                           'detail': 'Черновик ГПР. Источник для расчёта ещё не выбран.'}}


def serve_card(page, value, calls):
    def documents(route):
        body = route.request.post_data_json
        calls.append((route.request.url.rsplit('/', 1)[-1], body))
        route.fulfill(json={**copy.deepcopy(value), 'ticket': body['ticket']})
    page.route('**/monitor/contracts/documents', documents)


def open_card(page):
    page.locator('#contractsTab').click()
    page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
    page.locator('#contractGprBody[aria-busy="false"]').wait_for(state='attached')


@pytest.mark.parametrize('width', [390, 440, 1440])
def test_independent_disclosures_visible_export_and_exact_terminal_date(width):
    value, calls = card(), []
    with browser_page(width) as (page, _, errors):
        serve_card(page, value, calls)
        open_card(page)
        sections = page.locator('#contractsDetails > details.contract-card-section')
        expect(sections).to_have_count(3)
        assert sections.locator(':scope > summary').all_text_contents() == [
            'ГПР · источник для расчёта не выбран', 'Выполнение', 'Численность']
        expect(page.locator('#contractsDetails > details.contract-card-section[open]')).to_have_count(0)
        expect(page.locator('.contract-gpr-scroll')).to_be_hidden()
        expect(page.locator('#contractComparison')).to_be_hidden()
        expect(page.locator('#contractWorkforceBody')).to_be_hidden()
        expect(page.locator('#contractCardSummary')).to_be_visible()
        export = page.locator('#contractGprDownload')
        expect(export).to_be_visible()
        expect(export).to_be_enabled()
        expect(export).to_contain_text('Скачать черновик')
        assert export.evaluate('(e)=>e.closest("details")===null')
        expect(page.locator('#contractsDetails button[id*="Export"],#contractsDetails #contractGprDownload')).to_have_count(1)
        # Source selection is discoverable while the chart is closed.
        page.locator('#contractGprChooseSource').click()
        expect(page.locator('#contractGpr')).to_have_attribute('open', '')
        expect(page.locator('.contract-gpr-source-selection')).to_have_attribute('open', '')
        expect(page.locator('[data-gpr-signed]')).not_to_be_checked()
        expect(page.locator('[data-gpr-activate]')).to_have_text('Использовать эту редакцию для расчёта')
        assert all(path == 'documents' for path, _ in calls)
        expect(page.locator('.contract-gpr-period')).to_have_text('Период исходного ГПР: 01.08.2026 — 30.04.2027.')
        expect(page.locator('.contract-gpr-terminal-tick')).to_have_text('30.04.2027')
        first = page.locator('[data-track="source-plan"]').first
        bar = first.locator('rect[fill="#D9D9D9"]')
        assert float(bar.get_attribute('x')) == 0
        assert float(bar.get_attribute('width')) == 1000
        assert first.evaluate('(e)=>e.getBoundingClientRect().right<=e.closest(".contract-gpr-scroll").getBoundingClientRect().right+1')
        # Native keyboard controls preserve sibling state.
        page.locator('#contractExecution > summary').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#contractComparison')).to_be_visible()
        expect(page.locator('#contractGpr')).to_have_attribute('open', '')
        page.locator('#contractWorkforce > summary').focus()
        page.keyboard.press('Space')
        expect(page.locator('.contract-company-workforce')).to_be_visible()
        assert page.locator('#contractWorkforceBody .contract-gpr-scroll').count() == 0
        assert page.locator('#contractGprBody .contract-gpr-staff').count() == 0
        page.evaluate('loadContractDocuments(contractDocumentsState.id)')
        page.wait_for_function('contractGprExport?.ticket && !document.getElementById("contractGprDownload").disabled')
        expect(page.locator('#contractsDetails > details.contract-card-section[open]')).to_have_count(3)
        expect(page.locator('.contract-gpr-source-selection')).to_have_attribute('open', '')
        page.locator('#contractGpr > summary').click()
        expect(page.locator('.contract-gpr-scroll')).to_be_hidden()
        expect(page.locator('.contract-company-workforce')).to_be_visible()
        expect(export).to_be_visible()
        page.locator('#contractDialogClose').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractGprBody[aria-busy="false"]').wait_for(state='attached')
        expect(page.locator('#contractsDetails > details.contract-card-section[open]')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert errors == []


@pytest.mark.parametrize('mutation', ['unavailable', 'old_schema', 'active_without_source', 'not_draft', 'unknown_mode'])
def test_preview_export_needs_current_explicit_backend_metadata(mutation):
    value, calls = card(), []
    changes = {'unavailable': {'available': False}, 'old_schema': {'schema': 'contract-gpr-performance-xlsx-v12'},
               'active_without_source': {'mode': 'active', 'draft': False}, 'not_draft': {'draft': False},
               'unknown_mode': {'mode': 'unknown'}}
    value['gpr_export'].update(changes[mutation])
    with browser_page(390) as (page, _, errors):
        serve_card(page, value, calls)
        export_calls = []
        page.route('**/monitor/contracts/gpr.xlsx', lambda route: (export_calls.append(route.request.url), route.abort()))
        open_card(page)
        expect(page.locator('#contractGprDownload')).to_be_disabled()
        page.evaluate('exportContractGpr()')
        assert export_calls == [] and errors == []


def test_preview_download_does_not_select_source_and_has_one_request():
    value, calls = card(), []
    with browser_page(440) as (page, _, errors):
        serve_card(page, value, calls)
        downloads = []
        def download(route):
            body = route.request.post_data_json
            downloads.append(body)
            route.fulfill(body=b'PK synthetic workbook transport', content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        page.route('**/monitor/contracts/gpr.xlsx', download)
        open_card(page)
        with page.expect_download() as result:
            page.locator('#contractGprDownload').click()
        assert result.value.suggested_filename == 'synthetic-draft.xlsx'
        assert len(downloads) == 1
        assert not {'rows', 'planned', 'fact', 'filter', 'query'} & downloads[0].keys()
        assert page.evaluate('contractGprState.source') is None
        assert page.evaluate('contractGprState.preview.source.sha256') == value['gpr']['preview']['source']['sha256']
        assert all(path == 'documents' for path, _ in calls)
        assert errors == []


def test_rds_schedule_text_uses_typed_server_assessments_without_changing_quantities():
    value, calls = card(False), []
    current = 'Срок прошёл 28 дн.; завершение по КС не подтверждено'
    finish = 'Дата не определена: нет подтверждённого темпа'
    delay = 'Не менее 28 дн. по закрытию КС'
    row = {'estimate': 0, 'index': 1, 'number': '1.1', 'name': 'Учебная работа', 'unit': 'м²',
           'contract_quantity': 100, 'plan_quantity': 100, 'fact_quantity': 0,
           'fact_quantity_ratio': 0, 'quantity_deviation': -100, 'day_deviation': -25,
           'finish': '2026-10-09', 'schedule_reporting': {
               'schema': 'rds-schedule-reporting-v1',
               'current': {'kind': 'gpr_deadline_elapsed_unconfirmed', 'text': current,
                           'basis': 'Это срок по ГПР, а не измеренное физическое отставание.'},
               'finish': {'kind': 'unknown', 'text': finish, 'basis': 'КС не подтверждают темп.'},
               'delay': {'kind': 'ks_closure_lower_bound', 'text': delay,
                         'basis': 'Это период без полного закрытия КС, а не доказанный физический срок.'}}}
    value['rds_comparison'] = {'available': True, 'layout': 'rds-plan-fact-v3',
                               'cut': '2026-11-06', 'rows': [row]}
    with browser_page(390) as (page, _, errors):
        serve_card(page, value, calls)
        page.locator('#cut').fill('2026-11-06')
        open_card(page)
        page.locator('#contractExecution > summary').click()
        shown = page.locator('#contractComparisonRows [data-rds-position="0:1"]')
        expect(shown.locator('[data-label="Факт по загруженным КС"]')).to_contain_text('0 м²')
        expect(shown.locator('[data-label="Отклонение"]')).to_contain_text(current)
        expect(shown.locator('[data-label="Отклонение"]')).not_to_contain_text('Сдвиг к плану')
        expect(shown.locator('[data-label="Прогноз окончания"]')).to_contain_text(finish)
        expect(shown.locator('[data-label="Прогноз окончания"]')).to_contain_text(delay)
        shown.locator('[data-schedule-kind="ks_closure_lower_bound"] > details > summary').click()
        expect(shown).to_contain_text('а не доказанный физический срок')
        assert row['day_deviation'] == -25 and row['fact_quantity'] == 0
        assert not errors
