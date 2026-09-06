"""Открытый проект перезаписывается, а не удваивается.

«Ещё бы сохранение проекта могло быть поверх ранее сохранённого, а то я открыл
сохранённый, внёс изменения, и надо сохранять новый» (владелец, 04.09.2026).

Хранилище это умело давно: `project_save(..., project_id)` при переданном id
пишет ту же запись, сохраняет код «Поделиться» и против лимита такой проект не
считает. Не умела страница — `loadProject` открытый id не запоминал, а
`saveProjectToServer` его не слал, и сервер честно заводил второй экземпляр.

Опасная половина правки не в перезаписи, а в том, чтобы вовремя ЗАБЫТЬ
открытый проект: истории версий у хранилища нет, и «Сохранить поверх» после
подмены снимка записало бы чужие числа туда, откуда их не достать.

Запуск: python3 -m pytest tests/test_a_saved_project_is_written_over.py -q
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
    """Функция целиком — по объявлению и скобкам, а не по соседней строке."""
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


def _run(script: str) -> dict:
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


# Заглушки ровно те, без которых код не исполнится: всё, что не про наш вопрос.
STUBS = """
let inputs={}, tep={}, phasing=null, lastResult=null;
let aiHistory=[], aiProposals=[], aiIntake=null;
let territoryCleared=[], tepRatioComplaint='', phaseTepEditWarning='', storageInsideParking=0;
const tepRefillNote={};
let moLastQuery='', moAutoApartments=null;
let presetPreview=null, sensitivityOptions=null, sensitivityReport=null, sensitivityPicked=null;
let landScreeningLast=null, LAND_MAP=null;
const scenarioSelect={value:'base'};
const said=[];
function alert(text){said.push(String(text))}
function projectCadastral(){return[]}
function projectSummaryForStore(){return{}}
function openProjects(){}
function closeProjects(){}
function calculateAndOpen(){}
function forgetTerritoryState(){}
function renderInputs(){}
function renderTep(){}
function renderPhasing(){}
function renderStoredGlavapu(){}
function renderStoredCadastral(){}
function renderStoredLand(){}
function renderStoredMo(){}
function persistLocalSilently(){}
function cloneValue(value){return JSON.parse(JSON.stringify(value))}
function makeDefaultPhasing(){return null}
const INPUT_DEFAULT={}, TEP_DEFAULT={};
let asked=[];
"""

CODE = "\n".join([
    PAGE[PAGE.index("let openedProject=null;"):PAGE.index("function rememberOpenedProject(")],
    _piece("rememberOpenedProject"),
    _piece("applyProjectSnapshot"),
    _piece("loadProject", kind="async function"),
    _piece("saveProjectToServer", kind="async function"),
    _piece("deleteProject", kind="async function"),
    _piece("resetProjectState"),
])


def _script(body: str) -> str:
    return STUBS + CODE + "\n" + body


def _sent(answer_overwrite: bool, record: dict | None) -> dict:
    """Открыть проект (или нет) и сохранить, отвечая на вопрос о перезаписи."""
    return _run(_script("""
const sent=[];
function projectsCall(path,payload){
  sent.push({path,payload});
  if(path==='/projects/open')return Promise.resolve(%(record)s);
  if(path==='/projects/save')return Promise.resolve({id:'new777',name:payload.name});
  return Promise.resolve({});
}
function confirm(text){asked.push(String(text));return %(overwrite)s}
function prompt(text,suggested){asked.push(String(text));return 'Новое имя'}
(async()=>{
  if(%(open)s) await loadProject('abc123');
  await saveProjectToServer();
  console.log(JSON.stringify({sent,asked,said,opened:openedProject}));
})();
""" % {"record": json.dumps(record or {}, ensure_ascii=False),
       "overwrite": "true" if answer_overwrite else "false",
       "open": "true" if record else "false"}))


RECORD = {"id": "abc123", "name": "Румянцево", "share_code": "s3cr3t",
          "payload": {"inputs": {}, "tep": {}}}


def test_an_opened_project_is_written_over_under_its_own_id() -> None:
    got = _sent(True, RECORD)
    save = [row for row in got["sent"] if row["path"] == "/projects/save"][0]
    assert save["payload"]["id"] == "abc123", "перезапись идёт под id открытого"
    assert save["payload"]["name"] == "Румянцево", "имя берётся у него же"
    assert "Румянцево" in " ".join(got["asked"]), "вопрос называет проект"
    assert any("перезаписан" in line for line in got["said"])


def test_the_answer_no_saves_a_new_project_and_keeps_the_old_one() -> None:
    """«Отмена» — это второе намерение, а не отказ от сохранения."""
    got = _sent(False, RECORD)
    save = [row for row in got["sent"] if row["path"] == "/projects/save"][0]
    assert save["payload"]["id"] == "", "новый проект идёт без id"
    assert save["payload"]["name"] == "Новое имя", "имя спрашивается заново"


def test_a_live_link_is_named_as_a_fact_before_the_overwrite() -> None:
    """Решение владельца: перезапись обновляет ссылку намеренно —
    «отлично что увидит». Значит это факт рядом с вопросом, а не пугалка."""
    question = " ".join(_sent(True, RECORD)["asked"])
    assert "ссылка" in question and "увидит новые числа" in question
    without = " ".join(_sent(True, dict(RECORD, share_code=""))["asked"])
    assert "ссылка" not in without, "у проекта без ссылки строки о ней нет"


def test_a_project_that_was_never_opened_is_saved_as_new() -> None:
    got = _sent(False, None)
    save = [row for row in got["sent"] if row["path"] == "/projects/save"][0]
    assert save["payload"]["id"] == ""
    assert not any("поверх" in line for line in got["asked"]), \
        "перезаписывать нечего — и спрашивать не о чем"


def test_the_saved_project_becomes_the_opened_one() -> None:
    """Иначе третий экземпляр заведётся тем же способом, что и второй."""
    got = _sent(False, None)
    assert got["opened"] and got["opened"]["id"] == "new777"


def test_a_replaced_snapshot_forgets_the_opened_project() -> None:
    """Присланная ссылка, файл настроек и площадка КРТ идут одной функцией —
    и после неё «Сохранить поверх» записало бы чужие числа в чужую запись."""
    got = _run(_script("""
function projectsCall(){return Promise.resolve({})}
function confirm(){return true}
function prompt(){return 'x'}
openedProject={id:'abc123',name:'Румянцево',shareCode:''};
applyProjectSnapshot({inputs:{},tep:{}});
console.log(JSON.stringify({opened:openedProject}));
"""))
    assert got["opened"] is None


def test_a_reset_forgets_the_opened_project() -> None:
    got = _run(_script("""
function projectsCall(){return Promise.resolve({})}
function confirm(){return true}
function prompt(){return 'x'}
openedProject={id:'abc123',name:'Румянцево',shareCode:''};
resetProjectState();
console.log(JSON.stringify({opened:openedProject}));
"""))
    assert got["opened"] is None


def test_a_deleted_project_stops_being_the_opened_one() -> None:
    """Иначе «Сохранить поверх» завело бы его заново под тем же id."""
    got = _run(_script("""
function projectsCall(){return Promise.resolve({})}
function confirm(){return true}
function prompt(){return 'x'}
openedProject={id:'abc123',name:'Румянцево',shareCode:''};
(async()=>{
  await deleteProject('abc123');
  console.log(JSON.stringify({opened:openedProject}));
})();
"""))
    assert got["opened"] is None
