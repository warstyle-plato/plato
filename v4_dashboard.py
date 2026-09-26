"""Лист «Дашборд» книги v4 и его скрытый источник `Dashboard_Data`.

Устройство (ТЗ владельца, 19.09.2026): у книги один источник значений для
дашборда — скрытый лист `Dashboard_Data`, где каждая величина ФОРМУЛОЙ читает
листы книги (ПРОВЕРКИ, ОТЧЕТ, ТЭП, CAPEX, ВРИ, СРОКИ, CF), а сам «Дашборд» —
только формулы на `Dashboard_Data`. Правка вводной в книге двигает дашборд так
же, как ОТЧЁТ; хардов экономики здесь ноль по построению — единственное число,
которое пишем мы, это целевой LLCR банка, и оно подписано вводной.

Состав листа — страница «Итог» тизера (образцы владельца, 21.09.2026):
показатели эффективности, ТЭП, доходы и удельные на метр, цены и темп продаж,
себестоимость строительства по статьям, структура расходов проекта,
финансовая деятельность и налоги, сроки очередей и график долга и эскроу.
Раскладка узкая — двенадцать колонок, блоки идут вниз: листать вправо не
нужно (просьба владельца).

KPI читаются из колонки B блока паритета листа ПРОВЕРКИ: это книжная сторона
той же величины, которую паритет сверяет с движком. Второй список «где в
книге выручка» разошёлся бы с первым молча — поэтому здесь его нет.

Модуль не знает движка: состав карточек и рисков приходит из
`presentation.py`, строки статей CAPEX — из книги (карта строк передаётся
сборщиком), а числа — из модели представления (только для подписи
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
# Блоки идут друг за другом, и первая строка каждого считается от длины
# предыдущего: число, записанное руками, разошлось бы с составом молча.
# ---------------------------------------------------------------------------
_PARITY = {
    "revenue_mln": 76, "capex_mln": 77, "ebitda_mln": 78, "financing_mln": 79,
    "tax_mln": 80, "net_profit_mln": 81, "llcr": 82, "peak_bridge_mln": 83,
    "peak_pf_mln": 84, "vat_mln": 86, "pf_shortfall_mln": 87,
}
_CF_SHEETS = ("CF_1", "CF_2", "CF_3", "CF_4")
QUEUE_COUNT = len(_CF_SHEETS)
# Строки очередей на листах книги: «Вводные» 88–91, «СРОКИ» блоками по 10,
# «ВРИ» — по 13, «ОБЪЕКТЫ» (аллокация CAPEX объектов) — по 8.
_QUEUE_INPUT_ROWS = (88, 89, 90, 91)
_TERMS_SALES_ROWS = (9, 19, 29, 39)
_TERMS_BUILD_ROWS = (10, 20, 30, 40)
_VRI_PRINCIPAL_ROWS = (12, 25, 38, 51)
_VRI_INTEREST_ROWS = (13, 26, 39, 52)
_VRI_SECURITY_ROWS = (14, 27, 40, 53)
_OBJECT_CAPEX_ROWS = (96, 104, 112, 120)


def _cf_sum(cell: str) -> str:
    return "SUM(" + ",".join(f"'{s}'!{cell}" for s in _CF_SHEETS) + ")"


def _rve_max() -> str:
    return "MAX(" + ",".join(f"'{s}'!B8*'{s}'!B5" for s in _CF_SHEETS) + ")"


def _rve_release() -> str:
    """Раскрытие эскроу в месяц РВЭ каждой очереди — как считает движок."""
    return "SUM(" + ",".join(
        f"SUMIF('{s}'!$D$3:$GA$3,'{s}'!$B$8,'{s}'!$D$14:$GA$14)" for s in _CF_SHEETS) + ")"


def _sheet_sum(sheet: str, column: str, rows: tuple[int, ...]) -> str:
    return "SUM(" + ",".join(f"'{sheet}'!{column}{r}" for r in rows) + ")"


# ГНС наземная — база удельных на метр ГНС (движок: `project_above_gns`):
# ГНС проекта без подземного паркинга и кладовых. Продаваемая — итог ТЭП.
_GNS_ABOVE = "'ТЭП'!C36-SUM('ТЭП'!C6,'ТЭП'!C12,'ТЭП'!C18,'ТЭП'!C24)"
_SALEABLE = "'ТЭП'!D36"

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
    # Страница «Итог»: эффективность, финансовая деятельность, базы удельных.
    ("irr_equity", "IRR собственного капитала", "%", "'ОТЧЕТ'!B14"),
    ("full_project_cost_mln", "Полные расходы проекта (с НДС)", "млн ₽",
     f"'ОТЧЕТ'!B82+'ПРОВЕРКИ'!B{_PARITY['vat_mln']}"),
    ("peak_escrow_mln", "Пик эскроу", "млн ₽", "'ОТЧЕТ'!B18"),
    ("rve_escrow_release_mln", "Раскрыто эскроу в РВЭ", "млн ₽", _rve_release()),
    ("bridge_interest_mln", "Проценты БРИДЖа", "млн ₽", "'ОТЧЕТ'!G13"),
    ("pf_interest_mln", "Проценты ПФ", "млн ₽", "'ОТЧЕТ'!G14"),
    ("pf_limit_fee_mln", "Плата за лимит ПФ", "млн ₽", _cf_sum("B43")),
    ("issue_fees_mln", "Комиссии выдачи (БРИДЖ и резервирование ПФ)", "млн ₽", _cf_sum("B57")),
    ("gns_above_sqm", "ГНС наземная (база удельных)", "м²", _GNS_ABOVE),
    ("saleable_sqm", "Продаваемая площадь (база удельных)", "м²", _SALEABLE),
)
DATA_ROWS: dict[str, int] = {item[0]: index + 2 for index, item in enumerate(DATA_ITEMS)}
DATA_LAST_ROW = 1 + len(DATA_ITEMS)


def data_cell(key: str, column: str = "C") -> str:
    return f"'{DATA_SHEET}'!${column}${DATA_ROWS[key]}"


# Продукты: ключ движка → подпись и формулы книги (ГНС, продаваемая, единицы,
# выручка, стартовая цена первой очереди, темп продаж до РВЭ).
PRODUCT_HEADER_ROW = DATA_LAST_ROW + 2
PRODUCT_FIRST_ROW = PRODUCT_HEADER_ROW + 1


def _tep_sum(col: str, shift: int) -> str:
    return "SUM(" + ",".join(f"'ТЭП'!{col}{row + shift}" for row in (4, 10, 16, 22)) + ")"


PRODUCT_ITEMS: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    # key, label, gns, saleable, units, revenue_mln, start_price_th, pace_pre
    ("apartments", "Квартиры", "'ОТЧЕТ'!B46", "'ОТЧЕТ'!C46", "", _tep_sum("G", 0), "'ТЭП'!F4", "'ОТЧЕТ'!B87"),
    ("ground_commercial", "Коммерция первого этажа", "'ОТЧЕТ'!B47", "'ОТЧЕТ'!C47", "", _tep_sum("G", 1),
     "'ТЭП'!F5", "'ОТЧЕТ'!B88"),
    # ГНС подземного паркинга: у ОТЧЕТа она с 14.09.2026 стоит своей колонкой
    # «Подземная», а строка B48 обнулена, поэтому берётся из строк ТЭП очередей.
    ("underground_parking", "Подземный паркинг", _tep_sum("C", 2), "", _tep_sum("E", 2), _tep_sum("G", 2),
     "'ТЭП'!F6", "'ОТЧЕТ'!B89"),
    ("storage", "Кладовые", "", "", _tep_sum("E", 3), _tep_sum("G", 3), "'ТЭП'!F7", "'ОТЧЕТ'!B90"),
    ("offices", "МФОЦ / офисный центр", "'ТЭП'!C31", "'ТЭП'!D31", "", "'ТЭП'!G31", "'ТЭП'!F31", "'ОТЧЕТ'!B91"),
    ("standalone_retail", "Торговый центр / ОСЗ", "'ТЭП'!C32", "'ТЭП'!D32", "", "'ТЭП'!G32", "'ТЭП'!F32",
     "'ОТЧЕТ'!B92"),
    ("above_parking", "Наземный паркинг", "", "", "'ТЭП'!E33", "'ТЭП'!G33", "'ТЭП'!F33", "'ОТЧЕТ'!B93"),
)
PRODUCT_ROWS: dict[str, int] = {item[0]: PRODUCT_FIRST_ROW + index
                                for index, item in enumerate(PRODUCT_ITEMS)}
PRODUCT_TOTAL_ROW = PRODUCT_FIRST_ROW + len(PRODUCT_ITEMS)
# Колонки блока продуктов на Dashboard_Data.
PRODUCT_COLUMNS = {"label": "B", "gns": "C", "saleable": "D", "units": "E", "revenue": "F",
                   "avg_price": "G", "start_price": "H", "pace": "I", "per_gns": "J", "per_saleable": "K"}

RISK_HEADER_ROW = PRODUCT_TOTAL_ROW + 2
RISK_FIRST_ROW = RISK_HEADER_ROW + 1
RISK_ROWS: dict[str, int] = {item[0]: RISK_FIRST_ROW + index
                             for index, item in enumerate(RISK_CATALOGUE)}
RISK_LAST_ROW = RISK_FIRST_ROW + len(RISK_CATALOGUE) - 1

BRIDGE_HEADER_ROW = RISK_LAST_ROW + 2
BRIDGE_FIRST_ROW = BRIDGE_HEADER_ROW + 1
BRIDGE_LAST_ROW = BRIDGE_FIRST_ROW + len(BRIDGE_STEPS) - 1

# Структура расходов проекта — статьи движка (`expense_groups`) из ячеек
# книги. Порядок объявления; движок сортирует по убыванию, книга — нет:
# формульный лист не переставляет строки.
STRUCTURE_ITEMS: tuple[tuple[str, str], ...] = (
    ("Цена приобретения", "'ОТЧЕТ'!B33"),
    ("Смена ВРИ / земельные права",
     _sheet_sum("ВРИ", "B", _VRI_PRINCIPAL_ROWS) + "+" + _sheet_sum("ВРИ", "B", _VRI_SECURITY_ROWS)),
    ("Проценты по рассрочке ВРИ", _sheet_sum("ВРИ", "B", _VRI_INTEREST_ROWS)),
    ("ИРД и проектирование", "{ird}+{design_p}+{design_rd}+{author_supervision}"),
    ("Основное строительство", "{preparation}+{main_above}+{main_under}+{utilities}+{landscaping}"
                               "+{commissioning}+{site_maintenance}+{gc_fee}"),
    ("Отдельные объекты", _sheet_sum("ОБЪЕКТЫ", "B", _OBJECT_CAPEX_ROWS)),
    ("Социальная нагрузка", "'ОТЧЕТ'!B36"),
    ("Управление проектом", "{project_management}"),
    ("Технический заказчик / стройконтроль", "{technical_supervision}"),
    ("Резерв", "{reserve}"),
    ("Маркетинг и продажи", "'ОТЧЕТ'!B7"),
    ("Проценты и комиссии", "'ОТЧЕТ'!B9"),
    ("Налог на прибыль", "'ОТЧЕТ'!B11"),
    ("НДС", f"'ПРОВЕРКИ'!B{_PARITY['vat_mln']}"),
)
STRUCTURE_HEADER_ROW = BRIDGE_LAST_ROW + 2
STRUCTURE_FIRST_ROW = STRUCTURE_HEADER_ROW + 1
STRUCTURE_TOTAL_ROW = STRUCTURE_FIRST_ROW + len(STRUCTURE_ITEMS)

# Себестоимость строительства — статьи CAPEX, как их печатает отчёт движка
# (`construction_costs`): подпись и ключи статей книги. Строки статей на листе
# CAPEX первой очереди и шаг блока очереди передаёт сборщик книги.
COST_ITEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ИРД", ("ird",)),
    ("Проектирование (П, РД) и авторский надзор", ("design_p", "design_rd", "author_supervision")),
    ("Подготовка территории", ("preparation",)),
    ("СМР наземной части", ("main_above",)),
    ("СМР подземной части", ("main_under",)),
    ("Наружные инженерные сети", ("utilities",)),
    ("Благоустройство", ("landscaping",)),
    ("Сдача и ввод", ("commissioning",)),
    ("Содержание стройплощадки", ("site_maintenance",)),
    ("Вознаграждение генподрядчика", ("gc_fee",)),
    ("Технический заказчик / стройконтроль", ("technical_supervision",)),
    ("Управление проектом", ("project_management",)),
    ("Резерв", ("reserve",)),
)
COST_HEADER_ROW = STRUCTURE_TOTAL_ROW + 2
COST_FIRST_ROW = COST_HEADER_ROW + 1
COST_TOTAL_ROW = COST_FIRST_ROW + len(COST_ITEMS)

MONTH_LABEL_ROW = COST_TOTAL_ROW + 2
MONTH_DEBT_ROW = MONTH_LABEL_ROW + 1
MONTH_ESCROW_ROW = MONTH_LABEL_ROW + 2

# Очереди: имя, включена, старт, РнС, РВЭ, продажи с/по, стройка мес., продажи
# мес., конец стройки. Даты — те же ячейки, что у листа СРОКИ.
QUEUE_HEADER_ROW = MONTH_ESCROW_ROW + 2
QUEUE_FIRST_ROW = QUEUE_HEADER_ROW + 1
QUEUE_LAST_ROW = QUEUE_FIRST_ROW + QUEUE_COUNT - 1
QUEUE_COLUMNS = {"name": "A", "on": "B", "start": "C", "permit": "D", "rve": "E", "sales_start": "F",
                 "sales_end": "G", "build_months": "H", "sales_months": "I", "build_end": "J"}

ORIGIN_HEADER_ROW = QUEUE_LAST_ROW + 2
ORIGIN_FIRST_ROW = ORIGIN_HEADER_ROW + 1
ORIGIN_ITEMS = ("calculation_id", "engine_version", "generated_at", "template")


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
def _capex_article(key: str, capex_rows: dict[str, int], capex_stride: int) -> str:
    """Статья CAPEX по всем очередям: строка первой очереди плюс шаг блока."""
    if key not in capex_rows:
        raise KeyError(f"статья CAPEX без строки в книге: {key}")
    row = capex_rows[key]
    return "SUM(" + ",".join(f"'CAPEX'!B{row + capex_stride * q}" for q in range(QUEUE_COUNT)) + ")"


def build_data_sheet(origin: dict[str, Any], llcr_target: float, last_column: str,
                     month_columns: list[str], capex_rows: dict[str, int],
                     capex_stride: int) -> str:
    """Скрытый лист-источник: каждая величина — формула на листы книги.

    `month_columns` — колонки месяцев листа CF (D..GA): ряды долга и эскроу
    копируются помесячно, чтобы график перестраивался в Excel сам.
    `capex_rows`/`capex_stride` — где на листе CAPEX стоят статьи первой
    очереди и через сколько строк повторяется блок очереди.
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

    def header_row(number: int, titles: tuple[tuple[str, str], ...]) -> None:
        rows.append(_row(number, [(f"{c}{number}", _cell(f"{c}{number}", text=t)) for c, t in titles]))

    # Продукты: ключ, подпись, ГНС, продаваемая, единицы, выручка, средняя цена,
    # стартовая цена, темп до РВЭ, выручка на м² ГНС (на штуку), на м² прод.
    header_row(PRODUCT_HEADER_ROW, (
        ("A", "продукт"), ("B", "подпись"), ("C", "ГНС, м²"), ("D", "продаваемая, м²"),
        ("E", "единиц, шт."), ("F", "выручка, млн ₽"), ("G", "средняя цена, тыс ₽"),
        ("H", "стартовая цена, тыс ₽"), ("I", "темп до РВЭ, в мес."),
        ("J", "выручка на м² ГНС / на шт., тыс ₽"), ("K", "выручка на м² прод., тыс ₽")))
    for key, label, gns, saleable, units, revenue, start_price, pace in PRODUCT_ITEMS:
        r = PRODUCT_ROWS[key]
        cells = [(f"A{r}", _cell(f"A{r}", text=key)), (f"B{r}", _cell(f"B{r}", text=label)),
                 (f"F{r}", _cell(f"F{r}", formula=revenue)),
                 (f"H{r}", _cell(f"H{r}", formula=start_price)),
                 (f"I{r}", _cell(f"I{r}", formula=pace))]
        cells.append((f"C{r}", _cell(f"C{r}", formula=gns) if gns else _cell(f"C{r}")))
        cells.append((f"D{r}", _cell(f"D{r}", formula=saleable) if saleable else _cell(f"D{r}")))
        cells.append((f"E{r}", _cell(f"E{r}", formula=units) if units else _cell(f"E{r}")))
        base = f"D{r}" if saleable else (f"E{r}" if units else "")
        cells.append((f"G{r}", _cell(f"G{r}", formula=f"IFERROR(F{r}*1000/{base},0)") if base
                      else _cell(f"G{r}")))
        # Штучный продукт — на штуку (у машино-места метры ГНС ни с чем не
        # сравнимы), метровый — на свою ГНС; так же считает движок.
        per_gns = f"E{r}" if units else (f"C{r}" if gns else "")
        cells.append((f"J{r}", _cell(f"J{r}", formula=f"IFERROR(F{r}*1000/{per_gns},0)") if per_gns
                      else _cell(f"J{r}")))
        cells.append((f"K{r}", _cell(f"K{r}", formula=f"IFERROR(F{r}*1000/D{r},0)") if saleable
                      else _cell(f"K{r}")))
        rows.append(_row(r, cells))
    t = PRODUCT_TOTAL_ROW
    first, last = PRODUCT_FIRST_ROW, PRODUCT_TOTAL_ROW - 1
    rows.append(_row(t, [(f"A{t}", _cell(f"A{t}", text="total")), (f"B{t}", _cell(f"B{t}", text="Итого")),
                         (f"C{t}", _cell(f"C{t}", formula=f"SUM(C{first}:C{last})")),
                         (f"D{t}", _cell(f"D{t}", formula=f"SUM(D{first}:D{last})")),
                         (f"E{t}", _cell(f"E{t}", formula=f"SUM(E{first}:E{last})")),
                         (f"F{t}", _cell(f"F{t}", formula=f"SUM(F{first}:F{last})")),
                         (f"J{t}", _cell(f"J{t}", formula=f"IFERROR(F{t}*1000/{data_cell('gns_above_sqm')},0)")),
                         (f"K{t}", _cell(f"K{t}", formula=f"IFERROR(F{t}*1000/{data_cell('saleable_sqm')},0)"))]))

    # Риски: ключ, подпись, признак 0/1, величина рядом.
    header_row(RISK_HEADER_ROW, (
        ("A", "риск"), ("B", "подпись"), ("C", "сработал (1/0)"), ("D", "величина"), ("E", "чья очередь")))
    weakest_llcr = "MIN(" + ",".join(
        f"IF('{s}'!B5=1,'{s}'!B85,9999)" for s in _CF_SHEETS) + ")"
    queues_on = "(" + "+".join(f"'{s}'!B5" for s in _CF_SHEETS) + ")"
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
    header_row(BRIDGE_HEADER_ROW, (("A", "мост"), ("B", "млн ₽ со знаком")))
    for index, (key, label, sign) in enumerate(BRIDGE_STEPS):
        r = BRIDGE_FIRST_ROW + index
        formula = data_cell(key, "C") if sign > 0 else f"-{data_cell(key, 'C')}"
        rows.append(_row(r, [(f"A{r}", _cell(f"A{r}", text=label)), (f"B{r}", _cell(f"B{r}", formula=formula))]))

    # Структура расходов проекта: статья, млн ₽, доля, на м² ГНС, на м² прод.
    articles = {key: _capex_article(key, capex_rows, capex_stride) for key in capex_rows}
    header_row(STRUCTURE_HEADER_ROW, (
        ("A", "структура расходов"), ("B", "млн ₽"), ("C", "доля"),
        ("D", "на м² ГНС, тыс ₽"), ("E", "на м² прод., тыс ₽")))
    first, last, t = STRUCTURE_FIRST_ROW, STRUCTURE_TOTAL_ROW - 1, STRUCTURE_TOTAL_ROW
    for index, (label, formula) in enumerate(STRUCTURE_ITEMS):
        r = STRUCTURE_FIRST_ROW + index
        rows.append(_row(r, [
            (f"A{r}", _cell(f"A{r}", text=label)),
            (f"B{r}", _cell(f"B{r}", formula=formula.format(**articles))),
            (f"C{r}", _cell(f"C{r}", formula=f"IFERROR(B{r}/$B${t},0)")),
            (f"D{r}", _cell(f"D{r}", formula=f"IFERROR(B{r}*1000/{data_cell('gns_above_sqm')},0)")),
            (f"E{r}", _cell(f"E{r}", formula=f"IFERROR(B{r}*1000/{data_cell('saleable_sqm')},0)")),
        ]))
    rows.append(_row(t, [
        (f"A{t}", _cell(f"A{t}", text="Итого")),
        (f"B{t}", _cell(f"B{t}", formula=f"SUM(B{first}:B{last})")),
        (f"C{t}", _cell(f"C{t}", formula=f"SUM(C{first}:C{last})")),
        (f"D{t}", _cell(f"D{t}", formula=f"SUM(D{first}:D{last})")),
        (f"E{t}", _cell(f"E{t}", formula=f"SUM(E{first}:E{last})")),
    ]))

    # Себестоимость строительства: статья, млн ₽, на м² ГНС, на м² прод.
    header_row(COST_HEADER_ROW, (
        ("A", "себестоимость строительства"), ("B", "млн ₽"),
        ("C", "на м² ГНС, тыс ₽"), ("D", "на м² прод., тыс ₽")))
    first, last, t = COST_FIRST_ROW, COST_TOTAL_ROW - 1, COST_TOTAL_ROW
    for index, (label, keys) in enumerate(COST_ITEMS):
        r = COST_FIRST_ROW + index
        rows.append(_row(r, [
            (f"A{r}", _cell(f"A{r}", text=label)),
            (f"B{r}", _cell(f"B{r}", formula="+".join(articles[k] for k in keys))),
            (f"C{r}", _cell(f"C{r}", formula=f"IFERROR(B{r}*1000/{data_cell('gns_above_sqm')},0)")),
            (f"D{r}", _cell(f"D{r}", formula=f"IFERROR(B{r}*1000/{data_cell('saleable_sqm')},0)")),
        ]))
    rows.append(_row(t, [
        (f"A{t}", _cell(f"A{t}", text="Итого")),
        (f"B{t}", _cell(f"B{t}", formula=f"SUM(B{first}:B{last})")),
        (f"C{t}", _cell(f"C{t}", formula=f"SUM(C{first}:C{last})")),
        (f"D{t}", _cell(f"D{t}", formula=f"SUM(D{first}:D{last})")),
    ]))

    # Помесячные ряды долга и эскроу — колонки CF без пересчёта.
    for r, label, cf_row in ((MONTH_LABEL_ROW, "месяц", 3), (MONTH_DEBT_ROW, "долг всего, млн ₽", 19),
                             (MONTH_ESCROW_ROW, "эскроу на конец, млн ₽", 9)):
        cells = [(f"A{r}", _cell(f"A{r}", text=label))]
        for column in month_columns:
            cells.append((f"{column}{r}", _cell(f"{column}{r}", formula=f"'CF'!{column}{cf_row}")))
        rows.append(_row(r, cells))

    # Очереди: даты и сроки — те же ячейки, что у листа СРОКИ.
    header_row(QUEUE_HEADER_ROW, (
        ("A", "очередь"), ("B", "включена (1/0)"), ("C", "старт"), ("D", "РнС / открытие ПФ"),
        ("E", "РВЭ"), ("F", "продажи с"), ("G", "продажи по"), ("H", "стройка, мес."),
        ("I", "продажи, мес."), ("J", "конец стройки")))
    for q in range(QUEUE_COUNT):
        r = QUEUE_FIRST_ROW + q
        cf = _CF_SHEETS[q]
        inp = _QUEUE_INPUT_ROWS[q]
        rows.append(_row(r, [
            (f"A{r}", _cell(f"A{r}", formula=f"'Вводные'!$C${inp}")),
            (f"B{r}", _cell(f"B{r}", formula=f"'{cf}'!B5")),
            (f"C{r}", _cell(f"C{r}", formula=f"'{cf}'!B6")),
            (f"D{r}", _cell(f"D{r}", formula=f"'{cf}'!B7")),
            (f"E{r}", _cell(f"E{r}", formula=f"'{cf}'!B8")),
            (f"F{r}", _cell(f"F{r}", formula=f"'СРОКИ'!C{_TERMS_SALES_ROWS[q]}")),
            (f"G{r}", _cell(f"G{r}", formula=f"'СРОКИ'!D{_TERMS_SALES_ROWS[q]}")),
            (f"H{r}", _cell(f"H{r}", formula=f"'Вводные'!$F${inp}")),
            (f"I{r}", _cell(f"I{r}", formula=f"'Вводные'!$H${inp}")),
            (f"J{r}", _cell(f"J{r}", formula=f"'СРОКИ'!D{_TERMS_BUILD_ROWS[q]}")),
        ]))

    # Происхождение: текст, а не число — и потому не хард экономики.
    header_row(ORIGIN_HEADER_ROW, (("A", "происхождение"),))
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
        '<x:col min="3" max="11" width="16" customWidth="1" /></x:cols>'
        f'<x:sheetData>{"".join(rows)}</x:sheetData>'
        '<x:pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3" />'
        "</x:worksheet>"
    )


# ---------------------------------------------------------------------------
# Лист «Дашборд»: только формулы на Dashboard_Data. Двенадцать колонок,
# блоки идут вниз в порядке страницы «Итог» тизера.
# ---------------------------------------------------------------------------
WIDTH = 12                                   # колонок A..L
COLUMN_WIDTH = 12.5
CARD_SLOTS = ((0, 3), (4, 7), (8, 11))       # три карточки в ряд (индексы колонок)
LEFT_HALF, RIGHT_HALF = (0, 5), (6, 11)      # две половины листа
GANTT_YEARS = WIDTH - 2                      # колонки C..L — по году на колонку
CHART_ROWS_WIDE = 18
CHART_ROWS_PAIR = 16
_FORMATS = {"млн ₽": 207, "доля": 202, "%": 202, "x": 206, "мес.": 201, "дата": 200, "м²": 203,
            "шт.": 203, "тыс ₽": 203, "в мес.": 203, "текст": 211, "лет": 210}


def _value_style(styles: Styles, unit: str, card: bool) -> int:
    fmt = _FORMATS.get(unit, 207)
    if card:
        return styles.xf(fmt, font=3, fill=4, border=5, halign="center", valign="center")
    if unit == "текст":
        return styles.xf(fmt, font=8, fill=0, border=0, halign="left")
    return styles.xf(fmt, font=8, fill=0, border=0, halign="right")


class _Sheet:
    """Строки листа по курсору: блок кладётся под предыдущим, номера строк
    считаются, а не записываются. Объединения — по группам колонок."""

    def __init__(self, styles: Styles) -> None:
        self.styles = styles
        self.rows: list[str] = []
        self.merges: list[str] = []
        self.next_row = 1
        self.anchors: list[tuple[int, int, int, int]] = []
        st = styles
        self.title = st.xf(0, font=1, fill=2, border=0, halign="left", valign="center")
        self.subtitle = st.xf(0, font=2, fill=0, border=0, halign="left")
        self.section = st.xf(0, font=1, fill=6, border=13, halign="left", valign="center")
        self.card_label = st.xf(0, font=1, fill=6, border=0, halign="center")
        self.th = st.xf(0, font=1, fill=5, border=0, halign="center", valign="center", wrap=True)
        self.td = st.xf(0, font=8, fill=0, border=0, halign="left")
        self.td_muted = st.xf(0, font=2, fill=0, border=0, halign="left")
        self.bold_td = st.xf(0, font=3, fill=7, border=13, halign="left")
        self.risk_on = st.xf(0, font=st.font(RED, bold=True), fill=0, border=0, halign="center")
        self.gantt_build = st.xf(0, font=st.font(NAVY, size=8), fill=0, border=0, halign="left")
        self.gantt_sales = st.xf(0, font=st.font(GREEN, size=8), fill=0, border=0, halign="left")
        self.year = st.xf(201, font=1, fill=5, border=0, halign="center")

    def bold_value(self, unit: str) -> int:
        return self.styles.xf(_FORMATS.get(unit, 207), font=3, fill=7, border=13, halign="right")

    def value(self, unit: str) -> int:
        return _value_style(self.styles, unit, card=False)

    # --- строки ---------------------------------------------------------------
    def put(self, cells: dict[int, str], style: int, height: float | None = None,
            styles: dict[int, int] | None = None) -> int:
        """Строка целиком: у каждой из 12 колонок есть ячейка со стилем.
        `cells` — индекс колонки → готовый xml ячейки; остальные пустые."""
        r = self.next_row
        row: list[tuple[str, str]] = []
        for i in range(WIDTH):
            c = f"{_col(i)}{r}"
            row.append((c, cells.get(i) or _cell(c, style=(styles or {}).get(i, style))))
        self.rows.append(_row(r, row, height=height))
        self.next_row += 1
        return r

    def merge(self, r: int, first: int, last: int) -> None:
        if last > first:
            self.merges.append(f"{_col(first)}{r}:{_col(last)}{r}")

    def blank(self, count: int = 1) -> None:
        for _ in range(count):
            self.put({}, self.td)

    def band(self, text: str | None, formula: str | None, style: int, height: float) -> int:
        r = self.next_row
        c = f"A{r}"
        self.put({0: _cell(c, text=text, formula=formula, style=style)}, style, height=height)
        self.merge(r, 0, WIDTH - 1)
        return r

    def section_row(self, left: str, right: str | None = None) -> int:
        r = self.next_row
        cells = {0: _cell(f"A{r}", text=left, style=self.section)}
        if right is not None:
            cells[RIGHT_HALF[0]] = _cell(f"{_col(RIGHT_HALF[0])}{r}", text=right, style=self.section)
            self.put(cells, self.section, height=18)
            self.merge(r, *LEFT_HALF)
            self.merge(r, *RIGHT_HALF)
        else:
            self.put(cells, self.section, height=18)
            self.merge(r, 0, WIDTH - 1)
        return r

    def header(self, groups: list[tuple[int, int]], titles: list[str], height: float = 28) -> int:
        r = self.next_row
        cells = {g[0]: _cell(f"{_col(g[0])}{r}", text=t, style=self.th) for g, t in zip(groups, titles)}
        self.put(cells, self.th, height=height)
        for g in groups:
            self.merge(r, *g)
        return r

    def line(self, groups: list[tuple[int, int]], items: list[tuple[str | None, str | None, int]],
             fill_style: int | None = None) -> int:
        """Строка таблицы: на группу — (текст, формула, стиль)."""
        r = self.next_row
        cells: dict[int, str] = {}
        styles: dict[int, int] = {}
        for (first, last), (text, formula, style) in zip(groups, items):
            cells[first] = _cell(f"{_col(first)}{r}", text=text, formula=formula, style=style)
            for i in range(first, last + 1):
                styles[i] = style
        self.put(cells, fill_style if fill_style is not None else self.td, styles=styles)
        for g in groups:
            self.merge(r, *g)
        return r

    def chart_slot(self, rows: int, slots: list[tuple[int, int]]) -> None:
        top = self.next_row
        for _ in range(rows):
            self.put({}, self.td)
        for c0, c1 in slots:
            self.anchors.append((c0, top - 1, c1, top - 1 + rows))


# Группы колонок таблиц: (от, до) включительно, индексы колонок.
_G_TABLE_4 = [(0, 5), (6, 7), (8, 9), (10, 11)]          # подпись + три числа
_G_TABLE_5 = [(0, 3), (4, 5), (6, 7), (8, 9), (10, 11)]  # подпись + четыре
_G_KV_LEFT = [(0, 3), (4, 5)]
_G_KV_RIGHT = [(6, 9), (10, 11)]
_G_QUEUE = [(0, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 8), (9, 11)]


def _src(column: str, row: int) -> str:
    return f"'{DATA_SHEET}'!${column}${row}"


def build_dashboard_sheet(styles: Styles, drawing_rel_id: str, phased: bool) -> tuple[str, list[tuple[int, int, int, int]]]:
    """Лист «Дашборд» — формулы на Dashboard_Data, узкая вертикальная
    раскладка. Возвращает xml листа и якоря трёх диаграмм (мост, кольцо,
    долг и эскроу) — колонки и строки, куда их ставит рисунок."""
    sh = _Sheet(styles)
    del phased  # состав листа один для проекта в одну и в несколько очередей

    sh.band("DEVELOPAID · ИНВЕСТИЦИОННЫЙ ДАШБОРД", None, sh.title, 24)
    sh.band(None, data_cell("project_name"), sh.subtitle, 15)
    sh.blank()

    # Шесть карточек KPI — те же, что у тизера.
    cards = list(KPI_CATALOGUE[:CARD_COUNT])
    for band in range(2):
        r = sh.next_row
        label_cells = {}
        for slot, (left, right) in enumerate(CARD_SLOTS):
            _key, label, unit = cards[band * len(CARD_SLOTS) + slot]
            label_cells[left] = _cell(f"{_col(left)}{r}", text=f"{label}, {unit}", style=sh.card_label)
        sh.put(label_cells, sh.card_label)
        for left, right in CARD_SLOTS:
            sh.merge(r, left, right)
        top = sh.next_row
        for line in range(3):
            r = sh.next_row
            cells, line_styles = {}, {}
            for slot, (left, right) in enumerate(CARD_SLOTS):
                key, _label, unit = cards[band * len(CARD_SLOTS) + slot]
                style = _value_style(styles, unit, card=True)
                for i in range(left, right + 1):
                    line_styles[i] = style
                if line == 0:
                    cells[left] = _cell(f"{_col(left)}{r}", formula=data_cell(key), style=style)
            sh.put(cells, sh.td, height=20, styles=line_styles)
        for left, right in CARD_SLOTS:
            sh.merges.append(f"{_col(left)}{top}:{_col(right)}{top + 2}")
        sh.blank()

    # Показатели эффективности | финансирование и сроки — две колонки пар.
    sh.section_row("ПОКАЗАТЕЛИ ЭФФЕКТИВНОСТИ ПРОЕКТА", "ФИНАНСИРОВАНИЕ И СРОКИ")
    labels = {key: (label, unit) for key, label, unit in KPI_CATALOGUE}
    labels.update({key: (label, unit) for key, label, unit, _f in DATA_ITEMS if key not in labels})
    left_keys = ["ebitda_mln", "net_profit_mln", "margin", "irr_equity", "npv_mln", "term_months",
                 "llcr", "full_project_cost_mln"]
    right_keys = ["peak_bridge_mln", "peak_pf_mln", "financing_mln", "pf_shortfall_mln",
                  "project_start", "rve", "status"]
    for index in range(max(len(left_keys), len(right_keys))):
        items: list[tuple[str | None, str | None, int]] = []
        for keys in (left_keys, right_keys):
            if index < len(keys):
                key = keys[index]
                label, unit = labels[key]
                items += [(f"{label}, {unit}" if unit != "текст" else label, None, sh.td),
                          (None, data_cell(key), sh.value(unit))]
            else:
                items += [(None, None, sh.td), (None, None, sh.td)]
        sh.line(_G_KV_LEFT + _G_KV_RIGHT, items)
    sh.blank()

    # ТЭП — построено.
    P = PRODUCT_COLUMNS
    sh.section_row("ТЭП · ПОСТРОЕНО")
    sh.header(_G_TABLE_4, ["Продукт", "ГНС, м²", "Продаваемая, м²", "Единиц"])
    for key, *_rest in PRODUCT_ITEMS:
        src = PRODUCT_ROWS[key]
        sh.line(_G_TABLE_4, [(None, _src(P["label"], src), sh.td),
                             (None, _src(P["gns"], src), sh.value("м²")),
                             (None, _src(P["saleable"], src), sh.value("м²")),
                             (None, _src(P["units"], src), sh.value("шт."))])
    src = PRODUCT_TOTAL_ROW
    sh.line(_G_TABLE_4, [("Итого проект", None, sh.bold_td),
                         (None, _src(P["gns"], src), sh.bold_value("м²")),
                         (None, _src(P["saleable"], src), sh.bold_value("м²")),
                         (None, _src(P["units"], src), sh.bold_value("шт."))])
    sh.blank()

    # Доходы: выручка и удельные на метр.
    sh.section_row("ДОХОДЫ")
    sh.header(_G_TABLE_4, ["Продукт", "Выручка, млн ₽", "тыс ₽/м² ГНС (на шт.)", "тыс ₽/м² прод."])
    for key, *_rest in PRODUCT_ITEMS:
        src = PRODUCT_ROWS[key]
        sh.line(_G_TABLE_4, [(None, _src(P["label"], src), sh.td),
                             (None, _src(P["revenue"], src), sh.value("млн ₽")),
                             (None, _src(P["per_gns"], src), sh.value("тыс ₽")),
                             (None, _src(P["per_saleable"], src), sh.value("тыс ₽"))])
    src = PRODUCT_TOTAL_ROW
    sh.line(_G_TABLE_4, [("Всего", None, sh.bold_td),
                         (None, _src(P["revenue"], src), sh.bold_value("млн ₽")),
                         (None, _src(P["per_gns"], src), sh.bold_value("тыс ₽")),
                         (None, _src(P["per_saleable"], src), sh.bold_value("тыс ₽"))])
    sh.blank()

    # Цены реализации и темп продаж.
    sh.section_row("ЦЕНЫ РЕАЛИЗАЦИИ И ТЕМП ПРОДАЖ")
    sh.header(_G_TABLE_5, ["Продукт", "Средняя, тыс ₽", "Старт, тыс ₽", "Темп до РВЭ, в мес.", "Ед."])
    for key, _label, gns, saleable, units, *_rest in PRODUCT_ITEMS:
        src = PRODUCT_ROWS[key]
        unit = "шт." if (units and not saleable) else "м²"
        sh.line(_G_TABLE_5, [(None, _src(P["label"], src), sh.td),
                             (None, _src(P["avg_price"], src), sh.value("тыс ₽")),
                             (None, _src(P["start_price"], src), sh.value("тыс ₽")),
                             (None, _src(P["pace"], src), sh.value("в мес.")),
                             (unit, None, sh.value("текст"))])
    sh.blank()

    # Себестоимость строительства по статьям.
    sh.section_row("СЕБЕСТОИМОСТЬ СТРОИТЕЛЬСТВА")
    sh.header(_G_TABLE_4, ["Статья", "млн ₽", "тыс ₽/м² ГНС", "тыс ₽/м² прод."])
    for index in range(len(COST_ITEMS)):
        src = COST_FIRST_ROW + index
        sh.line(_G_TABLE_4, [(None, _src("A", src), sh.td),
                             (None, _src("B", src), sh.value("млн ₽")),
                             (None, _src("C", src), sh.value("тыс ₽")),
                             (None, _src("D", src), sh.value("тыс ₽"))])
    src = COST_TOTAL_ROW
    sh.line(_G_TABLE_4, [("Итого", None, sh.bold_td),
                         (None, _src("B", src), sh.bold_value("млн ₽")),
                         (None, _src("C", src), sh.bold_value("тыс ₽")),
                         (None, _src("D", src), sh.bold_value("тыс ₽"))])
    sh.blank()

    # Структура расходов проекта.
    sh.section_row("СТРУКТУРА РАСХОДОВ ПРОЕКТА")
    sh.header(_G_TABLE_4, ["Статья", "млн ₽", "Доля", "тыс ₽/м² прод."])
    for index in range(len(STRUCTURE_ITEMS)):
        src = STRUCTURE_FIRST_ROW + index
        sh.line(_G_TABLE_4, [(None, _src("A", src), sh.td),
                             (None, _src("B", src), sh.value("млн ₽")),
                             (None, _src("C", src), sh.value("доля")),
                             (None, _src("E", src), sh.value("тыс ₽"))])
    src = STRUCTURE_TOTAL_ROW
    sh.line(_G_TABLE_4, [("Итого", None, sh.bold_td),
                         (None, _src("B", src), sh.bold_value("млн ₽")),
                         (None, _src("C", src), sh.bold_value("доля")),
                         (None, _src("E", src), sh.bold_value("тыс ₽"))])
    sh.blank()

    # Финансовая деятельность и налоги | авто-риски.
    sh.section_row("ФИНАНСОВАЯ ДЕЯТЕЛЬНОСТЬ И НАЛОГИ", "АВТО-РИСКИ · считает книга")
    fin_keys = ["peak_escrow_mln", "rve_escrow_release_mln", "bridge_interest_mln", "pf_interest_mln",
                "pf_limit_fee_mln", "issue_fees_mln", "tax_mln", "vat_mln"]
    risks = list(RISK_CATALOGUE)
    for index in range(max(len(fin_keys), len(risks) + 1)):
        items = []
        if index < len(fin_keys):
            label, unit = labels[fin_keys[index]]
            items += [(f"{label}, {unit}", None, sh.td), (None, data_cell(fin_keys[index]), sh.value(unit))]
        else:
            items += [(None, None, sh.td), (None, None, sh.td)]
        if index < len(risks):
            key, _label, value_key = risks[index]
            src = RISK_ROWS[key]
            flag = _src("C", src)
            unit = "x" if value_key in ("llcr", "weakest_phase_llcr") else "млн ₽"
            items += [(None, _src("B", src), sh.td),
                      (None, f'IF({flag}=1,"ДА · "&TEXT({_src("D", src)},"0.0"),"нет")', sh.risk_on)]
        elif index == len(risks):
            items += [("Статус модели (ПРОВЕРКИ)", None, sh.td_muted), (None, data_cell("status"), sh.value("текст"))]
        else:
            items += [(None, None, sh.td), (None, None, sh.td)]
        sh.line(_G_KV_LEFT + _G_KV_RIGHT, items)
    sh.blank()

    # Сроки очередей: таблица дат и годовая лента стройки и продаж.
    Q = QUEUE_COLUMNS
    sh.section_row("СРОКИ · ОЧЕРЕДИ")
    sh.header(_G_QUEUE, ["Очередь", "Старт", "РнС / ПФ", "РВЭ", "Продажи с", "Продажи по",
                         "Стройка, мес.", "Продажи, мес."])
    for q in range(QUEUE_COUNT):
        src = QUEUE_FIRST_ROW + q
        on = _src(Q["on"], src)
        def when(column: str) -> str:
            return f'IF({on}=1,{_src(column, src)},"")'
        sh.line(_G_QUEUE, [(None, f'IF({on}=1,{_src(Q["name"], src)},"")', sh.td),
                           (None, when(Q["start"]), sh.value("дата")),
                           (None, when(Q["permit"]), sh.value("дата")),
                           (None, when(Q["rve"]), sh.value("дата")),
                           (None, when(Q["sales_start"]), sh.value("дата")),
                           (None, when(Q["sales_end"]), sh.value("дата")),
                           (None, when(Q["build_months"]), sh.value("мес.")),
                           (None, when(Q["sales_months"]), sh.value("мес."))])
    # Лента: год на колонку, в клетке — столько знаков, сколько месяцев года
    # занято этапом. Стройка — синим, продажи — зелёным.
    year0 = f"YEAR({data_cell('project_start')})"
    r = sh.next_row
    cells = {0: _cell(f"A{r}", text="Очередь / этап", style=sh.th)}
    for k in range(GANTT_YEARS):
        i = 2 + k
        cells[i] = _cell(f"{_col(i)}{r}", formula=f"{year0}+{k}", style=sh.year)
    sh.put(cells, sh.th, height=18)
    sh.merge(r, 0, 1)
    for q in range(QUEUE_COUNT):
        src = QUEUE_FIRST_ROW + q
        on = _src(Q["on"], src)
        for stage, start_col, end_col, style in (("Стройка", Q["permit"], Q["build_end"], sh.gantt_build),
                                                 ("Продажи", Q["sales_start"], Q["sales_end"], sh.gantt_sales)):
            r = sh.next_row
            s, e = _src(start_col, src), _src(end_col, src)
            cells = {0: _cell(f"A{r}", formula=f'IF({on}=1,{_src(Q["name"], src)},"")', style=sh.td),
                     1: _cell(f"B{r}", formula=f'IF({on}=1,"{stage}","")', style=sh.td_muted)}
            for k in range(GANTT_YEARS):
                i = 2 + k
                year = f"({year0}+{k})"
                months = (f"MAX(0,MIN(YEAR({e})*12+MONTH({e}),{year}*12+12)"
                          f"-MAX(YEAR({s})*12+MONTH({s}),{year}*12+1)+1)")
                cells[i] = _cell(f"{_col(i)}{r}", formula=f'IF({on}=1,REPT("█",{months}),"")', style=style)
            sh.put(cells, style)
    sh.blank()

    # Диаграммы: долг и эскроу во всю ширину, мост и кольцо — рядом.
    sh.section_row("ДОЛГ И ЭСКРОУ ПО МЕСЯЦАМ")
    debt_anchor_index = len(sh.anchors)
    sh.chart_slot(CHART_ROWS_WIDE, [(0, WIDTH)])
    sh.section_row("МОСТ ОТ ВЫРУЧКИ К ПРИБЫЛИ", "СТРУКТУРА РАСХОДОВ")
    sh.chart_slot(CHART_ROWS_PAIR, [(0, RIGHT_HALF[0]), (RIGHT_HALF[0], WIDTH)])
    # Порядок якорей — порядок диаграмм сборщика: мост, кольцо, долг.
    debt = sh.anchors.pop(debt_anchor_index)
    anchors = sh.anchors + [debt]

    origin_formula = ('"Расчёт "&\'{d}\'!$B${a}&" · движок "&\'{d}\'!$B${b}&" · собрано "&\'{d}\'!$B${c}'
                      .format(d=DATA_SHEET, a=ORIGIN_FIRST_ROW, b=ORIGIN_FIRST_ROW + 1, c=ORIGIN_FIRST_ROW + 2))
    sh.band(None, origin_formula, sh.subtitle, 15)

    cols = "".join(f'<x:col min="{i}" max="{i}" width="{COLUMN_WIDTH}" customWidth="1" />'
                   for i in range(1, WIDTH + 1))
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<x:worksheet {_NS} {_R_NS}>'
        '<x:sheetPr><x:tabColor rgb="FF17365D" /><x:pageSetUpPr fitToPage="1" /></x:sheetPr>'
        '<x:sheetViews><x:sheetView showGridLines="0" workbookViewId="0" /></x:sheetViews>'
        '<x:sheetFormatPr defaultRowHeight="15" />'
        f"<x:cols>{cols}</x:cols>"
        f'<x:sheetData>{"".join(sh.rows)}</x:sheetData>'
        f'<x:mergeCells count="{len(sh.merges)}">'
        + "".join(f'<x:mergeCell ref="{m}" />' for m in sh.merges) + "</x:mergeCells>"
        '<x:pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3" />'
        '<x:pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="0" />'
        f'<x:drawing r:id="{drawing_rel_id}" />'
        "</x:worksheet>"
    )
    return xml, anchors


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
    first, last = BRIDGE_FIRST_ROW, BRIDGE_LAST_ROW
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
    first, last = STRUCTURE_FIRST_ROW, STRUCTURE_TOTAL_ROW - 1
    points = "".join(
        f'<c:dPt><c:idx val="{i}"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="{RING_COLOURS[i % len(RING_COLOURS)]}"/></a:solidFill></c:spPr></c:dPt>'
        for i in range(len(STRUCTURE_ITEMS)))
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


def drawing_xml(rel_ids: list[str], anchors: list[tuple[int, int, int, int]]) -> bytes:
    """Рисунок листа: якорь каждой диаграммы (колонка и строка «от» и «до»,
    индексы с нуля) даёт раскладка листа — рисунок их не помнит сам."""
    parts = []
    for index, ((c0, r0, c1, r1), rel) in enumerate(zip(anchors, rel_ids), 1):
        parts.append(
            "<xdr:twoCellAnchor>"
            f"<xdr:from><xdr:col>{c0}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r0}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f"<xdr:to><xdr:col>{c1}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
            f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{index + 1}" name="Диаграмма {index}"/>'
            "<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>"
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            f'<a:graphic><a:graphicData uri="{_CHART_NS}"><c:chart xmlns:c="{_CHART_NS}" xmlns:r="{_REL_NS}" r:id="{rel}"/>'
            "</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<xdr:wsDr xmlns:xdr="{_DRAWING_NS}" xmlns:a="{_DRAWINGML_NS}">{"".join(parts)}</xdr:wsDr>'
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
          llcr_target: float, month_columns: list[str], phased: bool,
          capex_rows: dict[str, int], capex_stride: int) -> dict[str, Any]:
    """Собрать все части дашборда. Возвращает словарь «путь → байты» и
    новый styles.xml; лишние диаграммы шаблона названы в `dropped`.
    `capex_rows`/`capex_stride` — карта статей листа CAPEX (её владелец —
    сборщик книги)."""
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
    sheet_xml, anchors = build_dashboard_sheet(styles, where["drawing_rel"], phased)
    if len(anchors) != len(charts):
        raise ValueError(f"диаграмм {len(charts)}, а мест на листе {len(anchors)}")
    parts[where["drawing_path"]] = drawing_xml(rel_ids, anchors)
    parts[where["drawing_rels_path"]] = drawing_rels_xml(targets)
    parts[sheet_path] = sheet_xml.encode("utf-8")
    parts[DATA_SHEET_PATH] = build_data_sheet(origin, llcr_target, last_column, month_columns,
                                              capex_rows, capex_stride).encode("utf-8")
    added_charts = [path for _rel, path in targets if path.lstrip("/") not in {p for _r, p in existing}]
    return {"parts": parts, "styles_xml": styles.render(), "dropped": dropped,
            "added_charts": [p.lstrip("/") for p in added_charts], "styles_added": styles.added}
