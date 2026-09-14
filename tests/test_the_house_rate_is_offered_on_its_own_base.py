"""Показатель, который предлагают вписать, считается на базе того поля.

Владелец попросил (14.09.2026): «во вводных счётный показатель руб на ГНС,
посчитанный из данных настроек. С пометкой, что можно ввести вручную самому
руб на ГНС, или поменять в настройках вводные по площади и тп и этот
показатель пересчитается».

Ловушка здесь не в словах, а в БАЗЕ. Рядом уже стоит подпись «выходит X тыс
₽/м² ГНС», и делит она деньги благоустройства на наземную площадь ПРОЕКТА —
вместе с соцобъектами и ОСЗ. А поле «ставка на метр дома» умножается на
наземную часть ДОМА: квартиры плюс коммерция первого этажа. На умолчаниях это
145 381 против 140 381 м², и человек, прочитавший 2,75 и вписавший его в поле,
получил бы 386,4 млн ₽ вместо 400,1 — та же статья, тот же проект, другое
число. Поэтому показатель под полем считается на базе ЭТОГО поля, и обратный
ход обязан сойтись до копейки.

Запуск: python3 -m pytest tests/test_the_house_rate_is_offered_on_its_own_base.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

import main_legacy as core  # noqa: E402

PORT = 8137


def _run(inputs: dict) -> dict:
    return core.calculate(core.CalcRequest(inputs=dict(inputs),
                                           tep=copy.deepcopy(core.TEP_DEFAULT)))


def test_the_offered_rate_reproduces_the_money() -> None:
    """Вписал предложенное — получил ровно то же. Иначе это другое число."""
    by_method = _run(core.DEFAULT_INPUTS)
    summary = by_method["summary"]
    rate = summary["landscaping_house_rate_th"]
    assert rate > 0, summary
    hand = dict(core.DEFAULT_INPUTS)
    hand["landscaping_gns_th_per_sqm"] = rate
    by_hand = _run(hand)
    assert by_hand["capex"]["landscaping"] == pytest.approx(
        by_method["capex"]["landscaping"], rel=1e-9)


def test_the_two_bases_really_differ() -> None:
    """Предохранитель: совпади базы — первая проверка не значит ничего.

    Она сошлась бы и на показателе, посчитанном на чужой базе, и поймать
    подмену было бы нечем.
    """
    summary = _run(core.DEFAULT_INPUTS)["summary"]
    house = summary["landscaping_house_gns_sqm"]
    project = summary["project_gns_sqm"]
    assert house > 0 and project > house, (house, project)
    # И расхождение не микроскопическое: на умолчаниях это садик, 5 000 м².
    assert project - house > 1000, (house, project)


def test_the_house_ratio_travels_with_its_base() -> None:
    """Одинокое «на метр» читается как другой показатель — база едет рядом."""
    summary = _run(core.DEFAULT_INPUTS)["summary"]
    assert "landscaping_house_gns_sqm" in summary
    money = _run(core.DEFAULT_INPUTS)["capex"]["landscaping"]
    assert summary["landscaping_house_rate_th"] == pytest.approx(
        money / summary["landscaping_house_gns_sqm"] / 1000, rel=1e-9)


def test_the_note_names_all_three_states() -> None:
    """У подписи нет состояния, в котором она молчит.

    Пустое место под полем читается как ответ, а ответов здесь три: расчёта
    ещё нет, считает методика класса, ставка задана руками.
    """
    prelude = """
const cells={};
global.document={getElementById:id=>cells[id]||null};
const num=v=>String(v);
let inputs={};
let lastResult=null;
"""
    tail = """
const out={};
inputs={};lastResult=null;out.cold=landscapingHouseRateNote();
inputs={};lastResult={summary:{landscaping_house_rate_th:2.85,
                               landscaping_house_gns_sqm:140381}};
out.method=landscapingHouseRateNote();
inputs={landscaping_gns_th_per_sqm:4};
out.hand=landscapingHouseRateNote();
console.log(JSON.stringify(out));
"""
    said = page_blocks.run_json(prelude, tail)
    assert all(said.values()), said
    assert "Пересчитать модель" in said["cold"], said["cold"]
    # Утверждение — «сказано, откуда число и как его перебить», а не «стоит
    # такое-то слово»: проверка на оборот речи упала бы на правке текста.
    assert "методикой класса" in said["method"] and "2,85" in said["method"], said["method"]
    assert "140" in said["method"], "база не названа — «на метр» без неё другой показатель"
    assert "руками" in said["hand"] and "Настройках класса" not in said["hand"], said["hand"]
    assert said["hand"] != said["method"]


def test_in_a_real_browser_the_note_stands_under_its_own_field() -> None:
    """Подпись стоит ПОД своим полем, а не над ним и не под соседним.

    Замер уже ловил этот капкан дважды — на нормативе паркинга и на ставке
    двора: справка, встающая над вводом, приклеивается к подписи СОСЕДНЕЙ
    строки и читается как утверждение о ней. Это геометрия, и в исходнике
    сломанное выглядит как верное.
    """
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import main as wrapper

    with serve(wrapper.app, PORT) as base:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(base + "/", wait_until="networkidle")
            page.evaluate("() => calculate()")
            page.wait_for_function(
                "() => {const box=document.getElementById('landscapingHouseRateNote');"
                "return box && box.textContent.length > 0}", timeout=120_000)
            seen = page.evaluate("""() => {
              const note=document.getElementById('landscapingHouseRateNote');
              const field=document.getElementById('f_landscaping_gns_th_per_sqm');
              const other=document.getElementById('landscapingRateNote');
              if(!note||!field||!other)return null;
              const n=note.getBoundingClientRect(), f=field.getBoundingClientRect();
              return {text: note.textContent, below: n.top >= f.bottom - 1,
                      apart: Math.abs(n.top - other.getBoundingClientRect().top) > 4};
            }""")
            browser.close()

    assert not errors, errors
    assert seen, "поля ставки на метр дома или подписи под ним на странице нет"
    assert seen["below"], "подпись встала НАД вводом — читается как подпись соседней строки"
    assert seen["apart"], "обе подписи в одном месте — их не различить"
    assert "наземной части дома" in seen["text"], seen["text"]
