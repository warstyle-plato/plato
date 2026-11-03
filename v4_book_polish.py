"""Оформление готовой книги v4: то, что читатель видит, а формулы не меняют.

Решения владельца по ревизии книги 29.09.2026 (docs/excel_book_audit_2026-09-29.md):

* книга открывается на Дашборде, итоги впереди: Дашборд → ОТЧЕТ → Вводные →
  ИНСТРУКЦИЯ → расчётные листы → ПРОВЕРКИ → Источники;
* объекты и очереди, которых нет в проекте, скрыты — строки и листы, а не
  удалены: на них ссылаются формулы, и включённый потом в Excel объект
  вернётся, стоит показать строки;
* на листах с месяцами закреплены подписи и шапка, у итоговых листов задана
  печать; итог в «млн ₽» не выглядит как «37266,16417», флаг 0/1 — как «100%».

Проход работает над байтами собранной книги и ничего не знает о проекте: что
скрыть, решает сборщик (`hidden_rows`, `hidden_sheets`), и каждую строку он
называет подписью. Подпись не совпала — строка НЕ скрывается, а расхождение
уходит в `missing`: спрятать не ту строку хуже, чем показать лишнюю.

Формулы здесь не трогаются вовсе — только стили, атрибуты строк и листов.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Iterable

import v4_entry_sheet as ves

# Листы с помесячной сеткой: подписи в A–C, шапка — строки 3 (месяц) и 4 (№).
MONTHLY_SHEETS = ("Ставки", "Продажи", "ВРИ", "CAPEX", "CF_1", "CF_2", "CF_3", "CF_4",
                  "CF", "КРЕДИТЫ", "ОБЪЕКТЫ")
FREEZE = {**{name: "D5" for name in MONTHLY_SHEETS},
          "ОТЧЕТ": "A3", "ТЭП": "A4", "ПРОВЕРКИ": "A6"}
# Листы-таблицы, которые печатают: альбом, в ширину одной страницы.
PRINT_FIT = ("ОТЧЕТ", "ТЭП", "ПРОВЕРКИ", "Источники")

ORDER = ("Дашборд", "ОТЧЕТ", "Вводные", "ИНСТРУКЦИЯ", "Параметры модели", "ТЭП",
         "СРОКИ", "Ставки", "Продажи", "ВРИ", "CAPEX", "CF_1", "CF_2", "CF_3", "CF_4",
         "CF", "КРЕДИТЫ", "КОНСОЛИДАТОР", "ОБЪЕКТЫ", "ПРОВЕРКИ", "Источники",
         "Dashboard_Data")
FIRST_SHEET = "Дашборд"

_AMOUNT = "#,##0.0;[Red](#,##0.0);-"
_AREA = "#,##0;[Red](#,##0);-"
_PCT = "0.0%;[Red](0.0%);-"
# Единица строки (колонка C помесячного листа) → семейство и код формата.
UNIT_FORMATS: dict[str, tuple[str, str]] = {
    "млн ₽": ("number", _AMOUNT),
    "м²": ("number", _AREA),
    "шт.": ("number", _AREA),
    "тыс. ₽/м²": ("number", _AMOUNT),
    "тыс. ₽/шт.": ("number", _AMOUNT),
    "%": ("pct", _PCT),
    "% год": ("pct", _PCT),
}
# Флаг 0/1 в формате процента читается «100,0%»; General и «0» его не портят.
FLAG_UNITS = ("0/1", "0 / 1")
_FLAG = "0"

# Подпись «Очередь финансирования» обещала 1–3, а очередей четыре; проверка
# ввода на «Параметрах модели» и так разрешает 1, 2, 3, 4.
TEXT_FIXES = {"1–3": "1–4"}

_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Ключи API на листе ввода (колонки D, H, M блоков вводных). Скрыть колонку
# целиком нельзя: в D стоят сценарная таблица и даты соцобъектов. Поэтому ключ
# гасится — серым мелким шрифтом: для сверки он есть, глаз по нему не цепляется.
KEY_SHEET = "Вводные"
KEY_COLUMNS = ("D", "H", "M")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_KEY_HEADER = "Ключ API"
_KEY_FONT = '<x:font><x:sz val="8"/><x:color rgb="FFA6A6A6"/><x:name val="Carlito"/></x:font>'


def _font_id(styles: str, font: str) -> tuple[str, int]:
    block = re.search(r'<x:fonts count="(\d+)"[^>]*>(.*?)</x:fonts>', styles, re.S)
    fonts = re.findall(r"<x:font>.*?</x:font>|<x:font/>", block.group(2), re.S)
    if font in fonts:
        return styles, fonts.index(font)
    head = block.group(0)[:block.group(0).index(">") + 1]
    head = re.sub(r'count="\d+"', f'count="{len(fonts) + 1}"', head)
    new = head + block.group(2) + font + "</x:fonts>"
    return styles[:block.start()] + new + styles[block.end():], len(fonts)


def _xf_with_font(styles: str, xf_id: int, font_id: int) -> tuple[str, int]:
    block, items = ves._xf_items(styles)
    base = items[xf_id]
    clone = (re.sub(r'fontId="\d+"', f'fontId="{font_id}"', base, count=1)
             if 'fontId="' in base else base.replace("<x:xf ", f'<x:xf fontId="{font_id}" ', 1))
    clone = (re.sub(r'applyFont="\d"', 'applyFont="1"', clone)
             if "applyFont" in clone else clone.replace("<x:xf ", '<x:xf applyFont="1" ', 1))
    for index, item in enumerate(items):
        if item == clone:
            return styles, index
    items.append(clone)
    new_block = f'<x:cellXfs count="{len(items)}">{"".join(items)}</x:cellXfs>'
    return styles[:block.start()] + new_block + styles[block.end():], len(items) - 1


def _quiet_keys(xml: str, styles: str, strings: list[str]) -> tuple[str, str]:
    styles, font = _font_id(styles, _KEY_FONT)
    cache: dict[int, int] = {}

    def fix(cell: "re.Match[str]") -> str:
        nonlocal styles
        column, row, attrs, rest = cell.group(1), cell.group(2), cell.group(3), cell.group(4)
        text = _unescape(ves.cell_text(attrs, rest, strings)).strip()
        if not (_KEY.match(text) or text == _KEY_HEADER):
            return cell.group(0)
        style = re.search(r'\ss="(\d+)"', attrs)
        xf = int(style.group(1)) if style else 0
        if xf not in cache:
            styles, cache[xf] = _xf_with_font(styles, xf, font)
        attrs = (re.sub(r'\ss="\d+"', f' s="{cache[xf]}"', attrs) if style
                 else attrs + f' s="{cache[xf]}"')
        return f'<x:c r="{column}{row}"{attrs}{rest}'

    columns = "|".join(KEY_COLUMNS)
    xml = re.sub(rf'<x:c r="({columns})(\d+)"([^>]*?)(/>|>.*?</x:c>)', fix, xml, flags=re.S)
    return xml, styles


def _sheet_paths(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets = {}
    for rel in re.findall(r"<Relationship\b[^>]*>", rels):
        rid = re.search(r'Id="([^"]+)"', rel)
        target = re.search(r'Target="([^"]+)"', rel)
        if rid and target:
            path = target.group(1).lstrip("/")
            targets[rid.group(1)] = path if path.startswith("xl/") else "xl/" + path
    out = {}
    for tag in re.findall(r"<x:sheet\b[^>]*>", workbook):
        name = re.search(r'name="([^"]+)"', tag).group(1)
        rid = re.search(r'r:id="([^"]+)"', tag).group(1)
        out[_unescape(name)] = targets[rid]
    return out


def _unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&apos;", "'").replace("&amp;", "&"))


# --- лист -----------------------------------------------------------------

def _freeze(xml: str, cell: str) -> str:
    column = re.match(r"[A-Z]+", cell).group(0)
    row = int(cell[len(column):])
    x_split = _col_index(column) - 1
    y_split = row - 1
    attrs = []
    if x_split:
        attrs.append(f'xSplit="{x_split}"')
    if y_split:
        attrs.append(f'ySplit="{y_split}"')
    pane_name = ("bottomRight" if x_split and y_split else
                 "bottomLeft" if y_split else "topRight")
    pane = (f'<x:pane {" ".join(attrs)} topLeftCell="{cell}" '
            f'activePane="{pane_name}" state="frozen"/>')
    view = re.search(r"<x:sheetView\b([^>]*?)(/?)>", xml)
    if not view:
        return xml
    if view.group(2) == "/":
        replacement = f"<x:sheetView{view.group(1)}>{pane}</x:sheetView>"
        return xml[:view.start()] + replacement + xml[view.end():]
    end = xml.index("</x:sheetView>", view.end())
    inner = re.sub(r"<x:pane\b[^>]*/>", "", xml[view.end():end])
    inner = re.sub(r"<x:selection\b[^>]*/>", "", inner)
    return xml[:view.end()] + pane + inner + xml[end:]


def _col_index(letters: str) -> int:
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - 64
    return number


_AFTER_PAGE_SETUP = ("headerFooter", "rowBreaks", "colBreaks", "customProperties",
                     "cellWatches", "ignoredErrors", "smartTags", "drawing",
                     "legacyDrawing", "legacyDrawingHF", "picture", "oleObjects",
                     "controls", "webPublishItems", "tableParts", "extLst")


def _insert_before(xml: str, names: Iterable[str], piece: str) -> str:
    positions = [m.start() for name in names
                 for m in [re.search(rf"<x:{name}\b", xml)] if m]
    at = min(positions) if positions else xml.rindex("</x:worksheet>")
    return xml[:at] + piece + xml[at:]


def _print_fit(xml: str) -> str:
    """Альбомная печать в ширину одной страницы."""
    setup = '<x:pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
    if re.search(r"<x:pageSetup\b", xml):
        xml = re.sub(r"<x:pageSetup\b[^>]*/>", setup, xml, count=1)
    else:
        if not re.search(r"<x:pageMargins\b", xml):
            xml = _insert_before(xml, ("pageSetup",) + _AFTER_PAGE_SETUP,
                                 '<x:pageMargins left="0.4" right="0.4" top="0.5" '
                                 'bottom="0.5" header="0.3" footer="0.3"/>')
        xml = _insert_before(xml, _AFTER_PAGE_SETUP, setup)
    fit = '<x:pageSetUpPr fitToPage="1"/>'
    pr = re.search(r"<x:sheetPr\b([^>]*?)(/?)>", xml)
    if not pr:
        start = re.search(r"<x:worksheet\b[^>]*>", xml)
        return xml[:start.end()] + f"<x:sheetPr>{fit}</x:sheetPr>" + xml[start.end():]
    if "pageSetUpPr" in xml[pr.start():xml.find("</x:sheetPr>", pr.start()) + 1 or pr.end()]:
        return xml
    if pr.group(2) == "/":
        return xml[:pr.start()] + f"<x:sheetPr{pr.group(1)}>{fit}</x:sheetPr>" + xml[pr.end():]
    # pageSetUpPr идёт после tabColor и outlinePr — последним ребёнком.
    end = xml.index("</x:sheetPr>", pr.end())
    return xml[:end] + fit + xml[end:]


def _hide_rows(xml: str, sheet: str, rows: list[tuple[int, str, str]],
               strings: list[str], missing: list[str]) -> str:
    for row, column, label in rows:
        found = re.search(rf'<x:row r="{row}"([^>]*?)(/?)>', xml)
        if not found:
            # Пустая строка блока в файле не существует — скрывать нечего.
            # Строка с подписью обязана быть: её отсутствие и есть расхождение.
            if label:
                missing.append(f"{sheet}!{row}: строки нет — не скрыта")
            continue
        text = _cell_text(xml, f"{column}{row}", strings)
        if not text.startswith(label):
            missing.append(f"{sheet}!{column}{row}: ждали «{label}», стоит «{text}» — строка не скрыта")
            continue
        attrs = re.sub(r'\shidden="\d"', "", found.group(1))
        xml = xml[:found.start()] + f'<x:row r="{row}"{attrs} hidden="1"{found.group(2)}>' \
            + xml[found.end():]
    return xml


def _cell_text(xml: str, coord: str, strings: list[str]) -> str:
    found = re.search(rf'<x:c r="{coord}"([^>]*?)(?:/>|>(.*?)</x:c>)', xml, re.S)
    if not found:
        return ""
    return _unescape(ves.cell_text(found.group(1), found.group(2) or "", strings))


def _unit_formats(xml: str, styles: str, strings: list[str]) -> tuple[str, str, int]:
    """Формат числа по единице строки: B и месячные клетки D:GA."""
    changed = 0
    cache: dict[tuple[int, str], int] = {}
    # Семейство формата по стилю: разбор всего styles.xml на каждую из тысяч
    # месячных клеток стоил минуты. Стиль шаблона от правки не меняется —
    # новые стили дописываются в конец, — поэтому ответ можно помнить.
    families: dict[int, str] = {}

    def family_of(xf: int) -> str:
        if xf not in families:
            families[xf] = ves.format_family(ves.format_code(styles, ves.num_fmt_id(styles, xf)))
        return families[xf]

    def fix_row(match: "re.Match[str]") -> str:
        nonlocal styles, changed
        row_xml = match.group(0)
        row = match.group(1)
        unit = _cell_text(row_xml, f"C{row}", strings).strip()
        if unit in FLAG_UNITS:
            family, code = "flag", _FLAG
        elif unit in UNIT_FORMATS:
            family, code = UNIT_FORMATS[unit]
        else:
            return row_xml

        def fix_cell(cell: "re.Match[str]") -> str:
            nonlocal styles, changed
            column, attrs, rest = cell.group(1), cell.group(2), cell.group(3)
            if column in ("A", "C"):
                return cell.group(0)
            if "<x:f" not in rest and "<x:v>" not in rest:
                return cell.group(0)
            style = re.search(r'\ss="(\d+)"', attrs)
            xf = int(style.group(1)) if style else 0
            current = family_of(xf)
            wrong = current == "pct" if family == "flag" else current != family
            if not wrong:
                return cell.group(0)
            key = (xf, code)
            if key not in cache:
                styles, fmt = ves.with_format(styles, code)
                styles, cache[key] = ves.xf_with_format(styles, xf, fmt)
            new_attrs = (re.sub(r'\ss="\d+"', f' s="{cache[key]}"', attrs) if style
                         else attrs + f' s="{cache[key]}"')
            changed += 1
            return f'<x:c r="{column}{row}"{new_attrs}{rest}'

        return re.sub(rf'<x:c r="([A-Z]+){row}"([^>]*?)(/>|>.*?</x:c>)', fix_cell,
                      row_xml, flags=re.S)

    xml = re.sub(r'<x:row r="(\d+)"[^>]*>.*?</x:row>', fix_row, xml, flags=re.S)
    return xml, styles, changed


def _text_fixes(xml: str) -> str:
    for old, new in TEXT_FIXES.items():
        xml = xml.replace(f'<x:v>{old}</x:v>', f'<x:v>{new}</x:v>')
        xml = xml.replace(f'<x:t>{old}</x:t>', f'<x:t>{new}</x:t>')
    return xml


def _untab(xml: str, selected: bool) -> str:
    view = re.search(r"<x:sheetView\b[^>]*>", xml)
    if not view:
        return xml
    tag = re.sub(r'\stabSelected="\d"', "", view.group(0))
    if selected:
        tag = tag.replace("<x:sheetView", '<x:sheetView tabSelected="1"', 1)
    return xml[:view.start()] + tag + xml[view.end():]


# --- книга ----------------------------------------------------------------

def _workbook(xml: str, hidden: set[str], print_titles: dict[str, str]) -> str:
    sheets = re.search(r"<x:sheets>(.*?)</x:sheets>", xml, re.S)
    tags = re.findall(r"<x:sheet\b[^>]*/>", sheets.group(1))
    by_name = {_unescape(re.search(r'name="([^"]+)"', t).group(1)): t for t in tags}
    ordered = [name for name in ORDER if name in by_name]
    ordered += [name for name in by_name if name not in ordered]
    out = []
    for name in ordered:
        tag = by_name[name]
        if name in hidden and 'state="' not in tag:
            # Атрибут — в конец тега, как у скрытого Dashboard_Data: читатели
            # книги ищут `<x:sheet name=` подряд, и лист с state впереди имени
            # для них исчезал вместе со своими формулами.
            tag = re.sub(r"\s*/>$", ' state="hidden" />', tag)
        out.append(tag)
    xml = xml[:sheets.start(1)] + "".join(out) + xml[sheets.end(1):]
    first = ordered.index(FIRST_SHEET) if FIRST_SHEET in ordered else 0
    view = f'<x:bookViews><x:workbookView activeTab="{first}"/></x:bookViews>'
    if "<x:bookViews>" in xml:
        xml = re.sub(r"<x:bookViews>.*?</x:bookViews>", view, xml, flags=re.S)
    else:
        xml = xml.replace("<x:sheets>", view + "<x:sheets>", 1)
    # Сквозные строки печати: шапка месяцев и подписи строк на каждой странице.
    names = []
    for name, ref in print_titles.items():
        if name in ordered:
            quoted = name.replace("'", "''")
            areas = ",".join(f"'{quoted}'!{part}" for part in ref.split(","))
            names.append(f'<x:definedName name="_xlnm.Print_Titles" '
                         f'localSheetId="{ordered.index(name)}">{areas}</x:definedName>')
    if names:
        if "<x:definedNames>" in xml:
            xml = xml.replace("</x:definedNames>", "".join(names) + "</x:definedNames>", 1)
        else:
            xml = xml.replace("</x:sheets>", "</x:sheets><x:definedNames>"
                              + "".join(names) + "</x:definedNames>", 1)
    return xml


def polish(content: bytes, *, hidden_rows: dict[str, list[tuple[int, str, str]]] | None = None,
           hidden_sheets: Iterable[str] = (), missing: list[str] | None = None) -> bytes:
    """Оформляет собранную книгу. Сбой листа — в `missing`, лист остаётся как был."""
    missing = missing if missing is not None else []
    hidden_rows = hidden_rows or {}
    hidden = set(hidden_sheets)
    source = zipfile.ZipFile(io.BytesIO(content))
    paths = _sheet_paths(source)
    by_path = {path: name for name, path in paths.items()}
    strings = (ves.shared_strings(source.read("xl/sharedStrings.xml").decode("utf-8"))
               if "xl/sharedStrings.xml" in source.namelist() else [])
    styles = source.read("xl/styles.xml").decode("utf-8")
    for name in hidden_rows:
        if name not in paths:
            missing.append(f"оформление: листа «{name}» нет — строки не скрыты")
    for name in hidden - set(paths):
        missing.append(f"оформление: листа «{name}» нет — не скрыт")

    sheets: dict[str, str] = {}
    for path, name in by_path.items():
        xml = source.read(path).decode("utf-8")
        try:
            if name in FREEZE:
                xml = _freeze(xml, FREEZE[name])
            if name in PRINT_FIT:
                xml = _print_fit(xml)
            if name in MONTHLY_SHEETS:
                xml, styles, _changed = _unit_formats(xml, styles, strings)
            if name in hidden_rows:
                xml = _hide_rows(xml, name, hidden_rows[name], strings, missing)
            if name == KEY_SHEET:
                xml, styles = _quiet_keys(xml, styles, strings)
            xml = _text_fixes(xml)
            xml = _untab(xml, name == FIRST_SHEET)
        except Exception as exc:  # noqa: BLE001 — лист без оформления лучше несобранной книги
            missing.append(f"оформление листа «{name}»: {type(exc).__name__}: {exc}")
            xml = source.read(path).decode("utf-8")
        sheets[path] = xml

    titles = {name: "$A:$C,$3:$4" for name in MONTHLY_SHEETS}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename in sheets:
                payload = sheets[item.filename].encode("utf-8")
            elif item.filename == "xl/styles.xml":
                payload = styles.encode("utf-8")
            elif item.filename == "xl/workbook.xml":
                payload = _workbook(payload.decode("utf-8"), hidden, titles).encode("utf-8")
            archive.writestr(item, payload)
    source.close()
    return out.getvalue()
