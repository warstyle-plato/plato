"""Население для соцобъектов Москвы: норма РНГП или требование органа.

Норма — п. 1.4.2 и табл. 1.4.1 2152-ПП (ред. 2579-ПП): площадь квартир / 33 м².
Город на деле требует «1 квартира = 2,1 жителя». Решение владельца
(16.10.2026): умолчание — норма, требование органа — переключателем проекта;
действует только на ДОО, школу, поликлинику и компенсацию за них. Разбор —
docs/rngp_social_load_population.md.

Пример владельца: 1 000 квартир по 45 м² — по норме 1 364 жителя, по
требованию органа 2 100.

Запуск: python3 -m pytest tests/test_social_population_method.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import chromium_or_skip, serve, wait_for_result  # noqa: E402

import main_legacy as core  # noqa: E402

PORT = 18298
AREA, FLATS = 45000.0, 1000


def test_the_norm_is_the_default_and_names_its_clause():
    people, basis, method = core.moscow_social_population(AREA, FLATS)
    assert (people, method) == (1364, "rngp_area")
    assert "2152-ПП" in basis
    assert core.DEFAULT_INPUTS["social_population_method"] == "rngp_area"


def test_the_authority_method_counts_flats_and_says_it_is_not_the_norm():
    people, basis, method = core.moscow_social_population(AREA, FLATS, "flats_household")
    assert (people, method) == (2100, "flats_household")
    assert "требование органа, не РНГП" in basis
    assert "число квартир из ТЭП" in basis and "1364" in basis


def test_without_a_flat_count_the_average_flat_is_named():
    people, basis, _ = core.moscow_social_population(AREA, 0, "flats_household")
    flat_sqm, _ = core.average_flat_sqm("manual")
    flats = -(-AREA // flat_sqm)
    assert people == -(-int(flats * 21) // 10)
    assert "не задано" in basis and f"{flat_sqm:g} м²" in basis


def test_an_unknown_method_is_the_norm_not_a_zero():
    assert core.moscow_social_population(AREA, FLATS, "junk")[:1] == (1364,)
    assert core.moscow_social_population(AREA, FLATS, "")[2] == "rngp_area"


def test_the_switch_moves_social_places_and_only_them():
    kwargs = dict(apartment_area_sqm=AREA, residential_living_spp_sqm=50000,
                  nonresidential_np_sqm=3000, upks_rub=100000.0, apartment_count=FLATS)
    norm = core.tep_derived_norms(**kwargs)
    city = core.tep_derived_norms(**kwargs, social_population_method="flats_household")
    assert norm["social_population"] == norm["population"] == 1364
    assert city["social_population"] == 2100
    # Места — от 2 100 жителей, по нормативам первой зоны.
    assert city["school_places"] == -(-90 * 2100 // 1000) == 189
    assert city["kindergarten_places"] == -(-44 * 2100 // 1000)
    assert city["compensation_mln"] > norm["compensation_mln"]
    # Машино-места, население нормы и места приложения труда не меняются.
    for key in ("population", "apartment_units", "parking_permanent",
                "parking_guest", "parking_onsite", "jobs"):
        assert city[key] == norm[key], key


def test_the_endpoint_and_the_baseline_recalc_take_the_switch():
    client = TestClient(core.app)
    body = {"apartment_area_sqm": AREA, "residential_living_spp_sqm": 50000,
            "apartment_count": FLATS, "district": ""}
    norm = client.post("/tep/derived-by-site", json=body).json()
    city = client.post("/tep/derived-by-site",
                       json=dict(body, social_population_method="flats_household")).json()
    assert norm["places"]["school"] == 123 and city["places"]["school"] == 189
    assert city["social_population"] == 2100
    assert any("требование органа" in line for line in city["basis"])

    from test_recalc_under_the_approved_tep import APPROVED, BASELINE  # noqa: PLC0415

    same = dict(APPROVED, apartment_count=FLATS)
    base = core.recalculate_from_glavapu_baseline(BASELINE, same)
    moved = core.recalculate_from_glavapu_baseline(
        BASELINE, dict(same, social_population_method="flats_household"))
    assert moved["social_population"] == 2100
    assert moved["places"]["school"] > base["places"]["school"]
    assert moved["parking"] == base["parking"]


def test_the_city_requirement_follows_the_switch():
    tep = {"apartments": {"saleable": AREA, "units": FLATS}}
    norm = core.social_required_program({}, tep)
    city = core.social_required_program({"social_population_method": "flats_household"}, tep)
    assert norm["school_places"] == 123
    assert city["school_places"] == 189
    assert "требование органа" in city["basis"]


def test_the_form_options_are_the_engine_methods():
    fields = {f[0]: f for _group, items in core.FIELD_GROUPS for f in items}
    options = [value for value, _label in fields["social_population_method"][4]]
    assert options == list(core.SOCIAL_POPULATION_METHODS)


_SWITCH = """async (setup)=>{
  cadastralAnalysis={territory:{district:'', inside_moscow:true}};
  inputs._glavapu_import=null;
  tep.apartments.saleable=45000; tep.apartments.gns=50000; tep.apartments.units=1000;
  Object.assign(inputs,{kindergarten_places:267,school_places:500,clinic_capacity:100,
    social_compensation_mln:478.807,social_population_method:'rngp_area'});
  // Соцнагрузка посчитана на других метрах: пересчёт ТЭП пошёл бы пропорцией,
  // а она переключателя не видит.
  inputs._social_basis={apartment_area_sqm:40000,nonresidential_sqm:0,source:'нормативы Москвы'};
  if(setup==='manual')markFieldManual('inputs.kindergarten_places');
  if(setup==='krt')inputs.social_area_source='manual';
  syncTep(false);renderInputs();
  const watched=['kindergarten_places','school_places','clinic_capacity','social_compensation_mln',
    'land_rights_cost_mln','underground_manual_spaces'];
  const before=Object.fromEntries(watched.map(k=>[k,inputs[k]]));
  // Выбор — как у человека: значение в поле и событие change.
  const live=document.getElementById('f_social_population_method');
  live.value='flats_household';
  live.dispatchEvent(new Event('change'));
  const note=()=>document.getElementById('socialPopulationNote');
  for(let i=0;i<60;i++){
    const text=(note()&&note().textContent)||'';
    if(text&&!text.startsWith('Пересчитываю'))break;
    await new Promise(r=>setTimeout(r,100));
  }
  openTab('inputs');
  const group=document.querySelector('details[data-group="Социальная нагрузка"]');
  if(group)group.open=true;
  const n=note();
  return {before, after:Object.fromEntries(watched.map(k=>[k,inputs[k]])),
          field:document.getElementById('f_kindergarten_places').value,
          note:(n&&n.textContent)||''};
}"""


def _switch(setup: str = "") -> dict:
    """Настоящая страница на ширине телефона: переключатель в форме вводных."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    from main_registry import app as registry_app  # noqa: PLC0415

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 844})
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/", wait_until="domcontentloaded")
            wait_for_result(tab)
            got = tab.evaluate(_SWITCH, setup)
            # Итог виден под самим переключателем, а не на вкладке ТЭП.
            note = tab.locator("#socialPopulationNote")
            got["note_visible"] = note.count() == 1 and note.is_visible()
            if got["note_visible"]:
                select_box = tab.locator("#f_social_population_method").bounding_box()
                note_box = note.bounding_box()
                got["note_below_select"] = note_box["y"] >= select_box["y"] + select_box["height"] - 1
        finally:
            browser.close()
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    return got


def test_the_page_switch_recounts_the_places_by_the_chosen_method():
    """«Ничего не меняется при переключении» (владелец, 19.10.2026).

    Соцнагрузка, посчитанная на других метрах, уводила переключатель в
    пропорцию по площади: места менялись от метров, а не от способа, и
    компенсация на нормативном пути не двигалась вовсе.
    """
    got = _switch()
    norm = core.tep_derived_norms(apartment_area_sqm=45000, residential_living_spp_sqm=50000,
                                  apartment_count=1000,
                                  social_population_method="flats_household")
    assert got["after"]["kindergarten_places"] == norm["kindergarten_places"] == 93
    assert got["after"]["school_places"] == norm["school_places"] == 189
    assert got["after"]["clinic_capacity"] == norm["clinic_capacity"]
    assert got["field"] == "93"
    # Компенсация идёт за жителями: 1 364 по норме → 2 100 по квартирам.
    assert got["after"]["social_compensation_mln"] == round(478.807 * 2100 / 1364, 3)
    # Машино-места и плата за ВРИ от способа не зависят.
    for key in ("land_rights_cost_mln", "underground_manual_spaces"):
        assert got["after"][key] == got["before"][key], key
    assert got["note_visible"] and got["note_below_select"]
    assert "2,1" in got["note"] and "267 → 93" in got["note"]
    assert "1 364 → 2 100" in got["note"].replace("\xa0", " ")


def test_places_typed_by_hand_stay_and_the_note_says_why():
    got = _switch("manual")
    assert got["after"]["kindergarten_places"] == 267
    assert got["after"]["school_places"] == 189
    assert got["note_visible"]
    assert "Вписаны вручную, переключатель их не меняет: места ДОО" in got["note"]


def test_the_krt_requirement_is_not_touched_and_the_note_says_why():
    got = _switch("krt")
    for key in ("kindergarten_places", "school_places", "clinic_capacity",
                "social_compensation_mln"):
        assert got["after"][key] == got["before"][key], key
    assert got["note_visible"], got
    assert "требование КРТ" in got["note"]


def test_glavapu_places_follow_the_switch_and_nothing_else_moves():
    """Снимок проекта с выгрузкой ГлавАПУ: места — по ставкам выгрузки.

    Прежде переключатель звал весь пересчёт ТЭП, и он заодно переписывал
    плату за ВРИ и машино-места — чужие для переключателя числа.
    """
    import json  # noqa: PLC0415

    snapshot = json.loads((Path(__file__).resolve().parent.parent / "docs" / "projects"
                           / "77_01_0006018_75_2026-09-09.json").read_text("utf-8"))
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    from main_registry import app as registry_app  # noqa: PLC0415

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 844})
            tab.goto(f"{base}/", wait_until="domcontentloaded")
            wait_for_result(tab)
            got = tab.evaluate("""async (data)=>{
              applyProjectSnapshot(data);
              const wait=()=>new Promise(r=>setTimeout(r,100));
              for(let i=0;i<30&&!glavapuBaselineApplies();i++)await wait();
              syncTep(false);renderInputs();
              const keys=['kindergarten_places','school_places','clinic_capacity',
                'social_compensation_mln','land_rights_cost_mln','underground_manual_spaces'];
              const before=Object.fromEntries(keys.map(k=>[k,inputs[k]]));
              const live=document.getElementById('f_social_population_method');
              live.value='flats_household';live.dispatchEvent(new Event('change'));
              const note=()=>(document.getElementById('socialPopulationNote')||{}).textContent||'';
              for(let i=0;i<60&&(!note()||note().startsWith('Пересчитываю'));i++)await wait();
              return {before,after:Object.fromEntries(keys.map(k=>[k,inputs[k]])),note:note()};
            }""", snapshot)
        finally:
            browser.close()
    assert got["after"]["kindergarten_places"] != got["before"]["kindergarten_places"], got
    assert got["after"]["social_compensation_mln"] != got["before"]["social_compensation_mln"]
    for key in ("land_rights_cost_mln", "underground_manual_spaces"):
        assert got["after"][key] == got["before"][key], key
    assert "ставкам за место из выгрузки ГлавАПУ" in got["note"]
