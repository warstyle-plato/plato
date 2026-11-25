"""Source-bound KS6 observations/current material ownership, never historical repricing."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import re
from developaid_monitor_contracts import _norm
from developaid_monitor_statement_union import _unit
import developaid_contract_schedule_links as links

HEX = re.compile(r'^[0-9a-f]{64}$')
QUANTITY_TOLERANCE = 1e-6
# RDS whole component costs are printed to kopecks; KS6 retains four decimals.
PRINTED_COST_TOLERANCE = .00500001
CURRENT_MATERIAL_BASIS = ('Вклад поставки: стоимость каждого компонента текущей РДС умножена '
    'на подтверждённую долю его собственного объёма, не более 100% по каждой позиции. '
    'Это текущая мера готовности, а не сумма КС и не историческая оценка редакции периода. '
    'Компонентные суммы РДС округлены до копеек, поэтому возможна разница округления с исходной суммой КС.')


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def code(value):
    return re.sub(r'\s+', '', str(value or '')).strip('.')


def position_source(item):
    source = dict(item.get('source') or {})
    source.setdefault('file_sha256', item.get('file_sha256'))
    return {'number': item.get('position') or '', 'name': item.get('name') or '',
        'unit': item.get('unit') or '', 'quantity': item.get('plan_quantity'),
        'material_amount': item.get('planned_material_amount'),
        'cost_method': item.get('planned_cost_method'),
        'cost_split': item.get('planned_cost_split') is True, 'source': source}


def period_source(item, period):
    parent = item.get('source') or {}
    # Annual AU/AW coordinates must not become a period's L/N.
    out = {k: parent[k] for k in ('filename','sheet','row','file_sha256','snapshot_id','source_date') if k in parent}
    out.setdefault('file_sha256', item.get('file_sha256'))
    out.update(period.get('source') or {})
    return out


def component_source(source, component):
    out = {k:v for k,v in source.items() if k not in ('quantity_cell','amount_cell')}
    quantity, amount = source.get(component+'_quantity_cell'), source.get(component+'_amount_cell')
    out.update(component=component, quantity_cell=quantity, amount_cell=amount)
    if not quantity or not amount:
        out['legacy_cells'] = {k:source[k] for k in ('quantity_cell','amount_cell') if source.get(k)}
        out['coordinate_note'] = 'Раздельные ячейки компонента не сохранены в прежнем разборе; указан источник и строка.'
    return out


def _source_valid(source):
    return (isinstance(source.get('file_sha256'),str) and bool(HEX.fullmatch(source['file_sha256']))
        and isinstance(source.get('sheet'),str) and bool(source['sheet'])
        and type(source.get('row')) is int and source['row'] > 0)


def current_match(evidence, current):
    """One current priced leaf by full identity and retained component evidence."""
    if not evidence or not _source_valid(evidence.get('source') or {}):
        return None, 'Не сохранено однозначное происхождение строки КС-6а.'
    quantity, amount = evidence.get('quantity'), evidence.get('material_amount')
    if (not evidence.get('cost_split') or evidence.get('cost_method') not in
        ('quantity_times_labelled_unit_price','labelled_subtotals') or not numeric(quantity)
        or quantity <= 0 or not numeric(amount) or amount < 0):
        return None, 'Не подтверждены полный объём и отдельная плановая стоимость материала.'
    if not code(evidence.get('number')) or not _norm(evidence.get('name')) or not _unit(evidence.get('unit')):
        return None, 'Не подтверждены полный номер, название или единица позиции.'
    candidates = []
    for e,estimate in enumerate(current.get('estimates') or []):
        if estimate.get('scope') == 'accepted':
            continue
        for i,position in enumerate(estimate.get('positions') or []):
            whole = (position.get('amount') or {}).get('material')
            base = position.get('quantity')
            if (code(position.get('number')) == code(evidence['number']) and
                _norm(position.get('name')) == _norm(evidence['name']) and
                _unit(position.get('unit')) == _unit(evidence['unit']) and numeric(base) and
                abs(base-quantity) <= QUANTITY_TOLERANCE and numeric(whole) and
                abs(whole-amount) <= PRINTED_COST_TOLERANCE):
                candidates.append((e,i))
    return (candidates[0], '') if len(candidates) == 1 else (None,
        'Нет единственной текущей позиции с теми же номером, названием, единицей, объёмом и стоимостью материала.')


def event_id(act):
    source = act.get('source') or {}
    if not _source_valid(source):
        return None
    # Coordinates are parser evidence, not event identity: legacy N+O and
    # separately labelled N identify the same source period after refresh.
    label=str(act.get('label') or '').strip()
    period=['label',label] if label else None
    if period is None:
        return None
    value = [source['file_sha256'],source['sheet'],source['row'],period,'work_and_material_components']
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def position_evidence(found,item):
    records=(found or {}).get('source_positions') or {}
    return records.get(item) or records.get(str(item)) or {}


def _event_signature(act,found):
    proof=position_evidence(found,act.get('item'))
    identity=(code(proof.get('number')),_norm(proof.get('name')),_unit(proof.get('unit')),
        proof.get('quantity'),proof.get('material_amount'),proof.get('cost_method'),proof.get('cost_split'))
    return (code(act.get('number')),_norm(act.get('name')),_unit(act.get('unit')),
        act.get('quantity'),act.get('quantity_material'),act.get('amount_components'),
        act.get('start'),act.get('end'),act.get('basis') or 'work',
        act.get('dated_by') or '',act.get('preliminary') is True,identity)


def observations(found):
    rows = list((found or {}).get('acts') or []) + list((found or {}).get('zero_acts') or [])
    for item in (found or {}).get('unread') or []:
        rows.extend({'number':item['number'],'name':item['name'],'unit':item['unit'],'item':item['item'],
            'quantity':p.get('quantity'),'quantity_material':p.get('material_quantity'),
            'amount_components':{'work':p.get('work_amount'),'material':p.get('material_amount'),'total':p.get('amount')},
            'act_amount':p.get('amount'),'start':p.get('start'),'end':p.get('end'),'label':p.get('label') or '',
            'source':p.get('source') or item.get('source') or {}} for p in item.get('periods') or [])
    unique, conflicts, unbound = {}, set(), []
    for act in rows:
        identity = event_id(act)
        if identity is None:
            unbound.append(act)
            continue
        previous = unique.get(identity)
        if previous is not None:
            if _event_signature(previous,found) != _event_signature(act,found):
                conflicts.add(identity)
            continue
        unique[identity] = act
    return [(key,act) for key,act in unique.items() if key not in conflicts], conflicts, unbound


def _cash():
    return {'work':0.0,'material':0.0,'total':0.0,'known_work':0.0,'known_material':0.0,'known_total':0.0,'events':0}


def _add(bucket, act):
    bucket['events'] += 1
    amounts = act.get('amount_components') or {}
    for key in ('work','material','total'):
        value = amounts.get(key) if key != 'total' else amounts.get('total',act.get('act_amount'))
        if numeric(value):
            bucket['known_'+key] += value
            if bucket[key] is not None:
                bucket[key] += value
        else:
            bucket[key] = None


def material_quantity(act):
    return act.get('quantity') if act.get('basis')=='material' else act.get('quantity_material')


def material_quantity_unknown(act,evidence,current_material):
    planned=evidence.get('material_amount')
    no_component=numeric(planned) and planned==0 and numeric(current_material) and current_material==0
    return not numeric(material_quantity(act)) and not no_component


def project(found, current, cut):
    """Observe each source period once; project quantities through existing current links."""
    current = current or {}
    evidence = (found or {}).get('source_positions') or {}
    out = {'available':any(_source_valid(x.get('source') or {}) for x in evidence.values()),'source':'ks6a','cut':cut,'positions':[], 'events':[], 'unknown':[],
        'cash':{k:_cash() for k in ('source','current','before','after_cut','undated')},
        'basis':CURRENT_MATERIAL_BASIS,'bindings':{},'conflicts':0,'unbound':0,
        'uncertain_zero_event_ids':[],'undated_component_unknown':False,
        'sources':(found or {}).get('statement_sources') or [], 'date_basis':(found or {}).get('act_dates') or []}
    if not out['available']:
        return out
    events,conflicts,unbound = observations(found)
    out['source_hashes']=sorted({act['source']['file_sha256'] for _,act in events})
    out['unobserved']=not events and not conflicts and not unbound
    out.update(conflicts=len(conflicts),unbound=len(unbound),conflicting_ids=sorted(conflicts))
    bindings = {}
    for item,source in evidence.items():
        matched,reason = current_match(source,current)
        bindings[int(item)] = {'matched':matched,'reason':reason,'evidence':source}
    out['bindings'] = bindings
    positions = {}
    for identity,act in events:
        end = act.get('end')
        try:
            valid_date = bool(end) and dt.date.fromisoformat(end).isoformat() == end
        except (ValueError,TypeError):
            valid_date = False
        bucket = ('undated' if not valid_date else 'after_cut' if end > cut else
                  'before' if current.get('start') and end < current['start'] else 'current')
        _add(out['cash']['source'],act)
        _add(out['cash'][bucket],act)
        quantity = material_quantity(act)
        binding = bindings.get(act.get('item')) or {}
        matched_position=binding.get('matched')
        current_material=((current['estimates'][matched_position[0]]['positions'][matched_position[1]].get('amount') or {}).get('material')
                          if matched_position is not None else None)
        component_unknown=material_quantity_unknown(act,binding.get('evidence') or {},current_material)
        amounts=act.get('amount_components') or {}
        reported = amounts.get('material')
        if bucket=='current' and numeric(amounts.get('total')) and amounts['total']!=0 and any(
                not numeric(amounts.get(k)) for k in ('work','material')):
            out['unknown'].append({'id':identity,'number':act['number'],'label':act.get('label') or '',
                'reason':'В исходной сумме периода не отделены работы и материалы.','source':act['source']})
        if quantity in (None,0) and reported in (None,0) and not component_unknown:
            continue
        if component_unknown:
            if bucket=='undated':out['undated_component_unknown']=True
            else:out['uncertain_zero_event_ids'].append(identity)
        matched = binding.get('matched')
        event = {'id':identity,'number':act['number'],'name':act['name'],'unit':act['unit'],
            'quantity':quantity,'reported_amount':reported,'label':act.get('label') or '', 'end':end,
            'scope':bucket,'source':component_source(act['source'],'material'),
            'match':list(matched) if matched is not None else None,
            'reason':('Объём материала не подтверждён; ноль работ не доказывает отсутствие поставки.'
                if component_unknown else binding.get('reason') or '')}
        out['events'].append(event)
        if bucket=='undated':
            out['unknown'].append({**event,'reason':'Дата периода поставки не подтверждена; вклад на дату среза неизвестен.'})
        if bucket != 'current':
            continue
        if matched is None or not numeric(quantity) or not _unit(act.get('unit')):
            out['unknown'].append(event)
            continue
        e,i = matched
        position=current['estimates'][e]['positions'][i]
        key=links.position_key(position)
        record=positions.setdefault((e,i),{'estimate':e,'index':i,'key':key,'number':position['number'],
            'name':position['name'],'unit':position['unit'],'quantity':0.0,'reported_amount':0.0,
            'base_quantity':position['quantity'],'current_amount':(position.get('amount') or {}).get('material'),
            'source_sha256':current.get('estimate_sha256'),'events':[],'last':None})
        record['quantity'] += quantity
        record['reported_amount'] = (record['reported_amount']+reported
            if record['reported_amount'] is not None and numeric(reported) else None)
        record['events'].append(event)
        record['last']=max(record['last'] or end,end)
    out['positions']=list(positions.values())
    for record in out['positions']:
        estimate=current['estimates'][record['estimate']]
        bindings=[b for b in (estimate.get('links') or {}).get('positions') or [] if b.get('key')==record['key']]
        link=bindings[0] if len(bindings)==1 else None
        record['place']=link.get('status') if link else 'review'
        record['lines']=list(link.get('lines') or []) if link and link.get('status') in ('confirmed','proposed') else []
    for record in out['positions']:
        if record['quantity'] < -QUANTITY_TOLERANCE:
            record['reason']='Накопленный объём поставки после корректировок отрицателен.'
            record['quantity']=None
    if conflicts or unbound or out.get('unobserved'):
        for bucket in out['cash'].values():
            bucket.update(work=None,material=None,total=None)
    linked=[p for p in out['positions'] if p.get('lines')]
    out['coverage']={'events':len(out['events']),'current_events':sum(e['scope']=='current' for e in out['events']),
        'positions':len(out['positions']),'linked_positions':len(linked),
        'targets':len({t['code'] for p in linked for t in p['lines']}),
        'unknown_events':len(out['unknown']),'unlinked_positions':len(out['positions'])-len(linked)}
    out['reported_current_mapped_material']=sum(p['reported_amount'] for p in out['positions']) if all(
        numeric(p['reported_amount']) for p in out['positions']) else None
    return out


def by_line(projection):
    result = {}
    for record in projection.get('positions') or []:
        for target in record.get('lines') or []:
            share=target.get('share')
            if not numeric(share) or share < 0:
                continue
            result.setdefault(target['code'],{})[record['key']]={
                'key':record['key'],'quantity':record['quantity']*share if numeric(record['quantity']) else None,
                'unit':record['unit'],'last':record['last'],'reported_amount':record['reported_amount'],
                'events':[event['id'] for event in record['events']], 'source_sha256':record['source_sha256']}
    return result


def public(projection):
    return {key:value for key,value in projection.items() if key not in ('bindings','conflicting_ids')}


def unknown_historical(act, reason):
    work = 0.0 if act.get('basis')=='material' else act.get('quantity')
    material = act.get('quantity') if act.get('basis')=='material' else act.get('quantity_material')
    wm = 0.0 if work==0 else None
    mm = 0.0 if material==0 else None
    return {'work_quantity':work,'material_quantity':material,'work_amount':wm,'material_amount':mm,
        'total':0.0 if wm==mm==0 else None,'known_total':0.0,'reason':reason,
        'material_basis':'Количество материала из отдельных граф КС-6а; историческая стоимость не подтверждена.'}


def summary(fact, measured=None):
    """Canonical cash/valuation reconciliation; none of these bases is installation."""
    projection=fact.get('statement_components') or {}
    if not projection.get('available'):
        return None
    sources=projection.get('sources') or []
    raw=projection['cash']['source']
    hashes=set(projection.get('source_hashes') or [])
    matching=[r for r in sources if _source_valid(r.get('source') or {})
        and hashes=={(r.get('source') or {}).get('file_sha256')} and numeric(r.get('completed')) and numeric(raw.get('total'))
        and abs(r['completed']-raw['total'])<=.00500001]
    ref=matching[0] if len(matching)==1 else {}
    planned=ref.get('planned')
    undated=(projection.get('cash',{}).get('undated') or {}).get('events',0)
    comparable=(ref.get('monetary_comparable') is True and numeric(planned) and planned>0 and not undated)
    components=(measured or {}).get('components') or {}
    total=(measured or {}).get('total') or {}
    counted=[c.get('counted') for c in components.values()]
    return {'source':'ks6a','cut':projection.get('cut'),'cash':projection['cash'],
        'coverage':projection.get('coverage') or {},'source_dates':sorted({
            r.get('source_date') or (r.get('source') or {}).get('source_date') for r in sources
            if r.get('source_date') or (r.get('source') or {}).get('source_date')}),
        'sources':[r.get('source') or {} for r in sources],
        'planned':planned if numeric(planned) else None,
        'ratio':raw['total']/planned if comparable and numeric(raw.get('total')) else None,
        'ratio_basis':'Стоимость этой же ведомости; не доля текущей цены договора и не физическая готовность.',
        'ratio_unknown_reason':('' if comparable else 'Даты исходных периодов не подтверждены; денежная доля неизвестна.' if undated
            else 'Сопоставимость денежной базы ведомости не подтверждена.'),
        'amount_basis':ref.get('completed_amount_basis') or 'unspecified',
        'date_basis':'Суммы исходной КС-6а; периоды по датам актов, даты из подписания отмечены как предварительные.',
        'preliminary':bool(fact.get('preliminary')),'date_evidence':projection.get('date_basis') or [],
        'historical':{'total':fact.get('total'),'known_total':fact.get('known_total',fact.get('total')),
            'unknown_events':len(fact.get('valuation_gaps') or []),
            'basis':'Количество по цене РДС, действовавшей в конце периода КС; неподтверждённая идентичность или цена не подменяется текущей.'},
        'current':{'counted':sum(counted) if counted and all(numeric(x) for x in counted) else None,
            'components':components,'amount':total.get('amount'),'readiness':total.get('readiness'),
            'basis':CURRENT_MATERIAL_BASIS},
        'notice':'Денежное закрытие по КС — не оплата. Поставка материала — не выполненный объём монтажа.'}
