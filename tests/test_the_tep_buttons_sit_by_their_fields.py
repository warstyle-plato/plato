"""Кнопки вкладки «ТЭП» стоят у своих полей и говорят по-человечески.

Владелец (18.10.2026): меню «Действия с ТЭП» под таблицей было свалкой из
трёх кнопок с названиями, «понятными только ИИ», и телеграфными пояснениями.
Теперь:

- «Заполнить таблицу по площади и плотности» — в карточке участка, у полей
  площади и плотности. Перезаписывает строки, поэтому сначала показывает, что
  изменится (строка, было → будет), и меняет только по подтверждению; отказы
  (гостиница, нежилой, нет площади) идут сразу к объяснению отказа.
- «Пересчитать по нормативам» — сразу под таблицей: детсады, школы,
  поликлиника и машино-места под нынешнюю площадь квартир. Подсказка называет
  дорогу, которой пойдёт действие (ГлавАПУ, пропорция или норматив), без
  жаргона. Дорогу решает один предикат — его читают и действие, и подсказка.
- «Подтянуть значения из «Экономики» (МФЦ, ТЦ, паркинг и др.)» — под
  таблицей, вторичная: правка вводных обновляет строки сама
  (`TEP_DERIVED_INPUTS` → `syncTep`), кнопка нужна, когда число разошлось с
  полем. Длинная подпись переносится и не вылезает за экран телефона.

Проверяется настоящий код страницы: стенд на node через page_blocks и
отрисованная страница в Chromium на ширине телефона.

Запуск: python3 -m pytest tests/test_the_tep_buttons_sit_by_their_fields.py -q
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


def _tep_panel() -> str:
    page = core.PAGE
    return page[page.index('<div id="tep" class="panel">'):page.index('<div id="vri" class="panel">')]


# Слова, которые посетитель без подготовки не понимает: им не место ни в
# названиях кнопок, ни в пояснениях к ним.
JARGON = ("РНГП", "производн", "пропорции не от чего", "ГНС", "СПП", "ТЭП по")


def test_each_button_sits_by_the_fields_it_reads() -> None:
    tep = _tep_panel()
    assert 'id="tepActionsMenu"' not in tep and "Действия с ТЭП" not in tep, \
        "отдельное меню «Действия с ТЭП» вернулось"
    site = tep[tep.index('class="card site-card"'):tep.index('id="tepBody"')]
    assert 'onclick="formTepByDensity()">Заполнить таблицу по площади и плотности<' in site, \
        "кнопка заполнения по плотности не в карточке участка"
    assert site.index('id="siteDensity"') < site.index('onclick="formTepByDensity()"')
    table_card = tep[tep.index('id="tepBody"'):tep.index('id="tepSettingsCard"')]
    assert 'onclick="recalcFromTep()">Пересчитать по нормативам<' in table_card, \
        "кнопка пересчёта по нормативам не под таблицей"
    assert 'onclick="syncTep()">Подтянуть значения из «Экономики» (МФЦ, ТЦ, паркинг и др.)<' in table_card, \
        "кнопки «Подтянуть значения из «Экономики»» нет под таблицей"
    for old in ("Сформировать ТЭП по плотности", "Пересчитать нормативы по ТЭП",
                "Обновить производные ТЭП из вводных"):
        assert old not in core.PAGE, f"старая подпись «{old}» осталась на странице"
    hint = re.search(r'id="siteApplyHint">([^<]*)<', site).group(1)
    for word in JARGON:
        assert word not in hint, f"в пояснении к кнопке жаргон «{word}»"
    # Экономика проекта — отдельной командой в шапке.
    assert "Пересчитать модель" in core.PAGE[:core.PAGE.index('<div id="tep" class="panel">')]


def test_the_overlay_speaks_plainly_too() -> None:
    overlay = (Path(__file__).resolve().parent.parent / "ia_preview" / "assets" / "overlay.js").read_text()
    block = overlay[overlay.index("var hint = document.getElementById('siteApplyHint');"):]
    block = block[:block.index("/* Тексты")]
    texts = re.findall(r"'([^']*)'", block)
    said = " ".join(texts)
    assert "нажмите" in said
    for word in JARGON:
        assert word not in said, f"слой пишет в пояснение жаргон «{word}»"
    assert "Действиях с ТЭП" not in overlay and "Сформировать ТЭП" not in overlay
    assert "#tep [onclick=\"syncTep()\"]" in overlay, "слой не замечает пропажу кнопки «Экономики»"


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
confirmTepAction();           // «Заполнить»
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


def test_the_norms_hint_names_the_route_and_says_whether_it_runs_by_itself() -> None:
    tail = """
const modes=[],autos=[],hints=[];
const look=()=>{const m=tepNormsMode();modes.push(m.key);autos.push(m.auto);hints.push(m.text)};
look();                                                           // ни ГлавАПУ, ни базы
inputs._social_basis={apartment_area_sqm:30000,source:'тест'};
look();                                                           // база есть, квартиры изменились
tep.apartments.saleable=30000;
look();                                                           // база равна ТЭП — пропорции нет
cadastralAnalysis={territory:{district:'Красногорск',inside_moscow:false}};
look();                                                           // область, расчёт не загружен
inputs._mo_calc={territory:{district:'Красногорск'}};
look();                                                           // Подмосковье
let moCalled=null;
recalcMoFromApartments=(apartments,area)=>{moCalled={apartments,area}};
recalcFromTep();
inputs._glavapu_import={normalized:{change_vri_mln:12}};
look();                                                           // выгрузка с платой за ВРИ
renderTepActions();
process.stdout.write(JSON.stringify({modes,autos,hints,moCalled,hint:nodes.tepNormsHint.textContent}));
"""
    out = page_blocks.run_json(PRELUDE, tail)
    assert out["modes"] == ["norms", "proportion", "norms", "region", "mo", "glavapu"]
    # Сам пересчёт идёт только там, где его зовёт scheduleTepAutoRecalc.
    assert out["autos"] == [False, False, False, False, True, True]
    for text, auto in zip(out["hints"], out["autos"]):
        assert text.startswith("Если вы ввели новые площади квартир"), text
        assert ("пересчитываются сами" in text) == auto, text
        assert bool(re.search(r"сами (они здесь )?не", text)) == (not auto), text
        for word in JARGON:
            assert word not in text, f"в подсказке «Пересчитать по нормативам» жаргон «{word}»"
    # Вне Москвы подсказка не обещает московских нормативов.
    assert "нормативам Москвы" not in out["hints"][3] and "Впишите" in out["hints"][3]
    assert "Московской области" in out["hints"][4] and "Москвы" not in out["hints"][4].replace("Московской", "")
    assert "ГлавАПУ" in out["hint"]
    # В Подмосковье кнопка идёт тем же пересчётом области, а не московским.
    assert out["moCalled"] == {"apartments": 30000, "area": 2}
    # Решение о маршруте — один предикат: его читают и действие, и подсказка.
    assert "glavapuBaselineApplies()" in page_blocks.function("recalcFromTep")
    assert "tepNormsMode()" in page_blocks.function("recalcFromTep")
    assert "socialRescaleApplies()" in page_blocks.function("rescaleSocialFromTep")
    assert "glavapuBaselineApplies()" in page_blocks.function("tepNormsMode")
    assert "socialRescaleApplies()" in page_blocks.function("tepNormsMode")
    # «Сам» в подсказке — то же условие, что у автопересчёта.
    auto = page_blocks.function("scheduleTepAutoRecalc")
    assert "change_vri_mln" in auto and "inputs._mo_calc" in auto


PROBE = """()=>{
 const top=el=>Math.round(el.getBoundingClientRect().top+window.scrollY);
 const btn=document.querySelector('#tep [onclick="formTepByDensity()"]');
 const site=btn.closest('.card');
 const norms=document.querySelector('#tep [onclick="recalcFromTep()"]');
 const out={inSiteCard:site.classList.contains('site-card'),buttonTop:top(btn),
  tableTop:top(document.querySelector('#tep .teptable')),normsTop:top(norms),
  parkingTop:top(document.getElementById('siteParkingBox')),
  normsHint:document.getElementById('tepNormsHint').textContent,
  siteHint:document.getElementById('siteApplyHint').textContent,
  sync:!!document.querySelector('#tep [onclick="syncTep()"]'),
  syncTop:top(document.querySelector('#tep [onclick="syncTep()"]')),
  inside:[...document.querySelectorAll('#tep .tep-action .btn')].every(b=>{const r=b.getBoundingClientRect();return r.left>=0&&r.right<=window.innerWidth}),
  menu:!!document.getElementById('tepActionsMenu')};
 out.buttonVisible=btn.getBoundingClientRect().height>0&&norms.getBoundingClientRect().height>0;
 out.pageScroll=document.documentElement.scrollWidth-window.innerWidth;
 const was={gns:tep.apartments.gns,saleable:tep.apartments.saleable};
 inputs._glavapu_import={normalized:{}};
 btn.click();
 const dialog=document.getElementById('tepConfirmDialog');
 out.dialogShown=getComputedStyle(dialog).display==='flex';
 out.dialogTitle=document.getElementById('tepConfirmTitle').textContent;
 out.dialogText=document.getElementById('tepConfirmBody').textContent;
 closeTepConfirm();
 out.untouched=tep.apartments.gns===was.gns&&tep.apartments.saleable===was.saleable;
 btn.click();
 document.getElementById('tepConfirmOk').click();
 out.changed=tep.apartments.gns!==was.gns;
 out.expected=Math.abs(tep.apartments.gns-Number(inputs.site_area_ha)*effectiveSiteDensity()*MKD_SPP_SPLIT.apartments)<0.01;
 out.dialogClosed=getComputedStyle(dialog).display==='none';
 return out;}"""


def test_on_a_phone_the_buttons_sit_by_their_fields_and_confirm_first() -> None:
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 375, "height": 900})
            page.goto(base, wait_until="load")
            browser.wait_for_result(page)
            page.evaluate("async()=>{inputs.site_area_ha=2;inputs.site_density_sqm_per_ha=25000;"
                          "syncTep(false);await settledCalculate();renderTep();openTab('tep');}")
            page.wait_for_function("document.querySelectorAll('#tepBody tr').length>3", timeout=20000)
            got = page.evaluate(PROBE)
            page.close()
    assert got["inSiteCard"] and got["buttonTop"] < got["tableTop"], \
        "кнопка заполнения по плотности не в карточке участка"
    assert got["tableTop"] < got["normsTop"] < got["parkingTop"], \
        "кнопка пересчёта по нормативам не сразу под таблицей"
    assert not got["menu"], "меню «Действия с ТЭП» вернулось"
    assert got["sync"] and got["normsTop"] < got["syncTop"] < got["parkingTop"], \
        "«Подтянуть значения из «Экономики»» не под таблицей"
    assert got["inside"], "кнопка вылезает за экран телефона"
    assert got["normsHint"].startswith("Если вы ввели новые площади квартир"), got["normsHint"]
    for word in JARGON:
        assert word not in got["normsHint"] + got["siteHint"], f"на экране жаргон «{word}»"
    assert got["buttonVisible"] and got["pageScroll"] <= 0
    assert got["dialogShown"] and "Квартиры" in got["dialogText"]
    assert got["dialogTitle"] == "Заполнить таблицу по площади и плотности"
    assert got["untouched"], "«Отмена» изменила ТЭП"
    assert got["changed"] and got["expected"], "«Заполнить» не заменил квартиры площадью × плотностью"
    assert got["dialogClosed"]
