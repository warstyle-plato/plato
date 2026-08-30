"""Соцнагрузка масштабируется пропорцией, а не отказывается считаться.

«Почему нельзя брать пропорцию? В Подмосковье можно же пропорционально
снижать? Количество мест зависит от количества людей, а количество людей — от
количества жилых площадей. Себестоимости места у нас вбиты экспертно»
(владелец, 30.08.2026).

Он прав, и мой прежний отказ был перестраховкой. Норматив линеен по населению,
население линейно по площади квартир, ставка за место задана экспертно и от
метража не зависит — значит при правке ТЭП соцнагрузка масштабируется. И это
верно в любом регионе, потому что норматив здесь не применяется вовсе:
масштабируется то, что УЖЕ посчитано городом или введено человеком.

Граница ответа отсюда же: масштабировать нечего — это отказ, а не ноль. Пустая
соцнагрузка и уменьшенная до нуля значат разное.

Запуск: python3 -m pytest tests/test_the_social_load_scales_with_the_tep.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = (ROOT / "main_legacy.py").read_text(encoding="utf-8")

LOADED = {"apartment_area_before_sqm": 80_000, "apartment_area_after_sqm": 40_000,
          "kindergarten_places": 107, "school_places": 219, "clinic_capacity": 47,
          "social_compensation_mln": 1140.1, "underground_manual_spaces": 1017,
          "basis": "выгрузка ГлавАПУ"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(core.app)


def test_halving_the_flats_halves_the_places(client) -> None:
    got = client.post("/tep/rescale-social", json=LOADED).json()
    assert got["factor"] == 0.5
    assert got["places"] == {"kindergarten": 54, "school": 110, "clinic": 24}
    assert got["compensation_mln"] == 570.05
    assert got["underground_manual_spaces"] == 509


def test_places_round_up_because_half_a_place_is_not_built(client) -> None:
    got = client.post("/tep/rescale-social", json={
        **LOADED, "apartment_area_after_sqm": 60_000}).json()
    assert got["factor"] == 0.75
    # 107 × 0,75 = 80,25 → 81; 219 × 0,75 = 164,25 → 165.
    assert got["places"]["kindergarten"] == 81 and got["places"]["school"] == 165


def test_growth_scales_the_same_way(client) -> None:
    """Норматив линеен в обе стороны — правка вверх считается так же."""
    got = client.post("/tep/rescale-social", json={
        **LOADED, "apartment_area_after_sqm": 160_000}).json()
    assert got["factor"] == 2.0
    assert got["places"]["kindergarten"] == 214


def test_nothing_to_scale_is_a_refusal_not_a_zero(client) -> None:
    empty = client.post("/tep/rescale-social", json={
        "apartment_area_before_sqm": 80_000, "apartment_area_after_sqm": 40_000})
    assert empty.status_code == 422
    assert "Масштабировать нечего" in empty.json()["detail"]

    blind = client.post("/tep/rescale-social", json={
        "apartment_area_after_sqm": 40_000, "kindergarten_places": 107})
    assert blind.status_code == 422
    assert "неизвестна площадь квартир" in blind.json()["detail"]


def test_the_basis_says_it_is_a_proportion_and_from_what(client) -> None:
    basis = "; ".join(client.post("/tep/rescale-social", json=LOADED).json()["basis"])
    assert "пропорция по населению" in basis
    assert "80 000 → 40 000" in basis and "0,5000" in basis
    assert "выгрузка ГлавАПУ" in basis, "чьи были прежние числа — часть ответа"
    assert "ставка за место задана экспертно" in basis


def test_a_changed_commercial_area_is_named_not_scaled(client) -> None:
    """Приобъектные места считаются от нежилой своим коэффициентом района —
    пропорция по населению их не трогает, и об этом надо сказать."""
    got = client.post("/tep/rescale-social", json={
        **LOADED, "nonresidential_before_sqm": 8_695,
        "nonresidential_after_sqm": 4_000}).json()
    assert any("приобъектные" in line.lower() for line in got["warnings"])


def test_the_page_tries_the_proportion_before_the_norms() -> None:
    start = PAGE.index("async function recalcFromTep(options){")
    head = PAGE[start:start + 1200]
    assert "await rescaleSocialFromTep(options)" in head
    assert head.index("rescaleSocialFromTep") < head.index("recalcFromTepByNorms"), \
        "норматив считается, только когда масштабировать нечего"

    body = PAGE[PAGE.index("async function rescaleSocialFromTep(options){"):]
    body = body[: body.index("\nasync function recalcFromTepByNorms(")]
    assert "'/tep/rescale-social'" in body
    assert "Пересчитано пропорцией" in body
    # Экран не считает: коэффициент и числа приходят с сервера.
    for sign in ("after/before", "Math.ceil", "/33"):
        assert sign not in body, f"на экране появилась арифметика: {sign}"


def test_the_basis_is_stamped_where_the_numbers_appear() -> None:
    """Без отметки пропорцию считать не от чего, а угадывать площадь по числу
    мест значило бы обратить норматив, которого в Подмосковье нет."""
    assert "function stampSocialBasis(" in PAGE
    assert "SOCIAL_SCALED_KEYS.includes(id))stampSocialBasis('введены руками')" in PAGE
    assert "stampSocialBasis('выгрузка ГлавАПУ')" in PAGE
    assert "stampSocialBasis('нормативы Москвы')" in PAGE


def test_the_proportion_works_outside_moscow(tmp_path) -> None:
    """Главный случай владельца: Подмосковье, где нормативов Москвы нет."""
    play = pytest.importorskip("playwright.sync_api")
    import browser_launch

    from main_registry import app as registry_app

    served = TestClient(registry_app)
    page_file = tmp_path / "classic.html"
    page_file.write_text(served.get("/classic").text, encoding="utf-8")

    def answer(route):
        request = route.request
        for path in ("/tep/rescale-social", "/tep/derived-by-site"):
            if request.url.endswith(path):
                reply = served.post(path, json=json.loads(request.post_data))
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
              cadastralAnalysis={territory:{district:'Одинцово', inside_moscow:false}};
              tep.apartments.saleable=80000; tep.apartments.gns=130716;
              inputs.kindergarten_places=107; inputs.school_places=219;
              inputs.clinic_capacity=47; inputs.social_compensation_mln=1140.1;
              inputs.underground_manual_spaces=1017;
              stampSocialBasis('введены руками');
              tep.apartments.saleable=40000;
              await recalcFromTep({silent:true});
              const note=document.getElementById('tepDerivedNote');
              return {dou:inputs.kindergarten_places, school:inputs.school_places,
                      clinic:inputs.clinic_capacity, comp:inputs.social_compensation_mln,
                      park:inputs.underground_manual_spaces,
                      note:(note&&note.textContent)||''};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert (got["dou"], got["school"], got["clinic"]) == (54, 110, 24)
    assert got["comp"] == 570.05 and got["park"] == 509
    assert "Пересчитано пропорцией" in got["note"]
