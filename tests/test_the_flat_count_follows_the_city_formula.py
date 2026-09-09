"""Число квартир выгрузки идёт за метрами — это выход формулы города.

Владелец (09.09.2026): «кстати машиноместа похоже не меняются увы». Не менялись,
и применение тут ни при чём. Число квартир было заморожено на том, что стоит в
выгрузке ГлавАПУ, а постоянные места по пункту 2 приложения 5 к 945-ПП это
«квартиры × коэффициент полосы». Стоило средней перевалить 100 м² — коэффициент
упирается в 1,6, и площадь перестаёт двигать паркинг вовсе:

  ГНС 45 000 → 250 квартир, средняя 117,0 → 400 + 40 = 440
  ГНС 50 000 → 250 квартир, средняя 130,0 → 400 + 40 = 440
  ГНС 60 000 → 250 квартир, средняя 156,0 → 400 + 40 = 440

При этом 250 — не независимое число города, а ВЫХОД его же формулы: в выгрузке
население 525, площадь квартир 525 × 33 = 17 325 м², квартир 525 / 2,1 = ровно
250, средняя 69,3 — те самые 33 × 2,1. Число названо городом для ТЭП примерно на
26 650 м² ГНС; на утроенных метрах оно остаётся числом для прежних.

Решение владельца: следовать формуле города. Тот же класс, что и встроенная
коммерция рядом с фактическим жильём, — и та же цена молчания.

Запуск: python3 -m pytest tests/test_the_flat_count_follows_the_city_formula.py -q
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402


def _prelude(glavapu: bool):
    return "\n".join([
        "const TEP_RATIOS=" + json.dumps(core.TEP_RATIOS, ensure_ascii=False) + ";",
        "const MKD_SPP_SPLIT=" + json.dumps(core.MKD_SPP_SPLIT, ensure_ascii=False) + ";",
        "const TEP_SOCIAL_INPUTS={kindergarten:'social_dou_gba_sqm',"
        "school:'social_school_gba_sqm',clinic:'social_clinic_gba_sqm'};",
        "const TEP_ROW_INPUTS={};const TEP_ROW_SWITCH={};",
        "let inputs=" + json.dumps(
            {"_glavapu_import": {"normalized": {}} if glavapu else None,
             "vri_region": "msk"}, ensure_ascii=False) + ";",
        "let tep=" + json.dumps(core.TEP_DEFAULT, ensure_ascii=False) + ";",
        # Строка выгрузки: 250 квартир на 17 325 м² — ровно то, что стоит у города.
        "tep.apartments.gns=26654;tep.apartments.total_area=23988.6;",
        "tep.apartments.saleable=17325;tep.apartments.useful=17325;",
        "tep.apartments.units=250;",
        "function renderTep(){}",
        "function renderInputs(){}",
        "function updateTepTotals(){}",
        "function calculate(){}",
        "function scheduleTepAutoRecalc(){}",
        "function landNum(v,d){return Number(v||0).toFixed(d||0)}",
        "function num(v){return String(v)}",
        "function escapeHtml(v){return String(v)}",
    ])


def _run(tail: str, glavapu: bool = True):
    """Гоняет НАСТОЯЩИЙ код страницы, добирая зависимости по именам."""
    prelude = _prelude(glavapu)
    taken: list[str] = []
    bodies: list[str] = []
    for _ in range(60):
        script = prelude + "\n" + "\n".join(bodies) + "\n" + tail
        done = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        if done.returncode == 0:
            return json.loads(done.stdout), taken
        error = done.stderr
        if "ReferenceError" not in error or " is not defined" not in error:
            raise AssertionError(error[-2500:])
        name = error.split("ReferenceError: ")[1].split(" is not defined")[0].strip()
        if name in taken:
            raise AssertionError(f"{name} не разрешается\n{error[-1500:]}")
        bodies.append(page_blocks.piece(name))
        taken.append(name)
    raise AssertionError("зависимостей больше, чем разумно разрешать")


def _edit(gns: float, glavapu: bool = True):
    tail = "\n".join([
        f"tepCellChanged('apartments','gns',{gns});",
        "console.log(JSON.stringify({row:tep.apartments,note:apartmentUnitsNote()}));",
    ])
    return _run(tail, glavapu)


def _city_flats(saleable: float) -> int:
    """Формула города — та же, что у движка: два округления вверх."""
    people = math.ceil(saleable / core.PARKING_2118_PARAMS["sqm_per_person"])
    return math.ceil(people / core.PARKING_2118_PARAMS["household"])


def test_the_flat_count_follows_the_metres():
    """Правка метров двигает число квартир формулой, которой оно и получено."""
    shown, taken = _edit(50000)
    assert "tepCellChanged" in taken, "стенд обязан гонять сам обработчик правки"
    saleable = float(shown["row"]["saleable"])
    assert saleable == pytest.approx(32500, abs=0.2)
    assert shown["row"]["units"] == _city_flats(saleable) == 470
    # Средняя вернулась к нормативу населения: 33 × 2,1.
    assert saleable / shown["row"]["units"] == pytest.approx(69.3, abs=0.3)


def test_the_metres_move_the_parking_again():
    """Пока число квартир заморожено, площадь паркинг не двигает вовсе."""
    frozen = [core.moscow_permanent_parking_by_average(gns * 0.65, 250)[0]
              for gns in (45000, 50000, 60000)]
    assert len(set(frozen)) == 1, (
        "пример подобран так, что заморозку не видно — проверять нечего")

    moved = []
    for gns in (45000, 50000, 60000):
        shown, _ = _edit(gns)
        units = int(shown["row"]["units"])
        assert units == _city_flats(float(shown["row"]["saleable"]))
        permanent, _basis = core.moscow_permanent_parking_by_average(
            float(shown["row"]["saleable"]), float(units))
        moved.append(permanent + math.ceil(permanent / 10))
    assert len(set(moved)) == 3, f"площадь по-прежнему не двигает паркинг: {moved}"
    assert moved[1] == 414, moved


def test_a_project_without_the_export_is_not_touched():
    """Решение касается выгрузки: у собранного руками делитель свой."""
    shown, _ = _edit(50000, glavapu=False)
    assert shown["row"]["units"] == 250, "число квартир тронуто там, где о нём не спрашивали"


def test_the_caption_stops_claiming_it_is_frozen():
    """Подпись под строкой не вправе утверждать снятое правило."""
    shown, _ = _edit(50000)
    note = shown["note"]
    assert "не пересчитывается" not in note, note
    assert "формуле" in note and "ГлавАПУ" in note, note

    # Вписанное руками сильнее формулы — и подпись это называет.
    tail = "\n".join([
        "tepCellChanged('apartments','gns',50000);",
        "tep.apartments.units=300;",
        "console.log(JSON.stringify({row:tep.apartments,note:apartmentUnitsNote()}));",
    ])
    shown, _ = _run(tail)
    assert "вписано руками" in shown["note"], shown["note"]
    assert str(_city_flats(float(shown["row"]["saleable"]))) in shown["note"], shown["note"]
