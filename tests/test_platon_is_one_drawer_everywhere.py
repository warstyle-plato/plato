"""Платон стоит одним ящиком справа — на всех поверхностях, а не карточкой внизу.

Владелец 04.09.2026: «может Платон будет так же расположен во всех блоках
кабинета, как на основном расчете? всплывающим справа для диалога?» На расчёте
он `<aside class="ai-drawer">` — выезжает справа и держит разговор; в кабинете и
в торгах это была карточка внутри страницы.

Разметку копировать было нельзя по той же причине, по которой нет копии
`VERSION`: копию негде обновлять, а разошедшиеся стили дали бы трёх разных
Платонов, и каждый выглядел бы правильным. Стили берутся из `PAGE`, оболочку
строит `plato_question`, а груз — чей разговор, что в вопросе, какие подсказки —
даёт блок, из которого нажали.

Ящик на странице ОДИН: блоков в кабинете два, и второй ящик рядом с первым
означал бы двух разных Платонов на одном экране.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plato_question  # noqa: E402


def _node() -> str:
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("node не установлен")
    return node


def _pages() -> dict[str, str]:
    import auction_search.ui as auction_ui
    import main_legacy
    import market_search.cabinet as cabinet

    return {
        "торги": auction_ui.auctions_page(main_legacy),
        "кабинет рынка": cabinet.cabinet_page("market"),
        "свод продаж": cabinet.cabinet_page("sales"),
    }


def test_every_surface_shows_the_same_drawer() -> None:
    for name, page in _pages().items():
        assert 'class="ai-drawer"' in page, f"{name}: ящика нет — Платон остался карточкой"
        assert page.count('class="ai-drawer"') == 1, (
            f"{name}: ящиков два — это два разных Платона на одном экране")
        assert ".ai-drawer{position:fixed" in page, f"{name}: стили ящика не подставлены"
        assert "ai-open-btn" in page, f"{name}: ящик закрыт, и открыть его нечем"


def test_the_look_comes_from_the_page_not_from_a_copy() -> None:
    """Стили — из `PAGE`. Своей копии нет: её негде обновлять."""
    import main_legacy

    css = plato_question.drawer_css(main_legacy)
    assert ".ai-drawer{" in css and ".ai-overlay{" in css
    assert css in main_legacy.PAGE, "стили разошлись с расчётом"

    class _NoPage:
        PAGE = "<html></html>"

    with pytest.raises(plato_question.MissingPiece):
        plato_question.drawer_css(_NoPage)


def test_the_drawer_answers_the_block_that_opened_it() -> None:
    """Груз даёт блок, а не ящик: иначе он ответит о прошлом вопросе."""
    script = plato_question.SCRIPT + """
const said=[];
const seen={hint:'', chips:[], html:''};
// Хватает того, что трогает пакет: настоящий DOM тут не нужен, нужна проверка,
// что он спрашивает у поверхности, а не помнит своё.
const nodes={
 platoHint:{set textContent(v){seen.hint=v}},
 platoChips:{innerHTML:'', appendChild(b){seen.chips.push(b.textContent)}},
 platoOut:{set innerHTML(v){seen.html=v}, insertAdjacentHTML(){}},
 platoField:{value:'', focus(){}},
 platoSend:{disabled:false}
};
global.document={
 getElementById:id=>nodes[id]||null,
 querySelector:()=>null,
 createElement:()=>({}),
 addEventListener(){}
};
const first={talk:platoThread(), hint:'первый блок', chips:[['фишка А','вопрос А']],
             message:q=>'А: '+q};
const second={talk:platoThread(), hint:'второй блок', chips:[['фишка Б','вопрос Б']],
              message:q=>'Б: '+q};
platoOpen(first);
said.push(['подпись первого блока', seen.hint==='первый блок']);
said.push(['подсказки первого блока', seen.chips.join()==='фишка А']);
seen.chips.length=0;
platoOpen(second);
said.push(['подпись сменилась', seen.hint==='второй блок']);
said.push(['подсказки сменились', seen.chips.join()==='фишка Б']);
said.push(['разговоры раздельные', first.talk!==second.talk]);
console.log(JSON.stringify(said));
"""
    tools = ROOT / "tests" / "_drawer.js"
    tools.write_text(script, encoding="utf-8")
    try:
        run = subprocess.run([_node(), str(tools)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tools.unlink(missing_ok=True)
    assert run.returncode == 0, run.stderr
    for label, ok in json.loads(run.stdout.strip().splitlines()[-1]):
        assert ok, label


def test_an_empty_question_is_refused_before_the_model() -> None:
    """Пустой вопрос — это ответ, а не поход к модели за ничем."""
    script = plato_question.SCRIPT + """
const calls=[];
global.fetch=()=>{calls.push(1); return Promise.reject(new Error('ходить не надо'))};
const seen={html:''};
const nodes={
 platoHint:{set textContent(v){}}, platoChips:{innerHTML:'', appendChild(){}},
 platoOut:{set innerHTML(v){seen.html=v}, insertAdjacentHTML(){}},
 platoField:{value:'   ', focus(){}}, platoSend:{disabled:false}
};
global.document={getElementById:id=>nodes[id]||null, querySelector:()=>null,
 createElement:()=>({}), addEventListener(){}};
platoOpen({talk:platoThread(), hint:'', chips:[], message:q=>'что-то'});
platoSend().then(()=>{
 console.log(JSON.stringify([['к модели не ходили', calls.length===0],
   ['сказано словами', /Напишите вопрос/.test(seen.html)]]));
});
"""
    tools = ROOT / "tests" / "_drawer_empty.js"
    tools.write_text(script, encoding="utf-8")
    try:
        run = subprocess.run([_node(), str(tools)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tools.unlink(missing_ok=True)
    assert run.returncode == 0, run.stderr
    for label, ok in json.loads(run.stdout.strip().splitlines()[-1]):
        assert ok, label


def test_a_block_that_has_nothing_yet_says_so() -> None:
    """«Сначала соберите отчёт» — это ответ блока, а не поломка ящика."""
    script = plato_question.SCRIPT + """
const calls=[];
global.fetch=()=>{calls.push(1); return Promise.reject(new Error('ходить не надо'))};
const seen={html:''};
const nodes={
 platoHint:{set textContent(v){}}, platoChips:{innerHTML:'', appendChild(){}},
 platoOut:{set innerHTML(v){seen.html=v}, insertAdjacentHTML(){}},
 platoField:{value:'почему так дорого', focus(){}}, platoSend:{disabled:false}
};
global.document={getElementById:id=>nodes[id]||null, querySelector:()=>null,
 createElement:()=>({}), addEventListener(){}};
platoOpen({talk:platoThread(), hint:'', chips:[],
 message:()=>{throw new Error('Сначала соберите отчёт — Платону нужны числа.')}});
platoSend().then(()=>{
 console.log(JSON.stringify([['к модели не ходили', calls.length===0],
   ['причина названа', /Сначала соберите отчёт/.test(seen.html)]]));
});
"""
    tools = ROOT / "tests" / "_drawer_nodata.js"
    tools.write_text(script, encoding="utf-8")
    try:
        run = subprocess.run([_node(), str(tools)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tools.unlink(missing_ok=True)
    assert run.returncode == 0, run.stderr
    for label, ok in json.loads(run.stdout.strip().splitlines()[-1]):
        assert ok, label


def test_the_pack_survives_a_page_without_a_dom() -> None:
    """Пакет грузится и там, где DOM ещё нет: упавший на первой строке пакет
    не определил бы ни одной функции — та самая поломка, которую ловили
    незакрытой кавычкой в `PAGE`."""
    assert "typeof document" in plato_question.SCRIPT
    script = plato_question.SCRIPT + "\nconsole.log('загрузился');"
    tools = ROOT / "tests" / "_drawer_nodom.js"
    tools.write_text(script, encoding="utf-8")
    try:
        run = subprocess.run([_node(), str(tools)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tools.unlink(missing_ok=True)
    assert run.returncode == 0, run.stderr
    assert "загрузился" in run.stdout


def test_the_polling_path_is_declared_once() -> None:
    """Опрос был написан трижды, и копии разошлись: в торгах не было стадии."""
    pack = plato_question.SCRIPT
    assert pack.count("/agent/result/") == 1
    for name, page in _pages().items():
        assert page.count("/agent/result/") == 1, (
            f"{name}: своя копия опроса вернулась — она разойдётся с общей")

def test_every_block_that_asks_has_its_own_load() -> None:
    """Блоков, спрашивающих Платона, четыре, и груз у каждого свой.

    Ящик один на страницу, поэтому груз обязан приходить от блока: открытый
    из продаж с грузом рынка, он ответил бы о другом отчёте — и выглядело бы
    это как ошибка Платона, а не как наша.
    """
    import auction_search.ui as auction_ui
    import market_search.bnmap_ui as bnmap_ui
    import market_search.cabinet as cabinet

    blocks = {
        "рынок": ("MARKET_SURFACE", cabinet.CABINET_PAGE),
        "продажи": ("SALES_SURFACE", cabinet.CABINET_PAGE),
        "второй источник": ("BNMAP_SURFACE", bnmap_ui.markup()),
        "торги": ("AUCTION_SURFACE", auction_ui.AUCTIONS_PAGE),
    }
    for name, (surface, source) in blocks.items():
        assert f"{surface}=" in source or f"{surface}={{" in source, (
            f"{name}: своего груза нет")
        assert f"platoOpen({surface})" in source, (
            f"{name}: кнопка открывает ящик без своего груза")
        # Каждый груз обязан уметь отказать: «сначала соберите отчёт» — это
        # ответ блока, а не поломка ящика.
        assert "message:" in source

    # Копий пути к Платону не осталось ни на одной поверхности.
    for name, page in _pages().items():
        assert "askPlatoIn(" not in page, f"{name}: кабинетная копия опроса вернулась"
