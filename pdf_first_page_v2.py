"""Presentation patch for the DevelopAid PDF first page.

Uses the existing server-side OSM basemap renderer and the factual EGRN contour.
Also replaces the sixth KPI card with total project expenses.
Financial calculations are not changed.
"""

from __future__ import annotations

import io
from typing import Any

import pdf_first_page_extension as base


def _number(value: Any) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0


def _total_expenses(result: dict[str, Any]) -> float:
    report = result.get("report") or {}
    rows = report.get("expense_structure") or []
    total = sum(
        _number(row.get("value"))
        for row in rows
        if isinstance(row, dict)
    )
    if total > 0:
        return total
    summary = result.get("summary") or {}
    for key in ("total_expenses", "expenses_total", "total_costs", "total_cost"):
        value = _number(summary.get(key))
        if value > 0:
            return value
    return 0.0


def _osm_parcel_image(payload: dict[str, Any], core: Any, width: float = 260,
                      height: float = 126):
    """Return the real OSM basemap with the stored EGRN contour overlaid.

    If the basemap cannot be produced, fall back to the original schematic
    drawing so PDF generation itself never becomes dependent on map I/O.
    """
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image

    items = base._parcel_items(payload)
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

    # Show surrounding streets/buildings rather than an over-zoomed parcel.
    pad_x = max(span_x * 1.15, 130.0)
    pad_y = max(span_y * 1.15, 130.0)
    bbox = (
        min_x - pad_x,
        min_y - pad_y,
        max_x + pad_x,
        max_y + pad_y,
    )

    try:
        response = core.land_basemap(
            bbox=",".join(f"{value:.3f}" for value in bbox),
            width=960,
        )
        raw = getattr(response, "body", None)
        if not raw:
            raise RuntimeError("empty basemap")

        from PIL import Image as PILImage, ImageDraw, ImageFont

        image = PILImage.open(io.BytesIO(raw)).convert("RGBA")
        px_w, px_h = image.size
        draw = ImageDraw.Draw(image, "RGBA")
        bx0, by0, bx1, by1 = bbox

        def project(point):
            x, y = _number(point[0]), _number(point[1])
            px = (x - bx0) / (bx1 - bx0) * px_w
            py = (by1 - y) / (by1 - by0) * px_h
            return (px, py)

        stroke = max(4, round(px_w / 220))
        for ring in rings:
            projected = [project(point) for point in ring]
            if projected and projected[0] != projected[-1]:
                projected.append(projected[0])
            if len(projected) >= 4:
                # White halo keeps the cadastral boundary legible on dense OSM.
                draw.line(projected, fill=(255, 255, 255, 235), width=stroke + 4,
                          joint="curve")
                draw.line(projected, fill=(20, 20, 20, 255), width=stroke,
                          joint="curve")

        # OSM attribution must remain on the exported static image.
        label = "© OpenStreetMap"
        try:
            font = ImageFont.load_default()
            box = draw.textbbox((0, 0), label, font=font)
            tw, th = box[2] - box[0], box[3] - box[1]
        except Exception:
            font = None
            tw, th = 92, 12
        x, y = 8, px_h - th - 8
        draw.rounded_rectangle((x - 4, y - 3, x + tw + 4, y + th + 3),
                               radius=3, fill=(255, 255, 255, 225))
        draw.text((x, y), label, fill=(40, 40, 40, 255), font=font)

        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=88, optimize=True)
        out.seek(0)
        flowable = Image(ImageReader(out), width=width, height=height)
        flowable._developaid_image_buffer = out
        return flowable
    except Exception:
        return _ORIGINAL_PARCEL_DRAWING(payload, core, width=width, height=height)


def _patched_front_page_flowables(payload: dict[str, Any], core: Any):
    flowables = _ORIGINAL_FRONT_PAGE(payload, core)
    try:
        result = payload.get("result") or {}
        total = _total_expenses(result)
        if total <= 0 or not flowables:
            return flowables

        # Existing structure: KeepTogether -> blocks -> KPI Table -> six cell Tables.
        keep = flowables[0]
        blocks = getattr(keep, "_content", None) or []
        card_table = blocks[2]
        cell = card_table._cellvalues[1][2]
        label_para = cell._cellvalues[0][0]
        value_para = cell._cellvalues[1][0]

        from reportlab.platypus import Paragraph

        cell._cellvalues[0][0] = Paragraph("Расходы всего", label_para.style)
        cell._cellvalues[1][0] = Paragraph(core._pdf_money(total), value_para.style)
    except Exception:
        # The summary is presentation-only; never make the PDF fail because of it.
        pass
    return flowables


_ORIGINAL_PARCEL_DRAWING = base._parcel_drawing
_ORIGINAL_FRONT_PAGE = base._front_page_flowables


def install(core: Any) -> None:
    base._parcel_drawing = _osm_parcel_image
    base._front_page_flowables = _patched_front_page_flowables
    base.install(core)
