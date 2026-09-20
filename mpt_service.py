from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from mpt_calc import K_ZATR_2026, MPTInput, RULESET_REVIEWED_AT, calculate_mpt_benefit

app = FastAPI(title="DevelopAid MPT Calculator", version="0.1.0")


class MPTRequest(BaseModel):
    mpt_area_sqm: float = Field(gt=0)
    k_location: float = Field(ge=0, le=1)
    k_term: float = 1.0
    scenario: Literal["new", "reconstruction", "ons"] = "new"
    readiness_percent: float = Field(default=0.0, ge=0, le=100)
    excluded_area_sqm: float = Field(default=0.0, ge=0)
    object_type: str = ""


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "mpt",
        "version": app.version,
        "k_zatr": K_ZATR_2026,
        "ruleset_reviewed_at": RULESET_REVIEWED_AT.isoformat(),
    }


@app.post("/api/mpt/calculate")
def calculate(req: MPTRequest) -> dict[str, object]:
    try:
        result = calculate_mpt_benefit(MPTInput(**req.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


PAGE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DevelopAid — МПТ</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#101114;background:#f4f5f7}
*{box-sizing:border-box} body{margin:0}.wrap{max-width:920px;margin:0 auto;padding:24px 16px 56px}
.head{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:18px}
h1{font-size:28px;margin:0}.muted{color:#6a6f78;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:#fff;border:1px solid #e1e3e6;border-radius:14px;padding:16px;margin-bottom:14px}.field{display:flex;flex-direction:column;gap:6px}
label{font-size:13px;color:#4c5159}input,select{width:100%;font:inherit;padding:12px;border:1px solid #cfd3d8;border-radius:10px;background:#fff}
button{width:100%;padding:13px 16px;border:0;border-radius:10px;background:#15171a;color:#fff;font:inherit;font-weight:650;cursor:pointer}
.result{font-size:34px;font-weight:750;letter-spacing:-.02em}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}
.metric{background:#f6f7f8;border-radius:10px;padding:12px}.metric b{display:block;font-size:18px;margin-top:4px}.warn{margin-top:10px;padding:10px 12px;border-radius:9px;background:#fff5d8;font-size:13px}
.formula{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;padding:10px 12px;background:#f6f7f8;border-radius:9px;overflow:auto}
@media(max-width:680px){.grid,.metrics{grid-template-columns:1fr}.head{display:block}.result{font-size:30px}}
</style>
</head>
<body><main class="wrap">
<div class="head"><div><h1>Калькулятор льготы МПТ</h1><div class="muted">Москва · ПП №1874-ПП · расчёт на текущую дату</div></div><div class="muted">DevelopAid v0.1</div></div>
<div class="card"><div class="grid">
<div class="field"><label>Сценарий</label><select id="scenario"><option value="new">Новое строительство</option><option value="reconstruction">Реконструкция</option><option value="ons">ОНС</option></select></div>
<div class="field"><label>Назначение МПТ</label><select id="object_type"><option>Офис / деловое</option><option>Промышленное</option><option>Гостиница</option><option>Социальное</option><option>Спортивное</option><option>Культура</option><option>Иное</option></select></div>
<div class="field"><label>Площадь МПТ, м²</label><input id="area" type="number" min="0" step="1" value="10000"></div>
<div class="field"><label>Исключаемая площадь, м²</label><input id="excluded" type="number" min="0" step="1" value="0"></div>
<div class="field"><label>Кмест</label><select id="k_location"><option value="0">0,00</option><option value="0.3">0,30</option><option value="0.5">0,50</option><option value="0.7" selected>0,70</option><option value="0.8">0,80</option></select></div>
<div class="field"><label>Ксрок</label><select id="k_term"><option value="1" selected>1,00 — обычный срок</option><option value="1.05">1,05 — сокращение на 6–12 мес.</option><option value="1.1">1,10 — сокращение на 12+ мес.</option></select></div>
<div class="field" id="readinessBox" style="display:none"><label>Готовность ОНС, %</label><input id="readiness" type="number" min="0" max="100" step="1" value="0"></div>
</div><div style="height:14px"></div><button id="calc">Рассчитать льготу</button>
<div class="muted" style="margin-top:9px">Кмест пока задаётся вручную. Автоопределение по адресу/кадастровому кварталу будет отдельным справочником — без догадок внутри формулы.</div></div>
<div class="card"><div class="muted">Расчётная льгота</div><div id="benefit" class="result">—</div><div class="metrics">
<div class="metric"><span class="muted">Sмпт к расчёту</span><b id="eligible">—</b></div><div class="metric"><span class="muted">Льгота на 1 м²</span><b id="perSqm">—</b></div><div class="metric"><span class="muted">Кзатр 2026</span><b>166,23078</b></div>
</div><div style="height:12px"></div><div id="formula" class="formula">—</div><div id="warnings"></div></div>
<div class="muted">Нормативная база: ПП Москвы №1874-ПП; Кзатр = 166,23078 — приказ ДИПП Москвы от 10.03.2026 № ДИПП-ПР-33/26. Набор правил проверен 08.08.2026.</div>
</main>
<script>
const fmtRub=n=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:0}).format(n);
const fmtNum=n=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n);
const scenario=document.getElementById('scenario');
scenario.addEventListener('change',()=>{document.getElementById('readinessBox').style.display=scenario.value==='ons'?'flex':'none';});
async function calc(){
 const payload={mpt_area_sqm:+document.getElementById('area').value,k_location:+document.getElementById('k_location').value,k_term:+document.getElementById('k_term').value,scenario:scenario.value,readiness_percent:scenario.value==='ons'?+document.getElementById('readiness').value:0,excluded_area_sqm:+document.getElementById('excluded').value,object_type:document.getElementById('object_type').value};
 const r=await fetch('/api/mpt/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const data=await r.json(); if(!r.ok){alert(data.detail||'Ошибка расчёта');return;}
 document.getElementById('benefit').textContent=fmtRub(data.benefit_rub);
 document.getElementById('eligible').textContent=fmtNum(data.eligible_area_sqm)+' м²';
 document.getElementById('perSqm').textContent=fmtRub(data.benefit_per_sqm_rub);
 document.getElementById('formula').textContent=data.formula;
 document.getElementById('warnings').innerHTML=(data.warnings||[]).map(x=>'<div class="warn">'+x+'</div>').join('');
}
document.getElementById('calc').addEventListener('click',calc); calc();
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(PAGE)
