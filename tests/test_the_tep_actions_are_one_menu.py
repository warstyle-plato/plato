"""«Действия с ТЭП» — одно свёрнутое меню под таблицей, а не три кнопки над ней.

Владелец (17.10.2026): три конкурирующие кнопки пересчёта перед таблицей не
объясняли, что и в каком порядке нажимать и какая из них перезапишет
введённое. Теперь под таблицей одно меню с тремя РАЗНЫМИ действиями:

- «Сформировать ТЭП по плотности» — перезаписывает строки, поэтому сначала
  показывает, что изменится (строка, было → будет), и меняет только по
  подтверждению; отказы (гостиница, нежилой, нет площади) идут сразу к
  объяснению отказа — там выбор, куда класть потенциал.
- «Пересчитать нормативы по ТЭП» — ручное действие; подсказка называет
  режим, которым оно пойдёт: ГлавАПУ, пропорция или норматив. Режим решает
  один предикат, и его читают и действие, и подсказка.
- «Подтянуть строки из «Вводных»» (бывшая «Обновить производные ТЭП из
  вводных») — вторичное действие; подпись говорит, когда она нужна.

«Пересчитать модель» остаётся в шапке. Проверяется настоящий код страницы:
стенд на node через page_blocks и отрисованная страница в Chromium.

Запуск: python3 -m pytest tests/test_the_tep_actions_are_one_menu.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402
from tests import browser  # noqa: E402

PORT = 18797


def _menu() -> str:
    match = re.search(r'<details[^>]*id="tepActionsMenu"[^>]*>(.*?)</details>', core.PAGE, re.S)
    assert match, "меню «Действия с ТЭП» на странице нет"
    return match.group(0)


def test_the_three_actions_live_in_one_closed_menu() -> None:
    menu = _menu()
    assert " open" not in menu[:menu.index(">") + 1], "меню раскрыто по умолчанию"
    for label, call in [("Сформировать ТЭП по плотности", "formTepByDensity()"),
                        ("Пересчитать нормативы по ТЭП", "recalcFromTep()"),
                        ("Подтянуть строки из «Вводных»", "syncTep()")]:
        assert f'onclick="{call}">{label}<' in menu, f"в меню нет «{label}» → {call}"
    page = core.PAGE
    tep = page[page.index('<div id="tep" class="panel">'):page.index('<div id="vri" class="panel">')]
    for old in ("Рассчитать ТЭП от площади и плотности", "Пересчитать по параметрам исходного расчёта"):
        assert old not in tep, f"старая подпись «{old}» осталась на вкладке"
    # Кнопки — только в меню: над таблицей их нет.
    before_table = tep[:tep.index('id="tepBody"')]
    assert "onclick=\"formTepByDensity()\"" not in before_table
    assert "onclick=\"recalcFromTep()\"" not in before_table
    # Экономика проекта — отдельной командой в шапке, не в меню.
    assert "calculate()" not in menu
    assert "Пересчитать модель" in page[:page.index('<div id="tep" class="panel">')]


PRELUDE = """
function mk(tag){return {tag,children:[],style:{},dataset:{},innerHTML:'',textContent:'',value:'',
 appendChild(c){this.children.push(c);return c},contains(){return false},closest(){return null}};}
const nodes={};
const document={activeElement:null,createElement:mk,
 getElementById:id=>(nodes[id]=nodes[id]||mk(id)),querySelector(){return null},querySelectorAll(){return []}};
let phaseBundle=null,lastResult=null,cadastralAnalysis=null,moResult=null;
let inputs={site_area_ha:2,site_density_sqm_per_ha:25000,project_kind:'mixed'};
let tep={apartments:{gns:60000,total_area:54000,saleable:39000,useful:39000,units:600},
 ground_commercial:{gns:4000,total_area:3600,saleable:3600,useful:3600}};
let applied=0;
function applyDensityToTep(){applied+=1}
function projectKind(){return inputs.project_kind}
function effectiveSiteDensity(){return Number(inputs.site_density_sqm_per_ha||0)}
const MKD_SPP_SPLIT={apartments:0.94,ground_commercial:0.06};
"""


def test_forming_by_density_shows_what_changes_and_waits_for_the_answer() -> None:
    tail = """
inputs._glavapu_import={normalized:{}};
formTepByDensity();
const shown=nodes.tepConfirmDialog.style.display;
const body=nodes.tepConfirmBody.innerHTML;
const before=applied;
closeTepConfirm();            // «Отмена»
const afterCancel=applied;
formTepByDensity();
confirmTepAction();           // «Сформировать»
const plan=densityTepPlan();
inputs._glavapu_import=null;
const normative=densityTepPlan();
inputs.project_kind='hotel';
const hotel=densityTepPlan();
formTepByDensity();           // отказ — без окна, сразу к объяснению
process.stdout.write(JSON.stringify({shown,body,before,afterCancel,applied,plan,normative,hotel,
 closed:nodes.tepConfirmDialog.style.display}));
"""
    out = page_blocks.run_json(PRELUDE, tail)
    assert out["shown"] == "flex", "окно подтверждения не показано"
    assert out["before"] == 0 and out["afterCancel"] == 0, "ТЭП заменён до подтверждения"
    assert out["applied"] == 2, "по «Сформировать» замена не выполнена (или выполнена дважды)"
    assert "Квартиры" in out["body"] and "Коммерция 1 этажа" in out["body"]
    # Было → будет: прежние числа строки и новые от площади × плотности.
    rows = {r["label"]: r for r in out["plan"]["rows"]}
    assert rows["Квартиры"]["was"]["gns"] == 60000
    assert abs(rows["Квартиры"]["will"]["gns"] - 2 * 25000 * 0.94) < 1e-6
    assert abs(rows["Квартиры"]["will"]["saleable"] - 2 * 25000 * 0.94 * 0.65) < 1e-6
    assert abs(rows["Коммерция 1 этажа"]["will"]["gns"] - 2 * 25000 * 0.06) < 1e-6
    assert any("ГлавАПУ" in n for n in out["plan"]["notes"])
    # Без ГлавАПУ — нормативная ветка: квартиры = площадь × плотность, остальное РНГП.
    assert out["normative"]["mode"] == "normative"
    assert out["normative"]["rows"][0]["will"]["saleable"] == 2 * 25000
    assert any("РНГП" in n for n in out["normative"]["notes"])
    assert out["hotel"] is None
    assert out["closed"] == "none"


def test_the_norms_hint_names_the_route_the_action_takes() -> None:
    tail = """
const modes=[];
modes.push(tepNormsMode().key);                                   // ни ГлавАПУ, ни базы
inputs._social_basis={apartment_area_sqm:30000,source:'тест'};
modes.push(tepNormsMode().key);                                   // база есть, квартиры изменились
tep.apartments.saleable=30000;
modes.push(tepNormsMode().key);                                   // база равна ТЭП — пропорции нет
inputs._glavapu_import={normalized:{change_vri_mln:12}};
modes.push(tepNormsMode().key);                                   // выгрузка с платой за ВРИ
renderTepActions();
process.stdout.write(JSON.stringify({modes,hint:nodes.tepNormsHint.textContent}));
"""
    out = page_blocks.run_json(PRELUDE, tail)
    assert out["modes"] == ["norms", "proportion", "norms", "glavapu"]
    assert "ГлавАПУ" in out["hint"]
    # Решение о маршруте — один предикат: его читают и действие, и подсказка.
    assert "glavapuBaselineApplies()" in page_blocks.function("recalcFromTep")
    assert "socialRescaleApplies()" in page_blocks.function("rescaleSocialFromTep")
    assert "glavapuBaselineApplies()" in page_blocks.function("tepNormsMode")
    assert "socialRescaleApplies()" in page_blocks.function("tepNormsMode")


PROBE = """()=>{
 const top=el=>Math.round(el.getBoundingClientRect().top+window.scrollY);
 const menu=document.getElementById('tepActionsMenu');
 const out={menuOpen:menu.open,menuTop:top(menu),tableTop:top(document.querySelector('#tep .teptable'))};
 menu.open=true;
 const btn=document.querySelector('#tep [onclick="formTepByDensity()"]');
 out.buttonVisible=btn.getBoundingClientRect().height>0;
 out.pageScroll=document.documentElement.scrollWidth-window.innerWidth;
 const was={gns:tep.apartments.gns,saleable:tep.apartments.saleable};
 inputs._glavapu_import={normalized:{}};
 btn.click();
 const dialog=document.getElementById('tepConfirmDialog');
 out.dialogShown=getComputedStyle(dialog).display==='flex';
 out.dialogText=document.getElementById('tepConfirmBody').textContent;
 closeTepConfirm();
 out.untouched=tep.apartments.gns===was.gns&&tep.apartments.saleable===was.saleable;
 btn.click();
 document.getElementById('tepConfirmOk').click();
 out.changed=tep.apartments.gns!==was.gns;
 out.expected=Math.abs(tep.apartments.gns-Number(inputs.site_area_ha)*effectiveSiteDensity()*MKD_SPP_SPLIT.apartments)<0.01;
 out.dialogClosed=getComputedStyle(dialog).display==='none';
 return out;}"""


def test_on_a_phone_the_menu_confirms_before_it_overwrites() -> None:
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 390, "height": 900})
            page.goto(base, wait_until="load")
            browser.wait_for_result(page)
            page.evaluate("async()=>{inputs.site_area_ha=2;inputs.site_density_sqm_per_ha=25000;"
                          "syncTep(false);await settledCalculate();renderTep();openTab('tep');}")
            page.wait_for_function("document.querySelectorAll('#tepBody tr').length>3", timeout=20000)
            got = page.evaluate(PROBE)
            page.close()
    assert got["menuOpen"] is False, "меню раскрыто по умолчанию"
    assert got["menuTop"] > got["tableTop"], "меню стоит над таблицей"
    assert got["buttonVisible"] and got["pageScroll"] <= 0
    assert got["dialogShown"] and "Квартиры" in got["dialogText"]
    assert got["untouched"], "«Отмена» изменила ТЭП"
    assert got["changed"] and got["expected"], "«Сформировать» не заменил квартиры площадью × плотностью"
    assert got["dialogClosed"]
