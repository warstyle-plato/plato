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
