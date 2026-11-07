"""Natural quantities stay visible in the compact report and its A4 output."""
import copy
import io

import pytest

import developaid_management_report as report
import developaid_schedule_physical as physical
import developaid_schedule_timeline as timeline
from test_schedule_dependency_timeline import network, day
from test_schedule_physical import snapshot, config, CUT


def payload(partial=False):
    pm, cfg = network(), config()
    if partial:
        cfg['tasks'][0]['scope_confirmed'] = False
    model = physical.evaluate(pm, snapshot(), cfg, CUT)
    block = timeline.model(pm, {key: day(value) for key, value in model['seeds'].items()},
                           evidence=model['physical_evidence'])
    block['physical'] = model
    return {'project': 'Учебный проект', 'kind': 'week', 'start': '2026-11-01', 'end': CUT,
            'gantt': {'state': 'missing', 'dependency_timeline': block}}


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('width', [390, 1440])
def test_actual_report_keeps_quantities_visible_without_approving_unknown_scope(width, partial):
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    data = payload(partial)
    before = copy.deepcopy(data)
    markup = report.render_html(data)
    assert data == before
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page = engine.new_page(viewport={'width': width, 'height': 1000})
        page.route('**/*', lambda route: route.abort())
        page.set_content(markup)
        section = page.locator('.schedule-physical-summary')
        expect(section).to_be_visible()
        expect(section).to_contain_text('50 / 100 м²')
        expect(section).to_contain_text('Доля полного объёма компонента: 50%')
        assert page.locator('.schedule-physical-item').count() == 1
        assert section.evaluate('(e)=>e.querySelectorAll("details").length') == 0
        assert section.locator('.schedule-physical-value').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') >= 12
        assert section.evaluate('(e)=>e.getBoundingClientRect().width <= innerWidth')
        if partial:
            expect(section).to_contain_text('Состав работы и основание прогноза не подтверждены')
            expect(section).not_to_contain_text('Расчётное окончание компонента')
            expect(page.locator('.schedule-rnv-cards')).to_contain_text('недостаточно данных')
        engine.close()


def test_partial_quantities_remain_in_real_pdf_without_raw_network():
    import fitz
    from playwright.sync_api import sync_playwright
    from browser import chromium_or_skip
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page = engine.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content(report.render_html(payload(True)))
        content = page.pdf(format='A4')
        engine.close()
    with fitz.open(stream=content, filetype='pdf') as pdf:
        text = ' '.join(' '.join(page.get_text() for page in pdf).split())
    assert 'Физическое выполнение' in text and '50 / 100 м²' in text
    assert 'Состав работы и основание прогноза не подтверждены' in text
    assert 'недостаточно данных' in text
    assert 'Все работы исходной сети' not in text


def test_confirmation_note_stays_visible_and_escaped_without_promoting_a_revocation():
    data = payload(True)
    block = data['gantt']['dependency_timeline']
    block['confirmation'] = {'recorded_at': '2026-11-06T12:00:00+00:00',
                             'calendar_basis': 'unconfirmed', 'rnv_chain_complete': False,
                             'note': '<img src=x onerror=alert(1)> Проверка отозвана.'}
    before = copy.deepcopy(data)
    markup = report.render_html(data)
    assert data == before
    summary = markup.split('<div class="schedule-confirmation-summary">', 1)[1].split('</div>', 1)[0]
    assert '06.11.2026' in summary and 'Проверка отозвана.' in summary
    assert 'Календарь не подтверждён.' in summary
    assert 'Полнота цепочки до РНВ не подтверждена.' in summary
    assert '&lt;img' in summary and '<img' not in summary and '<details' not in summary
