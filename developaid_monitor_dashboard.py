"""Management KPI, funding-risk and recurring-input layer for Project Monitor."""
from __future__ import annotations

import datetime
import io
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor
import developaid_monitor_schedule_graph as schedule_graph

_INSTALLED = False
_ORIGINAL_BUILD = None
_ORIGINAL_STORE_SALES_FILE = None
_ORIGINAL_STORE_PROPOSAL = None


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def _finance_file(project: str) -> Path:
    return monitor._project_dir(project) / "baseline" / "finance.xlsx"


def _sales_dir(project: str) -> Path:
    path = monitor._project_dir(project) / "sales"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_sales(project: str, upto: datetime.date | None = None) -> Path | None:
    folder = monitor._project_dir(project) / "sales"
    if not folder.exists():
        return None
    rows = sorted(folder.glob("*.xlsx"))
    if upto:
        rows = [row for row in rows if row.stem[:10] <= upto.isoformat()]
    return rows[-1] if rows else None


def _find_header(ws: Any, needle: str, max_rows: int = 20) -> tuple[int, int] | None:
    wanted = _norm(needle)
    for r, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row, max_rows), values_only=True), 1):
        for c, value in enumerate(row, 1):
            if wanted in _norm(value):
                return r, c
    return None


def _finance_baseline(project: str) -> dict[str, Any]:
    path = _finance_file(project)
    if not path.exists():
        return {"known": False, "reason": "не загружен финансовый baseline"}
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Расчет стоимости строительства" not in wb.sheetnames:
            return {"known": False, "reason": "нет листа «Расчет стоимости строительства»"}
        ws = wb["Расчет стоимости строительства"]
        approved_hdr = _find_header(ws, "Утвержденная фин.модель проекта")
        need_hdr = _find_header(ws, "Средства на завершение согласно бюджету")
        paid_hdr = _find_header(ws, "Оплачено по состояни")
        programme_hdr = _find_header(ws, "производств")
        tail_hdr = _find_header(ws, "Остаток к выполнению на 01.04.27")
        if not approved_hdr or not need_hdr:
            return {"known": False, "reason": "не найдены колонки утвержденной модели/потребности"}
        approved_col = approved_hdr[1]
        need_col = need_hdr[1]
        paid_col = paid_hdr[1] if paid_hdr else 9
        programme_col = programme_hdr[1] if programme_hdr else 13
        tail_col = tail_hdr[1] if tail_hdr else 24
        total_row = None
        reserve_rows: list[int] = []
        for r, values in enumerate(ws.iter_rows(values_only=True), 1):
            code = actuals._code(values[0] if values else None)
            article = _norm(values[1] if len(values) > 1 else None)
            if total_row is None and "всего инвестиционные расходы глава 2, 3" in article:
                total_row = r
            if code in {"2.8", "2.9"}:
                reserve_rows.append(r)
        if total_row is None:
            return {"known": False, "reason": "не найдена итоговая строка глав 2+3"}
        approved = actuals._money(ws.cell(total_row, approved_col).value)
        completion_need = actuals._money(ws.cell(total_row, need_col).value)
        paid_at_baseline = actuals._money(ws.cell(total_row, paid_col).value)
        tail_after_apr = actuals._money(ws.cell(total_row, tail_col).value)
        reserve = 0.0
        reserve_parts: dict[str, float] = {}
        for r in reserve_rows:
            code = actuals._code(ws.cell(r, 1).value)
            amount = actuals._money(ws.cell(r, 10).value)
            reserve += amount
            reserve_parts[code] = amount
        month_row = (programme_hdr[0] + 1) if programme_hdr else 9
        ru_months = {"январь":1,"февраль":2,"март":3,"апрель":4,"май":5,"июнь":6,
                     "июль":7,"август":8,"сентябрь":9,"октябрь":10,"ноябрь":11,"декабрь":12}
        monthly: dict[str, float] = {}
        year = 2026
        previous_month = 0
        for c in range(programme_col, min(ws.max_column, programme_col + 15) + 1):
            label = _norm(ws.cell(month_row, c).value)
            month = ru_months.get(label)
            if not month:
                continue
            if previous_month and month < previous_month:
                year += 1
            previous_month = month
            monthly[datetime.date(year, month, 1).isoformat()] = actuals._money(ws.cell(total_row, c).value)
        return {
            "known": True, "source": path.name, "approved": approved,
            "completion_need_at_baseline": completion_need,
            "paid_at_baseline": paid_at_baseline,
            "reserve": reserve, "reserve_parts": reserve_parts,
            "monthly_need": monthly, "tail_after_apr": tail_after_apr,
        }
    finally:
        wb.close()


def _rss_ch23(estimate: dict[str, Any]) -> dict[str, float]:
    rows = estimate.get("by_code") or {}
    return {
        "limit": sum(float((rows.get(code) or {}).get("estimate") or 0.0) for code in ("2", "3")),
        "paid_bank_sheet": sum(float((rows.get(code) or {}).get("paid") or 0.0) for code in ("2", "3")),
        "contracted": sum(float((rows.get(code) or {}).get("contracted") or 0.0) for code in ("2", "3")),
    }


def _payment_total_ch23(rss: Path, estimate: dict[str, Any]) -> float:
    payments = actuals.read_payments(rss)
    parents = {row["code"]: row.get("parent") for row in estimate.get("rows") or []}
    def root(code: str) -> str:
        seen = set()
        while code and code not in seen:
            seen.add(code)
            parent = str(parents.get(code) or "")
            if not parent:
                return code.split(".")[0]
            code = parent
        return code.split(".")[0] if code else ""
    return sum(float(row.get("amount") or 0.0) for row in payments.get("rows") or []
               if root(str(row.get("estimate_code") or "").rstrip(".")) in {"2", "3"})


def _interpolated_crossing(month: datetime.date, month_amount: float, before: float, threshold: float) -> datetime.date:
    if month_amount <= 0:
        return month
    ratio = max(0.0, min(1.0, (threshold - before) / month_amount))
    if month.month == 12:
        nxt = datetime.date(month.year + 1, 1, 1)
    else:
        nxt = datetime.date(month.year, month.month + 1, 1)
    days = max(1, (nxt - month).days)
    return month + datetime.timedelta(days=max(0, min(days - 1, round(ratio * days))))


def _funding_risk(project: str, rss: Path, cut: datetime.date, view: dict[str, Any]) -> dict[str, Any]:
    baseline = _finance_baseline(project)
    if not baseline.get("known"):
        return {"known": False, "reason": baseline.get("reason", "нет финансового baseline")}
    estimate = actuals.read_estimate(rss)
    current = _rss_ch23(estimate)
    paid_actual = _payment_total_ch23(rss, estimate)
    paid_delta = max(0.0, paid_actual - float(baseline["paid_at_baseline"] or 0.0))
    remaining_need = max(0.0, float(baseline["completion_need_at_baseline"] or 0.0) - paid_delta)
    bank_remaining = max(0.0, current["limit"] - paid_actual)
    reserve = min(float(baseline["reserve"] or 0.0), bank_remaining)
    ordinary_remaining = max(0.0, bank_remaining - reserve)
    rnv = monitor._day((view.get("schedule") or {}).get("forecast_end"))
    if rnv is None:
        rnv = monitor._day((view.get("schedule") or {}).get("approved_end"))
    monthly: dict[datetime.date, float] = {}
    for key, amount in (baseline.get("monthly_need") or {}).items():
        month = monitor._day(key)
        if month is None:
            continue
        if month.year == cut.year and month.month == cut.month:
            if month.month == 12:
                nxt = datetime.date(month.year + 1, 1, 1)
            else:
                nxt = datetime.date(month.year, month.month + 1, 1)
            share = max(0.0, min(1.0, (nxt - cut).days / max(1, (nxt - month).days)))
            amount *= share
        elif month < cut.replace(day=1):
            continue
        monthly[month] = max(0.0, float(amount or 0.0))
    tail = max(0.0, float(baseline.get("tail_after_apr") or 0.0))
    tail_start = datetime.date(2027, 4, 1)
    if rnv and rnv >= tail_start and tail > 0:
        months: list[datetime.date] = []
        cursor = tail_start
        while cursor <= rnv.replace(day=1):
            months.append(cursor)
            cursor = (datetime.date(cursor.year + 1, 1, 1) if cursor.month == 12
                      else datetime.date(cursor.year, cursor.month + 1, 1))
        if months:
            per = tail / len(months)
            for month in months:
                monthly[month] = monthly.get(month, 0.0) + per
    curve_total = sum(monthly.values())
    if curve_total > 0 and remaining_need > 0:
        factor = remaining_need / curve_total
        monthly = {m: v * factor for m, v in monthly.items()}
    cumulative = 0.0
    reserve_start = None
    exhausted = None
    for month in sorted(monthly):
        amount = monthly[month]
        before = cumulative
        cumulative += amount
        if reserve_start is None and cumulative > ordinary_remaining:
            reserve_start = _interpolated_crossing(month, amount, before, ordinary_remaining)
        if exhausted is None and cumulative > bank_remaining:
            exhausted = _interpolated_crossing(month, amount, before, bank_remaining)
    additional = max(0.0, remaining_need - bank_remaining)
    return {
        "known": True, "source": baseline["source"], "bank_limit": current["limit"],
        "paid_actual": paid_actual, "bank_remaining": bank_remaining,
        "remaining_need": remaining_need, "reserve": reserve,
        "reserve_parts": baseline["reserve_parts"], "ordinary_remaining": ordinary_remaining,
        "reserve_start": monitor._iso(reserve_start), "bank_exhaustion": monitor._iso(exhausted),
        "additional_financing": additional, "forecast_to": monitor._iso(rnv),
        "monthly_need": {monitor._iso(k): v for k, v in sorted(monthly.items())},
        "method": "ДДС утвержденной модели до 01.04.2027 + остаток потребности до forecast РВЭ/РНВ",
    }


def _physical_smr(rss: Path, estimate: dict[str, Any], cut: datetime.date) -> float:
    works = actuals.read_completed_works(rss)
    return sum(float(row.get("amount") or 0.0) for row in works.get("rows") or []
               if row.get("construction") and row.get("date") and row["date"] <= cut
               and str(row.get("code") or "").startswith("2"))


def _sales_snapshot(project: str, cut: datetime.date) -> dict[str, Any]:
    path = _latest_sales(project, cut)
    if path is None:
        return {"known": False, "reason": "не загружен отчет о продажах"}
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        preferred = next((name for name in ("Продажи П-Ф", "Продажи", "Дашборд") if name in wb.sheetnames), "")
        return {"known": True, "source": path.name, "sheet": preferred}
    finally:
        wb.close()


def _dashboard(project: str, rss: Path, cut: datetime.date, view: dict[str, Any]) -> dict[str, Any]:
    estimate = actuals.read_estimate(rss)
    finance = _finance_baseline(project)
    current = _rss_ch23(estimate)
    physical = _physical_smr(rss, estimate, cut)
    approved = float(finance.get("approved") or 0.0)
    funding = _funding_risk(project, rss, cut, view)
    return {
        "physical": {"accepted": physical, "completion": physical / approved if approved > 0 else None},
        "construction": {
            "approved": approved or None, "limit": current["limit"], "contracted": current["contracted"],
            "remaining_need": funding.get("remaining_need") if funding.get("known") else None,
        },
        "schedule": {
            "approved_finish": (view.get("schedule") or {}).get("approved_end"),
            "forecast_finish": (view.get("schedule") or {}).get("forecast_end"),
            "rnv_delay_days": ((view.get("schedule") or {}).get("dependency_graph") or {}).get("rnv_delay_days"),
        },
        "sales": _sales_snapshot(project, cut), "funding": funding,
        "sources": {"rss": rss.name, "physical_fact": "Реестр выполненных работ",
                    "payment_fact": "Реестр платежей", "financial_baseline": finance.get("source")},
    }


def _store_sales_file(project: str, data: bytes, taken_at: Any) -> dict[str, Any]:
    day = monitor._iso(taken_at)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if not any(name in wb.sheetnames for name in ("Продажи П-Ф", "Продажи", "Дашборд")):
            raise ValueError("в книге не найден лист продаж")
    finally:
        wb.close()
    path = _sales_dir(project) / f"{day}.xlsx"
    if path.exists():
        raise FileExistsError(f"отчет продаж на {day} уже загружен")
    path.write_bytes(data)
    return {"taken_at": day, "stored": True, "path": str(path), "bytes": len(data)}


def _store_proposal(project: str, data: bytes, sheet: str, start: Any,
                    code: str, taken_at: Any) -> dict[str, Any]:
    return schedule_graph.store_reference(project, data, sheet, start, code, taken_at)


def _build(project: str, cut: Any, programme: dict[str, Any] | None = None, upto: str = "") -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("dashboard layer is not installed")
    view = _ORIGINAL_BUILD(project, cut, programme=programme, upto=upto)
    view = schedule_graph.apply(project, view)
    rss = monitor._latest(project, "estimate", ".xlsx", upto or monitor._iso(cut))
    cut_date = monitor._day(cut)
    if rss is not None and cut_date is not None:
        dashboard = _dashboard(project, rss, cut_date, view)
        view["dashboard"] = dashboard
        view["financing"] = dashboard["funding"]
    return view


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD, _ORIGINAL_STORE_SALES_FILE, _ORIGINAL_STORE_PROPOSAL
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    _ORIGINAL_STORE_SALES_FILE = getattr(monitor, "store_sales_file", None)
    _ORIGINAL_STORE_PROPOSAL = getattr(monitor, "store_proposal", None)
    monitor.build = _build
    monitor.store_sales_file = _store_sales_file
    monitor.store_proposal = _store_proposal
    _INSTALLED = True
