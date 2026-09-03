"""Строка квартир выдаёт себя средней квартирой, а не молчит.

«У нас сейчас 136 818 продаваемая жилья, он дал 3 800 квартир, почему так?
Должно же быть 1 974» (владелец, 03.09.2026).

Оба числа посчитаны честно, просто разными делителями, и число квартир
площадью не пересчитывается НИГДЕ. Делителей четыре:

* передача площадки КРТ — средний ПРОДАННЫЙ лот у соседей (36,0 м² на живом
  примере, отсюда 3 800);
* умолчание и Подмосковье — поле «средняя квартира», 58,75 м²;
* норматив Москвы — 33 м² на жителя × 2,1 человека на квартиру = 69,3 (1 974);
* выгрузка ГлавАПУ — строка 5 «Количество квартир», число города.

На экране они были неразличимы. Отметку о происхождении вести нельзя — она
устареет молча при первой же правке; частное «продаваемая ÷ квартиры» не
устаревает никогда, поэтому подпись считается от того, что в строке сейчас.

Запуск: python3 -m pytest tests/test_the_apartment_count_names_its_origin.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def _note(saleable: float, units: float, *, glavapu: bool = False,
          krt: bool = False) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const num=v=>String(Math.round(Number(v)*10)/10).replace('.',',');\n"
        "const escapeHtml=s=>String(s);\n"
        f"const PARKING_2118={json.dumps(core.PARKING_2118_PARAMS)};\n"
        f"const tep={{apartments:{{saleable:{saleable},units:{units}}}}};\n"
        f"const inputs={{{'_glavapu_import:{normalized:{}},' if glavapu else ''}}};\n"
        + ("const _manual_tep_import={source:{kind:'krt'}};\n" if krt
           else "const _manual_tep_import=null;\n")
        + _function("apartmentUnitsNote") + "\n"
        "process.stdout.write(apartmentUnitsNote());"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return done.stdout


def test_the_market_divisor_is_visible_and_flagged() -> None:
    """36 м² на квартиру видно сразу, и рядом стоит норматив города."""
    note = _note(136818, 3800, krt=True)
    assert "36" in note, note
    assert "из передачи площадки КРТ" in note
    # 1 975, а не 1 974: движок округляет вверх ДВАЖДЫ — сначала население
    # (136 818 / 33 = 4 146), потом квартиры (4 146 / 2,1 = 1 974,3 → 1 975).
    # Одно деление на 69,3 даёт 1 974,29 и то же 1 975, но совпадают они не
    # всегда, поэтому подпись повторяет порядок движка.
    assert "1975" in note.replace(" ", "").replace("\u00a0", ""), (
        "норматив Москвы рядом не назван: сравнить не с чем")


def test_the_city_export_is_named_as_the_city() -> None:
    """Число города подписано городом, а не «нашим»."""
    note = _note(136818, 3800, glavapu=True)
    assert "из выгрузки ГлавАПУ" in note


def test_the_norm_itself_raises_no_alarm() -> None:
    """Посчитанное нормативом расхождением не объявляется."""
    note = _note(136818, 1974)
    assert "69,3" in note or "69" in note
    assert "вышло бы" not in note, "оговорка стоит там, где расхождения нет"


def test_an_empty_row_says_nothing() -> None:
    """Нет площади или нет квартир — подписи нет: делить не на что."""
    assert _note(0, 1000) == ""
    assert _note(100000, 0) == ""
