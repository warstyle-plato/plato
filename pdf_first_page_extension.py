"""First-page summary for the existing DevelopAid PDF report.

This extension changes presentation only. It keeps the original
``core._build_developaid_pdf`` object intact because several regression tests
inspect that function's source as a contract for financial-report semantics.
"""

from __future__ import annotations

import sys
from typing import Any


_INSTALLED = False


def _number(value: Any) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0


def _recommended_price(result: dict[str, Any]) -> float:
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
    snapshot = (payload.get("inputs") or {}).get("_land_lookup") or {}
    return [
        item for item in (snapshot.get("results") or [])
        if isinstance(item, dict)
        and item.get("found")
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

    _, bold = core._pdf_font_names()
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height,
                     fillColor=colors.HexColor("#F6F6F4"),
                     strokeColor=colors.HexColor("#D8D8D8"), strokeWidth=0.6))
    for fraction in (0.24, 0.50, 0.76):
        drawing.add(Line(width * fraction, 0, width * fraction, height,
                         strokeColor=colors.HexColor("#E7E7E4"), strokeWidth=0.45))
    for fraction in (0.28, 0.58, 0.82):
        drawing.add(Line(0, height * fraction, width, height * fraction,
                         strokeColor=colors.HexColor("#E7E7E4"), strokeWidth=0.45))

    pad = 13.0
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    draw_w, draw_h = span_x * scale, span_y * scale
    off_x = (width - draw_w) / 2.0
    off_y = (height - draw_h) / 2.0

    def project(point):
        x, y = _number(point[0]), _number(point[1])
        return (
            off_x + (x - min_x) * scale,
            off_y + (max_y - y) * scale,
        )

    for ring in rings:
        projected = [project(point) for point in ring]
        flat = [coordinate for point in projected for coordinate in point]
        if len(flat) >= 6:
            drawing.add(Polygon(
                flat,
                strokeColor=colors.HexColor("#222222"),
                strokeWidth=1.5,
                fillColor=colors.HexColor("#EFEFEC"),
            ))

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
    import html
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
    normal = ParagraphStyle("pdf_front_normal", parent=styles["BodyText"],
                            fontName=regular, fontSize=7.7, leading=9.6,
                            textColor=colors.HexColor("#222222"))
    label_style = ParagraphStyle("pdf_front_label", parent=normal,
                                 fontSize=6.6, leading=8.0,
                                 textColor=colors.HexColor("#666666"))
    value_style = ParagraphStyle("pdf_front_value", parent=normal,
                                 fontName=bold, fontSize=10.2, leading=12.0,
                                 textColor=colors.HexColor("#111111"))
    heading = ParagraphStyle("pdf_front_h2", parent=normal, fontName=bold,
                             fontSize=12.5, leading=16, spaceAfter=5,
                             textColor=colors.HexColor("#111111"))

    def para(text: Any, style=normal):
        value = text if text not in (None, "") else "—"
        return Paragraph(html.escape(str(value)), style)

    recommended = _recommended_price(result)
    purchase = _purchase_price(result)
    kpis = [
        ("Рекомендованная цена" if recommended > 0 else "Цена приобретения",
         core._pdf_money(recommended if recommended > 0 else purchase)),
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
    card_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8D8D8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D8D8D8")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F6F4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    blocks: list[Any] = [Spacer(1, 1.5 * mm), para("Результаты расчёта", heading), card_table]
    drawing = _parcel_drawing(payload, core)
    if drawing is not None:
        items = _parcel_items(payload)
        total_area = sum(_number(item.get("area_sqm")) for item in items)
        if total_area <= 0:
            total_area = _number(inputs.get("site_area_ha")) * 10000.0
        total_tep = ((result.get("tep") or {}).get("total") or {})
        transfer = sum(
            _number(row.get("transfer"))
            for row in ((payload.get("tep") or {}).values())
            if isinstance(row, dict)
        )
        info_rows = [
            [para("Площадь ЗУ", label_style), para(core._pdf_num(total_area, 0) + " м²")],
            [para("Строит. объём", label_style), para(core._pdf_num(total_tep.get("gns"), 0) + " м²")],
            [para("Продаваемая", label_style), para(core._pdf_num(total_tep.get("saleable"), 0) + " м²")],
        ]
        if transfer > 0:
            info_rows.append([
                para("Передаваемая бесплатно", label_style),
                para(core._pdf_num(transfer, 0) + " м²"),
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


def _payload_from_caller() -> dict[str, Any] | None:
    """Find the builder payload without replacing the builder itself."""
    try:
        frame = sys._getframe(2)
        for _ in range(10):
            if frame is None:
                break
            candidate = frame.f_locals.get("payload")
            if isinstance(candidate, dict) and isinstance(candidate.get("result"), dict):
                return candidate
            frame = frame.f_back
    except Exception:
        return None
    return None


def install(core: Any) -> None:
    """Inject first-page flowables while preserving the original PDF builder."""
    global _INSTALLED
    if _INSTALLED:
        return
    original_order = core._pdf_ordered_story

    def ordered_story(story, order, page_break):
        payload = _payload_from_caller()
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

    core._pdf_ordered_story = ordered_story
    _INSTALLED = True
