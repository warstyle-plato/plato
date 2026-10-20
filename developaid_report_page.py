"""Страница «Сводка руководству» — отдельно от Монитора стройки.

«Я бы делал вообще этот раздел в мониторе отдельной страницей. Не смешивая
со стройкой» (владелец, 20.10.2026). Вход — в разделе «Строителю» контура,
рядом с Монитором. Здесь же живут записи «Общая информация по проекту»: они
часть сводки, а не данных стройки.

Стиль — тот же, что у Монитора: блок `<style>` берётся с его страницы, а не
копируется, иначе две страницы одного раздела однажды разошлись бы. Вход —
та же сессия Telegram (`developaid_web_session`), что у Монитора: вошёл там —
вошёл и здесь.

Числа считает сервер (`/monitor/report`), страница только показывает
готовую разметку; PDF печатает сервер (`/monitor/report.pdf`).
"""

from __future__ import annotations

from developaid_monitor_page import MONITOR_PAGE as _MONITOR

_STYLE = _MONITOR[_MONITOR.index("<style>") + len("<style>"):_MONITOR.index("</style>")]

REPORT_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · Сводка руководству</title>
<style>""" + _STYLE + """
#reportBox{background:#fff;padding:14px 18px;border:1px solid var(--line);border-radius:10px;margin-top:10px}
#reportBox h1{font-size:18px;margin:0 0 2px}#reportBox h2{font-size:14px;margin:18px 0 6px;border-bottom:1px solid #d6dde6;padding-bottom:3px}
#reportBox table{border-collapse:collapse;width:100%;margin:4px 0}#reportBox th,#reportBox td{border:1px solid #d6dde6;padding:4px 6px;text-align:right}
#reportBox th:first-child,#reportBox td:first-child{text-align:left}#reportBox th{background:#f2f5f8}
#reportBox .finding{border-left:3px solid #1f4e8c;padding:5px 9px;margin:7px 0;background:#f6f8fb}
#reportBox .finding.bad{border-left-color:#b2541a;color:inherit}#reportBox .sub{color:#5b6b7d;font-size:12px}#reportBox .finding.missing{border-left-color:#9aa5b1;color:#5b6b7d}
#reportBox .finding b{display:block}#reportBox .source,#reportBox .note{color:#6b7785;font-size:11px}
#reportBox .missing{color:#9a5b00;font-style:italic}#reportBox figure.chart{margin:8px 0;max-width:760px}
#reportBox figcaption{font-weight:600;font-size:12px}
.files{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
</style>
</head>
<body>
<div class="wrap">
__DEVELOPAID_CONTOUR__
<div class="top"><div><h1 style="margin:0">Сводка руководству</h1><div class="muted">Стройка, продажи, финансирование и бюджет за неделю или за месяц — для решений и рассылки</div></div>
<div class="files"><div class="field"><label>Проект</label><input id="project" placeholder="Название проекта в Мониторе"></div><div class="field"><label>Дата сводки</label><input id="cut" type="date"></div><div class="field"><label>Период</label><select id="reportKind"><option value="week">За неделю</option><option value="month">За месяц</option></select></div><div class="field"><label>Проект в отчёте о продажах</label><input id="reportSales" placeholder="как он назван там" title="Как проект называется в «Отчёте о продажах». Пусто — продажи и эскроу в сводку не попадут."></div><button class="btn" id="reportBtn">Показать</button><button class="btn alt" id="reportPdfBtn">Скачать PDF</button></div></div>
<div class="card auth-card" id="loginBox"><div class="body" style="padding:12px 14px"><b>Вход</b><div class="muted">Войдите через Telegram тем же аккаунтом DevelopAid, что и в Мониторе.</div><div class="files" style="margin-top:10px"><button class="btn" id="loginBtn">Войти через Telegram</button><button class="btn ghost" id="keyBtn">Ключ администратора</button></div><div class="msg" id="loginMsg"></div></div></div>
<div id="privateArea" class="hidden">
<div class="msg" id="reportMsg"></div>
<div id="reportBox"><p class="muted">Укажите проект и нажмите «Показать».</p></div>
<div class="card" id="notesCard"><div class="body" style="padding:12px 14px"><h2 style="margin:0 0 4px;font-size:15px">Общая информация по проекту</h2><div class="muted">Арбитражи, споры, решения собственника — то, чего нет в РСС и ГПР. Открытые вопросы и закрытые за период попадают в сводку. <span id="notesState"></span></div><div id="notesList" style="margin-top:8px"></div><div class="files" style="margin-top:8px"><input id="noteTopic" placeholder="Тема, например: арбитраж с подрядчиком" style="width:260px"><input id="noteText" placeholder="Что произошло и что дальше" style="width:360px"><button class="btn alt" id="noteAddBtn">Добавить запись</button></div><div class="msg" id="notesMsg"></div></div></div>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function dt(v){if(!v)return '—';const d=new Date(v);return isNaN(d)?v:d.toLocaleDateString('ru-RU')}
function msg(id,t,cls=''){const e=$(id);if(!e)return;e.textContent=t;e.className='msg '+cls}
const WEB_SESSION_KEY='developaid_web_session',ADMIN_KEY='plato_projects_key';
function readStorage(...keys){try{for(const k of keys){const v=localStorage.getItem(k);if(v)return v}}catch(e){}return ''}
function session(){return readStorage(WEB_SESSION_KEY,'session','developaid_session')}
function adminKey(){return readStorage(ADMIN_KEY,'key','developaid_key')}
function hasAuth(){return !!(session()||adminKey())}
function auth(){return{session:session(),key:adminKey()}}
function syncAuthUi(){const yes=hasAuth();$('loginBox').classList.toggle('hidden',yes);$('privateArea').classList.toggle('hidden',!yes);return yes}
function requireLogin(text='Войдите через Telegram, чтобы открыть сводку.'){$('loginBox').classList.remove('hidden');$('privateArea').classList.add('hidden');msg('loginMsg',text,'bad')}
async function post(path,p){const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(Object.assign(auth(),p||{}))}),d=await r.json().catch(()=>({}));if(r.status===401)requireLogin();if(!r.ok)throw new Error(d.detail||('Ошибка '+r.status));return d}
function remember(key,value){try{localStorage.setItem(key,value)}catch(e){}}
function recall(key){try{return localStorage.getItem(key)||''}catch(e){return ''}}
function reportSalesKey(){return 'mgmt_sales_project:'+$('project').value.trim()}
function reportPayload(){const sales=$('reportSales').value.trim();remember(reportSalesKey(),sales);remember('mgmt_report_project',$('project').value.trim());return {project:$('project').value.trim(),kind:$('reportKind').value,end:$('cut').value||'',sales_project:sales}}
async function renderReport(){const p=$('project').value.trim();if(!p)return msg('reportMsg','Укажите проект — как он назван в Мониторе.','bad');if(!$('reportSales').value)$('reportSales').value=recall(reportSalesKey());msg('reportMsg','Собираю сводку…','warn');try{const r=await post('/monitor/report',reportPayload());$('reportBox').innerHTML=r.html;msg('reportMsg','','')}catch(e){msg('reportMsg',e.message,'bad')}renderNotes()}
async function renderNotes(){const p=$('project').value.trim();if(!p)return;try{drawNotes(await post('/monitor/notes',{project:p}))}catch(e){msg('notesMsg',e.message,'bad')}}
function drawNotes(r){const list=r.notes||[],names=r.statuses||{};$('notesState').textContent=list.length?`Открытых вопросов: ${list.filter(n=>n.status==='open').length} из ${list.length}.`:'';$('notesList').innerHTML=list.length?list.map(n=>`<div class="note" data-id="${esc(n.id)}" style="border-top:1px solid #e5e7eb;padding:6px 0"><b>${esc(n.topic)}</b> · <span class="muted">${esc(names[n.status]||n.status)}</span><div>${esc(n.text)}</div><div class="muted" style="font-size:11px">${dt(n.at)} · ${esc(n.author)}${n.version>1?` · правок: ${n.version-1}, создал ${esc(n.created_by)} ${dt(n.created_at)}`:''}</div><div class="files"><input class="noteNew" placeholder="Новое состояние вопроса" style="width:300px"><button class="btn alt noteSave">Обновить</button><button class="btn alt noteToggle">${n.status==='open'?'Закрыть вопрос':'Открыть снова'}</button></div></div>`).join(''):'<div class="muted">Записей пока нет. Добавьте первую ниже.</div>';$('notesList').querySelectorAll('.note').forEach(box=>{const id=box.dataset.id,n=list.find(x=>x.id===id);box.querySelector('.noteSave').onclick=()=>noteSend({note_id:id,text:box.querySelector('.noteNew').value.trim()});box.querySelector('.noteToggle').onclick=()=>noteSend({note_id:id,status:n.status==='open'?'closed':'open'})})}
async function noteSend(extra){try{drawNotes(await post('/monitor/notes',Object.assign({project:$('project').value.trim()},extra)));msg('notesMsg','Запись сохранена.','good');return true}catch(e){msg('notesMsg',e.message,'bad');return false}}
$('noteAddBtn').onclick=async()=>{if(await noteSend({topic:$('noteTopic').value.trim(),text:$('noteText').value.trim()})){$('noteTopic').value='';$('noteText').value=''}};
$('reportBtn').onclick=()=>renderReport();
$('reportKind').onchange=()=>renderReport();
$('reportPdfBtn').onclick=async()=>{const btn=$('reportPdfBtn');btn.disabled=true;msg('reportMsg','Печатаю PDF — обычно до двадцати секунд.','warn');try{const r=await fetch('/monitor/report.pdf',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(Object.assign(auth(),reportPayload()))});if(r.status===401)requireLogin();if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.detail||('Не удалось напечатать PDF: ошибка '+r.status))}const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`Сводка ${$('project').value.trim()} ${$('cut').value||''}.pdf`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),60000);msg('reportMsg','PDF скачан.','good')}catch(e){msg('reportMsg',e.message,'bad')}finally{btn.disabled=false}};
$('loginBtn').onclick=async()=>{msg('loginMsg','Открываю Telegram…','good');try{const r=await fetch('/auth/telegram/start',{method:'POST'}),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Вход через Telegram недоступен');if(d.link)window.open(d.link,'_blank');for(let i=0;i<60;i++){await new Promise(ok=>setTimeout(ok,2000));const c=await fetch('/auth/telegram/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:d.code})}),cd=await c.json().catch(()=>({}));if(c.ok&&cd.session){remember(WEB_SESSION_KEY,cd.session);syncAuthUi();return}}throw new Error('Подтверждение не пришло за 2 минуты.')}catch(e){msg('loginMsg',e.message,'bad')}};
$('keyBtn').onclick=()=>{const k=prompt('Ключ администратора');if(!k)return;remember(ADMIN_KEY,k.trim());syncAuthUi()};
$('cut').value=new Date().toISOString().slice(0,10);
$('project').value=recall('mgmt_report_project');
if(syncAuthUi()&&$('project').value)renderReport();else if(!hasAuth())msg('loginMsg','Войдите через Telegram, чтобы открыть сводку.','bad');
</script>
</body></html>
"""
