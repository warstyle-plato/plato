"""Actual Monitor script and shared server markup at phone/desktop sizes."""
import pytest

import developaid_gpr_corpus as corpus
import developaid_schedule_timeline as timeline
from test_gpr_corpus_preview import book
from test_schedule_dependency_timeline import day, network
from test_monitor_cumulative_controls import browser_page


@pytest.mark.parametrize('width', [390, 1440])
def test_real_monitor_shows_inherited_delay_rnv_qualification_and_source(width):
    from playwright.sync_api import expect
    pm = network()
    pm.pop('calendar_confirmed')
    block = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    source = corpus.read(book(name='Монтаж фасада'))
    view = {'schedule': {'management': [], 'dependency_timeline': block,
                        'dependency_timeline_html': timeline.render(block),
                        'corpus_gpr': source, 'corpus_gpr_html': corpus.render_overview(source, '2026-11-06')},
            'dashboard': {'schedule': {'qualified_rnv': block['rnv']}}}
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(view)=>{++corpusSourceRequest;currentView=view;renderGantt(view);renderDash(view);renderCorpusGprSource({html:view.schedule.corpus_gpr_html})}', view)
        expect(page.locator('#dependencyTimelineCard')).to_be_visible()
        expect(page.locator('#dependencyTimelineBody .schedule-rnv-cards')).to_contain_text('Прогноз РНВ')
        expect(page.locator('#dependencyTimelineBody .schedule-rnv-cards')).to_contain_text('неполный')
        # Owner's decision: no dependency drawing; the RNV cards stay.
        assert page.locator('#dependencyTimelineBody .schedule-lane').count() == 0
        assert page.locator('#dependencyTimelineBody svg path[marker-end]').count() == 0
        assert page.locator('#dependencyTimelineBody .schedule-technical').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.locator('#corpusGprCard')).to_be_visible()
        page.locator('#corpusGprBody .schedule-source-packages>summary').click()
        page.locator('#corpusGprBody .corpus-gpr-source details>summary').click()
        expect(page.locator('#corpusGprBody')).to_contain_text('31.06.2027')
        expect(page.locator('#corpusGprBody')).to_contain_text('нет числа')
        assert page.locator('#corpusGprBody script').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        page.screenshot(path=f'/tmp/gpr-rnv-monitor-{width}.png', full_page=True)


def test_stale_source_response_and_logout_cannot_restore_private_preview():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        held = []
        def handle(route):
            held.append(route)
        page.route('**/monitor/gpr-corpus/view', handle)
        with page.expect_request('**/monitor/gpr-corpus/view'):
            page.evaluate('void loadCorpusGprSource()')
        page.evaluate("document.getElementById('project').value='Другой проект';renderCorpusGprSource({html:'<p>Новая версия</p>'})")
        held[0].fulfill(json={'html': '<p>Старые данные другого проекта</p>'})
        expect(page.locator('#corpusGprBody')).to_contain_text('Новая версия')
        expect(page.locator('#corpusGprBody')).not_to_contain_text('Старые данные')
        page.evaluate("localStorage.removeItem('plato_projects_key');syncAuthUi()")
        assert page.locator('#corpusGprBody').text_content() == ''
        expect(page.locator('#corpusGprCard')).to_be_hidden()
        assert not errors
