"""Участок вне Москвы и области — режим «Другой регион», а не Москва молча.

Поле `vri_region` знало только Москву и область, и любое другое значение
читалось как Москва: участок из Екатеринбурга (66:41:0304030:19) получал
московскую рассрочку платы за ВРИ, льготы 1874-ПП, парковку по 2118-ПП и
соцобъекты по московской норме, а «Получить ТЭП» отправлял его в калькулятор
ГлавАПУ, чей отказ человеку ничего не объяснял. Решение владельца 19.10.2026:
площадь, разрешённое использование и кадастровая стоимость — из госреестра,
ТЭП — по плотности, которую задаёт человек (стартовые 30 000 м² квартир на
гектар — допущение), соцобъекты, парковку и плату за ВРИ человек вписывает
сам; жители для двора — московские 33 м² на человека, подписанные допущением.
После «Подставить в проект» плата за ВРИ — ноль, остальное — наши умолчания.

Каждая проверка падает на прежнем поведении «считаем как Москву».

Запуск: python3 -m pytest tests/test_another_region_is_not_moscow.py -q
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

EKATERINBURG = "66:41:0304030:19"
OTHER = {"vri_region": "other"}


# --- один предикат региона ---------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("", "msk"), (None, "msk"), ("msk", "msk"), ("mo", "mo"),
    ("other", "other"), ("Другой регион", "other"),
    # Непонятное значение — не Москва: чужие нормы хуже честного «норм нет».
    ("66", "other"), ("ekb", "other"),
])
def test_the_region_has_one_answer(value, expected) -> None:
    assert core.project_region({"vri_region": value}) == expected
    assert core.class_region({"vri_region": value}) == expected


def test_the_region_field_offers_another_region() -> None:
    field = next(f for _group, fields in core.FIELD_GROUPS for f in fields
                 if f[0] == "vri_region")
    assert ["other", "Другой регион"] in [list(o) for o in field[4]], field


def test_a_number_from_another_district_is_another_region() -> None:
    assert core.project_regions.outside_moscow_region(EKATERINBURG)
    # Новая Москва носит областные номера 50: — префикс 50 ничего не решает.
    assert not core.project_regions.outside_moscow_region("50:21:0010101:1")
    assert not core.project_regions.outside_moscow_region("77:01:0004621:72")


# --- московские правила к другому региону не применяются ----------------------

def test_moscow_vri_benefits_do_not_apply() -> None:
    assert core.vri_relief_basis(OTHER) == "none"
    result = core.vri_benefits.compute(OTHER, {}, [])
    assert result["applicable"] is False, result
    assert "не в Москве" in result["reason"], result


def test_moscow_installment_rules_do_not_apply() -> None:
    """Москва: срок 1/3/6 лет, квартал, проценты по умолчанию. Другой регион — как ввели."""
    x = {**OTHER, "vri_installment_years": 2, "vri_periodicity_months": 1}
    settings = core._vri_settings(x, date(2028, 1, 1), 100_000_000.0)
    assert settings["region"] == "other"
    assert settings["years"] == 2 and settings["periodicity"] == 1, settings
    assert settings["interest_enabled"] is False, settings


def test_the_whole_calculation_runs_and_says_so() -> None:
    """Полный расчёт другого региона: без льгот города и со словами о порядке платы."""
    import copy
    inputs = {**copy.deepcopy(core.DEFAULT_INPUTS), **OTHER, "land_rights_cost_mln": 100.0,
              "vri_payment_mode": "installment"}
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    text = json.dumps(result, ensure_ascii=False)
    assert "порядка платы за смену ВРИ этого региона у нас нет" in text
    vri = json.dumps({k: v for k, v in result.items() if "vri" in k.lower()}, ensure_ascii=False)
    assert '"relief_basis": "none"' in text or '"relief_basis":"none"' in text, vri[:400]


def test_no_parking_norm_for_another_region() -> None:
    tep = {"apartments": {"saleable": 30000.0, "gns": 46000.0, "units": 500},
           "offices": {"gns": 10000.0, "total_area": 9000.0}}
    assert core.underground_parking_requirement(OTHER, tep) is None
    demand = core.parking_demand(OTHER, tep)
    assert demand["required_total"] == 0 and demand["rows"] == [], demand
    assert any("этого региона у нас нет" in m for m in demand["missing"]), demand
    assert "у нас нет" in demand["norm_of"], demand


def test_no_social_norm_for_another_region() -> None:
    need = core.social_required_program(OTHER, {"apartments": {"saleable": 30000.0}})
    assert need["available"] is False, need
    assert "умолчаниями" in need["basis"], need


def test_residents_are_counted_by_an_assumption() -> None:
    """Владелец 19.10.2026: московские 33 м² на жителя — допущением, не нормой региона."""
    people, basis = core.project_population({"apartments": {"saleable": 3300.0}}, "other")
    assert people == 100
    assert "допущение" in basis and "2152-ПП" not in basis, basis


def test_nonresidential_price_has_no_moscow_floor() -> None:
    assert core.nonresidential_price_th(100.0, region="other") \
        == core.nonresidential_price_th(100.0, region="mo")
    assert core.nonresidential_price_th(100.0, region="other") \
        < core.nonresidential_price_th(100.0, region="msk")


# --- маршрут: участок другого региона не идёт в калькулятор ГлавАПУ -----------

def _no_calculator(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("участок другого региона ушёл в калькулятор ГлавАПУ")
    monkeypatch.setattr(core, "_glavapu_analysis_payload", refuse)
    monkeypatch.setattr(core, "_core_api_url", lambda *_a, **_k: "")


def test_the_territory_route_refuses_in_plain_words(monkeypatch) -> None:
    _no_calculator(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        core.analyze_cadastral_territory(
            core.CadastralAnalysisRequest(cadastral_numbers=EKATERINBURG))
    assert caught.value.status_code == 400
    assert "не в Москве и не в Московской области" in caught.value.detail
    assert "БД вернула" not in caught.value.detail


def test_the_server_tep_refuses_another_region(monkeypatch) -> None:
    _no_calculator(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        core.cadastral_tep_server(core.CadastralAnalysisRequest(cadastral_numbers=EKATERINBURG))
    assert "не в Москве" in caught.value.detail
    rows = [{"code": str(i), "name": f"строка {i}", "unit": "", "value": "1"} for i in range(40)]
    with pytest.raises(HTTPException) as caught:
        core.import_cadastral_tep(core.CadastralTepRequest(
            rows=rows, cadastral_analysis={"recognized": [EKATERINBURG]}))
    assert "не в Москве" in caught.value.detail


def test_the_bot_routes_another_region_apart() -> None:
    assert core.cadastral_route([EKATERINBURG], None) == "other"
    assert core.cadastral_route([EKATERINBURG], {"territory": {"inside_moscow": False}}) == "other"
    assert core.cadastral_route([EKATERINBURG, "77:01:0004621:72"], None) == "mixed"
    assert core.cadastral_route(["50:20:0010101:1"], None) == "mo"


# --- страница: то, что видит человек -----------------------------------------

PORT = 19841
PARCEL = {
    "found": True, "cadastral_number": EKATERINBURG, "kind": "land",
    "kind_label": "Земельный участок", "address": "Свердловская область, г. Екатеринбург",
    "area_sqm": 12000.0, "area_ha": 1.2, "category": "Земли населённых пунктов",
    "permitted_use": "Многоэтажная жилая застройка (высотная застройка)",
    "cadastral_value_rub": 150_000_000.0, "cadastral_value_mln": 150.0,
    "region": "Свердловская область", "center": None, "contour_merc": [],
    "source": "НСПД / ЕГРН",
}


@pytest.fixture(scope="module")
def page():
    import browser
    chrome = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import main_registry

    with browser.serve(main_registry.app, PORT) as origin:
        with sync_playwright() as pw:
            browser_ = pw.chromium.launch(executable_path=str(chrome))
            tab = browser_.new_page()
            asked: list[str] = []
            tab.route("**/cadastral/analyze", lambda route: (
                asked.append(route.request.url),
                route.fulfill(status=400, content_type="application/json",
                              body=json.dumps({"detail": "калькулятор не должен был отвечать"}))))
            tab.route("**/land/lookup", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"query": EKATERINBURG, "results": [PARCEL],
                                 "found_count": 1, "warnings": []}, ensure_ascii=False)))
            tab.route("**/land/screening", lambda route: route.fulfill(
                status=200, content_type="application/json", body="{}"))
            tab.goto(origin + "/", wait_until="domcontentloaded")
            browser.wait_for_result(tab)
            tab.asked = asked
            yield tab
            browser_.close()


def test_the_page_takes_another_region_to_its_own_mode(page) -> None:
    import browser
    page.evaluate("""()=>{
      inputs.land_rights_cost_mln=2864.3; inputs.kindergarten_places=7;
      document.getElementById('cadastralNumbers').value=%s;
    }""" % json.dumps(EKATERINBURG))
    page.evaluate("()=>obtainTep()")
    page.wait_for_function(
        "()=>document.querySelector('#cadastralStatus button')", timeout=20_000)
    status = page.inner_text("#cadastralStatus")
    assert page.asked == [], "участок другого региона ушёл в калькулятор ГлавАПУ"
    assert "Свердловская область" in status and "1,2" in status, status
    assert "Норм этого региона у нас нет" in status, status
    assert "допущение" in status, status

    page.evaluate("()=>applyOtherRegion()")
    page.wait_for_function(
        "()=>/Участок подставлен/.test(document.getElementById('cadastralStatus').textContent)",
        timeout=20_000)
    browser.wait_for_result(page)
    got = page.evaluate("""()=>({region:inputs.vri_region, classRegion:classRegion(),
        area:Number(inputs.site_area_ha), flats:Number(tep.apartments.saleable),
        fee:Number(inputs.land_rights_cost_mln||0), dou:Number(inputs.kindergarten_places||0),
        note:(document.getElementById('otherRegionNote')||{}).textContent||'',
        noteShown:(document.getElementById('otherRegionNote')||{style:{}}).style.display!=='none',
        hint:tepNormsMode().text, density:siteDensitySourceLabel()})""")
    assert got["region"] == "other" and got["classRegion"] == "other", got
    assert got["area"] == pytest.approx(1.2), got
    assert got["flats"] == pytest.approx(1.2 * 30000, rel=1e-3), got
    # Решение владельца 19.10.2026: плата за ВРИ — ноль, остальное — наши
    # умолчания, которые человек правит сам.
    assert got["fee"] == 0, got
    assert got["dou"] == page.evaluate("()=>Number(INPUT_DEFAULT.kindergarten_places||0)"), got
    assert got["noteShown"] and "норм его региона у нас нет" in got["note"], got
    assert "нормативам Москвы" not in got["hint"], got
    assert "допущение" in got["density"], got


def test_the_progress_bar_does_not_repeat_the_refusal(page) -> None:
    """Отказ стоит в строке состояния один раз, без слипшейся копии под ней."""
    text = page.evaluate("""()=>new Promise(done=>{
      const s=document.getElementById('cadastralStatus');
      s.innerHTML='<span class="import-error">Первая фраза.</span><br><span>Вторая фраза.</span>';
      setTimeout(()=>done((document.getElementById('tepProgressText')||{}).textContent||''),60);
    })""")
    assert "Первая фраза" not in text and "фраза.Вторая" not in text, text
    assert "остановлен" in text, text
