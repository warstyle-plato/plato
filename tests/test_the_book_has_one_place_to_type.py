"""Ввод в книге один: «Вводные» для рук, «Параметры модели» для формул.

Владелец, 04.09.2026: «получается у нас будет по сути два ввода чтоль?» —
вопрос законный, и ответ на него не обещание, а проверка. Два места ввода —
это два достоверных на вид ответа про одно число: правка в одном молча не
доезжает до формул, а выглядит применённой.

Что считается вводом, решает ЦВЕТ САМОГО ШАБЛОНА, а не наш список: забытая в
списке ячейка осталась бы жёлтой на расчётном листе, то есть приглашала бы
печатать там, где печатать больше нельзя. Обратная половина не менее важна:
переехавшая ячейка обязана остаться жёлтой на новом листе — потерявшая цвет,
она читается как «считается», и человек её не тронет.

Запуск: python3 -m pytest tests/test_the_book_has_one_place_to_type.py -q
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

import v4_entry_sheet as ves  # noqa: E402

TEMPLATE = ROOT / "templates" / "DevelopAid_model_v4.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон v4 не поставляется")

_CELL = re.compile(r'<x:c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</x:c>)', re.S)


def _styles(sheet_xml: str) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for cell in _CELL.finditer(sheet_xml):
        found = re.search(r's="(\d+)"', cell.group(2))
        out[cell.group(1)] = int(found.group(1)) if found else None
    return out


def _has_value(sheet_xml: str) -> set[str]:
    return {cell.group(1) for cell in _CELL.finditer(sheet_xml)
            if "<x:v>" in (cell.group(3) or "") or "<x:is>" in (cell.group(3) or "")}


@pytest.fixture(scope="module")
def split():
    source = zipfile.ZipFile(core._V4_TEMPLATE_PATH)
    sheet = source.read(core._v4_inputs_sheet_path(source)).decode("utf-8")
    styles = source.read("xl/styles.xml").decode("utf-8")
    params, entry, report = ves.build(ves.rename_sheet_refs(sheet), styles)
    return params, entry, report, ves.style_map(styles)


def test_the_split_actually_moved_the_sheet(split):
    """Ноль найденного значит что-то только вместе с числом прочитанного.

    «Нарушений нет» на неразобранном листе выглядит ровно как чистый лист.
    """
    _params, _entry, report, style = split
    assert len(style["entry"]) > 20, style["entry"]
    assert report["moved"] > 150, report["moved"]


def test_nothing_yellow_is_left_on_the_calculation_sheet(split):
    """Печатать на «Параметрах модели» больше негде — и цвет это говорит."""
    params, _entry, _report, style = split
    left = [coord for coord, sid in _styles(params).items()
            if sid in style["entry"]]
    assert not left, f"на расчётном листе осталось приглашение печатать: {left[:12]}"


def test_every_moved_cell_stays_an_input_on_the_entry_sheet(split):
    """Переехавшая вводная остаётся жёлтой: посеревшая читается как расчёт."""
    _params, entry, report, style = split
    styles = _styles(entry)
    grey = [(source, target) for source, target in report["map"].items()
            if styles.get(target) not in style["entry"]]
    assert not grey, f"вводные потеряли цвет ввода: {grey[:12]}"


def test_every_moved_cell_left_a_readout_behind(split):
    """На прежней координате стоит ссылка на ввод, а не пустое место.

    Пустая ячейка на месте вводной — это ноль в формуле книги, и выглядит он
    как посчитанный.
    """
    params, _entry, report, _style = split
    bodies = {cell.group(1): (cell.group(3) or "") for cell in _CELL.finditer(params)}
    silent = [source for source, target in report["map"].items()
              if f"'{ves.ENTRY_SHEET}'!{target}" not in bodies.get(source, "")]
    assert not silent, f"вводные исчезли, не оставив читалки: {silent[:12]}"


def test_the_guard_catches_a_yellow_cell_left_behind(split):
    """Проверка, которая не падает на поломке, — не проверка."""
    params, _entry, _report, style = split
    planted = params.replace("</x:sheetData>", "", 1) + (
        f'<x:row r="9999"><x:c r="B9999" s="{sorted(style["entry"])[0]}">'
        "<x:v>1</x:v></x:c></x:row></x:sheetData>")
    left = [coord for coord, sid in _styles(planted).items() if sid in style["entry"]]
    assert left == ["B9999"], left
