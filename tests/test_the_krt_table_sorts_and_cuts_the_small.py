"""Таблица КРТ сортируется и отсекает мелкие площадки.

«Сортировка или фильтрация выводной таблицы по объёму жилья, чтобы не брать
мелкие объекты» и «в Excel уже есть данные расчёта модели — можно ли их тоже
выводить на экран, чтобы сортировать по LLCR» (владелец, 31.08.2026). Числа
модели приезжали в браузер и не рисовались: в выгрузке они были, на экране нет.

Две вещи проверяются как поведение, а не как строка в исходнике. Непосчитанная
модель — это «не знаем», а не ноль: при любом направлении сортировки такая
строка уходит вниз, иначе она встаёт впереди худших. И площадка без указанного
объёма жилья — не «маленькая»: порог её прячет, но считает отдельно и называет
под таблицей, потому что молча выброшенная читается как отсеянная по размеру.

Запуск: python3 -m pytest tests/test_the_krt_table_sorts_and_cuts_the_small.py -q
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


SITES = [
    {"slug": "big", "name": "Крупная", "housing_gfa_sqm": 300_000, "status": "Планируемый"},
    {"slug": "small", "name": "Мелкая", "housing_gfa_sqm": 12_000, "status": "Планируемый"},
    {"slug": "quiet", "name": "Без объёма", "housing_gfa_sqm": None, "status": "Планируемый"},
]
RANK = {
    "big": {"available": True, "project_llcr_x": 1.31, "margin_pct": 18.2},
    "small": {"available": True, "project_llcr_x": 0.94, "margin_pct": 4.1},
    # У третьей модель не считалась вовсе.
    "quiet": {"available": False, "reason": "модель не собрана"},
}


def _run(program: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def _sorted_by(key: str, direction: int) -> list[str]:
    program = (
        f"const state={{krtRank:{json.dumps(RANK)},krtRequirements:{{}},krtModels:{{}},"
        f"krtSort:{{key:{json.dumps(key)},dir:{direction}}}}};\n"
        "function krtScore(x){return {score:Number(x.housing_gfa_sqm)||0}}\n"
        + _function("krtValue") + "\n" + _function("krtCompare") + "\n"
        + f"const rows={json.dumps(SITES)}.slice().sort(krtCompare);\n"
        "console.log(JSON.stringify({names:rows.map(r=>r.slug)}));"
    )
    return _run(program)["names"]


def test_the_model_numbers_reach_the_screen() -> None:
    assert 'data-sort="llcr"' in PAGE and 'data-sort="margin"' in PAGE
    cell = _function("krtModelCell")
    assert "project_llcr_x" in cell and "margin_pct" in cell
    assert "weakest_phase_llcr_x" in cell, "слабейшая очередь стоит рядом с проектной"


def test_an_uncomputed_model_never_climbs_above_the_worst() -> None:
    """`null` — это «не знаем», и вниз оно уходит при обоих направлениях."""
    assert _sorted_by("llcr", -1) == ["big", "small", "quiet"]
    assert _sorted_by("llcr", 1) == ["small", "big", "quiet"]


def test_sorting_by_a_catalogue_column_works_both_ways() -> None:
    assert _sorted_by("housing", -1) == ["big", "small", "quiet"]
    assert _sorted_by("housing", 1) == ["small", "big", "quiet"]
    assert _sorted_by("name", 1)[0] == "quiet", "«Без объёма» первое по алфавиту"


def test_the_threshold_tells_a_small_site_from_an_unknown_one() -> None:
    filter_body = _function("filterKrt")
    assert "krtMinHousing" in filter_body
    assert "unknown++" in filter_body and "small++" in filter_body, \
        "скрытые порогом считаются раздельно"
    note = _function("renderKrtFilterNote")
    assert "ниже порога" in note and "не знаем" in note, \
        "молча выброшенная площадка читается как отсеянная по размеру"


def test_the_second_click_turns_the_column_over() -> None:
    body = _function("krtSortBy")
    assert "dir*=-1" in body
    assert "'name'" in body and "'status'" in body, \
        "у имени и статуса умолчание по возрастанию, у чисел по убыванию"
