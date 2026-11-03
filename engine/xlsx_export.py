"""Выгрузка полной модели в XLSX: ячейки, стили, листы, диаграммы.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("xlsx_export")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Выгрузка полной модели: XLSX по каждому расчёту + ZIP с консолидатором очередей
# ---------------------------------------------------------------------------

_XLSX_STYLE_TEXT = 0
_XLSX_STYLE_TITLE = 1
_XLSX_STYLE_HEADER = 2
_XLSX_STYLE_INT = 3
_XLSX_STYLE_NUM = 4
_XLSX_STYLE_PCT = 5
_XLSX_STYLE_TOTAL = 6
_XLSX_STYLE_BOLD = 7
_XLSX_STYLE_TOTAL_INT = 8

_XLSX_STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{_XLSX_MAIN_NS}">
  <numFmts count="3">
    <numFmt numFmtId="164" formatCode="#,##0"/>
    <numFmt numFmtId="165" formatCode="#,##0.00"/>
    <numFmt numFmtId="166" formatCode="0.0%"/>
  </numFmts>
  <fonts count="3">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="13"/><name val="Calibri"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEC"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top/><bottom style="thin"><color rgb="FF808080"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="9">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="165" fontId="1" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="164" fontId="1" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>'''.encode("utf-8")


class _XlsxCell:
    """Ячейка выгрузки: текст, число или формула с посчитанным значением."""

    __slots__ = ("value", "style", "formula")

    def __init__(self, value: Any = None, style: int = _XLSX_STYLE_TEXT, formula: str = "") -> None:
        self.value = value
        self.style = style
        self.formula = formula


def _cell_text(value: Any, style: int = _XLSX_STYLE_TEXT) -> _XlsxCell:
    return _XlsxCell("" if value is None else str(value), style)


def _cell_num(value: Any, style: int = _XLSX_STYLE_NUM) -> _XlsxCell:
    number = _land_float(value)
    if number is None or not math.isfinite(number):
        return _XlsxCell("", _XLSX_STYLE_TEXT)
    return _XlsxCell(number, style)


def _cell_mln(value: Any, style: int = _XLSX_STYLE_NUM) -> _XlsxCell:
    number = _land_float(value)
    if number is None or not math.isfinite(number):
        return _XlsxCell("", _XLSX_STYLE_TEXT)
    return _XlsxCell(round(number / 1_000_000.0, 4), style)


def _cell_formula(formula: str, value: Any, style: int = _XLSX_STYLE_TOTAL) -> _XlsxCell:
    number = _land_float(value)
    return _XlsxCell(number if number is not None and math.isfinite(number) else 0.0, style, formula)


def _header_row(labels: list[str]) -> list[_XlsxCell]:
    return [_cell_text(label, _XLSX_STYLE_HEADER) for label in labels]


def _sum_formula(column: str, first_row: int, last_row: int) -> str:
    return f"SUM({column}{first_row}:{column}{last_row})"


def _xlsx_sheet_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", str(name or "Лист")).strip()[:31] or "Лист"
    candidate, suffix = clean, 2
    while candidate.lower() in used:
        tail = f" {suffix}"
        candidate = clean[: 31 - len(tail)] + tail
        suffix += 1
    used.add(candidate.lower())
    return candidate


_XLSX_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_XLSX_DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_XLSX_CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"

# Палитра диаграмм: тёмно-синий основной, остальные — для второй и третьей серии.
_XLSX_CHART_COLORS = ("244A64", "6B8E23", "B4762A", "7A5C8E")


def _chart_title(text: str) -> str:
    if not text:
        return '<c:autoTitleDeleted val="1"/>'
    return (
        "<c:title><c:tx><c:rich>"
        '<a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>' + _xlsx_xml_text(text) + "</a:t></a:r></a:p>"
        '</c:rich></c:tx><c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>'
    )


def _chart_axes(cat_id: int, val_id: int, y_title: str) -> str:
    value_title = _chart_title(y_title).replace('<c:autoTitleDeleted val="0"/>', "") if y_title else ""
    return (
        f'<c:catAx><c:axId val="{cat_id}"/>'
        '<c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        '<c:axPos val="b"/><c:tickLblPos val="nextTo"/>'
        f'<c:crossAx val="{val_id}"/></c:catAx>'
        f'<c:valAx><c:axId val="{val_id}"/>'
        '<c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        f'<c:axPos val="l"/><c:majorGridlines/>{value_title}'
        '<c:numFmt formatCode="#,##0" sourceLinked="0"/><c:tickLblPos val="nextTo"/>'
        f'<c:crossAx val="{cat_id}"/></c:valAx>'
    )


def _chart_series(spec: dict[str, Any], index: int, line: bool) -> str:
    color = str(spec.get("color") or _XLSX_CHART_COLORS[index % len(_XLSX_CHART_COLORS)])
    if line:
        shape = (
            f'<c:spPr><a:ln w="22225"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln></c:spPr>'
            '<c:marker><c:symbol val="none"/></c:marker>'
        )
        tail = '<c:smooth val="0"/>'
    else:
        shape = f'<c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></c:spPr>'
        tail = ""
    categories = spec.get("categories") or ""
    cat = (
        f"<c:cat><c:strRef><c:f>{_xlsx_xml_text(categories)}</c:f></c:strRef></c:cat>"
        if categories else ""
    )
    return (
        f'<c:ser><c:idx val="{index}"/><c:order val="{index}"/>'
        f"<c:tx><c:v>{_xlsx_xml_text(spec.get('name') or '')}</c:v></c:tx>"
        f"{shape}{cat}"
        f"<c:val><c:numRef><c:f>{_xlsx_xml_text(spec.get('values') or '')}</c:f></c:numRef></c:val>"
        f"{tail}</c:ser>"
    )


def _chart_xml(chart: dict[str, Any]) -> bytes:
    line = str(chart.get("kind") or "bar") == "line"
    cat_id, val_id = 111111111, 222222222
    categories = chart.get("categories") or ""
    series = "".join(
        _chart_series({**item, "categories": categories}, index, line)
        for index, item in enumerate(chart.get("series") or [])
    )
    if line:
        plot = (
            '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>'
            f'{series}<c:marker val="0"/>'
            f'<c:axId val="{cat_id}"/><c:axId val="{val_id}"/></c:lineChart>'
        )
    else:
        plot = (
            '<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
            f'{series}<c:gapWidth val="60"/>'
            f'<c:axId val="{cat_id}"/><c:axId val="{val_id}"/></c:barChart>'
        )
    legend = (
        '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>'
        if len(chart.get("series") or []) > 1 else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<c:chartSpace xmlns:c="{_XLSX_CHART_NS}" xmlns:a="{_XLSX_DRAWINGML_NS}" '
        f'xmlns:r="{_XLSX_REL_NS}"><c:chart>'
        f"{_chart_title(str(chart.get('title') or ''))}"
        f'<c:plotArea><c:layout/>{plot}{_chart_axes(cat_id, val_id, str(chart.get("y_title") or ""))}</c:plotArea>'
        f'{legend}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/>'
        "</c:chart></c:chartSpace>"
    ).encode("utf-8")


def _drawing_xml(charts: list[dict[str, Any]]) -> bytes:
    anchors: list[str] = []
    for index, chart in enumerate(charts, 1):
        col, row = chart.get("anchor") or (0, 0)
        span_cols, span_rows = chart.get("span") or (8, 16)
        anchors.append(
            "<xdr:twoCellAnchor>"
            f"<xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff>"
            f"<xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f"<xdr:to><xdr:col>{col + span_cols}</xdr:col><xdr:colOff>0</xdr:colOff>"
            f"<xdr:row>{row + span_rows}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
            '<xdr:graphicFrame macro="">'
            f'<xdr:nvGraphicFramePr><xdr:cNvPr id="{index + 1}" name="Диаграмма {index}"/>'
            "<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>"
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            f'<a:graphic><a:graphicData uri="{_XLSX_CHART_NS}">'
            f'<c:chart xmlns:c="{_XLSX_CHART_NS}" xmlns:r="{_XLSX_REL_NS}" r:id="rId{index}"/>'
            "</a:graphicData></a:graphic></xdr:graphicFrame>"
            "<xdr:clientData/></xdr:twoCellAnchor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<xdr:wsDr xmlns:xdr="{_XLSX_DRAWING_NS}" xmlns:a="{_XLSX_DRAWINGML_NS}">'
        f'{"".join(anchors)}</xdr:wsDr>'
    ).encode("utf-8")


def _drawing_rels_xml(chart_numbers: list[int]) -> bytes:
    links = "".join(
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
        f'Target="../charts/chart{number}.xml"/>'
        for index, number in enumerate(chart_numbers, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_XLSX_PKG_REL_NS}">{links}</Relationships>'
    ).encode("utf-8")


def _sheet_rels_xml(drawing_number: int) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_XLSX_PKG_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
        f'Target="../drawings/drawing{drawing_number}.xml"/></Relationships>'
    ).encode("utf-8")


def _xlsx_sheet_ref(name: str, column: str, first: int, last: int) -> str:
    """Ссылка на диапазон листа в том виде, в каком её ждёт диаграмма."""
    quoted = name.replace("'", "''")
    return f"'{quoted}'!${column}${first}:${column}${last}"
