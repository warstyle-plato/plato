"""Кусок страницы PAGE: Скрипт: ставки, запуск расчёта (calculate), графики платежей
и ПФ, сравнение очередей, подписи норм и парковки к результату.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_calc")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""function addMonthsJS(iso,months){
 const d=new Date(iso+'T12:00:00');
 const day=d.getDate();
 d.setDate(1);
 d.setMonth(d.getMonth()+Number(months||0));
 const last=new Date(d.getFullYear(),d.getMonth()+1,0).getDate();
 d.setDate(Math.min(day,last));
 return d.toISOString().slice(0,10);
}

function syncRateControlsFromInputs(){
 if(!document.getElementById('rateStartPct'))return;
 rateStartPct.value=Number(inputs.rate_start_pct||14);
 rateNormalizationMonths.value=Number(inputs.rate_normalization_months||24);
 rateTargetHigh.value=Number(inputs.rate_target_high_pct||11);
 rateTargetBase.value=Number(inputs.rate_target_base_pct||9);
 rateTargetLow.value=Number(inputs.rate_target_low_pct||7);
 rateScenario.value=inputs.rate_scenario||'base';
 updateRateScenarioLabels();
}

function formatRateTarget(value){
 const n=Number(value);
 return Number.isFinite(n)
   ? n.toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+'%'
   : '—';
}

function rateScenarioLabel(code){
 const meta={
   high:['Консервативный','rate_target_high_pct'],
   base:['Базовый','rate_target_base_pct'],
   low:['Оптимистичный','rate_target_low_pct']
 }[code]||['Базовый','rate_target_base_pct'];
 return `${meta[0]} → ${formatRateTarget(inputs[meta[1]])}`;
}

function updateRateScenarioLabels(){
 const select=document.getElementById('rateScenario');
 if(!select)return;
 const selected=inputs.rate_scenario||select.value||'base';
 Array.from(select.options).forEach(option=>{option.textContent=rateScenarioLabel(option.value)});
 select.value=selected;
}

function syncRateModel(recalculate=false){
 if(document.getElementById('rateStartPct')){
   inputs.rate_start_pct=Number(rateStartPct.value||14);
   inputs.rate_normalization_months=Math.max(1,Number(rateNormalizationMonths.value||24));
   inputs.rate_target_high_pct=Number(rateTargetHigh.value||11);
   inputs.rate_target_base_pct=Number(rateTargetBase.value||9);
   inputs.rate_target_low_pct=Number(rateTargetLow.value||7);
 }
 updateRateScenarioLabels();
 generateRateCurve();
 renderRates();
 if(recalculate)calculate();
}

function generateRateCurve(){
 const start=String(inputs.rate_start_date||new Date().toISOString().slice(0,10));
 const startRate=Number(inputs.rate_start_pct||14);
 const horizon=Math.max(1,Number(inputs.rate_normalization_months||24));
 const shape=Math.max(.05,Number(inputs.rate_curve_shape||2));
 const targets={
   high:Number(inputs.rate_target_high_pct||11),
   base:Number(inputs.rate_target_base_pct||9),
   low:Number(inputs.rate_target_low_pct||7)
 };
 const denom=1-Math.exp(-shape);
 rates=[];
 const totalMonths=180;
 for(let i=0;i<=totalMonths;i++){
   const progress=i>=horizon?1:(1-Math.exp(-shape*i/horizon))/denom;
   const row={date:addMonthsJS(start,i)};
   Object.entries(targets).forEach(([key,target])=>{
     row[key]=startRate+(target-startRate)*progress;
   });
   rates.push(row);
 }
 return rates;
}

async function refreshCurrentKeyRate(recalculate=true){
 const status=document.getElementById('cbrRateStatus');
 if(status)status.textContent='Получаю текущую ставку Банка России…';
 try{
   const response=await fetch('/current-key-rate?_='+Date.now(),{cache:'no-store'});
   if(!response.ok)throw new Error('Банк России не ответил');
   const data=await response.json();
   inputs.rate_start_pct=Number(data.rate||14);
   inputs.rate_start_date=String(data.date||new Date().toISOString().slice(0,10));
   if(document.getElementById('rateStartPct'))rateStartPct.value=inputs.rate_start_pct;
   if(status){
     status.textContent=Number(inputs.rate_start_pct).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+
       '% · '+(data.live?'Банк России':'Резервное значение')+' · '+dateRu(inputs.rate_start_date);
   }
 }catch(e){
   if(status)status.textContent='Не удалось обновить; используется сохранённое значение · '+dateRu(inputs.rate_start_date);
 }
 generateRateCurve();
 renderRates();
 if(recalculate)calculate();
}

function renderRateCurveChart(){
 const target=document.getElementById('rateCurveChart');if(!target||!rates.length)return;
 const horizon=Math.max(1,Number(inputs.rate_normalization_months||24));
 const show=rates.slice(0,Math.min(rates.length,horizon+25));
 const W=1120,H=330,pL=54,pR=22,pT=18,pB=62;
 const values=show.flatMap(r=>[r.high,r.base,r.low]);
 const min=Math.floor(Math.min(...values)-1),max=Math.ceil(Math.max(...values)+1);
 const x=i=>pL+i*(W-pL-pR)/Math.max(show.length-1,1);
 const y=v=>pT+(max-v)*(H-pT-pB)/Math.max(max-min,1);
 const pts=key=>show.map((r,i)=>`${x(i)},${y(r[key])}`).join(' ');

 let grid='';
 for(let v=min;v<=max;v+=1){
   const major=v%2===0;
   grid+=`<line x1="${pL}" y1="${y(v)}" x2="${W-pR}" y2="${y(v)}" stroke="${major?'#dddddd':'#eeeeee'}"/>`;
   if(major)grid+=`<text x="8" y="${y(v)+4}" font-size="10" fill="#777">${v}%</text>`;
 }

 let quarterAxis='',yearAxis='';
 const yearBuckets={};
 show.forEach((r,i)=>{
   const d=new Date(r.date+'T12:00:00');
   const month=d.getMonth();
   const year=d.getFullYear();
   if(!yearBuckets[year])yearBuckets[year]=[];
   yearBuckets[year].push(i);
   if([0,3,6,9].includes(month)){
     const q=Math.floor(month/3)+1;
     quarterAxis+=`<line x1="${x(i)}" y1="${pT}" x2="${x(i)}" y2="${H-pB+16}" stroke="#e1e1e1"/>`;
     quarterAxis+=`<text class="rate-axis-label" x="${x(i)+4}" y="${H-18}">Q${q}</text>`;
   }
 });
 Object.entries(yearBuckets).forEach(([year,idxs])=>{
   const cx=(x(idxs[0])+x(idxs[idxs.length-1]))/2;
   yearAxis+=`<text class="rate-year-label" text-anchor="middle" x="${cx}" y="${H-4}">${year}</text>`;
 });

 const goalIndex=Math.min(horizon,show.length-1),goalX=x(goalIndex);
 const markerIdx=[0,Math.min(12,show.length-1),goalIndex].filter((v,i,a)=>a.indexOf(v)===i);
 const markers=key=>markerIdx.map(i=>`<circle cx="${x(i)}" cy="${y(show[i][key])}" r="${key==='base'?4:3}" fill="${key==='base'?'#111':key==='high'?'#666':'#aaa'}"/>`).join('');

 target.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
  ${grid}${quarterAxis}
  <line x1="${goalX}" y1="${pT}" x2="${goalX}" y2="${H-pB+16}" stroke="#777" stroke-dasharray="5 5"/>
  <text x="${Math.max(pL,goalX-70)}" y="${pT+12}" font-size="10" fill="#555">цель через ${horizon} мес.</text>
  <polyline points="${pts('high')}" fill="none" stroke="#666" stroke-width="2.3" vector-effect="non-scaling-stroke"/>
  <polyline points="${pts('base')}" fill="none" stroke="#111" stroke-width="3.4" vector-effect="non-scaling-stroke"/>
  <polyline points="${pts('low')}" fill="none" stroke="#aaa" stroke-width="2.3" vector-effect="non-scaling-stroke"/>
  ${markers('high')}${markers('base')}${markers('low')}
  ${yearAxis}
 </svg>
 <div class="legend"><span><i style="background:#666"></i>Консервативная → ${formatRateTarget(inputs.rate_target_high_pct)}</span><span><i></i>Базовая → ${formatRateTarget(inputs.rate_target_base_pct)}</span><span><i class="gray"></i>Оптимистичная → ${formatRateTarget(inputs.rate_target_low_pct)}</span></div>`;
}

function renderRates(){
 if(!rates.length)generateRateCurve();
 if(document.getElementById('rateBody')){
   rateBody.innerHTML=rates.slice(0,61).map(r=>`<tr>
     <td>${dateRu(r.date)}</td>
     <td>${Number(r.high).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
     <td>${Number(r.base).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
     <td>${Number(r.low).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
   </tr>`).join('');
 }
 syncRateControlsFromInputs();
 renderRateCurveChart();
}

// Расчёт экономики за входом. Признак приходит с сервера: без токена бота гейт
// выключен, и страница не имеет права запирать дверь, которую сервер не запер.
let calcRequiresLogin=false;

function calcNeedsLogin(){
 return calcRequiresLogin&&!activeSession()&&!projectsAdminKey;
}

async function calcRefusal(response){
 try{const data=await response.json();return String(data.detail||'')}catch(e){return ''}
}

function renderCalcLocked(reason){
 lastResult=null;phaseBundle=null;
 const box=document.getElementById('calcLocked');
 if(!box)return;
 box.style.display='';
 box.innerHTML='<h3>Экономика проекта — после входа через Telegram</h3>'+
  '<p>'+escapeHtml(reason||'Участок, ТЭП и градостроительные ограничения считаются без входа — '+
   'они на вкладках «Участок» и «ТЭП». Экономика, вердикт, LLCR, отчёт и выгрузки '+
   'принадлежат конкретному человеку, поэтому за ними нужен вход.')+'</p>'+
  '<p class="calc-locked-why">Вход занимает несколько секунд: подтверждение в боте, '+
  'без пароля и без второй регистрации.</p>'+
  '<button class="btn dark" onclick="openLogin()">Войти через Telegram</button>';
}

function hideCalcLocked(){
 const box=document.getElementById('calcLocked');
 if(box)box.style.display='none';
}

// Номер последнего запущенного расчёта и номер последнего ответившего (см.
// `calculate`). Расчёт «в пути», пока ответивший отстаёт от запущенного: ответ
// пришёл, отвергнут как опоздавший или упал — всё это «ответил».
let calcRun=0,calcSettled=0;
// Нет ли расчёта в пути. Один ответ на «расчёт закончился» для стендов и
// всего, что ждёт итог: пауза «на глаз» на медленной машине заканчивается
// раньше ответа, а `lastResult` после загрузки проекта ещё меняется.
function calcIdle(){return calcSettled===calcRun}
async function calculate(){
 // Форма забирается целиком, КРОМЕ полей, где стоит счётный показатель, а не
 // набранное число: у таких вводная равна нулю, и ноль здесь значит «считает
 // методика». Забери его отсюда — и методика превратилась бы в снимок: класс
 // сменили, ставка метра двора стала другой, а в поле осталась прежняя цифра,
 // как замирал паркинг, пока норма не начала помечать своё. Пометку ставит
 // тот, кто число печатает (`renderLandscapingHouseRateValue`), и он же её
 // снимает, как только человек вписал своё. Набранное при этом не теряется:
 // `onchange` поля пишет вводную сам, до всякого пересчёта.
 document.querySelectorAll('[id^=f_]').forEach(el=>{if(el.dataset.derived==='1')return;const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});
 if(document.getElementById('rateScenario'))inputs.rate_scenario=rateScenario.value||'base';
 if(document.getElementById('rateStartPct')){
   inputs.rate_start_pct=Number(rateStartPct.value||inputs.rate_start_pct||14);
   inputs.rate_normalization_months=Number(rateNormalizationMonths.value||inputs.rate_normalization_months||24);
   inputs.rate_target_high_pct=Number(rateTargetHigh.value||inputs.rate_target_high_pct||11);
   inputs.rate_target_base_pct=Number(rateTargetBase.value||inputs.rate_target_base_pct||9);
   inputs.rate_target_low_pct=Number(rateTargetLow.value||inputs.rate_target_low_pct||7);
 }
 updateRateScenarioLabels();
 generateRateCurve();
 repairParkingFromGlavapu();
 normalizeSocialObjectDates();
 reportView='all';
 // Экономика — за входом через бота: участок, ТЭП и ограничения открыты, а
 // вывод о деньгах уже принадлежит конкретному человеку (решение владельца,
 // 18.08.2026). Спрашиваем здесь, а не ловим 401 на каждом изменении поля:
 // расчёт зовётся при правке любой вводной.
 if(calcNeedsLogin()){renderCalcLocked();return null}
 // Номер сброса на момент запуска. Сброс перерисовывает поля, их onchange
 // зовёт расчёт, а расчёт асинхронный — он возвращается уже после обнуления и
 // заполняет отчёт заново. Тот же приём, что у опоздавшего ответа Платона:
 // результат прошлого состояния в новое не пускается.
 const startedAtReset=resetRun;
 // Номер самого расчёта. Каждая правка поля зовёт расчёт, ответы приходят в
 // любом порядке, и опоздавший ответ ПРЕЖНИХ вводных перерисовывал итог
 // поверх свежего: подставили рекомендацию 951, вписали 1300 — ушло 1300, а
 // в отчёте осталась выручка по 951. Показывается только последний запущенный.
 const calcTicket=++calcRun;
 try{
 if(phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1){
   const response=await fetch('/calculate-phased',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates,phasing,session:activeSession(),access_key:projectsAdminKey})});
   if(calcTicket!==calcRun)return null;
   if(!response.ok){renderCalcLocked(await calcRefusal(response));return null}
   const bundle=await response.json();
   if(calcTicket!==calcRun)return null;
   phaseBundle=bundle;lastResult=phaseBundle.consolidated;
 }else{
   const response=await fetch('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates,session:activeSession(),access_key:projectsAdminKey})});
   if(calcTicket!==calcRun)return null;
   if(!response.ok){renderCalcLocked(await calcRefusal(response));return null}
   const result=await response.json();
   if(calcTicket!==calcRun)return null;
   lastResult=result;phaseBundle=null;
   if(lastResult&&lastResult.tep&&Array.isArray(lastResult.tep.rows)){
    // Строку, которую тип проекта не считает, назад НЕ пишем: её нули —
    // участие в расчёте, а не решение человека, и записанные они стёрли бы
    // набранное, которое вернётся с жилым типом.
    lastResult.tep.rows.forEach(r=>{if(!tep[r.key]||r.excluded)return;['gns','total_area','useful','saleable','transfer','units'].forEach(k=>{if(r[k]!=null)tep[r.key][k]=Number(r[k])})})
   }
 }
 adoptEngineDerivedTep((phaseBundle&&phaseBundle.consolidated)||lastResult);
 // Перенос устаревших вводных решает движок (`migrate_growth_post`), а
 // страница только принимает его ответ: иначе поле показывало бы одно
 // число, а расчёт шёл по другому. Происхождение подписано у поля.
 applyInputMigrations((phaseBundle||lastResult||{}).input_migrations);
 if(startedAtReset!==resetRun){
  // Между стартом расчёта и его ответом человек нажал «Сбросить».
  lastResult=null;phaseBundle=null;blankResultSurfaces();return null;
 }
 repairParkingFromGlavapu();renderResult();renderPhaseReportControls();renderPhaseFinancing();renderPhaseObjects();
 if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();
 // Состояние сохраняется каждым пересчётом, а не отдельной кнопкой и
 // телеграм-потоком: применённая предустановка не переживала перезагрузку —
 // вводные молча возвращались к умолчаниям (ВРИ 2 864,29, покупка 0), и
 // выглядело это как «предустановка не проедается в расчёт».
 persistLocalSilently();
 return lastResult;
 }finally{if(calcTicket>calcSettled)calcSettled=calcTicket}
}

// Что принёс загруженный снимок в производных полях — до первого ответа
// движка. Совпало с движком — сказать нечего: иначе следующая правка ТЭП,
// честно сдвинувшая гостевые, выглядела бы «исправлением при загрузке».
// Разошлось — один раз уведомление и запись в журнал; таблица молчит.
// Состояние держит функция, а не верхнее `let`: так его видит и стенд страницы
// (`tests/page_blocks`), который добирает куски по именам функций.
function derivedState(){
 if(!derivedState.s)derivedState.s={tail:null,fresh:false};
 return derivedState.s;
}
function derivedTailField(key){
 return key==='underground_parking'?'guest_units':(SOCIAL_TEP_PRODUCTS.includes(key)?'transfer_units':null);
}
// `strip` снимает производное и с живой строки: до ответа движка в ТЭП нет
// чужого числа, которое прочёл бы кто-то, кроме подписи. Пресет своё число
// гостевых знает из документа — его строка остаётся как пришла.
function rememberDerivedTail(source,strip){
 const tail={};
 ['underground_parking'].concat(SOCIAL_TEP_PRODUCTS).forEach(key=>{
  const field=derivedTailField(key),row=source&&source[key];
  if(!row||typeof row!=='object'||row[field]==null||row[field]==='')return;
  tail[key]={[field]:Number(row[field]),units:Number(row.units||0)};
  if(strip&&tep[key])delete tep[key][field];
 });
 derivedState().tail={rows:tail,settled:false};
 derivedState().fresh=false;
}
// Производные поля в снимке, который уходит в файл или хранилище, — только
// числа движка для ЭТОГО состояния. Расчёта после загрузки не было (отказ,
// выгрузка записи из списка без открытия) — поля в снимок не идут вовсе:
// отсутствие значит «выведет движок», а не ноль и не чужое число.
function persistedTep(source,fresh=derivedState().fresh){
 const out=cloneValue(source||{});
 ['underground_parking'].concat(SOCIAL_TEP_PRODUCTS).forEach(key=>{
  const row=out[key];
  if(!row||typeof row!=='object')return;
  delete row.guest_units_stale;
  if(!fresh)delete row[derivedTailField(key)];
 });
 return out;
}
function settleDerivedTail(rows){
 const state=derivedState();
 if(!state.tail||state.tail.settled)return;
 const kept={};
 rows.forEach(r=>{
  const was=state.tail.rows[r.key],field=derivedTailField(r.key);
  if(!was||r.excluded||r[field]==null)return;
  if(Math.abs(Number(r[field])-was[field])>1e-9)kept[r.key]=was;
 });
 state.tail={rows:kept,settled:true};
 announceDerivedCorrections(derivedCorrections(rows));
}
// Список исправлений — ОДИН на уведомление и журнал: что было в файле и что
// дал движок для той же строки. Строится из запомненного загрузкой хвоста и
// ответа расчёта, второго счёта здесь нет.
function derivedCorrections(rows){
 const tail=derivedState().tail;
 if(!tail||!tail.settled)return [];
 return (rows||[]).filter(r=>tail.rows[r.key]).map(r=>{
  const field=derivedTailField(r.key);
  const name=field==='guest_units'?'гостевые места'
   :'переданные места '+String((tep[r.key]&&tep[r.key].label)||r.label||r.key);
  return {key:r.key,field,name,was:tail.rows[r.key][field],now:Number(r[field]||0),
          basis:field==='guest_units'?'норматив':'соцобъект передаётся целиком'};
 });
}
function derivedCorrectionsText(list){
 return 'В файле исправлены устаревшие числа: '
  +list.map(c=>c.name+' '+num(c.was)+' → '+num(c.now)+' ('+c.basis+')').join(', ');
}
function announceDerivedCorrections(list){
 if(!list||!list.length)return;
 const text=derivedCorrectionsText(list);
 showPageNotice(text);
 // Журнал пишет сервер (`usage_track`), а не консоль: ошибка только в логе
 // браузера невидима. Сбой записи расчёт не трогает.
 try{
  fetch('/tep-corrections',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({session:activeSession(),text,
    corrections:list.map(c=>({key:c.key,field:c.field,was:c.was,now:c.now}))})}).catch(()=>{});
 }catch(e){}
}
// Всплывающее уведомление внизу окна: одна строка, сама уходит, закрывается
// щелчком. Таймер живёт на функции — её можно гонять в отрыве от страницы.
function showPageNotice(text){
 if(showPageNotice.timer){clearTimeout(showPageNotice.timer);showPageNotice.timer=null}
 let box=document.getElementById('pageNotice');
 if(!box){
  box=document.createElement('div');
  box.id='pageNotice';
  box.setAttribute('role','status');
  box.style.cssText='position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:99997;'
   +'max-width:min(720px,calc(100vw - 32px));padding:10px 14px;border-radius:8px;'
   +'background:#2b2b2b;color:#fff;font-size:13px;line-height:1.4;box-shadow:0 6px 24px rgba(0,0,0,.25);cursor:pointer';
  box.onclick=()=>box.remove();
  document.body.appendChild(box);
 }
 box.textContent=text;
 showPageNotice.timer=setTimeout(()=>{if(box.isConnected)box.remove()},12000);
}

// Производные строки ТЭП — числа движка, и в состояние страницы пишутся ЕГО
// числа: гостевые места паркинга и переданные места соцобъекта. В сохранённом
// проекте жило чужое число (109 гостевых на 29 местах «Донского» и на 201
// месте «Власова», 250 переданных мест ДОО при нуле мест), и оно переезжало
// дальше с каждым сохранением. Пишется в обеих ветках расчёта — одиночной и
// очередей: прежде запись стояла только в одиночной, и проект с очередями
// хранил хвост вечно. О замене говорит подпись у строки ТЭП.
function adoptEngineDerivedTep(result){
 const rows=result&&result.tep&&Array.isArray(result.tep.rows)?result.tep.rows:[];
 settleDerivedTail(rows);
 if(rows.length)derivedState().fresh=true;
 rows.forEach(r=>{
  if(!tep[r.key]||r.excluded)return;
  if(r.key==='underground_parking'&&r.guest_units!=null)tep[r.key].guest_units=Number(r.guest_units);
  if(SOCIAL_TEP_PRODUCTS.includes(r.key)&&r.transfer_units!=null)tep[r.key].transfer_units=Number(r.transfer_units);
 });
}

function applyInputMigrations(list){
 if(!Array.isArray(list)||!list.length)return;
 let shown=false;
 list.forEach(m=>{
  if(!m)return;
  if(m.from){delete inputs[m.from];delete fieldOrigins()['inputs.'+m.from]}
  if(m.key){
   inputs[m.key]=m.value;
   fieldOrigins()['inputs.'+m.key]={source:'migrated',text:String(m.text||'перенесено')};
   const el=document.getElementById('f_'+m.key);if(el)el.value=m.value;
   shown=true;
  }
 });
 if(shown&&typeof renderInputs==='function')renderInputs();
}
function row(label,value){return `<tr><td>${label}</td><td>${value}</td></tr>`}
// Ступени надбавки по покрытию эскроу. Пусто — строк нет вовсе: у большинства
// НКЛ ставка одна, и пустая таблица «ступеней» читалась бы как их отсутствие
// в договоре, а не как невведённые вводные.
// Лестница ставки ПФ — таблицей диапазонов, как в НКЛ: «от 100% до 110% —
// 3,47%», а не строкой через точку с запятой (владелец, 20.08.2026: «там
// должна быть лесенка как в НКЛ и выбор ставки под каждый диапазон»).
// Хранится по-прежнему строкой во вводных (pf_special_steps) — тем же
// форматом, который читает движок и обе книги: таблица здесь только
// представление строки, второго хранилища нет.
function parsePfStepsInput(){
 const found=String(inputs.pf_special_steps||'').match(/-?\d+(?:[.,]\d+)?\s*:\s*-?\d+(?:[.,]\d+)?/g)||[];
 const steps=found.map(pair=>{
  const parts=pair.split(':');
  let edge=Number(String(parts[0]).replace(',','.'));
  const rate=Number(String(parts[1]).replace(',','.'));
  if(edge>0&&edge<=3)edge*=100; // разы → проценты, как в движке
  return {edge:edge,rate:rate};
 }).filter(s=>s.edge>0&&s.rate>=0);
 steps.sort((a,b)=>a.edge-b.edge);
 return steps;
}
function pfEdgeText(v){return String(Math.round(v*100)/100).replace('.',',')}
function savePfSteps(steps){
 inputs.pf_special_steps=steps.filter(s=>s.edge>0)
  .sort((a,b)=>a.edge-b.edge)
  .map(s=>pfEdgeText(s.edge)+':'+String(s.rate).replace('.',',')).join('; ');
 const box=document.getElementById('pfStepsEditor');
 if(box){const wrap=box.parentNode;box.remove();renderPfStepsEditor(wrap);}
 refreshGroupPeeks();calculate();
}
function pfStepEdit(index,what,value){
 const steps=parsePfStepsInput();
 if(!steps[index])return;
 steps[index][what]=Number(String(value).replace(',','.'))||0;
 savePfSteps(steps);
}
function pfStepRemove(index){const steps=parsePfStepsInput();steps.splice(index,1);savePfSteps(steps);}
function pfStepAdd(){
 const steps=parsePfStepsInput();
 const last=steps[steps.length-1];
 steps.push(last?{edge:last.edge+10,rate:Math.max(0.01,Math.round(last.rate*50)/100)}:{edge:100,rate:3.47});
 savePfSteps(steps);
}
// --- График ячейками, а не строкой ------------------------------------------
//
// «Реализация некрасивая — должны быть разные поля, а не одно поле, где через
// запятую хрен пойми чего пишется» (владелец, 02.09.2026). Хранение осталось
// прежним — строка «30%@0; 40%@6», её читают и движок, и книга, — а ввод стал
// таблицей: значение, единица и срок отдельными ячейками, строки добавляются и
// убираются («график может состоять и из двух платежей, и из десяти»).
//
// Единица у графика ОДНА на все строки: движок отказывается считать график,
// смешавший доли и суммы, и переключатель сверху делает такую ошибку
// невозможной по построению, а не ловит её после.
const SCHEDULE_FIELDS={};
function parseSchedule(text){
 const out=[];
 String(text||'').split(/[;\n]+/).forEach(part=>{
  const m=/^\s*(-?[\d.,]+)\s*(%?)\s*@\s*(-?\d+)\s*$/.exec(part);
  if(!m)return;
  out.push({value:Number(m[1].replace(',','.'))||0,percent:m[2]==='%',month:parseInt(m[3],10)||0});
 });
 return out;
}
function scheduleIsPercent(rows,opts){
 if(opts.value!=='money_or_share')return true;
 return rows.length?rows.every(r=>r.percent):true;
}
function serialiseSchedule(rows,percent){
 return rows.filter(r=>Number(r.value)>0)
  .sort((a,b)=>a.month-b.month)
  .map(r=>String(r.value).replace('.',',')+(percent?'%':'')+'@'+r.month).join('; ');
}
function scheduleAnchorDate(opts){
 const start=String(inputs.project_start||INPUT_DEFAULT.project_start||'');
 if(opts.anchor!=='project_start')return '';
 return start;
}
function scheduleMonthToDate(month,opts){
 const start=scheduleAnchorDate(opts);
 if(!start)return '';
 const d=new Date(start+'T00:00:00');
 if(isNaN(d.getTime()))return '';
 d.setMonth(d.getMonth()+(Number(month)||0));
 return d.toISOString().slice(0,10);
}
function scheduleDateToMonth(value,opts){
 const start=scheduleAnchorDate(opts);
 if(!start||!value)return 0;
 const a=new Date(start+'T00:00:00'), b=new Date(value+'T00:00:00');
 if(isNaN(a.getTime())||isNaN(b.getTime()))return 0;
 return Math.max(0,(b.getFullYear()-a.getFullYear())*12+(b.getMonth()-a.getMonth()));
}
function saveSchedule(id,rows,percent){
 inputs[id]=serialiseSchedule(rows,percent);
 const box=document.getElementById('sched_'+id);
 if(box){const wrap=box.parentNode;box.remove();renderScheduleEditor(wrap,id,SCHEDULE_FIELDS[id]||{});}
 refreshGroupPeeks();calculate();
}
function scheduleEdit(id,index,what,value){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 if(!rows[index])return;
 const percent=scheduleIsPercent(rows,opts);
 if(what==='date')rows[index].month=scheduleDateToMonth(value,opts);
 else if(what==='month')rows[index].month=Math.max(0,parseInt(value,10)||0);
 else rows[index].value=Number(String(value).replace(',','.'))||0;
 saveSchedule(id,rows,percent);
}
function scheduleRemove(id,index){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 const percent=scheduleIsPercent(rows,opts);
 rows.splice(index,1);
 saveSchedule(id,rows,percent);
}
function scheduleAdd(id){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 const percent=scheduleIsPercent(rows,opts);
 const last=rows[rows.length-1];
 // Новая строка — остаток до ста процентов, если это доли: чаще всего именно
 // его и вписывают, а сумма долей обязана сходиться.
 const used=rows.reduce((sum,r)=>sum+Number(r.value||0),0);
 const rest=percent?Math.max(0,Math.round((100-used)*100)/100):0;
 rows.push({value:rest||(last?last.value:0),percent:percent,
            month:last?last.month+6:0});
 saveSchedule(id,rows,percent);
}
function scheduleUnit(id,percent){
 const rows=parseSchedule(inputs[id]);
 saveSchedule(id,rows,percent==='1');
}
// Сумма графика — проверка, а не украшение. График долями на 90% молча
// теряет десятую часть платежа, график суммами — разницу с ценой: движок
// относит её на дату сделки и говорит об этом в предупреждениях расчёта, но
// читают их после, а ошибку делают здесь. Ограничение на входе и сходимость
// итога — разные проверки, и первая не заменяет вторую.
function scheduleAmount(v){
 return Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:2});
}
function scheduleTotalLine(id){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 if(!rows.length)return '';
 const percent=scheduleIsPercent(rows,opts);
 const used=Math.round(rows.reduce((sum,r)=>sum+Number(r.value||0),0)*100)/100;
 let bad=false,text='';
 if(percent){
  bad=Math.abs(used-100)>0.01;
  text='Сумма долей '+scheduleAmount(used)+'%'+(bad?' — должно быть 100%':'');
 } else {
  const field=opts.total_field;
  const name=opts.total_label||'заданная сумма';
  const base=field?Math.round((Number(inputs[field]??INPUT_DEFAULT[field]??0)||0)*100)/100:0;
  text='Сумма платежей '+scheduleAmount(used)+' млн ₽';
  // Незаданная база — это «сверить не с чем», а не «сходится»: зелёная
  // строка на пустоте читается как пройденная проверка.
  if(!field)return '<span style="color:#777">'+text+'</span>';
  if(!(base>0))return '<span style="color:#777">'+text+'. Сверить не с чем — '+name+' не задана</span>';
  const gap=Math.round((used-base)*100)/100;
  if(Math.abs(gap)<0.01){
   text+=' — сходится: '+name+' '+scheduleAmount(base);
  } else {
   bad=true;
   text+=', '+name+' '+scheduleAmount(base)+' — '+
    (gap<0?'не хватает ':'лишних ')+scheduleAmount(Math.abs(gap))+' млн ₽'+
    (gap<0?'; остаток ляжет в дату сделки':'; излишек снимется в дату сделки минусом');
  }
 }
 return '<span style="color:'+(bad?'#a33':'#777')+'">'+text+'</span>';
}
// Цену правят соседним полем, а редактор графика при этом не перерисовывается:
// строка «сходится», посчитанная от прежней цены, неотличима от верной.
function refreshScheduleTotals(){
 Object.keys(SCHEDULE_FIELDS).forEach(id=>{
  const box=document.getElementById('schedtotal_'+id);
  if(box)box.innerHTML=scheduleTotalLine(id);
 });
}
function renderScheduleEditor(wrap,id,opts){
 SCHEDULE_FIELDS[id]=opts||{};
 const rows=parseSchedule(inputs[id]);
 const percent=scheduleIsPercent(rows,opts);
 const money=opts.value==='money_or_share';
 const byDate=opts.anchor==='project_start';
 const cell='padding:2px 8px 2px 0';
 let html='<table style="border-collapse:collapse;margin-top:2px">'+
  '<tr><th style="text-align:left;'+cell+';font-size:11px;color:#777">'+(opts.value_label||'ЗНАЧЕНИЕ').toUpperCase()+'</th>'+
  '<th style="text-align:left;'+cell+';font-size:11px;color:#777">'+(opts.when_label||'СРОК').toUpperCase()+'</th><th></th></tr>';
 rows.forEach((r,i)=>{
  const when=byDate
   ? '<input type="date" value="'+scheduleMonthToDate(r.month,opts)+'" onchange="scheduleEdit(\''+id+'\',' +i+',\'date\',this.value)">'
     +' <span style="color:#777;font-size:11px">'+r.month+' мес. от начала проекта</span>'
   : '<input type="number" min="0" step="1" value="'+r.month+'" style="width:70px" onchange="scheduleEdit(\''+id+'\','+i+',\'month\',this.value)"> мес.'
     +(scheduleMonthToDate(r.month,opts)?'':'');
  html+='<tr><td style="'+cell+'"><input type="number" step="any" min="0" value="'+String(r.value).replace('.',',')+'" style="width:92px" '+
   'onchange="scheduleEdit(\''+id+'\','+i+',\'value\',this.value)">'+(percent?' %':' млн ₽')+'</td>'+
   '<td style="'+cell+'">'+when+'</td>'+
   '<td><button type="button" class="tep-refill" title="убрать строку" onclick="scheduleRemove(\''+id+'\','+i+')">×</button></td></tr>';
 });
 html+='</table>';
 html+='<div id="schedtotal_'+id+'" style="margin-top:3px;font-size:11px">'+scheduleTotalLine(id)+'</div>'+'<div style="margin-top:4px"><button type="button" class="tep-refill" onclick="scheduleAdd(\''+id+'\')">+ строка</button>'+
  (money?' <button type="button" class="tep-refill" onclick="scheduleUnit(\''+id+'\',\''+(percent?'0':'1')+'\')">'+
    (percent?'вводить суммами, млн ₽':'вводить долями, %')+'</button>':'')+
  (rows.length?' <button type="button" class="tep-refill" onclick="saveSchedule(\''+id+'\',[],'+(percent?'true':'false')+')">очистить</button>'
    :' <span style="color:#777">графика нет — считается как раньше</span>')+'</div>';
 const box=document.createElement('div');box.id='sched_'+id;box.innerHTML=html;
 wrap.appendChild(box);
}
function renderPfStepsEditor(wrap){
 const steps=parsePfStepsInput();
 const special=String(inputs.pf_special_pct??INPUT_DEFAULT.pf_special_pct??'').replace('.',',');
 let html='<table style="border-collapse:collapse;margin-top:2px">'+
  '<tr><th style="text-align:left;padding:2px 10px 2px 0;font-size:11px;color:#777">ПОКРЫТИЕ ЭСКРОУ</th>'+
  '<th style="text-align:left;padding:2px 8px;font-size:11px;color:#777">СТАВКА, % ГОДОВЫХ</th><th></th></tr>';
 if(steps.length){
  // Ниже первой ступени лестница договора не описывает ничего — действует
  // обычная специальная ставка, и строка называет её поле по имени.
  html+='<tr><td style="padding:2px 10px 2px 0;color:#777">ниже '+pfEdgeText(steps[0].edge)+'%</td>'+
   '<td style="padding:2px 8px;color:#777">'+special+'% — «Ставка ПФ при покрытии 1×»</td><td></td></tr>';
 }
 steps.forEach((s,i)=>{
  const upper=steps[i+1]?'– '+pfEdgeText(steps[i+1].edge)+'%':'% и выше';
  html+='<tr><td style="padding:2px 10px 2px 0;white-space:nowrap">от '+
   '<input type="number" step="any" min="0" value="'+s.edge+'" style="width:64px" '+
   'onchange="pfStepEdit('+i+',\'edge\',this.value)">'+(steps[i+1]?'% '+upper:upper)+'</td>'+
   '<td style="padding:2px 8px"><input type="number" step="any" min="0" value="'+s.rate+'" style="width:72px" '+
   'onchange="pfStepEdit('+i+',\'rate\',this.value)">%</td>'+
   '<td><button type="button" class="tep-refill" title="убрать ступень" onclick="pfStepRemove('+i+')">×</button></td></tr>';
 });
 html+='</table><div style="margin-top:4px"><button type="button" class="tep-refill" onclick="pfStepAdd()">+ ступень</button>'+
  (steps.length
   ?' <button type="button" class="tep-refill" onclick="savePfSteps([])">без лестницы — одна ставка</button>'
   :' <span style="color:#777">лестницы нет — весь долг под эскроу идёт по ставке выше</span>')+'</div>';
 const box=document.createElement('div');box.id='pfStepsEditor';box.innerHTML=html;
 wrap.appendChild(box);
}

function pfStepRows(f){
 const steps=(f&&f.pf_special_steps)||[];
 if(!steps.length)return '';
 return steps.map(st=>row(
  'Ступень: покрытие от '+String(st.coverage_from_pct).replace('.',',')+'%',
  String(st.rate_pct).replace('.',',')+'% · '+(st.months||0)+' мес.')).join('');
}

function renderPhaseComparison(){
 if(!phaseBundle||phaseBundle.mode!=='phased'){phaseComparisonCard.style.display='none';return}
 const c=phaseBundle.comparison||[],cons=phaseBundle.consolidated;
 // Состав, порядок и числа таблицы решает движок (`phase_comparison_table`):
 // тот же ответ печатает PDF, и две раскладки одного сравнения не разойдутся.
 // Экран только форматирует число по его виду.
 const table=cons.comparison_table||{columns:c.map(x=>x.name),blocks:[]};
 phaseComparisonHead.innerHTML=`<tr><th>Показатель</th>${table.columns.map(n=>`<th>${escapeHtml(n)}</th>`).join('')}<th>Свод</th></tr>`;
 const fmt=(r,v)=>{
  if(v==null||v==='')return '—';
  if(r.kind==='money')return money(v);
  if(r.kind==='qty')return num(v)+' '+(r.unit||'');
  if(r.kind==='th')return num2(v)+' тыс ₽/м²';
  if(r.kind==='pct')return pct(v);
  if(r.kind==='mult')return mult(v);
  if(r.kind==='date')return dateRu(v);
  return String(v);
 };
 // Сырые числа итогов и слагаемых уходят в разметку (`data-v`): проверка
 // сверяет итог с суммой слагаемых по ним, а не по округлённому тексту.
 const td=(r,v)=>`<td${r.group?` data-v="${v}"`:''}>${fmt(r,v)}</td>`;
 const span=table.columns.length+2;
 // Делители удельных — одна подпись таблицы мелким шрифтом, а не строки
 // тела: крупная «Делитель…» среди показателей читалась как ещё одно число.
 // Метры — целыми, как в PDF (`_phase_comparison_pdf`).
 const divisors=(table.divisors||[]).length
  ?`<tr class="pc-caption"><th colspan="${span}"><small class="pc-divisors">Удельные показатели — делители: ${table.divisors.map(d=>escapeHtml(d.label)+': '+
     table.columns.map((n,i)=>escapeHtml(n)+' '+num(Math.round(d.values[i]||0))).concat('свод '+num(Math.round(d.total||0))).join(' · ')+
     ' '+escapeHtml(d.unit||'')).join('<br>')}</small></th></tr>`
  :'';
 const label=r=>r.label+(r.rate_input!=null?` (вводная ${num2(r.rate_input)} тыс ₽/м²)`:'');
 phaseComparisonBody.innerHTML=divisors+table.blocks.map(b=>
  `<tr class="pc-block" data-block="${b.key}"><th colspan="${span}"><span>${b.title}</span></th></tr>`+
  b.rows.map(r=>r.kind==='note'
   // Пояснение — строка во всю ширину, а не «—» в каждой колонке.
   ?`<tr data-block="${b.key}" class="pc-note"><td colspan="${span}"><span>${escapeHtml(r.label)}</span></td></tr>`
   :`<tr data-block="${b.key}"${r.role?` class="pc-${r.role}"`:''}${r.group?` data-group="${r.group}"`:''}><td>${label(r)}</td>`+
   r.values.map(v=>td(r,v)).join('')+td(r,r.total)+'</tr>').join('')
 ).join('');
 renderPhaseEscrowCharts();
 // Причина, по которой долг сменил очередь — или по которой не сменил.
 // Обнулённый долг первой очереди рядом с выросшим долгом второй без этой
 // строки читается как ошибка расчёта.
 const note=document.getElementById('phaseDebtCarryNote');
 if(note){
  const carry=phaseBundle.debt_carry||(cons&&cons.debt_carry)||null;
  if(carry&&carry.note){
   note.textContent=carry.note;
   note.className='note '+(carry.applied?'phase-total-ok':'phase-total-bad');
   note.style.display='block';
  }else if(table.has_debt){
   note.textContent='Перенос долга между очередями выключен: непогашенный остаток остаётся на очереди, которая его набрала, и означает дефолт по её линии. Признак — на вкладке «Очерёдность».';
   note.className='note';note.style.display='block';
  }else{note.style.display='none'}
 }
}
// Свод складывает эскроу и долг всех очередей, и по нему не видно, какая
// очередь не рассчиталась: у каждой своя дата раскрытия. Поэтому график по
// очередям отдельный — тем же рисовальщиком и на тех же числах сервера.
//
// Легенда у него та же и из того же места. У сводного графика и у отчёта она
// стоит разметкой, потому что карточка написана руками; карточки очередей
// собирает скрипт, и подставленная сюда легенда была потеряна — шесть линий
// без единой подписи. Правило прежнее: легенда объявлена там же, где график
// один, — движком; здесь она просто доезжает до собранной разметки.
const ESCROW_LEGEND_HTML=`__DEVELOPAID_ESCROW_LEGEND__`;
function renderPhaseEscrowCharts(){
 // Ровно один набор на поверхность: на вкладке «Финансирование» и в отчёте,
 // оба раза ПОД сводным графиком, к которому относится оговорка «линии
 // очередей — ниже». Третья копия жила в разделе «Очереди проекта» того же
 // отчёта — одна и та же картинка дважды в одном документе (владелец,
 // 05.09.2026: «зачем графики эскроу и долга дважды»). PDF так и печатал с
 // самого начала: блок очередей идёт сразу за сводным.
 const boxes=['financeEscrowPhases','reportEscrowPhases']
   .map(id=>document.getElementById(id)).filter(Boolean);
 if(!boxes.length)return;
 const items=((phaseBundle&&phaseBundle.phases)||[]).map((p,i)=>{
  const rows=((p.result||{}).finance||{}).rows||[];
  const cover=(((p.result||{}).report||{}).financing||{}).escrow_cover||{};
  const svg=escrowCoverSvg(rows,cover);
  if(!svg)return '';
  const lines=escrowCoverLines(cover);
  return `<div class="phase-escrow" style="margin-bottom:20px"><div class="section-title">${escapeHtml(p.name||('Очередь '+(i+1)))}</div>${svg}${ESCROW_LEGEND_HTML}`
   +(lines?`<div class="note">${lines}</div>`:'')+'</div>';
 }).filter(Boolean);
 // Свод складывает эскроу и долг РАЗНЫХ договоров: на четырёх очередях он
 // даёт покрытие 0,58×, когда у первой 0,68×, а у третьей ноль. График
 // читается так, будто очередь стартует с эскроу в десять миллиардов
 // (владелец, 04.09.2026: «2 очередь стартует сразу с выборки и эскроу не с
 // 0 а с 10 млрд, а 3 с 30»). Числа верны, неверно место: линии очередей
 // теперь стоят прямо под сводным графиком, а не на соседней вкладке.
 const head=items.length?'<div class="section-title" style="margin-top:18px">По очередям — у каждой свой договор</div>':'';
 boxes.forEach(box=>{box.innerHTML=head+items.join('')});
}
function selectReportView(view){
 if(!phaseBundle||phaseBundle.mode!=='phased')return;reportView=view;phaseComparisonCard.style.display='none';
 if(view==='all')lastResult=phaseBundle.consolidated;
 else if(view==='compare'){lastResult=phaseBundle.consolidated}
 else{const i=Number(String(view).replace('phase',''))-1;if(phaseBundle.phases[i])lastResult=phaseBundle.phases[i].result}
 renderResult();renderPhaseReportControls();if(view==='compare'){phaseComparisonCard.style.display='block';renderPhaseComparison()}
}
function renderPhaseReportControls(){
 if(!document.getElementById('phaseReportControls'))return;
 if(!phaseBundle||phaseBundle.mode!=='phased'){phaseReportControls.style.display='none';phaseComparisonCard.style.display='none';return}
 phaseReportControls.style.display='flex';
 const b=[['all','Весь проект'],...phaseBundle.phases.map((p,i)=>[`phase${i+1}`,p.name]),['compare','Сравнение очередей']];
 phaseReportControls.innerHTML=b.map(([k,l])=>`<button class="btn ${reportView===k?'active':''}" onclick="selectReportView('${k}')">${l}</button>`).join('')
}
// Предложный падеж сразу, а не выведенный заменой окончаний: «в марте 2031»
// читается человеком, и склонять его правилом «я→е, а→е» — способ однажды
// получить «в мае» из «мая» и «в феврале» из чего угодно.
const RU_MONTHS_IN=['январе','феврале','марте','апреле','мае','июне',
                    'июле','августе','сентябре','октябре','ноябре','декабре'];
function ruMonth(iso){
 const m=/^(\d{4})-(\d{2})/.exec(String(iso||''));
 if(!m)return '';
 const index=Number(m[2])-1;
 return index>=0&&index<12?`${RU_MONTHS_IN[index]} ${m[1]}`:'';
}
// Плашка о непогашенном ПФ. Прежде она складывала все очереди в одну кучу —
// «в даты РВЭ очередей: долг перед раскрытием столько-то» — и из неё нельзя
// было понять ни какая очередь не рассчиталась, ни куда ушёл её долг. А с
// включённым переносом фраза «остаток гасится продажами после ввода» стала
// прямо неверной: остаток уходит на линию следующей очереди, а продажи
// остаются застройщику. Теперь плашка говорит по очередям и называет, что
// куда и когда ушло.
// Что случилось с ПФ каждой очереди — один разбор на все поверхности экрана.
// Плашка о непогашенном долге и оговорка у чистой прибыли отвечают на один и
// тот же вопрос «был ли дефолт», и две проверки на него однажды разойдутся:
// обе будут выглядеть верными, а говорить разное про один расчёт.
function pfQueueOutcomes(){
 const phased=phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1;
 if(!phased)return [];
 const rows=phaseBundle.comparison||[],phases=phaseBundle.phases||[];
 const carry=phaseBundle.debt_carry||(phaseBundle.consolidated||{}).debt_carry||null;
 const at={};((carry&&carry.transfers)||[]).forEach(t=>{at[t.from]=t});
 const out=[];
 rows.forEach((row,i)=>{
  const fin=(((phases[i]||{}).result||{}).report||{}).financing||{};
  const carried=Number(row.debt_carried_out||0);
  const gap=Number(fin.rve_unpaid||0)||carried;
  const swept=Number(fin.project_cash_sweep||0);
  if(!(gap>500000)&&!(swept>500000))return;
  const name=String(row.name||('О'+(i+1)));
  if(swept>500000&&!(gap>500000)){
   // Долг закрыт не эскроу, а накопленными продажами прошлых очередей.
   // Без этой строки он исчезает без объяснения: нехватка была, а дефолта
   // нет — и непонятно, чем закрыли.
   out.push({kind:'swept',name:name,gap:swept,when:ruMonth(fin.project_cash_sweep_month),
             index:i,last:i===rows.length-1});
  }else if(carried>500000){
   out.push({kind:'carried',name:name,gap:gap,when:ruMonth((at[i+1]||{}).at),
             to:String((rows[i+1]||{}).name||('О'+(i+2))),index:i});
  }else{
   out.push({kind:'default',name:name,gap:gap,when:ruMonth(fin.default_date),
             swept:swept,index:i,last:i===rows.length-1});
  }
 });
 return out;
}

// Дефолт в модели — факт о расчёте, и он старше любой плитки: прибыль после
// него посчитана на допущении, что банк дал проекту продолжиться. Прежде это
// говорилось только когда долг оставался непогашенным на КОНЕЦ горизонта;
// если остаточные продажи его закрывали, экран печатал прибыль голым числом
// (владелец, 30.08.2026: «значит нельзя писать и чистую прибыль»).
function modelDefaultInfo(r){
 const phased=phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1;
 if(phased)return pfQueueOutcomes().find(o=>o.kind==='default')||null;
 const f=(r&&r.report&&r.report.financing)||{};
 const gap=Number(f.rve_unpaid||f.rve_pf_shortfall||0);
 if(!(gap>500000))return null;
 return {kind:'default',name:'',gap:gap,when:ruMonth(f.default_date),index:0,last:true};
}

function pfRveWarningHtml(r){
 const phased=phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1;
 if(!phased){
  const f=r.report.financing||{},gap=Number(f.rve_unpaid||f.rve_pf_shortfall||0);
  if(!(gap>500000))return '';
  const when=ruMonth(f.default_date);
  return `<b>Дефолт${when?' в '+when:' в дату раскрытия'}: раскрытого эскроу не `
   +`хватило на ${money(gap)}.</b> Дальше нужна реструктуризация — её условий `
   +'модель не знает и считает по допущению, что остаток долга гасится '
   +DEFAULT_REPAYMENT_WORDS.single+'.';
 }
 const outcomes=pfQueueOutcomes();
 const carry=phaseBundle.debt_carry||(phaseBundle.consolidated||{}).debt_carry||null;
 const lines=outcomes.map(o=>o.kind==='swept'
  ?`<b>${escapeHtml(o.name)}</b>: раскрытого эскроу не хватило, но банк забирал `
   +`долю поступлений прошлых очередей — за период это <b>${money(o.gap)}</b>, `
   +`и долг закрыт.`
  :o.kind==='carried'
  ?`<b>${escapeHtml(o.name)}</b>: при раскрытии эскроу не погашено `
   +`<b>${money(o.gap)}</b> — этот долг принял ПФ <b>${escapeHtml(o.to)}</b>`
   +`${o.when?' в '+o.when:''}.`
  // Банк не ждёт продаж: в дату раскрытия он либо переоформляет долг, либо
  // фиксирует дефолт (владелец, 30.08.2026). Прежде здесь стояло «остаток
  // гасится её собственными продажами после ввода» — состояние, которого в
  // жизни не бывает.
  :`<b>${escapeHtml(o.name)}</b>: раскрытого эскроу`
   +`${o.swept>500000?' и забранных банком поступлений прошлых очередей ('+money(o.swept)+')':''}`
   +` не хватило на <b>${money(o.gap)}</b> — по модели это `
   +`<b>дефолт${o.when?' в '+o.when:' в дату раскрытия'}</b>.`);
 const firstDefault=outcomes.find(o=>o.kind==='default')||null;
 if(!lines.length)return '';
 const ending=Number(((phaseBundle.consolidated||{}).finance||{}).ending_pf||0);
 if(firstDefault){
  // План показываем, но называем несостоявшимся (решение владельца,
  // 30.08.2026): после дефолта банк финансирование не продолжает, и числа
  // следующих очередей — замысел, а не результат.
  if(carry&&carry.applied===false&&carry.note)lines.push(escapeHtml(String(carry.note)));
  else if(!carry&&!firstDefault.last)lines.push('Перенос долга на следующую очередь не включён — признак на вкладке «Очерёдность».');
  // Дату не повторяем: она названа строкой выше, а «после январе 2030» —
  // родительный падеж там, где список месяцев даёт предложный. Две формы
  // одного слова ради одной фразы не заводим.
  // Дефолт называем, но проект не хороним (владелец, 30.08.2026): «не закрывай,
  // лучше просто показывай, что по факту модель — дефолт на такой-то очереди и
  // надо будет согласие банка на перенос долга на следующую или
  // реструктуризация». Вариантов у банка много, чаще всего долг просто
  // переоформляют на следующую очередь; а если эскроу не наполнился из-за
  // продаж, это форс-мажор, которого в НКЛ и не могло быть заложено. Условий
  // реструктуризации модель не знает — считает прежним допущением и говорит
  // об этом вслух.
  // Последней очереди передавать долг некуда, и предлагать это ей нельзя:
  // движок такой перенос и не делает («перенос был бы фикцией»), а плашка
  // звала включить признак, который ничего бы не изменил (владелец,
  // 30.08.2026: «а ничего что очередей две всего?»).
  lines.push(firstDefault.last
   ?`<b>Понадобится согласие банка.</b> Переносить долг некуда — `
    +`<b>${escapeHtml(firstDefault.name)}</b> последняя очередь, и остаётся только `
    +'реструктуризация: её условий модель не знает и считает по допущению, что '
    +'остаток долга гасится '+DEFAULT_REPAYMENT_WORDS.phased+'; пени и требование она '
    +'не считает.'
   :'<b>Понадобится согласие банка</b> — на перенос долга на следующую '
    +'очередь или на реструктуризацию. Дальше модель считает по допущению, что '
    +'остаток долга гасится '+DEFAULT_REPAYMENT_WORDS.phased+'; пени и требование она '
    +'не считает.');
  lines.push(ending>500000
   ?`<b>По итогу всех очередей</b> при этом допущении непогашенным остаётся <b>${money(ending)}</b>.`
   :'<b>По итогу всех очередей</b> при этом допущении долг погашен полностью.');
 }else{
  // Итог сказан заголовком, когда он бездетален («долг закрыт»). Строка с
  // числом остаётся только там, где число есть: голое «погашен полностью»
  // сразу под тем же заголовком — это одно и то же дважды подряд.
  if(ending>500000)lines.push(
   `<b>По итогу всех очередей</b> непогашенным остаётся <b>${money(ending)}</b>.`);
  // «Долг погашен полностью» читается как «всё в порядке», хотя весь план
  // держится на согласии банка. Вариантов у него больше, чем можно
  // предусмотреть, и каждый предусмотренный выглядел бы предсказанием
  // (владелец, 30.08.2026: «банк может переложить долг на следующую очередь,
  // но сделать кэш-свип на первую. Эти варианты все не предусмотреть. Главное
  // видимо увидеть, что проблемная очередь есть»). Поэтому называем факт и
  // границу метода, а решение за банк не выдумываем.
  lines.push('<b>Но проблемные очереди есть, и план держится на согласии '
   +'банка.</b> Перенос долга и кэш-свип — то, о чём с ним договариваются; '
   +'вместо них он может потребовать дополнительное обеспечение, поручительство '
   +'или реструктурировать долг на своих условиях. Этих вариантов модель не '
   +'считает.');
 }
 // Заголовок называет ОХВАТ и МОМЕНТ. «Эскроу не погашает ПФ полностью» —
 // утверждение про весь проект, а речь о ОДНОЙ очереди в ОДНУ дату; двумя
 // строками ниже стояло «по итогу всех очередей долг погашен полностью», и
 // читатель получал два противоположных предложения об одном («как это
 // понимать?», владелец, 07.09.2026). Тот же вопрос, что у «суммы под именем
 // момента»: если у строки есть ответ «у каждой очереди своё», подпись врёт.
 const title=firstDefault
  ?`Модель даёт дефолт на очереди ${escapeHtml(firstDefault.name)}.`
  :ending>500000
  ?'Долг по проекту закрыт не полностью.'
  :'Долг по проекту закрыт, но не каждой очередью в свой срок.';
 return `<div style="margin-bottom:6px"><b>${title}</b></div>`
  +lines.map(line=>`<div style="margin-top:4px">${line}</div>`).join('');
}
// Плашка следует за РЕЗУЛЬТАТОМ, а не за правкой поля: её зовёт `renderResult`,
// и только он. Перерисовка полей без свежего расчёта оставляет её пустой — это
// верно, а не досадно: прежнее число под новыми вводными читалось бы как
// посчитанное, а «устаревшее число хуже пустого» здесь то же правило, что у
// сводки в заголовке группы.
// Плашка НЕ сверяет норматив с гаражом: сверять их нельзя. Приобъектная
// стоянка — асфальт в благоустройстве, гараж объекта — решение девелопера, и
// «сходится» между ними значило бы, что мы считаем норматив планом стройки.
// Подпись под полями пишется и БЕЗ свежего расчёта — этим она и отличается от
// плашки свода. Плашка следует за результатом намеренно: прежнее число под
// новыми вводными читалось бы как посчитанное. А подпись отвечает на другое —
// «чьё то, что стоит в поле сейчас», и у неё есть строка на каждое состояние,
// включая «расчёта не было». Пока её звал только `renderResult`, ячейка на
// перерисованной форме оставалась ПУСТОЙ: функция, написанная объяснять
// молчание, молчала сама — второй раз в этом же месте (замер в Chromium,
// 09.09.2026: `before` пусто, а вызов руками даёт «объект включён, но расчёт
// этого ещё не видел»). Ячейки создаёт форма, поэтому и писатель зовётся
// оттуда же.
function landscapingRateNote(){
 // Ни одного своего деления: обе производные посчитал движок. Второй счёт той
 // же величины однажды разошёлся бы с первым, и обе строки выглядели бы
 // верными — правило то же, что у разбивки выручки очереди.
 const s=(lastResult||{}).summary||{};
 const area=Number(s.landscaping_area_sqm);
 // Ноль двора — это ответ методики, а не отсутствие расчёта, и у него есть
 // основание: у нежилого проекта населения нет вовсе. Пока обе половины
 // отвечали одной фразой, посчитанный ноль читался как «нажмите пересчитать».
 if(!isFinite(area)||area<=0){
  // При ЗАДАННОЙ ставке основание двора советовало «задайте ставку на метр
  // ГНС» — то есть сделать то, что уже сделано. У двора и у денег основания
  // разные, и отвечать надо тем, которым посчитаны деньги.
  if(s.landscaping_by_rate&&s.landscaping_money_basis){
   return 'Двор от населения не считается — деньги идут ставкой: '+String(s.landscaping_money_basis)+'.';
  }
  return s.landscaping_basis?String(s.landscaping_basis)
                            :'Двор ещё не посчитан — нажмите «Пересчитать модель».';
 }
 // Удельное число здесь НЕ повторяется: оно стоит в соседнем поле, а два
 // одинаковых показателя рядом — это и есть «слишком много текста». Подпись
 // отвечает на своё: сколько двора и откуда он взялся.
 let text='Двор '+num(Math.round(area))+' м² · '+(s.landscaping_basis||'');
 if(s.landscaping_by_rate)text+=' · в деньги не идёт: ниже задана своя ставка на метр ГНС';
 // Свод «Статистики» считает на метр ГНС — ровно та база, что у соседнего
 // поля с тех пор, как она сведена. Прежняя оговорка «у него база метр дома,
 // сравнивайте с полем ниже» снята вместе с расхождением, которое её
 // требовало: сравнивать теперь можно прямо.
 const cls=String(inputs.project_class||''),row=cls?classStatsRow(cls,'landscaping_th_per_sqm'):null;
 if(row&&row.recommended_rub_m2!=null){
  text+=' · свод «Статистики» '+(row.recommended_rub_m2/1000).toLocaleString('ru-RU',{maximumFractionDigits:2})
   +' тыс ₽/м² ГНС';
 }
 return text;
}

function landscapingHouseRateNote(){
 // Ни одного своего деления: показатель посчитал движок. Подпись отвечает на
 // одно — чьё число стоит в поле сейчас; база названа единицей поля, и
 // повторять её здесь значит сказать одно дважды.
 const s=(lastResult||{}).summary||{};
 const own=Number(inputs.landscaping_gns_th_per_sqm||0);
 const rate=Number(s.landscaping_per_gns_th);
 // У подписи нет состояния, в котором она молчит: пустое место под полем
 // читается как ответ, а ответов тут три и они разные.
 // «Расчёта ещё нет» и «расчёт дал ноль» — разные ответы, и второй здесь
 // обычен: у нежилого проекта двор мерить населением нечем, методика честно
 // отвечает нулём, а подпись говорила «расчёта ещё нет» — то есть винила
 // кнопку за ответ методики. Был расчёт или нет, говорит основание: движок
 // кладёт его в свод всегда, и пустым оно бывает только до первого счёта.
 if(!isFinite(rate)||rate<=0){
  const counted=!!String(s.landscaping_basis||'');
  if(!counted){
   return own>0?'Задано руками. Расчёта ещё нет.'
               :'Считает методика класса. Расчёта ещё нет.';
  }
  if(own>0)return 'Задано руками, но метров, на которые ставка множится, в расчёте нет.';
  // У проекта без жилья ноль — не «методика дала ноль», а её ответ, и
  // причину называет движок (`yard_gap_reason`): у гостиницы двор в ставке
  // здания, у чисто нежилого жителей нет, а ставка объекта — СМР без двора
  // (владелец, 21.09 и 06.10.2026). Своего текста у страницы нет.
  const money=String(s.landscaping_money_basis||'');
  if(/^нежилой проект: /.test(money)){
   const why=money.replace(/^нежилой проект: /,'');
   return why.charAt(0).toUpperCase()+why.slice(1)+'. Вписанная здесь ставка её перебьёт.';
  }
  return 'Методика класса дала ноль: '+String(s.landscaping_basis)
   +'. Пока ставка здесь не задана, благоустройства в расчёте нет.';
 }
 if(own>0){
  // Число здесь — показатель МЕТОДИКИ, а не применённый: применённый равен
  // введённому по построению, и подпись обещала бы то, что уже стоит в поле.
  const back=Number(s.landscaping_by_class_th);
  return 'Задано руками. Очистите поле — вернётся методика класса'
   +(isFinite(back)&&back>0?' ('+back.toLocaleString('ru-RU',{maximumFractionDigits:2})+')':'')+'.';
 }
 return 'Считает методика класса (в «Настройках класса»). Своё число её перебьёт.';
}

// Счётный показатель стоит В САМОМ ПОЛЕ, а не только в подписи под ним
// (владелец, 15.09.2026: «во вводных обратном счетом получалась цифра
// стоимости на гнс, которую можно было при желании поменять руками»).
// Вводная при этом остаётся НУЛЁМ, и это не половинчатость: ноль здесь и
// значит «считает методика класса». Записанное в состояние число методику
// заменило бы снимком — смена класса его больше не двигала бы, и поле
// замерло бы ровно так, как замирал паркинг; а округление до сотых стоит
// 39 тыс ₽ на умолчаниях (2,85 × 140 381 против 400 125 тыс ₽ методики).
// Паркинг помечает поставленное нормой потому, что там число ПИШЕТСЯ; здесь
// оно не пишется вовсе, и помечать нечего — чьё оно, говорит подпись.
function renderLandscapingHouseRateValue(){
 const el=document.getElementById('f_landscaping_gns_th_per_sqm');
 // Поле перерисовывается ПОСРЕДИ ввода — перерисовать набранное значит
 // отобрать у человека то, что он печатает.
 if(!el||document.activeElement===el)return;
 const own=Number(inputs.landscaping_gns_th_per_sqm||0);
 if(own>0){delete el.dataset.derived;el.value=own;return;}
 const rate=Number(((lastResult||{}).summary||{}).landscaping_per_gns_th);
 // Расчёта ещё нет — поле пустое, а не нулевое: ноль читается как «ноль
 // рублей» там, где стоит статья на 400 млн. Число — точкой, без разрядов:
 // `input[type=number]` русскую запятую не принимает и молча обнуляет поле.
 el.value=isFinite(rate)&&rate>0?String(Math.round(rate*100)/100):'';
 // Пометка «здесь показатель, а не ввод» — её читает сбор формы в `calculate`.
 el.dataset.derived='1';
}

// Статья, посчитанная нулём, из структуры расходов исчезает целиком —
// нулевые строки в неё не попадают, — и её отсутствие читается как ответ
// методики «благоустройства здесь не нужно». Фразу собирает движок
// (`landscaping_gap`), экран её только печатает: второй текст об одной
// пустоте разошёлся бы с отчётом молча.
function landscapingGapRow(){
 const gap=String((((lastResult||{}).summary)||{}).landscaping_gap||'');
 if(!gap)return '';
 return '<tr class="sub"><td colspan="5" style="color:#a33">'+escapeHtml(gap)+'</td></tr>';
}

function renderLandscapingRateNote(){
 const box=document.getElementById('landscapingRateNote');
 if(box)box.textContent=landscapingRateNote();
 renderLandscapingHouseRateValue();
 // Обе подписи пишет один вызов: второй писатель пришлось бы звать из тех же
 // двух мест — формы и результата, — и один из них однажды отстал бы.
 const own=document.getElementById('landscapingHouseRateNote');
 if(own)own.textContent=landscapingHouseRateNote();
}

function renderObjectParkingFieldNotes(){
 OBJECT_PARKING_PREFIXES.forEach(prefix=>{
  const cell=document.getElementById('parkNorm_'+prefix);
  if(!cell)return;
  cell.textContent=objectParkingFieldNote(prefix);
  // Красным — только ДЕФИЦИТ: перебор это решение человека, а не ошибка
  // (владелец, 13.09.2026: «может там хотя бы красным писать уведомление…
  // или наоборот если руками правишь, то может возникнуть дефицит»).
  // Красное на обоих случаях сразу перестало бы различать их вовсе.
  // Разрыв берётся у `objectParkingGap` — у того же счёта, что и текст:
  // два ответа на одну разницу однажды разошлись бы, и подпись говорила бы
  // «дефицит» спокойным серым.
  const own=(projectParking().own)||[];
  const item=own.find(o=>o&&o.prefix===prefix);
  const gap=item?objectParkingGap(item):null;
  const short=!!(gap&&gap.required>0&&gap.diff<0);
  cell.style.color=short?'#a33':'#777';
 });
}

// Подпись под парой проекта пишется отдельным вызовом: её читатели — форма,
// ответ расчёта и пересчёт ТЭП — зовут её рядом с подписями объектов.
function renderUndergroundFieldNote(){
 const cell=document.getElementById('parkNorm_'+PROJECT_PARKING_KEY);
 if(!cell)return;
 const note=undergroundFieldNote();
 // Гараж проекта — главный числитель обеспеченности, и она стоит под ним.
 const provision=parkingProvisionText();
 cell.textContent=[note.text,provision?'Обеспеченность парковкой: '+provision+'.':'']
  .filter(Boolean).join(' ');
 cell.style.color=note.short?'#a33':'#777';
}

// Подпись под парой «места ↔ площадь» проекта: чьё число стоит в поле и
// что с ним будет. Норма названа числом ВСЕГДА, в том числе под вписанным
// руками, — это ориентир, по которому человек видит, насколько ушёл от
// норматива (владелец, 05.10.2026: «оставив серый ориентир для
// предупреждения»). Дефицит красным, перебор — спокойно: перебор это решение.
function undergroundFieldNote(){
 if(inputs.underground_parking_disabled)
  return {text:'Подземного паркинга нет — потребность закрывает наземный.',short:false};
 if(withoutHousing())return {text:'',short:false};
 const p=parkingRequirement();
 if(!p||!(p.spaces>0))
  return {text:'Норматив появится после расчёта ТЭП: мест считается от площади квартир и коммерции.',short:false};
 const per=undergroundAreaPerSpace();
 const normSpaces=Math.round(p.spaces);
 const normArea=Math.round(p.gns||p.spaces*per);
 const norm=`По нормативу: ${num(normSpaces)} м/м · ${num(normArea)} м²`;
 if(!parkingByHand(PROJECT_PARKING_KEY))
  return {text:norm+'. Оба числа выше поставил норматив — они следуют за ТЭП. Впишите своё, чтобы перебить.',short:false};
 const spaces=Number(inputs.underground_manual_spaces||0);
 const gap=spaces-normSpaces;
 const diff=gap<0?` — дефицит ${num(-gap)} м/м`:gap>0?` — на ${num(gap)} м/м больше положенного`:'';
 return {text:`Задано руками: ${num(spaces)} м/м${diff}. ${norm}. Правка ТЭП вернёт норматив; очистить поле — вернуться к нему сейчас.`,short:gap<0};
}

function renderObjectParkingNote(){
 // Норма ЗАПОЛНЯЕТ поле, а не только объясняется под ним. Пишется и во
 // вводные, и в само поле: перерисовывать форму целиком нельзя — она
 // перерисовывается ПОСРЕДИ ввода, и человек терял бы набранное.
 reconcileLegacyParking();
 ((projectParking().own)||[]).forEach(item=>{
  if(!item||!item.prefix||!item.by_norm)return;
  // Число поставила норма — помечаем его, иначе при следующей загрузке
  // проекта оно неотличимо от вписанного руками и замрёт навсегда.
  markParkingByNorm(item.prefix);
  [['under_spaces','_parking_under_spaces'],['over_spaces','_parking_over_spaces']].forEach(pair=>{
   const key=item.prefix+pair[1];
   inputs[key]=item[pair[0]];
   const el=document.getElementById('f_'+key);
   if(el&&document.activeElement!==el)el.value=item[pair[0]];
  });
 });
 // Норма у каждого объекта — своим числом под его же полем. Свод остаётся
 // плашкой: «положено 3053, строим 2956» отвечает на вопрос обо всём проекте,
 // а «сколько положено офисам» — на вопрос о поле, и одно другое не заменяет.
 // Обход идёт по СПИСКУ ОБЪЕКТОВ, а не по ответу расчёта. Прежде он шёл по
 // `own`: нет расчёта — список пуст — подпись не зовётся ни разу, и функция,
 // написанная объяснять молчание, молчала сама. Объекты у страницы известны
 // всегда (`OBJECT_PARKING_PREFIXES`), а что сказать про каждый — решает
 // подпись, и решать это должна она одна.
 renderObjectParkingFieldNotes();
 renderUndergroundFieldNote();
 const box=document.getElementById('objectParkingNote');
 if(!box)return;
 const note=projectParking().note;
 // Обеспеченность — весь гараж проекта на всю нормативную потребность. Число
 // и подпись делит движок (`parking_provision`, #656); страница не делит сама.
 const provision=parkingProvisionText();
 if(!note&&!provision){box.innerHTML='';return;}
 // Тон у плашки на странице ровно один — `warning`. Придуманные `ok` и `bad`
 // отрисовались бы обычной плашкой: выглядит стилизованным, а стиля нет.
 // Число прежнего поля площади места гаража из сохранённого проекта движок
 // держит и называет в плашке; снять его можно только здесь — своего поля
 // у него больше нет.
 const saved=projectParking().area_per_space_saved;
 const drop=saved?('<button type="button" id="objectParkingAreaSavedDrop" class="btn" '
  +'style="margin-top:6px;font-size:12px">'
  +(saved.origin==='manual'?'Взять норматив класса':'Понятно, убрать старое число')
  +'</button>'):'';
 box.innerHTML='<div class="note" style="margin:0;padding:9px 11px;font-size:12px">'
  +(provision?'<b id="parkingProvision">Обеспеченность парковкой: '+escapeHtml(provision)+'</b>'
    +(note?'<br>':''):'')
  +escapeHtml(note||'')+(drop?'<br>'+drop:'')+'</div>';
 const button=document.getElementById('objectParkingAreaSavedDrop');
 if(button)button.addEventListener('click',dropSavedObjectParkingArea);
}

function dropSavedObjectParkingArea(){
 delete inputs.object_parking_area_per_space_sqm;
 try{persistLocalSilently()}catch(e){}
 calculate();
}


// Маржа отдельно стоящих объектов — строкой на объект реестра, за своим
// продуктом. Строки шаблона стоят всегда; дописанный объект (ФОК, второй
// офисник) — когда у него есть маржа: иначе строки таблицы не складывались
// бы в итог, как было у ФОКа.
const TAX_MARGIN_LABELS={offices:'Маржа МФОЦ / офисов',standalone_retail:'Маржа ТЦ / ОСЗ',
 above_parking:'Маржа наземного паркинга'};
function taxMarginRows(margins,row,onlyNonzero){
 // Порядок таблиц отчёта — офисы первыми (`standalone_objects_report_order`).
 return STANDALONE_OBJECTS.slice().sort((a,b)=>(a.product!=='offices')-(b.product!=='offices'))
  .filter(o=>(!onlyNonzero&&TAX_MARGIN_LABELS[o.key])||Math.abs(Number(margins[o.key]||0))>0.5)
  .map(o=>row(TAX_MARGIN_LABELS[o.key]||('Маржа: '+o.group_label),money(margins[o.key]||0)))
  .join('');
}

"""
