"""Plan and fact of the contract's works in natural volumes, three percentages, lag, overdue and forecast.

The plan is the edition in force on the cut (`developaid_contract_plan`), the
fact is the acts КС-2 (or the KS-6a) priced by the estimate
(`developaid_contract_fact`); both lie on the same ГПР lines. Methodology of
12.11.2026 (docs/contract_schedule_control.md):

- a work is measured in its natural volume when all positions of its line are
  measured in one unit with a quantity; otherwise by its money, and it says so;
- three percentages of a work (rule 8): plan done on the cut = fact ÷ plan on the
  cut, readiness = fact ÷ the whole volume, deviation = (fact − plan) ÷ plan, with
  the deviation also in volume; no percent when its base is zero;
- the contract (rule 9, owner's decision 3А): readiness and plan done on the cut
  are the natural readiness of every work weighted by its cost in the estimate;
  a work is counted at most whole, so over-volume of one work never makes
  another unfinished work look done;
- lag (rule 10, decision 5А) = days back from the cut to the day when the
  accumulated plan equalled today's readiness; ahead = days forward to the day
  when the plan reaches it. Overdue is apart: days since the end of the work in
  the ГПР (or the contract deadline) while the work is not finished.

A line is finished when its natural fact reached its volume, when the KS-6a
completed the full volume of its positions, or (without a volume) when its fact
reached its cost (owner's decision А): it has no lag, its finish is the end of
its last KS period, compared with the line's end in the ГПР, and a fact below
the cost is a shortfall in money, not a lag.

The forecast keeps the lag of each line until its end: an unfinished line
behind the plan finishes later by its lag, a line on or ahead of the plan by
its schedule, a finished line on its last KS period. The latest finish is
compared with the contract deadline of the register, else with the end of the
schedule. KS periods the fact could not take (its `review`) are named with their
reasons, and the lag and the deviation are marked incomplete without them. This is a separate report of the
contract: it does not move the project РНВ (6А).
"""
from __future__ import annotations

import datetime as dt

import developaid_contract_plan as plan
from developaid_monitor_statement_union import _unit

ASSUMPTION = ("Отставание в днях — на сколько дней назад от даты среза план нарастающим итогом был равен "
              "сегодняшнему факту. Просрочка считается отдельно: сколько дней прошло после срока работы по "
              "графику, а работа не закончена. Прогноз считает, что отставание строки сохранится до её "
              "окончания: срок отстающей строки сдвигается на число дней отставания, а срок остальных строк "
              "остаётся по графику. Работа закончена, когда выполнен весь её объём; дата окончания — конец "
              "последнего периода КС по ней.")
WEIGHTS = ("Готовность работ — готовность каждой работы в натуре, взвешенная стоимостью работы без материалов. "
           "Поставка материалов учитывается отдельно и не подтверждает выполнение работ. "
           "Работа учитывается не больше чем целиком: сверхобъём одной работы не закрывает другую.")
_ROUND = 1.0  # A ruble: the plan is spread over days, so a smaller gap is rounding, not a deviation.
_SHARE = 1e-6  # Of a volume: the KS and the estimate print the same numbers, only float noise differs.


def _day(iso):
    return dt.date.fromisoformat(iso)


def _first_day(curve, target, low: dt.date, high: dt.date, tol: float) -> dt.date:
    """The earliest day of [low, high] on which the non-decreasing `curve` reaches `target`; `high` if none."""
    while low < high:
        middle = low + (high - low) // 2
        if curve(middle) >= target - tol:
            high = middle
        else:
            low = middle + dt.timedelta(days=1)
    return low


def _span(line, start):
    begin, finish = _day(line["start"]), _day(line["finish"])
    if start and start > begin:
        begin, finish = start, max(finish, start)
    return begin, finish


def _measure(curve, ready, due, begin, finish, day, tol, complete=False):
    """State of a plan `curve` (share of the whole) against the share `ready` on `day`: lag, ahead, forecast."""
    if complete or ready >= 1 - tol:
        state = "done"
    elif abs(ready - due) <= tol:
        state = "on_plan" if due > tol else "not_due"
    else:
        state = "behind" if ready < due else "ahead"
    lag = ahead = 0
    if state == "behind":
        lag = (day - _first_day(curve, ready, begin - dt.timedelta(days=1), day, tol)).days
    elif state in ("ahead", "done") and ready > due + tol:
        ahead = (_first_day(curve, min(ready, 1.0), day, max(finish, day), tol) - day).days
    forecast = None if state == "done" else finish + dt.timedelta(days=lag)
    return state, lag, ahead, forecast


def _volume(line, share, volumes, money):
    known = line.get("volume")
    if not known or not known.get("quantity") or (money and not volumes):
        return None
    unit = _unit(known["unit"])
    if any(_unit(v["unit"]) != unit for v in volumes):
        return None
    done = sum(v["quantity"] for v in volumes)
    planned = known["quantity"] * share
    return {"unit": known["unit"], "quantity": known["quantity"], "planned": planned, "fact": done,
            "behind": max(planned - done, 0.0), "deviation": done - planned}


def _ratio(part, whole):
    return part / whole if whole else None


def _operation_rows(line, got, day, start, physical_groups):
    """Measure each indexed operation; their areas never become the parent's physical area."""
    operations = line.get('operations')
    if not operations:
        return None
    group = dict(operations['group'])
    group['physical_fact'] = None
    group['physical_fact_reason'] = ('Объём выполненной конструкции не определён: каркас, узлы, '
                                     'остекление и другие операции учитываются отдельно.')
    if group.get('quantity') is None:
        candidates = [item for item in physical_groups
                      if group.get('section') and item.get('number') == group['number']
                      and item.get('section') == group['section']]
        if len(candidates) == 1:
            observed = candidates[0]
            group.update(quantity=observed.get('quantity'), unit=observed.get('unit'),
                         source=observed.get('source') or {}, source_kind='ks6a')
    else:
        group['source_kind'] = 'contract_estimate'
    facts = {part['key']: part for part in got.get('position_facts') or []}
    begin, finish = _span(line, start)
    curve = lambda d: plan.done(line, d, start)
    due = curve(day)
    result = []
    for part in operations['parts']:
        known = part.get('quantity')
        quantity = known * part['share'] if known is not None else None
        observed = facts.get(part['key']) or {}
        actual = observed.get('quantity', 0.0) if ('position_facts' in got or got.get('fact') == 0) else None
        natural = quantity is not None and quantity > 0 and bool(part.get('unit'))
        if natural and actual is not None:
            ready = actual / quantity
            state, lag, ahead, forecast = _measure(curve, ready, due, begin, finish, day, _SHARE)
            finished = observed.get('last') if state == 'done' else None
            if state == 'done' and not finished:
                state, forecast = 'unknown', None
        else:
            ready, state, lag, ahead, forecast, finished = None, 'unknown', 0, 0, None, None
        result.append({'code': line['code'] + '::operation:' + part['key'],
            'display_code': part['number'], 'name': part['name'], 'parent_code': line['code'],
            'position_key': part['key'], 'source': part.get('source') or {},
            'start': line['start'], 'finish': line['finish'], 'due': finish.isoformat(),
            'volume': {'unit': part['unit'], 'quantity': quantity, 'planned': quantity * due,
                       'fact': actual, 'deviation': actual - quantity * due if actual is not None else None} if natural else None,
            'planned': None, 'fact': None, 'deviation': None,
            'readiness': ready, 'plan_done': ready / due if ready is not None and due > _SHARE else None,
            'percent': ready / due - 1 if ready is not None and due > _SHARE else None,
            'state': state, 'lag_days': lag, 'ahead_days': ahead,
            'overdue_days': (day-finish).days if state != 'done' and day > finish else 0,
            'forecast_finish': forecast.isoformat() if forecast else None,
            'finished': finished, 'late_days': (_day(finished)-finish).days if finished else None})
    return {'group': group, 'lines': result}


def build(planned: dict, fact: dict, deadline: str | None, deadline_label: str, cut: str) -> dict:
    """Natural plan and fact, percentages, lag, overdue and forecast of the edition in force on `cut`."""
    result = {"cut": cut, "assumption": ASSUMPTION, "weights": WEIGHTS, "note": "", "total": None, "lines": [],
              "behind": [], "ahead": [], "done": [], "overdue": [], "forecast": None, "left_out": _left_out(fact),
              "source": fact.get("source"), "source_note": fact.get("source_note") or "",
              "preliminary": bool(fact.get("preliminary")), "data_gaps": _data_gaps(fact)}
    current = next((e for e in planned.get("editions") or [] if e.get("in_force")), None)
    if current is None:
        result["note"] = "Отклонение не рассчитано: на дату среза нет действующей редакции плана."
        return result
    if fact.get("note"):
        result["note"] = "Отклонение от плана не рассчитано, потому что нет факта. " + fact["note"]
        return result
    if not current["lines"]:
        result["note"] = "Отклонение не рассчитано: в плане нет ни одной строки, связанной с графиком."
        return result
    day = _day(cut)
    start = _day(current["start"]) if current.get("start") else None
    done_by_code = {x["code"]: x for x in fact.get("lines") or []}
    finishes = []
    work_lines = [line for line in current['lines'] if not line.get('supply_only')]
    if not work_lines:
        result['note'] = 'В сопоставленном плане только поставка материалов: готовность работ не рассчитана.'
        return result
    for line in work_lines:
        got = done_by_code.get(line["code"]) or {"fact": 0.0, "work_fact": 0.0, "material_fact": 0.0,
                                                "volumes": [], "last": None, "complete": False}
        begin, finish = _span(line, start)
        curve = lambda d, line=line: plan.done(line, d, start)
        due = line["planned"] / line["amount"] if line["amount"] else 0.0
        work_amount = line.get('work_amount', line['amount'])
        work_fact = got.get('work_fact', got['fact'] if 'work_amount' not in line else None)
        volume = _volume(line, due, got["volumes"], work_fact)
        unknown = not volume and (work_amount is None or work_fact is None)
        if volume:
            ready, tol = volume["fact"] / volume["quantity"], _SHARE
        elif unknown:
            ready, tol = 0.0, _SHARE
        else:
            ready, tol = _ratio(work_fact, work_amount) or 0.0, _ROUND / work_amount if work_amount else 1.0
        state, lag, ahead, forecast = (('unknown', 0, 0, None) if unknown else
            _measure(curve, ready, due, begin, finish, day, tol, got["complete"]))
        if state == "done" and not got["last"]:
            state, forecast = "behind", finish  # Done by the plan's numbers but no KS period dates its end.
        finished = _day(got["last"]) if state == "done" else None
        row = {"code": line["code"], "name": line["name"], "start": line["start"], "finish": line["finish"],
               "amount": line["amount"], "planned": line["planned"], "fact": got["fact"],
               "work_amount": work_amount, "work_fact": work_fact,
               "material_amount": line.get('material_amount'), "material_fact": got.get('material_fact'),
               "deviation": got["fact"] - line["planned"] if got['fact'] is not None else None,
               "basis": "volume" if volume else "money", "auto": line.get("auto", 0),
               "plan_share": due, "readiness": None if unknown else min(ready, 1.0) if state == "done" else ready,
               "plan_done": _ratio(ready, due) if not unknown and due > tol else None,
               "percent": _ratio(ready, due) - 1 if not unknown and due > tol else None,
               "state": state, "lag_days": lag, "ahead_days": ahead,
               "overdue_days": (day - finish).days if state != "done" and day > finish else 0,
               "behind_amount": (0.0 if finished else max(work_amount * (due-ready), 0.0)
                                 if work_amount is not None and not unknown else None),
               "volume": volume,
               "forecast_finish": forecast.isoformat() if forecast else None,
               "over": ready > 1 + tol,
               "due": finish.isoformat(), "finished": finished.isoformat() if finished else None,
               "late_days": (finished - finish).days if finished else 0,
               "shortfall": (max(line["amount"] - got["fact"], 0.0) if got['fact'] is not None else None)
                             if finished else 0.0}
        operations = _operation_rows(line, got, day, start, fact.get('physical_groups') or [])
        if operations:
            row['operations'] = operations
        result["lines"].append(row)
        if forecast or finished:
            finishes.append((forecast or finished, row))
    rows = result["lines"]
    result["behind"] = [r["code"] for r in sorted((r for r in rows if r["state"] == "behind"),
                                                  key=lambda r: (-r["lag_days"], -(r["behind_amount"] or 0)))]
    result["ahead"] = [r["code"] for r in sorted((r for r in rows if r["ahead_days"] and r["state"] != "done"),
                                                 key=lambda r: -r["ahead_days"])]
    result["done"] = [r["code"] for r in sorted((r for r in rows if r["state"] == "done"),
                                                key=lambda r: -r["late_days"])]
    result["overdue"] = [r["code"] for r in sorted((r for r in rows if r["overdue_days"]),
                                                   key=lambda r: -r["overdue_days"])]
    if any(r['work_amount'] is None or r['readiness'] is None for r in rows):
        result['note'] = 'Готовность сопоставленных работ не рассчитана: стоимость или объём работ не отделены от материалов.'
        result['data_gaps'].append(result['note'])
        return result
    spans = [_span(line, start) for line in work_lines]
    first, last = min(b for b, _ in spans), max(f for _, f in spans)
    whole = sum(r['work_amount'] for r in rows)
    if not whole:
        result['note'] = 'Стоимость работ без материалов не определена: готовность работ не рассчитана.'
        return result
    work_planned = sum(r['work_amount'] * r['plan_share'] for r in rows)
    curve = lambda d: sum(line.get('work_amount', line['amount']) * plan.done(line, d, start)
                          for line in work_lines) / whole
    # Every work weighs its cost; a work counts at most whole, a finished one whole.
    counted = sum(r["work_amount"] * (1.0 if r["state"] == "done" else min(max(r["readiness"], 0.0), 1.0))
                  for r in rows)
    ready = counted / whole if whole else 0.0
    due = work_planned / whole
    tol = _ROUND / whole if whole else 1.0
    all_done = all(r["state"] == "done" for r in rows)
    state, lag, ahead, _ = _measure(curve, ready, due, first, last, day, tol, all_done)
    amounts = [r['fact'] for r in fact.get('lines') or []
               if r['code'] in {line['code'] for line in current['lines']}]
    total_fact = None if any(v is None for v in amounts) else sum(amounts)
    result["total"] = {"amount": current['total'], "planned": current["planned"], "fact": total_fact,
                       "work_amount": whole, "work_planned": work_planned,
                       "deviation": total_fact - current["planned"] if total_fact is not None else None,
                       "readiness": ready, "plan_share": due,
                       "plan_done": ready / due if due > tol else None,
                       "percent": ready / due - 1 if due > tol else None,
                       "state": state, "lag_days": lag, "ahead_days": ahead,
                       "behind_amount": max(work_planned - counted, 0.0),
                       "shortfall": None if any(r['shortfall'] is None for r in rows) else sum(r["shortfall"] for r in rows),
                       "by_volume": sum(1 for r in rows if r["basis"] == "volume"),
                       "by_money": sum(1 for r in rows if r["basis"] == "money"),
                       "auto": current.get("auto", 0),
                       "overdue_works": len(result["overdue"]),
                       "preliminary": result["preliminary"],
                       # KS periods left out of the fact: the lag and the deviation are counted without them.
                       "incomplete": bool(result["left_out"]["count"] or result['data_gaps'])}
    result["forecast"] = _forecast(finishes, deadline, deadline_label, last, current, day)
    forecast = result["forecast"]
    result["total"]["overdue_days"] = (day - _day(forecast["deadline"])).days \
        if forecast["passed"] and not all_done else 0
    return result


def _left_out(fact):
    """KS periods the fact could not take (`review`): their count and every reason once, in order."""
    review = fact.get("review") or []
    return {"count": len(review), "reasons": list(dict.fromkeys(r["reason"] for r in review))}


def _data_gaps(fact):
    gaps = ([f'Позиций КС с неподтверждённым разделением работ и материалов: {len(fact["component_gaps"])}.']
            if fact.get('component_gaps') else [])
    if fact.get('missing_acts'):
        gaps.append('В карточке нет актов КС-2 № ' + ', '.join(fact['missing_acts']) +
                    ', которые указаны в сводной. Их выполнение в расчёт не вошло.')
    if fact.get('unread'):
        gaps.append(f'Работ КС-6а без подтверждённой истории выполнения: {len(fact["unread"])}.')
    outside = sum(v.get('count', 0) for v in (fact.get('outside') or {}).values())
    if outside:
        gaps.append(f'Выполнение по {outside} позициям не сопоставлено с действующим планом.')
    return gaps


def _forecast(finishes, deadline, deadline_label, last, current, day):
    if deadline:
        limit, label = _day(deadline), deadline_label or "срок договора"
    else:
        limit, label = last, "окончание графика действующей редакции"
    outside = sum(item["count"] for item in (current.get("outside") or {}).values())
    forecast = {"deadline": limit.isoformat(), "deadline_label": label, "from_register": bool(deadline),
                "finish": None, "done": bool(finishes) and all(row["state"] == "done" for _, row in finishes),
                "days_over": 0, "days_early": 0, "threat": False, "drivers": [], "outside": outside,
                "passed": limit < day}
    if not finishes:
        return forecast
    finish = max(f for f, _ in finishes)
    forecast["finish"] = finish.isoformat()
    forecast["days_over"] = max((finish - limit).days, 0)
    forecast["days_early"] = max((limit - finish).days, 0)
    forecast["threat"] = finish > limit
    forecast["drivers"] = [row["code"] for f, row in sorted(finishes, key=lambda x: x[0], reverse=True)
                           if f > limit]
    return forecast
