"""Норматив площади двора правится в настройках класса, а не во «Вводных».

Решение владельца, 14.09.2026: «убрать ли поле „норматив м²/чел" из
„Вводных", оставив его только в настройках класса» — «Да». Норматив
(11/15/20 м²/чел.) — свойство КЛАССА, и выбирают его выбором класса; во
«Вводных» остаётся привычное «тыс ₽ за метр двора» и заданная площадь,
которая норматив перебивает.

Ловушка здесь не в самом скрытии, а в том, что тянется за ним. Объявление
поля ОДНО и остаётся в `FIELD_GROUPS`: подпись и единицу оттуда берут и
таблица классов (`classFieldLabel` / `class_field_unit`), и строка
отклонений в PDF. Вычеркни запись — и в окне классов встанет сырой ключ
`landscaping_area_per_person_sqm` без меры, то есть ровно та болезнь, что
уже ловилась на именах статей расходов: «имя без единой русской буквы — это
не имя, а ключ». А бесподписное 11 рядом со ставкой метра читается как
ставка — это ловилось на удельных показателях и на осях графиков.

Отсюда три утверждения, и каждое своё:
  — во «Вводных» поля нет;
  — в настройках класса оно есть, с подписью и с единицей;
  — значение по-прежнему доезжает до расчёта и двигает площадь двора.

Сторож списка проверяет то, без чего скрытие врёт: у скрытого поля обязан
быть ВТОРОЙ дом. Скрытое поле без профиля класса — это вводная, которую
негде править, и на экране она неотличима от несуществующей.

Проверяется отрисовкой в настоящем Chromium: и у скрытого поля, и у
показанного исходник выглядит одинаково — имя стоит в `FIELD_GROUPS` в
обоих случаях, и строковый тест зелен на любом из них.

Запуск: python3 -m pytest tests/test_the_class_norm_left_the_inputs.py -q
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

NORM = "landscaping_area_per_person_sqm"

PROBE = """(norm)=>{
  openTab('inputs');
  const field=document.getElementById('f_'+norm);
  openClassDialog();
  const body=document.getElementById('classDialogBody');
  const text=body?body.textContent:'';
  return {inForm: !!field,
          hidden: CLASS_ONLY_INPUTS.includes(norm),
          value: inputs[norm],
          classText: text};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18134) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            got = page.evaluate(PROBE, NORM)
            page.close()
    return got


def test_the_norm_is_not_drawn_in_the_inputs(seen):
    assert seen["hidden"], "поле не объявлено правимым в настройках класса"
    assert not seen["inForm"], \
        "норматив м²/чел. по-прежнему нарисован во «Вводных»"


def test_the_norm_keeps_its_label_and_unit_in_the_class_settings(seen):
    """Скрытое из формы — не значит безымянное: подпись и меру берут из FIELD_GROUPS."""
    text = seen["classText"]
    # Подпись берётся из `FIELD_GROUPS`, а не пишется здесь второй раз: держать
    # её словами значит падать на переименовании, то есть на верной правке.
    label = core.class_field_label(NORM) if hasattr(core, "class_field_label") else None
    if label is None:
        label = next(field[1] for _group, fields in core.FIELD_GROUPS
                     for field in fields if field[0] == NORM)
    assert label in text, \
        "в настройках класса нет строки норматива — поле негде править"
    assert NORM not in text, \
        "в настройках класса стоит сырой ключ вместо подписи"
    assert "м²/чел." in text, \
        "единица норматива пропала: бесподписное число рядом со ставкой читается как ставка"


def test_the_value_still_reaches_the_page_state(seen):
    """Поле не рисуется, но вводная жива: её кладут умолчания и профиль класса."""
    assert float(seen["value"]) > 0, \
        f"норматив в состоянии страницы пуст: {seen['value']!r}"


def test_a_hidden_field_has_a_second_home():
    """У скрытого поля обязан быть дом: объявление и профиль класса."""
    declared = {item[0] for _group, fields in core.FIELD_GROUPS for item in fields}
    for field in core.CLASS_ONLY_INPUTS:
        assert field in declared, (
            f"{field} скрыт из формы и не объявлен в FIELD_GROUPS — "
            "подпись и единица в настройках класса возьмутся ниоткуда")
        homes = [name for name, preset in core.PROJECT_CLASS_PRESETS.items()
                 if field in preset]
        assert homes, (
            f"{field} скрыт из формы и не входит ни в один профиль класса — "
            "это вводная, которую негде править")
        assert core.class_field_unit(field), (
            f"у {field} нет единицы в подсказке — в таблице классов "
            "он встанет голым числом")


def test_the_norm_still_moves_the_yard():
    """Предохранитель: если бы норматив перестал читаться, двор бы не двигался."""
    tep = {"apartments": {"saleable": 30_000.0}}
    small, _ = core.landscaping_area({"vri_region": "msk",
                                      NORM: 11}, tep)
    large, _ = core.landscaping_area({"vri_region": "msk",
                                      NORM: 20}, tep)
    assert small > 0 and large > small, (
        f"норматив не двигает площадь двора: 11 → {small:g} м², 20 → {large:g} м²")
