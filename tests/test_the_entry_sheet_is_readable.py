"""Лист ввода читаем: подписи не режутся, заголовок не троится.

«По-твоему формат нормальный? С невидимыми надписями из-за размера ячеек»
(владелец, 05.09.2026). Формат был ненормальный, и причина не в вёрстке.

Шаблон пишет заголовок раздела в ЧЕТЫРЕ ячейки подряд одним и тем же текстом
(A38, B38, C38, D38 — все «СТОИМОСТЬ СТРОИТЕЛЬСТВА») и прячет три из них
объединением A38:D38. Новый лист ввода собирался копированием строк, а
объединения и ширины колонок не переносились вовсе: потерянное объединение не
оставило пустоты — оно выпустило наружу три копии заголовка, каждую обрезанную
по своей колонке, а ширина по умолчанию срезала и остальные подписи.

Правило шире этого листа: **потерянный перенос выглядит как поломка вёрстки.**
Прежде чем править ширины руками, надо спросить, что из исходного листа не
доехало.

Запуск: python3 -m pytest tests/test_the_entry_sheet_is_readable.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import v4_entry_sheet as ves  # noqa: E402


@pytest.fixture(scope="module")
def entry():
    openpyxl = pytest.importorskip("openpyxl")
    data, _name, _report = core.build_project_workbook(
        copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT),
        None, None, project_name="Формат листа ввода")
    book = openpyxl.load_workbook(io.BytesIO(data))
    return book[ves.ENTRY_SHEET]


def test_the_column_widths_came_from_the_template(entry) -> None:
    """Ширины взяты у листа, а не выдуманы: подпись не режется."""
    widths = {name: dim.width for name, dim in entry.column_dimensions.items()}
    assert widths, "ширины не заданы вовсе — подписи режутся шириной по умолчанию"
    assert widths.get("A", 0) >= 30, ("колонка подписи узкая: "
                                      f"{widths.get('A')}")


def test_the_section_header_is_shown_once(entry) -> None:
    """Заголовок раздела не троится: объединение перенесено вместе со строкой.

    Шаблон держит его в четырёх ячейках, и без объединения видны все четыре.
    """
    assert entry.merged_cells.ranges, "объединения не перенесены"
    repeats = []
    for row in range(1, entry.max_row + 1):
        seen = [entry.cell(row, column).value for column in range(1, 10)]
        text = [one for one in seen if isinstance(one, str) and one.strip()]
        if len(text) >= 2 and len(set(text)) == 1:
            repeats.append((row, text[0]))
    assert not repeats, f"заголовок виден несколько раз: {repeats}"


def test_a_merge_moves_to_the_row_it_landed_on(entry) -> None:
    """Объединение едет на НОВЫЙ номер строки, а не на прежний.

    Строки листа ввода перенумерованы: оставленное на прежнем номере
    объединение склеило бы чужие ячейки — и это выглядело бы как потерянное
    значение, а не как сдвиг.
    """
    for merged in entry.merged_cells.ranges:
        assert merged.min_row == merged.max_row, (
            f"перенесено вертикальное объединение {merged} — таких мы не переносим")
        head = entry.cell(merged.min_row, merged.min_col).value
        assert head not in (None, ""), (
            f"объединение {merged} стоит на пустой ячейке — уехало не на ту строку")


def test_the_guard_catches_a_lost_merge() -> None:
    """Проверка падает на потере переноса, а не только на живом коде."""
    sheet = ('<x:worksheet><x:cols/><x:sheetData/>'
             '<x:mergeCells count="1"><x:mergeCell ref="A38:D38"/></x:mergeCells>'
             '</x:worksheet>')
    assert ves._merges_xml(sheet, {38: 12}) == (
        '<x:mergeCells count="1"><x:mergeCell ref="A12:D12"/></x:mergeCells>')
    # Строка, не попавшая на лист ввода, объединения не тянет за собой.
    assert ves._merges_xml(sheet, {}) == ""
