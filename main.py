
from __future__ import annotations

from datetime import date
from math import pow
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="PLATO Development Model — Demo", version="0.1")


class CalcRequest(BaseModel):
    apartment_price_thousand: float = 375
    commercial_price_thousand: float = 300
    parking_price_million: float = 1.5
    above_ground_cost_thousand: float = 110
    underground_cost_thousand: float = 110
    share_sold_before_completion_pct: float = 85


def sales_revenue(quantity: float, start_price: float, pre_share: float,
                  pre_months: int = 24, post_months: int = 6,
                  growth_pre: float = 0.015, growth_post: float = 0.0025) -> float:
    """Simple monthly sales engine for the demo."""
    pre_qty = quantity * pre_share
    post_qty = quantity - pre_qty
    revenue = 0.0

    if pre_months > 0:
        q = pre_qty / pre_months
        for i in range(pre_months):
            revenue += q * start_price * pow(1 + growth_pre, i)

    if post_months > 0:
        q = post_qty / post_months
        completion_price = start_price * pow(1 + growth_pre, pre_months)
        for i in range(post_months):
            revenue += q * completion_price * pow(1 + growth_post, i)

    return revenue


def calculate(x: CalcRequest) -> dict:
    # Current control geometry from the Mytishchi model.
    apartment_saleable_sqm = 80_000.0
    commercial_saleable_sqm = 7_826.08695652174
    parking_units = 1_107.5142857142857

    above_ground_gross_sqm = 140_380.70986341068
    underground_gross_sqm = 38_763.0

    pre_share = x.share_sold_before_completion_pct / 100.0

    apartment_revenue = sales_revenue(
        apartment_saleable_sqm,
        x.apartment_price_thousand * 1_000,
        pre_share,
        growth_pre=0.015,
        growth_post=0.0025,
    )
    commercial_revenue = sales_revenue(
        commercial_saleable_sqm,
        x.commercial_price_thousand * 1_000,
        pre_share,
        growth_pre=0.015,
        growth_post=0.0025,
    )
    parking_revenue = sales_revenue(
        parking_units,
        x.parking_price_million * 1_000_000,
        pre_share,
        growth_pre=0.0075,
        growth_post=0.002,
    )

    above_capex = above_ground_gross_sqm * x.above_ground_cost_thousand * 1_000
    underground_capex = underground_gross_sqm * x.underground_cost_thousand * 1_000

    # Other current model cost blocks, explicitly visible instead of hidden Excel links.
    total_area = above_ground_gross_sqm + underground_gross_sqm
    ird = total_area * 1_000
    design_p = total_area * 2_500
    design_rd = total_area * 2_500
    preparation = total_area * 1_000
    utilities = total_area * 7_500
    landscaping = total_area * 5_000
    commissioning = total_area * 1_000
    site_maintenance = total_area * 1_000
    kindergarten = 250 * 2_750_000

    works_base = above_capex + underground_capex + kindergarten
    gc_fee = works_base * 0.07

    subtotal = (
        ird + design_p + design_rd + preparation +
        above_capex + underground_capex + utilities + landscaping +
        commissioning + site_maintenance + kindergarten + gc_fee
    )
    reserve = subtotal * 0.05
    management = subtotal * 0.05

    total_revenue = apartment_revenue + commercial_revenue + parking_revenue
    marketing = total_revenue * 0.03
    selling = total_revenue * 0.04
    total_capex = subtotal + reserve + management
    pre_fin_profit = total_revenue - total_capex - marketing - selling

    return {
        "revenue": total_revenue,
        "apartment_revenue": apartment_revenue,
        "commercial_revenue": commercial_revenue,
        "parking_revenue": parking_revenue,
        "above_capex": above_capex,
        "underground_capex": underground_capex,
        "total_capex": total_capex,
        "marketing": marketing,
        "selling": selling,
        "pre_financing_profit": pre_fin_profit,
        "note": "MVP: bridge/PF/escrow/interest/tax/LLCR parity block is not yet included."
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/calculate")
def calculate_api(x: CalcRequest):
    return calculate(x)


PAGE = r"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PLATO — Девелоперская модель</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#172033;background:#f4f6f8}
body{margin:0}.wrap{max-width:1180px;margin:auto;padding:24px}
h1{margin:0 0 6px;font-size:28px}.sub{color:#667085;margin-bottom:22px}
.grid{display:grid;grid-template-columns:360px 1fr;gap:18px}
.card{background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 10px rgba(16,24,40,.07)}
label{display:block;font-size:13px;color:#475467;margin:12px 0 5px}
input{width:100%;box-sizing:border-box;border:1px solid #d0d5dd;border-radius:8px;padding:10px;font-size:15px}
button{width:100%;margin-top:16px;padding:12px;border:0;border-radius:9px;background:#172033;color:#fff;font-weight:700}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.kpi{background:#f8fafc;padding:14px;border-radius:10px}.kpi b{display:block;font-size:21px;margin-top:5px}
table{width:100%;border-collapse:collapse;margin-top:18px}th,td{padding:9px;border-bottom:1px solid #eaecf0;text-align:right}th:first-child,td:first-child{text-align:left}
.note{margin-top:16px;color:#667085;font-size:13px;line-height:1.45}
@media(max-width:800px){.grid{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="wrap">
<h1>PLATO — Девелоперская модель</h1>
<div class="sub">Тестовая веб-версия расчётного ядра</div>
<div class="grid">
<div class="card">
<h3>Вводные</h3>
<label>Цена квартир, тыс. ₽/м²</label><input id="ap" value="375" type="number">
<label>Цена коммерции, тыс. ₽/м²</label><input id="com" value="300" type="number">
<label>Цена подземного м/м, млн ₽</label><input id="park" value="1.5" step="0.1" type="number">
<label>Наземная часть — CAPEX, тыс. ₽/м²</label><input id="above" value="110" type="number">
<label>Подземная часть — CAPEX, тыс. ₽/м²</label><input id="under" value="110" type="number">
<label>Продажи до РВЭ, %</label><input id="share" value="85" type="number">
<button onclick="run()">Пересчитать</button>
<div class="note">Поставь для подземной части 50 вместо 110 — сразу увидишь эффект отдельной себестоимости паркинга.</div>
</div>
<div class="card">
<div class="kpis">
<div class="kpi">Выручка<b id="rev">—</b></div>
<div class="kpi">CAPEX<b id="capex">—</b></div>
<div class="kpi">До финансирования<b id="profit">—</b></div>
<div class="kpi">Паркинг — выручка<b id="prev">—</b></div>
<div class="kpi">Подземный CAPEX<b id="pcost">—</b></div>
<div class="kpi">Наземный CAPEX<b id="acost">—</b></div>
</div>
<table>
<thead><tr><th>Блок</th><th>Сумма</th></tr></thead>
<tbody>
<tr><td>Квартиры</td><td id="ar"></td></tr>
<tr><td>Коммерция 1 этажа</td><td id="cr"></td></tr>
<tr><td>Подземный паркинг</td><td id="pr"></td></tr>
<tr><td>Маркетинг</td><td id="mk"></td></tr>
<tr><td>Расходы на продажи</td><td id="sl"></td></tr>
</tbody>
</table>
<div class="note"><b>Статус:</b> это MVP. Блок БРИДЖ → ПФ → эскроу → проценты → налоги → LLCR ещё переносится и пока не является заменой финальной Excel-модели.</div>
</div>
</div>
</div>
<script>
const money=v=>(v/1e9).toLocaleString('ru-RU',{maximumFractionDigits:2})+' млрд ₽';
async function run(){
 const body={
  apartment_price_thousand:+ap.value,
  commercial_price_thousand:+com.value,
  parking_price_million:+park.value,
  above_ground_cost_thousand:+above.value,
  underground_cost_thousand:+under.value,
  share_sold_before_completion_pct:+share.value
 };
 const r=await fetch('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(x=>x.json());
 rev.textContent=money(r.revenue);capex.textContent=money(r.total_capex);profit.textContent=money(r.pre_financing_profit);
 prev.textContent=money(r.parking_revenue);pcost.textContent=money(r.underground_capex);acost.textContent=money(r.above_capex);
 ar.textContent=money(r.apartment_revenue);cr.textContent=money(r.commercial_revenue);pr.textContent=money(r.parking_revenue);
 mk.textContent=money(r.marketing);sl.textContent=money(r.selling);
}
run();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
