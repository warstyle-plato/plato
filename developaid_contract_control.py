"""Deviation of the contract's fact from its accumulated plan, lag in days and the forecast.

The plan is the edition in force on the cut (`developaid_contract_plan`), the
fact is the KS-6a priced by the estimate (`developaid_contract_fact`); both
are money on the same ГПР lines. For every line and for the contract:

- deviation = fact − plan on the cut, in money and in % of the plan;
- lag (owner's decision 5А) = days back from the cut to the day when the
  accumulated plan equalled today's fact; ahead = days forward to the day when
  the plan reaches it;
- the behind volume = plan − fact, also in natural units when all positions of
  the line are measured in one unit.

The forecast keeps the lag of each line until its end: an unfinished line
behind the plan finishes later by its lag, a line on or ahead of the plan by
its schedule. The latest forecast finish is compared with the contract
deadline of the register, else with the end of the schedule. This is a
separate report of the contract: it does not move the project РНВ (6А).
"""
from __future__ import annotations

import datetime as dt

import developaid_contract_plan as plan
from developaid_monitor_statement_union import _unit

ASSUMPTION = ("Отставание в днях — на сколько дней назад от даты среза план нарастающим итогом был равен "
              "сегодняшнему факту. Прогноз считает, что отставание строки сохранится до её окончания: срок "
              "отстающей строки сдвигается на число дней отставания, а срок остальных строк остаётся по графику.")
_ROUND = 1.0  # A ruble: the plan is spread over days, so a smaller gap is rounding, not a deviation.


def _day(iso):
    return dt.date.fromisoformat(iso)


def _first_day(curve, target, low: dt.date, high: dt.date) -> dt.date:
    """The earliest day of [low, high] on which the non-decreasing `curve` reaches `target`; `high` if none."""
    while low < high:
        middle = low + (high - low) // 2
        if curve(middle) >= target - _ROUND:
            high = middle
        else:
            low = middle + dt.timedelta(days=1)
    return low


def _span(line, start):
    begin, finish = _day(line["start"]), _day(line["finish"])
    if start and start > begin:
        begin, finish = start, max(finish, start)
    return begin, finish


def _measure(curve, fact, planned, total, begin, finish, day):
    """State of a plan `curve` against `fact` on `day`: lag or ahead days and the forecast finish."""
    if total and fact >= total - _ROUND:
        state = "done"
    elif abs(fact - planned) <= _ROUND:
        state = "on_plan" if planned > _ROUND else "not_due"
    else:
        state = "behind" if fact < planned else "ahead"
    lag = ahead = 0
    if state == "behind":
        lag = (day - _first_day(curve, fact, begin - dt.timedelta(days=1), day)).days
    elif state in ("ahead", "done") and fact > planned + _ROUND:
        ahead = (_first_day(curve, min(fact, total), day, max(finish, day)) - day).days
    forecast = None if state == "done" else finish + dt.timedelta(days=lag)
    return state, lag, ahead, forecast


def _volume(line, share, volumes):
    known = line.get("volume")
    if not known:
        return None
    unit = _unit(known["unit"])
    done = sum(v["quantity"] for v in volumes if _unit(v["unit"]) == unit)
    if any(_unit(v["unit"]) != unit for v in volumes):
        return None
    planned = known["quantity"] * share
    return {"unit": known["unit"], "quantity": known["quantity"], "planned": planned, "fact": done,
            "behind": max(planned - done, 0.0)}


def build(planned: dict, fact: dict, deadline: str | None, deadline_label: str, cut: str) -> dict:
    """Deviation, lag and forecast of the edition in force of `planned` against `fact` on `cut`."""
    result = {"cut": cut, "assumption": ASSUMPTION, "note": "", "total": None, "lines": [], "behind": [],
              "ahead": [], "forecast": None}
    current = next((e for e in planned.get("editions") or [] if e.get("in_force")), None)
    if current is None:
        result["note"] = "Отклонение не рассчитано: на дату среза нет действующей редакции плана."
        return result
    if fact.get("note"):
        result["note"] = "Отклонение от плана не рассчитано, потому что нет факта. " + fact["note"]
        return result
    if not current["lines"]:
        result["note"] = "Отклонение не рассчитано: в плане нет ни одной строки с подтверждённой связью."
        return result
    day = _day(cut)
    start = _day(current["start"]) if current.get("start") else None
    done_by_code = {x["code"]: x for x in fact.get("lines") or []}
    finishes = []
    for line in current["lines"]:
        got = done_by_code.get(line["code"]) or {"fact": 0.0, "volumes": []}
        begin, finish = _span(line, start)
        curve = lambda d, line=line: line["amount"] * plan.done(line, d, start)
        state, lag, ahead, forecast = _measure(curve, got["fact"], line["planned"], line["amount"],
                                               begin, finish, day)
        share = line["planned"] / line["amount"] if line["amount"] else 0.0
        row = {"code": line["code"], "name": line["name"], "start": line["start"], "finish": line["finish"],
               "amount": line["amount"], "planned": line["planned"], "fact": got["fact"],
               "deviation": got["fact"] - line["planned"],
               "percent": (got["fact"] - line["planned"]) / line["planned"] if line["planned"] else None,
               "state": state, "lag_days": lag, "ahead_days": ahead,
               "behind_amount": max(line["planned"] - got["fact"], 0.0),
               "volume": _volume(line, share, got["volumes"]),
               "forecast_finish": forecast.isoformat() if forecast else None,
               "over": got["fact"] > line["amount"] + _ROUND}
        result["lines"].append(row)
        if forecast:
            finishes.append((forecast, row))
    rows = result["lines"]
    result["behind"] = [r["code"] for r in sorted((r for r in rows if r["state"] == "behind"),
                                                  key=lambda r: (-r["lag_days"], -r["behind_amount"]))]
    result["ahead"] = [r["code"] for r in sorted((r for r in rows if r["ahead_days"]),
                                                 key=lambda r: -r["ahead_days"])]
    spans = [_span(line, start) for line in current["lines"]]
    first, last = min(b for b, _ in spans), max(f for _, f in spans)
    curve = lambda d: plan.planned(current, d, start)
    total_fact = sum(r["fact"] for r in rows)
    state, lag, ahead, _ = _measure(curve, total_fact, current["planned"], current["total"], first, last, day)
    result["total"] = {"amount": current["total"], "planned": current["planned"], "fact": total_fact,
                       "deviation": total_fact - current["planned"],
                       "percent": (total_fact - current["planned"]) / current["planned"]
                       if current["planned"] else None,
                       "state": state, "lag_days": lag, "ahead_days": ahead,
                       "behind_amount": max(current["planned"] - total_fact, 0.0)}
    result["forecast"] = _forecast(finishes, deadline, deadline_label, last, current, day)
    return result


def _forecast(finishes, deadline, deadline_label, last, current, day):
    if deadline:
        limit, label = _day(deadline), deadline_label or "срок договора"
    else:
        limit, label = last, "окончание графика действующей редакции"
    outside = sum(item["count"] for item in (current.get("outside") or {}).values())
    forecast = {"deadline": limit.isoformat(), "deadline_label": label, "from_register": bool(deadline),
                "finish": None, "days_over": 0, "threat": False, "drivers": [], "outside": outside,
                "passed": limit < day}
    if not finishes:
        return forecast
    finish = max(f for f, _ in finishes)
    forecast["finish"] = finish.isoformat()
    forecast["days_over"] = max((finish - limit).days, 0)
    forecast["threat"] = finish > limit
    forecast["drivers"] = [row["code"] for f, row in sorted(finishes, key=lambda x: x[0], reverse=True)
                           if f > limit]
    return forecast
