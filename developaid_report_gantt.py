"""График сводки по корпусам: укрупнённые статьи, план, прогноз и РНВ.

«График как в мониторе, но с укрупнёнными статьями по корпусам с планом и
прогнозом окончания работ и РНВ» (владелец, 20.10.2026).

Своих расчётов здесь нет. Дерево работ, сроки по утверждённому ГПР и прогноз
окончания по темпу берутся из среза Монитора (`schedule.management` после
слоя темпа). Группировка повторяет Гант Монитора (`managementByCorpus` на его
странице): корпус берётся из объекта, раздела и названия работы по тому же
правилу (`CORPUS_PATTERN`), внутри корпуса работы собираются по статьям РСС,
к которым их привязал ГПР. Ступень «подземная/надземная часть» Монитора здесь
опущена: руководству нужны статьи, а не разбивка сметы.

Прогноз статьи известен, если он известен хотя бы у одной её работы (темп
актов или утверждённый перенос); неизвестный прогноз — «прогноза нет», а не
плановая дата. Рисунок — встроенный SVG, одна разметка для страницы и PDF;
план — пунктирный контур, прогноз — сплошная полоса: различимо в ч/б.
"""

from __future__ import annotations

import datetime
import html
import re
from typing import Any

# То же правило, что `corpusLabel` на странице Монитора; проверка держит
# их одинаковыми (tests/test_report_gantt.py).
CORPUS_PATTERN = r"(?:корпус|корп\.?|башня)\s*№?\s*([0-9A-Za-zА-Яа-я-]+)"
_CORPUS = re.compile(CORPUS_PATTERN, re.IGNORECASE)


def corpus_of(task: dict[str, Any]) -> str:
    parts = " ".join(str(task.get(key) or "") for key in ("object", "section", "name")
                     if task.get(key))
    found = _CORPUS.search(parts)
    if found:
        return f"Корпус {found.group(1)}"
    obj = str(task.get("object") or "").strip()
    return obj if obj and len(obj) < 90 else "Общие работы"


def _natural(text: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", str(text))]


def _date(value: Any) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _tasks(nodes: list[dict[str, Any]], rss: dict[str, Any] | None = None,
           out: list[tuple[dict[str, Any], dict[str, Any] | None]] | None = None):
    out = [] if out is None else out
    for node in nodes or []:
        here = node if node.get("level") == "rss" else rss
        if node.get("level") == "task":
            out.append((node, here))
        _tasks(node.get("children") or [], here, out)
    return out


def _known(task: dict[str, Any]) -> bool:
    return (task.get("pace_forecast_known") is True
            or task.get("forecast_source") == "approved_rebaseline")


def _summary(items: list[dict[str, Any]], known_of) -> dict[str, Any]:
    starts = [day for day in (_date(item.get("plan_start")) for item in items) if day]
    ends = [day for day in (_date(item.get("plan_finish")) for item in items) if day]
    known = [item for item in items if known_of(item)]
    forecasts = [day for day in (_date(item.get("forecast_finish")) for item in known) if day]
    plan_finish = max(ends) if ends else None
    forecast = max(forecasts) if forecasts else None
    # Опоздание — по строкам, где прогноз известен, каждой против её же плана.
    # Сравнить общий прогноз с общим планом нельзя: работа без прогноза
    # (не начатое благоустройство) отодвигает план, но не прогноз, и корпус
    # с опозданием выглядел бы опережающим.
    deltas = [(_date(item.get("forecast_finish")) - _date(item.get("plan_finish"))).days
              for item in known
              if _date(item.get("forecast_finish")) and _date(item.get("plan_finish"))]
    return {
        "plan_start": min(starts).isoformat() if starts else None,
        "plan_finish": plan_finish.isoformat() if plan_finish else None,
        "forecast_finish": forecast.isoformat() if forecast else None,
        "forecast_known": forecast is not None,
        "forecast_partial": bool(known) and len(known) < len(items),
        "delta_days": max(deltas) if deltas else None,
    }


def model(management: list[dict[str, Any]]) -> dict[str, Any]:
    """Корпуса и их статьи из дерева Монитора."""
    corpora: dict[str, dict[str, list]] = {}
    names: dict[str, str] = {}
    for task, rss in _tasks(management):
        code = str((rss or {}).get("code") or task.get("code") or "")
        corpora.setdefault(corpus_of(task), {}).setdefault(code, []).append(task)
        names.setdefault(code, str((rss or {}).get("name") or ""))
    if not corpora:
        return {"state": "missing", "reason": "В Мониторе нет утверждённого графика работ "
                                              "с датами — рисовать нечего."}
    out = []
    for corpus in sorted(corpora, key=_natural):
        articles = []
        for code in sorted(corpora[corpus], key=_natural):
            mixed = code.startswith("2.1")
            label = "ПОС и общеплощадочные работы" if mixed else (names[code] or "Статья без названия")
            row = _summary(corpora[corpus][code], _known)
            articles.append(dict(row, code=code, name=label,
                                 note="по актам этой статьи прогноз окончания не строится"
                                 if mixed else ""))
        out.append(dict(_summary(articles, lambda item: item["forecast_known"]),
                        name=corpus, articles=articles))
    return {"state": "ok", "corpora": out}


# --------------------------------------------------------------------------
# Рисунок
# --------------------------------------------------------------------------

WIDTH = 680
LABEL = 228
RIGHT = 80
ROW = 19
TOP = 30
PLAN = "#555"
FORECAST = "#1f4e8c"
LATE = "#b2541a"

_MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _months(first: datetime.date, last: datetime.date) -> list[datetime.date]:
    out, day = [], datetime.date(first.year, first.month, 1)
    while day <= last:
        out.append(day)
        day = datetime.date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return out


def _diamond(x: float, y: float, filled: bool) -> str:
    fill = FORECAST if filled else "#fff"
    return (f'<path d="M{x:.1f},{y - 5:.1f} L{x + 5:.1f},{y:.1f} L{x:.1f},{y + 5:.1f} '
            f'L{x - 5:.1f},{y:.1f} Z" fill="{fill}" stroke="{FORECAST}" stroke-width="1.5"/>')


def _day(value: datetime.date) -> str:
    return value.strftime("%d.%m.%Y")


def svg(gantt: dict[str, Any], cut: Any = None, rnv: dict[str, Any] | None = None) -> str:
    """Гант по корпусам; ``rnv`` — блок срока ввода сводки (``approved``, ``forecast``)."""
    if gantt.get("state") != "ok":
        return ""
    rnv = rnv or {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for corpus in gantt["corpora"]:
        rows.append(("corpus", corpus))
        rows.extend(("article", article) for article in corpus["articles"])
    plan_rnv, forecast_rnv = _date(rnv.get("approved")), _date(rnv.get("forecast"))
    today = _date(cut)
    days = [day for _, row in rows for day in (_date(row.get("plan_start")),
                                               _date(row.get("plan_finish")),
                                               _date(row.get("forecast_finish"))) if day]
    days += [day for day in (plan_rnv, forecast_rnv, today) if day]
    if not days:
        return ""
    first, last = min(days), max(days)
    first = datetime.date(first.year, first.month, 1)
    span = max((last - first).days + 15, 30)
    inner = WIDTH - LABEL - RIGHT
    height = TOP + ROW * (len(rows) + 1) + 34

    def x(day: datetime.date) -> float:
        return LABEL + inner * (day - first).days / span

    out = [(f'<svg class="chart gantt" viewBox="0 0 {WIDTH} {height}" width="100%" '
            f'role="img" aria-label="График работ по корпусам" '
            f'xmlns="http://www.w3.org/2000/svg" font-family="Arial, sans-serif">'),
           ('<text x="0" y="13" font-size="12.5" font-weight="700" fill="#1b2a3a">'
            'Сроки работ по корпусам: утверждённый график и прогноз по темпу</text>')]
    months = _months(first, first + datetime.timedelta(days=span))
    step = 1 if len(months) <= 14 else 3 if len(months) <= 40 else 6
    bottom = TOP + ROW * (len(rows) + 1)
    for month in months:
        if (month.month - 1) % step:
            continue
        mx = x(month)
        out.append(f'<line x1="{mx:.1f}" y1="{TOP - 4}" x2="{mx:.1f}" y2="{bottom}" '
                   f'stroke="#e3e8ee" stroke-width="1"/>')
        label = _MONTHS[month.month - 1] + (f" {month.year % 100:02d}"
                                            if month.month == 1 or month == months[0] else "")
        out.append(f'<text x="{mx + 2:.1f}" y="{TOP - 7}" font-size="9" fill="#6a7785">'
                   f'{label}</text>')
    y = TOP
    for kind, row in rows:
        start, plan_end = _date(row.get("plan_start")), _date(row.get("plan_finish"))
        forecast = _date(row.get("forecast_finish"))
        bold = kind == "corpus"
        name = row["name"] if bold else f"{row['code']} {row['name']}".strip()
        if bold:
            out.append(f'<rect x="0" y="{y:.1f}" width="{WIDTH}" height="{ROW}" fill="#f2f5f8"/>')
        out.append(f'<text x="{0 if bold else 10}" y="{y + 13:.1f}" font-size="10.5" '
                   f'font-weight="{700 if bold else 400}" fill="#1b2a3a">'
                   f'<title>{html.escape(name)}</title>{html.escape(_short(name, 36 if bold else 40))}'
                   f'</text>')
        if start and plan_end:
            out.append(f'<rect x="{x(start):.1f}" y="{y + 3:.1f}" '
                       f'width="{max(x(plan_end) - x(start), 2):.1f}" height="6" fill="#fff" '
                       f'stroke="{PLAN}" stroke-width="1" stroke-dasharray="4 2"/>')
        note = "нет прогноза"
        if start and forecast:
            out.append(f'<rect x="{x(start):.1f}" y="{y + 10:.1f}" '
                       f'width="{max(x(forecast) - x(start), 2):.1f}" height="6" '
                       f'fill="{FORECAST}"/>')
            delta = row.get("delta_days")
            if plan_end and forecast > plan_end:
                out.append(f'<rect x="{x(plan_end):.1f}" y="{y + 10:.1f}" '
                           f'width="{max(x(forecast) - x(plan_end), 1):.1f}" height="6" '
                           f'fill="{LATE}"/>')
            note = (f"+{delta} дн." if isinstance(delta, int) and delta > 0
                    else f"−{-delta} дн." if isinstance(delta, int) and delta < 0
                    else "в срок" if isinstance(delta, int) else "")
            if row.get("forecast_partial"):
                note += "*"
        out.append(f'<text x="{WIDTH - RIGHT + 6}" y="{y + 13:.1f}" font-size="9.5" '
                   f'font-weight="{700 if note.startswith("+") else 400}" '
                   f'fill="{LATE if note.startswith("+") else "#6a7785"}">{note}</text>')
        y += ROW
    # Ввод в эксплуатацию — веха проекта, а не корпуса.
    out.append(f'<text x="0" y="{y + 13:.1f}" font-size="10.5" font-weight="700" '
               f'fill="#1b2a3a">РНВ (разрешение на ввод)</text>')
    if plan_rnv:
        out.append(_diamond(x(plan_rnv), y + 9, False))
    if forecast_rnv:
        out.append(_diamond(x(forecast_rnv), y + 9, True))
    delay = rnv.get("delay_days")
    note = (f"+{delay:.0f} дн." if isinstance(delay, (int, float)) and delay > 0
            else "" if plan_rnv else "плана нет")
    out.append(f'<text x="{WIDTH - RIGHT + 6}" y="{y + 13:.1f}" font-size="9.5" '
               f'fill="{LATE if note.startswith("+") else "#6a7785"}">{note}</text>')
    if today:
        out.append(f'<line x1="{x(today):.1f}" y1="{TOP - 4}" x2="{x(today):.1f}" '
                   f'y2="{bottom}" stroke="#b42318" stroke-width="1" stroke-dasharray="2 2"/>'
                   f'<text x="{x(today) + 2:.1f}" y="{bottom + 10}" font-size="9" '
                   f'fill="#b42318">сегодня</text>')
    ly = bottom + 24
    out.append(
        f'<rect x="0" y="{ly - 7}" width="22" height="6" fill="#fff" stroke="{PLAN}" '
        f'stroke-dasharray="4 2"/><text x="27" y="{ly}" font-size="9.5" fill="#33414f">'
        f'план по утверждённому графику</text>'
        f'<rect x="190" y="{ly - 7}" width="22" height="6" fill="{FORECAST}"/>'
        f'<text x="217" y="{ly}" font-size="9.5" fill="#33414f">прогноз по темпу</text>'
        f'<rect x="318" y="{ly - 7}" width="14" height="6" fill="{LATE}"/>'
        f'<text x="337" y="{ly}" font-size="9.5" fill="#33414f">опоздание</text>'
        f'{_diamond(415, ly - 4, False)}<text x="424" y="{ly}" font-size="9.5" '
        f'fill="#33414f">РНВ план</text>{_diamond(488, ly - 4, True)}'
        f'<text x="497" y="{ly}" font-size="9.5" fill="#33414f">РНВ прогноз</text>')
    out.append("</svg>")
    return "".join(out)


def notes(gantt: dict[str, Any], rnv: dict[str, Any] | None = None) -> list[str]:
    """Пояснения под графиком: чего на нём нет и почему."""
    out = []
    rnv = rnv or {}
    if not rnv.get("approved"):
        out.append("Утверждённой даты РНВ в данных нет: она берётся из выгрузки "
                   "планировщика с сетью работ, а её в Монитор не загружали.")
    corpora = gantt.get("corpora") or []
    if any(item.get("forecast_partial") for corpus in corpora
           for item in [corpus, *corpus["articles"]]):
        out.append("* Прогноз посчитан не по всем работам строки: у части работ темпа "
                   "актов ещё нет, их срок не учтён.")
    if any(not article["forecast_known"] for corpus in corpora for article in corpus["articles"]):
        out.append("«Нет прогноза» — по работам статьи ещё нет актов, темп считать не из чего.")
    return out


def text_lines(gantt: dict[str, Any]) -> list[str]:
    """Корпуса для сообщения: окончание по плану и по прогнозу."""
    out = []
    for corpus in gantt.get("corpora") or []:
        plan, forecast = _date(corpus.get("plan_finish")), _date(corpus.get("forecast_finish"))
        if not plan:
            continue
        line = f"{corpus['name']}: окончание работ по графику {_day(plan)}"
        if forecast and corpus.get("forecast_partial"):
            delta = corpus.get("delta_days") or 0
            line += ("; прогноз есть не по всем работам, по известным — "
                     + (f"опоздание до {delta} дн." if delta > 0 else "в срок."))
            out.append(line)
            continue
        if forecast:
            delta = corpus.get("delta_days") or 0
            line += (f", прогноз {_day(forecast)}"
                     + (f" (+{delta} дн.)" if delta > 0
                        else f" (раньше на {-delta} дн.)" if delta < 0 else " — в срок"))
        else:
            line += ", прогноза пока нет"
        out.append(line + ".")
    return out
