"""Страница недельного монитора: рисует то, что посчитал сервер.

Отдельный адрес, а не вкладка расчёта: монитор живёт другим ритмом — раз в
неделю сюда приносят свежие выгрузки и смотрят «отстаём или нет», а не крутят
предпосылки. Общее у них — вход: сессия та же, что у проектов и Платона, и
лежит в том же localStorage, поэтому вошедшему на основной странице монитор
открыт сразу.

Страница не считает ничего — все числа приходят готовыми из /monitor/*.
Правило старое и дважды нарушенное: две поверхности, считающие каждая своё,
расходятся молча и обе выглядят достоверно.
"""

MONITOR_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>DevelopAid — монитор проекта</title>
<style>
 body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;background:#f4f5f7;color:#1c1e21}
 header{background:#101820;color:#fff;padding:14px 20px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
 header h1{font-size:17px;margin:0;font-weight:600}
 header .v{font-size:12px;color:#8a94a0}
 main{max-width:1180px;margin:0 auto;padding:16px}
 .card{background:#fff;border:1px solid #e2e5e9;border-radius:10px;padding:14px 16px;margin-bottom:14px}
 .card h2{font-size:14px;margin:0 0 10px;font-weight:600}
 .muted{color:#68727e;font-size:12px}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
 .kpi{border:1px solid #e8eaee;border-radius:8px;padding:9px 11px}
 .kpi .l{font-size:11px;color:#68727e}
 .kpi .n{font-size:17px;font-weight:600;margin-top:2px;white-space:nowrap}
 .kpi.bad .n{color:#b42318}.kpi.good .n{color:#067647}
 table{border-collapse:collapse;width:100%;font-size:12.5px}
 th,td{padding:5px 8px;border-bottom:1px solid #eef0f3;text-align:right;white-space:nowrap}
 th:first-child,td:first-child,th.t,td.t{text-align:left;white-space:normal}
 th{color:#68727e;font-weight:500;font-size:11.5px}
 td.neg{color:#b42318}td.pos{color:#067647}
 button{border:1px solid #c9ced6;background:#fff;border-radius:7px;padding:7px 13px;font-size:13px;cursor:pointer}
 button.dark{background:#101820;color:#fff;border-color:#101820}
 button:disabled{opacity:.5;cursor:default}
 input,select{border:1px solid #c9ced6;border-radius:7px;padding:6px 9px;font-size:13px;background:#fff}
 input[type=file]{border:none;padding:0;font-size:12px;max-width:230px}
 .up{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}
 .up .card{margin:0}
 .msg{font-size:12px;margin-top:6px;min-height:14px}
 .msg.err{color:#b42318}.msg.ok{color:#067647}
 #loginBox{display:none}
 .bar{height:9px;border-radius:3px;position:absolute}
 .gwrap{overflow-x:auto}
 svg text{font-size:10px;fill:#4b5563}
 .legend span{display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:11.5px;color:#4b5563}
 .sw{width:14px;height:8px;border-radius:2px;display:inline-block}
 details summary{cursor:pointer;font-size:12.5px;color:#374151}
 .pill{display:inline-block;border-radius:99px;padding:2px 9px;font-size:11px;background:#eef0f3;color:#374151;margin-left:6px}
 .pill.warn{background:#fef0c7;color:#93370d}
</style>
</head>
<body>
<header>
 <h1>DevelopAid · Монитор проекта</h1>
 <span class="v">__VERSION__</span>
 <span class="muted" id="who"></span>
</header>
<main>

<div class="card" id="loginBox">
 <h2>Вход</h2>
 <div class="muted" style="margin-bottom:8px">Здесь сметы, договоры и контрагенты действующего проекта — вход тот же, что у проектов: через бота в Telegram.</div>
 <div class="row">
  <button class="dark" id="loginBtn">Войти через Telegram</button>
  <button id="keyBtn">У меня ключ администратора</button>
  <span class="msg" id="loginMsg"></span>
 </div>
</div>

<div class="card">
 <div class="row">
  <label>Проект <input id="project" value="Гродненская" style="width:170px"></label>
  <label>Срез <input id="cut" type="date"></label>
  <button class="dark" id="refreshBtn">Обновить</button>
  <span class="muted" id="sourceLine"></span>
 </div>
 <div class="msg" id="viewMsg"></div>
</div>

<div class="card" id="verdictCard" style="display:none">
 <h2>Отстаём или нет</h2>
 <div class="grid" id="verdict"></div>
 <div class="muted" id="scheduleNote" style="margin-top:8px"></div>
</div>

<div class="card" id="moneyCard" style="display:none">
 <h2>Деньги</h2>
 <div class="grid" id="money"></div>
</div>

<div class="card" id="byCodeCard" style="display:none">
 <h2>Где отстаём — по кодам РСС</h2>
 <div class="gwrap"><table id="byCode"></table></div>
</div>

<div class="card" id="salesCard" style="display:none">
 <h2>Продажи</h2>
 <div class="grid" id="sales"></div>
</div>

<div class="card" id="ganttCard" style="display:none">
 <h2>График работ <span class="pill" id="ganttBaselinePill"></span></h2>
 <div class="grid" id="ganttKpi" style="margin-bottom:10px"></div>
 <div class="legend" style="margin-bottom:6px">
  <span><i class="sw" style="background:#c9ced6"></i>базовый план</span>
  <span><i class="sw" style="background:#7aa5d8"></i>текущий план</span>
  <span><i class="sw" style="background:#2f9e63"></i>факт</span>
  <span><i class="sw" style="background:#d1493f"></i>факт (просрочено)</span>
 </div>
 <div class="row" style="margin-bottom:6px">
  <label>Статья <select id="ganttCode"></select></label>
 </div>
 <div class="gwrap" id="gantt"></div>
</div>

<div class="card" id="trendCard" style="display:none">
 <h2>Тренд по снимкам</h2>
 <div class="gwrap"><table id="trend"></table></div>
</div>

<div class="card" id="rewrittenCard" style="display:none">
 <h2>Переписанное прошлое</h2>
 <div class="row" style="margin-bottom:6px">
  <select id="rwFirst"></select> → <select id="rwSecond"></select>
  <button id="rwBtn">Сравнить</button>
 </div>
 <div class="gwrap"><table id="rewritten"></table></div>
</div>

<div class="card">
 <h2>Загрузка выгрузок</h2>
 <div class="muted" style="margin-bottom:10px">Каждый файл кладётся снимком на свою дату и не перезаписывается: переписанное прошлое видно только сравнением снимков.</div>
 <div class="up">
  <div class="card"><h2>РСС</h2>
   <input type="file" id="fEstimate" accept=".xlsx">
   <div class="row" style="margin-top:6px"><label class="muted">на дату <input type="date" id="dEstimate"></label>
   <button data-up="estimate">Загрузить</button></div>
   <div class="msg" id="mEstimate"></div><div class="muted" id="sEstimate"></div>
  </div>
  <div class="card"><h2>Производственная программа</h2>
   <input type="file" id="fProgramme" accept=".xlsx">
   <div class="row" style="margin-top:6px">
    <label class="muted">первый месяц <input type="month" id="dProgrammeStart"></label>
    <label class="muted">на дату <input type="date" id="dProgramme"></label>
    <button data-up="programme">Загрузить</button></div>
   <div class="msg" id="mProgramme"></div><div class="muted" id="sProgramme"></div>
  </div>
  <div class="card"><h2>График работ (ГПР + выгрузка планировщика)</h2>
   <div class="muted">ГПР несёт код РСС, выгрузка планировщика — базовый план и факт. Без второй Гант рисует только текущий план.</div>
   <input type="file" id="fGpr" accept=".xlsx" title="очищенный ГПР">
   <input type="file" id="fPm" accept=".xlsx" title="выгрузка планировщика">
   <div class="row" style="margin-top:6px"><label class="muted">на дату <input type="date" id="dSchedule"></label>
   <button data-up="schedule">Загрузить</button></div>
   <div class="msg" id="mSchedule"></div><div class="muted" id="sSchedule"></div>
  </div>
  <div class="card"><h2>Новый график статьи (предложение)</h2>
   <div class="muted">Согласованный график заменяет план статьи: отставание от сорванного плана — ложная тревога.</div>
   <input type="file" id="fProposal" accept=".xlsx">
   <div class="row" style="margin-top:6px">
    <label class="muted">лист <input id="dProposalSheet" value="наше предложение" style="width:140px"></label>
    <label class="muted">код РСС <input id="dProposalCode" value="2.2.2.6" style="width:70px"></label></div>
   <div class="row" style="margin-top:6px">
    <label class="muted">первый месяц <input type="month" id="dProposalStart"></label>
    <label class="muted">согласован <input type="date" id="dProposal"></label>
    <button data-up="proposal">Загрузить</button></div>
   <div class="msg" id="mProposal"></div><div class="muted" id="sProposal"></div>
  </div>
  <div class="card"><h2>Продажи</h2>
   <div class="muted">Отдельно от РСС: книгу обновляют раз в месяц, и продажи в ней отставали на пять месяцев.</div>
   <table id="salesRows"><tr><th class="t">месяц</th><th>лотов</th><th>м²</th><th>выручка, ₽</th></tr></table>
   <div class="row" style="margin-top:6px"><button id="salesAdd">+ строка</button>
    <label class="muted">на дату <input type="date" id="dSales"></label>
    <button data-up="sales">Загрузить строки</button></div>
   <div class="row" style="margin-top:6px">
    <span class="muted">или книгой (лист «План продаж», возьмутся строки ФАКТ):</span>
    <input type="file" id="fSales" accept=".xlsx">
    <button data-up="salesFile">Загрузить файл</button></div>
   <div class="msg" id="mSales"></div><div class="muted" id="sSales"></div>
  </div>
 </div>
</div>

</main>
<script>
'use strict';
const WEB_SESSION_KEY='developaid_web_session';
const ADMIN_KEY='plato_projects_key';
const $=id=>document.getElementById(id);
const session=()=>{try{return localStorage.getItem(WEB_SESSION_KEY)||''}catch(e){return ''}};
const adminKey=()=>{try{return localStorage.getItem(ADMIN_KEY)||''}catch(e){return ''}};
const mln=v=>v==null?'—':(v/1e6).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+' млн ₽';
const num=v=>v==null?'—':(+v).toLocaleString('ru-RU');
let lastGantt=null;

function today(){return new Date().toISOString().slice(0,10)}
$('cut').value=today();
$('dEstimate').value=today();$('dProgramme').value=today();$('dSchedule').value=today();
$('dProposal').value=today();$('dSales').value=today();

async function api(path,body){
 const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(Object.assign({session:session(),key:adminKey()},body||{}))});
 const d=await r.json().catch(()=>({}));
 if(r.status===401){$('loginBox').style.display='';throw new Error(d.detail||'нужен вход')}
 if(!r.ok)throw new Error(d.detail||('ошибка '+r.status));
 return d;
}
async function apiGet(path,params){
 const q=new URLSearchParams(Object.assign({session:session(),key:adminKey()},params||{}));
 const r=await fetch(path+'?'+q);
 const d=await r.json().catch(()=>({}));
 if(r.status===401){$('loginBox').style.display='';throw new Error(d.detail||'нужен вход')}
 if(!r.ok)throw new Error(d.detail||('ошибка '+r.status));
 return d;
}
function b64(file){return new Promise((res,rej)=>{
 const fr=new FileReader();
 fr.onload=()=>res(String(fr.result).split(',',2)[1]||'');
 fr.onerror=()=>rej(new Error('файл не прочитался'));
 fr.readAsDataURL(file);
});}

// --- вход: та же пара маршрутов, что на основной странице -------------------
$('loginBtn').onclick=async()=>{
 const say=t=>{$('loginMsg').textContent=t};
 try{
  const r=await fetch('/auth/telegram/start',{method:'POST'});
  const d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Вход через Telegram недоступен');
  window.open(d.link,'_blank');
  say('Подтвердите вход в боте…');
  for(let i=0;i<60;i++){
   await new Promise(t=>setTimeout(t,2000));
   const c=await fetch('/auth/telegram/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:d.code})});
   if(c.ok){const cd=await c.json();
    if(cd.session){localStorage.setItem(WEB_SESSION_KEY,cd.session);say('');$('loginBox').style.display='none';refresh();return}}
  }
  say('Подтверждение не пришло — попробуйте ещё раз.');
 }catch(e){say(e.message)}
};
$('keyBtn').onclick=()=>{
 const k=prompt('Ключ администратора (DEVELOPAID_ADMIN_KEY)');
 if(!k)return;
 localStorage.setItem(ADMIN_KEY,k.trim());
 $('loginBox').style.display='none';
 refresh();
};

// --- свод -------------------------------------------------------------------
function kpi(label,value,cls){return '<div class="kpi '+(cls||'')+'"><div class="l">'+label+'</div><div class="n">'+value+'</div></div>'}

function renderView(d){
 const snap=d.snapshot||{};
 const m=snap.money||{};
 const sch=snap.schedule||{};
 $('moneyCard').style.display='';
 $('money').innerHTML=
  kpi('Бюджет РСС',mln(m.budget))+
  kpi('Законтрактовано',mln(m.contracted))+
  kpi('Оплачено до среза',mln(m.paid))+
  kpi('Принято работ',mln(m.accepted))+
  kpi('Оплачено вперёд',mln(m.paid_ahead),m.paid_ahead>1e8?'bad':'')+
  kpi('Осталось до бюджета',mln(m.left_to_budget));
 $('verdictCard').style.display='';
 if(sch.comparable){
  const gap=sch.gap||0;
  $('verdict').innerHTML=
   kpi('Должны были принять',mln(sch.due))+
   kpi('Приняли',mln(sch.done))+
   kpi(gap<0?'Отстаём на':'Опережаем на',mln(Math.abs(gap)),gap<0?'bad':'good')+
   kpi('Выполнение плана',((sch.ratio||0)*100).toFixed(0)+'%',(sch.ratio||0)<1?'bad':'good');
  $('scheduleNote').textContent='План с '+(sch.from||'')+', месяцев в сравнении: '+(sch.months_due||0)+'.';
 }else{
  $('verdict').innerHTML=kpi('Сравнение с планом','нет данных');
  $('scheduleNote').textContent=sch.reason||'Нет производственной программы — загрузите шахматку внизу.';
 }
 const props=(snap.source&&snap.source.proposals)||[];
 if(props.length){
  $('scheduleNote').textContent+=' По '+props.map(p=>p.code).join(', ')+' план заменён согласованным предложением.';
 }
 const by=(snap.by_code||[]);
 if(by.length){
  $('byCodeCard').style.display='';
  let h='<tr><th class="t">код</th><th class="t">статья</th><th>план</th><th>принято</th><th>Δ</th><th>работ</th><th>просрочено</th></tr>';
  for(const r of by){
   if(!r.planned&&!r.accepted&&!r.overdue)continue;
   h+='<tr><td class="t">'+(r.code||'—')+'</td><td class="t">'+(r.article||'')+'</td>'
    +'<td>'+mln(r.planned)+'</td><td>'+mln(r.accepted)+'</td>'
    +'<td class="'+(r.gap<0?'neg':'pos')+'">'+mln(r.gap)+'</td>'
    +'<td>'+num(r.works)+'</td><td>'+num(r.overdue)+'</td></tr>';
  }
  $('byCode').innerHTML=h;
 }
 const so=snap.sales||{};
 if(so&&Object.keys(so).length){
  $('salesCard').style.display='';
  $('sales').innerHTML=
   kpi('Продано лотов',num(so.units))+
   kpi('Продано, м²',num(Math.round(so.area||0)))+
   kpi('Выручка',mln(so.revenue))+
   kpi('Средняя цена',so.average_price?Math.round(so.average_price/1e3).toLocaleString('ru-RU')+' тыс ₽/м²':'—')+
   kpi('Факт по',so.last_fact||'—')+
   kpi('Месяцев без факта',num(so.months_without_fact),so.months_without_fact>0?'bad':'');
 }
 const src=snap.source||{};
 $('sourceLine').textContent='РСС: '+(src.estimate||'—')+(src.sales?' · продажи: '+src.sales:'');
 const tr=d.trend||[];
 if(tr.length>1){
  $('trendCard').style.display='';
  let h='<tr><th class="t">снимок</th><th>оплачено</th><th>принято</th><th>вперёд</th><th>Δ к плану</th></tr>';
  for(const t of tr){
   h+='<tr><td class="t">'+t.snapshot+'</td><td>'+mln(t.paid)+'</td><td>'+mln(t.accepted)+'</td>'
    +'<td>'+mln(t.paid_ahead)+'</td><td class="'+((t.gap||0)<0?'neg':'pos')+'">'+(t.gap==null?'—':mln(t.gap))+'</td></tr>';
  }
  $('trend').innerHTML=h;
 }
}

// --- Гант -------------------------------------------------------------------
function renderGantt(g){
 lastGantt=g;
 $('ganttCard').style.display='';
 $('ganttBaselinePill').textContent=g.source&&g.source.with_baseline?'с базовым планом':'без базового плана';
 $('ganttBaselinePill').className='pill'+(g.source&&g.source.with_baseline?'':' warn');
 const dl=g.deadline||{};
 $('ganttKpi').innerHTML=
  kpi('Работ',num(g.works))+
  kpi('Завершено',num(g.done))+
  kpi('В работе',num(g.running))+
  kpi('Просрочено',num(g.overdue),g.overdue>0?'bad':'')+
  (g.slip_median==null?'':kpi('Сдвиг от базового плана',Math.round(g.slip_median)+' дн (медиана)',g.slip_median>30?'bad':''))+
  (g.measured?kpi('Уехало вправо',num(g.slipped)+' из '+num(g.measured),g.slipped>g.measured/2?'bad':''):'')+
  (dl.known?kpi('Верхний срок: '+dl.name,dl.finish+' ('+(dl.slip_days>=0?'+':'')+dl.slip_days+' дн)',dl.slip_days>30?'bad':'good'):'');
 const sel=$('ganttCode');
 const groups=(g.by_code||[]).filter(c=>c.works>0);
 sel.innerHTML=groups.map(c=>'<option value="'+(c.code||'')+'">'
  +(c.code||'без кода')+' — '+(c.article||'').slice(0,40)
  +(c.worst!=null?' (до +'+c.worst+' дн)':'')+'</option>').join('');
 sel.onchange=()=>drawGantt(sel.value);
 if(groups.length)drawGantt(groups[0].code||'');
}
function drawGantt(code){
 const g=lastGantt;if(!g)return;
 const bars=(g.bars||[]).filter(b=>(b.code||'')===code);
 const dates=[];
 for(const b of bars)for(const pair of [b.plan,b.baseline,b.fact])for(const d of pair||[])if(d)dates.push(d);
 if(!dates.length){$('gantt').innerHTML='<div class="muted">По этой статье нет дат.</div>';return}
 dates.sort();
 const t0=new Date(dates[0]).getTime(),t1=new Date(dates[dates.length-1]).getTime()||t0+1;
 const W=940,LEFT=290,RH=30,H=bars.length*RH+34;
 const x=d=>LEFT+(new Date(d).getTime()-t0)/((t1-t0)||1)*(W-LEFT-14);
 let svg='<svg width="'+W+'" height="'+H+'" xmlns="http://www.w3.org/2000/svg">';
 const y0=new Date(dates[0]).getFullYear(),y1=new Date(dates[dates.length-1]).getFullYear();
 for(let y=y0;y<=y1;y++)for(const m of [0,3,6,9]){
  const d=new Date(Date.UTC(y,m,1)).toISOString().slice(0,10);
  if(new Date(d).getTime()<t0||new Date(d).getTime()>t1)continue;
  svg+='<line x1="'+x(d)+'" y1="18" x2="'+x(d)+'" y2="'+H+'" stroke="#eef0f3"/>'
   +'<text x="'+x(d)+'" y="12" text-anchor="middle">'+d.slice(0,7)+'</text>';
 }
 const cut=g.cut;
 if(cut)svg+='<line x1="'+x(cut)+'" y1="18" x2="'+x(cut)+'" y2="'+H+'" stroke="#b42318" stroke-dasharray="4 3"/>'
  +'<text x="'+x(cut)+'" y="12" text-anchor="middle" fill="#b42318">срез</text>';
 bars.forEach((b,i)=>{
  const y=26+i*RH;
  const name=(b.name||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
  svg+='<text x="4" y="'+(y+12)+'">'+name.slice(0,44)+(b.slip_days!=null?' ('+(b.slip_days>0?'+':'')+b.slip_days+')':'')+'</text>';
  const seg=(pair,color,y2,h)=>{
   if(!pair||!pair[0]||!pair[1])return;
   const a=x(pair[0]),w=Math.max(2,x(pair[1])-a);
   svg+='<rect x="'+a+'" y="'+y2+'" width="'+w+'" height="'+h+'" rx="2" fill="'+color+'"/>';
  };
  seg(b.baseline,'#c9ced6',y+2,6);
  seg(b.plan,'#7aa5d8',y+9,6);
  seg(b.fact,b.overdue?'#d1493f':'#2f9e63',y+16,6);
 });
 svg+='</svg>';
 $('gantt').innerHTML=svg;
}

// --- переписанное прошлое ---------------------------------------------------
function renderSnapshots(s){
 $('sEstimate').textContent=(s.estimate||[]).length?'снимки: '+s.estimate.join(', '):'';
 $('sProgramme').textContent=(s.programme||[]).length?'снимки: '+s.programme.join(', '):'';
 $('sSchedule').textContent=(s.schedule||[]).length?'снимки: '+s.schedule.join(', '):'';
 $('sProposal').textContent=(s.proposal||[]).length?'снимки: '+s.proposal.join(', '):'';
 $('sSales').textContent=(s.sales||[]).length?'снимки: '+s.sales.join(', '):'';
 const est=s.estimate||[];
 if(est.length>1){
  $('rewrittenCard').style.display='';
  $('rwFirst').innerHTML=est.map(d=>'<option>'+d+'</option>').join('');
  $('rwSecond').innerHTML=est.map(d=>'<option>'+d+'</option>').join('');
  $('rwFirst').value=est[est.length-2];
  $('rwSecond').value=est[est.length-1];
 }
}
$('rwBtn').onclick=async()=>{
 try{
  const d=await apiGet('/monitor/rewritten',{project:$('project').value,
   first:$('rwFirst').value,second:$('rwSecond').value});
  let h='<tr><th class="t">месяц</th><th>в первом</th><th>во втором</th><th>Δ</th></tr>';
  for(const r of d.rows||[]){
   const rewritten=(d.rewritten||[]).some(w=>w.month===r.month);
   h+='<tr'+(rewritten?' style="background:#fef0c7"':'')+'><td class="t">'+r.month+'</td>'
    +'<td>'+mln(r.before)+'</td><td>'+mln(r.after)+'</td>'
    +'<td class="'+(r.delta<0?'neg':'pos')+'">'+mln(r.delta)+'</td></tr>';
  }
  $('rewritten').innerHTML=h;
 }catch(e){$('rewritten').innerHTML='<tr><td class="t">'+e.message+'</td></tr>'}
};

// --- продажи: строки руками -------------------------------------------------
function salesRow(){
 const tr=document.createElement('tr');
 tr.innerHTML='<td class="t"><input type="month" style="width:130px"></td>'
  +'<td><input type="number" style="width:60px"></td>'
  +'<td><input type="number" style="width:80px"></td>'
  +'<td><input type="number" style="width:120px"></td>';
 $('salesRows').appendChild(tr);
}
$('salesAdd').onclick=salesRow;
salesRow();

// --- загрузки ---------------------------------------------------------------
const uploads={
 estimate:async()=>{
  const f=$('fEstimate').files[0];if(!f)throw new Error('выберите файл РСС');
  return api('/monitor/estimate',{project:$('project').value,taken_at:$('dEstimate').value,
   content_base64:await b64(f),filename:f.name});
 },
 programme:async()=>{
  const f=$('fProgramme').files[0];if(!f)throw new Error('выберите файл с шахматкой');
  if(!$('dProgrammeStart').value)throw new Error('укажите первый месяц программы');
  return api('/monitor/programme',{project:$('project').value,taken_at:$('dProgramme').value,
   start:$('dProgrammeStart').value,content_base64:await b64(f)});
 },
 schedule:async()=>{
  const f=$('fGpr').files[0];if(!f)throw new Error('выберите очищенный ГПР');
  const pm=$('fPm').files[0];
  return api('/monitor/schedule',{project:$('project').value,taken_at:$('dSchedule').value,
   gpr_base64:await b64(f),pm_base64:pm?await b64(pm):''});
 },
 proposal:async()=>{
  const f=$('fProposal').files[0];if(!f)throw new Error('выберите файл предложения');
  if(!$('dProposalStart').value)throw new Error('укажите первый месяц предложения');
  return api('/monitor/proposal',{project:$('project').value,taken_at:$('dProposal').value,
   sheet:$('dProposalSheet').value,code:$('dProposalCode').value,
   start:$('dProposalStart').value,content_base64:await b64(f)});
 },
 sales:async()=>{
  const rows=[];
  for(const tr of $('salesRows').querySelectorAll('tr')){
   const inp=tr.querySelectorAll('input');
   if(inp.length<4||!inp[0].value)continue;
   rows.push({month:inp[0].value,units:+inp[1].value||0,area:+inp[2].value||0,revenue:+inp[3].value||0});
  }
  if(!rows.length)throw new Error('заполните хотя бы одну строку');
  return api('/monitor/sales',{project:$('project').value,taken_at:$('dSales').value,rows});
 },
 salesFile:async()=>{
  const f=$('fSales').files[0];if(!f)throw new Error('выберите файл книги');
  return api('/monitor/sales',{project:$('project').value,taken_at:$('dSales').value,
   content_base64:await b64(f)});
 },
};
for(const btn of document.querySelectorAll('button[data-up]')){
 btn.onclick=async()=>{
  const kind=btn.dataset.up;
  const msg=$('m'+kind[0].toUpperCase()+kind.slice(1))||$('mSales');
  msg.className='msg';msg.textContent='…';
  btn.disabled=true;
  try{
   await uploads[kind]();
   msg.className='msg ok';msg.textContent='Загружено.';
   refresh();
  }catch(e){msg.className='msg err';msg.textContent=e.message}
  btn.disabled=false;
 };
}

// --- обновление -------------------------------------------------------------
async function refresh(){
 $('viewMsg').className='msg';$('viewMsg').textContent='';
 const project=$('project').value,cut=$('cut').value;
 try{localStorage.setItem('developaid_monitor_project',project)}catch(e){}
 try{
  const s=await apiGet('/monitor/snapshots',{project});
  renderSnapshots(s);
  if((s.estimate||[]).length){
   const d=await api('/monitor/view',{project,cut});
   renderView(d);
  }else{
   $('viewMsg').textContent='Снимков РСС ещё нет — загрузите первый внизу.';
  }
  if((s.schedule||[]).length){
   renderGantt(await api('/monitor/gantt',{project,cut}));
  }
 }catch(e){
  $('viewMsg').className='msg err';$('viewMsg').textContent=e.message;
 }
}
$('refreshBtn').onclick=refresh;
try{const saved=localStorage.getItem('developaid_monitor_project');if(saved)$('project').value=saved}catch(e){}
refresh();
</script>
</body>
</html>
"""
