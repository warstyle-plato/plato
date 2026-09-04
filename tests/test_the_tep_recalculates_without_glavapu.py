"""Правка ТЭП пересчитывает то, что можно посчитать, и называет остальное.

«При изменении ТЭПов не изменяется ВРИ и соц платеж, потребность в
обеспеченности местами… НО только если есть расчёт ГлавАПУ; если считаем своими
допущениями или формулами для МО — ничего не происходит. Пишется ошибка и
упоминание про отсутствие расчёта ГлавАПУ» (владелец, 29.08.2026).

При этом расчёт своими формулами был написан и не звался никем: маршрут
`/tep/derived` в репозитории вызывал только тест.

Чинится не подменой: расчёт по снятым ставкам выгрузки и расчёт по нормативам —
разные вещи, и подписывать их одинаково нельзя. Поэтому каждое число подписано
основанием, а каждое непосчитанное — причиной: молча выданный ноль неотличим от
посчитанного нуля.

Запуск: python3 -m pytest tests/test_the_tep_recalculates_without_glavapu.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = (ROOT / "main_legacy.py").read_text(encoding="utf-8")

SITE = {"apartment_area_sqm": 80_000, "residential_living_spp_sqm": 130_716,
        "nonresidential_np_sqm": 8_695}


@pytest.fixture
def client() -> TestClient:
    return TestClient(core.app)


def test_what_can_be_counted_is_counted(client) -> None:
    got = client.post("/tep/derived-by-site", json={**SITE, "district": "Хамовники"}).json()
    assert got["population"] == 2425
    assert got["places"] == {"kindergarten": 107, "school": 219, "clinic": 47}
    # Постоянным и гостевым местам коэффициенты района не нужны: постоянные
    # считаются от площади квартир, гостевые — десятая часть от них.
    assert got["parking"]["permanent"] == 924 and got["parking"]["guest"] == 93
    assert got["parking"]["underground"] == 1017
    assert got["jobs"] == 242


def test_the_zone_comes_from_the_district_and_changes_the_norms(client) -> None:
    """Во второй зоне ДОО 63 и школа 124 места на тысячу вместо 44 и 90."""
    first = client.post("/tep/derived-by-site", json={**SITE, "district": "Хамовники"}).json()
    second = client.post("/tep/derived-by-site", json={**SITE, "district": "Некрасовка"}).json()
    assert first["zone_two"] is False and second["zone_two"] is True
    assert second["places"]["kindergarten"] > first["places"]["kindergarten"]
    assert second["places"]["school"] > first["places"]["school"]
    assert "зона 2 по району «Некрасовка»" in "; ".join(second["basis"])


def test_an_unknown_district_is_said_out_loud(client) -> None:
    """Неизвестный район и район первой зоны дают разные нормативы, а на экране
    выглядят одинаково."""
    got = client.post("/tep/derived-by-site", json=SITE).json()
    assert got["zone_two"] is False
    assert any("Район участка не определён" in line for line in got["warnings"])


def test_what_cannot_be_counted_is_named_not_zeroed(client) -> None:
    got = client.post("/tep/derived-by-site", json={**SITE, "district": "Хамовники"}).json()
    refused = {item["name"]: item["reason"] for item in got["refused"]}
    assert "Приобъектные машино-места" in refused
    assert "К2" in refused["Приобъектные машино-места"], \
        "своего справочника районов не заводим — так и сказано"
    assert "Денежная соцкомпенсация" in refused and "УПКС" in refused["Денежная соцкомпенсация"]
    assert "Плата за смену ВРИ" in refused
    # Ни одного посчитанного нуля вместо отказа.
    assert "compensation_mln" not in got and "parking_onsite" not in got


def test_outside_moscow_it_refuses_with_a_reason(client) -> None:
    """Для области нормативов Москвы нет вовсе — это отказ, а не тишина."""
    answer = client.post("/tep/derived-by-site",
                         json={**SITE, "inside_moscow": False})
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert "вне Москвы" in detail and "области" in detail


def test_the_answer_says_whose_calculation_it_is(client) -> None:
    """Расчёт по снятым ставкам выгрузки и расчёт по нормативам — разные вещи."""
    got = client.post("/tep/derived-by-site", json={**SITE, "district": "Хамовники"}).json()
    assert "без выгрузки ГлавАПУ" in got["source"]
    assert any("945-ПП" in line for line in got["basis"]), "норматив назван приказом"


def test_the_arithmetic_is_not_written_a_second_time() -> None:
    """Оба пути зовут одну функцию: второй счёт тех же метров разошёлся бы."""
    body = PAGE[PAGE.index("def tep_derived_by_site("):]
    body = body[: body.index("\n@app.post")]
    assert "tep_derived_norms(" in body
    for sign in ("math.ceil", "/ 33.0", "* 0.8"):
        assert sign not in body, f"в обёртке появилась своя арифметика: {sign}"


def test_the_zone_list_is_declared_once() -> None:
    """Две копии списка районов дали бы на один участок два норматива."""
    assert PAGE.count('"некрасовка"') == 1, "список районов второй зоны размножился"
    assert "MOSCOW_ZONE_TWO_DISTRICTS" in PAGE
    assert "def district_zone_two(" in PAGE


def test_the_page_calls_the_norms_instead_of_refusing() -> None:
    start = PAGE.index("async function recalcFromTep(options){")
    head = PAGE[start:start + 900]
    assert "recalcFromTepByNorms(options)" in head
    assert "Нет исходного расчёта ГлавАПУ: пересчитывать не от чего" not in head

    body = PAGE[PAGE.index("async function recalcFromTepByNorms(options){"):]
    body = body[: body.index("\nasync function recalcFromTep(options){")]
    assert "'/tep/derived-by-site'" in body
    assert "Не посчитано — " in body, "отказ виден рядом с числами"
    assert "Чем посчитано:" in body, "основание названо"
    assert "его выгрузка сильнее" in body, "город считает сам, и это сказано"
    # Экран не считает: ни долей, ни делений.
    for sign in ("/33", "/ 33", "*0.8", "Math.ceil"):
        assert sign not in body, f"на экране появилась арифметика: {sign}"


def test_the_page_really_fills_the_fields(tmp_path) -> None:
    """Проверяется настоящим браузером на собранной странице: сервер отвечает
    тем же кодом, что в бою, но без сети — запрос перехватывается и
    обслуживаетсяTestClient'ом."""
    play = pytest.importorskip("playwright.sync_api")
    import json

    import browser_launch

    from main_registry import app as registry_app

    served = TestClient(registry_app)
    page_file = tmp_path / "classic.html"
    page_file.write_text(served.get("/classic").text, encoding="utf-8")

    def answer(route):
        request = route.request
        if request.url.endswith("/tep/derived-by-site"):
            reply = served.post("/tep/derived-by-site", json=json.loads(request.post_data))
            route.fulfill(status=reply.status_code, content_type="application/json",
                          body=reply.text)
            return
        route.abort() if request.url.startswith("http") else route.continue_()

    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.route("**/*", answer)
            tab.goto(page_file.resolve().as_uri())
            tab.wait_for_timeout(600)
            got = tab.evaluate("""async ()=>{
              cadastralAnalysis={territory:{district:'Некрасовка', inside_moscow:true}};
              tep.apartments.saleable=80000; tep.apartments.gns=130716;
              tep.apartments.units=1361;
              tep.ground_commercial.total_area=8695;
              inputs.kindergarten_places=0; inputs.school_places=0;
              inputs.clinic_capacity=0; inputs.underground_manual_spaces=0;
              await recalcFromTep({silent:true});
              const note=document.getElementById('tepDerivedNote');
              return {dou:inputs.kindergarten_places, school:inputs.school_places,
                      clinic:inputs.clinic_capacity,
                      parking:inputs.underground_manual_spaces,
                      note:(note&&note.textContent)||''};
            }""")
        finally:
            browser.close()

    # «Failed to fetch» — это оборванные нами же посторонние запросы страницы
    # (карта, справочники): в тесте сети нет намеренно. Всё прочее — поломка.
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert (got["dou"], got["school"], got["clinic"]) == (153, 301, 47), \
        "нормативы второй зоны не доехали до вводных"
    # Постоянные места — пунктом 2 по средней квартире (80 000 / 1 361 = 58,8 м²,
    # полоса до 70 × 0,8), гостевые десятой частью: то же, что считает движок.
    permanent, _ = core.moscow_permanent_parking_by_average(80000, 1361)
    assert permanent == 1089
    assert got["parking"] == permanent + math.ceil(permanent / 10.0) == 1198
    assert "Не посчитано" in got["note"] and "Чем посчитано" in got["note"]
