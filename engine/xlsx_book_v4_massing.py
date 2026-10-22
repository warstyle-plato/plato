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


def _v4_under_rate_ref(params_name: str = "'Вводные'") -> str:
    """Ставка подземной части с надбавкой за глубину — ссылкой книги."""
    rate = f"{params_name}!$B$45"
    cell = _V4_DEPTH_FACTOR_CELL.get()
    if not cell:
        return rate
    return f"({rate}*{params_name}!{cell})"


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
        "driveways_pct": "экспертная оценка, согласована владельцем",
        "setback_m": "полоса по периметру; градплан может задать другой отступ",
        "surface_parking_sqm": str(massing.get("surface_parking_basis") or ""),
        "above_gns_sqm": "из ТЭП проекта",
        "underground_sqm": "паркинг с рампами и проездами, подземные кладовые и гаражи объектов",
        "markup2_pct": "экспертная оценка, согласована владельцем",
        "markup3_pct": "экспертная оценка, согласована владельцем",
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
        parts.append(f'<x:row r="{row}">{cells}</x:row>')
    tail = "</x:sheetData>"
    assert tail in xml
    _V4_DEPTH_FACTOR_CELL.set(f"$B${rows['depth_factor']}")
    return xml.replace(tail, "".join(parts) + tail, 1), massing


def _v4_apply_underground_depth(xml: str, missing: list[str]) -> str:
    """СМР подземной части очередей (CAPEX, строка 22 каждого блока) — по
    ставке с надбавкой за глубину. Не опознали формулу — `missing`."""
    if not _V4_DEPTH_FACTOR_CELL.get():
        return xml
    import re as _re
    # Граница по цифре: `$B$457` (размещение кладовых) начинается с `$B$45`.
    rate = _re.compile(r"'Вводные'!\$B\$45(?!\d)")
    for phase in range(_V4_CAPEX_PHASES):
        row = _V4_CAPEX_ARTICLE_ROW["main_under"] + _V4_CAPEX_BLOCK_STRIDE * phase
        found = _re_search_cell_formula(xml, f"B{row}")
        if found is None or len(rate.findall(found)) != 1:
            missing.append(f"CAPEX · надбавка за глубину: формула строки {row} не опознана")
            continue
        xml, done = _v4_set_cells(xml, row, {f"B{row}": dict(
            formula=rate.sub(lambda _m: _v4_under_rate_ref("'Вводные'"), found, count=1))})
        if not done:
            missing.append(f"CAPEX · надбавка за глубину: строка {row} не записана")
    return xml
