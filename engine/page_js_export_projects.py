"""Кусок страницы PAGE: Скрипт: экспорт PDF/архива, локальное сохранение, пресеты,
проекты (вход, сохранение, общий доступ, файлы настроек), сброс.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_export_projects")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""function currentPdfReportPayload(cads=[]){
 const glavapuMeta=inputs._glavapu_import||null;
 const manualMeta=inputs._manual_tep_import||null;
 const source=(glavapuMeta&&glavapuMeta.source)||(manualMeta&&manualMeta.source)||{};
 return {result:lastResult,inputs:inputs,tep:tep,rates:rates,phasing:phasing,scenario:scenarioSelect.value||'base',cadastral_numbers:cads.length?cads:((cadastralAnalysis&&cadastralAnalysis.recognized)||source.cadastral_numbers||[]),project_name:(manualMeta&&manualMeta.project_name)||'',source_label:tepSourceLabel(!!manualMeta),
   // Чувствительность попадает в отчёт только если её считали: гнать полсотни
   // расчётов внутри сборки PDF ради раздела, который никто не просил, незачем.
   sensitivity:sensitivityReport};
}

async function exportReportPdf(){
 // Полный PDF проверяет ограничения у каждого участка проекта; на площадке
 // из двадцати участков это минуты НСПД, и сервер отвечает 202 с билетом —
 // PDF забирается опросом, как у тизера, а кнопка называет стадию.
 await calculate();
 const button=document.querySelector('[onclick="exportReportPdf()"]');
 const label=button?button.textContent:'';
 const show=text=>{if(button){button.disabled=!!text;button.textContent=text||label}};
 try{
  let response=await fetch('/report/pdf',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(Object.assign({session:activeSession(),access_key:projectsAdminKey||''},currentPdfReportPayload()))});
  const deadline=Date.now()+TEASER_POLL_LIMIT_MS;
  while(response.status===202){
   let state={};try{state=await response.json()}catch(e){}
   if(!state.ticket)break;
   show(state.detail||'PDF-отчёт готовится…');
   if(Date.now()>deadline){alert('PDF-отчёт всё ещё готовится ('+(state.detail||'')+'). Нажмите «Экспорт PDF» позже.');return;}
   await new Promise(done=>setTimeout(done,TEASER_POLL_MS));
   response=await fetch('/report/pdf/'+encodeURIComponent(state.ticket));
  }
  if(!response.ok||response.status!==200){let detail='Не удалось сформировать PDF';try{const x=await response.json();detail=x.detail||detail}catch(e){}alert(detail);return;}
  const blob=await response.blob();
  downloadBlobResponse(blob,response.headers.get('Content-Disposition')||'',`DevelopAid_Отчет_${new Date().toISOString().slice(0,10)}.pdf`);
 }finally{show('')}
}

async function exportTeaserPdf(){
 // Тизер считает сервер тем же расчётом, что PDF и книгу: страница только
 // шлёт вводные. Ответ разбирается с оглядкой на то, что он может быть не PDF.
 // На холодных кэшах сервер собирает тизер минутами и отвечает 202 с билетом
 // и стадией: PDF забирается опросом, кнопка называет, что сейчас идёт.
 await calculate();
 const button=document.querySelector('[onclick="exportTeaserPdf()"]');
 const label=button?button.textContent:'';
 const show=text=>{if(button){button.disabled=!!text;button.textContent=text||label}};
 try{
  let response=await fetch('/report/teaser',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(Object.assign({session:activeSession(),access_key:projectsAdminKey||''},currentPdfReportPayload()))});
  const deadline=Date.now()+TEASER_POLL_LIMIT_MS;
  while(response.status===202){
   let state={};try{state=await response.json()}catch(e){}
   if(!state.ticket)break;
   show(state.detail||'Тизер готовится…');
   if(Date.now()>deadline){alert('Тизер всё ещё готовится ('+(state.detail||'')+'). Нажмите «Скачать тизер» позже.');return;}
   await new Promise(done=>setTimeout(done,TEASER_POLL_MS));
   response=await fetch('/report/teaser/'+encodeURIComponent(state.ticket));
  }
  if(!response.ok||response.status!==200){let detail='Не удалось сформировать тизер';try{const x=await response.json();detail=x.detail||detail}catch(e){}alert(detail);return;}
  const blob=await response.blob();
  downloadBlobResponse(blob,response.headers.get('Content-Disposition')||'','DevelopAid_Тизер.pdf');
 }finally{show('')}
}
const TEASER_POLL_MS=3000;
const TEASER_POLL_LIMIT_MS=25*60*1000;

function downloadBlobResponse(blob,disposition,fallback){
 const utf=String(disposition||'').match(/filename\*=UTF-8''([^;]+)/i);
 const filename=utf?decodeURIComponent(utf[1]):fallback;
 const url=URL.createObjectURL(blob);
 const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1500);
}

async function exportModelArchive(){
 // Одна модель на выгрузку: книга DevelopAid v4, считающая проект формулами
 // из текущих вводных. Прежние выгрузки — архив очередей с консолидатором и
 // заполненный шаблон ПЛАТО — сняты вместе с маршрутами: они остались от
 // времени, когда очереди собирались отдельными файлами, и две выгрузки
 // рядом читались как разные модели одного проекта.
 const button=document.getElementById('exportModelButton');
 const label=button?button.textContent:'';
 if(button){button.disabled=true;button.textContent='Собираю модель…'}
 try{
  await calculate();
  const manualMeta=inputs._manual_tep_import||null;
  const response=await fetch('/report/workbook',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({
    inputs,tep,rates,
    phasing:(typeof phasing!=='undefined'?phasing:{}),
    project_name:(manualMeta&&manualMeta.project_name)||'',
    scenario:scenarioSelect.value||'base'
   })
  });
  if(!response.ok){
   let detail='Не удалось собрать модель';
   try{const x=await response.json();detail=x.detail||detail}catch(e){}
   alert(detail);return;
  }
  downloadBlobResponse(
   await response.blob(),
   response.headers.get('Content-Disposition'),
   `DevelopAid_модель_${new Date().toISOString().slice(0,10)}.xlsx`
  );
 }finally{
  if(button){button.disabled=false;button.textContent=label||'Скачать модель (Excel)'}
 }
}

// Кнопки «Сохранить» нет: каждый пересчёт и так пишет состояние в localStorage
// этого браузера — ручная копия того же самого создавала ложное ощущение
// надёжного сохранения (владелец, 16.08.2026). Настоящее сохранение, которое
// переживает смену устройства, — «Личный кабинет».
function persistLocalSilently(){localStorage.setItem('plato_v04',JSON.stringify({inputs,tep:persistedTep(tep),phasing,scenario:scenarioSelect.value}))}
function loadLocal(){try{const x=JSON.parse(localStorage.getItem('plato_v04'));if(x){
 // Сохранённое состояние накладывается на умолчания, а не подменяет их целиком.
 // Иначе поле, добавленное после сохранения, в браузере просто отсутствует:
 // список показывает пустую строку, а число при пересчёте становится нулём —
 // так «Периодичность платежей» ВРИ оказалась 0 при расчёте по квартальной.
 inputs=Object.assign(cloneValue(INPUT_DEFAULT),x.inputs||{});
 seedParkingByHand();adoptObjectRateKind();restoreKrtClearedVriFee();
 tep=cloneValue(TEP_DEFAULT);
 Object.entries(x.tep||{}).forEach(([key,values])=>{
  if(values&&typeof values==='object')tep[key]=Object.assign(tep[key]||{},values);
 });
 rememberDerivedTail(x.tep,true);
 phasing=x.phasing||phasing;rates=[];scenarioSelect.value=x.scenario||'base';
 // v0.12.25: old browser state could silently carry a three-phase project
 // into a newly imported small site. Only an explicit user choice or the
 // Mytishchi preset may restore phasing after this migration.
 const mytishchiPreset=inputs._preset_expert_overrides&&inputs._preset_expert_overrides.preset_id==='mytishchi';
 if(phasing.user_enabled!==true&&!mytishchiPreset)phasing=makeDefaultPhasing(1);
 // v0.7.1 migration: v0.7.0 temporarily misclassified the old 5% management rate as technical supervision.
 // Примета состояния v0.7.0 — нет поля управления проектом: там 5 % стояли
 // под технадзором. Нет версии у ЛЮБОГО проекта, сохранённого без неё, — и
 // миграция молча ставила технадзор 0 новому проекту при первой же
 // перезагрузке: CAPEX −1 млрд, LLCR «сам» рос (аудит регрессов, 29.09.2026).
 // Решает сохранённое, а не наложенное на умолчания.
 const savedInputs=x.inputs||{};
 if(savedInputs._cost_structure_version!=='0.7.1'){
   if(savedInputs.project_management_pct==null){
    inputs.project_management_pct=Number(savedInputs.technical_supervision_pct??5);
    // Source model had no separate technical-supervision input: reset migrated value to 0.
    inputs.technical_supervision_pct=0;
   }
   inputs._cost_structure_version='0.7.1';
 }
 if(inputs.author_supervision_pct==null)inputs.author_supervision_pct=0;
 delete inputs.author_supervision_mln;
 // Проект, сохранённый до этой версии, несёт нули в паре «места ↔ площадь»:
 // нуль означал «взять норматив ГлавАПУ», а поля должны показывать расчёт
 // участка, который человек и правит.
 fillUndergroundFromTep();
}}catch(e){
 // Молчаливый catch здесь стоил бы весь сохранённый проект: любая ошибка
 // внутри восстановления сбрасывала человека на умолчания и не говорила
 // ничего — на экране это «проект пропал». Ровно так же однажды молчала
 // рекурсия в `cloneValue`. Причина называется вслух; восстановиться из
 // сломанного состояния всё равно нельзя, поэтому дальше страница идёт на
 // умолчаниях — но человек знает, почему.
 try{
  if(typeof pageFailureBox==='function')pageFailureBox().textContent=
   'Сохранённый проект не восстановился — страница открыта на умолчаниях.\n'
   +String((e&&e.message)||e)+'\nПришлите этот текст.';
 }catch(_){}
}}

// --- импорт пресета проекта ---------------------------------------------------
// Пресет заполняет проект целиком, поэтому применяется в два шага: сначала
// экран проверки, потом «Применить». Молча заменить ТЭП и деньги нельзя —
// человек должен увидеть, что именно поменяется и откуда взялось каждое число.

let presetPreview=null;

async function fillProjectPresets(){
 // Пресеты проектов лежат на сервере рядом с предустановками ТЭП, но это
 // разные вещи: та несёт книгу с площадями, этот — весь проект с деньгами,
 // сроками и очередями. Поэтому и списка два.
 try{
  const answer=await fetch('/api/project-presets'+presetsQuery());
  if(answer.status===403){hidePresetsBlock();return}
  const data=await answer.json();
  const select=document.getElementById('projectPresetSelect');
  (data.presets||[]).forEach(p=>{
   const option=document.createElement('option');
   option.value=p.id;
   option.textContent=p.name+(p.region?' · '+p.region:'');
   select.appendChild(option);
  });
 }catch(e){}
}

async function loadServerProjectPreset(){
 const id=document.getElementById('projectPresetSelect').value;
 if(!id){alert('Выберите пресет проекта из списка');return}
 // Экран проверки пресета — своё окно: два окна друг на друге не читаются.
 closeProjects();
 let parsed;
 try{
  const response=await fetch('/api/project-presets/'+encodeURIComponent(id)+presetsQuery());
  parsed=await response.json();
  if(!response.ok)throw new Error(parsed.detail||'Пресет не загружен');
 }catch(e){alert(String(e.message||e));return}
 await previewPreset(parsed);
}

async function previewPreset(parsed){
 let data;
 try{
  const response=await fetch('/api/project-presets/import',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({preset:parsed,mode:'preview',inputs,tep})});
  data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Пресет не разобран');
 }catch(e){alert(String(e.message||e));return}
 presetPreview=parsed;
 renderPresetPreview(data);
}

async function uploadPreset(){
 const file=document.getElementById('presetFile').files[0];
 if(!file){alert('Выберите файл .json с пресетом проекта');return}
 let parsed;
 try{parsed=JSON.parse(await file.text())}
 catch(e){alert('Файл не читается как JSON: '+String(e.message||e));return}
 await previewPreset(parsed);
}

function presetRows(rows){
 return rows.map(r=>`<tr><td>${escapeHtml(String(r.label))}</td>`
  +`<td>${r.was==null||r.was===''?'—':escapeHtml(fmtPresetValue(r.was))}</td>`
  +`<td><b>${escapeHtml(fmtPresetValue(r.becomes))}</b></td>`
  +`<td><small>${escapeHtml(r.action)}</small></td></tr>`).join('');
}

function fmtPresetValue(v){
 if(typeof v==='boolean')return v?'да':'нет';
 if(typeof v==='number')return Math.abs(v)>=1000?num(v):String(Math.round(v*1000)/1000);
 return String(v);
}

function renderPresetPreview(data){
 const origins={source:'из документа',derived:'рассчитано',assumption:'предпосылка',tbd:'не определено'};
 presetTitle.textContent='Импорт: '+(data.project_name||'проект');
 presetSummary.textContent=(data.region?data.region+' · ':'')+'схема '+data.schema_version
  +' · изменений: вводные '+data.diff.inputs.length+', ТЭП '+data.diff.tep.length
  +((data.cadastral_numbers||[]).length?' · участков: '+data.cadastral_numbers.length:'');
 const tbd=(data.notes||[]).filter(n=>n.origin==='tbd');
 presetErrors.style.display=tbd.length?'':'none';
 // У незакрытого поля с известным адресом — поле ввода: документ обычно есть,
 // просто в файл его не внесли, а править JSON ради одного числа никто не станет.
 presetErrors.innerHTML=tbd.length?'<b>Осталось не определённым:</b><br>'
  +tbd.map(n=>escapeHtml(n.note)
    +(n.input_key?` <input type="number" step="0.01" style="width:150px" `
      +`id="fill_${n.input_key}" placeholder="${escapeHtml(n.input_unit||'')}">`:'')).join('<br>'):'';
 const block=(title,html)=>html?`<h3 style="font-size:13px;margin:16px 0 6px">${title}</h3>${html}`:'';
 const table=rows=>rows?`<div class="scroll"><table><thead><tr><th>Показатель</th><th>Было</th><th>Станет</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:'';
 presetBody.innerHTML=
  block('ТЭП', table(presetRows(data.diff.tep)))
  +block('Вводные — ВРИ, соцнагрузка, сети', table(presetRows(data.diff.inputs)))
  +block('Откуда числа', '<div class="scroll"><table><tbody>'
    +(data.notes||[]).map(n=>`<tr><td style="width:130px"><small>${origins[n.origin]||n.origin}</small></td>`
      +`<td>${escapeHtml(n.note)}</td></tr>`).join('')+'</tbody></table></div>')
  +block('Вне периметра сделки', (data.reference||[]).map(b=>
    `<div class="note"><b>${escapeHtml(b.title)}</b><br>`
    +b.rows.map(r=>`${escapeHtml(String(r[0]))}: <b>${escapeHtml(fmtPresetValue(r[1]))}</b>`).join('<br>')
    +'</div>').join(''))
  +block('Множители себестоимости', (data.multipliers||[]).length?'<div class="scroll"><table><tbody>'
    +data.multipliers.map(m=>`<tr><td>${escapeHtml(m.object)}</td><td><b>×${m.multiplier}</b></td>`
      +`<td><small>${escapeHtml(m.status)}</small></td></tr>`).join('')+'</tbody></table></div>':'')
  +block('Открытые вопросы', (data.open_items||[]).length?'<ul style="font-size:12px;color:#666">'
    +data.open_items.map(x=>`<li>${escapeHtml(String(x))}</li>`).join('')+'</ul>':'');
 presetDialog.style.display='flex';
}

function closePreset(){presetDialog.style.display='none';presetPreview=null}

function presetFilledValues(){
 const filled={};
 document.querySelectorAll('#presetErrors input[id^="fill_"]').forEach(el=>{
  const value=Number(el.value);
  if(el.value!==''&&isFinite(value))filled[el.id.slice('fill_'.length)]=value;
 });
 return filled;
}

async function applyPreset(){
 if(!presetPreview)return;
 let data;
 try{
  const response=await fetch('/api/project-presets/import',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({preset:presetPreview,mode:'apply',inputs,tep,filled:presetFilledValues()})});
  data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Пресет не применён');
 }catch(e){alert(String(e.message||e));return}
 // Как и всюду: приходящее накладывается на умолчания, а не заменяет их.
 inputs=Object.assign(cloneValue(INPUT_DEFAULT),data.applied_inputs||{});
 seedParkingByHand();adoptObjectRateKind();restoreKrtClearedVriFee();
 tep=cloneValue(TEP_DEFAULT);
 Object.entries(data.applied_tep||{}).forEach(([key,values])=>{
  if(values&&typeof values==='object')tep[key]=Object.assign(tep[key]||{},values);
 });
 rememberDerivedTail(data.applied_tep);
 if(data.project_name)inputs._manual_tep_import={project_name:data.project_name};
 // Полный пресет приносит и собственную очередность. Оставлять прежний
 // `phasing` нельзя: тогда новый ТЭП раскладывается по долям другого проекта
 // (например, 40/13,1/34/12,9 вместо 25/25/25/25), хотя предпросмотр обещал
 // применить очереди пресета.
 if(data.phasing){
  const importedPhasing=cloneValue(data.phasing);
  const phaseDefaults=makeDefaultPhasing(Number(importedPhasing.phase_count||1));
  phasing=Object.assign(phaseDefaults,importedPhasing);
  // Продуктовые доли пресета заменяют старый проект целиком; служебные
  // аллокации расходов, которых в файле нет, добираются из безопасных
  // умолчаний, чтобы таблицы очередности оставались рабочими.
  phasing.products=importedPhasing.products||phaseDefaults.products;
  phasing.shared_cash=Object.assign(phaseDefaults.shared_cash,importedPhasing.shared_cash||{});
  phasing.shared_allocation=Object.assign(phaseDefaults.shared_allocation,importedPhasing.shared_allocation||{});
  phasing.discrete=Object.assign(phaseDefaults.discrete,importedPhasing.discrete||{});
  phasing.social_objects=importedPhasing.social_objects||[];
 }else phasing=makeDefaultPhasing(1);
 renderInputs();renderTep();renderPhasing();persistLocalSilently();
 closePreset();
 // Участок приезжает вместе с проектом: номера в поле, а следом та же
 // выгрузка ЕГРН и скрининг, что при ручном вводе. ТЭП при этом не трогаем —
 // он пришёл из пресета, и штатный расчёт ГлавАПУ его бы перебил.
 const cadastres=data.cadastral_numbers||[];
 if(cadastres.length){
  writeCadastralField(cadastres.join(', '));
  drawLandPreviewQuiet(cadastres.join(', '));
 }
 calculateAndOpen('report');
}

// --- хранилище проектов на сервере -------------------------------------------
// В браузере живёт ровно один проект: следующий участок затирает предыдущий.
// Сюда складывается то, что сохранили явно, — просмотр площадки остаётся
// черновиком. Данные лежат на ядре в России, Render их только пересылает.

let projectsAdminKey=localStorage.getItem('plato_projects_key')||'';

async function projectsCall(path,body){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(Object.assign({session:activeSession(),key:projectsAdminKey},body||{}))});
 // Тело читаем текстом: «Хранилище недоступно» одинаково выглядело и на
 // пятисотке, и на странице шлюза, и на обрыве сети — то есть не говорило
 // ничего. Правило то же, что у askJson на странице торгов: называем код и
 // первые слова ответа.
 const raw=await response.text();
 let data={};
 try{data=raw?JSON.parse(raw):{}}catch(e){}
 if(!response.ok){
  const said=String(data.detail||'').trim()
   ||raw.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,160);
  throw new Error(said?('Хранилище ответило '+response.status+': '+said)
   :('Хранилище ответило кодом '+response.status+' и пустым телом'));
 }
 return data;
}

// Кнопка «Личный кабинет» видна всегда: за ней живут готовые примеры, которые
// ключа не требуют. Прежде она появлялась только при настроенном хранилище —
// вместе с ним пропали бы и примеры, а они витрина, а не чужие данные.
let projectsStorageReady=false;
let projectsAcceptsKey=false;
let projectsAcceptsLogin=false;

async function initProjects(){
 document.getElementById('projectsButton').style.display='';
 try{
  const status=await (await fetch('/projects/status')).json();
  projectsAcceptsKey=!!status.accepts_key;
  projectsAcceptsLogin=!!status.accepts_login;
  calcRequiresLogin=!!status.calc_requires_login;
  // Хранилище показывается, когда есть чем войти: сессия (мини-приложение
  // или вход через бота), сам вход через бота или ключ администратора.
  projectsStorageReady=!!status.configured&&(!!activeSession()||projectsAcceptsLogin||projectsAcceptsKey);
 }catch(e){projectsStorageReady=false}
 const actions=document.getElementById('projectsStorageActions');
 if(actions)actions.style.display=projectsStorageReady?'inline-flex':'none';
 renderLoginButton();
 // Личные значения классов подгружаются сразу: класс выбирают из селектора и
 // без открытых настроек, а перекрышка обязана примениться и там.
 loadClassOverrides();
}

function renderLoginButton(){
 const button=document.getElementById('loginButton');
 if(!button)return;
 // В мини-приложении вход уже есть — он и открыл окно.
 const needed=projectsAcceptsLogin&&!telegramSession&&!webSession()&&!projectsAdminKey;
 button.style.display=needed?'':'none';
}

function openLogin(){
 openProjects();
 renderProjectsLogin();
}

function projectSummaryForStore(){
 const s=(lastResult&&lastResult.summary)||{};
 return {revenue_mln:Number(s.revenue||0)/1e6,net_profit_mln:Number(s.net_profit||0)/1e6,
         llcr:Number(s.llcr||0),purchase_price_mln:Number(inputs.purchase_price_mln||0)};
}

function projectCadastral(){
 const source=(cadastralAnalysis&&cadastralAnalysis.cadastral_numbers)
  ||(moResult&&moResult.cadastral_numbers)
  // Ответ источника сильнее: он знает, какие из спрошенных номеров настоящие.
  // Но его молчание — не отсутствие участка у проекта, а отсутствие ответа, и
  // тогда меткой идёт то, что человек вписал. Адрес и координаты меткой не
  // становятся: в поле их вводить можно, а `cadastral` записи — это номера.
  ||cadastralNumbersIn(inputs._cadastral_query)||[];
 return Array.isArray(source)?source.slice(0,20):[];
}

function projectStorePayload(){
 return {payload:{inputs,tep:persistedTep(tep),phasing,scenario:scenarioSelect.value||'base'},
  summary:projectSummaryForStore(),cadastral:projectCadastral()};
}

async function storeProject(id,name){
 // Одна дверь на все три кнопки: «Сохранить», «Сохранить как…» и «Поверх» в
 // строке списка. Три сборки одного запроса разошлись бы молча — так уже
 // терялась периодичность платежей ВРИ у присланного проекта.
 try{
  const saved=await projectsCall('/projects/save',
   Object.assign({id,name},projectStorePayload()));
  // Сохранённый проект становится открытым: следующее «Сохранить» пишет
  // поверх него, а не заводит третий экземпляр. Ссылку карточка ответа не
  // несёт — признак берём у того, поверх кого пишем.
  const previous=(id&&openedProject&&openedProject.id===id)?openedProject:null;
  rememberOpenedProject(Object.assign({},saved,{
   share_code:previous?previous.shareCode:'',
   has_share:previous?previous.shared:!!saved.has_share}));
  alert(id?('Записано поверх «'+name+'»'):'Проект сохранён на сервере');
  openProjects();
 }catch(e){
  // 428 от сервера — не отказ, а вопрос «кто вы»: открываем знакомство,
  // а не пугаем человека кодом ошибки.
  if(String(e.message||e).indexOf('Заполните знакомство')>=0){openProfile();return}
  alert(String(e.message||e));
 }
}

function projectShareNote(shared){
 return shared?'\n\nУ проекта есть ссылка «Поделиться»: получатель при '
  +'следующем открытии увидит новые числа.':'';
}

function saveOpenedProject(){
 // Кнопка видна только при открытом проекте, но состояние могло смениться
 // между отрисовкой и нажатием: молчаливое «сохранил как новый» здесь было бы
 // не тем, что человек просил.
 if(!openedProject){alert('Открытого проекта нет — нажмите «Сохранить как…».');return}
 if(!confirm('Записать поверх «'+openedProject.name+'»?'
  +projectShareNote(openedProject.shared)))return;
 storeProject(openedProject.id,openedProject.name);
}

function saveProjectAsNew(){
 const manualMeta=inputs._manual_tep_import||null;
 const suggested=(manualMeta&&manualMeta.project_name)||projectCadastral()[0]||'Проект';
 const asked=prompt('Название проекта в хранилище',suggested);
 if(asked===null)return;
 storeProject('',String(asked));
}

function saveProjectOver(id,name,shared){
 // Запись поверх прямо из строки: открывать проект ради перезаписи незачем,
 // а истории версий у хранилища нет — поэтому спрашиваем именем проекта.
 if(!confirm('Записать текущие вводные поверх «'+name+'»?\n\n'
  +'Прежние числа этого проекта будут заменены — вернуть их будет неоткуда.'
  +projectShareNote(shared)))return;
 storeProject(id,name);
}

function renderProjectsLogin(reason){
 // Панель входа живёт рядом с таблицей, не затирая её: после входа таблица
 // нужна той же самой.
 const stored=document.getElementById('projectsStored');
 if(!stored)return;
 let box=document.getElementById('projectsLoginBox');
 if(!box){
  box=document.createElement('div');
  box.id='projectsLoginBox';
  box.style.cssText='border:1px solid var(--line);padding:16px;margin-bottom:14px';
  const note=document.createElement('div');
  note.style.cssText='font-size:12px;color:#555;margin-bottom:10px';
  // Текст статический, innerHTML — только ради ссылки на согласие: вход и
  // есть момент, когда данные начинают собираться.
  note.innerHTML='Проекты хранятся на сервере в России и привязаны к вашему Telegram. '
   +'Войдите через бота — и сохраняйте расчёты с любого устройства. '
   +'После входа станут доступны Платон и PDF-отчёт. Входя, вы соглашаетесь с '
   +'<a href="/consent" target="_blank" rel="noopener">обработкой персональных данных</a>.';
  box.appendChild(note);
  const login=document.createElement('button');
  login.className='btn dark';
  login.textContent='Войти через Telegram';
  const status=document.createElement('div');
  status.style.cssText='font-size:12px;color:#777;margin-top:10px';
  login.onclick=()=>loginViaTelegram(status);
  if(!projectsAcceptsLogin)login.style.display='none';
  box.appendChild(login);
  if(projectsAcceptsKey){
   const keyBtn=document.createElement('button');
   keyBtn.className='btn';
   keyBtn.style.marginLeft='10px';
   keyBtn.textContent='У меня ключ администратора';
   keyBtn.onclick=enterProjectsKey;
   box.appendChild(keyBtn);
  }
  box.appendChild(status);
  stored.insertBefore(box,stored.firstChild);
 }
 box.style.display='';
 // Причина показывается в самой панели: «сервер не знает, чей это проект» в
 // окне запроса ключа человек читал уже после того, как ключ ввёл.
 const status=box.querySelector('div:last-child');
 if(status)status.textContent=reason?String(reason):'';
 // Кнопка входа через бота прячется, когда сервер его не предлагает, и
 // человек оставался перед панелью «войдите через бота» без самой кнопки
 // (замечание владельца, 18.08.2026). Отсутствие входа объясняется вслух.
 if(status&&!projectsAcceptsLogin){
  status.textContent=projectsAcceptsKey
   ?'Вход через бота на этом сервере не настроен: не задано имя бота (TELEGRAM_BOT_USERNAME). Пока доступен только ключ администратора.'
   :'Вход на этом сервере не настроен: нет ни имени бота, ни ключа администратора.';
 }
 const scroll=stored.querySelector('.scroll');
 if(scroll)scroll.style.display='none';
}

function hideProjectsLogin(){
 const box=document.getElementById('projectsLoginBox');
 if(box)box.style.display='none';
 const stored=document.getElementById('projectsStored');
 const scroll=stored&&stored.querySelector('.scroll');
 if(scroll)scroll.style.display='';
}

function enterProjectsKey(){
 const key=prompt('Ключ администратора (DEVELOPAID_ADMIN_KEY)');
 if(!key)return;
 projectsAdminKey=key.trim();
 localStorage.setItem('plato_projects_key',projectsAdminKey);
 openProjects();
}

// Кто вошёл и чем выйти. Сессия входа живёт в localStorage браузера; пока
// кнопки не было, выйти можно было только через консоль — на телефоне никак.
function renderAccountBox(){
 const box=document.getElementById('accountBox');
 if(!box)return;
 // В мини-приложении сессия приходит из хеша от бота: выходить там некуда и
 // не из чего — окно и так открыто конкретным человеком.
 if(telegramSession){box.style.display='none';return}
 const web=webSession();
 if(!web&&!projectsAdminKey){box.style.display='none';return}
 const profile=(profileState&&profileState.profile)||{};
 const title=web
  ?(profile.name?escapeHtml(profile.name):'Вход через Telegram подтверждён')
  :'Вход по ключу администратора';
 const details=[];
 if(web&&profile.company)details.push(escapeHtml(profile.company));
 if(web&&profile.role)details.push(escapeHtml(profile.role));
 if(web&&profile.telegram_name)details.push('Telegram: '+escapeHtml(profile.telegram_name));
 box.style.display='';
 box.innerHTML='<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">'+
  '<div><b>'+title+'</b>'+
  (details.length?'<div style="font-size:11px;color:#777;margin-top:2px">'+details.join(' · ')+'</div>':'')+
  (web&&profileState&&profileState.known===false
    ?'<div style="font-size:11px;color:#a05a00;margin-top:2px">'+escapeHtml(profileState.reason||'Знакомство не проверено')+'</div>'
    :(web&&profileState&&profileState.known&&!profileState.complete
      ?'<div style="font-size:11px;color:#a05a00;margin-top:2px">Знакомство не заполнено — проекты не сохранятся.</div>':''))+
  '</div>'+
  '<span style="margin-left:auto;display:flex;gap:10px">'+
  (web?'<button class="btn" onclick="openProfile()">Знакомство</button>':'')+
  '<button class="btn" onclick="logoutFromSite()">Выход</button>'+
  '</span></div>';
}

function logoutFromSite(){
 if(!confirm('Выйти из личного кабинета на этом устройстве?'))return;
 try{localStorage.removeItem(WEB_SESSION_KEY)}catch(e){}
 // Ключ администратора — тоже вход, и он тоже лежит в браузере: оставить его
 // после «Выхода» значит не выйти.
 try{localStorage.removeItem('plato_projects_key')}catch(e){}
 projectsAdminKey='';
 profileState={complete:false,profile:{},sources:profileState.sources};
 renderLoginButton();
 location.reload();
}

async function openProjects(){
 // Окно открывается сразу: примеры в нём есть всегда, и держать человека
 // перед запросом ключа ради витрины незачем. Список сохранённых
 // подгружается следом и только там, где хранилище настроено.
 projectsDialog.style.display='flex';
 renderAccountBox();
 renderOpenedProjectButton();
 const stored=document.getElementById('projectsStored');
 if(!projectsStorageReady){
  if(stored)stored.style.display='none';
  return;
 }
 if(stored)stored.style.display='';
 // Входа нет — предлагаем его, а не запираем дверь: кнопка «Войти через
 // Telegram» и, где настроен, ключ администратора.
 if(!activeSession()&&!projectsAdminKey){
  renderProjectsLogin();
  return;
 }
 hideProjectsLogin();
 let data;
 try{data=await projectsCall('/projects/list',{})}
 catch(e){
  // Ключ, который сервер не принял, спрашивался снова и снова: человек сидел
  // в окне ввода, а выход — вход через Telegram — был за его пределами
  // (замечание владельца, 18.08.2026). Непринятый ключ забываем и показываем
  // оба входа сразу, с причиной отказа рядом.
  if(!activeSession()){
   projectsAdminKey='';
   try{localStorage.removeItem('plato_projects_key')}catch(e2){}
   renderAccountBox();
   renderProjectsLogin(String(e.message||e));
   return;
  }
  alert(String(e.message||e));return;
 }
 const rows=(data.projects||[]).map(p=>{
  const s=p.summary||{};
  return `<tr><td><b>${escapeHtml(p.name||'')}</b><br><small>${escapeHtml(String(p.saved_at||'').replace('T',' ').replace('+00:00',' UTC'))}`
   +`${p.cadastral&&p.cadastral.length?' · '+escapeHtml(p.cadastral.join(', ')):''}</small></td>`
   +`<td>${s.revenue_mln?money(s.revenue_mln*1e6):'—'}</td>`
   +`<td>${s.net_profit_mln?money(s.net_profit_mln*1e6):'—'}</td>`
   +`<td>${s.llcr?mult(s.llcr):'—'}</td>`
   +`<td><button class="btn" onclick="loadProject('${p.id}')">Открыть</button> `
   +`<button class="btn" title="Сохранить текущие вводные в этот проект, поверх прежних чисел" `
   +`data-id="${escapeHtml(String(p.id||''))}" data-name="${escapeHtml(String(p.name||''))}" `
   +`data-shared="${p.has_share?'1':''}" `
   +`onclick="saveProjectOver(this.dataset.id,this.dataset.name,!!this.dataset.shared)">Сохранить</button> `
   +`<button class="btn" onclick="shareProject('${p.id}')">Ссылка</button> `
   +`<button class="btn" onclick="downloadSettingsFile('${p.id}')">Файл</button> `
   +`<button class="btn" onclick="deleteProject('${p.id}')">Удалить</button></td></tr>`;
 }).join('');
 projectsBody.innerHTML=rows||'<tr><td colspan="5">Пока ничего не сохранено.</td></tr>';
}

function closeProjects(){projectsDialog.style.display='none'}

function changeProjectsKey(){
 const key=prompt('Ключ администратора', projectsAdminKey||'');
 if(key===null)return;
 projectsAdminKey=key.trim();
 if(projectsAdminKey)localStorage.setItem('plato_projects_key',projectsAdminKey);
 else localStorage.removeItem('plato_projects_key');
 openProjects();
}

// Присланный проект накладывается на умолчания одним способом — этим.
// Копий было три (кабинет, файл настроек, полученная ссылка), и площадка КРТ
// стала бы четвёртой: поле, добавленное позже, чинится в одной из них и
// остаётся сломанным в остальных — ровно так уже терялась периодичность ВРИ.
// Территория живёт не только во вводных: разбор кадастра, контуры ЕГРН,
// скрининг НСПД, расчёт Подмосковья и карточка ГлавАПУ лежат в переменных
// страницы и в её разметке. Присланный проект подменял вводные, а всё это
// оставалось от прошлого участка — и уезжало в PDF, в подпись площади и в
// имя проекта: площадка КРТ на 15 га приходила «с парой кадастров на 5 га»
// (владелец, 02.09.2026). Забывается разом и в одном месте; то, что несёт сам
// снимок, поднимается заново из его вводных.
// Какой проект хранилища сейчас открыт: `{id, name, shareCode}` или null.
// Открытый проект правят и сохраняют обратно, а страница id не помнила —
// `loadProject` его не запоминал, `saveProjectToServer` не слал, и сервер
// честно заводил второй экземпляр (владелец, 04.09.2026: «открыл сохранённый,
// внёс изменения, и надо сохранять новый»). Перезапись хранилище умеет давно:
// при переданном id запись пишется под тем же именем файла, код «Поделиться»
// сохраняется и против лимита такой проект не считается.
let openedProject=null;

function rememberOpenedProject(record){
 // Помним ровно то, что нужно вопросу перед сохранением: чем перезаписывать,
 // как проект зовут и есть ли у него живая ссылка.
 openedProject=record&&record.id?{id:String(record.id),
  name:String(record.name||'Проект'),
  shareCode:String(record.share_code||''),
  // Код ссылки страница знает не всегда (в строке списка его нет), а
  // предупредить о живой ссылке надо и там: признак отдельно от кода.
  shared:!!(record.share_code||record.has_share)}:null;
 renderOpenedProjectButton();
}

function renderOpenedProjectButton(){
 // «Сохранить» без открытого проекта записать не во что: кнопки нет, а рядом
 // стоит имя того, поверх кого пишем, — иначе «Сохранить» и «Сохранить как…»
 // на экране неразличимы.
 // Функция зовётся из `rememberOpenedProject`, а его гоняют проверки в node,
 // где документа нет вовсе: спрашиваем через typeof, а не надеемся.
 if(typeof document==='undefined')return;
 const button=document.getElementById('projectsSaveOver');
 const label=document.getElementById('projectsOpenedName');
 if(!button||!label)return;
 if(openedProject){
  button.style.display='';
  button.title='Записать поверх «'+openedProject.name+'»';
  label.textContent='открыт: '+openedProject.name;
 }else{
  button.style.display='none';
  button.title='';
  label.textContent='';
 }
}

function forgetTerritoryState(){
 cadastralAnalysis=null;landLookup=null;landScreeningLast=null;LAND_MAP=null;
 glavapuImport=null;moResult=null;
 // Запрос района и ТТК по участку — тоже про участок: новый проект спрашивает свой.
 sitePositionRun={key:'',state:'',error:'',count:0};
 // Отложенный пересчёт ТЭП — тоже про участок: доживи он до нового проекта, и
 // ТЭП пересчитается по выгрузке удалённого. Снимается вместе с остальным.
 clearTimeout(tepAutoTimer);tepAutoTimer=null;moAutoApartments=null;moAutoBusy=false;
 // Опрос НСПД по прошлому участку может ещё идти: номер прогона отсекает его
 // ответ, иначе он дорисует чужие зоны поверх нового проекта.
 ++landScreeningRun;
 // Сверка сценария с ГлавАПУ — про прошлый проект: номер запуска отсекает
 // опоздавший ответ, а таблица и статус снимаются вместе с остальным.
 ++glavapuScenarioRun;
 ['glavapuScenarioResult','glavapuScenarioStatus','glavapuScenarioSummary'].forEach(id=>{const box=document.getElementById(id);if(box){box.innerHTML='';box.style.display=id==='glavapuScenarioResult'?'':'none'}});
 closeGlavapuScenario();
 ['cadastralNumbers','landQuery','moQuery'].forEach(id=>{const field=document.getElementById(id);if(field)field.value=''});
 // Память о вписанном номере (`inputs._cadastral_query`) здесь НЕ трогаем:
 // обе двери этой функции пересобирают `inputs` заново — `applyProjectSnapshot`
 // следом, `resetAll` заранее из `INPUT_DEFAULT`, где ключа нет вовсе. А
 // правка отсюда опаснее, чем кажется: снимок иногда и есть текущий `inputs`
 // (`applyProjectSnapshot(projectStorePayload().payload)`), и удаление стирало
 // бы участок из того самого снимка, который восстанавливают.
 ['landPreview','cadastralPreview','landScreening'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='none'});
 const screening=document.getElementById('landScreening');
 if(screening){screening.innerHTML='';screening.className='land-screening'}
 const cadStatus=document.getElementById('cadastralStatus');if(cadStatus)cadStatus.textContent='На внешний сервер передаются только кадастровые номера; финансовая модель не передаётся.';
 const landStatus=document.getElementById('landStatus');if(landStatus)landStatus.textContent='На внешний сервис передаётся только строка поиска; финансовая модель не передаётся.';
 dropGlavapuPreview();dropMoPreview();
}

function applyProjectSnapshot(data){
 data=data||{};
 // Пришёл другой проект — значит открытый больше не открыт. Забывается здесь,
 // в единственной точке подмены снимка: иначе «Сохранить поверх» записало бы
 // чужие числа в тот проект, из которого их уже не достать — истории версий у
 // хранилища нет. Кто открыл проект по-настоящему, скажет об этом следом.
 openedProject=null;
 forgetTerritoryState();
 inputs=Object.assign(cloneValue(INPUT_DEFAULT),data.inputs||{});
 tep=cloneValue(TEP_DEFAULT);
 Object.entries(data.tep||{}).forEach(([key,values])=>{
  if(values&&typeof values==='object')tep[key]=Object.assign(tep[key]||{},values);
 });
 rememberDerivedTail(data.tep,true);
 phasing=data.phasing||makeDefaultPhasing(1);
 // Список тронутых полей паркинга — от ЭТОГО снимка, а не от прошлого проекта.
 seedParkingByHand();adoptObjectRateKind();restoreKrtClearedVriFee();
 if(typeof scenarioSelect!=='undefined'&&scenarioSelect)scenarioSelect.value=data.scenario||'base';
 renderInputs();renderTep();renderPhasing();
 // Шапка — класс и вид проекта — читает те же вводные, что и форма: без этого
 // загруженный «Пользовательский» проект показывал в шапке класс прежнего
 // проекта с его подсказкой ставок, пока страницу не перезагрузят.
 syncProjectClassSelector();syncProjectKindSelector();
 // Территория снимка — из его же вводных, тем же путём, что при загрузке страницы.
 renderStoredCadastralQuery();
 renderStoredGlavapu();renderStoredCadastral();renderStoredLand();renderStoredMo();
 if(typeof renderSitePanel==='function')renderSitePanel();
 persistLocalSilently();
}

async function loadProject(id){
 let record;
 try{record=await projectsCall('/projects/open',{id})}
 catch(e){alert(String(e.message||e));return}
 const data=record.payload||{};
 // Как и локальная загрузка: сохранённое накладывается на умолчания, а не
 // подменяет их — иначе поле, добавленное позже, исчезнет.
 applyProjectSnapshot(data);
 // После наложения: `applyProjectSnapshot` забывает открытый проект, и это
 // верно для всех её вызовов, кроме этого одного.
 rememberOpenedProject(record);
 closeProjects();
 calculateAndOpen('report');
}

// Файл настроек — второй способ передать проект, рядом со ссылкой (владелец,
// 21.08.2026). Ссылка живёт на нашем сервере: он должен отвечать, а код —
// не протухнуть. Файл не зависит ни от чего — его пересылают почтой, кладут
// в папку проекта, открывают через год. Внутри тот же снимок, что и по
// ссылке: вводные, ТЭП, очерёдность, сценарий — и ничего сверх того.
const SETTINGS_FILE_KIND='developaid.project.settings';

function settingsFileFrom(name,payload){
 return {kind:SETTINGS_FILE_KIND,version:1,app_version:'__DEVELOPAID_VERSION__',
  name:name||'Проект',saved_at:new Date().toISOString(),
  inputs:payload.inputs||{},tep:payload.tep||{},
  phasing:payload.phasing||null,scenario:payload.scenario||'base'};
}

// Скачивание собирается на месте: файл не уходит на сервер и обратно, поэтому
// не зависит ни от сети, ни от того, доступен ли он вошедшему.
function saveJsonFile(name,data){
 const blob=new Blob([JSON.stringify(data,null,1)],{type:'application/json'});
 const url=URL.createObjectURL(blob);
 const a=document.createElement('a');
 a.href=url;a.download=name;document.body.appendChild(a);a.click();
 document.body.removeChild(a);setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function safeFileName(name){
 return String(name||'Проект').replace(/[\\/:*?"<>|]+/g,' ').trim().slice(0,60)||'Проект';
}

async function downloadSettingsFile(id){
 let record;
 try{record=await projectsCall('/projects/open',{id})}
 catch(e){alert(String(e.message||e));return}
 const payload=record.payload||{};
 saveJsonFile(safeFileName(record.name)+' — настройки DevelopAid.json',
              settingsFileFrom(record.name,Object.assign({},payload,{tep:persistedTep(payload.tep,false)})));
}

// Текущий проект — тот, что открыт на экране, а не сохранённый. Сохранять
// ради выгрузки не заставляем: человек мог ничего не сохранять вовсе.
function downloadCurrentSettings(){
 saveJsonFile(safeFileName(currentProjectName())+' — настройки DevelopAid.json',
  settingsFileFrom(currentProjectName(),
   {inputs:inputs,tep:persistedTep(tep),phasing:phasing,scenario:scenarioSelect.value}));
}

// Имя берётся оттуда же, откуда его предлагает сохранение на сервер: своего
// поля с именем на странице нет, и заводить второе значило бы развести их.
function currentProjectName(){
 const meta=inputs._manual_tep_import||null;
 return (meta&&meta.project_name)||projectCadastral()[0]||'Проект DevelopAid';
}

function importSettingsFile(){
 const input=document.getElementById('settingsFileInput');
 if(input){input.value='';input.click()}
}

// Чужой файл — данные, а не команда: проверяем, что это наш формат, и
// накладываем на умолчания, а не подменяем их. Иначе поле, добавленное после
// выгрузки, исчезнет — на этом уже обжигались с сохранённым состоянием.
async function applySettingsFile(input){
 const file=input&&input.files&&input.files[0];
 if(!file)return;
 let data;
 try{data=JSON.parse(await file.text())}
 catch(e){alert('Файл не читается как JSON: '+String(e.message||e));return}
 if(!data||data.kind!==SETTINGS_FILE_KIND){
  alert('Это не файл настроек DevelopAid. Нужен .json из кнопки «Скачать настройки текущего».');
  return;
 }
 if(!confirm('Загрузить настройки «'+String(data.name||'без имени')+'»?\n\n'
  +'Сохранён: '+String(data.saved_at||'').replace('T',' ').slice(0,16)
  +(data.app_version?' · версия '+data.app_version:'')+'\n\n'
  +'Текущие вводные на экране будут заменены.'))return;
 applyProjectSnapshot(data);
 closeProjects();
 calculateAndOpen('report');
}

// Передача проекта другому человеку: не PDF, а набор параметров для работы
// (владелец, 20.08.2026). Ссылку открывает любой, кто её получил, и живёт она
// бессрочно — поэтому рядом всегда есть «отозвать»: у вечной открытой ссылки
// без выключателя нет способа передумать.
async function shareProject(id){
 let answer;
 try{answer=await projectsCall('/projects/share',{id})}
 catch(e){alert(String(e.message||e));return}
 const link=location.origin+'/?shared='+encodeURIComponent(answer.code);
 // Буфер обмена доступен не везде (нет https, отказ в правах, старый WebView) —
 // тогда ссылку показываем в поле, откуда её можно выделить руками. Молчаливое
 // «скопировано», когда не скопировалось, хуже отсутствия кнопки.
 let copied=false;
 try{await navigator.clipboard.writeText(link);copied=true}catch(e){}
 const message='Ссылка на проект «'+(answer.name||'')+'»:\n'+link+'\n\n'
  +(copied?'Скопирована в буфер обмена. ':'')
  +'Открыть её может любой, кому вы её пришлёте; получатель увидит снимок '
  +'расчёта и сможет сохранить его себе. Ваши дальнейшие правки в этот снимок '
  +'не попадут — обновите ссылку тем же «Поделиться».\n\n'
  +'Отозвать ссылку — «Поделиться» ещё раз и «Отозвать» в этом окне.';
 if(confirm(message+'\n\nОК — оставить ссылку, Отмена — отозвать её.'))return;
 try{await projectsCall('/projects/unshare',{id});alert('Ссылка отозвана.')}
 catch(e){alert(String(e.message||e))}
}

// Присланный проект: открывается по /?shared=<код>, входа не требует.
async function openSharedProject(code){
 let snapshot;
 try{snapshot=await projectsCall('/projects/shared',{id:code})}
 catch(e){alert('Проект по ссылке не открылся. '+String(e.message||e));return}
 const who=snapshot.author?('от '+snapshot.author):'без подписи автора';
 const when=String(snapshot.saved_at||'').replace('T',' ').slice(0,16);
 const s=snapshot.summary||{};
 const numbers=[s.revenue_mln?('выручка '+money(s.revenue_mln*1e6)):'',
                s.net_profit_mln?('прибыль '+money(s.net_profit_mln*1e6)):'',
                s.llcr?('LLCR '+mult(s.llcr)):''].filter(Boolean).join(' · ');
 if(!confirm('Проект «'+(snapshot.name||'без названия')+'» '+who+'\n'
   +(when?('посчитан '+when+'\n'):'')
   +(snapshot.cadastral&&snapshot.cadastral.length?('участок: '+snapshot.cadastral.join(', ')+'\n'):'')
   +(numbers?(numbers+'\n'):'')
   +'\nОткрыть его вводные у себя? Ваш текущий расчёт будет заменён.'))return;
 const data=snapshot.payload||{};
 // Как и своя загрузка: присланное накладывается на умолчания, а не подменяет
 // их — снимок мог быть сделан версией, где поля ещё не было.
 applyProjectSnapshot(data);
 // Ссылка из адреса убирается: перезагрузка страницы не должна второй раз
 // затирать работу, которую человек уже начал на присланных вводных.
 try{history.replaceState(null,'',location.pathname)}catch(e){}
 calculateAndOpen('report');
}

function checkSharedLink(){
 let code='';
 try{code=new URLSearchParams(location.search).get('shared')||''}catch(e){}
 if(code)openSharedProject(code);
}

async function deleteProject(id){
 if(!confirm('Удалить проект из хранилища?'))return;
 try{
  await projectsCall('/projects/delete',{id});
  // Удалённый проект открытым не остаётся: «Сохранить поверх» завело бы его
  // заново под тем же id, и удаление выглядело бы несработавшим.
  if(openedProject&&openedProject.id===String(id))openedProject=null;
  openProjects();
 }catch(e){alert(String(e.message||e))}
}

// Состояние страницы, которое НЕ принадлежит проекту, — и потому сбросу не
// подлежит: сессия и вход, анкета, номера запусков и таймеры. Номер запуска
// сбрасывать нельзя отдельно: на нём держится защита от опоздавшего ответа —
// обнулив его, мы пустили бы ответ на прошлый запрос в чистый проект.
// Справочник Подмосковья (цены округов, документ Кд) — тоже не проект: он
// приезжает с сервера один раз, и вычистить его значит ослепить расчёт МО.
//
// Список объявлен здесь, рядом со сбросом, а не в тесте: тест берёт его
// отсюда и требует, чтобы всякая ОСТАЛЬНАЯ переменная страницы сбросом
// обнулялась. Следующая переменная попадёт в проверку тем, что появилась, —
// а не тем, что о ней вспомнили. Список, ведомый памятью, уже подводил
// трижды: после «Сбросить» оставались то поля Подмосковья, то очередность,
// то посчитанный отчёт прошлого проекта, и человек видел одно — «не работает».
const NON_PROJECT_STATE=['feedbackShown','feedbackCalcs','feedbackReportSeconds','feedbackReportTimer',
 'profileState','profileAskedOnResult','calcRequiresLogin','calcRun','webLoginBusy',
 'projectsAdminKey','projectsStorageReady','projectsAcceptsKey','projectsAcceptsLogin',
 'telegramResultSent','telegramCalcOverrides','telegramEditSubmitting','telegramFinishing',
 'aiBusy','moAutoBusy','moRecalcTimer','sensitivityBusy','moDistrictPrices','moKdDocument',
 'landScreeningRun','tepRunSequence','glavapuScenarioRun',
 'CLASS_OVERRIDES','CLASS_OVERRIDES_NOTE','CLASS_OVERRIDES_FROM_SERVER',
 'CLASS_STATS_BY','CLASS_STATS_KEY','CLASS_STATS_ERROR','CLASS_DETAIL_OPEN',
 'PROJECT_KIND_WHERE'];

function resetProjectState(){
 // Данные проекта, которые живут переменными страницы, а не полями формы.
 // Их не видно на экране до тех пор, пока они не всплывут: подпись «Кладовые
 // 3 200 м²» под строкой паркинга, жалоба на пропорции ТЭП, разговор Платона
 // о прошлом проекте, отчёт чувствительности чужой площадки.
 lastResult=null;
 // Открытый проект — тоже данные проекта: после сброса «Сохранить поверх»
 // записало бы пустой расчёт в чужую запись.
 openedProject=null;
 aiHistory=[];aiProposals=[];aiIntake=null;aiDocument=null;
 territoryCleared=[];tepRatioComplaint='';phaseTepEditWarning='';
 Object.keys(tepRefillNote).forEach(key=>{delete tepRefillNote[key]});
 moLastQuery='';moAutoApartments=null;
 presetPreview=null;sensitivityOptions=null;sensitivityReport=null;sensitivityPicked=null;sensitivityFrameKind=null;
 // Ограничения прошлой площадки на карте новой — это чужие зоны под своим
 // контуром, и выглядят они так же убедительно, как свои.
 landScreeningLast=null;LAND_MAP=null;
}

// Посчитанное остаётся на экране, пока его не сотрут: renderResult при пустом
// результате выходит сразу и ничего не перерисовывает. Поэтому после сброса
// вкладка «Отчёт» показывала ТЭП, выручку и LLCR прошлого проекта — и это
// главное, что человек называл «сброс не работает».
//
// Стирается по строению, а не по списку имён: сгенерированное лежит в телах
// таблиц с id, в плитках и в оглавлении. Статичная разметка не трогается, и
// вставленное слоем перестройки — тоже: оно лежит выше, прямо в панели.
let resetRun=0;
// Каким обязан стать набор вводных после сброса. Объявлено один раз: проверка
// «что уцелело» сверяется с тем же выражением, которым сброс и присваивает.
// Пока их было два, проверка честно жаловалась на поля, которые сброс сам же
// и ставит.
// Каким обязано стать состояние после сброса. Объявлено один раз — и сбросом,
// и его самопроверкой: пока умолчаний было два, проверка жаловалась на поля,
// которые сброс сам же и ставит.
//
// Предпосылки аналитика возвращаются к умолчаниям, ДАННЫЕ УЧАСТКА обнуляются.
// Прежде сброс ставил и то и другое умолчанием, а умолчание ТЭП — это пример:
// 130 716,7 м² ГНС, 80 000 продаваемой, 1 361 квартира. На экране после
// «Сбросить» стояли те же числа, что до него, и читалось это ровно так —
// «ничего не сбросилось» (владелец, 29.08.2026, снимок экрана). Разделение то
// же, что при импорте участка: цена входа, площади объектов и соцнагрузка
// принадлежат площадке, а ставки, сроки и налоги — аналитику.
function resetInputsWanted(){
 const want=Object.assign(cloneValue(INPUT_DEFAULT),{
  project_class:'comfort', rate_scenario:'base',
  scenario_revenue_multiplier:1, scenario_cost_multiplier:1});
 TERRITORY_INPUT_KEYS.forEach(key=>{if(key in want)want[key]=SITE_ONLY_INPUTS.includes(key)?'':0});
 // Признак ВРИ — вид платы (`vriPaymentActive`): плата сброшена — снят и он.
 want.vri_required=vriPaymentActive(want);
 return want;
}
// ТЭП после сброса — нули, а не пример. Строки и подписи остаются: таблица без
// строк читается как поломка, а не как пустой проект.
function resetTepWanted(){
 const want=cloneValue(TEP_DEFAULT);
 Object.keys(want).forEach(row=>{
  ['gns','total_area','useful','saleable','transfer','units'].forEach(field=>{
   if(field in want[row])want[row][field]=0;
  });
 });
 return want;
}
function blankResultSurfaces(){
 ['report','finance','calendar','sensitivity'].forEach(id=>{
  const panel=document.getElementById(id);if(!panel)return;
  panel.querySelectorAll('table').forEach(table=>{
   const generated=table.querySelectorAll('tbody[id]');
   if(generated.length)generated.forEach(body=>{body.innerHTML=''});
   else if(table.id)table.innerHTML='';
  });
  panel.querySelectorAll('.kpis,.report-toc').forEach(node=>{node.innerHTML=''});
 });
 const meta=document.getElementById('pdfReportMeta');if(meta)meta.textContent='—';
}

// Кнопка «Сбросить» начинает проект заново, а не чистит его по списку.
// Три захода подряд список чинили — и каждый раз оставалось что-то ещё:
// поля Подмосковья, очередность, применённый файл ГлавАПУ, посчитанный отчёт.
// Перезагрузка страницы не имеет списка вовсе, поэтому и обойти его нечем:
// хранилище чистится, адрес приводится к чистому, окно поднимается заново.
//
// Мини-приложение перезагружать нельзя: бот открывает его ссылкой с сессией в
// хеше, и поднявшаяся заново страница загрузит из этой сессии тот же проект —
// сброс отменил бы сам себя. Там остаётся сброс на месте, а он полный.
function resetProject(){
 const left=resetAll();
 // Уцелевшее называется вслух. «Не всё обнуляется» — спор, который нельзя
 // выиграть памятью: обе стороны правы про разные поля. Молчание здесь и есть
 // причина спора.
 if(left&&left.length){
  try{alert('Сброс оставил: '+left.slice(0,12).join(', ')
    +(left.length>12?' и ещё '+(left.length-12):'')
    +'.\nЭто ошибка — пришлите этот список.')}catch(e){}
 }
 if(isTelegramWebApp())return left;
 try{localStorage.removeItem('plato_v04')}catch(e){}
 // Груз из торгов и КРТ ждёт в sessionStorage и применяется при загрузке:
 // не сняв его, мы перезагрузились бы в ту же площадку.
 try{sessionStorage.removeItem('developaid.auction.pending.v1')}catch(e){}
 try{location.replace(location.pathname)}catch(e){location.reload()}
}

function resetTepControls(){
 // Сброс чистил данные и не перерисовывал экран. renderTep() не трогает ни
 // панель участка, ни очередность: площадь 22,423 га и посадка 18 000 после
 // «Сбросить» оставались на месте, а любое касание поля возвращало их в
 // расчёт через onchange. Очередность при этом показывала прежние очереди
 // при уже сброшенном phasing — экран и состояние расходились молча.
 //
 // Правило: сброс обязан перерисовать всё, что он обнулил. Список того, что
 // рисуется не из inputs, проверяется тестом по самой странице, а не памятью.
 resetMoParams();
 if(typeof renderSitePanel==='function')renderSitePanel();
 if(typeof renderPhasing==='function')renderPhasing();
 if(typeof renderPhaseFinancing==='function')renderPhaseFinancing();
 // Выбранный пресет и имя файла настроек — тоже след прошлого проекта:
 // «Сбросить» с оставшимся «Румянцево» в списке читается как «не сработало».
 ['serverPresetSelect','projectPresetSelect'].forEach(id=>{
  const el=document.getElementById(id);if(el)el.selectedIndex=0;
 });
 const settingsFile=document.getElementById('settingsFileInput');
 if(settingsFile)settingsFile.value='';
}
function resetMoParams(){
 // Поля Подмосковья живут в разметке, а не в inputs, и сброс их не видел:
 // после «Сбросить» плотность оставалась прежней — 18 000 у чужого участка,
 // — а подпись рядом продолжала обещать умолчание. Значение по умолчанию у
 // каждого поля объявлено один раз, атрибутом value, и восстанавливается
 // оттуда же: вторая копия умолчаний в коде разошлась бы с разметкой.
 const box=document.getElementById('moParamsBox');if(!box)return;
 box.querySelectorAll('input').forEach(el=>{
  if(el.type==='checkbox'){el.checked=el.defaultChecked;return}
  el.value=el.getAttribute('value')||'';
 });
 box.querySelectorAll('select').forEach(el=>{el.selectedIndex=0});
 if(typeof toggleMoPrice==='function')toggleMoPrice();
 if(typeof toggleMoKd==='function')toggleMoKd();
 box.open=false;
}
function resetAll(){
 localStorage.removeItem('plato_v04');
 inputs=resetInputsWanted();
 tep=resetTepWanted();
 phasing=makeDefaultPhasing(1);phaseBundle=null;reportView='all';
 // Противоречия прошлого проекта не должны глушить раскрытие блока в новом.
 siteParkingConflictSeen='';
 // Территория забывается тем же способом, что при подмене проекта: прежде
 // glavapuImport переживал сброс, и «чистый» проект применял ТЭП удалённого
 // участка.
 forgetTerritoryState();
 rates=[];
 scenarioSelect.value='base';
 renderInputs();renderTep();renderStoredGlavapu();renderScenarioNote();syncProjectClassSelector();syncProjectKindSelector();
 resetTepControls();
 resetProjectState();
 blankResultSurfaces();
 syncRateControlsFromInputs();generateRateCurve();renderRates();
 refreshCurrentKeyRate(true);
 // Перерисовка полей выше поднимает onchange, а он зовёт calculate(). Расчёт
 // асинхронный: он возвращается уже ПОСЛЕ того, как сброс обнулил lastResult,
 // и заполняет отчёт заново. На сайте это скрыто перезагрузкой, в
 // мини-приложении её нет — и «Сбросить» оставлял на экране посчитанный отчёт.
 // Номер прогона отсекает опоздавший ответ тем же способом, что и везде.
 resetRun=(resetRun||0)+1;
 const stamp=resetRun;
 setTimeout(()=>{if(stamp!==resetRun)return;lastResult=null;blankResultSurfaces()},0);
 return resetLeftovers();
}

// Сброс, который проверяет сам себя. «Не всё обнуляется» — спор, который
// нельзя выиграть памятью: обе стороны правы про разные поля. Поэтому после
// сброса состояние сверяется с умолчаниями, и уцелевшее НАЗЫВАЕТСЯ. Пусто —
// значит пусто, а не «кажется, сработало».
function resetLeftovers(){
 const left=[];
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const want=resetInputsWanted();
 Object.keys(want).forEach(key=>{
  if(!same(inputs[key],want[key]))left.push('вводная «'+key+'»');
 });
 Object.keys(inputs).forEach(key=>{
  if(!(key in want))left.push('лишняя вводная «'+key+'»');
 });
 const wantTep=resetTepWanted();
 Object.keys(wantTep).forEach(row=>{
  const was=wantTep[row]||{},now=tep[row]||{};
  Object.keys(was).forEach(field=>{
   if(!same(now[field],was[field]))left.push('ТЭП «'+row+'.'+field+'»');
  });
 });
 return left;
}

// Кабинет показывается до всего остального. Прежде его открывал initProjects()
// в самом конце файла, и любой сбой выше оставлял кнопку скрытой навсегда:
// хранилище работало, а войти в него было нечем.
try{
 var projectsEarly=document.getElementById('projectsButton');
 if(projectsEarly)projectsEarly.style.display='';
}catch(e){}

loadLocal();
initProjects();
// Присланный проект открывается сразу: человек пришёл по ссылке, а не за своей
// вкладкой. Проверка идёт после loadLocal — сначала восстанавливается своё
// состояние, потом спрашивается, заменить ли его присланным.
checkSharedLink();
// Кто зашёл, спрашивается один раз: у вошедшего без анкеты открывается
// Анкету на загрузке только читаем: всплывать на каждой перезагрузке — это не
// «спросить один раз», а спрашивать без конца. Показывается она после входа и
// на выходе к результату.
loadProfile(false);
fillProjectPresets();
{
 const sc=SCENARIOS[scenarioSelect.value]||SCENARIOS.base;
 // Old saved projects did not have the new transparent scenario multipliers.
 // Treat their current inputs as the BASE model and only apply the selected +/-10% overlay.
 if(inputs.scenario_revenue_multiplier==null)inputs.scenario_revenue_multiplier=Number(sc.scenario_revenue_multiplier||1);
 if(inputs.scenario_cost_multiplier==null)inputs.scenario_cost_multiplier=Number(sc.scenario_cost_multiplier||1);
}
"""
