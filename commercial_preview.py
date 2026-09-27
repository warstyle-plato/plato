"""Standalone browser QA shell for the commercial beta engine.

This staging app deliberately does not import the residential application.  It
serves the commercial API and a small browser form so the underwriting engine
can be tested directly from the feature branch without touching main.
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import developaid_commercial as commercial

app = FastAPI(title="DevelopAid commercial engine QA")
commercial.install(app)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "engine": "commercial-beta-2"})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · Commercial Engine QA</title>
<style>
:root{--bg:#07111f;--panel:#0d1b2d;--line:#21344c;--text:#eef5ff;--muted:#91a7bf;--blue:#2f8cff}
*{box-sizing:border-box}body{margin:0;background:#07111f;color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:12px;align-items:end;margin-bottom:18px}
h1{font-size:26px;margin:4px 0}.muted{color:var(--muted);font-size:12px}.badge{border:1px solid var(--line);border-radius:99px;padding:7px 10px;font-size:11px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:14px}
.selectors,.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
label{display:flex;flex-direction:column;gap:6px;color:var(--muted);font-size:11px}input,select{background:#071727;color:#fff;border:1px solid var(--line);border-radius:10px;padding:10px;font-size:13px}
button{border:0;border-radius:10px;padding:11px 15px;background:var(--blue);color:white;font-weight:700;cursor:pointer}.actions{display:flex;align-items:center;gap:12px;margin-top:14px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.kpi{background:#091827;border:1px solid var(--line);border-radius:12px;padding:13px}.kpi span{display:block;color:var(--muted);font-size:10px}.kpi strong{display:block;font-size:18px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:11px}th,td{padding:8px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}th{color:var(--muted)}
pre{white-space:pre-wrap;word-break:break-word;font-size:10px;color:#b9cee4;max-height:320px;overflow:auto}
@media(max-width:800px){.selectors,.fields{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}main{padding:14px}}
</style>
</head>
<body><main>
<div class="top"><div><div class="muted">ОТДЕЛЬНЫЙ STAGING · MAIN НЕ ТРОНУТ</div><h1>Нежилая экономика β2</h1></div><div class="badge">без эскроу</div></div>

<section class="panel selectors">
<label>Тип объекта<select id="asset"><option value="office">Офис</option><option value="retail">Торговля</option><option value="hotel">Гостиница</option></select></label>
<label>Стратегия<select id="strategy"><option value="income">Доходная / hold</option><option value="sale">Продажа</option></select></label>
<label>Финансирование<select id="financing"><option value="equity_debt">Equity + обычный кредит</option><option value="equity">100% equity</option></select></label>
</section>

<section class="panel">
<div class="muted">ПАРАМЕТРЫ</div>
<div id="fields" class="fields"></div>
<div class="actions"><button id="calc">Рассчитать</button><span id="status" class="muted">Загрузка…</span></div>
</section>

<section id="kpis" class="kpis"></section>

<section class="panel">
<div class="muted">ГОДОВОЙ CASH FLOW</div>
<div style="overflow:auto"><table><thead><tr><th>Год</th><th>Development</th><th>Operating rev.</th><th>Sale rev.</th><th>Exit</th><th>Project CF</th><th>Interest</th><th>Ending debt</th><th>Equity CF</th></tr></thead><tbody id="annual"></tbody></table></div>
</section>

<section class="panel"><div class="muted">CHECKS / WARNINGS</div><pre id="checks"></pre></section>
</main>
<script>
const $=s=>document.querySelector(s);
const state={form:null,asset:'office',strategy:'income',financing:'equity_debt',values:{}};
const common=['land_cost_rub','gross_area_sqm','construction_cost_rub_sqm','soft_cost_pct','contingency_pct','construction_months'];
const incomeCommon=['opening_occupancy_pct','occupancy_pct','stabilization_months','hold_years','exit_cap_rate_pct','exit_cost_pct','project_discount_rate_pct','equity_hurdle_rate_pct'];
const saleCommon=['sale_start_month','sale_months','sales_curve','sale_price_growth_pct','selling_cost_pct','project_discount_rate_pct','equity_hurdle_rate_pct'];
const financing=['debt_share_pct','debt_rate_pct','loan_fee_pct','sales_cash_sweep_pct'];

function keys(){
 let out=[...common];
 if(state.strategy==='income'){
   out.push(...incomeCommon);
   if(state.asset==='office')out.push('income_area_sqm','rent_rub_sqm_month','rent_growth_pct','other_income_pct','opex_pct','leasing_cost_pct');
   if(state.asset==='retail')out.push('income_area_sqm','rent_rub_sqm_month','sales_rub_sqm_month','turnover_rent_pct','rent_growth_pct','opex_pct','marketing_pct');
   if(state.asset==='hotel')out.push('keys','adr_rub','adr_growth_pct','other_revenue_pct','opex_pct','management_fee_pct','ffe_reserve_pct','preopening_cost_rub');
 } else {
   out.push(...saleCommon);
   if(state.asset==='hotel')out.push('saleable_keys','sale_price_rub_key','preopening_cost_rub');
   else out.push('saleable_area_sqm','sale_price_rub_sqm');
 }
 if(state.financing==='equity_debt')out.push(...financing);
 return [...new Set(out)];
}
function renderFields(){
 const meta=Object.fromEntries(state.form.fields.map(x=>[x.key,x]));
 const host=$('#fields');host.innerHTML='';
 for(const k of keys()){
   const m=meta[k]||{label:k,unit:''};
   const lab=document.createElement('label');lab.textContent=m.label+(m.unit?' · '+m.unit:'');
   let input;
   if(k==='sales_curve'){
     input=document.createElement('select');
     for(const v of ['bell','flat','front_loaded','back_loaded']){const o=document.createElement('option');o.value=v;o.textContent=v;input.appendChild(o);}
     input.value=state.values[k]??'bell';
   } else {
     input=document.createElement('input');input.type='number';input.step='any';input.value=state.values[k]??0;
   }
   input.oninput=()=>{state.values[k]=k==='sales_curve'?input.value:Number(input.value||0)};
   lab.appendChild(input);host.appendChild(lab);
 }
}
const money=x=>Number(x||0).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
const pct=x=>x==null?'—':(Number(x)*100).toLocaleString('ru-RU',{maximumFractionDigits:2})+'%';
const mult=x=>x==null?'—':Number(x).toLocaleString('ru-RU',{maximumFractionDigits:2})+'x';
function render(r){
 const k=r.kpi;
 const cards=[
  ['Development cost',money(k.development_cost)],['Total revenue',money(k.total_revenue)],['Profit before tax',money(k.profit_before_tax)],['Margin',pct(k.margin)],
  ['Project IRR',pct(k.project_irr)],['Project NPV',money(k.project_npv)],['Equity required',money(k.equity_required)],['Equity IRR',pct(k.equity_irr)],
  ['Equity multiple',mult(k.equity_multiple)],['Peak debt',money(k.peak_debt)],['LTC',pct(k.ltc)],['Exit LTV',pct(k.exit_ltv)],
  ['NOI / year',money(k.stabilized_noi_annual)],['Yield on cost',pct(k.yield_on_cost)],['Exit value',money(k.exit_value)],['Net exit proceeds',money(k.net_exit_proceeds)]
 ];
 $('#kpis').innerHTML=cards.map(x=>'<div class="kpi"><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join('');
 $('#annual').innerHTML=(r.annual||[]).map(y=>'<tr><td>'+y.year+'</td><td>'+money(y.development_spend)+'</td><td>'+money(y.operating_revenue)+'</td><td>'+money(y.sale_revenue)+'</td><td>'+money(y.terminal_value)+'</td><td>'+money(y.project_cashflow)+'</td><td>'+money(y.interest)+'</td><td>'+money(y.ending_debt)+'</td><td>'+money(y.equity_cashflow)+'</td></tr>').join('');
 $('#checks').textContent=JSON.stringify({checks:r.checks,warnings:r.warnings,operating:r.operating},null,2);
}
async function calculate(){
 $('#status').textContent='Считаю…';
 try{
  const res=await fetch('/api/v2/commercial/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_type:state.asset,strategy:state.strategy,financing_mode:state.financing,inputs:state.values})});
  if(!res.ok)throw new Error(await res.text());
  const data=await res.json();render(data);$('#status').textContent='Готово · '+data.version;
 }catch(e){$('#status').textContent='Ошибка: '+e.message;}
}
async function init(){
 const res=await fetch('/api/v2/commercial/form',{cache:'no-store'});state.form=await res.json();
 function reset(){state.values=structuredClone(state.form.defaults[state.asset]);}
 reset();
 $('#asset').onchange=()=>{state.asset=$('#asset').value;reset();renderFields();calculate();};
 $('#strategy').onchange=()=>{state.strategy=$('#strategy').value;renderFields();calculate();};
 $('#financing').onchange=()=>{state.financing=$('#financing').value;renderFields();calculate();};
 $('#calc').onclick=calculate;renderFields();calculate();
}
init();
</script></body></html>"""
