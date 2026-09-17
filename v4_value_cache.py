"""Сохранённые значения книги: число рядом с формулой, а не вместо неё.

Книга v4 — это 121 691 формула и почти ни одного числа. Excel пересчитывает её
при открытии (`fullCalcOnLoad="1"`) и показывает всё; а предпросмотр в
телеграме, Quick Look на маке, просмотр на телефоне, Google Drive и Яндекс.Диск
формул не считают и читают только сохранённые значения. Их в книге не было ни
одного с 02.08.2026 — сборщик стирал их регуляркой на каждом листе, — и во всех
этих окнах книга выглядела ПУСТОЙ. Решение стереть было верным по доводу: смесь
старых трёхочередных значений с пустыми клонами четвёртой очереди выдавала бы
непосчитанную книгу за посчитанную. Не была названа цена, и платилась она сорок
два дня, пока владелец не открыл выгрузку и не сказал «модель пустая вообще».

Поэтому здесь не «вернуть как было», а третий ответ: значение СЧИТАЕТСЯ нашим
же вычислителем и кладётся рядом с живой формулой. Это не хардкод — правило про
число на месте формулы запрещает удалять формулу, а `<v>` рядом с `<f>` и есть
штатное представление Excel. Устареть кэш не может: `fullCalcOnLoad` заставляет
Excel пересчитать всё при открытии, то есть числу верят ровно те, кто считать
не умеет, и ровно до первого открытия в Excel.

Три границы, и каждая про то, что соврать кэшем хуже, чем промолчать:

* формула, которую вычислитель не понял или которая дала ошибку, остаётся БЕЗ
  значения, а не получает ноль — пустая клетка честна, ноль нет;
* сколько таких клеток, говорится вслух (`report["unresolved"]` уезжает в
  `missing` сборщика): молчаливый пропуск неотличим от посчитанной пустоты;
* строки и логические значения несут свой тип (`t="str"`, `t="b"`), иначе Excel
  прочитает текст как число и покажет не то, что посчитано.

Запуск проверок: python3 -m pytest tests/test_the_workbook_is_not_empty_in_a_viewer.py -q
"""

from __future__ import annotations

import datetime as _dt
import io
import re
import zipfile
from typing import Any

import openpyxl

from xlsx_eval import Evaluator

# Ячейка листа целиком: имя, атрибуты, содержимое. Пространство имён у шаблона
# есть не везде (`<c>` и `<x:c>` встречаются оба), поэтому префикс необязателен.
# Ячейка бывает пустой и пишется одним тегом: `<x:c r="B8" s="113" />`.
# Прежний образец допускал косую черту, но всё равно требовал тело и
# закрывающий тег — и на пустой ячейке съедал СЛЕДУЮЩУЮ за ней: match начинался
# на `B8`, а тело захватывало `C8` целиком. Ссылкой считался `B8`, значения для
# него нет, и ячейка `C8` оставалась без сохранённого значения. Цена — пустые
# итоги в любом просмотрщике, который не считает формулы: «Итого очередь 1»,
# «ИТОГО ЖИЛЫЕ ОЧЕРЕДИ» и «ИТОГО ПРОЕКТ» листа ТЭП стоят ровно за пустыми
# ячейками. Поэтому пустая ячейка — своя ветка образца, а не «необязательная
# косая черта».
_CELL = re.compile(
    r"<(?P<ns>x:)?c(?P<attrs>\s[^>]*?)?"
    r"(?:/>|>(?P<body>(?:(?!</(?:x:)?c>).)*)</(?:x:)?c>)",
    re.S,
)
_HAS_FORMULA = re.compile(r"<(?:x:)?f[\s/>]")
_OLD_VALUE = re.compile(r"<(?:x:)?v>.*?</(?:x:)?v>", re.S)
_REF = re.compile(r'\br="([A-Z]+\d+)"')
_TYPE = re.compile(r'\st="[^"]*"')

# Нулевой день книги Excel — тот же, что у вычислителя.
_EXCEL_EPOCH = _dt.date(1899, 12, 30)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _rendered(value: Any) -> tuple[str, str] | None:
    """Значение и тип ячейки — или None, если класть нечего.

    None и пустая строка значения не получают: у формулы, вернувшей пустоту,
    Excel и сам рисует пустую клетку, а `<v></v>` он считает повреждением.
    """
    if value is None or value is Ellipsis:
        return None
    if isinstance(value, bool):
        return ("1" if value else "0", "b")
    if isinstance(value, _dt.datetime):
        value = value.date()
    if isinstance(value, _dt.date):
        return (f"{(value - _EXCEL_EPOCH).days:d}", "")
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        # Repr float'а Excel читает без потерь, а лишние нули в файле не нужны.
        return (repr(int(number)) if number.is_integer() and abs(number) < 1e15
                else repr(number), "")
    text = str(value)
    return (_escape(text), "str") if text else None


def _sheet_with_values(xml: str, values: dict[str, Any]) -> tuple[str, int, int]:
    """Прописать значения в XML одного листа. Возвращает текст, сколько и сколько не смог."""
    written = skipped = 0

    def one(match: re.Match[str]) -> str:
        nonlocal written, skipped
        whole = match.group(0)
        body = match.group("body")
        if body is None or not _HAS_FORMULA.search(body):
            # Пустая ячейка формулы не несёт — и соседнюю больше не трогает.
            return whole
        attrs = match.group("attrs") or ""
        ref_match = _REF.search(attrs)
        if not ref_match:
            return whole
        rendered = _rendered(values.get(ref_match.group(1), Ellipsis))
        if rendered is None:
            skipped += 1
            return whole
        text, kind = rendered
        ns = match.group("ns") or ""
        # Прежнее значение снимается целиком: их не бывает больше одного, а
        # оставленное рядом с новым Excel считает повреждением файла.
        body = _OLD_VALUE.sub("", body)
        attrs = _TYPE.sub("", attrs)
        if kind:
            attrs = f'{attrs} t="{kind}"'
        written += 1
        return f"<{ns}c{attrs}>{body}<{ns}v>{text}</{ns}v></{ns}c>"

    return _CELL.sub(one, xml), written, skipped


def _sheet_paths(source: zipfile.ZipFile) -> dict[str, str]:
    """Путь листа в архиве → его имя, по связям книги.

    Порядком это не решается, и проверено дорого: в собранной книге 21 лист и
    19 файлов `sheetN.xml` — ввод и инструкцию сборщик кладёт своими путями, —
    а номер в имени файла не совпадает с местом листа в книге. Сопоставление
    «по порядку» молча писало значения ОДНОГО листа в ячейки ДРУГОГО: числа на
    вид настоящие, лист чужой. Имя и связь объявляет сама книга, её и читаем.
    """
    book_xml = source.read("xl/workbook.xml").decode("utf-8")
    rels_xml = source.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    # Атрибуты читаются по имени, а не по порядку: в шаблоне `Target` стоит
    # ПЕРЕД `Id`, а у листа `r:id` после `name` — образец, требующий порядка,
    # молча не находит ничего и отдаёт пустую карту, то есть «значений нет».
    targets = {}
    for tag in re.finditer(r"<Relationship\b[^>]*>", rels_xml):
        attrs = _attrs(tag.group(0))
        if attrs.get("Id") and attrs.get("Target"):
            targets[attrs["Id"]] = attrs["Target"]
    out: dict[str, str] = {}
    for tag in re.finditer(r"<(?:x:)?sheet\b[^>]*>", book_xml):
        attrs = _attrs(tag.group(0))
        target = targets.get(attrs.get("r:id") or attrs.get("id") or "")
        name = attrs.get("name")
        if not target or not name:
            continue
        # Адрес бывает абсолютным («/xl/worksheets/sheet14.xml») и относительным
        # («worksheets/sheet3.xml») — от папки книги. В архиве он лежит без
        # ведущей косой черты.
        path = target.lstrip("/") if target.startswith("/") else (
            target if target.startswith("xl/") else "xl/" + target)
        out[path] = _unescape(name)
    return out


def _attrs(tag: str) -> dict[str, str]:
    return {m.group(1): _unescape(m.group(2))
            for m in re.finditer(r'([A-Za-z_:][\w.:-]*)="([^"]*)"', tag)}


def _unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))


def with_cached_values(content: bytes) -> tuple[bytes, dict[str, Any]]:
    """Пересчитать книгу и положить значения рядом с формулами.

    Отдаёт новые байты и отчёт: сколько значений записано, сколько формул
    вычислитель не осилил и что это были за формулы. Любой сбой оставляет книгу
    ровно такой, какой она пришла: выгрузка без значений хуже, чем с ними, но
    несобранная выгрузка хуже обеих.
    """
    report: dict[str, Any] = {"written": 0, "unresolved": 0, "examples": []}
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    evaluator = Evaluator(book)
    values: dict[str, dict[str, Any]] = {}
    for sheet in book.worksheets:
        computed: dict[str, Any] = {}
        for row in sheet.iter_rows():
            for cell in row:
                formula = cell.value
                if not (isinstance(formula, str) and formula.startswith("=")):
                    continue
                try:
                    computed[cell.coordinate] = evaluator.cell(sheet.title, cell.coordinate)
                except Exception as exc:  # noqa: BLE001 — непонятая формула молчит, а не врёт
                    report["unresolved"] += 1
                    if len(report["examples"]) < 5:
                        report["examples"].append(
                            f"{sheet.title}!{cell.coordinate}: {type(exc).__name__}")
        values[sheet.title] = computed

    source = zipfile.ZipFile(io.BytesIO(content))
    by_path = _sheet_paths(source)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            payload = source.read(item.filename)
            title = by_path.get(item.filename)
            if title is not None and values.get(title):
                text, written, _ = _sheet_with_values(
                    payload.decode("utf-8"), values[title])
                report["written"] += written
                payload = text.encode("utf-8")
            archive.writestr(item, payload)
    source.close()
    return out.getvalue(), report
