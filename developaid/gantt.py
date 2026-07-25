from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class GanttItem:
    label: str
    start: date
    end: date
    group: str = "Проект"

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Gantt item ends before it starts: {self.label}")


def _as_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        normalized = value.strip().replace(".", "-")
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(normalized, fmt).date()
            except ValueError:
                pass
    return None


def build_calendar_items(
    project: Mapping[str, object],
    phases: Sequence[Mapping[str, object]] | None = None,
) -> list[GanttItem]:
    """Create report rows from the project calendar without inventing dates.

    The aliases allow the renderer to be connected to the current monolithic model
    first and then simplified when the application schema is normalized.
    """
    aliases: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        ("Покупка участка", ("purchase_date", "land_purchase_date", "deal_date"), ("purchase_end", "land_purchase_end", "deal_date")),
        ("БРИДЖ", ("bridge_start", "bridge_start_date"), ("bridge_end", "bridge_end_date", "rns_date")),
        ("ИРД и проектирование", ("ird_start", "design_start", "project_start"), ("ird_end", "design_end", "rns_date")),
        ("Продажи", ("sales_start", "sales_start_date"), ("sales_end", "sales_end_date", "post_sales_end")),
        ("Строительство", ("construction_start", "construction_start_date", "rns_date"), ("construction_end", "construction_end_date", "rnv_date")),
        ("Постпродажи", ("rnv_date",), ("post_sales_end", "sales_end", "sales_end_date")),
    )

    def first_date(source: Mapping[str, object], keys: Iterable[str]) -> date | None:
        for key in keys:
            parsed = _as_date(source.get(key))
            if parsed is not None:
                return parsed
        return None

    items: list[GanttItem] = []
    for label, start_keys, end_keys in aliases:
        start = first_date(project, start_keys)
        end = first_date(project, end_keys)
        if start and end:
            items.append(GanttItem(label, start, end))

    for index, phase in enumerate(phases or (), start=1):
        phase_name = str(phase.get("name") or phase.get("title") or f"Очередь {index}")
        start = first_date(phase, ("construction_start", "start", "start_date", "rns_date"))
        end = first_date(phase, ("construction_end", "end", "end_date", "rnv_date"))
        if start and end:
            items.append(GanttItem(f"Строительство — {phase_name}", start, end, "Очереди"))
        sales_start = first_date(phase, ("sales_start", "sales_start_date"))
        sales_end = first_date(phase, ("sales_end", "sales_end_date", "post_sales_end"))
        if sales_start and sales_end:
            items.append(GanttItem(f"Продажи — {phase_name}", sales_start, sales_end, "Очереди"))

    return sorted(items, key=lambda item: (item.start, item.end, item.label))


def render_gantt_html(items: Sequence[GanttItem], *, title: str = "Календарный план проекта") -> str:
    """Render a print-safe HTML Gantt block suitable for the existing PDF report."""
    if not items:
        return (
            f'<section class="gantt"><h2>{escape(title)}</h2>'
            '<p class="muted">Для календарного плана недостаточно дат.</p></section>'
        )

    start = min(item.start for item in items)
    end = max(item.end for item in items)
    span = max((end - start).days, 1)

    years = range(start.year, end.year + 1)
    year_cells: list[str] = []
    for year in years:
        year_start = max(start, date(year, 1, 1))
        year_end = min(end, date(year, 12, 31))
        left = ((year_start - start).days / span) * 100
        width = (max((year_end - year_start).days, 1) / span) * 100
        year_cells.append(
            f'<span class="gantt-year" style="left:{left:.3f}%;width:{width:.3f}%">{year}</span>'
        )

    rows: list[str] = []
    for item in items:
        left = ((item.start - start).days / span) * 100
        width = max(((item.end - item.start).days / span) * 100, 0.8)
        rows.append(
            '<div class="gantt-row">'
            f'<div class="gantt-label"><strong>{escape(item.label)}</strong>'
            f'<small>{item.start:%d.%m.%Y}–{item.end:%d.%m.%Y}</small></div>'
            '<div class="gantt-track">'
            f'<span class="gantt-bar" style="left:{left:.3f}%;width:{width:.3f}%"></span>'
            '</div></div>'
        )

    return (
        '<section class="gantt">'
        f'<h2>{escape(title)}</h2>'
        '<div class="gantt-axis"><div></div><div class="gantt-years">'
        + ''.join(year_cells)
        + '</div></div>'
        + ''.join(rows)
        + '</section>'
    )


GANTT_CSS = """
.gantt{break-inside:avoid;margin-top:18px}.gantt h2{margin:0 0 10px}
.gantt-axis,.gantt-row{display:grid;grid-template-columns:210px 1fr;gap:12px}
.gantt-years,.gantt-track{position:relative;min-height:25px;border-left:1px solid #d9dde3;border-right:1px solid #d9dde3}
.gantt-year{position:absolute;top:0;height:100%;font-size:10px;text-align:center;border-left:1px solid #e7e9ed}
.gantt-row{align-items:center;margin:6px 0}.gantt-label{display:flex;flex-direction:column;font-size:10px}
.gantt-label small{font-size:8px;color:#68707c;margin-top:2px}.gantt-track{height:18px;background:repeating-linear-gradient(90deg,#fff 0,#fff 11.9%,#f3f4f6 12%,#f3f4f6 12.2%)}
.gantt-bar{position:absolute;top:3px;height:12px;border-radius:3px;background:#303640;min-width:3px}
.gantt .muted{color:#68707c;font-size:10px}
"""
