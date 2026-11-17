"""Accumulated fact of a contract: KS quantities priced by the Расчёт and laid on the ГПР lines.

The fact is read from the positions of the acts КС-2 of the card, accumulated
from the start of the construction (`developaid_contract_acts.accumulated`);
the cumulative KS-6a is then a control reconciliation beside it. A card without
acts КС-2 takes the fact from the KS-6a, and says so (owner's decision 1А of
12.11.2026).

A fact row is one act КС-2 position or one dated period of one work of the
cumulative KS-6a. It belongs
to the edition of the plan in force on the last day of its period, and its money
is the quantity × the unit price of that edition's «Расчёт» (owner's decision
4А), not the sum written in the KS. The row finds its position by number, or by
name and unit; a finer row numbered under a position (4.1.1 under 4.1) with the
same unit is summed into it. A number and a name that point to different
positions, another unit or no position at all go to review with the reason,
never a guess.

The money of a position reaches the ГПР lines through the confirmed or the
unambiguous proposed link of the same position (number, name and unit) in the
edition in force on the cut (rule 3 of 12.11.2026). Work
of an estimate «на завершение работ» counts from its agreement date: earlier
work was accepted before the agreement and is shown beside the plan, not in it.

With the KS-6a as the fact, a line is complete by volume (owner's decision А)
when every position linked to it has KS-6a works and each of them reached its
full volume of the statement by the cut; the money of a complete line may stay
below its cost in the estimate. With the acts КС-2 the line is complete when its
natural fact reaches its volume in the estimate (`developaid_contract_control`).
The last day of the line is the end of its last KS period up to the cut.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

import developaid_contract_schedule_links as links
import developaid_contract_acts as contract_acts
from developaid_monitor_contracts import _norm
from developaid_monitor_statement_union import _unit

_QUANTITY = 1e-6  # Quantities of the KS and the statement are the same printed numbers: only float noise differs.
ASSUMPTION = ("Работы периода КС относятся к редакции расчёта, которая действовала в последний день периода. "
              "Деньги факта — объём КС × цена за единицу этой редакции, а не сумма, записанная в КС.")
_STATUSES = ("review", "extra", "missing")
_LINKED = ("confirmed", "proposed")
FROM_KS6A = "Актов КС-2 в карточке нет: факт взят из накопительной КС-6а."


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
        item_basis = item.get('quantity_basis') if item.get('quantity_basis') in ('work', 'material') else 'work'
        for period in periods:
            if period.get("amount") is not None:
                sums[period.get("label") or ""] = sums.get(period.get("label") or "", 0.0) + period["amount"]
        if item.get("completed_quantity") is None and item_basis != 'material':
            # Periods named by an act only may still be dated by the act (developaid_contract_act_dates).
            unread.append({"number": item.get("position") or "", "name": item.get("name") or "",
                           "unit": item.get("unit") or "", "reason": item.get("quantity_basis") or "",
                           "source": item.get("source") or {}, "item": index,
                           "plan_quantity": item.get("plan_quantity"),
                           "reported_quantity": item.get("reported_completed_quantity"),
                           "periods": [{"label": p.get("label") or "", "quantity": p.get("quantity"),
                                        "material_quantity": p.get('material_quantity'),
                                        "work_amount": p.get('work_amount'), "material_amount": p.get('material_amount'),
                                        "amount": p.get("amount"), "start": p.get("date_start"),
                                        "end": p.get("date_end"), "source": p.get("source") or {}}
                                       for p in periods]})
            continue
        works.append({"item": index, "number": item.get("position") or "", "name": item.get("name") or "",
                      "unit": item.get("unit") or "", "plan_quantity": item.get("plan_quantity"),
                      "basis": item_basis})
        for period in item.get("periods") or []:
            if not period.get("quantity") and not period.get("material_quantity") and not period.get("amount"):
                continue  # Nothing done in this period; a sum without a volume goes to review in `build`.
            period_basis = period.get('quantity_basis') if period.get('quantity_basis') in ('work', 'material') else item_basis
            quantity = period.get('quantity')
            if period_basis == 'material' and quantity is None:
                quantity = period.get('material_quantity')
            found.append({"number": item.get("position") or "", "name": item.get("name") or "",
                          "unit": item.get("unit") or "", "quantity": quantity,
                          "basis": period_basis,
                          "quantity_material": period.get('material_quantity'),
                          "amount_components": {'work': period.get('work_amount'),
                                                'material': period.get('material_amount'), 'total': period.get('amount')},
                          "act_amount": period.get("amount"), "start": period.get("date_start"),
                          "end": period["date_end"], "label": period.get("label") or "",
                          "item": index,
                          "source": period.get("source") or item.get("source") or {}})
    summary = [act for source in row.get("financial_sources") or [] for act in source.get("acts") or []]
    return {"acts": found, "unread": unread, "works": len(works), "items": works, "period_amounts": sums,
            "summary_acts": summary,
            "deadline": row.get("deadline"), "deadline_label": (row.get("deadline_source") or {}).get("label") or "",
            "deadline_manual": (row.get("deadline_source") or {}).get("label") == "Указан вручную"}


def unavailable(reason: str) -> dict:
    """No fact, because the register of the cut could not be built: `reason` says why."""
    return {"acts": [], "unread": [], "works": 0, "items": [], "problem": reason}


def statement_materials(found: dict | None, cut: str) -> dict:
    """A separate observation from the statement's labelled material columns.

    This projection is never added to the work fact or the uploaded acts.
    The closing summary supplies no quantity, price, or material amount.
    """
    result = {'source': 'ks6a', 'rows': [], 'unknown_count': len((found or {}).get('unread') or [])}
    if found is None or found.get('problem'):
        result['note'] = (found or {}).get('problem') or 'КС-6а к договору не привязана.'
        return result
    for period in found.get('acts') or []:
        if not period.get('end') or period['end'] > cut:
            continue
        quantity = period.get('quantity_material')
        amount = (period.get('amount_components') or {}).get('material')
        if not quantity and not amount:
            continue
        result['rows'].append({'number': period['number'], 'name': period['name'], 'unit': period['unit'],
            'quantity': quantity, 'amount': amount, 'label': period.get('label') or '',
            'basis': 'Отдельные графы материалов КС-6а.', 'source': period.get('source') or {}})
    return result


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


def _price(position, component="total"):
    price = (position.get("unit_price") or {}).get(component)
    if price is None and position.get("quantity") and (position.get("amount") or {}).get(component) is not None:
        price = position["amount"][component] / position["quantity"]
    return price


def _components(act, position):
    """Price work and supplied material by their own quantities, without inventing a missing quantity.

    Older saved reads do not identify whether the act had one or two quantity
    columns. A shared quantity is therefore accepted only when the act's own
    printed component prices and total prove it within a ruble of rounding.
    """
    basis = act.get('basis') or 'work'
    work_quantity = act['quantity'] if basis != 'material' else 0.0
    material_quantity = act['quantity'] if basis == 'material' else act.get('quantity_material')
    material_basis = 'Количество материала из акта.' if material_quantity is not None else ''
    printed = act.get('unit_price') or {}
    amounts = act.get('amount_components') or {}
    mp, wp, total = printed.get('material'), printed.get('work'), act.get('act_amount')
    if basis != 'material' and material_quantity is None:
        if amounts.get('material') is not None and mp:
            material_quantity = amounts['material'] / mp
            material_basis = 'Количество материала из его напечатанной суммы и цены акта.'
        elif mp is not None and wp is not None and total is not None:
            if abs(work_quantity * (mp + wp) - total) <= 1.0 and mp:
                material_quantity = work_quantity
                material_basis = 'Общий объём подтверждён напечатанными ценами и итогом акта.'
            elif abs(work_quantity * wp - total) <= 1.0:
                material_quantity = 0.0
                material_basis = 'Итог акта подтверждает только выполненную работу.'
        elif printed.get('material') is None and wp is not None and total is not None \
                and abs(work_quantity * wp - total) <= 1.0:
            material_quantity = 0.0
            material_basis = 'Итог акта подтверждает только выполненную работу.'
    work_price, material_price = _price(position, 'work'), _price(position, 'material')
    printed_total = printed.get('total')
    if basis != 'material' and material_quantity is None and mp is None and wp is None \
            and work_price is not None and material_price not in (None, 0) and printed_total is not None \
            and total is not None and abs(printed_total-work_price-material_price) <= 1e-6 \
            and abs(work_quantity*printed_total-total) <= 1.0:
        material_quantity = work_quantity
        material_basis = 'Общий объём подтверждён полной ценой акта и разбивкой цены РДС.'
    work_money = 0.0 if basis == 'material' or work_quantity == 0 else (
        work_quantity * work_price if work_price is not None else None)
    material_money = (0.0 if material_quantity == 0 else
                      material_quantity * material_price if material_quantity is not None and material_price is not None
                      else 0.0 if material_price == 0 else None)
    known = work_money is not None and material_money is not None
    fallback = _price(position)
    split_evidence = any(v is not None for v in (
        work_price, material_price, mp, wp, amounts.get('work'), amounts.get('material'),
        act.get('quantity_material'))) or basis == 'material'
    combined_only = not known and not split_evidence and fallback is not None
    money = work_money + material_money if known else act['quantity'] * fallback if combined_only else None
    reason = '' if known else 'Работы и материалы не разделены полностью: неизвестны количество или цена компонента.'
    return {'work_quantity': work_quantity, 'material_quantity': material_quantity,
            'work_amount': work_money, 'material_amount': material_money, 'total': money,
            'known_total': money if money is not None else sum(v for v in (work_money, material_money) if v is not None),
            'material_basis': material_basis, 'reason': reason, 'combined_only': combined_only,
            'act_amount': act.get('act_amount')}


def _add_money(one, other):
    return None if one is None or other is None else one + other


def _accumulate_money(record, value, key='amount', known_key='known_amount', known_value=None):
    """An unknown component makes the full amount unknown; a known subtotal stays explicit."""
    previous = record[key]
    if previous is None or value is None:
        if known_key not in record:
            record[known_key] = previous if previous is not None else 0.0
        if value is not None:
            record[known_key] += value
        elif known_value is not None:
            record[known_key] += known_value
        record[key] = None
    else:
        record[key] += value


def _sum_money(values):
    result = 0.0
    for value in values:
        result = _add_money(result, value)
    return result


def _money(value):
    if value is None:
        return 'сумма не определена'
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _month_ends(first: dt.date, last: dt.date):
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield min(dt.date(year, month, calendar.monthrange(year, month)[1]), last)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def from_acts(performed: dict | None) -> list[dict]:
    """Fact rows of the acts КС-2 in force up to the cut: one row per act and position of the estimate."""
    rows = []
    for position in (performed or {}).get("positions") or []:
        for part in position["parts"]:
            if not part["quantity"] and not part.get('quantity_material'):
                continue
            rows.append({"number": position["number"], "name": part["name"] or position["name"],
                         "unit": position["unit"], "quantity": part["quantity"], "act_amount": part["amount"],
                         "basis": part.get('basis') or position.get('basis') or 'work',
                         "quantity_material": part.get('quantity_material'),
                         "unit_price": part.get('unit_price') or {},
                         "amount_components": part.get('amount_components') or {},
                         "start": None, "end": part["day"], "label": f"акт КС-2 № {part['act'] or 'без номера'}",
                         "item": None, "preliminary": part["preliminary"], "source": part.get('source') or {}})
    return rows


def _missing_acts(performed: dict | None, found: dict | None, cut: str) -> list[str]:
    """Only acts explicitly observed by this contract's dated summary can be missing.

    Do not infer gaps from consecutive numbering or combine their volumes with
    uploaded acts. Full normalized numbers keep different years distinct.
    """
    present = {contract_acts.edition(a) for a in (performed or {}).get('acts') or []}
    expected = {contract_acts.edition(a) for a in (found or {}).get('summary_acts') or []
                if a.get('date') and a['date'] <= cut}
    return sorted((n for n in expected-present if n is not None),
                  key=lambda n: (tuple(map(int, re.findall(r'\d+', n))), n))


def reconcile(performed: dict | None, found: dict | None, cut: str) -> dict | None:
    """The accumulated volumes of the acts КС-2 against the KS-6a periods up to `cut`, by number and unit.

    None when one of them is missing: there is nothing to reconcile.
    """
    ks6a = [a for a in (found or {}).get("acts") or [] if a.get("quantity") and a["end"] <= cut]
    if not (performed or {}).get("positions") or not ks6a:
        return None
    sums = {}
    for side, rows in (("ks2", from_acts(performed)), ("ks6a", ks6a)):
        for row in rows:
            if row.get('basis') == 'material':
                continue
            key = (_code(row["number"]), _unit(row["unit"]))
            if not key[0]:
                continue  # A work without its number in the estimate is not the same work by its name alone.
            item = sums.setdefault(key, {"number": row["number"], "name": row["name"], "unit": row["unit"],
                                         "ks2": None, "ks6a": None})
            item[side] = (item[side] or 0.0) + row["quantity"]
    rows = []
    for item in sums.values():
        both = item["ks2"] is not None and item["ks6a"] is not None
        item["same"] = both and abs(item["ks2"] - item["ks6a"]) <= max(_QUANTITY, abs(item["ks6a"]) * 1e-6)
        rows.append(item)
    return {"rows": rows, "same": sum(1 for r in rows if r["same"]),
            "differs": sum(1 for r in rows if r["ks2"] is not None and r["ks6a"] is not None and not r["same"]),
            "only_ks2": sum(1 for r in rows if r["ks6a"] is None),
            "only_ks6a": sum(1 for r in rows if r["ks2"] is None)}


def build(editions: list[dict], in_force: str | None, found: dict | None, cut: str,
          performed: dict | None = None) -> dict:
    """The fact on `cut` by the lines of the edition `in_force` (sha256) of the plan.

    `performed` are the acts КС-2 of the card accumulated on `cut`; when they bring positions the fact is
    theirs, otherwise the KS-6a works of `found` (`acts`).
    """
    result = {"cut": cut, "assumption": ASSUMPTION, "total": 0.0, "lines": [], "months": [], "positions": [],
              "outside": {status: {"count": 0, "amount": 0.0} for status in _STATUSES},
              "before": None, "review": [], "unread": [], "price_differs": 0, "after_cut": 0, "note": "",
              "source": None, "source_note": "", "preliminary": False, "reconciliation": None,
              "materials": [], "component_gaps": [], 'material_statement': statement_materials(found, cut)}
    rows = from_acts(performed)
    if rows:
        result["source"] = "ks2"
        result["preliminary"] = any(a["preliminary"] for a in rows)
        result["after_cut"] = (performed or {}).get("later") or 0
        result["reconciliation"] = reconcile(performed, None if (found or {}).get("problem") else found, cut)
        # The KS-6a works without a dated period are not reconciled: they are named, not dropped.
        result["unread"] = [] if (found or {}).get("problem") else (found or {}).get("unread") or []
        result['missing_acts'] = _missing_acts(performed, found, cut)
    elif found is None:
        result["note"] = ("Актов КС-2 в карточке нет, а накопительная КС-6а этого договора на дату среза "
                          "не найдена: факт не рассчитан.")
        return result
    elif found.get("problem"):
        result["note"] = f"Актов КС-2 в карточке нет, а факт по КС-6а не рассчитан. {found['problem']}"
        return result
    else:
        result["source"], result["source_note"] = "ks6a", FROM_KS6A
        result["unread"] = found["unread"]
        rows = found["acts"]
    current = next((e for e in editions if e["sha256"] == in_force), None)
    if current is None:
        result["note"] = "Нет редакции плана, действующей на дату среза: факт не с чем сопоставить."
        return result
    if result["source"] == "ks6a" and not found.get("works"):
        # No work with a known quantity: a zero here would be a missing KS-6a, not an answer.
        result["note"] = ("Актов КС-2 в карточке нет, а в накопительной КС-6а этого договора нет выполнения "
                          "с датированными периодами до даты среза.")
        return result
    dated = sorted((e for e in editions if e.get("date")), key=lambda e: e["date"])
    start = _day(current["start"]) if current.get("start") else None
    if start:
        result["before"] = {"start": current["start"], "count": 0, "amount": 0.0, "unpriced": 0}
    links_now = {p["key"]: p for e in current["estimates"] if e.get("scope") != "accepted"
                 for p in (e.get("links") or {}).get("positions") or []}
    lines, volumes, positions, dated_money = {}, {}, {}, []
    dated_known_money = []
    known_lines = {}
    work_money, material_money, material_volumes = {}, {}, {}
    unknown_work, unknown_material = set(), set()
    last, done_quantity = {}, {}
    for act in rows:
        end = _day(act["end"])
        if end > _day(cut):
            result["after_cut"] += 1
            continue
        zero_without_material = (act['quantity'] == 0 and not act.get('quantity_material')
                                 and act.get('act_amount') not in (None, 0))
        if act["quantity"] is None or zero_without_material:
            absent = ('объём работ равен нулю и количество материала не записано' if zero_without_material
                      else 'объём не записан (например, оплачена только поставка материалов)')
            result["review"].append({**act, "reason": f"В периоде КС записана сумма {_money(act['act_amount'])}, "
                                                      f"а {absent}: без объёма выполнение не пересчитать по цене "
                                                      "расчёта."})
            continue
        edition = next((e for e in reversed(dated) if _day(e["date"]) <= end), None)
        if start and end < start and edition is None:
            # Accepted before the agreement, in a period whose Расчёт is not in the card.
            if act.get('basis') != 'material':
                done_quantity[act["item"]] = done_quantity.get(act["item"], 0.0) + act["quantity"]
            result["before"]["count"] += 1
            result["before"]["unpriced"] += 1
            _accumulate_money(result['before'], None)
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
        components = _components(act, position)
        money = components['total']
        if price is None and all(_price(position, part) is None for part in ('work', 'material')):
            result['review'].append({**act, 'edition': edition['title'],
                'reason': f"У позиции № {position['number']} в расчёте не прочитана цена за единицу."})
        # Only the volume that entered the fact counts toward a complete line: review volume is not known done.
        if act.get('basis') != 'material':
            done_quantity[act["item"]] = done_quantity.get(act["item"], 0.0) + components['work_quantity']
        if components['reason']:
            result['component_gaps'].append(f"Позиция № {position['number']}, {act.get('label') or 'период КС'}: " + components['reason'])
        if money is not None and act["act_amount"] is not None and abs(act["act_amount"] - money) > max(1.0, abs(money) * 0.005):
            result["price_differs"] += 1
        if start and end < start:
            place = "before"
            result["before"]["count"] += 1
            _accumulate_money(result['before'], money, known_value=components['known_total'])
        else:
            link = links_now.get(links.position_key(position))
            place = link["status"] if link else "missing"
            if place in _LINKED:
                for line in link["lines"]:
                    code, share = line['code'], line['share']
                    part_money = money * share if money is not None else None
                    lines[code] = _add_money(lines.get(code, 0.0), part_money)
                    known_lines[code] = known_lines.get(code, 0.0) + components['known_total'] * share
                    for key, target, unknown in [('work_amount', work_money, unknown_work),
                                                 ('material_amount', material_money, unknown_material)]:
                        value = components[key]
                        if value is None:
                            unknown.add(code)
                        else:
                            target[code] = target.get(code, 0.0) + value * share
                    if components['work_quantity']:
                        unit = volumes.setdefault(code, {}).setdefault(
                            _unit(position["unit"]), {"unit": position["unit"], "quantity": 0.0})
                        unit["quantity"] += components['work_quantity'] * share
                        last[code] = max(last.get(code, act["end"]), act["end"])
                    if components['material_quantity'] is not None:
                        unit = material_volumes.setdefault(code, {}).setdefault(
                            _unit(position["unit"]), {"unit": position["unit"], "quantity": 0.0})
                        unit['quantity'] += components['material_quantity'] * share
                dated_money.append((end, money))
                dated_known_money.append((end, components['known_total']))
                _accumulate_money(result, money, 'total', 'known_total', components['known_total'])
            else:
                result["outside"][place]["count"] += 1
                _accumulate_money(result['outside'][place], money, known_value=components['known_total'])
        if components['material_quantity'] or components['material_amount'] or (
                components['reason'] and (_price(position, 'material') or act.get('basis') == 'material')):
            result['materials'].append({'number': position['number'], 'name': position['name'],
                'unit': position['unit'], 'quantity': components['material_quantity'],
                'amount': components['material_amount'], 'basis': components['material_basis'],
                'reason': components['reason'], 'place': place, 'label': act.get('label') or '', 'end': act['end'],
                'source': act.get('source') or {}, 'edition': edition['title']})
        key = (edition["sha256"], e, i, place, act.get('basis') or 'work')
        row = positions.setdefault(key, {
            "number": position["number"], "name": position["name"], "unit": position["unit"], "price": price,
            "edition": edition["title"], "how": how, "place": place, "quantity": 0.0, "amount": 0.0,
            "act_amount": 0.0, "periods": 0, "last": act["end"]})
        row['basis'] = act.get('basis') or 'work'
        row["quantity"] += act["quantity"]
        _accumulate_money(row, money, known_value=components['known_total'])
        row["act_amount"] = None if act["act_amount"] is None or row["act_amount"] is None \
            else row["act_amount"] + act["act_amount"]
        row["periods"] += 1
        row["last"] = max(row["last"], act["end"])
    order = [line["code"] for line in links.leaves(current.get("schedule"))]
    # Every work of the statement, done or not yet, belongs to its position of the edition in force.
    items_of = {}
    for work in (found or {}).get("items") or [] if result["source"] == "ks6a" else []:
        if work.get('basis') == 'material':
            continue
        found_at = match(work, current["estimates"])
        if not isinstance(found_at, str):
            e, i, _ = found_at
            items_of.setdefault(links.position_key(current["estimates"][e]["positions"][i]), []).append(work)
    full = lambda work: bool(work["plan_quantity"]) and (
        done_quantity.get(work["item"], 0.0) >= work["plan_quantity"] - _QUANTITY)
    keys_of = {}
    for key, link in links_now.items():
        if link["status"] in _LINKED:
            for line in link["lines"]:
                keys_of.setdefault(line["code"], []).append(key)

    def complete(code):
        keys = keys_of.get(code) or []
        return bool(keys) and all(items_of.get(key) and all(full(work) for work in items_of[key]) for key in keys)

    result["lines"] = [{"code": code, "fact": lines[code], "volumes": list(volumes.get(code, {}).values()),
                        **({'known_fact': known_lines.get(code, 0.0)} if lines[code] is None else {}),
                        'work_fact': None if code in unknown_work else work_money.get(code, 0.0),
                        'material_fact': None if code in unknown_material else material_money.get(code, 0.0),
                        'material_volumes': list(material_volumes.get(code, {}).values()),
                        "last": last.get(code), "complete": complete(code)}
                       for code in order if code in lines]
    result['component_gaps'] = list(dict.fromkeys(result['component_gaps']))
    result["positions"] = list(positions.values())
    if result['total'] is None or any(p['amount'] is None for p in result['positions']) or \
            any(v['amount'] is None for v in result['outside'].values()) or \
            (result.get('before') and result['before']['amount'] is None):
        result['money_incomplete'] = True
    if dated_money:
        day = _day(cut)
        first = min(end for end, _ in dated_money)
        result["months"] = []
        for end in _month_ends(first, day):
            relevant = [m for d, m in dated_money if d <= end]
            total = _sum_money(relevant)
            result['months'].append({'month': end.isoformat()[:7], 'fact': total,
                **({'known_fact': sum(m for d, m in dated_known_money if d <= end)} if total is None else {})})
    return result
