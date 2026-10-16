"""Плату за смену ВРИ решает сумма, а не признак «Требуется изменение ВРИ».

Владелец увидел на телефоне снятую галочку «Требуется изменение ВРИ», а под
ней — обязательство 1,27 млрд ₽ с процентами и графиком платежей. Признак
терялся у сохранённых проектов (страница писала явный `false`), и на один
вопрос «действует ли плата» отвечали по-разному: движок молча включал признак
обратно и писал предупреждение, страница показывала галочку снятой, сверка
ГлавАПУ по снятому признаку писала ВРИ = 0, тизер решал «признак или сумма».

Решение владельца — «сумма решает»: один предикат `vri_payment_active`
(плата > 0), все читатели берут ответ у него. Снять галочку на странице —
значит обнулить плату, с подтверждением и видимой подписью.

Запуск: python3 -m pytest tests/test_the_vri_fee_decides_the_flag.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
from tests import browser  # noqa: E402

core = wrapper.core

FEE_MLN = 1276.304
# Сохранённый проект, у которого признак потерян: явный false при плате > 0.
LOST_FLAG = {"vri_required": False, "land_rights_cost_mln": FEE_MLN}


def _inputs(**extra) -> dict:
    x = dict(core.DEFAULT_INPUTS)
    x.update(LOST_FLAG, **extra)
    return x


def test_the_fee_alone_answers_the_question():
    assert core.vri_payment_active(LOST_FLAG) is True
    assert core.vri_payment_active({"vri_required": True, "land_rights_cost_mln": 0}) is False
    assert core.vri_payment_active({"vri_required": True}) is False


def test_the_engine_builds_the_schedule_without_a_contradiction_warning():
    permit = core.project_permit_date(_inputs())
    vri = core.build_vri_schedule(_inputs(), FEE_MLN * 1e6, permit)
    assert vri["enabled"] and vri["rows"], "плата задана — график обязан строиться"
    assert vri["settings"]["required"] is True
    assert not [w for w in vri["warnings"] if "Требуется изменение ВРИ" in w], (
        "противоречия «признак снят, плата задана» больше нет — нет и предупреждения")


def test_the_glavapu_check_does_not_write_zero_over_a_set_fee():
    ours, _ = core._glavapu_scenario_ours(_inputs(), core.TEP_DEFAULT, {"params": {}})
    value, origin = ours["vri_cost_mln"]
    assert value == pytest.approx(FEE_MLN), origin


def test_the_teaser_and_the_book_say_yes():
    import presentation
    import teaser_pdf

    land = presentation._land_block(
        {"land": {"vri_active": core.vri_payment_active(LOST_FLAG),
                  "vri_amount_mln": FEE_MLN}}, LOST_FLAG)
    assert land["vri_required"] is True
    rows = teaser_pdf._vri_rows({"land": land}, teaser_pdf._Formats(lambda v, d=1: f"{v:.{d}f}"))
    assert rows and rows[0][0] == "Плата за смену ВРИ"


def test_a_preset_with_a_fee_does_not_switch_the_flag_off():
    import project_preset

    inputs, _ = project_preset.map_inputs(
        {"vri": {"residual_principal_rub": FEE_MLN * 1e6}}, {})
    assert inputs["land_rights_cost_mln"] == pytest.approx(FEE_MLN)
    assert inputs.get("vri_required") is not False


PROBE = """(saved)=>{
 const out={};
 window.confirm=()=>true;
 applyProjectSnapshot(JSON.parse(JSON.stringify({inputs:Object.assign({},INPUT_DEFAULT,saved),
   tep:{},phasing:null,scenario:'base'})));
 const box=document.getElementById('f_vri_required');
 out.box_found=!!box;
 out.checked=!!(box&&box.checked);
 out.note=(document.getElementById('vriRequiredNote')||{}).textContent||'';
 return out;
}"""

UNCHECK = """()=>{
 const out={};
 window.confirm=()=>true;
 // Снятие галочки — обнуление платы с подтверждением.
 const box=document.getElementById('f_vri_required');
 box.checked=false;box.dispatchEvent(new Event('change'));
 out.after_fee=Number(inputs.land_rights_cost_mln);
 out.after_checked=document.getElementById('f_vri_required').checked;
 out.after_note=(document.getElementById('vriRequiredNote')||{}).textContent||'';
 out.after_field=(document.getElementById('f_land_rights_cost_mln')||{}).value;
 return out;
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18793) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("typeof applyProjectSnapshot==='function'"
                                   "&&document.querySelectorAll('details[data-group]').length>3",
                                   timeout=20000)
            got = page.evaluate(PROBE, LOST_FLAG)
            page.evaluate("calculate()")
            page.wait_for_function(
                "document.querySelectorAll('#vriTabSchedule tr').length>0", timeout=60000)
            got["schedule_rows"] = page.evaluate(
                "document.querySelectorAll('#vriTabSchedule tr').length")
            got.update(page.evaluate(UNCHECK))
            page.close()
    assert not errors, f"страница упала: {errors[:2]}"
    assert got["box_found"], "галочки «Требуется изменение ВРИ» на странице нет"
    return got


def test_a_saved_false_with_a_fee_is_shown_switched_on(seen):
    assert seen["checked"] is True
    assert "задана" in seen["note"] and "1 276,3" in seen["note"].replace("\xa0", " ")


def test_the_schedule_is_drawn(seen):
    assert seen["schedule_rows"] > 0


def test_unchecking_clears_the_fee_and_says_so(seen):
    assert seen["after_fee"] == 0
    assert seen["after_checked"] is False
    assert "обнулена" in seen["after_note"]
    assert str(seen["after_field"]) in ("0", "")
