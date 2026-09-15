# -*- coding: utf-8 -*-
"""Охват вводных книгой меряется по книге, а не по длине карты.

Запись «92 ячейки на 188 вводных» в списке дел держалась почти неделю и была
неверна: 92 — это длина `_V4_INPUT_CELLS`, а блоки (график платежей, лестницы
цены, профили продаж, ступени ставки ПФ, соцобъекты, очереди) в карту не входят
и несут ещё две с лишним сотни ячеек. Счёт, считающий то, о чём знает, занижает
охват по нашему же недосмотру — и по нему чинят то, что давно есть.

Здесь обе болезни меряются на СОБРАННОЙ книге:

1. ключ вводной назван в книге — иначе человек не найдёт, где её править;
2. ячейка ввода жива — её зеркало на «Параметрах модели» читает хоть одна
   формула. Мёртвая ячейка жёлтая и правится, а не меняет ничего: ровно так
   жили `B66` и `B68` до 0.22.x.

Читатели считаются с разворотом диапазонов: ссылка `$E$9:$G$9` читает ячейку,
и без разворота полтора десятка живых вводных выглядели бы мёртвыми. Ошибаться
сторож обязан в сторону «прочитано»: ложная тревога дороже пропуска — её
обходят, а обход выглядит правкой.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest
from openpyxl.utils import column_index_from_string as col_index, get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import v4_entry_sheet  # noqa: E402
import main as wrapper  # noqa: E402

core = wrapper.core

PARAMS = v4_entry_sheet.PARAMS_SHEET
ENTRY = v4_entry_sheet.ENTRY_SHEET

# Профиль продаж ЗАМЕЩАЕТ формулу «доля до РВЭ + остаток» — это методика, а не
# потеря: у объекта с профилем доля читателя не имеет и иметь не должна.
# Запрещаем место, а не слово: исключение названо здесь и только для сборки,
# где профиль задан.
PROFILE_SUPERSEDES = {
    "offices_share_before_rve_pct", "retail_share_before_rve_pct",
    "above_parking_share_before_rve_pct", "sports_share_before_rve_pct",
}

# Лестница цены замещает ежемесячный рост до РВЭ — «задан хоть один этап, и
# ежемесячный рост не применяется» (движок: `sales_schedule`, ветка
# `price_factor is not None`). У объекта с лестницей эта вводная читателя не
# имеет и иметь не должна.
LADDER_SUPERSEDES = {
    "monthly_growth_pre_pct", "offices_growth_pre_pct", "retail_growth_pre_pct",
    "above_parking_growth_pre_pct", "sports_growth_pre_pct",
}

_OBJECTS = {
    "offices_enabled": True, "retail_enabled": True,
    "above_parking_enabled": True, "sports_enabled": True,
    "offices_gba_sqm": 20000, "retail_gba_sqm": 15000,
    "above_parking_spaces": 100, "sports_gba_sqm": 5000,
    "vri_required": True,
    # Формат ступеней — «покрытие : ставка», как в договоре. Строка не того
    # формата разбирается в пустой список, блок не пишется вовсе, и охват
    # вышел бы занижен нашей же фикстурой.
    "pf_special_steps": "100:3,47; 110:1,75; 120:0,03",
}
_BLOCKS = {
    "purchase_schedule": "30%@0; 40%@6; 30%@12",
    "growth_stage1_pct": 5, "growth_stage2_pct": 7,
    "offices_sales_profile": "50%@0; 50%@12",
    "retail_sales_profile": "50%@0; 50%@12",
    "above_parking_sales_profile": "50%@0; 50%@12",
    "sports_sales_profile": "50%@0; 50%@12",
    "offices_growth_stage1_pct": 4, "retail_growth_stage1_pct": 4,
    "above_parking_growth_stage1_pct": 4, "sports_growth_stage1_pct": 4,
}


def _build(extra: dict) -> bytes:
    inputs = {**core.DEFAULT_INPUTS, **_OBJECTS, **extra}
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    content, _name, _meta = core.build_project_workbook(
        inputs, tep, [], {}, project_name="Охват")
    return content


@pytest.fixture(scope="module")
def rich() -> bytes:
    """Все блоки на месте: без них часть ячеек не пишется вовсе."""
    return _build(_BLOCKS)


@pytest.fixture(scope="module")
def plain() -> bytes:
    """Без графиков и лестниц: у объектов работает «доля до РВЭ + остаток»."""
    return _build({})


def _sheets(book: bytes) -> dict[str, str]:
    archive = zipfile.ZipFile(__import__("io").BytesIO(book))
    targets: dict[str, str] = {}
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    for match in re.finditer(r"<Relationship\b([^>]*)/>", rels):
        attrs = match.group(1)
        ident = re.search(r'Id="([^"]+)"', attrs)
        target = re.search(r'Target="([^"]+)"', attrs)
        if ident and target:
            targets[ident.group(1)] = target.group(1)
    out: dict[str, str] = {}
    book_xml = archive.read("xl/workbook.xml").decode("utf-8")
    for name, ident in re.findall(
            r'<(?:x:)?sheet name="([^"]+)"[^>]*?r:id="([^"]+)"', book_xml):
        target = targets.get(ident)
        if not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        out[name] = archive.read(path).decode("utf-8", "replace")
    return out


_CELL = r"\$?([A-Z]{1,3})\$?(\d+)"
_RANGE = re.compile(_CELL + r"\s*:\s*" + _CELL)
_LINK = re.compile(r"\s*'?" + re.escape(ENTRY) + r"'?!\$?([A-Z]{1,3})\$?(\d+)\s*")
_FOREIGN = re.compile(r"'[^']+'!\$?[A-Z]{1,3}\$?\d+(?:\s*:\s*\$?[A-Z]{1,3}\$?\d+)?")


def _mirrors(params_xml: str) -> dict[str, str]:
    """Ячейка «Параметров» → ячейка ввода, которую она зеркалит."""
    found: dict[str, str] = {}
    for match in re.finditer(
            r'<(?:x:)?c r="([A-Z]{1,3}\d+)"[^>]*>(.*?)</(?:x:)?c>', params_xml, re.S):
        coord, body = match.groups()
        formula = re.search(r"<(?:x:)?f>(.*?)</(?:x:)?f>", body, re.S)
        if not formula:
            continue
        link = _LINK.fullmatch(formula.group(1))
        if link:
            found[coord] = f"{link.group(1)}{link.group(2)}"
    return found


def _readers(sheets: dict[str, str]) -> set[str]:
    """Ячейки «Параметров», которые читает хоть одна формула книги."""
    seen: set[str] = set()

    def absorb(expression: str) -> None:
        for span in _RANGE.finditer(expression):
            left, right = sorted((col_index(span.group(1)), col_index(span.group(3))))
            top, bottom = sorted((int(span.group(2)), int(span.group(4))))
            if (right - left + 1) * (bottom - top + 1) > 200_000:
                continue
            for column in range(left, right + 1):
                for row in range(top, bottom + 1):
                    seen.add(f"{get_column_letter(column)}{row}")
        for cell in re.finditer(_CELL, _RANGE.sub(" ", expression)):
            seen.add(f"{cell.group(1)}{cell.group(2)}")

    for name, xml in sheets.items():
        for match in re.finditer(r"<(?:x:)?f>(.*?)</(?:x:)?f>", xml, re.S):
            expression = match.group(1)
            if name == PARAMS:
                # Ссылки самого листа на себя — без имени листа. Чужие срезаем
                # ВМЕСТЕ С АДРЕСОМ: срежь одно имя листа, и «'Вводные'!E113»
                # оставит «E113», который тут же зачтётся за свою ячейку —
                # мёртвая объявится живой. А пропустить всю формулу, где есть
                # хоть одно «!», тоже нельзя: вместе с чужой ссылкой пропадёт
                # соседняя своя, и живая вводная объявится мёртвой.
                absorb(_FOREIGN.sub(" ", expression))
            for piece in re.finditer(
                    r"'?" + re.escape(PARAMS) + r"'?!([^,()+\-*/=<>&]+)", expression):
                absorb(piece.group(1))
    return seen


def _key_at(sheet, row: int, column: int) -> str:
    """Ключ вводной: он стоит СПРАВА от своего значения, в своём же блоке.

    Брать колонку D всегда нельзя: на листе два блока в строку, и у правого
    (J–M) ключ лежит в M. С колонкой D ключ правого блока читался как ключ
    левого — четыре профильные доли получали чужие имена и не попадали под
    своё же исключение.
    """
    for shift in range(1, 5):
        value = sheet.cell(row, column + shift).value
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{3,}", value):
            return value
    return ""


def _orphans(book: bytes) -> list[tuple[str, str, str]]:
    sheets = _sheets(book)
    mirrors = _mirrors(sheets[PARAMS])
    readers = _readers(sheets)
    workbook = openpyxl.load_workbook(__import__("io").BytesIO(book))
    entry = workbook[ENTRY]
    out: list[tuple[str, str, str]] = []
    for mirror, source in sorted(mirrors.items()):
        if mirror in readers:
            continue
        row = int(re.search(r"\d+", source).group(0))
        column = col_index(re.match(r"[A-Z]{1,3}", source).group(0))
        label = (entry.cell(row, 10).value if column > 5
                 else entry.cell(row, 1).value) or entry.cell(row, 1).value or ""
        out.append((source, str(label)[:60], _key_at(entry, row, column),
                    entry[source].value))
    return out


def test_every_engine_input_is_named_in_the_workbook(rich: bytes) -> None:
    """Ключ вводной назван — иначе её негде искать."""
    workbook = openpyxl.load_workbook(__import__("io").BytesIO(rich))
    texts = [cell.value for name in workbook.sheetnames
             for row in workbook[name].iter_rows() for cell in row
             if isinstance(cell.value, str) and cell.value.strip()]
    missing = []
    for key in sorted(core.DEFAULT_INPUTS):
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])")
        if not any(pattern.search(text) for text in texts):
            missing.append(key)
    assert missing == [], f"вводные движка без имени в книге: {missing}"


def test_the_fixture_actually_carries_every_block(rich: bytes) -> None:
    """Предохранитель: без блоков охват меряется на неполной книге.

    Ступени ставки разбираются форматом «покрытие : ставка»; строка не того
    формата даёт пустой список, блока в книге нет, и первая проверка зеленеет
    на книге без него.
    """
    assert core.pf_special_steps(_OBJECTS["pf_special_steps"]), (
        "строка ступеней не разобрана — блока в книге не будет")
    workbook = openpyxl.load_workbook(__import__("io").BytesIO(rich))
    entry = workbook[ENTRY]
    headings = {str(cell.value) for row in entry.iter_rows() for cell in row
                if isinstance(cell.value, str)}
    for block in ("ГРАФИК ПЛАТЕЖЕЙ ЗА ПОКУПКУ", "СТУПЕНИ СТАВКИ ПФ ПО ПОКРЫТИЮ ЭСКРОУ"):
        assert block in headings, f"блока «{block}» в книге нет"


@pytest.mark.parametrize("fixture", ["plain", "rich"])
def test_no_input_cell_is_dead(fixture: str, request: pytest.FixtureRequest) -> None:
    """Жёлтая ячейка, которую никто не читает, — обещание, а не вводная."""
    book = request.getfixturevalue(fixture)
    superseded = PROFILE_SUPERSEDES | LADDER_SUPERSEDES
    dead = [item for item in _orphans(book)
            if not (fixture == "rich" and item[2] in superseded)
            # Подпись единиц модели («млн ₽») пришла из шаблона владельца и
            # стоит в ячейке со стилем ввода. Это надпись, а не вводная: ключа
            # у неё нет и значение не число. Запрещаем МЕСТО, а не вид: числовая
            # ячейка без ключа (так жила денежная компенсация) под исключение
            # не попадает.
            and not (item[2] == "" and isinstance(item[3], str))]
    assert dead == [], (
        "ячейки ввода без единого читателя: "
        + "; ".join(f"{coord} «{label}» {key} = {value!r}"
                    for coord, label, key, value in dead))


def test_the_watchman_would_notice_a_dead_cell(plain: bytes) -> None:
    """Предохранитель: сторож обязан падать на мёртвой ячейке.

    У живой вводной снимаем ВСЕХ читателей разом — не подменой одной формулы
    (её адрес может держать соседний диапазон, и подмена не сработает), а
    вычёркиванием каждой ссылки на неё из всех листов. Не упало бы — сторож
    не значит ничего.
    """
    sheets = _sheets(plain)
    mirrors = _mirrors(sheets[PARAMS])
    alive = sorted(set(mirrors) - {coord for coord, *_rest in _orphans(plain)})
    assert alive, "живых вводных нет — проверять нечего"
    victim = alive[0]
    column, row = re.match(r"([A-Z]{1,3})(\d+)", victim).groups()
    gone = re.compile(r"\$?" + column + r"\$?" + row + r"(?!\d)")
    for name, xml in list(sheets.items()):
        sheets[name] = re.sub(
            r"<(?:x:)?f>(.*?)</(?:x:)?f>",
            lambda m: "<x:f>" + gone.sub("ZZ9999", m.group(1)) + "</x:f>",
            xml, flags=re.S)
    assert victim not in _readers(sheets), (
        f"ссылки на {victim} вычеркнуты, а сторож всё равно считает её "
        "прочитанной — проверка зелена на любом коде")
