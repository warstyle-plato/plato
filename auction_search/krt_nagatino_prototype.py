"""Full-screen KRT investment-card prototype for Nagatino.

This is intentionally a presentation prototype over the existing production
sources. It does not introduce a second parser or a second market calculation.
The fixed programme below is the official Nagatino project-decision programme;
live status, market, ranking, requirements and geometry are read from the same
existing endpoints as the production KRT module.
"""

from __future__ import annotations


def nagatino_investment_card_page() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ Нагатино — инвестиционный разбор</title>
<style>
:root{--bg:#f4f4f2;--panel:#fff;--ink:#171717;--muted:#6f706c;--line:#deded9;--soft:#f0f0ed;--accent:#db6b2b;--warn:#9a4f20;--bad:#9f2923;--blue:#245b8a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:inherit}button{font:inherit}.shell{max-width:1480px;margin:0 auto;padding:22px}.crumbs{display:flex;gap:14px;align-items:center;color:var(--muted);font-size:12px;margin-bottom:18px}.crumbs a{text-decoration:none}.hero{background:#fff;border:1px solid var(--line);padding:22px}.hero h1{font-size:28px;line-height:1.08;margin:0 0 6px}.sub{color:var(--muted);font-size:13px}.flags{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0 16px}.flag{border:1px solid var(--line);padding:7px 9px;font-size:12px;font-weight:700;background:#fff}.flag.critical{border-color:#d0a074;background:#fff4ea}.flag.bad{border-color:#d39b98;background:#fff0ef}.flag.info{border-color:#aab9c7;background:#f2f7fb}.kpis{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));border-top:1px solid var(--line);border-left:1px solid var(--line)}.kpi{padding:13px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:#fff}.kpi b{display:block;font-size:22px;line-height:1.1}.kpi span{display:block;color:var(--muted);font-size:11px;margin-top:4px}.grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(330px,.75fr);gap:16px;margin-top:16px}.card{background:#fff;border:1px solid var(--line);margin-bottom:16px}.card>header{padding:12px 15px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;justify-content:space-between;gap:12px}.card>header h2{font-size:15px;margin:0}.card>header span{font-size:11px;color:var(--muted);text-align:right}.body{padding:15px}.mapstage{height:470px;position:relative;overflow:hidden;background:#eee}.mapstage img,.mapstage svg{position:absolute;inset:0;width:100%;height:100%}.mapstage svg{pointer-events:none}.maptools{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:9px}.maptools button{border:1px solid var(--line);background:#fff;padding:7px 10px;cursor:pointer}.maptools button.active{background:#171717;color:#fff}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:8px}.dot{display:inline-block;width:10px;height:10px;margin-right:4px;vertical-align:-1px}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.bucket{border:1px solid var(--line);padding:13px}.bucket h3{font-size:12px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}.metric{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}.metric:last-child{border-bottom:0}.metric b{text-align:right}.bigline{font-size:20px;font-weight:800;margin:0 0 7px}.note{font-size:11px;color:var(--muted)}.notice{padding:10px 11px;background:var(--soft);font-size:12px;margin:10px 0}.notice.warn{background:#fff4ea;color:var(--warn)}.notice.bad{background:#fff0ef;color:var(--bad)}.decision-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.decision{border:1px solid var(--line);padding:12px}.decision b{display:block;font-size:21px}.decision span{font-size:11px;color:var(--muted)}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}td.num{text-align:right;font-weight:700;white-space:nowrap}.scoretop{display:grid;grid-template-columns:120px 1fr;gap:13px}.scorebig{font-size:36px;font-weight:850;line-height:1}.scorebig small{display:block;font-size:11px;color:var(--muted);font-weight:500;margin-top:6px}.components{display:grid;grid-template-columns:1fr 1fr;gap:7px}.component{border:1px solid var(--line);padding:9px}.component b{font-size:18px}.component span{display:block;font-size:11px;color:var(--muted)}.why{margin-top:12px}.whyrow{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}.whyrow .value{font-size:11px;color:var(--muted)}.whyrow .weight{font-size:11px;color:var(--muted)}.whyrow .pts{font-weight:800}.actionbar{display:flex;gap:7px;flex-wrap:wrap}.actionbar button,.actionbar a{border:1px solid var(--line);background:#fff;color:var(--ink);text-decoration:none;padding:8px 10px;cursor:pointer}.actionbar .primary{background:#171717;color:#fff}.sticky{position:sticky;top:10px}.hidden{display:none!important}details{border-top:1px solid var(--line);margin-top:10px;padding-top:8px}summary{cursor:pointer;font-weight:700;font-size:12px}.statusline{font-weight:800;font-size:16px;margin-bottom:5px}.list{display:grid;gap:6px}.item{border:1px solid var(--line);padding:9px;font-size:12px}.item b{display:block;margin-bottom:2px}.muted{color:var(--muted)}.source{font-size:11px;color:var(--muted);margin-top:8px}.money{font-variant-numeric:tabular-nums;font-weight:800}.section-title{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:15px 0 7px}
@media(max-width:1050px){.grid{grid-template-columns:1fr}.sticky{position:static}.kpis{grid-template-columns:repeat(3,1fr)}}
@media(max-width:680px){.shell{padding:10px}.hero{padding:15px}.hero h1{font-size:22px}.kpis{grid-template-columns:repeat(2,1fr)}.two,.decision-grid,.scoretop,.components{grid-template-columns:1fr}.mapstage{height:380px}.whyrow{grid-template-columns:1fr auto}.whyrow .weight{grid-column:1/-1}}
</style>
</head>
<body>
<div class="shell">
 <div class="crumbs"><a href="/auctions">← КРТ Москвы</a><span>живой прототип карточки</span></div>
 <section class="hero">
  <h1>Варшавское ш., влд. 37 / Нагатинская ул., влд. 3А</h1>
  <div class="sub">ЮАО · Нагатино-Садовники · КРТ нежилой застройки · 14,62 га</div>
  <div class="flags" id="flags"><span class="flag">Загружаю статус…</span></div>
  <div class="kpis">
   <div class="kpi"><b>443 700</b><span>м² общий объём по проекту решения</span></div>
   <div class="kpi"><b>229 490</b><span>м² жильё</span></div>
   <div class="kpi"><b id="commercialHousing">229 490</b><span>м² коммерческий жилой остаток</span></div>
   <div class="kpi"><b id="marketPrice">—</b><span>₽/м² окружение</span></div>
   <div class="kpi"><b id="marketPace">—</b><span>ДДУ/мес. окружение</span></div>
   <div class="kpi"><b id="scoreKpi">—</b><span>балл возможности v2</span></div>
  </div>
 </section>

 <div class="grid">
  <main>
   <section class="card">
    <header><h2>Территория и рынок</h2><span>одна карта · разные слои</span></header>
    <div class="body">
     <div class="maptools">
      <button id="viewSite" class="active">Территория</button>
      <button id="viewMarket">Рынок 3 км</button>
      <button id="toggleLands">Участки</button>
      <button id="toggleObjects">Объекты</button>
     </div>
     <div id="map" class="mapstage"><div class="notice">Загружаю официальный контур…</div></div>
     <div class="legend"><span><i class="dot" style="background:#c03b32"></i>контур КРТ</span><span><i class="dot" style="background:#d7a23c"></i>участки</span><span><i class="dot" style="background:#777"></i>объекты</span><span><i class="dot" style="background:#245b8a"></i>рынок 3 км</span></div>
     <div class="source" id="mapNote"></div>
    </div>
   </section>

   <section class="card">
    <header><h2>Что разрешил построить город</h2><span>проект решения mos.ru</span></header>
    <div class="body">
     <div class="decision-grid">
      <div class="decision"><b>229 490 м²</b><span>жильё</span></div>
      <div class="decision"><b>185 460 м²</b><span>общественно-деловое</span></div>
      <div class="decision"><b>1 000 мест</b><span>СОШ · площадь вторична</span></div>
      <div class="decision"><b>350 мест</b><span>ДОО · площадь вторична</span></div>
     </div>
     <div class="notice">Коммунальный объект — не менее 230 м². СОШ и ДОО подлежат передаче Москве. Параметры проекта решения могут уточняться при утверждении документации по планировке.</div>
     <div class="source">Источник программы: <a target="_blank" rel="noopener" href="https://www.mos.ru/dgp/documents/view/336313220/">проект решения на mos.ru</a>. Здесь не используется карточочное «нежилое 52 510 м²» как замена структуре решения.</div>
    </div>
   </section>

   <section class="card">
    <header><h2>Что получает инвестор / что принимает на себя</h2><span>экономический смысл решения</span></header>
    <div class="body two">
     <div class="bucket">
      <h3>Получает</h3>
      <div class="metric"><span>Общий объём</span><b>443 700 м²</b></div>
      <div class="metric"><span>Жильё</span><b>229 490 м²</b></div>
      <div class="metric"><span>Общественно-деловое</span><b>185 460 м²</b></div>
      <div class="metric"><span>Предельный срок реализации</span><b>9 лет</b></div>
     </div>
     <div class="bucket">
      <h3>Городская нагрузка</h3>
      <div class="metric"><span>Жильё для реновации</span><b id="renoBurden">читаю решение…</b></div>
      <div class="metric"><span>СОШ</span><b>1 000 мест</b></div>
      <div class="metric"><span>ДОО</span><b>350 мест</b></div>
      <div class="metric"><span>Коммунальный объект</span><b>≥ 230 м²</b></div>
      <div class="metric"><span>Снос / реконструкция</span><b id="demoBurden">читаю…</b></div>
     </div>
    </div>
   </section>

   <section class="card">
    <header><h2>Территория сейчас</h2><span>участки, здания, судьба объектов</span></header>
    <div class="body">
     <div id="territoryStats" class="kpis" style="grid-template-columns:repeat(4,1fr);border-top:1px solid var(--line)"></div>
     <div id="objectsTable" style="margin-top:12px"><div class="notice">Загружаю перечень объектов…</div></div>
    </div>
   </section>

   <section class="card">
    <header><h2>Рынок и экономика DevelopAid</h2><span>живой отчёт, если уже посчитан</span></header>
    <div class="body" id="economics"><div class="notice">Открываю сохранённый отчёт…</div></div>
   </section>

   <section class="card">
    <header><h2>Публичный контекст</h2><span>оператор, застройщик, связь с большим проектом</span></header>
    <div class="body" id="publicContext"><div class="notice">Читаю сохранённые факты…</div></div>
   </section>
  </main>

  <aside>
   <div class="sticky">
    <section class="card">
     <header><h2>Вход в проект</h2><span>не путать со статусом города</span></header>
     <div class="body" id="entry"><div class="notice">Загружаю торги и статус…</div></div>
    </section>

    <section class="card">
     <header><h2>Балл возможности</h2><span>почему именно столько</span></header>
     <div class="body" id="score"><div class="notice">Собираю компоненты…</div></div>
    </section>

    <section class="card">
     <header><h2>Действия</h2><span>рабочие переходы</span></header>
     <div class="body actionbar">
      <a class="primary" href="/auctions">Открыть список КРТ</a>
      <a href="/krt/nagatino">Разбор территории</a>
      <a href="/auctions/krt-lab">Лаборатория балла</a>
      <a target="_blank" rel="noopener" href="https://www.mos.ru/dgp/documents/view/336313220/">Решение mos.ru</a>
     </div>
    </section>
   </div>
  </aside>
 </div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=(v,d=0)=>v===null||v===undefined||v===''||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:d});
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v===null||v===undefined||v===''||!Number.isFinite(Number(v))?null:Number(v);
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const piece=(x,stops)=>{x=num(x);if(x===null)return null;if(x<=stops[0][0])return stops[0][1];for(let i=1;i<stops.length;i++){const [a,b]=stops[i-1],[c,d]=stops[i];if(x<=c){const t=(x-a)/(c-a||1);return b+(d-b)*t}}return stops[stops.length-1][1]};
async function j(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok){const e=new Error(url+' → '+r.status);e.status=r.status;throw e}return r.json()}
function findNagatino(projects){
 const rows=projects||[];
 return rows.find(p=>Math.abs(Number(p.area_ha||0)-14.62)<.08 && /нагатин/i.test([p.name,p.address,p.district].join(' ')))
  ||rows.find(p=>/варшавск[^0-9]{0,50}37/i.test([p.name,p.address].join(' '))&&/нагатин/i.test([p.name,p.address,p.district].join(' ')));
}
function activeTender(row){return (row.tender_lots||[]).find(x=>['future','active','open','now'].includes(String(x.moment||x.status||'').toLowerCase())||(!x.moment&&!x.ended))}
function operatorInfo(row){
 const c=row.card_facts||{},p=row.press_facts||{},dev=(c.developers||[]).filter(Boolean);
 const taken=!!(p.taken||p.operator_name||((p.agreement||[]).length));
 return {taken,confirmed:!!(p.operator_name||(p.agreement||[]).length),operator:p.operator_name||'',developers:dev,selling:(p.selling_now||[]),probed:!!p.probed};
}
function comp(items){const known=items.filter(x=>x.s!==null),sum=known.reduce((z,x)=>z+x.w,0);return {score:sum?100*known.reduce((z,x)=>z+x.w*clamp(x.s),0)/sum:null,known:sum,total:items.reduce((z,x)=>z+x.w,0),items}}
function scoreV2(row,req){
 const ren=req.renovation||{},area=num(row.area_ha),demo=num(req.demolition_area_sqm),cond=num(req.conditional_area_sqm);
 const t=(name,fallback=[])=>Array.isArray(req[name])?req[name]:fallback;
 const res=t('resettlement').length||num(req.resettlement_mentions);
 const renShare=num(ren.area_sqm)!==null?num(ren.area_sqm)/(num(row.housing_gfa_sqm)||num(ren.housing_sqm)||1):null;
 const op=operatorInfo(row),tender=activeTender(row),status=String(row.status_kind||'');
 const eco=[
  {l:'Потолок цены входа',v:num(row.entry_capacity_rub_per_sqm),u:'₽/м²',w:20,s:piece(row.entry_capacity_rub_per_sqm,[[0,0],[100000,.18],[200000,.38],[350000,.65],[550000,.88],[750000,1]])},
  {l:'LLCR проекта',v:num(row.project_llcr_x),u:'x',w:15,s:piece(row.project_llcr_x,[[.9,0],[1,.12],[1.1,.42],[1.2,.72],[1.3,.9],[1.45,1]])},
  {l:'Маржа',v:num(row.margin_pct),u:'%',w:10,s:piece(row.margin_pct,[[-5,0],[0,.08],[7,.32],[12,.58],[18,.82],[25,1]])}
 ];
 const mkt=[
  {l:'Цена окружения',v:num(row.surrounding_price_rub_sqm),u:'₽/м²',w:8,s:piece(row.surrounding_price_rub_sqm,[[200000,0],[300000,.18],[450000,.45],[600000,.7],[800000,.9],[1000000,1]])},
  {l:'Продажи окружения',v:num(row.surrounding_sales_units_per_month),u:'ДДУ/мес.',w:12,s:piece(row.surrounding_sales_units_per_month,[[0,0],[3,.15],[7,.35],[12,.58],[20,.82],[30,1]])}
 ];
 const dd=demo!==null&&area?demo/area:null,cd=cond!==null&&area?cond/area:null;
 const bur=[
  {l:'Снос на гектар',v:dd,u:'м²/га',w:8,s:dd===null?null:1-piece(dd,[[0,0],[500,.08],[1500,.25],[3000,.55],[5000,.82],[7000,1]])},
  {l:'Доля реновации',v:renShare===null?null:renShare*100,u:'%',w:7,s:renShare===null?null:1-piece(renShare,[[0,0],[.05,.08],[.15,.3],[.3,.62],[.5,.9],[.7,1]])},
  {l:'Расселение / изъятие',v:res||0,u:'упомин.',w:5,s:res==null?null:(res<=0?1:res===1?.48:res<=3?.25:0)},
  {l:'Снос или реконструкция / га',v:cd,u:'м²/га',w:5,s:cd===null?null:1-piece(cd,[[0,0],[300,.1],[1000,.35],[2500,.7],[4500,1]])}
 ];
 const acc=[
  {l:'Оператор / занятость',v:op.confirmed?(op.taken?'занята':'свободна'):(op.probed?'не найден':'не проверено'),u:'',w:7,s:op.probed?(op.taken?.15:1):null},
  {l:'Стадия входа / торги',v:tender?'активные торги':status,u:'',w:3,s:tender?1:(status==='planned'?.58:status==='draft'?.32:.2)}
 ];
 const C={eco:comp(eco),mkt:comp(mkt),bur:comp(bur),acc:comp(acc)},W={eco:45,mkt:20,bur:25,acc:10};
 let got=0,used=0,known=0,total=0;Object.keys(W).forEach(k=>{const w=W[k],c=C[k];total+=w;known+=w*(c.total?c.known/c.total:0);if(c.score!==null){got+=w*c.score;used+=w}});
 const raw=used?got/used:null,coverage=total?100*known/total:0,score=raw===null?null:raw*(.65+.35*coverage/100);
 return {...C,raw,coverage,score,detail:{eco,mkt,bur,acc}};
}
function renderScore(sc){
 $('scoreKpi').textContent=sc.score===null?'—':Math.round(sc.score);
 const groups=[['Экономика',45,'eco'],['Рынок',20,'mkt'],['Нагрузка КРТ',25,'bur'],['Доступность входа',10,'acc']];
 const val=r=>r.v===null||r.v===undefined?'нет данных':(typeof r.v==='string'?r.v:fmt(r.v,r.u==='x'?2:(r.u==='%'||r.u==='ДДУ/мес.')?1:0)+(r.u?' '+r.u:''));
 const factor=.65+.35*sc.coverage/100;
 $('score').innerHTML='<div class="scoretop"><div class="scorebig">'+(sc.score===null?'—':Math.round(sc.score))+'/100<small>итоговый балл</small></div><div class="components">'+groups.map(g=>'<div class="component"><b>'+fmt(sc[g[2]].score,0)+'</b><span>'+g[0]+' · '+g[1]+'%</span></div>').join('')+'</div></div>'
  +'<div class="source">Сырой '+fmt(sc.raw,0)+' · покрытие '+fmt(sc.coverage,0)+'% · коэффициент полноты '+factor.toFixed(2)+' · итог '+fmt(sc.score,0)+'.</div>'
  +groups.map(g=>'<div class="why"><div class="section-title">'+g[0]+' · '+g[1]+'%</div>'+sc.detail[g[2]].map(r=>'<div class="whyrow"><div><b>'+esc(r.l)+'</b><div class="value">'+esc(val(r))+(r.v===null||r.v===undefined?' · неизвестное не стало нулём':'')+'</div></div><div class="weight">вес '+r.w+'</div><div class="pts">'+fmt(r.s===null?null:r.s*100,0)+'</div></div>').join('')+'</div>').join('');
}
function renderFlags(p,rank,req){
 const ren=req.renovation||{},op=operatorInfo({...p,...rank}),t=activeTender({...p,...rank});
 const bits=[];
 bits.push('<span class="flag">'+esc(p.status||'КРТ')+'</span>');
 if(ren.mentioned&&num(ren.area_sqm)!==null){
  const share=num(ren.area_sqm)/(num(p.housing_gfa_sqm)||229490);
  bits.push('<span class="flag critical">Реновация '+fmt(share*100,0)+'% жилья · '+fmt(ren.area_sqm)+' м²</span>');
  $('commercialHousing').textContent=fmt(Math.max(0,229490-num(ren.area_sqm)));
  $('renoBurden').textContent=fmt(ren.area_sqm)+' м²';
 }else if(ren.mentioned){bits.push('<span class="flag critical">Реновация упомянута · объём не назван</span>');$('commercialHousing').textContent='не определён';$('renoBurden').textContent='объём не назван'}
 else{bits.push('<span class="flag">Реновация в прочитанном решении не найдена</span>');$('renoBurden').textContent='не найдена в решении'}
 if(t)bits.push('<span class="flag info">Активные торги</span>');
 else bits.push('<span class="flag info">Торги: проверяется по рабочему модулю</span>');
 if(op.confirmed&&op.operator)bits.push('<span class="flag bad">Оператор: '+esc(op.operator)+'</span>');
 else if(op.taken)bits.push('<span class="flag bad">Есть подтверждённый признак занятости</span>');
 else bits.push('<span class="flag">Оператор официально не подтверждён</span>');
 if(op.selling.length)bits.push('<span class="flag critical">Есть сигнал связи с уже продающимся проектом · требует проверки</span>');
 else if(op.developers.length)bits.push('<span class="flag critical">Назван застройщик · это не равно оператору КРТ</span>');
 else bits.push('<span class="flag">Связь с большим действующим проектом не подтверждена</span>');
 $('flags').innerHTML=bits.join('');
}
function renderEntry(p,rank){
 const row={...p,...rank},live=activeTender(row),op=operatorInfo(row);
 let title=live?'Идёт аукцион — вход открыт':op.taken?'Вход закрыт / площадка занята':'Оператор не подтверждён';
 let cls=op.taken?'bad':live?'':'warn',facts=[];
 if(live){if(live.deadline)facts.push('Заявки до '+live.deadline);if(live.price_rub)facts.push('Цена права '+fmt(live.price_rub/1e6,1)+' млн ₽');if(live.source)facts.push(live.source)}
 else facts.push('Официальное извещение по Нагатино от 14.08.2026 есть в рабочем пакете; живой лот показывается только если он связан общим модулем торгов.');
 $('entry').innerHTML='<div class="statusline">'+esc(title)+'</div><div class="notice '+cls+'">'+facts.map(esc).join(' · ')+'</div>'
  +(op.operator?'<div class="metric"><span>Оператор</span><b>'+esc(op.operator)+'</b></div>':'')
  +(op.developers.length?'<div class="metric"><span>Названный застройщик</span><b>'+esc(op.developers.join(', '))+'</b></div>':'');
}
function renderEconomics(rank,report){
 $('marketPrice').textContent=fmt(rank.surrounding_price_rub_sqm);
 $('marketPace').textContent=fmt(rank.surrounding_sales_units_per_month,1);
 const s=report&&report.screening||{},m=s.metrics||{},cap=s.entry_capacity||{},market=report&&report.market||{};
 const price=rank.surrounding_price_rub_sqm||((market.analysis||{}).site||{}).price_per_sqm||((market.price_hint||{}).price_per_sqm);
 $('economics').innerHTML='<div class="decision-grid">'
  +'<div class="decision"><b>'+fmt(m.project_llcr_x,2)+'x</b><span>LLCR проекта</span></div>'
  +'<div class="decision"><b>'+fmt(m.margin_pct,1)+'%</b><span>маржа</span></div>'
  +'<div class="decision"><b>'+fmt(rank.entry_capacity_mln,0)+' млн ₽</b><span>потолок входа</span></div>'
  +'<div class="decision"><b>'+fmt(price,0)+' ₽/м²</b><span>рыночный ориентир</span></div></div>'
  +'<div class="notice">'+(s.available?esc(s.text||s.headline||'Модель посчитана'):'Сохранённый расчёт модели отсутствует или недоступен.')+'</div>';
}
function renderPublic(rank){
 const op=operatorInfo(rank),p=rank.press_facts||{},rows=[];
 if(op.operator)rows.push(['Оператор',op.operator,'подтверждён сохранённым источником']);
 if(op.developers.length)rows.push(['Застройщик',op.developers.join(', '),'само по себе не означает оператора КРТ']);
 if(op.selling.length)rows.push(['Связь с действующим проектом','Есть сигнал продажи ЖК рядом / по адресу','не объявляем частью КРТ без отдельного подтверждения']);
 if((p.agreement||[]).length)rows.push(['Договор КРТ','найдено упоминание','сильный признак занятости']);
 $('publicContext').innerHTML=rows.length?'<div class="list">'+rows.map(r=>'<div class="item"><b>'+esc(r[0])+' · '+esc(r[1])+'</b><div class="muted">'+esc(r[2])+'</div></div>').join('')+'</div>':'<div class="notice">Сохранённых подтверждённых признаков оператора или связи с крупным реализуемым проектом сейчас нет. Это не доказательство отсутствия связи.</div>';
}
function renderTerritory(req,parcels){
 const objects=(parcels&&parcels.territory&&parcels.territory.objects)||[];
 const lands=(parcels&&parcels.territory&&parcels.territory.lands)||[];
 const actions=(req.object_actions||[]);
 const source=objects.length?objects:actions.map(x=>({cadastral_number:x.cadastral_number||'',address:x.label||x.address||'',area_sqm:x.area_sqm,fate:x.category||''}));
 const kind=f=>{f=String(f||'').toLowerCase();if(f.includes('demolition_or_reconstruction')||f.includes('снос')&&f.includes('рекон'))return 'Снос / реконструкция';if(f.includes('demolition')||f.includes('снос'))return 'Снос';if(f.includes('reconstruction')||f.includes('рекон'))return 'Реконструкция';if(f.includes('preservation')||f.includes('сохран'))return 'Сохранение';return 'Не определено'};
 const counts={};source.forEach(o=>counts[kind(o.fate)]=(counts[kind(o.fate)]||0)+1);
 $('territoryStats').innerHTML=[
  [lands.length||'—','земельных участков'],
  [source.length||'—','объектов'],
  [counts['Снос']||0,'под снос'],
  [(counts['Реконструкция']||0)+(counts['Сохранение']||0),'реконструкция / сохранение']
 ].map(x=>'<div class="kpi"><b>'+x[0]+'</b><span>'+x[1]+'</span></div>').join('');
 $('demoBurden').textContent=(counts['Снос']||0)+' снос · '+(counts['Снос / реконструкция']||0)+' снос/реконструкция';
 $('objectsTable').innerHTML=source.length?'<table><thead><tr><th>КН / адрес</th><th>Объект</th><th>Площадь</th><th>Действие</th></tr></thead><tbody>'+source.slice(0,40).map(o=>'<tr><td>'+esc(o.cadastral_number||o.address||'—')+'</td><td>'+esc(o.name||o.purpose||o.address||'—')+'</td><td class="num">'+fmt(o.area_sqm)+' м²</td><td>'+esc(kind(o.fate))+'</td></tr>').join('')+'</tbody></table>':'<div class="notice">Перечень существующих объектов в текущем ответе не получен.</div>';
}
let MAP={point:null,parcels:null,market:false,lands:false,objects:false};
const MERC=20037508.342789244, mx=lon=>Number(lon)*MERC/180, my=lat=>Math.log(Math.tan((90+Number(lat))*Math.PI/360))*MERC/Math.PI;
function drawMap(){
 const box=$('map'),p=MAP.point;if(!p||!Number.isFinite(Number(p.latitude))){box.innerHTML='<div class="notice">Координаты КРТ не получены.</div>';return}
 const site=(p.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3),parcel=MAP.parcels&&MAP.parcels.territory||{},lands=MAP.lands?(parcel.lands||[]):[],objects=MAP.objects?(parcel.objects||[]):[];
 const center=Array.isArray(p.centre_merc)?p.centre_merc:[mx(p.longitude),my(p.latitude)],lat=Number(p.latitude),k=1/Math.cos(lat*Math.PI/180);
 let pts=site.flat().concat(lands.flatMap(x=>x.rings_merc||[]).flat()).concat(objects.flatMap(x=>x.rings_merc||[]).flat());
 if(!pts.length)pts=[center];
 let xs=pts.map(x=>x[0]),ys=pts.map(x=>x[1]),ax=Math.min(...xs),bx=Math.max(...xs),ay=Math.min(...ys),by=Math.max(...ys);
 if(MAP.market){const r=3000*k;ax=center[0]-r;bx=center[0]+r;ay=center[1]-r;by=center[1]+r}else{const w=Math.max(700*k,(bx-ax)*1.55),h=Math.max(700*k,(by-ay)*1.55),side=Math.max(w,h);ax=center[0]-side/2;bx=center[0]+side/2;ay=center[1]-side/2;by=center[1]+side/2}
 const W=1100,H=620,px=x=>(x-ax)/(bx-ax)*W,py=y=>(by-y)/(by-ay)*H,path=rings=>rings.map(r=>'M'+r.map(q=>px(q[0]).toFixed(1)+' '+py(q[1]).toFixed(1)).join('L')+'Z').join(' ');
 const base='/land/basemap?'+new URLSearchParams({bbox:[ax,ay,bx,by].join(','),width:'1100'});
 const sitePath=site.length?'<path d="'+path(site)+'" fill="#c03b32" fill-opacity=".16" stroke="#c03b32" stroke-width="4" vector-effect="non-scaling-stroke"/>':'';
 const landPaths=lands.map(x=>'<path d="'+path(x.rings_merc||[])+'" fill="#d7a23c" fill-opacity=".18" stroke="#b88218" stroke-width="1.5" vector-effect="non-scaling-stroke"/>').join('');
 const objPaths=objects.map(x=>'<path d="'+path(x.rings_merc||[])+'" fill="#777" fill-opacity=".35" stroke="#555" stroke-width="1" vector-effect="non-scaling-stroke"/>').join('');
 const mr=3000*k,market='<ellipse cx="'+px(center[0]).toFixed(1)+'" cy="'+py(center[1]).toFixed(1)+'" rx="'+((mr/(bx-ax))*W).toFixed(1)+'" ry="'+((mr/(by-ay))*H).toFixed(1)+'" fill="none" stroke="#245b8a" stroke-width="4" stroke-dasharray="12 8" vector-effect="non-scaling-stroke"/>';
 box.innerHTML='<img src="'+base+'" alt="OSM"><svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+landPaths+objPaths+sitePath+market+'</svg>';
 $('mapNote').textContent=(p.geometry_status==='official_polygon'?'Контур — официальный полигон реестра КРТ. ':'Контур — '+(p.geometry_status||'рабочий источник')+'. ')+(MAP.parcels?'Доступен слой кадастровых участков и объектов.':'Детальный слой территории потребует авторизации в модуле Нагатино.');
}
function bindMap(){
 $('viewSite').onclick=()=>{MAP.market=false;$('viewSite').classList.add('active');$('viewMarket').classList.remove('active');drawMap()};
 $('viewMarket').onclick=()=>{MAP.market=true;$('viewMarket').classList.add('active');$('viewSite').classList.remove('active');drawMap()};
 $('toggleLands').onclick=()=>{MAP.lands=!MAP.lands;$('toggleLands').classList.toggle('active',MAP.lands);drawMap()};
 $('toggleObjects').onclick=()=>{MAP.objects=!MAP.objects;$('toggleObjects').classList.toggle('active',MAP.objects);drawMap()};
}
async function boot(){
 bindMap();
 const [cat,ranking]=await Promise.all([j('/auctions/krt'),j('/auctions/krt/ranking')]);
 const p=findNagatino(cat.projects||[]);if(!p)throw new Error('Нагатино не найдено в текущем каталоге КРТ');
 const rank=(ranking.rows||[]).find(x=>String(x.slug||'')===String(p.slug||''))||{};
 const row={...p,...rank,status:p.status,status_kind:p.status_kind,area_ha:p.area_ha,housing_gfa_sqm:p.housing_gfa_sqm||229490};
 const [reqRes,pointRes,reportRes,parcelsRes]=await Promise.allSettled([
  j('/auctions/krt/'+encodeURIComponent(p.slug)+'/requirements'),
  j('/auctions/krt/'+encodeURIComponent(p.slug)+'/point'),
  j('/auctions/krt/'+encodeURIComponent(p.slug)+'/report'),
  j('/krt/nagatino/parcels')
 ]);
 const req=reqRes.status==='fulfilled'?reqRes.value:{};
 const point=pointRes.status==='fulfilled'?pointRes.value:null;
 const report=reportRes.status==='fulfilled'?reportRes.value:null;
 const parcels=parcelsRes.status==='fulfilled'?parcelsRes.value:null;
 MAP.point=point;MAP.parcels=parcels;
 const sc=scoreV2(row,req);
 renderFlags(p,rank,req);renderEntry(p,rank);renderScore(sc);renderEconomics(rank,report);renderPublic(rank);renderTerritory(req,parcels);drawMap();
}
boot().catch(e=>{document.querySelector('.shell').insertAdjacentHTML('afterbegin','<div class="notice bad"><b>Не удалось собрать живую карточку:</b> '+esc(e.message||e)+'</div>')});
</script>
</body>
</html>"""
