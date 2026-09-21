"""Ноль благоустройства называется вслух, а не исчезает из расходов.

Владелец, 20.09.2026: «Благоустройства так и нет в новом формате». Так и есть,
и это не вёрстка. Двор считается от населения, население — от площади квартир;
в нежилом проекте квартир нет, методика честно отвечает нулём, а нулевая строка
в структуру расходов не попадает («строка появляется вместе с числом»). Статья
исчезала с экрана, из PDF и из разговора целиком, и её отсутствие читалось как
ответ методики «благоустройства здесь не нужно» — при том что ответ другой:
мерить нечем, а двор входит в себестоимость объекта.

Рядом подпись под самой ставкой говорила «Расчёта ещё нет» на честно
посчитанном нуле — то есть винила кнопку за ответ методики. Правило записано
(«ноль величины — ответ методики, а не отсутствие расчёта») и соседнюю подпись
не защитило.

Утверждений четыре: пустота названа движком и только при построенных метрах;
на своде очередей она названа счётом, а не чужим текстом; подпись ставки
различает «не считали» и «посчитали ноль»; строка пустоты видна в структуре
расходов на живой странице.

Запуск: python3 -m pytest tests/test_the_empty_yard_is_named.py -q
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

PORT = 18965
OFFICE_GNS = 40000.0


def _nonresidential() -> tuple[dict, dict]:
    """Нежилой проект: офисник, и ни одной жилой строки в ТЭП."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if field in tep.get(key, {}):
                tep[key][field] = 0
    for key in ("kindergarten", "school", "clinic"):
        for field in ("gns", "total_area", "transfer", "units"):
            if field in tep.get(key, {}):
                tep[key][field] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        inputs[key] = 0
    inputs["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    inputs["offices_enabled"] = True
    inputs["offices_gba_sqm"] = OFFICE_GNS
    tep["offices"] = {**tep["offices"], "gns": OFFICE_GNS,
                      "total_area": OFFICE_GNS * 0.94,
                      "useful": OFFICE_GNS * 0.94 * 0.9,
                      "saleable": OFFICE_GNS * 0.94 * 0.9}
    return inputs, tep


def _summary(inputs: dict, tep: dict) -> dict:
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep))["summary"]


def test_the_empty_article_is_named() -> None:
    """Нежилой проект: статья ноль, и это сказано словами с основанием."""
    inputs, tep = _nonresidential()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep))
    # Предохранитель: метры есть, иначе называть пустоту было бы не о чем.
    assert float(result["summary"]["project_gns_sqm"]) > 0
    assert float(result["capex"].get("landscaping") or 0.0) == 0.0
    gap = str(result["summary"]["landscaping_gap"])
    assert "Благоустройства в расчёте нет" in gap, gap
    # Чем мерить, больше не спрашивают: двор нежилого проекта входит в
    # себестоимость объекта и отдельной статьёй не считается (владелец,
    # 21.09.2026). Пустота при этом по-прежнему названа.
    assert "себестоимость объекта" in gap, gap
    # Нулевой строки в структуре расходов не бывает — ради этого и фраза.
    assert not [item for item in result["report"]["expense_structure"]
                if "лагоустр" in str(item.get("label"))]


def test_a_paid_yard_is_not_called_empty() -> None:
    """Статья посчитана — называть нечего: приписка в каждом отчёте не читается."""
    paid = _summary(copy.deepcopy(core.DEFAULT_INPUTS),
                    copy.deepcopy(core.TEP_DEFAULT))
    assert float(paid["landscaping_per_gns_th"]) > 0
    assert paid["landscaping_gap"] == ""
    # И ставкой на метр ГНС — тоже статья, а не пустота.
    inputs, tep = _nonresidential()
    inputs["landscaping_gns_th_per_sqm"] = 3.0
    assert _summary(inputs, tep)["landscaping_gap"] == ""


def test_the_project_with_no_metres_is_not_scolded() -> None:
    """Ничего не строим — пустоты нет: это не пробел методики, а пустой ТЭП."""
    inputs, tep = _nonresidential()
    tep["offices"] = {**tep["offices"], "gns": 0, "total_area": 0,
                      "useful": 0, "saleable": 0}
    inputs["offices_gba_sqm"] = 0
    summary = _summary(inputs, tep)
    assert float(summary["project_gns_sqm"]) == 0
    assert summary["landscaping_gap"] == ""


def test_the_phase_summary_counts_instead_of_borrowing_a_reason() -> None:
    """Свод очередей называет счёт: основание у каждой очереди своё."""
    assert core._phase_landscaping_gap([]) == ""
    both = [{"summary": {"landscaping_gap": "A"}}, {"summary": {"landscaping_gap": "B"}}]
    assert core._phase_landscaping_gap(both) == "Благоустройства в расчёте нет ни в одной очереди."
    # Чужой текст в свод не уезжает: он говорил бы за остальные очереди.
    assert "A" not in core._phase_landscaping_gap(both)
    one = [{"summary": {"landscaping_gap": "A"}}, {"summary": {"landscaping_gap": ""}}]
    assert "в 1 очередях из 2" in core._phase_landscaping_gap(one)
    assert core._phase_landscaping_gap([{"summary": {}}]) == ""


@pytest.fixture(scope="module")
def screen() -> dict:
    """Подпись ставки и строка пустоты — с живой страницы нежилого проекта.

    Обе живут после расчёта и читают `lastResult`: стендом на node их не
    позвать, а в исходнике сломанная и починенная выглядят одинаково.
    """
    from playwright.sync_api import sync_playwright

    import main as app_mod

    path = chromium_or_skip()
    inputs, tep = _nonresidential()
    out: dict = {}
    with serve(app_mod.app, PORT):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=path)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="load")
            page.wait_for_function("()=>typeof lastResult!=='undefined'", timeout=60000)
            out["before"] = page.evaluate(
                "()=>{const e=document.getElementById('landscapingHouseRateNote');"
                "return e?e.textContent:''}")
            page.evaluate("d=>{Object.assign(inputs,d.inputs);"
                          "Object.keys(d.tep).forEach(k=>{tep[k]=d.tep[k]});}",
                          {"inputs": inputs, "tep": tep})
            page.evaluate("()=>calculate()")
            # Ждать надо то, что от проверяемого НЕ зависит: ожидание самой
            # пустоты на сломанном движке даёт минуту молчания и падение
            # фикстуры вместо внятного «пустота не названа».
            page.wait_for_function(
                "()=>lastResult&&lastResult.summary"
                "&&lastResult.summary.project_kind==='nonresidential'",
                timeout=60000)
            page.evaluate("()=>{openTab('inputs');renderInputs();}")
            out["rate"] = page.evaluate(
                "()=>{const e=document.getElementById('landscapingHouseRateNote');"
                "return e?e.textContent:''}")
            out["expenses"] = page.evaluate(
                "()=>{const e=document.getElementById('expenseStructureTable');"
                "return e?e.textContent:''}")
            out["errors"] = page.evaluate("()=>document.querySelectorAll('.fatal').length")
            browser.close()
    return out


def test_the_caption_tells_a_computed_zero_from_no_calculation(screen) -> None:
    """«Посчитали ноль» и «ещё не считали» — разные ответы, и оба сказаны."""
    assert screen["errors"] == 0, "страница не доработала"
    assert "Расчёта ещё нет" in screen["before"], screen["before"]
    assert "Расчёта ещё нет" not in screen["rate"], screen["rate"]
    assert "себестоимость объекта" in screen["rate"], screen["rate"]
    # И ставку здесь по-прежнему можно задать — методика её не запрещает.
    assert "перебьёт" in screen["rate"], screen["rate"]


def test_the_expense_table_names_the_empty_article(screen) -> None:
    """Пустота видна там, где человек ищет статью, — в структуре расходов."""
    assert "Благоустройства в расчёте нет" in screen["expenses"], screen["expenses"][:400]


def test_the_report_names_the_empty_article_too() -> None:
    """Отчёт носят в банк: пустота названа и на бумаге, той же фразой."""
    pypdf = pytest.importorskip("pypdf")
    inputs, tep = _nonresidential()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    content = core._build_developaid_pdf({
        "project_name": "Нежилой", "result": result,
        "inputs": inputs, "tep": tep, "rates": [],
    })
    path = Path("/tmp") / "empty_yard.pdf"
    path.write_bytes(content)
    reader = pypdf.PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Благоустройства в расчёте нет" in text
