"""Office report disclosures, projected from authoritative schedules (no financial model)."""
from __future__ import annotations

from datetime import date
from typing import Any


def _origin(x: dict, field: str) -> str:
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
        raw = x.get(field)
        fallback = raw is None or raw <= 0
        price = x.get('parking_price_th') if fallback else raw
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
        note = ('Расчётный план, не фактические продажи. ' +
                (p.get('price_ladder') or f"Рост цены до ввода: {x.get(prefix + '_growth_pre_pct', 'не задан')}%/мес.; "
                 f"после ввода: {x.get(prefix + '_growth_post_pct', 'не задан')}%/мес.") +
                ' Основание динамики — вводные расчёта; при отсутствии происхождения ручной ввод не подтверждён. ' +
                str(p.get('sales_profile') or 'Темп — распределение продаж действующей модели.'))
        context = dict(strategy='ДДУ', reference=str(x.get(prefix + '_sales_start') or '')[:7], note=note)
        if parking_obj and parking_obj.garage_sellable:
            split(_parking(x, t, parking_obj), quantity_series, revenue_series)
        else:
            field = obj.rate_price if obj else ''
            add(dict(key=key, label=p['label'], quantity=p.get('quantity'), unit=p['unit'],
                     base_price=(p.get('start_price_th', 0.0) * 1000 if not obj or x.get(field) is not None else None),
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
        if item['strategy'] == 'direct':
            components = [dict(key=key, label=item['title'], quantity=book.get('area_sqm'),
                               unit='шт.' if obj.measure == 'spaces' else 'м²', base_price=book.get('price_rub_sqm') if x.get(obj.rate_price) is not None else None, origin=_origin(x, obj.rate_price))]
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
                         + _origin(x, obj.prefix + '_growth_pre_pct'))
        else:
            # Cash rent and transaction exit are separate from residual valuation.
            rent_rows = [dict(month=r['month'][:7], revenue=r.get('rent_revenue', 0.0),
                              occupancy=r.get('occupancy')) for r in rows if r.get('occupancy') is not None]
            rent = item['totals'].get('rent_revenue')
            result.append(dict(key=key+':rent', label=item['title']+' — аренда (включая сдаваемые места)',
                               unit='м² и машино-места', quantity=None, revenue=rent, strategy='Аренда',
                               rows=rent_rows, note='Расчётное заполнение и аренда; ставки и индексация — в стратегии объекта.'))
            if item.get('exit_mode') != 'hold':
                exit_date = (item.get('kpi') or {}).get('exit_month')
                value = item['totals'].get('exit_revenue')
                if exit_date is not None:
                    add(dict(key=key+':exit', label=item['title']+' — продажа объекта при выходе',
                             quantity=1.0, unit='объект', base_price=value,
                             origin='Допущение модели: капитализация NOI следующих 12 месяцев; ставка капитализации — вводные объекта.'),
                        {exit_date: 1.0}, {exit_date: value}, strategy='Выход', reference=exit_date[:7],
                        note='Расчётная продажа целого объекта по капитализации NOI, не цена продажи м². '
                             'Цена определяется на дату выхода, отдельная исходная цена продажи не задаётся.')
                else:
                    warnings.append(item['title']+' — нет даты выхода; продажа объекта не раскрыта по месяцам.')
    cash = sum(p['revenue'] for p in result if p.get('revenue') is not None)
    valuation = sum((o.get('totals') or {}).get('residual_value', 0.0) for o in nonres.values())
    expected = fin.get('total_revenue')
    for p in result:
        p['share'] = p['revenue'] / cash if cash and p.get('revenue') is not None else None
    gap = None if expected is None else expected - cash - valuation
    if gap is not None and abs(gap) > 1.0:
        warnings.append(f'Раскрытие продуктов не сходится с итогом модели: разница {gap:,.2f} ₽.')
    return dict(products=result, cash_revenue=cash, valuation=valuation, model_revenue=expected,
                reconciliation_gap=gap, warnings=warnings)


def combine(results: list[dict], expected: float) -> dict:
    products, warnings = [], []
    valuation = 0.0
    for index, r in enumerate(results, 1):
        data = (r.get('report') or {}).get('office_results') or {}
        valuation += data.get('valuation', 0.0)
        warnings.extend(data.get('warnings') or [])
        for p in data.get('products') or []:
            products.append({**p, 'key': f"phase{index}:{p['key']}",
                             'label': f"Очередь {index} — {p['label']}"})
    cash = sum(p['revenue'] for p in products)
    for p in products:
        p['share'] = p['revenue'] / cash if cash else None
    gap = expected - cash - valuation
    if abs(gap) > 1:
        warnings.append(f'Раскрытие очередей не сходится с итогом: {gap:,.2f} ₽.')
    return dict(products=products, cash_revenue=cash, valuation=valuation, model_revenue=expected,
                reconciliation_gap=gap, warnings=warnings)


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
    rows.append(dict(label='Расхождение с итогом модели (деньги + оценка), ₽',value=(0.0 if data.get('reconciliation_gap') is not None and abs(data['reconciliation_gap'])<.01 else data.get('reconciliation_gap')),unit='num'))
    income.append(dict(title='Сверка выручки', rows=rows))
    for p in products:
        periods = p.get('rows') or []
        if not periods:
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


WORKBOOK_DISCLOSURE_SHEET = 'Раскрытие результатов'


def add_workbook_sheet(wb: Any, result: dict) -> None:
    """Supplemental export snapshot. Never overwrites formula model sheets.

    This sheet describes the exported run, so its limitation is printed at
    the top and repeated in the footer. Editable calculations remain on the
    original model sheets; no existing formula or defined name is relocated.
    """
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.pagebreak import Break
    data = (result.get('report') or {}).get('office_results')
    if not data:
        return
    ws = wb.create_sheet(WORKBOOK_DISCLOSURE_SHEET)
    ws.append(['Раскрытие результатов — снимок экспортированного расчёта'])
    ws.merge_cells('A1:H1')
    ws.append(['С НДС. При изменении вводных в Excel этот справочный лист не обновляется. '
               'Пересчитываемая модель — на расчётных листах книги; для нового раскрытия повторите экспорт.'])
    ws.merge_cells('A2:H2')
    ws.row_dimensions[2].height = 42
    ws.append(['Прочерк — показатель отсутствует/неприменим к потоку; действительный ноль сохранён числом.'])
    ws.merge_cells('A3:H3')
    income, sales, assumptions = blocks(data)
    sections = [('Продукты и выручка', income), ('Цены и темпы продаж', sales)]
    costs = next((s for s in ((result.get('report') or {}).get('object_report') or {}).get('sections') or []
                  if s['key'] == 'costs'), {})
    sections += [('Структура затрат', [b for b in costs.get('blocks') or [] if b.get('kind') == 'expense_structure']),
                 ('Допущения и ограничения', assumptions)]
    for title, group in sections:
        ws.append([title]); row = ws.max_row
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        ws.cell(row, 1).font = Font(name='Calibri', size=13, bold=True, color='FFFFFF')
        ws.cell(row, 1).fill = PatternFill('solid', fgColor='2B6475')
        for block in group:
            if block.get('kind') == 'monthly_plan' and ws.max_row > 12:
                ws.row_breaks.append(Break(id=ws.max_row))
            ws.append([block['title']]); ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
            if block.get('note'):
                ws.append([block['note']]); note_row = ws.max_row
                ws.merge_cells(start_row=note_row,start_column=1,end_row=note_row,end_column=8)
                ws.row_dimensions[note_row].height=42
            columns = block.get('columns') or [['label','Показатель','text'],['value','Значение','text']]
            ws.append([c[1] for c in columns]); head = ws.max_row
            for cell in ws[head]:
                cell.font=Font(bold=True)
                cell.fill=PatternFill('solid',fgColor='E8EFF1')
            records = block.get('years') if 'years' in block else block.get('rows') or []
            for record in records:
                if 'years' in block:
                    ws.append([record.get(c[0]) if record.get(c[0]) is not None else '—' for c in columns])
                    for i,c in enumerate(columns,1):
                        ws.cell(ws.max_row,i).number_format = '0.0%' if c[2]=='pct' else '#,##0.00' if c[2]!='text' else 'General'
                else:
                    ws.append([record.get('label'), record.get('value') if record.get('value') is not None else '—'])
                    ws.cell(ws.max_row,2).number_format='0.0%' if record.get('unit')=='pct' else '#,##0.00' if record.get('unit') in ('rub','num','count','sqm') else 'General'
            end = ws.max_row
            if block.get('kind') in ('expense_structure','monthly_plan') and end>head:
                plot=BarChart() if block['kind']=='expense_structure' else LineChart()
                plot.title=block['title']; plot.y_axis.title='₽' if block['kind']=='expense_structure' else 'Объём; единица в заголовках'
                plot.height=7; plot.width=20
                # Expense total is not a second cost category. Monthly plot
                # deliberately excludes price and money from volume units.
                last=end-1 if block['kind']=='expense_structure' else end
                indices=[2] if block['kind']=='expense_structure' else ([2,3,4] if len(columns)==6 else [])
                for i in indices:
                    plot.add_data(Reference(ws,min_col=i,max_col=i,min_row=head,max_row=last),titles_from_data=True)
                if indices:
                    plot.set_categories(Reference(ws,min_col=1,min_row=head+1,max_row=last))
                    ws.add_chart(plot,f'A{end+2}')
                    for _ in range(16): ws.append([''])
            ws.append([''])
    for row in ws:
        for cell in row:
            cell.alignment=Alignment(vertical='top',wrap_text=True)
            if not cell.font.name:
                cell.font=Font(name='Calibri',size=10)
    for col,width in zip('ABCDEFGH',[43,23,14,22,22,22,24,16]):
        ws.column_dimensions[col].width=width
    ws.freeze_panes='B5'
    ws.sheet_view.showGridLines=False
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.orientation='landscape'
    ws.page_setup.paperSize=ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth=1; ws.page_setup.fitToHeight=0
    ws.print_title_rows='1:3'
    ws.print_area=f'A1:H{ws.max_row}'
    ws.oddFooter.center.text='Снимок расчёта при экспорте; повторный расчёт — на листах модели'
