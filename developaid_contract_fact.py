"""Accumulated fact of a contract: KS-6a quantities priced by the Расчёт and laid on the ГПР lines.

A fact row is one dated period of one work of the cumulative KS-6a. It belongs
to the edition of the plan in force on the last day of its period, and its money
is the quantity × the unit price of that edition's «Расчёт» (owner's decision
4А), not the sum written in the KS. The row finds its position by number, or by
name and unit; a finer row numbered under a position (4.1.1 under 4.1) with the
same unit is summed into it. A number and a name that point to different
positions, another unit or no position at all go to review with the reason,
never a guess.

The money of a position reaches the ГПР lines through the confirmed link of the
same position (number, name and unit) in the edition in force on the cut. Work
of an estimate «на завершение работ» counts from its agreement date: earlier
work was accepted before the agreement and is shown beside the plan, not in it.

A line is complete by volume (owner's decision А) when every position linked to
it has KS-6a works and each of them reached its full volume of the statement by
the cut; the money of a complete line may stay below its cost in the estimate.
The last day of the line is the end of its last KS period up to the cut.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

import developaid_contract_schedule_links as links
from developaid_monitor_contracts import _norm
from developaid_monitor_statement_union import _unit

_QUANTITY = 1e-6  # Quantities of the KS and the statement are the same printed numbers: only float noise differs.
ASSUMPTION = ("Работы периода КС относятся к редакции расчёта, которая действовала в последний день периода. "
              "Деньги факта — объём КС × цена за единицу этой редакции, а не сумма, записанная в КС.")
_STATUSES = ("proposed", "review", "extra", "missing")


def _day(iso):
    return dt.date.fromisoformat(iso)


def _code(value):
    return re.sub(r"\s+", "", str(value or "")).strip(".")


def acts(row: dict | None) -> dict | None:
    """Dated periods of the contract's KS-6a works up to the cut and the works that give no dated fact.

    `row` is the contract of the register on the cut; None when the register has no such contract.
    """
    if row is None:
        return None
    found, unread, works, sums = [], [], [], {}
    for index, item in enumerate(row.get("physical_items") or []):
        if item.get("is_group") or item.get("is_duplicate"):
            continue  # A group sums its works; a verified duplicate repeats one.
        periods = list(item.get("periods") or []) + list(item.get("undated_periods") or [])
        for period in periods:
            if period.get("amount") is not None:
                sums[period.get("label") or ""] = sums.get(period.get("label") or "", 0.0) + period["amount"]
        if item.get("completed_quantity") is None:
            # Periods named by an act only may still be dated by the act (developaid_contract_act_dates).
            unread.append({"number": item.get("position") or "", "name": item.get("name") or "",
                           "unit": item.get("unit") or "", "reason": item.get("quantity_basis") or "",
                           "source": item.get("source") or {}, "item": index,
                           "plan_quantity": item.get("plan_quantity"),
                           "reported_quantity": item.get("reported_completed_quantity"),
                           "periods": [{"label": p.get("label") or "", "quantity": p.get("quantity"),
                                        "amount": p.get("amount"), "start": p.get("date_start"),
                                        "end": p.get("date_end"), "source": p.get("source") or {}}
                                       for p in periods]})
            continue
        works.append({"item": index, "number": item.get("position") or "", "name": item.get("name") or "",
                      "unit": item.get("unit") or "", "plan_quantity": item.get("plan_quantity")})
        for period in item.get("periods") or []:
            if not period.get("quantity") and not period.get("amount"):
                continue  # Nothing done in this period; a sum without a volume goes to review in `build`.
            found.append({"number": item.get("position") or "", "name": item.get("name") or "",
                          "unit": item.get("unit") or "", "quantity": period.get("quantity") or None,
                          "act_amount": period.get("amount"), "start": period.get("date_start"),
                          "end": period["date_end"], "label": period.get("label") or "",
                          "item": index,
                          "source": period.get("source") or item.get("source") or {}})
    summary = [act for source in row.get("financial_sources") or [] for act in source.get("acts") or []]
    return {"acts": found, "unread": unread, "works": len(works), "items": works, "period_amounts": sums,
            "summary_acts": summary,
            "deadline": row.get("deadline"), "deadline_label": (row.get("deadline_source") or {}).get("label") or ""}


def unavailable(reason: str) -> dict:
    """No fact, because the register of the cut could not be built: `reason` says why."""
    return {"acts": [], "unread": [], "works": 0, "items": [], "problem": reason}


def match(act: dict, estimates: list[dict]):
    """(estimate index, position index, how) of `act` among the positions of `estimates`, or a reason."""
    number, unit, name = _code(act["number"]), _unit(act["unit"]), _norm(act["name"])
    every = [(e, i) for e, estimate in enumerate(estimates) if estimate.get("scope") != "accepted"
             for i, _ in enumerate(estimate.get("positions") or [])]
    position = lambda c: estimates[c[0]]["positions"][c[1]]
    numbered = [c for c in every if number and _code(position(c)["number"]) == number]
    same = [c for c in numbered if _unit(position(c)["unit"]) == unit]
    named = [c for c in every if _norm(position(c)["name"]) == name and _unit(position(c)["unit"]) == unit]
    if len(same) > 1:
        same = [c for c in same if c in named]
        if len(same) != 1:
            return f"В расчёте несколько позиций № {number} в «{act['unit']}»: какая из них выполнена, не ясно."
    if same:
        if named and same[0] not in named:
            return (f"Номер указывает на позицию № {number}, а название и единица — на позицию "
                    f"№ {position(named[0])['number'] or 'без номера'} расчёта.")
        return (*same[0], "number")
    if numbered:
        return (f"В расчёте позиция № {number} измеряется в «{position(numbered[0])['unit']}», "
                f"а в КС — в «{act['unit']}»: объём не пересчитать в деньги.")
    if len(named) == 1:
        return (*named[0], "name")
    if named:
        return "В расчёте несколько позиций с таким названием и единицей: какая из них выполнена, не ясно."
    parents = [c for c in every if number and _code(position(c)["number"])
               and number.startswith(_code(position(c)["number"]) + ".")
               and _unit(position(c)["unit"]) == unit]
    longest = max((len(_code(position(c)["number"])) for c in parents), default=0)
    parents = [c for c in parents if len(_code(position(c)["number"])) == longest]
    if len(parents) == 1:
        return (*parents[0], "nested")
    return ("В расчёте нет позиции с этим номером или с таким же названием и единицей"
            + (f" (№ {act['number']})" if number else "") + ".")


def _price(position):
    price = (position.get("unit_price") or {}).get("total")
    if price is None and position.get("quantity") and (position.get("amount") or {}).get("total") is not None:
        price = position["amount"]["total"] / position["quantity"]
    return price


def _money(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _month_ends(first: dt.date, last: dt.date):
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield min(dt.date(year, month, calendar.monthrange(year, month)[1]), last)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def build(editions: list[dict], in_force: str | None, found: dict | None, cut: str) -> dict:
    """The fact on `cut` by the lines of the edition `in_force` (sha256) of the plan."""
    result = {"cut": cut, "assumption": ASSUMPTION, "total": 0.0, "lines": [], "months": [], "positions": [],
              "outside": {status: {"count": 0, "amount": 0.0} for status in _STATUSES},
              "before": None, "review": [], "unread": [], "price_differs": 0, "after_cut": 0, "note": ""}
    if found is None:
        result["note"] = "Накопительная КС-6а этого договора на дату среза не найдена: факт не рассчитан."
        return result
    if found.get("problem"):
        result["note"] = f"Факт не рассчитан: {found['problem']}"
        return result
    result["unread"] = found["unread"]
    current = next((e for e in editions if e["sha256"] == in_force), None)
    if current is None:
        result["note"] = "Нет редакции плана, действующей на дату среза: факт не с чем сопоставить."
        return result
    if not found.get("works"):
        # No work with a known quantity: a zero here would be a missing KS-6a, not an answer.
        result["note"] = "В накопительной КС-6а этого договора нет выполнения с датированными периодами до даты среза."
        return result
    dated = sorted((e for e in editions if e.get("date")), key=lambda e: e["date"])
    start = _day(current["start"]) if current.get("start") else None
    if start:
        result["before"] = {"start": current["start"], "count": 0, "amount": 0.0, "unpriced": 0}
    links_now = {p["key"]: p for e in current["estimates"] if e.get("scope") != "accepted"
                 for p in (e.get("links") or {}).get("positions") or []}
    lines, volumes, positions, dated_money = {}, {}, {}, []
    last, done_quantity = {}, {}
    for act in found["acts"]:
        end = _day(act["end"])
        if end > _day(cut):
            result["after_cut"] += 1
            continue
        if act["quantity"] is None:
            result["review"].append({**act, "reason": f"В периоде КС записана сумма {_money(act['act_amount'])}, "
                                                      "а объём не записан (например, оплачена только поставка "
                                                      "материалов): без объёма выполнение не пересчитать по цене "
                                                      "расчёта."})
            continue
        edition = next((e for e in reversed(dated) if _day(e["date"]) <= end), None)
        if start and end < start and edition is None:
            # Accepted before the agreement, in a period whose Расчёт is not in the card.
            done_quantity[act["item"]] = done_quantity.get(act["item"], 0.0) + act["quantity"]
            result["before"]["count"] += 1
            result["before"]["unpriced"] += 1
            continue
        if edition is None:
            result["review"].append({**act, "reason": "Период КС закончился раньше даты первой редакции расчёта, "
                                                      "загруженной в карточку."})
            continue
        found_at = match(act, edition["estimates"])
        if isinstance(found_at, str):
            result["review"].append({**act, "edition": edition["title"], "reason": found_at})
            continue
        e, i, how = found_at
        position = edition["estimates"][e]["positions"][i]
        price = _price(position)
        if price is None:
            result["review"].append({**act, "edition": edition["title"],
                                     "reason": f"У позиции № {position['number']} в расчёте не прочитана цена за единицу."})
            continue
        # Only the volume that entered the fact counts toward a complete line: review volume is not known done.
        done_quantity[act["item"]] = done_quantity.get(act["item"], 0.0) + act["quantity"]
        money = act["quantity"] * price
        if act["act_amount"] is not None and abs(act["act_amount"] - money) > max(1.0, abs(money) * 0.005):
            result["price_differs"] += 1
        if start and end < start:
            place = "before"
            result["before"]["count"] += 1
            result["before"]["amount"] += money
        else:
            link = links_now.get(links.position_key(position))
            place = link["status"] if link else "missing"
            if place == "confirmed":
                for line in link["lines"]:
                    lines[line["code"]] = lines.get(line["code"], 0.0) + money * line["share"]
                    unit = volumes.setdefault(line["code"], {}).setdefault(
                        _unit(position["unit"]), {"unit": position["unit"], "quantity": 0.0})
                    unit["quantity"] += act["quantity"] * line["share"]
                    last[line["code"]] = max(last.get(line["code"], act["end"]), act["end"])
                dated_money.append((end, money))
                result["total"] += money
            else:
                result["outside"][place]["count"] += 1
                result["outside"][place]["amount"] += money
        key = (edition["sha256"], e, i, place)
        row = positions.setdefault(key, {
            "number": position["number"], "name": position["name"], "unit": position["unit"], "price": price,
            "edition": edition["title"], "how": how, "place": place, "quantity": 0.0, "amount": 0.0,
            "act_amount": 0.0, "periods": 0, "last": act["end"]})
        row["quantity"] += act["quantity"]
        row["amount"] += money
        row["act_amount"] = None if act["act_amount"] is None or row["act_amount"] is None \
            else row["act_amount"] + act["act_amount"]
        row["periods"] += 1
        row["last"] = max(row["last"], act["end"])
    order = [line["code"] for line in links.leaves(current.get("schedule"))]
    # Every work of the statement, done or not yet, belongs to its position of the edition in force.
    items_of = {}
    for work in found.get("items") or []:
        found_at = match(work, current["estimates"])
        if not isinstance(found_at, str):
            e, i, _ = found_at
            items_of.setdefault(links.position_key(current["estimates"][e]["positions"][i]), []).append(work)
    full = lambda work: bool(work["plan_quantity"]) and (
        done_quantity.get(work["item"], 0.0) >= work["plan_quantity"] - _QUANTITY)
    keys_of = {}
    for key, link in links_now.items():
        if link["status"] == "confirmed":
            for line in link["lines"]:
                keys_of.setdefault(line["code"], []).append(key)

    def complete(code):
        keys = keys_of.get(code) or []
        return bool(keys) and all(items_of.get(key) and all(full(work) for work in items_of[key]) for key in keys)

    result["lines"] = [{"code": code, "fact": lines[code], "volumes": list(volumes[code].values()),
                        "last": last[code], "complete": complete(code)}
                       for code in order if code in lines]
    result["positions"] = list(positions.values())
    if dated_money:
        day = _day(cut)
        first = min(end for end, _ in dated_money)
        result["months"] = [{"month": end.isoformat()[:7], "fact": sum(m for d, m in dated_money if d <= end)}
                            for end in _month_ends(first, day)]
    return result
