"""Isolated UI/API integration for the Moscow MPT benefit calculator.

The extension intentionally does not change the existing VRI/TEP or financial
calculation engine. It only mounts an optional MPT panel into the existing Mini
App and adds a separate Telegram menu entry that opens that panel directly.
"""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import json

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from mpt_calculator import (
    KZATR_DEFAULT,
    MptCalculationError,
    MptInput,
    calculate_mpt_benefit,
    metadata,
)


def _strict_json(raw: bytes) -> Any:
    """JSON без NaN и Infinity: в расчёте им места нет, а json.loads их берёт."""
    def reject(token: str) -> Any:
        raise MptCalculationError(f"Числовое поле содержит {token} — это не число.")

    try:
        return json.loads(raw or b"{}", parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise MptCalculationError(f"Тело запроса не разобралось как JSON: {exc}") from exc


def _first_error(exc: ValidationError) -> str:
    """Читаемая причина вместо списка словарей — её увидит человек в панели."""
    errors = exc.errors()
    if not errors:
        return "Запрос не прошёл проверку."
    first = errors[0]
    field = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    return f"Поле «{field}»: {first.get('msg', 'некорректное значение')}" if field else str(
        first.get("msg", "некорректное значение"))

_INSTALLED = False
_MENU_TEXT = "🏗 Льгота МПТ — Москва"
_PAGE_MARKER = 'id="mpt-benefit-template"'


class MptCalculateRequest(BaseModel):
    category: str
    district: str
    area_sqm: float = Field(gt=0)
    mode: str = "new"
    ttk_position: str | None = None
    parking_sqm: float = Field(default=0, ge=0)
    garages_sqm: float = Field(default=0, ge=0)
    warehouse_inside_sqm: float = Field(default=0, ge=0)
    warehouse_yard_sqm: float = Field(default=0, ge=0)
    hotel_rooms_sqm: float = Field(default=0, ge=0)
    mixed_use: bool = False
    kzatr: float = Field(default=KZATR_DEFAULT, gt=0)
    ons_readiness_pct: float = Field(default=0, ge=0, lt=100)
    ons_registered_before_2019_11_01: bool | None = None


# Прежний интерфейс слал «Ксрок» и кадастровый номер: первого в постановлении
# нет вовсе, второй был нужен таблице из 99 кварталов, которой там тоже нет.
# Молча проглотить их нельзя — Ксрок менял ответ до 10%.
_REMOVED_FIELDS = {
    "kterm": "Ксрок в 1874-ПП отсутствует: формула п. 1.14.1 — 1000 × Sмпт × Кзатр × Кмест.",
    "cadastral_number": "Таблицы кадастровых кварталов в 1874-ПП нет; Кмест берётся по району.",
}


def _append_query(url: str, **values: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _mpt_url(base: Any, chat_id: int) -> str:
    return _append_query(base.core._telegram_web_app_url(chat_id, []), section="mpt")


def _keyboard_texts(reply_markup: Any) -> list[str]:
    if not isinstance(reply_markup, dict):
        return []
    rows = reply_markup.get("keyboard")
    if not isinstance(rows, list):
        return []
    result: list[str] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        for button in row:
            if isinstance(button, str):
                result.append(button)
            elif isinstance(button, dict):
                result.append(str(button.get("text") or ""))
    return result


def _main_menu_with_mpt(reply_markup: Any) -> Any:
    """Add MPT only to the persistent main reply keyboard, not temporary keyboards."""
    texts = _keyboard_texts(reply_markup)
    if not texts or _MENU_TEXT in texts:
        return reply_markup
    if not any("ВРИ" in text.upper() or "ТЭП" in text.upper() for text in texts):
        return reply_markup
    updated = copy.deepcopy(reply_markup)
    updated.setdefault("keyboard", []).append([{"text": _MENU_TEXT}])
    return updated


def _install_bot(base: Any) -> None:
    previous_send = base.core._telegram_send_message
    previous_handle_update = base.core._telegram_handle_update

    def send_message(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> Any:
        return previous_send(chat_id, text, reply_markup=_main_menu_with_mpt(reply_markup))

    def handle_update(update: dict[str, Any]) -> None:
        message = update.get("message") if isinstance(update, dict) else None
        if isinstance(message, dict):
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            chat_id = int(chat.get("id") or sender.get("id") or 0)
            text = str(message.get("text") or "").strip()
            command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
            if chat_id and (text == _MENU_TEXT or command in {"/mpt", "/мпт"}):
                try:
                    url = _mpt_url(base, chat_id)
                    send_message(
                        chat_id,
                        "<b>Льгота МПТ — Москва</b>\n"
                        "Расчёт самостоятельный: он определяет размер льготы, создаваемой самим МПТ. "
                        "К текущему ВРИ проекта льгота пока автоматически не применяется.",
                        reply_markup={"inline_keyboard": [[{
                            "text": "Открыть калькулятор МПТ",
                            "web_app": {"url": url},
                        }]]},
                    )
                except Exception as exc:
                    send_message(chat_id, "<b>Калькулятор МПТ не открылся.</b>\n" + str(exc)[:250])
                return
        previous_handle_update(update)

    base.core._telegram_send_message = send_message
    base.core._telegram_handle_update = handle_update


_MPT_FRAGMENT = r'''
<style>
#mpt-benefit-panel{margin:16px 0;border:1px solid rgba(127,127,127,.28);border-radius:14px;background:rgba(127,127,127,.045);overflow:hidden}
#mpt-benefit-panel>summary{cursor:pointer;padding:14px 16px;font-weight:700;list-style:none;display:flex;align-items:center;justify-content:space-between;gap:12px}
#mpt-benefit-panel>summary::-webkit-details-marker{display:none}
#mpt-benefit-panel>summary:after{content:'▾';opacity:.6}
#mpt-benefit-panel[open]>summary:after{content:'▴'}
#mpt-benefit-panel .mpt-body{padding:0 16px 16px}
#mpt-benefit-panel .mpt-note{font-size:12px;opacity:.68;margin:0 0 12px}
#mpt-benefit-panel .mpt-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 12px}
#mpt-benefit-panel label{display:block;font-size:12px;opacity:.78;margin-bottom:4px}
#mpt-benefit-panel input,#mpt-benefit-panel select{width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid rgba(127,127,127,.32);border-radius:9px;background:transparent;color:inherit;font:inherit}
#mpt-benefit-panel .mpt-wide{grid-column:1/-1}
#mpt-benefit-panel .mpt-hidden{display:none!important}
#mpt-benefit-panel button{margin-top:12px;padding:10px 14px;border:0;border-radius:9px;background:#6f64e8;color:#fff;font-weight:700;cursor:pointer}
#mpt-benefit-panel .mpt-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px}
#mpt-benefit-panel .mpt-kpi{padding:10px;border:1px solid rgba(127,127,127,.22);border-radius:10px}
#mpt-benefit-panel .mpt-kpi small{display:block;opacity:.65}
#mpt-benefit-panel .mpt-kpi strong{display:block;margin-top:3px;font-size:16px}
#mpt-benefit-panel .mpt-formula,#mpt-benefit-panel .mpt-warnings{margin-top:10px;padding:10px;border-radius:9px;background:rgba(127,127,127,.07);font-size:12px;white-space:pre-wrap}
@media(max-width:640px){#mpt-benefit-panel .mpt-grid,#mpt-benefit-panel .mpt-kpis{grid-template-columns:1fr}}
</style>
<template id="mpt-benefit-template">
  <details id="mpt-benefit-panel">
    <summary><span>Льгота МПТ — Москва</span><small style="opacity:.62;font-weight:500">1874-ПП</small></summary>
    <div class="mpt-body">
      <p class="mpt-note">Отдельный расчёт льготы, создаваемой самим МПТ. Текущий ВРИ проекта и финансовая модель не изменяются.</p>
      <div class="mpt-grid">
        <div><label for="mpt-category">Тип МПТ</label><select id="mpt-category"></select></div>
        <div><label for="mpt-mode">Сценарий</label><select id="mpt-mode"><option value="new">Новое строительство</option><option value="reconstruction">Реконструкция</option><option value="ons">ОНС</option></select></div>
        <div><label for="mpt-district">Район Москвы</label><select id="mpt-district"><option value="">— выберите район —</option></select></div>
        <div id="mpt-ttk-wrap"><label for="mpt-ttk">Положение относительно ТТК <span style="opacity:.6">п. 1.2</span></label><select id="mpt-ttk"><option value="">— выберите —</option><option value="outside">За внешней границей ТТК</option><option value="inside">Внутри ТТК</option></select></div>
        <div><label id="mpt-area-label" for="mpt-area">Общая площадь МПТ, м²</label><input id="mpt-area" type="number" min="0" step="1" placeholder="10000"></div>
        <div><label for="mpt-parking">Парковки, м²</label><input id="mpt-parking" type="number" min="0" step="1" value="0"></div>
        <div><label for="mpt-garages">Гаражи, м²</label><input id="mpt-garages" type="number" min="0" step="1" value="0"></div>
        <div id="mpt-warehouse-wrap"><label for="mpt-warehouse">Склад внутри здания, м²</label><input id="mpt-warehouse" type="number" min="0" step="1" value="0"></div>
        <div id="mpt-yard-wrap"><label for="mpt-yard">Открытая складская площадка, м²</label><input id="mpt-yard" type="number" min="0" step="1" value="0"></div>
        <div id="mpt-rooms-wrap" class="mpt-hidden"><label for="mpt-rooms">Номерной фонд, м² <span style="opacity:.6">не менее 75%</span></label><input id="mpt-rooms" type="number" min="0" step="1" value="0"></div>
        <div><label for="mpt-kzatr">Кзатр <span style="opacity:.6">акт ДИиПП</span></label><input id="mpt-kzatr" type="number" min="0" step="0.00001" value="166.23078"></div>
        <div class="mpt-wide"><label><input id="mpt-mixed" type="checkbox" style="width:auto"> Назначение сразу по нескольким ВРИ из граф 2 и 3 (порог 5 000 м², п. 3.1.3)</label></div>
        <div id="mpt-ons-wrap" class="mpt-wide mpt-hidden">
          <div class="mpt-grid">
            <div><label for="mpt-ready">Готовность ОНС, %</label><input id="mpt-ready" type="number" min="0" max="99.99" step="0.1" value="0"></div>
            <div style="align-self:end"><label><input id="mpt-ons-date" type="checkbox" style="width:auto"> Право зарегистрировано не позднее 01.11.2019</label></div>
          </div>
        </div>
      </div>
      <p id="mpt-context-note" class="mpt-note" style="margin-top:10px"></p>
      <button id="mpt-calc" type="button">Рассчитать льготу</button>
      <div id="mpt-result" class="mpt-hidden" aria-live="polite">
        <div class="mpt-kpis">
          <div class="mpt-kpi"><small>Расчётная льгота</small><strong id="mpt-benefit">—</strong></div>
          <div class="mpt-kpi"><small>Sмпт в расчёте</small><strong id="mpt-eligible">—</strong></div>
          <div class="mpt-kpi"><small>Кмест</small><strong id="mpt-kmest">—</strong></div>
        </div>
        <div id="mpt-blockers" class="mpt-warnings mpt-hidden"></div>
        <div id="mpt-formula" class="mpt-formula"></div>
        <div id="mpt-warnings" class="mpt-warnings"></div>
      </div>
    </div>
  </details>
</template>
<script>
(function(){
  const q=id=>document.getElementById(id);
  const rub=v=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:0}).format(v||0);
  const num=(v,d=1)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(v||0);
  let meta=null;

  let host=null;
  function findVriHost(){
    // Панель ВРИ по имени, а не по угадыванию текста: прежний перебор
    // `.panel` находил первую попавшуюся — «Вводные», — и панель оседала на
    // чужой вкладке.
    const vri=document.getElementById('vri');
    if(vri && vri.classList.contains('panel')) return vri;
    const candidates=[...document.querySelectorAll('[role="tabpanel"],section,.card,.panel,.sheet,.tab-pane')];
    const direct=candidates.find(el=>el.id!=='mpt-benefit-panel' && /(^|\s)ВРИ(\s|$)/i.test((el.textContent||'').slice(0,800)) && el.querySelector('input,select,button'));
    return direct || document.querySelector('main') || document.body;
  }
  function revealHost(){
    // Открывать надо ту вкладку, где панель действительно лежит. Прежний код
    // жал «ВРИ» вслепую: панель оставалась на скрытой вкладке, и переход по
    // ?section=mpt показывал пустой экран.
    const panel=q('mpt-benefit-panel');
    const owner=panel&&panel.closest('.panel,[role="tabpanel"],.tab-pane');
    const id=owner&&owner.id?owner.id:'';
    if(!id) return;
    const tab=document.querySelector('.tab[data-tab="'+id+'"]')
      ||[...document.querySelectorAll('[role="tab"],button')].find(el=>el.getAttribute&&el.getAttribute('data-tab')===id);
    if(tab) try{tab.click();}catch(_e){}
  }
  function hostVisible(){
    const panel=q('mpt-benefit-panel');
    const owner=panel&&panel.closest('.panel,[role="tabpanel"],.tab-pane');
    return !owner||getComputedStyle(owner).display!=='none';
  }
  function mount(){
    if(q('mpt-benefit-panel')) return;
    const tpl=q('mpt-benefit-template');
    if(!tpl) return;
    host=findVriHost();
    host.appendChild(tpl.content.cloneNode(true));
    wire();
  }
  function sync(){
    if(!meta) return;
    const category=q('mpt-category').value, mode=q('mpt-mode').value;
    const hotel=category==='hotel';
    // ТТК — условие присвоения статуса (п. 1.2), а не множитель Кмест:
    // спрашиваем у всех, кроме гостиниц, а не у двух категорий в одной группе.
    q('mpt-ttk-wrap').classList.toggle('mpt-hidden',hotel);
    q('mpt-rooms-wrap').classList.toggle('mpt-hidden',!hotel);
    q('mpt-ons-wrap').classList.toggle('mpt-hidden',mode!=='ons');
    q('mpt-warehouse-wrap').classList.toggle('mpt-hidden',hotel);
    q('mpt-yard-wrap').classList.toggle('mpt-hidden',hotel);
    if(hotel){q('mpt-warehouse').value='0';q('mpt-yard').value='0';}
    if(hotel){
      q('mpt-area-label').textContent=mode==='reconstruction'
        ? 'Прирост площади допустимых помещений средства размещения, м²'
        : 'Площадь допустимых помещений средства размещения, м²';
    }else{
      q('mpt-area-label').textContent=mode==='reconstruction'?'Прирост общей площади МПТ, м²':'Общая площадь МПТ, м²';
    }
    q('mpt-context-note').textContent=category==='industrial'
      ? 'Приложение 3 исключает склады и складские площадки из производственного ВРИ: закрытый склад учитывается максимум в пределах 25% площади, открытая площадка, парковки и гаражи исключаются.'
      : hotel
        ? 'Гостиница — единственная категория, которой ТТК не мешает (п. 1.2). Номерной фонд должен быть не менее 75% площади (п. 4.2). Исключаются парковки и гаражи.'
        : 'Парковки, гаражи, склад внутри здания и открытая складская площадка исключаются из Sмпт.';
  }
  async function loadMeta(){
    const r=await fetch('/api/mpt/meta',{credentials:'same-origin'});
    if(!r.ok) throw new Error('Не удалось загрузить нормативный справочник МПТ');
    meta=await r.json();
    q('mpt-category').innerHTML=(meta.categories||[]).map(x=>`<option value="${x.value}">${x.label}</option>`).join('');
    q('mpt-district').innerHTML='<option value="">— выберите район —</option>'+(meta.districts||[]).map(x=>`<option value="${x}">${x}</option>`).join('');
    sync();
  }
  async function calculate(){
    const result=q('mpt-result'), warnings=q('mpt-warnings');
    warnings.textContent='Считаю…'; result.classList.remove('mpt-hidden');
    const payload={
      category:q('mpt-category').value,
      district:q('mpt-district').value,
      area_sqm:Number(q('mpt-area').value||0),
      mode:q('mpt-mode').value,
      ttk_position:q('mpt-ttk').value||null,
      parking_sqm:Number(q('mpt-parking').value||0),
      garages_sqm:Number(q('mpt-garages').value||0),
      warehouse_inside_sqm:Number(q('mpt-warehouse').value||0),
      warehouse_yard_sqm:Number(q('mpt-yard').value||0),
      hotel_rooms_sqm:Number(q('mpt-rooms').value||0),
      mixed_use:q('mpt-mixed').checked,
      kzatr:Number(q('mpt-kzatr').value||0)||undefined,
      ons_readiness_pct:Number(q('mpt-ready').value||0),
      ons_registered_before_2019_11_01:q('mpt-mode').value==='ons'?q('mpt-ons-date').checked:null
    };
    try{
      const r=await fetch('/api/mpt/calculate',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(payload)});
      const data=await r.json();
      if(!r.ok) throw new Error(data.detail||'Расчёт не выполнен');
      q('mpt-benefit').textContent=rub(data.benefit_rub);
      q('mpt-eligible').textContent=num(data.eligible_area_sqm)+' м²';
      q('mpt-kmest').textContent=num(data.kmest,2);
      const blockers=q('mpt-blockers');
      blockers.textContent=(data.blockers||[]).map(x=>'✕ '+x).join('\n');
      blockers.classList.toggle('mpt-hidden',!(data.blockers||[]).length);
      q('mpt-formula').textContent=data.formula+'\n'+data.kmest_source+'\n'+data.normative_snapshot;
      warnings.textContent=(data.warnings||[]).length?(data.warnings||[]).map(x=>'• '+x).join('\n'):'Расчёт выполнен без дополнительных предупреждений.';
    }catch(err){
      q('mpt-benefit').textContent='—';q('mpt-eligible').textContent='—';q('mpt-kmest').textContent='—';
      q('mpt-formula').textContent='';q('mpt-blockers').classList.add('mpt-hidden');
      warnings.textContent=err?.message||String(err);
    }
  }
  function wire(){
    ['mpt-category','mpt-mode','mpt-district','mpt-ttk'].forEach(id=>q(id)?.addEventListener('change',sync));
    q('mpt-calc')?.addEventListener('click',calculate);
    loadMeta().catch(err=>{q('mpt-context-note').textContent=err?.message||String(err);});
    const params=new URLSearchParams(location.search);
    if(params.get('section')==='mpt'){
      revealHost();
      const panel=q('mpt-benefit-panel');
      if(panel){
        panel.open=true;
        setTimeout(()=>{
          // Если вкладку открыть не удалось, панель осталась бы невидимой, а
          // человек по ссылке из бота увидел бы пустой экран. Скажем об этом
          // вслух, а не оставим гадать.
          if(!hostVisible()) q('mpt-context-note').textContent=
            'Панель МПТ открыта на вкладке, которая сейчас скрыта. Откройте вкладку «ВРИ».';
          panel.scrollIntoView({behavior:'smooth',block:'start'});
        },80);
      }
    }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount); else mount();
})();
</script>
'''


def inject_mpt_panel(page: str) -> str:
    page = str(page or "")
    if not page or _PAGE_MARKER in page:
        return page
    if "</body>" in page:
        return page.replace("</body>", _MPT_FRAGMENT + "\n</body>", 1)
    return page + _MPT_FRAGMENT


def _install_page(base: Any) -> None:
    if hasattr(base.core, "PAGE") and isinstance(base.core.PAGE, str):
        base.core.PAGE = inject_mpt_panel(base.core.PAGE)


def install(base: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @base.app.get("/api/mpt/meta")
    def mpt_meta() -> dict[str, Any]:
        return metadata()

    @base.app.post("/api/mpt/calculate")
    async def mpt_calculate(request: Request) -> dict[str, Any]:
        # Тело читается своим разбором, а не аргументом-моделью. NaN и
        # Infinity — валидные литералы для json.loads, и стандартный путь на
        # них ломался дважды: Infinity проходил проверку «> 0» и давал ответ
        # 200 с benefit_rub: null, а NaN валил уже сам обработчик ошибки —
        # он пытался положить nan в тело ответа 422 и получал 500 без
        # объяснения.
        try:
            payload = _strict_json(await request.body())
            if not isinstance(payload, dict):
                raise MptCalculationError("Тело запроса должно быть объектом JSON.")
            for field, reason in _REMOVED_FIELDS.items():
                if field in payload:
                    raise MptCalculationError(f"Поле «{field}» больше не применяется. {reason}")
            data = MptCalculateRequest(**payload)
            result = calculate_mpt_benefit(
                MptInput(**(data.model_dump() if hasattr(data, "model_dump") else data.dict()))
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=_first_error(exc)) from exc
        except (MptCalculationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.as_dict()

    _install_page(base)
    _install_bot(base)
    _INSTALLED = True
