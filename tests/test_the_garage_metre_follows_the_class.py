"""Площадь на машино-место — классовая величина, а не общая вводная.

Решение владельца, 13.09.2026: «35 37,5 40». Место у комфорта 2,5 м в ширину,
у бизнеса и элитки 2,7–3,0 — шире место, шире проезд, и гросс на место растёт
вместе с ними.

Поле стоит в профиле класса, а список полей окна настроек — САМ пресет
(`Object.keys(p).filter(k=>k!=='label')`), поэтому строка, перекрышка и
отклонение в PDF появляются сами. Проверять надо не это, а то, ради чего поле
заводилось: что число ДОЕЗЖАЕТ до строки ТЭП и до денег. До 0.23.48 не
доезжало — движок читал норматив только в ручной ветке и в выгрузке.

Запуск: python3 -m pytest tests/test_the_garage_metre_follows_the_class.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

FIELD = "underground_area_per_space_sqm"
OWNER_SCALE = {"comfort": 35.0, "business": 37.5, "elite": 40.0}


def test_the_owner_scale_stands_in_the_presets() -> None:
    """Три числа владельца — в профиле, а не во вводных проекта."""
    got = {key: float(preset[FIELD])
           for key, preset in core.PROJECT_CLASS_PRESETS.items()}
    assert got == OWNER_SCALE


def test_the_scale_is_softer_than_the_yard() -> None:
    """Шкала гаража мягче шкалы двора, и это утверждение, а не совпадение.

    Ширину места ограничивает машина, а не кошелёк: у двора элитка отличается
    от комфорта вчетверо, у гаража — на седьмую часть. Сравниваются ОТНОШЕНИЯ,
    иначе проверка держала бы числа и падала бы на любой их правке.
    """
    presets = core.PROJECT_CLASS_PRESETS
    garage = presets["elite"][FIELD] / presets["comfort"][FIELD]
    yard = (presets["elite"]["landscaping_area_per_person_sqm"]
            / presets["comfort"]["landscaping_area_per_person_sqm"])
    assert 1.0 < garage < yard, (garage, yard)


def test_the_dialog_names_the_unit_of_the_new_row() -> None:
    """Физическое число рядом с тысячами рублей обязано назвать свою меру."""
    assert core.class_field_units().get(FIELD) == "м²/место"


@pytest.mark.parametrize("project_class", sorted(OWNER_SCALE))
def test_the_class_reaches_the_row_and_the_money(project_class: str) -> None:
    """Выбранный класс двигает подземную площадь и стоимость.

    Считается ровно то, что обещает поле: площадь = места × норматив класса.
    Предохранитель — комфорт и элит обязаны разойтись, иначе проверка зелена
    на коде, который норматив не читает вовсе.
    """
    def run(key: str) -> tuple[float, float, float]:
        inputs = copy.deepcopy(core.DEFAULT_INPUTS)
        inputs.update({field: value
                       for field, value in core.PROJECT_CLASS_PRESETS[key].items()
                       if field != "label"})
        inputs["project_class"] = key
        result = core.calculate(core.CalcRequest(
            inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rows=[]))
        row = next(item for item in result["tep"]["rows"]
                   if item["key"] == "underground_parking")
        return row["units"], row["gns"], result["summary"]["construction_volume_sqm"]

    units, gns, volume = run(project_class)
    assert gns == pytest.approx(units * OWNER_SCALE[project_class], abs=0.2)
    comfort_units, comfort_gns, comfort_volume = run("comfort")
    if project_class == "comfort":
        return
    # Мест столько же — расходится именно площадь на место.
    assert units == pytest.approx(comfort_units)
    assert gns > comfort_gns
    assert volume - comfort_volume == pytest.approx(gns - comfort_gns, abs=0.2)


def _switch_class_in_browser(manual_area: float | None, to: str) -> dict:
    """Переключить класс на живой странице и вернуть состояние пары.

    Проверяет это браузер, а не стенд: `applyProjectClassPreset` пишет поля
    напрямую, и «поле записано» в исходнике выглядит одинаково у верного кода
    и у сломанного — видно только то, что стало с производными.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    chromium = browser.chromium_or_skip()
    with browser.serve(core.app, 8411) as base:
        with sync_playwright() as play:
            engine = play.chromium.launch(executable_path=str(chromium))
            page = engine.new_page()
            page.goto(base, wait_until="load")
            page.wait_for_function("typeof applyProjectClassPreset==='function'")
            page.wait_for_timeout(2000)
            state = page.evaluate(
                """([manual, to]) => {
                  inputs.underground_manual_spaces = 3194;
                  syncUndergroundPair('underground_manual_spaces');
                  if (manual !== null) { inputs.underground_manual_gns_sqm = manual; }
                  syncTep(false); renderTep();
                  const was = Number(inputs.underground_manual_gns_sqm || 0);
                  applyProjectClassPreset(to);
                  const note = [...document.querySelectorAll('#tepBody tr')]
                    .map(t => t.innerText).find(t => /Подземный паркинг/.test(t)) || '';
                  return {was, per: inputs.underground_area_per_space_sqm,
                          spaces: inputs.underground_manual_spaces,
                          area: inputs.underground_manual_gns_sqm, note};
                }""", [manual_area, to])
            engine.close()
    return state


def test_the_class_moves_the_area_it_had_produced() -> None:
    """Смена класса двигает площадь, которую сама же и посчитала.

    Поля профиля писались напрямую, мимо всех пересчётов: класс менял
    норматив 35 → 37,5, а площадь паркинга оставалась прежней — «ничего не
    меняется в блоке машиномест» (владелец, 14.09.2026).
    """
    state = _switch_class_in_browser(None, "business")
    assert state["per"] == OWNER_SCALE["business"]
    assert state["was"] == pytest.approx(3194 * OWNER_SCALE["comfort"], abs=1)
    assert state["area"] == pytest.approx(3194 * OWNER_SCALE["business"], abs=1)


def test_a_hand_written_area_survives_the_class() -> None:
    """А вписанное руками пятно застройки смену класса переживает.

    Признак измеримый: площадь, полученная нормативом, равна «места ×
    норматив»; вписанная ему не равна. И расхождение НАЗЫВАЕТСЯ — два числа
    об одной величине, стоящие молча, читаются как одно.
    """
    state = _switch_class_in_browser(100000, "elite")
    assert state["per"] == OWNER_SCALE["elite"]
    assert state["area"] == pytest.approx(100000)
    assert "31,3 м²/место" in state["note"], state["note"]
    assert "Норматив класса — 40 м²/место" in state["note"], state["note"]
