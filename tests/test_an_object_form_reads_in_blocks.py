"""Форма отдельно стоящего объекта читается смысловыми блоками, а не свалкой.

Двадцать полей объекта шли одной сеткой подряд — от цены до числа машино-мест
(владелец, 27.09.2026: «хаотичное нагромождение полей»). Теперь они разбиты на
подписанные блоки: «Объект», «Объём», «Сроки строительства», «Себестоимость»,
«Цена и рост цены», «Темп продаж», «Паркинг объекта», «Судьба объекта».

Блоки объявлены ОДИН раз — в `_OBJECT_SECTIONS` рядом с реестром объектов —
и страница получает их подстановкой; своей копии состава у неё нет. Поэтому
проверяется отрисованная страница, а не литералы: у каждого блока заголовок,
каждое поле объекта стоит ровно в одном блоке, и у объекта, которого в реестре
ещё нет, блоки появляются сами. На прежней вёрстке (одна сетка без заголовков)
проверки краснеют.

Запуск: python3 -m pytest tests/test_an_object_form_reads_in_blocks.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
from tests import browser  # noqa: E402

PORT = 18771

# Что видно в группе: подряд заголовки блоков и поля, каждое со своим блоком —
# ближайшим заголовком ВЫШЕ по отрисованному дереву, а не по списку движка.
PROBE = """(groups)=>{
 const out={};
 for(const name of groups){
  const det=document.querySelector(`details[data-group="${CSS.escape(name)}"]`);
  if(!det){out[name]=null;continue}
  let head=null;const heads=[];const fields=[];
  for(const node of det.querySelectorAll('.field-section, .field[data-field]')){
   if(node.classList.contains('field-section')){
    head=node.textContent.trim();
    const box=node.getBoundingClientRect();
    // Блок — отдельная карточка: заголовок и поля внутри одной рамки с
    // фоном, заголовок крупнее подписи поля. Мелкая серая строка над общей
    // сеткой блоком не читалась (владелец, 27.09.2026).
    const card=node.closest('.field-card');
    const look=card?getComputedStyle(card):null;
    const label=det.querySelector('.field label');
    heads.push({title:head,visible:box.height>0,
     card:!!card&&card.dataset.section===head,
     framed:!!look&&(look.backgroundColor!=='rgba(0, 0, 0, 0)'||parseFloat(look.borderTopWidth)>0),
     bigger:parseFloat(getComputedStyle(node).fontSize)>(label?parseFloat(getComputedStyle(label).fontSize):0)});
   }else{
    const card=node.closest('.field-card');
    fields.push([node.dataset.field,head,card?card.dataset.section:null]);
   }
  }
  out[name]={heads,fields};
 }
 return out;
}"""

# Объект, которого в реестре нет: метры, свой гараж с продажей и признак
# «что с объектом дальше» — все ветви формы сразу.
FUTURE = core.StandaloneObject(
    "hotel", "hotel", "гостиница", 2, True, True, "sqm",
    "hotel_cost_th_per_sqm", "hotel_price_th_per_sqm",
    sale_gate="hotel_disposition",
    defaults={"gba_sqm": 8000, "saleable_sqm": 5000,
              "cost_th_per_sqm": 180, "price_th_per_sqm": 400},
    tep_label="Гостиница", group_label="Гостиница (будущий объект)")

SECTION_TITLES = [title for title, _ in core._OBJECT_SECTIONS]


def _expected(obj: core.StandaloneObject) -> list[str]:
    return [f[0] for f in core.standalone_object_group(obj)[1]
            if f[0] not in core.CLASS_ONLY_INPUTS]


def _check(name: str, got: dict | None, keys: list[str]) -> None:
    assert got is not None, f"группа «{name}» не отрисована"
    titles = [h["title"] for h in got["heads"]]
    assert titles, f"«{name}»: ни одного заголовка блока — поля идут одной свалкой"
    assert all(h["visible"] for h in got["heads"]), f"«{name}»: заголовок блока не виден"
    assert all(h["card"] for h in got["heads"]), f"«{name}»: блок не отдельной карточкой"
    assert all(h["framed"] for h in got["heads"]), f"«{name}»: карточка без фона и рамки"
    assert all(h["bigger"] for h in got["heads"]), (
        f"«{name}»: заголовок блока не крупнее подписи поля")
    outside = [f[0] for f in got["fields"] if f[2] != f[1]]
    assert not outside, f"«{name}»: поля вне карточки своего блока: {outside}"
    assert len(titles) == len(set(titles)), f"«{name}»: блок разорван надвое: {titles}"
    assert all(t in SECTION_TITLES for t in titles), (
        f"«{name}»: блок вне объявленных — {titles}")
    assert titles == sorted(titles, key=SECTION_TITLES.index), (
        f"«{name}»: блоки не в объявленном порядке: {titles}")
    seen = [key for key, *_ in got["fields"]]
    assert sorted(seen) == sorted(keys) and len(seen) == len(set(seen)), (
        f"«{name}»: поля на экране не совпали с формой объекта ровно по одному")
    orphans = [key for key, head, *_ in got["fields"] if head is None]
    assert not orphans, f"«{name}»: поля вне всякого блока: {orphans}"
    used = {head for _, head, *_ in got["fields"]}
    assert used == set(titles), f"«{name}»: заголовок без полей: {set(titles) - used}"


def test_every_object_field_has_a_declared_block() -> None:
    # Поле без блока ушло бы в «Прочее»: не пропало, но и не разложено.
    for obj in core.STANDALONE_OBJECTS + (FUTURE,):
        for field in core.standalone_object_group(obj)[1]:
            section = core.standalone_object_section(obj, field[0])
            assert section != core.OBJECT_SECTION_UNASSIGNED, (
                f"{field[0]}: блок не назначен — впишите окончание ключа "
                "в `_OBJECT_SECTIONS`")


def test_a_block_is_one_run_of_fields() -> None:
    # Порядок полей группирует движок; страница начинает новый блок там, где
    # блок сменился, — значит блок, разорванный в списке, разорвался бы и на экране.
    for obj in core.STANDALONE_OBJECTS + (FUTURE,):
        runs = [core.standalone_object_section(obj, f[0])
                for f in core.standalone_object_group(obj)[1]]
        collapsed = [s for i, s in enumerate(runs) if i == 0 or runs[i - 1] != s]
        assert len(collapsed) == len(set(collapsed)), f"{obj.key}: {collapsed}"


def test_the_page_draws_the_blocks_of_every_object() -> None:
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    # Экземпляр своей группы не имеет: он вкладка в блоке своего типа.
    groups = [o.group_label for o in core.OBJECT_TYPES]
    seconds = {base.key: core.object_instance(base, 2) for base in core.OBJECT_TYPES
               if base.duplicable}
    future = core.standalone_object_group(FUTURE)
    future_sections = {f[0]: core.standalone_object_section(FUTURE, f[0])
                       for f in future[1]}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelectorAll('details[data-group]').length>3",
                                   timeout=20000)
            got = page.evaluate(PROBE, groups)
            # Вкладка второго экземпляра каждого типа — те же блоки своими полями.
            page.evaluate("""(types)=>{types.forEach(t=>{OBJECT_TAB[t]=addObjectInstance(t)});
              renderInputs();}""", list(seconds))
            got_seconds = page.evaluate(PROBE, groups)
            # Будущий объект — строкой реестра, дописанной в ту же форму, и
            # настоящей перерисовкой страницы: своей раскладки у него нет.
            page.evaluate("""([group,sections])=>{
              FIELD_GROUPS.push(group);Object.assign(FIELD_SECTIONS,sections);
              renderInputs();}""", [future, future_sections])
            got_future = page.evaluate(PROBE, [future[0]])
    for obj in core.OBJECT_TYPES:
        _check(obj.group_label, got[obj.group_label], _expected(obj))
        if obj.key in seconds:
            _check(obj.group_label + " · объект 2", got_seconds[obj.group_label],
                   _expected(seconds[obj.key]))
    _check(future[0], got_future[future[0]], _expected(FUTURE))
    # Деньги метров и деньги мест — в разных блоках, как бы ни звалось поле.
    offices = {f[0]: f[1] for f in got["МФОЦ / офисы"]["fields"]}
    assert offices["offices_cost_th_per_sqm"] == "Себестоимость"
    assert offices["offices_price_th_per_sqm"] == "Цена и рост цены"
    assert offices["offices_parking_under_spaces"] == "Паркинг объекта"
    above = {f[0]: f[1] for f in got["Наземный паркинг"]["fields"]}
    assert above["above_parking_spaces"] == "Объём"
    assert above["above_parking_cost_mln_per_space"] == "Себестоимость"
    assert {f[0]: f[1] for f in got["ФОК / медцентр"]["fields"]}["sports_disposition"] == "Судьба объекта"
