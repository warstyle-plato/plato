"""Сброс проекта возвращает и поля Подмосковья, а подпись не обещает своё число.

На экране владельца рядом стояли две подписи об одном и том же: верхняя —
«посадка 18 000 м² на га», нижняя — «посадка по умолчанию — 30 000 м² на га».
Верхняя читала значение, нижняя печатала зашитую цифру, и обе выглядели
одинаково достоверно. Ошибка того же рода, что и «зашитая цифра на экране
неотличима от посчитанной»: копию негде обновлять, потому что копий три.

Вторая половина того же экрана: «Сбросить» не возвращал плотность. Поля
Подмосковья живут в разметке, а не в `inputs`, и `resetAll` их не видел —
после сброса у чистого проекта оставалась посадка прошлого участка, а на ней
считается потенциал продаваемой площади. Поле, которого нет в наборе, молча
остаётся мусором — правило записано в CLAUDE.md, и здесь оно сработало на
полях, объявленных прямо в HTML.

Запуск: python3 -m pytest tests/test_reset_clears_the_mo_block.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

OVERLAY = (ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")


def test_reset_touches_the_mo_block() -> None:
    """`resetAll` обязан звать сброс полей Подмосковья, а не забывать про них."""
    start = core.PAGE.index("function resetAll(){")
    body = core.PAGE[start:core.PAGE.index("\n}", start)]
    assert "resetMoParams()" in body


def test_the_mo_defaults_are_declared_once_in_the_markup() -> None:
    """Умолчание восстанавливается из атрибута value, а не из копии в коде.

    Вторая копия умолчаний разошлась бы с разметкой — ровно так разошлись три
    копии посадки.
    """
    start = core.PAGE.index("function resetMoParams(){")
    body = core.PAGE[start:core.PAGE.index("\n}", start)]
    assert "getAttribute('value')" in body
    assert "30000" not in body


def test_the_density_default_lives_in_the_field_not_in_the_markup_of_the_note() -> None:
    """Подпись читает поле. Зашитых «30 000» в слое перестройки не осталось."""
    assert "30000" not in OVERLAY
    assert "function moDensityDefault()" in OVERLAY


def test_the_note_says_current_density_when_it_differs_from_the_default() -> None:
    """«По умолчанию» рядом с не-умолчанием — неверное слово, а не неточное."""
    assert "посадка сейчас — " in OVERLAY
    assert "посадка по умолчанию — " in OVERLAY


def test_the_mo_density_field_still_declares_its_default() -> None:
    """Если атрибут исчезнет, читать станет нечего — и сброс, и подпись ослепнут."""
    match = re.search(r'<input[^>]*id="moDensity"[^>]*>', core.PAGE)
    assert match, "поле плотности Подмосковья"
    assert 'value="30000"' in match.group(0)
