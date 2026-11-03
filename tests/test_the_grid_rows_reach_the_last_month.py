"""Строка сетки доходит до последнего месяца, а её итог складывает весь горизонт.

Ширина помесячной сетки объявлена один раз (`_V4_MONTH_COLUMNS`,
`_V4_LAST_COLUMN`), и 0.22.91 протянул шаблон со 120 месяцев до 180. Копии
прежней ширины при этом остались в самом коде — четырьмя `range(120)` и восемью
литералами `DS` внутри формул, — и находились они не поиском по строке `120`, а
по тому, что величина ЗНАЧИТ: где кончается горизонт.

Цена промаха измерена на собранной книге. Тридцать шесть итогов в колонке B
складывали первые 120 месяцев из 180. На листе ОБЪЕКТЫ строки продаж паркинга
за 121-м месяцем не существовало ВОВСЕ (360 ячеек), а строка себестоимости с
121-го месяца шла без слагаемого паркинга — то есть у проекта длиннее десяти лет
книга не продавала места и не платила за них, и выглядело это как посчитанный
результат.

Проверяется то, что видно в собранной книге, а не текст исходника: литерал
`DS` в файле выглядит одинаково и у верного кода, и у сломанного.

Запуск: python3 -m pytest tests/test_the_grid_rows_reach_the_last_month.py -q
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

# Итог строки: `SUM(D37:GA37)`, иногда с листом и долларами. Диапазон одной
# колонки (`SUM(D5:D5)` КОНСОЛИДАТОРА) горизонтом не является.
_TOTAL_RE = re.compile(
    r"^SUM\((?:'[^']+'!)?\$?D\$?(\d+):(?:'[^']+'!)?\$?([A-Z]+)\$?(\d+)\)$")
_CELL_RE = re.compile(r'<(?:x:)?c r="([A-Z]+)(\d+)"[^>]*?(?:/>|>(.*?)</(?:x:)?c>)', re.S)


def _formula(body: str | None) -> str | None:
    if not body:
        return None
    found = re.search(r"<(?:x:)?f>(.*?)</(?:x:)?f>", body, re.S)
    return html.unescape(found.group(1)).strip() if found else None


@pytest.fixture(scope="module")
def sheets() -> dict[str, str]:
    """Листы собранной книги. Сборка дорогая — один раз на файл."""
    built = core.build_project_workbook(
        json.loads(json.dumps(core.DEFAULT_INPUTS)), core.TEP_DEFAULT, [], {},
        project_name="П")
    blob = built[0] if isinstance(built, tuple) else built
    data = blob if isinstance(blob, (bytes, bytearray)) else blob.getvalue()
    source = zipfile.ZipFile(io.BytesIO(data))
    out: dict[str, str] = {}
    for name in ("CAPEX", "ОБЪЕКТЫ", "Ставки", "ВРИ", "CF_1", "Продажи"):
        out[name] = source.read(core._v4_sheet_path(source, name)).decode("utf-8")
    return out


def _short_totals(xml: str) -> list[tuple[str, str]]:
    """Итоги колонки B, которые складывают не весь горизонт."""
    short: list[tuple[str, str]] = []
    for column, row, body in _CELL_RE.findall(xml):
        if column != "B":
            continue
        formula = _formula(body)
        if not formula:
            continue
        found = _TOTAL_RE.match(formula)
        if not found or found.group(2) == "D":
            continue
        if found.group(2) != core._V4_LAST_COLUMN:
            short.append((f"B{row}", formula))
    return short


def test_a_row_total_sums_the_whole_horizon(sheets) -> None:
    """Итог строки кончается там же, где кончается сетка."""
    seen = 0
    for name, xml in sheets.items():
        short = _short_totals(xml)
        seen += 1
        assert not short, (
            f"лист {name}: итог складывает не весь горизонт — {short[:4]}. "
            f"Сетка идёт до {core._V4_LAST_COLUMN} "
            f"({core._V4_MONTH_COLUMNS} мес.); ширина объявлена "
            "`_V4_LAST_COLUMN`, а не литералом в формуле.")
    assert seen, "листы не прочитаны — проверка ничего не утверждает"


def test_the_check_fails_on_a_truncated_total(sheets) -> None:
    """Сторож обязан падать на поломке — иначе он ничего не значит."""
    planted = sheets["CAPEX"].replace(
        f"SUM(D31:{core._V4_LAST_COLUMN}31)", "SUM(D31:DS31)", 1)
    assert planted != sheets["CAPEX"], "образец итога не найден — подделка не удалась"
    assert _short_totals(planted), "обрезанный итог не назван"


@pytest.mark.parametrize("sheet, rows", [
    # Соцстройка очередей: строка идёт формулой по блоку «Вводных».
    ("CAPEX", (31, 65, 99, 133)),
    # Паркинг объектов: объём, себестоимость и продажи мест.
    ("ОБЪЕКТЫ", (25, 29, 32, 33)),
    # Кривая ключевой ставки.
    ("Ставки", (5,)),
])
def test_the_rows_we_write_reach_the_last_month(sheets, sheet, rows) -> None:
    """Последний месяц сетки заполнен, а не оставлен шаблону.

    Прежде цикл писал 120 колонок из 180: у проекта длиннее десяти лет хвост
    графика оставался пустым, и книга собиралась МОЛЧА.
    """
    xml = sheets[sheet]
    last = core._V4_LAST_COLUMN
    for row in rows:
        found = re.search(
            r'<(?:x:)?c r="%s%d"[^>]*?(?:/>|>(.*?)</(?:x:)?c>)' % (last, row), xml, re.S)
        assert found is not None, f"{sheet}: ячейки {last}{row} нет вовсе"
        assert _formula(found.group(1)), (
            f"{sheet}: {last}{row} без формулы — строка кончается раньше сетки")
