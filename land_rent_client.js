// Calculation and legal presets come from developaid_land_rent, never JS rates.
const LAND_RENT_SPEC=__DEVELOPAID_LAND_RENT_SPEC__;
let landRentRedrawQueued=false;
let landRentNeedsRedraw=false;
function landRentResult(){return ((lastResult||{}).consolidated||lastResult||{}).land_rent||null}
let landRentAppliedTerritoryKey=null;
let landRentCalculatedTerritoryKey;
function landRentMoTerritoryKey(record){
 const numbers=(record?.vri?.parcels||[]).map(p=>String(p.cadastral_number||'')).filter(n=>CADASTRAL_NUMBER_RE.test(n));
 return numbers.length?[...new Set(numbers)].sort().join('|'):'';
}
function landRentTerritory(){
 const accepted=[];
 const msk=inputs._glavapu_import;
 if(msk?.mappings&&msk.normalized&&(msk.normalized.cadastral_quarter||(msk.recognized||[]).length))accepted.push({region:'msk',label:'Москва',source:'Применённая территория ГлавАПУ',key:'msk:'+JSON.stringify([msk.normalized.cadastral_quarter,msk.recognized||[],msk.normalized.site_area_ha]),numbers:(msk.recognized||[]).map(String).filter(n=>CADASTRAL_NUMBER_RE.test(n))});
 const mo=inputs._mo_calc;
 const moNumbers=landRentMoTerritoryKey(mo).split('|').filter(Boolean);
 if(moNumbers.length)accepted.push({region:'mo',label:'Московская область',source:'Применённый расчёт по участкам',key:'mo:'+moNumbers.join('|'),record:mo,numbers:moNumbers});
 const other=inputs._other_region;
 if(other?.numbers?.length&&other.region)accepted.push({region:'other',label:other.region,source:'Применённый участок ЕГРН',key:'other:'+other.numbers.slice().sort().join('|'),record:other,numbers:other.numbers});
 if(accepted.length!==1)return {region:null,label:'Регион участка ещё не подтверждён',source:'Примените данные участка в разделе ТЭП',key:null};
 const result=accepted[0];
 if(classRegion()!==result.region)return {region:null,label:'Регион проекта отличается от применённого участка',source:'Проверьте данные участка в разделе ТЭП',key:null};
 return result;
}
function landRentSyncTerritory(){
 const territory=landRentTerritory();
 if(withoutHousing()&&LAND_RENT_SPEC.presets[inputs.land_rent_mode]){
  inputs.land_rent_mode='manual';inputs.land_rent_preset_confirmed=false;
 }
 if(!territory.key)return territory;
 if(landRentAppliedTerritoryKey&&landRentAppliedTerritoryKey!==territory.key){
  inputs.land_rent_preset_confirmed=false;
  if(LAND_RENT_SPEC.presets[inputs.land_rent_mode]?.region!==territory.region&&LAND_RENT_SPEC.presets[inputs.land_rent_mode])inputs.land_rent_mode='unspecified';
 }
 landRentAppliedTerritoryKey=territory.key;
 if(!inputs.land_rent_mode||inputs.land_rent_mode==='unspecified'){
  inputs.land_rent_mode=withoutHousing()?'manual':territory.region==='msk'?'msk_mkd_3_2':territory.region==='mo'?'mo_housing_new_2026':'manual';
  inputs.land_rent_preset_confirmed=false;
 }
 landRentFillCadastral(territory);
 return territory;
}
// Parcels of the applied territory with their cadastral value from ЕГРН. The
// Moscow Region calculation also knows each parcel's value after the VRI change.
function landRentParcels(territory){
 if(!territory?.key)return [];
 const seen=new Set(),valid=n=>CADASTRAL_NUMBER_RE.test(n)&&!seen.has(n)&&seen.add(n);
 const value=v=>v==null||v===''||!Number.isFinite(Number(v))||Number(v)<=0?null:Number(v);
 const mo=territory.region==='mo'?(territory.record?.vri?.parcels||[]):[];
 if(mo.length)return mo.filter(p=>valid(String(p.cadastral_number||''))).map(p=>({number:String(p.cadastral_number),
  current_mln:value(p.cadastral_value_rub)==null?null:Number(p.cadastral_value_rub)/1e6,
  target_mln:value(p.cadastral_value_new_rub)==null?null:Number(p.cadastral_value_new_rub)/1e6}));
 const other=territory.region==='other'?territory.record:null;
 if(other?.parcels?.length)return other.parcels.filter(p=>valid(String(p.cadastral_number||''))).map(p=>({number:String(p.cadastral_number),current_mln:value(p.cadastral_value_mln),target_mln:null}));
 // An older saved territory keeps only the total: one value for all its parcels.
 if(other&&(territory.numbers||[]).length===1&&value(other.cadastral_value_mln)!=null)return [{number:String(territory.numbers[0]),current_mln:value(other.cadastral_value_mln),target_mln:null}];
 const wanted=new Set(territory.numbers||[]);
 return ((inputs._land_lookup||{}).results||[]).filter(x=>x&&x.found&&x.kind==='land'&&(!wanted.size||wanted.has(String(x.cadastral_number)))&&valid(String(x.cadastral_number||'')))
  .map(x=>({number:String(x.cadastral_number),current_mln:value(x.cadastral_value_mln),target_mln:null}));
}
const LAND_RENT_AUTO_FIELDS=['land_rent_cadastral_mln','land_rent_cadastral_target_mln'];
function landRentOwnOrigin(path){
 const o=(inputs._field_origin||{})[path];
 return !o||o.kind==='land_rent_egrn'||/^ЕГРН принятого арендуемого участка/.test(o.text||'');
}
// The value is the sum over the leased parcels, recomputed while the owner has
// not typed it. A parcel without a value in ЕГРН leaves the sum unknown, not partial.
function landRentFillCadastral(territory){
 if(inputs.land_right!=='lease'||(inputs.land_rent_base_kind||'cadastral_percent')!=='cadastral_percent')return;
 const parcels=landRentParcels(territory),excluded=new Set(inputs.land_rent_parcels_excluded||[]);
 const leased=parcels.filter(p=>!excluded.has(p.number)),out=parcels.filter(p=>excluded.has(p.number));
 const fill=(key,field,label)=>{
  const path='inputs.'+key;
  if(!landRentOwnOrigin(path))return;
  if(!leased.length||leased.some(p=>p[field]==null)){
   if((inputs._field_origin||{})[path]){inputs[key]=null;delete inputs._field_origin[path]}
   return;
  }
  inputs[key]=Math.round(leased.reduce((sum,p)=>sum+p[field],0)*1000)/1000;
  fieldOrigins()[path]={source:'document',kind:'land_rent_egrn',
   text:label+' '+leased.map(p=>p.number).join(', ')+(out.length?'. Не в аренде: '+out.map(p=>p.number).join(', '):'')};
 };
 fill('land_rent_cadastral_mln','current_mln','Из ЕГРН: сумма кадастровой стоимости участков');
 if(Number(inputs.land_rights_cost_mln||0)>0)fill('land_rent_cadastral_target_mln','target_mln','Из расчёта смены ВРИ: стоимость после смены ВРИ, сумма по участкам');
}
function landRentParcelToggle(number,leased){
 const excluded=new Set(inputs.land_rent_parcels_excluded||[]);
 if(leased)excluded.delete(number);else excluded.add(number);
 inputs.land_rent_parcels_excluded=[...excluded].sort();
 landRentRefresh(true);
}
function landRentRefresh(rebuild=false){
 landRentNeedsRedraw=landRentNeedsRedraw||rebuild;
 if(landRentRedrawQueued)return;
 landRentRedrawQueued=true;
 queueMicrotask(()=>{landRentRedrawQueued=false;const redraw=landRentNeedsRedraw;landRentNeedsRedraw=false;if(redraw)renderLandRentEditor();calculate()});
}
function landRentSet(key,value){
 if(key==='land_rent_mode'&&value!==inputs.land_rent_mode)inputs.land_rent_preset_confirmed=false;
 inputs[key]=value;
 // A cleared cadastral value goes back to the sum from ЕГРН.
 const refill=LAND_RENT_AUTO_FIELDS.includes(key)&&value==null;
 if(refill)delete fieldOrigins()['inputs.'+key];else markFieldManual('inputs.'+key);
 landRentRefresh(refill||['land_rent_mode','land_rent_base_kind','land_rent_first_year_relation','land_rent_payment_mode','land_rent_contract_date'].includes(key));
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
 inputs.land_rent_preset_confirmed=false;
 markFieldManual('inputs.land_rent_rates');landRentRefresh(true);
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
 const grid=document.createElement('div');grid.className='fields lr-fields';root.appendChild(grid);
 const years=landRentIndexYears(),indices=Array.isArray(inputs.land_rent_calendar_indices)?inputs.land_rent_calendar_indices:[];
 const table=document.createElement('div');table.className='scroll lr-index-table';
 table.innerHTML='<p class="lr-note">МО: базовая ставка '+escapeHtml(landRentPercent(LAND_RENT_SPEC.presets.mo_housing_new_2026.rates[0]))+' индексируется с 1 января года после заключения договора. Пустой индекс не считается нулевым.</p><table><thead><tr><th>Календарный год</th><th>Индекс, %</th><th>Источник</th></tr></thead><tbody>'+
 years.map(year=>{const entry=indices.find(r=>Number(r.year)===year)||{};const origin=(inputs.land_rent_indices_origin||{})[year]||{};return '<tr><td>'+year+'</td><td><input data-land-rent-index="'+year+'" aria-label="Индекс МО на '+year+' год" type="number" min="0" step="any" value="'+escapeHtml(String(entry.index_pct??''))+'" onchange="landRentIndexEdit('+year+',this.value)"></td><td class="lr-index-origin">'+escapeHtml(entry.index_pct==null||entry.index_pct===''?'Индекс не задан':origin.text||'Источник индекса не указан')+'</td></tr>'}).join('')+'</tbody></table>';
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
 el.dataset.inputOwner='land-rent';
 if(type==='checkbox')el.checked=inputs[key]===true;else el.value=inputs[key]??(options?options[0][0]:'');
 el.onchange=()=>landRentSet(key,type==='checkbox'?el.checked:type==='number'?(el.value.trim()===''?null:Number(el.value)):el.value);
 wrap.appendChild(el);
 if(LAND_RENT_AUTO_FIELDS.includes(key)||key==='land_rent_annual_base_mln')wrap.insertAdjacentHTML('beforeend',fieldOriginNote('inputs.'+key));
 box.appendChild(wrap);return el;
}
function landRentMoney(value){
 if(value==null||!Number.isFinite(Number(value)))return 'Не определено';
 const v=Number(value),scale=Math.abs(v)>=1e6?1e6:Math.abs(v)>=1e3?1e3:1;
 return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(v/scale)+(scale===1e6?' млн ₽':scale===1e3?' тыс. ₽':' ₽');
}
function landRentDate(value){
 const match=/^(\d{4})-(\d{2})-(\d{2})/.exec(String(value||''));
 return match?match[3]+'.'+match[2]+'.'+match[1]:'Не задана';
}
function landRentPercent(value){return value==null?'Не задана':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:4}).format(Number(value))+'%'}
function landRentSourceLabel(preset){return preset?(preset.short_source||preset.source):String(inputs.land_rent_source||'Источник договора не указан')}
function landRentShownResult(){
 const territory=landRentTerritory();
 if(landRentCalculatedTerritoryKey!==undefined&&landRentCalculatedTerritoryKey!==territory.key)return null;
 const r=landRentResult();return r&&r.mode===(inputs.land_rent_mode||'unspecified')?r:null;
}
function landRentPhased(){
 const r=landRentResult();
 return r?.cutoff_origin==='phases'||(typeof phasing!=='undefined'&&!!phasing.enabled&&Number(phasing.phase_count||1)>1);
}
function landRentPhaseHtml(r){
 const land=r?.phase_land||[];
 if(land.length<2)return 'Даты ввода очередей и их доли появятся после расчёта.';
 const names=typeof phasing!=='undefined'?phasing.phases||[]:[];
 return land.map((p,i)=>'<li>'+escapeHtml((names[i]||{}).name||('Очередь '+(i+1)))+': доля земли '+escapeHtml(new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(100*Number(p.share)))+'%, в аренде до '+escapeHtml(landRentDate(p.rve))+', аренда '+escapeHtml(landRentMoney(p.cash_total))+'</li>').join('');
}
function landRentReasons(r){return [...new Set([...(r?.missing||[]),...(r?.financial_missing||[]),...(r?.notes||[])])]}
function landRentPrimaryReason(r){
 return r?.financial_missing?.[0]||r?.missing?.[0]||(r?.post_rve_unknown?'После ввода нужен отдельный расчёт аренды.':
  (r?.financial_missing_codes||[]).includes('vat')?'Налоговые условия аренды ещё не подтверждены.':
  (r?.financial_missing_codes||[]).includes('payments')?'Сроки оплаты по договору ещё не подтверждены.':landRentReasons(r)[0]||'Уточните условия договора и оплаты.');
}
function landRentSummaryHtml(){
 const r=landRentShownResult(),mode=inputs.land_rent_mode||'unspecified',preset=LAND_RENT_SPEC.presets[mode];
 const total=r?.construction_total;
 const preliminary=r&&r.status!=='not_applicable'&&r.financial_complete!==true;
 let html='<div class="kpis lr-hero"><div class="kpi"><span class="lr-eyebrow">Начислено по ставкам:</span><b class="lr-amount" title="'+escapeHtml(total==null?'Сумма ещё не определена':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(total)+' ₽')+'">'+escapeHtml(landRentMoney(total))+'</b>';
 if(total==null&&r?.known_total>0)html+='<div class="lr-note">Известная часть: '+escapeHtml(landRentMoney(r.known_total))+'</div>';
 html+='</div><div class="kpi lr-cutoff"><span>Расчёт до</span><b>'+escapeHtml(landRentDate(r?.rve))+'</b><small>'+(r?.cutoff_origin==='manual'?'Дата ввода, которую вы подтвердили':r?.cutoff_origin==='phases'?'Ввод последней очереди; земля каждой очереди выходит из аренды с её вводом':'Ввод последнего здания на участке')+'</small></div></div>';
 if(!r)html+='<p class="note warning lr-status">Введите условия аренды. Результат появится после расчёта.</p>';
 else if(r.status==='not_applicable')html+='<p class="lr-status">'+escapeHtml(r.source||'Аренда не применяется')+'</p>';
 else if(preliminary)html+='<div class="note warning lr-status"><b>Предварительный расчёт</b><span>'+escapeHtml(landRentPrimaryReason(r))+'</span><a href="#landRentEditor" class="lr-link" onclick="event.preventDefault();const d=this.closest(\'#landRentEditor\').querySelector(\'[data-land-rent-detail=conditions]\');if(d)d.open=true">Условия и уточнения</a></div>';
 const annual=r?.annual_rows||[],manual=mode==='manual',rates=landRentManualRates();
 let rows=annual.map(a=>({...a,editIndex:rates.findIndex(rate=>Number(rate.year)===Number(a.year))}));
 if(manual){
  rows=rates.map((rate,index)=>({...annual.find(a=>Number(a.year)===Number(rate.year)),year:rate.year,rate_pct:rate.rate_pct,editIndex:index}));
  annual.filter(a=>!rates.some(rate=>Number(rate.year)===Number(a.year))).forEach(a=>rows.push({...a,editIndex:Math.max(0,Number(a.year)-1)}));
 }
 if(mode!=='unspecified'&&mode!=='not_applicable'&&r?.status!=='not_applicable'){
  if(mode==='mo_housing_new_2026')html+='<p class="lr-note lr-index-note">Суммы включают календарные индексы. В таблице — базовая ставка.</p>';
  html+='<div class="scroll lr-table-wrap"><table class="metric-table lr-main-table"><thead><tr><th>Год аренды</th><th>'+(mode==='mo_housing_new_2026'?'Базовая ставка':'Ставка')+'</th><th>Сумма</th></tr></thead><tbody>';
  html+=rows.length?rows.map(a=>{
   const period=a.overlap_start?landRentDate(a.overlap_start)+' — '+landRentDate(a.overlap_end):'Сумма за этот год ещё не рассчитана';
   const rate=manual?'<input data-input-owner="land-rent" aria-label="Ставка за '+escapeHtml(String(a.year))+' год" type="number" min="0" step="any" value="'+escapeHtml(String(a.rate_pct??''))+'" onchange="landRentRateEdit('+a.editIndex+',this.value)"><span class="lr-percent">%</span>':escapeHtml(landRentPercent(a.rate_pct));
   const amount=a.included_in_vri?'Включён в ВРИ':a.amount===undefined&&total!=null?'Вне периода':landRentMoney(a.amount);
   return '<tr><td title="'+escapeHtml(period)+'"><b>'+escapeHtml(String(a.year))+'-й</b>'+(a.overlap_start?'<small>'+escapeHtml(String(a.overlap_start).slice(0,4))+'</small>':'')+'</td><td class="lr-rate">'+rate+'</td><td title="'+escapeHtml(a.amount==null?period:new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(a.amount)+' ₽ · '+period)+'">'+escapeHtml(amount)+'</td></tr>';
  }).join(''):'<tr><td colspan="3" class="lr-empty">Подтвердите условия договора, чтобы увидеть начисления по годам.</td></tr>';
  html+='</tbody><tfoot><tr><th colspan="2">Итого до ввода</th><th>'+escapeHtml(landRentMoney(total))+'</th></tr></tfoot></table></div><div class="lr-tools"><button type="button" class="btn" onclick="'+(preset?'landRentCopyPreset()':'landRentAddYear()')+'">'+(preset?'Изменить ставки вручную':'+ Год аренды')+'</button><span class="hint">'+escapeHtml(landRentSourceLabel(preset))+'</span></div>';
 }
 return html;
}
function renderLandRentSummary(){
 landRentCalculatedTerritoryKey=landRentTerritory().key;
 const box=document.getElementById('landRentSummary');
 if(box){
  const next=document.createElement('div');next.innerHTML=landRentSummaryHtml();
  const tools=box.querySelector('.lr-tools'),nextTools=next.querySelector('.lr-tools');
  if(tools&&nextTools){
   // Keep action buttons alive through the blur -> mousedown -> click sequence.
   for(const selector of ['.lr-hero','.lr-status','.lr-index-note','.lr-table-wrap']){
    const old=box.querySelector(selector),fresh=next.querySelector(selector);
    if(old?.contains(document.activeElement))continue;
    if(old&&fresh)old.replaceWith(fresh);
    else if(old)old.remove();
    else if(fresh){const following=selector==='.lr-status'?box.querySelector('.lr-index-note,.lr-table-wrap'):box.querySelector('.lr-table-wrap');box.insertBefore(fresh,following||tools)}
   }
   tools.querySelector('.hint').textContent=nextTools.querySelector('.hint').textContent;
  }else box.innerHTML=next.innerHTML;
 }
 const root=document.getElementById('landRentEditor');if(root)landRentRefreshDetails(root);
}
function landRentRefreshDetails(root){
 const r=landRentShownResult(),reasons=root.querySelector('.lr-reasons');
 if(reasons)reasons.innerHTML=landRentReasons(r).map(line=>'<li>'+escapeHtml(line)+'</li>').join('');
 const scope=root.querySelector('.lr-scope-result');
 if(scope)scope.textContent=r?(r.cutoff_basis||'Расчёт до ввода')+' · '+landRentDate(r.rve):'Дата расчёта появится после заполнения условий.';
 const phases=root.querySelector('.lr-phases');
 if(phases)phases.innerHTML=landRentPhaseHtml(r)+(r?.phase_share_basis_text?'<li>Доли земли посчитаны '+escapeHtml(r.phase_share_basis_text)+'.</li>':'');
 const premium=root.querySelector('.lr-premium');
 if(premium)premium.textContent=r?.premium?.derived?r.premium.source:'';
 const cash=root.querySelector('.lr-cash-result');
 if(cash)cash.textContent=r?.historical?'Денежный поток '+(r.historical.mode==='classified'?'с фактом аренды':'с сохранённым импортом')+': '+landRentMoney(r.applied_total??r.cash_total):r?'Денежный поток: '+landRentMoney(r.cash_total)+(r.cash_schedule_estimated?' · плановое начисление, сроки оплаты не подтверждены':' · по графику оплаты'):'';
 const periods=root.querySelector('.lr-periods');
 if(periods)periods.innerHTML=(r?.annual_rows||[]).map(a=>'<li>'+escapeHtml(String(a.year))+'-й год: '+escapeHtml(landRentDate(a.overlap_start))+' — '+escapeHtml(landRentDate(a.overlap_end))+'</li>').join('');
 const segments=root.querySelector('.lr-segments');
 if(segments)segments.innerHTML=(r?.annual_rows||[]).flatMap(a=>a.calendar_segments||[]).map(a=>'<li>'+escapeHtml(landRentDate(a.start))+' — '+escapeHtml(landRentDate(a.end))+': '+(a.index_factor==null?'индекс не задан':'коэффициент '+escapeHtml(new Intl.NumberFormat('ru-RU',{maximumFractionDigits:4}).format(a.index_factor)))+' · '+escapeHtml(landRentMoney(a.amount))+'</li>').join('');
 root.querySelectorAll('[data-land-rent-index]').forEach(el=>{
  const year=Number(el.dataset.landRentIndex),row=(inputs.land_rent_calendar_indices||[]).find(r=>Number(r.year)===year);
  if(document.activeElement!==el)el.value=row?.index_pct??'';
  const origin=el.closest('tr').querySelector('.lr-index-origin');if(origin)origin.textContent=row?.index_pct==null||row?.index_pct===''?'Индекс не задан':(inputs.land_rent_indices_origin||{})[year]?.text||'Источник индекса не указан';
 });
}
function landRentStyle(){
 if(document.getElementById('landRentCompactStyle'))return;
 const style=document.createElement('style');style.id='landRentCompactStyle';style.textContent=`
 #landRentEditor .lr-fields{grid-template-columns:repeat(2,minmax(0,1fr))}
 #landRentEditor .field{min-width:0}
 #landRentEditor input,#landRentEditor select{min-width:0;max-width:100%}
 #landRentEditor .lr-hero{grid-template-columns:repeat(2,minmax(0,1fr));margin:8px 0 12px}
 #landRentEditor .lr-status{margin:10px 0 14px}
 #landRentEditor .lr-status>span{display:block;margin-top:3px}
 #landRentEditor .lr-main-table{table-layout:fixed}
 #landRentEditor .lr-main-table th:first-child{width:25%}
 #landRentEditor .lr-main-table th:nth-child(2){width:29%}
 #landRentEditor .lr-main-table td{overflow-wrap:anywhere}
 #landRentEditor .lr-main-table small{display:block;font-size:11px;color:var(--muted);margin-top:3px}
 #landRentEditor .lr-rate input{width:calc(100% - 16px);padding:7px 5px}
 #landRentEditor .lr-percent{margin-left:3px}
 #landRentEditor .lr-tools{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px 0}
 #landRentEditor .lr-tools .hint{text-align:right;min-width:0;font-size:12px;line-height:1.5;color:var(--muted);overflow-wrap:anywhere}
 #landRentEditor .lr-note,#landRentEditor .lr-detail li{font-size:12px;color:var(--muted);line-height:1.5;overflow-wrap:anywhere}
 #landRentEditor .lr-detail ul{padding-left:18px}
 #landRentEditor .lr-index-table table{table-layout:fixed;min-width:0}
 #landRentEditor .lr-index-table td,#landRentEditor .lr-index-table th{overflow-wrap:anywhere;padding:8px}
 @media(max-width:640px){#landRentEditor .lr-fields{grid-template-columns:minmax(0,1fr)}#landRentEditor .kpi{padding:12px}#landRentEditor .kpi b{font-size:20px}#landRentEditor .lr-hero{grid-template-columns:1fr}#landRentEditor .lr-tools{align-items:flex-start;flex-direction:column}#landRentEditor .lr-tools .btn{white-space:normal;max-width:100%}#landRentEditor .lr-tools .hint{max-width:100%;text-align:left}}
 `;document.head.appendChild(style);
}
function renderLandRentEditor(){
 const host=document.getElementById('vriInputGroups');if(!host)return;
 landRentStyle();
 const territory=landRentSyncTerritory();
 const old=document.getElementById('landRentEditor'),expanded=!old||old.open;
 const open=new Set(old?[...old.querySelectorAll('details[data-land-rent-detail]')].filter(d=>d.open).map(d=>d.dataset.landRentDetail):[]);
 if(old)old.remove();
 const root=document.createElement('details');root.id='landRentEditor';root.className='input-group';root.open=expanded;
 const title=document.createElement('summary');title.textContent='Аренда земли';root.appendChild(title);
 const note=(parent,text)=>{const p=document.createElement('p');p.className='lr-note';p.textContent=text;parent.appendChild(p);return p};
 const fields=parent=>{const box=document.createElement('div');box.className='fields lr-fields';parent.appendChild(box);return box};
 const detail=(key,label)=>{const box=document.createElement('details');box.className='lr-detail';box.dataset.landRentDetail=key;box.open=open.has(key);const summary=document.createElement('summary');summary.textContent=label;box.appendChild(summary);root.appendChild(box);return box};
 const lead=note(root,'Начисления до ввода. Плата за ВРИ учитывается отдельно.');lead.className='lr-note lr-intro';
 note(root,territory.label+' · '+territory.source);
 const mode=inputs.land_rent_mode||'unspecified',preset=LAND_RENT_SPEC.presets[mode];
 const basis=fields(root);
 if(String(inputs.land_right||'ownership')==='ownership')note(root,'Выбрана собственность на землю: сохранённые ставки аренды не начисляются. Для арендованного участка выберите право «Аренда».');
 if(mode!=='unspecified'&&mode!=='not_applicable'){
  if(mode==='manual'&&inputs.land_rent_base_kind==='annual_amount')landRentField(basis,'land_rent_annual_base_mln','Годовая сумма по договору, млн ₽ (100%)','number');
  else{
   landRentField(basis,'land_rent_cadastral_mln','Кадастровая стоимость арендуемой земли, млн ₽','number');
  }
  landRentField(basis,'land_rent_regime_start','Начало срока аренды по договору','date');
  if(inputs.land_rent_base_kind!=='annual_amount'){
   const parcels=landRentParcels(territory),excluded=new Set(inputs.land_rent_parcels_excluded||[]);
   if(parcels.length){
    const list=document.createElement('div');list.className='lr-parcels';
    list.innerHTML='<p class="lr-note">Участки из ЕГРН. Снимите отметку с участка, который не берётся в аренду: его стоимость не войдёт в сумму.'+
     (isFieldManual('inputs.land_rent_cadastral_mln')?' Сейчас стоимость вписана вручную, поэтому отметки её не меняют. Очистите поле, чтобы вернуть сумму из ЕГРН.':'')+'</p>'+
     parcels.map(p=>'<label class="lr-parcel"><input type="checkbox" data-land-rent-parcel="'+escapeHtml(p.number)+'"'+(excluded.has(p.number)?'':' checked')+
      ' onchange="landRentParcelToggle(this.dataset.landRentParcel,this.checked)"> '+escapeHtml(p.number)+' — '+
      escapeHtml(p.current_mln==null?'в ЕГРН нет кадастровой стоимости, впишите сумму вручную':landRentMoney(p.current_mln*1e6))+'</label>').join('');
    root.appendChild(list);
   }
  }
 }
 const result=document.createElement('div');result.id='landRentSummary';result.innerHTML=landRentSummaryHtml();root.appendChild(result);
 const conditions=detail('conditions','Договор, источник и следующие ставки'),contract=fields(conditions);
  const choices=Object.entries(LAND_RENT_SPEC.presets).filter(([key,p])=>p.region===territory.region&&!withoutHousing()).map(([key,p])=>[key,p.label]);
  if(preset&&!choices.some(([key])=>key===mode))choices.push([mode,'Сохранённые условия — применимость требует проверки']);
  landRentField(contract,'land_rent_mode','Условия договора','select',[
   ['unspecified','Условия не заданы'],['manual','Ставки по договору вручную'],['not_applicable','Аренда не применяется'],...choices]);
 if(mode!=='unspecified'&&mode!=='not_applicable'){
  if(preset){
   note(conditions,preset.source+'. '+preset.condition);
   if(/^https:\/\//.test(preset.url||'')){const link=document.createElement('a');link.href=preset.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Открыть текст акта: '+preset.url_label;conditions.appendChild(link)}
   landRentField(contract,'land_rent_preset_confirmed','Ставки сверены с договором: в нём те же условия','checkbox');
   note(conditions,preset.rates.map((rate,index)=>(index+1)+'-й год: '+landRentPercent(rate)).join(' · '));
   note(conditions,mode==='mo_housing_new_2026'?'Базовая ставка '+landRentPercent(preset.rates[0])+'; сумма зависит от календарных индексов.':'После таблицы до ввода: '+landRentPercent(preset.tail_rate_pct)+' в пределах выбранного режима.');
  }else{
   landRentField(contract,'land_rent_source','Основание ставок: договор / пункт / дата','text');
   landRentField(contract,'land_rent_tail_rule','После последнего заданного года','select',[
    ['unknown','Не определено — запросить ставку'],['repeat_last','Продолжать последнюю ставку (моё допущение)']]);
   landRentField(contract,'land_rent_vat_treatment','НДС по договору','select',[
    ['unknown','Налоговые условия не подтверждены'],['public_exempt','Публичная земля, платёж в бюджет: освобождение (ст. 149 НК)'],['taxable','Аренда с НДС по договору (суммы включают НДС)']]);
  }
  landRentField(contract,'land_rent_base_kind','База для годовых ставок','select',[
   ['cadastral_percent','Кадастровая стоимость × ставка, %'],['annual_amount','Годовая сумма договора × доля, %']]);
  const reasons=document.createElement('ul');reasons.className='lr-reasons';conditions.appendChild(reasons);
  if(mode==='mo_housing_new_2026'){
   landRentField(contract,'land_rent_contract_date','Дата заключения договора','date');
   landRentField(contract,'land_rent_public_scope','Чья земля','select',[
    ['','Не подтверждено'],['regional','Собственность Московской области'],['undelimited','Государственная собственность не разграничена'],['municipal','Муниципальная — отдельный акт / вручную']]);
   landRentField(contract,'land_rent_grant_basis','Основание предоставления','select',[
    ['','Не подтверждено'],['ordinary_nonauction','Обычное предоставление без торгов, вне специальных правил КРТ'],['special','Аукцион / КРТ / иное специальное основание']]);
   const indices=detail('indices','Московская область: календарные индексы и мой прогноз');
   renderLandRentCalendarIndices(indices);
   const segments=document.createElement('ul');segments.className='lr-segments';indices.appendChild(segments);
  }
  const payment=detail('payments','Первый год, ВРИ и график оплаты'),extra=fields(payment);
  if(inputs.land_rent_base_kind!=='annual_amount'&&Number(inputs.land_rights_cost_mln||0)>0){
   landRentField(extra,'land_rent_cadastral_target_mln','Кадастровая стоимость после смены ВРИ, млн ₽','number');
   note(payment,'С даты смены ВРИ аренда считается от кадастровой стоимости после смены. Пока поле пустое, аренда до конца считается от нынешней стоимости, и расчёт остаётся предварительным.');
  }
  landRentField(extra,'land_rent_first_year_relation','Первый год и ВРИ','select',[
   ['regular_only','Здесь обычная аренда; повышенная часть уточняется отдельно'],['full_year_in_vri','Вся аренда первого года уже включена в сумму ВРИ']]);
  if(inputs.land_rent_first_year_relation==='full_year_in_vri')landRentField(extra,'land_rent_first_year_confirmed','Подтверждаю: в ВРИ включены обычная аренда и повышенная часть первого года','checkbox');
  if(preset?.region==='msk'){
   // Our VRI fee already contains the raised first-year part; only a fee
   // typed by hand needs the owner's answer (developaid_land_rent.vri_premium).
   const feeTyped=isFieldManual('inputs.land_rights_cost_mln')||!(Number(inputs.land_rights_cost_mln||0)>0);
   if(feeTyped)landRentField(extra,'land_rent_premium_status','В первый год аренды к обычной ставке добавляется повышенная часть. Входит ли она в плату за смену ВРИ?','select',[
    ['unknown','Пока не знаю'],['in_vri','Да, входит в плату за смену ВРИ'],['separate_required','Нет, её нужно посчитать отдельно'],['not_applicable','К моему договору она не применяется']]);
   const premium=note(payment,'');premium.className='lr-premium lr-note';
  }
  landRentField(extra,'land_rent_payment_mode','Когда оплачиваем аренду','select',[
   ['monthly_estimate','Плановое начисление помесячно (оценка)'],['manual','По датам и суммам договора']]);
  if(inputs.land_rent_payment_mode==='manual'){
   const schedule=document.createElement('div');payment.appendChild(schedule);
   renderScheduleEditor(schedule,'land_rent_payment_schedule',{value:'money_or_share',anchor:'project_start',value_label:'Оплата',when_label:'Месяц оплаты',empty_label:'График должен точно сходиться с рассчитанной арендой.'});
  }
  const cash=note(payment,'');cash.className='lr-cash-result lr-note';
  const scope=detail('scope','Срок расчёта и объекты на участке'),dates=fields(scope);
  const scopeResult=note(scope,'');scopeResult.className='lr-scope-result lr-note';
  if(landRentPhased()){
   note(scope,'Проект разбит на очереди: земля каждой очереди выходит из аренды с её вводом, даты берутся из настроек очередей. Аренда месяца делится между очередями, которые ещё не введены, в том числе ещё не начатыми.');
   const phases=document.createElement('ul');phases.className='lr-phases lr-note';scope.appendChild(phases);
  }else landRentField(dates,'land_rent_manual_cutoff','Дата ввода последнего здания на участке, если она известна точнее расчётной','date');
  landRentField(dates,'land_rent_termination_date','Подтверждённая дата прекращения аренды (если есть)','date');
  note(scope,'После ввода нужен отдельный расчёт аренды. Дата ввода сама по себе не прекращает обязательство.');
  note(scope,LAND_RENT_SPEC.convention);
  const periods=document.createElement('ul');periods.className='lr-periods';scope.appendChild(periods);
 }
 root.querySelectorAll('input,select,textarea').forEach(el=>el.dataset.inputOwner='land-rent');
 host.appendChild(root);landRentRefreshDetails(root);
}
