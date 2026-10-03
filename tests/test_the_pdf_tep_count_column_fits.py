"""Колонка «Кол-во» таблицы ТЭП в PDF не рвёт меру и итог.

После разбора единиц по мере счёта (#550) в узкой колонке «1 362 квартир»
печаталось «кварти / р», а итог «1 362 квартир · 1 199 м/м · 250 мест»
разваливался на семь строк (аудит регрессий 29.09.2026, №4). Числа при этом
были верны — ломалась вёрстка.

Проверка идёт по настоящей таблице ReportLab из `_build_developaid_pdf`:
каждая ячейка количества укладывается в ширину колонки, строка продукта —
одной строкой, итог — ровно по строке на меру.

Запуск: python3 -m pytest tests/test_the_pdf_tep_count_column_fits.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

pytest.importorskip("reportlab")


def _tep_table(monkeypatch, inputs: dict, tep: dict):
    """Таблица ТЭП в том виде, в каком её собрал отчёт."""
    import reportlab.platypus as platypus

    built = []
    original = platypus.Table

    class Recording(original):
        def __init__(self, data, *args, **kwargs):
            super().__init__(data, *args, **kwargs)
            built.append((data, kwargs.get("colWidths") or (args[0] if args else None)))

    monkeypatch.setattr(platypus, "Table", Recording)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    core._build_developaid_pdf({"project_name": "Кол-во", "result": result,
                                "inputs": inputs, "tep": tep, "rates": []})
    for data, widths in built:
        header = [getattr(cell, "text", str(cell)) for cell in data[0]]
        if header and header[0] == "Продукт" and header[-1] == "Кол-во":
            return data, widths, result
    raise AssertionError("таблица ТЭП с колонкой «Кол-во» не найдена")


def _lines(cell, width: float) -> list[float]:
    cell.wrap(width, 10_000)
    return list(cell.getActualLineWidths0())


def _assert_counts_fit(data, widths, result) -> None:
    column = float(widths[-1]) - 10  # поля ячейки: 5 + 5 пт
    measures = [m for m, v in (result["tep"]["total"].get("units_by_measure") or {}).items() if v]
    assert measures, "у проекта нет единиц — проверять нечего"
    for row in data[1:-1]:
        cell = row[-1]
        if cell.text in ("", "—"):
            continue
        lines = _lines(cell, column)
        assert max(lines) <= column + 0.01, (cell.text, lines, column)
        # Мера из одного слова не переносится вовсе: «1 362 квартир» — одна
        # строка, а не «1 362 кварти / р».
        if " " not in cell.text.replace(" ", ""):
            assert len(lines) == 1, (cell.text, lines, column)
    total = data[-1][-1]
    lines = _lines(total, column)
    assert max(lines) <= column + 0.01, (total.text, lines, column)
    assert len(lines) == len(measures), (total.text, lines, measures)
    for measure in measures:
        assert measure in total.text


def test_the_default_project_prints_whole_counts(monkeypatch):
    data, widths, result = _tep_table(
        monkeypatch, copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT))
    _assert_counts_fit(data, widths, result)
    assert sum(widths) == pytest.approx(170 * 72 / 25.4, abs=0.5)


def test_nagatino_prints_whole_counts(monkeypatch):
    import project_preset

    path = ROOT / "presets" / "КРТ_Нагатино.json"
    if not path.exists():
        pytest.skip("пресет КРТ Нагатино не найден")
    preview = project_preset.build_preview(json.loads(path.read_text(encoding="utf-8")))
    inputs = {**copy.deepcopy(core.DEFAULT_INPUTS), **preview["inputs"]}
    data, widths, result = _tep_table(monkeypatch, inputs, preview["tep"])
    _assert_counts_fit(data, widths, result)


def test_the_count_is_one_unbreakable_word():
    text = core._pdf_count_text(1362, "квартир")
    assert text == "1 362 квартир"
    # Длинная мера переносится по своим словам, число с мерой — нет.
    assert core._pdf_count_text(4500, "посещений в смену") == "4 500 посещений в смену"


def test_the_width_check_catches_the_old_narrow_column():
    """Контрпример: прежние 15 мм проверка обязана поймать."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    regular, _bold = core._pdf_font_names()
    style = ParagraphStyle("t", fontName=regular, fontSize=8.8, leading=12)
    cell = Paragraph(core._pdf_count_text(1362, "квартир"), style)
    assert len(_lines(cell, 15 * 72 / 25.4 - 10)) > 1
    need = core._pdf_count_column_width([cell.text], regular, 8.8, 5, 0)
    assert len(_lines(cell, need - 10)) == 1
