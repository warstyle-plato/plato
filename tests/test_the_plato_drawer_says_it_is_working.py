"""Пока Платон думает, об этом сказано там, куда человек смотрит.

Владелец 07.09.2026, снимок кабинета: он написал второй вопрос «предложи
матрицу цен», нажал «Спросить» — и «диалог то не работает получается, второй
вопрос не задать».

Замер показал, что вопрос БЫЛ принят и ушёл: у Платона он идёт минутами
(опрос по номеру запуска до пяти минут — цепочка ядро → Render → OpenAI одним
соединением не держится). А на экране в этот момент стояло вот что: кнопка
погашена, подпись у неё прежняя «Спросить», в поле его собственный текст, и
рядом ни слова о работе. Признак работы («Платон Сергеевич думает…») ящик
пишет НАВЕРХ ленты — то есть туда, куда человек в эту секунду не смотрит: он
смотрит на поле, в которое только что написал. Погасшая кнопка без объяснения
и читается как «нажатие не сработало».

Правило «ожидание без признака работы читается как внезапность» было записано
ещё на плашке ограничений — ящик его не исполнял. Теперь состояние называет
сама кнопка, и возвращается прежняя подпись, когда ответ пришёл: подпись,
застрявшая на «думает…», врала бы в другую сторону.

Рядом закрыт молчаливый отказ того же рода: `platoSend` при невыбранном блоке
возвращался БЕЗ единого слова — нажали, и ничего. Причина у нас есть, она
просто не говорилась.

Проверяется браузером: подпись кнопки и её состояние — это то, что видно, и в
исходнике сломанный и починенный ящик выглядят одинаково.

Запуск: python3 -m pytest tests/test_the_plato_drawer_says_it_is_working.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from browser import chromium_or_skip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plato_question  # noqa: E402

HARNESS = """<!doctype html><meta charset="utf-8">
<style>__CSS__ body{margin:0} .tall{height:1400px}</style>
<div id="block" class="tall">отчёт о рынке</div>
__FAB__
__DRAWER__
<script>
__PACK__
const surface={talk:platoThread(), hint:'о рынке', chips:[], message:q=>'рынок: '+q};
platoBlock('#block', surface, 'об отчёте о рынке');
// Первый ответ приходит сразу, второй висит: так и бывает у Платона.
window.__asks=0; window.__release=null;
window.fetch=async (url, opts)=>{
  if(String(url).indexOf('/cabinet/ask')>=0){
    window.__asks+=1;
    if(window.__asks===1)
      return {ok:true,status:200,text:async()=>JSON.stringify({reply:'ПЕРВЫЙ'})};
    await new Promise(go=>{ window.__release=go });
    return {ok:true,status:200,text:async()=>JSON.stringify({reply:'ВТОРОЙ'})};
  }
  return {ok:false,status:404,text:async()=>'{}',json:async()=>({})};
};
function askState(){
  const b=document.getElementById('platoSend'), f=document.getElementById('platoField');
  const out=document.getElementById('platoOut');
  return {disabled:b.disabled, label:b.textContent.trim(), field:f.value,
          asks:window.__asks, said:out.innerText};
}
function ask(text){
  document.getElementById('platoField').value=text;
  document.getElementById('platoSend').click();
}
</script>"""


def _harness() -> str:
    import main_legacy

    return (HARNESS
            .replace("__CSS__", plato_question.drawer_css(main_legacy)
                     + "\n" + plato_question.launcher_css())
            .replace("__FAB__", plato_question.floating_launcher())
            .replace("__DRAWER__", plato_question.drawer_markup(plato_question.DRAWER_IDS))
            .replace("__PACK__", plato_question.script()))


@pytest.fixture()
def drawer(tmp_path):
    # Где браузер — один ответ на весь набор (`tests/browser.py`): он ищет, а
    # не помнит номер сборки, и на машине, где браузер ОБЯЗАН быть, его
    # отсутствие красит проверку красным, а не пропускает её молча.
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    page_file = tmp_path / "drawer.html"
    page_file.write_text(_harness(), encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 420, "height": 760})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(page_file.as_uri())
        page.evaluate("() => document.getElementById('platoFab').click()")
        page.wait_for_timeout(200)
        yield page, errors
        browser.close()


def test_the_button_says_the_answer_is_on_its_way(drawer) -> None:
    """Погасшая кнопка без слов читается как несработавшее нажатие."""
    page, errors = drawer
    idle = page.evaluate("() => { const b=document.getElementById('platoSend');"
                         " return b.textContent.trim() }")
    page.evaluate("() => ask('первый')")
    page.wait_for_timeout(400)
    page.evaluate("() => ask('предложи матрицу цен')")
    page.wait_for_timeout(400)

    seen = page.evaluate("() => askState()")
    assert seen["asks"] == 2, f"второй вопрос не ушёл вовсе: {seen}"
    assert seen["disabled"] is True, "пока ответ идёт, второй вопрос принимать нельзя"
    assert seen["label"] != idle, (
        f"кнопка молчит о работе: подпись осталась «{seen['label']}» — "
        "именно это и читается как «второй вопрос не задать»")
    assert "дума" in seen["label"].lower(), seen["label"]
    assert seen["field"] == "предложи матрицу цен", (
        "текст вопроса пропал из поля, хотя ответа ещё нет: " + repr(seen["field"]))
    assert not errors, errors


def test_the_button_comes_back_when_the_answer_arrives(drawer) -> None:
    """Подпись, застрявшая на «думает…», врала бы в другую сторону."""
    page, errors = drawer
    idle = page.evaluate("() => document.getElementById('platoSend').textContent.trim()")
    page.evaluate("() => ask('первый')")
    page.wait_for_timeout(400)
    page.evaluate("() => ask('второй')")
    page.wait_for_timeout(300)
    page.evaluate("() => window.__release && window.__release()")
    page.wait_for_timeout(500)

    seen = page.evaluate("() => askState()")
    assert seen["label"] == idle, f"подпись не вернулась: {seen['label']}"
    assert seen["disabled"] is False, "кнопка осталась погашенной после ответа"
    assert seen["field"] == "", "отвеченный вопрос остался в поле"
    assert "ВТОРОЙ" in seen["said"] and "ПЕРВЫЙ" in seen["said"], seen["said"]
    assert not errors, errors


def test_a_press_without_a_block_says_why(drawer) -> None:
    """Нажали, а спрашивать не о чем — это ответ, а не молчание."""
    page, errors = drawer
    page.evaluate("() => { PLATO_SURFACE=null; ask('вопрос в пустоту') }")
    page.wait_for_timeout(200)
    seen = page.evaluate("() => askState()")
    assert seen["asks"] == 0, "вопрос ушёл, хотя блок не выбран"
    assert seen["said"].strip(), "нажатие не сказало ничего — это выглядит как поломка"
    assert "блок" in seen["said"].lower(), seen["said"]
    assert not errors, errors
