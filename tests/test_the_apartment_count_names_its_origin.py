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

С 03.09.2026 у делителя есть ОТВЕТ, а не только список: собираем сами — 60 м²
(рынок, решение владельца), Подмосковье — РНГП области (58,8), выгрузка
ГлавАПУ — число города, и наш делитель к ней не применяется вовсе. Норматив
Москвы 69,3 м² остаётся мерой НАСЕЛЕНИЯ: подпись называет его только там, где
число квартир к нему близко и его можно принять за меру квартиры.

09.09.2026 это уточнено, и уточнение касается только выгрузки: «Следовать
формуле города» (решение владельца) — число квартир ГлавАПУ идёт за метрами по
ЕГО же формуле (население по 33 м², квартиры по 2,1 жителя), потому что правка
метров иначе двигала машино-места и не двигала квартиры. Значит про выгрузку
подпись «от площади не пересчитывается» больше не верна, а расхождение строки с
формулой города НАЗЫВАЕТСЯ: молча оставленное, оно выглядит посчитанным. Что не
изменилось: НАШ делитель (60 м² рынка, РНГП области) к числу города
по-прежнему не применяется — второй ответ на вопрос, на который город ответил.

Запуск: python3 -m pytest tests/test_the_apartment_count_names_its_origin.py -q
"""

from __future__ import annotations

import json
import math
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
          krt: bool = False, region: str = "msk") -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const num=v=>String(Math.round(Number(v)*10)/10).replace('.',',');\n"
        "const escapeHtml=s=>String(s);\n"
        f"const PARKING_2118={json.dumps(core.PARKING_2118_PARAMS)};\n"
        # Средняя квартира с основанием приходит на страницу из движка — тем же
        # плейсхолдером, что версия. Стенд подставляет её оттуда же, а не своей
        # копией: копия разошлась бы с ответом, который проверяем.
        + f"const AVERAGE_FLAT={json.dumps({key: {'sqm': value, 'basis': basis} for key, (value, basis) in core.AVERAGE_FLAT_SOURCES.items()}, ensure_ascii=False)};\n"
        f"const tep={{apartments:{{saleable:{saleable},units:{units}}}}};\n"
        + f"const inputs={{{'_glavapu_import:{normalized:{}},' if glavapu else ''}vri_region:'{region}'}};\n"
        + ("const _manual_tep_import={source:{kind:'krt'}};\n" if krt
           else "const _manual_tep_import=null;\n")
        + _function("apartmentUnitsNote") + "\n"
        "process.stdout.write(apartmentUnitsNote());"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return done.stdout


def test_the_market_divisor_is_visible_and_flagged() -> None:
    """36 м² на квартиру видно сразу, и рядом стоит НАША мера, а не норматив населения."""
    note = _note(136818, 3800, krt=True)
    assert "36" in note, note
    assert "из передачи площадки КРТ" in note
    flat, basis = core.average_flat_sqm("manual")
    assert basis in note, note
    # 136 818 ÷ 60 = 2 280,3 → 2 281. Сравнивать 3 800 с нормативом населения
    # Москвы нельзя: он отвечает на «сколько людей поместится», а не на
    # «на сколько лотов режут метры».
    plain = note.replace(" ", "").replace("\u00a0", "")
    assert "2281" in plain, note
    assert f"{flat:g}" in note, note


def _city_flats(saleable: float) -> int:
    """Формула города тем же порядком, что в движке: два округления вверх.

    Одним делением на 69,3 выходит то же не всегда, и подпись, разошедшаяся с
    расчётом на единицу, читалась бы как ошибка расчёта.
    """
    per_person = float(core.PARKING_2118_PARAMS["sqm_per_person"])
    household = float(core.PARKING_2118_PARAMS["household"])
    return math.ceil(math.ceil(saleable / per_person) / household)


def test_the_city_export_is_not_divided_by_our_yardstick() -> None:
    """Наш делитель к числу города не применяется — ни в метрах, ни в подписи.

    Утверждение узкое намеренно: с 09.09.2026 подпись сверяет строку с формулой
    ГОРОДА (см. соседний тест), и запрет на «вышло бы» держал бы форму, а не
    смысл. Запрещено ровно то, что запрещено решением 03.09.2026: мерить
    выгрузку нашей средней квартирой.
    """
    note = _note(136818, 3800, glavapu=True)
    assert "из выгрузки ГлавАПУ" in note, note

    yard, basis = core.average_flat_sqm("manual")
    ours = -(-136818 // int(yard))  # 136 818 ÷ 60 = 2 280,3 → 2 281
    plain = note.replace(" ", "").replace("\u00a0", "")
    assert str(ours) not in plain, note
    assert basis not in note, note


def test_the_city_export_is_measured_by_the_city_formula() -> None:
    """Решение владельца 09.09.2026: «Следовать формуле города».

    Строка не сошлась с ней на этих метрах — подпись называет её число, а не
    молчит: молча оставленные 3 800 выглядят посчитанными.
    """
    note = _note(136818, 3800, glavapu=True)
    plain = note.replace(" ", "").replace("\u00a0", "")
    assert str(_city_flats(136818)) in plain, note
    assert "не сходится" in note, note


def test_the_city_export_that_agrees_is_not_accused() -> None:
    """Сошлось — подпись говорит это и обещает, что метры его двигают.

    Предохранитель: без него «называем расхождение» зеленело бы и на подписи,
    которая кричит о расхождении всегда.
    """
    units = _city_flats(136818)
    note = _note(136818, units, glavapu=True)
    assert "по формуле" in note, note
    assert "Правка метров его двигает" in note, note
    assert "не сходится" not in note, note


def test_the_region_changes_the_yardstick() -> None:
    """Подмосковье меряет РНГП области, а не рынком Москвы: 58,8, а не 60."""
    mo_flat, mo_basis = core.average_flat_sqm("mo")
    assert mo_flat != core.average_flat_sqm("manual")[0]
    note = _note(136818, 3800, region="mo")
    assert mo_basis in note, note


def test_the_population_norm_is_named_as_a_population_norm() -> None:
    """69,3 м² — мера жителей, и подпись говорит это прямо, а не молчит."""
    note = _note(136818, 1974)
    assert "69,3" in note, note
    assert "норматив населения" in note, note
    assert "не мера квартиры" in note, note


def test_an_empty_row_says_nothing() -> None:
    """Нет площади или нет квартир — подписи нет: делить не на что."""
    assert _note(0, 1000) == ""
    assert _note(100000, 0) == ""
