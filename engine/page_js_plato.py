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
// Ничего не подставляется молча: загрузка ПОКАЗЫВАЕТ таблицу «поле — значение —
// откуда взято», а применение — отдельная кнопка с галочками. Чего разбор не
// понял, он спрашивает, а не додумывает.
function aiEsc(value){const box=document.createElement('div');box.textContent=String(value==null?'':value);return box.innerHTML}
let aiIntake=null;
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
   body:JSON.stringify({filename:file.name,content_b64:btoa(binary),inputs,tep,
    session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await r.json().catch(()=>({}));
  thinking.remove();
  if(!r.ok){appendAiMessage('system',data.detail||('Документ не разобрался: HTTP '+r.status));return}
  aiIntake=data;renderAiIntake(data);
 }catch(e){thinking.remove();appendAiMessage('system','Документ не разобрался: '+(e.message||e))}
 finally{document.getElementById('aiFile').value='';aiBusy=false;aiSendBtn.disabled=false;aiFileBtn.disabled=false}
}
function renderAiIntake(data){
 const doc=data.document||{};
 const box=document.createElement('div');box.className='ai-msg system';
 let html='<b>'+aiEsc(doc.filename||'документ')+'</b>';
 if(doc.pages)html+=' <span style="color:#888">· страниц '+aiEsc(doc.pages)+'</span>';
 // Скан — не пустой документ. Выдать «ничего не нашли» за «там ничего нет»
 // значит соврать про источник.
 const note=data.reason||doc.reason||'';
 if(note)html+='<div style="margin-top:6px;color:#8a4b08">'+aiEsc(note)+'</div>';
 const fields=data.fields||[];
 if(fields.length){
  html+='<div style="margin-top:8px"><table style="width:100%;border-collapse:collapse;font-size:12px">'
   +'<tr><th></th><th style="text-align:left">Поле</th><th style="text-align:left">Значение</th><th style="text-align:left">Откуда взято</th></tr>';
  fields.forEach((f,i)=>{html+='<tr>'
   +'<td><input type="checkbox" class="ai-intake-pick" data-key="'+aiEsc(f.key)+'" checked></td>'
   +'<td>'+aiEsc(f.key)+'</td>'
   +'<td><b>'+aiEsc(f.value)+'</b> '+aiEsc(f.unit||'')+'</td>'
   +'<td style="color:#666">'+(doc.recognized?'распознано: ':'')+'«'+aiEsc(f.quote)+'»</td></tr>'});
  html+='</table><button class="btn dark" style="margin-top:8px" onclick="applyAiIntake()">Применить отмеченное</button></div>';
 }
 (data.questions||[]).forEach(q=>{
  html+='<div style="margin-top:8px"><b>Вопрос:</b> '+aiEsc(q.question)+'</div>';
  if((q.options||[]).length)html+='<div style="color:#666;font-size:12px">'+q.options.map(aiEsc).join(' · ')+'</div>';
 });
 (data.notes||[]).forEach(note=>{html+='<div style="margin-top:6px;color:#666;font-size:12px">'+aiEsc(note)+'</div>'});
 // Отброшенное называется вслух: молча пропущенное поле читается как
 // «в документе такого нет».
 (data.dropped||[]).forEach(line=>{html+='<div style="margin-top:4px;color:#8a4b08;font-size:12px">Не взято — '+aiEsc(line)+'</div>'});
 if(!fields.length&&!(data.questions||[]).length&&!note)html+='<div style="margin-top:6px">В документе не нашлось полей, которые понимает модель.</div>';
 box.innerHTML=html;aiMessages.appendChild(box);aiMessages.scrollTop=aiMessages.scrollHeight;
}
async function applyAiIntake(){
 if(!aiIntake)return;
 const accept=Array.from(document.querySelectorAll('.ai-intake-pick:checked')).map(el=>el.dataset.key);
 if(!accept.length){appendAiMessage('system','Ничего не отмечено — применять нечего.');return}
 try{
  const r=await fetch('/agent/document',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({filename:(aiIntake.document||{}).filename||'',accept,extraction:aiIntake,
    inputs,tep,session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await r.json().catch(()=>({}));
  if(!r.ok){appendAiMessage('system',data.detail||'Не применилось');return}
  Object.assign(inputs,data.inputs||{});
  Object.keys(data.tep||{}).forEach(key=>{tep[key]=Object.assign(tep[key]||{},data.tep[key])});
  syncTep(false);renderInputs();renderTep();calculate();
  // Имя поля, а не ключ, и рядом — как значение было написано в документе:
  // молчаливый перевод единиц («1 650 000 000 ₽» → 1650 млн ₽) неотличим от
  // ошибки переписывания, а неприменённое без причины — от непрочитанного.
  const lines=(data.applied||[]).map(a=>(a.label||a.key)+': '+(a.was===undefined?'—':a.was)
   +' → '+a.now+(a.unit?' '+a.unit:'')+(a.as_written?' (в документе: '+a.as_written+')':''));
  (data.refused||[]).forEach(x=>lines.push('не применено — '+(x.label||x.key)+': '+x.reason));
  appendAiMessage('system','Подставлено:\n'+lines.join('\n'));
 }catch(e){appendAiMessage('system','Не применилось: '+(e.message||e))}
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
   response=await fetch('/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,scenario:scenario||'',trace_id:traceId,inputs,tep,rates,phasing,history:aiHistory.slice(-8),selected_view:reportView||'all',session:activeSession(),access_key:projectsAdminKey||''})});
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
   appendAiMessage('assistant',String(data.detail||'Платон доступен после входа через Telegram.'),'error');
   appendAiLoginButton();
   return;
  }
  if(!response.ok)throw new Error(data.detail||AI_UNAVAILABLE);
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
