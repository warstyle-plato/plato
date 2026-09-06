"""Запись поверх видна до нажатия, а не спрятана в вопросе.

«И где запись поверх? я думал будет кнопка в ряду ранее сохранённого проекта
рядом с открыть или наверх Сохранить и Сохранить как…» (владелец, 06.09.2026).

Первая версия правки прятала выбор в `confirm`: одна кнопка «Сохранить
текущий», ОК — поверх, Отмена — как новый. Узнать об этом можно было
единственным способом — нажав, а «Отмена» читается как «ничего не делать».

Проверяется то, что видно: строка списка несёт кнопку «Поверх» со своим id, а
шапка — две названные кнопки. Строковый поиск по `PAGE` тут не годится — он
подтвердил бы и разметку, которая на экран не выходит, — поэтому список
рисуется настоящим `openProjects` в node.

Запуск: python3 -m pytest tests/test_the_cabinet_shows_where_to_write_over.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _piece(name: str, kind: str = "function") -> str:
    start = PAGE.index(f"{kind} {name}(")
    depth, i = 0, PAGE.index("{", start)
    while True:
        if PAGE[i] == "{":
            depth += 1
        elif PAGE[i] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:i + 1]
        i += 1


STUBS = """
let projectsStorageReady=true, projectsAdminKey='key', openedProject=null;
const projectsDialog={style:{}};
const projectsBody={innerHTML:''};
function renderAccountBox(){}
function renderOpenedProjectButton(){}
function renderProjectsLogin(){}
function hideProjectsLogin(){}
function activeSession(){return 'session'}
function escapeHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
 .replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function money(v){return String(v)}
function mult(v){return String(v)}
const document={getElementById:()=>null};
"""

ROWS = [
    {"id": "abc123", "name": "Румянцево", "saved_at": "2026-09-06T10:00:00+00:00",
     "summary": {"revenue_mln": 1, "net_profit_mln": 2, "llcr": 1.2},
     "cadastral": [], "has_share": True},
    {"id": "row42", "name": "Нагатино", "saved_at": "2026-09-05T10:00:00+00:00",
     "summary": {}, "cadastral": [], "has_share": False},
]


def _rendered() -> str:
    script = STUBS + _piece("openProjects", kind="async function") + """
function projectsCall(path){
  if(path==='/projects/list')return Promise.resolve({projects:%s});
  return Promise.resolve({});
}
(async()=>{await openProjects();console.log(JSON.stringify(projectsBody.innerHTML))})();
""" % json.dumps(ROWS, ensure_ascii=False)
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_every_saved_row_offers_writing_over_it() -> None:
    html = _rendered()
    assert html.count(">Поверх<") == len(ROWS), "кнопка стоит у каждой строки"
    assert 'data-id="abc123"' in html and 'data-id="row42"' in html, \
        "кнопка знает, поверх чего пишет"
    assert html.index(">Открыть<") < html.index(">Поверх<"), \
        "владелец просил её рядом с «Открыть»"


def test_the_row_carries_the_link_flag_not_the_code() -> None:
    """Предупредить о живой ссылке надо ДО записи, а код в списке не нужен."""
    html = _rendered()
    rumyantsevo = html[html.index("Румянцево"):html.index("Нагатино")]
    nagatino = html[html.index("Нагатино"):]
    assert 'data-shared="1"' in rumyantsevo, "у проекта со ссылкой признак есть"
    assert 'data-shared=""' in nagatino, "у проекта без ссылки его нет"
    assert "share_code" not in html and "s3cr3t" not in html


def test_the_value_travels_as_data_not_as_code_in_onclick() -> None:
    """Экранированное значение внутри onclick снова становится кодом —
    правило уже стоило нам разбора; имя едет data-атрибутом."""
    html = _rendered()
    assert "saveProjectOver(this.dataset.id" in html
    assert "saveProjectOver('" not in html


def test_the_header_names_both_intentions() -> None:
    assert 'onclick="saveOpenedProject()"' in PAGE and ">Сохранить<" in PAGE
    assert 'onclick="saveProjectAsNew()"' in PAGE and "Сохранить как…" in PAGE
    assert "Сохранить текущий" not in PAGE, \
        "кнопки с двумя смыслами больше нет"
