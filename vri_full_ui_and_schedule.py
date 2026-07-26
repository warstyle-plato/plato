from __future__ import annotations

from typing import Any

VERSION = "0.12.54"


def _remove_amount(schedule: dict[Any, float], when: Any, amount: float) -> None:
    schedule[when] = float(schedule.get(when, 0.0) or 0.0) - amount
    if abs(schedule[when]) < 0.005:
        schedule.pop(when, None)


def _resolved_net_amount(core: Any, inputs: dict[str, Any], gross: float) -> tuple[float, float]:
    mode = str(inputs.get("vri_relief_mode") or "none")
    if mode == "percent":
        relief = gross * max(0.0, min(100.0, core.n(inputs, "vri_relief_pct", 0.0))) / 100.0
    elif mode == "amount":
        relief = max(0.0, core.n(inputs, "vri_relief_mln", 0.0) * 1_000_000)
    else:
        relief = 0.0
    relief = min(gross, relief)
    return gross - relief, relief


def _installment_schedule(core: Any, inputs: dict[str, Any], obligation_date: Any, net: float) -> list[tuple[Any, float]]:
    mode = str(inputs.get("vri_installment_mode") or "single")
    if mode != "installments" or net <= 0:
        return [(obligation_date, net)]

    count = max(1, int(core.n(inputs, "vri_installment_count", 4)))
    step = max(1, int(core.n(inputs, "vri_installment_period_months", 3)))
    initial_pct = max(0.0, min(100.0, core.n(inputs, "vri_initial_pct", 25.0)))
    initial = net * initial_pct / 100.0
    remainder = max(0.0, net - initial)

    rows: list[tuple[Any, float]] = []
    if initial > 0:
        rows.append((obligation_date, initial))
    regular_count = count if initial_pct < 100 else 0
    if regular_count:
        regular = remainder / regular_count
        for index in range(regular_count):
            rows.append((core.add_months(obligation_date, step * (index + 1)), regular))
    return rows or [(obligation_date, net)]


def apply(runtime: Any) -> None:
    core = runtime.core

    if not getattr(core.build_operating_model, "_developaid_vri_full_patch", False):
        original = core.build_operating_model

        def build_operating_model_with_vri(inputs: dict[str, Any], tep: dict[str, Any]) -> dict[str, Any]:
            result = original(inputs, tep)
            gross = float((result.get("capex_amounts") or {}).get("land_rights", 0.0) or 0.0)
            obligation_date = result.get("vri_obligation_date") or result.get("permit")
            net, relief = _resolved_net_amount(core, inputs, gross)

            if gross and obligation_date:
                for schedule_name in ("capex", "debt_capex"):
                    schedule = result.get(schedule_name) or {}
                    _remove_amount(schedule, obligation_date, gross)
                    for payment_date, payment in _installment_schedule(core, inputs, obligation_date, net):
                        schedule[payment_date] = float(schedule.get(payment_date, 0.0) or 0.0) + payment
                    result[schedule_name] = schedule

            result.setdefault("capex_amounts", {})["land_rights_gross"] = gross
            result["capex_amounts"]["land_rights_relief"] = relief
            result["capex_amounts"]["land_rights"] = net
            result["vri_gross_amount"] = gross
            result["vri_relief_amount"] = relief
            result["vri_net_amount"] = net
            result["vri_payment_schedule"] = [
                {"date": payment_date.isoformat(), "amount": payment}
                for payment_date, payment in _installment_schedule(core, inputs, obligation_date, net)
            ] if obligation_date else []
            return result

        build_operating_model_with_vri._developaid_vri_full_patch = True
        core.build_operating_model = build_operating_model_with_vri

    if not getattr(core._telegram_send_message, "_developaid_vri_warning_patch", False):
        original_send = core._telegram_send_message

        def send_with_vri_warning(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> Any:
            message = str(text or "")
            if "смена ВРИ" in message and "без учёта льготы" not in message:
                message += (
                    "\n\n<i>Важно: ВРИ по умолчанию рассчитан без учёта льготы и рассрочки. "
                    "Их можно настроить во вкладке «ВРИ» финансовой модели DevelopAid.</i>"
                )
            return original_send(chat_id, message, reply_markup=reply_markup)

        send_with_vri_warning._developaid_vri_warning_patch = True
        core._telegram_send_message = send_with_vri_warning

    page = str(getattr(core, "PAGE", ""))
    if not page or "developaid-vri-full-ui" in page or "</body>" not in page:
        runtime._RUNTIME_VERSION = VERSION
        runtime.app.version = VERSION
        return

    script = r'''
<style id="developaid-vri-full-style">
#developaid-vri-tab{cursor:pointer}
#developaid-vri-overlay{display:none;position:fixed;inset:64px 0 0 0;z-index:9998;background:#fff;overflow:auto;padding:18px 18px 80px}
#developaid-vri-overlay.open{display:block}
#developaid-vri-overlay .vri-wrap{max-width:1180px;margin:0 auto}
#developaid-vri-overlay .vri-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}
#developaid-vri-overlay h2{margin:0;font-size:28px}
#developaid-vri-overlay .vri-close{border:1px solid #ccd1d8;background:#fff;border-radius:10px;padding:8px 12px;cursor:pointer}
#developaid-vri-overlay .vri-note{padding:12px 14px;border-radius:12px;background:#fff7df;border:1px solid #eed58c;margin-bottom:16px}
#developaid-vri-overlay .vri-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
#developaid-vri-overlay .vri-card{border:1px solid #dfe3e8;border-radius:14px;padding:14px;background:#fff}
#developaid-vri-overlay .vri-card h3{margin:0 0 10px;font-size:16px}
#developaid-vri-overlay label{display:flex;flex-direction:column;gap:5px;font-size:12px;margin-bottom:10px}
#developaid-vri-overlay input,#developaid-vri-overlay select{width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid #cfd5dc;border-radius:9px;background:#fff}
#developaid-vri-overlay .vri-kpi{font-size:22px;font-weight:700;margin-top:5px}
#developaid-vri-overlay table{width:100%;border-collapse:collapse;margin-top:10px}
#developaid-vri-overlay th,#developaid-vri-overlay td{padding:8px;border-bottom:1px solid #e7e9ec;text-align:left;font-size:13px}
#developaid-vri-overlay .vri-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
#developaid-vri-overlay .vri-primary{background:#1f2937;color:#fff;border:0;border-radius:10px;padding:10px 14px;cursor:pointer}
@media(max-width:700px){#developaid-vri-overlay{inset:52px 0 0 0;padding:12px 12px 70px}#developaid-vri-overlay h2{font-size:22px}}
</style>
<script id="developaid-vri-full-ui">
(function(){
  function store(){try{if(typeof inputs==='object'&&inputs)return inputs;}catch(e){} if(window.inputs&&typeof window.inputs==='object')return window.inputs; return null;}
  function field(id){return document.getElementById(id)||document.querySelector('[name="'+id+'"]');}
  function n(v,d){const x=Number(v);return Number.isFinite(x)?x:(d||0);}
  function money(v){return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n(v)/1000000)+' млн ₽';}
  function addMonths(iso,delta){if(!iso)return '';const p=String(iso).split('-').map(Number);if(p.length<3)return '';const d=new Date(Date.UTC(p[0],p[1]-1,p[2]));const day=d.getUTCDate();d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+Number(delta||0));const last=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate();d.setUTCDate(Math.min(day,last));return d.toISOString().slice(0,10);}
  function gross(){const s=store()||{};return n((field('land_rights_cost_mln')||{}).value||s.land_rights_cost_mln)*1000000;}
  function values(){
    const s=store()||{};
    return {
      vri_relief_mode:(field('vri_relief_mode')||{}).value||s.vri_relief_mode||'none',
      vri_relief_pct:n((field('vri_relief_pct')||{}).value||s.vri_relief_pct),
      vri_relief_mln:n((field('vri_relief_mln')||{}).value||s.vri_relief_mln),
      vri_installment_mode:(field('vri_installment_mode')||{}).value||s.vri_installment_mode||'single',
      vri_initial_pct:n((field('vri_initial_pct')||{}).value||s.vri_initial_pct,25),
      vri_installment_count:Math.max(1,Math.round(n((field('vri_installment_count')||{}).value||s.vri_installment_count,4))),
      vri_installment_period_months:Math.max(1,Math.round(n((field('vri_installment_period_months')||{}).value||s.vri_installment_period_months,3))),
      vri_obligation_date_mode:(field('vriDateMode')||{}).value||s.vri_obligation_date_mode||'before_rns_1m',
      vri_obligation_date:(field('vriManualDate')||{}).value||s.vri_obligation_date||''
    };
  }
  function obligation(v){if(v.vri_obligation_date_mode==='manual'&&v.vri_obligation_date)return v.vri_obligation_date;const s=store()||{};const ps=(field('project_start')||{}).value||s.project_start||'';const ird=n((field('ird_months')||{}).value||s.ird_months,18);const rns=addMonths(ps,ird);if(v.vri_obligation_date_mode==='before_rns_3m')return addMonths(rns,-3);if(v.vri_obligation_date_mode==='at_rns')return rns;return addMonths(rns,-1);}
  function sync(){
    const s=store();const v=values();if(s)Object.assign(s,v);
    const g=gross();let relief=0;if(v.vri_relief_mode==='percent')relief=g*Math.max(0,Math.min(100,v.vri_relief_pct))/100;if(v.vri_relief_mode==='amount')relief=Math.max(0,v.vri_relief_mln*1000000);relief=Math.min(g,relief);const net=g-relief;
    const gp=document.getElementById('vriGrossKpi'),rp=document.getElementById('vriReliefKpi'),np=document.getElementById('vriNetKpi');if(gp)gp.textContent=money(g);if(rp)rp.textContent=money(relief);if(np)np.textContent=money(net);
    const pct=document.getElementById('vri_relief_pct_wrap'),amt=document.getElementById('vri_relief_mln_wrap');if(pct)pct.style.display=v.vri_relief_mode==='percent'?'flex':'none';if(amt)amt.style.display=v.vri_relief_mode==='amount'?'flex':'none';
    const inst=document.getElementById('vri_installment_fields');if(inst)inst.style.display=v.vri_installment_mode==='installments'?'grid':'none';
    const body=document.getElementById('vriScheduleBody');if(body){body.innerHTML='';const date=obligation(v);let rows=[];if(v.vri_installment_mode==='installments'){const initial=net*Math.max(0,Math.min(100,v.vri_initial_pct))/100;if(initial>0)rows.push([date,initial,'Первоначальный платёж']);const rest=net-initial;for(let i=0;i<v.vri_installment_count;i++)rows.push([addMonths(date,v.vri_installment_period_months*(i+1)),rest/v.vri_installment_count,'Платёж '+(i+1)]);}else rows=[[date,net,'Единовременно']];rows.forEach(r=>{const tr=document.createElement('tr');tr.innerHTML='<td>'+String(r[0]||'—')+'</td><td>'+r[2]+'</td><td>'+money(r[1])+'</td>';body.appendChild(tr);});}
  }
  function regionalCopy(){
    document.querySelectorAll('h1,h2,h3').forEach(el=>{if(el.textContent.trim()==='Калькулятор ТЭП ГлавАПУ')el.textContent='Расчёт ТЭП по кадастровому номеру';});
    document.querySelectorAll('p').forEach(el=>{if(el.textContent.includes('DevelopAid сам сформирует территорию в калькуляторе ГлавАПУ'))el.innerHTML='<b>Москва и Новая Москва:</b> расчёт через калькулятор ГлавАПУ.<br><b>Московская область:</b> собственный расчёт DevelopAid по постановлениям и распоряжениям Правительства Московской области.<br><b>Другие регионы:</b> загрузка ТЭП из Excel или ручной ввод. Перед применением значения показываются для проверки.';});
  }
  function install(){
    regionalCopy();
    if(document.getElementById('developaid-vri-tab')){sync();return;}
    const tep=[...document.querySelectorAll('button,a,[role="tab"],div,span')].find(el=>el.children.length===0&&el.textContent.trim()==='ТЭП');if(!tep)return;
    const tab=tep.cloneNode(true);tab.id='developaid-vri-tab';tab.textContent='ВРИ';tep.insertAdjacentElement('afterend',tab);
    const overlay=document.createElement('section');overlay.id='developaid-vri-overlay';overlay.innerHTML=`<div class="vri-wrap"><div class="vri-head"><h2>ВРИ: льгота и график оплаты</h2><button class="vri-close" type="button">Закрыть</button></div><div class="vri-note"><b>По умолчанию сумма ВРИ принимается без льготы и оплачивается единовременно.</b> Здесь можно задать льготу, рассрочку и дату обязательства. Изменения входят в cash flow, БРИДЖ, ПФ, проценты и собственный капитал после пересчёта модели.</div><div class="vri-grid"><div class="vri-card"><h3>Исходная сумма</h3><div class="vri-kpi" id="vriGrossKpi">—</div><small>Берётся из поля «Оформление земельных правоотношений / смена ВРИ».</small></div><div class="vri-card"><h3>Льгота</h3><label>Режим<select id="vri_relief_mode"><option value="none">Без льготы</option><option value="percent">Льгота, %</option><option value="amount">Льгота, млн ₽</option></select></label><label id="vri_relief_pct_wrap">Размер льготы, %<input id="vri_relief_pct" type="number" min="0" max="100" step="0.1" value="0"></label><label id="vri_relief_mln_wrap">Размер льготы, млн ₽<input id="vri_relief_mln" type="number" min="0" step="0.1" value="0"></label><div class="vri-kpi" id="vriReliefKpi">—</div></div><div class="vri-card"><h3>Сумма к оплате</h3><div class="vri-kpi" id="vriNetKpi">—</div><small>Исходная сумма за вычетом льготы.</small></div><div class="vri-card"><h3>Порядок оплаты</h3><label>Режим<select id="vri_installment_mode"><option value="single">Единовременно</option><option value="installments">Рассрочка</option></select></label><div id="vri_installment_fields" class="vri-grid"><label>Первоначальный платёж, %<input id="vri_initial_pct" type="number" min="0" max="100" step="1" value="25"></label><label>Количество последующих платежей<input id="vri_installment_count" type="number" min="1" step="1" value="4"></label><label>Период между платежами, мес.<input id="vri_installment_period_months" type="number" min="1" step="1" value="3"></label></div></div></div><div class="vri-card" style="margin-top:12px"><h3>График платежей</h3><table><thead><tr><th>Дата</th><th>Основание</th><th>Сумма</th></tr></thead><tbody id="vriScheduleBody"></tbody></table></div><div class="vri-actions"><button class="vri-primary" id="vriApplyAndRecalc" type="button">Применить и пересчитать модель</button><button class="vri-close" type="button">Вернуться к модели</button></div></div>`;document.body.appendChild(overlay);
    const s=store()||{};['vri_relief_mode','vri_relief_pct','vri_relief_mln','vri_installment_mode','vri_initial_pct','vri_installment_count','vri_installment_period_months'].forEach(id=>{const el=field(id);if(el&&s[id]!==undefined)el.value=s[id];});
    tab.addEventListener('click',e=>{e.preventDefault();overlay.classList.add('open');sync();});overlay.querySelectorAll('.vri-close').forEach(b=>b.addEventListener('click',()=>overlay.classList.remove('open')));overlay.addEventListener('input',sync);overlay.addEventListener('change',sync);document.getElementById('vriApplyAndRecalc').addEventListener('click',()=>{sync();overlay.classList.remove('open');const btn=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Пересчитать модель'));if(btn)btn.click();});sync();
  }
  document.addEventListener('DOMContentLoaded',()=>{install();setTimeout(install,500);setTimeout(install,1500)});window.addEventListener('load',install);
})();
</script>
'''
    core.PAGE = page.replace("</body>", script + "</body>", 1)
    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
