"""Протянуть помесячную сетку книги v4 вправо.

Шаблон кончается колонкой DS — 120 месяцев, — а горизонт движка длиннее: на
четырёх очередях с шагом 36 это 163 месяца. Книга при этом собиралась МОЛЧА и
теряла хвост: CAPEX 36 769 против 49 085 млн ₽ у движка.

Методику это не трогает: последняя колонка размножается вправо ровно так же,
как её протянул бы Excel, — относительные ссылки едут, абсолютные стоят. Что
собрать формулы заново нельзя, записано в правилах проекта: 73 104 формулы
шаблона — методика владельца.

Правила выведены ЗАМЕРОМ по самому шаблону, а не придуманы:
  * колонка X = колонка X−1 со сдвигом ОТНОСИТЕЛЬНЫХ колонок на +1 — совпало
    на всех 11 листах сетки, кроме строк заголовка месяца и счётчика периода;
  * у строки заголовка месяца двигается и абсолютная колонка
    (`'Ставки'!$DS$3`), поэтому там сдвигаются все ссылки;
  * счётчик периода — число, а не формула: растёт на единицу;
  * диапазон, кончающийся на последней колонке, — это «весь горизонт», и его
    конец переезжает; вертикальный диапазон ВНУТРИ колонки (`DS12:DS14`) едет
    вместе с колонкой, а окно последних месяцев (`DQ6:DS6`) двигается целиком.

Экранирование XML не трогаем вовсе: формулы правятся ровно так, как лежат в
файле. Раскодировать и закодировать обратно значит однажды написать сущность
там, где её не было, — так и вышло на первом заходе: `"` уехал в `&quot;` на
37 495 формулах, книга открылась, а вычислитель упал.

Приёмка — сверка со старым шаблоном по каждой формуле: у первой протяжки со
120 до 180 месяцев 66 006 формул не изменились, у 7 039 переехал конец
диапазона, у 59 и то и другое в одной формуле.

    python3 scripts/widen_v4_horizon.py templates/DevelopAid_model_v4.xlsx 180
"""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

from openpyxl.utils import column_index_from_string as ci, get_column_letter as gl

CELL = re.compile(r'<x:c r="([A-Z]{1,3})(\d+)"(.*?)(?:/>|>(.*?)</x:c>)', re.S)
REF = re.compile(r'(\$?)([A-Z]{1,3})(\$?)(\d+)')
# Строковый литерал формулы: в XML шаблона кавычка встречается и как символ,
# и как сущность `&quot;` — оба вида надо обойти, иначе сдвиг полезет в текст.
STRING = re.compile(r'"[^"]*"|&quot;(?:(?!&quot;).)*&quot;', re.S)
ROW = re.compile(r'<x:row r="(\d+)"([^>]*)>(.*?)</x:row>', re.S)


def _shift(formula: str, by: int, *, absolute_too: bool = False) -> str:
    """Сдвинуть ссылки формулы на `by` колонок. Строковые литералы не трогаем."""
    out, last = [], 0
    for match in STRING.finditer(formula):
        out.append(_shift_plain(formula[last:match.start()], by, absolute_too))
        out.append(match.group(0))
        last = match.end()
    out.append(_shift_plain(formula[last:], by, absolute_too))
    return "".join(out)


def _shift_plain(chunk: str, by: int, absolute_too: bool) -> str:
    def swap(match: re.Match[str]) -> str:
        dollar_col, col, dollar_row, row = match.groups()
        if dollar_col and not absolute_too:
            return match.group(0)
        return f"{dollar_col}{gl(ci(col) + by)}{dollar_row}{row}"
    return REF.sub(swap, chunk)


def _last_month_column(sheet_xml: str) -> int:
    """Последняя колонка сетки: самая правая, где вообще есть ячейка."""
    return max((ci(col) for col, _, _, _ in CELL.findall(sheet_xml)), default=0)


def _month_header_row(sheet_xml: str, last: int) -> int | None:
    """Строка, где стоит дата месяца: её ячейка последней колонки ссылается на
    строку 3 листа «Ставки». У «Ставок» это своя строка 3 с EDATE."""
    letter = gl(last)
    for col, row, _, body in CELL.findall(sheet_xml):
        if col != letter or not body:
            continue
        formula = re.search(r"<x:f>(.*?)</x:f>", body, re.S)
        if not formula:
            continue
        text = formula.group(1)
        if "Ставки" in text and re.search(r"\$?[A-Z]{1,3}\$?3\b", text):
            return int(row)
        if "EDATE(" in text and text.endswith(",1)"):
            return int(row)
    return None


def _counter_row(sheet_xml: str, last: int, months: int) -> int | None:
    """Строка счётчика периода: номер месяца, равный ширине сетки.

    В шаблоне он лежит формулой из одного числа (`<x:f>120</x:f>`), а не
    значением, — искать надо оба вида, иначе счётчик размножится константой.
    """
    letter = gl(last)
    for col, row, _, body in CELL.findall(sheet_xml):
        if col != letter or not body:
            continue
        for pattern in (r"<x:f>(-?\d+)</x:f>", r"<x:v>(-?\d+)</x:v>"):
            found = re.search(pattern, body)
            if found and int(found.group(1)) == months:
                return int(row)
    return None


def _clone_columns(sheet_xml: str, last: int, extra: int,
                   header_row: int | None, counter_row: int | None,
                   months: int) -> str:
    """Размножить последнюю колонку сетки вправо."""
    letter = gl(last)

    def widen_row(match: re.Match[str]) -> str:
        row_number, attrs, body = int(match.group(1)), match.group(2), match.group(3)
        source = None
        for cell in CELL.finditer(body):
            if cell.group(1) == letter:
                source = cell
        if source is None:
            return match.group(0)
        head, inner = source.group(3), source.group(4)
        made = []
        for step in range(1, extra + 1):
            column = gl(last + step)
            if inner is None:
                made.append(f'<x:c r="{column}{row_number}"{head}/>')
                continue
            piece = inner
            if row_number == counter_row:
                piece = re.sub(r"(<x:[fv]>)-?\d+(</x:[fv]>)",
                               rf"\g<1>{months + step}\g<2>", piece)
            else:
                formula = re.search(r"<x:f>(.*?)</x:f>", piece, re.S)
                if formula:
                    moved = _shift(formula.group(1), step,
                                   absolute_too=(row_number == header_row))
                    piece = piece[:formula.start(1)] + moved + piece[formula.end(1):]
                # Значение прошлого пересчёта к новой колонке отношения не имеет.
                piece = re.sub(r"<x:v>.*?</x:v>", "", piece, flags=re.S)
            made.append(f'<x:c r="{column}{row_number}"{head}>{piece}</x:c>')
        return f'<x:row r="{row_number}"{attrs}>{body}{"".join(made)}</x:row>'

    return ROW.sub(widen_row, sheet_xml)


# Экранирование не трогаем: формулы правятся ровно так, как лежат в XML.
# Раскодировать и закодировать обратно значит однажды написать сущность там,
# где её не было, — так и вышло: `"` уехал в `&quot;` на 37 495 формулах.
# Ссылки при этом узнаются и в экранированном тексте: имена сущностей
# (`lt`, `gt`, `amp`, `quot`) строчные, а ссылка требует заглавных.


RANGE = re.compile(
    r"((?:'[^']+'!)?)(\$?)([A-Z]{1,3})(\$?)(\d+)(\s*:\s*)((?:'[^']+'!)?)(\$?)([A-Z]{1,3})(\$?)(\d+)")


def _retarget(formula: str, sheet: str, grid: dict[str, int],
              widened: dict[str, int], in_band: bool) -> str:
    """Перевести ссылки на прежнюю последнюю колонку в новую.

    Диапазон от D (или E — так считается NPV со второго месяца) до последней
    колонки означает «весь горизонт»: переезжает конец. Вертикальный диапазон
    внутри одной колонки не трогаем — он уехал вместе с колонкой. Окно
    последних месяцев двигается целиком, иначе «последний квартал» станет
    «последние сорок шесть месяцев».
    """
    spans: list[tuple[int, int]] = []

    def move_range(match: re.Match[str]) -> str:
        (s1, d1, c1, r1d, r1, sep, s2, d2, c2, r2d, r2) = match.groups()
        # Двигает КОЛОНКА ТОГО ЛИСТА, на который ссылаются, а не того, где
        # стоит формула: «Консолидатор», «Отчёт», «Дашборд» и «Проверки» сеткой
        # не являются вовсе, и их сдвиг равен нулю — а читают они её всю.
        target = _sheet_of(s2 or s1, sheet)
        last = grid.get(target)
        if last is None or ci(c2) != last:
            return match.group(0)
        spans.append(match.span())
        if c1 == c2:                      # внутри одной колонки — уже переехал
            return match.group(0)
        wide = widened[target]
        if ci(c1) <= ci("E"):             # весь горизонт: двигаем только конец
            head = f"{s1}{d1}{c1}{r1d}{r1}{sep}{s2}{d2}"
            return f"{head}{gl(wide)}{r2d}{r2}"
        # окно, привязанное к концу: двигаем оба края
        return (f"{s1}{d1}{gl(ci(c1) + wide - last)}{r1d}{r1}{sep}"
                f"{s2}{d2}{gl(wide)}{r2d}{r2}")

    moved = RANGE.sub(move_range, formula)
    if in_band:
        # У ячейки сетки одиночная ссылка на последнюю колонку — это её
        # собственная колонка: она уже уехала при размножении.
        return moved

    def move_single(match: re.Match[str]) -> str:
        if any(start <= match.start() < end for start, end in spans):
            return match.group(0)
        qualifier, dollar_col, col, dollar_row, row = match.groups()
        target = _sheet_of(qualifier, sheet)
        last = grid.get(target)
        if last is None or ci(col) != last:
            return match.group(0)
        return f"{qualifier}{dollar_col}{gl(widened[target])}{dollar_row}{row}"

    spans = [m.span() for m in RANGE.finditer(moved)]
    return re.sub(r"((?:'[^']+'!)?)(\$?)([A-Z]{1,3})(\$?)(\d+)", move_single, moved)


def _sheet_of(qualifier: str, current: str) -> str:
    return qualifier.strip("!").strip("'") if qualifier else current


def _widen_cols(head: str, last: int, extra: int) -> str:
    """Ширины новых колонок — те же, что у последней месячной."""
    entries = re.findall(r'<x:col min="(\d+)" max="(\d+)"([^>]*)/>', head)
    source = None
    for low, high, rest in entries:
        if int(low) <= last <= int(high):
            source = rest
    if source is None:
        return head
    made = "".join(f'<x:col min="{last + step}" max="{last + step}"{source}/>'
                   for step in range(1, extra + 1))
    return head.replace("</x:cols>", made + "</x:cols>", 1)


def _widen_merges(xml: str, last: int, extra: int) -> str:
    """Шапка листа объединена по всей сетке — растягиваем вместе с ней."""
    letter, wider = gl(last), gl(last + extra)
    return re.sub(rf'(<x:mergeCell ref="[A-Z]{{1,3}}\d+:){letter}(\d+" />)',
                  rf'\g<1>{wider}\g<2>', xml)


def widen(path: Path, months: int, out: Path) -> dict[str, tuple[int, int]]:
    """Протянуть сетку месяцев до `months` и записать книгу в `out`."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import main_legacy as core
    import openpyxl

    source = zipfile.ZipFile(path)
    book = openpyxl.load_workbook(path)
    paths = {name: core._v4_sheet_path(source, name) for name in book.sheetnames}
    raw = {name: source.read(paths[name]).decode("utf-8") for name in book.sheetnames}

    # Лист сетки — тот, где месяцы идут колонками до самого края.
    grid = {name: _last_month_column(xml)
            for name, xml in raw.items() if _last_month_column(xml) >= 100}
    if not grid:
        raise SystemExit("сетка месяцев не найдена — шаблон не тот")

    report: dict[str, tuple[int, int]] = {}
    grown: dict[str, str] = {}
    for name, xml in raw.items():
        last = grid.get(name)
        if last is None:
            grown[name] = xml
            continue
        # «Сроки» сдвинуты на колонку: там месяц начинается с E.
        offset = 4 if name == "СРОКИ" else 3
        have = last - offset
        extra = months - have
        report[name] = (have, months)
        if extra <= 0:
            grown[name] = xml
            continue
        at = xml.index("<x:sheetData>")
        head, body = _widen_cols(xml[:at], last, extra), xml[at:]
        body = _clone_columns(body, last, extra,
                              _month_header_row(xml, last),
                              _counter_row(xml, last, have), have)
        grown[name] = _widen_merges(head + body, last, extra)

    # Ссылки на прежнюю последнюю колонку переводим ПОСЛЕ размножения: у новых
    # колонок относительные ссылки уже уехали, а абсолютные окна — нет.
    final: dict[str, str] = {}
    for name, xml in grown.items():
        widened = {sheet: last + months - (last - (4 if sheet == "СРОКИ" else 3))
                   for sheet, last in grid.items()}
        band = grid.get(name)

        def fix(match: re.Match[str]) -> str:
            column, row, head, inner = match.groups()
            if inner is None:
                return match.group(0)
            formula = re.search(r"<x:f>(.*?)</x:f>", inner, re.S)
            if not formula:
                return match.group(0)
            in_band = band is not None and 4 <= ci(column) <= widened[name]
            moved = _retarget(formula.group(1), name, grid, widened, in_band)
            inner = inner[:formula.start(1)] + moved + inner[formula.end(1):]
            return f'<x:c r="{column}{row}"{head}>{inner}</x:c>'

        final[name] = CELL.sub(fix, xml)

    # Пишем рядом и подменяем в конце: `out` может быть тем же файлом, и
    # писать в него, пока читаем, значит остаться без шаблона на полпути.
    beside = out.with_name(out.name + ".widened")
    with zipfile.ZipFile(path) as src:
        by_path = {paths[name]: xml for name, xml in final.items()}
        with zipfile.ZipFile(beside, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename in by_path:
                    data = by_path[item.filename].encode("utf-8")
                dst.writestr(item, data)
    beside.replace(out)
    return report


if __name__ == "__main__":
    template = Path(sys.argv[1] if len(sys.argv) > 1
                    else "templates/DevelopAid_model_v4.xlsx")
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else template
    for sheet, (was, now) in widen(template, months, out).items():
        print(f"  {sheet:<14} {was} → {now} месяцев")
