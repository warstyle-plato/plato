"""Кусок страницы PAGE: Скрипт: расчёт МО, загрузка выгрузки ГлавАПУ, пресеты сервера,
отправка результата в Telegram.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_mo_glavapu")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""let moResult=null,moLastQuery='';

// Подпись-приглашение из разметки: к ней возвращается строка ГлавАПУ, когда
// карточка снимается с экрана (расчёт МО, сброс проекта).
const GLAVAPU_STATUS_DEFAULT=document.getElementById('glavapuStatus').textContent;

// Смена территории снимает карточку другой методики. Расчёт МО оставлял на
// экране карточку ГлавАПУ прошлого запроса: под свежим итогом Подмосковья
// висел чужой московский участок, а его «Применить к Вводным и ТЭП» унёс бы
// в модель старый ТЭП. В обратную сторону — то же с блоком МО. Данные
// чистятся вместе с карточкой: карточка без кнопки безопасна, только когда
// ей нечего применять.
function dropGlavapuPreview(){
 glavapuImport=null;
 const preview=document.getElementById('glavapuPreview');if(preview)preview.style.display='none';
 const cadPreview=document.getElementById('cadastralPreview');if(cadPreview)cadPreview.style.display='none';
 const status=document.getElementById('glavapuStatus');if(status)status.textContent=GLAVAPU_STATUS_DEFAULT;
}
function dropMoPreview(){
 moResult=null;
 const preview=document.getElementById('moPreview');if(preview)preview.style.display='none';
 const status=document.getElementById('moStatus');if(status)status.style.display='none';
}

let moDistrictPrices={},moKdDocument='';

async function loadMoReference(){
 try{
  const response=await fetch('/mo/reference');
  const data=await response.json();
  if(!response.ok)return;
  const select=document.getElementById('moDistrict');
  if(!select)return;
  const current=select.value;
  select.innerHTML='<option value="">определить по участку</option>'+
   (data.districts||[]).map(d=>`<option value="${escapeHtml(d.name)}">${escapeHtml(d.name)}</option>`).join('');
  select.value=current||(inputs._mo_calc&&inputs._mo_calc.territory&&inputs._mo_calc.territory.district)||'';
  moDistrictPrices={};
  (data.districts||[]).forEach(d=>{moDistrictPrices[d.name]={
    price:d.market_price_rub_per_sqm,basis:d.market_price_basis,
    kd:d.vri_kd,kdBasis:d.vri_kd_basis}});
  moKdDocument=(data.vri_kd||{}).document||'';
  select.onchange=()=>{syncMoPrice();syncMoKd();recalcMo()};
  syncMoPrice();syncMoKd();bindMoParams();
  renderMoPriceState(data.market_price||{},data.vri_kd||{});
 }catch(e){}
}

// Кср не вводят руками: он определяется округом по распоряжению 114-Р.
// Поле только показывает подставленное, а ручной ввод — осознанное исключение.
function syncMoPrice(){
 const field=document.getElementById('moPrice');
 const unit=document.getElementById('moPriceUnit');
 const manual=document.getElementById('moPriceManual');
 if(!field||(manual&&manual.checked))return;
 const district=(document.getElementById('moDistrict')||{}).value||'';
 const found=moDistrictPrices[district];
 if(found&&found.price){
  field.value=Math.round(found.price);
  if(unit)unit.textContent=found.basis==='округ'
   ? '₽/м² · по округу, распоряжение 114-Р'
   : '₽/м² · среднее по области: округа нет в распоряжении';
 }else{
  field.value='';
  if(unit)unit.textContent='₽/м² · определится по округу участка';
 }
}

// Параметры меняют результат, а не только подпись: правка любого из них
// пересчитывает уже готовый расчёт по тому же участку. Заново запрашивать
// ЕГРН и маршрутизировать территорию не нужно — запрос запомнен.
let moRecalcTimer=null;
function recalcMo(){
 if(!moResult)return;
 clearTimeout(moRecalcTimer);
 moRecalcTimer=setTimeout(()=>calculateMo(moLastQuery),150);
}

function bindMoParams(){
 // Пустое поле «средняя квартира» — не ноль, а «берём РНГП области»: значение
 // и его основание приходят из движка, копии числа на странице нет.
 const flat=document.getElementById('moFlat');
 if(flat&&!Number(flat.value||0)){
  flat.value=AVERAGE_FLAT.mo.sqm;
  const note=document.getElementById('moFlatBasis');
  if(note)note.textContent=AVERAGE_FLAT.mo.basis;
 }
 ['moDensity','moArea','moFlat','moPrice','moKd'].forEach(id=>{
  const el=document.getElementById(id);
  if(el&&!el._moBound){el._moBound=true;el.addEventListener('change',recalcMo)}
 });
 // Площадь и плотность — те же поля модели, что в блоке «Участок и плотность»
 // на вкладке ТЭП: ввод в любом из двух окон обновляет оба. Иначе одна
 // величина жила бы в двух местах порознь и конфликтовала сама с собой.
 const density=document.getElementById('moDensity');
 if(density&&!density._siteBound){density._siteBound=true;
  density.addEventListener('change',()=>setSiteDensity(density.value))}
 const area=document.getElementById('moArea');
 if(area&&!area._siteBound){area._siteBound=true;
  area.addEventListener('change',()=>{if(Number(area.value)>0)setSiteArea(area.value)})}
}

// Кд задан таблицей 3 постановления № 1745: три группы округов, 10 / 5 / 1 %.
function syncMoKd(){
 const field=document.getElementById('moKd');
 const unit=document.getElementById('moKdUnit');
 const manual=document.getElementById('moKdManual');
 if(!field||(manual&&manual.checked))return;
 const district=(document.getElementById('moDistrict')||{}).value||'';
 const found=moDistrictPrices[district];
 if(found&&found.kd!=null){
  field.value=found.kd;
  if(unit)unit.textContent='доля · '+(Math.round(found.kd*1000)/10)+'% по таблице 3 постановления № 1745';
 }else if(district){
  field.value='';
  if(unit)unit.textContent='доля · округа нет в таблице 3, задайте вручную';
 }else{
  field.value='';
  if(unit)unit.textContent='доля · определится по округу участка';
 }
}

function toggleMoKd(){
 const field=document.getElementById('moKd');
 const manual=document.getElementById('moKdManual');
 const unit=document.getElementById('moKdUnit');
 if(!field||!manual)return;
 field.readOnly=!manual.checked;
 if(manual.checked){
  if(unit)unit.textContent='доля · задано вручную, справочник не применяется';
  field.focus();
 }else{
  syncMoKd();
  recalcMo();
 }
}

function toggleMoPrice(){
 const field=document.getElementById('moPrice');
 const manual=document.getElementById('moPriceManual');
 const unit=document.getElementById('moPriceUnit');
 if(!field||!manual)return;
 field.readOnly=!manual.checked;
 if(manual.checked){
  if(unit)unit.textContent='₽/м² · задано вручную, справочник не применяется';
  field.focus();
 }else{
  syncMoPrice();
  recalcMo();
 }
}

function renderMoPriceState(state,kdState){
 const node=document.getElementById('moPriceState');
 if(!node)return;
 const count=Number(state.count||0);
 node.innerHTML=count
  ?'<b>Справочник Кср: '+count+' муниципальных образований</b>'+(state.period?' · '+escapeHtml(state.period):'')+
   (state.region_average?' · среднее по области '+landNum(state.region_average,0)+' ₽/м²':'')+
   (state.document?'<br><span style="color:#888">'+escapeHtml(state.document)+'</span>':'')+
   '<br>Кср и УПКС подставляются по округу автоматически, загружать ничего не нужно.'
  :'Справочник Кср недоступен — Кср берётся из поля выше или из УПКС округа.';
 const kd=Number((kdState||{}).count||0);
 if(kd){
  node.innerHTML+='<br><br><b>Коэффициент доходности Кд: '+kd+' муниципальных образований</b>'+
   ((kdState||{}).document?'<br><span style="color:#888">'+escapeHtml(kdState.document)+'</span>':'');
 }
}

async function calculateMo(queryText){
 const button=document.getElementById('cadastralAnalyzeButton');
 const status=document.getElementById('cadastralStatus');
 const moStatus=document.getElementById('moStatus');
 const query=String(queryText!=null?queryText:(document.getElementById('cadastralNumbers').value||'')).trim();
 const area=Number(document.getElementById('moArea').value||0);
 if(!query&&!(area>0)){
  status.innerHTML='<span class="import-error">Введите кадастровый номер, адрес или площадь участка в гектарах.</span>';return;
 }
 button.disabled=true;button.textContent='Считаю…';
 dropGlavapuPreview();
 status.textContent='Участок в Московской области · считаю нормативы РНГП МО, УПКС и плату за ВРИ…';
 try{
  const response=await fetch('/mo/calculate',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({
    query,
    limit:30,
    site_area_ha:area||0,
    density_sqm_per_ha:Number(document.getElementById('moDensity').value||0)||30000,
    district:document.getElementById('moDistrict').value||'',
    market_price_rub_per_sqm:(document.getElementById('moPriceManual')||{}).checked
     ? Number(document.getElementById('moPrice').value||0)||0 : 0,
    vri_kd:(document.getElementById('moKdManual')||{}).checked
     ? Number(document.getElementById('moKd').value||0)||0 : 0,
    average_flat_sqm:Number(document.getElementById('moFlat').value||0)||AVERAGE_FLAT.mo.sqm
   })
  });
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Не удалось рассчитать проект');
  moResult=data;
  moLastQuery=query;
  renderMo(data);
  drawLandPreviewQuiet(query);
  syncMoParams(data);
  if(moStatus)moStatus.style.display='none';
  const parcels=((data.vri||{}).parcels||[]).length;
  const asked=cadastralNumbersIn(query).length;
  const parcelNote=asked?' · участков в расчёте: '+parcels+' из '+asked:(parcels?' · участков: '+parcels:'');
  status.innerHTML='<span class="import-ok">Московская область · расчёт готов: '+landNum(data.territory.site_area_ha,4)+' га, '+
   landNum(data.social.apartments_sqm,0)+' м² квартир'+parcelNote+'.</span> Проверьте значения и примените к модели.';
  // Если расчёт МО уже применён к проекту, правка плотности или Кд обязана
  // доехать до модели сама: иначе блок показывает новые числа, модель считает
  // по старым, и в Telegram уходит расчёт, которого пользователь не видел.
  if(inputs._mo_calc)await applyMo({silent:true});
 }catch(e){
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
 }finally{
  button.disabled=false;button.textContent='Получить ТЭП';
 }
}

// Что подставил сервер — видно в полях: пользователь правит поверх справочного.
function syncMoParams(data){
 const t=data.territory||{},v=data.vri||{};
 const density=document.getElementById('moDensity');
 if(density&&data.density_sqm_per_ha)density.value=data.density_sqm_per_ha;
 const district=document.getElementById('moDistrict');
 if(district&&t.district){district.value=t.district;syncMoPrice();syncMoKd();}
 const price=document.getElementById('moPrice');
 const manual=document.getElementById('moPriceManual');
 if(price&&v.market_price_rub_per_sqm&&!(manual&&manual.checked))price.value=Math.round(v.market_price_rub_per_sqm);
 const kd=document.getElementById('moKd');
 const kdManual=document.getElementById('moKdManual');
 if(kd&&v.kd!=null&&!(kdManual&&kdManual.checked))kd.value=v.kd;
 const area=document.getElementById('moArea');
 if(area&&t.site_area_ha)area.placeholder=landNum(t.site_area_ha,4)+' га из ЕГРН';
}

// Дефицит рабочих мест — это будущий объект, а не строка справки. РНГП МО
// требует 0,5 рабочего места на жителя; соцобъекты, нормативная торговля,
// общепит и быт часть закрывают, остаток закрывать девелоперу — офисом или
// дополнительной торговлей. Раньше на экране стояли «офисы под рабочие места
// N м²» без слова «нужно», и это читалось как справка (замечание владельца,
// 19.08.2026).
function jobsGapText(jobs){
 const gap=Number((jobs||{}).deficit||0);
 if(gap<=0)return 'дефицита нет: нормативные объекты закрывают потребность';
 const office=Number(jobs.office_sqm||0),retail=Number(jobs.retail_sqm||0);
 return 'офисы ≈ '+landNum(office,0)+' м² ГНС или торговля ≈ '+landNum(retail,0)+
  ' м² — или их сочетание на '+landNum(gap,0)+' мест';
}

function moTable(title,rows){
 return `<div class="mo-table"><h4>${escapeHtml(title)}</h4><table><tbody>${
  rows.map(r=>`<tr><td>${escapeHtml(r[0])}</td><td>${escapeHtml(r[1])}</td></tr>`).join('')
 }</tbody></table></div>`;
}

function renderMo(data){
 const s=data.social||{},v=data.vri||{},t=data.territory||{},b=data.balance||{};
 document.getElementById('moSummary').innerHTML=[
  ['Площадь участка',landNum(t.site_area_ha,4)+' га'],
  ['Площадь квартир',landNum(s.apartments_sqm,0)+' м²'],
  ['Население',landNum(s.population,0)+' чел.'],
  ['Смена ВРИ',v.payment_used_mln!=null?landNum(v.payment_used_mln,1)+' млн ₽':'—']
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 const tables=[];
 tables.push(moTable('Территория',[
  ['Кадастровые номера',(t.cadastral_numbers||[]).join(', ')||'—'],
  ['Городской округ',(t.district||'—')+(t.district_source?' · '+t.district_source:'')],
  ['Кадастровый квартал',t.quarter||'—'],
  ['Адрес по ЕГРН',t.address||'—'],
  ['Плотность',landNum(data.density_sqm_per_ha,0)+' м² квартир на 1 га']
 ]));
 tables.push(moTable('Социальная нагрузка по РНГП МО',[
  ['ДОО',landNum(s.kindergarten.places,0)+' мест · участок '+landNum(s.kindergarten.site_ha,4)+' га · '+landNum(s.kindergarten.gba_sqm,0)+' м²'],
  ['СОШ',landNum(s.school.places,0)+' мест · участок '+landNum(s.school.site_ha,4)+' га · '+landNum(s.school.gba_sqm,0)+' м²'],
  ['Поликлиника',landNum(s.clinic.capacity,0)+' пос./смену · '+landNum(s.clinic.gba_sqm,0)+' м²'],
  ['Паркинг постоянного хранения',landNum(s.parking.permanent_spaces,0)+' м/м · подземный '+landNum(s.parking.underground_sqm,0)+' м²'],
  ['Паркинг временного хранения',landNum(s.parking.temporary_spaces,0)+' м/м'
    +' <span style="color:#777">— не менее 30 м/м на 1000 жителей; в проекте не строим:'
    +' норматив разрешает разместить их в границах жилого района</span>'],
  ['Озеленение',landNum(s.green.quarter_sqm,0)+' м² · общего пользования '+landNum(s.green.public_sqm,0)+' м²'],
  ['Нежилые помещения общественные',landNum(s.public_premises_sqm,0)+' м²'],
  ['Рабочие места',landNum(s.jobs.required,0)+' требуется · '+landNum(s.jobs.from_objects,0)+
    ' дают нормативные объекты · дефицит '+landNum(s.jobs.deficit,0)],
  ['Чем закрыть дефицит',jobsGapText(s.jobs)],
  ['Компенсация в бюджет','стационар '+landNum(s.budget_compensation.hospital_beds,1)+' коек · скорая '+landNum(s.budget_compensation.ambulance_cars,2)+' маш. · депо '+landNum(s.budget_compensation.fire_cars,2)+' маш.'],
  ['СПП ГНС',landNum(s.gns_sqm,0)+' м²']
 ]));
 const upksSource=(data.upks||{}).source||{};
 const landSource=upksSource.land||{},oksSource=upksSource.oks||{};
 tables.push(moTable('Смена ВРИ',[
  ['УПКС земли под жильё',(v.upks_target!=null?landNum(v.upks_target,2)+' ₽/м²':'—')+
    (landSource.valuation_date?' · оценка на '+landSource.valuation_date:'')],
  ['УПКС ОКС МКД округа',(v.upks_average_oks!=null?landNum(v.upks_average_oks,2)+' ₽/м²':'—')+
    (oksSource.valuation_date?' · оценка на '+oksSource.valuation_date:'')],
  ['Кадастровая стоимость сейчас',landNum(v.cadastral_value_current_rub/1e6,1)+' млн ₽'],
  ['Кадастровая стоимость целевая',landNum(v.cadastral_value_target_rub/1e6,1)+' млн ₽'],
  ['Разница ∆КС',landNum(v.delta_rub/1e6,1)+' млн ₽'],
  ['Кср / Кд',(v.market_price_rub_per_sqm!=null?landNum(v.market_price_rub_per_sqm,0)+' ₽/м²':'—')+' · '+landNum(v.kd,2)+
    (v.market_price_source?' · '+v.market_price_source:'')+(v.market_price_period?' · '+v.market_price_period:'')],
  ['К1 / К',(v.k1!=null?landNum(v.k1,4):'—')+' · '+(v.k!=null?landNum(v.k,4):'—')],
  ['Плата за смену ВРИ',(v.payment_used_mln!=null?landNum(v.payment_used_mln,1)+' млн ₽':'—')+' · '+(v.payment_basis||'')]
 ]));
 if((v.parcels||[]).length){
  tables.push(moTable('Кадастровая стоимость участков (ЕГРН)',
   v.parcels.map(p=>[p.cadastral_number+(p.cadastral_value_date?' · оценка от '+landDate(p.cadastral_value_date):''),
    landNum(p.cadastral_value_rub/1e6,2)+' млн ₽ · '+landNum(p.upks_current,0)+' ₽/м² → '+landNum(p.upks_target,0)+' ₽/м²'])));
 }
 tables.push(moTable('Баланс территории (упрощённый)',
  (b.items||[]).map(i=>[i.label,landNum(i.area_ha,4)+' га'])
   .concat([['Занято нормативами',landNum(b.used_ha,4)+' га'],['Остаток под жильё, УДС и прочее',landNum(b.remaining_ha,4)+' га']])
 ));
 document.getElementById('moTables').innerHTML='<div class="mo-tables">'+tables.join('')+'</div>';
 document.getElementById('moWarnings').innerHTML=(data.warnings||[]).map(x=>'• '+escapeHtml(x)).join('<br>');
 document.getElementById('moPreview').style.display='block';
}

async function applyMo(options){
 const silent=!!(options&&options.silent);
 const status=document.getElementById('moStatus');
 if(!moResult){if(!silent)status.innerHTML='<span class="import-error">Сначала выполните расчёт.</span>';return}
 const incoming=moResult;
 resetTerritoryData({keepPhasing:silent});
 moResult=incoming;
 Object.assign(inputs,moResult.inputs||{});
 // Площадь участка приходит в территории расчёта, а не во вводных.
 {
  const moArea=Number(((moResult.territory)||{}).site_area_ha||0);
  if(moArea>0)inputs.site_area_ha=moArea;
  const moDensity=Number(moResult.density_sqm_per_ha||0);
  if(moDensity>0&&!inputs._site_density_user_set)inputs.site_density_sqm_per_ha=moDensity;
 }
 inputs._mo_calc={
  query:moResult.query||'',
  territory:moResult.territory||{},
  density_sqm_per_ha:moResult.density_sqm_per_ha,
  vri:moResult.vri||{},
  social:moResult.social||{},
  balance:moResult.balance||{},
  warnings:moResult.warnings||[]
 };
 Object.entries(moResult.tep||{}).forEach(([key,values])=>{
  if(tep[key])Object.assign(tep[key],values);
 });
 // Другой участок — другой паркинг: то же правило, что у импорта ГлавАПУ.
 // Без него пара «места ↔ площадь» прежнего участка (с пометкой «руками»)
 // перебивала норму нового на первом же пересчёте: в Мытищах расчёт МО
 // дал 2 289 м/м и 80 115 м², а в проекте остались 150 и 5 215 (владелец,
 // 04.10.2026). Тихое обновление параметров того же участка пару не трогает:
 // там вписанное человеком остаётся его решением — пока ТЭП тот же; привезло
 // ли обновление другой ТЭП, решает `fillUndergroundFromTep` по норме.
 if(!silent){
  inputs.underground_manual_spaces=0;
  inputs.underground_manual_gns_sqm=0;
  markParkingByNorm(PROJECT_PARKING_KEY);
 }
 syncTep(false);
 // Очерёдность сбрасываем только при явном применении: при автоматическом
 // обновлении параметров она уже настроена пользователем, и терять её нельзя.
 if(!silent)phasing=makeDefaultPhasing(1);
 renderInputs();renderTep();renderPhasing();
 if(status){
  status.style.display='';
  status.innerHTML=silent
   ? '<span class="import-ok">Параметры Подмосковья обновлены и применены к модели.</span>'
   : '<span class="import-ok">ТЭП, социальные мощности и стоимость смены ВРИ применены к модели.</span> Проверьте цены и себестоимость на вкладке «Вводные».';
 }
 await calculate();
}

function renderStoredMo(){
 const stored=inputs._mo_calc;
 if(!stored)return;
 const query=document.getElementById('moQuery');
 if(query)query.value=stored.query||'';
 const density=document.getElementById('moDensity');
 if(density&&stored.density_sqm_per_ha)density.value=stored.density_sqm_per_ha;
 const status=document.getElementById('moStatus');
 if(status)status.innerHTML='<span class="import-ok">В проекте сохранён расчёт по Подмосковью: '+
  escapeHtml((stored.territory&&stored.territory.district)||'округ не определён')+'.</span> Нажмите «Рассчитать», чтобы обновить.';
}

// Участок проекта — один владелец ответа для блоков, которым нужны кадастр,
// район и ТТК (льгота МПТ, льготы ВРИ). Читают его, а не соседние поля.
// Нет кадастрового анализа — null: ТЭП собран без адреса. Чего анализ не
// сказал — в missing с источником, а не молчаливое «вне ТТК».
function projectParcelFacts(){
 const a=(inputs&&inputs._cadastral_analysis)||cadastralAnalysis||null;
 if(!a||!a.territory)return null;
 const t=a.territory||{};
 const numbers=((a.recognized&&a.recognized.length)?a.recognized:(a.requested||[])).map(String);
 const district=String(t.district||'').trim();
 const ttk=t.inside_ttc===true?'inside':(t.inside_ttc_known===true?'outside':'');
 const missing=[];
 if(!district)missing.push('район: кадастровый анализ (ГлавАПУ) его не вернул');
 if(!ttk)missing.push('положение относительно ТТК: в сохранённом анализе нет признака ГлавАПУ — повторите кадастровый анализ');
 return {cadastral:numbers[0]||'',numbers,quarter:String(t.cadastral_quarter||''),district,ttk,
  inside_moscow:t.inside_moscow,missing,source:'кадастровый анализ проекта'};
}

function renderStoredCadastral(){
 const stored=inputs._cadastral_analysis;
 if(!stored)return;
 cadastralAnalysis=cloneValue(stored);
 writeCadastralField((stored.requested||[]).join(', '));
 renderCadastralPreview(cadastralAnalysis);
 cadastralStatus.innerHTML='<span class="import-ok">Показана территория, сохранённая в проекте.</span>';
}

// Готовые примеры — витрина владельца: в них настоящие проекты с ценами и
// сроками, и посторонним их не показывают (решение владельца, 18.08.2026).
// Сервер отказывает не своему, страница на отказ убирает блок целиком, а не
// оставляет пустой список без объяснения.
function presetsQuery(){
 return '?session='+encodeURIComponent(activeSession())+
        '&key='+encodeURIComponent(projectsAdminKey||'');
}

function hidePresetsBlock(){
 const box=document.getElementById('projectsExamples');
 if(box)box.style.display='none';
}

async function loadPresetCatalog(){
 try{
   const response=await fetch('/presets'+presetsQuery());
   const data=await response.json();
   if(response.status===403){hidePresetsBlock();return}
   if(!response.ok)throw new Error(data.detail||'Не удалось получить предустановки');
   const select=document.getElementById('serverPresetSelect');
   if(!select)return;
   select.innerHTML='<option value="">Предустановка ТЭП…</option>'+
     (data.presets||[]).filter(p=>p.available).map(p=>
       `<option value="${p.id}" data-download="${p.download_url}" title="${p.description||''}">${p.name}</option>`
     ).join('');
   select.onchange=()=>{
     const opt=select.options[select.selectedIndex];
     const link=document.getElementById('serverPresetDownload');
     if(select.value){
       link.href=(opt.dataset.download||'#')+presetsQuery();
       link.style.display='inline-flex';
     }else{
       link.style.display='none';
     }
   };
 }catch(e){
   console.warn('Preset catalog:',e);
 }
}

async function loadServerPreset(){
 const select=document.getElementById('serverPresetSelect');
 const id=select&&select.value;
 // Отказ печатался во «Вводных», а список теперь в личном кабинете:
 // сообщение уходило на страницу, которой человек не видит.
 if(!id){alert('Выберите предустановку из списка.');return}
 // Ход разбора и результат печатаются во «Вводных» — окно закрываем и
 // показываем ту вкладку, где всё это появится.
 closeProjects();openTab('inputs');
 const label=select.options[select.selectedIndex].textContent;
 glavapuStatus.textContent='Загружаю предустановку «'+label+'» с сервера…';
 glavapuPreview.style.display='none';
 try{
   const response=await fetch('/presets/'+encodeURIComponent(id)+presetsQuery());
   const payload=await response.json();
   if(!response.ok)throw new Error(payload.detail||'Ошибка загрузки предустановки');
   glavapuImport=payload;
   renderGlavapuPreview(payload);
   // Предустановка — готовый проект, проверять перед применением нечего.
   // Двухшаговый сценарий заканчивался «загрузил, а в расчёте пусто»:
   // второй клик пропускали, и вводные оставались прежними.
   await applyGlavapu();
 }catch(e){
   glavapuStatus.innerHTML='<span class="import-error">'+String(e.message||e)+'</span>';
 }
}

async function uploadGlavapu(){
 const file=document.getElementById('glavapuFile').files[0];
 if(!file){glavapuStatus.innerHTML='<span class="import-error">Выберите Excel-файл.</span>';return}
 if(!file.name.toLowerCase().endsWith('.xlsx')){glavapuStatus.innerHTML='<span class="import-error">Нужен файл .xlsx: шаблон ТЭП DevelopAid или выгрузка калькулятора ГлавАПУ.</span>';return}
 glavapuStatus.textContent='Разбираю '+file.name+'…';
 glavapuPreview.style.display='none';
 const bytes=await file.arrayBuffer();
 // Свой шаблон пробуем первым. Прежде страница знала один формат — файл
 // ГлавАПУ — и заполненный шаблон DevelopAid уходил туда же: разбор не
 // отказывался, не находил ни одного своего показателя и возвращал пустоту.
 // Человек видел «Файл распознан» и таблицу прочерков. Бот этот шаблон
 // принимает, и помощь обещает, что его можно прислать, — на сайте обещание
 // не работало.
 // Отказ по нашему шаблону несёт причину: пустой файл — это «заполните
 // жёлтые ячейки», а не «формат не распознан». Прежде любая неудача уводила
 // в разбор ГлавАПУ, и владелец, загрузив наш же пустой шаблон, читал, что
 // файл не наш.
 let templateError='';
 try{
   const manual=await fetch('/import/manual-tep?filename='+encodeURIComponent(file.name),{
     method:'POST',
     headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
     body:bytes.slice(0)
   });
   if(manual.ok){
     const parsed=await manual.json();
     if(parsed&&parsed.tep){
       await applyTelegramManualTep(parsed,{silent:true});
       const name=String(parsed.project_name||'').trim();
       glavapuStatus.innerHTML='<span class="import-ok">Шаблон ТЭП DevelopAid применён.</span>'
         +(name?' Проект: <b>'+escapeHtml(name)+'</b>.':'')
         +' Площади и продукты перенесены во вкладку ТЭП.';
       calculate();
       return;
     }
   }else if(manual.headers.get('X-DevelopAid-Template')==='yes'){
     const payload=await manual.json().catch(()=>({}));
     templateError=String(payload.detail||'').trim()||'Шаблон ТЭП DevelopAid заполнен не полностью.';
   }
 }catch(e){/* не наш шаблон — пробуем формат ГлавАПУ */}
 if(templateError){
   glavapuStatus.innerHTML='<span class="import-error">Это шаблон ТЭП DevelopAid, но он не заполнен: '
     +escapeHtml(templateError)+' Заполните жёлтые ячейки и загрузите файл снова.</span>';
   return;
 }
 try{
   const response=await fetch('/import/glavapu?filename='+encodeURIComponent(file.name),{
     method:'POST',
     headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
     body:await file.arrayBuffer()
   });
   const payload=await response.json();
   if(!response.ok)throw new Error(payload.detail||'Ошибка импорта');
   // Пустой разбор — не успех. Ни одного числа значит «формат не наш», а не
   // «в файле нули»: сводка из прочерков читается как распознанный файл.
   const found=Object.values(payload.normalized||{}).filter(
     v=>typeof v==='number'&&isFinite(v)&&v!==0).length;
   if(!found)throw new Error('Формат файла не распознан: это ни шаблон ТЭП DevelopAid, '
     +'ни выгрузка калькулятора ГлавАПУ. <a href="/templates/tep" download>Скачайте шаблон</a> и заполните его.');
   glavapuImport=payload;
   renderGlavapuPreview(payload);
   glavapuStatus.innerHTML='<span class="import-ok">Файл распознан. Проверьте значения перед применением.</span>';
 }catch(e){
   glavapuStatus.innerHTML='<span class="import-error">'+String(e.message||e)+'</span>';
 }
}

function renderGlavapuPreview(data){
 if(!data)return;
 const n=data.normalized||{};
 const src=data.source||{};
 glavapuSummary.innerHTML=[
   ['Файл',src.filename||'—'],
   ['Площадь территории',(n.site_area_ha??'—')+(n.site_area_ha!=null?' га':'')],
   ['Площадь квартир',(n.apartment_area_sqm!=null?num(n.apartment_area_sqm)+' м²':'—')],
   ['Смена ВРИ',(n.change_vri_mln!=null?Number(n.change_vri_mln).toLocaleString('ru-RU',{maximumFractionDigits:3})+' млн ₽':'—')],
   ['Соцплатеж',(n.social_compensation_total_mln!=null?(Number(n.social_compensation_total_mln)>=1000?(Number(n.social_compensation_total_mln)/1000).toLocaleString('ru-RU',{minimumFractionDigits:3,maximumFractionDigits:3})+' млрд ₽ ('+Number(n.social_compensation_total_mln).toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽)':Number(n.social_compensation_total_mln).toLocaleString('ru-RU',{maximumFractionDigits:3})+' млн ₽'):'—')]
 ].map(x=>`<div><small>${x[0]}</small><b>${x[1]}</b></div>`).join('');
 glavapuRows.innerHTML=(data.recognized||[]).map(x=>`<tr>
   <td>${x.label}</td><td>${x.display}</td><td>${x.unit||''}</td><td>${x.target}</td>
 </tr>`).join('');
 // Предупреждение, которое видно всегда, не видно никогда: шесть абзацев
 // справки печатались на каждый импорт, и «продаваемая площадь не прочитана»
 // терялось между ними. Теперь блок появляется, только когда есть что сказать.
 const gw=(data.warnings||[]).filter(x=>String(x||'').trim());
 glavapuWarnings.innerHTML=gw.map(x=>'• '+x).join('<br>');
 glavapuWarnings.style.display=gw.length?'block':'none';
 const gn=(data.notes||[]).filter(x=>String(x||'').trim());
 const notesBox=document.getElementById('glavapuNotesBox');
 if(notesBox){
   document.getElementById('glavapuNotes').innerHTML=gn.map(x=>'• '+x).join('<br>');
   notesBox.style.display=gn.length?'block':'none';
 }
 glavapuPreview.style.display='block';
}


function applyServerPresetProjectConfig(presetId){
 if(!presetId)return '';

 if(presetId==='mytishchi'){
   // Full project preset: reset phasing so no stale settings survive from another project.
   // Округ решает Кср и Кд платы за ВРИ в нормативном пересчёте: без него
   // расчёт берёт среднее по области и плата занижается на четверть.
   inputs.mo_district='Городской округ Мытищи';
   inputs.technical_supervision_pct=5;
   inputs.offices_enabled=true;
   inputs.offices_gba_sqm=Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.office_gba_sqm)||26700);
   inputs.offices_saleable_sqm=Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.office_saleable_sqm)||21360);
   phasing=makeDefaultPhasing(3);
   phasing.enabled=true;
   phasing.user_enabled=false;
   phasing.source='preset_mytishchi';
   phasing.phase_count=3;
   phasing.phase_gap_months=12;
   phasing.cost_inflation_pct=8;
   phasing.sales_price_inflation_pct=8;
   phasing.products.apartments=[40,32,28];
   phasing.products.ground_commercial=[40,32,28];
   phasing.products.underground_parking=[40,32,28];
   phasing.products.storage=[40,32,28];

   // Working social program approved for the Mytishchi scenario.
   // Normative need remains separately stored in _glavapu_import.normalized.
   inputs.social_mode='Строительство';
   inputs._social_mode_user_set=true;
   inputs.kindergarten_places=465;
   inputs.school_places=675;
   inputs.clinic_capacity=0;

   inputs._preset_expert_overrides={
     preset_id:'mytishchi',
     note:'Экспертная корректировка относительно исходного ТЭП ГлавАПУ',
     normative_kindergarten_need:Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.required_kindergarten_places)||465),
     expert_kindergarten_places:465,
     expert_school_places:675,
     normative_school_need:Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.required_school_places)||975),
     office_gba_sqm:inputs.offices_gba_sqm,
     office_saleable_sqm:inputs.offices_saleable_sqm,
     mfc_parking_spaces:Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.mfc_parking_spaces)||434),
     phasing:'3 очереди 40/32/28',
     social_objects:[
       {name:'ДОО №1',type:'kindergarten',capacity:250,phase:1},
       {name:'СОШ №1',type:'school',capacity:675,phase:2},
       {name:'ДОО №2',type:'kindergarten',capacity:215,phase:3}
     ]
   };

   // Discrete social objects by queue. Dates are bound to each phase start.
   phasing.social_objects=[
     {id:'preset_myt_dou_1',name:'ДОО №1',type:'kindergarten',capacity:250,phase:1,start_date:phaseStartDate(1),start_mode:'auto'},
     {id:'preset_myt_school_1',name:'СОШ №1',type:'school',capacity:675,phase:2,start_date:phaseStartDate(2),start_mode:'auto'},
     {id:'preset_myt_dou_2',name:'ДОО №2',type:'kindergarten',capacity:215,phase:3,start_date:phaseStartDate(3),start_mode:'auto'}
   ];
   normalizeSocialObjectDates();

   // Expert capacity overrides the source quantity, while source area is preserved unless user edits it.
   syncTep(false);

   return 'Preset Мытищи: 3 очереди 40/32/28; МФК/офисы 26,7/21,36 тыс. м²; подземный паркинг 2 723 м/м; рабочая социалка О1 ДОО 250, О2 СОШ 675, О3 ДОО 215. Нормативная потребность СОШ 975 хранится отдельно.';
 }

 if(presetId==='mishina'){
   // A small project preset is intentionally single-phase.
   // Clear discrete products so Mytishchi/localStorage values cannot leak into Mishina.
   inputs.technical_supervision_pct=5;
   // Состав объектов — реестр: второй офисник, оставленный от прошлого
   // проекта, иначе протёк бы в пресет так же, как первый.
   STANDALONE_OBJECTS.filter(o=>!o.sale_gate).forEach(o=>{
    inputs[o.prefix+'_enabled']=false;
    if(o.measure==='spaces'){inputs[o.prefix+'_spaces']=0}
    else{inputs[o.prefix+'_gba_sqm']=0;inputs[o.prefix+'_saleable_sqm']=0}
   });
   phasing=makeDefaultPhasing(1);
   phasing.enabled=false;
   delete inputs._preset_expert_overrides;
   autoSocialObjects(false);
   normalizeSocialObjectDates();
   return 'Preset Мишина: одноочередный проект.';
 }

 return '';
}

async function sendTelegramResult(){
 const glavapuMeta=inputs._glavapu_import||null;
 const manualMeta=inputs._manual_tep_import||null;
 if(!telegramSession||telegramResultSent||!lastResult||(!glavapuMeta&&!manualMeta))return;
 const n=(glavapuMeta&&glavapuMeta.normalized)||{};
 const s=lastResult.summary||{};
 const f=(lastResult.report&&lastResult.report.financing)||{};
 const source=(glavapuMeta&&glavapuMeta.source)||(manualMeta&&manualMeta.source)||{};
 const cads=(cadastralAnalysis&&cadastralAnalysis.recognized)||source.cadastral_numbers||[];
 const manual=!!manualMeta;
  const edited=telegramMode==='edit';
 // Нежилой проект считает не всё присланное (`residential_excluded` движка):
 // квартиры, паркинг МКД, соцнагрузка и плата за ВРИ в расчёт не входят.
 // Сводка в чат берёт тогда посчитанное движком, а не вводные и не выгрузку,
 // иначе чат назвал бы места и деньги, которых в расчёте нет.
 const counted=withoutHousing();
 const countedRow=key=>((lastResult.tep&&lastResult.tep.rows)||[]).find(r=>r.key===key)||{};
 const countedTotal=(lastResult.tep&&lastResult.tep.total)||{};
  persistLocalSilently();
 const payload={
   cadastral_numbers:cads,
   project_name:manual?String(manualMeta.project_name||''):'',
   source_label:tepSourceLabel(manual),
    purchase_price_mln:Number(inputs.purchase_price_mln||0),
    land_buyout_mln:Number(inputs.land_buyout_mln||0),
    // Источник проекта важнее сохранённого значения: в inputs могла остаться
    // площадь прошлого расчёта, и она перебивала площадь текущего участка.
    site_area_ha:Number(n.site_area_ha||(manualMeta&&manualMeta.site_area_ha)||inputs.site_area_ha||0),
    apartment_area_sqm:counted?Number(countedRow('apartments').saleable||0)
     :(manual||edited)?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),
    change_vri_mln:counted?0:(manual||edited)?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),
    social_compensation_mln:counted?0:(manual||edited)?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),
    // Обеспеченность парковкой — ответ движка с подписью «N мест / M по норме = K×».
    parking_provision_label:parkingProvisionText(),
    parking_spaces:counted
     ? Number(countedRow('underground_parking').units||0)+Number(countedRow('above_parking').units||0)
       +Number(countedTotal.parking_units||0)
     :(manual||edited)
     ? Number((tep.underground_parking&&tep.underground_parking.units)||0)+Number((tep.above_parking&&tep.above_parking.units)||0)
     : Number(n.parking_permanent||0)+Number(n.parking_guest||0)+Number(n.mfc_parking_spaces||0),
   revenue_mln:Number(s.revenue||0)/1e6,
    total_expenses_mln:Number(s.total_expenses||0)/1e6,
   ebitda_mln:Number(s.ebitda||0)/1e6,
   net_profit_mln:Number(s.net_profit||0)/1e6,
   margin:Number(s.margin||0),
   irr_equity:s.irr_equity==null?null:Number(s.irr_equity),
   equity_returns_na:returnsNa(s),
   llcr:Number(s.llcr||0),
   calculated_bridge_mln:Number(f.calculated_bridge||0)/1e6,
   pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6,
   // Состав блоков решает движок (`report.layout`): нежилому проекту без ДДУ
   // бот не печатает БРИДЖ, ПФ и LLCR, а печатает деньги объекта.
   layout:(lastResult&&lastResult.report&&lastResult.report.layout)||null,
   rve_pf_shortfall_mln:Number(f.rve_pf_shortfall||0)/1e6,
   ending_pf_mln:Number(f.ending_pf||0)/1e6,
   // Непокрытая потребность в ПФ: одобренного лимита не хватило. Без неё
   // вердикт в чате говорил «целесообразна» проекту, которому банк денег
   // не дал, — тем же текстом, что и полностью профинансированному.
   pf_shortfall_mln:Number(f.pf_shortfall||0)/1e6,
   pf_shortfall_month:f.pf_shortfall_month||'',
   // Дефолт в дату раскрытия эскроу карточка бота не знала вовсе, и вердикт
   // в чате печатал прибыль голым числом там, где остаточные продажи долг
   // закрыли, а банк своего погашения в РВЭ не получил.
   default_date:f.default_date||null,
    report_payload:currentPdfReportPayload(cads)
 };
 try{
   telegramProgress('Готов. Отправляю в чат…');
   // Если ответ задерживается, надпись не должна выглядеть зависшей: в чате
   // к этому моменту уже может быть всё, и человек ждёт впустую.
   const slow=setTimeout(()=>telegramProgress('Ответ сервера задерживается — проверьте чат.'),20000);
   const response=await fetch('/telegram/result',{
     method:'POST',
     headers:{'Content-Type':'application/json'},
     body:JSON.stringify({session:telegramSession,summary:payload})
   }).finally(()=>clearTimeout(slow));
   const result=await response.json();
   if(!response.ok)throw new Error(result.detail||'Telegram не принял результат');
   telegramResultSent=true;
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML+=' <b>Итоговая карточка и PDF-отчёт отправлены в Telegram.</b>'
     +' Изменили вводные — нажмите «Обновить расчёт в Telegram» внизу.';
   if(window.Telegram&&window.Telegram.WebApp)window.Telegram.WebApp.ready();
   if(telegramMode==='edit'){
     // Режим правки: человек пришёл менять вводные, окно закрывать нельзя —
     // его закроет сама кнопка «Обновить расчёт в Telegram».
     showTelegramResendButton();
   }else{
     finishTelegramSession('Карточка в чате. PDF-отчёт и Excel-модель придут следом.');
   }
 }catch(e){
   telegramProgress('');
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML+=' <span class="import-error">Не удалось отправить итог в Telegram: '+escapeHtml(String(e.message||e))+'</span>';
 }
}

// Данные территории: всё, что относится к конкретному участку. При загрузке
// нового участка они обязаны обнулиться целиком. Иначе от прошлого проекта
// остаётся то, чего в новом нет вовсе, — так 833 кладовые чужого ТЭП дали
// миллиард выручки, а карточка показывала площадь и округ прежнего расчёта.
// Поля участка, обнулённые последним импортом: их называет плашка «Участок
// применён». Пустой список — нечего было обнулять.
let territoryCleared=[];
const TERRITORY_INPUT_KEYS=[
 // Цена сделки относится к участку, а не к предпосылкам аналитика: при вводе
 // нового кадастра она обязана обнуляться. Иначе второй расчёт подряд считался
 // по цене предыдущего проекта, и это не бросалось в глаза.
 'purchase_price_mln',
 'site_area_ha','site_density_sqm_per_ha','land_rights_cost_mln','social_compensation_mln',
 'kindergarten_places','school_places','clinic_capacity',
 'social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm',
 // Метры и места отдельно стоящих объектов — из реестра движка
 // (`TERRITORY_OBJECT_INPUT_KEYS`): второй офисник относится к участку так же,
 // как первый. Подставляется списком, а не выражением: этот же список читает
 // форма v2 (`territory_input_keys`).
 __DEVELOPAID_TERRITORY_OBJECT_KEYS__,
 // К1, К2 и расстояние до станции город считает ПО ЭТОМУ участку: К1 — от его
 // расстояния до рельсового каркаса, К2 — по его району из приложения 3 к
 // 945-ПП. Предпосылкой аналитика они не были никогда, а лежали в них, и
 // потому новая площадка наследовала коэффициенты прежнего района: выгрузка
 // ГлавАПУ пишет их только при значении больше нуля (см. `input_mapping`), то
 // есть не назвавшая их площадка оставалась с чужими.
 // Цена измерена на офиснике 100 000 м² ГНС (вводные и строка ТЭП об объекте
 // говорят одно и то же, иначе это не проект): К2 = 0,2 (внутри ТТК) против
 // незаданного — 319 мест вместо 1590, гараж 11 165 м² вместо 55 650, CAPEX
 // 59 393 против 63 997 млн ₽. Ноль здесь и есть «не задано»:
 // подпись поля обещает верхний край (1,0), и обнуление возвращает ровно его.
 //
 // «Площадь на 1 место» и «край норматива» ОСТАЮТСЯ предпосылками: это
 // методика, а не ответ города, — первая меряет наш гросс с рампами и
 // проездами, вторая выбирает край вилки РНГП Подмосковья. И обнулять их
 // нельзя буквально: ноль метров на место делит на ноль, а пустой режим
 // теряет выбор человека.
 'parking_k1','parking_k2','parking_rail_distance_m'
];
"""
