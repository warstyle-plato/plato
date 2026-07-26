from __future__ import annotations

from datetime import date
from typing import Any

VERSION = "0.12.53"


def _resolve_vri_date(core: Any, inputs: dict[str, Any], permit: date) -> tuple[date, str]:
    """Resolve the investment-stage VRI obligation date.

    Default: one month before RnS. Users may choose another relative rule or a
    fixed documented date. The returned label is exposed in the operating model
    for reports and later Excel mapping.
    """
    mode = str(inputs.get("vri_obligation_date_mode") or "before_rns_1m").strip()

    if mode == "manual":
        raw = str(inputs.get("vri_obligation_date") or "").strip()
        if raw:
            try:
                return core.d(raw), "Дата известна — введена вручную"
            except Exception:
                pass

    if mode == "before_rns_3m":
        return core.add_months(permit, -3), "Оценочная дата — за 3 месяца до РнС"
    if mode == "at_rns":
        return permit, "Оценочная дата — в дату РнС"
    if mode == "after_purchase":
        months = int(core.n(inputs, "vri_months_after_purchase", 12))
        project_start = core.d(inputs.get("project_start", "2027-01-01"))
        return core.add_months(project_start, max(0, months)), (
            f"Оценочная дата — через {max(0, months)} мес. после покупки"
        )

    return core.add_months(permit, -1), "Оценочная дата — за 1 месяц до РнС"


def apply(runtime: Any) -> None:
    core = runtime.core

    if not getattr(core.build_operating_model, "_developaid_vri_date_patch", False):
        original = core.build_operating_model

        def build_operating_model_with_vri_date(inputs: dict[str, Any], tep: dict[str, Any]) -> dict[str, Any]:
            result = original(inputs, tep)
            amount = float((result.get("capex_amounts") or {}).get("land_rights", 0.0) or 0.0)
            permit = result["permit"]
            obligation_date, basis = _resolve_vri_date(core, inputs, permit)

            # The legacy engine placed the whole VRI payment at RnS. Move only
            # that amount; all other RnS costs remain untouched.
            if amount:
                for schedule_name in ("capex", "debt_capex"):
                    schedule = result.get(schedule_name) or {}
                    schedule[permit] = float(schedule.get(permit, 0.0) or 0.0) - amount
                    if abs(schedule[permit]) < 0.005:
                        schedule.pop(permit, None)
                    schedule[obligation_date] = float(schedule.get(obligation_date, 0.0) or 0.0) + amount
                    result[schedule_name] = schedule

            result["vri_obligation_date"] = obligation_date
            result["vri_obligation_date_basis"] = basis
            result["vri_obligation_date_is_estimated"] = not (
                str(inputs.get("vri_obligation_date_mode") or "") == "manual"
                and bool(str(inputs.get("vri_obligation_date") or "").strip())
            )
            return result

        build_operating_model_with_vri_date._developaid_vri_date_patch = True
        core.build_operating_model = build_operating_model_with_vri_date

    page = str(getattr(core, "PAGE", ""))
    if page and "developaid-vri-obligation-date-fix" not in page and "</body>" in page:
        script = r'''
<style id="developaid-vri-obligation-date-style">
#developaid-vri-date-panel{margin-top:12px;padding:12px;border:1px solid rgba(120,130,150,.28);border-radius:12px;background:rgba(120,130,150,.06)}
#developaid-vri-date-panel .vri-title{font-weight:700;margin-bottom:8px}
#developaid-vri-date-panel .vri-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}
#developaid-vri-date-panel label{display:flex;flex-direction:column;gap:5px;font-size:12px}
#developaid-vri-date-panel select,#developaid-vri-date-panel input{width:100%}
#developaid-vri-date-note{margin-top:8px;font-size:12px;opacity:.75}
</style>
<script id="developaid-vri-obligation-date-fix">
(function(){
  const KEY_MODE='vri_obligation_date_mode';
  const KEY_DATE='vri_obligation_date';
  const KEY_AFTER='vri_months_after_purchase';

  function inputStore(){
    if(typeof window.inputs==='object'&&window.inputs) return window.inputs;
    try{if(typeof inputs==='object'&&inputs) return inputs;}catch(e){}
    return null;
  }
  function field(key){return document.getElementById(key)||document.querySelector('[name="'+key+'"]');}
  function addMonths(iso,delta){
    if(!iso) return '';
    const p=String(iso).split('-').map(Number); if(p.length<3) return '';
    const d=new Date(Date.UTC(p[0],p[1]-1,p[2]));
    const day=d.getUTCDate(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth()+Number(delta||0));
    const last=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate();
    d.setUTCDate(Math.min(day,last)); return d.toISOString().slice(0,10);
  }
  function calculatedDate(mode){
    const ps=(field('project_start')||{}).value || (inputStore()||{}).project_start || '';
    const ird=Number((field('ird_months')||{}).value || (inputStore()||{}).ird_months || 18);
    const rns=addMonths(ps,ird);
    if(mode==='before_rns_3m') return addMonths(rns,-3);
    if(mode==='at_rns') return rns;
    if(mode==='after_purchase') return addMonths(ps,Number(document.getElementById('vriMonthsAfterPurchase')?.value||12));
    return addMonths(rns,-1);
  }
  function sync(){
    const panel=document.getElementById('developaid-vri-date-panel'); if(!panel) return;
    const mode=document.getElementById('vriDateMode').value;
    const manual=document.getElementById('vriManualDate');
    const after=document.getElementById('vriMonthsAfterPurchase');
    manual.closest('label').style.display=mode==='manual'?'flex':'none';
    after.closest('label').style.display=mode==='after_purchase'?'flex':'none';
    const resolved=mode==='manual'?manual.value:calculatedDate(mode);
    const store=inputStore();
    if(store){store[KEY_MODE]=mode;store[KEY_DATE]=resolved;store[KEY_AFTER]=Number(after.value||12);}
    const note=document.getElementById('developaid-vri-date-note');
    if(mode==='manual') note.textContent=resolved?'Дата обязательства: '+resolved+' (введена вручную).':'Укажите дату из документа или соглашения.';
    else note.textContent='Дата оценочная: '+(resolved||'будет рассчитана после заполнения сроков')+'. При изменении начала проекта или срока ИРД она сдвигается автоматически.';
  }
  function install(){
    if(document.getElementById('developaid-vri-date-panel')){sync();return;}
    const anchor=field('land_rights_cost_mln'); if(!anchor) return;
    const host=anchor.closest('.field,.input-row,.form-group')||anchor.parentElement;
    const store=inputStore()||{};
    const panel=document.createElement('div'); panel.id='developaid-vri-date-panel';
    panel.innerHTML='<div class="vri-title">Дата возникновения обязательства по ВРИ</div>'+
      '<div class="vri-grid">'+
      '<label>Правило даты<select id="vriDateMode">'+
      '<option value="before_rns_1m">За 1 месяц до РнС — по умолчанию</option>'+
      '<option value="before_rns_3m">За 3 месяца до РнС</option>'+
      '<option value="at_rns">В дату РнС</option>'+
      '<option value="after_purchase">Через N месяцев после покупки</option>'+
      '<option value="manual">Дата известна — указать вручную</option></select></label>'+
      '<label>Дата по документу<input id="vriManualDate" type="date"></label>'+
      '<label>Месяцев после покупки<input id="vriMonthsAfterPurchase" type="number" min="0" step="1" value="12"></label>'+
      '</div><div id="developaid-vri-date-note"></div>';
    host.insertAdjacentElement('afterend',panel);
    document.getElementById('vriDateMode').value=store[KEY_MODE]||'before_rns_1m';
    document.getElementById('vriManualDate').value=store[KEY_DATE]||'';
    document.getElementById('vriMonthsAfterPurchase').value=store[KEY_AFTER]??12;
    panel.addEventListener('input',sync); panel.addEventListener('change',sync);
    ['project_start','ird_months'].forEach(function(k){const el=field(k);if(el){el.addEventListener('input',sync);el.addEventListener('change',sync);}});
    sync();
  }
  document.addEventListener('DOMContentLoaded',function(){install();setTimeout(install,500);setTimeout(install,1500);});
  window.addEventListener('load',install);
})();
</script>
'''
        core.PAGE = page.replace("</body>", script + "</body>", 1)

    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
