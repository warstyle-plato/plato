"""Дополнительный нежилой объект в книге v4 копирует рабочий блок.

Проблема вторых офисов/ОСЗ была не в движке: денежный путь уже читает
STANDALONE_OBJECTS. Блокирующим местом оставалась книга — ФОК копировался
поимёнными функциями, поэтому пятый объект требовал ещё одной ручной копии
всех формул. Эти проверки держат общий механический слой: он обязан переносить
и вводные, и расчётный блок, не сочиняя формулы заново.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _sheet(name: str) -> str:
    with zipfile.ZipFile(core._V4_TEMPLATE_PATH) as source:
        return source.read(core._v4_sheet_path(source, name)).decode("utf-8")


def test_input_block_can_be_cloned_below_the_template() -> None:
    missing: list[str] = []
    source = _sheet("Вводные")
    offset = 140
    out, written = core._v4_clone_input_object_block(
        source, core._V4_RETAIL_INPUT_ROWS, offset,
        title="ТЕСТОВЫЙ ОСЗ 2", owner="тест", missing=missing)

    assert missing == []
    assert written == [row + offset for row in core._V4_RETAIL_INPUT_ROWS]
    target = core._V4_RETAIL_INPUT_ROWS.start + offset
    assert f'r="J{target}"' in out
    assert "ТЕСТОВЫЙ ОСЗ 2" in out
    # A–D исходного блока — чужие статьи себестоимости; в копии их быть не
    # должно, иначе дополнительный объект создаёт второй набор общих ставок.
    for row in written:
        assert not re.search(rf'<x:c r="[A-D]{row}"', out)


def test_calculation_block_moves_its_input_references_with_it() -> None:
    missing: list[str] = []
    source = _sheet("ОБЪЕКТЫ")
    input_offset = 140
    object_offset = 160
    out, written = core._v4_clone_calculation_object_block(
        source, core._V4_RETAIL_OBJECT_ROWS, object_offset,
        input_rows=range(40, 56), input_offset=input_offset,
        title="ТЕСТОВЫЙ ОСЗ 2", owner="тест", missing=missing)

    assert missing == []
    assert written == [row + object_offset for row in core._V4_RETAIL_OBJECT_ROWS]
    target = core._V4_RETAIL_OBJECT_ROWS.start + object_offset
    assert f'r="A{target}"' in out
    assert "ТЕСТОВЫЙ ОСЗ 2" in out

    # В исходном блоке есть ссылки на собственные вводные ТЦ. После копии ни
    # одна такая ссылка не должна остаться на исходных строках: иначе второй
    # объект выглядит отдельным, а считает первый.
    copied = "\n".join(
        m.group(0) for m in re.finditer(
            rf'<x:row r="(?:{"|".join(str(r) for r in written)})"[^>]*>.*?</x:row>',
            out, re.S))
    assert "'Вводные'!$K$4" not in copied
    assert "'Вводные'!$K$5" not in copied