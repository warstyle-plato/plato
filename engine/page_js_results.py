"""Кусок страницы PAGE: Скрипт: «Результаты» — renderResult, графики (Гант, темп продаж,
эскроу, финансирование), чувствительность и торнадо.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_results")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""function renderResult(){
 if(!lastResult)return;const r=lastResult,f=r.finance;
 renderObjectParkingNote();
 // Подпись под ставкой благоустройства зовётся и формой, и результатом:
 // написанная объяснять молчание, она молчала бы ровно до первого расчёта.
 // Место — здесь, а не внутри подписи паркинга: к паркингу она отношения не
 // имеет, а чужая связь ломает стенды, перечисляющие куски руками.
 renderLandscapingRateNote();
 hideCalcLocked();
 if(typeof feedbackCalcs!=='undefined'){feedbackCalcs+=1;feedbackMaybeAsk()}

 // Числа берутся из результата, а не из формы: форма не знает ни о льготе по
 // ВРИ, ни о доле очереди. Объявление стоит выше плиток, потому что цена
 // приобретения нужна уже им.
 const expenseGroup=label=>{
  const found=(r.report.expense_structure||[]).find(g=>g.label===label);
  return found?Number(found.value||0):0;
 };

 // Оговорка у чисел, зависящих от послед-дефолтного потока. Решение о том,
 // был ли дефолт, — не своё: то же, что у плашки (modelDefaultInfo).
 const modelDefault=modelDefaultInfo(r);
 const note=text=>`<i style="display:block;font-weight:400;font-size:11px;opacity:.75">`
  +`${text}</i>`;
 // Полная оговорка стоит один раз, у прибыли; маржинальность и NPV — та же
 // величина в другом виде, и повторять им фразу целиком значит превратить её
 // в фон, который перестают читать.
 const conditionalNote=modelDefault
  ?note(`условная: в модели дефолт`
   +`${modelDefault.name?' на '+escapeHtml(modelDefault.name):''}`
   +`${modelDefault.when?' в '+modelDefault.when:''}`)
  :'';
 const conditionalShort=modelDefault?note('при том же допущении'):'';

 const reportKpis=[
  ['Выручка',money(r.summary.revenue)],
  // Вторая половина уравнения. В PDF ключевая экономика идёт «Выручка →
  // Расходы всего → EBITDA», на экране расходов не было вовсе — и EBITDA
  // появлялась из ниоткуда, сравнить её было не с чем.
  ['Расходы всего',money(r.summary.total_expenses)],
  ['EBITDA',money(r.summary.ebitda)],
  // Прибыль, маржинальность и NPV после дефолта посчитаны на допущении, что
  // банк дал проекту продолжиться: это одна и та же величина в трёх видах.
  // Голое число читается как достигнутое — оговорка стоит у самого числа, а
  // не только в плашке выше: плашку можно пролистать, плитку нет.
  ['Чистая прибыль',money(r.summary.net_profit)+conditionalNote],
  ['Маржинальность',pct(r.summary.margin)+conditionalShort],
  ['NPV @'+Number(inputs.discount_rate_pct||20).toLocaleString('ru-RU')+'%',returnsNa(r.summary)||(money(r.summary.npv)+conditionalShort)],
  // Цена входа стояла только в «Параметрах проекта» ниже и в PDF первой
  // строкой ключевой экономики: экран и отчёт расходились по составу, а
  // главное число сделки в шапку не попадало вовсе.
  // Цена не задана — это «не задана», а не «0 млрд ₽»: карточка решения выше
  // говорит «не задана», и плитка рядом с нулём ей противоречила (ревизия
  // интерфейса, S17). Правило то же, что у карточки: цена больше нуля.
  // Итог сделки: цена участка вместе с выкупом ЗУ/ОКС у третьих лиц. Две
  // строки разбивки стоят в «Параметрах проекта» ниже — шапка остаётся в
  // десять плиток.
  ['Цена приобретения',(v=>v>0?money(v):'не задана')(expenseGroup('Цена приобретения'))],
  // Чем оплачен вход: свои деньги и пик банковского долга до ПФ. Прежде здесь
  // стояли оба БРИДЖа сразу — лимит банка и фактическая потребность, — и рядом
  // они читались как расхождение, а не как разные величины. Остался один,
  // фактический: он отвечает на вопрос «сколько денег нужно». Расчётный лимит и
  // пиковая непокрытая задолженность — величины для разговора с банком, они в
  // таблице «Финансирование» ниже, среди ставок и лимитов.
  ['Собственные средства до ПФ',money(r.report.financing.own_funds)],
  ['Пиковый БРИДЖ',money(r.report.financing.actual_bridge)],
  ['LLCR (расчётный)',mult(r.summary.llcr)]
 ];
 // Нежилой проект без ДДУ: БРИДЖа, ПФ и LLCR у него нет — шапку
 // заканчивают деньги объектов (`report.layout`, решение движка).
 const layout=reportLayout(r);
 if(!layout.project_finance)reportKpis.splice(-3,3);
 (layout.nonres_tiles||[]).forEach(t=>reportKpis.push([t.label,nonresCell(t)]));
 reportKpi.innerHTML=reportKpis.map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');
 applyReportLayout(layout);
 renderObjectReport(r);

 const rveWarning=document.getElementById('pfRveWarning');
 if(rveWarning){
  const html=pfRveWarningHtml(r);
  if(html){rveWarning.style.display='block';rveWarning.innerHTML=html}
  else{rveWarning.style.display='none';rveWarning.textContent=''}
 }

 llcrValue.textContent=mult(r.summary.llcr);
 financeKpi.innerHTML=[
  ['Пиковый БРИДЖ',money(f.peak_bridge)],
  ['Пиковая (непокрытая эскроу) задолженность ПФ',money(f.peak_uncovered_pf)],
  ['Остаток ПФ после раскрытия эскроу в РВЭ',money(f.rve_pf_shortfall)],
  ['Ставка БРИДЖ на текущей ключевой',pct(f.current_bridge_rate)],
  ['Средневзвешенная ставка БРИДЖ за период',pct(f.avg_bridge_rate)],
  ['Средняя ставка ПФ без эффекта эскроу',pct(f.avg_pf_base_rate)],
  ['Средняя фактическая ставка ПФ с учётом эскроу',pct(f.avg_pf_effective_rate)],
  ['Проценты и комиссии',money(f.financing_cost)],
  ['Лимит ПФ',money(f.pf_limit)],
  ['Остаток ПФ',money(f.ending_pf)]
 ].map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');

 bridgeTable.innerHTML=
  row('Расчётный лимит',money(f.calculated_bridge_limit))+
  row('Фактическая выборка',money(f.bridge_draw_total))+
  row('Пиковый остаток',money(f.peak_bridge))+
  row('Текущая ключевая ставка',pct(f.current_key_rate))+
  row('Спред БРИДЖ',pct(f.bridge_spread))+
  row('Ставка БРИДЖ на текущей ключевой',pct(f.current_bridge_rate))+
  row('Ставка БРИДЖ на старте проекта',pct(f.bridge_rate_at_project_start))+
  row('Средняя ключевая за период БРИДЖ',pct(f.avg_bridge_key_rate))+
  row('Средневзвешенная ставка БРИДЖ за период',pct(f.avg_bridge_rate))+
  row('Начисленные проценты',money(f.bridge_interest))+
  row('Капитализация процентов',money(f.bridge_capitalization))+
  row('Перенесено в ПФ',money(f.transferred_bridge_interest));

 pfTable.innerHTML=
  row('Лимит ПФ',money(f.pf_limit))+
  row('Совокупная выборка',money(f.pf_draw_total))+
  row('Пиковый остаток',money(f.peak_pf))+
  row('Погашено основного долга',money(f.pf_repayment_total))+
  row('Остаток после раскрытия эскроу в РВЭ',money(f.rve_pf_shortfall))+
  row('Остаток',money(f.ending_pf))+
  row('Средняя ключевая ставка в период ПФ',pct(f.avg_pf_key_rate))+
  row('Средняя ставка ПФ без эффекта эскроу',pct(f.avg_pf_base_rate))+
  row('Ставка ПФ при покрытии эскроу 1×',pct(f.pf_special_rate))+
  pfStepRows(f)+
  row('Средняя фактическая ставка ПФ с учётом эскроу',pct(f.avg_pf_effective_rate));

 interestTable.innerHTML=
  row('Проценты БРИДЖ',money(f.bridge_interest))+
  row('Капитализация БРИДЖ',money(f.bridge_capitalization))+
  row('Комиссия БРИДЖ',money(f.bridge_fee))+
  row('Проценты ПФ',money(f.pf_interest))+
  row('Капитализация процентов ПФ',money(f.pf_interest_capitalization))+
  row('Плата за невыбранный лимит',money(f.pf_limit_fee))+
  row('Комиссия за резервирование ПФ',money(f.pf_reservation_fee))+
  `<tr><th>Итого проценты и комиссии</th><th>${money(f.financing_cost)}</th></tr>`;

 llcrTable.innerHTML=
  row('Поступления проекта',money(f.total_revenue))+
  row('Коммерческие расходы',`(${money(f.commercial_costs)})`)+
  row('Налог на прибыль',`(${money(f.profit_tax)})`)+
  // НДС — денежный расход, движок вычитает его из числителя. Без строки
  // столбец не сходился к итогу, и покрытие выглядело необъяснимо ниже.
  row('НДС',`(${money(f.vat||0)})`)+
  row('Инвестиционные расходы',`(${money(f.total_capex)})`)+
  row('Поступление ПФ',money(f.pf_draw_total))+
  `<tr><th>Числитель LLCR</th><th>${money(f.llcr_numerator)}</th></tr>`+
  row('Основной долг ПФ',money(f.pf_draw_total))+
  // Принятый долг предыдущей очереди стоит в знаменателе, но своей строки не
  // имел: видимые строки не складывались в показанный итог, и покрытие
  // выглядело заниженным без причины.
  (Number(f.carried_debt_in||0)>0.5e6?row('Принятый долг предыдущей очереди',money(f.carried_debt_in)):'')+
  row('Проценты и комиссии',money(f.reported_interest_and_fees))+
 row('Корректировка переноса процентов БРИДЖ',`(${money(f.transferred_bridge_interest)})`)+
  `<tr><th>Знаменатель LLCR</th><th>${money(f.llcr_denominator)}</th></tr>`+
  `<tr><th>LLCR</th><th>${mult(f.llcr)}</th></tr>`;

 const taxMargins=f.tax_margin_by_product||{};
 // В рамке объекта нет жилого ядра: «Маржа основных продуктов» и строки
 // объектов, которых в проекте нет, были там нулями (у гостиницы — офис и ТЦ).
 const taxFrame=reportLayout(r).object_frame;
 const taxMarkup=
  // Ядро без жилья — общие затраты вне объектов: так и подписано.
  (taxFrame&&Math.abs(Number(taxMargins.core||0))<=0.5?''
   :row(taxFrame?'Маржа вне объектов (общие затраты)':'Маржа основных продуктов',money(taxMargins.core||0)))+
  taxMarginRows(taxMargins,row,taxFrame)+
  row('Вычет: проценты и банковские комиссии',`(${money(f.financing_tax_deductions||f.financing_cost||0)})`)+
  `<tr><th>Итоговая прибыль до налога</th><th>${money(f.profit_before_tax)}</th></tr>`+
  // НДС из базы налога на прибыль движок вычитает помесячно: он не доход, а
  // транзит в бюджет. Показываем его отдельной строкой рядом с налогом —
  // раньше платёж на миллиард не был виден в отчёте вовсе.
  row('Вычет из базы: НДС к уплате',`(${money(f.vat||0)})`)+
  `<tr><th>Налог на прибыль</th><th>${money(f.profit_tax)}</th></tr>`+
  `<tr><th>НДС к уплате</th><th>${money(f.vat||0)}</th></tr>`+
  `<tr><th>Итого налоги</th><th>${money((f.profit_tax||0)+(f.vat||0))}</th></tr>`;
 taxTable.innerHTML=taxMarkup;
 reportTaxTable.innerHTML=taxMarkup;

 renderFinanceChart(f.rows,((r.report||{}).financing||{}).escrow_cover||{});
 monthlyFinance.innerHTML=f.rows.filter((_,i)=>i%1===0).map(x=>`<tr>
  <td>${x.month.slice(0,7)}</td><td>${pct(x.key_rate)}</td><td class="money">${mln(x.bridge_balance)}</td><td>${pct(x.bridge_rate)}</td><td>${mln(x.bridge_interest+x.bridge_capitalization)}</td>
  <td class="money">${mln(x.pf_balance)}</td><td class="money">${mln(x.pf_payable||0)}</td><td class="money">${mln(x.escrow)}</td><td>${mult(x.coverage)}</td><td>${pct(x.pf_rate)}</td><td>${mln(x.pf_interest+x.pf_interest_capitalization)}</td><td>${mln(x.limit_fee)}</td><td>${mln(x.pf_repayment)}</td><td>${mln(x.profit_tax||0)}</td>
 </tr>`).join('');

 economicsTable.innerHTML=
  row('Выручка',money(r.summary.revenue))+
  row('CAPEX проекта',`(${money(r.summary.capex)})`)+
  row('Маркетинг и продажи',`(${money(r.summary.commercial_costs)})`)+
  (Number((r.finance||{}).nonres_costs||0)>0?row(((r.report||{}).nonres_costs_label||'Расходы объектов вне ДДУ'),`(${money(r.finance.nonres_costs)})`):'')+
  `<tr><th>EBITDA</th><th>${money(r.summary.ebitda)}</th></tr>`+
  row('Проценты и комиссии',`(${money(r.summary.financing_cost)})`)+
  `<tr><th>Прибыль до налога</th><th>${money(r.summary.profit_before_tax)}</th></tr>`+
  // Без строки НДС экономика не сходилась: прибыль до налога минус налог
  // давала не чистую прибыль, и разницу человеку было негде найти. НДС стоит
  // ПЕРЕД налогом на прибыль — в том порядке, в каком его вычитает база налога
  // (блок «Налоговая база»): стоя после, он читался платой из чистой прибыли
  // (ревизия интерфейса, S33). Числа те же, меняется только порядок строк.
  row('НДС к уплате',`(${money(r.summary.vat||0)})`)+
  row('Налог на прибыль',`(${money(r.summary.profit_tax)})`)+
  `<tr><th>Чистая прибыль</th><th>${money(r.summary.net_profit)}</th></tr>`+
  row('Маржинальность',pct(r.summary.margin))+
  row('NPV',returnsNa(r.summary)||money(r.summary.npv))+
  row('IRR equity',returnsNa(r.summary)||irrFmt(r.summary.irr_equity));

 // Числа карточки — из результата, а не из формы. Форма не знает ни о льготе,
 // ни о доле очереди: при стопроцентной льготе строка показывала полную плату
 // за ВРИ, которой проект не платит, а в разрезе очереди — цену покупки и плату
 // всего проекта рядом с расходами одной очереди. Соседние строки давно берутся
 // из расчёта, и эти две выбивались из общего правила. Сам `expenseGroup`
 // объявлен в начале функции — тем же значением живёт плитка цены входа.
 const vriRelief=Number(((r.vri||{}).totals||{}).relief||0);
 // Класс решает движок (`report.project_class`): у гостиницы — звёздность, а
 // не класс жилья. Строки метра продаваемой площади и цены квартир у неё
 // встали бы нулями, которые читались бы ответом, — вместо них номера,
 // затраты на номер и ADR из итога гостиницы.
 const pc=(r.report||{}).project_class||{};
 const hotelProject=pc.kind==='hotel';
 const hk=(((r.finance||{}).hotel||{}).kpi)||{};
 projectParamsTable.innerHTML=
  (r.summary.phase_count?row('Очередность',r.summary.phase_count+' очереди'):'')+
  row(escapeHtml(pc.title||'Класс проекта'),escapeHtml(pc.label||'—'))+
  row('Сценарий',scenarioSelect.options[scenarioSelect.selectedIndex].text)+
  row('Доходы к базовому сценарию',Number(r.summary.scenario_revenue_multiplier||1).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x')+
  row('Расходы к базовому сценарию',Number(r.summary.scenario_cost_multiplier||1).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x')+
  row('Стоимость покупки',money(expenseGroup('Цена приобретения')))+
  ((r.deal&&Number(r.deal.buyout_mln)>0)
   ?row('в т.ч. цена участка / права',money(Number(r.deal.price_mln)*1e6))
    +row('в т.ч. выкуп ЗУ/ОКС у третьих лиц (кадастровая стоимость, не цена сделки)',money(Number(r.deal.buyout_mln)*1e6)):'')+
  row('Стоимость смены ВРИ / права',money(Number(r.capex.land_rights||0))
   +(vriRelief>0?' <span style="color:#777;font-weight:400">льгота '+money(vriRelief)+'</span>':''))+
  (hotelProject?'':row(r.summary.social_payment_mode==='Строительство'?'Строительство соцобъектов':'Социальная компенсация',socialMoney(r.summary.social_payment)))+
  row('Проектирование П и РД',money((r.capex.design_p||0)+(r.capex.design_rd||0)))+
  (hotelProject
   ?row('Номерной фонд',hotelCell({value:hk.keys,unit:'count'}))+
    row('Затраты на номер с НДС',hotelCell({value:hk.capex_per_key,unit:'rub_unit'}))+
    row('ADR первого года, без НДС',hotelCell({value:hk.adr_first_year,unit:'rub_unit'}))
   :row('Продаваемая площадь',num(r.summary.monetizable_saleable_sqm)+' м²')+
  // Удельный показатель подписывается тем делителем, на который число
  // делится: это выручка квартир ÷ ПРОДАВАЕМАЯ ПЛОЩАДЬ квартир, то есть
  // тыс. ₽ за метр. Единицы не было вовсе, и «916,6 тыс. ₽» читались как цена
  // квартиры — тем более что строкой ниже, в блоке продаж квартир, стоит
  // «Средняя цена квартиры» в рублях ЗА КВАРТИРУ, и два названия отличались
  // одной буквой. Соседние строки этого же блока подписаны «/м² прод.» —
  // теперь и эта.
  row('Средняя цена м² квартир',th(r.summary.average_apartment_price_th)+'/м² прод.')+
  // Каждый удельный — на свою базу (решение 4 ревизии книги): расходы — на
  // суммарную площадь в ГНС и для сравнения с ценой на продаваемую; EBITDA и
  // прибыль — на продаваемую. Подписи баз — из словаря терминов.
  row('Полная себестоимость',th(r.summary.full_cost_per_saleable_th)+'/м² прод. · '+th(r.summary.full_cost_per_total_area_th)+'/м² '+TERMS.total_area.genitive)+
  row('Строительная себестоимость',th(r.summary.construction_cost_per_saleable_th)+'/м² прод. · '+th(r.summary.construction_cost_per_gns_th)+'/м² '+TERMS.core_total_area.genitive)+
  row('EBITDA на метр',th(r.summary.ebitda_per_saleable_th)+'/м² прод.')+
  row('Чистая прибыль на метр',th(r.summary.net_profit_per_saleable_th)+'/м² прод.'));

 // Свод финансирования на многоочередном проекте — это итоги, а не моменты:
 // подписи «в РВЭ» и «от предыдущей очереди» там называют событием сумму по
 // очередям. Само деление на очереди берётся оттуда же, откуда его берут все
 // остальные блоки страницы.
 const phased=!!(phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1);
 // График платежей за покупку — как посчитано движком: даты, суммы, доли.
 // Одна строка в дату сделки — прежнее поведение, и её не печатаем.
 const purchase=r.report.purchase||{};
 const purchaseRows=(purchase.rows||[]);
 const purchaseLine=(purchase.custom||(purchase.warnings||[]).length)
  ?row('График платежей за покупку',purchaseRows.map(x=>dateRu(x.date)+' — '+money(x.amount_mln*1e6)+' ('+pct(x.share)+')').join('<br>')
     +((purchase.warnings||[]).length?'<div class="cell-sub" style="color:#A35D00">'+purchase.warnings.map(escapeHtml).join('; ')+'</div>':''))
  :'';
 reportFinanceTable.innerHTML=
  purchaseLine+
  row(r.summary.phase_count>1?'Расчётный БРИДЖ — сумма лимитов очередей':'Расчётный БРИДЖ',money(r.report.financing.calculated_bridge))+
  row(r.summary.phase_count>1?'Пик одновременно открытых линий БРИДЖа очередей':'Фактический / пиковый БРИДЖ',money(r.report.financing.actual_bridge))+
  // Не из банка: собственные деньги, заём учредителя, перехваченный чужой долг.
  (Number(r.report.financing.own_funds||0)>0.5?row('Собственные средства до ПФ',money(r.report.financing.own_funds)+' <span style="color:#777;font-weight:400">без процентов</span>'):'')+
  row(phased?'Лимит ПФ — сумма по очередям':'Лимит ПФ',money(r.report.financing.pf_limit))+
  // Общий лимит по генеральным условиям — ожидание на все очереди, а не
  // потолок: НКЛ каждой считается заново при её открытии (владелец, 20.09.2026).
  (phased&&Number(r.report.financing.pf_limit_general||0)>500000?row('Общий лимит ПФ по генеральным условиям',money(r.report.financing.pf_limit_general)+' <span style="color:#777;font-weight:400">ожидание, потолком очередей не служит</span>'):'')+
  row('Пиковый ПФ',money(r.report.financing.pf_peak))+
  // Ушла из плиток шапки: для общей оценки проекта величина неочевидная, а
  // здесь, среди лимитов и ставок, читается тем, чем является.
  row('Пиковая (непокрытая эскроу) задолженность ПФ',money(r.report.financing.pf_uncovered_peak))+
  // Раскрытие эскроу — событие очереди, и у каждой оно своё. Подписи «в РВЭ»
  // на многоочередном проекте называли моментом сумму разнесённых во времени
  // событий: «раскрытый эскроу в РВЭ — какое из них?» (владелец, 31.08.2026).
  // Величины те же, но названы итогами, а по очередям они стоят в таблице
  // сравнения — с датой РВЭ у каждой.
  row(phased?'Долг ПФ перед раскрытием — всего':'Долг ПФ перед раскрытием в РВЭ',
      money(r.report.financing.rve_pf_before_repayment))+
  row(phased?'Раскрыто эскроу за проект':'Раскрытый эскроу в РВЭ',
      money(r.report.financing.rve_escrow_release))+
  // Раскрытое и погашенное — разные величины: эскроу гасит СВОЙ ПФ, излишек
  // уходит в кассу. Без этой строки три числа рядом не вычитаются.
  row('Из него на погашение ПФ',money(r.report.financing.rve_pf_repayment))+
  row(phased?'Не покрыто эскроу при раскрытии — всего':'Остаток ПФ после раскрытия в РВЭ',
      money(r.report.financing.rve_pf_shortfall))+
  // Плашка выше говорит «остаток гасится последующими продажами», а число,
  // отвечающее «погасился ли», стояло только в PDF и в книге. На экране его
  // не было вовсе, и проверить обещание было нечем (владелец, 25.08.2026).
  // Порядок: сколько пришло, сколько ушло, что осталось. Остаток последним —
  // он вывод, а не одно из трёх чисел; стоя первым, он читался как
  // противоречие строке «передано» с тем же числом.
  // «в т.ч. принято от предыдущей очереди» в своде — сумма приёмов, и при трёх
  // очередях «предыдущая» не отвечает ни на что. Кто у кого принял и когда —
  // в таблице сравнения; здесь остаётся итог переоформленного за проект.
  (Number(r.report.financing.debt_carried_out||0)>0.5e6
   ?row(phased?'Переоформлено между очередями, всего':'Долг передан в ПФ следующей очереди',
        money(r.report.financing.debt_carried_out)):'')+
  (!phased&&Number(r.report.financing.carried_debt_in||0)>0.5e6
   ?row('в т.ч. принято от предыдущей очереди',money(r.report.financing.carried_debt_in)):'')+
  row((Number(r.report.financing.debt_carried_out||0)>0.5e6
       ?'Осталось непогашенным на очереди'
       :'Непогашенный долг ПФ на конец проекта')
      +(Number(r.report.financing.ending_pf||0)>0?' · дефолт':''),
      money(r.report.financing.ending_pf))+
  (r.report.financing.peak_total_debt!=null?row('Максимальный совокупный долг',money(r.report.financing.peak_total_debt)):'')+
  // Ставки — в соседней карточке «Ставки и долговая нагрузка»: десять строк
  // стояли в обеих карточках рядом, одними словами и одними числами (ревизия
  // интерфейса, S7). Здесь — лимиты, пики и итог долга; там — только ставки.
  row('Проценты и комиссии',money(r.report.financing.interest_and_fees))+
  `<tr><th>LLCR</th><th>${mult(r.summary.llcr)}</th></tr>`;

 const sb=r.summary.social_payment_breakdown||{};
 const socialMode=r.summary.social_payment_mode||'—';
 // Расчётная потребность города: за неё платят, её же строят. При компенсации
 // в проекте не оставалось ни одного числа о социалке, кроме суммы, — платим
 // за 250 мест, а числа 250 нет нигде (владелец, 02.09.2026). Считает движок,
 // здесь только показ: второй счёт разошёлся бы с первым молча.
 const socialNeedRow=(()=>{
  const need=r.summary.social_required||{};
  if(!need.available)return `<tr><td colspan="2" style="color:#777;font-size:11px">Расчётная потребность города не определена: ${escapeHtml(need.basis||'источника нет')}.</td></tr>`;
  const gap=need.gap||{};
  const parts=[['ДОО','kindergarten_places','мест'],['СОШ','school_places','мест'],
               ['Поликлиника','clinic_capacity','пос./смену']]
   .filter(([,key])=>Number(need[key]||0)>0)
   .map(([label,key,unit])=>`${label} ${num(need[key]||0)} ${unit}`
     +(Number(gap[key]||0)>0?` (из них не строим ${num(gap[key])})`:''));
  if(!parts.length)return '';
  return `<tr><td colspan="2" style="color:#777;font-size:11px">Расчётная потребность города — ${parts.join(', ')}. Основание: ${escapeHtml(need.basis||'')}. Метры соцобъектов, которые строит город, в ГНС проекта не входят.</td></tr>`;
 })();
 const construction=sb.construction||{};
 const compensation=sb.compensation||{};
 const program=r.summary.social_program||{};
 // Денежная часть при совмещённом режиме — то, что осталось от общего
 // платежа за вычетом строек. Считается вычитанием, а не берётся из вводных:
 // так итог таблицы сходится с моделью при любом источнике компенсации.
 const socialBuilt=Number(construction.kindergarten_mln||0)+Number(construction.school_mln||0)
   +Number(construction.clinic_mln||0);
 const socialCash=Math.max(0,Number(r.summary.social_payment||0)-socialBuilt*1e6);
 if(socialMode==='Строительство и компенсация'){
   // Третьего режима у таблицы не было: строки шли по ветке «денежная
   // компенсация», разбивка по объектам стояла нулями, а итог нёс и стройку
   // тоже — три нуля против 2,7 млрд (замечание владельца, 19.08.2026).
   socialTable.innerHTML=
    row('Режим','Строительство и компенсация')+
    row(`ДОО — ${num(program.kindergarten_places||0)} мест`,money(Number(construction.kindergarten_mln||0)*1e6))+
    row(`СОШ — ${num(program.school_places||0)} мест`,money(Number(construction.school_mln||0)*1e6))+
    row(`Поликлиника — ${num(program.clinic_capacity||0)} пос./смену`,money(Number(construction.clinic_mln||0)*1e6))+
    row('Стоимость строительства',money(socialBuilt*1e6))+
    row('Денежная компенсация',money(socialCash))+
    `<tr><th>Социальная нагрузка / всего</th><th>${socialMoney(r.summary.social_payment)}</th></tr>`+
    socialPerMetre(r)+socialNeedRow+
    ((Number(compensation.kindergarten_mln||0)+Number(compensation.school_mln||0)
      +Number(compensation.clinic_mln||0))>0
      ? `<tr><td colspan="2" style="color:#777;font-size:11px">Справочно, разбивка компенсации по ГлавАПУ: `
        +`ДОО ${money(Number(compensation.kindergarten_mln||0)*1e6)}, `
        +`СОШ ${money(Number(compensation.school_mln||0)*1e6)}, `
        +`поликлиника ${money(Number(compensation.clinic_mln||0)*1e6)}</td></tr>`
      : '');
 }else if(socialMode==='Строительство'){
   socialTable.innerHTML=
    row('Режим','Строительство')+
    row(`ДОО — ${num(program.kindergarten_places||0)} мест`,money(Number(construction.kindergarten_mln||0)*1e6))+
    row(`СОШ — ${num(program.school_places||0)} мест`,money(Number(construction.school_mln||0)*1e6))+
    row(`Поликлиника — ${num(program.clinic_capacity||0)} пос./смену`,money(Number(construction.clinic_mln||0)*1e6))+
    `<tr><th>Стоимость строительства / всего</th><th>${socialMoney(r.summary.social_payment)}</th></tr>`+
    socialPerMetre(r)+socialNeedRow+
    `<tr><td colspan="2" style="color:#777;font-size:11px">Справочно: компенсация по ГлавАПУ — ${money((Number(compensation.kindergarten_mln||0)+Number(compensation.school_mln||0)+Number(compensation.clinic_mln||0))*1e6)}</td></tr>`;
 }else{
   socialTable.innerHTML=
    row('Режим','Денежная компенсация')+
    row('ДОО — компенсация',money(Number(compensation.kindergarten_mln||0)*1e6))+
    row('СОШ — компенсация',money(Number(compensation.school_mln||0)*1e6))+
    row('Поликлиника — компенсация',money(Number(compensation.clinic_mln||0)*1e6))+
    `<tr><th>Компенсация / всего</th><th>${socialMoney(r.summary.social_payment)}</th></tr>`+
    socialPerMetre(r)+socialNeedRow;
 }

 // Расчётный лимит БРИДЖа — цифра ОДНОГО договора: покупка, денежная
 // соцкомпенсация и проектирование, под которые банк открывает линию до РнС.
 // У проекта с очередями таких договоров столько же, сколько очередей, и
 // открыты они в разные годы — сложенные в одну сумму, они дают лимит,
 // которого не выдавал никто («это глупость, а не расчётный бридж»,
 // владелец, 04.09.2026). То же правило, по которому пиковый БРИДЖ уже
 // разложен по очередям.
 // Состав считает движок: он же решает, что попадает в БРИДЖ — только то, что
 // платится ДО РнС. Вычитать «итог минус социалка минус П минус РД» на экране
 // значило бы завести второй ответ на тот же вопрос, и при рассрочке покупки
 // он разошёлся бы с первым.
 function bridgeUsesOf(res){
  const fin=(res.report||{}).financing||{};
  const parts=fin.calculated_bridge_parts||{};
  const uses=[
    ['Приобретение проекта',Number(parts.purchase||0)],
    ['Социальная компенсация',Number(parts.social||0)],
    ['Проектирование — стадия П',Number(parts.design_p||0)],
    ['Проектирование — стадия РД',Number(parts.design_rd||0)]
  ].filter(x=>x[1]>0.5);
  return {total:Number(fin.calculated_bridge||0),uses:uses};
 }
 const bridgeCalc=bridgeUsesOf(r);
 const bridgeTotal=bridgeCalc.total, bridgeUses=bridgeCalc.uses;
 const bridgeShare=value=>bridgeTotal>0?(value/bridgeTotal*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+'%':'—';
 function bridgeActualNoteText(queues){
  const base='Оплачено к месяцу пика. До открытия ПФ у очереди нет ни выручки, ни ПФ, поэтому остаток её БРИДЖа равен оплаченному. Разница с расчётным лимитом — расходы, под которые лимит не даётся.';
  if(!queues||!queues.on_bridge||!queues.on_bridge.length)return base;
  const parts=[];
  if(queues.refinanced&&queues.refinanced.length)parts.push(queues.refinanced.join(', ')+' к этому месяцу уже на ПФ — их расходы сюда не входят');
  if(queues.not_started&&queues.not_started.length)parts.push(queues.not_started.join(', ')+' ещё не начаты');
  return 'Пик свода — месяц, когда на БРИДЖе '+queues.on_bridge.join(', ')+(parts.length?'; '+parts.join('; '):'')+'. '+base;
 }
 const bridgePurposeEl=document.getElementById('bridgePurposeTable');
 const bridgeLimitPhases=(phaseBundle&&phaseBundle.phases&&phaseBundle.phases.length>1&&r===phaseBundle.consolidated)?phaseBundle.phases:null;
 const bridgePurposeTitle=document.getElementById('bridgePurposeTitle');
 const bridgePurposeNote=document.getElementById('bridgePurposeNote');
 if(bridgeLimitPhases){
  const blocks=bridgeLimitPhases.map(p=>{
   const calc=bridgeUsesOf(p.result||{});
   const share=value=>calc.total>0?(value/calc.total*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+'%':'—';
   const name=escapeHtml(p.name||'Очередь');
   if(!calc.uses.length)return `<tbody><tr><th colspan="3">${name} · лимит БРИДЖа не рассчитывается</th></tr></tbody>`;
   return `<tbody><tr><th colspan="3">${name}</th></tr>`
    +calc.uses.map(x=>`<tr><td>${x[0]}</td><td>${money(x[1])}</td><td>${share(x[1])}</td></tr>`).join('')
    +`<tr><th>Лимит БРИДЖа ${name}</th><th>${money(calc.total)}</th><th>${calc.total>0?'100,0%':'—'}</th></tr></tbody>`;
  }).join('');
  bridgePurposeEl.innerHTML=`<thead><tr><th>Цель</th><th>Сумма</th><th>Доля</th></tr></thead>`+blocks;
  if(bridgePurposeTitle)bridgePurposeTitle.textContent='Расчётный лимит БРИДЖа — по очередям';
  if(bridgePurposeNote)bridgePurposeNote.textContent='Лимит считает банк по каждому договору отдельно: у каждой очереди своя линия до открытия её ПФ. Сложенные вместе, лимиты дали бы договор, которого никто не выдавал, поэтому свода здесь нет. Смена ВРИ / земельные права, проценты и комиссии в расчётный лимит не входят.';
 }else{
  bridgePurposeEl.innerHTML=
    `<thead><tr><th>Цель</th><th>Сумма</th><th>Доля</th></tr></thead>`+
    `<tbody>${bridgeUses.map(x=>`<tr><td>${x[0]}</td><td>${money(x[1])}</td><td>${bridgeShare(x[1])}</td></tr>`).join('')}</tbody>`+
    `<tfoot><tr><th>Итого БРИДЖ</th><th>${money(bridgeTotal)}</th><th>${bridgeTotal>0?'100,0%':'—'}</th></tr></tfoot>`;
  if(bridgePurposeTitle)bridgePurposeTitle.textContent='Структура расчётного БРИДЖа';
  if(bridgePurposeNote)bridgePurposeNote.textContent='Смена ВРИ / земельные права, проценты и комиссии в расчётный лимит БРИДЖа не входят.';
 }

 // Фактический пик — по статьям, оплаченным к месяцу пика. Лимит методики и
 // реальная потребность расходятся всегда, и разница — это то, что банк
 // называет «остальное вашими»; до сих пор её приходилось считать глазами.
 // На своде очередей у каждой своя линия: пик свода приходится на месяц, когда
 // открыты не все, и подпись называет, чья линия в него вошла, а чья уже на ПФ.
 // У очередей БРИДЖ — свой у каждой, до открытия её ПФ; «пик свода» —
 // это одновременно открытые линии, и структура по нему отвечает не на тот
 // вопрос («что за пиковый бридж в проектах с очередностью», владелец,
 // 04.09.2026). На своде блок рисуется по очередям: у каждой свой месяц пика,
 // свой пик и свои статьи; свод стоит подписью, а не таблицей.
 const bridgeActual=(r.report.financing.actual_bridge_structure||[]);
 const bridgeActualTotal=Number(r.report.financing.actual_bridge||0);
 const bridgeActualEl=document.getElementById('bridgeActualTable');
 const bridgeShareCell=x=>`<td>${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</td>`;
 const bridgeRowsHtml=rows=>rows.map(x=>`<tr><td>${escapeHtml(x.label)}</td><td>${money(x.value)}</td>${bridgeShareCell(x)}</tr>`).join('');
 const bridgePhases=(phaseBundle&&phaseBundle.phases&&phaseBundle.phases.length>1&&r===phaseBundle.consolidated)?phaseBundle.phases:null;
 if(bridgeActualEl&&bridgePhases){
  const blocks=bridgePhases.map(p=>{
   const pf=((p.result||{}).report||{}).financing||{};
   const rows=pf.actual_bridge_structure||[], peak=Number(pf.actual_bridge||0), when=String(pf.actual_bridge_month||'');
   if(!rows.length)return `<tbody><tr><th colspan="3">${escapeHtml(p.name||'Очередь')} · БРИДЖ не привлекался</th></tr></tbody>`;
   return `<tbody><tr><th colspan="3">${escapeHtml(p.name||'Очередь')} · пик ${money(peak)}${when?' · '+dateRu(when):''}</th></tr>${bridgeRowsHtml(rows)}<tr><th>Пик БРИДЖа ${escapeHtml(p.name||'')}</th><th>${money(peak)}</th><th>100,0%</th></tr></tbody>`;
  }).join('');
  bridgeActualEl.innerHTML=`<thead><tr><th>Статья</th><th>Оплачено к пику очереди</th><th>Доля</th></tr></thead>`+blocks;
  const monthEl=document.getElementById('bridgeActualMonth');
  if(monthEl)monthEl.textContent=' · по очередям';
  const noteEl=document.getElementById('bridgeActualNote');
  const queues=r.report.financing.actual_bridge_queues||null;
  if(noteEl)noteEl.textContent='У каждой очереди свой БРИДЖ до открытия её ПФ; оплачено к месяцу пика этой очереди. '
   +(bridgeActualTotal>0?`Свод: наибольшая сумма одновременно открытых линий — ${money(bridgeActualTotal)}${r.report.financing.actual_bridge_month?' в '+dateRu(String(r.report.financing.actual_bridge_month)):''}${queues&&queues.on_bridge&&queues.on_bridge.length?' ('+queues.on_bridge.join(', ')+')':''}.`:'');
 }else if(bridgeActualEl){
  bridgeActualEl.innerHTML=bridgeActual.length?
   (`<thead><tr><th>Статья</th><th>Оплачено к пику</th><th>Доля</th></tr></thead>`
    +`<tbody>${bridgeRowsHtml(bridgeActual)}</tbody>`
    +`<tfoot><tr><th>Пик БРИДЖа</th><th>${money(bridgeActualTotal)}</th><th>${bridgeActualTotal>0?'100,0%':'—'}</th></tr></tfoot>`)
   :'';
  const monthEl=document.getElementById('bridgeActualMonth');
  const when=String(r.report.financing.actual_bridge_month||'');
  const queues=r.report.financing.actual_bridge_queues||null;
  if(monthEl)monthEl.textContent=(when?' · '+dateRu(when):'')+(queues&&queues.on_bridge&&queues.on_bridge.length?' · на БРИДЖе: '+queues.on_bridge.join(', '):'');
  const noteEl=document.getElementById('bridgeActualNote');
  if(noteEl)noteEl.textContent=bridgeActual.length
   ?bridgeActualNoteText(queues)
   :'БРИДЖ не привлекался.';
 }

 // Каждая строка — на свою базу, решённую движком (`base`), и подписана ею;
 // вторая колонка — на продаваемую, у строк с этой же базой не повторяется.
 unitEconomicsTable.innerHTML=(r.report.unit_economics||[]).map(x=>`<tr>
  <td>${x.label}</td>
  <td>${money(x.total)}</td>
  <td>${unitNum(x.per_base_th,1)}</td>
  <td>${unitBase(x)}</td>
  <td>${x.base==='saleable_area'?'—':unitNum(x.per_saleable_th,1)}</td>
 </tr>`).join('');

 renderVri(r.vri);

 const expenseRows=(r.report.expense_structure||[]);
 expenseStructureChart.innerHTML=expenseRows.map(x=>`<div class="expense-row">
   <div class="expense-label">${x.label}</div>
   <div class="expense-track"><div class="expense-fill" style="width:${Math.max(0,Math.min(100,Number(x.share||0)*100))}%"></div></div>
   <div class="expense-pct">${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</div>
   <div class="expense-value">${money(x.value)}</div>
 </div>`).join('');
 // Отдельно стоящий объект меряется СВОЕЙ площадью, а наземный паркинг —
 // своими местами: подстроки «в т.ч.» стоят под своей статьёй и несут числа,
 // посчитанные движком на их базы. Колонки самой статьи остаются проектными —
 // они складываются в итог таблицы, — и об этом сказано подписью под ней.
 expenseStructureTable.innerHTML=expenseRows.map(x=>{
   const head=`<tr>
   <td>${x.label}</td>
   <td>${money(x.value)}</td>
   <td>${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</td>
   <td>${unitNum(x.per_base_th,2)}</td>
   <td>${unitNum(x.per_saleable_th,2)}</td>
 </tr>`;
   // Строки объекта собраны движком (`standalone_expense_item_rates`): здание
   // на свою площадь, свой гараж на свои метры и места. База названа в самой
   // ячейке — в колонке проектной таблицы число без неё читалось проектным.
   const base=l=>l.basis?` <span class="muted">${l.basis}</span>`:'';
   const parts=(x.items||[]).flatMap(o=>o.lines||[]).map(l=>`<tr class="sub">
   <td style="padding-left:18px">в т.ч. ${l.label}</td>
   <td>${money(l.value)}</td>
   <td>—</td>
   <td>${l.gns_th==null?'—':num2(l.gns_th)+base(l)}</td>
   <td>${l.per_unit_mln!=null?num2(l.per_unit_mln)+' млн ₽/место':(l.saleable_th==null?'—':num2(l.saleable_th)+base(l))}</td>
 </tr>`).join('');
   const note=(x.items&&x.items.length&&x.items_note)
     ?`<tr class="sub"><td colspan="5" class="muted" style="padding-left:18px">${x.items_note}</td></tr>`:'';
   return head+parts+note;
 }).join('')+landscapingGapRow();
 {
  const expenseSum=Number(r.summary.total_expenses||0)||expenseRows.reduce((s,x)=>s+Number(x.value||0),0);
  expenseTotal.textContent=money(expenseSum);
  // Итог — числа движка на ту же базу, что строки, а не деление здесь.
  document.getElementById('expenseBaseHead').textContent='тыс ₽/м² '+TERMS.total_area.genitive;
  document.getElementById('expenseTotalGns').textContent=unitNum(r.summary.full_cost_per_total_area_th,2);
  document.getElementById('expenseTotalSaleable').textContent=unitNum(r.summary.full_cost_per_saleable_th,2);
 }

 ratesDebtTable.innerHTML=
  row('Сценарий ключевой ставки',rateScenarioLabel(inputs.rate_scenario))+
  row('Текущая ключевая ставка',pct(r.report.financing.current_key_rate))+
  row('Спред БРИДЖ',pct(r.report.financing.bridge_spread))+
  row('Ставка БРИДЖ на текущей ключевой',pct(r.report.financing.current_bridge_rate))+
  row('Средняя ключевая за период БРИДЖ',pct(r.report.financing.avg_bridge_key_rate))+
  row('Средневзвешенная ставка БРИДЖ за период',pct(r.report.financing.avg_bridge_rate))+
  row('Средняя ключевая в период ПФ',pct(r.report.financing.avg_pf_key_rate))+
  row('Средняя ставка ПФ без эффекта эскроу',pct(r.report.financing.avg_pf_base_rate))+
  row('Ставка ПФ при покрытии эскроу 1×',pct(r.report.financing.pf_special_rate))+
  pfStepRows(r.report.financing)+
  // Пики, лимит, проценты и LLCR — в карточке «Финансирование» рядом; здесь
  // стояли их повторы (ревизия интерфейса, S7).
  row('Средняя фактическая ставка ПФ с учётом эскроу',pct(r.report.financing.avg_pf_effective_rate));

 // Признак приходит из движка и читается как есть: выводить «продаётся ли»
 // из нулевой выручки значило бы путать «не продал в этом расчёте» с «не
 // продаётся по построению».
 // Объект вне состава проекта движок помечает (`row_outside_project`) —
 // та же мерка, что у таблицы ТЭП: удалённые объекты не стоят строкой нулей.
 const sellable=p=>p.sellable!==false&&!p.excluded;
 if(phaseBundle&&phaseBundle.mode==='phased'&&reportView==='all'&&Array.isArray(r.report.phase_products)){
   const phaseNames=(phaseBundle.phases||[]).map(x=>x.name);
   const productTotals=Object.fromEntries((r.report.products||[]).map(x=>[x.key,x]));
   salesReportHead.innerHTML=`<tr><th>Продукт</th><th>ГНС, м²</th><th>Продаваемая, м²</th>${phaseNames.map(n=>`<th>${n}: объём</th>`).join('')}<th>Средняя цена</th><th>Выручка</th><th>Себестоимость</th><th>Маржа</th></tr>`;
   // Соцобъект не продаётся по построению: в таблице ПРОДАЖ ему не место.
   // Он стоял тут строкой с объёмом «350 м²» и выручкой ноль — мощность,
   // подписанная чужой единицей. Метры и мощность его видны в таблице ТЭП,
   // где у них свои колонки и своя мера.
   salesReportTable.innerHTML=(r.report.phase_products||[]).filter(sellable).map(p=>{
     const by=Object.fromEntries((p.phases||[]).map(x=>[x.phase,x]));
     const total=productTotals[p.key]||{};
     return `<tr><td>${p.label}</td><td>${num(total.gns||0)}</td><td>${num(total.saleable||0)}</td>`+
       phaseNames.map(n=>{const x=by[n]||{};return `<td>${num(x.quantity||0)} ${p.unit}<div class="cell-sub">${num(x.pace_pre||0)} ${p.unit}/мес</div></td>`}).join('')+
       `<td>${th(p.avg_price_th)}</td><td>${money(p.revenue)}</td><td>${money(total.cost||0)}</td><td>${total.margin==null?'—':pct(total.margin)}</td></tr>`;
   }).join('');
 }else{
   salesReportHead.innerHTML='<tr><th>Продукт</th><th>ГНС, м²</th><th>Продаваемая, м²</th><th>Объём</th><th>Средняя цена</th><th>Выручка</th><th>Себестоимость</th><th>Маржа</th></tr>';
   // Квартиры продаются штуками: «40 квартир в месяц» проверяется отделом
   // продаж и рынком, «2 400 м² в месяц» — нет. Метры остаются главными,
   // штуки идут второй строкой там же, а не абзацем ниже.
   const ap=r.report.apartment_sales||{};
   const inUnits=p=>p.key==='apartments'&&Number(ap.units_total||0)>0;
   const sub=text=>`<div class="cell-sub">${text}</div>`;
   // Профиль продаж и лестница цены объекта печатаются рядом с продуктом:
   // «60% в сделку, 40% через год» отличает объект с одним покупателем от
   // равномерных продаж, а неразобранная строка называется, а не молчит.
   const schedSub=p=>(p.sales_profile?sub('профиль продаж: '+escapeHtml(p.sales_profile)):'')
    +(p.price_ladder?sub('лестница цены: '+escapeHtml(p.price_ladder)):'')
    +((p.schedule_warnings||[]).length?sub('<span style="color:#A35D00">'+p.schedule_warnings.map(escapeHtml).join('; ')+'</span>'):'');
   // Паркинг объекта — строка своего объекта; построенное и продаваемое у него
   // разные числа: у ТЦ и ФОКа места строятся, но не продаются, и «0 шт.»
   // без подписи читалось бы как «мест нет».
   const builtSub=p=>p.built_units==null?'':sub('построено '+num(p.built_units)+' мест'
    +(Number(p.quantity||0)>0?'':' · не продаются — обеспечивают посетителей'));
   salesReportTable.innerHTML=(r.report.products||[]).filter(sellable).map(p=>`<tr>
    <td>${p.label}${schedSub(p)}${builtSub(p)}</td>
    <td>${num(p.gns||0)}</td>
    <td>${num(p.saleable||0)}</td>
    <td>${num(p.quantity)} ${p.unit}${inUnits(p)?sub(num(Math.round(ap.units_total))+' шт. · '+num2(ap.pace_pre_rve_units)+' кв./мес.'):''}</td>
    <td>${th(p.avg_price_th)}</td>
    <td>${money(p.revenue)}</td>
    <td>${money(p.cost||0)}</td>
    <td>${p.margin==null?'—':pct(p.margin)}</td>
   </tr>`).join('');
 }

 {
  const ap=r.report.apartment_sales||{};
  const paceEl=document.getElementById('apartmentPaceTable');
  if(paceEl)paceEl.innerHTML=Number(ap.units_total||0)>0?
   row('Квартир в проекте',num(Math.round(ap.units_total))+' шт.')+
   row('Средняя площадь квартиры',num2(ap.avg_unit_sqm)+' м²')+
   // Цена одной квартиры — десятки миллионов: в миллиардах она выходила
   // «0,03 млрд ₽» (ревизия интерфейса, S5). PDF пишет её в млн ₽ — так же.
   row('Средняя цена квартиры',mln(Number(ap.avg_unit_price_mln||0)*1e6))+
   row('Темп продаж до РВЭ',num2(ap.pace_pre_rve_units)+' кв./мес.')+
   row('Средний темп за период продаж',num2(ap.pace_units)+' кв./мес.')+
   row('Пиковый месяц',num2(ap.peak_units)+' кв.')
   :'';
  renderApartmentPaceChart(ap);
 }

 // Вкладка «Календарь» и раздел отчёта — один календарь (`calendarView`):
 // у проекта без жилья вкладка прежде рисовала жилой — «Старт продаж»,
 // «РВЭ», «Строительство ЖК» у гостиницы.
 syncSensitivityFrame(r);
 const calView=calendarView(r);
 calendarDateBoxes.innerHTML=calView.datesHtml;
 renderGantt('calendarGantt',calView.calendar);
 calendarRange.textContent=calView.calendar.start?dateRu(calView.calendar.start)+' — '+dateRu(calView.calendar.end):'—';

 // Календарь и чувствительность жили только на своих вкладках и в PDF: человек
 // смотрел отчёт на экране, печатал его и видел два незнакомых раздела. Отчёт
 // обязан быть тем же документом, что уходит в печать.
 {
  const dates=document.getElementById('reportCalendarDates');
  if(dates)dates.innerHTML=calView.datesHtml;
  renderGantt('reportCalendarGantt',calView.calendar);
  renderReportSensitivity();
  renderReportToc(r);
 }

 {
  // Рубль на метр в обеих базах: сумма сама по себе не сравнивается ни с
  // рынком, ни с себестоимостью.
  // Выручка — на продаваемую площадь (решение 4 ревизии книги); делит
  // движок (`revenue_structure`), страница печатает.
  // Состав, порядок и итоги групп решает движок (`revenue_structure`):
  // МКД → Итого МКД → объекты, каждый со своим паркингом → Итого ОСЗ →
  // Итого; нулевых продуктов нет. Прежде строки шли в порядке словаря.
  // Результат без раскладки (сохранён до неё) печатается прежним списком,
  // а не пустой таблицей: пустота читалась бы как «выручки нет».
  const rs=(r.revenue_structure||{}).rows
   ||[...Object.entries(r.revenue||{}).filter(([k])=>k!=='total').map(([k,v])=>({label:productName(k),value:v,role:'part',group:''})),
      {label:'Итого',value:(r.revenue||{}).total,role:'total',group:'all'}];
  revenueTable.innerHTML=rs.map(x=>{
   const c=x.group==='all'?'th':'td',cls=x.role==='total'?(x.group==='all'?'':' class="rs-total"'):' class="rs-part"';
   return `<tr${cls} data-group="${x.group}" data-role="${x.role}"><${c}>${escapeHtml(x.label)}</${c}><${c}>${money(x.value)}</${c}><${c}>${unitNum(x.per_saleable_th,2)}</${c}></tr>`;
  }).join('');
 }
 renderNonresStrategy(r);
 renderHotelReport(r);
 renderNonresFinancing(r);
 renderEquityParticipation(r);
 // Имена статей приходят из движка плейсхолдером, как VERSION и доли ТЭП.
 const capNames=__DEVELOPAID_CAPEX_NAMES__;
 {
  // Удельные статей — движка (`capex_units`): СМР на свою часть, прочее на
  // суммарную площадь в ГНС; база названа в строке.
  const cu=r.capex_units||{};
  const capCells=key=>{const u=cu[key]||{};
   return `<td>${unitNum(u.per_base_th,2)}</td><td>${unitBase(u)}</td><td>${unitNum(u.per_saleable_th,2)}</td>`;};
  // Порядок статей — порядок движка (`_MODEL_CAPEX_LABELS`: земля → ИРД и
  // проект → снос → СМР → объекты → соцнагрузка → надбавки → резерв), а не
  // порядок ключей ответа. Нулевая статья строку не занимает: итог её не
  // теряет, а «0 млрд ₽» между статьями только мешает читать.
  const capOrder=Object.keys(capNames);
  const capRank=key=>{const i=capOrder.indexOf(key);return i<0?capOrder.length:i};
  capexTable.innerHTML=Object.entries(r.capex).filter(([key,v])=>key!=='total'&&Math.abs(Number(v||0))>=0.5)
   .sort((a,b)=>capRank(a[0])-capRank(b[0]))
   .map(([key,v])=>`<tr><td>${capNames[key]||key}</td><td>${money(v)}</td>${capCells(key)}</tr>`).join('')
   +`<tr><th>Итого CAPEX</th><th>${money(r.capex.total)}</th>${capCells('total').replace(/<(\/?)td>/g,'<$1th>')}</tr>`;
 }
 // Построенных штук и проданных — разные числа, и до сих пор на экране стояло
 // только первое. Разниц теперь две: гостевые места (строятся, но общие) и
 // переданные в натуре (строятся, но отданы). Обе считает движок и обе везёт
 // строкой ТЭП — экран их только показывает, своей арифметики здесь нет.
 const soldUnits=x=>Number(x.saleable_units!==undefined?x.saleable_units:x.units||0);
 const unitNote=x=>{
  const parts=[];
  if(Number(x.guest_units||0)>0)parts.push('гостевых '+num(x.guest_units));
  if(Number(x.transfer_units||0)>0)parts.push('передано '+num(x.transfer_units));
  return parts.length
   ? `<span style="display:block;font-size:10px;color:#777">из них ${parts.join(' · ')}</span>`
   : '';
 };
 // Итога штук одним числом больше нет: квартиры, машино-места и места ДОО
 // складывались в 2 811 «штук», не значащих ничего. Ответ — разбор по мере.
 const builtCounts=countsCell(r.tep.rows,'units','parking_units');
 const soldCounts=countsCell(r.tep.rows.map(x=>Object.assign({},x,{_sold:soldUnits(x)})),
  '_sold','parking_saleable_units');
 // ГНС — наземная площадь здания, и у гаража с кладовыми её нет: под землёй
 // наружных стен не бывает, а экономика у подземной части своя — свой метр
 // стройки и продукт, продаваемый местами. Пока обе величины стояли в одной
 // колонке, итог складывал их под одним именем; теперь у каждой своя колонка,
 // и каждая складывается сама с собой. Строительный объём — их сумма, и он
 // назван отдельно: на нём считаются общие статьи.
 // Подземную базу считает движок (core_under_gns) — экран её не собирает:
 // второй счёт той же величины однажды разошёлся бы с первым.
 const underGns=Number(r.tep.core_under_gns||0);
 const isUnder=x=>UNDERGROUND_PRODUCTS.includes(x.key);
 const aboveGns=Math.max(0,Number(r.tep.total.gns||0)-underGns);
 // Гараж отдельно стоящего объекта — такая же подземная площадь, как гараж
 // дома, и живёт он полем на строке объекта. В колонке его не было вовсе, при
 // том что в `summary.underground_gns_sqm` и в статье CAPEX он есть: две
 // величины под одним именем. Итог берётся у движка, экран его не собирает.
 const objUnder=x=>Number(x.under_gns||0);
 const underTotal=Number(r.summary.underground_gns_sqm!==undefined
  ?r.summary.underground_gns_sqm:underGns);
 const dash='<span style="color:#bbb">—</span>';
 // Переданные метры строятся и не продаются: в продаваемой их нет, и без
 // указания отчёт читается так, будто продано всё построенное — «в отчёте
 // вообще нет указания на передаваемую! Чтобы не забыть, что вообще-то не всё
 // продал» (владелец, 10.09.2026).
 //
 // Стояло это ПРИПИСКОЙ ВНУТРИ колонки «Продаваемая площадь», и выходило
 // обратное задуманному: метры школы печатались под заголовком «продаваемая»
 // — «якобы продаются якобы метры школы и садика» (владелец, 26.09.2026).
 // Число отвечает на заголовок СВОЕЙ колонки, а не на приписку под собой,
 // поэтому у переданных метров колонка своя. Ноль в продаваемой при этом
 // остаётся нулём: «0 тоже сойдут» (владелец, 26.09.2026).
 const transferTotal=r.tep.rows.reduce((sum,x)=>sum+Number(x.transfer||0),0);
 // Свой паркинг отдельно стоящего объекта — продукт: гараж и места первых
 // этажей строятся, у офисника продаются машино-местами. Полем на строке
 // объекта он в ТЭП не был виден вовсе — ни мест, ни продаваемых; теперь это
 // подстрока «в т.ч.» с местами, а подземные метры гаража стоят на ней же.
 const objParkUnits=x=>Number(x.parking_units||0);
 const objParkRow=x=>{
  if(!objParkUnits(x))return '';
  const under=Number(x.parking_under_units||0),over=Number(x.parking_over_units||0);
  const sold=Number(x.parking_saleable_units||0),guest=Number(x.parking_guest_units||0);
  const where=[under?'подземных '+num(under):'',over?'на первых этажах '+num(over)+' (в ГНС здания)':''].filter(Boolean).join(' · ');
  const small=t=>t?`<span style="display:block;font-size:10px;color:#777">${t}</span>`:'';
  return `<tr class="sub"><td style="padding-left:18px">в т.ч. паркинг объекта, машино-места${small(where)}</td>`
   +`<td>${dash}</td><td>${objUnder(x)>0?num(objUnder(x)):dash}</td><td>${dash}</td><td>${dash}</td>`
   +`<td>${num(objParkUnits(x))}${small(guest?'из них гостевых '+num(guest):'')}</td>`
   +`<td>${num(sold)}${small(sold?'':'места обеспечивают посетителей, не продаются')}</td></tr>`;
 };
 reportTep.innerHTML=
  `<thead><tr><th>Продукт</th><th>ГНС наземная, м²</th><th>Подземная, м²</th><th>Продаваемая площадь, м²</th><th>Передаётся, м²</th><th>Построено</th><th>Продаётся</th></tr></thead>`+
  `<tbody>`+
  // Строку вне состава проекта движок помечает сам (`row_outside_project`):
  // то, что тип проекта не считает (нулевой «Подземный паркинг» дома рядом с
  // гаражом объекта читался бы вторым паркингом), и объект, которого в проекте
  // нет — удалённые «Коммерция ОСЗ 2…5», «Офисы 2…4» стояли здесь нулями.
  r.tep.rows.filter(x=>!x.excluded).map(x=>`<tr><td>${x.label}</td>`
   +`<td>${isUnder(x)?dash:num(x.gns)}</td>`
   +`<td>${isUnder(x)?num(x.gns):(objUnder(x)>0&&!objParkUnits(x)?num(objUnder(x)):dash)}</td>`
   +`<td>${num(x.saleable)}</td><td>${num(x.transfer)}</td>`
   +`<td>${countWithMeasure(x.key,x.units)}${unitNote(x)}</td>`
   +`<td>${countWithMeasure(x.key,soldUnits(x))}</td></tr>`
   +objParkRow(x)).join('')+
  `</tbody><tfoot><tr><th>Итого</th><th>${num(aboveGns)}</th><th>${num(underTotal)}</th>`
  +`<th>${num(r.tep.total.saleable)}</th><th>${num(transferTotal)}</th>`
   +`<th>${builtCounts}</th><th>${soldCounts}</th></tr></tfoot>`;
 const tepNote=document.getElementById('reportTepNote');
 if(tepNote)tepNote.innerHTML=underTotal>0
  ? `${TERMS.total_area.name} — ${num(Number(r.summary.construction_volume_sqm!==undefined?r.summary.construction_volume_sqm:r.tep.total.gns))} м², наземная плюс подземная. Общие статьи (ИРД, проектирование, подготовка, сети, сдача, содержание) считаются от ${TERMS.core_total_area.genitive}${r.tep.core_above_gns!==undefined?' — '+num(Number(r.tep.core_above_gns)+Number(r.tep.core_under_gns||0))+' м²':''}: квартиры, коммерция 1 этажа, подземный паркинг и кладовые. Удельные «на метр» считаются на наземной ГНС: подземная в неё не входит — у неё своя себестоимость метра и свой продукт, продаваемый местами. ГНС — внутренний термин DevelopAid; город нагрузки считает от суммарной поэтажной площади.`
  : 'ГНС — наземная площадь здания, внутренний термин DevelopAid. Город нагрузки считает от суммарной поэтажной площади.';
}


const REPORT_SECTIONS=[
 ['rsSite','Участок'],['rsSummary','Итог'],['rsPhases','Очереди'],
 ['rsExpenses','Расходы'],['rsIncome','Доходы'],['rsFinance','Финансирование'],
 ['rsSensitivity','Чувствительность'],['rsCalendar','Календарь'],
];

function socialPerMetre(r){
 // Социальная нагрузка на метр читается как цена входа в проект и сравнивается
 // между площадками; в миллиардах такое сравнение не делают.
 const gns=Number(r.summary.project_gns_sqm||0),saleable=Number(r.summary.monetizable_saleable_sqm||0);
 const value=Number(r.summary.social_payment||0);
 if(!(value>0)||!(gns>0))return '';
 const per=(area)=>area>0?num2(value/area/1000)+' тыс ₽/м²':'—';
 return row('Нагрузка на метр',per(gns)+' ГНС · '+per(saleable)+' прод.');
}

function renderReportSensitivity(){
 const box=document.getElementById('reportSensitivity');
 if(!box)return;
 if(!sensitivityReport||!(sensitivityReport.items||[]).length){
  box.innerHTML='<div class="section-title">Чувствительность</div>'
   +'<div style="font-size:12px;color:#777;margin-bottom:10px">Не рассчитана. '
   +'В PDF она досчитывается сама, поэтому печатный отчёт будет полнее экранного.</div>'
   +'<button class="btn no-print" onclick="openTab(\'sensitivity\',null);renderSensitivityForm()">Открыть расчёт чувствительности</button>';
  return;
 }
 const base=sensitivityReport.base;
 // Охват называется рядом с величиной проекта: торнадо по слабейшей очереди
 // и LLCR всего проекта — разные числа, и без второй половины первое читается
 // как «модель посчитала иначе».
 const scopeLine=escapeHtml(base.scope_label||'')+' · база '
  +sensFormat(base.value,base.digits)+' '+escapeHtml(base.unit||'')
  +(base.project_value===null||base.project_value===undefined?''
    :' · не весь проект: у проекта '+sensFormat(base.project_value,base.digits)+' '
      +escapeHtml(base.unit||''));
 box.innerHTML='<div class="section-title">Чувствительность · '+escapeHtml(base.label)+'</div>'
  +'<div style="font-size:12px;color:#777;margin-bottom:10px">'+scopeLine+'</div>'
  +'<div id="reportTornado"></div>'
  +(sensitivityReport.verdict||[]).map(line=>`<div class="note">${escapeHtml(String(line))}</div>`).join('');
 renderTornado(sensitivityReport,'reportTornado');
}

function renderReportToc(r){
 // Ссылка, ведущая в пустоту, хуже её отсутствия: очередей у одноочередного
 // проекта нет, чувствительности — пока её не посчитали.
 //
 // Но «раздел есть» — это не «раздел виден сейчас». Меню строится сразу после
 // расчёта, а вкладка отчёта в этот момент закрыта: у скрытой панели
 // display:none, и на вопрос о видимости все её разделы отвечали «меня нет».
 // Меню отфильтровывало себя до пустоты каждый раз. Смотрим на содержимое:
 // скрытый своим стилем раздел и раздел без карточек — мимо, остальные — в меню.
 const toc=document.getElementById('reportToc');
 if(!toc)return;
 const shown=el=>{try{return getComputedStyle(el).display!=='none'}catch(e){return true}};
 toc.innerHTML=reportTocSections(r||(typeof lastResult!=='undefined'?lastResult:null)).filter(([id])=>{
  const node=document.getElementById(id);
  if(!node||!shown(node))return false;
  return Array.from(node.children).some(child=>!child.classList.contains('report-section-title')
   &&shown(child)&&child.textContent.trim().length>0);
 }).map(([id,label])=>`<a href="#${id}" onclick="event.preventDefault();document.getElementById('${id}').scrollIntoView({behavior:'smooth',block:'start'})">${label}</a>`).join('');
}

// Календарь проекта — один на вкладку «Календарь» и раздел отчёта. У
// проекта без жилья — свой (`object_report`): стройка объекта, продажи /
// заполнение, кредит и выход; гостиница отдаёт вехи готовыми
// (`_hotel_calendar.dates`). Жилого календаря рамка объекта не печатает даже
// пустой: «Старт продаж» и «РВЭ» читались бы вехами объекта.
function calendarView(r){
 const frame=reportLayout(r).object_frame;
 const objCal=(objectSection(r,'calendar')||{}).calendar||null;
 const objItems=objCal?(((r.finance||{}).nonres||{}).objects||[]):null;
 const dates=frame?(objCal&&objCal.dates?objCal.dates.map(x=>[escapeHtml(x[0]),x[1]]):[
   ['Начало',r.dates.project_start],['РнС',r.dates.permit],
   ...(objItems||[]).map(o=>['Ввод — '+escapeHtml(o.title||o.key),o.commissioning]),
   ...(objItems||[]).map(o=>['Конец горизонта — '+escapeHtml(o.title||o.key),o.horizon_end]),
  ]):[
   ['Начало',r.dates.project_start],['РнС',r.dates.permit],
   ['Старт продаж',r.dates.sales_start],['РВЭ',r.dates.rve]
  ];
 return {datesHtml:dates.map(x=>`<div class="datebox">${x[0]}<b>${dateRu(x[1])}</b></div>`).join(''),
  calendar:frame?(objCal&&(objCal.events||[]).length?objCal
   :{events:[],reason:'Календаря объекта нет: расчёт объекта не построил ни одной вехи — '
     +'смотрите раздел «Объект и участок».'}):r.report.calendar};
}

function renderGantt(targetId,calendar){
 const target=document.getElementById(targetId);if(!target||!calendar){return}
 const events=calendar.events||[];if(!events.length){target.innerHTML=calendar.reason?`<div class="note">${escapeHtml(calendar.reason)}</div>`:'';return}
 const start=new Date(calendar.start+'T00:00:00'),end=new Date(calendar.end+'T00:00:00');
 const total=Math.max(1,(end-start)/(1000*60*60*24));
 const posDate=d=>Math.max(0,Math.min(100,(d-start)/(1000*60*60*24)/total*100));
 const pos=iso=>posDate(new Date(iso+'T00:00:00'));
 const groups=[];events.forEach(e=>{if(!groups.includes(e.group))groups.push(e.group)});

 // Quarter boundaries covering the whole project horizon.
 const qStart=new Date(start);
 qStart.setMonth(Math.floor(qStart.getMonth()/3)*3,1);
 const quarters=[];
 for(let d0=new Date(qStart);d0<=end;d0.setMonth(d0.getMonth()+3)){
   const qs=new Date(d0);
   const qe=new Date(d0);qe.setMonth(qe.getMonth()+3);
   quarters.push({start:qs,end:qe,year:qs.getFullYear(),q:Math.floor(qs.getMonth()/3)+1});
 }
 const quarterCount=quarters.length;
 const minWidth=Math.max(1150,250+quarterCount*105);

 let quarterAxis='',quarterLines='';
 quarters.forEach(q=>{
   const l=posDate(q.start),r=posDate(q.end),w=Math.max(0,r-l);
   quarterAxis+=`<div class="gantt-quarter" style="left:${l}%;width:${w}%">Q${q.q}</div>`;
   quarterLines+=`<div class="gantt-quarter-line" style="left:${l}%"></div>`;
 });

 let yearAxis='',yearLines='';
 const years=[...new Set(quarters.map(q=>q.year))];
 years.forEach(year=>{
   const ys=new Date(`${year}-01-01T00:00:00`);
   const ye=new Date(`${year+1}-01-01T00:00:00`);
   const l=posDate(ys),r=posDate(ye),w=Math.max(0,r-l);
   yearAxis+=`<div class="gantt-year-band" style="left:${l}%;width:${w}%">${year}</div>`;
   yearLines+=`<div class="gantt-year-line" style="left:${l}%"></div>`;
 });

 const axisMarkup=yearAxis+quarterAxis+yearLines;
 const gridMarkup=quarterLines+yearLines;

 let html=`<div class="gantt" style="min-width:${minWidth}px"><div class="gantt-axis"><div class="gantt-label"><b>Этап / событие</b></div><div class="gantt-track">${axisMarkup}</div></div>`;
 const phasePalette=['#242424','#555555','#7d7d7d','#a2a2a2','#c0c0c0'];
 const phaseNames=[];
 events.forEach(e=>{
   if(e.phase_index!=null&&!phaseNames.some(x=>x.index===Number(e.phase_index))){
     phaseNames.push({index:Number(e.phase_index),name:e.phase_name||`О${e.phase_index}`});
   }
 });
 phaseNames.sort((a,b)=>a.index-b.index);

 groups.forEach(g=>{
   html+=`<div class="gantt-row"><div class="gantt-label group">${g}</div><div class="gantt-track">${gridMarkup}</div></div>`;
   events.filter(e=>e.group===g).forEach(e=>{
     const l=pos(e.start),rgt=pos(e.end),w=Math.max(.4,rgt-l);
     const phaseIndex=Number(e.phase_index||0);
     const phaseColor=phaseIndex?phasePalette[Math.min(phaseIndex-1,phasePalette.length-1)]:null;
     let cls='';if(g==='Финансирование')cls=' finance';else if(g==='Продажи'||g==='Аренда')cls=' sales';else if(g==='Социальная нагрузка')cls=' social';
     const phaseClass=phaseColor?' phase-colored':'';
     const phaseStyle=phaseColor?`--phase-color:${phaseColor};`:'';
     const shape=e.kind==='milestone'
       ? `<div class="gantt-diamond${phaseClass}" style="${phaseStyle}left:${l}%"></div>`
       : `<div class="gantt-bar${phaseColor?'':cls}${phaseClass}" style="${phaseStyle}left:${l}%;width:${w}%"></div>`;
     html+=`<div class="gantt-row${phaseColor?' phase-row':''}" style="${phaseStyle}"><div class="gantt-label">${e.label}<span class="gantt-date">${dateRu(e.start)}${e.end!==e.start?' — '+dateRu(e.end):''}</span></div><div class="gantt-track">${gridMarkup}${shape}</div></div>`;
   });
 });
 html+='</div>';target.innerHTML=html;

 // Phase legend is shown only for a consolidated multi-phase calendar.
 if(targetId==='calendarGantt'){
   const phaseLegend=document.getElementById('calendarPhaseLegend');
   const typeLegend=document.getElementById('calendarTypeLegend');
   if(phaseLegend){
     phaseLegend.innerHTML=phaseNames.length>1
       ? phaseNames.map(p=>`<span style="--phase-color:${phasePalette[Math.min(p.index-1,phasePalette.length-1)]}">${p.name}</span>`).join('')
       : '';
   }
   // In the multi-phase view color encodes the queue; labels still identify event type.
   // Preserve the old type legend unchanged for a single-phase project.
   // Легенда типов — жилая («Продажи»): в рамке объекта её нет.
   const frame=typeof lastResult!=='undefined'&&reportLayout(lastResult).object_frame;
   if(typeLegend)typeLegend.style.display=phaseNames.length>1||frame?'none':'flex';
 }
}

// Месячный темп продаж квартир в штуках. Форма повторяет график из PDF —
// столбцы, четыре линии сетки, подписи месяцев по краям и в середине: экран и
// печать обязаны показывать одно и то же, иначе печать выглядит другим отчётом.
function renderApartmentPaceChart(sales){
 const target=document.getElementById('apartmentPaceChart');if(!target)return;
 const rows=(sales&&sales.rows)||[];
 const values=rows.map(x=>Math.max(0,Number(x.units||0)));
 const peak=Math.max(...values,0);
 // Пустой график с рамкой хуже отсутствующего: он обещает данные, которых нет.
 if(!rows.length||peak<=0){target.innerHTML='';target.style.display='none';return}
 target.style.display='';
 // Пропорции те же, что у графика в PDF (500×104): при фиксированной высоте
 // контейнера широкий график вписывался с полями в треть ширины.
 const W=1000,H=210,pL=50,pR=16,pT=20,pB=28;
 const top=peak*1.08,plotW=W-pL-pR,plotH=H-pT-pB;
 const slot=plotW/rows.length,bw=Math.max(1,slot*0.72);
 const y=v=>pT+plotH-plotH*v/top;
 let grid='';
 for(let tick=0;tick<=3;tick++){
  const value=top*tick/3;
  grid+=`<line x1="${pL}" y1="${y(value)}" x2="${W-pR}" y2="${y(value)}" stroke="#e5e5e5"/>`
      +`<text x="${pL-6}" y="${y(value)+4}" font-size="11" fill="#777" text-anchor="end">${num(value)}</text>`;
 }
 const bars=values.map((v,i)=>v<=0?'':
   `<rect x="${pL+i*slot+(slot-bw)/2}" y="${y(v)}" width="${bw}" height="${plotH*v/top}" fill="#202020"/>`).join('');
 const monthRu=iso=>{const [yy,mm]=String(iso||'').slice(0,7).split('-');return mm+'.'+yy};
 const marks=[...new Set([0,Math.floor(rows.length/2),rows.length-1])].map(i=>
   `<text x="${pL+(i+0.5)*slot}" y="${H-8}" font-size="11" fill="#777" text-anchor="middle">${monthRu(rows[i].month)}</text>`).join('');
 target.innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="height:auto;display:block">
  ${grid}${bars}
  <text x="${W-pR}" y="${pT-5}" font-size="11" fill="#777" text-anchor="end">квартир/мес.</text>
  ${marks}
 </svg>`;
}

// Эскроу против обязательства по ПФ. Прежде здесь сравнивалось тело долга со
// счётом — то есть ответ на другой вопрос: банку в раскрытие причитается и
// начисленное, оно копится вне лимита и платится кассой. Один рисовальщик на
// проект и на очереди: два разошлись бы, и оба выглядели бы верными. Числа
// приходят готовыми с сервера, здесь только геометрия.
function escrowCoverSvg(rows,cover){
 cover=cover||{};
 const duty=x=>Number(x.pf_obligation!==undefined?x.pf_obligation:(Number(x.pf_balance||0)+Number(x.pf_payable||0)));
 // Месяцы без долга и без счёта не рисуются — иначе ось растянута на годы
 // пустоты. Но обрезать их ВСЕ нельзя: первой точкой становится месяц с уже
 // сделанной выборкой, и кривая начинается с полки в миллиард — «зелёное и
 // жёлтое поле второй очереди не с 0 идут» (владелец, 04.09.2026). Соседний
 // месяц с каждой стороны остаётся: он настоящий и он нулевой, и на нём
 // видно, что очередь начинает с нуля.
 const all=(rows||[]);
 const alive=all.map(x=>duty(x)>0||Number(x.escrow||0)>0);
 const first=alive.indexOf(true), last=alive.lastIndexOf(true);
 if(first<0)return '';
 const data=all.slice(Math.max(0,first-1),Math.min(all.length,last+2));
 if(data.length<2)return '';
 const W=900,H=250,pL=58,pR=58,pT=18,pB=26,plotW=W-pL-pR,plotH=H-pT-pB;
 // Долг — это «сколько должны сейчас», накопленное — «сколько пришло с
 // начала». Разные величины, и на одной шкале накопленное всегда перерастает
 // долг: к концу оно равно почти всей выручке, а долг нулю. Долг сплющивался
 // в нижнюю треть графика. Поэтому у накопленного своя ось справа.
 const top=Math.max(...data.map(x=>Math.max(duty(x),Number(x.escrow||0))),1)*1.08;
 const cumTop=Math.max(...data.map(x=>Math.max(Number(x.escrow_released_cumulative||0),
  Number(x.sales_after_rve_cumulative||0))),1)*1.08;
 const X=i=>pL+plotW*i/(data.length-1);
 const Y=v=>pT+plotH-plotH*Math.max(0,v)/top;
 const Yc=v=>pT+plotH-plotH*Math.max(0,v)/cumTop;
 const pt=(i,v)=>`${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
 const path=f=>data.map((x,i)=>pt(i,f(x))).join(' ');
 // Заливка, а не линия: вопрос у графика один — перекрывает эскроу
 // обязательство или нет, — и ответ на него это площадь между кривыми.
 const area=f=>`${pt(0,0)} ${path(f)} ${pt(data.length-1,0)}`;
 // Непокрытая часть — своей заливкой, куском за куском: обязательство вперёд,
 // эскроу обратно. Один сплошной полигон склеил бы разрывы и закрасил месяцы,
 // где всё покрыто.
 let gaps='',run=[];
 const flush=()=>{if(run.length>1){
   const up=run.map(i=>pt(i,duty(data[i]))).join(' ');
   const back=run.slice().reverse().map(i=>pt(i,Number(data[i].escrow||0))).join(' ');
   gaps+=`<polygon points="${up} ${back}" fill="#A35D00" fill-opacity="0.16"/>`}
  run=[]};
 data.forEach((x,i)=>{if(duty(x)-Number(x.escrow||0)>0)run.push(i);else flush()});flush();
 let grid='';
 for(let t=0;t<=4;t++){const v=top*t/4,y=Y(v);
  grid+=`<line x1="${pL}" y1="${y.toFixed(1)}" x2="${W-pR}" y2="${y.toFixed(1)}" stroke="#e8e8e8"/>`
   +`<text x="${pL-6}" y="${(y+4).toFixed(1)}" font-size="11" fill="#777" text-anchor="end">${(v/1e9).toLocaleString('ru-RU',{maximumFractionDigits:1})}</text>`}
 const monthRu=iso=>{const parts=String(iso||'').slice(0,7).split('-');return parts.length===2?parts[1]+'.'+parts[0]:''};
 const marks=[...new Set([0,Math.floor(data.length/2),data.length-1])].map(i=>
  `<text x="${X(i).toFixed(1)}" y="${H-7}" font-size="11" fill="#777" text-anchor="${i===0?'start':(i===data.length-1?'end':'middle')}">${monthRu(data[i].month)}</text>`).join('');
 const at=data.findIndex(x=>String(x.month||'').slice(0,7)===String(cover.rve||'').slice(0,7));
 const late=at>data.length*0.7;
 const rveMark=at<0?'':`<line x1="${X(at).toFixed(1)}" y1="${pT}" x2="${X(at).toFixed(1)}" y2="${(pT+plotH).toFixed(1)}" stroke="#666" stroke-dasharray="3 3"/>`
  +`<text x="${X(at).toFixed(1)}" y="${pT+11}" dx="${late?-5:5}" font-size="11" fill="#555" text-anchor="${late?'end':'start'}">раскрытие эскроу</text>`;
 // Последняя точка — событие, а не обрыв линии: непогашенный остаток надо
 // назвать, иначе график читается как «расчёт кончился».
 const endLeft=Number(cover.ending_unpaid||0);
 const endMark=endLeft<=1e6?'':`<circle cx="${X(data.length-1).toFixed(1)}" cy="${Y(endLeft).toFixed(1)}" r="3.5" fill="#A35D00"/>`
  +`<text x="${(X(data.length-1)-6).toFixed(1)}" y="${(Y(endLeft)-8).toFixed(1)}" font-size="11" fill="#A35D00" text-anchor="end">не погашено ${mln(endLeft)}</text>`;
 // Сколько банк получил всего, накопленным итогом: раскрытый эскроу и то,
 // чем гасят дальше. Прежде здесь шли «продажи после раскрытия» от нуля —
 // рядом с эскроу в десятки миллиардов такая линия не значила ничего
 // (владелец, 01.09.2026). Вопрос у графика один: чем и когда закрыт долг.
 // Раскрытие эскроу и продажи после ввода — разные события, и одной линией
 // они врут. Ступенька в 70 млрд читалась как «после ввода продали на 70»
 // (владелец, 01.09.2026), хотя продаж в этот месяц ноль: это деньги
 // предыдущих двух лет, снятые с эскроу разом. Теперь их две.
 const cumPath=f=>data.map((x,i)=>`${X(i).toFixed(1)},${Yc(f(x)).toFixed(1)}`).join(' ');
 const released=data.some(x=>Number(x.escrow_released_cumulative||0)>0)
  ?`<polyline points="${cumPath(x=>Number(x.escrow_released_cumulative||0))}" fill="none" stroke="#1B5E77" stroke-width="1.8" stroke-dasharray="6 4"/>`:'';
 const afterSales=data.some(x=>Number(x.sales_after_rve_cumulative||0)>0)
  ?`<polyline points="${cumPath(x=>Number(x.sales_after_rve_cumulative||0))}" fill="none" stroke="#1B5E77" stroke-width="1.4" opacity="0.55"/>`:'';
 const repaid=released+afterSales;
 // Правая ось — подписи накопленного, чтобы шкалы не путались.
 let cumGrid='';
 for(let t=0;t<=4;t++){const v=cumTop*t/4,y=Yc(v);
  cumGrid+=`<text x="${W-pR+6}" y="${(y+4).toFixed(1)}" font-size="11" fill="#1B5E77" text-anchor="start">${(v/1e9).toLocaleString('ru-RU',{maximumFractionDigits:1})}</text>`}
 // Чьё это эскроу. Свод складывает счета очередей, а даты раскрытия у них
 // разные: в месяц первой выборки ПФ второй очереди на сводной линии стояло
 // 8,88 млрд, из которых 8,43 — деньги ПЕРВОЙ, и покрытие свода 0,58 против
 // 0,22 у самой очереди. Читалось это как «выборка второй очереди сразу
 // покрыта» (владелец, 04.09.2026: «Это деньги первой очереди или что?»).
 // Сумма верна — неверно, что она отвечает на вопрос про очередь, поэтому
 // площадь эскроу на своде разложена по очередям слоями снизу вверх.
 // Считать здесь нечего: доли приходят готовыми, экран их только рисует.
 // Число слоёв — по самой длинной строке: в первом месяце счёт может быть
 // ещё не у всех очередей, и слой пропал бы молча вместе с очередью.
 const parts=Array.from({length:Math.max(0,...data.map(x=>(x.escrow_by_phase||[]).length))});
 const layers=parts.length>1?parts.map((_,k)=>{
   const below=x=>(x.escrow_by_phase||[]).slice(0,k).reduce((a,b)=>a+Number(b||0),0);
   const upto=x=>below(x)+Number((x.escrow_by_phase||[])[k]||0);
   const top=data.map((x,i)=>pt(i,upto(x))).join(' ');
   const back=data.slice().reverse().map((x,i)=>pt(data.length-1-i,below(x))).join(' ');
   return `<polygon points="${top} ${back}" fill="#2D6A4F" fill-opacity="${(0.14+0.10*k).toFixed(2)}"`
    +` stroke="#2D6A4F" stroke-opacity="0.35" stroke-width="0.8"></polygon>`;
 }).join(''):`<polygon points="${area(x=>Number(x.escrow||0))}" fill="#2D6A4F" fill-opacity="0.30"/>`;
 // Слои названы прямо на рисунке: без подписи разделённая площадь читается
 // как одна, и общая легенда («Эскроу накоплено») отвечала бы про сумму.
 // Слои названы поимённо: «слоями по очередям» без имён не отвечает, какая
 // очередь где, — а порядок у слоёв тот же, что у очередей.
 const layerNames=((cover&&cover.phase_names)||[]).slice(0,parts.length);
 const layerNote=parts.length>1
  ? `<text x="${pL+4}" y="${pT+11}" font-size="11" fill="#2D6A4F">эскроу — слоями по очередям, снизу вверх`
    +`${layerNames.length===parts.length?': '+escapeHtml(layerNames.join(' · ')):''}</text>` : '';
 return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${grid}
  ${layers}${layerNote}
  ${gaps}
  <polyline points="${path(duty)}" fill="none" stroke="#A35D00" stroke-width="2.6"/>
  <polyline points="${path(x=>Number(x.pf_balance||0))}" fill="none" stroke="#A35D00" stroke-width="1" stroke-dasharray="4 3" opacity="0.85"/>
  <polyline points="${path(x=>Number(x.escrow||0))}" fill="none" stroke="#2D6A4F" stroke-width="2"/>
  ${repaid}${rveMark}${endMark}
  ${cumGrid}
  <text x="${pL}" y="${pT-4}" font-size="11" fill="#777" text-anchor="start">долг и эскроу, млрд ₽</text>
  <text x="${W-2}" y="${pT-4}" font-size="11" fill="#1B5E77" text-anchor="end">накопленным итогом, млрд ₽</text>
  ${marks}</svg>`;
}
function escrowCoverLines(cover){
 return ((cover&&cover.lines)||[]).map(escapeHtml).join('<br>');
}
function renderFinanceChart(rows,cover){
 const svg=escrowCoverSvg(rows,cover||{});
 financeChart.innerHTML=svg;
 const report=document.getElementById('reportEscrowChart');
 if(report)report.innerHTML=svg;
 const note=document.getElementById('escrowCoverNote');
 if(!note)return;
 // Покрытие свода не принадлежит ни одному договору: у каждой очереди свой
 // счёт эскроу и своя дата раскрытия, а ступень ставки ПФ банк считает по
 // очереди. Без этой строки сводная кривая читается как покрытие проекта.
 const phased=!!(phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.phases||[]).length>1);
 const caveat=phased
  ? 'Это СУММА очередей: у каждой свой счёт эскроу, свой долг и своя дата раскрытия. '
    +'Покрытие этой кривой не совпадает ни с одним договором — ставку ПФ банк считает по очереди. '
    +'Линии очередей — ниже.'
  : '';
 const text=[escrowCoverLines(cover),caveat].filter(Boolean).join('<br>');
 note.innerHTML=text;note.style.display=text?'':'none';
 const reportNote=document.getElementById('reportEscrowNote');
 if(reportNote){reportNote.innerHTML=text;reportNote.style.display=text?'':'none'}
 renderPhaseEscrowCharts();
}

// --- Анализ чувствительности (Tornado) ---------------------------------------
// Десятки расчётов — только по явной команде: обычная правка вводных их не
// запускает, иначе каждое нажатие в форме стоило бы секунду.
let sensitivityOptions=null, sensitivityReport=null, sensitivityPicked=null, sensitivityBusy=false;
// Рамка, под которую построены форма и последний анализ. Форма строится один
// раз, при открытии вкладки: смена типа проекта оставляла в ней жилые
// показатели и параметры (LLCR, цена квартир, спред ПФ), а в отчёте — жилой
// торнадо прошлого типа.
let sensitivityFrameKind=null;
function syncSensitivityFrame(r){
 const kind=reportLayout(r).kind||'housing';
 if(sensitivityFrameKind===null||sensitivityFrameKind===kind)return;
 sensitivityFrameKind=kind;
 sensitivityReport=null;sensitivityPicked=null;
 const res=document.getElementById('sensitivityResult');
 if(res)res.style.display='none';
 renderSensitivityForm(r);
}

async function loadSensitivityOptions(){
 if(sensitivityOptions)return sensitivityOptions;
 const response=await fetch('/analysis/sensitivity/options');
 sensitivityOptions=await response.json();
 return sensitivityOptions;
}

function sensitivityScopes(){
 const scopes=[['consolidated','Весь проект']];
 if(phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1){
  scopes.unshift(['weakest_phase','Слабейшая очередь']);
  (phasing.phases||[]).forEach((p,i)=>{if(p)scopes.push(['phase'+(i+1),'Очередь '+(p.name||('О'+(i+1)))])});
 }
 return scopes;
}

async function renderSensitivityForm(given){
 const box=document.getElementById('sensitivityControls');
 if(!box)return;
 const current=given||(typeof lastResult!=='undefined'?lastResult:null);
 sensitivityFrameKind=reportLayout(current).kind||'housing';
 const options=await loadSensitivityOptions();
 const scopes=sensitivityScopes();
 // Показатель и факторы проекта без жилья — из движка (`object_report`):
 // DSCR кредита объектов вместо LLCR, аренда, загрузка, ставка
 // капитализации, цена ДКП и ставка кредита вместо цены квартир.
 const objSens=(objectSection(current,'sensitivity')||{}).sensitivity;
 const debtKey=((reportLayout(current).debt_metric)||{}).key;
 const bankOnly=['llcr','peak_bridge_mln','pf_draw_total_mln'];
 const metrics=options.metrics.filter(m=>m.key==='dscr'?debtKey==='dscr':!(objSens&&bankOnly.includes(m.key)));
 const field=(label,html)=>`<div class="field"><label>${label}</label>${html}</div>`;
 const select=(id,pairs,current)=>`<select id="${id}">`+pairs.map(
   ([value,text])=>`<option value="${value}" ${String(value)===String(current)?'selected':''}>${escapeHtml(text)}</option>`
 ).join('')+'</select>';
 box.innerHTML=
   field('Показатель',select('sensMetric',metrics.map(m=>[m.key,m.label]),objSens?objSens.metric:'llcr'))
  +field('Что анализируем',select('sensScope',scopes,scopes[0][0]))
  +field('Отклонение процентных параметров',select('sensPct',[['5','±5%'],['10','±10%'],['20','±20%'],['custom','Своё значение']],'10'))
  +field('Отклонение сроков',select('sensMonths',[['3','±3 месяца'],['6','±6 месяцев'],['12','±12 месяцев'],['custom','Своё значение']],'6'))
  +field('Свой процент <span class="unit">%</span>','<input id="sensPctCustom" type="number" step="any" value="10" disabled>')
  +field('Свои месяцы <span class="unit">мес.</span>','<input id="sensMonthsCustom" type="number" step="1" value="6" disabled>');
 document.getElementById('sensPct').onchange=e=>{
  document.getElementById('sensPctCustom').disabled=e.target.value!=='custom';
 };
 document.getElementById('sensMonths').onchange=e=>{
  document.getElementById('sensMonthsCustom').disabled=e.target.value!=='custom';
 };
 renderSensitivityPicker(options,objSens);
}

function renderSensitivityPicker(options,objSens){
 const box=document.getElementById('sensitivityParams');
 if(!box)return;
 const groups={};
 const picked=objSens?objSens.parameters||[]:null;
 options.parameters.filter(p=>!picked||picked.includes(p.key)).forEach(p=>{(groups[p.group]=groups[p.group]||[]).push(p)});
 box.innerHTML='<p style="font-size:11px;color:#777;margin:0 0 8px">Ничего не отмечено — берутся все параметры, применимые к текущей модели. Продукты, которых нет в ТЭП, и нулевые значения не анализируются: их изменение ничего не поменяет.</p>'
  +Object.entries(groups).map(([group,list])=>
    `<div style="margin-bottom:10px"><div style="font-size:11px;font-weight:700;color:#555;margin-bottom:4px">${escapeHtml(group)}</div>`
    +list.map(p=>`<label style="display:inline-block;margin:0 14px 6px 0;font-size:12px">`
      +`<input type="checkbox" class="sens-param" value="${p.key}"${picked?' checked':''}> ${escapeHtml(p.label)}</label>`).join('')
    +'</div>').join('');
}

function sensitivityRequestBody(){
 const pct=document.getElementById('sensPct').value;
 const months=document.getElementById('sensMonths').value;
 const scope=document.getElementById('sensScope').value;
 const picked=Array.from(document.querySelectorAll('.sens-param:checked')).map(el=>el.value);
 const body={inputs,tep,rates,phasing,
   metric:document.getElementById('sensMetric').value,
   parameters:picked,
   change_pct:pct==='custom'?Number(document.getElementById('sensPctCustom').value||10):Number(pct),
   duration_change_months:months==='custom'?Number(document.getElementById('sensMonthsCustom').value||6):Number(months)};
 if(scope.startsWith('phase')){body.scope='selected';body.selected_view=scope}
 else body.scope=scope;
 return body;
}

async function runSensitivity(){
 if(sensitivityBusy)return;
 sensitivityBusy=true;
 const button=document.getElementById('sensitivityRun');
 const status=document.getElementById('sensitivityStatus');
 button.disabled=true;button.textContent='Считаю…';status.textContent='';
 try{
  const response=await fetch('/analysis/sensitivity',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(sensitivityRequestBody())});
  const report=await response.json();
  if(!response.ok)throw new Error(report.detail||'Не удалось посчитать чувствительность');
  sensitivityReport=report;
  sensitivityPicked=sensitivityRequestBody();
  renderSensitivityReport(report);
  status.textContent=`Параметров в анализе: ${report.items.length}`;
 }catch(e){
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  document.getElementById('sensitivityResult').style.display='none';
  sensitivityReport=null;
 }finally{
  button.disabled=false;button.textContent='Рассчитать чувствительность';sensitivityBusy=false;
 }
}

function sensFormat(value,digits){
 if(value==null)return '—';
 return Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
}

function renderSensitivityReport(report){
 const base=report.base;
 document.getElementById('sensitivityResult').style.display='';
 document.getElementById('sensitivityScope').textContent=base.scope_label;
 document.getElementById('sensitivityTitle').textContent=
   `${base.label}: ${sensFormat(base.value,base.digits)} ${base.unit}`.trim();
 renderTornado(report);
 const rows=report.items.map(row=>`<tr>
   <td>${escapeHtml(row.label)}</td>
   <td class="num">${sensFormat(row.base_input,row.kind==='months'?0:1)}</td>
   <td class="num">${sensFormat(row.low_input,row.kind==='months'?0:1)}</td>
   <td class="num">${sensFormat(row.high_input,row.kind==='months'?0:1)}</td>
   <td class="num">${sensFormat(row.low_result,base.digits)}</td>
   <td class="num">${sensFormat(row.high_result,base.digits)}</td>
   <td class="num"><b>${sensFormat(row.impact,base.digits)}</b></td></tr>`).join('');
 document.getElementById('sensitivityTable').innerHTML=report.items.length
  ? `<table style="margin-top:14px"><thead><tr><th>Параметр</th><th class="num">База</th>
     <th class="num">Ниже</th><th class="num">Выше</th>
     <th class="num">${escapeHtml(base.label)} ниже</th><th class="num">${escapeHtml(base.label)} выше</th>
     <th class="num">Размах</th></tr></thead><tbody>${rows}</tbody></table>`
  : '<p style="font-size:12px;color:#777">Ни один параметр не изменил показатель.</p>';
 document.getElementById('sensitivityVerdict').innerHTML=
   (report.verdict||[]).map(line=>`<p style="margin:0 0 6px">${escapeHtml(line)}</p>`).join('');
 document.getElementById('sensitivityWarnings').innerHTML=
   (report.warnings||[]).map(line=>escapeHtml(line)).join('<br>');
}

// Диаграмма своя, на SVG: тащить графическую библиотеку ради одного графика
// незачем, а печать и PDF со сторонним холстом работают хуже.
function renderTornado(report,targetId){
 // Торнадо рисуется и на вкладке чувствительности, и в отчёте: одна картинка
 // на две поверхности, чтобы экран и печать показывали одно.
 const box=document.getElementById(targetId||'sensitivityChart');
 if(!box)return;
 const items=report.items.slice(0,14);
 if(!items.length){box.innerHTML='';return}
 const base=report.base.value, digits=report.base.digits;
 const values=[base];
 items.forEach(row=>{[row.low_result,row.high_result].forEach(v=>{if(v!=null)values.push(v)})});
 let lo=Math.min(...values), hi=Math.max(...values);
 if(hi-lo<1e-9){hi=lo+1}
 const pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
 const labelWidth=250, right=70, rowHeight=30, top=34;
 const width=1000, plot=width-labelWidth-right;
 const height=top+items.length*rowHeight+18;
 const x=v=>labelWidth+(v-lo)/(hi-lo)*plot;
 const parts=[`<svg class="tornado" viewBox="0 0 ${width} ${height}" role="img" aria-label="Диаграмма чувствительности">`];
 parts.push(`<text x="${labelWidth}" y="18" font-size="12" fill="#777">${escapeHtml(report.base.label)}, ${escapeHtml(report.base.unit)}</text>`);
 items.forEach((row,index)=>{
  const y=top+index*rowHeight;
  const low=row.low_result==null?base:row.low_result;
  const high=row.high_result==null?base:row.high_result;
  // Плечо рисуется от базовой линии к своему значению, поэтому случай, когда
  // рост параметра ухудшает показатель, отображается сам собой.
  [[low,'#A35D00'],[high,'#2D6A4F']].forEach(([value,color])=>{
   const from=Math.min(x(base),x(value)), to=Math.max(x(base),x(value));
   parts.push(`<rect x="${from.toFixed(1)}" y="${y}" width="${Math.max(1,to-from).toFixed(1)}" height="18" fill="${color}" opacity="0.85"><title>${escapeHtml(row.label)}: ${sensFormat(value,digits)}</title></rect>`);
  });
  parts.push(`<text x="${labelWidth-8}" y="${y+13}" font-size="11" text-anchor="end" fill="#111">${escapeHtml(row.label.length>38?row.label.slice(0,37)+'…':row.label)}</text>`);
  parts.push(`<text x="${(Math.min(x(low),x(high))-6).toFixed(1)}" y="${y+13}" font-size="10" text-anchor="end" fill="#777">${sensFormat(Math.min(low,high),digits)}</text>`);
  parts.push(`<text x="${(Math.max(x(low),x(high))+6).toFixed(1)}" y="${y+13}" font-size="10" fill="#777">${sensFormat(Math.max(low,high),digits)}</text>`);
 });
 parts.push(`<line x1="${x(base).toFixed(1)}" y1="${top-10}" x2="${x(base).toFixed(1)}" y2="${height-14}" stroke="#111" stroke-width="1.5"/>`);
 parts.push(`<text x="${x(base).toFixed(1)}" y="${height-2}" font-size="10" text-anchor="middle" fill="#111">база ${sensFormat(base,digits)}</text>`);
 parts.push('</svg>');
 box.innerHTML=parts.join('');
}

"""
