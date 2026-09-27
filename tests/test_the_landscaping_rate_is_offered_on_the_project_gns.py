"""Показатель, который предлагают вписать, считается на базе того поля.

Владелец попросил (14.09.2026): «во вводных счётный показатель руб на ГНС,
посчитанный из данных настроек. С пометкой, что можно ввести вручную самому
руб на ГНС». Первая версия назвала поле «ставкой на метр дома», потому что
умножалось оно на наземную часть ДОМА — квартиры плюс коммерция первого
этажа, — а соседняя подпись делила те же деньги на наземную площадь ПРОЕКТА,
вместе с соцобъектами и ОСЗ. Два почти равных числа под одним словом «ГНС»:
145 381 против 140 381 м² на умолчаниях.

Имя оказалось хуже болезни («фраза „ставка на метр дома" ужасная. На м² ГНС
видимо пишут грамотные люди», владелец, 16.09.2026), и правильный ответ —
свести базы, а не подписать расхождение. База поля теперь НАЗЕМНАЯ ГНС
ПРОЕКТА: та же, которой меряют удельные, которой считает свод «Статистики» и
которой книга умножала ставку всё это время (в v4 это I+J при I+J+K —
строительном объёме). Отсюда три утверждения, и каждое проверяется числом:
обратный ход сходится, показатель поля и `landscaping_per_gns_th` — одно
число, а третьего «на метр» у статьи больше нет.

Запуск: python3 -m pytest tests/test_the_landscaping_rate_is_offered_on_the_project_gns.py -q
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
    """Вписал предложенное — получил те же деньги, до округления показателя."""
    base = _run(core.DEFAULT_INPUTS)
    offered = float(base["summary"]["landscaping_per_gns_th"])
    assert offered > 0, base["summary"]
    typed = dict(core.DEFAULT_INPUTS)
    typed["landscaping_gns_th_per_sqm"] = offered
    again = _run(typed)
    assert again["capex"]["landscaping"] == pytest.approx(
        base["capex"]["landscaping"], rel=1e-9), {
            "методика": base["capex"]["landscaping"],
            "вписано": again["capex"]["landscaping"]}


def test_the_rate_multiplies_the_project_gns() -> None:
    """База — наземная ГНС проекта, и это проверяется умножением."""
    typed = dict(core.DEFAULT_INPUTS)
    typed["landscaping_gns_th_per_sqm"] = 3.0
    got = _run(typed)
    gns = float(got["summary"]["project_gns_sqm"])
    assert gns > 0
    assert got["capex"]["landscaping"] == pytest.approx(3.0 * gns * 1000, rel=1e-9)
    # Предохранитель: прежняя база — метры дома — обязана ОТЛИЧАТЬСЯ, иначе
    # проверка проходила бы и на ней, ничего не утверждая.
    house = sum(float((core.TEP_DEFAULT.get(key) or {}).get("gns") or 0.0)
                for key in ("apartments", "ground_commercial"))
    assert abs(house - gns) > 1000, (house, gns)


def test_the_indicator_is_declared_once() -> None:
    """Третьего «на метр» у статьи нет: показатель поля и есть удельный ГНС."""
    got = _run(core.DEFAULT_INPUTS)
    summary = got["summary"]
    assert "landscaping_per_gns_th" in summary
    assert "landscaping_per_saleable_th" in summary
    # Пара обязательна — одинокое «на метр» читается как другой показатель.
    assert summary["landscaping_per_saleable_th"] > 0
    # А «на метр дома» снят вместе со своей базой.
    assert "landscaping_house_rate_th" not in summary
    assert "landscaping_house_gns_sqm" not in summary
    assert "landscaping_house" not in core.PAGE


def test_the_note_names_the_state_not_the_base() -> None:
    """Подпись говорит, чьё число стоит в поле; базу называет единица поля."""
    seen = page_blocks.run_json(
        "const inputs={landscaping_gns_th_per_sqm:0};"
        "let lastResult={summary:{landscaping_per_gns_th:2.75}};",
        "const byMethod=landscapingHouseRateNote();"
        "inputs.landscaping_gns_th_per_sqm=4;"
        "const byHand=landscapingHouseRateNote();"
        "lastResult={summary:{}};"
        "inputs.landscaping_gns_th_per_sqm=0;"
        "const notYet=landscapingHouseRateNote();"
        "console.log(JSON.stringify({byMethod,byHand,notYet}));")
    assert "методика класса" in seen["byMethod"], seen
    assert "Настройках класса" in seen["byMethod"], seen
    assert "руками" in seen["byHand"].lower(), seen
    assert "Расчёта ещё нет" in seen["notYet"], seen
    # Ни одно состояние не молчит: пустое место под полем читается как ответ.
    assert all(len(text) > 10 for text in seen.values()), seen
    # И база тут не повторяется — её называет единица поля строкой выше.
    assert all("ГНС" not in text for text in seen.values()), seen


def test_in_a_real_browser_the_note_stands_under_its_own_field() -> None:
    """Подпись приклеена к своему полю, а не к соседнему.

    Мерится РОДИТЕЛЕМ, а не координатами: форма двухколонная, и у подписей
    соседних колонок совпадают верхние края — проверка на «не в одном месте»
    падала бы на верной сетке.
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
            page.goto(base + "/", wait_until="networkidle")
            page.evaluate("() => calculate()")
            page.wait_for_function(
                "() => {const box=document.getElementById('landscapingHouseRateNote');"
                "return box && box.textContent.length > 0}", timeout=120_000)
            seen = page.evaluate("""() => {
              const note=document.getElementById('landscapingHouseRateNote');
              const box=note.closest('.field');
              const own=box?box.querySelectorAll('input,select').length:0;
              const field=box?(box.querySelector('input')||{}).id:'';
              const a=(document.getElementById('f_landscaping_gns_th_per_sqm')||{})
                .getBoundingClientRect?document.getElementById('f_landscaping_gns_th_per_sqm')
                .getBoundingClientRect():null;
              const b=note.getBoundingClientRect();
              return {field, own, under: a? b.top >= a.bottom - 1 : null,
                      text: note.textContent};
            }""")
            browser.close()

    assert not errors, errors
    assert seen["field"] == "f_landscaping_gns_th_per_sqm", seen
    assert seen["own"] == 1, ("в блоке поля больше одного ввода", seen)
    assert seen["under"] is True, ("подпись стоит НАД вводом", seen)
    assert seen["text"].strip(), seen
