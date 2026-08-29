"""Свод продаж презентацией: слайд — раздел отчёта, и его можно править.

«Страниц PDF = слайд или раздел PDF = слайд» (владелец, 27.08.2026). Разделы и
страницы у нас совпадают — раздел свода печатается со своей страницы, — поэтому
вопрос решён одним ответом: слайд отвечает разделу.

Первая версия клала на слайд СНИМОК раздела. Владелец: «этот отчёт в
редактируемом виде нужен отделу продаж, картинка никому не уперлась»
(29.08.2026). Картинку нельзя ни поправить перед встречей, ни пересобрать под
свой шаблон — а именно это с колодой и делают.

Значит на слайде настоящие объекты PowerPoint: заголовок, вывод текстом,
таблица ячейками, график с данными. И вот чего при этом делать нельзя:
собирать их «по тем же данным» из свода. Это была бы вторая реализация отчёта о
продажах — она разошлась бы с экраном молча, и обе выглядели бы верными (так
уже расходились бот с сайтом, отчёт с книгой и книга с движком).

Поэтому колода собирается из ТОЙ ЖЕ разметки, которой печатается PDF: каждое
число слайда буквально взято из строки экрана. Считать здесь нечего и нечем —
в модуле нет ни одного имени величины свода, и это проверяется тестом. График
строится из своей же таблицы, а не считается заново: разойтись им негде.
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from typing import Any

# Слайд 16:9. Дюймы, потому что в них считает сам формат.
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
# Строк таблицы на слайде. Тринадцать месяцев в одну таблицу влезают, дальше
# таблица продолжается на следующем слайде: ужать её до нечитаемого — не то же
# самое, что поместить.
ROWS_PER_SLIDE = 13
# Текстовых строк раздела на слайде. Раздел, у которого таблицы нет вовсе
# (полосы долей), живёт своими подписями — они и есть его числа.
LINES_PER_SLIDE = 10


class DeckUnavailable(RuntimeError):
    """Колода не собралась. Это ответ, а не повод отдать пустой файл."""


class _Sections(HTMLParser):
    """Разбор печатной разметки свода на разделы, таблицы и строки.

    Разметка своя, поэтому разбираем её сами: чужой библиотеки ради десятка
    тегов в образ не возим. Промах здесь не «пустой слайд», а слайд без
    половины чисел, поэтому пустой разбор объявляется отказом выше.
    """

    _SKIP = {"script", "style", "button", "textarea", "select", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self.head: dict[str, Any] = {"title": "", "lines": [], "tables": [], "note": ""}
        self.tail: dict[str, Any] = {"title": "На чём посчитано", "lines": [],
                                     "tables": [], "note": ""}
        self._current = self.head
        self._kv_depth = 0
        self._kv_row: list[str] | None = None
        self._skip_depth = 0
        self._svg_depth = 0
        self._cell: list[str] | None = None
        self._row: list[str] | None = None
        self._table: dict[str, Any] | None = None
        self._text: list[str] = []
        self._in_head_cell = False
        self._want: str = ""

    # --- служебное -----------------------------------------------------
    def _flush_line(self) -> None:
        line = re.sub(r"\s+", " ", "".join(self._text)).strip()
        self._text = []
        if not line:
            return
        if self._want == "title" and not self._current["title"]:
            self._current["title"] = line
            return
        if self._want == "note":
            self._current["note"] = line
            return
        self._current["lines"].append(line)

    # --- разбор --------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if tag == "svg":
            self._svg_depth += 1
            return
        if self._svg_depth:
            return
        if tag in self._SKIP or "noprint" in classes or "salesnav" in classes:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if self._kv_depth:
            self._kv_depth += 1
            if self._kv_depth == 2:
                self._flush_line()
                self._kv_row = []
            elif self._kv_depth == 3:
                self._flush_line()
            return
        if tag == "div" and "kv" in classes.split():
            # Плашка ключевых чисел: имя, число и пояснение под ним. Россыпью
            # текстовых строк они на слайде наезжали друг на друга и читались
            # как обрывки; таблицей — читаются и правятся.
            self._flush_line()
            self._kv_depth = 1
            self._table = {"head": ["Показатель", "Значение", "Пояснение"], "rows": []}
            return
        if tag == "section" and "salesblock" in classes:
            self._flush_line()
            self._current = {"title": "", "lines": [], "tables": [], "note": ""}
            self.sections.append(self._current)
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self._flush_line()
            self._want = "title"
            return
        if tag == "div" and "sumup" in classes:
            self._flush_line()
            self._want = "note"
            return
        if tag == "table":
            self._flush_line()
            self._table = {"head": [], "rows": []}
            return
        if tag == "tr" and self._table is not None:
            self._row = []
            return
        if tag in {"td", "th"} and self._table is not None:
            self._cell = []
            self._in_head_cell = tag == "th"
            return
        if tag in {"br", "p", "div", "li", "summary"}:
            self._flush_line()

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
            return
        if self._svg_depth:
            return
        if self._skip_depth:
            if tag in self._SKIP or tag == "div":
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in {"td", "th"} and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
            return
        if tag == "tr" and self._table is not None and self._row is not None:
            if self._in_head_cell and not self._table["head"]:
                self._table["head"] = self._row
            elif any(cell for cell in self._row):
                self._table["rows"].append(self._row)
            self._row = None
            self._in_head_cell = False
            return
        if tag == "table" and self._table is not None:
            if self._table["rows"]:
                self._current["tables"].append(self._table)
            self._table = None
            return
        if self._kv_depth:
            if self._kv_depth == 3 and self._kv_row is not None:
                line = re.sub(r"\s+", " ", "".join(self._text)).strip()
                self._text = []
                self._kv_row.append(line)
            elif self._kv_depth == 2 and self._kv_row is not None:
                if any(cell for cell in self._kv_row) and self._table is not None:
                    self._table["rows"].append(self._kv_row[:3])
                self._kv_row = None
            self._kv_depth -= 1
            if self._kv_depth == 0 and self._table is not None:
                if self._table["rows"]:
                    self._current["tables"].append(self._table)
                self._table = None
            return
        if tag == "section":
            self._flush_line()
            self._current = self.tail
            self._want = ""
            return
        if tag in {"h1", "h2", "h3", "h4", "p", "div", "li", "summary"}:
            self._flush_line()
            self._want = ""

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._svg_depth:
            return
        if self._cell is not None:
            self._cell.append(data)
            return
        self._text.append(data)

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush_line()


def sections(html: str) -> list[dict[str, Any]]:
    """Разделы печатной разметки: заголовок, вывод, строки и таблицы."""
    parser = _Sections()
    parser.feed(html)
    parser.close()
    # Лист «На чём посчитано» существует, только когда на нём что-то есть:
    # заголовок у него наш, и пустой он выдал бы пустую колоду за собранную.
    tail = [parser.tail] if (parser.tail["lines"] or parser.tail["tables"]) else []
    out = [parser.head] + parser.sections + tail
    kept = [item for item in out if item["lines"] or item["tables"] or item["note"]]
    if not kept:
        raise DeckUnavailable("В разметке свода не нашлось ни одного раздела")
    return kept


_NUMBER = re.compile(r"^-?\d[\d  ]*(?:[.,]\d+)?$")


def cell_number(text: str) -> float | None:
    """Число из ячейки таблицы — целиком или никак.

    «3 306 021» уже читалось с середины в ценах рынка и во второй раз в
    комментариях CRM; здесь ячейка либо число целиком, либо не число.
    Проценты и суммы с подписями числом не считаются: график по колонке
    «5,00%» и по колонке «млн ₽» — разные графики.
    """
    raw = str(text or "").strip().replace("−", "-")
    if not raw or not _NUMBER.match(raw):
        return None
    try:
        return float(raw.replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def chart_data(table: dict[str, Any]) -> dict[str, Any] | None:
    """Категории и один ряд для графика — из той же таблицы, что на слайде.

    Ряд один и берётся первой числовой колонкой. Класть на одну ось рубли,
    метры и цену метра нельзя: столбик в пиксель рядом со столбиком во весь
    слайд читается как «этого нет», а не как «этого мало». Какая колонка
    нарисована — сказано подписью под графиком; остальные стоят числами в
    таблице на следующем слайде, и график в PowerPoint перестраивается по ним
    руками: он настоящий, а не картинка.

    Колонка берётся, только если КАЖДАЯ её ячейка — число: прочерк посередине
    нарисовал бы ноль там, где значения нет, а «пропуск — не ноль» мы уже
    проходили на плане банка.
    """
    head, rows = table.get("head") or [], table.get("rows") or []
    if len(head) < 2 or len(rows) < 2:
        return None
    categories = [str(row[0]) for row in rows if row]
    for index in range(1, len(head)):
        values = [cell_number(row[index]) if index < len(row) else None for row in rows]
        if len(values) != len(categories) or any(value is None for value in values):
            continue
        return {"categories": categories, "name": str(head[index]),
                "series": [(str(head[index]), [float(value) for value in values])]}
    return None


def build(pages: list[dict[str, Any]], *, title: str, subtitle: str, footer: str) -> bytes:
    """Колода из разобранных разделов. Ни одного числа здесь не считается."""
    try:
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
        from pptx.util import Inches, Pt
    except ImportError as exc:  # noqa: BLE001
        raise DeckUnavailable(
            "В образе нет python-pptx — презентацию собрать нечем") from exc
    if not pages:
        raise DeckUnavailable("Собирать нечего: в своде нет ни одного раздела")

    deck = Presentation()
    deck.slide_width = Inches(SLIDE_W_IN)
    deck.slide_height = Inches(SLIDE_H_IN)
    blank = deck.slide_layouts[6]
    ink = RGBColor(0x16, 0x20, 0x2B)
    dim = RGBColor(0x5B, 0x6B, 0x7D)

    def textbox(slide, text: str, *, top: float, size: int, colour: RGBColor,
                bold: bool = False, height: float = 0.6):
        box = slide.shapes.add_textbox(Inches(0.6), Inches(top),
                                       Inches(SLIDE_W_IN - 1.2), Inches(height))
        frame = box.text_frame
        frame.word_wrap = True
        run = frame.paragraphs[0].add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = colour
        return box

    def new_slide(heading: str):
        slide = deck.slides.add_slide(blank)
        textbox(slide, heading, top=0.42, size=24, colour=ink, bold=True)
        return slide

    def put_table(slide, table: dict[str, Any], *, top: float, height: float) -> None:
        head = table.get("head") or []
        rows = table.get("rows") or []
        columns = max([len(head)] + [len(row) for row in rows]) or 1
        shape = slide.shapes.add_table(len(rows) + (1 if head else 0), columns,
                                       Inches(0.6), Inches(top),
                                       Inches(SLIDE_W_IN - 1.2), Inches(height))
        grid = shape.table
        offset = 0
        if head:
            for index in range(columns):
                cell = grid.cell(0, index)
                cell.text = str(head[index]) if index < len(head) else ""
                cell.text_frame.paragraphs[0].runs[0].font.size = Pt(11)
                cell.text_frame.paragraphs[0].runs[0].font.bold = True
            offset = 1
        for line, row in enumerate(rows):
            for index in range(columns):
                cell = grid.cell(line + offset, index)
                cell.text = str(row[index]) if index < len(row) else ""
                paragraph = cell.text_frame.paragraphs[0]
                if paragraph.runs:
                    paragraph.runs[0].font.size = Pt(11)

    def put_chart(slide, data: dict[str, Any], *, top: float, height: float) -> None:
        payload = CategoryChartData()
        payload.categories = data["categories"]
        for name, values in data["series"]:
            payload.add_series(name, values)
        frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(top),
            Inches(SLIDE_W_IN - 1.2), Inches(height), payload)
        chart = frame.chart
        chart.has_legend = len(data["series"]) > 1
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False

    # Титул: чей отчёт и на какую дату. Слайд, отделившийся от колоды, обязан
    # сам говорить, чей он, — как лист на бумаге.
    first = deck.slides.add_slide(blank)
    textbox(first, title, top=2.6, size=34, colour=ink, bold=True, height=1.0)
    textbox(first, subtitle, top=3.9, size=16, colour=dim)
    textbox(first, footer, top=6.6, size=11, colour=dim)

    for page in pages:
        heading = str(page.get("title") or "Раздел")
        tables = list(page.get("tables") or [])
        note = str(page.get("note") or "").strip()
        lines = [line for line in (page.get("lines") or []) if line][:LINES_PER_SLIDE]
        drawn = chart_data(tables[0]) if tables else None

        slide = new_slide(heading)
        top = 1.25
        if note:
            textbox(slide, note, top=top, size=14, colour=dim, height=0.8)
            top += 0.9
        if drawn:
            put_chart(slide, drawn, top=top, height=SLIDE_H_IN - top - 1.05)
            textbox(slide, f"На графике колонка «{drawn['name']}»; остальные числа —"
                           " таблицей на следующем слайде. График настоящий: данные"
                           " правятся в PowerPoint.",
                    top=SLIDE_H_IN - 0.95, size=11, colour=dim, height=0.4)
        elif lines:
            for index, line in enumerate(lines):
                textbox(slide, line, top=top + index * 0.42, size=13, colour=ink)
        elif tables:
            put_table(slide, tables[0], top=top, height=min(4.8, 0.34 * (len(tables[0]["rows"]) + 1)))
            tables = tables[1:]

        # Таблицы — целиком и ячейками: их и правят. Длинная продолжается
        # следующим слайдом, а не ужимается до нечитаемого.
        for table in tables:
            rows = table.get("rows") or []
            for start in range(0, len(rows), ROWS_PER_SLIDE):
                chunk = {"head": table.get("head") or [],
                         "rows": rows[start:start + ROWS_PER_SLIDE]}
                part = new_slide(heading + ("" if start == 0 else " · продолжение"))
                put_table(part, chunk, top=1.25,
                          height=min(5.6, 0.34 * (len(chunk["rows"]) + 1)))
        if note:
            slide.notes_slide.notes_text_frame.text = note

    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def file_name(title: str) -> str:
    """Имя файла: то же правило, что у PDF отчёта."""
    keep = "".join(ch for ch in title if ch.isalnum() or ch in " -_")[:80].strip()
    return re.sub(r"\s+", " ", keep) or "sales"
