"""Work and RNV forecast from the GPR alone (PM is off, money pace is not used).

Owner's decisions:

* PM is not a source; nothing is carried along PM chains.
* A work's forecast comes from its own pace: natural quantities of cumulative
  KS where the work is bound to them (``ks`` argument), otherwise the growth of
  its percent across dated GPR records (approved GPR, weekly GPR files and
  manual decisions in Monitor). No growth with the deadline passed means the
  work stands still and gets no date; a work still within its plan keeps it.
* RNV is the GPR plan; its forecast is the latest forecast of the GPR works
  that carry an RSS estimate article (construction works), marked as an
  estimate without the chain up to the permit. Works without an article
  (sales, petitions, management tasks) do not enter it.

Pace window mirrors the cumulative rule: records within the last 90 days, the
latest no older than 45 days. Missing evidence stays unknown with its reason.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

import developaid_monitor as monitor

WINDOW_DAYS = 90
STALE_DAYS = 45
DONE = 0.999
_CACHE: dict[tuple, dict[str, tuple[float | None, str]]] = {}


def _day(value: Any) -> dt.date | None:
    return monitor._day(value)


def _progress(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    # Same reading as manager._baseline_status: a file may store 60 or 0.6.
    number = number / 100.0 if number > 1.0 else number
    return number if 0.0 <= number <= 1.0 else None


def _works(parsed: dict) -> dict[str, tuple[float | None, str]]:
    out, duplicates = {}, set()
    for item in parsed.get("works") or []:
        tid = str(item.get("id") or item.get("wbs") or "").strip()
        if tid:
            if tid in out:
                duplicates.add(tid)
            progress, status = _progress(item.get("progress")), str(item.get("status") or "")
            # A dated, explicit completion status is a source fact. It is
            # interpreted once here for baseline, weekly and report readers.
            if item.get("progress") is None and "заверш" in status.lower():
                progress = 1.0
            out[tid] = (progress, status)
    for tid in duplicates:
        out.pop(tid, None)
    return out


def _weekly(project: str, path: Path) -> dict[str, tuple[float | None, str]]:
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        data = path.read_bytes()
        try:
            parsed = monitor._read_baseline_gpr_bytes(data)
        except ValueError:
            parsed = {"works": []}
        if not parsed.get("works"):
            packages = monitor._schedule_packages(project, data)
            parsed = {"works": (packages or {}).get("works") or []}
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = _works(parsed)
    return _CACHE[key]


def history(project: str, cut: dt.date) -> dict[str, list[tuple[dt.date, float, str]]]:
    """Dated GPR percents per work up to the cut: (date, progress, origin)."""
    out: dict[str, list[tuple[dt.date, float, str]]] = {}

    def add(tid: str, day: dt.date | None, progress: float | None, origin: str) -> None:
        if day and progress is not None and day <= cut:
            out.setdefault(tid, []).append((day, progress, origin))

    folder = monitor._project_dir(project)
    try:
        baseline = monitor._read_baseline_gpr(project)
        meta = json.loads((folder / "baseline" / "meta.json").read_text(encoding="utf-8"))
        base_day = _day(meta.get("taken_at"))
    except (OSError, ValueError, FileNotFoundError):
        baseline, base_day = {"works": []}, None
    for tid, (progress, _status) in _works(baseline).items():
        add(tid, base_day, progress, "approved_gpr")
    earliest = cut - dt.timedelta(days=WINDOW_DAYS + STALE_DAYS)
    weekly = folder / "schedule_fact"
    if weekly.exists():
        files = sorted(p for p in weekly.glob("*.xlsx") if _day(p.stem) and _day(p.stem) <= cut)
        # Older files cannot enter the pace window; keep one before it as context.
        keep = [p for p in files if _day(p.stem) >= earliest] or files[-1:]
        for path in keep:
            for tid, (progress, _status) in _weekly(project, path).items():
                add(tid, _day(path.stem), progress, "weekly_gpr")
    manual = folder / "work_fact"
    if manual.exists():
        for path in sorted(manual.glob("*.json")):
            day = _day(path.stem.split(".", 1)[0])
            try:
                rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
            except (OSError, ValueError):
                continue
            for row in rows:
                add(str(row.get("id")), day, _progress(row.get("progress")), "manual")
    for points in out.values():
        points.sort(key=lambda p: (p[0], {"approved_gpr": 0, "weekly_gpr": 1, "manual": 2}[p[2]]))
    return out


def work(row: dict, points: list[tuple[dt.date, float, str]], cut: dt.date,
         ks: dict | None = None) -> dict[str, Any]:
    """Forecast of one GPR work with its method and reason."""
    plan_start, plan_finish = _day(row.get("plan_start")), _day(row.get("plan_finish"))
    points = [point for point in points if point[0] <= cut and _progress(point[1]) is not None]
    result = {"forecast_finish": None, "method": "unknown", "reason": "", "progress": None,
              "progress_date": None, "progress_origin": None, "pace_per_day": None, "window": None}
    if ks and ks.get("forecast_finish"):
        completed = ks.get("mode") == "completed"
        method = "confirmed_completion" if completed else "cumulative_quantities"
        return dict(result, forecast_finish=ks["forecast_finish"], method=method,
                    progress=_progress(ks.get("progress")), progress_origin=method,
                    progress_date=ks.get("progress_date"), reason=("Дата завершения подтверждена вручную."
                    if completed else "По натуральному темпу накопительных."))
    if ks and ks.get("scope_confirmed") and ks.get("mode") in {"quantities", "completed"}:
        return dict(result, method="cumulative_unknown", progress=_progress(ks.get("progress")),
                    progress_origin="cumulative_quantities", progress_date=ks.get("progress_date"),
                    reason=ks.get("reason") or "Натуральный темп этой работы не подтверждён.")
    if points:
        last = points[-1]
        result.update(progress=last[1], progress_date=last[0].isoformat(), progress_origin=last[2])
        if last[1] >= DONE:
            first_done = next(p for p in points if p[1] >= DONE)
            return dict(result, forecast_finish=first_done[0].isoformat(), method="done",
                        reason="Завершена по ГПР; дата — первая запись со 100%.")
    window = [p for p in points if p[0] >= cut - dt.timedelta(days=WINDOW_DAYS)]
    pace = None
    if len(window) >= 2 and (cut - window[-1][0]).days <= STALE_DAYS:
        days = (window[-1][0] - window[0][0]).days
        growth = window[-1][1] - window[0][1]
        if days > 0 and growth > 0:
            pace = growth / days
            result["window"] = [window[0][0].isoformat(), window[-1][0].isoformat()]
    if pace:
        remaining = math.ceil((1.0 - window[-1][1]) / pace - 1e-10)
        if remaining > 36500:
            return dict(result, method="no_pace", reason="При нынешнем росте процента остаток займёт больше 100 лет.")
        finish = window[-1][0] + dt.timedelta(days=remaining)
        return dict(result, forecast_finish=finish.isoformat(), method="gpr_pace", pace_per_day=pace,
                    reason="По росту процента в ГПР за последние 90 дней.")
    if plan_finish and plan_finish >= cut:
        started = plan_start is None or plan_start <= cut
        return dict(result, forecast_finish=plan_finish.isoformat(), method="plan",
                    reason=("Срок по плану ещё не наступил; роста процента за 90 дней нет — показан план."
                            if started else "Работа по плану ещё не началась — показан план."))
    if points and (cut - points[-1][0]).days > STALE_DAYS:
        return dict(result, method="stale", reason="Последний процент в ГПР старше 45 дней; темп неизвестен.")
    if not points:
        return dict(result, method="unknown", reason="В ГПР нет датированных процентов этой работы.")
    if len({p[0] for p in window}) < 2:
        return dict(result, method="no_pace", reason="Нет двух свежих датированных процентов для определения темпа.")
    return dict(result, method="stalled",
                reason="Срок по плану прошёл, а процент в ГПР за 90 дней не рос: работа стоит, прогноза нет.")


def forecasts(project: str, cut: dt.date, rows: list[dict], ks: dict | None = None) -> dict[str, dict]:
    points = history(project, cut)
    out = {}
    ids = [str(row.get("id") or row.get("wbs") or "").strip() for row in rows]
    duplicates = {tid for tid, count in Counter(ids).items() if tid and count > 1}
    for row in rows:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        if tid:
            if tid in duplicates:
                out[tid] = {"forecast_finish": None, "progress": None, "method": "unknown",
                            "reason": "Идентификатор работы повторяется в ГПР; требуется уточнение."}
            else:
                out[tid] = work(row, points.get(tid) or [], cut, (ks or {}).get(tid))
    return out


ESTIMATE_NOTE = ("Оценка по ГПР без цепочки до получения разрешения: самая поздняя прогнозная дата "
                 "строительных работ (со статьёй сметы РСС). PM отключён.")


def rnv(rows: list[dict], works: dict[str, dict], approved: Any) -> dict[str, Any]:
    """Qualified RNV of the GPR: plan, estimate and the work that drives it."""
    approved_day = _day(approved)
    scope = [r for r in rows if str(r.get("code") or "").strip()]
    reasons = [ESTIMATE_NOTE]
    known, missing = [], []
    for row in scope:
        tid = str(row.get("id") or row.get("wbs") or "").strip()
        item = works.get(tid) or {}
        day = _day(item.get("forecast_finish"))
        (known if day else missing).append((day, row, item))
    outside = len(rows) - len(scope)
    if outside:
        reasons.append(f"{outside} работ ГПР без статьи сметы (продажи, ходатайства и т. п.) в прогноз РНВ не входят.")
    if missing:
        names = ", ".join("«" + str(r.get("name") or "") + "»" for _, r, _ in missing[:5])
        reasons.append(f"Без прогноза {len(missing)} строительных работ (стоят или нет данных): {names}"
                       + (" и др." if len(missing) > 5 else "") + ". Итоговая дата неполная.")
    if not known:
        return {"state": "unknown", "approved": monitor._iso(approved_day), "approved_source": "утверждённый ГПР",
                "forecast": None,
                "indicative_forecast": None, "delay_days": None, "driving_chain": [],
                "basis": "gpr", "reasons": reasons + ["Ни у одной строительной работы ГПР нет прогноза."]}
    day, row, item = max(known, key=lambda k: k[0])
    delay = (day - approved_day).days if approved_day else None
    state = "partial" if missing else "estimate"
    return {"state": state, "approved": monitor._iso(approved_day), "approved_source": "утверждённый ГПР",
            "forecast": day.isoformat() if state == "estimate" else None,
            "indicative_forecast": day.isoformat(), "delay_days": delay,
            "driving_chain": [{"id": str(row.get("id") or row.get("wbs") or ""), "name": str(row.get("name") or ""),
                               "method": item.get("method"), "reason": item.get("reason")}],
            "basis": "gpr", "reasons": reasons}
