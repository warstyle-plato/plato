"""«Из каких денег платим ВРИ» — варианты названы тем, что они делают.

Владелец не понял «Как весь проект» / «Заданные доли»: что это значит, не
сказано, а доли под ними при первом варианте не читались и стояли нулями без
объяснения, при втором — молча делились на свою сумму. Теперь: «Автоматически:
до ПФ — БРИДЖ, после — ПФ» / «Вручную по долям»; доли при автоматическом
разносе заперты с подписью (тот же замок, что у льготы — `vriReliefFieldIdle`);
сумма долей ≠ 100 подписана нормировкой, сумма 0 — разносом по дате. Ключи
значений прежние: сохранённые проекты читаются как раньше.

Запуск: python3 -m pytest tests/test_the_vri_money_source_says_what_it_does.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
from tests import browser  # noqa: E402

core = wrapper.core

AUTO = "Автоматически: до ПФ — БРИДЖ, после — ПФ"
SHARES = "Вручную по долям"


def test_one_source_of_words():
    assert core._input_field_label("vri_financing_mode") == "Из каких денег платим ВРИ"
    assert core.input_option_label("vri_financing_mode", "auto") == AUTO
    assert core.input_option_label("vri_financing_mode", "shares") == SHARES


PROBE = """(shares)=>{
 const out={};
 const pick=()=>{
  const sel=document.getElementById('f_vri_financing_mode');
  const box=k=>document.getElementById('f_'+k);
  const note=document.getElementById('vriSharesNote');
  return {options:Array.from(sel.options).map(o=>o.textContent),
   label:(sel.closest('.field')||sel.parentElement).textContent,
   locked:['vri_share_bridge_pct','vri_share_pf_pct','vri_share_equity_pct'].map(k=>box(k).disabled),
   idle:Array.from(document.querySelectorAll('.vri-relief-idle')).map(e=>e.textContent),
   note:note&&note.style.display!=='none'?note.textContent:''};
 };
 out.auto=pick();
 const sel=document.getElementById('f_vri_financing_mode');
 sel.value='shares';sel.dispatchEvent(new Event('change'));
 out.shares_zero=pick();
 const b=document.getElementById('f_vri_share_bridge_pct');
 b.value=String(shares);b.dispatchEvent(new Event('change'));
 out.shares_half=pick();
 return out;
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18795) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("!!document.getElementById('f_vri_financing_mode')",
                                   timeout=20000)
            got = page.evaluate(PROBE, 50)
            page.close()
    assert not errors, f"страница упала: {errors[:2]}"
    return got


def test_the_options_say_what_they_do(seen):
    assert seen["auto"]["options"] == [AUTO, SHARES]
    assert "Из каких денег платим ВРИ" in seen["auto"]["label"]


def test_shares_are_locked_and_signed_in_auto(seen):
    assert seen["auto"]["locked"] == [True, True, True]
    assert sum("Не читается: источники — по дате платежа" in t
               for t in seen["auto"]["idle"]) == 3


def test_zero_shares_say_the_date_split_is_used(seen):
    assert seen["shares_zero"]["locked"] == [False, False, False]
    assert "Доли не заданы" in seen["shares_zero"]["note"]


def test_shares_off_a_hundred_say_how_they_are_normed(seen):
    note = seen["shares_half"]["note"].replace("\xa0", " ")
    assert "Сумма долей 50%" in note and "БРИДЖ 100%" in note
