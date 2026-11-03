"""Три числа продукта в очереди связаны, а не живут порознь.

«Тут тоже ячейки не зависят друг от друга. Меняешь ГНС — не меняется общая и
обратно» (владелец, 03.09.2026). В таблице ТЭП любое из трёх чисел ведущее, а
два других достраиваются пропорциями (решение владельца 19.08.2026); в таблице
реальных ТЭП очередей связи не было вовсе: правка ГНС оставляла продаваемую
прежней, и строка переставала сходиться сама с собой — при том что «Итого по
очередям» рядом честно сравнивается с проектом и краснеет.

Штука (`units`) — счётчик, пропорцией не считается: у паркинга это места, и
выводить их из метров значило бы завести четвёртый делитель числа мест.

Запуск: python3 -m pytest tests/test_the_phase_tep_cells_follow_each_other.py -q
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def got(core, tmp_path_factory):
    playwright = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page = tmp_path_factory.mktemp("page") / "page.html"
    page.write_text(core.PAGE.replace("__DEVELOPAID_VERSION__", "test"), encoding="utf-8")
    with playwright.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(page.as_uri())
            tab.wait_for_function("() => typeof setPhaseProductTep === 'function'", timeout=15000)
            out = tab.evaluate("""() => {
              phasing.enabled = true;
              phasing.phase_count = 2;
              while (phasing.phases.length < 2)
                phasing.phases.push({name: 'О' + (phasing.phases.length + 1),
                                     start_offset_months: 12, construction_months: 24,
                                     products: {}});
              phasing.phases.forEach(p => { p.products = {}; });
              // Доли снимаем: с ними последняя очередь — автоматический остаток.
              phasing.products = {};
              const ratio = tepRatio('apartments');
              // Ведущая ГНС: продаваемая обязана пойти за ней.
              setPhaseProductTep(0, 'apartments', 'gns', '40000');
              const byGns = {...(phasing.phases[0].products.apartments || {})};
              // Ведущая продаваемая: теперь наоборот.
              setPhaseProductTep(0, 'apartments', 'saleable', '20000');
              const bySaleable = {...(phasing.phases[0].products.apartments || {})};
              // Штука остаётся тем, что вписали: это счётчик, а не метры.
              setPhaseProductTep(1, 'apartments', 'units', '300');
              const units = {...(phasing.phases[1].products.apartments || {})};
              return {byGns, bySaleable, units, ratio};
            }""")
            tab.close()
        finally:
            browser.close()
    assert [item for item in errors if "Failed to fetch" not in item] == [], errors
    return out


def test_the_saleable_follows_the_gns(got):
    """Вписали ГНС — продаваемая посчиталась той же пропорцией, что в ТЭП."""
    chain = got["ratio"]
    expected = 40000 * float(chain["saleable_of_gns"])
    assert got["byGns"]["gns"] == pytest.approx(40000, abs=1)
    assert got["byGns"]["saleable"] == pytest.approx(expected, rel=0.001), got["byGns"]


def test_the_gns_follows_the_saleable(got):
    """И обратно: любое из двух — ведущее, как в таблице ТЭП."""
    chain = got["ratio"]
    expected = 20000 / float(chain["saleable_of_gns"])
    assert got["bySaleable"]["saleable"] == pytest.approx(20000, abs=1)
    assert got["bySaleable"]["gns"] == pytest.approx(expected, rel=0.001), got["bySaleable"]


def test_the_count_is_not_derived_from_metres(got):
    """Число квартир площадью не пересчитывается нигде — и здесь тоже.

    Само число может быть обрезано остатком проекта — это прежняя и верная
    защита; проверяется другое: правка счётчика не дописала метры.
    """
    assert "units" in got["units"], got["units"]
    assert "gns" not in got["units"], got["units"]
    assert "saleable" not in got["units"], got["units"]
