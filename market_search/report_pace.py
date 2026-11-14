"""Темп отчёта на общей календарной базе, отдельно от средних источника."""

from __future__ import annotations

import re
from typing import Any

_MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь",
           "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def align_report_pace(subject: dict[str, Any], peers: list[dict[str, Any]],
                      subject_series: list[dict[str, Any]], month: str | None,
                      source: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Средний месячный темп за три полных календарных месяца.

    Месяц задаёт выпуск помесячного отчёта. Пропуск в нём не откатывает
    сравнение назад, а сосед без ряда не получает средний темп вместо факта.
    """
    if not subject_series or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        def provider_row(row: dict[str, Any]) -> dict[str, Any]:
            derived = {"pace_reference", "pace_basis", "pace_month", "pace_label", "pace_series",
                       "units_in_last_month"}
            clean = {k: v for k, v in row.items() if k not in derived}
            clean.update(row.get("provider_pace") or {})
            return clean

        own, neighbours = provider_row(subject), [provider_row(p) for p in peers]
        return {**own, "pace_reference": {
            "basis": "provider_average", "label": "средний темп источника",
            "peer_count": sum(p.get("units_per_month") is not None for p in neighbours),
            "peer_total": len(peers),
        }}, neighbours

    year, number = map(int, month.split("-"))
    serial = year * 12 + number - 1
    def window_at(end: str) -> list[str]:
        y, n = map(int, end.split("-"))
        at = y * 12 + n - 1
        return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(at - 2, at + 1)]

    window = window_at(month)

    def label(at: str) -> str:
        y, n = map(int, at.split("-"))
        return f"{_MONTHS[n - 1]} {y}"

    period_label = (f"{_MONTHS[(serial - 2) % 12]}–{_MONTHS[number - 1]} {year}"
                    if window[0][:4] == month[:4] else f"{label(window[0])} — {label(month)}")

    def row_with_period(row: dict[str, Any], series: list[dict[str, Any]]) -> dict[str, Any]:
        points = {p.get("month"): p.get("sold") for p in series}
        def average(end: str) -> float | None:
            values = [points.get(m) for m in window_at(end)]
            # Округление — при показе, не до медианы и отношения.
            return sum(values) / 3 if all(v is not None for v in values) else None

        anchors = sorted({m for m in points if m <= month} | {month})
        original = row.get("provider_pace") or {
            key: row.get(key) for key in
            ("units_per_month", "units_per_month_3m", "known_sales_for")}
        return {**row, "provider_pace": dict(original),
                "units_per_month": average(month),
                "units_per_month_3m": average(month),
                "units_in_last_month": points.get(month),
                "pace_series": [{"month": m, "sold": average(m)} for m in anchors] if series else [],
                "pace_basis": "calendar_average", "pace_month": month, "pace_label": period_label}

    own = row_with_period(subject, subject_series)
    neighbours = [row_with_period(p, p.get("sales_series") or []) for p in peers]
    own["pace_reference"] = {
        "basis": "calendar_average", "month": month, "months": 3,
        "label": period_label, "month_label": label(month), "source": source,
        "recent_from": window[0], "recent_to": month,
        "peer_count": sum(p["units_per_month"] is not None for p in neighbours),
        "peer_total": len(neighbours),
    }
    return own, neighbours
