"""Кусок страницы PAGE: Скрипт: очереди строительства — доли продуктов по очередям,
финансирование очередей, социальные объекты.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_phasing")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""function currentMonetizableSaleable(){
 return Number((tep.apartments||{}).saleable||0)+Number((tep.ground_commercial||{}).saleable||0)
  +STANDALONE_OBJECTS.filter(o=>o.product==='offices'||o.product==='standalone_retail')
    .reduce((sum,o)=>sum+(inputs[o.prefix+'_enabled']?Number(inputs[o.prefix+'_saleable_sqm']||0):0),0);
}
function recommendationCount(){return Math.max(1,Math.min(5,Math.ceil(currentMonetizableSaleable()/Math.max(20000,Number(phasing.target_size_sqm||70000)))))}
function phaseOptions(selected){return phasing.phases.map((p,i)=>`<option value="${i+1}" ${Number(selected)===i+1?'selected':''}>${p.name}</option>`).join('')}
function phaseStartDate(phaseNo){
 const i=Math.max(0,Math.min(phasing.phases.length-1,Number(phaseNo||1)-1));
 const p=phasing.phases[i]||{start_offset_months:0};
 return addMonthsJS(inputs.project_start,Number(p.start_offset_months||0));
}
function normalizeSocialObjectDates(){
 if(!phasing||!Array.isArray(phasing.social_objects))return;
 phasing.social_objects.forEach(o=>{
   const phase=Math.max(1,Math.min(phasing.phases.length,Number(o.phase||1)));
   o.phase=phase;
   const phaseStart=phaseStartDate(phase);
   // Old saved objects had no start_mode and could retain dates from 2026 / another project.
   // Treat an empty or pre-phase date as automatic and bind it to the selected queue start.
   if(!o.start_mode){
     o.start_mode=(!o.start_date||String(o.start_date)<phaseStart)?'auto':'manual';
   }
   if(o.start_mode!=='manual'||!o.start_date||String(o.start_date)<phaseStart){
     o.start_date=phaseStart;
     if(String(o.start_date)<phaseStart)o.start_mode='auto';
   }
 });
}
function currentPhaseFinancingStrategy(){
 return phasing.financing_strategy||'independent';
}
function setPhaseCarryDebt(value){
 phasing.carry_debt_forward=!!value;renderPhasing();calculate();
}
// Деньги от продаж прошлых очередей копятся у застройщика, пока строится
// следующая. Банк в дату раскрытия заберёт их раньше, чем станет
// переоформлять долг: они уже на счету, а перенос — его одолжение
// (владелец, 31.08.2026). Признак, а не умолчание: книга сметания пока не
// знает, и молча они разойдутся.
function setPhaseSweepCash(value){
 phasing.sweep_project_cash=!!value;renderPhasing();calculate();
}
function setPhaseSweepPct(value){
 const v=Number(String(value).replace(',','.'));
 phasing.cash_sweep_pct=isFinite(v)?Math.min(100,Math.max(0,v)):80;
 renderPhasing();calculate();
}
function togglePhasing(v){
 if(v&&Number(phasing.phase_count||1)<=1){
   const t=phasing.target_size_sqm||70000,g=phasing.phase_gap_months||12,cinf=Number(phasing.cost_inflation_pct??8),pinf=Number(phasing.sales_price_inflation_pct??8),strategy=currentPhaseFinancingStrategy(),carry=!!phasing.carry_debt_forward,sweep=phasing.sweep_project_cash!==false,sweepPct=Number(phasing.cash_sweep_pct??80);
   phasing=makeDefaultPhasing(Math.max(2,recommendationCount()));
   phasing.target_size_sqm=t;phasing.phase_gap_months=g;phasing.cost_inflation_pct=cinf;phasing.sales_price_inflation_pct=pinf;phasing.financing_strategy=strategy;phasing.carry_debt_forward=carry;phasing.sweep_project_cash=sweep;phasing.cash_sweep_pct=sweepPct;
 }
 phasing.enabled=!!v;phasing.user_enabled=!!v;
 if(v&&!phasing.social_objects.length&&inputs.social_mode==='Строительство')autoSocialObjects(false);
 normalizeSocialObjectDates();renderInputs();renderPhasing();calculate()
}
function setPhaseCount(count){const e=phasing.enabled&&Number(count)>1,t=phasing.target_size_sqm||70000,g=phasing.phase_gap_months||12,cinf=Number(phasing.cost_inflation_pct??8),pinf=Number(phasing.sales_price_inflation_pct??8),strategy=currentPhaseFinancingStrategy(),carry=!!phasing.carry_debt_forward,sweep=phasing.sweep_project_cash!==false,sweepPct=Number(phasing.cash_sweep_pct??80);phasing=makeDefaultPhasing(Math.max(1,Math.min(5,count)));phasing.enabled=e;phasing.user_enabled=e;phasing.target_size_sqm=t;phasing.phase_gap_months=g;phasing.cost_inflation_pct=cinf;phasing.sales_price_inflation_pct=pinf;phasing.financing_strategy=strategy;phasing.carry_debt_forward=carry;phasing.sweep_project_cash=sweep;phasing.cash_sweep_pct=sweepPct;phasing.phases.forEach((p,i)=>p.start_offset_months=i*g);autoSocialObjects(false);normalizeSocialObjectDates();renderInputs();renderPhasing();calculate()}
function autoPhaseDates(){phasing.phases.forEach((p,i)=>p.start_offset_months=i*Number(phasing.phase_gap_months||12));normalizeSocialObjectDates();renderPhasing();calculate()}
function autoSuggestPhasing(){const c=recommendationCount(),cinf=Number(phasing.cost_inflation_pct??8),pinf=Number(phasing.sales_price_inflation_pct??8),strategy=currentPhaseFinancingStrategy(),carry=!!phasing.carry_debt_forward,sweep=phasing.sweep_project_cash!==false,sweepPct=Number(phasing.cash_sweep_pct??80);phasing=makeDefaultPhasing(c);phasing.enabled=c>1;phasing.user_enabled=c>1;phasing.cost_inflation_pct=cinf;phasing.sales_price_inflation_pct=pinf;phasing.financing_strategy=strategy;phasing.carry_debt_forward=carry;phasing.sweep_project_cash=sweep;phasing.cash_sweep_pct=sweepPct;phasing.target_size_sqm=Number(document.getElementById('phaseTargetSize')?.value||70000);phasing.phase_gap_months=Number(document.getElementById('phaseGap')?.value||12);phasing.phases.forEach((p,i)=>p.start_offset_months=i*phasing.phase_gap_months);autoSocialObjects(false);renderPhasing();calculate()}
function rebalancePhaseProductShares(values,index,value){
 const count=Math.max(1,Number(phasing.phase_count||values.length||1)),out=Array.from({length:count},(_,j)=>Math.max(0,Number(values[j]||0)));
 const lockedTotal=out.slice(0,index).reduce((s,x)=>s+x,0),available=Math.max(0,100-lockedTotal),rightIndexes=out.map((_,j)=>j).filter(j=>j>index);
 if(!rightIndexes.length){out[index]=available;return out}
 const edited=Math.max(0,Math.min(available,Number(value||0))),remaining=available-edited;out[index]=edited;
 const rightTotal=rightIndexes.reduce((s,j)=>s+out[j],0);
 let allocated=0;
 rightIndexes.forEach((j,pos)=>{const next=pos===rightIndexes.length-1?remaining-allocated:(rightTotal>0?remaining*out[j]/rightTotal:remaining/rightIndexes.length);out[j]=Math.max(0,Number(next.toFixed(6)));allocated+=out[j]});
 return out;
}
// Итог строки обязан говорить про то, что на экране. Пока поле в фокусе, доли
// ещё не применены: набранные 30 при остальных 25 дают 105, а ИТОГО показывало
// зелёные 100,0% от прошлого состояния — итог выглядел сошедшимся ровно тогда,
// когда строка ему противоречила (владелец, 23.08.2026). Пересчёт долей и
// метров остаётся на уходе из поля: ребаланс по каждой набранной цифре считал
// бы «3» отдельной правкой и уводил соседние очереди не туда.
function previewPhaseProductShares(key){
 const row=document.querySelector(`tr[data-share-row="${key}"]`);
 if(!row)return;
 const total=row.querySelector('[data-share-total]');
 if(!total)return;
 const shown=Array.from(row.querySelectorAll('input')).reduce((s,el)=>s+Number(el.value||0),0);
 const stored=(phasing.products[key]||[]).reduce((s,x)=>s+Number(x||0),0);
 total.className=Math.abs(shown-100)<.1?'phase-total-ok':'phase-total-bad';
 total.innerHTML=shown.toFixed(1)+'%'+(Math.abs(shown-stored)>1e-6
  ?'<br><small>не применено — нажмите Enter или уведите курсор</small>':'');
}
function setPhaseProductShare(k,i,v){
 if(!phasing.products[k])return;
 phasing.products[k]=rebalancePhaseProductShares(phasing.products[k],i,v);
 // A new percentage allocation replaces stale absolute TEP for this product.
 // Otherwise an imported/manual override masks the percentages on screen.
 phasing.phases.forEach(p=>{const product=(p.products||{})[k];if(!product)return;['gns','total_area','useful','saleable','transfer','units'].forEach(field=>delete product[field]);product.assumption_source='Распределено по долям очередей'});
 renderPhasing();calculate();
}
// Квартир, машино-мест и кладовых не бывает 412,94. Доли режут метры, а
// штуки — считаются: раскладка идёт по наибольшему остатку, чтобы сумма
// очередей сходилась со строкой проекта ровно, а не «почти» (владелец,
// 04.09.2026: «штуки квартир не могут быть дробными»). Округление каждой
// доли по отдельности этого не даёт — три очереди по 412,94 дают 1239 при
// проектных 1238, и таблица честно показывает расхождение с проектом.
function phaseIntegerSplit(master,shares,sum){
 const total=Math.round(Math.max(0,Number(master)||0));
 const raw=shares.map(v=>total*Math.max(0,Number(v||0))/(sum||1));
 const base=raw.map(v=>Math.floor(v));
 let left=total-base.reduce((s,v)=>s+v,0);
 const order=raw.map((v,i)=>[v-Math.floor(v),i]).sort((a,b)=>b[0]-a[0]);
 for(let k=0;k<order.length&&left>0;k++){base[order[k][1]]+=1;left--}
 return base;
}
function phaseProductDerived(key,field,index){
 const master=Number((tep[key]||{})[field]||0),count=Number(phasing.phase_count||1);
 // Social objects are assigned by their registry, not by the generic fallback
 // to queue 1.  Without this branch the screen showed the master capacity in
 // O1 and the explicit KRT object again in O2/O3: ДОУ 700 instead of 350 and
 // school 2,000 instead of 1,000 places.  Preserve the master total while
 // distributing every displayed field by the registered capacity.
 if(['kindergarten','school','clinic'].includes(key)){
  const registry=(phasing.social_objects||[]).filter(o=>o&&o.type===key),totalCapacity=registry.reduce((s,o)=>s+Math.max(0,Number(o.capacity||0)),0);
  if(registry.length){
   const phaseCapacity=registry.filter(o=>Number(o.phase||1)===index+1).reduce((s,o)=>s+Math.max(0,Number(o.capacity||0)),0);
   return field==='units'?phaseCapacity:(totalCapacity>0?master*phaseCapacity/totalCapacity:0);
  }
 }
 if(phasing.products[key]){
  const a=(phasing.products[key]||phaseWeightPreset(count)).slice(0,count),sum=a.reduce((s,v)=>s+Number(v||0),0)||100;
  if(field==='units')return phaseIntegerSplit(master,a,sum)[index]||0;
  return master*Number(a[index]||0)/sum;
 }
 const assigned=discreteDefaults(count)[key]||1;
 return index+1===Number((phasing.discrete||{})[key]||assigned)?master:0;
}
let phaseTepEditWarning='';
function phaseProductTepValues(key,field){
 return phasing.phases.map((p,i)=>{const own=(p.products||{})[key]||{};return Math.max(0,Number(own[field]!==undefined?own[field]:phaseProductDerived(key,field,i)))});
}
function phaseProductTepLimit(key,field,index){
 const master=Math.max(0,Number((tep[key]||{})[field]||0));
 if(!(master>0))return null;
 const locked=phaseProductTepValues(key,field).slice(0,index).reduce((s,x)=>s+x,0);
 return Math.max(0,master-locked);
}
function clampPhaseProductTepRight(key,field,index){
 const master=Math.max(0,Number((tep[key]||{})[field]||0));if(!(master>0))return;
 const values=phaseProductTepValues(key,field),used=values.slice(0,index+1).reduce((s,x)=>s+x,0),remaining=Math.max(0,master-used),rightIndexes=values.map((_,i)=>i).filter(i=>i>index),rightTotal=rightIndexes.reduce((s,i)=>s+values[i],0);
 if(rightTotal<=remaining+1e-6)return;
 let allocated=0;
 rightIndexes.forEach((i,pos)=>{const next=pos===rightIndexes.length-1?remaining-allocated:remaining*values[i]/rightTotal;const phase=phasing.phases[i];if(!phase.products)phase.products={};if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};phase.products[key][field]=Math.max(0,Number(next.toFixed(6)));allocated+=phase.products[key][field]});
}
function syncPhaseProductSharesFromTep(key,field,index){
 if(!phasing.products[key])return;
 const values=phaseProductTepValues(key,field),total=values.reduce((s,x)=>s+x,0);
 if(total<=0)return;
 const master=Math.max(0,Number((tep[key]||{})[field]||0));
 if(master>0){phasing.products[key]=rebalancePhaseProductShares(phasing.products[key],index,values[index]/master*100);phasing.phases.forEach(p=>{const product=(p.products||{})[key];if(product)delete product[field]});return}
 values.forEach((x,i)=>{const phase=phasing.phases[i];if(!phase.products)phase.products={};if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};phase.products[key][field]=x});
 let allocated=0;
 phasing.products[key]=values.map((x,i)=>{const share=i===values.length-1?100-allocated:Number((x/total*100).toFixed(6));allocated+=share;return Math.max(0,share)});
}
// Какой мерой отдают этот продукт: метрами или штуками. У паркинга и кладовых
// продаётся ШТУКА, и метры про них ничего не говорят — гараж, отданный городу,
// уменьшил бы площадь, а места продолжили бы продаваться все.
// Объекты, которые меряются местами, — из реестра движка подстановкой.
const PHASE_GIVEN_IN_UNITS=['underground_parking','storage',__DEVELOPAID_UNIT_OBJECTS__];
// Соцобъекты передаются городу целиком, и продаваемой площади у них нет:
// правило «переданное уходит из продаваемой» к ним не идёт.
const SOCIAL_TEP_PRODUCTS=['kindergarten','school','clinic'];
// Строки, у которых «передаётся» не вводится руками, а следует из признака.
// У соцобъекта передаётся весь объект; у ФОКа передача решается полем «что с
// объектом дальше» — «всё или так, или так» (владелец, 05.09.2026), и вписать
// половину метров нельзя по построению, а не по внимательности.
const DERIVED_TRANSFER_PRODUCTS=SOCIAL_TEP_PRODUCTS.concat(['sports']);
function derivedTransferNote(key){
 return key==='sports'
  ? 'ФОК уходит целиком: продажа или передача — поле «Что с объектом дальше»'
  : 'Соцобъект передаётся городу целиком: своей продаваемой площади у него нет';
}
// Соцобъект очереди меряется МЕСТАМИ: сколько его в этой очереди, говорит
// таблица соцобъектов ниже, а метры считаются от мест тем же нормативом, что и
// у проекта (`social_area_per_place` в движке — на странице это поле норматива,
// которое `syncTep` держит равным ступени РНГП или фактическому при требовании
// КРТ). Своей арифметики здесь нет: второй ответ на «сколько метров у садика»
// разошёлся бы с расчётом, и обе строки выглядели бы верными.
function phaseSocialTepRow(key,index){
 // Своя таблица пуста — размещает движок сам («поздняя раскладка: разгружаем
 // первую очередь»), и на 250 местах он строит садик во ВТОРОЙ очереди. Пока
 // вкладка считала только по своей таблице, она показывала нули там, где
 // модель строит объект, — то есть повторяла ту же ошибку, что чинится:
 // показанное расходилось с посчитанным. Умолчание не переписываем второй
 // раз — берём ПРИМЕНЁННОЕ размещение из ответа движка (`social_allocation`).
 const own=(phasing.social_objects||[]).filter(o=>o&&Number(o.capacity||0)>0);
 const applied=own.length?own
  :((phaseBundle&&phaseBundle.social_allocation)||[]);
 const places=applied
  .filter(o=>o&&o.type===key&&Number(o.phase||1)===index+1)
  .reduce((sum,o)=>sum+Number(o.capacity||0),0);
 const perPlace=Number(inputs[SOCIAL_TEP_NORM_INPUTS[key]]||0);
 const area=places>0?places*perPlace:0;
 const share=socialTotalShare();
 // Продаваемой у соцобъекта нет вовсе: он передаётся городу целиком.
 return {gns:area>0&&share>0?area/share:0,saleable:0,units:places,area:area};
}
function phaseGivenField(key){
 return PHASE_GIVEN_IN_UNITS.includes(key)?'transfer_units':'transfer';
}
function setPhaseProductGiven(index,key,value){
 if(DERIVED_TRANSFER_PRODUCTS.includes(key))return;
 const phase=phasing.phases[index];if(!phase)return;if(!phase.products)phase.products={};
 if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};
 const field=phaseGivenField(key);
 const own=phase.products[key];
 const was=Number(own[field]||0);
 const now=Math.max(0,Number(value||0));
 own[field]=now;
 if(field==='transfer'){
  // Переданные метры строятся, но не продаются: продаваемая ЭТОЙ очереди
  // падает ровно на них, и очередь становится заданной — доля проекта её
  // больше не двигает, иначе отданное вернулось бы при первом пересчёте.
  // Тождество то же, что в таблице ТЭП: полезная — построенная площадь,
  // продаваемая — за вычетом переданного. Полезная уезжает в очередь своим
  // полем: движок вычитает переданное сам ровно тогда, когда продаваемой ему
  // не объявили, и два вычитания отняли бы отданное дважды.
  const net=own.saleable!==undefined?Number(own.saleable):phaseProductDerived(key,'saleable',index);
  const gross=Math.max(net+was,
   own.useful!==undefined?Number(own.useful):phaseProductDerived(key,'useful',index));
  own.useful=Number(gross.toFixed(2));
  own.saleable=Math.max(0,Number((gross-now).toFixed(2)));
  syncPhaseProductSharesFromTep(key,'saleable',index);
 }
 // Проектная строка — сумма очередей: приоритет у очередности.
 const sum=phasing.phases.reduce((total,p)=>total+Number(((p.products||{})[key]||{})[field]||0),0);
 if(!tep[key])tep[key]={};
 tep[key][field]=Number(sum.toFixed(field==='transfer'?2:0));
 if(field==='transfer'){
  // Проектная строка — сумма очередей: продаваемая складывается из их нетто,
  // а полная площадь это она же плюс всё переданное. Тождество считает один
  // помощник — второй счёт той же величины однажды разошёлся бы с первым.
  const net=phasing.phases.reduce((total,p,i)=>{
   const row=(p.products||{})[key]||{};
   return total+(row.saleable!==undefined?Number(row.saleable):phaseProductDerived(key,'saleable',i));
  },0);
  tepApplyTransfer(key,net+Number(tep[key].transfer||0));
  tepRowToInputs(key);
 }
 renderPhasing();renderTep();renderInputs();calculate();
}
function setPhaseProductTep(index,key,field,value){
 const phase=phasing.phases[index];if(!phase)return;if(!phase.products)phase.products={};
 if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};
 // Штука — счётчик: дробной её не принимаем ни из поля, ни из ограничения
 // остатком, иначе округление на экране разойдётся с тем, что уедет в расчёт.
 const count=field==='units';
 const asked=value===''?null:Math.max(0,Number(value||0)),limit=phaseProductTepLimit(key,field,index);
 const requested=asked===null?null:(count?Math.round(asked):asked);
 let bounded=requested===null?null:(limit===null?requested:Math.min(count?Math.floor(limit+1e-6):limit,requested));
 phaseTepEditWarning=requested!==null&&bounded<requested-1e-6?`Значение ограничено до ${num(bounded)}: доступный остаток исходного ТЭП — ${num(limit)}.`:'';
 if(bounded===null)delete phase.products[key][field];else phase.products[key][field]=bounded;
 if(Object.keys(phase.products[key]).every(k=>k==='assumption_source'))delete phase.products[key];
 // Три числа продукта связаны теми же пропорциями, что и в таблице ТЭП: там
 // любое из них ведущее, а два других достраиваются. Здесь связи не было
 // вовсе — правишь ГНС очереди, продаваемая остаётся прежней, и строка
 // перестаёт сходиться сама с собой (владелец, 03.09.2026: «тут тоже ячейки
 // не зависят друг от друга»). Штука — счётчик, пропорцией не считается.
 if(bounded!==null&&['gns','saleable'].includes(field)&&TEP_RATIOS[key]){
  const base={gns:0,total_area:0,saleable:0,useful:0};
  base[field]=bounded;
  const filled=tepFillByRatios(key,base);
  const paired=field==='gns'?'saleable':'gns';
  const want=Number(filled[paired]||0);
  if(want>0){
   const pairLimit=phaseProductTepLimit(key,paired,index);
   const value=pairLimit===null?want:Math.min(pairLimit,want);
   phase.products[key][paired]=value;
   syncPhaseProductSharesFromTep(key,paired,index);
   if(!phasing.products[key])clampPhaseProductTepRight(key,paired,index);
  }
 }
 syncPhaseProductSharesFromTep(key,field,index);if(!phasing.products[key])clampPhaseProductTepRight(key,field,index);renderPhasing();calculate();
}
function setSharedShare(bucket,k,i,v){phasing[bucket][k][i]=Number(v||0)}
function splitCapacity(total,typical){let t=Math.max(0,Number(total||0)),out=[];typical=Math.max(1,Number(typical||1));while(t>0){const v=Math.min(typical,t);out.push(v);t-=v}return out}
function autoSocialObjects(doRender=true){
 phasing.social_objects=[];if(inputs.social_mode!=='Строительство'){if(doRender)renderPhasing();return}
 [['kindergarten',productName('kindergarten'),Number(inputs.kindergarten_places||0),250],['school',productName('school'),Number(inputs.school_places||0),1100],['clinic',productName('clinic'),Number(inputs.clinic_capacity||0),300]].forEach(([type,label,total,typical])=>{
  const chunks=splitCapacity(total,typical);chunks.forEach((capacity,i)=>{let phase;if(chunks.length===1)phase=type==='kindergarten'?1:Math.min(2,phasing.phase_count);else phase=1+Math.round(i*(phasing.phase_count-1)/Math.max(1,chunks.length-1));phasing.social_objects.push({id:`${type}_${Date.now()}_${i}`,name:`${label} №${i+1}`,type,capacity,phase,start_date:phaseStartDate(phase),start_mode:'auto'})})
 });normalizeSocialObjectDates();if(doRender){renderPhasing();calculate()}
}
function addSocialObject(type){const l=k=>productName(k),n=phasing.social_objects.filter(x=>x.type===type).length,phase=1;phasing.social_objects.push({id:`${type}_${Date.now()}`,name:`${l(type)} №${n+1}`,type,capacity:0,phase,start_date:phaseStartDate(phase),start_mode:'auto'});renderPhasing();calculate()}
function updateSocialObject(i,k,v){
 const o=phasing.social_objects[i];if(!o)return;
 if(k==='phase'){
   o.phase=Number(v||1);
   if(o.start_mode!=='manual')o.start_date=phaseStartDate(o.phase);
 }else if(k==='start_date'){
   if(v){o.start_date=v;o.start_mode='manual'}else{o.start_mode='auto';o.start_date=phaseStartDate(o.phase)}
 }else{o[k]=k==='capacity'?Number(v||0):v}
 normalizeSocialObjectDates();renderPhasing();calculate()
}
function deleteSocialObject(i){phasing.social_objects.splice(i,1);renderPhasing();calculate()}
function renderSocialStatus(){
 if(!document.getElementById('socialObjectsStatus'))return;const t={kindergarten:0,school:0,clinic:0};
 phasing.social_objects.forEach(o=>t[o.type]=(t[o.type]||0)+Number(o.capacity||0));
 const r={kindergarten:Number(inputs.kindergarten_places||0),school:Number(inputs.school_places||0),clinic:Number(inputs.clinic_capacity||0)},l={kindergarten:productName('kindergarten'),school:productName('school'),clinic:productName('clinic')};
 socialObjectsStatus.innerHTML=Object.keys(t).map(k=>{const ok=Math.abs(t[k]-r[k])<.01;return `<span class="${ok?'phase-total-ok':'phase-total-bad'}">${l[k]}: ${num(t[k])} / ${num(r[k])}${ok?' ✓':' — не сходится'}</span>`}).join(' &nbsp; ')
}
function renderPhasingStatus(){if(!document.getElementById('phaseProductStatus'))return;phaseProductStatus.textContent='Контроль 100% — '+Object.entries(phasing.products).map(([k,a])=>{const s=a.reduce((x,y)=>x+Number(y||0),0);return `${k}: ${s.toFixed(1)}% ${Math.abs(s-100)<.1?'✓':'!'}`}).join(' · ')}
function setPhaseFinancingStrategy(value){
 phasing.financing_strategy=value==='unified_project_cash'?'unified_project_cash':'independent';
 renderPhasing();calculate();
}
// Переход из подсказки на вкладке «Очередность» к блоку стратегии в
// «Экономика → Финансирование»: группа раскрывается, блок — в начале экрана.
function openPhaseFinancing(){
 openTab('inputs');
 const det=document.querySelector('details[data-group="Финансирование"]');
 if(det)det.open=true;
 const block=document.getElementById('phaseFinancingBlock');
 if(block)block.scrollIntoView({block:'start'});
}
function renderPhaseFinancing(){
 // Блок стоит в «Экономика → Финансирование» и виден только при очередности
 // на 2+ очереди — тем же условием, что настройки вкладки «Очередность».
 const block=document.getElementById('phaseFinancingBlock');
 if(block)block.hidden=!(phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1);
 const independent=document.getElementById('phaseFinancingIndependent'),unified=document.getElementById('phaseFinancingUnified'),body=document.getElementById('phaseFinancingBody'),summary=document.getElementById('phaseFinancingSummary');
 const strategy=currentPhaseFinancingStrategy();phasing.financing_strategy=strategy;
 if(independent)independent.checked=strategy==='independent';if(unified)unified.checked=strategy==='unified_project_cash';
 const carryBox=document.getElementById('phaseCarryDebt');
 if(carryBox)carryBox.checked=!!phasing.carry_debt_forward;
 const sweepBox=document.getElementById('phaseSweepCash');
 // Отсутствующий ключ — «не задано», а не «снято»: у проекта, сохранённого
 // до появления признака, его нет, и `!!` показал бы галочку снятой при
 // включённом расчёте — экран разошёлся бы с сервером.
 if(sweepBox)sweepBox.checked=phasing.sweep_project_cash!==false;
 const sweepPct=document.getElementById('phaseSweepPct');
 if(sweepPct){sweepPct.value=Number(phasing.cash_sweep_pct??80);
  sweepPct.disabled=phasing.sweep_project_cash===false;}
 if(!body||!summary)return;
 const funding=phaseBundle&&phaseBundle.mode==='phased'?phaseBundle.phase_financing:null;
 if(!funding||funding.strategy!==strategy){body.innerHTML='';summary.textContent='Пересчитываю финансирование очередей…';return}
 const rows=funding.rows||[],totals=funding.totals||{};
 body.innerHTML=rows.map(x=>`<tr><td>${escapeHtml(x.name||('О'+x.phase))}</td><td>${money(x.pre_rns_costs)}</td><td>${money(x.project_cash_used)}</td><td>${money(x.own_funds)}</td><td>${money(x.new_bridge)}</td><td>${money(x.peak_pf)}</td></tr>`).join('');
 summary.innerHTML=funding.enabled
  ?`Единый денежный поток включён: свободные деньги проекта оплатили <b>${money(totals.project_cash_used)}</b> расходов следующих очередей до разрешения на строительство. Новый бридж — ${money(totals.new_bridge)}.`
  :`Каждая очередь финансируется отдельно: расходы до разрешения на строительство она оплачивает своими деньгами и бриджем. Всего взято бриджа — <b>${money(totals.new_bridge)}</b>.`;
}
const VOLUME_SHARE_ARTICLES=['ird','design','preparation','utilities'];
// Статья «по объёму»: доли считает движок по строительному объёму очереди,
// и цена метра у каждой очереди равна вводной. Заданная руками доля остаётся
// возможной — и тогда рядом стоит фактическая цена метра этой очереди из
// последнего расчёта: 42% читаются как «25,9 тыс ₽/м² при вводной 14,5».
function sharedRateNote(k,i){
 const c=(phaseBundle&&phaseBundle.comparison)||[],row=c[i]||{},r=row.shared_rates_th||{},inp=row.shared_rate_inputs_th||{};
 if(r[k]==null)return '';
 return `<div style="font-size:10px;color:#777;margin-top:2px">${num2(r[k])} тыс ₽/м² МКД${inp[k]!=null?' · вводная '+num2(inp[k]):''}</div>`;
}
function setSharedVolume(bucket,k){phasing[bucket][k]='volume';renderPhasing();calculate()}
function setSharedManual(bucket,k){const applied=(phaseBundle&&phaseBundle.shared_cash_applied&&phaseBundle.shared_cash_applied[k])||phaseWeightPreset(phasing.phases.length);phasing[bucket][k]=Array.from({length:phasing.phases.length},(_,i)=>Number(applied[i]||0));renderPhasing()}
function renderShareTable(h,b,data,labels,bucket){
 const head=document.getElementById(h),body=document.getElementById(b);if(!head||!body)return;
 head.innerHTML=`<tr><th>Статья</th>${phasing.phases.map(p=>`<th>${p.name}</th>`).join('')}<th>Итого</th></tr>`;
 body.innerHTML=Object.entries(data).map(([k,a])=>{
  if(!Array.isArray(a)){
   const applied=(phaseBundle&&phaseBundle.shared_cash_applied&&phaseBundle.shared_cash_applied[k])||null;
   const shares=applied?applied.map((v,i)=>`${(phasing.phases[i]||{}).name||('О'+(i+1))} ${Number(v).toFixed(1)}%`).join(' · '):'доли посчитает движок по объёму каждой очереди';
   return `<tr><td>${labels[k]||k}</td><td colspan="${phasing.phases.length}" style="color:#555">по объёму очереди — цена метра равна вводной${applied?': '+shares:'. '+shares} <button type="button" class="btn-small" onclick="setSharedManual('${bucket}','${k}')">задать руками</button></td><td class="phase-total-ok">100,0%</td></tr>`;
  }
  const s=a.reduce((x,y)=>x+Number(y||0),0);
  const back=(bucket==='shared_cash'&&VOLUME_SHARE_ARTICLES.includes(k))?` <a href="#" style="font-size:11px" onclick="setSharedVolume('${bucket}','${k}');return false">по объёму</a>`:'';
  return `<tr><td>${labels[k]||k}${back}</td>${a.map((v,i)=>`<td><input type="number" step="1" value="${Number(v).toFixed(1)}" onchange="setSharedShare('${bucket}','${k}',${i},this.value)">${bucket==='shared_cash'?sharedRateNote(k,i):''}</td>`).join('')}<td class="${Math.abs(s-100)<.1?'phase-total-ok':'phase-total-bad'}">${s.toFixed(1)}%</td></tr>`}).join('')
}
function renderPhasing(){
 if(!document.getElementById('phasingEnabled'))return;
 normalizeSocialObjectDates();
 document.getElementById('phasing').classList.toggle('phasing-on',!!phasing.enabled&&Number(phasing.phase_count||1)>1);
 phasingEnabled.checked=!!phasing.enabled;phaseCount.value=String(phasing.phase_count);phaseTargetSize.value=Number(phasing.target_size_sqm||70000);phaseGap.value=Number(phasing.phase_gap_months||12);if(document.getElementById('phaseCostInflation'))phaseCostInflation.value=Number(phasing.cost_inflation_pct??8);if(document.getElementById('phaseSalesPriceInflation'))phaseSalesPriceInflation.value=Number(phasing.sales_price_inflation_pct??8);
 const recommended=recommendationCount();
 phaseRecommendation.textContent=recommended<=1
   ? `1 очередь при ${num(currentMonetizableSaleable())} м² — разбиение не требуется`
   : `${recommended} очереди при ${num(currentMonetizableSaleable())} м²`;
 phaseCards.innerHTML=phasing.phases.map((p,i)=>{const cf=Math.pow(1+Number(phasing.cost_inflation_pct??8)/100,Number(p.start_offset_months||0)/12),pf=Math.pow(1+Number(phasing.sales_price_inflation_pct??8)/100,Number(p.start_offset_months||0)/12);return `<div class="phase-card"><h3>${p.name}</h3><div class="field"><label>Название</label><input value="${p.name}" onchange="phasing.phases[${i}].name=this.value;renderPhasing()"></div><div class="field"><label>Сдвиг старта, мес.</label><input type="number" value="${p.start_offset_months}" onchange="phasing.phases[${i}].start_offset_months=Number(this.value);normalizeSocialObjectDates();renderPhasing();calculate()"></div><div class="field"><label>Строительство, мес.</label><input type="number" value="${p.construction_months}" onchange="phasing.phases[${i}].construction_months=Number(this.value);calculate()"></div><div class="field"><label>Лимит НКЛ очереди, млн ₽</label><input type="number" value="${p.pf_limit_approved_mln||''}" placeholder="пусто — по потребности" title="Индивидуальные условия НКЛ этой очереди — единственный потолок её выборки. Пусто — НКЛ считается по потребности очереди; общий лимит во вводных — ожидание на все очереди, потолком не служит" onchange="phasing.phases[${i}].pf_limit_approved_mln=Number(this.value);calculate()"></div><div style="font-size:11px;color:#777;margin-top:8px">Старт: ${dateRu(addMonthsJS(inputs.project_start,p.start_offset_months))}<br>Индекс затрат: ×${cf.toFixed(3)}<br>Индекс стартовой цены: ×${pf.toFixed(3)}</div></div>`}).join('');
 phaseProductHead.innerHTML=`<tr><th>Продукт</th>${phasing.phases.map((p,i)=>`<th>${p.name}${i===phasing.phases.length-1?'<br><small>остаток</small>':''}</th>`).join('')}<th>Итого</th></tr>`;
 phaseProductBody.innerHTML=Object.entries(phasing.products).map(([k,a])=>{const s=a.reduce((x,y)=>x+Number(y||0),0);return `<tr data-share-row="${k}"><td>${productName(k)}</td>${a.map((v,i)=>`<td><input type="number" step="1" value="${Number(v).toFixed(1)}" ${i===a.length-1?'readonly title="Автоматический остаток до 100%"':`oninput="previewPhaseProductShares('${k}')" onchange="setPhaseProductShare('${k}',${i},this.value)"`}></td>`).join('')}<td data-share-total="${k}" class="${Math.abs(s-100)<.1?'phase-total-ok':'phase-total-bad'}">${s.toFixed(1)}%</td></tr>`}).join('');renderPhasingStatus();
 phasing.phases.forEach(p=>{if(!p.products)p.products={}});
 const numericTepFields=['gns','total_area','useful','saleable','transfer','units'];
 const activePhaseProduct=k=>numericTepFields.some(field=>Number((tep[k]||{})[field]||0)>0)
  ||!!phasing.products[k]
  ||phasing.phases.some(p=>numericTepFields.some(field=>Number((((p.products||{})[k]||{})[field])||0)>0))
  ||(phasing.social_objects||[]).some(o=>o&&o.type===k&&Number(o.capacity||0)>0);
 // The queue is a set of actual project products.  Empty defaults such as
 // storage, above-ground parking and clinic must not look like KRT objects.
 const tepKeys=Object.keys(TEP_DEFAULT).filter(k=>tep[k]&&activePhaseProduct(k));
 phaseTepHead.innerHTML=`<tr><th>Продукт</th>${phasing.phases.map(p=>`<th>${p.name}<br><small>ГНС · продаваемая · шт. · передаётся</small></th>`).join('')}<th>Итого по очередям</th></tr>`;
 phaseTepBody.innerHTML=tepKeys.map(k=>{
  const totals={gns:0,saleable:0,units:0,given:0};
  const cells=phasing.phases.map((p,i)=>{
   const own=(p.products||{})[k]||{};
   // Соцстрока очереди не правится здесь: её метры считаются от мест, а места
   // задаёт таблица соцобъектов ниже. Редактируемая ячейка обещала бы правку,
   // которой не будет, — вписанное затиралось бы на первом же расчёте, и
   // молча: до 08.09.2026 вписанное вообще ДОЕЗЖАЛО до движка поверх
   // норматива, и строка выходила из двух источников разом — ГНС 9 999 при
   // общей 4 500 и 111 местах, где ни одно число не отвечает двум другим.
   const socialRow=SOCIAL_TEP_PRODUCTS.includes(k)?phaseSocialTepRow(k,i):null;
   const inputsHtml=socialRow
    ? ['gns','saleable','units'].map(field=>{const v=Number(socialRow[field]||0);totals[field]+=v;
       return `<input type="number" value="${field==='units'?Math.round(v):Number(v.toFixed(2))}" readonly`
        +` style="margin:0;background:#f3f3f1;color:#555"`
        +` title="считается от мест этой очереди: ${num(socialRow.units)} × ${landNum(Number(inputs[SOCIAL_TEP_NORM_INPUTS[k]]||0),2)} м²/место. Места задаются в таблице соцобъектов ниже">`}).join('')
    : ['gns','saleable','units'].map(field=>{const isCount=field==='units',derived=phaseProductDerived(k,field,i),has=own[field]!==undefined,raw=has?Number(own[field]):derived,value=isCount?Math.round(raw):raw,isRemainder=!!phasing.products[k]&&i===phasing.phases.length-1,limit=phaseProductTepLimit(k,field,i),maxAttr=limit===null?'':`max="${Number(limit.toFixed(6))}"`;totals[field]+=value;return `<input type="number" min="0" ${maxAttr} step="${isCount?'1':'any'}" value="${isCount?value:Number(value.toFixed(2))}" title="${isRemainder?'Автоматический остаток':field+(has?' — введено вручную':' — рассчитано по доле')+(limit===null?'':` · максимум ${num(limit)}`)}" ${isRemainder?'readonly':`onchange="setPhaseProductTep(${i},'${k}','${field}',this.value)"`}>`}).join('');
   // Передаваемое правится в ОЧЕРЕДИ, а проектная строка становится их суммой
   // (владелец, 04.09.2026: «приоритет в очередности»). Долями оно не делится:
   // отдают конкретные метры конкретной очереди и конкретные машино-места, а
   // не долю проекта. Поэтому поле идёт мимо машинерии долей и не режется
   // остатком проектного ТЭП — иначе при нулевой проектной передаче в очередь
   // нельзя было бы вписать ничего.
   const givenField=phaseGivenField(k);
   const given=Number(own[givenField]||0);
   totals.given+=given;
   // У соцобъекта передаётся ВЕСЬ объект — садик не отдают наполовину, и
   // продаваемой площади у него нет вовсе. Поле, которое нечем заполнить,
   // на экране читается как забытое («зачем эта ячейка у соцобъектов?»,
   // владелец, 04.09.2026), поэтому его там нет.
   const givenInput=DERIVED_TRANSFER_PRODUCTS.includes(k)
    ? `<div class="phase-given-none" title="${derivedTransferNote(k)}">—</div>`
    : `<input type="number" min="0" step="${givenField==='transfer'?'any':'1'}" value="${given.toFixed(givenField==='transfer'?1:0)}"`
      +` title="передаётся ${givenField==='transfer'?'м² — вычитается из продаваемой площади этой очереди':'шт. — вычитается из продаваемых мест этой очереди'}"`
      +` onchange="setPhaseProductGiven(${i},'${k}',this.value)">`;
   return `<td><div style="display:grid;grid-template-columns:repeat(4,minmax(72px,1fr));gap:5px">${inputsHtml}${givenInput}</div></td>`;
  }).join('');
  // Сумма очередей сравнивается с проектом, а не показывается сама по себе.
  // Ячейка, вписанная руками, за правкой пропорций не идёт — и это правильно,
  // фактический ТЭП из ГПЗУ затираться не должен. Неправильно другое: пока
  // расхождение молчит, две строки выглядят одинаково достоверно. Сумма метров
  // по очередям обязана сходиться с проектом — на пресете Нагатино паркинг
  // расходился на 17 мест и 595 м², и заметить это было негде.
  const master={gns:Number((tep[k]||{}).gns||0),saleable:Number((tep[k]||{}).saleable||0),units:Number((tep[k]||{}).units||0)};
  const off=['gns','saleable','units'].filter(f=>Math.abs(totals[f]-master[f])>Math.max(1,master[f]*0.001));
  const names={gns:'ГНС',saleable:'продаваемая',units:'шт.'};
  // Переданное в итоге строки — сумма очередей: проектная строка ей и равна,
  // поэтому расхождением здесь быть нечему, а число видеть надо.
  const givenTotal=totals.given;
  const totalCell=off.length
   ? `<span class="phase-total-bad">${num(totals.gns)} · ${num(totals.saleable)} · ${num(totals.units)}</span>`
     +`<div class="phase-total-bad" style="font-size:11px;font-weight:500;margin-top:3px">не сходится с проектом: `
     +off.map(f=>`${names[f]} ${num(totals[f])} против ${num(master[f])} (${totals[f]>master[f]?'+':''}${num(totals[f]-master[f])})`).join('; ')+`</div>`
   : `<span class="phase-total-ok">${num(totals.gns)} · ${num(totals.saleable)} · ${num(totals.units)} ✓</span>`;
  // Переданное показывается всегда, когда оно есть: ноль в строке — это «не
  // передаём», а молчание читалось бы как «такого поля нет».
  const givenCell=givenTotal>0
   ? `<div style="font-size:11px;color:#7a1f1f;margin-top:3px">передаётся ${num(givenTotal)} `
     +`${phaseGivenField(k)==='transfer'?'м² — не продаются':'шт. — не продаются'}</div>`
   : '';
  // Чем меряется передача, у каждой строки своё: метры отдают метрами,
  // машино-места и кладовые — штуками. В шапке это не сказать: она одна на
  // все продукты, и «передаётся» без единицы читается как вопрос («что
  // передаётся? штуки или метры?», владелец, 04.09.2026).
  // «Передаётся в м²» рядом со строкой, где стоят и метры, и штуки, не
  // отвечает на вопрос: из какого из трёх чисел это вычитается («если в
  // квартирах и штуки и метры указаны», владелец, 04.09.2026). Подпись
  // называет базу, а не единицу.
  const givenHint=k==='sports'
   ? 'передаётся или продаётся целиком — по признаку объекта'
   : SOCIAL_TEP_PRODUCTS.includes(k)
   ? 'передаётся городу целиком'
   : (phaseGivenField(k)==='transfer'
      ? 'передаётся, м² — из продаваемой площади'
      : 'передаётся, шт. — из продаваемых мест');
  return `<tr><td><b>${productName(k)}</b><div style="font-size:11px;color:#777">${givenHint}</div></td>${cells}<td>${totalCell}${givenCell}</td></tr>`;
 }).join('');
 if(document.getElementById('phaseTepWarning'))phaseTepWarning.textContent=phaseTepEditWarning;
 const sl={purchase:'Покупка / вход',land_rights:'Земельные права / ВРИ',ird:'ИРД',design:'П + РД',preparation:'Подготовительные',utilities:'Наружные сети',social_compensation:'Соцкомпенсация',social_construction:'Соцобъекты — аналитическая аллокация'};
 renderShareTable('phaseCashHead','phaseCashBody',phasing.shared_cash,sl,'shared_cash');renderShareTable('phaseAllocHead','phaseAllocBody',phasing.shared_allocation,sl,'shared_allocation');
 socialObjectsBody.innerHTML=phasing.social_objects.map((o,i)=>`<tr><td><input value="${o.name||''}" onchange="updateSocialObject(${i},'name',this.value)"></td><td><select onchange="updateSocialObject(${i},'type',this.value)"><option value="kindergarten" ${o.type==='kindergarten'?'selected':''}>${productName('kindergarten')}</option><option value="school" ${o.type==='school'?'selected':''}>${productName('school')}</option><option value="clinic" ${o.type==='clinic'?'selected':''}>${productName('clinic')}</option></select></td><td><input type="number" value="${Number(o.capacity||0)}" onchange="updateSocialObject(${i},'capacity',this.value)"></td><td><select onchange="updateSocialObject(${i},'phase',this.value)">${phaseOptions(o.phase)}</select></td><td><input type="date" value="${o.start_date||''}" onchange="updateSocialObject(${i},'start_date',this.value)"></td><td><button class="btn" onclick="deleteSocialObject(${i})">×</button></td></tr>`).join('');renderSocialStatus();
 renderPhaseObjects();
 renderPhaseFinancing();
}

// Очередь выбирается только объекту, который есть в проекте: заведён и
// включён, или с метрами. Ответ — у движка (`row_listed`, признак `listed`
// строки ТЭП), тот же, что у ТЭП тизера; второй проверки здесь нет. Здесь
// стояли селекторы всех заведённых объектов, выключенных тоже («почему в
// Очерёдности все эти объекты, если включён только один офисник?», владелец,
// 04.10.2026). Нет ответа или признака — селектор остаётся: отсутствие ответа
// не решение. Очередь спрятанного объекта в `phasing.discrete` не трогается и
// вернётся вместе с ним.
function phaseObjectListed(key){
 // Свод, а не открытая очередь: в первой очереди объект второй пуст.
 const result=(phaseBundle&&phaseBundle.consolidated)||lastResult;
 const rows=result&&result.tep&&result.tep.rows;
 const row=Array.isArray(rows)?rows.find(r=>r&&r.key===key):null;
 // Ответ движка — о посчитанных вводных. Объект, включённый после него,
 // движок по `row_listed` назовёт объектом проекта всегда (заведён и
 // включён), и прятать его до пересчёта значило бы читать устаревший ответ.
 const o=OBJECT_BY_KEY[key];
 if(o&&inputOn(inputs[o.prefix+'_enabled']))return true;
 return !row||row.listed!==false;
}
function renderPhaseObjects(){
 // Узел — как у `tepBody` в `syncTep`: стенд страницы зовёт её без разметки.
 if(typeof assignObjects==='undefined'||!assignObjects)return;
 assignObjects.innerHTML=projectObjects().filter(o=>phaseObjectListed(o.key)).map(o=>
  `<div class="field"><label>${escapeHtml(productName(o.key))}</label>`
  +`<select data-object="${escapeHtml(o.key)}">${phaseOptions(phasing.discrete[o.key])}</select></div>`).join('');
 assignObjects.querySelectorAll('select[data-object]').forEach(sel=>{
  const key=sel.dataset.object;
  sel.value=String(phasing.discrete[key]||1);
  sel.onchange=function(){phasing.discrete[key]=Number(this.value);calculate()};
 })
}

"""
