from __future__ import annotations

from html import escape


AUCTIONS_PAGE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · Торги Москвы</title>
<style>
/* Палитра, шрифт и формы — те же, что у DevelopAid: сервис один, и страница
   торгов не должна выглядеть чужой. Прямые углы, тонкая серая линия, чёрная
   кнопка, системный шрифт (замечание владельца, 23.08.2026). */
:root{--bg:#f2f2ef;--panel:#fff;--text:#171717;--muted:#6b6b6b;--line:#dedede;--soft:#f7f7f5;--accent:#111;--ok:#1f6b3b;--warn:#8a5a00;--bad:#a33}

*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}.shell{max-width:1500px;margin:auto;padding:24px}.head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:18px}.head h1{font-size:27px;line-height:1.05;margin:0 0 5px}.head p{margin:0;color:var(--muted)}.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:0;padding:6px 10px;font-size:12px;background:var(--panel)}.filters{display:grid;grid-template-columns:1fr 1fr 1fr minmax(220px,1.5fr) auto;gap:9px;margin-bottom:14px}select,input,button{min-height:42px;border:1px solid var(--line);border-radius:0;background:var(--panel);color:var(--text);padding:0 11px;font:inherit}button{cursor:pointer;font-weight:700;border-color:#111}button.primary{background:var(--accent);color:#fff}button:disabled{opacity:.45;cursor:not-allowed}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:14px}.stat{border:1px solid var(--line);border-radius:0;background:var(--panel);padding:12px}.stat b{font-size:22px;display:block}.stat span{font-size:12px;color:var(--muted)}.coverage{display:none}.layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(360px,.8fr);gap:12px}.tablewrap,.side{border:1px solid var(--line);background:var(--panel);border-radius:0;overflow:hidden}.tablewrap{overflow:auto;min-height:420px}table{border-collapse:collapse;width:100%;min-width:900px}th{position:sticky;top:0;background:var(--panel);z-index:1;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.045em;text-align:left;padding:11px 12px;border-bottom:1px solid var(--line)}td{padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:top}tbody tr{cursor:pointer}tbody tr:hover{background:var(--soft)}.lotname{font-weight:700;margin-bottom:4px;max-width:360px}.cad{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted)}.tag{display:inline-flex;padding:4px 7px;border-radius:0;background:var(--soft);font-size:11px;font-weight:700}.tag.ok{color:var(--ok)}.tag.warn{color:var(--warn)}.money{font-weight:750;white-space:nowrap}.side{padding:16px;min-height:420px}.side h2{font-size:18px;margin:0 0 4px}.side .sub{color:var(--muted);font-size:12px;margin-bottom:14px}.empty{display:grid;place-items:center;color:var(--muted);min-height:360px;text-align:center;padding:25px}.kv{display:grid;grid-template-columns:145px 1fr;gap:7px 10px;padding:10px 0;border-bottom:1px solid var(--line)}.kv div:nth-child(odd){color:var(--muted)}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.notice{border-radius:0;padding:10px 11px;background:var(--soft);font-size:12px;margin:10px 0}.notice.warn{color:var(--warn)}.section{margin-top:16px}.section h3{font-size:13px;margin:0 0 7px}.items{display:grid;gap:6px}.item{border:1px solid var(--line);border-radius:0;padding:8px 9px;font-size:12px}.item b{display:block;margin-bottom:2px}.source{font-size:11px;color:var(--muted);margin-top:4px}.status{font-size:12px;color:var(--muted);margin-left:auto}.spinner{display:inline-block;width:13px;height:13px;border:2px solid var(--line);border-top-color:var(--text);border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;margin-right:5px}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:950px){.filters{grid-template-columns:1fr 1fr}.stats{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}.side{min-height:0}.shell{padding:14px}}
.tabs{display:flex;gap:7px;margin:0 0 14px}.tabs button.on{background:var(--accent);color:var(--bg)}.hidden{display:none!important}.fit{display:inline-flex;align-items:center;gap:6px;font-weight:750;white-space:nowrap}.fit .light{width:10px;height:10px;border-radius:50%;background:var(--muted);}.fit.ok{color:var(--ok)}.fit.ok .light{background:var(--ok)}.fit.warn{color:var(--warn)}.fit.warn .light{background:var(--warn)}.fit.bad{color:var(--bad)}.fit.bad .light{background:var(--bad)}
.multi{position:relative;min-width:0}.multi-toggle{width:100%;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:30px;position:relative}.multi-toggle:after{content:'⌄';position:absolute;right:11px;font-size:16px;line-height:1}.multi-toggle[aria-expanded="true"]:after{content:'⌃'}.multi-menu{position:absolute;z-index:20;top:calc(100% + 6px);left:0;width:max-content;min-width:100%;max-width:min(320px,80vw);padding:8px;border:1px solid var(--line);border-radius:0;background:var(--panel);}.multi-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:2px 4px 7px;font-size:12px;font-weight:750;color:var(--muted)}.multi-clear{min-height:28px;padding:0 7px;border:0;background:transparent;color:var(--muted);font-size:12px}.multi-options{display:grid;gap:2px;max-height:310px;overflow:auto}.multi-option{display:flex;align-items:center;gap:9px;min-height:36px;padding:5px 7px;border-radius:0;cursor:pointer}.multi-option:hover{background:var(--soft)}.multi-option input{flex:0 0 auto;width:17px;height:17px;min-height:0;margin:0;padding:0;accent-color:var(--accent)}
</style>
</head>
<body>
<div class="shell">
  <div class="head">
    <div><h1>Торги · Москва</h1><p>Официальные ЭТП → проверка лота → документы КРТ → DevelopAid</p></div>
    <div class="badge">primary-source only</div>
  </div>
  <div class="tabs"><button id="tabAuctions" class="on">Текущие торги</button><button id="tabKrt">Проекты КРТ Москвы</button></div>
  <div id="krtPanel" class="hidden">
    <div class="filters" style="grid-template-columns:2fr repeat(4,1fr) auto">
      <input id="krtSearch" placeholder="Название КРТ или район">
      <div class="multi" id="krtOkrug">
        <button type="button" class="multi-toggle" id="krtOkrugToggle" aria-haspopup="true" aria-expanded="false" aria-controls="krtOkrugMenu">Все округа</button>
        <div class="multi-menu hidden" id="krtOkrugMenu">
          <div class="multi-head"><span>Выберите округа</span><button type="button" class="multi-clear" id="krtOkrugClear">Сбросить</button></div>
          <div class="multi-options" id="krtOkrugOptions"></div>
        </div>
      </div>
      <select id="krtStatus"><option value="">Все статусы</option><option>Планируемый</option><option>В реализации</option></select>
      <select id="krtPurpose"><option value="">Любое назначение</option><option value="housing_gfa_sqm">Жильё</option><option value="business_gfa_sqm">Общественно-деловое</option><option value="nonresidential_gfa_sqm">Нежилое</option></select>
      <select id="krtProfile" title="Критерии предварительной оценки Платона"><option value="housing_ready">Платон: жильё и быстрый старт</option><option value="housing_pipeline">Платон: жилищный потенциал</option><option value="business">Платон: деловая застройка</option></select>
      <button id="krtRefresh" class="primary">Обновить каталог</button>
      <button id="krtRankBtn">Оценить отобранные моделью</button>
    </div>
    <div class="stats"><div class="stat"><b id="krtCount">—</b><span>проектов</span></div><div class="stat"><b id="krtArea">—</b><span>га территории</span></div><div class="stat"><b id="krtHousing">—</b><span>м² жилья</span></div><div class="stat"><b id="krtGfa">—</b><span>м² всего</span></div></div>
    <div id="krtRankStatus" class="notice" style="display:none"></div>
    <div class="layout"><div class="tablewrap"><table><thead><tr><th>Проект КРТ</th><th>Оценка Платона</th><th title="Предельная цена входа при LLCR 1,20x, на метр продаваемой площади">Потолок входа, ₽/м²</th><th>Статус</th><th>Площадь</th><th>Общий объём</th><th>Жильё</th><th>Рабочие места</th></tr></thead><tbody id="krtRows"></tbody></table><div id="krtEmpty" class="empty">Открываю официальный каталог krt.mos.ru…</div></div><aside class="side" id="krtSide"><div class="empty">Выберите проект КРТ.<br>ТЭП берутся из krt.mos.ru, рынок считает существующий движок DevelopAid.</div></aside></div>
  </div>
  <div class="filters" id="auctionFilters">
    <select id="source"><option value="all">Все официальные источники</option><option value="investmoscow">Торги Москвы → ЭТП</option><option value="lot_online">РАД / Lot-online</option><option value="roseltorg">Росэлторг</option></select>
    <select id="kind"><option value="all">Все типы</option><option value="krt">КРТ</option><option value="land_sale">Продажа земли</option><option value="land_lease">Аренда земли</option><option value="property_complex">ЗИК</option></select>
    <select id="noise"><option value="0">Девелоперские</option><option value="1">Показать всё</option></select>
    <input id="search" placeholder="Адрес / кадастр / лот">
    <button id="refresh" class="primary">Обновить</button>
  </div>
  <div class="stats" id="auctionStats">
    <div class="stat"><b id="sCount">—</b><span>лотов в выборке</span></div>
    <div class="stat"><b id="sKrt">—</b><span>КРТ</span></div>
    <div class="stat"><b id="sLand">—</b><span>земля / аренда</span></div>
    <div class="stat"><b id="sDeadline">—</b><span>ближайший дедлайн</span></div>
  </div>
  <div id="coverage" class="notice coverage"></div>
  <div class="layout" id="auctionLayout">
    <div class="tablewrap"><table><thead><tr><th>Лот</th><th>Тип</th><th>Площадь</th><th>Текущая цена</th><th>Заявка до</th><th>Документы</th></tr></thead><tbody id="rows"></tbody></table><div id="tableEmpty" class="empty">Нажмите «Обновить», чтобы получить текущую выборку с официальных площадок.</div></div>
    <aside class="side" id="side"><div class="empty">Выберите лот.<br>Карточка справа показывает только данные ЭТП; аналитика DevelopAid появляется после разбора.</div></aside>
  </div>
</div>
<script>
const state={lots:[],filtered:[],coverage:[],selected:null,ingested:null,krt:[],krtFiltered:[],krtOkrugs:new Set(),krtModels:{},krtReports:{},krtPolls:0,krtTimer:null,krtRank:{},krtRankProgress:null,krtRankTimer:null};
const KRT_OKRUGS=['ЦАО','САО','СВАО','ВАО','ЮВАО','ЮАО','ЮЗАО','ЗАО','СЗАО','НАО','ТАО','ЗелАО'];
const $=id=>document.getElementById(id);
const fmtMoney=n=>Number.isFinite(Number(n))?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(Number(n)/1e6)+' млн ₽':'—';
const fmtArea=n=>n!==null&&n!==undefined&&n!==''&&Number.isFinite(Number(n))?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(Number(n))+' м²':'—';
const fmtMln=n=>n!==null&&n!==undefined&&Number.isFinite(Number(n))?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(Number(n))+' млн ₽':'—';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindLabel=k=>({krt:'КРТ',land_sale:'Продажа земли',land_lease:'Аренда земли',property_complex:'ЗИК',unfinished:'Незавершёнка',other:'Другое'})[k]||k||'—';
function shortDate(v){if(!v)return '—';const d=new Date(v);return Number.isNaN(d.getTime())?String(v).slice(0,16):new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d)}
function filter(){const q=$('search').value.trim().toLowerCase(),k=$('kind').value;state.filtered=state.lots.filter(l=>(k==='all'||l.lot_kind===k)&&(!q||JSON.stringify([l.title,l.address,l.cadastral_numbers,l.source?.external_lot_id]).toLowerCase().includes(q)));renderRows();stats()}
function renderRows(){const body=$('rows'),empty=$('tableEmpty');body.innerHTML='';empty.style.display=state.filtered.length?'none':'grid';state.filtered.forEach((l,i)=>{const tr=document.createElement('tr');tr.innerHTML=`<td><div class="lotname">${esc(l.title||l.address||'Лот')}</div><div class="source">Почему здесь: ${esc(l.screening?.why_here||l.selection_reasons?.slice(0,4).join(' · ')||'требуется проверка')}</div><div class="cad">${esc((l.cadastral_numbers||[]).join(', ')||l.source?.external_lot_id||'')}</div></td><td><span class="tag ${l.lot_kind==='krt'?'ok':''}">${esc(kindLabel(l.lot_kind))}</span></td><td>${fmtArea(l.land_area_sqm)}</td><td class="money">${fmtMoney(l.current_price_rub??l.start_price_rub)}</td><td>${esc(shortDate(l.application_deadline))}</td><td>${l.documents?.length||0}</td>`;tr.onclick=()=>selectLot(l);body.appendChild(tr)})}
function stats(){const a=state.filtered;$('sCount').textContent=a.length;$('sKrt').textContent=a.filter(x=>x.lot_kind==='krt').length;$('sLand').textContent=a.filter(x=>['land_sale','land_lease'].includes(x.lot_kind)).length;const ds=a.map(x=>new Date(x.application_deadline)).filter(x=>!Number.isNaN(x.getTime())).sort((a,b)=>a-b);$('sDeadline').textContent=ds.length?new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit'}).format(ds[0]):'—'}
function renderCoverage(){const box=$('coverage'),r=(state.coverage||[])[0];if(!r){box.style.display='none';return}const unsupported=(r.unsupported_etp_hosts||[]).join(', ');box.style.display='block';box.className='notice coverage'+((r.errors||[]).length?' warn':'');box.textContent=`Торги Москвы: карточек ${r.city_cards||0} · ссылок на ЭТП ${r.official_etp_links||0} · подтверждено ${r.verified_lots||0} · без подтверждённой ЭТП ${r.unresolved_city_cards||0}${unsupported?' · нужны адаптеры: '+unsupported:''}${(r.errors||[]).length?' · часть каталога недоступна':''}`}
function selectLot(l){state.selected=l;state.ingested=null;const side=$('side');side.innerHTML=`<h2>${esc(l.title||'Лот')}</h2><div class="sub">${esc(l.source?.source_name||l.source?.platform||'ЭТП')} · ${esc(l.source?.external_lot_id||'')}</div><div class="kv"><div>Юр. конструкция</div><div>${esc(kindLabel(l.lot_kind))}</div><div>Кадастр</div><div class="cad">${esc((l.cadastral_numbers||[]).join(', ')||'—')}</div><div>Площадь</div><div>${fmtArea(l.land_area_sqm)}</div><div>Цена сейчас</div><div class="money">${fmtMoney(l.current_price_rub??l.start_price_rub)}</div><div>Минимальная цена</div><div>${fmtMoney(l.min_price_rub)}</div><div>Заявка до</div><div>${esc(shortDate(l.application_deadline))}</div><div>ВРИ площадки</div><div>${esc(l.permitted_use||'—')}</div></div><div class="actions"><button class="primary" id="ingestBtn">Разобрать лот</button><button id="sourceBtn">Открыть ЭТП</button></div><div id="detailStatus" class="notice">Документы пока только перечислены. Полный разбор запускается по выбранному лоту, чтобы не нагружать ЭТП массовыми скачиваниями.</div><div id="analysis"></div>`;$('ingestBtn').onclick=ingest;$('sourceBtn').onclick=()=>window.open(l.source?.lot_url,'_blank','noopener')}
async function discover(){const btn=$('refresh');btn.disabled=true;btn.innerHTML='<span class="spinner"></span>Читаю ЭТП';$('tableEmpty').style.display='grid';$('tableEmpty').textContent='Получаю публичный каталог официальной площадки…';try{const qs=new URLSearchParams({source:$('source').value,include_noise:$('noise').value==='1'?'true':'false'});const r=await fetch('/auctions/discover?'+qs);const d=await r.json();if(!r.ok)throw new Error(d.detail||'Не удалось получить каталог');state.lots=d.lots||[];state.coverage=d.coverage||[];renderCoverage();filter();if(!state.lots.length){$('tableEmpty').textContent='Подтверждённых текущих лотов не найдено. Воронка источников показана выше.'}}catch(e){state.lots=[];state.coverage=[];renderCoverage();filter();$('tableEmpty').style.display='grid';$('tableEmpty').textContent=String(e.message||e)}finally{btn.disabled=false;btn.textContent='Обновить'}}
async function ingest(){const l=state.selected;if(!l)return;const b=$('ingestBtn'),status=$('detailStatus');b.disabled=true;b.innerHTML='<span class="spinner"></span>Разбираю';status.textContent=l.lot_kind==='krt'?'Читаю карточку и официальные документы КРТ…':'Повторно сверяю официальную карточку…';try{const r=await fetch('/auctions/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:l.source.lot_url,enrich_krt_documents:true,include_raw:false})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Лот не разобран');state.ingested=d;renderAnalysis(d)}catch(e){status.className='notice warn';status.textContent=String(e.message||e)}finally{b.disabled=false;b.textContent='Разобрать заново'}}
function renderAnalysis(d){const s=d.screening||{},l=d.lot||{},a=$('analysis'),status=$('detailStatus');if(s.krt_auth_required){status.className='notice warn';status.textContent='Часть документации требует входа на ЭТП. Лот сохранён, но DevelopAid не считает закрытые документы отсутствующими.'}else if(s.krt_documents_complete===true){status.className='notice';status.textContent='Официальные документы КРТ разобраны без пропусков, обнаруженных загрузчиком.'}else{status.className='notice';status.textContent='Карточка ЭТП сверена. Для обычной земли следующий слой — кадастр/градпроверка DevelopAid.'}
 const program=l.krt_program||[],obs=l.obligations||[],docs=l.documents||[],px=s.platon_explanation||{};
 a.innerHTML=`<div class="section"><h3>Оценка Платона: ${esc(px.rating||s.rating||'—')}</h3><div class="notice"><b>Почему здесь:</b> ${esc(px.why_here||s.why_here||'—')}</div><div class="items">${(px.concerns||[]).map(x=>`<div class="item"><b>Что настораживает</b>${esc(x)}</div>`).join('')}${(px.verify_before_calculation||[]).map(x=>`<div class="item"><b>Что проверить до расчёта</b>${esc(x)}</div>`).join('')}</div></div><div class="section"><h3>Готовность к DevelopAid</h3><div class="kv"><div>Структура сделки</div><div>${esc(kindLabel(s.legal_structure))}</div><div>Требует условий КРТ</div><div>${s.requires_krt_terms?'да':'нет'}</div><div>Документов</div><div>${docs.length}</div><div>Программа КРТ</div><div>${program.length}</div><div>Обязательств</div><div>${obs.length}</div></div></div>${program.length?`<div class="section"><h3>Программа застройки из документов</h3><div class="items">${program.slice(0,12).map(x=>`<div class="item"><b>${esc(x.category)} · ${esc(x.area_sqm?fmtArea(x.area_sqm):x.quantity?x.quantity+' '+(x.unit||''):'')}</b>${esc(x.title)}<div class="source">${esc(x.provenance?.source_document||'')}</div></div>`).join('')}</div></div>`:''}${obs.length?`<div class="section"><h3>Обязательства инвестора</h3><div class="items">${obs.slice(0,12).map(x=>`<div class="item"><b>${esc(x.category)}${x.quantity?' · '+x.quantity+' '+(x.unit||''):''}</b>${esc(x.title)}<div class="source">${esc(x.provenance?.source_document||'')}</div></div>`).join('')}</div></div>`:''}<div class="actions"><button id="copySeed">Скопировать seed</button><button id="modelBtn" ${s.ready_for_financial_model?'':'disabled'}>Подготовить в DevelopAid</button></div><div id="modelNote" class="notice">Handoff использует штатный project-preset import; отдельный расчётный движок для торгов не создаётся.</div>`;
 $('copySeed').onclick=async()=>{await navigator.clipboard.writeText(JSON.stringify(d.developaid_seed,null,2));$('copySeed').textContent='Скопировано'};$('modelBtn').onclick=()=>{const note=$('modelNote');note.textContent='Project-preset handoff подключается следующим слоем: цена лота → цена входа, КРТ-ТЭП → planning, обязательства → отдельные cost/constraint lines.'}
}
function switchTab(showKrt){['auctionFilters','auctionStats','auctionLayout','coverage'].forEach(id=>$(id).classList.toggle('hidden',showKrt));$('krtPanel').classList.toggle('hidden',!showKrt);$('tabAuctions').classList.toggle('on',!showKrt);$('tabKrt').classList.toggle('on',showKrt);if(showKrt&&!state.krt.length)loadKrt()}
async function loadKrt(){const b=$('krtRefresh');b.disabled=true;b.innerHTML='<span class="spinner"></span>Читаю krt.mos.ru';try{const r=await fetch('/auctions/krt',{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Каталог не получен');state.krt=d.projects||[];populateKrtOkrugs();$('krtEmpty').textContent=state.krt.length?'':'Официальный каталог обновляется в фоне. Первые проекты появятся автоматически.';filterKrt();if(!d.complete&&state.krtPolls<18){state.krtPolls++;clearTimeout(state.krtTimer);state.krtTimer=setTimeout(loadKrt,10000)}else state.krtPolls=0}catch(e){$('krtEmpty').style.display='grid';$('krtEmpty').textContent=String(e.message||e)}finally{b.disabled=false;b.textContent='Обновить каталог'}}
function updateKrtOkrugLabel(){const values=KRT_OKRUGS.filter(x=>state.krtOkrugs.has(x)),button=$('krtOkrugToggle');button.textContent=!values.length?'Все округа':values.length<=3?values.join(', '):`${values.slice(0,2).join(', ')} +${values.length-2}`;button.title=values.length?values.join(', '):'Все округа';$('krtOkrugClear').disabled=!values.length}
function populateKrtOkrugs(){const values=KRT_OKRUGS,options=$('krtOkrugOptions');options.innerHTML='';values.forEach(value=>{const label=document.createElement('label'),input=document.createElement('input'),text=document.createElement('span');label.className='multi-option';input.type='checkbox';input.value=value;input.checked=state.krtOkrugs.has(value);text.textContent=value;input.onchange=()=>{input.checked?state.krtOkrugs.add(value):state.krtOkrugs.delete(value);updateKrtOkrugLabel();filterKrt()};label.append(input,text);options.appendChild(label)});updateKrtOkrugLabel()}
function closeKrtOkrugs(){const menu=$('krtOkrugMenu'),button=$('krtOkrugToggle');menu.classList.add('hidden');button.setAttribute('aria-expanded','false')}
function krtFit(x){const profile=$('krtProfile').value,total=Number(x.total_gfa_sqm)||0,housing=Number(x.housing_gfa_sqm)||0,business=Number(x.business_gfa_sqm)||0,area=Number(x.area_ha)||0,jobs=Number(x.jobs)||0,active=x.status==='В реализации';let score=0,reasons=[],checks=[];const complete=[x.okrug,x.district,x.status,total,area].filter(Boolean).length;score+=complete*3;if(complete>=4)reasons.push('основные ТЭП заполнены');else checks.push('неполные исходные ТЭП');if(profile==='housing_ready'){score+=active?30:12;reasons.push(active?'проект уже в реализации':'проект пока планируемый');const share=total?housing/total:0;score+=Math.min(35,share*45);if(housing>0)reasons.push(`жильё ${Math.round(share*100)}% общего объёма`);else checks.push('жилой объём не указан');score+=housing>=200000?20:housing>=50000?14:housing>0?7:0}else if(profile==='housing_pipeline'){score+=active?20:18;const share=total?housing/total:0;score+=Math.min(42,share*52);if(housing>0)reasons.push(`жилищный потенциал ${fmtArea(housing)}`);else checks.push('жилой объём не указан');score+=housing>=300000?22:housing>=100000?16:housing>0?8:0}else{score+=active?22:15;const share=total?business/total:0;score+=Math.min(42,share*52);if(business>0)reasons.push(`деловой объём ${fmtArea(business)}`);else checks.push('деловой объём не указан');score+=jobs>=3000?21:jobs>=500?14:jobs>0?7:0}if(area>0&&area<=40){score+=5;reasons.push('управляемый масштаб территории')}else if(area>40)checks.push('крупная территория требует поэтапной проверки');score=Math.max(0,Math.min(100,Math.round(score)));const tone=score>=75?'ok':score>=50?'warn':'bad',label=score>=75?'Высокое':score>=50?'Среднее':'Низкое';return{score,tone,label,reasons:reasons.slice(0,4),checks:checks.slice(0,3)}}
function filterKrt(){const q=$('krtSearch').value.trim().toLowerCase(),status=$('krtStatus').value,purpose=$('krtPurpose').value;state.krtFiltered=state.krt.filter(x=>(!q||[x.name,x.district,x.okrug].join(' ').toLowerCase().includes(q))&&(!state.krtOkrugs.size||state.krtOkrugs.has(x.okrug))&&(!status||x.status===status)&&(!purpose||Number(x[purpose])>0)).sort((a,b)=>krtFit(b).score-krtFit(a).score||String(a.name).localeCompare(String(b.name),'ru'));renderKrt()}
function sumKrt(rows,key,d){const n=rows.reduce((s,x)=>s+(Number(x[key])||0),0);return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(n)}
function renderKrt(){const a=state.krtFiltered,body=$('krtRows');body.innerHTML='';$('krtEmpty').style.display=a.length?'none':'grid';$('krtCount').textContent=a.length;$('krtArea').textContent=sumKrt(a,'area_ha',1);$('krtHousing').textContent=sumKrt(a,'housing_gfa_sqm',0);$('krtGfa').textContent=sumKrt(a,'total_gfa_sqm',0);a.forEach(x=>{const fit=krtFit(x),model=state.krtModels[x.slug],light=model?.traffic_light,tr=document.createElement('tr'),deep=light?`Модель · ${esc(light.label)}`:`${fit.score} · ${fit.label}`,tone=light?.tone||fit.tone,title=light?'Предварительный прогон финансовой модели':'Предварительно, до анализа рынка';tr.innerHTML=`<td><div class="lotname">${esc(x.name)}</div><div class="source">${esc([x.okrug,x.district].filter(Boolean).join(' · '))}</div></td><td><span class="fit ${tone}" title="${title}"><span class="light"></span>${deep}</span></td><td class="money">${krtRankCell(x.slug)}</td><td><span class="tag ${x.status==='В реализации'?'ok':'warn'}">${esc(x.status||'—')}</span></td><td>${x.area_ha?esc(x.area_ha+' га'):'—'}</td><td>${fmtArea(x.total_gfa_sqm)}</td><td>${fmtArea(x.housing_gfa_sqm)}</td><td>${esc(x.jobs??'—')}</td>`;tr.onclick=()=>selectKrt(x);body.appendChild(tr)})}
// Балл — потолок цены входа на метр продаваемой (решение владельца,
// 23.08.2026). На метр, а не в абсолюте: потолок в рублях выгоден крупным
// площадкам просто по размеру. Пустая ячейка значит «не посчитали», и это не
// то же самое, что «не выдерживает», — поэтому у неё своя подпись.
// Картинка участка. Границ КРТ каталог krt.mos.ru не публикует и сам это
// объявляет (`geometry_status: not_published_in_catalogue`) — есть только
// геокодированная точка и площадь в гектарах. Поэтому рисуем карту улиц вокруг
// точки с меткой и масштабной линейкой, и НЕ рисуем фигуру «примерной
// площади»: квадрат или круг на карте читается как контур, и по нему начнут
// мерить пятно застройки. Подложку отдаёт движковый `/land/basemap` тем же
// меркаторным bbox, в котором мы ставим метку, — совмещать в браузере нечего.
// Кадастровый слой `/land/map-image` для этого масштаба не годится: он верен
// на двухстах метрах карточки участка, а на километре даёт клубок границ ЕГРН
// без улиц и названий.
const MERC=20037508.342789244;
const mercX=lon=>lon*MERC/180;
const mercY=lat=>Math.log(Math.tan((90+lat)*Math.PI/360))*MERC/Math.PI;
// Карта живёт в карточке и появляется сразу при выборе территории: ради одной
// картинки гонять весь отчёт рынка незачем. Точку отдаёт `/auctions/krt/{slug}/point`
// — тот же геокодер движка и тот же кэш.
async function loadKrtPoint(x){
 const box=document.getElementById('krtMapBox');
 if(!box)return;
 try{
  const r=await fetch('/auctions/krt/'+encodeURIComponent(x.slug)+'/point',{cache:'no-store'});
  const d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Точка не определена');
  box.innerHTML=krtSiteMap(d,d.area_ha!=null?d.area_ha:x.area_ha);
 }catch(e){
  box.innerHTML='<div class="section"><h3>Участок на карте</h3>'
   +'<div class="notice warn">'+esc(e.message||e)+'</div></div>';
 }
}
function krtSiteMap(subject,areaHa){
 const lat=Number(subject&&subject.latitude), lon=Number(subject&&subject.longitude);
 if(!Number.isFinite(lat)||!Number.isFinite(lon))
  return '<div class="notice warn">Точка участка не определена — карта не построена.</div>';
 // Кадр по площади: сторона квадрата такой же площади, с запасом в 2,5 раза,
 // чтобы было видно окружение. Меньше 600 м не берём — на 300 м улиц не видно.
 const side=Math.max(600, Math.sqrt(Math.max(1,Number(areaHa)||1)*10000)*2.5);
 const half=side/2, cx=mercX(lon), cy=mercY(lat);
 // Меркатор растягивает метры к северу — поправка по широте, иначе кадр
 // окажется у́же заявленного и масштабная линейка соврёт.
 const k=1/Math.cos(lat*Math.PI/180), hx=half*k, hy=half*k;
 const bbox=[cx-hx,cy-hy,cx+hx,cy+hy].join(',');
 const src='/land/basemap?'+new URLSearchParams({bbox:bbox,width:'900'});
 const scale=Math.round(side/4/50)*50||100;
 const scalePct=(scale/side*100).toFixed(1);
 const precision=String((subject&&subject.precision)||'');
 const rough=precision&&precision!=='street'&&precision!=='house';
 return `<div class="section"><h3>Участок на карте</h3>
  <div style="position:relative;border:1px solid #e3e3e0;overflow:hidden">
   <img src="${src}" alt="Карта окрестностей участка" style="display:block;width:100%"
        onerror="this.parentNode.innerHTML='<div class=\'empty\' style=\'padding:26px\'>Подложка карты недоступна</div>'">
   <span style="position:absolute;left:50%;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;
                border:3px solid #b3261e;border-radius:50%;background:rgba(255,255,255,.65)"></span>
   <div style="position:absolute;left:12px;bottom:12px;background:rgba(255,255,255,.9);
               padding:4px 8px;font-size:11px;display:flex;align-items:center;gap:7px">
    <span style="display:block;height:3px;background:#222;width:${scalePct}%;min-width:34px"></span>
    <span>${scale} м</span>
   </div>
  </div>
  <div class="source" style="margin-top:7px">Метка — геокодированный центр территории, кадр ${Math.round(side)} м.
   Официальный полигон границ КРТ каталогом не публикуется, поэтому контур не показан:
   по нему стали бы мерить пятно застройки.${rough?' Точность геокодера ниже уровня улицы — положение метки приблизительное.':''}</div>
 </div>`;
}
function krtRankCell(slug){
 const row=state.krtRank[slug];
 if(!row)return '<span class="source">не оценён</span>';
 if(!row.available)return `<span class="source" title="${esc(row.reason||'')}">не посчитан</span>`;
 const per=row.entry_capacity_rub_per_sqm;
 if(per===null||per===undefined)
  return `<span class="source" title="${esc(row.entry_capacity_reason||'')}">потолок не подобран</span>`;
 const total=row.entry_capacity_mln!=null?` · ${fmtMln(row.entry_capacity_mln)}`:'';
 return `<b>${new Intl.NumberFormat('ru-RU').format(per)}</b><span class="source">${esc(total)}</span>`;
}
// Ход показывается тем, что есть: сколько посчитано из скольких, что считается
// сейчас, сколько секунд идёт. Ожидание без признака работы читается как
// внезапность, а прогон по каталогу идёт минутами.
function renderKrtRankStatus(){
 const box=$('krtRankStatus'),p=state.krtRankProgress;
 if(!box)return;
 if(!p||(!p.running&&!p.total&&!p.updated_at)){box.style.display='none';return}
 box.style.display='';
 if(p.running){
  const left=p.current?` · сейчас: ${esc(p.current)}`:'';
  const failed=p.failed?` · не посчитано: ${p.failed}`:'';
  box.className='notice';
  const how=p.scheduled?'по расписанию':'по вашей кнопке';
  box.innerHTML=`<span class="spinner"></span>Считаю модель ${how}: ${p.done} из ${p.total} · ${p.elapsed_seconds||0} с${left}${failed}`;
  return;
 }
 const when=p.updated_at?new Date(p.updated_at*1000).toLocaleString('ru-RU'):'';
 const failed=p.failed?` Не посчитано: ${p.failed}.`:'';
 box.className=p.stale?'notice warn':'notice';
 // Счёт идёт сам раз в неделю — это надо сказать, иначе кнопку жмут каждый
 // раз и ждут минуты на пустом месте.
 box.innerHTML=`Оценка модели по каталогу от ${esc(when)}.${failed}`
  +' Каталог обновляется и пересчитывается сам раз в неделю; кнопка нужна, '
  +'только если хотите пересчитать отобранное прямо сейчас.'
  +(p.stale?' Данные старше суток.':'');
}
async function loadKrtRanking(){
 try{
  const r=await fetch('/auctions/krt/ranking',{cache:'no-store'}),d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Рейтинг не получен');
  state.krtRank={};(d.rows||[]).forEach(row=>{state.krtRank[row.slug]=row;
   if(row.available&&row.traffic_light)state.krtModels[row.slug]={traffic_light:row.traffic_light}});
  state.krtRankProgress=d.progress||null;
  renderKrtRankStatus();renderKrt();
  clearTimeout(state.krtRankTimer);
  if(d.progress&&d.progress.running)state.krtRankTimer=setTimeout(loadKrtRanking,3000);
 }catch(e){const box=$('krtRankStatus');if(box){box.style.display='';box.className='notice warn';box.textContent=String(e.message||e)}}
}
async function startKrtRanking(){
 const b=$('krtRankBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span>Запускаю';
 try{
  // Считаем то, что осталось после фильтра: смотрят перспективные округа и
  // нужный статус, а прогон по всему каталогу — это минуты чужой работы.
  const slugs=(state.krtFiltered||[]).map(v=>v.slug).filter(Boolean);
  const r=await fetch('/auctions/krt/ranking/refresh',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({slugs:slugs})});
  const d=await r.json();
  if(!r.ok){
   if(r.status===401)throw new Error('Нужен вход в кабинет рынка: откройте /cabinet в соседней вкладке и войдите по ключу.');
   throw new Error(d.detail||'Прогон не запущен');
  }
  state.krtRankProgress=d.progress||null;renderKrtRankStatus();loadKrtRanking();
 }catch(e){const box=$('krtRankStatus');box.style.display='';box.className='notice warn';box.textContent=String(e.message||e)}
 finally{b.disabled=false;b.textContent='Оценить все КРТ моделью'}
}
function selectKrt(x){state.selectedKrt=x;const fit=krtFit(x),cached=state.krtModels[x.slug];$('krtSide').innerHTML=`<h2>${esc(x.name)}</h2><div class="sub">krt.mos.ru · ${esc([x.okrug,x.district].filter(Boolean).join(' · '))}</div><div class="notice"><div class="fit ${fit.tone}"><span class="light"></span>Предварительная оценка Платона: ${fit.score}/100 · ${fit.label}</div><div class="source">По официальным ТЭП, до проверки окружения и экономики.</div></div><div class="items">${fit.reasons.map(x=>`<div class="item"><b>Соответствует запросу</b>${esc(x)}</div>`).join('')}${fit.checks.map(x=>`<div class="item"><b>Нужно проверить</b>${esc(x)}</div>`).join('')}</div><div class="kv"><div>Статус</div><div>${esc(x.status||'—')}</div><div>Площадь</div><div>${esc(x.area_ha?x.area_ha+' га':'—')}</div><div>Всего построить</div><div>${fmtArea(x.total_gfa_sqm)}</div><div>Жильё</div><div>${fmtArea(x.housing_gfa_sqm)}</div><div>Нежилое</div><div>${fmtArea(x.nonresidential_gfa_sqm)}</div><div>Общественно-деловое</div><div>${fmtArea(x.business_gfa_sqm)}</div><div>Рабочие места</div><div>${esc(x.jobs??'—')}</div></div><div class="notice warn">Официальный полигон границ пока не получен. Анализ использует геокодированную точку и помечает это приближение.</div><div class="actions"><button class="primary" id="krtHandoff">Передать в DevelopAid</button><button id="krtPlato">Рекомендация Платона</button><button id="krtMarket">Пересчитать сейчас</button><button id="krtShare">Поделиться</button><button id="krtSource">Открыть krt.mos.ru</button></div><div id="krtShareNote" class="notice" style="display:none"></div><div id="krtMapBox"><div class="notice">Строю карту участка…</div></div><div id="krtMarketResult">${cached?renderKrtModel(cached):''}</div>`;$('krtMarket').onclick=()=>loadKrtMarket(x);$('krtSource').onclick=()=>window.open(x.url,'_blank','noopener');
 $('krtShare').onclick=()=>shareKrt(x);
 $('krtHandoff').onclick=()=>handoffKrt(x);
 $('krtPlato').onclick=()=>askPlatoAboutKrt(x);
 // На узком экране колонка карточки уходит ПОД таблицу, и нажатие на строку
 // выглядит как «ничего не произошло»: карточка открылась там, куда не смотрят
 // (телефон владельца, 23.08.2026). Прокручиваем к ней.
 if(window.matchMedia('(max-width:950px)').matches){
  try{$('krtSide').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){$('krtSide').scrollIntoView()}
 }
 loadKrtPoint(x);
 // Отчёт уже посчитан — его показывают, а не считают заново. Прогон по
 // каталогу сходил и к рынку, и к движку; заставлять человека ждать те же
 // минуты второй раз значит выбрасывать сделанную работу.
 loadKrtReport(x);
}

// Готовый отчёт площадки. 404 — это «ещё не считали», а не поломка: так и
// говорится, и рядом остаётся кнопка пересчёта.
async function loadKrtReport(x){
 const out=$('krtMarketResult');
 if(state.krtReports[x.slug]){renderKrtReport(x,state.krtReports[x.slug],out);return}
 out.innerHTML='<div class="notice"><span class="spinner"></span>Открываю посчитанный отчёт…</div>';
 try{
  const r=await fetch('/auctions/krt/'+encodeURIComponent(x.slug)+'/report',{cache:'no-store'});
  const d=await r.json();
  if(!r.ok){
   if(r.status===401)throw new Error('Нужен вход в кабинет рынка: откройте /cabinet в соседней вкладке и войдите по ключу.');
   if(r.status===404){out.innerHTML=`<div class="notice">${esc(d.detail||'Отчёт ещё не посчитан.')}</div>`;return}
   throw new Error(d.detail||'Отчёт не получен');
  }
  state.krtReports[x.slug]=d;
  if(d.screening&&d.screening.available){state.krtModels[x.slug]=d.screening;renderKrt()}
  renderKrtReport(x,d,out);
 }catch(e){out.innerHTML=`<div class="notice warn">${esc(e.message||e)}</div>`}
}

function renderKrtReport(x,d,out){
 const when=d.computed_at?new Date(d.computed_at*1000).toLocaleString('ru-RU'):'';
 const plato=d.plato&&d.plato.text
  ? `<div class="section"><h3>Рекомендация Платона</h3><div class="notice"><div style="white-space:pre-wrap">${esc(d.plato.text)}</div><div class="source" style="margin-top:7px">Спрошено ${d.plato.asked_at?new Date(d.plato.asked_at*1000).toLocaleString('ru-RU'):''} по маркетингу и по модели сразу.</div></div></div>`
  : '<div class="section"><h3>Рекомендация Платона</h3><div class="notice">Не спрошена. Кнопка «Рекомендация Платона» задаёт ему вопрос по этим же числам — маркетингу и модели вместе.</div></div>';
 const head=`<div class="notice"><b>Отчёт посчитан ${esc(when)}</b><div class="source" style="margin-top:5px">Числа ниже взяты из этого прогона. «Пересчитать сейчас» повторит его с сегодняшним рынком.</div></div>`;
 out.innerHTML=head+plato+renderKrtModel(d.screening);
 if(d.market)renderKrtMarketBlocks(d.market,out);
}

// Передача в DevelopAid: те же вводные, которыми посчитан отчёт. Второй сборки
// модели здесь нет — иначе карточка и калькулятор однажды разошлись бы.
async function handoffKrt(x){
 const b=$('krtHandoff'),note=$('krtShareNote');
 const say=t=>{if(note){note.textContent=t;note.style.display=''}};
 b.disabled=true;b.innerHTML='<span class="spinner"></span>Передаю';
 try{
  const r=await fetch('/auctions/krt/'+encodeURIComponent(x.slug)+'/handoff',{cache:'no-store'});
  const d=await r.json();
  if(!r.ok){
   if(r.status===401)throw new Error('Нужен вход в кабинет рынка: откройте /cabinet в соседней вкладке и войдите по ключу.');
   throw new Error(d.detail||'Передавать нечего');
  }
  sessionStorage.setItem('developaid.auction.pending.v1',JSON.stringify({
   krt_model:{inputs:d.inputs,tep:d.tep,phasing:d.phasing},
   krt_name:d.name||x.name||'',
   krt_slug:x.slug
  }));
  location.href='/?krt_import=1';
 }catch(e){say(String(e.message||e))}
 finally{b.disabled=false;b.textContent='Передать в DevelopAid'}
}

async function askPlatoAboutKrt(x){
 const b=$('krtPlato'),out=$('krtMarketResult');
 b.disabled=true;b.innerHTML='<span class="spinner"></span>Спрашиваю';
 try{
  const r=await fetch('/auctions/krt/'+encodeURIComponent(x.slug)+'/plato',{method:'POST'});
  const d=await r.json();
  if(!r.ok){
   if(r.status===401)throw new Error('Нужен вход в кабинет рынка: откройте /cabinet в соседней вкладке и войдите по ключу.');
   throw new Error(d.detail||'Платон не ответил');
  }
  const stored=state.krtReports[x.slug];
  if(stored){stored.plato={text:d.text,asked_at:d.asked_at};renderKrtReport(x,stored,out)}
 }catch(e){
  const box=$('krtShareNote');
  if(box){box.textContent=String(e.message||e);box.style.display=''}
 }finally{b.disabled=false;b.textContent='Рекомендация Платона'}
}

// Поделиться территорией: ссылка открывает ту же карточку с теми же выводами.
// Отдаём не «посмотри КРТ такой-то», а сам разбор — балл, светофор, класс от
// маркетинга, потолок входа и чего в нём не учтено: без этого получатель видит
// цифру без основания и достраивает основание сам.
function krtShareText(x){
 const r=state.krtRank[x.slug]||{}, m=state.krtModels[x.slug]||{};
 const light=r.traffic_light||m.traffic_light||{};
 const lines=['КРТ · '+(x.name||''), [x.okrug,x.district].filter(Boolean).join(' · ')];
 if(x.area_ha)lines.push('Площадь: '+x.area_ha+' га');
 if(x.total_gfa_sqm)lines.push('Объём: '+fmtArea(x.total_gfa_sqm)+' всего, '+fmtArea(x.housing_gfa_sqm)+' жильё');
 if(light.label)lines.push('Модель DevelopAid: '+light.label);
 if(r.entry_capacity_rub_per_sqm!=null)
  lines.push('Потолок цены входа: '+new Intl.NumberFormat('ru-RU').format(r.entry_capacity_rub_per_sqm)
   +' ₽/м² продаваемой'+(r.entry_capacity_mln!=null?' · '+fmtMln(r.entry_capacity_mln):''));
 if(r.project_llcr_x!=null)lines.push('LLCR проекта: '+Number(r.project_llcr_x).toFixed(2)+'x'
   +(r.weakest_phase_llcr_x!=null?' · слабейшая очередь '+Number(r.weakest_phase_llcr_x).toFixed(2)+'x':''));
 if(r.margin_pct!=null)lines.push('Маржа до неизвестных обязательств: '+Number(r.margin_pct).toFixed(1)+'%');
 if(r.segment)lines.push('Класс от маркетинга: '+r.segment
   +(r.start_price_rub_sqm?' · старт '+new Intl.NumberFormat('ru-RU').format(r.start_price_rub_sqm)+' ₽/м²':''));
 if(r.available===false&&r.reason)lines.push('Не посчитано: '+r.reason);
 lines.push('');
 lines.push('Чего нет в оценке: цена аукциона (в каталоге krt.mos.ru её нет), '
  +'обязательства КРТ сверх опубликованных, границы территории.');
 lines.push('Оценка предварительная, до проверки документов. DevelopAid.');
 lines.push(location.origin+'/auctions#krt='+encodeURIComponent(x.slug));
 return lines.filter(v=>v!==undefined&&v!==null).join('\n');
}
async function shareKrt(x){
 const text=krtShareText(x), note=$('krtShareNote');
 const say=t=>{if(note){note.textContent=t;note.style.display=''}};
 try{
  if(navigator.share){await navigator.share({title:'КРТ · '+(x.name||''),text:text});return}
  await navigator.clipboard.writeText(text);
  say('Разбор скопирован — вставьте в переписку.');
 }catch(e){
  // Отказ бывает и намеренным: человек закрыл окно «Поделиться».
  if(e&&e.name==='AbortError')return;
  say('Скопировать не удалось: '+(e&&e.message?e.message:e));
 }
}
async function loadKrtMarket(x){const b=$('krtMarket'),out=$('krtMarketResult');b.disabled=true;b.innerHTML='<span class="spinner"></span>Рынок → модель';out.innerHTML='<div class="notice">Определяю продукт и цену, затем запускаю финансовый движок и автоматические очереди…</div>';try{const r=await fetch('/auctions/krt/'+encodeURIComponent(x.slug)+'/market',{cache:'no-store'}),d=await r.json();if(!r.ok){if(r.status===401)throw new Error('Нужен вход в кабинет рынка: откройте /cabinet в соседней вкладке и войдите по ключу.');throw new Error(d.detail||'Маркетинг не получен')}if(d.model_screening?.available){state.krtModels[x.slug]=d.model_screening;renderKrt()}delete state.krtReports[x.slug];loadKrtRanking();renderKrtMarket(d,out)}catch(e){out.innerHTML=`<div class="notice warn">${esc(e.message||e)}</div>`}finally{b.disabled=false;b.textContent='Обновить маркетинг и модель'}}
function renderKrtModel(m){
 if(!m?.available)return `<div class="section"><h3>Предварительный прогон модели</h3><div class="notice warn">${esc(m?.reason||'Модель не рассчитана')}</div></div>`;
 const t=m.traffic_light||{},market=m.market||{},ph=m.phasing||{},abs=m.absorption||{},k=m.metrics||{},cap=m.entry_capacity,phases=ph.phases||[];
 const pace=abs.available?`${new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(abs.market_units_per_month)} ДДУ/мес. · ${esc(abs.sellout_months_per_phase)} мес. на очередь`:'не определён';
 return `<div class="section"><h3>Предварительный прогон модели</h3><div class="notice"><div class="fit ${esc(t.tone||'warn')}"><span class="light"></span>${esc(m.headline||t.label||'Рассчитано')}</div><div style="margin-top:6px">${esc(m.text||'')}</div><div class="source" style="margin-top:7px">${esc(m.criterion||'')}</div></div><div class="kv"><div>Класс из маркетинга</div><div>${esc(market.recommended_segment||'—')}</div><div>Стартовая цена</div><div class="money">${market.start_price_rub_sqm?new Intl.NumberFormat('ru-RU').format(market.start_price_rub_sqm)+' ₽/м²':'—'}</div><div>Темп / реализация</div><div>${pace}</div><div>Очереди</div><div>${esc(ph.count||1)} · автоматически, цель ${fmtArea(ph.target_saleable_sqm)}</div><div>Продаваемая площадь</div><div>${fmtArea(ph.saleable_sqm)}</div><div>LLCR проекта</div><div>${Number.isFinite(Number(k.project_llcr_x))?Number(k.project_llcr_x).toFixed(2)+'x':'—'}</div><div>LLCR слабейшей очереди</div><div>${Number.isFinite(Number(k.weakest_phase_llcr_x))?Number(k.weakest_phase_llcr_x).toFixed(2)+'x':'—'}</div><div>Маржа до неизвестных обязательств</div><div>${Number.isFinite(Number(k.margin_pct))?Number(k.margin_pct).toFixed(1)+'%':'—'}</div><div>Чистая прибыль до цены входа</div><div>${fmtMln(k.net_profit_mln)}</div><div>Резерв при LLCR 1,20x</div><div>${cap?.available?fmtMln(cap.amount_mln):'—'}</div></div>${cap?.available?`<div class="notice warn">${esc(cap.meaning)}</div>`:''}${phases.length>1?`<div class="items">${phases.map(p=>`<div class="item"><b>${esc(p.name)} · LLCR ${Number(p.llcr_x||0).toFixed(2)}x</b>${fmtArea(p.saleable_sqm)} продаваемых · маржа ${Number(p.margin_pct||0).toFixed(1)}%</div>`).join('')}</div>`:''}<div class="section"><h3>Что поставлено в модель</h3><div class="items">${(m.assumptions||[]).map(x=>`<div class="item">${esc(x)}</div>`).join('')}</div></div><div class="section"><h3>Что пока не учтено</h3><div class="items">${(m.exclusions||[]).map(x=>`<div class="item"><b>Нужно добавить</b>${esc(x)}</div>`).join('')}</div></div></div>`
}
function renderKrtMarket(d,out){
 const peers=d.peers||[],hint=d.price_hint||{},c=d.comparison||{},analysis=d.analysis||{},verdict=analysis.site||analysis.overall||{};
 const price=verdict.price_per_sqm||hint.price_per_sqm;
 const headline=verdict.headline||(price?'Рыночный ориентир найден':'Вывод по продукту пока не сложился');
 const summary=verdict.text||(peers.length?'Платон нашёл соседние проекты, но данных об их классе недостаточно для уверенного ответа, что именно здесь строить.':'В выбранном радиусе недостаточно сопоставимых проектов для вывода о продукте и цене.');
 const entry=hint.entry_per_sqm?`Для старта продаж ориентир входной цены — ${new Intl.NumberFormat('ru-RU').format(hint.entry_per_sqm)} ₽/м²; средняя цена проекта формируется позднее по очередям и квартирографии.`:'';
 out.innerHTML=`<div class="section"><h3>Короткий вывод Платона</h3><div class="notice"><b>${esc(headline)}</b><div style="margin-top:5px">${esc(summary)}</div>${entry?`<div class="source" style="margin-top:7px">${esc(entry)}</div>`:''}</div></div>${renderKrtModel(d.model_screening)}${krtMarketBlocks(d)}`
}
// Рынок рядом и список соседей рисуются одним куском и для свежего запроса, и
// для сохранённого отчёта: две разметки на одни данные разошлись бы, и человек
// увидел бы про одну площадку два разных списка соседей.
function krtMarketBlocks(d){
 const peers=d.peers||[],hint=d.price_hint||{},c=d.comparison||{},analysis=d.analysis||{},verdict=analysis.site||analysis.overall||{};
 const price=verdict.price_per_sqm||hint.price_per_sqm;
 return `<div class="section"><h3>Рынок рядом</h3><div class="kv"><div>Радиус</div><div>${esc(c.radius_km||3)} км</div><div>Найдено проектов</div><div>${esc(c.found??peers.length)}</div><div>Использовано</div><div>${esc(c.used??peers.length)}</div><div>Ориентир цены</div><div class="money">${price?new Intl.NumberFormat('ru-RU').format(price)+' ₽/м²':'—'}</div></div></div><div class="section"><h3>Реализуемые проекты</h3><div class="items">${peers.length?peers.map(p=>`<div class="item"><b>${esc(p.name)} · ${esc(p.distance_km??'—')} км</b><div>${p.price_per_sqm?new Intl.NumberFormat('ru-RU').format(p.price_per_sqm)+' ₽/м²':'цена не опубликована'}${p.price_per_sqm_min?' · от '+new Intl.NumberFormat('ru-RU').format(p.price_per_sqm_min):''}</div><div class="source">${esc([p.developer,p.segment,p.living_area?'объём '+fmtArea(p.living_area):null,p.remaining_units?'остаток '+p.remaining_units+' лотов':null,p.units_per_month?'темп '+p.units_per_month+' ДДУ/мес':null].filter(Boolean).join(' · '))}</div></div>`).join(''):'<div class="notice">Сопоставимых проектов в выбранном радиусе не найдено.</div>'}</div></div>`;
}
function renderKrtMarketBlocks(report,out){out.insertAdjacentHTML('beforeend',krtMarketBlocks(report))}
$('tabAuctions').onclick=()=>switchTab(false);$('tabKrt').onclick=()=>switchTab(true);$('krtRefresh').onclick=loadKrt;$('krtRankBtn').onclick=startKrtRanking;$('krtSearch').oninput=filterKrt;$('krtStatus').onchange=filterKrt;$('krtPurpose').onchange=filterKrt;$('krtProfile').onchange=()=>{filterKrt();if(state.selectedKrt)selectKrt(state.selectedKrt)};
$('krtOkrugToggle').onclick=e=>{e.stopPropagation();const menu=$('krtOkrugMenu'),open=menu.classList.contains('hidden');menu.classList.toggle('hidden',!open);$('krtOkrugToggle').setAttribute('aria-expanded',String(open))};$('krtOkrugMenu').onclick=e=>e.stopPropagation();$('krtOkrugClear').onclick=()=>{state.krtOkrugs.clear();$('krtOkrugOptions').querySelectorAll('input').forEach(x=>x.checked=false);updateKrtOkrugLabel();filterKrt()};document.addEventListener('click',closeKrtOkrugs);document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeKrtOkrugs();$('krtOkrugToggle').focus()}});
loadKrtRanking();
// Ссылка из «Поделиться» открывает ту же территорию: получатель попадает на
// разбор, а не на общий список, где ещё надо искать.
(function openSharedKrt(){
 const m=/[#&]krt=([^&]+)/.exec(location.hash||'');
 if(!m)return;
 const slug=decodeURIComponent(m[1]);
 const tries=[0,1200,3000,6000,10000];
 tries.forEach(delay=>setTimeout(()=>{
  if(state.selectedKrt&&state.selectedKrt.slug===slug)return;
  const found=(state.krt||[]).find(v=>v.slug===slug);
  if(found){switchTab(true);selectKrt(found)}
 },delay));
})();
$('refresh').onclick=discover;$('search').oninput=filter;$('kind').onchange=filter;$('source').onchange=discover;$('noise').onchange=discover;
</script>
</body></html>'''


def auctions_page() -> str:
    return AUCTIONS_PAGE
