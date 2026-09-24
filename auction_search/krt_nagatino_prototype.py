"""Full-screen KRT investment-card prototype for Nagatino.

This is intentionally a presentation prototype over the existing production
sources. It does not introduce a second parser or a second market calculation.
The fixed programme below is the official Nagatino project-decision programme;
live status, market, ranking, requirements and geometry are read from the same
existing endpoints as the production KRT module.
"""

from __future__ import annotations


def nagatino_investment_card_page(footer_html: str = "") -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ Нагатино — инвестиционный разбор</title>
<style>
:root{--bg:#f4f4f2;--panel:#fff;--ink:#171717;--muted:#6f706c;--line:#deded9;--soft:#f0f0ed;--accent:#db6b2b;--warn:#9a4f20;--bad:#9f2923;--blue:#245b8a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:inherit}button{font:inherit}.shell{max-width:1480px;margin:0 auto;padding:22px}.brandbar{height:48px;display:flex;align-items:center;margin-bottom:10px}.brandbar img{height:32px;width:auto;display:block}.crumbs{display:flex;gap:14px;align-items:center;color:var(--muted);font-size:12px;margin-bottom:18px}.crumbs a{text-decoration:none}.hero{background:#fff;border:1px solid var(--line);padding:22px}.hero h1{font-size:28px;line-height:1.08;margin:0 0 6px}.sub{color:var(--muted);font-size:13px}.flags{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0 16px}.flag{border:1px solid var(--line);padding:7px 9px;font-size:12px;font-weight:700;background:#fff}.flag.critical{border-color:#d0a074;background:#fff4ea}.flag.bad{border-color:#d39b98;background:#fff0ef}.flag.info{border-color:#aab9c7;background:#f2f7fb}.kpis{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));border-top:1px solid var(--line);border-left:1px solid var(--line)}.kpi{padding:13px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:#fff}.kpi b{display:block;font-size:22px;line-height:1.1}.kpi span{display:block;color:var(--muted);font-size:11px;margin-top:4px}.grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(330px,.75fr);gap:16px;margin-top:16px}.card{background:#fff;border:1px solid var(--line);margin-bottom:16px}.card>header{padding:12px 15px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;justify-content:space-between;gap:12px}.card>header h2{font-size:15px;margin:0}.card>header span{font-size:11px;color:var(--muted);text-align:right}.body{padding:15px}.mapstage{height:470px;position:relative;overflow:hidden;background:#eee}.mapstage img,.mapstage svg{position:absolute;inset:0;width:100%;height:100%}.mapstage svg{pointer-events:none}.maptools{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:9px}.maptools button{border:1px solid var(--line);background:#fff;padding:7px 10px;cursor:pointer}.maptools button.active{background:#171717;color:#fff}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:8px}.dot{display:inline-block;width:10px;height:10px;margin-right:4px;vertical-align:-1px}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.bucket{border:1px solid var(--line);padding:13px}.bucket h3{font-size:12px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}.metric{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}.metric:last-child{border-bottom:0}.metric b{text-align:right}.bigline{font-size:20px;font-weight:800;margin:0 0 7px}.note{font-size:11px;color:var(--muted)}.notice{padding:10px 11px;background:var(--soft);font-size:12px;margin:10px 0}.notice.warn{background:#fff4ea;color:var(--warn)}.notice.bad{background:#fff0ef;color:var(--bad)}.decision-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.decision{border:1px solid var(--line);padding:12px}.decision b{display:block;font-size:21px}.decision span{font-size:11px;color:var(--muted)}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}td.num{text-align:right;font-weight:700;white-space:nowrap}.scoretop{display:grid;grid-template-columns:120px 1fr;gap:13px}.scorebig{font-size:36px;font-weight:850;line-height:1}.scorebig small{display:block;font-size:11px;color:var(--muted);font-weight:500;margin-top:6px}.components{display:grid;grid-template-columns:1fr 1fr;gap:7px}.component{border:1px solid var(--line);padding:9px}.component b{font-size:18px}.component span{display:block;font-size:11px;color:var(--muted)}.why{margin-top:12px}.whyrow{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}.whyrow .value{font-size:11px;color:var(--muted)}.whyrow .weight{font-size:11px;color:var(--muted)}.whyrow .pts{font-weight:800}.actionbar{display:flex;gap:7px;flex-wrap:wrap}.actionbar button,.actionbar a{border:1px solid var(--line);background:#fff;color:var(--ink);text-decoration:none;padding:8px 10px;cursor:pointer}.actionbar .primary{background:#171717;color:#fff}.sticky{position:sticky;top:10px}.hidden{display:none!important}details{border-top:1px solid var(--line);margin-top:10px;padding-top:8px}summary{cursor:pointer;font-weight:700;font-size:12px}.statusline{font-weight:800;font-size:16px;margin-bottom:5px}.list{display:grid;gap:6px}.item{border:1px solid var(--line);padding:9px;font-size:12px}.item b{display:block;margin-bottom:2px}.muted{color:var(--muted)}.source{font-size:11px;color:var(--muted);margin-top:8px}.legal-footer{max-width:1480px;margin:8px auto 18px;padding:14px 22px;border-top:1px solid var(--line);display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:11px}.legal-footer a{text-decoration:none;border-bottom:1px solid var(--line)}.money{font-variant-numeric:tabular-nums;font-weight:800}.section-title{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:15px 0 7px}
@media(max-width:1050px){.grid{grid-template-columns:1fr}.sticky{position:static}.kpis{grid-template-columns:repeat(3,1fr)}}
@media(max-width:680px){.shell{padding:10px}.hero{padding:15px}.hero h1{font-size:22px}.kpis{grid-template-columns:repeat(2,1fr)}.two,.decision-grid,.scoretop,.components{grid-template-columns:1fr}.mapstage{height:380px}.whyrow{grid-template-columns:1fr auto}.whyrow .weight{grid-column:1/-1}}
</style>
</head>
<body>
<div class="shell">
 <header class="brandbar"><a href="/" aria-label="DevelopAid"><img src="/guide/assets/logo.webp" alt="DevelopAid"></a></header>
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
    <header><h2>Программа проекта и городская нагрузка</h2><span>что можно построить и что нужно отдать / выполнить</span></header>
    <div class="body two">
     <div class="bucket">
      <h3>Потенциал проекта</h3>
      <div class="metric"><span>Общий объём</span><b>443 700 м²</b></div>
      <div class="metric"><span>Жильё</span><b>229 490 м²</b></div>
      <div class="metric"><span>Общественно-деловое</span><b>185 460 м²</b></div>
      <div class="metric"><span>Срок реализации</span><b>9 лет</b></div>
     </div>
     <div class="bucket">
      <h3>Городская нагрузка</h3>
      <div class="metric"><span>Жильё для реновации</span><b id="renoBurden">читаю решение…</b></div>
      <div class="metric"><span>СОШ</span><b>1 000 мест</b></div>
      <div class="metric"><span>ДОО</span><b>350 мест</b></div>
      <div class="metric"><span>Коммунальная инфраструктура</span><b>≥ 230 м²</b></div>
      <div class="metric"><span>Снос / реконструкция</span><b id="demoBurden">читаю…</b></div>
      <div class="source">СОШ и ДОО передаются Москве.</div>
     </div>
    </div>
    <div class="body" style="padding-top:0">
     <div class="source">Источник: <a target="_blank" rel="noopener" href="https://www.mos.ru/dgp/documents/view/336313220/">проект решения на mos.ru</a></div>
    </div>
   </section>

   <section class="card">
    <header><h2>Территория сейчас</h2><span>сводка сверху · детализация по раскрытию</span></header>
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
    <header>
     <h2>Публичный контекст</h2>
     <div class="actionbar">
      <button type="button" id="refreshPublic">Обновить поиск в публичном пространстве</button>
     </div>
    </header>
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
     <header><h2>Рейтинг КРТ</h2><span>4 независимых оценки · 0–100</span></header>
     <div class="body">
      <div class="metric" style="align-items:center">
       <span>Ценовой ориентир, ₽/м²</span>
       <div style="display:flex;gap:6px;align-items:center">
        <input id="priceTarget" inputmode="numeric" type="number" min="1" step="10000" value="600000" style="width:120px;padding:7px 8px;border:1px solid var(--line);font:inherit">
        <button id="recalcScore" type="button">Пересчитать</button>
       </div>
      </div>
      <div id="score"><div class="notice">Читаю backend breakdown по #485…</div></div>
     </div>
    </section>

    <section class="card">
     <header><h2>Действия</h2><span>по этой площадке</span></header>
     <div class="body actionbar">
      <button class="primary" type="button" id="handoffDevelopAid">Передать в DevelopAid</button>
      <button type="button" id="askPlato">Спросить Платона</button>
      <button type="button" id="shareCard">Поделиться карточкой</button>
      <a href="/krt/nagatino">Разбор территории</a>
      <a target="_blank" rel="noopener" href="https://www.mos.ru/dgp/documents/view/336313220/">Решение mos.ru</a>
      <div id="actionStatus" class="source" style="flex-basis:100%"></div>
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
function scaleText(stops,ratioMode=false){
 return (stops||[]).map(x=>{
  const v=ratioMode?fmt(Number(x[0])*100,0)+'%':fmt(x[0],2);
  return v+' → '+fmt(x[1],0);
 }).join(' · ');
}
function componentLine(key,x){
 const score=x&&x.score;
 const value=x&&x.value,bench=x&&x.benchmark,ratio=x&&x.ratio;
 const parts=[];
 if(key==='llcr'){
  parts.push('LLCR '+fmt(value,3)+'x');
  if(x.entry_capacity_mln!==null&&x.entry_capacity_mln!==undefined)parts.push('предельная цена права '+fmt(x.entry_capacity_mln,1)+' млн ₽');
 }else if(key==='price'){
  parts.push('окружение '+fmt(value,0)+' ₽/м²');
  parts.push('ориентир '+fmt(bench,0)+' ₽/м²');
  parts.push('отношение '+(ratio===null||ratio===undefined?'—':fmt(Number(ratio)*100,1)+'%'));
 }else if(key==='absorption'){
  parts.push('локальная медиана '+fmt(value,0)+' м²/мес.');
  parts.push('Москва по классу '+fmt(bench,0)+' м²/мес.');
  parts.push('отношение '+(ratio===null||ratio===undefined?'—':fmt(Number(ratio)*100,1)+'%'));
 }else if(key==='burden'){
  parts.push('нагрузка '+fmt(value,1)+' млн ₽');
  parts.push('ordinary CAPEX '+fmt(bench,1)+' млн ₽');
  parts.push('доля '+fmt(x.burden_pct,2)+'%');
  if(x.rub_per_housing_sqm!==null&&x.rub_per_housing_sqm!==undefined)parts.push(fmt(x.rub_per_housing_sqm,0)+' ₽/м² жилья');
 }
 return '<div class="why"><div class="whyrow"><div><b>'+esc(x.name||key)+'</b><div class="value">'+esc(parts.join(' · '))+'</div>'
  +(score===null||score===undefined?'<div class="source">'+esc(x.missing_reason||'нет данных')+'</div>':'<div class="source">'+esc(x.formula||'')+'</div>')
  +(x.source?'<div class="source">Источник: '+esc(x.source)+'</div>':'')
  +'</div><div class="pts">'+(score===null||score===undefined?'—':fmt(score,1))+'/100</div></div></div>';
}
function renderMethodology(m){
 if(!m)return '';
 const ex=m.examples||{},rules=m.rules||{},explain=m.explanations||{};
 return '<details style="margin-top:12px"><summary><b>Методика оценки</b></summary>'
  +'<div class="source" style="margin-top:10px">Источник методики: GitHub issue #'+esc(m.issue||485)+'. Формула: '+esc(m.formula||'')+'</div>'
  +'<div class="section-title">LLCR</div><div class="value">'+esc(scaleText(m.llcr_stops,false))+'</div><div class="source">'+esc(ex.llcr||'')+'</div>'
  +'<div class="section-title">Цена рынка</div><div class="value">'+esc(scaleText(m.price_ratio_stops,true))+'</div><div class="source">'+esc(ex.price||'')+'</div>'
  +'<div class="section-title">Поглощение · только м²/мес.</div><div class="value">'+esc(scaleText(m.absorption_ratio_stops,true))+'</div><div class="source">'+esc(ex.absorption||'')+'</div>'
  +'<div class="section-title">Нагрузка КРТ</div><div class="value">'+esc(scaleText(m.burden_pct_stops,false))+'% шкалы нагрузки</div><div class="source">'+esc(ex.burden||'')+'</div>'
  +'<div class="section-title">Линейная интерполяция</div><div class="source">'+esc(m.linear_interpolation||'')+'</div>'
  +'<div class="section-title">Правила полноты</div><div class="source">'+esc(explain.coverage||rules.missing||'')+'</div>'
  +'<div class="source">'+esc(explain.running||rules.running||'')+'</div>'
  +'<div class="source">'+esc(explain.entry_capacity||rules.entry_capacity||'')+'</div>'
  +'</details>';
}
function renderScore(payload){
 const sc=payload&&payload.rating?payload.rating:payload;
 if(!sc){$('score').innerHTML='<div class="notice bad">Backend breakdown рейтинга не получен.</div>';return}
 $('scoreKpi').textContent=sc.display_score===null||sc.display_score===undefined?'—':fmt(sc.display_score,0);
 const C=sc.components||{},order=['llcr','price','absorption','burden'];
 let html='<div class="scoretop"><div class="scorebig">'
  +(sc.display_score===null||sc.display_score===undefined?'—':fmt(sc.display_score,0))
  +'/100<small>инвестиционный рейтинг</small></div><div class="components">'
  +order.map(k=>'<div class="component"><b>'+((C[k]&&C[k].score)!==null&&(C[k]&&C[k].score)!==undefined?fmt(C[k].score,0):'—')+'</b><span>'+esc((C[k]&&C[k].name)||k)+' · 0–100</span></div>').join('')
  +'</div></div>'
  +'<div class="source">Покрытие '+fmt(sc.coverage_pct,0)+'%. '+esc(sc.reason||'')+'</div>';
 if(sc.arithmetic)html+='<div class="notice"><b>Как рассчитано:</b> '+esc(sc.arithmetic)+'</div>';
 html+=order.map(k=>componentLine(k,C[k]||{})).join('');
 html+=renderMethodology(sc.methodology);
 $('score').innerHTML=html;
}
async function loadInvestmentScore(){
 const input=$('priceTarget'),button=$('recalcScore');
 const target=Math.max(1,Number(input&&input.value||600000));
 if(button){button.disabled=true;button.innerHTML='<span class="spinner"></span>Считаю'}
 try{
  const data=await j('/auctions/krt-prototype/nagatino/investment-score?price_target_rub_sqm='+encodeURIComponent(target));
  renderScore(data);
 }catch(e){
  $('scoreKpi').textContent='—';
  $('score').innerHTML='<div class="notice bad">Рейтинг #485 не получен: '+esc(e.message||e)+'</div>';
 }finally{
  if(button){button.disabled=false;button.textContent='Пересчитать'}
 }
}
function bindScore(){
 const b=$('recalcScore'),i=$('priceTarget');
 if(b)b.onclick=loadInvestmentScore;
 if(i)i.onkeydown=e=>{if(e.key==='Enter')loadInvestmentScore()};
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
 const storedMarket=report&&report.market||{}, peers=storedMarket.peers||[],
       analysis=storedMarket.analysis||{}, hint=storedMarket.price_hint||{},
       siteVerdict=analysis.site||analysis.overall||{};
 const price=num(rank.surrounding_price_rub_sqm)??num(siteVerdict.price_per_sqm)??num(hint.price_per_sqm);
 const pace=num(rank.surrounding_sales_units_per_month);
 $('marketPrice').textContent=fmt(price);
 $('marketPace').textContent=fmt(pace,1);

 const s=report&&report.screening||{},m=s.metrics||{};
 const computed=num(rank.computed_at);
 const date=computed?new Date(computed*1000).toLocaleString('ru-RU'):'—';
 const peerCount=(storedMarket.comparison||{}).used??(peers.length||null);
 let html='<div class="section-title">Окружение продаж · радиус 3 км</div>'
  +'<div class="decision-grid">'
  +'<div class="decision"><b>'+fmt(price,0)+(price!==null?' ₽/м²':'')+'</b><span>цена окружения</span></div>'
  +'<div class="decision"><b>'+fmt(pace,1)+(pace!==null?' ДДУ/мес.':'')+'</b><span>темп продаж окружения</span></div>'
  +'<div class="decision"><b>'+esc(rank.segment||'—')+'</b><span>рыночный сегмент</span></div>'
  +'<div class="decision"><b>'+fmt(peerCount,0)+'</b><span>аналогов в сохранённом отчёте</span></div>'
  +'</div>';
 if(peers.length){
  html+='<details><summary>Сопоставимые проекты — '+peers.length+'</summary><div style="overflow:auto;margin-top:8px"><table><thead><tr><th>Проект</th><th>Расстояние</th><th>Цена</th><th>Продажи</th><th>Остаток</th></tr></thead><tbody>'
   +peers.slice(0,12).map(p=>'<tr><td><b>'+esc(p.name||p.address||'—')+'</b><div class="source">'+esc(p.developer||'')+'</div></td><td>'+fmt(p.distance_km,1)+' км</td><td class="num">'+(num(p.price_per_sqm)!==null?fmt(p.price_per_sqm)+' ₽/м²':'—')+'</td><td class="num">'+(num(p.units_per_month)!==null?fmt(p.units_per_month,1)+' ДДУ/мес.':'—')+'</td><td class="num">'+fmt(p.remaining_units,0)+'</td></tr>').join('')
   +'</tbody></table></div></details>';
 }else{
  html+='<div class="source">Сохранённый рыночный отчёт пока не содержит детального списка аналогов. Числа не подменяются догадками.</div>';
 }

 html+='<div class="section-title">Экономика DevelopAid</div>'
  +'<div class="decision-grid">'
  +'<div class="decision"><b>'+fmt(m.project_llcr_x??rank.project_llcr_x,3)+'x</b><span>LLCR проекта</span></div>'
  +'<div class="decision"><b>'+fmt(m.margin_pct??rank.margin_pct,1)+'%</b><span>маржа</span></div>'
  +'<div class="decision"><b>'+fmt(rank.entry_capacity_mln,0)+' млн ₽</b><span>потолок входа</span></div>'
  +'<div class="decision"><b>'+fmt(rank.entry_capacity_rub_per_sqm,0)+' ₽/м²</b><span>потолок на продаваемый м²</span></div>'
  +'<div class="decision"><b>'+fmt(rank.saleable_sqm,0)+' м²</b><span>продаваемая площадь модели</span></div>'
  +'<div class="decision"><b>'+fmt(rank.net_profit_mln,0)+' млн ₽</b><span>чистая прибыль модели</span></div>'
  +'<div class="decision"><b>'+fmt(rank.start_price_rub_sqm,0)+' ₽/м²</b><span>цена в расчёте</span></div>'
  +'<div class="decision"><b>'+date+'</b><span>когда считалась модель</span></div>'
  +'</div>';
 if(rank.available===false)html+='<div class="notice bad">'+esc(rank.reason||'Модель DevelopAid не собрана')+'</div>';
 else if(s.available)html+='<div class="notice">'+esc(s.text||s.headline||'Модель посчитана')+'</div>';
 $('economics').innerHTML=html;
}
function publicFacts(press,rank){
 const p=press||{},op=operatorInfo({...rank,press_facts:p}),rows=[];
 if(op.operator)rows.push(['Оператор',op.operator,'подтверждён найденным источником']);
 if(op.developers.length)rows.push(['Застройщик',op.developers.join(', '),'само по себе не означает оператора КРТ']);
 if(op.selling.length)rows.push(['Связь с действующим проектом','Есть признак текущих продаж','требует проверки привязки к территории КРТ']);
 if((p.agreement||[]).length)rows.push(['Договор КРТ','Найдено упоминание','сильный признак фактической занятости']);
 if((p.operator_named||[]).length&&!op.operator){
  const x=p.operator_named[0]||{};rows.push(['Оператор в публикации',x.name||x.quote||'найдено упоминание','сверить с официальным договором/распоряжением']);
 }
 if((p.developer_named||[]).length&&!op.developers.length){
  const x=p.developer_named[0]||{};rows.push(['Застройщик в публикации',x.name||x.quote||'найдено упоминание','не приравнивается к оператору КРТ']);
 }
 if((p.city_needs||[]).length){
  const x=p.city_needs[0]||{};rows.push(['Городские обязательства',x.quote||'найдено упоминание','проверить против проекта решения']);
 }
 return rows.slice(0,5);
}
function renderPublic(rank,press){
 const p=press||rank.press_facts||{},rows=publicFacts(p,rank);
 let html=rows.length?'<div class="list">'+rows.map(r=>'<div class="item"><b>'+esc(r[0])+' · '+esc(r[1])+'</b><div class="muted">'+esc(r[2])+'</div></div>').join('')+'</div>'
  :'<div class="notice">Сохранённых подтверждённых признаков оператора или связи с крупным реализуемым проектом сейчас нет. Это не доказательство отсутствия связи.</div>';
 const docs=(p.documents||[]).filter(x=>x&&x.url);
 if(docs.length){
  html+='<details><summary>Источники поиска — '+docs.length+'</summary><div class="list" style="margin-top:8px">'
   +docs.slice(0,12).map(x=>'<div class="item"><b>'+esc(x.domain||'источник')+'</b><a target="_blank" rel="noopener" href="'+esc(x.url)+'">'+esc(x.title||x.url)+'</a></div>').join('')
   +'</div></details>';
 }
 if(p.checked_at)html+='<div class="source">Публичное пространство проверено: '+new Date(Number(p.checked_at)*1000).toLocaleString('ru-RU')+'.</div>';
 $('publicContext').innerHTML=html;
}
async function refreshPublic(p,rank){
 const b=$('refreshPublic');if(!b)return;
 b.disabled=true;b.innerHTML='<span class="spinner"></span>Ищу…';
 $('publicContext').innerHTML='<div class="notice">Обновляю поиск по публикациям, официальным материалам и открытым источникам…</div>';
 try{
  const d=await j('/auctions/krt/'+encodeURIComponent(p.slug)+'/open-sources');
  renderPublic(rank,d);
 }catch(e){
  $('publicContext').innerHTML='<div class="notice bad">Поиск не обновлён: '+esc(e.message||e)+'</div>';
 }finally{
  b.disabled=false;b.textContent='Обновить поиск в публичном пространстве';
 }
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
 $('objectsTable').innerHTML=source.length?'<details><summary>Снос / реконструкция / сохранение — '+source.length+' объектов</summary><div style="overflow:auto;margin-top:8px"><table><thead><tr><th>КН / адрес</th><th>Объект</th><th>Площадь</th><th>Действие</th></tr></thead><tbody>'+source.slice(0,40).map(o=>'<tr><td>'+esc(o.cadastral_number||o.address||'—')+'</td><td>'+esc(o.name||o.purpose||o.address||'—')+'</td><td class="num">'+fmt(o.area_sqm)+' м²</td><td>'+esc(kind(o.fate))+'</td></tr>').join('')+'</tbody></table></div></details>':'<div class="notice">Перечень существующих объектов в текущем ответе не получен.</div>';
}
let MAP={point:null,parcels:null,market:false,lands:true,objects:true};
const MERC=20037508.342789244, mx=lon=>Number(lon)*MERC/180, my=lat=>Math.log(Math.tan((90+Number(lat))*Math.PI/360))*MERC/Math.PI;
function drawMap(){
 const point=MAP.point||{}, parcelPayload=MAP.parcels||{},
       parcel=parcelPayload.territory||{}, krt=parcelPayload.krt_site||{};
 const pointRings=(point.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3);
 const krtRings=(krt.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3);
 const landRows=(parcel.lands||[]), objectRows=(parcel.objects||[]);
 const landAll=landRows.flatMap(x=>(x.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3));
 const objectAll=objectRows.flatMap(x=>(x.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3));
 const site=pointRings.length?pointRings:krtRings;
 const geometry=site.length?site:(landAll.length?landAll:objectAll);
 let center=(Array.isArray(point.centre_merc)&&point.centre_merc.length>=2)?point.centre_merc:
            ((Array.isArray(krt.centre_merc)&&krt.centre_merc.length>=2)?krt.centre_merc:null);
 if(!center&&geometry.length){
  const q=geometry.flat();center=[q.reduce((z,p)=>z+Number(p[0]),0)/q.length,q.reduce((z,p)=>z+Number(p[1]),0)/q.length];
 }
 if(!center){$('map').innerHTML='<div class="notice">Геометрия территории пока не получена.</div>';return}

 const invLat=y=>(180/Math.PI)*(2*Math.atan(Math.exp(Number(y)*Math.PI/MERC))-Math.PI/2);
 const lat=Number.isFinite(Number(point.latitude))?Number(point.latitude):invLat(center[1]);
 const lands=MAP.lands?landRows:[],objects=MAP.objects?objectRows:[];
 let pts=(site.length?site:geometry).flat().concat(lands.flatMap(x=>x.rings_merc||[]).flat()).concat(objects.flatMap(x=>x.rings_merc||[]).flat());
 if(!pts.length)pts=[center];
 let xs=pts.map(x=>Number(x[0])),ys=pts.map(x=>Number(x[1])),ax=Math.min(...xs),bx=Math.max(...xs),ay=Math.min(...ys),by=Math.max(...ys);
 const k=1/Math.cos(lat*Math.PI/180);
 if(MAP.market){const r=3000*k;ax=center[0]-r;bx=center[0]+r;ay=center[1]-r;by=center[1]+r}
 else{const w=Math.max(700*k,(bx-ax)*1.55),h=Math.max(700*k,(by-ay)*1.55),side=Math.max(w,h);ax=center[0]-side/2;bx=center[0]+side/2;ay=center[1]-side/2;by=center[1]+side/2}
 const W=1100,H=620,px=x=>(x-ax)/(bx-ax)*W,py=y=>(by-y)/(by-ay)*H,
       path=rings=>rings.map(r=>'M'+r.map(q=>px(Number(q[0])).toFixed(1)+' '+py(Number(q[1])).toFixed(1)).join('L')+'Z').join(' ');
 const base='/land/basemap?'+new URLSearchParams({bbox:[ax,ay,bx,by].join(','),width:'1100'});
 const sitePath=site.length?'<path d="'+path(site)+'" fill="#c03b32" fill-opacity=".16" stroke="#c03b32" stroke-width="4" vector-effect="non-scaling-stroke"/>':'';
 const landPaths=lands.map(x=>'<path d="'+path(x.rings_merc||[])+'" fill="#d7a23c" fill-opacity=".18" stroke="#b88218" stroke-width="1.5" vector-effect="non-scaling-stroke"/>').join('');
 const objPaths=objects.map(x=>'<path d="'+path(x.rings_merc||[])+'" fill="#777" fill-opacity=".35" stroke="#555" stroke-width="1" vector-effect="non-scaling-stroke"/>').join('');
 const mr=3000*k,market=MAP.market?'<ellipse cx="'+px(center[0]).toFixed(1)+'" cy="'+py(center[1]).toFixed(1)+'" rx="'+((mr/(bx-ax))*W).toFixed(1)+'" ry="'+((mr/(by-ay))*H).toFixed(1)+'" fill="none" stroke="#245b8a" stroke-width="4" stroke-dasharray="12 8" vector-effect="non-scaling-stroke"/>':'';
 $('map').innerHTML='<img src="'+base+'" alt="OSM"><svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+landPaths+objPaths+sitePath+market+'</svg>';
 $('mapNote').textContent=(site.length?(pointRings.length?'Контур КРТ — /point. ':'Контур КРТ — сохранённый пакет территории. '):'Отдельный полигон КРТ не получен: карта центрирована по реально прочитанным участкам/объектам территории. ')
  +'Участки и объекты взяты из /krt/nagatino/parcels. Режим «Рынок 3 км» показывает радиус от центра фактической геометрии.';
}
function bindMap(){
 $('toggleLands').classList.toggle('active',MAP.lands);
 $('toggleObjects').classList.toggle('active',MAP.objects);
 $('viewSite').onclick=()=>{MAP.market=false;$('viewSite').classList.add('active');$('viewMarket').classList.remove('active');drawMap()};
 $('viewMarket').onclick=()=>{MAP.market=true;$('viewMarket').classList.add('active');$('viewSite').classList.remove('active');drawMap()};
 $('toggleLands').onclick=()=>{MAP.lands=!MAP.lands;$('toggleLands').classList.toggle('active',MAP.lands);drawMap()};
 $('toggleObjects').onclick=()=>{MAP.objects=!MAP.objects;$('toggleObjects').classList.toggle('active',MAP.objects);drawMap()};
}
function parentAction(action,p){
 const payload={type:'developaid-krt-prototype-action',action,slug:String((p&&p.slug)||''),name:String((p&&p.name)||'')};
 if(window.parent&&window.parent!==window){window.parent.postMessage(payload,location.origin);return true}
 return false;
}
async function shareStandalone(){
 const url=location.origin+'/auctions/krt-prototype/nagatino';
 const data={title:'КРТ Нагатино · DevelopAid',text:'Инвестиционный разбор КРТ Нагатино',url};
 try{
  if(navigator.share){await navigator.share(data);return 'Ссылка передана'}
  await navigator.clipboard.writeText(url);return 'Ссылка скопирована'
 }catch(e){
  try{await navigator.clipboard.writeText(url);return 'Ссылка скопирована'}catch(_){return url}
 }
}
function bindActions(p){
 const status=$('actionStatus'),say=t=>{if(status)status.textContent=t||''};
 const handoff=$('handoffDevelopAid'),plato=$('askPlato'),share=$('shareCard');
 if(handoff)handoff.onclick=()=>{
  if(parentAction('handoff',p))say('Передаю площадку в DevelopAid…');
  else say('Передача запускается из карточки, открытой поверх списка КРТ.');
 };
 if(plato)plato.onclick=()=>{
  if(parentAction('plato',p))say('Передаю контекст Платону…');
  else say('Платон запускается из карточки, открытой поверх списка КРТ.');
 };
 if(share)share.onclick=async()=>say(await shareStandalone());
}
async function boot(){
 bindMap();
 const [catRes,localRankingRes,liveRes,parcelsRes]=await Promise.allSettled([
  j('/auctions/krt'),
  j('/auctions/krt/ranking'),
  j('/auctions/krt-prototype/nagatino/live-data'),
  j('/krt/nagatino/parcels')
 ]);
 if(catRes.status!=='fulfilled'&&liveRes.status!=='fulfilled')throw (liveRes.reason||catRes.reason);
 const cat=catRes.status==='fulfilled'?catRes.value:{projects:[]};
 const live=liveRes.status==='fulfilled'?liveRes.value:{};
 const p=(live.project&&live.project.slug)?live.project:findNagatino(cat.projects||[]);
 if(!p)throw new Error('Нагатино не найдено в текущем каталоге КРТ');
 const localRanking=localRankingRes.status==='fulfilled'?localRankingRes.value:{};
 const localRank=(localRanking.rows||[]).find(x=>String(x.slug||'')===String(p.slug||''))||{};
 const liveRank=live.row||{};
 const rank={...localRank,...liveRank};
 const row={...p,...rank,status:p.status,status_kind:p.status_kind,area_ha:p.area_ha,housing_gfa_sqm:p.housing_gfa_sqm||rank.housing_gfa_sqm||229490};
 const [reqRes,pointRes]=await Promise.allSettled([
  j('/auctions/krt/'+encodeURIComponent(p.slug)+'/requirements'),
  j('/auctions/krt/'+encodeURIComponent(p.slug)+'/point')
 ]);
 const req0=reqRes.status==='fulfilled'?reqRes.value:(rank.requirements||((live.screening||{}).requirements)||{});
 const req={...req0,renovation:(req0.renovation&&Object.keys(req0.renovation).length?req0.renovation:(rank.renovation||{}))};
 const parcels=parcelsRes.status==='fulfilled'?parcelsRes.value:null;
 const point=pointRes.status==='fulfilled'?pointRes.value:null;
 const report=live.market_report||((live.screening||{}).market_report)||null;
 MAP.point=point;MAP.parcels=parcels;
 bindActions(p);bindScore();
 renderFlags(p,rank,req);renderEntry(p,rank);renderEconomics(rank,report);renderPublic(rank);renderTerritory(req,parcels);drawMap();loadInvestmentScore();if($('refreshPublic'))$('refreshPublic').onclick=()=>refreshPublic(p,rank);
 // Сразу показываем сохранённый расчёт, затем тем же рабочим движком
 // обновляем рынок и модель в фоне. Отдельного расчётчика у preview нет.
 j('/auctions/krt-prototype/nagatino/live-data?refresh=true').then(fresh=>{
  const rr={...rank,...(fresh.row||{})};
  const fr=fresh.market_report||((fresh.screening||{}).market_report)||null;
  renderFlags(p,rr,req);renderEntry(p,rr);renderEconomics(rr,fr);renderPublic(rr);loadInvestmentScore();
 }).catch(e=>{
  $('economics').insertAdjacentHTML('afterbegin','<div class="notice warn">Свежий пересчёт не завершён: '+esc(e.message||e)+'. Показан последний сохранённый расчёт.</div>');
 });
 if(liveRes.status!=='fulfilled'){
  $('economics').insertAdjacentHTML('afterbegin','<div class="notice bad">Живой рынок и модель не собраны: '+esc(liveRes.reason&&liveRes.reason.message||liveRes.reason||'ошибка')+'.</div>');
 }
 if(pointRes.status!=='fulfilled'){
  $('map').innerHTML='<div class="notice bad">Не удалось получить контур/точку КРТ: '+esc(pointRes.reason&&pointRes.reason.message||pointRes.reason||'ошибка')+'</div>';
 }else if(parcelsRes.status!=='fulfilled'){
  $('mapNote').textContent+=' Слои участков/объектов не загрузились, но контур/точка КРТ показаны.';
 }
}
boot().catch(e=>{document.querySelector('.shell').insertAdjacentHTML('afterbegin','<div class="notice bad"><b>Не удалось собрать живую карточку:</b> '+esc(e.message||e)+'</div>')});
</script>
</body>
</html>""".replace("__FOOTER__", footer_html)
