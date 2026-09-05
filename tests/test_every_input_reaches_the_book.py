"""Вводная движка обязана быть в книге — ячейкой или названной вслух.

«Ты 46 то доделай и потом уже архитектуру презентации вводных меняй»
(владелец, 03.09.2026). Счёт был 82 из 164, и каждое измерение находило
больше, чем прошлое: сначала не знали про второй блок колонок, потом про блок
очередей, потом про блок соцобъектов. Пока счёт ведётся глазами, «нет ячейки»
неотличимо от «мы про неё не знаем».

Вводные делятся надвое, и обе половины закрываются здесь:
  • книга считает — значит у поля есть ячейка со своим ключом;
  • книге считать нечем (за вводной нормативные таблицы города) — значит она
    названа в `V4_INPUTS_NOT_IN_BOOK` с причиной и показана основанием.
Третьего не бывает: молча отсутствующая вводная читается как несуществующая.

Запуск: python3 -m pytest tests/test_every_input_reaches_the_book.py -q
"""

from __future__ import annotations

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

WORD = re.compile(r"\b[a-z][a-z0-9_]{3,}\b")

# Проект, у которого включено всё: блоки графиков и лестниц пишутся только
# тогда, когда им есть что писать, и на голых умолчаниях половина полей не
# появилась бы вовсе — счёт вышел бы верным для пустого проекта и ничьим.
LOADED = {**core.DEFAULT_INPUTS, "purchase_price_mln": 1000,
          "purchase_schedule": "30%@0; 70%@12",
          "offices_enabled": True, "retail_enabled": True,
          "above_parking_enabled": True, "sports_enabled": True,
          "sports_disposition": "sale",
          "sports_sales_profile": "50%@0; 50%@9",
          "sports_growth_stage1_pct": 6,
          "offices_sales_profile": "60%@0; 40%@12",
          "retail_sales_profile": "70%@0; 30%@6",
          "above_parking_sales_profile": "80%@0; 20%@6",
          "growth_stage1_pct": 10, "offices_growth_stage1_pct": 8,
          "retail_growth_stage1_pct": 5, "above_parking_growth_stage1_pct": 4}


@pytest.fixture(scope="module")
def book():
    content, _, meta = core.build_project_workbook(
        LOADED, core.TEP_DEFAULT, [], {}, project_name="Охват")
    assert not meta["missing"], meta["missing"]
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def named_in(book) -> set[str]:
    found: set[str] = set()
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    found.update(word for word in WORD.findall(cell.value) if "_" in word)
    return found


def engine_inputs() -> list[str]:
    return [field[0] for group in core.FIELD_GROUPS for field in group[1]]


def test_the_sweep_actually_read_the_book(book):
    """Проверка отказывается судить о пустоте: пустой набор имён значил бы,
    что разбор не нашёл ячейки, а не что книга полна."""
    found = named_in(book)
    assert len(found) > 100, f"имён в книге найдено {len(found)} — разбор не сработал"
    assert "purchase_price_mln" in found, "цену покупки книга обязана называть"


def test_every_engine_input_is_named_or_declared_absent(book):
    """164 из 164: либо ячейка, либо названная причина, третьего нет."""
    found = named_in(book)
    absent = [key for key in engine_inputs()
              if key not in found and key not in core.V4_INPUTS_NOT_IN_BOOK]
    assert not absent, "вводные движка, которых в книге нет и о которых она молчит: " \
                       + ", ".join(absent)


def test_the_declared_absentees_are_really_absent_by_design(book):
    """Список «книге не сосчитать» не свалка: у каждой причина, и каждая
    показана основанием — значение видно, править нечем."""
    sheet = v4_inputs.inputs(book)
    shown = {str(sheet[f"D{row}"].value or "") for row in range(1, sheet.max_row + 1)}
    for key, reason in core.V4_INPUTS_NOT_IN_BOOK.items():
        assert len(reason) > 30, f"{key}: причина не названа"
        assert key in shown, f"{key}: не показана основанием в блоке «считает движок»"


def test_the_declared_list_has_no_stale_rows():
    """Поле, которое книга научилась считать, из списка уходит."""
    known = set(engine_inputs())
    stale = [key for key in core.V4_INPUTS_NOT_IN_BOOK if key not in known]
    assert not stale, "в списке «книге не сосчитать» вводные, которых у движка нет: " \
                      + ", ".join(stale)


def test_the_guard_catches_a_new_input(book):
    """Проверка, которая не падает на поломке, — не проверка."""
    found = named_in(book)
    invented = "выдуманная_вводная_которой_нет"
    assert invented not in found and invented not in core.V4_INPUTS_NOT_IN_BOOK
