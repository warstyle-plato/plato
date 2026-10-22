"""Управленческая сводка по проекту: стройка, деньги стройки, продажи.

Сводка собирается здесь один раз и раздаётся всем поверхностям: сообщению
в Telegram, PDF и странице. Своих расчётов у неё нет — она читает тех,
кто уже отвечает за каждое число:

* физическое выполнение — проценты работ из еженедельного ГПР-факта и
  точечных фактов страницы (`manager._baseline_status`), план — по датам
  утверждённого ГПР (`monitor._plan_progress`);
* бюджет месяца — план из план-факта БДДС против реестра платежей РСС
  (`developaid_monthly_budget`);
* общая информация — записи, введённые руками на странице проекта
  (`developaid_project_notes`);
* продажи — договоры контрактации, план финмодели по месяцам
  (`contracting.fm_plan_by_month`) и квартальный план банка.

Чего нет, то названо причиной: пустой блок не равен нулю.
"""

from __future__ import annotations

import datetime
import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_monthly_budget as monthly_budget
import developaid_legal_cases as legal_cases
import developaid_project_notes as project_notes
import developaid_site_photos as site_photos
import developaid_report_charts as charts
import developaid_report_gantt as report_gantt
from market_search import contracting, sales_store

PERIODS = {"week": "неделю", "month": "месяц"}

_MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
           "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def _date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def period_bounds(kind: str, end: Any) -> dict[str, datetime.date]:
    """Границы периода, который заканчивается днём ``end`` включительно.

    Неделя — семь дней по ``end``; месяц — календарный месяц, в котором
    лежит ``end`` (месячная сводка уходит первого числа за прошлый месяц).
    """
    if kind not in PERIODS:
        raise ValueError(f"неизвестный период сводки: {kind!r}")
    last = _date(end)
    first = (last - datetime.timedelta(days=6) if kind == "week"
             else last.replace(day=1))
    return {"start": first, "end": last,
            "before": first - datetime.timedelta(days=1)}


def previous_bounds(kind: str, bounds: dict[str, datetime.date]) -> dict[str, datetime.date]:
    """Предыдущий период той же длины — для «неделя к неделе», «месяц к месяцу»."""
    return period_bounds(kind, bounds["before"])


def _missing(reason: str) -> dict[str, Any]:
    return {"state": "missing", "reason": reason}


# --------------------------------------------------------------------------
# Стройка: физическое выполнение по ГПР
# --------------------------------------------------------------------------

def _weighted(items: list[tuple[float, float]]) -> float | None:
    total = sum(weight for weight, _ in items)
    if total <= 0:
        return None
    return sum(weight * value for weight, value in items) / total


def _snapshot_day(project: str, upto: datetime.date) -> str:
    path = monitor._latest(project, "schedule_fact", ".xlsx", upto.isoformat())
    return path.stem if path is not None else ""


def _physical_notes(block: dict[str, Any]) -> list[str]:
    """Откуда проценты и чего не хватает — одни слова для сообщения и PDF."""
    source = block.get("source") or {}
    out = [f"Проценты — {source.get('label') or 'из графика работ'}: то же, что "
           "показывает Монитор на эту дату."]
    if not block.get("fact_snapshot"):
        out.append("Недельный ГПР-факт с процентами в Монитор не загружали: выполнение "
                   "взято из утверждённого ГПР и решений, принятых в Мониторе.")
    elif not block.get("fresh"):
        out.append(f"За этот период новый график с процентами не загружали, "
                   f"последний — от {_day(block['fact_snapshot'])}.")
    return out


def _gpr_source(project: str, end: datetime.date, fact_day: str) -> dict[str, Any]:
    """Откуда проценты: тот же набор, что у Монитора (`manager._baseline_status`).

    Утверждённый ГПР, поверх — свежайший ГПР-факт не позднее даты, поверх —
    точечные решения в Мониторе (в том числе «закрыть сомнительные»). Сводка
    называет каждый слой с датой, чтобы число можно было сверить с Монитором.
    """
    meta = monitor._project_dir(project) / "baseline" / "meta.json"
    try:
        baseline_day = str(json.loads(meta.read_text(encoding="utf-8")).get("taken_at") or "")
    except (OSError, ValueError):
        found = monitor._baseline_file(project)
        baseline_day = found.stem if found is not None and found.stem[:1].isdigit() else ""
    folder = monitor._project_dir(project) / "work_fact"
    days = sorted(path.stem.split(".", 1)[0] for path in folder.glob("*.json")) \
        if folder.exists() else []
    days = [day for day in days if day <= end.isoformat()]
    manual = len(monitor.work_facts(project, end.isoformat()))
    label = (f"ГПР-факт от {_day(fact_day)}" if fact_day else
             f"утверждённый ГПР{' от ' + _day(baseline_day) if baseline_day else ''}")
    if manual:
        label += (f" и решения в Мониторе по {manual} "
                  f"{_plural(manual, 'работе', 'работам', 'работам')} (последнее — "
                  f"{_day(days[-1])})")
    return {"baseline": baseline_day or None, "fact": fact_day or None,
            "manual_works": manual, "manual_last": days[-1] if days else None,
            "day": max(filter(None, [fact_day, days[-1] if days else "", baseline_day]),
                       default=""),
            "label": label}


def _dated(baseline: dict[str, Any]) -> list[tuple[str, dict[str, Any], float]]:
    """Работы утверждённого ГПР с датами: (id, работа, вес по длительности)."""
    out = []
    for work in baseline.get("works") or []:
        start, finish = work.get("start"), work.get("finish")
        tid = str(work.get("id") or work.get("wbs") or "").strip()
        if tid and start and finish:
            out.append((tid, work, float(max(1, (finish - start).days))))
    return out


def _progress(works: list[tuple[str, dict[str, Any], float]],
              statuses: dict[str, dict[str, Any]], day: datetime.date) -> dict[str, Any]:
    """Факт и план на день по работам, у которых процент известен."""
    fact, plan, unknown = [], [], 0
    objects: dict[str, dict[str, list[tuple[float, float]]]] = {}
    sections: dict[str, dict[str, list[tuple[float, float]]]] = {}
    each: dict[str, dict[str, Any]] = {}
    for tid, work, weight in works:
        progress = (statuses.get(tid) or {}).get("progress")
        if progress is None:
            unknown += 1
            continue
        planned = monitor._plan_progress(work["start"], work["finish"], day)
        fact.append((weight, progress))
        plan.append((weight, planned))
        each[tid] = {"plan": planned, "fact": progress}
        for groups, key in ((objects, "object"), (sections, "section")):
            group = groups.setdefault(str(work.get(key) or "").strip()
                                      or "Без названия", {"plan": [], "fact": []})
            group["plan"].append((weight, planned))
            group["fact"].append((weight, progress))
    return {"fact": _weighted(fact), "plan": _weighted(plan), "works": len(fact),
            "unknown": unknown, "each": each,
            "objects": [{"object": name, "plan": _weighted(g["plan"]),
                         "fact": _weighted(g["fact"])} for name, g in sorted(objects.items())],
            "sections": {name: {"plan": _weighted(g["plan"]), "fact": _weighted(g["fact"]),
                                "weight": sum(w for w, _ in g["fact"])}
                         for name, g in sections.items()}}


def _breakdown(works: list[tuple[str, dict[str, Any], float]], now: dict[str, Any],
               before: dict[str, Any] | None) -> dict[str, Any]:
    """Разделы ГПР, самые отстающие работы и работы без прироста за период."""
    sections = []
    for name, item in now["sections"].items():
        earlier = ((before or {}).get("sections") or {}).get(name) or {}
        sections.append({"section": name, "plan": item["plan"], "fact": item["fact"],
                         "lag": item["fact"] - item["plan"],
                         "delta": (item["fact"] - earlier["fact"])
                         if earlier.get("fact") is not None else None,
                         "weight": item["weight"]})
    sections.sort(key=lambda row: -row["weight"])
    laggards, stalled = [], []
    for tid, work, _ in works:
        point = now["each"].get(tid)
        if not point:
            continue
        row = {"name": str(work.get("name") or tid), "object": str(work.get("object") or ""),
               "section": str(work.get("section") or ""), "plan": point["plan"],
               "fact": point["fact"], "lag": point["fact"] - point["plan"],
               "finish": work["finish"].isoformat()}
        if row["lag"] < -0.005:
            laggards.append(row)
        earlier = ((before or {}).get("each") or {}).get(tid)
        # Без прироста: работа идёт по плану (план вырос за период), не
        # закончена, а процент тот же, что на начало периода.
        if (earlier and point["fact"] < 0.999 and point["plan"] > earlier["plan"] + 1e-6
                and abs(point["fact"] - earlier["fact"]) < 1e-6):
            stalled.append(row)
    laggards.sort(key=lambda row: row["lag"])
    stalled.sort(key=lambda row: row["lag"])
    return {"sections": sections, "laggards": laggards[:8], "laggards_total": len(laggards),
            "stalled": stalled[:8], "stalled_total": len(stalled),
            "stalled_known": before is not None}


def _plan_curve(works: list[tuple[str, dict[str, Any], float]],
                days: list[datetime.date]) -> list[float | None]:
    return [_weighted([(w, monitor._plan_progress(work["start"], work["finish"], day))
                       for _, work, w in works]) for day in days]


def physical(project: str, kind: str, end: Any) -> dict[str, Any]:
    """Физическое выполнение: факт ГПР на конец и начало периода против плана.

    Процент работы — тот, что прораб ставит в ГПР-факте (или точечный факт со
    страницы). Общий процент — среднее по работам, взвешенное длительностью
    работы по утверждённому ГПР: стоимости у работы в ГПР нет. Отставание —
    факт минус план на ту же дату; его изменение за период — динамика.
    """
    bounds = period_bounds(kind, end)
    try:
        baseline = monitor._read_baseline_gpr(project)
    except FileNotFoundError:
        return _missing("Не загружен утверждённый ГПР проекта.")
    now_day = _snapshot_day(project, bounds["end"])
    source = _gpr_source(project, bounds["end"], now_day)
    works = _dated(baseline)
    now = _progress(works, manager._baseline_status(project, bounds["end"].isoformat()),
                    bounds["end"])
    if not now["works"]:
        return _missing(f"В графике ({source['label']}) нет процентов выполнения "
                        "ни у одной работы.")
    before_day = _snapshot_day(project, bounds["before"])
    before = (_progress(works, manager._baseline_status(project, bounds["before"].isoformat()),
                        bounds["before"]) if before_day else None)
    lag = now["fact"] - now["plan"]
    lag_before = (before["fact"] - before["plan"]
                  if before and before["fact"] is not None else None)
    return {
        "state": "ok",
        # На какой день состояние графика: ГПР-факт или решение в Мониторе.
        "snapshot": source["day"],
        "fact_snapshot": now_day or None,
        "source": source,
        "snapshot_before": before_day or None,
        # Новый ГПР-факт за период не пришёл — прирост ноль не наблюдён,
        # а просто не измерен заново.
        "fresh": bool(now_day) and now_day >= bounds["start"].isoformat(),
        "plan": now["plan"],
        "fact": now["fact"],
        "lag": lag,
        "fact_before": before["fact"] if before else None,
        "plan_before": before["plan"] if before else None,
        "lag_before": lag_before,
        "delta": (now["fact"] - before["fact"]) if before else None,
        "works": now["works"],
        "works_unknown": now["unknown"],
        "objects": now["objects"],
        "breakdown": _breakdown(works, now, before),
        "series": _physical_series(project, works, bounds["end"]),
    }


def _physical_series(project: str, works: list[tuple[str, dict[str, Any], float]],
                     end: datetime.date) -> dict[str, Any]:
    """S-кривая: план по утверждённому ГПР помесячно и факт каждого ГПР-факта."""
    folder = monitor._project_dir(project) / "schedule_fact"
    days = sorted(path.stem for path in folder.glob("*.xlsx")) if folder.exists() else []
    days = [day for day in days if day <= end.isoformat()]
    facts = []
    for day in days:
        moment = _date(day)
        point = _progress(works, manager._baseline_status(project, day), moment)
        facts.append({"day": day, "fact": point["fact"], "plan": point["plan"]})
    first = min(work["start"] for _, work, _ in works)
    last = max(work["finish"] for _, work, _ in works)
    months = []
    cursor = first.replace(day=1)
    while cursor <= last:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    months.append(last)
    return {"plan": [{"day": day.isoformat(), "plan": value}
                     for day, value in zip(months, _plan_curve(works, months))],
            "fact": facts}


# --------------------------------------------------------------------------
# Люди на площадке
# --------------------------------------------------------------------------

def _crew_rows(reports: list[dict[str, Any]], first: datetime.date,
               last: datetime.date) -> list[dict[str, Any]]:
    return [r for r in reports if first.isoformat() <= str(r.get("date") or "") <= last.isoformat()]


def _crew_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    workers = [float((r.get("parsed") or {}).get("workers_total") or 0) for r in rows]
    itr = [float((r.get("parsed") or {}).get("itr_total") or 0) for r in rows]
    return {"days": len(rows),
            "workers_avg": sum(workers) / len(workers) if workers else None,
            "workers_max": max(workers) if workers else None,
            "itr_avg": sum(itr) / len(itr) if itr else None}


def _works_done(rows: list[dict[str, Any]], parties: list[str] | None = None
                ) -> list[dict[str, Any]]:
    """Работы за период из раздела «По работам» ежедневных отчётов бота.

    Строка приписана подрядчику тем же правилом и по тому же списку известных
    подрядчиков, что в карточке Монитора (`daily.attribute_works`,
    `daily.known_parties`). Одна и та же строка в разные дни — одна строка
    с числом дней: прораб пишет «Корпус 1 монолит» каждый день, повтор не
    новая работа.
    """
    import developaid_monitor_daily as daily

    groups: dict[str, dict[str, Any]] = {}
    for report_row in sorted(rows, key=lambda r: str(r.get("date") or "")):
        parsed = report_row.get("parsed") or {}
        known = [c["name"] for c in parsed.get("contractors") or []] + list(parties or [])
        for item in daily.attribute_works(parsed.get("works") or [], known):
            line = str(item.get("line") or "")
            if item.get("named_inline"):
                # Имя подрядчика уже в колонке «Подрядчик» — в строке оно лишнее.
                line = daily._split_inline(line)[-1]
            line = " ".join(line.split()).strip(" ;.")
            if not line:
                continue
            name = item.get("contractor") or "подрядчик не назван"
            group = groups.setdefault(name, {"contractor": name, "lines": {}})
            entry = group["lines"].setdefault(line.lower(), {"line": line, "days": []})
            day = str(report_row.get("date") or "")
            if day not in entry["days"]:
                entry["days"].append(day)
    out = []
    for group in groups.values():
        lines = sorted(group["lines"].values(), key=lambda e: (-len(e["days"]), e["days"][0]))
        out.append({"contractor": group["contractor"], "lines": lines,
                    "days": len({d for e in lines for d in e["days"]})})
    out.sort(key=lambda g: (-g["days"], -len(g["lines"])))
    return out


def crew(project: str, kind: str, end: Any) -> dict[str, Any]:
    """Численность на площадке из ежедневных отчётов, которые приносит бот.

    Тот же разбор, что у карточки «Люди на площадке». День без отчёта —
    пропуск, а не ноль: средняя считается по дням, когда отчёт был.
    Плановой численности в ГПР нет — сравнение «план против факта» не
    выдумывается.
    """
    import developaid_monitor_daily as daily

    bounds = period_bounds(kind, end)
    reports = daily._load_reports(project)
    if not reports:
        return _missing("Ежедневные отчёты со стройки не приходили: чат стройки "
                        "не связан с ботом или отчётов ещё не было.")
    now = _crew_rows(reports, bounds["start"], bounds["end"])
    previous = previous_bounds(kind, bounds)
    before = _crew_rows(reports, previous["start"], previous["end"])
    last = max((str(r.get("date") or "") for r in reports
                if str(r.get("date") or "") <= bounds["end"].isoformat()), default="")
    contractors: dict[str, dict[str, float]] = {}
    for report_row in now:
        for item in (report_row.get("parsed") or {}).get("contractors") or []:
            block = contractors.setdefault(item.get("name") or "без имени",
                                           {"workers": 0.0, "itr": 0.0, "days": 0})
            block["workers"] += float(item.get("workers") or 0)
            block["itr"] += float(item.get("itr") or 0)
            block["days"] += 1
    by_contractor = sorted(
        ({"name": name, "workers_avg": b["workers"] / b["days"], "itr_avg": b["itr"] / b["days"],
          "days": b["days"]} for name, b in contractors.items()),
        key=lambda row: -row["workers_avg"])
    window = 31 if kind == "month" else 28
    days = [bounds["end"] - datetime.timedelta(days=n) for n in range(window - 1, -1, -1)]
    by_day = {str(r.get("date")): r for r in reports}
    series = [{"day": day.isoformat(),
               "workers": (float((by_day[day.isoformat()].get("parsed") or {})
                                 .get("workers_total") or 0)
                           if day.isoformat() in by_day else None)} for day in days]
    return {"state": "ok", "now": _crew_stats(now), "previous": _crew_stats(before),
            "period_days": (bounds["end"] - bounds["start"]).days + 1,
            "last_report": last or None, "by_contractor": by_contractor[:10],
            "series": series,
            "works": _works_done(now, daily.known_parties(project, bounds["end"]))}


# --------------------------------------------------------------------------
# Деньги стройки: бюджет месяца
# --------------------------------------------------------------------------

def budget(project: str, kind: str, end: Any) -> dict[str, Any]:
    """План месяца из план-факта БДДС против оплат по РСС: стройка и коммерция.

    Месяц — тот, в котором кончается период. Карта строк и кодов РСС живёт в
    `developaid_monthly_budget`.
    """
    return monthly_budget.month_budget(project, period_bounds(kind, end)["end"])


# --------------------------------------------------------------------------
# Финансирование
# --------------------------------------------------------------------------

def _borrowed(source: Any) -> bool:
    return actuals.borrowed(source)


def _borrowed_rows(rss: Path, chapters: Any):
    """Платежи кредитом; с главами — только по этим главам РСС (их признак — Монитора)."""
    if not chapters:
        return lambda row: _borrowed(row.get("source"))
    import developaid_monitor_dashboard as dashboard

    inside = dashboard.payment_in_chapters(actuals.read_estimate(rss), chapters)
    return lambda row: _borrowed(row.get("source")) and inside(row)


def _sums(rows: list[dict[str, Any]], bounds: dict[str, datetime.date],
          keep) -> dict[str, float]:
    """За период, с начала месяца конца периода и с начала проекта."""
    month_start = bounds["end"].replace(day=1)
    out = {"period": 0.0, "month": 0.0, "total": 0.0}
    for row in rows:
        day = row.get("date")
        if not day or day > bounds["end"] or not keep(row):
            continue
        amount = float(row.get("amount") or 0.0)
        out["total"] += amount
        if day >= month_start:
            out["month"] += amount
        if day >= bounds["start"]:
            out["period"] += amount
    return out


def _monitor_view(project: str, end: datetime.date) -> dict[str, Any]:
    """Срез Монитора на конец периода — со всеми слоями, как на его странице."""
    import developaid_monitor_page  # noqa: F401 — ставит слои среза, как на странице

    return monitor.build(project, cut=end.isoformat(), upto=end.isoformat())


def _monitor_dashboard(project: str, end: datetime.date) -> dict[str, Any]:
    """Панель Монитора на конец периода: срок, финансирование — его расчётом."""
    return _monitor_view(project, end).get("dashboard") or {}


def _monitor_funding(project: str, end: datetime.date) -> dict[str, Any]:
    """Финансирование стройки так, как его считает панель Монитора."""
    return (_monitor_dashboard(project, end).get("funding")) or {
        "known": False, "reason": "панель Монитора не собрала финансирование"}


def _credit_parts(sales_project: str, data_dir: Path | None) -> tuple[list, Any]:
    kept = sales_store.load(data_dir or sales_store.default_dir(), sales_project)
    sources = kept.get("sources") or {}
    contracts = ((sources.get("contracting") or {}).get("data")) or {}
    credit = ((sources.get("credit") or {}).get("data")) or None
    return contracts.get("rows") or [], credit


def _escrow(sales_project: str, data_dir: Path | None) -> dict[str, Any]:
    if not str(sales_project or "").strip():
        return _missing("Проект не связан с отчётом о продажах — эскроу и план "
                        "кредита взять неоткуда.")
    rows, credit = _credit_parts(sales_project, data_dir)
    got = contracting.escrow_sufficiency({}, rows, credit)
    if got.get("missing"):
        return _missing("Эскроу: " + "; ".join(got["missing"]) + ".")
    plan_escrow: dict[str, float] = {}
    plan_pf: dict[str, float] = {}
    for queue in (credit or {}).get("queues") or []:
        for month, value in (queue.get("escrow") or {}).items():
            plan_escrow[month] = plan_escrow.get(month, 0.0) + float(value or 0.0)
        for month, value in (queue.get("pf") or {}).items():
            plan_pf[month] = plan_pf.get(month, 0.0) + float(value or 0.0)
    return {"state": "ok", "queues": got.get("queues") or [],
            "partial_month": got.get("partial_month"),
            # Помесячно: план эскроу и остатка кредита (нарастающим, сумма
            # очередей) и поступления на эскроу по договорам.
            "plan_escrow": plan_escrow, "plan_pf": plan_pf,
            "actual_escrow": contracting.escrow_actual(rows)}


def _quarter_end(quarter: str) -> str:
    """«2026 Q3» → «2026-09»: месяц, на конец которого банк ставит остаток."""
    year, part = quarter.split(" Q")
    return f"{year}-{int(part) * 3:02d}"


def _bank_escrow(sales_project: str, data_dir: Path | None,
                 end: datetime.date) -> dict[str, Any]:
    """Эскроу против плана банка: на конец закрытого квартала и на сейчас.

    План — строка «…(утверждено по CF)» листа плана банка, нарастающим по
    кварталам; факт — поступления на эскроу по графикам договоров, тоже
    нарастающим. План финмодели (лист «КРЕДИТЫ») — другой документ, и под
    словом «план банка» он не показывается.
    """
    if not str(sales_project or "").strip():
        return _missing("Проект не связан с отчётом о продажах — плана банка нет.")
    kept = sales_store.load(data_dir or sales_store.default_dir(), sales_project)
    sources = kept.get("sources") or {}
    bank = ((sources.get("bank_plan") or {}).get("data")) or None
    if not bank:
        return _missing("План банка не загружен: в книге проекта нужен лист "
                        + " или ".join(f"«{name}»" for name in contracting.BANK_SHEETS) + ".")
    plan = contracting.bank_escrow_plan(bank)
    if not plan:
        return _missing(f"В плане банка (лист «{bank.get('sheet') or ''}») нет строки "
                        f"«{contracting.BANK_ESCROW_LABEL}».")
    contracts = ((sources.get("contracting") or {}).get("data")) or {}
    inflow = contracting.escrow_actual(contracts.get("rows") or [])
    month = end.strftime("%Y-%m")

    def accumulated(upto: str) -> float:
        return sum(value for key, value in inflow.items() if key <= upto)

    closed = [q for q in sorted(plan, key=_quarter_end) if _quarter_end(q) < month]
    current = next((q for q in sorted(plan, key=_quarter_end) if _quarter_end(q) >= month), None)
    out: dict[str, Any] = {"state": "ok", "sheet": bank.get("sheet") or "", "plan": plan}
    if closed:
        last = closed[-1]
        actual = accumulated(_quarter_end(last))
        out["closed"] = {"quarter": last, "plan": plan[last], "actual": actual,
                         "gap": actual - plan[last]}
    if current:
        out["current"] = {"quarter": current, "plan": plan[current],
                          "actual": accumulated(month), "measured_at": month}
    return out


def funding(project: str, kind: str, end: Any, sales_project: str = "",
            data_dir: Path | None = None,
            dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    """Финансирование: лимит банка и дефицит, выборка кредита, проценты, эскроу.

    Выборка — платежи РСС из заёмных средств (кредит банк перечисляет сразу
    подрядчикам); проценты — статья 3.5 РСС «Услуги банка». Лимит, остаток и
    дефицит — тот же расчёт, что в карточке финансирования Монитора. Эскроу и
    план кредита — из отчёта о продажах (лист «КРЕДИТЫ» финмодели).
    """
    bounds = period_bounds(kind, end)
    rss = monitor._latest(project, "estimate", ".xlsx", bounds["end"].isoformat())
    if rss is None:
        return _missing("Не загружен ни один отчёт РСС с реестром платежей "
                        f"на {bounds['end']:%d.%m.%Y}.")
    payments = actuals.read_payments(rss)["rows"]
    previous = previous_bounds(kind, bounds)
    if dashboard is not None:
        limit = dashboard.get("funding") or {
            "known": False, "reason": dashboard.get("error")
            or "панель Монитора не собрала финансирование"}
    else:
        try:
            limit = _monitor_funding(project, bounds["end"])
        except Exception as exc:  # noqa: BLE001 — причина уходит в сводку
            limit = {"known": False, "reason": f"{type(exc).__name__}: {exc}"}
    # Выборка — по тем же главам РСС, что лимит Монитора (владелец,
    # 22.10.2026: «лимит 4,64, выбрано 4,80, остаток 1,00 — так не
    # сходится»). Лимит не посчитан — все главы, как раньше.
    keep = _borrowed_rows(rss, limit.get("chapters") if limit.get("known") else None)
    monthly: dict[str, float] = {}
    for row in payments:
        day = row.get("date")
        if day and day <= bounds["end"] and keep(row):
            key = day.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0.0) + float(row.get("amount") or 0.0)
    out: dict[str, Any] = {
        "state": "ok", "rss": rss.stem,
        "draws": _sums(payments, bounds, keep),
        "draws_previous": _sums(payments, previous, keep)["period"],
        "draws_monthly": monthly,
        "interest": _sums(payments, bounds, lambda row: monthly_budget._under(
            str(row.get("estimate_code") or "").rstrip("."), "3.5")),
        "limit": limit,
    }
    out["escrow"] = _escrow(sales_project, data_dir)
    out["escrow_bank"] = _bank_escrow(sales_project, data_dir, bounds["end"])
    escrow = out["escrow"]
    if escrow.get("state") == "ok":
        month = bounds["end"].strftime("%Y-%m")
        actual = escrow.get("actual_escrow") or {}
        escrow["inflow_month"] = actual.get(month)
        escrow["inflow_total"] = sum(v for m, v in actual.items() if m <= month)
    return out


# --------------------------------------------------------------------------
# Продажи
# --------------------------------------------------------------------------

def _signed(row: dict[str, Any]) -> datetime.date | None:
    try:
        return _date(row["signed"]) if row.get("signed") else None
    except ValueError:
        return None


def _fact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = contracting._totals(rows)
    flats = contracting._totals(
        [row for row in rows
         if contracting.product_name(row["product"]) == "Квартира"])
    # Метры — только у товаров, которые продаются метром (квартиры, помещения).
    # Машиноместа и кладовые продаются штукой: их деньги в сумме, а метры в
    # «площади» смешали бы паркинг с жильём, и общая строка не сходилась бы ни
    # с одним планом (финансист, 21.10.2026: «сумма учитывает машиноместа, а
    # площадь машиномест не учитывается»). Штуки названы рядом.
    measured = [row for row in rows if contracting.product_measure(
        contracting.product_name(row["product"])) == "area"]
    pieces: dict[str, float] = {}
    for row in rows:
        name = contracting.product_name(row["product"])
        if contracting.product_measure(name) == "units":
            pieces[name] = pieces.get(name, 0.0) + float(row.get("units") or 1.0)
    return {"contracts": int(totals["contracts"]), "units": totals["units"],
            "area": sum(float(row["area"] or 0.0) for row in measured),
            "amount": totals["amount"],
            "area_unknown": sum(1 for row in measured if not row["area"]),
            "pieces": pieces,
            # Цена — по квартирам: банк и финмодель называют её так же, а
            # общая цена метра смешала бы паркинг с жильём.
            "price_flats": flats["price_per_sqm"] or None}


def sales(sales_project: str, kind: str, end: Any,
          data_dir: Path | None = None) -> dict[str, Any]:
    """Продажи за период и с начала квартала против плана ФМ и банка."""
    if not str(sales_project or "").strip():
        return _missing("Проект не связан с отчётом о продажах: выберите его "
                        "на странице «Сводка руководству».")
    bounds = period_bounds(kind, end)
    kept = sales_store.load(data_dir or sales_store.default_dir(), sales_project)
    sources = kept.get("sources") or {}

    def part(name: str) -> Any:
        return ((sources.get(name) or {}).get("data")) or None

    contracts = part("contracting")
    if not contracts:
        return _missing(f"В отчёте о продажах проекта «{sales_project}» "
                        "не загружена контрактация.")
    rows = contracts.get("rows") or []
    dated = [(row, _signed(row)) for row in rows]
    undated = sum(1 for _, day in dated if day is None)

    def between(first: datetime.date, last: datetime.date | None = None) -> list[dict[str, Any]]:
        last = last or bounds["end"]
        return [row for row, day in dated
                if day is not None and first <= day <= last]

    previous = previous_bounds(kind, bounds)

    month_start = bounds["end"].replace(day=1)
    quarter_start = month_start.replace(month=(month_start.month - 1) // 3 * 3 + 1)
    month_key = month_start.strftime("%Y-%m")
    quarter = contracting.quarter_of(month_key)

    fm = contracting.fm_plan_by_month(part("fm_plan"))
    fm_month = fm.get(month_key)
    fm_quarter_months = [values for month, values in fm.items()
                         if contracting.quarter_of(month) == quarter]
    fm_quarter = ({"amount": sum(v["amount"] for v in fm_quarter_months),
                   "area": sum(v["area"] for v in fm_quarter_months)}
                  if fm_quarter_months else None)

    bank = part("bank_plan") or {}
    bank_quarter = None
    bank_reason = ""
    # Ряд «факт против планов» нарастающим итогом — тот же, что рисует отчёт
    # о продажах: один счёт кварталов и остатка банка на дату его плана.
    summary = contracting.summarise(contracts, part("ledger") or {})
    comparison = contracting.plan_comparison(
        dict(summary, fm_plan=part("fm_plan"), bank_plan=bank or None))
    opening = comparison.get("bank_opening") or {}
    if not bank:
        bank_reason = "План банка не загружен."
    elif quarter in (bank.get("gross_by_quarter") or {}):
        if opening.get("quarter") == quarter:
            bank_reason = ("В первом квартале плана банка лежат продажи с начала "
                           "проекта — с кварталом его сравнивать нельзя.")
        else:
            bank_quarter = {
                "amount": float(bank["gross_by_quarter"][quarter]),
                "area": (bank.get("area_by_quarter") or {}).get(quarter),
                "price": (bank.get("price_by_quarter") or {}).get(quarter)}
    else:
        bank_reason = f"В плане банка нет квартала {quarter}."

    uploaded = (sources.get("contracting") or {}).get("at") or ""
    return {
        "state": "ok",
        "project": kept.get("project") or sales_project,
        "uploaded": uploaded or None,
        # Договоры, подписанные после загрузки контрактации, сводке не видны.
        "stale": bool(uploaded) and uploaded[:10] < bounds["end"].isoformat(),
        "undated": undated,
        "period": _fact(between(bounds["start"])),
        "previous": _fact(between(previous["start"], previous["end"])),
        "products": _by_product(between(bounds["start"]), between(datetime.date(1900, 1, 1)),
                                part("fm_plan"), quarter),
        "pace": [{"month": m["month"], "area": m.get("area"), "amount": m.get("amount"),
                  "units": m.get("units"), "price_flats": m.get("price_flats")}
                 for m in summary.get("dynamics") or [] if m["month"] <= month_key][-12:],
        "payments": [{"name": item["name"], "count": item["count"], "amount": item["amount"],
                      "area": item["area"]} for item in summary.get("by_payment") or []],
        "pool": _pool(contracting.pool_progress(summary, rows, part("fm_plan"), part("pool"))),
        "series": [{"label": q["label"],
                    "fact": q.get("fact_amount_cum"), "fm": q.get("fm_amount_cum"),
                    "bank": q.get("bank_amount_cum"),
                    "fact_area": q.get("fact_area_cum"), "fm_area": q.get("fm_area_cum"),
                    "bank_area": q.get("bank_area_cum"), "partial": q.get("partial")}
                   for q in comparison.get("quarters") or []],
        "month": {"key": month_key, "fact": _fact(between(month_start)),
                  "fm": fm_month},
        "quarter": {"key": quarter, "fact": _fact(between(quarter_start)),
                    "fm": fm_quarter, "bank": bank_quarter,
                    "bank_reason": bank_reason or None},
    }


def _by_product(period: list[dict[str, Any]], total: list[dict[str, Any]],
                fm: dict[str, Any] | None, quarter: str) -> list[dict[str, Any]]:
    """По типам (как их называет отчёт о продажах): период, с начала, план ФМ квартала."""
    out: dict[str, dict[str, Any]] = {}
    for scope, rows in (("period", period), ("total", total)):
        for row in rows:
            name = contracting.product_name(row["product"])
            item = out.setdefault(name, {"product": name,
                                         "measure": contracting.product_measure(name)})
            block = item.setdefault(scope, {"units": 0.0, "area": 0.0, "amount": 0.0})
            block["units"] += float(row.get("units") or 0.0)
            block["area"] += float(row.get("area") or 0.0)
            block["amount"] += float(row.get("amount") or 0.0)
    plans = (fm or {}).get("plan") or {}
    for name, item in out.items():
        for scope in ("period", "total"):
            block = item.setdefault(scope, {"units": 0.0, "area": 0.0, "amount": 0.0})
            divisor = block["units"] if item["measure"] == "units" else block["area"]
            block["price"] = block["amount"] / divisor if divisor else None
        months = [v for m, v in (plans.get(name) or {}).items()
                  if contracting.quarter_of(m) == quarter]
        item["fm_quarter"] = ({"amount": sum(float(v.get("amount") or 0.0) for v in months),
                               "area": sum(float(v.get("area") or 0.0) for v in months),
                               "units": sum(float(v.get("units") or 0.0) for v in months)}
                              if months else None)
    return sorted(out.values(), key=lambda item: -item["total"]["amount"])


def _pool(got: dict[str, Any]) -> dict[str, Any]:
    """Остаток нераспроданного по продуктам — из счёта отчёта о продажах."""
    products = [{"product": p["product"], "sold_units": p["sold_units"],
                 "pool_units": p["pool_units"], "sold_area": p["sold_area"],
                 "pool_area": p["pool_area"], "area_share": p["area_share"]}
                for p in got.get("products") or [] if p.get("pool_area") or p.get("pool_units")]
    return {"products": products, "total": got.get("total") or {},
            "missing": got.get("missing") or []}


# --------------------------------------------------------------------------
# Сводка целиком
# --------------------------------------------------------------------------

def schedule(dashboard: dict[str, Any]) -> dict[str, Any]:
    """Срок ввода: утверждённый и прогноз Монитора по темпу (его расчёт)."""
    if dashboard.get("error"):
        return _missing(f"Прогноз срока не посчитан: {dashboard['error']}")
    block = dashboard.get("schedule") or {}
    if not block.get("approved_finish") and not block.get("forecast_finish"):
        return _missing("Прогноз срока не посчитан: нет утверждённого срока и прогноза.")
    return {"state": "ok", "approved": block.get("approved_finish"),
            "forecast": block.get("forecast_finish"),
            "known": block.get("forecast_known", True),
            "source": block.get("forecast_source") or "",
            "delay_days": block.get("rnv_delay_days"),
            "stalled": list(block.get("stalled") or [])}


def _stalled_words(block: dict[str, Any]) -> str:
    """Работы, которые почти стоят: прогноз ввода их не учитывает (Монитор)."""
    items = block.get("stalled") or []
    if not items:
        return ""
    shown = ", ".join(f"«{item['name']}»" + (f" ({item['object']})" if item.get("object") else "")
                      for item in items[:3])
    more = len(items) - 3
    return (f"Прогноз не учитывает {len(items)} "
            f"{_plural(len(items), 'работу', 'работы', 'работ')}, которые почти стоят: "
            f"актов по ним так мало, что при нынешнем темпе они растянулись бы на годы, "
            f"и такой темп не продлевается в будущее — {shown}"
            + (f" и ещё {more}" if more > 0 else "") + ".")


def gantt(view: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any]:
    """Сроки работ по корпусам — из дерева графика Монитора (`report_gantt`)."""
    if dashboard.get("error"):
        return _missing(f"Монитор не собрал срез: {dashboard['error']}")
    return report_gantt.model((view.get("schedule") or {}).get("management") or [])


# --------------------------------------------------------------------------
# Связь проекта Монитора с проектом отчёта о продажах
# --------------------------------------------------------------------------
#
# Склады разные и имена в них разные («Гродненская» в Мониторе, «ЖК
# Гродненская» в отчёте о продажах), поэтому связь — явная запись, сделанная
# человеком один раз, а не догадка по имени. Лежит на сервере в каталоге
# проекта Монитора: её читают страница, PDF и рассылка, у всех одна.

_SALES_LINK = "sales_link.json"


def sales_projects(data_dir: Path | None = None) -> list[str]:
    """Проекты, по которым загружен отчёт о продажах."""
    return [item["project"] for item in sales_store.projects(data_dir or sales_store.default_dir())
            if str(item.get("project") or "").strip()]


def sales_link(project: str) -> dict[str, Any] | None:
    """Связь с отчётом о продажах; ``None`` — её ещё не задавали.

    Пустое ``sales_project`` в записи — решение «продаж в сводке нет», а не
    отсутствие решения.
    """
    place = monitor._project_dir(project) / _SALES_LINK
    if not place.exists():
        return None
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(got, dict) or not isinstance(got.get("sales_project"), str):
        return None
    return got


def link_sales(project: str, sales_project: str, author: str,
               data_dir: Path | None = None) -> dict[str, Any]:
    """Запомнить, какой проект отчёта о продажах у проекта Монитора."""
    name = str(sales_project or "").strip()
    if name and name not in sales_projects(data_dir):
        raise ValueError(f"В отчёте о продажах нет проекта «{name}».")
    record = {"sales_project": name, "by": author,
              "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    folder = monitor._project_dir(project)
    # Два воркера: запись через временный файл и замену, читатель видит
    # либо старую связь, либо новую, но не половину файла.
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".sales_link.", suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(record, out, ensure_ascii=False)
    os.replace(tmp, folder / _SALES_LINK)
    return record


def build(project: str, kind: str, end: Any, sales_project: str | None = None,
          sales_dir: Path | None = None) -> dict[str, Any]:
    """Сводка за неделю или месяц по проекту мониторинга ``project``.

    ``sales_project`` не передан — берётся сохранённая связь проекта.
    """
    bounds = period_bounds(kind, end)
    declined = False
    if sales_project is None:
        link = sales_link(project)
        sales_project = (link or {}).get("sales_project") or ""
        declined = link is not None and not sales_project
    blocks: dict[str, Any] = {}
    # Срез Монитора — один расчёт на всю сводку: срок, график по корпусам и
    # финансирование.
    try:
        view = _monitor_view(project, bounds["end"])
        dashboard = view.get("dashboard") or {}
    except Exception as exc:  # noqa: BLE001 — причина уходит в сводку
        view = {}
        dashboard = {"error": f"{type(exc).__name__}: {exc}"}
    for name, collect in (
            ("physical", lambda: physical(project, kind, bounds["end"])),
            ("crew", lambda: crew(project, kind, bounds["end"])),
            ("schedule", lambda: schedule(dashboard)),
            ("gantt", lambda: gantt(view, dashboard)),
            ("budget", lambda: budget(project, kind, bounds["end"])),
            ("sales", lambda: sales(sales_project, kind, bounds["end"], sales_dir)),
            ("funding", lambda: funding(project, kind, bounds["end"], sales_project,
                                        sales_dir, dashboard)),
            ("legal", lambda: dict(legal_cases.for_report(
                project, bounds["start"], bounds["end"]), state="ok")),
            ("notes", lambda: dict(project_notes.for_period(
                project, bounds["start"], bounds["end"]), state="ok")),
            ("photos", lambda: dict(site_photos.for_report(
                project, bounds["start"], bounds["end"]), state="ok"))):
        try:
            blocks[name] = collect()
        except Exception as exc:  # noqa: BLE001
            # Сломанный файл одного блока не должен гасить всю сводку, но
            # причина должна дойти до читателя, а не остаться в логе.
            blocks[name] = _missing(
                f"Блок не собран: {type(exc).__name__}: {exc}")
    if declined:
        blocks["sales"] = _missing("Продажи в сводку не входят: так выбрано на "
                                   "странице «Сводка руководству».")
    blocks["findings"] = findings({"kind": kind, "end": bounds["end"].isoformat(), **blocks})
    return {"project": project, "kind": kind,
            "start": bounds["start"].isoformat(),
            "end": bounds["end"].isoformat(), **blocks}


# --------------------------------------------------------------------------
# Главное за период
# --------------------------------------------------------------------------

def _share(part: float | None, whole: float | None) -> float | None:
    return part / whole if part is not None and whole else None


def findings(report: dict[str, Any]) -> list[dict[str, str]]:
    """Выводы для первой страницы — из посчитанных блоков, с числом и источником.

    Ничего нового здесь не считается: только сравнение того, что уже есть в
    блоках. Нет данных — вывод говорит, чего нет.
    """
    out: list[dict[str, str]] = []
    period = PERIODS[report["kind"]]

    def add(topic: str, text: str, source: str, tone: str = "") -> None:
        out.append({"topic": topic, "text": text, "source": source, "tone": tone})

    block = report.get("physical") or {}
    if block.get("state") == "ok":
        lag = block["lag"]
        text = _sentence(f"Выполнено {_pct(block['fact'])} работ по графику при плане "
                         f"{_pct(block['plan'])} — " + (f"отставание {_pp(-lag)[1:]}" if lag < 0
                                                       else f"опережение {_pp(lag)[1:]}"))
        if block.get("lag_before") is not None:
            change = lag - block["lag_before"]
            if abs(change) < 0.0005:
                text += f" За {period} отставание не изменилось."
            else:
                text += _sentence(f" За {period} отставание "
                                  f"{'сократилось' if change > 0 else 'выросло'} на "
                                  f"{_pp(abs(change))[1:]}")
        add("Стройка", text, block["source"]["label"],
            "bad" if lag < -0.02 else "")
    else:
        add("Стройка", block.get("reason") or "Данных нет.", "", "missing")

    stroika = report.get("physical") or {}
    block = report.get("crew") or {}
    if block.get("state") == "ok":
        now, before = block["now"], block["previous"]
        if now["days"]:
            text = (f"В среднем {now['workers_avg']:.0f} рабочих и {now['itr_avg']:.0f} ИТР в день, "
                    f"максимум {now['workers_max']:.0f} — по {now['days']} "
                    f"{_plural(now['days'], 'отчёту', 'отчётам', 'отчётам')} из "
                    f"{block['period_days']} дней периода")
            tone = ""
            if before["days"] and before["workers_avg"]:
                change = now["workers_avg"] / before["workers_avg"] - 1
                text += (f"; в предыдущий такой же период — {before['workers_avg']:.0f} "
                         f"({'+' if change >= 0 else '−'}{abs(change) * 100:.0f}%)")
                worse = (stroika.get("lag_before") is not None
                         and stroika["lag"] < stroika["lag_before"])
                if change < -0.05 and worse:
                    text += ". Людей стало меньше, а отставание выросло — под нужный темп их не хватает"
                    tone = "bad"
            add("Люди на площадке", _sentence(text),
                "ежедневные отчёты со стройки (бот)", tone)
        else:
            add("Люди на площадке",
                f"За период ни одного отчёта со стройки; последний — от "
                f"{_day(block.get('last_report'))}.", "ежедневные отчёты со стройки (бот)",
                "missing")
    elif block.get("reason"):
        add("Люди на площадке", block["reason"], "", "missing")
    breakdown = stroika.get("breakdown") or {}
    if breakdown.get("laggards"):
        worst = "; ".join(f"{row['name']}{(' (' + row['object'] + ')') if row['object'] else ''} — "
                          f"{_pp(-row['lag'])[1:]}" for row in breakdown["laggards"][:3])
        text = f"Больше всего отстают: {worst}"
        if breakdown.get("stalled_total"):
            text += (f". Без прироста за {period} при идущем плане — "
                     f"{breakdown['stalled_total']} "
                     f"{_plural(breakdown['stalled_total'], 'работа', 'работы', 'работ')}")
        add("Отстающие работы", _sentence(text), stroika["source"]["label"],
            "bad")

    block = report.get("schedule") or {}
    if block.get("state") == "ok" and block.get("forecast"):
        delay = block.get("delay_days")
        late = isinstance(delay, (int, float)) and delay > 0
        if block.get("approved"):
            text = (f"Ввод по утверждённому графику — {_day(block['approved'])}, "
                    f"прогноз при нынешнем темпе — {_day(block['forecast'])}")
            text += f": на {delay:.0f} дн. позже." if late else ": в срок."
        else:
            text = (f"Прогноз ввода при нынешнем темпе — {_day(block['forecast'])}; "
                    "утверждённого срока ввода в данных Монитора нет, сравнить не с чем.")
        if block.get("stalled"):
            text += " " + _stalled_words(block)
        add("Срок", text, "прогноз Монитора по темпу работ",
            "bad" if late else "")
    elif block.get("reason"):
        add("Срок", block["reason"], "", "missing")
    late = [corpus for corpus in (report.get("gantt") or {}).get("corpora") or []
            if (corpus.get("delta_days") or 0) > 0]
    if late:
        worst = max(late, key=lambda corpus: corpus["delta_days"])
        when = ("по работам с известным темпом" if worst.get("forecast_partial")
                else f"работы по прогнозу закончатся {_day(worst['forecast_finish'])}")
        add("Корпуса", f"Сильнее всех опаздывает {worst['name']}: {when} — на "
            f"{worst['delta_days']} дн. позже утверждённого графика"
            + (f"; всего с опозданием {len(late)} "
               f"{_plural(len(late), 'корпус', 'корпуса', 'корпусов')}." if len(late) > 1 else "."),
            "график Монитора по корпусам, прогноз по темпу", "bad")

    block = report.get("budget") or {}
    if block.get("state") in {"ok", "partial"}:
        month = _date(block["month"])
        end = _date(report["end"])
        days = ((month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
                - month).days
        elapsed = min(1.0, (end - month).days / days + 1 / days) if end >= month else 0.0
        parts = []
        table = block.get("by_budget_article") or {}
        total = table.get("total") or {}
        if total.get("plan"):
            # Итог и статьи — из той же таблицы, что в документе.
            parts.append(f"по стройке и коммерческим расходам оплачено {_rub(total['fact'])} "
                         f"из {_rub(total['plan'])} ({_pct(total['share'])}), "
                         f"осталось {_rub(total['remaining'])}")
            for chapter in table["chapters"]:
                line = chapter["total"]
                if (chapter["key"] != "service" and line.get("plan")
                        and line.get("fact") is not None):
                    parts.append(f"{chapter['label'].lower()} — оплачено {_rub(line['fact'])} "
                                 f"из {_rub(line['plan'])} ({_pct(line['share'])})")
            rows = {row["key"]: row for chapter in table["chapters"] for row in chapter["rows"]}
            over = [rows[key] for key in table.get("overrun") or []]
            if over:
                parts.append("перерасход: " + ", ".join(
                    f"«{row['label']}» на {_rub(-row['remaining'])}" for row in over[:3]))
            left = rows.get(table.get("largest_left") or "")
            if left:
                parts.append(f"больше всего не оплачено по статье «{left['label']}» — "
                             f"{_rub(left['remaining'])} из {_rub(left['plan'])}")
            loose = [row for chapter in table["chapters"] for row in chapter["rows"]
                     if row["key"] == "unplanned" and chapter["key"] != "service"]
            if loose:
                parts.append(f"без плана в бюджете оплачено {_rub(sum(r['fact'] for r in loose))}")
        forecast = _budget_forecast(block, end)
        build = next((row for row in forecast if row["label"].startswith("Стройка")), None)
        if build:
            parts.append(f"по нынешнему темпу к концу месяца стройке оплатят около "
                         f"{_rub(build['forecast'])} — "
                         + (f"на {_rub(build['gap'])} больше плана" if build["gap"] > 0
                            else f"на {_rub(-build['gap'])} меньше плана"))
        if parts:
            text = "; ".join(parts)
            add("Бюджет месяца", text[:1].upper() + text[1:]
                + f". Прошло {_pct(elapsed)} месяца.",
                f"план-факт БДДС от {_day(block.get('budget_file'))}, РСС от {_day(block['rss'])}",
                "bad" if (table.get("overrun") or (total.get("share") is not None
                                                   and total["share"] > elapsed + 0.1)) else "")
        else:
            add("Бюджет месяца", block.get("reason") or "Плана на месяц нет.",
                f"РСС от {_day(block['rss'])}", "missing")
    else:
        add("Бюджет месяца", block.get("reason") or "Данных нет.", "", "missing")

    block = report.get("sales") or {}
    if block.get("state") == "ok":
        quarter = block["quarter"]
        fact = quarter["fact"]
        pieces = [f"С начала квартала продано {fact['contracts']} "
                  f"{_plural(fact['contracts'], 'договор', 'договора', 'договоров')} на "
                  f"{_rub(fact['amount'])}, {_area(fact['area'])}"]
        for name, plan in (("финмодели", quarter.get("fm")), ("банка", quarter.get("bank"))):
            if plan and plan.get("amount"):
                gap = fact["amount"] - plan["amount"]
                piece = (f"план {name} выполнен на {_pct(_share(fact['amount'], plan['amount']))} "
                         f"({'больше' if gap >= 0 else 'меньше'} на {_rub(abs(gap))}")
                if plan.get("area"):
                    piece += f", {_area(abs(fact['area'] - plan['area']))}"
                pieces.append(piece + ")")
        text = "; ".join(pieces) + "."
        previous = block.get("previous") or {}
        text += (f" За {period} — {_rub(block['period']['amount'])}, "
                 f"за предыдущий такой же период — {_rub(previous.get('amount'))}.")
        pace = [p for p in block.get("pace") or [] if p.get("area")]
        if len(pace) >= 4:
            last, before = pace[-2], pace[-5:-2]
            average = sum(p["area"] for p in before) / len(before)
            if average:
                change = last["area"] / average - 1
                text += (f" Темп за {_months_label(last['month'])} — {_area(last['area'])}, "
                         f"{'выше' if change >= 0 else 'ниже'} среднего трёх месяцев до него "
                         f"на {abs(change) * 100:.0f}%.")
        pool = (block.get("pool") or {}).get("total") or {}
        if pool.get("pool_area"):
            text += (f" Продано {_pct(pool.get('area_share'))} площади, осталось "
                     f"{_area(pool['pool_area'] - pool['sold_area'])}.")
        add("Продажи", text, f"контрактация от {_day(block.get('uploaded'))}, планы ФМ и банка",
            "bad" if quarter.get("fm") and fact["amount"] < quarter["fm"]["amount"] else "")
    else:
        add("Продажи", block.get("reason") or "Данных нет.", "", "missing")

    block = report.get("funding") or {}
    if block.get("state") == "ok":
        limit = block.get("limit") or {}
        pieces = []
        if limit.get("known"):
            need = _approved_need(limit)
            if need and need["deficit"] is not None:
                pieces.append(f"по утверждённому бюджету {_rub(need['approved'])} не хватает "
                              f"на достройку {_rub(need['deficit'])}"
                              if need["deficit"] > 0 else
                              f"утверждённый бюджет {_rub(need['approved'])} покрыт лимитами и резервом")
            extra = float(limit.get("additional_financing") or 0.0)
            pieces.append(f"по РСС не хватает {_rub(extra)} "
                          f"{_since(limit.get('additional_financing_from'))}"
                          if extra > 0 else "по РСС лимитов и резерва хватает до ввода")
        pieces.append(f"выборка кредита за {period} — {_rub(block['draws']['period'])} "
                      f"(за предыдущий такой же период — {_rub(block.get('draws_previous'))})")
        escrow = block.get("escrow") or {}
        for queue in (escrow.get("queues") or [])[:2]:
            if queue.get("plan_coverage_at") is not None:
                pace_cover = queue.get("keeping_pace_coverage")
                if pace_cover is not None:
                    text = (f"при нынешнем темпе эскроу очереди «{queue['queue']}» "
                            + ("НЕ покрывает" if pace_cover < 1 else "покрывает")
                            + f" кредит ({_times(pace_cover)}), по плану финмодели — "
                            f"{_times(queue['plan_coverage_at'])}")
                else:
                    text = (f"эскроу очереди «{queue['queue']}» покроет кредит на "
                            f"{_times(queue['plan_coverage_at'])} по плану финмодели")
                pieces.append(text)
        closed = (block.get("escrow_bank") or {}).get("closed")
        if closed:
            pieces.append(f"эскроу на конец {closed['quarter']} "
                          f"{'выше' if closed['gap'] >= 0 else 'ниже'} плана банка на "
                          f"{_rub(abs(closed['gap']))}")
        if escrow.get("state") == "ok" and escrow.get("inflow_month") is not None:
            pieces.append(f"на эскроу за {_months_label(report['end'])} поступило "
                          f"{_rub(escrow['inflow_month'])}")
        add("Финансирование", "; ".join(pieces).capitalize() + ".",
            f"РСС от {_day(block['rss'])}, карточка финансирования Монитора, план «КРЕДИТЫ»",
            "bad" if limit.get("known") and float(limit.get("additional_financing") or 0) > 0
            else "")
    else:
        add("Финансирование", block.get("reason") or "Данных нет.", "", "missing")

    block = report.get("legal") or {}
    if block.get("state") == "ok" and block.get("open"):
        opened = block["open"]
        ours = sum(item["totals"]["to_them"] for item in opened)
        theirs = sum(item["totals"]["to_us"] for item in opened)
        text = (f"Открытых споров: {len(opened)}; наши требования — {_rub(ours)}"
                + (f", требования к нам — {_rub(theirs)}" if theirs else ""))
        growing = [item["card"]["counterparty"] for item in opened
                   if any(claim["growing"] for claim in item["card"]["claims"])]
        if growing:
            text += f"; неустойка продолжает расти: {', '.join(growing)}"
        dated = sorted((item for item in opened if item["card"]["deadline"]),
                       key=lambda item: item["card"]["deadline"])
        if dated:
            first = dated[0]["card"]
            text += (f". Ближайший срок — {_day(first['deadline'])}, "
                     f"{first['counterparty']}: {first['next_step'] or 'следующий шаг не записан'}")
        waiting = sum(1 for item in opened if item.get("unchecked"))
        add("Споры", _sentence(text),
            f"реестр споров; {waiting} из {len(opened)} карточек внесены по документам "
            "владельца и ждут проверки юриста" if waiting
            else "реестр споров, карточки подтверждены по документам")

        add("Споры", _sentence(text), "реестр споров, карточки подтверждены по документам")
    elif block.get("state") == "ok" and not block.get("recorded"):
        add("Споры", LEGAL_EMPTY, "реестр споров", "missing")

    block = report.get("notes") or {}
    if block.get("state") == "ok":
        opened = block.get("open") or []
        fresh = [n for n in opened if n.get("changed")]
        if opened:
            text = f"Открытых вопросов: {len(opened)}"
            if fresh:
                text += (f", новых или изменённых за {period}: {len(fresh)} — "
                         + ", ".join(f"«{n['topic']}»" for n in fresh[:3]))
            add("Открытые вопросы", text + ".", "общая информация по проекту")
    return out


# --------------------------------------------------------------------------
# Текст сообщения
# --------------------------------------------------------------------------

def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}".replace(".", ",") + "%"


def _sentence(text: str) -> str:
    """Точка в конце — одна: «п. п.» уже кончается точкой."""
    return text if text.endswith(".") else text + "."


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(count % 10, many)


def _pp(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(value) * 100:.1f}".replace(".", ",") + " п. п."


def _rub(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    amount = abs(value)
    if amount >= 1e9:
        text = f"{amount / 1e9:.2f} млрд ₽"
    elif amount >= 1e6:
        text = f"{amount / 1e6:.1f} млн ₽"
    else:
        text = f"{amount:,.0f} ₽".replace(",", " ")
    return sign + text.replace(".", ",")


def _area(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f} м²".replace(",", " ")


def _day(value: str | None) -> str:
    return _date(value).strftime("%d.%m.%Y") if value else "—"


def _title(report: dict[str, Any]) -> str:
    start, end = _date(report["start"]), _date(report["end"])
    if report["kind"] == "month":
        return f"за {_MONTHS[end.month - 1]} {end.year}"
    return f"за неделю {start:%d.%m} — {end:%d.%m.%Y}"


_PIECE_WORDS = {"Машиноместо": ("машиноместо", "машиноместа", "машиномест"),
                "Кладовая": ("кладовая", "кладовые", "кладовых")}


def _pieces(fact: dict[str, Any]) -> str:
    """«3 машиноместа, 1 кладовая» — то, что продаётся штукой."""
    out = []
    for name, count in sorted((fact.get("pieces") or {}).items()):
        words = _PIECE_WORDS.get(name, (name.lower(),) * 3)
        out.append(f"{count:.0f} {_plural(int(count), *words)}")
    return ", ".join(out)


def _sales_line(label: str, fact: dict[str, Any]) -> str:
    price = (f", квартиры в среднем по {_rub(fact['price_flats'])} за м²"
             if fact.get("price_flats") else "")
    word = _plural(fact["contracts"], "договор", "договора", "договоров")
    pieces = _pieces(fact)
    return (f"{label}: {fact['contracts']} {word} на {_rub(fact['amount'])}: "
            f"квартиры и помещения — {_area(fact['area'])}"
            + (f", {pieces}" if pieces else "") + f"{price}.")


def _months_label(key: str | None) -> str:
    if not key:
        return "—"
    year, month = str(key)[:7].split("-")
    return f"{_MONTHS[int(month) - 1]} {year}"


_MONTHS_SINCE = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                 "августа", "сентября", "октября", "ноября", "декабря")


def _since(key: str | None) -> str:
    """«с ноября 2026» — месяц после предлога «с»."""
    if not key:
        return "—"
    year, month = str(key)[:7].split("-")
    return f"с {_MONTHS_SINCE[int(month) - 1]} {year}"


def _times(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",") + "×"


def _bank_escrow_lines(block: dict[str, Any]) -> list[str]:
    """Эскроу против плана банка словами: закрытый квартал и текущий."""
    if not block:
        return []
    if block.get("state") != "ok":
        return [block.get("reason") or "План банка по эскроу: данных нет."]
    out = []
    closed = block.get("closed")
    if closed:
        gap = closed["gap"]
        out.append(f"Эскроу по плану банка (лист «{block['sheet']}», утверждено по CF): "
                   f"на конец {closed['quarter']} план {_rub(closed['plan'])}, накоплено "
                   f"{_rub(closed['actual'])} — {'больше' if gap >= 0 else 'меньше'} плана "
                   f"на {_rub(abs(gap))}.")
    current = block.get("current")
    if current:
        out.append(f"План банка на конец {current['quarter']} — {_rub(current['plan'])}; "
                   f"на {_months_label(current['measured_at'])} накоплено "
                   f"{_rub(current['actual'])}.")
    return out


def _chapters_words(limit: dict[str, Any]) -> str:
    """«главы 1–3» из расчёта Монитора; без главы 1 — и почему."""
    words = f"главы {limit.get('chapters_label') or '2–3'}"
    reason = limit.get("chapters_reason")
    return f"{words} ({reason})" if reason else words


def _remaining_words(limit: dict[str, Any], borrowed: float | None = None,
                     short: bool = False) -> str:
    """Как из лимита получился остаток — словами, чтобы вычитание читалось.

    Остаток считается по статьям: лимит статьи минус всё оплаченное по ней —
    кредитом и своими деньгами, а статья с перерасходом идёт нулём. Разницу
    раскладывает Монитор (`remaining_check`); здесь она только называется.
    """
    check = limit.get("remaining_check") or {}
    paid = float(limit.get("paid_actual") or 0.0)
    if borrowed is None:
        borrowed = limit.get("paid_borrowed")
    words = f"лимит минус всё оплаченное {_rub(paid)}"
    if borrowed is not None:
        words += f" (кредитом {_rub(borrowed)}, своими деньгами {_rub(paid - float(borrowed))})"
    if short:
        return words
    # Поправка меньше 0,1% лимита — округление, а не отдельная строка.
    tiny = 0.001 * float(limit.get("bank_limit") or 0.0)
    if float(check.get("overpaid") or 0.0) > tiny:
        words += f"; перерасход по статьям {_rub(check['overpaid'])} остаток не уменьшает"
    gap = float(check.get("book_gap") or 0.0)
    if abs(gap) > tiny:
        words += (f"; лимиты статей в финкниге {'больше' if gap > 0 else 'меньше'} "
                  f"сметы РСС на {_rub(abs(gap))}")
    return words


def _approved_need(limit: dict[str, Any]) -> dict[str, float] | None:
    """Потребность по утверждённому бюджету — из расчёта Монитора, не заново.

    РСС — то, что даёт банк; утверждённая модель — сколько надо, чтобы
    построить (владелец, 30.08.2026). Шапка Монитора считает дефицит от модели
    («лестница» `deficit_ladder.total`), а сводка показывала только дефицит по
    РСС, и утверждённого бюджета в ней не было вовсе (владелец, 21.10.2026:
    «в мониторе есть бюджет строительства по утверждённому бюджету, 6 с лишним
    млрд. Где это учтено?»).
    """
    approved = float(limit.get("approved") or 0.0)
    if not limit.get("known") or approved <= 0:
        return None
    total = (limit.get("deficit_ladder") or {}).get("total")
    return {"approved": approved,
            "remaining": float(limit.get("approved_remaining") or 0.0),
            "fuel": float(limit.get("bank_remaining") or 0.0) + float(limit.get("reserve") or 0.0),
            "deficit": float(total) if total is not None else None}


def _funding_text(report: dict[str, Any]) -> list[str]:
    """Строки блока «Финансирование» — одни и те же для сообщения и PDF."""
    block = report.get("funding") or {}
    if block.get("state") != "ok":
        return [block.get("reason") or "Данных нет."]
    lines = []
    limit = block.get("limit") or {}
    if limit.get("known"):
        lines.append(f"Лимит банка по смете РСС ({_chapters_words(limit)}): "
                     f"{_rub(limit.get('bank_limit'))}; "
                     f"остаток лимитов статей {_rub(limit.get('bank_remaining'))} — "
                     f"{_remaining_words(limit, (block.get('draws') or {}).get('total'))}; "
                     f"резерв {_rub(limit.get('reserve'))}.")
        need = _approved_need(limit)
        if need:
            line = (f"Утверждённый бюджет ({_chapters_words(limit)}, финмодель): "
                    f"{_rub(need['approved'])}; "
                    f"остаток потребности (бюджет минус оплаченное) {_rub(need['remaining'])} "
                    f"при лимитах статей и резерве {_rub(need['fuel'])}")
            if need["deficit"] is not None:
                line += (f" — не хватает по утверждённому бюджету {_rub(need['deficit'])}"
                         if need["deficit"] > 0 else " — хватает")
            lines.append(line + ".")
        else:
            lines.append("Утверждённый бюджет не загружен (финансовая книга, лист «Расчет "
                         "стоимости строительства»): дефицит посчитан только по РСС.")
        extra = float(limit.get("additional_financing") or 0.0)
        if extra > 0:
            lines.append(f"По РСС не хватает: {_rub(extra)}, "
                         f"начиная {_since(limit.get('additional_financing_from'))}.")
        else:
            lines.append("По РСС лимитов и резерва хватает до ввода по прогнозу Монитора.")
    else:
        lines.append(f"Лимит и дефицит не посчитаны: {limit.get('reason') or 'нет данных'}.")
    period = PERIODS[report["kind"]]
    draws, interest = block["draws"], block["interest"]
    lines.append(f"Выборка кредита (платежи РСС из заёмных средств"
                 + (f", {_chapters_words(limit)}" if limit.get("known") else "") + f"): за {period} "
                 f"{_rub(draws['period'])}, с начала месяца {_rub(draws['month'])}, "
                 f"с начала проекта {_rub(draws['total'])}.")
    lines.append(f"Услуги банка (статья 3.5 РСС, в том числе проценты): за {period} "
                 f"{_rub(interest['period'])}, с начала месяца {_rub(interest['month'])}, "
                 f"с начала проекта {_rub(interest['total'])}.")
    lines.extend(_bank_escrow_lines(block.get("escrow_bank") or {}))
    escrow = block.get("escrow") or {}
    if escrow.get("state") != "ok":
        lines.append(escrow.get("reason") or "Эскроу: данных нет.")
    for queue in escrow.get("queues") or []:
        text = (f"Эскроу, очередь «{queue['queue']}»: на {_months_label(queue['measured_at'])} "
                f"накоплено {_rub(queue.get('actual'))}")
        if queue.get("plan") is not None:
            text += f" при плане финмодели (лист «КРЕДИТЫ») {_rub(queue['plan'])}"
            if queue.get("gap") is not None:
                text += f" ({'больше' if queue['gap'] >= 0 else 'меньше'} плана на {_rub(abs(queue['gap']))})"
        text += "."
        if queue.get("plan_coverage_at") is not None:
            at = _months_label(queue.get("disclosure"))
            word = "к раскрытию" if queue.get("disclosure_known") else "к концу плана"
            text += (f" {word.capitalize()} ({at}) план покрывает кредит на "
                     f"{_times(queue['plan_coverage_at'])}")
            if queue.get("keeping_pace_coverage") is not None:
                text += f", при нынешнем темпе — на {_times(queue['keeping_pace_coverage'])}"
            text += "."
        lines.append(text)
    lines.append(f"Платежи — из отчёта РСС от {_day(block['rss'])}.")
    return lines


def _funding_html(report: dict[str, Any]) -> str:
    esc = html.escape
    block = report.get("funding") or {}
    if block.get("state") != "ok":
        return f"<p class='missing'>{esc(block.get('reason') or 'Данных нет.')}</p>"
    out = []
    limit = block.get("limit") or {}
    if limit.get("known"):
        extra = float(limit.get("additional_financing") or 0.0)
        check = limit.get("remaining_check") or {}
        rows = [["Лимит по смете РСС", _rub(limit.get("bank_limit"))],
                ["Оплачено с начала проекта (кредитом и своими деньгами)", _rub(limit.get("paid_actual"))]]
        rows.append(["в том числе кредитом", _rub((block.get("draws") or {}).get("total"))])
        tiny = 0.001 * float(limit.get("bank_limit") or 0.0)
        if float(check.get("overpaid") or 0.0) > tiny:
            rows.append(["Перерасход по статьям (остаток не уменьшает)", _rub(check["overpaid"])])
        if abs(float(check.get("book_gap") or 0.0)) > tiny:
            rows.append(["Лимиты статей финкниги против сметы РСС", _signed_rub(check["book_gap"])])
        out.append(_table([f"Лимит банка ({esc(_chapters_words(limit))})", "Сумма"], rows + [
            ["Остаток лимитов статей", _rub(limit.get("bank_remaining"))],
            ["Резерв", _rub(limit.get("reserve"))],
            ["Не хватает по РСС",
             (f"{_rub(extra)} {_since(limit.get('additional_financing_from'))}"
              if extra > 0 else "хватает до ввода")]]))
        need = _approved_need(limit)
        if need:
            out.append(_table([f"Утверждённый бюджет ({esc(_chapters_words(limit))}, финмодель)",
                               "Сумма"], [
                ["Утверждённый бюджет", _rub(need["approved"])],
                ["Оплачено с начала проекта", _rub(limit.get("paid_actual"))],
                ["Остаток потребности (бюджет минус оплаченное)", _rub(need["remaining"])],
                ["Лимиты статей и резерв по РСС", _rub(need["fuel"])],
                ["Не хватает по утверждённому бюджету",
                 "—" if need["deficit"] is None
                 else (_rub(need["deficit"]) if need["deficit"] > 0 else "хватает")]]))
        else:
            out.append("<p class='missing'>Утверждённый бюджет не загружен (финансовая книга, "
                       "лист «Расчет стоимости строительства»): дефицит посчитан только по РСС.</p>")
    else:
        out.append(f"<p class='missing'>Лимит и дефицит не посчитаны: "
                   f"{esc(limit.get('reason') or 'нет данных')}.</p>")
    draws, interest = block["draws"], block["interest"]
    out.append(_table(["", f"За {PERIODS[report['kind']]}", "С начала месяца", "С начала проекта"], [
        ["Выборка кредита (платежи из заёмных средств"
         + (f", {esc(_chapters_words(limit))}" if limit.get("known") else "") + ")", _rub(draws["period"]),
         _rub(draws["month"]), _rub(draws["total"])],
        ["Услуги банка, статья 3.5 (в том числе проценты)", _rub(interest["period"]),
         _rub(interest["month"]), _rub(interest["total"])]]))
    bank = block.get("escrow_bank") or {}
    if bank.get("state") == "ok":
        rows = []
        if bank.get("closed"):
            c = bank["closed"]
            rows.append([f"На конец {c['quarter']}", _rub(c["plan"]), _rub(c["actual"]),
                         _signed_rub(c["gap"])])
        if bank.get("current"):
            c = bank["current"]
            rows.append([f"На конец {c['quarter']} (накоплено на "
                         f"{_months_label(c['measured_at'])})", _rub(c["plan"]),
                         _rub(c["actual"]), "—"])
        out.append(_table([f"Эскроу против плана банка (лист «{esc(bank['sheet'])}», "
                           "утверждено по CF)", "План банка", "Накоплено", "Против плана"], rows))
    elif bank:
        out.append(f"<p class='missing'>{esc(bank.get('reason') or '')}</p>")
    escrow = block.get("escrow") or {}
    if escrow.get("state") != "ok":
        out.append(f"<p class='missing'>{esc(escrow.get('reason') or 'Эскроу: данных нет.')}</p>")
    elif escrow.get("queues"):
        out.append(_table(["Эскроу, очередь", "Месяц", "Накоплено", "План финмодели («КРЕДИТЫ»)",
                           "Покрытие кредита по плану",
                           "При нынешнем темпе"], [
            [esc(q["queue"]), _months_label(q.get("measured_at")), _rub(q.get("actual")),
             _rub(q.get("plan")), _times(q.get("plan_coverage_at")),
             _times(q.get("keeping_pace_coverage"))] for q in escrow["queues"]]))
    out.append(f"<p class='note'>Платежи — из отчёта РСС от {_day(block['rss'])}.</p>")
    return "\n".join(out)


def render_text(report: dict[str, Any]) -> str:
    """Сообщение для Telegram (разметка HTML) — из той же сводки, что и PDF."""
    esc = html.escape
    lines = [f"<b>Сводка по проекту «{esc(report['project'])}» {_title(report)}</b>"]

    lines += ["", "<b>Главное</b>"]
    for item in report.get("findings") or []:
        lines.append(f"• <b>{esc(item['topic'])}.</b> {esc(item['text'])}")

    lines += ["", "<b>Стройка</b>"]
    block = report.get("physical") or {}
    if block.get("state") == "ok":
        lines.append(f"Выполнено по графику работ {_pct(block['fact'])}, "
                     f"по плану к этой дате должно быть {_pct(block['plan'])}.")
        if block.get("delta") is not None:
            lines.append(_sentence(
                f"За {PERIODS[report['kind']]} выполнение "
                f"{'выросло' if block['delta'] >= 0 else 'снизилось'} на "
                f"{_pp(abs(block['delta']))[1:]}"))
        else:
            lines.append("Прирост за период посчитать не из чего: на начало "
                         "периода не было ни одного графика с процентами выполнения.")
        lines.extend(esc(line) for line in _physical_notes(block))
    else:
        lines.append(esc(block.get("reason") or "Данных нет."))

    block = report.get("crew") or {}
    if block.get("state") == "ok" and block["now"]["days"]:
        now = block["now"]
        lines.append(f"Люди: в среднем {now['workers_avg']:.0f} рабочих и {now['itr_avg']:.0f} ИТР "
                     f"в день по {now['days']} отчётам, максимум {now['workers_max']:.0f}.")
    elif block.get("reason"):
        lines.append(esc(block["reason"]))
    for group in (block.get("works") or [])[:4]:
        shown = "; ".join(entry["line"] for entry in group["lines"][:3])
        more = len(group["lines"]) - 3
        lines.append(esc(f"Работы {group['contractor']}: {shown}"
                         + (f" и ещё {more}" if more > 0 else "") + "."))
    chosen = len((report.get("photos") or {}).get("items") or [])
    if chosen:
        lines.append(f"Фото со стройки: {chosen} — в PDF.")
    breakdown = (report.get("physical") or {}).get("breakdown") or {}
    for row in breakdown.get("laggards", [])[:3]:
        lines.append(esc(f"Отстаёт: {row['name']}"
                         + (f" ({row['object']})" if row["object"] else "")
                         + f" — {_pct(row['fact'])} при плане {_pct(row['plan'])}."))

    lines.extend(esc(line) for line in report_gantt.text_lines(report.get("gantt") or {}))

    lines += ["", "<b>Продажи</b>"]
    block = report.get("sales") or {}
    if block.get("state") == "ok":
        lines.append(_sales_line(f"За {PERIODS[report['kind']]}", block["period"]))
        month = block["month"]
        if month.get("fm"):
            lines.append(f"План финмодели на месяц: {_rub(month['fm']['amount'])}, "
                         f"{_area(month['fm']['area'])}; продано с начала месяца "
                         f"{_rub(month['fact']['amount'])}, {_area(month['fact']['area'])}.")
        quarter = block["quarter"]
        lines.append(_sales_line(f"С начала квартала {quarter['key']}", quarter["fact"]))
        if quarter.get("fm"):
            lines.append(f"План финмодели на квартал: {_rub(quarter['fm']['amount'])}, "
                         f"{_area(quarter['fm']['area'])}.")
        if quarter.get("bank"):
            lines.append(f"План банка на квартал: {_rub(quarter['bank']['amount'])}, "
                         f"{_area(quarter['bank'].get('area'))}.")
        elif quarter.get("bank_reason"):
            lines.append(esc(quarter["bank_reason"]))
        if block.get("stale"):
            lines.append(f"Внимание: договоры загружены {_day(block['uploaded'])}, "
                         "более поздние сделки в сводку не попали.")
    else:
        lines.append(esc(block.get("reason") or "Данных нет."))

    lines += ["", "<b>Финансирование</b>"]
    lines += [esc(line) for line in _funding_text(report)]

    lines += ["", "<b>Бюджет месяца</b>"]
    block = report.get("budget") or {}
    if block.get("state") in {"ok", "partial"}:
        month = _date(block["month"])
        name = f"{_MONTHS[month.month - 1]} {month.year}"
        for line in block["lines"]:
            if line.get("plan") is not None and line.get("fact") is None:
                lines.append(f"{line['label']} за {name}: план {_rub(line['plan'])}, "
                             "оплат в РСС нет.")
            elif line.get("plan") is not None:
                lines.append(f"{line['label']} за {name}: план {_rub(line['plan'])}, "
                             f"оплачено {_rub(line['fact'])}, "
                             f"осталось {_rub(line['remaining'])}"
                             + (f" — {line['note']}." if line.get("note") else "."))
            else:
                lines.append(f"{line['label']} за {name}: оплачено {_rub(line['fact'])}.")
        if block.get("reason"):
            lines.append(esc(block["reason"]))
        lines.append(f"Оплаты взяты из отчёта РСС от {_day(block['rss'])}.")
    else:
        lines.append(esc(block.get("reason") or "Данных нет."))

    lines += ["", "<b>Общая информация</b>"]
    lines.extend(_legal_lines(report.get("legal") or {}))
    block = report.get("notes") or {}
    if block.get("state") != "ok":
        lines.append(esc(block.get("reason") or "Данных нет."))
    elif not block.get("open") and not block.get("closed"):
        lines.append("Открытых вопросов нет, за период записей не было.")
    else:
        for note in block.get("open") or []:
            mark = " (новое)" if note.get("changed") else ""
            lines.append(f"• <b>{esc(note['topic'])}</b>{mark}: {esc(note['text'])} "
                         f"— {_day(note['at'])}, {esc(note['author'])}.")
        for note in block.get("closed") or []:
            lines.append(f"• <b>{esc(note['topic'])}</b> — вопрос закрыт: "
                         f"{esc(note['text'])} — {_day(note['at'])}, {esc(note['author'])}.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Документ для PDF и для просмотра на странице
# --------------------------------------------------------------------------

REPORT_STYLE = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#17202a;font-size:11.5px;line-height:1.4;margin:0}
h1{font-size:20px;margin:0 0 2px;color:#0f2a4d}
h2{break-after:avoid;page-break-after:avoid;font-size:15px;color:#1f4e8c;margin:20px 0 8px;border-bottom:2px solid #1f4e8c;padding-bottom:3px}
h3{break-after:avoid;page-break-after:avoid;font-size:12px;margin:14px 0 4px;color:#17202a}
.sub{color:#5b6b7d;font-size:11px;margin-bottom:8px}
table{border-collapse:collapse;width:100%;margin:4px 0 6px;break-inside:avoid;page-break-inside:avoid}
tr{break-inside:avoid;page-break-inside:avoid}
th,td{border-bottom:1px solid #e1e6ec;padding:4px 6px;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}
.keep{break-inside:avoid;page-break-inside:avoid}th{background:#eef2f7;font-weight:600;color:#334155;border-bottom:1px solid #c5cfdb}
.neg{color:#b42318;font-weight:600}
.photos{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:6px 0}
figure.photo{margin:0;break-inside:avoid;page-break-inside:avoid}figure.photo img{width:100%;height:230px;object-fit:cover;border-radius:4px;border:1px solid #d6dde6;display:block}
figure.photo figcaption{font-size:10.5px;margin-top:3px}
table.legal td{vertical-align:top;text-align:left;white-space:normal}table.legal td:first-child{width:28%;color:#5b6b7d}
table.works td{vertical-align:top}table.works td:nth-child(2),table.works th:nth-child(2){text-align:left;white-space:normal}table.works td:nth-child(3){color:#5b6b7d;font-size:10.5px;white-space:normal}
table.articles tr.chapter td{background:#f4f7fb;font-weight:600}
table.articles tr.total td{border-top:2px solid #1f4e8c;font-weight:600}
table.articles tr.over td{background:#fdecea}table.articles tr.left td{background:#fff6dd}
.note{color:#5b6b7d;font-size:10.5px;margin:4px 0}.warn{color:#9a5b00}.missing{color:#9a5b00;font-style:italic}
.item{margin:4px 0}.item b{font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0 4px}
.tile{border:1px solid #d6dde6;border-top:4px solid #1f4e8c;border-radius:4px;padding:7px 9px;break-inside:avoid;background:#fff}
.tile.good{border-top-color:#2e7d32}.tile.bad{border-top-color:#b42318;background:#fff8f7}.tile.missing{border-top-color:#9aa5b1}
.tile .k{font-size:10px;color:#5b6b7d;text-transform:uppercase;letter-spacing:.02em}
.tile .v{font-size:20px;font-weight:700;margin:2px 0;color:#0f2a4d}.tile.bad .v{color:#b42318}.tile.missing .v{font-size:13px;color:#7b8794;font-weight:600}
.tile .n{font-size:10px;color:#475569}
ul.findings{margin:6px 0;padding-left:18px}ul.findings li{margin:5px 0;padding-left:2px}
ul.findings li.bad::marker{color:#b42318}ul.findings li.missing{color:#5b6b7d}
ul.findings li b{font-weight:700}ul.findings li.bad b{color:#b42318}
.finding .source{color:#7b8794;font-size:10px}
.pagebreak{break-after:page;page-break-after:always}
h2.block{break-before:page;page-break-before:always}h2.block.first{break-before:auto;page-break-before:auto}
ol.toc{margin:6px 0 10px;padding-left:22px;columns:2;column-gap:24px}ol.toc li{margin:2px 0;break-inside:avoid}ol.toc a{color:#1f4e8c;text-decoration:none}
section{break-inside:auto}
.switch-charts .switch{display:none}
figure.chart{margin:10px 0 6px;break-inside:avoid;page-break-inside:avoid}figure.chart figcaption{font-size:11.5px;color:#17202a;margin-bottom:3px;font-weight:600}
svg.chart{display:block;max-width:100%}
"""


def _month_name(key: str) -> str:
    """«2026-10» → «октябрь 2026»."""
    year, month = str(key).split("-")[:2]
    return f"{_MONTHS[int(month) - 1]} {year}"


def _quarter_name(key: str) -> str:
    """«2026 Q4» → «4 квартал 2026»."""
    year, number = str(key).split(" Q")
    return f"{number} квартал {year}"


def _row(cells: list[str], head: bool = False) -> str:
    tag = "th" if head else "td"
    return "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>"


def _table(head: list[str], rows: list[list[str]]) -> str:
    return "<table>" + _row(head, True) + "".join(_row(row) for row in rows) + "</table>"


def _breakdown_html(breakdown: dict[str, Any], kind: str) -> str:
    esc = html.escape
    out = []
    sections = breakdown.get("sections") or []
    if len(sections) > 1:
        out.append("<h3>По разделам графика работ</h3>")
        out.append(_table(["Раздел", "План к дате", "Выполнено", "Отставание",
                           f"Прирост за {PERIODS[kind]}"], [
            [esc(row["section"]), _pct(row["plan"]), _pct(row["fact"]), _pp(row["lag"]),
             _pp(row["delta"]) if row.get("delta") is not None else "—"]
            for row in sections[:12]]))
        shown = sections[:8]
        out.append(charts.bar_chart(
            "Разделы графика: план и факт выполнения", [row["section"][:22] for row in shown],
            [{"name": "План", "values": [row["plan"] * 100 for row in shown]},
             {"name": "Факт", "values": [row["fact"] * 100 for row in shown]}], "%", digits=0))
    if breakdown.get("laggards"):
        total = breakdown["laggards_total"]
        out.append(f"<h3>Больше всего отстают (с отставанием {total} "
                   f"{_plural(total, 'работа', 'работы', 'работ')})</h3>")
        out.append(_table(["Работа", "Объект", "План к дате", "Выполнено", "Отставание", "Окончание по плану"], [
            [esc(row["name"]), esc(row["object"]), _pct(row["plan"]), _pct(row["fact"]),
             _pp(row["lag"]), _day(row["finish"])] for row in breakdown["laggards"]]))
    if breakdown.get("stalled"):
        out.append(f"<h3>Без прироста за {PERIODS[kind]} ({breakdown['stalled_total']})</h3>")
        out.append("<p class='note'>План работы за период вырос, а процент выполнения тот же, "
                   "что на начало периода.</p>")
        out.append(_table(["Работа", "Объект", "План к дате", "Выполнено"], [
            [esc(row["name"]), esc(row["object"]), _pct(row["plan"]), _pct(row["fact"])]
            for row in breakdown["stalled"]]))
    elif breakdown and not breakdown.get("stalled_known"):
        out.append("<p class='note'>Работы без прироста не выделены: на начало периода не было "
                   "графика с процентами.</p>")
    return "\n".join(out)


def _crew_html(block: dict[str, Any], kind: str) -> str:
    esc = html.escape
    if block.get("state") != "ok":
        return f"<p class='missing'>{esc(block.get('reason') or 'Данных нет.')}</p>"
    now, before = block["now"], block["previous"]
    out = []
    if not now["days"]:
        out.append(f"<p class='missing'>За период ни одного отчёта со стройки; последний — "
                   f"от {_day(block.get('last_report'))}.</p>")
    else:
        def num(value: float | None) -> str:
            return "—" if value is None else f"{value:.0f}"

        out.append(_table(["", f"За {PERIODS[kind]}", "Предыдущий такой же период"], [
            ["Дней с отчётом", f"{now['days']} из {block['period_days']}", str(before["days"])],
            ["Рабочих в среднем в день", num(now["workers_avg"]), num(before["workers_avg"])],
            ["Рабочих максимум", num(now["workers_max"]), num(before["workers_max"])],
            ["ИТР в среднем в день", num(now["itr_avg"]), num(before["itr_avg"])]]))
        if block.get("by_contractor"):
            out.append(_table(["Подрядчик", "Рабочих в среднем", "ИТР в среднем", "Дней в отчётах"], [
                [esc(row["name"]), f"{row['workers_avg']:.0f}", f"{row['itr_avg']:.0f}",
                 str(row["days"])] for row in block["by_contractor"]]))
    series = block.get("series") or []
    if any(point["workers"] is not None for point in series):
        out.append(charts.line_chart(
            "Рабочих на площадке по дням (пропуск — дня без отчёта)",
            [_date(p["day"]).strftime("%d.%m") for p in series],
            [{"name": "Рабочие", "values": [p["workers"] for p in series]}],
            "чел.", label_every=charts.every(len(series))))
    out.append("<p class='note'>Плановой численности в графике работ нет — сравнение с "
               "планом не приводится.</p>")
    return "\n".join(out)


def _works_html(block: dict[str, Any], kind: str) -> str:
    """Выполненные работы за период — как их назвали прорабы в отчётах бота."""
    esc = html.escape
    if block.get("state") != "ok":
        return ""
    title = f"<h3>Выполненные работы за {PERIODS[kind]} — по ежедневным отчётам со стройки</h3>"
    groups = block.get("works") or []
    if not groups:
        days = (block.get("now") or {}).get("days")
        why = ("в отчётах за период нет раздела «По работам»" if days
               else "за период не было ни одного отчёта со стройки")
        return title + f"<p class='missing'>Работы не перечислены: {why}.</p>"
    rows = []
    for group in groups:
        for index, entry in enumerate(group["lines"]):
            dates = ", ".join(_date(day).strftime("%d.%m") for day in entry["days"])
            rows.append([f"<b>{esc(group['contractor'])}</b>" if index == 0 else "",
                         esc(entry["line"]), dates])
    return (title + "<table class='works'>" + _row(["Подрядчик", "Работы", "Дни в отчётах"], True)
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
            + "</table><p class='note'>Строки — как их написали в отчёте; одинаковая строка "
              "за несколько дней показана один раз с датами.</p>")


def _photos_html(block: dict[str, Any], kind: str) -> str:
    """Фото со стройки, отмеченные на странице сводки. Не отмечено — блока нет."""
    esc = html.escape
    items = block.get("items") or []
    if not items:
        return ""
    cells = []
    for item in items:
        note = " · ".join(part for part in (_date(item["day"]).strftime("%d.%m.%Y"),
                                            item.get("author") or "") if part)
        caption = (f"{esc(item['caption'])}<br>" if item.get("caption") else "")
        cells.append(f"<figure class='photo'><img src='{item['src']}' alt='{esc(item.get('caption') or 'фото со стройки')}'>"
                     f"<figcaption>{caption}<span class='note'>{esc(note)}</span></figcaption></figure>")
    return (f"<h3>Фото со стройки за {PERIODS[kind]}</h3><div class='photos'>"
            + "".join(cells) + "</div>")


def _month_elapsed(month: datetime.date, end: datetime.date) -> float:
    days = ((month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - month).days
    return min(1.0, max(0.0, ((end - month).days + 1) / days))


def _budget_forecast(block: dict[str, Any], end: datetime.date) -> list[dict[str, Any]]:
    """Сколько оплатят к концу месяца, если темп с начала месяца сохранится."""
    elapsed = _month_elapsed(_date(block["month"]), end)
    out = []
    for line in block.get("lines") or []:
        # Служба заказчика: факт РСС шире плана (см. примечание строки) —
        # прогноз против плана был бы ложной тревогой.
        # Земля и АХР платятся разово, темп месяца к ним не применим.
        if (not line.get("plan") or not elapsed
                or line["key"] in {"service", "land", "admin"}):
            continue
        forecast = line["fact"] / elapsed
        out.append({"label": line["label"], "plan": line["plan"], "fact": line["fact"],
                    "forecast": forecast, "gap": forecast - line["plan"]})
    return out


# Меры темпа продаж — одна таблица для кнопок и графиков. Порядок — порядок
# кнопок; первая мера открыта на странице.
PACE_MEASURES = (
    ("area", "м²", "м² договоров", 1.0, 0),
    ("units", "лоты", "лотов всех типов (квартиры, помещения, машиноместа, кладовые)", 1.0, 0),
    ("amount", "млн ₽", "сумма договоров, млн ₽", 1e6, 1),
)


def _pace_charts(pace: list[dict[str, Any]]) -> str:
    """Темп продаж по месяцам — один предмет в трёх мерах, цена линией на каждом.

    Владелец (22.10.2026): «может совместить для экономии места? и отдельно
    лотами и млн рублей сделать такие же графики? на странице переключением как
    в отчёте о продажах, а в пдф подряд три графика». Разметка одна: страница
    показывает одну меру и кнопки, документ — все три подряд без кнопок.
    """
    if not pace:
        return ""
    months = [_month_short(p["month"]) for p in pace]
    prices = [p.get("price_flats") for p in pace]
    line = ({"name": "Цена квартир, тыс. ₽/м²", "values": charts.scaled(prices, 1e3),
             "unit": "тыс. ₽/м²", "digits": 0} if any(prices) else None)
    buttons, panes = [], []
    for index, (key, name, words, divisor, digits) in enumerate(PACE_MEASURES):
        figure = charts.bar_chart(
            f"Темп продаж по месяцам: {words}" + (" и цена квартир" if line else ""),
            months, [{"name": name, "values": charts.scaled([p.get(key) for p in pace], divisor)}],
            name, digits=digits, line=line)
        if not figure:
            continue
        on = " on" if not panes else ""
        buttons.append(f'<button type="button" data-pane="{key}" class="{on.strip()}">{name}</button>')
        panes.append(f'<div class="pane{on}" data-pane="{key}">{figure}</div>')
    if not panes:
        return ""
    return ('<div class="switch-charts" data-switch="sales-pace">'
            f'<div class="switch">{"".join(buttons)}</div>{"".join(panes)}</div>')


def _signed_rub(value: float | None) -> str:
    """Отклонение: минус — красным (перерасход, отставание, недобор)."""
    if value is None:
        return "—"
    return f"<span class='neg'>{_rub(value)}</span>" if value < -0.5 else _rub(value)


# Строки бюджета месяца под итогом «стройка и коммерческие расходы»: они идут
# во «Всего по бюджету месяца», но не в сравнимый итог.
_BELOW_TOTAL = {"service", "land", "admin"}


def _budget_articles_html(table: dict[str, Any]) -> str:
    """Бюджет месяца по статьям БДДС: план, оплачено по РСС, остаток, процент."""
    esc = html.escape
    if not table.get("chapters"):
        return ""
    over = set(table.get("overrun") or [])
    left = table.get("largest_left")
    rows = []

    def cells(row: dict[str, Any], label: str, codes: str = "") -> list[str]:
        if row.get("plan") is not None:
            plan = _rub(row["plan"])
        elif row.get("key") == "unplanned":
            plan = "без плана"
        elif row.get("in_budget") is False:
            plan = "нет в бюджете"
        else:
            plan = "—"
        fact = _rub(row["fact"]) if row["fact"] is not None else "нет в РСС"
        return [label, esc(codes), plan, fact, _signed_rub(row.get("remaining")),
                _pct(row.get("share"))]

    whole = table.get("whole")
    for chapter in table["chapters"]:
        if whole and chapter["key"] in _BELOW_TOTAL:
            continue
        single = chapter["key"] == "service"
        if not single:
            rows.append(("chapter", cells(chapter["total"], f"<b>{esc(chapter['label'])}</b>")))
        for row in chapter["rows"]:
            if row.get("plan") is None and not row["fact"]:
                continue
            tone = "over" if row["key"] in over else ("left" if row["key"] == left else "")
            label = esc(row["label"]) if single else "&nbsp;&nbsp;" + esc(row["label"])
            rows.append((tone, cells(row, label, row.get("rss", ""))))
    rows.append(("total", cells(table["total"], f"<b>{esc(table['total']['label'])}</b>")))
    if whole:
        for chapter in table["chapters"]:
            if chapter["key"] in _BELOW_TOTAL:
                row = chapter["total"]
                rows.append(("", cells(row, esc(row["label"]), row.get("rss", ""))))
        rows.append(("total", cells(whole, f"<b>{esc(whole['label'])}</b>")))
    head = ["Статья бюджета", "Коды РСС", "План месяца", "Оплачено", "Осталось", "Выполнено"]
    body = "".join(f"<tr class='{tone}'>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                   for tone, row in rows)
    out = [f"<table class='articles'>{_row(head, True)}{body}</table>"]
    notes = ["Красным — статьи с перерасходом, жёлтым — статья с самым большим "
             "неоплаченным остатком."]
    if any(chapter["key"] == "service" for chapter in table["chapters"]):
        notes.append("Служба заказчика в итог стройки и коммерческих расходов не входит: в статье 2.6 РСС кроме службы "
                     "заказчика и охраны лежат зарплаты офиса и связь, которые бюджет "
                     "относит к административным расходам, — её процент с планом не сравним.")
    if whole:
        notes.append("«Всего по бюджету месяца» — строка «РАСХОДЫ» бюджета: стройка, "
                     "коммерческие расходы, служба заказчика, земля (глава 1) и "
                     "административно-хозяйственные расходы. Оплачено по земле и "
                     "административно-хозяйственным расходам — из колонки «ФАКТ» "
                     "бюджета (их платят мимо реестра РСС); если факта в бюджете нет, "
                     "земля — по главе 1 РСС.")
    if not table.get("has_plan"):
        notes.append("Бюджета на этот месяц нет — показаны только оплаты.")
    out.append("<p class='note'>" + " ".join(notes) + "</p>")
    return "\n".join(out)


def _quarter_elapsed(end: datetime.date) -> float:
    start = datetime.date(end.year, (end.month - 1) // 3 * 3 + 1, 1)
    stop = _month_shift_up(start, 3)
    return min(1.0, ((end - start).days + 1) / (stop - start).days)


def _month_shift_up(month: datetime.date, ahead: int) -> datetime.date:
    index = month.year * 12 + month.month - 1 + ahead
    return datetime.date(index // 12, index % 12 + 1, 1)


def tiles(report: dict[str, Any]) -> list[dict[str, str]]:
    """Плитки первой страницы: главное число блока и тон отклонения.

    Числа — из уже посчитанных блоков, как и выводы; нет данных — плитка так и
    говорит, а не показывает ноль.
    """
    end = _date(report["end"])
    period = PERIODS[report["kind"]]
    out: list[dict[str, str]] = []

    def add(label: str, value: str | None, note: str, tone: str = "") -> None:
        if value is None:
            out.append({"label": label, "value": "нет данных", "note": note, "tone": "missing"})
        else:
            out.append({"label": label, "value": value, "note": note, "tone": tone})

    block = report.get("physical") or {}
    if block.get("state") == "ok":
        lag = block.get("lag")
        add("Стройка: выполнено", _pct(block["fact"]),
            f"план {_pct(block.get('plan'))}"
            + (f", {_pp(lag)}" if lag is not None else ""),
            "bad" if lag is not None and lag < -0.02 else "good")
    else:
        add("Стройка: выполнено", None, "нет графика с процентами")

    block = report.get("crew") or {}
    now = (block.get("now") or {}) if block.get("state") == "ok" else {}
    if now.get("days"):
        before = block["previous"]
        change = (now["workers_avg"] / before["workers_avg"] - 1
                  if before.get("days") and before.get("workers_avg") else None)
        add("Рабочих в среднем в день", f"{now['workers_avg']:.0f}",
            f"в прошлый период {before['workers_avg']:.0f}" if change is not None
            else f"по {now['days']} отчётам",
            "bad" if change is not None and change < -0.05 else "")
    else:
        add("Рабочих в среднем в день", None, "отчётов со стройки за период нет")

    block = report.get("sales") or {}
    quarter = (block.get("quarter") or {}) if block.get("state") == "ok" else {}
    pace = _quarter_elapsed(end)
    for name, key in (("финмодели", "fm"), ("банка", "bank")):
        plan = (quarter.get(key) or {}).get("amount")
        if quarter and plan:
            share = quarter["fact"]["amount"] / plan
            add(f"Продажи квартала к плану {name}", _pct(share),
                f"{_rub(quarter['fact']['amount'])} из {_rub(plan)}; прошло {_pct(pace)} квартала",
                "bad" if share < pace - 0.05 else "good")
        else:
            add(f"Продажи квартала к плану {name}", None,
                "плана нет" if quarter else "отчёт о продажах не подключён")

    # Деньги стройки — пятью плашками подряд (владелец, 21.10.2026: «в
    # плашках сверху должен быть ещё бюджет утверждённый, лимит банка,
    # выбрано у банка, остаток лимита, дефицит на достройку»). Все числа — из
    # того же расчёта Монитора и тех же платежей РСС, что и раздел ниже.
    block = report.get("funding") or {}
    limit = (block.get("limit") or {}) if block.get("state") == "ok" else {}
    need = _approved_need(limit) if limit.get("known") else None
    chapters = _chapters_words(limit)
    add("Утверждённый бюджет", _rub(need["approved"]) if need else None,
        f"{chapters}, финмодель" if need else "финансовая книга не загружена")
    if limit.get("known"):
        add("Лимит банка", _rub(limit.get("bank_limit")), f"смета РСС, {chapters}")
    else:
        add("Лимит банка", None, limit.get("reason") or "лимит не посчитан")
    draws = block.get("draws") if block.get("state") == "ok" else None
    if draws:
        note = f"кредитом, {chapters}; за {period} — {_rub(draws['period'])}" \
            if limit.get("known") else f"кредитом, все главы РСС; за {period} — {_rub(draws['period'])}"
        over = draws["total"] - float(limit.get("bank_limit") or 0.0)
        if limit.get("known") and over > 0:
            note += f"; больше лимита на {_rub(over)}"
        add("Выбрано у банка", _rub(draws["total"]), note, "bad" if limit.get("known") and over > 0 else "")
    else:
        add("Выбрано у банка", None, "отчёт РСС не загружен")
    if limit.get("known"):
        extra = float(limit.get("additional_financing") or 0.0)
        add("Остаток лимита банка", _rub(limit.get("bank_remaining")),
            _remaining_words(limit, draws["total"] if draws else None, short=True)
            + f"; резерв {_rub(limit.get('reserve'))}; по РСС "
            + (f"не хватает {_rub(extra)} {_since(limit.get('additional_financing_from'))}"
               if extra > 0 else "хватает до ввода"), "bad" if extra > 0 else "good")
    else:
        add("Остаток лимита банка", None, "лимит не посчитан")
    if need and need["deficit"] is not None:
        add("Дефицит на достройку", _rub(need["deficit"]) if need["deficit"] > 0 else "нет",
            f"утверждённый бюджет минус оплаченное ({_rub(need['remaining'])}) против "
            f"остатка лимитов и резерва ({_rub(need['fuel'])})",
            "bad" if need["deficit"] > 0 else "good")
    else:
        add("Дефицит на достройку", None, "утверждённый бюджет не загружен")
    queues = ((block.get("escrow") or {}).get("queues") or []) if block else []
    cover = next((q for q in queues if q.get("plan_coverage_at") is not None), None)
    if cover:
        pace_cover = cover.get("keeping_pace_coverage")
        worst = min(v for v in (cover["plan_coverage_at"], pace_cover) if v is not None)
        # Главное — нынешний темп, план финмодели — справкой (владелец,
        # 21.10.2026: «эскроу НЕ покрывает кредит в текущем темпе, это важнее,
        # что по плану 0,95»).
        if pace_cover is not None:
            add("Эскроу при нынешнем темпе", _times(pace_cover),
                ("НЕ покрывает кредит" if pace_cover < 1 else "покрывает кредит")
                + f"; по плану финмодели {_times(cover['plan_coverage_at'])}",
                "bad" if worst < 1 else "good")
        else:
            add("Эскроу покрывает кредит", _times(cover["plan_coverage_at"]),
                "по плану финмодели; темп не посчитан", "bad" if worst < 1 else "good")
    else:
        add("Эскроу покрывает кредит", None, "нет плана кредита или эскроу")

    block = report.get("budget") or {}
    table = block.get("by_budget_article") or {}
    elapsed = (_month_elapsed(_date(block["month"]), end)
               if block.get("state") in {"ok", "partial"} else 0.0)
    over = set(table.get("overrun") or [])
    for key, label in (("construction", "Бюджет стройки"), ("commercial", "Бюджет коммерции")):
        chapter = next((c for c in table.get("chapters") or [] if c["key"] == key), None)
        line = (chapter or {}).get("total") or {}
        if line.get("plan"):
            hit = [row for row in chapter["rows"] if row["key"] in over]
            add(f"{label} за месяц", _pct(line["share"]),
                f"оплачено {_rub(line['fact'])} из {_rub(line['plan'])}; прошло {_pct(elapsed)} месяца"
                + (f"; перерасход по {len(hit)} "
                   f"{_plural(len(hit), 'статье', 'статьям', 'статьям')}" if hit else ""),
                "bad" if hit or line["share"] > elapsed + 0.1 else "")
        else:
            add(f"{label} за месяц", None, "плана месяца нет")
    return out


def _gantt_html(report: dict[str, Any]) -> str:
    block = report.get("gantt") or {}
    out = ["<h3>Сроки работ по корпусам</h3>"]
    if block.get("state") != "ok":
        out.append(f"<p class='note'>{html.escape(block.get('reason') or 'Графика работ нет.')}</p>")
        return "".join(out)
    rnv = report.get("schedule") if (report.get("schedule") or {}).get("state") == "ok" else {}
    out.append(report_gantt.svg(block, report.get("end"), rnv))
    out.extend(f"<p class='note'>{html.escape(line)}</p>"
               for line in report_gantt.notes(block, rnv))
    return "".join(out)


def _tiles_html(items: list[dict[str, str]]) -> str:
    esc = html.escape
    return ("<div class='tiles'>" + "".join(
        f"<div class='tile {esc(item['tone'])}'><div class='k'>{esc(item['label'])}</div>"
        f"<div class='v'>{esc(item['value'])}</div><div class='n'>{esc(item['note'])}</div></div>"
        for item in items) + "</div>")


def _delta(value: float | None) -> str:
    """Отклонение со знаком; меньше рубля — ноль без знака, а не «−0 ₽»."""
    if value is None:
        return "—"
    if abs(value) < 0.5:
        return "0 ₽"
    return ("+" if value > 0 else "") + _rub(value)


def _budget_depth_html(block: dict[str, Any], end: datetime.date) -> str:
    esc = html.escape
    out = []
    forecast = _budget_forecast(block, end)
    if forecast:
        out.append("<h3>Прогноз освоения до конца месяца по нынешнему темпу</h3>")
        out.append(_table(["Строка", "План месяца", "Оплачено", "Прогноз к концу месяца",
                           "Против плана"], [
            [esc(row["label"]), _rub(row["plan"]), _rub(row["fact"]), _rub(row["forecast"]),
             ("+" if row["gap"] >= 0 else "") + _rub(row["gap"])] for row in forecast]))
    trend = block.get("trend") or []
    if any(point["fact"]["construction"] or point["plan"]["construction"] for point in trend):
        def money(value: float | None, gap: str) -> str:
            return gap if value is None else _rub(value)

        divisor, unit = _scale([v for p in trend for v in
                                (p["plan"]["construction"], p["fact"]["construction"])])
        out.append(charts.bar_chart(
            "Стройка и проектирование: план и оплачено по месяцам",
            [_month_short(p["month"][:7]) for p in trend],
            [{"name": "План", "values": charts.scaled(
                [p["plan"]["construction"] for p in trend], divisor)},
             {"name": "Оплачено", "values": charts.scaled(
                 [p["fact"]["construction"] for p in trend], divisor)}], unit, digits=0))
        out.append(_table(["Месяц", "Стройка: план", "Стройка: оплачено",
                           "Коммерция: план", "Коммерция: оплачено"], [
            [_months_label(p["month"]), money(p["plan"]["construction"], "нет плана"),
             money(p["fact"]["construction"], "нет данных"),
             money(p["plan"]["commercial"], "нет плана"),
             money(p["fact"]["commercial"], "нет данных")] for p in trend]))
        out.append("<p class='note'>«Нет данных» — месяц раньше первой оплаты в реестре РСС; "
                   "«нет плана» — месяца нет ни в одном загруженном бюджете.</p>")
    articles = block.get("articles") or {}
    if articles.get("known"):
        if articles.get("chapters"):
            out.append(f"<h3>Бюджет за {_months_label(articles['month'])} по главам</h3>")
            out.append(_table(["Глава бюджета", "План", "Факт", "Отклонение"], [
                [(f"<b>{esc(row['label'])}</b>" if row["key"] == "expenses" else esc(row["label"])),
                 _rub(row.get("plan")), _rub(row.get("fact")),
                 _delta(row["fact"] - row["plan"])
                 if row.get("plan") is not None and row.get("fact") is not None else "—"]
                for row in articles["chapters"]]))
        out.append(f"<h3>Отклонения по статьям бюджета за {_months_label(articles['month'])}</h3>")
        body = [
            [esc(row["article"]), _rub(row.get("plan")),
             "не платили" if row.get("fact_blank") else _rub(row.get("fact")),
             _delta(row.get("delta"))] for row in articles["rows"][:10]]
        # Итог — по всем статьям, а не по показанным десяти (владелец,
        # 22.10.2026: «тут нет нигде итого»).
        every = articles["rows"]
        plan_sum = sum(row["plan"] for row in every if row.get("plan") is not None)
        fact_sum = sum(row["fact"] or 0.0 for row in every)
        body.append(["<b>Итого по статьям</b>", f"<b>{_rub(plan_sum)}</b>",
                     f"<b>{_rub(fact_sum)}</b>", f"<b>{_delta(fact_sum - plan_sum)}</b>"])
        out.append(_table(["Статья", "План", "Факт", "Отклонение"], body))
        out.append("<p class='note'>Плюс — перерасход, минус — недоосвоение. Данные — из "
                   f"план-факта БДДС от {_day(articles['file'])}.</p>")
    elif articles.get("reason"):
        out.append(f"<p class='note'>Отклонения по статьям бюджета: {esc(articles['reason'])}.</p>")
    if block.get("by_article"):
        out.append("<h3>Оплачено с начала месяца по статьям РСС</h3>")
        shown = block["by_article"][:10]
        paid = sum(row["amount"] for row in block["by_article"])
        body = [[f"{esc(row['code'])} {esc(row['name'])}", _rub(row["amount"])] for row in shown]
        rest = paid - sum(row["amount"] for row in shown)
        if abs(rest) >= 0.5:
            body.append([f"Остальные статьи ({len(block['by_article']) - len(shown)})",
                         _rub(rest)])
        body.append(["<b>Итого оплачено с начала месяца</b>", f"<b>{_rub(paid)}</b>"])
        out.append(_table(["Статья РСС", "Оплачено"], body))
    if block.get("recipients"):
        out.append("<h3>Крупнейшие получатели оплат с начала месяца</h3>")
        body = [[esc(row["name"]), _rub(row["amount"])] for row in block["recipients"]]
        top = sum(row["amount"] for row in block["recipients"])
        body.append([f"<b>Итого по {len(block['recipients'])} крупнейшим</b>",
                     f"<b>{_rub(top)}</b>"])
        paid = sum(row["amount"] for row in block.get("by_article") or [])
        if paid > top + 0.5:
            body.append(["Все остальные получатели", _rub(paid - top)])
        out.append(_table(["Контрагент", "Оплачено"], body))
    return "\n".join(out)


def _sales_depth_html(block: dict[str, Any], kind: str) -> str:
    esc = html.escape
    out = []
    products = block.get("products") or []
    if products:
        def price(item: dict[str, Any], scope: str) -> str:
            value = item[scope].get("price")
            if value is None:
                return "—"
            return _rub(value) + (" за лот" if item["measure"] == "units" else " за м²")

        out.append("<h3>По типам помещений</h3>")
        out.append(_table(["Тип", f"За {PERIODS[kind]}: лотов", "м²", "сумма",
                           "С начала продаж: лотов", "м²", "сумма", "Средняя цена",
                           "План ФМ на квартал"], [
            [esc(item["product"]), f"{item['period']['units']:.0f}", _area(item["period"]["area"]),
             _rub(item["period"]["amount"]), f"{item['total']['units']:.0f}",
             _area(item["total"]["area"]), _rub(item["total"]["amount"]), price(item, "total"),
             _rub((item.get("fm_quarter") or {}).get("amount")) if item.get("fm_quarter") else "—"]
            for item in products]))
    out.append(_pace_charts(block.get("pace") or []))
    payments = block.get("payments") or []
    total = sum(item["amount"] for item in payments)
    if payments and total:
        out.append("<h3>Формы оплаты (с начала продаж)</h3>")
        out.append(_table(["Форма оплаты", "Договоров", "Сумма", "Доля"], [
            [esc(item["name"]), str(item["count"]), _rub(item["amount"]),
             _pct(item["amount"] / total)] for item in payments]))
    pool = block.get("pool") or {}
    if pool.get("products"):
        out.append("<h3>Остаток нераспроданного</h3>")
        out.append(_table(["Тип", "Продано лотов", "Всего лотов", "Продано м²", "Всего м²",
                           "Осталось м²"], [
            [esc(p["product"]), f"{p['sold_units']:.0f}",
             f"{p['pool_units']:.0f}" if p.get("pool_units") else "—",
             _area(p["sold_area"]), _area(p["pool_area"]),
             _area(max(0.0, p["pool_area"] - p["sold_area"])) if p["pool_area"] else "—"]
            for p in pool["products"]]))
    elif block.get("state") == "ok":
        out.append("<p class='note'>Остаток нераспроданного не посчитан: в отчёте о продажах "
                   "нет квартирографии или плана финмодели по объёмам.</p>")
    return "\n".join(out)


def _funding_depth_html(report: dict[str, Any]) -> str:
    block = report.get("funding") or {}
    if block.get("state") != "ok":
        return ""
    out = []
    escrow = block.get("escrow") or {}
    if escrow.get("state") == "ok":
        out.append(f"<p class='note'>Поступления на эскроу по графикам договоров: за "
                   f"{_months_label(_date(report['end']).isoformat())} — "
                   f"{_rub(escrow.get('inflow_month'))}, всего — {_rub(escrow.get('inflow_total'))}. "
                   "Поступления видны помесячно, поэтому за неделю их не выделить.</p>")
        end = _date(report["end"]).strftime("%Y-%m")
        months = sorted(m for m in escrow.get("plan_pf") or {} if m <= end
                        and (escrow["plan_pf"].get(m) or 0) > 0)[-18:]
        if months:
            actual = _cumulative(escrow.get("actual_escrow") or {}, months)
            out.append(charts.line_chart(
                "Покрытие кредита эскроу: факт и план по месяцам",
                [_month_short(m) for m in months],
                [{"name": "Факт (эскроу / кредит по плану)",
                  "values": [a / escrow["plan_pf"][m] for a, m in zip(actual, months)]},
                 {"name": "План ФМ", "values": [(escrow["plan_escrow"].get(m) or 0) / escrow["plan_pf"][m]
                                               for m in months]}],
                "раз", digits=2, label_every=charts.every(len(months))))
    limit = block.get("limit") or {}
    if limit.get("known"):
        balance = limit.get("monthly_reserve_balance") or {}
        unfunded = limit.get("monthly_unfunded") or {}
        months = sorted(set(balance) | set(unfunded))[:24]
        if months:
            values = [balance.get(m) for m in months] + [unfunded.get(m) for m in months]
            divisor, unit = _scale(values)
            out.append(charts.line_chart(
                "Резерв и непокрытая потребность по месяцам (расчёт Монитора)",
                [_month_short(m[:7]) for m in months],
                [{"name": "Остаток резерва", "values": charts.scaled(
                    [balance.get(m) for m in months], divisor)},
                 {"name": "Не хватает в месяц", "values": charts.scaled(
                     [unfunded.get(m) for m in months], divisor)}],
                unit, digits=1 if divisor == 1e9 else 0, label_every=charts.every(len(months))))
    return "\n".join(out)


def _scale(values: list[float | None]) -> tuple[float, str]:
    """Делитель и подпись единицы — по величине чисел, одна пара на график."""
    peak = max((abs(v) for v in values if v is not None), default=0.0)
    return (1e9, "млрд ₽") if peak >= 2e9 else (1e6, "млн ₽")


def _physical_chart(block: dict[str, Any]) -> str:
    facts = (block.get("series") or {}).get("fact") or []
    if not facts:
        return ""
    facts = facts[-26:]
    labels = [_date(p["day"]).strftime("%d.%m") for p in facts]
    return charts.line_chart(
        "Выполнение по графику работ: план и факт на дату каждого ГПР-факта",
        labels,
        [{"name": "План", "values": [p["plan"] * 100 if p["plan"] is not None else None
                                     for p in facts]},
         {"name": "Факт", "values": [p["fact"] * 100 if p["fact"] is not None else None
                                     for p in facts]}],
        "%", label_every=charts.every(len(labels)))


def _sales_chart(block: dict[str, Any]) -> str:
    series = block.get("series") or []
    if block.get("state") != "ok" or not series:
        return ""
    values = [q[k] for q in series for k in ("fact", "fm", "bank")]
    divisor, unit = _scale(values)
    labels = [_quarter_name(q["label"]).replace(" квартал ", " кв. ") for q in series]
    lines = [{"name": "Факт", "values": charts.scaled([q["fact"] for q in series], divisor)},
             {"name": "План финмодели", "values": charts.scaled([q["fm"] for q in series], divisor)},
             {"name": "План банка", "values": charts.scaled([q["bank"] for q in series], divisor)}]
    return charts.line_chart("Продажи нарастающим итогом по кварталам, сумма договоров",
                             labels, [line for line in lines if any(
                                 v is not None for v in line["values"])],
                             unit, digits=1 if divisor == 1e9 else 0,
                             label_every=charts.every(len(labels)))


def _cumulative(monthly: dict[str, float], months: list[str]) -> list[float]:
    total = sum(v for m, v in monthly.items() if months and m < months[0])
    out = []
    for month in months:
        total += monthly.get(month, 0.0)
        out.append(total)
    return out


def _funding_chart(report: dict[str, Any]) -> str:
    block = report.get("funding") or {}
    if block.get("state") != "ok":
        return ""
    end = _date(report["end"]).strftime("%Y-%m")
    escrow = block.get("escrow") or {}
    known = (set(block.get("draws_monthly") or {}) | set(escrow.get("actual_escrow") or {})
             | {m for m in (escrow.get("plan_pf") or {}) if m <= end})
    months = sorted(m for m in known if m <= end)[-18:]
    if not months:
        return ""
    lines = [{"name": "Выборка кредита, факт",
              "values": _cumulative(block.get("draws_monthly") or {}, months)}]
    if escrow.get("state") == "ok":
        lines.append({"name": "Кредит по плану ФМ",
                      "values": [escrow["plan_pf"].get(m) for m in months]})
        lines.append({"name": "Эскроу, факт",
                      "values": _cumulative(escrow.get("actual_escrow") or {}, months)})
        lines.append({"name": "Эскроу по плану ФМ",
                      "values": [escrow["plan_escrow"].get(m) for m in months]})
    values = [v for line in lines for v in line["values"]]
    divisor, unit = _scale(values)
    for line in lines:
        line["values"] = charts.scaled(line["values"], divisor)
    return charts.line_chart("Выборка кредита и эскроу нарастающим итогом по месяцам",
                             [_month_short(m) for m in months], lines, unit,
                             digits=1 if divisor == 1e9 else 0,
                             label_every=charts.every(len(months)))


def _month_short(key: str) -> str:
    return f"{key[5:7]}.{key[2:4]}"


def _budget_chart(block: dict[str, Any]) -> str:
    if block.get("state") not in {"ok", "partial"}:
        return ""
    lines = block.get("lines") or []
    divisor, unit = _scale([v for line in lines for v in (line.get("plan"), line["fact"])])
    return charts.bar_chart(
        f"Бюджет на {_months_label(block['month'])}: план и оплачено по статьям",
        [line["label"] for line in lines],
        [{"name": "План", "values": charts.scaled([line.get("plan") for line in lines], divisor)},
         {"name": "Оплачено", "values": charts.scaled([line["fact"] for line in lines], divisor)}],
        unit, digits=1) + "".join(
            f"<p class='note'>{html.escape(line['label'])}: {html.escape(line['note'])}.</p>"
            for line in lines if line.get("note") and line.get("plan") is not None)


# Блоки документа по порядку владельца: ключ якоря и заголовок. Содержание,
# заголовки и якоря берут этот список — второй перечень разошёлся бы с первым.
BLOCKS = (
    ("main", "Главное за период"),
    ("build", "Стройка"),
    ("sales", "Продажи"),
    ("funding", "Финансирование"),
    ("budget", "Бюджет месяца"),
    ("legal", "Споры и претензии"),
    ("info", "Общая информация"),
)


def _block_heading(key: str) -> str:
    """Заголовок блока с якорем; в документе блок начинается с новой страницы."""
    title = dict(BLOCKS)[key]
    # «Главное» остаётся на первой странице под плитками (решение владельца об
    # оформлении); остальные блоки — каждый с новой страницы.
    classes = "block first" if key == BLOCKS[0][0] else "block"
    return f"<h2 class='{classes}' id='block-{key}'>{html.escape(title)}</h2>"


def _toc_html() -> str:
    """Содержание — в начале документа (владелец, 22.10.2026: «а в начало
    содержание?»). Номеров страниц нет: Chromium при печати их не считает, а
    блоки идут в этом же порядке, каждый с новой страницы; строки — ссылки."""
    return ("<ol class='toc'>" + "".join(
        f"<li><a href='#block-{key}'>{html.escape(title)}</a></li>" for key, title in BLOCKS)
        + "</ol>")


def render_html(report: dict[str, Any]) -> str:
    """Тело документа сводки — те же числа, что в сообщении, таблицами."""
    esc = html.escape
    out = [f"<h1>Сводка по проекту «{esc(report['project'])}»</h1>",
           f"<div class='sub'>{esc(_title(report))}</div>", _toc_html()]

    def missing(block: dict[str, Any]) -> str:
        return f"<p class='missing'>{esc(block.get('reason') or 'Данных нет.')}</p>"

    out.append(_tiles_html(tiles(report)))
    out.append(_block_heading("main") + "<ul class='findings'>")
    for item in report.get("findings") or []:
        tone = f" {item['tone']}" if item.get("tone") else ""
        source = (f" <span class='source'>Источник: {esc(item['source'])}.</span>"
                  if item.get("source") else "")
        out.append(f"<li class='finding{tone}'><b>{esc(item['topic'])}.</b> "
                   f"{esc(item['text'])}{source}</li>")
    out.append("</ul>")

    out.append(_block_heading("build"))
    block = report.get("physical") or {}
    if block.get("state") == "ok":
        out.append(_table(["", "План к дате", "Выполнено", "Отставание"], [[
            "Весь проект", _pct(block["plan"]), _pct(block["fact"]),
            _pp(block["fact"] - block["plan"]) if block.get("plan") is not None else "—"]]
            + [[esc(item["object"]), _pct(item["plan"]), _pct(item["fact"]),
                _pp(item["fact"] - item["plan"]) if item.get("plan") is not None else "—"]
               for item in block.get("objects") or []]))
        if block.get("delta") is not None:
            out.append(f"<p class='note'>За {PERIODS[report['kind']]} выполнение "
                       f"{'выросло' if block['delta'] >= 0 else 'снизилось'} на "
                       f"{_pp(abs(block['delta']))[1:]}</p>")
        else:
            out.append("<p class='note'>Прирост за период посчитать не из чего: на начало "
                       "периода не было графика с процентами выполнения.</p>")
        notes = _physical_notes(block)
        out.append(f"<p class='note'>{esc(notes[0])}</p>")
        out.extend(f"<p class='note warn'>{esc(line)}</p>" for line in notes[1:])
        out.append(_physical_chart(block))
        out.append(_breakdown_html(block.get("breakdown") or {}, report["kind"]))
    else:
        out.append(missing(block))
    out.append("<h3>Люди на площадке</h3>")
    out.append(_crew_html(report.get("crew") or {}, report["kind"]))
    out.append(_works_html(report.get("crew") or {}, report["kind"]))
    out.append(_gantt_html(report))
    block = report.get("schedule") or {}
    if block.get("state") == "ok" and block.get("forecast"):
        delay = block.get("delay_days")
        lead = (f"по утверждённому графику {_day(block['approved'])}, "
                if block.get("approved") else "утверждённого срока в данных нет, ")
        out.append(f"<p class='note'>Ввод: {lead}прогноз Монитора при нынешнем темпе "
                   f"{_day(block['forecast'])}"
                   + (f" — на {delay:.0f} дн. позже." if isinstance(delay, (int, float))
                      and delay > 0 else ".") + "</p>")
        if block.get("stalled"):
            out.append(f"<p class='note warn'>{html.escape(_stalled_words(block))}</p>")

    out.append(_photos_html(report.get("photos") or {}, report["kind"]))

    out.append(_block_heading("sales"))
    block = report.get("sales") or {}
    if block.get("state") == "ok":
        def fact_cells(fact: dict[str, Any]) -> list[str]:
            return [str(fact["contracts"]), _rub(fact["amount"]), _area(fact["area"]),
                    _pieces(fact) or "—",
                    _rub(fact.get("price_flats")) if fact.get("price_flats") else "—"]

        month, quarter = block["month"], block["quarter"]
        rows = [[f"За {PERIODS[report['kind']]}", *fact_cells(block["period"])]]
        if report["kind"] != "month":
            rows.append([f"С начала месяца ({_month_name(month['key'])})",
                         *fact_cells(month["fact"])])
        rows.append([f"С начала квартала ({_quarter_name(quarter['key'])})",
                     *fact_cells(quarter["fact"])])
        out.append(_table(["Факт", "Договоров", "Сумма", "Площадь квартир и помещений",
                           "Машиноместа и кладовые", "Цена квартир, ₽/м²"], rows))
        plans = []
        if month.get("fm"):
            plans.append(["План финмодели на месяц", _rub(month["fm"]["amount"]),
                          _area(month["fm"]["area"])])
        if quarter.get("fm"):
            plans.append(["План финмодели на квартал", _rub(quarter["fm"]["amount"]),
                          _area(quarter["fm"]["area"])])
        if quarter.get("bank"):
            plans.append(["План банка на квартал", _rub(quarter["bank"]["amount"]),
                          _area(quarter["bank"].get("area"))])
        if plans:
            out.append(_table(["План", "Сумма", "Площадь"], plans))
        if quarter.get("bank_reason"):
            out.append(f"<p class='note'>{esc(quarter['bank_reason'])}</p>")
        if block.get("stale"):
            out.append(f"<p class='note warn'>Договоры загружены {_day(block['uploaded'])}, "
                       "более поздние сделки в сводку не попали.</p>")
    else:
        out.append(missing(block))

    out.append(_sales_chart(report.get("sales") or {}))
    if (report.get("sales") or {}).get("state") == "ok":
        out.append(_sales_depth_html(report["sales"], report["kind"]))

    out.append(_block_heading("funding"))
    out.append(_funding_html(report))
    out.append(_funding_chart(report))
    out.append(_funding_depth_html(report))

    block = report.get("budget") or {}
    if block.get("state") in {"ok", "partial"}:
        month = _date(block["month"])
        elapsed = _month_elapsed(month, _date(report["end"]))
        # Заголовок, подпись и таблица статей — одним куском: заголовок внизу
        # страницы без таблицы под ним читается как пустой раздел.
        out.append("<div class='keep'>" + _block_heading("budget")
                   + f"<div class='sub'>{_MONTHS[month.month - 1]} {month.year}: план — "
                   f"план-факт БДДС, оплачено — реестр платежей РСС на "
                   f"{_day(report['end'])}; прошло {_pct(elapsed)} месяца</div>"
                   + _budget_articles_html(block.get("by_budget_article") or {}) + "</div>")
        if block.get("reason"):
            out.append(f"<p class='note warn'>{esc(block['reason'])}</p>")
        out.append(f"<p class='note'>Оплаты — из отчёта РСС от {_day(block['rss'])}.</p>")
    else:
        out.append(_block_heading("budget"))
        out.append(missing(block))

    out.append(_budget_chart(report.get("budget") or {}))
    if (report.get("budget") or {}).get("state") in {"ok", "partial"}:
        out.append(_budget_depth_html(report["budget"], _date(report["end"])))

    out.append(_block_heading("legal"))
    out.append(_legal_html(report.get("legal") or {}))
    out.append(_block_heading("info"))
    block = report.get("notes") or {}
    if block.get("state") != "ok":
        out.append(missing(block))
    elif not block.get("open") and not block.get("closed"):
        out.append("<p class='note'>Открытых вопросов нет, за период записей не было.</p>")
    else:
        for note in block.get("open") or []:
            mark = " (новое)" if note.get("changed") else ""
            out.append(f"<div class='item'><b>{esc(note['topic'])}</b>{mark}: "
                       f"{esc(note['text'])} <span class='note'>— {_day(note['at'])}, "
                       f"{esc(note['author'])}</span></div>")
        for note in block.get("closed") or []:
            out.append(f"<div class='item'><b>{esc(note['topic'])}</b> — вопрос закрыт: "
                       f"{esc(note['text'])} <span class='note'>— {_day(note['at'])}, "
                       f"{esc(note['author'])}</span></div>")
    return "\n".join(_keep_headings([part for part in out if part]))


def _claims_words(card: dict[str, Any], direction: str) -> str:
    items = [claim for claim in card["claims"] if claim["direction"] == direction]
    return "; ".join(f"{claim['label']} — {_rub(claim['amount'])}"
                     + (" (растёт)" if claim["growing"] else "") for claim in items)


LEGAL_UNCHECKED = ("(Внесено по документам владельца, юрист ещё не проверил — "
                   "проверьте и подтвердите на странице сводки.)")

LEGAL_EMPTY = ("Споры в реестр пока не внесены, поэтому в сводке их нет. Загрузите "
               "документы спора на странице сводки, проверьте карточку, которую "
               "предложит Платон, и подтвердите её.")
LEGAL_NONE_OPEN = "Открытых споров нет, за период ни один спор не закрыт."


def _legal_lines(block: dict[str, Any]) -> list[str]:
    """Споры для сообщения: строка на спор, события за период."""
    esc = html.escape
    if block.get("state") != "ok":
        return [esc(block.get("reason") or "Реестр споров не собран.")] if block else []
    if not block.get("recorded"):
        return [LEGAL_EMPTY]
    if not block.get("open") and not block.get("closed"):
        return [LEGAL_NONE_OPEN]
    names = block.get("statuses") or {}
    out = []
    for item in (block.get("open") or []) + (block.get("closed") or []):
        card, totals = item["card"], item["totals"]
        line = (f"• <b>Спор: {esc(card['counterparty'])}</b>"
                + (f" ({esc(card['contract'])})" if card["contract"] else "")
                + (f", дело {esc(card['court_case'])}" if card.get("court_case") else "")
                + f" — {esc(names.get(card['status'], card['status']).lower())}. "
                + (esc(_sentence(card["subject"])) if card["subject"] else ""))
        if totals["to_them"]:
            line += f" Наши требования: {_rub(totals['to_them'])}."
        if totals["to_us"]:
            line += f" Требования к нам: {_rub(totals['to_us'])}."
        if card["next_step"]:
            line += (f" Дальше: {esc(_sentence(card['next_step']))}"
                     + (f" Срок — {_day(card['deadline'])}." if card["deadline"] else ""))
        if item.get("unchecked"):
            line += " " + LEGAL_UNCHECKED
        out.append(line)
    return out


def _legal_html(block: dict[str, Any]) -> str:
    """Споры и претензии: по блоку на спор — суть, требования, что дальше, события."""
    esc = html.escape
    if block.get("state") != "ok":
        return f"<p class='missing'>{esc(block.get('reason') or 'Реестр споров не собран.')}</p>"
    items = (block.get("open") or []) + (block.get("closed") or [])
    if not block.get("recorded"):
        return f"<p class='missing'>{esc(LEGAL_EMPTY)}</p>"
    if not items:
        return f"<p>{esc(LEGAL_NONE_OPEN)}</p>"
    names = block.get("statuses") or {}
    out = []
    for item in items:
        card, totals = item["card"], item["totals"]
        rows = []
        for direction, label in (("to_them", "Наши требования"), ("to_us", "Требования к нам")):
            claims = [claim for claim in card["claims"] if claim["direction"] == direction]
            if claims:
                rows.append([label + (f", всего {_rub(totals[direction])}"
                                      if len(claims) > 1 else ""),
                             "<br>".join(f"{esc(claim['label'])} — {_rub(claim['amount'])}"
                                         + (" <b>(растёт)</b>" if claim["growing"] else "")
                                         for claim in claims)])
        if card["next_step"] or card["deadline"]:
            rows.append(["Что дальше", esc(card["next_step"] or "—")
                         + (f" — <b>до {_day(card['deadline'])}</b>" if card["deadline"] else "")])
        if item["fresh"]:
            rows.append(["За период", "<br>".join(
                f"{_day(event['date'])} — {esc(event['summary'])}"
                + (f" ({esc(event['document'])})" if event["document"] else "")
                for event in item["fresh"])])
        if card["position"]:
            rows.append(["Позиция и риск", esc(card["position"])])
        out.append(
            f"<div class='item'><b>{esc(card['counterparty'])}</b>"
            + (f" · {esc(card['contract'])}" if card["contract"] else "")
            + (f" · дело {esc(card['court_case'])}" if card.get("court_case") else "")
            + (f" · наша сторона: {esc(card['our_side'])}" if card.get("our_side") else "")
            + f" · <b>{esc(names.get(card['status'], card['status']))}</b>"
            + (f"<br>{esc(card['subject'])}" if card["subject"] else "")
            + (f"<br><i>{esc(LEGAL_UNCHECKED)}</i>" if item.get("unchecked") else "") + "</div>"
            + "<table class='legal'>" + "".join(_row(row) for row in rows) + "</table>")
    return "".join(out)


def _keep_headings(parts: list[str]) -> list[str]:
    """Заголовок раздела — вместе с первым блоком под ним, чтобы не висел внизу страницы."""
    out: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        if part.startswith("<h2") and part.endswith("</h2>") and index + 1 < len(parts):
            out.append(f"<div class='keep'>{part}{parts[index + 1]}</div>")
            index += 2
            continue
        out.append(part)
        index += 1
    return out
