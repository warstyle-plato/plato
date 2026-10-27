"""Кусок страницы PAGE: Скрипт: Платон Сергеевич — окно агента, сообщения, предложения правок,
приём документов, ожидание ответа.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_plato")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""let aiHistory=[],aiBusy=false,aiProposals=[];
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function toggleAgent(open){aiDrawer.classList.toggle('open',!!open);aiOverlay.classList.toggle('open',!!open);if(open)setTimeout(()=>aiInput.focus(),80)}
// Модель отвечает Markdown-ом, а сообщение выводилось как есть, и человек
// читал «**LLCR 1,070x**» вместе со звёздочками. Разметка снимается уже после
// экранирования: на вход сюда приходит текст без единого живого тега, поэтому
// вставить через ответ модели чужой HTML нельзя.
function renderAiMarkdown(text){
 return escapeHtml(text)
  .replace(/^#{1,6}\s*(.+)$/gm,'<b>$1</b>')
  .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
  .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g,'$1<i>$2</i>')
  .replace(/`([^`\n]+)`/g,'<code>$1</code>')
  .replace(/^\s*[-*]\s+/gm,'• ')
  .replace(/\n/g,'<br>');
}
function appendAiMessage(role,content,extra=''){hideAiHero();const d=document.createElement('div');d.className=`ai-msg ${role} ${extra}`.trim();d.innerHTML=renderAiMarkdown(content);aiMessages.appendChild(d);aiMessages.scrollTop=aiMessages.scrollHeight;return d}
// Картинка объясняет пустое окно и на этом её работа кончается: с первым
// сообщением она уходит и переписке не мешает.
function hideAiHero(){
 const hero=document.getElementById('aiHero');
 if(hero)hero.style.display='none';
}

function appendAiProposals(proposals){
 hideAiHero();
 (proposals||[]).forEach(p=>{
   const idx=aiProposals.push(p)-1;
   const changes=(p.changes||[]).map(x=>`${escapeHtml(x.label)}: <b>${escapeHtml(x.old)}</b> → <b>${escapeHtml(x.new)}</b>`).join('<br>');
   const llcr=p.scenario&&p.scenario.llcr_x!=null?`<div style="margin-top:7px">LLCR после: <b>${Number(p.scenario.llcr_x).toFixed(3)}x</b></div>`:'';
   const d=document.createElement('div');d.className='ai-msg assistant';
   d.style.border='1px solid #c9d7c7';d.style.background='#f7fbf6';
   d.innerHTML=`<b>Готовое изменение вводных</b><div style="margin-top:6px">${changes}</div>${llcr}<button style="margin-top:10px;padding:8px 12px;border:0;border-radius:8px;background:#173b2d;color:#fff;font-weight:700;cursor:pointer" onclick="applyAgentProposal(${idx})">Применить в модель</button>`;
   aiMessages.appendChild(d);
 });
 aiMessages.scrollTop=aiMessages.scrollHeight;
}
async function applyAgentProposal(idx){
 const p=aiProposals[idx];if(!p||!p.patch)return;
 Object.entries(p.patch).forEach(([k,v])=>{
   const value=Number(v);
   if(k==='main_construction_cost_th_per_sqm'){inputs.main_above_th_per_sqm=value;inputs.main_under_th_per_sqm=value}
   else inputs[k]=value;
 });
 // Предложение Платона — тоже не класс: поле профиля, которое он поменял,
 // помечается вписанным так же, как правка руками.
 Object.keys(p.patch).forEach(k=>{
   if(k==='main_construction_cost_th_per_sqm'){markClassManual('main_above_th_per_sqm');markClassManual('main_under_th_per_sqm')}
   else markClassManual(k);
   // Класс офиса число Платона тоже не перезаписывает.
   markFieldManual('inputs.'+(k==='main_construction_cost_th_per_sqm'?'main_above_th_per_sqm':k));
 });
 renderInputs();syncTep(false);syncProjectClassSelector();syncProjectKindSelector();renderPhasing();await calculate();
 appendAiMessage('assistant','Изменение применено к текущим Inputs и модель пересчитана.');
}
function askAgentQuick(text,scenario){aiInput.value=text;sendAgentMessage(scenario)}
async function refreshAgentStatus(){try{const r=await fetch('/agent/status'),s=await r.json();aiStatusDot.classList.toggle('ready',!!s.enabled);aiStatusDot.title=s.enabled?`AI готов · ${s.model} · думает через ${s.thinks_via||'этот сервер'}`:'AI не настроен: нет ни OPENAI_API_KEY, ни PLATO_AI_URL'}catch(e){aiStatusDot.classList.remove('ready')}}
async function syncInputsForAgent(){document.querySelectorAll('[id^=f_]').forEach(el=>{const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});if(document.getElementById('rateScenario'))inputs.rate_scenario=rateScenario.value||'base';generateRateCurve();repairParkingFromGlavapu();normalizeSocialObjectDates()}
// Разбор присланного документа. Тизер, справка по участку, решение ГЗК — то,
// что аналитик переписывает в модель руками, и ошибка переписывания на экране
// неотличима от расчёта.
//
// Ничего не подставляется молча: загрузка ПОКАЗЫВАЕТ карточку (найдено, уйдёт
// в расчёт, не хватает), вопросы о недостающем меняют карточку, а в модель
// она уходит только кнопкой «Всё верно, считать».
function aiEsc(value){const box=document.createElement('div');box.textContent=String(value==null?'':value);return box.innerHTML}
let aiIntake=null;
// Документ в разговоре: после разбора человек спрашивает дальше, и вопрос
// уходит вместе с документом. Отдельно от aiHistory — та режется по числу
// реплик, и документ выпадал бы из неё через несколько вопросов. Новая
// загрузка заменяет прежний документ.
let aiDocument=null;
function rememberAiDocument(data){
 const ctx=data&&data.context;
 const had=aiDocument;
 if(!ctx||!ctx.text){
  aiDocument=null;
  appendAiMessage('system','Документ в разговор не попал: '+(data&&data.reason||'разбор не вернул текста документа')
   +(had?'. Прежний документ «'+had.filename+'» из разговора убран.':'.'));
  return;
 }
 aiDocument=ctx;
 aiHistory.push({role:'user',content:'Документ на разбор: '+ctx.filename});
 aiHistory.push({role:'assistant',content:String(ctx.summary||'')});
 aiHistory=aiHistory.slice(-10);
 appendAiMessage('system','Документ «'+ctx.filename+'» в разговоре: следующие вопросы Платон видит вместе с ним'
  +(ctx.trimmed?' (первые '+ctx.read_chars+' знаков из '+ctx.total_chars+')':'')
  +'. Новая загрузка заменит его'+(had&&had.filename!==ctx.filename?' — «'+had.filename+'» заменён':'')+'.');
}
async function sendAgentDocument(file){
 if(!file||aiBusy)return;
 aiBusy=true;aiSendBtn.disabled=true;aiFileBtn.disabled=true;
 appendAiMessage('user','Документ: '+file.name);
 const thinking=document.createElement('div');thinking.className='ai-thinking';
 thinking.textContent='Читаю документ…';aiMessages.appendChild(thinking);aiMessages.scrollTop=aiMessages.scrollHeight;
 try{
  // Сначала прочитать, потом сбросить поле: iOS Safari освобождает выбранный
  // файл при сбросе, и чтение после него падает «The object can not be found here».
  const buffer=await file.arrayBuffer();
  document.getElementById('aiFile').value='';
  // Разбор base64 порциями: строка на два мегабайта через apply падает на
  // пределе аргументов, и падение выглядит как «файл не читается».
  const bytes=new Uint8Array(buffer);let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));
  await syncInputsForAgent();
  const r=await fetch('/agent/document',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({filename:file.name,content_b64:btoa(binary),inputs,tep,class_profile:aiClassProfile(),
    session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await r.json().catch(()=>({}));
  thinking.remove();
  if(!r.ok){appendAiMessage('system',(serverDetail(data)||('Документ не разобрался: HTTP '+r.status))
   +(aiDocument?'\nВ разговоре остаётся прежний документ «'+aiDocument.filename+'».':''));return}
  aiIntake=data;aiIntakeApplied=[];aiCard=data.card||null;
  renderAiIntakeFirst(data);rememberAiDocument(data);
 }catch(e){thinking.remove();appendAiMessage('system','Документ не разобрался: '+(e.message||e))}
 finally{document.getElementById('aiFile').value='';aiBusy=false;aiSendBtn.disabled=false;aiFileBtn.disabled=false}
}
// Разбор тизера — три шага, одинаковых на сайте и в боте (владелец,
// 25.10.2026). Первый — только карточка: найдено (со страницей), уйдёт в
// расчёт (поле и значение с происхождением), не хватает (что возьмётся по
// умолчанию или по норме). Вопросов здесь нет, модель не меняется. Карточку
// собирает сервер (`teaser_card.build`), окно её только показывает.
let aiCard=null;
// Числа класса жилья в этом проекте (регион, личные настройки, вид проекта):
// карточка показывает их, а не московскую базу класса.
function aiClassProfile(){
 const keys=['apartment_price_th','commercial_price_th','parking_price_th','main_above_th_per_sqm','main_under_th_per_sqm'];
 const out={};
 Object.keys(PROJECT_CLASS_PRESETS).forEach(c=>{out[c]={};keys.forEach(k=>{
  try{const v=classValue(c,k);if(Number.isFinite(Number(v)))out[c][k]=Number(v)}catch(e){}
 })});
 return out;
}
function renderAiIntakeFirst(data){
 const doc=data.document||{};
 const note=data.reason||doc.reason||'';
 if(!data.card){
  // Разбор не удался или документ без текста: карточки нет, причина — вслух.
  const box=document.createElement('div');box.className='ai-msg system';
  box.innerHTML='<b>'+aiEsc(doc.filename||'документ')+'</b><div style="margin-top:6px;color:#8a4b08">'
   +aiEsc(note||'Разбор не вернул данных: в документе не нашлось того, что понимает модель.')+'</div>'
   +(data.dropped||[]).map(line=>'<div style="margin-top:4px;color:#8a4b08;font-size:12px">Не взято: '+aiEsc(line)+'</div>').join('');
  aiMessages.appendChild(box);aiMessages.scrollTop=aiMessages.scrollHeight;return;
 }
 renderAiCard(data.card,{first:true,recognized:!!doc.recognized,trimmed:doc.trimmed?doc:null});
}
function aiCardRows(rows,cell){
 return '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">'+rows.map(cell).join('')+'</table>';
}
function renderAiCard(card,opts){
 opts=opts||{};
 const box=document.createElement('div');box.className='ai-msg system ai-card';
 const q=card.questions||{};
 let html='<b>'+(opts.first?'Что я прочитал в тизере':'Итог разбора перед расчётом')+'</b> · «'+aiEsc(card.filename||'документ')+'»'
  +(card.pages?'<span style="color:#888"> · страниц: '+aiEsc(card.pages)+'</span>':'');
 if(card.recognized)html+='<div style="margin-top:6px;color:#8a4b08">Документ — скан: текст распознан по картинке, поэтому сверьте числа с документом.</div>';
 if(opts.trimmed)html+='<div style="margin-top:6px;color:#8a4b08">Документ длинный: прочитаны первые '+aiEsc(opts.trimmed.read_chars)+' знаков из '+aiEsc(opts.trimmed.total_chars)+'.</div>';
 if(card.error)html+='<div style="margin-top:6px;color:#8a4b08">'+aiEsc(card.error)+'</div>';
 const found=card.found||[];
 html+='<div class="ai-card-found" style="margin-top:8px"><b>1. Что найдено в тизере</b>';
 html+=found.length?aiCardRows(found,f=>'<tr><td style="padding:2px 4px 2px 0">'+aiEsc(f.label)+'<div style="color:#888;font-size:11px">«'+aiEsc(f.quote)+'»</div></td>'
   +'<td style="padding:2px 4px;white-space:nowrap"><b>'+aiEsc(Array.isArray(f.value)?f.value.join(', '):f.value)+'</b> '+aiEsc(f.unit)+'</td>'
   +'<td class="ai-card-page" style="padding:2px 0;color:#666">'+aiEsc(f.page_text)+'<div style="color:'+(f.used?'#2e6b2e':'#8a4b08')+'">'+aiEsc(f.status)+'</div></td></tr>')
  :'<div style="margin-top:4px">В тизере не нашлось чисел, которые понимает модель.</div>';
 html+='</div>';
 const go=card.to_engine||[];
 html+='<div class="ai-card-engine" style="margin-top:10px"><b>2. Что уйдёт в расчёт</b>';
 html+=go.length?aiCardRows(go,r=>'<tr data-path="'+aiEsc(r.path)+'"><td style="padding:2px 4px 2px 0">'+aiEsc(r.label)+'</td><td style="padding:2px 4px"><b>'+aiEsc(r.shown)+'</b>'
   +'<div style="color:#666;font-size:11px">'+aiEsc(r.origin)+'</div></td></tr>')
  :'<div style="margin-top:4px">Из тизера в расчёт ничего не идёт.</div>';
 html+='</div>';
 const miss=card.missing||[];
 if(miss.length){
  html+='<div class="ai-card-missing" style="margin-top:10px"><b>3. Чего нет в тизере — что возьмётся вместо этого</b>';
  html+=aiCardRows(miss,r=>'<tr data-path="'+aiEsc(r.path)+'"><td style="padding:2px 4px 2px 0">'+aiEsc(r.label)+'</td><td style="padding:2px 4px">'+aiEsc(r.shown)
   +'<div style="color:#666;font-size:11px">'+aiEsc(r.origin)+'</div></td></tr>');
  html+='</div>';
 }
 (card.notes||[]).forEach(n=>{html+='<div style="margin-top:6px;color:#666;font-size:12px">'+aiEsc(n)+'</div>'});
 (card.dropped||[]).forEach(line=>{html+='<div style="margin-top:4px;color:#8a4b08;font-size:12px">Не взято: '+aiEsc(line)+'</div>'});
 const left=Math.max(0,Number(q.total||0)-Number(q.index||0));
 html+='<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">';
 if(card.ready)html+='<button class="btn dark" data-act="calc">Всё верно, считать</button>';
 else html+='<div style="width:100%">Модель пока не менялась. Дальше — '+aiEsc(left)+' '+(left===1?'вопрос':left<5?'вопроса':'вопросов')+' о том, чего в тизере нет, по одному.</div>'
  +'<button class="btn dark" data-act="questions">Перейти к вопросам</button>';
 html+='</div>';
 box.innerHTML=html;aiMessages.appendChild(box);aiMessages.scrollTop=aiMessages.scrollHeight;
 box.querySelectorAll('button[data-act]').forEach(b=>b.onclick=()=>{
  box.querySelectorAll('button[data-act]').forEach(x=>x.disabled=true);
  if(b.dataset.act==='questions')renderAiQuestion(card);
  else confirmAiCard(card,box);
 });
 return box;
}
// Происхождение подставленного из документа: значение нормы или импорта после
// сохранения не должно выглядеть ручным, а документ — источник, а не человек.
function aiDocumentOrigin(filename,how){
 return {source:'document',text:'из документа «'+(filename||'документ')+'»'+(how?' · '+how:'')};
}
// Ответ сервера на применение — в модель, одним путём для таблицы разбора и
// для вопросов: два пути разошлись бы ровно на том поле, где важно.
function aiNum(v){
 if(v===undefined||v===null||v==='')return '—';
 const n=Number(v);return Number.isFinite(n)&&typeof v!=='boolean'?n.toLocaleString('ru-RU',{maximumFractionDigits:2}):String(v);
}
// «Было → стало» одной строкой и в единицах поля; у суммы обязательств —
// из чего она сложилась, у вписанного числа — как его прочли.
function aiChangeLine(a){
 const now=a.shown||aiNum(a.now);
 let line=(a.label||a.key)+': '+aiNum(a.was)+' → '+now+(a.unit&&!a.shown?' '+a.unit:'');
 if(a.parts&&a.parts.length>1||(a.parts&&a.base))
  line+=' (сумма: '+(a.base?aiNum(a.base)+' уже стояло в проекте + ':'')+a.parts.map(p=>aiNum(p.value)).join(' + ')+')';
 if(a.read_as)line+=' — '+a.read_as;
 return line;
}
// Кадастровый номер из документа — в поле участка (вкладка «Проект» →
// «Участок»), с происхождением «из документа». Прежде применение отвечало
// «участок применяется отдельным запросом ЕГРН», а запроса не было: номер в
// проект не попадал вовсе (владелец, 18.10.2026).
function applyAiCadastral(a,filename){
 const raw=Array.isArray(a.value)?a.value.join(', '):String(a.value==null?'':a.value);
 const numbers=[...new Set(cadastralNumbersIn(raw))];
 if(!numbers.length)return 'не применено — '+(a.label||'кадастровые номера')+': в «'+raw+'» не опознан кадастровый номер';
 writeCadastralField(numbers.join(', '),aiDocumentOrigin(filename));
 dropStaleLandPreview();
 aiCadastralReady=true;
 return (a.label||'Кадастровые номера')+' → '+numbers.join(', ')+' — во вкладке «Проект», поле участка. '
  +'Сведения ЕГРН и ТЭП по нему ещё не получены — кнопка ниже';
}
let aiCadastralReady=false;
function appendAiCadastralButton(){
 if(!aiCadastralReady)return;aiCadastralReady=false;
 const d=document.createElement('div');d.className='ai-msg system';
 d.innerHTML='<button class="btn dark" onclick="this.disabled=true;toggleAgent(false);obtainTep()">Получить ТЭП по участку из документа</button>';
 aiMessages.appendChild(d);aiMessages.scrollTop=aiMessages.scrollHeight;
}
// Шаг второй: вопросы только о недостающем, по одному. Ответ меняет
// карточку, а не модель: в расчёт она уходит кнопкой «Всё верно, считать».
let aiQuestion=null;
function renderAiQuestion(card){
 aiCard=card;
 const q=card.questions||{};
 if(!q.card){renderAiCard(card);return}
 aiQuestion={id:card.id,index:q.index,total:q.total,card:q.card,filename:card.filename};
 const ask=q.card;
 const box=document.createElement('div');box.className='ai-msg system ai-question';
 let html='<b>Вопрос '+aiEsc(q.index+1)+' из '+aiEsc(q.total)+'</b><div style="margin-top:4px">'+aiEsc(ask.question)+'</div>';
 html+='<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">';
 (ask.options||[]).forEach((o,i)=>{
  html+='<button class="btn ai-question-option" data-choice="'+i+'" onclick="answerAiQuestion('+i+')">'+aiEsc(o.label)+'</button>';
 });
 html+='</div>';
 const unit=ask.unit||((ask.options||[]).find(o=>o.target)||{}).unit||'';
 const typed=!ask.kind&&(ask.key||(ask.options||[]).some(o=>o.target&&(o.value===null||o.value===undefined)));
 if(typed)
  html+='<div style="display:flex;gap:6px;margin-top:8px;align-items:center"><input class="ai-question-value" inputmode="decimal" placeholder="своё значение'
   +(unit?', '+aiEsc(unit):'')+'" style="flex:1;min-width:0;padding:6px 8px;border:1px solid #ccc;border-radius:6px">'
   +(ask.key?'<button class="btn dark" onclick="answerAiQuestion(-1)">Ответить</button>':'')+'</div>';
 html+='<div style="margin-top:8px;font-size:12px"><a href="#" data-action="skip" onclick="answerAiQuestion(-1,this.dataset.action);return false">Пропустить</a> · '
  +'<a href="#" data-action="stop" onclick="answerAiQuestion(-1,this.dataset.action);return false">Закончить вопросы</a></div>';
 box.innerHTML=html;aiMessages.appendChild(box);aiMessages.scrollTop=aiMessages.scrollHeight;
 aiQuestion.box=box;
}
async function answerAiQuestion(choice,action,mode){
 const queue=aiQuestion;if(!queue||!queue.card||aiBusy)return;
 const box=queue.box;const typedEl=box&&box.querySelector('.ai-question-value');
 const typed=action?'':(mode?queue.typed||'':String(typedEl&&typedEl.value||'').trim());
 const option=(queue.card.options||[])[choice];
 if(!action&&!queue.card.kind&&option&&option.target&&(option.value===null||option.value===undefined)&&!typed){
  appendAiMessage('system','У варианта «'+option.label+'» нет числа. Впишите значение в поле под вопросом и нажмите вариант ещё раз.');return}
 if(!action&&choice<0&&!typed){appendAiMessage('system','Впишите значение или выберите вариант.');return}
 aiBusy=true;
 if(box)box.querySelectorAll('button,input,a').forEach(el=>{el.disabled=true;el.style.pointerEvents='none'});
 try{
  await syncInputsForAgent();
  const r=await fetch('/agent/document/answer',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({intake_id:queue.id,index:queue.index,action:action||'answer',choice,value:typed,
    mode:mode||'',inputs,tep,class_profile:aiClassProfile(),session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await r.json().catch(()=>({}));
  if(!r.ok){appendAiMessage('system','Ответ не принят: '+(serverDetail(data)||('HTTP '+r.status)));
   if(box)box.querySelectorAll('button,input,a').forEach(el=>{el.disabled=false;el.style.pointerEvents=''});return}
  if(data.stale){appendAiMessage('system','На этот вопрос уже ответили. Продолжаю с текущего.');
   renderAiQuestion(data.card);return}
  if(data.confirm){queue.typed=typed;renderAiConfirm(queue,choice,data.confirm);return}
  const said=action==='skip'?'пропущено':(action==='stop'?'вопросы закончены':(data.answer||typed));
  if(action!=='stop'){
   aiHistory.push({role:'user',content:'Ответ на вопрос по документу «'+queue.card.question+'»: '+said});
   aiHistory=aiHistory.slice(-10);
  }
  const lines=(data.applied||[]).map(a=>'в карточку: '+aiChangeLine(a))
   .concat((data.refused||[]).map(x=>'в расчёт не пойдёт: '+(x.label||x.key)+': '+x.reason));
  appendAiMessage('system',(action==='skip'?'Пропущено.':action==='stop'?'Вопросы закончены.':'Ответ: '+said)
   +(lines.length?'\n'+lines.join('\n'):''));
  aiCard=data.card;
  if(data.card.questions&&data.card.questions.card)renderAiQuestion(data.card);
  else{aiQuestion=null;renderAiCard(data.card)}
 }catch(e){appendAiMessage('system','Ответ не принят: '+(e.message||e));
  if(box)box.querySelectorAll('button,input,a').forEach(el=>{el.disabled=false;el.style.pointerEvents=''})}
 finally{aiBusy=false}
}
// В поле обязательства уже стоит своё число: прибавить ответ к нему или
// заменить — решает человек. Молча прибавленное к ручному числу или молча
// затёртое им одинаково неотличимы от ошибки.
function renderAiConfirm(queue,choice,c){
 const box=document.createElement('div');box.className='ai-msg system ai-confirm';
 box.innerHTML='В поле «'+aiEsc(c.label)+'» уже стоит '+aiEsc(aiNum(c.current))+' '+aiEsc(c.unit)
  +(c.origin?' ('+aiEsc(c.origin)+')':'')+'. Ответ добавляет '+aiEsc(aiNum(c.adding))+' '+aiEsc(c.unit)+'. Как поступить?'
  +'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">'
  +'<button class="btn dark" data-mode="add">Прибавить: будет '+aiEsc(aiNum(Number(c.current)+Number(c.adding)))+' '+aiEsc(c.unit)+'</button>'
  +'<button class="btn" data-mode="replace">Заменить: будет '+aiEsc(aiNum(c.adding))+' '+aiEsc(c.unit)+'</button></div>';
 box.querySelectorAll('button').forEach(b=>b.onclick=()=>{box.querySelectorAll('button').forEach(x=>x.disabled=true);answerAiQuestion(choice,'',b.dataset.mode)});
 aiMessages.appendChild(box);aiMessages.scrollTop=aiMessages.scrollHeight;
}
// Состояние модели до документа — для «было → стало» итога и для отмены
// одной кнопкой. Снимок вводных, ТЭП и ключевых показателей.
let aiDocBaseline=null,aiIntakeApplied=[];
function aiSnapshot(){
 return {inputs:JSON.parse(JSON.stringify(inputs)),tep:JSON.parse(JSON.stringify(tep)),
  metrics:aiMetrics(lastResult)};
}
function aiMetrics(r){
 const s=r&&r.summary;if(!s)return null;
 return [['Чистая прибыль',money(s.net_profit)],['NPV проекта',money(s.npv)],
  ['IRR проекта',irrFmt(s.irr_project)],['LLCR',mult(s.llcr)]];
}
// Пересчёт после документа и ключевые показатели «до документа → сейчас».
async function aiRecalcInto(recalc){
 recalc.textContent='Пересчитываю модель…';
 const before=aiDocBaseline&&aiDocBaseline.metrics;
 const got=await calculate().catch(e=>({error:e}));
 // null — расчёт отказал (вход, доступ): прежний результат тогда остаётся
 // на месте и выдавать его за пересчитанный нельзя.
 const after=got===null?null:aiMetrics(lastResult);
 if(!after){recalc.textContent='Модель не пересчиталась'+(got&&got.error?': '+(got.error.message||got.error):' — результат расчёта не получен')+'. Значения уже стоят во вводных; нажмите «Рассчитать».';return}
 recalc.innerHTML='Модель пересчитана.'+'<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">'
  +'<tr><th style="text-align:left">Показатель</th><th style="text-align:right">До документа</th><th style="text-align:right">Сейчас</th></tr>'
  +after.map((m,i)=>'<tr><td>'+aiEsc(m[0])+'</td><td style="text-align:right">'+aiEsc(before?before[i][1]:'—')+'</td><td style="text-align:right"><b>'+aiEsc(m[1])+'</b></td></tr>').join('')
  +'</table>'+(before?'':'<div style="color:#666;font-size:12px">До документа расчёта не было, сравнить не с чем.</div>');
 aiMessages.scrollTop=aiMessages.scrollHeight;
}
// Отмена — назад к снимку до документа: вводные, ТЭП и происхождение полей.
async function undoAiDocument(){
 if(!aiDocBaseline)return;
 Object.keys(inputs).forEach(k=>delete inputs[k]);Object.assign(inputs,JSON.parse(JSON.stringify(aiDocBaseline.inputs)));
 Object.keys(tep).forEach(k=>delete tep[k]);Object.assign(tep,JSON.parse(JSON.stringify(aiDocBaseline.tep)));
 aiIntakeApplied=[];if(aiIntake)aiIntake._applied=[];
 syncTep(false);renderInputs();renderTep();await calculate();
 appendAiMessage('system','Изменения из документа отменены: вводные и ТЭП вернулись к состоянию до документа, модель пересчитана.');
}
// Шаг третий: «Всё верно, считать». Движок получает ровно строки «уйдёт в
// расчёт». Карточка собирается заново по текущим вводным: если их поменяли
// после загрузки тизера, показываем новую и не считаем по старой.
function aiCardKey(card){return JSON.stringify((card.to_engine||[]).map(r=>[r.path,r.value]))}
function aiCardValueNow(path){
 const p=path.split('.');
 if(p[0]==='inputs')return inputs[p[1]];
 if(p[0]==='tep')return (tep[p[1]]||{})[p[2]];
 return undefined;
}
async function confirmAiCard(shown,box){
 if(aiBusy)return;aiBusy=true;
 const status=document.createElement('div');status.className='ai-intake-recalc';status.style.marginTop='6px';
 box.appendChild(status);status.textContent='Сверяю карточку с вводными…';
 try{
  await syncInputsForAgent();
  const r=await fetch('/agent/document/card',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({intake_id:shown.id,inputs,tep,class_profile:aiClassProfile(),session:activeSession(),access_key:projectsAdminKey||''})});
  const card=await r.json().catch(()=>({}));
  if(!r.ok){status.textContent='Расчёт не запущен: '+(serverDetail(card)||('HTTP '+r.status));return}
  if(aiCardKey(card)!==aiCardKey(shown)){
   status.textContent='Вводные поменялись после загрузки тизера, поэтому карточка собрана заново. Проверьте её и нажмите «Всё верно, считать» ещё раз.';
   aiBusy=false;renderAiCard(card);return;
  }
  aiDocBaseline=aiSnapshot();
  const rows=card.to_engine||[];
  // Класс — первым: его профиль ставит цены и ставки, а строки карточки
  // затем пишут ровно свои числа.
  const cls=rows.find(x=>x.path==='inputs.project_class');
  // Вписанное руками класс не меняет: карточка это уже сказала, поэтому окно
  // «заменить вписанное?» здесь отвечается «оставить».
  if(cls&&cls.value!==inputs.project_class){
   const ask=window.confirm;window.confirm=()=>false;
   try{applyProjectClassPreset(cls.value)}finally{window.confirm=ask}
  }
  rows.forEach(row=>{
   const p=row.path.split('.');
   if(p[0]==='inputs')inputs[p[1]]=row.value;
   else if(p[0]==='tep'){tep[p[1]]=tep[p[1]]||{};tep[p[1]][p[2]]=row.value}
   else if(row.path==='land.cadastral_numbers'){applyAiCadastral({label:row.label,value:row.value},card.filename);return}
   fieldOrigins()[row.path]={source:'document',text:row.origin||aiDocumentOrigin(card.filename).text};
  });
  syncTep(false);renderInputs();renderTep();syncProjectClassSelector();
  // Сверка после записи: если пересчёт страницы сдвинул число карточки,
  // это видно здесь, а не в расчёте молча.
  const moved=rows.filter(row=>!row.derived&&(row.path.startsWith('inputs.')||row.path.startsWith('tep.')))
   .filter(row=>{const now=aiCardValueNow(row.path);
    return typeof row.value==='number'?Math.abs(Number(now)-row.value)>1e-6:String(now)!==String(row.value)})
   .map(row=>row.label+': в карточке '+aiNum(row.value)+', в расчёте '+aiNum(aiCardValueNow(row.path)));
  if(moved.length){
   const warn=document.createElement('div');warn.style.cssText='margin-top:6px;color:#8a4b08';
   warn.textContent='Не совпало с карточкой — '+moved.join('; ')+'.';box.appendChild(warn);
  }
  aiBusy=false;
  await aiRecalcInto(status);
  const after=document.createElement('div');after.style.cssText='display:flex;flex-wrap:wrap;gap:6px;margin-top:8px';
  after.innerHTML='<button class="btn dark" data-act="report">Открыть результат</button>'
   +'<button class="btn" data-act="inputs">Проверить вводные</button>'
   +'<button class="btn" data-act="undo">Отменить изменения документа</button>';
  box.appendChild(after);
  after.querySelectorAll('button[data-act]').forEach(b=>b.onclick=()=>{
   const act=b.dataset.act;
   if(act==='report'){toggleAgent(false);openTab('report')}
   else if(act==='inputs'){toggleAgent(false);openTab('inputs')}
   else if(act==='undo'){b.disabled=true;undoAiDocument()}
  });
  appendAiCadastralButton();
 }catch(e){status.textContent='Расчёт не запущен: '+(e.message||e)}
 finally{aiBusy=false}
}
async function sendAgentMessage(scenario){
 if(aiBusy)return;const message=String(aiInput.value||'').trim();if(!message)return;
 aiBusy=true;aiSendBtn.disabled=true;aiInput.value='';appendAiMessage('user',message);aiHistory.push({role:'user',content:message});
 const thinking=document.createElement('div');thinking.className='ai-thinking';thinking.textContent='Анализирую текущую модель…';aiMessages.appendChild(thinking);aiMessages.scrollTop=aiMessages.scrollHeight;
 // trace_id генерирует страница: он нужен ей раньше ответа, чтобы опрашивать
 // стадию. Пока запрос идёт, подпись показывает, что именно сейчас происходит,
 // и «долго» отличимо от «зависло».
 const traceId=Array.from(crypto.getRandomValues(new Uint8Array(6))).map(b=>b.toString(16).padStart(2,'0')).join('');
 const stagePoll=setInterval(async()=>{try{const r=await fetch('/agent/trace/'+traceId);const t=await r.json();if(t&&t.label&&t.stage!=='done')thinking.textContent=t.label+'…'}catch(e){}},1200);
 // Номер принятой работы читает catch ниже, поэтому он объявлен ДО try:
 // объявленный внутри, он в catch недоступен, и кнопка «Забрать ответ» не
 // вставала бы никогда.
 let resumeTrace='';
 try{
  await syncInputsForAgent();
  let data={},response=null;
  try{
   response=await fetch('/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,scenario:scenario||'',trace_id:traceId,inputs,tep,rates,phasing,history:aiHistory.slice(-8),document:aiDocument||{},selected_view:reportView||'all',session:activeSession(),access_key:projectsAdminKey||''})});
   try{data=await response.json()}catch(e){}
   if(response.ok&&data&&data.pending){
    // Сервер не держит соединение: работа принята и идёт, ответ ждёт под
    // номером запуска. Так длительность работы перестаёт упираться в чужие
    // сроки — nginx, Render и мобильная сеть рвали её на полпути.
    data=await awaitAgentResult(traceId,thinking,true);
    if(data&&data.timedOut)resumeTrace=data.traceId;
    response={ok:!!data.answer,status:200};
   }
  }catch(networkError){
   // «Load failed» — не ответ сервера, а обрыв соединения: один длинный
   // запрос не переживает ни nginx, ни мобильную сеть, а работа на сервере
   // при этом доходит до конца. Забираем готовый ответ коротким запросом.
   data=await awaitAgentResult(traceId,thinking);
   if(data&&data.timedOut)resumeTrace=data.traceId;
   response={ok:!!data.answer,status:504};
  }
  if(response&&!response.ok&&(response.status===502||response.status===504)){
   const late=await awaitAgentResult(traceId,thinking);
   if(late&&late.answer){data=late;response={ok:true,status:200}}
   // Сохранённая причина отказа лучше общего текста: прежде она здесь
   // терялась, и человек читал «временно не получил ответ» вместо неё.
   else if(late&&late.detail&&!data.detail)data={detail:late.detail};
   if(late&&late.timedOut)resumeTrace=late.traceId;
  }
  thinking.remove();
  if(response&&response.status===401){
   // Мягкий гейт: вопрос требует входа — кнопка прямо в чате, а не совет
   // искать её где-то в другом окне.
   appendAiMessage('assistant',String(serverDetail(data)||'Платон доступен после входа через Telegram.'),'error');
   appendAiLoginButton();
   return;
  }
  if(!response.ok)throw new Error(serverDetail(data)||AI_UNAVAILABLE);
  const answer=String(data.answer||'Ответ не получен.');
  appendAiMessage('assistant',answer+(data.cached?'\n\n*Ответ из кэша: тот же вопрос по тем же вводным за последние 10 минут.*':''));
  if(Array.isArray(data.proposals)&&data.proposals.length)appendAiProposals(data.proposals);aiHistory.push({role:'assistant',content:answer});aiHistory=aiHistory.slice(-10);
 }catch(e){thinking.remove();appendAiMessage('assistant',String(e.message||e),'error');
  // Работа принята — значит забрать её можно: кнопка стоит там, где человек
  // прочитал отказ, а не на соседнем экране.
  if(resumeTrace)appendAiResumeButton(resumeTrace)}
 finally{clearInterval(stagePoll);aiBusy=false;aiSendBtn.disabled=false;aiInput.focus()}
}
const AI_UNAVAILABLE='Платон Сергеевич временно не получил ответ от AI-сервиса. Расчётная модель продолжает работать. Повторите вопрос через несколько секунд.';

function appendAiResumeButton(traceId){
 // «Забрать ответ» — не повтор вопроса: работа уже идёт под этим номером, и
 // второе нажатие «Отправить» заказало бы вторую работу вместо начатой.
 const wrap=document.createElement('div');
 wrap.style.cssText='margin:8px 0';
 const btn=document.createElement('button');
 btn.className='btn dark';
 btn.textContent='Забрать ответ';
 const status=document.createElement('div');
 status.style.cssText='font-size:12px;color:#777;margin-top:6px';
 btn.onclick=async()=>{
  btn.disabled=true;btn.textContent='Забираю…';
  const late=await awaitAgentResult(traceId,status,true);
  if(late&&late.answer){
   wrap.remove();
   const answer=String(late.answer);
   appendAiMessage('assistant',answer);
   if(Array.isArray(late.proposals)&&late.proposals.length)appendAiProposals(late.proposals);
   aiHistory.push({role:'assistant',content:answer});aiHistory=aiHistory.slice(-10);
   return;
  }
  btn.disabled=false;btn.textContent='Забрать ответ';
  status.textContent=String((late&&late.detail)||AI_UNAVAILABLE);
 };
 wrap.appendChild(btn);
 wrap.appendChild(status);
 aiMessages.appendChild(wrap);
 aiMessages.scrollTop=aiMessages.scrollHeight;
}

function appendAiLoginButton(){
 const wrap=document.createElement('div');
 wrap.style.cssText='margin:8px 0';
 const btn=document.createElement('button');
 btn.className='btn dark';
 btn.textContent='Войти через Telegram';
 const status=document.createElement('div');
 status.style.cssText='font-size:12px;color:#777;margin-top:6px';
 btn.onclick=()=>loginViaTelegram(status);
 wrap.appendChild(btn);
 wrap.appendChild(status);
 aiMessages.appendChild(wrap);
 aiMessages.scrollTop=aiMessages.scrollHeight;
}

async function awaitAgentResult(traceId,thinking,accepted){
 // Ответ ждёт на сервере под номером запуска. Опрос короткий и частый: его
 // не рвёт ни прокси, ни спящий мобильный интернет.
 let deadline=Date.now()+300000;const hardStop=Date.now()+900000;let seenStage='';
 const startedAt=Date.now();let lastStage='';
 while(Date.now()<deadline){
  await new Promise(r=>setTimeout(r,2000));
  try{
   const r=await fetch('/agent/result/'+traceId);
   if(r.ok){
    const x=await r.json();
    if(x&&!x.pending&&x.answer)return x;
    // Работа упала — причина лежит там же, под номером запуска.
    if(x&&!x.pending&&x.error)return {detail:String(x.error)};
   }
  }catch(e){}
  let stage='';
  try{const t=await(await fetch('/agent/trace/'+traceId)).json();if(t&&t.label&&t.stage!=='done')stage=t.label}catch(e){}
  // Пока движок отчитывается о новом шаге, работа идёт, а не висит: сдаваться
  // по часам, когда на той стороне что-то происходит, — терять посчитанное.
  if(stage)lastStage=stage;
  if(stage&&stage!==seenStage){seenStage=stage;deadline=Math.min(hardStop,Date.now()+180000)}
  // Пока ждём, показываем стадию: «долго» должно отличаться от «зависло».
  if(thinking){
   // Принятая работа и оборванное соединение — разные вещи, и человеку врать
   // ни в ту, ни в другую сторону нельзя.
   const tail=accepted?' (работа идёт, жду ответ)':' (соединение оборвалось, жду ответ)';
   thinking.textContent=stage?stage+'…'+tail
                            :(accepted?'Работа принята, жду ответ…':'Соединение оборвалось, забираю готовый ответ…');
  }
 }
 // Сдаваясь, окно называет причину. Общий текст «временно не получил ответ»
 // одинаков и когда молчит AI-сервис, и когда стоит очередь у сервиса модели,
 // и когда работа давно упала, — по нему разобрать нечего.
 const waited=Math.round((Date.now()-startedAt)/1000);
 // Окно сдалось, а работа на сервере продолжается и ляжет под тем же номером
 // запуска: выбросить её значит потерять посчитанное (экран владельца,
 // 14.09.2026 — «ответ не пришёл за 6 мин 24 с»). Номер уезжает вместе с
 // отказом, и рядом с ним встаёт кнопка «Забрать ответ».
 return {timedOut:true,traceId:traceId,
   detail:'Ответ не пришёл за '+Math.floor(waited/60)+' мин '+(waited%60)+' с.'
   +(lastStage?' Последняя стадия: '+lastStage+'.':'')
   +' Работа на сервере продолжается — заберите ответ кнопкой ниже.'};
}

document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.getElementById('aiDrawer')?.classList.contains('open'))toggleAgent(false);if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&document.getElementById('aiDrawer')?.classList.contains('open'))sendAgentMessage()});


"""
