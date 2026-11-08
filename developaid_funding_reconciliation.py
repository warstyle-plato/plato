"""Source-preserving funding bridge; arithmetic is not financial acceptance.

No network, workbook reads or inferred payment identities live here. A schedule
coverage decision is usable only for the exact source versions and cut that
were reviewed. Unproved coverage stays explicit rather than becoming zero.
"""
from __future__ import annotations

import math
import re
import datetime
from typing import Any


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def admin_schedule_policy(comp: dict, schedule: dict | None, chapter: str,
                          cut: str) -> dict:
    """Return only proven unpaid additions; never infer inclusion from an RSS code."""
    result = {"items": [], "monthly_additions": {}, "added_to_need": 0.0,
              "programme_known": (schedule or {}).get("plan_known", True),
              "state": "not_replaced" if not schedule else "complete"}
    if not schedule:
        return result
    if result["programme_known"] is not True:
        result["state"] = "incomplete"
    proof = schedule.get("admin_coverage") or {}
    proof = proof if isinstance(proof, dict) else {}
    hashes = [comp.get("source_sha256"), schedule.get("source_sha256")]
    bound = (all(isinstance(x, str) and re.fullmatch(r"[0-9a-f]{64}", x) for x in hashes)
             and proof.get("budget_sha256") == hashes[0]
             and proof.get("schedule_sha256") == hashes[1]
             and proof.get("cut") == cut and proof.get("basis") == "reviewed_sources")
    records = proof.get("items") if bound else []
    records = records if isinstance(records, list) else []
    for item in comp.get("admin_items") or []:
        candidates = item.get("chapter_candidates") or []
        if chapter not in candidates and candidates:
            continue
        source_row = (item.get("source") or {}).get("row")
        matches = [r for r in records if isinstance(r, dict)
                   and isinstance(source_row, int) and not isinstance(source_row, bool)
                   and source_row > 0
                   and r.get("code") == item.get("code")
                   and r.get("source_row") == source_row]
        record = matches[0] if len(matches) == 1 else {}
        state = record.get("state") if len(candidates) == 1 else "unknown"
        known = item.get("known_fields") or {}
        plan = number(item.get("plan")) if known.get("plan", True) else None
        row = {"code": item.get("code"), "source": item.get("source") or {},
               "state": "unknown", "model_remaining": plan, "added_to_need": 0.0}
        if state == "included":
            row.update(state="included", reason="АХР учтены в проверенном составе графика")
        elif state == "excluded" and plan is not None:
            monthly = item.get("monthly") or {}
            values = {k: number(v) for k, v in monthly.items()}
            try:
                months_valid = all(datetime.date.fromisoformat(k).day == 1 for k in values)
            except (TypeError, ValueError):
                months_valid = False
            # Chapter-level payments cannot be attributed to an admin leaf by
            # guesswork. A new per-payment audit is needed after such payments.
            if number(schedule.get("paid_since")) != 0.0:
                row["reason"] = "Оплаты после даты базы не распределены по строкам АХР"
            elif not values or not months_valid or any(v is None or v < 0 for v in values.values()):
                row["reason"] = "Не подтверждён помесячный неоплаченный план АХР"
            elif abs(sum(values.values()) - plan) > 1e-6 * max(1.0, abs(plan)):
                row["reason"] = "Помесячный план АХР не равен остатку строки"
            else:
                row.update(state="excluded", added_to_need=plan,
                           reason="АХР отсутствуют в проверенном составе графика")
                month_cut = cut[:7] + "-01"
                for month, amount in values.items():
                    target = max(month, month_cut)
                    result["monthly_additions"][target] = (
                        result["monthly_additions"].get(target, 0.0) + amount)
                result["added_to_need"] += plan
        else:
            row["reason"] = ("Денежная глава АХР не установлена" if len(candidates) != 1 else
                             "Включение АХР в график не подтверждено для этих версий и даты")
        if row["state"] == "unknown":
            result["state"] = "incomplete"
        result["items"].append(row)
    return result


def build(own: dict, comp: dict, chapter_flow: dict, cut: str,
          schedule_policy: dict | None = None, schedule: dict | None = None) -> dict:
    """Explain the same budget using independently calculated source components.

    The bridge is B = paid + remaining limit + calculated additional + named
    unresolved components - unused capacity. Additional is derived from chapter
    needs, not assigned the unexplained residual of the equation.
    """
    fields = comp.get("known_fields") or {}
    budget = number(comp.get("total")) if fields.get("total", True) else None
    paid = number(own.get("paid")) if own.get("payments_known", True) else None
    left = number(own.get("left")) if own.get("payments_known", True) and own.get("limits_known", True) else None
    unallocated = chapter_flow.get("") or {}
    unmapped = number(unallocated.get("total", 0.0))
    rows = own.get("rows") or []
    chapters = {row.get("chapter") for row in rows if row.get("chapter")}
    amounts = [number(row.get("amount")) for row in rows if row.get("chapter")]
    outside_values = [number(flow.get("total")) for ch, flow in chapter_flow.items()
                      if ch and ch not in chapters]
    outside = sum(outside_values) if all(v is not None for v in outside_values) else None
    # Unused capacity in one chapter cannot pay the positive shortage of a
    # different chapter. Preserve both sides of that restriction in the bridge.
    additional = sum(max(0.0, v) for v in amounts if v is not None)
    unused = sum(max(0.0, -v) for v in amounts if v is not None)
    components = [
        {"kind": "unallocated_budget", "amount": unmapped,
         "reason": "Расходы без подтверждённой денежной главы"},
        {"kind": "schedule_difference", "amount": number(own.get("model_over_schedule")),
         "reason": "Различие бюджета модели и проверяемого графика"},
        {"kind": "payment_difference", "amount": number(own.get("accounting")),
         "reason": "Факт финансовой базы и оплаты на дату не совпадают"},
        {"kind": "outside_bank_scope", "amount": outside,
         "reason": "Оплаты и покрытие расходов вне выбранных банковских глав не сверены"},
    ]
    policy = schedule_policy or {"state": "not_replaced", "items": [], "added_to_need": 0.0}
    reasons = []
    if budget is None or any(not fields.get(k, True) for k in ("fact", "plan", "monthly")):
        reasons.append("В финансовой базе есть неизвестные денежные значения")
    if not own.get("payments_known", True):
        reasons.append("Оплаты на дату не прочитаны для всех выбранных глав")
    if not own.get("limits_known", True):
        reasons.append("Лимит не прочитан для всех выбранных глав")
    if unmapped is None or unmapped:
        reasons.append("Часть бюджета не распределена по денежным главам")
    if policy["state"] == "incomplete":
        reasons.append("Требуется сверить включение АХР в график финансирования")
    if any(r["amount"] is None or abs(r["amount"]) > 0.5 for r in components[1:]):
        reasons.append("Бюджет, график и оплаты требуют сверки состава и дат")
    amount_known = (budget is not None and all(fields.get(k, True) for k in ("fact", "plan", "monthly"))
                    and policy.get("programme_known", True) is True
                    and all(v is not None for v in amounts)
                    and paid is not None and left is not None
                    and (bool(rows) or budget == 0.0))
    values = [paid, left, *[r["amount"] for r in components]]
    rhs = (paid + left + additional + sum(r["amount"] for r in components) - unused
           if amount_known and all(v is not None for v in values) else None)
    matches = (abs(budget - rhs) <= 1e-6 * max(1.0, abs(budget))
               if budget is not None and rhs is not None else False)
    if not matches:
        reasons.append("Состав исходных сумм не даёт арифметической сверки")
    result = {"schema": 1, "cut": cut, "budget": budget, "paid_at_cut": paid,
            "bank_limit_total": (number(own.get("limit")) if own.get("limits_known", True) else None),
            "remaining_bank_limit": left,
            "calculated_additional": additional if amount_known else None,
            "confirmed_additional": None, "unused_capacity": unused if amount_known else None,
            "components": components, "rhs": rhs, "matches": matches,
            "state": "needs_reconciliation" if reasons else "arithmetically_reconciled",
            "reasons": reasons, "admin_schedule": policy,
            "primary_source_gate": "BLOCKED", "financial_acceptance_performed": False,
            "payment_identity_verified": None, "source_dates": {},
            "unallocated_programme": {
                "model_total": unmapped, "model_fact": number(unallocated.get("fact", 0.0)),
                "model_plan": number(unallocated.get("plan", 0.0)),
                "monthly": dict(unallocated.get("monthly") or {}),
                "paid_at_cut": None, "funding_coverage": None}}
    result["display_rows"] = display_rows(result)
    result["need_breakdown"] = need_breakdown(own, comp, cut, amount_known, schedule)
    result["need_breakdown"]["display_rows"] = breakdown_rows(result["need_breakdown"])
    return result


def need_breakdown(own: dict, comp: dict, cut: str, known: bool,
                   schedule: dict | None = None) -> dict:
    """Spend each chapter's own limit chronologically, never apportion its gap to works."""
    chapters = []
    for row in own.get("rows") or []:
        if not row.get("chapter"):
            continue
        left = number(row.get("left"))
        available = max(0.0, left or 0.0)
        months, programme_known = [], known and left is not None
        for month, raw in sorted((row.get("monthly_need") or {}).items()):
            amount = number(raw)
            try:
                month_valid = datetime.date.fromisoformat(month).day == 1
            except (ValueError, TypeError):
                month_valid = False
            if amount is None or amount < 0 or not month_valid:
                programme_known = False
            covered = min(available, amount) if programme_known else None
            gap = amount - covered if programme_known else None
            if covered is not None:
                available -= covered
            months.append({"month": month, "to_pay": amount, "covered": covered,
                           "uncovered": gap, "basis": "chapter_programme"})
        past = max(0.0, -(left or 0.0)) if known and left is not None else None
        gap = max(0.0, number(row.get("amount")) or 0.0) if known else None
        future_gap = (sum(m["uncovered"] for m in months) if programme_known else None)
        chapters.append({"chapter": row["chapter"], "to_pay": number(row.get("to_pay")),
                         "available_limit": max(0.0, left) if left is not None else None,
                         "remaining_limit": left, "calculated_uncovered": gap,
                         "future_uncovered": future_gap,
                         "confirmed_uncovered": None, "past_over_limit": past,
                         "matches": (abs(gap - past - future_gap) < 1e-6 * max(1.0, abs(gap))
                                     if gap is not None and past is not None and future_gap is not None else None),
                         "months": months, "source": "funding_schedule" if row.get("by_schedule") else "financial_model",
                         "work_allocation_known": False})
    items = []
    for item in comp.get("budget_items") or []:
        code = str(item.get("code") or "")
        items.append({"code": code, "name": item.get("name") or "", "chapter": item.get("chapter") or "",
                      "kind": "admin" if code == "2.4" or code.startswith("2.4.") else "model_article",
                      "source": item.get("source") or {},
                      "model_plan": number(item.get("plan")) if (item.get("known_fields") or {}).get("plan", True) else None,
                      "monthly_model_plan": dict(item.get("monthly") or {}),
                      "to_pay_at_cut": None, "covered": None, "uncovered": None,
                      "reason": "Нет проверенной денежной привязки оплат и доступного лимита к этой строке"})
    details = []
    for item in (schedule or {}).get("detail_rows") or []:
        details.append({**item, "to_pay_at_cut": None, "covered": None, "uncovered": None,
                        "reason": "План и остаток графика не являются доказанным дефицитом статьи"})
    return {"cut": cut, "chapters": chapters, "model_articles": items, "schedule_articles": details,
            "calculated_chapter_total": (sum(r["calculated_uncovered"] for r in chapters) if known else None),
            "work_allocation_known": False,
            "coverage_columns_state": "not_read_by_supported_parser",
            "coverage_columns_reason": "Значения и год колонок «Банк/Резерв» требуют отдельной проверки заголовков; отсутствие покрытия в файле не установлено"}


def display_rows(r: dict) -> list[dict]:
    """Shared labels and values; the browser never reconstructs the equation."""
    def row(key: str, label: str, note: str = "") -> dict:
        return {"key": key, "label": label, "value": r[key], "note": note}
    rows = [row("budget", "Утверждённый бюджет"),
            row("bank_limit_total", "Лимит банка", "Полный лимит уже включает оплаченное"),
            row("paid_at_cut", "Оплачено с начала проекта", "На " + r["cut"]),
            row("remaining_bank_limit", "Остаток лимита банка", "Лимит минус оплаченное"),
            row("calculated_additional", "Расчётная дополнительная потребность",
                "Финансовая сверка не завершена. " + "; ".join(r["reasons"]))]
    names = {"unallocated_budget": "Бюджет без денежной главы",
             "schedule_difference": "Разница модели и графика",
             "payment_difference": "Несверенные оплаты",
             "outside_bank_scope": "Расходы вне банковского контура"}
    rows += [{"key": item["kind"], "label": names[item["kind"]],
              "value": item["amount"], "note": item["reason"]}
             for item in r["components"] if item["amount"] is None or abs(item["amount"]) > 0.5]
    if r["unused_capacity"] is not None and r["unused_capacity"] > 0.5:
        rows.append(row("unused_capacity", "Неиспользуемая часть лимита",
                        "Вычитается из суммы источников в сверке бюджета"))
    return rows


def breakdown_rows(detail: dict) -> list[dict]:
    """Separate chapter totals, their months, and unallocated source catalogues."""
    rows = []
    for ch in detail["chapters"]:
        cover = (sum(m["covered"] for m in ch["months"])
                 if all(m["covered"] is not None for m in ch["months"]) else None)
        rows.append({"kind": "chapter", "name": "Глава " + ch["chapter"], "period": "Итого",
                     "source_plan": None, "to_pay": ch["to_pay"], "covered": cover,
                     "uncovered": ch["calculated_uncovered"],
                     "note": ("Включает превышение лимита уже оплаченным; это не будущая работа"
                              if ch["past_over_limit"] else "Расчёт по программе главы; по работам не распределён")})
        if ch["past_over_limit"]:
            rows.append({"kind": "past", "name": "Глава " + ch["chapter"],
                         "period": "Превышение лимита уже оплаченным", "source_plan": None,
                         "to_pay": None, "covered": None, "uncovered": ch["past_over_limit"],
                         "note": "Входит в итог главы; не относится к неоплаченным работам"})
        rows += [{"kind": "month", "name": "Глава " + ch["chapter"], "period": m["month"],
                  "source_plan": None, "to_pay": m["to_pay"], "covered": m["covered"],
                  "uncovered": m["uncovered"], "note": "Часть итога главы, не дополнительная сумма"}
                 for m in ch["months"]]
    for item in detail["model_articles"]:
        source = item["source"]
        rows.append({"kind": item["kind"], "name": item["code"] + " " + item["name"],
                     "period": "План финансовой базы", "source_plan": item["model_plan"],
                     "to_pay": None, "covered": None, "uncovered": None,
                     "monthly_source_plan": item["monthly_model_plan"],
                     "note": item["reason"], "source": source})
    for item in detail["schedule_articles"]:
        rows.append({"kind": "schedule_article", "name": item["code"] + " " + item["name"],
                     "period": "Остаток в графике", "source_plan": item.get("source_remaining"),
                     "to_pay": None, "covered": None, "uncovered": None,
                     "monthly_source_plan": item["monthly_plan"], "source": item["source"],
                     "note": "Покрытие этой работы из графика ещё не разобрано и не подтверждено"})
    return rows


def lines(reconciliation: dict | None, money: Any) -> list[str]:
    if not reconciliation:
        return []
    r = reconciliation
    out = [f"Бюджет {money(r['budget'])}: оплачено на дату {money(r['paid_at_cut'])}, "
           f"остаток лимита {money(r['remaining_bank_limit'])}, расчётная дополнительная "
           f"потребность {money(r['calculated_additional'])}."]
    for item in r["components"]:
        if item["amount"] is None or abs(item["amount"]) > 0.5:
            out.append(item["reason"] + ": " + money(item["amount"]) + ".")
    if r["unused_capacity"] is not None and r["unused_capacity"] > 0.5:
        out.append("Неиспользуемая часть лимита: " + money(r["unused_capacity"]) + ".")
    if r["reasons"]:
        out.append("Финансирование требует уточнения: " + "; ".join(r["reasons"]) + ".")
    out.append("Финансовая сверка первичных источников не завершена.")
    return out
