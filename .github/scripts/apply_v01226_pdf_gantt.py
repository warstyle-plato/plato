from __future__ import annotations

from pathlib import Path


MAIN = Path("main.py")
text = MAIN.read_text(encoding="utf-8")

old_import = "from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String"
new_import = "from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Polygon, Rect, String"
if old_import not in text:
    raise SystemExit("PDF shapes import not found")
text = text.replace(old_import, new_import, 1)

version_old = 'app = FastAPI(title="DevelopAid Development Investment Model", version="0.12.25")'
version_new = 'app = FastAPI(title="DevelopAid Development Investment Model", version="0.12.26")'
if version_old in text:
    text = text.replace(version_old, version_new, 1)

story_marker = '''        return drawing

    story=[P("DevelopAid",h1)'''
if story_marker not in text:
    raise SystemExit("PDF story marker not found")

gantt_function = r'''        return drawing

    def gantt_drawings(items: list[dict[str, Any]], chunk_size: int = 18) -> list[Drawing]:
        """Build a real calendar Gantt for the PDF report.

        Bars are positioned by actual project dates. Milestones are diamonds.
        Multi-phase projects keep separate event rows and use phase colours.
        Long calendars are split into several repeated-axis drawings.
        """
        prepared: list[dict[str, Any]] = []
        for raw in items:
            try:
                start = d(raw.get("start"))
                end = d(raw.get("end") or raw.get("start"))
            except Exception:
                continue
            if end < start:
                start, end = end, start
            item = dict(raw)
            item["_start"] = start
            item["_end"] = end
            prepared.append(item)
        if not prepared:
            return []

        first = min(item["_start"] for item in prepared)
        last = max(item["_end"] for item in prepared)
        q_month = ((first.month - 1) // 3) * 3 + 1
        horizon_start = date(first.year, q_month, 1)
        last_q_month = ((last.month - 1) // 3) * 3 + 1
        horizon_end = add_months(date(last.year, last_q_month, 1), 3)
        total_days = max(1, (horizon_end - horizon_start).days)

        width = 500.0
        label_width = 148.0
        track_x = label_width
        track_width = width - label_width
        axis_height = 36.0
        row_height = 19.0
        phase_palette = ["#171717", "#A35D00", "#2D6A4F", "#4F6D7A", "#7A5C61"]
        group_palette = {
            "Финансирование": "#4B4B4B",
            "Продажи": "#7B7B7B",
            "Социальная нагрузка": "#A0A0A0",
            "Строительство": "#202020",
            "Подготовка": "#666666",
            "Ключевые вехи": "#111111",
        }

        def x_at(value: date) -> float:
            ratio = (value - horizon_start).days / total_days
            return track_x + track_width * max(0.0, min(1.0, ratio))

        chunks = [prepared[i:i + chunk_size] for i in range(0, len(prepared), chunk_size)]
        drawings: list[Drawing] = []
        for chunk in chunks:
            rows: list[tuple[str, Any]] = []
            previous_group = None
            for item in chunk:
                group = str(item.get("group") or "Прочее")
                if group != previous_group:
                    rows.append(("group", group))
                    previous_group = group
                rows.append(("event", item))

            height = axis_height + row_height * len(rows) + 4.0
            drawing = Drawing(width, height)
            body_top = height - axis_height

            drawing.add(Rect(0, body_top, width, axis_height, fillColor=colors.HexColor("#F6F6F4"), strokeColor=None))
            drawing.add(Line(label_width, 0, label_width, height, strokeColor=colors.HexColor("#CFCFCF"), strokeWidth=0.6))
            drawing.add(String(4, height - 13, "Этап / событие", fontName=bold, fontSize=7.4, fillColor=colors.HexColor("#222222")))

            quarter = horizon_start
            while quarter < horizon_end:
                next_quarter = add_months(quarter, 3)
                x = x_at(quarter)
                x_next = x_at(next_quarter)
                drawing.add(Line(x, 0, x, body_top, strokeColor=colors.HexColor("#DDDDDD"), strokeWidth=0.45))
                drawing.add(String((x + x_next) / 2, height - 29, f"Q{((quarter.month - 1) // 3) + 1}", fontName=regular, fontSize=6.2, textAnchor="middle", fillColor=colors.HexColor("#666666")))
                quarter = next_quarter
            drawing.add(Line(x_at(horizon_end), 0, x_at(horizon_end), body_top, strokeColor=colors.HexColor("#DDDDDD"), strokeWidth=0.45))

            for year in range(horizon_start.year, horizon_end.year + 1):
                ys = max(horizon_start, date(year, 1, 1))
                ye = min(horizon_end, date(year + 1, 1, 1))
                if ye <= ys:
                    continue
                x1, x2 = x_at(ys), x_at(ye)
                drawing.add(String((x1 + x2) / 2, height - 12, str(year), fontName=bold, fontSize=7.0, textAnchor="middle", fillColor=colors.HexColor("#333333")))
                drawing.add(Line(x1, 0, x1, height, strokeColor=colors.HexColor("#B9B9B9"), strokeWidth=0.75))

            for row_index, (kind, value) in enumerate(rows):
                y = body_top - (row_index + 1) * row_height
                drawing.add(Line(0, y, width, y, strokeColor=colors.HexColor("#E4E4E4"), strokeWidth=0.4))
                if kind == "group":
                    drawing.add(Rect(0, y, width, row_height, fillColor=colors.HexColor("#F1F1EF"), strokeColor=None))
                    drawing.add(String(4, y + 6, str(value).upper(), fontName=bold, fontSize=6.5, fillColor=colors.HexColor("#666666")))
                    continue

                item = value
                label = str(item.get("label") or "—")
                phase_name = str(item.get("phase_name") or "").strip()
                if phase_name and phase_name.lower() not in label.lower():
                    label = f"{phase_name} · {label}"
                if len(label) > 34:
                    label = label[:32] + "…"
                start = item["_start"]
                end = item["_end"]
                drawing.add(String(4, y + 9, label, fontName=regular, fontSize=6.7, fillColor=colors.HexColor("#222222")))
                date_label = start.strftime("%m.%Y") if start == end else f"{start.strftime('%m.%Y')}—{end.strftime('%m.%Y')}"
                drawing.add(String(4, y + 2.3, date_label, fontName=regular, fontSize=5.4, fillColor=colors.HexColor("#777777")))

                phase_index = int(item.get("phase_index") or 0)
                colour = phase_palette[min(max(phase_index - 1, 0), len(phase_palette) - 1)] if phase_index else group_palette.get(str(item.get("group") or ""), "#333333")
                fill = colors.HexColor(colour)
                x1 = x_at(start)
                x2 = x_at(end + timedelta(days=1))
                centre_y = y + row_height / 2
                milestone = str(item.get("kind") or "") == "milestone" or start == end
                if milestone:
                    size = 4.1
                    drawing.add(Polygon([x1, centre_y + size, x1 + size, centre_y, x1, centre_y - size, x1 - size, centre_y], fillColor=fill, strokeColor=None))
                else:
                    drawing.add(Rect(x1, centre_y - 4.0, max(2.2, x2 - x1), 8.0, fillColor=fill, strokeColor=None))

            drawing.add(Line(0, 0, width, 0, strokeColor=colors.HexColor("#CFCFCF"), strokeWidth=0.6))
            drawings.append(drawing)
        return drawings

    story=[P("DevelopAid",h1)'''

text = text.replace(story_marker, gantt_function, 1)

old_calendar = '''    events=calendar_data.get('events') or []
    if events:
        story.append(PageBreak());story.append(P("Календарь проекта",h2));event_rows=[["Этап","Начало","Окончание","Группа"]]
        for item in events: event_rows.append([item.get('label') or '—',item.get('start') or '—',item.get('end') or '—',item.get('group') or '—'])
        story.append(table(event_rows,[72*mm,30*mm,30*mm,38*mm],font_size=7.2))
'''
new_calendar = '''    events=calendar_data.get('events') or []
    if events:
        gantt_pages=gantt_drawings(events)
        for page_index,gantt in enumerate(gantt_pages):
            story.append(PageBreak())
            story.append(P("Календарный план проекта" if page_index==0 else "Календарный план проекта · продолжение",h2))
            story.append(gantt)
        story.append(Spacer(1,2*mm))
        story.append(P("Полосы построены по фактическим датам модели; ромбами отмечены ключевые вехи. При включённой очередности этапы каждой очереди показаны отдельными строками.",small))
'''
if old_calendar not in text:
    raise SystemExit("Old calendar table block not found")
text = text.replace(old_calendar, new_calendar, 1)

MAIN.write_text(text, encoding="utf-8")
print("Integrated PDF calendar Gantt into main.py")
