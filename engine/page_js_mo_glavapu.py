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
let moTerritoryEpoch=0;
let moCalculateRun=0;

// Подпись-приглашение из разметки: к ней возвращается строка ГлавАПУ, когда
// карточка снимается с экрана (расчёт МО, сброс проекта).
const GLAVAPU_STATUS_DEFAULT=document.getElementById('glavapuStatus').textContent;

// Смена территории снимает карточку другой методики. Расчёт МО оставлял на
// экране карточку ГлавАПУ прошлого запроса: под свежим итогом Подмосковья
// висел чужой московский участок, а его «Подставить в проект» унёс бы
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
   ? '₽/м². Цена по округу участка из распоряжения 114-Р'
   : '₽/м². Округа нет в распоряжении 114-Р, поэтому взято среднее по области';
 }else{
  field.value='';
  if(unit)unit.textContent='₽/м². Определится по округу участка';
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
  if(unit)unit.textContent='доля. Это '+String(Math.round(found.kd*1000)/10).replace('.',',')+'% по таблице 3 постановления № 1745-ПП';
 }else if(district){
  field.value='';
  if(unit)unit.textContent='доля. Округа нет в таблице 3 постановления № 1745-ПП, задайте коэффициент вручную';
 }else{
  field.value='';
  if(unit)unit.textContent='доля. Определится по округу участка';
 }
}

const MO_BENEFITS_CATALOG=__DEVELOPAID_MO_BENEFITS_CATALOG__;
let moVriBenefitsDraft=null;
function moVriBenefitMode(){
 const node=moVriNode('moVriBenefitMode');return node&&node.value==='calculated'?'calculated':'manual';
}
function moVriBenefitModeChanged(){
 moVriReliefEdited(false);renderMoVriBenefitEditor();
}
function moVriBenefitConfig(){return {schema:1,rows:JSON.parse(JSON.stringify(moVriBenefitsDraft||[])),separate_transfer_offset:!!moVriNode('moVriDistinctOffset')?.checked}}
function loadMoVriBenefitDraft(){
 const saved=inputs.mo_vri_benefits;
 moVriBenefitsDraft=saved&&saved.schema===1?JSON.parse(JSON.stringify(saved.rows||[])):[];
 const distinct=moVriNode('moVriDistinctOffset');if(distinct)distinct.checked=saved?.separate_transfer_offset===true;
 const mode=moVriNode('moVriBenefitMode');
 if(mode)mode.value=saved&&saved.schema===1?'calculated':Number(inputs.mo_vri_compensation_mln||0)>0?'manual':'calculated';
 renderMoVriBenefitEditor();
}
function addMoVriBenefitRow(){
 const kind=(moVriNode('moVriBenefitKind')||{}).value||'investment';
 if(!moVriBenefitsDraft)moVriBenefitsDraft=[];
 if(moVriBenefitsDraft.length>=100){moVriReliefStatus('Допускается не больше 100 обязательств.');return}
 moVriBenefitsDraft.push({id:'obligation-'+Date.now()+'-'+Math.random().toString(36).slice(2),kind,
  ...(kind==='investment'?{object_type:'hotel_3',index_mode:'base',municipality_uplift:false}:{}),
  ...(kind==='resettlement'?{district:inputs._mo_calc?.territory?.district||''}:{})});
 moVriReliefEdited(false);renderMoVriBenefitEditor();
}
function removeMoVriBenefitRow(index){
 moVriBenefitsDraft.splice(index,1);moVriReliefEdited(false);renderMoVriBenefitEditor();
}
function setMoVriBenefitField(index,key,value){
 const row=(moVriBenefitsDraft||[])[index];if(!row)return;
 if(key==='amount_mln'){row.amount_rub=value===''?null:Number(value)*1e6}
 else if(key==='municipality_uplift')row[key]=value===true;
 else row[key]=value===''?null:value;
 moVriReliefEdited(false);
 if(['object_type','index_mode','municipality_uplift'].includes(key))renderMoVriBenefitEditor();
}
function renderMoVriBenefitEditor(){
 const host=moVriNode('moVriBenefitRows');if(!host)return;
 const calculated=moVriBenefitMode()==='calculated';
 const editor=moVriNode('moVriBenefitsEditor');if(editor)editor.style.display=calculated?'':'none';
 const manual=moVriNode('moCompensation');if(manual){const field=manual.closest?manual.closest('.field'):null;if(field)field.style.display=calculated?'none':''}
 const esc=value=>escapeHtml(String(value??''));
 host.innerHTML=(moVriBenefitsDraft||[]).map((row,i)=>{
  const number=(key,label,placeholder='из проекта')=>'<div class="field"><label>'+esc(label)+'</label><input type="number" min="0" step="any" aria-label="'+esc(label)+'" value="'+esc(row[key])+'" placeholder="'+esc(placeholder)+'" oninput="setMoVriBenefitField('+i+',\''+key+'\',this.value)"></div>';
  const text=(key,label,placeholder='')=>'<div class="field"><label>'+esc(label)+'</label><input type="text" aria-label="'+esc(label)+'" value="'+esc(row[key])+'" placeholder="'+esc(placeholder)+'" oninput="setMoVriBenefitField('+i+',\''+key+'\',this.value)"></div>';
  let fields='',note='';
  if(['kindergarten','school'].includes(row.kind)){
   fields=number('required_places','Нормативная потребность, мест','автоматически по РНГП')+number('planned_places','Проектная мощность, мест')+number('rub_per_place','Стоимость засчитываемого места, ₽')+number('eligible_places','Засчитываемые места по соглашению','профицит после проверки >10%')+text('valuation_basis','Источник стоимости места','при ручной ставке — акт или соглашение');
   note='Проверяется строгое превышение потребности более чем на 10%. Предварительно оценивается разница проектной и нормативной мощности. Ставка из бюджета проекта — оценка; согласованную зачётную мощность можно указать отдельно.';
  }else if(row.kind==='resettlement'){
   fields=number('area_sqm','Расселяемая аварийная площадь, м²','укажите площадь')+text('district','Муниципалитет переселения','например, Мытищи')+number('rub_per_sqm','Стоимость метра, ₽/м²','КЦТ по муниципалитету')+text('valuation_basis','Источник ручной стоимости');
   note='Укажите аварийную площадь по обязательствам переселения. Цена КЦТ берётся по муниципалитету переселения. Со = Об × Цм — предварительная оценка по положению КРТ; стоимость для Ксу* подтверждается ДоКРТ.';
  }else if(row.kind==='victims'){
   const value=row.amount_rub==null?'':row.amount_rub/1e6;
   fields='<div class="field"><label>Сумма возмещения, млн ₽</label><input aria-label="Сумма возмещения, млн ₽" type="number" min="0" step="any" value="'+esc(value)+'" oninput="setMoVriBenefitField('+i+',\'amount_mln\',this.value)"></div>';
   note='Возмещение специальной категории пострадавших граждан по п. 5.1(1) 1310-ПП, предусмотренное ДоКРТ и соглашениями с муниципалитетом.';
  }else{
   const types=MO_BENEFITS_CATALOG.investment_types,rate=types.find(t=>t.key===row.object_type);
   fields='<div class="field"><label>Инвестиционный объект</label><select aria-label="Инвестиционный объект" onchange="setMoVriBenefitField('+i+',\'object_type\',this.value)">'+types.map(t=>'<option value="'+esc(t.key)+'"'+(row.object_type===t.key?' selected':'')+'>'+esc(t.label)+'</option>').join('')+'</select></div>';
   fields+=number('area_sqm','Общая площадь инвестиционного объекта, м²','укажите площадь');
   fields+='<div class="field"><label>Норматив 933-ПП, ₽/м² без НДС</label><output>'+esc(rate?rate.rub_per_sqm.toLocaleString('ru-RU'):'выберите объект')+'</output></div>';
   fields+='<div class="field"><label>Уровень цен</label><select aria-label="Уровень цен" onchange="setMoVriBenefitField('+i+',\'index_mode\',this.value)"><option value="base"'+(row.index_mode!=='indexed'?' selected':'')+'>На 07.08.2026 — без индексации</option><option value="indexed"'+(row.index_mode==='indexed'?' selected':'')+'>С накопленным индексом Ки</option></select></div>';
   if(row.index_mode==='indexed')fields+=number('price_index','Накопленный индекс Ки, коэффициент','например, 1.025')+text('index_basis','Период и источник индексов Росстата','с сентября 2026 до месяца перед заявлением');
   fields+='<div class="field"><label><input type="checkbox" '+(row.municipality_uplift?'checked':'')+' onchange="setMoVriBenefitField('+i+',\'municipality_uplift\',this.checked)"> Коэффициент муниципалитета 1,2 по 151/2004-ОЗ</label></div>';
   if(row.municipality_uplift)fields+=text('uplift_basis','Основание коэффициента 1,2','муниципалитет и пункт перечня');
   note='Стоимость = площадь × норматив × Ки × коэффициент муниципалитета. Ки — произведение месячных индексов Росстата, каждый процентный индекс делится на 100. Стоимость этих обязательств уменьшает ВРИ либо отдельный платёж КРТ; повторный зачёт недопустим.';
  }
  return '<div class="note" style="margin:12px 0"><div class="toolbar"><b>'+esc(MO_BENEFITS_CATALOG.grounds[row.kind]||row.kind)+'</b><button type="button" class="btn" onclick="removeMoVriBenefitRow('+i+')" aria-label="Удалить обязательство '+(i+1)+'">Удалить</button></div><div class="fields" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr))">'+fields+'</div><p class="hint">'+esc(note)+'</p></div>';
 }).join('');
}
function renderMoVriBenefitBreakdown(benefits){
 const host=moVriNode('moVriBenefitBreakdown');if(!host)return;
 if(!benefits){host.innerHTML='';return}
 host.innerHTML='<table class="metric-table"><thead><tr><th>Основание</th><th>Расчёт и источник</th><th>Оценка уменьшения</th></tr></thead><tbody>'+(benefits.rows||[]).map(r=>'<tr><td>'+escapeHtml(r.label)+'</td><td>'+(r.required_places!=null?escapeHtml('Потребность: '+r.required_places+' мест; проект: '+r.planned_places+'; профицит: '+r.surplus_places+'; зачёт: '+r.eligible_places+'; превышение: '+(r.required_places>0?((r.planned_places/r.required_places-1)*100).toFixed(2)+'%':'при нулевой потребности'))+'<br>':'')+escapeHtml(r.formula||r.error||'Недостаточно данных')+(r.unit_rate_rub!=null?'<br>Ставка: '+escapeHtml(moVriMoney(r.unit_rate_rub)):'')+'<br>'+escapeHtml(r.valuation_basis||r.source||'')+'<br><small>'+escapeHtml((r.notes||[]).join(' '))+'</small></td><td>'+escapeHtml(r.amount_rub==null?'нужны данные':moVriMoney(r.amount_rub))+'</td></tr>').join('')+'</tbody><tfoot><tr><th>Итого потенциальная льгота</th><td>'+(benefits.complete?'Предварительная оценка':'Расчёт не завершён; известная часть '+escapeHtml(moVriMoney(benefits.known_subtotal_rub)))+'</td><td><b>'+escapeHtml(benefits.total_rub==null?'не определена':moVriMoney(benefits.total_rub))+'</b></td></tr></tfoot></table>';
}

const MO_VRI_COMPENSATION_SOURCE=__DEVELOPAID_MO_VRI_COMPENSATION_SOURCE__;
let moVriReliefOwner=null;
let moVriReliefProjectKey='';
let moVriReliefModelKey='';
let moVriReliefPreview=null;
let moVriReliefRun=0;
let moVriReliefBaseSource=null;
let moVriReliefGrossEdited=false;
let moVriReliefCompEdited=false;
function moVriNode(id){return document.getElementById(id)}
function moVriDraftProjectKey(){return JSON.stringify([inputs._project_uid||'',moTerritoryEpoch])}
function moVriHasCompensationDraft(){
 return moVriReliefCompEdited&&moVriReliefOwner===inputs&&moVriReliefProjectKey===moVriDraftProjectKey();
}
function moVriNumber(value){
 if(value===null||value===undefined||String(value).trim()==='')return null;
 const result=Number(value);return Number.isFinite(result)?result:null;
}
function moVriMoney(rubles){
 return rubles==null?'не указана':Number(rubles).toLocaleString('ru-RU',{maximumFractionDigits:2})+' ₽';
}
function normalizeMoVriRegion(){
 // Mirror normalize_mo_vri_region: applied/proof proves a deduction; a number alone does not.
 if(classRegion()==='mo'||inputs._vri_relief_applied_at_project===true)return;
 const config=inputs.mo_vri_benefits,applied=config?.schema===1?config.applied:null;
 const record=inputs._mo_vri_relief,stored=inputs._mo_calc;
 const vri=(record!=null?(record?.schema===1?record.vri:null):stored?.vri)||{};
 const amount=value=>{const n=moVriNumber(value);return typeof value!=='boolean'&&n!==null&&n>=0?n:null};
 let gross=amount(vri.payment_before_compensation_rub),net=amount(vri.payment_used_mln);
 if((gross===null||net===null)&&applied){gross=amount(applied.gross_rub);net=amount(applied.net_mln)}
 const origins=inputs._field_origin||{},feeOrigin=origins['inputs.land_rights_cost_mln']||{};
 const current=amount(inputs.land_rights_cost_mln);
 if(gross!==null&&net!==null&&gross+.011>=net*1e6&&current!==null&&Math.abs(current-net)<1e-6&&feeOrigin.source!=='manual'){
  inputs.land_rights_cost_mln=gross/1e6;
  fieldOrigins()['inputs.land_rights_cost_mln']={source:'migrated',text:'Восстановлена исходная плата до уменьшения МО. Расчёт платы для текущего региона не выполнен.'};
  if(record?.source?.kind==='manual'){
   const field=moVriNode('moVriGross');if(field)field.value=String(gross/1e6);
   moVriReliefGrossEdited=true;moVriReliefBaseSource={kind:'manual',label:'Плата до уменьшения введена вручную'};
  }
 }else if(feeOrigin.source==='mo_vri_compensation')delete origins['inputs.land_rights_cost_mln'];
 const compOrigin=origins['inputs.mo_vri_compensation_mln']||{};
 const compensation=amount(inputs.mo_vri_compensation_mln),recorded=amount(vri.compensation_rub);
 if(compOrigin.source==='mo_vri_compensation'||(applied&&compOrigin.source!=='manual'&&compensation!==null&&recorded!==null&&Math.abs(compensation*1e6-recorded)<.005)){
  delete inputs.mo_vri_compensation_mln;delete origins['inputs.mo_vri_compensation_mln'];
 }
 if(config&&typeof config==='object'){delete config.applied;delete config.result}
 delete inputs._mo_vri_relief;
 if(stored?.vri&&typeof stored.vri==='object'){
  // Accepted parcels retain their cadastral rent bases; only the fee is detached.
  if(Object.prototype.hasOwnProperty.call(stored.vri,'parcels'))stored.vri={parcels:cloneValue(stored.vri.parcels)};
  else delete stored.vri;
 }
}
function moVriSavedBasis(){
 const own=inputs._mo_vri_relief;
 const calc=inputs._mo_calc;
 if(own!=null&&(!own||typeof own!=='object'||own.schema!==1))return null;
 const vri=own&&own.schema===1?own.vri:(calc&&calc.vri);
 if(!vri||typeof vri!=='object')return null;
 const gross=moVriNumber(vri.payment_before_compensation_rub);
 const used=moVriNumber(vri.payment_used_mln),current=moVriNumber(inputs.land_rights_cost_mln);
 if(gross===null||gross<0||used===null||current===null||Math.abs(used-current)>=1e-6)return null;
 const entered=moVriNumber(inputs.mo_vri_compensation_mln)||0;
 const saved=moVriNumber(vri.compensation_rub)||0;
 if(Math.abs(entered*1e6-saved)>=0.005)return null;
 return {gross,kind:own&&own.schema===1?(own.source||{}).kind||'manual':'mo_calculation',
  label:own&&own.schema===1?(own.source||{}).label||'Плата до уменьшения введена вручную':'Плата до уменьшения из сохранённого расчёта по Московской области',vri};
}
function moVriModelKey(){
 const basis=moVriSavedBasis();
 return JSON.stringify([classRegion(),inputs._project_uid||'',inputs.land_rights_cost_mln,
  inputs.mo_vri_compensation_mln,inputs.mo_vri_benefits,inputs.school_places,inputs.kindergarten_places,
  inputs.school_cost_mln_per_place,inputs.kindergarten_cost_mln_per_place,basis&&basis.gross,basis&&basis.kind,
  inputs.vri_transfer_offset_mln,inputs.vri_relief_mode,inputs.vri_relief_pct,inputs.vri_relief_mln,tep,
  typeof partialTepMode==='function'&&partialTepMode()]);
}
function moVriReliefBinding(){
 return JSON.stringify([moVriModelKey(),(moVriNode('moVriGross')||{}).value,
  (moVriNode('moCompensation')||{}).value,moVriReliefBaseSource,moVriBenefitMode(),moVriBenefitsDraft]);
}
function moVriReliefStatus(text){const node=moVriNode('moVriReliefStatus');if(node)node.textContent=text}
function invalidateMoVriRelief(){
 ++moVriReliefRun;moVriReliefPreview=null;
 const apply=moVriNode('moVriApplyButton');if(apply)apply.disabled=true;
 const preview=moVriNode('moVriPreviewButton');if(preview)preview.disabled=false;
 const result=moVriNode('moVriReliefResult');if(result)result.style.display='none';
}
function resetMoVriRelief(){
 // Номер запроса только растёт: поздний ответ старого проекта не становится
 // допустимым после сброса. Сам черновик и его происхождение принадлежат проекту.
 invalidateMoVriRelief();
 moVriReliefOwner=null;moVriReliefProjectKey='';moVriReliefModelKey='';
 moVriReliefPreview=null;moVriReliefBaseSource=null;
 moVriReliefGrossEdited=false;moVriReliefCompEdited=false;
 moVriBenefitsDraft=null;renderMoVriBenefitBreakdown(null);
 ['moVriGross','moCompensation'].forEach(id=>{const field=moVriNode(id);if(field)field.value=''});
 ['moVriGrossSource','moVriReliefStatus'].forEach(id=>{const node=moVriNode(id);if(node)node.textContent=''});
 const totals=moVriNode('moVriReliefTotals');if(totals)totals.innerHTML='';
}
function invalidateMoCalculation(){
 ++moCalculateRun;
 const button=moVriNode('cadastralAnalyzeButton');if(button){button.disabled=false;button.textContent='Получить ТЭП'}
}
function resetMoTerritoryDraft(){
 ++moTerritoryEpoch;invalidateMoCalculation();
 resetMoVriRelief();
}
function moVriReliefEdited(baseChanged){
 invalidateMoVriRelief();renderMoVriBenefitBreakdown(null);
 if(baseChanged){moVriReliefGrossEdited=true;moVriReliefBaseSource={kind:'manual',label:'Плата до уменьшения введена вручную'}}
 else moVriReliefCompEdited=true;
 const origin=moVriNode('moVriGrossSource');
 if(origin&&moVriReliefBaseSource)origin.textContent=moVriReliefBaseSource.label;
 moVriReliefStatus('Проверьте предварительный расчёт. До применения плата проекта остаётся прежней.');
}
function renderMoVriReliefResult(vri,withFinal){
 renderMoVriBenefitBreakdown(vri.benefits||null);
 const rows=[['Плата до уменьшения',moVriMoney(vri.payment_before_compensation_rub)],
  [vri.benefits?'Расчётная потенциальная льгота':'Компенсация по соглашению',moVriMoney(vri.compensation_rub)],
  ['Фактически вычтено',vri.compensation_applied_rub==null?'уменьшение не применено':moVriMoney(vri.compensation_applied_rub)],
  ['Плата после уменьшения',moVriMoney(vri.payment_used_rub)]];
 if(vri.benefits)rows.push(['Оценка сверх доступного уменьшения этой платы',moVriMoney(Math.max(0,Number(vri.compensation_rub||0)-Number(vri.compensation_applied_rub||0)))]);
 if(withFinal){
  rows.push(['Отдельный зачёт переданных площадей',moVriMoney(vri.transfer_offset_requested_rub)],
   ['Из него учтено в плате',moVriMoney(vri.transfer_offset_applied_rub)]);
  if(Number(vri.other_relief_rub)>0)rows.push(['Другие уменьшения, заданные во ВРИ',moVriMoney(vri.other_relief_rub)]);
  rows.push(['Итого основная плата, без процентов рассрочки',moVriMoney(vri.payment_after_reliefs_rub)]);
 }
 const totals=moVriNode('moVriReliefTotals');
 if(totals)totals.innerHTML=rows.map(([label,value])=>'<tr><td>'+escapeHtml(label)+'</td><td><b>'+escapeHtml(value)+'</b></td></tr>').join('');
 const result=moVriNode('moVriReliefResult');if(result)result.style.display='';
}
function renderMoVriRelief(){
 const panel=moVriNode('moVriReliefPanel');if(!panel)return;
 normalizeMoVriRegion();
 const region=classRegion();panel.style.display=region==='mo'?'':'none';
 const mpt=moVriNode('mpt-benefit-panel');if(mpt){mpt.hidden=region!=='msk';mpt.style.display=region==='msk'?'':'none'}
 if(region!=='mo'){invalidateMoVriRelief();return}
 const source=moVriNode('moVriReliefSource');if(source&&MO_VRI_COMPENSATION_SOURCE.url)source.href=MO_VRI_COMPENSATION_SOURCE.url;
 const projectKey=moVriDraftProjectKey(),modelKey=moVriModelKey();
 const ownerChanged=moVriReliefOwner!==inputs||moVriReliefProjectKey!==projectKey;
 if(ownerChanged||moVriReliefModelKey!==modelKey){
  // Другой проект получает свои поля. Обычный пересчёт ТЭП снимает только
  // прежний результат: renderTep дополняет производные поля после renderInputs.
  // Новый ручной ввод при таком изменении остаётся черновиком до Preview/Apply.
  invalidateMoVriRelief();moVriReliefOwner=inputs;moVriReliefProjectKey=projectKey;moVriReliefModelKey=modelKey;
  if(ownerChanged){moVriReliefGrossEdited=false;moVriReliefCompEdited=false;loadMoVriBenefitDraft()}
  const basis=moVriSavedBasis();
  if(!moVriReliefGrossEdited){
   moVriReliefBaseSource=basis?{kind:basis.kind,label:basis.label}:null;
   const gross=moVriNode('moVriGross');if(gross)gross.value=basis?String(basis.gross/1e6):'';
  }
  syncMoCompensation();
  const origin=moVriNode('moVriGrossSource');if(origin)origin.textContent=moVriReliefBaseSource?moVriReliefBaseSource.label:'Исходная плата до уменьшения в проекте не подтверждена. Впишите известную сумму; текущая плата показана отдельно.';
  if(moVriReliefGrossEdited||moVriReliefCompEdited)moVriReliefStatus('Параметры проекта изменились. Введённые суммы сохранены; рассчитайте уменьшение ещё раз.');
  else if(basis){renderMoVriReliefResult(basis.vri);moVriReliefStatus('Показано уменьшение, уже учтённое в текущей плате проекта. Изменения нужно сначала рассчитать и затем применить.')}
  else moVriReliefStatus('Укажите плату до уменьшения. Предварительный расчёт не меняет проект.');
 }
 const current=moVriNode('moVriCurrentFee');if(current)current.textContent='Плата в настройках проекта: '+moVriMoney(moVriNumber(inputs.land_rights_cost_mln)===null?null:Number(inputs.land_rights_cost_mln)*1e6)+'. Отдельный зачёт площадей и другие льготы применяются к ней при построении графика ВРИ.';
 const transfer=moVriNode('moVriTransferNote');if(transfer){
  const metres=moVriNumber((tep.apartments||{}).transfer),offset=moVriNumber(inputs.vri_transfer_offset_mln);
  transfer.textContent='В модели передаётся квартир: '+(metres===null?'не указано':metres.toLocaleString('ru-RU')+' м²')+
   '. Отдельный денежный зачёт: '+moVriMoney(offset===null?null:offset*1e6)+'.';
 }
 if(typeof partialTepMode==='function'&&partialTepMode()){
  invalidateMoVriRelief();moVriReliefStatus('Сначала дополните исходные данные ТЭП. Применение платы к неполному проекту недоступно.');
  const preview=moVriNode('moVriPreviewButton');if(preview)preview.disabled=true;
 }
}
function openMoVriRelief(){
 openTab('vri');renderMoVriRelief();const panel=moVriNode('moVriReliefPanel');
 if(panel&&classRegion()==='mo'){panel.open=true;panel.scrollIntoView({block:'start',behavior:'smooth'})}
}
function openMoVriTransferOffset(){
 openTab('vri');const field=moVriNode('f_vri_transfer_offset_mln');if(!field)return;
 let parent=field.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement}
 field.scrollIntoView({block:'center',behavior:'smooth'});field.focus();
}
async function previewMoVriRelief(){
 renderMoVriRelief();
 if(classRegion()!=='mo')return;
 if(typeof partialTepMode==='function'&&partialTepMode())return;
 const calculated=moVriBenefitMode()==='calculated';
 const gross=moVriNumber((moVriNode('moVriGross')||{}).value),compensation=moVriNumber((moVriNode('moCompensation')||{}).value);
 invalidateMoVriRelief();
 const compensationField=moVriNode('moCompensation');
 if(!calculated&&compensationField&&compensationField.validity&&compensationField.validity.badInput){moVriReliefStatus('Закончите ввод суммы компенсации или очистите поле.');return}
 if((gross===null&&!calculated)||(gross!==null&&gross<0)){moVriReliefStatus('Укажите известную плату до уменьшения: сумму не меньше нуля.');return}
 if(!calculated&&compensation!==null&&compensation<0){moVriReliefStatus('Сумма компенсации должна быть не меньше нуля.');return}
 const owner=inputs,binding=moVriReliefBinding(),run=moVriReliefRun;
 const origin=moVriReliefBaseSource||{kind:'manual',label:'Плата до уменьшения введена вручную'};
 const button=moVriNode('moVriPreviewButton');if(button)button.disabled=true;
 moVriReliefStatus('Считаю уменьшение платы…');
 try{
  const response=await fetch('/mo/vri-compensation',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({payment_before_compensation_rub:gross===null?null:gross*1e6,compensation_rub:calculated?null:compensation===null?null:compensation*1e6,
    benefits:calculated?moVriBenefitConfig():null,
    inputs,tep,session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await serverJson(response);
  if(run!==moVriReliefRun||owner!==inputs||binding!==moVriReliefBinding())return;
  if(!response.ok)throw new Error(serverDetail(data)||'Не удалось рассчитать уменьшение платы');
  const vri=data&&data.vri;
  renderMoVriBenefitBreakdown(data.benefits||null);
  if(data.benefits&&!vri){moVriReliefStatus(data.benefits.complete?'Потенциальная льгота рассчитана. Укажите исходную плату за ВРИ для расчёта остатка и применения.':'Заполните недостающие данные обязательств. Проект не изменён.');return}
  if(!vri||moVriNumber(vri.payment_before_compensation_rub)===null||moVriNumber(vri.payment_used_rub)===null
   ||moVriNumber(vri.payment_used_mln)===null||moVriNumber(vri.payment_after_reliefs_rub)===null||Number(vri.payment_used_rub)<0
   ||Math.abs(Number(vri.payment_before_compensation_rub)-gross*1e6)>0.011
   ||(!calculated&&Math.abs((moVriNumber(vri.compensation_rub)||0)-(compensation||0)*1e6)>0.011)
   ||Math.abs(Number(vri.payment_used_mln)*1e6-Number(vri.payment_used_rub))>0.011)
   throw new Error('Сервер не вернул полный расчёт платы. Проект не изменён.');
  moVriReliefPreview={owner,binding,vri,source:origin,benefits:calculated?moVriBenefitConfig():null};renderMoVriReliefResult(vri,true);
  moVriNode('moVriApplyButton').disabled=false;
  moVriReliefStatus('Предварительный расчёт. Для переноса платы нажмите «Применить плату к проекту». '+(vri.warnings||[]).join(' '));
 }catch(error){
  if(run===moVriReliefRun&&owner===inputs&&binding===moVriReliefBinding())moVriReliefStatus(String(error.message||error));
 }finally{if(button&&run===moVriReliefRun)button.disabled=false}
}
async function applyMoVriRelief(){
 const preview=moVriReliefPreview;
 if(!preview||preview.owner!==inputs||classRegion()!=='mo'||preview.binding!==moVriReliefBinding()
  ||(typeof partialTepMode==='function'&&partialTepMode())){
  invalidateMoVriRelief();moVriReliefStatus('Исходные данные изменились. Рассчитайте уменьшение ещё раз.');return;
 }
 invalidateMoVriRelief();
 inputs.land_rights_cost_mln=preview.vri.payment_used_mln;
 inputs.mo_vri_compensation_mln=preview.vri.compensation_rub==null?0:preview.vri.compensation_rub/1e6;
 if(preview.benefits){
  inputs.mo_vri_benefits={...cloneValue(preview.benefits),result:cloneValue(preview.vri.benefits),
   applied:{gross_rub:preview.vri.payment_before_compensation_rub,net_mln:preview.vri.payment_used_mln}};
 }else delete inputs.mo_vri_benefits;
 inputs._mo_vri_relief={schema:1,vri:cloneValue(preview.vri),source:cloneValue(preview.source)};
 fieldOrigins()['inputs.land_rights_cost_mln']={source:'mo_vri_compensation',text:'Плата по Московской области после уменьшения по соглашению. '+preview.source.label+'.'};
 if(preview.benefits)fieldOrigins()['inputs.mo_vri_compensation_mln']={source:'mo_vri_compensation',text:'Предварительная оценка по обязательствам 1310-ПП; пересчитывается при изменении входов.'};
 else markFieldManual('inputs.mo_vri_compensation_mln');
 moVriReliefOwner=null;renderInputs();
 renderMoVriReliefResult(preview.vri,true);
 let kept=true;try{persistLocalSilently()}catch(error){kept=false}
 moVriReliefStatus('Плата применена к проекту. ТЭП, очередность и отдельный денежный зачёт сохранены.'+(kept?'':' Локальную копию сохранить не удалось: сохраните проект в кабинете или скачайте настройки.'));
 await calculate();
}

// Полный пересчёт МО читает только уже применённую сумму проекта. Поле в
// панели ВРИ — черновик до отдельного «Применить»: его читает только
// previewMoVriRelief, иначе правка плотности молча применила бы этот черновик.
function moCompensationRub(){
 const mln=Number(inputs.mo_vri_compensation_mln||0);
 return mln>0?mln*1e6:0;
}

// Плата после уменьшения бывает 1 ₽: в миллионах с одним знаком это «0,0»,
// и строка читалась бы как отсутствие платы. Малую сумму пишем в рублях.
function moFeeText(v){
 const rub=v.payment_used_rub;
 if(rub!=null&&rub>0&&rub<100000)return landNum(rub,0)+' ₽';
 return v.payment_used_mln!=null?landNum(v.payment_used_mln,1)+' млн ₽':'—';
}

function syncMoCompensation(){
 const field=document.getElementById('moCompensation');
 if(!field||moVriHasCompensationDraft())return;
 const mln=Number(inputs.mo_vri_compensation_mln||0);
 field.value=mln>0?String(mln):'';
}

function toggleMoKd(){
 const field=document.getElementById('moKd');
 const manual=document.getElementById('moKdManual');
 const unit=document.getElementById('moKdUnit');
 if(!field||!manual)return;
 field.readOnly=!manual.checked;
 if(manual.checked){
  if(unit)unit.textContent='доля. Задано вручную, справочник не применяется';
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
  if(unit)unit.textContent='₽/м². Задано вручную, справочник не применяется';
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
  ?'<b>Средняя цена метра жилья (Кср) известна для '+count+' муниципальных образований'+
   (state.period?' на '+escapeHtml(state.period):'')+'.</b>'+
   (state.region_average?' В среднем по области — '+landNum(state.region_average,0)+' ₽/м².':'')+
   (state.document?'<br><span style="color:#888">'+escapeHtml(state.document)+'</span>':'')+
   '<br>Цена метра и кадастровая стоимость подставляются по округу сами, загружать ничего не нужно.'
  :'Справочник цен на жильё сейчас недоступен. Цену метра возьмём из поля выше, а если оно пустое — из удельного показателя кадастровой стоимости (УПКС) жилья в округе.';
 const kd=Number((kdState||{}).count||0);
 if(kd){
  node.innerHTML+='<br><br><b>Коэффициент доходности (Кд) известен для '+kd+' муниципальных образований.</b>'+
   ((kdState||{}).document?'<br><span style="color:#888">'+escapeHtml(kdState.document)+'</span>':'');
 }
}

async function calculateMo(queryText){
 const owner=inputs,epoch=moTerritoryEpoch,run=++moCalculateRun,region=classRegion();
 const current=()=>owner===inputs&&epoch===moTerritoryEpoch&&run===moCalculateRun&&region===classRegion();
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
 status.textContent='Участок в Московской области. Считаю по нормам области ТЭП, школы и детсады и плату за смену разрешённого использования…';
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
    vri_compensation_rub:moCompensationRub(),
    average_flat_sqm:Number(document.getElementById('moFlat').value||0)||AVERAGE_FLAT.mo.sqm
   })
  });
  const data=await response.json();
  if(!current())return;
  if(!response.ok)throw new Error(serverDetail(data)||'Не удалось рассчитать проект');
  moResult=data;
  moLastQuery=query;
  renderMo(data);
  drawLandPreviewQuiet(query);
  syncMoParams(data);
  if(moStatus)moStatus.style.display='none';
  const parcels=((data.vri||{}).parcels||[]).length;
  const asked=cadastralNumbersIn(query).length;
  const parcelNote=asked?', участков в расчёте: '+parcels+' из '+asked:(parcels?', участков: '+parcels:'');
  status.innerHTML='<span class="import-ok">Расчёт по Московской области готов: '+landNum(data.territory.site_area_ha,4)+' га, '+
   landNum(data.social.apartments_sqm,0)+' м² квартир'+parcelNote+'.</span> Проверьте числа и нажмите «Подставить в проект».';
  // Если расчёт МО уже применён к проекту, правка плотности или Кд обязана
  // доехать до модели сама: иначе блок показывает новые числа, модель считает
  // по старым, и в Telegram уходит расчёт, которого пользователь не видел.
  if(inputs._mo_calc)await applyMo({silent:true});
 }catch(e){
  if(!current())return;
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
 }finally{
  if(run===moCalculateRun){button.disabled=false;button.textContent='Получить ТЭП'}
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
 const compensation=document.getElementById('moCompensation');
 if(compensation&&!moVriHasCompensationDraft())compensation.value=v.compensation_rub!=null?String(v.compensation_rub/1e6):'';
}

// Дефицит рабочих мест — это будущий объект, а не строка справки. РНГП МО
// требует 0,5 рабочего места на жителя; соцобъекты, нормативная торговля,
// общепит и быт часть закрывают, остаток закрывать девелоперу — офисом или
// дополнительной торговлей. Раньше на экране стояли «офисы под рабочие места
// N м²» без слова «нужно», и это читалось как справка (замечание владельца,
// 19.08.2026).
function jobsGapText(jobs){
 const gap=Number((jobs||{}).deficit||0);
 if(gap<=0)return 'дефицита нет: школы, детсады и другие обязательные объекты дают достаточно рабочих мест';
 const office=Number(jobs.office_sqm||0),retail=Number(jobs.retail_sqm||0);
 return 'около '+landNum(office,0)+' м² офисов или около '+landNum(retail,0)+
  ' м² магазинов или их сочетание — этого хватит на недостающие рабочие места';
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
  ['Плата за смену ВРИ',moFeeText(v)]
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 const tables=[];
 tables.push(moTable('Территория',[
  ['Кадастровые номера',(t.cadastral_numbers||[]).join(', ')||'—'],
  ['Городской округ',(t.district||'—')+(t.district_source?' ('+t.district_source+')':'')],
  ['Кадастровый квартал',t.quarter||'—'],
  ['Адрес по госреестру',t.address||'—'],
  ['Плотность',landNum(data.density_sqm_per_ha,0)+' м² квартир на 1 га']
 ]));
 tables.push(moTable('Школы, детсады и другие объекты по нормам Московской области',[
  ['Детский сад',landNum(s.kindergarten.places,0)+' мест, участок '+landNum(s.kindergarten.site_ha,4)+' га, здание '+landNum(s.kindergarten.gba_sqm,0)+' м²'],
  ['Школа',landNum(s.school.places,0)+' мест, участок '+landNum(s.school.site_ha,4)+' га, здание '+landNum(s.school.gba_sqm,0)+' м²'],
  ['Поликлиника',landNum(s.clinic.capacity,0)+' посещений в смену, здание '+landNum(s.clinic.gba_sqm,0)+' м²'],
  ['Парковка для жителей',landNum(s.parking.permanent_spaces,0)+' машино-мест, подземная '+landNum(s.parking.underground_sqm,0)+' м²'],
  ['Парковка для гостей',landNum(s.parking.temporary_spaces,0)+' машино-мест. Норма — не меньше 30 мест'
    +' на 1000 жителей. В проекте их не строим: норма разрешает поставить их в пределах жилого района.'],
  ['Озеленение',landNum(s.green.quarter_sqm,0)+' м², из них общего пользования '+landNum(s.green.public_sqm,0)+' м²'],
  ['Нежилые помещения общественные',landNum(s.public_premises_sqm,0)+' м²'],
  ['Рабочие места',landNum(s.jobs.required,0)+' нужно по норме, '+landNum(s.jobs.from_objects,0)+
    ' дадут школы, детсады и другие обязательные объекты, не хватает '+landNum(s.jobs.deficit,0)],
  ['Что добавить для рабочих мест',jobsGapText(s.jobs)],
  ['Компенсация в бюджет','больница на '+landNum(s.budget_compensation.hospital_beds,1)+' коек, скорая помощь '+landNum(s.budget_compensation.ambulance_cars,2)+' машин, пожарное депо '+landNum(s.budget_compensation.fire_cars,2)+' машин'],
  ['Площадь жилой части по наружным стенам',landNum(s.gns_sqm,0)+' м²']
 ]));
 const upksSource=(data.upks||{}).source||{};
 const landSource=upksSource.land||{},oksSource=upksSource.oks||{};
 tables.push(moTable('Смена ВРИ',[
  ['УПКС земли под жильё',(v.upks_target!=null?landNum(v.upks_target,2)+' ₽/м²':'—')+
    (landSource.valuation_date?' · оценка на '+landSource.valuation_date:'')],
  ['УПКС ОКС МКД округа',(v.upks_average_oks!=null?landNum(v.upks_average_oks,2)+' ₽/м²':'—')+
    (oksSource.valuation_date?' · оценка на '+oksSource.valuation_date:'')],
  ['УПКС ОКС МКД для коэффициента К',(v.upks_p!=null?landNum(v.upks_p,2)+' ₽/м²':'—')+(v.upks_p_basis?' · '+v.upks_p_basis:'')],
  ['Кадастровая стоимость сейчас',landNum(v.cadastral_value_current_rub/1e6,1)+' млн ₽'],
  ['Кадастровая стоимость целевая',landNum(v.cadastral_value_target_rub/1e6,1)+' млн ₽'],
  ['Разница ∆КС',landNum(v.delta_rub/1e6,1)+' млн ₽'],
  ['Кср / Кд',(v.market_price_rub_per_sqm!=null?landNum(v.market_price_rub_per_sqm,0)+' ₽/м²':'—')+' · '+landNum(v.kd,2)+
    (v.market_price_source?' · '+v.market_price_source:'')+(v.market_price_period?' · '+v.market_price_period:'')],
  ['К1 / К',(v.k1!=null?landNum(v.k1,4):'—')+' · '+(v.k!=null?landNum(v.k,4):'—')],
  ...(v.compensation_rub!=null?[
   ['Плата до уменьшения',v.payment_before_compensation_rub!=null?landNum(v.payment_before_compensation_rub/1e6,1)+' млн ₽':'—'],
   ['Компенсация по соглашению',landNum(v.compensation_rub/1e6,1)+' млн ₽ · '+(v.compensation_basis||'')+
     (v.compensation_applied_rub!=null?' · вычтено '+landNum(v.compensation_applied_rub/1e6,1)+' млн ₽':'')]
  ]:[]),
  ['Плата за смену ВРИ',moFeeText(v)+' · '+(v.payment_basis||'')]
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
 const said=showSiteRestrictions('moRestrictions',data.site_restrictions);
 document.getElementById('moWarnings').innerHTML=(data.warnings||[]).filter(x=>!said.includes(String(x)))
  .map(x=>'• '+escapeHtml(x)).join('<br>');
 document.getElementById('moPreview').style.display='block';
}

async function applyMo(options){
 const silent=!!(options&&options.silent);
 const status=document.getElementById('moStatus');
 if(!moResult){if(!silent)status.innerHTML='<span class="import-error">Сначала выполните расчёт.</span>';return}
 const incoming=moResult;
 const sameTerritory=silent&&inputs._mo_calc&&JSON.stringify([inputs._mo_calc.query,inputs._mo_calc.territory])===JSON.stringify([incoming.query,incoming.territory]);
 const keepBenefits=sameTerritory&&inputs.mo_vri_benefits?cloneValue(inputs.mo_vri_benefits):null;
 const leaseTerritoryBefore=landRentMoTerritoryKey(inputs._mo_calc);
 const keepLeaseTerms=silent&&!!leaseTerritoryBefore&&leaseTerritoryBefore===landRentMoTerritoryKey(incoming);
 resetTerritoryData({keepPhasing:silent,keepLeaseTerms,keepMoVriDraft:sameTerritory});
 moResult=incoming;
 Object.assign(inputs,moResult.inputs||{});
 if(keepBenefits&&keepBenefits.applied&&moResult.vri?.payment_before_compensation_rub!=null){
  keepBenefits.applied={gross_rub:moResult.vri.payment_before_compensation_rub,net_mln:moResult.vri.payment_used_mln};
  inputs.mo_vri_benefits=keepBenefits;
 }
 syncMoCompensation();
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
  warnings:moResult.warnings||[],
  site_restrictions:moResult.site_restrictions||null
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
 syncMoCompensation();
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

// Пресеты проектов — витрина владельца: в них настоящие проекты с ценами и
// сроками, и посторонним их не показывают (решение владельца, 18.08.2026).
// Сервер отказывает не своему, страница на отказ убирает блок целиком, а не
// оставляет пустой список без объяснения. Серверных предустановок ТЭП
// («Мишина», «Мытищи») больше нет (решение владельца, 23.10.2026).
function presetsQuery(){
 return '?session='+encodeURIComponent(activeSession())+
        '&key='+encodeURIComponent(projectsAdminKey||'');
}

function hidePresetsBlock(){
 const box=document.getElementById('projectsExamples');
 if(box)box.style.display='none';
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
     templateError=String(serverDetail(payload)||'').trim()||'Шаблон ТЭП DevelopAid заполнен не полностью.';
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
   if(!response.ok)throw new Error(serverDetail(payload)||'Ошибка импорта');
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
 const said=showSiteRestrictions('glavapuRestrictions',data.site_restrictions);
 const gw=(data.warnings||[]).filter(x=>String(x||'').trim()&&!said.includes(String(x)));
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


// Машино-места в чат — по видам и из расчёта движка, как итоги и PDF
// (решение владельца 16.10.2026): подземный паркинг (из них к продаже),
// наземный, приобъектные. Одно число под подписью «подземный паркинг»
// складывало все три вида, а в жилом проекте бралось из ТЭП страницы или
// выгрузки, а не из расчёта.
function telegramParkingByKind(result){
 const tepResult=(result&&result.tep)||{};
 const row=key=>(tepResult.rows||[]).find(r=>r.key===key)||{};
 const under=row('underground_parking');
 return {
  underground:Number(under.units||0),
  underground_saleable:Number(under.saleable_units||0),
  above:Number(row('above_parking').units||0),
  // Паркинг объектов стоит полем на их строках; сумма — у итога ТЭП.
  attached:Number((tepResult.total||{}).parking_units||0)};
}

async function sendTelegramResult(){
 function telegramResultErrorNotice(message){
 let notice=document.getElementById('telegramResultError');
 if(!message){if(notice&&typeof notice.remove==='function')notice.remove();return}
 if(!notice){
  notice=document.createElement('div');notice.id='telegramResultError';notice.setAttribute('role','alert');
  notice.style.cssText='position:fixed;left:0;right:0;top:0;z-index:99998;padding:12px 16px;'
   +'background:#fff2d9;color:#6c3d00;font-weight:700;font-size:14px;overflow-wrap:anywhere;max-height:40vh;overflow:auto';
  document.body.appendChild(notice);
 }
 notice.textContent=message;
 }
 const glavapuMeta=inputs._glavapu_import||null;
 const manualMeta=inputs._manual_tep_import||null;
 const documentMeta=inputs._intake_qualification||null;
 if(!telegramSession||telegramResultSent||!lastResult||(!glavapuMeta&&!manualMeta&&!documentMeta))return;
 if(sendTelegramResult.pending)return;
 // A timed-out request may already have delivered its message. Only the
 // explicit user recalculation/edit action may try again after that outcome.
 if(sendTelegramResult.uncertain&&(typeof telegramEditSubmitting==='undefined'||!telegramEditSubmitting))return;
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
  persistLocalSilently();
 const payload={
   cadastral_numbers:cads,
   project_name:manual?String(manualMeta.project_name||''):'',
   source_label:tepSourceLabel(manual),
    purchase_price_mln:Number(inputs.purchase_price_mln||0),
    land_buyout_mln:Number(inputs.land_buyout_mln||0),
    // Основание выкупа — из расчёта, той же подписью, что страница и PDF.
    land_buyout_label:String(((lastResult&&lastResult.deal)||{}).buyout_label||''),
    // Источник проекта важнее сохранённого значения: в inputs могла остаться
    // площадь прошлого расчёта, и она перебивала площадь текущего участка.
    site_area_ha:Number(n.site_area_ha||(manualMeta&&manualMeta.site_area_ha)||inputs.site_area_ha||0),
    apartment_area_sqm:counted?Number(countedRow('apartments').saleable||0)
     :(manual||edited)?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),
    change_vri_mln:counted?0:(manual||edited)?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),
    social_compensation_mln:counted?0:(manual||edited)?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),
    // Обеспеченность парковкой — ответ движка с подписью «N мест / M по норме = K×».
    parking_provision_label:parkingProvisionText(),
    parking:telegramParkingByKind(lastResult),
   revenue_mln:Number(s.revenue||0)/1e6,
    total_expenses_mln:Number(s.total_expenses||0)/1e6,
   ebitda_mln:Number(s.ebitda||0)/1e6,
   net_profit_mln:Number(s.net_profit||0)/1e6,
   preliminary:!!s.preliminary,
   preliminary_reason:s.preliminary_reason||'',
   margin:Number(s.margin||0),
   irr_project:s.irr_project==null?null:Number(s.irr_project),
   irr_equity:s.irr_equity==null?null:Number(s.irr_equity),
   irr_equity_label:irrEquityNa(s),
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
   // Чем модель гасит долг после дефолта, зависит от числа очередей: без него
   // бот говорил «продажами следующих периодов» и проекту с одной очередью.
   queue_count:(phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length)||1,
    report_payload:currentPdfReportPayload(cads)
 };
 let requestStarted=false;
 const previousUnknown=!!sendTelegramResult.uncertain;
 try{
   sendTelegramResult.pending=true;
   sendTelegramResult.failure='';
   telegramResultErrorNotice('');
   telegramProgress('Готов. Отправляю в чат…');
   // Если ответ задерживается, надпись не должна выглядеть зависшей: в чате
   // к этому моменту уже может быть всё, и человек ждёт впустую.
   const controller=typeof AbortController==='function'?new AbortController():null;
   let slow;
   const deadline=new Promise((_,reject)=>{slow=setTimeout(()=>{
     reject(new Error('Время ожидания истекло. Доставка неизвестна: проверьте чат перед повторной отправкой.'));
     if(controller)controller.abort();
   },20000)});
   const request=(async()=>{
     const body=JSON.stringify({session:telegramSession,summary:payload,
      qualification_session:typeof telegramQualificationSession==='string'?telegramQualificationSession:''});
     requestStarted=true;
     const response=await fetch('/telegram/result',{
       method:'POST',
       headers:{'Content-Type':'application/json'},
       body,
       ...(controller?{signal:controller.signal}:{})
     });
     const result=await response.json();
     if(!response.ok){const e=new Error(serverDetail(result)||'Telegram не принял результат');e.deliveryUnknown=![401,403,409,422].includes(response.status);throw e}
     if(!result||result.ok!==true)throw new Error('Сервер не подтвердил доставку. Проверьте чат перед повторной отправкой.');
     return result;
   })();
   await Promise.race([request,deadline]).finally(()=>clearTimeout(slow));
   telegramResultSent=true;
   sendTelegramResult.uncertain=false;
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML+=' <b>Итоговая карточка отправлена в Telegram. PDF-отчёт и Excel-модель придут следом.</b>'
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
   sendTelegramResult.uncertain=previousUnknown||(requestStarted&&e.deliveryUnknown!==false);
   sendTelegramResult.failure=String(e.message||e)+(sendTelegramResult.uncertain?' Доставка неизвестна. Проверьте чат перед повторной отправкой.':'');
   telegramResultErrorNotice('Не удалось отправить итог в Telegram: '+sendTelegramResult.failure);
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML+=' <span class="import-error">Не удалось отправить итог в Telegram: '+escapeHtml(sendTelegramResult.failure)+'</span>';
 }finally{
   sendTelegramResult.pending=false;
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
 // Соглашение о Ксу* заключают на конкретный участок.
 'mo_vri_compensation_mln',
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
