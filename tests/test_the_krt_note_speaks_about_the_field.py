"""Надпись о плате за ВРИ говорит о ПОЛЕ, а не только о режиме.

«Надпись противоречит 10 млрд» (владелец, 07.09.2026, экран калькулятора): в
поле «Оформление земельных правоотношений / смена ВРИ» стояло 10 166,649 млн ₽,
а прямо над ним — «Режим „Требование КРТ": платы за смену ВРИ здесь нет».
Число верное: заданная плата идёт в расчёт как есть — в CAPEX, в расчётный
лимит БРИДЖа, в график платежей и в книгу. Неверна была надпись: утверждение о
методике КРТ она подавала как утверждение о текущем состоянии поля.

Правка 05.09.2026 закрыла только ПЕРЕКЛЮЧЕНИЕ режима (`krtClearsVriFee` зовётся
из `onchange`). Всё, что кладёт плату при УЖЕ включённом режиме, проходило мимо,
и главный такой путь — выгрузка ГлавАПУ: `applyGlavapu` писала
`mappings.inputs` в `inputs` через `Object.assign`, то есть мимо
`KRT_REQUIREMENT_INPUTS`, и не говорила ни слова.

Закреплено: замок держит и против выгрузки ГлавАПУ, а не тронутое ею —
называется. Надпись у поля и подвал КРТ — tests/test_krt_keeps_the_vri_fee.py
(режим КРТ плату больше не отменяет, решение владельца 13.10.2026).

Запуск: python3 -m pytest tests/test_the_krt_note_speaks_about_the_field.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _function_body(page: str, declaration: str) -> str:
    """Границей куска кода служат скобки, а не соседняя строка.

    Проверка, вырезающая «от объявления до следующего комментария», ломается,
    когда рядом что-то переписали, и падает не о том, что сломалось.
    """
    start = page.index(declaration)
    open_brace = page.index("{", start + len(declaration) - 1)
    depth = 0
    for i in range(open_brace, len(page)):
        if page[i] == "{":
            depth += 1
        elif page[i] == "}":
            depth -= 1
            if depth == 0:
                return page[start:i + 1]
    raise AssertionError(f"тело {declaration} не закрыто скобкой")


def test_the_glavapu_import_respects_the_krt_lock() -> None:
    """Ловится ВЫЗОВ: есть общий писатель вводных — звать обязаны его.

    Поведенческая проверка тут была бы зелёной и на сломанном коде: замок
    держит только те ключи, которые ему передали, а `Object.assign` до него
    не доходит вовсе.
    """
    body = _function_body(core.PAGE, "async function applyGlavapu()")
    assert "applyDerivedInputs(glavapuImport.mappings.inputs" in body, (
        "выгрузка пишет вводные мимо замка «Требования КРТ»")
    assert "Object.assign(inputs,glavapuImport.mappings.inputs" not in body, (
        "прежний писатель остался рядом с новым — два ответа на один вопрос")
    assert "glavapuSkipped" in body, "не тронутое замком не названо"
