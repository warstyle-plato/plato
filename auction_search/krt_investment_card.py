from __future__ import annotations

import json


def krt_investment_card_page(slug: str) -> str:
    """Generic full-screen KRT investment card over the production endpoints.

    The card owns no parser and no financial model. It only composes the
    catalogue, ranking, requirements, territory, market and DevelopAid outputs
    that already exist in the production KRT module.
    """
    slug_js = json.dumps(str(slug or ""), ensure_ascii=False)
    return r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ — инвестиционный разбор DevelopAid</title>
<style>
:root{--bg:#f4f4f2;--panel:#fff;--ink:#171717;--muted:#6f706c;--line:#deded9;--soft:#f0f0ed;--orange:#db6b2b;--warn:#8d5419;--bad:#9f2923;--blue:#245b8a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
a{color:inherit}.shell{max-width:1480px;margin:0 auto;padding:20px}.crumbs{font-size:12px;color:var(--muted);margin-bottom:12px}
.hero,.card{background:var(--panel);border:1px solid var(--line)}.hero{padding:20px}.hero h1{font-size:27px;line-height:1.12;margin:0 0 5px}.sub{color:var(--muted);font-size:13px}
.flags{display:flex;gap:6px;flex-wrap:wrap;margin:13px 0 15px}.flag{border:1px solid var(--line);padding:6px 8px;font-size:11px;font-weight:750;background:#fff}
.flag.critical{border-color:#d0a074;background:#fff4ea;color:#7d430f}.flag.bad{border-color:#d39b98;background:#fff0ef;color:#8b231e}.flag.info{border-color:#aab9c7;background:#f2f7fb;color:#244f73}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));border-top:1px solid var(--line);border-left:1px solid var(--line)}
.kpi{padding:12px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.kpi b{font-size:20px;display:block;line-height:1.1}.kpi span{font-size:11px;color:var(--muted);display:block;margin-top:4px}
.grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(330px,.72fr);gap:14px;margin-top:14px}.card{margin-bottom:14px}.card header{padding:11px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px;align-items:baseline}.card h2{font-size:14px;margin:0}.card header span{font-size:11px;color:var(--muted)}.body{padding:14px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.bucket{border:1px solid var(--line);padding:12px}.bucket h3{font-size:12px;text-transform:uppercase;letter-spacing:.03em;margin:0 0 8px;color:var(--muted)}
.metric{display:grid;grid-template-columns:1fr auto;gap:10px;padding:7px 0;border-bottom:1px solid var(--soft)}.metric:last-child{border-bottom:0}.metric span{color:var(--muted);font-size:12px}.metric b{text-align:right}
.notice{padding:9px 10px;background:var(--soft);font-size:12px;margin:8px 0}.notice.warn{color:var(--warn)}.notice.bad{color:var(--bad)}.source{font-size:11px;color:var(--muted);margin-top:6px}.statusline{font-size:17px;font-weight:780;margin-bottom:8px}
.maptools,.actionbar{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:9px}.maptools button,.actionbar button,.actionbar a{border:1px solid var(--line);background:#fff;color:var(--ink);padding:7px 9px;text-decoration:none;font:inherit;cursor:pointer}.maptools button.active,.actionbar .primary{background:#111;color:#fff;border-color:#111}
.mapstage{height:500px;position:relative;border:1px solid var(--line);overflow:hidden;background:#e9ebe8}.mapstage img,.mapstage svg{position:absolute;inset:0;width:100%;height:100%}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:7px}.dot{width:9px;height:9px;display:inline-block;margin-right:4px}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.03em}.num{text-align:right;white-space:nowrap}
details{border:1px solid var(--line);margin-top:10px}summary{cursor:pointer;padding:9px 10px;font-weight:700}.detailsbody{padding:0 10px 10px}
.scorebig{font-size:38px;font-weight:800;line-height:1}.scorebig small{font-size:11px;color:var(--muted);font-weight:500;display:block;margin-top:5px}.components{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:10px}.component{border:1px solid var(--line);padding:8px}.component b{font-size:18px}.component span{display:block;font-size:10px;color:var(--muted)}
.sticky{position:sticky;top:10px}.spinner{display:inline-block;width:12px;height:12px;border:2px solid #bbb;border-top-color:#222;border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;margin-right:5px}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:980px){.grid{grid-template-columns:1fr}.sticky{position:static}.kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){.shell{padding:8px}.hero{padding:14px}.hero h1{font-size:21px}.kpis{grid-template-columns:repeat(2,1fr)}.two,.components{grid-template-columns:1fr}.mapstage{height:360px}}
</style>
</head>
<body>
<div class="shell">
 <div class="crumbs">КРТ Москвы · инвестиционный разбор</div>
 <section class="hero">
  <h1 id="title">Загружаю площадку…</h1>
  <div class="sub" id="subtitle"></div>
  <div class="flags" id="flags"><span class="flag">Читаю статус…</span></div>
  <div class="kpis">
   <div class="kpi"><b id="totalGfa">—</b><span>м² общий объём</span></div>
   <div class="kpi"><b id="housingGfa">—</b><span>м² жильё</span></div>
   <div class="kpi"><b id="commercialHousing">—</b><span>м² коммерческое жильё</span></div>
   <div class="kpi"><b id="marketPrice">—</b><span>₽/м² окружение</span></div>
   <div class="kpi"><b id="marketPace">—</b><span>ДДУ/мес. окружение</span></div>
   <div class="kpi"><b id="scoreKpi">—</b><span>рейтинг #485</span></div>
  </div>
 </section>

 <div class="grid">
  <main>
   <section class="card">
    <header><h2>Территория и рынок</h2><span>одна карта · слои КРТ / участки / объекты / 3 км</span></header>
    <div class="body">
     <div class="maptools">
      <button id="viewSite" class="active">Территория</button><button id="viewMarket">Рынок 3 км</button>
      <button id="toggleLands">Участки</button><button id="toggleObjects">Объекты</button>
     </div>
     <div id="map" class="mapstage"><div class="notice">Загружаю геометрию…</div></div>
     <div class="legend"><span><i class="dot" style="background:#c03b32"></i>КРТ</span><span><i class="dot" style="background:#d7a23c"></i>участки</span><span><i class="dot" style="background:#777"></i>объекты</span><span><i class="dot" style="background:#245b8a"></i>радиус 3 км</span></div>
     <div class="source" id="mapNote"></div>
    </div>
   </section>

   <section class="card">
    <header><h2>Программа проекта и городская нагрузка</h2><span>без дублирования двух одинаковых блоков</span></header>
    <div class="body two">
     <div class="bucket"><h3>Потенциал</h3><div id="programme"></div></div>
     <div class="bucket"><h3>Городская нагрузка</h3><div id="burden"></div></div>
    </div>
    <div class="body" style="padding-top:0"><div class="source" id="programmeSource"></div></div>
   </section>

   <section class="card">
    <header><h2>Территория сейчас</h2><span>сводка сверху · перечень по раскрытию</span></header>
    <div class="body">
     <div class="kpis" id="territoryStats" style="grid-template-columns:repeat(4,1fr)"></div>
     <div id="objectsTable"></div>
    </div>
   </section>

   <section class="card">
    <header><h2>Рынок и экономика DevelopAid</h2><span>тот же production market + financial engine</span></header>
    <div class="body">
     <div class="actionbar"><button id="refreshMarket" class="primary">Обновить рынок и модель</button></div>
     <div id="economics"><div class="notice">Открываю сохранённый расчёт…</div></div>
    </div>
   </section>

   <section class="card">
    <header><h2>Публичный контекст</h2><span>оператор / застройщик / договор / связь с проектом</span></header>
    <div class="body">
     <div class="actionbar"><button id="refreshPublic">Обновить публичный поиск</button></div>
     <div id="publicContext"></div>
    </div>
   </section>
  </main>

  <aside>
   <div class="sticky">
    <section class="card"><header><h2>Вход в проект</h2><span>отдельно от статуса города</span></header><div class="body" id="entry"></div></section>
    <section class="card"><header><h2>Рейтинг КРТ #485</h2><span>неизвестное ≠ ноль</span></header><div class="body" id="score"><div class="notice">Читаю breakdown…</div></div></section>
    <section class="card"><header><h2>Действия</h2><span>по этой площадке</span></header><div class="body actionbar">
      <button id="handoffDevelopAid" class="primary">Передать в DevelopAid</button><button id="askPlato">Спросить Платона</button><button id="shareCard">Поделиться</button><a id="territoryLink" target="_blank" rel="noopener">Территория и ЕГРН</a>
      <div id="actionStatus" class="source" style="flex-basis:100%"></div>
    </div></section>
   </div>
  </aside>
 </div>
</div>
<script>
const SLUG=__SLUG__;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>v===null||v===undefined||v===''||!Number.isFinite(Number(v))?null:Number(v);
const fmt=(v,d=0)=>num(v)===null?'—':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:d});
async function get(url){const r=await fetch(url,{cache:'no-store'});let b={};try{b=await r.json()}catch(_){ }if(!r.ok){const e=new Error((b&&b.detail)||url+' → '+r.status);e.status=r.status;throw e}return b}
function findProject(cat){return (cat.projects||[]).find(x=>String(x.slug||'')===SLUG)||null}
function activeTender(row){return (row.tender_lots||[]).find(x=>['future','active','open','now'].includes(String(x.moment||x.status||'').toLowerCase())||(!x.moment&&!x.ended))||null}
function operatorInfo(row){
 const p=row.press_facts||{},c=row.card_facts||{},developers=(c.developers||[]).filter(Boolean);
 const operator=p.operator_name||(((p.operator_named||[])[0]||{}).name)||'';
 const agreement=(p.agreement||[]).length>0,selling=(p.selling_now||[]);
 const taken=!!(operator||agreement||selling.length||p.taken);
 return {operator,agreement,selling,developers,taken,probed:!!p.probed};
}
function renovationInfo(p,rank,req){
 const r=(req&&req.renovation)||rank.renovation||{}, housing=num(p.housing_gfa_sqm)||num(rank.housing_gfa_sqm);
 const area=num(r.area_sqm)??num(r.spp_sqm),mentioned=!!(r.mentioned||area!==null);
 const share=area!==null&&housing&&housing>0?Math.min(1,area/housing):null;
 return {area,housing,share,mentioned,reason:r.not_counted_reason||'',quote:r.quote||''};
}
function renderHero(p,rank,req){
 $('title').textContent=p.name||SLUG;
 $('subtitle').textContent=[p.okrug,p.district,p.status,p.area_ha?fmt(p.area_ha,2)+' га':''].filter(Boolean).join(' · ');
 $('totalGfa').textContent=fmt(p.total_gfa_sqm);
 $('housingGfa').textContent=fmt(p.housing_gfa_sqm);
 const ren=renovationInfo(p,rank,req),live=activeTender({...p,...rank}),op=operatorInfo({...p,...rank});
 $('commercialHousing').textContent=ren.area!==null&&ren.housing!==null?fmt(Math.max(0,ren.housing-ren.area)):fmt(p.housing_gfa_sqm);
 const bits=['<span class="flag">'+esc(p.status||'КРТ')+'</span>'];
 if(ren.share!==null){
  bits.push('<span class="flag critical">'+(ren.share>=.99?'100% РЕНОВАЦИЯ':'Реновация '+fmt(ren.share*100,0)+'% жилья')+'</span>');
 }else if(ren.mentioned)bits.push('<span class="flag critical">Реновация · объём не определён</span>');
 if(live)bits.push('<span class="flag info">Идут торги</span>');
 if(op.taken)bits.push('<span class="flag bad">Площадка занята</span>');
 else if(!live)bits.push('<span class="flag">Оператор не подтверждён</span>');
 if(op.selling.length)bits.push('<span class="flag critical">Связь с действующим проектом · проверить</span>');
 else if(op.developers.length)bits.push('<span class="flag">Застройщик: '+esc(op.developers[0])+' · не оператор КРТ</span>');
 $('flags').innerHTML=bits.join('');
}
function renderEntry(p,rank){
 const row={...p,...rank},live=activeTender(row),op=operatorInfo(row),facts=[];
 let title='Вход не подтверждён';
 if(live){title='Идёт аукцион — вход открыт';if(live.deadline)facts.push('Заявки до '+live.deadline);if(live.price_rub)facts.push('Цена права '+fmt(live.price_rub/1e6,1)+' млн ₽');}
 else if(op.taken){title='Вход закрыт / площадка занята';if(op.operator)facts.push('Оператор: '+op.operator);if(op.agreement)facts.push('Есть упоминание заключённого договора КРТ');if(op.selling.length)facts.push('Есть текущие продажи на связанной площадке');}
 else facts.push('Живой лот и подтверждённый оператор не найдены в сохранённых данных.');
 $('entry').innerHTML='<div class="statusline">'+esc(title)+'</div><div class="notice '+(op.taken?'bad':live?'':'warn')+'">'+esc(facts.join(' · '))+'</div>'
  +(op.developers.length?'<div class="metric"><span>Названный застройщик</span><b>'+esc(op.developers.join(', '))+'</b></div>':'');
}
function deadlineText(req){return (req.deadlines||[]).slice(0,2).map(x=>x.quote||x.label||x.text||String(x)).filter(Boolean).join(' · ')}
function actionCounts(req){
 const a=Array.isArray(req.object_actions)?req.object_actions:[],count=k=>a.filter(x=>x&&x.category===k).length;
 return {demo:count('demolition'),conditional:count('demolition_or_reconstruction'),recon:count('reconstruction'),preserve:count('preservation'),res:Number(req.resettlement_mentions??(req.resettlement||[]).length)||0};
}
function renderProgramme(p,req){
 const ren=renovationInfo(p,{},req),prog=(req.programme||[]).filter(x=>x&&x.category!=='housing_gfa_sqm');
 let left='<div class="metric"><span>Общий объём</span><b>'+fmt(p.total_gfa_sqm)+' м²</b></div>'
  +'<div class="metric"><span>Жильё</span><b>'+fmt(p.housing_gfa_sqm)+' м²</b></div>';
 prog.slice(0,8).forEach(x=>{left+='<div class="metric"><span>'+esc(x.label||x.category||'Объект')+'</span><b>'+fmt(x.area_sqm)+' м²</b></div>'});
 const dl=deadlineText(req);if(dl)left+='<div class="metric"><span>Срок</span><b>'+esc(dl)+'</b></div>';
 $('programme').innerHTML=left;
 const c=actionCounts(req);let right='';
 right+='<div class="metric"><span>Жильё реновации</span><b>'+(ren.area!==null?fmt(ren.area)+' м²':(ren.mentioned?'объём не назван':'не найдено в решении'))+'</b></div>';
 right+='<div class="metric"><span>Снос</span><b>'+c.demo+'</b></div><div class="metric"><span>Снос / реконструкция</span><b>'+c.conditional+'</b></div><div class="metric"><span>Реконструкция</span><b>'+c.recon+'</b></div><div class="metric"><span>Сохранение</span><b>'+c.preserve+'</b></div><div class="metric"><span>Расселение / изъятие</span><b>'+c.res+'</b></div>';
 $('burden').innerHTML=right;
 const d=req.decision||{};
 $('programmeSource').innerHTML=d.page_url?'Источник: <a target="_blank" rel="noopener" href="'+esc(d.page_url)+'">материалы решения на mos.ru</a>':'Источник: карточка КРТ / проект решения, если опубликован.';
}
function fate(x){const f=String(x.fate||x.category||'').toLowerCase();if(f.includes('demolition_or_reconstruction'))return 'Снос / реконструкция';if(f.includes('demolition')||f.includes('снос'))return 'Снос';if(f.includes('reconstruction')||f.includes('рекон'))return 'Реконструкция';if(f.includes('preservation')||f.includes('сохран'))return 'Сохранение';return 'Не определено'}
function renderTerritory(req,parcels){
 const terr=(parcels&&parcels.territory)||{},lands=terr.lands||[],objects=terr.objects||[];
 const fallback=(req.object_actions||[]).map(x=>({cadastral_number:x.cadastral_number,address:x.label||x.address,area_sqm:x.area_sqm,fate:x.category}));
 const rows=objects.length?objects:fallback,counts={};rows.forEach(x=>counts[fate(x)]=(counts[fate(x)]||0)+1);
 $('territoryStats').innerHTML=[[lands.length||'—','земельных участков'],[rows.length||'—','объектов'],[counts['Снос']||0,'под снос'],[(counts['Реконструкция']||0)+(counts['Сохранение']||0),'реконструкция / сохранение']].map(x=>'<div class="kpi"><b>'+x[0]+'</b><span>'+x[1]+'</span></div>').join('');
 $('objectsTable').innerHTML=rows.length?'<details><summary>Снос / реконструкция / сохранение — '+rows.length+' объектов</summary><div class="detailsbody" style="overflow:auto"><table><thead><tr><th>КН / адрес</th><th>Объект</th><th>Площадь</th><th>Действие</th></tr></thead><tbody>'+rows.slice(0,60).map(x=>'<tr><td>'+esc(x.cadastral_number||x.address||'—')+'</td><td>'+esc(x.name||x.purpose||x.address||'—')+'</td><td class="num">'+fmt(x.area_sqm)+' м²</td><td>'+esc(fate(x))+'</td></tr>').join('')+'</tbody></table></div></details>':'<div class="notice">Перечень существующих объектов в текущих данных не получен.</div>';
}
function renderEconomics(rank,report){
 const market=(report&&report.market)||report||{},analysis=market.analysis||{},site=analysis.site||analysis.overall||{},hint=market.price_hint||{},peers=market.peers||[];
 const price=num(rank.surrounding_price_rub_sqm)??num(site.price_per_sqm)??num(hint.price_per_sqm),pace=num(rank.surrounding_sales_units_per_month);
 $('marketPrice').textContent=fmt(price);$('marketPace').textContent=fmt(pace,1);
 const screening=(report&&report.screening)||rank.screening||{},m=screening.metrics||{};
 let html='<div class="two"><div class="bucket"><h3>Рынок 3 км</h3><div class="metric"><span>Цена окружения</span><b>'+fmt(price)+' ₽/м²</b></div><div class="metric"><span>Темп</span><b>'+fmt(pace,1)+' ДДУ/мес.</b></div><div class="metric"><span>Сегмент</span><b>'+esc(rank.segment||market.recommended_segment||'—')+'</b></div><div class="metric"><span>Аналоги</span><b>'+fmt(peers.length)+'</b></div></div>'
  +'<div class="bucket"><h3>Экономика DevelopAid</h3><div class="metric"><span>LLCR</span><b>'+fmt(m.project_llcr_x??rank.project_llcr_x,3)+'x</b></div><div class="metric"><span>Маржа</span><b>'+fmt(m.margin_pct??rank.margin_pct,1)+'%</b></div><div class="metric"><span>Потолок входа</span><b>'+fmt(rank.entry_capacity_mln,1)+' млн ₽</b></div><div class="metric"><span>Потолок / продаваемый м²</span><b>'+fmt(rank.entry_capacity_rub_per_sqm)+' ₽/м²</b></div></div></div>';
 if(peers.length)html+='<details><summary>Сопоставимые проекты — '+peers.length+'</summary><div class="detailsbody" style="overflow:auto"><table><thead><tr><th>Проект</th><th>Расстояние</th><th>Цена</th><th>Продажи</th><th>Остаток</th></tr></thead><tbody>'+peers.slice(0,12).map(x=>'<tr><td>'+esc(x.name||x.address||'—')+'</td><td>'+fmt(x.distance_km,1)+' км</td><td class="num">'+fmt(x.price_per_sqm)+' ₽/м²</td><td class="num">'+fmt(x.units_per_month,1)+'</td><td class="num">'+fmt(x.remaining_units)+'</td></tr>').join('')+'</tbody></table></div></details>';
 if(screening&&screening.available===false)html+='<div class="notice warn">'+esc(screening.reason||'Модель не собрана')+'</div>';
 $('economics').innerHTML=html;
}
function renderPublic(rank,press){
 const p=press||rank.press_facts||{},op=operatorInfo({...rank,press_facts:p}),rows=[];
 if(op.operator)rows.push(['Оператор',op.operator,'по найденному источнику']);
 if(op.developers.length)rows.push(['Застройщик',op.developers.join(', '),'само по себе не означает оператора КРТ']);
 if(op.agreement)rows.push(['Договор КРТ','найдено упоминание','сильный признак занятости']);
 if(op.selling.length)rows.push(['Действующий проект','есть текущие продажи','нужно проверить привязку именно к территории КРТ']);
 if((p.developer_named||[]).length&&!op.developers.length)rows.push(['Застройщик в публикации',(p.developer_named[0]||{}).name||'найдено упоминание','не приравнивается к оператору']);
 $('publicContext').innerHTML=rows.length?rows.slice(0,5).map(x=>'<div class="metric"><span>'+esc(x[0])+' · '+esc(x[2])+'</span><b>'+esc(x[1])+'</b></div>').join(''):'<div class="notice">Сохранённых подтверждённых признаков оператора или связи с более крупным проектом нет. Это не доказательство отсутствия связи.</div>';
}
function renderScore(sc){
 if(!sc){$('scoreKpi').textContent='—';$('score').innerHTML='<div class="notice">Breakdown #485 пока не рассчитан.</div>';return}
 $('scoreKpi').textContent=sc.display_score===null||sc.display_score===undefined?'—':fmt(sc.display_score);
 const C=sc.components||{},order=['llcr','price','absorption','burden'];
 $('score').innerHTML='<div class="scorebig">'+(sc.display_score===null||sc.display_score===undefined?'—':fmt(sc.display_score))+'/100<small>'+esc(sc.reason||'инвестиционный рейтинг')+'</small></div><div class="source">Покрытие '+fmt(sc.coverage_pct)+'%</div><div class="components">'+order.map(k=>{const x=C[k]||{};return '<div class="component"><b>'+(x.score===null||x.score===undefined?'—':fmt(x.score,1))+'</b><span>'+esc(x.name||k)+'</span><div class="source">'+esc(x.score===null||x.score===undefined?(x.missing_reason||'нет данных'):(x.formula||''))+'</div></div>'}).join('')+'</div>';
}
let MAP={point:null,parcels:null,market:false,lands:true,objects:true};const MERC=20037508.342789244;
function drawMap(){
 const point=MAP.point||{},pp=MAP.parcels||{},terr=pp.territory||{},krt=pp.krt_site||{};
 const pointR=(point.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3),krtR=(krt.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3);
 const landRows=terr.lands||[],objectRows=terr.objects||[],landAll=landRows.flatMap(x=>(x.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3)),objectAll=objectRows.flatMap(x=>(x.rings_merc||[]).filter(r=>Array.isArray(r)&&r.length>=3));
 const site=pointR.length?pointR:krtR,geometry=site.length?site:(landAll.length?landAll:objectAll);
 let center=(Array.isArray(point.centre_merc)&&point.centre_merc.length>=2)?point.centre_merc:((Array.isArray(krt.centre_merc)&&krt.centre_merc.length>=2)?krt.centre_merc:null);
 if(!center&&geometry.length){const q=geometry.flat();center=[q.reduce((z,p)=>z+Number(p[0]),0)/q.length,q.reduce((z,p)=>z+Number(p[1]),0)/q.length]}
 if(!center&&num(point.longitude)!==null&&num(point.latitude)!==null){const lon=Number(point.longitude),lat=Number(point.latitude);center=[lon*MERC/180,Math.log(Math.tan((90+lat)*Math.PI/360))*MERC/Math.PI]}
 if(!center){$('map').innerHTML='<div class="notice">Геометрия территории пока не получена.</div>';return}
 const invLat=y=>(180/Math.PI)*(2*Math.atan(Math.exp(Number(y)*Math.PI/MERC))-Math.PI/2),lat=num(point.latitude)??invLat(center[1]),lands=MAP.lands?landRows:[],objects=MAP.objects?objectRows:[];
 let pts=(site.length?site:geometry).flat().concat(lands.flatMap(x=>x.rings_merc||[]).flat()).concat(objects.flatMap(x=>x.rings_merc||[]).flat());if(!pts.length)pts=[center];
 let xs=pts.map(x=>Number(x[0])),ys=pts.map(x=>Number(x[1])),ax=Math.min(...xs),bx=Math.max(...xs),ay=Math.min(...ys),by=Math.max(...ys);const k=1/Math.cos(lat*Math.PI/180);
 if(MAP.market){const r=3000*k;ax=center[0]-r;bx=center[0]+r;ay=center[1]-r;by=center[1]+r}else{const side=Math.max(700*k,(bx-ax)*1.55,(by-ay)*1.55);ax=center[0]-side/2;bx=center[0]+side/2;ay=center[1]-side/2;by=center[1]+side/2}
 const W=1100,H=620,px=x=>(x-ax)/(bx-ax)*W,py=y=>(by-y)/(by-ay)*H,path=rings=>rings.map(r=>'M'+r.map(q=>px(Number(q[0])).toFixed(1)+' '+py(Number(q[1])).toFixed(1)).join('L')+'Z').join(' ');
 const base='/land/basemap?'+new URLSearchParams({bbox:[ax,ay,bx,by].join(','),width:'1100'}),sitePath=site.length?'<path d="'+path(site)+'" fill="#c03b32" fill-opacity=".16" stroke="#c03b32" stroke-width="4" vector-effect="non-scaling-stroke"/>':'';
 const landPaths=lands.map(x=>'<path d="'+path(x.rings_merc||[])+'" fill="#d7a23c" fill-opacity=".18" stroke="#b88218" stroke-width="1.5" vector-effect="non-scaling-stroke"/>').join(''),objPaths=objects.map(x=>'<path d="'+path(x.rings_merc||[])+'" fill="#777" fill-opacity=".35" stroke="#555" stroke-width="1" vector-effect="non-scaling-stroke"/>').join('');
 const mr=3000*k,market=MAP.market?'<ellipse cx="'+px(center[0]).toFixed(1)+'" cy="'+py(center[1]).toFixed(1)+'" rx="'+((mr/(bx-ax))*W).toFixed(1)+'" ry="'+((mr/(by-ay))*H).toFixed(1)+'" fill="none" stroke="#245b8a" stroke-width="4" stroke-dasharray="12 8" vector-effect="non-scaling-stroke"/>':'';
 $('map').innerHTML='<img src="'+base+'" alt="Карта"><svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+landPaths+objPaths+sitePath+market+'</svg>';
 $('mapNote').textContent=(site.length?'Контур КРТ получен. ':'Карта центрирована по доступной геометрии территории. ')+(MAP.parcels?'Участки и объекты — из рабочего свода территории. ':'Слой участков/объектов пока недоступен. ')+'Рынок — радиус 3 км.';
}
function bindMap(){
 $('viewSite').onclick=()=>{MAP.market=false;$('viewSite').classList.add('active');$('viewMarket').classList.remove('active');drawMap()};$('viewMarket').onclick=()=>{MAP.market=true;$('viewMarket').classList.add('active');$('viewSite').classList.remove('active');drawMap()};
 $('toggleLands').onclick=()=>{MAP.lands=!MAP.lands;$('toggleLands').classList.toggle('active',MAP.lands);drawMap()};$('toggleObjects').onclick=()=>{MAP.objects=!MAP.objects;$('toggleObjects').classList.toggle('active',MAP.objects);drawMap()};
}
function parentAction(action,p){if(window.parent&&window.parent!==window){window.parent.postMessage({type:'developaid-krt-card-action',action,slug:String(p.slug||''),name:String(p.name||'')},location.origin);return true}return false}
async function boot(){
 bindMap();$('territoryLink').href='/krt/site/'+encodeURIComponent(SLUG);
 const [catR,rankR,reqR,pointR,parcelR,reportR,scoreR]=await Promise.allSettled([
  get('/auctions/krt'),get('/auctions/krt/ranking'),get('/auctions/krt/'+encodeURIComponent(SLUG)+'/requirements'),get('/auctions/krt/'+encodeURIComponent(SLUG)+'/point'),get('/krt/site/'+encodeURIComponent(SLUG)+'/parcels'),get('/auctions/krt/'+encodeURIComponent(SLUG)+'/report'),get('/auctions/krt/'+encodeURIComponent(SLUG)+'/investment-score')
 ]);
 const cat=catR.status==='fulfilled'?catR.value:{projects:[]},p=findProject(cat);if(!p)throw new Error('Площадка не найдена в текущем каталоге КРТ');
 const rankData=rankR.status==='fulfilled'?rankR.value:{rows:[]},rank=(rankData.rows||[]).find(x=>String(x.slug||'')===SLUG)||{},req=reqR.status==='fulfilled'?reqR.value:(rank.requirements||{}),parcels=parcelR.status==='fulfilled'?parcelR.value:null,report=reportR.status==='fulfilled'?reportR.value:null;
 MAP.point=pointR.status==='fulfilled'?pointR.value:null;MAP.parcels=parcels;
 renderHero(p,rank,req);renderEntry(p,rank);renderProgramme(p,req);renderTerritory(req,parcels);renderEconomics(rank,report);renderPublic(rank);renderScore(scoreR.status==='fulfilled'?(scoreR.value.rating||scoreR.value):null);drawMap();
 $('refreshMarket').onclick=async()=>{const b=$('refreshMarket');b.disabled=true;b.innerHTML='<span class="spinner"></span>Считаю';try{const d=await get('/auctions/krt/'+encodeURIComponent(SLUG)+'/market');const r2=await get('/auctions/krt/ranking');const rr=(r2.rows||[]).find(x=>String(x.slug||'')===SLUG)||rank;renderEconomics(rr,d);renderHero(p,rr,req);try{const s=await get('/auctions/krt/'+encodeURIComponent(SLUG)+'/investment-score');renderScore(s.rating||s)}catch(_){}}catch(e){$('economics').insertAdjacentHTML('afterbegin','<div class="notice bad">'+esc(e.message||e)+'</div>')}finally{b.disabled=false;b.textContent='Обновить рынок и модель'}};
 $('refreshPublic').onclick=async()=>{const b=$('refreshPublic');b.disabled=true;b.innerHTML='<span class="spinner"></span>Ищу';try{const d=await get('/auctions/krt/'+encodeURIComponent(SLUG)+'/open-sources');renderPublic(rank,d)}catch(e){$('publicContext').innerHTML='<div class="notice bad">'+esc(e.message||e)+'</div>'}finally{b.disabled=false;b.textContent='Обновить публичный поиск'}};
 $('handoffDevelopAid').onclick=()=>{const s=$('actionStatus');if(parentAction('handoff',p))s.textContent='Передаю в DevelopAid…';else location.href='/auctions#krt='+encodeURIComponent(SLUG)};
 $('askPlato').onclick=()=>{const s=$('actionStatus');if(parentAction('plato',p))s.textContent='Передаю контекст Платону…';else s.textContent='Платон открывается из каталога КРТ.'};
 $('shareCard').onclick=async()=>{const url=location.origin+'/auctions/krt-card/'+encodeURIComponent(SLUG);try{if(navigator.share)await navigator.share({title:'КРТ · '+(p.name||''),url});else await navigator.clipboard.writeText(url);$('actionStatus').textContent='Ссылка скопирована'}catch(e){if(e&&e.name!=='AbortError')$('actionStatus').textContent=String(e.message||e)}};
}
boot().catch(e=>{document.querySelector('.shell').insertAdjacentHTML('afterbegin','<div class="notice bad"><b>Карточка не собрана:</b> '+esc(e.message||e)+'</div>')});
</script>
</body></html>""".replace("__SLUG__", slug_js)
