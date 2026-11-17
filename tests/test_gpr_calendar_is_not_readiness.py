"""The rendered work matrix keeps dates without a made-up volume percentage."""
import copy

import pytest
from playwright.sync_api import expect

from test_monitor_cumulative_controls import browser_page
from test_gpr_readable_matrix import matrix_view, serve_view, settled


@pytest.mark.parametrize('width', [390, 1440])
def test_elapsed_calendar_share_is_not_displayed_as_planned_readiness(monkeypatch, width):
    view = matrix_view(1)
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    task = next(row for row in tasks if row['object'] == 'Корпус 3')
    task.update(source_format='corpus-gpr-v1', name='Учебный навесной фасад',
                plan_start='2031-03-12', plan_finish='2032-10-09', plan_progress=.501,
                actual_progress=0, display_progress={'value': 0, 'label': 'Выполнено по ГПР',
                                                     'date': '2031-06-10'})
    before = copy.deepcopy(view)
    serve_view(monkeypatch, view)
    with browser_page(width) as (page, _, errors):
        settled(page, view)
        cell = page.locator('#gprFactMatrix [data-work-id="Корпус 3-0"]')
        expect(cell.locator('b')).to_have_text('0%')
        expect(cell.locator('.gpr-cell-plan')).to_have_text('План: 12.03.2031 — 09.10.2032')
        expect(cell).not_to_contain_text('50,1%')
        expect(cell).not_to_contain_text('Δ')
        expect(cell).not_to_contain_text('п.п.')
        expect(cell).to_have_attribute('data-calendar-fraction', '0.501')
        assert 'не определяет плановую готовность по объёму работ' in cell.get_attribute('title')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors and view == before
