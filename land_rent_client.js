// Calculation and legal presets come from developaid_land_rent, never JS rates.
const LAND_RENT_SPEC=__DEVELOPAID_LAND_RENT_SPEC__;
function landRentResult(){return ((lastResult||{}).consolidated||lastResult||{}).land_rent||null}
function landRentSet(key,value){
 inputs[key]=value;markFieldManual('inputs.'+key);renderLandRentEditor();calculate();
}
function landRentManualRates(){
 return Array.isArray(inputs.land_rent_rates)?inputs.land_rent_rates:[];
}
function landRentRateEdit(index,value){
 const rows=landRentManualRates().map(r=>({...r}));
 while(rows.length<=index)rows.push({year:rows.length+1,rate_pct:null});
 rows[index].rate_pct=String(value).trim()===''?null:Number(String(value).replace(',','.'));
 landRentSet('land_rent_rates',rows);
}
function landRentAddYear(){
 const rows=landRentManualRates().map(r=>({...r}));
 rows.push({year:rows.length?Math.max(...rows.map(r=>Number(r.year)||0))+1:1,rate_pct:null});
 landRentSet('land_rent_rates',rows);
}
function landRentCopyPreset(){
 const p=LAND_RENT_SPEC.presets[inputs.land_rent_mode];if(!p)return;
 inputs.land_rent_rates=p.rates.map((rate,i)=>({year:i+1,rate_pct:rate}));
 inputs.land_rent_tail_rule='unknown';
 inputs.land_rent_mode='manual';
 markFieldManual('inputs.land_rent_rates');renderLandRentEditor();calculate();
}
function landRentIndexYears(){
 const signed=new Date(inputs.land_rent_contract_date||'');
 if(Number.isNaN(signed.getTime()))return [];
 const result=landRentResult();
 let finish=new Date(result&&result.rve||'');
 if(Number.isNaN(finish.getTime())){finish=new Date(inputs.project_start||'');finish.setMonth(finish.getMonth()+Number(inputs.ird_months||0)+Number(inputs.construction_months||0))}
 const from=signed.getUTCFullYear()+1,to=Number.isNaN(finish.getTime())?from:Math.min(from+99,finish.getUTCFullYear());
 return Array.from({length:Math.max(0,to-from+1)},(_,i)=>from+i);
}
function landRentIndexEdit(year,value){
 const rows=(Array.isArray(inputs.land_rent_calendar_indices)?inputs.land_rent_calendar_indices:[]).filter(r=>Number(r.year)!==year).map(r=>({...r}));
 rows.push({year,index_pct:String(value).trim()===''?null:Number(String(value).replace(',','.'))});
 inputs.land_rent_indices_origin={...(inputs.land_rent_indices_origin||{}),[year]:{source:'manual',text:'Индекс введён пользователем'}};
 landRentSet('land_rent_calendar_indices',rows.sort((a,b)=>a.year-b.year));
}
function landRentForecastIndices(){
 const value=inputs.land_rent_forecast_index_pct;
 if(value==null||value===''||!Number.isFinite(Number(value))||Number(value)<0)return;
 const rows=Array.isArray(inputs.land_rent_calendar_indices)?inputs.land_rent_calendar_indices.map(r=>({...r})):[];
 const origin={...(inputs.land_rent_indices_origin||{})};
 landRentIndexYears().forEach(year=>{
  // Only empty future cells; previously entered actual/manual values survive.
  if(year<=new Date().getUTCFullYear())return;
  const old=rows.find(r=>Number(r.year)===year);
  if(old&&old.index_pct!=null&&old.index_pct!=='')return;
  if(old)old.index_pct=Number(value);else rows.push({year,index_pct:Number(value)});
  origin[year]={source:'forecast',text:'Прогноз пользователя: '+value+'%, не нормативный индекс'};
 });
 inputs.land_rent_indices_origin=origin;
 landRentSet('land_rent_calendar_indices',rows.sort((a,b)=>a.year-b.year));
}
function renderLandRentCalendarIndices(root){
 const grid=document.createElement('div');grid.className='fields';root.appendChild(grid);
 landRentField(grid,'land_rent_mo_cadastral_unchanged','В этом сценарии кадастровая стоимость постоянна; при изменении нужен отдельный расчёт','checkbox');
 const years=landRentIndexYears(),indices=Array.isArray(inputs.land_rent_calendar_indices)?inputs.land_rent_calendar_indices:[];
 const table=document.createElement('div');table.className='scroll';
 table.innerHTML='<p class="hint">МО: базовый Кд 6% индексируется с 1 января года после заключения договора. Пустой индекс не считается нулевым.</p><table><thead><tr><th>Календарный год</th><th>Индекс, %</th><th>Источник</th></tr></thead><tbody>'+
 years.map(year=>{const entry=indices.find(r=>Number(r.year)===year)||{};const origin=(inputs.land_rent_indices_origin||{})[year]||{};return '<tr><td>'+year+'</td><td><input aria-label="Индекс МО на '+year+' год" type="number" min="0" step="any" value="'+escapeHtml(String(entry.index_pct??''))+'" onchange="landRentIndexEdit('+year+',this.value)"></td><td>'+escapeHtml(origin.text||'По договору / нормативному индексу')+'</td></tr>'}).join('')+'</tbody></table>';
 root.appendChild(table);
 landRentField(grid,'land_rent_forecast_index_pct','Мой прогноз будущих индексов, % в год','number');
 const fill=document.createElement('button');fill.type='button';fill.className='tep-refill';fill.textContent='Заполнить пустые будущие годы моим прогнозом';fill.onclick=landRentForecastIndices;root.appendChild(fill);
}
function landRentField(box,key,label,type,options){
 const wrap=document.createElement('div');wrap.className='field';
 const caption=document.createElement('label');caption.htmlFor='f_'+key;caption.textContent=label;wrap.appendChild(caption);
 let el;
 if(options){el=document.createElement('select');options.forEach(o=>{const n=document.createElement('option');n.value=o[0];n.textContent=o[1];el.appendChild(n)})}
 else{el=document.createElement('input');el.type=type||'text';if(type==='number'){el.step='any';el.min='0'}}
 el.id='f_'+key;
 if(type==='checkbox')el.checked=inputs[key]===true;else el.value=inputs[key]??(options?options[0][0]:'');
 el.onchange=()=>landRentSet(key,type==='checkbox'?el.checked:type==='number'?(el.value.trim()===''?null:Number(el.value)):el.value);
 wrap.appendChild(el);
 if(key==='land_rent_cadastral_mln')wrap.insertAdjacentHTML('beforeend',fieldOriginNote('inputs.'+key));
 box.appendChild(wrap);return el;
}
function landRentSummaryHtml(){
 const r=landRentResult();if(!r)return '<p class="hint">Введите кадастровую стоимость, начало аренды и ставки по годам.</p>';
 const lines=[...new Set([...(r.missing||[]),...(r.financial_missing||[]),...(r.notes||[])])];
 const number=v=>v==null?'не определена':money(v);
 let html='<p><b>Начислено по ставкам: '+escapeHtml(number(r.construction_total))+'</b>';
 if(r.construction_total==null&&r.known_total>0)html+=' · известная часть '+escapeHtml(number(r.known_total));
 html+='</p>';
 if(r.rve)html+='<p class="hint">Период расчёта — до '+escapeHtml(r.rve)+'. '+escapeHtml(r.cutoff_origin==='manual'?'Подтверждённая дата ввода на арендуемой земле.':'Последний ввод основных объектов общего участка.')+'</p>';
 if(r.historical)html+='<p>Денежный поток '+(r.historical.mode==='classified'?'с фактом аренды':'с сохранённым импортом')+': <b>'+escapeHtml(number(r.applied_total??r.cash_total))+'</b></p>';
 if(lines.length)html+='<p class="hint" style="color:#946000">'+lines.map(escapeHtml).join('<br>')+'</p>';
 if((r.annual_rows||[]).length)html+='<div class="scroll"><table><thead><tr><th>Год аренды</th><th>Период в проекте</th><th>'+(r.mode==='mo_housing_new_2026'?'Базовый Кд':'Ставка')+'</th><th>Сумма</th></tr></thead><tbody>'+
 r.annual_rows.map(a=>'<tr><td>'+a.year+'</td><td>'+escapeHtml(a.overlap_start)+' — '+escapeHtml(a.overlap_end)+'</td><td>'+(a.rate_pct==null?'не задана':escapeHtml(String(a.rate_pct))+'%')+'</td><td>'+escapeHtml(a.included_in_vri?'уже включён в ВРИ':number(a.amount))+'</td></tr>').join('')+'</tbody></table></div>';
 if(r.mode==='mo_housing_new_2026'){
  const rows=(r.annual_rows||[]).flatMap(a=>a.calendar_segments||[]);
  const base=LAND_RENT_SPEC.presets[r.mode].rates[0];
  html+='<details><summary>Расчётная ставка с календарными индексами</summary><table><thead><tr><th>Период</th><th>Коэффициент</th><th>Расчётная ставка</th><th>Сумма</th></tr></thead><tbody>'+rows.map(a=>'<tr><td>'+escapeHtml(a.start)+' — '+escapeHtml(a.end)+'</td><td>'+(a.index_factor==null?'не задан':escapeHtml(a.index_factor.toFixed(4)))+'</td><td>'+(a.index_factor==null?'не определена':escapeHtml((base*a.index_factor).toFixed(3))+'%')+'</td><td>'+escapeHtml(number(a.amount))+'</td></tr>').join('')+'</tbody></table></details>';
 }
 return html;
}
function renderLandRentSummary(){
 const box=document.getElementById('landRentSummary');if(box)box.innerHTML=landRentSummaryHtml();
}
function renderLandRentEditor(){
 const host=document.getElementById('vriInputGroups');if(!host)return;
 const old=document.getElementById('landRentEditor');const expanded=!old||old.open;
 if(old)old.remove();
 const root=document.createElement('details');root.id='landRentEditor';root.className='input-group';root.open=expanded;
 const title=document.createElement('summary');title.textContent='Аренда земельного участка';root.appendChild(title);
 const lead=document.createElement('p');lead.className='hint';lead.textContent='Отдельно от платы за ВРИ. Кадастровая стоимость относится только к арендуемой земле.';root.appendChild(lead);
 const grid=document.createElement('div');grid.className='fields';root.appendChild(grid);
 const mode=inputs.land_rent_mode||'unspecified';const preset=LAND_RENT_SPEC.presets[mode];
 landRentField(grid,'land_rent_mode','Как определить аренду','select',[
  ['unspecified','Условия аренды не заданы'],['not_applicable','Аренда не применяется'],
  ['manual','Ставки и условия по договору — вручную'],
  ...Object.entries(LAND_RENT_SPEC.presets).map(([key,p])=>[key,p.label])]);
 if(String(inputs.land_right||'ownership')==='ownership'){
  const own=document.createElement('p');own.className='hint';own.textContent='Выбрана собственность на землю: сохранённые ставки аренды не начисляются. Для арендованного участка выберите право «Аренда».';root.appendChild(own);
 }
 if(mode!=='unspecified'&&mode!=='not_applicable'){
  landRentField(grid,'land_rent_cadastral_mln','Кадастровая стоимость арендуемой земли, млн ₽','number');
  landRentField(grid,'land_rent_regime_start','Начало срока / строительного режима по договору','date');
  landRentField(grid,'land_rent_manual_cutoff','Дата последнего ввода на арендуемой земле (если подтверждена отдельно)','date');
  if(preset){
   const source=document.createElement('p');source.className='hint';source.textContent=preset.source+'. '+preset.condition;root.appendChild(source);
   landRentField(grid,'land_rent_preset_confirmed','Подтверждаю применимость указанных условий к договору','checkbox');
  }else{
   landRentField(grid,'land_rent_source','Основание ставок: договор / пункт / дата','text');
   landRentField(grid,'land_rent_base_kind','База для годовых ставок','select',[
    ['cadastral_percent','Кадастровая стоимость × ставка, %'],['annual_amount','Годовая сумма договора × доля, %']]);
   if(inputs.land_rent_base_kind==='annual_amount')landRentField(grid,'land_rent_annual_base_mln','Годовая сумма по договору, млн ₽ (100%)','number');
  }
  if(mode==='mo_housing_new_2026'){
   landRentField(grid,'land_rent_contract_date','Дата заключения договора','date');
   landRentField(grid,'land_rent_public_scope','Чья земля','select',[
    ['','Не подтверждено'],['regional','Собственность Московской области'],['undelimited','Государственная собственность не разграничена'],['municipal','Муниципальная — отдельный акт / вручную']]);
   landRentField(grid,'land_rent_grant_basis','Основание предоставления','select',[
    ['','Не подтверждено'],['ordinary_nonauction','Обычное предоставление без торгов, вне специальных правил КРТ'],['special','Аукцион / КРТ / иное специальное основание']]);
   if(typeof renderLandRentCalendarIndices==='function')renderLandRentCalendarIndices(root);
  }
  const table=document.createElement('div');table.className='scroll';
  const rates=preset?preset.rates.map((v,i)=>({year:i+1,rate_pct:v})):landRentManualRates();
  table.innerHTML='<table><thead><tr><th>Год срока аренды</th><th>Годовая ставка, %</th></tr></thead><tbody>'+
   rates.map((r,i)=>'<tr><td>'+escapeHtml(String(r.year))+'</td><td><input aria-label="Ставка за '+escapeHtml(String(r.year))+' год" type="number" min="0" step="any" '+(preset?'readonly ':'')+'value="'+escapeHtml(String(r.rate_pct??''))+'" '+(preset?'':'onchange="landRentRateEdit('+i+',this.value)"')+'></td></tr>').join('')+'</tbody></table>';
  root.appendChild(table);
  const add=document.createElement('button');add.type='button';add.className='tep-refill';add.textContent=preset?'Изменить ставки вручную':'+ Год аренды';add.onclick=preset?landRentCopyPreset:landRentAddYear;root.appendChild(add);
  if(preset){const tail=document.createElement('p');tail.className='hint';tail.textContent=mode==='mo_housing_new_2026'?'Базовый Кд 6%; итог зависит от календарных индексов.':'После таблицы до ввода: '+preset.tail_rate_pct+'% (только в пределах выбранного режима).';root.appendChild(tail)}
  else landRentField(grid,'land_rent_tail_rule','После последнего заданного года','select',[
   ['unknown','Не определено — запросить ставку'],['repeat_last','Продолжать последнюю ставку (моё допущение)']]);
  const details=document.createElement('details');const heading=document.createElement('summary');heading.textContent='Оплата, первый год и период после ввода';details.appendChild(heading);root.appendChild(details);
  const extra=document.createElement('div');extra.className='fields';details.appendChild(extra);
  landRentField(extra,'land_rent_first_year_relation','Первый год и ВРИ','select',[
   ['regular_only','Здесь обычная аренда; состав повышенной части уточняется отдельно'],
   ['full_year_in_vri','Вся аренда первого года уже включена в сумму ВРИ']]);
  if(inputs.land_rent_first_year_relation==='full_year_in_vri')landRentField(extra,'land_rent_first_year_confirmed','Подтверждаю: в ВРИ включены и обычная аренда, и повышенная часть первого года','checkbox');
  if(preset&&preset.region==='msk'){
   landRentField(extra,'land_rent_premium_status','Повышенная часть первого года (приложение 8 к 273-ПП)','select',[
    ['unknown','Состав ещё не подтверждён'],['in_vri','Включена в указанную сумму ВРИ'],
    ['separate_required','Требуется отдельный расчёт'],['not_applicable','Не применяется по подтверждённому основанию']]);
   landRentField(extra,'land_rent_premium_source','Источник состава ВРИ / основание неприменения повышенной части','text');
  }
  landRentField(extra,'land_rent_payment_mode','Когда оплачиваем аренду','select',[
   ['monthly_estimate','Плановое начисление помесячно (оценка)'],['manual','По датам и суммам договора']]);
  if(inputs.land_rent_payment_mode==='manual'){
   const payment=document.createElement('div');details.appendChild(payment);
   renderScheduleEditor(payment,'land_rent_payment_schedule',{value:'money_or_share',anchor:'project_start',value_label:'Оплата',when_label:'Месяц оплаты',empty_label:'График должен точно сходиться с рассчитанной арендой.'});
  }
  const after=document.createElement('p');after.className='hint';after.textContent='После ввода нужен отдельный расчёт аренды. Дата ввода сама по себе не прекращает обязательство.';details.appendChild(after);
  landRentField(extra,'land_rent_termination_date','Подтверждённая дата прекращения аренды (если есть)','date');
  if(!preset)landRentField(extra,'land_rent_vat_treatment','НДС по договору','select',[
   ['unknown','Налоговые условия не подтверждены'],['public_exempt','Публичная земля, платёж в бюджет: освобождение (ст. 149 НК)'],['taxable','Аренда с НДС по договору (суммы включают НДС)']]);
  const convention=document.createElement('p');convention.className='hint';convention.textContent=LAND_RENT_SPEC.convention;details.appendChild(convention);
 }
 const result=document.createElement('div');result.id='landRentSummary';result.innerHTML=landRentSummaryHtml();root.appendChild(result);host.appendChild(root);
}
