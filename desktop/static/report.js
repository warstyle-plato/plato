'use strict';
const percentage=n=>n==null?'—':`${fmt(n*100,2)} %`;
const reportDate=d=>d?String(d).slice(0,10).split('-').reverse().join('.'):'—';
function reportTable(host,headings,rows){const wrap=text('div','','table-scroll'),table=document.createElement('table');table.className='report-table';const head=table.createTHead().insertRow();headings.forEach(h=>head.append(text('th',h)));for(const values of rows){const row=table.insertRow();values.forEach((value,i)=>{const cell=row.insertCell();cell.textContent=value??'—';if(i)cell.className='number';});}if(!rows.length){const cell=table.insertRow().insertCell();cell.colSpan=headings.length;cell.textContent='Данных в этом расчёте нет.';}wrap.append(table);host.append(wrap);}
function reportSection(host,title,open=false){const section=document.createElement('details');section.className='report-section';section.open=open;section.append(text('summary',title));const body=text('div','','report-section-body');section.append(body);host.append(section);return body;}
function renderDesktopReport(){const host=$('#resultBody');host.replaceChildren();const r=state.snapshot?.result;
  if(!r){host.append(text('p','Заполните параметры и нажмите «Рассчитать».','empty'));$('#cashflowBody').textContent='Данные появятся после расчёта.';return;}
  host.classList.remove('empty');const verdict=text('div','','result-verdict');verdict.append(text('strong',r.verdict?.title||'Расчёт выполнен'),text('p',r.verdict?.text||''));host.append(verdict);
  const k=r.kpi||{},f=r.financing||{};
  const summary=reportSection(host,'Экономика и эффективность',true);
  metricRows(summary,[['Выручка',money(k.revenue)],['CAPEX',money(k.capex)],['Коммерческие расходы',money(k.commercial_costs)],['Полные расходы',money(k.total_expenses)],['EBITDA',money(k.ebitda)],['Проценты и комиссии',money(k.financing_cost)],['Прибыль до налога',money(k.profit_before_tax)],['Налог на прибыль',money(k.profit_tax)],['Чистая прибыль',money(k.net_profit)],['Маржинальность',percentage(k.margin)],['NPV',money(k.npv)],['IRR собственного капитала',percentage(k.irr_equity)],['LLCR',k.llcr==null?'—':`${fmt(k.llcr,2)}×`]]);
  const products=reportSection(host,'Продукты и выручка');
  reportTable(products,['Продукт','Объём продаж','Средняя цена, тыс. ₽/ед.','Выручка, млн ₽'],(r.revenue?.products||[]).filter(x=>!['kindergarten','school','clinic','other_mandatory'].includes(x.key)&&(x.quantity||x.revenue||x.gns)).map(x=>[x.label,`${fmt(x.quantity)} ${x.unit||''}`,fmt(x.avg_price_th,2),fmt(x.revenue/1e6)]));
  const tep=reportSection(host,'ТЭП и передаваемые площади');
  reportTable(tep,['Продукт','ГНС, м²','Общая, м²','Полезная, м²','Продаваемая, м²','Передаваемая, м²','Кол-во, шт.'],(r.tep?.rows||[]).filter(x=>x.gns||x.units||x.transfer).map(x=>[x.label,...['gns','total_area','useful','saleable','transfer','units'].map(key=>fmt(x[key]))]));
  const expense=reportSection(host,'Структура расходов');
  reportTable(expense,['Статья','Сумма, млн ₽','Доля','На продаваемый м², тыс. ₽'],(r.capex?.structure||[]).map(x=>[x.label,fmt(x.value/1e6),percentage(x.share),fmt(x.per_saleable_th,2)]));
  const construction=reportSection(host,'Затраты на строительство');
  reportTable(construction,['Статья','Сумма, млн ₽','На м² ГНС, тыс. ₽','На продаваемый м², тыс. ₽'],(r.capex?.construction||[]).map(x=>[x.label,fmt(x.value/1e6),fmt(x.per_gns_th,2),fmt(x.per_saleable_th,2)]));
  const units=reportSection(host,'Экономика на квадратный метр');
  reportTable(units,['Показатель','Всего, млн ₽','На м² ГНС, тыс. ₽','На продаваемый м², тыс. ₽'],(r.unit_economics||[]).map(x=>[x.label,fmt(x.total/1e6),fmt(x.per_gns_th,2),fmt(x.per_saleable_th,2)]));
  const finance=reportSection(host,'Финансирование: БРИДЖ, ПФ и эскроу');
  metricRows(finance,[['Расчётный БРИДЖ',money(f.calculated_bridge)],['Фактический пик БРИДЖа',money(f.actual_bridge)],['Пик БРИДЖа с капитализацией',money(f.bridge_peak_capitalized)],['Лимит ПФ',money(f.pf_limit)],['Пик тела ПФ',money(f.pf_peak)],['Пик ПФ без покрытия эскроу',money(f.pf_uncovered_peak)],['Средняя ставка ПФ',percentage(f.avg_pf_rate)],['Стоимость финансирования',money(f.interest_and_fees)],['Раскрытие эскроу при вводе',money(f.rve_escrow_release)],['Погашение ПФ при вводе',money(f.rve_pf_repayment)],['Недостаток эскроу для погашения ПФ при вводе',money(f.rve_pf_shortfall)],['Остаток ПФ в конце проекта',money(f.ending_pf)]]);
  reportTable(finance,['Состав фактического БРИДЖа','Сумма, млн ₽','Доля'],(f.actual_bridge_structure||[]).map(x=>[x.label,fmt(x.value/1e6),percentage(x.share)]));
  const social=reportSection(host,'Земельные права и социальная нагрузка');const vri=r.vri?.totals||{},program=r.social?.program||{};
  metricRows(social,[['Смена ВРИ / земельные права',money(vri.amount)],['Собственные средства на земельные права',money(vri.cash)],['БРИДЖ на земельные права',money(vri.bridge)],['ПФ на земельные права',money(vri.pf)],['Социальная нагрузка',money(r.social?.payment)],['Режим',r.social?.payment_mode||'—'],['ДОО, мест',fmt(program.kindergarten_places)],['Школа, мест',fmt(program.school_places)],['Поликлиника, посещений в смену',fmt(program.clinic_capacity)]]);
  const calendar=reportSection(host,'Календарь проекта');reportTable(calendar,['Этап','Начало','Окончание'],(r.calendar?.events||[]).map(x=>[x.label,reportDate(x.start),reportDate(x.end)]));
  const queues=reportSection(host,'Результаты по очередям');reportTable(queues,['Очередь','Выручка, млн ₽','Расходы, млн ₽','Прибыль, млн ₽','LLCR'],(r.queues||[]).map(x=>[x.name,fmt(x.kpi?.revenue==null?null:x.kpi.revenue/1e6),fmt(x.kpi?.total_expenses==null?null:x.kpi.total_expenses/1e6),fmt(x.kpi?.net_profit==null?null:x.kpi.net_profit/1e6),fmt(x.kpi?.llcr,2)]));
  if(r.warnings?.length){const section=reportSection(host,'Замечания движка',true),ul=text('ul','','warnings');r.warnings.forEach(w=>ul.append(text('li',w)));section.append(ul);}
  renderDesktopCashflow(r.monthly||{});
}
function renderDesktopCashflow(m){const host=$('#cashflowBody');host.replaceChildren();host.classList.remove('empty');
  const finance=new Map((m.finance_months||[]).map((date,i)=>[String(date).slice(0,7),i]));
  const months=m.months||[];const detail=m.detail||{};
  const rows=[];const add=(label,values,axis=months,percent=false)=>{if(!Array.isArray(values))return;const index=axis===months?null:finance;
    rows.push([label,...months.map((month,i)=>{const n=values[index?index.get(String(month).slice(0,7)):i];return n==null?'—':percent?percentage(n):fmt(n/1e6,2);})]);};
  add('Поток проекта',m.cashflow_project);add('Поток собственного капитала',m.cashflow_equity);add('Налог на прибыль',m.profit_tax);
  for(const [key,label]of [['bridge_draw','Привлечение БРИДЖа'],['bridge_repayment','Погашение БРИДЖа'],['bridge_balance','Остаток БРИДЖа'],['bridge_interest','Проценты БРИДЖа'],['bridge_capitalization','Капитализация БРИДЖа'],['pf_draw','Привлечение ПФ'],['pf_repayment','Погашение ПФ'],['pf_balance','Остаток ПФ'],['pf_interest','Проценты ПФ'],['pf_interest_capitalization','Капитализация процентов ПФ'],['escrow','Эскроу'],['limit_fee','Комиссия за лимит'],['interest_payment','Выплата процентов']])add(label,m[key],m.finance_months);
  for(const [key,label]of [['key_rate','Ключевая ставка, %'],['bridge_rate','Ставка БРИДЖа, %'],['pf_rate','Ставка ПФ, %'],['coverage','Покрытие эскроу, %']])add(label,m[key],m.finance_months,true);
  const detailMonths=detail.months||months;
  // Detail and finance are aligned by their own dates, never just by array position.
  function addDetail(label,values){if(!Array.isArray(values))return;const positions=new Map(detailMonths.map((d,i)=>[String(d).slice(0,7),i]));rows.push([label,...months.map(d=>{const n=values[positions.get(String(d).slice(0,7))];return n==null?'—':fmt(n/1e6,2);})]);}
  for(const x of detail.costs||[])addDetail(x.label,x.values);
  addDetail("CAPEX — всего",detail.capex_total);addDetail("Коммерческие расходы",detail.commercial_costs);
  for(const x of detail.revenue||[])addDetail(`Продажи · ${x.label}`,x.values);
  reportTable(host,['Показатель',...months.map(d=>String(d).slice(0,7))],rows);host.querySelector('table').classList.add('cash-table');
}
