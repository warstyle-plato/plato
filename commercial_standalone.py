"""Standalone public preview for DevelopAid non-residential economics beta.

This preview intentionally does not import the residential core. It is only for
reviewing the commercial UX and beta underwriting formulas, so it starts fast
on a sleeping/free Render instance and cannot accidentally depend on escrow or
residential project-finance state.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import developaid_commercial as commercial

app = FastAPI(title="DevelopAid Commercial Beta Preview")
commercial.install(app)

HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>DevelopAid · Нежильё β</title>
<style>
:root{--bg:#07111f;--panel:#0c1b2e;--panel2:#10243b;--line:rgba(255,255,255,.09);--text:#edf5ff;--muted:#8ea8c3;--blue:#2f8cff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 70% 0,#102748 0,transparent 35%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.shell{display:grid;grid-template-columns:240px 1fr;min-height:100vh}.side{padding:28px 20px;border-right:1px solid var(--line);background:rgba(5,14,25,.78)}
.brand{font-size:20px;font-weight:750}.brand small{display:block;color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase;margin-top:4px}
.eyebrow{color:var(--muted);font-size:10px;letter-spacing:.13em;text-transform:uppercase}.side .eyebrow{display:block;margin:34px 0 10px}
.kind{display:grid;gap:8px}.kind button{border:1px solid var(--line);border-radius:12px;padding:11px;background:#0a1a2c;color:var(--muted);text-align:left}.kind button.active{color:#fff;border-color:rgba(47,140,255,.55);background:rgba(47,140,255,.13)}
.nav{margin-top:26px;padding-top:20px;border-top:1px solid var(--line)}.nav strong{display:block;padding:11px 12px;border-radius:11px;background:rgba(47,140,255,.12);border:1px solid rgba(47,140,255,.25);font-size:12px}
.main{padding:30px;max-width:1400px;width:100%;margin:0 auto}.top{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:20px}.top h1{font-size:30px;margin:5px 0 0}.badge{font-size:10px;color:#b7cbe0;border:1px solid var(--line);padding:8px 10px;border-radius:99px}
.panel{background:linear-gradient(145deg,rgba(16,36,59,.92),rgba(9,24,41,.92));border:1px solid var(--line);border-radius:18px;padding:20px}
.selectors{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}.selectors label,.fields label{display:flex;flex-direction:column;gap:7px;color:var(--muted);font-size:11px}
select,input{width:100%;border:1px solid var(--line);border-radius:11px;background:#071727;color:#fff;padding:11px 12px;font-size:13px;outline:none}select:focus,input:focus{border-color:rgba(47,140,255,.65)}
.note{margin:14px 0 0;color:#a8bfd5;font-size:12px;line-height:1.5}.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:11px}.fields span{display:flex;justify-content:space-between;gap:10px}.fields small{font-size:9px;color:#6f8ba6}
button.primary{margin-top:16px;border:0;border-radius:12px;padding:12px 16px;background:linear-gradient(135deg,#2f8cff,#555be3);color:#fff;font-weight:700;cursor:pointer}
.status{margin-top:12px;color:var(--muted);font-size:11px}.summary{display:grid}.srow{display:grid;grid-template-columns:135px 1fr;gap:12px;padding:11px 0;border-bottom:1px solid var(--line);font-size:12px}.srow span{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:16px}.kpi{min-height:112px}.kpi label{display:block;color:var(--muted);font-size:10px;margin-bottom:12px}.kpi strong{font-size:20px}.kpi small{display:block;color:#7893ad;font-size:9px;margin-top:8px}
.report{margin-top:16px}.sections{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.sec{border:1px solid var(--line);border-radius:13px;padding:14px;background:rgba(6,18,31,.45)}.sec h3{font-size:12px;margin:0 0 8px}.sec div{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-top:1px solid rgba(255,255,255,.045);font-size:11px}.sec div span{color:var(--muted)}.sec div strong{text-align:right}
.warn{margin-top:15px;padding:12px;border:1px solid rgba(47,140,255,.2);border-radius:12px;background:rgba(47,140,255,.06);color:#abc0d6;font-size:11px;line-height:1.5}
@media(max-width:900px){.shell{display:block}.side{display:none}.main{padding:18px 14px}.grid,.selectors{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}.sections{grid-template-columns:1fr}}
@media(max-width:520px){.fields{grid-template-columns:1fr}.top h1{font-size:25px}.kpis{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="shell">
<aside class="side">
  <div class="brand">DevelopAid<small>Investment OS</small></div>
  <span class="eyebrow">Тип проекта</span>
  <div class="kind"><button>Жильё</button><button class="active">Нежильё β</button></div>
  <div class="nav"><span class="eyebrow">Раздел</span><strong>Экономика нежилья</strong></div>
</aside>
<main class="main">
  <div class="top"><div><span class="eyebrow">Отдельный контур β</span><h1>Экономика нежилого проекта</h1></div><span class="badge">без эскроу</span></div>
  <section class="panel selectors">
    <label>Тип объекта<select id="asset"></select></label>
    <label>Модель реализации<select id="strategy"></select></label>
    <label>Финансирование<select id="financing"></select></label>
    <p id="note" class="note" style="grid-column:1/-1"></p>
  </section>
  <div class="grid">
    <section class="panel"><span class="eyebrow">Допущения</span><h2 id="inputsTitle">Параметры</h2><div id="fields" class="fields"></div><button id="calc" class="primary">Рассчитать β</button><div id="status" class="status"></div></section>
    <section class="panel"><span class="eyebrow">Логика модели</span><h2>Структура расчёта</h2><div id="summary" class="summary"></div></section>
  </div>
  <section id="kpis" class="kpis"></section>
  <section class="panel report"><span class="eyebrow">Отчёт β</span><h2>Показатели по типу объекта</h2><div id="sections" class="sections"></div><div id="warnings"></div></section>
</main>
</div>
<script>
const S={d:null,asset:'office',strategy:'income',financing:'equity_debt',v:{}};
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const n=x=>x===null||x===undefined||Number.isNaN(Number(x))?null:Number(x);
function money(x){const a=n(x);if(a===null)return'—';if(Math.abs(a)>=1e9)return(a/1e9).toLocaleString('ru-RU',{maximumFractionDigits:2})+' млрд ₽';return(a/1e6).toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽'}
function pct(x){const a=n(x);return a===null?'—':(a*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%'}
function keys(){let a=['land_cost_rub','gross_area_sqm','construction_cost_rub_sqm','soft_cost_pct','contingency_pct','construction_months'];
 if(S.strategy==='income'){a.push('stabilization_months','hold_years','exit_cap_rate_pct');if(S.asset==='hotel')a.push('keys','adr_rub','occupancy_pct','other_revenue_pct','opex_pct','ffe_reserve_pct');else{a.push('income_area_sqm','rent_rub_sqm_month','occupancy_pct','opex_pct');if(S.asset==='retail')a.push('sales_rub_sqm_month','turnover_rent_pct')}}
 else{a.push('sale_start_month','sale_months','selling_cost_pct');if(S.asset==='hotel')a.push('saleable_keys','sale_price_rub_key');else a.push('saleable_area_sqm','sale_price_rub_sqm')}
 if(S.financing==='equity_debt'){a.push('debt_share_pct','debt_rate_pct','loan_fee_pct');if(S.strategy==='sale')a.push('sales_cash_sweep_pct')}
 return [...new Set(a)]}
function renderFields(){const meta=Object.fromEntries(S.d.fields.map(x=>[x.key,x]));$('inputsTitle').textContent={office:'Офис',retail:'Торговля',hotel:'Гостиница'}[S.asset];
 $('fields').innerHTML=keys().map(k=>{const m=meta[k]||{label:k,unit:''};return '<label><span>'+esc(m.label)+'<small>'+esc(m.unit||'')+'</small></span><input type="number" step="any" data-k="'+esc(k)+'" value="'+esc(S.v[k]??'')+'"></label>'}).join('');
 document.querySelectorAll('[data-k]').forEach(i=>i.addEventListener('input',()=>S.v[i.dataset.k]=Number(i.value||0)))}
function metric(label,v){const a=n(v);if(a===null)return'—';if(/₽/.test(label))return money(a);if(/RevPAR/.test(label))return a.toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';return a.toLocaleString('ru-RU',{maximumFractionDigits:2})}
function render(r){const k=r.kpi||{},income=r.strategy==='income';const cards=[
 ['Девелоперские затраты',money(k.development_cost),''],['Совокупный доход',money(k.total_revenue),''],['Прибыль до налога',money(k.profit_before_tax),''],['Маржа',pct(k.margin),''],['Собственный капитал',money(k.equity_required),''],['Пиковый долг',money(k.peak_debt),'без эскроу'],['IRR проекта',pct(k.project_irr),''],['IRR капитала',pct(k.equity_irr),'']];
 if(income){cards.push(['Стабилизированный NOI',money(k.stabilized_noi_annual),'в год'],['Yield on cost',pct(k.yield_on_cost),''])}
 $('kpis').innerHTML=cards.map(x=>'<article class="panel kpi"><label>'+esc(x[0])+'</label><strong>'+esc(x[1])+'</strong><small>'+esc(x[2])+'</small></article>').join('');
 const rp=r.report||{};$('summary').innerHTML=[['Тип расчёта',rp.title],['Реализация',rp.strategy],['Капитал',rp.financing],['Эскроу','Не используется']].map(x=>'<div class="srow"><span>'+esc(x[0])+'</span><strong>'+esc(x[1]||'')+'</strong></div>').join('');
 $('sections').innerHTML=(rp.sections||[]).map(s=>'<div class="sec"><h3>'+esc(s.name)+'</h3>'+Object.entries(s.metrics||{}).map(([l,v])=>'<div><span>'+esc(l)+'</span><strong>'+esc(metric(l,v))+'</strong></div>').join('')+'</div>').join('');
 $('warnings').innerHTML=(r.warnings||[]).map(x=>'<div class="warn">'+esc(x)+'</div>').join('')}
async function calc(){$('status').textContent='Считаю…';try{const q=await fetch('/api/v2/commercial/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_type:S.asset,strategy:S.strategy,financing_mode:S.financing,inputs:S.v})});const r=await q.json();if(!q.ok)throw new Error(r.detail||'Ошибка расчёта');render(r);$('status').textContent='Готово. Расчёт выполнен без эскроу.'}catch(e){$('status').textContent=String(e.message||e)}}
async function init(){const q=await fetch('/api/v2/commercial/form');S.d=await q.json();const fill=(id,a)=>$(id).innerHTML=a.map(x=>'<option value="'+esc(x.value)+'">'+esc(x.label)+'</option>').join('');
 fill('asset',S.d.asset_types);fill('strategy',S.d.strategies);fill('financing',S.d.financing_modes);S.v={...S.d.defaults[S.asset]};$('note').textContent=S.d.beta_note;
 $('asset').onchange=e=>{S.asset=e.target.value;S.v={...S.d.defaults[S.asset]};renderFields();calc()};$('strategy').onchange=e=>{S.strategy=e.target.value;renderFields();calc()};$('financing').onchange=e=>{S.financing=e.target.value;renderFields();calc()};$('calc').onclick=calc;renderFields();calc()}
init().catch(e=>$('status').textContent=String(e.message||e));
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
@app.get("/commercial", response_class=HTMLResponse)
def commercial_preview() -> HTMLResponse:
    return HTMLResponse(HTML, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "preview": "commercial-beta"})
