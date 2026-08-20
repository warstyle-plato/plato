"""Management aggregation for Project Monitor.

The operating contract stays deliberately small: a fixed PM/GPR baseline and
one fresh RSS 6.1.2 every week.

Physical progress is read only from ``Реестр выполненных работ``. Payment fact
is read only from ``Реестр платежей``. The RSS/DevelopAid crosswalk is used for
hierarchy and naming only; it never becomes physical fact.

The director view is hierarchical:
    control block -> DevelopAid article -> RSS code -> WBS tasks.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor

_INSTALLED = False
_ORIGINAL_BUILD = None
_ORIGINAL_GANTT = None


def _natural(value: Any) -> tuple:
    """Natural ordering: 2.2.3.9 comes before 2.2.3.10."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.findall(r"\d+|[^\d]+", str(value or ""))
    )


def _as_date(value: Any) -> datetime.date | None:
    """Dates from the base Monitor can already be JSON/plain ISO strings."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return monitor._day(value)


def _codes(value: Any) -> list[str]:
    return list(dict.fromkeys(
        item.rstrip(".")
        for item in re.findall(r"\d+(?:\.\d+)+", str(value or ""))
    ))


def _control(code: str) -> str:
    if code.startswith("2.1"):
        return "Подготовка"
    if code.startswith(("2.2", "2.3")):
        return "Основные объекты"
    if code.startswith("2.4"):
        return "Наружные сети"
    if code.startswith("2.5"):
        return "Благоустройство"
    if code.startswith("2.6"):
        return "Служба заказчика"
    if code.startswith("2.7"):
        return "Проектирование"
    if code.startswith(("2.8", "2.9")):
        return "Резерв"
    return "Прочие СМР"


def _detail(code: str) -> str:
    if code.startswith("2.1"):
        return "Подготовительные работы"
    if code.startswith("2.2.1"):
        return "Основное строительство — подземная часть"
    if code.startswith(("2.2.2", "2.2.3", "2.3")):
        return "Основное строительство — надземная часть + ВИС"
    if code.startswith("2.4"):
        return "Наружные инженерные сети"
    if code.startswith("2.5"):
        return "Благоустройство"
    return _control(code)


def _baseline_mapping(project: str) -> dict[str, dict[str, str]]:
    """Read RSS -> DevelopAid naming from Project Control's ``РСС ФАКТ``.

    This is a crosswalk only. Values from this sheet are never used as the
    physical fact for the Gantt.
    """
    path = monitor._baseline_file(project)
    if path is None:
        return {}

    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if "РСС ФАКТ" not in workbook.sheetnames:
            return {}
        result: dict[str, dict[str, str]] = {}
        header: dict[str, int] = {}
        for values in workbook["РСС ФАКТ"].iter_rows(values_only=True):
            normalized = [
                re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))
                for value in values
            ]
            if not header and "код рсс" in normalized and "статья developaid" in normalized:
                header = {
                    "code": normalized.index("код рсс"),
                    "article": normalized.index("статья developaid"),
                }
                if "статья рсс" in normalized:
                    header["rss_name"] = normalized.index("статья рсс")
                continue
            if not header:
                continue

            code_index = header["code"]
            code = actuals._code(values[code_index] if code_index < len(values) else None)
            if not code:
                continue
            article_index = header["article"]
            article = (
                str(values[article_index] or "").strip()
                if article_index < len(values) else ""
            )
            rss_index = header.get("rss_name", -1)
            rss_name = (
                str(values[rss_index] or "").strip()
                if 0 <= rss_index < len(values) else ""
            )
            low = article.lower().replace("ё", "е")
            detail = _detail(code)
            if "подзем" in low:
                detail = "Основное строительство — подземная часть"
            elif "надзем" in low or "назем" in low or "вис" in low:
                detail = "Основное строительство — надземная часть + ВИС"
            elif "подготов" in low:
                detail = "Подготовительные работы"
            elif "наруж" in low:
                detail = "Наружные инженерные сети"
            elif "благо" in low:
                detail = "Благоустройство"
            result[code] = {
                "rss_name": rss_name,
                "detail": detail,
                "control": _control(code),
            }
        return result
    finally:
        workbook.close()


def _descendants(estimate: dict[str, Any], root: str) -> set[str]:
    children: dict[str, set[str]] = {}
    for row in estimate["rows"]:
        parent = str(row.get("parent") or "")
        if parent:
            children.setdefault(parent, set()).add(row["code"])
    selected: set[str] = set()
    stack = [root]
    while stack:
        code = stack.pop()
        if code in selected:
            continue
        selected.add(code)
        stack.extend(children.get(code, ()))
    return selected


def _metrics(
    estimate: dict[str, Any],
    works: dict[str, Any],
    code: str,
    cut: datetime.date,
) -> dict[str, Any]:
    """Physical fact for one RSS article, strictly from accepted-work rows."""
    matched = _descendants(estimate, code)
    eac = float((estimate["by_code"].get(code) or {}).get("estimate") or 0.0)
    rows = [
        row for row in works["rows"]
        if row.get("construction")
        and row.get("code") in matched
        and row.get("date")
        and row["date"] <= cut
    ]
    accepted = sum(float(row.get("amount") or 0.0) for row in rows)
    recent = sum(
        float(row.get("amount") or 0.0)
        for row in rows
        if row["date"] > cut - datetime.timedelta(days=92)
    )
    return {
        "eac": eac,
        "accepted": accepted,
        "progress": accepted / eac if eac > 0 else None,
        "rate": recent / eac / 3 if eac > 0 else None,
        "last": max((row["date"] for row in rows), default=None),
    }


def _status(
    start: datetime.date,
    finish: datetime.date,
    cut: datetime.date,
    plan: float,
    fact: float | None,
    rate: float | None,
    forecast: datetime.date | None,
) -> str:
    if cut < start:
        return "ПО ПЛАНУ: НЕ НАЧАТО"
    if fact is None:
        return "НЕТ ДАННЫХ РСС"
    if fact >= 1:
        return "ЗАВЕРШЕНО"
    if (not rate or rate <= 1e-9) and fact < plan:
        return "НЕТ ТЕМПА / РИСК"
    if forecast and forecast > finish:
        return "ОТСТАВАНИЕ"
    return "В СРОК" if fact >= plan else "ОТСТАВАНИЕ"


def _forecast(
    cut: datetime.date,
    fact: float | None,
    rate: float | None,
    last: datetime.date | None,
) -> datetime.date | None:
    if fact is None:
        return None
    if fact >= 1:
        return last or cut
    if rate and rate > 1e-9:
        days = round((1 - max(0.0, fact)) / rate * 30.4375)
        return cut + datetime.timedelta(days=days)
    return None


def _summary(
    children: list[dict[str, Any]],
    cut: datetime.date,
    name: str,
    key: str,
    level: str,
) -> dict[str, Any]:
    start = min(_as_date(item["plan_start"]) for item in children)
    finish = max(_as_date(item["plan_finish"]) for item in children)
    if start is None or finish is None:
        raise ValueError("в baseline отсутствуют даты управленческого блока")

    eac = sum(float(item.get("eac") or 0.0) for item in children)
    if eac > 0:
        plan = sum(
            float(item.get("plan_progress") or 0.0) * float(item.get("eac") or 0.0)
            for item in children
        ) / eac
        accepted = sum(float(item.get("accepted") or 0.0) for item in children)
        fact = accepted / eac
        recent = sum(
            float(item.get("rate_3m") or 0.0) * float(item.get("eac") or 0.0) * 3
            for item in children
        )
        rate = recent / eac / 3
    else:
        plan = sum(float(item.get("plan_progress") or 0.0) for item in children) / max(1, len(children))
        accepted = 0.0
        fact = None
        rate = None

    forecasts = [
        _as_date(item.get("forecast_finish"))
        for item in children
        if _as_date(item.get("forecast_finish")) is not None
    ]
    forecast = max(forecasts) if forecasts else None
    status = _status(start, finish, cut, plan, fact, rate, forecast)
    if (
        any(item.get("status") == "НЕТ ТЕМПА / РИСК" for item in children)
        and status not in {"ЗАВЕРШЕНО", "ПО ПЛАНУ: НЕ НАЧАТО"}
    ):
        status = "НЕТ ТЕМПА / РИСК"

    duration = max(1, (finish - start).days)
    fact_date = (
        start + datetime.timedelta(days=round(duration * min(max(fact or 0.0, 0.0), 1.0)))
        if fact is not None else None
    )
    return {
        "key": key,
        "level": level,
        "name": name,
        "plan_start": start,
        "plan_finish": finish,
        "plan_progress": plan,
        "actual_progress": fact,
        "actual_equivalent_date": fact_date,
        "accepted": accepted,
        "eac": eac,
        "rate_3m": rate,
        "forecast_finish": forecast,
        "delta_days": (forecast - finish).days if forecast else None,
        "status": status,
        "children": children,
    }


def _management(
    project: str,
    rss: Path,
    schedule: dict[str, Any],
) -> list[dict[str, Any]]:
    estimate = actuals.read_estimate(rss)
    works = actuals.read_completed_works(rss)
    mapping = _baseline_mapping(project)
    cut = _as_date(schedule.get("cut"))
    if cut is None:
        raise ValueError("не задана дата среза")

    # The base Monitor serializes its result before returning it, so dates here
    # may be ISO strings. Normalize once before any duration arithmetic.
    tasks_by_code: dict[str, list[dict[str, Any]]] = {}
    for raw_task in schedule.get("rows") or []:
        task = dict(raw_task)
        start = _as_date(task.get("plan_start"))
        finish = _as_date(task.get("plan_finish"))
        if start is None or finish is None:
            continue
        task["plan_start"] = start
        task["plan_finish"] = finish
        task["forecast_finish"] = _as_date(task.get("forecast_finish"))
        task["actual_equivalent_date"] = _as_date(task.get("actual_equivalent_date"))
        for code in _codes(task.get("code")):
            tasks_by_code.setdefault(code, []).append(task)

    rss_rows: list[dict[str, Any]] = []
    for code, tasks in tasks_by_code.items():
        start = min(task["plan_start"] for task in tasks)
        finish = max(task["plan_finish"] for task in tasks)
        metrics = _metrics(estimate, works, code, cut)
        weights = [
            max(1, (task["plan_finish"] - task["plan_start"]).days)
            for task in tasks
        ]
        plan = sum(
            float(task.get("plan_progress") or 0.0) * weight
            for task, weight in zip(tasks, weights)
        ) / sum(weights)
        forecast = _forecast(cut, metrics["progress"], metrics["rate"], metrics["last"])
        meta = mapping.get(code, {})
        duration = max(1, (finish - start).days)
        fact_date = (
            start + datetime.timedelta(
                days=round(duration * min(max(metrics["progress"] or 0.0, 0.0), 1.0))
            )
            if metrics["progress"] is not None else None
        )
        rss_rows.append({
            "key": f"rss:{code}",
            "level": "rss",
            "code": code,
            "name": (
                meta.get("rss_name")
                or (estimate["by_code"].get(code) or {}).get("article")
                or code
            ),
            "control": meta.get("control") or _control(code),
            "detail": meta.get("detail") or _detail(code),
            "plan_start": start,
            "plan_finish": finish,
            "plan_progress": plan,
            "actual_progress": metrics["progress"],
            "actual_equivalent_date": fact_date,
            "accepted": metrics["accepted"],
            "eac": metrics["eac"],
            "rate_3m": metrics["rate"],
            "forecast_finish": forecast,
            "delta_days": (forecast - finish).days if forecast else None,
            "status": _status(
                start, finish, cut, plan, metrics["progress"], metrics["rate"], forecast
            ),
            "children": tasks,
        })

    rss_rows.sort(key=lambda item: _natural(item["code"]))

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rss_rows:
        buckets.setdefault((row["control"], row["detail"]), []).append(row)

    details: list[dict[str, Any]] = []
    for (control, detail), children in buckets.items():
        item = _summary(children, cut, detail, f"detail:{control}:{detail}", "detail")
        item["control"] = control
        item["sort_code"] = min((child["code"] for child in children), key=_natural)
        details.append(item)
    details.sort(key=lambda item: _natural(item["sort_code"]))

    control_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in details:
        control_buckets.setdefault(row["control"], []).append(row)

    controls: list[dict[str, Any]] = []
    for control, children in control_buckets.items():
        item = _summary(children, cut, control, f"control:{control}", "control")
        item["sort_code"] = min(
            (child["sort_code"] for child in children),
            key=_natural,
        )
        controls.append(item)
    controls.sort(key=lambda item: _natural(item["sort_code"]))
    return controls


def _payment_baseline(project: str) -> dict[str, Any]:
    """Read project/control Plan from fixed ``CF ПЛАН-ФАКТ`` baseline."""
    from openpyxl import load_workbook

    folder = monitor._project_dir(project) / "baseline"
    for path in (folder / "finance.xlsx", folder / "gpr.xlsx"):
        if not path.exists():
            continue
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            if "CF ПЛАН-ФАКТ" not in workbook.sheetnames:
                continue
            rows = list(workbook["CF ПЛАН-ФАКТ"].iter_rows(values_only=True))
            plan_row = None
            date_row = None
            total_row = None
            for index, row in enumerate(rows):
                normalized = [
                    str(value or "").strip().lower().replace("ё", "е")
                    for value in row
                ]
                if plan_row is None and normalized.count("план") >= 2:
                    plan_row = index
                    for prior in range(index - 1, max(-1, index - 6), -1):
                        if sum(
                            isinstance(value, (datetime.date, datetime.datetime))
                            for value in rows[prior]
                        ) >= 2:
                            date_row = prior
                            break
                if row and str(row[0] or "").strip().lower() == "итого проект":
                    total_row = index
            if plan_row is None or date_row is None or total_row is None:
                continue

            dates: dict[int, datetime.date] = {}
            last = None
            for column, value in enumerate(rows[date_row]):
                if isinstance(value, datetime.datetime):
                    last = value.date().replace(day=1)
                elif isinstance(value, datetime.date):
                    last = value.replace(day=1)
                if last:
                    dates[column] = last
            plan_columns = [
                column for column, value in enumerate(rows[plan_row])
                if str(value or "").strip().lower() == "план"
            ]

            def series(row: tuple[Any, ...]) -> dict[str, float]:
                result: dict[str, float] = {}
                for column in plan_columns:
                    month = dates.get(column)
                    if month is None:
                        continue
                    value = actuals._money(row[column] if column < len(row) else None)
                    result[month.isoformat()] = value * (
                        1e6 if abs(value) < 100_000 else 1.0
                    )
                return result

            total = series(rows[total_row])
            by_article: dict[str, dict[str, float]] = {}
            for row in rows[plan_row + 1:total_row]:
                label = str(row[0] or "").strip() if row else ""
                if label:
                    by_article[label] = series(row)
            if total:
                return {
                    "known": True,
                    "series": total,
                    "by_article": by_article,
                }
        finally:
            workbook.close()
    return {"known": False, "series": {}, "by_article": {}}


def _payments(project: str, rss: Path) -> dict[str, Any]:
    """Payment fact, strictly from the current RSS payment register."""
    baseline = _payment_baseline(project)
    payments = actuals.read_payments(rss)
    total_fact: dict[str, float] = {}
    article_fact: dict[str, dict[str, float]] = {}
    code_fact: dict[str, dict[str, float]] = {}

    for row in payments["rows"]:
        date = row.get("date")
        if not date:
            continue
        month = date.replace(day=1).isoformat()
        amount = float(row.get("amount") or 0.0)
        code = str(row.get("estimate_code") or "").rstrip(".")
        article = _control(code) if code else "Не сопоставлено"
        total_fact[month] = total_fact.get(month, 0.0) + amount
        article_fact.setdefault(article, {})
        article_fact[article][month] = article_fact[article].get(month, 0.0) + amount
        if code:
            code_fact.setdefault(code, {})
            code_fact[code][month] = code_fact[code].get(month, 0.0) + amount

    months = sorted(set(total_fact) | set(baseline["series"]))
    rows: list[dict[str, Any]] = []
    for month in months:
        plan = (
            float(baseline["series"].get(month, 0.0))
            if baseline["known"] else None
        )
        fact = float(total_fact.get(month, 0.0))
        rows.append({
            "month": month,
            "plan": plan,
            "fact": fact,
            "delta": fact - plan if plan is not None else None,
        })

    articles: list[dict[str, Any]] = []
    for name in sorted(set(baseline["by_article"]) | set(article_fact)):
        plan_series = baseline["by_article"].get(name, {})
        fact_series = article_fact.get(name, {})
        articles.append({
            "article": name,
            "plan": plan_series,
            "fact": fact_series,
            "plan_total": sum(plan_series.values()),
            "fact_total": sum(fact_series.values()),
        })

    return {
        "known": baseline["known"],
        "source": "CF ПЛАН-ФАКТ" if baseline["known"] else "",
        "rows": rows,
        "plan_total": (
            sum(baseline["series"].values()) if baseline["known"] else None
        ),
        "fact_total": sum(total_fact.values()),
        "last_fact": monitor._iso(payments.get("last")),
        "articles": articles,
        "by_code_fact": code_fact,
        "fact_source": "Реестр платежей",
    }


def _attach_payments(nodes: list[dict[str, Any]], cash: dict[str, Any]) -> None:
    by_article = {item["article"]: item for item in cash.get("articles", [])}
    by_code = cash.get("by_code_fact", {})

    def visit(node: dict[str, Any]) -> None:
        if node.get("level") == "control":
            item = by_article.get(node["name"], {})
            node["payments"] = {
                "plan": item.get("plan", {}),
                "fact": item.get("fact", {}),
                "plan_total": item.get("plan_total"),
                "fact_total": item.get("fact_total", 0.0),
            }
        elif node.get("level") == "rss":
            fact = by_code.get(node.get("code", ""), {})
            node["payments"] = {
                "plan": {},
                "fact": fact,
                "plan_total": None,
                "fact_total": sum(fact.values()),
            }
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("level"):
                visit(child)

    for node in nodes:
        visit(node)


def _build(
    project: str,
    cut: Any,
    programme: dict[str, Any] | None = None,
    upto: str = "",
) -> dict[str, Any]:
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    rss = monitor._latest(project, "estimate", ".xlsx", upto)
    if rss is None:
        return view

    management = _management(project, rss, view["schedule"])
    cash = _payments(project, rss)
    _attach_payments(management, cash)
    view["schedule"]["management"] = monitor._plain(management)
    view["schedule"]["fact_source"] = "Реестр выполненных работ"
    view["payments"] = monitor._plain(cash)

    works = actuals.read_completed_works(rss)
    # The headline physical number must use the same source as the Gantt, not
    # the aggregate "completed" cell from the estimate sheet.
    view["money"]["accepted"] = float(works.get("construction_dated") or 0.0)
    view["money"]["payment_fact"] = float(cash.get("fact_total") or 0.0)
    return view


def _gantt(project: str, cut: Any, upto: str = "") -> dict[str, Any]:
    view = _build(project, cut, upto=upto)
    schedule = view["schedule"]
    return {
        "cut": view["cut"],
        "management": schedule.get("management", []),
        "rows": schedule.get("rows", []),
        "works": len(schedule.get("rows", [])),
        "overdue": schedule.get("risks", 0),
        "baseline_end": schedule.get("baseline_end"),
        "forecast_end": schedule.get("forecast_end"),
        "source": {
            "schedule": "fixed-baseline",
            "estimate": view["source"]["estimate"],
            "with_baseline": True,
            "fact": "Реестр выполненных работ",
            "payments": "Реестр платежей",
        },
    }


def install() -> None:
    """Install the manager view once while preserving the base Monitor API."""
    global _INSTALLED, _ORIGINAL_BUILD, _ORIGINAL_GANTT
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    _ORIGINAL_GANTT = monitor.gantt
    monitor.build = _build
    monitor.gantt = _gantt
    _INSTALLED = True
