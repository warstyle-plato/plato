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

import re

from developaid_management_report import REPORT_STYLE
from developaid_monitor_page import MONITOR_PAGE as _MONITOR

_STYLE = _MONITOR[_MONITOR.index("<style>") + len("<style>"):_MONITOR.index("</style>")]


def _scoped(style: str, scope: str) -> str:
    """Стиль документа сводки внутри ``scope``: тот же, что печатается в PDF.

    Документ рисует сервер одной разметкой для страницы и PDF; если бы у
    страницы был свой список правил, плитки и цвета отклонений однажды
    разошлись бы с PDF.
    """
    out = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        names = [name.strip() for name in selectors.split(",")]
        out.append(",".join(scope if name == "body" else f"{scope} {name}" for name in names)
                   + "{" + body + "}")
    return "\n".join(out)


REPORT_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · Сводка руководству</title>
<style>""" + _STYLE + """
""" + _scoped(REPORT_STYLE, "#reportBox") + """
#reportBox{background:#fff;padding:14px 18px;border:1px solid var(--line);border-radius:10px;margin-top:10px;max-width:980px}
#reportBox .finding.bad{color:inherit}#reportBox .pagebreak{height:0}
@media (max-width:700px){#reportBox .tiles{grid-template-columns:repeat(2,1fr)}}
.files{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.photo-pick{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-top:8px}
.photo-pick label{display:block;border:2px solid #d6dde6;border-radius:8px;padding:4px;cursor:pointer;font-size:11px}
.photo-pick label.on{border-color:#1f4e8c;background:#eef3fa}.photo-pick img{width:100%;height:110px;object-fit:cover;border-radius:5px;display:block;background:#f2f5f8}
</style>
</head>
<body>
<div class="wrap">
__DEVELOPAID_CONTOUR__
<div class="top"><div><h1 style="margin:0">Сводка руководству</h1><div class="muted">Стройка, продажи, финансирование и бюджет за неделю или за месяц — для решений и рассылки</div></div>
<div class="files"><div class="field"><label>Проект</label><select id="project"><option value="">Загружаю список проектов…</option></select></div><div class="field"><label>Дата сводки</label><input id="cut" type="date"></div><div class="field"><label>Период</label><select id="reportKind"><option value="week">За неделю</option><option value="month">За месяц</option></select></div><div class="field" id="salesField"><label>Проект в отчёте о продажах</label><div id="salesLinked" class="hidden" style="padding-top:6px"><span id="salesName"></span> <button class="btn ghost" id="salesChange" type="button" title="Выбрать другой проект из отчёта о продажах">Сменить</button></div><select id="reportSales" class="hidden" title="Выбор запоминается на сервере для всех, кто открывает сводку этого проекта."></select></div><button class="btn" id="reportBtn">Показать</button><button class="btn alt" id="reportPdfBtn">Скачать PDF</button></div></div>
<div class="card auth-card" id="loginBox"><div class="body" style="padding:12px 14px"><b>Вход</b><div class="muted">Войдите через Telegram тем же аккаунтом DevelopAid, что и в Мониторе.</div><div class="files" style="margin-top:10px"><button class="btn" id="loginBtn">Войти через Telegram</button><button class="btn ghost" id="keyBtn">Ключ администратора</button></div><div class="msg" id="loginMsg"></div></div></div>
<div id="privateArea" class="hidden">
<div class="msg" id="reportMsg"></div>
<div id="reportBox"><p class="muted">Выберите проект и нажмите «Показать».</p></div>
<div class="card" id="mailingCard"><div class="body" style="padding:12px 14px"><h2 style="margin:0 0 4px;font-size:15px">Рассылка руководству</h2><div class="muted">Сводка приходит в Telegram сообщением и PDF: за неделю — по понедельникам, за месяц — 1-го числа, в 9:00 по Москве. Получатель подписывается сам: отправьте ему ссылку-приглашение, он откроет её и нажмёт «Старт» в боте. <span id="mailingNext"></span></div><div id="mailingLink" style="margin-top:8px"></div><div class="files" style="margin-top:6px"><button class="btn alt" id="mailingInviteBtn">Создать ссылку-приглашение</button></div><div id="mailingList" style="margin-top:8px"></div><div class="msg" id="mailingMsg"></div></div></div>
<div class="card" id="photosCard"><div class="body" style="padding:12px 14px"><h2 style="margin:0 0 4px;font-size:15px">Фото со стройки</h2><div class="muted">Фото из чата стройки за период сводки. Отметьте те, что нужно показать руководству: в сводку попадают только отмеченные. <span id="photosState"></span></div><div id="photosList" class="photo-pick"></div><div class="msg" id="photosMsg"></div></div></div>
<div class="card" id="notesCard"><div class="body" style="padding:12px 14px"><h2 style="margin:0 0 4px;font-size:15px">Общая информация по проекту</h2><div class="muted">Арбитражи, споры, решения собственника — то, чего нет в РСС и ГПР. Открытые вопросы и закрытые за период попадают в сводку. <span id="notesState"></span></div><div id="notesList" style="margin-top:8px"></div><div class="files" style="margin-top:8px"><input id="noteTopic" placeholder="Тема, например: арбитраж с подрядчиком" style="width:260px"><input id="noteText" placeholder="Что произошло и что дальше" style="width:360px"><button class="btn alt" id="noteAddBtn">Добавить запись</button></div><div class="msg" id="notesMsg"></div></div></div>
<div class="card hidden" id="mergeCard"><div class="body" style="padding:12px 14px"><h2 style="margin:0 0 4px;font-size:15px">Один проект под двумя именами</h2><div class="muted">Если файлы одного проекта загружали под разными названиями, сводка по каждому имени видит только свою часть. Объединение переносит в главный проект всё, чего в нём нет, и ничего в нём не перезаписывает; старое имя продолжает работать и ведёт в главный.</div><div class="files" style="margin-top:8px"><div class="field"><label>Перенести из</label><select id="mergeSource"></select></div><div class="field"><label>В главный проект</label><select id="mergeTarget"></select></div><button class="btn alt" id="mergeCheckBtn">Проверить, что перенесётся</button><button class="btn" id="mergeApplyBtn" disabled>Объединить</button></div><div id="mergePlan" style="margin-top:8px"></div><div class="msg" id="mergeMsg"></div></div></div>
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
let projectList=[],salesList=[];
const sameName=(a,b)=>String(a||'').toLowerCase().replace(/[\\s-]+/g,' ').trim()===String(b||'').toLowerCase().replace(/[\\s-]+/g,' ').trim();
function currentProject(){return projectList.find(x=>x.project===$('project').value)}
function drawProjects(r,want){projectList=r.projects||[];salesList=r.sales_projects||[];want=want||recall('mgmt_report_project');$('project').innerHTML=projectList.length?projectList.map(x=>`<option value="${esc(x.project)}">${esc(x.project)}</option>`).join(''):'<option value="">В Мониторе пока нет проектов</option>';const hit=projectList.find(x=>x.project===want)||projectList.find(x=>sameName(x.project,want));if(hit)$('project').value=hit.project;drawSalesLink(false);drawMerge()}
function drawSalesLink(changing){const p=currentProject(),link=p?p.sales:null,choose=!!p&&(changing||!link);$('salesLinked').classList.toggle('hidden',!p||choose);$('reportSales').classList.toggle('hidden',!choose);if(link)$('salesName').textContent=link.sales_project?`«${link.sales_project}»`:'продажи в сводку не входят';$('reportSales').innerHTML='<option value="">— выберите проект —</option>'+salesList.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('')+'<option value="__none__">Продаж по этому проекту в сводке не нужно</option>';$('reportSales').value=link?(link.sales_project||'__none__'):''}
function drawMerge(){$('mergeCard').classList.toggle('hidden',projectList.length<2);const opts=projectList.map(x=>`<option value="${esc(x.project)}">${esc(x.project)}</option>`).join(''),now=$('project').value;$('mergeSource').innerHTML=opts;$('mergeTarget').innerHTML=opts;const other=projectList.find(x=>x.project!==now);if(other)$('mergeSource').value=other.project;if(now)$('mergeTarget').value=now;$('mergeApplyBtn').disabled=true;$('mergePlan').innerHTML=''}
function mergeWords(r){const c=r.counts||{},n=k=>c[k]||0;let t=`<div>Из «${esc(r.source)}» в «${esc(r.target)}»: перенесётся файлов — ${n('move')}; уже есть такие же — ${n('same')}; журналы, которые дополнятся записями, — ${n('append')}; дни ручных отметок по работам, которые сольются, — ${n('combine')}.</div>`;if(n('conflict'))t+=`<div class="msg warn">Разные файлы с одним именем — ${n('conflict')}: главный проект их не потеряет, а файлы из «${esc(r.source)}» лягут рядом для проверки: ${(r.conflicts||[]).map(esc).join(', ')}.</div>`;return t}
async function mergeRun(apply){const source=$('mergeSource').value,target=$('mergeTarget').value;if(source===target)return msg('mergeMsg','Выберите два разных проекта.','bad');if(apply&&!confirm(`Объединить «${source}» с «${target}»? Главным останется «${target}».`))return;try{msg('mergeMsg',apply?'Объединяю…':'Проверяю…','warn');const r=await post('/monitor/merge',{source,target,apply});$('mergePlan').innerHTML=mergeWords(r);if(apply){drawProjects(await post('/monitor/report/projects',{}),target);msg('mergeMsg',`Готово: «${source}» теперь ведёт в «${target}».`+(r.subscribers_moved?` Получателей рассылки перешло: ${r.subscribers_moved}.`:''),'good');renderReport()}else{$('mergeApplyBtn').disabled=false;msg('mergeMsg','','')}}catch(e){msg('mergeMsg',e.message,'bad')}}
$('mergeCheckBtn').onclick=()=>mergeRun(false);$('mergeApplyBtn').onclick=()=>mergeRun(true);$('mergeSource').onchange=$('mergeTarget').onchange=()=>{$('mergeApplyBtn').disabled=true;$('mergePlan').innerHTML=''};
async function loadProjects(){try{drawProjects(await post('/monitor/report/projects',{}));if(!projectList.length)msg('reportMsg','В Мониторе пока нет проектов. Загрузите РСС или график работ на странице Монитора — проект появится в списке.','warn');return projectList.length>0}catch(e){msg('reportMsg',e.message,'bad');return false}}
function reportPayload(){remember('mgmt_report_project',$('project').value);return {project:$('project').value,kind:$('reportKind').value,end:$('cut').value||''}}
async function renderReport(quiet){const p=$('project').value;if(!p)return msg('reportMsg','Выберите проект в списке.','bad');msg('reportMsg','Собираю сводку…','warn');try{const r=await post('/monitor/report',reportPayload());$('reportBox').innerHTML=r.html;msg('reportMsg','','')}catch(e){msg('reportMsg',e.message,'bad')}renderNotes();loadMailing();if(!quiet)loadPhotos()}
const photoUrls={};
async function photoSrc(id){if(photoUrls[id])return photoUrls[id];const r=await fetch('/monitor/photo',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(Object.assign(auth(),{project:$('project').value.trim(),photo_id:id}))});if(!r.ok)return '';photoUrls[id]=URL.createObjectURL(await r.blob());return photoUrls[id]}
async function loadPhotos(extra){const p=$('project').value.trim();if(!p)return;try{drawPhotos(await post('/monitor/photos',Object.assign({project:p,kind:$('reportKind').value,end:$('cut').value||''},extra||{})));return true}catch(e){msg('photosMsg',e.message,'bad');return false}}
function drawPhotos(r){const list=r.photos||[];$('photosState').textContent=list.length?`За период: ${list.length}, отмечено для сводки: ${list.filter(x=>x.chosen).length}.`:'';$('photosList').innerHTML=list.length?list.map(x=>`<label data-id="${esc(x.id)}" class="${x.chosen?'on':''}"><img alt="${esc(x.caption||'фото со стройки')}"><input type="checkbox" class="photoPick" ${x.chosen?'checked':''}> В сводку<div class="muted">${dt(x.day)} · ${esc(x.author||'автор не указан')}</div>${x.caption?`<div>${esc(x.caption)}</div>`:''}</label>`).join(''):'<div class="muted">За этот период фото из чата стройки не приходили. Бот сохраняет фото из чата, привязанного командой /site, начиная с этой версии.</div>';$('photosList').querySelectorAll('label').forEach(box=>{const id=box.dataset.id;photoSrc(id).then(src=>{if(src)box.querySelector('img').src=src});box.querySelector('.photoPick').onchange=async e=>{if(await loadPhotos({photo_id:id,chosen:e.target.checked})){msg('photosMsg','Выбор сохранён — сводка обновлена.','good');renderReport(true)}}})}
async function loadMailing(extra){const p=$('project').value.trim();if(!p)return;try{drawMailing(await post('/monitor/report/mailing',Object.assign({project:p},extra||{})));return true}catch(e){msg('mailingMsg',e.message,'bad');return false}}
function drawMailing(r){const people=r.subscribers||[],next=r.next||{};$('mailingNext').textContent=next.at?`Ближайшая рассылка — ${dt(next.at)} в 9:00, ${next.kind==='week'?'за неделю':'за месяц'}.`:'';$('mailingInviteBtn').textContent=r.invite?'Выдать новую ссылку (прежняя перестанет действовать)':'Создать ссылку-приглашение';$('mailingLink').innerHTML=r.link?`<div>Ссылка-приглашение: <input id="mailingLinkText" readonly value="${esc(r.link)}" style="width:420px"> <button class="btn ghost" id="mailingCopyBtn">Скопировать</button></div><div class="muted" style="font-size:11px">Создана ${dt(r.invite.at)}, ${esc(r.invite.by)}. Кто открыл ссылку, остаётся подписан и после выдачи новой.</div>`:(r.link_reason?`<div class="msg bad">${esc(r.link_reason)}</div>`:'<div class="muted">Ссылки ещё нет.</div>');if($('mailingCopyBtn'))$('mailingCopyBtn').onclick=()=>{$('mailingLinkText').select();try{navigator.clipboard.writeText(r.link)}catch(e){document.execCommand('copy')}msg('mailingMsg','Ссылка скопирована.','good')};$('mailingList').innerHTML=people.length?`<b>Получатели: ${people.length}</b>`+people.map(x=>`<div class="mailingPerson" data-chat="${esc(x.chat_id)}" style="border-top:1px solid #e5e7eb;padding:5px 0">${esc(x.name||('чат '+x.chat_id))} <span class="muted">· подписан ${dt(x.at)}${x.last?` · последняя сводка: ${esc(x.last.label)}${x.last.error?' — '+esc(x.last.error):''}`:' · сводок ещё не было'}</span> <button class="btn ghost mailingRemove">Отписать</button></div>`).join(''):'<div class="muted">Получателей пока нет.</div>';$('mailingList').querySelectorAll('.mailingPerson').forEach(box=>{box.querySelector('.mailingRemove').onclick=async()=>{if(!confirm('Отписать получателя от сводки по этому проекту?'))return;if(await loadMailing({remove_chat:Number(box.dataset.chat)}))msg('mailingMsg','Получатель отписан.','good')}})}
$('mailingInviteBtn').onclick=async()=>{if(await loadMailing({invite:true}))msg('mailingMsg','Новая ссылка готова: отправьте её тем, кто должен получать сводку.','good')};
async function renderNotes(){const p=$('project').value.trim();if(!p)return;try{drawNotes(await post('/monitor/notes',{project:p}))}catch(e){msg('notesMsg',e.message,'bad')}}
function drawNotes(r){const list=r.notes||[],names=r.statuses||{};$('notesState').textContent=list.length?`Открытых вопросов: ${list.filter(n=>n.status==='open').length} из ${list.length}.`:'';$('notesList').innerHTML=list.length?list.map(n=>`<div class="note" data-id="${esc(n.id)}" style="border-top:1px solid #e5e7eb;padding:6px 0"><b>${esc(n.topic)}</b> · <span class="muted">${esc(names[n.status]||n.status)}</span><div>${esc(n.text)}</div><div class="muted" style="font-size:11px">${dt(n.at)} · ${esc(n.author)}${n.version>1?` · правок: ${n.version-1}, создал ${esc(n.created_by)} ${dt(n.created_at)}`:''}</div><div class="files"><input class="noteNew" placeholder="Новое состояние вопроса" style="width:300px"><button class="btn alt noteSave">Обновить</button><button class="btn alt noteToggle">${n.status==='open'?'Закрыть вопрос':'Открыть снова'}</button></div></div>`).join(''):'<div class="muted">Записей пока нет. Добавьте первую ниже.</div>';$('notesList').querySelectorAll('.note').forEach(box=>{const id=box.dataset.id,n=list.find(x=>x.id===id);box.querySelector('.noteSave').onclick=()=>noteSend({note_id:id,text:box.querySelector('.noteNew').value.trim()});box.querySelector('.noteToggle').onclick=()=>noteSend({note_id:id,status:n.status==='open'?'closed':'open'})})}
async function noteSend(extra){try{drawNotes(await post('/monitor/notes',Object.assign({project:$('project').value.trim()},extra)));msg('notesMsg','Запись сохранена.','good');return true}catch(e){msg('notesMsg',e.message,'bad');return false}}
$('noteAddBtn').onclick=async()=>{if(await noteSend({topic:$('noteTopic').value.trim(),text:$('noteText').value.trim()})){$('noteTopic').value='';$('noteText').value=''}};
$('reportBtn').onclick=()=>renderReport();
$('project').onchange=()=>{drawSalesLink(false);renderReport()};
$('salesChange').onclick=()=>drawSalesLink(true);
$('reportSales').onchange=async()=>{const v=$('reportSales').value;if(!v)return;try{drawProjects(await post('/monitor/report/link',{project:$('project').value,sales_project:v==='__none__'?'':v}),$('project').value);msg('reportMsg','Выбор запомнен: теперь он действует для всех, кто открывает сводку этого проекта.','good');renderReport(true)}catch(e){msg('reportMsg',e.message,'bad')}};
$('reportKind').onchange=()=>renderReport();
$('reportPdfBtn').onclick=async()=>{const btn=$('reportPdfBtn');btn.disabled=true;msg('reportMsg','Печатаю PDF — обычно до двадцати секунд.','warn');try{const r=await fetch('/monitor/report.pdf',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(Object.assign(auth(),reportPayload()))});if(r.status===401)requireLogin();if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.detail||('Не удалось напечатать PDF: ошибка '+r.status))}const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`Сводка ${$('project').value.trim()} ${$('cut').value||''}.pdf`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),60000);msg('reportMsg','PDF скачан.','good')}catch(e){msg('reportMsg',e.message,'bad')}finally{btn.disabled=false}};
$('loginBtn').onclick=async()=>{msg('loginMsg','Открываю Telegram…','good');try{const r=await fetch('/auth/telegram/start',{method:'POST'}),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Вход через Telegram недоступен');if(d.link)window.open(d.link,'_blank');for(let i=0;i<60;i++){await new Promise(ok=>setTimeout(ok,2000));const c=await fetch('/auth/telegram/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:d.code})}),cd=await c.json().catch(()=>({}));if(c.ok&&cd.session){remember(WEB_SESSION_KEY,cd.session);if(syncAuthUi())start();return}}throw new Error('Подтверждение не пришло за 2 минуты.')}catch(e){msg('loginMsg',e.message,'bad')}};
$('keyBtn').onclick=()=>{const k=prompt('Ключ администратора');if(!k)return;remember(ADMIN_KEY,k.trim());if(syncAuthUi())start()};
$('cut').value=new Date().toISOString().slice(0,10);
async function start(){if(await loadProjects())renderReport()}
if(syncAuthUi())start();else msg('loginMsg','Войдите через Telegram, чтобы открыть сводку.','bad');
</script>
</body></html>
"""
