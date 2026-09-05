"""Лист инструкции говорит о книге то, что в ней есть.

«Объясни инструкцией, что где вводить, а Эксель можно и где. Наверное лист
инструкции не помешал бы» (владелец, 04.09.2026).

Написать инструкцию текстом значило бы завести вторую правду о книге: раздел
переименуют, ячейка переедет, а инструкция останется прежней и будет читаться
как верная. Ровно так устарела оговорка «кадастровых номеров у площадки нет» и
«полигон границ каталогом не публикуется». Поэтому оглавление разделов
читается с САМОГО листа ввода, а не пишется рядом, и проверяется это сверкой:
каждый названный раздел обязан стоять на листе ввода на названной строке.

Попутно здесь закрыта причина, по которой инструкция и понадобилась. Разделов
на листе ввода не было вовсе: у раздела ДВА соседних заголовка — имя и шапка
колонок, — и шапка становилась границей для имени над ней. На лист уезжала
только шапка, и выходило сто строк подписей и пять «Показатель» без единого
названия — «хер поймёшь, куда ТЭПы вбивать».

Запуск: python3 -m pytest tests/test_the_book_explains_where_to_type.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

import v4_entry_sheet as ves  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = ROOT / "templates" / "DevelopAid_model_v4.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон v4 не поставляется")


@pytest.fixture(scope="module")
def book():
    content, _, meta = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT, [], {}, project_name="Инструкция")
    assert meta["missing"] == [], meta["missing"]
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def _pairs(sheet) -> list[tuple[str, str]]:
    return [(str(sheet.cell(row=r, column=1).value or "").strip(),
             str(sheet.cell(row=r, column=2).value or "").strip())
            for r in range(1, sheet.max_row + 1)]


def test_the_entry_sheet_has_its_sections(book):
    """Без имён разделов лист ввода — сто строк подписей подряд."""
    entry = book[ves.ENTRY_SHEET]
    titles = [str(entry.cell(row=r, column=1).value or "")
              for r in range(1, entry.max_row + 1)]
    named = [t for t in titles if t and t == t.upper() and len(t) > 6]
    assert len(named) >= 5, named
    assert "СДЕЛКА, НАЛОГИ И ФИНАНСИРОВАНИЕ" in named
    assert "ТЭП И СРОКИ ПО ОЧЕРЕДЯМ" in named


def test_the_guide_sections_are_read_from_the_sheet(book):
    """Каждый названный раздел стоит на листе ввода на названной строке."""
    guide, entry = book[ves.GUIDE_SHEET], book[ves.ENTRY_SHEET]
    pairs = _pairs(guide)
    start = next(i for i, (a, _) in enumerate(pairs) if a == "РАЗДЕЛЫ ЛИСТА ВВОДА")
    sections = []
    for name, span in pairs[start + 2:]:
        if not name or "–" not in span:
            break
        sections.append((name, int(span.split("–")[0])))
    assert len(sections) >= 5, sections
    for name, row in sections:
        assert str(entry.cell(row=row, column=1).value or "").strip() == name, \
            f"инструкция обещает «{name}» на строке {row}, а там другое"


def test_the_guide_names_the_two_sheets_and_the_colours(book):
    """Что где вводить и где можно — то, ради чего лист заведён."""
    text = " ".join(a + " " + b for a, b in _pairs(book[ves.GUIDE_SHEET]))
    assert ves.ENTRY_SHEET in text and ves.PARAMS_SHEET in text
    for word in ("жёлт", "формул", "заголовок"):
        assert word in text.casefold(), word


def test_the_guide_does_not_promise_a_sheet_that_is_not_there(book):
    """Инструкция, называющая несуществующий лист, — та же устаревшая
    оговорка, только сразу неверная."""
    text = " ".join(a + " " + b for a, b in _pairs(book[ves.GUIDE_SHEET]))
    for name in ("ОТЧЕТ", "Дашборд", "ПРОВЕРКИ"):
        if name in text:
            assert name in book.sheetnames, name


def test_the_guide_counts_come_from_the_transfer(book):
    """Число переехавших ячеек — из отчёта о переносе, а не из головы."""
    pairs = dict(_pairs(book[ves.GUIDE_SHEET]))
    moved = int(pairs["Переехало на лист ввода"])
    entry = book[ves.ENTRY_SHEET]
    filled = sum(1 for row in entry.iter_rows() for cell in row
                 if cell.value is not None)
    assert 0 < moved <= filled, (moved, filled)


def test_the_guide_is_second_and_the_report_is_third(book):
    """Инструкция рядом с листом, о котором она, но не вместо работы."""
    assert book.sheetnames[:3] == [ves.ENTRY_SHEET, ves.GUIDE_SHEET, "ОТЧЕТ"]
