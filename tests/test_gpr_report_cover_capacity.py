"""Full GPR source notes fit the A4 cover without whole-document scaling.

These synthetic combinations stress layout only. The existing budget/full
fixtures retain their text; native saved partial readiness and native credit
scenarios supply longer notes. They do not establish financial acceptance.
"""
import copy
import io

import pymupdf
import pytest
from playwright.sync_api import sync_playwright

import developaid_management_report as report
import developaid_monitor as monitor
from browser import chromium_or_skip
from market_search import report_pdf
from test_gpr_executive_readiness import saved, PROJECT, CUT
from test_the_credit_due_table import _built, _with_the_increase


def _normal(text):
    # Chromium can wrap dates on either side of an en dash or a nonbreaking
    # money separator. Every non-whitespace character must remain in order.
    return ''.join(text.split()).casefold()


def _cover_model(tmp_path, monkeypatch, variant, credit):
    state = copy.deepcopy(monitor.build(PROJECT, CUT)['schedule']['readiness'])
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'other-monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'other-data'))
    if variant == 'budget17':
        from test_management_report_budget_articles import _setup
        built = _setup()
    else:
        from test_management_report_analytics import _full
        built = _full()
    built['end'] = CUT
    built['gantt']['readiness'] = state
    if credit != 'missing':
        native_credit = _built(monkeypatch)
        built['credit_due'] = (_with_the_increase(native_credit) if credit == 'extra'
                               else native_credit['credit_due'])
        assert built['credit_due']['state'] == 'ok'
        assert bool(built['credit_due']['extra']) == (credit == 'extra')
    return built


@pytest.mark.parametrize('variant', ['budget17', 'full18'])
@pytest.mark.parametrize('credit', ['missing', 'base', 'extra'])
def test_full_cover_notes_and_page2_keep_their_normal_font(saved, tmp_path, monkeypatch, variant, credit):
    built = _cover_model(tmp_path, monkeypatch, variant, credit)
    before = copy.deepcopy(built)
    items = report.tiles(built)
    assert len(items) == (17 if variant == 'budget17' else 18)
    body = report.render_html(built)
    heading = "<h2 class='block' id='block-build'>"
    # Print the genuine cover at normal A4 width independently of later
    # tables, then require the same normal type in the complete document.
    cover_body = body[:body.index(heading)] + report._block_heading('build') + '<p>Граница обложки</p></div>'
    for name, content in [('cover', cover_body), ('full', body)]:
        document = report_pdf.document(content, style=report.REPORT_STYLE, title='Synthetic cover capacity')
        raw = report_pdf.render(document, footer='Synthetic', executable_path=str(chromium_or_skip()))
        (tmp_path / f'{variant}-{credit}-{name}.pdf').write_bytes(raw)
        pdf = pymupdf.open(stream=raw, filetype='pdf')
        cover = _normal(pdf[0].get_text())
        for item in items:
            for key in ('label', 'value', 'note'):
                assert _normal(item[key]) in cover, (name, item['label'], key)
        for item in built['findings']:
            assert _normal(item['text']) in cover, (name, item['topic'])
        assert any(hit.y0 < 120 for hit in pdf[1].search_for('Стройка'))
        spans = [span for block in pdf[0].get_text('dict')['blocks'] if 'lines' in block
                 for line in block['lines'] for span in line['spans']]
        title = next(span for span in spans if span['text'].startswith('Сводка по проекту'))
        assert title['size'] == pytest.approx(15, abs=.05), (name, title['size'])
        value = next(span for span in spans if span['text'] == '40,5%')
        assert value['size'] == pytest.approx(15, abs=.05), (name, value['size'])
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(chromium_or_skip()))
        page = browser.new_page(viewport={'width': 703, 'height': 1000})
        page.set_content(report_pdf.document(body, style=report.REPORT_STYLE, title='Synthetic width'))
        page.emulate_media(media='print')
        assert page.evaluate('document.documentElement.scrollWidth<=document.body.clientWidth+1')
        if credit != 'missing':
            cells = page.locator('table.credit-due :is(th,td)')
            assert cells.count() > 50
            assert cells.evaluate_all('(cells)=>cells.every(e=>e.scrollWidth<=e.clientWidth+1)')
        browser.close()
    assert built == before
