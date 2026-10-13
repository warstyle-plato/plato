"""XML-помощники книги v4: буквы и номера колонок, помесячная сетка, ячейки
и строки листа, лист ввода и пути листов внутри zip, кассовые доли очередей.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_xml")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

def _v4_column_letter(number: int) -> str:
    letters = ""
    while number > 0:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _v4_column_number(letters: str) -> int:
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - 64
    return number


def _v4_row_xml(row: int, cells: list[str]) -> str:
    """Собирает строку листа, расставляя ячейки по возрастанию колонки.

    Excel требует от ячеек строки возрастающего порядка ссылок и молча
    выбрасывает те, что стоят после старшей колонки. Блок раздачи налога
    писал `A B C D E F G L M N O P H I J K` — и в Excel колонки «Налог О1…О4»
    оказывались ПУСТЫМИ, а «Итого» под ними нулём: чистая прибыль ОТЧЁТа шла
    без налога на прибыль (на четырёх очередях 56 598,6 вместо 42 128,6 при
    налоге 14 470,0). Наш вычислитель читает ячейки по координате и порядка
    не замечает — то есть книга и проверки расходились молча, а поймал это
    владелец глазами (14.09.2026).

    Поэтому строку собирает эта функция, а не конкатенация в порядке
    написания кода: порядок ячеек — свойство файла, а не порядка вычислений.
    """
    ordered = sorted(cells, key=lambda cell: _v4_column_number(
        re.match(r'<x:c r="([A-Z]+)', cell).group(1)))
    return f'<x:row r="{row}">' + "".join(ordered) + "</x:row>"


# Ширина помесячной сетки книги объявлена ЗДЕСЬ и больше нигде. Прежде тот же
# факт стоял в трёх видах — этой константой, числом `_V4_CAPEX_MONTH_COLUMNS`
# и одиннадцатью литералами `$DS$` внутри f-строк, — и протянуть книгу со 120
# месяцев до 180 значило найти все три копии. Цена промаха измерена: на четырёх
# очередях с шагом 36 горизонт движка 163 месяца, а книга обрезала его до 120 и
# собиралась МОЛЧА — CAPEX 36 769 против 49 085 млн ₽, EBITDA 190 против 2 701.
_V4_CF_FIRST_COL = 4                 # D
_V4_CF_LAST_COL = 183                # GA — 180 месяцев
_V4_LAST_COLUMN = _v4_column_letter(_V4_CF_LAST_COL)
_V4_MONTH_COLUMNS = _V4_CF_LAST_COL - _V4_CF_FIRST_COL + 1


def _v4_month_span(row: int, sheet: str = "") -> str:
    """Диапазон «весь горизонт» по строке листа: `$D$37:$GA$37`."""
    prefix = f"'{sheet}'!" if sheet else ""
    return f"{prefix}$D${row}:${_V4_LAST_COLUMN}${row}"


def _v4_cell_formula(xml: str, coord: str) -> str | None:
    """Формула ячейки как есть. Нет ячейки или нет формулы — `None`.

    Читается затем, чтобы правку строить НА НЕЙ, а не писать свою рядом: свою
    пришлось бы держать в согласии с шаблоном вручную, и она разошлась бы молча.
    """
    found = re.search(
        r'<x:c r="%s"[^>]*>(.*?)</x:c>' % re.escape(coord), xml, re.S)
    if not found:
        return None
    formula = re.search(r"<x:f>(.*?)</x:f>", found.group(1), re.S)
    return html.unescape(formula.group(1)) if formula else None


def _v4_col_number(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch) - 64)
    return number


def _v4_set_or_insert_cell(
    xml: str, coord: str, *, number: Any = None, text: str | None = None,
    formula: str | None = None,
) -> tuple[str, bool]:
    """Пишет в ячейку, а если её в XML нет — вставляет на своё место в строке.

    Пустых ячеек в файле не существует, и `_v4_set_cell` умеет только заменять
    существующую. Новая колонка (кассовые доли общепроектных статей) поэтому
    молча не записывалась. Порядок колонок внутри строки обязан расти, иначе
    Excel вправе счесть лист повреждённым.
    """
    updated, done = _v4_set_cell(xml, coord, number=number, text=text, formula=formula)
    if done:
        return updated, True
    letters = re.match(r"([A-Z]+)(\d+)", coord)
    if not letters:
        return xml, False
    column, row = letters.group(1), letters.group(2)
    row_pattern = re.compile(r'(<x:row r="%s"[^>]*>)(.*?)(</x:row>)' % row, re.S)
    found = row_pattern.search(xml)
    if not found:
        return xml, False
    if formula is not None:
        cell = f'<x:c r="{coord}"><x:f>{xml_escape(formula)}</x:f></x:c>'
    elif text is not None:
        cell = (f'<x:c r="{coord}" t="inlineStr">'
                f"<x:is><x:t>{xml_escape(str(text))}</x:t></x:is></x:c>")
    else:
        cell = f'<x:c r="{coord}"><x:v>{_v4_number(number)}</x:v></x:c>'
    body = found.group(2)
    insert_at = len(body)
    for existing in re.finditer(r'<x:c r="([A-Z]+)%s"' % row, body):
        if _v4_col_number(existing.group(1)) > _v4_col_number(column):
            insert_at = existing.start()
            break
    new_body = body[:insert_at] + cell + body[insert_at:]
    return (xml[:found.start()] + found.group(1) + new_body + found.group(3)
            + xml[found.end():]), True


_V4_ROW_CELL_RE = re.compile(r'<x:c r="([A-Z]{1,3})(\d+)"[^>]*?(?:/>|>.*?</x:c>)', re.S)


def _v4_row_formulas(xml: str, row: int) -> dict[str, str]:
    """Формулы всей строки за один проход по листу.

    Обратная сторона `_v4_set_cells`: читать ячейку за ячейкой так же дорого,
    как писать. Блок паркинга объектов читал 120 месяцев по четырём строкам в
    четырёх блоках — почти пять тысяч проходов по мегабайтному листу, и сборка
    книги подорожала с 3,2 до 15,0 секунды. Платил за это весь набор: книгу
    собирают 34 файла проверок, и полный прогон на CI вырос с 40 минут до 74.
    """
    found = re.search(
        r'<x:row r="%d"[^>]*?(?:/>|>(?P<body>.*?)</x:row>)' % row, xml, re.S)
    if not found:
        return {}
    out: dict[str, str] = {}
    for cell in _V4_ROW_CELL_RE.finditer(found.group("body") or ""):
        formula = re.search(r"<x:f>(.*?)</x:f>", cell.group(0), re.S)
        if formula:
            out[cell.group(1) + cell.group(2)] = html.unescape(formula.group(1))
    return out


def _v4_set_cells(xml: str, row: int, cells: dict[str, dict[str, Any]],
                  styles: dict[str, str | None] | None = None) -> tuple[str, bool]:
    """Пишет пачку ячеек ОДНОЙ строки за один проход по листу.

    Каждая ячейка искалась регуляркой по всему XML листа. У строки сноса и
    строки процентов ВРИ таких ячеек 120 на блок, блоков четыре, строк четыре —
    и сборка книги подорожала с 6,3 до 11,2 секунды, а вместе с ней весь набор
    тестов: он перестал укладываться в сорок пять минут CI. Лист теперь
    трогается один раз на строку, а не один раз на ячейку.
    """
    found = re.search(
        r'<x:row r="%d"(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</x:row>)' % row, xml, re.S)
    if not found:
        return xml, False
    body = found.group("body") or ""
    kept: dict[str, str] = {}
    for cell in _V4_ROW_CELL_RE.finditer(body):
        kept[cell.group(1) + cell.group(2)] = cell.group(0)
    styles = styles or {}
    for coord, payload in cells.items():
        style = styles.get(coord)
        if style is None:
            previous = kept.get(coord)
            got = re.search(r'\ss="(\d+)"', previous) if previous else None
            style = got.group(1) if got else None
        attr = f' s="{style}"' if style else ""
        if payload.get("formula") is not None:
            rendered = f'<x:c r="{coord}"{attr}><x:f>{xml_escape(payload["formula"])}</x:f></x:c>'
        elif payload.get("text") is not None:
            rendered = (f'<x:c r="{coord}"{attr} t="inlineStr">'
                        f'<x:is><x:t>{xml_escape(str(payload["text"]))}</x:t></x:is></x:c>')
        else:
            rendered = f'<x:c r="{coord}"{attr}><x:v>{_v4_number(payload.get("number"))}</x:v></x:c>'
        kept[coord] = rendered
    order = sorted(kept, key=lambda c: _v4_col_number(re.match(r"[A-Z]+", c).group(0)))
    rebuilt = f'<x:row r="{row}"{found.group("attrs") or ""}>' + "".join(
        kept[coord] for coord in order) + "</x:row>"
    return xml[:found.start()] + rebuilt + xml[found.end():], True


def _v4_ensure_row(xml: str, row: int) -> str:
    """Создаёт пустую строку листа, если её в XML нет вовсе.

    Пустых строк в файле не существует, а «Вводные» держат между блоками зазоры —
    и добавка группы обязана вставать в СВОЙ блок, а не в конец листа (решение
    владельца, 03.09.2026: править объект, листая от одной его половины к другой,
    нельзя). Строка вставляется на своё место по возрастанию номера: Excel вправе
    счесть лист повреждённым, если порядок нарушен, и это уже ловится тестом.
    """
    if re.search(r'<x:row r="%d"[ />]' % row, xml):
        return xml
    for existing in re.finditer(r'<x:row r="(\d+)"', xml):
        if int(existing.group(1)) > row:
            return xml[:existing.start()] + f'<x:row r="{row}"></x:row>' + xml[existing.start():]
    tail = "</x:sheetData>"
    assert tail in xml
    return xml.replace(tail, f'<x:row r="{row}"></x:row>' + tail, 1)


def _v4_note_cell(xml: str, value_coord: str, text: str) -> tuple[str, bool]:
    """Пишет примечание в колонку E строки ячейки ``value_coord``.

    Пустых E-ячеек в XML шаблона нет, поэтому при отсутствии ячейка
    вставляется в строку — на своё место по порядку колонок, иначе Excel
    вправе отбросить лист как повреждённый.
    """
    row = re.sub(r"[A-Z]+", "", value_coord)
    coord = f"E{row}"
    updated, done = _v4_set_cell(xml, coord, text=text)
    if done:
        return updated, True
    row_pattern = re.compile(r'(<x:row r="%s"[^>]*>)(.*?)(</x:row>)' % row, re.S)
    found = row_pattern.search(xml)
    if not found:
        return xml, False
    cell = (f'<x:c r="{coord}" t="inlineStr">'
            f"<x:is><x:t>{xml_escape(text)}</x:t></x:is></x:c>")
    body = found.group(2)
    insert_at = len(body)
    for existing in re.finditer(r'<x:c r="([A-Z]+)%s"' % row, body):
        if _v4_col_number(existing.group(1)) > _v4_col_number("E"):
            insert_at = existing.start()
            break
    new_body = body[:insert_at] + cell + body[insert_at:]
    return (xml[:found.start()] + found.group(1) + new_body + found.group(3)
            + xml[found.end():]), True


# Лист ввода дописывается в книгу как новый файл: имя занято своим,
# отношение и тип содержимого объявляются рядом. Переиспользовать чужой номер
# нельзя — шаблон нумерует листы своими sheetN.xml.
_V4_ENTRY_SHEET_PATH = "xl/worksheets/sheetEntry.xml"
_V4_ENTRY_REL_ID = "RidEntryInputs0001"
_V4_GUIDE_SHEET_PATH = "xl/worksheets/sheetGuide.xml"
_V4_GUIDE_REL_ID = "RidEntryGuide0001"


def _v4_workbook_with_entry(workbook: str, add: bool) -> str:
    """Переименовать расчётный лист и поставить лист ввода первым.

    Первым — потому что с него начинают: книга открывается там, где печатают.
    А расчётный лист уходит за отчёт: печатать в нём больше нечего, и вторым
    он занимал бы место того, ради чего книгу открывают («книгу открывают ради
    отчёта, а он лежал пятнадцатым листом»). Порядок листов ничего не ломает:
    формулы ссылаются по именам, а не по позиции.
    """
    workbook = re.sub(r'(<x:sheet name=")%s(")' % re.escape(v4_entry_sheet.ENTRY_SHEET),
                      lambda m: m.group(1) + v4_entry_sheet.PARAMS_SHEET + m.group(2),
                      workbook, count=1)
    if not add:
        return workbook
    workbook = _v4_sheet_moved_behind(workbook, v4_entry_sheet.PARAMS_SHEET, "Дашборд")
    namespace = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    # Инструкция стоит второй — сразу за листом, о котором она. Первой её
    # ставить нельзя: книгу открывают, чтобы печатать, а не читать инструкцию,
    # и первый лист — тот, с которого начинают работу.
    guide = (f'<x:sheet name="{v4_entry_sheet.GUIDE_SHEET}" sheetId="901" '
             f'r:id="{_V4_GUIDE_REL_ID}" {namespace} />')
    entry = (f'<x:sheet name="{v4_entry_sheet.ENTRY_SHEET}" sheetId="900" '
             f'r:id="{_V4_ENTRY_REL_ID}" {namespace} />')
    return workbook.replace("<x:sheets>", "<x:sheets>" + entry + guide, 1)


def _v4_sheet_moved_behind(workbook: str, name: str, after: str) -> str:
    """Переставить лист за другой. Не нашли — оставить как есть.

    Молча переставить не тот лист хуже, чем не переставить: порядок читают
    глазами, и проверка на него стоит отдельно.
    """
    moved = re.search(r'<x:sheet name="%s"[^>]*/>' % re.escape(name), workbook)
    anchor = re.search(r'<x:sheet name="%s"[^>]*/>' % re.escape(after), workbook)
    if not moved or not anchor or moved.start() > anchor.start():
        return workbook
    without = workbook[:moved.start()] + workbook[moved.end():]
    anchor = re.search(r'<x:sheet name="%s"[^>]*/>' % re.escape(after), without)
    if not anchor:
        return workbook
    return without[:anchor.end()] + moved.group(0) + without[anchor.end():]


def _v4_rels_with_entry(rels: str) -> str:
    links = "".join(
        '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="/' + path + '" ' + f'Id="{rel}" />'
        for path, rel in ((_V4_ENTRY_SHEET_PATH, _V4_ENTRY_REL_ID),
                          (_V4_GUIDE_SHEET_PATH, _V4_GUIDE_REL_ID)))
    return rels.replace("</Relationships>", links + "</Relationships>", 1)


def _v4_types_with_entry(types: str) -> str:
    overrides = "".join(
        '<Override PartName="/' + path + '" ContentType='
        '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml" />'
        for path in (_V4_ENTRY_SHEET_PATH, _V4_GUIDE_SHEET_PATH))
    return types.replace("</Types>", overrides + "</Types>", 1)


def _v4_sheet_path(archive: zipfile.ZipFile, name: str) -> str:
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    sheet = re.search(r'<x:sheet name="%s"[^>]*r:id="([^"]+)"' % re.escape(name), workbook)
    if not sheet:
        raise RuntimeError(f"в книге v4 нет листа «{name}»")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rel = re.search(r'Target="([^"]+)"[^>]*Id="%s"' % re.escape(sheet.group(1)), rels) \
        or re.search(r'Id="%s"[^>]*Target="([^"]+)"' % re.escape(sheet.group(1)), rels)
    if not rel:
        raise RuntimeError(f"лист «{name}» не найден в связях книги v4")
    target = rel.group(1)
    return "xl/" + target.lstrip("/").removeprefix("xl/")


def _v4_sheet_names_by_path(archive: zipfile.ZipFile) -> dict[str, str]:
    """Путь листа в архиве -> его имя в книге.

    Продление сетки решается по ИМЕНИ листа, а имя лежит в `workbook.xml`:
    угадывать его по номеру файла нельзя — порядок `sheetN.xml` в шаблоне
    имени не соответствует (CF_4 лежит в sheet19.xml).
    """
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets = {match.group(2): match.group(1) for match in re.finditer(
        r'Target="([^"]+)"[^>]*?Id="([^"]+)"', rels)}
    targets.update({match.group(1): match.group(2) for match in re.finditer(
        r'Id="([^"]+)"[^>]*?Target="([^"]+)"', rels)})
    out: dict[str, str] = {}
    for match in re.finditer(r'<x:sheet name="([^"]+)"[^>]*?r:id="([^"]+)"', workbook):
        target = targets.get(match.group(2))
        if target:
            out["xl/" + target.lstrip("/").removeprefix("xl/")] = match.group(1)
    return out


def _v4_inputs_sheet_path(archive: zipfile.ZipFile) -> str:
    return _v4_sheet_path(archive, "Вводные")


def _v4_normalized(weights: list[float], count: int) -> list[float]:
    """Веса очередей в долях единицы. Страница хранит их в процентах
    ([40, 32, 28]); записанные как есть, они раздували ГНС очереди в
    сорок раз. Нормировка на сумму принимает оба формата."""
    total = sum(weights[:count])
    return [w / total for w in weights[:count]]


def _v4_fold_tail(weights: list[float], enabled: int, book: int) -> list[float]:
    """Очередей больше, чем листов CF в книге: хвост сливается в последнюю
    книжную очередь, а не размазывается по всем — объёмы четвёртой очереди
    ближе по срокам к третьей, чем к первой."""
    trimmed = weights[:enabled]
    if enabled > book and len(trimmed) >= book:
        trimmed = trimmed[:book - 1] + [sum(trimmed[book - 1:])]
    return trimmed
