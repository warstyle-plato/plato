"""Вводные открываются на одной группе, а не на одиннадцати.

Вкладка разворачивала всё подряд: одиннадцать групп, полторы сотни полей,
экран без начала. Человек, впервые открывший калькулятор, листает поля вместо
того, чтобы ввести цену и сроки и посмотреть, что вышло.

Свёрнутая группа не должна быть закрытой дверью без таблички: в заголовке
показываются два-три значения, по которым видно, надо ли туда заходить, а у
необязательных объектов — сам факт «выключен», потому что их площади при
выключенном объекте ни на что не влияют.

Табличка обязана поспевать за полем. Правка внутри группы не перерисовывает
список целиком, и без обновления в заголовке осталось бы прошлое число — это
хуже пустого места: устаревшее значение выглядит как посчитанное.

Тест гоняет настоящий `renderInputs` из `PAGE` через node, а не его пересказ.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
PAGE = core.PAGE


def page_function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth = 0
    for position in range(PAGE.index("{", start), len(PAGE)):
        if PAGE[position] == "{":
            depth += 1
        elif PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def page_const(name: str) -> str:
    match = re.search(r"const %s=.*?;\n" % re.escape(name), PAGE, re.S)
    assert match, f"не найдено объявление {name}"
    return match.group(0)


DOM = """
const created=[];
function makeEl(tag){
 const node={tagName:tag,children:[],dataset:{},style:{},className:'',open:false,
  disabled:false,checked:false,value:'',id:'',type:'',title:'',step:'',
  appendChild(c){this.children.push(c);return c},
  set innerHTML(v){this._html=String(v||'');if(!v)this.children=[]},
  get innerHTML(){return this._html||''},
  set textContent(v){this._text=String(v)},
  get textContent(){return this._text||''},
  querySelector(sel){return find(this,sel)},
  remove(){}};
 created.push(node);return node;
}
function find(root,sel){
 for(const child of root.children){
  if(sel==='summary'&&child.tagName==='summary')return child;
  if(sel==='.group-peek'&&child.className==='group-peek')return child;
  const deep=find(child,sel);if(deep)return deep;
 }
 return null;
}
const boxes={inputGroups:makeEl('div'),vriInputGroups:makeEl('div')};
const document={createElement:makeEl,getElementById:(id)=>boxes[id]||null,
 querySelectorAll:(sel)=>sel==='details[data-group]'
   ?created.filter(n=>n.tagName==='details'&&n.dataset.group):[]};
const phasing={enabled:false};
const rateScenario={value:''};
const syncProjectClassSelector=()=>{},syncTep=()=>{},syncUndergroundPair=()=>{};
const calculate=()=>{},applyRequiredSocialProgramFromGlavapu=()=>false;
function groups(){
 return created.filter(n=>n.tagName==='details'&&n.dataset.group).map(det=>{
  const sum=det.querySelector('summary');
  const peek=sum&&sum.querySelector('.group-peek');
  return {name:det.dataset.group,open:det.open,
          peek:peek?peek.textContent:''};
 });
}
"""


def render(inputs: dict, tail: str = "console.log(JSON.stringify(groups()));") -> list:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = "\n".join([
        page_const("FIELD_GROUPS"),
        page_const("INPUT_DEFAULT"),
        page_const("num"),
        page_const("VRI_GROUP_NAME"),
        PAGE[PAGE.index("const GROUP_PEEK={"):PAGE.index("function groupPeek(")],
        page_function("groupPeek"),
        page_function("refreshGroupPeeks"),
        # Лестница ставки ПФ рисуется своим виджетом прямо в форме, поэтому
        # `renderInputs` без него не работает вовсе.
        page_function("parsePfStepsInput"),
        page_function("pfEdgeText"),
        page_function("savePfSteps"),
        page_function("pfStepEdit"),
        page_function("pfStepRemove"),
        page_function("pfStepAdd"),
        page_function("renderPfStepsEditor"),
        page_function("renderInputs"),
        DOM,
        f"const inputs=Object.assign(structuredClone(INPUT_DEFAULT),{json.dumps(inputs)});",
        "renderInputs();",
        tail,
    ])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- открыта одна группа --------------------------------------------------------

def test_only_the_first_group_is_open():
    """«Сделка и сроки» — то, с чего начинается любой расчёт."""
    rendered = [item for item in render({}) if item["name"] != core.FIELD_GROUPS[1][0]]
    assert rendered[0]["name"] == "Сделка и сроки"
    assert rendered[0]["open"] is True
    assert [item["name"] for item in rendered[1:] if item["open"]] == []


def test_the_vri_group_keeps_its_own_tab_open():
    """У ВРИ отдельная вкладка: свёрнутая группа была бы там единственным
    содержимым, и вкладка открывалась бы пустой."""
    vri = [item for item in render({}) if item["name"] == core.FIELD_GROUPS[1][0]]
    assert vri and vri[0]["open"] is True


def test_every_group_is_still_rendered():
    """Свернули, а не спрятали: поля на месте, их просто не видно сразу."""
    assert len(render({})) == len(core.FIELD_GROUPS)


# --- заголовок говорит, что внутри ----------------------------------------------

def test_a_collapsed_group_shows_its_key_numbers():
    peek = {item["name"]: item["peek"] for item in render(
        {"apartment_price_th": 350, "share_before_rve_pct": 85})}
    assert "350" in peek["Продажи"] and "85" in peek["Продажи"]
    assert "тыс. ₽/м²" in peek["Продажи"]


def test_a_switched_off_object_says_only_that():
    """Площадь выключенного объекта в выручку не входит — показывать её значит
    обещать метры, которых в расчёте нет."""
    peek = {item["name"]: item["peek"] for item in render({"offices_enabled": False})}
    assert peek["МФОЦ / офисы"] == "выключен"


def test_a_switched_on_object_shows_its_size():
    peek = {item["name"]: item["peek"] for item in render(
        {"offices_enabled": True, "offices_gba_sqm": 125160})}
    assert "125" in peek["МФОЦ / офисы"]


def test_the_unit_hint_is_cut_at_the_semicolon():
    """У части полей за единицей идёт пояснение через точку с запятой — в
    заголовке ему места нет."""
    peek = {item["name"]: item["peek"] for item in render({"pre_pf_own_funds_mln": 3199.9})}
    assert "млн ₽" in peek["Финансирование"]
    assert "тратятся" not in peek["Финансирование"]


def test_a_zero_is_not_a_summary():
    """«0 млн ₽» в заголовке читается как посчитанный ноль, а на деле это
    незаполненное поле."""
    peek = {item["name"]: item["peek"] for item in render(
        {"pre_pf_own_funds_mln": 0, "pf_spread_pp": 4.5})}
    assert peek["Финансирование"] == "4,5 п.п."


def test_a_repeated_unit_is_printed_once():
    """«110 тыс. ₽/м² ГНС · 120 тыс. ₽/м² ГНС» — половина строки уходит на
    повтор единицы."""
    peek = {item["name"]: item["peek"] for item in render(
        {"main_above_th_per_sqm": 190, "main_under_th_per_sqm": 120})}
    assert peek["Строительство"] == "190 · 120 тыс. ₽/м² ГНС"


def test_the_open_group_hides_its_peek():
    """Развёрнутая группа показывает сами поля — повтор в заголовке лишний."""
    assert 'details[open]>summary>.group-peek{display:none}' in PAGE


# --- заголовок не отстаёт от поля -----------------------------------------------

def test_the_peek_follows_the_field():
    """Прежнее число в заголовке выглядит как посчитанное — обновляем."""
    tail = ("inputs.apartment_price_th=650;refreshGroupPeeks();"
            "console.log(JSON.stringify(groups()));")
    peek = {item["name"]: item["peek"] for item in
            render({"apartment_price_th": 350}, tail)}
    assert "650" in peek["Продажи"] and "350" not in peek["Продажи"]


def test_the_peek_disappears_when_the_object_is_switched_on():
    tail = ("inputs.offices_enabled=true;inputs.offices_gba_sqm=125160;"
            "refreshGroupPeeks();console.log(JSON.stringify(groups()));")
    peek = {item["name"]: item["peek"] for item in
            render({"offices_enabled": False}, tail)}
    assert peek["МФОЦ / офисы"] != "выключен"
    assert "125" in peek["МФОЦ / офисы"]


def test_the_change_handler_refreshes_the_peek():
    """Обновление живёт в обработчике поля, а не только в перерисовке."""
    body = page_function("renderInputs")
    assert "refreshGroupPeeks()" in body


# --- список групп берётся из движка ---------------------------------------------

def test_the_peek_map_names_existing_groups():
    """Опечатка в названии группы молча оставила бы заголовок пустым."""
    listed = re.findall(r"^ '([^']+)':", PAGE[PAGE.index("const GROUP_PEEK={"):
                                              PAGE.index("function groupPeek(")], re.M)
    known = {group[0] for group in core.FIELD_GROUPS}
    assert listed and set(listed) <= known


def test_the_peek_map_names_existing_fields():
    fields = {field[0] for group in core.FIELD_GROUPS for field in group[1]}
    block = PAGE[PAGE.index("const GROUP_PEEK={"):PAGE.index("function groupPeek(")]
    named = set(re.findall(r"'([a-z_0-9]+)'", block)) - {group[0] for group in core.FIELD_GROUPS}
    assert named <= fields, named - fields
