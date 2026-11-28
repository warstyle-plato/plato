"""Accumulated fact of a contract: KS quantities priced by the Расчёт and laid on the ГПР lines.

The cumulative KS-6a has priority. If it is absent or wholly unreadable,
uploaded acts КС-2 supply the quantities, with their scope explicitly labelled.
The two sources are never added together. A partly readable KS-6a retains its
unknown works instead of filling them with acts (owner's clarification of 24.11.2026).

A fact row is one dated period of one work of the cumulative KS-6a. It belongs
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
below its cost in the estimate. КС-2 never replaces that source volume.
The last day of the line is the end of its last KS period up to the cut.
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import re

import developaid_contract_schedule_links as links
import developaid_contract_acts as contract_acts
import developaid_contract_statement_components as statement_components
from developaid_contract_act_dates import compact_number
from developaid_monitor_contracts import _norm
from developaid_monitor_statement_union import _unit

_QUANTITY = 1e-6  # Quantities of the KS and the statement are the same printed numbers: only float noise differs.
ASSUMPTION = ("Работы периода КС относятся к редакции расчёта, которая действовала в последний день периода. "
              "Деньги факта — объём КС × цена за единицу этой редакции, а не сумма, записанная в КС.")
_STATUSES = ("review", "extra", "missing")
_LINKED = ("confirmed", "proposed")
FROM_KS6A = "Выполнение рассчитано по накопительной КС-6а. Акты КС-2 используются для сверки и подтверждения."
FROM_KS2 = ("Выполнение рассчитано по позициям загруженных актов КС-2: пригодная для расчёта КС-6а отсутствует. "
            "Полнота комплекта актов не подтверждена. Итоги актов показаны отдельно от факта по графику.")


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
    if row.get('source_kind') == 'contract_document':
        return {**unavailable(row.get('performance_basis') or 'КС этого договора не предоставлены.'),
                'document_source_ids': row.get('document_source_ids') or []}
    found, unread, works, sums, groups, zero_acts = [], [], [], {}, [], []
    source_positions = {}
    for index, item in enumerate(row.get("physical_items") or []):
        if item.get('is_group') and not item.get('is_duplicate'):
            groups.append({'number': item.get('position') or '', 'name': item.get('name') or '',
                           'section': item.get('scope') or '', 'unit': item.get('unit') or '',
                           'quantity': item.get('plan_quantity'), 'source': item.get('source') or {},
                           'source_kind': 'ks6a'})
        if item.get("is_group") or item.get("is_duplicate"):
            continue  # A group sums its works; a verified duplicate repeats one.
        source_positions[index] = statement_components.position_source(item)
        dated_periods = [{**p,'source':statement_components.period_source(item,p)} for p in item.get('periods') or []]
        periods = dated_periods + [{**p,'source':statement_components.period_source(item,p)} for p in item.get('undated_periods') or []]
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
                                        "physical_quantity_basis":p.get("quantity_basis") or "explicit_quantity",
                                        "material_quantity": p.get('material_quantity'),
                                        "amount_split": p.get('amount_split') is True,
                                        "work_amount": p.get('work_amount'), "material_amount": p.get('material_amount'),
                                        "amount": p.get("amount"), "start": p.get("date_start"),
                                        "end": p.get("date_end"), "source": p.get("source") or {}}
                                       for p in periods]})
            continue
        works.append({"item": index, "number": item.get("position") or "", "name": item.get("name") or "",
                      "unit": item.get("unit") or "", "plan_quantity": item.get("plan_quantity"),
                      "basis": item_basis})
        for period in dated_periods:
            period_basis = period.get('quantity_basis') if period.get('quantity_basis') in ('work', 'material') else item_basis
            quantity = period.get('quantity')
            if period_basis == 'material' and quantity is None:
                quantity = period.get('material_quantity')
            observation = {"number": item.get("position") or "", "name": item.get("name") or "",
                          "unit": item.get("unit") or "", "quantity": quantity,
                          "basis": period_basis,
                          'physical_quantity_basis':period.get('quantity_basis') or 'explicit_quantity',
                          "quantity_material": period.get('material_quantity'),
                          "amount_components": {'work': period.get('work_amount'),
                                                'material': period.get('material_amount'), 'total': period.get('amount')},
                          "act_amount": period.get("amount"), "start": period.get("date_start"),
                          "end": period.get("date_end"), "label": period.get("label") or "",
                          "item": index,
                          "source": period.get("source") or item.get("source") or {}}
            if not period.get("quantity") and not period.get("material_quantity") and not period.get("amount"):
                reported = item.get('reported_completed_quantity')
                cumulative = reported if reported is not None else item.get('completed_quantity')
                if type(cumulative) in (int, float) and cumulative == 0 and \
                        type(period.get('quantity')) in (int, float) and period['quantity'] == 0:
                    zero_acts.append(observation)
                continue  # Explicit zeros remain evidence, without changing the financial-period stream.
            found.append(observation)
    summary = [act for source in row.get("financial_sources") or [] for act in source.get("acts") or []]
    return {"acts": found, "unread": unread, "works": len(works), "items": works, "period_amounts": sums,
            'document_source_ids': row.get('document_source_ids') or [],
            'physical_groups': groups, 'source_positions':source_positions,
            'physical_source_rows': [{key:item[key] for key in (
                'position','name','unit','plan_quantity','source','snapshot_date',
                'reported_completed_quantity','completed_quantity','reported_material_quantity','material_quantity',
                'periods','undated_periods') if key in item} for item in row.get('physical_items') or []
                if not item.get('is_group') and not item.get('is_duplicate')],
            'statement_sources':[{k:x[k] for k in ('source','source_date','period_year','completed',
                'completed_materials','completed_works','financial_complete','period_dates_known',
                'planned','planned_materials','planned_works','monetary_comparable','parts_monetary_comparable',
                'completed_amount_basis','planned_amount_basis') if k in x}
                for x in row.get('reported_performance_sources') or []],
            "summary_acts": summary,
            "deadline": row.get("deadline"), "deadline_label": (row.get("deadline_source") or {}).get("label") or "",
            "deadline_manual": (row.get("deadline_source") or {}).get("label") == "Указан вручную",
            **({'zero_acts': zero_acts} if zero_acts else {})}


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
    periods=found.get('acts') or []
    if any(statement_components._source_valid(p.get('source') or {})
            for p in (found.get('source_positions') or {}).values()):
        events,conflicts,unbound=statement_components.observations(found)
        periods=[period for _,period in events]
        result['unknown_count']+=len(conflicts)+len(unbound)
        if conflicts or unbound:
            result['note']='Происхождение или повтор исходного периода требует проверки; неподтверждённые строки не суммируются.'
    for period in periods:
        if not period.get('end') or period['end'] > cut:
            continue
        quantity = statement_components.material_quantity(period)
        amount = (period.get('amount_components') or {}).get('material')
        evidence=statement_components.position_evidence(found,period.get('item'))
        planned=evidence.get('material_amount')
        unknown=(statement_components._source_valid(evidence.get('source') or {}) and
            not statement_components.numeric(quantity) and not (statement_components.numeric(planned) and planned==0))
        if not quantity and not amount and not unknown:
            continue
        if unknown:result['unknown_count']+=1
        result['rows'].append({'number': period['number'], 'name': period['name'], 'unit': period['unit'],
            'quantity': quantity, 'amount': amount, 'label': period.get('label') or '',
            **({'reason':'Объём материала не подтверждён; ноль работ не доказывает отсутствие поставки.'} if unknown else {}),
            'basis': 'Отдельные графы материалов КС-6а.',
            'source': statement_components.component_source(period.get('source') or {},'material')})
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


def _rds_observation(records, current, act, components, edition):
    """Retain the existing typed match and component calculation before GPR allocation.

    This is source evidence for active RDS rows, including rows with no GPR link.
    It changes neither period pricing nor any existing financial accumulator.
    """
    matched = match(act, current['estimates'])
    if isinstance(matched, str):
        return
    estimate, index, how = matched
    record = records.setdefault((estimate, index), {
        'estimate': estimate, 'index': index, 'how': how,
        'estimate_sha256': current.get('estimate_sha256'),
        'work_quantity': 0.0, 'material_quantity': 0.0,
        'work_observed': False, 'material_observed': False,
        'work_amount': 0.0, 'material_amount': 0.0, 'amount': 0.0,
        'periods': 0, 'sources': [], 'priced_editions': [], 'reasons': []})
    if act.get('basis') != 'material':
        record['work_observed'] = True
        record['work_quantity'] = _add_money(record['work_quantity'], components['work_quantity'])
    record['material_observed'] |= components['material_quantity'] is not None
    record['material_quantity'] = _add_money(record['material_quantity'], components['material_quantity'])
    for component in ('work_amount', 'material_amount'):
        record[component] = _add_money(record[component], components[component])
    _accumulate_money(record, components['total'], known_value=components['known_total'])
    record['periods'] += 1
    # Retain typed physical increments before aggregation. Source selections,
    # duplicate removal and component attribution above remain authoritative;
    # an accumulated total must never be reused as each period's increment.
    if act.get('basis') != 'material':
        witness = {'source': act.get('source') or {}, 'label': act.get('label') or '',
                   'start': act.get('start'), 'end': act.get('end')}
        event_id = hashlib.sha256(json.dumps(witness, sort_keys=True,
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        event = {**witness, 'id': event_id, 'quantity_kind': 'increment',
                 'work_quantity': components['work_quantity'],
                 'physical_quantity_basis':act.get('physical_quantity_basis') or 'explicit_quantity',
                 'date_basis': 'document_observation' if act.get('preliminary') or not act.get('start')
                               else 'reported_period',
                 'preliminary': bool(act.get('preliminary'))}
        record.setdefault('reporting_events', []).append(event)
    evidence = {'source': act.get('source') or {}, 'label': act.get('label') or '',
                'start': act.get('start'), 'end': act.get('end'),
                'material_basis': components['material_basis']}
    if evidence not in record['sources']:
        record['sources'].append(evidence)
    if edition['title'] not in record['priced_editions']:
        record['priced_editions'].append(edition['title'])
    if components['reason'] and components['reason'] not in record['reasons']:
        record['reasons'].append(components['reason'])


def _money(value):
    if value is None:
        return 'сумма не определена'
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _month_ends(first: dt.date, last: dt.date):
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        yield min(dt.date(year, month, calendar.monthrange(year, month)[1]), last)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _ks2_reporting_context(performed):
    """Scope attestation for a reporting zero, separate from accepted physical evidence."""
    import math
    performed = performed or {}
    evidence = performed.get('evidence') or {}
    unread_rows = [{**row, 'source_sha256': item.get('sha256')}
                  for item in evidence.get('acts') or [] for row in item.get('unread_positions') or []]
    typed_warnings = {row.get('warning') for row in unread_rows if row.get('warning')}
    unclassified_warnings = [warning for item in evidence.get('acts') or []
                             for warning in item.get('warnings') or [] if warning not in typed_warnings]
    parts = [part for position in performed.get('positions') or [] for part in position.get('parts') or []]
    def quantity(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    readable = (type(evidence.get('count')) is int and evidence['count'] > 0
        and evidence.get('unread_count') == 0 and not performed.get('excluded') and bool(parts)
        and not unclassified_warnings
        and all(quantity(part.get('quantity')) or quantity(part.get('quantity_material')) for part in parts))
    return {'schema': 'loaded-ks2-reporting-scope-v1', 'readable_at_cut': bool(readable and not unread_rows),
            'reporting_scope_available': bool(readable), 'unread_rows': unread_rows,
            'excluded_count': len(performed.get('excluded') or [])}


def from_acts(performed: dict | None) -> list[dict]:
    """КС-2 rows for reconciliation or fallback fact: one row per act and position."""
    rows = []
    for position in (performed or {}).get("positions") or []:
        for part in position["parts"]:
            if part["quantity"] is None and not part.get('quantity_material'):
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


def _period_act(label):
    compact = compact_number(label)
    if compact is not None:
        return contract_acts.edition({'number': compact})
    match = re.fullmatch(r'\s*(?:(?:акт\s+)?КС\s*-?\s*2|акт)?\s*№\s*(\d+(?:\s*[/.-]\s*\d+)*)\s*',
                         str(label or ''), re.I)
    return contract_acts.edition({'number': match[1]}) if match else None


def _proved_zero_work(work):
    """A separate zero work component is proof; missing quantity is not zero."""
    periods = work.get('periods') or []
    return bool(periods) and work.get('reported_quantity') == 0 and all(
        period.get('quantity') in (None, 0)
        and (period.get('amount_split') is True and period.get('work_amount') == 0 or
             period.get('quantity') == 0 and not any(period.get(field) for field in
                 ('amount', 'material_quantity', 'work_amount', 'material_amount')))
        for period in periods)


def confirmation(performed: dict | None, found: dict | None, cut: str, reconciliation=None) -> dict:
    """Document confirmation is separate from the completeness of KS-6a facts."""
    if found is None or found.get('problem'):
        return {'state': 'no_statement', 'missing_acts': [], 'upload_required': False, 'message': ''}
    expected = {contract_acts.edition(act) for act in found.get('summary_acts') or []
                if act.get('date') and act['date'] <= cut}
    periods = [*(found.get('acts') or []),
               *(period for work in found.get('unread') or [] for period in work.get('periods') or [])]
    expected.update(_period_act(period.get('label')) for period in periods
                    if (not period.get('end') or period['end'] <= cut)
                    and any(period.get(field) for field in ('quantity', 'material_quantity', 'quantity_material',
                                                          'amount', 'act_amount')))
    expected.discard(None)
    present = {contract_acts.edition(act) for act in [*(performed or {}).get('acts', []),
                                                    *(performed or {}).get('excluded', [])]
               if not act.get('day') or act['day'] <= cut}
    present.discard(None)
    missing = sorted(expected-present, key=lambda n: (tuple(map(int, re.findall(r'\d+', n))), n))
    upload = bool(missing or not present)
    issues = [message for act in found.get('act_dates') or [] for message in act.get('warnings') or []]
    differs = bool(issues or reconciliation and (reconciliation['differs'] or reconciliation['only_ks2']
                                                 or reconciliation['only_ks6a']))
    verified = bool(reconciliation and not differs and not found.get('unread')
                    and not (performed or {}).get('excluded'))
    message = ('Загрузите КС-2' + (' № ' + ', '.join(missing) if missing else '') + ' для подтверждения.'
               if upload else 'КС-2 и КС-6а расходятся: проверьте сверку.' if differs else
               'Объёмы работ по КС-6а совпадают с КС-2.' if verified else
               'КС-2 загружены; для подтверждения проверьте даты и позиции актов.')
    return {'state': 'pending' if upload else 'differs' if differs else 'confirmed' if verified else 'review',
            'expected_acts': sorted(expected), 'missing_acts': missing,
            'upload_required': upload, 'message': message, 'issues': issues}


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

    KS-6a supplies the fact when at least one of its works is readable.
    Otherwise `performed` supplies КС-2 quantities, never added to the statement.
    """
    result = {"cut": cut, "assumption": ASSUMPTION, "total": 0.0, "lines": [], "months": [], "positions": [],
              "outside": {status: {"count": 0, "amount": 0.0} for status in _STATUSES},
              "before": None, "review": [], "unread": [], "price_differs": 0, "after_cut": 0, "note": "",
              "source": None, "source_note": "", "preliminary": False, "reconciliation": None,
              "materials": [], 'rds_positions': [], 'rds_unread': [],
              "component_gaps": [], 'material_statement': statement_materials(found, cut),
              'physical_groups': (found or {}).get('physical_groups') or [],
              'act_evidence': (performed or {}).get('evidence'),
              'ks_reporting_context': _ks2_reporting_context(performed),
              'physical_source_rows': (found or {}).get('physical_source_rows') or []}
    result['reconciliation'] = reconcile(performed, None if (found or {}).get('problem') else found, cut)
    result['confirmation'] = confirmation(performed, found, cut, result['reconciliation'])
    act_rows = from_acts(performed)
    statement_usable = found is not None and not found.get('problem') and bool(found.get('works'))
    if not statement_usable and act_rows:
        result['source'], result['source_note'] = 'ks2', FROM_KS2
        if found is not None:
            problem = (found.get('problem') or
                       ('В КС-6а не прочитаны объёмы ни одной работы.' if found.get('unread') else
                        'В КС-6а нет позиций работ для расчёта.'))
            result['source_note'] += ' ' + problem
        result['source_incomplete'] = True
        result['physical_groups'] = []
        result['confirmation'] = {'state': 'acts_only', 'missing_acts': [], 'upload_required': False,
                                  'message': 'Выполнение по загруженным КС-2; полнота комплекта актов не подтверждена.'}
        rows = act_rows
        result['preliminary'] = any(row.get('preliminary') for row in rows)
        result['after_cut'] = (performed or {}).get('later') or 0
    elif found is None:
        result['total'] = None
        result["note"] = "Накопительная КС-6а этого договора на дату среза не найдена: загрузите КС-6а для расчёта выполнения."
        return result
    elif found.get("problem"):
        result['total'] = None
        result["note"] = f"Выполнение по КС-6а не рассчитано. {found['problem']}"
        return result
    else:
        result["source"], result["source_note"] = "ks6a", FROM_KS6A
        result["unread"] = found.get("unread") or []
        rows = found.get("acts") or []
        result['preliminary'] = any(row.get('preliminary') for row in rows)
    current = next((e for e in editions if e["sha256"] == in_force), None)
    material_projection = (statement_components.project(found,current,cut) if result['source']=='ks6a'
                           else {'available':False})
    result['statement_components'] = statement_components.public(material_projection)
    result['valuation_gaps'] = []
    if result['source']=='ks6a' and material_projection.get('available'):
        uncertain_zero=set(material_projection.get('uncertain_zero_event_ids') or [])
        rows=list(rows)+[act for act in (found or {}).get('zero_acts') or []
            if statement_components.event_id(act) in uncertain_zero]
    result['material_ownership_unknown']=bool(material_projection.get('unknown') or
        material_projection.get('conflicts') or material_projection.get('unbound') or material_projection.get('unobserved'))
    if current is None:
        result['total'] = None
        result["note"] = "Нет редакции плана, действующей на дату среза: факт не с чем сопоставить."
        return result
    if result["source"] == "ks6a" and not found.get("works"):
        # No work with a known quantity: a zero here would be a missing KS-6a, not an answer.
        result['total'] = None
        result["note"] = ("В КС-6а не подтверждены даты или объёмы выполнения до среза. Причины указаны по работам."
                          if result['unread'] else
                          "В накопительной КС-6а нет позиций работ для расчёта выполнения.")
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
    last, material_last, done_quantity, position_facts, rds_positions = {}, {}, {}, {}, {}
    material_position_facts = {}
    seen_events = set()
    for act in rows:
        if material_projection.get('available'):
            event = statement_components.event_id(act)
            if event is None:
                result['review'].append({**act,'reason':'Не подтверждён неизменный идентификатор исходного периода КС-6а; повтор и сумма требуют проверки.'})
                continue
            if event in set(material_projection.get('conflicting_ids') or []):
                continue
            if event and event in seen_events:
                continue
            if event:
                seen_events.add(event)
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
        source_binding = (material_projection.get('bindings') or {}).get(act.get('item')) or {}
        current_at = source_binding.get('matched')
        current_position = (current['estimates'][current_at[0]]['positions'][current_at[1]]
                            if current_at is not None else None)
        source_identity=statement_components.position_evidence(found,act.get('item'))
        material_observed=act.get('quantity_material') not in (None,0) or act.get('basis')=='material'
        identity_changed = (bool(source_identity.get('name')) and material_observed and
            (_norm(position.get('name')) != _norm(act.get('name')) or _unit(position.get('unit')) != _unit(act.get('unit'))))
        if identity_changed:
            reason = ('Номер или родитель старой редакции обозначает другую позицию. '
                'Историческая стоимость этого компонента не подтверждена; сумма ведомости сохранена отдельно.')
            result['valuation_gaps'].append({'number':act['number'],'name':act['name'],
                'label':act.get('label') or '', 'end':act['end'],'edition':edition['title'],
                'source':act.get('source') or {},'reported_amount':act.get('act_amount'),'reason':reason})
            if current_at is not None:
                e,i=current_at
                position=current_position
            else:
                position={**position,'number':act['number'],'name':act['name'],'unit':act['unit']}
            price=None
            components=statement_components.unknown_historical(act,reason)
        else:
            price = _price(position)
            components = _components(act, position)
        if start is None or end >= start:
            _rds_observation(rds_positions, current, act, components, edition)
        money = components['total']
        if price is None and all(_price(position, part) is None for part in ('work', 'material')):
            result['review'].append({**act, 'edition': edition['title'],
                'reason': f"У позиции № {position['number']} в расчёте не прочитана цена за единицу."})
        # Only the volume that entered the fact counts toward a complete line: review volume is not known done.
        if act.get('basis') != 'material':
            done_quantity[act["item"]] = done_quantity.get(act["item"], 0.0) + components['work_quantity']
        if components['reason'] and not identity_changed:
            result['component_gaps'].append(f"Позиция № {position['number']}, {act.get('label') or 'период КС'}: " + components['reason'])
        if money is not None and act["act_amount"] is not None and abs(act["act_amount"] - money) > max(1.0, abs(money) * 0.005):
            result["price_differs"] += 1
        if start and end < start:
            place = "before"
            result["before"]["count"] += 1
            _accumulate_money(result['before'], money, known_value=components['known_total'])
        else:
            link = links_now.get(links.position_key(current_position or position))
            place = link["status"] if link else "missing"
            if place in _LINKED:
                for line in link["lines"]:
                    code, share = line['code'], line['share']
                    if act.get('basis') != 'material':
                        part = position_facts.setdefault(code, {}).setdefault(link['key'],
                            {'key': link['key'], 'quantity': 0.0, 'last': None, 'sources': []})
                        part['quantity'] += components['work_quantity'] * share
                        if components['work_quantity']:
                            part['last'] = max(part['last'] or act['end'], act['end'])
                        evidence = {'end': act['end'], 'label': act.get('label') or '',
                                    'source': act.get('source') or {}}
                        if evidence not in part['sources']:
                            part['sources'].append(evidence)
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
                        part=material_position_facts.setdefault(code,{}).setdefault(link['key'],
                            {'key':link['key'],'quantity':0.0,'amount':0.0,'unit':position['unit'],'last':None})
                        part['quantity'] += components['material_quantity']*share
                        part['amount']=_add_money(part['amount'],components['material_amount']*share if components['material_amount'] is not None else None)
                        if components['material_quantity'] or components['material_amount']:
                            part['last']=max(part['last'] or act['end'],act['end'])
                        unit = material_volumes.setdefault(code, {}).setdefault(
                            _unit(position["unit"]), {"unit": position["unit"], "quantity": 0.0})
                        unit['quantity'] += components['material_quantity'] * share
                    if share and (components['material_quantity'] or components['material_amount']):
                        material_last[code] = max(material_last.get(code, act['end']), act['end'])
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
                'source': statement_components.component_source(act.get('source') or {},'material'),
                'reported_amount':(act.get('amount_components') or {}).get('material'),
                'edition': edition['title']})
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
    # A missing dated row is not zero when that very position has unread KS-6a.
    # Resolve uncertainty by the same strict position and link rules as fact;
    # never assign an unread position by its caption alone.
    uncertain = {}
    # Explicit dated zero-only statement rows are omitted from financial flows.
    # Preserve their source proof for physical RDS cells, never infer zeros from absence.
    if result['source'] == 'ks6a':
        for act in (found or {}).get('zero_acts') or []:
            if statement_components.event_id(act) in seen_events:
                continue
            if not act.get('end') or act['end'] > cut or start and _day(act['end']) < start:
                continue
            matched = match(act, current['estimates'])
            if isinstance(matched, str):
                continue
            e, i, _ = matched
            _rds_observation(rds_positions, current, act,
                             _components(act, current['estimates'][e]['positions'][i]), current)
    for work in result['unread']:
        matched = match(work, current['estimates'])
        if isinstance(matched, str):
            continue
        e, i, _ = matched
        position = current['estimates'][e]['positions'][i]
        result['rds_unread'].append({'estimate': e, 'index': i,
            'estimate_sha256': current.get('estimate_sha256'),
            'work_zero_proved': _proved_zero_work(work),
            'reason': work.get('reason') or 'Объём в КС-6а не подтверждён.'})
        observed = rds_positions.get((e, i))
        if observed is not None:
            observed.setdefault('known_amount', observed['amount'] or 0.0)
            observed['amount'] = None
            observed['material_quantity'] = observed['material_amount'] = None
            if not _proved_zero_work(work):
                observed['work_quantity'] = observed['work_amount'] = None
            observed['reasons'].append(work.get('reason') or 'Объём в КС-6а не подтверждён.')
        key = links.position_key(position)
        link = links_now.get(key)
        if not link or link['status'] not in _LINKED:
            continue
        zero_work = _proved_zero_work(work)
        for target in link['lines']:
            if not target['share']:
                continue
            code = target['code']
            item = uncertain.setdefault(code, {'quantity_incomplete': False, 'reasons': []})
            reason = work.get('reason') or 'В КС-6а не подтверждены даты или объёмы выполнения.'
            if reason not in item['reasons']:
                item['reasons'].append(reason)
            item['quantity_incomplete'] |= not zero_work
            lines[code] = None
            if not zero_work:
                unknown_work.add(code)
                observed = position_facts.setdefault(code, {}).setdefault(key,
                    {'key': key, 'quantity': 0.0, 'last': None, 'sources': []})
                observed['known_quantity'] = observed.get('known_quantity', observed['quantity'])
                observed['quantity'] = None
            if position.get('amount', {}).get('material') != 0:
                unknown_material.add(code)
    if uncertain:
        result['known_total'] = result.get('known_total', result['total'])
        result['total'] = None
        result['quantity_incomplete'] = any(item['quantity_incomplete'] for item in uncertain.values())
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

    if material_projection.get('available'):
        material_position_facts = statement_components.by_line(material_projection)
        for code in material_position_facts:
            if code not in lines:
                lines[code]=None
                unknown_work.add(code)
                unknown_material.add(code)
    if result['valuation_gaps']:
        result['component_gaps'].append('Историческая стоимость частей КС-6а не подтверждена: '
            +str(len(result['valuation_gaps']))+'. Их исходные суммы и текущие физические связи показаны отдельно.')
    result["lines"] = [{"code": code, "fact": lines[code], "volumes": list(volumes.get(code, {}).values()),
                        'position_facts': list(position_facts.get(code, {}).values()),
                        **({'known_fact': known_lines.get(code, 0.0)} if lines[code] is None else {}),
                        'work_fact': None if code in unknown_work else work_money.get(code, 0.0),
                        'material_fact': None if code in unknown_material else material_money.get(code, 0.0),
                        'material_volumes': list(material_volumes.get(code, {}).values()),
                        'material_position_facts':list(material_position_facts.get(code,{}).values()),
                        'material_current_source':bool(material_projection.get('available')),
                        'material_positions_unknown':bool(material_projection.get('unknown') or
                            material_projection.get('conflicts') or material_projection.get('unbound') or material_projection.get('unobserved')),
                        'material_last': material_last.get(code),
                        "last": last.get(code), "complete": complete(code) and not uncertain.get(code, {}).get('quantity_incomplete'),
                        **uncertain.get(code, {})}
                       for code in order if code in lines]
    if material_projection.get('undated_component_unknown'):
        result['known_total']=result.get('known_total',result['total'])
        result['total']=None
        result['component_gaps'].append('Дата и объём материала исходного периода не подтверждены; полная историческая стоимость неизвестна.')
    if material_projection.get('conflicts') or material_projection.get('unbound') or material_projection.get('unobserved'):
        result['known_total']=result.get('known_total',result['total'])
        result['total']=None
        reason='Идентификатор или повтор исходного периода КС-6а не подтверждён либо содержит разные сведения; факт требует проверки.'
        result['note']=reason
        result['review'].append({'number':'','name':'Периоды КС-6а','reason':reason,
            'source_event_ids':material_projection.get('conflicting_ids') or []})
    result['component_gaps'] = list(dict.fromkeys(result['component_gaps']))
    result["positions"] = list(positions.values())
    result['rds_positions'] = list(rds_positions.values())
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
            result['months'].append({'month': end.isoformat()[:7], 'fact': None if uncertain else total,
                **({'known_fact': sum(m for d, m in dated_known_money if d <= end)}
                   if total is None or uncertain else {})})
    return result
