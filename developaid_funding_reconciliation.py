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
    """Compare the complete approved budget with payments and available limits.

    The budget gap is a legitimate subtraction of independently read totals.
    The schedule controls calendar comparisons, never the approved budget. A
    missing article allocation cannot make known aggregate totals unknown.
    """
    fields = comp.get("known_fields") or {}
    budget = number(comp.get("total")) if fields.get("total", True) else None
    paid = number(own.get("paid")) if own.get("payments_known", True) else None
    limit = number(own.get("limit")) if own.get("limits_known", True) else None
    left = (number(own.get("left")) if paid is not None and limit is not None else None)
    rows = [r for r in own.get("rows") or [] if r.get("chapter")]
    chapters = {r["chapter"] for r in rows}
    unallocated = chapter_flow.get("") or {}
    unmapped = number(unallocated.get("total", 0.0))
    outside_values = [number(f.get("total")) for ch, f in chapter_flow.items()
                      if ch and ch not in chapters]
    outside = sum(outside_values) if all(v is not None for v in outside_values) else None
    def composition_total(predicate, fallback):
        # chapter_flow's legacy floats cannot restore a missing source cell.
        items = comp.get("budget_items")
        if not isinstance(items, list):
            return fallback if fields.get("total", True) else None
        values = [number(item.get("total")) if (item.get("known_fields") or {}).get("total", True)
                  else None for item in items if predicate(item.get("chapter") or "")]
        return sum(values) if all(v is not None for v in values) else None
    unmapped = composition_total(lambda ch: not ch, unmapped)
    outside = composition_total(lambda ch: bool(ch) and ch not in chapters, outside)
    chapter_values = [(number((chapter_flow.get(r["chapter"]) or {}).get("total")),
                       number(r.get("paid")), number(r.get("left"))) for r in rows]
    totals_known = budget is not None and paid is not None and limit is not None and left is not None
    # Full limit includes payments. Only positive remainders are available;
    # payments exceeding a chapter limit do not reduce another chapter's cash.
    row_lefts = [number(r.get("left")) for r in rows]
    available = (sum(max(0.0, v) for v in row_lefts) if totals_known and rows
                 and all(v is not None for v in row_lefts) else
                 max(0.0, left) if totals_known else None)
    over_limit = (sum(max(0.0, -v) for v in row_lefts) if available is not None and rows
                  and all(v is not None for v in row_lefts) else
                  max(0.0, -left) if totals_known else None)
    chapter_scope_known = (totals_known and bool(rows) and unmapped == 0 and outside == 0
                           and all(all(v is not None for v in values) for values in chapter_values)
                           and abs(sum(v[0] for v in chapter_values) - budget) <= 1e-6 * max(1., abs(budget))
                           and abs(sum(v[1] for v in chapter_values) - paid) <= 1e-6 * max(1., abs(paid)))
    # The economic article map is not a bank restriction. Moving the same
    # admin cost between chapters must not change the aggregate budget gap.
    # Chapter comparisons remain diagnostics until an independently verified
    # restriction on using a limit is available.
    if totals_known:
        applicable = min(available, max(0., budget - paid))
        additional = max(0., budget - paid - available)
        paid_excess = max(0., paid - budget)
    else:
        applicable = additional = paid_excess = None
    unused = available - applicable if available is not None and applicable is not None else None
    rhs = paid + available + additional - unused - paid_excess if totals_known else None
    matches = (abs(budget - rhs) <= 1e-6 * max(1., abs(budget))
               if budget is not None and rhs is not None else False)
    section_totals = [number(s.get("total")) for s in comp.get("sections") or []]
    composition_matches = (all(v is not None for v in section_totals)
                           and abs(sum(section_totals) - budget) <= 1e-6 * max(1., abs(budget))
                           if section_totals and budget is not None else None)
    if composition_matches is False:
        matches = False
    # These explain different source versions/compositions; they are never
    # plugs added to or subtracted from the approved-budget equation.
    payments_known = own.get("payments_known", True) is True
    programme_known = own.get("programme_known", True) is True
    payment_difference_known = (payments_known and programme_known
                                and all(fields.get(k, True) for k in ("total", "fact", "plan", "monthly")))
    schedule_used = bool(schedule) or any(row.get("by_schedule") for row in rows)
    schedule_difference_known = (fields.get("total", True) and payments_known and programme_known
                                 and (schedule_policy or {}).get("programme_known", True) is True)
    components = [
        {"kind": "unallocated_budget", "amount": unmapped,
         "reason": "Включено в общий бюджет; денежная глава не подтверждена"},
        {"kind": "schedule_difference", "amount":
             (number(own.get("model_over_schedule")) if schedule_difference_known else None)
             if schedule_used else 0.0,
         "reason": ("Различие бюджета модели и программы графика; общий бюджет не уменьшает"
                    if schedule_difference_known or not schedule_used else
                    "Разница модели и графика не определена: исходные суммы прочитаны не полностью")},
        {"kind": "payment_difference", "amount":
             number(own.get("accounting")) if payment_difference_known else None,
         "reason": ("Факт финансовой базы и оплаты на дату различаются; в сверке использованы оплаты на дату"
                    if payment_difference_known else
                    "Разница финансовой базы и оплат не определена: исходные суммы прочитаны не полностью")},
        {"kind": "outside_bank_scope", "amount": outside,
         "reason": "Расходы вне выбранных банковских глав включены в общий бюджет"},
    ]
    reasons = []
    if composition_matches is False:
        reasons.append("Итог утверждённого бюджета не равен сумме его разделов")
    if budget is None:
        reasons.append("Утверждённый бюджет не прочитан полностью")
    if paid is None:
        reasons.append("Оплаты на дату не прочитаны для всего выбранного состава")
    if limit is None:
        reasons.append("Лимит не прочитан для всего выбранного состава")
    source_completeness = own.get("source_completeness") or {}
    if any("estimate_code" in row.get("fields", [])
           for rows in (source_completeness.get("payments") or {}).values() for row in rows):
        reasons.append("У части платежей не прочитан код РСС; принадлежность к выбранным главам неизвестна")

    policy = schedule_policy or {"state": "not_replaced", "items": [], "added_to_need": 0.0}
    schedule_known = (all(fields.get(k, True) for k in ("fact", "plan", "monthly"))
                      and policy.get("programme_known", True) is True
                      and own.get("programme_known", True) is True and totals_known)
    result = {"schema": 2, "basis": "approved_budget", "cut": cut,
            "budget": budget, "paid_at_cut": paid, "bank_limit_total": limit,
            "remaining_bank_limit": left, "available_bank_limit": available,
            "applicable_bank_coverage": applicable, "over_limit_paid": over_limit,
            "calculated_additional": additional, "aggregate_additional":
                max(0., budget - paid - available) if totals_known else None,
            "confirmed_additional": None, "unused_capacity": unused,
            "paid_above_budget": paid_excess,
            "coverage_scope": "aggregate", "bank_chapters": sorted(chapters),
            "chapter_mapping_complete": bool(chapter_scope_known),
            "components": components, "rhs": rhs, "matches": matches,
            "composition_matches": composition_matches,
            "state": "arithmetically_reconciled" if matches else "needs_reconciliation",
            "reasons": reasons, "admin_schedule": policy,
            "primary_source_gate": "BLOCKED", "financial_acceptance_performed": False,
            "payment_identity_verified": None, "source_dates": {},
            "source_completeness": source_completeness,
            "unallocated_programme": {
                "model_total": unmapped, "model_fact": number(unallocated.get("fact", 0.0)),
                "model_plan": number(unallocated.get("plan", 0.0)),
                "monthly": dict(unallocated.get("monthly") or {}),
                "paid_at_cut": None, "funding_coverage": None}}
    result["display_rows"] = display_rows(result)
    result["need_breakdown"] = need_breakdown(own, comp, cut, schedule_known, schedule)
    detail = result["need_breakdown"]
    detail["approved_budget_gap"] = additional
    programme_gap = detail["calculated_chapter_total"]
    detail["programme_vs_approved_gap"] = (programme_gap - additional
                                           if programme_gap is not None and additional is not None else None)
    detail["display_rows"] = breakdown_rows(detail)
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
                      "economic_kind": "admin" if code == "2.4" or code.startswith("2.4.") else "other",
                      "bank_chapter": item.get("chapter") or None,
                      "bank_chapter_candidates": list(item.get("chapter_candidates") or []),
                      "bank_sources": list(item.get("bank_source_candidates") or []),
                      "source": item.get("source") or {},
                      "model_plan": number(item.get("plan")) if (item.get("known_fields") or {}).get("plan", True) else None,
                      "monthly_model_plan": dict(item.get("monthly") or {}),
                      "to_pay_at_cut": None, "covered": None, "uncovered": None,
                      "reason": "Покрытие отдельных работ из графика ещё не разобрано и не подтверждено"})
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
            row("available_bank_limit", "Доступный остаток лимита банка", "Положительные остатки лимитов на ту же дату"),
            row("calculated_additional", "Расчётная дополнительная потребность",
                "Утверждённый бюджет минус оплаты и применимое доступное покрытие. " + "; ".join(r["reasons"]))]
    names = {"unallocated_budget": "Бюджет без денежной главы",
             "schedule_difference": "Разница модели и графика",
             "payment_difference": "Несверенные оплаты",
             "outside_bank_scope": "Расходы вне банковского контура"}
    rows += [{"key": item["kind"], "label": names[item["kind"]],
              "value": item["amount"], "note": item["reason"]}
             for item in r["components"] if item["amount"] is None or abs(item["amount"]) > 0.5]
    if r["unused_capacity"] is not None and r["unused_capacity"] > 0.5:
        rows.append(row("unused_capacity", "Неиспользуемая часть лимита",
                        "Не покрывает остаток утверждённого бюджета выбранного состава"))
    if r["paid_above_budget"] is not None and r["paid_above_budget"] > 0.5:
        rows.append(row("paid_above_budget", "Оплачено сверх бюджета главы",
                        "Вычитается из источников при сверке утверждённого бюджета"))
    if r["over_limit_paid"] is not None and r["over_limit_paid"] > 0.5:
        rows.append(row("over_limit_paid", "Оплачено сверх лимитов глав",
                        "Уже оплачено; не является доступным остатком"))
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
                              if ch["past_over_limit"] else "Программа главы; не является распределением общей доппотребности")})
        if ch["past_over_limit"]:
            rows.append({"kind": "past", "name": "Глава " + ch["chapter"],
                         "period": "Превышение лимита уже оплаченным", "source_plan": None,
                         "to_pay": None, "covered": None, "uncovered": ch["past_over_limit"],
                         "note": "Входит в итог главы; не относится к неоплаченным работам"})
        rows += [{"kind": "month", "name": "Глава " + ch["chapter"], "period": m["month"],
                  "source_plan": None, "to_pay": m["to_pay"], "covered": m["covered"],
                  "uncovered": m["uncovered"], "note": "Часть программы главы, не дополнительная сумма к общему дефициту"}
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
           f"доступный остаток лимита {money(r['available_bank_limit'])}, расчётная дополнительная "
           f"потребность {money(r['calculated_additional'])}."]
    for item in r["components"]:
        if item["amount"] is None or abs(item["amount"]) > 0.5:
            out.append(item["reason"] + ": " + money(item["amount"]) + ".")
    if r["paid_above_budget"] is not None and r["paid_above_budget"] > 0.5:
        out.append("Оплачено сверх бюджета главы: " + money(r["paid_above_budget"]) + ".")
    if r["unused_capacity"] is not None and r["unused_capacity"] > 0.5:
        out.append("Неиспользуемая часть лимита: " + money(r["unused_capacity"]) + ".")
    if r["reasons"]:
        out.append("Финансирование требует уточнения: " + "; ".join(r["reasons"]) + ".")
    out.append("Финансовая сверка первичных источников не завершена.")
    return out
