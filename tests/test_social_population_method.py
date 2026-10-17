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

from browser import chromium_or_skip, serve  # noqa: E402

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


def test_the_page_switch_recounts_the_places():
    """Настоящая страница: переключатель в форме меняет места в вводных."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    from main_registry import app as registry_app  # noqa: PLC0415

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            tab.wait_for_timeout(600)
            got = tab.evaluate("""async ()=>{
              cadastralAnalysis={territory:{district:'', inside_moscow:true}};
              inputs._glavapu_import=null; inputs._social_basis=null;
              tep.apartments.saleable=45000; tep.apartments.gns=50000;
              tep.apartments.units=1000;
              inputs.kindergarten_places=0; inputs.school_places=0;
              inputs.clinic_capacity=0;
              renderInputs();
              const el=document.getElementById('f_social_population_method');
              const options=el?[...el.options].map(o=>o.value):[];
              await recalcFromTep({silent:true});
              const before=inputs.school_places;
              // Пересчёт перерисовал вводные — поле берётся заново, как его
              // видит человек.
              const live=document.getElementById('f_social_population_method');
              live.value='flats_household';
              live.dispatchEvent(new Event('change'));
              for(let i=0;i<40&&inputs.school_places===before;i++)
                await new Promise(r=>setTimeout(r,100));
              const note=document.getElementById('tepDerivedNote');
              return {options, before, after:inputs.school_places,
                      method:inputs.social_population_method,
                      note:(note&&note.textContent)||''};
            }""")
        finally:
            browser.close()
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["options"] == list(core.SOCIAL_POPULATION_METHODS)
    assert (got["before"], got["after"], got["method"]) == (123, 189, "flats_household")
    assert "требование органа" in got["note"]
