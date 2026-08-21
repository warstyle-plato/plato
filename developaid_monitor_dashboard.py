"""Management KPI layer for DevelopAid Project Monitor.

The fixed financial baseline is ``baseline/finance.xlsx``.  It is deliberately
separate from ``baseline/gpr.xlsx``: the former provides the approved model and
current completion need, while the latter remains the immutable schedule.

Physical construction fact is never read from the aggregate ``Выполнено``
column of the RSS cost sheet.  It is reconstructed only from dated construction
acts in ``Реестр выполненных работ``.
"""
from __future__ import annotations

import datetime
import io
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor

_INSTALLED = False
_ORIGINAL_BUILD = None
_ORIGINAL_STORE_SALES_FILE = None


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


def _find_header(ws: Any, labels: tuple[str, ...], max_rows: int = 25) -> dict[str, int]:
    result: dict[str, int] = {}
    wanted = {_norm(label): label for label in labels}
    for r in range(1, min(ws.max_row, max_rows) + 1):
        values = [_norm(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)]
        for c, value in enumerate(values, 1):
            for needle, canonical in wanted.items():
                if needle and needle in value and canonical not in result:
                    result[canonical] = c
        if len(result) == len(labels):
            break
    return result


def _approved_baseline(project: str) -> dict[str, Any]:
    """Read approved SМR and current completion need from the fixed finance book."""
    path = _finance_file(project)
    if not path.exists():
        return {"known": False, "reason": "не загружен финансовый baseline"}
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Расчет стоимости строительства" not in wb.sheetnames:
            return {"known": False, "reason": "в финансовом baseline нет «Расчет стоимости строительства»"}
        ws = wb["Расчет стоимости строительства"]
        headers = _find_header(ws, (
            "Утвержденная фин.модель проекта",
            "Средства на завершение согласно бюджету",
        ))
        approved_col = headers.get("Утвержденная фин.модель проекта")
        need_col = headers.get("Средства на завершение согласно бюджету")
        if not approved_col:
            return {"known": False, "reason": "не найдена колонка «Утвержденная фин.модель проекта»"}
        for r in range(1, ws.max_row + 1):
            code = actuals._code(ws.cell(r, 1).value)
            article = _norm(ws.cell(r, 2).value)
            if code == "2" or article == "стоимость смр":
                approved = actuals._money(ws.cell(r, approved_col).value)
                completion_need = actuals._money(ws.cell(r, need_col).value) if need_col else 0.0
                return {
                    "known": approved > 0,
                    "approved_smr": approved,
                    "remaining_need_at_baseline": completion_need,
                    "source": path.name,
                }
        return {"known": False, "reason": "в baseline не найдена строка «Стоимость СМР»"}
    finally:
        wb.close()


def _rss_smr(estimate: dict[str, Any]) -> dict[str, float]:
    row = estimate.get("by_code", {}).get("2") or {}
    return {
        "limit": float(row.get("estimate") or 0.0),
        "contracted": float(row.get("contracted") or 0.0),
        "paid": float(row.get("paid") or 0.0),
    }


def _descendants(estimate: dict[str, Any], root: str) -> set[str]:
    children: dict[str, set[str]] = {}
    for row in estimate.get("rows") or []:
        parent = str(row.get("parent") or "")
        if parent:
            children.setdefault(parent, set()).add(str(row.get("code") or ""))
    selected: set[str] = set()
    stack = [root]
    while stack:
        code = stack.pop()
        if code in selected:
            continue
        selected.add(code)
        stack.extend(children.get(code, ()))
    return selected


def _physical_smr(rss: Path, estimate: dict[str, Any], cut: datetime.date) -> float:
    """Dated construction acts only. Never use RSS aggregate `completed`."""
    works = actuals.read_completed_works(rss)
    codes = _descendants(estimate, "2")
    return sum(
        float(row.get("amount") or 0.0)
        for row in works.get("rows") or []
        if row.get("construction")
        and row.get("code") in codes
        and row.get("date")
        and row["date"] <= cut
    )


def _unclosed_advance(rss: Path) -> float | None:
    """Read the bank's explicit `НЕ закрыт. Аванс` marker when present."""
    from openpyxl import load_workbook
    wb = load_workbook(rss, read_only=True, data_only=True)
    try:
        if "Расчет стоимости строительства" not in wb.sheetnames:
            return None
        ws = wb["Расчет стоимости строительства"]
        for row in ws.iter_rows(min_row=1, max_row=min(15, ws.max_row), values_only=True):
            for ix, value in enumerate(row):
                if "не закрыт" in _norm(value) and "аванс" in _norm(value):
                    for nxt in row[ix + 1:]:
                        amount = actuals._money(nxt)
                        if amount:
                            return amount
        return None
    finally:
        wb.close()


def _baseline_finish(view: dict[str, Any]) -> str | None:
    return (view.get("schedule") or {}).get("baseline_end")


def _forecast_finish(view: dict[str, Any]) -> str | None:
    return (view.get("schedule") or {}).get("forecast_end")


def _sales_snapshot(project: str, cut: datetime.date) -> dict[str, Any]:
    """Sales are optional until a recurring sales workbook has been uploaded."""
    path = _latest_sales(project, cut)
    if path is None:
        return {"known": False, "reason": "не загружен отчет о продажах"}
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        # The source workbook is intentionally left intact.  For now expose the
        # source/date; detailed sales KPIs are added only when headers are
        # recognized rather than guessed from a specific project template.
        return {"known": True, "source": path.name, "sheets": wb.sheetnames}
    finally:
        wb.close()


def _dashboard(project: str, rss: Path, cut: datetime.date, view: dict[str, Any]) -> dict[str, Any]:
    estimate = actuals.read_estimate(rss)
    approved = _approved_baseline(project)
    current = _rss_smr(estimate)
    physical = _physical_smr(rss, estimate, cut)
    advance = _unclosed_advance(rss)
    approved_smr = float(approved.get("approved_smr") or 0.0)
    paid = current["paid"]
    remaining_need = max(0.0, approved_smr - paid) if approved_smr else None
    limit_gap = approved_smr - current["limit"] if approved_smr else None
    completion = physical / approved_smr if approved_smr > 0 else None
    completion_vs_limit = physical / current["limit"] if current["limit"] > 0 else None
    advance_share = advance / paid if advance is not None and paid > 0 else None

    pf = {
        "available": False,
        "scenario": "лимиты увеличены до утвержденной реальной потребности",
        "additional_limit": max(0.0, limit_gap or 0.0),
        "reason": (
            "Для ответа о погашении ПФ нужен расчетный ДДС DevelopAid: "
            "график выборки ПФ, ставка/проценты, прогноз эскроу и правила погашения. "
            "До пересчета этих потоков Monitor не делает вывод «погасится / не погасится»."
        ),
    }
    return {
        "physical": {
            "accepted": physical,
            "completion": completion,
            "completion_vs_bank_limit": completion_vs_limit,
        },
        "construction": {
            **current,
            "approved_smr": approved_smr or None,
            "remaining_need": remaining_need,
            "limit_gap": limit_gap,
            "limit_gap_pct": (limit_gap / current["limit"] if limit_gap is not None and current["limit"] else None),
            "baseline_known": bool(approved.get("known")),
            "baseline_reason": approved.get("reason"),
        },
        "advances": {
            "unclosed": advance,
            "share_of_paid": advance_share,
            "known": advance is not None,
        },
        "schedule": {
            "baseline_finish": _baseline_finish(view),
            "forecast_finish": _forecast_finish(view),
            "forecast_method": "RSS pace; dependency/float CPM layer pending" if _forecast_finish(view) else "недостаточно темпа",
        },
        "sales": _sales_snapshot(project, cut),
        "pf": pf,
        "sources": {
            "financial_baseline": approved.get("source"),
            "rss": rss.name,
            "physical_fact": "Реестр выполненных работ / датированные строительные акты",
        },
    }


def _store_sales_file(project: str, data: bytes, taken_at: Any) -> dict[str, Any]:
    """Persist recurring sales snapshots while retaining legacy validation."""
    day = monitor._iso(taken_at)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("дата отчета продаж нужна в виде ГГГГ-ММ-ДД")
    # Validate as an Excel workbook first; do not silently persist random bytes.
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if not any(name in wb.sheetnames for name in ("Продажи П-Ф", "Продажи", "Дашборд")):
            raise ValueError("в книге не найден лист продаж")
    finally:
        wb.close()
    folder = _sales_dir(project)
    path = folder / f"{day}.xlsx"
    if path.exists():
        raise FileExistsError(f"отчет продаж на {day} уже загружен")
    path.write_bytes(data)
    return {"taken_at": day, "path": str(path), "bytes": len(data), "stored": True}


def _build(project: str, cut: Any, programme: str = "") -> dict[str, Any]:
    if _ORIGINAL_BUILD is None:
        raise RuntimeError("dashboard layer is not installed")
    view = _ORIGINAL_BUILD(project, cut=cut, programme=programme)
    rss = monitor._latest(project, "estimate", ".xlsx", monitor._iso(cut))
    cut_date = monitor._day(cut)
    if rss is not None and cut_date is not None:
        view["dashboard"] = _dashboard(project, rss, cut_date, view)
    return view


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD, _ORIGINAL_STORE_SALES_FILE
    if _INSTALLED:
        return
    _ORIGINAL_BUILD = monitor.build
    _ORIGINAL_STORE_SALES_FILE = getattr(monitor, "store_sales_file", None)
    monitor.build = _build
    monitor.store_sales_file = _store_sales_file
    _INSTALLED = True
