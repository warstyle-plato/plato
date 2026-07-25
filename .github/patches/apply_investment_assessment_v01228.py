from __future__ import annotations

from pathlib import Path

MAIN = Path('main.py')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected 1 occurrence, found {count}')
    return text.replace(old, new, 1)


text = MAIN.read_text(encoding='utf-8')

# Version and template compatibility.
version_count = text.count('0.12.27')
if version_count < 3:
    raise RuntimeError(f'version: expected at least 3 occurrences, found {version_count}')
text = text.replace('0.12.27', '0.12.28')
text = replace_once(
    text,
    'MANUAL_TEP_TEMPLATE_VERSION = "DevelopAid_TEP_2"',
    'MANUAL_TEP_TEMPLATE_VERSION = "DevelopAid_TEP_3"',
    'template version',
)
text = replace_once(
    text,
    '    if version != MANUAL_TEP_TEMPLATE_VERSION:\n        raise ValueError("Версия шаблона не распознана. Скачайте актуальный файл командой /template.")',
    '    if version not in {MANUAL_TEP_TEMPLATE_VERSION, "DevelopAid_TEP_2"}:\n        raise ValueError("Версия шаблона не распознана. Скачайте актуальный файл командой /template.")',
    'template backward compatibility',
)
text = replace_once(
    text,
    'def health(): return {"status":"ok","version":"0.12.25"}',
    'def health(): return {"status":"ok","version":"0.12.28"}',
    'health version',
)

# Request schema for deterministic investment assessment.
class_anchor = '''class AgentChatRequest(BaseModel):
    message: str
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    history: list[dict[str, Any]] = []
    selected_view: str = "all"


class CadastralAnalysisRequest(BaseModel):
'''
class_replacement = '''class AgentChatRequest(BaseModel):
    message: str
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    history: list[dict[str, Any]] = []
    selected_view: str = "all"


class InvestmentAssessmentRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    target_llcr: float = 1.20
    target_npv_mln: float = 0.0


class CadastralAnalysisRequest(BaseModel):
'''
text = replace_once(text, class_anchor, class_replacement, 'assessment request class')

# Deterministic endpoint: ceiling by bankability and investment return.
endpoint_anchor = '''@app.get("/current-key-rate")
def current_key_rate() -> dict[str, Any]:
'''
endpoint_code = r'''def _assessment_solution_value(result: dict[str, Any]) -> float | None:
    if not isinstance(result, dict) or not result.get("available"):
        return None
    solution = result.get("solution") or {}
    value = solution.get("variable")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


@app.post("/investment/assessment")
def investment_assessment_api(req: InvestmentAssessmentRequest) -> dict[str, Any]:
    target_llcr = max(1.0, min(3.0, float(req.target_llcr or 1.20)))
    target_npv_mln = float(req.target_npv_mln or 0.0)
    agent_req = AgentChatRequest(
        message="Автоматическая инвестиционная оценка",
        inputs=copy.deepcopy(req.inputs),
        tep=copy.deepcopy(req.tep),
        rates=copy.deepcopy(req.rates),
        phasing=copy.deepcopy(req.phasing),
        history=[],
        selected_view="all",
    )
    bundle = _run_authoritative_model(agent_req.inputs, agent_req.tep, agent_req.rates, agent_req.phasing)
    llcr_scope = "weakest_phase" if bundle.get("mode") == "phased" else "consolidated"

    llcr_ceiling = _tool_goal_seek(
        agent_req, bundle,
        "purchase_price_mln", "llcr", target_llcr,
        "at_least", "maximum_variable", llcr_scope,
        None, None,
    )
    npv_ceiling = _tool_goal_seek(
        agent_req, bundle,
        "purchase_price_mln", "npv_mln", target_npv_mln,
        "at_least", "maximum_variable", "consolidated",
        None, None,
    )

    llcr_value = _assessment_solution_value(llcr_ceiling)
    npv_value = _assessment_solution_value(npv_ceiling)
    current_price = max(0.0, n(agent_req.inputs, "purchase_price_mln"))
    current_snapshot = _result_snapshot(bundle["consolidated"])
    current_min_llcr = _min_phase_llcr(bundle)
    current_npv_mln = float((bundle["consolidated"].get("summary") or {}).get("npv", 0) or 0) / 1e6

    if llcr_value is None or npv_value is None:
        missing = []
        if llcr_value is None:
            missing.append("LLCR")
        if npv_value is None:
            missing.append("NPV")
        return {
            "available": False,
            "status": "not_feasible",
            "verdict": (
                "По текущим ценам, себестоимости, срокам и финансированию проект не проходит "
                "обязательные критерии даже при нулевой цене покупки. Сначала нужно менять экономику проекта."
            ),
            "failed_criteria": missing,
            "target_llcr_x": target_llcr,
            "target_npv_mln": target_npv_mln,
            "current_purchase_price_mln": round(current_price, 4),
            "current": {
                "min_llcr_x": round(current_min_llcr, 4),
                "npv_mln": round(current_npv_mln, 2),
                "snapshot": current_snapshot,
                "phase_llcr": _phase_llcr(bundle),
            },
            "llcr_ceiling": llcr_ceiling,
            "npv_ceiling": npv_ceiling,
            "method": "Полный детерминированный Goal Seek на копии текущей модели; исходные Inputs не изменены.",
        }

    max_price = min(llcr_value, npv_value)
    binding = "LLCR 1,20×" if llcr_value <= npv_value + 0.01 else "NPV ≥ 0"
    binding_result = llcr_ceiling if binding.startswith("LLCR") else npv_ceiling
    ceiling_is_lower_bound = bool(binding_result.get("threshold_beyond_bound"))

    ceiling_inputs = copy.deepcopy(agent_req.inputs)
    ceiling_inputs["purchase_price_mln"] = max_price
    ceiling_bundle = _run_authoritative_model(ceiling_inputs, agent_req.tep, agent_req.rates, agent_req.phasing)
    ceiling_snapshot = _result_snapshot(ceiling_bundle["consolidated"])
    ceiling_min_llcr = _min_phase_llcr(ceiling_bundle)
    ceiling_npv_mln = float((ceiling_bundle["consolidated"].get("summary") or {}).get("npv", 0) or 0) / 1e6

    if current_price <= 0.0001:
        status = "ceiling_calculated"
        verdict = (
            "Проект предварительно экономически реализуем по текущим предпосылкам. "
            "Ниже показан максимальный расчётный уровень цены покупки."
        )
    elif current_price <= max_price + 0.01:
        status = "passes"
        verdict = (
            "Текущая цена покупки проходит оба критерия: LLCR не ниже целевого и NPV не ниже нуля. "
            "Перед решением проверьте стресс-сценарий и исходные предпосылки."
        )
    else:
        status = "above_ceiling"
        verdict = (
            "Текущая цена покупки выше допустимого уровня. По текущей экономике требуется торг "
            "либо подтверждённое улучшение цены продаж, себестоимости, сроков или финансирования."
        )

    gap = current_price - max_price if current_price > 0 else None
    gap_pct = (current_price / max_price - 1.0) * 100 if gap is not None and max_price > 0 else None
    return {
        "available": True,
        "status": status,
        "verdict": verdict,
        "target_llcr_x": target_llcr,
        "target_npv_mln": target_npv_mln,
        "current_purchase_price_mln": round(current_price, 4),
        "max_purchase_price_mln": round(max_price, 4),
        "llcr_ceiling_mln": round(llcr_value, 4),
        "npv_ceiling_mln": round(npv_value, 4),
        "binding_constraint": binding,
        "ceiling_is_lower_bound": ceiling_is_lower_bound,
        "comparison": {
            "price_above_ceiling_mln": round(gap, 4) if gap is not None else None,
            "price_above_ceiling_pct": round(gap_pct, 2) if gap_pct is not None else None,
        },
        "current": {
            "min_llcr_x": round(current_min_llcr, 4),
            "npv_mln": round(current_npv_mln, 2),
            "snapshot": current_snapshot,
            "phase_llcr": _phase_llcr(bundle),
        },
        "at_ceiling": {
            "min_llcr_x": round(ceiling_min_llcr, 4),
            "npv_mln": round(ceiling_npv_mln, 2),
            "snapshot": ceiling_snapshot,
            "phase_llcr": _phase_llcr(ceiling_bundle),
        },
        "assumptions": {
            "project_class": str(agent_req.inputs.get("project_class") or "custom"),
            "apartment_price_th_per_sqm": round(n(agent_req.inputs, "apartment_price_th"), 2),
            "main_above_cost_th_per_sqm_gns": round(n(agent_req.inputs, "main_above_th_per_sqm"), 2),
            "discount_rate_pct": round(n(agent_req.inputs, "discount_rate_pct"), 2),
            "rate_scenario": str(agent_req.inputs.get("rate_scenario") or "base"),
            "phased": bundle.get("mode") == "phased",
        },
        "llcr_ceiling": llcr_ceiling,
        "npv_ceiling": npv_ceiling,
        "method": (
            "Допустимая цена — меньшее из двух значений: потолок при LLCR не ниже целевого "
            "и потолок при NPV не ниже нуля. Выполнен многократный полный пересчёт DevelopAid на копии модели."
        ),
        "warning": (
            "Это предварительная инвестиционная оценка, а не рыночный отчёт или решение банка. "
            "Результат зависит от текущих цен продаж, бюджета, сроков, социальной нагрузки и условий финансирования."
        ),
    }


@app.get("/current-key-rate")
def current_key_rate() -> dict[str, Any]:
'''
text = replace_once(text, endpoint_anchor, endpoint_code, 'assessment endpoint')

# Telegram template caption and manual metadata.
text = replace_once(
    text,
    '                "Бот проверит файл и покажет сводку перед открытием модели."',
    '                "Бот проверит файл, покажет сводку, а мини-приложение рассчитает допустимую цену покупки. "\n'
    '                "Внутри Платон Сергеевич поможет подобрать параметры и ответит на вопросы."',
    'template caption',
)
text = replace_once(
    text,
    '''  inputs._manual_tep_import={
   project_name:String(manual.project_name||''),
   site_area_ha:Number(manual.site_area_ha||0),
''',
    '''  inputs._manual_tep_import={
   project_name:String(manual.project_name||''),
   region:String(manual.region||''),
   site_area_ha:Number(manual.site_area_ha||0),
''',
    'manual import region',
)

# UI styles.
css_anchor = '.ai-drawer{position:fixed;top:0;right:0;'
css_insert = r'''.investment-card{border-top:7px solid #111;background:#fff}.investment-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}.investment-head h2{margin:0 0 6px}.investment-head p{margin:0;color:#666;font-size:12px;line-height:1.5;max-width:850px}.investment-verdict{padding:15px 16px;margin:14px 0;border-left:5px solid #555;background:#f5f5f3;font-size:14px;line-height:1.55}.investment-verdict.pass{border-left-color:#166534;background:#f0f8f2;color:#134e2a}.investment-verdict.fail{border-left-color:#b42318;background:#fff3f2;color:#8f1d16}.investment-verdict.warn{border-left-color:#9a6700;background:#fff8e6;color:#704800}.investment-kpis{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));border-top:1px solid #111;border-left:1px solid #ddd}.investment-kpi{padding:14px;border-right:1px solid #ddd;border-bottom:1px solid #ddd;min-height:88px}.investment-kpi small{display:block;color:#777;font-size:10px;text-transform:uppercase;letter-spacing:.06em}.investment-kpi b{display:block;margin-top:8px;font-size:20px;font-weight:650}.investment-details{margin-top:12px;font-size:12px;line-height:1.55;color:#555}.investment-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.investment-loading{padding:14px 0;color:#777;font-size:12px}@media(max-width:760px){.investment-kpis{grid-template-columns:1fr 1fr}}
'''
if css_anchor not in text:
    raise RuntimeError('investment css anchor not found')
text = text.replace(css_anchor, css_insert + css_anchor, 1)

# UI card after TEP import block.
html_anchor = '''      </div>
      <div class="card">
        <div class="section-title">Вводные данные</div>
'''
html_replacement = '''      </div>
      <div id="investmentAssessmentCard" class="card investment-card" style="display:none">
        <div class="investment-head">
          <div>
            <div class="section-title">Инвестиционная оценка</div>
            <h2>Экономическая целесообразность покупки</h2>
            <p>DevelopAid рассчитывает два потолка цены входа: по LLCR не ниже 1,20× и по NPV не ниже нуля. Итоговая допустимая цена — меньшее из двух значений.</p>
          </div>
          <button class="btn dark" onclick="runInvestmentAssessment(true)">Пересчитать оценку</button>
        </div>
        <div id="investmentAssessmentBody" class="investment-loading">Загрузите и примените ТЭП — оценка появится автоматически.</div>
      </div>
      <div class="card">
        <div class="section-title">Вводные данные</div>
'''
text = replace_once(text, html_anchor, html_replacement, 'investment card')

# JS state.
text = replace_once(
    text,
    'let aiHistory=[],aiBusy=false,aiProposals=[];',
    'let aiHistory=[],aiBusy=false,aiProposals=[];\nlet lastInvestmentAssessment=null,investmentAssessmentBusy=false;',
    'investment js state',
)

# JS calculation and rendering functions.
js_anchor = '''function currentMonetizableSaleable(){
'''
js_code = r'''const investmentMln=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' млн ₽';
function renderInvestmentAssessment(data){
 const card=document.getElementById('investmentAssessmentCard'),body=document.getElementById('investmentAssessmentBody');
 if(!card||!body)return;card.style.display='block';
 if(!data||!data.available){
  const verdict=(data&&data.verdict)||'Не удалось определить допустимую цену покупки по текущим предпосылкам.';
  const cur=(data&&data.current)||{};
  body.innerHTML=`<div class="investment-verdict fail"><b>Проект пока не проходит инвестиционные критерии.</b><br>${escapeHtml(verdict)}</div>`+
   `<div class="investment-kpis"><div class="investment-kpi"><small>Минимальный LLCR</small><b>${Number(cur.min_llcr_x||0).toFixed(3)}×</b></div><div class="investment-kpi"><small>NPV</small><b>${investmentMln(cur.npv_mln||0)}</b></div><div class="investment-kpi"><small>Цель LLCR</small><b>1,20×</b></div><div class="investment-kpi"><small>Цель NPV</small><b>≥ 0</b></div></div>`+
   `<div class="investment-actions"><button class="btn" onclick="askInvestmentAgent()">Подобрать параметры с Платоном Сергеевичем</button></div>`;
  return;
 }
 const cls=data.status==='passes'?'pass':(data.status==='above_ceiling'?'fail':'warn');
 const title=data.status==='passes'?'Цена проходит':(data.status==='above_ceiling'?'Нужен торг':'Ценовой потолок рассчитан');
 const prefix=data.ceiling_is_lower_bound?'не менее ':'';
 const current=Number(data.current_purchase_price_mln||0),max=Number(data.max_purchase_price_mln||0),cmp=data.comparison||{},at=data.at_ceiling||{},snap=at.snapshot||{},a=data.assumptions||{};
 const offerLine=current>0
  ? `<div><b>Цена в Inputs:</b> ${investmentMln(current)}${data.status==='above_ceiling'?` · выше потолка на <b>${investmentMln(cmp.price_above_ceiling_mln||0)}</b> (${Number(cmp.price_above_ceiling_pct||0).toFixed(1)}%)`:' · находится в допустимом диапазоне'}</div>`
  : '<div>Цена продавца пока не введена. Укажите её во Вводных и нажмите «Пересчитать оценку».</div>';
 body.innerHTML=`<div class="investment-verdict ${cls}"><b>${title}.</b><br>${escapeHtml(data.verdict||'')}</div>`+
  `<div class="investment-kpis">`+
   `<div class="investment-kpi"><small>Допустимая цена покупки</small><b>${prefix}${investmentMln(max)}</b></div>`+
   `<div class="investment-kpi"><small>Потолок по LLCR 1,20×</small><b>${investmentMln(data.llcr_ceiling_mln)}</b></div>`+
   `<div class="investment-kpi"><small>Потолок по NPV ≥ 0</small><b>${investmentMln(data.npv_ceiling_mln)}</b></div>`+
   `<div class="investment-kpi"><small>Ограничивающий критерий</small><b>${escapeHtml(data.binding_constraint||'—')}</b></div>`+
  `</div>`+
  `<div class="investment-details">${offerLine}<div><b>На расчётном потолке:</b> минимальный LLCR ${Number(at.min_llcr_x||0).toFixed(3)}× · NPV ${investmentMln(at.npv_mln||0)} · чистая прибыль ${investmentMln(snap.net_profit_mln||0)} · маржа ${Number(snap.margin_pct||0).toFixed(1)}%.</div><div><b>Предпосылки:</b> жильё ${Number(a.apartment_price_th_per_sqm||0).toLocaleString('ru-RU')} тыс. ₽/м² · наземная себестоимость ${Number(a.main_above_cost_th_per_sqm_gns||0).toLocaleString('ru-RU')} тыс. ₽/м² ГНС · ставка дисконтирования ${Number(a.discount_rate_pct||0).toFixed(1)}%.</div><div style="margin-top:7px">${escapeHtml(data.warning||'')}</div></div>`+
  `<div class="investment-actions"><button class="btn dark" onclick="askInvestmentAgent()">Обсудить и подобрать параметры</button><button class="btn" onclick="openTab('inputs')">Изменить вводные</button></div>`;
}
async function runInvestmentAssessment(showCard=true){
 const card=document.getElementById('investmentAssessmentCard'),body=document.getElementById('investmentAssessmentBody');
 if(showCard&&card)card.style.display='block';
 if(investmentAssessmentBusy)return lastInvestmentAssessment;
 const hasSource=!!inputs._glavapu_import||!!inputs._manual_tep_import;
 if(!hasSource){if(body)body.textContent='Сначала загрузите и примените ТЭП.';return null}
 investmentAssessmentBusy=true;if(body)body.innerHTML='<div class="investment-loading">Подбираю допустимую цену покупки полным пересчётом модели…</div>';
 try{
  await syncInputsForAgent();
  const response=await fetch('/investment/assessment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates,phasing,target_llcr:1.20,target_npv_mln:0})});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'Не удалось выполнить инвестиционную оценку');
  lastInvestmentAssessment=data;renderInvestmentAssessment(data);return data;
 }catch(e){if(body)body.innerHTML='<div class="investment-verdict fail"><b>Оценка не выполнена.</b><br>'+escapeHtml(String(e.message||e))+'</div>';return null}
 finally{investmentAssessmentBusy=false}
}
function askInvestmentAgent(){
 toggleAgent(true);
 setTimeout(()=>askAgentQuick('Оцени экономическую целесообразность покупки по текущей модели. Сопоставь цену в Inputs с допустимым потолком по LLCR 1,20 и NPV не ниже нуля. Если цена не проходит — подбери реалистичные изменения цены продажи, себестоимости, сроков или финансирования и подготовь изменения только после расчёта.'),100);
}

function currentMonetizableSaleable(){
'''
text = replace_once(text, js_anchor, js_code, 'investment js functions')

# Automatic assessment after imported TEP is applied (ГлавАПУ and Telegram/manual).
auto_anchor = '''  await calculate();
  await sendTelegramResult();
'''
auto_count = text.count(auto_anchor)
if auto_count != 2:
    raise RuntimeError(f'auto assessment calls: expected 2 occurrences, found {auto_count}')
text = text.replace(
    auto_anchor,
    '''  await calculate();
  await runInvestmentAssessment(true);
  await sendTelegramResult();
''',
)

# Reopen assessment for locally stored imported projects without duplicating Telegram launch calculation.
init_anchor = '''  await loadPresetCatalog();
  await initializeTelegramLaunch();
}
'''
init_replacement = '''  await loadPresetCatalog();
  await initializeTelegramLaunch();
  if((inputs._glavapu_import||inputs._manual_tep_import)&&!lastInvestmentAssessment)await runInvestmentAssessment(true);
}
'''
text = replace_once(text, init_anchor, init_replacement, 'initial assessment restore')

MAIN.write_text(text, encoding='utf-8')
print('DevelopAid v0.12.28 investment assessment patch applied')
