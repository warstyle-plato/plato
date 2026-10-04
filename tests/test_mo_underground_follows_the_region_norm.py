"""Подземный паркинг МКД в Московской области считается нормой области.

Проект «Мытищи» (владелец, 04.10.2026: «по-моему ошибка в подземном паркинге:
он показывает в МКД какие-то левые 150 мест»). Потребность в местах и движок
(`underground_parking_requirement`), и страница (`parkingRequirement`) брали
только из московских источников — 2118-ПП и выгрузки ГлавАПУ, — плюс десятая
часть гостевых, а регион «Московская область» не читали вовсе. Норматив РНГП
МО у движка при этом был (`mo_social_program`), и соцобъекты по региону на него
уже переключались: на один проект выходило два норматива.

Проверяется на отрисованной странице: регион меняется своим обработчиком
поля, число читается из поля «Машино-места — решение проекта» и строки ТЭП и
сверяется с движком на тех же вводных. Предохранитель — московское число на
тех же квартирах обязано отличаться от областного, иначе проверка зелена на
любом коде.

Запуск: python3 -m pytest tests/test_mo_underground_follows_the_region_norm.py -q
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

READ = """()=>({
  field: Number(document.getElementById('f_underground_manual_spaces').value||0),
  area: Number(document.getElementById('f_underground_manual_gns_sqm').value||0),
  row: Number(tep.underground_parking.units||0),
  need: parkingRequirement(),
  inputs: JSON.parse(JSON.stringify(inputs)),
  tep: JSON.parse(JSON.stringify(tep)),
})"""

REGION = """(value)=>{
  const el=document.getElementById('f_vri_region');
  el.value=value;
  el.dispatchEvent(new Event('change'));
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict[str, dict] = {}
    with browser.serve(core.app, 18157) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            ctx = engine.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.evaluate(REGION, "msk")
            page.wait_for_timeout(1500)
            out["msk"] = page.evaluate(READ)
            page.evaluate(REGION, "mo")
            page.wait_for_timeout(1500)
            out["mo"] = page.evaluate(READ)
            ctx.close()
    return out


def test_moscow_and_region_disagree_on_the_same_flats(seen):
    """Предохранитель: иначе равенство ниже ничего не доказывает."""
    msk, mo = seen["msk"], seen["mo"]
    assert msk["tep"]["apartments"]["saleable"] == mo["tep"]["apartments"]["saleable"]
    assert msk["field"] > 0 and mo["field"] > 0
    assert msk["field"] != mo["field"], (
        f"Москва и область дали одно число {mo['field']} — регион не читается")


def test_the_region_field_shows_the_mo_norm(seen):
    mo = seen["mo"]
    flats = float(mo["tep"]["apartments"]["saleable"])
    want = core.mo_social_program(flats)["parking"]["permanent_spaces"]
    assert mo["field"] == want, (
        f"в поле {mo['field']} м/м, РНГП МО на {flats:.0f} м² квартир — {want}")
    assert mo["row"] == want, f"строка ТЭП {mo['row']} м/м при норме МО {want}"
    assert mo["need"]["guest"] == 0, "в области гостевые в квартале не строятся"
    per = float(mo["inputs"].get("underground_area_per_space_sqm") or 35)
    assert mo["area"] == round(want * per), \
        f"площадь {mo['area']} м² не равна {want} × {per:g}"
    assert "РНГП Московской области" in mo["need"]["basis"]


def test_page_and_engine_give_one_answer(seen):
    """Один вопрос — один ответ: движок на тех же вводных считает то же."""
    for region in ("msk", "mo"):
        got = seen[region]
        inputs = dict(got["inputs"])
        inputs["underground_manual_spaces"] = 0
        inputs["underground_manual_gns_sqm"] = 0
        engine = core.underground_parking_requirement(inputs, got["tep"])
        assert engine and engine["spaces"] == got["need"]["spaces"], (
            f"{region}: страница {got['need']['spaces']}, движок "
            f"{engine and engine['spaces']}")


def test_engine_sells_every_mo_space():
    """Заданные руками места в области все постоянные: 1/11 не вычитается."""
    tep = {"apartments": {"saleable": 20000.0, "units": 300},
           "underground_parking": {"units": 0, "gns": 0}}
    mo = core.underground_tep_row(
        {"vri_region": "mo", "underground_manual_spaces": 220}, tep)
    msk = core.underground_tep_row(
        {"vri_region": "msk", "underground_manual_spaces": 220}, tep)
    assert mo["guest_units"] == 0
    assert core.underground_guest_spaces(mo) == 0
    assert core.underground_guest_spaces(msk) == 20, "Москва по-прежнему S/11"


def test_the_designers_200k_workbook():
    """Расчёт проектировщиков «Мытищи» на 200 000 м² квартир (04.10.2026):
    население 7 143, постоянных мест 2 289 (90% от 356 на 1000), подземная
    площадь 80 115 м² (35 м²/место) — гостевых сверху нет."""
    tep = {"apartments": {"saleable": 200000.0},
           "underground_parking": {"units": 0, "gns": 0}}
    need = core.underground_parking_requirement({"vri_region": "mo"}, tep)
    assert need["spaces"] == 2289 and need["guest"] == 0
    row = core.underground_tep_row({"vri_region": "mo"}, tep)
    assert row["units"] == 2289 and row["gns"] == 80115
    assert core.underground_guest_spaces(row) == 0


# Состояние проекта «Мытищи» (выгрузка владельца, 04.10.2026): регион МО,
# пара подземного паркинга 150 м/м / 5 215 м² осталась от прежнего участка и
# помечена «руками», а расчёт МО по этому участку даёт 2 289 / 80 115.
STALE = """()=>{
  inputs.vri_region='mo';
  inputs.underground_manual_spaces=150;
  inputs.underground_manual_gns_sqm=5215;
  markParkingByHand(PROJECT_PARKING_KEY);
}"""

APPLY = """async (silent)=>{
  const response=await fetch('/mo/calculate',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:'',limit:30,site_area_ha:6.6667,
      density_sqm_per_ha:30000,district:'',market_price_rub_per_sqm:0,vri_kd:0,
      average_flat_sqm:AVERAGE_FLAT.mo.sqm})});
  moResult=await response.json();
  if(silent)inputs._mo_calc=inputs._mo_calc||{};
  await applyMo({silent});
  return {spaces:Number(inputs.underground_manual_spaces||0),
          area:Number(inputs.underground_manual_gns_sqm||0),
          row:Number(tep.underground_parking.units||0),
          flats:Number(tep.apartments.saleable||0),
          field:Number(document.getElementById('f_underground_manual_spaces').value||0),
          byHand:parkingByHand(PROJECT_PARKING_KEY)};
}"""


@pytest.fixture(scope="module")
def applied():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict[str, dict] = {}
    with browser.serve(core.app, 18163) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for mode, silent in (("explicit", False), ("silent", True)):
                ctx = engine.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                page.evaluate(STALE)
                out[mode] = page.evaluate(APPLY, silent)
                ctx.close()
    return out


def test_applying_the_mo_site_drops_the_old_parking_pair(applied):
    got = applied["explicit"]
    want = core.mo_social_program(got["flats"])["parking"]["permanent_spaces"]
    assert want > 150, f"проверка ничего не доказывает: норма {want}"
    assert got["spaces"] == want and got["row"] == want and got["field"] == want, got
    assert not got["byHand"], "норма нового участка помечена как ручная"


def test_a_silent_refresh_keeps_the_hand_pair(applied):
    """Предохранитель: тихое обновление того же участка руки не трогает —
    иначе сброс выше мог бы оказаться сбросом на любой пересчёт."""
    got = applied["silent"]
    assert got["spaces"] == 150 and got["area"] == 5215 and got["byHand"], got
