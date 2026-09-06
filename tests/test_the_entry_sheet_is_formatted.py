"""Лист ввода выглядит книгой владельца, а не вставкой в неё.

«Форматирование листа ввода в эксель сделано?» (владелец, 06.09.2026) — вопрос
законный, и ответ был «нет»: переезд ввода сделан, а вид листа нет.
Собственная шапка листа, заголовки блока очередей и подписи дописанных блоков
(«Шаг 1», «доля») шли без стиля — шрифтом по умолчанию посреди оформленной
книги; шапка уезжала вверх на ста тридцати строках, и человек правил значение,
не видя, чьё оно.

Ширины колонок и перенос объединений держит соседний
`test_the_entry_sheet_is_readable.py` — там своё утверждение («подписи не
режутся, заголовок не троится»), и повторять его здесь значило бы завести
второго сторожа одному утверждению.

Проверяется не чтением исходника, а СОБРАННОЙ книгой: стиль и закрепление
живут в XML листа, и строка в коде о них ничего не доказывает.

Правило, которое здесь держится: **цвета берутся у шаблона, а не
выдумываются.** Свой цвет сказал бы то, чего шаблон не говорит: цвет в этой
книге — утверждение о ячейке.

Запуск: python3 -m pytest tests/test_the_entry_sheet_is_formatted.py -q
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

import v4_entry_sheet as ves  # noqa: E402

TEMPLATE = ROOT / "templates" / "DevelopAid_model_v4.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон v4 не поставляется")

_CELL = re.compile(r'<x:c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</x:c>)', re.S)


@pytest.fixture(scope="module")
def book() -> zipfile.ZipFile:
    import io
    inputs = dict(core.DEFAULT_INPUTS)
    # График платежей дописывает свой блок вниз листа: без него подписи «Шаг 1»
    # и «доля» на лист не попадают вовсе, и проверка стиля не проверяет ничего.
    inputs["purchase_schedule"] = "60%@0; 40%@12"
    content, _, _ = core.build_project_workbook(
        inputs, core.TEP_DEFAULT, [], {}, project_name="Формат")
    return zipfile.ZipFile(io.BytesIO(content))


def _sheet(book: zipfile.ZipFile, name: str) -> str:
    return book.read(core._v4_sheet_path(book, name)).decode("utf-8")


def _template_sheet() -> tuple[str, str]:
    with zipfile.ZipFile(core._V4_TEMPLATE_PATH) as source:
        return (source.read(core._v4_inputs_sheet_path(source)).decode("utf-8"),
                source.read("xl/styles.xml").decode("utf-8"))


def _cells(sheet_xml: str, only: set[str] | None = None
           ) -> list[tuple[str, str | None, str]]:
    """Ячейки листа: адрес, стиль, текст. `only` — оставить перечисленные.

    Отличать наши ячейки от перенесённых обязан сборщик, а не проверка: снаружи
    наша подпись и подпись шаблона выглядят одинаково, и «на глазок» проверка
    спрашивала бы стиль и с чужой — то есть требовала бы от книги владельца
    того, чего в ней нет. Список авторства приходит из отчёта о сборке.
    """
    out: list[tuple[str, str | None, str]] = []
    for cell in _CELL.finditer(sheet_xml):
        if only is not None and cell.group(1) not in only:
            continue
        style = re.search(r's="(\d+)"', cell.group(2))
        out.append((cell.group(1), style.group(1) if style else None,
                    re.sub(r"<[^>]+>", "", cell.group(3) or "")))
    return out


def test_the_entry_header_stays_on_screen(book) -> None:
    """Шапка закреплена, и порядок тегов листа не нарушен.

    sheetViews обязан стоять ПЕРЕД cols: иначе Excel объявляет книгу
    повреждённой, а на экране это неотличимо от «книга не собралась».
    """
    entry = _sheet(book, ves.ENTRY_SHEET)
    assert 'state="frozen"' in entry, "шапка листа ввода не закреплена"
    assert re.search(r"<x:sheetViews.*?<x:cols.*?<x:sheetData", entry, re.S), (
        "порядок тегов листа нарушен: sheetViews → cols → sheetData")


def test_every_cell_we_write_carries_a_template_style() -> None:
    """Наша ячейка не бывает без стиля, и стиль у неё — шаблонный.

    Строка без стиля посреди оформленной книги читается как чужая вставка, а
    придуманный цвет сказал бы то, чего шаблон не говорит: цвет здесь —
    утверждение о ячейке.

    Лист инструкции написан нами ЦЕЛИКОМ, поэтому с него спрашивается каждая
    ячейка; с листа ввода — только те, что назвал сборщик.
    """
    template, styles = _template_sheet()
    params, entry, report = ves.build(ves.rename_sheet_refs(template), styles)
    chrome = ves.chrome_styles(template, styles)
    allowed = {str(one) for one in chrome.values() if one is not None}
    allowed |= {str(one) for one in ves._header_styles(styles)}
    allowed |= {str(one) for one in ves.style_map(styles)["entry"]}

    authored = set(report["authored"])
    assert authored, "сборщик не назвал ни одной своей ячейки — проверять нечего"
    guide = ves.guide(entry, params, styles, report, [])
    for name, cells in ((ves.ENTRY_SHEET, _cells(entry, authored)),
                        ("ИНСТРУКЦИЯ", _cells(guide))):
        bare = [(coord, text[:60]) for coord, style, text in cells if style is None]
        assert not bare, f"на листе «{name}» наши ячейки без стиля: {bare[:5]}"
        alien = [(coord, style, text[:40]) for coord, style, text in cells
                 if style not in allowed]
        assert not alien, f"на листе «{name}» стиль не из шаблона: {alien[:5]}"


def test_the_labels_of_appended_blocks_are_styled(book) -> None:
    """Подписи дописанных блоков — тем же стилем, что подписи шаблона.

    «Шаг 1» и «доля» писались без стиля, и блок графика платежей выглядел
    вставленным в чужой лист. Заголовок блока стиль имел с 0.21.х — подписи
    забыли: одна правка закрыла половину и оставила половину.
    """
    entry = _sheet(book, ves.ENTRY_SHEET)
    steps = [(coord, style) for coord, style, text in _cells(entry)
             if text.startswith("Шаг ")]
    assert steps, "блок графика платежей на лист ввода не попал — проверять нечего"
    assert all(style is not None for _, style in steps), (
        f"подписи шагов без стиля: {[c for c, s in steps if s is None][:5]}")


def test_the_book_still_opens(book) -> None:
    """Оформление не должно ломать книгу — она обязана читаться."""
    openpyxl = pytest.importorskip("openpyxl")
    import io
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as copy:
        for item in book.infolist():
            copy.writestr(item, book.read(item.filename))
    loaded = openpyxl.load_workbook(io.BytesIO(data.getvalue()), data_only=False)
    assert ves.ENTRY_SHEET in loaded.sheetnames
    assert loaded[ves.ENTRY_SHEET].freeze_panes, "закрепление шапки не доехало до книги"
