"""Contract deadline and unworked-advance warnings for the contract register.

One owner for the legal team's signals. The register (`developaid_monitor_contracts.build`)
calls :func:`assess` once per contract row and :func:`payments` once per build;
the Monitor page and the management summary read the stored result.

Deadline forecast. The contract is a money obligation: it is fulfilled when its
full confirmed price is executed. The pace is the money of dated, deduplicated,
completed cumulative periods that lie wholly within the last 90 days, divided by
the calendar days from the first such period's start to the last one's end. A
pace older than 45 days is not extrapolated. Without a confirmed full price, a
comparable VAT basis or a pace, the forecast stays unknown with its reason.
This is an indicator from accepted money, not physical readiness.

Works and materials. When the books separate «Стоимость СМР» and «Стоимость
материалы», the pace is works only and the unworked advance is paid over works;
paid over works plus delivered materials is a reference line.

Unworked advance. Payments come from «Реестр платежей» of the same RSS workbook
and join a contract only by its exact identity: contractor, number and contract
date. Payments after the cut are not facts for the cut. Paid minus executed is
shown as «оплачено сверх выполнения»; the word «аванс» in a payment purpose is
reference only and never classifies money.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

PACE_WINDOW_DAYS = 90
STALE_AFTER_DAYS = 45

# Order is severity; the page and the summary sort by it.
STATUSES = {
    "overdue": "Срок договора прошёл",
    "late": "Не успевает к сроку",
    "stalled": "Работы стоят",
    "unknown": "Прогноз неизвестен",
    "no_deadline": "Срок не указан",
    "on_track": "Успевает",
    "done": "Выполнено",
}
WARNING_STATUSES = ("overdue", "late", "stalled")


def _day(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        text = str(value or "")
        day = dt.date.fromisoformat(text)
        return day if day.isoformat() == text else None
    except ValueError:
        return None


def _tolerance(value: float) -> float:
    return max(0.01, abs(value) * 1e-7)


def forecast(*, amount: float | None, completed: float | None, comparable: bool,
             periods: list[tuple], cut: dt.date, deadline: dt.date | None,
             works: float | None = None, materials: float | None = None) -> dict:
    """Status of one contract against its deadline from accepted money pace.

    When the books separate works (СМР) and materials, the pace is works only:
    a delivery of materials does not move the deadline (owner's decision). The
    remaining part is the price less executed works and delivered materials;
    materials still to come stay inside it, so the forecast errs on the late
    side. Without the split the total pace is used and the reason says so."""
    split = works is not None and materials is not None
    result = {"status": "unknown", "label": "", "forecast_finish": None, "delay_days": None,
              "remaining": None, "pace_per_day": None, "pace_window": None, "reason": "",
              "pace_basis": "works" if split else "total"}

    def done(status: str, reason: str = "", **values) -> dict:
        return dict(result, status=status, label=STATUSES[status], reason=reason, **values)

    if amount is None or amount <= 0:
        reason = ("Нет подтверждённой полной суммы договора. Завершение по накопительным неизвестно, "
                  "срок окончания не прогнозируется.")
        return done("overdue" if deadline and deadline < cut else "unknown", reason)
    if completed is None or not comparable:
        reason = ("Выполнение по накопительным на дату среза не подтверждено." if completed is None else
                  "Сумма договора и выполнение по накопительным имеют несопоставимую базу НДС.")
        reason += " Завершение по накопительным неизвестно, срок окончания не прогнозируется."
        return done("overdue" if deadline and deadline < cut else "unknown", reason)
    remaining = amount - completed
    if remaining <= _tolerance(amount):
        return done("done", "Выполнение по накопительным достигло полной суммы договора.", remaining=0.0)
    window_start = cut - dt.timedelta(days=PACE_WINDOW_DAYS)
    # (start, end, money) where money is works when split, else the total.
    periods = [(p[0], p[1], (p[3] if split else p[2]) if len(p) > 3 else p[2]) for p in periods
               if not split or len(p) > 3 and p[3] is not None]
    recent = sorted(p for p in periods if p[0] >= window_start and p[1] <= cut)
    pace = None
    finish = None
    reason = ""
    if not recent:
        reason = "В последние 90 дней нет закрытых периодов выполнения; текущий темп неизвестен."
    elif (cut - recent[-1][1]).days > STALE_AFTER_DAYS:
        reason = "Последний период выполнения закончился больше 45 дней назад; текущий темп не экстраполируется."
    else:
        days = (recent[-1][1] - recent[0][0]).days + 1
        money = math.fsum(p[2] for p in recent)
        if money <= 0:
            reason = "В последних периодах нет положительного выполнения."
        else:
            pace = money / days
            remaining_days = math.ceil(remaining / money * days - 1e-10)
            if remaining_days > 36500:
                reason = "При текущем темпе остаток займёт больше 100 лет; прогноз не показывается."
                pace = None
            else:
                finish = cut + dt.timedelta(days=remaining_days)
    if not split:
        note = "В накопительных работы и материалы не разделены: темп посчитан по общей сумме."
        reason = (reason + " " + note).strip()
    values = {"remaining": remaining, "pace_per_day": pace,
              "pace_window": ([recent[0][0].isoformat(), recent[-1][1].isoformat()] if pace else None),
              "forecast_finish": finish.isoformat() if finish else None}
    if deadline and deadline < cut:
        delay = ((finish or cut) - deadline).days
        return done("overdue", reason, delay_days=delay if finish else (cut - deadline).days, **values)
    if pace is None:
        # No current production with work remaining is itself the warning.
        return done("stalled" if recent or periods else "unknown", reason, **values)
    if not deadline:
        return done("no_deadline", "Срок договора не указан; прогноз окончания показан без сравнения.", **values)
    if finish > deadline:
        return done("late", reason, delay_days=(finish - deadline).days, **values)
    return done("on_track", reason, delay_days=0, **values)


def _norm(value: Any) -> str:
    value = str(value or "").casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r'[«»“”"]', "", value)).strip()


def payment_identity(row: dict, *, reference_key) -> tuple:
    """The same canonical party/number policy used for RSS, never persisted IDs."""
    _, contractor, number = reference_key(row)
    return contractor, number, _day(row.get("contract_date"))


def payments(path: Any, cut: dt.date) -> tuple[list[dict] | None, list[str]]:
    """Retain unresolved source rows instead of turning their absence into zero."""
    import developaid_actuals as actuals
    from pathlib import Path
    if path is None:
        return None, ["Реестр платежей РСС не загружен; оплаты по договорам не показаны."]
    try:
        rows = actuals.read_payments(path, include_incomplete=True).get("rows") or []
    except (KeyError, ValueError, OSError):
        return None, ["Реестр платежей в выбранном снимке РСС не прочитан; оплаты по договорам не показаны."]
    out, undated = [], 0
    for row in rows:
        day = _day(row.get("date"))
        if day is not None and day > cut:
            continue
        if day is None:
            undated += 1
        amount = row.get("amount")
        try:
            amount = None if amount is None or isinstance(amount, bool) else float(amount)
        except (TypeError, ValueError):
            amount = None
        if amount is not None and not math.isfinite(amount):
            amount = None
        out.append({"contractor": row.get("contractor") or "",
                    "contract": row.get("contract") or "",
                    "contract_date": _day(row.get("contract_date")),
                    "amount": amount, "date": day,
                    "advance_label": "аванс" in _norm(row.get("purpose")),
                    "source": {"label": "Реестр платежей РСС", "filename": Path(path).name,
                               "sheet": actuals._PAYMENTS_SHEET, "row": row.get("source_row")}})
    warnings = ([f"В реестре платежей {undated} строк без даты платежа; итог оплаты по подходящим договорам неизвестен."]
                if undated else [])
    return out, warnings


def advance(row: dict, paid_rows: list[dict] | None, *, reference_key,
            completed_basis: str, identity_counts: dict | None = None) -> dict:
    """Allocate only complete, unique payment identities; retain unknown totals.

    A known subset is separate from the authoritative total. An unresolved row
    could add a payment, so neither total paid nor unworked advance becomes zero.
    """
    result = {"paid": None, "paid_advance_labelled": None, "unworked": None, "payments_count": 0,
              "unworked_with_materials": None, "basis": "total",
              "confirmed_paid": None, "confirmed_paid_advance_labelled": None,
              "unmatched_candidates": 0, "unmatched_amount": None, "reason": "", "sources": []}
    if paid_rows is None:
        return dict(result, reason="Реестр платежей не прочитан.")
    identity = payment_identity(row, reference_key=reference_key)
    if not all(identity):
        return dict(result, reason="Подрядчик, номер или дата договора не подтверждены; оплаты не сопоставлены.")

    def compatible(key):
        return all(not part or part == expected for part, expected in zip(key, identity))

    related = [(payment, payment_identity(payment, reference_key=reference_key))
               for payment in paid_rows]
    related = [(payment, key) for payment, key in related if compatible(key)]
    result["sources"] = [payment["source"] for payment, _ in related if payment.get("source")]
    if identity_counts is not None and identity_counts.get(identity, 0) != 1:
        return dict(result, unmatched_candidates=len(related),
                    unmatched_amount=(math.fsum(p["amount"] for p, _ in related)
                                      if related and all(p.get("amount") is not None for p, _ in related) else None),
                    reason="Подрядчик, номер и дата подходят нескольким договорам из накопительных; "
                           "платежи не распределены между разными карточками.")
    exact = [payment for payment, key in related if all(key) and key == identity
             and payment.get("date") is not None and payment.get("amount") is not None]
    unresolved = [payment for payment, _ in related if payment not in exact]
    confirmed = math.fsum(p["amount"] for p in exact)
    confirmed_advance = math.fsum(p["amount"] for p in exact if p["advance_label"])
    result.update(confirmed_paid=confirmed, confirmed_paid_advance_labelled=confirmed_advance,
                  payments_count=len(exact), unmatched_candidates=len(unresolved),
                  unmatched_amount=(math.fsum(p["amount"] for p in unresolved)
                                    if unresolved and all(p.get("amount") is not None for p in unresolved) else None))
    if unresolved:
        missing_date = any(not p.get("contract_date") for p in unresolved)
        return dict(result, reason=f"Ещё {len(unresolved)} подходящих строк реестра платежей "
                    + ("без даты договора" if missing_date else "с неполными реквизитами, датой платежа или суммой")
                    + "; итог оплаты и неотработанный аванс неизвестны. Проверьте исходные строки.")
    paid = confirmed
    result.update(paid=paid, paid_advance_labelled=confirmed_advance)
    notes = []
    completed = row.get("completed")
    if completed is None:
        notes.append("Выполнение по накопительным не подтверждено; переплата сверх выполнения не считается.")
    elif completed_basis in {"without_vat", "conflicting"}:
        notes.append("Выполнение указано без НДС или с разными базами НДС, а оплаты — фактические платежи; "
                     "переплата не считается без сверки.")
    else:
        works, materials = row.get("completed_works"), row.get("completed_materials")
        if row.get("works_materials_split") and works is not None and materials is not None:
            result.update(unworked=max(0.0, paid - works), basis="works",
                          unworked_with_materials=max(0.0, paid - works - materials))
        else:
            result["unworked"] = max(0.0, paid - completed)
            notes.append("Работы и материалы в накопительных не разделены; сравнение с общим выполнением.")
        if completed_basis == "unspecified":
            notes.append("База НДС выполнения не указана; сравнение с оплатами — оценка.")
    return dict(result, reason=" ".join(notes))


def summary(rows: list[dict]) -> dict:
    """Unknown or partial payment coverage never becomes a zero total."""
    risk = [r.get("risk") or {} for r in rows]
    unworked = [r.get("advance") or {} for r in rows]
    at_risk = [r for r in rows if (r.get("risk") or {}).get("status") in WARNING_STATUSES]
    exposed = [r for r in at_risk if ((r.get("advance") or {}).get("unworked") or 0) > 0]
    unknown = sum(x.get("unworked") is None for x in unworked)
    risk_unknown = sum((r.get("advance") or {}).get("unworked") is None for r in at_risk)
    confirmed = math.fsum(x["unworked"] for x in unworked if x.get("unworked") is not None)
    risk_confirmed = math.fsum(r["advance"]["unworked"] for r in exposed)
    return {
        "counts": {status: sum(1 for x in risk if x.get("status") == status) for status in STATUSES},
        "warning_count": len(at_risk),
        "unworked_total": None if unknown else confirmed,
        "unworked_confirmed_total": confirmed,
        "unworked_unknown_count": unknown,
        "unworked_at_risk_total": None if risk_unknown else risk_confirmed,
        "unworked_at_risk_confirmed_total": risk_confirmed,
        "unworked_at_risk_unknown_count": risk_unknown,
        "unworked_at_risk_count": len(exposed),
    }


def severity(row: dict) -> tuple:
    status = (row.get("risk") or {}).get("status") or "unknown"
    order = list(STATUSES).index(status) if status in STATUSES else len(STATUSES)
    return (order, -((row.get("advance") or {}).get("unworked") or 0), -((row.get("risk") or {}).get("delay_days") or 0))
