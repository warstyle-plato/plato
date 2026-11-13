"""Accumulated plan of a contract: money of the confirmed links spread over the ГПР lines.

An edition of the plan is a document of the card that brings a «Расчёт» or a
schedule: the latest estimate and the latest schedule at or before it make the
plan from its date until the next edition (owner's decision 7А: an agreement
recalculates the accumulated plan). A confirmed link and an unambiguous proposed
one enter the plan at once (methodology of 12.11.2026, rule 3: checking a link
by hand is an option, not a gate); a position on review or an extra one is
counted outside it with its money, and the reason stays with the position.

The schedule has no monthly sums, so the money of a line is spread evenly over
the days of its bar, and this is labelled as an assumption (2А). An estimate
«на завершение работ» holds only the work left at its agreement date: its money
is spread over the part of each bar from that date, and a line whose bar ended
before the agreement is due on the agreement date. Work accepted before such an
agreement is not in this plan; an annex «на выполненные и принятые работы» of the
same agreement is shown beside it.
"""
from __future__ import annotations

import calendar
import datetime as dt

import developaid_contract_schedule_links as links
from developaid_monitor_statement_union import _unit

EVEN_SPLIT = ("Стоимость строки распределена по дням её срока поровну: в графике нет сумм по месяцам, "
              "это допущение, а не данные графика.")
_OUTSIDE = ("review", "extra")
_LINKED = ("confirmed", "proposed")


def _day(iso):
    return dt.date.fromisoformat(iso)


def _shown(day):
    return day.strftime("%d.%m.%Y")


def done(line: dict, day: dt.date, start: dt.date | None = None) -> float:
    """Planned share of `line` by the end of `day`; the plan starts not before `start`."""
    begin, finish = _day(line["start"]), _day(line["finish"])
    if start and start > begin:
        if start > finish:
            return 1.0 if day >= start else 0.0
        begin = start
    if day < begin:
        return 0.0
    return min(1.0, ((day - begin).days + 1) / ((finish - begin).days + 1))


def _month_ends(first: dt.date, last: dt.date):
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield dt.date(year, month, calendar.monthrange(year, month)[1])
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _volume(parts):
    """Natural volume of a line: only when all its positions are measured in one unit with a quantity."""
    if not parts or len({_unit(unit) for unit, _, _ in parts}) != 1 or any(q is None for _, q, _ in parts):
        return None
    return {"unit": parts[0][0], "quantity": sum(q * share for _, q, share in parts)}


def edition(estimates: list[dict], schedule: dict | None, start: dt.date | None) -> dict:
    """Plan lines of linked `estimates` over `schedule`; `start` is the date of an estimate «на завершение»."""
    dated = {line["code"]: line for line in links.leaves(schedule)}
    money, outside, without = {}, {status: {"count": 0, "amount": 0.0} for status in _OUTSIDE}, 0
    volumes, auto, auto_positions = {}, {}, 0
    accepted, accepted_without = None, 0
    for estimate in estimates:
        positions = (estimate.get("links") or {}).get("positions") or []
        if estimate.get("scope") == "accepted":
            # A position without a sum is named, not counted as zero: the sum is then of the others only.
            known = [p["amount"] for p in positions if p["amount"] is not None]
            accepted_without += len(positions) - len(known)
            if known or not positions:
                accepted = (accepted or 0.0) + sum(known)
            continue
        for position in positions:
            if position["amount"] is None:
                without += 1
            elif position["status"] in _OUTSIDE:
                outside[position["status"]]["count"] += 1
                outside[position["status"]]["amount"] += position["amount"]
            elif position["status"] in _LINKED:
                # A position split over several lines is one automatic link, not one per line.
                auto_positions += position["status"] == "proposed"
                for line in position["lines"]:
                    money[line["code"]] = money.get(line["code"], 0.0) + position["amount"] * line["share"]
                    auto[line["code"]] = auto.get(line["code"], 0) + (position["status"] == "proposed")
                    volumes.setdefault(line["code"], []).append(
                        (position.get("unit"), position.get("quantity"), line["share"]))
    lines = [{"code": code, "name": dated[code]["name"], "start": dated[code]["start"],
              "finish": dated[code]["finish"], "amount": amount, "volume": _volume(volumes.get(code)),
              "auto": auto.get(code, 0),
              "overdue": bool(start and _day(dated[code]["finish"]) < start)}
             for code, amount in sorted(money.items(), key=lambda kv: list(dated).index(kv[0]))]
    return {"lines": lines, "total": sum(line["amount"] for line in lines), "outside": outside,
            "auto": auto_positions,
            "without_amount": without, "accepted": accepted, "accepted_without_amount": accepted_without}


def planned(plan: dict, day: dt.date, start: dt.date | None) -> float:
    return sum(line["amount"] * done(line, day, start) for line in plan["lines"])


def build(editions: list[dict], cut: str) -> dict:
    """The plan of every edition and the one in force on `cut`.

    Each edition: `title`, `sha256`, `date` (ISO or None), `estimates` with
    applied links, `estimate_title` (the document of the estimates), `schedule`
    (or None), `schedule_title`, `start` (ISO date of an estimate «на завершение»
    or None).
    """
    day = _day(cut)
    dated = [e for e in editions if e.get("date")]
    in_force = next((e for e in reversed(dated) if _day(e["date"]) <= day), None)
    shown = []
    for item in editions:
        start = _day(item["start"]) if item.get("start") else None
        plan = edition(item["estimates"], item.get("schedule"), start)
        later = next((e["date"] for e in dated if item.get("date") and e["date"] > item["date"]), None)
        entry = {"sha256": item["sha256"], "title": item["title"], "date": item.get("date"),
                 "estimate": item.get("estimate_title") or item["title"],
                 "until": (_day(later) - dt.timedelta(days=1)).isoformat() if later else None,
                 "schedule": item.get("schedule_title") or "", "start": item.get("start"),
                 "in_force": item is in_force, **plan}
        # The plan on the cut belongs to the edition in force: an older one would answer with a superseded plan.
        for line in entry["lines"]:
            line["planned"] = line["amount"] * done(line, day, start) if entry["in_force"] else None
        entry["planned"] = sum(line["planned"] for line in entry["lines"]) if entry["in_force"] else None
        entry["overdue"] = sum(1 for line in entry["lines"] if line["overdue"])
        if entry["lines"]:
            first = start or min(_day(line["start"]) for line in entry["lines"])
            last = max(max(_day(line["finish"]) for line in entry["lines"]), first)
            entry["months"] = [{"month": end.isoformat()[:7], "planned": planned(plan, end, start)}
                               for end in _month_ends(first, last)]
        else:
            entry["months"] = []
        if not item.get("date"):
            entry["note"] = "Дата документа не прочитана: для плана на дату среза эта редакция не выбирается."
        shown.append(entry)
    return {"cut": cut, "assumption": EVEN_SPLIT, "editions": shown,
            "in_force": in_force["sha256"] if in_force else None,
            "note": "" if in_force else (
                f"На дату среза {_shown(day)} ни одна редакция с Расчётом ещё не действовала." if dated
                else "")}
