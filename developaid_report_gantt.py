"""График сводки по корпусам: укрупнённые статьи, план, прогноз и РНВ.

calendar/render_calendar сохраняют полный канонический календарь нового
Монитора; прежние model/render и скалярные статьи сохранены для совместимости
текстовых выводов. Компактная сводка читает выбранную проекцию через
compact_model/render_compact и соединяет корпуса по явным referenceID.
Разметка не пересчитывает сроки и веса.

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
import copy
import html
import math
import re
from collections import Counter, defaultdict
from typing import Any

import developaid_schedule_done as done_rule

# То же правило, что `corpusLabel` на странице Монитора; проверка держит
# их одинаковыми (tests/test_report_gantt.py).
CORPUS_PATTERN = r"(?:корпус|корп\.?|башня)\s*№?\s*([0-9A-Za-zА-Яа-я-]+)"
_CORPUS = re.compile(CORPUS_PATTERN, re.IGNORECASE)


def corpus_of(task: dict[str, Any]) -> str:
    obj = str(task.get("object") or "").strip()
    if obj and re.search(r"паркинг|parking", obj, re.I):
        return obj
    own = _CORPUS.search(obj)
    if own:
        return f"Корпус {own.group(1)}"
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


def _done(task: dict[str, Any]) -> bool:
    """Работа закончена — так её отметил слой темпа Монитора (`work_done`)."""
    return task.get("work_done") is True


def finished_late_text(row: dict[str, Any]) -> str:
    """Опоздание уже законченных работ — та же фраза, что на странице Монитора."""
    days = row.get("finished_late_days")
    return f"Закончено на {days} дн. позже плана" if days else ""


def missing_text(row: dict[str, Any]) -> str:
    """«у K работ нет прогноза[, N стоит]» — те же слова, что в клетке страницы.
    Если у всех K есть только план, то «нет данных о темпе» (решение владельца)."""
    missing = row.get("missing_forecast") or []
    k, stopped = len(missing), missing.count("stalled")
    if not k:
        return ""
    works = "работы" if k % 10 == 1 and k % 100 != 11 else "работ"
    what = "данных о темпе" if all(m == "plan" for m in missing) else "прогноза"
    stand = ("" if not stopped else
             f", {stopped} {'стоит' if stopped % 10 == 1 and stopped % 100 != 11 else 'стоят'}")
    return f"у {k} {works} нет {what}{stand}"


def _summary(items: list[dict[str, Any]], known_of) -> dict[str, Any]:
    starts = [day for day in (_date(item.get("plan_start")) for item in items) if day]
    ends = [day for day in (_date(item.get("plan_finish")) for item in items) if day]
    known = [item for item in items if known_of(item)]
    forecasts = [day for day in (_date(item.get("forecast_finish")) for item in known
                                 if not done_rule.observed_only(item)) if day]
    plan_finish = max(ends) if ends else None
    forecast = max(forecasts) if forecasts else None
    # Опоздание — то, что Монитор записал строке (`delta_days`): у
    # завершённой по ГПР работы его нет, разница «дата файла − план» не
    # опоздание. Сравнить общий прогноз с общим планом тоже нельзя: работа без
    # прогноза (не начатое благоустройство) отодвигает план, но не прогноз.
    # Законченная работа не опаздывает сейчас; её опоздание — отдельно,
    # «закончено на N дн. позже плана» (`finished_late_days`).
    deltas = [item["delta_days"] for item in known
              if item.get("delta_days") is not None and not _done(item)]
    finished_late = [item["finished_late_days"] for item in items if item.get("finished_late_days")]
    # Работы без прогноза срока — та же выборка, что у страницы (`missing_forecast`):
    # у строки статьи/корпуса — сумма по вложенным, у работы — она сама.
    missing = [m for item in items for m in (item["missing_forecast"] if "missing_forecast" in item else
               [] if known_of(item) or _done(item) else [item.get("pace_forecast_method") or ""])]
    return {
        "plan_start": min(starts).isoformat() if starts else None,
        "plan_finish": plan_finish.isoformat() if plan_finish else None,
        "forecast_finish": forecast.isoformat() if forecast else None,
        "forecast_known": forecast is not None,
        "forecast_partial": bool(known) and (len(known) < len(items)
                                             or any(item.get("forecast_partial") for item in known)),
        "delta_days": max(deltas) if deltas else None,
        "finished_late_days": max(finished_late) if finished_late else None,
        "all_done": bool(items) and all(item.get("all_done") is True or _done(item) for item in items),
        "missing_forecast": missing,
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
        out.append(dict(_summary(articles, lambda item: item["forecast_known"] or item["all_done"]),
                        name=corpus, articles=articles))
    return {"state": "ok", "corpora": out}


# --------------------------------------------------------------------------
# Рисунок
# --------------------------------------------------------------------------

WIDTH = 680
LABEL = 228
RIGHT = 112  # «срок пока не оценить» помещается целиком
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
        note = ((f"закончено +{row['finished_late_days']} дн." if row.get("finished_late_days")
                 else "завершено") if row.get("all_done") else "срок пока не оценить")
        if start and forecast:
            out.append(f'<rect x="{x(start):.1f}" y="{y + 10:.1f}" '
                       f'width="{max(x(forecast) - x(start), 2):.1f}" height="6" '
                       f'fill="{FORECAST}"/>')
            delta = row.get("delta_days")
            if plan_end and forecast > plan_end:
                out.append(f'<rect x="{x(plan_end):.1f}" y="{y + 10:.1f}" '
                           f'width="{max(x(forecast) - x(plan_end), 1):.1f}" height="6" '
                           f'fill="{LATE}"/>')
            note = ((f"закончено +{row['finished_late_days']} дн." if row.get("finished_late_days")
                     else "завершено") if row.get("all_done")
                    else f"+{delta} дн." if isinstance(delta, int) and delta > 0
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
        out.append("Утверждённой даты РНВ в данных нет: проверьте утверждённый ГПР проекта.")
    corpora = gantt.get("corpora") or []
    if any(item.get("forecast_partial") for corpus in corpora
           for item in [corpus, *corpus["articles"]]):
        out.append("* Прогноз посчитан не по всем работам строки: у части работ нет "
                   "актуального темпа по ГПР или подтверждённым объёмам, их срок не учтён.")
    if any(not article["forecast_known"] and not article["all_done"]
           for corpus in corpora for article in corpus["articles"]):
        out.append("«Срок пока не оценить» — по работам нет актуального темпа выполнения.")
    return out


def render(gantt: dict[str, Any], cut: Any = None, *, explanations: bool = True) -> str:
    """Executive corpus lanes; article detail remains opt-in, not a long PDF."""
    if gantt.get('state') != 'ok':
        return ''
    from developaid_schedule_visual import styles, lanes, legend, date_text
    out = [styles(), '<div class="chart gantt"><section class="schedule-overview">']
    caption = 'Срез на '+date_text(cut)+'. Даты взяты из графика Монитора.' if cut else ''
    rows = [dict(corpus, id='corpus:'+str(i), forecast_label=(
                    'По известным работам' if corpus.get('forecast_partial') else 'Прогноз'),
                 subtitle='. '.join(part for part in ('Все работы завершены' if corpus.get('all_done') else '',
                                                      finished_late_text(corpus)) if part))
            for i, corpus in enumerate(gantt.get('corpora') or [])]
    out.append(lanes(rows, heading='План и прогноз по корпусам', caption=caption))
    out.append(legend(rows))
    article_count = sum(len(corpus.get('articles') or []) for corpus in gantt.get('corpora') or [])
    if article_count:
        out.append('<details class="schedule-article-details schedule-article-tree"><summary>Этапы и статьи по корпусам ('+str(article_count)+')</summary>')
    for corpus in gantt.get('corpora') or []:
        articles = corpus.get('articles') or []
        if not articles:
            continue
        out.append('<details class="schedule-article-details schedule-article-leaf"><summary>'+html.escape(str(corpus['name']))+
                   ': этапы и статьи ('+str(len(articles))+')</summary>')
        out.append(lanes([dict(article, id=str(article.get('code') or ''),
                               forecast_label=('По известным работам' if article.get('forecast_partial') else 'Прогноз'))
                          for article in articles]))
        out.append('</details>')
    if article_count:
        out.append('</details>')
    if explanations:
        out.append('<p class="schedule-note">Процент физической готовности корпуса из денежных актов не выводится. '
                   'Если прогноз есть только по части работ, это явно указано у даты.</p>')
    out.append('</section></div>')
    return ''.join(out)


def text_lines(gantt: dict[str, Any]) -> list[str]:
    """Корпуса для сообщения: окончание по плану и по прогнозу."""
    out = []
    for corpus in gantt.get("corpora") or []:
        plan, forecast = _date(corpus.get("plan_finish")), _date(corpus.get("forecast_finish"))
        if not plan:
            continue
        line = f"{corpus['name']}: окончание работ по графику {_day(plan)}"
        # Нет отклонения — значит, его не посчитали, а не «в срок».
        delta = corpus.get("delta_days")
        late = finished_late_text(corpus)
        if corpus.get("all_done"):
            line += ", все работы завершены" + (". " + late if late else "")
        elif forecast and corpus.get("forecast_partial"):
            line += ("; срок пока не оценить: " + (missing_text(corpus) or "прогноз есть не по всем работам")
                     + (f" (у остальных опоздание до {delta} дн.)" if delta is not None and delta > 0
                        else " (остальные идут по сроку)" if delta is not None
                        else " (у остальных отклонение от графика не посчитано)"))
        elif forecast:
            line += (f", прогноз {_day(forecast)}"
                     + (f" (+{delta} дн.)" if delta is not None and delta > 0
                        else f" (раньше на {-delta} дн.)" if delta is not None and delta < 0
                        else " — в срок" if delta is not None
                        else "; отклонение от графика не посчитано"))
        else:
            line += "; срок пока не оценить" + (": " + missing_text(corpus) if missing_text(corpus) else "")
        if late and not corpus.get("all_done"):
            line += "; среди законченных работ: " + late[0].lower() + late[1:]
        out.append(line + ".")
    return out


def _attested_partial_calendar_gap(reference, references, scope, mapping, gaps, id_scope):
    """Read native declared uncertainty; never repair or infer missing members."""
    if type(gaps) is not list or len(gaps) > 2000:
        return False
    indexed = {}
    for gap in gaps:
        if (type(gap) is not dict or set(gap) != {'work_id','remaining_id','kind'}
                or type(gap['work_id']) is not str or gap['work_id'] not in references
                or gap['work_id'] in indexed or gap['work_id'] not in mapping or type(gap['kind']) is not str):
            return False
        key, kind, remaining = gap['work_id'], gap['kind'], gap['remaining_id']
        qualification = scope.get(key) or {}
        if type(qualification) is not dict:
            return False
        if kind == 'unclassified_scope':
            valid = qualification == {'status':'gap','reason':kind} and remaining is None
        elif kind == 'outside_current_source':
            valid = id_scope == 'full_source' and not qualification and mapping[key] is None and remaining is None
        elif kind == 'unknown_time':
            current = mapping.get(key)
            valid = (not qualification and type(current) in {str,int}
                     and type(remaining) is str and remaining == str(current))
        else:
            return False
        if not valid:
            return False
        indexed[key] = kind
    return indexed.get(reference) in {'unclassified_scope','outside_current_source'}


def calendar(schedule: dict[str, Any], cut: Any) -> dict[str, Any]:
    """Copy the compiled source roster and qualify its canonical display points.

    No forecast or group progress is calculated here. A bad point remains a
    named gap; other source rows and individually qualified points survive.
    """
    roster = []
    def collect(nodes, control='', detail='', rss=''):
        for node in nodes or []:
            level = node.get('level')
            here = (str(node.get('name') or '') if level == 'control' else control,
                    str(node.get('name') or '') if level == 'detail' else detail,
                    str(node.get('name') or node.get('code') or '') if level == 'rss' else rss)
            if level == 'task':
                roster.append(dict(task=copy.deepcopy(node), control=here[0], detail=here[1], rss=here[2]))
            collect(node.get('children'), *here)
    collect(schedule.get('management'))
    for task in schedule.get('undated_works') or []:
        roster.append(dict(task=copy.deepcopy(task), control='', detail=str(task.get('section') or 'Работы с неполными датами'), rss=''))
    owner = schedule.get('owner_rnv') or {}
    owner = owner if isinstance(owner, dict) else {}
    result = dict(schema=1, cut=str(cut), rows=roster, display=None, qualified=False, points={}, issues=[],
                  readiness_forecast_invalid=False, owner_rnv=copy.deepcopy(owner) if owner.get('source') == 'owner_decision' and _date(owner.get('date')) else None)
    def problem(reason, *, invalid=True):
        result['issues'].append(reason)
        if invalid:
            result['readiness_forecast_invalid'] = True
    source = [*(schedule.get('rows') or []), *(schedule.get('undated_works') or [])]
    source = source or [item['task'] for item in roster]
    present = {str(item['task']['id']) for item in roster if item['task'].get('id') is not None}
    missing = [row for row in schedule.get('rows') or [] if row.get('id') is not None and str(row['id']) not in present]
    for row in missing:
        roster.append(dict(task=copy.deepcopy(row),control='Иерархию работы нужно проверить',
                           detail=str(row.get('section') or 'Работы вне исходной иерархии'),rss=''))
    if missing:
        problem('В исходном перечне есть работы без строки в иерархии ГПР. Они сохранены отдельно; общая календарная дата требует сверки состава.')
    by_id = defaultdict(list)
    for row in source:
        if row.get('id') is not None:
            by_id[str(row['id'])].append(row)
    tree_ids = Counter(str(item['task']['id']) for item in roster if item['task'].get('id') is not None)
    state = schedule.get('readiness') or {}
    project = state.get('project') or {} if isinstance(state, dict) else None
    forecast = project.get('forecast') or {} if isinstance(project, dict) else None
    display = forecast.get('display') or {} if isinstance(forecast, dict) else None
    identity = state.get('forecast_identity') or {} if isinstance(state, dict) else None
    mapping = identity.get('remaining_ids') or {} if isinstance(identity, dict) else None
    issues = result['issues']
    def unavailable(reason, *, invalid=True):
        problem(reason, invalid=invalid)
        return result
    if not display:
        return unavailable('Для этого среза нет подтверждённой календарной проекции. План и исходные показания сохранены.', invalid=False)
    if not roster:
        return unavailable('Для календаря нет полного исходного перечня работ. Независимая оценка готовности сохранена.', invalid=False)
    if (not all(isinstance(value, dict) for value in [state,project,forecast,display,identity,mapping])
            or not isinstance(project.get('work_ids'), list)
            or not isinstance(state.get('forecast_scope') or {}, dict)):
        return unavailable('Структура календарной проекции не подтверждена. План и исходные показания сохранены.')
    valid_date = lambda value: value is None or isinstance(value, str) and _date(value) is not None and _date(value).isoformat() == value
    if (type(display.get('schema')) is not int or display.get('schema') != 1
            or display.get('basis') != 'readiness_project_forecast' or display.get('truncated') is not False
            or not isinstance(display.get('rows'), list) or len(display['rows']) > 2000
            or not isinstance(display.get('paragraphs'), list) or len(display['paragraphs']) != 2
            or not all(isinstance(p, str) and 0 < len(p) <= 4000 for p in display['paragraphs'])):
        return unavailable('Календарная проекция неполна или имеет неподтверждённый формат. План и показания сохранены.')
    if (state.get('cut') != str(cut) or display.get('cut') != str(cut)
            or not re.fullmatch(r'[a-f0-9]{64}', str(state.get('source_sha256') or ''))
            or forecast.get('source_sha256') != state.get('source_sha256')
            or identity.get('source_sha256') != state.get('source_sha256')
            or not isinstance(forecast.get('id_scope'), str) or forecast['id_scope'] not in {'current_source', 'full_source'}
            or any(display.get(key) != forecast.get(key) for key in
                   ['source_sha256','full_source_sha256','id_scope','finish','total','covered','reference_total'])
            or any(identity.get(key) != forecast.get(key) for key in ['source_sha256','full_source_sha256','id_scope'])
            or forecast.get('id_scope') == 'full_source' and not re.fullmatch(r'[a-f0-9]{64}', str(forecast.get('full_source_sha256') or ''))
            or not valid_date(display.get('finish'))
            or any(type(display.get(key)) is not int or display[key] < 0 for key in ['total','covered','reference_total'])
            or display['covered'] > display['total']):
        return unavailable('Источник, дата среза или состав календарной проекции не совпадают с текущим ГПР. Общая дата не показана; план и показания сохранены.')
    result['display'] = copy.deepcopy(display)
    references = [str(key) for key in project.get('work_ids') or []]
    counts = Counter(references)
    translations = Counter(str(value) for value in mapping.values() if value is not None)
    # Only an explicit exclusion attested by the same native projection can
    # reduce its denominator. A missing translation remains a selected gap.
    exclusions = forecast.get('excluded')
    attested_exclusions = {}
    if not isinstance(exclusions, list):
        problem('Исключения из календарного состава не подтверждены. Общая дата требует сверки.')
    else:
        for exclusion in exclusions:
            if (not isinstance(exclusion, dict) or not isinstance(exclusion.get('work_id'), str)
                    or exclusion['work_id'] not in counts or exclusion['work_id'] in attested_exclusions
                    or not isinstance(exclusion.get('kind'), str)
                    or exclusion['kind'] not in {'separate_scope','nonconstruction_scope'}):
                problem('Не подтверждено исключение работы из календарного состава. План и показания сохранены.')
                continue
            attested_exclusions[exclusion['work_id']] = exclusion['kind']
    if (type(project.get('total')) is not int or project['total'] != len(references)
            or display['reference_total'] != len(references)
            or display['total'] != len(references)-len(attested_exclusions)):
        problem('Число исходных работ не совпадает с подтверждённым календарным составом. Общая дата скрыта; план и показания сохранены.')
    expected = {}
    declared_gaps = set()
    for reference in references:
        qualification = (state.get('forecast_scope') or {}).get(reference) or {}
        if counts[reference] != 1:
            problem('Идентификатор выбранной работы повторяется. Общая дата требует сверки состава; исходные строки сохранены.')
            continue
        if not isinstance(qualification, dict):
            problem('Не подтверждён формат связи работы с выбранным составом. План и показания сохранены.')
            continue
        if qualification.get('status') is not None and not isinstance(qualification['status'], str):
            problem('Не подтверждён статус связи работы с выбранным составом. План и показания сохранены.')
            continue
        status = qualification.get('status')
        if status == 'excluded':
            if (not isinstance(qualification.get('reason'), str)
                    or qualification['reason'] not in {'separate_scope','nonconstruction_scope'}
                    or attested_exclusions.get(reference) != qualification['reason']):
                problem('Исключение выбранной работы не подтверждено исходной проекцией. Общая дата требует сверки состава.')
            continue
        if reference in attested_exclusions or status not in {None,'gap'}:
            problem('Статус выбранной работы противоречит исходной календарной проекции. План и показания сохранены.')
        if status == 'gap' or reference not in mapping or mapping[reference] is None:
            attested = _attested_partial_calendar_gap(reference, references,
                state.get('forecast_scope') or {}, mapping, forecast.get('gaps'), forecast.get('id_scope'))
            if attested:
                declared_gaps.add(reference)
            problem('Для выбранной работы не подтверждена точная связь с текущим ГПР. Общая дата скрыта; план и показания сохранены.', invalid=not attested)
            continue
        current = mapping[reference]
        if isinstance(current, bool) or not isinstance(current, (str,int)) or not str(current) or len(str(current)) > 512:
            problem('Нет точного идентификатора работы в текущем источнике. План и показания сохранены.')
            continue
        current = str(current)
        if counts[reference] != 1 or translations[current] != 1 or len(by_id[current]) != 1 or tree_ids[current] != 1:
            problem('Неоднозначная связь работы с выбранным составом. Эта точка не показана; исходные строки сохранены.')
            continue
        expected[current] = reference
    point_counts = Counter(p.get('work_id') for p in display['rows'] if isinstance(p, dict) and isinstance(p.get('work_id'), str))
    for point in display['rows']:
        key = point.get('work_id') if isinstance(point, dict) else None
        row = by_id[key][0] if isinstance(key, str) and len(by_id[key]) == 1 else None
        scenario = (row or {}).get('plan_pace_scenario') or {}
        complete = bool(scenario.get('complete') or (row or {}).get('work_done'))
        measured = bool((row or {}).get('forecast_known') and not (row or {}).get('observed_complete_by'))
        finish = None if complete else ((row or {}).get('forecast_finish') if measured else None) or scenario.get('finish') or None
        basis = 'complete' if complete else ('measured' if measured else 'conditional') if finish else 'unknown'
        if (not row or point_counts[key] != 1 or expected.get(key) != point.get('reference_work_id')
                or not key or len(key) > 512 or not valid_date(point.get('finish')) or not valid_date(point.get('plan_finish'))
                or point.get('finish') != finish or point.get('plan_finish') != (row.get('plan_finish') or None)
                or point.get('complete') is not complete or point.get('basis') != basis
                or not valid_date(point.get('source_date')) or point.get('source_date') and point['source_date'] > str(cut)
                or point.get('source_date') != (scenario.get('source_date') or None)):
            label = str((row or {}).get('name') or 'Работа без однозначной связи с источником')
            problem('Не подтверждена календарная точка: '+label+'. Её прогноз не показан; план и показание сохранены.')
            continue
        result['points'][key] = copy.deepcopy(point)
    if set(result['points']) != set(expected):
        problem('Не для каждой работы выбранного состава подтверждена календарная точка. Общая дата скрыта; пригодные индивидуальные даты сохранены.')
    if declared_gaps and (display['total'] != len(result['points']) + len(declared_gaps)
            or display['covered'] != sum(bool(point['complete'] or point['finish']) for point in result['points'].values())):
        problem('Покрытие частичной оценки не совпало с исходными точками и заявленными пробелами. Общая дата требует сверки.')
    result['qualified'] = not issues
    return result


def _calendar_progress(task):
    """Read a supplied physical/GPR observation; monetary acceptance is separate."""
    physical = ('gpr_percent','cumulative_quantities','cumulative_statement','confirmed_completion')
    fact = task.get('display_progress')
    if isinstance(fact, dict) and (task.get('progress_kind') != 'accepted_cost_ratio'
            or fact.get('source') in physical or fact.get('basis') in physical):
        result = dict(fact)
    elif task.get('gpr_progress') is not None:
        result = dict(value=task['gpr_progress'], date=task.get('gpr_progress_date'), label='Выполнено по ГПР', source='ГПР')
    elif task.get('progress_kind') in physical:
        origin = task.get('progress_source') or {}
        result = dict(value=task.get('actual_progress', task.get('pace_progress')), date=origin.get('date'),
                      label='По ведомости' if task.get('progress_kind') == 'cumulative_statement' else 'Выполнено по ГПР', source=origin.get('label'))
    else:
        result = dict(value=None)
    value = result.get('value')
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0 <= value <= 1:
        result['value'] = None
    return result


def render_calendar(model: dict[str, Any], cut: Any = None) -> str:
    """One responsive full-work calendar for the summary and native A4 print."""
    from developaid_schedule_visual import date_text
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    rows = model.get('rows') or []
    if not rows:
        return '<p class="note">В этом срезе нет исходных работ для календаря.</p>'
    same_cut = model.get('cut') == str(cut)
    display = model.get('display') or {}
    qualified = bool(model.get('qualified') and same_cut)
    points = (model.get('points') or {}) if same_cut else {}
    finish = display.get('finish') if qualified else None
    owner = model.get('owner_rnv') or {}
    days = [date for item in rows for date in (_date(item['task'].get('plan_start')), _date(item['task'].get('plan_finish')), _date(item['task'].get('actual_finish'))) if date]
    days += [date for date in (_date(p.get('finish')) for p in points.values()) if date]
    days += [date for date in [_date(finish), _date(owner.get('date')), _date(cut)] if date]
    first, last = (min(days), max(days)) if days else (None,None)
    if days:
        first = first-datetime.timedelta(days=min(15,(first-datetime.date.min).days))
        last = last+datetime.timedelta(days=min(15,(datetime.date.max-last).days))
    span = max(1,(last-first).days) if days else 1
    def pos(value):
        date = _date(value)
        return max(0,min(100,(date-first).days/span*100)) if date and days else None
    def marker(value, name, title):
        x = pos(value)
        return (f'<i class="{name}" data-date="{esc(value)}" style="left:{x:.5f}%" title="{esc(title)}"></i>') if x is not None else ''
    def marks():
        return marker(cut,'cg-cut','Дата среза '+date_text(cut))+marker(finish,'gpr-scoped-finish','Оценка выбранного состава; не РНВ')+marker(owner.get('date'),'cg-owner-rnv','Отдельный план РНВ владельца')
    out = [_CALENDAR_STYLE, '<div class="chart gantt"><section class="report-gpr-calendar" data-calendar-version="canonical" data-cut="'+esc(cut)+'">']
    if qualified:
        out.append('<p class="cg-scope"><b>Гант учтённого состава: '+esc(date_text(finish) if finish else 'окончание неизвестно')+'</b><br>Даты учтены для '+str(display['covered'])+' из '+str(display['total'])+' работ. Это оценка выбранного состава, не прогноз РНВ. Остальные работы сохранены с планом и исходными показаниями.</p>')
    else:
        out.append('<p class="cg-gap"><b>Общая календарная оценка не подтверждена.</b> План и исходные показания всех работ сохранены.</p>')
    for issue in model.get('issues') or []:
        out.append('<p class="cg-gap">'+esc(issue)+'</p>')
    if not same_cut:
        out.append('<p class="cg-gap">Дата этой проекции не совпадает со срезом отчёта. Прогнозные точки скрыты.</p>')
    if owner:
        out.append('<p class="note">Отдельный план РНВ владельца: '+esc(date_text(owner['date']))+'.</p>')
    out.append('<div class="cg-legend"><span>▱ План</span><span>━ Показание выполнения</span><span>┊ Оценка выбранного состава</span><span>▨ Условный срок, при плановом темпе</span><span>┃ Измеренный срок</span></div>')
    out.append('<div class="cg-axis"><b>Корпус, этап и работа</b><div class="cg-track" data-domain-start="'+esc(first.isoformat() if days else '')+'" data-domain-end="'+esc(last.isoformat() if days else '')+'">')
    if days:
        for index in range(7):
            tick = first+datetime.timedelta(days=round(span*index/6))
            out.append('<span class="cg-tick" style="left:'+str(index/6*100)+'%">'+esc(tick.strftime('%m.%y'))+'</span>')
    out.append(marks()+'</div><b>План, выполнение и основание срока</b></div>')
    corpora = {}
    for item in rows:
        corpora.setdefault(corpus_of(item['task']), {}).setdefault(item['detail'] or item['control'] or str(item['task'].get('section') or 'Работы'), []).append(item)
    for corpus, stages in sorted(corpora.items(), key=lambda item:_natural(item[0])):
        out.append('<details class="cg-corpus" open><summary>'+esc(corpus)+'</summary>')
        for stage, items in stages.items():
            out.append('<details class="cg-stage"><summary>'+esc(stage)+' · '+str(len(items))+' работ</summary>')
            for item in items:
                task = item['task'];key = '' if task.get('id') is None else str(task['id']);point = points.get(key)
                scope = 'selected' if point else 'unconfirmed' if not qualified else 'outside'
                fact = _calendar_progress(task);value = fact.get('value')
                progress = ('Выполнение неизвестно' if value is None else str(fact.get('label') or 'По источнику')+': '+f'{value*100:g}%'+(' от '+date_text(fact['date']) if fact.get('date') else ''))
                if _date(task.get('actual_finish')):
                    end = 'Фактическое окончание: '+date_text(task['actual_finish'])
                elif point and point['complete']:
                    end = 'Завершено по источнику; фактическая дата не подтверждена'
                elif point and point['finish']:
                    end = ('Условное окончание: ' if point['basis']=='conditional' else 'Измеренное окончание: ')+date_text(point['finish'])
                elif point:
                    end = 'Окончание неизвестно'
                else:
                    end = 'Вне выбранного состава' if qualified else 'Точка прогноза не подтверждена'
                out.append('<article class="cg-work" data-work-id="'+esc(key)+'" data-forecast-scope="'+scope+'"><div class="cg-label"><b>'+esc(task.get('name') or 'Работа без названия')+'</b>')
                path = ' → '.join(str(x) for x in [task.get('object') or corpus,item['control'],item['detail'],item['rss']] if x)
                if path:out.append('<small>'+esc(path)+'</small>')
                cells = task.get('source_cells') or {}
                refs = ', '.join(str(cells[k]) for k in ['progress','start','finish'] if cells.get(k))
                if refs:out.append('<small>Ячейки исходного ГПР: '+esc(refs)+'</small>')
                elif task.get('wbs'):out.append('<small>Работа '+esc(task['wbs'])+'</small>')
                out.append('</div><div><div class="cg-track">'+marks())
                start, stop = pos(task.get('plan_start')), pos(task.get('plan_finish'))
                if start is not None and stop is not None and stop >= start:
                    out.append(f'<span class="cg-plan" style="left:{start:.5f}%;width:{max(.2,stop-start):.5f}%"></span>')
                    if value is not None:out.append(f'<span class="cg-fact" style="left:{start:.5f}%;width:{(stop-start)*value:.5f}%"></span>')
                if point and point['finish']:
                    x = pos(point['finish']);left = min(stop,x) if stop is not None else x
                    out.append(f'<span class="cg-forecast {point["basis"]}" style="left:{left:.5f}%;width:{abs(x-(stop if stop is not None else x)):.5f}%"></span><i class="gpr-forecast-end {point["basis"]}" data-finish="{esc(point["finish"])}" style="left:{x:.5f}%"></i>')
                out.append(marker(task.get('actual_finish'),'cg-actual','Фактическое окончание по источнику')+'</div></div><div class="cg-metrics"><div>'+esc(progress)+'</div><div>План: '+esc(date_text(task.get('plan_start')))+' — '+esc(date_text(task.get('plan_finish')))+'</div><b>'+esc(end)+'</b>')
                if point and point['basis']=='conditional':out.append('<div>Основание: плановый темп, а не измеренная скорость.</div>')
                if point and point['basis']=='measured':out.append('<div>Основание: датированный темп выполнения.</div>')
                if not point:out.append('<div>План и показание этой работы сохранены отдельно от общей оценки.</div>')
                out.append('</div></article>')
            out.append('</details>')
        out.append('</details>')
    out.append('</section></div>')
    return ''.join(out)


_CALENDAR_STYLE = '''<style>
.report-gpr-calendar{max-width:100%;overflow-wrap:anywhere}.report-gpr-calendar *{box-sizing:border-box}.cg-scope,.cg-gap{font-size:12px;line-height:1.5}.cg-gap{color:#825314}.cg-legend{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:10px;color:#475569;margin:12px 0}.cg-axis,.cg-work{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1.25fr) minmax(0,1.2fr);gap:12px;align-items:start}.cg-axis{font-size:10px;padding:10px 0}.cg-axis .cg-track{height:28px}.cg-track{position:relative;height:38px;min-width:0;background:repeating-linear-gradient(to right,#f3f5f8,#f3f5f8 calc(16.666% - 1px),#dce3eb calc(16.666% - 1px),#dce3eb 16.666%)}.cg-tick{position:absolute;top:0;font-size:9px;transform:translateX(-50%);white-space:nowrap}.cg-tick:first-child{transform:none}.cg-tick:nth-child(7){transform:translateX(-100%)}.cg-track i{position:absolute;top:0;bottom:0;pointer-events:none}.cg-cut{border-left:1px solid #666}.gpr-scoped-finish{border-left:2px dashed #245b93}.cg-owner-rnv{border-left:1px dashed #7b5396}.cg-actual{border-left:3px solid #207448}.cg-plan,.cg-fact,.cg-forecast{position:absolute;height:8px;top:9px;min-width:0}.cg-plan{border:1px dashed #586575}.cg-fact{top:12px;height:4px;background:#267a58}.cg-forecast{top:25px;height:5px;background:#245b93}.cg-forecast.conditional{background:repeating-linear-gradient(120deg,#8c5eaa,#8c5eaa 3px,#e4d8ed 3px,#e4d8ed 6px)}.gpr-forecast-end{top:21px!important;height:13px;border-left:3px solid #245b93}.gpr-forecast-end.conditional{border-color:#8c5eaa}.cg-corpus>summary{font-weight:700;font-size:14px;background:#eef3f8;padding:9px;cursor:pointer}.cg-stage>summary{font-size:12px;font-weight:600;padding:9px;cursor:pointer}.cg-work{padding:10px 0;border-bottom:1px solid #e4e9ef;break-inside:avoid;page-break-inside:avoid}.cg-label b{font-size:11px}.cg-label small{display:block;color:#667085;font-size:9px;margin-top:4px}.cg-metrics{font-size:10px;line-height:1.5}.cg-metrics b{display:block}.cg-stage,.cg-corpus{margin:8px 0;break-inside:auto;page-break-inside:auto}
@media(max-width:600px){.cg-axis{grid-template-columns:1fr}.cg-axis>b{display:none}.cg-axis .cg-track{height:25px}.cg-work{grid-template-columns:1fr;gap:7px}.cg-label b{font-size:13px}.cg-metrics{font-size:12px}.cg-scope,.cg-gap{font-size:13px}}
@media print{.cg-corpus::details-content,.cg-stage::details-content{display:block!important;content-visibility:visible!important}.cg-corpus,.cg-stage{display:block!important;break-inside:auto!important;page-break-inside:auto!important}.cg-corpus>summary,.cg-stage>summary{break-after:avoid;page-break-after:avoid;list-style:none}.cg-work{grid-template-columns:minmax(0,1.05fr) minmax(0,1.25fr) minmax(0,1.2fr);gap:9px}.cg-label b{font-size:9pt}.cg-label small{font-size:7pt}.cg-metrics{font-size:8pt}.cg-axis{grid-template-columns:minmax(0,1.05fr) minmax(0,1.25fr) minmax(0,1.2fr)}.cg-axis>b{display:block}.cg-track{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style>'''


def compact_model(block: dict[str, Any], cut: Any) -> dict[str, Any]:
    """Report-only overview. Join explicit reference IDs; never calculate a forecast."""
    from developaid_gpr_summary import gpr_summary
    state = block.get('readiness') or {}
    projection = block.get('calendar') or {}
    summary = gpr_summary(state, cut)
    project = state.get('project') or {}
    forecast = project.get('forecast') or {}
    display = projection.get('display') or {}
    identity = state.get('forecast_identity') or {}
    mapping = identity.get('remaining_ids') or {}
    rows = projection.get('rows') or []
    points = projection.get('points') or {}
    corpora = state.get('corpora') or []
    valid_day = lambda value: isinstance(value, str) and _date(value) is not None and _date(value).isoformat() == value
    by_id = {str(item['task']['id']): item['task'] for item in rows
             if isinstance(item, dict) and isinstance(item.get('task'), dict) and item['task'].get('id') is not None}
    # Requalify only the compiled DTO already supplied to this renderer. The
    # native validator owns source/scope/exclusion/point-date rules; there is
    # no second, weaker interpretation of its qualified flag here.
    tasks = [dict(task, level='task') for task in by_id.values()]
    checked = calendar(dict(rows=tasks, undated_works=[], management=tasks,
                            readiness=state), cut)
    projection_matches = (not projection or
                          (projection.get('schema') == checked['schema']
                           and projection.get('cut') == str(cut)
                           and len(by_id) == len(rows) and projection.get('issues') == checked['issues']
                           and projection.get('display') == checked['display'] and points == checked['points']))
    # Corpus membership is another explicit ID join, not inferred from labels.
    references = project.get('work_ids') or []
    memberships = [key for group in corpora for key in group.get('work_ids') or []]
    membership_matches = len(memberships) == len(set(memberships)) and set(memberships) == set(references)
    readiness_bound = bool(summary and membership_matches
                           and re.fullmatch('[a-f0-9]{64}', str(summary['source_sha256'] or '')))
    assessment_bound = bool(readiness_bound and projection_matches
                            and checked['readiness_forecast_invalid'] is False
                            and summary['id_scope'] in {'current_source', 'full_source'}
                            and (summary['id_scope'] != 'full_source' or
                                 re.fullmatch('[a-f0-9]{64}', str(summary['full_source_sha256'] or ''))))
    valid = bool(readiness_bound and projection_matches and projection.get('qualified') is True
                 and checked['qualified'] and display.get('finish') == summary['finish'])
    excluded = {item['work_id'] for item in forecast.get('excluded') or []} if checked['qualified'] else set()
    def aggregate(keys):
        selected = [points[mapping[key]] for key in keys if mapping.get(key) in points]
        tasks = [by_id[p['work_id']] for p in selected if p.get('work_id') in by_id]
        starts = [t.get('plan_start') for t in tasks]
        plans = [p.get('plan_finish') for p in selected]
        unknown = len(selected) != len(keys) or any(not p.get('complete') and not valid_day(p.get('finish')) for p in selected)
        dated = [p['finish'] for p in selected if valid_day(p.get('finish'))]
        return dict(selected=len(selected) if valid else None, total=len(keys),
                    plan_start=min(starts) if valid and starts and all(map(valid_day, starts)) else None,
                    plan_finish=max(plans) if valid and plans and all(map(valid_day, plans)) else None,
                    finish=max(dated, default=None) if valid and not unknown else None,
                    complete=bool(valid and selected and not unknown and all(p.get('complete') for p in selected)),
                    partial=bool(unknown), unknown=not valid or unknown)
    groups = []
    for group in corpora:
        keys = [key for key in group.get('work_ids') or [] if key not in excluded]
        joined = [by_id[mapping[key]] for key in keys if mapping.get(key) in by_id]
        # The membership is an ID join. Source object labels only name an
        # explicitly joined group; a work mentioning another corpus cannot move it.
        objects = {t.get('object') for t in joined if t.get('object')}
        groups.append(dict(name=group.get('name') or 'Объект не указан', progress=group.get('progress'),
                           partial_progress=bool(group.get('partial')), objects=objects,
                           **aggregate(keys)))
    outside_groups = {}
    for task in by_id.values():
        if str(task['id']) in points:
            continue
        obj = task.get('object') or 'Объект не указан'
        matches = [g for g in groups if g['total'] and obj in g['objects']]
        existing = matches[0] if len(matches) == 1 else outside_groups.get(obj)
        if existing is None:
            existing = dict(name=obj, progress=None, partial_progress=False, objects={obj},
                            selected=0, total=0, plan_start=None, plan_finish=None, finish=None,
                            complete=False, partial=False, unknown=True)
            groups.append(existing)
            outside_groups[obj] = existing
        existing['outside'] = existing.get('outside', 0) + 1
    matrix = []
    for stage in state.get('matrix') or []:
        cells = []
        for group in corpora:
            found = [cell for cell in stage.get('cells') or [] if cell.get('name') == group.get('name')]
            cell = found[0] if len(found) == 1 else {}
            keys = cell.get('work_ids') or []
            cells.append(cell.get('progress') if readiness_bound and set(keys) <= set(group.get('work_ids') or []) else None)
        matrix.append(dict(stage=stage.get('stage') or 'Этап не указан', values=cells))
    owner = projection.get('owner_rnv') or {}
    owner_date = owner.get('date') if owner.get('source') == 'owner_decision' and valid_day(owner.get('date')) else None
    return dict(qualified=bool(valid), assessment_qualified=assessment_bound,
                readiness_qualified=readiness_bound, finish=summary['finish'] if assessment_bound else None,
                covered=forecast.get('covered') if assessment_bound else None,
                total=forecast.get('total') if assessment_bound else None,
                summary=summary, groups=groups, matrix=matrix, matrix_columns=len(corpora),
                owner_plan=owner_date, cut=str(cut))


def render_compact(model: dict[str, Any]) -> str:
    """Three report blocks share the same bound project date, on screen and paper."""
    from developaid_schedule_visual import date_text
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    def pct(value):
        return f'{value*100:.1f}%'.replace('.', ',') if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1 else 'Нет данных'
    finish = model['finish']
    finish_text = date_text(finish) if finish else 'Пока не определён'
    project_attr = ' data-project-forecast="'+esc(finish)+'"'
    summary = model.get('summary') or {}
    out = [_COMPACT_STYLE, '<div class="report-gpr-compact">', '<section data-gpr-block="forecast"'+project_attr+'><h3>Прогноз учтённых работ</h3><strong class="rg-project-date">'+esc(finish_text)+'</strong>']
    if finish:
        count_text = lambda value: str(value) if type(value) is int and value >= 0 else 'неизвестно'
        out.append('<p>Условная оценка при плановом темпе. Сроки учтены для '+count_text(model['covered'])+' из '+count_text(model['total'])+' работ. Это не прогноз разрешения на ввод.</p>')
        if not model['qualified']:
            out.append('<p>Общая оценка сохранена. Календарные даты корпусов пока не подтверждены.</p>')
    else:
        out.append('<p>Для этого среза нет подтверждённой общей календарной оценки. Плановая дата её не заменяет.</p>')
    if summary:
        out.append('<p>'+esc(summary['readiness_text'])+'</p>')
    if summary.get('progress') is None and summary.get('reason'):
        out.append('<p class="rg-gap">'+esc(str(summary['reason'])[:240])+'</p>')
    if model['owner_plan']:
        out.append('<p class="rg-owner-plan">План РНВ владельца: '+esc(date_text(model['owner_plan']))+'.</p>')
    out.append('<p><a href="/monitor#tab=monitor">Подробные работы и источники — в Мониторе</a>.</p></section>')
    out.append('<section data-gpr-block="matrix"'+project_attr+'><h3>Матрица готовности</h3>')
    cols = model['matrix_columns'];selected_groups = model['groups'][:cols]
    if cols:
        out.append('<table class="rg-matrix"><thead><tr><th scope="col">Этап</th>'+''.join('<th scope="col">'+esc(g['name'])+'</th>' for g in selected_groups)+'</tr></thead><tbody>')
        for stage in model['matrix']:
            out.append('<tr><th scope="row">'+esc(stage['stage'])+'</th>'+''.join('<td>'+esc(pct(v))+'</td>' for v in stage['values'])+'</tr>')
        out.append('<tr class="rg-total"><th scope="row">По корпусу</th>'+''.join('<td>'+esc(pct(g['progress']) if model['readiness_qualified'] else 'Нет данных')+(' · частично' if g['partial_progress'] else '')+'</td>' for g in selected_groups)+'</tr>')
        out.append('<tr class="rg-project-total"><th scope="row">Прогноз проекта</th><td colspan="'+str(cols)+'">'+esc(finish_text)+'</td></tr></tbody></table>')
    else:
        out.append('<p>Матрица выбранного состава для этого среза отсутствует.</p>')
    out.append('</section><section data-gpr-block="gantt"'+project_attr+'><h3>Гант по корпусам</h3><p>Пунктир — план учтённых работ, цветная полоса — их оценка окончания. Вертикальная линия — прогноз проекта: '+esc(finish_text)+'.</p>')
    dates = [value for g in model['groups'] for value in (g['plan_start'], g['plan_finish'], g['finish']) if _date(value)]
    dates += [v for v in (finish, model['cut']) if _date(v)]
    first = datetime.date(min(_date(v).year for v in dates), 1, 1) if dates else None
    last_year = max(_date(v).year for v in dates) if dates else None
    last = datetime.date(last_year + 1, 1, 1) if dates and last_year < 9999 else _date(max(dates)) if dates else None
    span = max(1, (last-first).days) if dates else 1
    pos = lambda value: (_date(value)-first).days/span*100 if first and _date(value) else None
    if first:
        years = list(range(first.year, last_year+1));stride = max(1, math.ceil(len(years)/6))
        out.append('<div class="rg-axis"><span>Корпус / состав</span><div class="rg-years">')
        for year in years[::stride]:
            out.append('<span data-year="'+str(year)+'" style="left:'+str(pos(str(year)+'-01-01'))+'%">'+str(year)+'</span>')
        out.append('</div></div>')
    for group in model['groups']:
        outside = not group['total']
        status = 'Вне выбранного состава проекта' if outside else 'Завершено по источнику' if group['complete'] else date_text(group['finish']) if group['finish'] else 'Окончание неизвестно'
        note = ('Состав этой оценки не подтверждён' if group['selected'] is None
                else str(group['selected'])+' из '+str(group['total'])+' выбранных работ') if not outside else str(group.get('outside', 0))+' исходных работ; не включены в общий прогноз'
        if not outside and group.get('outside'):
            note += '; ещё '+str(group['outside'])+' вне выбранного состава'
        out.append('<article class="rg-corpus" data-corpus="'+esc(group['name'])+'" data-selected="'+esc(group['selected'])+'" data-plan-finish="'+esc(group['plan_finish'])+'" data-corpus-forecast="'+esc(group['finish'])+'"><div><b>'+esc(group['name'])+'</b><small>'+esc(note)+'</small></div><div><div class="rg-track">')
        start, plan, end = pos(group['plan_start']), pos(group['plan_finish']), pos(group['finish'])
        if start is not None and plan is not None and plan >= start:
            out.append('<span class="rg-plan" style="left:'+str(start)+'%;width:'+str(plan-start)+'%"></span>')
        if start is not None and end is not None and end >= start:
            out.append('<span class="rg-forecast" style="left:'+str(start)+'%;width:'+str(end-start)+'%"></span>')
        if finish:
            out.append('<i class="rg-project-line" data-date="'+esc(finish)+'" style="left:'+str(pos(finish))+'%"></i>')
        out.append('</div><div class="rg-dates">План: '+esc(date_text(group['plan_finish']) if group['plan_finish'] else 'нет даты')+' · Оценка: <b>'+esc(status)+'</b></div></div></article>')
    if not model['groups']:
        out.append('<p>Канонический состав работ для сводного Ганта отсутствует.</p>')
    return ''.join(out)+'</section></div>'


_COMPACT_STYLE = '''<style>
.report-gpr-compact{max-width:100%;overflow-wrap:anywhere}.report-gpr-compact section{margin:16px 0}.report-gpr-compact p{font-size:12px;line-height:1.5;margin:7px 0}.rg-project-date{font-size:23px;color:#245b93}.rg-matrix{width:100%;table-layout:fixed;border-collapse:collapse;font-size:12px}.rg-matrix th,.rg-matrix td{border:1px solid #dce3eb;padding:8px 6px;overflow-wrap:anywhere;text-align:center}.rg-matrix th:first-child{text-align:left;width:34%}.rg-total,.rg-project-total{background:#eef3f8}.rg-axis,.rg-corpus{display:grid;grid-template-columns:minmax(110px,.7fr) minmax(0,2fr);gap:14px}.rg-axis{margin:18px 0 8px;font-size:12px;font-weight:700;break-after:avoid}.rg-years{position:relative;height:25px;min-width:0}.rg-years span{position:absolute;top:0;white-space:nowrap;font-size:12px}.rg-corpus{padding:12px 0;border-bottom:1px solid #dce3eb;break-inside:avoid;page-break-inside:avoid}.rg-corpus b{font-size:13px}.rg-corpus small{display:block;font-size:11px;line-height:1.5;margin-top:4px;color:#526277}.rg-track{position:relative;min-width:0;height:34px;background:#f1f4f8;border:1px solid #dce3eb}.rg-plan,.rg-forecast{position:absolute;height:9px;top:5px}.rg-plan{border:1px dashed #586575}.rg-forecast{top:21px;height:7px;background:#5275a5}.rg-project-line{position:absolute;top:0;bottom:0;border-left:2px dashed #245b93}.rg-dates{font-size:11px;line-height:1.5;margin-top:5px}.rg-dates b{font-size:11px}
@media(max-width:600px){.rg-axis,.rg-corpus{grid-template-columns:minmax(0,1fr);gap:6px}.rg-axis>span{display:none}.rg-matrix{font-size:11px}.rg-matrix th,.rg-matrix td{padding:7px 4px}.rg-matrix th:first-child{width:31%}.rg-years span{font-size:13px}.rg-corpus small,.rg-dates{font-size:12px}.report-gpr-compact p{font-size:13px}}
@media print{.rg-axis,.rg-corpus{grid-template-columns:minmax(100px,.7fr) minmax(0,2fr)}.rg-axis>span{display:block}.rg-years span{font-size:10pt}.rg-matrix{font-size:9pt}.rg-track{-webkit-print-color-adjust:exact;print-color-adjust:exact}.report-gpr-compact section>h3{break-after:avoid}.rg-corpus{break-inside:avoid}}
</style>'''
