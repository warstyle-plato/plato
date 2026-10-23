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
import re
from typing import Any, Sequence

WIDTH = 680
HEIGHT = 270
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 58, 64, 24, 48

# Цвет, штрих и маркер каждой линии: в ч/б печати различаются штрих и маркер.
# План — всегда пунктир, факт — сплошная (`_style`).
STYLES = (
    {"color": "#1f4e8c", "dash": "", "marker": "circle"},
    {"color": "#b2541a", "dash": "6 4", "marker": "square"},
    {"color": "#3f7d3a", "dash": "2 3", "marker": "triangle"},
    {"color": "#6b4c9a", "dash": "10 3 2 3", "marker": "diamond"},
)


def _is_plan(name: str) -> bool:
    lowered = name.lower()
    if lowered.startswith("факт"):
        return False
    return lowered.startswith("план") or "по плану" in lowered


def _style(index: int, name: str) -> dict[str, str]:
    style = dict(STYLES[index % len(STYLES)])
    style["dash"] = "6 4" if _is_plan(name) else ""
    return style


def _end_labels(labels: list[tuple[float, float, str, str]]) -> list[str]:
    """Подписи значений у последних точек линий; разведены, чтобы не слиплись."""
    placed: list[float] = []
    out = []
    for x, y, text, color in sorted(labels, key=lambda item: item[1]):
        y = max(y, placed[-1] + 12) if placed else y
        placed.append(y)
        out.append(f'<text x="{x + 7:.1f}" y="{y + 3.5:.1f}" font-size="10.5" font-weight="600" '
                   f'fill="{color}">{html.escape(text)}</text>')
    return out


def _num(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.replace("-", "−")


def _ticks(low: float, high: float, count: int = 5, min_step: float = 0.0) -> list[float]:
    """Деления шкалы. ``min_step`` — не мельче разряда подписи: при целых
    подписях шаг 0,2 давал «0, 0, 0, 1, 1» на графике из двух лотов."""
    if high <= low:
        high = low + 1.0
    raw = max((high - low) / count, min_step)
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
        parts.append(f'<text x="{x+28}" y="{y}" font-size="10.5" fill="#333">{label}</text>')
        x += 36 + 6 * len(name)
    return "".join(parts)


def line_chart(title: str, labels: Sequence[str], series: Sequence[dict[str, Any]],
               unit: str, digits: int = 0, label_every: int = 1) -> str:
    """Линии по общим подписям X. ``series``: ``{"name", "values"}``, None — пропуск."""
    values = [v for s in series for v in s["values"] if v is not None]
    if not labels or not values:
        return ""
    low, high = min(0.0, min(values)), max(values)
    ticks = _ticks(low, high, min_step=10 ** -digits)
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
        out.append(f'<text x="{PAD_LEFT-6}" y="{y+3:.1f}" font-size="10.5" fill="#555" '
                   f'text-anchor="end">{_num(tick, digits)}</text>')
    out.append(f'<text x="8" y="11" font-size="10.5" fill="#555">{html.escape(unit)}</text>')
    for i, label in enumerate(labels):
        if i % max(1, label_every) and i != len(labels) - 1:
            continue
        out.append(f'<text x="{x_at(i):.1f}" y="{HEIGHT-PAD_BOTTOM+14}" font-size="10" fill="#555" '
                   f'text-anchor="middle">{html.escape(label)}</text>')
    styles = []
    ends = []
    for index, item in enumerate(series):
        style = _style(index, item["name"])
        styles.append(style)
        last = next(((i, v) for i, v in reversed(list(enumerate(item["values"])))
                     if v is not None), None)
        if last is not None:
            ends.append((x_at(last[0]), y_at(last[1]), _num(last[1], digits), style["color"]))
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
    out.extend(_end_labels(ends))
    out.append(_legend([s["name"] for s in series], styles))
    out.append("</svg>")
    return f'<figure class="chart"><figcaption>{html.escape(title)}</figcaption>{"".join(out)}</figure>'


BAR_STYLES = ({"fill": "#9db7d6"}, {"fill": "#1f4e8c"}, {"fill": "url(#hatch)"})


# Ширина знака подписи группы (шрифт 10.5px, кириллица) и шаг строки переноса.
LABEL_CHAR_W = 6.0
LABEL_LINE_H = 11


def _wrap(label: str, width: float) -> list[str]:
    """Подпись группы в несколько строк по словам, чтобы уместиться в слот.

    Владелец (23.10.2026, график «Бюджет: план и оплачено по статьям»):
    «Смазалось» — пять длинных названий статей налезали друг на друга.
    Слово длиннее строки остаётся целым: резать слова хуже, чем выйти за слот.
    """
    limit = max(1, int(width / LABEL_CHAR_W))
    lines: list[str] = []
    for word in label.split():
        # Составное слово («Административно-хозяйственные») делится по дефису.
        for part in re.split(r"(?<=-)", word):
            if not part:
                continue
            glue = "" if lines and lines[-1].endswith("-") else " "
            if lines and len(lines[-1]) + len(glue) + len(part) <= limit:
                lines[-1] += glue + part
            else:
                lines.append(part)
    return lines or [label]


def _group_label(x: float, y: float, label: str, lines: Sequence[str]) -> str:
    # Полное название — в aria-label: строки переноса склеиваются без пробела,
    # а читатели разметки (и тесты) ищут название целиком.
    spans = "".join(f'<tspan x="{x:.1f}" dy="{0 if i == 0 else LABEL_LINE_H}">{html.escape(t)}</tspan>'
                    for i, t in enumerate(lines))
    return (f'<text x="{x:.1f}" y="{y}" font-size="10.5" fill="#333" text-anchor="middle" '
            f'class="group" aria-label="{html.escape(label)}">{spans}</text>')


def bar_chart(title: str, groups: Sequence[str], series: Sequence[dict[str, Any]],
              unit: str, digits: int = 0, line: dict[str, Any] | None = None) -> str:
    """Сгруппированные столбцы: группа — подпись X, серия — столбец в группе.

    ``line`` — линия на своей шкале справа (``{"name", "values", "unit",
    "digits"}``): объём и цена на одном графике, как в отчёте о продажах
    (владелец, 22.10.2026: «может совместить для экономии места?»). Левая шкала
    объёма всегда от нуля, шкала цены — от своего минимума: у объёма ноль —
    настоящее начало отсчёта, а у цены нет.
    """
    values = [v for s in series for v in s["values"] if v is not None]
    if not groups or not values:
        return ""
    line_values = [v for v in (line or {}).get("values") or [] if v is not None]
    if not line_values:
        line = None
    ticks = _ticks(min(0.0, min(values)), max(values), min_step=10 ** -digits)
    low, high = ticks[0], ticks[-1]
    inner_w = WIDTH - PAD_LEFT - PAD_RIGHT
    inner_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    slot = inner_w / len(groups)
    bar = min(42.0, slot * 0.8 / max(1, len(series)))
    labels = [_wrap(group, slot - 6) for group in groups]
    # Лишние строки подписей опускают легенду и удлиняют рисунок, а не поле.
    extra = (max(len(lines) for lines in labels) - 1) * LABEL_LINE_H
    height = HEIGHT + extra

    def y_at(v: float) -> float:
        return PAD_TOP + inner_h * (1 - (v - low) / (high - low or 1))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
           f'width="100%" role="img" aria-label="{html.escape(title)}" class="chart">',
           '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
           'patternTransform="rotate(45)"><rect width="6" height="6" fill="#fff"/>'
           '<line x1="0" y1="0" x2="0" y2="6" stroke="#b2541a" stroke-width="2"/></pattern></defs>']
    for tick in ticks:
        y = y_at(tick)
        out.append(f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{WIDTH-PAD_RIGHT}" y2="{y:.1f}" '
                   f'stroke="#e1e6ec" stroke-width="1"/>')
        out.append(f'<text x="{PAD_LEFT-6}" y="{y+3:.1f}" font-size="10.5" fill="#555" '
                   f'text-anchor="end">{_num(tick, digits)}</text>')
    out.append(f'<text x="8" y="11" font-size="10.5" fill="#555">{html.escape(unit)}</text>')
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
            out.append(f'<text x="{left + s*bar + bar/2 - 1:.1f}" y="{top-3:.1f}" font-size="10" '
                       f'fill="#333" text-anchor="middle">{_num(value, digits)}</text>')
        out.append(_group_label(PAD_LEFT + g * slot + slot / 2, HEIGHT - PAD_BOTTOM + 14, group, labels[g]))
    legend = _legend([s["name"] for s in series], BAR_STYLES, bars=True)
    if line:
        style = STYLES[1]
        line_digits = int(line.get("digits") or 0)
        right_ticks = _ticks(min(line_values), max(line_values), count=4,
                             min_step=10 ** -line_digits)
        r_low, r_high = right_ticks[0], right_ticks[-1]

        def ry_at(v: float) -> float:
            return PAD_TOP + inner_h * (1 - (v - r_low) / (r_high - r_low or 1))

        for tick in right_ticks:
            out.append(f'<text x="{WIDTH-PAD_RIGHT+6}" y="{ry_at(tick)+3:.1f}" font-size="10.5" '
                       f'fill="{style["color"]}" text-anchor="start">{_num(tick, line_digits)}</text>')
        out.append(f'<text x="{WIDTH-PAD_RIGHT+6}" y="11" font-size="10.5" fill="{style["color"]}">'
                   f'{html.escape(str(line.get("unit") or ""))}</text>')
        path, points = [], []
        broken = True
        for g, value in enumerate(line["values"]):
            if value is None:
                broken = True
                continue
            x, y = PAD_LEFT + g * slot + slot / 2, ry_at(value)
            path.append(f'{"M" if broken else "L"}{x:.1f},{y:.1f}')
            broken = False
            points.append(_marker(style["marker"], x, y, style["color"]))
        out.append(f'<path d="{" ".join(path)}" fill="none" stroke="{style["color"]}" '
                   f'stroke-width="2" class="line"/>')
        out.extend(points)
        # Подпись у последней точки — внутри поля: справа стоит шкала цены.
        last = next((g, v) for g, v in reversed(list(enumerate(line["values"]))) if v is not None)
        out.append(f'<text x="{PAD_LEFT + last[0]*slot + slot/2:.1f}" y="{ry_at(last[1])-8:.1f}" '
                   f'font-size="10.5" font-weight="600" fill="{style["color"]}" text-anchor="middle">'
                   f'{_num(last[1], line_digits)}</text>')
        swatch = (f'<line x1="{{x}}" y1="{{y}}" x2="{{x2}}" y2="{{y}}" stroke="{style["color"]}" '
                  f'stroke-width="2"/>')
        x = PAD_LEFT + sum(36 + 6 * len(s["name"]) for s in series)
        y = HEIGHT - 10
        legend += (swatch.format(x=x, y=y - 4, x2=x + 22)
                   + _marker(style["marker"], x + 11, y - 4, style["color"])
                   + f'<text x="{x+28}" y="{y}" font-size="10.5" fill="#333">{html.escape(line["name"])}</text>')
    out.append(f'<g transform="translate(0,{extra})">{legend}</g>' if extra else legend)
    out.append("</svg>")
    return f'<figure class="chart"><figcaption>{html.escape(title)}</figcaption>{"".join(out)}</figure>'


def scaled(values: Sequence[float | None], divisor: float) -> list[float | None]:
    """Числа в единицах оси: делитель — тот же, что в подписи единицы."""
    return [None if v is None else v / divisor for v in values]


def every(count: int, fit: int = 12) -> int:
    """Через сколько подписывать X, чтобы подписи не налезали."""
    return max(1, -(-count // fit))

