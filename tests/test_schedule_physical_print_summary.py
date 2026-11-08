"""Real GPR/natural sources retain quantities and dates in the executive/A4 report."""
import copy
import datetime as dt
import io

import pytest
from openpyxl import load_workbook

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_schedule_gpr_physical as physical
import developaid_schedule_timeline as timeline
from test_monitor_cumulative_ledgers import archive, book
from test_monitor_management_gantt import _gpr_book

CUT = '2026-11-06'
PROJECT = 'Учебный проект'


@pytest.fixture
def gpr_sources(tmp_path, monkeypatch):
    """Save real books, archive and explicit source-bound mapping; no PM/RSS."""
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc))
    import developaid_monitor_page  # noqa: F401 — actual production overlays

    def build(scenario='confirmed', *, view=False):
        monitor.store_schedule(PROJECT, _gpr_book([
            (1, 'Монтаж корпуса 1', .8, dt.date(2026, 9, 1), dt.date(2026, 10, 31),
             'В работе', '2.2.1.1')]), None, '2026-10-01')
        workbook = load_workbook(io.BytesIO(book()))
        sheet = workbook.active
        sheet['D9'], sheet['E9'], sheet['H9'], sheet['K9'], sheet['N9'] = 'м2', 100, 25, 25, 50
        if scenario != 'stale':
            sheet['H7'] = 'Выполнение № 1 (01.09.2026 - 30.09.2026)'
            sheet['K7'] = 'Выполнение № 2 (01.10.2026 - 31.10.2026)'
        output = io.BytesIO()
        workbook.save(output)
        ledgers.store_archive(PROJECT, archive([('Натуральный монтаж.xlsx', output.getvalue())]),
                              '2026-11-01', 'Учебный архив.zip')
        state = physical.catalog(PROJECT, CUT)
        physical.save(PROJECT, **{key: state[key] for key in (
            'source_kind', 'source_sha256', 'snapshot_id', 'revision')}, configuration={
                'tasks': [{'task_id': '1', 'mode': 'quantities',
                           'scope_confirmed': scenario != 'unconfirmed', 'actual_finish': ''}],
                'components': [{'component_id': 'Монтаж корпуса 1', 'task_id': '1', 'item_ids': ['0:0']}],
                'note': 'Проверены работа, корпус, единица и полный объём.'})
        # An unconfirmed relationship must not erase the original archive or
        # pretend that its quantities are already confirmed for the GPR work.
        catalog = physical.catalog(PROJECT, CUT)
        assert catalog['items'][0]['completed_quantity'] == 50
        assert catalog['items'][0]['plan_quantity'] == 100
        assert catalog['source_kind'] == 'gpr' and catalog['recorded_at'].startswith(CUT)
        if view:
            return monitor.build(PROJECT, CUT)
        result = report.build(PROJECT, 'week', CUT)
        model = result['gantt']['dependency_timeline']['physical']
        assert model['source_kind'] == 'gpr' and model['snapshot_id'] == catalog['snapshot_id']
        assert result['schedule']['qualification']['basis'] == 'gpr'
        assert result['schedule']['qualification']['forecast'] is None or scenario == 'confirmed'
        return result

    return build


@pytest.mark.parametrize('scenario', ['confirmed', 'stale', 'unconfirmed'])
@pytest.mark.parametrize('width', [390, 1440])
def test_actual_report_keeps_quantities_visible_without_approving_unknown_scope(width, scenario, gpr_sources):
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    data = gpr_sources(scenario)
    before = copy.deepcopy(data)
    markup = report.render_html(data)
    assert data == before
    summary = data['construction_summary']
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page = engine.new_page(viewport={'width': width, 'height': 1000})
        page.route('**/*', lambda route: route.abort())
        page.set_content(markup)
        section = page.locator('.executive-schedule')
        expect(section).to_be_visible()
        if summary['source_status']['state'] != 'confirmed':
            expect(section).to_contain_text(summary['source_status']['reason'])
        assert section.locator('details').count() == 0
        assert section.evaluate('(e)=>e.getBoundingClientRect().width <= innerWidth')
        assert page.locator('.schedule-confirmation-summary').count() == 0
        if scenario == 'unconfirmed':
            assert summary['source_status']['state'] == 'unconfirmed'
            assert summary['facts'] == []
            assert section.locator('.executive-facts').count() == 0
            assert data['gantt']['dependency_timeline']['physical']['tasks'][0]['progress'] is None
        else:
            fact = section.locator('.executive-facts')
            expect(fact).to_be_visible()
            expect(fact).to_contain_text('50 из 100 м²')
            expect(fact).to_contain_text('28.02.2026' if scenario == 'stale' else '31.10.2026')
            assert fact.locator('li').count() == 1
            assert fact.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') >= 12
            assert summary['facts'][0]['done'] == 50 and summary['facts'][0]['plan'] == 100
            assert data['gantt']['dependency_timeline']['physical']['tasks'][0]['progress'] == .5
        if scenario != 'confirmed':
            assert summary['forecast'] is None
            expect(section.locator('.schedule-rnv-cards')).to_contain_text('Не определена')
        else:
            assert summary['state'] == 'estimate'
            expect(section).to_contain_text('Оценка окончания работ')
            expect(section).to_contain_text('не подтверждает дату получения разрешения на ввод')
        engine.close()


@pytest.mark.parametrize('scenario', ['confirmed', 'stale', 'unconfirmed'])
def test_quantities_and_source_dates_remain_in_real_pdf_without_raw_network(scenario, gpr_sources):
    import fitz
    from playwright.sync_api import sync_playwright
    from browser import chromium_or_skip
    data = gpr_sources(scenario)
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page = engine.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content(report.render_html(data))
        content = page.pdf(format='A4')
        engine.close()
    with fitz.open(stream=content, filetype='pdf') as pdf:
        text = ' '.join(' '.join(page.get_text() for page in pdf).split())
    assert 'Сроки и выполнение работ' in text and '06.11.2026' in text
    assert '31.10.2026' in text  # the approved GPR date survives qualification
    main = text.split('Приложение. Источники и ограничения оценки', 1)[0]
    if scenario == 'unconfirmed':
        assert '50 из 100 м²' not in main
        assert data['construction_summary']['source_status']['reason'] in main
    else:
        assert '50 из 100 м²' in main
        assert ('28.02.2026' if scenario == 'stale' else '31.10.2026') in main
    if scenario != 'confirmed':
        assert 'Не определена' in main and data['construction_summary']['forecast'] is None
    assert 'Все работы исходной сети' not in text


def test_legacy_confirmation_note_is_escaped_without_promoting_a_revocation(gpr_sources):
    data = gpr_sources('unconfirmed')
    block = data['gantt']['dependency_timeline']
    block['confirmation'] = {'recorded_at': '2026-11-06T12:00:00+00:00',
                             'calendar_basis': 'unconfirmed', 'rnv_chain_complete': False,
                             'note': '<img src=x onerror=alert(1)> Проверка отозвана.'}
    before = copy.deepcopy(data)
    # Legacy opt-in rendering remains safe, while PM confirmation is not a
    # source for the normal GPR executive report.
    markup = timeline.render(block, context='monitor')
    summary = markup.split('<div class="schedule-confirmation-summary">', 1)[1].split('</div>', 1)[0]
    assert '06.11.2026' in summary and 'Проверка отозвана.' in summary
    assert 'Календарь не подтверждён.' in summary
    assert 'Полнота цепочки до РНВ не подтверждена.' in summary
    assert '&lt;img' in summary and '<img' not in summary and '<details' not in summary
    assert 'Проверка отозвана.' not in report.render_html(data)
    assert data == before and data['construction_summary']['forecast'] is None
