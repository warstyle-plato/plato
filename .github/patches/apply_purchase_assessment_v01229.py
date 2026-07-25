from __future__ import annotations

from pathlib import Path

MAIN = Path('main.py')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected 1 occurrence, found {count}')
    return text.replace(old, new, 1)


def insert_before_telegram_send(source: str, function_marker: str) -> str:
    start = source.find(function_marker)
    if start < 0:
        raise RuntimeError(f'function not found: {function_marker}')
    end = source.find('\n}\n', start)
    if end < 0:
        raise RuntimeError(f'function end not found: {function_marker}')
    send = source.find('await sendTelegramResult();', start, end)
    if send < 0:
        raise RuntimeError(f'Telegram send not found: {function_marker}')
    if 'await runPurchaseAssessment(true);' in source[start:end]:
        return source
    line_start = source.rfind('\n', start, send) + 1
    indent = source[line_start:send]
    return source[:line_start] + indent + 'await runPurchaseAssessment(true);\n' + source[line_start:]


text = MAIN.read_text(encoding='utf-8')

# Version and Excel-template compatibility.
version_count = text.count('0.12.28')
if version_count < 3:
    raise RuntimeError(f'version markers: expected at least 3, found {version_count}')
text = text.replace('0.12.28', '0.12.29')
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

# API request schema.
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


class PurchaseAssessmentRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    target_llcr: float = 1.20
    target_npv_mln: float = 0.0


class CadastralAnalysisRequest(BaseModel):
'''
text = replace_once(text, class_anchor, class_replacement, 'purchase assessment request')

# Deterministic purchase assessment. It reuses the existing authoritative Goal Seek.
endpoint_anchor = '''@app.get("/current-key-rate")
def current_key_rate() -> dict[str, Any]:
'''
endpoint_code = r'''def _purchase_assessment_solution(result: dict[str, Any]) -> float | None:
    if not isinstance(result, dict) or not result.get("available"):
        return None
    try:
        value = float((result.get("solution") or {}).get("variable"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


@app.post("/investment/purchase-assessment")
def purchase_assessment_api(req: PurchaseAssessmentRequest) -> dict[str, Any]:
    target_llcr = max(1.0, min(3.0, float(req.target_llcr or 1.20)))
    target_npv_mln = float(req.target_npv_mln or 0.0)
    agent_req = AgentChatRequest(
        message="Автоматическая оценка цены покупки",
        inputs=copy.deepcopy(req.inputs),
        tep=copy.deepcopy(req.tep),
        rates=copy.deepcopy(req.rates),
        phasing=copy.deepcopy(req.phasing),
        history=[],
        selected_view="all",
    )
    current_bundle = _run_authoritative_model(
        agent_req.inputs, agent_req.tep, agent_req.rates, agent_req.phasing
    )
    llcr_scope = "weakest_phase" if current_bundle.get("mode") == "phased" else "consolidated"
    llcr_result = _tool_goal_seek(
        agent_req, current_bundle,
        "purchase_price_mln", "llcr", target_llcr,
        "at_least", "maximum_variable", llcr_scope,
        None, None,
    )
    npv_result = _tool_goal_seek(
        agent_req, current_bundle,
        "purchase_price_mln", "npv_mln", target_npv_mln,
        "at_least", "maximum_variable", "consolidated",
        None, None,
    )
    llcr_ceiling = _purchase_assessment_solution(llcr_result)
    npv_ceiling = _purchase_assessment_solution(npv_result)
    current_price = max(0.0, n(agent_req.inputs, "purchase_price_mln"))
    current_min_llcr = _min_phase_llcr(current_bundle)
    _, current_npv, _ = _metric_value(current_bundle, "npv_mln", "consolidated", "all")

    if llcr_ceiling is None or npv_ceiling is None:
        return {
            "available": False,
            "status": "not_feasible",
            "verdict": (
                "По текущим ценам продаж, себестоимости, срокам и финансированию проект не проходит "
                "оба обязательных критерия даже при нулевой цене покупки."
            ),
            "current_purchase_price_mln": round(current_price, 4),
            "current_min_llcr_x": round(float(current_min_llcr or 0), 4),
            "current_npv_mln": round(float(current_npv or 0), 2),
            "target_llcr_x": target_llcr,
            "target_npv_mln": target_npv_mln,
            "llcr_result": llcr_result,
            "npv_result": npv_result,
            "warning": (
                "Это предварительная инвестиционная оценка, а не рыночный отчёт или решение банка. "
                "Сначала проверьте рыночные цены, бюджет, сроки, социальную нагрузку и условия финансирования."
            ),
        }

    max_price = min(llcr_ceiling, npv_ceiling)
    binding = "LLCR" if llcr_ceiling <= npv_ceiling + 0.01 else "NPV"
    binding_result = llcr_result if binding == "LLCR" else npv_result
    ceiling_inputs = copy.deepcopy(agent_req.inputs)
    ceiling_inputs["purchase_price_mln"] = max_price
    ceiling_bundle = _run_authoritative_model(
        ceiling_inputs, agent_req.tep, agent_req.rates, agent_req.phasing
    )
    ceiling_min_llcr = _min_phase_llcr(ceiling_bundle)
    _, ceiling_npv, _ = _metric_value(ceiling_bundle, "npv_mln", "consolidated", "all")

    if current_price <= 0.0001:
        status = "ceiling_calculated"
        verdict = "Проект предварительно реализуем; цена продавца не введена, поэтому рассчитан ценовой потолок."
    elif current_price <= max_price + 0.01:
        status = "passes"
        verdict = "Текущая цена покупки проходит критерии LLCR и NPV при заданных предпосылках."
    else:
        status = "above_ceiling"
        verdict = "Текущая цена выше расчётного потолка: нужен торг либо подтверждённое улучшение экономики проекта."

    gap = max(0.0, current_price - max_price) if current_price > 0 else None
    gap_pct = (current_price / max_price - 1) * 100 if gap is not None and max_price > 0 else None
    return {
        "available": True,
        "status": status,
        "verdict": verdict,
        "current_purchase_price_mln": round(current_price, 4),
        "max_purchase_price_mln": round(max_price, 4),
        "llcr_ceiling_mln": round(llcr_ceiling, 4),
        "npv_ceiling_mln": round(npv_ceiling, 4),
        "binding_constraint": binding,
        "ceiling_is_lower_bound": bool(binding_result.get("threshold_beyond_bound")),
        "price_above_ceiling_mln": round(gap, 4) if gap is not None else None,
        "price_above_ceiling_pct": round(gap_pct, 2) if gap_pct is not None else None,
        "current_min_llcr_x": round(float(current_min_llcr or 0), 4),
        "current_npv_mln": round(float(current_npv or 0), 2),
        "ceiling_min_llcr_x": round(float(ceiling_min_llcr or 0), 4),
        "ceiling_npv_mln": round(float(ceiling_npv or 0), 2),
        "target_llcr_x": target_llcr,
        "target_npv_mln": target_npv_mln,
        "method": (
            "Полный детерминированный Goal Seek DevelopAid. Допустимая цена — меньшее из потолков "
            "по LLCR не ниже 1,20× и NPV не ниже нуля. Исходные параметры автоматически не изменяются."
        ),
        "warning": (
            "Это предварительная инвестиционная оценка, а не рыночный отчёт или решение банка. "
            "Результат зависит от введённых цен продаж, бюджета, сроков, социальной нагрузки и финансирования."
        ),
    }


@app.get("/current-key-rate")
def current_key_rate() -> dict[str, Any]:
'''
text = replace_once(text, endpoint_anchor, endpoint_code, 'purchase assessment endpoint')

# Explain the next stage in the Telegram template caption.
text = replace_once(
    text,
    '            "Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid."',
    '            "Бот проверит структуру, покажет сводку и предложит открыть проект в DevelopAid. "\n'
    '            "В приложении появится оценка допустимой цены покупки, а Платон Сергеевич поможет подобрать параметры и ответит на вопросы."',
    'Telegram template caption',
)

# Compact in-app card; this is not a separate screen.
css_anchor = '.ai-drawer{position:fixed;top:0;right:0;'
css = r'''.purchase-assessment-card{border-top:7px solid #111}.purchase-assessment-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap}.purchase-assessment-head h2{margin:0 0 6px}.purchase-assessment-head p{margin:0;max-width:860px;color:#666;font-size:12px;line-height:1.5}.purchase-verdict{margin:14px 0;padding:13px 15px;border-left:5px solid #8a4b08;background:#fff8e6;font-size:13px;line-height:1.55}.purchase-verdict.pass{border-left-color:#166534;background:#f0f8f2;color:#134e2a}.purchase-verdict.fail{border-left-color:#b42318;background:#fff3f2;color:#8f1d16}.purchase-kpis{display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));border-top:1px solid #111;border-left:1px solid #ddd}.purchase-kpi{padding:13px;border-right:1px solid #ddd;border-bottom:1px solid #ddd}.purchase-kpi small{display:block;color:#777;font-size:10px;text-transform:uppercase;letter-spacing:.05em}.purchase-kpi b{display:block;margin-top:7px;font-size:19px}.purchase-details{margin-top:11px;color:#555;font-size:12px;line-height:1.55}.purchase-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}@media(max-width:760px){.purchase-kpis{grid-template-columns:1fr 1fr}}
'''
if css_anchor not in text:
    raise RuntimeError('CSS anchor not found')
text = text.replace(css_anchor, css + css_anchor, 1)

html_anchor = '''      </div>
      <div class="card">
        <div class="section-title">Вводные данные</div>
'''
html = '''      </div>
      <div id="purchaseAssessmentCard" class="card purchase-assessment-card" style="display:none">
        <div class="purchase-assessment-head">
          <div><div class="section-title">Инвестиционная оценка</div><h2>Целесообразность покупки</h2><p>После применения ТЭП DevelopAid автоматически определяет допустимую цену входа по двум ограничениям: LLCR не ниже 1,20× и NPV не ниже нуля.</p></div>
          <button class="btn dark" onclick="runPurchaseAssessment(true)">Пересчитать</button>
        </div>
        <div id="purchaseAssessmentBody" class="purchase-details">Примените ТЭП — оценка появится автоматически.</div>
      </div>
      <div class="card">
        <div class="section-title">Вводные данные</div>
'''
text = replace_once(text, html_anchor, html, 'purchase assessment card')

text = replace_once(
    text,
    'let aiHistory=[],aiBusy=false,aiProposals=[];',
    'let aiHistory=[],aiBusy=false,aiProposals=[];\nlet purchaseAssessmentBusy=false,lastPurchaseAssessment=null;',
    'purchase assessment JS state',
)

js_anchor = 'function currentMonetizableSaleable(){\n'
js = r'''const assessmentMoney=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽';
function renderPurchaseAssessment(data){
 const card=document.getElementById('purchaseAssessmentCard'),body=document.getElementById('purchaseAssessmentBody');
 if(!card||!body)return;card.style.display='block';
 if(!data||!data.available){
  const verdict=(data&&data.verdict)||'Не удалось определить допустимую цену покупки.';
  body.innerHTML=`<div class="purchase-verdict fail"><b>Проект пока не проходит.</b><br>${escapeHtml(verdict)}</div>`+
   `<div class="purchase-kpis"><div class="purchase-kpi"><small>Текущий LLCR</small><b>${Number(data?.current_min_llcr_x||0).toFixed(3)}×</b></div><div class="purchase-kpi"><small>Текущий NPV</small><b>${assessmentMoney(data?.current_npv_mln||0)}</b></div><div class="purchase-kpi"><small>Цель LLCR</small><b>1,20×</b></div><div class="purchase-kpi"><small>Цель NPV</small><b>≥ 0</b></div></div>`+
   `<div class="purchase-actions"><button class="btn" onclick="askPurchaseAgent()">Подобрать параметры с Платоном Сергеевичем</button></div>`;
  return;
 }
 const cls=data.status==='passes'?'pass':(data.status==='above_ceiling'?'fail':'');
 const title=data.status==='passes'?'Цена проходит':(data.status==='above_ceiling'?'Нужен торг':'Ценовой потолок рассчитан');
 const lower=data.ceiling_is_lower_bound?'не менее ':'';
 const current=Number(data.current_purchase_price_mln||0);
 const comparison=current>0?(data.status==='above_ceiling'?`Цена в Inputs выше потолка на <b>${assessmentMoney(data.price_above_ceiling_mln||0)}</b> (${Number(data.price_above_ceiling_pct||0).toFixed(1)}%).`:'Цена в Inputs находится в допустимом диапазоне.'):'Цена продавца в Inputs пока не указана.';
 body.innerHTML=`<div class="purchase-verdict ${cls}"><b>${title}.</b><br>${escapeHtml(data.verdict||'')}</div>`+
  `<div class="purchase-kpis"><div class="purchase-kpi"><small>Допустимая цена покупки</small><b>${lower}${assessmentMoney(data.max_purchase_price_mln)}</b></div><div class="purchase-kpi"><small>Потолок по LLCR</small><b>${assessmentMoney(data.llcr_ceiling_mln)}</b></div><div class="purchase-kpi"><small>Потолок по NPV</small><b>${assessmentMoney(data.npv_ceiling_mln)}</b></div><div class="purchase-kpi"><small>Ограничивает</small><b>${escapeHtml(data.binding_constraint||'—')}</b></div></div>`+
  `<div class="purchase-details">${comparison}<br>На потолке: LLCR ${Number(data.ceiling_min_llcr_x||0).toFixed(3)}×, NPV ${assessmentMoney(data.ceiling_npv_mln||0)}.<br>${escapeHtml(data.warning||'')}</div>`+
  `<div class="purchase-actions"><button class="btn dark" onclick="askPurchaseAgent()">Обсудить и подобрать параметры</button><button class="btn" onclick="openTab('inputs')">Изменить вводные</button></div>`;
}
async function runPurchaseAssessment(showCard=true){
 const card=document.getElementById('purchaseAssessmentCard'),body=document.getElementById('purchaseAssessmentBody');
 if(showCard&&card)card.style.display='block';
 if(purchaseAssessmentBusy)return lastPurchaseAssessment;
 if(!inputs._glavapu_import&&!inputs._manual_tep_import){if(body)body.textContent='Сначала загрузите и примените ТЭП.';return null}
 purchaseAssessmentBusy=true;if(body)body.textContent='Рассчитываю допустимую цену покупки полным пересчётом модели…';
 try{
  await syncInputsForAgent();
  const response=await fetch('/investment/purchase-assessment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates,phasing,target_llcr:1.20,target_npv_mln:0})});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'Ошибка инвестиционной оценки');
  lastPurchaseAssessment=data;renderPurchaseAssessment(data);return data;
 }catch(e){if(body)body.innerHTML='<div class="purchase-verdict fail"><b>Оценка не выполнена.</b><br>'+escapeHtml(String(e.message||e))+'</div>';return null}
 finally{purchaseAssessmentBusy=false}
}
function askPurchaseAgent(){
 toggleAgent(true);
 setTimeout(()=>askAgentQuick('Оцени целесообразность покупки по текущим параметрам. Сопоставь цену в Inputs с потолком по LLCR 1,20 и NPV не ниже нуля. Если цена не проходит, подбери реалистичные изменения цены продаж, себестоимости, сроков или финансирования. Ничего не применяй без моего подтверждения.'),100);
}

function currentMonetizableSaleable(){
'''
text = replace_once(text, js_anchor, js, 'purchase assessment JS')

text = insert_before_telegram_send(text, 'async function applyTelegramManualTep(manual){')
text = insert_before_telegram_send(text, 'async function applyGlavapu(){')

# Restore the card for a locally saved imported project.
init_start = text.find('async function initializeApp(){')
init_end = text.find('\n}\n', init_start)
launch = text.find('await initializeTelegramLaunch();', init_start, init_end)
if init_start < 0 or init_end < 0 or launch < 0:
    raise RuntimeError('initializeApp anchor not found')
if 'lastPurchaseAssessment)await runPurchaseAssessment(true);' not in text[init_start:init_end]:
    line_start = text.rfind('\n', init_start, launch) + 1
    line_end = text.find('\n', launch)
    indent = text[line_start:launch]
    restore = indent + 'if((inputs._glavapu_import||inputs._manual_tep_import)&&!lastPurchaseAssessment)await runPurchaseAssessment(true);\n'
    text = text[:line_end + 1] + restore + text[line_end + 1:]

MAIN.write_text(text, encoding='utf-8')
print('DevelopAid v0.12.29 purchase assessment patch applied')
