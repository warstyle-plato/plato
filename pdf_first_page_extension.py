"""First-page summary for the existing DevelopAid PDF report.

The extension deliberately does not change model calculations. It only adds
flowables to the report header and reuses values already present in the result
payload. Parcel geometry is read from the saved EGRN lookup snapshot; when it
is absent or malformed the report is still generated without a map.
"""

from __future__ import annotations

import threading
from typing import Any


_STATE = threading.local()
_INSTALLED = False


def _number(value: Any) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0


def _recommended_price(result: dict[str, Any]) -> float:
    """Use an already-calculated recommendation if the engine exposes one.

    No goal seek is started from PDF generation: a report must not silently run
    another investment calculation. The aliases keep presentation compatible
    with result payloads that already expose the recommendation under one of
    the established names.
    """
    summary = result.get("summary") or {}
    report = result.get("report") or {}
    for source in (summary, report, result):
        for key in (
            "recommended_purchase_price_mln",
            "recommended_price_mln",
            "max_purchase_price_mln",
            "recommended_entry_price_mln",
        ):
            value = _number(source.get(key))
            if value > 0:
                return value * 1_000_000.0
    return 0.0


def _purchase_price(result: dict[str, Any]) -> float:
    for group in ((result.get("report") or {}).get("expense_structure") or []):
        if str(group.get("label") or "") == "Цена приобретения":
            return _number(group.get("value"))
    return 0.0


def _parcel_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = payload.get("inputs") or {}
    snapshot = inputs.get("_land_lookup") or {}
    return [
        item for item in (snapshot.get("results") or [])
        if isinstance(item, dict) and item.get("found")
        and isinstance(item.get("contour_merc"), list)
    ]


def _parcel_drawing(payload: dict[str, Any], core: Any, width: float = 260,
                    height: float = 126):
    from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
    from reportlab.lib import colors

    items = _parcel_items(payload)
    rings = [
        ring for item in items for ring in (item.get("contour_merc") or [])
        if isinstance(ring, list) and len(ring) >= 3
    ]
    points = [
        point for ring in rings for point in ring
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]
    if not points:
        return None

    xs = [_number(point[0]) for point in points]
    ys = [_number(point[1]) for point in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max_x - min_x, max_y - min_y
    if not (span_x > 0 and span_y > 0):
        return None

    regular, bold = core._pdf_font_names()
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height,
                     fillColor=colors.HexColor("#F6F6F4"),
                     strokeColor=colors.HexColor("#D8D8D8"), strokeWidth=0.6))

    # Quiet schematic context. The only factual geometry here is the EGRN
    # contour; background lines are deliberately neutral and unlabeled.
    for fraction in (0.24, 0.50, 0.76):
        drawing.add(Line(width * fraction, 0, width * fraction, height,
                         strokeColor=colors.HexColor("#E7E7E4"), strokeWidth=0.45))
    for fraction in (0.28, 0.58, 0.82):
        drawing.add(Line(0, height * fraction, width, height * fraction,
                         strokeColor=colors.HexColor("#E7E7E4"), strokeWidth=0.45))

    pad = 13.0
    usable_w, usable_h = width - 2 * pad, height - 2 * pad
    scale = min(usable_w / span_x, usable_h / span_y)
    draw_w, draw_h = span_x * scale, span_y * scale
    off_x = (width - draw_w) / 2.0
    off_y = (height - draw_h) / 2.0

    def project(point):
        x, y = _number(point[0]), _number(point[1])
        return (off_x + (x - min_x) * scale,
                off_y + (max_y - y) * scale)

    for ring in rings:
        projected = [project(point) for point in ring]
        if len(projected) < 3:
            continue
        flat = [coordinate for point in projected for coordinate in point]
        drawing.add(Polygon(flat,
                            strokeColor=colors.HexColor("#222222"),
                            strokeWidth=1.5,
                            fillColor=colors.HexColor("#EFEFEC")))

    label = "Контур ЕГРН"
    if len(items) > 1:
        label = f"Территория · {len(items)} ЗУ"
    elif items and items[0].get("cadastral_number"):
        label = str(items[0]["cadastral_number"])
    drawing.add(Rect(7, 7, min(width - 14, 8 + len(label) * 5.0), 16,
                     fillColor=colors.white,
                     strokeColor=colors.HexColor("#D8D8D8"), strokeWidth=0.4))
    drawing.add(String(11, 12, label, fontName=bold, fontSize=6.8,
                       fillColor=colors.HexColor("#333333")))
    return drawing


def _front_page_flowables(payload: dict[str, Any], core: Any) -> list[Any]:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

    result = payload.get("result") or {}
    summary = result.get("summary") or {}
    report = result.get("report") or {}
    financing = report.get("financing") or {}
    inputs = payload.get("inputs") or {}
    regular, bold = core._pdf_font_names()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "pdf_front_normal", parent=styles["BodyText"], fontName=regular,
        fontSize=7.7, leading=9.6, textColor=colors.HexColor("#222222"))
    label_style = ParagraphStyle(
        "pdf_front_label", parent=normal, fontSize=6.6, leading=8.0,
        textColor=colors.HexColor("#666666"))
    value_style = ParagraphStyle(
        "pdf_front_value", parent=normal, fontName=bold, fontSize=10.2,
        leading=12.0, textColor=colors.HexColor("#111111"))
    heading = ParagraphStyle(
        "pdf_front_h2", parent=normal, fontName=bold, fontSize=12.5,
        leading=16, spaceAfter=5, textColor=colors.HexColor("#111111"))

    def para(text: Any, style=normal):
        import html
        return Paragraph(html.escape(str(text if text not in (None, "") else "—")), style)

    recommended = _recommended_price(result)
    purchase = _purchase_price(result)
    first_label = "Рекомендованная цена" if recommended > 0 else "Цена приобретения"
    first_value = core._pdf_money(recommended if recommended > 0 else purchase)

    kpis = [
        (first_label, first_value),
        ("Выручка", core._pdf_money(summary.get("revenue"))),
        ("Чистая прибыль", core._pdf_money(summary.get("net_profit"))),
        ("Маржинальность", core._pdf_pct(summary.get("margin"))),
        ("LLCR", core._pdf_num(summary.get("llcr"), 2) + "x"),
        ("Пиковый БРИДЖ", core._pdf_money(financing.get("actual_bridge"))),
    ]

    cells = []
    for label, value in kpis:
        cell = Table([[para(label, label_style)], [para(value, value_style)]],
                     colWidths=[53.5 * mm], rowHeights=[5.2 * mm, 8.2 * mm])
        cell.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        cells.append(cell)
    card_table = Table([cells[:3], cells[3:]], colWidths=[56.5 * mm] * 3,
                       rowHeights=[14.5 * mm, 14.5 * mm], hAlign="LEFT")
    card_style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8D8D8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8D8D8")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F6F4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if recommended > 0:
        card_style.append(("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F1F1EF")))
    card_table.setStyle(TableStyle(card_style))

    blocks: list[Any] = [Spacer(1, 1.5 * mm), para("Результаты расчёта", heading), card_table]

    drawing = _parcel_drawing(payload, core)
    if drawing is not None:
        items = _parcel_items(payload)
        total_area = sum(_number(item.get("area_sqm")) for item in items)
        if total_area <= 0:
            total_area = _number(inputs.get("site_area_ha")) * 10000.0
        tep = result.get("tep") or {}
        total_tep = tep.get("total") or {}
        transfer = sum(
            _number(row.get("transfer"))
            for row in ((payload.get("tep") or {}).values())
            if isinstance(row, dict)
        )
        info_rows = [
            [para("Площадь ЗУ", label_style), para(core._pdf_num(total_area, 0) + " м²", normal)],
            [para("Строит. объём", label_style), para(core._pdf_num(total_tep.get("gns"), 0) + " м²", normal)],
            [para("Продаваемая", label_style), para(core._pdf_num(total_tep.get("saleable"), 0) + " м²", normal)],
        ]
        if transfer > 0:
            info_rows.append([
                para("Передаваемая бесплатно", label_style),
                para(core._pdf_num(transfer, 0) + " м²", normal),
            ])
        info = Table(info_rows, colWidths=[34 * mm, 41 * mm], hAlign="LEFT")
        info.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.35, colors.HexColor("#E0E0DE")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        map_block = Table([[drawing, info]], colWidths=[94 * mm, 76 * mm], hAlign="LEFT")
        map_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8D8D8")),
            ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8D8D8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        blocks.extend([Spacer(1, 3 * mm), para("Участок", heading), map_block])

    return [KeepTogether(blocks)]


def install(core: Any) -> None:
    """Install once into the shared PDF builder used by both site and bot."""
    global _INSTALLED
    if _INSTALLED:
        return
    original_build = core._build_developaid_pdf
    original_order = core._pdf_ordered_story

    def ordered_story(story, order, page_break):
        payload = getattr(_STATE, "payload", None)
        if payload:
            try:
                extra = _front_page_flowables(payload, core)
                if extra:
                    copied = list(story)
                    index = next(
                        (i for i, item in enumerate(copied)
                         if isinstance(item, core._PdfSection)),
                        len(copied),
                    )
                    copied[index:index] = extra
                    story = copied
            except Exception:
                # Presentation must never make an otherwise valid report fail.
                pass
        return original_order(story, order, page_break)

    def build(payload):
        previous = getattr(_STATE, "payload", None)
        _STATE.payload = payload
        try:
            return original_build(payload)
        finally:
            _STATE.payload = previous

    core._pdf_ordered_story = ordered_story
    core._build_developaid_pdf = build
    _INSTALLED = True
