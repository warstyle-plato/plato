"""Книга v4: пятно застройки, этажность, подземные уровни и надбавка за глубину.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_massing")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.

Методика — `engine/site_massing.py`, формулы — `site_massing_book` (общие с
нежилой книгой). Блок дописывается в свободный низ «Вводных», как блоки
благоустройства и кладовых; ставка подземной части в CAPEX очередей, в CAPEX
гаражей объектов и в их проверке умножается на ячейку множителя.
"""
# ruff: noqa

import contextvars as _massing_contextvars

import site_massing_book as _massing_book

# Ячейка множителя за глубину в ЭТОЙ книге (на «Вводных»). Пусто — блок не
# писался, и ставка остаётся ставкой.
_V4_DEPTH_FACTOR_CELL: "_massing_contextvars.ContextVar[str]" = _massing_contextvars.ContextVar(
    "_V4_DEPTH_FACTOR_CELL", default="")


# Формат числа служебных вводных блока (`_v4_type_input_formats`): метры.
_V4_KEYED_INPUT_FORMATS.update({key: _v4_input_format_code("number", "м²", 1000.0)
                                for key in _massing_book.AREA_KEYS})
_V4_KEYED_INPUT_FORMATS.update({key: "0.0" for key in _massing_book.PERCENT_KEYS})


def _v4_under_rate_ref(params_name: str = "'Вводные'") -> str:
    """Ставка подземной части с надбавкой за глубину — ссылкой книги."""
    rate = f"{params_name}!$B$45"
    cell = _V4_DEPTH_FACTOR_CELL.get()
    if not cell:
        return rate
    return f"({rate}*{params_name}!{cell})"


# Ячейка «помещается благоустройства» блока пятна застройки нужна формуле
# блока благоустройства, а тот пишется раньше: формула несёт метку, и блок
# пятна ставит на её место свою ячейку.
_V4_LANDSCAPING_ROOM_TOKEN = "__MASSING_LANDSCAPING_ROOM__"
# Строки блока ждут вставки до сборки листа ввода (`_v4_site_massing_flush`):
# пока лист перечитывают сотни раз, вместо девяти тысяч знаков блока на нём
# стоит одна пустая строка, держащая его номера.
_V4_MASSING_PENDING: "_massing_contextvars.ContextVar[tuple[str, str]]" = \
    _massing_contextvars.ContextVar("v4_massing_pending", default=("", ""))


def _v4_site_massing_rows_xml(xml: str, inputs: dict[str, Any],
                              tep: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Блок «Пятно застройки и подземные уровни» внизу «Вводных» → (xml, расчёт движка).

    Вводные блока — числа того же расчёта (`site_massing`), расчётные строки —
    формулы `site_massing_book`. Правка отступа, доли проездов или надбавки в
    книге двигает уровни и СМР подземной части её формулами.
    """
    import re as _re
    massing = site_massing(inputs, tep)
    values = _massing_book.input_values(massing, inputs)
    numbers = [int(number) for number in _re.findall(r'<x:row r="(\d+)"', xml)]
    base_row = (max(numbers) if numbers else 0) + 2
    rows: dict[str, int] = {}
    for offset, (key, _label, _kind) in enumerate(_massing_book.ROWS, start=1):
        rows[key] = base_row + offset
    formulas = _massing_book.formulas(lambda key: f"$B${rows[key]}")

    def text_cell(coord: str, value: str, entry: bool = False) -> str:
        attr = _v4_entry_attr() if entry else ""
        return (f'<x:c r="{coord}"{attr} t="inlineStr"><x:is><x:t>{xml_escape(value)}'
                "</x:t></x:is></x:c>")

    parts = [f'<x:row r="{base_row}">'
             + _v4_head_cell(f"A{base_row}", "ПЯТНО ЗАСТРОЙКИ, ЭТАЖНОСТЬ И ПОДЗЕМНЫЕ УРОВНИ")
             + "</x:row>"]
    basis = {
        "yard_sqm": str(massing.get("yard_basis") or ""),
        "driveways_pct": "поле site_driveways_pct; экспертная оценка, согласована владельцем",
        "setback_m": "полоса по периметру; градплан может задать другой отступ",
        "surface_parking_sqm": (f"мест на земле × земля на место (surface_parking_spaces × "
                                f"surface_parking_sqm_per_space); "
                                f"{massing.get('surface_parking_basis') or ''}"),
        "above_gns_sqm": "из ТЭП, без отдельных зданий",
        "objects_plot_sqm": ", ".join(o["label"] for o in massing.get("objects") or []),
        "coverage_pct": "поле site_coverage_max_pct",
        "typical_storeys": "поле residential_storeys_typical",
        "underground_sqm": "паркинг с рампами и проездами, подземные кладовые и гаражи объектов",
        "markup2_pct": "поле underground_level2_markup_pct; экспертная оценка, согласована владельцем",
        "markup3_pct": "поле underground_level3_markup_pct; экспертная оценка, согласована владельцем",
        "depth_factor": "умножает ставку подземной части в CAPEX очередей и гаражей объектов",
    }
    for key, label, kind in _massing_book.ROWS:
        row = rows[key]
        cells = text_cell(f"A{row}", label)
        if kind == _massing_book.INPUT:
            value = values[key]
            if isinstance(value, str):
                cells += text_cell(f"B{row}", value, entry=True)
            else:
                cells += (f'<x:c r="B{row}"{_v4_entry_attr()}>'
                          f"<x:v>{_v4_number(round(float(value), 6))}</x:v></x:c>")
        else:
            cells += f'<x:c r="B{row}"><x:f>{xml_escape(formulas[key])}</x:f></x:c>'
        if basis.get(key):
            cells += text_cell(f"C{row}", basis[key])
        if key in _massing_book.BOOK_KEYS:
            cells += text_cell(f"D{row}", _massing_book.BOOK_KEYS[key])
        parts.append(f'<x:row r="{row}">{cells}</x:row>')
    tail = "</x:sheetData>"
    assert tail in xml
    _V4_DEPTH_FACTOR_CELL.set(f"$B${rows['depth_factor']}")
    xml = xml.replace(_V4_LANDSCAPING_ROOM_TOKEN, f"$B${rows['landscaping_room_sqm']}")
    # Номера строк заняты сейчас (следующие блоки встанут ниже), а сами строки
    # ждут `_v4_site_massing_flush`: сборка перечитывает лист сотни раз.
    last = max(rows.values())
    placeholder = f'<x:row r="{last}"></x:row>'
    _V4_MASSING_PENDING.set((placeholder, "".join(parts)))
    return xml.replace(tail, placeholder + tail, 1), massing


def _v4_site_massing_flush(xml: str, missing: list[str]) -> str:
    """Строки блока пятна — на место пустой строки, державшей их номера."""
    placeholder, rows_xml = _V4_MASSING_PENDING.get()
    if not placeholder:
        return xml
    _V4_MASSING_PENDING.set(("", ""))
    if xml.count(placeholder) != 1:
        missing.append("Вводные · пятно застройки: место блока не найдено, блок не вписан")
        return xml
    return xml.replace(placeholder, rows_xml, 1)


def _v4_under_depth_formula(formula: str, row: int, missing: list[str]) -> str:
    """СМР подземной части очереди (CAPEX, строка 22 блока) — по ставке с
    надбавкой за глубину. Зовётся проходом площади кладовых
    (`_v4_apply_storage_area_rows`), который эту формулу уже держит в руках.
    Не опознали ставку — `missing`, формула остаётся прежней."""
    import re as _re
    if not _V4_DEPTH_FACTOR_CELL.get():
        return formula
    # Граница по цифре: `$B$457` (размещение кладовых) начинается с `$B$45`.
    rate = _re.compile(r"'Вводные'!\$B\$45(?!\d)")
    if len(rate.findall(formula)) != 1:
        missing.append(f"CAPEX · надбавка за глубину: формула строки {row} не опознана")
        return formula
    return rate.sub(lambda _m: _v4_under_rate_ref("'Вводные'"), formula, count=1)
