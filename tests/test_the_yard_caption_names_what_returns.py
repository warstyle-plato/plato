"""Подпись обещает число, которое ВЕРНЁТСЯ, а не то, что уже стоит в поле.

Владелец прислал экран прода (20.09.2026): в поле «Благоустройство — ставка»
стоит 30, а под ним «Задано руками. Очистите поле — вернётся методика класса
(30)». Тридцать — это ровно то, что он вписал: показатель считался из ДЕНЕГ, а
деньги при заданной ставке считаются ИЗ НЕЁ, то есть подпись повторяла ввод и
обещала не тот исход. На умолчаниях методика даёт 0,31 тыс ₽/м² ГНС против
вписанных 30 — предложенное действие меняет статью почти в сто раз, а подпись
говорила, что не изменит ничего.

Рядом вторая половина того же: при заданной ставке двор в деньги не идёт
ВОВСЕ (`landscaping_cost` при `rate > 0` площадь не читает), а подпись площади
называла двор и молчала об этом — то есть ставила его рядом с суммой как её
причину.

Утверждений три, и каждое проверяется числом или тем, что видно на экране:
показатель методики не зависит от поля; подпись ставки печатает именно его;
подпись площади говорит, что двор в деньги не идёт.

Запуск: python3 -m pytest tests/test_the_yard_caption_names_what_returns.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser import chromium_or_skip, serve  # noqa: E402

import main_legacy as core  # noqa: E402

PORT = 18959
HAND_RATE = 30.0


def _summary(own: float) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs["landscaping_gns_th_per_sqm"] = own
    result = core.calculate(core.CalcRequest(inputs=inputs,
                                             tep=copy.deepcopy(core.TEP_DEFAULT)))
    return result["summary"]


def test_the_class_indicator_does_not_follow_the_field() -> None:
    """Показатель методики один и тот же — с рукой в поле и без неё."""
    empty, hand = _summary(0.0), _summary(HAND_RATE)
    by_class = float(empty["landscaping_by_class_th"])
    assert by_class > 0, "методика ничего не посчитала — мерить нечем"
    assert float(hand["landscaping_by_class_th"]) == pytest.approx(by_class)
    # Предохранитель: если рука не двигает применённый показатель, то
    # проверка выше зелена при любом коде — сравнивать было бы нечего.
    assert float(hand["landscaping_per_gns_th"]) == pytest.approx(HAND_RATE)
    assert float(empty["landscaping_per_gns_th"]) == pytest.approx(by_class)
    assert by_class < HAND_RATE / 10, (
        "методика и рука почти сошлись — пример не различает подмену")


def test_the_driver_is_named() -> None:
    """Чем посчитаны деньги, говорит свод, а не догадка экрана."""
    assert _summary(0.0)["landscaping_by_rate"] is False
    assert _summary(HAND_RATE)["landscaping_by_rate"] is True


@pytest.fixture(scope="module")
def captions() -> dict:
    """Обе подписи, снятые с живой страницы при обоих состояниях поля.

    Подписи читают `lastResult`, то есть существуют только после расчёта:
    стендом на node их не позвать, а в исходнике сломанная и починенная
    выглядят одинаково.
    """
    from playwright.sync_api import sync_playwright

    import main as app_mod

    path = chromium_or_skip()
    out: dict = {}
    with serve(app_mod.app, PORT):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=path)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="load")
            page.wait_for_function("()=>typeof lastResult!=='undefined'",
                                   timeout=60000)
            for own in (0.0, HAND_RATE):
                page.evaluate("o=>{inputs.landscaping_gns_th_per_sqm=o}", own)
                page.evaluate("()=>calculate()")
                page.wait_for_function("()=>lastResult&&lastResult.summary",
                                       timeout=60000)
                page.evaluate("()=>{openTab('inputs');renderInputs();}")
                out[own] = {
                    "area": page.evaluate(
                        "()=>{const e=document.getElementById('landscapingRateNote');"
                        "return e?e.textContent:''}"),
                    "rate": page.evaluate(
                        "()=>{const e=document.getElementById('landscapingHouseRateNote');"
                        "return e?e.textContent:''}"),
                    "by_class": page.evaluate(
                        "()=>lastResult.summary.landscaping_by_class_th"),
                }
            out["errors"] = page.evaluate(
                "()=>document.querySelectorAll('.fatal').length")
            browser.close()
    return out


def test_the_rate_caption_prints_the_number_that_returns(captions) -> None:
    """В скобках — методика, а не то же число, что в поле."""
    assert captions["errors"] == 0, "страница не доработала"
    hand = captions[HAND_RATE]
    shown = f"{float(hand['by_class']):.2f}".replace(".", ",")
    assert shown in hand["rate"], hand["rate"]
    # Зеркало ловится прямо: введённого числа в обещании быть не должно.
    assert "(30" not in hand["rate"], hand["rate"]
    assert "Очистите поле" in hand["rate"]


def test_the_area_caption_says_the_yard_is_out_of_the_money(captions) -> None:
    """Двор назван, и сказано, что при заданной ставке он в деньги не идёт."""
    assert "в деньги не идёт" in captions[HAND_RATE]["area"], captions[HAND_RATE]["area"]
    assert "в деньги не идёт" not in captions[0.0]["area"], captions[0.0]["area"]
    assert "Двор" in captions[0.0]["area"]
