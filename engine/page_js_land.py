"""Кусок страницы PAGE: Скрипт: ТЭП из источников и участок — генплан, ГлавАПУ-сценарий,
кадастр, скрининг ограничений, карта участка.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_land")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""function waitForGenplan(test,timeout=60000){
 return new Promise((resolve,reject)=>{
   const started=Date.now();
   const tick=()=>{
     try{const result=test();if(result){resolve(result);return}}catch(e){}
     if(Date.now()-started>=timeout){reject(new Error('Калькулятор ГлавАПУ не ответил вовремя'));return}
     setTimeout(tick,180);
   };
   tick();
 });
}

function genplanButton(doc,label){
 return Array.from(doc.querySelectorAll('button')).find(button=>String(button.textContent||'').trim()===label)||null;
}

function setGenplanInput(frame,input,value){
 const win=frame.contentWindow;
 const setter=Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype,'value').set;
 setter.call(input,value);
 if(input._valueTracker)input._valueTracker.setValue('');
 input.dispatchEvent(new win.Event('input',{bubbles:true}));
 input.dispatchEvent(new win.Event('change',{bubbles:true}));
}

function readGenplanRows(doc){
 const table=doc.querySelector('table[aria-label="calc table"]');
 if(!table)return [];
 return Array.from(table.querySelectorAll('tbody tr')).map(row=>{
   const cells=Array.from(row.children).map(cell=>String(cell.textContent||'').replace(/\s+/g,' ').trim());
   if(cells.length<4)return null;
   const rawCode=cells[0];
   const code=/^\d+(?:[.,]\d+)*$/.test(rawCode)?rawCode.replace(/,/g,'.'):'';
   return {code,name:cells[1],unit:cells[2],value:cells[3]};
 }).filter(row=>row&&row.name&&row.value);
}

// Один вход на всю страну. Кадастровый номер 50:* может быть Новой Москвой,
// поэтому префикс ничего не решает: сначала спрашиваем ГлавАПУ, и только если
// территория не московская — считаем по нормативам Московской области.
async function obtainTep(){
 const field=document.getElementById('cadastralNumbers');
 const status=document.getElementById('cadastralStatus');
 const raw=(field&&field.value||'').trim();
 if(!raw){status.innerHTML='<span class="import-error">Введите кадастровый номер или адрес.</span>';return}
 dropStaleLandPreview();
 const entered=raw.split(/[\n,;]+/).map(x=>x.trim()).filter(Boolean);
 // Одна испорченная строка не отменяет разбор остальных. Прежде здесь стояло
 // `every`: ввели два номера, в первом опечатка — и ОБА уезжали в геокодер как
 // адрес, а ответ приходил «участок не найден, введите кадастровый номер»
 // (экран владельца, 26.08.2026). Человек их ввёл; неверна была одна строка,
 // и сказать об этом обязаны мы, а не он должен догадаться.
 const numbers=entered.filter(x=>CADASTRAL_NUMBER_RE.test(x));
 const looksCadastral=numbers.length>0;
 // Правило «несколько номеров через запятую» действует только там, где хоть
 // один номер УЗНАН: тогда остальные строки — действительно пропущенные записи
 // списка, ради чего оно и писалось (опечатка в одном из двух номеров,
 // 26.08.2026). На чистом адресе запятые принадлежат самому адресу, и деление
 // по ним резало «г Москва, ул Мишина, 46» на три «непохожих на кадастровый
 // номер» куска — при том что поле само предлагает вводить адрес, и адрес
 // целиком уходил в поиск. Совет исправить то, что исправлять не нужно, уводит
 // человека искать ошибку там, где её нет (экран владельца, 06.09.2026).
 const rejected=looksCadastral?entered.filter(x=>!CADASTRAL_NUMBER_RE.test(x)):[];
 // Молча отброшенная строка читается как отсутствующая. Называем её и
 // говорим, чем именно она не похожа на кадастровый номер.
 // Текст пришёл от человека и уходит в innerHTML — экранируем. Своего `esc`
 // на этой странице нет, а заводить его ради одной строки значит завести
 // второй такой же в соседнем файле.
 const safe=x=>String(x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 const rejectedNote=rejected.length
  ? ' Пропущено, не похоже на кадастровый номер: '+rejected.map(x=>'«'+safe(x)+'»').join(', ')
    +' (нужен вид 77:01:0004621:72 — в третьем блоке 6–8 цифр).'
  : '';
 const regionOnly=looksCadastral&&numbers.every(x=>x.startsWith('50:'));

 if(!looksCadastral){
  // Адрес или координаты: территорию ГлавАПУ по ним не собрать, идём через ЕГРН.
  status.textContent='Ищу участок по адресу…';
  const found=await lookupLand({quiet:true});
  // Поиск сорвался — причина уже написана в строке состояния, и закрашивать
  // её «участок не найден» нельзя: человек пойдёт искать ошибку в кадастре,
  // которой там нет. Так выключенный VPN выглядел как отсутствующий участок.
  if(found===null)return;
  const resolved=found.map(x=>x.cadastral_number).filter(Boolean);
  if(!resolved.length){
   // «Не найден» и «введите номер» — разные вещи, и путать их нельзя: номер
   // человек уже ввёл, просто по нему ничего не нашлось.
   // Причину называет сам поиск: адрес не распознан геокодером, в точке нет
   // участка, найдены здания без участка — это разные ответы, и заменять их
   // общим «не найден» значит закрашивать диагноз своим предположением.
   // Постоянные приписки про источник данных сюда не идут: они стоят под
   // любым ответом и о неудаче не говорят ничего.
   const reason=String((landLookup||{}).reason||'').trim();
   status.innerHTML='<span class="import-error">По этому запросу участок не найден.'
    +(rejected.length?rejectedNote:'')
    +(reason?' '+safe(reason):'')
    +(rejected.length?'':' Проверьте адрес или введите кадастровый номер.')+'</span>';return;
  }
  field.value=resolved.join(', ');
  return obtainTep();
 }

 // Номер другого кадастрового округа (66:, 78:…) — не Москва и не область:
 // калькулятор ГлавАПУ его не знает, а нормы области к нему не относятся.
 // Такой участок идёт в режим «Другой регион» (решение владельца 19.10.2026),
 // а не в московский калькулятор, чей отказ человеку ничего не объяснял.
 const outside=numbers.filter(outsideMoscowRegion);
 if(outside.length&&outside.length<numbers.length){
  status.innerHTML='<span class="import-error">В списке есть участки Москвы или Московской области и участки другого региона. '
   +'Посчитайте их по отдельности: для другого региона норм у нас нет, и считается он иначе.</span>'+rejectedNote;
  return;
 }
 if(outside.length)return obtainOtherRegionTep(rejectedNote);

 status.textContent='Определяю, где находится участок…'+rejectedNote;
 let analysis=null,failure='';
 try{
  const response=await fetch('/cadastral/analyze',{
   method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_numbers:raw})
  });
  const data=await response.json();
  if(response.ok&&(data.recognized||[]).length)analysis=data;else failure=serverDetail(data)||'территория не сформирована';
 }catch(e){failure=String(e.message||e)+CONNECTION_HINT}

 const insideMoscow=!!((analysis||{}).territory||{}).inside_moscow;
 if(insideMoscow)return obtainCadastralTep(analysis);
 if(regionOnly)return calculateMo(raw);
 if(analysis)return obtainCadastralTep(analysis);
 // Тупик без выхода читается как «сервис сломан»: сведения ЕГРН по этим же
 // номерам доступны всегда, и путь дальше через них есть.
 status.innerHTML='<span class="import-error">Не получилось определить, где находится участок. '+escapeHtml(failure)+
  '</span> <span style="font-size:11px;color:#777">Данные об участке можно посмотреть кнопкой «Только данные об участке», '+
  'а готовый ТЭП — загрузить своим файлом.</span>';
}

// Режим «Другой регион» — участок не в Москве и не в Московской области
// (решение владельца 19.10.2026). Площадь, разрешённое использование и
// кадастровая стоимость — из госреестра; ТЭП — по плотности, которую задаёт
// человек (стартовые 30 000 м² квартир на гектар — наше допущение); места
// соцобъектов, машино-места и плату за смену ВРИ человек вписывает сам —
// московские правила к такому участку не применяются, а норм его региона у
// нас нет. Прежде чем подставить числа, показываем их, как и в других путях.
let otherRegionPending=null;
const OTHER_REGION_DENSITY=30000;
function otherRegionName(found){
 const names=[...new Set((found||[]).map(x=>String(x.region||'').trim()).filter(Boolean))];
 return names.join(', ')||'другой регион';
}
function otherRegionNormsText(){
 return 'Норм этого региона у нас нет. ТЭП считается по плотности, которую задаёте вы: для начала мы берём '+
  num(OTHER_REGION_DENSITY)+' м² квартир на гектар — это наше допущение, поправьте его под свой участок на вкладке «ТЭП». '+
  'Плату за смену разрешённого использования ставим нулём, а места в детских садах, школах и поликлинике и машино-места — '+
  'нашими умолчаниями. Поправьте их во «Вводных» под свой участок: московские правила к нему не применяются.';
}
async function obtainOtherRegionTep(rejectedNote){
 const status=document.getElementById('cadastralStatus');
 otherRegionPending=null;
 dropGlavapuPreview();dropMoPreview();
 const found=await lookupLand({quiet:true});
 // Сорванный запрос — причина уже в строке состояния.
 if(found===null)return null;
 const parcels=(found||[]).filter(x=>x&&x.kind==='land'&&Number(x.area_ha||0)>0);
 if(!parcels.length){
  status.innerHTML='<span class="import-error">Участок не в Москве и не в Московской области, а в госреестре '+
   'по этому номеру не нашлось земельного участка с площадью. Проверьте номер.</span>'+(rejectedNote||'');
  return null;
 }
 const area=Math.round(parcels.reduce((s,x)=>s+Number(x.area_ha||0),0)*10000)/10000;
 const value=parcels.reduce((s,x)=>s+Number(x.cadastral_value_mln||0),0);
 const uses=[...new Set(parcels.map(x=>String(x.permitted_use||'').trim()).filter(Boolean))];
 otherRegionPending={region:otherRegionName(parcels),
  numbers:parcels.map(x=>x.cadastral_number),area_ha:area,
  cadastral_value_mln:Math.round(value*1000)/1000,permitted_use:uses.join('; ')};
 status.innerHTML='<span class="import-ok">Участок найден: '+escapeHtml(otherRegionPending.region)+', '+
  landNum(area,4)+' га'+(uses.length?', разрешённое использование — '+escapeHtml(uses.join('; ')):'')+
  (value>0?', кадастровая стоимость '+landNum(value,1)+' млн ₽':'')+'.</span> '+
  '<div class="note warning other-region-note" style="margin:6px 0">'+escapeHtml(otherRegionNormsText())+'</div>'+
  '<button class="btn dark" onclick="applyOtherRegion()">Подставить в проект</button>'+(rejectedNote||'');
 return otherRegionPending;
}
async function applyOtherRegion(){
 const status=document.getElementById('cadastralStatus');
 const pending=otherRegionPending;
 if(!pending)return;
 // Новый участок — территория прежнего проекта обнуляется, но дальше просто:
 // что знаем — из госреестра, плата за ВРИ — ноль, остальное — наши
 // умолчания, которые человек правит сам (решение владельца 19.10.2026).
 // Обнулённым называется только то, что нулём и осталось.
 resetTerritoryData();
 const ownDefaults=TERRITORY_INPUT_KEYS.filter(key=>key in INPUT_DEFAULT&&
  !['land_rights_cost_mln','purchase_price_mln','site_area_ha','site_density_sqm_per_ha'].includes(key));
 ownDefaults.forEach(key=>{inputs[key]=cloneValue(INPUT_DEFAULT[key])});
 STANDALONE_OBJECTS.forEach(o=>{const k=o.prefix+'_enabled';if(k in INPUT_DEFAULT)inputs[k]=cloneValue(INPUT_DEFAULT[k])});
 territoryCleared=territoryCleared.filter(key=>!ownDefaults.includes(key));
 inputs.vri_region='other';
 fieldOrigins()['inputs.vri_region']={source:'document',
  text:'по кадастровому номеру: участок не в Москве и не в Московской области ('+pending.region+')'};
 inputs._other_region=cloneValue(pending);
 inputs.site_area_ha=pending.area_ha;
 inputs.site_density_sqm_per_ha=0;
 inputs._site_density_user_set=false;
 inputs.land_rights_cost_mln=0;
 otherRegionPending=null;
 status.textContent='Считаю ТЭП по плотности…';
 try{
  await applyNormativeTep();
 }catch(e){
  status.innerHTML='<span class="import-error">'+escapeHtml(stepFailure('ТЭП по плотности',e))+'</span>';
  return;
 }
 status.innerHTML='<span class="import-ok">Участок подставлен в проект: '+landNum(pending.area_ha,4)+' га, квартиры '+
  num(tep.apartments.saleable)+' м² продаваемой площади.</span> '+escapeHtml(otherRegionNormsText())+territoryClearedNote();
}

// Токен запуска: каждый клик «Получить ТЭП» получает свой номер, и ответ
// устаревшего запуска не имеет права трогать интерфейс и данные. Повторный
// клик при живом запросе игнорируется целиком.
let tepRunSequence=0;
function tepRunLog(runId,stage,detail){
 try{
  const client=isTelegramWebApp()?'telegram':'site';
  console.log('[tep#'+runId+' '+client+'] '+stage+(detail?' · '+detail:''));
 }catch(e){}
}

function tepSourceLabel(manual){
 // Штатный калькулятор и серверные формулы помечались одинаково — «ГлавАПУ»,
 // и два отчёта с разными числами выглядели одинаково достоверно. Различие
 // видно только по имени файла выгрузки, чего человек знать не обязан.
 // Площадка КРТ приходит с карточки торгов тем же маркером, что ручной
 // шаблон, но источник у неё свой и назван: «Ручной шаблон» в шапке PDF
 // выдавал бы каталог города за то, что человек вписал сам.
 if(manual){const src=((inputs._manual_tep_import||{}).source||{});return String(src.label||'Ручной шаблон DevelopAid')}
 const fmt=String(((glavapuImport||{}).source||{}).format||'');
 return /серверн/i.test(fmt)?'ГлавАПУ: расчёт по его формулам на сервере DevelopAid'
                            :'ГлавАПУ: калькулятор на сайте';
}
// Сверка «наше / ГлавАПУ». Сервер ставит задание браузеру и отвечает сразу;
// страница спрашивает тот же маршрут, пока задание не кончится. Таблицу
// собирает glavapuScenarioHtml — одна функция и для окна, и для теста.
const GLAVAPU_SCENARIO_STATUS={match:['совпало','#2e7d32'],diff:['расходится','#b3261e'],
 covered:['покрывает','#2e7d32'],short:['не хватает','#b3261e'],
 reference:['справочно','#666'],
 not_applied:['параметр не принят','#8a4b08'],ours_missing:['нет нашей величины','#666'],
 glavapu_missing:['нет у ГлавАПУ','#666']};
let glavapuScenarioRun=0;
function glavapuScenarioNum(v){
 if(v===null||v===undefined||v==='')return '—';
 const x=Number(v);if(!isFinite(x))return escapeHtml(String(v));
 // Ноль в пределах округления — ноль, а не «-0».
 if(Math.abs(x)<0.0005)return '0';
 return x.toLocaleString('ru-RU',{maximumFractionDigits:Math.abs(x)<1000?3:0});
}
function glavapuScenarioHtml(a){
 a=a||{};
 const parts=[];
 const sc=a.scenario||{},p=sc.params||{};
 if(a.state==='done'||a.comparison){
  const c=a.comparison||{rows:[],counts:{}};
  const counts=c.counts||{};
  parts.push('<div class="note" style="margin:6px 0">Калькулятор ГлавАПУ здесь только проверяет: его числа стоят рядом '+
   'с нашими и ничего в проекте не заменяют. Совпало: '+(counts.match||0)+
   ', расходится: '+(counts.diff||0)+(counts.not_applied?', не принят параметр: '+counts.not_applied:'')+
   (counts.short?', не хватает: '+counts.short:'')+'.</div>');
  // Странности самой выгрузки — над таблицей: это не расхождение с нами,
  // а то, что читатель книги калькулятора поймёт неверно.
  const odd=c.anomalies||[];
  if(odd.length){
   parts.push('<div class="note warning glavapu-scenario-anomalies"><b>Странности выгрузки калькулятора:</b><br>'+
    odd.map(x=>escapeHtml(x.text)+' <span style="color:#777">('+escapeHtml(x.where||'')+')</span>').join('<br>')+'</div>');
  }
  const notes=c.notes||{};
  const typical=((a.glavapu||{}).social_typical)||[];
  let group='';
  const rows=(c.rows||[]).map(r=>{
   const st=GLAVAPU_SCENARIO_STATUS[r.status]||[r.status,'#333'];
   let head='';
   if(r.group!==group){
    head='<tr class="glavapu-scenario-group"><td colspan="5" style="font-weight:600;background:#fafaf8">'+escapeHtml(r.group)+
     (notes[r.group]?'<div style="font-weight:400;font-size:11px;color:#555">'+escapeHtml(notes[r.group])+'</div>':'')+
     (r.group==='Соцобъекты, которые поставил калькулятор'&&typical.length?
      '<div style="font-weight:400;font-size:11px;color:#555">Типовые здания калькулятора. '+typical.map(t=>
       escapeHtml(t.name)+': участок '+glavapuScenarioNum(t.site_ha)+' га, полезная площадь '+glavapuScenarioNum(t.np_ths)+
       ' тыс. м², поэтажная площадь '+glavapuScenarioNum(t.spp_ths)+' тыс. м², '+glavapuScenarioNum(t.places)+' мест.').join(' ')+'</div>':'')+
     '</td></tr>';
   }
   group=r.group;
   return head+'<tr data-kind="'+escapeHtml(r.kind)+'" data-status="'+escapeHtml(r.status)+'">'+
    '<td>'+escapeHtml(r.label)+'</td>'+
    '<td style="text-align:right">'+glavapuScenarioNum(r.ours)+'<div style="font-size:10px;color:#888">'+escapeHtml(r.ours_origin||'')+'</div></td>'+
    '<td style="text-align:right">'+glavapuScenarioNum(r.glavapu)+'<div style="font-size:10px;color:#888">'+escapeHtml(r.glavapu_origin||'')+'</div></td>'+
    '<td style="text-align:right">'+glavapuScenarioNum(r.delta)+'</td>'+
    '<td style="color:'+st[1]+'"><b>'+escapeHtml(st[0])+'</b>'+(r.reason?'<div style="font-size:11px">'+escapeHtml(r.reason)+'</div>':'')+'</td></tr>';
  }).join('');
  parts.push('<div class="scroll" style="max-height:none"><table class="glavapu-scenario-table"><thead><tr><th>Показатель</th><th>Наше</th><th>ГлавАПУ</th><th>Разница</th><th>Итог и причина</th></tr></thead><tbody>'+rows+'</tbody></table></div>');
 }
 const refused=((a.applied||{}).refused)||[];
 if(refused.length){
  parts.push('<div class="note warning"><b>Калькулятор не принял:</b><br>'+refused.map(r=>
   escapeHtml(r.param)+' — '+escapeHtml(r.reason)+' <span style="color:#777">('+escapeHtml(r.place)+')</span>').join('<br>')+'</div>');
 }
 const notSent=sc.not_sent||[];
 if(notSent.length){
  parts.push('<div class="note warning"><b>Не передано в калькулятор:</b><br>'+notSent.map(r=>escapeHtml(r.reason)).join('<br>')+'</div>');
 }
 if(p&&p.area_ha!==undefined){
  const nonres=(p.nonres||[]).map(x=>escapeHtml(x.menu)+' '+glavapuScenarioNum(x.spp_ths)).join(', ')||'нет';
  const social=(p.social||[]).map(x=>escapeHtml(x.label)+' '+x.places+' мест').join(', ')||'нет';
  const ratio=(((a.applied||{}).applied)||[]).find(x=>x.param==='ratio');
  // Квартиры: штуки уходят (галочка калькулятора «через количество квартир»),
  // площадь квартир — нет: в режиме «СПП в ГНС» он считает её сам.
  const origin=sc.origin||{};
  const flats=Number(p.flats_count||0)>0?' Квартир — '+glavapuScenarioNum(p.flats_count)+' шт. (галочка «через количество квартир»).'
   :' Число квартир не передано: в ТЭП его нет, и калькулятор считает квартиры сам.';
  parts.push('<details style="margin-top:6px"><summary style="font-size:12px">Что передано калькулятору</summary><div class="note">'+
   'Площадь участка — '+glavapuScenarioNum(p.area_ha)+' га. Поэтажная площадь жилых зданий — '+glavapuScenarioNum(p.spp_residential_ths)+
   ' тыс. м², из них нежилая часть — '+glavapuScenarioNum(p.vpp_pct)+'%. Нежилые объекты по виду использования: '+nonres+
   '. Соцобъекты: '+social+'.'+flats+(p.land_right?' Право на землю — '+escapeHtml(p.land_right)+'.':'')+
   (ratio?' Ползунок калькулятора «Соотношение жилых / нежилых зданий» встал на: '+escapeHtml(ratio.got)+'.':'')+
   (origin.flats_area?'<div style="margin-top:4px">Не передаётся: '+escapeHtml(origin.flats_area)+'.</div>':'')+'</div></details>');
 }
 return parts.join('');
}
function glavapuScenarioStatusText(a){
 a=a||{};
 if(a.state==='queued')return 'Задание поставлено, калькулятор ГлавАПУ начнёт расчёт…';
 if(a.state==='running')return 'Калькулятор ГлавАПУ считает наш сценарий…';
 if(a.state==='done')return 'Сверка готова'+(a.seconds?' ('+a.seconds+' с)':'')+'.';
 const where=a.where?' Место: '+a.where+'.':'';
 const hint=a.hint?' '+a.hint:'';
 return 'Сверка не выполнена: '+(a.error||a.state||'нет ответа')+'.'+where+hint;
}
async function glavapuScenarioCheck(force){
 const run=++glavapuScenarioRun;
 const status=document.getElementById('glavapuScenarioStatus');
 const box=document.getElementById('glavapuScenarioResult');
 status.style.display='block';
 status.textContent='Ставлю задание калькулятору ГлавАПУ…';
 const summaryBox=document.getElementById('glavapuScenarioSummary');
 summaryBox.innerHTML='';summaryBox.style.display='none';
 const body={inputs,tep,force:!!force};
 let answer=null;
 try{
  for(let i=0;i<120;i++){
   const response=await fetch('/glavapu/scenario',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(i?Object.assign({},body,{poll:true,force:false}):body)});
   answer=await response.json();
   if(!response.ok)throw new Error(serverDetail(answer)||('HTTP '+response.status));
   if(run!==glavapuScenarioRun)return;
   status.textContent=glavapuScenarioStatusText(answer);
   if(answer.state!=='queued'&&answer.state!=='running')break;
   await new Promise(r=>setTimeout(r,4000));
  }
 }catch(error){
  status.textContent='Сверка не выполнена: '+error.message+'. Место: запрос страницы к /glavapu/scenario.';
  return;
 }
 box.innerHTML=glavapuScenarioHtml(answer);
 glavapuScenarioKeepTerritory(answer);
 const summary=document.getElementById('glavapuScenarioSummary');
 summary.innerHTML=glavapuScenarioSummaryHtml(answer);
 summary.style.display=summary.innerHTML?'':'none';
}
// Строки 57–58 калькулятора («Озеленённые территории ЖК» и разбивка) —
// в проект: двор по норме пятна застройки берёт большее из нашей нормы и
// строки 57 (решение владельца 22.10.2026). Строка 57 — 5 м² × квартиры × 2,1,
// поэтому с ней хранится число квартир, принятое калькулятором: движок берёт
// её, только пока в ТЭП столько же квартир. Поле не принято — не храним.
// Участки соцобъектов (разделы «ДОО:», «Школы:») и баланс территории
// (строка 14) хранятся рядом: пятно ставит школу, сад и офисы на их участки,
// пока калькулятор считал те же места и ту же нежилую площадь.
function glavapuScenarioKeepTerritory(a){
 a=a||{};
 if(a.state!=='done')return;
 const side=a.glavapu||{};
 const params=((a.scenario||{}).params)||{};
 const refused=((a.applied||{}).refused||[]).map(r=>r&&r.param);
 const flats=refused.includes('flats_count')?0:Number(params.flats_count||0);
 const keep={key:a.key||'',done_at:a.finished_at||a.done_at||new Date().toISOString(),
  flats_count:flats,territory:cloneValue(side.territory||{}),social_obj:cloneValue(side.social_obj||{}),
  balance:cloneValue(side.balance||{}),
  spp_nonres_ths:refused.some(p=>String(p||'').startsWith('nonres'))?0:Number(params.spp_nonres_ths||0)};
 if(!Object.keys(keep.territory).length&&!Object.keys(keep.social_obj).length&&!Object.keys(keep.balance).length){
  if(inputs._glavapu_scenario){delete inputs._glavapu_scenario;calculate()}
  return;
 }
 inputs._glavapu_scenario=keep;
 calculate();
}
// Короткий итог для карточки: сколько совпало и разошлось, и кнопка окна.
// Отказ сюда не пишется — его причина и место уже в строке статуса.
function glavapuScenarioSummaryHtml(a){
 a=a||{};
 if(a.state!=='done'||!a.comparison)return '';
 const c=a.comparison.counts||{};
 const parts=['совпало: '+(c.match||0),'расходится: '+(c.diff||0)];
 if(c.not_applied)parts.push('параметр не принят: '+c.not_applied);
 if(c.ours_missing)parts.push('нет нашей величины: '+c.ours_missing);
 if(c.glavapu_missing)parts.push('нет у ГлавАПУ: '+c.glavapu_missing);
 if(c.short)parts.push('не хватает: '+c.short);
 const refused=((a.applied||{}).refused||[]).length;
 const notSent=((a.scenario||{}).not_sent||[]).length;
 const odd=(a.comparison.anomalies||[]).length;
 const warn=(refused?' Калькулятор не принял полей: '+refused+'.':'')+(notSent?' Не передано: '+notSent+'.':'')+
  (odd?' Найдено странностей калькулятора: '+odd+'.':'');
 return '<div class="toolbar" style="margin-top:8px"><span style="font-size:13px">'+escapeHtml(parts.join(', '))+'.'+
  (warn?'<span style="color:#8a4b08">'+escapeHtml(warn)+'</span>':'')+
  '</span><button class="btn dark" onclick="openGlavapuScenario()">Открыть сверку</button></div>';
}
function openGlavapuScenario(){document.getElementById('glavapuScenarioDialog').style.display='flex'}
function closeGlavapuScenario(){document.getElementById('glavapuScenarioDialog').style.display='none'}
async function obtainServerTep(analysis,status,runId){
 // Формулы калькулятора, посчитанные сервером: равноценная замена
 // браузерной автоматизации, а не суррогат — сходятся до единицы.
 status.textContent='Считаю ТЭП на сервере…';
 tepRunLog(runId,'серверный расчёт: запрос');
 const response=await fetch('/cadastral/tep-server',{
  method:'POST',headers:{'Content-Type':'application/json'},
  // Территория уже собрана — отдаём её серверу, чтобы он не спрашивал ГлавАПУ
  // второй раз за один клик: этот запрос стоит секунд, а расчёт и так не быстр.
  body:JSON.stringify({cadastral_numbers:(analysis.recognized||analysis.requested||[]).join(', '),
   request_id:'tep-'+runId,cadastral_analysis:analysis})
 });
 const payload=await response.json();
 if(!response.ok)throw new Error(serverDetail(payload)||'Серверный расчёт ТЭП не получился');
 if(runId!==tepRunSequence){tepRunLog(runId,'ответ устаревшего запуска отброшен');return null}
 glavapuImport=payload;
 inputs._cadastral_analysis=cloneValue(analysis);
 renderGlavapuPreview(payload);
 drawLandPreviewQuiet();
 const areaText=Number((analysis.territory||{}).area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4});
 // Кто посчитал — штатный калькулятор или наши формулы, и если формулы, то
 // почему. Браузер живёт на ядре, и с телефона его состояние иначе не увидеть.
 const hl=((payload.source||{}).headless)||{};
 const byCalculator=/Штатный калькулятор/i.test(String((payload.source||{}).format||''));
 const why=byCalculator?'':' <span style="color:#8a4b08">Калькулятор ГлавАПУ не ответил, поэтому посчитали по его формулам у себя ('+
   escapeHtml(hl.state||'нет данных')+', '+escapeHtml(hl.where||'—')+').'+
   (hl.hint?' '+escapeHtml(hl.hint):'')+'</span>';
 status.innerHTML='<span class="import-ok">ТЭП посчитан '+(byCalculator?'калькулятором ГлавАПУ':'по формулам ГлавАПУ')+' для участка '+areaText+
  ' га.</span>'+why+' Проверьте числа ниже и нажмите «Подставить в проект».';
 glavapuStatus.innerHTML='<span class="import-ok">ТЭП посчитан '+(byCalculator?'калькулятором ГлавАПУ':'по формулам ГлавАПУ')+'.</span>'+why+' Проверьте числа, прежде чем подставлять их в проект.';
 tepRunLog(runId,'серверный расчёт: получен', areaText+' га');
 return payload;
}

async function obtainCadastralTep(preAnalysis){
 const field=document.getElementById('cadastralNumbers');
 const button=document.getElementById('cadastralAnalyzeButton');
 const status=document.getElementById('cadastralStatus');
 const frame=document.getElementById('genplanAutomationFrame');
 const raw=(field&&field.value||'').trim();
 if(!raw){status.innerHTML='<span class="import-error">Введите хотя бы один кадастровый номер.</span>';return null}
 if(button.disabled)return null; // запрос уже идёт — второй клик игнорируется
 const runId=++tepRunSequence;
 tepRunLog(runId,'старт','кадастры: '+raw.slice(0,80));
 button.disabled=true;button.textContent='Получаю ТЭП…';
 document.getElementById('cadastralPreview').style.display='none';
 document.getElementById('glavapuPreview').style.display='none';
 dropMoPreview();
 // Шаг записывается перед каждым куском: браузер сообщает о своих отказах
 // своими словами, и без шага «The string did not match the expected pattern»
 // не говорит ни что сломалось, ни где.
 let tepStep='сведения по кадастровым номерам';
 try{
   status.textContent='1 из 4 · Определяю границы участка по кадастровым номерам…';
   let analysis=preAnalysis;
   if(!analysis){
     const analysisResponse=await fetch('/cadastral/analyze',{
       method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_numbers:raw})
     });
     analysis=await analysisResponse.json();
     if(!analysisResponse.ok)throw new Error(serverDetail(analysis)||'Не удалось определить территорию');
   }
   if(!(analysis.recognized||[]).length)throw new Error('Калькулятор не распознал кадастровые номера');
   cadastralAnalysis=analysis;
   inputs._cadastral_analysis=cloneValue(analysis);
   // Площадь из ЕГРН — пока нет ГлавАПУ и ручного ввода, участок мерится ей.
   // Территорию, приехавшую с источником (площадка КРТ, загруженный ТЭП),
   // разобранные номера не перемеряют: они могут быть её частью. Так один
   // участок 66 м² из перечня встал площадью КРТ на 5 га, а ТЭП на
   // десятки тысяч метров остался — и расчёт пошёл по нему молча.
   {
    const cadArea=Number(((analysis||{}).territory||{}).area_ha||0);
    if(cadArea>0&&!inputs._site_area_user_set&&!inputs._glavapu_import&&!importedSiteAreaHa())inputs.site_area_ha=cadArea;
   }
   tepStep='карточка территории';
   field.value=(analysis.requested||[]).join(', ');
   renderCadastralPreview(analysis);

   // Telegram WebView не тянет автоматизацию скрытого iframe: сайт собирал
   // ТЭП, мини-приложение падало по таймауту. Здесь сразу серверный расчёт.
   if(isTelegramWebApp()){
     return await obtainServerTep(analysis,status,runId);
   }

   tepStep='расчёт в калькуляторе ГлавАПУ';
   status.textContent='2 из 4 · Открываю калькулятор ГлавАПУ…';
   const area=Number((analysis.territory||{}).area_ha||0).toFixed(4);
   frame.src='/calc/?terrArea='+encodeURIComponent(area)+'&restrictArea=0&plato='+Date.now();
   const parcelButton=await waitForGenplan(()=>{
     const doc=frame.contentDocument;
     return doc&&genplanButton(doc,'Участок');
   });
   parcelButton.click();
   const cadInput=await waitForGenplan(()=>frame.contentDocument&&frame.contentDocument.querySelector('#id-cad-numbers-text-field'));
   setGenplanInput(frame,cadInput,(analysis.recognized||analysis.requested||[]).join(', '));
   const sendButton=await waitForGenplan(()=>{
     const candidate=frame.contentDocument&&genplanButton(frame.contentDocument,'Отправить');
     return candidate&&!candidate.disabled?candidate:null;
   });
   sendButton.click();
   const proceedButton=await waitForGenplan(()=>{
     const candidate=frame.contentDocument&&genplanButton(frame.contentDocument,'Перейти к расчётам');
     return candidate&&!candidate.disabled?candidate:null;
   });
   proceedButton.click();

   tepStep='чтение таблицы ГлавАПУ';
   status.textContent='3 из 4 · Забираю из калькулятора готовую таблицу ТЭП…';
   const rows=await waitForGenplan(()=>{
     const extracted=readGenplanRows(frame.contentDocument);
     const codes=new Set(extracted.map(row=>row.code));
     return codes.has('60')&&codes.has('54')&&extracted.length>=60?extracted:null;
   });
   const tepResponse=await fetch('/cadastral/tep-from-calculator',{
     method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows,cadastral_analysis:analysis})
   });
   const payload=await tepResponse.json();
   if(!tepResponse.ok)throw new Error(serverDetail(payload)||'Не удалось перенести ТЭП в DevelopAid');
   if(runId!==tepRunSequence){tepRunLog(runId,'ответ устаревшего запуска отброшен');return null}

   tepStep='перенос ТЭП в модель';
   status.textContent='4 из 4 · Готовлю числа для проверки…';
   glavapuImport=payload;
   inputs._cadastral_analysis=cloneValue(analysis);
   renderGlavapuPreview(payload);
   drawLandPreviewQuiet();
   const areaText=Number((analysis.territory||{}).area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4});
   status.innerHTML='<span class="import-ok">ТЭП посчитан калькулятором ГлавАПУ для участка '+areaText+' га.</span> Проверьте числа ниже и нажмите «Подставить в проект».';
   glavapuStatus.innerHTML='<span class="import-ok">ГлавАПУ посчитал ТЭП по кадастровым номерам.</span> Проверьте числа, прежде чем подставлять их в проект.';
   tepRunLog(runId,'штатный калькулятор: получено', areaText+' га');
   return payload;
 }catch(e){
   tepRunLog(runId,'ошибка',String(e.message||e).slice(0,120));
   if(runId!==tepRunSequence)return null;
   // Автоматизация штатного калькулятора не отработала — таймаут, сеть или
   // изменившаяся вёрстка genplan. Территория уже известна: докатываемся
   // серверными формулами вместо голой ошибки.
   if(cadastralAnalysis){
     try{return await obtainServerTep(cadastralAnalysis,status,runId)}catch(e2){}
   }
   status.innerHTML='<span class="import-error">'
     +escapeHtml(stepFailure(tepStep||'расчёт ТЭП', e))+'</span>';
   return null;
 }finally{
   button.disabled=false;button.textContent='Получить ТЭП';
   frame.src='about:blank';
 }
}

// Браузер сообщает о своих отказах своими словами: «The string did not match
// the expected pattern» — это Safari, и по одной этой строке не понять ни что
// сломалось, ни где (боевая проверка владельца, 18.08.2026). К сообщению
// добавляем род ошибки и шаг, на котором она случилась: тот же принцип, что у
// `_error_location` на сервере — ошибка без места это ошибка, которой нет.
function stepFailure(step, error){
 const name=String((error&&error.name)||'').trim();
 const text=String((error&&error.message)||error||'').trim()||'ошибка без описания';
 const known=/^[А-Яа-яЁё]/.test(text);      // наши сообщения уже по-русски
 const detail=[name,known?'':'сообщение браузера'].filter(Boolean).join(', ');
 return text+' — на шаге «'+step+'»'+(detail?' ('+detail+')':'')+'.';
}

function renderCadastralPreview(data){
 if(!data)return;
 const territory=data.territory||{},coeff=data.coefficients||{};
 const district=[territory.administrative_district,territory.district].filter(Boolean).join(', ')||'—';
 const rail=coeff.rail==null?'—':Number(coeff.rail).toLocaleString('ru-RU',{maximumFractionDigits:4});
 cadastralSummary.innerHTML=[
   ['Участков',String(territory.parcel_count||0)],
   ['Площадь',Number(territory.area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4})+' га'],
   ['Район',district],
   ['Кадастровый квартал',territory.cadastral_quarter||'—'],
   ['Коэффициент К1',rail+(coeff.rail_zone?' ('+coeff.rail_zone+')':'')]
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 const parcels=data.parcels||[];
 cadastralParcels.innerHTML=parcels.length?`<table><thead><tr><th>Кадастровый номер</th><th>Площадь, га</th></tr></thead><tbody>${parcels.map(x=>`<tr><td>${escapeHtml(x.cadastral_number)}</td><td>${Number(x.area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4})}</td></tr>`).join('')}</tbody></table>`:'<div style="padding:10px;color:#777">Участки не распознаны.</div>';
 cadastralWarnings.innerHTML=(data.warnings||[]).map(x=>'• '+escapeHtml(x)).join('<br>');
 cadastralPreview.style.display='block';
}

let landLookup=null;
let landScreeningRun=0;
// Ответ скрининга рисуется и больше нигде не живёт, а развёрнутой карте нужны
// очертания зон того же участка. Держим последний ответ целиком: собирать его
// заново значило бы спросить НСПД второй раз и показать поверх карты не то,
// что показано в списке ограничений.
let landScreeningLast=null;
let LAND_MAP=null;
let LAND_MAP_VIEWS=null;

// Карточка участка с контуром и картой — при любом пути получения ТЭП, а не
// только при поиске по адресу: кадастровый «Получить ТЭП» оставлял человека
// без картинки участка (замечание владельца, 16.08.2026). Тихо: статусы и
// кнопки принадлежат основному потоку, карточка — украшение и не имеет права
// ничего ронять; повторный запрос дешёвый — сведения лежат в серверном кэше.
async function drawLandPreviewQuiet(query){
 try{
  const raw=String(query!=null?query:((document.getElementById('cadastralNumbers')||{}).value||'')).trim();
  if(!cadastralNumbersIn(raw).length)return;
  const response=await fetch('/land/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:raw,limit:30,session:activeSession()})});
  // Ограничения не зависят от картинки: карточка — украшение, а скрининг —
  // ответ на вопрос «можно ли тут строить». Раньше он запускался только после
  // удачного контура, и на 22 участках не показывался вовсе (замечание
  // владельца, 19.08.2026).
  loadLandScreening(raw);
  if(!response.ok)return;
  const data=await response.json();
  if(!Number(data.found_count||0))return;
  landLookup=data;
  inputs._land_lookup=cloneValue(data);
  renderLandLookup(data);
 }catch(e){/* контур — украшение, не данные */}
}

// Оценка участка до финмодели: что мешает строить. Самостоятельная ценность —
// человек вводит кадастр и сразу видит ограничения с документом-основанием,
// не запуская расчёт экономики. Один участок — коротко, несколько — свод плюс
// разбивка (решение владельца). Блок тихий: своя ошибка его прячет, но ничего
// не роняет, потому что расчёт от него не зависит.
async function loadLandScreening(query){
 const box=document.getElementById('landScreening');
 if(!box)return;
 const raw=String(query!=null?query:((document.getElementById('cadastralNumbers')||{}).value||'')).trim();
 const numbers=cadastralNumbersIn(raw).slice(0,10);
 if(!numbers.length){box.style.display='none';return}
 const run=++landScreeningRun;
 const started=Date.now();
 const finished=[];
 box.style.display='block';
 const paint=()=>{
  if(run!==landScreeningRun)return;
  const state=screeningWorkingHtml(numbers,finished,Math.round((Date.now()-started)/1000));
  box.className=state.cls;box.innerHTML=state.html;
 };
 paint();
 const ticker=setInterval(paint,500);
 try{
  // Участки опрашиваются поодиночке: так видно ход работы, а не пустой экран.
  // Стоит это столько же — сервер и в одном запросе идёт по номерам подряд,
  // а посчитанное кладётся в кэш, поэтому сводный запрос ниже уже дешёвый.
  // По двое разом: двадцать два участка по очереди — это две минуты, а
  // больше двух одновременно НСПД начинает отвечать отказами (у нас на этот
  // случай предохранитель, но лучше до него не доводить).
  const ask=async number=>{
   let parcel=null;
   try{
    const one=await fetch('/land/screening?cad='+encodeURIComponent(number));
    if(run!==landScreeningRun)return;
    if(one.ok){const data=await one.json();parcel=(data.parcels||[])[0]||null}
   }catch(e){/* участок мог не ответить — ход показываем всё равно */}
   finished.push({number:number,parcel:parcel});
   paint();
  };
  const queue=numbers.slice();
  const worker=async()=>{
   while(queue.length){
    if(run!==landScreeningRun)return;
    await ask(queue.shift());
   }
  };
  await Promise.all([worker(),worker()]);
  if(run!==landScreeningRun)return;
  // Свод считает движок, а не страница: даже когда участок один, вердикт
  // приходит с сервера.
  const response=await fetch('/land/screening?cad='+encodeURIComponent(numbers.join(',')));
  if(run!==landScreeningRun)return;
  if(!response.ok){box.style.display='none';return}
  renderLandScreening(await response.json());
 }catch(e){box.style.display='none'}
 finally{clearInterval(ticker)}
}

// Плашка ожидания. Прежде она была невидимой: класс тона не ставился, а текст
// в шапке белый — на белом фоне ничего не читалось, и ограничения появлялись
// внезапно, без признака работы (замечание владельца, 18.08.2026). Теперь
// видно, что идёт, сколько прошло и что уже проверено.
function screeningWorkingHtml(numbers,finished,seconds){
 const total=numbers.length;
 const done=finished.length;
 const current=Math.min(done+1,total);
 // Оценка остатка по уже пройденному: «41 с» без «осталось» читается как
 // «зависло» (замечание владельца, 19.08.2026). Пока не прошёл ни один
 // участок, оценивать нечем — и мы не выдумываем.
 const left=done&&done<total?Math.round(seconds/done*(total-done)):0;
 const head='Проверяю градостроительные ограничения'+
  (total>1?': участок '+current+' из '+total+', прошло ':'. Прошло ')+seconds+' с'+
  (left?', осталось примерно '+left+' с':'')+'.';
 const steps=finished.map(item=>{
  const parcel=item.parcel;
  let mark='в ЕГРН нет сведений';
  if(parcel&&parcel.too_small){
   mark='не проверялся: участок меньше порога';
  }else if(parcel&&parcel.found){
   const flags=parcel.findings||[];
   const killers=flags.filter(f=>f.flag_class==='killer').length;
   mark=killers?'есть запрет':(flags.length?flags.length+' ограничени'+(flags.length===1?'е':(flags.length<5?'я':'й')):'ограничений не найдено');
  }
  return '<div class="step">'+escapeHtml(item.number)+' — '+mark+'</div>';
 }).join('');
 return {cls:'land-screening working',
  html:'<header>'+escapeHtml(head)+'</header>'+
   '<div class="progress"><i style="width:'+Math.round(100*done/total)+'%"></i></div>'+
   steps+
   '<footer>Спрашиваем НСПД о зонах с особыми условиями использования территории, охраняемых природных '+
   'территориях, лесничествах, красных линиях и территориальных зонах. Это около шестидесяти слоёв карты '+
   'на каждый участок'+
   (total>1?', а участков '+total:'')+
   '. Обычно уходит две-три секунды на участок.</footer>'};
}

// Пятно застройки: контур участка и зоны поверх него, в одной плоскости.
// «Зона накрывает 71%» — число; где именно она лежит, число не говорит, а
// решение принимают по месту: угол или середина, вдоль улицы или поперёк
// (замечание владельца, 18.08.2026). Рисуем сами, тем же меркатором, что и
// миниатюра участка: внешних карт тут нет, работает и в WebView.
function screeningSpotSvg(parcel){
 const rings=(parcel&&parcel.contour_merc)||[];
 if(!Array.isArray(rings)||!rings.length)return '';
 const zones=(parcel.findings||[]).filter(f=>Array.isArray(f.outline_merc)&&f.outline_merc.length);
 if(!zones.length)return '';
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 rings.forEach(ring=>(ring||[]).forEach(p=>{
  if(!Array.isArray(p)||p.length<2)return;
  minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
 }));
 if(!(maxX>minX)||!(maxY>minY))return '';
 const spanX=maxX-minX,spanY=maxY-minY;
 const pad=Math.max(spanX,spanY)*0.12;
 const w=spanX+pad*2,h=spanY+pad*2;
 const toPath=list=>(list||[]).map(ring=>'M'+(ring||[])
   .filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>((p[0]-minX+pad)).toFixed(1)+' '+((maxY-p[1]+pad)).toFixed(1))
   .join(' L ')+' Z').join(' ');
 const paint={killer:'#b3261e',economic:'#a05a00',info:'#777'};
 // Зоны рисуются под контуром: границы участка должны оставаться читаемыми,
 // иначе непонятно, что чем накрыто.
 const layers=zones.map(zone=>{
  const colour=paint[zone.flag_class]||'#777';
  return `<path d="${toPath(zone.outline_merc)}" fill="${colour}" fill-opacity="0.22" `+
   `stroke="${colour}" stroke-width="1.5" stroke-opacity="0.75" vector-effect="non-scaling-stroke"/>`;
 }).join('');
 const legend=zones.map(zone=>{
  const colour=paint[zone.flag_class]||'#777';
  return `<span class="spot-key"><i style="background:${colour}"></i>`+
   `${escapeHtml(zone.name||zone.type_zone||'зона')}`+
   `${zone.coverage_pct!=null?', '+landNum(zone.coverage_pct,0)+'%':''}</span>`;
 }).join('');
 return `<div class="land-spot"><div class="land-spot-stage" `+
  `style="aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)};max-width:${Math.round(260*w/h)}px">`+
  `<svg viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}" preserveAspectRatio="none" role="img" `+
  `aria-label="Участок и накрывающие его зоны">${layers}`+
  `<path d="${toPath(rings)}" fill="none" stroke="#111" stroke-width="2.5" `+
  `fill-rule="evenodd" vector-effect="non-scaling-stroke"/></svg></div>`+
  `<div class="spot-legend">${legend}</div>`+
  `<small>Границы участка взяты из ЕГРН, зоны — из НСПД. Наложение приблизительное: `+
  `мы оцениваем его по сетке, с точностью около процента. `+
  `<a href="#" data-cad="${escapeHtml(parcel.cadastral_number||'')}"`+
  ` onclick="landMapFromContour(this.dataset.cad);return false">Развернуть карту</a></small></div>`;
}

function screeningFlagLabel(cls){
 return cls==='killer'?'СТОП':(cls==='economic'?'ВЛИЯЕТ':'справка');
}

function renderLandScreening(data){
 const box=document.getElementById('landScreening');
 if(!box||!data||!data.parcels)return;
 landScreeningLast=data;
 const v=data.verdict||{};
 const tone=v.status==='CRITICAL'?'critical':(v.status==='WARNING'?'warning':(v.status==='NOT_SCREENED'?'unknown':'clean'));
 const found=data.parcels.filter(p=>p.found);
 // Один участок — короткая карточка; несколько — разбивка. Считаем по
 // запрошенным, а не по найденным: из двадцати двух номеров сведения ЕГРН
 // пришли по десяти, и разбивка молча превращалась в карточку одного участка.
 const single=data.parcels.length<2;
 // Почему участок не проверен, если не проверен. «Чисто» на непроверенном —
 // тот же разрешительный вывод на пустоте, что и зелёный экран без запросов.
 const skipReason=p=>{
  if(p.probe_failed)return 'не проверялся: запрос в НСПД не прошёл';
  if(!p.found)return 'не проверялся: нет сведений ЕГРН';
  if(p.too_small)return 'не проверялся: участок меньше '+landNum((data.min_area_sqm||0)/100,0)+' соток';
  if(p.verdict&&p.verdict.probed===false)return 'не проверялся';
  return '';
 };
 const screened=data.parcels.filter(p=>!skipReason(p)).length;
 const item=f=>`<li><span class="flag ${f.flag_class}">${screeningFlagLabel(f.flag_class)}</span> `+
   `<b>${escapeHtml(f.name||f.type_zone||f.category||'ограничение')}</b>`+
   `${f.zones_count>1?' <span class="meta">('+f.zones_count+' подзоны)</span>':''}`+
   // Доля участка под зоной — то, ради чего скрининг и затевался: «зона есть»
   // одинаково выглядит и при срезанном угле, и при съеденном участке.
   `${f.coverage_pct!=null?' <span class="share">'+landNum(f.coverage_pct,0)+'% участка</span>':''}`+
   `<div class="meta">${escapeHtml(f.impact||'')}`+
   `${f.reg_number?', реестров'+((f.reg_numbers&&f.reg_numbers.length>1)?'ые №№ '+escapeHtml(f.reg_numbers.join(', '))+(f.reg_numbers_more>0?' и ещё '+f.reg_numbers_more:''):'ый № '+escapeHtml(f.reg_number)):''}`+
   `${f.document_number?', '+escapeHtml(f.document||'документ')+' № '+escapeHtml(f.document_number):''}`+
   `${f.document_date?' от '+escapeHtml(f.document_date):''}</div></li>`;
 // Больше шести строк брокер не читает, а на плотном участке их бывает
 // три десятка: показываем главные, остальные — счётчиком (18.08.2026).
 const LIMIT=6;
 const list=flags=>{
  const head=flags.slice(0,LIMIT).map(item).join('');
  const rest=flags.length-LIMIT;
  return `<ul>${head}${rest>0?`<li class="meta">и ещё ${rest} ограничени${rest===1?'е':(rest<5?'я':'й')} — в отчёте перечислены полностью</li>`:''}</ul>`;
 };
 let body='';
 // Пустой список находок и непроверенный участок выглядели одинаково зелёными.
 const spot=single&&found[0]?screeningSpotSvg(found[0]):'';
 // Причина пропуска у трёх случаев разная, а строка была одна — про
 // отсутствующие сведения ЕГРН. Мелкий участок и неответивший НСПД получали
 // чужой диагноз.
 const skipWhy=p=>{
  if(!p)return 'по номеру нет сведений ЕГРН';
  if(p.probe_failed)return 'НСПД не ответил на запрос по этому номеру';
  if(!p.found)return 'по номеру нет сведений ЕГРН';
  if(p.too_small)return 'участок мельче '+landNum((data.min_area_sqm||0)/100,0)+' соток';
  return 'участок не проверялся';
 };
 if(v.status==='NOT_SCREENED'&&single){
  const why=skipWhy(data.parcels[0]);
  const tail=(data.parcels[0]&&data.parcels[0].too_small)
   ?'. Порог снимается в запросе, если участок всё же нужен'
   :', а без границ участка спрашивать НСПД не о чем';
  body='<ul><li>Ограничения не проверялись: '+escapeHtml(why)+escapeHtml(tail)+'.</li></ul>';
 }else if(single){
  const p=found[0];
  const flags=(p&&p.findings)||[];
  body=flags.length?list(flags)
   :'<ul><li>В НСПД ограничений на участок не обнаружено.</li></ul>';
  // Рамка запроса шире контура намеренно: иначе полоса вдоль границы не
  // находится. Зоны, задевшие рамку, но не сам участок, показываются отдельно
  // и без флага — молча выброшенное ограничение читается как его отсутствие,
  // а поставленное в общий список выглядит запретом здесь.
  const near=(p&&p.nearby)||[];
  if(near.length)body+=`<div class="meta" style="margin-top:10px">Рядом с участком, но не на нём — ${near.length} `
   +`ограничени${near.length===1?'е':(near.length<5?'я':'й')}: `
   +escapeHtml(near.slice(0,4).map(f=>f.name||f.type_zone||f.category||'зона').join(', '))
   +`${near.length>4?' и ещё '+(near.length-4):''}. На вывод они не влияют: `
   +`ни одна не накрывает участок.</div>`;
 }else{
  // Перечисляются все запрошенные участки, а не только найденные: человек
  // ввёл двадцать два номера и вправе увидеть двадцать две строки. Пропущенный
  // участок, которого нет в списке, читается как проверенный и чистый.
  body=data.parcels.map(p=>{
   const flags=p.findings||[];
   const skipped=skipReason(p);
   const head=`<div class="parcel">${escapeHtml(p.cadastral_number)}`+
    `${p.area_ha!=null?', '+landNum(p.area_ha,4)+' га':''}`+
    `: ${skipped?escapeHtml(skipped):(flags.filter(f=>f.flag_class==='killer').length?'есть запрет':(flags.length?flags.length+' ограничени'+(flags.length===1?'е':'й'):'чисто'))}</div>`;
   return head+(!skipped&&flags.length?list(flags):'');
  }).join('');
 }
 const missed=data.parcels.filter(p=>!p.found&&!p.probe_failed).length;
 // Недоступность НСПД — не ответ об участке: у неё своя строка, иначе
 // сорванные запросы читаются как «таких участков нет».
 const unreached=data.parcels.filter(p=>p.probe_failed).length;
 // Сумма должна сходиться с тем, что ввёл человек: проверено + мелкие + без
 // сведений ЕГРН + не поместившиеся = запрошено. Иначе «участков: 10» на
 // двадцати двух введённых выглядит потерей участков (замечание владельца,
 // 19.08.2026).
 const asked=data.requested_count||data.parcels.length;
 const cut=Math.max(0,(data.requested_count||0)-(data.checked_count||0));
 box.className='land-screening '+tone;
 const counts=[asked>1?'участков: '+asked:'',asked>1?'проверено: '+screened:'',
  data.small_count?'мелких пропущено: '+data.small_count:'',missed?'без сведений ЕГРН: '+missed:'',
  unreached?'НСПД не ответил: '+unreached:'',cut?'не поместилось в запрос: '+cut:''].filter(Boolean);
 box.innerHTML=`<header>${escapeHtml(v.headline||'Оценка участка')}.`+
  `${counts.length?' Всего '+counts.join(', ')+'.':''}`+
  `${v.free_pct!=null?' Свободно от ограничений около '+landNum(v.free_pct,0)+'% площади'+
    (screened<asked?' проверенных участков':'')+'.':''}</header>`+
  body+spot+
  `<footer>${escapeHtml(v.disclaimer||'')}`+
  `${data.small_count?' Участки мельче '+landNum((data.min_area_sqm||0)/100,0)+' соток не проверялись: '+
    'посадку они не определяют, а стоят столько же, сколько крупные.':''}`+
  ` Проверено ${escapeHtml(data.calculated_at||'')}.</footer>`;
}

function landNum(value,digits){
 if(value==null||value==='')return '—';
 const number=Number(value);
 if(!isFinite(number))return '—';
 return number.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
}

// Координаты показываем с точкой, иначе «55,9105, 37,7365» читается как четыре числа.
function landCoords(center){
 if(!center||center.lat==null||center.lng==null)return '—';
 return Number(center.lat).toFixed(6)+', '+Number(center.lng).toFixed(6);
}

function landDate(value){
 const text=String(value||'').trim();
 const iso=text.match(/^(\d{4})-(\d{2})-(\d{2})/);
 return iso?`${iso[3]}.${iso[2]}.${iso[1]}`:(text||'—');
}

// Снимок ЕГРН относится к тому запросу, по которому получен. Прежде блок жил
// сам по себе: расчёт ТЭП по кадастровому номеру идёт через /cadastral/analyze
// и ЕГРН не трогает, поэтому карточка предыдущего участка оставалась на экране
// рядом с новым ТЭП. На одном экране выходили два участка сразу — «ТЭП посчитан:
// 2,0844 га» и «Суммарная площадь 0,9820 га», оба достоверные с виду.
function landQueryKey(text){
 return String(text||'').toLowerCase().replace(/\s+/g,' ').trim();
}
function landSnapshotFits(){
 const field=document.getElementById('cadastralNumbers');
 if(!landLookup||!field)return false;
 return landQueryKey(landLookup.query)===landQueryKey(field.value);
}
function hideLandPreview(){
 const preview=document.getElementById('landPreview');
 if(preview)preview.style.display='none';
}
function dropStaleLandPreview(){
 if(!landSnapshotFits())hideLandPreview();
}

// Что человек вписал в поле участка — это данные ПРОЕКТА, а не побочный след
// удачного ответа внешнего источника. Прежде номер оседал только там, где
// кто-то ответил: `_cadastral_analysis` пишет расчёт ГлавАПУ, `_land_lookup` —
// ЕГРН, и то лишь при `found_count>0`. Не ответил никто — и номер жил только в
// DOM: замер 15.09.2026 на живой странице дал после сохранения и открытия
// метку записи `[]`, ни одного ключа с «cad» во вводных и пустое поле. То есть
// проект открывался без участка ровно в тот день, когда НСПД лежал.
// «Что похоже на кадастровый номер» страница отвечала ЧЕТЫРЬМЯ литералами —
// проверкой строки целиком, проверкой вхождения и двумя выборками всех номеров
// подряд. Пятой копией стала бы метка записи проекта, и разошлись бы они молча:
// копию негде обновлять, потому что копии нет. Формы две, источник один.
const CADASTRAL_NUMBER_SOURCE='\\d{2}:\\d{2}:\\d{6,8}:\\d+';
const CADASTRAL_NUMBER_RE=new RegExp('^'+CADASTRAL_NUMBER_SOURCE+'$');
function cadastralNumbersIn(text){
 return String(text==null?'':text).match(new RegExp(CADASTRAL_NUMBER_SOURCE,'g'))||[];
}

function rememberCadastralQuery(value){
 const text=String(value==null?'':value).trim().slice(0, 600);
 if(text)inputs._cadastral_query=text; else delete inputs._cadastral_query;
}

// Единственный писатель поля: он же и запоминает. Две двери — набранное руками
// и поставленное кодом — разошлись бы молча, и половина проектов сохраняла бы
// участок, а половина нет.
// `origin` — откуда номер ({source:'document',text}); не передан — прежнее
// происхождение остаётся: восстановление сохранённого проекта номер не
// меняет и источник у него не отбирает.
function writeCadastralField(value,origin){
 const field=document.getElementById('cadastralNumbers');
 if(field)field.value=String(value==null?'':value);
 rememberCadastralQuery(value);
 if(origin)inputs._cadastral_origin=origin;
 showCadastralOrigin();
}
// Набранное руками — ручное: номер из документа, исправленный человеком,
// документу больше не принадлежит.
function typeCadastralField(value){
 rememberCadastralQuery(value);
 if(inputs._cadastral_origin&&inputs._cadastral_origin.source!=='manual')
  inputs._cadastral_origin={source:'manual',text:'вписано вручную'};
 showCadastralOrigin();
}
function showCadastralOrigin(){
 const field=document.getElementById('cadastralNumbers');
 if(!field||!field.parentNode)return;
 let note=document.getElementById('cadastralOrigin');
 const o=inputs._cadastral_origin;
 const text=o&&o.source==='document'&&inputs._cadastral_query?'Номер '+(o.text||'из документа'):'';
 if(!text){if(note)note.remove();return}
 if(!note){note=document.createElement('div');note.id='cadastralOrigin';note.className='glavapu-origin';
  note.style.cssText='font-size:11px;color:#666;margin-top:4px';
  field.parentNode.parentNode.insertBefore(note,field.parentNode.nextSibling)}
 note.textContent=text;
}

// Запасное восстановление участка: номер без контура и без карточки. Стоит
// ПЕРВЫМ в цепочке `renderStored*` — у кого есть ответ источника, тот перепишет
// поле своим; у кого нет, останется хотя бы то, что человек вписал. Статуса
// «показана территория из проекта» здесь нет намеренно: мы ничего не
// показываем, мы только вернули строку поиска.
function renderStoredCadastralQuery(){
 const stored=inputs._cadastral_query;
 if(!stored)return;
 const field=document.getElementById('cadastralNumbers');
 if(field)field.value=String(stored);
 showCadastralOrigin();
}

async function lookupLand(options){
 const field=document.getElementById('cadastralNumbers');
 const button=document.getElementById('cadastralAnalyzeButton');
 const status=document.getElementById('cadastralStatus');
 const raw=(field&&field.value||'').trim();
 if(!raw){status.innerHTML='<span class="import-error">Введите кадастровый номер, адрес или координаты.</span>';return}
 button.disabled=true;button.textContent='Ищу…';
 status.textContent='Запрашиваю данные об участке в госреестре…';
 hideLandPreview();
 try{
  const response=await fetch('/land/lookup',{
   method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:raw,limit:30,session:activeSession()})
  });
  const data=await response.json();
  if(!response.ok)throw new Error(serverDetail(data)||'Не удалось получить данные об участке из госреестра');
  landLookup=data;
  // Снимок сохраняется в проект сразу: отдельная кнопка «Сохранить участок»
  // была лишним шагом, и забытая, она молча теряла сведения при закрытии.
  inputs._land_lookup=cloneValue(data);
  renderLandLookup(data);
  // Скрининг — довесок к карточке, а не ответ на запрос. Его сбой не имеет
  // права утащить весь поиск в ветку ошибки: сведения ЕГРН уже получены, и
  // сказать про них «не удалось» значит соврать про то, что удалось. Свою
  // неудачу скрининг показывает в своём блоке.
  try{loadLandScreening(raw)}catch(e){}
  const found=Number(data.found_count||0);
  if(!(options&&options.quiet)){
   status.innerHTML=found
    ?'<span class="import-ok">Найдено объектов в госреестре: '+found+'.</span> Проверьте данные ниже.'
    :'<span class="import-error">В госреестре ничего не нашлось.</span> Уточните номер или адрес.';
  }
  return (data.results||[]).filter(x=>x&&x.found);
 }catch(e){
  // Сорванный запрос — не «участок не найден». Возвращаем null, а не пустой
  // список: вызывающий обязан отличить «спросили, и там пусто» от «спросить
  // не удалось», иначе он закрасит настоящую причину своим диагнозом.
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))
   +'</span>'+CONNECTION_HINT;
  return null;
 }finally{
  button.disabled=false;button.textContent='Получить ТЭП';
 }
}

// Карта не ответила — подпись не имеет права обещать подложку, которой нет:
// прежде img молча снимал себя, а под контуром оставалось «подложка —
// публичная карта НСПД», и отличить «НСПД молчит» от «карта не завезена»
// было нельзя (скриншоты владельца, 16.08.2026).
function landMapLost(img){
 try{
  const box=img.closest('.land-contour');
  img.remove();
  // Правим ТОЛЬКО свой кусок подписи. Прежде переписывался textContent всей
  // строки, а это стирает вложенные узлы: ссылку «развернуть карту» и место
  // для номера участка сносило ровно тогда, когда НСПД молчит, — то есть в
  // том самом случае, ради которого функция и написана.
  const note=box&&box.querySelector('.land-map-note');
  if(note){note.textContent='Карта НСПД не ответила, показан только контур.';return}
  const cap=box&&box.querySelector('small');
  if(cap)cap.textContent=cap.textContent.replace('Фон — публичная карта НСПД.','Карта НСПД не ответила, показан только контур.');
 }catch(e){}
}

// Площадь контура по формуле шнурков — только чтобы разложить участки по
// порядку отрисовки. Знак не важен: обход колец бывает любой.
function landRingArea(rings){
 return (rings||[]).reduce((sum,ring)=>{
  const pts=(ring||[]).filter(p=>Array.isArray(p)&&p.length>=2);
  let a=0;
  for(let i=0;i<pts.length;i++){
   const q=pts[(i+1)%pts.length];
   a+=pts[i][0]*q[1]-q[0]*pts[i][1];
  }
  return sum+Math.abs(a)/2;
 },0);
}

function landTerritorySvg(found){
 // Несколько участков — общая посадка: все контуры в одном масштабе, как они
 // стоят друг относительно друга. По одному участку хватает миниатюры в его
 // карточке.
 const items=(found||[]).filter(x=>Array.isArray(x.contour_merc)&&x.contour_merc.length)
  // Крупные вниз, мелкие наверх. Заполненный контур перехватывает указатель
  // на всей своей площади, поэтому участок, нарисованный последним, отвечал
  // за всех: на территории из двадцати наведение в любую точку показывало
  // один и тот же номер — тот, что лежит поверх (экран владельца,
  // 27.08.2026). Порядок по площади возвращает мелким шанс быть наведёнными.
  .slice().sort((a,b)=>landRingArea(b.contour_merc)-landRingArea(a.contour_merc));
 if(items.length<2)return '';
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 items.forEach(item=>item.contour_merc.forEach(ring=>(ring||[]).forEach(p=>{
  if(!Array.isArray(p)||p.length<2)return;
  minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
 })));
 if(!(maxX>minX)||!(maxY>minY))return '';
 const spanX=maxX-minX,spanY=maxY-minY;
 const pad=Math.max(spanX,spanY)*0.05;
 const w=spanX+pad*2,h=spanY+pad*2;
 const paths=items.map(item=>{
  const d=item.contour_merc.map(ring=>'M'+ring
   .filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>((p[0]-minX+pad)).toFixed(1)+' '+((maxY-p[1]+pad)).toFixed(1))
   .join(' L ')+' Z').join(' ');
  const cad=escapeHtml(item.cadastral_number||'');
  // Номер едет атрибутом, а не подстановкой в JS-строку обработчика: см.
  // правило про &#39; в CLAUDE.md.
  return `<path d="${d}" fill="rgba(245,245,243,.35)" stroke="#111" stroke-width="2" fill-rule="evenodd" vector-effect="non-scaling-stroke" data-cad="${cad}" onmouseenter="landTerritoryHover(this)" onmouseleave="landTerritoryHover(null)"><title>${cad}</title></path>`;
 }).join('');
 const mapSrc=`/land/map-image?bbox=${(minX-pad).toFixed(1)},${(minY-pad).toFixed(1)},${(maxX+pad).toFixed(1)},${(maxY+pad).toFixed(1)}`;
 // max-width держит высоту на истинном аспекте: при 100% ширины и max-height
 // сцена сплющивалась (preserveAspectRatio="none" тянул и подложку, и контур
 // по ширине — «высота маленькая», замечание владельца 17.08.2026). Ширина,
 // при которой высота ровно 240px, — 240·w/h; выше не поднимется, форма верна.
 const stage=`aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)};max-width:${Math.round(240*w/h)}px`;
 return `<div class="land-contour land-territory"><div class="land-contour-stage" style="${stage}">`+
  `<img class="land-contour-map" src="${mapSrc}" alt="" loading="lazy" decoding="async" onerror="landMapLost(this)">`+
  `<svg viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}" preserveAspectRatio="none" role="img" aria-label="Взаимное расположение участков">${paths}</svg></div>`+
  // Номер показывается подписью, а не одной лишь всплывающей подсказкой SVG:
  // её ждать секунду, а на телефоне не бывает вовсе — «наведите, увидите
  // номер» обещало то, чего человек не видел.
  `<small>Территория из ${items.length} участков в одном масштабе. `+
  `<span class="land-map-note">Фон — публичная карта НСПД.</span> `+
  `<a href="#" onclick="landMapFromTerritory();return false">Развернуть карту</a>. `+
  `<b id="landTerritoryLabel" style="color:#111">Наведите на контур, чтобы увидеть номер участка.</b></small></div>`;
}

function landTerritoryHover(path){
 const label=document.getElementById('landTerritoryLabel');
 if(!label)return;
 label.textContent=(path&&path.dataset.cad)||'Наведите на контур, чтобы увидеть номер участка.';
}

function landMapFromTerritory(){
 // Вся территория разом: на общем виде спрашивают не про один участок, а про
 // то, что вокруг них всех. Кольца берутся те же, что нарисованы, — второй
 // сборки нет.
 const items=((landLookup&&landLookup.results)||[])
  .filter(x=>x&&x.found&&Array.isArray(x.contour_merc)&&x.contour_merc.length);
 const rings=items.flatMap(x=>x.contour_merc);
 if(!rings.length)return;
 const zones=((landScreeningLast&&landScreeningLast.parcels)||[])
  .flatMap(p=>(p&&p.findings)||[]);
 openLandMap({rings:rings,zones:zones,massing:siteMassingMapShapes(),
  title:`Территория из ${items.length} участков и окружение`,panorama:true});
}

function landContourSvg(item){
 // Миниатюра границ: свой SVG по кольцам из ЕГРН, без внешних карт — работает
 // и в телеграм-WebView, и при недоступной НСПД. Координаты — веб-меркатор:
 // для формы участка это плоскость, но метр в нём растянут на 1/cos(широты),
 // поэтому подпись ширины пересчитывается через широту центра.
 const rings=item.contour_merc;
 if(!Array.isArray(rings)||!rings.length)return '';
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 rings.forEach(ring=>(ring||[]).forEach(p=>{
  if(!Array.isArray(p)||p.length<2)return;
  minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
 }));
 if(!(maxX>minX)||!(maxY>minY))return '';
 const spanX=maxX-minX,spanY=maxY-minY;
 const pad=Math.max(spanX,spanY)*0.06;
 const w=spanX+pad*2,h=spanY+pad*2;
 const paths=rings.map(ring=>'M'+ring
  .filter(p=>Array.isArray(p)&&p.length>=2)
  .map(p=>((p[0]-minX+pad)).toFixed(1)+' '+((maxY-p[1]+pad)).toFixed(1))
  .join(' L ')+' Z').join(' ');
 const cosLat=item.center&&item.center.lat?Math.cos(item.center.lat*Math.PI/180):0;
 const widthM=cosLat?Math.round(spanX*cosLat):0;
 const scaleNote=widthM?` Ширина — около ${widthM.toLocaleString('ru-RU')} м.`:'';
 // Подложка — кадастровая карта НСПД под тем же bbox: соседи и кварталы
 // дают контекст «где это». Не загрузилась — картинка молча исчезает, и
 // остаётся чистый контур: подложка — украшение, а не данные.
 const mapSrc=`/land/map-image?bbox=${(minX-pad).toFixed(1)},${(minY-pad).toFixed(1)},${(maxX+pad).toFixed(1)},${(maxY+pad).toFixed(1)}`;
 // max-width — высота на истинном аспекте, а не сплющена потолком (см. landTerritorySvg).
 const stage=`aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)};max-width:${Math.round(240*w/h)}px`;
 return `<div class="land-contour"><div class="land-contour-stage" style="${stage}">`+
  `<img class="land-contour-map" src="${mapSrc}" alt="" loading="lazy" decoding="async" onerror="landMapLost(this)">`+
  `<svg viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}" preserveAspectRatio="none" role="img" aria-label="Границы участка по ЕГРН">`+
  `<path d="${paths}" fill="rgba(245,245,243,.35)" stroke="#111" stroke-width="2.5" fill-rule="evenodd" vector-effect="non-scaling-stroke"/></svg></div>`+
  `<small>Границы по сведениям ЕГРН. `+
  `<span class="land-map-note">Фон — публичная карта НСПД.</span>${scaleNote}`+
  // Номер едет атрибутом, а не подстановкой в JS-строку обработчика:
  // escapeHtml превращает кавычку в &#39;, браузер раскодирует её обратно ДО
  // разбора скрипта — и экранированное значение снова становится кодом.
  ` <a href="#" data-cad="${escapeHtml(item.cadastral_number||'')}"`+
  ` onclick="landMapFromContour(this.dataset.cad);return false">Развернуть карту</a></small></div>`;
}

// Карта, которую крутят. Миниатюра отвечает на «как выглядит участок», а на
// «что вокруг» ответить не может: сервер отдал ровно тот bbox, о котором его
// попросили, подвинуть картинку нечем (решение владельца, 27.08.2026).
//
// Считает тот же веб-меркатор, что миниатюра и пятно застройки, — и это не
// стилистика. Контуры ЕГРН и очертания зон приезжают в метрах меркатора
// (`contour_merc`, `outline_merc`); готовая библиотека карт работает в паре
// «широта, долгота», и каждое кольцо пришлось бы переводить. Перепутанный
// порядок пары молча зеркалит полигон — участок остаётся правдоподобным и
// встаёт не туда. Здесь переводить нечего: те же числа, только с переносом
// и увеличением.
const LAND_MAP_WORLD=2*20037508.342789244;
const LAND_MAP_ORIGIN=-20037508.342789244;
// Ссылка «Открыть панораму в Яндекс Картах» — шаблон сервера
// (`YANDEX_PANORAMA_LINK`), тот же, что у бота: обычная ссылка, не API, ключ
// ей не нужен.
const LAND_PANORAMA_LINK=__DEVELOPAID_PANORAMA_LINK__;
function landMapScale(zoom){return LAND_MAP_WORLD/(256*Math.pow(2,zoom))}
function landMapLat(y){return (2*Math.atan(Math.exp(y/6378137))-Math.PI/2)*180/Math.PI}
// Пиксель карты мира — та же формула, что у серверной склейки (_basemap_png):
// подложка и контур обязаны считать одно, иначе участок съезжает с карты, а
// выглядит это как неточность источника, а не как наша ошибка. y растёт вниз,
// поэтому север — минус.
function landMapWorldPx(x,zoom){return (x-LAND_MAP_ORIGIN)/landMapScale(zoom)}
function landMapWorldPy(y,zoom){return (-y-LAND_MAP_ORIGIN)/landMapScale(zoom)}
// Экран: центр вида стоит в центре сцены. Одна функция на тайлы, контур, зоны
// и линейку — разъехаться нечему.
function landMapProject(point,view){
 return [landMapWorldPx(point[0],view.zoom)-landMapWorldPx(view.cx,view.zoom)+view.width/2,
         landMapWorldPy(point[1],view.zoom)-landMapWorldPy(view.cy,view.zoom)+view.height/2];
}
function landMapUnproject(sx,sy,view){
 const scale=landMapScale(view.zoom);
 return [view.cx+(sx-view.width/2)*scale,view.cy-(sy-view.height/2)*scale];
}
function landMapView(){
 const stage=document.getElementById('landMapStage');
 if(!stage||!LAND_MAP)return null;
 const rect=stage.getBoundingClientRect();
 return {zoom:LAND_MAP.zoom,cx:LAND_MAP.cx,cy:LAND_MAP.cy,
         width:Math.max(200,Math.round(rect.width)),height:Math.max(160,Math.round(rect.height)),
         left:rect.left,top:rect.top};
}
// Метр меркатора — не метр земли: он растянут на 1/cos(широты). Линейка и
// подпись масштаба обязаны считать по земле, иначе на широте Москвы всё
// показанное расстояние будет больше настоящего в полтора раза.
function landMapGround(mercatorMetres,y){return mercatorMetres*Math.cos(landMapLat(y)*Math.PI/180)}
function landMapMetres(pixels,zoom,y){return landMapGround(pixels*landMapScale(zoom),y)}

// Гибрид Яндекса — снимок со спутника с улицами и подписями. Отдаёт его только
// JavaScript API Яндекса, и только в браузере: серверная склейка (`/land/basemap`)
// снимка не получит, а условия Яндекса запрещают его сохранять. Поэтому гибрид —
// вид живой карты, а не картинка; в отчёт и в бот уходит карта улиц.
//
// Проекция здесь главная ловушка. Тайлы Яндекса лежат в эллиптическом
// меркаторе (EPSG:3395), а контуры ЕГРН у нас — в сферическом (EPSG:3857).
// Нарисовать контур нашими пикселями поверх снимка Яндекса значит увести его
// на ~200 м к северу на широте Москвы, и выглядело бы это как неточность ЕГРН.
// Поэтому контуры уходят в Яндекс широтой и долготой, а проекцию API считает
// сам: метры сферического меркатора переводятся обратной формулой ТОЙ ЖЕ
// сферы (`landMapGeo`), и никакой своей эллиптической формулы здесь нет.
function landMapGeo(point){
 return [landMapLat(point[1]),point[0]/6378137*180/Math.PI];
}
function landMapMerc(geo){
 return [geo[1]*Math.PI/180*6378137,6378137*Math.log(Math.tan(Math.PI/4+geo[0]*Math.PI/360))];
}
// Один вопрос — один ответ: предлагать ли гибрид, решает сервер по ключу, и
// спрашивается он один раз на страницу. Сбой вопроса — тоже ответ с причиной,
// а не молча спрятанная кнопка.
function landMapViews(){
 if(!LAND_MAP_VIEWS){
  LAND_MAP_VIEWS=fetch('/land/basemap-views',{credentials:'same-origin'})
   .then(r=>r.ok?r.json():Promise.reject(new Error('сервер ответил '+r.status)))
   .catch(e=>({map:{available:true},hybrid:{available:false,
     reason:'Не удалось узнать, подключён ли снимок со спутника ('+String(e.message||e)
       +'). Карта улиц работает как обычно.'}}));
 }
 return LAND_MAP_VIEWS;
}
function landMapLayerPref(){
 try{return localStorage.getItem('plato.basemap')==='hybrid'?'hybrid':'map'}catch(e){return 'map'}
}
function landMapLayerBar(){
 const bar=document.getElementById('landMapLayers');
 if(!bar||!LAND_MAP)return;
 const hybrid=(LAND_MAP.views&&LAND_MAP.views.hybrid)||null;
 const on=LAND_MAP.layer;
 const btn=(layer,label,enabled,hint)=>`<button type="button" data-layer="${layer}"`
  +` onclick="landMapSetLayer('${layer}')"${enabled?'':' disabled'} title="${escapeHtml(hint||'')}"`
  +` aria-pressed="${on===layer?'true':'false'}" style="border:1px solid #3b6db4;`
  +`background:${on===layer?'#3b6db4':'#fff'};color:${on===layer?'#fff':(enabled?'#3b6db4':'#999')};`
  +`border-radius:6px;padding:4px 10px;cursor:${enabled?'pointer':'not-allowed'};font-size:12px">${label}</button>`;
 bar.innerHTML=btn('map','Схема',true,'Карта улиц OpenStreetMap')
  +btn('hybrid','Гибрид',!!(hybrid&&hybrid.available),
       hybrid?(hybrid.available?'Снимок со спутника с улицами — Яндекс Карты':hybrid.reason):'Проверяем, подключён ли снимок…')
  // Панорама нажимается всегда: где встроенной нет, она открывает ссылку на
  // Яндекс Карты и называет причину, а не прячется.
  +(LAND_MAP.panoramaUrl?btn('panorama','Панорама',true,'Улицы вокруг участка глазами пешехода — Яндекс Карты'):'');
}
function landPanoramaUrl(lat,lng){
 lat=Number(lat);lng=Number(lng);
 if(!isFinite(lat)||!isFinite(lng)||Math.abs(lat)>90||Math.abs(lng)>180)return '';
 return LAND_PANORAMA_LINK.split('{lat}').join(lat.toFixed(6)).split('{lng}').join(lng.toFixed(6));
}
function landMapYandex(src){
 if(window.ymaps&&window.ymaps.ready)return new Promise(ok=>window.ymaps.ready(()=>ok(window.ymaps)));
 return new Promise((ok,fail)=>{
  const tag=document.createElement('script');
  tag.src=src;tag.async=true;
  tag.onload=()=>window.ymaps?window.ymaps.ready(()=>ok(window.ymaps)):fail(new Error('скрипт пришёл без карты'));
  tag.onerror=()=>fail(new Error('Карты Яндекса не загрузились'));
  document.head.appendChild(tag);
 });
}
function landMapSetLayer(layer){
 if(!LAND_MAP||(layer!=='map'&&layer!=='hybrid'&&layer!=='panorama'))return;
 const hybrid=LAND_MAP.views&&LAND_MAP.views.hybrid;
 LAND_MAP.layerNote='';
 if(layer==='panorama'){
  // Панорама не запоминается выбором вида: открытие карты не должно само
  // тратить показ из суточного лимита.
  if(LAND_MAP.layer==='panorama')return;
  if(LAND_MAP.layer==='hybrid')landMapHybridClose();
  LAND_MAP.layer='panorama';
  landMapLayerBar();
  landMapPanoramaOpen();
  return;
 }
 if(LAND_MAP.layer==='panorama')landMapPanoramaClose();
 if(layer==='hybrid'&&!(hybrid&&hybrid.available)){
  // Не предлагали — не включаем, и не подменяем схемой молча: причина в подписи.
  LAND_MAP.layerNote=(hybrid&&hybrid.reason)||'Снимок со спутника не подключён.';
  layer='map';
 }
 try{localStorage.setItem('plato.basemap',layer)}catch(e){}
 if(LAND_MAP.layer==='panorama')LAND_MAP.layer='map';
 if(layer===LAND_MAP.layer&&(layer==='map'||LAND_MAP.ymap)){landMapLayerBar();renderLandMap();return}
 if(LAND_MAP.layer==='hybrid')landMapHybridClose();
 LAND_MAP.layer=layer;
 landMapLayerBar();
 if(layer==='map'){renderLandMap();return}
 landMapHybridOpen();
}
function landMapHybridOpen(){
 const stage=document.getElementById('landMapStage');
 const state=LAND_MAP;
 if(!stage||!state)return;
 stage.innerHTML='<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#555;font-size:13px">Загружаем снимок со спутника…</div>';
 landMapNote();
 landMapYandex(state.views.hybrid.script).then(ymaps=>{
  if(LAND_MAP!==state||state.layer!=='hybrid')return;
  stage.innerHTML='<div id="landMapYandex" style="position:absolute;inset:0"></div>';
  // Проекцию не задаём: у Яндекса она своя (эллиптическая), и снимок с
  // контуром совпадают только тогда, когда обоих считает API.
  const map=new ymaps.Map('landMapYandex',{
   center:landMapGeo([state.cx,state.cy]),zoom:Math.round(state.zoom),
   type:'yandex#hybrid',controls:['zoomControl','rulerControl'],
  });
  const geo=rings=>(rings||[]).map(ring=>(ring||[]).filter(p=>Array.isArray(p)&&p.length>=2).map(landMapGeo));
  (state.shapes||[]).filter(s=>Array.isArray(s.rings)&&s.rings.length).forEach((shape,i)=>{
   const colour=shape.colour||'#777777';
   const poly=new ymaps.Polygon(geo(shape.rings),{hintContent:String(shape.title||'')},
    {fillColor:colour,fillOpacity:0.34,strokeColor:colour,strokeWidth:1.5});
   if(typeof state.onPick==='function')poly.events.add('click',()=>state.onPick(String(shape.key||i)));
   map.geoObjects.add(poly);
  });
  const paint={killer:'#b3261e',economic:'#a05a00',info:'#777777'};
  (state.zones||[]).filter(z=>Array.isArray(z.outline_merc)&&z.outline_merc.length).forEach(zone=>{
   const colour=paint[zone.flag_class]||'#777777';
   map.geoObjects.add(new ymaps.Polygon(geo(zone.outline_merc),{},
    {fillColor:colour,fillOpacity:0.22,strokeColor:colour,strokeWidth:1.5}));
  });
  if((state.rings||[]).length){
   // На снимке тёмный контур теряется — граница участка жёлтая, как на кадастре.
   map.geoObjects.add(new ymaps.Polygon(geo(state.rings),{},
    {fillColor:'#ffffff',fillOpacity:0.12,strokeColor:'#ffd400',strokeWidth:3}));
  }
  if(state.measuring)map.behaviors.enable('ruler');
  state.ymap=map;
  landMapNote();
 }).catch(e=>{
  if(LAND_MAP!==state)return;
  state.layer='map';
  state.layerNote='Снимок со спутника не открылся: '+String(e.message||e)+'. Показана карта улиц.';
  landMapLayerBar();
  renderLandMap();
 });
}
function landMapHybridClose(){
 const state=LAND_MAP;
 if(!state||!state.ymap)return;
 // Вид не прыгает при переключении: центр и масштаб забираем у Яндекса обратно.
 try{
  const merc=landMapMerc(state.ymap.getCenter());
  state.cx=merc[0];state.cy=merc[1];
  state.zoom=Math.max(3,Math.min(19,Math.round(state.ymap.getZoom())));
  state.ymap.destroy();
 }catch(e){}
 state.ymap=null;
}
// Панорама Яндекса — бесплатный тариф (решение владельца 25.10.2026): только
// в открытой части (`payload.panorama`) и не больше суточного лимита, который
// считает сервер (`/land/panorama/claim`). Во всех прочих случаях — кнопка-
// ссылка на Яндекс Карты и причина словами, а не пустое окно.
function landMapPanoramaRefuse(reason){
 const stage=document.getElementById('landMapStage');
 const state=LAND_MAP;
 if(!stage||!state)return;
 state.panoramaReason=reason;
 stage.innerHTML='<div data-panorama="link" style="position:absolute;inset:0;display:flex;flex-direction:column;'
  +'align-items:center;justify-content:center;gap:14px;padding:24px;text-align:center;background:#f4f4f1">'
  +'<div id="landMapPanoramaReason" style="max-width:560px;font-size:14px;color:#333;line-height:1.45">'+escapeHtml(reason)+'</div>'
  +'<a id="landMapPanoramaLink" href="'+escapeHtml(state.panoramaUrl)+'" target="_blank" rel="noopener" '
  +'style="display:inline-block;background:#3b6db4;color:#fff;border-radius:8px;padding:10px 18px;'
  +'font-size:14px;text-decoration:none">Открыть панораму в Яндекс Картах</a></div>';
 landMapNote();
}
function landMapPanoramaOpen(){
 const stage=document.getElementById('landMapStage');
 const state=LAND_MAP;
 if(!stage||!state)return;
 state.panoramaReason='';
 if(!state.panoramaEmbed){
  landMapPanoramaRefuse('На этой странице встроенной панорамы нет: она открывается в самих Яндекс Картах, в точке участка.');
  return;
 }
 const view=(state.views&&state.views.panorama)||null;
 if(!view||!view.available){
  landMapPanoramaRefuse((view&&view.reason)||'Встроенная панорама сейчас недоступна. Панораму можно открыть в самих Яндекс Картах — кнопка ниже.');
  return;
 }
 stage.innerHTML='<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#555;font-size:13px">Загружаем панораму…</div>';
 landMapNote();
 const stale=()=>LAND_MAP!==state||state.layer!=='panorama';
 fetch('/land/panorama/claim',{method:'POST',credentials:'same-origin',
   headers:{'Content-Type':'application/json'},body:'{}'})
  .then(r=>r.ok?r.json():Promise.reject(new Error('сервер ответил '+r.status)))
  .catch(e=>({granted:false,reason:'Не удалось проверить, остались ли сегодня встроенные панорамы. Панораму можно открыть '
    +'в самих Яндекс Картах — кнопка ниже ('+String(e.message||e)+').'}))
  .then(claim=>{
   if(stale())return null;
   if(!claim||!claim.granted){
    // Лимит кончился, пока окно было открыто: следующий раз — сразу ссылка.
    view.available=false;view.reason=(claim&&claim.reason)||'Встроенные панорамы на сегодня закончились.';
    landMapPanoramaRefuse(view.reason);
    return null;
   }
   return landMapYandex(view.script).then(ymaps=>{
    if(stale())return;
    if(!ymaps.panorama||!ymaps.panorama.isSupported()){
     landMapPanoramaRefuse('Этот браузер не умеет показывать панорамы Яндекса. Откройте её в самих Яндекс Картах — кнопка ниже.');
     return;
    }
    return ymaps.panorama.locate(state.panoramaPoint).then(found=>{
     if(stale())return;
     if(!found||!found.length){
      landMapPanoramaRefuse('В этом месте у Яндекса нет панорамы улиц: съёмочный автомобиль здесь не проезжал. '
       +'В Яндекс Картах можно поискать панораму на соседних улицах — кнопка ниже.');
      return;
     }
     stage.innerHTML='<div id="landMapPanorama" style="position:absolute;inset:0"></div>';
     state.player=new ymaps.panorama.Player('landMapPanorama',found[0],{direction:'auto'});
     landMapNote();
    });
   });
  })
  .catch(e=>{
   if(stale())return;
   landMapPanoramaRefuse('Встроенная панорама не открылась. Её можно посмотреть в самих Яндекс Картах — кнопка ниже ('+String(e.message||e)+').');
  });
}
function landMapPanoramaClose(){
 const state=LAND_MAP;
 if(!state)return;
 if(state.player){try{state.player.destroy()}catch(e){}}
 state.player=null;
 state.panoramaReason='';
}
function landMapNote(){
 const note=document.getElementById('landMapNote');
 if(!note||!LAND_MAP)return;
 let text;
 if(LAND_MAP.layer==='panorama'){
  text=LAND_MAP.player
   ?'Панорама улиц — Яндекс Карты. Тяните картинку, чтобы оглядеться; стрелки ведут по улице. В отчёт панорама не попадает.'
   :(LAND_MAP.panoramaReason?'Ссылка откроет панораму в Яндекс Картах в новой вкладке, эта карта останется открытой.':'');
  note.textContent=text;
  return;
 }
 if(LAND_MAP.layer==='hybrid'){
  // Почему снимка нет в отчёте, говорит сервер (`print_reason`): правило одно.
  const hybrid=(LAND_MAP.views&&LAND_MAP.views.hybrid)||{};
  text='Снимок со спутника, улицы и подписи — Яндекс Карты. Границы участков взяты из ЕГРН, зоны — из НСПД.'
   +(hybrid.print_reason?' '+hybrid.print_reason:'');
 }else if(LAND_MAP.measuring){
  text='Линейка включена: щёлкните две точки, и мы покажем расстояние между ними по прямой. Для коэффициента К1 парковки расстояние до входа на станцию меряют пешком, поэтому оно будет длиннее.';
 }else{
  text=LAND_MAP.note||'Тяните карту мышью или пальцем, колесом мыши меняйте масштаб. Границы участков взяты из ЕГРН, зоны — из НСПД, фон — карта OpenStreetMap.';
 }
 if(LAND_MAP.layerNote&&LAND_MAP.layer!=='hybrid')text=LAND_MAP.layerNote+' '+text;
 if((LAND_MAP.massing||[]).length&&LAND_MAP.layer!=='hybrid')
  text='Цветные прямоугольники с номерами — корпуса объёмной схемы из вкладки «ТЭП». Они расставлены рядами для наглядности, это не генплан. '+text;
 note.textContent=text;
}

function openLandMap(payload){
 // payload: {rings, zones, title, note, shapes, onPick, massing}
 // `massing` — корпуса объёмной схемы проекта (`siteMassingMapShapes`): та же
 // раскладка движка, что на схеме во вкладке «ТЭП», в метрах меркатора.
 // `shapes` — чужие контуры со своим цветом и подписью: ими карту КРТ рисует
 // страница торгов. Второй живой карты не заводим: тайлы, проекция, линейка и
 // масштаб объявлены здесь один раз, и копию было бы негде обновлять.
 const box=document.getElementById('landMapDialog');
 if(!box)return;
 const rings=(payload&&payload.rings)||[];
 const shapes=(payload&&payload.shapes)||[];
 const points=rings.flat().concat(shapes.flatMap(s=>(s&&s.rings||[]).flat()))
   .filter(p=>Array.isArray(p)&&p.length>=2);
 if(!points.length)return;
 const minX=Math.min(...points.map(p=>p[0])),maxX=Math.max(...points.map(p=>p[0]));
 const minY=Math.min(...points.map(p=>p[1])),maxY=Math.max(...points.map(p=>p[1]));
 // Окно раскрывается до замера: у скрытого блока ширина ноль, и масштаб
 // считался бы по запасному числу, а не по тому, что человек увидит.
 box.style.display='flex';
 const stage=document.getElementById('landMapStage');
 const width=Math.max(320,(stage&&stage.clientWidth)||900);
 // Открываемся на участке целиком с запасом на окружение: показать участок
 // впритык — это то же, что миниатюра, ради чего тогда открывать.
 const span=Math.max(maxX-minX,maxY-minY,50)*2.4;
 const zoom=Math.log2(LAND_MAP_WORLD/256/(span/width));
 LAND_MAP={
  rings:rings,zones:(payload&&payload.zones)||[],
  shapes:shapes,onPick:(payload&&payload.onPick)||null,
  massing:(payload&&payload.massing)||[],
  title:(payload&&payload.title)||'Участок и окружение',
  note:(payload&&payload.note)||'',
  cx:(minX+maxX)/2,cy:(minY+maxY)/2,
  // Вниз, а не к ближайшему: округление вверх обрезает участок ровно в тот
 // момент, когда его открыли посмотреть целиком.
 zoom:Math.max(3,Math.min(19,Math.floor(zoom))),
  measure:[],measuring:false,drag:null,moved:0,
  layer:'map',views:null,ymap:null,layerNote:'',
  // Точка панорамы — середина того, что открыли; ссылка на Яндекс Карты есть
  // на любой странице, встроенная панорама — только где её разрешили.
  panoramaPoint:landMapGeo([(minX+maxX)/2,(minY+maxY)/2]),
  panoramaEmbed:!!(payload&&payload.panorama),player:null,panoramaReason:'',
 };
 LAND_MAP.panoramaUrl=landPanoramaUrl(LAND_MAP.panoramaPoint[0],LAND_MAP.panoramaPoint[1]);
 renderLandMap();
 landMapLayerBar();
 // Вид выбирается тем, что человек выбрал в прошлый раз, но только когда сервер
 // подтвердил, что гибрид есть: до ответа показана схема, а не пустое поле.
 const state=LAND_MAP;
 landMapViews().then(views=>{
  if(LAND_MAP!==state)return;
  state.views=views;
  landMapLayerBar();
  landMapLayerBar();
  if(landMapLayerPref()==='hybrid')landMapSetLayer('hybrid');
 });
}
function closeLandMap(){
 landMapHybridClose();
 landMapPanoramaClose();
 const box=document.getElementById('landMapDialog');
 if(box)box.style.display='none';
 LAND_MAP=null;
}
function landMapZoomBy(step){
 if(!LAND_MAP)return;
 if(LAND_MAP.layer==='panorama')return;
 if(LAND_MAP.layer==='hybrid'){
  if(LAND_MAP.ymap)LAND_MAP.ymap.setZoom(Math.max(3,Math.min(19,LAND_MAP.ymap.getZoom()+step)));
  return;
 }
 LAND_MAP.zoom=Math.max(3,Math.min(19,LAND_MAP.zoom+step));
 renderLandMap();
}
function landMapMeasureToggle(){
 if(!LAND_MAP)return;
 LAND_MAP.measuring=!LAND_MAP.measuring;
 if(!LAND_MAP.measuring)LAND_MAP.measure=[];
 if(LAND_MAP.ymap){
  // На снимке линейка — своя у Яндекса: она меряет в его же проекции.
  if(LAND_MAP.measuring)LAND_MAP.ymap.behaviors.enable('ruler');
  else LAND_MAP.ymap.behaviors.disable('ruler');
 }
 renderLandMap();
}
function landMapPoint(event){
 const view=landMapView();
 if(!view)return null;
 return landMapUnproject(event.clientX-view.left,event.clientY-view.top,view);
}
function landMapClick(event){
 if(!LAND_MAP||LAND_MAP.layer!=='map')return;
 // Щелчок по чужой фигуре — выбор площадки, а не точка линейки.
 const pick=event.target&&event.target.getAttribute&&event.target.getAttribute('data-pick');
 if(pick!==null&&pick!==undefined&&!LAND_MAP.measuring&&typeof LAND_MAP.onPick==='function'){
  if((LAND_MAP.moved||0)>4)return;
  LAND_MAP.onPick(pick);
  return;
 }
 if(!LAND_MAP.measuring)return;
 // Линейка нужна не «вообще»: К1 приобъектной парковки задаётся расстоянием
 // до входа на станцию (0,75 до 1200 м · 0,9 до 2200 м), и до сих пор его
 // мерили где-то на стороне и вписывали числом.
 // Щелчок приходит и после перетаскивания — точка ставилась бы там, где
 // человек отпустил карту, а не там, куда целился.
 if((LAND_MAP.moved||0)>4)return;
 const point=landMapPoint(event);
 if(!point)return;
 if(LAND_MAP.measure.length>=2)LAND_MAP.measure=[];
 LAND_MAP.measure.push(point);
 renderLandMap();
}
function landMapDown(event){
 // В гибриде карту двигает Яндекс: захват указателя сценой отнял бы у него
 // перетаскивание.
 if(LAND_MAP&&LAND_MAP.layer!=='map')return;
 // Двигать карту можно и с включённой линейкой: иначе, чтобы дотянуться до
 // станции, её пришлось бы выключать, тянуть и включать заново — а меряют
 // как раз то, что в один экран не помещается.
 if(!LAND_MAP)return;
 LAND_MAP.drag={x:event.clientX,y:event.clientY};
 LAND_MAP.moved=0;
 try{event.currentTarget.setPointerCapture(event.pointerId)}catch(e){}
}
function landMapMove(event){
 if(!LAND_MAP||!LAND_MAP.drag||LAND_MAP.layer!=='map')return;
 const scale=landMapScale(LAND_MAP.zoom);
 const dx=event.clientX-LAND_MAP.drag.x,dy=event.clientY-LAND_MAP.drag.y;
 LAND_MAP.moved+=Math.abs(dx)+Math.abs(dy);
 LAND_MAP.cx-=dx*scale;
 LAND_MAP.cy+=dy*scale;
 LAND_MAP.drag={x:event.clientX,y:event.clientY};
 renderLandMap();
}
function landMapUp(){if(LAND_MAP)LAND_MAP.drag=null}
function landMapWheel(event){
 if(!LAND_MAP||LAND_MAP.layer!=='map')return;
 event.preventDefault();
 // Колесо увеличивает к курсору, а не к центру: иначе разглядываемое место
 // уезжает из кадра ровно тогда, когда его разглядывают.
 const before=landMapPoint(event);
 landMapZoomBy(event.deltaY<0?1:-1);
 const after=landMapPoint(event);
 if(before&&after){
  LAND_MAP.cx+=before[0]-after[0];
  LAND_MAP.cy+=before[1]-after[1];
  renderLandMap();
 }
}

function renderLandMap(){
 const stage=document.getElementById('landMapStage');
 const view=landMapView();
 if(!stage||!view)return;
 // Гибрид рисует Яндекс в своём контейнере; перерисовка сцены его бы стёрла.
 // Панораму тоже рисует Яндекс.
 if(LAND_MAP.layer!=='map'){landMapNote();return}
 const W=view.width,H=view.height,zoom=view.zoom,scale=landMapScale(zoom);
 const left=landMapWorldPx(view.cx,zoom)-W/2,top=landMapWorldPy(view.cy,zoom)-H/2;
 const project=p=>landMapProject(p,view);
 const limit=Math.pow(2,zoom);
 let tiles='';
 for(let tx=Math.floor(left/256);tx<=Math.floor((left+W)/256);tx++){
  for(let ty=Math.floor(top/256);ty<=Math.floor((top+H)/256);ty++){
   if(ty<0||ty>=limit)continue;
   const wrapped=((tx%limit)+limit)%limit;
   tiles+=`<img src="/land/tiles/${zoom}/${wrapped}/${ty}.png" alt="" draggable="false"`+
    ` style="position:absolute;left:${Math.round(tx*256-left)}px;top:${Math.round(ty*256-top)}px;`+
    `width:256px;height:256px;user-select:none" onerror="this.style.visibility='hidden'">`;
  }
 }
 const toPath=list=>(list||[]).map(ring=>'M'+(ring||[])
   .filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>project(p).map(v=>v.toFixed(1)).join(' '))
   .join(' L ')+' Z').join(' ');
 const paint={killer:'#b3261e',economic:'#a05a00',info:'#777'};
 const zoneLayers=(LAND_MAP.zones||[]).filter(z=>Array.isArray(z.outline_merc)&&z.outline_merc.length)
  .map(zone=>{
   const colour=paint[zone.flag_class]||'#777';
   return `<path d="${toPath(zone.outline_merc)}" fill="${colour}" fill-opacity="0.22" stroke="${colour}" stroke-width="1.5"/>`;
  }).join('');
 // Чужие фигуры лежат ПОД контуром и ловят указатель: перетаскивание при этом
 // не ломается — событие всплывает к сцене, а щелчок после перетаскивания
 // отсекается тем же счётчиком, что и у линейки.
 const shapeLayers=(LAND_MAP.shapes||[]).filter(s=>Array.isArray(s.rings)&&s.rings.length)
  .map((shape,i)=>{
   const colour=shape.colour||'#777';
   return `<path d="${toPath(shape.rings)}" fill="${colour}" fill-opacity="0.34" stroke="${colour}"`
    +` stroke-width="1.2" data-pick="${escapeHtml(String(shape.key||i))}"`
    +` style="pointer-events:auto;cursor:pointer">`
    +`<title>${escapeHtml(String(shape.title||''))}</title></path>`;
  }).join('');
 const contour=`<path d="${toPath(LAND_MAP.rings)}" fill="rgba(245,245,243,.18)" stroke="#111" stroke-width="2.5" fill-rule="evenodd"/>`;
 // Корпуса схемы — поверх контура: пятно цвета очереди и номер строки легенды.
 const massing=(LAND_MAP.massing||[]).map(b=>{
  const pts=b.ring.map(project);
  const cx=pts.reduce((a,p)=>a+p[0],0)/pts.length,cy=pts.reduce((a,p)=>a+p[1],0)/pts.length;
  return `<g class="land-map-corpus" data-building="${b.number}"><path d="${toPath([b.ring])}" fill="${b.colour}" fill-opacity="0.78" stroke="#1d1d1d" stroke-width="1"><title>${escapeHtml(b.title)}</title></path>`
   +`<text x="${cx.toFixed(1)}" y="${(cy+4).toFixed(1)}" font-size="12" font-weight="700" text-anchor="middle" fill="#fff">${b.number}</text></g>`;
 }).join('');
 let ruler='',rulerNote='';
 if(LAND_MAP.measure.length){
  const pts=LAND_MAP.measure.map(project);
  ruler=pts.map(p=>`<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="5" fill="#fff" stroke="#3b6db4" stroke-width="2.5"/>`).join('');
  if(pts.length===2){
   ruler=`<line x1="${pts[0][0].toFixed(1)}" y1="${pts[0][1].toFixed(1)}" x2="${pts[1][0].toFixed(1)}" y2="${pts[1][1].toFixed(1)}" stroke="#3b6db4" stroke-width="2.5" stroke-dasharray="6 4"/>`+ruler;
   const a=LAND_MAP.measure[0],b=LAND_MAP.measure[1];
   rulerNote=`${landNum(landMapGround(Math.hypot(a[0]-b[0],a[1]-b[1]),LAND_MAP.cy),0)} м по прямой`;
  }
 }
 // Масштабная линейка круглым числом: 500 м «примерно вот столько» читается,
 // а «463 м» — нет.
 const nice=[50,100,200,500,1000,2000,5000];
 const perPx=landMapMetres(1,zoom,LAND_MAP.cy);
 const barM=nice.filter(v=>v/perPx<=W*0.35).pop()||nice[0];
 const barPx=Math.round(barM/perPx);
 stage.innerHTML=`<div style="position:absolute;inset:0;overflow:hidden">${tiles}</div>`+
  `<svg width="${W}" height="${H}" style="position:absolute;inset:0;pointer-events:none">${shapeLayers}${zoneLayers}${contour}${massing}${ruler}</svg>`+
  `<div style="position:absolute;left:12px;bottom:12px;background:rgba(255,255,255,.88);padding:4px 8px;border-radius:4px;font-size:11px;color:#333">`+
  `<div style="border:2px solid #333;border-top:0;height:5px;width:${barPx}px;margin-bottom:2px"></div>${landNum(barM,0)} м · © OpenStreetMap</div>`+
  (rulerNote?`<div style="position:absolute;right:12px;bottom:12px;background:#3b6db4;color:#fff;padding:4px 10px;border-radius:4px;font-size:12px">${escapeHtml(rulerNote)}</div>`:'');
 const head=document.getElementById('landMapTitle');
 if(head)head.textContent=LAND_MAP.title;
 landMapNote();
 const button=document.getElementById('landMapRuler');
 if(button)button.textContent=LAND_MAP.measuring?'Линейка включена':'Линейка';
}

function landMapFromContour(cad){
 // Кнопка стоит у миниатюры и открывает ту же геометрию, что миниатюра
 // нарисовала: второй раз её не собираем — разошлись бы две картинки одного
 // участка, и обе выглядели бы верными. Участок ищется по кадастровому
 // номеру, а не по месту в списке: список фильтруется и переставляется.
 const results=((landLookup&&landLookup.results)||[])
  .filter(x=>x&&x.found&&Array.isArray(x.contour_merc)&&x.contour_merc.length);
 const item=(cad?results.find(x=>x.cadastral_number===cad):null)||results[0];
 if(!item)return;
 const screened=((landScreeningLast&&landScreeningLast.parcels)||[])
  .find(p=>p&&p.cadastral_number&&p.cadastral_number===item.cadastral_number);
 openLandMap({
  rings:item.contour_merc,
  zones:(screened&&screened.findings)||[],
  massing:siteMassingMapShapes(),
  title:item.cadastral_number?('Участок '+item.cadastral_number+' и окружение'):'Участок и окружение',
  // Карточка участка открыта без входа — здесь встроенная панорама разрешена.
  panorama:true,
 });
}

function landCardHtml(item,showContour){
 // showContour=false у карточки, когда участков несколько: общий вид территории
 // (landTerritorySvg) уже показывает все контуры в одном масштабе, и мини-карта
 // в каждой карточке была бы 30 повторов одного и того же — нужен общий рисунок,
 // а не тридцать (замечание владельца, 17.08.2026). Одиночный участок — со своей.
 if(showContour===undefined)showContour=true;
 const panoramaUrl=item.center?landPanoramaUrl(item.center.lat,item.center.lng):'';
 const mapLink=item.map_url
  ?`<div class="land-links"><a href="${escapeHtml(item.map_url)}" target="_blank" rel="noopener">Открыть на публичной кадастровой карте</a>`
   +(panoramaUrl?` · <a href="${escapeHtml(panoramaUrl)}" target="_blank" rel="noopener">Открыть панораму в Яндекс Картах</a>`:'')+`</div>`
  :'';
 if(!item.found){
  const rows=[['Регион по коду округа',item.region||'—'],['Кадастровый квартал',item.quarter||'—']];
  return `<div class="land-item miss"><header><h4>${escapeHtml(item.cadastral_number||'—')}</h4>`+
   `<span class="land-kind">нет сведений</span></header>`+
   `<div class="land-grid">${rows.map(r=>`<div><small>${escapeHtml(r[0])}</small><b>${escapeHtml(r[1])}</b></div>`).join('')}</div>`+
   `<div style="margin-top:9px;font-size:11px;color:#8a6d00">${escapeHtml(item.note||'')}</div>${mapLink}</div>`;
 }
 const rows=[
  ['Адрес',item.address||'—'],
  ['Площадь',item.area_sqm!=null?landNum(item.area_sqm,0)+' м² ('+landNum(item.area_ha,4)+' га)':'—'],
  ['Категория земель',item.category||'—'],
  ['Разрешённое использование',item.permitted_use||'—'],
  ['Кадастровая стоимость',item.cadastral_value_mln!=null?landNum(item.cadastral_value_mln,3)+' млн ₽':'—'],
  ['Удельная стоимость',item.unit_value_rub_per_sqm!=null?landNum(item.unit_value_rub_per_sqm,0)+' ₽/м²':'—'],
  ['Форма собственности',item.ownership||'—'],
  ['Статус объекта',item.status||'—'],
  ['Дата постановки на учёт',landDate(item.registration_date)],
  ['Кадастровый квартал',item.quarter||'—'],
  ['Субъект РФ',item.region||'—'],
  ['Координаты центра',landCoords(item.center)]
 ];
 if(item.matched_address)rows.push(['Адрес по геокодеру',item.matched_address+(item.geocoder?' ('+item.geocoder+')':'')]);
 return `<div class="land-item"><header><h4>${escapeHtml(item.cadastral_number||'—')}</h4>`+
  `<span class="land-kind">${escapeHtml(item.kind_label||'')}${item.cadastral_value_date?', оценка от '+escapeHtml(landDate(item.cadastral_value_date)):''}</span></header>`+
  `<div class="land-grid">${rows.map(r=>`<div><small>${escapeHtml(r[0])}</small><b>${escapeHtml(r[1])}</b></div>`).join('')}</div>${showContour?landContourSvg(item):''}${mapLink}</div>`;
}

function renderLandLookup(data){
 if(!data)return;
 const results=data.results||[];
 const found=results.filter(x=>x.found);
 const totalHa=found.reduce((sum,x)=>sum+Number(x.area_ha||0),0);
 const totalValue=found.reduce((sum,x)=>sum+Number(x.cadastral_value_mln||0),0);
 const regions=[...new Set(found.map(x=>x.region).filter(Boolean))];
 document.getElementById('landSummary').innerHTML=[
  ['Найдено',found.length+' из '+results.length],
  ['Суммарная площадь',totalHa?landNum(totalHa,4)+' га':'—'],
  ['Кадастровая стоимость',totalValue?landNum(totalValue,1)+' млн ₽':'—'],
  ['Субъект РФ',regions.join(', ')||'—']
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 // Несколько участков — общий вид территории один на всех, карточки без своих
// мини-карт: иначе на 30 участков вышло бы 30 повторов той же подложки.
 const single=found.length<2;
 document.getElementById('landCards').innerHTML=results.length
  ?landTerritorySvg(found)+results.map(x=>landCardHtml(x,single)).join('')
  :'<div style="padding:10px;color:#777">Ничего не найдено.</div>';
 document.getElementById('landWarnings').innerHTML=(data.warnings||[]).map(x=>'• '+escapeHtml(x)).join('<br>');
 document.getElementById('landPreview').style.display='block';
}

function useLandForTep(){
 const status=document.getElementById('cadastralStatus');
 const numbers=((landLookup&&landLookup.results)||[])
  .filter(x=>x.found&&x.kind==='land'&&x.cadastral_number)
  .map(x=>x.cadastral_number);
 if(!numbers.length){status.innerHTML='<span class="import-error">Нет найденных земельных участков для переноса.</span>';return}
 writeCadastralField(numbers.join(', '));
 const field=document.getElementById('cadastralNumbers');
 if(field)field.scrollIntoView({behavior:'smooth',block:'center'});
 status.innerHTML='<span class="import-ok">Номера участков ('+numbers.length+') перенесены в поле выше.</span> Нажмите «Получить ТЭП», чтобы посчитать ТЭП по нормам.';
}

function renderStoredLand(){
 const stored=inputs._land_lookup;
 if(!stored)return;
 landLookup=cloneValue(stored);
 writeCadastralField(stored.query||'');
 renderLandLookup(landLookup);
 loadLandScreening(stored.query||'');
 const status=document.getElementById('cadastralStatus');
 if(status)status.innerHTML='<span class="import-ok">Показаны сведения об участке, сохранённые в проекте.</span>';
}

"""
