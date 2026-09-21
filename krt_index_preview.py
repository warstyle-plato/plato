"""Experimental KRT index. Isolated route: /krt-preview."""
import json
import urllib.request
import urllib.parse
from fastapi.responses import HTMLResponse, JSONResponse

PAGE = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ — DevelopAid preview</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f2f2ef;color:#171717;font:14px Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}header{height:64px;background:#fff;border-bottom:1px solid #e6eaf0;display:flex;align-items:center;padding:0 28px;gap:34px;position:sticky;top:0;z-index:5}.brand{font-size:22px;font-weight:800}.nav{display:flex;gap:25px;color:#536077}.nav b{color:#172033}.wrap{max-width:1480px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;align-items:end}.hero h1{font-size:30px;margin:0 0 6px}.muted{color:#7b8799}.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:24px 0}.stat{background:#fff;border:1px solid #e6eaf0;border-radius:0;padding:16px}.stat strong{display:block;font-size:26px;margin-top:8px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.tab{border:1px solid #e1e6ed;background:#fff;border-radius:0;padding:10px 14px;cursor:pointer}.tab.active{background:#111;color:#fff;border-color:#111}.grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(360px,.85fr);gap:16px}.list{display:flex;flex-direction:column;gap:10px}.card{background:#fff;border:1px solid #e3e8ef;border-radius:0;padding:14px;display:grid;grid-template-columns:150px 1fr auto;gap:16px;align-items:stretch;cursor:pointer}.scheme{border-radius:0;background:#edf1f5;position:relative;overflow:hidden;min-height:118px}.scheme:before{content:"";position:absolute;inset:16px 25px;border:3px solid #6b7890;border-radius:44% 56% 52% 48%;transform:rotate(-8deg);background:rgba(255,255,255,.45)}.scheme:after{content:"схема территории";position:absolute;left:10px;bottom:8px;font-size:11px;color:#718096}.title{font-size:18px;font-weight:750;margin:3px 0 5px}.badge{display:inline-block;border-radius:7px;padding:5px 8px;font-size:12px;font-weight:700;background:#eef1f5}.badge.tender{background:#ffe6e8;color:#c82b3b}.badge.decision{background:#e8f3ff;color:#1766b1}.badge.new{background:#e8f7ef;color:#147a4b}.badge.done{background:#fff1d9;color:#94610b}.metrics{display:flex;gap:24px;margin-top:18px;flex-wrap:wrap}.metric b{display:block;font-size:15px}.metric small{color:#8994a4}.side{position:sticky;top:80px;align-self:start}.map{height:480px;background:linear-gradient(135deg,#eef3ed,#e7eef5);border:1px solid #e0e6ed;border-radius:0;position:relative;overflow:hidden}.map:before{content:"Москва · карта площадок";position:absolute;left:18px;top:16px;font-weight:750}.road{position:absolute;height:2px;background:#cbd5df;transform-origin:left center}.dot{position:absolute;width:14px;height:14px;border:3px solid white;border-radius:50%;background:#23324c;box-shadow:0 1px 4px #778}.filters{background:#fff;border:1px solid #e3e8ef;border-radius:0;padding:16px;margin-top:10px}.filters input,.filters select{width:100%;padding:10px;border:1px solid #dce2e9;border-radius:9px;margin-top:8px;background:#fff}.empty,.loading{background:#fff;border:1px solid #e3e8ef;border-radius:0;padding:28px;color:#6d7889}.deadline{font-weight:750;color:#cf3043;white-space:nowrap}.arrow{align-self:center;font-size:24px;color:#7d8898}@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.side{position:static}.map{height:300px}.card{grid-template-columns:105px 1fr}.card>.arrow{display:none}.nav{display:none}}</style></head>
<body><header><div class="brand">DevelopAid</div><div class="nav"><span>Аналитика</span><b>КРТ</b><span>Торги</span><span>Участки</span><span>Проекты</span><span>Рынок</span></div></header>
<main class="wrap"><div class="hero"><div><h1>Площадки КРТ</h1><div class="muted">Единый реестр жизненного цикла: от появления площадки до реализации</div></div><div class="muted">Тестовая версия · данные текущего каталога</div></div>
<div class="stats" id="stats"></div><div class="tabs" id="tabs"></div>
<div class="grid"><section class="list" id="list"><div class="loading">Загружаю текущий каталог КРТ…</div></section><aside class="side"><div class="map" id="map"></div><div class="filters"><b>Фильтры</b><input id="q" placeholder="Адрес, район, название…"><select id="okrug"><option value="">Все округа</option></select></div></aside></div></main>
<script>
let rows=[],active='all';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>{let n=Number(v);return Number.isFinite(n)?n:0};
function status(r){let s=String(r.status||r.lifecycle_status||'').toLowerCase();let t=r.tender||r.auction||r.tender_url||r.auction_url||r.deadline;
 if(/реализ|строит/.test(s))return'realization'; if(/заверш|состоя|прием.*заверш/.test(s))return'done'; if(t||/торг|заяв/.test(s))return'tender'; if(/решен/.test(s)||r.draft_decision_url)return'decision'; if(r.is_new||r.new)return'new'; return'other'}
const meta={all:['Все площадки',''],tender:['Торги идут','tender'],new:['Новые','new'],decision:['Решение','decision'],done:['Приём завершён','done'],realization:['Реализуется','realization'],other:['Подготовка','other']};
function normalize(x){let r={...x};r._st=status(r);r._name=r.name||r.title||r.address||r.slug||'Площадка КРТ';r._okrug=r.okrug||r.district_group||'';r._district=r.district||'';return r}
function renderStats(){let counts={};rows.forEach(r=>counts[r._st]=(counts[r._st]||0)+1);let keys=['all','new','decision','tender','done','realization'];stats.innerHTML=keys.map(k=>'<div class="stat"><span class="muted">'+meta[k][0]+'</span><strong>'+(k==='all'?rows.length:(counts[k]||0))+'</strong></div>').join('');tabs.innerHTML=keys.concat(['other']).map(k=>'<button class="tab '+(active===k?'active':'')+'" data-k="'+k+'">'+meta[k][0]+' '+(k==='all'?rows.length:(counts[k]||0))+'</button>').join('');document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{active=b.dataset.k;render()})}
function label(r){return {tender:'Торги идут',new:'Новое',decision:'Решение опубликовано',done:'Приём завершён',realization:'В реализации',other:'Подготовка'}[r._st]}
function fmt(v,suf=''){let n=num(v);return n?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(n)+suf:'—'}
function card(r){let href='/krt-preview/site/'+encodeURIComponent(r.slug||'');let dl=r.deadline||r.application_deadline||'';return '<article class="card" onclick="location.href=\''+href+'\'"><div class="scheme"></div><div><span class="badge '+r._st+'">'+label(r)+'</span><div class="title">'+esc(r._name)+'</div><div class="muted">'+esc([r._okrug,r._district].filter(Boolean).join(' · '))+'</div><div class="metrics"><div class="metric"><b>'+fmt(r.krt_area_ha,' га')+'</b><small>Площадь</small></div><div class="metric"><b>'+fmt((r.total_gfa_sqm||0)/1000,' тыс. м²')+'</b><small>Потенциал ГНС</small></div><div class="metric"><b>'+fmt(r.surrounding_price_rub_sqm,' ₽/м²')+'</b><small>Цена окружения</small></div><div class="metric"><b>'+fmt(r.score)+'</b><small>Балл</small></div></div></div><div>'+(dl?'<div class="muted">Заявки до</div><div class="deadline">'+esc(dl)+'</div>':'')+'<div class="arrow">→</div></div></article>'}
function renderMap(view){map.innerHTML='<div></div>';for(let i=0;i<view.length&&i<40;i++){let d=document.createElement('i');d.className='dot';let h=[...String(view[i].slug||view[i]._name)].reduce((a,c)=>a+c.charCodeAt(0),0);d.style.left=(10+(h*17)%80)+'%';d.style.top=(12+(h*29)%76)+'%';d.title=view[i]._name;map.appendChild(d)}}
function render(){renderStats();let query=q.value.toLowerCase(),o=okrug.value;let view=rows.filter(r=>(active==='all'||r._st===active)&&(!o||r._okrug===o)&&(!query||JSON.stringify([r._name,r._okrug,r._district,r.address]).toLowerCase().includes(query)));list.innerHTML=view.length?view.slice(0,80).map(card).join(''):'<div class="empty">По этим условиям площадок нет.</div>';renderMap(view)}
async function boot(){try{let a=await fetch('/krt-preview/data').then(r=>r.json());let raw=a.projects||a.sites||a.rows||a.items||a.krt||[];rows=raw.map(normalize);let os=[...new Set(rows.map(r=>r._okrug).filter(Boolean))].sort();okrug.innerHTML+=[...os].map(x=>'<option>'+esc(x)+'</option>').join('');q.oninput=render;okrug.onchange=render;render()}catch(e){list.innerHTML='<div class="empty">Не удалось прочитать каталог: '+esc(e.message)+'</div>'}}</script><script>boot()</script></body></html>'''


PREVIEW_CARD = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ — карточка DevelopAid preview</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f2ef;color:#171717;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}header{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #ddd;padding:16px 28px}.top{max-width:1320px;margin:auto;display:flex;align-items:center;gap:24px}.brand{font-size:21px;font-weight:800}.top a{color:#171717;text-decoration:none}.nav{display:flex;gap:8px;overflow:auto;margin-left:auto}.nav a{padding:8px 10px;border:1px solid #ddd;white-space:nowrap}.wrap{max-width:1320px;margin:auto;padding:26px}.back{display:inline-block;margin-bottom:16px;color:#666}.hero{background:#fff;border:1px solid #ddd;padding:22px}.hero h1{font-size:28px;margin:4px 0 8px}.muted{color:#6b6b6b}.badge{display:inline-block;border:1px solid #bbb;padding:5px 8px;font-size:12px}.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:18px}.metric{border-top:1px solid #ddd;padding-top:10px}.metric b{display:block;font-size:19px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:16px;margin-top:16px}.section{background:#fff;border:1px solid #ddd;padding:20px;margin-bottom:12px;scroll-margin-top:92px}.section h2{font-size:18px;margin:0 0 12px}.actions{background:#fff;border:1px solid #ddd;padding:16px;position:sticky;top:92px;height:max-content}.actions h3{margin:0 0 12px}.actions a,.actions button{display:block;width:100%;padding:11px 12px;margin:7px 0;border:1px solid #111;background:#fff;color:#111;text-align:left;text-decoration:none;font:inherit;font-weight:650;cursor:pointer}.actions .primary{background:#111;color:#fff}.box{background:#f7f7f5;border:1px solid #e1e1df;padding:12px;margin-top:9px;white-space:pre-wrap}.cols{display:grid;grid-template-columns:1fr 1fr;gap:10px}.loading{color:#777}.err{color:#933}.links a{display:inline-block;margin:4px 10px 4px 0;color:#171717}.frame{width:100%;height:720px;border:1px solid #ddd;background:#fff}@media(max-width:800px){header{padding:12px}.top{display:block}.nav{margin-top:10px}.wrap{padding:12px}.metrics{grid-template-columns:1fr 1fr}.layout{display:block}.actions{position:static;margin-bottom:12px}.cols{grid-template-columns:1fr}.frame{height:650px}}
</style></head><body><header><div class="top"><a class="brand" href="/krt-preview">DevelopAid · КРТ</a><nav class="nav"><a href="#overview">Обзор</a><a href="#analytics">Аналитика</a><a href="#territory">Территория</a><a href="#documents">Документы</a><a href="#trades">Торги</a></nav></div></header>
<main class="wrap"><a class="back" href="/krt-preview">← Все площадки КРТ</a><section class="hero" id="overview"><span class="badge" id="status">КРТ</span><h1 id="title">Загружаю площадку…</h1><div class="muted" id="where"></div><div class="metrics" id="metrics"></div></section>
<div class="layout"><div>
<section class="section" id="analytics"><h2>Аналитика и рекомендация Платона</h2><div id="analyticsBody" class="loading">Читаю готовый отчёт ранжирования…</div></section>
<section class="section" id="territory"><h2>Территория и ЕГРН</h2><div id="territoryBody"><p>Здесь остаётся существующая рабочая карточка территории — карта, участки, правообладатели и экспорт.</p><a id="oldCard" target="_blank">Открыть полный существующий свод территории ↗</a></div></section>
<section class="section" id="documents"><h2>Документы и публикации</h2><div class="links"><a id="pubLink" href="#">Найти публикации о площадке</a><a id="reqLink" href="#">Требования решения КРТ</a></div><div id="docResult" class="box" style="display:none"></div></section>
<section class="section" id="trades"><h2>Торги</h2><div id="tradeBody" class="loading">Связанные торги и стадия площадки загружаются из каталога.</div></section>
</div><aside class="actions"><h3>Действия с площадкой</h3><a class="primary" id="handoff" href="#">Передать в DevelopAid</a><a id="export" href="#">Скачать Excel</a><a id="existing" href="#">Существующая карточка</a><button onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href)">Скопировать ссылку</button></aside></div></main>
<script>
const slug=decodeURIComponent(location.pathname.split('/').pop()), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>{n=Number(n);return Number.isFinite(n)&&n?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(n):'—'};
async function j(url){let r=await fetch(url);if(!r.ok)throw new Error((await r.text()).slice(0,180));return r.json()}
async function boot(){
 let cat=await j('/krt-preview/data'), rows=cat.projects||cat.sites||cat.rows||cat.items||cat.krt||[], r=rows.find(x=>String(x.slug||'')===slug)||{};
 title.textContent=r.name||r.title||r.address||slug; status.textContent=r.status||r.lifecycle_status||'КРТ'; where.textContent=[r.okrug,r.district,r.address].filter(Boolean).join(' · ');
 metrics.innerHTML=[['Площадь',fmt(r.krt_area_ha)+' га'],['Потенциал ГНС',fmt((Number(r.total_gfa_sqm)||0)/1000)+' тыс. м²'],['Цена окружения',fmt(r.surrounding_price_rub_sqm)+' ₽/м²'],['Балл',fmt(r.score)],['Стадия',r.status||r.lifecycle_status||'—']].map(x=>'<div class="metric"><span class="muted">'+esc(x[0])+'</span><b>'+esc(x[1])+'</b></div>').join('');
 let old='/krt/site/'+encodeURIComponent(slug); oldCard.href=old;existing.href=old;export.href=old+'/export.xlsx'; handoff.href='/auctions/krt/'+encodeURIComponent(slug)+'/handoff'; pubLink.href='/auctions/krt/'+encodeURIComponent(slug)+'/open-sources';reqLink.href='/auctions/krt/'+encodeURIComponent(slug)+'/requirements';
 tradeBody.innerHTML=(r.deadline||r.application_deadline||r.tender_url||r.auction_url)?'<b>У площадки есть связанное событие торгов.</b><div class="box">'+esc(r.deadline||r.application_deadline||r.tender_url||r.auction_url||'')+'</div>':'В строке каталога активный лот сейчас не указан.';
 try{let a=await j('/krt-preview/proxy/report/'+encodeURIComponent(slug));let sc=a.screening||{}, rec=a.recommendation||a.plato_recommendation||sc.recommendation||'';analyticsBody.className='';analyticsBody.innerHTML='<div class="cols"><div class="box"><b>Рейтинг</b><br>'+esc(r.score??a.score??'—')+'</div><div class="box"><b>Цена окружения</b><br>'+esc(fmt(r.surrounding_price_rub_sqm||sc.market_price_rub_sqm))+' ₽/м²</div></div><div class="box"><b>Рекомендация Платона</b><br>'+esc(typeof rec==='string'?rec:JSON.stringify(rec,null,2)||'В отчёте нет текстовой рекомендации')+'</div>'}catch(e){analyticsBody.className='err';analyticsBody.textContent='Готовый отчёт недоступен на тестовом стенде: '+e.message}
}
boot().catch(e=>{title.textContent='Карточка не загрузилась';where.textContent=e.message});
</script></body></html>'''

def install(app):
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
