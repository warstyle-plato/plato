"""Кусок страницы PAGE: Скрипт: ВРИ, сценарий, парковка объектов, таблица ТЭП, площадка
и плотность, норматив соцобъектов, КРТ, пересчёт от ТЭП.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_tep")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""function vriTotalsRows(t,summary){
 // Плата за ВРИ на метр — то, чем участки сравнивают между собой: сама сумма
 // ни о чём не говорит без площади, которую на ней построят.
 const perMetre=(()=>{
  const s=summary||{};
  const gns=Number(s.project_gns_sqm||0),saleable=Number(s.monetizable_saleable_sqm||0);
  const value=Number(t.amount||0);
  if(!(value>0)||!(gns>0))return '';
  const per=(area)=>area>0?num2(value/area/1000)+' тыс ₽/м²':'—';
  return row('Плата на метр',per(gns)+' ГНС · '+per(saleable)+' прод.');
 })();
 return ((Number(t.relief||0)>0)?row('Обязательство до льготы',money(t.gross))+
   row('Льгота'+(t.relief_source?' — '+escapeHtml(t.relief_source):''),money(t.relief)):'')+
   row('Сумма обязательства',money(t.amount))+
   row('Основной долг',money(t.principal))+
   row('Проценты по рассрочке',money(t.interest))+
   row('Расходы на обеспечение',money(t.security_cost))+
   row('Выплаты до открытия ПФ',money(t.before_pf))+
   row('Выплаты после открытия ПФ',money(t.after_pf))+
   row('Профинансировано БРИДЖем',money(t.bridge))+
   row('Профинансировано ПФ',money(t.pf))+
   row('Профинансировано капиталом',money(t.equity))+
   row('Денежный поток по ВРИ, всего',money(t.cash))+perMetre;
}

function vriScheduleRows(rows){
 return (rows||[]).map(x=>{
   const sources=[];
   if(Number(x.bridge||0)>0.5)sources.push('БРИДЖ');
   if(Number(x.pf||0)>0.5)sources.push('ПФ');
   if(Number(x.equity||0)>0.5)sources.push('капитал');
   return `<tr>
    <td>${dateRu(x.date)}${x.security?' · обеспечение':''}</td>
    <td>${money(x.principal)}</td>
    <td>${money(x.interest)}</td>
    <td>${money(x.total)}</td>
    <td>${money(x.balance_after)}</td>
    <td>${sources.join(' + ')||'—'}</td>
   </tr>`;
 }).join('');
}

// Льготы по плате за ВРИ и рабочие места — таблица по объектам проекта.
// Одна функция и для окна, и для теста; числа — с сервера (`vri.benefits`).
function vriBenefitsHtml(b,basis){
 if(!b)return '';
 if(!b.applicable)return b.reason?'<div class="note">'+escapeHtml(b.reason)+'</div>':'';
 const rows=b.rows||[];
 if(!rows.length&&!(b.transfer_mln>0)&&!b.override&&!b.mpt_reason)return '';
 const n0=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0});
 const n3=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
 const body=rows.map(r=>{
  const why=(r.blockers||[]).length?'<span style="color:#8a4b08">'+escapeHtml(r.blockers.join('; '))+'</span>'
   :escapeHtml(r.kmest_source||'');
  return '<tr data-key="'+escapeHtml(r.key)+'"><td>'+escapeHtml(r.label)+
   (r.category_label?'<div style="font-size:10px;color:#888">'+escapeHtml(r.category_label)+'</div>':'')+'</td>'+
   '<td style="text-align:right">'+n0(r.area_sqm)+'<div style="font-size:10px;color:#888">'+escapeHtml(r.area_origin||'')+'</div></td>'+
   '<td style="text-align:right" title="'+escapeHtml(r.jobs_basis||'')+'">'+n0(r.jobs)+'</td>'+
   '<td style="text-align:right">'+(r.kmest===null||r.kmest===undefined?'—':String(r.kmest).replace('.',','))+'</td>'+
   '<td style="text-align:right"><b>'+n3(r.benefit_mln)+'</b></td>'+
   '<td style="font-size:11px">'+why+'</td></tr>';
 }).join('');
 const transfer=b.transfer_mln>0?'<tr data-key="transfer"><td>Передача квартир городу<div style="font-size:10px;color:#888">'+
  escapeHtml((b.transfer||{}).area_origin||'')+'</div></td><td style="text-align:right">'+n0((b.transfer||{}).area_sqm)+
  '</td><td></td><td></td><td style="text-align:right"><b>'+n3(b.transfer_mln)+'</b></td><td style="font-size:11px">'+
  escapeHtml((b.transfer||{}).source||'')+'</td></tr>':'';
 const total='<tr style="font-weight:600;background:#fafaf8"><td>Итого</td><td></td><td style="text-align:right">'+n0(b.jobs_total)+
  '</td><td></td><td style="text-align:right">'+n3(b.total_mln)+'</td><td style="font-size:11px">льгота МПТ '+n3(b.mpt_mln)+
  (b.mpt_source&&b.mpt_source.text?' ('+escapeHtml(b.mpt_source.text)+')':'')+
  (b.transfer_mln>0?' + передача квартир '+n3(b.transfer_mln):'')+' млн ₽</td></tr>';
 const act=b.act||{};
 const actLink=act.url?'<a href="'+escapeHtml(act.url)+'" target="_blank" rel="noopener">'+escapeHtml(act.title||act.short||'')+'</a>':escapeHtml(act.title||'');
 const kz=b.kzatr?'<div style="font-size:11px;color:#777;margin:4px 0">Льгота за МПТ = 1000 ₽/м² × площадь × Кзатр × Кмест — '+actLink+
  '. Кмест берётся из приложения 3 к постановлению (таблица 1: графа — вид объекта, строка — группа районов; таблица 2 — приоритетные кадастровые кварталы). Кзатр '+
  String(b.kzatr.value).replace('.',',')+' ('+escapeHtml(b.kzatr.quarter)+'). Рабочие места — по нормам калькулятора ГлавАПУ.</div>':'';
 let action='';
 const auto=Number(b.auto_mpt_mln!==undefined?b.auto_mpt_mln:b.mpt_mln||0);
 const ov=b.override||null;
 // Льгота за МПТ из калькулятора по другому участку заменяет автоматическую
 // (решение владельца, 14.10.2026): видно, откуда она, и её можно снять.
 const override=ov?'<div class="note vri-mpt-override" style="margin-top:8px">Льгота за МПТ — '+escapeHtml(((b.mpt_source||{}).text)||'')+': <b>'+
  n3(ov.benefit_mln)+' млн ₽</b>'+(ov.district?' · '+escapeHtml(ov.district):'')+(ov.category_label?' · '+escapeHtml(ov.category_label):'')+
  '. Заменяет посчитанную по участку проекта ('+n3(auto)+' млн ₽), а не складывается с ней.'+
  (ov.error?'<br><span style="color:#b3261e">'+escapeHtml(ov.error)+'</span>':'')+
  ((ov.blockers||[]).length?'<br><span style="color:#8a4b08">'+escapeHtml(ov.blockers.join('; '))+'</span>':'')+
  ' <button class="btn" onclick="clearMptOverride()">Снять применённую</button></div>':'';
 // Чего не хватает для льготы за МПТ — словами и с местом, а не молчаливым нулём.
 const missing=(!ov&&b.mpt_reason)?'<div class="note vri-mpt-missing" style="color:#8a4b08;border-color:#8a4b08;font-weight:600">'+
  escapeHtml(b.mpt_reason)+'</div>':'';
 if(basis==='project_benefits'){
  action='<div class="import-status" style="margin-top:8px"><span class="'+(b.total_mln>0?'import-ok':'')+'">'+
   (b.total_mln>0?'Льгота '+n3(b.total_mln)+' млн ₽ входит в плату за ВРИ сама (ручной льготы нет).'+
    (b.mpt_mln>0?' Это расчёт по 1874-ПП: статус МПТ присваивает город (ДИиПП, МВК). Отказаться — «Льгота по плате: Не применять льготу».':'')
    :'Посчитанной льготы нет — плата за ВРИ начисляется целиком.')+'</span></div>';
 }else if(basis==='percent'||basis==='amount'){
  action='<div class="toolbar" style="margin-top:8px"><span style="font-size:12px;color:#777">В расчёте ручная льгота — она главнее посчитанной ('+
   n3(b.total_mln)+' млн ₽).</span><button class="btn" onclick="useProjectVriBenefits()">Вернуться к посчитанной</button></div>';
 }else if(basis==='off'){
  action='<div class="toolbar" style="margin-top:8px"><span style="font-size:12px;color:#777">Выбран отказ от льготы — посчитанная ('+
   n3(b.total_mln)+' млн ₽) в плату не входит.</span><button class="btn" onclick="useProjectVriBenefits()">Применить посчитанную</button></div>';
 }
 action=(typeof sitePositionNote==='function'?sitePositionNote():'')+missing+override+action;
 const notes=(b.notes||[]).length?'<div class="note">'+b.notes.map(x=>escapeHtml(x)).join('<br>')+'</div>':'';
 // Вписанное положение участка против разбора кадастра — красным над
 // таблицей: ошибочное «за ТТК» дало бы льготу, которой у участка нет.
 const conflicts=(b.conflicts||[]).length?'<div class="note vri-benefits-conflict" style="color:#b3261e;font-weight:600;border-color:#b3261e">'+
  b.conflicts.map(x=>escapeHtml(x)).join('<br>')+'</div>':'';
 return conflicts+'<div class="scroll" style="max-height:none"><table class="metric-table metric-compact vri-benefits-table"><thead><tr>'+
  '<th>Объект</th><th>Площадь, м²</th><th>Рабочие места</th><th>Кмест</th><th>Льгота, млн ₽</th><th>Основание / почему нет</th></tr></thead><tbody>'+
  body+transfer+total+'</tbody></table></div>'+kz+notes+action;
}
function renderVriBenefits(b,basis){
 const card=document.getElementById('vriBenefitsCard');
 if(!card)return;
 const html=vriBenefitsHtml(b,basis);
 card.style.display=html?'':'none';
 document.getElementById('vriBenefitsBody').innerHTML=html;
}
// Посчитанная льгота, которую сейчас перекрывает ручная (или отказ), — одна
// функция для кнопки у поля «Льгота по плате» и строки в калькуляторе МПТ.
// null — предлагать нечего: действует посчитанная или её нет.
function vriProjectReliefOffer(vri){
 const b=(vri&&vri.benefits)||{}, basis=((vri&&vri.totals)||{}).relief_basis;
 if(!['percent','amount','off'].includes(basis))return null;
 const mln=Number(b.total_mln||0);
 if(!(b.applicable!==false&&mln>0))return null;
 return {mln,text:mln.toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽',basis};
}
function fillVriReliefOffer(){
 const box=document.getElementById('vriReliefOffer');
 if(!box)return;
 const offer=vriProjectReliefOffer(((typeof lastResult==='object'&&lastResult)||{}).vri);
 box.innerHTML=offer?'<button type="button" class="btn vri-apply-project" style="margin-top:6px;font-weight:600" onclick="useProjectVriBenefits()">Применить посчитанную ('+
  escapeHtml(offer.text)+')</button>':'';
}
// Вернуть посчитанную по проекту льготу: ручной нет — действует расчётная.
function useProjectVriBenefits(){
 inputs.vri_relief_mode='none';
 delete inputs._vri_relief_source;
 markFieldManual('inputs.vri_relief_mode');
 renderInputs();refreshGroupPeeks();calculate();
}
// Снять льготу за МПТ, применённую из калькулятора по другому участку:
// возвращается посчитанная по участку проекта.
function clearMptOverride(){
 delete inputs.vri_mpt_override;
 renderInputs();refreshGroupPeeks();calculate();
 if(typeof window.mptOverrideChanged==='function')window.mptOverrideChanged();
}
// Применить льготу за МПТ из калькулятора по другому участку: в проект
// уходят вводные калькулятора, а сумму считает движок тем же `mpt_calculator`
// (`vri_mpt_override`) — значение хранит происхождение и не замерзает.
function applyMptOverride(payload,place){
 inputs.vri_mpt_override={payload:payload,cadastral:String((place||{}).cadastral||''),
  address:String((place||{}).address||''),applied_at:new Date().toISOString()};
 renderInputs();refreshGroupPeeks();calculate();
}
// Поля ВРИ, которые читаются только в своём режиме: доля и сумма ручной
// льготы, доли источников оплаты. Ответ — почему поле сейчас не читается, или
// пусто. Один ответ и для замка поля, и для его подписи.
const VRI_SHARE_FIELDS=['vri_share_bridge_pct','vri_share_pf_pct','vri_share_equity_pct'];
function vriReliefFieldIdle(id){
 if(VRI_SHARE_FIELDS.includes(id))
  return String(inputs.vri_financing_mode||'auto')==='shares'?''
   :'Не читается: источники — по дате платежа («'+fieldOptionLabel('vri_financing_mode','auto')+'»).';
 const need={vri_relief_pct:'percent',vri_relief_mln:'amount'}[id];
 if(!need)return '';
 const mode=String(inputs.vri_relief_mode||'none');
 if(mode===need)return '';
 const said={none:'нет ручной — действует льгота, посчитанная по проекту',off:'не применять льготу',
  percent:'доля от суммы',amount:'фиксированная сумма'}[mode]||mode;
 return 'Не читается: «Льгота по плате» — '+said+'.';
}

// Подпись варианта поля выбора — из объявления поля (`FIELD_GROUPS`), как и
// сам список: второе название варианта разошлось бы со страницей.
function fieldOptionLabel(field,value){
 for(const g of FIELD_GROUPS)for(const f of (g[1]||[]))
  if(f[0]===field&&Array.isArray(f[4])){const o=f[4].find(p=>String(p[0])===String(value));if(o)return o[1]}
 return String(value||'');
}
// Как делятся платежи при «Вручную по долям» — тем же правилом, что движок
// (`_vri_split_payment`): каждая доля делится на сумму долей, а нулевая
// сумма возвращает разнос по дате платежа. Пусто — доли дают ровно 100%.
function vriSharesNote(){
 if(String(inputs.vri_financing_mode||'auto')!=='shares')return '';
 const v=VRI_SHARE_FIELDS.map(k=>Math.max(0,Number(inputs[k]||0)));
 const total=v[0]+v[1]+v[2];
 if(!(total>0))return 'Доли не заданы (сумма 0) — платежи разнесены автоматически: «'
  +fieldOptionLabel('vri_financing_mode','auto')+'».';
 if(Math.abs(total-100)<0.001)return '';
 const pct=x=>(x/total*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%';
 return 'Сумма долей '+total.toLocaleString('ru-RU',{maximumFractionDigits:1})+'%, а не 100% — каждая доля делится на сумму: БРИДЖ '
  +pct(v[0])+', ПФ '+pct(v[1])+', капитал '+pct(v[2])+'.';
}
function refreshVriSharesNote(){
 const el=document.getElementById('vriSharesNote');
 if(el)vriNoteFill(el,vriSharesNote());
}

// Район и ТТК для льготы за МПТ — из участка проекта, без ручного выбора.
// Проект из пресета или сохранённый без разбора кадастра несёт номера
// участков (поле участка, выписка ЕГРН), но не разбор ГлавАПУ, а район и
// признак ТТК даёт только он. Тогда разбор запрашивается сам — один раз на
// набор номеров — и ложится в `_cadastral_analysis`, того же владельца
// (`site_position`), что после кнопки анализа. ТЭП и площадь он не трогает.
let sitePositionRun={key:'',state:'',error:'',count:0};
function sitePositionNumbers(){
 const out=new Set(projectCadastral().map(String));
 ((inputs._land_lookup||{}).results||[]).forEach(r=>{
  const num=String((r||{}).cadastral_number||'');
  if(r&&r.found!==false&&CADASTRAL_NUMBER_RE.test(num))out.add(num);
 });
 return Array.from(out).filter(x=>CADASTRAL_NUMBER_RE.test(x)).slice(0,30);
}
function sitePositionWanted(b,basis){
 if(!b||!b.mpt_reason||b.override||basis!=='project_benefits')return false;
 if(classRegion()!=='msk')return false;
 const facts=projectParcelFacts();
 const hand=String(inputs.parking_district||'').trim()&&String(inputs.parking_inside_ttk||'').trim();
 return !hand&&!(facts&&facts.district&&facts.ttk);
}
async function resolveSitePosition(){
 const numbers=sitePositionNumbers();
 if(!numbers.length)return;
 const key=numbers.join(',');
 if(sitePositionRun.key===key)return;
 sitePositionRun={key:key,state:'running',error:'',count:numbers.length};
 try{
  const response=await fetch('/cadastral/analyze',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({cadastral_numbers:numbers.join(', ')})});
  const raw=await response.text();
  let data={};try{data=raw?JSON.parse(raw):{}}catch(e){}
  if(!response.ok)throw new Error('разбор кадастра ответил '+response.status+(data.detail?': '+data.detail:''));
  // Пока шёл запрос, открыли другой проект — ответ не его.
  if(sitePositionNumbers().join(',')!==key)return;
  if(!(data.recognized||[]).length)throw new Error('разбор кадастра не распознал номера участка');
  cadastralAnalysis=data;
  inputs._cadastral_analysis=cloneValue(data);
  const t=data.territory||{};
  sitePositionRun.state=(t.district&&(t.inside_ttc===true||t.inside_ttc_known===true))?'done':'partial';
  if(typeof renderCadastralPreview==='function')try{renderCadastralPreview(data)}catch(e){}
 }catch(e){
  sitePositionRun.state='error';
  sitePositionRun.error=String((e&&e.message)||e);
 }
 calculate();
}
function sitePositionNote(){
 const r=sitePositionRun;
 if(r.state==='running')return '<div class="note vri-site-position" style="color:#555">Определяю район и положение относительно ТТК по участку проекта (разбор кадастра, номеров: '+r.count+')…</div>';
 if(r.state==='error')return '<div class="note vri-site-position" style="color:#b3261e">Район и ТТК по участку определить не удалось: '+escapeHtml(r.error)+
  '. Выберите «Район участка» и «Положение относительно ТТК» в карточке «Участок» или повторите разбор кадастра.</div>';
 return '';
}
function vriReliefSourceNote(){
 const src=inputs._vri_relief_source;
 if(!src)return '';
 if(!src||inputs.vri_relief_mode!=='amount'||Math.abs(Number(inputs.vri_relief_mln||0)-Number(src.value||0))>0.0005)return '';
 return '<div style="font-size:11px;color:#777;margin-top:4px">Сумма: '+escapeHtml(src.by||'')+'</div>';
}
// Почему графика ВРИ нет — настоящей причиной. Плата, снятая льготой
// целиком, — не «изменение не требуется»: так и сказано, с суммами.
function vriEmptyReason(vri){
 const t=(vri&&vri.totals)||{};
 const gross=Number(t.gross||0), relief=Number(t.relief||0);
 const mln=v=>(v/1e6).toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽';
 if(gross>0&&relief>0&&relief>=gross-0.5)
  return 'Плата за изменение ВРИ '+mln(gross)+' снята льготой полностью — к оплате 0, график платежей не строится.';
 if(!(gross>0))return 'Плата за изменение ВРИ в проекте равна нулю: сумма платы не задана и не посчитана — график не строится.';
 return 'Сумма обязательства по ВРИ равна нулю — график не строится.';
}
function renderVri(vri){
 const reliefBasis=((vri&&vri.totals)||{}).relief_basis;
 // Не хватает района или ТТК, а номера участка есть — спросить разбор
 // кадастра самим, а не ждать ручного выбора.
 if(sitePositionWanted(vri&&vri.benefits,reliefBasis))resolveSitePosition();
 renderVriBenefits(vri&&vri.benefits,reliefBasis);
 fillVriReliefOffer();
 renderKrtVriFooter();
 syncVriRequiredBox();
 if(typeof window.mptOverrideChanged==='function')window.mptOverrideChanged();
 const REGION={msk:'Москва',mo:'Московская область'};
 const MODE={lump:'единовременно',installment:'рассрочка'};
 const t=(vri&&vri.totals)||{};
 // Льгота на всю плату даёт «к оплате 0» и пустой график, но результат не
 // пропадает: «до льготы − льгота = 0» видно так же, как любая другая сумма.
 // Прежде блок прятался, и смена льготы выглядела как «ничего не пересчиталось».
 const enabled=!!(vri&&(vri.enabled||Number(t.relief||0)>0));
 const list=(vri&&vri.warnings)||[];

 // Карточка в отчёте.
 const card=document.getElementById('vriCard');
 if(card){
   card.style.display=enabled?'':'none';
   if(enabled){
     const basis=(vri.settings&&vri.settings.obligation_basis)||'';
     document.getElementById('vriMode').textContent=
       (REGION[vri.region]||vri.region||'')+' · '+(MODE[vri.payment_mode]||vri.payment_mode||'')+(basis?' · '+basis:'');
     document.getElementById('vriTotalsTable').innerHTML=vriTotalsRows(t,(lastResult||{}).summary);
     document.getElementById('vriScheduleTable').innerHTML=vriScheduleRows(vri.rows);
     const warn=document.getElementById('vriWarnings');
     warn.style.display=list.length?'':'none';
     warn.innerHTML=list.map(w=>`<div>${escapeHtml(w)}</div>`).join('');
   }
 }

 // Своя вкладка: те же цифры рядом с вводными.
 const tab=document.getElementById('vriTabCard');
 const empty=document.getElementById('vriTabEmpty');
 if(!tab)return;
 tab.style.display=enabled?'':'none';
 // Графика нет и тогда, когда льгота сняла плату целиком: итоги видны, а
 // строка под ними говорит, почему платежей нет.
 const noSchedule=!(vri&&vri.enabled);
 if(empty)empty.style.display=noSchedule?'':'none';
 const emptyNote=document.getElementById('vriTabEmptyNote');
 if(emptyNote&&noSchedule)emptyNote.textContent=vriEmptyReason(vri);
 if(!enabled)return;
 document.getElementById('vriTabTotals').innerHTML=vriTotalsRows(t,(lastResult||{}).summary);
 document.getElementById('vriTabSchedule').innerHTML=vriScheduleRows(vri.rows);
 const tabWarn=document.getElementById('vriTabWarnings');
 tabWarn.style.display=list.length?'':'none';
 tabWarn.innerHTML=list.map(w=>`<div>${escapeHtml(w)}</div>`).join('');
}

function applyScenario(name){
 const sc=SCENARIOS[name]||SCENARIOS.base;
 inputs.scenario_revenue_multiplier=Number(sc.scenario_revenue_multiplier||1);
 inputs.scenario_cost_multiplier=Number(sc.scenario_cost_multiplier||1);
 scenarioSelect.value=name;
 renderScenarioNote();
 calculate();
}

function renderScenarioNote(){
 const rev=Number(inputs.scenario_revenue_multiplier||1);
 const cost=Number(inputs.scenario_cost_multiplier||1);
 const revPct=Math.round((rev-1)*100);
 const costPct=Math.round((cost-1)*100);
 const box=document.getElementById('scenarioNote');
 if(box){
   const f=v=>v===0?'без корректировки':(v>0?'+':'')+v+'%';
   box.textContent=`Доходы ${f(revPct)} · расходы ${f(costPct)}`;
 }
}

// Средняя квартира — то, чем строка квартир себя выдаёт. Число квартир
// приходит из четырёх мест и площадью не пересчитывается нигде: выгрузка
// ГлавАПУ (строка 5), передача площадки КРТ (средний ПРОДАННЫЙ лот у соседей —
// на живом примере 36 м²), расчёт Подмосковья (поле «средняя квартира», 58,75)
// и норматив Москвы (33 м² на жителя × 2,1 — те же числа, что в паркинге).
// На 136 818 м² это 3 800 квартир против 1 974, и на экране они выглядели
// одинаково достоверно (владелец, 03.09.2026: «должно же быть 1974»).
// Считается от того, что в строке СЕЙЧАС: отметка о происхождении устарела бы
// молча, а частное от деления — нет.
function apartmentUnitsNote(){
 const row=tep.apartments||{};
 const saleable=Number(row.saleable||0), units=Number(row.units||0);
 if(saleable<=0||units<=0)return '';
 const per=saleable/units;
 // Норматив считается ТЕМ ЖЕ порядком, что в движке: сначала население по
 // 33 м², потом квартиры по 2,1 человека — с округлением вверх на каждом шаге.
 // Одним делением на 69,3 выходит то же самое не всегда: два округления вверх
 // и одно — разные действия, и подпись, разошедшаяся с расчётом на единицу,
 // читалась бы как ошибка расчёта.
 const perPerson=Number(PARKING_2118.sqm_per_person||33);
 const household=Number(PARKING_2118.household||2.1);
 const norm=perPerson*household;
 const byNorm=Math.ceil(Math.ceil(saleable/perPerson)/household);
 // `_manual_tep_import` объявлен ниже по файлу: до его объявления обращение
 // по имени падает (temporal dead zone), а `renderTep` зовётся раньше — из
 // `syncTep` при загрузке. Спрашиваем через `typeof`: функция, читающая то,
 // чего может ещё не быть, обязана это проверять.
 const handover=(typeof _manual_tep_import!=='undefined')?_manual_tep_import:null;
 const source=inputs._glavapu_import?'из выгрузки ГлавАПУ'
   :((handover&&handover.source&&handover.source.kind==='krt')
     ?'из передачи площадки КРТ':'наше');
 // С чем сверять — решает источник, а не привычка. Выгрузку ГлавАПУ сверять не
 // с чем вовсе: город сказал число квартир, и наш делитель был бы вторым
 // ответом на его вопрос. У Подмосковья своя мера — РНГП области; у собранного
 // руками — рынок, 60 м² (решение владельца, 03.09.2026). Норматив Москвы
 // 33 × 2,1 меряет НАСЕЛЕНИЕ и на роль средней квартиры не годится.
 const region=classRegion()==='mo'?'mo':'manual';
 const yard=AVERAGE_FLAT[region]||AVERAGE_FLAT.manual;
 const byYard=yard&&yard.sqm>0?Math.ceil(saleable/yard.sqm):0;
 // Выгрузка ГлавАПУ: число квартир — выход формулы города, и с 09.09.2026 оно
 // идёт за метрами (решение владельца). Значит подпись «от площади не
 // пересчитывается» тут больше не верна, а совпадение с формулой спрашивается,
 // а не хранится: хранимая производная расходится с правилом молча.
 if(inputs._glavapu_import){
  if(byNorm>0&&units===byNorm){
   return `Средняя квартира ${num(Math.round(per*10)/10)} м² — число квартир по формуле`
    + ` ГлавАПУ: население по ${num(perPerson)} м², квартиры по ${String(household).replace('.',',')}`
    + ` жителя. Правка метров его двигает.`;
  }
  // «Вписано руками» — утверждение о происхождении, которого подпись не знает:
  // число могло прийти из выгрузки и просто не сойтись с формулой на новых
  // метрах. Называем то, что видно: источник и расхождение.
  return `Средняя квартира ${num(Math.round(per*10)/10)} м² — число квартир из выгрузки`
   + ` ГлавАПУ, и с его формулой на этих метрах не сходится`
   + (byNorm>0?`: по ней вышло бы ${num(byNorm)}.`:'.');
 }
 let off='';
 if(byYard>0&&Math.abs(units-byYard)/byYard>=0.15){
  off=` При средней квартире ${num(Math.round(yard.sqm*10)/10)} м² (${escapeHtml(yard.basis)})`
   +` вышло бы ${num(byYard)}.`;
 }
 // Норматив Москвы называется только тогда, когда число квартир к нему близко
 // и человек может принять его за меру квартиры: 69,3 м² — это про жителей.
 const cityNote=(region!=='mo'&&byNorm>0
   &&Math.abs(units-byNorm)/byNorm<0.02)
  ? ` Это норматив населения Москвы (${num(Math.round(norm*10)/10)} м² на жителя×домовладение), а не мера квартиры.`
  : '';
 return `Средняя квартира ${num(Math.round(per*10)/10)} м² — число квартир ${escapeHtml(source)}`
   + ` и от площади не пересчитывается.${off}${cityNote}`;
}

function renderTepUndergroundNote(aboveGns,underGns){
 const box=document.getElementById('tepUndergroundNote');
 if(!box)return;
 if(!underGns){box.textContent='';return}
 box.textContent=`Итог ГНС — наземная площадь: ${num(aboveGns)} м². `
  +`Подземная часть (${storagePlacementWords()}) ${num(underGns)} м² — `
  +`у неё своя экономика и в ГНС она не входит. `
  +`${TERMS.total_area.name} ${num(aboveGns+underGns)} м².`;
}

function projectParking(){
 // Норматив и собственный паркинг объекта — величины ПРОЕКТА, и вид на экране
 // их не меняет. Читать их из `lastResult` было нельзя: он идёт за выбранной
 // вкладкой отчёта (`selectReportView`), и у свода очередей блока паркинга не
 // было вовсе — подпись под полем уходила в «Расчёт не выполнен» при
 // посчитанной модели и советовала проверить вход (владелец, 14.09.2026).
 // Хуже второе: `renderObjectParkingNote` не только объясняет, но и ПИШЕТ
 // норму в поля проекта. На вкладке одной очереди там лежит её собственный
 // паркинг — у очереди без объекта это ноль, — и переключение вида молча
 // обнуляло бы гараж проекта.
 if(phaseBundle&&phaseBundle.mode==='phased'&&phaseBundle.consolidated)
  return (phaseBundle.consolidated.parking)||{};
 return ((lastResult||{}).parking)||{};
}

// Обеспеченность парковкой — подпись движка «N мест / M по норме = K×»
// (`parking_provision`, #656): весь гараж проекта на всю нормативную
// потребность. Страница не делит сама — плашка и сводка в чат читают это.
function parkingProvisionText(){return String((projectParking().provision||{}).label||'')}

// Чей норматив — говорит расчёт (`PARKING_NORM_OF` движка), а не подпись:
// у области он свой, и московское имя под областным числом было бы неправдой.
function parkingNormOf(){return String(projectParking().norm_of||'(документ расчёт не назвал)')}

function objectParkingNote(key){
 const own=(projectParking().own)||[];
 const item=own.find(o=>o&&o.tep_key===key&&o.enabled);
 if(!item||!item.units)return '';
 const where=`${num(item.under_spaces)} в подземном, ${num(item.over_spaces)} на первых этажах`;
 const sold=item.sellable
   ?`продаётся ${num(item.saleable_units)}${item.guest_spaces?`, гостевых ${num(item.guest_spaces)}`:''}`
   :'не продаются — обеспеченность посетителей';
 return `Паркинг объекта: ${num(item.units)} м/м (${where}), `
  +`${num(item.under_gns)} м² подземной части, ${sold}`
  +(Number(item.over_gba_sqm||0)>0
    ?`; места первых этажей занимают ${num(item.over_gba_sqm)} м² ГНС здания — продаваемая объекта меньше на ${num(item.saleable_taken_sqm)} м²`
    :'')
  +` · ${item.by_norm?'по нормативу '+parkingNormOf():'задано руками'}`;
}

// Какие поля паркинга объекта тронуты руками. Список заводится в момент, когда
// проект приходит на страницу: в этот момент норма в поля ещё ничего не
// писала, значит непустое число — человеческое. Без такого посева проект,
// сохранённый до правки, потерял бы вписанные числа при первом же пересчёте.
const OBJECT_PARKING_PREFIXES=STANDALONE_OBJECTS.filter(o=>o.garage).map(o=>o.prefix);
// Проектный подземный паркинг — такой же паркинг, только поля у него зовутся
// иначе. Прежде посев выводил имя поля из приставки (`pfx+'_parking_under_spaces'`),
// и места в списке ему не было вовсе: пару заполняла норма при загрузке
// сохранённого проекта, а дальше строка ТЭП замирала. Измерено 13.09.2026:
// первый визит 1199 мест идут за нормой, возврат — пара 1199 заполнена, и
// удвоение квартир поднимает норму до 2397 при строке, застывшей на 1199.
// Карта — один ответ на «где лежит число этого паркинга», и по ней идёт посев.
const PROJECT_PARKING_KEY='underground';
// Карта «где лежит число этого паркинга» строится из реестра, а не
// перечисляется: список объектов объявлен один раз, и вторая его жизнь
// молчала бы ровно на том объекте, ради которого реестр и заведён.
const PARKING_OWNER_FIELDS=Object.fromEntries(
 OBJECT_PARKING_PREFIXES.map(p=>[p,[p+'_parking_under_spaces',p+'_parking_over_spaces']])
  .concat([[PROJECT_PARKING_KEY,['underground_manual_spaces','underground_manual_gns_sqm']]]));
function parkingByHand(key){return (inputs._parking_by_hand||[]).includes(key)}
function parkingByNorm(key){return (inputs._parking_by_norm||[]).includes(key)}
// Пара «места ↔ площадь» подземного паркинга — решение человека? Тот же
// предикат, что у движка (`underground_parking_by_hand`): пометка руки сильнее
// пометки нормы, пара без пометок — человеческая. Страница прежде читала
// всякое непустое поле как ручное и ставила в строку ТЭП число поля, а движок
// по пометке нормы считал норму: на экране 201 место и 7 538 м², в расчёте
// 264 и 9 900 (или 7 537,5 против округлённых 7 538).
function undergroundPairByHand(){
 if(parkingByHand(PROJECT_PARKING_KEY))return true;
 if(parkingByNorm(PROJECT_PARKING_KEY))return false;
 return true;
}
function seedParkingByHand(){
 // Список приехал вместе с проектом — он и есть ответ, пересев затёр бы его:
 // заполненное нормой поле стало бы «тронутым руками» и замерло бы навсегда.
 if(Array.isArray(inputs._parking_by_hand))return;
 // Иначе непустое поле читается как вписанное руками — и в этом ловушка:
 // норма САМА заполняет поле с 07.09.2026, а при следующей загрузке её же
 // число неотличимо от человеческого. На живом проекте офисы замерли на
 // 2 956 мест при норме 134 286 (владелец, 09.09.2026: «машиноместа не
 // пересчитались вообще»). Поэтому норма помечает своё число (`_parking_by_norm`),
 // и посев такие поля тронутыми не считает.
 const byNorm=new Set(Array.isArray(inputs._parking_by_norm)?inputs._parking_by_norm:[]);
 // Проектный подземный здесь намеренно НЕ засевается: его пару заполняет
 // норма, и на этом шаге `tep` ещё не загружен — сравнить с нормой нечем.
 // Решает `fillUndergroundFromTep`, когда ТЭП уже на месте.
 inputs._parking_by_hand=Object.keys(PARKING_OWNER_FIELDS).filter(key=>
  key!==PROJECT_PARKING_KEY&&!byNorm.has(key)&&
  PARKING_OWNER_FIELDS[key].some(field=>Number(inputs[field]||0)));
}

function markParkingByNorm(prefix){
 // Число поставила норма — значит оно ЕЁ, и переживать загрузку обязано
 // именно так. Из «тронутых руками» prefix при этом уходит: иначе один
 // список говорит «моё», второй «человеческое», и кто прав — решает порядок.
 const norm=new Set(Array.isArray(inputs._parking_by_norm)?inputs._parking_by_norm:[]);
 norm.add(prefix);inputs._parking_by_norm=Array.from(norm);
 if(Array.isArray(inputs._parking_by_hand))
  inputs._parking_by_hand=inputs._parking_by_hand.filter(x=>x!==prefix);
 if(prefix===PROJECT_PARKING_KEY)delete inputs._underground_hand_norm;
}

function restoreParkingNorm(prefix){
 // Обратная кнопка к «вписал руками». У всякого замка спрашивают, чем его
 // открыть: без неё поле старого проекта заперто навсегда, а замершее число
 // на экране выглядит посчитанным.
 inputs._parking_by_hand=(inputs._parking_by_hand||[]).filter(x=>x!==prefix);
 markParkingByNorm(prefix);
 calculate();
}
function reconcileLegacyParking(){
 // «Не работает только если грузить сохранённый проект; если заново вбить ТЭП,
 // всё работает» (владелец, 09.09.2026) — и это ровно тот признак: посев видит
 // непустое поле и объявляет его человеческим, а поставила его норма.
 //
 // Пометок у такого проекта нет вовсе, и разобрать по ним нечего. Зато есть
 // сравнение: если в поле стоит ровно то, что даёт норма на ТЕХ ЖЕ вводных, —
 // это её число, и другого объяснения совпадению до единицы нет. Сейчас оно
 // не меняет ничего (числа и так равны), но со следующей правки ТЭП поле
 // снова идёт за нормой, а не замирает.
 //
 // Ошибиться можно в одну сторону: человек вписал ровно норму. Тогда его
 // число сегодня то же самое, подпись честно скажет «по нормативу», и одна
 // правка руками возвращает замок. Обратная ошибка дороже: замершее поле на
 // экране выглядит посчитанным, а расходится на два порядка.
 if(Array.isArray(inputs._parking_by_norm))return;
 ((projectParking().own)||[]).forEach(item=>{
  if(!item||!item.prefix)return;
  const req=Number(item.required_spaces||0);
  if(req<=0)return;
  const under=Number(inputs[item.prefix+'_parking_under_spaces']||0);
  const over=Number(inputs[item.prefix+'_parking_over_spaces']||0);
  if(under===req&&over===0)markParkingByNorm(item.prefix);
 });
 if(!Array.isArray(inputs._parking_by_norm))inputs._parking_by_norm=[];
}

function markParkingByHand(prefix){
 const marks=new Set(inputs._parking_by_hand||[]);
 marks.add(prefix);
 inputs._parking_by_hand=Array.from(marks);
 // Тронутое руками перестаёт быть числом нормы — иначе посев вернёт его ей.
 if(Array.isArray(inputs._parking_by_norm))
  inputs._parking_by_norm=inputs._parking_by_norm.filter(x=>x!==prefix);
 if(prefix===PROJECT_PARKING_KEY)pinUndergroundHandNorm();
}

// Вписанное руками число подземного паркинга живёт до следующей правки ТЭП:
// «если мы увеличили квартиры после того, как что-то ввели вручную, должен
// быть пересчёт, а дальше можно опять руками поправить» (владелец,
// 05.10.2026). Чтобы отличить «ТЭП не трогали» от «ТЭП поменяли», рядом с
// замком хранится норма, при которой число вписали: разошлась — замок снят.
// Сравниваются МЕСТА, а не метры: норматив площади на место меняет метры при
// тех же квартирах, и это правка пары, а не ТЭП (`syncUndergroundPair`).
function pinUndergroundHandNorm(){
 const p=parkingRequirement();
 inputs._underground_hand_norm=p&&p.spaces>0?Math.round(p.spaces):0;
}

// Норма стоит У ТОГО ПОЛЯ, которое человек правит. Прежде число жило одной
// плашкой под последним полем группы (ФОК): смотришь на офисы — ответ через
// два экрана, а на телефоне и вовсе не найти («а где посмотреть сколько по
// нормативу то этому?», владелец, 07.09.2026). Приставку поля несёт сам
// объект (`prefix`), второй карты «какое поле у какого объекта» здесь нет.
// Число не считается: берётся из результата, посчитанного движком.
// Сколько строим против того, сколько положено, — одним ответом на двух
// читателей: текст подписи и её тон. Второй счёт той же разницы однажды
// покрасил бы спокойным то, о чём подпись говорит «дефицит».
//
// Считать это обязана страница, а не сервер: оба слагаемых уже лежат в его
// ответе (`required_spaces` и `units`), и разницу двух его же чисел он не
// пересчитывает — здесь нет экономики, есть вычитание.
function objectParkingGap(item){
 const required=Number((item||{}).required_spaces||0);
 const built=Number((item||{}).units||0);
 return {required:required,built:built,diff:built-required};
}

function objectParkingFieldNote(prefix){
 const own=(projectParking().own)||[];
 const item=own.find(o=>o&&o.prefix===prefix);
 // Расчёта не было — норме взяться неоткуда, и молчать об этом нельзя.
 // Число мы намеренно не показываем (прежнее под новыми вводными читалось бы
 // как посчитанное), но ПРИЧИНУ обязаны: на экране иначе стоят обещание в
 // подсказке и ноль в поле, а по той же подсказке ноль значит «гаража нет»
 // (экран владельца, 08.09.2026, объект уже включён). Расчёт закрыт входом
 // (`calc_requires_login`), и на телефоне вход бывает не тот, что на ноутбуке:
 // хранилище у каждого браузера своё.
 if(!projectParking().own)
  return 'Расчёт не выполнен — норматив появится после пересчёта. '
   +'Если модель не считается, проверьте вход: расчёт закрыт входом через бота.';
 // Расчёт есть, а объекта в его ответе нет — так бывает, когда галочку
 // включили только что: `own` собран прежним прогоном. Молчать здесь нельзя:
 // в полях стоят нули, а по подписи ноль значит «гаража нет» — то есть
 // молчание превращается в утверждение, которого человек не делал.
 if(!item)return !!inputs[prefix+'_enabled']
  ?'Объект включён, но расчёт этого ещё не видел — норматив встанет после пересчёта.'
  :'Объект выключен — мест нет и норматив не считается. '
   +'Включите объект выше, и поля заполнятся нормой.';
 // Выключенный объект не строится — значит и мест у него нет, и норматив ему
 // не считается. Прежде подпись здесь просто МОЛЧАЛА, а подсказка у поля
 // обещала норму безусловно: на экране выходило обещание, ноль и тишина, —
 // и по той же подсказке ноль читается как «гаража нет, вписано руками»
 // (экран владельца, 08.09.2026: «как было так и есть»). Молчание объясняют
 // там, где на него смотрят.
 // Ответ расчёта старше галочки — обычное дело: признак только что тронули, а
 // пересчёт ещё идёт. Сказать в этот момент «объект выключен» значит соврать о
 // том, что человек видит собственными глазами строкой выше.
 const onNow=!!inputs[prefix+'_enabled'];
 if(!item.enabled&&onNow)
  return 'Объект включён, но расчёт этого ещё не видел — норматив встанет после пересчёта.';
 if(!item.enabled)return 'Объект выключен — мест нет и норматив не считается. '
  +'Включите объект выше, и поля заполнятся нормой.';
 const req=Number(item.required_spaces||0);
 // Число уже стоит В ПОЛЕ, повторять его здесь незачем: одно и то же дважды
 // подряд перестают читать. Подпись отвечает на другое — чьё оно и что будет,
 // если поле тронуть.
 if(item.by_norm)return req
  ?'Оба числа выше поставил норматив '+parkingNormOf()+' — они следуют за ТЭП. '
   +'Впишите своё, чтобы перебить; ноль руками значит «гаража нет».'
  :'По нормативу '+parkingNormOf()+' мест не требуется.';
 // Замок обязан называть, чем его открыть. Проект, сохранённый до того, как
 // норма начала заполнять поле, приходит без списков — и её же число читается
 // как человеческое и замирает: на живом проекте офисы стояли 2 956 при норме
 // 134 286 (владелец, 09.09.2026: «машиноместа не пересчитались вообще»).
 // Разойтись эти два числа могут на два порядка, поэтому норматив называется
 // рядом, а путь назад — очистить поле — сказан прямо.
 const back=' Очистите поле — вернётся норматив и снова пойдёт за ТЭП.';
 if(!req)return 'Задано руками. По нормативу '+parkingNormOf()+' мест не требуется.' + back;
 // Норматив — обязательство ОБЪЕКТА, а не одного из двух полей: места при
 // объекте бывают и под ним, и на первых этажах. Пока это не сказано, число
 // под полем «мест на первых этажах» читается как норма ЭТОГО поля.
 //
 // И главное, ради чего строка переписана: у величины есть мера, а сравнения
 // с ней рядом не стояло. Владелец вписал 500 мест на первые этажи, подземные
 // остались нормативными 1 493 — строится 1 993 при норме 1 493, — и на
 // экране об этом не было ни слова («почему подземная не изменилась», 
 // 13.09.2026). Обратная сторона молчала так же: 400 мест при норме 1 590
 // печатались двумя числами подряд, а дефицит в 1 093 места числом не
 // назывался. Оба случая модель знала и не говорила.
 const gap=objectParkingGap(item);
 const norm=`Задано руками. Норматив ${parkingNormOf()} — ${num(req)} мест на объект: `
  +'это оба поля вместе, под зданием и на первых этажах.';
 // Перебор — решение человека, а не ошибка, поэтому он назван, но не
 // выделен: он же и подсказывает, на сколько можно снизить подземные.
 if(gap.diff>0)return norm
  +` Строим ${num(gap.built)} — на ${num(gap.diff)} больше положенного;`
  +` на столько же можно снизить места в подземном.` + back;
 if(gap.diff<0)return norm
  +` Строим ${num(gap.built)} — дефицит ${num(-gap.diff)} мест.` + back;
 return norm + ` Строим ровно норматив.` + back;
}

function renderTep(){
 repairParkingFromGlavapu();
 const body=tepBody;body.innerHTML='';
 const importedParking=parkingRequirement();
 const groups=tepGroupRows();
 groups.forEach(group=>{
  // Заголовок раздела рисуется, только когда разделов больше одного:
  // единственный раздел — это та же таблица с лишней строкой над ней.
  if(groups.length>1){
   const head=document.createElement('tr');
   head.className='tep-group';
   head.innerHTML=`<th colspan="7"><span class="tep-sticky">${escapeHtml(group.title)}</span></th>`;
   body.appendChild(head);
  }
  group.keys.forEach(key=>{
   const row=tep[key];
   const tr=document.createElement('tr');
   // МКД в нежилом проекте нет. Строка не убирается, а запирается и называет
   // причину: молча выброшенная читается как отсутствие такого продукта у
   // модели вообще.
   const mkdLocked=withoutHousing()&&MKD_PRODUCTS.includes(key);
   let label=row.label;
   if(mkdLocked){
    label+=' <span class="tep-note">Нежилой проект: МКД в нём нет — строка обнулена и заперта. '+projectKindWhereNote()+'</span>';
   }
   if(key==='underground_parking'&&inputs.underground_parking_disabled){
     const shortfall=undergroundShortfallNote();
     label+=` <span class="tep-note">Подземного паркинга нет — потребность закрывает наземный. Включить обратно: раздел «Подземный паркинг».</span>`;
     if(shortfall)label+=` <span class="tep-note bad">${shortfall}</span>`;
   }
   else if(key==='underground_parking'&&(Number(inputs.underground_manual_spaces||0)>0||Number(inputs.underground_manual_gns_sqm||0)>0)){
     const per=undergroundAreaPerSpace();
     const spaces=Number(tep.underground_parking.units||0);
     const area=Number(tep.underground_parking.gns||0);
     const shortfall=undergroundShortfallNote();
     // Подпись отвечает на два вопроса, и оба сказаны числом. ЧЬЁ это число:
     // пару заполняет норма, и её же результат под словом «задано проектом»
     // читался как решение человека — признак у этого явный, а не выведенный
     // из совпадения с нормативом. И КАК оно получено: печатается фактический
     // показатель, площадь ÷ места, потому что подпись утверждает равенство, и
     // с чужим множителем оно не сходилось («3 194 м/м × 37,5 = 111 790 м²»
     // при 119 775 по арифметике). Норматив класса называется рядом ровно
     // тогда, когда он расходится: два числа об одной величине, стоящие
     // молча, читаются как одно.
     const byHand=parkingByHand(PROJECT_PARKING_KEY);
     const factPer=spaces>0?area/spaces:per;
     label+=` <span class="tep-note">${byHand?'Решение проекта':'По нормативу'}: ${num(spaces)} м/м × ${num(factPer)} м²/место (гросс) = ${num(area)} м². Менять — в разделе «Подземный паркинг»${byHand?'; правка ТЭП вернёт норматив, очистить поле — вернуться к нему сейчас':''}.`
      +(spaces>0&&Math.abs(factPer-per)>0.05
        ? ` Норматив класса — ${num(per)} м²/место: площадь задана и его не применяет.`
        : '')
      +`</span>`;
     if(shortfall)label+=` <span class="tep-note bad">${shortfall}</span>`;
   }
   if(key==='underground_parking'&&importedParking){
     label+=` <span class="tep-note">Потребность: ${num(importedParking.permanent)} постоянных + ${num(importedParking.guest)} гостевых${importedParking.mfc?` + ${num(importedParking.mfc)} МФК`:''} = ${num(importedParking.spaces)} м/м · ${escapeHtml(importedParking.basis||'')}</span>`;
   }
   // Прежде здесь стояла кнопка «⟳ по пропорциям»: она пересчитывала строку от
   // ГНС нашими долями. Доли теперь правятся под таблицей и пересчитывают строку
   // сами, как только их поменяли (просьба владельца, 20.08.2026), — кнопка,
   // делающая то же самое чужими числами, стала лишней дверью в ту же комнату.
   // Галочки полей, чей дом — эта строка ТЭП (`TEP_ONLY_INPUTS`): размещение
   // кладовых правится здесь, а не складкой во «Вводных» (владелец, 16.10.2026).
   label+=tepRowSwitches(key);
   if(key==='apartments'){
     const note=apartmentUnitsNote();
     if(note)label+=` <span class="tep-note">${escapeHtml(note)}</span>`;
   }
   // Паркинг объекта — своя подстрока под строкой объекта (ниже), а не
   // приписка к его имени: подписью под «Офисами» места читались деталью
   // офиса, а не продуктом, и их не находили (владелец, 24.09.2026).
   const parkNote=objectParkingNote(key);
   // Какое из двух чисел чьё — иначе вписанное «по решению КРТ» молча
   // становится не тем: решение задаёт площадь В ГАБАРИТАХ НАРУЖНЫХ СТЕН, то
   // есть наземную, а поле во вводных называется общей.
   if(TEP_SOCIAL_INPUTS[key]){
     const share=Math.round(socialTotalShare()*1000)/10;
     label+=String(inputs.social_area_source||'norm')==='manual'
       ? ` <span class="tep-note">`
         +`Площадь в решении о КРТ дана в габаритах наружных стен — это ГНС. `
         +`Правится любое из двух: общая = ГНС × ${landNum(share,1)}%. `
         +`Места — в разделе «Социальная нагрузка».`
         +`${socialNormNote(key)}</span>`
       // Запертая ячейка честнее редактируемой: в нормативном режиме площадь
       // считается от мест, и вписанное вернулось бы к прежнему на первом же
       // пересчёте — молча, то есть неотличимо от «не сработало».
       : ` <span class="tep-note">`
         +`Площадь считается от мест ${moscowSocialStepsApply()
           ?'по нормативу Москвы (2151-ПП)':'по нормативу области (калькулятор МО) / поля'}. Чтобы вписать свою — `
         +`в блоке «Социальная нагрузка» выберите в поле «Как задаются соцобъекты» вариант «Ручной ввод».</span>`;
   }
   if(TEP_RATIOS[key]){
     const own=tepNoteText(key);
     const text=own||tepRowComplaint(key,row);
     const tone=own?tepNoteTone(key):'bad';
     if(text)label+=` <span class="tep-note ${tone}">${escapeHtml(text)}</span>`;
   }
   // Выключенный объект: строка в таблице нулевая, потому что нулевой её видит
   // модель, — но метры человека при этом никуда не делись, и молчать о них
   // нельзя. Прежде такую строку можно было править: правка уходила во вводные
   // поверх сохранённого, и 36 660 м² продаваемой превращались в ноль, а потом
   // во вписанное в соседнюю ячейку число. Теперь ячейки заперты, числа названы,
   // а включить объект можно отсюда же — ходить за галочкой на другую вкладку
   // незачем (замечание владельца, 20.08.2026).
   const rowSwitch=TEP_ROW_SWITCH[key];
   const rowOff=rowSwitch&&!inputs[rowSwitch[0]];
   if(rowOff){
     const map=TEP_ROW_INPUTS[key]||{};
     const savedGns=Number(inputs[map.gns]||0),savedSale=Number(inputs[map.saleable]||0);
     label+=` <span class="tep-note bad">Объект выключен, поэтому в модель не идёт`
       +(savedGns||savedSale?`. Сохранено: ${num(savedGns)} м² ГНС, ${num(savedSale)} м² продаваемой`:'')
       +`. <button type="button" class="tep-refill" onclick="enableTepRow('${key}')">включить объект</button></span>`;
   }
   let html=`<td>${label}</td>`;
   // Доля стоит под тем числом, которое из неё получается: «% ГНС» под общей
   // площадью, «% общей» под продаваемой. Прежде они лежали под раскрытием над
   // таблицей — свёрнутым по умолчанию, и это читалось как «их нет вовсе»
   // (владелец, 21.08.2026). Отдельной колонкой слева было бы непонятно: доля
   // без своего числа рядом не читается.
   const chain=TEP_RATIOS[key]?tepRatioChain(tepRatio(key)):null;
   const own=chain&&tepRatioChangedKeys().includes(key);
   // «% общей» стоит под ПОЛЕЗНОЙ, а не под продаваемой: доля строит вал, а в
   // продаваемой лежит вал МИНУС переданное. Пока передачи нет, числа
   // равны и разницы не видно; при передаче 4 500 м² под 9 420 стояло
   // «72,22 % общей», то есть подпись описывала соседнюю величину — «ну вот
   // как это понимать?» (владелец, 12.09.2026). Правило то же, что было
   // записано здесь с самого начала, просто число сменило колонку.
   const ratioField=col=>{
    if(!chain)return '';
    const which=col==='total_area'?'total':(col==='useful'?'saleable':'');
    if(!which)return '';
    const value=Math.round((which==='total'?chain[0]:chain[1])*1e4)/100;
    const of=which==='total'?'% ГНС':'% общей';
    // Доля стоит ровно под своим числом и по его левому краю: разная ширина
    // без общей раскладки давала лесенку, а ячейки без доли (ГНС) вдобавок
    // центрировались по высоте и уезжали вниз — таблица выглядела кривой
    // (владелец, 23.08.2026).
    return '<div style="margin-top:4px;font-size:11px;color:'+(own?'#a33':'#777')
     +';white-space:nowrap;display:flex;align-items:center;gap:4px">'
     +'<input type="number" step="0.1" min="0" max="100" class="tep-ratio" value="'+value+'" style="font-size:11px;margin:0" '
     +'title="доля, по которой достраивается это число" '
     +'onchange="tepRatioSet(\''+key+'\',\''+which+'\',this.value)"><span>'+of+'</span>'
     +(own&&which==='saleable'?'<button type="button" class="tep-refill" onclick="tepRatioReset(\''+key+'\')">наши</button>':'')
     +'</div>';
   };
   ['gns','total_area','useful','saleable','transfer','units'].forEach(col=>{
     // Соцстрока: правится только пара «ГНС — общая» и только в ручном режиме.
     // Места и передаваемая приходят из вводных на каждом пересчёте, поэтому
     // редактируемая ячейка там обещала бы то, чего не будет.
     const socialLocked=!!TEP_SOCIAL_INPUTS[key]
       &&(String(inputs.social_area_source||'norm')!=='manual'
          ||!['gns','total_area'].includes(col));
     const locked=mkdLocked||socialLocked||rowOff||(key==='underground_parking'&&(importedParking||inputs.underground_parking_disabled||Number(inputs.underground_manual_spaces||0)>0||Number(inputs.underground_manual_gns_sqm||0)>0)&&['gns','total_area','useful','saleable','transfer','units'].includes(col));
     // Два атрибута style на одном input браузер не складывает — берёт первый,
     // и запертая ячейка теряла бы серый фон. Стиль собирается один.
     html+=`<td style="vertical-align:top"><input type="number" step="0.1" value="${inputDisplay(row[col])}" style="margin:0${locked?';background:#f3f3f1;color:#555':''}" ${locked?'readonly':''} onchange="tepCellChanged('${key}','${col}',this.value)">${locked?'':ratioField(col)}</td>`;
   });tr.innerHTML=html;body.appendChild(tr);
   // Своей колонки паркингу не заводим — таблица плотная, и лишние колонки
   // владелец отклонял; подстрока на всю ширину. Текст — тот же
   // `objectParkingNote`, что был подписью: второго описания мест нет.
   // Приём взят из PR #506 (Codex), текст — из единственного источника.
   if(parkNote){
    const park=document.createElement('tr');
    park.className='tep-park';
    park.innerHTML=`<td style="padding-left:14px;color:#555">↳ Паркинг объекта</td>`
     +`<td colspan="6" style="font-size:11px;color:#555;text-align:left"><span class="tep-park-note">${escapeHtml(parkNote)}</span></td>`;
    body.appendChild(park);
   }
  });
  // Подытог раздела — только когда продуктов в нём больше одного: под
  // единственной строкой это она же во второй раз (правило «Итого МКД»).
  const sub=groups.length>1&&group.keys.length>1?tepSubtotalRow(group):null;
  if(sub)body.appendChild(sub);
 });updateTepTotals();renderTepRatioNote();
}

// Подытог раздела. Складывается то же, что стоит в строках, — и у ГНС рядом
// называется подземная часть: наземная и подземная площади в одной колонке
// складываются под одним именем, и без этой приписки сумма читается как
// наземная ГНС, которой она не равна.
// Сколько у строки подземной площади. Правило одно на итог и на подытог:
// подземный продукт целиком плюс собственный гараж отдельно стоящего объекта.
// Две копии этого счёта разошлись бы, и подпись под таблицей спорила бы со
// строкой раздела — оба числа выглядели бы верными.
function tepRowUnderGns(key,row){
 const r=row||{};
 return (undergroundProducts().includes(key)?Number(r.gns||0):0)
  +(Number(r.under_gns||0)||objectGarageUnderGns(key));
}
// Сколько у строки НАЗЕМНОЙ площади — пара к подземной выше. Гараж лежит под
// землёй целиком, кладовые — либо под землёй, либо ВНУТРИ метров квартир, и
// к наземной ГНС их колонка не прибавляется ни в одном случае; правило —
// `ROWS_OUTSIDE_ABOVE_SUM` из движка (`project_above_gns`). Читатели,
// считавшие сами, пропускали один гараж, и кладовые садились в наземную ГНС.
function tepRowAboveGns(key,row){
 return UNDERGROUND_PLACEMENT.outside_above.includes(key)?0:Number((row||{}).gns||0);
}
// Галочки у строки ТЭП из `TEP_ONLY_INPUTS`. Снята — значение `off`, оно же
// умолчание движка: отсутствующий ключ не читается как «стоит».
function tepRowSwitches(key){
 return Object.keys(TEP_ONLY_INPUTS).filter(id=>TEP_ONLY_INPUTS[id].row===key).map(id=>{
  const spec=TEP_ONLY_INPUTS[id];
  const on=String(inputs[id]||'')===spec.on;
  return ` <label class="tep-note tep-switch" title="${escapeHtml(spec.hint)}">`
   +`<input type="checkbox" id="tep_${id}" data-field="${id}" ${on?'checked':''} `
   +`onchange="tepRowSwitchSet('${id}',this.checked)">${escapeHtml(spec.label)}</label>`;
 }).join('');
}
function tepRowSwitchSet(id,checked){
 const spec=TEP_ONLY_INPUTS[id];if(!spec)return;
 inputs[id]=checked?spec.on:spec.off;
 markFieldManual('inputs.'+id);
 renderTep();
 return calculate();
}
// Что под землёй у ЭТОГО проекта — по размещению кладовых (поле проекта).
// Отсутствующий ключ — умолчание движка, а не «наземные».
function undergroundProducts(source){
 const own=(source||inputs||{})[UNDERGROUND_PLACEMENT.field];
 return UNDERGROUND_PLACEMENT.by_placement[own]
  ||UNDERGROUND_PLACEMENT.by_placement[UNDERGROUND_PLACEMENT.default];
}
function storagePlacementWords(){
 return undergroundProducts().includes('storage')
  ?'паркинг, кладовые, гаражи объектов':'паркинг, гаражи объектов';
}
// Метры гаража объекта считает движок (`apply_object_parking`), а таблица ТЭП
// на вводных живёт своими строками, куда их никто не пишет. Подпись «гаражи
// объектов» при этом складывала поле, которое всегда пусто, и гараж офисника
// в 35 000 м² в «подземную часть» не попадал. Число берётся у движка.
function objectGarageUnderGns(key){
 const item=((projectParking().own)||[]).find(o=>o&&o.tep_key===key&&o.enabled);
 return item?Number(item.under_gns||0):0;
}

function tepSubtotalRow(group){
 const cols=['gns','total_area','useful','saleable','transfer','units'];
 const sums={};cols.forEach(c=>sums[c]=group.keys.reduce((a,k)=>a+Number((tep[k]||{})[c]||0),0));
 const under=group.keys.reduce((a,k)=>a+tepRowUnderGns(k,tep[k]),0);
 const tr=document.createElement('tr');
 tr.className='tep-sub';
 // В колонке ГНС стоит НАЗЕМНАЯ площадь — то, что колонка и обещает; подземная
 // названа рядом своим именем. Сумма двух разных величин под одним именем —
 // ровно та ошибка, из-за которой итог таблицы показывал строительный объём.
 tr.innerHTML=`<td>Итого · ${escapeHtml(group.title.toLowerCase())}</td>`
  +cols.map(c=>{
    const value=c==='gns'
      ?group.keys.reduce((a,k)=>a+tepRowAboveGns(k,tep[k]),0)
      :sums[c];
    return `<td>${num(value)}`
     +(c==='gns'&&under>0?`<div class="tep-note">подземная ${num(under)}</div>`:'')
     +`</td>`;
  }).join('');
 // Раздел, где всё по нулям, подытога не получает: строка из шести нулей —
 // это шум, а не полнота, и она разрывает таблицу там, где читать нечего.
 return cols.some(c=>Math.abs(sums[c])>1e-9)?tr:null;
}
// Правка ячейки ТЭП: соседние площади того же продукта достраиваются
// пропорциями, если они пустые. Введённое руками не трогается — иначе человек
// перестанет доверять таблице, в которой его числа меняются сами.
// Пропорции печатаются рядом с таблицей: подставленное число, происхождение
// которого не видно, неотличимо от введённого человеком.
function renderTepRatioNote(){
 // Сами доли теперь стоят в таблице под своими числами, поэтому здесь остаётся
 // только правило и отказ. Раскрытие со списком долей убрано: свёрнутое по
 // умолчанию, оно читалось как «долей нет вовсе» (владелец, 21.08.2026).
 const box=document.getElementById('tepRatioNote');
 if(!box)return;
 const changed=tepRatioChangedKeys();
 const complaint=tepRatioComplaint
  ?'<div style="color:#a33;margin-top:4px">'+escapeHtml(tepRatioComplaint)+'</div>':'';
 // Сокращения расшифровываются ОДИН раз под таблицей, а не в каждой из
 // двенадцати подписей: «ДОО» в строке и «дошкольная образовательная
 // организация» рядом с ним — это одно и то же имя, написанное дважды, и
 // строка продукта от такого только тяжелеет.
 box.innerHTML='<b>ГНС</b> — наземная площадь здания (термин DevelopAid);'
  +' <b>общая</b> — площадь по проектной документации;'
  +' <b>продаваемая</b> — то, что продаём; <b>передаваемая</b> — метры, которые строим и отдаём'
  +' городу. <b>ДОО</b> — детский сад, <b>СОШ</b> — школа, <b>ОСЗ</b> — отдельно стоящее здание.'
  +'<br>Пустые площади достраиваются долями под столбцами; введённое вами не перебивается.'
  +(changed.length
    ?' <span style="color:#a33">Доли изменены вами — они выделены красным и уезжают в проект вместе со вводными.</span>'
    :'')
  +complaint;
}

// Наши доли объявлены один раз — в движке, и подставлены сюда. Правка человека
// живёт строкой во вводных: отдельного хранилища у неё нет, поэтому она
// сохраняется, делится ссылкой и открывается вместе с проектом. Формат тот же,
// что читает движок (`tep_ratios_applied`), и это проверяется тестом — иначе
// одна и та же строка значила бы на двух сторонах разное.
function tepRatioOverrides(){
 const out={};
 String(inputs.tep_ratios_custom||'').replace(/\n/g,';').split(';').forEach(chunk=>{
  chunk=chunk.trim();if(!chunk)return;
  const at=chunk.indexOf(':');if(at<0)return;
  const key=chunk.slice(0,at).trim();if(!TEP_RATIOS[key])return;
  const parts=chunk.slice(at+1).split('/');
  const total=Number(String(parts[0]||'').trim().replace(',','.'));
  const sale=Number(String(parts[1]||'').trim().replace(',','.'));
  if(!(total>0&&total<=100)||!(sale>0&&sale<=100))return;
  out[key]={total_of_gns:total/100,saleable_of_gns:total/100*sale/100,source:'задано вручную'};
 });
 return out;
}

function tepRatio(key){return tepRatioOverrides()[key]||TEP_RATIOS[key]}

// Доли хранятся от ГНС — так они заданы у калькулятора. Человек же читает их
// цепочкой, и вторым числом ему нужна доля от общей: это частное двух долей, а
// не третье хранимое число.
function tepRatioChain(r){
 const total=Number((r&&r.total_of_gns)||0);
 return [total,total>0?Number(r.saleable_of_gns||0)/total:0];
}

function tepRatioChangedKeys(){
 const own=tepRatioOverrides();
 return Object.keys(own).filter(key=>
  Math.abs(own[key].total_of_gns-TEP_RATIOS[key].total_of_gns)>1e-6||
  Math.abs(own[key].saleable_of_gns-TEP_RATIOS[key].saleable_of_gns)>1e-6);
}

let tepRatioComplaint='';

function tepRatioWrite(map){
 inputs.tep_ratios_custom=Object.keys(map).map(key=>{
  const c=tepRatioChain(map[key]);
  const trim=value=>String(Math.round(value*1e4)/1e4);
  return key+':'+trim(c[0]*100)+'/'+trim(c[1]*100);
 }).join(';');
}

// Свободное поле доли — тот же класс ошибки, что дал 238 млрд ₽ платы за ВРИ:
// вписанное число выглядит посчитанным. Общая больше ГНС и продаваемая больше
// общей не бывают, поэтому такое не принимается вовсе, а не принимается с
// оговоркой: оговорку не читают, а метры уезжают в модель.
function tepRatioSet(key,what,value){
 if(!TEP_RATIOS[key])return;
 const pct=Number(String(value==null?'':value).replace(',','.'));
 if(!(pct>0&&pct<=100)){
  tepRatioComplaint=what==='total'
   ?'Общая площадь — от 0 до 100% ГНС: больше ГНС она не бывает. Доля не изменена.'
   :'Продаваемая — от 0 до 100% общей: больше общей она не бывает. Доля не изменена.';
  renderTep();return;
 }
 const own=tepRatioOverrides();
 const chain=tepRatioChain(own[key]||TEP_RATIOS[key]);
 const total=(what==='total'?pct/100:chain[0]);
 const sale=(what==='saleable'?pct/100:chain[1]);
 own[key]={total_of_gns:total,saleable_of_gns:total*sale,source:'задано вручную'};
 tepRatioWrite(own);
 tepRatioComplaint='';
 // Доля без пересчёта — обещание, а не действие: строка осталась бы на прежних
 // метрах, и увидеть новую долю было бы негде.
 if(Number((tep[key]||{}).gns||0)>0||Number((tep[key]||{}).saleable||0)>0)refillTepRow(key);
 else renderTep();
}

function tepRatioReset(key){
 const own=tepRatioOverrides();
 delete own[key];
 tepRatioWrite(own);
 tepRatioComplaint='';
 if(Number((tep[key]||{}).gns||0)>0||Number((tep[key]||{}).saleable||0)>0)refillTepRow(key);
 else renderTep();
}

function tepRowComplaint(key,row){
 const gns=Number(row.gns||0),total=Number(row.total_area||0),sale=Number(row.saleable||0);
 if(total>gns+1&&gns>0)return 'общая площадь больше ГНС — так не бывает, проверьте строку';
 if(sale>total+1&&total>0)return 'продаваемая больше общей — так не бывает, проверьте строку';
 if(gns>0&&sale>0){
  // Доли объявлены от ГНС: продаваемая сравнивается с ней же, иначе сравнение
  // поедет вслед за общей площадью, которая тоже может быть введена неверно.
  const r=tepRatio(key);
  const expected=gns*r.saleable_of_gns;
  if(expected>0&&Math.abs(sale-expected)/expected>0.25)
   return 'продаваемая расходится с пропорцией больше чем на четверть ('+
    landNum(sale/gns*100,0)+'% ГНС против '+landNum(r.saleable_of_gns*100,0)+'%) — проверьте или пересчитайте';
 }
 return '';
}

// Выключатель объекта во вводных: пока он снят, строка обнуляется при каждом
// пересчёте, и любое число в ней исчезает. Молчать об этом нельзя — человек
// жмёт кнопку и видит нули.
// Состав — реестр: объекты, чья строка идёт от метров (у наземного паркинга
// строка от мест, и выключателя в ТЭП у неё нет).
const TEP_ROW_SWITCH=__DEVELOPAID_TEP_ROW_SWITCH__;

// Включать объект за человека нельзя — это меняет экономику проекта. Но и
// отправлять его за галочкой на другую вкладку незачем: решение остаётся за
// ним, а нажатие происходит здесь.
function enableTepRow(key){
 const sw=TEP_ROW_SWITCH[key];
 if(!sw)return;
 inputs[sw[0]]=true;
 setTepNote(key,'');
 syncTep(false);renderInputs();renderTep();
 scheduleTepAutoRecalc(key);
 calculate();
}

// Явный пересчёт строки: человек просит — считаем от ГНС и переписываем всё.
// Пустая строка считаться не из чего: это тоже ответ, и он должен прозвучать.
function refillTepRow(key){
 const r=tepRatio(key);
 if(!r)return;
 const row=tep[key];
 const gns=Number(row.gns||0);
 // Вал полезной площади: продаваемая уже без переданного, полезная — с ним.
 const gross=Math.max(Number(row.useful||0),Number(row.saleable||0)+Number(row.transfer||0));
 const say=text=>{setTepNote(key,text);renderTep()};
 const sw=TEP_ROW_SWITCH[key];
 if(sw&&!inputs[sw[0]]){
  say('Объект выключен во вводных: включите «'+sw[1]+' → Объект включен», иначе строка обнуляется при каждом пересчёте.');
  return;
 }
 if(gns<=0&&gross<=0){
  say('Нечего пересчитывать: впишите ГНС или продаваемую площадь — остальное достроится само.');
  return;
 }
 // Пересобирается ВАЛ, а не остаток: в `saleable` лежит уже вычтенное
 // переданное, и пересчёт от него уменьшал бы строку на него второй раз.
 const base=gns>0?{gns:gns,total_area:0,saleable:0,useful:0}
                 :{gns:0,total_area:0,saleable:gross,useful:0};
 const filled=tepFillByRatios(key,base);
 ['gns','total_area','saleable','useful'].forEach(field=>{row[field]=filled[field]});
 // Переданное вычитается ТЕМ ЖЕ тождеством, что и в правке ячейки:
 // без этого правка доли и кнопка «наши» возвращали отданные метры в продажу
 // (замер 12.09.2026: 4 500 м² квартир снова становились продаваемыми).
 tepApplyTransfer(key,filled.saleable);
 // Жилая СПП двинулась — за ней идёт встроенная коммерция, как и при правке
 // ячейки: правило одно, а закрытое в одном месте соседнее не защищает.
 if(key==='apartments'&&Math.abs(Number(row.gns||0)-gns)>0.05){
  rescaleApartmentUnits();rescaleBuiltInCommercial();
 }
 // Посчитанное возвращается во вводные — иначе `syncTep` вернёт прежнее.
 if(tepRowToInputs(key))renderInputs();
 renderTep();
 scheduleTepAutoRecalc(key);
 calculate();
}

// Ответ кнопки живёт до следующей перерисовки строки. У заметки есть тон:
// жалоба красная, а сообщение о посчитанном — обычная подпись. Красным
// покрашенный пересчёт читается как тревога, а тревожиться не о чем.
const tepRefillNote={};
function setTepNote(key,text,tone){
 if(!text){delete tepRefillNote[key];return}
 tepRefillNote[key]={text:String(text),tone:tone===undefined?'bad':tone};
}
function tepNoteText(key){const n=tepRefillNote[key];return n?n.text:''}
function tepNoteTone(key){const n=tepRefillNote[key];return n&&n.tone?n.tone:''}

// Строки офисов и ТЦ производные: их пересобирает `syncTep` из вводных, и
// вписанное прямо в таблицу исчезало при первом же пересчёте — «в обратную
// сторону не работает» (замечание владельца, 19.08.2026). Число надо не
// защищать от пересчёта, а вернуть туда, откуда пересчёт его берёт.
const TEP_ROW_INPUTS=__DEVELOPAID_TEP_ROW_INPUTS__;
// Соцобъект во вводных живёт ОДНИМ числом — общей площадью, а ГНС из неё
// выводится. Пока обратного пути не было, правка ГНС в таблице не доезжала
// никуда: ячейка выглядела редактируемой, а на следующем пересчёте ГНС
// возвращалась к «общая ÷ доля» (владелец, 03.09.2026: «если тут меняю ГНС,
// то общая не меняется»). Ведущим может быть любое из двух — как у трёх
// площадей продукта.
const TEP_SOCIAL_INPUTS={kindergarten:'social_dou_gba_sqm',
 school:'social_school_gba_sqm',clinic:'social_clinic_gba_sqm'};
// Норматив на место — своё поле у каждого объекта; им меряется и строка
// очереди, и строка проекта.
const SOCIAL_TEP_NORM_INPUTS={kindergarten:'social_dou_norm_sqm',
 school:'social_school_norm_sqm',clinic:'social_clinic_norm_sqm'};
// Доля объявлена в движке и подставлена на страницу; второй копии числа здесь
// нет — она бы разошлась с той, по которой считает `syncTep`.
function socialTotalShare(){
 return Number((TEP_RATIOS.apartments||{}).total_of_gns||0)||0.9;
}

function tepRowToInputs(key){
 const map=TEP_ROW_INPUTS[key];
 if(!map)return false;
 inputs[map.gns]=Number(tep[key].gns||0);
 inputs[map.saleable]=Number(tep[key].saleable||0);
 const sw=TEP_ROW_SWITCH[key];
 if(sw&&!inputs[sw[0]]&&Number(tep[key].gns||0)>0){
  // Выключенный объект обнулит строку на первом же пересчёте. Числа сохранены,
  // но включать объект за человека нельзя: это меняет экономику проекта.
  setTepNote(key,'Площади сохранены во вводных, но объект выключен: включите «'+sw[1]+
   ' → Объект включен», иначе строка обнулится при пересчёте.');
 }
 return true;
}

// Любое из трёх чисел — ведущее: изменили его, и два других пересчитались по
// пропорциям. Правило одно на все случаи, без памяти о том, что человек уже
// правил: «поменять хочется любую площадь» (решение владельца, 19.08.2026).
// Прежняя защита введённого руками давала строку, которую нельзя досчитать: у
// квартир оставался ГНС 50 000 при продаваемой 50 000, и модель считала по
// нелепице, пока человек не удалит ячейку.
function storageAreaPerUnit(){
 // Ноль и пустое значат «умолчание», а не «кладовая без площади»: поле
 // приходит явным нулём, когда его не было в сохранённом проекте.
 return Number(inputs.storage_area_per_unit_sqm||0)||__DEVELOPAID_STORAGE_AREA_PER_UNIT__;
}

function syncStoragePair(changed){
 // Штуки и метры кладовых — одна величина в двух видах, как места и площадь
 // гаража. Жили они независимо: 800 штук давали 0 м², 8 000 м² давали 0 штук
 // (владелец, 14.09.2026: «ввёл в ТЭП 800 штук — ничего не изменилось в
 // площади и наоборот»). Ведущее — ШТУКИ: продаётся кладовая, а не её метр.
 // Вписанную площадь пара НЕ перетирает — она сильнее норматива, и тогда
 // фактическая площадь кладовой видна подписью строки.
 const row=tep.storage;if(!row)return;
 const per=storageAreaPerUnit();if(per<=0)return;
 if(changed==='gns'){
  const area=Number(row.gns||0);
  row.units=area>0?Math.round(area/per):0;
 }else{
  const units=Number(row.units||0);
  row.gns=units>0?Math.round(units*per*10)/10:0;
 }
 row.total_area=row.gns;
}

// Встроенная коммерция первого этажа — доля той же СПП жилых зданий, что и
// квартиры: у ГлавАПУ это 94/6. Правка жилья руками её не двигала — соседние
// строки правка ячейки не трогает вовсе, — и на фактическом ТЭП выходило
// смешанное: квартиры по решению ГЗК, коммерция нормативная. Молчали при этом
// не только метры: плата за ВРИ считается от жилой СПП ВМЕСТЕ со встроенной,
// то есть её база наполовину оставалась прежней, а выручка коммерции — тоже
// (владелец, 09.09.2026: «почему коммерция первого этажа пропорционально не
// изменилась?»). Пересчитываем пропорцией и НАЗЫВАЕМ это: молча переписанная
// строка неотличима от невнимательности, а своё число человек вписывает сюда
// же — оно сильнее, пока жильё не правят снова.
function rescaleBuiltInCommercial(){
 const row=tep.ground_commercial;
 if(!row)return;
 const living=Number((tep.apartments&&tep.apartments.gns)||0);
 const per=Number(MKD_SPP_SPLIT.apartments||0);
 const share=Number(MKD_SPP_SPLIT.ground_commercial||0);
 // Пустое жильё — это «человек стирает и печатает», а не «коммерции нет».
 if(!(living>0)||!(per>0)||!(share>0))return;
 const was=Number(row.gns||0);
 const want=Math.round(living/per*share*10)/10;
 if(Math.abs(want-was)<0.05)return;
 const filled=tepFillByRatios('ground_commercial',
  {gns:want,total_area:0,saleable:0,useful:0});
 ['gns','total_area','saleable'].forEach(field=>{row[field]=filled[field]});
 row.useful=row.saleable;
 setTepNote('ground_commercial',
  'Пересчитана пропорцией '+Math.round(per*100)+'/'+Math.round(share*100)+
  ' от жилой СПП: было '+landNum(was,0)+' → стало '+landNum(want,0)+
  ' м² ГНС. Своё число вписывается здесь же.', '');
}

// Число квартир выгрузки — не независимое число города, а ВЫХОД его же
// формулы: население = площадь квартир / 33, квартиры = население / 2,1. В
// выгрузке по 77:01:0006018:75 стоит население 525 и ровно 250 квартир, то
// есть средняя 69,3 м² — те самые 33 × 2,1. Правя метры, человек меняет вход
// этой формулы, и её выход обязан идти следом: иначе 250 квартир остаются
// числом города для ПРЕЖНИХ метров (владелец, 09.09.2026: «кстати машиноместа
// похоже не меняются увы»).
//
// Цена заморозки видна на паркинге. Постоянные места по пункту 2 — это
// «квартиры × коэффициент полосы», и как только средняя перевалила 100 м²,
// коэффициент упирается в 1,6: 45 000, 50 000 и 60 000 м² ГНС дают одни и те
// же 400 + 40 мест. Площадь перестаёт двигать паркинг вовсе.
function rescaleApartmentUnits(){
 // Решение касается выгрузки ГлавАПУ: у собранного руками и у Подмосковья
 // делитель свой, и трогать их этой правкой нельзя.
 if(!inputs._glavapu_import)return;
 const row=tep.apartments;
 if(!row)return;
 const saleable=Number(row.saleable||0);
 if(!(saleable>0))return;
 const perPerson=Number(PARKING_2118.sqm_per_person||0);
 const household=Number(PARKING_2118.household||0);
 if(!(perPerson>0)||!(household>0))return;
 const was=Number(row.units||0);
 // Тем же порядком, что в движке: два округления вверх, а не одно деление на
 // 69,3 — подпись, разошедшаяся с расчётом на квартиру, читается как ошибка.
 const want=Math.ceil(Math.ceil(saleable/perPerson)/household);
 if(!(want>0)||want===was)return;
 row.units=want;
}

function tepCellChanged(key,col,value){
 const was=Number(tep[key][col]||0);
 tep[key][col]=Number(value||0);
 markFieldManual('tep.'+key+'.'+col);
 // Переданное муниципалитету не продаётся: метры остаются в ГНС — их строят, —
 // но уходят из продаваемой. В Подмосковье этим ещё и уменьшают плату за смену
 // ВРИ, сумма зачёта вводится во «Вводных» (замечание владельца, 19.08.2026).
 // У соцобъектов передаваемая — это вся площадь объекта, там правило другое.
 if(col==='transfer'&&TEP_RATIOS[key]){
  // Полная площадь берётся из полезной, а у строки старого проекта полезная
  // равна НЕТТО — там она восстанавливается как «продаваемая плюс прежняя
  // передаваемая». Максимум из двух подходит обоим случаям и не требует знать,
  // какой это проект.
  const gross=Math.max(Number(tep[key].useful||0),Number(tep[key].saleable||0)+was);
  tepApplyTransfer(key,gross);
  tepRowToInputs(key);
  renderInputs();
  renderTep();
  calculate();
  return;
 }
 // Соцобъект: пара «ГНС — общая» пересчитывается в обе стороны, а во вводные
 // уходит общая — то единственное число, которое там есть. Решение о КРТ
 // задаёт площадь «в габаритах наружных стен», то есть НАЗЕМНУЮ: вписывать её
 // надо в ГНС, и тогда общая считается сама.
 if(TEP_SOCIAL_INPUTS[key]&&['gns','total_area'].includes(col)){
  const share=socialTotalShare();
  const entered=Number(value||0);
  const total=col==='gns'?entered*share:entered;
  tep[key].total_area=Math.round(total*10)/10;
  tep[key].gns=total>0?Math.round(total/share*10)/10:0;
  // Передаваемая у соцобъекта — вся площадь объекта: правило продуктов сюда
  // не идёт, но и отставать от общей она не должна.
  tep[key].transfer=tep[key].total_area;
  inputs[TEP_SOCIAL_INPUTS[key]]=tep[key].total_area;
  renderInputs();
  renderTep();
  scheduleTepAutoRecalc(key);
  calculate();
  return;
 }
 if(key==='storage'&&['gns','units'].includes(col)){
  syncStoragePair(col);
  renderTep();
  scheduleTepAutoRecalc(key);
  calculate();
  return;
 }
 if(['gns','total_area','saleable'].includes(col)&&TEP_RATIOS[key]){
  // Вписанная продаваемая — НЕТТО: переданное из неё уже вычтено. Значит
  // пропорцию надо гнать от полной площади, иначе ГНС потеряет метры, которые
  // строятся. Прежде правка ГНС затирала продаваемую полным числом из
  // пропорции, и переданное молча возвращалось в продажу.
  const transfer=Math.max(0,Number(tep[key].transfer||0));
  const base={gns:0,total_area:0,saleable:0,useful:0};
  base[col]=col==='saleable'?Number(value||0)+transfer:Number(value||0);
  const filled=tepFillByRatios(key,base);
  ['gns','total_area'].forEach(field=>{tep[key][field]=filled[field]});
  tepApplyTransfer(key,filled.saleable);
  tepRowToInputs(key);
  if(key==='apartments'){rescaleApartmentUnits();rescaleBuiltInCommercial()}
  renderInputs();
  renderTep();
 }else if(key==='apartments'){
  // Число квартир — вход нормы мест (2118-ПП, п. 2 по средней квартире), и
  // считает её сама страница (`parkingRequirement`). Перерисовка ждала ответа
  // расчёта: долгий или отказавший расчёт оставлял места, подписи и поле мест
  // от прежнего числа (владелец, 22.10.2026: «машиноместа даже не дрогнули»).
  tepRowToInputs(key);renderInputs();renderTep();
 }else{tepRowToInputs(key);updateTepTotals()}
 scheduleTepAutoRecalc(key);
 calculate();
}

function updateTepTotals(){
 repairParkingFromGlavapu();
 const sums={gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0};
 // ГНС — НАЗЕМНАЯ площадь здания: под землёй наружных стен не бывает. В движке
 // это разведено 04.09.2026 (`project_gns_sqm` против `underground_gns_sqm`), а
 // итог таблицы всё это время складывал их в одну клетку под одним именем — то
 // самое, что тем же правилом и запрещено. Список подземных продуктов приходит
 // из движка плейсхолдером: второй копии, которую негде обновлять, нет.
 let underGns=0;
 Object.entries(tep).forEach(([k,r])=>{
   Object.keys(sums).forEach(c=>{
     sums[c]+=c==='gns'?tepRowAboveGns(k,r):Number(r[c]||0);
   });
   underGns+=tepRowUnderGns(k,r);
 });
 renderTepUndergroundNote(sums.gns,underGns);
 tg.textContent=num(sums.gns);ta.textContent=num(sums.total_area);tu.textContent=num(sums.useful);ts.textContent=num(sums.saleable);tt.textContent=num(sums.transfer);tn.textContent=num(sums.units);
 renderSitePanel();
 renderSiteMassing();
}
// Пятно застройки, этажность и подземная часть: ответ движка
// (`tep.site_massing`, тот же расчёт, по которому СМР подземной части взяло
// надбавку за глубину). Страница ничего не пересчитывает, только показывает.
function siteMassingResult(){
 return (((typeof lastResult==='object'&&lastResult)||{}).tep||{}).site_massing||null;
}
function siteMassingOrigin(origin){
 if(origin==='manual')return 'Задано вручную.';
 if(origin==='limit')return 'Взято по предельной этажности: иначе здание было бы выше предела.';
 if(origin==='coverage')return 'Процент застройки участка. Свободного места больше, но здание обычно занимает не всё.';
 return 'Оценка по балансу территории.';
}
function renderSiteMassing(){
 const body=document.getElementById('siteMassingBody');
 if(!body)return;
 renderSiteMassingFields();
 const m=siteMassingResult();
 renderSiteMassingScheme(m);
 if(!m){
  body.innerHTML='<p class="site-massing-hint">Здесь появятся пятно застройки, средняя этажность и число подземных уровней, когда проект будет посчитан.</p>';
  return;
 }
 const sq=v=>num(Math.round(Number(v||0)))+' м²';
 const pct=v=>num(Math.round(Number(v||0)*100))+'%';
 const row=(label,value,basis,strong)=>'<tr'+(strong?' class="site-massing-sum"':'')+'><td>'+escapeHtml(label)+
  '</td><td class="num">'+escapeHtml(value)+'</td><td class="hint">'+escapeHtml(basis||'')+'</td></tr>';
 const site=Number(m.site_sqm||0);
 const rows=[];
 rows.push(row('Площадь участка',sq(site),'Из карточки «Участок и плотность».'));
 rows.push(row('− Двор рядом со зданием по норме',sq(m.yard_sqm),m.yard_basis));
 if(Number(m.yard_roof_sqm||0)>0.5)rows.push(row('Благоустройство на кровле стилобата',sq(m.yard_roof_sqm),
  'Площадь благоустройства в смете ('+sq(m.landscaping_sqm)+') больше нормы. Разница может быть на кровле стилобата и места рядом со зданием не занимает.'));
 rows.push(row('− Проезды, тротуары и пожарные проезды',sq(m.driveways_sqm),
  'Это '+num(m.driveways_pct)+'% участка. Доля — экспертная оценка: в нормативах её нет.'));
 rows.push(row('− Открытые стоянки',sq(m.surface_parking_sqm),
  'Машино-мест на земле: '+num(m.surface_parking_spaces)+'. На одно место нужно '+num(m.surface_parking_sqm_per_space)+' м² ('+m.surface_parking_basis+').'));
 rows.push(row('− Отступы от границ участка',sq(m.setbacks_sqm),'Полоса шириной '+num(m.setback_m)+' м вдоль границ участка.'));
 rows.push(row('Свободно под здание после двора, проездов и отступов',sq(m.footprint_estimate_sqm),
  'Это наибольшее возможное пятно. '+(m.coverage_origin==='none'?'Процент застройки не задан: у нежилого проекта пятно — всё свободное место.':
   'Процент застройки — '+num(m.coverage_pct)+'%'+(m.coverage_origin==='manual'?', задан в проекте.':', обычное значение для жилья, если градплан не задаёт другое.'))));
 rows.push(row('Пятно застройки',sq(m.footprint_sqm)+(site>0?', это '+pct(m.footprint_share)+' участка':''),
  siteMassingOrigin(m.footprint_origin),true));
 if(Number(m.footprint_shortage_sqm||0)>0.5)rows.push(row('Не хватает земли под пятно',sq(m.footprint_shortage_sqm),
  'Столько не хватает, чтобы здание не было выше '+num(m.storeys_limit)+' этажей. Подробности — в красной плашке выше.'));
 rows.push(row('Средняя этажность',Number(m.average_storeys||0)>0?'≈ '+Number(m.average_storeys).toLocaleString('ru-RU',{maximumFractionDigits:1}):'—',
  'Наземная площадь здания ('+sq(m.above_gns_sqm)+'), делённая на пятно застройки.',true));
 rows.push(row('Подземный контур',sq(m.underground_contour_sqm),'Участок без отступов. Под машино-места идёт '+
  num(Math.round(Number(m.underground_use_factor||0)*100))+'% этой площади, остальное — стены, лестницы и шахты.'));
 rows.push(row('Площадь подземной части',sq(m.underground_sqm),'Паркинг с рампами и проездами и подземные кладовые из ТЭП.'));
 rows.push(row('Подземных уровней',String(m.underground_levels||0),
  m.underground_levels_origin==='manual'?'Задано вручную.':'Площадь подземной части, делённая на полезную площадь одного уровня, с округлением вверх.',true));
 let levels='';
 if((m.underground_level_rows||[]).length){
  levels='<table class="site-massing-levels"><thead><tr><th>Уровень</th><th>Площадь</th><th>Ставка СМР</th></tr></thead><tbody>'+
   m.underground_level_rows.map(r=>'<tr><td>−'+Math.abs(Number(r.level))+(Number(r.markup_pct)>0?' (надбавка +'+num(r.markup_pct)+'%)':'')+
    '</td><td class="num">'+sq(r.area_sqm)+'</td><td class="num">'+num(r.rate_th)+' тыс ₽/м²</td></tr>').join('')+
   '</tbody></table>'+(m.underground_depth_basis?'<p class="site-massing-hint">'+escapeHtml(m.underground_depth_basis)+'</p>':'');
 }
 const warn=(m.warnings||[]).map(w=>'<div class="note warning site-massing-warning">'+escapeHtml(w)+'</div>').join('');
 const notes=(m.notes||[]).map(w=>'<p class="site-massing-hint">'+escapeHtml(w)+'</p>').join('');
 body.innerHTML=warn+'<div class="scroll"><table class="site-massing-table"><tbody>'+rows.join('')+'</tbody></table></div>'+levels+notes+
  '<p class="site-massing-hint">Это оценка по балансу территории, а не проект: формы участка расчёт не знает.</p>';
}
// Объёмная схема: многоугольники, номера и легенда — ответ движка
// (`site_massing_scheme`); тот же ответ рисует PDF. Здесь ничего не
// раскладывается и не проецируется.
function siteMassingSchemeSvg(ax){
 const vb=ax.viewbox||[0,0,1,1];const u=vb[2]/400;
 const shapes=(ax.shapes||[]).map(s=>'<polygon data-kind="'+s.kind+'"'+(s.building?' data-building="'+s.building+'"':'')+
  ' points="'+s.points.map(p=>p[0]+','+p[1]).join(' ')+'" fill="'+s.fill+'" stroke="'+s.stroke+'" stroke-width="'+(s.width*u)+'"'+
  (s.dash?' stroke-dasharray="'+s.dash.map(d=>d*u).join(' ')+'"':'')+(s.opacity&&s.opacity<1?' fill-opacity="'+s.opacity+'"':'')+' stroke-linejoin="round"></polygon>').join('');
 const r=Number(ax.label_radius||5);
 const labels=(ax.labels||[]).map(l=>'<g class="site-massing-mark" data-building="'+l.building+'"><circle cx="'+l.x+'" cy="'+l.y+'" r="'+r+
  '" fill="#fff" stroke="#222" stroke-width="'+(r/8)+'"></circle><text x="'+l.x+'" y="'+(l.y+r*0.42)+'" font-size="'+(r*1.2)+
  '" text-anchor="middle" font-weight="700" font-family="sans-serif">'+escapeHtml(l.text)+'</text></g>').join('');
 const fs=Number(ax.font_size||8);
 const texts=(ax.texts||[]).map(t=>'<text class="site-massing-level" data-level="'+t.level+'" x="'+t.x+'" y="'+t.y+'" font-size="'+fs+
  '" text-anchor="'+(t.anchor||'start')+'" fill="#333" font-family="sans-serif">'+escapeHtml(t.text)+'</text>').join('');
 return '<svg viewBox="'+vb.join(' ')+'" role="img" aria-label="Объёмная схема застройки участка">'+shapes+texts+labels+'</svg>';
}
// Корпуса схемы для карты участка: кольца в меркаторе — ответ движка
// (`ring_merc`), есть только у схемы по контуру из ЕГРН.
function siteMassingMapShapes(){
 const m=siteMassingResult()||{};const scheme=m.scheme||{};
 const legend={};((scheme.axonometry||{}).legend||[]).forEach(g=>{legend[g.number]=g});
 return ((scheme.layout||{}).buildings||[]).filter(b=>Array.isArray(b.ring_merc)&&b.ring_merc.length)
  .map(b=>({ring:b.ring_merc,number:b.number,title:b.label,colour:(legend[b.number]||{}).color||'#555'}));
}
function siteMassingOpenMap(){
 const many=((typeof landLookup==='object'&&landLookup&&landLookup.results)||[]).filter(x=>x&&x.found).length>1;
 if(many)landMapFromTerritory();else landMapFromContour();
}
function renderSiteMassingScheme(m){
 const box=document.getElementById('siteMassingScheme');
 if(!box)return;
 const scheme=(m&&m.scheme)||{};const ax=scheme.axonometry||{};const layout=scheme.layout||{};
 if(!(ax.shapes||[]).length){box.innerHTML='';return;}
 const legend=(ax.legend||[]).map(g=>'<li data-building="'+g.number+'"><i style="background:'+g.color+'"></i>'+escapeHtml(g.line||'')+'</li>').join('');
 const notes=(layout.notes||[]).map(t=>'<p class="site-massing-hint">'+escapeHtml(t)+'</p>').join('');
 box.innerHTML='<p class="site-massing-hint">'+escapeHtml(ax.caption||'')+'</p>'+siteMassingSchemeSvg(ax)+'<ul class="site-massing-legend">'+legend+'</ul>'+notes+
  '<p class="site-massing-hint">'+escapeHtml(ax.footer||'')+'</p>'+
  (siteMassingMapShapes().length?'<button type="button" class="btn" id="siteMassingMapButton" onclick="siteMassingOpenMap()">Показать корпуса на карте участка</button>':'');
}
// Поля допущений: подпись и единица — из FIELD_GROUPS. Поля «пусто — по
// расчёту» (пятно, уровни, предельная этажность, земля на место) показывают
// пустоту, а не ноль.
const SITE_MASSING_AUTO=['surface_parking_sqm_per_space','building_footprint_sqm','underground_levels','max_storeys_allowed','site_coverage_max_pct'];
function renderSiteMassingFields(){
 const box=document.getElementById('siteMassingFields');
 if(!box||(typeof box.contains==='function'&&box.contains(document.activeElement)))return;
 const decl={};allFieldGroups().forEach(g=>g[1].forEach(f=>{decl[f[0]]=f}));
 const m=siteMassingResult()||{};
 const auto={building_footprint_sqm:m.footprint_estimate_sqm?'оценка '+num(Math.round(m.footprint_estimate_sqm)):'',
  underground_levels:m.underground_sqm?'по расчёту':'',surface_parking_sqm_per_space:m.surface_parking_sqm_per_space?String(m.surface_parking_sqm_per_space).replace('.',','):'',
  max_storeys_allowed:'не выше '+num(m.storeys_limit||25),site_coverage_max_pct:m.coverage_origin==='none'?'не задан':String(m.coverage_pct||30).replace('.',',')+'%'};
 box.innerHTML='';
 SITE_MASSING_INPUTS.forEach(id=>{
  const f=decl[id];if(!f)return;
  const [,label,unit]=f;
  const wrap=document.createElement('div');wrap.className='field';
  wrap.innerHTML='<label>'+escapeHtml(label)+'</label>';
  const el=document.createElement('input');el.type='number';el.step='any';el.id='massing_'+id;
  const v=inputs[id];
  const isAuto=SITE_MASSING_AUTO.includes(id);
  el.value=(v===undefined||v===null||v===''||(isAuto&&Number(v)===0))?'':v;
  el.placeholder=isAuto?(auto[id]||''):String(INPUT_DEFAULT[id]??'');
  el.onchange=()=>{
   const raw=String(el.value).trim();
   inputs[id]=raw===''?(isAuto?0:INPUT_DEFAULT[id]):Number(raw);
   if(raw!=='')markFieldManual('inputs.'+id);
   else if(inputs._field_origin)delete inputs._field_origin['inputs.'+id];
   calculate();
  };
  wrap.appendChild(el);
  const hint=document.createElement('span');hint.style.cssText='display:block;font-size:11px;color:#777';hint.textContent=unit;
  wrap.appendChild(hint);
  box.appendChild(wrap);
 });
}
// Участок и плотность. Площадь приходит из ГлавАПУ, из кадастра (ЕГРН) или
// руками; плотность для Москвы — из калькулятора ГлавАПУ, для площади из
// кадастра — 30 000 м²/га по умолчанию, и всё перебивается ручным вводом.
function glavapuDensitySqmHa(){
 const n=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 return n?Number(n.density_spp_th_sqm_ha||0)*1000:0;
}
function effectiveSiteDensity(){
 const stored=Number(inputs.site_density_sqm_per_ha||0);
 if(stored>0)return stored;
 const g=glavapuDensitySqmHa();
 return g>0?g:30000;
}
// Площадь территории, приехавшая вместе с загруженным ТЭП (площадка КРТ,
// файл ТЭП), — или 0. Она владеет площадью, пока человек не вписал свою:
// разбор кадастровых номеров отвечает за свои участки, а не за территорию.
function importedSiteAreaHa(){
 return Math.max(0,Number((inputs._manual_tep_import||{}).site_area_ha||0));
}
function siteAreaIsImported(){
 const own=importedSiteAreaHa();
 return own>0&&Math.abs(Number(inputs.site_area_ha||0)-own)<0.00005;
}
// Застройка во столько раз больше участка не бывает: даже башни Сити дают
// около 20 метров поэтажной площади на метр земли. Порог взят с запасом —
// предупреждение про явную подмену территории, а не про плотный проект.
const SITE_GNS_PER_SQM_IMPLAUSIBLE=40;
function siteAreaTepMismatch(){
 const area=Number(inputs.site_area_ha||0);
 const gns=Object.values(tep||{}).reduce((s,r)=>s+Math.max(0,Number((r||{}).gns||0)),0);
 if(!(area>0&&gns>0))return null;
 const ratio=gns/(area*10000);
 if(ratio<=SITE_GNS_PER_SQM_IMPLAUSIBLE)return null;
 return {area_ha:area,gns:gns,ratio:ratio,source:siteAreaSourceLabel(),imported_ha:siteAreaIsImported()?0:importedSiteAreaHa()};
}
function siteAreaWarningHtml(){
 const m=siteAreaTepMismatch();
 if(!m)return '';
 const ha=v=>Number(v).toLocaleString('ru-RU',{maximumFractionDigits:4});
 let html='<b>Площадь участка не сходится с ТЭП.</b> На участке '+ha(m.area_ha)+' га ('
  +num(m.area_ha*10000)+' м²) в ТЭП стоит '+num(m.gns)+' м² — застройки в '+num(m.ratio)
  +' раз больше самого участка. Так не бывает: площадь, скорее всего, взята у другой или '
  +'неполной территории (сейчас она '+escapeHtml(m.source)+'). Расчёт идёт по этим числам — '
  +'проверьте поле «Площадь участка» здесь, на шаге «ТЭП».';
 if(m.imported_ha>0){
  const krt=((inputs._manual_tep_import||{}).source||{}).kind==='krt';
  html+=' <button type="button" class="btn" id="siteAreaRestore" onclick="restoreImportedSiteArea()">Вернуть площадь '
   +(krt?'территории КРТ':'из загруженного ТЭП')+' — '+ha(m.imported_ha)+' га</button>';
 }
 return html;
}
function restoreImportedSiteArea(){
 const own=importedSiteAreaHa();
 if(!(own>0))return;
 inputs.site_area_ha=own;
 inputs._site_area_user_set=false;
 renderSitePanel();
 calculate();
}
function siteAreaSourceLabel(){
 if(inputs._site_area_user_set)return 'введена вручную';
 {
  const krt=((inputs._manual_tep_import||{}).source||{});
  // Источник приезжает вместе с площадкой: половина каталога КРТ — площадки
  // без карточки, у них это проект решения на mos.ru, а не krt.mos.ru.
  // Подпись — только пока площадь та самая: перемеренная разбором номеров
  // площадь «из площадки КРТ» не происходит.
  if(krt.kind==='krt'&&siteAreaIsImported())return 'из площадки КРТ ('+String(krt.origin||'карточка krt.mos.ru')+')';
 }
 if(inputs._glavapu_import)return 'из калькулятора ГлавАПУ';
 if(inputs._mo_calc)return 'из калькулятора Подмосковья';
 if(inputs._cadastral_analysis||cadastralAnalysis)return 'из кадастра (ЕГРН)';
 return Number(inputs.site_area_ha||0)>0?'из сохранённого проекта':'не задана';
}
function siteDensitySourceLabel(){
 if(inputs._site_density_user_set&&Number(inputs.site_density_sqm_per_ha||0)>0)return 'введена вручную';
 if(classRegion()==='other')return 'наше допущение — 30 000 м² квартир на гектар: норм этого региона у нас нет, поправьте под свой участок';
 if(Number(inputs.site_density_sqm_per_ha||0)>0&&inputs._mo_calc)return 'из калькулятора Подмосковья';
 if(glavapuDensitySqmHa()>0)return 'из калькулятора ГлавАПУ (Москва)';
 return 'по умолчанию 30 000 м²/га';
}
// Чьими нормативами считается ручной и кадастровый ТЭП без выгрузки ГлавАПУ —
// один ответ на все подписи страницы. Регион решает `classRegion()`: пустой
// регион — Москва, и подпись области под московским проектом (и наоборот)
// стоять не должна.
function normativeNormsLabel(){
 return classRegion()==='mo'?'РНГП Московской области':'Москвы';
}
// Другой регион: норм у нас нет, и подписи «нормативами …» к нему не идут.
const OTHER_REGION_TEP_NOTE='Участок не в Москве и не в Московской области, и норм его региона у нас нет. Пересчёт по плотности меняет только квартиры. Места в детских садах, школах и поликлинике, машино-места и плата за смену разрешённого использования — наши умолчания: поправьте их во «Вводных» под свой участок.';
// Москва без выгрузки ГлавАПУ: квартиры — площадь × плотность, остальное —
// нормативы ГОРОДА через `/tep/derived-by-site`, то есть та же
// `tep_derived_norms` движка, что и у пересчёта по ТЭП: 33 м²/чел, места ДОО
// и СОШ по зоне района, постоянные машино-места по 2118-ПП и десятая часть
// гостевых. Прежде такой проект шёл в `/mo/calculate` и получал нормы
// области — 28 м²/чел, ДОО 65 и СОШ 135 на тысячу — под московским адресом
// (решение владельца, 16.10.2026). Арифметики на странице нет: что считать и
// чем это подписать, отвечает сервер.
// Квартиры = площадь × плотность — одна арифметика для Москвы без выгрузки и
// для другого региона; что дальше считать нормами, решает вызывающий.
function fillApartmentsByDensity(area,density,keepRows){
 const row=tep.apartments;
 const filled=tepFillByRatios('apartments',{gns:0,total_area:0,saleable:Math.round(area*density*10)/10,useful:0});
 ['gns','total_area','saleable','useful'].forEach(f=>{row[f]=filled[f]});
 row.transfer=0;
 // Число квартир — делителем собранного руками ТЭП (рынок, 60 м²): норматив
 // 33 × 2,1 меряет население, а не среднюю квартиру (см. подпись строки).
 const yard=Number((AVERAGE_FLAT.manual||{}).sqm||0);
 row.units=yard>0?Math.ceil(Number(row.saleable||0)/yard):0;
 // Вписанные человеком площади квартир — его, как и в областном пересчёте.
 Object.entries(keepRows||{}).forEach(([key,values])=>{if(tep[key])Object.assign(tep[key],values)});
 rescaleBuiltInCommercial();
 return row;
}
// Другой регион (решение владельца 19.10.2026): норм его у нас нет, и
// пересчёт по плотности трогает только квартиры. Места соцобъектов,
// машино-места и плату за ВРИ вписывает человек — их здесь не трогаем.
function applyOtherRegionTep(area,density,keepRows){
 const row=fillApartmentsByDensity(area,density,keepRows);
 return {tep:{apartments:Object.assign({},row)},warnings:[]};
}
async function applyMoscowNormativeTep(area,density,keepRows){
 const row=fillApartmentsByDensity(area,density,keepRows);
 const territory=((inputs._cadastral_analysis||cadastralAnalysis||{}).territory)||{};
 const response=await fetch('/tep/derived-by-site',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({apartment_area_sqm:Number(row.saleable||0),
   residential_living_spp_sqm:Number(row.gns||0),
   nonresidential_np_sqm:nonresidentialAboveSqm(),
   // Число квартир не передаётся: на стадии оценки это наша оценка по рыночной
   // средней, а не данное города, и постоянные места идут пунктом 1 —
   // S / (33 × 2,1) × 0,8 (решение владельца, 16.10.2026).
   apartment_count:0,
   district:String(territory.district||''),
   inside_moscow:true})});
 const data=await response.json();
 if(!response.ok)throw new Error(data.detail||'Не удалось рассчитать ТЭП по нормативам Москвы');
 const places=data.places||{};
 const skipped=applyDerivedInputs({kindergarten_places:places.kindergarten,
  school_places:places.school,clinic_capacity:places.clinic});
 // Посчитанные места — строящиеся объекты, как и у областного расчёта.
 if(inputs.social_mode!=='Строительство'&&inputs.social_mode!=='Строительство и компенсация')
  inputs.social_mode='Строительство';
 const parking=data.parking||{};
 setUndergroundFromMethod(parking.permanent,parking.guest,parking.underground);
 stampSocialBasis('нормативы Москвы');
 return Object.assign({},data,{tep:{apartments:Object.assign({},row)},
  warnings:(data.warnings||[]).concat(skipped?[skipped]:[])});
}
async function applyNormativeTep(densityOverride,keepRows){
 // Нормативный пересчёт ручного и кадастрового ТЭП: квартиры = площадь ×
 // плотность, остальное — от населения нормативами региона. Чьи нормативы,
 // решает `classRegion()`: Москва — свои (`applyMoscowNormativeTep`), область
 // — калькулятор Подмосковья ниже: население 28 м²/чел, ДОО 65 и СОШ 135
 // мест на 1000 жителей, поликлиника 17,75 пос./смену, паркинг 356 м/м на
 // 1000 (90% постоянные, подземные 35 м²/место), рабочие места 50%
 // населения → офисы. Раньше ручной и кадастровый ТЭП считались долями 94/6,
 // и социалка с объектами КРТ оставались от первоначального объёма квартир —
 // очередям доставалась разбивка от проекта, которого больше нет.
 const area=Number(inputs.site_area_ha||0);
 // Плотность может прийти извне: обратный счёт от заданного объёма квартир
 // считает её как метры ÷ гектары и гонит те же нормативы.
 const density=Number(densityOverride)>0?Number(densityOverride):effectiveSiteDensity();
 let data;
 if(classRegion()==='other'){
  data=applyOtherRegionTep(area,density,keepRows);
 }else if(classRegion()!=='mo'){
  data=await applyMoscowNormativeTep(area,density,keepRows);
 }else{
  const stored=inputs._mo_calc||{};
  // Округ решает Кср и Кд платы за ВРИ. Без него расчёт берёт среднее по
  // области: на Мытищах это 198 907 ₽ вместо 238 052 ₽ за метр — и плата
  // расходится на четверть. Округ ищется в сохранённом расчёте МО, в поле
  // на вкладке импорта и в самом проекте (пресет несёт его отдельным ключом).
  const district=(stored.territory&&stored.territory.district)
   ||((document.getElementById('moDistrict')||{}).value||'')
   ||inputs.mo_district||'';
  // Кадастры проекта уезжают в запрос: сервер определяет округ по адресам
  // участков из ЕГРН, а плату за ВРИ считает по разнице кадастровых
  // стоимостей — точнее прямой формулы. Раньше запрос был пуст, если проект
  // пришёл не из калькулятора МО, и расчёт не знал, что это Мытищи.
  const analysis=inputs._cadastral_analysis||cadastralAnalysis||{};
  const projectNumbers=(analysis.recognized||analysis.requested||[]).filter(Boolean).join(', ');
  const body={
   query:stored.query||projectNumbers||'',
   limit:30,
   site_area_ha:area,
   density_sqm_per_ha:density,
   district:district,
   market_price_rub_per_sqm:0,
   vri_kd:0,
   average_flat_sqm:Number((document.getElementById('moFlat')||{}).value||0)||AVERAGE_FLAT.mo.sqm
  };
  const response=await fetch('/mo/calculate',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(body)});
  data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Не удалось рассчитать нормативный ТЭП');
  Object.entries(data.tep||{}).forEach(([key,values])=>{if(tep[key])Object.assign(tep[key],values)});
  // Обратный счёт от вписанных метров: строка, которую человек вписал, остаётся
  // его. Сервер выводит ГНС и общую из продаваемой своими долями, и ответ молча
  // заменял вписанные 215 720,6 м² ГНС на 220 781,6 — при обещании таблицы
  // «введённое вами не перебивается». Из ответа берётся только производное:
  // число квартир, население, социалка, паркинг, плата за ВРИ.
  Object.entries(keepRows||{}).forEach(([key,values])=>{if(tep[key])Object.assign(tep[key],values)});
  if(keepRows&&keepRows.apartments)rescaleBuiltInCommercial();
  const keepLand=Number(inputs.land_rights_cost_mln||0);
  const keepRegion=inputs.vri_region;
  Object.assign(inputs,data.inputs||{});
  const parcels=((data.vri||{}).parcels||[]).length;
  // Плата за ВРИ считается от УПКС конкретных участков; без кадастра расчёта
  // нет, и введённая руками сумма не затирается нулём. Регион ВРИ без
  // кадастра МО тоже остаётся прежним.
  if(!(Number((data.inputs||{}).land_rights_cost_mln||0)>0)&&keepLand>0)inputs.land_rights_cost_mln=keepLand;
  if(!parcels&&keepRegion)inputs.vri_region=keepRegion;
  inputs._mo_calc={query:body.query,territory:data.territory||{},
   density_sqm_per_ha:data.density_sqm_per_ha,vri:data.vri||{},social:data.social||{},
   balance:data.balance||{},warnings:data.warnings||[],
   // Объём квартир последнего нормативного расчёта. По нему обратный счёт
   // отличает правку человека от собственного результата и не зовёт себя по кругу.
   apartments_saleable:Number((data.tep&&data.tep.apartments&&data.tep.apartments.saleable)||0)};
  if(data.territory&&data.territory.district)inputs.mo_district=data.territory.district;
  moResult=data;
 }
 syncTep(false);
 // Разбивка соцобъектов по очередям пересобирается под новые мощности.
 // Старый список строил семь ДОУ на 1 562 места и СОШ на 3 250 от проекта,
 // которого больше нет: вводные уже показывали 453 и 950, а модель платила
 // за старую социалку — расход не следовал ни за площадями, ни за очередями.
 if(typeof phasing!=='undefined'&&phasing&&Array.isArray(phasing.social_objects)){
  autoSocialObjects(false);
  renderPhasing();
 }
 renderInputs();renderTep();
 await calculate();
 return data;
}
// Куда класть потенциал участка в нежилом проекте — выбирает человек
// (решение владельца, 21.09.2026: «надо предлагать выбирать куда хочет
// вставить. В офисники или в тц»). Сами не делим: доля между офисами и
// торговлей была бы нашей догадкой, а на экране она выглядит как норматив
// города. Список объявлен один раз — кнопки и писатель читают его.
// Вторые объекты сюда не входят нарочно: они — для «двух объектов в одной
// очереди», а потенциал пустого участка кладут в первый.
const NONRES_DENSITY_TARGETS=[
 ['offices','МФОЦ / офисы'],
 ['standalone_retail','ТЦ / коммерция ОСЗ']
];
// Вводные объекта, которыми задаются его метры. Строка ТЭП производная: её
// считает `syncTep` по долям, и писать в неё напрямую значило бы завести
// второй ответ на «сколько у объекта метров».
const NONRES_TARGET_INPUTS={
 offices:{flag:'offices_enabled',gba:'offices_gba_sqm',sale:'offices_saleable_sqm'},
 standalone_retail:{flag:'retail_enabled',gba:'retail_gba_sqm',sale:'retail_saleable_sqm'}
};

function applyDensityToObject(target){
 const status=document.getElementById('siteApplyStatus');
 const field=NONRES_TARGET_INPUTS[target];
 const name=(NONRES_DENSITY_TARGETS.find(t=>t[0]===target)||[])[1]||target;
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(!field||!(area>0)||!(density>0)){
  if(status){status.style.display='';
   status.innerHTML='<span class="import-error">Нужны площадь участка и плотность.</span>'}
  return;
 }
 const spp=area*density;
 const wasGba=Number(inputs[field.gba]||0),wasSale=Number(inputs[field.sale]||0);
 inputs[field.flag]=true;
 inputs[field.gba]=spp;
 // Продаваемая пересчитывается долями объекта: оставленное прежнее число
 // описывало бы другой объём, а расходилось бы с ГНС молча.
 inputs[field.sale]=0;
 syncTep(false);renderInputs();renderTep();refreshGroupPeeks();calculate();
 if(status){
  status.style.display='';
  status.innerHTML='<span class="import-ok">Потенциал участка положен в «'+escapeHtml(name)+'»: '
   +num(spp)+' м² ГНС, продаваемая '+num(Number(inputs[field.sale]||0))+' м² (по долям объекта).</span>'
   +(wasGba>0||wasSale>0?'<div style="margin-top:4px">Заменено: было '+num(wasGba)+' м² ГНС'
     +(wasSale>0?' и '+num(wasSale)+' м² продаваемой':'')+'.</div>':'')
   +'<div style="margin-top:4px">Правится там же — вводные объекта на вкладке «Экономика».</div>';
 }
}

function applyDensityToHotel(){
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(!(area>0&&density>0))return;
 setHotelField('gba_sqm',Math.round(area*density),
  {text:'потенциал участка: '+landNum(area,3)+' га × '+num(density)+' м²/га',cells:[]});
 renderInputs();calculate();
 const status=document.getElementById('siteApplyStatus');
 if(status)status.innerHTML='<span class="import-ok">Потенциал участка положен в гостиницу: '
  +num(area*density)+' м² ГНС.</span>';
}

// Что заменит «Сформировать ТЭП по новым параметрам» — для подтверждения перед
// заменой. Отказы (гостиница, нежилой, нет площади) объясняет сам
// applyDensityToTep: там и выбор, куда класть потенциал, — плана для них нет.
function densityTepPlan(){
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(isHotel()||isNonResidential()||!(area>0)||!(density>0))return null;
 const spp=area*density;
 const was=key=>({gns:Number(((tep[key])||{}).gns||0),saleable:Number(((tep[key])||{}).saleable||0)});
 if(inputs._glavapu_import){
  const flats=spp*MKD_SPP_SPLIT.apartments,shops=spp*MKD_SPP_SPLIT.ground_commercial;
  return {mode:'glavapu',
   basis:'СПП '+num(spp)+' м² = '+landNum(area,3)+' га × '+num(density)+' м²/га; квартиры '
    +num(MKD_SPP_SPLIT.apartments*100)+'% СПП, коммерция 1 этажа '+num(MKD_SPP_SPLIT.ground_commercial*100)+'%.',
   rows:[{label:'Квартиры',was:was('apartments'),will:{gns:flats,saleable:flats*0.65}},
         {label:'Коммерция 1 этажа',was:was('ground_commercial'),will:{gns:shops,saleable:shops*0.9}}],
   notes:['Общая и полезная площадь этих строк пересчитаются долями. Остальные строки таблицы не меняются.',
          'Данные выгрузки ГлавАПУ в этих строках будут заменены; вернуть их — повторно «Получить ТЭП» на вкладке «Участок».']};
 }
 // Чьи нормативы — по региону проекта: план не должен обещать Москве РНГП
 // области, а области — московские.
 if(classRegion()==='other')return {mode:'normative',
  basis:'Квартиры '+num(spp)+' м² продаваемой = '+landNum(area,3)+' га × '+num(density)+' м² квартир/га.',
  rows:[{label:'Квартиры',was:was('apartments'),will:{gns:null,saleable:spp}}],
  notes:[OTHER_REGION_TEP_NOTE]};
 const norms='нормативами '+normativeNormsLabel();
 const mo=classRegion()==='mo';
 return {mode:'normative',
  basis:'Квартиры '+num(spp)+' м² продаваемой = '+landNum(area,3)+' га × '+num(density)+' м² квартир/га; остальное — '+norms+' от населения.',
  rows:[{label:'Квартиры',was:was('apartments'),will:{gns:null,saleable:spp}}],
  notes:['Н'+norms.slice(1)+' пересчитаются также: число квартир и население, ДОО, СОШ, поликлиника, машино-места'
    +(mo?', офисы (рабочие места), плата за изменение ВРИ':'')+' и разбивка соцобъектов по очередям.',
         'Вводные, заполненные этим расчётом, заменят прежние; строки отдельно стоящих объектов идут от их вводных на «Экономике».']};
}
function densityTepPlanHtml(plan){
 const cell=v=>v===null||v===undefined?'по долям':num(v)+' м²';
 const rows=plan.rows.map(r=>'<tr><td>'+escapeHtml(r.label)+'</td><td>'+num(r.was.gns)+' / '+num(r.was.saleable)
   +'</td><td>'+cell(r.will.gns)+' / '+cell(r.will.saleable)+'</td></tr>').join('');
 return '<div>'+escapeHtml(plan.basis)+'</div>'
  +'<table class="tep-confirm-table"><thead><tr><th>Строка</th><th>Было, ГНС / продаваемая</th><th>Будет, ГНС / продаваемая</th></tr></thead><tbody>'+rows+'</tbody></table>'
  +plan.notes.map(n=>'<div class="hint" style="margin-top:6px">'+escapeHtml(n)+'</div>').join('');
}
let tepConfirmAction=null;
function openTepConfirm(title,html,okLabel,action){
 const dialog=document.getElementById('tepConfirmDialog');
 const body=document.getElementById('tepConfirmBody');
 if(!dialog||!body){action();return}
 const head=document.getElementById('tepConfirmTitle');if(head)head.textContent=title;
 const ok=document.getElementById('tepConfirmOk');if(ok)ok.textContent=okLabel;
 body.innerHTML=html;tepConfirmAction=action;dialog.style.display='flex';
}
function closeTepConfirm(){
 const dialog=document.getElementById('tepConfirmDialog');
 if(dialog)dialog.style.display='none';
 tepConfirmAction=null;
}
function confirmTepAction(){
 const action=tepConfirmAction;closeTepConfirm();
 if(action)action();
}
// Кнопка в карточке участка: сначала показать, что изменится, и только по
// подтверждению — заменить. Без плана (отказ) — сразу к объяснению отказа.
function formTepByDensity(){
 const plan=densityTepPlan();
 if(!plan){applyDensityToTep();return}
 openTepConfirm('Сформировать ТЭП по новым параметрам',densityTepPlanHtml(plan),'Сформировать',applyDensityToTep);
}
function applyDensityToTep(){
 const status=document.getElementById('siteApplyStatus');
 const area=Number(inputs.site_area_ha||0);
 // Нормативный ТЭП калькулятора — это ЖИЛЬЁ: 94% СПП квартиры, 6% встроенная
 // коммерция. В нежилом проекте таких строк нет, и прежде кнопка их всё
 // равно наполняла: на участке 0,546 га при 35 000 м²/га она клала 15 397 м²
 // квартир и 983 м² коммерции в ЗАПЕРТЫЕ ячейки — убрать их человек не мог,
 // а движок их продавал. Раскладывать потенциал по офисам и ТЦ самим нельзя:
 // доля была бы нашей догадкой, а на экране она выглядит как норматив
 // города. Поэтому отказ, и он называет, где эти метры задаются.
 // Гостиничный проект — та же причина: метры гостиницы — её поле, и
 // потенциал участка кладётся туда только по нажатию.
 if(isHotel()){
  const density=effectiveSiteDensity();
  status.style.display='';
  status.innerHTML='<span class="import-error">Гостиничный проект: нормативный ТЭП калькулятора — жильё, '
   +'а метры гостиницы задаются полем «Площадь гостиницы (ГНС)» в блоке «Гостиница» на вкладке «Экономика».</span>'
   +(area>0&&density>0?'<div style="margin-top:6px"><button type="button" class="btn" onclick="applyDensityToHotel()">'
     +'Положить потенциал участка '+num(area*density)+' м² в гостиницу</button></div>':'');
  return;
 }
 if(isNonResidential()){
  const density=effectiveSiteDensity();
  status.style.display='';
  status.innerHTML='<span class="import-error">Нежилой проект: нормативный ТЭП калькулятора — жильё '
   +'(94% СПП квартиры, 6% встроенная коммерция), и класть его в запертые строки нельзя.</span>'
   +(area>0&&density>0?'<div style="margin-top:4px">Потенциал участка: <b>'+num(area*density)
     +' м²</b> СПП ('+landNum(area,3)+' га × '+num(density)+' м²/га). Куда его положить?</div>'
     +'<div style="margin-top:6px">'
     +NONRES_DENSITY_TARGETS.map(t=>'<button type="button" class="btn" style="margin:0 6px 6px 0" '
       +'onclick="applyDensityToObject(\''+t[0]+'\')">'+escapeHtml(t[1])+'</button>').join('')
     +'</div>'
    :'<div style="margin-top:4px">Сначала задайте площадь участка и плотность.</div>')
   +'<div style="margin-top:4px">Эти же метры правятся вводными объектов на вкладке «Экономика»; '
   +'строки ТЭП у них производные.</div>';
  return;
 }
 if(!(area>0)){
  status.style.display='';
  status.innerHTML='<span class="import-error">Сначала укажите площадь участка — вручную или из калькулятора/кадастра.</span>';
  return;
 }
 const density=effectiveSiteDensity();
 if(!inputs._glavapu_import){
  // Ручной ТЭП, кадастр и проект из калькулятора Подмосковья считаются
  // одинаково — от квартир нормативами региона (`applyNormativeTep`: Москва
  // — свои, область — РНГП). Долевой метод 94/6 пересчитывал
  // только жильё: офисы на 92 тыс. м², 7 700 машино-мест и социалка
  // оставались от первоначального объёма квартир, а разбивка на очереди
  // делила проект, которого больше нет. Москва с ГлавАПУ идёт своей веткой:
  // там нормативный расчёт делает сам калькулятор ГлавАПУ.
  status.style.display='';
  if(classRegion()==='other'){
   status.textContent='Считаю ТЭП по плотности…';
   applyNormativeTep().then(()=>{
    status.innerHTML='<span class="import-ok">Квартиры пересчитаны по плотности: '+num(tep.apartments.saleable)+
     ' м² продаваемой площади ('+landNum(area,3)+' га × '+num(density)+' м² квартир на гектар).</span> '+
     escapeHtml(OTHER_REGION_TEP_NOTE);
   }).catch(e=>{status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>'});
   return;
  }
  status.innerHTML='Считаю ТЭП по нормативам '+normativeNormsLabel()+': квартиры '+num(area*density)+
   ' м² продаваемой ('+num(area)+' га × '+num(density)+
   ' м² квартир/га), социалка и паркинг — от населения…';
  applyNormativeTep().then(data=>{
   // Плата за ВРИ и её основание — часть того же пересчёта: молчаливое
   // среднее по области занижало плату на четверть против цены округа.
   const priceWarn=(((data||{}).warnings)||[]).find(w=>String(w).includes('среднее значение по Московской области')||String(w).includes('Округ не определён'));
   // Офисы от дефицита рабочих мест и плата за ВРИ — ответ калькулятора
   // области; у Москвы плата считается своей кнопкой, и сервер говорит это сам.
   const mo=classRegion()==='mo';
   const source=(data||{}).source;
   const origin=typeof source==='string'?source:String((source||{}).service||'');
   status.innerHTML='<span class="import-ok">ТЭП пересчитан нормативами '+normativeNormsLabel()+': квартиры '+
    num(tep.apartments.saleable)+' м² продаваемой ('+num(tep.apartments.gns)+
    ' м² ГНС), подземный паркинг '+num(tep.underground_parking.units)+' м/м, ДОО '+
    num(tep.kindergarten.units)+' мест, СОШ '+num(tep.school.units)+' мест'+
    (mo?', офисы '+num(Number(inputs.offices_gba_sqm||0))+' м² GBA. Смена ВРИ: '+
    num(Number(inputs.land_rights_cost_mln||0))+' млн ₽.':'.')+'</span>'+
    (priceWarn?'<div class="import-error" style="margin-top:4px">'+escapeHtml(String(priceWarn))+'</div>':'')+
    (origin||(((data||{}).basis)||[]).length
     ?'<div class="hint" style="margin-top:4px">Чем посчитано: '
      +escapeHtml([origin].concat((data||{}).basis||[]).filter(Boolean).join('; '))+'.</div>':'')+
    (((data||{}).refused)||[]).map(x=>'<div class="hint">Не посчитано — '
      +escapeHtml(String(x.name||''))+': '+escapeHtml(String(x.reason||''))+'.</div>').join('');
  }).catch(e=>{
   status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  });
  return;
 }
 // Москва с ГлавАПУ: квартиры — 94% СПП, коммерция 1 этажа — 6%;
 // продаваемая квартир — 65% ГНС, коммерции — 90%; общая площадь — 90% ГНС.
 const spp=area*density;
 tep.apartments.gns=spp*MKD_SPP_SPLIT.apartments;
 tep.apartments.total_area=tep.apartments.gns*0.9;
 tep.apartments.saleable=tep.apartments.gns*0.65;
 tep.apartments.useful=tep.apartments.saleable;
 tep.ground_commercial.gns=spp*MKD_SPP_SPLIT.ground_commercial;
 tep.ground_commercial.total_area=tep.ground_commercial.gns*0.9;
 tep.ground_commercial.saleable=tep.ground_commercial.gns*0.9;
 tep.ground_commercial.useful=tep.ground_commercial.saleable;
 renderTep();
 status.style.display='';
 status.innerHTML='<span class="import-ok">ТЭП пересчитан: СПП '+num(spp)+' м² при плотности '+num(density)+
  ' м²/га. Квартиры '+num(tep.apartments.gns)+' м² ГНС (продаваемая '+num(tep.apartments.saleable)+
  ' м²), коммерция '+num(tep.ground_commercial.gns)+' м² ГНС.</span>';
 calculate();
}
function setSiteArea(value){
 inputs.site_area_ha=Number(value)||0;
 inputs._site_area_user_set=inputs.site_area_ha>0;
 const mo=document.getElementById('moArea');
 if(mo&&document.activeElement!==mo&&inputs.site_area_ha>0)mo.value=inputs.site_area_ha;
 renderSitePanel();
}
function setSiteDensity(value){
 inputs.site_density_sqm_per_ha=Number(value)||0;
 // Пустое поле — возврат к автоматике, а не плотность ноль.
 inputs._site_density_user_set=inputs.site_density_sqm_per_ha>0;
 const mo=document.getElementById('moDensity');
 if(mo&&document.activeElement!==mo&&inputs.site_density_sqm_per_ha>0)mo.value=inputs.site_density_sqm_per_ha;
 renderSitePanel();
}
// Поля участка из `SITE_ONLY_INPUTS`: подпись, единица и варианты — из
// FIELD_GROUPS. Пустое поле — «считать автоматически», а не ноль.
function renderSiteParkingFields(){
 const box=document.getElementById('siteParkingFields');
 if(!box)return;
 renderSiteParkingSummary();
 // Человек печатает в поле — перерисовка сняла бы с него фокус.
 if(box.contains(document.activeElement))return;
 const decl={};allFieldGroups().forEach(g=>g[1].forEach(f=>{decl[f[0]]=f}));
 box.innerHTML='';
 SITE_ONLY_INPUTS.forEach(id=>{
  const f=decl[id];if(!f)return;
  const [,label,unit,type,options]=f;
  const wrap=document.createElement('div');wrap.className='field';
  wrap.innerHTML=`<label>${escapeHtml(label)}</label>`;
  let el;
  if(type==='select'){
   el=document.createElement('select');
   (options||[]).forEach(([value,title])=>{const o=document.createElement('option');o.value=value;o.textContent=title;el.appendChild(o)});
   el.value=String(inputs[id]??'');
  }else{
   el=document.createElement('input');el.type='number';el.step='any';
   // Ноль в К1, К2 и расстоянии не бывает ответом — это «не задано» (старые
   // проекты хранили умолчание нулём). Пустое поле показывает, что принял
   // расчёт и откуда: число движка, а не вторая догадка страницы.
   const v=inputs[id];el.value=(v===undefined||v===null||v===''||Number(v)===0)?'':v;
   el.placeholder=siteParkingPlaceholder(id);
  }
  el.id='site_'+id;
  el.onchange=()=>{inputs[id]=type==='select'?el.value:(String(el.value).trim()===''?'':Number(el.value));calculate()};
  wrap.appendChild(el);
  const hint=document.createElement('span');hint.style.cssText='display:block;font-size:11px;color:#777';hint.textContent=unit+siteParkingBasis(id);
  wrap.appendChild(hint);
  siteParkingConflicts(id).forEach(text=>{
   const warn=document.createElement('span');warn.className='site-conflict';
   warn.style.cssText='display:block;font-size:11px;color:#b3261e;font-weight:600';
   warn.textContent=text;wrap.appendChild(warn);
  });
  box.appendChild(wrap);
 });
}
// Заголовок свёрнутого блока: зачем он здесь и что сейчас в расчёте. Числа —
// те же, что «авто:» в полях (`parking.k1`, `k2`, `k_basis.district` движка):
// страница их не пересчитывает. Противоречие с разбором кадастра видно в
// заголовке без раскрытия, а появившись впервые, раскрывает блок само — молча
// прятать предупреждение нельзя. Закрытое человеком при том же противоречии
// остаётся закрытым: перерисовка решение не отменяет.
let siteParkingConflictSeen='';
function siteParkingPeek(){
 const p=projectParking()||{};
 const basis=p.k_basis||{};
 const fmt=v=>{const n=Number(v||0);return n?String(n).replace('.',','):'—'};
 const parts=['число машино-мест нежилья','К1 '+fmt(p.k1),'К2 '+fmt(p.k2)];
 if(basis.district)parts.push(basis.district);
 return parts.join(' · ');
}
function renderSiteParkingSummary(){
 const sum=document.getElementById('siteParkingSummary');
 if(!sum)return;
 const conflicts=SITE_ONLY_INPUTS.flatMap(id=>siteParkingConflicts(id));
 sum.innerHTML='Паркинг и нормативы<span class="group-peek">'+escapeHtml(siteParkingPeek())+'</span>'+
  (conflicts.length?'<span class="site-conflict-mark">⚠ '+(conflicts.length===1?'противоречие':conflicts.length+' противоречия')+
   ' с разбором кадастра</span>':'');
 const det=document.getElementById('siteParkingBox');
 const key=conflicts.join('\n');
 if(det&&key&&key!==siteParkingConflictSeen)det.open=true;
 siteParkingConflictSeen=key;
}
// Противоречие вписанного с разбором кадастра — красным под полем. Решение и
// текст — из ответа движка (`parking.k_basis.conflicts`, владелец
// `site_position`): страница правило не повторяет, она его показывает.
function siteParkingConflicts(id){
 const basis=(projectParking()||{}).k_basis||{};
 return (basis.conflicts||[]).filter(c=>c&&c.field===id).map(c=>String(c.text||''));
}
// Что принял расчёт для ТТК и откуда — рядом с полем, как «авто:» у К1/К2.
function siteParkingBasis(id){
 const basis=(projectParking()||{}).k_basis||{};
 if(id==='parking_district')
  return basis.district?'. Сейчас в расчёте: '+basis.district+(basis.district_source?', источник — '+basis.district_source:'')
   :'. Сейчас в расчёте района нет: по кадастровому номеру его определить не удалось. Без района льгота по плате за ВРИ за нежилые объекты не считается';
 if(id!=='parking_inside_ttk')return '';
 if(basis.inside_ttk===true||basis.inside_ttk===false)
  return '. Сейчас в расчёте: '+(basis.inside_ttk?'внутри ТТК':'за ТТК')+(basis.ttk_source?', источник — '+basis.ttk_source:'');
 return '. Сейчас в расчёте положение неизвестно: по кадастровому номеру его определить не удалось';
}
// Что принял расчёт при пустом поле — из ответа движка (`parking.k1`, `k_origin`).
function siteParkingPlaceholder(id){
 const p=projectParking()||{};
 const origin={glavapu:'из выгрузки ГлавАПУ',table:'по таблице 945-ПП',upper_edge:'верхний край — мест больше всего'};
 if(id==='parking_k1'||id==='parking_k2'){
  const key=id==='parking_k1'?'k1':'k2';
  const v=Number(p[key]||0);
  if(!v)return 'пусто — посчитается автоматически';
  return 'авто: '+String(v).replace('.',',')+' · '+(origin[(p.k_origin||{})[key]]||'посчитано расчётом');
 }
 if(id==='parking_rail_distance_m')return 'пусто — не задано (К1 тогда по выгрузке или 1,0)';
 return '';
}
// Другой регион — плашкой в карточке участка, пока проект в этом режиме:
// страница прямо говорит, что норм региона у нас нет (решение владельца
// 19.10.2026), а не только в строке состояния, которую перепишет следующий шаг.
function renderOtherRegionNote(){
 const box=document.getElementById('otherRegionNote');
 if(!box)return;
 const other=classRegion()==='other';
 box.style.display=other?'':'none';
 if(!other)return;
 const place=String(((inputs._other_region)||{}).region||'').trim();
 box.textContent=(place?'Участок: '+place+'. ':'')+OTHER_REGION_TEP_NOTE+
  ' Плотность для начала — 30 000 м² квартир на гектар, это наше допущение.';
}
function renderSitePanel(){
 renderSiteParkingFields();
 const areaEl=document.getElementById('siteAreaHa');
 if(!areaEl)return;
 const densityEl=document.getElementById('siteDensity');
 const area=Number(inputs.site_area_ha||0);
 if(document.activeElement!==areaEl)areaEl.value=area>0?area:'';
 const stored=Number(inputs.site_density_sqm_per_ha||0);
 if(document.activeElement!==densityEl)densityEl.value=stored>0?stored:'';
 densityEl.placeholder=num(effectiveSiteDensity());
 document.getElementById('siteAreaSource').textContent=siteAreaSourceLabel();
 {
  const warn=document.getElementById('siteAreaWarning');
  if(warn){const html=siteAreaWarningHtml();warn.innerHTML=html;warn.style.display=html?'':'none'}
 }
 document.getElementById('siteDensitySource').textContent=siteDensitySourceLabel();
 const potential=area*effectiveSiteDensity();
 // Семантика плотности зависит от источника. В нормативном расчёте (РНГП —
 // ручной ТЭП, кадастр, калькулятор Подмосковья) плотность — м² продаваемой
 // площади квартир на гектар: потенциал сравнивается с квартирами, а паркинг
 // и социалка считаются от них нормативами. У Москвы с ГлавАПУ плотность
 // нормирует наземную поэтажную площадь: подземный паркинг в неё не входит.
 const normative=!inputs._glavapu_import;
 const unitEl=document.getElementById('siteDensityUnit');
 if(unitEl)unitEl.textContent=normative?(classRegion()==='other'?'м² квартир / га':'м² квартир / га по нормативам РНГП'):'м² поэтажной площади / га';
 renderOtherRegionNote();
 // Две «плотности» под одним словом путали: московская считается в м² СПП/га,
 // подмосковная — в м² продаваемых квартир/га. Эквивалент по методике
 // ГлавАПУ-ТЭП (квартиры 94% СПП, продаваемая 65% ГНС) держит обе рядом.
 const equivEl=document.getElementById('siteDensityEquiv');
 if(equivEl){
   const density=effectiveSiteDensity();
   // Справка «как считается плотность» — складкой под полями; без плотности
   // ей нечего сказать, и пустая складка на телефоне только занимала бы строку.
   const help=equivEl.closest?equivEl.closest('details.site-help'):null;
   if(help)help.style.display=density>0?'':'none';
   equivEl.textContent=density>0
     ? (normative
        ? 'Здесь плотность — это метры квартир, которые можно продать, на гектар участка. '+
          'По методике Москвы, где плотность меряют поэтажной площадью всех наземных зданий, это примерно '+
          num(density/(0.94*0.65))+' м² на гектар.'
        : 'Здесь плотность — это поэтажная площадь всех наземных зданий на гектар участка, как её меряет Москва. '+
          'По нормативам РНГП, где считают только метры квартир на продажу, это примерно '+num(density*0.94*0.65)+' м² квартир на гектар.')
     : '';
 }
 const potLabel=document.getElementById('sitePotentialLabel');
 if(potLabel)potLabel.textContent=normative?'Потенциал продаваемой площади квартир':'Потенциал поэтажной площади';
 const useLabel=document.getElementById('siteUsageLabel');
 if(useLabel)useLabel.textContent=normative?'Использовано квартирами':'Использовано наземными зданиями';
 let above=0,core=0;
 Object.entries(tep).forEach(([key,row])=>{
   const gns=tepRowAboveGns(key,row);above+=gns;
   if(key==='apartments'||key==='ground_commercial')core+=gns;
 });
 const other=above-core;
 const used=normative?Number((tep.apartments||{}).saleable||0):above;
 document.getElementById('sitePotential').textContent=potential>0?num(potential)+' м²':'—';
 const usage=potential>0?used/potential*100:0;
 document.getElementById('siteUsage').textContent=potential>0?num(usage)+'%':'—';
 const warn=document.getElementById('siteDensityWarn');
 if(potential>0&&used>potential*1.005){
  warn.style.display='';
  warn.innerHTML=normative
   ?'Продаваемая площадь квартир <b>'+num(used)+' м²</b> превышает потенциал <b>'+num(potential)+
    ' м²</b> при плотности '+num(effectiveSiteDensity())+' м² квартир/га. Нажмите «Сформировать ТЭП по новым параметрам» выше — '+
    'таблица пересчитается по нормативам целиком.'
   // Превышение чаще всего создают не квартиры, а офисы/ТЦ/наземный паркинг и
   // соцобъекты: кнопка пересчёта их сознательно не трогает, а потенциал
   // участка они занимают наравне с жильём. Без разбивки это выглядит как
   // ошибка пересчёта.
   :'Площадь наземных зданий проекта <b>'+num(above)+' м²</b> превышает потенциал участка <b>'+num(potential)+
    ' м²</b> при плотности '+num(effectiveSiteDensity())+' м²/га.'+
    (other>0.5?' В составе: жильё и коммерция 1 этажа — <b>'+num(core)+' м²</b>, прочие наземные (офисы, ТЦ, наземный паркинг, соцобъекты) — <b>'+
     num(other)+' м²</b>. Кнопка пересчёта меняет только жильё и коммерцию; отключите лишние объекты или поднимите плотность.'
     :' Проверьте плотность или состав ТЭП.');
 }else warn.style.display='none';
 renderTepActions();
}
function glavapuSocialNp(row){
 const normalized=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 if(!normalized)return 0;
 const key={kindergarten:'actual_kindergarten_np_sqm',school:'actual_school_np_sqm',
            clinic:'actual_clinic_np_sqm'}[row];
 return key?Number(normalized[key]||0):0;
}
function glavapuSocialSpp(row){
 const normalized=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 if(!normalized)return 0;
 const key={kindergarten:'actual_kindergarten_spp_sqm',school:'actual_school_spp_sqm',
            clinic:'actual_clinic_spp_sqm'}[row];
 return key?Number(normalized[key]||0):0;
}
function applyRequiredSocialProgramFromGlavapu(){
 // Режимов, при которых объект строится, два: «Строительство» и «Строительство
 // и компенсация». Второй сюда не попадал вовсе, и потребность города в него
 // не подставлялась — при том что ТЭП он заполняет наравне с первым.
 if(inputs.social_mode!=='Строительство'
    &&inputs.social_mode!=='Строительство и компенсация')return false;
 const normalized=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 if(!normalized)return false;
 let changed=false;
 const mappings=[
   ['kindergarten_places','required_kindergarten_places','social_dou_gba_sqm','social_dou_norm_sqm'],
   ['school_places','required_school_places','social_school_gba_sqm','social_school_norm_sqm'],
   ['clinic_capacity','required_clinic_capacity','social_clinic_gba_sqm','social_clinic_norm_sqm']
 ];
 mappings.forEach(([inputKey,requiredKey,areaKey,normKey])=>{
   const required=Number(normalized[requiredKey]||0);
   if(Number(inputs[inputKey]||0)<=0 && required>0){inputs[inputKey]=required;changed=true}
   if(Number(inputs[areaKey]||0)<=0 && Number(inputs[inputKey]||0)>0){
     inputs[areaKey]=Number(inputs[inputKey]||0)*Number(inputs[normKey]||0);changed=true
   }
 });
 return changed;
}

// Поля вводных, из которых собирается таблица ТЭП. Список объявлен рядом с
// самим `syncTep` и один на всё: связь «поле → ТЭП» держалась на строке в
// обработчике `onchange`, и площадь офиса в неё не попала — объект включался,
// а метры до таблицы не доезжали (замечание владельца, 19.08.2026). Тест
// сверяет список с тем, что `syncTep` читает на самом деле.
// Как делится СПП жилых зданий на жильё и встроенное нежилое. Подставляется
// движком: доля объявлена там один раз, копии здесь нет.
const MKD_SPP_SPLIT=__DEVELOPAID_MKD_SPP_SPLIT__;
const TEP_RATIOS=__DEVELOPAID_TEP_RATIOS__;
// Норматив площади соцобъекта — ступень по ёмкости здания (2151-ПП — нормативы
// Москвы, редакция 2579-ПП). Таблица приходит из движка подстановкой: второй
// копии числа нет.
const SOCIAL_AREA_STEPS=__DEVELOPAID_SOCIAL_AREA_STEPS__;
// Фактический показатель площади на место рядом с нормативом города. Одно
// число без второго читается как норматив: 22,2 м²/место по договору КРТ и 15
// по 2151-ПП — разные ответы на разные вопросы, и подменять первый вторым нельзя.
function socialNormNote(kind){
 const map={kindergarten:['social_dou_gba_sqm','kindergarten_places'],
  school:['social_school_gba_sqm','school_places'],
  clinic:['social_clinic_gba_sqm','clinic_capacity']};
 const pair=map[kind];
 if(!pair)return '';
 const area=Number(inputs[pair[0]]||0),units=Number(inputs[pair[1]]||0);
 if(!(area>0)||!(units>0))return '';
 const fact=area/units;
 const unit=kind==='clinic'?'м²/(пос./смену)':'м²/место';
 const city=socialAreaPerPlace(kind,units);
 return ` Фактически ${landNum(fact,1)} ${unit}`
  +(city?` — норматив Москвы (2151-ПП) ${landNum(city,1)}.`
   :!moscowSocialStepsApply()?` — норматив области (калькулятор МО) / поле.`
   // У поликлиники ступени нет, а предел города — верхний (2150-ПП): число
   // берётся из умолчания поля, второй копии на странице нет.
   :kind==='clinic'?` — предел города не более ${landNum(INPUT_DEFAULT.social_clinic_norm_sqm,0)} (2150-ПП, уточняется МТЗ).`
   :` — ступени города для этого объекта нет.`);
}
// Ступени — московские (2151-ПП в ред. 2579-ПП). У области нормативы свои —
// их несёт поле из калькулятора МО, и ступень города их не перебивает
// (решение владельца 16.10.2026). Предикат тот же, что у движка
// (`moscow_social_steps_apply`): регион проекта `vri_region`, пусто — Москва.
function moscowSocialStepsApply(){return classRegion()==='msk'}
function socialAreaPerPlace(kind,places){
 if(!moscowSocialStepsApply())return 0;
 const steps=SOCIAL_AREA_STEPS[kind];
 const n=Number(places||0);
 if(!steps||!(n>0))return 0;
 for(const [limit,value] of steps){if(limit===null||n<=limit)return value}
 return steps[steps.length-1][1];
}
const MKD_PRODUCTS=__DEVELOPAID_MKD_PRODUCTS__;
// Что под землёй — по размещению кладовых, правило из движка
// (`underground_products`); строки вне суммы наземной ГНС — оттуда же.
const UNDERGROUND_PLACEMENT=__DEVELOPAID_UNDERGROUND_PRODUCTS__;
// Чем считается продукт — из движка. Квартира, машино-место, место в саду и
// посещение в смену несравнимы, и складывать их вместе нельзя; копия этого
// списка на странице разошлась бы с движком молча.
const TEP_COUNT_MEASURE=__DEVELOPAID_TEP_COUNT_MEASURE__;
const COUNT_PARKING=__DEVELOPAID_COUNT_PARKING__;
function countMeasure(key){
 const measure=TEP_COUNT_MEASURE[key];
 return measure===undefined?'шт.':measure;
}
// Число со своей мерой. Метровому продукту штук не полагается вовсе — у него
// их нет, и печатать «0 шт.» значило бы отвечать на вопрос, которого нет.
function countWithMeasure(key,value){
 const measure=countMeasure(key);
 if(!measure)return '<span style="color:#bbb">—</span>';
 return num(value)+' '+measure;
}
// Итог штук — РАЗБОР, а не сумма: «конечно это не надо суммировать»
// (владелец, 27.09.2026). Гараж объекта идёт в машино-места: иначе ответ на
// «сколько мест в проекте» терял бы гараж офисника.
function countsByMeasure(rows,field,garageField){
 const out=new Map();
 (rows||[]).forEach(row=>{
  const value=Number(row[field]||0);
  const measure=countMeasure(row.key);
  if(value&&measure)out.set(measure,(out.get(measure)||0)+value);
  const garage=garageField?Number(row[garageField]||0):0;
  if(garage)out.set(COUNT_PARKING,(out.get(COUNT_PARKING)||0)+garage);
 });
 return out;
}
function countsCell(rows,field,garageField){
 const parts=[];
 countsByMeasure(rows,field,garageField).forEach((value,measure)=>{
  if(value)parts.push(num(value)+' '+measure);
 });
 return parts.length?parts.join('<br>'):'<span style="color:#bbb">—</span>';
}
// Разделы таблицы ТЭП — из движка. Третий раздел объявлен пустым списком и
// собирает всё, что не попало в первые два: продукт, заведённый позже, обязан
// остаться в таблице, а не исчезнуть из неё молча.
const TEP_GROUPS=__DEVELOPAID_TEP_GROUPS__;
function tepGroupRows(){
 const seen=new Set();
 const groups=TEP_GROUPS.map(([title,keys])=>{
  const rows=keys.filter(k=>tep[k]&&objectInProject(k));
  keys.forEach(k=>seen.add(k));
  return {title:title, keys:rows};
 });
 const rest=Object.keys(tep).filter(k=>!seen.has(k)&&objectInProject(k));
 // Остаток кладётся в раздел, объявленный пустым; такого нет — заводится
 // последним, чтобы строка не пропала.
 const tail=groups.find(g=>!g.keys.length)||groups[groups.length-1];
 if(tail)tail.keys=tail.keys.concat(rest); else groups.push({title:'Прочее',keys:rest});
 return groups.filter(g=>g.keys.length);
}
const PARKING_2118=__DEVELOPAID_PARKING_2118__;
const AVERAGE_FLAT=__DEVELOPAID_AVERAGE_FLAT__;
const VRI_USE_TYPES=__DEVELOPAID_VRI_USE_TYPES__;

// ТЭП собирают руками, и известно обычно одно число из трёх. Пропорции
// достраивают остальные — в обе стороны: от ГНС вниз к продаваемой и от
// продаваемой вверх к ГНС (просьба владельца, 19.08.2026). Заполняются только
// пустые ячейки: введённое человеком и пришедшее из ГлавАПУ сильнее пропорции.
function tepFillByRatios(key,row){
 const r=tepRatio(key);
 if(!r)return {...row};
 const out={...row};
 let gns=Number(out.gns||0),total=Number(out.total_area||0),sale=Number(out.saleable||0);
 // Обе доли считаются от ГНС — так они заданы у калькулятора; «продаваемая от
 // общей» это их частное, и хранить его отдельно значило бы завести второе
 // число для одной величины.
 if(!gns&&total)gns=total/r.total_of_gns;
 if(!gns&&sale)gns=sale/r.saleable_of_gns;
 if(!total&&gns)total=gns*r.total_of_gns;
 if(!sale&&gns)sale=gns*r.saleable_of_gns;
 const round=value=>Math.round(Number(value||0)*10)/10;
 out.gns=round(gns);out.total_area=round(total);out.saleable=round(sale);
 // Полезная площадь у этих продуктов равна продаваемой: разводить их незачем,
 // а нулевая полезная при непустой продаваемой ломает удельные показатели.
 if(!Number(out.useful||0))out.useful=out.saleable;
 return out;
}

// Переданные метры строятся, но не продаются. Тождество строки одно, и
// объявлено оно в движке (`saleable_after_transfer`): полезная — построенная
// площадь, продаваемая — она же за вычетом переданного. Полезная от передачи
// НЕ уменьшается: метры построены и полезны, просто не наши (владелец,
// 10.09.2026).
//
// Прежде здесь считалась ДЕЛЬТА — «минус разница с прошлым числом», — и
// подпись под строкой называла именно её: в поле стояло 5 000, а на экране
// «Переданные 4 000 м² убраны из продаваемой» (экран владельца, 10.09.2026).
// Дельту помнить не нужно вовсе: полная площадь известна, и продаваемая
// считается заново.
function tepApplyTransfer(key,usefulGross){
 const row=tep[key];if(!row)return 0;
 const round=v=>Math.round(Number(v||0)*10)/10;
 const useful=Math.max(0,round(usefulGross));
 const transfer=Math.max(0,Number(row.transfer||0));
 row.useful=useful;
 row.saleable=Math.max(0,round(useful-transfer));
 // Переданное больше построенного не обрезается молча — это расхождение
 // человека с его же строкой, и оно называется. Тона два: расхождение — жалоба,
 // а обычная передача — сообщение о посчитанном, и красным его красить незачем.
 // Получателя метров модель не знает, поэтому слово и оговорка приходят
 // подстановкой (`TRANSFER_LABELS`), а не пишутся здесь «городу».
 if(transfer>useful){
  setTepNote(key,'Передаётся '+landNum(transfer,0)+' м² при полезной площади '+landNum(useful,0)
   +' м²: передаётся больше, чем строится.');
 }else if(transfer>0){
  setTepNote(key,TRANSFER_WORD+' '+landNum(transfer,0)+' м² из '+landNum(useful,0)
   +' м² полезной площади — они строятся, но не продаются. '+TRANSFER_RECIPIENT_NOTE+'.','');
 }else{
  setTepNote(key,'');
 }
 return row.saleable;
}

const UNDERGROUND_PAIR_INPUTS=['underground_manual_spaces','underground_manual_gns_sqm',
 'underground_area_per_space_sqm'];
const TEP_DERIVED_INPUTS=UNDERGROUND_PAIR_INPUTS.concat([
 'underground_parking_disabled',
 // Поля объектов, от которых считается их строка ТЭП, — из реестра движка,
 // подстановкой списка при сборке страницы.
 __DEVELOPAID_TEP_DERIVED_OBJECT_INPUTS__,
 'social_mode','kindergarten_places','school_places','clinic_capacity',
 'social_area_source',
 'social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm']);

// Пересчёт производных под фактический ТЭП. Калькулятор ГлавАПУ считает по
// нормативу — плотность на площадь участка; когда ТЭП утверждён решением ГЗК и
// метров в разы меньше, соцнагрузка, плата за ВРИ и машино-места остаются от
// норматива и завышены кратно (владелец, 20.08.2026). Считает сервер теми же
// формулами, что и бот, и подписывает ответ своим именем: подменять городской
// расчёт молча нельзя.
function glavapuCoefficients(){
 const imported=(inputs._glavapu_import||{});
 // Оснований два источника: ответ анализа по кадастровому номеру и выгрузка
 // калькулятора, приложенная файлом. Выгрузка главнее: в ней те же числа, но
 // в том виде, в каком их посчитал город.
 const norm=imported.normalized||{};
 const coeff=Object.assign({},imported.coefficients||{},
  norm.rent_coefficient?{rent:norm.rent_coefficient}:{},
  norm.vri_base_cost_rub?{base_cost_zh_high:norm.vri_base_cost_rub}:{});
 const territory=imported.territory||{};
 const inside=!!territory.inside_ttc;
 return {
  bases:(norm.vri_base_costs_by_use||{}),
  k1:Number(coeff.rail||0),
  k2:Number((inside?coeff.business_inside_ttc:coeff.business_outside_ttc)||0),
  rent:Number(coeff.rent||0),
  base:Number(coeff.base_cost_zh_high||0),
  upks:Number(coeff.upks_zh_high||0),
  inside:inside,
  district:String(territory.district||''),
  quarter:String(territory.cadastral_quarter||'')
 };
}

// Свой расчёт платы за ВРИ: строки типов использования приходят из движка,
// метры и основания задаёт человек. Базовая стоимость МКД подставляется из
// импорта; остальные типы человек берёт с листа «Параметры территории» своей
// выгрузки — у нас их нет, и выдумывать их нельзя.
// Карточки своего расчёта ВРИ больше нет (владелец, 20.08.2026):
// его работу делает «Пересчитать под фактический ТЭП» — плата считается
// по ставкам исходной выгрузки вместе с социалкой и машино-местами.
// Сама формула города осталась в движке (vri_manual_payment): ею пересчёт
// подтверждает свою пропорцию, и /vri/manual отвечает по-прежнему.

// Обратный счёт в Московской области. РНГП считает всё от населения, а
// население — от площади квартир: поставили 200 000 вместо 672 690 — и ДОО,
// СОШ, поликлиника, машино-места, рабочие места и плата за ВРИ обязаны упасть
// втрое. Прежде правка квартир меняла только свою строку: соцобъекты
// оставались от объёма, которого больше нет, и баланс территории уходил в
// минус (владелец, 23.08.2026: «всё же должно обратным счётом поменяться»).
//
// Формулы для этого уже написаны в `applyNormativeTep` — их просто никто не
// звал при ручной правке: кнопка считает вперёд от плотности, а не назад от
// метров. Здесь плотность выводится из самих метров.
//
// Пересчёт идёт, только когда изменились КВАРТИРЫ: они драйвер нормативов.
// Правка офисов или коммерции своего населения не создаёт, и гнать по ней
// нормативный расчёт значило бы затирать введённое человеком.
// Что задано требованием КРТ, пересчёт не трогает. До этого признак защищал
// только ПЛОЩАДЬ и норматив соцобъекта, а места, соцкомпенсацию и плату за
// ВРИ три пересчёта переписывали молча: «ввожу из КРТ ГНС в ТЭП, и автоматом
// всё пересчитывает — возвращает ВРИ сам, кол-во мест в садике и ДОО
// вставляет из ГлавАПУ… и этот флажок включен» (владелец, 04.09.2026).
// Список запертого объявлен ОДИН раз: три копии разошлись бы, и починенный
// пересчёт выглядел бы как починенные все.
const KRT_REQUIREMENT_INPUTS=['kindergarten_places','school_places','clinic_capacity',
 'social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm',
 'social_dou_norm_sqm','social_school_norm_sqm','social_clinic_norm_sqm',
 'social_compensation_mln','land_rights_cost_mln'];
const KRT_REQUIREMENT_LABELS={kindergarten_places:'места ДОО',school_places:'места СОШ',
 clinic_capacity:'мощность поликлиники',social_dou_gba_sqm:'площадь ДОО',
 social_school_gba_sqm:'площадь СОШ',social_clinic_gba_sqm:'площадь поликлиники',
 social_dou_norm_sqm:'норматив ДОО',social_school_norm_sqm:'норматив СОШ',
 social_clinic_norm_sqm:'норматив поликлиники',
 social_compensation_mln:'соцкомпенсация',land_rights_cost_mln:'плата за ВРИ'};
function krtRequirementEntered(){return String(inputs.social_area_source||'norm')==='manual'}
// Заперто ли ЭТО поле. Правило одно, читателей два: писатель вводных и
// отчёт о пересчёте. Пока отчёт выводил причину из расхождения чисел, он
// называл замком КРТ и то, для чего метод просто не дал числа.
function krtLocks(key){
 return krtRequirementEntered()&&KRT_REQUIREMENT_INPUTS.indexOf(key)>=0;
}
// Режим «Требование КРТ» плату за смену ВРИ НЕ отменяет: её уменьшают льготы
// проекта — за МПТ от нежилых объектов (1874-ПП) и за передачу квартир городу,
// и в сумме они могут обнулить плату (владелец, 13.10.2026). Считает их движок
// (`vri_relief` → `vri_benefits_for`), страница только показывает результат.
//
// Прежде переключение в КРТ обнуляло поле и запоминало убранное в
// `_krt_vri_cleared_mln`. Обнулял наш код, а не человек, — поэтому у
// сохранённых так проектов плата возвращается при загрузке и об этом
// говорится у поля (решение владельца, 13.10.2026).
function restoreKrtClearedVriFee(){
 const was=Number(inputs._krt_vri_cleared_mln||0);
 if(!(was>0))return false;
 delete inputs._krt_vri_cleared_mln;
 if(Number(inputs.land_rights_cost_mln||0)>0)return false;
 inputs.land_rights_cost_mln=was;
 inputs._krt_vri_restored_mln=was;
 return true;
}

// Действует ли плата за смену ВРИ — тот же ответ, что у движка
// (`vri_payment_active`): решает сумма платы, а не признак. Признак
// «Требуется изменение ВРИ» — вид суммы: при плате > 0 он включён, снять его
// — значит обнулить плату. Сохранённый старый явный false плату не обнуляет.
function vriPaymentActive(x){return Number((x||inputs).land_rights_cost_mln||0)>0}
// Плата, обнулённая снятием признака на этой странице, — чтобы подпись
// называла, что именно сделала галочка.
let vriFeeClearedMln=0;
// Галочку пытались поставить без суммы: клик не откатывается молча, а
// объясняет, откуда взять плату (владелец, 22.10.2026: «почему не могу
// нажать кнопку ВРИ?»).
let vriFeeAskedWithoutSum=false;
// Откуда в этом проекте берётся плата за смену ВРИ, если её нет. Московский
// участок — из калькулятора ГлавАПУ (строка 44 ТЭП) по его кадастровым
// номерам; площадка КРТ, чьи участки перечня не покрывают территорию,
// плату оттуда не получит — это сказано прямо.
function vriFeeWhereFrom(){
 const imp=inputs._manual_tep_import||{};
 const terr=imp.territory||{};
 if(((imp.source||{}).kind)==='krt'){
  const land=Number(terr.land_area_ha||0),all=Number(imp.site_area_ha||0);
  const ha=v=>Number(v).toLocaleString('ru-RU',{maximumFractionDigits:4});
  const part=all>0&&land>0&&land<all*0.9
   ?' Участки из перечня проекта решения занимают '+ha(land)+' га из '+ha(all)+' га территории — по ним калькулятор ГлавАПУ посчитает плату только за эту часть.'
   :all>0&&!(land>0)?' Участков с границами в проекте решения не нашлось, поэтому посчитать плату по ним нечем.':'';
  return 'Для площадки КРТ плата за смену ВРИ в карточке торгов не считается.'+part
   +' Впишите сумму из расчёта ГлавАПУ или договора КРТ.';
 }
 if(classRegion()==='msk')return 'В Москве плату считает калькулятор ГлавАПУ: на шаге «Участок» введите кадастровые номера и нажмите «Получить ТЭП» — плата придёт вместе с ТЭП. Или впишите сумму сами.';
 return 'Впишите сумму платы в поле ниже.';
}
function vriRequiredNote(){
 const fee=Number(inputs.land_rights_cost_mln||0);
 const o=(inputs._field_origin||{})['inputs.land_rights_cost_mln'];
 const from=o&&o.source==='glavapu'?' (из ГлавАПУ)':o&&o.source==='manual'?' (вписана вручную)':'';
 if(fee>0)return `Плата ${num(fee)} млн ₽ задана${from} — смена ВРИ учитывается. Снять признак — значит обнулить плату.`;
 if(vriFeeClearedMln>0)return `Плата ${num(vriFeeClearedMln)} млн ₽ обнулена снятием признака — смена ВРИ не учитывается.`;
 // Льгота без платы ни на что не действует — и молча стоять не должна.
 const relief=inputs.vri_relief_mode==='amount'?Number(inputs.vri_relief_mln||0):0;
 const reliefLine=relief>0?` Вписанная льгота ${num(relief)} млн ₽ без платы ни на что не действует.`:'';
 if(vriFeeAskedWithoutSum)
  return 'Галочка ставится сама, когда задана сумма платы: смену ВРИ в расчёте включает сумма, а не галочка. Сейчас плата — 0. '
   +vriFeeWhereFrom()+reliefLine;
 return 'Плата за смену ВРИ не задана — смена ВРИ не учитывается. Чтобы учесть, впишите сумму в «Оформление земельных правоотношений / смена ВРИ».'+reliefLine;
}
// Кнопка у подписи: ведёт к полю суммы. Узел постоянный, виден только
// после попытки поставить галочку без платы.
function vriFeeGoNode(){
 const b=document.createElement('button');
 b.type='button';b.id='vriFeeGo';b.className='btn';
 b.textContent='Вписать сумму платы';
 b.style.cssText='margin:6px 0 0';
 b.onclick=focusVriFeeField;
 b.style.display=vriFeeAskedWithoutSum&&!vriPaymentActive()?'':'none';
 return b;
}
function focusVriFeeField(){
 const field=document.getElementById('f_land_rights_cost_mln');
 if(!field)return;
 // Поле суммы стоит на другой вкладке (вводные), а скрытое поле фокус не
 // принимает: прежний откат с фокусом поэтому не делал ничего видимого.
 const panel=field.closest?field.closest('.panel'):null;
 if(panel&&!panel.classList.contains('active')){
  const tab=document.querySelector('.tabs [data-tab="'+panel.id+'"]');
  if(tab)tab.click();
 }
 const group=field.closest?field.closest('details'):null;
 if(group&&!group.open)group.open=true;
 if(field.scrollIntoView)field.scrollIntoView({block:'center'});
 field.focus();
}
// Подпись под полем ВРИ: узел с постоянным id, пустая — скрыта.
function vriNoteNode(id,text){
 const node=document.createElement('div');
 node.id=id;node.className='hint vri-note';
 node.style.cssText='margin:4px 0 0;color:#666;font-size:12px';
 vriNoteFill(node,text);
 return node;
}
function vriNoteFill(node,text){
 node.textContent=text;
 node.style.display=text?'':'none';
}
function syncVriRequiredBox(){
 inputs.vri_required=vriPaymentActive();
 const el=document.getElementById('f_vri_required');
 if(el)el.checked=inputs.vri_required;
 if(inputs.vri_required)vriFeeAskedWithoutSum=false;
 const note=document.getElementById('vriRequiredNote');
 if(note)vriNoteFill(note,vriRequiredNote());
 const go=document.getElementById('vriFeeGo');
 if(go)go.style.display=vriFeeAskedWithoutSum&&!inputs.vri_required?'':'none';
}
function vriRequiredToggled(el){
 const fee=Number(inputs.land_rights_cost_mln||0);
 if(!el.checked&&fee>0){
  if(!confirm('Снять признак «Требуется изменение ВРИ» — значит обнулить плату за ВРИ '+num(fee)+' млн ₽.\n\nОбнулить плату?')){el.checked=true;return}
  inputs.land_rights_cost_mln=0;
  markFieldManual('inputs.land_rights_cost_mln');
  vriFeeClearedMln=fee;
 }
 if(el.checked&&!(fee>0)){
  // Включить признак без суммы нечем: плату решает сумма. Но молча
  // откатывать клик нельзя — подпись и кнопка говорят, что сделать.
  el.checked=false;
  vriFeeAskedWithoutSum=true;
 }
 syncVriRequiredBox();
 const land=document.getElementById('f_land_rights_cost_mln');
 if(land)land.value=inputs.land_rights_cost_mln;
 calculate();
}
function krtVriFeeNote(){
 const back=Number(inputs._krt_vri_restored_mln||0);
 return '<div class="note krt-vri-fee-note" style="margin:0 0 6px;padding:11px 12px">'
  +'Ручной ввод соцобъектов плату за смену ВРИ не отменяет. Её уменьшают льготы проекта '
  +'за нежилые объекты (МПТ) и за передачу квартир городу. Расчёт — в конце блока «Социальная нагрузка».'
  +(back>0?` Возвращено ${num(back)} млн ₽: прежняя версия расчёта при ручном вводе соцобъектов обнуляла плату.`:'')
  +'</div>';
}

// Подвал блока «Социальная нагрузка» в КРТ: от чего льгота, сколько, и что
// остаётся к оплате. Все числа — из результата движка (`vri.totals`,
// `vri.benefits`): страница не считает льготу второй раз.
function krtVriFooterHtml(vri){
 const head='<div class="krt-vri-footer-head" style="font-weight:600;margin-bottom:4px">Плата за смену ВРИ при ручном вводе соцобъектов</div>';
 const wrap=html=>'<div class="note krt-vri-footer" style="margin:10px 0 0;padding:11px 12px">'+head+html+'</div>';
 if(!vri||!vri.totals)return wrap('Пересчитайте проект — здесь появится льгота и плата к оплате.');
 const t=vri.totals, b=vri.benefits||{};
 const mln=v=>num(Number(v||0)/1e6);
 const gross=Number(t.gross||0), relief=Number(t.relief||0), pay=Math.max(0,gross-relief);
 if(!(gross>0))return wrap('Плата за смену ВРИ в проекте не задана — льготе нечего уменьшать.');
 const basis=String(t.relief_basis||'none');
 const rows=(b.rows||[]);
 const lines=[];
 if(b.override)lines.push(`Льгота за МПТ ${escapeHtml((b.mpt_source||{}).text||'')}: ${num(b.override.benefit_mln)} млн ₽ — заменяет посчитанную по участку проекта`);
 else rows.filter(r=>Number(r.benefit_mln||0)>0).forEach(r=>lines.push(
  `${escapeHtml(r.label)} — ${num(r.area_sqm)} м²: льгота за МПТ ${num(r.benefit_mln)} млн ₽`));
 if(Number(b.transfer_mln||0)>0)lines.push(
  `Передача квартир городу — ${num((b.transfer||{}).area_sqm)} м²: ${num(b.transfer_mln)} млн ₽`);
 const blocked=rows.filter(r=>!(Number(r.benefit_mln||0)>0)&&r.category&&(r.blockers||[]).length)
  .map(r=>`${escapeHtml(r.label)}: ${escapeHtml(r.blockers.join('; '))}`);
 const list=lines.length?'<ul style="margin:4px 0 6px 18px;padding:0">'+lines.map(x=>'<li>'+x+'</li>').join('')+'</ul>':'';
 const why=blocked.length?'<div style="font-size:12px;color:#8a4b08;margin:4px 0">Без льготы: '+blocked.join('<br>')+'</div>':'';
 const total=`Плата до льгот ${mln(gross)} млн ₽ − льгота ${mln(relief)} млн ₽ = <b>к оплате ${mln(pay)} млн ₽</b>.`;
 if(basis==='percent'||basis==='amount'){
  return wrap('Льгота вписана руками — она главнее расчётной'
   +(Number(b.total_mln||0)>0?` (по проекту вышло ${num(b.total_mln)} млн ₽)`:'')+'. '+total+list+why);
 }
 if(basis==='off')return wrap('Выбран отказ от льготы'
  +(Number(b.total_mln||0)>0?` (по проекту вышло бы ${num(b.total_mln)} млн ₽)`:'')+'. '+total);
 if(!b.applicable)return wrap(escapeHtml(b.reason||'Льготы по проекту не посчитаны.')
  +' Льготы нет — плата за ВРИ начисляется: <b>к оплате '+mln(pay)+' млн ₽</b>.');
 if(relief>0){
  return wrap('Льгота посчитана по проекту и уже вычтена из платы:'+list+total
   +(Number(b.total_mln||0)*1e6>gross+1?' Льготы больше платы — к оплате ноль, остаток не переносится.':'')+why);
 }
 if(b.mpt_reason&&!b.override)return wrap(escapeHtml(b.mpt_reason)
  +' Пока льготы нет — <b>плата за ВРИ начисляется: '+mln(pay)+' млн ₽</b>.'+why);
 return wrap('Льготы нет: в проекте нет нежилых объектов с льготой за МПТ и передачи квартир городу. '
  +'Ручной ввод соцобъектов плату не отменяет, поэтому <b>плата за ВРИ начисляется: '+mln(pay)+' млн ₽</b>.'+why);
}
function renderKrtVriFooter(){
 const box=document.getElementById('krtVriFooter');
 if(box)box.innerHTML=krtVriFooterHtml((lastResult||{}).vri);
}

// Пишет только незапертое и возвращает подпись о том, чего НЕ тронуло: молча
// не тронутое поле выглядит так же, как не посчитанное.
// Строка отчёта про ОДНО поле: что в нём стоит сейчас и почему.
//
// Список «подставлено» строился ДО подстановки, а запертое требованием КРТ не
// подставлялось — и одно поле выходило описанным дважды и противоположно:
// «Плата за ВРИ: было 18 265,9 → стало 10 166,6», а ниже «Не тронуто —
// вписано требованием КРТ: … плата за ВРИ» (экран владельца, 26.09.2026).
// Верхняя строка утверждала подстановку, которой не было, и заголовок над ней
// говорил «Подставлено».
//
// Причина берётся у правила (`krtLocks`) и у того, предлагалось ли число
// вовсе, а не выводится из того, что числа разошлись: «не тронули, потому что
// заперто» и «не тронули, потому что метод числа не дал» лечатся разным, а по
// расхождению они неразличимы.
function derivedLine(name,key,counted,offered){
 const kept=Number(inputs[key]||0),now=Number(counted||0);
 if(krtLocks(key))
  return name+': осталось '+num(kept)+'. Соцобъекты вписаны вручную, и пересчёт это поле не меняет.'
   +(Math.abs(kept-now)<0.001?'':' По расчёту вышло бы '+num(now)+'.');
 if(!offered)
  return name+': осталось '+num(kept)+' — метод числа не дал, поле не тронуто';
 return name+': '+num(kept);
}
// `options.keepManual` — массив: вписанное вручную поле не перезаписывается,
// его подпись складывается туда (импорт выгрузки называет это сам);
// `options.written(key)` — отметка записанного поля (происхождение).
function applyDerivedInputs(values,options){
 const skipped=[];
 const keepManual=options&&options.keepManual;
 Object.keys(values||{}).forEach(key=>{
  if(krtLocks(key)){
   skipped.push(KRT_REQUIREMENT_LABELS[key]||key);return;
  }
  if(keepManual&&isFieldManual('inputs.'+key)){
   keepManual.push(TERRITORY_CLEARED_LABELS[key]||key);return;
  }
  inputs[key]=values[key];
  // Записанное пересчётом больше не ручное: отметка «вписано вручную»
  // пережила бы своё число и заперла бы поле от следующего пересчёта.
  if(isFieldManual('inputs.'+key))delete fieldOrigins()['inputs.'+key];
  if(options&&options.written)options.written(key);
 });
 return skipped.length
  ?'Не тронуто, потому что вписано вручную: '+skipped.join(', ')+'.'
  :'';
}
// Отложенный пересчёт ТЭП. Объявление обязано быть: `clearTimeout(tepAutoTimer)`
// читает переменную ПЕРВЫМ, до всякого присваивания, и на необъявленной это
// не тихий undefined, а ReferenceError — он рвёт загрузку страницы там, где
// её застал. Объявление жило здесь и потерялось 23.08.2026 при чистке
// соседнего блока; двенадцать дней правка ТЭП по выгрузке ГлавАПУ роняла
// страницу молча (экран владельца, 03.09.2026).
let tepAutoTimer=null;
let moAutoApartments=null;
let moAutoBusy=false;
function moNormativeApartments(){
 return Number((inputs._mo_calc||{}).apartments_saleable||0);
}
function scheduleTepAutoRecalc(changedKey){
 // Автопересчёт нормативов запускает только изменение ЖИЛОЙ базы. Офис,
 // коммерция, кладовые и их доли не создают население. Раньше любая правка
 // ТЭП по проекту с ГлавАПУ запускала общий recalc: смена 50→60% офисника
 // показывала новое население, соцкомпенсацию и ВРИ, хотя квартира не
 // изменилась ни на метр.
 if(changedKey!=='apartments')return;
 const baseline=((inputs._glavapu_import||{}).normalized)||null;
 if(baseline&&Number(baseline.change_vri_mln||0)){
  clearTimeout(tepAutoTimer);
  // Правка идёт ячейка за ячейкой; считать после каждой значит слать запрос на
  // каждый символ и показывать промежуточные числа как результат.
  tepAutoTimer=setTimeout(()=>{recalcFromTep({silent:true})},500);
  return;
 }
 // Московская область: своей выгрузки нет, но есть нормативы РНГП.
 if(!inputs._mo_calc)return;
 const area=Number(inputs.site_area_ha||0);
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!(area>0&&apartments>0))return;
 // Пересчёт сам переписывает строку квартир — без этой отсечки он звал бы себя
 // по кругу.
 if(moAutoBusy)return;
 const known=moAutoApartments!==null?moAutoApartments:moNormativeApartments();
 if(known>0&&Math.abs(apartments-known)<=Math.max(1,known*0.0005))return;
 clearTimeout(tepAutoTimer);
 tepAutoTimer=setTimeout(()=>{recalcMoFromApartments(apartments,area)},500);
}
// Пояснение обратного счёта: что пересчитано, что сохранено и что поменялось
// (было → стало). Молча заменённое число неотличимо от посчитанного.
function moBackcountNote(typed,unitsWas,offered){
 const now=Number((tep.apartments&&tep.apartments.units)||0);
 const parts=['Нормативы пересчитаны под '+num(Number(typed.saleable||0))+' м² квартир: '
  +'социалка, машино-места, рабочие места и плата за ВРИ следуют за объёмом.'];
 parts.push('Вписанные площади квартир сохранены: ГНС '+num(Number(typed.gns||0))
  +' м², общая '+num(Number(typed.total_area||0))+' м², продаваемая '
  +num(Number(typed.saleable||0))+' м².'
  +(Math.abs(Number(offered.gns||0)-Number(typed.gns||0))>=0.05&&Number(offered.gns||0)>0
    ?' Нормативные доли дали бы ГНС '+num(Number(offered.gns||0))+' м² — не подставлено.':''));
 if(Math.abs(now-unitsWas)>=0.05)
  parts.push('Число квартир пересчитано от продаваемой: было '+num(unitsWas)+' → стало '+num(now)+'.');
 return parts.join(' ');
}
async function recalcMoFromApartments(apartments,area){
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';
  note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 moAutoBusy=true;
 try{
  const density=apartments/area;
  say('Пересчитываю нормативы РНГП под '+num(apartments)+' м² квартир: '
   +'плотность '+num(density)+' м²/га, население, социалка, машино-места и плата за ВРИ…',false);
  const row=tep.apartments||{};
  // Столбцы, которые берутся у человека, а не у ответа: это и есть вписанное.
  // Число квартир сюда не входит — оно выход формулы от продаваемой, и
  // прежнее число описывало бы прежний объём.
  const typed={};
  ['gns','total_area','saleable','useful','transfer'].forEach(col=>{typed[col]=Number(row[col]||0)});
  const unitsWas=Number(row.units||0);
  const data=await applyNormativeTep(density,{apartments:typed});
  moAutoApartments=Number((tep.apartments&&tep.apartments.saleable)||0);
  say(moBackcountNote(typed,unitsWas,((data||{}).tep||{}).apartments||{}),true);
 }catch(e){
  // Молчать нельзя: человек уже видит новые квартиры и старую социалку рядом,
  // и без объяснения это выглядит посчитанным.
  say('Нормативы под новый объём не пересчитались: '+escapeHtml(e.message||e)
   +'. Социалка, машино-места и плата за ВРИ остались от прежнего объёма.',false);
 }finally{moAutoBusy=false}
}

// Пересчёт под фактический ТЭП, когда выгрузки ГлавАПУ нет.
//
// Считается то, для чего есть все основания, и НЕ считается то, для чего их
// нет: каждое число подписано основанием, каждый пропуск — причиной. Считает
// сервер, экран только показывает и подставляет подтверждённое — арифметики
// здесь нет ни одной.
// Соцнагрузка, которую можно пересчитать пропорцией, и метры, под которые она
// посчитана. Отметка ставится там, где числа появляются: при импорте, после
// пересчёта и при ручной правке. Без неё пропорцию считать не от чего — а
// угадывать площадь по числу мест значило бы обратить норматив, которого в
// Подмосковье нет.
const SOCIAL_SCALED_KEYS=['kindergarten_places','school_places','clinic_capacity',
 'social_compensation_mln','underground_manual_spaces'];
function stampSocialBasis(source){
 inputs._social_basis={
  apartment_area_sqm:Number((tep.apartments&&tep.apartments.saleable)||0),
  nonresidential_sqm:nonresidentialAboveSqm(),
  source:String(source||'')};
}
function nonresidentialAboveSqm(){
 return Number((tep.ground_commercial&&tep.ground_commercial.total_area)||0)
  +standaloneProductSum('total_area',['offices','standalone_retail']);
}
// Сумма поля строк ТЭП по продуктам: «офисы» — это офисы и второй офисник.
// Перечисленные одним ключом, они не видели второго объекта того же рода.
function standaloneProductSum(field,products){
 return STANDALONE_OBJECTS.filter(o=>products.includes(o.product))
  .reduce((sum,o)=>sum+Number((tep[o.key]&&tep[o.key][field])||0),0);
}

// Пропорция: места зависят от населения, население — от площади квартир,
// ставка за место задана экспертно. Норматив здесь не применяется вовсе,
// поэтому это работает и в Подмосковье, где московских нормативов нет
// (владелец, 30.08.2026).
// Какой дорогой пойдёт «Пересчитать по нормативам» — один предикат на
// действие и на подсказку у кнопки: выгрузка ГлавАПУ с платой за ВРИ — по
// её ставкам; Подмосковье — нормативами области (тем же пересчётом, что идёт
// сам после правки квартир); иначе пропорция от прежней соцнагрузки, если
// квартиры изменились; иначе — нормативы Москвы от текущего ТЭП, а вне
// Москвы без расчёта области — честный отказ. Подсказка
// говорит и то, идёт ли пересчёт сам (`scheduleTepAutoRecalc`): с выгрузкой
// ГлавАПУ и в Подмосковье — да, в остальных случаях только по кнопке
// (владелец, 18.10.2026: «а когда не происходит?»).
function glavapuBaselineApplies(){
 const baseline=((inputs._glavapu_import||{}).normalized)||null;
 return !!(baseline&&Number(baseline.change_vri_mln||0));
}
function socialRescaleApplies(){
 const basis=inputs._social_basis||null;
 const after=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!basis||!Number(basis.apartment_area_sqm||0)||!after)return false;
 return Math.abs(after-Number(basis.apartment_area_sqm||0))>=1;
}
function tepNormsMode(){
 const lead='Если вы ввели новые площади квартир, ';
 if(glavapuBaselineApplies())return {key:'glavapu',auto:true,
  text:lead+'соцнагрузка (детсады, школы, поликлиника), машино-места и платежи городу пересчитываются сами — по ставкам из расчёта ГлавАПУ. Кнопка повторит пересчёт и покажет, что изменилось.'};
 if(inputs._mo_calc)return {key:'mo',auto:true,
  text:lead+'соцнагрузка (детсады, школы, поликлиника), машино-места и платежи городу пересчитываются сами — по нормативам Московской области. Кнопка повторит пересчёт вручную.'};
 if(socialRescaleApplies())return {key:'proportion',auto:false,
  text:lead+'пересчитайте соцнагрузку (детсады, школы, поликлиника) и машино-места — сами они здесь не меняются. Изменятся в той же пропорции, что и число жителей; перед заменой покажем, что изменится.'};
 // Участок вне Москвы, а расчёта области нет: московские нормативы сервер к
 // нему не применяет, и обещать их подсказка не должна. Другой регион — тот
 // же ответ: норм его у нас нет.
 if(classRegion()==='other')return {key:'region',auto:false,
  text:lead+'детсады, школы, поликлинику и машино-места здесь сами не пересчитать: участок не в Москве и не в Московской области, а норм его региона у нас нет. Сейчас там наши умолчания — поправьте их во «Вводных».'};
 if((((cadastralAnalysis||{}).territory)||{}).inside_moscow===false)return {key:'region',auto:false,
  text:lead+'детсады, школы, поликлинику и машино-места здесь сами не пересчитать: участок не в Москве, а нормативы его региона не загрузились. Впишите эти числа во «Вводных» вручную.'};
 return {key:'norms',auto:false,
  text:lead+'пересчитайте соцнагрузку (детсады, школы, поликлиника) и машино-места по нормативам Москвы — сами они здесь не меняются. Перед заменой покажем, что изменится.'};
}
function renderTepActions(){
 const hint=document.getElementById('tepNormsHint');
 if(hint)hint.textContent=tepNormsMode().text;
}
async function rescaleSocialFromTep(options){
 const silent=!!(options&&options.silent);
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 const basis=inputs._social_basis||null;
 const after=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!socialRescaleApplies())return false;
 let d;
 try{
  const r=await fetch('/tep/rescale-social',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({apartment_area_before_sqm:Number(basis.apartment_area_sqm||0),
    apartment_area_after_sqm:after,
    nonresidential_before_sqm:Number(basis.nonresidential_sqm||0),
    nonresidential_after_sqm:nonresidentialAboveSqm(),
    kindergarten_places:Number(inputs.kindergarten_places||0),
    school_places:Number(inputs.school_places||0),
    clinic_capacity:Number(inputs.clinic_capacity||0),
    social_compensation_mln:Number(inputs.social_compensation_mln||0),
    underground_manual_spaces:Number(inputs.underground_manual_spaces||0),
    basis:String(basis.source||'')})});
  d=await r.json();
  if(!r.ok)return false;
 }catch(e){return false}
 const lines=[
  'ДОО '+num(inputs.kindergarten_places)+' → '+num(d.places.kindergarten)
   +' · школа '+num(inputs.school_places)+' → '+num(d.places.school)
   +' · поликлиника '+num(inputs.clinic_capacity)+' → '+num(d.places.clinic),
  'Соцкомпенсация, млн ₽: '+num(inputs.social_compensation_mln)+' → '+num(d.compensation_mln),
  'Машино-места подземные: '+num(inputs.underground_manual_spaces)+' → '+num(d.underground_manual_spaces)];
 (d.warnings||[]).forEach(w=>lines.push('⚠ '+w));
 if(!silent&&!confirm('Пересчёт соцнагрузки пропорцией под новый ТЭП:\n\n'
   +lines.join('\n')+'\n\nПодставить в модель?'))
  {say(lines.map(escapeHtml).join('<br>'),true);return true}
 const derived={kindergarten_places:d.places.kindergarten,school_places:d.places.school,
  clinic_capacity:d.places.clinic};
 if(Number(inputs.social_compensation_mln||0)>0)derived.social_compensation_mln=d.compensation_mln;
 const skipped=applyDerivedInputs(derived);
 if(skipped)lines.push(skipped);
 if(Number(inputs.underground_manual_spaces||0)>0)inputs.underground_manual_spaces=d.underground_manual_spaces;
 stampSocialBasis(basis.source||'пропорция');
 syncTep(false);renderInputs();renderTep();
 say((silent?'Пересчитано пропорцией: ':'Подставлено: ')+lines.map(escapeHtml).join('<br>')
   +'<br><b>Чем посчитано:</b> '+(d.basis||[]).map(escapeHtml).join('; ')+'.',true);
 calculate();
 return true;
}

// Тела запросов пересчёта — по одному на маршрут. Их читают и кнопка
// пересчёта ТЭП, и переключатель населения для соцобъектов: собранное в двух
// местах тело однажды разошлось бы полем.
function bySiteBody(){
 const territory=((cadastralAnalysis||{}).territory)||{};
 return {apartment_area_sqm:Number((tep.apartments&&tep.apartments.saleable)||0),
  residential_living_spp_sqm:Number((tep.apartments&&tep.apartments.gns)||0),
  nonresidential_np_sqm:nonresidentialAboveSqm(),
  apartment_count:Number((tep.apartments&&tep.apartments.units)||0),
  social_population_method:String(inputs.social_population_method||'rngp_area'),
  district:String(territory.district||''),
  inside_moscow:territory.inside_moscow!==false};
}
function baselineRecalcBody(){
 // Нежилая наземная — встроенные помещения плюс отдельные объекты: приобъектные
 // места считаются от неё, а МПТ от неё же дают льготу по плате за ВРИ.
 return {baseline:((inputs._glavapu_import||{}).normalized)||null,areas:{
  apartment_area_sqm:Number((tep.apartments&&tep.apartments.saleable)||0),
  residential_living_spp_sqm:Number((tep.apartments&&tep.apartments.gns)||0),
  apartment_count:Number((tep.apartments&&tep.apartments.units)||0),
  ground_commercial_spp_sqm:Number((tep.ground_commercial&&tep.ground_commercial.gns)||0),
  nonresidential_np_sqm:nonresidentialAboveSqm(),
  land_right:String(inputs.land_right||'ownership'),
  social_population_method:String(inputs.social_population_method||'rngp_area'),
  nonres_spp_by_use:{
   office:standaloneProductSum('gns',['offices']),
   trade:standaloneProductSum('gns',['standalone_retail'])}}};
}

async function recalcFromTepByNorms(options){
 const silent=!!(options&&options.silent);
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!apartments){
  if(!silent)say('Пересчитывать не от чего: в ТЭП нет продаваемой площади квартир.',false);
  return;
 }
 let d;
 try{
  const r=await fetch('/tep/derived-by-site',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(bySiteBody())});
  d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Пересчёт не выполнен');
 }catch(e){say('Пересчёт по нормативам не выполнен: '+escapeHtml(String(e.message||e)),false);return}

 const lines=[
  'Население: '+num(d.population)+' чел. · квартир '+num(d.apartment_units),
  'ДОО '+num(d.places.kindergarten)+' · школа '+num(d.places.school)
   +' · поликлиника '+num(d.places.clinic)+' пос./смену',
  'Машино-места подземные: '+num(d.parking.underground)
   +' ('+num(d.parking.permanent)+' постоянных + '+num(d.parking.guest)+' гостевых)',
  'Места приложения труда: '+num(d.jobs)];
 // Население соцобъектов по требованию органа — своей строкой: оно не равно
 // населению нормы, и места выше посчитаны от него.
 if(d.social_population!=null&&d.social_population!==d.population)
  lines.splice(1,0,'Население для соцобъектов: '+num(d.social_population)+' чел. — '+String(d.social_population_basis||''));
 (d.refused||[]).forEach(x=>lines.push('Не посчитано — '+x.name+': '+x.reason));
 (d.warnings||[]).forEach(w=>lines.push('⚠ '+w));
 if(!silent&&!confirm('Пересчёт по нормативам Москвы (выгрузки ГлавАПУ нет):\n\n'
   +lines.join('\n')+'\n\nПодставить в модель?'))
  {say(lines.map(escapeHtml).join('<br>'),true);return}
 const skipped=applyDerivedInputs({kindergarten_places:d.places.kindergarten,
  school_places:d.places.school,clinic_capacity:d.places.clinic});
 if(skipped)lines.push(skipped);
 setUndergroundFromMethod(d.parking.permanent,d.parking.guest,d.parking.underground);
 stampSocialBasis('нормативы Москвы');
 syncTep(false);renderInputs();renderTep();
 say((silent?'Пересчитано под новый ТЭП: ':'Подставлено: ')+lines.map(escapeHtml).join('<br>')
   +'<br><b>Чем посчитано:</b> '+(d.basis||[]).map(escapeHtml).join('; ')+'. '
   +'Это наш расчёт по нормативам, а не расчёт города: город считает штатным '
   +'калькулятором, и его выгрузка сильнее.',true);
 calculate();
}

// Переключатель «Население для соцобъектов» меняет только места ДОО, школы,
// поликлиники и компенсацию за них — машино-места, плата за ВРИ и население
// нормы от него не зависят, и пересчёт ТЭП целиком здесь был бы чужой
// правкой. Пропорция от прежней соцнагрузки переключатель не видит вовсе:
// она масштабирует метры, а метры не менялись. Поэтому дорога своя: с
// выгрузкой ГлавАПУ — ставки выгрузки, без неё — нормативы Москвы.
// Итог или причина отказа пишутся ПОД переключателем: заметка на вкладке ТЭП
// с вводных не видна, и «ничего не меняется» (владелец, 19.10.2026) было
// неотличимо от молчаливого отказа. Места, вписанные руками или требованием
// КРТ, переключатель не трогает и говорит об этом (решение владельца,
// 19.10.2026); места из выгрузки ГлавАПУ пересчитывает.
let socialPopulationNoteText='';
function sayPopulationSwitch(text){
 socialPopulationNoteText=String(text||'');
 const node=document.getElementById('socialPopulationNote');
 if(node)vriNoteFill(node,socialPopulationNoteText);
}
const SOCIAL_SWITCH_FIELDS=[['kindergarten_places','места ДОО'],['school_places','места в школе'],
 ['clinic_capacity','мощность поликлиники'],['social_compensation_mln','компенсация, млн ₽']];
async function socialPopulationSwitched(methodBefore){
 if(classRegion()==='mo')
  return sayPopulationSwitch('В Подмосковье этот переключатель не действует: соцобъекты там считаются по нормативам области.');
 if(classRegion()==='other')
  return sayPopulationSwitch('Этот переключатель здесь не действует: участок не в Москве и не в Московской области, норм соцобъектов его региона у нас нет, и места стоят нашими умолчаниями — поправьте их сами.');
 if(krtRequirementEntered())
  return sayPopulationSwitch('Места соцобъектов и компенсация вписаны вручную, поэтому переключатель их не меняет. Чтобы считать их от числа жителей, выберите в поле «Как задаются соцобъекты» вариант «По нормативу».');
 if(!Number((tep.apartments&&tep.apartments.saleable)||0))
  return sayPopulationSwitch('Места соцобъектов не пересчитаны: в ТЭП не задана продаваемая площадь квартир, а число жителей считается от неё.');
 sayPopulationSwitch('Пересчитываю места соцобъектов под выбранный способ…');
 const viaBaseline=glavapuBaselineApplies();
 let d;
 try{
  const r=await fetch(viaBaseline?'/tep/recalc-from-baseline':'/tep/derived-by-site',
   {method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(viaBaseline?baselineRecalcBody():bySiteBody())});
  d=await r.json();
  if(!r.ok)throw new Error(d.detail||('сервер ответил '+r.status));
 }catch(e){
  return sayPopulationSwitch('Места соцобъектов не пересчитаны: '+String(e.message||e)+'.');
 }
 // Переключатель меняет только жителей и места соцобъектов — и сверку с
 // выгрузкой читает только по ним (`social_matches_baseline`). Машино-места
 // он не трогает, и их расхождение не повод отказывать в пересчёте мест ДОО.
 const socialCheck=(d.self_check&&d.self_check.mismatch_by_scope||{}).social||[];
 if(viaBaseline&&d.self_check&&d.self_check.social_matches_baseline===false)
  return sayPopulationSwitch('Места соцобъектов не пересчитаны: в выгрузке ГлавАПУ число жителей и места '
   +'детского сада, школы или поликлиники не сходятся с нормативом Москвы ('+socialCheck.join('; ')
   +'). Если пересчитать их по-своему, мы разойдёмся с городом, не зная почему. '
   +'Загрузите выгрузку ГлавАПУ заново или впишите нужные места в поля ниже вручную.');
 const offer={kindergarten_places:d.places.kindergarten,school_places:d.places.school,
  clinic_capacity:d.places.clinic};
 let compensationBasis='';
 const compensationWas=Number(inputs.social_compensation_mln||0);
 if(viaBaseline){
  if(d.compensation_mln>0){offer.social_compensation_mln=d.compensation_mln;
   compensationBasis='компенсация — по ставкам за место из выгрузки ГлавАПУ'}
 }else if(compensationWas>0){
  // Ставки за место у нормативного пути нет: компенсация вписана экспертно или
  // пришла с выгрузкой. Места линейны по числу жителей — компенсация идёт за
  // ними в той же пропорции, ставка за место остаётся прежней.
  const byMethod=d.social_population_by_method||{};
  const was=Number(byMethod[String(methodBefore||'rngp_area')]||0);
  const now=Number(d.social_population||0);
  if(was>0&&now>0&&was!==now){
   offer.social_compensation_mln=Math.round(compensationWas*now/was*1000)/1000;
   compensationBasis='компенсация — в той же пропорции, что число жителей ('+num(was)+' → '+num(now)+'), ставка за место прежняя';
  }
 }
 const before={};SOCIAL_SWITCH_FIELDS.forEach(([key])=>{before[key]=Number(inputs[key]||0)});
 const kept=SOCIAL_SWITCH_FIELDS.filter(([key])=>(key in offer)&&isFieldManual('inputs.'+key)).map(([,label])=>label);
 applyDerivedInputs(offer,{keepManual:[]});
 const moved=[],same=[];
 SOCIAL_SWITCH_FIELDS.forEach(([key,label])=>{
  if(!(key in offer)||kept.includes(label))return;
  const now=Number(inputs[key]||0);
  if(Math.abs(now-before[key])<0.0005)same.push(label+' '+num(now));
  else moved.push(label+' '+num(before[key])+' → '+num(now));
 });
 const parts=['Жителей для соцобъектов: '+num(d.social_population)+' — '+String(d.social_population_basis||'')+'.'];
 if(moved.length)parts.push('Пересчитано: '+moved.join(', ')+'.');
 if(same.length)parts.push('Не изменились — при этом числе жителей норматив даёт столько же: '+same.join(', ')+'.');
 if(kept.length)parts.push('Вписаны вручную, переключатель их не меняет: '+kept.join(', ')+'. Чтобы считать их от жителей, очистите поле и нажмите пересчёт ТЭП.');
 if(compensationWas>0&&!('social_compensation_mln' in offer))
  parts.push('Компенсация не пересчитана: '+(viaBaseline?'выгрузка ГлавАПУ не дала ставок за место.':'число жителей при этом способе то же.'));
 if(compensationBasis)parts.push('Чем посчитано: '+compensationBasis+'.');
 stampSocialBasis(viaBaseline?'выгрузка ГлавАПУ':'нормативы Москвы');
 socialPopulationNoteText=parts.join(' ');
 syncTep(false);renderInputs();renderTep();
 calculate();
}

// Метод (норматив по ТЭП или сценарий ГлавАПУ) знает не только места, но и
// сколько из них гостевых. Пара мест при этом может быть ручной — и тогда
// движок выводил гостевые как места/11, а не брал число метода: на 341 месте
// 34 вместо 35, и одно гостевое уходило в продажу. Решение владельца
// (16.10.2026): гостевые — из метода. Число едет рядом с местами, для которых
// метод его дал; поменяли места руками — оно больше не их, и движок снова
// считает места/11 (`underground_tep_row`).
function setUndergroundFromMethod(permanent,guest,spaces){
 const total=Number(spaces!=null?spaces:Number(permanent||0)+Number(guest||0));
 inputs.underground_manual_spaces=total;
 const g=Number(guest);
 if(total>0&&Number.isFinite(g)&&g>=0&&g<=total)inputs._underground_method_guest={spaces:total,guest:g};
 else delete inputs._underground_method_guest;
}

async function recalcFromTep(options){
 const silent=!!(options&&options.silent);
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 // Другой регион: норм у нас нет, а числа соцобъектов и машино-мест вписал
 // человек — ни нормой, ни пропорцией их не переписываем.
 if(classRegion()==='other'){say(escapeHtml(OTHER_REGION_TEP_NOTE),false);return}
 // Подмосковье — нормативами области, тем же пересчётом, что идёт сам после
 // правки квартир. Московские нормативы сервер к области не применяет.
 if(tepNormsMode().key==='mo'){
  const area=Number(inputs.site_area_ha||0);
  const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
  if(!(area>0&&apartments>0)){
   say('Пересчитывать не от чего: нужны площадь участка и продаваемая площадь квартир.',false);return}
  return recalcMoFromApartments(apartments,area);
 }
 if(!glavapuBaselineApplies()){
  // Без выгрузки ГлавАПУ пересчёт не отказывается целиком. Сначала пропорция:
  // если соцнагрузка в модели уже есть, места и компенсация масштабируются по
  // населению — норматив тут не применяется вовсе, и это работает в любом
  // регионе. Не от чего масштабировать — считаем по нормативам Москвы.
  if(await rescaleSocialFromTep(options))return;
  return recalcFromTepByNorms(options);
 }
 if(!silent)say('Пересчитываю по параметрам исходного расчёта…',false);
 let d;
 try{
  const r=await fetch('/tep/recalc-from-baseline',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(baselineRecalcBody())});
  d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Пересчёт не выполнен');
 }catch(e){say('Пересчёт не выполнен: '+escapeHtml(String(e.message||e)),false);return}
 // Метод обязан воспроизводить исходный расчёт на исходных метрах. Не
 // воспроизводит — это расхождение с базой, а не результат.
 if(d.self_check&&d.self_check.matches_baseline===false){
  say('Пересчёт не сходится с исходным расчётом ГлавАПУ: '
     +escapeHtml((d.self_check.mismatch||[]).join('; '))
     +'. Показывать такое как расчёт нельзя — нужна свежая выгрузка.',false);
  return;
 }
 const b=d.baseline||{};
 // «Было» — это ВЫГРУЗКА ГлавАПУ, а не состояние до правки: ставки сняты с
 // неё, и сравнение идёт с ней. Пока строка говорила просто «было», каждая
 // правка ТЭП показывала весь дрейф с момента импорта как её следствие —
 // «с чего вдруг поменялось население тоже не ясно» (владелец, 26.09.2026):
 // доля офисов население не двигает вовсе, оно считается от площади квартир.
 // Не изменившееся не печатается стрелкой: строка со стрелкой читается как
 // следствие правки, даже когда числа по обе стороны одинаковы.
 const cmp=(name,was,now)=>Math.abs(Number(was||0)-Number(now||0))<0.5
  ? name+': '+num(now)+' — как в выгрузке ГлавАПУ'
  : name+': в выгрузке ГлавАПУ '+num(was)+' → на нынешнем ТЭП '+num(now);
 // Половины разные, и смешивать их нельзя. Машино-места и население — это
 // КОНТЕКСТ: полями они не становятся, и сравнивать их можно только с
 // выгрузкой. Плата за ВРИ, соцкомпенсация и места соцобъектов — ПОДСТАНОВКА,
 // и про них честно говорить только после того, как она случилась.
 const context=[
  cmp('Машино-места',b.parking_total,d.parking.total)
   +' ('+d.parking.permanent+' постоянных + '+d.parking.guest+' гостевых + '
   +d.parking.attached+' приобъектных)',
  // Числа метода по соцобъектам стояли хвостом этой строки — и противоречили
  // строкам о самих полях: в хвосте «ДОО 412», а поле заперто на 350. Своим
  // местам они уже сказаны, а второй ответ на тот же вопрос разошёлся бы с
  // первым молча.
  cmp('Население, чел.',b.population,d.population)];
 if(d.social_population!=null&&d.social_population!==d.population)
  context.push('Население для соцобъектов: '+num(d.social_population)+' чел. — '+String(d.social_population_basis||''));
 (d.warnings||[]).forEach(w=>context.push('⚠ '+w));
 // Вопрос задаётся о НАМЕРЕНИИ: здесь подстановки ещё не было.
 const proposal=['Плата за ВРИ, млн ₽: по ставке территории '+num(d.vri_total_mln)
   +(d.land_right_factor&&d.land_right_factor!==1?' (аренда: делитель 1,001)':''),
  'Соцкомпенсация, млн ₽: по ставке территории '+num(d.compensation_mln)].concat(context);
 // Спрашивать на каждой правке ТЭП нечего: человек уже сказал, чего хочет,
 // изменив метры. Подтверждение осталось у явного нажатия кнопки.
 if(!silent&&!confirm('Пересчёт по параметрам исходного расчёта ГлавАПУ:\n\n'+proposal.join('\n')
   +'\n\nПодставить в модель?'))
  {say(proposal.map(escapeHtml).join('<br>'),true);return}
 const derived={kindergarten_places:d.places.kindergarten,school_places:d.places.school,
  clinic_capacity:d.places.clinic};
 if(d.compensation_mln>0)derived.social_compensation_mln=d.compensation_mln;
 if(d.vri_total_mln>0)derived.land_rights_cost_mln=d.vri_total_mln;
 applyDerivedInputs(derived);
 // Отчёт строится ПОСЛЕ подстановки и читает поля: приписка «не тронуто»
 // здесь больше не нужна — каждая строка сама говорит, что в поле стоит и
 // почему. Признак «предлагалось ли число» берётся у того же `derived`,
 // который ушёл в подстановку, а не у второго условия рядом.
 const lines=[['Плата за ВРИ, млн ₽','land_rights_cost_mln',d.vri_total_mln],
  ['Соцкомпенсация, млн ₽','social_compensation_mln',d.compensation_mln],
  ['Места ДОО','kindergarten_places',d.places.kindergarten],
  ['Места СОШ','school_places',d.places.school],
  ['Мощность поликлиники','clinic_capacity',d.places.clinic]]
  .map(x=>derivedLine(x[0],x[1],x[2],Object.prototype.hasOwnProperty.call(derived,x[1])))
  .concat(context);
 const parkingWas=Number((tep.underground_parking&&tep.underground_parking.units)||0);
 // В подземный гараж идут постоянные и гостевые. Приобъектные — места у входа
 // для посетителей встроенной коммерции, под землю их не кладут: с ними гараж
 // выходил больше нормы, и лишние места ехали в себестоимость.
 setUndergroundFromMethod(d.parking.permanent,d.parking.guest);
 stampSocialBasis('выгрузка ГлавАПУ');
 syncTep(false);renderInputs();renderTep();
 const parkingNow=Number((tep.underground_parking&&tep.underground_parking.units)||0);
 lines.push(parkingNow===parkingWas
  ? 'Машино-места в ТЭП: '+parkingNow+' — не изменились'
  : 'Машино-места в ТЭП: было '+parkingWas+', стало '+parkingNow);
 // Заголовок отвечает за весь список и обязан быть верен о нём. «Подставлено»
 // над списком, в котором не подставлено ничего, — то же враньё, что и строка
 // о подстановке, которой не было, только крупнее.
 const wrote=Object.keys(derived).some(key=>!krtLocks(key))||parkingNow!==parkingWas;
 const head=wrote?(silent?'Пересчитано под новый ТЭП: ':'Подставлено: ')
  :'Подставлять нечего: соцобъекты вписаны вручную, а машино-места не изменились. ';
 say(head+lines.map(escapeHtml).join('<br>')
   +'<br>Ставки территории взяты из исходного расчёта ГлавАПУ и применены к новым метрам. '
   +'Проверено обратным ходом: на исходном ТЭП метод воспроизводит его числа.',true);
 calculate();
}

function syncTep(rerender=true){
 // Тип проекта — признак, а не разовое действие переключателя: жильё убирает
 // ТОТ ЖЕ пересчёт, через который проходит всякий писатель ТЭП — импорт
 // ГлавАПУ, расчёт от плотности, мост КРТ, загрузка проекта. Прежде оно
 // возвращалось молча, а на экране строки заперты и полей нет: убрать
 // вернувшееся человек не мог.
 if(withoutHousing())clearResidentialInputs();
 // Соцобъекты строятся и в совмещённом режиме — иначе ДОУ и школа исчезают
 // из ТЭП при выбранном «Строительство и компенсация», хотя они в проекте.
 const socialBuild=inputs.social_mode==='Строительство'
   ||inputs.social_mode==='Строительство и компенсация';
 // Пропорция может дописать вводные (известна продаваемая — считается ГНС).
 // Тогда поле обязано показать своё число, а не остаться пустым.
 let inputsFilled=false;
 // Пара «места ↔ площадь» идёт за ТЭП, пока её не тронули руками: правка
 // квартир меняет норму, и число в поле обязано меняться вместе с ней.
 // Раньше пересчёт звался только при импорте ГлавАПУ и при загрузке проекта,
 // то есть ровно один раз, — и дальше поле замирало.
 if(fillUndergroundFromTep())inputsFilled=true;
 if(inputs.underground_parking_disabled||Number(inputs.underground_manual_spaces||0)>0||Number(inputs.underground_manual_gns_sqm||0)>0){repairParkingFromGlavapu()}else{tep.underground_parking.gns=Number(tep.underground_parking.units||0)*undergroundAreaPerSpace()}tep.underground_parking.total_area=tep.underground_parking.gns;
 // Строки отдельно стоящих объектов — обходом реестра. Перечисленные здесь
 // поимённо, они не знали второго офисника: его метры считались движком и не
 // появлялись ни в строке ТЭП, ни в ГНС проекта.
 //
 // ФОК строится в любом случае — деньги на него тратятся и при передаче
 // городу, — а продаётся только по признаку. Переданные метры уходят в
 // «передаётся»: они строятся, но не продаются, как у соцобъекта. Половиной
 // объект не делится: «всё или так, или так» (владелец, 05.09.2026).
 STANDALONE_OBJECTS.forEach(o=>{
  const row=tep[o.key];if(!row)return;
  const p=o.prefix,flag=p+'_enabled';
  if(o.measure==='spaces'){
   row.units=inputs[flag]?Number(inputs[p+'_spaces']||0):0;
   row.gns=row.units*Number(inputs[p+'_area_per_space_sqm']||25);row.total_area=row.gns;
   return;
  }
  const gbaId=p+'_gba_sqm',saleId=p+'_saleable_sqm';
  if(!inputs[flag]){row.gns=0;row.total_area=0;row.saleable=0;row.useful=0;
   if(o.sale_gate)row.transfer=0;return}
  const sold=!o.sale_gate||String(inputs[o.sale_gate]||'transfer')==='sale';
  const key=o.key;
  const filled=tepFillByRatios(key,{gns:Number(inputs[gbaId]||0),total_area:0,
   saleable:sold?Number(inputs[saleId]||0):0,useful:0});
  row.gns=filled.gns;row.total_area=filled.total_area;
  if(o.sale_gate){
   row.saleable=sold?filled.saleable:0;row.useful=row.saleable;
   row.transfer=sold?0:row.total_area;
  }else{
   row.saleable=filled.saleable;row.useful=filled.useful;
   // Известна только продаваемая — ГНС считается и возвращается во вводные:
   // себестоимость объекта берётся оттуда, и с нулём она была бы нулевой при
   // живой выручке. Число видно в поле, а не подставлено втихую.
   if(!Number(inputs[gbaId]||0)&&filled.gns>0){inputs[gbaId]=filled.gns;inputsFilled=true}
  }
  if(sold&&!Number(inputs[saleId]||0)&&filled.saleable>0){inputs[saleId]=filled.saleable;inputsFilled=true}
 });
 // Соцобъект: места, площадь и ГНС. Прежде строка получала только общую
 // площадь и места, а `gns` не трогалась вовсе — поля «ГНС ДОУ» во вводных нет.
 // Импорт ГлавАПУ при этом писал в неё СПП из выгрузки, и один и тот же садик
 // давал разный ГНС проекта в зависимости от того, как он в проект попал
 // (владелец, 02.09.2026). ГНС считается, а статьи «на м² ГНС» её не берут:
 // их база — ядро МКД (`core_total_gns` в движке), и соцобъект туда не входит.
 [['kindergarten','social_dou_gba_sqm','social_dou_norm_sqm','kindergarten_places'],
  ['school','social_school_gba_sqm','social_school_norm_sqm','school_places'],
  ['clinic','social_clinic_gba_sqm','social_clinic_norm_sqm','clinic_capacity']]
 .forEach(([row,areaId,normId,unitsId])=>{
  const units=socialBuild?Number(inputs[unitsId]||0):0;
  // Норматив площади — ступень по ёмкости здания, а не одно число: маленький
  // садик стоит 27 м² на место, крупный 16 (2151-ПП, редакция 2579-ПП). Считается
  // от КОЛИЧЕСТВА МЕСТ (решение владельца, 02.09.2026), поэтому поле следует
  // за мощностью, а не живёт своей жизнью. У поликлиники ступени нет: норма
  // города — верхний предел (2150-ПП, разд. 1.4), и он живёт умолчанием поля.
  // Требование договора КРТ сильнее норматива: город даёт места И площадь, и
  // они с нормативом не совпадают (владелец, 03.09.2026: «в крт уже прописаны
  // требования к сош доо и поликлинике по местам и площади, и они не
  // совпадают с нормативными»). Прежде вписанное затиралось при каждой
  // синхронизации — «меняешь места в Экономике, он пересчитывает площадь, в
  // тэпах меняешь вручную площадь, он опять возвращает». Приоритет по полю:
  // руками > документ лота КРТ > выгрузка ГлавАПУ > норматив.
  const byHand=String(inputs.social_area_source||'norm')==='manual';
  const cityNorm=byHand?0:socialAreaPerPlace(row,units);
  if(cityNorm&&Number(inputs[normId]||0)!==cityNorm){inputs[normId]=cityNorm;inputsFilled=true}
  // Требование КРТ задаёт площадь, а не норматив — и поле норматива в этом
  // режиме показывает ФАКТИЧЕСКИЙ показатель (решение владельца, 03.09.2026:
  // «показывать фактически»), а не то число, которое стояло тут до вписанного
  // требования. Норматив города при этом называется рядом: 22,2 м²/место по
  // договору и 15 по 2151-ПП — разные ответы, и второй не отменяет первого.
  let area=socialBuild?Number(inputs[areaId]||0):0;
  // Места ввели руками, площадь — нет: считаем её нормативом на место. Прежде
  // это делал только импорт ГлавАПУ и только в режиме «Строительство», а при
  // ручном вводе метры объекта не появлялись нигде.
  const imported=glavapuSocialSpp(row);
  const importedNp=glavapuSocialNp(row);
  // Вписанную руками площадь не трогаем вовсе: ноль в поле при ручном режиме
  // значит «объекта нет», а не «посчитай за меня».
  if(!byHand&&socialBuild&&units>0&&Number(inputs[normId]||0)>0
     &&(area<=0||(cityNorm&&!importedNp))){
   // Выгрузка города приносит СВОЮ площадь объекта — она сильнее норматива.
   // Своей нет — считаем от мест: площадь, оставшаяся от прежней мощности,
   // читается как посчитанная и молча завышает или занижает ТЭП.
   area=units*Number(inputs[normId]||0);
   inputs[areaId]=area;inputsFilled=true;
  }
  if(byHand){
   const fact=units>0&&area>0?Math.round(area/units*100)/100:0;
   if(Number(inputs[normId]||0)!==fact){inputs[normId]=fact;inputsFilled=true}
  }
  tep[row].total_area=area;
  tep[row].transfer=area;
  tep[row].units=units;
  // Выгрузка приносит настоящую СПП объекта — её не трогаем. Своей нет:
  // считаем по той же пропорции НП/СПП, что и остальной ТЭП.
  // Пропорция общей к ГНС уже объявлена в движке и подставлена на страницу —
  // второй копии числа здесь нет.
  const share=socialTotalShare();
  tep[row].gns=area>0?(imported>0?imported:area/share):0;
 });
 // ГлавАПУ has priority over any old/stale underground-parking TEP values.
 repairParkingFromGlavapu();
 // Без перерисовки обновлялась только строка итогов, а ячейки продуктов
 // оставались с прежними числами: правка машино-мест на «Вводных» доходила до
 // таблицы ТЭП лишь со следующим полным рендером — то есть после расчёта. Не
 // перерисовывать нужно ровно в одном случае: когда человек печатает в самой
 // таблице и потеряет фокус. Тогда и не перерисовываем, в остальных — сразу.
 const editingTep=typeof tepBody!=='undefined'&&tepBody
  &&tepBody.contains(document.activeElement);
 if(rerender||!editingTep)renderTep();else updateTepTotals();
 // Пара полей подземного паркинга и подпись под ней идут за ТЭП здесь же:
 // норма посчитана страницей, ждать ответа сервера ей незачем, а поле со
 // старым числом под новой строкой ТЭП читалось бы как решение человека.
 if(inputsFilled){
  ['underground_manual_spaces','underground_manual_gns_sqm'].forEach(id=>{
   const el=document.getElementById('f_'+id);
   if(el&&document.activeElement!==el)el.value=inputs[id];
  });
 }
 renderUndergroundFieldNote();
 // Включённый или выключенный объект меняет состав очередей сразу, а не со
 // следующим ответом движка (`renderPhaseObjects`).
 if(typeof renderPhaseObjects==='function')renderPhaseObjects();
 return inputsFilled;
}
"""
