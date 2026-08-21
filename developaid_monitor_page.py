"""Embedded managerial Project Monitor page."""
from __future__ import annotations

import developaid_monitor_manager as _manager
_manager.install()
import developaid_monitor_dashboard as _dashboard
_dashboard.install()

MONITOR_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · Project Monitor</title>
<style>
:root{
  --bg:#f5f6f8;--card:#fff;--text:#18202a;--muted:#667085;--line:#e4e7ec;
  --navy:#183153;--navy2:#2f4b6c;--risk:#b42318;--warn:#9a6700;--ok:#247044;
  --plan:#c7ced7;--grid:#eef1f4
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:13px Inter,Arial,sans-serif}
.wrap{max-width:1580px;margin:auto;padding:20px}
.top{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:12px}
h1{margin:0;font-size:24px} h2{margin:0;font-size:14px}
.muted{color:var(--muted)}
.controls,.files,.auth-actions,.legend{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:10px;text-transform:uppercase;font-weight:750;color:var(--muted)}
input{height:34px;border:1px solid #d0d5dd;border-radius:6px;padding:0 8px;background:#fff}
.btn{height:34px;border:0;border-radius:6px;padding:0 12px;background:var(--navy);color:#fff;font-weight:700;cursor:pointer}
.btn.alt{background:#475467}.btn.ghost{background:#fff;color:var(--navy);border:1px solid #cfd5dd}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-top:10px;overflow:hidden}
.head{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:center}
.body{padding:13px 14px}
.setup{display:grid;grid-template-columns:1.15fr 1fr;gap:10px}
.box{border:1px solid var(--line);border-radius:8px;padding:12px;background:#fbfcfd}
.box b{display:block;margin-bottom:6px}.box p{font-size:11px;line-height:1.45;color:var(--muted);margin:4px 0 10px}
.msg{font-size:11px;margin-top:7px;min-height:14px}.good{color:var(--ok)}.bad{color:var(--risk)}.warn{color:var(--warn)}
.auth-card{border-left:4px solid var(--navy)}.auth-title{font-size:16px;font-weight:760;margin-bottom:4px}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:11px;min-height:105px}
.kpi .l{font-size:9px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:800}
.kpi .n{font-size:22px;font-weight:760;margin:8px 0 4px}.kpi .s{font-size:10px;line-height:1.35;color:var(--muted)}
.legend{font-size:10px;color:var(--muted);margin-top:4px}
.lg{display:inline-flex;align-items:center;gap:4px}
.sw{display:inline-block;width:18px;height:6px;border-radius:3px}.sw.plan{background:var(--plan)}.sw.ks{background:var(--navy)}
.sw.tail{height:3px;background:var(--risk)}.sw.pay{width:4px;height:12px;background:var(--navy2);border-radius:0}.sw.payplan{width:4px;height:12px;background:#cbd2da;border-radius:0}
.g-axis,.g-row{display:grid;grid-template-columns:335px 1fr 225px}
.g-axis{padding:8px 12px;border-bottom:1px solid var(--line);font-size:10px;color:var(--muted)}
.axis{height:20px;position:relative}.tick{position:absolute;transform:translateX(-50%);white-space:nowrap}
.g-row{min-height:72px;border-bottom:1px solid var(--grid)}
.g-label,.g-metrics{padding:9px 11px}.g-label{cursor:pointer}
.title{font-weight:680}.sub{font-size:10px;color:var(--muted);margin-top:4px}.chev{display:inline-block;width:16px;color:#667085}
.lanes{position:relative;padding:5px 0}
.lane-wrap{display:grid;grid-template-columns:42px 1fr;align-items:center}
.lane-name{font-size:8px;text-transform:uppercase;color:#98a2b3;text-align:right;padding-right:6px}
.lane{height:27px;position:relative;background:repeating-linear-gradient(to right,transparent,transparent calc(12.5% - 1px),#f0f2f5 calc(12.5% - 1px),#f0f2f5 12.5%)}
.lane.paylane{height:25px;border-top:1px solid #f0f2f5}
.planbar{position:absolute;top:10px;height:7px;background:var(--plan);border-radius:3px}
.ksbar{position:absolute;top:10px;height:7px;background:var(--navy);border-radius:3px}
.closedbar{position:absolute;top:10px;height:7px;background:#667085;border-radius:3px}
.tail{position:absolute;top:12px;height:3px;background:var(--risk)}
.mark{position:absolute;top:5px;width:2px;height:17px;background:var(--risk)}
.cut{position:absolute;top:0;bottom:0;width:1px;background:#344054;opacity:.75}
.funding-zone{position:absolute;top:0;bottom:0;background:rgba(180,35,24,.065);pointer-events:none}
.reserve-mark{position:absolute;top:0;bottom:0;border-left:1px dashed var(--warn);pointer-events:none}
.limit-mark{position:absolute;top:0;bottom:0;border-left:2px solid var(--risk);pointer-events:none}
.pay{position:absolute;bottom:3px;width:5px;background:var(--navy2);transform:translateX(-2px)}
.pay.planpay{background:#cbd2da}
.g-metrics{text-align:right;font-size:10px;color:var(--muted);line-height:1.45}
.m-main{font-weight:700;color:var(--text)}.risktext{color:var(--risk)}.oktext{color:var(--ok)}
.lvl-detail .g-label{padding-left:27px}.lvl-rss .g-label{padding-left:44px}.lvl-task .g-label{padding-left:62px;background:#fafbfc}
.selected{background:#f5f8fb}
.detail-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.mini{border:1px solid var(--line);border-radius:7px;padding:10px}.mini .l{font-size:9px;text-transform:uppercase;color:var(--muted);font-weight:800}
.mini .v{font-size:17px;font-weight:750;margin-top:5px}
.links{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.links>div{border-top:1px solid var(--line);padding-top:8px}
.linkrow{font-size:11px;margin:5px 0;line-height:1.35}.hidden{display:none!important}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.setup{grid-template-columns:1fr}.g-axis,.g-row{grid-template-columns:245px 1fr 155px}.lane-wrap{grid-template-columns:34px 1fr}}
</style>
</head>
<body><div class="wrap">
<div class="top">
 <div><h1>DevelopAid · Project Monitor</h1><div class="muted">Утвержденный ГПР / rebaseline → КС и платежи РСС → зависимости PM → финансовый риск</div></div>
 <div class="controls"><div class="field"><label>Проект</label><input id="project" value="Кутузов Сити"></div><div class="field"><label>Срез</label><input id="cut" type="date"></div><button class="btn" id="refresh">Обновить</button></div>
</div>

<div class="card auth-card" id="loginBox"><div class="body">
 <div class="auth-title">Вход в Project Monitor</div>
 <div class="muted">Войдите через Telegram тем же аккаунтом DevelopAid.</div>
 <div class="auth-actions" style="margin-top:10px"><button class="btn" id="loginBtn">Войти через Telegram</button><button class="btn ghost" id="keyBtn">Ключ администратора</button><button class="btn ghost hidden" id="logoutBtn">Выйти</button><span id="loginState"></span></div>
 <div class="msg" id="loginMsg"></div>
</div></div>

<div id="privateArea" class="hidden">
<div class="card"><div class="head"><h2>Инициализация и обновление</h2><span class="muted">benchmark фиксируется один раз</span></div><div class="body setup">
 <div class="box"><b>1 · Benchmark проекта</b>
  <p>ГПР задаёт WBS и привязку к РСС. Финансовая книга — утверждённую модель, потребность и ДДС. Сырой PM — только зависимости, float и конечную веху.</p>
  <div class="files"><input id="gpr" type="file" accept=".xlsx"><span class="muted">ГПР+RSS</span><input id="finance" type="file" accept=".xlsx"><span class="muted">ФМ/потребность</span><input id="pm" type="file" accept=".xlsx"><span class="muted">сырой PM</span><input id="baselineDate" type="date"><button class="btn alt" id="baselineBtn">Зафиксировать</button></div>
  <div class="msg" id="baselineMsg"></div>
  <div style="margin-top:10px;border-top:1px solid var(--line);padding-top:9px"><b>Утверждённый rebaseline статьи</b>
   <div class="files"><input id="rebase" type="file" accept=".xlsx"><input id="rebaseCode" value="2.2.2.6"><input id="rebaseSheet" value="наше предложение"><button class="btn alt" id="rebaseBtn">Добавить rebaseline</button></div>
   <div class="msg" id="rebaseMsg"></div>
  </div>
 </div>
 <div class="box"><b>2 · Регулярное обновление</b>
  <p><strong>КС/актирование — только «Реестр выполненных работ».</strong> Денежный факт — только «Реестр платежей». КС/EAC не считается физическим процентом WBS и не двигает календарные сроки.</p>
  <div class="files"><input id="rss" type="file" accept=".xlsx"><input id="rssDate" type="date"><button class="btn alt" id="rssBtn">Загрузить РСС</button></div>
  <div class="files" style="margin-top:8px"><input id="sales" type="file" accept=".xlsx"><button class="btn alt" id="salesBtn">Загрузить продажи</button></div>
  <div class="msg" id="weeklyMsg"></div>
 </div>
</div></div>

<div class="card hidden" id="dashCard"><div class="head"><h2>Состояние проекта</h2><span class="muted" id="source"></span></div><div class="body"><div class="kpis" id="kpis"></div></div></div>

<div class="card hidden" id="ganttCard"><div class="head">
 <div><h2>Управленческий Гант · сроки + КС + оплаты</h2>
  <div class="legend">
   <span class="lg"><i class="sw plan"></i>утверждённый график</span>
   <span class="lg"><i class="sw ks"></i>КС/EAC (только RSS-уровень)</span>
   <span class="lg"><i class="sw tail"></i>сдвиг forecast</span>
   <span class="lg"><i class="sw payplan"></i>план оплат</span>
   <span class="lg"><i class="sw pay"></i>факт оплат</span>
  </div>
 </div>
 <span class="muted">клик: блок → RSS → WBS</span>
</div><div id="gantt"></div></div>

<div class="card hidden" id="detailCard"><div class="head"><h2 id="detailTitle">Статья</h2><span class="muted">график · КС · оплаты · зависимости PM</span></div><div class="body"><div class="detail-grid" id="detailGrid"></div><div class="links"><div><b>Что влияет на эту работу</b><div id="pred"></div></div><div><b>На что влияет она</b><div id="succ"></div></div></div></div></div>
</div>
<div class="msg bad" id="viewMsg"></div>
</div>

<script>
'use strict';
const $=id=>document.getElementById(id), expanded=new Set(); let selected=null;
const WEB_SESSION_KEY='developaid_web_session', ADMIN_KEY='plato_projects_key';
const today=new Date().toISOString().slice(0,10);
$('cut').value=today;$('rssDate').value=today;$('baselineDate').value=today;

function readStorage(...keys){try{for(const k of keys){const v=localStorage.getItem(k);if(v)return v}}catch(e){}return ''}
function session(){return readStorage(WEB_SESSION_KEY,'session','developaid_session')}
function adminKey(){return readStorage(ADMIN_KEY,'key','developaid_key')}
function hasAuth(){return !!(session()||adminKey())}
function auth(){return {session:session(),key:adminKey()}}
function syncAuthUi(){const yes=hasAuth();$('loginBox').classList.toggle('hidden',yes);$('privateArea').classList.toggle('hidden',!yes);$('logoutBtn').classList.toggle('hidden',!yes);$('loginState').textContent=yes?'Вход выполнен':'';return yes}
function requireLogin(text='Войдите через Telegram, чтобы открыть данные проекта.'){$('loginBox').classList.remove('hidden');$('privateArea').classList.add('hidden');msg('loginMsg',text,'bad')}
async function post(path,p){const r=await fetch(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(Object.assign(auth(),p||{}))}),d=await r.json().catch(()=>({}));if(r.status===401)requireLogin();if(!r.ok)throw new Error(d.detail||('HTTP '+r.status));return d}
const b64=f=>new Promise((ok,no)=>{const r=new FileReader();r.onload=()=>ok(String(r.result).split(',')[1]);r.onerror=no;r.readAsDataURL(f)});
function money(v){if(v==null||!isFinite(Number(v)))return '—';const n=Number(v);return Math.abs(n)>=1e9?(n/1e9).toLocaleString('ru-RU',{maximumFractionDigits:2})+' млрд ₽':(n/1e6).toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽'}
function pct(v){return v==null?'—':(Number(v)*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%'}
function dt(v){if(!v)return '—';const d=new Date(v);return isNaN(d)?v:d.toLocaleDateString('ru-RU')}
function msg(id,t,cls=''){const e=$(id);if(!e)return;e.textContent=t;e.className='msg '+cls}
function kpi(l,n,s='',cls=''){return `<div class="kpi"><div class="l">${l}</div><div class="n ${cls}">${n}</div><div class="s">${s}</div></div>`}

$('loginBtn').onclick=async()=>{msg('loginMsg','Открываю Telegram…','good');try{const r=await fetch('/auth/telegram/start',{method:'POST'}),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Вход через Telegram недоступен');if(!d.code)throw new Error('Сервер не вернул код входа');if(d.link)window.open(d.link,'_blank');msg('loginMsg','Подтвердите вход в Telegram.','good');for(let i=0;i<60;i++){await new Promise(ok=>setTimeout(ok,2000));const c=await fetch('/auth/telegram/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:d.code})}),cd=await c.json().catch(()=>({}));if(c.ok&&cd.session){localStorage.setItem(WEB_SESSION_KEY,cd.session);syncAuthUi();await refresh();return}if(c.status>=500)throw new Error(cd.detail||'Ошибка подтверждения входа')}throw new Error('Подтверждение не пришло за 2 минуты.')}catch(e){msg('loginMsg',e.message,'bad')}};
$('keyBtn').onclick=()=>{const k=prompt('Ключ администратора (DEVELOPAID_ADMIN_KEY)');if(!k)return;localStorage.setItem(ADMIN_KEY,k.trim());syncAuthUi();refresh()};
$('logoutBtn').onclick=()=>{try{localStorage.removeItem(WEB_SESSION_KEY);localStorage.removeItem('session');localStorage.removeItem('developaid_session');localStorage.removeItem(ADMIN_KEY);localStorage.removeItem('key');localStorage.removeItem('developaid_key')}catch(e){}syncAuthUi();requireLogin('Сессия удалена. Войдите через Telegram.')};

$('baselineBtn').onclick=async()=>{const g=$('gpr').files[0],f=$('finance').files[0],pm=$('pm').files[0],d=$('baselineDate').value,p=$('project').value.trim();if(!g||!f)return msg('baselineMsg','Нужны ГПР+RSS и финансовая книга','bad');try{msg('baselineMsg','Фиксирую benchmark…','good');await post('/monitor/schedule',{project:p,taken_at:d,gpr_base64:await b64(g),pm_base64:await b64(f)});if(pm)await post('/monitor/proposal',{project:p,taken_at:d,start:d,code:'__PM__',sheet:'Таблица_задач1',content_base64:await b64(pm)});msg('baselineMsg','Benchmark создан. PM-зависимости сохранены отдельно.','good');await refresh()}catch(e){msg('baselineMsg',e.message,'bad')}};
$('rebaseBtn').onclick=async()=>{const f=$('rebase').files[0];if(!f)return msg('rebaseMsg','Выберите файл rebaseline','bad');try{await post('/monitor/proposal',{project:$('project').value.trim(),taken_at:$('cut').value,start:$('cut').value,code:$('rebaseCode').value.trim(),sheet:$('rebaseSheet').value.trim(),content_base64:await b64(f)});msg('rebaseMsg','Rebaseline сохранён; исходный ГПР остаётся историческим baseline v1.','good');await refresh()}catch(e){msg('rebaseMsg',e.message,'bad')}};
$('rssBtn').onclick=async()=>{const f=$('rss').files[0],d=$('rssDate').value;if(!f)return msg('weeklyMsg','Выберите РСС 6.1.2','bad');try{await post('/monitor/estimate',{project:$('project').value.trim(),taken_at:d,filename:f.name,content_base64:await b64(f)});$('cut').value=d;msg('weeklyMsg','РСС загружен: КС и платежи пересчитаны.','good');await refresh()}catch(e){if(String(e.message).includes('уже загружен')){$('cut').value=d;msg('weeklyMsg','Этот срез уже сохранён — открываю существующий расчёт.','warn');await refresh();return}msg('weeklyMsg',e.message,'bad')}};
$('salesBtn').onclick=async()=>{const f=$('sales').files[0];if(!f)return msg('weeklyMsg','Выберите отчёт продаж','bad');try{await post('/monitor/sales',{project:$('project').value.trim(),taken_at:$('cut').value,content_base64:await b64(f)});msg('weeklyMsg','Продажи сохранены.','good');await refresh()}catch(e){msg('weeklyMsg',e.message,'bad')}};

function renderDash(v){
 const d=v.dashboard||{},s=d.schedule||{},ph=d.physical||{},f=d.funding||{};
 $('dashCard').classList.remove('hidden');$('source').textContent=(d.sources&&d.sources.rss)||'';
 $('kpis').innerHTML=
   kpi('Forecast РВЭ / РНВ',dt(s.forecast_finish),s.rnv_delay_days?`+${s.rnv_delay_days} дн к утвержденному сроку`:'по утверждённой PM-сети',s.rnv_delay_days>0?'bad':'good')+
   kpi('Актировано СМР / утв. модель',pct(ph.completion),`${money(ph.accepted)} по датированным КС · это не физический % WBS`)+
   kpi('Остаток реальной потребности',money(f.remaining_need),`до ${dt(f.forecast_to)}`)+
   kpi('Начало использования резерва',dt(f.reserve_start),`резерв ${money(f.reserve)} · 2.8/2.9`,f.reserve_start?'warn':'')+
   kpi('Исчерпание лимита банка',dt(f.bank_exhaustion),`остаток лимита ${money(f.bank_remaining)}`,f.bank_exhaustion?'bad':'good')+
   kpi('Доп. финансирование до РВЭ',money(f.additional_financing),f.known?f.method:(f.reason||'нет данных'),f.additional_financing>0?'bad':'good');
}
function collect(nodes,out=[]){for(const n of nodes||[]){out.push(n);collect(n.children||[],out)}return out}
function toDate(v){const d=new Date(v);return isNaN(d)?null:d}

function renderGantt(v){
 const roots=(v.schedule&&v.schedule.management)||[];
 if(!roots.length){$('ganttCard').classList.add('hidden');return}
 $('ganttCard').classList.remove('hidden');
 const all=collect(roots,[]),starts=all.map(x=>toDate(x.plan_start)).filter(Boolean),finishes=all.map(x=>toDate(x.forecast_finish||x.plan_finish)).filter(Boolean),fund=v.financing||{};
 if(!starts.length||!finishes.length)return;
 if(fund.forecast_to){const z=toDate(fund.forecast_to);if(z)finishes.push(z)}
 let min=new Date(Math.min(...starts.map(d=>+d))),max=new Date(Math.max(...finishes.map(d=>+d)));
 min.setDate(min.getDate()-15);max.setDate(max.getDate()+15);
 const span=Math.max(1,+max-+min),pos=x=>{const d=toDate(x);return d?Math.max(0,Math.min(100,(+d-+min)/span*100)):null};
 let html='<div class="g-axis"><div>Этап / статья / WBS</div><div class="axis">';
 for(let i=0;i<=6;i++){const d=new Date(+min+span*i/6);html+=`<span class="tick" style="left:${i/6*100}%">${d.toLocaleDateString('ru-RU',{month:'short',year:'2-digit'})}</span>`}
 html+='</div><div style="text-align:right">Срок · КС · оплаты</div></div>';

 function commonMarks(){
   let x='';const cp=pos(v.cut),rs=pos(fund.reserve_start),ex=pos(fund.bank_exhaustion);
   if(cp!=null)x+=`<span class="cut" style="left:${cp}%"></span>`;
   if(rs!=null)x+=`<span class="reserve-mark" style="left:${rs}%"></span>`;
   if(ex!=null)x+=`<span class="limit-mark" style="left:${ex}%"></span><span class="funding-zone" style="left:${ex}%;right:0"></span>`;
   return x;
 }
 function row(n){
   const key=n.key||('task:'+String(n.id||n.wbs||n.name)),kids=(n.children||[]).filter(Boolean),open=expanded.has(key),lvl=n.level||'task',ps=pos(n.plan_start),pf=pos(n.plan_finish),ff=pos(n.forecast_finish),sel=selected===key?' selected':'',payments=n.payments||{},dep=n.dependencies||{};
   let works=commonMarks(),pays=commonMarks();
   if(ps!=null&&pf!=null)works+=`<span class="planbar" style="left:${ps}%;width:${Math.max(1,pf-ps)}%"></span>`;
   if(n.schedule_closed&&ps!=null&&pf!=null)works+=`<span class="closedbar" style="left:${ps}%;width:${Math.max(1,pf-ps)}%"></span>`;
   else if(lvl==='rss'&&n.actual_progress!=null&&ps!=null&&pf!=null){
     const ratio=Math.max(0,Math.min(1,Number(n.actual_progress)));
     works+=`<span class="ksbar" title="КС/EAC — стоимостное актирование, не физический процент" style="left:${ps}%;width:${Math.max(0,(pf-ps)*ratio)}%"></span>`;
   }
   if(ff!=null&&pf!=null&&ff>pf){works+=`<span class="tail" style="left:${pf}%;width:${ff-pf}%"></span><span class="mark" style="left:${ff}%"></span>`}

   const pm=Object.entries(payments.plan||{}),fm=Object.entries(payments.fact||{}),mx=Math.max(1,...pm.map(x=>Number(x[1])||0),...fm.map(x=>Number(x[1])||0));
   for(const [m,a] of pm){const x=pos(m);if(x!=null)pays+=`<span class="pay planpay" style="left:${x}%;height:${Math.max(2,(Number(a)||0)/mx*16)}px"></span>`}
   for(const [m,a] of fm){const x=pos(m);if(x!=null)pays+=`<span class="pay" style="left:${x}%;height:${Math.max(2,(Number(a)||0)/mx*16)}px"></span>`}

   const delta=n.delta_days!=null?Number(n.delta_days):0;
   let main=n.schedule_closed?'<span class="oktext">завершено</span>':(delta>0?`<span class="risktext">+${delta} дн</span>`:'по графику');
   let evidence='';
   if(lvl==='rss'&&n.actual_progress!=null)evidence=`КС/EAC ${pct(n.actual_progress)}`;
   else if(lvl==='task')evidence=n.baseline_status||n.status||'WBS';
   let third='';
   if(lvl==='task'&&dep.current_float_days!=null)third=`float ${dep.current_float_days} дн${dep.impact_rnv_days?` · РНВ +${dep.impact_rnv_days} дн`:''}`;
   else if(dep.impact_rnv_days)third=`влияние на РНВ +${dep.impact_rnv_days} дн`;
   const paid=payments.fact_total==null?'':`оплачено ${money(payments.fact_total)}`;

   html+=`<div class="g-row lvl-${lvl}${sel}" data-key="${key}">
    <div class="g-label"><span class="chev">${kids.length?(open?'▾':'▸'):''}</span><span class="title">${n.code?`${n.code} · `:''}${n.name||n.wbs||''}</span><div class="sub">${lvl==='task'?'WBS '+(n.wbs||n.id||''):lvl==='rss'?'RSS · финансовая привязка':lvl==='detail'?'этап':'управленческий блок'}</div></div>
    <div class="lanes"><div class="lane-wrap"><span class="lane-name">работы</span><div class="lane">${works}</div></div><div class="lane-wrap"><span class="lane-name">оплаты</span><div class="lane paylane">${pays}</div></div></div>
    <div class="g-metrics"><div class="m-main">${main}</div><div>${evidence}</div><div>${paid}</div><div>${third}</div></div>
   </div>`;
   if(open)for(const c of kids)row(c);
 }
 for(const r of roots)row(r);
 $('gantt').innerHTML=html;
 document.querySelectorAll('.g-row').forEach(el=>el.onclick=()=>{
   const key=el.dataset.key,n=collect(roots,[]).find(x=>(x.key||('task:'+String(x.id||x.wbs||x.name)))===key);
   if(!n)return;selected=key;if((n.children||[]).length){expanded.has(key)?expanded.delete(key):expanded.add(key)}
   renderGantt(v);renderDetail(n);
 });
}

function renderDetail(n){
 $('detailCard').classList.remove('hidden');$('detailTitle').textContent=(n.code?`${n.code} · `:'')+(n.name||n.wbs||'Статья');
 const dep=n.dependencies||{},pay=n.payments||{},delta=n.delta_days!=null?Number(n.delta_days):0,lvl=n.level||'task';
 const evidence=(lvl==='rss'&&n.actual_progress!=null)?pct(n.actual_progress):'—';
 $('detailGrid').innerHTML=
  `<div class="mini"><div class="l">Срок / forecast</div><div class="v ${delta>0?'bad':''}">${dt(n.forecast_finish)}</div><div class="sub">утверждено ${dt(n.plan_finish)} · ${n.schedule_closed?'завершено':delta>0?'+'+delta+' дн':'без сдвига'}</div></div>`+
  `<div class="mini"><div class="l">КС / EAC</div><div class="v">${evidence}</div><div class="sub">${lvl==='rss'?`${money(n.accepted)} актировано · не физический % WBS`:'показывается только на RSS-уровне'}</div></div>`+
  `<div class="mini"><div class="l">Оплаты</div><div class="v">${money(pay.fact_total)}</div><div class="sub">план ${money(pay.plan_total)}</div></div>`+
  `<div class="mini"><div class="l">Float / влияние</div><div class="v">${lvl==='task'&&dep.current_float_days!=null?dep.current_float_days+' дн':'—'}</div><div class="sub">${lvl==='task'?`передано ${dep.inherited_delay_days||0} дн · РНВ ${dep.impact_rnv_days||0} дн`:'float показывается только на WBS'}</div></div>`;
 const fmt=x=>`<div class="linkrow"><b>${x.id}</b> ${x.name||''}<br><span class="muted">${x.type||''}${x.lag_days?` ${x.lag_days>0?'+':''}${x.lag_days} дн`:''}</span></div>`;
 $('pred').innerHTML=(lvl==='task'?(dep.predecessors||[]).map(fmt).join(''):'')||'<span class="muted">связи показываются на WBS-уровне</span>';
 $('succ').innerHTML=(lvl==='task'?(dep.successors||[]).map(fmt).join(''):'')||'<span class="muted">связи показываются на WBS-уровне</span>';
}

async function refresh(){
 if(!hasAuth()){syncAuthUi();msg('viewMsg','Войдите через Telegram, чтобы открыть данные проекта.','bad');return}
 syncAuthUi();const p=$('project').value.trim();if(!p)return;
 try{msg('viewMsg','');const raw=await post('/monitor/view',{project:p,cut:$('cut').value,upto:''});const v=raw.snapshot||raw.view||raw.report||raw.response||raw;renderDash(v);renderGantt(v)}
 catch(e){msg('viewMsg',e.message,'bad')}
}
$('refresh').onclick=refresh;syncAuthUi();if(hasAuth())refresh();else msg('viewMsg','Войдите через Telegram, чтобы открыть данные проекта.','bad');
</script>
</body></html>
"""
