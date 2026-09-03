"""Машино-места считает постановление — на всех поверхностях, а не там, где повезло.

«Машиноместа конечно он должен считать по постановлениям» (владелец,
03.09.2026). До этой правки формула жила в трёх видах, и совпадали они только
на бумаге:

* движок — 2118-ПП: `ceil(S / (33 × 2,1) × 0,8)` от ПЛОЩАДИ КВАРТИР;
* страница — та же норма, но пересчёт начинался с проверки выгрузки ГлавАПУ и
  без неё не делал ничего: проект, набранный руками, оставался с прежним
  числом мест, и правка метров его не двигала;
* модуль КРТ — своя строка `ГНС жилья / 100`, то есть прежний порядок 945-ПП
  и чужая база.

На 136 818 м² квартир норма даёт 1 580 постоянных мест; старая строка модуля
КРТ на том же проекте — около 2 100. Число выглядело посчитанным в обоих
случаях.

Запуск: python3 -m pytest tests/test_parking_follows_the_decree_everywhere.py -q
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
APARTMENTS = 136818.0


def _function(name: str) -> str:
    """Границу функции считаем скобками: соседний комментарий не контракт."""
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


def test_the_engine_counts_by_the_decree() -> None:
    """Пункт 1 приложения 5: от площади квартир, без К1, гостевые десятой частью."""
    permanent = core.moscow_permanent_parking_2118(APARTMENTS)
    assert permanent == math.ceil(APARTMENTS / (33.0 * 2.1) * 0.8) == 1580
    # К1 в постоянных местах больше нет: удвоение площади удваивает места ровно.
    assert core.moscow_permanent_parking_2118(APARTMENTS * 2) == 3159


def test_the_page_counts_without_a_city_export() -> None:
    """Норма считается и без выгрузки: у проекта, набранного руками, тоже есть места."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const num=v=>String(v);\n"
        f"const PARKING_2118={json.dumps(core.PARKING_2118_PARAMS)};\n"
        f"const tep={{apartments:{{saleable:{APARTMENTS}}}}};\n"
        "const inputs={};\n"
        + _function("undergroundAreaPerSpace") + "\n"
        + _function("normativeUnderground") + "\n"
        "process.stdout.write(JSON.stringify(normativeUnderground()));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    got = json.loads(done.stdout)
    assert got["permanent"] == 1580, got
    assert got["guest"] == 158, got
    assert got["spaces"] == 1738
    assert "2118-ПП" in got["basis"], "основание не названо"
    # Приобъектные места нежилья без К1 и К2 не выдумываются — и это сказано.
    assert got["mfc"] == 0
    assert "нежил" in got["basis"]


def test_the_page_has_one_answer_about_the_requirement() -> None:
    """У потребности один ответ на весь экран: выгрузка, иначе норма."""
    assert "function parkingRequirement(" in PAGE
    # Прямых обращений к выгрузке за потребностью не осталось: иначе один
    # читатель показывал бы норму, а соседний — пустоту.
    body = _function("parkingRequirement")
    assert "getGlavapuUnderground()" in body and "normativeUnderground()" in body
    # Объявление функции содержит ту же строку — считаем только вызовы.
    calls = PAGE.count("getGlavapuUnderground()") - PAGE.count("function getGlavapuUnderground()")
    assert calls - body.count("getGlavapuUnderground()") == 0, (
        "потребность где-то читается мимо общего ответа")


def test_the_krt_module_does_not_keep_its_own_formula() -> None:
    """Модуль КРТ зовёт движковую норму, а не делит ГНС на сто."""
    source = (ROOT / "auction_search" / "krt_screening.py").read_text(encoding="utf-8")
    assert "moscow_permanent_parking_2118" in source
    assert "PARKING_GNS_PER_SPACE" not in source, "старая формула осталась в модуле"
    assert "housing_gfa / PARKING" not in source
