"""The real PAGE keeps covered KS facts separate from whole-package GPR."""
from __future__ import annotations

import copy
import io

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader
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
        assert host.inner_text() == '' and not errors
