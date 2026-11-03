"""«Настройки классов»: четыре правила владельца от 28.09.2026.

Проверка логики окна классов нашла четыре расхождения, и по каждому владелец
ответил:

1. **У нежилого своя цена.** Строки «Стартовая цена — ТЦ / ОСЗ» и «— МФОЦ /
   офисы» обещали «считается от цены квартир», а за ценой квартир не шли.
   Решение — своя цена, не следует; обещание снято (проверка —
   `test_the_class_keeps_what_was_typed.py`).
2. **В МО без московского пола.** Правило цены нежилого знает регион (пол
   450 тыс ₽/м² — московский), но профиль класса один, и проект в области
   получал ОСЗ по 450 при квартирах по 350. База класса для региона —
   `class_base_preset`; её читают сверка отклонений и страница.
3. **Правка колонки текущего класса сразу идёт в проект.** Прежде число ждало
   повторного выбора класса, а окно писало «всё соответствует». Поле проекта
   идёт за классом, только пока в нём число класса: вписанное руками или
   пришедшее импортом остаётся своим.
4. **Свод «Статистики» — по региону проекта и на его площадях.** Он всегда
   спрашивался по Москве и один раз за жизнь страницы.

Проверяется отрисованная страница в Chromium и сверка движка.

Запуск: python3 -m pytest tests/test_class_settings_follow_the_owner_rules.py -q
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

PORT = 18975


# --- движок: база класса для региона -----------------------------------------------

def test_the_region_base_drops_the_moscow_floor_only_in_the_region() -> None:
    msk = core.class_base_preset("comfort", "msk")
    mo = core.class_base_preset("comfort", "mo")
    assert msk["retail_price_th_per_sqm"] == core.MOSCOW_NONRES_PRICE_FLOOR_TH
    for field in core.CLASS_NONRES_PRICE_FIELDS:
        assert mo[field] == mo["apartment_price_th"], field
    # Дорогие классы пол не трогал — у них база одна в обоих регионах.
    assert core.class_base_preset("elite", "mo") == core.class_base_preset("elite", "msk")


def test_the_deviation_is_measured_from_the_region_base() -> None:
    mo = dict(core.DEFAULT_INPUTS, project_class="comfort", vri_region="mo",
              **{f: 350.0 for f in core.CLASS_NONRES_PRICE_FIELDS})
    assert core.project_class_deviations(mo)["rows"] == []
    moscow_in_mo = dict(mo, retail_price_th_per_sqm=450.0)
    fields = [r["field"] for r in core.project_class_deviations(moscow_in_mo)["rows"]]
    assert fields == ["retail_price_th_per_sqm"]


# --- страница ------------------------------------------------------------------------

SCENARIO = r"""async () => {
  const out = {};
  const typed = (id, value) => {
    const el = document.getElementById('f_' + id);
    el.value = String(value); el.dispatchEvent(new Event('change'));
  };
  const urls = [];
  const realFetch = window.fetch;
  window.fetch = (u, o) => { if (String(u).includes('cost-recommendation')) urls.push(String(u)); return realFetch(u, o); };
  const settle = () => new Promise(r => setTimeout(r, 400));

  applyProjectClassPreset('comfort');
  out.mskRetail = inputs.retail_price_th_per_sqm;

  // 2. Регион → МО: цена нежилого идёт за базой области.
  typed('vri_region', 'mo'); await settle();
  out.moRetail = inputs.retail_price_th_per_sqm;
  out.moOffices = inputs.offices_price_th_per_sqm;
  openClassDialog(); await settle(); await settle();
  out.moNote = document.getElementById('classDialogNote').innerText;
  out.moStatsUrls = urls.splice(0);

  // 4. Смена ТЭП — окно спрашивает свод заново.
  tep.apartments = Object.assign({}, tep.apartments, {gns: Number((tep.apartments || {}).gns || 0) + 10000});
  closeClassDialog(); openClassDialog(); await settle(); await settle();
  out.statsAfterTep = urls.splice(0).length;

  // Цена, пришедшая импортом, регион не переживает молча — она своя.
  inputs.retail_price_th_per_sqm = 520;
  typed('vri_region', 'msk'); await settle();
  out.importedAfterRegion = inputs.retail_price_th_per_sqm;
  out.officesBackInMoscow = inputs.offices_price_th_per_sqm;

  // 3. Колонка текущего класса — сразу в проект; чужого — нет.
  await setClassBase('comfort', 'main_above_th_per_sqm', 125);
  out.currentClassEdit = inputs.main_above_th_per_sqm;
  await setClassBase('business', 'main_under_th_per_sqm', 170);
  out.otherClassEdit = inputs.main_under_th_per_sqm;
  // Вписанное руками правка класса не трогает.
  typed('apartment_price_th', 410); await settle();
  await setClassBase('comfort', 'apartment_price_th', 500);
  out.manualKept = inputs.apartment_price_th;
  return out;
}"""


@pytest.fixture(scope="module")
def seen() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda d: d.accept())
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelectorAll('details[data-group]').length>3",
                                   timeout=20000)
            got = page.evaluate(SCENARIO)
            page.close()
    got["errors"] = errors
    return got


def test_the_page_runs_the_scenario(seen) -> None:
    assert seen["errors"] == [], seen["errors"]


def test_the_region_moves_the_nonresidential_base(seen) -> None:
    assert seen["mskRetail"] == core.MOSCOW_NONRES_PRICE_FLOOR_TH
    assert seen["moRetail"] == core.PROJECT_CLASS_PRESETS["comfort"]["apartment_price_th"]
    assert seen["moOffices"] == seen["moRetail"]
    assert "Все значения соответствуют базе" in seen["moNote"], seen["moNote"]
    assert seen["officesBackInMoscow"] == core.MOSCOW_NONRES_PRICE_FLOOR_TH


def test_an_imported_price_survives_the_region_switch(seen) -> None:
    assert seen["importedAfterRegion"] == 520


def test_the_current_class_column_reaches_the_project(seen) -> None:
    assert seen["currentClassEdit"] == 125
    assert seen["otherClassEdit"] == core.PROJECT_CLASS_PRESETS["comfort"]["main_under_th_per_sqm"]
    assert seen["manualKept"] == 410


def test_the_statistics_follow_the_region_and_the_tep(seen) -> None:
    assert seen["moStatsUrls"], "свод в МО не запрашивался"
    assert all("%D0%9C%D0%BE%D1%81%D0%BA%D0%BE%D0%B2%D1%81%D0%BA%D0%B0%D1%8F" in u
               or "Московская" in u for u in seen["moStatsUrls"]), seen["moStatsUrls"]
    assert seen["statsAfterTep"] > 0, "после смены ТЭП свод не спрошен заново"
