import pytest
from playwright.sync_api import expect
from test_gpr_why_page import why_view, serve, show
from test_monitor_cumulative_controls import browser_page


@pytest.mark.parametrize('width',[390,1440])
def test_legend_and_conditional_strips_are_next_to_the_collapsed_corpus_gantt(monkeypatch, tmp_path, width):
    view = why_view()
    finish = view['schedule']['readiness']['project']['forecast']['finish']
    serve(monkeypatch, view)
    with browser_page(width) as (page, _, errors):
        show(page, view)
        assert page.locator('#ganttCard > .head .legend').count() == 0
        expect(page.locator('#ganttLegend')).to_be_hidden()
        overview = page.locator('#gprCalendarOverview .gpr-forecast-strip.conditional')
        expect(overview).to_have_attribute('data-finish',finish)
        page.locator('#gprCalendar > summary').click()
        expect(page.locator('#ganttLegend')).to_be_visible()
        assert page.evaluate('$("ganttLegend").compareDocumentPosition($("gantt"))&Node.DOCUMENT_POSITION_FOLLOWING')
        corpus = page.locator('#gantt .lvl-corpus').filter(has_text='Корпус Север')
        expect(corpus.locator('.gpr-forecast-strip.conditional')).to_have_attribute('data-finish',finish)
        expect(corpus.locator('.m-main')).to_contain_text('Условное окончание')
        assert page.locator('#gantt .lvl-task').count() == 0
        corpus.click()
        expect(page.locator('#detailGrid')).to_contain_text('Условное окончание работ')
        expect(page.locator('#detailGrid')).to_contain_text('19.04.2034')
        stage = page.locator('#gantt .lvl-stage').filter(has=page.locator('.gpr-forecast-strip.conditional')).first
        expect(stage.locator('.gpr-forecast-end')).to_have_attribute('data-finish',finish)
        page.screenshot(path=str(tmp_path/f'monitor-group-forecast-{width}.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_outside_legacy_finish_never_reappears_in_the_selected_detail_panel(monkeypatch):
    view = why_view()
    for row in [*view['schedule']['rows'], *view['schedule']['management'][0]['children'][0]['children'][0]['children']]:
        if row['id']=='why-3':
            row.update(forecast_known=True, pace_forecast_known=True, forecast_finish='2099-12-31',delta_days=999,delay_reason={'delay_days':999,'text':'Чужая причина из другого состава'})
    serve(monkeypatch, view)
    with browser_page(1440) as (page, _, errors):
        show(page, view)
        page.locator('#gprCalendar > summary').click()
        page.locator('#ganttExpand').click()
        page.locator('#gantt [data-work-id="why-3"]').click()
        detail = page.locator('#detailGrid')
        expect(detail).not_to_contain_text('2099')
        expect(page.locator('#detailCard')).not_to_contain_text('999 дн')
        expect(page.locator('#detailWhy')).not_to_contain_text('Чужая причина')
        assert not errors
