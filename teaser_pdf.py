"""Тизер проекта — одна страница A4 из модели представления.

Собирается из `presentation.build_project_presentation`, а не из книги и не
обрезкой полного отчёта: тот остаётся как есть. Единица у каждого числа стоит
рядом, форматирование денег — то же, что у полного PDF (передаётся вызывающим:
модуль движка не импортирует, иначе появился бы второй экземпляр ядра).
"""

from __future__ import annotations

import io
from typing import Any, Callable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#17365D")
NAVY_DARK = colors.HexColor("#0B1F33")
LIGHT = colors.HexColor("#EAF2F8")
GREY = colors.HexColor("#666666")
RED = colors.HexColor("#C00000")
GREEN = colors.HexColor("#2E7D32")

TEASER_TITLE = "DevelopAid · тизер проекта"


def _fmt_value(value: Any, unit: str, num: Callable[..., str]) -> str:
    if value is None or value == "":
        return "—"
    if unit == "млн ₽":
        return num(value, 1)
    if unit == "%":
        return num(float(value) * 100, 1) + "%"
    if unit == "x":
        return num(value, 2) + "x"
    if unit == "мес.":
        return num(value, 0)
    if unit in ("м²", "шт."):
        return num(value, 0)
    return str(value)


def build_teaser_pdf(presentation: dict[str, Any], fonts: tuple[str, str],
                     num: Callable[..., str]) -> bytes:
    """Одна страница: шапка, шесть карточек, ТЭП и продажи, финансирование,
    риски, происхождение. Больше страницы не бывает — это проверяется."""
    regular, bold = fonts
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title=TEASER_TITLE, author="DevelopAid")
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=15, leading=18, textColor=NAVY_DARK)
    sub = ParagraphStyle("sub", fontName=regular, fontSize=8.5, leading=11, textColor=GREY)
    head = ParagraphStyle("head", fontName=bold, fontSize=9.5, leading=12, textColor=colors.white)
    label = ParagraphStyle("label", fontName=regular, fontSize=8, leading=10, textColor=GREY, alignment=1)
    value = ParagraphStyle("value", fontName=bold, fontSize=14, leading=17, textColor=NAVY_DARK, alignment=1)
    body = ParagraphStyle("body", fontName=regular, fontSize=8.5, leading=11, textColor=NAVY_DARK)
    body_b = ParagraphStyle("body_b", fontName=bold, fontSize=8.5, leading=11, textColor=NAVY_DARK)
    th = ParagraphStyle("th", fontName=bold, fontSize=7.5, leading=9.5, textColor=NAVY_DARK)
    risk_on = ParagraphStyle("risk_on", fontName=bold, fontSize=8.5, leading=11, textColor=RED)
    risk_off = ParagraphStyle("risk_off", fontName=regular, fontSize=8.5, leading=11, textColor=GREEN)
    foot = ParagraphStyle("foot", fontName=regular, fontSize=7.5, leading=9.5, textColor=GREY)

    width = A4[0] - 24 * mm
    origin = presentation.get("origin") or {}
    story: list[Any] = []
    story.append(Paragraph(TEASER_TITLE, h1))
    story.append(Paragraph(
        f"{presentation.get('project_name') or 'Проект'} · расчёт {origin.get('calculation_id') or '—'} "
        f"· движок {origin.get('engine_version') or '—'} · {origin.get('generated_at') or ''}", sub))
    story.append(Spacer(1, 4 * mm))

    # Карточки: две строки по три.
    cards = list(presentation.get("cards") or [])
    grid: list[list[Any]] = []
    for band in range(0, len(cards), 3):
        chunk = cards[band:band + 3]
        grid.append([Paragraph(f"{c['label']}, {c['unit']}", label) for c in chunk])
        grid.append([Paragraph(_fmt_value(c["value"], c["unit"], num), value) for c in chunk])
    if grid:
        table = Table(grid, colWidths=[width / 3] * 3, rowHeights=[6 * mm, 11 * mm] * (len(grid) // 2))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, colors.white),
            ("INNERGRID", (0, 0), (-1, -1), 1.5, colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(table)
    story.append(Spacer(1, 4 * mm))

    def section(text: str) -> Table:
        t = Table([[Paragraph(text, head)]], colWidths=[width], rowHeights=[6 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        return t

    # ТЭП и продажи одной таблицей: продукт · ГНС · продаваемая · единиц · выручка · цена.
    story.append(section("ТЭП и продажи по продуктам"))
    rows = [[Paragraph(t, th) for t in ("Продукт", "ГНС, м²", "Продаваемая, м²", "Единиц, шт.", "Выручка, млн ₽", "Ср. цена, тыс ₽")]]
    for product in presentation.get("products") or []:
        rows.append([
            Paragraph(product["label"], body),
            Paragraph(_fmt_value(product.get("gns"), "м²", num) if product.get("gns") else "—", body),
            Paragraph(_fmt_value(product.get("saleable"), "м²", num) if product.get("saleable") else "—", body),
            Paragraph(_fmt_value(product.get("quantity"), "шт.", num) if product.get("unit") == "шт." else "—", body),
            Paragraph(_fmt_value(product.get("revenue_mln"), "млн ₽", num), body),
            Paragraph(_fmt_value(product.get("avg_price_th"), "шт.", num) if product.get("avg_price_th") else "—", body),
        ])
    tep = presentation.get("tep") or {}
    rows.append([Paragraph("Итого проект", body_b),
                 Paragraph(_fmt_value(tep.get("project_gns_sqm"), "м²", num), body_b),
                 Paragraph(_fmt_value(tep.get("saleable_sqm"), "м²", num), body_b),
                 Paragraph("", body), Paragraph(_fmt_value(next(
                     (k["value"] for k in presentation.get("kpi") or [] if k["key"] == "revenue_mln"), None),
                     "млн ₽", num), body_b), Paragraph("", body)])
    table = Table(rows, colWidths=[width * 0.28] + [width * 0.144] * 5)
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY), ("LINEABOVE", (0, -1), (-1, -1), 0.6, NAVY),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    story.append(table)
    sales = presentation.get("sales") or {}
    dates = presentation.get("dates") or {}
    story.append(Paragraph(
        f"Старт проекта {dates.get('project_start') or '—'} · РнС {dates.get('permit') or '—'} · "
        f"старт продаж {sales.get('start') or '—'} · РВЭ {dates.get('rve') or '—'} · "
        f"продажи до {sales.get('end') or '—'}", sub))
    story.append(Spacer(1, 3 * mm))

    # Финансирование и риски — двумя колонками.
    story.append(section("Финансирование · риски, которые модель нашла сама"))
    fin_rows = []
    for item in (presentation.get("kpi") or [])[6:]:
        fin_rows.append([Paragraph(f"{item['label']}, {item['unit']}", body),
                         Paragraph(_fmt_value(item["value"], item["unit"], num), body_b)])
    risk_rows = []
    for risk in presentation.get("risks") or []:
        style = risk_on if risk["active"] else risk_off
        tail = ""
        if risk["active"]:
            unit = "x" if risk["value_key"] in ("llcr", "weakest_phase_llcr") else "млн ₽"
            tail = f": {_fmt_value(risk.get('value'), unit, num)} {unit}"
            if risk.get("detail"):
                tail += f" ({risk['detail']})"
        risk_rows.append([Paragraph(risk["label"] + (tail if risk["active"] else " — нет"), style)])
    if not risk_rows:
        risk_rows.append([Paragraph("Рисков модель не нашла", risk_off)])
    left = Table(fin_rows, colWidths=[width * 0.32, width * 0.14])
    left.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    right = Table(risk_rows, colWidths=[width * 0.50])
    right.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    both = Table([[left, right]], colWidths=[width * 0.48, width * 0.52])
    both.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(both)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Целевой LLCR банка {num(presentation.get('llcr_target') or 0, 2)}x. Числа посчитаны движком "
        f"DevelopAid одним расчётом; тизер их не пересчитывает. Отпечаток вводных: "
        f"{origin.get('inputs_fingerprint') or origin.get('calculation_id') or '—'}.", foot))

    doc.build(story)
    return buf.getvalue()
