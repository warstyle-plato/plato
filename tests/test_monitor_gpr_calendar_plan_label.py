"""Calendar duration is not a planned physical completion percentage."""
import ast
import json
from html import unescape
from pathlib import Path

from page_blocks import run_json


def _page():
    tree = ast.parse((Path(__file__).resolve().parents[1] /
                      'developaid_monitor_page.py').read_text())
    # Read the actual embedded page without importing/installing the application.
    return next(node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and 'function renderGprFactMatrix(' in node.value)


def _task(**changes):
    return dict({'id': 'work-1', 'level': 'task', 'object': 'Корпус А',
                 'section': 'Фасады', 'name': 'Учебная работа',
                 'source_format': 'corpus-gpr-v1',
                 'plan_start': '2031-03-12', 'plan_finish': '2032-10-09',
                 'plan_progress': .375,
                 'display_progress': {'value': 0, 'label': 'Выполнено по ГПР',
                                      'date': '2031-06-10'},
                 'work_done': False, 'pace_forecast_known': False,
                 'pace_forecast_method': 'plan',
                 'plan_pace_scenario': {'finish': '2033-02-17',
                                        'note': 'Условная дата при плановом темпе'}},
                **changes)


def _render(rows, page=None, cut="2031-06-15"):
    prelude = r"""
const host={innerHTML:'',querySelectorAll:()=>[]};
const elements={gprFactMatrix:host,project:{value:'Синтетический проект'},
 gprMatrixExpand:{},gprMatrixPrint:{}};
const $=id=>elements[id];
const window={};
let gprMatrixPrimed=false;
// Click/print actions are outside this render-only stand and must not run.
function renderGantt(){throw Error('unexpected navigation')}
function renderDetail(){throw Error('unexpected navigation')}
function beginGprPrint(){throw Error('unexpected print')}
"""
    tail = 'const cut=' + json.dumps(cut) + ';const rows=' + json.dumps(rows, ensure_ascii=False) + r""";
const before=JSON.stringify(rows);
const roots=rows.map(n=>({name:corpusLabel(n),level:'control',children:[n]}));
renderGprFactMatrix({cut,schedule:{}},roots);
console.log(JSON.stringify({html:host.innerHTML,unchanged:before===JSON.stringify(rows)}));
"""
    return run_json(prelude, tail, page=page or _page())


def test_matrix_shows_source_plan_dates_without_inventing_physical_plan_percent():
    result = _render([_task()])
    html = unescape(result['html'])
    assert result['unchanged']
    assert 'class="gpr-cell-plan">План: 12.03.2031 — 09.10.2032' in html
    assert 'Плановые даты: 12.03.2031 — 09.10.2032' in html
    assert 'не определяет плановую готовность по объёму работ' in html
    assert '37,5%' not in html and 'Δ' not in html and 'п.п.' not in html
    assert 'data-fact="0" data-calendar-fraction="0.375"' in html
    assert 'data-scenario-finish="2033-02-17"' in html
    assert 'При плановом темпе: 17.02.2033' in html


def test_calendar_duration_does_not_become_physical_readiness_for_other_formats():
    for source_format in ('legacy-gpr', None, {'format': 'corpus-gpr-v1'}):
        result = _render([_task(source_format=source_format)])
        html = unescape(result['html'])
        assert result['unchanged']
        assert 'class="gpr-cell-plan">План: 12.03.2031 — 09.10.2032' in html
        assert '37,5%' not in html and 'Δ' not in html
        assert 'data-calendar-fraction="0.375"' in html


def test_unknown_values_dates_and_escaped_source_text_stay_safe():
    result = _render([_task(plan_start=None, plan_finish=None,
                           plan_progress=None, plan_pace_scenario=None,
                           display_progress={'value': None,
                                             'label': '<неизвестно> "источник"',
                                             'date': None})])
    html = result['html']
    assert result['unchanged']
    assert 'class="gpr-cell-plan">План: начало неизвестно — окончание неизвестно</span>' in html
    assert 'Плановые даты: начало неизвестно — окончание неизвестно' in html
    assert 'Нет показания' in html
    assert 'data-fact="" data-calendar-fraction=""' in html
    assert '&lt;неизвестно&gt; &quot;источник&quot;' in html
    assert 'NaN' not in html and 'undefined' not in html
