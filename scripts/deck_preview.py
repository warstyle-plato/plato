"""Предпросмотр колоды картинками: фигуры по их координатам, графики по данным.

Колоду четыре раза подряд называли убогой, и каждый раз я чинил её вслепую:
LibreOffice в песочнице pptx не открывает, `pdftoppm` в образе нет — увидеть
слайд нечем, а «убого или нет» разбором файла не проверяется. Отсюда правило:
**поверхность, которую не видно, чинится по одному замечанию за раз** — и это
не работа, а переписка.

Здесь фигуры выкладываются по своим координатам в HTML, графики рисуются по
своим же данным, а снимок делает Chromium — он в образе есть и запускается за
полсекунды. Это НЕ рендер PowerPoint: шрифты подставные, графики приблизительны.
Но пустоту, переполнение, выравнивание и общий вид показывает, а именно они и
были сломаны.

    python3 scripts/deck_preview.py колода.pptx каталог/

Дальше — снимок каждого слайда любым браузером по `preview.html`.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

PX = 96.0  # пикселей на дюйм


def inches(value) -> float:
    return Emu(value).inches if value is not None else 0.0


def colour(fmt) -> str:
    try:
        return "#%02X%02X%02X" % tuple(fmt.rgb)
    except Exception:  # noqa: BLE001
        return "#16202B"


def chart_svg(chart, width: float, height: float) -> str:
    plots = list(chart.plots)
    cats = [str(c) for c in plots[0].categories]
    bars = list(plots[0].series[0].values)
    line = list(plots[1].series[0].values) if len(plots) > 1 else None
    pad = 40
    w, h = width - pad * 2, height - pad * 2
    top = max(bars) or 1
    step = w / max(1, len(cats))
    gap = (plots[0].gap_width or 150) / 100.0
    bar_w = step / (1 + gap)
    out = [f'<svg width="{width}" height="{height}">']
    for i, value in enumerate(bars):
        bh = h * (value / top)
        x = pad + i * step + (step - bar_w) / 2
        out.append(f'<rect x="{x:.1f}" y="{pad + h - bh:.1f}" width="{bar_w:.1f}"'
                   f' height="{bh:.1f}" fill="#1367AE"/>')
        if plots[0].has_data_labels:
            out.append(f'<text x="{x + bar_w / 2:.1f}" y="{pad + h - bh - 6:.1f}"'
                       f' font-size="11" font-weight="700" text-anchor="middle"'
                       f' fill="#16202B">{value:,.0f}</text>'.replace(",", " "))
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{pad + h + 16:.1f}" font-size="10"'
                   f' text-anchor="middle" fill="#5B6B7D">{html.escape(cats[i])}</text>')
    if line:
        lo, hi = min(line), max(line)
        span = (hi - lo) or 1
        points = " ".join(
            f"{pad + i * step + step / 2:.1f},{pad + h - h * 0.75 * (v - lo) / span - h * 0.12:.1f}"
            for i, v in enumerate(line))
        out.append(f'<polyline points="{points}" fill="none" stroke="#0E2A43" stroke-width="2.5"/>')
        for point in points.split():
            x, y = point.split(",")
            out.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#0E2A43"/>')
    out.append("</svg>")
    return "".join(out)


def render(path: str, out_dir: str) -> list[str]:
    deck = Presentation(path)
    width, height = inches(deck.slide_width) * PX, inches(deck.slide_height) * PX
    made = []
    for number, slide in enumerate(deck.slides, 1):
        back = "#FFFFFF"
        try:
            if slide.background.fill.type is not None:
                back = colour(slide.background.fill.fore_color)
        except Exception:  # noqa: BLE001
            pass
        parts = [f'<div class="slide" style="width:{width}px;height:{height}px;'
                 f'background:{back}">']
        for shape in slide.shapes:
            left, top = inches(shape.left) * PX, inches(shape.top) * PX
            w, h = inches(shape.width) * PX, inches(shape.height) * PX
            style = f"position:absolute;left:{left:.1f}px;top:{top:.1f}px;width:{w:.1f}px"
            if shape.has_chart:
                parts.append(f'<div style="{style};height:{h:.1f}px">'
                             + chart_svg(shape.chart, w, h) + "</div>")
            elif shape.has_table:
                rows = []
                for line_no, row in enumerate(shape.table.rows):
                    cells = []
                    for cell in row.cells:
                        fill = colour(cell.fill.fore_color) if cell.fill.type else "#FFF"
                        bold = "font-weight:700;" if line_no == 0 else ""
                        align = ("text-align:right;"
                                 if cell.text_frame.paragraphs[0].alignment else "")
                        cells.append(f'<td style="background:{fill};{bold}{align}">'
                                     f"{html.escape(cell.text)}</td>")
                    rows.append("<tr>" + "".join(cells) + "</tr>")
                parts.append(f'<table style="{style}">' + "".join(rows) + "</table>")
            elif str(shape.shape_type or "").startswith("AUTO_SHAPE"):
                try:
                    fill = colour(shape.fill.fore_color) if shape.fill.type is not None else "#FFF"
                except Exception:  # noqa: BLE001
                    fill = "#FFF"
                inner = ""
                if shape.has_text_frame and shape.text_frame.text.strip():
                    rows = []
                    for para in shape.text_frame.paragraphs:
                        for run in para.runs:
                            size = run.font.size.pt if run.font.size else 14
                            weight = 700 if run.font.bold else 400
                            tone = colour(run.font.color) if run.font.color else "#16202B"
                            rows.append(f'<div style="font-size:{size * 1.333:.1f}px;'
                                        f'font-weight:{weight};color:{tone}">'
                                        f"{html.escape(run.text)}</div>")
                    inner = "".join(rows)
                parts.append(f'<div style="{style};height:{h:.1f}px;background:{fill};'
                             f'border:1px solid #DDE5ED;box-sizing:border-box;'
                             f'padding:{"8px 12px" if inner else "0"}">{inner}</div>')
            elif shape.has_text_frame and shape.text_frame.text.strip():
                lines = []
                for para in shape.text_frame.paragraphs:
                    runs = []
                    for run in para.runs:
                        size = run.font.size.pt if run.font.size else 14
                        weight = 700 if run.font.bold else 400
                        tone = colour(run.font.color) if run.font.color else "#16202B"
                        runs.append(f'<span style="font-size:{size * 1.333:.1f}px;'
                                    f'font-weight:{weight};color:{tone}">'
                                    f"{html.escape(run.text)}</span>")
                    align = {1: "left", 2: "center", 3: "right"}.get(
                        int(para.alignment) if para.alignment is not None else 1, "left")
                    lines.append(f'<div style="text-align:{align}">' + "".join(runs) + "</div>")
                skin = ""
                try:
                    if shape.fill.type is not None:
                        skin = (f"background:{colour(shape.fill.fore_color)};"
                                f"border:1px solid #DDE5ED;padding:8px 12px;"
                                f"box-sizing:border-box;height:{h:.1f}px")
                except Exception:
                    pass
                parts.append(f'<div style="{style};{skin}">' + "".join(lines) + "</div>")
        parts.append(f'<div class="num">слайд {number}</div></div>')
        made.append("".join(parts))
    page = ("<style>body{margin:0;background:#8894a2;font-family:Calibri,Arial,sans-serif}"
            ".slide{position:relative;margin:0 auto 18px;overflow:hidden;box-sizing:border-box}"
            "table{border-collapse:collapse;font-size:14px}"
            "td{border:1px solid #DDE5ED;padding:6px 8px}"
            ".num{position:absolute;left:6px;bottom:2px;font-size:10px;color:#c8d2dc}"
            "</style>" + "".join(made))
    Path(out_dir, "preview.html").write_text(page, encoding="utf-8")
    return made


if __name__ == "__main__":
    where = sys.argv[2] if len(sys.argv) > 2 else "."
    made = render(sys.argv[1], where)
    print(f"слайдов: {len(made)} → {Path(where, 'preview.html')}")
