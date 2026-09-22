"""Experimental KRT index. Isolated route: /krt-preview."""
import json
import urllib.request
import urllib.parse
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

PAGE = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ — DevelopAid preview</title><style>
:root{--bg:#f2f2ef;--panel:#fff;--text:#171717;--muted:#6b6b6b;--line:#dedede;--soft:#f7f7f5;--accent:#111;--ok:#1f6b3b;--warn:#8a5a00;--bad:#a33}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}.shell{max-width:1480px;margin:auto;background:#fff;min-height:100vh}.brandbar{padding:18px 28px 0}.brand{font-size:23px;font-weight:800}.brandline{height:7px;background:#050505;margin-top:12px}.head{padding:18px 28px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;align-items:end}.head h1{font-size:28px;margin:0}.muted,.source{color:var(--muted)}.content{padding:20px 28px 40px}.filters{display:grid;grid-template-columns:2fr repeat(4,1fr);gap:8px}.filters input,.filters select{min-width:0;height:42px;border:1px solid var(--line);background:#fff;padding:0 10px;font:inherit}.multi{position:relative}.multi>button{width:100%;height:42px;border:1px solid var(--line);background:#fff;text-align:left;padding:0 12px;font:inherit}.multi-menu{display:none;position:absolute;z-index:20;top:41px;left:0;min-width:240px;background:#fff;border:1px solid var(--line);padding:8px;box-shadow:0 8px 24px rgba(0,0,0,.12)}.multi.open .multi-menu{display:block}.multi-menu label{display:block;padding:7px 5px;white-space:nowrap}.multi-menu input{height:auto;margin-right:7px}.filters2{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px}.actions{display:flex;gap:8px;margin:10px 0 16px}.actions button{min-height:38px;border:1px solid #111;background:#fff;padding:0 12px;font-weight:650}.actions .primary{background:#111;color:#fff}.stats{display:grid;grid-template-columns:repeat(6,1fr);border:1px solid var(--line);margin-bottom:14px}.stat{padding:12px 14px;border-right:1px solid var(--line)}.stat:last-child{border:0}.stat b{display:block;font-size:21px}.stat span{font-size:11px;color:var(--muted)}.summary{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:12px 0}.cards{display:grid;gap:10px}.card{border:1px solid var(--line);background:#fff;display:grid;grid-template-columns:180px minmax(240px,1.25fr) minmax(420px,2fr) 34px;cursor:pointer}.visual{background:#eceeea;min-height:168px;position:relative;border-right:1px solid var(--line);overflow:hidden}.visual:before,.visual:after{content:"";position:absolute;border:2px solid #8d928b}.visual:before{inset:28px 35px;transform:rotate(-8deg)}.visual:after{inset:48px 22px 32px 58px;transform:rotate(12deg)}.visual span{position:absolute;left:10px;bottom:8px;font-size:10px;color:#777}.identity{padding:14px}.badge{display:inline-block;border:1px solid var(--line);padding:4px 7px;font-size:11px;margin-bottom:8px}.badge.live{border-color:#b77;color:#922}.name{font-size:17px;font-weight:700;line-height:1.25;margin-bottom:5px}.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}.chip{background:var(--soft);border:1px solid var(--line);padding:3px 6px;font-size:10px}.numbers{display:grid;grid-template-columns:repeat(4,1fr);border-left:1px solid var(--line)}.num{padding:12px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-height:76px}.num:nth-last-child(-n+4){border-bottom:0}.num b{display:block;font-size:15px}.num small{display:block;color:var(--muted);font-size:10px;margin-top:4px}.arrow{display:flex;align-items:center;justify-content:center;font-size:22px}.empty{border:1px solid var(--line);padding:30px;color:var(--muted)}.countnote{font-size:12px;color:var(--muted)}@media(max-width:900px){.head{padding:14px 16px}.content{padding:14px 16px}.filters,.filters2{grid-template-columns:1fr 1fr}.stats{grid-template-columns:repeat(2,1fr)}.stat{border-bottom:1px solid var(--line)}.card{grid-template-columns:105px 1fr 28px}.visual{min-height:145px}.numbers{grid-column:1/-1;grid-template-columns:repeat(2,1fr);border-left:0;border-top:1px solid var(--line)}.num{min-height:66px}.num:nth-last-child(-n+4){border-bottom:1px solid var(--line)}.arrow{grid-column:3;grid-row:1/3}.actions{overflow:auto}.actions button{white-space:nowrap}}@media(max-width:560px){.filters,.filters2{grid-template-columns:1fr 1fr}.head h1{font-size:24px}.card{grid-template-columns:88px 1fr 24px}.identity{padding:11px}.name{font-size:15px}.visual:before{inset:30px 16px}.visual:after{inset:48px 10px 35px 28px}}
.modal{display:none;position:fixed;z-index:100;inset:0;background:rgba(0,0,0,.38);padding:5vh 4vw}.modal.open{display:block}.modal-card{max-width:900px;height:90vh;margin:auto;background:#fff;border:1px solid #111;display:flex;flex-direction:column}.modal-head{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}.modal-head b{font-size:18px}.modal-head button{border:0;background:none;font-size:24px}.modal-body{padding:16px;overflow:auto;flex:1}.askrow{display:flex;gap:7px}.askrow input{flex:1;padding:10px;border:1px solid var(--line)}.askrow button{background:#111;color:#fff;border:0;padding:0 14px}</style></head><body><div class="shell"><div class="brandbar"><div class="brand">DevelopAid</div><div class="brandline"></div></div><div class="head"><div><h1>Площадки КРТ Москвы</h1><div class="muted">Тот же рабочий реестр и ранжирование · новый интерфейс</div></div><div class="source">TEST · main не изменён</div></div><main class="content">
<div class="filters"><input id="q" placeholder="Название КРТ, район, адрес"><div class="multi" data-id="okrug"><button type="button">Округа</button><div class="multi-menu" id="okrug"></div></div><div class="multi" data-id="stage"><button type="button">Стадии КРТ</button><div class="multi-menu" id="stage"><label><input type="checkbox" value="draft"> Проект решения</label><label><input type="checkbox" value="planned"> Планируемая</label><label><input type="checkbox" value="tender"> Идёт аукцион</label><label><input type="checkbox" value="announced"> Торги объявлялись</label><label><input type="checkbox" value="running"> В реализации</label></div></div><div class="multi" data-id="entry"><button type="button">Возможность входа</button><div class="multi-menu" id="entry"><label><input type="checkbox" value="free"> Свободна</label><label><input type="checkbox" value="taken"> Занята</label><label><input type="checkbox" value="unknown"> Не знаем</label></div></div><div class="multi" data-id="reno"><button type="button">Реновация</button><div class="multi-menu" id="reno"><label><input type="checkbox" value="yes"> Есть реновация</label><label><input type="checkbox" value="no"> Не найдена</label><label><input type="checkbox" value="unknown"> Не знаем</label></div></div></div>
<div class="filters2"><div class="multi" data-id="purpose"><button type="button">Назначение</button><div class="multi-menu" id="purpose"><label><input type="checkbox" value="housing"> Жильё</label><label><input type="checkbox" value="business"> Общественно-деловое</label><label><input type="checkbox" value="nonres"> Нежилое</label><label><input type="checkbox" value="unknown"> Не названо</label></div></div><input id="minHousing" type="number" placeholder="Жильё от, м²"><input id="minPrice" type="number" placeholder="Цена окружения от, ₽/м²"><select id="sort"><option value="score">Сначала по баллу</option><option value="price">По цене окружения</option><option value="llcr">По LLCR</option><option value="area">По площади</option><option value="new">Сначала новые</option></select></div>
<div class="actions"><button class="primary" onclick="load()">Обновить представление</button><button onclick="location.href='/auctions?tab=krt'">Текущий production-интерфейс</button></div>
<div class="stats" id="stats"></div><div class="summary"><b id="found">Загружаю…</b><span class="countnote" id="coverage"></span></div><section class="cards" id="list"><div class="empty">Читаю рабочий каталог и готовый рейтинг…</div></section></main></div>
<script>
let rows=[],rank={}; const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=v=>{v=Number(v);return Number.isFinite(v)?v:null}, fmt=(v,d=0)=>n(v)===null?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(Number(v)), money=v=>n(v)===null?'—':fmt(v,0)+' ₽/м²';
function R(x){return rank[x.slug]||{}} function live(x){return (x.tender_lots||[]).some(l=>{let d=l.application_deadline_iso?new Date(l.application_deadline_iso):null;return !d||d>Date.now()})}
function stageOf(x){let s=String(x.status||'').toLowerCase();if(x.no_card)return'draft';if(live(x))return'tender';if((x.tender_lots||[]).length)return'announced';if(/реализ/.test(s))return'running';return'planned'}
function entryOf(x){if(stageOf(x)==='running')return'taken';let r=R(x),c=x.card_facts||r.card_facts,p=r.press_facts;if((c&&(c.operator_name||c.developer_name))||(p&&(p.operator_name||p.agreement||p.selling_now)))return'taken';if((c&&c.available)||(p&&p.available))return'free';return'unknown'}
function renoOf(x){let r=R(x),z=r.renovation||{},req=r.requirements||{},rr=req.renovation||{};if(n(z.spp_sqm)>0||n(rr.area_sqm)>0||z.mentioned===true||rr.mentioned===true)return'yes';if((x.card_facts&&x.card_facts.available)||(r.card_facts&&r.card_facts.available)||(r.press_facts&&r.press_facts.available)||rr.basis)return'no';return'unknown'}
function purposeOf(x,p){let h=n(x.housing_gfa_sqm)||n(R(x).housing_gfa_sqm)||0,b=n(x.business_gfa_sqm)||0,non=n(x.nonresidential_gfa_sqm)||0;if(p==='housing')return h>0;if(p==='business')return b>0;if(p==='nonres')return non>0;if(p==='unknown')return !(h||b||non);return true}
function val(x,k){let r=R(x);if(k==='score')return n(r.score)??n(x.score);if(k==='price')return n(r.surrounding_price_rub_sqm)??n(x.surrounding_price_rub_sqm);if(k==='llcr')return n(r.project_llcr_x);if(k==='area')return n(x.area_ha)??n(x.krt_area_ha);if(k==='new')return n(x.first_seen_at)||0;return 0}
function statusLabel(x){return {draft:'Проект решения',planned:'Планируемая',tender:'Идёт аукцион',announced:'Торги объявлялись',running:'В реализации'}[stageOf(x)]}
function card(x){let r=R(x),href='/krt-preview/site/'+encodeURIComponent(x.slug||''),price=val(x,'price'),reno=renoOf(x),entry=entryOf(x);let ceiling=r.entry_capacity_rub_per_sqm, total=r.entry_capacity_mln,llcr=r.project_llcr_x,margin=r.margin_pct,score=val(x,'score');
 return '<article class="card" onclick="location.href=\''+href+'\'"><div class="visual"><span>схема территории</span></div><div class="identity"><span class="badge '+(stageOf(x)==='tender'?'live':'')+'">'+esc(statusLabel(x))+'</span><div class="name">'+esc(x.name||x.address||x.slug)+'</div><div class="muted">'+esc([x.okrug,x.district,x.address].filter(Boolean).join(' · '))+'</div><div class="chips"><span class="chip">Вход: '+esc({free:'свободна',taken:'занята',unknown:'не знаем'}[entry])+'</span><span class="chip">Реновация: '+esc({yes:'есть',no:'не найдена',unknown:'не знаем'}[reno])+'</span></div></div><div class="numbers">'+
 [['Балл',fmt(score)],['Потолок входа',ceiling?money(ceiling)+(total?' · '+fmt(total,1)+' млн ₽':''):'—'],['LLCR',llcr?fmt(llcr,2)+'x':'—'],['Маржа',margin!==null&&margin!==undefined?fmt(margin,1)+'%':'—'],['Цена окружения',money(price)],['Площадь',fmt(x.area_ha??x.krt_area_ha,1)+' га'],['Общий объём',fmt(x.total_gfa_sqm)+' м²'],['Жильё',fmt(x.housing_gfa_sqm)+' м²']].map(a=>'<div class="num"><b>'+esc(a[1])+'</b><small>'+esc(a[0])+'</small></div>').join('')+'</div><div class="arrow">→</div></article>'}
const picks=id=>new Set([...$(id).querySelectorAll('input:checked')].map(o=>o.value).filter(Boolean)); function render(){let q=$('q').value.trim().toLowerCase(),os=picks('okrug'),sts=picks('stage'),ens=picks('entry'),res=picks('reno'),pus=picks('purpose'),mh=n($('minHousing').value),mp=n($('minPrice').value),sk=$('sort').value;
 let v=rows.filter(x=>(!q||[x.name,x.address,x.district,x.okrug].join(' ').toLowerCase().includes(q))&&(!os.size||os.has(x.okrug))&&(!sts.size||sts.has(stageOf(x)))&&(!ens.size||ens.has(entryOf(x)))&&(!res.size||res.has(renoOf(x)))&&(!pus.size||[...pus].some(p=>purposeOf(x,p)))&&(!mh||(n(x.housing_gfa_sqm)||0)>=mh)&&(!mp||(val(x,'price')||0)>mp));
 v.sort((a,b)=>(val(b,sk)??-Infinity)-(val(a,sk)??-Infinity));$('found').textContent='Найдено: '+v.length+' из '+rows.length;$('list').innerHTML=v.length?v.map(card).join(''):'<div class="empty">По выбранным условиям площадок нет.</div>';
 let totalArea=v.reduce((z,x)=>z+(n(x.area_ha??x.krt_area_ha)||0),0),housing=v.reduce((z,x)=>z+(n(x.housing_gfa_sqm)||0),0);
 let ss=[['Площадок',v.length],['Новые',v.filter(x=>x.is_new).length],['Идёт аукцион',v.filter(x=>stageOf(x)==='tender').length],['В реализации',v.filter(x=>stageOf(x)==='running').length],['Территория',fmt(totalArea,1)+' га'],['Жильё',fmt(housing)+' м²']];
 $('stats').innerHTML=ss.map(a=>'<div class="stat"><b>'+esc(a[1])+'</b><span>'+esc(a[0])+'</span></div>').join('')}
async function load(){try{let [c,rr]=await Promise.all([fetch('/krt-preview/data').then(r=>r.json()),fetch('/krt-preview/ranking').then(r=>r.json())]);rows=c.projects||[];rank={};(rr.rows||[]).forEach(x=>rank[x.slug]=x);let os=[...new Set(rows.map(x=>x.okrug).filter(Boolean))].sort();$('okrug').innerHTML=os.map(x=>'<label><input type="checkbox" value="'+esc(x)+'"> '+esc(x)+'</label>').join('');$('coverage').textContent='Рейтинг: '+Object.keys(rank).length+' строк · каталог: '+rows.length+' площадок';render()}catch(e){$('list').innerHTML='<div class="empty">Ошибка загрузки: '+esc(e.message)+'</div>'}}
['q','okrug','stage','entry','reno','purpose','minHousing','minPrice','sort'].forEach(id=>$(id).addEventListener(id==='q'||id.startsWith('min')?'input':'change',()=>{render();updateMulti()}));function updateMulti(){document.querySelectorAll('.multi').forEach(m=>{let id=m.dataset.id,n=$(id).querySelectorAll('input:checked').length,b=m.querySelector('button'),base={okrug:'Округа',stage:'Стадии КРТ',entry:'Возможность входа',reno:'Реновация',purpose:'Назначение'}[id];b.textContent=base+(n?' · '+n:'')})}document.querySelectorAll('.multi>button').forEach(b=>b.onclick=e=>{let m=b.parentElement,was=m.classList.contains('open');document.querySelectorAll('.multi').forEach(x=>x.classList.remove('open'));if(!was)m.classList.add('open');e.stopPropagation()});document.addEventListener('click',e=>{if(!e.target.closest('.multi'))document.querySelectorAll('.multi').forEach(x=>x.classList.remove('open'))});load();
</script></body></html>'''

PREVIEW_CARD = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>КРТ · DevelopAid</title><style>
:root{--bg:#f2f2ef;--line:#ddd;--muted:#6d6d6d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#171717;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial}.shell{max-width:1380px;margin:auto;background:#fff;min-height:100vh}.head{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);padding:14px 24px}.head b{font-size:20px}.nav{display:flex;gap:16px;overflow:auto;margin-top:9px}.nav a{color:#222;text-decoration:none;white-space:nowrap}.main{padding:22px 24px}.hero{border-bottom:7px solid #111;padding-bottom:18px}.hero h1{font-size:29px;margin:6px 0}.badge{display:inline-block;border:1px solid #bbb;padding:4px 7px}.metrics{display:grid;grid-template-columns:repeat(6,1fr);border:1px solid var(--line);margin-top:16px}.metric{padding:11px;border-right:1px solid var(--line)}.metric b{display:block;font-size:17px}.metric small,.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;margin-top:16px}.sec{border:1px solid var(--line);padding:18px;margin-bottom:12px;scroll-margin-top:90px}.sec h2{margin:0 0 12px;font-size:18px}.cols{display:grid;grid-template-columns:1fr 1fr;gap:10px}.box{border:1px solid var(--line);background:#f8f8f6;padding:11px;margin:8px 0;white-space:pre-wrap}.actions{position:sticky;top:92px;height:max-content;border:1px solid var(--line);padding:14px}.actions a,.actions button{display:block;width:100%;padding:10px;margin:7px 0;border:1px solid #111;background:#fff;color:#111;text-decoration:none;text-align:left;font:inherit;font-weight:650}.actions .primary{background:#111;color:#fff}details{border-top:1px solid var(--line);padding:9px 0}summary{cursor:pointer;font-weight:650}.tender{border-left:5px solid #111}.links a{margin-right:12px}.mapimg{max-width:100%;border:1px solid var(--line)}@media(max-width:800px){.main{padding:12px}.head{padding:12px}.grid{display:block}.actions{position:static;margin-bottom:12px}.metrics{grid-template-columns:1fr 1fr}.cols{grid-template-columns:1fr}.hero h1{font-size:24px}}</style></head><body><div class="shell"><header class="head"><b>DevelopAid · КРТ</b><nav class="nav"><a href="#overview">Обзор</a><a href="#city">Город</a><a href="#load">Нагрузка</a><a href="#territory">Территория</a><a href="#press">Публикации</a><a href="#market">Рынок</a><a href="#tender">Торги</a><button id="platoTop" style="border:1px solid #111;background:#111;color:#fff;padding:5px 10px">Платон</button></nav></header><main class="main"><a href="/krt-preview">← Все площадки</a><section class="hero" id="overview"><span class="badge" id="status">КРТ</span><h1 id="title">Загрузка…</h1><div class="muted" id="where"></div><div class="metrics" id="metrics"></div></section><div class="grid"><div>
<section class="sec" id="city"><h2>Что разрешает и требует город</h2><div id="cityBody">Загружаю решение и ТЭП…</div><div class="links" id="sourceLinks"></div></section>
<section class="sec" id="load"><h2>Нагрузка и обязательства</h2><div id="loadBody">Читаю требования решения…</div><details><summary id="demoSummary">Объекты под снос</summary><div id="demoBody"></div></details></section>
<section class="sec" id="territory"><h2>Территория, карта и схемы</h2><p>Свод территории, участки, ЕГРН и правообладатели остаются теми же данными существующей карточки.</p><div class="links"><a id="territoryLink">Открыть карту и разбивку территории ↗</a> <a id="outlineLink">Схема границ города ↗</a></div></section>
<section class="sec" id="press"><h2>Что известно о проекте</h2><div id="pressBody">Сохранённые публикации и признаки оператора загружаются из рейтинга.</div><button id="pressBtn">Обновить поиск публикаций</button><div id="pressResult" class="box" style="display:none"></div></section>
<section class="sec" id="market"><h2>Экономика и окружение</h2><div id="marketBody">Загружаю готовый прогон…</div></section>
<section class="sec tender" id="tender"><h2>Торги</h2><div id="tenderBody"></div></section>
</div><aside class="actions"><b>Действия</b><a class="primary" id="handoff">Передать в расчёт DevelopAid</a><a id="old">Полная текущая карточка</a><a id="export">Скачать Excel</a><button onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href)">Скопировать ссылку</button></aside></div></main></div><div class="modal" id="platoModal"><div class="modal-card"><div class="modal-head"><b>Платон · КРТ</b><button id="platoClose">×</button></div><div class="modal-body"><p class="muted">ИИ-агент по текущей площадке. Контекст — данные КРТ, документы города, рынок, модель и торги.</p><div id="platoContext" class="box"></div><div class="askrow"><input id="platoQuestion" placeholder="Спросить Платона об этой площадке"><button id="platoAsk">Спросить</button></div><div id="platoAnswer" class="box">Рекомендация загружается из готового отчёта.</div></div></div></div><script>
const slug=decodeURIComponent(location.pathname.split('/').pop()),$=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),fmt=(v,d=0)=>v===null||v===undefined||v===''?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(Number(v));
async function j(u){let r=await fetch(u),t=await r.text(),d;try{d=JSON.parse(t)}catch(e){}if(!r.ok)throw Error((d&&d.detail)||t.slice(0,150)||r.status);return d}
function listFacts(p){if(!p)return 'Поиск ещё не выполнялся.';let bits=[];if(p.operator_name)bits.push('Оператор: '+p.operator_name);for(let k of ['operator_named','operator_appointed','agreement','selling_now','city_needs'])for(let x of (p[k]||[]))bits.push((x.name?x.name+' — ':'')+(x.quote||x.title||JSON.stringify(x)));return bits.length?bits.join('\n\n'):'Прочитанных признаков оператора / договора / реализации пока нет.'}
function openPlato(){ $('platoModal').classList.add('open') } $('platoTop').onclick=openPlato;$('platoClose').onclick=()=>$('platoModal').classList.remove('open');async function boot(){let [cat,rr,dd]=await Promise.all([j('/krt-preview/data'),j('/krt-preview/ranking'),j('/krt-preview/decisions').catch(()=>({matched_rows:[],tep:{}}))]),rows=cat.projects||[],r=rows.find(x=>String(x.slug||'')===slug);if(!r)throw Error('Площадка '+slug+' не найдена в рабочем каталоге');let rank=(rr.rows||[]).find(x=>x.slug===slug)||{}, dm=(dd.matched_rows||[]).find(x=>x.slug===slug)||{}, dtep=(dd.tep||{})[String(dm.id||'')]||null, place=[r.name,r.address,r.district].filter(Boolean).join(' '), isNagatino=/варшавск[^0-9]{0,40}37|нагатинск[^0-9]{0,40}3\s*[аa]/i.test(place), nag=null;if(isNagatino){try{nag=await j('/krt-preview/nagatino/source')}catch(e){nag=null}};
$('title').textContent=r.name||r.address||slug;$('platoContext').textContent=(r.name||slug)+' · '+[r.okrug,r.district].filter(Boolean).join(' · ');$('status').textContent=r.status|| (r.no_card?'Проект решения':'КРТ');$('where').textContent=[r.okrug,r.district,r.address].filter(Boolean).join(' · ');
let tep=(nag&&nag.tep)||dtep||r, ms=[['Площадь',fmt(tep.area_ha??r.area_ha??r.krt_area_ha,1)+' га'],['Общий объём',fmt(tep.total_gfa_sqm??r.total_gfa_sqm)+' м²'],['Жильё',fmt(tep.housing_gfa_sqm??r.housing_gfa_sqm)+' м²'],['Балл',fmt(rank.score??r.score)],['LLCR',rank.project_llcr_x?fmt(rank.project_llcr_x,2)+'x':'—'],['Цена окружения',rank.surrounding_price_rub_sqm?fmt(rank.surrounding_price_rub_sqm)+' ₽/м²':'—']];$('metrics').innerHTML=ms.map(x=>'<div class="metric"><b>'+esc(x[1])+'</b><small>'+esc(x[0])+'</small></div>').join('');
$('old').href=isNagatino?'/krt/nagatino':'/krt/site/'+encodeURIComponent(slug);$('territoryLink').href=isNagatino?'/krt/nagatino':'/krt/site/'+encodeURIComponent(slug);$('outlineLink').href=isNagatino?'/krt-preview/nagatino/decision-outline.png':'/krt/site/'+encodeURIComponent(slug)+'/decision-outline.png';$('export').href=isNagatino?'/krt/nagatino/export.xlsx':'/krt/site/'+encodeURIComponent(slug)+'/export.xlsx';$('handoff').href='/auctions/krt/'+encodeURIComponent(slug)+'/handoff';
let links=[];if(r.url)links.push('<a target="_blank" href="'+esc(r.url)+'">Карточка КРТ на krt.mos.ru ↗</a>');if(dm.url)links.push('<a target="_blank" href="'+esc(dm.url)+'">Проект решения на mos.ru ↗</a>');else if(r.decision_url)links.push('<a target="_blank" href="'+esc(r.decision_url)+'">Проект решения mos.ru ↗</a>');if(r.source&&r.source.url)links.push('<a target="_blank" href="'+esc(r.source.url)+'">Источник ↗</a>');$('sourceLinks').innerHTML=links.join('');
$('cityBody').innerHTML='<div class="cols"><div class="box"><b>ТЭП из проекта решения'+(dm.id?' №'+esc(dm.id):'')+'</b><br>Площадь территории '+fmt(tep.area_ha,2)+' га<br>Предельная СПП '+fmt(tep.total_gfa_sqm)+' м²<br>Жилое назначение '+fmt(tep.housing_gfa_sqm)+' м²<br>Нежилое назначение '+fmt(tep.nonresidential_gfa_sqm)+' м²'+(tep.flats_sqm!=null?'<br>Площадь квартир '+fmt(tep.flats_sqm)+' м²':'')+'</div><div class="box"><b>Карточка каталога — для сверки</b><br>СПП '+fmt(r.total_gfa_sqm)+' м²<br>Жильё '+fmt(r.housing_gfa_sqm)+' м²<br>Нежилое '+fmt(r.nonresidential_gfa_sqm)+' м²<br>Статус '+esc(r.status||'—')+'</div></div>';
try{let req=await j('/krt-preview/proxy/'+encodeURIComponent(slug)+'/requirements'), groups=[['Снос',req.demolition||[]],['Снос или реконструкция',req.demolition_or_reconstruction||[]],['Реконструкция',req.reconstruction||[]],['Сохранение',req.preservation||[]]], total=groups.reduce((n,x)=>n+x[1].length,0);$('loadBody').innerHTML='<div class="cols"><div class="box"><b>Городские нужды / реновация</b><br>'+esc(req.renovation&&req.renovation.mentioned?(req.renovation.area_sqm?fmt(req.renovation.area_sqm)+' м²':req.renovation.quote||'Упомянуты, объём не назван'):'В проекте решения не подтверждены')+'</div><div class="box"><b>Что требует документ</b><br>'+esc((req.warning||'Требования прочитаны из официального документа'))+'</div></div>';$('demoSummary').textContent='Объекты: снос / реконструкция / сохранение — '+total;$('demoBody').innerHTML=groups.filter(x=>x[1].length).map(x=>'<div class="box"><b>'+esc(x[0])+' — '+x[1].length+'</b><br>'+esc(x[1].join('\n'))+'</div>').join('')||'<div class="box">В опубликованном проекте решения перечень действий по объектам не найден.</div>';if(nag&&nag.objects){let ng=[['Снос',nag.objects.demolition||[],nag.totals.demolition],['Снос или реконструкция',nag.objects.conditional||[],nag.totals.conditional],['Реконструкция',nag.objects.reconstruction||[],nag.totals.reconstruction],['Сохранение',nag.objects.preservation||[],nag.totals.preservation]];let nn=ng.reduce((z,x)=>z+x[1].length,0);$('demoSummary').textContent='Извещение торгов: судьба объектов — '+nn+' из '+(nag.objects_total||nn);$('demoBody').innerHTML=ng.filter(x=>x[1].length).map(x=>'<div class="box"><b>'+esc(x[0])+' — '+x[1].length+' · '+fmt((x[2]||{}).area_sqm,1)+' м²</b><br>'+x[1].map(o=>esc((o.cadastral_number||'')+(o.address?' · '+o.address:'')+(o.fate?' · '+o.fate:'')+(o.area_sqm?' · '+fmt(o.area_sqm,1)+' м²':''))).join('<br>')+'</div>').join('')}</div>'} }catch(e){$('loadBody').textContent='Требования пока не прочитаны: '+e.message}
$('pressBody').innerHTML='<div class="box">'+esc(listFacts(rank.press_facts))+'</div>';$('pressBtn').onclick=async()=>{let b=$('pressResult');b.style.display='';b.textContent='Ищу…';try{b.textContent=listFacts(await j('/krt-preview/proxy/'+encodeURIComponent(slug)+'/open-sources'))}catch(e){b.textContent=e.message}};
try{let a=await j('/krt-preview/proxy/report/'+encodeURIComponent(slug)),sc=a.screening||{},mr=sc.market_report||a.market||{},rec=a.plato||a.recommendation||sc.plato||sc.recommendation||'';$('platoAnswer').textContent=typeof rec==='string'&&rec?rec:'Готовой текстовой рекомендации в отчёте нет — откройте Платона для анализа текущей площадки.';$('marketBody').innerHTML='<div class="cols"><div class="box"><b>Модель</b><br>LLCR '+esc(fmt(rank.project_llcr_x??sc.project_llcr_x,2))+'x<br>Маржа '+esc(fmt(rank.margin_pct??sc.margin_pct,1))+'%<br>Потолок входа '+esc(fmt(rank.entry_capacity_rub_per_sqm))+' ₽/м²</div><div class="box"><b>Окружение</b><br>Цена '+esc(fmt(rank.surrounding_price_rub_sqm))+' ₽/м²<br>'+esc(JSON.stringify(mr,null,2))+'</div></div>'}catch(e){$('marketBody').textContent='Готовый отчёт: '+e.message}
let lots=r.tender_lots||[];
if(lots.length){$('tenderBody').innerHTML='<span class="badge" style="border-color:#922;color:#922"><b>Идут / опубликованы торги</b></span><b style="display:block;margin-top:9px">Связанные лоты: '+lots.length+'</b>'+lots.map(l=>'<div class="box">'+esc(l.title||l.name||'Лот')+'<br>'+esc(l.application_deadline||l.deadline||l.application_deadline_iso||'')+(l.url||l.lot_url?'<br><a target="_blank" href="'+esc(l.url||l.lot_url)+'">Открыть лот ↗</a>':'')+'</div>').join('')+'<a href="'+(isNagatino?'/krt/nagatino':'/krt/site/'+encodeURIComponent(slug))+'"><b>Открыть существующий разбор территории и лота →</b></a>'}else if(nag&&nag.auction&&nag.auction.announced){$('tenderBody').innerHTML='<span class="badge" style="border-color:#922;color:#922"><b>Торги объявлены</b></span><div class="box">По этой территории в эталонном пакете есть официальное извещение о торгах. Связанный live-лот в строке каталога сейчас не приехал, поэтому срок не выдумываем.</div><a href="'+esc(nag.auction.analysis_url||'/krt/nagatino')+'"><b>Открыть разбор лота Нагатино →</b></a>'}else $('tenderBody').innerHTML='<div class="box">Связанный лот в рабочем каталоге сейчас не найден. Это «связку не получили», а не утверждение, что торгов нет.</div>';
}boot().catch(e=>{$('title').textContent='Карточка не открылась';$('where').textContent=e.message});
</script></body></html>'''

def install(app):
    @app.get("/krt-preview/proxy/nagatino/parcels", include_in_schema=False)
    async def krt_preview_nagatino_parcels():
        url = "https://plato-development-investment-model.onrender.com/krt/nagatino/parcels"
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=55) as response:
                return JSONResponse(json.loads(response.read().decode("utf-8")), headers={"Cache-Control":"no-store"})
        except Exception as exc:
            return JSONResponse({"error":str(exc)}, status_code=502)

    @app.get("/krt-preview/proxy/{slug}/requirements", include_in_schema=False)
    async def krt_preview_requirements(slug: str):
        url = "https://plato-development-investment-model.onrender.com/auctions/krt/" + urllib.parse.quote(slug) + "/requirements"
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=55) as response:
                return JSONResponse(json.loads(response.read().decode("utf-8")), headers={"Cache-Control":"no-store"})
        except Exception as exc:
            return JSONResponse({"available":False,"reason":str(exc)}, status_code=502)

    @app.get("/krt-preview/proxy/{slug}/open-sources", include_in_schema=False)
    async def krt_preview_open_sources(slug: str):
        url = "https://plato-development-investment-model.onrender.com/auctions/krt/" + urllib.parse.quote(slug) + "/open-sources"
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=90) as response:
                return JSONResponse(json.loads(response.read().decode("utf-8")), headers={"Cache-Control":"no-store"})
        except Exception as exc:
            return JSONResponse({"available":False,"reason":str(exc)}, status_code=502)

    @app.get("/krt-preview/decisions", include_in_schema=False)
    async def krt_preview_decisions():
        url = "https://plato-development-investment-model.onrender.com/auctions/krt/decisions"
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=55) as response:
                return JSONResponse(json.loads(response.read().decode("utf-8")),
                                    headers={"Cache-Control":"no-store"})
        except Exception as exc:
            return JSONResponse({"error":str(exc),"matched_rows":[],"tep":{}},
                                status_code=502)

    @app.get("/krt-preview/nagatino/source", include_in_schema=False)
    async def krt_preview_nagatino_source():
        """Bundled official source package: auction notice, EGRN extracts and draft decision."""
        try:
            from auction_search import nagatino_parcels
            from market_search.krt_requirements import pdf_text
            from market_search import krt_decision_tep

            territory = nagatino_parcels.territory()
            text = pdf_text(nagatino_parcels.DECISION_PATH.read_bytes())
            tep = krt_decision_tep.parse(text)
            groups = {"demolition": [], "conditional": [], "reconstruction": [],
                      "preservation": [], "other": []}
            for item in territory.get("objects") or []:
                fate = str(item.get("fate") or "").strip()
                low = fate.casefold()
                if "снос" in low and "рекон" in low:
                    kind = "conditional"
                elif "снос" in low or "демонт" in low:
                    kind = "demolition"
                elif "рекон" in low:
                    kind = "reconstruction"
                elif "сохран" in low:
                    kind = "preservation"
                else:
                    kind = "other"
                area = item.get("area_sqm")
                if area in (None, ""):
                    area = item.get("notice_area_sqm")
                groups[kind].append({
                    "cadastral_number": item.get("cadastral_number") or "",
                    "address": item.get("address") or "",
                    "name": item.get("name") or "",
                    "fate": fate,
                    "area_sqm": area,
                })
            totals = {}
            for key, items in groups.items():
                totals[key] = {
                    "count": len(items),
                    "area_sqm": round(sum(float(x.get("area_sqm") or 0) for x in items), 1),
                }
            return JSONResponse({
                "tep": tep,
                "objects": groups,
                "totals": totals,
                "territory_totals": territory.get("totals") or {},
                "lands": len(territory.get("lands") or []),
                "objects_total": len(territory.get("objects") or []),
                "auction": {
                    "announced": True,
                    "source": "Приложение № 2 к извещению о торгах",
                    "analysis_url": "/krt/nagatino",
                },
            }, headers={"Cache-Control":"no-store"})
        except Exception as exc:
            return JSONResponse({"error":f"{type(exc).__name__}: {exc}"}, status_code=502)

    @app.get("/krt-preview/nagatino/decision-outline.png", include_in_schema=False)
    async def krt_preview_nagatino_outline():
        try:
            from auction_search import nagatino_parcels
            raw = nagatino_parcels.decision_outline_picture()
            return Response(raw, media_type="image/png",
                            headers={"Cache-Control":"public,max-age=86400"})
        except Exception as exc:
            return JSONResponse({"detail":str(exc)}, status_code=502)

    @app.get("/krt-preview/ranking", include_in_schema=False)
    async def krt_preview_ranking():
        url = "https://plato-development-investment-model.onrender.com/auctions/krt/ranking"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=55) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except Exception as exc:
            return JSONResponse({"error": str(exc), "rows": []}, status_code=502)

    @app.get("/krt-preview/proxy/report/{slug}", include_in_schema=False)
    async def krt_preview_report(slug: str):
        url = "https://plato-development-investment-model.onrender.com/auctions/krt/" + urllib.parse.quote(slug) + "/report"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=55) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)

    @app.get("/krt-preview/site/{slug}", response_class=HTMLResponse, include_in_schema=False)
    async def krt_preview_site(slug: str):
        return HTMLResponse(PREVIEW_CARD, headers={"Cache-Control":"no-store, must-revalidate"})

    @app.get("/krt-preview/data", include_in_schema=False)
    async def krt_preview_data():
        # Preview has an isolated filesystem. Read the real catalogue from
        # production so design testing uses the same KRT rows the user sees.
        url = "https://plato-development-investment-model.onrender.com/auctions/krt"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DevelopAid-KRT-preview/1"})
            with urllib.request.urlopen(req, timeout=55) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except Exception as exc:
            return JSONResponse({"error": str(exc), "sites": []}, status_code=502)

    @app.get("/krt-preview", response_class=HTMLResponse, include_in_schema=False)
    async def krt_preview():
        return HTMLResponse(PAGE, headers={"Cache-Control":"no-store, must-revalidate"})
