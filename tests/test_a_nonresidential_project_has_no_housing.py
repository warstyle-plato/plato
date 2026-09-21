"""Нежилой проект: ни жилья, ни соцнагрузки, ни платы за смену ВРИ.

Владелец, 16.09.2026: «если нужен режим расчёта нежилья, где нет ни КРТ ни
ВРИ ничего. Как его отдельно включать? Где-то кнопку у ввода кадастр?»
Кнопка — НЕ у кадастра: он отвечает на «где», а тип проекта на «что строим»,
и проект приезжает ещё файлом, ссылкой и мостом КРТ, минуя это поле вовсе.
Место — в шапке рядом с классом.

Замер на живой странице до правки (офисник 60 000 м², квартиры обнулены
руками) показал, ЧТО именно переживает обнуление жилья: подземный паркинг
1 199 мест и 41 965 м², садик на 250 мест и плата за ВРИ 2 864 млн ₽ — всё
это шло в CAPEX, в расчётный лимит БРИДЖа и в книгу как настоящее. Значит
режим обязан обнулить их сам и НАЗВАТЬ убранное: «не тронули» читается как
«убрали», а молчаливое обнуление врёт не меньше молчаливого сохранения.

Утверждений здесь пять, и каждое своё:

  — состав типов объявлен один раз, в движке (копии на странице нет);
  — движок НЕ убирает жильё сам, а называет оставшееся: вводная принадлежит
    человеку, а проект приходит и мимо страницы;
  — двор у нежилого проекта не «нечего благоустраивать», а «мерить нечем» —
    население тут не драйвер, и база у него своя, ставка на метр ГНС;
  — финансирование режим не трогает вовсе (решение владельца того же дня:
    214-ФЗ нежильё не исключает — ст. 1 ч. 1 «иных объектов недвижимости»);
  — страница обнуляет, запирает и называет, а убранное можно вернуть.

Последнее проверяется настоящим Chromium: в исходнике страница со сломанным
режимом выглядит так же, как с работающим.

Запуск: python3 -m pytest tests/test_a_nonresidential_project_has_no_housing.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18947


def _objects_only() -> tuple[dict, dict]:
    """Проект из одного офисника: жилья нет вовсе, платить банку есть чем."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        x[key] = 0
    x.update(offices_enabled=True, offices_gba_sqm=60000, offices_price_th=300,
             purchase_price_mln=500)
    return x, t


def test_the_kinds_are_declared_once() -> None:
    """Состав типов — из движка; на странице копии нет."""
    assert core.DEFAULT_INPUTS["project_kind"] == core.PROJECT_KIND_MIXED
    keys = [pair[0] for pair in core.PROJECT_KINDS]
    assert keys == [core.PROJECT_KIND_MIXED, core.PROJECT_KIND_NONRESIDENTIAL]
    page = core.PAGE
    assert "__DEVELOPAID_PROJECT_KINDS__" not in page
    assert "__DEVELOPAID_NONRESIDENTIAL_INPUTS__" not in page
    # Два написанных руками `<option>` были бы копией, которую негде
    # обновлять: третий тип проекта молчал бы на странице.
    for key in keys:
        assert f'<option value="{key}"' not in page, "состав типов переписан на странице"
    # А сам список на страницу доехал — иначе селектор пуст.
    assert '"nonresidential"' in page
    assert f'"{dict(core.PROJECT_KINDS)[core.PROJECT_KIND_NONRESIDENTIAL]}"' in page


def test_the_engine_names_what_is_left_of_housing() -> None:
    """Оставшееся жильё названо поимённо, а не убрано молча."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    # Предохранитель: на умолчаниях жильё ЕСТЬ. Без него проверка зелена на
    # любом коде — называть было бы нечего.
    assert float(t["apartments"]["saleable"]) > 0
    assert float(x["kindergarten_places"]) > 0
    assert float(x["land_rights_cost_mln"]) > 0

    assert core.nonresidential_leftovers(x, t) == [], "у жилого проекта остатков не бывает"

    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    left = core.nonresidential_leftovers(x, t)
    joined = " | ".join(left)
    assert "Квартиры" in joined
    assert "места ДОО" in joined
    assert "плата за смену ВРИ" in joined

    # Ноль — не остаток: строка о нём читалась бы как найденное жильё.
    clean_x, clean_t = _objects_only()
    clean_x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    assert core.nonresidential_leftovers(clean_x, clean_t) == []


def test_the_engine_does_not_clear_it_itself() -> None:
    """Вводная принадлежит человеку: движок говорит, а не правит."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    was_fee = float(x["land_rights_cost_mln"])
    was_flats = float(t["apartments"]["saleable"])
    result = core.calculate(core.CalcRequest(inputs=x, tep=t))
    assert float(x["land_rights_cost_mln"]) == was_fee
    assert float(t["apartments"]["saleable"]) == was_flats
    # И сказано это в своде — его читают отчёт и PDF.
    summary = result["summary"]
    assert summary["project_kind"] == core.PROJECT_KIND_NONRESIDENTIAL
    assert summary["project_kind_leftovers"], "оставшееся жильё нигде не названо"


def test_the_queues_carry_the_kind_to_the_verdict() -> None:
    """Свод очередей собирается ЗАНОВО, и поле до него само не доезжает.

    PDF читает свод, а не одиночный расчёт: без этих двух ключей у нежилого
    проекта с очередями не было бы ни строки «Тип проекта», ни названного
    оставшегося жилья — и молчание читалось бы как жилой проект.
    """
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    phasing = {"enabled": True, "phase_count": 2, "phases": [
        {"name": "О1", "start_offset_months": 0, "construction_months": 24,
         "products": {}},
        {"name": "О2", "start_offset_months": 12, "construction_months": 24,
         "products": {}}]}
    bundle = core._run_authoritative_model(x, t, [], phasing)
    # Предохранитель: это действительно свод очередей, а не одиночный расчёт.
    assert bundle["mode"] == "phased"
    summary = bundle["consolidated"]["summary"]
    assert summary["project_kind"] == core.PROJECT_KIND_NONRESIDENTIAL
    assert summary["project_kind_leftovers"], "оставшееся жильё до свода не доехало"


def test_the_yard_says_why_it_has_no_area() -> None:
    """Ноль двора — ответ методики, и у него разные причины."""
    x, t = _objects_only()
    mixed = core.landscaping_area(x, t)
    assert mixed[0] == 0.0
    assert "квартир в проекте нет" in mixed[1]

    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    area, basis = core.landscaping_area(x, t)
    assert area == 0.0
    assert "благоустраивать нечего" not in basis, "у нежилого проекта двор есть"
    assert "ставку на метр ГНС" in basis, "не сказано, чем его мерить"

    # У жилого проекта двор по-прежнему считается населением.
    home_x = copy.deepcopy(core.DEFAULT_INPUTS)
    home_area, home_basis = core.landscaping_area(home_x, core.TEP_DEFAULT)
    assert home_area > 0 and "чел." in home_basis


def test_the_mode_does_not_touch_the_financing() -> None:
    """Режим — про вводные, а не про методику денег.

    Решение владельца 16.09.2026: «оставляем второе и ничего не пишем». Я
    предлагал считать нежильё инвесткредитом без эскроу, и посылка была
    неверной: 214-ФЗ нежильё не исключает (ст. 1 ч. 1 — «иных объектов
    недвижимости», ст. 2 п. 2 — «жилое ИЛИ НЕЖИЛОЕ помещение, машино-место»),
    единственное исключение — объекты производственного назначения.
    """
    x, t = _objects_only()
    mixed = core.calculate(core.CalcRequest(inputs=copy.deepcopy(x),
                                            tep=copy.deepcopy(t)))["summary"]
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    nonres = core.calculate(core.CalcRequest(inputs=copy.deepcopy(x),
                                             tep=copy.deepcopy(t)))["summary"]
    # Предохранитель: деньги в проекте есть, иначе сравнивать нечего.
    assert mixed["revenue"] > 0 and mixed["financing_cost"] > 0
    for key in ("revenue", "capex", "ebitda", "financing_cost", "llcr",
                "net_profit", "profit_tax"):
        assert mixed[key] == nonres[key], f"режим сдвинул {key}"


def test_the_pdf_names_the_kind_only_when_it_differs() -> None:
    """Тип обычного проекта в каждом отчёте — постоянная приписка."""
    pytest.importorskip("reportlab")
    pymupdf = pytest.importorskip("pymupdf")

    def text_of(kind: str, strip: bool) -> str:
        x = copy.deepcopy(core.DEFAULT_INPUTS)
        t = copy.deepcopy(core.TEP_DEFAULT)
        if strip:
            x, t = _objects_only()
        x["project_kind"] = kind
        x.update(offices_enabled=True, offices_gba_sqm=60000, offices_price_th=300)
        bundle = core._run_authoritative_model(x, t, [], {})
        data = core._build_developaid_pdf({
            "result": bundle["consolidated"], "inputs": x, "tep": t,
            "rates": [], "phasing": {}, "scenario": "base",
            "project_name": "Проверка"})
        assert data[:4] == b"%PDF"
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)

    assert "Тип проекта" not in text_of(core.PROJECT_KIND_MIXED, False)

    clean = text_of(core.PROJECT_KIND_NONRESIDENTIAL, True)
    assert "Тип проекта" in clean
    assert "Осталось от жилья" not in clean

    dirty = text_of(core.PROJECT_KIND_NONRESIDENTIAL, False)
    assert "Осталось от жилья" in dirty
    assert "Квартиры" in dirty


PROBE = """()=>{
  const cols=['gns','total_area','useful','saleable','transfer','units'];
  const before={
    flats: Number(tep.apartments.saleable||0),
    dou: Number(inputs.kindergarten_places||0),
    fee: Number(inputs.land_rights_cost_mln||0),
    parking: Number(tep.underground_parking.units||0),
    yardRate: Number(inputs.landscaping_gns_th_per_sqm||0),
    field: !!document.getElementById('f_kindergarten_places')
  };
  applyProjectKind('nonresidential');
  const rows={};
  Array.from(document.querySelectorAll('#tepBody tr')).forEach(tr=>{
    const inputsInRow=Array.from(tr.querySelectorAll('input[type=number]'));
    if(!inputsInRow.length)return;
    const name=(tr.cells[0].textContent||'').trim();
    rows[name]={locked: inputsInRow.every(i=>i.hasAttribute('readonly')),
                sum: inputsInRow.slice(0,6).reduce((a,i)=>a+Number(i.value||0),0)};
  });
  const note=(document.getElementById('inputGroups').querySelector('.note')||{}).textContent||'';
  const after={
    flats: Number(tep.apartments.saleable||0),
    dou: Number(inputs.kindergarten_places||0),
    fee: Number(inputs.land_rights_cost_mln||0),
    parking: Number(tep.underground_parking.units||0),
    yardRate: Number(inputs.landscaping_gns_th_per_sqm||0),
    field: !!document.getElementById('f_kindergarten_places'),
    note: note,
    rows: rows,
    flatsRow: Object.keys(rows).find(k=>k.indexOf(productName('apartments'))===0)||''
  };
  applyProjectKind('mixed');
  const backNote=(document.getElementById('inputGroups').querySelector('.note')||{}).textContent||'';
  restoreResidentialInputs();
  const restored={
    flats: Number(tep.apartments.saleable||0),
    dou: Number(inputs.kindergarten_places||0),
    fee: Number(inputs.land_rights_cost_mln||0),
    yardRate: Number(inputs.landscaping_gns_th_per_sqm||0),
    field: !!document.getElementById('f_kindergarten_places')
  };
  return {before: before, after: after, backNote: backNote, restored: restored};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            got = page.evaluate(PROBE)
            page.wait_for_timeout(600)
            page.close()
    got["errors"] = errors
    return got


def test_the_page_survives_the_switch(seen) -> None:
    assert seen["errors"] == [], "страница не доработала до конца"


def test_the_switch_clears_the_housing(seen) -> None:
    before, after = seen["before"], seen["after"]
    # Предохранитель: до переключения жильё было. Иначе обнулять нечего, и
    # проверка зелена на любом коде.
    assert before["flats"] > 0 and before["dou"] > 0 and before["fee"] > 0
    assert before["parking"] > 0, "подземный паркинг не был заполнен нормой"
    assert after["flats"] == 0
    assert after["dou"] == 0
    assert after["fee"] == 0
    assert after["parking"] == 0, "паркинг МКД пережил обнуление квартир"


def test_the_switch_names_what_it_removed(seen) -> None:
    note = seen["after"]["note"]
    assert "Нежилой проект" in note
    assert "Убрано" in note, "обнулено молча"
    assert "места ДОО" in note and "плата за смену ВРИ" in note
    # Финансирование режим не трогает — и сказано это там же.
    assert "214-ФЗ" in note


def test_the_housing_rows_are_locked_and_told_why(seen) -> None:
    rows, flats = seen["after"]["rows"], seen["after"]["flatsRow"]
    assert flats, "строки квартир на экране нет"
    assert rows[flats]["locked"], "строка МКД осталась правимой"
    assert rows[flats]["sum"] == 0
    assert "Нежилой проект" in flats, "строка не называет причину"
    # Поле жилой вводной заменено надписью, а не осталось редактируемым.
    assert seen["before"]["field"] is True
    assert seen["after"]["field"] is False


def test_the_removed_can_be_returned(seen) -> None:
    assert "Вернуть убранное" in seen["backNote"], "убранное не предложено вернуть"
    restored, before = seen["restored"], seen["before"]
    assert restored["flats"] == before["flats"]
    assert restored["dou"] == before["dou"]
    assert restored["fee"] == before["fee"]
    assert restored["field"] is True


def test_the_default_yard_rate_lives_in_the_mode_only() -> None:
    """Ставка двора нежилого проекта — свойство РЕЖИМА, а не умолчание.

    Поле `landscaping_gns_th_per_sqm` глобальное и сильнее методики класса:
    поставленное в `DEFAULT_INPUTS`, оно двинуло бы КАЖДЫЙ жилой проект — на
    умолчаниях благоустройство 400,1 → 1 453,8 млн ₽ и LLCR 0,9595 → 0,9313.
    Решение владельца 21.09.2026: «неважно какая цифра по умолчанию, главное
    считать на гнс… НО нельзя чтобы это сломало логику расчёта от населения
    для жилья».
    """
    assert core.NONRESIDENTIAL_LANDSCAPING_TH_PER_SQM > 0
    assert float(core.DEFAULT_INPUTS.get("landscaping_gns_th_per_sqm") or 0.0) == 0.0, (
        "ставка нежилого режима уехала в умолчания — она сильнее методики класса")
    # И на страницу она едет из движка, а не написана там числом.
    assert "__DEVELOPAID_NONRES_LANDSCAPING_RATE__" not in core.PAGE
    assert f"const NONRES_LANDSCAPING_RATE={core.NONRESIDENTIAL_LANDSCAPING_TH_PER_SQM:g}" in core.PAGE


def test_the_residential_methodology_does_not_move() -> None:
    """Жилой проект считает двор населением — ровно как считал.

    Предохранитель обязателен: если бы ставка стояла умолчанием, методика
    молчала бы, и проверка «методика жива» зеленела бы на пустом основании.
    """
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    summary = core.calculate(core.CalcRequest(inputs=x, tep=t))["summary"]
    assert summary["landscaping_by_rate"] is False, "жилой проект посчитан ставкой"
    assert summary["landscaping_area_sqm"] > 0
    assert "чел." in summary["landscaping_basis"]
    assert "м² двора" in summary["landscaping_money_basis"]


def test_the_money_says_what_it_was_counted_from() -> None:
    """У двора и у денег основания разные, и второе никто не читал.

    При ЗАДАННОЙ ставке основание площади печатало «задайте ставку на метр
    ГНС» — то есть советовало сделать то, что уже сделано: свод брал
    основание у площади, а деньги своё возвращали, и его не читал никто.
    """
    x, t = _objects_only()
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    x["landscaping_gns_th_per_sqm"] = core.NONRESIDENTIAL_LANDSCAPING_TH_PER_SQM
    summary = core.calculate(core.CalcRequest(inputs=copy.deepcopy(x),
                                              tep=copy.deepcopy(t)))["summary"]
    # Предохранитель: площадь двора тут ноль, значит её основание и есть тот
    # самый совет — иначе проверять нечего.
    assert summary["landscaping_area_sqm"] == 0
    assert "задайте ставку" in summary["landscaping_basis"]
    money = summary["landscaping_money_basis"]
    assert "м² ГНС" in money and "задайте ставку" not in money
    assert summary["landscaping_gap"] == "", "деньги есть, а статья названа пустой"


def test_the_switch_sets_the_yard_rate_and_names_it(seen) -> None:
    """Режим ставит ставку двора — и называет поставленное.

    Молчаливая подстановка врёт не меньше молчаливого обнуления: число в поле
    неотличимо от вписанного человеком.
    """
    before, after = seen["before"], seen["after"]
    # Предохранитель: до переключения ставки не было, иначе ставить нечего.
    assert before["yardRate"] == 0
    assert after["yardRate"] == core.NONRESIDENTIAL_LANDSCAPING_TH_PER_SQM
    assert "Поставлено" in after["note"], "ставка подставлена молча"
    assert "м² ГНС" in after["note"]


def test_the_returned_project_loses_the_mode_rate(seen) -> None:
    """«Вернуть убранное» снимает и поставленное: иначе жилой проект уходит
    считаться ставкой, которую человек не задавал."""
    assert seen["restored"]["yardRate"] == 0


# --- Режим — признак, а не разовое действие переключателя -------------------
#
# Экран владельца 21.09.2026: тип «Нежилое», квартиры и кладовые по нулям, а
# подземный паркинг 149 м/м и 5 215 м² — под подписью «строка обнулена и
# заперта». Обнулял его переключатель верно; возвращала выгрузка ГлавАПУ,
# которая о режиме не знала: без квартир наша норма отвечает нулём, а
# ВЫГРУЗКА отвечает своим числом, посчитанным по нормативному — то есть
# ЖИЛОМУ — ТЭП участка (135 постоянных + 14 гостевых).
#
# Цена на проверочном нежилом проекте: CAPEX +762,6 млн ₽, выручка +74,2
# (135 мест продаются), чистая прибыль −932,3 млн, LLCR 0,609 → 0,526.
#
# Там же вторая половина: кнопка «Рассчитать ТЭП от площади и плотности»
# раскладывала СПП по МКД — 94% квартиры, 6% встроенная коммерция, — и на
# участке 0,546 га при 35 000 м²/га клала 15 397 и 983 м² в ЗАПЕРТЫЕ строки.
# Убрать их человек не мог: ячейки только для чтения, полей на экране нет.


def _parking_stand(kind: str) -> dict:
    """Строка подземного паркинга при живой выгрузке ГлавАПУ."""
    import json

    import page_blocks

    prelude = """
const inputs={project_kind:'%s', _glavapu_import:{normalized:{
  parking_permanent:135, parking_guest:14, mfc_parking_spaces:0, office_gba_sqm:0}}};
let tep={
 apartments:{label:'Квартиры',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0},
 ground_commercial:{label:'Коммерция 1 этажа',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0},
 underground_parking:{label:'Подземный паркинг',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0},
 storage:{label:'Кладовые',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0}
};
const num=v=>String(Math.round(Number(v||0)));
""" % kind
    tail = """
repairParkingFromGlavapu();
const p=parkingRequirement();
console.log(JSON.stringify({units:tep.underground_parking.units,
 gns:tep.underground_parking.gns, required:p?p.spaces:0}));
"""
    out, _ = page_blocks.run(prelude, tail)
    return json.loads(out)


def test_the_glavapu_parking_does_not_survive_the_mode() -> None:
    """Паркинг МКД в нежилом проекте не ставит ни норма, ни выгрузка."""
    housing = _parking_stand("mixed")
    # Предохранитель: в ЖИЛОМ проекте та же выгрузка эту строку заполняет,
    # иначе проверка зелена на коде, который не ставит паркинг вовсе.
    assert housing["units"] == 149 and housing["required"] == 149
    assert housing["gns"] > 0

    nonres = _parking_stand("nonresidential")
    assert nonres["units"] == 0, "паркинг МКД вернулся выгрузкой ГлавАПУ"
    assert nonres["gns"] == 0
    assert nonres["required"] == 0, "потребность жилья считается без жилья"


def _density_stand(kind: str) -> dict:
    """Что делает кнопка «Рассчитать ТЭП от площади и плотности»."""
    import json

    import page_blocks

    prelude = """
const inputs={project_kind:'%s', site_area_ha:0.546, site_density_manual:35000,
  _glavapu_import:{normalized:{parking_permanent:135,parking_guest:14,
   mfc_parking_spaces:0, office_gba_sqm:0}}};
let tep={
 apartments:{label:'Квартиры',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0},
 ground_commercial:{label:'Коммерция 1 этажа',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0},
 underground_parking:{label:'Подземный паркинг',gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0}
};
// `num` НЕ заглушка: разрядку числа ставит она, и подменённая она заставила бы
// проверку держать форму стенда, а не то, что увидит человек.
let STATUS={style:{},innerHTML:''};
const document={getElementById:()=>STATUS};
function renderTep(){}
function calculate(){}
function applyNormativeTep(){return Promise.resolve({})}
function escapeHtml(s){return String(s)}
""" % kind
    tail = """
applyDensityToTep();
console.log(JSON.stringify({flats:Math.round(tep.apartments.gns),
 commercial:Math.round(tep.ground_commercial.gns),
 status:STATUS.innerHTML.replace(/<[^>]+>/g,' ').replace(/\\s+/g,' ').trim()}));
"""
    out, _ = page_blocks.run(prelude, tail)
    return json.loads(out)


def test_the_density_button_does_not_bring_housing_back() -> None:
    """В нежилом проекте кнопка отказывается — и говорит, где задать метры."""
    housing = _density_stand("mixed")
    # Предохранитель: в жилом проекте кнопка работает как работала.
    assert housing["flats"] > 0 and housing["commercial"] > 0

    nonres = _density_stand("nonresidential")
    assert nonres["flats"] == 0 and nonres["commercial"] == 0, \
        "кнопка положила жильё в запертые строки нежилого проекта"
    status = nonres["status"]
    assert "Нежилой проект" in status, "отказ не назвал причину"
    # Отказ, о котором не сказано, где тогда задавать метры, отвечает половину.
    assert "Экономика" in status and "офисы" in status
    # Потенциал участка назван числом: иначе отказ выглядит как «считать
    # нечем», хотя площадь и плотность у нас есть.
    assert "16 380" in status.replace(" ", " "), status


def test_the_class_note_names_what_the_class_moves() -> None:
    """Подпись класса называет то, что класс двигает ЗДЕСЬ.

    «Почему активен блок класса?» (владелец, 21.09.2026). Активен законно: на
    проверочном офиснике класс двигает выручку с 3 794,8 до 17 390,4 млн ₽ и
    LLCR с 0,543 до 1,609 — цена метра ОСЗ идёт за ценой жилья класса. Врала
    подпись: «Кв/комм · м/м» называет то, чего в нежилом проекте нет.
    """
    import json

    import page_blocks

    def note(kind: str) -> str:
        prelude = """
const inputs={project_kind:'%s', project_class:'business'};
let BOX={textContent:''};
const document={getElementById:id=>id==='projectClassSelect'?null:BOX};
""" % kind
        tail = """
renderProjectClassPreview();
console.log(JSON.stringify({note:BOX.textContent}));
"""
        out, _ = page_blocks.run(prelude, tail)
        return json.loads(out)["note"]

    housing = note("mixed")
    # Предохранитель: у жилого проекта подпись прежняя.
    assert "Кв/комм" in housing and "м/м" in housing

    nonres = note("nonresidential")
    assert "Кв/комм" not in nonres and "м/м " not in nonres, \
        "подпись называет квартиры и места МКД в нежилом проекте"
    assert "Офисы/ТЦ" in nonres, nonres
    assert "себес." in nonres, "подпись молчит о СМР, которую класс двигает"


# Писатели ТЭП о режиме не знали, и вернувшееся жильё убрать было нечем:
# строки заперты, полей на экране нет. Проверяется живым браузером — в
# исходнике страница со сломанным признаком выглядит так же, как с
# работающим, а `syncTep` тянет полстраницы и стендом на node не гоняется.
PROBE_RETURNED = """() => {
  applyProjectKind('nonresidential');
  // Так кладут метры импорт ГлавАПУ, мост КРТ и загрузка проекта — мимо
  // переключателя, который один и обнулял.
  tep.apartments.gns=15397; tep.apartments.saleable=10008; tep.apartments.total_area=13857;
  tep.ground_commercial.gns=983; tep.ground_commercial.saleable=885;
  tep.underground_parking.units=149; tep.underground_parking.gns=5215;
  inputs.land_rights_cost_mln=1186.7; inputs.kindergarten_places=104;
  syncTep(false); renderTep();
  return {flats: Number(tep.apartments.gns||0),
          commercial: Number(tep.ground_commercial.gns||0),
          parking: Number(tep.underground_parking.units||0),
          fee: Number(inputs.land_rights_cost_mln||0),
          dou: Number(inputs.kindergarten_places||0),
          cleared: (inputs._nonres_cleared||[]).join(' | ')};
}"""


@pytest.fixture(scope="module")
def returned():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT + 1) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            got = page.evaluate(PROBE_RETURNED)
            page.wait_for_timeout(400)
            page.close()
    got["errors"] = errors
    return got


def test_the_mode_takes_back_what_a_writer_returned(returned) -> None:
    assert returned["errors"] == [], "страница не доработала до конца"
    assert returned["flats"] == 0, "квартиры вернулись писателем и остались"
    assert returned["commercial"] == 0
    assert returned["parking"] == 0, "паркинг МКД вернулся и остался"
    assert returned["fee"] == 0, "плата за смену ВРИ вернулась и осталась"
    assert returned["dou"] == 0


def test_the_mode_names_what_it_took_back(returned) -> None:
    """Убранное называется поимённо — и то, что вернул писатель, тоже.

    Молчаливое обнуление врёт не меньше молчаливого сохранения, а поля на
    экране нет: не сказав, человек и не узнает, что его метры не считаются.
    """
    # Разряды на странице разделяет неразрывный пробел — держать его форму в
    # проверке значит держать оформление, а утверждение здесь о другом.
    cleared = returned["cleared"].replace("\u00a0", " ")
    assert "плата за смену ВРИ 1 186,7" in cleared, cleared
    assert "места ДОО 104" in cleared, cleared


# Куда положить потенциал участка — выбирает человек (решение владельца,
# 21.09.2026: «надо предлагать выбирать куда хочет вставить. В офисники или
# в тц»). Делить его самим нельзя: доля между офисами и торговлей была бы
# нашей догадкой, а на экране выглядела бы как норматив города.
PROBE_TARGET = """() => {
  applyProjectKind('nonresidential');
  inputs.site_area_ha=0.546; inputs.site_density_manual=35000;
  applyDensityToTep();
  const box=document.getElementById('siteApplyStatus');
  const ask=box.innerText.replace(/\\s+/g,' ');
  const buttons=[...box.querySelectorAll('button')].map(b => b.textContent.trim());
  const wasGba=Number(inputs.offices_gba_sqm||0);
  applyDensityToObject('offices');
  return {ask: ask, buttons: buttons, wasGba: wasGba,
          done: box.innerText.replace(/\\s+/g,' '),
          gba: Number(inputs.offices_gba_sqm||0),
          sale: Number(inputs.offices_saleable_sqm||0),
          rowGns: Number(tep.offices.gns||0),
          flats: Number(tep.apartments.gns||0),
          enabled: !!inputs.offices_enabled};
}"""


@pytest.fixture(scope="module")
def chosen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT + 2) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            got = page.evaluate(PROBE_TARGET)
            page.wait_for_timeout(400)
            page.close()
    got["errors"] = errors
    return got


def test_the_density_button_asks_where_to_put_it(chosen) -> None:
    """Отказ заменён вопросом: потенциал назван числом, цели — кнопками."""
    assert chosen["errors"] == [], "страница не доработала до конца"
    ask = chosen["ask"].replace(" ", " ")
    assert "16 380" in ask, ask
    # Цели берутся из объявленного списка, а не пишутся на экране руками.
    assert chosen["buttons"] == [name for _, name in _density_targets()], chosen["buttons"]


def test_the_chosen_object_gets_the_metres(chosen) -> None:
    """Выбранный объект получает метры, а жильё остаётся нулём."""
    assert chosen["enabled"] is True, "объект не включился"
    assert round(chosen["gba"]) == 16380, chosen["gba"]
    assert round(chosen["rowGns"]) == 16380, "строка ТЭП объекта не пошла за вводной"
    # Продаваемая — производная долей объекта, а не оставшееся прежнее число.
    assert 0 < chosen["sale"] < chosen["gba"]
    assert chosen["flats"] == 0, "жильё вернулось вместе с потенциалом"


def test_the_replaced_metres_are_named(chosen) -> None:
    """Заменённое называется числом: молча переписанная вводная неотличима
    от невнимательности."""
    # Предохранитель: в умолчаниях у объекта метры были, иначе заменять нечего.
    assert chosen["wasGba"] > 0
    done = chosen["done"].replace(" ", " ")
    assert "Заменено" in done, done
    assert str(round(chosen["wasGba"])) in done.replace(" ", ""), done


def _density_targets() -> list[tuple[str, str]]:
    """Список целей — со страницы, а не пересказом: пересказанный, он
    разошёлся бы с кнопками молча."""
    import json

    import page_blocks

    raw = page_blocks.constant("NONRES_DENSITY_TARGETS")
    body = raw[raw.index("["):raw.rindex("]") + 1].replace("'", '"')
    return [tuple(pair) for pair in json.loads(body)]
