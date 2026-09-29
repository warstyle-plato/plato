"""Окно «Настройки классов» показывает строки только объектов проекта.

Владелец (29.09.2026): в окне стояли «Стартовая цена — МФОЦ / офисы 2…5» и
«ТЦ / коммерция ОСЗ 2…5» при проекте, где этих объектов нет: «зачем они в
настройках, если они не добавлены вообще в проект?». Состав решает тот же
предикат, что у расчёта и формы (`objectInProject` ← `object_instances`).
Добавили объект — его строки появились; удалили — ушли, а вписанное руками
не потерялось. Себестоимости ТЦ в профиле класса нет: у ТЦ она одним числом
во вводных объекта (решение владельца).

Проверяется отрисованное окно — Chromium на живой странице.

Запуск: python3 -m pytest tests/test_the_class_dialog_shows_only_project_objects.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18977

SCENARIO = """() => {
  const out = {};
  const rows = () => { renderClassDialog();
    return Array.from(document.querySelectorAll('#classDialogBody tr td:first-child'))
      .map(td => td.textContent); };
  delete inputs.object_instances;
  out.empty = rows();
  addObjectInstance('offices');
  out.office2 = rows();
  // Вписанное руками у второго офиса переживает удаление и смену класса.
  inputs.offices2_price_th_per_sqm = 777; markClassManual('offices2_price_th_per_sqm');
  removeObjectInstance('offices2');
  out.removed = rows();
  window.confirm = () => true;
  applyProjectClassPreset(inputs.project_class === 'business' ? 'comfort' : 'business');
  out.kept = Number(inputs.offices2_price_th_per_sqm);
  return out;
}"""


@pytest.fixture(scope="module")
def dialog():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.evaluate("localStorage.removeItem('plato_v04')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.evaluate("openClassDialog()")
            got = page.evaluate(SCENARIO)
            page.close()
    got["errors"] = errors
    return got


def _instance_rows(rows: list[str]) -> list[str]:
    names = [obj.group_label for obj in core.OBJECT_INSTANCES.values()]
    return [row for row in rows if any(name in row for name in names)]


def test_a_project_without_instances_shows_no_instance_rows(dialog) -> None:
    assert dialog["errors"] == [], dialog["errors"]
    assert dialog["empty"], "окно классов пустое — мерить нечего"
    # Первый объект типа — на месте, как раньше.
    assert any("МФОЦ / офисы" in row for row in dialog["empty"]), dialog["empty"]
    assert _instance_rows(dialog["empty"]) == [], _instance_rows(dialog["empty"])


def test_an_added_office_brings_its_own_rows_only(dialog) -> None:
    rows = _instance_rows(dialog["office2"])
    assert rows and all("МФОЦ / офисы 2" in row for row in rows), rows
    # Цена и себестоимость — у офиса по шкале класса.
    assert len(rows) == 2, rows


def test_a_removed_office_leaves_the_dialog_and_keeps_its_number(dialog) -> None:
    assert _instance_rows(dialog["removed"]) == [], _instance_rows(dialog["removed"])
    assert dialog["kept"] == 777


def test_the_retail_cost_has_no_class_scale() -> None:
    """У ТЦ себестоимость одним числом во вводных — без шкалы класса."""
    for preset in core.PROJECT_CLASS_PRESETS.values():
        for obj in core.STANDALONE_OBJECTS:
            if obj.product == "standalone_retail":
                assert obj.rate_cost not in preset, obj.rate_cost
        assert "offices_cost_th_per_sqm" in preset
