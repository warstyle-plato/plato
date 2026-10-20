"""Графики сводки руководству — встроенный SVG без внешних библиотек.

Одна и та же разметка уходит на страницу и в PDF (его печатает Chromium через
`market_search.report_pdf`), поэтому график — это строка SVG, а не картинка и
не скрипт. Линии различаются не только цветом, но и штрихом и маркером: сводку
печатают и в чёрно-белом.

Числа приходят уже посчитанными; здесь только рисование. Единица оси задаётся
вызывающим — тем же делителем, на который он делит числа.
"""

from __future__ import annotations

import html
import math
from typing import Any, Sequence

WIDTH = 680
HEIGHT = 230
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 62, 34, 24, 46

# Цвет, штрих и маркер каждой линии: в ч/б печати различаются штрих и маркер.
STYLES = (
    {"color": "#1f4e8c", "dash": "", "marker": "circle"},
    {"color": "#b2541a", "dash": "6 4", "marker": "square"},
    {"color": "#3f7d3a", "dash": "2 3", "marker": "triangle"},
    {"color": "#6b4c9a", "dash": "10 3 2 3", "marker": "diamond"},
)


def _num(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.replace("-", "−")


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    if high <= low:
        high = low + 1.0
    raw = (high - low) / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    start = (low // step) * step
    out = [round(start, 10)]
    while out[-1] < high - 1e-12:
        out.append(round(out[-1] + step, 10))
    return out


def _marker(kind: str, x: float, y: float, color: str) -> str:
    if kind == "square":
        return f'<rect x="{x-3:.1f}" y="{y-3:.1f}" width="6" height="6" fill="#fff" stroke="{color}" stroke-width="1.5"/>'
    if kind == "triangle":
        return (f'<path d="M{x:.1f},{y-4:.1f} L{x+4:.1f},{y+3:.1f} L{x-4:.1f},{y+3:.1f} Z" '
                f'fill="#fff" stroke="{color}" stroke-width="1.5"/>')
    if kind == "diamond":
        return (f'<path d="M{x:.1f},{y-4:.1f} L{x+4:.1f},{y:.1f} L{x:.1f},{y+4:.1f} L{x-4:.1f},{y:.1f} Z" '
                f'fill="#fff" stroke="{color}" stroke-width="1.5"/>')
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#fff" stroke="{color}" stroke-width="1.5"/>'


def _legend(names: Sequence[str], styles: Sequence[dict[str, str]], bars: bool = False) -> str:
    parts = []
    x = PAD_LEFT
    y = HEIGHT - 10
    for name, style in zip(names, styles):
        if bars:
            parts.append(f'<rect x="{x}" y="{y-8}" width="14" height="9" fill="{style["fill"]}" '
                         f'stroke="#333" stroke-width="0.6"/>')
        else:
            dash = f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
            parts.append(f'<line x1="{x}" y1="{y-4}" x2="{x+22}" y2="{y-4}" stroke="{style["color"]}" '
                         f'stroke-width="2"{dash}/>' + _marker(style["marker"], x + 11, y - 4, style["color"]))
        label = html.escape(name)
        parts.append(f'<text x="{x+28}" y="{y}" font-size="10" fill="#333">{label}</text>')
        x += 36 + 6 * len(name)
    return "".join(parts)


def line_chart(title: str, labels: Sequence[str], series: Sequence[dict[str, Any]],
               unit: str, digits: int = 0, label_every: int = 1) -> str:
    """Линии по общим подписям X. ``series``: ``{"name", "values"}``, None — пропуск."""
    values = [v for s in series for v in s["values"] if v is not None]
    if not labels or not values:
        return ""
    low, high = min(0.0, min(values)), max(values)
    ticks = _ticks(low, high)
    low, high = ticks[0], ticks[-1]
    inner_w = WIDTH - PAD_LEFT - PAD_RIGHT
    inner_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    step = inner_w / max(1, len(labels) - 1)

    def x_at(i: int) -> float:
        return PAD_LEFT + i * step if len(labels) > 1 else PAD_LEFT + inner_w / 2

    def y_at(v: float) -> float:
        return PAD_TOP + inner_h * (1 - (v - low) / (high - low or 1))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
           f'width="100%" role="img" aria-label="{html.escape(title)}" class="chart">']
    for tick in ticks:
        y = y_at(tick)
        out.append(f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{WIDTH-PAD_RIGHT}" y2="{y:.1f}" '
                   f'stroke="#e1e6ec" stroke-width="1"/>')
        out.append(f'<text x="{PAD_LEFT-6}" y="{y+3:.1f}" font-size="9.5" fill="#555" '
                   f'text-anchor="end">{_num(tick, digits)}</text>')
    out.append(f'<text x="8" y="11" font-size="9.5" fill="#555">{html.escape(unit)}</text>')
    for i, label in enumerate(labels):
        if i % max(1, label_every) and i != len(labels) - 1:
            continue
        out.append(f'<text x="{x_at(i):.1f}" y="{HEIGHT-PAD_BOTTOM+14}" font-size="9" fill="#555" '
                   f'text-anchor="middle">{html.escape(label)}</text>')
    styles = []
    for index, item in enumerate(series):
        style = STYLES[index % len(STYLES)]
        styles.append(style)
        path, points = [], []
        broken = True
        for i, value in enumerate(item["values"]):
            if value is None:
                # Пропуск — разрыв линии: дня без данных нет, а не ноль.
                broken = True
                continue
            x, y = x_at(i), y_at(value)
            path.append(f'{"M" if broken else "L"}{x:.1f},{y:.1f}')
            broken = False
            points.append(_marker(style["marker"], x, y, style["color"]))
        if not path:
            continue
        dash = f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        out.append(f'<path d="{" ".join(path)}" fill="none" stroke="{style["color"]}" '
                   f'stroke-width="2"{dash}/>')
        if len(points) <= 40:
            out.extend(points)
    out.append(_legend([s["name"] for s in series], styles))
    out.append("</svg>")
    return f'<figure class="chart"><figcaption>{html.escape(title)}</figcaption>{"".join(out)}</figure>'


BAR_STYLES = ({"fill": "#9db7d6"}, {"fill": "#1f4e8c"}, {"fill": "url(#hatch)"})


def bar_chart(title: str, groups: Sequence[str], series: Sequence[dict[str, Any]],
              unit: str, digits: int = 0) -> str:
    """Сгруппированные столбцы: группа — подпись X, серия — столбец в группе."""
    values = [v for s in series for v in s["values"] if v is not None]
    if not groups or not values:
        return ""
    ticks = _ticks(min(0.0, min(values)), max(values))
    low, high = ticks[0], ticks[-1]
    inner_w = WIDTH - PAD_LEFT - PAD_RIGHT
    inner_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    slot = inner_w / len(groups)
    bar = min(42.0, slot * 0.8 / max(1, len(series)))

    def y_at(v: float) -> float:
        return PAD_TOP + inner_h * (1 - (v - low) / (high - low or 1))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
           f'width="100%" role="img" aria-label="{html.escape(title)}" class="chart">',
           '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
           'patternTransform="rotate(45)"><rect width="6" height="6" fill="#fff"/>'
           '<line x1="0" y1="0" x2="0" y2="6" stroke="#b2541a" stroke-width="2"/></pattern></defs>']
    for tick in ticks:
        y = y_at(tick)
        out.append(f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{WIDTH-PAD_RIGHT}" y2="{y:.1f}" '
                   f'stroke="#e1e6ec" stroke-width="1"/>')
        out.append(f'<text x="{PAD_LEFT-6}" y="{y+3:.1f}" font-size="9.5" fill="#555" '
                   f'text-anchor="end">{_num(tick, digits)}</text>')
    out.append(f'<text x="8" y="11" font-size="9.5" fill="#555">{html.escape(unit)}</text>')
    zero = y_at(0.0)
    for g, group in enumerate(groups):
        left = PAD_LEFT + g * slot + (slot - bar * len(series)) / 2
        for s, item in enumerate(series):
            value = item["values"][g]
            if value is None:
                continue
            y = y_at(value)
            top, height = min(y, zero), abs(zero - y)
            style = BAR_STYLES[s % len(BAR_STYLES)]
            out.append(f'<rect x="{left + s*bar:.1f}" y="{top:.1f}" width="{bar-2:.1f}" '
                       f'height="{max(height, 0.5):.1f}" fill="{style["fill"]}" stroke="#333" '
                       f'stroke-width="0.6"/>')
            out.append(f'<text x="{left + s*bar + bar/2 - 1:.1f}" y="{top-3:.1f}" font-size="8.5" '
                       f'fill="#333" text-anchor="middle">{_num(value, digits)}</text>')
        out.append(f'<text x="{PAD_LEFT + g*slot + slot/2:.1f}" y="{HEIGHT-PAD_BOTTOM+14}" '
                   f'font-size="9.5" fill="#333" text-anchor="middle">{html.escape(group)}</text>')
    out.append(_legend([s["name"] for s in series], BAR_STYLES, bars=True))
    out.append("</svg>")
    return f'<figure class="chart"><figcaption>{html.escape(title)}</figcaption>{"".join(out)}</figure>'


def scaled(values: Sequence[float | None], divisor: float) -> list[float | None]:
    """Числа в единицах оси: делитель — тот же, что в подписи единицы."""
    return [None if v is None else v / divisor for v in values]


def every(count: int, fit: int = 12) -> int:
    """Через сколько подписывать X, чтобы подписи не налезали."""
    return max(1, -(-count // fit))

