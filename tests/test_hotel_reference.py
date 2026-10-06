"""Ориентиры гостиницы стоят в модуле ровно такими, как в ячейках книг.

`hotel_reference` — машинная сторона разбора эталонных моделей владельца
(`docs/reference/hotel/`). Число без сверки с ячейкой — то самое число без
основания, которое на экране выглядит как посчитанное. Поэтому каждая ячейка
перечитывается из книги (сохранённые Excel итоги, `data_only=True`), а сверка
обязана падать на подделке — иначе её зелёный цвет ничего не доказывает.

Запуск: python3 -m pytest tests/test_hotel_reference.py -q
"""

from __future__ import annotations

import ast
import dataclasses
import math
import sys
import warnings
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hotel_reference as ref  # noqa: E402
import hotel_reference_doc as doc  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string  # noqa: E402


@lru_cache(maxsize=None)
def workbook_cells() -> dict[str, object]:
    """Все ячейки, на которые ссылается модуль: ключ → значение книги.

    Книги открываются один раз и только на чтение; лист читается окном строк,
    в которое попадают нужные ячейки, — книга Домбая весит 5 МБ.
    """
    wanted: dict[tuple[str, str], list[ref.Benchmark]] = defaultdict(list)
    for b in ref.BENCHMARKS:
        wanted[(b.model, b.sheet)].append(b)
    found: dict[str, object] = {}
    by_model: dict[str, list[str]] = defaultdict(list)
    for model, sheet in wanted:
        by_model[model].append(sheet)
    for model, sheets in by_model.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = openpyxl.load_workbook(ref.workbook_path(model), data_only=True,
                                          read_only=True)
        try:
            for sheet in sheets:
                items = wanted[(model, sheet)]
                coords = [coordinate_from_string(b.cell) for b in items]
                grid: dict[str, object] = {}
                for row in book[sheet].iter_rows(
                        min_row=min(r for _, r in coords), max_row=max(r for _, r in coords),
                        max_col=max(column_index_from_string(c) for c, _ in coords)):
                    for cell in row:
                        if hasattr(cell, "coordinate"):
                            grid[cell.coordinate] = cell.value
                for b in items:
                    found[b.key] = grid.get(b.cell)
        finally:
            book.close()
    return found


def mismatches(benchmarks, cells) -> list[str]:
    out = []
    for b in benchmarks:
        actual = cells.get(b.key)
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            out.append(f"{b.source}: в книге не число ({actual!r})")
        elif not math.isclose(b.value, actual, rel_tol=1e-8, abs_tol=1e-9):
            out.append(f"{b.source}: в модуле {b.value!r}, в книге {actual!r}")
    return out


def test_every_benchmark_is_the_cell_it_names():
    assert mismatches(ref.BENCHMARKS, workbook_cells()) == []


def test_the_check_fails_on_a_forged_value():
    """Подделка — ориентир, сдвинутый на процент, — обязана быть пойманной."""
    forged = [dataclasses.replace(b, value=b.value * 1.01 if b.value else 1.0)
              for b in ref.BENCHMARKS[:3]]
    assert len(mismatches(forged, workbook_cells())) == 3


def test_the_check_fails_on_a_wrong_address():
    """Число верное, адрес чужой: ссылка на соседнюю ячейку — тоже подделка."""
    rooms = ref.BY_KEY["dombai:Предпосылки!E116"]
    moved = dataclasses.replace(rooms, cell="E118")
    cells = dict(workbook_cells())
    cells[moved.key] = 155  # то, что книга держит в E118
    assert mismatches([moved], cells)


def test_every_reference_file_is_on_disk():
    for model in ref.MODELS:
        assert ref.workbook_path(model).is_file(), model


def test_keys_are_unique_and_groups_are_known():
    assert len(ref.BY_KEY) == len(ref.BENCHMARKS)
    assert {b.group for b in ref.BENCHMARKS} <= set(ref.GROUPS)
    assert {d.group for d in ref.DERIVED} <= set(ref.GROUPS)


def test_derived_values_read_only_known_cells():
    for d in ref.DERIVED:
        assert d.numerator in ref.BY_KEY and d.denominator in ref.BY_KEY, d.label
        assert d.numerator.split(":")[0] == d.denominator.split(":")[0] == d.model
    for _, keys, _ in ref.DISCREPANCIES:
        assert all(k in ref.BY_KEY for k in keys)


def test_staff_per_room_agrees_with_the_book_where_it_states_it():
    """UAI сам пишет «штат на номер» (E121) — частное модуля сходится с ним."""
    staff = next(d for d in ref.DERIVED if d.model == ref.UAI and d.group == "staff")
    assert staff.value == pytest.approx(ref.value("uai:Штатное расписание!E121"))


def test_the_document_tables_are_built_from_the_module():
    text = doc.DOC.read_text(encoding="utf-8")
    assert doc.current_block(text) == doc.render(), (
        "python3 scripts/hotel_reference_doc.py --write")


def test_the_engine_does_not_read_the_reference_yet():
    """До решения владельца ориентир чужого отеля в экономику не идёт."""
    for name in ("main_legacy.py", "main.py", "developaid_nonres_strategy.py"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names}
        imported |= {node.module for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module}
        assert "hotel_reference" not in imported, name
