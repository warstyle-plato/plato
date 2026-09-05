"""Вводная, которую никто не читает, — не вводная, а обещание.

Сторож хардов ищет число на месте формулы шаблона. Эту болезнь он не видит и
видеть не может: здесь нет ни харда, ни снятой формулы — есть жёлтая ячейка,
которую человек правит, а книга не читает.

Нашёл её соседний писатель книги (Fable, 03.09.2026) на двух клетках:
«Лаг старта продаж» (B68) и «Тренд темпа продаж» (B66) не читает НИ ОДНА
формула, при том что соседи по блоку читаются сотнями и тысячами ссылок.
Работу делают колонки очередей G и AD — у лага и тренда своё значение на
очередь. Правка B68 не меняла ничего, и узнать об этом было неоткуда.

Хуже: ключ движка стоял на мёртвой ячейке. Правка живой и правка мёртвой
выглядели одинаково.

Запуск: python3 -m pytest tests/test_no_input_is_written_unread.py -q
"""

from __future__ import annotations

import collections
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

import v4_inputs  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

# Формулы книги читают лист параметров: ввод переехал на свой лист, а на
# прежних координатах стоят ссылки на него. Читателем вводной считается тот,
# кто читает КООРДИНАТУ из `_V4_INPUT_CELLS`, — она и указывает на параметры.
CROSS = re.compile(v4_inputs.PARAMS + r"'?!\$?([A-Z]{1,2})\$?(\d+)\b")
LOCAL = re.compile(r"(?<![A-Z0-9!:$])\$?([A-Z]{1,2})\$?(\d+)")


@pytest.fixture(scope="module")
def book():
    content, _, _ = core.build_project_workbook(
        {**core.DEFAULT_INPUTS}, core.TEP_DEFAULT, [], {}, project_name="Читатели")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def readers(book) -> collections.Counter:
    """Сколько формул книги читают каждую ячейку листа параметров."""
    found: collections.Counter = collections.Counter()
    for sheet in book.worksheets:
        own = sheet.title == v4_inputs.PARAMS
        for row in sheet.iter_rows():
            for cell in row:
                if not (isinstance(cell.value, str) and cell.value.startswith("=")):
                    continue
                for column, number in CROSS.findall(cell.value):
                    found[f"{column}{number}"] += 1
                if own:
                    # Ссылки внутри самого листа считаются тоже: читалка
                    # соседней колонки — полноценный читатель.
                    for column, number in LOCAL.findall(cell.value):
                        found[f"{column}{number}"] += 1
    return found


def test_the_sweep_actually_read_the_book(book):
    """Проверка отказывается судить о пустоте: ноль читателей у ВСЕГО значил бы,
    что разбор не нашёл формулы, а не что книга мертва."""
    found = readers(book)
    assert len(found) > 100, f"ссылок на лист параметров найдено {len(found)} — разбор не сработал"
    assert found.get("B59", 0) > 100, "цену квартир читает вся книга — её обязано быть видно"


def test_every_mapped_input_has_at_least_one_reader(book):
    """Ключ движка стоит только на ячейке, которую книга читает."""
    found = readers(book)
    dead = [(key, coord) for key, coord in core._V4_INPUT_CELLS.items()
            if found.get(coord, 0) == 0]
    assert not dead, (
        "вводные, которые книга пишет и никто не читает: "
        + "; ".join(f"{coord} — {key}" for key, coord in dead))


def test_the_two_found_cells_became_readouts(book):
    """Лаг и тренд теперь показывают значение очереди, а не притворяются вводной."""
    sheet = v4_inputs.inputs(book)
    assert sheet["B68"].value == "=G88", sheet["B68"].value
    assert sheet["B66"].value == "=AD88", sheet["B66"].value
    for coord in ("D66", "D68"):
        assert "блоке очередей" in str(sheet[coord].value or ""), \
            f"{coord} не говорит, где эту вводную правят"


def test_the_key_moved_to_the_cell_that_works():
    """Один ключ на двух ячейках — правка живой и мёртвой выглядят одинаково."""
    assert "sales_lag_months" not in core._V4_INPUT_CELLS.values()
    assert core._V4_INPUT_CELLS.get("sales_lag_months") is None


def test_the_guard_catches_a_planted_dead_input(book):
    """Проверка, которая не падает на поломке, — не проверка."""
    found = readers(book)
    planted = dict(core._V4_INPUT_CELLS)
    planted["выдуманная_вводная"] = "B9999"
    dead = [(key, coord) for key, coord in planted.items() if found.get(coord, 0) == 0]
    assert dead == [("выдуманная_вводная", "B9999")]
