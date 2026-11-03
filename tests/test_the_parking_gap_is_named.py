"""Разрыв с нормативом приобъектной парковки назван числом и в обе стороны.

Владелец вписал 500 мест на первые этажи офисника и спросил: «Почему подземная
не изменилась? Может там хотя бы красным писать уведомление, что общая сумма
потребности на 500 меньше и можно снизить? Или наоборот если руками правишь, то
может возникнуть дефицит от расчетных значений» (13.09.2026).

Подземная не изменилась по построению, и это верно: оба поля принадлежат
человеку, и движок не решает за него, откуда взять 500. Неверно было другое —
**у величины есть мера, а сравнения с ней рядом не стояло**. На его числах
норматив 1 493, поля 1 493 и 500, строится 1 993 — и об этом ни слова.
Обратная сторона молчала так же: 400 мест при норме 1 590 печатались двумя
числами подряд, а дефицит в 1 093 места числом не назывался.

Красным — только дефицит: перебор это решение человека, а не ошибка, и красное
на обоих случаях сразу перестало бы их различать.

И третье, из того же снимка: подпись стояла ВЫШЕ ввода второго поля и потому
читалась как утверждение о нём — «по нормативу приложения 6 — 1 493 мест» под
строкой «мест на первых этажах». Норматив при этом на ОБЪЕКТ, то есть на оба
поля вместе.

Проверяется отрисовка, а не наличие строки в файле: искомый текст присутствует
и в сломанной странице.

Запуск: python3 -m pytest tests/test_the_parking_gap_is_named.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402
from test_the_parking_note_reaches_the_screen import _const, _piece  # noqa: E402

PAGE = core.PAGE

# Числа владельца: офисник, норматив приложения 6 — 1 493 места.
NORM = 1493


def _result(required: int, under: int, over: int, by_norm: bool = False):
    return {"parking": {"own": [
        {"prefix": "offices", "tep_key": "offices", "enabled": True,
         "by_norm": by_norm, "required_spaces": required,
         "units": under + over, "under_spaces": under, "over_spaces": over},
    ]}}


def _render(result, inputs=None):
    """Позвать настоящего писателя подписей со страницы.

    Ячейка несёт `style`: тон подписи — то, что видно, и стенд без него падал
    бы на нашей же правке, а падение выходило бы про стенд.
    """
    prelude = """
const cells = {parkNorm_offices:{textContent:"",style:{}},
               parkNorm_retail:{textContent:"",style:{}},
               parkNorm_sports:{textContent:"",style:{}}};
global.document = {getElementById: id => cells[id] || null};
const num = v => String(v);
%(prefixes)s
let inputs = %(inputs)s;
let lastResult = %(result)s;
// Очерёдности здесь нет: одиночный расчёт оставляет связку пустой, и
// `projectParking` берёт паркинг из результата.
let phaseBundle = null;
""" % {"result": json.dumps(result, ensure_ascii=False),
       "inputs": json.dumps(inputs or {"offices_enabled": True}, ensure_ascii=False),
       "prefixes": page_blocks.object_roster()}
    # Куски добирает общий разрешитель: перечисленные руками, они отставали от
    # страницы — `projectParking` завели рядом, и стенд упал на своей неполноте.
    tail = """
renderObjectParkingFieldNotes();
console.log(JSON.stringify({text: cells.parkNorm_offices.textContent,
                            color: cells.parkNorm_offices.style.color}));
"""
    return page_blocks.run_json(prelude, tail)


def test_an_overshoot_is_named_with_its_number() -> None:
    """Случай владельца: 1 493 подземных плюс 500 наземных при норме 1 493."""
    shown = _render(_result(NORM, under=NORM, over=500))

    assert "1993" in shown["text"], shown["text"]
    assert "500" in shown["text"], shown["text"]
    assert "больше" in shown["text"], shown["text"]
    # Перебор — не ошибка: он назван и не выделен.
    assert shown["color"] != "#a33", shown


def test_the_overshoot_says_what_can_be_reduced() -> None:
    """«На столько же можно снизить подземные» — это и был его вопрос."""
    shown = _render(_result(NORM, under=NORM, over=500))

    assert "снизить" in shown["text"], shown["text"]
    assert "подземн" in shown["text"], shown["text"]


def test_a_shortfall_is_named_and_shown_in_red() -> None:
    """Обратная сторона: задал меньше норматива — назван дефицит числом."""
    shown = _render(_result(1590, under=200, over=200))

    assert "дефицит" in shown["text"].lower(), shown["text"]
    assert "1190" in shown["text"], shown["text"]
    assert shown["color"] == "#a33", shown


def test_the_norm_is_named_as_the_objects_one_not_the_fields() -> None:
    """Норматив — на объект, на оба поля вместе, а не на «первые этажи»."""
    shown = _render(_result(NORM, under=NORM, over=500))

    assert "на объект" in shown["text"], shown["text"]
    assert "оба поля" in shown["text"], shown["text"]


def test_an_exact_match_says_so() -> None:
    """Сошлось — это тоже ответ, и молчать о нём нельзя."""
    shown = _render(_result(NORM, under=993, over=500))

    assert "ровно норматив" in shown["text"], shown["text"]
    assert shown["color"] != "#a33", shown


def test_the_gap_is_counted_once_for_text_and_tone() -> None:
    """Тон берётся у того же счёта, что и текст.

    Два ответа на одну разницу однажды разошлись бы, и подпись говорила бы
    «дефицит» спокойным серым.
    """
    render = _piece("renderObjectParkingFieldNotes")

    assert "objectParkingGap(" in render, render
    # Своего вычитания у писателя тона нет.
    assert "required_spaces" not in render, render


def test_the_note_stands_below_its_input() -> None:
    """Подпись ставится ПОСЛЕ поля, а не над ним.

    Стоя над вводом, она приклеивалась к подписи поля «мест на первых этажах»
    и читалась как норматив ЭТОГО поля.
    """
    mark = "wrap.appendChild(el);"
    cell = "normCell.id='parkNorm_'"

    assert PAGE.index(mark) < PAGE.index(cell), "подпись снова выше ввода"


def test_in_a_real_browser_the_note_sits_below_the_input() -> None:
    """Подпись стоит НИЖЕ ввода — это геометрия, и меряет её браузер.

    Прошлый раз ровно эту поломку строковый тест и пропустил: правило «подпись
    переехала под оба поля» было закрыто проверкой на текст, а div всё это
    время висел ВЫШЕ ввода второго поля — и на телефоне владельца норматив
    объекта читался как норматив «первых этажей» (13.09.2026).
    """
    import browser as browser_helper

    chrome = browser_helper.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main as _wrapper

    with browser_helper.serve(_wrapper.app, 18751) as base:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base + "/", wait_until="networkidle")
            # Объект включён — иначе поля паркинга не рисуются вовсе.
            page.evaluate("inputs.offices_enabled=true; renderInputs()")
            box = page.evaluate(
                """() => {
                  const input = document.getElementById('f_offices_parking_over_spaces');
                  const note = document.getElementById('parkNorm_offices');
                  if(!input||!note) return null;
                  const a = input.getBoundingClientRect(), b = note.getBoundingClientRect();
                  return {input_bottom: a.bottom, note_top: b.top, note_height: b.height};
                }""")
            browser.close()

    assert not errors, errors
    assert box, "поля паркинга объекта не нарисованы"
    assert box["note_top"] >= box["input_bottom"] - 1, (
        f"подпись выше ввода: верх {box['note_top']}, низ поля {box['input_bottom']}")
