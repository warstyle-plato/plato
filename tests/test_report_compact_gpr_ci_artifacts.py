"""Public synthetic PAGE/PDF review artifacts; no stored projects or source files.

All inputs are fictional literals from this module and public test fixtures.
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


def _axis_page_literal():
    """Read the real PAGE script without importing the application for Node."""
    import ast
    module = ast.parse((ROOT / 'developaid_monitor_page.py').read_text())
    assignment = next(node for node in module.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'MONITOR_PAGE'
                              for target in node.targets))
    return next(node.value for node in ast.walk(assignment.value)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and len(node.value) > 100_000)


def _axis_node(code):
    import os
    import shutil
    import subprocess
    node = shutil.which('node')
    assert node, 'Node is required for the native axis lifecycle guard'
    try:
        result = subprocess.run([node, '--single-threaded', '--v8-pool-size=1'], input=code,
                                text=True, capture_output=True, timeout=30,
                                env={**os.environ, 'UV_THREADPOOL_SIZE': '1'})
    except subprocess.TimeoutExpired as error:
        pytest.fail('Native axis Node timed out; stdout='+repr(error.stdout)[-1000:]
                    +'; stderr='+repr(error.stderr)[-1000:])
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_native_monitor_axis_script_compiles_and_layout_preserves_anchors_and_lifecycle():
    """Execute actual PAGE functions against measured-box/event counterexamples."""
    page = _axis_page_literal()
    source = page[page.index('let ganttAxisCleanup=null;'):
                  page.index("window.addEventListener('pagehide',clearGanttAxisLayout);")]
    script = next(script for script in re.findall(r'<script[^>]*>(.*?)</script>', page, re.S)
                  if 'function renderGantt(' in script)
    result = _axis_node('''const vm=require('node:vm');
        new vm.Script('''+json.dumps(script)+''');
        const assert=require('node:assert/strict');
        class Events{constructor(){this.events=new Map()}
          addEventListener(k,f){if(!this.events.has(k))this.events.set(k,new Set());this.events.get(k).add(f)}
          removeEventListener(k,f){this.events.get(k)?.delete(f)}
          emit(k){for(const f of this.events.get(k)||[])f()}
          count(){return [...this.events.values()].reduce((n,s)=>n+s.size,0)}}
        globalThis.window=new Events();const details=new Events();
        let frames=new Map(),next=0,current;
        globalThis.requestAnimationFrame=f=>{frames.set(++next,f);return next};
        globalThis.cancelAnimationFrame=id=>frames.delete(id);
        const flush=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(f=>f())};
        const observers=[];
        globalThis.ResizeObserver=class{constructor(f){this.f=f;this.active=false;observers.push(this)}observe(){this.active=true}disconnect(){this.active=false}};
        globalThis.$=id=>id==='gprCalendar'?details:{querySelector:()=>current};
        globalThis.getComputedStyle=el=>({display:el.visible?'block':'none'});
        class Label{constructor(position,width,visible=true){this.dataset={axisPosition:String(position),axisDate:'2044-01-15'};this.style={left:position+'%'};this.natural=width;this.visible=visible;this.hidden=false}
          getBoundingClientRect(){return {width:Math.min(this.natural,this.axis.width),height:16*Math.ceil(this.natural/this.axis.width)}}}
        class Axis{constructor(width){this.width=width;this.style={};this.dataset={};this.isConnected=true;
          this.ticks=Array.from({length:7},(_,i)=>new Label(i/6*100,76));
          this.labels=[new Label(0,130),new Label(1,130,false),new Label(99,150),new Label(99,140),new Label(100,900)];delete this.labels.at(-1).dataset.axisPosition;
          [...this.ticks,...this.labels].forEach(el=>el.axis=this)}
          getBoundingClientRect(){return {width:this.width}}
          querySelectorAll(s){assert.ok(['.tick','.axis-lab'].includes(s));return s==='.tick'?this.ticks:this.labels}}
        '''+source+'''
        assert.match(ganttAxisTickLabel(new Date('2044-01-15T12:00:00Z')),/2044/);
        const counts=[];
        for(const width of [840,364,240,81,100]){
          const axis=new Axis(width),anchors=JSON.stringify([...axis.ticks,...axis.labels].map(e=>[e.style.left,e.dataset]));
          layoutGanttAxis(axis);const boxes=[...axis.ticks.filter(e=>!e.hidden),...axis.labels.filter(e=>e.visible)].map(e=>{
            const x=width*parseFloat(e.style.left)/100+parseFloat(e.style.transform.slice(11));
            return {left:x,right:x+e.getBoundingClientRect().width,top:parseFloat(e.style.top),bottom:parseFloat(e.style.top)+e.getBoundingClientRect().height}});
          for(const a of boxes){assert.ok(a.left>=-0.01&&a.right<=width+0.01);for(const b of boxes)if(a!==b)assert.ok(a.right<=b.left||b.right<=a.left||a.bottom<=b.top||b.bottom<=a.top)}
          assert.equal(JSON.stringify([...axis.ticks,...axis.labels].map(e=>[e.style.left,e.dataset])),anchors);
          counts.push(axis.ticks.filter(e=>!e.hidden).length);
        }
        assert.ok(counts[0]>counts[2]&&counts[2]>=2);
        assert.equal(counts[3],1);assert.equal(counts[4],1);
        current=new Axis(400);const old=current;observeGanttAxis();const stale=[...frames.values()][0];const prior=observers.at(-1);
        current=new Axis(240);observeGanttAxis();assert.equal(prior.active,false);assert.equal(frames.size,1);stale();assert.equal(old.dataset.axisLayout,undefined);flush();
        assert.equal(current.dataset.axisLayout,'ready');assert.equal(observers.filter(o=>o.active).length,1);
        current.width=600;window.emit('resize');details.emit('toggle');assert.equal(frames.size,1);flush();assert.equal(current.dataset.axisLayoutWidth,'600');
        window.emit('resize');clearGanttAxisLayout();assert.equal(frames.size,0);assert.equal(window.count(),0);assert.equal(details.count(),0);assert.equal(observers.filter(o=>o.active).length,0);
        prior.f();stale();assert.equal(frames.size,0);
        console.log(JSON.stringify({counts,anchorsPreserved:true,staleCallbacksIgnored:true,cleanup:true}));
    ''')
    assert json.loads(result)['cleanup'] is True


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
                 project=dict(progress=.375, coverage=88, partial=True, known_readings=4, total=6, source_dates=[CUT],
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


def _public_monitor_axis_view():
    from test_gpr_work_forecast_page import view
    value = view('profile')  # Fictional public fixture; no stored source input.
    value['project'] = PROJECT
    # Deliberately coincident fictional milestones exercise separate rows.
    value['schedule']['owner_rnv'] = dict(
        date=value['schedule']['work_forecast']['summary']['finish'], source='owner_decision')
    return value


def test_public_monitor_axis_fixture_keeps_one_source_bound_work_date():
    from developaid_gpr_work_forecast import for_schedule
    value = _public_monitor_axis_view()
    actual = for_schedule(value['schedule'], value['cut'])
    assert actual == value['schedule']['work_forecast']
    assert actual['state'] == 'known' and actual['project']['forecast']['covered'] > 0
    assert value['schedule']['owner_rnv']['date'] == actual['summary']['finish']


def test_monitor_axis_responsive_columns_leave_a_readable_plot_budget():
    """Static width budget supplements genuine641/700px geometry below."""
    css = _axis_page_literal().split('</style>', 1)[0]
    rule = re.search(r'@media\(min-width:641px\) and \(max-width:1100px\)\{'
                     r'#gantt \.g-axis,#gantt \.g-row\{grid-template-columns:'
                     r'([0-9]+)px minmax\(([0-9]+)px,1fr\) ([0-9]+)px\}\}', css)
    assert rule, 'The narrow plot must share bounded responsive columns with its rows'
    left, plot_minimum, right = map(int, rule.groups())
    padding = int(re.search(r'\.wrap\{[^}]*padding:([0-9]+)px', css)[1])
    border = int(re.search(r'\.card\{[^}]*border:([0-9]+)px', css)[1])
    for viewport in (641, 700):
        available = viewport - 2 * padding - 2 * border
        assert available >= left + plot_minimum + right
        assert available - left - right >= plot_minimum >= 240


def _monitor_axis_geometry(page):
    return page.evaluate('''()=>{
      const axis=document.querySelector('#gantt .axis'),r=axis.getBoundingClientRect();
      const visible=e=>e.checkVisibility()&&!e.hidden;
      const inspect=e=>{const b=e.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(e);
        return {text:e.textContent,date:e.dataset.axisDate||null,anchor:e.style.left,
          left:b.left,right:b.right,top:b.top,bottom:b.bottom,font:parseFloat(getComputedStyle(e).fontSize),
          textRects:[...range.getClientRects()].map(x=>({left:x.left,right:x.right,top:x.top,bottom:x.bottom}))}};
      return {width:innerWidth,axis:{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width},
        ticks:[...axis.querySelectorAll('.tick')].filter(visible).map(inspect),
        milestones:[...axis.querySelectorAll('.axis-lab')].filter(visible).map(inspect),
        overview:[...document.querySelectorAll('.gpr-overview-axis span')].filter(visible).map(inspect),
        horizontalOverflow:document.documentElement.scrollWidth>innerWidth,
        observers:window.publicAxisObservers,
        sourceSignature:{domain:[axis.parentElement.dataset.domainStart,axis.parentElement.dataset.domainEnd],
          ticks:[...axis.querySelectorAll('.tick')].map(e=>({time:e.dataset.axisTime,anchor:e.style.left})),
          marks:[...document.querySelectorAll('#gantt .cut,#gantt .owner-rnv-plan,#gantt .gpr-scoped-finish,#gantt .planbar,#gantt .factbar,#gantt .gpr-forecast-strip,#gantt .gpr-forecast-end')].map(e=>({kind:e.className,date:e.dataset.date||e.dataset.finish||e.title,left:e.style.left,width:e.style.width})),
          work:JSON.stringify(currentView.schedule.work_forecast)}};
    }''')


def _assert_monitor_axis_geometry(geometry):
    axis = geometry['axis']
    assert axis['width'] > 0 and not geometry['horizontalOverflow']
    assert len(geometry['ticks']) >= 2
    assert all(re.search(r'\b[0-9]{4}\b', tick['text']) for tick in geometry['ticks'])
    assert len(geometry['milestones']) == 3
    boxes = geometry['ticks'] + geometry['milestones']
    for box in boxes:
        assert box['font'] >= 12
        assert axis['left']-1 <= box['left'] < box['right'] <= axis['right']+1
        assert axis['top']-1 <= box['top'] < box['bottom'] <= axis['bottom']+1
        assert all(axis['left']-1 <= text['left'] <= text['right'] <= axis['right']+1
                   for text in box['textRects'])
    for index, first in enumerate(boxes):
        for second in boxes[index+1:]:
            assert (first['right'] <= second['left']+0.5 or second['right'] <= first['left']+0.5
                    or first['bottom'] <= second['top']+0.5 or second['bottom'] <= first['top']+0.5), (first, second)
    assert geometry['overview'] and all(box['font'] >= 12 for box in geometry['overview'])
    assert geometry['observers']['active'] == 1


@pytest.mark.parametrize('width', [1440, 390, 641, 700])
def test_public_synthetic_full_monitor_axis_fonts_bounds_dates_and_reflow(monkeypatch, width):
    """Genuine PAGE geometry; public artifacts contain only fictional inputs."""
    from playwright.sync_api import expect
    from test_gpr_why_page import serve
    from test_gpr_work_forecast_page import show
    from test_monitor_cumulative_controls import browser_page
    value = _public_monitor_axis_view()
    serve(monkeypatch, value)
    init = '''(()=>{
      const Native=ResizeObserver;window.publicAxisObservers={active:0,created:0,disconnected:0};
      window.ResizeObserver=class extends Native{
        constructor(callback){super(callback);this.axisTargets=new Set()}
        observe(target,options){if(target.matches?.('#gantt .axis')&&!this.axisTargets.has(target)){this.axisTargets.add(target);publicAxisObservers.active++;publicAxisObservers.created++}super.observe(target,options)}
        disconnect(){publicAxisObservers.active-=this.axisTargets.size;publicAxisObservers.disconnected+=this.axisTargets.size;this.axisTargets.clear();super.disconnect()}
      };
    })();'''
    with browser_page(width, init=init) as (page, _, errors):
        show(page, value)
        page.locator('#gprCalendar > summary').click()
        axis = page.locator('#gantt .axis')
        expect(axis).to_be_visible()
        wait = '''()=>{const a=document.querySelector('#gantt .axis');return a?.dataset.axisLayout==='ready'&&Math.abs(Number(a.dataset.axisLayoutWidth)-a.getBoundingClientRect().width)<.1}'''
        page.wait_for_function(wait)
        initial = _monitor_axis_geometry(page)
        out = _output()
        artifact = out / f'public-synthetic-monitor-axis-{width}-geometry.json'
        artifact.write_text(json.dumps(dict(public_synthetic_only=True,
            real_project_or_source_data=False, validation_passed=False, initial=initial), ensure_ascii=False, indent=2))
        page.locator('#gantt').screenshot(path=str(out / f'public-synthetic-monitor-axis-{width}.png'))
        _assert_monitor_axis_geometry(initial)
        if width in (641, 700):
            assert initial['axis']['width'] >= 240
        expected = value['schedule']['work_forecast']['summary']['finish']
        assert {x['date'] for x in initial['milestones']} == {value['cut'], expected}
        assert initial['milestones'][1]['date'] == initial['milestones'][2]['date'] == expected
        assert initial['milestones'][1]['bottom'] <= initial['milestones'][2]['top']

        # The plot changes width while hidden, then opens; no source values,
        # native date domain or percentage anchors may move with its labels.
        page.evaluate("$('gprCalendar').open=false")
        expect(axis).to_be_hidden()
        alternate = 700 if width != 700 else 1440
        page.set_viewport_size(dict(width=alternate, height=950))
        page.evaluate("$('gprCalendar').open=true")
        expect(axis).to_be_visible()
        page.wait_for_function(wait)
        resized = _monitor_axis_geometry(page)
        _assert_monitor_axis_geometry(resized)
        assert resized['sourceSignature'] == initial['sourceSignature']
        if width == 1440:
            assert len(resized['ticks']) < len(initial['ticks'])

        page.set_viewport_size(dict(width=width, height=950))
        page.wait_for_function(wait)
        page.evaluate('()=>{renderGantt(currentView);renderGantt(currentView)}')
        page.wait_for_function(wait)
        rendered = _monitor_axis_geometry(page)
        _assert_monitor_axis_geometry(rendered)
        assert rendered['sourceSignature'] == initial['sourceSignature']
        assert rendered['observers']['disconnected'] >= 2
        assert not errors
        artifact.write_text(json.dumps(dict(public_synthetic_only=True, real_project_or_source_data=False,
            validation_passed=True, initial=initial, resized=resized, rendered=rendered), ensure_ascii=False, indent=2))
        page.evaluate('clearReadiness()')
        assert page.evaluate('publicAxisObservers.active') == 0


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
            qualifier = host.locator('[data-gpr-block=forecast] p').filter(has_text='Покрытие веса: 88,0%.')
            expect(qualifier).to_have_count(1)
            expect(qualifier).to_be_visible()
            expect(qualifier).to_contain_text('Пригодные показания: 4 из 6 работ.')
            expect(qualifier).to_contain_text('Оценка по известной части состава.')
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
        qualification = text.split('Прогноз учтённых работ', 1)[1].split('Матрица готовности', 1)[0]
        assert 'Пригодные показания: 4 из 6 работ.' in qualification
        assert 'Покрытие веса: 88,0%.' in qualification
        assert 'Оценка по известной части состава.' in qualification
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
