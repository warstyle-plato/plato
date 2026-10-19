"""Кусок страницы PAGE: Скрипт: вводные — сброс данных территории, происхождение полей,
применение ГлавАПУ, подземная парковка, класс проекта, вид проекта,
renderInputs, гостиница.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_inputs")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""const TERRITORY_MARKERS=['_glavapu_import','_field_origin','_manual_tep_import','_mo_calc','_cadastral_analysis','_cadastral_query','_cadastral_origin',
 '_site_area_user_set','_site_density_user_set','_demolition_source','_land_buyout_source','_vri_relief_source','vri_mpt_override'];

// Предпосылки аналитика — цены, себестоимость, ставки, сроки, налоги — это не
// данные участка, и сбрасывать их при смене территории нельзя.
// Подписи обнулённых полей — человеческие: ключ `purchase_price_mln` в плашке
// не значит ничего, а «цена входа» значит всё.
const TERRITORY_CLEARED_LABELS={
 purchase_price_mln:'цена входа', land_rights_cost_mln:'плата за смену ВРИ',
 social_compensation_mln:'социальная компенсация', site_area_ha:'площадь участка',
 site_density_sqm_per_ha:'плотность', kindergarten_places:'места в ДОО',
 school_places:'места в школе', clinic_capacity:'мощность поликлиники',
 social_dou_gba_sqm:'площадь ДОО', social_school_gba_sqm:'площадь школы',
 social_clinic_gba_sqm:'площадь поликлиники', offices_gba_sqm:'площадь офисов',
 offices_saleable_sqm:'продаваемая офисов', retail_gba_sqm:'площадь ТЦ',
 retail_saleable_sqm:'продаваемая ТЦ', above_parking_spaces:'наземные машино-места',
 sports_gba_sqm:'площадь ФОКа', sports_saleable_sqm:'продаваемая ФОКа',
 parking_k1:'К1 паркинга', parking_k2:'К2 паркинга',
 parking_rail_distance_m:'расстояние до станции',
 // Поля вторых объектов — подписи из реестра движка, подстановкой.
 __DEVELOPAID_TERRITORY_OBJECT_LABELS__
};
function territoryClearedNote(){
 if(!territoryCleared.length)return '';
 const names=territoryCleared.map(k=>TERRITORY_CLEARED_LABELS[k]||k);
 return ' <b>Обнулено вместе с участком: '+names.join(', ')
  +'.</b> Эти значения относятся к площадке, а не к вашим предпосылкам — введите заново.';
}

function resetTerritoryData(options){
 // Очерёдность — решение пользователя, а не свойство территории. При тихом
 // пересчёте параметров Подмосковья участок тот же, и сбрасывать её нельзя.
 const keepPhasing=!!(options&&options.keepPhasing);
 Object.keys(tep).forEach(key=>{
  ['gns','total_area','useful','saleable','transfer','units'].forEach(field=>{
   if(field in tep[key])tep[key][field]=0;
  });
 });
 // Что именно обнулили — запоминаем и показываем. Цена входа принадлежит
 // участку и обязана сбрасываться, но человек об этом не предупреждён:
 // импортировал участок, не заметил ноль, посчитал — и получил LLCR 1,08
 // вместо 1,02. Молчаливое обнуление врёт не меньше молчаливого переезда.
 territoryCleared=[];
 TERRITORY_INPUT_KEYS.forEach(key=>{
  if(!(key in inputs))return;
  if(Number(inputs[key])>0)territoryCleared.push(key);
  // К1, К2 и расстояние при пустом поле считаются сами (по расстоянию → по
  // району → 1,0): пустое поле — не ноль, и сброс ставит пустоту.
  inputs[key]=SITE_ONLY_INPUTS.includes(key)?'':0;
 });
 TERRITORY_MARKERS.forEach(key=>{delete inputs[key]});
 STANDALONE_OBJECTS.forEach(o=>{inputs[o.prefix+'_enabled']=false});
 glavapuImport=null;
 cadastralAnalysis=null;
 moResult=null;
 if(!keepPhasing)phasing=makeDefaultPhasing(1);
 const preview=document.getElementById('cadastralPreview');
 if(preview){preview.innerHTML='';preview.style.display='none';}
 const moStatus=document.getElementById('moStatus');
 if(moStatus)moStatus.style.display='none';
}

// Происхождение значения поля: `inputs._field_origin['inputs.<ключ>']` или
// `['tep.<строка>.<поле>']` = {source:'glavapu'|'manual', text}. Ручное
// значение остаётся ручным: импорт его не перезаписывает и называет это.
function fieldOrigins(){
 if(!inputs._field_origin||typeof inputs._field_origin!=='object')inputs._field_origin={};
 return inputs._field_origin;
}
function markFieldManual(path){
 fieldOrigins()[path]={source:'manual',text:'вписано вручную'};
}
function isFieldManual(path){
 const o=(inputs._field_origin||{})[path];
 return !!(o&&o.source==='manual');
}
function fieldOriginNote(path){
 const o=(inputs._field_origin||{})[path];
 if(!o||(o.source!=='glavapu'&&o.source!=='hotel_preset'&&o.source!=='migrated'&&o.source!=='document'))return '';
 return '<div class="glavapu-origin" style="font-size:11px;color:#666;margin-top:2px">'+escapeHtml(o.text||'ГлавАПУ')+'</div>';
}
// Регион проекта — поле «Регион» проекта, и только оно. Ни имя файла
// выгрузки, ни кадастровый номер регион не задают: у Новой Москвы — НАО и ТАО —
// номера областные — 50:21, 50:26, 50:27, — а участок московский.
function projectRegion(){
 return {region:classRegion(),origin:'поле «Регион» проекта'};
}
// Подмосковье и другие регионы: калькулятор ГлавАПУ — московский и в таком
// проекте не участвует вовсе (владелец, 06.10.2026): ни подстановки, ни
// справки. Выгрузка не применяется и в проекте не сохраняется.
function refuseGlavapuOutsideMoscow(region){
 glavapuStatus.innerHTML='<span class="import-error"><b>Проект не московский</b> ('+escapeHtml(region.origin)+
  '): калькулятор ГлавАПУ — московский и в этом проекте не участвует. Выгрузка не применена и '+
  'в проекте не сохранена.</span>';
}
// Та же территория — выгрузка того же квартала с той же площадью: новая
// версия расчёта, а не новый участок. Тогда территория не обнуляется, и
// вписанное вручную остаётся.
function sameGlavapuTerritory(incoming){
 const before=((inputs._glavapu_import||{}).normalized)||{};
 const now=(incoming&&incoming.normalized)||{};
 const quarter=String(now.cadastral_quarter||'').trim();
 return !!quarter&&quarter===String(before.cadastral_quarter||'').trim()
  &&Math.abs(Number(now.site_area_ha||0)-Number(before.site_area_ha||0))<0.001;
}

async function applyGlavapu(){
 if(!glavapuImport){glavapuStatus.innerHTML='<span class="import-error">Сначала разберите файл.</span>';return}
 {
  const region=projectRegion();
  if(region.region!=='msk'){refuseGlavapuOutsideMoscow(region);return}
 }
 // Проект, сохранённый прежними версиями, не нёс mappings: применение
 // сначала обнуляло территорию, затем применяло пустоту — ВРИ, соцплатёж и
 // площади пропадали молча. Без mappings применять нечего — и портить нечего.
 {
  const m=glavapuImport.mappings||{};
  if(!Object.keys(m.inputs||{}).length&&!Object.keys(m.tep||{}).length){
   glavapuStatus.innerHTML='<span class="import-error">Показаны данные уже применённого файла — они в проекте. '+
    'Чтобы применить заново, загрузите предустановку или разберите файл ещё раз.</span>';
   return;
  }
 }
 const incoming=glavapuImport;
 // Новый участок — территория обнуляется целиком (с ручными значениями:
 // они про прежнюю площадку). Новая выгрузка того же участка — нет.
 const sameTerritory=sameGlavapuTerritory(incoming);
 const keptOrigins=sameTerritory?Object.assign({},inputs._field_origin||{}):{};
 if(sameTerritory)territoryCleared=[];
 else resetTerritoryData();
 glavapuImport=incoming;
 inputs._field_origin=keptOrigins;
 const provenance=incoming.provenance||{};
 const stamp=(path)=>{if(provenance[path])fieldOrigins()[path]=provenance[path]};
 // Значения прежней выгрузки того же участка, которых новая не несёт,
 // уходят вместе с ней: ручные остаются, выгруженные — нет.
 Object.keys(keptOrigins).forEach(path=>{
  if(keptOrigins[path].source!=='glavapu'||provenance[path])return;
  const parts=path.split('.');
  if(parts[0]==='tep'&&tep[parts[1]]&&parts[2] in tep[parts[1]])tep[parts[1]][parts[2]]=0;
  if(parts[0]==='inputs'&&parts[1] in inputs)inputs[parts[1]]=SITE_ONLY_INPUTS.includes(parts[1])?'':0;
  delete inputs._field_origin[path];
 });

 const previousMode=inputs.social_mode||'Строительство';
 const preserveMode=!!inputs._social_mode_user_set||!!inputs._glavapu_import;

 // Замок «Требования КРТ» держит и против выгрузки ГлавАПУ. Прежде здесь
 // стоял `Object.assign` — он писал плату за ВРИ, места, площади и
 // соцкомпенсацию поверх запертых полей и не говорил ни слова: так в поле
 // платы оказывались 10 166,649 млн ₽ при включённом режиме. Приоритет по
 // полю объявлен один раз и не зависит от того, кто пишет: руками > документ
 // лота КРТ > выгрузка ГлавАПУ > норматив.
 const manualKept=[];
 const glavapuSkipped=applyDerivedInputs(glavapuImport.mappings.inputs||{},
  {keepManual:manualKept,written:key=>stamp('inputs.'+key)});

 inputs._glavapu_import={
   source:glavapuImport.source,
   normalized:glavapuImport.normalized,
   recognized:glavapuImport.recognized,
   warnings:glavapuImport.warnings,
   // Без mappings повторное «Применить» после перезагрузки обнуляло
   // территорию (resetTerritoryData) и применяло пустоту.
   mappings:glavapuImport.mappings,
   provenance:glavapuImport.provenance||{}
 };
 // Площадь территории ГлавАПУ знает точно — она не должна оставаться справочной.
 {
  const glavapuArea=Number(((glavapuImport.normalized)||{}).site_area_ha||0);
  if(glavapuArea>0&&!isFieldManual('inputs.site_area_ha')){
   inputs.site_area_ha=glavapuArea;
   const when=(glavapuImport.source||{}).export_date;
   fieldOrigins()['inputs.site_area_ha']={source:'glavapu',
    text:'ГлавАПУ, '+(when?'выгрузка от '+when:'выгрузка (дата в файле не указана)')+', лист «ТЭП», строка 1'};
  }
  // Москва: плотность от СПП приезжает тем же файлом и не должна оставаться
  // справочной. Ручной ввод не перебивается.
  const glavapuDensity=Number(((glavapuImport.normalized)||{}).density_spp_th_sqm_ha||0)*1000;
  if(glavapuDensity>0&&!inputs._site_density_user_set)inputs.site_density_sqm_per_ha=0;
 }

 // Social mode is a scenario choice. Re-import must not silently reset it.
 inputs.social_mode=preserveMode
   ? previousMode
   : ((glavapuImport.normalized&&glavapuImport.normalized.suggested_social_mode)||previousMode);

 // Construction mode: use calculated ГлавАПУ needs when actual planned facilities are zero.
 applyRequiredSocialProgramFromGlavapu();

 Object.entries(glavapuImport.mappings.tep||{}).forEach(([key,vals])=>{
   if(!tep[key])return;
   Object.entries(vals).forEach(([field,value])=>{
    const path='tep.'+key+'.'+field;
    if(isFieldManual(path)){manualKept.push('ТЭП «'+key+'» → '+field);return}
    tep[key][field]=value;
    stamp(path);
   });
 });

 // Rebuild social TEP after generic mappings, then enforce parking rule.
 syncTep(false);
 // Другой участок — другой паркинг: пара полей перезаполняется его расчётом,
 // иначе в них остались бы места и метры предыдущего проекта.
 inputs.underground_manual_spaces=0;
 inputs.underground_manual_gns_sqm=0;
 // Вместе с числом снимается и замок: он про прежний участок, а этот другой.
 // Иначе пара осталась бы пустой, и поля показывали бы ноль там, где норма
 // нового участка уже посчитана.
 markParkingByNorm(PROJECT_PARKING_KEY);
 fillUndergroundFromTep();
 repairParkingFromGlavapu();

 // Server presets may include an expert project configuration in addition to source TEP.
 const presetId=glavapuImport.source&&glavapuImport.source.preset_id;
 if(presetId!=='mytishchi')phasing=makeDefaultPhasing(1);
 const presetNote=applyServerPresetProjectConfig(presetId);

 applyTelegramCalcOverrides();

 renderInputs();
 renderTep();
 renderPhasing();
 renderGlavapuPreview(glavapuImport);

 const socialNote=inputs.social_mode==='Строительство'
  ? 'Соцрежим: строительство; расчётные мощности ГлавАПУ используются при нулевых фактических объектах.'
  : 'Соцрежим: денежная компенсация.';
 const manualNote=manualKept.length?' <b>Оставлено вписанное вручную: '+escapeHtml(manualKept.join(', '))+'.</b>':'';
 const sourceNote=' Происхождение подставленных значений — у полей: «ГлавАПУ, '+
  ((glavapuImport.source||{}).export_date?'выгрузка от '+glavapuImport.source.export_date:'выгрузка (дата в файле не указана)')+', лист, строка».';
 glavapuStatus.innerHTML='<span class="import-ok">Данные ТЭП применены. Денежные единицы приведены к млн ₽. '+socialNote+manualNote+sourceNote+' Подземный паркинг собран из жилого блока и, при наличии, отдельного блока МФК.'+(presetNote?' <b>'+presetNote+'</b>':'')+(glavapuSkipped?' <b>'+escapeHtml(glavapuSkipped)+'</b>':'')+territoryClearedNote()+'</span>';
 await calculate();
 await sendTelegramResult();
}

function renderStoredGlavapu(){
 const stored=inputs._glavapu_import;
 if(!stored)return;
 glavapuImport={source:stored.source||{},normalized:stored.normalized||{},recognized:stored.recognized||[],warnings:stored.warnings||[],
  mappings:stored.mappings||{inputs:{},tep:{}},provenance:stored.provenance||{}};
 renderGlavapuPreview(glavapuImport);
 glavapuStatus.innerHTML='<span class="import-ok">Показаны данные последнего применённого файла ГлавАПУ.</span>';
}


// Потребность в местах — по метрам, которые в таблице СЕЙЧАС, а не по тем, для
// которых её посчитал город. Импорт приносит норматив для НОРМАТИВНОГО ТЭП:
// человек правит ТЭП по решению ГЗК вдвое, а строка продолжает требовать 957
// мест и объявлять нехватку, которой нет (замечание владельца, 20.08.2026).
//
// Считается ровно так, как велел владелец: постоянные — нормой 2118-ПП от
// площади квартир, гостевые — десятой частью; приобъектные МФК своей формулы
// требуют коэффициентов квартала, поэтому берутся пропорцией — во сколько раз
// изменились офисные метры, во столько же меняются места. Числа нормы объявлены
// в движке и подставлены сюда: копии нет.
function getGlavapuUnderground(){
 const stored=inputs._glavapu_import;
 const n=stored&&stored.normalized?stored.normalized:null;
 if(!n)return null;
 const impPermanent=Number(n.parking_permanent||0);
 const impGuest=Number(n.parking_guest||0);
 const impMfc=Number(n.mfc_parking_spaces||0);
 if(impPermanent+impGuest+impMfc<=0)return null;
 // Площадь квартир — продаваемая жилья: это она в норме 2118-ПП.
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 const count=Number((tep.apartments&&tep.apartments.units)||0);
 let permanent=impPermanent,guest=impGuest,basis='норматив ГлавАПУ по нормативному ТЭП';
 // Пока квартиры те же, что у выгрузки (импорт кладёт площадь и число как
 // есть), места города и остаются; правили площадь или число квартир — норма
 // от новых, та же, что без выгрузки (`permanentByNorm`). Правило то же, что
 // у движка (`glavapu_apartments_unchanged`).
 const city=Number(n.apartment_area_sqm||0);
 const unchanged=city>0&&Math.abs(apartments-city)<0.5
  &&Math.abs(count-Number(n.apartment_units||0))<0.5;
 if(apartments>0&&!unchanged){
  const own=permanentByNorm(apartments,count);
  permanent=own.permanent;
  guest=Math.ceil(permanent*PARKING_2118.guest_share);
  basis=own.basis;
 }
 let mfc=impMfc;
 const wasOffice=Number(n.office_gba_sqm||0);
 if(impMfc>0&&wasOffice>0){
  const nowOffice=STANDALONE_OBJECTS
   .filter(o=>o.product==='offices'||o.product==='standalone_retail')
   .reduce((sum,o)=>sum+Number((tep[o.key]&&tep[o.key].gns)||0),0);
  mfc=Math.ceil(impMfc*nowOffice/wasOffice);
 }
 const spaces=permanent+guest+mfc;
 if(spaces<=0)return null;
 const per=undergroundAreaPerSpace();
 const mfcArea=impMfc>0&&mfc===impMfc?(Number(n.mfc_parking_area_sqm||0)||mfc*per):mfc*per;
 return {permanent,guest,mfc,spaces,basis,gns:(permanent+guest)*per+mfcArea};
}

// Постановление считает места всегда, а не только когда есть выгрузка
// ГлавАПУ (решение владельца, 03.09.2026: «машиноместа конечно он должен
// считать по постановлениям»). Прежде пересчёт начинался с проверки импорта и
// без него не делал НИЧЕГО: проект, набранный руками, оставался с тем числом
// мест, которое когда-то попало в строку, и правка метров его не двигала.
// Норма та же, что в движке, числа подставлены плейсхолдером — копии нет.
//
// Приобъектные места нежилья сюда не входят намеренно: их формуле нужны К1 и
// К2 квартала, которых без выгрузки у нас нет, а единица «пока не знаем»
// отдала бы максимум, выданный за норматив. Поэтому здесь только жильё, и
// основание это называет.
// Постоянные места по 2118-ПП — один расчёт на обоих читателей: норму без
// выгрузки и выгрузку, чьи квартиры поправили.
function permanentByNorm(apartments,count){
 if(count>0){
  // Пункт 2 по средней квартире: состава квартир до АГР нет, но средняя
  // меняется вместе с их числом — все квартиры относятся к её полосе.
  const avg=apartments/count;
  const band=avg<PARKING_2118.bands.small_max?'small':(avg<=PARKING_2118.bands.medium_max?'medium':'large');
  return {permanent:Math.ceil(count*PARKING_2118.mix[band]),
          basis:'2118-ПП, п. 2 по средней квартире '+avg.toFixed(1).replace('.',',')+' м² ('
                +num(Math.round(count))+' квартир × '+String(PARKING_2118.mix[band]).replace('.',',')+')'};
 }
 return {permanent:Math.ceil(apartments/(PARKING_2118.sqm_per_person*PARKING_2118.household)
                             *PARKING_2118.per_flat),
         basis:'2118-ПП, п. 1 от '+num(Math.round(apartments))+' м² квартир (число квартир не задано)'};
}

function normativeUnderground(){
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(apartments<=0)return null;
 const count=Number((tep.apartments&&tep.apartments.units)||0);
 const own=permanentByNorm(apartments,count);
 const permanent=own.permanent;
 const basis=own.basis+', приобъектные нежилья не учтены';
 const guest=Math.ceil(permanent*PARKING_2118.guest_share);
 const spaces=permanent+guest;
 if(spaces<=0)return null;
 return {permanent,guest,mfc:0,spaces,basis,
         gns:spaces*undergroundAreaPerSpace()};
}

// Потребность в местах — один ответ на весь экран. Выгрузка города знает
// приобъектные места нежилья и потому идёт первой; её нет — считает норма.
//
// Нежилой проект: МКД в нём нет, значит нет и его подземного паркинга. Норма
// без квартир и так отвечает нулём, а ВЫГРУЗКА отвечает своим числом,
// посчитанным по нормативному — то есть ЖИЛОМУ — ТЭП участка: на экране
// владельца это 135 постоянных + 14 гостевых = 149 м/м и 5 215 м² под
// подписью «строка обнулена и заперта» (21.09.2026). Цена на проверочном
// нежилом проекте: CAPEX +762,6 млн ₽, выручка +74,2 (135 мест продаются),
// чистая прибыль −932,3 млн, LLCR 0,609 → 0,526. Гараж самого офисника к
// этому отношения не имеет: он считается своей нормой (приложение 6 к
// 945-ПП) и живёт своими полями объекта.
function parkingRequirement(){
 if(withoutHousing())return null;
 if(String(inputs.vri_region||'msk')==='mo')return moNormativeUnderground();
 return getGlavapuUnderground()||normativeUnderground();
}

// Московская область: РНГП МО, а не 2118-ПП и не выгрузка ГлавАПУ — оба
// московские. Та же формула, что `mo_social_program` движка, числа — из
// плейсхолдера; гостевых нет, временные места закрывает жилой район.
function moNormativeUnderground(){
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(apartments<=0)return null;
 const m=PARKING_2118.mo;
 const up=v=>Math.ceil(Math.round(v*1e6)/1e6);
 const population=up(apartments/m.living_space_per_person_sqm);
 const permanent=up(population*m.parking_permanent_per_1000/1000*m.parking_permanent_share);
 if(permanent<=0)return null;
 return {permanent,guest:0,mfc:0,spaces:permanent,
         basis:'РНГП Московской области: '+num(population)+' чел. от '+num(Math.round(apartments))
               +' м² квартир, только постоянное хранение',
         gns:permanent*undergroundAreaPerSpace()};
}

function undergroundAreaPerSpace(){
 return Number(inputs.underground_area_per_space_sqm||0)||35;
}

function repairParkingFromGlavapu(){
 if(!tep.underground_parking)return false;
 // Отказ от подземного паркинга: в области потребность закрывают наземным
 // гаражом. Ноль в поле мест значит «по нормативу», поэтому отказ — отдельный
 // признак, иначе импорт ГлавАПУ вернул бы паркинг при первом пересчёте.
 // Нежилой проект здесь же: строку чистит ТОТ ЖЕ писатель, что её и
 // наполняет, иначе обнуление переключателем отменяется первой же
 // отрисовкой — `renderTep` зовёт эту функцию первой строкой.
 if(inputs.underground_parking_disabled||withoutHousing()){
  ['units','gns','total_area','useful','saleable','transfer'].forEach(f=>{tep.underground_parking[f]=0});
  return true;
 }
 // Заданная руками площадь главнее импорта: норматив описывает потребность,
 // а реальный подземный этаж диктуют пятно застройки, рампы и техпомещения.
 // Пустое поле оставляет прежнюю починку устаревших значений.
 // Пара, поставленная нормой, идёт за нормой: поле — её число, а строка
 // берёт ответ нормы как есть, без округления поля. Иначе загруженный проект
 // показывал места прежних вводных, хотя движок по той же пометке считал
 // норму (`underground_parking_by_hand`).
 if(!undergroundPairByHand()&&fillUndergroundFromTep()){
  ['underground_manual_spaces','underground_manual_gns_sqm'].forEach(id=>{
   const el=document.getElementById('f_'+id);if(el)el.value=inputs[id];
  });
 }
 const manualSpaces=Number(inputs.underground_manual_spaces||0);
 const manualArea=Number(inputs.underground_manual_gns_sqm||0);
 if(undergroundPairByHand()&&(manualSpaces>0||manualArea>0)){
  const per=undergroundAreaPerSpace();
  const spaces=manualSpaces>0?manualSpaces:Math.round(manualArea/per);
  // Площадь берётся так же, как её берёт движок: заданная руками сильнее
  // норматива ВСЕГДА, а не только когда мест не назвали. Прежде при
  // заполненных обоих полях страница выбрасывала введённую площадь и ставила
  // `места × 35`: на 666 местах с заданными 15 540 м² в строке ТЭП вставало
  // 23 310 — 7 770 м² подземной части, которых движок не строит. На экране
  // одно число, в расчёте другое, и оба выглядели заданными.
  tep.underground_parking.units=spaces;
  tep.underground_parking.gns=manualArea>0?manualArea:spaces*per;
  tep.underground_parking.total_area=tep.underground_parking.gns;
  tep.underground_parking.useful=0;
  tep.underground_parking.saleable=0;
  tep.underground_parking.transfer=0;
  return true;
 }
 const p=parkingRequirement();
 if(!p)return false;
 tep.underground_parking.units=p.spaces;
 tep.underground_parking.gns=p.gns;
 tep.underground_parking.total_area=p.gns;
 tep.underground_parking.useful=0;
 tep.underground_parking.saleable=0;
 tep.underground_parking.transfer=0;
 return true;
}

function syncUndergroundPair(changed){
 // Места и площадь — одна величина в двух видах, а не два независимых поля.
 // Раньше в них могли одновременно стоять 50 мест и 3 000 м² при нормативе
 // 35: пара расходилась, и было непонятно, что из этого считает модель.
 // Ведущее — количество мест: норматив меняют, когда меняется представление
 // о рампах и проездах, а не о числе машин.
 const per=undergroundAreaPerSpace();
 if(per<=0)return;
 if(changed==='underground_manual_gns_sqm'){
  const area=Number(inputs.underground_manual_gns_sqm||0);
  inputs.underground_manual_spaces=area>0?Math.round(area/per):0;
 }else{
  const spaces=Number(inputs.underground_manual_spaces||0);
  inputs.underground_manual_gns_sqm=spaces>0?Math.round(spaces*per):0;
 }
 ['underground_manual_spaces','underground_manual_gns_sqm'].forEach(id=>{
  const el=document.getElementById('f_'+id);
  if(el)el.value=inputs[id];
 });
}

function fillUndergroundFromTep(){
 // Поля показывают расчёт участка, а не пустоту со значением «возьми
 // норматив»: человек пришёл править числа, которые видит, и ноль в поле
 // читался как «паркинга нет». Новый импорт ГлавАПУ перезаписывает пару.
 //
 // Но заполнить мало — надо сказать, ЧЬЁ это число. Прежде пара, заполненная
 // нормой при загрузке сохранённого проекта, дальше читалась как решение
 // человека: строка ТЭП подписывалась «Задано проектом», правка квартир мест
 // не двигала, а вернуть поле к норме можно было только вписав норму руками —
 // и тогда оно запиралось снова. Владелец, 13.09.2026: «когда я поменял ТЭПы
 // после расчёта, машиноместа не будут двигаться? Это неверно».
 //
 // Пометка — та же, что у паркинга объектов, и списки те же: тронутое руками
 // норма не трогает, своё число она обновляет вместе с ТЭП.
 if(inputs.underground_parking_disabled||withoutHousing())return false;
 const spaces=Number(inputs.underground_manual_spaces||0);
 const area=Number(inputs.underground_manual_gns_sqm||0);
 const p=parkingRequirement();
 if(!p||!(p.spaces>0))return false;
 const per=undergroundAreaPerSpace();
 const wantSpaces=Math.round(p.spaces);
 const wantArea=Math.round(p.gns||p.spaces*per);
 if(parkingByHand(PROJECT_PARKING_KEY)){
  // Замок держит, пока норма та же, при которой число вписали. Поменяли ТЭП —
  // норма другая, и пара возвращается к ней: дальше человек правит заново.
  // Замок без записанной нормы (проект до этой правки) получает её сейчас.
  const pinned=Number(inputs._underground_hand_norm||0);
  if(pinned<=0){inputs._underground_hand_norm=wantSpaces;return false}
  if(pinned===wantSpaces)return false;
 }
 // Проект, сохранённый до этой правки, пометок не несёт вовсе, и разобрать по
 // ним нечего. Зато есть сравнение — то же, что у `reconcileLegacyParking`:
 // пара, равная норме на ТЕХ ЖЕ вводных, поставлена нормой, другого объяснения
 // совпадению до единицы нет; несовпадающая — человеческая, и её не трогаем.
 // Пустая пара — тоже нормина: ноль означал «взять норматив».
 if(!parkingByNorm(PROJECT_PARKING_KEY)&&!parkingByHand(PROJECT_PARKING_KEY)&&(spaces>0||area>0)){
  const mine=(spaces===wantSpaces)||(spaces<=0&&area===wantArea);
  if(!mine){markParkingByHand(PROJECT_PARKING_KEY);return false}
 }
 markParkingByNorm(PROJECT_PARKING_KEY);
 if(spaces===wantSpaces&&area===wantArea)return false;
 inputs.underground_manual_spaces=wantSpaces;
 inputs.underground_manual_gns_sqm=wantArea;
 return true;
}

function undergroundShortfallNote(){
 // Места ГлавАПУ — норматив обеспеченности, а не пожелание: если ручная
 // площадь вмещает меньше, это расхождение с требованиями, и человек должен
 // видеть его сразу, а не узнавать на согласовании.
 const manualSpaces=Number(inputs.underground_manual_spaces||0);
 const manualArea=Number(inputs.underground_manual_gns_sqm||0);
 const off=!!inputs.underground_parking_disabled;
 if(!off&&manualSpaces<=0&&manualArea<=0)return '';
 const required=parkingRequirement();
 if(!required)return '';
 // При отказе норматив закрывает наземный паркинг — его места идут в зачёт.
 const above=STANDALONE_OBJECTS.filter(o=>o.measure==='spaces')
  .reduce((sum,o)=>sum+(inputs[o.prefix+'_enabled']?Number(inputs[o.prefix+'_spaces']||0):0),0);
 const fact=(off?0:(manualSpaces>0?manualSpaces:Math.round(manualArea/undergroundAreaPerSpace())))+(off?above:0);
 if(fact>=required.spaces)return '';
 return 'В проекте '+fact+' м/м, потребность по норме — '+required.spaces+
        ' м/м ('+(required.basis||'')+'): не хватает '+(required.spaces-fact)+'.';
}


function renderProjectClassPreview(){
 const select=document.getElementById('projectClassSelect');
 const key=select?select.value:(inputs.project_class||'comfort');
 const p=PROJECT_CLASS_PRESETS[key];
 const box=document.getElementById('projectClassPreview');
 if(!box)return;
 if(!p){
   box.textContent='Пользовательские значения';
   return;
 }
 // Подпись называет то, что класс двигает ЗДЕСЬ. В нежилом проекте квартир и
 // машино-мест МКД нет, а «Кв/комм 650 · м/м 5 000» стояло по-прежнему —
 // «почему активен блок класса?» (владелец, 21.09.2026). Селектор активен
 // законно, врала подпись.
 //
 // Двигает класс ровно три числа, и они измерены: цену метра ОСЗ
 // (450 / 650 / 1 500), цену машино-места гаража объекта (1 500 / 5 000 /
 // 20 000) и подземную ставку СМР (88 / 152 / 240), по которой этот гараж
 // строится. При цене офисов, зафиксированной на 450 у всех трёх классов,
 // выручка всё равно идёт 3 794,8 → 4 901,0 → 9 642,2 млн ₽, и вся разница
 // в гараже: 474,1 против 6 321,6 млн.
 //
 // НАЗЕМНУЮ ставку класса подпись не называет: себестоимость самого здания —
 // своя ставка объекта (`offices_cost_th_per_sqm`), и 190/152 к ней не
 // применяются вовсе («у нас же там нет 190/152 в принципе», владелец
 // 21.09.2026). С 27.09.2026 класс двигает и её — шкалой класса офиса
 // 175 / 200 / 225, и подпись называет четвёртое число.
 // Класс проекта — это и класс офисника (владелец, 27.09.2026): подпись
 // называет его и себестоимость здания офиса, которую класс теперь двигает.
 const office=OFFICE_CLASS_BY_PROJECT_CLASS[key];
 const officeText=office&&(isNonResidential()||inputs.offices_enabled)
  ? ` · офисы класса ${office.office_class}, здание офиса ${classValue(key,'offices_cost_th_per_sqm').toLocaleString('ru-RU')}`
  : '';
 box.textContent=isNonResidential()
  ? `Офисы/ТЦ ${classValue(key,'offices_price_th_per_sqm').toLocaleString('ru-RU')} · м/м ${classValue(key,'parking_price_th').toLocaleString('ru-RU')} · подземные ${classValue(key,'main_under_th_per_sqm').toLocaleString('ru-RU')}${officeText} тыс. ₽`
  : `Кв/комм ${classValue(key,'apartment_price_th').toLocaleString('ru-RU')} · м/м ${classValue(key,'parking_price_th').toLocaleString('ru-RU')} · себес. ${classValue(key,'main_above_th_per_sqm').toLocaleString('ru-RU')}/${classValue(key,'main_under_th_per_sqm').toLocaleString('ru-RU')}${officeText} тыс. ₽`;
}

// Число профиля класса, вписанное руками, — решение человека, и смена класса
// его молча не затирает (инвариант «ручное не подменяется расчётным»). Прежде
// правку помнили пять полей из литерала — цены квартир, коммерции, машино-места
// и две ставки СМР, — а цену офисов, благоустройство, нормативы паркинга и
// кладовую следующий выбор класса перезаписывал без слова. Правило одно:
// поле профиля, изменённое руками, помечается вписанным. Список полей — сам
// профиль (`classSetsField`), а не перечисление рядом с ним.
function classManualKeys(){
 return Array.isArray(inputs._class_manual)?inputs._class_manual.filter(classSetsField):[];
}
function markClassManual(k){
 if(!classSetsField(k))return false;
 const list=classManualKeys();
 if(!list.includes(k))list.push(k);
 inputs._class_manual=list;
 // Новая правка отменяет прежнее происхождение: число, набранное поверх
 // рекомендации, — уже не рекомендация.
 if(inputs._class_manual_source&&typeof inputs._class_manual_source==='object')delete inputs._class_manual_source[k];
 return true;
}
function isClassManual(k){return classManualKeys().includes(k)}
// Не класс и не пальцы: число поставил источник (рекомендация DevelopAid по
// рынку). Как и ручное, смена класса его не затирает, но у поля названо, откуда
// оно, — иначе значение рекомендации после сохранения выглядело бы набранным.
// Происхождение держится, пока в поле стоит именно это число.
function markClassFieldSource(k,value,by){
 if(!markClassManual(k))return false;
 const map=inputs._class_manual_source&&typeof inputs._class_manual_source==='object'?inputs._class_manual_source:{};
 map[k]={value:Number(value),by:String(by||'')};
 inputs._class_manual_source=map;
 return true;
}
function classFieldSource(k){
 const s=inputs._class_manual_source&&inputs._class_manual_source[k];
 if(!s||!s.by||!isClassManual(k))return '';
 return Math.abs(Number(inputs[k])-Number(s.value))<1e-9?String(s.by):'';
}
// Что включает ставка объекта, зависит от вида проекта (`object_rate_hint`):
// группы полей несут приписку смешанного проекта, здесь она меняется на
// приписку текущего вида. Своего правила у страницы нет — только карта движка.
const OBJECT_RATE_HINTS=__DEVELOPAID_OBJECT_RATE_HINTS__;
function objectRateUnit(id,unit){
 // Подземная ставка у нежилого проекта строит свой гараж объектов — других
 // подземных метров у него нет, и подпись это говорит.
 if(id==='main_under_th_per_sqm'&&inputs.project_kind==='nonresidential')
  return String(unit)+' — свой подземный гараж объектов';
 const hints=OBJECT_RATE_HINTS[id];
 if(!hints)return unit;
 const own=hints[inputs.project_kind]||hints.mixed;
 return own===hints.mixed?unit:String(unit).replace(hints.mixed,own);
}
// Чисто нежилой проект: ставки СМР вводятся в ОДНОМ месте — в блоке
// «Строительство», рядом с подземной ставкой и статьями проекта (владелец,
// 07.10.2026: «два одинаковых блока в разных местах — как понять, куда и что
// вводить?»). Число — то же поле объекта (`{prefix}_cost_th_per_sqm`): оно
// только переезжает на экране, расчёт и книги читают его, как прежде. Объект
// один — строка «наземная часть», объектов несколько — строка на каждый.
// Объект «под ключ» (наземный паркинг, ставка за место) остаётся в своём
// блоке: его ставка — не СМР здания (`OBJECT_SMR.defaults` — только СМР).
function nonresBuildingRateFields(){
 if(!isNonResidential())return [];
 const objs=projectObjects().filter(o=>inputOn(inputs[o.prefix+'_enabled'])
  &&Object.prototype.hasOwnProperty.call(OBJECT_SMR.defaults,o.prefix+'_cost_th_per_sqm'));
 return objs.map(o=>{
  const key=o.prefix+'_cost_th_per_sqm';
  let unit='тыс. ₽/м² GBA';
  for(const g of allFieldGroups())for(const f of g[1])if(f[0]===key)unit=f[2];
  const label='Основное строительство — наземная часть'
   +(objs.length>1?', '+(o.tep_label||o.label||o.group_label):'');
  return [key,label,unit,'number'];
 });
}
function movedToConstruction(id){
 return isNonResidential()&&Object.prototype.hasOwnProperty.call(OBJECT_SMR.defaults,String(id));
}
function classFieldUnitText(id,unit){
 unit=objectRateUnit(id,unit);
 // Площадь сноса и выкуп, найденные по контуру КРТ, подписаны своим
 // происхождением, пока число в поле то же, что положил контур; исправленное —
 // уже ручное. Проверка внутри, а не своей функцией: стенды страницы собирают
 // `classFieldUnitText` по имени, и новое имя рядом роняло бы их все.
 const krtSource=id==='demolition_area_sqm'?inputs._demolition_source:(id==='land_buyout_mln'?inputs._land_buyout_source:null);
 if(krtSource&&krtSource.by&&Math.abs(Number(inputs[id])-Number(krtSource.value))<0.05)
  return unit+' · '+krtSource.by+(krtSource.warn?' · ВНИМАНИЕ: '+krtSource.warn:'')
   +(id==='demolition_area_sqm'?' — исправьте, если здание сохраняется':' — вписанное руками сильнее');
 if(!classSetsField(id))return unit;
 if(!isClassManual(id))return unit+' · ставит класс проекта, правится в «Настройках класса»';
 return unit+' · '+(classFieldSource(id)||'вписано руками')+' — смена класса его не затрёт';
}
// Подпись у единицы без перерисовки вводных: перерисовка снесла бы соседние
// с полем узлы — например, ответ кнопки рекомендации.
// Единица — из объявления поля (`FIELD_GROUPS`), как её берёт и `renderInputs`.
function refreshClassFieldUnit(id){
 const span=document.querySelector('.field[data-field="'+id+'"] > label > .unit');
 if(!span)return;
 for(const grp of allFieldGroups())for(const f of grp[1])if(f[0]===id){span.textContent=classFieldUnitText(id,f[2]);return}
}

function applyProjectClassPreset(selectedKey){
 const select=document.getElementById('projectClassSelect');
 const key=selectedKey||(select?select.value:'comfort');
 const p=PROJECT_CLASS_PRESETS[key];
 if(!p){inputs.project_class='custom';renderProjectClassPreview();return;}
 // Вписанное руками, что класс поменял бы, называется поимённо, и решает
 // человек: заменить значениями класса или оставить своё. Без окна (стенд,
 // встроенный вид) — оставить: молча терять ручное хуже, чем не поставить класс.
 const manualAll=classManualKeys().filter(k=>Object.prototype.hasOwnProperty.call(p,k)
   &&isFinite(Number(inputs[k]))&&Math.abs(Number(inputs[k])-classValue(key,k))>1e-9);
 // О вписанном у экземпляра вне проекта не спрашиваем — его в проекте нет, — но
 // и не затираем: добавят объект снова, и число человека вернётся с ним.
 const manual=manualAll.filter(fieldInProject);
 const hiddenManual=manualAll.filter(k=>!fieldInProject(k));
 let keep=hiddenManual.slice();
 if(manual.length){
  const lines=manual.map(k=>`${classFieldLabel(k)}: ${Number(inputs[k]).toLocaleString('ru-RU')} → ${classValue(key,k).toLocaleString('ru-RU')}`).join('\n');
  const ask=typeof window!=='undefined'&&typeof window.confirm==='function'?window.confirm.bind(window):null;
  const replace=ask?ask(`Класс «${p.label||key}» заменит числа, вписанные руками:\n${lines}\n\nОК — заменить значениями класса.\nОтмена — оставить вписанные руками.`):false;
  if(replace)inputs._class_manual=classManualKeys().filter(k=>!manual.includes(k));
  else keep=keep.concat(manual);
 }
 inputs.project_class=key;
 // Личная перекрышка сильнее общей базы: применяется значение человека,
 // а отклонение от ОБЩЕЙ базы по-прежнему считает сервер и печатает в PDF.
 // Список полей — сам пресет: поле, добавленное в профиль класса позже,
 // применяется без правки здесь.
 // Профиль класса перестал быть только деньгами: в нём живут физические
 // нормативы — метры на машино-место, метры двора на человека, площадь
 // кладовой. Поля писались напрямую, мимо всех пересчётов, и производные за
 // ними не шли: класс менял норматив 35 → 37,5, а площадь паркинга стояла
 // прежней («ничего не меняется в блоке машиномест», владелец, 14.09.2026).
 //
 // `parkingByHand` на этот вопрос не отвечает и отвечать не должен: он про
 // пару целиком — «норма её не трогает», — а здесь спрашивают, КОТОРУЮ из
 // двух половин задал человек. Вписал места, а метры посчитала пара — метры
 // производные, и за новым нормативом идти обязаны; вписал пятно застройки —
 // оно смену класса переживает. Различает их сама пара: производная равна
 // «места × ПРЕЖНИЙ норматив», у вписанной равенства нет.
 const wasPer=undergroundAreaPerSpace();
 const wasStoragePer=storageAreaPerUnit();
 Object.keys(p).filter(k=>k!=='label'&&!keep.includes(k)).forEach(k=>inputs[k]=classValue(key,k));
 (function(){
  // Норматив не двинулся — двигать нечего, и лишний пересчёт только затёр бы
  // пару там, где класс к ней отношения не имеет.
  if(undergroundAreaPerSpace()!==wasPer){
   const spaces=Number(inputs.underground_manual_spaces||0);
   const area=Number(inputs.underground_manual_gns_sqm||0);
   if(spaces>0&&Math.abs(area-spaces*wasPer)<1)syncUndergroundPair('underground_manual_spaces');
  }
  // Кладовые признака «руками» не имеют вовсе: штуки и метры там связаны
  // всегда — правка любой считает вторую, — значит после смены норматива
  // метры идут за штуками так же, как при правке ячейки.
  if(storageAreaPerUnit()!==wasStoragePer){
   const units=Number((tep.storage||{}).units||0);
   if(units>0)syncStoragePair('units');
  }
 })();
 syncTep(false);
 renderInputs();
 renderTep();
 if(document.getElementById('projectClassSelect'))document.getElementById('projectClassSelect').value=key;
 renderProjectClassPreview();
 calculate();
}

// --- Тип проекта -------------------------------------------------------------
// Состав объявлен в движке и приезжает подстановкой: копию негде обновлять,
// потому что копии нет. То же правило, что у VERSION, FIELD_GROUPS и долей ТЭП.
const PROJECT_KINDS=__DEVELOPAID_PROJECT_KINDS__;
// Что принадлежит жилью и в нежилом проекте не живёт. Тот же список читает
// движок, когда ищет оставшееся: два перечисления разошлись бы, и «режим
// включён» значило бы на экране одно, а в расчёте другое.
const NONRESIDENTIAL_CLEARED=__DEVELOPAID_NONRESIDENTIAL_INPUTS__;

function projectKind(){
 const v=String(inputs.project_kind||'mixed');
 return PROJECT_KINDS.some(p=>p[0]===v)?v:'mixed';
}
function isNonResidential(){return projectKind()==='nonresidential'}
function isHotel(){return projectKind()==='hotel'}
// Проект без жилья: нежилой или гостиничный. Один ответ на «считается ли
// дом», как у движка (`without_housing`): обнуление МКД, замок строк ТЭП и
// пометка жилых полей у обоих типов одни и те же.
function withoutHousing(){return projectKind()!=='mixed'}
// Где стоит выбор типа. Отвечает одно место: в этой разметке — шапка, а слой
// `/ia`, переставляя список на шаг «Участок», переназначает ответ здесь же.
// Подсказки у запертых жилых полей и строк ТЭП читают его, а не пишут место
// своей копией: копия осталась бы «в шапке», когда список уже уехал.
let PROJECT_KIND_WHERE='в шапке';
function projectKindWhereNote(){return 'Тип проекта — '+PROJECT_KIND_WHERE+'.'}
// Подземный паркинг жилого дома. В нежилом проекте его поля заперты, и
// подсказка обязана сказать, ГДЕ вводятся места объекта: «это жильё» читалось
// как «паркинг пропал», и места офиса казалось негде ввести (владелец).
// Принадлежность — группой «Подземный паркинг» из FIELD_GROUPS движка, а не
// своим перечнем ключей.
function isResidentialParkingField(id){
 const group=FIELD_GROUPS.find(g=>g[0]==='Подземный паркинг');
 return !!group&&group[1].some(f=>f[0]===id);
}
function clearedHousingNote(id){
 if(isResidentialParkingField(id)){
  return 'Это подземный паркинг жилого дома (МКД): в проекте «'+escapeHtml(projectKindLabel(projectKind()))
   +'» он не считается.'+(isHotel()?'':' Места объекта вводятся выше, в блоке «Паркинг объекта».')
   +' '+projectKindWhereNote();
 }
 return 'Проект «'+escapeHtml(projectKindLabel(projectKind()))+'»: это жильё, и в расчёт оно не идёт. '+projectKindWhereNote();
}
// Подпись типа берётся из того же списка, что и селектор: вторая копия
// слова разошлась бы с ним молча, и кнопка звала бы режим не тем именем,
// каким он назван в шапке.
function projectKindLabel(kind){
 const row=PROJECT_KINDS.find(p=>p[0]===kind);
 return row?row[1]:'';
}

// Обнуляет жильё и ВОЗВРАЩАЕТ список убранного. Молчаливое обнуление врёт не
// меньше молчаливого сохранения: правило выведено на плате за ВРИ в режиме
// КРТ и здесь то же. Убранное запоминается — переключение по ошибке иначе
// уничтожает набранное безвозвратно.
//
// Зовётся она не только переключателем, а КАЖДЫМ пересчётом ТЭП, и потому
// дополняет прежнее, а не переписывает его. Режим был разовым действием:
// строки обнулялись в момент нажатия, а следующий писатель возвращал их
// молча — выгрузка ГлавАПУ ставила подземный паркинг по жилому нормативу
// участка, кнопка «Сформировать ТЭП по новым параметрам» раскладывала СПП
// по квартирам и встроенной коммерции (15 397 и 983 м² на участке 0,546 га),
// и убрать это человек не мог: ячейки заперты, полей на экране нет.
function clearResidentialInputs(){
 const saved=inputs._nonres_saved||{};
 saved.inputs=saved.inputs||{};saved.tep=saved.tep||{};
 const removed=(inputs._nonres_cleared||[]).slice();
 const say=text=>{if(removed.indexOf(text)<0)removed.push(text)};
 const cols=['gns','total_area','useful','saleable','transfer','units'];
 MKD_PRODUCTS.forEach(key=>{
  const row=tep[key];if(!row)return;
  if(!cols.some(c=>Number(row[c]||0)>0))return;
  // Убранное первым — решение человека, убранное потом — работа писателя,
  // который о режиме не знал. Запоминаем первое: возврат к жилому типу
  // обязан вернуть набранное, а не последнюю догадку калькулятора.
  if(!saved.tep[key]){saved.tep[key]={};cols.forEach(c=>{saved.tep[key][c]=row[c]})}
  cols.forEach(c=>{row[c]=0});
  say(productName(key));
 });
 Object.keys(NONRESIDENTIAL_CLEARED).forEach(k=>{
  const was=Number(inputs[k]||0);
  if(!(was>0))return;
  if(saved.inputs[k]===undefined)saved.inputs[k]=was;
  inputs[k]=0;
  say(NONRESIDENTIAL_CLEARED[k]+' '+num(was));
 });
 // Пара «места ↔ площадь» подземного паркинга после обнуления идёт за нормой,
 // а норма без квартир — ноль. Оставленный признак «задано руками» запер бы
 // ноль как решение человека, которого он не принимал.
 markParkingByNorm(PROJECT_PARKING_KEY);
 inputs._nonres_saved=saved;
 inputs._nonres_cleared=removed;
 return removed;
}

// Ставка двора — не уборка, а подстановка, и потому стоит отдельно: её ставит
// ПЕРЕКЛЮЧАТЕЛЬ, один раз. Зовись она из пересчёта, очищенное человеком поле
// возвращалось бы к нашему числу на первой же правке ТЭП — то есть режим
// перебивал бы его решение молча.
// Ставку двора режим больше НЕ ставит: двор нежилого проекта входит в
// себестоимость объекта («у нас себестоимость вообще всего объекта же целиком
// прописана», владелец 21.09.2026). Прежде поставленное — снимаем: мы сами
// его и поставили, и проект, переключённый до этой правки, иначе остался бы
// считать статью, которой в методике больше нет. Вписанное человеком не
// трогаем — оно сильнее методики в любом режиме.
function placeNonResidentialDefaults(){
 const saved=inputs._nonres_saved||{inputs:{},tep:{}};
 if(saved.landscaping_rate
    &&Number(inputs.landscaping_gns_th_per_sqm||0)===Number(saved.landscaping_rate)){
  inputs.landscaping_gns_th_per_sqm=0;
 }
 delete saved.landscaping_rate;
 inputs._nonres_saved=saved;
 inputs._nonres_placed=[];
 return [];
}

// Возвращает ровно то, что убрал режим. Восстановление — не автоматическое:
// человек нажимает сам, иначе возврат к жилому типу молча дорисовал бы
// проекту метры, которых он в этот раз не заказывал.
function restoreResidentialInputs(){
 const saved=inputs._nonres_saved||{};
 Object.keys(saved.tep||{}).forEach(key=>{
  if(!tep[key])return;
  Object.keys(saved.tep[key]).forEach(c=>{tep[key][c]=saved.tep[key][c]});
 });
 Object.keys(saved.inputs||{}).forEach(k=>{inputs[k]=saved.inputs[k]});
 if(Object.keys(saved.inputs||{}).length)markParkingByHand(PROJECT_PARKING_KEY);
 // Снимаем ТОЛЬКО своё: перебитая руками ставка принадлежит человеку, и
 // возврат к жилому типу не вправе стереть его число.
 if(saved.landscaping_rate&&Number(inputs.landscaping_gns_th_per_sqm||0)===saved.landscaping_rate){
  inputs.landscaping_gns_th_per_sqm=0;
 }
 delete inputs._nonres_saved;delete inputs._nonres_cleared;delete inputs._nonres_placed;
 syncTep(false);renderInputs();renderTep();refreshGroupPeeks();calculate();
}

function projectKindHasSaved(){
 const saved=inputs._nonres_saved||{};
 return Object.keys(saved.inputs||{}).length>0||Object.keys(saved.tep||{}).length>0
  ||!!saved.landscaping_rate;
}

// Имена блоков, где задаются метры объектов, берутся из САМИХ групп вводных:
// написанные здесь руками, они разошлись бы с экраном молча — так уже уезжали
// имена статей расходов и подписи продуктов.
function objectGroupTitles(){
 const keys=STANDALONE_OBJECTS.map(o=>o.prefix+(o.measure==='spaces'?'_spaces':'_gba_sqm'));
 const out=[];
 (FIELD_GROUPS||[]).forEach(group=>{
  const title=group[0],fields=group[1]||[];
  if(fields.some(f=>keys.indexOf(f[0])>=0))out.push(title);
 });
 return out;
}

// Что случилось при переключении — одним окном. Собирается из тех же
// `_nonres_cleared` и `_nonres_placed`, что читает плашка: два текста об одном
// событии разошлись бы, и оба выглядели бы верными.
function projectKindDialogHtml(){
 const cleared=inputs._nonres_cleared||[],placed=inputs._nonres_placed||[];
 if(isHotel()){
  let html='<p style="margin:0 0 10px">Квартиры, встроенная коммерция, кладовые и подземный паркинг МКД '
   +'обнулены и заперты; соцнагрузка, плата за смену ВРИ и объекты (ТЦ, офисы, паркинг, ФОК) не считаются.</p>';
  if(cleared.length)html+='<p style="margin:0 0 10px"><b>Убрано:</b> '+escapeHtml(cleared.join(', '))+'.</p>';
  html+='<p style="margin:0 0 10px"><b>Где теперь задавать гостиницу:</b> вкладка «Экономика», блок «Гостиница»: '
   +'номера, площадь и стоимость здания, ADR, загрузка, доли USALI, кредит и выход. Числа эталонных моделей '
   +'подставляются только кнопкой ориентира и помечаются происхождением; пустое поле расчёт называет, а не считает нулём.</p>';
  html+='<p style="margin:0">Финансирование — своё у гостиницы: обычный кредит (КС + спред) или льготный по госпрограмме '
   +'(доля КС + маржа). БРИДЖа, ПФ и эскроу у неё нет.</p>';
  return html;
 }
 const groups=objectGroupTitles();
 let html='<p style="margin:0 0 10px">Квартиры, встроенная коммерция, кладовые и подземный '
  +'паркинг МКД обнулены и заперты. Соцнагрузка и плата за смену ВРИ не считаются: первая идёт '
  +'от населения, вторая от СПП жилых зданий.</p>';
 if(cleared.length)html+='<p style="margin:0 0 10px"><b>Убрано:</b> '+escapeHtml(cleared.join(', '))+'.</p>';
 // Поставленную ставку двора окно НЕ называет: «это никому неинтересно и
 // никакой роли не играет — у нас себестоимость всего объекта целиком
 // прописана» (владелец, 21.09.2026). Молчаливой подстановка от этого не
 // становится: число объяснено там, где стоит, — подписью у самого поля
 // («деньги идут ставкой: 10 тыс ₽/м² ГНС × 19 110 м²»), и человек читает её
 // тогда, когда смотрит на ставку, а не когда переключает тип.
 html+='<p style="margin:0 0 10px"><b>Где теперь задавать метры:</b> вкладка «Экономика», блоки '
  +escapeHtml(groups.map(t=>'«'+t+'»').join(', '))+'. Строки ТЭП у них производные — считаются '
  +'по долям объекта.</p>';
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(area>0&&density>0){
  const spp=area*density;
  html+='<div style="margin:12px 0;padding:11px 12px;border:1px solid #d7e1ee;border-radius:8px;background:#f7f9fc">'
   +'<div><b>Потенциал участка: '+num(spp)+' м².</b> Куда положить ТЭП нежилого проекта?</div>'
   +'<div style="margin-top:8px">'
   +NONRES_DENSITY_TARGETS.map(t=>'<button type="button" class="btn" style="margin:0 6px 6px 0" '
     +'onclick="applyDensityToObjectFromDialog(\''+t[0]+'\')">'+escapeHtml(t[1])+'</button>').join('')
   +'</div>'
   +'<div style="font-size:11px;color:#667085">Выбор сразу запишет рассчитанный потенциал в объект. '
   +'Если метры хотите задать вручную — нажмите «Понятно» и заполните объект на вкладке «Экономика».</div>'
   +'</div>';
 }else{
  html+='<p style="margin:0 0 10px">Площадь участка или плотность пока не заданы, поэтому распределять '
   +'потенциал нечего. Их можно задать на шаге «ТЭП», а метры объекта — вручную на вкладке «Экономика».</p>';
 }
 html+='<p style="margin:0">Финансирование режим не трогает: 214-ФЗ нежильё не исключает, эскроу '
  +'и лестница ставки ПФ те же.</p>';
 return html;
}

function openProjectKindDialog(){
 const box=document.getElementById('projectKindDialogBody');
 const dialog=document.getElementById('projectKindDialog');
 if(!box||!dialog)return;
 const title=document.getElementById('projectKindDialogTitle');
 if(title)title.textContent=isHotel()?'Гостиничный проект':'Нежилой проект';
 box.innerHTML=projectKindDialogHtml();
 dialog.style.display='flex';
}

function closeProjectKindDialog(){
 const dialog=document.getElementById('projectKindDialog');
 if(dialog)dialog.style.display='none';
}

function applyDensityToObjectFromDialog(target){
 // Если человек выбирает нежилой тип на «Экономике», не отправляем его на
 // другую вкладку ради второго клика: выбор назначения ТЭП делается в том же
 // окне, которое сообщает последствия переключения.
 applyDensityToObject(target);
 closeProjectKindDialog();
}

// Отмена переключения целиком: тип возвращается ПЕРВЫМ, иначе пересчёт ТЭП,
// который зовёт `restoreResidentialInputs`, уберёт возвращённое сразу же —
// в нежилом режиме он на то и стоит.
function cancelNonResidential(){
 closeProjectKindDialog();
 applyProjectKind('mixed');
 restoreResidentialInputs();
}

// Надпись отвечает на три разных вопроса, и слить их нельзя: что считает
// режим сейчас, что он убрал и что лежит убранным у жилого проекта.
function projectKindNote(){
 const cleared=inputs._nonres_cleared||[],placed=inputs._nonres_placed||[];
 if(isHotel()){
  return '<div class="note" style="margin:0 0 12px;padding:11px 12px">'
   +'<b>Гостиничный проект.</b> Жильё, соцнагрузка, плата за смену ВРИ и объекты (ТЦ, офисы, паркинг, ФОК) '
   +'не считаются; гостиница — блок «Гостиница» ниже: номера, ADR, загрузка, USALI, свой кредит и выход. '
   +'<button type="button" class="tep-refill" onclick="openProjectKindDialog()">что отключено</button>'
   +'</div>';
 }
 if(isNonResidential()){
  return '<div class="note" style="margin:0 0 12px;padding:11px 12px">'
   +'<b>Нежилой проект.</b> Жильё, соцнагрузка и плата за смену ВРИ не считаются; метры '
   +'объектов задаются на вкладке «Экономика». '
   +'<button type="button" class="tep-refill" onclick="openProjectKindDialog()">что отключено</button>'
   +'</div>';
 }
 if(projectKindHasSaved()){
  return '<div class="note" style="margin:0 0 12px;padding:11px 12px">'
   +'Режим «'+escapeHtml(projectKindLabel('nonresidential'))+'» убирал жилые вводные'+(cleared.length?': '+escapeHtml(cleared.join(', ')):'')+'.'
   +(placed.length?' И ставил: '+escapeHtml(placed.join(', '))+'.':'')+' '
   +'<button class="btn" type="button" style="margin-top:8px" onclick="restoreResidentialInputs()">Вернуть убранное</button>'
   +'</div>';
 }
 return '';
}

function syncProjectKindSelector(){
 const select=document.getElementById('projectKindSelect');
 if(!select)return;
 if(!select.options.length){
  PROJECT_KINDS.forEach(pair=>{
   const o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];select.appendChild(o);
  });
 }
 select.value=projectKind();
 const box=document.getElementById('projectKindNoteTop');
 if(box)box.textContent=isHotel()?'номера, USALI, свой кредит':isNonResidential()?'жилья, соцнагрузки и ВРИ нет':'жильё, объекты, соцнагрузка';
 syncHotelClassSelector();
}

// Класс в шапке у гостиничного проекта — её звёздность (`hotel_stars`), а
// класс жилья прячется: его пресет — цены квартир, СМР, двор — у гостиницы
// ничего не считает. Значение одно на шапку и блок «Гостиница».
function syncHotelClassSelector(){
 const hotel=isHotel();
 const own=document.getElementById('projectClassBox'),box=document.getElementById('hotelClassBox');
 if(own)own.style.display=hotel?'none':'';
 if(box)box.style.display=hotel?'':'none';
 const select=document.getElementById('hotelClassSelect');
 if(!select)return;
 if(!select.options.length){
  const field=HOTEL.fields.find(f=>f.key==='stars');
  [['','— не задан —'],...(field?field.choices:[])].forEach(pair=>{
   const o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];select.appendChild(o);
  });
 }
 const v=inputs.hotel_stars;
 select.value=hotelBlank(v)?'':String(v);
}
function setHotelClass(value){
 setHotelField('stars',hotelBlank(value)?null:value,null);
 renderInputs();refreshGroupPeeks();calculate();
}

function applyProjectKind(key){
 const kind=PROJECT_KINDS.some(p=>p[0]===key)?key:'mixed';
 inputs.project_kind=kind;
 adoptObjectRateKind();
 if(kind!=='mixed'){clearResidentialInputs();placeNonResidentialDefaults()}
 syncTep(false);
 syncProjectKindSelector();
 renderInputs();
 renderTep();
 refreshGroupPeeks();
 calculate();
 // Окно после пересчёта: до него списки убранного и поставленного ещё не
 // полны — пересчёт ТЭП убирает и то, что вернули писатели.
 if(kind!=='mixed')openProjectKindDialog();
 else closeProjectKindDialog();
}

function syncProjectClassSelector(){
 const select=document.getElementById('projectClassSelect');
 if(!select)return;
 const key=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?inputs.project_class:'custom';
 select.value=key;
 renderProjectClassPreview();
}

// Значение этого поля ставит выбранный класс. Список — САМ ПРОФИЛЬ, а не
// перечисление рядом с ним: поле, добавленное в профиль позже, получает
// пометку тем, что оно там появилось. То же правило, по которому
// `applyProjectClassPreset` применяет `Object.keys(p)`, а не свой список.
// Спрашиваем «Комфорт»: он база профиля, и состав ключей у трёх классов
// один — расхождение состава ловит тест, а не эта строка. `custom` в
// `PROJECT_CLASS_PRESETS` нет вовсе, и это верно: профиля у него не бывает.
function classSetsField(k){
 const p=PROJECT_CLASS_PRESETS.comfort||{};
 return k!=='label'&&Object.prototype.hasOwnProperty.call(p,k);
}

// Подпись поля вне его группы: у поля объекта — с именем объекта («Стартовая
// цена — МФОЦ / офисы»). Карту считает движок тем же правилом, что строки
// отклонений в PDF; короткая подпись осталась только внутри своей группы.
const FIELD_LABELS_OUTSIDE=__DEVELOPAID_FIELD_LABELS_OUTSIDE__;
function classFieldLabel(k){if(FIELD_LABELS_OUTSIDE[k])return FIELD_LABELS_OUTSIDE[k];for(const g of allFieldGroups()){for(const f of g[1]){if(f[0]===k)return f[1]}}return k}
// Единицы полей класса считает движок и подставляет готовой картой — как
// PRODUCT_LABELS и доли ТЭП. Свой разрез подсказки на JS был бы второй
// реализацией одного правила, и разошлись бы они молча.
const CLASS_FIELD_UNITS=__DEVELOPAID_CLASS_UNITS__;
function classFieldUnit(k){return CLASS_FIELD_UNITS[k]||''}
// Разделы окна классов и подписи их строк — карта движка
// (`CLASS_DIALOG_SECTIONS`): раздел строки не угадывается по имени поля.
const CLASS_DIALOG=__DEVELOPAID_CLASS_DIALOG__;
// Личные значения классов — перекрышка поверх общей базы (решение владельца,
// 24.08.2026: база одна и общая, у человека может быть своя). Лежат на ядре
// рядом с проектами и действуют при следующем применении класса; отклонения
// проекта в PDF и книгах по-прежнему считаются от ОБЩЕЙ базы.
let CLASS_OVERRIDES=null;
let CLASS_OVERRIDES_NOTE='';
// База класса — для региона проекта: в МО цена нежилого без московского пола.
// Что в регионе отличается от профиля, считает движок (`class_base_preset`) и
// подставляет картой — своего правила цены нежилого у страницы нет.
const CLASS_REGION_BASES=__DEVELOPAID_CLASS_REGION_BASES__;
function classRegion(){return String(inputs.vri_region||'msk')==='mo'?'mo':'msk'}
function classBaseIn(region,c,k){
 const regional=((CLASS_REGION_BASES[region]||{})[c]||{})[k];
 return Number(regional!==undefined?regional:PROJECT_CLASS_PRESETS[c][k]);
}
function classBase(c,k){return classBaseIn(classRegion(),c,k)}
// Поле проекта идёт за классом, только пока в нём стоит число класса: число,
// вписанное руками или пришедшее импортом, остаётся своим. Одно правило для
// смены региона и для правки колонки текущего класса.
function followsClass(k,previous){
 return !isClassManual(k)&&isFinite(Number(inputs[k]))&&Math.abs(Number(inputs[k])-previous)<1e-9;
}
// Регион сменился — поля, чья база зависит от региона, идут за новой базой:
// иначе в МО стояла бы московская цена нежилого.
function followClassRegion(previousRegion){
 const cur=inputs.project_class;
 if(!PROJECT_CLASS_PRESETS[cur])return;
 const regional=new Set(Object.values(CLASS_REGION_BASES).flatMap(byClass=>Object.values(byClass).flatMap(Object.keys)));
 regional.forEach(k=>{
  const own=CLASS_OVERRIDES&&CLASS_OVERRIDES[cur]?Number(CLASS_OVERRIDES[cur][k]):NaN;
  if(isFinite(own)&&own>0)return;
  if(followsClass(k,classBaseIn(previousRegion,cur,k)))inputs[k]=classValue(cur,k);
 });
}
// Ставка метрового объекта в чисто нежилом проекте — СМР здания, а профиль
// класса и умолчания реестра — «под ключ» (решение владельца 06.10.2026).
// Перевод — коэффициенты движка (`object_smr_conversion`): S = (T − c) / m,
// округление до 0,1 тем же правилом, что у `object_smr_rate`.
const OBJECT_SMR=__DEVELOPAID_OBJECT_SMR__;
function objectSmrRate(turnkey,c){
 const conv=OBJECT_SMR.conversion[c]||OBJECT_SMR.custom;
 return Math.max(0,Math.floor((Number(turnkey)-conv[0])/conv[1]*10+0.5)/10);
}
function objectRateForKind(c,k,turnkey,kind){
 return kind==='nonresidential'&&Object.prototype.hasOwnProperty.call(OBJECT_SMR.defaults,k)
  ?objectSmrRate(turnkey,c):Number(turnkey);
}
function classValueForKind(c,k,kind){
 const own=CLASS_OVERRIDES&&CLASS_OVERRIDES[c]?Number(CLASS_OVERRIDES[c][k]):NaN;
 return objectRateForKind(c,k,isFinite(own)&&own>0?own:classBase(c,k),kind);
}
function classValue(c,k){return classValueForKind(c,k,projectKind())}
// Умолчание ставки объекта для вида проекта: число класса, если поле ставит
// класс, иначе умолчание реестра — оба переведены для нежилого.
function objectRateDefault(k,kind){
 const c=inputs.project_class;
 if(classSetsField(k)&&PROJECT_CLASS_PRESETS[c])return classValueForKind(c,k,kind);
 return objectRateForKind(c,k,OBJECT_SMR.defaults[k],kind);
}
// Вид проекта сменился — ставка объекта, стоящая на умолчании прежнего вида,
// идёт за умолчанием нового. Вписанное руками (или другое число) — своё.
function followObjectRateKind(previousKind,kind){
 Object.keys(OBJECT_SMR.defaults).forEach(k=>{
  if(isClassManual(k)||!isFinite(Number(inputs[k])))return;
  if(Math.abs(Number(inputs[k])-objectRateDefault(k,previousKind))<1e-9)
   inputs[k]=objectRateDefault(k,kind);
 });
}
// Под какой вид проекта положены умолчания ставок объектов — пометка
// `_object_rate_kind`. Её нет у проекта, сохранённого до 06.10.2026: тогда
// ставка везде значила «под ключ», то есть вид — смешанный. Одна функция на
// смену вида и на каждую загрузку состояния: нежилой проект, сохранённый с
// умолчанием «под ключ», получает умолчание СМР, а не считает 175 как СМР.
function adoptObjectRateKind(){
 const was=inputs._object_rate_kind||'mixed',now=projectKind();
 if(was!==now)followObjectRateKind(was,now);
 inputs._object_rate_kind=now;
}
function openClassDialog(){
 renderClassDialog();
 document.getElementById('classDialog').style.display='flex';
 loadClassOverrides();
 loadClassStats();
}
function closeClassDialog(){document.getElementById('classDialog').style.display='none'}
let CLASS_OVERRIDES_FROM_SERVER=false;
async function loadClassOverrides(){
 // Загружается не только из окна: применение класса из селектора обязано
 // брать личные значения и без открытых настроек, поэтому нас зовёт и
 // initProjects. Вошедший позже человек дозагружается при следующем вызове.
 if(CLASS_OVERRIDES_FROM_SERVER)return;
 if(!activeSession()&&!projectsAdminKey){
  // «Не проверили» и «не заполнено» — разные ответы: без входа хранилище не
  // спрашивается вовсе, и это называется вслух, а не выглядит как пустота.
  if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
  CLASS_OVERRIDES_NOTE='Свои значения классов сохраняются после входа через бота; сейчас правка живёт до перезагрузки страницы.';
  renderClassDialog();return;
 }
 try{
  const data=await projectsCall('/classes/overrides/get',{});
  CLASS_OVERRIDES=data.overrides||{};CLASS_OVERRIDES_NOTE='';
  CLASS_OVERRIDES_FROM_SERVER=true;
 }catch(e){
  if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
  CLASS_OVERRIDES_NOTE='Хранилище не ответило ('+(e.message||e)+') — сохранённые свои значения не показаны.';
 }
 renderClassDialog();
}
async function setClassBase(c,k,value){
 const num=Number(String(value).replace(/\s/g,'').replace(',','.'));
 const previous=classValue(c,k);
 if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
 if(!isFinite(num)||num<=0||Math.abs(num-classBase(c,k))<1e-9){
  // Пустое, мусор или ровно база — своего значения нет; выключатель
  // перекрышки — вернуть базу, отдельной кнопки не нужно.
  if(CLASS_OVERRIDES[c]){delete CLASS_OVERRIDES[c][k];if(!Object.keys(CLASS_OVERRIDES[c]).length)delete CLASS_OVERRIDES[c];}
 }else{
  (CLASS_OVERRIDES[c]=CLASS_OVERRIDES[c]||{})[k]=num;
 }
 // Правка колонки ТЕКУЩЕГО класса проекта сразу идёт в проект (решение
 // владельца, 28.09.2026): прежде число ждало повторного выбора класса, а
 // окно тем временем писало «всё соответствует». Вписанное в проект руками
 // не трогается; правка чужого класса проект не двигает.
 if(c===inputs.project_class&&followsClass(k,previous)){
  inputs[k]=classValue(c,k);
  renderInputs();
  calculate();
 }
 renderProjectClassPreview();
 renderClassDialog();
 if(!activeSession()&&!projectsAdminKey)return;
 try{await projectsCall('/classes/overrides/save',{payload:CLASS_OVERRIDES});}
 catch(e){CLASS_OVERRIDES_NOTE='Не сохранилось: '+(e.message||e);renderClassDialog();}
}
function renderClassDialog(){
 const box=document.getElementById('classDialogBody');if(!box)return;
 const classes=Object.keys(PROJECT_CLASS_PRESETS);
 // Строки экземпляров вне проекта не рисуются; их значения и перекрышки
 // остаются и вернутся строками, когда экземпляр добавят.
 const keys=Object.keys(PROJECT_CLASS_PRESETS[classes[0]]).filter(k=>k!=='label'&&fieldInProject(k));
 const cur=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?inputs.project_class:'custom';
 const confLabels={high:'высокое',medium:'среднее',limited:'ограниченное',pilot:'пилотное — источников мало',insufficient:'недостаточно данных'};
 const thous=v=>v==null?'—':(v/1000).toLocaleString('ru-RU',{maximumFractionDigits:1});
 let deviations=0;
 let owned=0;
 let html='<table style="width:100%;border-collapse:collapse;font-size:12px"><tr><th style="text-align:left;padding:6px 8px;border-bottom:1px solid #ddd">Поле</th>'+classes.map(c=>`<th style="text-align:right;padding:6px 8px;border-bottom:1px solid #ddd;${c===cur?'background:#eef4fb':''}">${PROJECT_CLASS_PRESETS[c].label}</th>`).join('')+'<th style="text-align:right;padding:6px 8px;border-bottom:1px solid #ddd">В проекте</th></tr>';
 // Строки идут разделами карты движка (`CLASS_DIALOG`), в её порядке. Поле
 // профиля, которого в карте нет, не пропадает: оно встаёт в раздел «без
 // раздела» с прежней подписью — видимая дыра карты, а не потерянная строка.
 // Справка о нормах ГОРОДА живёт рядом с нормативом, который она объясняет,
 // а не во «Вводных», где считают деньги (владелец, 16.09.2026: «нормы
 // логично вставить в настройки класса»), и в окне — строкой в конце
 // раздела благоустройства, а не под объектами ОСЗ внизу таблицы. Она про
 // Москву: в области 2152-ПП не писан, и там эта справка была бы неправдой.
 // Строкой таблицы она шириной с таблицу, а на телефоне таблица шире окна:
 // справка держится ширины видимой части окна (`cqw` от `classDialogBody`)
 // и прилипает к его левому краю, иначе подпись уезжает за край экрана.
 const norms=String(inputs.vri_region||'msk')==='msk'
  ? '<details class="note" style="margin:8px 0 0;padding:11px 12px;position:sticky;left:0;box-sizing:border-box;max-width:100cqw">'
 +'<summary style="cursor:pointer">Нормы озеленения города — справка, в расчёт не входит</summary>'
 +'<div style="margin-top:6px">Норматив двора выше — НАША ставка площади, а не норма '
 +'города. Город (2152-ПП, табл. 1.4.2, территория преобразования) требует 5,0 м²/чел. '
 +'озеленённых территорий ЖК, из них 3,5 — зелёные насаждения. С 18.08.2026 (2260-ПП) часть '
 +'нормы разрешено не добирать метрами, а платить деньгами в бюджет по решению ГЗК через '
 +'инфраструктурный договор: −15% при ОТОП ≥5 га, ООПТ или ООЗТ в радиусе 500 м; внутри '
 +'Садового кольца при участке 0,5–1 га — от 3,0 м²/чел., при участке меньше 0,5 га или '
 +'реконструкции без нового строительства — можно без озеленения вовсе. Модель платит полную '
 +'ставку всегда и компенсацию не считает: порядок её расчёта определит акт ДГП, а его нет. '
 +'Согласованное снижение вносится площадью двора во «Вводных».</div></details>'
  : '';
 let normsPlaced=false;
 const placed=new Set();
 const sections=CLASS_DIALOG.map(s=>({id:s.id,title:s.title,rows:s.rows.filter(r=>keys.includes(r.key))}));
 sections.forEach(s=>s.rows.forEach(r=>placed.add(r.key)));
 const loose=keys.filter(k=>!placed.has(k));
 if(loose.length)sections.push({id:'unmapped',title:'Без раздела — поле не внесено в карту окна',rows:loose.map(k=>({key:k,label:classFieldLabel(k)}))});
 for(const sec of sections){
 if(!sec.rows.length)continue;
 // Заголовок раздела — тёмная полоса крупнее строк, как в «Сравнении очередей».
 html+=`<tr class="class-section" data-section="${sec.id}"><th colspan="${classes.length+2}" style="text-align:left;padding:8px 10px 7px;font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fff;background:#111;border-top:12px solid #fff">${escapeHtml(sec.title)}</th></tr>`;
 for(const {key:k,label:rowLabel} of sec.rows){
  const actual=Number(inputs[k]);
  // Отклонение проекта меряется от ОБЩЕЙ базы — той же, что сервер печатает
  // в PDF и книгах; личная перекрышка эту сверку не подменяет.
  const base=cur!=='custom'?classBase(cur,k):null;
  const dev=base!=null&&isFinite(actual)&&Math.abs(actual-base)>1e-9;
  if(dev)deviations++;
  // Статья со сводом раскрывается в обоснование: источники, диапазон и
  // положение значения проекта. Экспертная ставка без ответа «почему такая»
  // и была тем «невнятным», ради которого блок переделан (владелец, 26.08.2026).
  const rowStats=classes.map(c=>classStatsRow(c,k));
  const hasStats=rowStats.some(Boolean);
  const unit=classFieldUnit(k);
  const unitCell=(unit?`<span style="color:#8a94a6;font-size:11px;white-space:nowrap">, ${escapeHtml(unit)}</span>`:'');
  const labelCell=(hasStats
   ?`<a href="#" onclick="toggleClassDetail('${k}');return false" title="Обоснование: источники, диапазон и положение вашего значения" style="color:inherit;text-decoration:none;border-bottom:1px dashed #b6c4d6">${escapeHtml(rowLabel)} <span style="color:#3b6db4">${CLASS_DETAIL_OPEN[k]?'▾':'▸'}</span></a>`
   :escapeHtml(rowLabel))+unitCell;
  html+=`<tr class="class-row" data-key="${k}" data-section="${sec.id}"><td style="padding:5px 8px;border-bottom:1px solid #f0f0f0">${labelCell}</td>`+classes.map(c=>{
   const own=Math.abs(classValue(c,k)-classBase(c,k))>1e-9;
   if(own)owned++;
   return `<td style="text-align:right;padding:3px 8px;border-bottom:1px solid #f0f0f0;${c===cur?'background:#f6f9fd':''}"><input type="number" value="${classValue(c,k)}" onchange="setClassBase('${c}','${k}',this.value)" title="${own?'Своё значение; общая база: '+classBase(c,k).toLocaleString('ru-RU'):'Общая база класса — своё значение можно вписать прямо сюда'}" style="width:84px;text-align:right;border:1px solid ${own?'#c98a1b':'#dfe4ea'};border-radius:5px;padding:3px 6px;font-size:12px;${own?'background:#fdf6e6;font-weight:600':''}"></td>`;
  }).join('')+`<td style="text-align:right;padding:3px 8px;border-bottom:1px solid #f0f0f0;white-space:nowrap"><input type="number" value="${isFinite(actual)?actual:''}" onchange="setClassRate('${k}',this.value)" style="width:92px;text-align:right;border:1px solid ${dev?'#b42318':'#d5dbe3'};border-radius:5px;padding:3px 6px;font-size:12px;${dev?'color:#b42318;font-weight:700':''}">${dev?' <span style="color:#b42318;font-weight:700">≠</span>':''}</td></tr>`;
  // Свод «Статистики» стоит строкой под той ставкой, к которой относится:
  // связь числа со ставкой видна на месте, а не выводится из соседней таблицы.
  if(hasStats){
   // База свода стоит в самой подписи, а не только в подсказке: у
   // благоустройства ставка класса меряет метр ДВОРА, а свод — метр ГНС, и
   // строчка «15» над строчкой «5,9» без имён баз читается как спор двух
   // чисел об одном («это существует одновременно!!?», владелец, 14.09.2026).
   // Подсказка тут не ответ — на телефоне её нет вовсе. Имя базы даёт сервер
   // (`unit_label`), второй список «что в чём меряется» разошёлся бы молча.
   const statsUnit=(rowStats.find(Boolean)||{}).unit_label;
   html+='<tr><td style="padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#3b6db4">свод „Статистики“, '
    +escapeHtml(statsUnit?String(statsUnit).replace('₽/м²','тыс ₽/м²'):'тыс ₽/м²')+'</td>'
    +classes.map((c,i)=>{
     const r=rowStats[i];
     if(!r)return '<td style="text-align:right;padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#999">—</td>';
     const v=Math.round(r.recommended_rub_m2/100)/10;
     const spread=(r.p25_rub_m2!=null&&r.p75_rub_m2!=null)?(r.p25_rub_m2/1000).toLocaleString('ru-RU',{maximumFractionDigits:1})+'–'+(r.p75_rub_m2/1000).toLocaleString('ru-RU',{maximumFractionDigits:1})+' тыс, ':'';
     // Свод с чужой базой остаётся на экране ориентиром и перестаёт быть
     // ссылкой: подставленный, он выглядит как годное число. Причину называет
     // сервер — второй список «что с чем сравнимо» разошёлся бы с первым.
     if(r.applyable===false){
      return '<td style="text-align:right;padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#8a94a6" '
       +'title="'+escapeHtml(r.not_applyable_reason||'базы не совпадают')+'">'
       +v.toLocaleString('ru-RU',{maximumFractionDigits:1})+'<span style="color:#c98a1b"> \u26a0</span></td>';
     }
     return '<td style="text-align:right;padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px">'
      +'<a href="#" onclick="setClassBase(\''+c+'\',\''+k+'\','+v+');return false" '
      +'title="Свод модуля «Статистика» для класса «'+PROJECT_CLASS_PRESETS[c].label+'»: разброс источников '+spread+'источников '+r.source_count+'. Клик подставит это число классу." '
      +'style="color:#3b6db4;text-decoration:none;border-bottom:1px dashed #9bb8dc">'+v.toLocaleString('ru-RU',{maximumFractionDigits:1})+'</a></td>';
    }).join('')
    +'<td style="border-bottom:1px solid #f0f0f0"></td></tr>';
  }
  if(hasStats&&CLASS_DETAIL_OPEN[k]){
   // Обоснование считается для текущего класса; «Пользовательский» смотрит
   // на первый класс списка — базы для него всё равно нет.
   const detailCls=(cur!=='custom'&&classStatsRow(cur,k))?cur:classes[rowStats.findIndex(Boolean)];
   const rec=classStatsRow(detailCls,k);
   if(rec){
    const srcRows=(rec.included_sources||[]).map(x=>`<div>· ${x.source} — ${x.grade_label||('грейд '+x.grade)}${x.reference_date?(', '+x.reference_date):''}: <b>${thous(x.value_rub_m2)}</b> тыс ₽/м² в приведении к нашей базе площади</div>`).join('');
    const mine=Number(inputs[k]);
    let pos='';
    if(isFinite(mine)&&rec.p25_rub_m2!=null&&rec.p75_rub_m2!=null){
     const lo=rec.p25_rub_m2/1000,hi=rec.p75_rub_m2/1000;
     const verdict=mine<lo?`ниже p25 рынка (${thous(rec.p25_rub_m2)})`:(mine>hi?`выше p75 рынка (${thous(rec.p75_rub_m2)})`:'в границах p25–p75 рынка');
     pos=`<div style="margin-top:3px">В проекте <b>${mine.toLocaleString('ru-RU')}</b> тыс ₽/м² — ${verdict}.</div>`;
    }
    html+=`<tr><td colspan="${classes.length+2}" style="padding:4px 10px 8px 22px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#555;background:#fbfcfe">Обоснование для класса «${PROJECT_CLASS_PRESETS[detailCls].label}»: свод <b>${thous(rec.recommended_rub_m2)}</b> тыс ₽/м², разброс p25–p75 ${thous(rec.p25_rub_m2)}–${thous(rec.p75_rub_m2)}, источников ${rec.source_count}, доверие — ${confLabels[rec.confidence]||rec.confidence}.${srcRows?'<div style="margin-top:3px">'+srcRows+'</div>':''}${pos}</td></tr>`;
   }
  }
 }
 if(sec.id==='norms'&&norms){
  html+=`<tr class="class-note" data-section="norms"><td colspan="${classes.length+2}" style="padding:0 0 8px;border-bottom:1px solid #f0f0f0">${norms}</td></tr>`;
  normsPlaced=true;
 }
 }
 box.innerHTML=html+'</table>'+(normsPlaced?'':norms);
 const note=document.getElementById('classDialogNote');
 const parts=[];
 if(cur==='custom')parts.push('Класс «Пользовательский»: базы для сверки нет — все ставки заданы проектом.');
 else if(deviations)parts.push(`<span style="color:#b42318;font-weight:600">Изменено против базы «${PROJECT_CLASS_PRESETS[cur].label}»: ${deviations} из ${keys.length} значений.</span> Отклонения печатаются в PDF и помечаются в книгах v4 и ПЛАТО.`);
 else parts.push(`Все значения соответствуют базе класса «${PROJECT_CLASS_PRESETS[cur].label}».`);
 if(owned)parts.push('<span style="color:#8a5a00">Янтарные ячейки — ваши значения классов:</span> они применяются при выборе класса вместо общей базы; вернуть базу — вписать её число (оно в подсказке ячейки).');
 if(CLASS_OVERRIDES_NOTE)parts.push('<span style="color:#8a5a00">'+CLASS_OVERRIDES_NOTE+'</span>');
 note.innerHTML=parts.join(' ');
 renderClassStats();
}
function setClassRate(k,value){
 const num=Number(value);
 if(!isFinite(num))return;
 inputs[k]=num;
 markClassManual(k);
 renderInputs();
 renderProjectClassPreview();
 renderClassDialog();
 calculate();
}

// --- свод строительной себестоимости из модуля «Статистика» -----------------
// Числа берутся у /api/statistics/cost-recommendation — того же, что страница
// «Статистика»: у свода не бывает двух жизней. В окне свод стоит строкой прямо
// под ставкой, к которой относится, — по числу на каждый класс; методика
// словами живёт за кнопкой «Как считаются класс и сценарий», а таблица
// источников — на своей странице (замечание владельца, 26.08.2026: внутренние
// правила модуля читателю ничего не объясняют, а свод отдельной таблицей не
// связывается со ставками класса).
let CLASS_STATS_BY=null;
let CLASS_STATS_ERROR='';
let CLASS_DETAIL_OPEN={};
function toggleClassDetail(k){CLASS_DETAIL_OPEN[k]=!CLASS_DETAIL_OPEN[k];renderClassDialog();}
function classStatsAreas(){
 // ТЭП проекта — чтобы ставки, опубликованные на продаваемый метр или общую
 // площадь здания, нормализовались на НАШИ площади, а не на условный пример.
 let gba=0,sell=0,under=0;
 for(const key in tep){
  const row=tep[key]||{};
  sell+=Number(row.saleable)||0;
  // Подземная и наземная — по правилам строки (`tepRowUnderGns`,
  // `tepRowAboveGns`), а общая площадь — их сумма: гараж один не был всей
  // подземной частью, и кладовые уходили в наземную ставку.
  const above=tepRowAboveGns(key,row),below=tepRowUnderGns(key,row);
  gba+=above+below;
  under+=below;
 }
 const areas={};
 if(gba>0)areas.gba_sqm=String(Math.round(gba));
 if(sell>0)areas.sellable_sqm=String(Math.round(sell));
 if(under>0)areas.underground_gns_sqm=String(Math.round(under));
 if(gba>under)areas.above_ground_gns_sqm=String(Math.round(gba-under));
 return areas;
}
// Свод спрашивается по региону проекта и на его площади; ключ запоминается,
// и окно, открытое после смены ТЭП или региона, спрашивает заново — прежде
// свод считался один раз и всегда по Москве.
let CLASS_STATS_KEY='';
function classStatsRegionName(){return classRegion()==='mo'?'Московская область':'Москва'}
async function loadClassStats(){
 const areas=classStatsAreas();
 const statsKey=JSON.stringify([classStatsRegionName(),areas]);
 if(CLASS_STATS_BY&&CLASS_STATS_KEY===statsKey)return;
 CLASS_STATS_BY=null;CLASS_STATS_KEY=statsKey;
 CLASS_STATS_ERROR='';
 const classes=Object.keys(PROJECT_CLASS_PRESETS);
 try{
  const answers=await Promise.all(classes.map(c=>{
   const params=new URLSearchParams(Object.assign({class:c,region:classStatsRegionName()},areas));
   return fetch('/api/statistics/cost-recommendation?'+params.toString())
    .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()});
  }));
  CLASS_STATS_BY={};
  classes.forEach((c,i)=>CLASS_STATS_BY[c]=answers[i]);
 }catch(e){CLASS_STATS_BY=null;CLASS_STATS_ERROR=String((e&&e.message)||e);}
 renderClassDialog();
}
function classStatsRow(c,k){
 const d=CLASS_STATS_BY&&CLASS_STATS_BY[c];if(!d)return null;
 const row=(d.recommendations||[]).find(r=>r.model_key===k);
 return row&&row.recommended_rub_m2!=null?row:null;
}
function renderClassStats(){
 const box=document.getElementById('classSourcesBody');if(!box)return;
 if(CLASS_STATS_ERROR){
  // Неответ модуля не показывается пустотой: строка свода молча исчезла бы,
  // и «не загрузилось» читалось бы как «свода нет».
  box.innerHTML='<div style="font-size:12px;color:#b42318">Свод модуля «Статистика» не загрузился ('+CLASS_STATS_ERROR+') — строки «свод „Статистики“» под ставками СМР не показаны.</div>';
  return;
 }
 if(!CLASS_STATS_BY){box.innerHTML='<div style="font-size:12px;color:#777">Загружаю свод модуля «Статистика»…</div>';return;}
 box.innerHTML='<div style="font-size:12px;color:#555">Строки «свод „Статистики“» — независимый ориентир себестоимости, посчитанный модулем «Статистика» из раскрытий источников рынка и наших данных на ТЭП этого проекта. <b>Данные — Москва и Московская область.</b> Клик по числу подставляет его классу; «Вставить данные из статистики» подставляет весь свод разом; клик по названию статьи раскрывает обоснование — источники с грейдами, диапазон рынка и положение вашего значения в нём. Как это считается — за кнопкой «Как считаются класс и сценарий»; таблица источников — на странице <a href="/statistics" target="_blank" style="color:#3b6db4">«Статистика»</a>.</div>';
}

// Поставить свои значения во все классы — одна кнопка, а снять их можно было
// только вручную, ячейка за ячейкой: восемь статей на три класса, до двадцати
// четырёх штук. Владелец нажал «Вставить данные из статистики», и правка базы
// класса перестала быть видна вовсе — своё значение сильнее базы и живёт на
// сервере, поэтому переживает выкатку (30.08.2026: «не сработало твоё 80
// процентов от наземной»). Кнопка, у которой нет обратной, — ловушка.
async function clearClassOverrides(){
 if(!CLASS_OVERRIDES||!Object.keys(CLASS_OVERRIDES).length){
  CLASS_OVERRIDES_NOTE='Своих значений классов нет — таблица и так на общих базах.';
  renderClassDialog();return;
 }
 CLASS_OVERRIDES={};
 renderProjectClassPreview();
 renderClassDialog();
 // Без входа хранилища нет: правка живёт до перезагрузки, и об этом уже
 // сказано в примечании под таблицей — второй раз не повторяем.
 if(!activeSession()&&!projectsAdminKey)return;
 try{await projectsCall('/classes/overrides/save',{payload:{}});}
 catch(e){CLASS_OVERRIDES_NOTE='Не сохранилось: '+(e.message||e);renderClassDialog();}
}

async function fillClassesFromStats(){
 // Кнопка «Вставить данные из статистики»: весь свод разом во все классы —
 // клики по числу остаются для точечной правки (владелец, 27.08.2026).
 if(!CLASS_STATS_BY){CLASS_OVERRIDES_NOTE='Свод ещё не загружен — попробуйте через пару секунд.';renderClassDialog();return;}
 if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
 const classes=Object.keys(PROJECT_CLASS_PRESETS);
 const keys=Object.keys(PROJECT_CLASS_PRESETS[classes[0]]).filter(k=>k!=='label');
 // Статья, у которой свод меряет не ту базу, что поле, пропускается — и
 // пропуск называется вслух: молча пропущенная читается как «свода по ней
 // нет», а подставленная молча уводит статью в шесть раз.
 const skipped={};
 for(const c of classes){
  for(const k of keys){
   const r=classStatsRow(c,k);
   if(!r)continue;
   if(r.applyable===false){skipped[k]=r.not_applyable_reason||'базы не совпадают';continue;}
   const v=Math.round(r.recommended_rub_m2/100)/10;
   if(!isFinite(v)||v<=0)continue;
   if(Math.abs(v-classBase(c,k))<1e-9){
    if(CLASS_OVERRIDES[c]){delete CLASS_OVERRIDES[c][k];if(!Object.keys(CLASS_OVERRIDES[c]).length)delete CLASS_OVERRIDES[c];}
   }else{
    (CLASS_OVERRIDES[c]=CLASS_OVERRIDES[c]||{})[k]=v;
   }
  }
 }
 const skippedKeys=Object.keys(skipped);
 CLASS_OVERRIDES_NOTE=skippedKeys.length
  ? ('Не подставлено: '+skippedKeys.map(k=>classFieldLabel(k)+' \u2014 '+skipped[k]).join('; ')+'.')
  : '';
 renderProjectClassPreview();
 renderClassDialog();
 if(!activeSession()&&!projectsAdminKey)return;
 try{await projectsCall('/classes/overrides/save',{payload:CLASS_OVERRIDES});}
 catch(e){CLASS_OVERRIDES_NOTE='Не сохранилось: '+(e.message||e);renderClassDialog();}
}


function applyTelegramCalcOverrides(){
 const o=telegramCalcOverrides||{};
 if(!Object.keys(o).length)return;
 if(o.project_class)inputs.project_class=String(o.project_class);
 const smr=Number(o.smr_th_per_sqm||0);
 if(smr>0){
  // Ставка СМР из диалога задаёт только сами СМР. Прежде вместе с ней
  // обнулялись благоустройство и резерв — считалось, что ставка их уже
  // включает. По одному и тому же проекту это давало CAPEX меньше на
  // 550 млн ₽, чем на сайте, и LLCR 1,12x против 1,07x: бот и сайт
  // расходились на ровном месте, хотя вводные совпадали.
  inputs.main_above_th_per_sqm=smr;
  inputs.main_under_th_per_sqm=smr;
 }
 // Правки Платона приходят настоящими именами полей модели. Список ключей был
 // фиксированным — три цены и СМР из диалога, — и всё остальное молча терялось:
 // ссылка на модель менялась, а открывалась она со старыми вводными.
 Object.keys(o).forEach(k=>{
  if(k==='project_class'||k==='smr_th_per_sqm')return;
  if(!(k in INPUT_DEFAULT))return;
  const d=INPUT_DEFAULT[k];
  if(typeof d==='number'){
   // Ноль — законное значение: Платон предлагает и цену покупки 0.
   const v=Number(o[k]);if(Number.isFinite(v))inputs[k]=v;
  }else if(typeof d==='boolean'){inputs[k]=!!o[k];}
  else{inputs[k]=String(o[k]);}
 });
}

// Запрос к своему серверу сорвался. Самая частая причина — включённый VPN:
// сведения ЕГРН запрашиваются с российского адреса, и с зарубежного выхода
// запрос до ядра не доходит. Раньше это выглядело как «участок не найден», и
// человек шёл проверять кадастровый номер, в котором ошибки не было.
const CONNECTION_HINT=' Не удалось связаться с сервером. Если включён VPN — '
 +'отключите его и повторите: сведения ЕГРН запрашиваются с российского адреса.';

const VRI_GROUP_NAME=__DEVELOPAID_VRI_GROUP_NAME__;

// Свёрнутая группа не должна быть закрытой дверью без таблички: в заголовке
// показываются два-три числа, по которым видно, надо ли туда заходить.
// Список короткий и явный — «первые два поля группы» дали бы шум там, где
// первым стоит служебное поле.
const GROUP_PEEK={
 'Продажи':['apartment_price_th','share_before_rve_pct'],
 'Строительство':['main_above_th_per_sqm','main_under_th_per_sqm'],
 'Коммерческие расходы и налоги':['marketing_pct','profit_tax_pct'],
 'Финансирование':['pf_spread_pp','pre_pf_own_funds_mln'],
 'Социальная нагрузка':['social_mode'],
 'МФОЦ / офисы':['offices_enabled','offices_gba_sqm'],
 'ТЦ / коммерция ОСЗ':['retail_enabled','retail_gba_sqm'],
 'Подземный паркинг':['underground_manual_spaces'],
 'Наземный паркинг':['above_parking_enabled','above_parking_spaces'],
 'ФОК / медцентр':['sports_enabled','sports_purpose','sports_gba_sqm']
};

function groupPeek(name,fields){
 const out=[];
 for(const id of (GROUP_PEEK[name]||[])){
  const f=fields.find(x=>x[0]===id);if(!f)continue;
  const [,,unit,type]=f;
  const v=(id in inputs)?inputs[id]:INPUT_DEFAULT[id];
  // Выключенный объект — исчерпывающая сводка: его площади ни о чём не говорят.
  if(type==='checkbox'){if(!v)return 'выключен';continue}
  if(v===''||v===null||v===undefined)continue;
  if(type==='number'){
   const n=Number(v);
   // Ноль в заголовке — это «не задано», а не сведение: показывать нечего.
   if(!Number.isFinite(n)||n===0)continue;
   out.push({text:num(n),unit:String(unit).split(';')[0].trim()});
  }else out.push({text:String(v),unit:''});
 }
 // Одинаковая единица у соседей печатается один раз: «110 · 120 тыс. ₽/м² ГНС».
 return out.map((part,i)=>{
  const next=out[i+1];
  return next&&next.unit===part.unit?part.text:(part.text+(part.unit?' '+part.unit:''));
 }).join(' · ');
}
// Вторые объекты — те же два числа, что у первого: включён ли и сколько.
STANDALONE_OBJECTS.forEach(o=>{
 if(!GROUP_PEEK[o.group_label])GROUP_PEEK[o.group_label]=
  [o.prefix+'_enabled',o.prefix+(o.measure==='spaces'?'_spaces':'_gba_sqm')];
});

// Табличка обязана поспевать за полем: правка внутри группы не всегда
// перерисовывает список, а устаревшее число в заголовке хуже пустого.
function refreshGroupPeeks(){
 refreshScheduleTotals();
 document.querySelectorAll('details[data-group]').forEach(det=>{
  const grp=FIELD_GROUPS.find(g=>g[0]===det.dataset.group);if(!grp)return;
  const sum=det.querySelector('summary');if(!sum)return;
  const text=groupPeek(grp[0],grp[1]);
  let hint=sum.querySelector('.group-peek');
  if(!text){if(hint)hint.remove();return}
  if(!hint){hint=document.createElement('span');hint.className='group-peek';sum.appendChild(hint)}
  hint.textContent=text;
 });
}

function renderInputs(){
 const box=document.getElementById('inputGroups');
 // Что было раскрыто и где стоял курсор — снимается ДО очистки узла.
 // Перерисовка зовётся не только при загрузке: ввод мест ДОО заставляет
 // `syncTep` дописать площадь и норматив во вводные, и это возвращает
 // «правда» — то есть перерисовку. Прежде она оставляла открытой только
 // первую группу, и «Социальная нагрузка» схлопывалась после КАЖДОГО
 // введённого числа, вместе с фокусом (владелец, 03.09.2026: «после каждого
 // ввода данных закрывает эту вкладку»). Открытое человеком — его решение,
 // и перерисовка его не отменяет.
 const wasOpen=new Set(Array.from(box.querySelectorAll('details[data-group]'))
   .filter(d=>d.open).map(d=>d.dataset.group));
 const active=document.activeElement;
 const focusId=active&&active.id?active.id:'';
 let caret=null;
 try{caret=active&&active.selectionStart!=null?active.selectionStart:null}catch(e){caret=null}
 box.innerHTML='';
 // Надпись режима стоит НАД полями: она объясняет, почему половина из них
 // заперта, и прочитать её надо до того, как человек начнёт их искать.
 box.innerHTML=projectKindNote();
 // Гостиничный проект: блок «Гостиница» стоит первым, а группы, которых он
 // не читает (продажи жилья, соцнагрузка, паркинги, объекты), не рисуются —
 // поле, правка которого ничего не меняет, не вводная.
 if(isHotel())box.appendChild(hotelInputsBlock(wasOpen));
 const vriBox=document.getElementById('vriInputGroups');if(vriBox)vriBox.innerHTML='';
 FIELD_GROUPS.forEach((grp,idx)=>{
   if(isHotel()&&HOTEL.hidden_groups.includes(grp[0]))return;
   const ownTab=grp[0]===VRI_GROUP_NAME&&vriBox;
   // Группа, у которой все поля уехали в «Настройки класса», не рисуется
   // вовсе: пустая складка «Кладовые» читается как продукт, у которого
   // вводных нет, а не как поле, переехавшее в соседнее окно. Считается это
   // СОСТАВОМ группы, а не её именем: группа, чьё последнее своё поле уедет
   // в класс завтра, исчезнет тем же правилом. Выход ДО создания узла —
   // наполовину нарисованная группа оставила бы пустую складку.
   if(!grp[1].some(f=>!notOnInputs(f[0])))return;
   // Блок типа объекта несёт все его экземпляры вкладками.
   const grpObj=OBJECT_BY_GROUP[grp[0]];
   // Открыта только первая группа. Одиннадцать развёрнутых групп — это
   // экран, на котором не видно, с чего начинать: человек листает поля
   // вместо того, чтобы ввести цену и сроки и посмотреть результат.
   // Первая группа открыта только при первой отрисовке: дальше решает то,
   // что человек раскрыл сам.
   const det=document.createElement('details');
   if(ownTab||(wasOpen.size?wasOpen.has(grp[0]):idx===0&&!isHotel()))det.open=true;
   det.dataset.group=grp[0];
   const sum=document.createElement('summary');sum.textContent=grp[0];
   const peek=groupPeek(grp[0],grp[1]);
   if(peek){const hint=document.createElement('span');hint.className='group-peek';hint.textContent=peek;sum.appendChild(hint)}
   det.appendChild(sum);
   let fields=grp[1];
   // У недублируемого типа (ФОК) вкладок и кнопки «Добавить объект» нет.
   if(grpObj&&grpObj.duplicable){
    const shown=objectTabObject(grpObj.key);
    det.dataset.object=shown.key;
    det.appendChild(objectTabsBar(grpObj.key,shown));
    fields=objectFields(shown);
   }
   // Поля объекта разбиты на смысловые блоки: каждый блок — отдельная
   // карточка с заголовком и своей сеткой полей внутри, и новая карточка
   // начинается там, где у поля сменился блок. Заголовок одной мелкой серой
   // строкой над общей сеткой форму не делил — она читалась прежним списком
   // (владелец, 27.09.2026). Порядок полей сгруппирован движком — страница
   // его не пересобирает.
   let grid=null,section=null;
   const openGrid=(parent)=>{grid=document.createElement('div');grid.className='fields';(parent||det).appendChild(grid)};
   // Нежилой проект: ставки зданий — в «Строительстве», перед подземной.
   const moved=new Set();
   if(fields.some(f=>f[0]==='main_under_th_per_sqm')){
    const own=nonresBuildingRateFields();
    own.forEach(f=>moved.add(f[0]));
    if(own.length)fields=fields.flatMap(f=>f[0]==='main_under_th_per_sqm'?[...own,f]:[f]);
   }
   fields.forEach(f=>{
     const [id,label,unit,type]=f;
     // Ставка здания нежилого проекта стоит в «Строительстве» — в блоке
     // объекта её нет (одно место ввода).
     if(grpObj&&movedToConstruction(id))return;
     // Норматив площади двора правится в «Настройках класса»: он свойство
     // класса, а не площадки. Поле при этом объявлено там же, где все
     // остальные, — отсюда берут подпись и единицу окно классов и строка
     // отклонений в отчёте; здесь оно только не рисуется. Выход ДО создания
     // узла: наполовину нарисованное поле оставило бы в сетке пустую клетку.
     if(notOnInputs(id)||strategyHides(id))return;
     const own=moved.has(id)?null:fieldSection(id);
     if(own&&own!==section){
       section=own;
       const card=document.createElement('section');card.className='field-card';card.dataset.section=own;
       const head=document.createElement('div');head.className='field-section';head.textContent=own;
       card.appendChild(head);det.appendChild(card);openGrid(card);
     }else if(!grid||(!own&&section)){section=null;openGrid()}
     const wrap=document.createElement('div');wrap.className='field';wrap.dataset.field=id;
     // Класс задаёт не только деньги, и об этом сказано у самого поля:
     // одиннадцать вводных ставит выбранный класс, а на экране они
     // неотличимы от набранных руками («я не вижу ничего про площадь
     // машиноместа установлена по классу», владелец, 15.09.2026). Пометка
     // стоит у ЕДИНИЦЫ, то есть рядом с числом, а не строкой ниже: подпись
     // под полем читают, когда уже засомневались.
     const unitText=classFieldUnitText(id,unit);
     wrap.innerHTML=`<label>${label} <span class="unit">${unitText}</span></label>`;
     // Срок строительства при очередности задаёт очередь, а не проект: движок
     // читает проектное поле ТОЛЬКО когда очередь своего срока не назвала, а
     // страница называет его всегда. Поле, которого никто не читает, — не
     // вводная, и на экране оно неотличимо от работающего (владелец,
     // 07.09.2026: «какой будет срок, если эти сроки противоречат друг другу?»).
     // Сроки очередей названы здесь же: иначе гашение отвечает «не тут», не
     // сказав «а где».
     // Жилое поле в нежилом проекте: оно обнулено и не читается, и сказано
     // это у самого поля. Запереть мало — «не тронули» читается как «убрали»,
     // а пустая клетка без слов неотличима от несработавшей правки.
     if(withoutHousing()&&NONRESIDENTIAL_CLEARED[id]){
       wrap.innerHTML+='<div class="note" style="margin:0;padding:11px 12px">'
        +clearedHousingNote(id)+'</div>';
       grid.appendChild(wrap);return;
     }
     if(id==='construction_months'&&phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1){
       const terms=(phasing.phases||[]).map((ph,n)=>`${ph.name||('О'+(n+1))} — ${Number(ph.construction_months||0)}`).join(', ');
       wrap.innerHTML+=`<div class="note" style="margin:0;padding:11px 12px">Задаётся по очередям на вкладке «Очередность» — это поле при очередности не читается.`
        +(terms?` Сейчас: ${terms} мес.`:'')+`</div>`;
       grid.appendChild(wrap);return;
     }
     if(phasing&&phasing.enabled&&['kindergarten_start','school_start','clinic_start'].includes(id)){
       wrap.innerHTML+=`<div class="note" style="margin:0;padding:11px 12px">Определяется по выбранной очереди на вкладке «Очередность». По умолчанию — дата начала этой очереди.</div>`;
       grid.appendChild(wrap);return;
     }
     // Что из мест асфальт, а что продаётся. Текст считает СЕРВЕР рядом с
     // числами: собранный на странице, он был бы вторым счётом той же
     // величины, и однажды разошёлся бы с отчётом. Здесь только место под него.
     if(id==='sports_parking_over_spaces'){
      wrap.innerHTML+='<div id="objectParkingNote" style="margin-top:6px"></div>';
     }
     if(id==='land_rights_cost_mln'&&krtRequirementEntered()){
       wrap.innerHTML+=krtVriFeeNote();
     }
     if(id==='vri_relief_mln'){
       wrap.innerHTML+=vriReliefSourceNote();
     }
     if(type==='pf_steps'){renderPfStepsEditor(wrap);grid.appendChild(wrap);return;}
     // График — ячейками, а не строкой: значение, единица и срок отдельными
     // полями, строки добавляются и убираются.
     if(type==='schedule'){renderScheduleEditor(wrap,id,f[4]||{});grid.appendChild(wrap);return;}
     let el;
     if(Array.isArray(f[4])){el=document.createElement('select');f[4].forEach(pair=>{let o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];el.appendChild(o)})}
     else if(type==='select'){el=document.createElement('select');__DEVELOPAID_SOCIAL_MODES__.forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
     else if(type==='finance_select'){el=document.createElement('select');['Капитализация в ПФ','Выплата при рефинансировании'].forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
     else {el=document.createElement('input');el.type=type==='checkbox'?'checkbox':type;if(type==='number')el.step='any'}
     el.id='f_'+id;
     // В Москве периодичность рассрочки по ВРИ установлена нормативно —
     // квартал, и движок всё равно считает по нему. Пока поле оставалось
     // свободным, выбранное значение расходилось с посчитанным.
     const mskQuarter=id==='vri_periodicity_months'&&String(inputs.vri_region||'msk')==='msk';
     if(mskQuarter)inputs[id]=3;
     // Отсутствующий ключ — не «снято». Чекбокс рисовался по !!inputs[id], и
     // поле, которого нет в наборе, приходило снятым, а обратно уходило
     // явным false, затирая умолчание. Так «ВРИ включена в банковский
     // бюджет» превращалась в «Нет», ВРИ уходила из долга, и LLCR
     // оказывался выше настоящего: 1,16 вместо 1,07.
     if(type==='checkbox')el.checked=(id in inputs)?!!inputs[id]:!!INPUT_DEFAULT[id];
     if(id==='vri_required'){inputs.vri_required=vriPaymentActive();el.checked=inputs.vri_required}
     else el.value=inputs[id]??INPUT_DEFAULT[id]??'';
     if(mskQuarter){
      el.disabled=true;
      el.title='Москва: платежи ежеквартально — установлено нормативно';
     }
     el.onchange=()=>{if(id==='vri_required')return vriRequiredToggled(el);const classRegionBefore=classRegion();inputs[id]=type==='checkbox'?el.checked:(type==='number'&&!Array.isArray(f[4])?Number(el.value):el.value);markFieldManual('inputs.'+id);if(id==='land_rights_cost_mln'){vriFeeClearedMln=0;syncVriRequiredBox()}if(id==='demolition_area_sqm'||id==='land_buyout_mln')refreshClassFieldUnit(id);if(id==='social_mode')inputs._social_mode_user_set=true;if(id==='social_population_method'&&String(inputs.vri_region||'msk')!=='mo')recalcFromTep({silent:true});{const parkOwner=OBJECT_PARKING_PREFIXES.find(p=>id===p+'_parking_under_spaces'||id===p+'_parking_over_spaces');if(parkOwner){if(String(el.value).trim()==='')restoreParkingNorm(parkOwner);else markParkingByHand(parkOwner);}}if(id==='underground_manual_spaces'||id==='underground_manual_gns_sqm'){if(Number(el.value)>0)markParkingByHand(PROJECT_PARKING_KEY);else markParkingByNorm(PROJECT_PARKING_KEY);}if(SOCIAL_SCALED_KEYS.includes(id))stampSocialBasis('введены руками');if(id==='vri_region'){followClassRegion(classRegionBefore);syncTep(false);renderInputs();return calculate()}if(id==='vri_relief_mode'||id==='vri_financing_mode'){renderInputs();return calculate()}if(VRI_SHARE_FIELDS.includes(id))refreshVriSharesNote();if(STRATEGY_FIELD_READERS_SWITCHES.includes(id)){renderInputs();return calculate()}if(markClassManual(id)){syncProjectClassSelector();refreshClassFieldUnit(id)}if(UNDERGROUND_PAIR_INPUTS.includes(id))syncUndergroundPair(id);if(id==='storage_area_per_unit_sqm'){syncStoragePair('units');renderTep()}if(TEP_DERIVED_INPUTS.includes(id)){const modeSwitched=id==='social_area_source';const filled=id==='social_mode'&&applyRequiredSocialProgramFromGlavapu();const derived=syncTep(false);if(modeSwitched||filled||derived)renderInputs()}refreshGroupPeeks();calculate()};
     wrap.appendChild(el);
     // Подписи признака ВРИ и нормировки долей — узлами, как подпись замка
     // ниже: `innerHTML+=` пересоздал бы уже вставленное поле без обработчиков.
     if(id==='vri_required')wrap.appendChild(vriNoteNode('vriRequiredNote',vriRequiredNote()));
     if(id==='vri_share_equity_pct')wrap.appendChild(vriNoteNode('vriSharesNote',vriSharesNote()));
     // Ручная льгота при посчитанной — кнопка «Применить посчитанную» у
     // самого поля: искать её внизу вкладки владелец не стал (15.10.2026).
     if(id==='vri_relief_mode'){
      const offer=document.createElement('div');
      offer.id='vriReliefOffer';
      wrap.appendChild(offer);
      if(typeof fillVriReliefOffer==='function')fillVriReliefOffer();
     }
     // Доля и сумма льготы читаются только в своём режиме. Оставшиеся от
     // прежнего выбора «100» рядом с «Нет ручной — по расчёту проекта»
     // читались как льгота на всю плату, хотя расчёт их не берёт.
     const reliefIdle=vriReliefFieldIdle(id);
     if(reliefIdle){
      el.disabled=true;el.title=reliefIdle;
      const idle=document.createElement('div');
      idle.className='hint vri-relief-idle';
      idle.style.cssText='margin:4px 0 0;color:#777';
      idle.textContent=reliefIdle;
      wrap.appendChild(idle);
     }
     {const originNote=fieldOriginNote('inputs.'+id);if(originNote)wrap.insertAdjacentHTML('beforeend',originNote);}
     // Смягчение, которое даёт ГОРОД по своему решению, — справка у числа, а
     // не множитель в расчёте (решение владельца, 13.09.2026: «это зависит от
     // решения мэрии, так что мы же можем просто указать на такую возможность
     // справочно»). Стоит она у ПЛОЩАДИ двора: норматив м²/чел. переехал в
     // «Настройки класса» (владелец, 14.09.2026), и площадь осталась
     // единственным полем «Вводных», куда согласованное снижение вносят.
     // Переехать справка обязана вместе с ним: оставшись у скрытого поля, она
     // не нарисовалась бы вовсе — молча, потому что в исходнике она на месте.
     // Первой строкой сказано, ЧЬЁ число считает двор, — наши 11/15/20 м²/чел.
     // это стоимость двора по классу, а не норма города, и одно под другим
     // читалось бы как ссылка на акт там, где стоит экспертная ставка. Только
     // Москва: 2152-ПП другим регионам не писан.
     //
     // Место — ПОСЛЕ поля, и отдельным узлом, а не `innerHTML+=` до него: там
     // справка встаёт над вводом и приклеивается к подписи поля, то есть
     // читается как утверждение о нём. Замер поймал это на первом же прогоне —
     // 200 px выше поля; тот же капкан, что 13.09.2026 на нормативе паркинга.
     // Статья считается на дворе, а сравнивают её со сметой и со сводом на
     // метр ГНС. Производную считает движок (`landscaping_per_gns_th`) — здесь
     // только место под неё; заполняет `renderLandscapingRateNote()`, и зовут
     // её и форма, и результат: написанная объяснять молчание, она молчала бы
     // ровно там, где нужна, — до первого расчёта.
     // Строка двора переехала вместе со ставкой: ставку метра двора правят
     // теперь в «Настройках класса» (она в `CLASS_ONLY_INPUTS`), и подпись,
     // оставшаяся у скрытого поля, не нарисовалась бы ВОВСЕ — молча, потому
     // что в исходнике она на месте. Новый дом — площадь двора: строка про
     // двор и говорит, и площадь осталась единственным полем двора во
     // «Вводных». То же правило, по которому переехала справка о 2260-ПП.
     if(id==='landscaping_area_sqm'){
      const per=document.createElement('div');
      per.className='hint';
      per.id='landscapingRateNote';
      per.style.cssText='margin:4px 0 0;color:#777';
      wrap.appendChild(per);
     }
     // Счётный показатель ₽ на метр дома — просьба владельца (14.09.2026: «во
     // вводных счётный показатель руб на ГНС, посчитанный из данных настроек,
     // с пометкой, что можно ввести вручную или поменять в настройках»). Он
     // стоит под тем полем, куда его и вписывают, и считается на базе ЭТОГО
     // поля: показатель на другой базе, предложенный к вводу, — это другое
     // число, выданное за то же.
     if(id==='landscaping_gns_th_per_sqm'){
      const own=document.createElement('div');
      own.className='hint';
      own.id='landscapingHouseRateNote';
      own.style.cssText='margin:4px 0 0;color:#777';
      wrap.appendChild(own);
     }
     // Место под норму — ПОСЛЕ поля, а не до него. Стоя над вводом, подпись
     // приклеивалась к подписи поля и читалась как утверждение о нём: «по
     // нормативу приложения 6 — 1 493 мест» под строкой «мест на первых
     // этажах» (экран владельца, 13.09.2026). Норматив при этом на ОБЪЕКТ, то
     // есть на оба поля вместе. Правило «подпись переехала под оба поля»
     // записано 09.09 и было применено наполовину: div висел у второго поля
     // и выше его ввода. Заполняет его `renderObjectParkingFieldNotes`: число
     // следует за РАСЧЁТОМ, а не за правкой поля, иначе прежняя норма под
     // новыми метрами читается как посчитанная.
     // Объекты с гаражом — из реестра: перечисленные здесь руками, они не
     // знали второго офисника, и норма под его местами не появлялась.
     const parkPrefix=OBJECT_PARKING_PREFIXES.find(p=>id===p+'_parking_over_spaces');
     if(parkPrefix){
      const normCell=document.createElement('div');
      normCell.id='parkNorm_'+parkPrefix;
      normCell.style.cssText='margin-top:4px;font-size:10px;color:#777';
      wrap.appendChild(normCell);
     }
     // Та же подпись у проектного подземного: норма под парой полей, серым,
     // пишет её `renderObjectParkingFieldNotes` — тем же вызовом, что и у
     // объектов, иначе одна из подписей отставала бы от расчёта.
     if(id==='underground_manual_gns_sqm'){
      const normCell=document.createElement('div');
      normCell.id='parkNorm_'+PROJECT_PARKING_KEY;
      normCell.style.cssText='margin-top:4px;font-size:10px;color:#777';
      wrap.appendChild(normCell);
     }
     grid.appendChild(wrap);
   });
   // Подвал блока КРТ: льгота по проекту и плата за ВРИ после неё.
   if(grp[0]==='Социальная нагрузка'&&krtRequirementEntered()){
    const foot=document.createElement('div');foot.id='krtVriFooter';
    foot.innerHTML=krtVriFooterHtml((lastResult||{}).vri);det.appendChild(foot);
   }
   (ownTab?vriBox:box).appendChild(det);
 });
 rateScenario.value=inputs.rate_scenario||'base';
 // Фокус возвращается туда, где он был: перерисовка случается ПОСРЕДИ ввода
 // (место ДОО дописывает площадь во вводные), и без возврата человек после
 // каждого числа заново ищет поле мышью.
 if(focusId){
  const back=document.getElementById(focusId);
  if(back&&typeof back.focus==='function'){
   back.focus();
   if(caret!=null&&typeof back.setSelectionRange==='function'){
    try{back.setSelectionRange(caret,caret)}catch(e){}
   }
  }
 }
 // Подпись под полями пишет тот, кто эти поля создал: ячейки
 // пересобираются пустыми при каждой перерисовке формы.
 renderObjectParkingFieldNotes();
 renderUndergroundFieldNote();
 renderLandscapingRateNote();
}

// --- гостиничный проект ----------------------------------------------------
// Поля, группы, ориентиры и диапазоны — из движка (`hotel_page_spec`): копии
// подписей и чисел здесь нет. Поле гостиницы — `inputs.hotel_<key>`;
// происхождение числа — `inputs.hotel_origins[key]`. Ориентир чужой площадки
// ставится только кнопкой и несёт свою ячейку; правка руками происхождение
// снимает — набранное человеком не выглядит ориентиром, и наоборот.
const HOTEL=__DEVELOPAID_HOTEL__;
function hotelOrigins(){return inputs[HOTEL.origins_key]||{}}
function setHotelField(key,value,origin){
 inputs['hotel_'+key]=value;
 const origins={...hotelOrigins()};
 if(origin)origins[key]=origin;else delete origins[key];
 inputs[HOTEL.origins_key]=origins;
}
function hotelBlank(v){return v===undefined||v===null||(typeof v==='string'&&!v.trim())}
function hotelValue(field){
 const v=inputs['hotel_'+field.key];
 return hotelBlank(v)?field.default:v;
}
// Нужно ли поле при текущих выборах — то же правило, что у движка
// (`_is_needed`): кредитные поля не нужны без кредита, мультипликатор — при
// ставке капитализации.
function hotelFieldNeeded(field){
 if(!field.needed_when)return true;
 const owner=HOTEL.fields.find(f=>f.key===field.needed_when[0]);
 if(owner&&!hotelFieldNeeded(owner))return false;
 return field.needed_when[1].includes(String(hotelValue(owner)));
}
function hotelRangeText(field){
 const stars=String(inputs.hotel_stars||'');
 const r=(field.ranges||{})[stars]||(field.ranges||{})[''];
 if(!r)return '';
 const fmt=v=>Number(v).toLocaleString('ru-RU',{maximumFractionDigits:2});
 const span=r.min===r.max?fmt(r.min):fmt(r.min)+'–'+fmt(r.max);
 return 'ориентиры'+(stars&&(field.ranges||{})[stars]?' класса '+stars+'*':'')+': '+span+' ('+r.sources.join(', ')+')';
}
// Происхождение — по ТЕКУЩЕМУ ориентиру (то же правило, что
// `hotel_presets.current_origins`): проект, сохранённый с прежним ключом
// ориентира, показывает его нынешнее имя, а не сохранённый текст.
function hotelOriginNow(key){
 const o=hotelOrigins()[key];
 if(!o||!o.preset)return o;
 const name=(HOTEL.preset_aliases||{})[o.preset]||o.preset;
 const p=HOTEL.presets.find(x=>x.key===name);
 return p&&p.origins[key]?p.origins[key]:o;
}
function hotelFieldNote(field){
 const origin=hotelOriginNow(field.key);
 const raw=inputs['hotel_'+field.key];
 if(origin&&!hotelBlank(raw))return {cls:'hotel-origin',text:origin.text};
 if(hotelBlank(raw)&&field.default!==null&&field.default!==undefined)
  return {cls:'hotel-default',text:'умолчание: '+field.origin};
 if(hotelBlank(raw)){
  const range=hotelRangeText(field);
  return {cls:'hotel-empty',text:(field.required?'не задано — расчёт гостиницы ждёт это поле':'не задано')+(range?'; '+range:'')};
 }
 return {cls:'hotel-manual',text:'введено вручную'+(field.hint?' · '+field.hint:'')};
}
function applyHotelPreset(key,onlyEmpty){
 const preset=HOTEL.presets.find(p=>p.key===key);
 if(!preset)return;
 Object.keys(preset.values).forEach(f=>{
  if(onlyEmpty&&!hotelBlank(inputs['hotel_'+f]))return;
  setHotelField(f,preset.values[f],preset.origins[f]);
 });
 // Вводные движка (ставка статьи сметы) — как `hotel_presets.apply_preset`:
 // умолчание заменяется, вписанное руками остаётся.
 Object.keys(preset.engine_values||{}).forEach(k=>{
  if(isFieldManual('inputs.'+k))return;
  inputs[k]=preset.engine_values[k];
  fieldOrigins()['inputs.'+k]=Object.assign({source:'hotel_preset'},preset.engine_origins[k]);
 });
 renderInputs();refreshGroupPeeks();calculate();
}
function hotelInputsBlock(wasOpen){
 const det=document.createElement('details');
 det.dataset.group='Гостиница';det.className='hotel-block';
 det.open=!wasOpen||!wasOpen.size||wasOpen.has('Гостиница');
 const sum=document.createElement('summary');sum.textContent='Гостиница';det.appendChild(sum);
 const bar=document.createElement('div');bar.className='hotel-presets note';
 bar.innerHTML='<b>Ориентир эталонной модели.</b> Числа чужой площадки подставляются только по нажатию и '
  +'помечаются ячейкой книги; пустое поле показывает диапазон ориентиров. '
  +HOTEL.presets.map(p=>'<span class="hotel-preset" data-preset="'+escapeHtml(p.key)+'">'
   +'<button type="button" class="btn" onclick="applyHotelPreset(\''+p.key+'\',true)">Заполнить пустые: '+escapeHtml(p.title)+'</button>'
   +'<button type="button" class="tep-refill" onclick="applyHotelPreset(\''+p.key+'\',false)">заменить все</button></span>').join(' ');
 det.appendChild(bar);
 syncHotelClassSelector();
 HOTEL.groups.forEach(([gkey,gtitle])=>{
  const fields=HOTEL.fields.filter(f=>f.group===gkey&&hotelFieldNeeded(f));
  if(!fields.length)return;
  const card=document.createElement('section');card.className='field-card';card.dataset.section=gtitle;
  const head=document.createElement('div');head.className='field-section';head.textContent=gtitle;card.appendChild(head);
  const grid=document.createElement('div');grid.className='fields';card.appendChild(grid);
  fields.forEach(field=>{
   const id='hotel_'+field.key;
   const wrap=document.createElement('div');wrap.className='field';wrap.dataset.field=id;
   wrap.innerHTML='<label>'+escapeHtml(field.label)+' <span class="unit">'+escapeHtml(field.unit||'')+'</span></label>';
   let el;
   if(field.kind==='choice'){
    el=document.createElement('select');
    if(!field.required){const o=document.createElement('option');o.value='';o.textContent='— не задан —';el.appendChild(o)}
    field.choices.forEach(pair=>{const o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];el.appendChild(o)});
   }else{el=document.createElement('input');el.type=field.kind==='date'?'date':'number';if(field.kind!=='date')el.step='any'}
   // Свой префикс id: общий сборщик формы читает все `f_*` и превратил бы
   // пустое поле гостиницы в ноль — а пустое здесь значит «не задано».
   el.id='h_'+id;
   const v=hotelValue(field);
   el.value=hotelBlank(v)?'':v;
   el.onchange=()=>{
    const raw=el.value;
    const value=hotelBlank(raw)?null:(field.kind==='number'?Number(raw):raw);
    setHotelField(field.key,value,null);
    renderInputs();refreshGroupPeeks();calculate();
   };
   wrap.appendChild(el);
   const note=hotelFieldNote(field);
   const nd=document.createElement('div');nd.className='hint '+note.cls;nd.textContent=note.text;
   wrap.appendChild(nd);
   grid.appendChild(wrap);
  });
  det.appendChild(card);
 });
 return det;
}
// Отчёт гостиницы печатает строки движка (`hotel_report`); незаполненная
// гостиница называет, каких вводных нет, а не рисует нули.
function hotelCell(row){
 const v=row.value;
 if(v===null||v===undefined||v==='')return '—';
 if(row.unit==='rub_unit')return Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
 if(row.unit==='count')return Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0});
 if(row.unit==='years')return Number(v).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1});
 return nonresCell(row);
}
function renderHotelReport(r){
 const card=document.getElementById('hotelReportCard'),box=document.getElementById('hotelReportBody');
 if(!card||!box)return;
 const h=((r||{}).report||{}).hotel;
 card.hidden=!h;
 if(!h){box.innerHTML='';return}
 if(!h.computed){
  box.innerHTML='<div class="note hotel-missing">Гостиница не считается: не заданы '
   +escapeHtml((h.missing||[]).join(', '))+'. Заполните их в блоке «Гостиница» на вкладке «Экономика» '
   +'или кнопкой ориентира.</div>';
  return;
 }
 const keyRows='<table class="hotel-kpi"><tbody>'+h.rows.map(row=>'<tr><td>'+escapeHtml(row.label)+'</td><td>'+hotelCell(row)+'</td></tr>').join('')
  +(h.warnings||[]).map(w=>'<tr class="warn"><td>'+escapeHtml(w)+'</td><td></td></tr>').join('')+'</tbody></table>';
 const u=h.usali||{years:[],rows:[]};
 const usali='<div class="scroll"><table class="hotel-usali"><thead><tr><th>USALI по годам</th>'
  +u.years.map(y=>'<th>'+y+'</th>').join('')+'</tr></thead><tbody>'
  +u.rows.map(row=>'<tr data-key="'+escapeHtml(row.key)+'"><td>'+escapeHtml(row.label)+'</td>'
   +row.values.map(v=>'<td>'+hotelCell({value:v,unit:row.unit})+'</td>').join('')+'</tr>').join('')
  +'</tbody></table></div>';
 box.innerHTML=keyRows+usali;
}

"""
