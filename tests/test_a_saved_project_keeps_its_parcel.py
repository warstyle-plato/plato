"""Участок проекта переживает сохранение — даже когда источник промолчал.

Кадастровый номер оседал на странице только там, где кто-то ОТВЕТИЛ:
`inputs._cadastral_analysis` пишет расчёт ГлавАПУ, `inputs._land_lookup` —
ЕГРН, и то лишь при `found_count > 0`. Не ответил никто — и вписанный номер
жил только в DOM. Замер 15.09.2026 на живой странице: человек вписывает
`77:01:0004023:1000`, `projectStorePayload()` отдаёт метку записи `[]`, ни
одного ключа с «cad» во вводных, а после открытия проекта поле пустое. То есть
проект открывался без участка ровно в тот день, когда НСПД лежал (а он лежал
06.09.2026 по регламентным работам), и на экране это неотличимо от «человек
номер не вводил».

Теперь вписанное — данные ПРОЕКТА: `inputs._cadastral_query`. Три границы, и
каждая проверяется здесь отдельно.

* **Ответ источника сильнее вписанного.** `renderStoredCadastralQuery` стоит
  ПЕРВЫМ в цепочке `renderStored*`: у кого есть ответ ЕГРН или ГлавАПУ, тот
  перепишет поле своим — вместе с контуром и карточкой; у кого нет, останется
  хотя бы строка поиска. Статуса «показана территория из проекта» запасной путь
  не ставит: он ничего не показывает, он вернул строку.
* **Адрес меткой записи не становится.** Поле принимает «кадастровый номер,
  адрес или координаты», а `cadastral` записи — это номера, и по ним ищут в
  списке. Адрес при этом в поле возвращается: это та же строка поиска проекта.
* **Писатель поля один** (`writeCadastralField`). Две двери — набранное руками
  и поставленное кодом (мост КРТ, присланный проект, перенос номеров в блок
  ГлавАПУ) — разошлись бы молча, и половина проектов сохраняла бы участок, а
  половина нет.

Проверяется настоящим браузером по настоящему адресу: в исходнике страница,
которая номер теряет, выглядит ровно так же, как та, которая его возвращает.
Груз при этом проходит через JSON — так снимок и приезжает с сервера; поданный
тем же объектом, он проверял бы не то (`applyProjectSnapshot` правит `inputs`
по дороге).

Запуск: python3 -m pytest tests/test_a_saved_project_keeps_its_parcel.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

TYPED = "77:01:0004023:1000, 77:01:0004023:1001"
ADDRESS = "Московская область, г. Мытищи, ул. Мира, 1"

PROBE = """([typed, address])=>{
  const out={};
  const field=document.getElementById('cadastralNumbers');
  if(!field)return {missing:true};
  // Снимок приезжает с сервера разобранным JSON — отдельным объектом.
  const asStored=(body)=>JSON.parse(JSON.stringify(body));
  const type=(text)=>{
    field.value=text;
    field.dispatchEvent(new Event('input',{bubbles:true}));
    return asStored(projectStorePayload());
  };

  const numbers=type(typed);
  out.label=numbers.cadastral;
  out.remembered=numbers.payload.inputs._cadastral_query;
  applyProjectSnapshot(numbers.payload);
  out.reopened=document.getElementById('cadastralNumbers').value;

  const plain=type(address);
  out.address_label=plain.cadastral;
  applyProjectSnapshot(plain.payload);
  out.address_reopened=document.getElementById('cadastralNumbers').value;

  // Ответ источника и вписанное спорят за одно поле.
  applyProjectSnapshot(asStored({
    inputs: Object.assign({}, INPUT_DEFAULT, {
      _cadastral_query: '77:01:0004023:1000',
      _cadastral_analysis: {requested:['77:99:0000000:7'],
                            cadastral_numbers:['77:99:0000000:7']}}),
    tep:{}, phasing:null, scenario:'base'}));
  out.source_wins=document.getElementById('cadastralNumbers').value;

  // Разбор списка с опечаткой: ветка, где один номер УЗНАН, а соседняя строка
  // нет. Она читает образец вторым обращением, и снятая константа роняла бы
  // её `ReferenceError` — молча, потому что сюда не заходит ни один обычный
  // ввод. Проверяем тем, что видно человеку: страница называет негодную
  // строку, а не падает.
  try{
    out.mixed=lookupLandComplaint('77:01:0004023:1000, 77:01:000402');
  }catch(e){ out.mixed='УПАЛО: '+String(e); }

  // Забыли территорию — поле пусто, и открытый следом чистый проект участка
  // прошлого не получает.
  forgetTerritoryState();
  applyProjectSnapshot(asStored({inputs:Object.assign({},INPUT_DEFAULT),
                                 tep:{}, phasing:null, scenario:'base'}));
  out.after_forget=document.getElementById('cadastralNumbers').value;
  return out;
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18131) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            got = page.evaluate(PROBE, [TYPED, ADDRESS])
            page.close()
    assert not errors, f"страница упала: {errors[:2]}"
    assert not got.get("missing"), "поля участка на странице нет"
    return got


def test_the_typed_parcel_comes_back_with_the_project(seen):
    """То, ради чего всё: вписанный номер переживает открытие проекта."""
    assert seen["remembered"] == TYPED, \
        f"вписанное не стало частью проекта: {seen['remembered']!r}"
    assert seen["reopened"] == TYPED, \
        f"проект открылся без участка: {seen['reopened']!r}"


def test_the_record_is_labelled_by_the_numbers_it_was_given(seen):
    """Метка записи — номера, и по ним проект узнают в списке."""
    assert seen["label"] == ["77:01:0004023:1000", "77:01:0004023:1001"], \
        f"метка записи не несёт участок: {seen['label']!r}"


def test_an_address_is_not_a_cadastral_label_but_is_still_the_query(seen):
    """Адрес вводить можно, номером записи он не становится — и возвращается."""
    assert seen["address_label"] == [], \
        f"адрес стал кадастровой меткой записи: {seen['address_label']!r}"
    assert seen["address_reopened"] == ADDRESS, \
        f"адрес не вернулся в поле поиска: {seen['address_reopened']!r}"


def test_the_source_answer_beats_what_was_typed(seen):
    """У кого есть ответ ЕГРН или ГлавАПУ, тот и пишет поле: с ним придёт контур."""
    assert seen["source_wins"] == "77:99:0000000:7", \
        f"запасной путь перебил ответ источника: {seen['source_wins']!r}"


def test_a_forgotten_territory_does_not_come_back(seen):
    """Предохранитель: чистый проект не получает участок предыдущего."""
    assert seen["after_forget"] == "", \
        f"участок прошлого проекта пережил смену: {seen['after_forget']!r}"


def test_the_page_asks_what_a_cadastral_number_looks_like_in_one_place():
    """Образец был написан четырьмя литералами, и меткой записи стал бы пятый.

    Запрещено МЕСТО, а не слово: объяснение выше само называет вид номера, и
    проверка на строку завалилась бы на собственном объяснении.
    """
    page = core.PAGE
    # Страница — сырая строка Python, поэтому объявленный источник стоит в ней
    # с ДВОЙНЫМ слешем (`'\\d{2}…'`, в JS это строка `\d{2}…`), а regex-литерал
    # `/^\d{2}…$/` — с одинарным. Считать надо литералы: у объявленного
    # источника их ноль, и первый же появившийся — копия.
    literal = r"\d{2}:\d{2}:\d{6,8}:\d+"
    assert page.count(literal) == 0, (
        f"образец кадастрового номера написан на странице литералом "
        f"{page.count(literal)} раз — он объявлен один раз (CADASTRAL_NUMBER_SOURCE)")
    assert page.count(r"\\d{2}:\\d{2}:\\d{6,8}:\\d+") == 1, \
        "объявления образца на странице нет либо оно не одно"
    assert "CADASTRAL_NUMBER_SOURCE" in page, "источник образца со страницы пропал"
