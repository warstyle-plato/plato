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


def charts(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Графики таблицы: по одному на числовую колонку.

    Класть рубли, метры и цену метра на одну ось нельзя — столбик в пиксель
    рядом со столбиком во весь слайд читается как «этого нет». Первая версия
    решала это выбором одной колонки и подписью, какая нарисована; владелец
    (29.08.2026): «не проще для каждого графика свой слайд сделать?» — проще, и
    ничего не теряется: каждая мера показана, ни одна не спорит с соседней, а
    лишний слайд в PowerPoint удаляют одним нажатием.

    Колонка берётся, только если КАЖДАЯ её ячейка — число: прочерк посередине
    нарисовал бы ноль там, где значения нет, а «пропуск — не ноль» мы уже
    проходили на плане банка.
    """
    head, rows = table.get("head") or [], table.get("rows") or []
    if len(head) < 2 or len(rows) < 2:
        return []
    categories = [str(row[0]) for row in rows if row]
    out: list[dict[str, Any]] = []
    for index in range(1, len(head)):
        values = [cell_number(row[index]) if index < len(row) else None for row in rows]
        if len(values) != len(categories) or any(value is None for value in values):
            continue
        out.append({"name": str(head[index]), "categories": categories,
                    "values": [float(value) for value in values]})
    return out


def build(pages: list[dict[str, Any]], *, title: str, subtitle: str, footer: str) -> bytes:
    """Колода из разобранных разделов. Ни одного числа здесь не считается."""
    try:
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_TICK_MARK
        from pptx.enum.text import PP_ALIGN
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
    # Цвета продукта, а не офисные: тот же синий, что в кабинете и на странице.
    # Ряд один, поэтому категориальная палитра здесь не нужна — нужен один
    # фирменный цвет и текстовые токены под подписи.
    ink = RGBColor(0x16, 0x20, 0x2B)
    dim = RGBColor(0x5B, 0x6B, 0x7D)
    brand = RGBColor(0x13, 0x67, 0xAE)

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
        """Таблица в оформлении продукта, а не в заводской синей полосатости.

        Заводской стиль PowerPoint красит шапку в сплошную синеву и чередует
        строки — на слайде с числами это шум, который спорит с числами. Здесь
        шапка на светлой подложке, строки белые, текст носит текстовые токены.
        """
        head = table.get("head") or []
        rows = table.get("rows") or []
        columns = max([len(head)] + [len(row) for row in rows]) or 1
        shape = slide.shapes.add_table(len(rows) + (1 if head else 0), columns,
                                       Inches(0.6), Inches(top),
                                       Inches(SLIDE_W_IN - 1.2), Inches(height))
        grid = shape.table
        grid.first_row = bool(head)
        grid.horz_banding = False

        def dress(cell, text: str, *, header: bool) -> None:
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0xF4, 0xF7, 0xFA) if header else RGBColor(0xFF, 0xFF, 0xFF)
            cell.margin_left = Inches(0.06)
            cell.margin_right = Inches(0.06)
            paragraph = cell.text_frame.paragraphs[0]
            # Числу место справа: колонка чисел, прижатая влево, не читается
            # столбиком. Заголовок стоит там же, где его числа.
            if cell_number(text) is not None or (header and cell is not grid.cell(0, 0)):
                paragraph.alignment = PP_ALIGN.RIGHT
            for run in paragraph.runs or [paragraph.add_run()]:
                run.font.size = Pt(11)
                run.font.bold = header
                run.font.color.rgb = ink if header else RGBColor(0x2A, 0x33, 0x3D)

        offset = 0
        if head:
            for index in range(columns):
                dress(grid.cell(0, index),
                      str(head[index]) if index < len(head) else "", header=True)
            offset = 1
        for line, row in enumerate(rows):
            for index in range(columns):
                dress(grid.cell(line + offset, index),
                      str(row[index]) if index < len(row) else "", header=False)

    def put_chart(slide, data: dict[str, Any], *, top: float, height: float) -> None:
        """График, а не заводская заготовка PowerPoint.

        «Убогие графики очень, как для первого класса школы» (владелец,
        30.08.2026) — и это была правда: столбики во всю ширину слота заводской
        синевы, сетка по всему полю, ось со значениями и подписи офисным
        шрифтом. Здесь наведён порядок по правилам оформления данных:
        столбик тонкий, цвет — наш фирменный, а не офисный; текст носит
        текстовые токены, а не цвет ряда; сетка убрана там, где значения стоят
        прямо на столбиках, и оставлена волосяной, где их много; легенды нет —
        ряд один, и его называет заголовок слайда.
        """
        payload = CategoryChartData()
        payload.categories = data["categories"]
        payload.add_series(data["name"], data["values"])
        frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(top),
            Inches(SLIDE_W_IN - 1.2), Inches(height), payload)
        chart = frame.chart
        chart.has_legend = False
        chart.font.size = Pt(11)
        chart.font.name = "Calibri"
        chart.font.color.rgb = dim

        plot = chart.plots[0]
        plot.vary_by_categories = False
        # Столбик не заполняет слот: воздух между столбиками — часть чтения, а
        # столбик во всю ширину слота и есть то самое «как для первого класса».
        # Ширины в формате нет, есть просвет — и он тем больше, чем меньше
        # категорий: на трёх категориях столбик иначе выходит в две ладони.
        count = len(data["categories"])
        plot.gap_width = 400 if count <= 3 else (250 if count <= 8 else
                                                 (140 if count <= 12 else 60))

        series = plot.series[0]
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = brand
        series.format.line.fill.background()

        # Число на каждом столбике — это хаос, если столбиков много: тогда
        # значения несёт ось. Мало — значения стоят прямо на шапках, и ось со
        # своей сеткой становится лишней краской.
        labelled = len(data["categories"]) <= 8
        plot.has_data_labels = labelled
        if labelled:
            labels = plot.data_labels
            labels.number_format = "#,##0.#"
            labels.number_format_is_linked = False
            labels.position = XL_LABEL_POSITION.OUTSIDE_END
            labels.font.size = Pt(11)
            labels.font.bold = True
            labels.font.color.rgb = ink

        value_axis = chart.value_axis
        value_axis.has_major_gridlines = not labelled
        if value_axis.has_major_gridlines:
            line = value_axis.major_gridlines.format.line
            line.color.rgb = RGBColor(0xE3, 0xEB, 0xF2)
            line.width = Pt(0.75)
        value_axis.visible = not labelled
        value_axis.has_minor_gridlines = False
        value_axis.major_tick_mark = XL_TICK_MARK.NONE
        value_axis.format.line.fill.background()
        if value_axis.visible:
            value_axis.tick_labels.number_format = "#,##0"
            value_axis.tick_labels.number_format_is_linked = False
            value_axis.tick_labels.font.size = Pt(10)
            value_axis.tick_labels.font.color.rgb = dim

        category_axis = chart.category_axis
        category_axis.has_major_gridlines = False
        category_axis.major_tick_mark = XL_TICK_MARK.NONE
        category_axis.format.line.color.rgb = RGBColor(0xDD, 0xE5, 0xED)
        category_axis.tick_labels.font.size = Pt(10)
        category_axis.tick_labels.font.color.rgb = dim

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
        drawn = charts(tables[0]) if tables else []

        # Первый слайд раздела — о чём он: заголовок, вывод и подписи, которые
        # на экране стоят рядом с картинкой (доли полос — это и есть числа
        # такого раздела).
        slide = new_slide(heading)
        top = 1.25
        if note:
            textbox(slide, note, top=top, size=14, colour=dim, height=0.8)
            top += 0.9
        if lines:
            for index, line in enumerate(lines):
                textbox(slide, line, top=top + index * 0.42, size=13, colour=ink)
        elif not drawn and tables:
            put_table(slide, tables[0], top=top,
                      height=min(4.8, 0.34 * (len(tables[0]["rows"]) + 1)))
            tables = tables[1:]

        # По слайду на график: каждая мера показана и ни одна не спорит с
        # соседней. Ряд один, поэтому легенда не нужна — мера стоит в
        # заголовке слайда.
        for chart in drawn:
            part = new_slide(f"{heading} · {chart['name']}")
            put_chart(part, chart, top=1.25, height=SLIDE_H_IN - 1.95)
            textbox(part, "График настоящий: данные правятся в PowerPoint,"
                          " числа — таблицей на следующих слайдах.",
                    top=SLIDE_H_IN - 0.95, size=11, colour=dim, height=0.4)

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
