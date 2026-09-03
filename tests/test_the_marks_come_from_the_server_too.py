"""Пометки в таблице КРТ берутся и из прогона, а не только из нажатой кнопки.

«И где эта реновация и застройщики» (владелец, 03.09.2026, снимок экрана с
фильтром «Планируемый»). Признаки были посчитаны и лежали на сервере: у ста
планируемых площадок прогон нашёл 30 находок «городские нужды», 37 названных
застройщиков и пять «занята». На экране не стояло ни одной.

Причина — правка, применённая наполовину. Карточка города в таблице запасной
путь имела (`x.card_facts`, затем строка рейтинга), находки публикаций — нет:
они читались ТОЛЬКО из `state.krtPress`, то есть из кнопки, нажатой в этой
вкладке. Прогон платится за них один раз на площадку и кладёт их в строку
рейтинга — оттуда таблица их и не брала.

Проверяется настоящим кодом страницы через node. Пересказ здесь бесполезен:
строка `press_facts` в исходнике присутствует и у сломанной версии.

Запуск: python3 -m pytest tests/test_the_marks_come_from_the_server_too.py -q
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

from auction_search import ui  # noqa: E402

PAGE = ui.AUCTIONS_PAGE


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


def _marks(*, rank_row: dict, pressed: dict | None = None,
           row: dict | None = None) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const esc=s=>String(s).replace(/[&<>\"]/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));\n"
        f"const state={{krtCards:{{}},krtRank:{{s:{json.dumps(rank_row)}}},"
        f"krtPress:{json.dumps(pressed or {})}}};\n"
        + _function("krtMarks") + "\n"
        f"process.stdout.write(krtMarks({json.dumps(row or {'slug': 's'})}));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return done.stdout


CITY_NEEDS = {"quote": "Реновация — Черемушки, Котловка (ЮЗАО)",
              "url": "https://example.org/a", "official": False}
OPERATOR = {"quote": "оператором стал ФОНД", "name": "Фонд реновации",
            "url": "https://example.org/b", "official": True}


def test_a_finding_from_the_run_reaches_the_table() -> None:
    """Находка прогона рисуется без нажатой кнопки — она уже оплачена."""
    html = _marks(rank_row={"press_facts": {"available": True,
                                            "city_needs": [CITY_NEEDS],
                                            "operator_named": [OPERATOR]}})
    assert "реновация" in html, "находка «городские нужды» не доехала до таблицы"
    assert "Фонд реновации" in html, "названный оператор не доехал до таблицы"


def test_the_quote_travels_with_the_mark() -> None:
    """«Почему реновация?» — на цитату есть чем ответить, на общий ответ нет."""
    html = _marks(rank_row={"press_facts": {"available": True,
                                            "city_needs": [CITY_NEEDS]}})
    assert "Черемушки" in html
    assert "публикация: " in html, "источник признака не назван"


def test_the_city_card_says_it_is_the_city_card() -> None:
    """У официальной карточки своя подпись: источник — часть утверждения."""
    html = _marks(rank_row={},
                  row={"slug": "s", "card_facts": {
                      "renovation": True,
                      "renovation_quote": "Программа реновации",
                      "developers": ["АО «Мосинжпроект»"]}})
    assert "карточка krt.mos.ru: " in html
    assert "Мосинжпроект" in html


def test_a_pressed_button_wins_over_the_run() -> None:
    """Нажатая кнопка свежее — и потому сильнее, но второго ответа не заводит."""
    html = _marks(
        rank_row={"press_facts": {"available": True, "operator_named": [OPERATOR]}},
        pressed={"s": {"available": True,
                       "operator_named": [dict(OPERATOR, name="ГК Ромашка")]}})
    assert "ГК Ромашка" in html
    assert "Фонд реновации" not in html


def test_silence_is_not_a_mark() -> None:
    """Не спрашивали — пусто. Молчание источника не выдаётся за его ответ."""
    assert _marks(rank_row={}) == ""
    assert _marks(rank_row={"press_facts": {"available": False}}) == ""
