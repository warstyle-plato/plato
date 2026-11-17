"""Office report disclosures, projected from authoritative schedules (no financial model)."""
from __future__ import annotations

from datetime import date
from typing import Any


def _number(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _origin(x: dict, field: str) -> str:
    if field and x.get(field) in (None, ''):
        return 'Нет данных — значение во вводных отсутствует.'
    origin = (x.get('_field_origin') or {}).get('inputs.' + field) or {}
    origin = origin if isinstance(origin, dict) else {}
    return str(origin.get('text') or origin.get('source') or
               'вводные расчёта; ручной ввод или умолчание не различены в сохранённых данных')


def _parking(x: dict, t: dict, obj: Any) -> list[dict]:
    """Same proportional guest exclusion and price fallback as operating_model."""
    row = t.get(obj.key) or {}
    under, over = row.get('parking_under_units'), row.get('parking_over_units')
    saleable = row.get('parking_saleable_units')
    if under is None or over is None or saleable is None:
        return []
    total = under + over
    out = []
    for kind, count, label in [('under', under, 'Подземные места'),
                                ('over', over, 'Места на первых этажах')]:
        if count <= 0 or total <= 0 or saleable <= 0:
            continue
        field = f'{obj.prefix}_parking_{kind}_price_mln_per_space'
        raw = _number(x.get(field))
        fallback = raw is None or raw <= 0
        price = _number(x.get('parking_price_th')) if fallback else raw
        price = None if price is None else price * (1000 if fallback else 1e6)
        out.append(dict(key=f'{obj.key}:parking:{kind}', label=f'{obj.tep_label or obj.label} — {label}',
                        quantity=saleable * count / total, unit='шт.', base_price=price,
                        origin=('общая цена машино-места проекта (правило модели при пустой/нулевой цене типа); '
                                + _origin(x, 'parking_price_th')) if fallback else _origin(x, field)))
    return out


def build(x: dict, t: dict, op: dict, fin: dict, products: list[dict], objects: Any) -> dict:
    """One disclosure dataset for screen, PDF and workbook; money is RUB incl. VAT.

    Physical quantities and prices are never inferred from revenue alone. Direct
    sale weights are emitted by the simulator, DDU quantities by operating_model.
    Parking decomposition uses the exact bases of the existing weighted price.
    """
    result: list[dict] = []
    warnings: list[str] = []
    valuation_missing: list[dict] = []
    nonres = {o['key']: o for o in (fin.get('nonres') or {}).get('objects') or []}
    registry = {o.key: o for o in objects}

    def add(component: dict, quantities: dict, revenue: dict, *, strategy: str,
            reference: str | None, note: str) -> None:
        quantity = component.get('quantity')
        rows, cumulative = [], 0.0
        months = sorted(set(quantities) | set(revenue))
        if months:
            # Include idle months between sales, rather than disguising pauses.
            start, end = date.fromisoformat(str(months[0])[:10]), date.fromisoformat(str(months[-1])[:10])
            months = []
            while start <= end:
                months.append(start.isoformat())
                start = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        for month in months:
            q = quantities.get(month, 0.0)
            value = revenue.get(month, 0.0)
            cumulative += q
            price = value / q if q > 0 and component.get('base_price') is not None else None
            rows.append(dict(month=month[:7], quantity=q, cumulative=cumulative,
                             remaining=max(0.0, quantity - cumulative) if quantity is not None else None,
                             revenue=value, price=price))
        active = [r for r in rows if r['quantity'] > 0]
        value = sum(revenue.values())
        result.append({**component, 'strategy': strategy, 'reference_date': reference,
                       'first_date': active[0]['month'] if active else None,
                       'last_date': active[-1]['month'] if active else None,
                       'first_price': active[0]['price'] if active else None,
                       'last_price': active[-1]['price'] if active else None,
                       'average_price': value / cumulative if cumulative > 0 and component.get('base_price') is not None else None,
                       'revenue': value, 'rows': rows, 'note': note,
                       'price_end_note': 'Вне периодов реализации цена на конец расчёта моделью не рассчитывается.'})

    def iso(series: dict) -> dict:
        return {str(k)[:10]: v for k, v in series.items()}

    def split(components: list[dict], q: dict, revenue: dict) -> None:
        total_q = sum(c['quantity'] for c in components)
        base = sum(c['quantity'] * (c['base_price'] or 0.0) for c in components)
        for c in components:
            qs = {m: v * c['quantity'] / total_q for m, v in q.items()} if total_q else {}
            rs = {m: v * c['quantity'] * (c['base_price'] or 0.0) / base for m, v in revenue.items()} if base else {}
            add(c, qs, rs, strategy=context['strategy'], reference=context['reference'], note=context['note'])

    # DDU and other products already sold by operating_model.
    for p in products:
        key = p['key']
        if p.get('excluded') or not p.get('sellable') or key in nonres:
            continue
        quantity_series = iso((op.get('quantity_product_schedules') or {}).get(key) or {})
        revenue_series = iso((op.get('revenue_product_schedules') or {}).get(key) or {})
        if not quantity_series:
            continue
        obj = registry.get(key)
        parent = p.get('object')
        parking_obj = registry.get(parent) if parent else None
        obj = obj or parking_obj
        prefix = obj.prefix if obj else ''
        schedule_note = (op.get('object_schedule_notes') or {}).get(prefix or 'core') or {}
        profile = ('Применён заданный профиль: ' + str(p.get('sales_profile'))
                   if schedule_note.get('profile_applied') else
                   'Темп — стандартное распределение действующей модели; пользовательский профиль не применён.')
        growth_fields = ([prefix + f'_growth_stage{k}_pct' for k in (1, 2, 3, 4)]
                         if schedule_note.get('steps_applied') else
                         [prefix + '_growth_pre_pct', prefix + '_growth_post_pct'])
        note = ('Расчётный план, не фактические продажи. ДДУ: деньги покупателей на эскроу, '
                'раскрытие и поступление проекту — в денежном потоке финансирования. ' +
                (p.get('price_ladder') if schedule_note.get('steps_applied') else
                 f"Рост цены до ввода: {x.get(prefix + '_growth_pre_pct', 'не задан')}%/мес.; "
                 f"после ввода: {x.get(prefix + '_growth_post_pct', 'не задан')}%/мес.") +
                ' Источник динамики: ' + '; '.join(f"{('ступень ' + str(i+1)) if schedule_note.get('steps_applied') else ('рост до ввода' if i==0 else 'рост после ввода')}: {_origin(x, f)}" for i,f in enumerate(growth_fields)) +
                '. ' + profile + ' ' + '; '.join(p.get('schedule_warnings') or []))

        context = dict(strategy='ДДУ', reference=str(x.get(prefix + '_sales_start') or '')[:7], note=note)
        if parking_obj and parking_obj.garage_sellable:
            split(_parking(x, t, parking_obj), quantity_series, revenue_series)
        else:
            field = obj.rate_price if obj else ''
            add(dict(key=key, label=p['label'], quantity=p.get('quantity'), unit=p['unit'],
                     base_price=(p.get('start_price_th', 0.0) * 1000 if not obj or _number(x.get(field)) is not None else None),
                     origin=_origin(x, field)), quantity_series, revenue_series,
                strategy=context['strategy'], reference=context['reference'], note=note)
    for key, item in nonres.items():
        obj = registry.get(key)
        if obj is None:
            warnings.append('Нет описания продукта ' + key)
            continue
        book = item.get('book') or {}
        params = book.get('params') or {}
        rows = item.get('rows') or []
        warnings.extend(item['title'] + ': ' + str(w) for w in item.get('warnings') or [])
        if item['strategy'] == 'direct':
            components = [dict(key=key, label=item['title'], quantity=book.get('area_sqm'),
                               unit='шт.' if obj.measure == 'spaces' else 'м²', base_price=book.get('price_rub_sqm') if _number(x.get(obj.rate_price)) is not None else None, origin=_origin(x, obj.rate_price))]
            components += _parking(x, t, obj) if obj.garage_sellable else []
            for c in components:
                quantities = {r['month']: r.get('sale_weight', 0.0) * c['quantity'] for r in rows}
                revenues = {r['month']: r.get('sale_price_factor', 0.0) * quantities[r['month']]
                            * (c['base_price'] or 0.0) for r in rows}
                # Keep only the sales window, including deliberate zero-revenue sales.
                active = [r['month'] for r in rows if r.get('sale_weight', 0.0) > 0]
                quantities = {m: v for m, v in quantities.items() if active and active[0] <= m <= active[-1]}
                revenues = {m: revenues[m] for m in quantities}
                add(c, quantities, revenues, strategy='ДКП', reference=str(book.get('price_start') or '')[:7],
                    note=f"Расчётный план, не факт. Рост до ввода {book.get('growth_pre', 0)*100:g}%/мес., "
                         f"после {book.get('growth_post', 0)*100:g}%/мес.; основание — вводные модели. "
                         f"Профиль: {params.get('direct_sale_curve', 'flat')}. Происхождение роста: "
                         + _origin(x, obj.prefix + '_growth_pre_pct') + '; после ввода: '
                         + _origin(x, obj.prefix + '_growth_post_pct'))
        else:
            # Cash rent and transaction exit are separate from residual valuation.
            rent_rows = [dict(month=r['month'][:7], revenue=r.get('rent_revenue', 0.0),
                              occupancy=r.get('occupancy')) for r in rows if r.get('occupancy') is not None]
            rent = item['totals'].get('rent_revenue')
            result.append(dict(key=key+':rent', label=item['title']+' — аренда (включая сдаваемые места)',
                               unit='м² и машино-места', quantity=None, revenue=rent, strategy='Аренда',
                               rows=rent_rows, note='Расчётное заполнение и аренда; ставки и индексация — в стратегии объекта.'))
            value_reason = ('ставка капитализации не задана' if (_number(params.get('exit_cap_pct')) or 0) <= 0 else
                            'нет положительного NOI для оценки' if float((item.get('kpi') or {}).get('forward_noi') or 0) <= 0 else '')
            if item.get('exit_mode') == 'hold' and value_reason:
                valuation_missing.append(dict(key=key,label=item['title'],reason=value_reason))
                warnings.append(item['title']+': оценка удержания — нет данных; '+value_reason)
            if item.get('exit_mode') != 'hold':
                exit_date = (item.get('kpi') or {}).get('exit_month')
                value = item['totals'].get('exit_revenue')
                if exit_date is not None and value is not None and value > 0:
                    add(dict(key=key+':exit', label=item['title']+' — продажа объекта при выходе',
                             quantity=1.0, unit='объект', base_price=value,
                             origin='Допущение модели: капитализация NOI следующих 12 месяцев; ставка капитализации — вводные объекта.'),
                        {exit_date: 1.0}, {exit_date: value}, strategy='Выход', reference=exit_date[:7],
                        note='Расчётная продажа целого объекта по капитализации NOI, не цена продажи м². '
                             'Цена определяется на дату выхода, отдельная исходная цена продажи не задаётся.')
                else:
                    reason = ('ставка капитализации не задана' if (_number(params.get('exit_cap_pct')) or 0) <= 0 else
                              'дата выхода не задана' if exit_date is None else
                              'положительная стоимость выхода не определена из NOI')
                    warnings.append(item['title']+' — продажа объекта: нет данных; '+reason+'.')
                    result.append(dict(key=key+':exit',label=item['title']+' — продажа объекта при выходе',
                                       quantity=None,unit='объект',revenue=value,strategy='Выход',rows=[],
                                       planned_date=exit_date,missing_reason=reason))
    cash = sum(p['revenue'] for p in result if p.get('revenue') is not None)
    valuation = sum((o.get('totals') or {}).get('residual_value', 0.0) for o in nonres.values())
    expected = fin.get('total_revenue')
    for p in result:
        p['share'] = p['revenue'] / cash if cash and p.get('revenue') is not None else None
    gap = None if expected is None else expected - cash - valuation
    if gap is not None and abs(gap) > 1.0:
        warnings.append(f'Раскрытие продуктов не сходится с итогом модели: разница {gap:,.2f} ₽.')
    return dict(products=result, cash_revenue=cash, valuation=valuation, model_revenue=expected,
                reconciliation_gap=gap, warnings=warnings, valuation_missing=valuation_missing)


def combine(results: list[dict], expected: float) -> dict:
    products, warnings, valuation_missing = [], [], []
    valuation = 0.0
    for index, r in enumerate(results, 1):
        data = (r.get('report') or {}).get('office_results') or {}
        valuation += data.get('valuation', 0.0)
        warnings.extend(data.get('warnings') or [])
        valuation_missing.extend(data.get('valuation_missing') or [])
        for p in data.get('products') or []:
            products.append({**p, 'key': f"phase{index}:{p['key']}",
                             'label': f"Очередь {index} — {p['label']}"})
    cash = sum(p['revenue'] for p in products)
    for p in products:
        p['share'] = p['revenue'] / cash if cash and p.get('revenue') is not None else None
    gap = expected - cash - valuation
    if abs(gap) > 1:
        warnings.append(f'Раскрытие очередей не сходится с итогом: {gap:,.2f} ₽.')
    return dict(products=products, cash_revenue=cash, valuation=valuation, model_revenue=expected,
                reconciliation_gap=gap, warnings=warnings, valuation_missing=valuation_missing)


def blocks(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Common report block schema consumed by HTML, PDF and Excel."""
    income, sales, assumptions = [], [], []
    products = data.get('products') or []
    table = []
    for p in products:
        table.append(dict(label=p['label'], quantity=p.get('quantity'), unit=p['unit'],
                          first=p.get('first_price', None), last=p.get('last_price', None),
                          average=p.get('average_price', None), revenue=p.get('revenue'), share=p.get('share')))
    income.append(dict(title='Состав денежной выручки по продуктам', kind='product_revenue',
                       note='Цены — ₽ за указанную единицу, с НДС; м² — продаваемая площадь. '
                            'Первая/последняя — цены периодов продаж; средняя взвешена объёмами. '
                            'Аренда и выход — отдельные денежные потоки; оценка удержания в доли не входит.',
                       columns=[['label','Продукт / тип','text'],['quantity','Объём','num'],['unit','Ед.','text'],
                                ['first','Первая цена, ₽/ед.','num'],['last','Последняя цена, ₽/ед.','num'],
                                ['average','Средняя цена, ₽/ед.','num'],['revenue','Выручка','rub'],['share','Доля','pct']],
                       widths=[38,16,13,21,21,21,24,16], years=table))
    rows = [dict(label='Денежная выручка — продажи и аренда', value=data.get('cash_revenue'), unit='rub')]
    if data.get('valuation'):
        rows += [dict(label='Оценка удерживаемых объектов — без сделки, не денежная выручка', value=data['valuation'], unit='rub'),
                 dict(label='Итог модели, включая оценку', value=data.get('model_revenue'), unit='rub')]
    rows.extend(dict(label=p['label']+' — оценка удержания', value='Нет данных — '+p['reason'], unit='text') for p in data.get('valuation_missing') or [])
    rows.append(dict(label='Расхождение с итогом модели (деньги + оценка), ₽',value=(0.0 if data.get('reconciliation_gap') is not None and abs(data['reconciliation_gap'])<.01 else data.get('reconciliation_gap')),unit='num'))
    income.append(dict(title='Сверка выручки', rows=rows))
    for p in products:
        periods = p.get('rows') or []
        if p.get('missing_reason'):
            sales.append(dict(title=p['label'],rows=[
                dict(label='Планируемая дата выхода',value=p.get('planned_date'),unit='date'),
                dict(label='Цена и объём продажи',value='Нет данных — '+p['missing_reason'],unit='text')]))
            continue
        if not periods:
            continue
        if p['strategy'] == 'Выход':
            sales.append(dict(title=p['label']+' — цена и расчётный план',
                              note=p['note']+' '+p['origin'], kind='single_sale_plan',
                              years=periods, columns=[['month','Дата сделки','text'],
                                  ['quantity','Объектов','num'],['price','Цена сделки, ₽/объект, с НДС','num'],
                                  ['revenue','Выручка','rub']],
                              widths=[25,25,65,55]))
            continue
        if p['strategy'] == 'Аренда':
            sales.append(dict(title=p['label']+' — заполнение и аренда', kind='monthly_plan',
                              note=p['note'], years=periods, columns=[['month','Месяц','text'],
                               ['occupancy','Заполнение','pct'],['revenue','Арендная выручка','rub']],
                              charts=[dict(title='Заполнение, %', unit='%', fields=[['occupancy','Заполнение']], multiplier=100),
                                      dict(title='Аренда, млн ₽/мес.', unit='млн ₽', fields=[['revenue','Аренда']], multiplier=1e-6)]))
            continue
        unit = p['unit']
        price_rows = [dict(label='Период продаж', value=f"{p.get('first_date') or 'не задан'} — {p.get('last_date') or 'не задан'}",unit='text')]
        first, base = p.get('first_price'), p.get('base_price')
        if base is None or first is None or abs(base-first) > 0.01:
            price_rows.append(dict(label=f"Исходная цена на {p.get('reference_date') or 'неизвестную дату'}, ₽/{unit}, с НДС",value=base,unit='num'))
        price_rows += [dict(label=f"Первая продажа ({p.get('first_date')}), ₽/{unit}, с НДС",value=first,unit='num'),
                       dict(label=f"Последняя продажа ({p.get('last_date')}), ₽/{unit}, с НДС",value=p.get('last_price'),unit='num'),
                       dict(label=f'Средневзвешенная цена, ₽/{unit}, с НДС',value=p.get('average_price'),unit='num'),
                       dict(label='Источник исходной цены',value=p.get('origin'),unit='text'),
                       dict(label='Динамика и темп',value=p['note'],unit='text'),
                       dict(label='Цена на конец расчёта',value=p['price_end_note'],unit='text')]
        sales.append(dict(title=p['label']+' — цены',rows=price_rows))
        sales.append(dict(title=p['label']+' — расчётный план продаж', kind='monthly_plan', years=periods,
                          note=f'Объёмы в {unit}; деньги с НДС. Накопление и остаток — физический объём, не доля выручки. '
                               'Таблица показывает изменения цены и темпа по месяцам, включая паузы.',
                          columns=[['month','Месяц','text'],['quantity',f'{unit}/мес.','num'],
                                   ['cumulative',f'Продано, {unit}','num'],['remaining',f'Остаток, {unit}','num'],
                                   ['price',f'Цена, ₽/{unit}','num'],['revenue','Выручка','rub']],
                          charts=[dict(title=f'Темп, {unit}/мес.',unit=unit,fields=[['quantity','Темп']],multiplier=1),
                                  dict(title=f'Продано и остаток, {unit}',unit=unit,fields=[['cumulative','Продано'],['remaining','Остаток']],multiplier=1),
                                  dict(title='Выручка, млн ₽/мес.',unit='млн ₽',fields=[['revenue','Выручка']],multiplier=1e-6),
                                  dict(title=f'Цена, тыс. ₽/{unit}',unit=f'тыс. ₽/{unit}',fields=[['price','Цена']],multiplier=.001)]))
    assumptions.append(dict(title='Основания и ограничения раскрытия',rows=[
        dict(label='Статус продаж',value='Расчётный план. Фактические сделки в этих рядах отсутствуют.',unit='text'),
        dict(label='Машино-места',value='Размещение — только заданные в ТЭП типы. Гостевые исключены пропорционально, как в расчёте. Дробные места — расчётное распределение; округление не меняет выручку.',unit='text'),
        dict(label='Отсутствующие значения',value='Прочерк означает: показатель не задан либо неприменим к этому потоку. У аренды нет цены продажи м², у выхода цена определяется NOI. Нулевая цена типа парковки по правилу текущей модели наследует общую цену; это подписано у продукта.',unit='text'),
        *[dict(label='Сверка',value=w,unit='text') for w in data.get('warnings') or []]]))
    return income, sales, assumptions
