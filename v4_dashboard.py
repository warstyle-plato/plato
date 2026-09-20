"""Лист «Дашборд» книги v4 и его скрытый источник `Dashboard_Data`.

Устройство (ТЗ владельца, 19.09.2026): у книги один источник значений для
дашборда — скрытый лист `Dashboard_Data`, где каждая величина ФОРМУЛОЙ читает
листы книги (ПРОВЕРКИ, ОТЧЕТ, ТЭП, CF), а сам «Дашборд» — только формулы на
`Dashboard_Data`. Правка вводной в книге двигает дашборд так же, как ОТЧЁТ;
хардов экономики здесь ноль по построению — единственное число, которое пишем
мы, это целевой LLCR банка, и оно подписано вводной.

KPI читаются из колонки B блока паритета листа ПРОВЕРКИ: это книжная сторона
той же величины, которую паритет сверяет с движком. Второй список «где в
книге выручка» разошёлся бы с первым молча — поэтому здесь его нет.

Модуль не знает движка: состав карточек и рисков приходит из
`presentation.py`, а числа — из модели представления (только для подписи
происхождения; ни одно число экономики отсюда в книгу не пишется).
"""

from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from presentation import BRIDGE_STEPS, CARD_COUNT, KPI_CATALOGUE, RISK_CATALOGUE

DATA_SHEET = "Dashboard_Data"
DASHBOARD_SHEET = "Дашборд"
DATA_SHEET_PATH = "xl/worksheets/sheetDashboardData.xml"
DATA_REL_ID = "RidDashboardData0001"
DATA_SHEET_ID = 902

_NS = 'xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Палитра кабинета: тёмно-синий и его оттенки, серый для вычетов, зелёный —
# для итога, красный — для итога со знаком минус.
NAVY = "17365D"
NAVY_DARK = "0B1F33"
NAVY_LIGHT = "1F4E78"
STEEL = "8FA9C4"
GREY = "A6A6A6"
GREEN = "2E7D32"
RED = "C00000"
RING_COLOURS = ("0B1F33", "17365D", "1F4E78", "2E75B6", "8FA9C4", "BDD7EE", "D9D9D9")

LLCR_TARGET_LABEL = "Целевой LLCR банка (вводная дашборда)"

# ---------------------------------------------------------------------------
# Раскладка Dashboard_Data. Ключ → строка. Величины книги для KPI — колонка B
# блока паритета ПРОВЕРОК: одна книжная сторона на паритет и на дашборд.
# ---------------------------------------------------------------------------
_PARITY = {
    "revenue_mln": 76, "capex_mln": 77, "ebitda_mln": 78, "financing_mln": 79,
    "tax_mln": 80, "net_profit_mln": 81, "llcr": 82, "peak_bridge_mln": 83,
    "peak_pf_mln": 84, "vat_mln": 86, "pf_shortfall_mln": 87,
}
_CF_SHEETS = ("CF_1", "CF_2", "CF_3", "CF_4")


def _cf_sum(cell: str) -> str:
    return "SUM(" + ",".join(f"'{s}'!{cell}" for s in _CF_SHEETS) + ")"


def _rve_max() -> str:
    return "MAX(" + ",".join(f"'{s}'!B8*'{s}'!B5" for s in _CF_SHEETS) + ")"


# (ключ, подпись, единица, формула книги). Порядок = строки со 2-й.
DATA_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    ("revenue_mln", "Выручка", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['revenue_mln']}"),
    ("capex_mln", "CAPEX", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['capex_mln']}"),
    ("ebitda_mln", "EBITDA", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['ebitda_mln']}"),
    ("net_profit_mln", "Чистая прибыль", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['net_profit_mln']}"),
    ("margin", "Маржинальность", "доля", "'ОТЧЕТ'!B13"),
    ("llcr", "LLCR", "x", f"'ПРОВЕРКИ'!B{_PARITY['llcr']}"),
    ("peak_bridge_mln", "Пик БРИДЖа", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['peak_bridge_mln']}"),
    ("peak_pf_mln", "Пик ПФ", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['peak_pf_mln']}"),
    ("financing_mln", "Стоимость финансирования", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['financing_mln']}"),
    ("npv_mln", "NPV собственного капитала", "млн ₽", "'ОТЧЕТ'!B15"),
    ("term_months", "Срок проекта до РВЭ", "мес.",
     f"(YEAR({_rve_max()})-YEAR('Вводные'!$B$8))*12+MONTH({_rve_max()})-MONTH('Вводные'!$B$8)"),
    ("commercial_mln", "Коммерческие расходы", "млн ₽", "'ОТЧЕТ'!B7"),
    ("tax_mln", "Налог на прибыль", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['tax_mln']}"),
    ("vat_mln", "НДС к уплате", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['vat_mln']}"),
    ("pf_shortfall_mln", "Непокрытая потребность в ПФ", "млн ₽", f"'ПРОВЕРКИ'!B{_PARITY['pf_shortfall_mln']}"),
    ("rve_unpaid_mln", "Не покрыто раскрытым эскроу в РВЭ", "млн ₽", _cf_sum("B29")),
    ("ending_pf_mln", "Непогашенный долг на конец проекта", "млн ₽", "'CF'!B19"),
    ("llcr_target", LLCR_TARGET_LABEL, "x", ""),
    ("project_start", "Старт проекта", "дата", "'Вводные'!$B$8"),
    ("rve", "РВЭ последней очереди", "дата", _rve_max()),
    ("project_name", "Проект", "текст", "'ОТЧЕТ'!A2"),
    ("status", "Статус модели (лист ПРОВЕРКИ)", "текст", "'ПРОВЕРКИ'!B3"),
)
DATA_ROWS: dict[str, int] = {item[0]: index + 2 for index, item in enumerate(DATA_ITEMS)}

# Продукты: ключ движка → подпись и формулы книги (ГНС, продаваемая, единицы, выручка).
PRODUCT_FIRST_ROW = 30
_TEP_Q = ("'ТЭП'!{col}4", "'ТЭП'!{col}10", "'ТЭП'!{col}16", "'ТЭП'!{col}22")


def _tep_sum(col: str, shift: int) -> str:
    return "SUM(" + ",".join(f"'ТЭП'!{col}{row + shift}" for row in (4, 10, 16, 22)) + ")"


PRODUCT_ITEMS: tuple[tuple[str, str, str, str, str, str], ...] = (
    # key, label, gns, saleable, units, revenue_mln
    ("apartments", "Квартиры", "'ОТЧЕТ'!B46", "'ОТЧЕТ'!C46", "", _tep_sum("G", 0)),
    ("ground_commercial", "Коммерция первого этажа", "'ОТЧЕТ'!B47", "'ОТЧЕТ'!C47", "", _tep_sum("G", 1)),
    # ГНС подземного паркинга: у ОТЧЕТа она с 14.09.2026 стоит своей колонкой
    # «Подземная», а строка B48 обнулена, поэтому берётся из строк ТЭП очередей.
    ("underground_parking", "Подземный паркинг", _tep_sum("C", 2), "", _tep_sum("E", 2), _tep_sum("G", 2)),
    ("storage", "Кладовые", "", "", _tep_sum("E", 3), _tep_sum("G", 3)),
    ("offices", "МФОЦ / офисный центр", "'ТЭП'!C31", "'ТЭП'!D31", "", "'ТЭП'!G31"),
    ("standalone_retail", "Торговый центр / ОСЗ", "'ТЭП'!C32", "'ТЭП'!D32", "", "'ТЭП'!G32"),
    ("above_parking", "Наземный паркинг", "", "", "'ТЭП'!E33", "'ТЭП'!G33"),
)
PRODUCT_ROWS: dict[str, int] = {item[0]: PRODUCT_FIRST_ROW + index
                                for index, item in enumerate(PRODUCT_ITEMS)}
PRODUCT_TOTAL_ROW = PRODUCT_FIRST_ROW + len(PRODUCT_ITEMS)

RISK_FIRST_ROW = 45
RISK_ROWS: dict[str, int] = {item[0]: RISK_FIRST_ROW + index
                             for index, item in enumerate(RISK_CATALOGUE)}
BRIDGE_FIRST_ROW = 55
RING_FIRST_ROW = 65
RING_COUNT = 7                     # 'ОТЧЕТ'!A33:B39 — структура расходов
MONTH_LABEL_ROW, MONTH_DEBT_ROW, MONTH_ESCROW_ROW = 75, 76, 77
ORIGIN_FIRST_ROW = 82
ORIGIN_ITEMS = ("calculation_id", "engine_version", "generated_at", "template")


def data_cell(key: str, column: str = "C") -> str:
    return f"'{DATA_SHEET}'!${column}${DATA_ROWS[key]}"


# ---------------------------------------------------------------------------
# Стили: находим готовый xf у шаблона или дописываем свой. Своих цветов не
# выдумываем — шрифты и заливки берутся из каталога шаблона; единственная
# добавка — красный шрифт для сработавшего риска, которого в шаблоне нет.
# ---------------------------------------------------------------------------
class Styles:
    def __init__(self, styles_xml: str) -> None:
        self.xml = styles_xml
        self._xfs = re.search(r'<x:cellXfs count="(\d+)">(.*?)</x:cellXfs>', styles_xml, re.S)
        if not self._xfs:
            raise ValueError("styles.xml без cellXfs")
        self._items = re.findall(r'<x:xf [^>]*?(?:/>|>.*?</x:xf>)', self._xfs.group(2), re.S)
        self.added = 0

    def font(self, rgb: str, bold: bool = False, size: int = 11) -> int:
        block = re.search(r'<x:fonts count="(\d+)">(.*?)</x:fonts>', self.xml, re.S)
        fonts = re.findall(r'<x:font>.*?</x:font>|<x:font/>', block.group(2), re.S)
        wanted = (f'<x:font>{"<x:b />" if bold else ""}<x:sz val="{size}" />'
                  f'<x:color rgb="FF{rgb}" /><x:name val="Carlito" /></x:font>')
        squeeze = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
        for index, font in enumerate(fonts):
            if squeeze(font) == squeeze(wanted):
                return index
        count = int(block.group(1))
        new_block = f'<x:fonts count="{count + 1}">{block.group(2)}{wanted}</x:fonts>'
        self.xml = self.xml[:block.start()] + new_block + self.xml[block.end():]
        return count

    def xf(self, num_fmt: int = 0, font: int = 0, fill: int = 0, border: int = 0,
           halign: str = "", valign: str = "", wrap: bool = False) -> int:
        align = ""
        if halign or valign or wrap:
            align = ("<x:alignment" + (f' horizontal="{halign}"' if halign else "")
                     + (f' vertical="{valign}"' if valign else "")
                     + (' wrapText="1"' if wrap else "") + " />")
        head = (f'<x:xf numFmtId="{num_fmt}" fontId="{font}" fillId="{fill}" borderId="{border}" '
                'xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"')
        wanted = head + (f' applyAlignment="1">{align}</x:xf>' if align else " />")
        squeeze = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
        for index, item in enumerate(self._items):
            if squeeze(item) == squeeze(wanted):
                return index
        self._items.append(wanted)
        self.added += 1
        return len(self._items) - 1

    def render(self) -> str:
        block = re.search(r'<x:cellXfs count="(\d+)">(.*?)</x:cellXfs>', self.xml, re.S)
        new_block = f'<x:cellXfs count="{len(self._items)}">{"".join(self._items)}</x:cellXfs>'
        return self.xml[:block.start()] + new_block + self.xml[block.end():]


# ---------------------------------------------------------------------------
# Ячейки и строки
# ---------------------------------------------------------------------------
def _col(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _col_index(letters: str) -> int:
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - 64)
    return value - 1


def _cell(coord: str, *, text: str | None = None, formula: str | None = None,
          number: float | None = None, style: int | None = None) -> str:
    attrs = f' s="{style}"' if style is not None else ""
    if formula is not None:
        return f'<x:c r="{coord}"{attrs}><x:f>{_xml_escape(formula)}</x:f></x:c>'
    if text is not None:
        return (f'<x:c r="{coord}"{attrs} t="inlineStr"><x:is><x:t xml:space="preserve">'
                f'{_xml_escape(text)}</x:t></x:is></x:c>')
    if number is not None:
        return f'<x:c r="{coord}"{attrs}><x:v>{repr(float(number))}</x:v></x:c>'
    return f'<x:c r="{coord}"{attrs} />'


def _row(number: int, cells: list[tuple[str, str]], height: float | None = None) -> str:
    """Ячейки строки — по возрастанию колонки: Excel иначе теряет их молча."""
    ordered = sorted(cells, key=lambda pair: _col_index(pair[0]))
    attrs = f' ht="{height}" customHeight="1"' if height else ""
    return (f'<x:row r="{number}"{attrs}>'
            + "".join(xml for _, xml in ordered) + "</x:row>")


# ---------------------------------------------------------------------------
# Dashboard_Data
# ---------------------------------------------------------------------------
def build_data_sheet(origin: dict[str, Any], llcr_target: float, last_column: str,
                     month_columns: list[str]) -> str:
    """Скрытый лист-источник: каждая величина — формула на листы книги.

    `month_columns` — колонки месяцев листа CF (D..GA): ряды долга и эскроу
    копируются помесячно, чтобы график перестраивался в Excel сам.
    """
    rows: list[str] = []
    rows.append(_row(1, [("A1", _cell("A1", text="ключ")), ("B1", _cell("B1", text="подпись")),
                         ("C1", _cell("C1", text="значение")), ("D1", _cell("D1", text="единица"))]))
    for key, label, unit, formula in DATA_ITEMS:
        r = DATA_ROWS[key]
        if key == "llcr_target":
            value = _cell(f"C{r}", number=llcr_target)
        else:
            value = _cell(f"C{r}", formula=formula)
        rows.append(_row(r, [(f"A{r}", _cell(f"A{r}", text=key)), (f"B{r}", _cell(f"B{r}", text=label)),
                             (f"C{r}", value), (f"D{r}", _cell(f"D{r}", text=unit))]))

    # Продукты: ключ, подпись, ГНС, продаваемая, единицы, выручка, средняя цена.
    header = PRODUCT_FIRST_ROW - 1
    rows.append(_row(header, [(f"{c}{header}", _cell(f"{c}{header}", text=t)) for c, t in (
        ("A", "продукт"), ("B", "подпись"), ("C", "ГНС, м²"), ("D", "продаваемая, м²"),
        ("E", "единиц, шт."), ("F", "выручка, млн ₽"), ("G", "средняя цена, тыс ₽"))]))
    for key, label, gns, saleable, units, revenue in PRODUCT_ITEMS:
        r = PRODUCT_ROWS[key]
        cells = [(f"A{r}", _cell(f"A{r}", text=key)), (f"B{r}", _cell(f"B{r}", text=label)),
                 (f"F{r}", _cell(f"F{r}", formula=revenue))]
        cells.append((f"C{r}", _cell(f"C{r}", formula=gns) if gns else _cell(f"C{r}")))
        cells.append((f"D{r}", _cell(f"D{r}", formula=saleable) if saleable else _cell(f"D{r}")))
        cells.append((f"E{r}", _cell(f"E{r}", formula=units) if units else _cell(f"E{r}")))
        base = f"D{r}" if saleable else (f"E{r}" if units else "")
        cells.append((f"G{r}", _cell(f"G{r}", formula=f"IFERROR(F{r}*1000/{base},0)") if base
                      else _cell(f"G{r}")))
        rows.append(_row(r, cells))
    t = PRODUCT_TOTAL_ROW
    first, last = PRODUCT_FIRST_ROW, PRODUCT_TOTAL_ROW - 1
    rows.append(_row(t, [(f"A{t}", _cell(f"A{t}", text="total")), (f"B{t}", _cell(f"B{t}", text="Итого")),
                         (f"C{t}", _cell(f"C{t}", formula=f"SUM(C{first}:C{last})")),
                         (f"D{t}", _cell(f"D{t}", formula=f"SUM(D{first}:D{last})")),
                         (f"E{t}", _cell(f"E{t}", formula=f"SUM(E{first}:E{last})")),
                         (f"F{t}", _cell(f"F{t}", formula=f"SUM(F{first}:F{last})"))]))

    # Риски: ключ, подпись, признак 0/1, величина рядом.
    header = RISK_FIRST_ROW - 1
    rows.append(_row(header, [(f"{c}{header}", _cell(f"{c}{header}", text=t)) for c, t in (
        ("A", "риск"), ("B", "подпись"), ("C", "сработал (1/0)"), ("D", "величина"), ("E", "чья очередь"))]))
    weakest_llcr = "MIN(" + ",".join(
        f"IF('{s}'!B5=1,'{s}'!B85,9999)" for s in _CF_SHEETS) + ")"
    queues_on = "(" + "+".join(f"'{s}'!B5" for s in _CF_SHEETS) + ")"
    weakest_name = "IF(" + ",".join(
        [f"{weakest_llcr}='{_CF_SHEETS[0]}'!B85,'Вводные'!$C$88"]
        + [""]) + ")"
    # Имя слабейшей — по совпадению LLCR с очередью: первая совпавшая.
    weakest_name = ("IF({w}='CF_1'!B85,'Вводные'!$C$88,IF({w}='CF_2'!B85,'Вводные'!$C$89,"
                    "IF({w}='CF_3'!B85,'Вводные'!$C$90,'Вводные'!$C$91)))").format(w=weakest_llcr)
    risk_formulas = {
        "default_rve": (f"IF({data_cell('rve_unpaid_mln', 'C')}>0.5,1,0)", data_cell("rve_unpaid_mln", "C"), ""),
        "pf_shortfall": (f"IF({data_cell('pf_shortfall_mln', 'C')}>0.5,1,0)", data_cell("pf_shortfall_mln", "C"), ""),
        "llcr_below_target": (f"IF({data_cell('llcr', 'C')}<{data_cell('llcr_target', 'C')},1,0)",
                              data_cell("llcr", "C"), ""),
        "ending_debt": (f"IF({data_cell('ending_pf_mln', 'C')}>0.5,1,0)", data_cell("ending_pf_mln", "C"), ""),
        "weakest_phase": (f"IF({queues_on}>1,IF({weakest_llcr}<1,1,0),0)",
                          f"IF({queues_on}>1,{weakest_llcr},\"\")",
                          f"IF({queues_on}>1,{weakest_name},\"\")"),
    }
    for key, label, _value_key in RISK_CATALOGUE:
        r = RISK_ROWS[key]
        flag, value, detail = risk_formulas[key]
        cells = [(f"A{r}", _cell(f"A{r}", text=key)), (f"B{r}", _cell(f"B{r}", text=label)),
                 (f"C{r}", _cell(f"C{r}", formula=flag)), (f"D{r}", _cell(f"D{r}", formula=value)),
                 (f"E{r}", _cell(f"E{r}", formula=detail) if detail else _cell(f"E{r}"))]
        rows.append(_row(r, cells))

    # Мост от выручки к чистой прибыли: подпись и бар со знаком.
    header = BRIDGE_FIRST_ROW - 1
    rows.append(_row(header, [(f"A{header}", _cell(f"A{header}", text="мост")),
                              (f"B{header}", _cell(f"B{header}", text="млн ₽ со знаком"))]))
    for index, (key, label, sign) in enumerate(BRIDGE_STEPS):
        r = BRIDGE_FIRST_ROW + index
        formula = data_cell(key, "C") if sign > 0 else f"-{data_cell(key, 'C')}"
        rows.append(_row(r, [(f"A{r}", _cell(f"A{r}", text=label)), (f"B{r}", _cell(f"B{r}", formula=formula))]))

    # Кольцо структуры расходов — строки 33–39 листа ОТЧЕТ, как есть.
    header = RING_FIRST_ROW - 1
    rows.append(_row(header, [(f"A{header}", _cell(f"A{header}", text="структура расходов")),
                              (f"B{header}", _cell(f"B{header}", text="млн ₽"))]))
    for index in range(RING_COUNT):
        r = RING_FIRST_ROW + index
        rows.append(_row(r, [(f"A{r}", _cell(f"A{r}", formula=f"'ОТЧЕТ'!A{33 + index}")),
                             (f"B{r}", _cell(f"B{r}", formula=f"'ОТЧЕТ'!B{33 + index}"))]))

    # Помесячные ряды долга и эскроу — колонки CF без пересчёта.
    for r, label, cf_row in ((MONTH_LABEL_ROW, "месяц", 3), (MONTH_DEBT_ROW, "долг всего, млн ₽", 19),
                             (MONTH_ESCROW_ROW, "эскроу на конец, млн ₽", 9)):
        cells = [(f"A{r}", _cell(f"A{r}", text=label))]
        for column in month_columns:
            cells.append((f"{column}{r}", _cell(f"{column}{r}", formula=f"'CF'!{column}{cf_row}")))
        rows.append(_row(r, cells))
    # Происхождение: текст, а не число — и потому не хард экономики.
    header = ORIGIN_FIRST_ROW - 1
    rows.append(_row(header, [(f"A{header}", _cell(f"A{header}", text="происхождение"))]))
    for index, key in enumerate(ORIGIN_ITEMS):
        r = ORIGIN_FIRST_ROW + index
        rows.append(_row(r, [(f"A{r}", _cell(f"A{r}", text=key)),
                             (f"B{r}", _cell(f"B{r}", text=str(origin.get(key) or "")))]))

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<x:worksheet {_NS}><x:sheetPr><x:tabColor rgb="FF{GREY}" /></x:sheetPr>'
        '<x:sheetViews><x:sheetView workbookViewId="0" /></x:sheetViews>'
        '<x:sheetFormatPr defaultRowHeight="15" />'
        '<x:cols><x:col min="1" max="1" width="24" customWidth="1" />'
        '<x:col min="2" max="2" width="44" customWidth="1" />'
        '<x:col min="3" max="7" width="16" customWidth="1" /></x:cols>'
        f'<x:sheetData>{"".join(rows)}</x:sheetData>'
        '<x:pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3" />'
        "</x:worksheet>"
    )


# ---------------------------------------------------------------------------
# Лист «Дашборд»: только формулы на Dashboard_Data
# ---------------------------------------------------------------------------
CARD_SLOTS = (("A", "E"), ("F", "J"), ("K", "P"))   # три карточки в ряд
CARD_ROWS = ((4, 5, 7), (9, 10, 12))                # (подпись, верх значения, низ значения)
TEP_HEADER_ROW = 14
TABLE_FIRST_ROW = 16
FIN_HEADER_ROW = 24
FIN_FIRST_ROW = 25
CHART_TOP_ROW = 32
CHART_BOTTOM_ROW = 50
CHART_SLOTS = ((0, 6), (6, 11), (11, 16))            # колонки (от, до) трёх диаграмм


def _value_style(styles: Styles, unit: str, card: bool) -> int:
    fmt = {"млн ₽": 207, "доля": 202, "x": 206, "мес.": 201, "дата": 200,
           "м²": 203, "шт.": 203, "тыс ₽": 203, "текст": 211}.get(unit, 207)
    if card:
        return styles.xf(fmt, font=3, fill=4, border=5, halign="center", valign="center")
    return styles.xf(fmt, font=8, fill=0, border=0, halign="right")


def build_dashboard_sheet(styles: Styles, drawing_rel_id: str, phased: bool) -> str:
    """Лист «Дашборд» — формулы на Dashboard_Data, одна печатная страница."""
    title = styles.xf(0, font=1, fill=2, border=0, halign="left", valign="center")
    subtitle = styles.xf(0, font=2, fill=0, border=0, halign="left")
    section = styles.xf(0, font=1, fill=6, border=13, halign="left", valign="center")
    card_label = styles.xf(0, font=1, fill=6, border=0, halign="center")
    th = styles.xf(0, font=1, fill=5, border=0, halign="center", valign="center", wrap=True)
    td = styles.xf(0, font=8, fill=0, border=0, halign="left")
    td_muted = styles.xf(0, font=2, fill=0, border=0, halign="left")
    risk_on = styles.xf(0, font=styles.font(RED, bold=True), fill=0, border=0, halign="center")
    risk_off = styles.xf(0, font=styles.font(GREEN), fill=0, border=0, halign="center")

    merges: list[str] = ["A1:P1", "A2:P2"]
    rows: list[str] = []

    rows.append(_row(1, [(f"{_col(i)}1", _cell(f"{_col(i)}1", text="DEVELOPAID · ИНВЕСТИЦИОННЫЙ ДАШБОРД" if i == 0 else None, style=title))
                         for i in range(16)], height=24))
    rows.append(_row(2, [(f"{_col(i)}2", _cell(f"{_col(i)}2", formula=data_cell("project_name") if i == 0 else None, style=subtitle))
                         for i in range(16)]))

    cards = list(KPI_CATALOGUE[:CARD_COUNT])
    for band, (label_row, top, bottom) in enumerate(CARD_ROWS):
        label_cells: list[tuple[str, str]] = []
        value_cells: dict[int, list[tuple[str, str]]] = {r: [] for r in range(top, bottom + 1)}
        for slot, (left, right) in enumerate(CARD_SLOTS):
            key, label, unit = cards[band * len(CARD_SLOTS) + slot]
            merges.append(f"{left}{label_row}:{right}{label_row}")
            merges.append(f"{left}{top}:{right}{bottom}")
            style = _value_style(styles, unit, card=True)
            for ci in range(_col_index(left), _col_index(right) + 1):
                c = _col(ci)
                label_cells.append((f"{c}{label_row}", _cell(
                    f"{c}{label_row}", text=f"{label}, {unit}" if ci == _col_index(left) else None,
                    style=card_label)))
                for r in range(top, bottom + 1):
                    value_cells[r].append((f"{c}{r}", _cell(
                        f"{c}{r}", formula=data_cell(key) if (ci == _col_index(left) and r == top) else None,
                        style=style)))
        rows.append(_row(label_row, label_cells))
        for r in range(top, bottom + 1):
            rows.append(_row(r, value_cells[r], height=20))

    # Разделы: ТЭП и продажи (A–H и I–P), финансирование и риски.
    def section_row(number: int, left_text: str, right_text: str) -> None:
        merges.extend([f"A{number}:H{number}", f"I{number}:P{number}"])
        cells = []
        for i in range(16):
            c = _col(i)
            text = left_text if i == 0 else right_text if i == 8 else None
            cells.append((f"{c}{number}", _cell(f"{c}{number}", text=text, style=section)))
        rows.append(_row(number, cells, height=18))

    section_row(TEP_HEADER_ROW, "КЛЮЧЕВОЙ ТЭП · построено", "ПРОДАЖИ · выручка по продуктам")
    head = TEP_HEADER_ROW + 1
    tep_head = (("A", "Продукт"), ("D", "ГНС, м²"), ("F", "Продаваемая, м²"), ("H", "Единиц"))
    sales_head = (("I", "Продукт"), ("L", "Выручка, млн ₽"), ("N", "Ср. цена, тыс ₽"), ("P", "Доля"))
    merges.extend([f"A{head}:C{head}", f"D{head}:E{head}", f"F{head}:G{head}",
                   f"I{head}:K{head}", f"L{head}:M{head}", f"N{head}:O{head}"])
    cells = []
    for i in range(16):
        c = _col(i)
        text = dict(tep_head + sales_head).get(c)
        cells.append((f"{c}{head}", _cell(f"{c}{head}", text=text, style=th)))
    rows.append(_row(head, cells, height=28))
    num = _value_style(styles, "м²", card=False)
    money = _value_style(styles, "млн ₽", card=False)
    pct = _value_style(styles, "доля", card=False)
    for index, (key, *_rest) in enumerate(PRODUCT_ITEMS):
        r = TABLE_FIRST_ROW + index
        src = PRODUCT_ROWS[key]
        merges.extend([f"A{r}:C{r}", f"D{r}:E{r}", f"F{r}:G{r}", f"I{r}:K{r}", f"L{r}:M{r}", f"N{r}:O{r}"])
        cells = [
            (f"A{r}", _cell(f"A{r}", formula=f"'{DATA_SHEET}'!$B${src}", style=td)),
            (f"B{r}", _cell(f"B{r}", style=td)), (f"C{r}", _cell(f"C{r}", style=td)),
            (f"D{r}", _cell(f"D{r}", formula=f"'{DATA_SHEET}'!$C${src}", style=num)), (f"E{r}", _cell(f"E{r}", style=num)),
            (f"F{r}", _cell(f"F{r}", formula=f"'{DATA_SHEET}'!$D${src}", style=num)), (f"G{r}", _cell(f"G{r}", style=num)),
            (f"H{r}", _cell(f"H{r}", formula=f"'{DATA_SHEET}'!$E${src}", style=num)),
            (f"I{r}", _cell(f"I{r}", formula=f"'{DATA_SHEET}'!$B${src}", style=td)),
            (f"J{r}", _cell(f"J{r}", style=td)), (f"K{r}", _cell(f"K{r}", style=td)),
            (f"L{r}", _cell(f"L{r}", formula=f"'{DATA_SHEET}'!$F${src}", style=money)), (f"M{r}", _cell(f"M{r}", style=money)),
            (f"N{r}", _cell(f"N{r}", formula=f"'{DATA_SHEET}'!$G${src}", style=num)), (f"O{r}", _cell(f"O{r}", style=num)),
            (f"P{r}", _cell(f"P{r}", formula=f"IFERROR('{DATA_SHEET}'!$F${src}/'{DATA_SHEET}'!$F${PRODUCT_TOTAL_ROW},0)", style=pct)),
        ]
        rows.append(_row(r, cells))
    r = TABLE_FIRST_ROW + len(PRODUCT_ITEMS)
    src = PRODUCT_TOTAL_ROW
    bold_td = styles.xf(0, font=3, fill=7, border=13, halign="left")
    bold_num = styles.xf(203, font=3, fill=7, border=13, halign="right")
    bold_money = styles.xf(207, font=3, fill=7, border=13, halign="right")
    merges.extend([f"A{r}:C{r}", f"D{r}:E{r}", f"F{r}:G{r}", f"I{r}:K{r}", f"L{r}:M{r}", f"N{r}:O{r}"])
    rows.append(_row(r, [
        (f"A{r}", _cell(f"A{r}", text="Итого проект", style=bold_td)), (f"B{r}", _cell(f"B{r}", style=bold_td)), (f"C{r}", _cell(f"C{r}", style=bold_td)),
        (f"D{r}", _cell(f"D{r}", formula=f"'{DATA_SHEET}'!$C${src}", style=bold_num)), (f"E{r}", _cell(f"E{r}", style=bold_num)),
        (f"F{r}", _cell(f"F{r}", formula=f"'{DATA_SHEET}'!$D${src}", style=bold_num)), (f"G{r}", _cell(f"G{r}", style=bold_num)),
        (f"H{r}", _cell(f"H{r}", formula=f"'{DATA_SHEET}'!$E${src}", style=bold_num)),
        (f"I{r}", _cell(f"I{r}", text="Итого", style=bold_td)), (f"J{r}", _cell(f"J{r}", style=bold_td)), (f"K{r}", _cell(f"K{r}", style=bold_td)),
        (f"L{r}", _cell(f"L{r}", formula=f"'{DATA_SHEET}'!$F${src}", style=bold_money)), (f"M{r}", _cell(f"M{r}", style=bold_money)),
        (f"N{r}", _cell(f"N{r}", style=bold_num)), (f"O{r}", _cell(f"O{r}", style=bold_num)),
        (f"P{r}", _cell(f"P{r}", formula=f"IFERROR('{DATA_SHEET}'!$F${src}/'{DATA_SHEET}'!$F${src},0)", style=bold_num)),
    ]))

    section_row(FIN_HEADER_ROW, "ФИНАНСИРОВАНИЕ И СРОКИ", "АВТО-РИСКИ · считает книга")
    fin_items = [key for key, *_ in KPI_CATALOGUE[CARD_COUNT:]] + ["project_start", "rve"]
    fin_labels = {key: (label, unit) for key, label, unit in KPI_CATALOGUE}
    fin_labels.update({"project_start": ("Старт проекта", "дата"), "rve": ("РВЭ последней очереди", "дата")})
    risk_items = list(RISK_CATALOGUE)
    line_count = max(len(fin_items), len(risk_items) + 1)
    for index in range(line_count):
        r = FIN_FIRST_ROW + index
        merges.extend([f"A{r}:E{r}", f"F{r}:H{r}", f"I{r}:M{r}", f"O{r}:P{r}"])
        cells: list[tuple[str, str]] = []
        if index < len(fin_items):
            key = fin_items[index]
            label, unit = fin_labels[key]
            style = _value_style(styles, unit, card=False)
            cells += [(f"A{r}", _cell(f"A{r}", text=f"{label}, {unit}", style=td)),
                      (f"F{r}", _cell(f"F{r}", formula=data_cell(key), style=style))]
        else:
            cells += [(f"A{r}", _cell(f"A{r}", style=td)), (f"F{r}", _cell(f"F{r}", style=td))]
        for c in ("B", "C", "D", "E", "G", "H"):
            cells.append((f"{c}{r}", _cell(f"{c}{r}", style=td)))
        if index < len(risk_items):
            key, label, value_key = risk_items[index]
            src = RISK_ROWS[key]
            flag = f"'{DATA_SHEET}'!$C${src}"
            cells += [
                (f"I{r}", _cell(f"I{r}", formula=f"'{DATA_SHEET}'!$B${src}", style=td)),
                (f"N{r}", _cell(f"N{r}", formula=f'IF({flag}=1,"ДА","нет")',
                                style=risk_on if index == 0 else risk_on)),
                (f"O{r}", _cell(f"O{r}", formula=f"IF({flag}=1,'{DATA_SHEET}'!$D${src},\"\")",
                                style=_value_style(styles, "x" if value_key in ("llcr", "weakest_phase_llcr") else "млн ₽", card=False))),
            ]
        elif index == len(risk_items):
            cells += [(f"I{r}", _cell(f"I{r}", text="Статус модели (ПРОВЕРКИ)", style=td_muted)),
                      (f"N{r}", _cell(f"N{r}", style=td)),
                      (f"O{r}", _cell(f"O{r}", formula=data_cell("status"), style=td))]
        else:
            cells += [(f"I{r}", _cell(f"I{r}", style=td)), (f"N{r}", _cell(f"N{r}", style=td)), (f"O{r}", _cell(f"O{r}", style=td))]
        for c in ("J", "K", "L", "M", "P"):
            cells.append((f"{c}{r}", _cell(f"{c}{r}", style=td)))
        rows.append(_row(r, cells))
    del risk_off  # цвет «нет» — обычный текст; красное только у сработавшего

    r = CHART_TOP_ROW - 1
    section_row(r, "МОСТ ОТ ВЫРУЧКИ К ПРИБЫЛИ · СТРУКТУРА РАСХОДОВ", "ДОЛГ И ЭСКРОУ ПО МЕСЯЦАМ")
    r = CHART_BOTTOM_ROW + 1
    origin_style = styles.xf(0, font=2, fill=0, border=0, halign="left")
    merges.append(f"A{r}:P{r}")
    origin_formula = ('"Расчёт "&\'{d}\'!$B${a}&" · движок "&\'{d}\'!$B${b}&" · собрано "&\'{d}\'!$B${c}'
                      .format(d=DATA_SHEET, a=ORIGIN_FIRST_ROW, b=ORIGIN_FIRST_ROW + 1, c=ORIGIN_FIRST_ROW + 2))
    rows.append(_row(r, [(f"{_col(i)}{r}", _cell(f"{_col(i)}{r}", formula=origin_formula if i == 0 else None, style=origin_style))
                         for i in range(16)]))

    cols = "".join(f'<x:col min="{i}" max="{i}" width="11.5" customWidth="1" />' for i in range(1, 17))
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<x:worksheet {_NS} {_R_NS}>'
        '<x:sheetPr><x:tabColor rgb="FF17365D" /><x:pageSetUpPr fitToPage="1" /></x:sheetPr>'
        '<x:sheetViews><x:sheetView showGridLines="0" workbookViewId="0" /></x:sheetViews>'
        '<x:sheetFormatPr defaultRowHeight="15" />'
        f"<x:cols>{cols}</x:cols>"
        f'<x:sheetData>{"".join(rows)}</x:sheetData>'
        f'<x:mergeCells count="{len(merges)}">'
        + "".join(f'<x:mergeCell ref="{m}" />' for m in merges) + "</x:mergeCells>"
        '<x:pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3" />'
        '<x:pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="1" />'
        f'<x:drawing r:id="{drawing_rel_id}" />'
        "</x:worksheet>"
    )


# ---------------------------------------------------------------------------
# Диаграммы: формулы на диапазоны Dashboard_Data — Excel перестраивает сам.
# ---------------------------------------------------------------------------
def _rich_title(text: str) -> str:
    return ('<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1100" b="1">'
            f'<a:solidFill><a:srgbClr val="{NAVY_DARK}"/></a:solidFill></a:defRPr></a:pPr>'
            f'<a:r><a:rPr lang="ru-RU" sz="1100" b="1"><a:solidFill><a:srgbClr val="{NAVY_DARK}"/></a:solidFill></a:rPr>'
            f'<a:t>{_xml_escape(text)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>'
            '<c:autoTitleDeleted val="0"/>')


def _axes(cat_id: int, val_id: int, cat_format: str = "General") -> str:
    return (
        f'<c:catAx><c:axId val="{cat_id}"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
        f'<c:delete val="0"/><c:axPos val="b"/><c:numFmt formatCode="{cat_format}" sourceLinked="0"/>'
        '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="low"/>'
        '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="ru-RU"/></a:p></c:txPr>'
        f'<c:crossAx val="{val_id}"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
        f'<c:valAx><c:axId val="{val_id}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        '<c:axPos val="l"/><c:majorGridlines><c:spPr><a:ln w="9525"><a:solidFill><a:srgbClr val="D9D9D9"/></a:solidFill>'
        '<a:prstDash val="dash"/></a:ln></c:spPr></c:majorGridlines><c:numFmt formatCode="#,##0" sourceLinked="0"/>'
        '<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
        '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="ru-RU"/></a:p></c:txPr>'
        f'<c:crossAx val="{cat_id}"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx>'
    )


def _chart_space(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<c:chartSpace xmlns:c="{_CHART_NS}" xmlns:a="{_DRAWINGML_NS}" xmlns:r="{_REL_NS}">'
        '<c:lang val="ru-RU"/><c:roundedCorners val="0"/>'
        f"<c:chart>{body}<c:plotVisOnly val=\"1\"/><c:dispBlanksAs val=\"gap\"/></c:chart>"
        f'<c:spPr><a:ln w="9525"><a:solidFill><a:srgbClr val="D9D9D9"/></a:solidFill></a:ln></c:spPr>'
        "</c:chartSpace>"
    ).encode("utf-8")


def _ref(column: str, first: int, last: int) -> str:
    return f"'{DATA_SHEET}'!${column}${first}:${column}${last}"


def bridge_chart_xml() -> bytes:
    first, last = BRIDGE_FIRST_ROW, BRIDGE_FIRST_ROW + len(BRIDGE_STEPS) - 1
    points = "".join(
        f'<c:dPt><c:idx val="{i}"/><c:invertIfNegative val="0"/><c:bubble3D val="0"/>'
        f'<c:spPr><a:solidFill><a:srgbClr val="{NAVY if sign > 0 and i == 0 else (GREEN if sign > 0 else STEEL)}"/></a:solidFill></c:spPr></c:dPt>'
        for i, (_k, _l, sign) in enumerate(BRIDGE_STEPS))
    series = (
        '<c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:v>млн ₽</c:v></c:tx>'
        f'<c:spPr><a:solidFill><a:srgbClr val="{NAVY}"/></a:solidFill></c:spPr>'
        f'<c:invertIfNegative val="0"/>{points}'
        '<c:dLbls><c:numFmt formatCode="#,##0" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
        '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="ru-RU"/></a:p></c:txPr>'
        '<c:dLblPos val="outEnd"/><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/>'
        '<c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>'
        f'<c:cat><c:strRef><c:f>{_xml_escape(_ref("A", first, last))}</c:f></c:strRef></c:cat>'
        f'<c:val><c:numRef><c:f>{_xml_escape(_ref("B", first, last))}</c:f></c:numRef></c:val></c:ser>'
    )
    body = (
        _rich_title("Мост от выручки к чистой прибыли, млн ₽")
        + '<c:plotArea><c:layout/><c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
        + series + '<c:gapWidth val="45"/><c:axId val="510001"/><c:axId val="510002"/></c:barChart>'
        + _axes(510001, 510002) + "</c:plotArea>"
    )
    return _chart_space(body)


def ring_chart_xml() -> bytes:
    first, last = RING_FIRST_ROW, RING_FIRST_ROW + RING_COUNT - 1
    points = "".join(
        f'<c:dPt><c:idx val="{i}"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="{RING_COLOURS[i % len(RING_COLOURS)]}"/></a:solidFill></c:spPr></c:dPt>'
        for i in range(RING_COUNT))
    series = (
        '<c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:v>Структура расходов</c:v></c:tx>'
        f'{points}'
        '<c:dLbls><c:numFmt formatCode="0%" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
        '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="ru-RU"/></a:p></c:txPr>'
        '<c:showLegendKey val="0"/><c:showVal val="0"/><c:showCatName val="0"/><c:showSerName val="0"/>'
        '<c:showPercent val="1"/><c:showBubbleSize val="0"/><c:showLeaderLines val="1"/></c:dLbls>'
        f'<c:cat><c:strRef><c:f>{_xml_escape(_ref("A", first, last))}</c:f></c:strRef></c:cat>'
        f'<c:val><c:numRef><c:f>{_xml_escape(_ref("B", first, last))}</c:f></c:numRef></c:val></c:ser>'
    )
    body = (
        _rich_title("Структура расходов проекта")
        + '<c:plotArea><c:layout/><c:doughnutChart><c:varyColors val="1"/>' + series
        + '<c:firstSliceAng val="0"/><c:holeSize val="55"/></c:doughnutChart></c:plotArea>'
        '<c:legend><c:legendPos val="r"/><c:overlay val="0"/>'
        '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="ru-RU"/></a:p></c:txPr></c:legend>'
    )
    return _chart_space(body)


def debt_chart_xml(last_column: str) -> bytes:
    cat = f"'{DATA_SHEET}'!$D${MONTH_LABEL_ROW}:${last_column}${MONTH_LABEL_ROW}"
    debt = f"'{DATA_SHEET}'!$D${MONTH_DEBT_ROW}:${last_column}${MONTH_DEBT_ROW}"
    escrow = f"'{DATA_SHEET}'!$D${MONTH_ESCROW_ROW}:${last_column}${MONTH_ESCROW_ROW}"
    bar = (
        '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
        '<c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:v>Долг всего (БРИДЖ + ПФ)</c:v></c:tx>'
        f'<c:spPr><a:solidFill><a:srgbClr val="{NAVY}"/></a:solidFill></c:spPr><c:invertIfNegative val="0"/>'
        f'<c:cat><c:numRef><c:f>{_xml_escape(cat)}</c:f></c:numRef></c:cat>'
        f'<c:val><c:numRef><c:f>{_xml_escape(debt)}</c:f></c:numRef></c:val></c:ser>'
        '<c:gapWidth val="30"/><c:axId val="520001"/><c:axId val="520002"/></c:barChart>'
    )
    line = (
        '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>'
        '<c:ser><c:idx val="1"/><c:order val="1"/><c:tx><c:v>Эскроу на конец месяца</c:v></c:tx>'
        f'<c:spPr><a:ln w="22225"><a:solidFill><a:srgbClr val="{GREEN}"/></a:solidFill></a:ln></c:spPr>'
        '<c:marker><c:symbol val="none"/></c:marker>'
        f'<c:cat><c:numRef><c:f>{_xml_escape(cat)}</c:f></c:numRef></c:cat>'
        f'<c:val><c:numRef><c:f>{_xml_escape(escrow)}</c:f></c:numRef></c:val><c:smooth val="0"/></c:ser>'
        '<c:marker val="1"/><c:axId val="520001"/><c:axId val="520002"/></c:lineChart>'
    )
    body = (
        _rich_title("Долг и эскроу по месяцам, млн ₽")
        + "<c:plotArea><c:layout/>" + bar + line + _axes(520001, 520002, "mm.yy") + "</c:plotArea>"
        '<c:legend><c:legendPos val="b"/><c:overlay val="0"/>'
        '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="800"/></a:pPr><a:endParaRPr lang="ru-RU"/></a:p></c:txPr></c:legend>'
    )
    return _chart_space(body)


def drawing_xml(rel_ids: list[str]) -> bytes:
    anchors = []
    for index, ((c0, c1), rel) in enumerate(zip(CHART_SLOTS, rel_ids), 1):
        anchors.append(
            "<xdr:twoCellAnchor>"
            f"<xdr:from><xdr:col>{c0}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{CHART_TOP_ROW - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f"<xdr:to><xdr:col>{c1}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{CHART_BOTTOM_ROW}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
            f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{index + 1}" name="Диаграмма {index}"/>'
            "<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>"
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            f'<a:graphic><a:graphicData uri="{_CHART_NS}"><c:chart xmlns:c="{_CHART_NS}" xmlns:r="{_REL_NS}" r:id="{rel}"/>'
            "</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<xdr:wsDr xmlns:xdr="{_DRAWING_NS}" xmlns:a="{_DRAWINGML_NS}">{"".join(anchors)}</xdr:wsDr>'
    ).encode("utf-8")


def drawing_rels_xml(targets: list[tuple[str, str]]) -> bytes:
    links = "".join(
        f'<Relationship Type="{_REL_NS}/chart" Target="{target}" Id="{rel}" />'
        for rel, target in targets)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<Relationships xmlns="{_PKG_REL_NS}">{links}</Relationships>'
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Где в архиве лежат части дашборда — спрашиваем у книги, а не помним числом.
# ---------------------------------------------------------------------------
def locate(archive: Any, sheet_path: str) -> dict[str, Any]:
    """Пути листа «Дашборд», его рисунка и диаграмм.

    `sheet_path` — путь листа (его даёт `_v4_sheet_path`). Рисунок ищется в
    связях листа, диаграммы — в связях рисунка: номера частей в разных
    выпусках шаблона могут отличаться, а имя листа — контракт.
    """
    name = sheet_path.rsplit("/", 1)[-1]
    rels_path = f"xl/worksheets/_rels/{name}.rels"
    rels = archive.read(rels_path).decode("utf-8")
    drawing = re.search(r'<Relationship [^>]*relationships/drawing"[^>]*/>', rels)
    if not drawing:
        raise ValueError("у листа «Дашборд» нет рисунка")
    drawing_rel = re.search(r'Id="([^"]+)"', drawing.group(0)).group(1)
    drawing_target = re.search(r'Target="([^"]+)"', drawing.group(0)).group(1)
    drawing_path = "xl/" + drawing_target.lstrip("/").removeprefix("xl/")
    drawing_name = drawing_path.rsplit("/", 1)[-1]
    drawing_rels_path = f"xl/drawings/_rels/{drawing_name}.rels"
    chart_rels = archive.read(drawing_rels_path).decode("utf-8")
    charts: list[tuple[str, str]] = []
    for item in re.findall(r'<Relationship [^>]*relationships/chart"[^>]*/>', chart_rels):
        rel = re.search(r'Id="([^"]+)"', item).group(1)
        target = re.search(r'Target="([^"]+)"', item).group(1)
        charts.append((rel, "xl/" + target.lstrip("/").removeprefix("xl/")))
    return {"sheet_path": sheet_path, "drawing_rel": drawing_rel, "drawing_path": drawing_path,
            "drawing_rels_path": drawing_rels_path, "charts": charts}


def workbook_with_data_sheet(workbook: str) -> str:
    """Скрытый лист-источник — последним в книге."""
    if f'name="{DATA_SHEET}"' in workbook:
        return workbook
    sheet = (f'<x:sheet name="{DATA_SHEET}" sheetId="{DATA_SHEET_ID}" state="hidden" '
             f'r:id="{DATA_REL_ID}" {_R_NS} />')
    return workbook.replace("</x:sheets>", sheet + "</x:sheets>", 1)


def rels_with_data_sheet(rels: str) -> str:
    link = (f'<Relationship Type="{_REL_NS}/worksheet" Target="/{DATA_SHEET_PATH}" '
            f'Id="{DATA_REL_ID}" />')
    return rels.replace("</Relationships>", link + "</Relationships>", 1)


def types_with_data_sheet(types: str, dropped_parts: list[str]) -> str:
    override = (f'<Override PartName="/{DATA_SHEET_PATH}" ContentType='
                '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml" />')
    for part in dropped_parts:
        types = re.sub(r'<Override PartName="/%s"[^>]*/>' % re.escape(part), "", types)
    return types.replace("</Types>", override + "</Types>", 1)


def build(archive: Any, sheet_path: str, styles_xml: str, origin: dict[str, Any],
          llcr_target: float, month_columns: list[str], phased: bool) -> dict[str, Any]:
    """Собрать все части дашборда. Возвращает словарь «путь → байты» и
    новый styles.xml; лишние диаграммы шаблона названы в `dropped`."""
    where = locate(archive, sheet_path)
    styles = Styles(styles_xml)
    last_column = month_columns[-1]
    charts = [bridge_chart_xml(), ring_chart_xml(), debt_chart_xml(last_column)]
    existing = where["charts"]
    parts: dict[str, bytes] = {}
    rel_ids: list[str] = []
    targets: list[tuple[str, str]] = []
    for index, chart in enumerate(charts):
        if index < len(existing):
            rel, path = existing[index]
        else:
            rel, path = f"RidDashChart{index + 1:04d}", f"xl/drawings/charts/chartDash{index + 1}.xml"
        parts[path] = chart
        rel_ids.append(rel)
        targets.append((rel, "/" + path))
    dropped = [path for _rel, path in existing[len(charts):]]
    parts[where["drawing_path"]] = drawing_xml(rel_ids)
    parts[where["drawing_rels_path"]] = drawing_rels_xml(targets)
    parts[sheet_path] = build_dashboard_sheet(styles, where["drawing_rel"], phased).encode("utf-8")
    parts[DATA_SHEET_PATH] = build_data_sheet(origin, llcr_target, last_column, month_columns).encode("utf-8")
    added_charts = [path for _rel, path in targets if path.lstrip("/") not in {p for _r, p in existing}]
    return {"parts": parts, "styles_xml": styles.render(), "dropped": dropped,
            "added_charts": [p.lstrip("/") for p in added_charts], "styles_added": styles.added}
