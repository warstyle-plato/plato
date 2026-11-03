"""Ручной и кадастровый ТЭП без выгрузки ГлавАПУ считается нормативами СВОЕГО региона.

«Сформировать ТЭП по плотности» звала `/mo/calculate` для любого проекта — и
Москва получала нормы области: 28 м²/чел, ДОО 65 и СОШ 135 на тысячу,
356 × 0,9 машино-мест; регион ВРИ при этом восстанавливался только без
участков. Решение владельца (16.10.2026, docs/normative_audit_msk_mo_2026-10.md,
§6, вопрос 3): Москва (`vri_region` 'msk' или пусто — пусто значит Москва, как
у `classRegion()`) считается методикой движка `tep_derived_norms` через
`/tep/derived-by-site`; область ('mo') — как прежде, через `/mo/calculate`.
Регион выбирает один предикат страницы — `classRegion()`.

Стенд гоняет НАСТОЯЩИЙ `applyNormativeTep` со страницы; `fetch` подменён и
записывает, какой адрес и с чем вызван. Ответы маршрутов — у самого сервера,
а числа московского маршрута сверяются с `core.tep_derived_norms`.

Запуск: python3 -m pytest tests/test_a_moscow_tep_is_not_counted_by_the_oblast.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402

AREA_HA = 2.0
DENSITY = 25_000
SALEABLE = AREA_HA * DENSITY
DISTRICT = "Некрасовка"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import main_registry

    return TestClient(main_registry.app)


@pytest.fixture(scope="module")
def answers(client) -> dict:
    """Ответы обоих маршрутов — у сервера, не выдуманные стендом."""
    gns = round(SALEABLE / core.TEP_RATIOS["apartments"]["saleable_of_gns"], 1)
    msk = client.post("/tep/derived-by-site", json={
        "apartment_area_sqm": SALEABLE, "residential_living_spp_sqm": gns,
        "nonresidential_np_sqm": 0, "apartment_count": 0,
        "district": DISTRICT, "inside_moscow": True})
    assert msk.status_code == 200, msk.text
    mo = client.post("/mo/calculate", json={
        "query": "", "limit": 30, "site_area_ha": AREA_HA,
        "density_sqm_per_ha": DENSITY, "district": "",
        "market_price_rub_per_sqm": 0, "vri_kd": 0, "average_flat_sqm": 0})
    assert mo.status_code == 200, mo.text
    return {"/tep/derived-by-site": msk.json(), "/mo/calculate": mo.json()}


def run_apply(region: str | None, answers: dict) -> dict:
    inputs = {"site_area_ha": AREA_HA, "site_density_sqm_per_ha": DENSITY,
              "_site_density_user_set": True}
    if region is not None:
        inputs["vri_region"] = region
    prelude = "\n".join([
        "let inputs=" + json.dumps(inputs, ensure_ascii=False) + ";",
        "let tep=" + json.dumps(core.TEP_DEFAULT, ensure_ascii=False) + ";",
        "let cadastralAnalysis={territory:{district:" + json.dumps(DISTRICT, ensure_ascii=False)
        + ",inside_moscow:true}},moResult=null;",
        "const ANSWERS=" + json.dumps(answers, ensure_ascii=False) + ";",
        "const calls=[];",
        "async function fetch(url,opts){calls.push({url,body:JSON.parse(((opts||{}).body)||'{}')});"
        " const answer=ANSWERS[url];if(!answer)throw new Error('стенд не знает маршрута '+url);"
        " return {ok:true,json:async()=>answer}}",
        "const notes={};",
        "const document={getElementById(id){return notes[id]||(notes[id]={style:{},innerHTML:'',value:''})},"
        "activeElement:null};",
        # Отрисовка и экономика к маршрутизации отношения не имеют.
        "function renderTep(){}",
        "function renderInputs(){}",
        "function renderPhasing(){}",
        "async function calculate(){}",
        "function syncTep(){}",
        "function setTepNote(){}",
        "function escapeHtml(s){return String(s)}",
        "function num(v){return Number(v||0).toFixed(1)}",
        "function landNum(v,d){return Number(v||0).toFixed(d===undefined?1:d)}",
    ])
    tail = "\n".join([
        "applyNormativeTep().then(data=>{console.log(JSON.stringify({calls,",
        " places:{kindergarten:inputs.kindergarten_places,school:inputs.school_places,"
        "clinic:inputs.clinic_capacity},",
        " underground:inputs.underground_manual_spaces,guest:inputs._underground_method_guest||null,",
        " apartments:tep.apartments,region:inputs.vri_region,social_basis:inputs._social_basis||null,",
        " source:data.source||null,basis:data.basis||null}))})",
        " .catch(e=>{console.error(e);process.exit(1)});",
    ])
    out, taken = page_blocks.run(prelude, tail)
    got = json.loads(out)
    got["taken"] = taken
    return got


@pytest.fixture(scope="module")
def moscow(answers):
    return run_apply("msk", answers)


@pytest.fixture(scope="module")
def unnamed(answers):
    return run_apply(None, answers)


@pytest.fixture(scope="module")
def oblast(answers):
    return run_apply("mo", answers)


def test_the_stand_runs_the_real_page(moscow):
    for name in ("applyNormativeTep", "classRegion"):
        assert name in moscow["taken"], f"стенд обязан гонять настоящий {name}"


def test_moscow_goes_to_the_city_norms_not_the_oblast_calculator(moscow, answers):
    urls = [call["url"] for call in moscow["calls"]]
    assert "/mo/calculate" not in urls, "Москва посчитана калькулятором области"
    assert urls == ["/tep/derived-by-site"], urls
    body = moscow["calls"][0]["body"]
    assert body["apartment_area_sqm"] == pytest.approx(SALEABLE)
    assert body["inside_moscow"] is True
    assert body["district"] == DISTRICT
    # Постоянные места — пунктом 1 (S / (33 × 2,1) × 0,8): числа квартир у
    # оценки нет, рыночная средняя — не данное города.
    assert body["apartment_count"] == 0
    expected = answers["/tep/derived-by-site"]
    assert moscow["places"] == {k: expected["places"][k] for k in ("kindergarten", "school", "clinic")}
    assert moscow["underground"] == expected["parking"]["underground"]
    assert moscow["guest"] == {"spaces": expected["parking"]["underground"],
                               "guest": expected["parking"]["guest"]}
    assert moscow["region"] == "msk"


def test_an_empty_region_is_moscow(unnamed):
    """Пустой регион — Москва, как у `classRegion()`; областью он не становится."""
    assert [call["url"] for call in unnamed["calls"]] == ["/tep/derived-by-site"]
    assert not unnamed.get("region")


def test_moscow_answer_names_its_origin(moscow):
    assert moscow["source"], "ответ без подписи, чей это расчёт"
    assert "ГлавАПУ" in moscow["source"] and "Москв" in moscow["source"]
    assert any("33 м²" in line for line in moscow["basis"]), moscow["basis"]
    assert "Москв" in moscow["social_basis"]["source"]
    assert "област" not in moscow["source"].lower()


def test_the_oblast_keeps_its_calculator(oblast, answers):
    assert [call["url"] for call in oblast["calls"]] == ["/mo/calculate"]
    body = oblast["calls"][0]["body"]
    assert body["site_area_ha"] == pytest.approx(AREA_HA)
    assert body["density_sqm_per_ha"] == pytest.approx(DENSITY)
    expected = answers["/mo/calculate"]
    assert oblast["places"]["kindergarten"] == expected["inputs"]["kindergarten_places"]
    assert oblast["places"]["school"] == expected["inputs"]["school_places"]
    assert oblast["region"] == "mo"
    assert "Московской области" in expected["source"]["service"]


def test_the_two_regions_really_differ(answers):
    """Предохранитель: если нормы совпали бы, маршрут было бы не отличить."""
    msk = answers["/tep/derived-by-site"]["places"]
    mo = answers["/mo/calculate"]["inputs"]
    assert msk["kindergarten"] != mo["kindergarten_places"]
    assert msk["school"] != mo["school_places"]


def test_the_moscow_route_is_the_engine_norms(client, moscow):
    """Числа маршрута — те же, что у `core.tep_derived_norms` на том, что
    отправила страница: второй реализации методики нет."""
    body = moscow["calls"][0]["body"]
    answer = client.post("/tep/derived-by-site", json=body)
    assert answer.status_code == 200, answer.text
    got = answer.json()
    want = core.tep_derived_norms(
        apartment_area_sqm=body["apartment_area_sqm"],
        residential_living_spp_sqm=body["residential_living_spp_sqm"],
        nonresidential_np_sqm=body["nonresidential_np_sqm"],
        zone_two=core.district_zone_two(DISTRICT),
        apartment_count=body["apartment_count"])
    assert got["places"] == {"kindergarten": want["kindergarten_places"],
                             "school": want["school_places"],
                             "clinic": want["clinic_capacity"]}
    assert got["parking"]["permanent"] == want["parking_permanent"]
    assert got["parking"]["guest"] == want["parking_guest"]
    assert got["population"] == want["population"]
    # Страница подставила ровно эти места.
    assert moscow["places"] == got["places"]
    assert moscow["underground"] == want["parking_permanent"] + want["parking_guest"]


# --- подписи -----------------------------------------------------------------

def run_labels(region: str | None) -> list[str]:
    """Настоящая `applyDensityToTep`: что она пишет под кнопкой."""
    inputs = {"site_area_ha": AREA_HA, "site_density_sqm_per_ha": DENSITY,
              "_site_density_user_set": True}
    if region is not None:
        inputs["vri_region"] = region
    prelude = "\n".join([
        "let inputs=" + json.dumps(inputs, ensure_ascii=False) + ";",
        "let tep=" + json.dumps(core.TEP_DEFAULT, ensure_ascii=False) + ";",
        "let cadastralAnalysis=null,moResult=null;",
        "const shown=[];",
        "const document={getElementById:()=>({style:{},set innerHTML(v){shown.push(v)}})};",
        "function num(v){return String(Math.round(v))}",
        "function landNum(v,d){return Number(v||0).toFixed(d===undefined?1:d)}",
        "function escapeHtml(v){return String(v)}",
        "function renderTep(){}",
        "function renderInputs(){}",
        "function refreshGroupPeeks(){}",
        "function syncTep(){}",
        "function calculate(){}",
        "function applyNormativeTep(){return Promise.resolve({source:'стенд'})}",
    ])
    tail = ("applyDensityToTep();\n"
            "setTimeout(()=>console.log(JSON.stringify({shown})),0);\n")
    return page_blocks.run_json(prelude, tail)["shown"]


def test_the_labels_do_not_name_the_oblast_for_moscow():
    shown = run_labels("msk")
    assert any("нормативам Москвы" in s for s in shown), shown
    assert any("ТЭП пересчитан нормативами Москвы" in s for s in shown), shown
    for text in shown:
        assert "РНГП" not in text and "области" not in text, text


def test_the_labels_name_the_rngp_for_the_oblast():
    shown = run_labels("mo")
    assert any("нормативам РНГП Московской области" in s for s in shown), shown
    assert any("ТЭП пересчитан нормативами РНГП Московской области" in s for s in shown), shown
    for text in shown:
        assert "нормативами Москвы" not in text, text


def test_the_region_is_decided_by_one_predicate():
    """Выбор маршрута и подписи — `classRegion()`, а не сравнение строк по месту."""
    for name in ("applyNormativeTep", "normativeNormsLabel", "densityTepPlan"):
        body = page_blocks.function(name)
        assert "classRegion()" in body or "normativeNormsLabel()" in body, name
        assert "String(inputs.vri_region" not in body, (
            f"{name} сравнивает регион сам, мимо classRegion()")
