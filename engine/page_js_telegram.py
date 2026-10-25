"""Кусок страницы PAGE: Скрипт, конец: запуск из Telegram (сессия, правки, возврат
результата) и initializeApp; закрывает страницу.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_telegram")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""async function loadTelegramSessionData(){
 if(!telegramSession)return {};
 const response=await fetch('/telegram/session-data',{
  method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({session:telegramSession})
 });
 const payload=await response.json();
 if(!response.ok)throw new Error(payload.detail||'Telegram-сессия недействительна');
 return payload||{};
}

// Тот ли это проект, что в открытой карточке. Сверяем площадь квартир и
// территории: если совпали, в браузере лежит состояние этого же расчёта — его
// и оставляем, чтобы не потерять настроенную очерёдность и правки вводных.
function telegramStateMatches(manual){
 if(!manual||!manual.tep)return false;
 const near=(a,b)=>{
  a=Number(a||0);b=Number(b||0);
  if(!a&&!b)return true;
  return Math.abs(a-b)<=Math.max(1,Math.abs(a)*0.001);
 };
 const theirs=(manual.tep.apartments&&manual.tep.apartments.saleable)||0;
 const ours=(tep.apartments&&tep.apartments.saleable)||0;
 return near(theirs,ours)&&near(manual.site_area_ha,inputs.site_area_ha);
}

async function applyTelegramManualTep(manual,options){
 const silent=!!(options&&options.silent);
 if(!manual||!manual.tep)return false;
 resetTerritoryData();
 Object.assign(inputs,manual.inputs||{});
 {
  const manualArea=Number(manual.site_area_ha||0);
  if(manualArea>0)inputs.site_area_ha=manualArea;
 }
 Object.entries(manual.tep||{}).forEach(([key,values])=>{
  if(tep[key])Object.assign(tep[key],values||{});
 });
 inputs._manual_tep_import={
  project_name:String(manual.project_name||''),
  site_area_ha:Number(manual.site_area_ha||0),
  source:manual.source||{}
 };
 syncTep(false);
 // Участки пришедшего проекта показываем сразу: иначе поле остаётся пустым или,
 // хуже, с номерами прошлого расчёта, и непонятно, что именно посчитано.
 const numbers=((manual.source||{}).cadastral_numbers)||[];
 writeCadastralField(numbers.join(', '));
 const preview=document.getElementById('cadastralPreview');
 if(preview){preview.innerHTML='';preview.style.display='none';}
 if(typeof cadastralStatus!=='undefined'&&cadastralStatus){
  cadastralStatus.innerHTML=numbers.length
   ? '<span class="import-ok">Участков в расчёте: '+numbers.length+'.</span> Территория пришла из Telegram вместе с ТЭП.'
   : '';
 }
 const moStatus=document.getElementById('moStatus');
 if(moStatus)moStatus.style.display='none';
 renderInputs();
 renderTep();
 renderPhasing();
 openTab('tep');
 const status=document.getElementById('glavapuStatus');
 if(status)status.innerHTML='<span class="import-ok">Ручной ТЭП из Telegram загружен в модель. Проверьте таблицу; финансовые вводные сохранены отдельно.</span>';
 await calculate();
 // В режиме правки отправлять нечего: пользователь ещё ничего не менял, и
 // карточка в чате уже есть — та самая, по которой он и нажал «изменить».
 if(!silent)await sendTelegramResult();
 return true;
}


let telegramEditSubmitting=false;

async function submitTelegramEditedResult(){
 if(telegramEditSubmitting)return;
 telegramEditSubmitting=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 try{
  if(tg&&tg.MainButton){tg.MainButton.disable();tg.MainButton.setText('Обновляю расчёт…')}
  await calculate();
  persistLocalSilently();
  telegramResultSent=false;
  await sendTelegramResult();
  if(!telegramResultSent)throw new Error('Не удалось отправить обновлённый расчёт в Telegram');
  finishTelegramSession('Обновлённый расчёт отправлен в чат.');
 }catch(e){
  const status=document.getElementById('glavapuStatus');
  if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  if(tg&&tg.MainButton){tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}
 }finally{
  telegramEditSubmitting=false;
 }
}

// Расчёт по кадастру и Подмосковью закрывал окно только на пути ГлавАПУ, а на
// остальных мини-приложение оставалось висеть поверх уже готовой карточки в
// чате — человек не понимал, что расчёт закончен, и ждал, что от него ещё
// чего-то хотят. Показываем это прямо и уходим.
let telegramFinishing=false;
function finishTelegramSession(note){
 if(telegramFinishing)return;
 telegramFinishing=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(tg&&tg.MainButton){try{tg.MainButton.hide()}catch(e){}}
 const banner=document.createElement('div');
 banner.id='telegramDoneBanner';
 banner.style.cssText='position:fixed;inset:0;z-index:99999;background:#ffffff;'
  +'display:flex;flex-direction:column;align-items:center;justify-content:center;'
  +'gap:10px;padding:24px;text-align:center;font-weight:700;font-size:18px';
 banner.innerHTML='<div style="font-size:34px">✓</div>'
  +'<div>Расчёт завершён</div>'
  +'<div style="font-weight:400;font-size:14px;color:#666">'
  +escapeHtml(note||'Результат отправлен в чат. Окно закроется само.')+'</div>';
 document.body.appendChild(banner);
 if(tg&&tg.HapticFeedback){try{tg.HapticFeedback.notificationOccurred('success')}catch(e){}}
 // Полторы секунды — чтобы надпись успели прочитать, но не ждали.
 setTimeout(()=>{if(tg&&tg.close)tg.close()},1500);
}

// Кнопка нужна в любом режиме, а не только в режиме редактирования: результат
// уходит в Telegram один раз, и без неё правка любого параметра в открытой
// модели уже никогда не доезжает до чата.
function showTelegramResendButton(){
 if(!telegramSession)return;
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(tg&&tg.MainButton){
  tg.MainButton.setText('Обновить расчёт в Telegram');
  tg.MainButton.show();
  tg.MainButton.enable();
  if(!showTelegramResendButton.bound){
   tg.MainButton.onClick(submitTelegramEditedResult);
   showTelegramResendButton.bound=true;
  }
  return;
 }
 if(document.getElementById('telegramEditSubmit'))return;
 const btn=document.createElement('button');
 btn.id='telegramEditSubmit';
 btn.className='btn';
 btn.textContent='Обновить расчёт в Telegram';
 btn.style.cssText='position:fixed;left:16px;right:16px;bottom:16px;z-index:9999;padding:14px;font-weight:700';
 btn.onclick=submitTelegramEditedResult;
 document.body.appendChild(btn);
}

function setupTelegramEditSubmit(){
 const status=document.getElementById('glavapuStatus');
 if(status)status.innerHTML='<span class="import-ok"><b>Режим редактирования.</b> Изменения сразу пересчитываются в модели. После завершения нажмите «Обновить расчёт в Telegram» внизу.</span>';
 showTelegramResendButton();
}

// Мини-приложение висело на «Считаю…» после переноса тизера из бота
// (владелец, 31.08.2026). Полоса ставится перед расчётом и снимается ПОСЛЕ
// него строкой ниже — а если расчёт бросил, до этой строки не доходит вовсе, и
// окно замирает навсегда. Обёртка снимает полосу при любом исходе и называет
// причину: замершее окно не говорит человеку ничего, а ошибка говорит.
async function initializeTelegramLaunch(){
 try{
  return await runTelegramLaunch();
 }catch(e){
  telegramProgress('');
  const status=document.getElementById('glavapuStatus');
  const why=escapeHtml(String((e&&e.message)||e||'причина не названа'));
  if(status)status.innerHTML='<span class="import-error">Расчёт из чата не прошёл: '+why+'</span>';
  const tg=window.Telegram&&window.Telegram.WebApp;
  if(tg&&tg.MainButton){try{tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}catch(err){}}
 }
}

async function runTelegramLaunch(){
 if(window.Telegram&&window.Telegram.WebApp){
  window.Telegram.WebApp.ready();
  window.Telegram.WebApp.expand();
 }
 let sessionData={};
 if(telegramSession){
  try{
   sessionData=await loadTelegramSessionData();
   telegramCalcOverrides=sessionData.calc_overrides||{};
  }catch(e){
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
   return;
  }
 }
 if(telegramMode==='edit'){
  // Открываем проект из той карточки, по которой нажали «изменить». Раньше
  // бралось только сохранённое в браузере состояние, и если расчёт делал бот
  // на сервере — по Подмосковью или по адресу, — браузер его никогда не видел
  // и показывал чужой прошлый проект. Тяжёлый расчёт при этом не перезапускаем:
  // ТЭП приходит в самой сессии готовым.
  if(sessionData.manual_tep&&!telegramStateMatches(sessionData.manual_tep)){
   await applyTelegramManualTep(sessionData.manual_tep,{silent:true});
  }
  applyTelegramCalcOverrides();
  renderInputs();
  renderTep();
  renderPhasing();
  syncProjectClassSelector();syncProjectKindSelector();
  openTab('inputs');
  telegramProgress('Считаю…');
  await calculate();
  telegramProgress('');
  setupTelegramEditSubmit();
  return;
 }
 if(telegramMode==='intake'){
  // Тизер без кадастрового номера: «Всё верно, считать» в чате. Расчёт —
  // умолчания движка и ровно строки карточки разбора, без остатков прежнего
  // проекта из WebView (как и экспресс-расчёт по участку).
  resetAll();
  applyTelegramCalcOverrides();
  renderInputs();renderTep();renderPhasing();
  syncProjectClassSelector();syncProjectKindSelector();
  openTab('inputs');
  telegramProgress('Считаю…');
  await calculate();
  telegramProgress('');
  const status=document.getElementById('glavapuStatus');
  if(status)status.innerHTML='<span class="import-ok"><b>Расчёт по карточке тизера готов.</b> Значения тизера стоят во вводных, у каждого подписано, откуда оно взято. Остальное — умолчания модели.</span>';
  return;
 }
 if(telegramCad){
  const field=document.getElementById('cadastralNumbers');
  if(!field)return;
  // Экспресс-расчёт из чата обещает ровно «класс + цены + СМР», остальное —
  // умолчания движка. Сохранённый в WebView проект сюда не допускается:
  // браузер бота однажды запомнил старую структуру расходов (сети 7,5 вместо
  // 10,25, проектирование 5 вместо 14,5) и два миллиарда собственных средств
  // чужого эксперимента — и каждый «адрес + класс» из бота молча считался с
  // ними, расходясь с сайтом на одинаковых вводных. Правки после расчёта
  // живут в режиме редактирования — он открывает проект своей карточки.
  resetAll();
  writeCadastralField(telegramCad);
  openTab('inputs');
  const status=document.getElementById('cadastralStatus');
  if(status)status.textContent='Получаю ТЭП ГлавАПУ и рассчитываю проект…';
  telegramProgress('Считаю…');
  // Применяется и уходит в чат ТОЛЬКО результат этого запуска. Проверка
  // глобального glavapuImport здесь была гонкой: renderStoredGlavapu на
  // старте поднимал импорт из сохранённого проекта, и после таймаута сбора
  // мини-приложение показывало ошибку — а затем «Готов. Отправляю в чат…»
  // со старым ТЭП, как будто расчёт удался.
  const payload=await obtainCadastralTep();
  const usable=payload&&payload.mappings&&(
   Object.keys(payload.mappings.inputs||{}).length||Object.keys(payload.mappings.tep||{}).length)
   &&Number((payload.normalized||{}).site_area_ha||0)>0;
  if(usable){
   // Закрытие после успешной отправки делает сам sendTelegramResult: путь один
   // на все источники, иначе часть расчётов снова осталась бы висеть.
   glavapuImport=payload;
   await applyGlavapu();
  }else{
   telegramProgress('');
   finishTelegramSession('ТЭП не получен: '+(payload?'в ответе нет обязательных полей.':'территория или расчёт не отработали.')+' Проверьте кадастровые номера и повторите из чата.');
  }
  return;
 }
 if(sessionData.manual_tep){
  // Присланный в чат ТЭП — тоже экспресс-расчёт: финансовые предпосылки в нём
  // задаёт бот, всё незаданное — умолчания движка, а не остатки прежнего
  // проекта из WebView.
  resetAll();
  await applyTelegramManualTep(sessionData.manual_tep);
 }
}
async function initializeApp(){
 repairParkingFromGlavapu();
 renderInputs();
 renderTep();
 renderStoredGlavapu();
 renderStoredCadastral();
 renderStoredLand();
 renderStoredMo();
 renderScenarioNote();
 syncProjectClassSelector();syncProjectKindSelector();
 renderPhasing();
 inputs.rate_scenario=inputs.rate_scenario||'base';
 syncRateControlsFromInputs();
 generateRateCurve();
 renderRates();
 await refreshCurrentKeyRate(false);
 await calculate();
 await refreshAgentStatus();
 await loadMoReference();
 await initializeTelegramLaunch();
 // Докуда дошла загрузка — это ответ ловушке ошибок, а не украшение: у
 // сообщения из чужого скрипта места в нашем коде нет, и единственное, что
 // мы можем сказать честно, — загрузились мы к тому моменту или нет.
 window.__developaidBooted=true;
}
initializeApp();
</script>
</body></html>"""
