"""Public synthetic PAGE/PDF review artifacts; no stored projects or source files.

All names, IDs, dates, amounts and source hashes below are fictional literals.
Only this module writes .ci-ui-review/gpr-synthetic; never copy private captures.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.ci-ui-review' / 'gpr-synthetic'
PROJECT = 'Вымышленный квартал — публичный CI-пример'
CUT = '2031-05-12'
FINISH = '2032-08-20'
ORIGIN = 'https://gpr-synthetic.invalid'


def synthetic_report(project_finish=FINISH):
    """Small public post-calculation DTO, including an explicit ref/current join."""
    rows, points, corpora = [], {}, []
    mapping = {}
    for index, finish in enumerate(['2032-04-15', project_finish, '2032-06-07'], 1):
        name = 'Учебный корпус '+str(index)
        members = []
        for stage in ['frame', 'services']:
            reference = f'fictional-reference-{index}-{stage}'
            current = f'fictional-current-{index}-{stage}'
            members.append(reference)
            mapping[reference] = current
            task = dict(id=current, object=name, name='Вымышленный пакет '+stage,
                        plan_start='2028-01-10', plan_finish='2031-09-30',
                        plan_pace_scenario=dict(finish=finish, source_date=CUT))
            rows.append(dict(task=task))
            points[current] = dict(work_id=current, reference_work_id=reference,
                                   finish=finish, plan_finish='2031-09-30',
                                   complete=False, basis='conditional', source_date=CUT)
        corpora.append(dict(name=name, work_ids=members, progress=[.25, .5, None][index-1], partial=True))
    rows.append(dict(task=dict(id='fictional-parking', object='Учебный паркинг',
                               name='Вымышленный пакет вне состава', plan_start='2031-01-10',
                               plan_finish='2038-12-31')))
    display = dict(schema=1, basis='readiness_project_forecast', cut=CUT,
                   source_sha256='d'*64, full_source_sha256='d'*64, id_scope='full_source',
                   finish=project_finish, total=6, covered=6, reference_total=6,
                   truncated=False, rows=list(points.values()),
                   paragraphs=['Public synthetic explanation only.', 'No private source or project.'])
    forecast = {key: display[key] for key in ['source_sha256', 'full_source_sha256', 'id_scope',
                                             'finish', 'total', 'covered', 'reference_total']}
    forecast.update(display=copy.deepcopy(display), excluded=[])
    state = dict(cut=CUT, source_sha256='d'*64,
                 project=dict(progress=.375, known_readings=4, total=6, source_dates=[CUT],
                              work_ids=list(mapping), forecast=forecast),
                 corpora=corpora,
                 forecast_identity=dict(source_sha256='d'*64, full_source_sha256='d'*64,
                                        id_scope='full_source', remaining_ids=mapping),
                 matrix=[dict(stage='Учебный конструктив', cells=copy.deepcopy(corpora))])
    return dict(project=PROJECT, kind='week', start='2031-05-06', end=CUT,
                gantt=dict(readiness=state, calendar=dict(schema=1, cut=CUT, qualified=True,
                           display=copy.deepcopy(display), rows=rows, points=points, issues=[],
                           owner_rnv=dict(date='2031-09-30', source='owner_decision'))),
                funding=dict(state='ok', rss='2031-05-11', limit=dict(known=False, reason='Учебный лимит не задан.'),
                             draws=dict(total=1_234_567, period=12_345, month=23_456),
                             interest=dict(total=100, period=20, month=30),
                             escrow=dict(state='missing', reason='Учебное эскроу не задано.')),
                findings=[dict(topic='Продажи', text='Публичный вымышленный пример.', source='CI')])


def _body_and_financial_check():
    import developaid_management_report as report
    import developaid_report_gantt as gantt
    value = synthetic_report()
    before = copy.deepcopy(value)
    body = report.render_html(value)
    assert value == before
    compact = gantt.compact_model(value['gantt'], CUT)
    assert compact['qualified'] and compact['finish'] == FINISH
    financial = lambda sample: [row for row in report.tiles(sample)
                                if row.get('group') != 'gpr_readiness']
    # Moving only the canonical GPR date cannot change any financial tile.
    assert financial(value) == financial(synthetic_report('2032-09-14'))
    known = next(row for row in financial(value) if row['label'] == 'Выбрано у банка')
    assert known['value'] == '1,2 млн ₽'
    assert next(row for row in financial(value) if row['label'] == 'Лимит банка')['value'] == 'нет данных'
    return value, body


def _output():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    return OUTPUT


@pytest.mark.parametrize('width', [390, 1440])
def test_public_synthetic_native_page_and_print_layout(width):
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    from developaid_report_page import REPORT_PAGE
    value, body = _body_and_financial_check()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()), args=['--no-sandbox'])
        try:
            context = browser.new_context(viewport=dict(width=width, height=1000),
                                          service_workers='block', accept_downloads=False)
            calls = []
            def route(route):
                request = route.request
                url = urlsplit(request.url)
                if url.scheme != 'https' or url.netloc != 'gpr-synthetic.invalid' or url.query:
                    return route.abort('blockedbyclient')
                if request.method == 'GET' and url.path == '/report':
                    return route.fulfill(content_type='text/html', body=REPORT_PAGE)
                if request.method == 'POST' and url.path == '/monitor/report/projects':
                    calls.append('public_projects')
                    return route.fulfill(json=dict(projects=[dict(project=PROJECT)]))
                if request.method == 'POST' and url.path == '/monitor/report/build':
                    payload = request.post_data_json
                    assert payload['project'] == PROJECT and payload['kind'] == 'week' and payload['end'] == CUT
                    calls.append('public_report')
                    return route.fulfill(json=dict(html=body, report=value))
                return route.abort('blockedbyclient')
            context.route('**/*', route)
            if hasattr(context, 'route_web_socket'):
                context.route_web_socket('**/*', lambda ws: ws.close())
            hint = dict(version=1, current=dict(project=PROJECT, cut=CUT),
                        scopes=[dict(project=PROJECT, cut=CUT, view='monitor', monitor={}, report=dict(reportKind='week'))])
            context.add_init_script('localStorage.setItem("plato_projects_key","public-synthetic-not-a-service-key");'
                                    'sessionStorage.setItem("developaid_monitor_navigation_v1",'+json.dumps(json.dumps(hint))+');')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(ORIGIN+'/report')
            host = page.locator('#reportBox .report-gpr-compact')
            expect(host).to_be_visible()
            out = _output()
            # Keep a public-only image even if a later geometry assertion fails.
            host.screenshot(path=str(out/f'public-synthetic-page-{width}.png'))
            expect(host.locator('[data-gpr-block]')).to_have_count(3)
            assert host.locator('[data-gpr-block]').evaluate_all('es=>es.map(e=>e.dataset.projectForecast)') == [FINISH]*3
            expect(host.locator('.rg-corpus:visible')).to_have_count(4)
            expect(host.locator('.rg-plan')).to_have_count(3)
            expect(host.locator('.rg-forecast')).to_have_count(3)
            assert host.locator('details,.cg-work,.cg-stage').count() == 0
            # Document overflow can stay bounded while an ancestor clips the
            # table. Every column AND its actual text must fit without scrolling.
            matrix = host.locator('.rg-matrix')
            expect(matrix.locator('thead th')).to_have_count(4)
            assert matrix.locator('thead th').all_text_contents() == ['Этап', 'Учебный корпус 1', 'Учебный корпус 2', 'Учебный корпус 3']
            matrix_geometry = matrix.evaluate('''table=>{
                const box=table.getBoundingClientRect(),cells=[...table.querySelectorAll('th,td')];
                const viewport={left:Math.max(0,box.left),right:Math.min(innerWidth,box.right)};
                for(let node=table.parentElement;node;node=node.parentElement){
                    if(!/^(auto|scroll|hidden|clip)$/.test(getComputedStyle(node).overflowX))continue;
                    const clip=node.getBoundingClientRect(),left=clip.left+node.clientLeft;
                    viewport.left=Math.max(viewport.left,left);
                    viewport.right=Math.min(viewport.right,left+node.clientWidth);
                }
                const inspect=cell=>{
                    const r=cell.getBoundingClientRect(),range=document.createRange();
                    range.selectNodeContents(cell);
                    return {text:cell.textContent, left:r.left,right:r.right,width:r.width,height:r.height,
                        font:parseFloat(getComputedStyle(cell).fontSize),
                        textRects:[...range.getClientRects()].map(x=>({left:x.left,right:x.right}))};
                };
                return {viewport,display:getComputedStyle(table).display,
                    clientWidth:table.clientWidth,scrollWidth:table.scrollWidth,cells:cells.map(inspect)};
            }''')
            assert matrix_geometry['display'] == 'table'
            assert matrix_geometry['scrollWidth'] <= matrix_geometry['clientWidth']+1
            for cell in matrix_geometry['cells']:
                assert cell['width'] > 0 and cell['height'] > 0 and cell['font'] >= 11
                assert cell['left'] >= matrix_geometry['viewport']['left']-1
                assert cell['right'] <= matrix_geometry['viewport']['right']+1
                assert all(max(cell['left'],matrix_geometry['viewport']['left'])-1 <= text['left']
                           <= text['right'] <= min(cell['right'],matrix_geometry['viewport']['right'])+1
                           for text in cell['textRects'])
            expect(host.locator('.rg-corpus').last).to_contain_text('Вне выбранного состава проекта')
            expect(host.locator('.rg-corpus').last).to_contain_text('нет даты')
            assert host.locator('.rg-corpus').last.locator('.rg-plan,.rg-forecast').count() == 0
            assert '2038' not in host.inner_text()
            # Unknown readiness remains labelled; it is not converted to zero.
            expect(host.locator('.rg-total td').last).to_contain_text('Нет данных')
            expect(page.locator('#reportBox .tile').filter(has=page.locator('.k', has_text='Выбрано у банка')).locator('.v')).to_have_text('1,2 млн ₽')
            years = host.locator('.rg-years [data-year]').evaluate_all('''es=>es.map(e=>{
                const r=e.getBoundingClientRect();return {year:e.textContent,left:r.left,right:r.right,
                    font:parseFloat(getComputedStyle(e).fontSize)};})''')
            assert [row['year'] for row in years] == ['2028', '2029', '2030', '2031', '2032']
            assert all(row['font'] >= 12 and 0 <= row['left'] < row['right'] <= width for row in years)
            assert all(a['right'] <= b['left'] for a, b in zip(years, years[1:]))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            host.locator('[data-gpr-block=gantt]').screenshot(path=str(out/f'public-synthetic-gantt-{width}.png'))
            page.emulate_media(media='print')
            expect(host.locator('.rg-corpus:visible')).to_have_count(4)
            for bar in host.locator('.rg-plan,.rg-forecast').all():
                expect(bar).to_be_visible()
            assert not errors
            assert calls == ['public_projects', 'public_report']
            (out/f'public-synthetic-geometry-{width}.json').write_text(json.dumps(
                dict(fixture='PUBLIC_SYNTHETIC_ONLY', width=width, project_forecast=FINISH,
                     blocks=3, corpus_rows=4, selected_bars=3, axis=years,
                     matrix=matrix_geometry, print_rows_visible=4),
                ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            browser.close()


def test_public_synthetic_native_pdf_has_compact_layout_and_canonical_date():
    import fitz
    import developaid_management_report as report
    from market_search.report_pdf import document, render
    from browser import chromium_or_skip
    value, body = _body_and_financial_check()
    full = document(body, style=report.REPORT_STYLE, title=PROJECT)
    out = _output()
    (out/'public-synthetic-document.html').write_text(full, encoding='utf-8')
    raw = render(full, footer='Публичный вымышленный CI-пример', executable_path=str(chromium_or_skip()))
    (out/'public-synthetic-report.pdf').write_bytes(raw)
    pdf = fitz.open(stream=raw, filetype='pdf')
    try:
        text = ' '.join(' '.join(page.get_text().split()) for page in pdf)
        assert all(label in text for label in ['Прогноз учтённых работ', 'Матрица готовности',
                                               'Гант по корпусам', 'Вне выбранного состава проекта'])
        assert text.count('20.08.2032') >= 3
        assert 'План РНВ владельца: 30.09.2031' in text
        assert '2038' not in text and 'Вымышленный пакет' not in text
        assert 'Приложение. Источники и ограничения оценки' not in text
        assert '1,2 млн ₽' in text
        gpr_pages = [page.number for page in pdf if any(label in page.get_text()
                     for label in ['Прогноз учтённых работ', 'Матрица готовности', 'Гант по корпусам', 'Учебный паркинг'])]
        assert gpr_pages
        year_spans = []
        for index in gpr_pages:
            page = pdf[index]
            assert all(word[0] >= -1 and word[2] <= page.rect.width+1 for word in page.get_text('words'))
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        if span['text'].strip() in {'2028', '2029', '2030', '2031', '2032'}:
                            assert span['size'] >= 9
                            year_spans.append(dict(page=index+1, year=span['text'].strip(), bbox=list(span['bbox'])))
        assert {span['year'] for span in year_spans} == {'2028', '2029', '2030', '2031', '2032'}
        for page_index in {span['page'] for span in year_spans}:
            axis = sorted((s for s in year_spans if s['page'] == page_index), key=lambda s:s['bbox'][0])
            assert [span['year'] for span in axis] == ['2028', '2029', '2030', '2031', '2032']
            assert all(a['bbox'][2] <= b['bbox'][0] for a, b in zip(axis, axis[1:]))
        for label, index in [('title', 0), ('gpr-first', min(gpr_pages)), ('gpr-last', max(gpr_pages))]:
            (out/f'public-synthetic-pdf-{label}.png').write_bytes(pdf[index].get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).tobytes('png'))
        (out/'public-synthetic-pdf-layout.json').write_text(json.dumps(
            dict(fixture='PUBLIC_SYNTHETIC_ONLY', project_forecast=FINISH, pages=len(pdf),
                 gpr_pages=[p+1 for p in gpr_pages], full_year_axis=year_spans),
            ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        pdf.close()
