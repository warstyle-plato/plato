"""The real PAGE keeps covered KS facts separate from whole-package GPR."""
from __future__ import annotations

import copy
import io

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader
from browser import open_ks_calculation
from test_gpr_source_groups_ui import view
from test_monitor_cumulative_controls import browser_page, MARKER


def covered_view(known=True):
    result = view()
    result['schedule']['physical_progress'] = {'tasks': [], 'covered_source_groups': [{
        'group_id': 'covered-source', 'source_name': 'Монтаж элементов', 'source_scope': 'Корпус 1, этажи 3–4',
        'contractor': 'Учебный подрядчик', 'contract': 'Учебный договор', 'period_year': 2026,
        'target_scope_confirmed': False, 'candidate_task_ids': ['3', '4'],
        'scope_reason': 'Выполнение относится только к указанному разделу КС. Полнота всего пакета ГПР не подтверждена.',
        'coverage': {'source_positions': 2, 'known_positions': 2, 'target_scope_confirmed': False},
        'model': {'progress': .6 if known else None, 'progress_date': '2026-11-06',
                  'reason': '' if known else 'Не подтверждены полные веса СМР.',
                  'components': [{'name': 'Стены', 'progress': .4, 'unit': 'м³', 'completed_quantity': 4, 'plan_quantity': 10},
                                 {'name': 'Перекрытия', 'progress': .8, 'unit': 'м³', 'completed_quantity': 8, 'plan_quantity': 10}]}}]}
    return result


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('known', [True, False])
def test_covered_source_percent_and_components_do_not_become_individual_gpr_percent(width, known):
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', covered_view(known))
        expect(page.locator('#ksSharedBox > summary')).to_have_text('Как посчитан процент выполнения (по КС)')
        open_ks_calculation(page)
        host = page.locator('#ksSharedGroups')
        expect(host.locator('.ks-covered-source')).to_have_count(1)
        expect(host.locator('.ks-source-group')).to_have_count(0)
        expect(host.locator('.contract-main-money')).to_have_text('60%' if known else '—')
        expect(host).to_contain_text('Полнота всего пакета ГПР не подтверждена')
        expect(host).to_contain_text('Известен объём 2 из 2 позиций раздела')
        assert '60%' not in page.locator('#gantt').inner_text()
        host.locator('summary').click()
        expect(host).to_contain_text('Стены: 40%')
        expect(host).to_contain_text('Перекрытия: 80%')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            text = ' '.join((s.extract_text() or '') for s in PdfReader(io.BytesIO(page.pdf())).pages)
            assert 'Выполнение охваченных разделов КС' in text and 'Полнота всего пакета ГПР' in text
        assert not errors


def test_collapsed_ks_calculation_still_prints_and_stays_collapsed_after_printing():
    with browser_page(1440) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', covered_view())
        box = page.locator('#ksSharedBox')
        assert box.get_attribute('open') is None
        # Блок стоит под графиком, а не над ним.
        assert page.evaluate("!!($('gantt').compareDocumentPosition($('ksSharedBox'))&Node.DOCUMENT_POSITION_FOLLOWING)")
        text = ' '.join((s.extract_text() or '') for s in PdfReader(io.BytesIO(page.pdf())).pages)
        assert 'Как посчитан процент выполнения' in text and 'Полнота всего пакета ГПР' in text
        assert box.get_attribute('open') is None
        assert not errors


def test_source_text_is_escaped_and_replacing_project_clears_covered_facts():
    with browser_page(390) as (page, responses, errors):
        value = covered_view()
        group = value['schedule']['physical_progress']['covered_source_groups'][0]
        group.update(source_name=MARKER, source_scope=MARKER, scope_reason=MARKER)
        group['model']['components'][0]['name'] = MARKER
        page.evaluate('(v)=>renderGantt(v)', value)
        host = page.locator('#ksSharedGroups')
        expect(host).to_contain_text(MARKER)
        assert host.locator('img').count() == 0 and not page.evaluate('window.untrustedRan===true')
        next_view = copy.deepcopy(value)
        next_view['schedule']['physical_progress'] = {}
        page.evaluate('(v)=>renderGantt(v)', next_view)
        expect(host).to_be_hidden()
        expect(page.locator('#ksSharedBox')).to_be_hidden()
        assert host.inner_text() == '' and not errors


def test_many_source_groups_keep_the_gpr_chart_accessible_and_expand_without_duplicating():
    with browser_page(390) as (page, responses, errors):
        value = covered_view()
        groups = value['schedule']['physical_progress']['covered_source_groups']
        base = groups[0]
        groups[:] = [dict(copy.deepcopy(base), group_id=f'group-{i}', source_name=f'Раздел {i}') for i in range(7)]
        page.evaluate('(v)=>renderGantt(v)', value)
        open_ks_calculation(page)
        host = page.locator('#ksSharedGroups')
        expect(host.locator('.ks-covered-source')).to_have_count(7)
        assert host.locator('.ks-covered-source:visible').count() == 3
        expect(host.locator('.ks-covered-more > summary')).to_have_text('Ещё разделов КС: 4')
        host.locator('.ks-covered-more > summary').click()
        assert host.locator('.ks-covered-source:visible').count() == 7
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_executive_render_and_pdf_name_covered_scope_and_construction_plan(width):
    import developaid_report_schedule as report
    with browser_page(width) as (page, responses, errors):
        physical = covered_view()['schedule']['physical_progress']
        timeline = {'rnv': {'state': 'partial', 'basis': 'gpr', 'approved': None,
            'planned_construction_finish': '2027-02-01', 'plan_date': '2027-02-01',
            'plan_label': 'План окончания работ', 'indicative_forecast': '2027-01-15'},
            'physical': physical}
        summary = report.model(timeline)
        page.set_content(report.render(summary)+report.details(summary))
        expect(page.locator('.schedule-rnv-cards > div:first-child > span')).to_have_text('План окончания работ')
        expect(page.locator('.schedule-rnv-cards > div:first-child > strong')).to_have_text('01.02.2027')
        expect(page.locator('.executive-facts')).to_contain_text('60% по объёмам охваченного раздела КС')
        expect(page.locator('.executive-facts')).to_contain_text('Полнота всего пакета ГПР не подтверждена')
        assert 'План ввода' not in page.locator('body').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            text = ' '.join((s.extract_text() or '') for s in PdfReader(io.BytesIO(page.pdf())).pages)
            assert 'План окончания работ' in text and '01.02.2027' in text
            assert '60%' in text and 'охваченного раздела КС' in text
        assert not errors


def full_server_view(tmp_path, monkeypatch, *, no_calendar=False):
    """Actual imports and Monitor, including its complete server timeline HTML."""
    from openpyxl import load_workbook
    import developaid_monitor as monitor
    import developaid_monitor_ledgers as ledgers
    from test_gpr_corpus_baseline import construction_book
    from test_monitor_cumulative_ledgers import archive, book
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'isolated-monitor')
    project = 'Учебный полный серверный ГПР'
    gpr_data = construction_book()
    if no_calendar:
        gpr = load_workbook(io.BytesIO(gpr_data))
        for row in (5, 6):
            for col in (6, 7, 9, 10, 12, 13):
                gpr['ГПР'].cell(row, col).value = None
        output = io.BytesIO(); gpr.save(output); gpr_data = output.getvalue()
    monitor.store_schedule(project, gpr_data, None, '2026-11-09')
    wb = load_workbook(io.BytesIO(book()))
    ws = wb.active
    ws.insert_rows(9, 2)
    ws['B9'], ws['C9'] = '-', 'Корпус 1 этажи 2–3'
    ws['B10'], ws['C10'] = '1', 'Устройство отделки фасадов (вертикальная часть)'
    data = io.BytesIO(); wb.save(data)
    ledgers.store_archive(project, archive([('Учебные объёмы.xlsx', data.getvalue())]),
                          '2026-11-09', 'Учебный архив.zip')
    return monitor.build(project, '2026-11-09')


@pytest.mark.parametrize('width', [390, 1440])
def test_full_monitor_build_has_one_covered_card_owner_and_preserves_report_sources(tmp_path, monkeypatch, width):
    import developaid_report_schedule as report
    import developaid_schedule_visual as visual
    value = full_server_view(tmp_path, monkeypatch)
    schedule = value['schedule']
    physical = schedule['physical_progress']
    count = len(physical['covered_source_groups'])
    assert count == 1
    assert schedule['dependency_timeline_html']  # this HTML used to supply a second complete grid
    assert 'ks-covered-source' not in schedule['dependency_timeline_html']
    assert visual.physical_summary(physical).count('ks-covered-source') == count
    summary = report.model(schedule['dependency_timeline'])
    assert summary['facts'] and all(f['source_scope_only'] for f in summary['facts'])
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', value)
        expect(page.locator('.ks-covered-source')).to_have_count(count)
        expect(page.locator('#ksSharedGroups .ks-covered-source')).to_have_count(count)
        expect(page.locator('#dependencyTimelineBody .ks-covered-source')).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            page.set_content(report.render(summary)+report.details(summary))
            text = ' '.join((s.extract_text() or '') for s in PdfReader(io.BytesIO(page.pdf())).pages)
            assert 'охваченная часть КС' in text and 'полный пакет ГПР не подтверждён' in text
        assert not errors


def test_covered_facts_remain_visible_when_the_source_has_no_calendar_dates(tmp_path, monkeypatch):
    value = full_server_view(tmp_path, monkeypatch, no_calendar=True)
    assert value['schedule']['rows'] == [] and value['schedule']['management'] == []
    assert len(value['schedule']['physical_progress']['covered_source_groups']) == 1
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', value)
        expect(page.locator('#ganttCard')).to_be_visible()
        expect(page.locator('.ks-covered-source')).to_have_count(1)
        # Без календаря график пуст: расчёт по КС — единственное содержание, он раскрыт сразу.
        assert page.locator('#ksSharedBox').get_attribute('open') is not None
        expect(page.locator('.ks-covered-source')).to_be_visible()
        expect(page.locator('#gprEmptyText')).to_contain_text('нет полных плановых дат')
        assert page.locator('#gantt').inner_text() == ''
        assert not errors
